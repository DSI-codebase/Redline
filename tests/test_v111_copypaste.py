"""Copy / paste marks, copy / paste formatting, and sticky style memory."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import (
    Annotation, COPYABLE_KINDS, STYLE_FIELDS,
    KIND_RECT, KIND_CALLOUT, KIND_CLOUD, KIND_ARROW, KIND_TEXTBOX,
    KIND_PEN, KIND_COMMENT, KIND_HIGHLIGHT,
)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


# --- model layer -----------------------------------------------------------

class TestCopyModel(unittest.TestCase):
    def test_clone_new_id_and_deep_copy(self):
        a = Annotation(page=1, kind=KIND_CLOUD, points=[(1, 2), (3, 4), (5, 6)],
                       color=(1, 0, 0), text="x")
        b = a.clone()
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(a.points, b.points)
        b.points.append((9, 9))                    # deep copy — a is unaffected
        self.assertEqual(len(a.points), 3)
        self.assertEqual(b.text, "x")

    def test_clone_same_id_option(self):
        a = Annotation(page=0, kind=KIND_RECT)
        self.assertEqual(a.clone(new_id=False).id, a.id)

    def test_translate_rect_points_callout(self):
        a = Annotation(page=0, kind=KIND_CALLOUT, rect=(10, 10, 50, 30),
                       callout_point=(5, 60))
        a.translate(100, 5)
        self.assertEqual(a.rect, (110, 15, 150, 35))
        self.assertEqual(a.callout_point, (105, 65))
        c = Annotation(page=0, kind=KIND_CLOUD, points=[(0, 0), (10, 0), (10, 10)])
        c.translate(2, 3)
        self.assertEqual(c.points, [(2, 3), (12, 3), (12, 13)])

    def test_style_dict_excludes_text_and_geometry(self):
        a = Annotation(page=0, kind=KIND_RECT, color=(1, 0, 0), fill_color=(0, 0, 1),
                       fill_opacity=0.5, width=3.0, text="keep me", rect=(1, 2, 3, 4))
        s = a.style_dict()
        self.assertEqual(set(s), set(STYLE_FIELDS))
        self.assertNotIn("text", s)
        self.assertNotIn("rect", s)
        b = Annotation(page=0, kind=KIND_RECT, text="mine", rect=(9, 9, 9, 9))
        b.apply_style(s)
        self.assertEqual(b.color, (1, 0, 0))
        self.assertEqual(b.fill_color, (0, 0, 1))
        self.assertEqual(b.width, 3.0)
        self.assertEqual(b.text, "mine")          # text NOT copied
        self.assertEqual(b.rect, (9, 9, 9, 9))     # geometry NOT copied

    def test_copyable_kinds(self):
        from app.model.annotations import KIND_CIRCLE, KIND_LINE
        self.assertEqual(COPYABLE_KINDS,
                         {KIND_TEXTBOX, KIND_CALLOUT, KIND_RECT, KIND_CIRCLE,
                          KIND_ARROW, KIND_LINE, KIND_CLOUD})


# --- view layer ------------------------------------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestCopyPasteView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _win(self, pages=1):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        d = fitz.open()
        for _ in range(pages):
            d.new_page(width=400, height=300)
        d.save(src); d.close()
        win = MainWindow(); win.load_document(src)
        return win

    def test_copy_paste_offsets_new_mark(self):
        win = self._win(); v = win.view
        rect = Annotation(page=0, kind=KIND_RECT, rect=(30, 30, 120, 90),
                          color=(1, 0, 0), fill_color=(0, 0.6, 1))
        v.store.add(rect)
        v.copy_annotation(rect)
        v.paste_clipboard()
        rects = [a for a in v.store.all() if a.kind == KIND_RECT]
        self.assertEqual(len(rects), 2)
        pasted = [a for a in rects if a.id != rect.id][0]
        self.assertNotEqual(pasted.id, rect.id)
        self.assertGreater(pasted.rect[0], rect.rect[0])     # offset right/down
        self.assertEqual(pasted.fill_color, (0, 0.6, 1))     # style carried
        # pasted mark is selected
        self.assertTrue(v._item_by_ann[pasted.id].isSelected())

    def test_paste_is_one_undo_step(self):
        win = self._win(); v = win.view
        rect = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 60, 40))
        v.store.add(rect)
        v.copy_marks([rect])
        v.paste_clipboard()
        self.assertEqual(len([a for a in v.store.all() if a.kind == KIND_RECT]), 2)
        v.undo_stack.undo()
        self.assertEqual(len([a for a in v.store.all() if a.kind == KIND_RECT]), 1)

    def test_repeated_paste_cascades(self):
        win = self._win(); v = win.view
        rect = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 60, 40))
        v.store.add(rect)
        v.copy_marks([rect])
        v.paste_clipboard()
        v.paste_clipboard()
        xs = sorted(a.rect[0] for a in v.store.all() if a.kind == KIND_RECT)
        self.assertEqual(len(set(xs)), 3)          # original + two distinct offsets

    def test_copy_multiple(self):
        win = self._win(); v = win.view
        a = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 40, 40))
        b = Annotation(page=0, kind=KIND_ARROW, rect=(50, 50, 90, 90))
        v.store.add(a); v.store.add(b)
        v.copy_marks([a, b])
        v.paste_clipboard()
        self.assertEqual(len(v.store.all()), 4)

    def test_non_copyable_kinds_ignored(self):
        win = self._win(); v = win.view
        pen = Annotation(page=0, kind=KIND_PEN, points=[(1, 1), (2, 2)])
        v.copy_marks([pen])
        self.assertFalse(v._obj_clip)              # pen isn't copyable
        v.paste_clipboard()
        self.assertEqual(v.store.all(), [pen] if pen in v.store.all() else [])

    def test_paste_clamps_page_into_range(self):
        win = self._win(pages=1); v = win.view
        ghost = Annotation(page=7, kind=KIND_RECT, rect=(10, 10, 40, 40))
        v._obj_clip = [ghost.to_dict()]
        v.paste_clipboard()
        pasted = [a for a in v.store.all() if a.kind == KIND_RECT][0]
        self.assertEqual(pasted.page, 0)           # clamped to a valid page

    def test_ctrl_c_prefers_selected_mark_over_text(self):
        win = self._win(); v = win.view
        rect = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 60, 40))
        v.store.add(rect)
        v._item_by_ann[rect.id].setSelected(True)
        v._selected_text = "some page text"
        v.copy_selection()                          # the Ctrl+C entry point
        self.assertEqual(len(v._obj_clip), 1)       # copied the mark, not the text


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestFormatPaint(unittest.TestCase):
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

    def test_paste_format_same_kind_only(self):
        win = self._win(); v = win.view
        src = Annotation(page=0, kind=KIND_RECT, color=(1, 0, 0), width=3,
                         fill_color=(0, 0, 1), fill_opacity=0.5, rect=(10, 10, 60, 40))
        v.copy_format(src)
        self.assertTrue(v.has_format_for(KIND_RECT))
        self.assertFalse(v.has_format_for(KIND_CLOUD))
        # applies to a same-kind mark
        tgt = Annotation(page=0, kind=KIND_RECT, color=(0, 0, 0), width=1,
                         text="keep", rect=(100, 100, 150, 130))
        v.store.add(tgt)
        v.paste_format(tgt)
        self.assertEqual(tgt.color, (1, 0, 0))
        self.assertEqual(tgt.fill_color, (0, 0, 1))
        self.assertEqual(tgt.width, 3)
        self.assertEqual(tgt.text, "keep")          # content untouched
        self.assertEqual(tgt.rect, (100, 100, 150, 130))  # geometry untouched
        # undoable
        v.undo_stack.undo()
        self.assertIsNone(tgt.fill_color)

    def test_paste_format_wrong_kind_noop(self):
        win = self._win(); v = win.view
        v.copy_format(Annotation(page=0, kind=KIND_RECT, color=(1, 0, 0)))
        cloud = Annotation(page=0, kind=KIND_CLOUD, color=(0, 0, 0),
                           points=[(1, 1), (2, 2), (3, 3)])
        v.store.add(cloud)
        v.paste_format(cloud)                        # kind mismatch -> no change
        self.assertEqual(cloud.color, (0, 0, 0))


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestStickyStyleMemory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_remember_text_style_updates_tool(self):
        from app.main_window import MainWindow
        win = MainWindow()
        fv = {"font_size": 22.0, "bold": True, "italic": False,
              "color": (0.0, 0.5, 0.0), "fill_color": (1, 1, 0), "fill_opacity": 0.8}
        win._remember_text_style(fv)
        t = win.view.tool
        self.assertEqual(t.text_color, (0.0, 0.5, 0.0))
        self.assertEqual(t.font_size, 22.0)
        self.assertTrue(t.bold)
        self.assertEqual(t.text_fill, (1, 1, 0))
        self.assertEqual(t.text_fill_opacity, 0.8)
        # toolbar controls reflect it
        self.assertEqual(win.font_size.value(), 22)
        self.assertTrue(win.bold.isChecked())

    def test_remember_none_is_safe(self):
        from app.main_window import MainWindow
        win = MainWindow()
        win._remember_text_style(None)               # a comment (no font values)


if __name__ == "__main__":
    unittest.main()
