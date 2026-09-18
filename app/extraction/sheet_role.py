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
    (PLC_IO, ("DIGITAL INPUT", "DIGITAL OUTPUT", "ANALOG INPUT", "ANALOG OUTPUT",
              "DISCRETE INPUT", "DISCRETE OUTPUT", "PLC I/O", "PLC IO",
              "I/O MODULE", "IO MODULE", "INPUT MODULE", "OUTPUT MODULE")),
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
