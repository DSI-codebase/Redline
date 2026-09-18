"""Findings and waivers as this application stores and shows them.

Deliberately its own types rather than the rule library's.  A sidecar written by
a colleague who has the rule library installed must still open for someone who
does not: findings are data, and reading data should not require the engine that
produced it.  These types are also what the sidecar round-trips, so they own
their own JSON.

Qt-free, so the storage layer can use them without dragging the UI in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Mirrors the rule library's vocabulary.
DEFINITE = "definite"
POTENTIAL = "potential"
INFO = "info"
SEVERITIES = (DEFINITE, POTENTIAL, INFO)

SEVERITY_LABELS = {
    DEFINITE: "Definite violation",
    POTENTIAL: "Potential issue",
    INFO: "Informational",
}

STATUS_OPEN = "open"
STATUS_WAIVED = "waived"

_ORDER = {DEFINITE: 0, POTENTIAL: 1, INFO: 2}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Place:
    """One spot on the drawing set that a finding covers.

    A finding used to have exactly one, and for most of them it still does.
    The rule library now rolls a repeated drafting event into a single finding
    -- one stale wire number carried onto eighteen symbols is one decision, not
    eighteen rows -- and names every place it covers in the evidence. Reading
    only the first would leave 287 of the 379 places a real 41-sheet audit
    reports invisible, on sixteen sheets that would look clean.

    ``x``/``y``/``w``/``h`` are the printed box of the text this place is
    about, and are zero where the place is known only as a sheet and a rung.
    That is not a failure: the finding still belongs to the sheet, still lists
    under it, and simply has no box to outline.
    """

    sheet: str = ""
    rung: Optional[int] = None
    page: int = 0
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    subject_id: str = ""

    @property
    def has_location(self) -> bool:
        return bool(self.x or self.y)

    @property
    def label(self) -> str:
        """``232-16`` where the rung is known, ``232`` where it is not."""
        if not self.sheet:
            return ""
        return f"{self.sheet}-{self.rung:02d}" if self.rung is not None \
            else str(self.sheet)

    def to_dict(self) -> dict:
        d = {"sheet": self.sheet, "page": self.page,
             "x": self.x, "y": self.y, "w": self.w, "h": self.h}
        if self.rung is not None:
            d["rung"] = self.rung
        if self.subject_id:
            d["subject_id"] = self.subject_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Place":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def parse_place(text: str) -> tuple:
    """``"232-16"`` -> ``("232", 16)``; ``"232"`` -> ``("232", None)``.

    The rule library writes places in this one spelling, in ``also_at`` and in
    its own rolled-up evidence, so one parser covers every producer.
    """
    text = str(text or "").strip()
    if not text:
        return "", None
    sheet, sep, rung = text.rpartition("-")
    if sep and sheet and rung.isdigit():
        return sheet, int(rung)
    return text, None


@dataclass
class Finding:
    """One thing the audit wants a person to confirm.

    ``key`` is the rule library's fingerprint: stable across re-runs and free of
    coordinates, so a waiver survives a re-extract and a redraw that nudges the
    tag it is about. Findings are rewritten wholesale on every run; waivers are
    keyed on this and are not.
    """

    key: str = ""
    rule_id: str = ""
    severity: str = POTENTIAL
    status: str = STATUS_OPEN
    message: str = ""
    clause: str = ""
    subject_kind: str = ""
    subject_id: str = ""
    sheet: str = ""
    page: int = 0
    # Printed box of the text this finding is about, in the page's displayed
    # space. Zero size when the subject has no single place on the drawing.
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    # Every place this finding covers, primary first. `sheet`, `page`, `x` and
    # `y` above mirror `places[0]`, so anything that only ever wanted one place
    # keeps working; anything that shows the reviewer where to go should walk
    # this instead, or it shows one place out of eighteen.
    places: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    pack: str = ""
    pack_version: str = ""

    def __post_init__(self):
        # A finding built by hand, or loaded from a sidecar written before
        # findings could cover more than one place, still has exactly one.
        if not self.places and (self.sheet or self.x or self.y):
            self.places = [Place(sheet=self.sheet, page=self.page, x=self.x,
                                 y=self.y, w=self.w, h=self.h,
                                 subject_id=self.subject_id)]

    @property
    def sheets(self) -> list:
        """Every sheet this finding covers, in reading order, without repeats."""
        out = []
        for place in self.places:
            if place.sheet and place.sheet not in out:
                out.append(place.sheet)
        return out

    @property
    def place_count(self) -> int:
        return len(self.places)

    @property
    def sheet_label(self) -> str:
        """``232`` for one sheet, ``232 +8`` where the finding covers nine.

        The suffix is what tells a reviewer scanning the list that this row is
        not the whole of the problem.
        """
        seen = self.sheets
        if not seen:
            return ""
        return seen[0] if len(seen) == 1 else f"{seen[0]} +{len(seen) - 1}"

    @property
    def waived(self) -> bool:
        return self.status == STATUS_WAIVED

    @property
    def has_location(self) -> bool:
        return bool(self.x or self.y)

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABELS.get(self.severity, self.severity)

    @property
    def sort_key(self):
        return (_ORDER.get(self.severity, 9), self.sheet, self.rule_id,
                self.subject_id)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "rule_id": self.rule_id, "severity": self.severity,
            "status": self.status, "message": self.message, "clause": self.clause,
            "subject_kind": self.subject_kind, "subject_id": self.subject_id,
            "sheet": self.sheet, "page": self.page,
            "x": self.x, "y": self.y, "w": self.w, "h": self.h,
            "places": [p.to_dict() for p in self.places],
            "evidence": self.evidence, "provenance": self.provenance,
            "pack": self.pack, "pack_version": self.pack_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        out = {k: v for k, v in d.items() if k in known}
        # A sidecar written before findings could cover more than one place has
        # no `places` at all, and __post_init__ synthesises the one it has.
        out["places"] = [Place.from_dict(p) for p in (d.get("places") or [])]
        return cls(**out)

    @classmethod
    def from_pydrc(cls, raw: dict, extents: Optional[dict] = None,
                   pages_by_sheet: Optional[dict] = None) -> "Finding":
        """Convert one finding from the rule library's JSON.

        ``pages_by_sheet`` maps a sheet number to its page index, which is what
        lets the other places a rolled-up finding covers be resolved to a page
        at all. Without it only the primary place survives, which is what this
        method used to do and what left five sixths of a real audit's places
        invisible.
        """
        raw = raw or {}
        loc = raw.get("location") or {}
        subject = raw.get("subject") or {}
        cites = raw.get("cites") or {}
        pack = raw.get("pack") or {}
        evidence = dict(raw.get("evidence") or {})
        subject_id = str(subject.get("id", ""))
        page = loc.get("page_index")
        if page is None:
            # Not every entity kind carries one. A protective device, a
            # terminal, a source, a load, a cross-reference and an index entry
            # all reach here with no page at all, and defaulting them to 0
            # files them on the first sheet of the set -- usually the drawing
            # index -- so double-clicking the row navigates somewhere the
            # finding has nothing to do with.
            #
            # The finding always names its sheet, and the sheet knows its page.
            page = (pages_by_sheet or {}).get(str(loc.get("sheet", "")))

        x = float(loc.get("x") or 0.0)
        y = float(loc.get("y") or 0.0)
        w = h = 0.0
        box = extents.get((int(page), subject_id)) if (
            extents and page is not None) else None
        if box:
            x, y, w, h = box
        elif (subject.get("kind") in _DRAWING_SPACE_KINDS
              and (raw.get("provenance") or {}).get("source") == "acade"):
            # This coordinate is in the source drawing's model space, not the
            # page's. Both are bare numbers, so nothing downstream can tell:
            # a drawing runs about 31 x 21 inches, which as PDF points is
            # half an inch square in the top-left corner, with y inverted --
            # every such finding boxed in the same wrong spot.
            #
            # Zeroing it is not just damage control. A place with no location
            # is skipped by the overlay and falls back to naming its sheet,
            # which is honest; and it lets _places_from try the `on` tag,
            # which a nonzero coordinate blocks.
            x = y = 0.0

        # A finding that names no sheet keeps page 0: DRC-SHEET-INDEX-001 is
        # about the index itself, and has nowhere better to point.
        places = _places_from(evidence, str(loc.get("sheet", "")),
                              loc.get("rung"),
                              int(page) if page is not None else 0,
                              x, y, w, h, subject_id,
                              extents or {}, pages_by_sheet or {})
        # The scalars mirror places[0], including a box _places_from resolved
        # that the lookup above could not. Two answers to "where is this" that
        # disagree is how an overlay ends up drawn somewhere the list does not
        # mention.
        x, y, w, h = places[0].x, places[0].y, places[0].w, places[0].h

        clause = " ".join(str(cites.get(k, "")) for k in
                          ("standard", "edition", "clause")).strip()
        return cls(
            key=str(raw.get("fingerprint", "")),
            rule_id=str(raw.get("rule_id", "")),
            severity=str(raw.get("severity", POTENTIAL)),
            status=str(raw.get("status", STATUS_OPEN)),
            message=str(raw.get("message", "")),
            clause=" ".join(clause.split()),
            subject_kind=str(subject.get("kind", "")),
            subject_id=subject_id,
            sheet=str(loc.get("sheet", "")),
            page=int(page) if page is not None else 0,
            x=x, y=y, w=w, h=h,
            places=places,
            evidence=evidence,
            provenance=dict(raw.get("provenance") or {}),
            pack=str(pack.get("id", "")),
            pack_version=str(pack.get("version", "")),
        )


@dataclass
class Waiver:
    """A human decision that a finding is acceptable here.

    Every real panel has justified exceptions, and a checker without a way to
    record them gets switched off after the second review. Waivers outlive
    findings: an audit re-run replaces the findings table wholesale and must
    never touch this one.
    """

    key: str = ""
    rule_id: str = ""
    reason: str = ""
    author: str = ""
    created: str = field(default_factory=now_iso)
    subject_id: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "rule_id": self.rule_id, "reason": self.reason,
                "author": self.author, "created": self.created,
                "subject_id": self.subject_id}

    @classmethod
    def from_dict(cls, d: dict) -> "Waiver":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Coverage:
    """What a rule could not look at, and why.

    Reported beside findings, never folded into them: "no findings" and "could
    not check" must not be the same answer.
    """

    rule_id: str = ""
    eligible: int = 0
    checked: int = 0
    skipped: int = 0
    reasons: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.skipped == 0

    @property
    def ran(self) -> bool:
        """Whether the rule had anything to look at.

        A rule with nothing eligible skips nothing, so it satisfies
        ``complete`` -- and a report that only asks ``complete`` cannot tell it
        apart from a rule that examined every entity and found them all sound.
        That is the one confusion the rule library's coverage accounting exists
        to prevent: "no findings" and "could not check" must never be the same
        answer.

        It is not hypothetical. A merge that dropped the source-derived motor
        circuits left four enabled motor rules at eligible 0 -- 344 checks, 40
        of them honest skips -- and every one of them was filed under
        "complete" and dropped from the report.
        """
        return self.eligible > 0

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "eligible": self.eligible,
                "checked": self.checked, "skipped": self.skipped,
                "reasons": self.reasons}

    @classmethod
    def from_dict(cls, d: dict) -> "Coverage":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class AuditRun:
    """Summary of one audit, stored in the sidecar's meta table."""

    ran_at: str = field(default_factory=now_iso)
    packs: list = field(default_factory=list)
    eligible: int = 0
    checked: int = 0
    skipped: int = 0
    coverage: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.skipped == 0

    @property
    def idle_rules(self) -> list:
        """Enabled rules that had nothing eligible to look at.

        Reported separately from skips because the cause is different: a skip
        is a rule that looked and could not judge, and this is a rule that was
        never given anything -- usually a model missing a whole entity kind.
        """
        return [c for c in self.coverage if not c.ran]

    @property
    def everything_accounted_for(self) -> bool:
        """Nothing skipped AND nothing left idle: the only true clean bill."""
        return self.complete and not self.idle_rules

    @property
    def blocked(self) -> bool:
        """The run produced nothing, and said why.

        Distinct from a run that produced nothing because there was nothing to
        produce, and distinct from a completed run that recorded a non-fatal
        error alongside real coverage.
        """
        return bool(self.errors) and not self.eligible

    def summary_line(self) -> str:
        """The one sentence the panel header shows.

        Says what was *not* checked first when anything was missed, because
        that is the part a reader is most likely to assume away.
        """
        if self.blocked:
            # Never "Nothing to check." here. That sentence describes a drawing
            # with nothing in it, and this is a check that could not run -- the
            # exact confusion the coverage accounting exists to prevent,
            # arriving in the one line most likely to be read.
            return "The check could not be run: " + self.errors[0]
        if not self.eligible:
            return "Nothing to check."
        idle = self.idle_rules
        if self.complete and idle:
            # Never just "N of N checked" while a rule sat idle: that sentence
            # is what a reviewer reads as a clean bill.
            return (f"{self.checked} of {self.eligible} checked — "
                    f"{len(idle)} rule{'' if len(idle) == 1 else 's'} had "
                    f"nothing to check against.")
        if self.complete:
            return f"{self.checked} of {self.eligible} checked."
        top = sorted(self._reason_totals().items(), key=lambda kv: -kv[1])
        why = "; ".join(f"{n} {r}" for r, n in top[:2])
        tail = f" ({why})" if why else ""
        return (f"{self.checked} of {self.eligible} checked — "
                f"{self.skipped} not checked{tail}.")

    def _reason_totals(self) -> dict:
        totals: dict = {}
        for cov in self.coverage:
            for reason, n in (cov.reasons or {}).items():
                totals[reason] = totals.get(reason, 0) + int(n)
        return totals

    def to_json(self) -> str:
        return json.dumps({
            "ran_at": self.ran_at, "packs": list(self.packs),
            "eligible": self.eligible, "checked": self.checked,
            "skipped": self.skipped, "errors": list(self.errors),
            "coverage": [c.to_dict() for c in self.coverage],
        })

    @classmethod
    def from_json(cls, raw: Optional[str]) -> Optional["AuditRun"]:
        if not raw:
            return None
        try:
            d = json.loads(raw)
        except Exception:
            return None
        return cls(
            ran_at=str(d.get("ran_at", "")),
            packs=list(d.get("packs") or []),
            eligible=int(d.get("eligible", 0)),
            checked=int(d.get("checked", 0)),
            skipped=int(d.get("skipped", 0)),
            errors=list(d.get("errors") or []),
            coverage=[Coverage.from_dict(c) for c in (d.get("coverage") or [])],
        )


def visible_findings(findings, disabled) -> list:
    """The findings left once the rules switched off in Settings are removed.

    Turning a rule off hides its findings rather than deleting them, so turning
    it back on restores the view without a re-run -- but "the view" has to mean
    every view. The panel filtered its own list and nothing else did, so a
    disabled rule kept painting boxes on the drawing and kept filling rows in
    all three exported reports. On the demo set, switching off one rule dropped
    the panel to 53 rows while the overlay still drew all 78 findings and every
    export still listed the 25 that had been turned off.

    Read by the panel, the overlay and the exports, so there is one answer to
    "which findings is this report about".
    """
    rules = set(disabled or ())
    if not rules:
        return list(findings or [])
    return [f for f in (findings or []) if f.rule_id not in rules]


def sort_findings(findings) -> list:
    return sorted(findings, key=lambda f: f.sort_key)


def apply_waivers(findings, waivers: dict) -> list:
    """Mark findings the user has already decided about.

    Waived findings are marked, never dropped: a reviewer needs to see that a
    decision was made, not just its consequence.
    """
    for f in findings:
        f.status = STATUS_WAIVED if f.key in waivers else STATUS_OPEN
    return findings


#: Subject kinds whose coordinates are in drawing space **when the finding came
#: from a source drawing**. Both halves are required.
#:
#: The kind alone is not enough: a plot-derived arrow is found by reading its
#: reference text off the page, so its coordinates are page points and correct.
#: Gating on kind alone zeroed all three arrow findings on a PDF-only audit,
#: which were carrying good boxes at (254.8, 461.0), (383.9, 570.2) and
#: (565.8, 48.2) on a 1224 x 792 page.
#:
#: And the source alone is not enough either: 25 of 36 non-arrow findings from
#: a source drawing hold boxes resolved from the page's own text, and a gate on
#: provenance would throw all of them away.
#:
#: The merge that enriches a plot-derived model replaces these wholesale
#: rather than matching them onto plot-read entities, so they keep the DXF's
#: model space -- and their subject ids are synthetic (a sheet-rung label like
#: "232-16"), so they are never found among the page's printed text either.
#: A device or wire number is different: its id is printed, so the extents
#: lookup answers in page coordinates and this never applies.
#:
#: Keyed on the kind rather than on provenance deliberately. The merge copies
#: `provenance` onto matched base devices that kept their correct page
#: coordinates, so provenance would discard good boxes.
_DRAWING_SPACE_KINDS = frozenset({"signal_arrow"})


def _named_places(evidence: dict) -> list:
    """``[("CBL-23215", "232-16"), ...]`` from the rule library's ``on``.

    Rules that roll several symbols into one finding list them as
    ``TAG@sheet-rung``, which is what lets a place be outlined around the tag
    it is about rather than marked vaguely on the sheet.

    A list of pairs, not a dict keyed by place: a place is a sheet and a rung,
    so symbols with no rung all share their sheet's label, and keeping one tag
    per place threw the rest away. Sixteen field instruments across two sheets
    came back as two boxes when the drawing gives sixteen positions.
    """
    out, seen = [], set()
    for entry in evidence.get("on") or ():
        tag, sep, place = str(entry).rpartition("@")
        tag, place = tag.strip(), place.strip()
        if sep and tag and place and (tag, place) not in seen:
            seen.add((tag, place))
            out.append((tag, place))
    return out


def _first_tag_by_place(named: list) -> dict:
    """The tag to fall back on for a place named without one."""
    out = {}
    for tag, place in named:
        out.setdefault(place, tag)
    return out


def _places_from(evidence, sheet, rung, page, x, y, w, h, subject_id,
                 extents, pages_by_sheet) -> list:
    """The primary place, then every other place the finding names.

    ``also_at`` is the rule library's universal vocabulary for this: the engine
    writes it when it rolls duplicate findings together, and the checks that
    aggregate internally write the same key so a consumer reads one shape
    either way. Anything else is a bonus.
    """
    named = _named_places(evidence)
    tags = _first_tag_by_place(named)
    primary = Place(sheet=sheet, rung=rung if rung is None else int(rung),
                    page=page, x=x, y=y, w=w, h=h, subject_id=subject_id)
    # A rolled-up finding's subject is the thing repeated -- a wire number, a
    # tag shape like CBL-*15 -- and no such text is printed on any sheet, so
    # the caller's lookup found nothing. The symbol standing at this place is
    # printed, and `on` names it.
    if not primary.has_location:
        tag = tags.get(primary.label, "")
        box = extents.get((int(page), tag)) if tag else None
        if box:
            primary.subject_id = tag
            (primary.x, primary.y, primary.w, primary.h) = (
                float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    places = [primary]
    # `on` names a symbol per place and `also_at` names places alone, so a
    # finding carrying both is read from `on`: it is the same set of places,
    # spelled finely enough to tell two symbols on one rung-less sheet apart.
    # Each entry still has to resolve its own box -- a name the page does not
    # print gets a place with no location, which the overlay skips and the
    # report renders as the sheet. A place is never invented, only named.
    if named:
        rest = named
        # The first entry names the symbol the finding opens at -- both
        # producers put it there, the engine's rollup by construction and an
        # aggregating check by passing that symbol as the violation's entity.
        # It is the primary, so it takes over the primary's identity instead
        # of being appended beside it; without this a finding about sixteen
        # symbols reports seventeen places, the extra one a second box drawn
        # exactly on the first. Guarded on the place matching, so a producer
        # that ever breaks the contract loses the naming rather than the box.
        if named[0][1] == primary.label:
            tag = named[0][0]
            rest = named[1:]
            box = extents.get((int(page), tag)) if page is not None else None
            primary.subject_id = tag
            if box and not primary.has_location:
                (primary.x, primary.y, primary.w, primary.h) = (
                    float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        for tag, label in rest:
            at_sheet, at_rung = parse_place(label)
            at_page = pages_by_sheet.get(at_sheet)
            box = extents.get((int(at_page), tag)) if at_page is not None else None
            places.append(Place(
                sheet=at_sheet, rung=at_rung,
                page=int(at_page) if at_page is not None else 0,
                x=float(box[0]) if box else 0.0,
                y=float(box[1]) if box else 0.0,
                w=float(box[2]) if box else 0.0,
                h=float(box[3]) if box else 0.0,
                subject_id=tag))
        return places

    seen = {primary.label} if primary.label else set()
    for text in evidence.get("also_at") or ():
        label = str(text).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        at_sheet, at_rung = parse_place(label)
        at_page = pages_by_sheet.get(at_sheet)
        tag = tags.get(label, "")
        box = extents.get((int(at_page), tag)) if (
            at_page is not None and tag) else None
        places.append(Place(
            sheet=at_sheet, rung=at_rung,
            page=int(at_page) if at_page is not None else 0,
            x=float(box[0]) if box else 0.0,
            y=float(box[1]) if box else 0.0,
            w=float(box[2]) if box else 0.0,
            h=float(box[3]) if box else 0.0,
            subject_id=tag))
    return places
