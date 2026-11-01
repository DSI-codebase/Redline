"""The frozen build is the shipped form, and nothing launched it before v1.8.1.

v1.8.0 passed the suite on windows-latest and died on launch with
``FileNotFoundError: ...\\_internal\\pymupdf\\layout/resources/onnx/
layout_rf2.4.1+imf1.yaml``. PyMuPDF 2.0 moved its layout analyzer into the
wheel and `import fitz` activates it, which loads an ONNX model from data files
beside its modules. A source install has them. The PyInstaller bundle had the
modules and not the files, and the suite only ever runs from source.

Reproduced on Linux with the same spec, PyMuPDF 2.0 and PyInstaller 6.22.3 on
2026-10-31: the same exception from the same line (BoxRFDGNN.py:269).

Three gates, in the order a change meets them:

1. the spec keeps PyMuPDF's optional add-ons out of the bundle (every push);
2. ``main.py --self-test`` turns a launch failure into exit 1 and a report
   rather than an unhandled exception (every push, from source);
3. ``build-windows.yml`` runs that self-test against the FROZEN exe after
   PyInstaller and before the installer, so a build that cannot launch is never
   packaged or published (tag builds and manual runs).

The workflow and the spec are read by structure, never by a regex over the
file: both carry comments explaining this defect that name every string the
checks look for.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

REPO = pathlib.Path(__file__).resolve().parent.parent
SPEC = REPO / "packaging" / "DSI_Redline.spec"
BUILD = REPO / ".github" / "workflows" / "build-windows.yml"
MAIN = REPO / "main.py"


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


def _self_test_flag() -> str:
    """``main.SELF_TEST``, read with ``ast`` so this needs no Qt."""
    for node in ast.parse(MAIN.read_text(encoding="utf-8")).body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "SELF_TEST" for t in node.targets)
                and isinstance(node.value, ast.Constant)):
            return node.value.value
    return ""


def _steps(path: pathlib.Path) -> list[str]:
    """The job's steps, one string each, with comment lines dropped.

    A step starts at a ``- `` at the indentation of the first item under
    ``steps:``. Lines of a ``run: |`` block are deeper, so a PowerShell line
    beginning with a dash stays inside its step.
    """
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if not ln.lstrip().startswith("#")]
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "steps:"), None)
    if start is None:
        return []
    indent, steps = None, []
    for ln in lines[start + 1:]:
        if not ln.strip():
            continue
        lead = len(ln) - len(ln.lstrip())
        if indent is not None and lead < indent:
            break
        if ln.lstrip().startswith("- ") and indent in (None, lead):
            indent = lead
            steps.append([ln])
        elif steps:
            steps[-1].append(ln)
    return ["\n".join(s) for s in steps]


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


class TestTheBuildLaunchesWhatItBuilt(unittest.TestCase):

    def _find(self, steps, *needles):
        hits = [i for i, s in enumerate(steps) if all(n in s for n in needles)]
        self.assertEqual(len(hits), 1,
                         f"expected one step containing {needles}, found {len(hits)}")
        return hits[0]

    def test_the_self_test_runs_the_frozen_exe_between_build_and_packaging(self):
        steps = _steps(BUILD)
        self.assertGreaterEqual(len(steps), 8,
                                f"found {len(steps)} steps, so the reader missed the job")
        flag = _self_test_flag()
        self.assertTrue(flag.startswith("--"), "main.py no longer defines SELF_TEST")

        build = self._find(steps, "pyinstaller packaging/DSI_Redline.spec")
        smoke = self._find(steps, "DSI Redline.exe", flag)
        installer = self._find(steps, "ISCC.exe")
        later = [i for i, s in enumerate(steps)
                 if "upload-artifact" in s or "gh release" in s or "Compress-Archive" in s]
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
        self.assertNotIn("if:", smoke, "a condition would let a build skip it")
        self.assertIn("ExitCode", smoke, "the exit code is never read")
        self.assertIn("WaitForExit(", smoke,
                      "no timeout, so an error dialog would hang the job")


if __name__ == "__main__":
    unittest.main()
