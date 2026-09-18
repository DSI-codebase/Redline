"""Optional second viewer: a read-only *reference* pane on the same document,
for keeping a legend / TOC in view while working on another page.

It scrolls independently, shows marks made in the main viewer live (both views
listen to one AnnotationStore), and can't be used to change anything.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import Annotation, KIND_RECT, KIND_COMMENT

try:
    from PySide6.QtWidgets import QApplication, QGraphicsItem
    from app.viewer.pdf_view import PdfView
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _make_pdf(dirpath, pages=3):
    src = os.path.join(dirpath, "d.pdf")
    d = fitz.open()
    for i in range(pages):
        p = d.new_page(width=400, height=300)
        p.insert_text((60, 60), f"PAGE {i + 1}")
    d.save(src); d.close()
    return src


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestReadOnlyView(unittest.TestCase):
    """The read_only flag on PdfView itself."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._made = []

    def tearDown(self):
        # stop each view's deferred render before closing its document, so a
        # pending timer can't fire against a closed doc in a later test
        for doc, v in self._made:
            v._render_timer.stop()
            try:
                doc.close()
            except Exception:
                pass

    def _view(self, read_only):
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        doc = Document(_make_pdf(tmp)); doc.load()
        v = PdfView(read_only=read_only)
        v.set_document(doc, None)
        self._made.append((doc, v))
        return doc, v

    def test_default_view_is_editable(self):
        doc, v = self._view(False)
        self.assertFalse(v.read_only)
        self.assertTrue(v.select_mode)

    def test_read_only_disables_select_mode(self):
        doc, v = self._view(True)
        self.assertTrue(v.read_only)
        self.assertFalse(v.select_mode)   # marks not movable/selectable

    def test_mutations_are_no_ops(self):
        doc, v = self._view(True)
        a = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60))
        doc.store.add(a)
        n = len(doc.store.all())
        # every mutation entry point must do nothing and never raise
        v.delete_selected()
        v.paste_clipboard()
        v._paste_at(v.mapToScene(v.rect().center()))
        v.paste_format(a)
        v.reorder_annotation(a, "front")
        v._commit_new(Annotation(page=0, kind=KIND_RECT, rect=(0, 0, 5, 5)))
        v._erase_at(v.mapToScene(v.rect().center()))
        self.assertEqual(len(doc.store.all()), n)
        self.assertEqual(v.undo_stack.count(), 0)
        self.assertEqual(a.z_order, 0.0)          # reorder didn't touch it

    def test_begin_draft_refuses(self):
        doc, v = self._view(True)
        self.assertFalse(v._begin_draft(v.mapToScene(v.rect().center())))

    def test_push_command_is_a_backstop(self):
        # every edit funnels through push_command, so the invariant holds
        # structurally even if some future caller forgets its own guard
        from app.viewer.command_stack import ModifyAnnotationCommand, capture
        doc, v = self._view(True)
        a = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60))
        doc.store.add(a)
        before = capture(a)
        a2 = Annotation(page=0, kind=KIND_RECT, rect=(0, 0, 5, 5))
        v.push_command(ModifyAnnotationCommand(v, a, before, capture(a2), "x"))
        self.assertEqual(v.undo_stack.count(), 0)

    def test_grip_handlers_refuse_even_if_driven(self):
        # the grips can never be shown in a read-only pane, but they also write
        # the model + store.update() outside push_command — so drive their
        # handlers directly and assert they still refuse
        doc, v = self._view(True)
        a = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60))
        doc.store.add(a)
        item = v._item_by_ann[a.id]
        rect_before = tuple(a.rect)
        item.setRect(0, 0, 500, 500)      # pretend a resize happened
        item._end_resize()
        item.setRotation(45.0)
        item._end_rotate()
        self.assertEqual(tuple(a.rect), rect_before)   # model untouched
        self.assertEqual(a.rotation, 0.0)
        self.assertEqual(v.undo_stack.count(), 0)

    def test_marks_render_but_are_locked(self):
        doc, v = self._view(True)
        a = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60))
        doc.store.add(a)
        item = v._item_by_ann.get(a.id)
        self.assertIsNotNone(item)                                  # visible…
        self.assertFalse(bool(item.flags() & QGraphicsItem.ItemIsMovable))
        self.assertFalse(bool(item.flags() & QGraphicsItem.ItemIsSelectable))


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestReferencePane(unittest.TestCase):
    """The second viewer as wired into the main window."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # The dock layout (including whether the pane was left open) is saved
        # between sessions like every other dock, so start each test from a
        # clean layout instead of inheriting one from a previous run.
        from app.config import AppConfig
        cfg = AppConfig()
        cfg.s.remove("ui/window_state")
        cfg.s.remove("ui/geometry")
        cfg.s.sync()

    def _win(self):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        win = MainWindow()
        win.load_document(_make_pdf(tmp))
        return win

    def test_hidden_by_default(self):
        win = self._win()
        self.assertFalse(win.ref_dock.isVisible())

    def test_shares_document_and_store(self):
        win = self._win()
        self.assertIs(win.ref_view.document, win.document)
        self.assertIs(win.ref_view.store, win.view.store)
        self.assertTrue(win.ref_view.read_only)
        self.assertFalse(win.view.read_only)     # main viewer stays editable

    def test_marks_from_main_view_appear_in_reference(self):
        win = self._win()
        a = Annotation(page=0, kind=KIND_COMMENT, text="hi")
        win.view.store.add(a)
        self.assertIn(a.id, win.ref_view._item_by_ann)   # live sync
        win.view.store.remove(a.id)
        self.assertNotIn(a.id, win.ref_view._item_by_ann)

    def test_scrolls_independently(self):
        win = self._win()
        win.view.go_to_page(2)
        self.app.processEvents()
        self.assertEqual(win.view._current_page_index(), 2)
        self.assertEqual(win.ref_view._current_page_index(), 0)   # stays put

    def test_toggle_shows_and_hides(self):
        win = self._win()
        win.show(); self.app.processEvents()
        win._toggle_reference_view(); self.app.processEvents()
        self.assertTrue(win.ref_dock.isVisible())
        win._toggle_reference_view(); self.app.processEvents()
        self.assertFalse(win.ref_dock.isVisible())
        win.close()

    def test_dock_has_stable_object_name(self):
        # so the layout persists across sessions like the other docks
        win = self._win()
        self.assertEqual(win.ref_dock.objectName(), "RefViewDock")

    def test_settings_refresh_reaches_reference(self):
        # "Show ignored" changes which marks are drawn — the reference pane must
        # not be left showing a stale set.
        win = self._win()
        a = Annotation(page=0, kind=KIND_COMMENT, text="SHX junk", ignored=True)
        win.view.store.add(a)
        self.assertNotIn(a.id, win.view._item_by_ann)
        self.assertNotIn(a.id, win.ref_view._item_by_ann)
        prev = win.config.get("filter/show_ignored")
        try:
            win.config.set("filter/show_ignored", True)
            win.view.rebuild_all_items()
            win.ref_view.rebuild_all_items()
            self.assertIn(a.id, win.view._item_by_ann)
            self.assertIn(a.id, win.ref_view._item_by_ann)   # stayed in step
        finally:
            win.config.set("filter/show_ignored", prev)

    def test_reference_view_shares_config(self):
        win = self._win()
        self.assertIs(win.ref_view.config, win.config)

    def test_hidden_pane_renders_nothing(self):
        # a pane the user may never open must not hold a set of page bitmaps
        win = self._win()
        self.app.processEvents()
        self.assertFalse(win.ref_dock.isVisible())
        self.assertFalse(win.ref_view.render_enabled)
        self.assertTrue(all(not it.is_rendered() for it in win.ref_view._page_items))

    def test_showing_enables_rendering_and_hiding_frees_it(self):
        win = self._win()
        win.show(); self.app.processEvents()
        win._toggle_reference_view(); self.app.processEvents()
        self.assertTrue(win.ref_view.render_enabled)
        win._toggle_reference_view(); self.app.processEvents()
        self.assertFalse(win.ref_view.render_enabled)
        self.assertTrue(all(not it.is_rendered() for it in win.ref_view._page_items))
        win.close()

    def test_first_show_gives_the_dock_a_usable_width(self):
        # a never-shown dock otherwise opens at its ~70px minimum
        win = self._win()
        win.resize(1600, 900); win.show(); self.app.processEvents()
        win._toggle_reference_view(); self.app.processEvents()
        self.assertGreater(win.ref_dock.width(), 200)
        win.close()

    def test_failed_open_keeps_current_document_usable(self):
        # regression: the old document used to be closed BEFORE the new one was
        # built, so a bad file left the app pointed at a closed Document
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        win = self._win()
        good = win.document
        tmp = tempfile.mkdtemp()
        bad = os.path.join(tmp, "bad.pdf")
        with open(bad, "wb") as fh:
            fh.write(b"not a pdf at all")
        with mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok):
            win.load_document(bad)
        self.assertIs(win.document, good)
        self.assertFalse(win.document.fitz_doc.is_closed)
        self.assertIs(win.view.document, good)
        self.assertIs(win.ref_view.document, good)

    def test_document_reopen_rewires_reference(self):
        win = self._win()
        tmp = tempfile.mkdtemp()
        win.load_document(_make_pdf(tmp, pages=2))
        self.assertIs(win.ref_view.document, win.document)
        self.assertIs(win.ref_view.store, win.view.store)


if __name__ == "__main__":
    unittest.main()
