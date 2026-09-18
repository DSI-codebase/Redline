"""Text-layer extraction via PyMuPDF.

Pulls words with bounding rects, font and color, and (best-effort) the
optional-content layer (OCG) each token belongs to.  Kept GUI-free.
"""

from __future__ import annotations

import re
from typing import Optional

import fitz  # PyMuPDF

from .wire_parser import Token, SOURCE_TEXT


# A page is considered "vector"/text-bearing when it exposes a non-trivial
# amount of extractable text.  Scanned pages fall back to OCR.
MIN_TEXT_CHARS = 8


def page_has_text(page: "fitz.Page") -> bool:
    """True when the page has a usable text layer (vs scanned raster)."""
    try:
        txt = page.get_text("text") or ""
    except Exception:
        return False
    return len(txt.strip()) >= MIN_TEXT_CHARS


def get_ocg_names(doc: "fitz.Document") -> dict:
    """Return ``{xref: name}`` for every optional-content group in the doc.

    Returns an empty dict when the document has no layers (most AutoCAD PDF
    plots), in which case jumper-layer handling is silently skipped downstream.
    """
    names: dict = {}
    try:
        ocgs = doc.get_ocgs() or {}
        for xref, info in ocgs.items():
            name = info.get("name") if isinstance(info, dict) else None
            if name:
                names[xref] = name
    except Exception:
        pass
    return names


def _build_mcid_layer_map(page: "fitz.Page", ocg_names: dict) -> dict:
    """Best-effort map of marked-content-id -> layer name for a page.

    AutoCAD plots almost never carry OCGs, so this normally returns ``{}`` and
    every token is reported with ``layer=None``.  When layers *are* present we
    try to associate text with them via the page's ``/Properties`` resource.
    """
    if not ocg_names:
        return {}
    mapping: dict = {}
    try:
        # The page /Properties dict maps a name -> OCG xref; marked content uses
        # those names.  This is heuristic and wrapped defensively.
        props = page.get_contents()  # noqa: F841 - presence check only
    except Exception:
        return {}
    return mapping


def extract_tokens(
    page: "fitz.Page",
    page_index: int,
    ocg_names: Optional[dict] = None,
) -> list:
    """Extract word-level :class:`Token` objects from a page.

    Coordinates are the word's top-left corner **in the page's displayed
    orientation** -- the same space the viewer, the annotations and the OCR path
    all use.

    ``get_text("words")`` reports in the *unrotated* space, which on a rotated
    plot is a different coordinate system entirely: an AutoCAD Electrical sheet
    is typically a 792x1224 page rotated 270 degrees for display as 1224x792, so
    a raw ``y`` of 1110 is a perfectly ordinary text position that lies off the
    bottom of a 792-point page. Left untransformed it sent every
    double-click-to-jump on a rotated drawing to the wrong place (often off the
    page), sorted "reading order" sideways, and would have placed audit findings
    nowhere near the thing they describe. ``page.rotation_matrix`` maps into the
    displayed space, matching what the search-highlight path already does.

    Pages with no rotation are unaffected: the matrix is the identity.
    """
    tokens: list = []
    try:
        words = page.get_text("words")
    except Exception:
        return tokens

    try:
        rot = page.rotation_matrix
    except Exception:
        rot = None

    for w in words:
        text = (w[4] or "").strip()
        if not text:
            continue
        if rot is not None:
            r = (fitz.Rect(w[0], w[1], w[2], w[3]) * rot).normalize()
            x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
        else:
            x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
        tokens.append(
            Token(
                text=text,
                x=float(x0),
                y=float(y0),
                page=page_index,
                layer=None,  # best-effort; populated only when OCGs exist
                source=SOURCE_TEXT,
                confidence=1.0,
                w=float(x1) - float(x0),
                h=float(y1) - float(y0),
            )
        )
    return tokens


# Common AutoCAD-Electrical title-block sheet patterns, e.g. "SHEET 300",
# "SHT 300", "SHEET 300 OF 420".  Best-effort only.
_SHEET_RE = re.compile(r"\b(?:SHEET|SHT)\.?\s*(?:NO\.?\s*)?(\d{1,4})", re.IGNORECASE)


def read_titleblock_sheet(page: "fitz.Page", sheet_width: int = 3) -> Optional[int]:
    """Best-effort title-block sheet number for cross-checking.

    Returns ``None`` when nothing convincing is found.  Never raises.
    """
    try:
        text = page.get_text("text") or ""
    except Exception:
        return None
    m = _SHEET_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def read_titleblock_sheet_label(page: "fitz.Page") -> Optional[str]:
    """Best-effort title-block sheet number as the *raw* string (e.g. ``"000"``).

    Two passes, both preserving leading zeros (a cover sheet reads ``"000"``):

    1. A ``SHEET 300`` / ``SHT 300`` keyword match in the page text.
    2. Failing that, the **bottom-right corner** heuristic for AutoCAD title
       blocks where the ``THIS SHEET:`` label is SHX (not in the text layer):
       the sheet number is the **lesser** of the few numeric tokens sitting in
       that corner. Conservative — gives up (returns ``None``) when the corner
       is empty or too ambiguous, so the editable Sheet column is the fallback.

    Returns ``None`` when nothing convincing is found; never raises.
    """
    try:
        text = page.get_text("text") or ""
    except Exception:
        text = ""
    m = _SHEET_RE.search(text)
    if m:
        return m.group(1)
    return _corner_sheet_label(page)


def _corner_sheet_label(page: "fitz.Page",
                        x_frac: float = 0.70, y_frac: float = 0.82,
                        max_candidates: int = 4) -> Optional[str]:
    """The lesser numeric token in the page's bottom-right corner, or ``None``."""
    try:
        r = page.rect
        words = page.get_text("words") or []
    except Exception:
        return None
    x_min = r.x0 + r.width * x_frac
    y_min = r.y0 + r.height * y_frac
    nums = []
    for w in words:
        try:
            x0, y0, tok = float(w[0]), float(w[1]), str(w[4]).strip()
        except (IndexError, ValueError, TypeError):
            continue
        if x0 >= x_min and y0 >= y_min and tok.isdigit() and 1 <= len(tok) <= 4:
            nums.append(tok)
    if not nums or len(nums) > max_candidates:
        return None              # nothing, or too ambiguous — leave it blank
    return min(nums, key=lambda s: int(s))


def extract_document_tokens(doc: "fitz.Document") -> list:
    """Extract tokens for every text-bearing page in a document.

    Pages without a text layer are reported via :func:`page_has_text` and left
    to the OCR fallback by the caller.
    """
    ocg_names = get_ocg_names(doc)
    tokens: list = []
    for i in range(doc.page_count):
        page = doc[i]
        if page_has_text(page):
            tokens.extend(extract_tokens(page, i, ocg_names))
    return tokens


# Aim each rendered tile at roughly this long-edge (px) - close to the size
# Claude works best with, so small wire numbers survive instead of being
# down-scaled away on a full-page render.
AI_TILE_TARGET_PX = 1500.0
AI_TILE_OVERLAP = 0.06          # tile overlap fraction (so boundary labels are read)


def _ai_results_to_tokens(results, page_index, origin_x, origin_y, zoom):
    """Convert Claude's tile results (bbox in tile-image pixels) to page-space
    :class:`Token` objects."""
    from .wire_parser import Token, SOURCE_AI
    out = []
    for r in results:
        if not isinstance(r, dict) or r.get("is_wire") is False:
            continue
        label = str(r.get("label", "")).strip()
        if not label:
            continue
        bbox = r.get("bbox") or [0, 0, 0, 0]
        try:
            x = origin_x + float(bbox[0]) / zoom
            y = origin_y + float(bbox[1]) / zoom
        except (TypeError, ValueError, IndexError):
            x = origin_x
            y = origin_y
        try:
            conf = float(r.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        out.append(Token(text=label, x=x, y=y, page=page_index,
                         source=SOURCE_AI, confidence=conf))
    return out


def _dedupe_ai_tokens(tokens, tol=8.0):
    """Drop near-duplicate AI tokens (same label at ~same spot) that arise from
    overlapping tiles, keeping the higher-confidence one."""
    kept = []
    for t in sorted(tokens, key=lambda z: -z.confidence):
        dup = False
        for k in kept:
            if k.text == t.text and abs(k.x - t.x) <= tol and abs(k.y - t.y) <= tol:
                dup = True
                break
        if not dup:
            kept.append(t)
    return kept


def ai_page(page: "fitz.Page", page_index: int, field_widths=(3, 2, 1),
            zero_pad: bool = True, model: str = "claude-opus-4-8",
            api_key: str = "", tiles: int = 2, should_cancel=None,
            on_tile=None) -> list:
    """Read wire-number labels from a scanned page using Claude vision.

    The page is split into an ``tiles`` x ``tiles`` grid (with a small overlap);
    each tile is rendered at full resolution and sent to Claude so small labels
    survive image down-scaling.  Tile-local bboxes are mapped back to page
    coordinates and overlap duplicates are removed.  Returns ``[]`` on failure.
    """
    from . import claude_api
    tiles = max(1, int(tiles))
    rect = page.rect
    W, H = float(rect.width), float(rect.height)
    tile_w, tile_h = W / tiles, H / tiles
    pad_x, pad_y = tile_w * AI_TILE_OVERLAP, tile_h * AI_TILE_OVERLAP
    # zoom so each (padded) tile's long edge ~= the target pixel size
    long_edge = max(tile_w + 2 * pad_x, tile_h + 2 * pad_y)
    zoom = max(1.0, min(6.0, AI_TILE_TARGET_PX / long_edge))

    tokens: list = []
    total_tiles = tiles * tiles
    done = 0
    for ry in range(tiles):
        for cx in range(tiles):
            if should_cancel is not None and should_cancel():
                return tokens
            x0 = max(0.0, cx * tile_w - pad_x)
            y0 = max(0.0, ry * tile_h - pad_y)
            x1 = min(W, (cx + 1) * tile_w + pad_x)
            y1 = min(H, (ry + 1) * tile_h + pad_y)
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                      clip=fitz.Rect(x0, y0, x1, y1), alpha=False)
                results = claude_api.read_wire_region(
                    pix, field_widths=field_widths, zero_pad=zero_pad,
                    model=model, api_key=api_key)
                tokens.extend(_ai_results_to_tokens(results, page_index, x0, y0, zoom))
            except Exception:
                pass
            done += 1
            if on_tile is not None:
                on_tile(done, total_tiles)
    return _dedupe_ai_tokens(tokens)


def _ai_component_results_to_tokens(results, page_index, origin_x, origin_y, zoom):
    """Convert Claude component-tile results to page-space :class:`Token`s."""
    from .wire_parser import Token, SOURCE_AI
    out = []
    for r in results:
        if not isinstance(r, dict) or r.get("is_component") is False:
            continue
        label = str(r.get("label", "")).strip()
        if not label:
            continue
        bbox = r.get("bbox") or [0, 0, 0, 0]
        try:
            x = origin_x + float(bbox[0]) / zoom
            y = origin_y + float(bbox[1]) / zoom
        except (TypeError, ValueError, IndexError):
            x, y = origin_x, origin_y
        try:
            conf = float(r.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        out.append(Token(text=label, x=x, y=y, page=page_index,
                         source=SOURCE_AI, confidence=conf))
    return out


def ai_page_components(page, page_index, families=(), model="claude-opus-4-8",
                       api_key="", tiles=2, should_cancel=None, on_tile=None):
    """Read component/device tags from a scanned page using Claude vision.

    Same tiling strategy as :func:`ai_page` (so small tags survive), but with the
    component-label prompt.  Returns ``[]`` on failure.
    """
    from . import claude_api
    tiles = max(1, int(tiles))
    rect = page.rect
    W, H = float(rect.width), float(rect.height)
    tile_w, tile_h = W / tiles, H / tiles
    pad_x, pad_y = tile_w * AI_TILE_OVERLAP, tile_h * AI_TILE_OVERLAP
    long_edge = max(tile_w + 2 * pad_x, tile_h + 2 * pad_y)
    zoom = max(1.0, min(6.0, AI_TILE_TARGET_PX / long_edge))

    tokens: list = []
    total_tiles = tiles * tiles
    done = 0
    for ry in range(tiles):
        for cx in range(tiles):
            if should_cancel is not None and should_cancel():
                return tokens
            x0 = max(0.0, cx * tile_w - pad_x)
            y0 = max(0.0, ry * tile_h - pad_y)
            x1 = min(W, (cx + 1) * tile_w + pad_x)
            y1 = min(H, (ry + 1) * tile_h + pad_y)
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                      clip=fitz.Rect(x0, y0, x1, y1), alpha=False)
                results = claude_api.read_component_region(
                    pix, families=families, model=model, api_key=api_key)
                tokens.extend(_ai_component_results_to_tokens(
                    results, page_index, x0, y0, zoom))
            except Exception:
                pass
            done += 1
            if on_tile is not None:
                on_tile(done, total_tiles)
    return _dedupe_ai_tokens(tokens)


def collect_component_tokens(doc: "fitz.Document", method: str = "ai",
                             ai_key: str = "", ai_model: str = "claude-opus-4-8",
                             ai_tiles: int = 2, families=(), ocr_zoom: float = 3.0,
                             progress=None, should_cancel=None,
                             ai_tile_progress=None) -> list:
    """Collect tokens for component-label detection.

    Text-bearing (vector) pages always use the text layer.  For scanned pages,
    ``method`` selects the engine: ``"ai"`` (Claude vision, tiled) or ``"ocr"``
    (Tesseract).  Degrades gracefully when the chosen engine is unavailable.
    """
    ocg_names = get_ocg_names(doc)
    tokens: list = []
    use_ai = False
    use_ocr = False
    if method == "ai":
        try:
            from . import claude_api
            use_ai = claude_api.available(ai_key)
        except Exception:
            use_ai = False
    elif method == "ocr":
        try:
            from . import ocr as _ocr
            use_ocr = _ocr.available()
        except Exception:
            use_ocr = False
    total = doc.page_count
    for i in range(total):
        if should_cancel is not None and should_cancel():
            break
        if progress is not None:
            progress(i + 1, total)
        page = doc[i]
        if page_has_text(page):
            tokens.extend(extract_tokens(page, i, ocg_names))
        elif use_ai:
            page_no = i + 1
            on_tile = ((lambda td, tt: ai_tile_progress(page_no, total, td, tt))
                       if ai_tile_progress is not None else None)
            tokens.extend(ai_page_components(
                page, i, families=families, model=ai_model, api_key=ai_key,
                tiles=ai_tiles, should_cancel=should_cancel, on_tile=on_tile))
        elif use_ocr:
            from . import ocr as _ocr
            tokens.extend(_ocr.ocr_page(page, i, zoom=ocr_zoom))
    return tokens


def collect_tokens(doc: "fitz.Document", ocr_enabled: bool = False,
                   ocr_zoom: float = 3.0, progress=None, should_cancel=None,
                   ai_enabled: bool = False, ai_key: str = "",
                   ai_model: str = "claude-opus-4-8", field_widths=(3, 2, 1),
                   zero_pad: bool = True, ai_tiles: int = 2,
                   ai_tile_progress=None) -> list:
    """Collect tokens from every page: text layer where present, OCR otherwise.

    For pages **without** a text layer (scanned drawings), Claude vision is used
    when ``ai_enabled`` and a key is available (it reads non-standard labels and
    vets what is a wire number); otherwise Tesseract OCR is used when
    ``ocr_enabled`` and the binary is present. Vector pages always use the text
    layer. ``progress(current_page, page_count)`` is called *before* each page so
    a UI can show "scanning page N" while a slow page runs; ``should_cancel()``
    is polled before each page. Everything degrades gracefully.
    """
    ocg_names = get_ocg_names(doc)
    tokens: list = []
    use_ocr = False
    if ocr_enabled:
        try:
            from . import ocr as _ocr
            use_ocr = _ocr.available()
        except Exception:
            use_ocr = False
    use_ai = False
    if ai_enabled:
        try:
            from . import claude_api
            use_ai = claude_api.available(ai_key)
        except Exception:
            use_ai = False
    total = doc.page_count
    for i in range(total):
        if should_cancel is not None and should_cancel():
            break
        if progress is not None:
            progress(i + 1, total)
        page = doc[i]
        if page_has_text(page):
            tokens.extend(extract_tokens(page, i, ocg_names))
        elif use_ai:
            page_no = i + 1
            on_tile = ((lambda td, tt: ai_tile_progress(page_no, total, td, tt))
                       if ai_tile_progress is not None else None)
            tokens.extend(ai_page(page, i, field_widths=field_widths,
                                  zero_pad=zero_pad, model=ai_model,
                                  api_key=ai_key, tiles=ai_tiles,
                                  should_cancel=should_cancel, on_tile=on_tile))
        elif use_ocr:
            from . import ocr as _ocr
            tokens.extend(_ocr.ocr_page(page, i, zoom=ocr_zoom))
    return tokens
