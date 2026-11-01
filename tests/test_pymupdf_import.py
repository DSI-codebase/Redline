"""PyMuPDF is imported as ``pymupdf``, never through the deprecated ``fitz`` alias.

PyMuPDF 2.0 (2026-10-16) emits, on ``import fitz``::

    FutureWarning: The `fitz` API is deprecated and will be removed in future.
    Use `import pymupdf` instead.

``requirements.txt`` says ``PyMuPDF>=1.25``, unpinned above, so the first tag
build after a release that drops the alias installs that release, and
``import fitz`` then fails at launch: ``app/model/storage.py`` is on the launch
path through ``app/config.py``. Every import was renamed on 2026-10-31. The
floor needs no change for this: ``pymupdf`` is importable from 1.24.3
(measured that day, and 1.24.2 ships ``fitz`` alone).

The sweep reads **code**, never text. Comments and docstrings here and across
the suite name the alias while explaining exactly this, so a regex over source
finds the words in prose and calls it a regression. ``TestTheSweepReadsCode``
proves the distinction on the repository's own files rather than asserting it.

``import pymupdf as fitz`` is not a finding: it imports ``pymupdf``, which is
the whole requirement, and only the local name is old.
"""

from __future__ import annotations

import ast
import io
import pathlib
import tokenize
import unittest
import warnings

REPO = pathlib.Path(__file__).resolve().parent.parent

#: Every place the app's own Python lives. Named rather than ``REPO.rglob``,
#: because a contributor's virtualenv inside the clone holds third-party code
#: (pdf2docx imports the alias in twelve files) that is not this repository's.
ROOTS = ("app", "tools", "tests")
FILES = ("main.py", "packaging/DSI_Redline.spec")

ALIAS = "fitz"


def _is_alias(name: str | None) -> bool:
    return name is not None and (name == ALIAS or name.startswith(ALIAS + "."))


def _parse(source: str, filename: str = "<string>") -> ast.Module:
    # A swept file with an invalid escape in a docstring repeats its warning
    # into this module's output when compiled here. That file's to fix.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source, filename=filename)


def _swept() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for root in ROOTS:
        out.extend(sorted((REPO / root).rglob("*.py")))
    out.extend(REPO / f for f in FILES if (REPO / f).exists())
    return out


def alias_imports(source: str, filename: str = "<string>") -> list[int]:
    """Line numbers where ``source`` imports the ``fitz`` module.

    Three spellings: ``import fitz`` (alone, in a list, or ``as`` anything),
    ``from fitz import ...``, and a constant-string ``importlib.import_module``
    or ``__import__``. A relative ``from .fitz import`` is a local module, not
    PyMuPDF, and is not one. Raises ``SyntaxError`` rather than returning
    ``[]``: a file this cannot parse is a file it has not checked.
    """
    tree = _parse(source, filename)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_alias(a.name) for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if not node.level and _is_alias(node.module):
                lines.append(node.lineno)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            arg = node.args[0]
            if (name in ("import_module", "__import__")
                    and isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    and _is_alias(arg.value)):
                lines.append(node.lineno)
    return sorted(lines)


def pymupdf_imports(source: str) -> int:
    """How many ``import pymupdf`` statements ``source`` holds. The floor's count."""
    n = 0
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Import):
            n += sum(a.name == "pymupdf" for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module == "pymupdf" and not node.level:
            n += 1
    return n


class TestNoModuleImportsTheFitzAlias(unittest.TestCase):

    def test_nothing_imports_fitz(self):
        found, unreadable, checked = [], [], 0
        for path in _swept():
            rel = path.relative_to(REPO).as_posix()
            try:
                lines = alias_imports(path.read_text(encoding="utf-8"), rel)
            except (SyntaxError, UnicodeDecodeError) as exc:
                unreadable.append(f"{rel}: {exc.__class__.__name__}")
                continue
            checked += 1
            found.extend(f"{rel}:{n}" for n in lines)
        # Three numbers, never two: a file that did not parse was not checked,
        # and folding it into "clean" is a pass that never ran.
        self.assertEqual(unreadable, [], "could not parse, so not checked")
        self.assertGreater(
            checked, 50,
            f"only {checked} files checked. The sweep is not reaching app/, "
            "tools/ and tests/, so an empty finding below measures nothing.")
        self.assertEqual(
            found, [],
            "these import PyMuPDF through the deprecated `fitz` alias. "
            "PyMuPDF 2.0 warns on it and a later release removes it, and "
            "requirements.txt's unpinned PyMuPDF>=1.25 installs that release "
            "into the next tag build. Write `import pymupdf` and rename the "
            "uses, or `import pymupdf as fitz` where that is not worth it.")

    def test_the_app_imports_pymupdf_where_it_used_the_alias(self):
        # The floor. "Nothing imports fitz" holds just as well for a checkout
        # where PyMuPDF was removed, or for a sweep that parses nothing.
        storage = (REPO / "app" / "model" / "storage.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            pymupdf_imports(storage), 1,
            "app/model/storage.py, on the launch path through app/config.py, "
            "no longer imports pymupdf, so the gate above is asserting the "
            "absence of an alias nothing would use")
        importing = 0
        for path in _swept():
            try:
                importing += pymupdf_imports(path.read_text(encoding="utf-8")) > 0
            except (SyntaxError, UnicodeDecodeError):
                continue  # the sweep above reports it; counting it here is not checking it
        self.assertGreater(
            importing, 20,
            f"only {importing} files import pymupdf. The rename covered 65 on "
            "2026-10-31, so either the sweep lost its roots or PyMuPDF left "
            "the app, and both make the check above vacuous.")


class TestTheSweepReadsCode(unittest.TestCase):
    """Prose that names the alias is not an import, and an import is."""

    def test_the_repository_names_the_alias_in_prose(self):
        """Every line where a swept file has the words in a string or a comment.

        ``tokenize`` decides what is prose, independently of the ``ast`` reader
        under test, so a reader that matched text would report one of these
        lines. Lines where the words are CODE are left to the sweep above,
        which is what a real reintroduced import is.
        """
        needle = "import " + ALIAS
        prose = {}
        for path in _swept():
            src = path.read_text(encoding="utf-8")
            if needle not in src:
                continue
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.type in (tokenize.STRING, tokenize.COMMENT) and needle in tok.string:
                    rel = path.relative_to(REPO).as_posix()
                    first = tok.start[0]
                    for offset, line in enumerate(tok.string.splitlines()):
                        if needle in line:
                            prose.setdefault(rel, set()).add(first + offset)
        # Without a real file whose TEXT has the words, nothing below is shown.
        self.assertTrue(
            prose,
            f"no swept file mentions `{needle}` in a string or a comment, so "
            "nothing shows the sweep tells prose from code")
        for rel, lines in sorted(prose.items()):
            with self.subTest(rel):
                hit = set(alias_imports((REPO / rel).read_text(encoding="utf-8"), rel))
                self.assertEqual(
                    sorted(hit & lines), [],
                    f"{rel} names `{needle}` in prose on these lines and the "
                    "sweep reported an import there: the reader is matching text")

    def test_a_docstring_and_a_comment_are_not_findings(self):
        source = (
            '"""Use pymupdf. Never write: import fitz"""\n'
            "# from fitz import Rect\n"
            "s = 'import fitz'\n"
            "import pymupdf\n"
            "import pymupdf as fitz\n"
            "from .fitz import local_module\n"
        )
        self.assertEqual(alias_imports(source), [])

    def test_every_spelling_of_a_real_import_is_a_finding(self):
        cases = {
            "import fitz\n": [1],
            "import os, fitz\n": [1],
            "import fitz as pdf\n": [1],
            "import fitz.utils\n": [1],
            "from fitz import Rect\n": [1],
            "from fitz.utils import getColor\n": [1],
            "def f():\n    import fitz\n": [2],
            "class C:\n    def m(self):\n        from fitz import open\n": [3],
            "import importlib\nm = importlib.import_module('fitz')\n": [2],
            "m = __import__('fitz')\n": [1],
            "try:\n    import fitz\nexcept ImportError:\n    fitz = None\n": [2],
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(alias_imports(source), expected)

    def test_a_file_that_does_not_parse_is_refused(self):
        with self.assertRaises(SyntaxError):
            alias_imports("import fitz\ndef broken(:\n")


if __name__ == "__main__":
    unittest.main()
