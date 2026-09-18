"""Every test in this suite must be reachable, and reachable the same way.

Two ways a test module here silently runs fewer tests than it holds. Neither
is a failure -- both are a *smaller number*, which no runner reports as
anything.

**A misplaced ``if __name__ == "__main__"`` block hides everything below it
from a direct run.** ``python3 tests/test_requirements.py`` ran **3** tests
where ``python3 -m unittest tests.test_requirements`` ran **5**: the guard sat
at line 44 and ``TestVersionIsStatedOnce`` began at 48, so the two tests that
vanished were the version-drift gates -- the ones that exist because the
installer once sat at 1.4.0 while the app moved on. Four modules carried the
guard mid-file; in three of them it was harmless only because those modules
import ``app`` at module scope and cannot be run as scripts at all. That is
luck, not a design, and it is exactly the kind that expires.

**A Qt-dependent class without the ``skipUnless`` its siblings carry errors
instead of skipping.** ``tests/test_v14_audit_panel.py`` guards its PySide6
import into ``_QT_OK`` and decorates the classes that need it;
``TestRolledUpFindingOnScreen`` was missing one, so a machine without Qt got
``FAILED (errors=1, skipped=31)`` where it should get a clean skip. An error
is loud, which is better than the alternative -- but it is loud about the
wrong thing, and it makes a legitimately-skipping run look broken.

Both gates sweep **the artifact** rather than a list of the modules that had
the problem when this was written. A gate scoped to today's offenders covers
what was there when the list was made.
"""

import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def _modules():
    return sorted(n for n in os.listdir(HERE)
                  if n.startswith("test_") and n.endswith(".py"))


# Assembled rather than written, so this file contains no literal that matches
# what it searches for -- which is what lets the gate below sweep its own module
# without needing a waiver. A class-body comprehension cannot see class-level
# names, so these are module scope.
_DEV = "/" + "dev"
_POSIX_ONLY = tuple(f"{_DEV}/{n}" for n in ("null", "zero", "stdout", "stderr"))


def _tree(name):
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=name)


class TestTheSweepFindsSomething(unittest.TestCase):
    """The gate's own premise. Both checks below are 'nothing was wrong'
    assertions, and a sweep that has stopped finding modules reports exactly
    that while measuring nothing.
    """

    def test_the_module_scan_finds_the_suite(self):
        found = _modules()
        self.assertGreater(
            len(found), 20,
            "the module scan found almost nothing; every check in this file "
            "would now pass over an empty list")
        self.assertIn("test_requirements.py", found)
        self.assertIn("test_v14_audit_panel.py", found)


class TestNoTestIsHiddenByAMisplacedMainGuard(unittest.TestCase):
    def test_the_main_guard_is_the_last_thing_in_the_file(self):
        for name in _modules():
            with self.subTest(name):
                tree = _tree(name)
                guards = [n.lineno for n in tree.body
                          if isinstance(n, ast.If)
                          and ast.dump(n.test).count("__main__")]
                if not guards:
                    continue
                below = [n.name for n in tree.body
                         if isinstance(n, ast.ClassDef)
                         and n.lineno > min(guards)]
                self.assertEqual(
                    below, [],
                    f"{name}: the `if __name__ == \"__main__\"` guard at line "
                    f"{min(guards)} sits above {below} -- a direct run of this "
                    "file executes unittest.main() before those classes are "
                    "defined, and reports a smaller number with no error. "
                    "Move the guard to the end of the file.")


class TestNoClassUsesAGuardedImportWithoutSkipping(unittest.TestCase):
    """A name bound inside a ``try: import ...`` is absent when it fails.

    Limit, stated rather than discovered later: this reads **direct** use of
    such a name inside a class body. A class calling a module-level helper
    that uses one is not caught. Widening it means resolving calls, which is
    a different tool; the direct case is what fired here, on a class whose
    ``setUpClass`` calls ``QApplication.instance()`` on line two.

    **Calibrated before it was trusted, and its first draft cried wolf.**
    ``unittest.skipUnless`` sets ``__unittest_skip__`` on the class it
    decorates and a subclass **inherits it** -- measured, not assumed: a
    child of a skipped base reports ``OK (skipped=2)`` and
    ``Child.__unittest_skip__`` is ``True``. So ``test_v12_order.py``'s
    ``TestDrawNewOnce`` and ``TestStackingOrder`` are covered by the ``_Base``
    above them and the whole module skips cleanly (10 of 10). A gate that
    flags a working file is one nobody reads twice, so ancestry counts --
    within this module, which is where these bases live.
    """

    def _decorated(self, node, by_name):
        """Is this class skipped -- itself, or through a base in this file?"""
        seen = set()
        stack = [node]
        while stack:
            cls = stack.pop()
            if cls.name in seen:
                continue
            seen.add(cls.name)
            if any("skip" in ast.dump(d).lower() for d in cls.decorator_list):
                return True
            for base in cls.bases:
                if isinstance(base, ast.Name) and base.id in by_name:
                    stack.append(by_name[base.id])
        return False

    def _guarded_names(self, tree):
        names = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for stmt in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    for alias in stmt.names:
                        names.add((alias.asname or alias.name).split(".")[0])
        return names

    def test_a_class_touching_an_optional_import_carries_a_skip(self):
        for name in _modules():
            tree = _tree(name)
            guarded = self._guarded_names(tree)
            if not guarded:
                continue
            by_name = {n.name: n for n in tree.body
                       if isinstance(n, ast.ClassDef)}
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if self._decorated(node, by_name):
                    continue
                used = sorted({n.id for n in ast.walk(node)
                               if isinstance(n, ast.Name) and n.id in guarded})
                with self.subTest(f"{name}::{node.name}"):
                    self.assertEqual(
                        used, [],
                        f"{name}: {node.name} uses {used}, which is bound "
                        "inside a guarded import, and carries no skip "
                        "decorator -- without that dependency it raises "
                        "NameError instead of skipping. Its siblings in the "
                        "same file show the decorator to copy.")


class TestNoTestUsesAPosixOnlyDevicePath(unittest.TestCase):
    """A POSIX device path does not exist on Windows, and this suite runs there.

    It is a LATENT platform failure: green on every Linux leg, red on all three
    Windows ones, and the local suite cannot reach it -- the same shape as a
    leaked PyMuPDF handle, one aisle over. It cost a CI round. The degradation
    gate opened one for its runner's stream; on Windows that resolves to a
    directory that is not there, so the sweep subprocess died and the module
    reported FAILED while the seven modules it exists to check all reported
    `ok`.

    `io.StringIO()` needs no filesystem at all and is the portable answer;
    `os.devnull` is the other one. What fails is naming the path directly.

    TWO THINGS MAKE THIS GATE NOT FIRE ON ITSELF, AND NEITHER IS AN EXEMPTION.
    Its first draft flagged its own needle table and its own docstring, which is
    the shape this repo has paid for repeatedly -- and the standing answer is to
    tighten the check, never to waive the text explaining the thing.

      * the needles are ASSEMBLED rather than written, so this file contains no
        literal that matches them;
      * a docstring is not code. Bare string expressions are excluded
        structurally, which is a general statement about what counts rather
        than a carve-out for this module.

    Swept over the artifact, not over the one file that had it: there is exactly
    one occurrence today, and a gate scoped to it covers only what was broken
    the day it was written.
    """

    @staticmethod
    def _code_literals(tree):
        """Every string literal that is CODE -- docstrings and bare string
        expressions excluded, since neither is executed as a value."""
        prose = {id(n.value) for n in ast.walk(tree)
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        return [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and id(n) not in prose]

    def test_no_module_names_a_dev_path(self):
        for name in _modules():
            hits = sorted({lit for lit in self._code_literals(_tree(name))
                           if any(d in lit for d in _POSIX_ONLY)})
            with self.subTest(name):
                self.assertEqual(
                    hits, [],
                    f"{name} names {hits} in code. That path does not exist on "
                    f"Windows, which this suite runs on, so it is green locally "
                    f"and red only there. Use io.StringIO() for a discarded "
                    f"stream, or os.devnull for a real path.")

    def test_the_sweep_can_see_code_literals_at_all(self):
        """Without this, a walk that found nothing would read as a pass."""
        found = sum(len(self._code_literals(_tree(n))) for n in _modules())
        self.assertGreater(found, 100,
                           "almost no code string literals found across the "
                           "suite — the scan above cannot fail for the right "
                           "reason")

    def test_a_docstring_mentioning_one_is_not_a_finding(self):
        """The calibration that made the first draft honest: this very module's
        docstring describes the defect, and describing is not doing."""
        tree = ast.parse('"""mentions %s/null in prose."""\nx = 1\n' % _DEV)
        self.assertEqual(
            [l for l in self._code_literals(tree)
             if any(d in l for d in _POSIX_ONLY)], [])

    def test_a_real_use_IS_a_finding(self):
        tree = ast.parse('open("%s/null", "w")\n' % _DEV)
        self.assertTrue(
            [l for l in self._code_literals(tree)
             if any(d in l for d in _POSIX_ONLY)],
            "the scan does not see a path passed to a call, which is the "
            "only shape this defect has ever taken")


if __name__ == "__main__":
    unittest.main()
