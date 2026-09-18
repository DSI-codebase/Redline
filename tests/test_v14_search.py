"""The upgraded Ctrl+F: search engine (case/word/regex/context/marks/decode),
the results-index panel, its persistence, and search history."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

# `app.config` reaches PySide6 (QSettings), so these imports are what made
# the module ERROR rather than skip.
if _QT_OK:
    from app.viewer.doc_search import (
        DocumentSearch, SearchOptions, BadPatternError, MAX_MATCHES,
    )
    from app.model.annotations import (
        AnnotationStore, Annotation, KIND_TEXTBOX, KIND_COMMENT,
    )
    from app.config import AppConfig, MAX_RECENT_SEARCHES
    from PySide6.QtWidgets import QApplication


def _make_pdf(dirpath, name="s.pdf", pages=1, lines=None):
    p = os.path.join(dirpath, name)
    d = fitz.open()
    for _ in range(pages):
        pg = d.new_page(width=612, height=792)
        y = 100
        for line in (lines or ["HELLO WORLD apple",
                               "FEED FROM CB-10412 VIA XFMR-20031",
                               "apple Apple APPLE pineapple",
                               "wire 300801 runs to LT-10010 coil"]):
            pg.insert_text((72, y), line)
            y += 40
    d.save(p)
    d.close()
    return p


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestEngine(unittest.TestCase):
    """DocumentSearch alone — no Qt."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = fitz.open(_make_pdf(self.tmp))
        self.eng = DocumentSearch(self.doc)

    def tearDown(self):
        self.doc.close()

    def test_plain_search_is_case_insensitive(self):
        r = self.eng.search("apple", SearchOptions())
        self.assertEqual(len(r.matches), 5)   # apple, apple/Apple/APPLE, pineapple

    def test_match_case(self):
        r = self.eng.search("APPLE", SearchOptions(case_sensitive=True))
        self.assertEqual([m.text for m in r.matches], ["APPLE"])

    def test_whole_word(self):
        r = self.eng.search("apple", SearchOptions(whole_word=True))
        # pineapple no longer matches; the three case variants do
        self.assertEqual(len(r.matches), 4)
        self.assertTrue(all(m.text.lower() == "apple" for m in r.matches))

    def test_whole_word_and_case_combine(self):
        r = self.eng.search("apple",
                            SearchOptions(whole_word=True, case_sensitive=True))
        self.assertEqual(len(r.matches), 2)   # line 1 + line 3 lowercase only

    def test_regex(self):
        r = self.eng.search(r"CB-\d+", SearchOptions(regex=True))
        self.assertEqual([m.text for m in r.matches], ["CB-10412"])

    def test_bad_regex_raises(self):
        with self.assertRaises(BadPatternError):
            self.eng.search("(", SearchOptions(regex=True))

    def test_zero_width_regex_does_not_hang(self):
        r = self.eng.search(r"x*", SearchOptions(regex=True))
        self.assertTrue(all(m.text for m in r.matches))

    def test_context_surrounds_the_hit(self):
        r = self.eng.search("CB-10412", SearchOptions())
        m = r.matches[0]
        self.assertIn("FEED FROM", m.before)
        self.assertIn("VIA XFMR-20031", m.after)

    def test_context_on_index_path_too(self):
        r = self.eng.search("CB-10412", SearchOptions(case_sensitive=True))
        m = r.matches[0]
        self.assertIn("FEED FROM", m.before)
        self.assertIn("VIA", m.after)

    def test_matches_are_page_ordered(self):
        doc = fitz.open(_make_pdf(self.tmp, "multi.pdf", pages=3))
        try:
            r = DocumentSearch(doc).search("apple", SearchOptions())
            pages = [m.page for m in r.matches]
            self.assertEqual(pages, sorted(pages))
        finally:
            doc.close()

    def test_cap(self):
        doc = fitz.open()
        pg = doc.new_page(width=612, height=792)
        for i in range(60):
            pg.insert_text((40, 30 + i * 12), "zz " * 30)
        eng = DocumentSearch(doc)
        try:
            r = eng.search("z", SearchOptions(case_sensitive=True))
            self.assertTrue(r.capped)
            self.assertEqual(len(r.matches), MAX_MATCHES)
        finally:
            doc.close()

    def test_component_decode(self):
        from app.extraction.component_parser import ComponentConfig
        r = self.eng.search("LT-10010", SearchOptions(),
                            component_config=ComponentConfig())
        self.assertIn("tag LT", r.matches[0].decode)
        self.assertIn("sheet 100", r.matches[0].decode)
        self.assertIn("rung 10", r.matches[0].decode)

    def test_wire_decode(self):
        from app.extraction.wire_parser import WireConfig
        r = self.eng.search("300801", SearchOptions(),
                            wire_config=WireConfig())
        self.assertIn("wire", r.matches[0].decode)
        self.assertIn("sheet 300", r.matches[0].decode)

    def test_plain_text_has_no_decode(self):
        from app.extraction.component_parser import ComponentConfig
        from app.extraction.wire_parser import WireConfig
        r = self.eng.search("pineapple", SearchOptions(),
                            component_config=ComponentConfig(),
                            wire_config=WireConfig())
        self.assertEqual(r.matches[0].decode, "")

    # -- marks ---------------------------------------------------------------

    def _store(self):
        store = AnnotationStore()
        store.add(Annotation(page=0, kind=KIND_TEXTBOX, rect=(50, 50, 200, 80),
                             text="replace the apple valve", author="EM"),
                  silent=True)
        store.add(Annotation(page=0, kind=KIND_COMMENT, rect=(60, 700, 84, 724),
                             text="ignored apple", ignored=True), silent=True)
        return store

    def test_marks_are_searched(self):
        r = self.eng.search("apple", SearchOptions(include_marks=True),
                            store=self._store())
        marks = [m for m in r.matches if m.source == "mark"]
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0].kind, KIND_TEXTBOX)
        self.assertEqual(marks[0].author, "EM")
        self.assertIn("replace the", marks[0].before)

    def test_ignored_marks_are_skipped(self):
        r = self.eng.search("ignored apple", SearchOptions(include_marks=True),
                            store=self._store())
        self.assertEqual([m for m in r.matches if m.source == "mark"], [])

    def test_marks_can_be_excluded(self):
        r = self.eng.search("apple", SearchOptions(include_marks=False),
                            store=self._store())
        self.assertTrue(all(m.source == "text" for m in r.matches))


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestSearchHistoryConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig()
        self.cfg.clear_recent_searches()

    def tearDown(self):
        self.cfg.clear_recent_searches()

    def test_most_recent_first_and_deduped(self):
        self.cfg.add_recent_search("CB-10412")
        self.cfg.add_recent_search("apple")
        self.cfg.add_recent_search("cb-10412")     # case-insensitive dedupe
        self.assertEqual(self.cfg.recent_searches, ["cb-10412", "apple"])

    def test_capped(self):
        for i in range(MAX_RECENT_SEARCHES + 5):
            self.cfg.add_recent_search(f"q{i}")
        self.assertEqual(len(self.cfg.recent_searches), MAX_RECENT_SEARCHES)
        self.assertEqual(self.cfg.recent_searches[0],
                         f"q{MAX_RECENT_SEARCHES + 4}")

    def test_survives_corrupt_value(self):
        self.cfg.set("search/recent", "{not json")
        self.assertEqual(self.cfg.recent_searches, [])


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestSearchPanel(unittest.TestCase):
    """The panel + viewer wiring."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.model.document import Document
        from app.viewer.pdf_view import PdfView
        cfg = AppConfig()
        cfg.clear_recent_searches()
        for k in ("search/case", "search/word", "search/regex"):
            cfg.set(k, "false")
        cfg.set("search/marks", "true")
        self.tmp = tempfile.mkdtemp()
        self.doc = Document(_make_pdf(self.tmp)); self.doc.load()
        self.view = PdfView()
        self.view.set_document(self.doc, cfg)
        self.app.processEvents()

    def tearDown(self):
        AppConfig().clear_recent_searches()
        try:
            self.doc.close()
        except Exception:
            pass

    def _open(self, q="apple"):
        self.view.show_search()
        self.view.run_search(q)
        return self.view._search_bar

    def test_canvas_escape_keeps_the_panel_open(self):
        bar = self._open()
        self.view.cancel_action()                    # Esc pressed in the canvas
        self.assertFalse(bar.isHidden())
        self.assertTrue(self.view._search_matches)   # highlights intact too

    def test_close_button_still_closes(self):
        bar = self._open()
        bar.btn_close.click()
        self.assertTrue(bar.isHidden())
        self.assertEqual(self.view._search_matches, [])

    def test_panel_survives_document_switch_and_researches(self):
        from app.model.document import Document
        bar = self._open("apple")
        bar.input.setText("apple")
        doc2 = Document(_make_pdf(self.tmp, "second.pdf")); doc2.load()
        self.view.set_document(doc2, self.view.config)
        self.app.processEvents()                     # runs the deferred re-run
        try:
            self.assertFalse(bar.isHidden())
            self.assertTrue(self.view._search_matches)
        finally:
            doc2.close()

    def test_results_list_has_headers_and_rows(self):
        from app.viewer.search_bar import ROLE_INDEX
        bar = self._open()
        kinds = [bar.results.item(i).data(ROLE_INDEX)
                 for i in range(bar.results.count())]
        self.assertIn(-1, kinds)                     # a page header
        self.assertEqual(sorted(k for k in kinds if k >= 0),
                         list(range(len(self.view._search_matches))))

    def test_clicking_a_row_jumps_to_that_match(self):
        from app.viewer.search_bar import ROLE_INDEX
        bar = self._open()
        last = len(self.view._search_matches) - 1
        row = bar._match_rows[last]
        bar._activate_item(bar.results.item(row))
        self.assertEqual(self.view._search_index, last)

    def test_next_syncs_the_list_selection(self):
        bar = self._open()
        self.view.search_next()
        item = bar.results.currentItem()
        from app.viewer.search_bar import ROLE_INDEX
        self.assertEqual(item.data(ROLE_INDEX), self.view._search_index)

    def test_option_toggle_researches(self):
        bar = self._open("apple")
        n_plain = len(self.view._search_matches)
        bar.opt_word.setChecked(True)                # emits optionsChanged
        self.assertLess(len(self.view._search_matches), n_plain)

    def test_bad_regex_shows_error_not_crash(self):
        bar = self._open()
        bar.opt_regex.setChecked(True)
        self.view.run_search("(")
        self.assertEqual(bar.count.text(), "—")
        self.assertEqual(self.view._search_matches, [])

    def test_mark_matches_appear_and_jump(self):
        self.doc.store.add(
            Annotation(page=0, kind=KIND_TEXTBOX, rect=(40, 40, 220, 70),
                       text="the apple note"), silent=True)
        self._open("apple")
        marks = [i for i, m in enumerate(self.view._search_hits)
                 if m.source == "mark"]
        self.assertEqual(len(marks), 1)
        self.view.search_activate(marks[0])
        self.assertEqual(self.view._search_index, marks[0])

    def test_enter_records_history(self):
        bar = self._open()
        bar.input.setText("XFMR-20031")
        bar._on_return()
        self.assertIn("XFMR-20031", AppConfig().recent_searches)

    def test_history_feeds_the_completer(self):
        bar = self._open()
        bar.remember("unique_query_zz")
        model = bar.input.completer().model()
        strings = [model.data(model.index(i, 0))
                   for i in range(model.rowCount())]
        self.assertIn("unique_query_zz", strings)

    def test_count_label_and_current(self):
        bar = self._open()
        n = len(self.view._search_matches)
        self.assertEqual(bar.count.text(), f"1/{n}")

    def test_cycling_matches_does_not_scroll_the_panel_away(self):
        # Jumping between matches scrolls the view; the panel used to be a
        # child of the *viewport*, and QGraphicsView scrolls viewport children
        # along with the content — so Enter carried the panel off-screen.
        from app.model.document import Document
        src = _make_pdf(self.tmp, "many.pdf", pages=6)
        doc2 = Document(src); doc2.load()
        self.view.set_document(doc2, self.view.config)
        self.view.resize(1000, 700)
        self.view.show()
        self.app.processEvents()
        try:
            # "HELLO" appears once per page, so every jump scrolls a full page
            # ("apple" would cluster several matches in view and never scroll)
            self.view.show_search()
            self.view.run_search("HELLO")
            self.app.processEvents()
            bar = self.view._search_bar
            home = bar.pos()
            moved = False
            for _ in range(4):
                before_y = self.view.verticalScrollBar().value()
                self.view.search_next()
                self.app.processEvents()
                moved = moved or (self.view.verticalScrollBar().value()
                                  != before_y)
                self.assertEqual(bar.pos(), home)
                self.assertFalse(bar.isHidden())
                self.assertFalse(bar.visibleRegion().isEmpty())
            self.assertTrue(moved, "test never scrolled — it proves nothing")
        finally:
            doc2.close()

    def test_short_context_is_not_spuriously_elided(self):
        # elidedText() at a width exactly equal to horizontalAdvance() still
        # elides (integer metrics round below the true advance), so every row
        # used to lose a character or two even with the whole row free.
        from PySide6.QtGui import QFont, QFontMetrics
        from app.viewer.search_bar import _ResultDelegate
        from PySide6.QtCore import Qt
        f = QFont(); fm = QFontMetrics(f)
        b = QFont(); b.setBold(True); fmb = QFontMetrics(b)
        before, match, after = "page 0 ", "apple", " target"
        bw, mw, aw = _ResultDelegate._budget(fm, fmb, before, match, after,
                                             avail=360)
        self.assertEqual(fm.elidedText(before, Qt.ElideLeft, bw), before)
        self.assertEqual(fmb.elidedText(match, Qt.ElideRight, mw), match)
        self.assertEqual(fm.elidedText(after, Qt.ElideRight, aw), after)
        # and a genuinely long line still gets cut down to the room available
        long = "X" * 400
        bw, mw, aw = _ResultDelegate._budget(fm, fmb, long, match, long,
                                             avail=360)
        self.assertLessEqual(bw + mw + aw, 360)
        self.assertNotEqual(fm.elidedText(long, Qt.ElideLeft, bw), long)

    def test_panel_repositions_on_resize(self):
        # hidden widgets don't receive resize events — show the view (offscreen)
        self.view.show()
        bar = self._open()
        self.view.resize(900, 500)
        self.app.processEvents()
        right_gap = self.view.viewport().width() - (bar.x() + bar.width())
        self.assertGreaterEqual(right_gap, 8)
        self.assertLessEqual(right_gap, 40)


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestMainWindowShortcuts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        cfg = AppConfig()
        cfg.s.remove("ui/window_state")
        cfg.s.remove("ui/geometry")

    def test_find_next_prev_actions_exist(self):
        from PySide6.QtGui import QAction, QKeySequence
        from app.main_window import MainWindow
        win = MainWindow()
        texts = {}
        for a in win.findChildren(QAction):
            for ks in a.shortcuts():
                texts[ks.toString()] = a.text()
        want_next = QKeySequence(QKeySequence.FindNext).toString()
        want_prev = QKeySequence(QKeySequence.FindPrevious).toString()
        if want_next:
            self.assertIn(want_next, texts)
        if want_prev:
            self.assertIn(want_prev, texts)


if __name__ == "__main__":
    unittest.main()
