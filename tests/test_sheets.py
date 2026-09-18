"""Per-page sheet numbers: title-block auto-detect (string-preserving),
document round-trip, and TODO grouping/export by page vs sheet."""

import os
import tempfile
import unittest

import fitz

from app.extraction.text_extract import read_titleblock_sheet_label
from app.extraction import sheet_number, sheet_role
from app.model.document import Document
from app.model.annotations import Annotation
from app.export.todo_export import _grouped, GROUP_PAGE, GROUP_SHEET, GROUP_NONE


def _make_pdf(path, sheet_texts):
    """One landscape page per entry; entry is the title-block text (or None)."""
    doc = fitz.open()
    for txt in sheet_texts:
        page = doc.new_page(width=792, height=612)   # landscape
        if txt:
            page.insert_text((72, 72), txt)
    doc.save(path)
    doc.close()


class TestTitleblockLabel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_preserves_leading_zeros(self):
        p = os.path.join(self.tmp, "a.pdf")
        _make_pdf(p, ["SHEET 000", "SHEET 261"])
        doc = fitz.open(p)
        self.assertEqual(read_titleblock_sheet_label(doc[0]), "000")
        self.assertEqual(read_titleblock_sheet_label(doc[1]), "261")
        doc.close()

    def test_none_when_absent(self):
        p = os.path.join(self.tmp, "b.pdf")
        _make_pdf(p, ["no sheet here"])
        doc = fitz.open(p)
        self.assertIsNone(read_titleblock_sheet_label(doc[0]))
        doc.close()


class TestDocumentSheetLabels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "draw.pdf")
        _make_pdf(self.src, ["SHEET 000", "SHEET 300", "no titleblock"])

    def test_autodetect_on_load(self):
        doc = Document(self.src)
        doc.load()
        self.assertEqual(doc.sheet_label(0), "000")
        self.assertEqual(doc.sheet_label(1), "300")
        self.assertEqual(doc.sheet_label(2), "")   # not detected -> blank
        doc.close()

    def test_edit_persists_and_overrides_autodetect(self):
        doc = Document(self.src)
        doc.load()
        doc.set_sheet_label(2, "601")      # manual entry on the blank page
        doc.set_sheet_label(1, "300A")     # correct an auto-detected one
        doc.close()

        doc2 = Document(self.src)
        doc2.load()
        self.assertEqual(doc2.sheet_label(2), "601")
        self.assertEqual(doc2.sheet_label(1), "300A")  # saved edit wins over detect
        self.assertEqual(doc2.sheet_label(0), "000")
        doc2.close()

    def test_clear_label(self):
        doc = Document(self.src)
        doc.load()
        doc.set_sheet_label(0, "")
        self.assertEqual(doc.sheet_label(0), "")
        doc.close()


class TestTodoGrouping(unittest.TestCase):
    def test_group_by_page_vs_sheet(self):
        a0 = Annotation(page=0, kind="comment", is_todo=True, text="a")
        a1 = Annotation(page=1, kind="comment", is_todo=True, text="b")
        a2 = Annotation(page=2, kind="comment", is_todo=True, text="c")
        sheets = {0: "000", 1: "300"}   # page 2 has no sheet
        by_page = [h for h, _ in _grouped([a0, a1, a2], GROUP_PAGE, sheets)]
        self.assertEqual(by_page, ["Page 1", "Page 2", "Page 3"])
        by_sheet = [h for h, _ in _grouped([a0, a1, a2], GROUP_SHEET, sheets)]
        self.assertEqual(by_sheet, ["Sheet 000", "Sheet 300", "(no sheet)"])

    def test_no_grouping(self):
        a0 = Annotation(page=0, kind="comment", is_todo=True, text="a")
        out = _grouped([a0], GROUP_NONE, {})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "")


class TestSheetProvenance(unittest.TestCase):
    """Where a page's sheet number came from.

    An audit that cannot tell a number a human confirmed from one a heuristic
    guessed cannot report its own coverage honestly, so every resolved sheet
    records the strategy that produced it.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "draw.pdf")

    def _drawing_number_pdf(self, path, numbers):
        doc = fitz.open()
        for n in numbers:
            page = doc.new_page(width=792, height=1224)
            page.insert_text((40.0, 1000.0), f"EL2507777-{n}", rotate=270)
            page.set_rotation(270)
        doc.save(path)
        doc.close()

    def test_records_the_strategy_that_answered(self):
        self._drawing_number_pdf(self.src, ["000", "300", "601"])
        doc = Document(self.src)
        doc.load()
        self.assertEqual(doc.sheet_label(1), "300")
        self.assertEqual(doc.sheet_source(1), sheet_number.DRAWING_NUMBER)
        self.assertEqual(doc.sheet_confidence(1), 1.0)
        doc.close()

    def test_user_edit_outranks_detection_and_persists(self):
        self._drawing_number_pdf(self.src, ["000", "300"])
        doc = Document(self.src)
        doc.load()
        doc.set_sheet_label(1, "301")
        doc.close()

        again = Document(self.src)
        again.load()
        self.assertEqual(again.sheet_label(1), "301")
        self.assertEqual(again.sheet_source(1), sheet_number.USER)
        # …and detection has not quietly overwritten it.
        self.assertEqual(again.sheet_label(0), "000")
        again.close()

    def test_unresolved_page_reports_zero_confidence(self):
        doc = fitz.open()
        doc.new_page(width=792, height=1224).insert_text((60, 60), "no numbering")
        doc.save(self.src)
        doc.close()
        d = Document(self.src)
        d.load()
        self.assertEqual(d.sheet_label(0), "")
        self.assertEqual(d.sheet_confidence(0), 0.0)
        d.close()

    def test_labels_from_an_older_sidecar_are_marked_unknown(self):
        # A sidecar written before provenance existed carries labels but no
        # sources. They may have been typed or guessed; saying "unknown" is the
        # only honest answer.
        self._drawing_number_pdf(self.src, ["000"])
        doc = Document(self.src)
        doc.load()
        doc.sidecar.set_meta("sheet_labels", '{"0": "777"}')
        doc.sidecar.set_meta("sheet_label_sources", "")
        doc.close()

        again = Document(self.src)
        again.load()
        self.assertEqual(again.sheet_label(0), "777")
        self.assertEqual(again.sheet_source(0), sheet_number.UNKNOWN)
        again.close()


class TestSheetRoles(unittest.TestCase):
    """A sheet's job decides which rules apply to it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "roles.pdf")
        doc = fitz.open()
        for title in ("TITLE PAGE", "BACK PANEL LAYOUT", "24 VDC DISTRIBUTION"):
            page = doc.new_page(width=792, height=1224)
            page.insert_text((40.0, 1000.0), title, rotate=270)
            page.set_rotation(270)
        doc.save(self.src)
        doc.close()

    def test_detects_roles_on_load(self):
        doc = Document(self.src)
        doc.load()
        self.assertEqual(doc.sheet_role_of(0), sheet_role.INDEX)
        self.assertEqual(doc.sheet_role_of(1), sheet_role.LAYOUT)
        self.assertEqual(doc.sheet_role_of(2), sheet_role.SCHEMATIC)
        doc.close()

    def test_override_persists_and_survives_redetection(self):
        doc = Document(self.src)
        doc.load()
        doc.set_sheet_role(2, sheet_role.PLC_IO)
        doc.close()

        again = Document(self.src)
        again.load()
        self.assertEqual(again.sheet_role_of(2), sheet_role.PLC_IO)
        self.assertEqual(again.sheet_role_of(0), sheet_role.INDEX)
        again.close()

    def test_clearing_an_override_returns_to_detection(self):
        doc = Document(self.src)
        doc.load()
        doc.set_sheet_role(1, sheet_role.PLC_IO)
        doc.set_sheet_role(1, "")
        doc.close()

        again = Document(self.src)
        again.load()
        self.assertEqual(again.sheet_role_of(1), sheet_role.LAYOUT)
        again.close()


if __name__ == "__main__":
    unittest.main()
