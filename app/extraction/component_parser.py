"""Component-label detection, parsing, and classification.

Sibling of :mod:`wire_parser`, but for *device/component* tags rather than
conductor numbers.  A component label looks like::

    [FAMILY] [-] [ S S S ][ R R ]
     letters  sep  sheet    rung

e.g. ``LT-10010`` -> family ``LT``, sheet ``100``, rung ``10`` (with the default
component widths sheet=3, rung=2).  The family code identifies the device type
(LT = light, CR = control relay, PB = push button, …); drafters sometimes invent
their own, so unknown family codes are still captured and *flagged* rather than
dropped.

GUI-free so the core is unit-testable in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# reuse the shared source tags
from .wire_parser import SOURCE_TEXT, SOURCE_OCR, SOURCE_AI  # noqa: F401

# --- classification constants ----------------------------------------------

TYPE_CONFORMING = "conforming"        # number splits cleanly into sheet+rung
TYPE_NONCONFORMING = "nonconforming"  # a family+number tag of another length

FLAG_UNKNOWN_FAMILY = "unknown_family"

# A pragmatic seed list: codes mined from the sample drawing set plus common
# electrical / ISA device families.  Fully user-editable in Settings.
DEFAULT_FAMILY_CODES = (
    # mined from the sample set
    "CR", "SS", "CB", "LT", "LS", "PS", "IS", "SI", "SC", "HS", "LIT", "UPS",
    "ZI", "ZIR", "YC", "RECP", "FPD", "ENET", "EAR", "PSH", "PSL", "SA",
    "VFDS", "ZICR", "YIQR",
    # common electrical / control families
    "PB", "FU", "M", "MTR", "OL", "TD", "SOL", "SV", "HOA", "DS", "MCB",
    "GFCI", "TB", "TR", "XF", "XFMR", "CT", "PT", "R", "K", "Q",
    # common ISA instrument families
    "FT", "FV", "PV", "TV", "LV", "TT", "ZS", "ZSO", "ZSC", "FIT", "PIT",
    "TIT", "RTD", "TC", "PLC", "HMI", "VFD", "MOV",
    # power / grounding / misc families (reported during testing)
    "CBL", "DV", "EN", "DN", "GND", "PDB", "PRS", "PW", "SCR", "SE", "X",
)


# --- configuration ----------------------------------------------------------


@dataclass
class ComponentConfig:
    """Knobs for component-label detection / parsing (separate from wires)."""

    sheet_width: int = 3
    rung_width: int = 2
    zero_pad: bool = True
    families: tuple = DEFAULT_FAMILY_CODES
    # plausible digit-count window for the numeric part of a tag
    min_digits: int = 3
    max_digits: int = 8

    @property
    def conform_width(self) -> int:
        return self.sheet_width + self.rung_width

    def family_set(self) -> set:
        return {f.strip().upper() for f in self.families if str(f).strip()}

    def token_pattern(self) -> "re.Pattern[str]":
        """Anchored pattern matching a whole ``FAMILY[-/ ]NNN`` tag."""
        return re.compile(
            rf"^([A-Za-z]{{1,4}})[-_/ ]?(\d{{{self.min_digits},{self.max_digits}}})$")


# --- data carrier -----------------------------------------------------------


@dataclass
class ComponentLabel:
    """A classified component-label occurrence ready for the table / export."""

    label: str
    family: str
    number: str                     # the digit part, as printed
    sheet: Optional[int]
    rung: Optional[int]
    comp_type: str
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
        return self.comp_type == TYPE_CONFORMING

    @property
    def unknown_family(self) -> bool:
        return FLAG_UNKNOWN_FAMILY in self.flags

    @property
    def sort_key(self):
        big = float("inf")
        return (
            self.sheet if self.sheet is not None else big,
            self.rung if self.rung is not None else big,
            self.family,
            self.number,
        )


# --- low-level parsing ------------------------------------------------------


def parse_component_label(text: str, config: ComponentConfig) -> Optional[tuple]:
    """Decompose a tag into ``(family, number, sheet, rung)``.

    ``sheet``/``rung`` are ``None`` when the digit part is not exactly
    ``sheet_width + rung_width`` long.  Returns ``None`` when the text is not a
    family+number tag at all.
    """
    m = config.token_pattern().match((text or "").strip())
    if not m:
        return None
    family = m.group(1).upper()
    number = m.group(2)
    sheet = rung = None
    if len(number) == config.conform_width:
        sw = config.sheet_width
        sheet = int(number[:sw])
        rung = int(number[sw:sw + config.rung_width])
    return family, number, sheet, rung


def build_component_label(family: str, sheet: int, rung: int,
                          config: ComponentConfig, sep: str = "-") -> str:
    """Inverse of :func:`parse_component_label` (used by tests / round-trips)."""
    if config.zero_pad:
        num = f"{sheet:0{config.sheet_width}d}{rung:0{config.rung_width}d}"
    else:
        num = f"{sheet}{rung}"
    return f"{family.upper()}{sep}{num}"


# --- the parser -------------------------------------------------------------


class ComponentParser:
    """Detects, parses and classifies component labels from extracted tokens."""

    def __init__(self, config: Optional[ComponentConfig] = None):
        self.config = config or ComponentConfig()
        self._families = self.config.family_set()

    def is_candidate(self, token) -> bool:
        """Decide whether a raw token could be a component label.

        Accept it when the family code is known, when the numeric part has the
        conforming sheet+rung length (a strong signal even for an invented
        family), or when AI vision already vetted it as a component.  This keeps
        random ``LETTERS-DIGITS`` noise out while still capturing drafters'
        custom codes that follow the numbering scheme.
        """
        parsed = parse_component_label(getattr(token, "text", ""), self.config)
        if parsed is None:
            return False
        family, number, sheet, _rung = parsed
        if token.source == SOURCE_AI:
            return True
        if family in self._families:
            return True
        return sheet is not None        # conforming length even if family unknown

    def classify_token(self, token) -> Optional[ComponentLabel]:
        parsed = parse_component_label(token.text, self.config)
        if parsed is None:
            return None
        family, number, sheet, rung = parsed
        flags: list = []
        if family not in self._families:
            flags.append(FLAG_UNKNOWN_FAMILY)
        comp_type = TYPE_CONFORMING if sheet is not None else TYPE_NONCONFORMING
        return ComponentLabel(
            label=token.text.strip(), family=family, number=number,
            sheet=sheet, rung=rung, comp_type=comp_type, page=token.page,
            source=token.source, confidence=token.confidence,
            x=token.x, y=token.y, layer=token.layer, flags=flags,
        )

    def parse(self, tokens: Iterable) -> list:
        out: list = []
        for tok in tokens:
            if not self.is_candidate(tok):
                continue
            cl = self.classify_token(tok)
            if cl is not None:
                out.append(cl)
        return out


# --- post-processing (mirrors wire_parser) ----------------------------------


def reclassify(components: Iterable[ComponentLabel],
               config: Optional[ComponentConfig]) -> list:
    """Re-derive family / sheet / rung / type / flags for already-extracted
    labels under a (possibly changed) config — e.g. after the user edits the
    known family codes or field widths in Settings — *without* re-running
    extraction. Mutates each label in place (preserving count / included /
    position) and returns the list."""
    fams = config.family_set() if config else set()
    out = list(components)
    for c in out:
        parsed = parse_component_label(c.label, config)
        if parsed is None:
            continue
        family, number, sheet, rung = parsed
        c.family, c.number, c.sheet, c.rung = family, number, sheet, rung
        c.comp_type = TYPE_CONFORMING if sheet is not None else TYPE_NONCONFORMING
        flags = [f for f in c.flags if f != FLAG_UNKNOWN_FAMILY]
        if family not in fams:
            flags.append(FLAG_UNKNOWN_FAMILY)
        c.flags = flags
    return out


def dedupe(components: Iterable[ComponentLabel]) -> list:
    """Collapse identical tags (``label``), keeping the first + an occurrence
    count."""
    first: dict = {}
    order: list = []
    for c in components:
        key = c.label
        if key in first:
            first[key].count += 1
        else:
            keep = ComponentLabel(**{**c.__dict__, "count": 1})
            keep.flags = list(c.flags)
            first[key] = keep
            order.append(key)
    return [first[k] for k in order]


def numerical_order(components: Iterable[ComponentLabel]) -> list:
    return sorted(components, key=lambda c: c.sort_key)


def reading_order(components: Iterable[ComponentLabel], y_tol: float = 6.0) -> list:
    """Spatial reading order: top-to-bottom by band, left-to-right within, per
    page."""
    items = list(components)
    by_page: dict = {}
    for c in items:
        by_page.setdefault(c.page, []).append(c)
    ordered: list = []
    for page in sorted(by_page):
        page_items = sorted(by_page[page], key=lambda c: (c.y, c.x))
        band = 0
        last_y = None
        banded: list = []
        for c in page_items:
            if last_y is not None and (c.y - last_y) > y_tol:
                band += 1
            banded.append((band, c.x, c))
            last_y = c.y
        banded.sort(key=lambda t: (t[0], t[1]))
        ordered.extend(c for _, _, c in banded)
    return ordered
