"""Turning an open drawing into the model the rule engine evaluates.

Deliberately free of Qt, of the sidecar, and of :class:`~app.model.document.Document`
itself: it takes plain data and a PyMuPDF handle, so the audit can run on a
worker thread without touching anything the main thread owns.  The sidecar's
sqlite connection is single-thread only, and the document's is not ours to
borrow.

What a plot can populate is a real limit, not an oversight.  Sheets, devices and
wire numbers come out of the text layer; conductor size, insulation and
endpoints do not exist in a plotted drawing at all.  Rules that need them report
as uncovered rather than clean, which is the whole point of carrying provenance
on every fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from ..extraction import rung as rung_mod
from ..extraction import sheet_number as sn
from ..extraction import signal_arrow as arrow_mod
from ..extraction import text_region as tr
from ..extraction import titleblock as tb
from ..extraction.component_parser import ComponentConfig, ComponentParser
from ..extraction.text_extract import extract_tokens
from ..extraction.wire_parser import WireConfig, WireParser

# Rows of the drawing index on the title sheet: a three-digit section followed
# by its description. The index is a claim about the package's contents, which
# makes it checkable against the package.
_INDEX_HEADING_RE = re.compile(r"DRAWING\s+(?:SECTION\s+)?INDEX", re.IGNORECASE)
_SECTION_RE = re.compile(r"^\d{3}$")


@dataclass
class ModelBuild:
    """A built model, plus what the UI needs that the model itself does not carry.

    ``extents`` maps ``(page_index, label)`` to the printed box of the text that
    produced an entity, so a finding can be drawn *around* the tag it is about
    rather than at a point near it. It is kept beside the model rather than
    inside it because it is a presentation detail: the rule engine has no use
    for it, and a model document is an interchange format shared with producers
    that have no coordinates at all.
    """

    model: object = None
    extents: dict = None

    def __post_init__(self):
        if self.extents is None:
            self.extents = {}


@dataclass
class AdapterOptions:
    """What to include when building the model."""

    wire_config: Optional[WireConfig] = None
    component_config: Optional[ComponentConfig] = None
    region_config: Optional[tr.TextRegionConfig] = None
    # Labels the user has unticked in the Wire Numbers / Component Labels tabs.
    excluded_labels: frozenset = frozenset()
    read_index: bool = True
    read_arrows: bool = True
    read_titleblock: bool = True


def _provenance(source: str, confidence: float = 1.0, resolved_by: str = ""):
    from pydrc.model import Provenance, SOURCE_PDF_TEXT, SOURCE_USER
    kind = SOURCE_USER if source == sn.USER else SOURCE_PDF_TEXT
    return Provenance(source=kind, confidence=confidence, resolved_by=resolved_by)


def parse_drawing_index(text: str) -> list:
    """``(section, description)`` rows from a title sheet's drawing index."""
    m = _INDEX_HEADING_RE.search(text or "")
    if not m:
        return []
    lines = [ln.strip() for ln in text[m.start():].splitlines() if ln.strip()]
    rows, pending = [], None
    for line in lines:
        if _SECTION_RE.match(line):
            pending = line
        elif pending:
            rows.append((pending, line))
            pending = None
    return rows


def build_model(fitz_doc, sheet_labels: dict, sheet_sources: dict,
                sheet_roles: dict, options: Optional[AdapterOptions] = None,
                project: Optional[dict] = None,
                progress: Optional[Callable] = None,
                cancel: Optional[Callable] = None):
    """Build a :class:`ModelBuild` from an open PyMuPDF document.

    ``progress(done, total)`` and ``cancel()`` follow the convention in
    :mod:`app.tools.runner`.  Returns ``None`` when cancelled.
    """
    from pydrc.model import (ModelDocument, Project, Sheet, Device, Conductor,
                             IndexEntry, SignalArrow)

    options = options or AdapterOptions()
    wire_cfg = options.wire_config or WireConfig()
    comp_cfg = options.component_config or ComponentConfig()

    model = ModelDocument()
    page_count = int(getattr(fitz_doc, "page_count", 0))
    total = max(1, page_count + 1)

    meta = project or {}
    model.project = Project(
        number=str(meta.get("number", "")),
        title=str(meta.get("title", "")),
        customer=str(meta.get("customer", "")),
        revision=str(meta.get("revision", "")),
        provenance=_provenance(sn.DRAWING_NUMBER),
    )

    # -- sheets --------------------------------------------------------------
    # Per-page tokens are needed for the rung gutter, the connectors and the
    # title block, so they are kept rather than re-extracted three times.
    page_tokens: dict = {}
    page_rungs: dict = {}
    for page_no in range(page_count):
        if cancel is not None and cancel():
            return None
        try:
            page = fitz_doc[page_no]
            page_tokens[page_no] = extract_tokens(page, page_no)
        except Exception:
            page_tokens[page_no] = []
            continue
        label = str(sheet_labels.get(page_no, "") or "")
        if label:
            try:
                page_rungs[page_no] = rung_mod.extract_rungs(
                    page_tokens[page_no], label, page.rect.width)
            except Exception:
                page_rungs[page_no] = []

    fields = {}
    if options.read_titleblock:
        for page_no, toks in page_tokens.items():
            try:
                page = fitz_doc[page_no]
                fields[page_no] = tb.read_fields(toks, page.rect.width,
                                                 page.rect.height)
            except Exception:
                continue

    for page_no in range(page_count):
        label = str(sheet_labels.get(page_no, "") or "")
        strategy = str(sheet_sources.get(page_no, sn.UNKNOWN))
        confidence = sn.CONFIDENCE.get(strategy, 0.5) if label else 0.0
        claimed = fields.get(page_no)
        rungs = page_rungs.get(page_no) or []
        model.sheets.append(Sheet(
            number=label,
            page_index=page_no,
            role=str(sheet_roles.get(page_no, "schematic")),
            declared_number=(claimed.this_sheet if claimed else ""),
            next_sheet=(claimed.next_sheet if claimed else ""),
            line_count=(max(r.line for r in rungs) if rungs else None),
            provenance=_provenance(strategy, confidence, strategy),
        ))

    # -- tokens, regions, and the entities parsed from them ------------------
    tokens: list = []
    for page_no in range(page_count):
        if cancel is not None and cancel():
            return None
        tokens.extend(page_tokens.get(page_no) or [])
        if progress is not None:
            progress(page_no + 1, total)

    page_sizes = {}
    for page_no in range(page_count):
        try:
            rect = fitz_doc[page_no].rect
            page_sizes[page_no] = (float(rect.width), float(rect.height))
        except Exception:
            continue
    regions = tr.classify_tokens(tokens, sheet_roles, options.region_config,
                                 page_sizes)
    region_of = {}
    extents: dict = {}
    for tok, role in zip(tokens, regions):
        text = tok.text.strip()
        region_of[(tok.page, text, round(tok.x, 1), round(tok.y, 1))] = role
        # First occurrence wins, matching how the parsers dedupe.
        extents.setdefault((tok.page, text),
                           (float(tok.x), float(tok.y),
                            float(getattr(tok, "w", 0.0) or 0.0),
                            float(getattr(tok, "h", 0.0) or 0.0)))

    def _region(item, label: str) -> str:
        return region_of.get(
            (item.page, label, round(item.x, 1), round(item.y, 1)), tr.DRAWING)

    def _region_at(lookup: dict, page_no: int, x: float, y: float) -> str:
        """Region role for a point, from whichever token sits there."""
        for (pg, _text, tx, ty), role in lookup.items():
            if pg == page_no and abs(tx - x) < 1.0 and abs(ty - y) < 1.0:
                return role
        return tr.DRAWING

    excluded = set(options.excluded_labels or ())

    for comp in ComponentParser(comp_cfg).parse(tokens):
        if comp.label in excluded:
            continue
        model.devices.append(Device(
            tag=comp.label,
            family=comp.family,
            number=comp.number,
            declared_sheet=comp.sheet,
            declared_rung=comp.rung,
            found_on_sheet=str(sheet_labels.get(comp.page, "") or ""),
            page_index=comp.page,
            x=round(float(comp.x), 2),
            y=round(float(comp.y), 2),
            region_role=_region(comp, comp.label),
            provenance=_provenance(comp.source, float(comp.confidence)),
        ))

    for wire in WireParser(wire_cfg).parse(tokens):
        if wire.label in excluded:
            continue
        model.conductors.append(Conductor(
            label=wire.label,
            declared_sheet=wire.sheet,
            declared_rung=wire.rung,
            wire_index=wire.wire_index,
            found_on_sheet=str(sheet_labels.get(wire.page, "") or ""),
            page_index=wire.page,
            x=round(float(wire.x), 2),
            y=round(float(wire.y), 2),
            wire_type=wire.wire_type,
            region_role=_region(wire, wire.label),
            provenance=_provenance(wire.source, float(wire.confidence)),
        ))

    # -- off-page connectors -------------------------------------------------
    if options.read_arrows:
        for page_no, toks in page_tokens.items():
            label = str(sheet_labels.get(page_no, "") or "")
            if not label:
                continue
            try:
                found = arrow_mod.dedupe(arrow_mod.extract_arrows(
                    toks, page_rungs.get(page_no) or [], label))
            except Exception:
                continue
            for a in found:
                model.signal_arrows.append(SignalArrow(
                    label=a.raw,
                    direction=a.direction,
                    found_on_sheet=a.source_sheet,
                    found_on_rung=a.source_line,
                    target_sheet=f"{a.target_sheet:03d}",
                    target_rung=a.target_line,
                    page_index=page_no,
                    x=round(float(a.x), 2),
                    y=round(float(a.y), 2),
                    region_role=_region_at(region_of, page_no, a.x, a.y),
                    provenance=_provenance(sn.DRAWING_NUMBER),
                ))

    # -- the drawing index ---------------------------------------------------
    if options.read_index:
        for page_no, role in sorted(sheet_roles.items()):
            if role != "index" or page_no >= page_count:
                continue
            try:
                text = fitz_doc[page_no].get_text("text") or ""
            except Exception:
                continue
            for section, description in parse_drawing_index(text):
                model.index_entries.append(IndexEntry(
                    section=section, description=description,
                    provenance=_provenance(sn.DRAWING_NUMBER)))

    if progress is not None:
        progress(total, total)
    return ModelBuild(model=model, extents=extents)
