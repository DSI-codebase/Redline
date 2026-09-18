"""Offscreen tests for the viewer's text-selection and in-document search."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import fitz
    from PySide6.QtWidgets import QApplication
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _make_text_pdf(path, pages=3):
    d = fitz.open()
    for _ in range(pages):
        p = d.new_page(width=612, height=792)
        p.insert_text((72, 100), "HELLO WORLD apple")
        p.insert_text((72, 140), "FOO apple BAR")
    d.save(path)
    d.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestViewerFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.model.document import Document
        from app.viewer.pdf_view import PdfView
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "text.pdf")
        _make_text_pdf(self.src, 3)
        self.doc = Document(self.src); self.doc.load()
        self.view = PdfView()
        self.view.set_document(self.doc, None)
        self.app.processEvents()

    def tearDown(self):
        try:
            self.doc.close()
        except Exception:
            pass

    # -- search --------------------------------------------------------------

    def test_search_finds_all_matches(self):
        self.view.run_search("apple")
        self.assertEqual(len(self.view._search_matches), 6)   # 2/page * 3
        self.assertEqual(self.view._search_index, 0)

    def test_search_navigation_wraps(self):
        self.view.run_search("WORLD")
        n = len(self.view._search_matches)
        self.assertEqual(n, 3)
        self.view.search_prev()                                # wrap to last
        self.assertEqual(self.view._search_index, n - 1)
        self.view.search_next()                                # wrap to first
        self.assertEqual(self.view._search_index, 0)

    def test_search_no_match_clears(self):
        self.view.run_search("apple")
        self.view.run_search("nope_zzz")
        self.assertEqual(self.view._search_matches, [])
        self.assertEqual(self.view._search_items, [])

    def test_hide_search_clears(self):
        self.view.run_search("apple")
        self.view.hide_search()
        self.assertEqual(self.view._search_matches, [])
        self.assertEqual(self.view._search_items, [])

    def test_show_search_creates_bar(self):
        self.view.show_search()
        self.assertIsNotNone(self.view._search_bar)
        # the view itself isn't shown in the test, so check the bar's own state
        self.assertFalse(self.view._search_bar.isHidden())
        self.view.hide_search()
        self.assertTrue(self.view._search_bar.isHidden())

    # -- text selection ------------------------------------------------------

    def _word(self, page, text):
        for w in self.doc.fitz_doc[page].get_text("words"):
            if w[4] == text:
                return w
        raise AssertionError(text)

    def test_text_selection_and_copy(self):
        page_item = self.view._page_items[0]
        a = self._word(0, "HELLO")
        b = self._word(0, "WORLD")
        self.view._begin_text_selection(0, page_item,
                                        (a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
        self.view._update_text_selection((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        self.assertIn("HELLO", self.view._selected_text)
        self.assertIn("WORLD", self.view._selected_text)
        self.assertGreaterEqual(len(self.view._text_sel_items), 2)
        self.view.copy_selection()
        self.assertEqual(QApplication.clipboard().text(), self.view._selected_text)

    def test_clear_text_selection(self):
        page_item = self.view._page_items[0]
        a = self._word(0, "HELLO")
        self.view._begin_text_selection(0, page_item, a[0], a[1])
        self.view._update_text_selection(a[2], a[3])
        self.view._clear_text_selection()
        self.assertEqual(self.view._selected_text, "")
        self.assertEqual(self.view._text_sel_items, [])

    def test_word_index_at(self):
        from app.viewer.pdf_view import PdfView
        words = self.doc.fitz_doc[0].get_text("words")
        h = self._word(0, "HELLO")
        idx = PdfView._word_index_at(words, (h[0] + h[2]) / 2, (h[1] + h[3]) / 2)
        self.assertEqual(words[idx][4], "HELLO")

    def test_words_to_text_keeps_lines(self):
        from app.viewer.pdf_view import _words_to_text
        words = self.doc.fitz_doc[0].get_text("words")
        text = _words_to_text(words)
        self.assertIn("HELLO WORLD apple", text)
        self.assertIn("\n", text)

    # -- rotated-page alignment (highlights must follow the visible image) ---

    def _rotated_view(self, rot):
        from app.model.document import Document
        from app.viewer.pdf_view import PdfView
        src = os.path.join(self.tmp, f"rot{rot}.pdf")
        d = fitz.open(); p = d.new_page(width=612, height=792)
        p.insert_text((100, 120), "TARGET", fontsize=14)
        p.set_rotation(rot)
        d.save(src); d.close()
        doc = Document(src); doc.load()
        view = PdfView(); view.set_document(doc, None); self.app.processEvents()
        return doc, view

    def _expected_visual(self, page):
        w = next(x for x in page.get_text("words") if x[4] == "TARGET")
        r = fitz.Rect(w[:4]) * page.rotation_matrix
        r.normalize()
        return r

    def test_text_selection_visual_on_rotated_page(self):
        for rot in (90, 270):
            doc, view = self._rotated_view(rot)
            try:
                exp = self._expected_visual(doc.fitz_doc[0])
                vw = next(w for w in view._visual_words(0) if w[4] == "TARGET")
                self.assertAlmostEqual(vw[0], exp.x0, delta=1.0)
                self.assertAlmostEqual(vw[1], exp.y0, delta=1.0)
                # within the visible (rotated) page bounds
                pr = doc.fitz_doc[0].rect
                self.assertTrue(0 <= vw[0] <= pr.width and 0 <= vw[1] <= pr.height)
            finally:
                doc.close()

    def test_search_visual_on_rotated_page(self):
        for rot in (90, 270):
            doc, view = self._rotated_view(rot)
            try:
                exp = self._expected_visual(doc.fitz_doc[0])
                view.run_search("TARGET")
                self.assertEqual(len(view._search_matches), 1)
                _, mr = view._search_matches[0]
                self.assertAlmostEqual(mr.x0, exp.x0, delta=1.0)
                self.assertAlmostEqual(mr.y0, exp.y0, delta=1.0)
            finally:
                doc.close()


if __name__ == "__main__":
    unittest.main()
