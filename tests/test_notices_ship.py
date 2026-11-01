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
import importlib.util
import pathlib
import re
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
SPEC = REPO / "packaging" / "DSI_Redline.spec"
NOTICES = REPO / "THIRD-PARTY-NOTICES.md"
LICENSES = REPO / "licenses"

# The audit's list of packages whose wheel ships no license file, and the text
# at the top of licenses/ that covers each. Read from the tool rather than
# written here again, so the two cannot disagree about which packages have no
# directory of their own.
_spec = importlib.util.spec_from_file_location(
    "notices_audit", REPO / "tools" / "notices_audit.py")
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)


def _supplied_text(name: str, licenses: pathlib.Path, supplied: dict) -> pathlib.Path | None:
    """The hand-supplied text that covers ``name``, when the audit lists it and it is there."""
    for listed, (filename, _) in supplied.items():
        if _audit.normalize(listed) == _audit.normalize(name):
            path = licenses / filename
            return path if path.is_file() else None
    return None


def _entries_without_texts(entries, licenses: pathlib.Path, supplied: dict) -> list[str]:
    """Each entry that has neither ``licenses/<name>/`` holding a file nor a
    ``SUPPLIED_BY_HAND`` text that is there."""
    missing = []
    for name in sorted(entries):
        folder = licenses / name
        if folder.is_dir() and any(p.is_file() for p in folder.rglob("*")):
            continue
        if _supplied_text(name, licenses, supplied):
            continue
        missing.append(name)
    return missing


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


def _rows(text: str) -> dict[str, str]:
    """The licence table: `| \\`licenses/X\\` | what it covers |` -> {X: cover}."""
    return dict(re.findall(r"^\|\s*`licenses/([^`]+)`\s*\|\s*(.+?)\s*\|\s*$", text, re.M))


def _shipped_files() -> set[str]:
    """Every file under licenses/, as a path relative to it, at any depth."""
    return {p.relative_to(LICENSES).as_posix() for p in LICENSES.rglob("*") if p.is_file()}


def _package_entries(text: str) -> dict[str, list[str]]:
    """`#### <distribution> <version>` -> the quoted licence lines under it.

    Only an indented `> ` line is a quote from a licence file. A `> ` at column
    0 is this document's own callout prose. Any other heading ends the entry.
    """
    entries: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^#### (\S+) (\S+)\s*$", line)
        if heading:
            current = heading.group(1)
            entries[current] = []
        elif line.startswith("#"):
            current = None
        elif current and re.match(r"^\s+> ", line):
            entries[current].append(re.sub(r"^\s+> ", "", line))
    return entries


def _collapse(text: str) -> str:
    return " ".join(text.split())


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
        """PySide6 and shiboken6 ship no LGPL text of their own -- measured on
        the 6.11.2 wheels as zero LICENSE/COPYING/NOTICE entries, and on the
        6.11.3 wheels as one file, `LicenseRef-Qt-Commercial.txt`, eight lines
        addressed to commercial Qt licensees. The LGPL requires the text to
        accompany the binary, so this project supplies it; if that file goes,
        the installer ships LGPL code with no LGPL text.

        And LGPL-3.0 incorporates GPL-3.0 **by reference**, so the LGPL text
        alone is an incomplete notice -- which is why the pair is asserted
        together rather than one at a time.

        LGPL-2.1 is the third for the same reason: lxml's own `LICENSES.txt`
        says its binary wheels bundle iconv under `LGPL 2.1` and gives a URL
        rather than the text (measured on the 6.1.3 Windows wheel).
        """
        self.assertTrue(LICENSES.is_dir(), "licenses/ is missing")
        for name, heading, version, fsf in (
                ("LGPL-3.0.txt", "GNU LESSER GENERAL PUBLIC LICENSE",
                 "Version 3, 29 June 2007", "Copyright (C) 2007 Free Software Foundation"),
                ("GPL-3.0.txt", "GNU GENERAL PUBLIC LICENSE",
                 "Version 3, 29 June 2007", "Copyright (C) 2007 Free Software Foundation"),
                ("LGPL-2.1.txt", "GNU LESSER GENERAL PUBLIC LICENSE",
                 "Version 2.1, February 1999",
                 "Copyright (C) 1991, 1999 Free Software Foundation")):
            with self.subTest(name):
                path = LICENSES / name
                self.assertTrue(path.is_file(),
                                f"{name} -- a licence text nothing else supplies is gone")
                body = path.read_text(encoding="utf-8")
                self.assertIn(heading, body)
                self.assertIn(version, body)
                # Verbatim, not reflowed. The FSF ships these hard-wrapped with
                # "(C)"; a rendered copy (paragraphs unwrapped onto single
                # lines, "(c) 2007" as the © glyph) is the same licence and is
                # not the document the FSF publishes, which is the only thing
                # "verbatim" can mean on a public repository's notices.
                self.assertIn(fsf, body, f"{name} is not the FSF's own wording")
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

        **It walks the tree, not the top level**, and the first version did not.
        From the 2026-10-31 audit each bundled package's own files ship under
        `licenses/<distribution>/`, and a listing of `licenses/` that keeps only
        files would have checked the four top-level texts and none of the
        sixty-seven below them -- a lookup that stops finding, reading as
        clean. A row may name a directory (`licenses/numpy/`); it covers every
        file beneath it, and it must hold at least one.
        """
        text = NOTICES.read_text(encoding="utf-8")
        on_disk = _shipped_files()
        self.assertGreaterEqual(len(on_disk), 4,
                                f"licenses/ holds only {sorted(on_disk)} -- an empty "
                                "sweep would pass every assertion below")
        rows = _rows(text)
        self.assertTrue(rows, "the notices' licence table has no rows at all")
        for rel in sorted(on_disk):
            with self.subTest(rel):
                covering = [r for r in rows
                            if r == rel or (r.endswith("/") and rel.startswith(r))]
                self.assertTrue(covering,
                                f"{rel} ships and no table row says what it covers")
                for row in covering:
                    self.assertTrue(rows[row].strip(), f"{row}'s row says nothing")
        missing = sorted(r for r in rows
                         if r not in on_disk
                         and not (r.endswith("/") and any(f.startswith(r) for f in on_disk)))
        self.assertFalse(missing,
                         f"the notices name {missing}, which the installer would not carry")

    def test_every_bundled_package_has_its_texts_and_the_reverse(self) -> None:
        """Each `#### <distribution> <version>` entry has `licenses/<distribution>/`,
        and each directory there has an entry.

        The two halves drift apart silently in opposite ways: a package listed
        with no texts shipped (the notice the licence requires is missing from
        the installer), and a directory of texts no entry explains (the
        installer carries a licence for something the notices never name).
        """
        entries = _package_entries(NOTICES.read_text(encoding="utf-8"))
        # The 2026-09-01 audit listed ten packages. Fewer entries than that is
        # a parse that found nothing, not a smaller dependency tree.
        self.assertGreaterEqual(len(entries), 10,
                                f"only {sorted(entries)} parsed as package entries")
        dirs = {p.name for p in LICENSES.iterdir() if p.is_dir()}
        for name in _entries_without_texts(entries, LICENSES, _audit.SUPPLIED_BY_HAND):
            with self.subTest(entry=name):
                self.fail(f"{name} is listed and licenses/{name}/ is not there or "
                          "ships no file, and SUPPLIED_BY_HAND in "
                          "tools/notices_audit.py names no text for it")
        for name in sorted(dirs - set(entries)):
            with self.subTest(directory=name):
                self.fail(f"licenses/{name}/ ships and no package entry names it")

    def test_every_text_supplied_by_hand_is_there(self):
        """The audit accepts an empty wheel only for these, so each text must be
        at the top of licenses/, where the table test then requires its row."""
        for name, (filename, why) in sorted(_audit.SUPPLIED_BY_HAND.items()):
            with self.subTest(name):
                self.assertTrue((LICENSES / filename).is_file(),
                                f"SUPPLIED_BY_HAND names licenses/{filename} for {name}")
                self.assertTrue(why.strip(), f"{name} is supplied by hand for no stated reason")

    def test_an_entry_supplied_by_hand_needs_no_directory_and_nothing_else_does(self):
        """The list is empty today, so the real notices cannot exercise this.
        A licenses/ tree made here can: one package with its directory, one
        whose wheel shipped nothing and whose text is supplied by hand."""
        with tempfile.TemporaryDirectory() as tmp:
            licenses = pathlib.Path(tmp)
            (licenses / "numpy").mkdir()
            (licenses / "numpy" / "LICENSE.txt").write_text("BSD\n", encoding="utf-8")
            (licenses / "LGPL-3.0.txt").write_text("LGPL\n", encoding="utf-8")
            entries = {"numpy": [], "PySide6": []}
            listed = {"pyside6": ("LGPL-3.0.txt", "the 6.11.2 wheel ships none")}
            self.assertEqual(_entries_without_texts(entries, licenses, listed), [],
                             "a listed entry with its text there was refused")
            self.assertEqual(_entries_without_texts(entries, licenses, {}), ["PySide6"],
                             "an unlisted entry with no directory was accepted")
            self.assertEqual(
                _entries_without_texts(entries, licenses,
                                       {"PySide6": ("GPL-3.0.txt", "not there")}),
                ["PySide6"], "a listed entry whose text is missing was accepted")
            (licenses / "numpy" / "LICENSE.txt").unlink()
            self.assertEqual(_entries_without_texts(entries, licenses, listed), ["numpy"],
                             "an empty directory was taken for texts")

    def test_every_quoted_copyright_line_is_in_that_packages_own_files(self) -> None:
        """A quoted line is verbatim from the package's licence file, so it must
        be IN that file. Each indented `> ` line under an entry is looked up in
        the files of that entry's own directory, whitespace collapsed (the files
        indent some lines, and Markdown cannot keep a leading space).

        This is what keeps a hand-edited year, or a line carried over from the
        previous version of a package, from reading as measured.
        """
        entries = _package_entries(NOTICES.read_text(encoding="utf-8"))
        quoted = sum(len(lines) for lines in entries.values())
        self.assertGreaterEqual(quoted, 10,
                                f"{quoted} quoted lines parsed -- too few to be the audit")
        checked = 0
        for name, lines in sorted(entries.items()):
            folder = LICENSES / name
            sources = [p for p in folder.rglob("*") if p.is_file()] if folder.is_dir() else []
            supplied = _supplied_text(name, LICENSES, _audit.SUPPLIED_BY_HAND)
            if supplied:
                sources.append(supplied)
            if not sources:
                continue  # the entry-to-directory test reports this one
            corpus = "\n".join(_collapse(p.read_text(encoding="utf-8", errors="replace"))
                               for p in sources)
            for line in lines:
                checked += 1
                with self.subTest(entry=name, line=line):
                    self.assertIn(_collapse(line), corpus,
                                  f"{name}: this quote is not in licenses/{name}/")
        # Found is not checked: an entry with no texts is skipped above, so a
        # lookup that stopped finding the texts would skip every line and pass.
        self.assertGreaterEqual(checked, 10,
                                f"{quoted} quoted lines parsed and only {checked} "
                                "checked against a license file")

    def test_the_notices_carry_no_semicolon_and_no_dash(self) -> None:
        """The notices are a deliverable, and a deliverable carries no semicolon
        and no em dash (the owner's rule, `.claude/rules/house-voice.md`). An en
        dash or a spaced hyphen in the em dash's place is the same sentence
        with another mark, so both are refused too.

        Code spans and the indented `> ` quotes keep their characters, because
        they are a vendor's own wording: the Python Software Foundation's notice
        of copyright has a semicolon in it, and copying it verbatim is the point.
        A `> ` at column 0 is this file's own prose and is checked.
        """
        text = NOTICES.read_text(encoding="utf-8")
        prose = "\n".join(line for line in text.splitlines()
                          if not re.match(r"^\s+> ", line))
        prose = re.sub(r"`[^`]*`", "", prose)
        self.assertGreater(len(prose), 2000, "nearly nothing left to check")
        for mark, name in ((";", "semicolon"), ("—", "em dash"), ("–", "en dash")):
            with self.subTest(name):
                found = [ln.strip() for ln in prose.splitlines() if mark in ln]
                self.assertFalse(found, f"a {name} in the notices' prose: {found[:3]}")
        with self.subTest("spaced hyphen"):
            found = [ln.strip() for ln in prose.splitlines() if re.search(r"\S - \S", ln)]
            self.assertFalse(found, f"a spaced hyphen in the notices' prose: {found[:3]}")

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
