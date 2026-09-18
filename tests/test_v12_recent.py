"""File ▸ Open Recent — the last N opened PDFs, remembered between sessions."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

# `app.config` reaches PySide6 (QSettings), so this import is what made the
# module ERROR -- the direct PySide6 probe that used to sit below it never
# got the chance to run.
if _QT_OK:
    from app.config import AppConfig, MAX_RECENT_FILES
    from PySide6.QtWidgets import QApplication


def _make_pdf(dirpath, name):
    p = os.path.join(dirpath, name)
    d = fitz.open(); d.new_page(width=300, height=200); d.save(p); d.close()
    return p


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestRecentConfig(unittest.TestCase):
    """The stored list itself (no GUI) -- but AppConfig is built on QSettings,
    so it cannot be constructed at all without Qt. Skipping is the honest
    answer; erroring was not."""

    def setUp(self):
        self.cfg = AppConfig()
        self.cfg.clear_recent_files()

    def tearDown(self):
        self.cfg.clear_recent_files()

    def test_starts_empty(self):
        self.assertEqual(self.cfg.recent_files, [])

    def test_most_recent_first(self):
        self.cfg.add_recent_file("/tmp/a.pdf")
        self.cfg.add_recent_file("/tmp/b.pdf")
        self.assertEqual([os.path.basename(p) for p in self.cfg.recent_files],
                         ["b.pdf", "a.pdf"])

    def test_capped_at_max(self):
        for i in range(MAX_RECENT_FILES + 5):
            self.cfg.add_recent_file(f"/tmp/f{i}.pdf")
        rec = self.cfg.recent_files
        self.assertEqual(len(rec), MAX_RECENT_FILES)
        self.assertIn(f"f{MAX_RECENT_FILES + 4}.pdf", rec[0])   # newest kept
        self.assertTrue(all("f0.pdf" not in p for p in rec))    # oldest dropped

    def test_reopening_moves_to_top_without_duplicating(self):
        for n in ("a", "b", "c"):
            self.cfg.add_recent_file(f"/tmp/{n}.pdf")
        self.cfg.add_recent_file("/tmp/a.pdf")
        rec = self.cfg.recent_files
        self.assertEqual(len(rec), 3)
        self.assertIn("a.pdf", rec[0])

    def test_dedupes_case_insensitively_and_stores_absolute(self):
        self.cfg.add_recent_file("/tmp/Case.pdf")
        self.cfg.add_recent_file(os.path.normcase("/tmp/Case.pdf"))
        self.assertEqual(len(self.cfg.recent_files), 1)
        self.assertTrue(os.path.isabs(self.cfg.recent_files[0]))

    def test_persists_across_config_instances(self):
        # a new AppConfig (i.e. the next session) sees the same list
        self.cfg.add_recent_file("/tmp/kept.pdf")
        self.assertIn("kept.pdf", AppConfig().recent_files[0])

    def test_clear(self):
        self.cfg.add_recent_file("/tmp/a.pdf")
        self.cfg.clear_recent_files()
        self.assertEqual(self.cfg.recent_files, [])

    def test_survives_corrupt_stored_value(self):
        self.cfg.set("recent/files", "{not json")
        self.assertEqual(self.cfg.recent_files, [])


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestRecentMenu(unittest.TestCase):
    """The File ▸ Open Recent menu."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        cfg = AppConfig()
        cfg.s.remove("ui/window_state")
        cfg.s.remove("ui/geometry")
        cfg.clear_recent_files()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        AppConfig().clear_recent_files()

    def _win(self):
        from app.main_window import MainWindow
        return MainWindow()

    def _entries(self, win):
        return [a for a in win.m_recent.actions()
                if a.text() and not a.text().startswith("Clear") and not a.isSeparator()]

    def test_empty_menu_shows_placeholder(self):
        win = self._win()
        acts = win.m_recent.actions()
        self.assertEqual(len(acts), 1)
        self.assertFalse(acts[0].isEnabled())

    def test_opening_records_and_lists_the_file(self):
        win = self._win()
        p = _make_pdf(self.tmp, "drawing.pdf")
        win.load_document(p)
        self.assertIn("drawing.pdf", win.config.recent_files[0])
        self.assertIn("drawing.pdf", self._entries(win)[0].text())

    def test_menu_is_ordered_most_recent_first(self):
        win = self._win()
        for n in ("one.pdf", "two.pdf"):
            win.load_document(_make_pdf(self.tmp, n))
        labels = [a.text() for a in self._entries(win)]
        self.assertIn("two.pdf", labels[0])
        self.assertIn("one.pdf", labels[1])

    def test_failed_open_is_not_recorded(self):
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        win = self._win()
        bad = os.path.join(self.tmp, "bad.pdf")
        with open(bad, "wb") as fh:
            fh.write(b"not a pdf")
        with mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok):
            win.load_document(bad)
        self.assertEqual(win.config.recent_files, [])

    def test_missing_file_is_listed_but_disabled(self):
        # Seed the recents list directly instead of open-then-delete: several
        # components legitimately hold an opened PDF (the Document, the PDF
        # Tools thumbnail grid), and Windows refuses to unlink a file any of
        # them still has open. The menu only checks os.path.exists, so a path
        # that was never created exercises exactly the same behavior on every
        # platform: the entry stays listed, grayed out as "(not found)".
        win = self._win()
        p = os.path.join(self.tmp, "gone.pdf")     # never created
        win.config.add_recent_file(p)
        win._rebuild_recent_menu()
        act = self._entries(win)[0]
        self.assertFalse(act.isEnabled())
        self.assertIn("not found", act.text())
        self.assertIn("gone.pdf", act.text())      # still identifiable

    def test_entry_opens_the_document(self):
        win = self._win()
        first = _make_pdf(self.tmp, "first.pdf")
        second = _make_pdf(self.tmp, "second.pdf")
        win.load_document(first)
        win.load_document(second)
        self.assertIn("second.pdf", win.document.path)
        # click the entry for the first file
        act = next(a for a in self._entries(win) if "first.pdf" in a.text())
        act.trigger()
        self.assertIn("first.pdf", win.document.path)

    def test_clear_list_empties_the_menu(self):
        win = self._win()
        win.load_document(_make_pdf(self.tmp, "x.pdf"))
        win._clear_recent_files()
        self.assertEqual(win.config.recent_files, [])
        acts = win.m_recent.actions()
        self.assertEqual(len(acts), 1)
        self.assertFalse(acts[0].isEnabled())


if __name__ == "__main__":
    unittest.main()
