"""PDF→Word: pdf2docx imports PyMuPDF as `fitz`, and the dialog names what failed.

Measured 2026-10-31 on Python 3.11, PyMuPDF 2.0 and pdf2docx 0.5.13, from a
fresh `pip install -r requirements.txt`:

* every pdf2docx release on PyPI, 0.5.0 to 0.5.13, imports `fitz` and none
  imports `pymupdf` (11 files through 0.5.8, 12 from 0.5.9), and upstream
  master does too. `pdf2docx/converter.py:9` is one of them, and the package
  `__init__` imports it, so `import pdf2docx` needs `fitz`;
* PyMuPDF 2.0 emits "The `fitz` API is deprecated and will be removed in
  future" on that import, and names no release that removes it;
* with `fitz` refused by a meta-path finder, `import pdf2docx` raises
  `ModuleNotFoundError: No module named 'fitz'`, and `ConvertDialog` answered
  that with "PDF→Word needs the 'pdf2docx' package (pip install pdf2docx)", so
  a user who had pdf2docx installed was told to install it.

`app.tools.pdf_ops.import_pdf2docx` binds the names pdf2docx imports to
`pymupdf` first (the owner's choice over a PyMuPDF ceiling), and
`app.tools.dialogs.pdf2docx_problem` reports the ImportError's own `name`.

The blocker is the one `tests/test_qt_absent_degrades.py` uses for PySide6,
raising what importlib raises for an absent module. It goes in AFTER the app's
modules have loaded, and evicts what they cached, because Redline's own modules
still `import fitz` at module scope at this commit and would not load under it.
From that point on `import fitz` finds nothing, which is the state a PyMuPDF
without the alias leaves.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from tests._qt import QT_OK, REASON as QT_REASON

ROOT = Path(__file__).resolve().parent.parent

_HAVE_PDF2DOCX = importlib.util.find_spec("pdf2docx") is not None
_PDF2DOCX_REASON = "pdf2docx is not installed, so there is no import of it to break"

# What an installed pdf2docx is told. Asserted verbatim, so a rewording that
# loses the install command fails here rather than in a user's message box.
_INSTALL_IT = "PDF→Word needs the 'pdf2docx' package (pip install pdf2docx)."

_PRELUDE = textwrap.dedent("""
    import json, os, sys, tempfile

    def block(*tops, name=True, message=None):
        # Refuse every import under TOPS from here on. With name=True this
        # raises what importlib raises for an absent module, carrying `name`;
        # with name=False an ImportError with no name, the shape a C
        # extension's own failure takes.
        for key in [k for k in sys.modules if k.split(".")[0] in tops]:
            del sys.modules[key]
        class _Refuse:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in tops:
                    if name:
                        raise ModuleNotFoundError(
                            f"No module named {fullname!r}", name=fullname)
                    raise ImportError(message or f"{fullname} failed to load")
        sys.meta_path.insert(0, _Refuse())

    def report(**kw):
        print(json.dumps(kw))
""")

_DIALOG = textwrap.dedent("""
    from PySide6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([])
    import app.tools.dialogs as dlg

    def dialog(src="in.pdf", out="out.docx"):
        d = dlg.ConvertDialog("PDF → Word", None, src)
        d.out.setText(out)
        return d

    def shown_message(d):
        # Press Run and return what the warning box would have said, through
        # the dialog's own handler rather than by calling build_task.
        seen = []
        class _Box:
            @staticmethod
            def warning(parent, title, text):
                seen.append(text)
        dlg.QMessageBox = _Box
        d._on_run()
        return seen
""")


def _run(body: str, *, qt: bool) -> dict:
    src = _PRELUDE + (_DIALOG if qt else "") + textwrap.dedent(body)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", src], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not r.stdout.strip():
        raise AssertionError(
            f"the scenario itself died (exit {r.returncode}):\n{r.stderr[-3000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(_HAVE_PDF2DOCX, _PDF2DOCX_REASON)
class TestTheDefectReproduces(unittest.TestCase):
    """Falsify the instrument before believing anything it says.

    The alias tests below pass trivially over a blocker that does not block,
    or over a pdf2docx that no longer imports `fitz`.
    """

    def test_fitz_really_is_unimportable_under_the_blocker(self):
        got = _run("""
            import fitz  # loads here, as the app's own modules load it
            block("fitz")
            try:
                import fitz
                report(blocked=False)
            except ModuleNotFoundError as exc:
                report(blocked=True, name=exc.name)
        """, qt=False)
        self.assertEqual(got, {"blocked": True, "name": "fitz"})

    def test_pdf2docx_cannot_import_without_fitz(self):
        got = _run("""
            block("fitz")
            try:
                import pdf2docx
                report(error=None)
            except ImportError as exc:
                report(error=type(exc).__name__, name=exc.name)
        """, qt=False)
        if got["error"] is None:
            self.fail(
                "the installed pdf2docx imported with `fitz` refused, so it no "
                "longer needs the alias: `_fitz_aliases` in app/tools/pdf_ops.py "
                "can go, and requirements.txt's pdf2docx floor can rise to this "
                "release")
        self.assertEqual(got, {"error": "ModuleNotFoundError", "name": "fitz"})


@unittest.skipUnless(QT_OK, QT_REASON)
@unittest.skipUnless(_HAVE_PDF2DOCX, _PDF2DOCX_REASON)
class TestTheAliasCarriesPdfToWord(unittest.TestCase):
    def test_a_pdf_converts_with_fitz_refused(self):
        """Converted, not merely imported: pdf2docx calls `fitz` at run time too."""
        got = _run("""
            import pymupdf
            block("fitz")
            tmp = tempfile.mkdtemp()
            src, out = os.path.join(tmp, "in.pdf"), os.path.join(tmp, "out.docx")
            doc = pymupdf.open()
            doc.new_page().insert_text((72, 72), "REDLINE PDF2DOCX 4471")
            doc.save(src)
            doc.close()
            fn = dialog(src, out).build_task()
            fn(None, None)
            import docx
            text = "\\n".join(p.text for p in docx.Document(out).paragraphs)
            report(fitz_is_pymupdf=sys.modules.get("fitz") is pymupdf,
                   wrote=os.path.getsize(out) > 0, text=text)
        """, qt=True)
        self.assertTrue(got["fitz_is_pymupdf"], got)
        self.assertTrue(got["wrote"], got)
        self.assertIn("REDLINE PDF2DOCX 4471", got["text"])


@unittest.skipUnless(QT_OK, QT_REASON)
@unittest.skipUnless(_HAVE_PDF2DOCX, _PDF2DOCX_REASON)
class TestTheMessageNamesWhatFailed(unittest.TestCase):
    def test_fitz_is_named_when_nothing_aliases_it(self):
        """The defect as it was found: pdf2docx installed, `fitz` gone.

        `_fitz_aliases` is emptied so the alias cannot rescue the import, which
        is the state on any change that drops it.
        """
        got = _run("""
            dlg.ops._fitz_aliases = lambda: {}
            block("fitz")
            report(seen=shown_message(dialog()))
        """, qt=True)
        self.assertEqual(len(got["seen"]), 1, got)
        msg = got["seen"][0]
        self.assertIn("'fitz'", msg)
        self.assertNotIn("pip install", msg)

    def test_a_module_pdf2docx_needs_is_named(self):
        got = _run("""
            block("cv2")
            report(seen=shown_message(dialog()))
        """, qt=True)
        self.assertEqual(len(got["seen"]), 1, got)
        msg = got["seen"][0]
        self.assertIn("'cv2'", msg)
        self.assertNotIn("pip install", msg)

    def test_a_nameless_import_error_reports_its_own_text(self):
        got = _run("""
            block("cv2", name=False, message="numpy.core.multiarray failed to import")
            report(seen=shown_message(dialog()))
        """, qt=True)
        self.assertEqual(len(got["seen"]), 1, got)
        msg = got["seen"][0]
        self.assertIn("ImportError: numpy.core.multiarray failed to import", msg)
        self.assertNotIn("pip install", msg)

    def test_an_absent_pdf2docx_is_told_to_install_it(self):
        got = _run("""
            block("pdf2docx")
            report(seen=shown_message(dialog()))
        """, qt=True)
        self.assertEqual(got["seen"], [_INSTALL_IT])


@unittest.skipUnless(_HAVE_PDF2DOCX, _PDF2DOCX_REASON)
class TestTheAliasCoversWhatPdf2docxUses(unittest.TestCase):
    """Read the INSTALLED pdf2docx, not a list of what 0.5.13 used.

    A release that adds `from fitz.table import ...` fails here, where the
    alias would otherwise leave that one import to whatever `fitz` resolves to.
    """

    def test_every_fitz_name_pdf2docx_uses_is_bound(self):
        from app.tools import pdf_ops
        aliases = pdf_ops._fitz_aliases()

        spec = importlib.util.find_spec("pdf2docx")
        root = Path(next(iter(spec.submodule_search_locations)))
        files = sorted(root.rglob("*.py"))
        modules, from_names, attrs = set(), set(), set()
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            bound = {"fitz"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.split(".")[0] == "fitz":
                            modules.add(a.name)
                            if a.asname:
                                bound.add(a.asname)
                elif (isinstance(node, ast.ImportFrom) and node.level == 0
                      and node.module and node.module.split(".")[0] == "fitz"):
                    modules.add(node.module)
                    from_names.update((node.module, a.name) for a in node.names)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id in bound):
                    attrs.add(node.attr)

        # Floors on what was CHECKED and what was FOUND: a scan that read no
        # files, or found no `fitz`, agrees with every assertion below.
        self.assertGreaterEqual(len(files), 10, f"read only {len(files)} files under {root}")
        self.assertTrue(modules, "found no `fitz` import in pdf2docx: if it has "
                                 "moved to `pymupdf`, the alias can go")

        self.assertEqual(sorted(modules - aliases.keys()), [],
                         "pdf2docx imports a `fitz` module the alias does not bind")
        self.assertEqual(
            sorted(f"{m}.{n}" for m, n in from_names if not hasattr(aliases[m], n)), [],
            "pdf2docx imports a name its bound module does not have")
        self.assertEqual(
            sorted(a for a in attrs if not hasattr(aliases["fitz"], a)), [],
            "pdf2docx uses a `fitz.<name>` that `pymupdf` does not have")


if __name__ == "__main__":
    unittest.main()
