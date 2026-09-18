"""OCR fallback for scanned/raster pages (Phase 8).

Uses Tesseract via ``pytesseract``.  Optional: if the binary or the Python
wrapper is missing the module degrades gracefully (``available()`` returns
False) and the app continues with the text-layer pipeline only.
"""

from __future__ import annotations

from typing import Optional

import fitz  # PyMuPDF

from .wire_parser import Token, SOURCE_OCR

# Render scanned pages at a higher DPI so small wire numbers survive OCR.
DEFAULT_OCR_ZOOM = 3.0
# pytesseract confidence is 0..100; below this we treat a word as low-confidence
# (a candidate for AI disambiguation).
LOW_CONF = 55.0


def available() -> bool:
    """True when both ``pytesseract`` and the Tesseract binary are usable."""
    try:
        import pytesseract  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_page(page: "fitz.Page", page_index: int,
             zoom: float = DEFAULT_OCR_ZOOM,
             min_conf: float = 0.0) -> list:
    """OCR a single page and return word-level :class:`Token` objects.

    Token coordinates are mapped back to PDF points (so they line up with the
    text-layer pipeline and the spatial reading-order sort).  Returns an empty
    list when OCR is unavailable.
    """
    if not available():
        return []
    import pytesseract
    from PIL import Image
    import io

    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    tokens: list = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < min_conf:
            continue
        # pixel -> PDF point
        x = data["left"][i] / zoom
        y = data["top"][i] / zoom
        tokens.append(Token(
            text=text, x=float(x), y=float(y), page=page_index,
            layer=None, source=SOURCE_OCR,
            confidence=max(0.0, conf) / 100.0,
            w=float(data.get("width", [0] * n)[i] or 0) / zoom,
            h=float(data.get("height", [0] * n)[i] or 0) / zoom,
        ))
    return tokens


def is_low_confidence(token: Token) -> bool:
    return token.source == SOURCE_OCR and token.confidence * 100.0 < LOW_CONF


# --- best-effort table reconstruction from OCR geometry ---------------------


def words_to_structured(words, gutter_frac: float = 0.9,
                        min_table_rows: int = 2) -> dict:
    """Reconstruct a table (or prose) from positioned OCR words.

    ``words`` is a list of dicts ``{left, top, width, text, line}`` where
    ``line`` groups words on the same text line.  Columns are found from the
    vertical **whitespace gutters** that run between word blocks across the whole
    region; a gutter wider than ``gutter_frac × median word width`` separates two
    columns.  Returns the region-content shape used by the crop exporter::

        {"type": "table"|"text", "title": "", "rows": [[...]], "text": str}

    A region is called a *table* only when it has >=2 columns, >=2 rows, and at
    least half its rows fill more than one column; otherwise it is prose.
    """
    words = [w for w in words if str(w.get("text", "")).strip()]
    if not words:
        return {"type": "text", "title": "", "rows": [], "text": ""}

    lines: dict = {}
    for w in words:
        lines.setdefault(w["line"], []).append(w)
    line_ids = sorted(lines, key=lambda lid: min(x["top"] for x in lines[lid]))

    widths = sorted(int(w["width"]) for w in words)
    med_w = widths[len(widths) // 2] or 10
    gutter_min = max(10.0, gutter_frac * med_w)

    # merge covered x-intervals across all words, then split at wide gutters
    ivs = sorted([int(w["left"]), int(w["left"]) + int(w["width"])] for w in words)
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    boundaries = []
    for i in range(len(merged) - 1):
        if merged[i + 1][0] - merged[i][1] >= gutter_min:
            boundaries.append((merged[i][1] + merged[i + 1][0]) / 2.0)

    def col_of(x):
        c = 0
        for b in boundaries:
            if x >= b:
                c += 1
            else:
                break
        return c

    n_cols = len(boundaries) + 1
    grid = []
    multi = 0
    for lid in line_ids:
        cells = [""] * n_cols
        for w in sorted(lines[lid], key=lambda z: z["left"]):
            c = col_of(int(w["left"]))
            cells[c] = (cells[c] + " " + w["text"]).strip() if cells[c] else w["text"]
        grid.append(cells)
        if sum(1 for c in cells if c) >= 2:
            multi += 1

    n_rows = len(grid)
    is_table = (n_cols >= 2 and n_rows >= min_table_rows
                and multi >= max(2, n_rows / 2))
    if is_table:
        return {"type": "table", "title": "", "rows": grid, "text": ""}
    text = "\n".join(
        " ".join(w["text"] for w in sorted(lines[lid], key=lambda z: z["left"]))
        for lid in line_ids)
    return {"type": "text", "title": "", "rows": [], "text": text}


def ocr_structured(pix) -> dict:
    """OCR a rendered region and reconstruct a table/prose result.

    Returns the region-content dict (see :func:`words_to_structured`) or ``{}``
    when OCR is unavailable / fails so callers can fall back.
    """
    if not available():
        return {}
    import io
    import pytesseract
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception:
        return {}
    words = []
    n = len(data.get("text", []))
    for i in range(n):
        t = (data["text"][i] or "").strip()
        if not t:
            continue
        try:
            if float(data["conf"][i]) < 0:
                continue
        except (ValueError, TypeError):
            continue
        words.append({
            "left": int(data["left"][i]), "top": int(data["top"][i]),
            "width": int(data["width"][i]), "text": t,
            "line": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
        })
    return words_to_structured(words)
