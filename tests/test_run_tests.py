"""The test runner's own skip attribution, and the gate over it.

It has been wrong four times: once counting every skip against the design
rule library when most were Qt; once failing a run whose Qt was fine because a
compound reason named PySide6 alongside PyDRC; once -- for as long as the
Tests workflow existed -- telling every CI run that the rule library was
absent when the library was installed and **ezdxf** was the thing missing,
because the workflow installed `pydrc` without its `[dxf]` extra; and once,
on 2026-10-30, the second one's fix turned inside out: Qt missing, PyDRC
0.19.0 installed, and three "needs PySide6 and PyDRC" skips bannered as the
design rule library being absent.

The third and fourth are why a reason string is no longer the last word. A
compound reason forces a pick; `missing_optional()`, `drc_status()` and
`qt_available()` ask the interpreter, which cannot be wrong about what it can
import.
"""

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
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
    BOTH = {"needs PySide6 and PyDRC": 2}

    def test_splits_the_two_causes(self):
        result = run_tests.classify(
            {"PyDRC is not installed": 15, "PySide6 not available": 47},
            qt_ok=False, drc_ok=False)
        self.assertEqual(result, (15, 47, {}))

    def test_a_reason_naming_one_is_trusted_over_this_runner(self):
        # The child that skipped measured it; the runner's probe is a second
        # opinion only where the reason cannot say which.
        result = run_tests.classify(
            {"PyDRC is not installed": 15, "PySide6 not available": 47},
            qt_ok=True, drc_ok=True)
        self.assertEqual(result, (15, 47, {}))

    def test_a_reason_naming_both_is_the_rule_library_when_qt_loads(self):
        # Qt is installed by both workflows, so attributing this to Qt fails a
        # run that is working exactly as intended when no token is configured.
        result = run_tests.classify(self.BOTH, qt_ok=True, drc_ok=False)
        self.assertEqual(result, (2, 0, {}))

    def test_a_reason_naming_both_is_qt_when_the_rule_library_loads(self):
        # The 2026-10-30 machine: PyDRC 0.19.0 installed, libEGL.so.1 absent.
        result = run_tests.classify(self.BOTH, qt_ok=False, drc_ok=True)
        self.assertEqual(result, (0, 2, {}))

    def test_a_reason_naming_both_is_both_when_neither_loads(self):
        result = run_tests.classify(self.BOTH, qt_ok=False, drc_ok=False)
        self.assertEqual(result, (2, 2, {}))

    def test_a_reason_naming_both_is_unmeasured_when_both_load(self):
        # Neither banner would be true, so neither gets it.
        result = run_tests.classify(self.BOTH, qt_ok=True, drc_ok=True)
        self.assertEqual(result, (0, 0, self.BOTH))

    def test_ezdxf_and_pydrc_is_a_rule_library_skip(self):
        # Both named libraries are the optional kind, so the category is not
        # in doubt even with PyDRC loading -- the CI case, where ezdxf was the
        # absent one. Which of the two is for the banner -- see
        # TestMissingOptional.
        result = run_tests.classify({"needs ezdxf and pydrc": 5},
                                    qt_ok=True, drc_ok=True)
        self.assertEqual(result, (5, 0, {}))

    def test_unrelated_reasons_count_as_neither(self):
        result = run_tests.classify({"needs a display": 3},
                                    qt_ok=False, drc_ok=False)
        self.assertEqual(result, (0, 0, {}))

    def test_nothing_skipped(self):
        self.assertEqual(run_tests.classify({}, qt_ok=False, drc_ok=False),
                         (0, 0, {}))


class TestQtMissingWithPyDRCInstalled(unittest.TestCase):
    """The run of 2026-10-30, replayed through `main`.

    Linux, Python 3.13.17, PyDRC 0.19.0 installed, ``libEGL.so.1`` missing so
    `tests/_qt.py` said ``QT_OK = False``. Three Settings classes in
    `tests/test_unloadable_packs.py` skipped with "needs PySide6 and PyDRC",
    and the banner said the design rule library was absent, under a first
    line reading ``Design rule library: PyDRC 0.19.0``.

    The fakes sit where the runner looks rather than on the runner: `pydrc`,
    `pydrc.checks`, `ezdxf` and `tests._qt` are planted in ``sys.modules`` so
    `drc_status`, `missing_optional` and `qt_available` run as written, and
    only the unittest child process is replaced. Neither library has to be
    installed, and an installed one is shadowed for the duration.
    """

    SKIPPED = 3

    def _replay(self, *flags, qt_ok=False):
        def child(cmd, **_):
            out = "".join(
                f"test_{i} (tests.test_unloadable_packs.TestSettingsShowsPacks"
                f".test_{i}) ... skipped 'needs PySide6 and PyDRC'\n"
                for i in range(self.SKIPPED))
            out += ("\n" + "-" * 70 + "\nRan 8 tests in 0.120s\n\n"
                    f"OK (skipped={self.SKIPPED})\n")
            return subprocess.CompletedProcess(cmd, 0, "", out)

        pydrc = types.ModuleType("pydrc")
        pydrc.__version__ = "0.19.0"
        pydrc.checks = types.ModuleType("pydrc.checks")
        qt = types.ModuleType("tests._qt")
        qt.QT_OK = qt_ok
        planted = {"pydrc": pydrc, "pydrc.checks": pydrc.checks,
                   "ezdxf": types.ModuleType("ezdxf"), "tests._qt": qt}

        saved = {name: sys.modules.get(name) for name in planted}
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
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        return code, buf.getvalue()

    def assertTheFakeTook(self, out):
        # Without this, a run that never saw PyDRC as installed would print a
        # rule-library banner in other words, and the absence assertion below
        # would agree with it.
        self.assertIn("Design rule library: PyDRC 0.19.0", out)
        self.assertIn(f"8 tests across 1 modules; {self.SKIPPED} skipped.",
                      out)

    def test_the_banner_does_not_blame_the_rule_library(self):
        code, out = self._replay()
        self.assertTheFakeTook(out)
        self.assertNotIn("design rule library is absent", out)
        banners = [ln for ln in out.splitlines() if "SKIPPED because" in ln]
        self.assertEqual(banners, [
            f"!! {self.SKIPPED} tests were SKIPPED because Qt (PySide6) "
            f"could not be loaded.",
        ])
        self.assertEqual(code, 0)

    def test_ci_flags_fail_it_for_qt_not_for_the_rule_library(self):
        # Both workflows pass --strict; --require-drc follows the token.
        code, out = self._replay("--strict", "--require-drc")
        self.assertTheFakeTook(out)
        self.assertNotIn("--require-drc: failing", out)
        self.assertIn(f"--strict: failing because {self.SKIPPED} tests were "
                      f"skipped for a missing Qt", out)
        self.assertEqual(code, 1)

    def test_with_both_loading_it_blames_neither_and_still_fails_ci(self):
        # The skip happened and the runner cannot say why. Before compound
        # reasons were measured this failed --require-drc as a rule-library
        # skip; it must not turn green by becoming unexplained.
        code, out = self._replay("--strict", "--require-drc", qt_ok=True)
        self.assertTheFakeTook(out)
        banners = [ln for ln in out.splitlines() if "SKIPPED because" in ln]
        self.assertEqual(banners, [
            f'!! {self.SKIPPED} tests were SKIPPED because of "needs PySide6 '
            f'and PyDRC", yet Qt and the design rule library both load in '
            f'this runner.',
        ])
        self.assertIn(f"--require-drc: failing because {self.SKIPPED} tests "
                      f"were skipped for a cause this runner could not "
                      f"measure.", out)
        self.assertEqual(code, 1)


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


if __name__ == "__main__":
    unittest.main()
