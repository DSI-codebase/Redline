"""Unsaved markup has to survive the close, or at least ask.

``Document.mark_dirty`` existed with no caller: nothing ever set the flag, so
``dirty`` was structurally ``False``, so the close path -- which never read it
anyway -- had nothing to read.  Fifty marks across fourteen sheets, close the
window, reopen: zero survived, with no prompt and no warning.  These tests hold
the two halves of the fix apart: that the flag now tracks real edits and only
real edits, and that the window acts on it.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.document import Document
from app.model.annotations import Annotation, KIND_RECT

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtCore import Qt
    _QT_OK = True
except Exception:                                          # pragma: no cover
    _QT_OK = False


def _blank_pdf(path, pages=3):
    d = fitz.open()
    for i in range(pages):
        d.new_page(width=792, height=612).insert_text((72, 72), f"SHEET {200+i}")
    d.save(path)
    d.close()
    return path


class TestDirtyTracking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _blank_pdf(os.path.join(self.tmp, "job.pdf"))

    def _doc(self, path=None):
        doc = Document(path or self.src)
        doc.load()
        self.addCleanup(doc.close)
        return doc

    def _mark(self, i=0):
        return Annotation(page=i % 3, kind=KIND_RECT,
                          rect=(100.0 + i, 100.0, 160.0 + i, 130.0))

    def test_a_freshly_opened_document_is_clean(self):
        self.assertFalse(self._doc().dirty)

    def test_drawing_a_mark_makes_it_dirty(self):
        doc = self._doc()
        doc.store.add(self._mark())
        self.assertTrue(doc.dirty)

    def test_every_edit_path_sets_the_flag(self):
        """add / update / remove -- which is draw, move, resize, retype,
        delete, undo and redo, since the command stack and the canvas items
        all reach the model through exactly these three."""
        doc = self._doc()
        ann = doc.store.add(self._mark())
        doc.save()
        for label, act in (("update", lambda: doc.store.update(ann)),
                           ("remove", lambda: doc.store.remove(ann.id)),
                           ("re-add", lambda: doc.store.add(ann))):
            with self.subTest(edit=label):
                doc.save()
                self.assertFalse(doc.dirty)
                act()
                self.assertTrue(doc.dirty)

    def test_saving_clears_the_flag(self):
        doc = self._doc()
        doc.store.add(self._mark())
        doc.save()
        self.assertFalse(doc.dirty)

    def test_a_saved_file_reopens_clean(self):
        """The trap this fix has to miss.

        ``silent=True`` gates only the store's *emit*, not the body of add ---
        so a flag set inside ``AnnotationStore.add`` would fire for every mark
        ``Document.load`` reads back, and a saved fifty-mark file would come up
        dirty and prompt to save on every close.  Hence a listener, which
        ``silent`` does suppress.
        """
        doc = self._doc()
        for i in range(50):
            doc.store.add(self._mark(i))
        out = doc.save()
        doc.close()

        reopened = self._doc(out)
        self.assertEqual(len(reopened.store.all()), 50)
        self.assertFalse(reopened.dirty)

    def test_a_colleagues_annotations_do_not_dirty_the_file(self):
        """Marks already living in the PDF are not unsaved work."""
        d = fitz.open(self.src)
        d[0].add_rect_annot(fitz.Rect(20, 20, 90, 60)).update()
        foreign = os.path.join(self.tmp, "from_them.pdf")
        d.save(foreign)
        d.close()

        doc = self._doc(foreign)
        self.assertTrue(doc.store.all())               # it really was imported
        self.assertFalse(doc.dirty)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestPanelTicks(unittest.TestCase):
    """Which wires and components are ticked for export is a decision, and it
    reaches disk only on save -- so it counts as unsaved work too."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _blank_pdf(os.path.join(self.tmp, "job.pdf"))
        self.doc = Document(self.src)
        self.doc.load()
        self.addCleanup(self.doc.close)

    def test_unticking_a_wire_marks_the_document_dirty(self):
        from app.panels.wire_panel import WirePanel
        from app.extraction.wire_parser import WireNumber, TYPE_CONFORMING
        wp = WirePanel()
        wp.document = self.doc
        wp.wires = [WireNumber(label="2000", sheet=2, rung=5, wire_index=0,
                               wire_type=TYPE_CONFORMING, page=0, count=3)]
        wp._populate()
        self.assertFalse(self.doc.dirty, "populating the table is not an edit")

        wp.table.item(0, 0).setCheckState(Qt.Unchecked)
        self.assertFalse(wp.wires[0].included)
        self.assertTrue(self.doc.dirty)

    def test_check_all_marks_the_document_dirty(self):
        from app.panels.component_panel import ComponentPanel
        from app.extraction.component_parser import ComponentLabel
        cp = ComponentPanel()
        cp.document = self.doc
        cp.components = [ComponentLabel(label="PB100", family="PB", number="100",
                                        sheet=1, rung=0, comp_type="pushbutton",
                                        page=0)]
        cp._populate()
        self.assertFalse(self.doc.dirty)

        cp._set_all_visible(False)
        self.assertTrue(self.doc.dirty)

    def test_a_panel_with_no_document_does_not_raise(self):
        from app.panels.wire_panel import WirePanel
        wp = WirePanel()
        wp._mark_dirty()                                   # no document set yet


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestClosePrompt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _blank_pdf(os.path.join(self.tmp, "job.pdf"))
        self.asked = 0

    def _window(self, dirty=True):
        from app.main_window import MainWindow
        win = MainWindow()
        win.load_document(self.src)
        self.addCleanup(win.deleteLater)
        if dirty:
            win.document.store.add(Annotation(page=0, kind=KIND_RECT,
                                              rect=(10, 10, 90, 60)))
            self.assertTrue(win.document.dirty)
        return win

    def _answer(self, button):
        """Stand in for the modal box and record that it was put up."""
        def fake_exec(_box):
            self.asked += 1
            return button
        patch = mock.patch.object(QMessageBox, "exec", fake_exec)
        patch.start()
        self.addCleanup(patch.stop)

    def _close(self, win):
        ev = QCloseEvent()
        win.closeEvent(ev)
        return ev.isAccepted()

    def test_cancel_keeps_the_window_open(self):
        win = self._window()
        self._answer(QMessageBox.Cancel)
        self.assertFalse(self._close(win))
        self.assertEqual(self.asked, 1)
        self.assertTrue(win.document.dirty)          # nothing was thrown away
        self.assertEqual(win.document.page_count, 3)  # nor torn down

    def test_discard_closes_without_saving(self):
        win = self._window()
        self._answer(QMessageBox.Discard)
        self.assertTrue(self._close(win))
        self.assertEqual(self.asked, 1)

    def test_save_writes_the_marks_then_closes(self):
        win = self._window()
        path = win.document.path
        self._answer(QMessageBox.Save)
        self.assertTrue(self._close(win))
        self.assertEqual(self.asked, 1)

        from app.model.storage import marked_pdf_path
        reopened = Document(marked_pdf_path(path))
        reopened.load()
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.store.all()), 1)

    def test_a_clean_document_closes_without_asking(self):
        win = self._window(dirty=False)
        self._answer(QMessageBox.Cancel)               # would refuse, if asked
        self.assertTrue(self._close(win))
        self.assertEqual(self.asked, 0)

    def test_opening_another_file_asks_first(self):
        win = self._window()
        other = _blank_pdf(os.path.join(self.tmp, "other.pdf"))
        self._answer(QMessageBox.Cancel)
        win.load_document(other)
        self.assertEqual(self.asked, 1)
        self.assertEqual(os.path.abspath(win.document.path),
                         os.path.abspath(self.src))   # still on the first file
        self.assertTrue(win.document.dirty)


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
