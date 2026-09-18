"""Sheet-role detection.

Role is what keeps a location rule from firing on pages whose whole purpose is
to reference devices drawn elsewhere. Measured on a real plot, role awareness
removes 92% of tag-location hits, essentially all of which were correct
drafting rather than defects.
"""

import unittest

import fitz

from app.extraction.sheet_role import (
    SheetRoleConfig, detect_role, detect_document_roles, role_from_text,
    SCHEMATIC, PLC_IO, LAYOUT, TERMINAL_DETAIL, TOPOLOGY, BOM, INDEX, LEGEND,
    REFERENCING_ROLES, ROLE_LABELS, ROLES,
)

W, H = 792.0, 1224.0   # portrait, as plotted; rotated 270 for display


def _title_block(page, title):
    """Write ``title`` the way AutoCAD Electrical plots it.

    On a sheet rotated 270 for display, title-block text is written rotated so
    it reads horizontally on screen: successive words share an unrotated x and
    step down in unrotated y. Writing it unrotated instead produces a title that
    displays *vertically*, which is not what any real plot looks like -- and a
    fixture that unrealistic tests the wrong thing.
    """
    page.insert_text((40.0, 1000.0), title, rotate=270)


def _sheet(title, rotation=270, body=""):
    """A page with ``title`` in the title block and optional body text."""
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    _title_block(page, title)
    if body:
        # insert_text does not wrap, so a long string simply runs off the page
        # and never reaches the text layer. Lay the body out as real lines.
        for i, line in enumerate(body):
            page.insert_text((300.0, 200.0 + i * 14.0), line)
    page.set_rotation(rotation)
    return doc, page


class TestRoleFromText(unittest.TestCase):
    def test_maps_real_titles(self):
        cases = [
            ("TITLE PAGE", INDEX),
            ("SYMBOLS PAGE", LEGEND),
            ("BILL OF MATERIALS", BOM),
            ("ENCLOSURE LAYOUT", LAYOUT),
            ("BACK PANEL LAYOUT", LAYOUT),
            ("NETWORK TOPOLOGY", TOPOLOGY),
            ("DIGITAL INPUTS SLOT 1", PLC_IO),
            ("DIGITAL OUTPUTS SLOT 2", PLC_IO),
            ("TERMINAL BLOCK LAYOUT", TERMINAL_DETAIL),
        ]
        for title, want in cases:
            self.assertEqual(role_from_text(title), want, title)

    def test_terminal_block_beats_layout(self):
        # Both keywords are present; the more specific one has to win, or every
        # terminal sheet is misfiled as a panel layout.
        self.assertEqual(role_from_text("TERMINAL BLOCK LAYOUT"), TERMINAL_DETAIL)

    def test_case_and_spacing_insensitive(self):
        self.assertEqual(role_from_text("  bill   of    materials "), BOM)

    def test_ordinary_schematic_titles_imply_nothing(self):
        for title in ("110 VAC DISTRIBUTION", "24 VDC DISTRIBUTION",
                      "SAFETY RELAY", "VFD/MOTOR WIRING"):
            self.assertIsNone(role_from_text(title), title)


class TestDetectRole(unittest.TestCase):
    def test_reads_the_title_block_on_a_rotated_page(self):
        doc, page = _sheet("TERMINAL BLOCK LAYOUT")
        self.assertEqual(detect_role(page), TERMINAL_DETAIL)
        doc.close()

    def test_defaults_to_schematic(self):
        doc, page = _sheet("110 VAC DISTRIBUTION")
        self.assertEqual(detect_role(page), SCHEMATIC)
        doc.close()

    def test_ignores_a_keyword_in_the_drawing_body_on_a_busy_page(self):
        # "TERMINAL BLOCK" appears in a note, not the title block. A busy page
        # must not be reclassified by its body text.
        body = [
            "NOTE: ALL FIELD WIRING LANDS ON A TERMINAL BLOCK IN THE",
            "MAIN ENCLOSURE. USE FERRULES ON ALL STRANDED CONDUCTORS",
            "AND LABEL BOTH ENDS OF EVERY WIRE WITH HEAT SHRINK",
            "MARKERS SO THAT THE MARKER IS LEGIBLE WITHOUT TWISTING",
            "OR PULLING ON THE WIRE. LEAVE ENOUGH SLACK AT EVERY",
            "TERMINATION THAT THE DEVICE CAN MOVE TWO INCHES IN ANY",
            "DIRECTION WITHOUT STRAIN ON THE JOINT. WIRES TRAVELING",
            "IN A COMMON BUNDLE SHALL RUN PARALLEL AND MUST NOT DIVE",
            "IN AND OUT OR TWIST AROUND ONE ANOTHER. ROUTE EVERY",
            "BUNDLE VERTICALLY OR HORIZONTALLY WHEREVER POSSIBLE.",
            "USE WIRE ANCHORS OF THE SCREW TYPE WHEREVER ONE FITS.",
        ]
        doc, page = _sheet("24 VDC DISTRIBUTION", body=body)
        self.assertEqual(detect_role(page), SCHEMATIC)
        doc.close()

    def test_unrotated_pages_work_too(self):
        doc = fitz.open()
        page = doc.new_page(width=1224.0, height=792.0)
        page.insert_text((900.0, 760.0), "NETWORK TOPOLOGY")
        self.assertEqual(detect_role(page), TOPOLOGY)
        doc.close()


class TestDocumentRoles(unittest.TestCase):
    def test_classifies_a_whole_set(self):
        titles = ["TITLE PAGE", "SYMBOLS PAGE", "BILL OF MATERIALS",
                  "BACK PANEL LAYOUT", "DIGITAL INPUTS", "TERMINAL BLOCK LAYOUT",
                  "24 VDC DISTRIBUTION"]
        doc = fitz.open()
        for t in titles:
            page = doc.new_page(width=W, height=H)
            _title_block(page, t)
            page.set_rotation(270)
        got = detect_document_roles(doc)
        self.assertEqual(
            [got[i] for i in range(len(titles))],
            [INDEX, LEGEND, BOM, LAYOUT, PLC_IO, TERMINAL_DETAIL, SCHEMATIC])
        doc.close()


class TestVocabulary(unittest.TestCase):
    def test_referencing_roles_exclude_the_ones_rules_apply_to(self):
        self.assertNotIn(SCHEMATIC, REFERENCING_ROLES)
        self.assertNotIn(PLC_IO, REFERENCING_ROLES)
        self.assertIn(LAYOUT, REFERENCING_ROLES)
        self.assertIn(TERMINAL_DETAIL, REFERENCING_ROLES)

    def test_every_role_has_a_label(self):
        for role in ROLES:
            self.assertIn(role, ROLE_LABELS)


if __name__ == "__main__":
    unittest.main()
