"""v1.1.0 Phase 4: revision-cloud tool (freehand + click-polygon, outline only)."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import Annotation, KIND_CLOUD
from app.model.storage import write_annotations_to_pdf, marked_pdf_path
from app.model.document import Document

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


class TestCloudModel(unittest.TestCase):
    def test_points_roundtrip(self):
        a = Annotation(page=0, kind=KIND_CLOUD,
                       points=[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)])
        b = Annotation.from_dict(a.to_dict())
        self.assertEqual(b.points, [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)])

    def test_cloud_not_comment_unless_noted(self):
        self.assertFalse(Annotation(page=0, kind=KIND_CLOUD).shows_in_comments)
        self.assertTrue(Annotation(page=0, kind=KIND_CLOUD, text="rev A").shows_in_comments)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestCloudPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scallop_path_nonempty(self):
        from app.viewer.annotation_items import cloud_path
        p = cloud_path([(0, 0), (100, 0), (100, 80), (0, 80)], radius=9.0)
        self.assertFalse(p.isEmpty())
        self.assertGreater(p.elementCount(), 10)

    def test_single_point_is_a_dot(self):
        from app.viewer.annotation_items import cloud_path
        p = cloud_path([(10, 10)], radius=9.0)
        self.assertFalse(p.isEmpty())

    def test_item_bounding_covers_polygon(self):
        from app.viewer.annotation_items import make_item, CloudItem
        from app.model.annotations import AnnotationStore

        class _V:
            select_mode = True
            store = AnnotationStore()
        it = make_item(Annotation(page=0, kind=KIND_CLOUD,
                                  points=[(0, 0), (100, 0), (100, 80), (0, 80)],
                                  color=(1, 0, 0), width=1.5), _V())
        self.assertIsInstance(it, CloudItem)
        br = it.boundingRect()
        self.assertGreaterEqual(br.width(), 100)
        self.assertGreaterEqual(br.height(), 80)


class TestCloudExport(unittest.TestCase):
    def _blank(self, path):
        d = fitz.open(); d.new_page(width=400, height=300); d.save(path); d.close()

    def test_export_polygon_with_cloud_effect(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        self._blank(src)
        ann = Annotation(page=0, kind=KIND_CLOUD, color=(1, 0, 0), width=1.5,
                         points=[(50, 50), (150, 40), (160, 120), (60, 130)])
        d = fitz.open(src)
        self.assertEqual(write_annotations_to_pdf(d, [ann]), 1)
        mp = marked_pdf_path(src)
        d.save(mp)
        d.close()
        d2 = fitz.open(mp)
        got = [(a.type[1], d2.xref_get_key(a.xref, "BE")) for a in d2[0].annots()]
        d2.close()
        self.assertEqual(len(got), 1)
        typ, be = got[0]
        self.assertEqual(typ, "Polygon")
        self.assertEqual(be[0], "dict")
        self.assertIn("/C", be[1])          # cloudy border effect

    def test_under_three_points_not_written(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        self._blank(src)
        d = fitz.open(src)
        n = write_annotations_to_pdf(d, [Annotation(page=0, kind=KIND_CLOUD,
                                                    points=[(10, 10), (20, 20)])])
        d.close()
        self.assertEqual(n, 0)

    def test_cloud_roundtrips_via_sidecar(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        self._blank(src)
        pts = [(50, 50), (150, 40), (160, 120), (60, 130)]
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_CLOUD, points=pts, color=(1, 0, 0)))
        doc.save(); doc.close()
        doc2 = Document(src); doc2.load()
        c = [a for a in doc2.store.all() if a.kind == KIND_CLOUD][0]
        self.assertEqual(len(c.points), 4)
        doc2.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestCloudInteraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _win(self):
        import app.viewer.tools as T
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(src); d.close()
        win = MainWindow(); win.load_document(src)
        win.view.tool.current = T.TOOL_CLOUD
        return win

    def test_polygon_clicks_build_and_close(self):
        win = self._win()
        v = win.view
        page = v._page_items[0]
        for lx, ly in [(50, 50), (150, 50), (150, 120), (50, 120)]:
            pt = page.mapToScene(QPointF(lx, ly))
            v._cloud_press = pt
            v._cloud_on_release(pt)
        self.assertEqual(len(v._cloud_pts), 4)
        v._cloud_finish()
        clouds = [a for a in v.store.all() if a.kind == KIND_CLOUD]
        self.assertEqual(len(clouds), 1)
        self.assertEqual(len(clouds[0].points), 4)

    def test_polygon_under_three_vertices_discarded(self):
        win = self._win()
        v = win.view
        page = v._page_items[0]
        for lx, ly in [(50, 50), (150, 50)]:
            pt = page.mapToScene(QPointF(lx, ly))
            v._cloud_press = pt
            v._cloud_on_release(pt)
        v._cloud_finish()
        self.assertEqual([a for a in v.store.all() if a.kind == KIND_CLOUD], [])

    def test_drag_starts_freehand_cloud(self):
        win = self._win()
        v = win.view
        page = v._page_items[0]
        v._cloud_press = page.mapToScene(QPointF(200, 200))
        handled = v._cloud_on_move(page.mapToScene(QPointF(240, 240)))
        self.assertTrue(handled)
        self.assertIsNotNone(v._draft)
        self.assertEqual(v._draft.kind, KIND_CLOUD)

    def test_escape_cancels_polygon(self):
        win = self._win()
        v = win.view
        page = v._page_items[0]
        pt = page.mapToScene(QPointF(50, 50))
        v._cloud_press = pt
        v._cloud_on_release(pt)
        self.assertIsNotNone(v._cloud_pts)
        v.cancel_action()
        self.assertIsNone(v._cloud_pts)
        self.assertEqual([a for a in v.store.all() if a.kind == KIND_CLOUD], [])

    def test_switching_tools_abandons_polygon(self):
        import app.viewer.tools as T
        win = self._win()
        v = win.view
        page = v._page_items[0]
        for lx, ly in [(50, 50), (150, 50)]:
            pt = page.mapToScene(QPointF(lx, ly))
            v._cloud_press = pt
            v._cloud_on_release(pt)
        self.assertIsNotNone(v._cloud_pts)
        self.assertIn("__cloudpreview__", v._item_by_ann)
        win._set_tool(T.TOOL_SELECT)        # leaving the cloud tool mid-polygon
        self.assertIsNone(v._cloud_pts)
        self.assertNotIn("__cloudpreview__", v._item_by_ann)
        self.assertEqual([a for a in v.store.all() if a.kind == KIND_CLOUD], [])

    def test_opening_new_doc_clears_polygon_state(self):
        import tempfile, fitz
        win = self._win()
        v = win.view
        page = v._page_items[0]
        # start a polygon (persists between clicks, references the current page)
        pt = page.mapToScene(QPointF(50, 50))
        v._cloud_press = pt
        v._cloud_on_release(pt)
        self.assertIsNotNone(v._cloud_page)
        # open a different document without cancelling first
        tmp = tempfile.mkdtemp()
        src2 = os.path.join(tmp, "d2.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(src2); d.close()
        from app.model.document import Document
        doc2 = Document(src2); doc2.load()
        v.set_document(doc2, v.config)
        # stale state referencing the destroyed page must be gone (no crash)
        self.assertIsNone(v._cloud_pts)
        self.assertIsNone(v._cloud_page)
        self.assertIsNone(v._cloud_press)
        # a fresh cloud click on the new doc works without error
        npt = v._page_items[0].mapToScene(QPointF(60, 60))
        v._cloud_press = npt
        v._cloud_on_release(npt)
        self.assertEqual(len(v._cloud_pts), 1)


if __name__ == "__main__":
    unittest.main()
