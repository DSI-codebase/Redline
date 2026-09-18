"""Reading the title block's own fields.

A title block states things the drawing can be checked against: which sheet this
is, and which sheet comes next.  Both are claims, and both can disagree with
reality — on the sample set one sheet's drawing number reads ``EL2507777-003``
while its title block says ``THIS SHEET: 004``, and the sheet before it points
its ``NEXT`` at 004 accordingly, stepping straight over 003.

Fields are read by geometry, not by proximity in the flat text: labels sit in
one row and their values in the row beneath, and a naive "value to the right of
the label" search picks up schematic content instead.

GUI-free, like its siblings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

THIS_SHEET = "this_sheet"
NEXT_SHEET = "next_sheet"

# The label as printed, split across tokens: "THIS SHEET:" then "NEXT:".
_THIS_RE = re.compile(r"^THIS$", re.IGNORECASE)
_NEXT_RE = re.compile(r"^NEXT:?$", re.IGNORECASE)


@dataclass
class TitleBlockConfig:
    """Where a field's value sits relative to its label."""

    # The value row sits just below the label row.
    max_below: float = 22.0
    # Horizontal window around the label, as offsets from the label's left edge.
    # A field's value is printed under the start of its own label.
    left_window: float = -26.0
    right_window: float = 14.0
    value_digits: int = 3
    # Only look inside the title block.
    x_frac: float = 0.55
    y_frac: float = 0.72


@dataclass(frozen=True)
class TitleBlockFields:
    """What the title block says about this sheet."""

    this_sheet: str = ""
    next_sheet: str = ""

    @property
    def resolved(self) -> bool:
        return bool(self.this_sheet or self.next_sheet)


def _value_under(label, tokens, lo: float, hi: float,
                 config: TitleBlockConfig) -> str:
    """The digit token printed below ``label``, within a horizontal window."""
    best = None
    for t in tokens:
        text = str(t.text).strip()
        if not text.isdigit() or len(text) != config.value_digits:
            continue
        dy = t.y - label.y
        if not (0 < dy <= config.max_below):
            continue
        dx = t.x - label.x
        if not (lo <= dx <= hi):
            continue
        if best is None or dy < (best.y - label.y):
            best = t
    return str(best.text).strip() if best is not None else ""


def read_fields(tokens: Iterable, page_width: float = 0.0,
                page_height: float = 0.0,
                config: Optional[TitleBlockConfig] = None) -> TitleBlockFields:
    """Read ``THIS SHEET`` and ``NEXT`` from a page's tokens."""
    config = config or TitleBlockConfig()
    items = list(tokens)
    if page_width and page_height:
        x_min = page_width * config.x_frac
        y_min = page_height * config.y_frac
        items = [t for t in items if t.x >= x_min and t.y >= y_min]
    if not items:
        return TitleBlockFields()

    this_label = next((t for t in items if _THIS_RE.match(str(t.text).strip())), None)
    next_label = next((t for t in items if _NEXT_RE.match(str(t.text).strip())), None)

    this_value = next_value = ""
    if this_label is not None:
        this_value = _value_under(this_label, items, config.left_window,
                                  config.right_window, config)
    if next_label is not None:
        next_value = _value_under(next_label, items, config.left_window * 0.2,
                                  config.right_window, config)
    return TitleBlockFields(this_sheet=this_value, next_sheet=next_value)


def read_document_fields(doc, config: Optional[TitleBlockConfig] = None) -> dict:
    """``{page_index: TitleBlockFields}`` for a whole document."""
    from .text_extract import extract_tokens
    config = config or TitleBlockConfig()
    out: dict = {}
    for i in range(getattr(doc, "page_count", 0)):
        try:
            page = doc[i]
            out[i] = read_fields(extract_tokens(page, i), page.rect.width,
                                 page.rect.height, config)
        except Exception:
            out[i] = TitleBlockFields()
    return out
