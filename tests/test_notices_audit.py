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
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

# The workflow-step harness: the `run:` block reader and the probe that finds a
# bash which can actually run a script (`windows-latest` puts WSL's launcher on
# PATH, which runs nothing). Imported rather than copied, so both harnesses
# drive the same shell.
from tests.test_drc_ref_resolution import BASH, _code_only, _run_script

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(HERE, ".github", "workflows", "build-windows.yml")
NOTICES_STEP = "Check the notices against the bundle"
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


def _pkg_toc(build: pathlib.Path, entries: list[tuple[str, str, str]]) -> tuple:
    """A `PKG-00.toc` literal in the shape PyInstaller 6.22.3 wrote on
    2026-11-01: eleven fields, the entries third, an empty list seventh."""
    return (str(build / "DSI Redline.pkg"),
            {"BINARY": True, "DATA": True, "PYMODULE": True, "PYSOURCE": True},
            entries, "libpython3.11.so.1.0", True, False, False, [], None, None, None)


class _Build(_Tmp):
    """Four distributions, each reaching the bundle by a different road or none.

    - `alpha` has a module in the PYZ
    - `beta` has a data file at the same path under _internal/
    - `gamma` has a vendored library (`gamma.libs/`), flattened beside the exe
    - `delta` is installed and reaches nothing
    plus `libhost.so.1`, a file no distribution claims, and an executable's
    archive (`PKG-00.toc`) holding the app's `main.py` and a bootstrap module
    compiled into the build folder, which no distribution claims either.
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
        self.pkg_entries = [
            ("pyi-contents-directory _internal", "", "OPTION"),
            ("PYZ-00.pyz", str(self.build / "PYZ-00.pyz"), "PYZ"),
            ("pyimod01_archive", str(self.build / "localpycs" / "pyimod01_archive.pyc"),
             "PYMODULE"),
            ("main", str(self.tmp / "main.py"), "PYSOURCE"),
        ]
        self.write_pkg()
        self.dist = self.tmp / "dist" / "DSI Redline"
        internal = self.dist / "_internal"
        (internal / "beta").mkdir(parents=True)
        (internal / "beta" / "data.bin").write_text("x", encoding="utf-8")
        (internal / "libg-1a2b3c4d.so.1").write_text("x", encoding="utf-8")
        (internal / "libhost.so.1").write_text("x", encoding="utf-8")

    def write_pkg(self, toc: object = None) -> None:
        if toc is None:
            toc = _pkg_toc(self.build, self.pkg_entries)
        (self.build / "PKG-00.toc").write_text(repr(toc), encoding="utf-8")

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

    def test_a_run_time_hook_in_the_executable_ships_its_distribution(self) -> None:
        """A hook from `pyinstaller-hooks-contrib` lands in the archive appended
        to the exe, which is neither the PYZ nor _internal/. Read only those
        two, and its distribution reads as not shipping."""
        _dist(self.site, "contrib", "5.0", ["contrib/rthooks/pyi_rth_contrib.py"])
        self.pkg_entries.append(
            ("pyi_rth_contrib", str(self.site / "contrib" / "rthooks" / "pyi_rth_contrib.py"),
             "PYSOURCE"))
        self.write_pkg()
        m = audit.measure(self.build, self.dist, [str(self.site)])
        row = next(r for r in m.rows if r.name == "contrib")
        self.assertTrue(row.ships, "a run-time hook ships inside the exe")
        self.assertEqual((row.pyz, row.pkg, row.files), (0, 1, 0))
        self.assertEqual(m.pkg_code, 3)
        self.assertEqual(m.pkg_unclaimed, ["main", "pyimod01_archive"])

    def test_only_scripts_and_modules_in_the_archive_count(self) -> None:
        """The archive's options, its PYZ, and in a one-file build its binaries
        and data are entries too. Only PYSOURCE and PYMODULE are code."""
        for code in ("BINARY", "DATA", "PYZ", "OPTION", "EXTENSION"):
            with self.subTest(code):
                self.pkg_entries.append(("delta", str(self.site / "delta" / "__init__.py"), code))
                self.write_pkg()
                m = audit.measure(self.build, self.dist, [str(self.site)])
                delta = next(r for r in m.rows if r.name == "delta")
                self.assertEqual(delta.pkg, 0, f"a {code} entry counted as code")
                self.assertFalse(delta.ships)
                self.pkg_entries.pop()

    def test_the_archive_is_counted_in_the_output(self) -> None:
        code, stdout, _ = _quiet(self.argv())
        self.assertEqual(code, 0)
        self.assertIn("2 scripts and modules in the executable's archive (PKG-00.toc), "
                      "0 claimed by a distribution, 2 by none: main, pyimod01_archive",
                      stdout)

    def test_the_entry_list_is_found_by_shape_not_position(self) -> None:
        entries = [("m", "/x/m.py", "PYSOURCE")]
        pyz = ("PYZ-00.pyz", entries)
        pkg = _pkg_toc(self.build, entries)
        self.assertIs(audit.toc_entries(pyz), entries, "the PYZ toc has it second")
        self.assertIs(audit.toc_entries(pkg), entries, "the PKG toc has it third of eleven")
        self.assertEqual(len(pkg), 11)
        moved = (*pkg[:2], *pkg[3:], entries)
        self.assertIs(audit.toc_entries(moved), entries, "moved to the end, still found")
        self.assertIsNone(audit.toc_entries(("x", {}, [], None)), "no entry list")
        self.assertIsNone(audit.toc_entries(("x", entries, list(entries))),
                          "two entry lists is ambiguous, not the first one")

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

    def test_a_build_folder_with_no_pkg_table(self) -> None:
        (self.build / "PKG-00.toc").unlink()
        code, _, err = _quiet(self.argv())
        self.assertEqual(code, 2)
        self.assertIn("no PKG-00.toc", err)

    def test_a_pkg_table_that_lists_no_code(self) -> None:
        self.pkg_entries[:] = [e for e in self.pkg_entries if e[2] not in audit.PKG_CODE]
        self.assertEqual(len(self.pkg_entries), 2, "the option and the PYZ are left")
        self.write_pkg()
        code, _, err = _quiet(self.argv())
        self.assertEqual(code, 2)
        self.assertIn("lists no PYSOURCE or PYMODULE entry", err)

    def test_a_pkg_table_with_no_entry_list(self) -> None:
        self.write_pkg((str(self.build / "DSI Redline.pkg"), {}, [], None))
        code, _, err = _quiet(self.argv())
        self.assertEqual(code, 2)
        self.assertIn("PKG-00.toc holds no single list", err)

    def test_a_pkg_table_that_is_not_a_literal(self) -> None:
        (self.build / "PKG-00.toc").write_text("", encoding="utf-8")
        code, _, err = _quiet(self.argv())
        self.assertEqual(code, 2)
        self.assertIn("is not a Python literal", err)

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
        wheels = audit.open_wheels(audit.read_names(str(self.names)), self.wheels,
                                   self.licenses)
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
        self.assertIn("SUPPLIED_BY_HAND", err, "the refusal no longer says how to supply it")
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


class TestSuppliedByHand(_Wheels):
    """A wheel with no license file, its text supplied at the top of licenses/.

    `bare_pkg`'s wheel holds no license file. It is listed as `bare-pkg` in
    the shipping set and keyed `Bare.Pkg` in SUPPLIED_BY_HAND, three spellings
    pip reads as one name. The real default is patched, so `main()` runs the
    path a release runs.
    """

    ENTRY = {"Bare.Pkg": ("GPL-3.0.txt", "its wheel ships no license file")}

    def setUp(self) -> None:
        super().setUp()
        _wheel(self.wheels, "bare_pkg", "1.0", {"bare_pkg/__init__.py": ""})
        self.names.write_text("pep639==1.0\nlegacy==2.0\nrootonly==3.0\nbare-pkg==1.0\n",
                              encoding="utf-8")

    def run_with(self, entry: dict, *argv: str) -> tuple[int, str, str]:
        with mock.patch.dict(audit.SUPPLIED_BY_HAND, entry, clear=True):
            return _quiet(list(argv))

    def copy(self, entry: dict, *extra: str) -> tuple[int, str, str]:
        return self.run_with(entry, "copy", str(self.names), "--wheels", str(self.wheels),
                             "--licenses", str(self.licenses), *extra)

    def test_a_listed_package_is_reported_as_supplied_by_hand(self) -> None:
        code, out, err = self.copy(self.ENTRY)
        self.assertEqual(code, 0, err)
        self.assertFalse((self.licenses / "bare_pkg").exists(),
                         "a folder was written for a package whose wheel has no text")
        code, out, err = self.copy(self.ENTRY, "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("by hand: bare_pkg==1.0  licenses/GPL-3.0.txt  "
                      "(its wheel ships no license file)", out)
        self.assertIn("4 distributions: 3 with license files of their own, "
                      "1 supplied by hand", out)

    def test_the_list_is_empty_today(self) -> None:
        """The 6.11.3 Qt wheels ship LicenseRef-Qt-Commercial.txt, so no
        package needs an entry. A non-empty list is a decision to record."""
        self.assertEqual(audit.SUPPLIED_BY_HAND, {})

    def test_holders_reads_the_supplied_text(self) -> None:
        code, out, err = self.run_with(self.ENTRY, "holders", str(self.names), "--wheels",
                                       str(self.wheels), "--licenses", str(self.licenses))
        self.assertEqual(code, 0, err)
        self.assertIn("Supplied by hand: its wheel ships no license file", out)
        self.assertIn("`licenses/GPL-3.0.txt`, 1 lines", out)

    def test_an_unlisted_spelling_does_not_match(self) -> None:
        """`barepkg` is not `bare-pkg` to pip, so it lists a package that is
        not shipping, and the empty wheel stays unsupplied."""
        code, _, err = self.copy({"barepkg": ("GPL-3.0.txt", "x")})
        self.assertEqual(code, 2)
        self.assertIn("SUPPLIED_BY_HAND names barepkg", err)

    def test_a_listed_text_that_is_not_there(self) -> None:
        code, _, err = self.copy({"Bare.Pkg": ("LGPL-9.txt", "x")})
        self.assertEqual(code, 2)
        self.assertIn("SUPPLIED_BY_HAND names licenses/LGPL-9.txt for Bare.Pkg", err)

    def test_a_listed_text_must_sit_at_the_top(self) -> None:
        self.assertEqual(self.copy({})[0], 2, "the empty wheel must refuse unlisted")
        self.names.write_text("pep639==1.0\n", encoding="utf-8")
        self.assertEqual(self.copy({})[0], 0)
        self.names.write_text("pep639==1.0\nbare-pkg==1.0\n", encoding="utf-8")
        code, _, err = self.copy({"Bare.Pkg": ("pep639/LICENSE", "x")})
        self.assertEqual(code, 2)
        self.assertIn("not a file at the top", err)

    def test_a_listed_wheel_that_ships_a_license_again_is_stale(self) -> None:
        code, _, err = self.copy({**self.ENTRY, "PEP639": ("GPL-3.0.txt", "x")})
        self.assertEqual(code, 2)
        self.assertIn("SUPPLIED_BY_HAND names PEP639", err)
        self.assertIn("stale", err)

    def test_a_listed_package_that_no_longer_ships(self) -> None:
        self.names.write_text("pep639==1.0\n", encoding="utf-8")
        code, _, err = self.copy(self.ENTRY)
        self.assertEqual(code, 2)
        self.assertIn("no longer ships", err)

    def test_a_folder_under_a_listed_name_is_stale(self) -> None:
        self.assertEqual(self.copy(self.ENTRY)[0], 0)
        (self.licenses / "bare_pkg").mkdir()
        (self.licenses / "bare_pkg" / "LICENSE").write_text("x", encoding="utf-8")
        code, out, _ = self.copy(self.ENTRY, "--check")
        self.assertEqual(code, 1)
        self.assertIn("stale:   bare_pkg/", out)


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


# ------------------------------------------------- the Build Windows step

def _step_names(path: str) -> list[str]:
    """Each named step in the workflow, in order, comment lines dropped. The
    same `- name:` spelling `_run_script` finds a step by."""
    with open(path, encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh.read().splitlines()
                 if not ln.lstrip().startswith("#")]
    return [ln[len("- name: "):] for ln in lines if ln.startswith("- name: ")]


def _step_header(path: str, step_name: str) -> str:
    """The step's own keys, from its `- name:` line to its `run:` line."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == f"- name: {step_name}")
    out = []
    for ln in lines[start:]:
        out.append(ln)
        if ln.strip().startswith("run:"):
            break
    return "\n".join(out)


class TestTheBuildChecksTheNotices(unittest.TestCase):
    """Structural, so it runs where bash does not."""

    def setUp(self) -> None:
        self.code = _code_only(_run_script(WORKFLOW, NOTICES_STEP))

    def test_it_runs_after_the_self_test_and_before_anything_is_packaged(self) -> None:
        names = _step_names(WORKFLOW)
        self.assertGreaterEqual(len(names), 10, f"read {len(names)} steps, so the reader missed the job")
        self.assertEqual(names.count(NOTICES_STEP), 1)
        selftest, inno = "Launch the built app (self-test)", "Build installer (Inno Setup)"
        self.assertIn("--self-test", _run_script(WORKFLOW, selftest), f"{selftest!r} moved")
        self.assertIn("ISCC.exe", _run_script(WORKFLOW, inno), f"{inno!r} moved")
        at = names.index(NOTICES_STEP)
        self.assertEqual(names[at - 1], selftest, "the notices are checked before the "
                         "built app has been started")
        self.assertEqual(names[at + 1], inno, "something runs between the check and "
                         "the installer")
        later = [n for n in names if n.startswith(("Package", "Upload", "Publish"))]
        self.assertEqual(len(later), 4, f"the zip, both uploads and the release: {later}")
        self.assertTrue(all(names.index(n) > at for n in later),
                        "something is packaged or published before the check")

    def test_a_tag_build_can_fail_on_it_and_nothing_skips_it(self) -> None:
        header = _step_header(WORKFLOW, NOTICES_STEP)
        self.assertNotIn("continue-on-error", header)
        self.assertNotIn("if:", header, "a condition would skip the step with no line in the log")
        self.assertIn("shell: bash", header)
        self.assertRegex(header, r"IS_TAG: \$\{\{ startsWith\(github\.ref, 'refs/tags/'\) \}\}",
                         "the step no longer knows whether this is a tag build")
        self.assertIn("exit 1", self.code)

    def test_each_exit_code_is_kept_and_never_read_through_a_pipe(self) -> None:
        """`|| true` throws the code away, and a pipe reports the last command's.
        Either makes a difference or a refusal read as a pass."""
        runs = [ln for ln in self.code.splitlines() if "tools/notices_audit.py" in ln
                and ln.strip().startswith("python ")]
        self.assertEqual([re.search(r"notices_audit\.py (\w+)", ln).group(1) for ln in runs],
                         ["shipped", "fetch", "copy"], "the three stages, in order")
        for ln in runs:
            with self.subTest(ln.strip()):
                self.assertTrue(ln.rstrip().endswith("|| rc=$?"), "the exit code is not kept")
                self.assertNotIn("|| true", ln)
                self.assertNotIn(" | ", ln, "piped, so $? is the last command's")
        self.assertIn("--check", runs[2], "copy without --check writes licenses/")
        self.assertIn("changed=$(git status --porcelain -- licenses/) || git_rc=$?", self.code)


# `python` is a shell FUNCTION standing in for the audit, for the reason the
# PyDRC harness gives: no directory, no execute bit and no PATH edit, so it
# runs the same under Git bash. git is the real one, in a real repository,
# because what the step asks of git is the thing under test.
_AUDIT_STUB = """
python() {
  if [ "$1" != "tools/notices_audit.py" ]; then
    echo "UNEXPECTED: python $*" >&2
    return 99
  fi
  echo "AUDIT-RAN: $2"
  case "$2" in
    shipped) return "${SHIPPED_RC:-0}" ;;
    fetch) return "${FETCH_RC:-0}" ;;
    copy)
      case " $* " in
        *" --check "*) return "${COPY_RC:-0}" ;;
      esac
      echo "UNEXPECTED: copy without --check, which writes licenses/" >&2
      return 99 ;;
  esac
  echo "UNEXPECTED: python $*" >&2
  return 99
}
"""


@unittest.skipUnless(BASH and shutil.which("git"),
                     "no bash that can run a script, or no git, was found here")
class TestDrivingTheNoticesStep(unittest.TestCase):
    """The step's real `run:` block, under the flags Actions gives `shell: bash`."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="notices-step-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        lic = os.path.join(self.tmp, "licenses", "numpy")
        os.makedirs(lic)
        with open(os.path.join(lic, "LICENSE.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("BSD\n")
        for argv in (["init", "-q"], ["config", "core.autocrlf", "false"],
                     ["add", "licenses"],
                     ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                      "commit", "-q", "-m", "licenses"]):
            subprocess.run(["git", *argv], cwd=self.tmp, check=True, capture_output=True)

    def drive(self, *, token: str = "tok", tag: bool = True, **env: str) -> tuple[int, str]:
        script = _run_script(WORKFLOW, NOTICES_STEP)
        self.assertNotIn("${{", script, "an Actions expression bash cannot read is in the script")
        path = os.path.join(self.tmp, "step.sh")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_AUDIT_STUB + script)
        full = dict(os.environ, PYDRC_TOKEN=token, IS_TAG="true" if tag else "false", **env)
        r = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", path],
                           cwd=self.tmp, env=full, capture_output=True, text=True,
                           errors="replace")
        out = r.stdout + r.stderr
        # Every path through the step prints one of these, so output with none
        # of them means the shell never ran the script, and a test expecting a
        # failure would pass on a shell that fails everything.
        self.assertTrue(any(m in out for m in ("::warning::", "::error::", "Notices: licenses/")),
                        f"{BASH} did not run the step. Output was:\n{out!r}")
        self.assertNotIn("UNEXPECTED", out)
        return r.returncode, out

    def edit(self, how: str) -> str:
        lic = os.path.join(self.tmp, "licenses")
        if how == "modify":
            with open(os.path.join(lic, "numpy", "LICENSE.txt"), "a", encoding="utf-8") as fh:
                fh.write("changed\n")
            return "licenses/numpy/LICENSE.txt"
        if how == "add":
            os.makedirs(os.path.join(lic, "newpkg"))
            with open(os.path.join(lic, "newpkg", "LICENSE"), "w", encoding="utf-8") as fh:
                fh.write("new\n")
            return "licenses/newpkg/"
        shutil.rmtree(os.path.join(lic, "numpy"))
        return "licenses/numpy/LICENSE.txt"

    def test_without_the_token_it_says_the_notices_were_not_checked(self) -> None:
        rc, out = self.drive(token="")
        self.assertEqual(rc, 0, out)
        self.assertIn("::warning::", out)
        self.assertIn("NOT checked", out)
        self.assertNotIn("AUDIT-RAN", out)

    def test_a_bundle_that_matches_passes(self) -> None:
        rc, out = self.drive()
        self.assertEqual(rc, 0, out)
        self.assertEqual(re.findall(r"AUDIT-RAN: (\w+)", out), ["shipped", "fetch", "copy"])
        self.assertIn("Notices: licenses/ matches", out)
        self.assertNotIn("::", out)

    def test_a_difference_fails_a_tag_build(self) -> None:
        """git is clean, so the exit code is the only signal. `|| true` in
        place of `|| rc=$?` passes this build."""
        rc, out = self.drive(COPY_RC="1")
        self.assertEqual(rc, 1, out)
        self.assertIn("::error::copy --check exited 1", out)

    def test_a_refusal_fails_a_tag_build_and_stops_the_stages_after_it(self) -> None:
        for stage, var, ran in (("shipped", "SHIPPED_RC", ["shipped"]),
                                ("fetch", "FETCH_RC", ["shipped", "fetch"]),
                                ("copy --check", "COPY_RC", ["shipped", "fetch", "copy"])):
            with self.subTest(stage):
                rc, out = self.drive(**{var: "2"})
                self.assertEqual(rc, 1, out)
                self.assertIn(f"::error::tools/notices_audit.py {stage} exited 2", out)
                self.assertEqual(re.findall(r"AUDIT-RAN: (\w+)", out), ran)

    def test_a_checkout_that_is_not_the_commit_fails_a_tag_build(self) -> None:
        """Untracked and deleted files too, which `git diff` alone never shows."""
        for how in ("modify", "add", "remove"):
            with self.subTest(how):
                self.setUp()
                named = self.edit(how)
                rc, out = self.drive()
                self.assertEqual(rc, 1, out)
                self.assertIn("::error::licenses/ is not the commit", out)
                self.assertIn(named, out)

    def test_a_git_status_that_fails_is_not_read_as_clean(self) -> None:
        rc, out = self.drive(GIT_DIR=os.path.join(self.tmp, "no-such-git"))
        self.assertEqual(rc, 1, out)
        self.assertIn("git status exited", out)

    def test_a_manual_run_warns_and_goes_on(self) -> None:
        for name, env in (("difference", {"COPY_RC": "1"}), ("refusal", {"SHIPPED_RC": "2"}),
                          ("checkout", {})):
            with self.subTest(name):
                self.setUp()
                if name == "checkout":
                    self.edit("modify")
                rc, out = self.drive(tag=False, **env)
                self.assertEqual(rc, 0, out)
                self.assertIn("::warning::", out)
                self.assertNotIn("::error::", out)
                self.assertIn("This is a manual run, so it does not fail", out)


if __name__ == "__main__":
    unittest.main()
