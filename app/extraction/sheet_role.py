"""What job a sheet does, and why the audit needs to know.

A design rule that compares a tag's declared sheet against the sheet it appears
on is only meaningful where that comparison means something.  A panel-layout
sheet shows every device in the enclosure, each labeled with the schematic sheet
it originates on; a terminal-block sheet references the whole project.  Those
pages are 100% "off-sheet" by design.

Measured on a real plot, flagging every mismatch fires on 47% of tags, nearly
all of them correct drafting.  Restricting the comparison to sheets whose role
makes it meaningful removes 92% of that.  So sheet role is not a nicety: it is
the difference between an audit people keep switched on and one they do not.

Roles are inferred from the descriptive title in the title block and are
user-editable, because inference will not always be right and the person
reading the drawing always knows better.

GUI-free, like its siblings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Vocabulary shared with the rule library, so an adapter can pass roles straight
# through without translating.
SCHEMATIC = "schematic"
PLC_IO = "plc-io"
LAYOUT = "layout"
TERMINAL_DETAIL = "terminal-detail"
TOPOLOGY = "topology"
BOM = "bom"
INDEX = "index"
LEGEND = "legend"
UNKNOWN = "unknown"

ROLES = (SCHEMATIC, PLC_IO, LAYOUT, TERMINAL_DETAIL, TOPOLOGY,
         BOM, INDEX, LEGEND, UNKNOWN)

# Human-readable, for a settings combo box.
ROLE_LABELS = {
    SCHEMATIC: "Schematic",
    PLC_IO: "PLC I/O",
    LAYOUT: "Panel layout",
    TERMINAL_DETAIL: "Terminal block detail",
    TOPOLOGY: "Network topology",
    BOM: "Bill of materials",
    INDEX: "Title / index",
    LEGEND: "Symbol legend",
    UNKNOWN: "Unknown",
}

# Sheets whose purpose is to reference things drawn elsewhere.  Location rules
# must stay quiet here.
REFERENCING_ROLES = frozenset({LAYOUT, TERMINAL_DETAIL, TOPOLOGY, BOM, INDEX, LEGEND})

# Ordered most-specific first: "TERMINAL BLOCK LAYOUT" is a terminal detail, not
# a panel layout, so the terminal keywords have to be tested first.
ROLE_KEYWORDS = (
    (TERMINAL_DETAIL, ("TERMINAL BLOCK", "TERMINAL STRIP", "TERMINAL DETAIL",
                       "TERMINAL PLAN", "TB DETAIL")),
    # "PLCIO" and "RELAY OUTPUT" measured 2026-10-03 on four real sets (56
    # sheets): without them 12 PLC sheets read as schematic, 10 titled PLCIO
    # and 2 titled RELAY OUTPUTS; with them, 55 of 56 roles right, none worse.
    (PLC_IO, ("DIGITAL INPUT", "DIGITAL OUTPUT", "ANALOG INPUT", "ANALOG OUTPUT",
              "DISCRETE INPUT", "DISCRETE OUTPUT", "PLC I/O", "PLC IO", "PLCIO",
              "RELAY OUTPUT", "I/O MODULE", "IO MODULE", "INPUT MODULE",
              "OUTPUT MODULE")),
    (BOM, ("BILL OF MATERIAL", "PARTS LIST", "MATERIAL LIST")),
    (LEGEND, ("SYMBOL", "LEGEND")),
    (INDEX, ("TITLE PAGE", "TITLE SHEET", "COVER SHEET",
             "DRAWING INDEX", "SHEET INDEX", "DRAWING SECTION INDEX")),
    (TOPOLOGY, ("TOPOLOGY", "NETWORK DIAGRAM", "NETWORK ARCHITECTURE")),
    (LAYOUT, ("ENCLOSURE LAYOUT", "PANEL LAYOUT", "BACK PANEL", "SUBPANEL",
              "DOOR LAYOUT", "NAMEPLATE", "LAYOUT", "ENCLOSURE")),
)


@dataclass
class SheetRoleConfig:
    """Where to look for the sheet's descriptive title.

    The band is expressed in the page's *displayed* space, which is also the
    space extraction reports coordinates in.
    """

    titleblock_x_frac: float = 0.55
    titleblock_y_frac: float = 0.72
    # A page this sparse has no body text to confuse a keyword with, so the
    # whole page can be searched.
    sparse_page_chars: int = 600
    default_role: str = SCHEMATIC
    # Words on one printed line differ in top edge by a fraction of a point
    # (glyph heights vary), so reading order has to band the y coordinate before
    # sorting. Without this "TERMINAL BLOCK LAYOUT" can come back as "BLOCK
    # LAYOUT TERMINAL" and stop matching the phrase it plainly is.
    row_band_tol: float = 6.0


def role_from_text(text: str, config: Optional[SheetRoleConfig] = None) -> Optional[str]:
    """The role a piece of title text implies, or ``None`` if it implies none."""
    config = config or SheetRoleConfig()
    haystack = " ".join((text or "").upper().split())
    if not haystack:
        return None
    for role, keywords in ROLE_KEYWORDS:
        for kw in keywords:
            if kw in haystack:
                return role
    return None


def _titleblock_text(page, config: SheetRoleConfig) -> str:
    """Text from the title-block band, in displayed space."""
    import fitz
    try:
        raw = page.get_text("words") or []
        rot = page.rotation_matrix
        rect = page.rect
    except Exception:
        return ""
    x_min = rect.x0 + rect.width * config.titleblock_x_frac
    y_min = rect.y0 + rect.height * config.titleblock_y_frac
    band = []
    for w in raw:
        try:
            r = (fitz.Rect(w[0], w[1], w[2], w[3]) * rot).normalize()
        except Exception:
            continue
        if r.x0 >= x_min and r.y0 >= y_min:
            band.append((r.y0, r.x0, str(w[4])))
    tol = max(config.row_band_tol, 0.001)
    band.sort(key=lambda t: (int(t[0] // tol), t[1]))
    return " ".join(t for _y, _x, t in band)


def detect_role(page, config: Optional[SheetRoleConfig] = None) -> str:
    """Best-effort role for one page.

    Falls back to ``schematic``, which is both the commonest kind of sheet and
    the conservative choice: it is the role location rules *do* apply to, so a
    misdetection shows up as a finding a reviewer can dismiss rather than as a
    rule silently switching itself off.
    """
    config = config or SheetRoleConfig()
    role = role_from_text(_titleblock_text(page, config), config)
    if role:
        return role
    try:
        text = page.get_text("text") or ""
    except Exception:
        text = ""
    if len(text.strip()) < config.sparse_page_chars:
        role = role_from_text(text, config)
        if role:
            return role
    return config.default_role


def detect_document_roles(doc, config: Optional[SheetRoleConfig] = None) -> dict:
    """``{page_index: role}`` for a whole document."""
    config = config or SheetRoleConfig()
    out: dict = {}
    for i in range(getattr(doc, "page_count", 0)):
        try:
            out[i] = detect_role(doc[i], config)
        except Exception:
            out[i] = config.default_role
    return out


# --- Jev: the same judgment, asked of a model --------------------------------
#
# Opt-in and off by default. ROLE_KEYWORDS above stays the answer whenever Jev
# is off, has no key, fails, or is unsure; Jev only ever replaces a keyword
# result, never a role a person set (``Document.roles_for_audit``).
#
# Changing any text below changes what Jev decides. A role recorded under the
# old wording is not comparable with one asked under the new, so the answers
# carry the model that gave them and a version of this wording.

JEV_QUESTION_ID = "role"
JEV_WORDING = 1

JEV_INSTRUCTIONS = (
    "Decide what job this sheet does in an electrical control-panel drawing "
    "set. `title_block` is the text printed in the sheet's title block, in "
    "reading order: the sheet's descriptive title is in it, alongside the "
    "client, project, drawing number, dates and revision notes. `page_text`, "
    "when present, is all the text on a sparse page."
)

# Ordered as ROLES, with `unknown` last: option order moves a Choice (TypeSafe's
# jev-1.13 jaggedness note), so it is fixed here rather than left to a dict
# literal somebody reorders for tidiness.
JEV_CRITERIA = {
    SCHEMATIC: "A ladder or wiring schematic: power distribution, control "
               "circuits, motor or drive wiring, safety circuits. The title "
               "names a circuit or a voltage, such as 110 VAC DISTRIBUTION.",
    PLC_IO: "A PLC input or output sheet: the title names digital or analog "
            "inputs or outputs, an I/O module, or a PLC rack or slot.",
    LAYOUT: "A physical arrangement drawing: an enclosure, back panel, "
            "subpanel or door layout, or a nameplate schedule. A terminal "
            "block layout is not this.",
    TERMINAL_DETAIL: "A terminal block or terminal strip detail, plan or "
                     "layout.",
    TOPOLOGY: "A network topology, network diagram or communications "
              "architecture.",
    BOM: "A bill of materials, parts list or material list.",
    INDEX: "A title page, cover sheet, or drawing or sheet index.",
    LEGEND: "A symbol legend or symbols page that explains drawing notation.",
    UNKNOWN: "The text shows no sheet title that fits any option above.",
}

# Set from confidence bands on four real, owner-labeled sets, 56 sheets asked
# twice (HANDOFF-JEV.md): 100 answers at 0.75 or above, none wrong; 3 between
# 0.60 and 0.75, 2 wrong. Changing it needs new bands, not a new opinion.
JEV_THRESHOLD = 0.75


def jev_question() -> dict:
    """The one Choice asked per sheet."""
    return {JEV_QUESTION_ID: {"type": "choice",
                              "instructions": JEV_INSTRUCTIONS,
                              "criteria": dict(JEV_CRITERIA)}}


def jev_state(page, config: Optional[SheetRoleConfig] = None) -> Optional[dict]:
    """What Jev is shown for one page: the same two sources the keyword path
    reads, or ``None`` when the page has no text to judge (a scanned sheet)."""
    config = config or SheetRoleConfig()
    band = " ".join(_titleblock_text(page, config).split())
    try:
        text = " ".join((page.get_text("text") or "").split())
    except Exception:
        text = ""
    state: dict = {}
    if band:
        state["title_block"] = band
    if text and len(text) < config.sparse_page_chars:
        state["page_text"] = text
    return state or None


def jev_document_roles(doc, pages, *, ask=None, api_key: str = "",
                       model: Optional[str] = None,
                       config: Optional[SheetRoleConfig] = None,
                       progress=None, should_cancel=None) -> dict:
    """``{page_index: answer}`` for the ``pages`` Jev answered.

    ``answer`` is ``{role, confidence, probabilities, model, wording}``. A page
    with no text, a failed request, or a choice outside :data:`ROLES` is simply
    absent, so the caller keeps the keyword role for it. Never raises.
    """
    from . import jev_api
    ask = ask or jev_api.ask
    model = model or jev_api.DEFAULT_MODEL
    config = config or SheetRoleConfig()
    pages = list(pages)
    out: dict = {}
    for n, page_no in enumerate(pages, 1):
        if should_cancel is not None and should_cancel():
            break
        if progress is not None:
            progress(n, len(pages))
        try:
            state = jev_state(doc[page_no], config)
            if state is None:
                continue
            got = jev_api.choice_answer(
                ask(state, jev_question(), model=model, api_key=api_key),
                JEV_QUESTION_ID)
        except Exception:
            continue
        if got is None or got["choice"] not in ROLES:
            continue
        out[page_no] = {"role": got["choice"],
                        "confidence": got["confidence"],
                        "probabilities": got["probabilities"],
                        "model": got["model"] or model,
                        "wording": JEV_WORDING}
    return out


def jev_roles_for_path(pdf_path: str, pages, **kwargs) -> dict:
    """:func:`jev_document_roles` on a file this function opens and closes, for
    a worker thread that must not touch the open document. Never raises."""
    import fitz
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return {}
    try:
        return jev_document_roles(doc, pages, **kwargs)
    finally:
        doc.close()


def apply_jev_roles(roles: dict, answers: dict,
                    threshold: float = JEV_THRESHOLD,
                    model: Optional[str] = None) -> dict:
    """``roles`` with each page in ``answers`` replaced where its answer applies
    (:func:`jev_role_applies`); every other page unchanged. The caller passes
    only pages a person did not set."""
    out = dict(roles)
    for page_no, answer in (answers or {}).items():
        role = jev_role_applies(answer, threshold, model)
        if role:
            out[page_no] = role
    return out


def jev_answer_current(answer, model: Optional[str] = None) -> bool:
    """Whether a recorded answer was asked under this wording of the question
    and by ``model`` (the pinned default when omitted). Anything else is stale:
    it is re-asked rather than trusted."""
    if not isinstance(answer, dict):
        return False
    if model is None:
        from . import jev_api
        model = jev_api.DEFAULT_MODEL
    return answer.get("wording") == JEV_WORDING and answer.get("model") == model


def jev_role_applies(answer, threshold: float = JEV_THRESHOLD,
                     model: Optional[str] = None) -> Optional[str]:
    """The role a recorded Jev answer sets, or ``None`` when it sets none:
    stale (:func:`jev_answer_current`), ``unknown``, or below the threshold."""
    if not jev_answer_current(answer, model):
        return None
    role = answer.get("role")
    if role not in ROLES or role == UNKNOWN:
        return None
    try:
        confidence = float(answer.get("confidence"))
    except (TypeError, ValueError):
        return None
    return role if confidence >= threshold else None
