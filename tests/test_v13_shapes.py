"""v1.3 markup changes:

* circle and line tools (rectangle / arrow behaviour, different shape)
* the callout is placed arrow-first with three clicks, and its leader travels
  with the box when the box is moved.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import (
    Annotation, COPYABLE_KINDS, KIND_CIRCLE, KIND_LINE, KIND_ARROW, KIND_RECT,
    KIND_CALLOUT,
)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF
    from app.viewer.pdf_view import PdfView
    from app.viewer import tools as T
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _doc(dirpath, name="d.pdf"):
    from app.model.document import Document
    src = os.path.join(dirpath, name)
    d = fitz.open(); d.new_page(width=400, height=300); d.save(src); d.close()
    doc = Document(src); doc.load()
    return doc, src


class TestCircleLineModel(unittest.TestCase):
    def test_new_kinds_are_copyable(self):
        self.assertIn(KIND_CIRCLE, COPYABLE_KINDS)
        self.assertIn(KIND_LINE, COPYABLE_KINDS)

    def test_pdf_roundtrip_keeps_the_kinds_apart(self):
        tmp = tempfile.mkdtemp()
        doc, _ = _doc(tmp)
        doc.store.add(Annotation(page=0, kind=KIND_CIRCLE, rect=(20, 20, 140, 100),
                                 color=(1, 0, 0), fill_color=(0, 0, 1),
                                 fill_opacity=0.5, width=2), silent=True)
        doc.store.add(Annotation(page=0, kind=KIND_LINE, rect=(200, 50, 340, 120),
                                 color=(0, .6, 0), width=3), silent=True)
        doc.store.add(Annotation(page=0, kind=KIND_ARROW, rect=(200, 150, 340, 220),
                                 color=(0, 0, 1), width=3), silent=True)
        out = doc.save(); doc.close()

        chk = fitz.open(out)
        try:
            self.assertEqual(sorted(a.type[1] for a in chk[0].annots()),
                             ["Circle", "Line", "Line"])
        finally:
            chk.close()

        from app.model.document import Document
        back = Document(out); back.load()
        try:
            kinds = sorted(a.kind for a in back.store.all())
            # the two "Line" annots come back as arrow vs line via the arrowhead
            self.assertEqual(kinds, [KIND_ARROW, KIND_CIRCLE, KIND_LINE])
            circ = next(a for a in back.store.all() if a.kind == KIND_CIRCLE)
            self.assertIsNotNone(circ.fill_color)          # circles keep their fill
            self.assertAlmostEqual(circ.fill_opacity, 0.5, delta=0.02)
        finally:
            back.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestCircleLineDrawing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        tmp = tempfile.mkdtemp()
        doc, _ = _doc(tmp)
        v = PdfView(); v.set_document(doc, None)
        return doc, v

    def _drag(self, v, tool, a, b):
        v.tool.current = tool
        page = v._page_items[0]
        v._begin_draft(page.mapToScene(QPointF(*a)))
        v._update_draft(page.mapToScene(QPointF(*b)))
        v._finish_draft()

    def test_circle_draws_like_a_rectangle(self):
        doc, v = self._view()
        self._drag(v, T.TOOL_CIRCLE, (30, 30), (150, 110))
        a = doc.store.all()[0]
        self.assertEqual(a.kind, KIND_CIRCLE)
        # normalised to a bounding box, exactly like the rectangle
        self.assertEqual(tuple(round(q) for q in a.rect), (30, 30, 150, 110))
        from app.viewer.annotation_items import EllipseShapeItem
        self.assertIsInstance(v._item_by_ann[a.id], EllipseShapeItem)
        doc.close()

    def test_line_keeps_its_endpoints_like_an_arrow(self):
        doc, v = self._view()
        # drawn right-to-left: endpoints must NOT be normalised away
        self._drag(v, T.TOOL_LINE, (300, 200), (120, 60))
        a = doc.store.all()[0]
        self.assertEqual(a.kind, KIND_LINE)
        self.assertEqual(tuple(round(q) for q in a.rect), (300, 200, 120, 60))
        from app.viewer.annotation_items import LineItem
        self.assertIsInstance(v._item_by_ann[a.id], LineItem)
        doc.close()

    def test_tiny_drag_is_discarded(self):
        doc, v = self._view()
        self._drag(v, T.TOOL_CIRCLE, (30, 30), (31, 31))
        self.assertEqual(doc.store.all(), [])
        doc.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestCalloutThreeClicks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self, accept=True):
        tmp = tempfile.mkdtemp()
        doc, _ = _doc(tmp)
        v = PdfView(); v.set_document(doc, None)
        v.new_text_prompt = lambda ann, tb: (accept, "NOTE", False)
        v.tool.current = T.TOOL_CALLOUT
        return doc, v

    def _click(self, v, x, y):
        v._callout_click(v._page_items[0].mapToScene(QPointF(x, y)))

    def test_arrow_then_box(self):
        doc, v = self._view()
        self._click(v, 50, 50)                      # 1: what the arrow points at
        self.assertEqual(v._co_stage, 1)
        self.assertEqual(v._draft.kind, KIND_ARROW)  # previews the arrow first
        self._click(v, 150, 120)                     # 2: arrow end == box corner
        self.assertEqual(v._co_stage, 2)
        self.assertEqual(v._draft.kind, KIND_CALLOUT)
        self._click(v, 280, 200)                     # 3: finish the box
        self.assertEqual(v._co_stage, 0)

        a = doc.store.all()[0]
        self.assertEqual(a.kind, KIND_CALLOUT)
        self.assertEqual(tuple(round(q) for q in a.rect), (150, 120, 280, 200))
        self.assertEqual(tuple(round(q) for q in a.callout_point), (50, 50))
        self.assertEqual(a.text, "NOTE")
        doc.close()

    def test_box_starts_at_the_arrow_end_whichever_way_it_is_drawn(self):
        doc, v = self._view()
        self._click(v, 300, 250)
        self._click(v, 200, 180)
        self._click(v, 80, 60)          # drag back up-left
        a = doc.store.all()[0]
        self.assertEqual(tuple(round(q) for q in a.rect), (80, 60, 200, 180))
        doc.close()

    def test_escape_abandons_a_half_placed_callout(self):
        doc, v = self._view()
        self._click(v, 50, 50)
        self._click(v, 150, 120)
        v.cancel_action()
        self.assertEqual(v._co_stage, 0)
        self.assertEqual(doc.store.all(), [])
        self.assertIsNone(v._draft)
        doc.close()

    def test_cancelling_the_text_prompt_discards_it(self):
        doc, v = self._view(accept=False)
        self._click(v, 50, 50); self._click(v, 150, 120); self._click(v, 280, 200)
        self.assertEqual(doc.store.all(), [])
        self.assertEqual(v._co_stage, 0)
        doc.close()

    def test_tiny_box_keeps_drawing_instead_of_committing(self):
        doc, v = self._view()
        self._click(v, 50, 50); self._click(v, 150, 120)
        self._click(v, 151, 121)         # too small to be a box
        self.assertEqual(doc.store.all(), [])
        self.assertEqual(v._co_stage, 2)  # still placing
        doc.close()

    def test_new_document_resets_a_half_placed_callout(self):
        doc, v = self._view()
        self._click(v, 50, 50)
        tmp = tempfile.mkdtemp()
        doc2, _ = _doc(tmp, "other.pdf")
        v.set_document(doc2, None)
        self.assertEqual(v._co_stage, 0)
        self.assertIsNone(v._co_page)
        doc.close(); doc2.close()


if __name__ == "__main__":
    unittest.main()
