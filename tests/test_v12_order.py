"""Draw-new (no second existing-mark popup) and object stacking order."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import Annotation, KIND_RECT

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF
    import app.viewer.tools as T
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class _Base(unittest.TestCase):
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


class TestDrawNewOnce(_Base):
    def test_draw_new_suppresses_next_prompt(self):
        win = self._win(); v = win.view
        v.tool.current = T.TOOL_RECT
        mark = Annotation(page=0, kind=KIND_RECT, rect=(40, 40, 200, 160), color=(1, 0, 0))
        v.store.add(mark)
        page = v._page_items[0]
        scene_pt = page.mapToScene(QPointF(120, 100))       # inside the rect

        calls = []
        v.existing_mark_prompt = lambda ann: (calls.append(ann) or "new")

        # 1st press over the existing mark: prompts once, arms the one-shot, draws nothing
        handled = v._begin_draft(scene_pt)
        self.assertTrue(handled)
        self.assertEqual(len(calls), 1)
        self.assertTrue(v._suppress_existing_prompt)
        self.assertIsNone(v._draft)

        # 2nd press (placing the object): NO re-prompt, a draft is started
        v._begin_draft(scene_pt)
        self.assertEqual(len(calls), 1)                     # not asked again
        self.assertFalse(v._suppress_existing_prompt)
        self.assertIsNotNone(v._draft)

    def test_offpage_press_consumes_flag(self):
        # a stray press that misses a page must not leave the one-shot armed,
        # or a later legitimate prompt would be silently skipped
        win = self._win(); v = win.view
        v.tool.current = T.TOOL_RECT
        mark = Annotation(page=0, kind=KIND_RECT, rect=(40, 40, 200, 160))
        v.store.add(mark)
        v.existing_mark_prompt = lambda ann: "new"
        over = v._page_items[0].mapToScene(QPointF(120, 100))
        v._begin_draft(over)                       # choose "new" -> arms the flag
        self.assertTrue(v._suppress_existing_prompt)
        off = QPointF(-5000, -5000)                # far outside any page
        self.assertFalse(v._begin_draft(off))      # misses a page
        self.assertFalse(v._suppress_existing_prompt)   # but still consumed the flag

    def test_right_click_clears_suppression(self):
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtCore import QPoint
        win = self._win(); v = win.view
        v._suppress_existing_prompt = True
        ev = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5))
        v.contextMenuEvent(ev)
        self.assertFalse(v._suppress_existing_prompt)

    def test_edit_choice_does_not_arm_suppression(self):
        win = self._win(); v = win.view
        v.tool.current = T.TOOL_RECT
        mark = Annotation(page=0, kind=KIND_RECT, rect=(40, 40, 200, 160))
        v.store.add(mark)
        scene_pt = v._page_items[0].mapToScene(QPointF(120, 100))
        v.existing_mark_prompt = lambda ann: "edit"
        v._begin_draft(scene_pt)
        self.assertFalse(v._suppress_existing_prompt)


class TestStackingOrder(_Base):
    def _three(self, v):
        a = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 60, 40), color=(1, 0, 0))
        b = Annotation(page=0, kind=KIND_RECT, rect=(20, 20, 70, 50), color=(0, 1, 0))
        c = Annotation(page=0, kind=KIND_RECT, rect=(30, 30, 80, 60), color=(0, 0, 1))
        for m in (a, b, c):
            v._assign_top_z(m); v.store.add(m)
        return a, b, c

    def _order(self, v, page=0):
        marks = [m for m in v.store.all() if m.page == page]
        return [m for m in sorted(marks, key=lambda m: m.z_order)]

    def test_new_marks_stack_upward(self):
        win = self._win(); v = win.view
        a, b, c = self._three(v)
        self.assertLess(a.z_order, b.z_order)
        self.assertLess(b.z_order, c.z_order)
        # graphics-item z tracks the model (above the page bitmap)
        from app.viewer.annotation_items import ANNOT_Z
        self.assertAlmostEqual(v._item_by_ann[c.id].zValue(), ANNOT_Z + c.z_order)

    def test_bring_to_front_and_back(self):
        win = self._win(); v = win.view
        a, b, c = self._three(v)
        v.reorder_annotation(a, "front")
        self.assertEqual(self._order(v)[-1], a)
        v.reorder_annotation(a, "back")
        self.assertEqual(self._order(v)[0], a)

    def test_bring_forward_and_backward(self):
        win = self._win(); v = win.view
        a, b, c = self._three(v)               # order a,b,c (bottom->top)
        v.reorder_annotation(a, "up")          # a swaps with b -> b,a,c
        self.assertEqual(self._order(v), [b, a, c])
        v.reorder_annotation(c, "down")        # c swaps with a -> b,c,a
        self.assertEqual(self._order(v), [b, c, a])

    def test_reorder_is_undoable(self):
        win = self._win(); v = win.view
        a, b, c = self._three(v)
        before = self._order(v)
        v.reorder_annotation(a, "front")
        self.assertNotEqual(self._order(v), before)
        v.undo_stack.undo()
        self.assertEqual(self._order(v), before)

    def test_edge_cases_no_crash(self):
        win = self._win(); v = win.view
        a, b, c = self._three(v)
        top = self._order(v)[-1]
        v.reorder_annotation(top, "up")        # already on top -> no-op
        self.assertEqual(self._order(v)[-1], top)
        bottom = self._order(v)[0]
        v.reorder_annotation(bottom, "down")   # already at back -> no-op
        self.assertEqual(self._order(v)[0], bottom)
        # single mark on a page: nothing to reorder
        win2 = self._win(); v2 = win2.view
        lone = Annotation(page=0, kind=KIND_RECT, rect=(1, 1, 2, 2))
        v2._assign_top_z(lone); v2.store.add(lone)
        v2.reorder_annotation(lone, "front")   # must not raise
        self.assertEqual(len([m for m in v2.store.all()]), 1)

    def test_z_order_persists_and_exports(self):
        win = self._win(); v = win.view
        a, b, c = self._three(v)
        v.reorder_annotation(a, "front")
        za = a.z_order
        marked = win.document.save()
        win.document.close()
        # reopen: z_order restored from the sidecar
        from app.model.document import Document
        doc2 = Document(marked); doc2.load()
        ra = [m for m in doc2.store.all() if m.id == a.id][0]
        self.assertEqual(ra.z_order, za)
        doc2.close()


if __name__ == "__main__":
    unittest.main()
