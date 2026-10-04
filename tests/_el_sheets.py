"""Synthetic sheets in DSI's EL-generation title block.

The title block every DSI AutoCAD Electrical 2027 job seen so far prints: DSI
JOB NUMBER, ENCLOSURE NUMBER, REVIEWED BY and the rest as labels in the text
layer, each with its value in the row beneath. Nothing here comes from a
customer drawing. The geometry follows what was measured on two real plots
(DSI-codebase/BluePrint, docs/research/2026-10-04/plots-EL2503311-Stacker.md,
sections 3 and 6): a 792 x 1224 portrait page plotted with /Rotate 270, labels
at 3.26 pt over values at 5.66 pt, ``ENCLOSURE NUMBER:`` at display
(1131.8, 733.9) and ``DRAWING NUMBER:`` at (1040.8, 765.1), and a ladder's
line-number gutter at x=51 (lines 01-40) and x=636 (41-80) on a 16.2 pt pitch
from y=48.1. The words are generic.

Everything is placed in *displayed* space, the space extraction reports in, and
mapped back through the page's derotation, so a position here is one a reader of
the measurement can check against the rendered sheet.
"""

import fitz

from app.extraction.sheet_role import (
    BOM, INDEX, LAYOUT, LEGEND, PLC_IO, SCHEMATIC, TERMINAL_DETAIL, TOPOLOGY)

W, H = 792.0, 1224.0
JOB = "EL0000000"

LABEL_PT = 3.26
VALUE_PT = 5.66

GUTTER_X = (51.0, 636.0)
FIRST_LINE_Y = 48.1
LINE_PITCH = 16.2


def new_page(doc):
    """A blank EL sheet, rotated for display as the plots are."""
    page = doc.new_page(width=W, height=H)
    page.set_rotation(270)
    return page


def put(page, x, y, text, size=VALUE_PT):
    """Write ``text`` with its baseline origin at displayed ``(x, y)``,
    reading left to right on screen."""
    page.insert_text(fitz.Point(x, y) * page.derotation_matrix, text,
                     fontsize=size, rotate=270)


def title_block(page, description, sheet, next_sheet=""):
    """The EL title block: each label, and its value one row beneath it."""
    fields = (
        # (x, label y, label, value)
        (700.0, 700.0, "CLIENT:", "SAMPLE CLIENT"),
        (790.0, 700.0, "CLIENT JOB ID:", ""),
        (860.0, 700.0, "PROJECT DESCRIPTION:", "SAMPLE CONTROLS UPGRADE"),
        (960.0, 700.0, "SHEET DESCRIPTION:", description),
        (700.0, 733.9, "DRAWN BY:", "AB"),
        (760.0, 733.9, "DESIGN BY:", "CD"),
        (960.0, 733.9, "DSI JOB NUMBER:", JOB),
        (1131.8, 733.9, "ENCLOSURE NUMBER:", "MCP"),
        (700.0, 765.1, "REVIEWED BY:", "CD"),
        (860.0, 765.1, "SCALE:", "NTS"),
        (900.0, 765.1, "REV:", "2"),
        (1040.8, 765.1, "DRAWING NUMBER:", f"{JOB}_{sheet}"),
        (1131.8, 765.1, "THIS SHEET:", sheet),
        (1175.0, 765.1, "NEXT:", next_sheet),
    )
    for x, y, label, value in fields:
        put(page, x, y, label, LABEL_PT)
        if value:
            put(page, x, y + 11.0, value)


def line_y(line):
    """Displayed baseline of ladder line ``line`` (1-80)."""
    return FIRST_LINE_Y + ((line - 1) % 40) * LINE_PITCH


def ladder_body(page, sheet, lines=80):
    """A power-distribution ladder in DSI's numbering: a line-number gutter of
    ``sheet`` + two-digit line, ``SSSLLI`` wire numbers and ``%F-%S%N`` tags,
    each on the line it encodes.

    Returns ``(wires, tags)`` as printed, so a test can confirm Redline's own
    parsers read the body as the ladder it is meant to be.
    """
    for line in range(1, lines + 1):
        x = GUTTER_X[(line - 1) // 40]
        y = line_y(line)
        put(page, x, y, sheet)
        # Sheet then line as two text items, as ACADE plots them.
        put(page, x + 12.0, y, f"{line:02d}")
    wires, tags = [], []
    for line, index, family in ((5, 0, "CB"), (8, 0, "CB"), (12, 0, "CR"),
                                (12, 1, None), (20, 0, "PS"), (33, 0, "CB")):
        x = GUTTER_X[(line - 1) // 40]
        wire = f"{sheet}{line:02d}{index}"
        put(page, x + 120.0 + 60.0 * index, line_y(line) - 3.0, wire)
        wires.append(wire)
        if family:
            tag = f"{family}-{sheet}{line:02d}"
            put(page, x + 60.0, line_y(line) - 3.0, tag)
            tags.append(tag)
    return wires, tags


def index_body(page, rows):
    """A title page's DRAWING SECTION INDEX: a heading, the column headings,
    then one row per ``(section, description)``, each cell its own text item."""
    x_section, x_description, y = 760.0, 830.0, 120.0
    put(page, x_section, y, "DRAWING SECTION INDEX")
    put(page, x_section, y + 14.0, "DRAWING SECTION")
    put(page, x_description, y + 14.0, "DRAWING DESCRIPTION")
    for i, (section, description) in enumerate(rows):
        row_y = y + 30.0 + 12.0 * i
        put(page, x_section, row_y, section)
        put(page, x_description, row_y, description)


# The section index of an EL-generation title page, as DSI prints it: four of
# the five rows are ranges. Sections and descriptions are generic; the shape is
# the one measured.
EL_INDEX_ROWS = (
    ("000-015", "TITLE PAGE, SYMBOL LEGEND, BOM, PANEL LAYOUTS"),
    ("100", "NETWORK TOPOLOGY"),
    ("300-303", "120VAC POWER DISTRIBUTION"),
    ("400-401", "24VDC POWER DISTRIBUTION"),
    ("600-609", "PLC IO MODULES"),
)

# A set laid out in the measured set's sections and order, plus a terminal-block
# sheet (DSI's 800 section; that set had none), each with the role a person
# reading it would give. Every sheet prints ENCLOSURE NUMBER: in its title
# block, as every real one does; the four 300/400 sheets carry a ladder body.
EL_SET = (
    # (sheet, sheet description, ladder body, role)
    ("000", "TITLE PAGE", False, INDEX),
    ("001", "SYMBOL LEGEND", False, LEGEND),
    ("010", "BILL OF MATERIALS", False, BOM),
    ("011", "RELAY ENCLOSURE LAYOUT", False, LAYOUT),
    ("012", "PLC ENCLOSURE / PANEL LAYOUT", False, LAYOUT),
    ("100", "NETWORK TOPOLOGY", False, TOPOLOGY),
    ("300", "120VAC POWER DISTRIBUTION", True, SCHEMATIC),
    ("301", "120VAC FIELD POWER DISTRIBUTION", True, SCHEMATIC),
    ("400", "PLC PANEL / 24VDC POWER DISTRIBUTION", True, SCHEMATIC),
    ("401", "RELAY CABINET / 24VDC POWER DISTRIBUTION", True, SCHEMATIC),
    ("601", "PLC RACK 1 - SLOT 1 / 24VDC SINKING DIGITAL INPUTS", False, PLC_IO),
    ("605", "PLC RACK 1 - SLOT 6 / 120VAC DIGITAL OUTPUTS", False, PLC_IO),
    ("800", "TERMINAL BLOCK LAYOUT", False, TERMINAL_DETAIL),
)


def build_set(doc, index_rows=EL_INDEX_ROWS):
    """Every sheet of :data:`EL_SET` into ``doc``, the title page carrying
    ``index_rows``. Returns the tags printed on the ladders."""
    tags = []
    for i, (sheet, description, ladder, _role) in enumerate(EL_SET):
        following = EL_SET[i + 1][0] if i + 1 < len(EL_SET) else "END"
        page = new_page(doc)
        title_block(page, description, sheet, following)
        if i == 0:
            index_body(page, index_rows)
        if ladder:
            tags.extend(ladder_body(page, sheet)[1])
    return tags
