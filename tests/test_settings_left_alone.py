"""A test run leaves the developer's Redline settings exactly as it found them.

`tests/__init__.py` gives every test process a settings folder of its own, and
this is its gate. It reads the store the app really uses rather than asking the
redirect where it put things, because a check that consults the redirect agrees
with the redirect.

1. Snapshot the developer's store, in a child process that never imports
   `tests`, through QSettings(ORG, APP): the constructor AppConfig used before
   the redirect existed, which is always NativeFormat. That is the registry on
   Windows and `~/.config/PDFMarkup/PDFMarkupApp.conf` on Linux. The child
   hashes each value, so an API key in the store never reaches this process or
   a CI log, and a failure names keys, never values.
2. Run modules that open documents through `MainWindow.load_document`, in a
   child that imports `tests` first, which is what each
   `python -m unittest tests.<module>` started by `tools/run_tests.py` does.
3. Snapshot again. The two must be equal.

Run alone, `test_v12_refview` leaves 14 `d.pdf` rows on the Recent list, and
`test_v110_callout` writes settings late enough that, without the atexit sync
in `tests/__init__.py`, it creates the removed folder again (2026-11-01).

Floored, because "nothing changed" is also what a run that opened nothing
reports: the child must run tests with none failing, and must put at least one
document on the Recent list, every one of them into a file under its own folder.

Falsified 2026-11-01 on Linux, each injection applied by a script that asserted
its anchor matched once:

* `tests/__init__.py` emptied: all three tests fail, and the store test names
  the five keys the run added.
* only its setDefaultFormat line deleted: the store and list tests fail.
  setPath moved IniFormat and AppConfig still opened NativeFormat, which is the
  shape of a path-only redirect on Windows, where setPath cannot move the
  registry.
* AppConfig put back to QSettings(ORG, APP), the hook intact: the store and
  list tests fail.
* the sync before the folder's removal deleted: the folder test fails. It
  passed at first, because the child then read the Recent list by building an
  AppConfig, and building a QSettings is itself that sync. See `_RUN`.

Run against a store seeded with a Recent list and an API key, the hook in
place leaves the file byte-identical. Without it the gate names `recent/files`
and `recent/opened` as changed, and the key's value is not in the output.

Falsified 2026-11-01 on Windows, with the first injection: `tests/__init__.py`
emptied on a throwaway branch from main 221f893, which is the file as it was
before PR #53 (git's empty blob), the edit asserted by a script before the
push. In Tests run 41344893116 this module was the only one to fail on each of
the three windows-latest legs, and all three of its tests failed. The store
test named `\\HKEY_CURRENT_USER\\Software\\PDFMarkup\\PDFMarkupApp` with
`recent/files`, `recent/opened`, `ui/geometry` and `ui/window_state` changed,
so the snapshot child reads the registry the defect writes. Changed rather
than added: the runner is a fresh machine, and every module before this one
also ran without the hook and had already written those keys when the first
snapshot was taken. The three ubuntu-latest legs and the floors job failed on
this module alone too.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

if _QT_OK:
    from app.config import ORG, APP

ROOT = Path(__file__).resolve().parent.parent

MODULES = ("tests.test_v12_refview", "tests.test_v110_callout")

# Run where `tests` cannot be imported, so nothing in it can steer what this
# reads. QSettings(org, app) is NativeFormat whatever setDefaultFormat says.
_SNAPSHOT = textwrap.dedent("""
    import hashlib, json, sys
    from PySide6.QtCore import QSettings
    s = QSettings(sys.argv[1], sys.argv[2])
    print(json.dumps({
        "file": s.fileName(),
        "values": {k: hashlib.sha256(repr(s.value(k)).encode("utf-8")).hexdigest()
                   for k in s.allKeys()},
    }))
""")

# `import tests` first, as `python -m unittest tests.<module>` imports the
# package before the module. getattr, so a hook that is gone still reaches the
# store comparison rather than dying here.
#
# The child WATCHES each document go onto the Recent list instead of reading
# the store after the run. Building a QSettings syncs the file, writing out
# what every other QSettings on it still holds, and that is the sync
# tests/__init__.py does before removing its folder: a first draft built an
# AppConfig here to read the list, did that sync itself, and the folder test
# stayed green with the sync deleted.
_RUN = textwrap.dedent("""
    import io, json, sys, unittest
    import tests
    from app.config import AppConfig
    opened = []
    _add = AppConfig.add_recent_file
    def _watch(self, path, when=None):
        opened.append([self.s.fileName(), str(path)])
        return _add(self, path, when)
    AppConfig.add_recent_file = _watch
    suite = unittest.TestLoader().loadTestsFromNames(sys.argv[1:])
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    print(json.dumps({
        "ran": result.testsRun,
        "failed": [str(t) for t, _ in result.failures + result.errors],
        "settings_dir": getattr(tests, "SETTINGS_DIR", None),
        "opened": opened,
    }))
""")


def _last_json(proc: subprocess.CompletedProcess, what: str) -> dict:
    lines = (proc.stdout or "").strip().splitlines()
    if proc.returncode != 0 or not lines:
        raise AssertionError(f"{what} died (exit {proc.returncode}):\n"
                             f"{(proc.stderr or '')[-3000:]}")
    return json.loads(lines[-1])


def _snapshot() -> dict:
    with tempfile.TemporaryDirectory() as away:
        proc = subprocess.run([sys.executable, "-c", _SNAPSHOT, ORG, APP],
                              cwd=away, capture_output=True, text=True,
                              timeout=120)
    return _last_json(proc, "the snapshot of the developer's store")


def _same_file(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _under(path: str, folder: str) -> bool:
    path = os.path.normcase(os.path.abspath(path))
    folder = os.path.normcase(os.path.abspath(folder))
    return path.startswith(folder + os.sep)


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestATestRunLeavesTheDevelopersSettingsAlone(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        cls.before = _snapshot()
        proc = subprocess.run([sys.executable, "-c", _RUN, *MODULES],
                              cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=900)
        cls.after = _snapshot()
        cls.child = _last_json(proc, "the child running " + ", ".join(MODULES))

    def _assert_the_child_opened_documents(self):
        c = self.child
        self.assertGreater(c["ran"], 0, f"{MODULES} ran no tests, so an "
                                        "unchanged store proves nothing")
        self.assertEqual(c["failed"], [], "the modules the gate runs failed, "
                                          "so it is not measuring a real run")
        self.assertTrue(c["opened"], f"{MODULES} put nothing on the Recent "
                        "list, so they no longer open a document and an "
                        "unchanged store proves nothing. Name a module that does.")

    def test_the_developers_store_is_unchanged(self):
        self._assert_the_child_opened_documents()
        before, after = self.before["values"], self.after["values"]
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(k for k in set(before) & set(after)
                         if before[k] != after[k])
        if added or removed or changed:
            self.fail(
                f"running {', '.join(MODULES)} changed the developer's "
                f"settings in {self.after['file']}: added {added}, removed "
                f"{removed}, changed {changed}. tests/__init__.py is meant to "
                "give every test process a store of its own.")

    def test_every_document_went_on_the_suites_own_list(self):
        self._assert_the_child_opened_documents()
        c = self.child
        self.assertIsNotNone(c["settings_dir"],
                             "tests/__init__.py set no SETTINGS_DIR")
        elsewhere = sorted({store for store, _ in c["opened"]
                            if not _under(store, c["settings_dir"])
                            or _same_file(store, self.after["file"])})
        self.assertEqual(elsewhere, [],
                         f"{len(c['opened'])} documents opened, and some were "
                         f"recorded outside the suite's folder "
                         f"{c['settings_dir']}, in {elsewhere}")

    def test_the_childs_folder_is_gone_after_it_exits(self):
        folder = self.child["settings_dir"]
        self.assertIsNotNone(folder, "tests/__init__.py set no SETTINGS_DIR")
        self.assertFalse(os.path.exists(folder),
                         f"{folder} is still there after its process exited. "
                         "A QSettings destroyed after atexit writes what it "
                         "holds, which creates the folder again.")


if __name__ == "__main__":
    unittest.main()
