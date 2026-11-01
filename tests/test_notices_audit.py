"""`tools/notices_audit.py` measures the build, and refuses rather than guessing.

The tool replaces a dozen hand steps (the 2026-10-31 audit), so each rule it
encodes is held here against a fixture small enough to read: which files make
a distribution count as shipped, which wheel members are its license files,
when `copy --check` reports drift, and every input it refuses with exit 2.

None of this needs a PyInstaller build or the network. The fixtures are a fake
site-packages, a fake PYZ table of contents and fake wheels, written into a
temporary directory per test.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "notices_audit", os.path.join(HERE, "tools", "notices_audit.py"))
audit = importlib.util.module_from_spec(_spec)
sys.modules["notices_audit"] = audit  # dataclasses resolve their module by name
_spec.loader.exec_module(audit)


def _quiet(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = audit.main(argv)
    return code, out.getvalue(), err.getvalue()


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)


# ------------------------------------------------------------------ shipped

def _dist(site: pathlib.Path, name: str, version: str, files: list[str]) -> None:
    """An installed distribution: its files on disk, and a RECORD naming them."""
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")
    for rel in files:
        p = site / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel, encoding="utf-8")
    record = files + [f"{info.name}/METADATA", f"{info.name}/RECORD"]
    (info / "RECORD").write_text("".join(f"{r},,\n" for r in record), encoding="utf-8")


class _Build(_Tmp):
    """Four distributions, each reaching the bundle by a different road or none.

    - `alpha` has a module in the PYZ
    - `beta` has a data file at the same path under _internal/
    - `gamma` has a vendored library (`gamma.libs/`), flattened beside the exe
    - `delta` is installed and reaches nothing
    plus `libhost.so.1`, a file no distribution claims.
    """

    def setUp(self) -> None:
        super().setUp()
        self.site = self.tmp / "site"
        _dist(self.site, "alpha", "1.0", ["alpha/__init__.py"])
        _dist(self.site, "beta", "2.0", ["beta/__init__.py", "beta/data.bin"])
        _dist(self.site, "gamma", "3.0", ["gamma/__init__.py", "gamma.libs/libg-1a2b3c4d.so.1"])
        _dist(self.site, "delta", "4.0", ["delta/__init__.py"])
        self.build = self.tmp / "build" / "DSI_Redline"
        self.build.mkdir(parents=True)
        toc = (str(self.build / "PYZ-00.pyz"),
               [("alpha", str(self.site / "alpha" / "__init__.py"), "PYMODULE")])
        (self.build / "PYZ-00.toc").write_text(repr(toc), encoding="utf-8")
        self.dist = self.tmp / "dist" / "DSI Redline"
        internal = self.dist / "_internal"
        (internal / "beta").mkdir(parents=True)
        (internal / "beta" / "data.bin").write_text("x", encoding="utf-8")
        (internal / "libg-1a2b3c4d.so.1").write_text("x", encoding="utf-8")
        (internal / "libhost.so.1").write_text("x", encoding="utf-8")

    def argv(self, *extra: str) -> list[str]:
        return ["shipped", "--build", str(self.build), "--dist", str(self.dist),
                "--site", str(self.site), *extra]


class TestShipped(_Build):

    def test_each_road_into_the_bundle_counts_and_none_is_not_shipping(self) -> None:
        m = audit.measure(self.build, self.dist, [str(self.site)])
        shipping = {r.name for r in m.rows if r.ships}
        self.assertEqual(shipping, {"alpha", "beta", "gamma"})
        self.assertEqual(len(m.rows), 4, "delta must be checked, not just skipped")

    def test_a_file_no_distribution_claims_is_counted_not_dropped(self) -> None:
        m = audit.measure(self.build, self.dist, [str(self.site)])
        self.assertEqual(m.unclaimed, {"libhost.so.1": 1})
        self.assertEqual(m.bundle_files, 3)

    def test_a_vendored_library_claims_its_flattened_copy_too(self) -> None:
        """Measured on the 2026-11-01 build: a `.libs/` library found at its
        own path stopped the basename lookup, so its copy beside the exe read
        as claimed by nobody."""
        internal = self.dist / "_internal"
        (internal / "gamma.libs").mkdir()
        (internal / "gamma.libs" / "libg-1a2b3c4d.so.1").write_text("x", encoding="utf-8")
        m = audit.measure(self.build, self.dist, [str(self.site)])
        self.assertEqual(m.unclaimed, {"libhost.so.1": 1})

    def test_write_lists_the_shipping_set_without_the_excluded(self) -> None:
        out = self.tmp / "shipped.txt"
        code, stdout, _ = _quiet(self.argv("--write", str(out), "--exclude", "beta"))
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(encoding="utf-8").splitlines(),
                         ["alpha==1.0", "gamma==3.0"])
        self.assertIn("4 installed distributions checked, 3 ship, 1 of those excluded, "
                      "2 listed", stdout)

    def test_pydrc_is_excluded_by_default(self) -> None:
        _dist(self.site, "pydrc", "0.23.1", ["pydrc/__init__.py"])
        (self.dist / "_internal" / "pydrc").mkdir()
        (self.dist / "_internal" / "pydrc" / "__init__.py").write_text("x", encoding="utf-8")
        out = self.tmp / "shipped.txt"
        code, stdout, _ = _quiet(self.argv("--write", str(out)))
        self.assertEqual(code, 0)
        self.assertNotIn("pydrc", out.read_text(encoding="utf-8"))
        self.assertIn("SHIPS, excluded", stdout)

    def test_setuptools_shipping_is_named_rather_than_dropped(self) -> None:
        _dist(self.site, "setuptools", "79.0.1", ["setuptools/__init__.py"])
        (self.dist / "_internal" / "setuptools").mkdir()
        (self.dist / "_internal" / "setuptools" / "__init__.py").write_text("x", encoding="utf-8")
        out = self.tmp / "shipped.txt"
        code, stdout, _ = _quiet(self.argv("--write", str(out)))
        self.assertEqual(code, 0)
        self.assertIn("setuptools==79.0.1", out.read_text(encoding="utf-8"))
        self.assertIn("setuptools==65.5.0", stdout)


class TestShippedRefuses(_Build):

    def test_a_build_folder_with_no_pyz_table(self) -> None:
        (self.build / "PYZ-00.toc").unlink()
        code, _, err = _quiet(self.argv())
        self.assertEqual(code, 2)
        self.assertIn("PYZ-00.toc", err)

    def test_an_app_folder_with_no_internal(self) -> None:
        shutil.rmtree(self.dist / "_internal")
        code, _, err = _quiet(self.argv())
        self.assertEqual(code, 2)
        self.assertIn("_internal", err)

    def test_no_installed_distribution_read(self) -> None:
        empty = self.tmp / "empty-site"
        empty.mkdir()
        code, _, err = _quiet(["shipped", "--build", str(self.build), "--dist",
                               str(self.dist), "--site", str(empty)])
        self.assertEqual(code, 2)
        self.assertIn("no installed distribution", err)

    def test_nothing_ships(self) -> None:
        code, _, err = _quiet(self.argv("--exclude", "alpha", "beta", "gamma"))
        self.assertEqual(code, 2)
        self.assertIn("nothing ships", err)


# ---------------------------------------------------------- wheels and copy

def _wheel(folder: pathlib.Path, name: str, version: str, members: dict[str, str],
           metadata: str = "") -> pathlib.Path:
    path = folder / f"{name}-{version}-py3-none-any.whl"
    info = f"{name}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{info}/METADATA",
                   f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{metadata}")
        for rel, text in members.items():
            z.writestr(rel.replace("{info}", info), text)
    return path


class _Wheels(_Tmp):
    """Three wheels, one per branch of the member rule, and a vendored copy."""

    def setUp(self) -> None:
        super().setUp()
        self.wheels = self.tmp / "wheels"
        self.wheels.mkdir()
        _wheel(self.wheels, "pep639", "1.0", {
            "{info}/licenses/LICENSE": "MIT top",
            "{info}/licenses/sub/NOTICE": "notice",
            "pep639/_vendor/x/LICENSE": "BSD vendored",
            "pep639/_vendor/y/LICENSE": "MIT top",   # same bytes as the top one
            "pep639/__init__.py": "",
            "pep639/license.py": "code, not a text",
        }, "License-Expression: MIT\n")
        _wheel(self.wheels, "legacy", "2.0", {
            "{info}/COPYING": "GPL", "{info}/LICENSE.unrelated": "not declared",
        }, "License: GPL-2.0\nLicense-File: COPYING\n")
        _wheel(self.wheels, "rootonly", "3.0", {"{info}/LICENSE.txt": "Apache"},
               "Classifier: License :: OSI Approved :: Apache Software License\n")
        self.names = self.tmp / "shipped.txt"
        self.names.write_text("pep639==1.0\nlegacy==2.0\nrootonly==3.0\n", encoding="utf-8")
        self.licenses = self.tmp / "licenses"
        self.licenses.mkdir()
        (self.licenses / "GPL-3.0.txt").write_text("project-supplied", encoding="utf-8")


class TestLicenseMembers(_Wheels):

    def _members(self, name: str, version: str) -> list[tuple[str, str]]:
        with zipfile.ZipFile(self.wheels / f"{name}-{version}-py3-none-any.whl") as z:
            return audit.license_members(z)[2]

    def test_pep639_takes_the_licenses_folder_and_a_vendored_text_once(self) -> None:
        self.assertEqual(sorted(rel for _, rel in self._members("pep639", "1.0")),
                         ["LICENSE", "pep639/_vendor/x/LICENSE", "sub/NOTICE"])

    def test_a_declared_license_file_wins_over_other_root_files(self) -> None:
        self.assertEqual([rel for _, rel in self._members("legacy", "2.0")], ["COPYING"])

    def test_a_root_license_file_is_taken_when_nothing_is_declared(self) -> None:
        self.assertEqual([rel for _, rel in self._members("rootonly", "3.0")],
                         ["LICENSE.txt"])

    def test_the_declared_string_and_where_it_came_from(self) -> None:
        wheels = audit.open_wheels(audit.read_names(str(self.names)), self.wheels)
        got = {w.name: audit.declared_license(w.meta) for w in wheels}
        self.assertEqual(got["pep639"], ("MIT", "License-Expression"))
        self.assertEqual(got["legacy"], ("GPL-2.0", "License"))
        self.assertEqual(got["rootonly"],
                         ("License :: OSI Approved :: Apache Software License", "classifier"))


class TestCopy(_Wheels):

    def _copy(self, *extra: str) -> tuple[int, str, str]:
        return _quiet(["copy", str(self.names), "--wheels", str(self.wheels),
                       "--licenses", str(self.licenses), *extra])

    def test_copy_writes_bytes_and_check_then_agrees(self) -> None:
        code, _, _ = self._copy()
        self.assertEqual(code, 0)
        self.assertEqual((self.licenses / "pep639" / "sub" / "NOTICE").read_text(encoding="utf-8"),
                         "notice")
        self.assertEqual(self._copy("--check")[0], 0)

    def test_check_reports_a_changed_byte(self) -> None:
        self._copy()
        (self.licenses / "legacy" / "COPYING").write_text("GPL edited", encoding="utf-8")
        code, out, _ = self._copy("--check")
        self.assertEqual(code, 1)
        self.assertIn("changed: legacy/COPYING", out)

    def test_check_reports_a_missing_and_an_extra_file(self) -> None:
        self._copy()
        (self.licenses / "rootonly" / "LICENSE.txt").unlink()
        (self.licenses / "rootonly" / "HANDWRITTEN.txt").write_text("x", encoding="utf-8")
        code, out, _ = self._copy("--check")
        self.assertEqual(code, 1)
        self.assertIn("missing: rootonly/LICENSE.txt", out)
        self.assertIn("extra:   rootonly/HANDWRITTEN.txt", out)

    def test_a_folder_no_listed_distribution_owns_is_stale_and_kept_unless_pruned(self) -> None:
        self._copy()
        (self.licenses / "gone").mkdir()
        (self.licenses / "gone" / "LICENSE").write_text("x", encoding="utf-8")
        code, out, _ = self._copy("--check")
        self.assertEqual(code, 1)
        self.assertIn("stale:   gone/", out)
        self.assertEqual(self._copy()[0], 0)
        self.assertTrue((self.licenses / "gone").is_dir(), "removed without --prune")
        self.assertEqual(self._copy("--prune")[0], 0)
        self.assertFalse((self.licenses / "gone").exists())

    def test_a_top_level_text_is_never_reported_or_touched(self) -> None:
        self._copy("--prune")
        self.assertEqual((self.licenses / "GPL-3.0.txt").read_text(encoding="utf-8"),
                         "project-supplied")
        self.assertEqual(self._copy("--check")[0], 0)


class TestCopyRefuses(_Wheels):

    def test_a_listed_distribution_with_no_wheel(self) -> None:
        self.names.write_text("pep639==1.0\nabsent==9.9\n", encoding="utf-8")
        code, _, err = _quiet(["copy", str(self.names), "--wheels", str(self.wheels),
                               "--licenses", str(self.licenses)])
        self.assertEqual(code, 2)
        self.assertIn("absent==9.9", err)

    def test_a_wheel_with_no_license_file(self) -> None:
        _wheel(self.wheels, "bare", "1.0", {"bare/__init__.py": ""})
        self.names.write_text("bare==1.0\n", encoding="utf-8")
        code, _, err = _quiet(["copy", str(self.names), "--wheels", str(self.wheels),
                               "--licenses", str(self.licenses)])
        self.assertEqual(code, 2)
        self.assertIn("holds no license file", err)
        self.assertFalse((self.licenses / "bare").exists())

    def test_an_empty_names_file(self) -> None:
        self.names.write_text("# nothing here\n\n", encoding="utf-8")
        code, _, err = _quiet(["holders", str(self.names), "--wheels", str(self.wheels)])
        self.assertEqual(code, 2)
        self.assertIn("names no distribution", err)

    def test_a_line_that_is_not_name_equals_version(self) -> None:
        self.names.write_text("pep639\n", encoding="utf-8")
        code, _, err = _quiet(["copy", str(self.names), "--wheels", str(self.wheels)])
        self.assertEqual(code, 2)
        self.assertIn("not name==version", err)


# ------------------------------------------------------- holders and fetch

class TestStatements(unittest.TestCase):

    def test_a_statement_is_kept_and_clause_text_is_not(self) -> None:
        text = "\n".join([
            "Copyright (c) 2018 Alex Grönholm",
            " Copyright (C) 1998-2012 Daniel Veillard.  All Rights Reserved.",
            "  > Copyright © 2025, Karen Petrosyan.",
            "Based on previous work under copyright (c) 2002 McMillan Enterprises, Inc.",
            "* Redistributions of source code must retain the above copyright notice,",
            "      (c) You must retain, in the Source form of any Derivative Works",
            "   Copyright [yyyy] [name of copyright owner]",
            "THE SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS",
        ])
        self.assertEqual(audit.statements(text), [
            "Copyright (c) 2018 Alex Grönholm",
            "Copyright (C) 1998-2012 Daniel Veillard.  All Rights Reserved.",
            "> Copyright © 2025, Karen Petrosyan.",
            "Based on previous work under copyright (c) 2002 McMillan Enterprises, Inc.",
        ])


class TestFetch(unittest.TestCase):

    def test_the_wheels_asked_for_are_the_windows_ones(self) -> None:
        """The installer is Windows, and numpy 2.4.6's license file is 914 lines
        in its win_amd64 wheel and 935 in its Linux one."""
        argv = audit.fetch_command([("numpy", "2.4.6")], "wheels", python="py")
        self.assertEqual(argv[:4], ["py", "-m", "pip", "download"])
        for flag in ("--no-deps", "--only-binary=:all:"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--platform") + 1], "win_amd64")
        self.assertEqual(argv[argv.index("--python-version") + 1], "3.11")
        self.assertEqual(argv[-1], "numpy==2.4.6")


class TestTheRepositoryIsWhatTheToolWrites(unittest.TestCase):
    """The committed licenses/ has the shape `copy` produces: top-level files are
    the project-supplied texts, and everything else sits in a folder per
    distribution. A file dropped loose into a distribution's place would be
    one the tool can neither check nor regenerate."""

    def test_only_the_project_supplied_texts_sit_at_the_top(self) -> None:
        licenses = pathlib.Path(HERE) / "licenses"
        top = sorted(p.name for p in licenses.iterdir() if p.is_file())
        self.assertTrue(top, "licenses/ has no top-level text at all")
        for name in top:
            with self.subTest(name):
                self.assertRegex(name, r"^(L?GPL|Apache)-[0-9.]+\.txt$")
        self.assertGreaterEqual(sum(1 for p in licenses.iterdir() if p.is_dir()), 10,
                                "fewer than ten distribution folders: a sweep of nothing")


if __name__ == "__main__":
    unittest.main()
