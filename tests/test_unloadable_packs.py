"""A rule pack that will not load is named in Settings, with the reason.

PyDRC 0.19.0 refuses ``enabled`` on a rule. A user pack that set it loaded
under 0.18.0 and now raises ``PackError``. ``available_packs`` and
``available_rules`` dropped the failure with a bare ``continue``, so the pack
and its rules left the Design rules tab without a word, while a check that ran
the pack stopped in "Design rule check failed" with the reason.

Two more, found after that fix (2026-10-30). The pack had no box, so OK saved
the boxes ticked and dropped it from the choice: the check then ran without it
and said nothing. And a file in a pack directory that the library cannot read
as a pack at all was invisible, or, for three kinds of file, made
``loader.discover`` raise, which emptied the tab and stopped every check.

PyDRC 0.21.0's ``discover`` says which files it stepped over, and the runner
asks it. Its own walk stays for an older PyDRC.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import audit
from tests._qt import QT_OK

HAVE_PYDRC = audit.available()

#: The pack's id and its file name differ on purpose: the loader's message
#: names the file, so a pack id spelled like it would be "named" by the
#: message alone and the assertions below could not tell.
PACK_ID = "switched-off"
PACK_FILE = "user-pack.yaml"
#: A rule switched off in its own pack: the key 0.19.0 refuses.
PACK_TEXT = (f"pack: {{id: {PACK_ID}, version: 1.0.0, title: Switched off}}\n"
             "rules:\n"
             "  - {id: SWITCHED-RULE-001, entity: device, enabled: false,"
             " check: {fn: expect, args: {predicate:"
             " {field: tag, op: is_not_null}}}, message: x}\n")
PROBLEM = "unexpected keys ['enabled']"
#: The same pack without the refused key, which loads.
GOOD_TEXT = PACK_TEXT.replace(" enabled: false,", "")

#: Files the library cannot read as a pack, and a piece of the reason each
#: is named with. The last three made ``discover`` raise in PyDRC 0.19.0.
NOT_PACKS = {
    "bad-yaml.yaml": (b"pack: {id: broken\n  rules: [", "not valid YAML"),
    "bad.json": (b"{not json", "not valid JSON"),
    "no-id.yaml": (b"pack: {version: 1.0.0}\nrules:\n"
                   b"  - {id: NOID-RULE-001, entity: device,"
                   b" check: {fn: expect}}\n", "pack.id is required"),
    "empty.yaml": (b"", "pack must be a mapping"),
    "a-list.yaml": (b"- 1\n- 2\n", "pack must be a mapping"),
    "latin1.yaml": ("pack: {id: café, version: 1.0.0}\n".encode("latin-1"),
                    "codec can't decode"),
}


class _PackDirs(unittest.TestCase):
    """Temporary ``PYDRC_PACK_PATH`` directories, emptied after each test."""

    def setUp(self):
        self.dirs = [tempfile.mkdtemp()]
        self.dir = self.dirs[0]
        self.saved_path = os.environ.get("PYDRC_PACK_PATH")
        self._point()

    def _point(self):
        os.environ["PYDRC_PACK_PATH"] = os.pathsep.join(self.dirs)

    def another_dir(self) -> str:
        """A further directory, later in the path, so it wins."""
        self.dirs.append(tempfile.mkdtemp())
        self._point()
        return self.dirs[-1]

    def write(self, name, data, where=None) -> str:
        path = os.path.join(where or self.dir, name)
        with open(path, "wb") as fh:
            fh.write(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def tearDown(self):
        if self.saved_path is None:
            os.environ.pop("PYDRC_PACK_PATH", None)
        else:
            os.environ["PYDRC_PACK_PATH"] = self.saved_path
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)


class _UserPack(_PackDirs):
    """A pack directory holding the switched-off pack."""

    def setUp(self):
        super().setUp()
        self.pack_path = self.write(PACK_FILE, PACK_TEXT)


class _Settings:
    """A QApplication, and the saved pack choice put back after each test."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app.config import AppConfig
        self.config = AppConfig()
        self.saved_packs = self.config.audit_packs()
        self.config.set_audit_packs([])

    def tearDown(self):
        self.config.set_audit_packs(self.saved_packs)
        self.config.sync()
        super().tearDown()

    def _dialog(self):
        from app.settings_dialog import SettingsDialog
        return SettingsDialog(self.config)


def _blank_pdf(path):
    import fitz
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


@unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")
class TestTheRunnerNamesAPackThatWillNotLoad(_UserPack):
    def test_the_library_finds_the_pack(self):
        """Else every test here passes on a pack nobody looked for."""
        from pydrc.packs import loader
        from app.audit.runner import user_pack_dirs
        self.assertIn(PACK_ID, loader.discover(user_pack_dirs()))

    def test_it_is_named_with_the_loaders_reason(self):
        """Injected: the bare ``continue`` restored in ``_load_each`` (red)."""
        from app.audit.runner import available_packs, unloadable_packs
        failed = dict(unloadable_packs())
        self.assertIn(PACK_ID, failed)
        self.assertIn(PROBLEM, failed[PACK_ID])
        self.assertNotIn(PACK_ID, [p[0] for p in available_packs()])

    def test_the_reason_is_the_one_the_check_stops_with(self):
        from app.audit.runner import run_audit, unloadable_packs
        pdf = _blank_pdf(os.path.join(self.dir, "blank.pdf"))
        with self.assertRaises(Exception) as raised:
            run_audit(pdf, {}, {}, {}, pack_ids=[PACK_ID])
        self.assertEqual(dict(unloadable_packs())[PACK_ID], str(raised.exception))

    def test_a_pack_the_check_names_and_the_library_cannot_find(self):
        from app.audit.runner import unloadable_packs
        failed = dict(unloadable_packs(["gone"]))
        self.assertIn("no rule pack named 'gone'", failed["gone"])

    def test_a_pack_that_loads_is_not_named(self):
        from app.audit.runner import available_packs, default_packs, unloadable_packs
        self.assertGreaterEqual(len(available_packs()), 4)
        self.assertEqual(set(dict(unloadable_packs(default_packs()))), {PACK_ID})


@unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")
class TestPacksAreFoundWhereTheLibraryFindsThem(_PackDirs):
    """Before PyDRC 0.21.0 the runner finds packs itself, in ``_walk_packs``,
    so the walk is held to ``loader.discover``."""

    def test_the_map_is_discovers_on_a_tree_discover_can_read(self):
        """Injected: the search order reversed in ``_walk_packs`` (red)."""
        from pydrc.packs import loader
        from app.audit.runner import _find_packs, _walk_packs, user_pack_dirs
        self.write("user-ok.yaml", GOOD_TEXT.replace(PACK_ID, "user-ok"))
        # A user pack with a built-in's id, and the same id in two user
        # directories: a later one wins in both.
        self.write("heat.yaml", GOOD_TEXT.replace(PACK_ID, "erc-heat"))
        later = self.another_dir()
        self.write("user-ok-later.yaml", GOOD_TEXT.replace(PACK_ID, "user-ok"),
                   where=later)
        # The kinds of file discover can step over.
        for name in ("bad-yaml.yaml", "bad.json", "no-id.yaml"):
            self.write(name, NOT_PACKS[name][0])
        expected = loader.discover(user_pack_dirs())
        self.assertGreaterEqual(len(expected), 5, expected)
        self.assertEqual(expected["user-ok"], os.path.join(later, "user-ok-later.yaml"))
        self.assertEqual(expected["erc-heat"], os.path.join(self.dir, "heat.yaml"))
        self.assertEqual(_find_packs(user_pack_dirs())[0], expected)
        self.assertEqual(_walk_packs(loader, user_pack_dirs())[0], expected)


@unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")
class TestAFileThatIsNotAPackIsNamed(_PackDirs):
    def setUp(self):
        super().setUp()
        self.paths = {name: self.write(name, data)
                      for name, (data, _why) in NOT_PACKS.items()}

    def test_the_library_does_not_find_them(self):
        """Else the naming below is of files the library reads anyway."""
        from pydrc.packs import loader
        from app.audit.runner import user_pack_dirs
        for name, path in self.paths.items():
            lone = tempfile.mkdtemp()
            try:
                shutil.copy(path, lone)
                try:
                    found = loader.discover([lone])
                except Exception:
                    found = {}
                self.assertNotIn(os.path.join(lone, name), found.values(), name)
            finally:
                shutil.rmtree(lone, ignore_errors=True)
        self.assertEqual(len(self.paths), len(NOT_PACKS))
        self.assertTrue(user_pack_dirs())

    def test_each_is_named_with_the_reason(self):
        """Injected: no file recorded as unreadable in ``_find_packs`` (red)."""
        from app.audit.runner import unreadable_pack_files
        named = dict(unreadable_pack_files())
        for name, (_data, why) in NOT_PACKS.items():
            self.assertIn(self.paths[name], named, name)
            self.assertIn(why, named[self.paths[name]], name)
        self.assertEqual(len(named), len(NOT_PACKS), named)

    def test_the_packs_beside_them_still_load_and_the_check_runs(self):
        """Injected: ``except loader.PackError`` in ``_walk_packs``, as
        ``discover`` has (red against PyDRC 0.19.1: an empty file raises)."""
        from app.audit.runner import (available_packs, default_packs,
                                      run_audit, unloadable_packs)
        self.assertGreaterEqual(len(available_packs()), 4)
        self.assertEqual(unloadable_packs(default_packs()), [])
        result = run_audit(_blank_pdf(os.path.join(self.dir, "blank.pdf")),
                           {}, {}, {})
        self.assertEqual(len(result.run.packs), len(default_packs()))


@unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")
class TestTheFilesAreNamedFromTheLibrarysReport(_PackDirs):
    """From PyDRC 0.21.0, ``loader.discover(dirs, skipped=[])`` reports each
    file it stepped over with ``lint``'s reason, and ``_find_packs`` takes
    that report rather than walking the directories again. ``_walk_packs``
    stays for a PyDRC before 0.21.0, and for a ``discover`` that raises.

    Each branch is also driven by a stand-in ``discover``, so all three run
    whichever PyDRC is installed, and nothing here skips for its version.
    """

    def setUp(self):
        super().setUp()
        self.paths = {name: self.write(name, data)
                      for name, (data, _why) in NOT_PACKS.items()}
        self.write("user-ok.yaml", GOOD_TEXT.replace(PACK_ID, "user-ok"))

    def assertEachNamed(self, named: dict):
        for name, (_data, why) in NOT_PACKS.items():
            self.assertIn(self.paths[name], named, name)
            self.assertIn(why, named[self.paths[name]], name)
        self.assertEqual(len(named), len(NOT_PACKS), named)

    def test_the_installed_library_is_asked_when_it_can_say(self):
        """Injected: ``_find_packs`` walking on every PyDRC (red against
        0.21.0: the walk ran)."""
        import inspect
        from pydrc.packs import loader
        from app.audit import runner
        reports = "skipped" in inspect.signature(loader.discover).parameters
        with mock.patch.object(runner, "_walk_packs",
                               wraps=runner._walk_packs) as walk:
            named = dict(runner.unreadable_pack_files())
        self.assertEqual(walk.called, not reports,
                         f"discover reports what it skipped: {reports}")
        self.assertEachNamed(named)

    def test_the_walk_finds_and_names_what_the_library_does(self):
        """The walk held to the library's own report. Before PyDRC 0.21.0
        ``_find_packs`` IS the walk, so this compares it with itself there,
        and the test above is the one that says which ran."""
        from pydrc.packs import loader
        from app.audit import runner
        dirs = runner.user_pack_dirs()
        found, unreadable = runner._find_packs(dirs)
        self.assertIn("user-ok", found)
        self.assertGreaterEqual(len(unreadable), len(NOT_PACKS))
        self.assertEqual(runner._walk_packs(loader, dirs), (found, unreadable))

    def test_a_report_is_taken_as_the_library_gives_it(self):
        """Injected: the report dropped and the directories walked (red)."""
        from pydrc.packs import loader
        from app.audit import runner
        late, early = os.path.join("packs", "z.yaml"), os.path.join("packs", "a.yaml")

        def discover(extra=None, skipped=None):
            skipped += [(late, "z: why"), (early, "a: why")]
            return {"p": os.path.join("packs", "p.yaml")}

        with mock.patch.object(loader, "discover", discover), \
                mock.patch.object(runner, "_walk_packs",
                                  side_effect=AssertionError("walked")):
            self.assertEqual(runner._find_packs(runner.user_pack_dirs()),
                             ({"p": os.path.join("packs", "p.yaml")},
                              [(early, "a: why"), (late, "z: why")]))

    def test_a_library_without_the_report_is_walked(self):
        """As a PyDRC before 0.21.0 is: its ``discover`` takes no
        ``skipped``. Injected: ``except loader.PackError`` around
        ``discover`` (red: TypeError)."""
        from pydrc.packs import loader
        from app.audit import runner

        def discover(extra=None):
            raise AssertionError("only skipped= reaches here, and it cannot")

        with mock.patch.object(loader, "discover", discover):
            found, unreadable = runner._find_packs(runner.user_pack_dirs())
        self.assertIn("user-ok", found)
        self.assertEachNamed(dict(unreadable))

    def test_a_discover_that_raises_is_walked_and_the_packs_still_load(self):
        """Injected: no ``except`` around ``discover`` (red: TypeError), and
        an empty answer in place of the walk (red)."""
        from pydrc.packs import loader
        from app.audit import runner

        def discover(extra=None, skipped=None):
            raise TypeError("unhashable type: 'list'")

        with mock.patch.object(loader, "discover", discover):
            named = dict(runner.unreadable_pack_files())
            packs = runner.available_packs()
        self.assertEachNamed(named)
        self.assertIn("user-ok", [p[0] for p in packs])
        self.assertGreaterEqual(len(packs), 5)


@unittest.skipUnless(QT_OK and HAVE_PYDRC, "needs PySide6 and PyDRC")
class TestSettingsNamesAPackThatWillNotLoad(_Settings, _UserPack):
    def _box(self, dlg, pack_id):
        return dict(dlg.drc_packs)[pack_id]

    def test_the_tab_names_the_pack_and_the_problem(self):
        """Injected: the bare ``continue`` restored in ``_load_each`` (red)."""
        dlg = self._dialog()
        text = dlg.drc_pack_failed.text()
        self.assertIn(f"{PACK_ID} will not load", text)
        self.assertIn(PROBLEM, text)
        box = self._box(dlg, PACK_ID)
        self.assertIn("will not load", box.text())
        self.assertFalse(box.isChecked())

    def test_a_saved_pack_the_library_no_longer_finds_is_named(self):
        self.config.set_audit_packs(["drc-base", "gone"])
        text = self._dialog().drc_pack_failed.text()
        self.assertIn("gone will not load", text)
        self.assertIn("no rule pack named 'gone'", text)

    def test_with_every_pack_loading_the_tab_says_nothing(self):
        os.remove(self.pack_path)
        dlg = self._dialog()
        self.assertGreaterEqual(len(dlg.drc_packs), 4)
        self.assertEqual(dlg.drc_pack_failed.text(), "")

    def test_ok_keeps_a_saved_pack_that_will_not_load(self):
        """Injected: no box for a pack that will not load (red: OK saved
        the default packs and dropped it)."""
        self.config.set_audit_packs(["drc-base", "erc-nec-2026", PACK_ID])
        dlg = self._dialog()
        dlg.apply()
        self.assertEqual(sorted(self.config.audit_packs()),
                         sorted(["drc-base", "erc-nec-2026", PACK_ID]))
        self.assertTrue(self._box(dlg, PACK_ID).isChecked())
        self.assertIn("is set to run it", dlg.drc_pack_failed.text())

    def test_unticking_it_drops_it_from_the_choice(self):
        self.config.set_audit_packs(["drc-base", "erc-nec-2026", PACK_ID])
        dlg = self._dialog()
        self._box(dlg, PACK_ID).setChecked(False)
        self.assertIn(f"{PACK_ID} will not load", dlg.drc_pack_failed.text())
        self.assertNotIn("is set to run it", dlg.drc_pack_failed.text())
        dlg.apply()
        self.assertEqual(self.config.audit_packs(), [])

    def test_a_default_that_will_not_load_still_saves_as_the_default(self):
        """A user pack with a built-in's id wins, so drc-base itself fails.
        OK with nothing changed must go on following the library."""
        self.write("base.yaml", PACK_TEXT.replace(PACK_ID, "drc-base"))
        dlg = self._dialog()
        self.assertTrue(self._box(dlg, "drc-base").isChecked())
        self.assertIn("drc-base will not load", dlg.drc_pack_failed.text())
        dlg.apply()
        self.assertEqual(self.config.audit_packs(), [])


@unittest.skipUnless(QT_OK and HAVE_PYDRC, "needs PySide6 and PyDRC")
class TestSettingsNamesAFileThatIsNotAPack(_Settings, _PackDirs):
    def test_the_tab_builds_and_names_each_file(self):
        """Injected: ``except loader.PackError`` in ``_walk_packs`` (red
        against PyDRC 0.19.1: the dialog raised building the tab)."""
        paths = [self.write(name, data) for name, (data, _why) in NOT_PACKS.items()]
        dlg = self._dialog()
        self.assertGreaterEqual(len(dlg.drc_packs), 4)
        self.assertTrue(dlg.drc_rows)
        text = dlg.drc_pack_failed.text()
        for path in paths:
            self.assertIn(f"{path} is not a rule pack the library can read", text)


if __name__ == "__main__":
    unittest.main()
