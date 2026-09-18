"""v1.1.0 Phase 1: notes on any mark.

A note (free text) can be attached to any mark kind - not just comments and
text boxes. Noted marks surface in the Comments sidebar, show a corner badge on
the canvas, and export a genuine comment popup to the PDF.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import (
    Annotation, AnnotationStore,
    KIND_HIGHLIGHT, KIND_PEN, KIND_COMMENT, KIND_TEXTBOX, KIND_RECT, KIND_ARROW,
)
from app.model.storage import (
    write_annotations_to_pdf, load_pdf_annotations,
    marked_pdf_path, DEFAULT_IGNORE_PATTERNS,
)

try:
    from PySide6.QtWidgets import QApplication
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


# --- model layer -----------------------------------------------------------

class TestNoteModel(unittest.TestCase):
    def test_has_note(self):
        self.assertFalse(Annotation(page=0, kind=KIND_RECT).has_note)
        self.assertFalse(Annotation(page=0, kind=KIND_RECT, text="   ").has_note)
        self.assertTrue(Annotation(page=0, kind=KIND_RECT, text="fix this").has_note)

    def test_shows_in_comments(self):
        # inherently textual + historically-listed kinds always show
        for k in (KIND_COMMENT, KIND_TEXTBOX, KIND_HIGHLIGHT, KIND_PEN):
            self.assertTrue(Annotation(page=0, kind=k).shows_in_comments)
        # bare shape marks do NOT show until noted
        self.assertFalse(Annotation(page=0, kind=KIND_RECT).shows_in_comments)
        self.assertFalse(Annotation(page=0, kind=KIND_ARROW).shows_in_comments)
        # ...but a note pulls them into the sidebar
        self.assertTrue(Annotation(page=0, kind=KIND_RECT, text="note").shows_in_comments)
        self.assertTrue(Annotation(page=0, kind=KIND_ARROW, text="note").shows_in_comments)


# --- comment sidebar -------------------------------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestSidebarIncludesNoted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel_with(self, anns):
        from app.panels.comment_panel import CommentPanel
        store = AnnotationStore()
        for a in anns:
            store.add(a, silent=True)
        panel = CommentPanel()
        panel.set_store(store, config=None)
        panel.refresh()
        return panel

    def _texts(self, panel):
        from PySide6.QtCore import Qt
        return [panel.tree.topLevelItem(i).data(0, Qt.UserRole)
                for i in range(panel.tree.topLevelItemCount())]

    def test_noted_rect_and_arrow_listed_bare_ones_not(self):
        noted_rect = Annotation(page=0, kind=KIND_RECT, text="check clearance")
        bare_rect = Annotation(page=1, kind=KIND_RECT)
        noted_arrow = Annotation(page=2, kind=KIND_ARROW, text="wrong feed")
        bare_arrow = Annotation(page=3, kind=KIND_ARROW)
        hl = Annotation(page=4, kind=KIND_HIGHLIGHT)
        panel = self._panel_with([noted_rect, bare_rect, noted_arrow, bare_arrow, hl])
        listed = self._texts(panel)
        self.assertIn(noted_rect, listed)
        self.assertIn(noted_arrow, listed)
        self.assertIn(hl, listed)               # highlights always listed
        self.assertNotIn(bare_rect, listed)
        self.assertNotIn(bare_arrow, listed)

    def test_rectangle_and_arrow_type_filters(self):
        from PySide6.QtCore import Qt
        noted_rect = Annotation(page=0, kind=KIND_RECT, text="a")
        noted_arrow = Annotation(page=1, kind=KIND_ARROW, text="b")
        panel = self._panel_with([noted_rect, noted_arrow])
        # "Rectangle" filter (index 5) shows only the rect
        panel.type_filter.setCurrentIndex(5)
        panel.refresh()
        rows = [panel.tree.topLevelItem(i).data(0, Qt.UserRole)
                for i in range(panel.tree.topLevelItemCount())]
        self.assertEqual(rows, [noted_rect])
        # "Arrow" filter (index 6) shows only the arrow
        panel.type_filter.setCurrentIndex(6)
        panel.refresh()
        rows = [panel.tree.topLevelItem(i).data(0, Qt.UserRole)
                for i in range(panel.tree.topLevelItemCount())]
        self.assertEqual(rows, [noted_arrow])


# --- PDF export ------------------------------------------------------------

class TestNoteExport(unittest.TestCase):
    def _blank(self, path):
        d = fitz.open(); d.new_page(width=600, height=400); d.save(path); d.close()

    def test_noted_shape_exports_popup_and_content(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        self._blank(src)
        anns = [
            Annotation(page=0, kind=KIND_RECT, rect=(50, 50, 200, 120),
                       color=(1, 0, 0), width=1.5, author="Eli", text="raise 6 in"),
            Annotation(page=0, kind=KIND_ARROW, rect=(300, 60, 380, 140),
                       color=(0, 0, 1), width=2.0, author="Eli", text="reroute"),
        ]
        d = fitz.open(src)
        write_annotations_to_pdf(d, anns)
        mp = marked_pdf_path(src)
        d.save(mp)
        d.close()

        d2 = fitz.open(mp)
        # each note also becomes a standalone sticky-note comment (visible in any
        # viewer), carrying the content and a popup
        stickies = [a for a in d2[0].annots() if a.type[1] == "Text"]
        contents = sorted(a.info.get("content") for a in stickies)
        self.assertEqual(contents, ["raise 6 in", "reroute"])
        self.assertTrue(all(a.has_popup for a in stickies))
        d2.close()

        # the note round-trips back onto the same mark (the sticky is skipped)
        loaded = load_pdf_annotations(fitz.open(mp), DEFAULT_IGNORE_PATTERNS)
        by_kind = {a.kind: a for a in loaded}
        self.assertEqual(by_kind[KIND_RECT].text, "raise 6 in")
        self.assertEqual(by_kind[KIND_ARROW].text, "reroute")
        self.assertNotIn(KIND_COMMENT, by_kind)   # no duplicate comment on reload

    def test_unnoted_shape_has_no_popup(self):
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
        self.assertFalse(any(a.has_popup for a in d2[0].annots()))
        d2.close()


# --- canvas badge ----------------------------------------------------------

@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestNoteBadge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_badge_toggles_with_note(self):
        from app.viewer.annotation_items import make_item, _NoteBadge

        class _StubView:
            select_mode = True
            store = AnnotationStore()

        view = _StubView()
        ann = Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60))
        item = make_item(ann, view)

        # no note -> no badge (or a hidden one)
        item._refresh_note_badge()
        badge = getattr(item, "_note_badge", None)
        self.assertTrue(badge is None or not badge.isVisible())

        # attach a note -> badge appears
        ann.text = "verify"
        item._refresh_note_badge()
        self.assertIsInstance(item._note_badge, _NoteBadge)
        self.assertTrue(item._note_badge.isVisible())

        # clear the note -> badge hides again
        ann.text = ""
        item._refresh_note_badge()
        self.assertFalse(item._note_badge.isVisible())

    def test_comment_mark_never_badged(self):
        from app.viewer.annotation_items import make_item

        class _StubView:
            select_mode = True
            store = AnnotationStore()

        ann = Annotation(page=0, kind=KIND_COMMENT, rect=(10, 10, 26, 26), text="hi")
        item = make_item(ann, _StubView())
        item._refresh_note_badge()
        self.assertIsNone(getattr(item, "_note_badge", None))


if __name__ == "__main__":
    unittest.main()
