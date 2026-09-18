"""Telling the drawing apart from the prose written on it.

A drafting note is ordinary English that happens to contain tag-shaped and
wire-shaped text.  On a real plot, one block of notes on the title sheet
produced three false findings on its own: the sentence *"(ie: 261201 FOR 1ST
ADDITIONAL WIRE / 261202 FOR THE SECOND...)"* yielded two wire numbers that do
not exist anywhere in the panel, and *"A WIRE ON SHEET 26 LINE 12"* yielded a
wrong sheet number for the whole page.

So every token carries a region role, and rules ignore the ones that are not
part of the drawing.  Two signals, because either alone leaves a gap:

1. **The sheet's role.**  An index, legend or bill-of-materials sheet is
   tabulation and prose end to end.
2. **Prose runs.**  A note is a long line of closely-spaced words; a tag on a
   schematic sits alone in space.  This catches notes blocks sitting on an
   otherwise ordinary drawing sheet, which the first signal cannot.

GUI-free, like its siblings.  Coordinates are the displayed-space ones
:func:`app.extraction.text_extract.extract_tokens` produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from . import sheet_role

# Region roles, sharing the rule library's vocabulary.
DRAWING = "drawing"
NOTES = "notes"
LEGEND = "legend"
INDEX = "index"
TITLEBLOCK = "titleblock"

REGION_ROLES = (DRAWING, NOTES, LEGEND, INDEX, TITLEBLOCK)

# Regions whose text is prose, tabulation or metadata rather than the drawing.
NON_DRAWING = frozenset({NOTES, LEGEND, INDEX, TITLEBLOCK})

# A sheet whose whole job is prose or tabulation: everything on it reads as
# that region, without needing to look at the layout.
SHEET_ROLE_REGIONS = {
    sheet_role.INDEX: INDEX,
    sheet_role.LEGEND: LEGEND,
    sheet_role.BOM: INDEX,
}


@dataclass
class TextRegionConfig:
    """Knobs for prose detection."""

    # Words this close together (in points) on one display row belong to the
    # same run. Roughly a couple of spaces at typical drawing text sizes.
    max_word_gap: float = 14.0
    # A run at least this long is a candidate for prose. Drawing callouts run
    # to three or four words; sentences run much longer.
    min_prose_words: int = 6
    # …but length alone is not enough. A PLC I/O list and a terminal-block
    # schedule are long, tightly-spaced rows of perfectly real wire numbers, and
    # masking those would hide genuine findings -- a false negative, which in an
    # audit is worse than noise. What actually separates a sentence from a table
    # is English: notes are written in it, drawing labels are not.
    min_function_words: int = 2
    # Display rows are banded before grouping, since glyph heights vary by a
    # fraction of a point within one printed line.
    row_band_tol: float = 6.0
    enable_prose_runs: bool = True
    # The title-block strip along the bottom-right of a sheet. Its text is
    # metadata about the drawing, not the drawing: an address's ZIP code parses
    # exactly like a wire number once variable-width numbering is on. The band
    # is deliberately tighter than the one sheet-number detection searches --
    # a two-column ladder's bottom rows sit around 0.85 of the page height and
    # must stay unmasked.
    titleblock_x_frac: float = 0.55
    titleblock_y_frac: float = 0.88


# English words that appear in drafting notes and carry no meaning on a
# drawing. Deliberately excludes short words and anything that doubles as
# electrical notation: "TO" and "FROM" label signal arrows, "A" is amps, "N" is
# neutral, "NO" is a normally-open contact. Including those made a perfectly
# ordinary off-page connector row -- "300140 to 70004 DRIVE POWER to 70006" --
# read as a sentence, which would have masked a real wire and hidden any
# finding about it.
FUNCTION_WORDS = frozenset("""
ALSO AND ANY ARE BEEN BEING BOTH EACH EITHER EVERY FOR HAVE INTO MUST ONLY
OTHER SHALL SHOULD SUCH THAN THAT THE THEIR THEM THERE THESE THEY THIS
UNLESS USED WHEN WHENEVER WHERE WHEREVER WHICH WHILE WILL WITH WITHOUT WOULD
""".split())


def _function_word_count(run) -> int:
    n = 0
    for _x, _idx, tok in run:
        word = "".join(ch for ch in str(getattr(tok, "text", "")).upper()
                       if ch.isalpha())
        if word in FUNCTION_WORDS:
            n += 1
    return n


def _row_key(y: float, tol: float) -> int:
    return int(float(y) // max(tol, 0.001))


def prose_token_ids(tokens: Iterable, config: Optional[TextRegionConfig] = None) -> set:
    """Ids of tokens that sit inside a run of closely-spaced words.

    Identity is by position in the sequence, so this works for any token object
    carrying ``x``, ``y`` and ``page``.
    """
    config = config or TextRegionConfig()
    items = list(tokens)
    if not config.enable_prose_runs:
        return set()

    rows: dict = {}
    for idx, tok in enumerate(items):
        key = (getattr(tok, "page", 0), _row_key(getattr(tok, "y", 0.0),
                                                 config.row_band_tol))
        rows.setdefault(key, []).append((float(getattr(tok, "x", 0.0)), idx, tok))

    prose: set = set()
    for _key, row in rows.items():
        row.sort()
        run = [row[0]]
        for prev, cur in zip(row, row[1:]):
            prev_x, _pi, prev_tok = prev
            cur_x, _ci, _ct = cur
            prev_width = _width(prev_tok)
            if (cur_x - (prev_x + prev_width)) <= config.max_word_gap:
                run.append(cur)
            else:
                _flush(run, prose, config)
                run = [cur]
        _flush(run, prose, config)
    return prose


def _width(token) -> float:
    """Printed width of a token, falling back to a character estimate.

    Producers that carry real extents give an exact gap between words; the
    estimate only has to be good enough to tell a sentence from two labels
    sitting apart.
    """
    w = float(getattr(token, "w", 0.0) or 0.0)
    if w > 0:
        return w
    return len(str(getattr(token, "text", "") or "")) * 5.0


def _flush(run: list, prose: set, config: TextRegionConfig) -> None:
    if len(run) < config.min_prose_words:
        return
    if _function_word_count(run) < config.min_function_words:
        return          # a long row of codes is a table, not a sentence
    for _x, idx, _tok in run:
        prose.add(idx)


def classify_tokens(tokens: Iterable, sheet_roles: Optional[dict] = None,
                    config: Optional[TextRegionConfig] = None,
                    page_sizes: Optional[dict] = None) -> list:
    """Region role per token, in the order given.

    ``sheet_roles`` maps page index to a sheet role; pages whose role makes the
    whole sheet prose win outright, and prose-run detection fills the gaps on
    ordinary drawing sheets.  ``page_sizes`` maps page index to ``(width,
    height)`` in the displayed space; with it, tokens in the title-block strip
    are marked ``titleblock`` -- without it that masking is skipped, since a
    band computed against unknown dimensions would land anywhere.
    """
    config = config or TextRegionConfig()
    sheet_roles = sheet_roles or {}
    page_sizes = page_sizes or {}
    items = list(tokens)
    prose = prose_token_ids(items, config)

    out: list = []
    for idx, tok in enumerate(items):
        page = getattr(tok, "page", 0)
        role = SHEET_ROLE_REGIONS.get(sheet_roles.get(page))
        if role is None:
            size = page_sizes.get(page)
            if size:
                width, height = size
                if (tok.x >= width * config.titleblock_x_frac
                        and tok.y >= height * config.titleblock_y_frac):
                    out.append(TITLEBLOCK)
                    continue
            role = NOTES if idx in prose else DRAWING
        out.append(role)
    return out
