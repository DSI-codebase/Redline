"""v1.1.0 Phase 5: TODO audit — a completed TODO is struck through both on the
sheet (a line across the mark) and in the TODO list (a struck-out row)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.model.annotations import (
    Annotation, AnnotationStore, KIND_RECT, KIND_COMMENT,
)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestOnSheetStrike(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _item(self, **kw):
        from app.viewer.annotation_items import make_item

        class _V:
            select_mode = True
            store = AnnotationStore()
        ann = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 110, 60), **kw)
        return make_item(ann, _V())

    def test_no_strike_for_incomplete_todo(self):
        it = self._item(is_todo=True, todo_done=False)
        it._refresh_done_overlay()
        line = getattr(it, "_done_strike", None)
        self.assertTrue(line is None or not line.isVisible())

    def test_no_strike_for_non_todo(self):
        it = self._item(is_todo=False, todo_done=False)
        it._refresh_done_overlay()
        self.assertIsNone(getattr(it, "_done_strike", None))

    def test_strike_appears_and_clears(self):
        it = self._item(is_todo=True, todo_done=True)
        it._refresh_done_overlay()
        self.assertTrue(it._done_strike.isVisible())
        # spans the mark horizontally
        ln = it._done_strike.line()
        self.assertLess(ln.x1(), ln.x2())
        # un-completing hides it
        it.ann.todo_done = False
        it._refresh_done_overlay()
        self.assertFalse(it._done_strike.isVisible())


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestTodoListStrike(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self, anns):
        from app.panels.todo_panel import TodoPanel
        store = AnnotationStore()
        for a in anns:
            store.add(a, silent=True)
        panel = TodoPanel()
        panel.set_store(store, config=None, document=None)
        panel.refresh()
        return panel

    def _row_for(self, panel, ann):
        def walk(node):
            if node.data(0, Qt.UserRole) is ann:
                return node
            for j in range(node.childCount()):
                hit = walk(node.child(j))
                if hit is not None:
                    return hit
            return None
        for i in range(panel.tree.topLevelItemCount()):
            hit = walk(panel.tree.topLevelItem(i))
            if hit is not None:
                return hit
        return None

    def test_done_row_struck_out_incomplete_not(self):
        done = Annotation(page=0, kind=KIND_COMMENT, is_todo=True, todo_done=True,
                          text="fixed")
        todo = Annotation(page=1, kind=KIND_COMMENT, is_todo=True, todo_done=False,
                          text="open")
        panel = self._panel([done, todo])
        done_row = self._row_for(panel, done)
        todo_row = self._row_for(panel, todo)
        self.assertIsNotNone(done_row)
        self.assertIsNotNone(todo_row)
        self.assertTrue(done_row.font(panel.COL_TEXT).strikeOut())
        self.assertFalse(todo_row.font(panel.COL_TEXT).strikeOut())

    def test_count_reports_done(self):
        anns = [Annotation(page=0, kind=KIND_COMMENT, is_todo=True, todo_done=True,
                           text="a"),
                Annotation(page=0, kind=KIND_COMMENT, is_todo=True, todo_done=False,
                           text="b")]
        panel = self._panel(anns)
        self.assertIn("1 done", panel.count_label.text())


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestLiveToggle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_toggling_done_updates_on_sheet(self):
        import tempfile, fitz
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(src); d.close()
        win = MainWindow(); win.load_document(src)
        ann = Annotation(page=0, kind=KIND_RECT, rect=(20, 20, 120, 80),
                         is_todo=True, todo_done=False)
        win.view.store.add(ann)
        item = win.view._item_by_ann[ann.id]
        self.assertTrue(getattr(item, "_done_strike", None) is None
                        or not item._done_strike.isVisible())
        ann.todo_done = True
        win.view.store.update(ann)
        item = win.view._item_by_ann[ann.id]
        self.assertTrue(item._done_strike.isVisible())


if __name__ == "__main__":
    unittest.main()
