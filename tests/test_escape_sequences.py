r"""No Python source in this repository holds an invalid escape sequence.

``"C:\Program Files"`` in an ordinary string holds ``\P``, which is not an
escape. Python 3.12 and later report it as ``SyntaxWarning: invalid escape
sequence '\P'``, and the language reference says a future release will make it
a SyntaxError. This docstring is raw, which is the fix.

2026-11-01: two docstrings in ``tests/test_drc_ref_resolution.py``
(``_bash_candidates`` and ``_usable_bash``) held ``C:\Program Files\...`` and
``C:\Windows\...`` in ordinary strings, and a721ce1 made them raw. Nothing had
caught them, for three reasons, each measured on ea528ab that day:

  * ``tools/run_tests.py`` captures each module's output and prints it only
    when the module fails, so on a green run the warning reached no log.
  * The warning is emitted when the source is COMPILED, and a cached ``.pyc``
    skips compiling. On 3.13 the module's first run printed both warnings and
    its second run printed none.
  * 3.11 spells it ``DeprecationWarning``, which the default filters drop for
    an imported module, so 3.11 printed nothing even from a fresh cache. The
    Windows build, the PyMuPDF floor job and two of the six Tests legs run
    3.11.

So this gate compiles every source from its bytes, which no cache can skip,
and RECORDS what the compiler says:

  * **Recording, not** ``-W error``. Promoted to an error, the first invalid
    escape in a file raises and hides every later one. On a file holding five
    such literals, ``-W error`` reported one and recording reported five.
  * **Every category, not SyntaxWarning alone.** On ea528ab the same two
    escapes came back as two SyntaxWarnings on 3.12 and 3.13 and as two
    DeprecationWarnings on 3.11, so a SyntaxWarning-only gate passes on 3.11
    over the defect it exists for. ``compile`` runs no code, so anything it
    warns about is the text.
  * **Attributed to the file compiled**, never to ``warning.filename``. A
    constant-folding warning (3.13's ``~`` on a bool) arrives filed under the
    caller of ``compile`` rather than the source that holds it.
  * **A file that does not compile, or cannot be read, is its own state**,
    counted and reported beside the findings rather than folded into "no
    warnings".

The walk covers every ``.py`` under the repository root and the PyInstaller
``.spec``, which the build runs as Python. It prunes ``.git``, and any
directory holding ``pyvenv.cfg``: ``.gitignore`` names three virtual
environment locations inside the checkout, and an environment there holds
other people's code. Pruned by that file, which is what makes a directory an
environment (PEP 405), never by a list of directory names.

**Floored**, because an absence assertion agrees with an empty checkout. The
walk found 161 sources on 2026-11-01 before this module existed, so a floor of
100 fires on an empty or partial walk and leaves room to delete.

Two limits, stated rather than discovered later:

  * **One finding per literal.** The compiler reports the first invalid escape
    in each string and stops there. A raw prefix clears the rest with it.
  * **A VALID escape is silent.** ``"C:\bin\tools"`` compiles to a backspace
    and a tab with no warning, which is the shape
    ``docs/records/the-account-the-pin-and-the-shell.md`` met. This gate
    catches a Windows path only through an invalid escape beside it, as
    ``\P`` in ``C:\Program Files``. Raw strings for any Windows path stay the
    rule, and ``test_a_valid_escape_is_silent`` holds this paragraph true.
"""

import functools
import os
import tempfile
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SOURCE_SUFFIXES = (".py", ".spec")
_FLOOR = 100


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _sources(root):
    """Every Python source under ``root``, as absolute paths in walk order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d != ".git"
            and not os.path.isfile(os.path.join(dirpath, d, "pyvenv.cfg")))
        for name in sorted(filenames):
            if name.endswith(_SOURCE_SUFFIXES):
                yield os.path.join(dirpath, name)


def _compile(source, filename):
    """``(warned, error)`` from compiling ``source``.

    ``warned`` is ``[(line, category, message)]`` for every warning the
    compiler emitted, with ``line`` None when the warning was filed under
    another file. ``error`` is the exception when it did not compile.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(source, filename, "exec", dont_inherit=True)
            error = None
        except (SyntaxError, ValueError) as exc:
            error = exc
    warned = [(w.lineno if w.filename == filename else None,
               w.category.__name__, str(w.message)) for w in caught]
    return warned, error


@functools.lru_cache(maxsize=None)
def sweep(root):
    """``(found, findings, broken, unread)`` for every source under ``root``.

    ``findings`` is ``[(path, line, category, message)]``; ``broken`` and
    ``unread`` are ``[(path, reason)]`` for a source that did not compile and
    one that could not be read.
    """
    found, findings, broken, unread = 0, [], [], []
    for path in _sources(root):
        found += 1
        rel = _rel(path, root)
        try:
            with open(path, "rb") as fh:
                source = fh.read()
        except OSError as exc:
            unread.append((rel, f"{type(exc).__name__}: {exc}"))
            continue
        warned, error = _compile(source, path)
        findings.extend((rel, line, cat, msg) for line, cat, msg in warned)
        if error is not None:
            broken.append((rel, f"{type(error).__name__}: {error}"))
    return found, tuple(findings), tuple(broken), tuple(unread)


def _tally(root):
    found, _, broken, unread = sweep(root)
    compiled = found - len(broken) - len(unread)
    return (f"{found} sources found, {compiled} compiled, {len(broken)} did "
            f"not compile, {len(unread)} could not be read")


class TestTheWalkFindsTheRepository(unittest.TestCase):
    """The gate's own premise. The class below asserts an absence, and an
    absence is what an empty walk reports."""

    def test_the_walk_finds_and_compiles_the_sources(self):
        found, _, broken, unread = sweep(ROOT)
        compiled = found - len(broken) - len(unread)
        self.assertGreater(
            found, _FLOOR,
            f"the walk found {found} sources under {ROOT}; every check in "
            "this file would now pass over an empty list")
        self.assertGreater(
            compiled, _FLOOR,
            f"{_tally(ROOT)}: the walk found sources and compiled almost none "
            "of them, so 'no warnings' measured nothing")

    def test_the_walk_reaches_each_kind_of_source(self):
        """One of each place a source lives, the module this gate was written
        for, and this module, so the gate sweeps itself."""
        found = {_rel(p, ROOT) for p in _sources(ROOT)}
        for expected in ("main.py", "app/__init__.py", "tools/run_tests.py",
                         "packaging/DSI_Redline.spec",
                         "tests/test_drc_ref_resolution.py",
                         "tests/test_escape_sequences.py"):
            with self.subTest(expected):
                self.assertIn(expected, found)


class TestNoSourceHasAnInvalidEscape(unittest.TestCase):

    def test_every_source_compiles_without_a_warning(self):
        _, findings, _, _ = sweep(ROOT)
        lines = "\n".join(f"  {path}:{line or '?'}: {cat}: {msg}"
                          for path, line, cat, msg in findings)
        self.assertEqual(
            list(findings), [],
            f"\n{lines}\n{_tally(ROOT)}. The compiler warned about the text "
            "above. For an invalid escape, make the string raw (an r prefix) "
            "or double each backslash. Python 3.12 and later report this as "
            "a SyntaxWarning that tools/run_tests.py shows only when a module "
            "fails, and a future Python makes it a SyntaxError.")

    def test_every_source_compiles(self):
        _, _, broken, unread = sweep(ROOT)
        self.assertEqual(
            list(broken) + list(unread), [],
            f"{_tally(ROOT)}. A source this interpreter cannot compile or "
            "read was not checked for escapes, and is not a pass.")


class TestTheCompilerReportsWhatThisGateReads(unittest.TestCase):
    """Calibrated against the interpreter running it, because the category
    moved between 3.11 and 3.12. Each source below is a raw literal, so this
    module stays clean under its own sweep without a waiver."""

    @staticmethod
    def _escapes(source):
        warned, error = _compile(source, "<calibration>")
        messages = [msg for _, _, msg in warned]
        if error is not None:
            messages.append(str(error))
        return [m for m in messages if "invalid escape sequence" in m]

    def test_a_non_raw_windows_path_IS_a_finding(self):
        found = self._escapes(r'p = "C:\Program Files\Git\bin\bash.exe"' "\n")
        self.assertEqual(len(found), 1, found)

    def test_the_same_path_raw_is_not(self):
        self.assertEqual(
            self._escapes(r'p = r"C:\Program Files\Git\bin\bash.exe"' "\n"), [])

    def test_a_docstring_is_a_literal_here(self):
        """The shape that happened. The POSIX device path gate excludes
        docstrings because describing a path is not opening it. The compiler
        does not draw that line, so this gate must not."""
        source = r'''def f():
    """Tried first: C:\Windows\System32\bash.exe."""
'''
        self.assertEqual(len(self._escapes(source)), 1)

    def test_every_literal_is_reported_not_only_the_first(self):
        """Why the gate records rather than running under ``-W error``."""
        source = r'''a = "C:\Program Files"
b = "C:\Windows"
c = b"C:\Users"
'''
        self.assertEqual(len(self._escapes(source)), 3)

    def test_a_valid_escape_is_silent(self):
        """The stated limit in the module docstring, held true."""
        self.assertEqual(self._escapes(r'p = "C:\bin\tools"' "\n"), [])


class TestTheWalkPrunesByStructure(unittest.TestCase):

    def test_git_and_an_environment_are_pruned_and_nothing_else(self):
        """``env/`` is a name ``.gitignore`` lists, and without
        ``pyvenv.cfg`` it is walked, so the prune is the file and not the
        name."""
        layout = {
            "a.py": "",
            "notes.txt": "",
            "packaging/b.spec": "",
            "env/c.py": "",
            ".git/hooks/d.py": "",
            ".venv/pyvenv.cfg": "home = /usr/bin\n",
            ".venv/lib/e.py": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for rel, body in layout.items():
                path = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(body)
            walked = sorted(_rel(p, tmp) for p in _sources(tmp))
        self.assertEqual(walked, ["a.py", "env/c.py", "packaging/b.spec"])


if __name__ == "__main__":
    unittest.main()
