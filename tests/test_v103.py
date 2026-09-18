"""v1.0.3 fixes: family codes, component re-flag, single-sidecar / no double
save, corner sheet detection, TODO filter-all-columns + no-drag, grip marker,
and wire/component jump routing."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.extraction.component_parser import (
    DEFAULT_FAMILY_CODES, ComponentConfig, ComponentParser, reclassify,
    FLAG_UNKNOWN_FAMILY,
)
from app.extraction.wire_parser import Token, SOURCE_TEXT
from app.model import storage
from app.model.document import Document
from app.model.annotations import Annotation, KIND_HIGHLIGHT
from app.extraction.text_extract import read_titleblock_sheet_label, _corner_sheet_label

try:
    from PySide6.QtWidgets import QApplication
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


# --- Bug 7 / Bug 8 : family codes + re-flag --------------------------------

class TestFamilyCodes(unittest.TestCase):
    def test_new_codes_present(self):
        for code in ("CBL", "DV", "EN", "DN", "GND", "PDB", "PRS", "PW", "SCR", "SE", "X"):
            self.assertIn(code, DEFAULT_FAMILY_CODES)

    def test_reclassify_clears_unknown_flag_after_codes_added(self):
        # extract with a code NOT known -> flagged unknown
        cfg = ComponentConfig(families=("LT",))
        tok = Token(text="GND-10010", x=0, y=0, page=0, layer=None, source=SOURCE_TEXT)
        comps = ComponentParser(cfg).parse([tok])
        self.assertTrue(comps and comps[0].unknown_family)
        # user adds GND in Settings -> reclassify with new config clears the flag
        reclassify(comps, ComponentConfig(families=("LT", "GND")))
        self.assertFalse(comps[0].unknown_family)
        self.assertNotIn(FLAG_UNKNOWN_FAMILY, comps[0].flags)


# --- Feature 4 : single sidecar / single .marked.pdf -----------------------

class TestSingleSidecar(unittest.TestCase):
    def test_canonical_paths(self):
        self.assertEqual(storage.sidecar_path("/d/foo.pdf"),
                         storage.sidecar_path("/d/foo.marked.pdf"))
        self.assertEqual(storage.marked_pdf_path("/d/foo.pdf"), "/d/foo.marked.pdf")
        # never foo.marked.marked.pdf
        self.assertEqual(storage.marked_pdf_path("/d/foo.marked.pdf"), "/d/foo.marked.pdf")
        self.assertEqual(storage.original_pdf_path("/d/foo.marked.pdf"), "/d/foo.pdf")
        self.assertTrue(storage.is_marked_pdf("/d/foo.marked.pdf"))
        self.assertFalse(storage.is_marked_pdf("/d/foo.pdf"))

    def _make_pdf(self, path):
        d = fitz.open(); d.new_page(width=400, height=300); d.save(path); d.close()

    def _annot_count(self, path):
        d = fitz.open(path)
        n = sum(len(list(pg.annots() or [])) for pg in d)
        d.close()
        return n

    def test_resave_from_marked_base_does_not_double(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._make_pdf(src)
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_HIGHLIGHT, rect=(40, 40, 120, 70)))
        marked = doc.save()
        doc.close()
        self.assertTrue(marked.endswith(".marked.pdf"))
        self.assertEqual(self._annot_count(marked), 1)

        # delete the original so the next save is forced to base on the marked
        os.remove(src)
        doc2 = Document(marked); doc2.load()
        marked2 = doc2.save()                          # in-place save over the open file
        self.assertEqual(marked2, marked)             # one .marked.pdf, no .marked.marked
        self.assertEqual(self._annot_count(marked2), 1)  # not doubled
        # the Document reopened the file it just replaced and stays usable
        self.assertEqual(doc2.page_count, 1)
        self.assertEqual(os.path.abspath(doc2.path), os.path.abspath(marked))
        doc2.save()                                    # repeated in-place save is fine
        self.assertEqual(self._annot_count(marked), 1)
        doc2.close()

    def test_sidecar_recreated_flag(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._make_pdf(src)
        marked = os.path.join(tmp, "draw.marked.pdf")
        self._make_pdf(marked)            # a marked file with NO sidecar next to it
        doc = Document(marked)
        self.assertTrue(doc.sidecar_recreated)
        doc.close()


# --- Bug 4 : bottom-right corner sheet number ------------------------------

class TestCornerSheet(unittest.TestCase):
    def test_lesser_of_two_corner_numbers(self):
        d = fitz.open(); pg = d.new_page(width=792, height=612)
        # two numbers in the bottom-right corner: sheet 902 + total 920
        pg.insert_text((720, 560), "902")
        pg.insert_text((720, 580), "920")
        pg.insert_text((60, 60), "300120")    # a wire number, top-left — ignored
        self.assertEqual(_corner_sheet_label(d[0]), "902")
        self.assertEqual(read_titleblock_sheet_label(d[0]), "902")
        d.close()

    def test_keyword_still_wins(self):
        d = fitz.open(); pg = d.new_page(width=792, height=612)
        pg.insert_text((300, 300), "SHEET 261")
        self.assertEqual(read_titleblock_sheet_label(d[0]), "261")
        d.close()

    def test_empty_corner_returns_none(self):
        d = fitz.open(); d.new_page(width=792, height=612)
        self.assertIsNone(_corner_sheet_label(d[0]))
        d.close()


# --- GUI-backed checks (offscreen) -----------------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestTodoFilterAndDrag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_filter_matches_all_columns_and_no_drag(self):
        from app.panels.todo_panel import TodoPanel
        from PySide6.QtWidgets import QAbstractItemView
        tp = TodoPanel()
        self.assertEqual(tp.tree.dragDropMode(), QAbstractItemView.NoDragDrop)
        a = Annotation(page=4, kind="comment", is_todo=True, text="check breaker",
                       author="Eli", tags=["RFI", "priority"])
        hay = tp._row_haystack(a)
        self.assertIn("rfi", hay)        # tag
        self.assertIn("eli", hay)        # commenter
        self.assertIn("5", hay)          # page (4 -> "5")
        self.assertIn("check breaker", hay)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestGripsAndJump(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_grips_marked(self):
        from app.viewer.annotation_items import _HandleItem, _RotateHandle
        self.assertTrue(getattr(_HandleItem, "_is_grip", False))
        self.assertTrue(getattr(_RotateHandle, "_is_grip", False))

    def test_wire_jump_routes_to_location(self):
        from app.main_window import MainWindow

        class _Wire:
            page, x, y = 2, 123.0, 45.0

        win = MainWindow()
        calls = []
        win.view.go_to_location = lambda p, x, y: calls.append((p, x, y))
        win._jump_to(_Wire())
        self.assertEqual(calls, [(2, 123.0, 45.0)])


if __name__ == "__main__":
    unittest.main()
