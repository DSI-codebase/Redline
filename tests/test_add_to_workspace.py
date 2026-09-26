"""Add to workspace: a drawing copied into a workspace folder, all of it, over
nothing, and the window working on the copy afterward.

Asserted where each rule acts:

* `app/model/drawing_copy.py` (no Qt) -- the PDF, the marked copy and the
  sidecar travel together; the marks really arrive (a `Document` opened on the
  copy has them); a clash keeps both under one renamed stem and leaves what
  was there byte-for-byte; a byte-identical file is recognized; a file that
  appears mid-copy fails the copy instead of being overwritten; a failure
  removes only what the copy created; every PDF destination is put to the
  storage refusals.
* `app/model/workspaces.py` -- where a file can go: quick folders first, then
  the other top-level folders, never hidden ones.
* `app/add_to_workspace.py` and the window -- the menu in each state, Save
  before copying, keep both / cancel, open the identical one, New folder…, the
  switch to the copy, and the same menu on a File view Recent row.

`AppConfig` is the real per-user QSettings store, so every test that writes it
puts back exactly the keys it touched.
"""

import hashlib
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model import drawing_copy as C
from app.model import workspaces as W
from app.model.annotations import Annotation, KIND_RECT
from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

if _QT_OK:
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
    from app.config import AppConfig

_KEYS = ("recent/files", "recent/opened", "recent/pinned", "recent/max",
         "workspaces/list", "workspaces/selected", "workspaces/recent_max",
         "files/quick_folders")


def _pdf(path, text="E-101"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d = fitz.open()
    d.new_page(width=300, height=200).insert_text((40, 40), text)
    d.save(path)
    d.close()
    return path


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _marked_drawing(folder, stem="E-101", marks=2):
    """A drawing with marks saved the way the app saves them: the PDF, a
    `.marked.pdf` and a sidecar holding the marks."""
    from app.model.document import Document
    src = _pdf(os.path.join(folder, stem + ".pdf"), stem)
    doc = Document(src)
    doc.load()
    for i in range(marks):
        doc.store.add(Annotation(page=0, kind=KIND_RECT, rect=(10 + i, 10, 60, 40),
                                 text=f"mark {i}"))
    doc.save()
    doc.close()
    return src


def _marks_in(pdf_path):
    from app.model.document import Document
    doc = Document(pdf_path)
    doc.load()
    try:
        return sorted(a.text for a in doc.store.all())
    finally:
        doc.close()


# --- the copy, without Qt ----------------------------------------------------

class TestTheCopy(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.base, "Downloads")
        self.dest = os.path.join(self.base, "Project", "drawings")

    def test_all_three_files_travel_and_the_marks_arrive(self):
        src = _marked_drawing(self.src_dir)
        plan = C.plan_copy(src, self.dest)
        self.assertEqual(sorted(plan.sources), ["db", "marked", "pdf"])
        self.assertFalse(plan.clash)
        written = C.copy_drawing(plan)
        self.assertEqual(sorted(os.path.basename(p) for p in written.values()),
                         ["E-101.marked.pdf", "E-101.markup.db", "E-101.pdf"])
        for kind in ("pdf", "marked"):
            self.assertEqual(_sha(plan.sources[kind]), _sha(written[kind]))
        self.assertEqual(plan.open_path, os.path.join(self.dest, "E-101.pdf"))
        self.assertEqual(_marks_in(plan.open_path), ["mark 0", "mark 1"])

    def test_starting_from_the_marked_copy_plans_the_same_set(self):
        src = _marked_drawing(self.src_dir)
        marked = os.path.join(self.src_dir, "E-101.marked.pdf")
        self.assertEqual(C.plan_copy(marked, self.dest).sources,
                         C.plan_copy(src, self.dest).sources)

    def test_a_clash_keeps_both_and_leaves_what_was_there(self):
        src = _marked_drawing(self.src_dir)
        there = _pdf(os.path.join(self.dest, "E-101.pdf"), "a different E-101")
        before = _sha(there)
        plan = C.plan_copy(src, self.dest)
        self.assertEqual((plan.stem, plan.clash, plan.identical), ("E-101 (2)", True, ""))
        C.copy_drawing(plan)
        self.assertEqual(_sha(there), before)
        self.assertEqual(sorted(n for n in os.listdir(self.dest) if "(2)" in n),
                         ["E-101 (2).marked.pdf", "E-101 (2).markup.db", "E-101 (2).pdf"])
        # the renamed set still finds its own sidecar
        self.assertEqual(_marks_in(plan.open_path), ["mark 0", "mark 1"])

    def test_the_next_free_stem_and_a_stem_taken_by_a_sidecar_alone(self):
        src = _pdf(os.path.join(self.src_dir, "E-101.pdf"))
        _pdf(os.path.join(self.dest, "E-101.pdf"), "other")
        _pdf(os.path.join(self.dest, "E-101 (2).pdf"), "other 2")
        self.assertEqual(C.plan_copy(src, self.dest).stem, "E-101 (3)")
        lone = os.path.join(self.base, "B")
        os.makedirs(lone)
        open(os.path.join(lone, "E-101.markup.db"), "wb").close()
        plan = C.plan_copy(src, lone)
        self.assertEqual((plan.stem, plan.identical), ("E-101 (2)", ""))

    def test_a_byte_identical_file_is_already_there(self):
        src = _pdf(os.path.join(self.src_dir, "E-101.pdf"))
        os.makedirs(self.dest)
        with open(src, "rb") as a, open(os.path.join(self.dest, "E-101.pdf"), "wb") as b:
            b.write(a.read())
        plan = C.plan_copy(src, self.dest)
        self.assertEqual(plan.identical, os.path.join(self.dest, "E-101.pdf"))

    def test_a_file_that_appears_mid_copy_is_not_overwritten(self):
        src = _marked_drawing(self.src_dir)
        plan = C.plan_copy(src, self.dest)
        os.makedirs(self.dest)
        squatter = os.path.join(self.dest, "E-101.marked.pdf")
        with open(squatter, "wb") as fh:
            fh.write(b"not yours")
        with self.assertRaises(C.CopyError):
            C.copy_drawing(plan)
        with open(squatter, "rb") as fh:
            self.assertEqual(fh.read(), b"not yours")
        # the PDF it had already written is taken back
        self.assertEqual(os.listdir(self.dest), ["E-101.marked.pdf"])

    def test_a_failure_removes_only_what_the_copy_made(self):
        src = _marked_drawing(self.src_dir)
        plan = C.plan_copy(src, self.dest)
        with mock.patch.object(C, "_backup", side_effect=sqlite3.OperationalError("disk")):
            with self.assertRaises(sqlite3.OperationalError):
                C.copy_drawing(plan)
        self.assertEqual(os.listdir(self.dest), [])
        self.assertEqual(sorted(os.listdir(self.src_dir)),
                         ["E-101.marked.pdf", "E-101.markup.db", "E-101.pdf"])

    def test_every_pdf_destination_is_put_to_the_refusals(self):
        src = _marked_drawing(self.src_dir)
        plan = C.plan_copy(src, self.dest)
        with mock.patch.object(C, "refuse_protected") as protected, \
                mock.patch.object(C, "refuse_overwriting_input") as inputs:
            C.copy_drawing(plan)
        self.assertEqual(sorted(os.path.basename(c.args[0]) for c in protected.call_args_list),
                         ["E-101.marked.pdf", "E-101.pdf"])
        self.assertEqual(len(inputs.call_args_list), 3)

    def test_a_refusal_stops_the_copy(self):
        from app.model.storage import ProtectedPathError
        src = _pdf(os.path.join(self.src_dir, "E-101.pdf"))
        plan = C.plan_copy(src, self.dest)
        with mock.patch.object(C, "refuse_protected", side_effect=ProtectedPathError("no")):
            with self.assertRaises(ProtectedPathError):
                C.copy_drawing(plan)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "E-101.pdf")))

    def test_a_missing_drawing_is_refused(self):
        with self.assertRaises(C.CopyError):
            C.plan_copy(os.path.join(self.src_dir, "gone.pdf"), self.dest)


class TestWhereAFileCanGo(unittest.TestCase):

    def test_quick_first_then_the_rest_never_hidden(self):
        root = tempfile.mkdtemp()
        for d in ("Drawings", "RFIs", "Superseded", ".git", "archive"):
            os.makedirs(os.path.join(root, d))
        ws = W.Workspace(root=root, hidden=["Superseded"])
        quick, others = W.destinations(ws, ["drawings", "documentation", "notes"])
        self.assertEqual(quick, ["drawings", "documentation", "notes"])
        expected = ["archive", "RFIs"]
        if os.path.normcase("A") != os.path.normcase("a"):    # a case-sensitive disk
            expected = ["archive", "Drawings", "RFIs"]
        self.assertEqual(others, expected)

    def test_folder_names(self):
        self.assertEqual(W.check_folder_name("  RFIs "), "RFIs")
        for bad in ("", "a/b", "c:d", "..", "why?"):
            with self.subTest(bad=bad):
                with self.assertRaises(W.WorkspaceError):
                    W.check_folder_name(bad)


# --- the menu and the flow ---------------------------------------------------

@unittest.skipUnless(_QT_OK, _QT_REASON)
class _Window(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.cfg = AppConfig()
        self._saved = {k: self.cfg.s.value(k) for k in _KEYS}
        for k in _KEYS:
            self.cfg.s.remove(k)
        from app.main_window import MainWindow
        self.win = MainWindow()
        self.base = tempfile.mkdtemp()
        self.a = os.path.join(self.base, "Project A")
        self.b = os.path.join(self.base, "Plant B")
        for d in (os.path.join(self.a, "drawings"), os.path.join(self.a, "RFIs"),
                  os.path.join(self.b, "drawings")):
            os.makedirs(d)
        self.cfg.add_workspace(self.a)
        self.cfg.add_workspace(self.b)
        self.cfg.select_workspace(self.a)
        # Every question a test expects is answered by patching an _ask_*
        # function, which never reaches QMessageBox. Any box that DOES open is
        # one nobody answers: offscreen it waits for ever. Record it, answer
        # Cancel, and fail the test in tearDown, naming it.
        self.dialogs = []

        def unexpected(*args, **_kw):
            self.dialogs.append([str(a) for a in args if isinstance(a, str)])
            return QMessageBox.Cancel

        for name in ("warning", "information", "critical", "question", "exec"):
            patcher = mock.patch.object(QMessageBox, name, side_effect=unexpected)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        # a test that leaves unsaved marks (Cancel at Save) would make close()
        # ask about them in a modal box nobody answers
        if self.win.document is not None:
            self.win.document._dirty = False
        self.win.close()
        for k, v in self._saved.items():
            if v is None:
                self.cfg.s.remove(k)
            else:
                self.cfg.s.setValue(k, v)
        self.cfg.sync()
        self.assertEqual(self.dialogs, [], "a dialog opened that the test did not answer")

    def _menu(self, source):
        from app import add_to_workspace
        menu = QMenu()
        add_to_workspace.populate(menu, self.win, source)
        self._menus = getattr(self, "_menus", []) + [menu]
        return menu

    @staticmethod
    def _labels(menu):
        return [a.text() for a in menu.actions() if not a.isSeparator()]

    @staticmethod
    def _sub(menu, label):
        return next(a.menu() for a in menu.actions() if a.text() == label and a.menu())

    @staticmethod
    def _trigger(menu, label):
        next(a for a in menu.actions() if a.text() == label).trigger()


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestTheMenu(_Window):

    def test_a_drawing_outside_every_workspace(self):
        src = _pdf(os.path.join(self.base, "Downloads", "E-101.pdf"))
        m = self._menu(src)
        self.assertEqual(self._labels(m), ["Project A", "drawings", "documentation",
                                           "notes", "RFIs", "New folder…",
                                           "Other workspaces"])
        self.assertFalse(m.actions()[0].isEnabled())                 # the heading
        self.assertEqual(self._labels(self._sub(self._sub(m, "Other workspaces"), "Plant B")),
                         ["drawings", "documentation", "notes", "New folder…"])

    def test_a_drawing_already_in_the_current_workspace(self):
        src = _pdf(os.path.join(self.a, "drawings", "E-101.pdf"))
        m = self._menu(src)
        already = next(a for a in m.actions() if a.text() == "Already in Project A")
        self.assertFalse(already.isEnabled())
        self.assertNotIn("drawings", self._labels(m))
        self.assertIn("drawings", self._labels(self._sub(self._sub(m, "Other workspaces"),
                                                         "Plant B")))

    def test_an_unavailable_workspace_and_no_workspace_at_all(self):
        src = _pdf(os.path.join(self.base, "Downloads", "E-101.pdf"))
        os.rename(self.b, self.b + " moved")
        m = self._menu(src)
        other = self._sub(m, "Other workspaces")
        entry = next(a for a in other.actions() if a.text().startswith("Plant B"))
        self.assertIn("(unavailable)", entry.text())
        self.assertFalse(entry.isEnabled())

        for root in (self.a, self.b):
            self.cfg.remove_workspace(root)
        m = self._menu(src)
        self.assertEqual(self._labels(m), ["Add a workspace…"])
        self._trigger(m, "Add a workspace…")
        self.assertEqual(self.win.file_view.page(), "workspaces")

    def test_no_drawing(self):
        m = self._menu(None)
        self.assertEqual(self._labels(m), ["Open a drawing first"])

    def test_the_file_menu_fills_itself_as_it_opens(self):
        self.win.load_document(_pdf(os.path.join(self.base, "Downloads", "E-101.pdf")))
        self.win.m_add_ws.aboutToShow.emit()
        self.assertIn("New folder…", self._labels(self.win.m_add_ws))


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestAddingTheOpenDrawing(_Window):

    def setUp(self):
        super().setUp()
        self.src = _marked_drawing(os.path.join(self.base, "Downloads"))
        self.src_hashes = {n: _sha(os.path.join(self.base, "Downloads", n))
                           for n in ("E-101.pdf", "E-101.marked.pdf")}
        self.win.load_document(self.src)
        self.win.document.store.add(Annotation(page=0, kind=KIND_RECT,
                                               rect=(100, 100, 150, 150), text="unsaved"))
        self.assertTrue(self.win.document.dirty)

    def test_cancel_at_save_copies_nothing(self):
        with mock.patch("app.add_to_workspace._ask_save", return_value=False):
            self._trigger(self._menu(self.src), "drawings")
        self.assertEqual(os.listdir(os.path.join(self.a, "drawings")), [])
        self.assertEqual(self.win.document.path, self.src)

    def test_saved_copied_and_switched_to_the_copy(self):
        with mock.patch("app.add_to_workspace._ask_save", return_value=True):
            self._trigger(self._menu(self.src), "drawings")
        copy = os.path.join(self.a, "drawings", "E-101.pdf")
        self.assertEqual(os.path.normpath(self.win.document.path), copy)
        self.assertIn("unsaved", [a.text for a in self.win.document.store.all()])
        self.assertIn("Project A ▸ drawings", self.win.statusBar().currentMessage())
        ws = self.cfg.find_workspace(self.a)
        self.assertEqual([r for r, _t in ws.recent], ["drawings/E-101.pdf"])
        # the original PDF is untouched; only its marked copy took the save
        self.assertEqual(_sha(self.src), self.src_hashes["E-101.pdf"])

    def test_a_quick_folder_is_made_on_first_use(self):
        with mock.patch("app.add_to_workspace._ask_save", return_value=True):
            self._trigger(self._menu(self.src), "documentation")
        self.assertTrue(os.path.isfile(os.path.join(self.a, "documentation", "E-101.pdf")))

    def test_keep_both_or_cancel_on_a_clash(self):
        there = _pdf(os.path.join(self.a, "drawings", "E-101.pdf"), "someone else's")
        before = _sha(there)
        with mock.patch("app.add_to_workspace._ask_save", return_value=True), \
                mock.patch("app.add_to_workspace._ask_keep_both", return_value=False):
            self._trigger(self._menu(self.src), "drawings")
        self.assertEqual(os.listdir(os.path.join(self.a, "drawings")), ["E-101.pdf"])
        with mock.patch("app.add_to_workspace._ask_keep_both", return_value=True) as ask:
            self._trigger(self._menu(self.src), "drawings")
        self.assertEqual(ask.call_args.args[2], "E-101 (2).pdf")
        self.assertEqual(os.path.normpath(self.win.document.path),
                         os.path.join(self.a, "drawings", "E-101 (2).pdf"))
        self.assertEqual(_sha(there), before)

    def test_new_folder(self):
        with mock.patch("app.add_to_workspace._ask_save", return_value=True), \
                mock.patch("app.add_to_workspace._ask_folder_name",
                           return_value=("Submittals", True)):
            self._trigger(self._menu(self.src), "New folder…")
        self.assertTrue(os.path.isfile(os.path.join(self.a, "Submittals", "E-101.pdf")))
        # a name that would be a path is refused before anything is made
        from app import add_to_workspace
        warned = []
        with mock.patch("app.add_to_workspace._ask_folder_name", return_value=("a/b", True)), \
                mock.patch("app.add_to_workspace._warn",
                           side_effect=lambda w, t: warned.append(t)):
            add_to_workspace._new_folder(self.win, self.win.document.path, self.b)
        self.assertEqual(len(warned), 1)
        self.assertEqual(os.listdir(self.b), ["drawings"])


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestAddingFromTheFileView(_Window):

    def test_an_identical_file_is_opened_instead(self):
        src = _pdf(os.path.join(self.base, "Downloads", "E-101.pdf"))
        os.makedirs(os.path.join(self.a, "drawings"), exist_ok=True)
        with open(src, "rb") as a, \
                open(os.path.join(self.a, "drawings", "E-101.pdf"), "wb") as b:
            b.write(a.read())
        with mock.patch("app.add_to_workspace._ask_open_existing", return_value=True):
            self._trigger(self._menu(src), "drawings")
        # nothing copied: no "E-101 (2)". (Opening the one there made its
        # sidecar, which every open does.)
        self.assertEqual(sorted(os.listdir(os.path.join(self.a, "drawings"))),
                         ["E-101.markup.db", "E-101.pdf"])
        self.assertEqual(os.path.normpath(self.win.document.path),
                         os.path.join(self.a, "drawings", "E-101.pdf"))

    def test_a_recent_row_copies_without_switching(self):
        opened = _pdf(os.path.join(self.base, "Downloads", "open.pdf"))
        other = _pdf(os.path.join(self.base, "Downloads", "E-201.pdf"))
        self.cfg.add_recent_file(other)
        self.win.load_document(opened)
        fv = self.win.file_view
        fv.show_recent()
        row = next(i for i in fv.file_rows() if i.text(0) == "E-201.pdf")
        menu = fv._context_menu_for(row)
        sub = self._sub(menu, "Add to workspace")
        self._trigger(sub, "RFIs")
        self.assertTrue(os.path.isfile(os.path.join(self.a, "RFIs", "E-201.pdf")))
        self.assertEqual(self.win.document.path, opened)             # no switch
        self.assertIn("Copied E-201.pdf", self.win.statusBar().currentMessage())

    def test_a_recent_row_that_is_missing_offers_no_copy(self):
        self.cfg.add_recent_file(os.path.join(self.base, "gone.pdf"))
        fv = self.win.file_view
        fv.show_recent()
        row = fv.file_rows()[0]
        self.assertNotIn("Add to workspace", self._labels(fv._context_menu_for(row)))


if __name__ == "__main__":
    unittest.main()
