"""Four requests about marks, each asserted where it acts.

1. Double-clicking any mark that can carry a note opens its editor -- the same
   one right-click ▸ Add note… / Edit note… opens. Before, only the comment
   bubble, the text box and the callout answered a double-click.
2. The Comments pane's right-click menu offers edit, go-to, the TODO flag, the
   commenter, copy and delete. Before, it offered Delete alone.
3. A TODO mark is badged BLUE on the sheet. Before, the badge was orange for
   every noted mark, TODO or not, and a text box never showed its TODO at all.
4. A jump from a list zooms to the target's extents. Before, it scrolled to the
   target at whatever zoom was on screen: readable on an 11x17 schematic at fit
   width, a few pixels across on a 36x48 in site plan -- and a pen stroke, whose
   ``rect`` is all zeros, landed on the page's top-left corner.

The locate assertions take their oracle from the page transform and the model's
own coordinates, never from ``_annotation_scene_rect`` -- the function under test.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import (
    Annotation, AnnotationStore,
    KIND_HIGHLIGHT, KIND_PEN, KIND_COMMENT, KIND_TEXTBOX, KIND_RECT,
    KIND_CIRCLE, KIND_ARROW, KIND_LINE, KIND_CALLOUT, KIND_CLOUD,
)

try:
    from PySide6.QtWidgets import (
        QApplication, QGraphicsSceneMouseEvent, QMessageBox,
    )
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtTest import QTest
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False

SITE_W, SITE_H = 2592.0, 3456.0     # a 36x48 in sheet, in points
NOTE_KINDS = (KIND_HIGHLIGHT, KIND_PEN, KIND_RECT, KIND_CIRCLE, KIND_ARROW,
              KIND_LINE, KIND_CLOUD)


def _pdf(dirpath, w, h):
    src = os.path.join(dirpath, "sheet.pdf")
    d = fitz.open()
    d.new_page(width=w, height=h)
    d.save(src)
    d.close()
    return src


def _mark(kind, **kw):
    """A mark of ``kind`` with geometry its item can draw."""
    if kind in (KIND_PEN, KIND_CLOUD):
        kw.setdefault("points", [(100, 100), (160, 120), (140, 170)])
    else:
        kw.setdefault("rect", (100, 100, 180, 150))
    return Annotation(page=0, kind=kind, **kw)


class _StubView:
    """What an item asks of its view, recording the editor it opens."""

    def __init__(self, select_mode=True, read_only=False):
        self.select_mode = select_mode and not read_only
        self.read_only = read_only
        self.store = AnnotationStore()
        self.opened = []

    def edit_note_annotation(self, ann):
        self.opened.append(("note", ann))

    def edit_comment_annotation(self, ann):
        self.opened.append(("comment", ann))

    def edit_text_annotation(self, ann):
        self.opened.append(("text", ann))


def _double_click(item):
    ev = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMouseDoubleClick)
    ev.setButton(Qt.LeftButton)
    ev.setAccepted(False)
    item.mouseDoubleClickEvent(ev)
    return ev.isAccepted()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class _ViewCase(unittest.TestCase):
    """A real PdfView, shown offscreen so its viewport has a real size."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._made = []

    def tearDown(self):
        for doc, v in self._made:
            v._render_timer.stop()
            v.hide()
            try:
                doc.close()
            except Exception:
                pass

    def _view(self, anns=(), w=SITE_W, h=SITE_H, read_only=False):
        from app.model.document import Document
        from app.viewer.pdf_view import PdfView
        doc = Document(_pdf(tempfile.mkdtemp(), w, h))
        doc.load()
        for a in anns:
            doc.store.add(a, silent=True)
        v = PdfView(read_only=read_only)
        v.resize(900, 700)
        v.show()
        v.set_document(doc, None)
        self._made.append((doc, v))
        self.app.processEvents()      # the deferred fit_width lands now, not later
        return v

    def _scene(self, v, x, y, page=0):
        return v._page_items[page].mapToScene(QPointF(x, y))

    def _visible(self, v):
        return v.mapToScene(v.viewport().rect()).boundingRect()

    def assertOnScreen(self, v, pts):
        vis = self._visible(v)
        for p in pts:
            self.assertTrue(vis.contains(p),
                            f"{p} is off screen; the view shows {vis}")

    def assertCenteredOn(self, v, p, tol=3.0):
        c = self._visible(v).center()
        self.assertLess(abs(c.x() - p.x()), tol, f"center {c} is not {p}")
        self.assertLess(abs(c.y() - p.y()), tol, f"center {c} is not {p}")


# --- 1. double-click opens the note editor ----------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestDoubleClickOpensTheEditor(_ViewCase):

    def test_every_note_kind_opens_the_note_editor(self):
        from app.viewer.annotation_items import make_item
        for kind in NOTE_KINDS:
            with self.subTest(kind=kind):
                view = _StubView()
                ann = _mark(kind)
                self.assertTrue(_double_click(make_item(ann, view)))
                self.assertEqual(view.opened, [("note", ann)])

    def test_the_text_kinds_keep_their_own_editors(self):
        from app.viewer.annotation_items import make_item
        for kind, editor in ((KIND_COMMENT, "comment"), (KIND_TEXTBOX, "text"),
                             (KIND_CALLOUT, "text")):
            with self.subTest(kind=kind):
                view = _StubView()
                ann = _mark(kind)
                _double_click(make_item(ann, view))
                self.assertEqual(view.opened, [(editor, ann)])

    def test_nothing_opens_outside_the_select_tool_or_in_a_reference_pane(self):
        from app.viewer.annotation_items import make_item
        for view in (_StubView(select_mode=False), _StubView(read_only=True)):
            with self.subTest(select_mode=view.select_mode, read_only=view.read_only):
                self.assertFalse(_double_click(make_item(_mark(KIND_RECT), view)))
                self.assertEqual(view.opened, [])

    def _dclick_mark(self, v, ann):
        x0, y0, x1, y1 = ann.rect
        at = v.mapFromScene(self._scene(v, (x0 + x1) / 2, (y0 + y1) / 2))
        QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, at)
        self.app.processEvents()

    def test_a_double_click_on_the_canvas_reaches_the_mark(self):
        # The routing, not the handler: a real double-click on the viewport goes
        # through PdfView, the scene and the item, and asks for the note editor.
        ann = _mark(KIND_RECT, rect=(200, 200, 320, 280))
        v = self._view([ann], w=612, h=792)
        asked = []
        v.requestCommentEdit.connect(asked.append)
        self._dclick_mark(v, ann)
        self.assertEqual(asked, [ann])

    def test_a_drawing_tool_double_click_opens_nothing(self):
        from app.viewer import tools as T
        ann = _mark(KIND_RECT, rect=(200, 200, 320, 280))
        v = self._view([ann], w=612, h=792)
        v.tool.current = T.TOOL_PEN
        asked = []
        v.requestCommentEdit.connect(asked.append)
        self._dclick_mark(v, ann)
        self.assertEqual(asked, [])


# --- 2. the Comments pane's right-click menu --------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestCommentsContextMenu(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self, *anns):
        from app.panels.comment_panel import CommentPanel
        store = AnnotationStore()
        for a in anns:
            store.add(a, silent=True)
        panel = CommentPanel()
        panel.set_store(store)
        self.events = []
        store.add_listener(lambda ev, a: self.events.append((ev, a)))
        return panel

    @staticmethod
    def _labels(menu):
        return [a.text() for a in menu.actions() if not a.isSeparator()]

    @staticmethod
    def _action(menu, label):
        for a in menu.actions():
            if a.text() == label:
                return a
        raise AssertionError(f"no {label!r} in {[a.text() for a in menu.actions()]}")

    def test_a_comment_offers_the_full_menu(self):
        ann = Annotation(page=0, kind=KIND_COMMENT, text="check breaker")
        panel = self._panel(ann)
        self.assertEqual(self._labels(panel._context_menu_for(ann)), [
            "Edit comment…", "Go to in PDF", "Flag as TODO",
            "Change commenter…", "Copy text", "Delete comment"])

    def test_the_edit_label_names_the_editor_it_opens(self):
        for kind, text, label in ((KIND_TEXTBOX, "x", "Edit text…"),
                                  (KIND_CALLOUT, "x", "Edit text…"),
                                  (KIND_RECT, "x", "Edit note…"),
                                  (KIND_HIGHLIGHT, "", "Add note…")):
            with self.subTest(kind=kind):
                ann = Annotation(page=0, kind=kind, text=text)
                menu = self._panel(ann)._context_menu_for(ann)
                self.assertEqual(self._labels(menu)[0], label)

    def test_each_request_is_emitted_with_its_mark(self):
        ann = Annotation(page=0, kind=KIND_COMMENT, text="t", is_todo=True)
        panel = self._panel(ann)
        for label, signal in (("Edit comment…", panel.editRequested),
                              ("Go to in PDF", panel.activated),
                              ("Change commenter…", panel.authorEditRequested),
                              ("Show in TODO list", panel.revealTodoRequested)):
            with self.subTest(label=label):
                got = []
                signal.connect(got.append)
                self._action(panel._context_menu_for(ann), label).trigger()
                self.assertEqual(got, [ann])

    def test_the_todo_flag_round_trips_through_the_store(self):
        ann = Annotation(page=0, kind=KIND_RECT, text="n")
        panel = self._panel(ann)

        self._action(panel._context_menu_for(ann), "Flag as TODO").trigger()
        self.assertEqual((ann.is_todo, ann.todo_done), (True, False))

        menu = panel._context_menu_for(ann)
        self.assertIn("Show in TODO list", self._labels(menu))
        self.assertNotIn("Flag as TODO", self._labels(menu))
        self._action(menu, "Mark done").trigger()
        self.assertEqual((ann.is_todo, ann.todo_done), (True, True))

        self._action(panel._context_menu_for(ann), "Mark not done").trigger()
        self.assertEqual((ann.is_todo, ann.todo_done), (True, False))

        self._action(panel._context_menu_for(ann), "Mark done").trigger()
        self._action(panel._context_menu_for(ann), "Remove TODO flag").trigger()
        # done is cleared too: the bubble paints green on todo_done alone
        self.assertEqual((ann.is_todo, ann.todo_done), (False, False))
        # every change reached the store, so the canvas and the TODO tab follow
        self.assertEqual([ev for ev, _ in self.events], ["update"] * 5)

    def test_copy_text(self):
        ann = Annotation(page=0, kind=KIND_COMMENT, text="replace fuse F12")
        panel = self._panel(ann)
        self._action(panel._context_menu_for(ann), "Copy text").trigger()
        self.assertEqual(QApplication.clipboard().text(), "replace fuse F12")
        empty = Annotation(page=0, kind=KIND_HIGHLIGHT)
        self.assertFalse(self._action(
            self._panel(empty)._context_menu_for(empty), "Copy text").isEnabled())

    def test_delete_acts_on_the_row_it_was_opened_on(self):
        a = Annotation(page=0, kind=KIND_COMMENT, text="a")
        b = Annotation(page=0, kind=KIND_COMMENT, text="b")
        panel = self._panel(a, b)
        panel.reveal(a)                                  # a is selected...
        got = []
        panel.deleteRequested.connect(got.append)
        keep = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.Yes)
        try:
            self._action(panel._context_menu_for(b), "Delete comment").trigger()
        finally:
            QMessageBox.question = keep
        self.assertEqual(got, [b])                       # ...and b is deleted


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestTheWindowAnswersTheMenu(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_edit_opens_the_editor_for_the_kind(self):
        from app.main_window import MainWindow
        win = MainWindow()
        try:
            opened = []
            win._edit_text = lambda ann, is_textbox: opened.append((ann.kind, is_textbox))
            for kind in (KIND_TEXTBOX, KIND_CALLOUT, KIND_COMMENT, KIND_RECT):
                ann = Annotation(page=0, kind=kind, text="x")
                label = win.comment_panel._context_menu_for(ann).actions()[0]
                label.trigger()
            self.assertEqual(opened, [(KIND_TEXTBOX, True), (KIND_CALLOUT, True),
                                      (KIND_COMMENT, False), (KIND_RECT, False)])
        finally:
            win.close()

    def test_show_in_todo_list_reveals_it_there(self):
        from app.main_window import MainWindow
        win = MainWindow()
        try:
            shown = []
            win._reveal_in_panel = lambda ann, target: shown.append((ann, target))
            ann = Annotation(page=0, kind=KIND_COMMENT, text="x", is_todo=True)
            win.comment_panel.revealTodoRequested.emit(ann)
            self.assertEqual(shown, [(ann, "todo")])
        finally:
            win.close()


# --- 3. a TODO is badged blue -----------------------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestTodoBadgeIsBlue(_ViewCase):

    def setUp(self):
        super().setUp()
        self._items = []      # a badge is a child: it dies with a collected item

    def _badge(self, ann):
        from app.viewer.annotation_items import make_item
        item = make_item(ann, _StubView())
        self._items.append(item)
        item._refresh_note_badge()
        return getattr(item, "_note_badge", None)

    def _rgb(self, badge):
        c = badge.brush().color()
        return (c.red(), c.green(), c.blue())

    def test_note_is_orange_and_todo_is_blue(self):
        from app.viewer.annotation_items import NOTE_BADGE_RGB, TODO_BADGE_RGB
        self.assertNotEqual(NOTE_BADGE_RGB, TODO_BADGE_RGB)
        for kind in NOTE_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(self._rgb(self._badge(_mark(kind, text="n"))),
                                 NOTE_BADGE_RGB)
                self.assertEqual(self._rgb(self._badge(
                    _mark(kind, text="n", is_todo=True))), TODO_BADGE_RGB)
                self.assertEqual(self._rgb(self._badge(
                    _mark(kind, text="n", is_todo=True, todo_done=True))),
                    TODO_BADGE_RGB)

    def test_a_todo_with_no_note_is_still_badged(self):
        from app.viewer.annotation_items import TODO_BADGE_RGB
        badge = self._badge(_mark(KIND_RECT, is_todo=True))
        self.assertTrue(badge.isVisible())
        self.assertEqual(self._rgb(badge), TODO_BADGE_RGB)

    def test_a_text_box_shows_its_todo_and_only_its_todo(self):
        from app.viewer.annotation_items import TODO_BADGE_RGB
        for kind in (KIND_TEXTBOX, KIND_CALLOUT):
            with self.subTest(kind=kind):
                self.assertIsNone(self._badge(_mark(kind, text="shown on the page")))
                badge = self._badge(_mark(kind, text="x", is_todo=True))
                self.assertTrue(badge.isVisible())
                self.assertEqual(self._rgb(badge), TODO_BADGE_RGB)

    def test_the_bubble_is_never_badged(self):
        self.assertIsNone(self._badge(_mark(KIND_COMMENT, text="x", is_todo=True)))

    def test_the_canvas_recolors_when_the_flag_changes(self):
        # through the store, as the TODO tab and the Comments menu change it
        from app.viewer.annotation_items import NOTE_BADGE_RGB, TODO_BADGE_RGB
        ann = _mark(KIND_RECT, text="n")
        v = self._view([ann], w=612, h=792)
        badge = v._item_by_ann[ann.id]._note_badge
        self.assertEqual(self._rgb(badge), NOTE_BADGE_RGB)
        ann.is_todo = True
        v.store.update(ann)
        self.assertEqual(self._rgb(badge), TODO_BADGE_RGB)
        ann.is_todo = False
        v.store.update(ann)
        self.assertEqual(self._rgb(badge), NOTE_BADGE_RGB)


# --- 4. a jump zooms to the target's extents --------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestLocateZoomsToExtents(_ViewCase):

    def test_a_small_mark_on_a_site_plan_is_framed_legibly(self):
        ann = _mark(KIND_RECT, rect=(1200, 1600, 1260, 1640))
        v = self._view([ann])
        fit = v._zoom
        self.assertLess(60 * fit, 30, "premise: at fit width it is a speck")
        v.flash_annotation(ann)
        self.assertGreaterEqual(60 * v._zoom, 150,
                                "a 60 pt mark should be 150+ px across")
        self.assertLessEqual(v._zoom, v.LOCATE_MAX_ZOOM)
        self.assertOnScreen(v, [self._scene(v, 1200, 1600), self._scene(v, 1260, 1640)])
        self.assertCenteredOn(v, self._scene(v, 1230, 1620))

    def test_a_mark_larger_than_the_view_is_zoomed_out_to(self):
        ann = _mark(KIND_RECT, rect=(300, 400, 2300, 3000))
        v = self._view([ann])
        v.set_zoom(2.0)
        v.flash_annotation(ann)
        self.assertLess(v._zoom, 2.0)
        self.assertOnScreen(v, [self._scene(v, 300, 400), self._scene(v, 2300, 3000)])

    def test_a_pen_stroke_or_cloud_is_found_where_it_is_drawn(self):
        # ann.rect is all zeros for both, in the app and after a reload, so
        # centering on it went to the page's top-left corner
        pts = [(1500, 2000), (1560, 2030), (1600, 2050)]
        for kind in (KIND_PEN, KIND_CLOUD):
            for hidden in (False, True):   # with an item, and with none (ignored)
                with self.subTest(kind=kind, item=not hidden):
                    ann = Annotation(page=0, kind=kind, points=list(pts),
                                     ignored=hidden)
                    self.assertEqual(ann.rect, (0.0, 0.0, 0.0, 0.0))
                    v = self._view([ann])
                    self.assertEqual(ann.id in v._item_by_ann, not hidden)
                    v.flash_annotation(ann)
                    self.assertOnScreen(v, [self._scene(v, *p) for p in pts])
                    self.assertCenteredOn(v, self._scene(v, 1550, 2025), tol=10.0)

    def test_the_extents_follow_a_rotated_view(self):
        ann = _mark(KIND_RECT, rect=(1200, 1600, 1260, 1640))
        v = self._view([ann])
        v.rotate_view(90)
        v.flash_annotation(ann)
        self.assertOnScreen(v, [self._scene(v, 1200, 1600), self._scene(v, 1260, 1640)])
        self.assertCenteredOn(v, self._scene(v, 1230, 1620))

    def test_a_wire_jump_zooms_to_its_point(self):
        v = self._view()
        v.go_to_location(0, 900.0, 1100.0)
        self.assertEqual(v._zoom, v.LOCATE_MAX_ZOOM)
        self.assertCenteredOn(v, self._scene(v, 900, 1100))

    def test_an_audit_box_is_zoomed_to_whole(self):
        v = self._view()
        v.go_to_rect(0, 400.0, 500.0, 1400.0, 1300.0)
        self.assertOnScreen(v, [self._scene(v, 400, 500), self._scene(v, 1400, 1300)])
        self.assertCenteredOn(v, self._scene(v, 900, 900))

    def test_the_window_hands_an_audit_box_its_size(self):
        from app.main_window import MainWindow

        class _Place:
            page, x, y, w, h = 1, 100.0, 200.0, 40.0, 12.0

        win = MainWindow()
        try:
            calls = []
            win.view.go_to_rect = lambda *a: calls.append(a)
            win.view.go_to_location = lambda *a: calls.append(("point",) + a)
            win._jump_to(_Place())
            self.assertEqual(calls, [(1, 100.0, 200.0, 140.0, 212.0)])
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
