"""Wire-number detection, parsing, and classification.

This module is intentionally free of any GUI (Qt) dependency so the core
extraction logic can be unit-tested in isolation.

Wire-number encoding (configurable field widths)::

    [ S S S ][ R R ][ W ]
      sheet    rung   wire-index-on-rung (0-based)

Default widths: sheet=3, rung=2, wire-index=1 -> 6 digits total.

Worked example used by the test-suite: the second wire on rung 14 of sheet
432 -> ``432141`` (sheet ``432``, rung ``14``, wire index ``1`` because the
index is 0-based).  The first wire on that rung -> ``432140``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

# --- classification constants ----------------------------------------------

TYPE_CONFORMING = "conforming"
TYPE_FIXED = "fixed"        # a.k.a. "fixed/OEM"
TYPE_JUMPER = "jumper"

SOURCE_TEXT = "text"
SOURCE_OCR = "ocr"
SOURCE_AI = "ai"

FLAG_SHEET_MISMATCH = "sheet_mismatch"


# --- configuration ----------------------------------------------------------


@dataclass
class WireConfig:
    """All knobs that influence wire-number detection / parsing.

    Field widths and zero-padding are user-configurable in Settings; the
    parser receives a fully-resolved ``WireConfig`` so it never reads QSettings
    directly.
    """

    sheet_width: int = 3
    rung_width: int = 2
    wire_width: int = 1
    zero_pad: bool = True
    # When set, this regex is used to recognise a *complete* wire label instead
    # of the derived ``^\d{total_width}$`` pattern.  Use a capturing-free,
    # anchored pattern, e.g. ``^\d{6}$``.
    regex_override: str = ""
    # Cross-check each label's first-N digits against a *resolved* sheet number.
    # Drawings frequently reference wires from several sheets on one page, so
    # inferring the sheet from the most common prefix produces false mismatch
    # flags.  Left off by default; only enable when title-block sheet numbers
    # can be supplied reliably (or you accept modal-prefix inference).
    cross_check_sheet: bool = False
    # ACADE's %S%N wire format writes the line number unpadded, so widths vary:
    # "30080" is 300-8-0 and "300140" is 300-14-0 on the same sheet. With this
    # set, any total width from sheet+1+wire up to sheet+rung+wire digits
    # parses; the sheet keeps its fixed width, the wire index its own, and the
    # line number is whatever sits between. Off by default -- a project that
    # zero-pads stays strict -- and switched on when a source-drawing import
    # reports the unpadded format.
    unpadded_rung: bool = False
    # OCG / layer name keywords (case-insensitive substring match).
    wire_layer_keywords: tuple = ("WIRE", "WIRENO", "WIRE_NO", "WIRENUM")
    jumper_layer_keywords: tuple = ("JUMPER",)
    # How far (in PDF points) two tokens may differ in Y and still be treated as
    # belonging to the same "rung" band for spatial reading-order sorting.
    row_band_tol: float = 6.0

    @property
    def total_width(self) -> int:
        return self.sheet_width + self.rung_width + self.wire_width

    def label_pattern(self) -> "re.Pattern[str]":
        """Anchored pattern matching a *whole* conforming label."""
        if self.regex_override:
            return re.compile(self.regex_override)
        if self.unpadded_rung:
            lo = self.sheet_width + 1 + self.wire_width
            return re.compile(rf"^\d{{{lo},{self.total_width}}}$")
        return re.compile(rf"^\d{{{self.total_width}}}$")

    def token_search_pattern(self) -> "re.Pattern[str]":
        """Pattern used to find a conforming label *inside* a larger token."""
        if self.regex_override:
            # Best effort: strip anchors for an in-token search.
            body = self.regex_override.lstrip("^").rstrip("$")
            return re.compile(body)
        if self.unpadded_rung:
            lo = self.sheet_width + 1 + self.wire_width
            return re.compile(rf"\b\d{{{lo},{self.total_width}}}\b")
        return re.compile(rf"\b\d{{{self.total_width}}}\b")


# --- data carriers ----------------------------------------------------------


@dataclass
class Token:
    """A raw text token extracted from a page (text layer, OCR, or AI)."""

    text: str
    x: float            # left edge, in the page's DISPLAYED space
    y: float            # top edge, in the page's DISPLAYED space
    page: int           # 0-based page index
    layer: Optional[str] = None
    source: str = SOURCE_TEXT
    confidence: float = 1.0
    # Printed extent. Zero when a producer cannot supply it, so callers must
    # tolerate that; with it, a mark can be drawn around the word rather than
    # at a corner of it, and prose can be told from a table by real spacing
    # rather than by guessing a width from the character count.
    w: float = 0.0
    h: float = 0.0

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h


@dataclass
class WireNumber:
    """A classified wire-number occurrence ready for the table / export."""

    label: str
    sheet: Optional[int]
    rung: Optional[int]
    wire_index: Optional[int]
    wire_type: str
    page: int
    source: str = SOURCE_TEXT
    confidence: float = 1.0
    x: float = 0.0
    y: float = 0.0
    count: int = 1
    included: bool = True
    layer: Optional[str] = None
    flags: list = field(default_factory=list)

    @property
    def is_conforming(self) -> bool:
        return self.wire_type == TYPE_CONFORMING

    @property
    def is_fixed(self) -> bool:
        return self.wire_type == TYPE_FIXED

    @property
    def is_jumper(self) -> bool:
        return self.wire_type == TYPE_JUMPER

    @property
    def sort_key(self):
        """Numerical / logical ordering key (sheet, rung, wire-index)."""
        big = float("inf")
        return (
            self.sheet if self.sheet is not None else big,
            self.rung if self.rung is not None else big,
            self.wire_index if self.wire_index is not None else big,
            self.label,
        )


# --- low-level parsing helpers ----------------------------------------------


def parse_label(label: str, config: WireConfig) -> Optional[tuple]:
    """Decompose a *conforming* label into ``(sheet, rung, wire_index)``.

    Returns ``None`` if the label does not match the configured field layout.
    """
    label = label.strip()
    if not config.label_pattern().match(label):
        return None
    sw, rw, ww = config.sheet_width, config.rung_width, config.wire_width
    if config.unpadded_rung and label.isdigit():
        # Sheet keeps its fixed width and the wire index its own; the line
        # number is whatever sits between ("30080" -> 300, 8, 0).
        lo = sw + 1 + ww
        if not (lo <= len(label) <= config.total_width):
            return None
        return (int(label[:sw]), int(label[sw:len(label) - ww]),
                int(label[len(label) - ww:]))
    # If a custom regex matched but the length differs from the field layout we
    # cannot reliably slice it; bail out so it is treated as fixed/OEM.
    if len(label) != config.total_width or not label.isdigit():
        return None
    sheet = int(label[0:sw])
    rung = int(label[sw:sw + rw])
    wire = int(label[sw + rw:sw + rw + ww])
    return sheet, rung, wire


def build_label(sheet: int, rung: int, wire_index: int, config: WireConfig) -> str:
    """Inverse of :func:`parse_label` - compose a label from parts."""
    if config.zero_pad:
        return (
            f"{sheet:0{config.sheet_width}d}"
            f"{rung:0{config.rung_width}d}"
            f"{wire_index:0{config.wire_width}d}"
        )
    return f"{sheet}{rung}{wire_index}"


# --- the parser -------------------------------------------------------------


class WireParser:
    """Detects, parses and classifies wire numbers from extracted tokens."""

    def __init__(self, config: Optional[WireConfig] = None):
        self.config = config or WireConfig()

    # -- candidate detection -------------------------------------------------

    def _layer_is_jumper(self, layer: Optional[str]) -> bool:
        if not layer:
            return False
        up = layer.upper()
        return any(k.upper() in up for k in self.config.jumper_layer_keywords)

    def _layer_is_wire(self, layer: Optional[str]) -> bool:
        if not layer:
            return False
        up = layer.upper()
        return any(k.upper() in up for k in self.config.wire_layer_keywords)

    def is_candidate(self, token: Token) -> bool:
        """Decide whether a raw token could be a wire label.

        A token qualifies when it either matches the conforming-label pattern
        *or* sits on a wire/jumper layer and looks number-ish.  Without any
        layer metadata only the pattern path applies (so OEM/fixed labels can
        only be recovered when layer data exists - matching the spec).
        """
        text = (token.text or "").strip()
        if not text:
            return False
        if self.config.label_pattern().match(text):
            return True
        # AI vision has already vetted the token as a wire label, so accept it
        # even when it doesn't match the configured width (non-standard sets).
        if token.source == SOURCE_AI and re.search(r"\d", text):
            return True
        if self._layer_is_jumper(token.layer) or self._layer_is_wire(token.layer):
            # number-ish and not absurdly long
            if re.search(r"\d", text) and len(text) <= self.config.total_width + 4:
                return True
        return False

    # -- sheet resolution ----------------------------------------------------

    def resolve_sheet(
        self,
        page_tokens: Iterable[Token],
        titleblock_sheet: Optional[int] = None,
    ) -> Optional[int]:
        """Resolve the sheet number for a page.

        Priority: an explicit title-block sheet (best-effort cross-check) wins.
        Otherwise, only when ``cross_check_sheet`` is enabled, fall back to the
        most common first-N digits among cleanly parsing tokens on the page.
        Returns ``None`` when nothing is known (the common case), which means no
        ``sheet_mismatch`` flags are raised.
        """
        if titleblock_sheet is not None:
            return titleblock_sheet
        if not self.config.cross_check_sheet:
            return None
        counts: Counter = Counter()
        for tok in page_tokens:
            parts = parse_label(tok.text, self.config)
            if parts is not None:
                counts[parts[0]] += 1
        if counts:
            return counts.most_common(1)[0][0]
        return None

    # -- classification ------------------------------------------------------

    def classify_token(self, token: Token, resolved_sheet: Optional[int]) -> WireNumber:
        text = token.text.strip()
        parts = parse_label(text, self.config)
        flags: list = []

        # Jumper layer dominates classification.
        if self._layer_is_jumper(token.layer):
            sheet, rung, wire = parts if parts else (None, None, None)
            return WireNumber(
                label=text, sheet=sheet, rung=rung, wire_index=wire,
                wire_type=TYPE_JUMPER, page=token.page, source=token.source,
                confidence=token.confidence, x=token.x, y=token.y,
                layer=token.layer, flags=flags,
            )

        if parts is not None:
            sheet, rung, wire = parts
            if resolved_sheet is not None and sheet != resolved_sheet:
                flags.append(FLAG_SHEET_MISMATCH)
            return WireNumber(
                label=text, sheet=sheet, rung=rung, wire_index=wire,
                wire_type=TYPE_CONFORMING, page=token.page, source=token.source,
                confidence=token.confidence, x=token.x, y=token.y,
                layer=token.layer, flags=flags,
            )

        # On a wire layer but does not follow the rule -> fixed / OEM.
        best_sheet = None
        digits = re.sub(r"\D", "", text)
        if len(digits) >= self.config.sheet_width:
            best_sheet = int(digits[: self.config.sheet_width])
        return WireNumber(
            label=text, sheet=best_sheet, rung=None, wire_index=None,
            wire_type=TYPE_FIXED, page=token.page, source=token.source,
            confidence=token.confidence, x=token.x, y=token.y,
            layer=token.layer, flags=flags,
        )

    # -- top-level pipeline --------------------------------------------------

    def parse(
        self,
        tokens: Iterable[Token],
        titleblock_sheets: Optional[dict] = None,
    ) -> list:
        """Run the full detect -> resolve -> classify pipeline.

        ``titleblock_sheets`` optionally maps ``page-index -> sheet-number`` for
        the best-effort title-block cross-check.  Returns one
        :class:`WireNumber` per detected occurrence (no de-duplication; use
        :func:`dedupe` for that).
        """
        titleblock_sheets = titleblock_sheets or {}
        candidates = [t for t in tokens if self.is_candidate(t)]

        # Group candidates by page for per-page sheet resolution.
        by_page: dict = {}
        for tok in candidates:
            by_page.setdefault(tok.page, []).append(tok)

        results: list = []
        for page, page_tokens in by_page.items():
            resolved = self.resolve_sheet(page_tokens, titleblock_sheets.get(page))
            for tok in page_tokens:
                results.append(self.classify_token(tok, resolved))
        return results


# --- post-processing helpers ------------------------------------------------


def dedupe(wire_numbers: Iterable[WireNumber]) -> list:
    """Collapse identical labels, keeping the first occurrence + a count.

    Identity is ``(label, wire_type)``.  Because a label is self-describing
    (its first digits encode the sheet) the same label printed at both ends of
    a wire, or repeated where a bus crosses several drawing pages, denotes one
    physical wire and collapses to a single row whose ``count`` reflects every
    occurrence.  The returned objects are copies of the first occurrence.
    """
    first: dict = {}
    order: list = []
    for wn in wire_numbers:
        key = (wn.label, wn.wire_type)
        if key in first:
            first[key].count += 1
        else:
            # shallow copy so we never mutate caller state unexpectedly
            keep = WireNumber(**{**wn.__dict__, "count": 1})
            keep.flags = list(wn.flags)
            first[key] = keep
            order.append(key)
    return [first[k] for k in order]


def reading_order(wire_numbers: Iterable[WireNumber], y_tol: float = 6.0) -> list:
    """Sort into spatial reading order: top-to-bottom by rung band, then
    left-to-right within a band, per page."""
    items = list(wire_numbers)
    by_page: dict = {}
    for wn in items:
        by_page.setdefault(wn.page, []).append(wn)

    ordered: list = []
    for page in sorted(by_page):
        page_items = sorted(by_page[page], key=lambda w: (w.y, w.x))
        # Assign band ids by scanning down the page.
        band = 0
        last_y = None
        banded: list = []
        for wn in page_items:
            if last_y is not None and (wn.y - last_y) > y_tol:
                band += 1
            banded.append((band, wn.x, wn))
            last_y = wn.y
        banded.sort(key=lambda t: (t[0], t[1]))
        ordered.extend(wn for _, _, wn in banded)
    return ordered


def numerical_order(wire_numbers: Iterable[WireNumber]) -> list:
    """Sort by (sheet, rung, wire-index, label)."""
    return sorted(wire_numbers, key=lambda w: w.sort_key)
