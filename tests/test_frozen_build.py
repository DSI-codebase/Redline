"""The frozen build is the shipped form, and nothing launched it before v1.8.1.

v1.8.0 passed the suite on windows-latest and died on launch with
``FileNotFoundError: ...\\_internal\\pymupdf\\layout/resources/onnx/
layout_rf2.4.1+imf1.yaml``. PyMuPDF 2.0 moved its layout analyzer into the
wheel and `import fitz` activates it, which loads an ONNX model from data files
beside its modules. A source install has them. The PyInstaller bundle had the
modules and not the files, and the suite only ever runs from source.

Reproduced on Linux with the same spec, PyMuPDF 2.0 and PyInstaller 6.22.3 on
2026-10-31: the same exception from the same line (BoxRFDGNN.py:269).

The same class of defect came back in v1.8.1's build, in a form the self-test
cannot see. The spec collected PyDRC's data with ``includes=["**/*.yaml"]``,
and PyDRC v0.23.1's calculator tables and part ratings file are JSON: 29 files,
none bundled. The window builds without reading a table, so the app launched,
and every calculator stopped with "no NEC 2026 table '240.4-D' (looked for
...\\_internal\\pydrc\\calc\\data\\nec\\2026\\240.4-D.json)". Measured with
PyInstaller 6.22.3 on 2026-11-01: that filter collected 9 of PyDRC's 38 data
files.

Five gates, in the order a change meets them:

1. the spec keeps PyMuPDF's optional add-ons out of the bundle (every push);
2. the spec's ``includes`` match every data file the installed PyDRC has
   (every push with PyDRC installed, which CI requires when it has the token);
3. ``main.py --self-test`` turns a launch failure into exit 1 and a report
   rather than an unhandled exception (every push, from source);
4. ``build-windows.yml`` runs ``tools/bundle_check.py`` against the FROZEN
   bundle, comparing it with the installed PyDRC file by file;
5. ...and runs the self-test against the frozen exe. Both run after PyInstaller
   and before the installer, so a bundle missing a file, or one that cannot
   launch, is never packaged or published (tag builds and manual runs).

The workflow is read through ``tests/_workflow.py`` and the spec with ``ast``,
never by a regex over the file: both carry comments explaining these defects
that name every string the checks look for.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import importlib.util
import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from tests import _workflow
from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

REPO = pathlib.Path(__file__).resolve().parent.parent
SPEC = REPO / "packaging" / "DSI_Redline.spec"
BUILD = REPO / ".github" / "workflows" / "build-windows.yml"
MAIN = REPO / "main.py"
TOOL = REPO / "tools" / "bundle_check.py"

_tool_spec = importlib.util.spec_from_file_location("bundle_check", TOOL)
bundle_check = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(bundle_check)

try:
    _PYDRC_DIR = bundle_check.package_dir("pydrc")
except bundle_check.Refusal:
    _PYDRC_DIR = None


def _spec_excludes() -> list[str]:
    """The strings the spec's ``Analysis(excludes=...)`` resolves to.

    A list literal is read in place; a name is resolved to its module-level
    assignment. Anything else returns ``[]``, which the test refuses.
    """
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    assigned = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = node.value
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Analysis"):
            for kw in node.keywords:
                if kw.arg != "excludes":
                    continue
                value = kw.value
                if isinstance(value, ast.Name):
                    value = assigned.get(value.id)
                if isinstance(value, ast.List):
                    return [e.value for e in value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _spec_includes() -> list:
    """The patterns each ``collect_data_files`` call in the spec collects.

    One list per call. A call with no ``includes`` collects everything, as
    PyInstaller reads it, so it gets ``["**/*"]``. An ``includes`` that is not
    a list literal gets ``None``, which the test refuses rather than guesses.
    """
    out = []
    for node in ast.walk(ast.parse(SPEC.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "collect_data_files"):
            value = next((kw.value for kw in node.keywords if kw.arg == "includes"), None)
            if value is None:
                out.append(["**/*"])
            elif isinstance(value, ast.List):
                out.append([e.value for e in value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)])
            else:
                out.append(None)
    return out


def _matched(root: pathlib.Path, patterns) -> set:
    """What ``includes=patterns`` matches under ``root``, as PyInstaller 6 reads it:
    ``pathlib.Path.glob`` per pattern, and a matched directory brings every file
    under it."""
    out = set()
    for pattern in patterns:
        for p in root.glob(pattern):
            for f in (p.rglob("*") if p.is_dir() else [p]):
                if f.is_file():
                    out.add(f.relative_to(root).as_posix())
    return out


def _self_test_flag() -> str:
    """``main.SELF_TEST``, read with ``ast`` so this needs no Qt."""
    for node in ast.parse(MAIN.read_text(encoding="utf-8")).body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "SELF_TEST" for t in node.targets)
                and isinstance(node.value, ast.Constant)):
            return node.value.value
    return ""


def _steps(path: pathlib.Path) -> list[dict]:
    """The ``build`` job's steps, as ``tests/_workflow.py`` reads them.

    This split the file by hand: from the first ``steps:`` line, comment lines
    dropped, one string per ``- `` at the first item's indent. A needle then
    matched anywhere in a step's string, its ``name:`` and ``env:`` included,
    and a condition was any line beginning ``if:``. Each check now asks the
    field it is about: a command is looked for in the ``run:`` script
    (``_script``), an action in ``uses:`` (``_action``), and a condition or a
    ``continue-on-error`` among the step's own keys.
    """
    jobs = _workflow.load(str(path))["jobs"]
    if "build" not in jobs:
        raise AssertionError(f"no job named 'build' in {path}; it has {sorted(jobs)}")
    steps = (jobs["build"] or {}).get("steps") or []
    odd = [i for i, st in enumerate(steps) if not isinstance(st, dict)]
    if odd:
        raise AssertionError(f"steps {odd} of the build job in {path} are not mappings")
    return steps


def _script(step: dict) -> str:
    """The step's ``run:`` script with its comment lines dropped, or ``""``.

    YAML comments never reach it. A ``#`` line inside the script is the
    script's own comment, in bash and in PowerShell, and the hand reader
    dropped those too, so a command commented out still does not count as run.
    """
    run = step.get("run")
    if not isinstance(run, str):
        return ""
    return "\n".join(ln for ln in run.splitlines() if not ln.lstrip().startswith("#"))


def _action(step: dict) -> str:
    """The action a ``uses:`` step runs, its ``@`` ref dropped, or ``""``."""
    uses = step.get("uses")
    return uses.split("@", 1)[0] if isinstance(uses, str) else ""


class TestTheSpecLeavesPyMuPDFsAddOnsOut(unittest.TestCase):

    def test_the_layout_analyzer_and_pymupdf4llm_are_excluded(self):
        excludes = _spec_excludes()
        self.assertTrue(excludes, "no `excludes` list found on the spec's Analysis() call")
        self.assertIn("tkinter", excludes, "the reader lost the one exclude that predates this")
        for name in ("pymupdf.layout", "pymupdf4llm"):
            with self.subTest(name):
                self.assertIn(
                    name, excludes,
                    f"{name} is bundled again. PyMuPDF 2.0 imports it from "
                    "`import pymupdf`, and pymupdf.layout then loads ONNX model "
                    "files the analysis does not collect: v1.8.0's launch crash.")

    def test_the_reader_does_not_see_a_name_in_a_comment(self):
        """The spec's comment names both modules, so prove the reader skips it."""
        source = SPEC.read_text(encoding="utf-8")
        self.assertIn("pymupdf.layout", source.split("excludes =")[0],
                      "the comment above the list no longer names the module, "
                      "so this guard proves nothing")
        stripped = ast.unparse(ast.parse(source))
        self.assertEqual(stripped.count("pymupdf.layout"), 1,
                         "the module is named once in code, in the list")


@unittest.skipUnless(_PYDRC_DIR, "PyDRC is not installed")
class TestTheSpecCollectsEveryPyDRCDataFile(unittest.TestCase):
    """The spec's filter, held to the package it filters, on every push.

    The oracle is the installed PyDRC's own files, listed by the same function
    the build's bundle check uses, never a list of extensions written here.
    """

    def test_every_installed_data_file_matches_the_specs_includes(self):
        calls = _spec_includes()
        self.assertEqual(len(calls), 1,
                         f"expected one collect_data_files call in the spec, found {len(calls)}")
        patterns = calls[0]
        self.assertIsNotNone(patterns, "the spec's includes= is not a list literal")
        installed = bundle_check.data_files(_PYDRC_DIR)
        # The floor. A sweep that found no tables passes whatever the spec says.
        self.assertTrue(any(f.startswith("calc/data/") and f.endswith(".json") for f in installed),
                        f"no calculator table found under {_PYDRC_DIR}, so this compared nothing")
        self.assertTrue(any(f.startswith("packs/") and f.endswith(".yaml") for f in installed),
                        f"no rule pack found under {_PYDRC_DIR}, so this compared nothing")
        left_out = sorted(set(installed) - _matched(_PYDRC_DIR, patterns))
        self.assertEqual(
            left_out, [],
            f"the spec's includes {patterns} leave {len(left_out)} of PyDRC's "
            f"{len(installed)} data files out of the bundle, and PyDRC reads them "
            "from beside its modules: v1.8.1's \"no NEC 2026 table\".")


def _quiet(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bundle_check.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestTheBundleCheck(unittest.TestCase):
    """``tools/bundle_check.py`` on a package and a bundle built here.

    The fixture has the shape of the v1.8.1 defect: a YAML pack and a JSON
    table beside the modules, and a module and a ``__pycache__`` that the
    bundle keeps in its archive rather than as files.
    """

    NAME = "redline_bundle_check_fixture"
    DATA = ("packs/base.yaml", "calc/data/nec/2026/240.4-D.json")

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        site = self.tmp / "site"
        pkg = site / self.NAME
        for rel in self.DATA + ("__init__.py", "calc/__init__.py", "__pycache__/x.cpython-311.pyc"):
            (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            (pkg / rel).write_text("x", encoding="utf-8")
        sys.path.insert(0, str(site))
        self.addCleanup(sys.path.remove, str(site))
        importlib.invalidate_caches()
        self.dist = self.tmp / "dist" / "DSI Redline"
        self.bundled = self.dist / "_internal" / self.NAME

    def _bundle(self, *rels):
        for rel in rels:
            (self.bundled / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.bundled / rel).write_text("x", encoding="utf-8")

    def _run(self, name=None):
        return _quiet(["--dist", str(self.dist), name or self.NAME])

    def test_a_bundle_with_every_data_file_passes_and_says_how_many(self):
        self._bundle(*self.DATA)
        code, out, err = self._run()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("2 data files installed, 2 in the bundle, 0 missing", out)

    def test_modules_and_pycache_are_not_data(self):
        """The bundle above holds no .py and no __pycache__ and passed. This
        says why: they were never in the list it compared."""
        self.assertEqual(
            bundle_check.data_files(bundle_check.package_dir(self.NAME)), sorted(self.DATA))

    def test_the_v181_bundle_fails_and_names_the_table(self):
        """The injected defect: the YAML bundled and the JSON not."""
        self._bundle("packs/base.yaml")
        code, out, _ = self._run()
        self.assertEqual(code, bundle_check.MISSING)
        self.assertIn("1 missing", out)
        self.assertIn(f"missing from _internal/{self.NAME}/: calc/data/nec/2026/240.4-D.json", out)

    def test_a_package_that_is_not_installed_is_refused(self):
        self._bundle(*self.DATA)
        code, out, err = self._run("redline_no_such_package")
        self.assertEqual((code, out), (bundle_check.REFUSED, ""))
        self.assertIn("not installed", err)

    def test_a_package_with_no_data_files_is_refused(self):
        for rel in self.DATA:
            (self.tmp / "site" / self.NAME / rel).unlink()
        self.bundled.mkdir(parents=True)
        code, out, err = self._run()
        self.assertEqual((code, out), (bundle_check.REFUSED, ""))
        self.assertIn("no data files", err)

    def test_a_dist_with_no_internal_folder_is_refused(self):
        self.dist.mkdir(parents=True)
        code, out, err = self._run()
        self.assertEqual((code, out), (bundle_check.REFUSED, ""))
        self.assertIn("no _internal/", err)


@unittest.skipUnless(_QT_OK, _QT_REASON)  # imports `main`, which imports PySide6 (main.py:9)
class TestTheSelfTestReportsRatherThanRaises(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.report = os.path.join(self.tmp, "self-test.txt")

    def _read(self):
        with open(self.report, encoding="utf-8") as fh:
            return fh.read()

    def test_the_flag_is_parsed(self):
        from main import self_test_report
        self.assertIsNone(self_test_report(["prog"]))
        self.assertIsNone(self_test_report(["prog", "drawing.pdf"]))
        self.assertEqual(self_test_report(["prog", "--self-test", "r.txt"]), "r.txt")
        self.assertEqual(self_test_report(["prog", "--self-test"]), "")

    def test_a_flag_with_no_path_is_refused_before_anything_starts(self):
        import main
        with mock.patch.object(main, "start") as start:
            self.assertEqual(main.main(["prog", "--self-test"]), 2)
        start.assert_not_called()

    def test_a_launch_that_works_reports_ok(self):
        import main
        code = main.main(["prog", main.SELF_TEST, self.report])
        self.assertEqual((code, self._read()), (0, "ok\n"))

    def test_a_launch_that_fails_at_the_v180_line_reports_the_traceback(self):
        """The injected defect: the import that failed in v1.8.0, failing."""
        import main
        with mock.patch.dict(sys.modules, {"app.main_window": None}):
            code = main.main(["prog", main.SELF_TEST, self.report])
        text = self._read()
        self.assertEqual(code, 1)
        self.assertIn("Traceback", text)
        self.assertIn("app.main_window", text)


class _Steps:

    def _find(self, steps, *needles):
        """The index of the one step whose ``run:`` script holds every needle."""
        hits = [i for i, st in enumerate(steps) if all(n in _script(st) for n in needles)]
        self.assertEqual(len(hits), 1,
                         f"expected one step whose run: script contains {needles}, "
                         f"found {len(hits)}")
        return hits[0]

    @staticmethod
    def _packaging(steps):
        """Each step that packages or publishes: an ``actions/upload-artifact``
        step, or a script that zips the app or calls ``gh release``."""
        return [i for i, st in enumerate(steps)
                if _action(st) == "actions/upload-artifact"
                or "gh release" in _script(st) or "Compress-Archive" in _script(st)]


class TestTheBuildChecksTheBundleAgainstTheInstall(_Steps, unittest.TestCase):

    def test_the_check_runs_between_the_build_and_the_installer(self):
        steps = _steps(BUILD)
        self.assertGreaterEqual(len(steps), 8,
                                f"found {len(steps)} steps, so the reader missed the job")
        rel = TOOL.relative_to(REPO).as_posix()
        build = self._find(steps, "pyinstaller packaging/DSI_Redline.spec")
        check = self._find(steps, f"python {rel}")
        installer = self._find(steps, "ISCC.exe")
        later = self._packaging(steps)
        self.assertTrue(later, "the reader found no packaging step")
        self.assertLess(build, check, "the check runs before there is a bundle")
        self.assertLess(check, installer, "the installer is built before the bundle is checked")
        self.assertLess(check, min(later), "something is packaged before the bundle is checked")
        self.assertIn('--dist "dist/DSI Redline" pydrc', _script(steps[check]),
                      "the check no longer names the folder PyInstaller writes, or PyDRC")

    def test_the_check_can_fail_the_job_and_skips_only_a_build_without_pydrc(self):
        steps = _steps(BUILD)
        check = self._find(steps, f"python {TOOL.relative_to(REPO).as_posix()}")
        step = steps[check]
        self.assertNotIn("continue-on-error", step)
        self.assertEqual(step.get("if"), "env.PYDRC_BUILT != 'none'",
                         "the check runs whenever the build installed PyDRC, and only then")
        sets_none = self._find(steps, "PYDRC_BUILT=none")
        self.assertLess(sets_none, check,
                        "PYDRC_BUILT is set after the check reads it, so the check never runs")


class TestTheBuildLaunchesWhatItBuilt(_Steps, unittest.TestCase):

    def test_the_self_test_runs_the_frozen_exe_between_build_and_packaging(self):
        steps = _steps(BUILD)
        self.assertGreaterEqual(len(steps), 8,
                                f"found {len(steps)} steps, so the reader missed the job")
        flag = _self_test_flag()
        self.assertTrue(flag.startswith("--"), "main.py no longer defines SELF_TEST")

        build = self._find(steps, "pyinstaller packaging/DSI_Redline.spec")
        smoke = self._find(steps, "DSI Redline.exe", flag)
        installer = self._find(steps, "ISCC.exe")
        later = self._packaging(steps)
        self.assertGreaterEqual(len(later), 4, "the zip, both uploads and the release")

        self.assertLess(build, smoke, "the self-test runs before there is an exe")
        self.assertLess(smoke, installer,
                        "the installer is built before the app is known to launch")
        self.assertLess(smoke, min(later),
                        "something is packaged or published before the app is "
                        "known to launch")

    def test_the_self_test_step_can_fail_the_job(self):
        steps = _steps(BUILD)
        smoke = steps[self._find(steps, "DSI Redline.exe", _self_test_flag())]
        self.assertNotIn("continue-on-error", smoke)
        self.assertNotIn("if", smoke, "a condition would let a build skip it")
        script = _script(smoke)
        self.assertIn("ExitCode", script, "the exit code is never read")
        # An argument, because `$p.WaitForExit()` waits forever and still
        # contains "WaitForExit(", which is all this asked until 2026-11-01.
        self.assertRegex(script, r"\.WaitForExit\(\s*[^)\s]",
                         "no timeout, so an error dialog would hang the job")


if __name__ == "__main__":
    unittest.main()
