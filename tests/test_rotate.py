"""In-memory view rotation: pages rotate in the viewer (nothing written to
disk), annotations stay children of their page so they rotate/realign with it,
and the annotation model is never mutated. Plus: nav-pane selection switches to
the Viewer tab."""

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


def _landscape_pdf(path, pages=2):
    d = fitz.open()
    for _ in range(pages):
        d.new_page(width=800, height=600)
    d.save(path)
    d.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestViewRotation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_doc(self):
        from app.model.document import Document
        from app.model.annotations import Annotation, KIND_RECT, KIND_PEN
        from app.viewer.pdf_view import PdfView
        p = os.path.join(tempfile.mkdtemp(), "d.pdf")
        _landscape_pdf(p)
        doc = Document(p)
        doc.load()
        self.rect_ann = Annotation(page=0, kind=KIND_RECT, rect=(100.0, 50.0, 300.0, 150.0))
        self.pen_ann = Annotation(page=0, kind=KIND_PEN, points=[(10.0, 20.0), (40.0, 60.0)])
        doc.store.add(self.rect_ann)
        doc.store.add(self.pen_ann)
        view = PdfView()
        view.set_document(doc)
        return view

    def _dims(self, view, i=0):
        r = view._page_scene_rect(view._page_items[i])
        return round(r.width()), round(r.height())

    def test_rotate_swaps_displayed_dimensions(self):
        view = self._view_with_doc()
        self.assertEqual(view.rotation, 0)
        self.assertEqual(self._dims(view), (800, 600))   # landscape
        view.rotate_view(90)
        self.assertEqual(view.rotation, 90)
        self.assertEqual(self._dims(view), (600, 800))   # now portrait

    def test_annotation_model_never_mutated(self):
        view = self._view_with_doc()
        rect_before = tuple(self.rect_ann.rect)
        pts_before = list(self.pen_ann.points)
        for _ in range(3):
            view.rotate_view(90)
        self.assertEqual(tuple(self.rect_ann.rect), rect_before)
        self.assertEqual(list(self.pen_ann.points), pts_before)

    def test_marks_are_children_of_their_page(self):
        view = self._view_with_doc()
        page0 = view._page_items[0]
        for ann in (self.rect_ann, self.pen_ann):
            item = view._item_by_ann.get(ann.id)
            self.assertIsNotNone(item)
            # child of the page -> rotates and stays aligned with it automatically
            self.assertIs(item.parentItem(), page0)

    def test_full_turn_restores_orientation(self):
        view = self._view_with_doc()
        for _ in range(4):
            view.rotate_view(90)
        self.assertEqual(view.rotation, 0)
        self.assertEqual(self._dims(view), (800, 600))

    def test_opposite_rotation_restores(self):
        view = self._view_with_doc()
        view.rotate_view(90)
        view.rotate_view(270)            # +270 == -90
        self.assertEqual(view.rotation, 0)
        self.assertEqual(self._dims(view), (800, 600))

    def test_nothing_written_to_disk(self):
        # rotate_view must not touch the source file (in-memory only)
        from app.model.document import Document
        view = self._view_with_doc()
        src = view.document.path
        mtime = os.path.getmtime(src)
        size = os.path.getsize(src)
        view.rotate_view(90)
        self.assertEqual(os.path.getmtime(src), mtime)
        self.assertEqual(os.path.getsize(src), size)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestNavJumpsToViewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_nav_selection_switches_to_viewer_tab(self):
        from app.main_window import MainWindow
        win = MainWindow()
        # move to a non-viewer tab, then act as if a nav page was picked
        win.tabs.setCurrentWidget(win.todo_panel)
        self.assertIsNot(win.tabs.currentWidget(), win.view)
        win._nav_to_page(0)
        self.assertIs(win.tabs.currentWidget(), win.view)

    def test_nav_signal_is_wired_to_handler(self):
        from app.main_window import MainWindow
        win = MainWindow()
        win.tabs.setCurrentWidget(win.tools_panel)
        win.nav_panel.pageActivated.emit(0)   # what a page/bookmark click emits
        self.assertIs(win.tabs.currentWidget(), win.view)


if __name__ == "__main__":
    unittest.main()
