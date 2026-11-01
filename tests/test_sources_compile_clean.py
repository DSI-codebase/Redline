r"""Every source file compiles without a warning, on every interpreter CI runs.

Two docstrings in `tests/test_drc_ref_resolution.py` held Windows paths in
plain strings, `C:\Program Files\Git\bin\bash.exe` and
`C:\Windows\System32\bash.exe`. `\P` and `\W` are not escapes, and from 3.12
the compiler says so with a `SyntaxWarning`. Measured 2026-11-01 at 2eabbf6 by
compiling every `.py` the repository tracks: 160 files, 2 warnings, both
there, on 3.11, 3.12 and 3.13 alike.

Nobody saw them, and each reason shaped this gate:

  * a module warns only when it is compiled, and once `__pycache__` holds it,
    a later import compiles nothing and says nothing. So this compiles from
    SOURCE, with `compile()`, and never imports.
  * on 3.11 the same defect is a `DeprecationWarning`, which the default
    filters hide: importing the old module there printed nothing at all. A
    gate raising `SyntaxWarning` alone passes it on that leg, so both
    categories are raised.
  * `tools/run_tests.py` prints a module's output only when the module fails
    or under `-v`, so a warning from a passing module went nowhere.

The warning was the smaller defect. `\b` IS an escape, a backspace, so the
first docstring's `__doc__` read `Git<BS>in<BS>ash.exe` and the second
`System32<BS>ash.exe`. The path `help()` showed was not the path in the
source. A raw string is the fix because it keeps the source text and makes
`__doc__` agree with it. Doubling each backslash changes the text a reader of
the source sees.

`compile()` rather than `ast.parse()`, because some warnings come from the
compiler stage, which `ast.parse()` never reaches: `x is 1` warns under the
first and not the second (measured on 3.13, 2026-11-01).

Raised as an error, the first warning stops the compiler, so a red run names
the first defect in each file rather than every one. Before 3.13 the line it
names is where the STRING starts, and from 3.13 it is the line holding the
escape.
"""

import os
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every `.py` under these is compiled, and so is each file named beside them.
# `main.py` is the entry point the installer freezes, and the one tracked
# source outside the three directories.
SWEPT_DIRS = ("app", "tests", "tools")
SWEPT_FILES = ("main.py",)

# SyntaxWarning from 3.12 on, DeprecationWarning on 3.11, for the same defect.
RAISED = (SyntaxWarning, DeprecationWarning)

# 160 files on the day this was written. The floor is what makes an empty or
# misdirected walk fail instead of reporting a clean tree it never read.
FLOOR = 100

# One file from each swept location, plus the one that carried the defect.
ANCHORS = ("app/__init__.py", "main.py", "tests/test_drc_ref_resolution.py",
           "tools/run_tests.py")


def _sources():
    """Repository-relative, `/`-separated path of every file the gate compiles."""
    found = []
    for top in SWEPT_DIRS:
        for d, dirs, names in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            found.extend(os.path.join(d, n) for n in names if n.endswith(".py"))
    found.extend(os.path.join(ROOT, f) for f in SWEPT_FILES
                 if os.path.isfile(os.path.join(ROOT, f)))
    return sorted(os.path.relpath(p, ROOT).replace(os.sep, "/") for p in found)


def _complaint(source, filename):
    """What the compiler raises about `source` with warnings as errors, or None.

    The compiler converts a warning raised as an error into a `SyntaxError`
    carrying the line. A warning that arrives unconverted, or a source that
    cannot compile at all, is a finding too: either way the file is not clean.
    """
    with warnings.catch_warnings():
        for category in RAISED:
            warnings.simplefilter("error", category)
        try:
            compile(source, filename, "exec", dont_inherit=True)
        except (SyntaxError, ValueError, Warning) as e:
            line = getattr(e, "lineno", None)
            msg = getattr(e, "msg", None) or str(e)
            return f"{filename}:{line}: {type(e).__name__}: {msg}"
    return None


def _sweep():
    """`(found, checked, unreadable, findings)` over the swept tree.

    Three outcomes per file, never two: compiled clean, compiled with a
    complaint, or never compiled because it could not be read.
    """
    found = _sources()
    checked, unreadable, findings = 0, [], []
    for rel in found:
        try:
            with open(os.path.join(ROOT, rel), "rb") as fh:
                source = fh.read()
        except OSError as e:
            unreadable.append(f"{rel}: {e}")
            continue
        checked += 1
        complaint = _complaint(source, rel)
        if complaint:
            findings.append(complaint)
    return found, checked, unreadable, findings


class TestTheSweepFindsTheTree(unittest.TestCase):
    """The gate's own premise. A walk that found nothing reports no warnings."""

    def test_every_swept_location_is_found(self):
        found = _sources()
        self.assertGreaterEqual(
            len(found), FLOOR,
            f"the walk found {len(found)} source files, under the floor of "
            f"{FLOOR}, so the check below would pass over a tree it never read")
        for top in SWEPT_DIRS:
            self.assertTrue(any(p.startswith(top + "/") for p in found),
                            f"no .py found under {top}/, so it is not swept")
        for anchor in ANCHORS:
            self.assertIn(anchor, found)


class TestEverySourceCompilesWithoutAWarning(unittest.TestCase):

    def test_no_source_draws_a_compiler_warning(self):
        found, checked, unreadable, findings = _sweep()
        # Floored on what was CHECKED, not only on what was found: a loop that
        # skips past every file can find plenty and compile none.
        self.assertGreaterEqual(checked, FLOOR,
                                f"{checked} files compiled of {len(found)} found")
        self.assertEqual(unreadable, [],
                         "these were found and never compiled, so this run "
                         "cannot say they are clean:\n" + "\n".join(unreadable))
        self.assertEqual(checked, len(found))
        self.assertEqual(
            findings, [],
            f"{len(findings)} of {checked} files draw a warning from the "
            f"compiler, the first in each shown here. For an invalid escape in "
            f"a docstring or a Windows path, make it a raw string (r\"\"\"...)."
            f"\n" + "\n".join(findings))


class TestTheCompileCatchesTheDefect(unittest.TestCase):
    """Calibrated in both directions on the interpreter running the suite, so
    each leg of the matrix proves the gate can fire there, 3.11 included."""

    # Assembled rather than written, so this module holds no invalid escape of
    # its own and the sweep above can include it without a waiver.
    _PATH = "C:" + "\\" + "Program Files" + "\\" + "Git"
    _PLAIN = 'def f():\n    """Maps to %s."""\n' % _PATH
    _RAW = 'def f():\n    r"""Maps to %s."""\n' % _PATH

    def test_the_calibration_source_is_the_defect(self):
        self.assertIn("\\P", self._PLAIN)
        self.assertEqual(self._PLAIN.count("\\"), 2)

    def test_an_invalid_escape_in_a_docstring_IS_a_finding(self):
        complaint = _complaint(self._PLAIN.encode("utf-8"), "<calibration>")
        self.assertIsNotNone(
            complaint,
            "a docstring holding an invalid escape compiled clean, so this "
            "interpreter's warning for it is not raised by the gate")
        self.assertIn("invalid escape sequence", complaint)

    def test_the_same_docstring_as_a_raw_string_is_not(self):
        self.assertIsNone(_complaint(self._RAW.encode("utf-8"), "<calibration>"))


if __name__ == "__main__":
    unittest.main()
