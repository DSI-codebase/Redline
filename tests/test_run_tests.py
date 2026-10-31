"""The test runner's own skip attribution, and the gate over it.

It has been wrong four times: once counting every skip against the design
rule library when most were Qt; once failing a run whose Qt was fine because a
compound reason named PySide6 alongside PyDRC; once -- for as long as the
Tests workflow existed -- telling every CI run that the rule library was
absent when the library was installed and **ezdxf** was the thing missing,
because the workflow installed `pydrc` without its `[dxf]` extra; and once
(2026-10-30) telling a run with PyDRC 0.19.0 installed and Qt missing that "13
tests were SKIPPED because the design rule library is absent", because the
second fix filed "needs PySide6 and PyDRC" under the library whatever was
measured, and the banner fell back to that sentence when nothing optional was
missing.

The third and fourth are why `classify` is no longer the last word. It reads a
reason string and a compound reason forces it to pick; `missing_optional()`
and `qt_missing()` ask the interpreter, which cannot be wrong about what it can
import, and `classify` picks by what they measured.
"""

import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "run_tests", os.path.join(HERE, "tools", "run_tests.py"))
run_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_tests)


def _run_script(step_name: str) -> str:
    """The `run:` block of the named step in the Tests workflow.

    Hand-parsed rather than via PyYAML, which is not a dependency of this
    repository. What matters is that it returns the SCRIPT and not the whole
    file -- see the docstring on the test that needed it.
    """
    wf = os.path.join(HERE, ".github", "workflows", "tests.yml")
    with open(wf, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    try:
        i = next(n for n, ln in enumerate(lines)
                 if ln.strip() == f"- name: {step_name}")
    except StopIteration:
        raise AssertionError(f"no step named {step_name!r} in {wf}")
    out, in_run, indent = [], False, None
    for ln in lines[i + 1:]:
        if ln.strip().startswith("- name:"):
            break
        if not in_run:
            if ln.strip().startswith("run:"):
                in_run = True
                rest = ln.split("run:", 1)[1].strip()
                if rest and rest != "|":
                    out.append(rest)
            continue
        if not ln.strip():
            out.append("")
            continue
        lead = len(ln) - len(ln.lstrip())
        if indent is None:
            indent = lead
        if lead < indent:
            break
        out.append(ln[indent:])
    return "\n".join(out)


class TestClassify(unittest.TestCase):
    def test_splits_the_two_causes(self):
        drc, qt = run_tests.classify(
            {"PyDRC is not installed": 15, "PySide6 not available": 47})
        self.assertEqual((drc, qt), (15, 47))

    def test_a_reason_naming_both_counts_against_the_rule_library(self):
        # Qt is installed by both workflows, so attributing this to Qt fails a
        # run that is working exactly as intended when no token is configured.
        drc, qt = run_tests.classify({"needs PySide6 and PyDRC": 2})
        self.assertEqual((drc, qt), (2, 0))

    def test_a_reason_naming_both_stays_with_the_library_when_it_is_missing(self):
        drc, qt = run_tests.classify({"needs PySide6 and PyDRC": 3},
                                     qt_missing=False, rule_library_missing=True)
        self.assertEqual((drc, qt), (3, 0))

    def test_a_reason_naming_both_counts_against_qt_when_only_qt_is_missing(self):
        """Injected: the compound reason sent to the rule library whatever
        was measured (red)."""
        drc, qt = run_tests.classify({"needs PySide6 and PyDRC": 3},
                                     qt_missing=True, rule_library_missing=False)
        self.assertEqual((drc, qt), (0, 3))

    def test_a_reason_naming_both_counts_against_both_when_both_are_missing(self):
        drc, qt = run_tests.classify({"needs PySide6 and PyDRC": 3},
                                     qt_missing=True, rule_library_missing=True)
        self.assertEqual((drc, qt), (3, 3))

    def test_a_reason_naming_one_ignores_what_was_measured(self):
        # Only a compound reason is ambiguous. A Qt skip is a Qt skip.
        reasons = {"PyDRC is not installed": 2, "PySide6 not available": 4}
        for qt_missing in (False, True):
            for missing in (False, True):
                with self.subTest(qt_missing=qt_missing, missing=missing):
                    self.assertEqual(run_tests.classify(
                        reasons, qt_missing=qt_missing,
                        rule_library_missing=missing), (2, 4))

    def test_ezdxf_and_pydrc_is_a_rule_library_skip(self):
        # Still attributed to the rule library, because from the STRING alone
        # that is the better guess. What changed is that the banner no longer
        # stops there -- see TestMissingOptional.
        drc, qt = run_tests.classify({"needs ezdxf and pydrc": 5})
        self.assertEqual((drc, qt), (5, 0))

    def test_unrelated_reasons_count_as_neither(self):
        drc, qt = run_tests.classify({"needs a display": 3})
        self.assertEqual((drc, qt), (0, 0))

    def test_nothing_skipped(self):
        self.assertEqual(run_tests.classify({}), (0, 0))


class TestMissingOptional(unittest.TestCase):
    """The measured answer, which is what the banner should print.

    `classify` guesses from a reason string; this imports. The distinction
    cost five tests that never ran in CI while every run announced the wrong
    cause and passed.
    """

    def test_it_names_only_what_cannot_be_imported(self):
        absent = dict(run_tests.missing_optional())
        for mod in absent:
            with self.subTest(mod):
                with self.assertRaises(Exception):
                    __import__(mod)
        for mod in run_tests._OPTIONAL:
            if mod in absent:
                continue
            with self.subTest(mod):
                __import__(mod)   # must not raise: it was reported present

    def test_every_optional_library_is_described(self):
        # The description is what a reader sees instead of "the design rule
        # library" when the absent thing is ezdxf.
        for mod, described in run_tests._OPTIONAL.items():
            with self.subTest(mod):
                self.assertTrue(described.strip(), f"{mod} has no description")
                self.assertNotEqual(described, mod)

    def test_the_dxf_extra_is_what_the_workflow_installs(self):
        """The one-word regression that hid for the life of the workflow.

        `requirements-drc.txt` installs `pydrc[dxf]`; the workflow installed
        bare `pydrc`, so ezdxf was absent on every runner and the five tests
        guarded by `HAVE_EZDXF and HAVE_PYDRC` never ran. Asserted against the
        requirements file rather than a literal, so the two cannot drift.
        """
        req = os.path.join(HERE, "requirements-drc.txt")
        with open(req, encoding="utf-8") as fh:
            spec = [ln for ln in fh if ln.strip() and not ln.startswith("#")]
        self.assertTrue(spec, "requirements-drc.txt declares nothing")
        name = spec[0].split("@")[0].strip()          # e.g. "pydrc[dxf]"
        self.assertIn("[", name, f"{name!r} names no extra; this test is stale")
        install = [
            ln for ln in _run_script("Install the design rule library (optional)").splitlines()
            if "PyDRC@main" in ln and not ln.strip().startswith("#")
        ]
        self.assertTrue(install, "the workflow no longer installs PyDRC")
        for ln in install:
            self.assertIn(
                name, ln,
                f"the workflow installs PyDRC without the extra that "
                f"requirements-drc.txt asks for ({name})",
            )

    def test_qt_is_measured_by_the_probe_the_skips_use(self):
        """Missing exactly when the Qt modules ``tests/_qt.py`` imports
        cannot be imported in this interpreter."""
        missing = run_tests.qt_missing()
        try:
            import PySide6.QtCore  # noqa: F401
            import PySide6.QtGui  # noqa: F401
            import PySide6.QtWidgets  # noqa: F401
            loads = True
        except Exception:
            loads = False
        self.assertEqual(missing, not loads)

    def test_require_drc_is_passed_only_when_the_library_was_installed(self):
        """A fork with no token must still get a clean run.

        Read from the step's `run:` SCRIPT, never from the file text. The
        first draft searched the whole workflow and **passed with the flag
        deleted**, because the comment explaining why the flag exists also
        names it -- a gate satisfied by the documentation of the thing it
        exists to catch. Comment lines are stripped for the same reason.
        """
        script = _run_script("Run tests")
        code = "\n".join(
            ln for ln in script.splitlines() if not ln.strip().startswith("#")
        )
        self.assertIn("--require-drc", code, "the CI gate is gone")
        self.assertIn(
            'if [ -n "$PYDRC_TOKEN" ]', code,
            "--require-drc is no longer conditional on the token, so a fork "
            "without access would fail for a reason that is not its fault",
        )




class TestTheBanners(unittest.TestCase):
    """Each banner says what was measured missing, never what a reason's
    wording was filed under."""

    EZDXF = ("ezdxf", run_tests._OPTIONAL["ezdxf"])

    def _whys(self, reasons, absent, qt_absent, rule_library_missing):
        return [why for _n, why, _hint in run_tests.gaps(
            reasons, absent, qt_absent,
            rule_library_missing=rule_library_missing)]

    def test_qt_missing_alone_never_blames_the_rule_library(self):
        """Measured 2026-10-30 with PyDRC 0.19.0 installed and Qt not: "13
        tests were SKIPPED because the design rule library is absent".
        Injected: ``gaps`` calling ``classify`` without the measurements (red)."""
        banners = run_tests.gaps({"needs PySide6 and PyDRC": 13,
                                  "PySide6 (or its system libraries) not available": 1},
                                 absent=[], qt_absent=True,
                                 rule_library_missing=False)
        self.assertEqual([(n, why) for n, why, _ in banners],
                         [(14, "Qt (PySide6) could not be loaded")])

    def test_ezdxf_missing_takes_only_the_skips_that_checked_it(self):
        """Qt missing, PyDRC importable, ezdxf not. The "needs PySide6 and
        PyDRC" classes check ``audit.available()``, never ezdxf, so only the
        five "needs ezdxf and pydrc" skips are ezdxf's. Injected:
        ``rule_library_missing=bool(absent)`` in ``gaps`` (red: the ezdxf
        banner said 22, counting the 17 Qt skips a second time)."""
        banners = run_tests.gaps({"needs PySide6 and PyDRC": 17,
                                  "needs ezdxf and pydrc": 5,
                                  "PySide6 not available": 100},
                                 absent=[self.EZDXF], qt_absent=True,
                                 rule_library_missing=False)
        self.assertEqual([(n, why) for n, why, _ in banners], [
            (5, self.EZDXF[1] + " could not be imported"),
            (117, "Qt (PySide6) could not be loaded"),
        ])

    def test_a_skip_with_nothing_measured_absent_does_not_say_absent(self):
        """Injected: the old fallback, "the design rule library is absent" (red)."""
        # pydrc imports and its check still fails: audit.available() is False.
        whys = self._whys({"PyDRC is not installed": 2}, absent=[],
                          qt_absent=False, rule_library_missing=True)
        self.assertEqual(len(whys), 1)
        self.assertNotIn("absent", whys[0])
        self.assertNotIn("could not be imported", whys[0])
        self.assertIn("import here", whys[0])

    def test_an_absent_library_is_named(self):
        whys = self._whys({"needs ezdxf and pydrc": 5}, absent=[self.EZDXF],
                          qt_absent=False, rule_library_missing=False)
        self.assertEqual(whys, [self.EZDXF[1] + " could not be imported"])


class TestMainMeasuresTheRuleLibraryWithAudit(unittest.TestCase):
    """`main` passes `drc_status`'s answer to both `classify` and `gaps`.

    In-process rather than through a subprocess like
    TestTheRunnerWithQtMissing, so it runs where PyDRC is not installed: the
    probes run as written against modules planted in ``sys.modules`` (pydrc
    0.19.0 importable, ezdxf blocked, ``tests._qt.QT_OK`` False), and only
    the unittest child is replaced.
    """

    SKIPPED = 3

    def _run(self, *flags):
        def child(cmd, **_):
            out = "".join(
                f"test_{i} (tests.test_unloadable_packs.Settings.test_{i}) "
                f"... skipped 'needs PySide6 and PyDRC'\n"
                for i in range(self.SKIPPED))
            out += f"\nRan 8 tests in 0.1s\n\nOK (skipped={self.SKIPPED})\n"
            return subprocess.CompletedProcess(cmd, 0, "", out)

        pydrc = types.ModuleType("pydrc")
        pydrc.__version__ = "0.19.0"
        pydrc.checks = types.ModuleType("pydrc.checks")
        qt = types.ModuleType("tests._qt")
        qt.QT_OK = False
        planted = {"pydrc": pydrc, "pydrc.checks": pydrc.checks,
                   "ezdxf": None, "tests._qt": qt}   # None: import raises

        saved = {name: sys.modules.get(name, KeyError) for name in planted}
        buf = io.StringIO()
        try:
            sys.modules.update(planted)
            with mock.patch.dict(os.environ), \
                    mock.patch.object(run_tests.subprocess, "run",
                                      side_effect=child), \
                    contextlib.redirect_stdout(buf):
                code = run_tests.main(["tests.test_unloadable_packs", *flags])
        finally:
            for name, module in saved.items():
                if module is KeyError:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        return code, buf.getvalue()

    def test_ezdxf_missing_does_not_fail_require_drc_for_a_qt_skip(self):
        """Injected: ``rule_library_missing=bool(absent)`` in `main`'s own
        ``classify`` call, ``gaps`` left fixed (red: "--require-drc: failing
        because 3 tests were skipped for a missing optional library")."""
        code, out = self._run("--strict", "--require-drc")
        # Else the run never saw PyDRC as installed, and the assertions below
        # would hold for a different reason.
        self.assertIn("Design rule library: PyDRC 0.19.0", out)
        self.assertIn(f"; {self.SKIPPED} skipped.", out)
        banners = re.findall(r"^!! (\d+) tests were SKIPPED because (.*)\.$",
                             out, re.M)
        self.assertEqual(banners, [(str(self.SKIPPED),
                                    "Qt (PySide6) could not be loaded")])
        self.assertNotIn("--require-drc: failing", out)
        self.assertIn("--strict: failing because", out)
        self.assertEqual(code, 1)


# Refuses PySide6 and nothing else, the blocker tests/test_qt_absent_degrades.py
# uses. A sitecustomize on PYTHONPATH, because the runner starts a process per
# module and each one must be blocked too.
_NO_QT = textwrap.dedent("""
    import sys
    class _NoQt:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "PySide6":
                raise ImportError("PySide6 blocked by test_run_tests")
    sys.meta_path.insert(0, _NoQt())
""")


@unittest.skipUnless(importlib.util.find_spec("pydrc"), "PyDRC is not installed")
class TestTheRunnerWithQtMissing(unittest.TestCase):
    """The whole runner, on a module whose Settings tests skip with "needs
    PySide6 and PyDRC", with PyDRC importable and Qt blocked."""

    MODULE = "tests.test_unnumbered_pages_and_packs"

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        with open(os.path.join(cls.dir, "sitecustomize.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(_NO_QT)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (cls.dir, env.get("PYTHONPATH")) if p)
        cls.env = env
        cls.blocked = subprocess.run(
            [sys.executable, "-c", "import PySide6.QtWidgets"],
            env=env, capture_output=True, text=True)
        cls.result = subprocess.run(
            [sys.executable, os.path.join(HERE, "tools", "run_tests.py"),
             "--strict", "--require-drc", cls.MODULE],
            cwd=HERE, env=env, capture_output=True, text=True, timeout=600)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_the_blocker_blocks_and_the_compound_reason_is_there(self):
        """Else the assertions below are about a run that skipped nothing."""
        self.assertNotEqual(self.blocked.returncode, 0, self.blocked.stdout)
        self.assertIn("needs PySide6 and PyDRC", self.result.stdout)

    def test_every_skip_is_under_the_qt_banner_and_no_other(self):
        """Injected: the compound reason sent to the rule library whatever
        was measured (red: a second banner took six of the skips)."""
        out = self.result.stdout
        total = re.search(r"; (\d+) skipped\.", out)
        self.assertTrue(total, out)
        self.assertGreater(int(total.group(1)), 0, out)
        banners = re.findall(r"^!! (\d+) tests were SKIPPED because (.*)\.$",
                             out, re.M)
        self.assertEqual(banners, [(total.group(1), "Qt (PySide6) could not be loaded")])

    def test_ci_fails_it_for_qt_rather_than_for_the_library(self):
        """Under CI's flags the run failed with "--require-drc: failing
        because 13 tests were skipped for a missing optional library", and no
        optional library was missing."""
        self.assertEqual(self.result.returncode, 1, self.result.stdout)
        self.assertIn("--strict: failing because", self.result.stdout)
        self.assertNotIn("--require-drc: failing", self.result.stdout)


if __name__ == "__main__":
    unittest.main()
