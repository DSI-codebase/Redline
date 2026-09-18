"""The notices must reach the user, not just the repository.

`THIRD-PARTY-NOTICES.md` at the repo root satisfies nothing for somebody who
downloads the installer. MIT, BSD and the LGPL all require the notice to travel
with the **distributed form**, and this build has two of them -- the Inno
installer and the portable zip -- both packaged from `dist/DSI Redline/*`. So
the files go into the PyInstaller `datas`, which is the one place that reaches
both, and this asserts they are still there.

**Parsed with `ast`, never with a regex over the source.** The spec carries a
comment explaining exactly why those files are bundled, and that comment names
both of them -- so a text search for `THIRD-PARTY-NOTICES.md` in the spec passes
with the entry deleted and the comment left behind. That is the inverted dead
gate this repository family has paid for repeatedly, and it is avoidable here by
reading the assignment rather than the page.

This cannot prove the built artifact contains them -- PyInstaller runs on
Windows and nothing here does. It proves the declaration, which is the half that
is checkable locally and the half that gets deleted by accident.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
SPEC = REPO / "packaging" / "DSI_Redline.spec"
NOTICES = REPO / "THIRD-PARTY-NOTICES.md"
LICENSES = REPO / "licenses"


def _datas_strings() -> list[str]:
    """Every string literal in the spec's `datas` assignment, comments gone.

    `ast` drops comments entirely, which is the property being relied on.
    """
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "datas" in names:
                return [n.value for n in ast.walk(node.value)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return []


class TestTheNoticesAreBundled(unittest.TestCase):

    def test_the_notices_file_exists_and_says_something(self) -> None:
        self.assertTrue(NOTICES.is_file(), "THIRD-PARTY-NOTICES.md is missing")
        text = NOTICES.read_text(encoding="utf-8")
        self.assertGreater(len(text), 2000,
                           "the notices file is too short to be a real audit")
        # The load-bearing finding: PyMuPDF's arm is unresolved and the file
        # must keep saying so rather than quietly reading as settled.
        self.assertIn("AGPL", text,
                      "the notices no longer record the PyMuPDF AGPL arm")

    def test_the_licence_texts_the_packages_do_not_ship_are_supplied(self) -> None:
        """PySide6 and shiboken6 ship no licence file of their own -- measured
        on the 6.11.2 wheels, zero LICENSE/COPYING/NOTICE entries in either
        distribution. The LGPL requires the text to accompany the binary, so
        this project supplies it; if that file goes, the installer ships LGPL
        code with no LGPL text.

        And LGPL-3.0 incorporates GPL-3.0 **by reference**, so the LGPL text
        alone is an incomplete notice -- which is why the pair is asserted
        together rather than one at a time.
        """
        self.assertTrue(LICENSES.is_dir(), "licenses/ is missing")
        for name, heading in (("LGPL-3.0.txt", "GNU LESSER GENERAL PUBLIC LICENSE"),
                              ("GPL-3.0.txt", "GNU GENERAL PUBLIC LICENSE")):
            with self.subTest(name):
                path = LICENSES / name
                self.assertTrue(path.is_file(),
                                f"{name} -- a licence text nothing else supplies is gone")
                body = path.read_text(encoding="utf-8")
                self.assertIn(heading, body)
                self.assertIn("Version 3, 29 June 2007", body)
                # Verbatim, not reflowed. The FSF ships these hard-wrapped with
                # "(C)"; a rendered copy (paragraphs unwrapped onto single
                # lines, "(c) 2007" as the © glyph) is the same licence and is
                # not the document the FSF publishes, which is the only thing
                # "verbatim" can mean on a public repository's notices.
                self.assertIn("Copyright (C) 2007 Free Software Foundation", body,
                              f"{name} is not the FSF's own wording")
                self.assertGreater(len(body.splitlines()), 150,
                                   f"{name} looks reflowed or truncated")

    def test_every_licence_file_is_named_in_the_notices_and_the_reverse(self) -> None:
        """A rule, not the four files that happened to be there.

        Two ways this drifts and each is silent: a text added to `licenses/`
        that the notices' table never lists (so a reader cannot tell what it
        covers or why it ships), and a row naming a file that is not there (so
        the notices promise a text the installer does not carry). Both are
        checked, because a list gated in one direction covers half of what it
        is for.

        **It reads the TABLE, not the document**, and the first draft did not.
        Asserting `licenses/<name>` appears anywhere in the notices passed with
        the table row deleted, because the prose above it explains where the
        GPL text came from and necessarily names the file -- the gate satisfied
        by the paragraph explaining the thing, which this repository has paid
        for more than once. A row is `| \\`licenses/X\\` | what it covers |`,
        so that is what is parsed.
        """
        text = NOTICES.read_text(encoding="utf-8")
        on_disk = {p.name for p in LICENSES.iterdir() if p.is_file()}
        self.assertGreaterEqual(len(on_disk), 4,
                                f"licenses/ holds only {sorted(on_disk)} -- an empty "
                                "sweep would pass every assertion below")
        rows = dict(re.findall(r"^\|\s*`licenses/([^`]+)`\s*\|\s*(.+?)\s*\|\s*$",
                               text, re.M))
        self.assertTrue(rows, "the notices' licence table has no rows at all")
        for name in sorted(on_disk):
            with self.subTest(name):
                self.assertIn(name, rows,
                              f"{name} ships and no table row says what it covers")
                self.assertTrue(rows[name].strip(),
                                f"{name}'s row says nothing")
        missing = sorted(set(rows) - on_disk)
        self.assertFalse(missing,
                         f"the notices name {missing}, which the installer would not carry")

    def test_the_spec_bundles_the_notices_into_the_distributed_form(self) -> None:
        strings = _datas_strings()
        self.assertTrue(strings, "no `datas` assignment found in the spec")
        joined = " ".join(strings)
        self.assertIn("THIRD-PARTY-NOTICES.md", joined,
                      "the notices are not bundled, so neither the installer "
                      "nor the portable zip carries them")
        self.assertIn("licenses", joined,
                      "the licences directory is not bundled")

    def test_the_check_reads_the_assignment_rather_than_the_comment(self) -> None:
        """The guard on the guard.

        The spec's comment names both files by design, so this asserts the
        extraction is genuinely blind to comments -- otherwise every assertion
        above passes over prose while the bundling is gone.
        """
        source = SPEC.read_text(encoding="utf-8")
        self.assertIn("# ", source, "the spec has no comments to be fooled by")
        stripped = ast.unparse(ast.parse(source))
        self.assertNotIn("#", stripped.split("THIRD-PARTY")[0][-200:],
                         "ast.unparse leaked a comment, which should be impossible")
        # And the real proof: the extraction finds it in the assignment.
        self.assertIn("THIRD-PARTY-NOTICES.md", " ".join(_datas_strings()))


if __name__ == "__main__":
    unittest.main()
