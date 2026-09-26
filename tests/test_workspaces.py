"""Workspaces: declared project folders, and their page in the File view.

The problem they answer: project drawings fell off the recent list after an
afternoon of unrelated PDFs. So each workspace keeps its own recent list, fed
by EVERY open of a file under its folder whatever route opened it, and a page
that lists everything under the folder.

Asserted where each rule acts:

* `app/model/workspaces.py` (no Qt) -- containment, the no-nesting rule and its
  message, ordering, favorites and hidden folders by relative path, the
  per-workspace recent list, New workspace…'s folders, and the scan: recursive,
  one row per drawing, hidden folders left out AND counted, unreadable folders
  reported rather than skipped.
* `AppConfig` -- add / create / relocate / remove, and which workspace is
  current. A refused New workspace… must leave no folder behind.
* the File view and the window -- the list, the page and its sections, the
  right-click menus, the Unavailable state, search reaching workspace files,
  the scan running off the UI thread, and opens being recorded.

`AppConfig` is the real per-user QSettings store, so every test that writes it
puts back exactly the keys it touched.
"""

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model import workspaces as W
from app.model.workspaces import Workspace, WorkspaceError
from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

if _QT_OK:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMainWindow
    from app.config import AppConfig, DEFAULT_QUICK_FOLDERS, WORKSPACE_RECENT_BOUNDS

_KEYS = ("recent/files", "recent/opened", "recent/pinned", "recent/max",
         "workspaces/list", "workspaces/selected", "workspaces/recent_max",
         "files/quick_folders")


def _touch(path, pdf=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if pdf:
        d = fitz.open()
        d.new_page(width=300, height=200)
        d.save(path)
        d.close()
    else:
        open(path, "wb").close()     # an empty file is a valid new SQLite sidecar
    return path


def _project(base):
    """A project folder with the shapes a scan has to get right."""
    root = os.path.join(base, "Project 2417")
    for rel in ("drawings/E-101.pdf", "drawings/E-102.pdf", "drawings/E-102.marked.pdf",
                "drawings/E-103.pdf", "drawings/E-103.marked.pdf",
                "documentation/manual.pdf", "documentation/vendor/vfd.pdf",
                "Superseded/E-101 rev A.pdf", ".cache/junk.pdf", "scope.pdf"):
        _touch(os.path.join(root, *rel.split("/")))
    _touch(os.path.join(root, "drawings", "E-103.markup.db"), pdf=False)
    _touch(os.path.join(root, "drawings", "notes.txt"), pdf=False)
    os.makedirs(os.path.join(root, "notes"))
    return root


# --- the rules, without Qt ---------------------------------------------------

class TestContainmentAndNesting(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.a = os.path.join(self.base, "A")
        self.b = os.path.join(self.base, "B")
        for d in (self.a, self.b, os.path.join(self.a, "sub")):
            os.makedirs(d, exist_ok=True)
        self.wa = Workspace(root=self.a)
        self.wb = Workspace(root=self.b, name="Plant B")

    def test_contains_and_relative(self):
        f = os.path.join(self.a, "sub", "x.pdf")
        self.assertTrue(W.contains(self.a, f))
        self.assertTrue(W.contains(self.a, self.a))
        self.assertFalse(W.contains(self.a, os.path.join(self.base, "A2", "x.pdf")))
        self.assertEqual(W.relative(self.a, f), "sub/x.pdf")
        self.assertEqual(W.absolute(self.a, "sub/x.pdf"), os.path.normpath(f))

    def test_nesting_is_refused_in_every_direction_and_named(self):
        inside = os.path.join(self.a, "sub")
        for root, word in ((inside, "inside"), (self.base, "contains"),
                           (self.a, "already")):
            with self.subTest(root=root):
                clash = W.overlap(root, [self.wa, self.wb])
                self.assertIsNotNone(clash)
                self.assertIn(word, W.nesting_message(root, clash))
                self.assertIn(clash.display_name, W.nesting_message(root, clash))
        self.assertIsNone(W.overlap(os.path.join(self.base, "C"), [self.wa, self.wb]))
        # Locate… into its own old path -- a project restructured one level
        # down -- must not collide with its own old self, and only with it
        inside = os.path.join(self.a, "sub")
        self.assertIsNotNone(W.overlap(inside, [self.wa]))
        self.assertIsNone(W.overlap(inside, [self.wa], ignore=self.a))
        self.assertIs(W.overlap(os.path.join(self.b, "x"), [self.wa, self.wb],
                                ignore=self.a), self.wb)

    def test_containing_picks_the_one_and_the_deepest_of_a_legacy_pair(self):
        f = os.path.join(self.a, "sub", "x.pdf")
        self.assertIs(W.containing([self.wa, self.wb], f), self.wa)
        self.assertIsNone(W.containing([self.wb], f))
        deep = Workspace(root=os.path.join(self.a, "sub"))
        self.assertIs(W.containing([self.wa, deep], f), deep)

    def test_order_is_pinned_then_last_used_and_never_used_last(self):
        never = Workspace(root="/n")
        old = Workspace(root="/o", last_used="2026-01-01T00:00:00")
        new = Workspace(root="/w", last_used="2026-09-01T00:00:00")
        pin = Workspace(root="/p", pinned=True, last_used="2025-01-01T00:00:00")
        self.assertEqual([w.root for w in W.ordered([never, old, new, pin])],
                         [pin.root, new.root, old.root, never.root])


class TestWhatAWorkspaceRemembers(unittest.TestCase):

    def test_favorites_and_hidden_folders_are_relative(self):
        ws = Workspace(root="/p")
        ws.set_favorite("drawings/E-101.pdf", True)
        ws.set_favorite("drawings/E-101.pdf", True)
        self.assertEqual(ws.favorites, ["drawings/E-101.pdf"])
        ws.set_hidden("Superseded", True)
        self.assertTrue(ws.is_hidden("Superseded"))
        self.assertTrue(ws.is_hidden("Superseded/2025"))      # below a hidden one
        self.assertFalse(ws.is_hidden("drawings"))
        ws.set_favorite("drawings/E-101.pdf", False)
        self.assertEqual(ws.favorites, [])

    def test_its_recent_list_is_one_row_per_drawing_and_capped(self):
        ws = Workspace(root="/p")
        ws.record_open("drawings/E-101.pdf", "2026-09-01T08:00:00", keep=3)
        ws.record_open("drawings/E-102.pdf", "2026-09-02T08:00:00", keep=3)
        ws.record_open("drawings/E-101.marked.pdf", "2026-09-03T08:00:00", keep=3)
        self.assertEqual([r for r, _t in ws.recent],
                         ["drawings/E-101.marked.pdf", "drawings/E-102.pdf"])
        self.assertEqual(ws.last_used, "2026-09-03T08:00:00")
        for i in range(5):
            ws.record_open(f"f{i}.pdf", f"2026-09-1{i}T08:00:00", keep=3)
        self.assertEqual(len(ws.recent), 3)
        ws.forget_recent("f4.pdf")
        self.assertEqual([r for r, _t in ws.recent], ["f3.pdf", "f2.pdf"])

    def test_a_stored_dict_with_junk_still_reads(self):
        ws = Workspace.from_dict({"root": "/p", "recent": [["a.pdf", "t"], "junk", [1]],
                                  "surprise": 1})
        self.assertEqual(ws.recent, [["a.pdf", "t"]])


class TestNewWorkspaceFolders(unittest.TestCase):

    def test_creates_the_folder_and_its_quick_subfolders(self):
        parent = tempfile.mkdtemp()
        root = W.create_workspace(parent, "Job 88", ["drawings", "documentation", "notes"])
        self.assertEqual(sorted(os.listdir(root)), ["documentation", "drawings", "notes"])

    def test_refuses_an_existing_folder_and_a_bad_name(self):
        parent = tempfile.mkdtemp()
        os.makedirs(os.path.join(parent, "taken"))
        for name in ("taken", "", "a/b", "c:d", ".."):
            with self.subTest(name=name):
                with self.assertRaises(WorkspaceError):
                    W.create_workspace(parent, name, ["drawings"])


class TestScan(unittest.TestCase):

    def setUp(self):
        self.root = _project(tempfile.mkdtemp())
        self.ws = Workspace(root=self.root, hidden=["Superseded"])

    def _rels(self, result):
        return [f.rel for f in result.files]

    def test_recursive_one_row_per_drawing_hidden_left_out_and_counted(self):
        r = W.scan(self.ws)
        self.assertEqual(self._rels(r), [
            "scope.pdf",
            "documentation/manual.pdf",
            "documentation/vendor/vfd.pdf",
            "drawings/E-101.pdf",
            "drawings/E-102.marked.pdf",   # no sidecar: the marked copy has the marks
            "drawings/E-103.pdf",          # sidecar present: the original shows them
        ])
        self.assertEqual(r.folders, 4)
        self.assertEqual(r.hidden_skipped, 1)
        self.assertNotIn(".cache/junk.pdf", self._rels(r))
        self.assertEqual(r.summary(), "6 PDFs in 4 folders · 1 hidden folder not shown")

    def test_show_hidden_lists_them_marked(self):
        r = W.scan(self.ws, show_hidden=True)
        hidden = [f for f in r.files if f.hidden]
        self.assertEqual([f.rel for f in hidden], ["Superseded/E-101 rev A.pdf"])
        self.assertEqual(r.hidden_skipped, 0)

    def test_modified_is_the_newest_of_a_drawings_files(self):
        pdf = os.path.join(self.root, "drawings", "E-102.pdf")
        marked = os.path.join(self.root, "drawings", "E-102.marked.pdf")
        os.utime(pdf, (1_000_000_000, 1_000_000_000))
        os.utime(marked, (1_500_000_000, 1_500_000_000))
        row = next(f for f in W.scan(self.ws).files if f.rel.startswith("drawings/E-102"))
        self.assertEqual(row.modified, 1_500_000_000)
        os.utime(pdf, (1_900_000_000, 1_900_000_000))
        row = next(f for f in W.scan(self.ws).files if f.rel.startswith("drawings/E-102"))
        self.assertEqual(row.modified, 1_900_000_000)

    def test_a_folder_that_cannot_be_read_is_reported_not_skipped(self):
        real = os.scandir
        bad = os.path.join(self.root, "documentation")

        def scandir(path="."):
            if os.path.normpath(path) == os.path.normpath(bad):
                raise PermissionError(13, "denied", path)
            return real(path)

        with mock.patch("os.scandir", scandir):
            r = W.scan(self.ws)
        self.assertEqual(r.unreadable, ["documentation"])
        self.assertIn("1 folder could not be read", r.summary())

    def test_cancel(self):
        self.assertTrue(W.scan(self.ws, cancel=lambda: True).canceled)


# --- the stored list ---------------------------------------------------------

@unittest.skipUnless(_QT_OK, _QT_REASON)
class _KeepsSettings(unittest.TestCase):

    def setUp(self):
        self.cfg = AppConfig()
        self._saved = {k: self.cfg.s.value(k) for k in _KEYS}
        for k in _KEYS:
            self.cfg.s.remove(k)
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                self.cfg.s.remove(k)
            else:
                self.cfg.s.setValue(k, v)
        self.cfg.sync()


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestWorkspaceStore(_KeepsSettings):

    def test_add_refuses_a_missing_folder_and_a_nested_one(self):
        with self.assertRaises(WorkspaceError):
            self.cfg.add_workspace(os.path.join(self.base, "nope"))
        root = _project(self.base)
        self.cfg.add_workspace(root)
        with self.assertRaises(WorkspaceError) as ctx:
            self.cfg.add_workspace(os.path.join(root, "drawings"))
        self.assertIn("Project 2417", str(ctx.exception))
        self.assertEqual(len(self.cfg.workspaces()), 1)

    def test_a_refused_new_workspace_leaves_no_folder_behind(self):
        root = _project(self.base)
        self.cfg.add_workspace(root)
        with self.assertRaises(WorkspaceError):
            self.cfg.create_workspace(root, "Inner")
        self.assertFalse(os.path.exists(os.path.join(root, "Inner")))

    def test_new_workspace_uses_the_quick_folders_setting(self):
        self.assertEqual(self.cfg.quick_folders(), list(DEFAULT_QUICK_FOLDERS))
        self.cfg.set_quick_folders([" drawings ", "RFIs", "rfis", "", "specs/"])
        self.assertEqual(self.cfg.quick_folders(), ["drawings", "RFIs", "specs"])
        ws = self.cfg.create_workspace(self.base, "Job 88")
        self.assertEqual(sorted(os.listdir(ws.root)), ["RFIs", "drawings", "specs"])
        self.assertIsNotNone(self.cfg.find_workspace(ws.root))

    def test_locate_keeps_what_it_remembers_and_the_selection(self):
        root = _project(self.base)
        ws = self.cfg.add_workspace(root)
        ws.set_favorite("drawings/E-101.pdf", True)
        ws.set_hidden("Superseded", True)
        self.cfg.update_workspace(ws)
        self.cfg.select_workspace(root)
        moved = os.path.join(self.base, "moved")
        os.rename(root, moved)
        self.assertFalse(self.cfg.find_workspace(root).available)
        ws = self.cfg.relocate_workspace(root, moved)
        self.assertEqual((ws.favorites, ws.hidden), (["drawings/E-101.pdf"], ["Superseded"]))
        self.assertEqual(self.cfg.selected_workspace_root, os.path.normpath(moved))
        self.assertIsNone(self.cfg.find_workspace(root))

    def test_locate_into_its_own_old_folder(self):
        root = _project(self.base)
        self.cfg.add_workspace(root)
        ws = self.cfg.relocate_workspace(root, os.path.join(root, "drawings"))
        self.assertEqual(ws.root, os.path.normpath(os.path.join(root, "drawings")))

    def test_remove_never_touches_the_folder(self):
        root = _project(self.base)
        self.cfg.add_workspace(root)
        self.cfg.select_workspace(root)
        self.cfg.remove_workspace(root)
        self.assertEqual(self.cfg.workspaces(), [])
        self.assertEqual(self.cfg.selected_workspace_root, "")
        self.assertTrue(os.path.isfile(os.path.join(root, "drawings", "E-101.pdf")))

    def test_current_is_the_open_files_workspace_else_the_selected_one(self):
        a = _project(os.path.join(self.base, "a"))
        b = _project(os.path.join(self.base, "b"))
        self.cfg.add_workspace(a)
        self.cfg.add_workspace(b)
        self.assertIsNone(self.cfg.current_workspace(None))
        self.cfg.select_workspace(a)
        self.assertEqual(self.cfg.current_workspace(None).root, os.path.normpath(a))
        in_b = os.path.join(b, "drawings", "E-101.pdf")
        self.assertEqual(self.cfg.current_workspace(in_b).root, os.path.normpath(b))
        outside = _touch(os.path.join(self.base, "loose.pdf"))
        self.assertEqual(self.cfg.current_workspace(outside).root, os.path.normpath(a))

    def test_the_per_workspace_list_size_is_bounded(self):
        lo, hi = WORKSPACE_RECENT_BOUNDS
        for stored, read in ((1, lo), (9999, hi), (25, 25)):
            with self.subTest(stored=stored):
                self.cfg.set("workspaces/recent_max", stored)
                self.assertEqual(self.cfg.workspace_recent_max, read)


# --- the page ----------------------------------------------------------------

@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestWorkspacePages(_KeepsSettings):

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
        self.opened, self.warned = [], []
        self.fv.openRequested.connect(self.opened.append)
        self.fv.warn = lambda title, text: self.warned.append(text)
        self.fv.confirm = lambda title, text: True
        self.root = _project(self.base)

    def tearDown(self):
        self.fv.stop_scans()
        self.win.close()
        super().tearDown()

    def _labels(self, item):
        return [a.text() for a in self.fv._context_menu_for(item).actions()
                if not a.isSeparator()]

    def _act(self, item, label):
        next(a for a in self.fv._context_menu_for(item).actions()
             if a.text() == label).trigger()

    def _page(self):
        self.fv.show_workspace(self.root)
        self.assertTrue(self.fv.wait_for_scans())
        return self.fv

    def _row(self, name):
        for it in self.fv.workspace_file_rows():
            if it.text(0).startswith(name):
                return it
        raise AssertionError(f"no {name!r} in "
                             f"{[i.text(0) for i in self.fv.workspace_file_rows()]}")

    def _folder(self, name):
        found = self.fv.ws_files.findItems(name, Qt.MatchRecursive | Qt.MatchStartsWith)
        return next(i for i in found if i.data(0, Qt.UserRole + 4) == "folder")

    def test_opens_on_the_current_workspace_else_recent(self):
        self.fv.open_page()
        self.assertEqual(self.fv.page(), "recent")
        self.cfg.add_workspace(self.root)
        self.cfg.select_workspace(self.root)
        self.fv.open_page()
        self.assertEqual(self.fv.page(), "workspace")
        self.assertEqual(self.fv.ws_title.text(), "Project 2417")

    def test_the_list_pins_first_and_names_an_unavailable_folder(self):
        gone = os.path.join(self.base, "Gone")
        os.makedirs(gone)
        for root, used in ((self.root, "2026-09-01T08:00:00"), (gone, "2026-09-20T08:00:00")):
            ws = self.cfg.add_workspace(root)
            ws.last_used = used
            self.cfg.update_workspace(ws)
        os.rmdir(gone)
        self.fv.show_workspaces()
        rows = self.fv.workspace_rows()
        # last used first; a folder that is gone stays listed, and says so
        self.assertEqual([r.text(0) for r in rows], ["Gone   (unavailable)", "Project 2417"])
        self._act(rows[1], "Pin")
        self.assertEqual(self.fv.groups(self.fv.ws_tree), ["Pinned", "Workspaces"])
        self.assertEqual(self._labels(self.fv.workspace_rows()[0]),
                         ["Open", "Unpin", "Rename…", "Locate…", "Remove from list"])

    def test_click_rename_and_remove(self):
        self.cfg.add_workspace(self.root)
        self.fv.show_workspaces()
        row = self.fv.workspace_rows()[0]
        self.fv.ask_text = lambda *a, **k: ("Plant 2417 upgrade", True)
        self._act(row, "Rename…")
        self.assertEqual(self.cfg.find_workspace(self.root).display_name, "Plant 2417 upgrade")
        self.fv.ask_text = lambda *a, **k: ("Project 2417", True)     # the folder's own name
        self._act(self.fv.workspace_rows()[0], "Rename…")
        self.assertEqual(self.cfg.find_workspace(self.root).name, "")
        self.fv._on_clicked(self.fv.workspace_rows()[0])
        self.assertEqual(self.fv.page(), "workspace")
        self.assertEqual(self.cfg.selected_workspace_root, os.path.normpath(self.root))
        self.fv.show_workspaces()
        self.fv.confirm = lambda title, text: False          # asked, and No keeps it
        self._act(self.fv.workspace_rows()[0], "Remove from list")
        self.assertEqual(len(self.cfg.workspaces()), 1)
        self.fv.confirm = lambda title, text: True
        self._act(self.fv.workspace_rows()[0], "Remove from list")
        self.assertEqual(self.cfg.workspaces(), [])
        self.assertTrue(os.path.isdir(self.root))

    def test_add_and_new_through_the_buttons(self):
        self.fv.ask_folder = lambda title: self.root
        self.fv.btn_add_ws.click()
        self.assertEqual(self.fv.page(), "workspace")
        self.fv.ask_folder = lambda title: os.path.join(self.root, "drawings")
        self.fv.btn_add_ws.click()
        self.assertEqual(len(self.warned), 1)
        self.assertIn("Project 2417", self.warned[0])
        self.fv.ask_folder = lambda title: self.base
        self.fv.ask_text = lambda *a, **k: ("Job 88", True)
        self.fv.btn_new_ws.click()
        self.assertEqual(self.fv.ws_title.text(), "Job 88")
        self.assertEqual(sorted(os.listdir(os.path.join(self.base, "Job 88"))),
                         sorted(self.cfg.quick_folders()))

    def test_the_page_sections_counts_and_hidden_folders(self):
        ws = self.cfg.add_workspace(self.root)
        ws.set_hidden("Superseded", True)
        ws.set_favorite("drawings/E-101.pdf", True)
        ws.record_open("drawings/E-101.pdf", "2026-09-26T08:00:00", keep=25)
        ws.record_open("documentation/manual.pdf", "2026-09-26T09:00:00", keep=25)
        self.cfg.update_workspace(ws)
        fv = self._page()
        self.assertEqual(fv.groups(fv.ws_files),
                         ["Favorites", "Recent in this workspace", "All files"])
        favorites = fv.ws_files.topLevelItem(0)
        recent = fv.ws_files.topLevelItem(1)
        self.assertEqual([favorites.child(i).text(0) for i in range(favorites.childCount())],
                         ["E-101.pdf"])
        # a favorite is not repeated under recent
        self.assertEqual([recent.child(i).text(0) for i in range(recent.childCount())],
                         ["manual.pdf"])
        self.assertEqual(fv.ws_count.text(), "6 PDFs in 4 folders · 1 hidden folder not shown")
        self.assertEqual(self._folder("documentation").text(1), "2 PDFs")
        self.assertFalse(any(i.text(0).startswith("E-101 rev A")
                             for i in fv.workspace_file_rows()))
        fv.show_hidden.setChecked(True)
        self.assertTrue(fv.wait_for_scans())
        self.assertIn("(hidden)", self._folder("Superseded").text(0))
        self.assertTrue(any(i.text(0).startswith("E-101 rev A")
                            for i in fv.workspace_file_rows()))

    def test_file_menu_favorite_and_forget(self):
        ws = self.cfg.add_workspace(self.root)
        ws.record_open("scope.pdf", "2026-09-26T08:00:00", keep=25)
        self.cfg.update_workspace(ws)
        fv = self._page()
        all_scope = [i for i in fv.workspace_file_rows()
                     if i.text(0) == "scope.pdf" and i.parent().text(0) == "All files"][0]
        self.assertEqual(self._labels(all_scope),
                         ["Open", "Pin", "Favorite", "Show in folder", "Copy path"])
        recent_scope = fv.ws_files.topLevelItem(0).child(0)
        self.assertIn("Remove from this list", self._labels(recent_scope))
        self._act(recent_scope, "Remove from this list")
        self.assertEqual(self.cfg.find_workspace(self.root).recent, [])
        self._act(self._row("E-101"), "Favorite")
        self.assertEqual(self.cfg.find_workspace(self.root).favorites, ["drawings/E-101.pdf"])
        self.assertEqual(fv.groups(fv.ws_files), ["Favorites", "All files"])
        fv._on_clicked(self._row("E-102"))
        self.assertEqual(self.opened, [os.path.join(self.root, "drawings", "E-102.marked.pdf")])

    def test_hide_a_folder_from_its_menu_and_bring_it_back(self):
        self.cfg.add_workspace(self.root)
        fv = self._page()
        self.assertEqual(self._labels(self._folder("documentation")),
                         ["Hide from workspace", "Show in folder", "Copy path"])
        self._act(self._folder("documentation"), "Hide from workspace")
        self.assertTrue(fv.wait_for_scans())
        self.assertEqual(self.cfg.find_workspace(self.root).hidden, ["documentation"])
        self.assertFalse(any(i.text(0) == "manual.pdf" for i in fv.workspace_file_rows()))
        fv.show_hidden.setChecked(True)
        self.assertTrue(fv.wait_for_scans())
        self._act(self._folder("documentation"), "Show in workspace")
        self.assertTrue(fv.wait_for_scans())
        self.assertEqual(self.cfg.find_workspace(self.root).hidden, [])

    def test_filter_reaches_every_section_and_opens_folders(self):
        ws = self.cfg.add_workspace(self.root)
        ws.set_favorite("scope.pdf", True)
        self.cfg.update_workspace(ws)
        fv = self._page()
        fv.ws_filter.setText("vfd")
        self.assertEqual([i.text(0) for i in fv.workspace_file_rows()], ["vfd.pdf"])
        self.assertTrue(self._folder("documentation").isExpanded())
        fv._on_escape()
        self.assertEqual(fv.ws_filter.text(), "")

    def test_an_unavailable_workspace_offers_locate(self):
        ws = self.cfg.add_workspace(self.root)
        ws.set_favorite("scope.pdf", True)
        self.cfg.update_workspace(ws)
        moved = os.path.join(self.base, "moved")
        os.rename(self.root, moved)
        self.fv.show_workspace(self.root)
        self.assertTrue(self.fv.ws_body.isHidden())
        self.assertFalse(self.fv.ws_missing.isHidden())
        self.assertIn(os.path.normpath(self.root), self.fv.ws_missing_text.text())
        self.fv.ask_folder = lambda title: moved
        self.fv.btn_locate.click()
        self.assertTrue(self.fv.wait_for_scans())
        self.assertFalse(self.fv.ws_body.isHidden())
        self.assertEqual(self.fv.ws_files.topLevelItem(0).child(0).text(0), "scope.pdf")

    def test_recent_search_reaches_workspace_files(self):
        ws = self.cfg.add_workspace(self.root)
        ws.set_hidden("Superseded", True)
        self.cfg.update_workspace(ws)
        self.cfg.add_recent_file(os.path.join(self.root, "drawings", "E-103.pdf"))
        self.fv.show_recent()
        self.fv.search.setText("E-10")
        self.assertTrue(self.fv.wait_for_scans())
        self.assertEqual(self.fv.groups(), ["Recent", "Project 2417"])
        head = self.fv.tree.topLevelItem(1)
        hits = [head.child(i).text(0) for i in range(head.childCount())]
        # listed once (E-103 is already under Recent), hidden folders left out
        self.assertEqual(hits, ["E-101.pdf", "E-102.marked.pdf"])

    def test_the_scan_runs_off_the_ui_thread(self):
        self.cfg.add_workspace(self.root)
        threads = []
        real = W.scan

        def spy(*a, **k):
            threads.append(threading.get_ident())
            return real(*a, **k)

        with mock.patch.object(W, "scan", spy):
            self._page()
        self.assertTrue(threads)
        self.assertNotIn(threading.get_ident(), threads)


# --- the window --------------------------------------------------------------

@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestTheWindowRecordsWorkspaceOpens(_KeepsSettings):
    """Never shown, so ``isHidden()`` is the request (see test_file_view)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app.main_window import MainWindow
        self.win = MainWindow()
        self.a = _project(os.path.join(self.base, "a"))
        self.b = _project(os.path.join(self.base, "b"))
        self.cfg.add_workspace(self.a)
        self.cfg.add_workspace(self.b)

    def tearDown(self):
        self.win.close()
        super().tearDown()

    def test_any_open_under_a_workspace_lands_on_its_recent_list(self):
        self.win.load_document(os.path.join(self.a, "documentation", "manual.pdf"))
        loose = _touch(os.path.join(self.base, "loose.pdf"))
        self.win.load_document(loose)
        ws = self.win.config.find_workspace(self.a)
        self.assertEqual([r for r, _t in ws.recent], ["documentation/manual.pdf"])
        self.assertTrue(ws.last_used)
        self.assertEqual(self.win.config.find_workspace(self.b).recent, [])

    def test_the_file_view_lands_on_the_open_files_workspace(self):
        self.win.config.select_workspace(self.a)
        self.win.load_document(os.path.join(self.b, "scope.pdf"))
        self.win.show_file_view()
        self.win.file_view.wait_for_scans()
        self.assertEqual(self.win.file_view.page(), "workspace")
        self.assertEqual(self.win.file_view.ws_path.text(), os.path.normpath(self.b))

    def test_closing_the_window_stops_the_scans(self):
        with mock.patch.object(self.win.file_view, "stop_scans") as stop:
            self.win.close()
        stop.assert_called_once()

    def test_settings_write_the_workspace_options(self):
        from app.settings_dialog import SettingsDialog
        d = SettingsDialog(self.cfg)
        d.ws_recent_max.setValue(40)
        d.quick_folders.setText("drawings, RFIs")
        d.apply()
        self.assertEqual(self.cfg.workspace_recent_max, 40)
        self.assertEqual(self.cfg.quick_folders(), ["drawings", "RFIs"])


if __name__ == "__main__":
    unittest.main()
