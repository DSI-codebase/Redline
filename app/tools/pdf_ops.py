"""PDF manipulation operations (GUI-free), reimplemented on PyMuPDF.

This merges the legacy tkinter utility's functions (split / combine / insert /
swap / delete / rotate / crop / PDF->Word) onto the app's existing PyMuPDF
stack, plus a robust region-based sheet-number extractor that replaces the old
full-page regex.  Every long operation accepts optional ``progress(done,total)``
and ``cancel()`` callbacks so the GUI can run it on a worker thread.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import fitz  # PyMuPDF

# The one guard, imported rather than reimplemented. A page tool has no Document
# and no sidecar, so it can only ask "is this my own input" -- but the ANSWER has
# to be the same everywhere, and a second same-file comparison here would be a
# second opinion about which two paths are one file.
from ..model.storage import refuse_overwriting_input, refuse_protected

# sheet-number parse modes
SHEET_EXACT = "exact"
SHEET_FIRST_NUMBER = "first_number"
SHEET_SMALLER_OF_TWO = "smaller_of_two"


def _guard_out(out_path: str, *inputs: Optional[str]) -> None:
    """Every write in this module goes through here first.

    Two questions, and they are different:

    * **Is this my own input?** Measured to destroy real files -- with the
      output aimed at a source, ``extract_pages`` took a four-page drawing to
      one page, ``split_ranges`` (merge=True) took five to two, and
      ``combine_pdfs`` replaced its input with the combination. PyMuPDF refuses
      SOME of these itself (``save to original must be incremental``) but only
      where the write comes from the very document that opened the file; every
      one of these builds a NEW document, so that check never fires.
    * **Is this a drawing under review?** A page tool has no Document, but a
      drawing that carries marks in DSI Redline is identifiable from its
      sidecar, and destroying one is the same loss as destroying an original.
      Measured: ``rotate_pdf(a.pdf, victim.pdf, 90)`` replaced a four-page
      drawing with a three-page rotated copy of an unrelated file, silently.

    What is NOT covered, stated rather than implied: a PDF this app has never
    opened is indistinguishable from a stale export, and the save dialog has
    already asked about replacing it. Redline protects what it can identify.
    """
    refuse_overwriting_input(out_path, *inputs)
    refuse_protected(out_path)


def _base_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _safe(text: str) -> str:
    """Sanitise a string for use in a filename."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_") or "x"


# --- page-range parsing -----------------------------------------------------


def parse_page_ranges(spec: str, max_page: Optional[int] = None) -> list:
    """Parse a 1-based page spec like ``"1,3,5-7"`` into sorted 0-based indices."""
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
            if start > end:
                start, end = end, start
            out.update(range(start, end + 1))
        else:
            out.add(int(part))
    pages = sorted(p - 1 for p in out if p >= 1)
    if max_page is not None:
        pages = [p for p in pages if p < max_page]
    return pages


def pages_to_spec(pages) -> str:
    """Compact a list of 0-based page indices into a 1-based spec ("1,3,5-7").

    The inverse of :func:`parse_page_ranges`; used to keep a visual selection
    and its page-spec text box in sync.
    """
    nums = sorted({int(p) + 1 for p in pages if int(p) >= 0})
    if not nums:
        return ""
    parts = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


# --- sheet-number parsing ---------------------------------------------------


def sheet_from_text(text: str, mode: str = SHEET_FIRST_NUMBER) -> str:
    """Derive a sheet identifier from text read out of a title-block box."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    if mode == SHEET_EXACT:
        return text
    nums = re.findall(r"\d+", text)
    if mode == SHEET_SMALLER_OF_TWO:
        if len(nums) >= 2:
            return str(min(int(n) for n in nums))
        return nums[0] if nums else ""
    # first_number (default)
    return nums[0] if nums else ""


# --- sheet-number regions ---------------------------------------------------


@dataclass
class SheetRegion:
    """A title-block box that applies to a contiguous page range (0-based,
    inclusive)."""
    start: int
    end: int
    rect: tuple  # (x0, y0, x1, y1) in page (visual) points


def region_for_page(regions: Iterable[SheetRegion], page: int) -> Optional[SheetRegion]:
    """Return the region covering ``page`` (last one wins on overlap)."""
    found = None
    for r in regions:
        if r.start <= page <= r.end:
            found = r
    return found


def extract_sheet_numbers(doc: "fitz.Document", regions: Iterable[SheetRegion],
                          mode: str = SHEET_FIRST_NUMBER, ocr: bool = False,
                          ai: bool = False, ai_key: str = "",
                          ai_model: str = "claude-opus-4-8",
                          progress: Optional[Callable] = None,
                          cancel: Optional[Callable] = None) -> dict:
    """Read the sheet number from each page's assigned box.

    Returns ``{page_index: sheet_string}`` ("" when nothing was read).  Each box
    ``rect`` is in the viewer's *visual* (rotated) coordinates; the per-page read
    (text layer, then OCR / AI) is delegated to :func:`read_region_text`, which
    derotates the box for the text-layer read.
    """
    regions = list(regions)
    out: dict = {}
    total = doc.page_count
    for i in range(total):
        if cancel is not None and cancel():
            break
        if progress is not None:
            progress(i + 1, total)
        reg = region_for_page(regions, i)
        if reg is None:
            out[i] = ""
            continue
        text = read_region_text(doc[i], reg.rect, ocr=ocr, ai=ai,
                                ai_key=ai_key, ai_model=ai_model)
        out[i] = sheet_from_text(text, mode)
    return out


def read_region_text(page, rect, ocr: bool = False, ai: bool = False,
                     ai_key: str = "", ai_model: str = "") -> str:
    """Read the raw text inside a title-block box on one page.

    ``rect`` (a ``fitz.Rect`` or an ``(x0, y0, x1, y1)`` tuple) is the viewer's
    box in **visual** (rotated) page coordinates — the same space as
    ``page.rect`` and ``get_pixmap(clip=...)``. PyMuPDF's ``get_text(clip=...)``
    wants the clip in the page's *unrotated* coordinate space, so the visual box
    is multiplied by ``page.derotation_matrix`` first (identity on unrotated
    pages). The pixmap-based OCR / AI fallbacks keep the *visual* rect.

    Both the wizard preview and the actual split call this one function, so the
    "Text read from the box" preview and the split always agree — previously the
    preview skipped the derotation and showed "(nothing found)" on rotated pages
    (which AutoCAD plots almost always are) even though the split read fine.
    Returns the raw string.
    """
    rect_vis = rect if isinstance(rect, fitz.Rect) else fitz.Rect(*rect)
    text = ""
    try:
        clip = rect_vis * page.derotation_matrix   # get_text wants unrotated coords
        clip.normalize()
        text = page.get_text("text", clip=clip).strip()
    except Exception:
        text = ""
    if not text and ocr:
        text = _ocr_text_in_rect(page, rect_vis)   # get_pixmap wants visual coords
    if not text and ai:
        text = _ai_text_in_rect(page, rect_vis, ai_key, ai_model)
    return text


def _ocr_text_in_rect(page, rect, zoom: float = 3.0) -> str:
    try:
        from ..extraction import ocr as _ocr
        if not _ocr.available():
            return ""
        import pytesseract
        from PIL import Image
        import io
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return (pytesseract.image_to_string(img) or "").strip()
    except Exception:
        return ""


def _ai_text_in_rect(page, rect, api_key, model) -> str:
    try:
        from ..extraction import claude_api
        if not claude_api.available(api_key):
            return ""
        pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0), clip=rect, alpha=False)
        rows = claude_api.read_text_region(pix, api_key=api_key, model=model)
        return (rows or "").strip()
    except Exception:
        return ""


# --- split ------------------------------------------------------------------


def split_pdf(src: str, out_dir: str, naming: str = "page",
              regions: Optional[Iterable[SheetRegion]] = None,
              mode: str = SHEET_FIRST_NUMBER, ocr: bool = False, ai: bool = False,
              ai_key: str = "", ai_model: str = "claude-opus-4-8",
              progress: Optional[Callable] = None,
              cancel: Optional[Callable] = None) -> list:
    """Split a PDF into one file per page, named by page number or sheet number.

    Returns the list of written paths.  For ``naming='sheet'`` the per-page boxes
    in ``regions`` are read to get the sheet id; duplicates get a ``_2`` suffix.
    """
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(src)
    try:
        base = _base_name(src)
        n = doc.page_count
        width = max(2, len(str(n)))
        sheets = {}
        if naming == "sheet":
            sheets = extract_sheet_numbers(
                doc, regions or [], mode=mode, ocr=ocr, ai=ai,
                ai_key=ai_key, ai_model=ai_model)
        written: list = []
        used: dict = {}
        for i in range(n):
            if cancel is not None and cancel():
                break
            if progress is not None:
                progress(i + 1, n)
            if naming == "sheet":
                sheet = sheets.get(i) or ""
                if sheet:
                    tag = _safe(sheet)
                    if tag.isdigit():
                        tag = tag.zfill(3)
                else:
                    tag = f"page{(i + 1):0{width}d}"  # fall back to page number
                count = used.get(tag, 0) + 1
                used[tag] = count
                suffix = "" if count == 1 else f"_{count}"
                name = f"{base}-sheet{tag}{suffix}.pdf"
            else:
                name = f"{base}-page{(i + 1):0{width}d}.pdf"
            out = fitz.open()
            out.insert_pdf(doc, from_page=i, to_page=i)
            path = os.path.join(out_dir, name)
            _guard_out(path, src)
            out.save(path)
            out.close()
            written.append(path)
        return written
    finally:
        doc.close()


# --- extract / range split (visual page selection) --------------------------


def extract_pages(src: str, out: str, pages, merge: bool = True,
                  progress: Optional[Callable] = None,
                  cancel: Optional[Callable] = None) -> list:
    """Pull a chosen set of pages out of a PDF.

    ``pages`` is an iterable of 0-based page indices (order preserved, de-duped).
    With ``merge=True`` they are written into a single PDF at ``out`` (a file
    path).  With ``merge=False`` ``out`` is a folder and each page is written to
    its own ``<base>-pageNN.pdf``.  Returns the list of written paths.
    """
    seen = set()
    ordered = []
    for p in pages:
        p = int(p)
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    if not ordered:
        raise ValueError("No pages selected.")
    # MEASURED to destroy its own source: extract_pages(src, src, [0]) took a
    # four-page drawing to one page and returned normally. It builds a NEW
    # fitz.Document from the pages it read, so PyMuPDF's own
    # "save to original must be incremental" check never fires -- that check
    # only sees a save from the document that opened the file.
    if merge:
        _guard_out(out, src)          # `out` is a FOLDER when merge=False
    doc = fitz.open(src)
    try:
        n = doc.page_count
        ordered = [p for p in ordered if 0 <= p < n]
        if not ordered:
            raise ValueError("No valid pages selected.")
        base = _base_name(src)
        width = max(2, len(str(n)))
        total = len(ordered)
        if merge:
            picked = fitz.open()
            for i, p in enumerate(ordered):
                if cancel is not None and cancel():
                    break
                if progress is not None:
                    progress(i + 1, total)
                picked.insert_pdf(doc, from_page=p, to_page=p)
            picked.save(out)
            picked.close()
            return [out]
        os.makedirs(out, exist_ok=True)
        written: list = []
        for i, p in enumerate(ordered):
            if cancel is not None and cancel():
                break
            if progress is not None:
                progress(i + 1, total)
            one = fitz.open()
            one.insert_pdf(doc, from_page=p, to_page=p)
            path = os.path.join(out, f"{base}-page{(p + 1):0{width}d}.pdf")
            _guard_out(path, src)
            one.save(path)
            one.close()
            written.append(path)
        return written
    finally:
        doc.close()


def split_ranges(src: str, out: str, ranges, merge: bool = False,
                 progress: Optional[Callable] = None,
                 cancel: Optional[Callable] = None) -> list:
    """Split a PDF into the given page ranges.

    ``ranges`` is an iterable of ``(start, end)`` 0-based inclusive tuples.  Each
    range becomes one file ``<base>-range<a>-<b>.pdf`` in the ``out`` folder;
    with ``merge=True`` every range is concatenated into the single PDF ``out``
    (a file path).  Returns the written paths.
    """
    if merge:
        # MEASURED: split_ranges(src, src, [(1, 2)], merge=True) took a
        # five-page drawing to two pages. `out` is a FOLDER when merge=False,
        # and each file written into it is guarded at its own save below.
        _guard_out(out, src)
    norm = []
    for a, b in ranges:
        a, b = int(a), int(b)
        if a > b:
            a, b = b, a
        norm.append((a, b))
    if not norm:
        raise ValueError("No ranges defined.")
    doc = fitz.open(src)
    try:
        n = doc.page_count
        norm = [(max(0, a), min(n - 1, b)) for a, b in norm if a < n and b >= 0]
        if not norm:
            raise ValueError("No valid ranges.")
        base = _base_name(src)
        width = max(2, len(str(n)))
        total = len(norm)
        if merge:
            merged = fitz.open()
            for i, (a, b) in enumerate(norm):
                if cancel is not None and cancel():
                    break
                if progress is not None:
                    progress(i + 1, total)
                merged.insert_pdf(doc, from_page=a, to_page=b)
            merged.save(out)
            merged.close()
            return [out]
        os.makedirs(out, exist_ok=True)
        written: list = []
        for i, (a, b) in enumerate(norm):
            if cancel is not None and cancel():
                break
            if progress is not None:
                progress(i + 1, total)
            part = fitz.open()
            part.insert_pdf(doc, from_page=a, to_page=b)
            name = (f"{base}-range{(a + 1):0{width}d}-{(b + 1):0{width}d}.pdf"
                    if b > a else f"{base}-page{(a + 1):0{width}d}.pdf")
            path = os.path.join(out, name)
            _guard_out(path, src)
            part.save(path)
            part.close()
            written.append(path)
        return written
    finally:
        doc.close()


# --- combine ----------------------------------------------------------------


def _numeric_key(filename: str):
    m = re.search(r"\d+", os.path.basename(filename))
    return (int(m.group()) if m else float("inf"), os.path.basename(filename).lower())


def combine_pdfs(items, out_path: str, progress: Optional[Callable] = None,
                 cancel: Optional[Callable] = None) -> str:
    """Combine PDFs into one file.

    ``items`` is either a directory (its *.pdf sorted by the number in each
    filename, like the legacy tool) or an explicit ordered list of file paths.
    """
    if isinstance(items, str) and os.path.isdir(items):
        files = [os.path.join(items, f) for f in os.listdir(items)
                 if f.lower().endswith(".pdf")]
        files.sort(key=_numeric_key)
    else:
        files = list(items)
    # MEASURED to destroy one of its own inputs: combine_pdfs([src, other], src)
    # replaced a four-page drawing with the six-page combination. Same mechanism
    # as extract_pages -- a fresh document is built, so the library check never
    # fires. Every input is checked, not just the first: the dialog can add a
    # whole folder, and the output is typed by hand.
    _guard_out(out_path, *files)
    merged = fitz.open()
    try:
        total = len(files)
        for i, f in enumerate(files):
            if cancel is not None and cancel():
                break
            if progress is not None:
                progress(i + 1, total)
            src = fitz.open(f)
            merged.insert_pdf(src)
            src.close()
        merged.save(out_path)
        return out_path
    finally:
        merged.close()


# --- insert / swap / delete / rotate ----------------------------------------


def insert_pdf(target: str, insert: str, out_path: str, index: int) -> str:
    """Insert ``insert`` into ``target`` before 0-based ``index`` (0..len)."""
    _guard_out(out_path, target, insert)
    doc = fitz.open(target)
    try:
        index = max(0, min(int(index), doc.page_count))
        ins = fitz.open(insert)
        doc.insert_pdf(ins, start_at=index)
        ins.close()
        doc.save(out_path)
        return out_path
    finally:
        doc.close()


def swap_page(src: str, new_page_pdf: str, out_path: str, index: int) -> str:
    """Replace the page at 0-based ``index`` with the (single) page of
    ``new_page_pdf``."""
    _guard_out(out_path, src, new_page_pdf)
    doc = fitz.open(src)
    try:
        if not (0 <= index < doc.page_count):
            raise IndexError("Page index out of range.")
        new = fitz.open(new_page_pdf)
        if new.page_count != 1:
            new.close()
            raise ValueError("The replacement PDF must have exactly one page.")
        doc.insert_pdf(new, start_at=index)        # new page now at `index`
        doc.delete_page(index + 1)                 # remove the original
        new.close()
        doc.save(out_path)
        return out_path
    finally:
        doc.close()


def delete_pages(src: str, out_path: str, spec: str) -> str:
    """Remove the pages named by a 1-based spec like ``"1,3,5-7"``."""
    _guard_out(out_path, src)
    doc = fitz.open(src)
    try:
        pages = parse_page_ranges(spec, max_page=doc.page_count)
        if not pages:
            raise ValueError("No valid pages to remove.")
        if len(pages) >= doc.page_count:
            raise ValueError("Refusing to delete every page.")
        doc.delete_pages(pages)
        doc.save(out_path)
        return out_path
    finally:
        doc.close()


def rotate_pdf(src: str, out_path: str, angle: int, pages=None) -> str:
    """Rotate pages by ``angle`` (added to current rotation). ``pages`` is an
    optional iterable of 0-based indices (default: all)."""
    _guard_out(out_path, src)
    doc = fitz.open(src)
    try:
        targets = range(doc.page_count) if pages is None else pages
        for i in targets:
            if 0 <= i < doc.page_count:
                p = doc[i]
                p.set_rotation((p.rotation + int(angle)) % 360)
        doc.save(out_path)
        return out_path
    finally:
        doc.close()


def rotate_pdf_map(src: str, out_path: str, page_angles: dict,
                   progress: Optional[Callable] = None,
                   cancel: Optional[Callable] = None) -> str:
    """Rotate pages by individual deltas.

    ``page_angles`` maps a 0-based page index to a delta (added to the page's
    current rotation).  Pages absent from the map are left untouched.  Used by
    the visual rotate tool, where each page can carry its own ↺/↻ preview.
    """
    _guard_out(out_path, src)
    doc = fitz.open(src)
    try:
        items = [(int(i), int(a)) for i, a in page_angles.items()
                 if a and 0 <= int(i) < doc.page_count]
        total = max(1, len(items))
        for done, (i, a) in enumerate(items, 1):
            if cancel is not None and cancel():
                break
            if progress is not None:
                progress(done, total)
            p = doc[i]
            p.set_rotation((p.rotation + a) % 360)
        doc.save(out_path)
        return out_path
    finally:
        doc.close()


# --- crop -> PNG ------------------------------------------------------------


def crop_regions_to_png(src: str, out_dir: str, regions_by_page: dict,
                        zoom: float = 3.0, progress: Optional[Callable] = None,
                        cancel: Optional[Callable] = None) -> list:
    """Render each region (``{page_index: [rect, ...]}``, rects in page points)
    to a PNG.  Returns the written paths."""
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(src)
    try:
        base = _base_name(src)
        written: list = []
        items = [(pg, r) for pg, rects in regions_by_page.items() for r in rects]
        total = len(items)
        done = 0
        for pg in sorted(regions_by_page):
            page = doc[pg]
            for ridx, rect in enumerate(regions_by_page[pg], 1):
                if cancel is not None and cancel():
                    return written
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                      clip=fitz.Rect(*rect), alpha=False)
                path = os.path.join(out_dir, f"{base}_pg{pg + 1}_r{ridx}.png")
                # A .png cannot be a PDF this app protects and cannot be the
                # source, so this can never fire -- present so the AST gate
                # reads "every writer is guarded" without an exception list,
                # which is a list that goes stale the first time somebody
                # forgets to add to it.
                _guard_out(path, src)
                pix.save(path)
                written.append(path)
                done += 1
                if progress is not None:
                    progress(done, total)
        return written
    finally:
        doc.close()


# --- PDF -> Word ------------------------------------------------------------


def pdf_to_docx(src: str, out_path: str, progress: Optional[Callable] = None) -> str:
    """Convert a PDF to .docx via pdf2docx (raises if pdf2docx is unavailable)."""
    # A .docx destination cannot be a PDF this app protects, so only the
    # own-input half can fire -- kept for uniformity, because the next writer
    # added here should not have to decide which half applies.
    _guard_out(out_path, src)
    from pdf2docx import Converter
    cv = Converter(src)
    try:
        cv.convert(out_path)
    finally:
        cv.close()
    return out_path
