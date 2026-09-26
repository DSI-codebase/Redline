"""The File view and the recent list behind it.

Three layers, asserted where each one acts:

* `app/model/recent.py` -- one entry per DRAWING (`foo.pdf` and
  `foo.marked.pdf` share a sidecar, so the recent list spent two slots on one
  drawing), which file a row opens, the date groups, and search. No Qt, so
  these run on a machine without it.
* `AppConfig` -- the list keeps `recent_max` drawings with the time each was
  opened, pins are a separate list that Clear list leaves alone, and a list
  written before times were kept still reads.
* the File view and the window -- groups, the not-found state, the right-click
  menu, Esc, drops, the overlay's geometry, Ctrl+O, and a successful open from
  ANY route taking the view down.

`AppConfig` is QSettings, which is the real per-user store, so every test that
writes the recent keys puts back exactly what was there.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model import recent as R
from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

if _QT_OK:
    from PySide6.QtCore import Qt, QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
    from app.config import AppConfig, RECENT_FILES_BOUNDS

_KEYS = ("recent/files", "recent/opened", "recent/pinned", "recent/max")


def _touch(path, pdf=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if pdf:
        d = fitz.open()
        d.new_page(width=300, height=200)
        d.save(path)
        d.close()
    else:
        # empty: a valid (new) SQLite file for a sidecar, and not a PDF
        open(path, "wb").close()
    return path


# --- the rules, without Qt ---------------------------------------------------

class TestOneEntryPerDrawing(unittest.TestCase):

    def test_a_drawing_and_its_marked_copy_are_one_key(self):
        self.assertEqual(R.drawing_key("/p/foo.pdf"), R.drawing_key("/p/foo.marked.pdf"))
        self.assertNotEqual(R.drawing_key("/p/foo.pdf"), R.drawing_key("/q/foo.pdf"))
        self.assertNotEqual(R.drawing_key("/p/foo.pdf"), R.drawing_key("/p/bar.pdf"))

    def test_dedupe_keeps_the_first_spelling(self):
        self.assertEqual(R.dedupe(["/p/foo.marked.pdf", "/p/bar.pdf", "/p/foo.pdf"]),
                         ["/p/foo.marked.pdf", "/p/bar.pdf"])


class TestWhichFileARowOpens(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.pdf = os.path.join(self.d, "foo.pdf")
        self.marked = os.path.join(self.d, "foo.marked.pdf")
        self.db = os.path.join(self.d, "foo.markup.db")

    def test_the_original_when_it_is_all_there_is(self):
        _touch(self.pdf)
        self.assertEqual(R.open_target(self.marked), self.pdf)

    def test_the_original_when_its_sidecar_holds_the_marks(self):
        for p in (self.pdf, self.marked):
            _touch(p)
        _touch(self.db, pdf=False)
        for stored in (self.pdf, self.marked):
            with self.subTest(stored=os.path.basename(stored)):
                self.assertEqual(R.open_target(stored), self.pdf)

    def test_the_marked_copy_when_the_sidecar_is_missing(self):
        # Opening foo.pdf here would show a clean sheet: a document never reads
        # its marked copy's annotations, and the sidecar that holds them is gone.
        for p in (self.pdf, self.marked):
            _touch(p)
        for stored in (self.pdf, self.marked):
            with self.subTest(stored=os.path.basename(stored)):
                self.assertEqual(R.open_target(stored), self.marked)

    def test_the_marked_copy_when_it_is_all_there_is(self):
        _touch(self.marked)
        self.assertEqual(R.open_target(self.pdf), self.marked)

    def test_the_stored_path_when_neither_exists(self):
        self.assertEqual(R.open_target(self.marked), self.marked)


class TestDateGroups(unittest.TestCase):
    NOW = datetime(2026, 9, 26, 9, 30)

    def _at(self, **delta):
        return (self.NOW - timedelta(**delta)).isoformat(timespec="seconds")

    def test_calendar_days_not_hours(self):
        # 23:50 yesterday is yesterday, though it is under ten hours ago
        self.assertEqual(R.date_group("2026-09-25T23:50:00", self.NOW), R.GROUP_YESTERDAY)
        self.assertEqual(R.date_group("2026-09-26T00:05:00", self.NOW), R.GROUP_TODAY)

    def test_each_group(self):
        for delta, group in (({"minutes": 5}, R.GROUP_TODAY),
                             ({"days": 1}, R.GROUP_YESTERDAY),
                             ({"days": 2}, R.GROUP_THIS_WEEK),
                             ({"days": 6}, R.GROUP_THIS_WEEK),
                             ({"days": 7}, R.GROUP_OLDER),
                             ({"days": 400}, R.GROUP_OLDER)):
            with self.subTest(delta=delta):
                self.assertEqual(R.date_group(self._at(**delta), self.NOW), group)

    def test_no_time_is_older_rather_than_a_guess(self):
        for stamp in ("", None, "not a date"):
            with self.subTest(stamp=stamp):
                self.assertEqual(R.date_group(stamp, self.NOW), R.GROUP_OLDER)

    def test_a_stamp_with_an_offset_is_read_in_local_time(self):
        now = datetime.now().astimezone()
        stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
        self.assertEqual(R.date_group(stamp, now), R.GROUP_TODAY)


class TestSearch(unittest.TestCase):

    def test_every_word_in_name_or_folder_ignoring_case(self):
        p = "/work/Project 2417/drawings/E-101 Panel Schedule.pdf"
        self.assertTrue(R.matches("2417 panel", p))
        self.assertTrue(R.matches("SCHEDULE", p))
        self.assertFalse(R.matches("2417 invoice", p))
        self.assertTrue(R.matches("   ", p))


# --- the stored lists --------------------------------------------------------

@unittest.skipUnless(_QT_OK, _QT_REASON)
class _KeepsSettings(unittest.TestCase):
    """Snapshot and restore the recent keys of the real per-user settings."""

    def setUp(self):
        self.cfg = AppConfig()
        self._saved = {k: self.cfg.s.value(k) for k in _KEYS}
        for k in _KEYS:
            self.cfg.s.remove(k)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                self.cfg.s.remove(k)
            else:
                self.cfg.s.setValue(k, v)
        self.cfg.sync()

    def p(self, *parts):
        # normpath: a caller writing "dwg/foo.pdf" gets C:\...\dwg\foo.pdf on
        # Windows, the spelling the app stores (abspath) and hands back. Joined
        # as-is it was ...\dwg/foo.pdf, which is the same file and a different
        # string -- four tests failed on windows-latest on exactly that.
        return os.path.normpath(os.path.join(self.tmp, *parts))


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestRecentStore(_KeepsSettings):

    def test_a_drawing_takes_one_slot_whichever_file_opened_it(self):
        self.cfg.add_recent_file(self.p("foo.pdf"))
        self.cfg.add_recent_file(self.p("bar.pdf"))
        self.cfg.add_recent_file(self.p("foo.marked.pdf"))
        self.assertEqual([os.path.basename(p) for p in self.cfg.recent_files],
                         ["foo.marked.pdf", "bar.pdf"])

    def test_the_cap_is_the_setting_and_the_setting_is_bounded(self):
        self.assertEqual(self.cfg.recent_max, 50)
        lo, hi = RECENT_FILES_BOUNDS
        for stored, read in ((3, lo), (5000, hi), (25, 25)):
            with self.subTest(stored=stored):
                self.cfg.set("recent/max", stored)
                self.assertEqual(self.cfg.recent_max, read)
        self.cfg.set("recent/max", 12)
        for i in range(20):
            self.cfg.add_recent_file(self.p(f"f{i}.pdf"))
        self.assertEqual(len(self.cfg.recent_files), 12)
        # the STORED list is trimmed too, not only the read: otherwise it grows
        # for ever, and raising the setting brings back what was dropped
        import json
        self.assertEqual(len(json.loads(self.cfg.s.value("recent/files"))), 12)

    def test_the_open_time_follows_the_drawing(self):
        self.cfg.add_recent_file(self.p("foo.pdf"), when="2026-09-20T10:00:00")
        self.assertEqual(self.cfg.recent_opened(self.p("foo.marked.pdf")),
                         "2026-09-20T10:00:00")
        self.cfg.add_recent_file(self.p("foo.marked.pdf"))
        self.assertNotEqual(self.cfg.recent_opened(self.p("foo.pdf")),
                            "2026-09-20T10:00:00")

    def test_a_list_from_before_times_were_kept_still_reads(self):
        # the stored shape did not change, so an older build reads a newer list
        # too -- and a newer build reads an older one, with no time for each
        import json
        self.cfg.set("recent/files", json.dumps([self.p("old.pdf"), self.p("older.pdf")]))
        self.assertEqual(self.cfg.recent_files, [self.p("old.pdf"), self.p("older.pdf")])
        self.assertEqual(self.cfg.recent_opened(self.p("old.pdf")), "")
        self.assertIsInstance(json.loads(self.cfg.s.value("recent/files")), list)

    def test_remove_from_list_forgets_the_time_too(self):
        self.cfg.add_recent_file(self.p("foo.pdf"))
        self.cfg.remove_recent_file(self.p("foo.marked.pdf"))
        self.assertEqual(self.cfg.recent_files, [])
        self.assertEqual(self.cfg.recent_opened(self.p("foo.pdf")), "")

    def test_pins_are_their_own_list(self):
        self.cfg.add_recent_file(self.p("a.pdf"), when="2026-09-01T08:00:00")
        self.cfg.pin_file(self.p("a.marked.pdf"))
        self.cfg.pin_file(self.p("a.pdf"))                    # same drawing: once
        self.assertEqual(len(self.cfg.pinned_files), 1)
        self.assertTrue(self.cfg.is_pinned(self.p("a.pdf")))

        self.cfg.clear_recent_files()
        self.assertEqual(self.cfg.recent_files, [])
        self.assertTrue(self.cfg.is_pinned(self.p("a.pdf")), "Clear list unpinned it")
        # the pin keeps its time after the drawing leaves the recent list
        self.assertEqual(self.cfg.recent_opened(self.p("a.pdf")), "2026-09-01T08:00:00")

        self.cfg.set("recent/max", 10)
        for i in range(15):
            self.cfg.add_recent_file(self.p(f"f{i}.pdf"))
        self.assertTrue(self.cfg.is_pinned(self.p("a.pdf")), "a pin aged out")

        self.cfg.unpin_file(self.p("a.pdf"))
        self.assertEqual(self.cfg.pinned_files, [])
        self.assertEqual(self.cfg.recent_opened(self.p("a.pdf")), "")


# --- the page ----------------------------------------------------------------

@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestFileViewPage(_KeepsSettings):
    NOW = datetime(2026, 9, 26, 9, 30)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app.file_view import FileView
        self.win = QMainWindow()
        self.win.menuBar().addMenu("File")
        self.win.resize(1000, 700)
        self.win.show()
        self.fv = FileView(self.cfg, self.win)
        self.fv.now = lambda: self.NOW
        self.opened = []
        self.fv.openRequested.connect(self.opened.append)

    def tearDown(self):
        self.win.close()
        super().tearDown()

    def _add(self, rel, days=0, exists=True):
        path = self.p(rel)
        if exists:
            _touch(path)
        when = (self.NOW - timedelta(days=days)).isoformat(timespec="seconds")
        self.cfg.add_recent_file(path, when=when)
        return path

    def _row(self, name):
        for it in self.fv.file_rows():
            if it.text(0).startswith(name):
                return it
        raise AssertionError(f"no row {name!r} in {[i.text(0) for i in self.fv.file_rows()]}")

    def _menu_labels(self, item):
        return [a.text() for a in self.fv._context_menu_for(item).actions()
                if not a.isSeparator()]

    def _action(self, item, label):
        return next(a for a in self.fv._context_menu_for(item).actions()
                    if a.text() == label)

    def test_groups_in_order_with_a_pin_shown_once(self):
        self._add("old.pdf", days=30)
        self._add("week.pdf", days=3)
        self._add("yday.pdf", days=1)
        self._add("today.pdf", days=0)
        pin = self._add("pinned.pdf", days=0)
        self.cfg.pin_file(pin)
        self.fv.refresh()
        self.assertEqual(self.fv.groups(),
                         ["Pinned", "Today", "Yesterday", "This week", "Older"])
        names = [it.text(0) for it in self.fv.file_rows()]
        self.assertEqual(names, ["pinned.pdf", "today.pdf", "yday.pdf",
                                 "week.pdf", "old.pdf"])

    def test_a_click_opens_the_drawing_the_row_names(self):
        pdf = self._add("dwg/foo.pdf")
        _touch(self.p("dwg/foo.marked.pdf"))
        _touch(self.p("dwg/foo.markup.db"), pdf=False)
        self.cfg.add_recent_file(self.p("dwg/foo.marked.pdf"))
        self.fv.refresh()
        self.assertEqual(len(self.fv.file_rows()), 1)
        self.fv._on_clicked(self._row("foo.pdf"), 0)
        self.assertEqual(self.opened, [pdf])

    def test_a_missing_file_is_listed_grayed_and_does_not_open(self):
        self._add("gone.pdf", exists=False)
        self.fv.refresh()
        row = self._row("gone.pdf")
        self.assertIn("(not found)", row.text(0))
        self.fv._on_clicked(row, 0)
        self.assertEqual(self.opened, [])
        self.assertFalse(self._action(row, "Open").isEnabled())
        self.assertIn("Remove from list", self._menu_labels(row))

    def test_search_lists_hits_by_source(self):
        self._add("Project 2417/E-101 Panel Schedule.pdf", days=4)
        self._add("Downloads/invoice.pdf")
        pin = self._add("Project 2417/E-001 Cover.pdf")
        self.cfg.pin_file(pin)
        self.fv.search.setText("2417")
        self.assertEqual(self.fv.groups(), ["Pinned", "Recent"])
        self.assertEqual([it.text(0) for it in self.fv.file_rows()],
                         ["E-001 Cover.pdf", "E-101 Panel Schedule.pdf"])
        self.assertFalse(self.fv.tree.isHidden())
        self.fv.search.setText("nothing like it")
        self.assertEqual(self.fv.file_rows(), [])
        self.assertIn("nothing like it", self.fv.empty.text())
        # the message stands in place of an empty list, not under it
        self.assertEqual((self.fv.tree.isHidden(), self.fv.empty.isHidden()),
                         (True, False))

    def test_pin_and_unpin_move_the_row(self):
        self._add("a.pdf")
        self.fv.refresh()
        self.assertEqual(self._menu_labels(self._row("a.pdf")),
                         ["Open", "Pin", "Show in folder", "Copy path",
                          "Remove from list"])
        self._action(self._row("a.pdf"), "Pin").trigger()
        self.assertEqual(self.fv.groups(), ["Pinned"])
        # a pinned row is not removed from the list: Unpin is how it goes
        self.assertEqual(self._menu_labels(self._row("a.pdf")),
                         ["Open", "Unpin", "Show in folder", "Copy path"])
        self._action(self._row("a.pdf"), "Unpin").trigger()
        self.assertEqual(self.fv.groups(), ["Today"])

    def test_remove_copy_and_show_in_folder(self):
        path = self._add("sub/a.pdf")
        self.fv.refresh()
        self._action(self._row("a.pdf"), "Copy path").trigger()
        self.assertEqual(QApplication.clipboard().text(), os.path.abspath(path))
        with mock.patch("app.file_view.reveal_in_file_manager") as reveal:
            self._action(self._row("a.pdf"), "Show in folder").trigger()
        reveal.assert_called_once_with(path)
        self._action(self._row("a.pdf"), "Remove from list").trigger()
        self.assertEqual(self.fv.file_rows(), [])
        self.assertEqual(self.cfg.recent_files, [])
        self.assertTrue(os.path.isfile(path), "Remove from list touched the file")

    def test_esc_clears_the_search_before_it_goes_back(self):
        backs = []
        self.fv.backRequested.connect(lambda: backs.append(1))
        self.fv.search.setText("x")
        self.fv._on_escape()
        self.assertEqual((self.fv.search.text(), backs), ("", []))
        self.fv._on_escape()
        self.assertEqual(backs, [1])

    def test_a_dropped_pdf_is_opened(self):
        pdf = _touch(self.p("dropped.pdf"))
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(pdf)])
        ev = QDropEvent(QPointF(5, 5), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        self.fv.dropEvent(ev)
        self.assertEqual(self.opened, [pdf])

    def test_it_covers_the_window_below_the_menu_bar_and_follows_a_resize(self):
        self.fv.open_page()
        self.app.processEvents()
        top = self.win.menuBar().geometry().bottom() + 1
        self.assertGreater(top, 0)
        self.assertEqual(self.fv.geometry().top(), top)
        self.assertEqual(self.fv.width(), self.win.width())
        self.win.resize(1300, 900)
        self.app.processEvents()
        self.assertEqual((self.fv.width(), self.fv.geometry().bottom() + 1),
                         (self.win.width(), self.win.height()))


# --- the window --------------------------------------------------------------

@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestTheWindowAndTheFileView(_KeepsSettings):
    """The window is never shown here, so ``isVisible()`` is False for every
    child whatever the view was asked to do; ``isHidden()`` is the request."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app.main_window import MainWindow
        self.win = MainWindow()

    def tearDown(self):
        self.win.close()
        super().tearDown()

    def test_ctrl_o_is_the_file_view_and_open_pdf_is_the_dialog(self):
        from PySide6.QtGui import QKeySequence
        self.assertEqual(self.win.act_file_view.shortcut(), QKeySequence(QKeySequence.Open))
        self.assertTrue(self.win.act_open.shortcut().isEmpty())
        self.win.act_file_view.trigger()
        self.assertFalse(self.win.file_view.isHidden())

    def test_any_successful_open_takes_the_view_down(self):
        self.win.show_file_view()
        self.win.load_document(_touch(self.p("a.pdf")))
        self.assertTrue(self.win.file_view.isHidden())

    def test_a_failed_open_leaves_it_up(self):
        bad = self.p("bad.pdf")
        _touch(bad, pdf=False)
        self.win.show_file_view()
        with mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok):
            self.win.file_view.openRequested.emit(bad)
        self.assertIsNone(self.win.document)
        self.assertFalse(self.win.file_view.isHidden())

    def test_picking_the_open_drawing_just_goes_back_to_it(self):
        pdf = _touch(self.p("a.pdf"))
        self.win.load_document(pdf)
        self.win.show_file_view()
        with mock.patch.object(QMessageBox, "information",
                               side_effect=AssertionError("asked 'Already open'")):
            self.win.file_view.openRequested.emit(self.p("a.marked.pdf"))
        self.assertTrue(self.win.file_view.isHidden())

    def test_browse_is_the_file_dialog(self):
        pdf = _touch(self.p("browsed.pdf"))
        self.win.show_file_view()
        with mock.patch("app.main_window.QFileDialog.getOpenFileName",
                        return_value=(pdf, "PDF (*.pdf)")):
            self.win.file_view.btn_browse.click()
        self.assertEqual(self.win.document.path, pdf)
        self.assertTrue(self.win.file_view.isHidden())

    def test_open_recent_opens_the_file_the_file_view_would(self):
        # the menu and the File view read one list and must agree on a click
        pdf = _touch(self.p("dwg/foo.pdf"))
        _touch(self.p("dwg/foo.marked.pdf"))
        _touch(self.p("dwg/foo.markup.db"), pdf=False)
        self.cfg.add_recent_file(self.p("dwg/foo.marked.pdf"))
        self.win._rebuild_recent_menu()
        entry = next(a for a in self.win.m_recent.actions() if "foo" in a.text())
        entry.trigger()
        self.assertEqual(self.win.document.path, pdf)

    def test_settings_files_tab_writes_the_size(self):
        from app.settings_dialog import SettingsDialog
        d = SettingsDialog(self.cfg)
        d.recent_max.setValue(75)
        d.apply()
        self.assertEqual(self.cfg.recent_max, 75)


@unittest.skipUnless(_QT_OK, _QT_REASON)  # `main` imports PySide6 (main.py:9)
class TestWhereALaunchLands(unittest.TestCase):

    def _win(self):
        calls = []
        win = mock.Mock()
        win.load_document.side_effect = lambda p: calls.append(("open", p))
        win.show_file_view.side_effect = lambda: calls.append(("file view",))
        return win, calls

    def test_no_file_lands_on_the_file_view(self):
        from main import land
        win, calls = self._win()
        land(win, None)
        self.assertEqual(calls, [("file view",)])

    def test_a_file_opens_and_skips_it(self):
        from main import land
        win, calls = self._win()
        land(win, "/x/drawing.pdf")
        self.assertEqual(calls, [("open", "/x/drawing.pdf")])


if __name__ == "__main__":
    unittest.main()
