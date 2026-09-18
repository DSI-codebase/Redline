"""Change who a mark is by, from the Comments 'By' / TODO 'Commenter' columns."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import Annotation, AnnotationStore, KIND_COMMENT

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

if _QT_OK:
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from PySide6.QtCore import Qt


@unittest.skipUnless(_QT_OK, _QT_REASON)  # reaches PySide6 through app.viewer.command_stack (command_stack.py:13)
class TestAuthorSnapshot(unittest.TestCase):
    def test_capture_restore_author(self):
        from app.viewer.command_stack import capture, _restore
        a = Annotation(page=0, kind=KIND_COMMENT, author="Eli")
        snap = capture(a)
        self.assertEqual(snap["author"], "Eli")
        a.author = "Bob"
        _restore(a, snap)
        self.assertEqual(a.author, "Eli")


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestPanelDoubleClick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_comments_by_column_emits(self):
        from app.panels.comment_panel import CommentPanel
        store = AnnotationStore()
        c = Annotation(page=0, kind=KIND_COMMENT, text="hi", author="Eli")
        store.add(c, silent=True)
        panel = CommentPanel(); panel.set_store(store, config=None); panel.refresh()
        got = []
        panel.authorEditRequested.connect(lambda a: got.append(a))
        item = panel.tree.topLevelItem(0)
        panel._on_double(item, panel._COL_BY)          # double-click the By column
        self.assertEqual(got, [c])
        got.clear()
        panel._on_double(item, 1)                      # the Comment column: no emit
        self.assertEqual(got, [])

    def test_todo_commenter_column_emits(self):
        from app.panels.todo_panel import TodoPanel
        store = AnnotationStore()
        c = Annotation(page=0, kind=KIND_COMMENT, is_todo=True, text="do", author="Eli")
        store.add(c, silent=True)
        panel = TodoPanel(); panel.set_store(store, config=None, document=None)
        panel.refresh()
        got = []
        panel.authorEditRequested.connect(lambda a: got.append(a))
        # find the row for c
        def find(node):
            if node.data(0, Qt.UserRole) is c:
                return node
            for j in range(node.childCount()):
                hit = find(node.child(j))
                if hit:
                    return hit
            return None
        row = next(filter(None, (find(panel.tree.topLevelItem(i))
                                 for i in range(panel.tree.topLevelItemCount()))))
        panel._on_double(row, panel.COL_COMMENTER)
        self.assertEqual(got, [c])


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestEditAuthor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _win(self):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(src); d.close()
        win = MainWindow(); win.load_document(src)
        return win

    def test_single_change_and_undo(self):
        win = self._win()
        c = Annotation(page=0, kind=KIND_COMMENT, text="x", author="Eli")
        win.view.store.add(c)
        orig_q, orig_g = QMessageBox.question, QInputDialog.getText
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        QInputDialog.getText = staticmethod(lambda *a, **k: ("Bob", True))
        try:
            win._edit_author(c)
        finally:
            QMessageBox.question, QInputDialog.getText = orig_q, orig_g
        self.assertEqual(c.author, "Bob")
        win.view.undo_stack.undo()
        self.assertEqual(c.author, "Eli")

    def test_confirm_no_keeps_name(self):
        win = self._win()
        c = Annotation(page=0, kind=KIND_COMMENT, text="x", author="Eli")
        win.view.store.add(c)
        orig_q = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
        try:
            win._edit_author(c)
        finally:
            QMessageBox.question = orig_q
        self.assertEqual(c.author, "Eli")

    def test_rename_all_by_author(self):
        win = self._win()
        a = Annotation(page=0, kind=KIND_COMMENT, text="a", author="AutoCAD")
        b = Annotation(page=0, kind=KIND_COMMENT, text="b", author="AutoCAD")
        e = Annotation(page=0, kind=KIND_COMMENT, text="c", author="Eli")
        for m in (a, b, e):
            win.view.store.add(m)
        orig_exec, orig_click, orig_g = (QMessageBox.exec, QMessageBox.clickedButton,
                                         QInputDialog.getText)

        def fake_exec(self):
            self._clicked = next(bt for bt in self.buttons() if "All" in bt.text())
            return 0
        QMessageBox.exec = fake_exec
        QMessageBox.clickedButton = lambda self: getattr(self, "_clicked", None)
        QInputDialog.getText = staticmethod(lambda *a, **k: ("CAD", True))
        try:
            win._edit_author(a)
        finally:
            QMessageBox.exec, QMessageBox.clickedButton = orig_exec, orig_click
            QInputDialog.getText = orig_g
        self.assertEqual((a.author, b.author, e.author), ("CAD", "CAD", "Eli"))
        # one macro -> single undo restores both
        win.view.undo_stack.undo()
        self.assertEqual((a.author, b.author), ("AutoCAD", "AutoCAD"))


if __name__ == "__main__":
    unittest.main()
