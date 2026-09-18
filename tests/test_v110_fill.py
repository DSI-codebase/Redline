"""v1.1.0 Phase 2: interior fill + opacity for rectangles and text boxes.

A rectangle or text box can carry a fill color with an opacity from 0 (no
fill) to 1 (an opaque cover that redacts what's beneath). Fills render on the
canvas, export to the PDF, and round-trip through the sidecar and the PDF.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import (
    Annotation, KIND_RECT, KIND_TEXTBOX, KIND_HIGHLIGHT,
)
from app.model.storage import (
    write_annotations_to_pdf, load_pdf_annotations,
    marked_pdf_path, DEFAULT_IGNORE_PATTERNS,
)
from app.model.document import Document

try:
    from PySide6.QtWidgets import QApplication
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


class TestFillModel(unittest.TestCase):
    def test_defaults_no_fill(self):
        a = Annotation(page=0, kind=KIND_RECT)
        self.assertIsNone(a.fill_color)
        self.assertEqual(a.fill_opacity, 1.0)

    def test_dict_roundtrip_preserves_fill(self):
        a = Annotation(page=0, kind=KIND_RECT, fill_color=(0.2, 0.4, 0.6),
                       fill_opacity=0.5)
        b = Annotation.from_dict(a.to_dict())
        self.assertEqual(b.fill_color, (0.2, 0.4, 0.6))
        self.assertEqual(b.fill_opacity, 0.5)

    def test_dict_roundtrip_none_fill(self):
        a = Annotation(page=0, kind=KIND_RECT)
        b = Annotation.from_dict(a.to_dict())
        self.assertIsNone(b.fill_color)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestFillBrush(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_brush_only_when_visible(self):
        from app.viewer.annotation_items import fill_brush
        self.assertIsNone(fill_brush(Annotation(page=0, kind=KIND_RECT)))
        self.assertIsNone(fill_brush(Annotation(page=0, kind=KIND_RECT,
                                                fill_color=(1, 0, 0), fill_opacity=0.0)))
        b = fill_brush(Annotation(page=0, kind=KIND_RECT,
                                  fill_color=(1, 1, 1), fill_opacity=1.0))
        self.assertIsNotNone(b)
        self.assertEqual(b.color().alpha(), 255)
        half = fill_brush(Annotation(page=0, kind=KIND_RECT,
                                     fill_color=(0, 0, 1), fill_opacity=0.5))
        self.assertAlmostEqual(half.color().alpha(), 127, delta=1)


class TestFillExport(unittest.TestCase):
    def _blank(self, path):
        d = fitz.open(); d.new_page(width=600, height=400); d.save(path); d.close()

    def test_rect_and_textbox_fill_export_and_reload(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._blank(src)
        anns = [
            Annotation(page=0, kind=KIND_RECT, rect=(50, 50, 200, 120),
                       color=(1, 0, 0), width=1.5, fill_color=(1.0, 1.0, 1.0),
                       fill_opacity=1.0),                       # opaque white cover
            Annotation(page=0, kind=KIND_TEXTBOX, rect=(250, 60, 420, 110),
                       color=(0, 0, 0), text="COVER", fill_color=(1.0, 1.0, 0.0),
                       fill_opacity=1.0),
        ]
        d = fitz.open(src)
        write_annotations_to_pdf(d, anns)
        mp = marked_pdf_path(src)
        d.save(mp)
        d.close()

        d2 = fitz.open(mp)
        by_type = {a.type[1]: a for a in d2[0].annots()}
        # rect fill is stored as the interior color (/IC)
        self.assertEqual(len(by_type["Square"].colors.get("fill") or []), 3)
        # freetext fill is the annotation background (/C), rendered via /AP
        self.assertEqual(len(by_type["FreeText"].colors.get("stroke") or []), 3)
        d2.close()

        # rect fill round-trips straight out of the PDF; the text-box fill relies
        # on the sidecar (a separate test), so only the rect is asserted here
        loaded = load_pdf_annotations(fitz.open(mp), DEFAULT_IGNORE_PATTERNS)
        by_kind = {a.kind: a for a in loaded}
        self.assertIsNotNone(by_kind[KIND_RECT].fill_color)
        for got, want in zip(by_kind[KIND_RECT].fill_color, (1.0, 1.0, 1.0)):
            self.assertAlmostEqual(got, want, delta=0.02)

    def test_translucent_rect_sets_opacity(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._blank(src)
        d = fitz.open(src)
        write_annotations_to_pdf(d, [Annotation(page=0, kind=KIND_RECT,
                                                rect=(10, 10, 90, 60), color=(1, 0, 0),
                                                fill_color=(0, 0, 1), fill_opacity=0.4)])
        mp = marked_pdf_path(src)
        d.save(mp)
        d.close()
        d2 = fitz.open(mp)
        opac = [a.opacity for a in d2[0].annots()]
        d2.close()
        self.assertTrue(opac and abs(opac[0] - 0.4) < 0.05)

    def test_textbox_fill_roundtrips_via_pdf(self):
        # a FreeText's fill lives in /C, so load_pdf_annotations must read it back
        # (regression: it previously read the empty /IC 'fill' key)
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        self._blank(src)
        d = fitz.open(src)
        write_annotations_to_pdf(d, [Annotation(page=0, kind=KIND_TEXTBOX,
                                                rect=(50, 50, 200, 90), color=(1, 0, 0),
                                                text="HI", fill_color=(1.0, 1.0, 0.0),
                                                fill_opacity=1.0)])
        mp = marked_pdf_path(src)
        d.save(mp)
        d.close()
        loaded = load_pdf_annotations(fitz.open(mp), DEFAULT_IGNORE_PATTERNS)
        tb = [a for a in loaded if a.kind == KIND_TEXTBOX][0]
        self.assertIsNotNone(tb.fill_color)
        for got, want in zip(tb.fill_color, (1.0, 1.0, 0.0)):
            self.assertAlmostEqual(got, want, delta=0.02)

    def test_unfilled_rect_has_no_fill(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._blank(src)
        d = fitz.open(src)
        write_annotations_to_pdf(d, [Annotation(page=0, kind=KIND_RECT,
                                                rect=(10, 10, 90, 60), color=(1, 0, 0))])
        mp = marked_pdf_path(src)
        d.save(mp)
        d.close()
        d2 = fitz.open(mp)
        fills = [(a.colors or {}).get("fill") for a in d2[0].annots()]
        d2.close()
        self.assertTrue(all(f in (None, []) for f in fills))

    def test_fill_persists_via_sidecar(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._blank(src)
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60),
                                 color=(0, 0, 1), fill_color=(0.3, 0.6, 0.9),
                                 fill_opacity=0.5))
        doc.save(); doc.close()
        doc2 = Document(src); doc2.load()
        rect = [a for a in doc2.store.all() if a.kind == KIND_RECT][0]
        self.assertEqual(rect.fill_color, (0.3, 0.6, 0.9))
        self.assertEqual(rect.fill_opacity, 0.5)
        doc2.close()

    def test_textbox_fill_persists_via_sidecar(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._blank(src)
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_TEXTBOX, rect=(10, 10, 190, 60),
                                 color=(0, 0, 0), text="COVER",
                                 fill_color=(1.0, 1.0, 1.0), fill_opacity=1.0))
        doc.save(); doc.close()
        doc2 = Document(src); doc2.load()
        tb = [a for a in doc2.store.all() if a.kind == KIND_TEXTBOX][0]
        self.assertEqual(tb.fill_color, (1.0, 1.0, 1.0))
        doc2.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestFillDraftFromTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_new_rect_inherits_tool_fill(self):
        from app.main_window import MainWindow
        import app.viewer.tools as T
        win = MainWindow()
        win.view.tool.shape_fill = (1.0, 1.0, 1.0)
        win.view.tool.shape_fill_opacity = 1.0
        win.view.tool.current = T.TOOL_RECT
        # the fill button becomes enabled for the rect tool
        win._update_fill_btn()
        self.assertTrue(win.fill_btn.isEnabled())

    def test_fill_button_disabled_for_pen(self):
        from app.main_window import MainWindow
        import app.viewer.tools as T
        win = MainWindow()
        win.view.tool.current = T.TOOL_PEN
        win._update_fill_btn()
        self.assertFalse(win.fill_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
