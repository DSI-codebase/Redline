"""Off-page connectors: where a signal leaves a sheet, and where it arrives.

An AutoCAD Electrical schematic marks a signal crossing sheets with a labelled
arrow -- ``to 70004``, ``from 30014``, sometimes ``to 70004 PG.700`` with the
destination page spelled out, and sometimes ``TO LINE 30041``.  The number is a
sheet-and-line reference: ``70004`` is sheet 700, line 04.  A six-digit form is
a full wire number, whose first five digits are the same reference.

These are checkable because they come in pairs.  If sheet 300 line 14 says it
goes *to* sheet 700 line 04, then sheet 700 line 04 should say it comes *from*
sheet 300 line 14.  A missing counterpart is a signal that leaves somewhere and
arrives nowhere -- exactly the kind of thing that survives a visual review of a
forty-sheet set.

GUI-free, like its siblings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .rung import rung_at

TO = "to"
FROM = "from"

_DIRECTION_RE = re.compile(r"^(TO|FROM)$", re.IGNORECASE)
_LINE_WORD_RE = re.compile(r"^LINE$", re.IGNORECASE)
_PAGE_HINT_RE = re.compile(r"^PG\.?\s*(\d{1,4})$", re.IGNORECASE)


@dataclass(frozen=True)
class SignalArrow:
    """One off-page connector label."""

    page: int
    direction: str            # "to" | "from"
    target_sheet: int
    target_line: int
    # The sheet and line the arrow itself sits on, from the gutter.
    source_sheet: str = ""
    source_line: Optional[int] = None
    # An explicit "PG.700" beside the reference, when the drawing spells it out.
    target_page_hint: str = ""
    raw: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    @property
    def target(self) -> str:
        return f"{self.target_sheet:03d}-{self.target_line:02d}"

    @property
    def source(self) -> str:
        if self.source_line is None:
            return self.source_sheet or ""
        return f"{self.source_sheet}-{self.source_line:02d}"

    @property
    def counterpart_direction(self) -> str:
        return FROM if self.direction == TO else TO


@dataclass
class SignalArrowConfig:
    """Knobs for arrow detection."""

    sheet_width: int = 3
    line_width: int = 2
    # How far right of the marker word the reference may sit, and how far the
    # two may differ vertically and still be one label.
    max_gap: float = 40.0
    row_band_tol: float = 4.0
    # A reference is sheet+line, or a full wire number (sheet+line+index).
    min_digits: int = 5
    max_digits: int = 6

    @property
    def ref_width(self) -> int:
        return self.sheet_width + self.line_width


def _decode(text: str, config: SignalArrowConfig):
    """``(sheet, line)`` from a reference, or ``None``."""
    if not text.isdigit():
        return None
    if not (config.min_digits <= len(text) <= config.max_digits):
        return None
    sw = config.sheet_width
    try:
        return int(text[:sw]), int(text[sw:sw + config.line_width])
    except ValueError:
        return None


def extract_arrows(tokens: Iterable, rungs=(), sheet_label: str = "",
                   config: Optional[SignalArrowConfig] = None) -> list:
    """Every off-page connector label on one page.

    ``rungs`` come from :mod:`app.extraction.rung`; with them each arrow knows
    which line it sits on, which is what makes the pairing checkable.
    """
    config = config or SignalArrowConfig()
    items = sorted(tokens, key=lambda t: (t.y, t.x))
    rungs = list(rungs)
    out = []

    for i, tok in enumerate(items):
        m = _DIRECTION_RE.match(str(tok.text).strip())
        if not m:
            continue
        direction = m.group(1).lower()
        end = tok.x + float(getattr(tok, "w", 0.0) or 0.0)

        # The reference is the next token to the right on the same printed row,
        # optionally after the word LINE.
        reference = None
        cursor = end
        for other in items[i + 1:]:
            if abs(other.y - tok.y) > config.row_band_tol:
                continue
            if other.x < cursor - 1:
                continue
            if other.x - cursor > config.max_gap:
                break
            text = str(other.text).strip()
            if _LINE_WORD_RE.match(text):
                cursor = other.x + float(getattr(other, "w", 0.0) or 0.0)
                continue
            decoded = _decode(text, config)
            if decoded is None:
                break
            reference = (other, text, decoded)
            break
        if reference is None:
            continue

        ref_tok, raw, (target_sheet, target_line) = reference

        # An explicit page hint, when the drawing spells the destination out.
        hint = ""
        ref_end = ref_tok.x + float(getattr(ref_tok, "w", 0.0) or 0.0)
        for other in items:
            if abs(other.y - ref_tok.y) > config.row_band_tol:
                continue
            gap = other.x - ref_end
            if 0 <= gap <= config.max_gap:
                hm = _PAGE_HINT_RE.match(str(other.text).strip())
                if hm:
                    hint = hm.group(1)
                    break

        rung = rung_at(rungs, tok.x, tok.y) if rungs else None
        out.append(SignalArrow(
            page=tok.page, direction=direction,
            target_sheet=target_sheet, target_line=target_line,
            source_sheet=(rung.sheet if rung else str(sheet_label or "")),
            source_line=(rung.line if rung else None),
            target_page_hint=hint, raw=f"{tok.text} {raw}",
            x=float(tok.x), y=float(tok.y),
            w=float(ref_end - tok.x),
            h=float(getattr(tok, "h", 0.0) or 0.0),
        ))
    return out


def dedupe(arrows: Iterable) -> list:
    """Collapse arrows that say the same thing on the same rung.

    A connector is commonly drawn twice on one row -- once at each end of the
    symbol -- so the same label appears more than once. That is one signal, not
    two, and counting it twice would make a missing counterpart look satisfied.
    """
    seen = {}
    for a in arrows:
        key = (a.page, a.source_line, a.direction, a.target_sheet, a.target_line)
        seen.setdefault(key, a)
    return list(seen.values())
