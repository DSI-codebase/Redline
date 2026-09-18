"""The line-number gutter down the side of a schematic sheet.

Every rung of a ladder drawing is numbered, and that number is printed in a
gutter as the sheet number followed by the line: ``300`` ``14``.  It is what
wire numbers and device tags encode, so recovering it turns "this text is
somewhere on sheet 300" into "this text is on sheet 300, line 14" -- which is
what a cross-reference has to match against.

Sheets carry one or two columns of line numbers, as the sample set's own title
page says: *"LINE #'S ARE ARRANGED VERTICALLY DOWN EACH SHEET IN (1) or (2)
COLUMNS."*  On a two-column sheet the left gutter runs 1-40 and the right 41-80
over the same vertical span, so a single printed row spans two different rungs.
A mark therefore belongs to the nearest gutter *to its left*, never simply to
the leftmost one.

GUI-free, like its siblings.  Coordinates are the displayed-space ones
:func:`app.extraction.text_extract.extract_tokens` produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class Rung:
    """One numbered line on a sheet."""

    page: int
    sheet: str
    line: int
    x: float          # left edge of the gutter entry
    y: float          # top edge

    @property
    def label(self) -> str:
        return f"{self.sheet}-{self.line:02d}"


@dataclass
class RungConfig:
    """Knobs for finding the gutter."""

    # A gutter entry is the sheet number immediately followed by the line
    # number, printed as two tokens with almost no gap.
    max_pair_gap: float = 8.0
    row_band_tol: float = 3.0
    line_digits: int = 2
    # Ignore anything further right than this fraction of the page: the title
    # block repeats the sheet number, and it is not a rung.
    max_x_frac: float = 0.92


def extract_rungs(tokens: Iterable, sheet_label: str, page_width: float = 0.0,
                  config: Optional[RungConfig] = None) -> list:
    """Every gutter entry on one page.

    ``sheet_label`` is the page's resolved sheet number; a gutter entry is only
    recognized when its first token matches it, which is what keeps a stray
    three-digit number from being read as a rung.
    """
    config = config or RungConfig()
    sheet_label = str(sheet_label or "")
    if not sheet_label:
        return []

    items = list(tokens)
    heads = [t for t in items if str(t.text).strip() == sheet_label]
    limit = page_width * config.max_x_frac if page_width else None

    out = []
    for head in heads:
        if limit is not None and head.x > limit:
            continue
        end = head.x + float(getattr(head, "w", 0.0) or 0.0)
        for other in items:
            text = str(other.text).strip()
            if len(text) != config.line_digits or not text.isdigit():
                continue
            if abs(other.y - head.y) > config.row_band_tol:
                continue
            gap = other.x - end
            if 0 <= gap <= config.max_pair_gap:
                out.append(Rung(page=head.page, sheet=sheet_label,
                                line=int(text), x=float(head.x),
                                y=float(head.y)))
                break
    out.sort(key=lambda r: (r.y, r.x))
    return out


def gutter_columns(rungs: Iterable, tolerance: float = 40.0) -> list:
    """The x positions of the gutters, left to right.

    Reported so a caller can tell a one-column sheet from a two-column one
    without re-deriving it.
    """
    xs = sorted({round(r.x) for r in rungs})
    columns: list = []
    for x in xs:
        if not columns or x - columns[-1] > tolerance:
            columns.append(x)
    return columns


def rung_at(rungs: Iterable, x: float, y: float,
            above_tol: float = 3.0) -> Optional[Rung]:
    """The rung a point falls within.

    Two steps, and both matter. Horizontally, the point belongs to the nearest
    gutter at or left of it: on a two-column sheet one printed row carries two
    different rungs, so taking the leftmost would file the whole right-hand
    column under left-hand line numbers.

    Vertically, a rung *spans* from its own gutter entry down to the next one.
    Drawing content sits below the number that labels it, often by a dozen
    points, so matching the gutter's own row would leave most marks unassigned.
    ``above_tol`` allows for text set a hair higher than its label.
    """
    rungs = list(rungs)
    if not rungs:
        return None

    columns = [r.x for r in rungs if r.x <= x]
    if not columns:
        return None
    column_x = max(columns)
    column = sorted((r for r in rungs if abs(r.x - column_x) < 1.0),
                    key=lambda r: r.y)

    best = None
    for r in column:
        if r.y <= y + above_tol:
            best = r
        else:
            break
    if best is None and column:
        # Content in the header band above the ladder -- a PLC module's rack
        # and slot annotation, say -- belongs to the first rung it sits over.
        # Handled as its own case rather than by loosening the tolerance, which
        # would pull ordinary marks down into the rung below them.
        first = column[0]
        pitch = (column[1].y - first.y) if len(column) > 1 else 16.0
        if first.y - y <= pitch:
            best = first
    return best


def index_by_line(rungs: Iterable) -> dict:
    """``{line number: Rung}`` for one page."""
    return {r.line: r for r in rungs}
