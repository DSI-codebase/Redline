"""`tools/notices_audit.py`, held to a build that is not there.

The tool reads a finished PyInstaller build and fifty installed distributions,
and none of that exists in CI. So this builds the smallest thing with the same
shape in a temporary directory: a site-packages with `RECORD` files, a
`PYZ-00.toc` literal naming real paths in it, a `base_library.zip`, an
`_internal/` tree with an executable beside it, and wheels holding license
files. Nothing touches the network or the repository's own `licenses/`.

Each route into the bundle gets its own distribution, so a rule that stops
firing takes exactly one name out of the SHIPS set:

    alpha        a module whose real path is in the PYZ toc
    beta         a native file at the same relative path under _internal/
    gamma        a vendored native lib, `gamma.libs/x`, found by basename
    epsilon      a module compiled into base_library.zip
    pyinstaller  `_pyi_rth_utils` in the toc, and the bootloader beside _internal/
    pydrc        DSI's own: it ships and is never copied into licenses/

and three that must NOT ship: `delta` (installed, absent from the bundle),
`setuptools` (the build-environment trap), and `decoy`, which installs a module
named `alpha` from another directory. A module is matched by its real path, so
a name that happens to agree with the toc must not count.

The end-to-end check against a real build is the procedure in
THIRD-PARTY-NOTICES.md ("How to re-run the audit"). It needs the build, so it
is a local step.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import pathlib
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "notices_audit", REPO / "tools" / "notices_audit.py")
na = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(na)

# License bodies, each distinct, so a file copied from the wrong place is
# visible as wrong bytes rather than as a right-looking name.
ALPHA_LICENSE = b"Alpha License\r\nCopyright (c) 2024 Caf\xe9 Authors\r\n"
ALPHA_SUB = b"alpha sub-component COPYING\n"
ALPHA_ROOT = b"an older alpha LICENSE at the dist-info root\n"
ALPHA_VENDORED = b"BSD-3-Clause for the vendored thing\n"
BETA_WIN = b"beta LICENSE.txt, Windows wheel\n"
BETA_LINUX = b"beta LICENSE.txt, Linux wheel, which is longer\n"
GAMMA_COPYING = b"gamma COPYING\n"
GAMMA_AUTHORS = b"gamma AUTHORS\n"
EPSILON_LICENSE = b"epsilon LICENSE\n"
PYI_COPYING = b"PyInstaller COPYING.txt\n"


class _Build:
    """A finished build in a temporary directory, made of exactly these parts."""

    def __init__(self, root: pathlib.Path):
        self.root = root
        self.site = root / "site"
        self.elsewhere = root / "elsewhere"
        self.work = root / "build"
        self.dist = root / "dist"
        self.internal = self.dist / na.APP_NAME / "_internal"
        self.wheels = root / "wheels"
        self.licenses = root / "licenses"
        self.toc: list[tuple[str, str]] = []
        self.base_library = ["codecs.pyc", "encodings/__init__.pyc"]

    def install(self, name, version, files, site=None):
        site = site or self.site
        info = f"{name.replace('-', '_')}-{version}.dist-info"
        for rel, body in files.items():
            path = site / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        (site / info).mkdir(parents=True, exist_ok=True)
        (site / info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")
        record = [f"{rel},," for rel in files] + [f"{info}/METADATA,,", f"{info}/RECORD,,"]
        (site / info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")

    def in_pyz(self, name, path):
        self.toc.append((name, str(path)))

    def in_internal(self, rel, body=b"\x7fELF"):
        path = self.internal / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def wheel(self, filename, members):
        self.wheels.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.wheels / filename, "w") as z:
            for name, body in members.items():
                z.writestr(name, body)

    def finish(self, toc=True, base_library=True, internal=True, executable=True):
        out = self.work / na.SPEC_NAME
        out.mkdir(parents=True, exist_ok=True)
        if toc:
            literal = (str(out / "PYZ-00.pyz"),
                       [(n, p, "PYMODULE") for n, p in self.toc])
            (out / "PYZ-00.toc").write_text(repr(literal), encoding="utf-8")
        if base_library:
            with zipfile.ZipFile(out / "base_library.zip", "w") as z:
                for member in self.base_library:
                    z.writestr(member, b"pyc")
        if not internal:
            shutil.rmtree(self.internal, ignore_errors=True)
            self.internal.parent.mkdir(parents=True, exist_ok=True)
            (self.internal.parent / f"{na.APP_NAME}.exe").write_bytes(b"MZ bootloader")
            return self
        self.internal.mkdir(parents=True, exist_ok=True)
        if base_library:
            shutil.copy(out / "base_library.zip", self.internal / "base_library.zip")
        if executable:
            (self.internal.parent / f"{na.APP_NAME}.exe").write_bytes(b"MZ bootloader")
        return self


def _meta(name, version, mv="2.4", license_files=()):
    lines = [f"Metadata-Version: {mv}", f"Name: {name}", f"Version: {version}"]
    lines += [f"License-File: {f}" for f in license_files]
    return ("\n".join(lines) + "\n").encode("utf-8")


def standard(root: pathlib.Path, *, rth_utils=True) -> _Build:
    """The build every test starts from. Its SHIPS set is SHIPS below."""
    b = _Build(root)

    b.install("alpha", "1.0", {"alpha/__init__.py": b""})
    b.in_pyz("alpha", b.site / "alpha" / "__init__.py")
    b.wheel("alpha-1.0-py3-none-any.whl", {
        "alpha/__init__.py": b"",
        "alpha/license.py": b"LICENSE = 'code, not a license text'\n",
        "alpha/LICENSE": ALPHA_LICENSE,                  # same bytes: already taken
        "alpha/_vendor/thing/LICENSE": ALPHA_VENDORED,   # new bytes: vendored
        "alpha-1.0.dist-info/METADATA": _meta("alpha", "1.0", "2.4", ["LICENSE", "sub/COPYING"]),
        "alpha-1.0.dist-info/LICENSE": ALPHA_ROOT,       # rule 1 answered, so never read
        "alpha-1.0.dist-info/licenses/LICENSE": ALPHA_LICENSE,
        "alpha-1.0.dist-info/licenses/sub/COPYING": ALPHA_SUB,
    })

    b.install("beta", "2.0", {"beta/_native.so": b"\x7fELF"})
    b.in_internal("beta/_native.so")
    for tag, body in (("win_amd64", BETA_WIN), ("manylinux_2_28_x86_64", BETA_LINUX)):
        b.wheel(f"beta-2.0-cp311-cp311-{tag}.whl", {
            "beta/_native.pyd": b"MZ",
            "beta-2.0.dist-info/METADATA": _meta("beta", "2.0", "2.1", ["LICENSE.txt"]),
            "beta-2.0.dist-info/LICENSE.txt": body,
            "beta-2.0.dist-info/NOTICE": b"not named by License-File\n",
            "beta-2.0.dist-info/README.md": b"readme\n",
        })

    b.install("gamma", "3.0", {"gamma/__init__.py": b"",
                               "gamma.libs/libgamma-1a2b3c.so": b"\x7fELF"})
    b.in_internal("libgamma-1a2b3c.so")      # not at gamma.libs/, by basename
    b.wheel("gamma-3.0-cp311-cp311-win_amd64.whl", {
        "gamma/__init__.py": b"",
        "gamma-3.0.dist-info/METADATA": _meta("gamma", "3.0", "2.1"),
        "gamma-3.0.dist-info/COPYING": GAMMA_COPYING,
        "gamma-3.0.dist-info/AUTHORS.rst": GAMMA_AUTHORS,
        "gamma-3.0.dist-info/README.rst": b"readme\n",
    })

    b.install("epsilon", "1.0", {"epsilon_boot.py": b""})
    b.base_library.append("epsilon_boot.pyc")
    b.wheel("epsilon-1.0-py3-none-any.whl", {
        "epsilon_boot.py": b"",
        "epsilon-1.0.dist-info/METADATA": _meta("epsilon", "1.0"),
        "epsilon-1.0.dist-info/licenses/LICENSE": EPSILON_LICENSE,
    })

    rth = "PyInstaller/fake-modules/_pyi_rth_utils/__init__.py"
    b.install("pyinstaller", "6.22.3", {
        rth: b"", "PyInstaller/bootloader/Windows-64bit-intel/run.exe": b"MZ"})
    if rth_utils:
        b.in_pyz("_pyi_rth_utils", b.site / rth)
    b.wheel("pyinstaller-6.22.3-py3-none-win_amd64.whl", {
        "PyInstaller/__init__.py": b"",
        "pyinstaller-6.22.3.dist-info/METADATA": _meta("pyinstaller", "6.22.3", "2.4", ["COPYING.txt"]),
        "pyinstaller-6.22.3.dist-info/licenses/COPYING.txt": PYI_COPYING,
    })

    b.install("pydrc", "0.23.1", {"pydrc/__init__.py": b"",
                                  "pydrc/packs/base.yaml": b"rules: []\n"})
    b.in_pyz("pydrc", b.site / "pydrc" / "__init__.py")
    b.in_internal("pydrc/packs/base.yaml", b"rules: []\n")

    b.install("delta", "4.0", {"delta/__init__.py": b""})
    b.install("setuptools", na.RUNNER_SETUPTOOLS, {"setuptools/__init__.py": b""})
    b.install("decoy", "5.0", {"alpha/__init__.py": b""}, site=b.elsewhere)

    stdlib = root / "stdlib" / "json" / "__init__.py"
    stdlib.parent.mkdir(parents=True)
    stdlib.write_bytes(b"")
    b.in_pyz("json", stdlib)
    b.toc.append(("ns_package", "-"))        # a namespace package has no file

    b.in_internal("docs/a.md", b"# a\n")
    b.in_internal("docs/b.md", b"# b\n")
    b.in_internal("libpython3.11.so.1.0")
    b.in_internal("licenses/Apache-2.0.txt", b"Apache\n")
    return b


SHIPS = {"alpha", "beta", "gamma", "epsilon", "pyinstaller", "pydrc"}

WRITTEN = {
    "alpha": {"LICENSE": ALPHA_LICENSE, "sub/COPYING": ALPHA_SUB,
              "alpha/_vendor/thing/LICENSE": ALPHA_VENDORED},
    "beta": {"LICENSE.txt": BETA_WIN},
    "gamma": {"AUTHORS.rst": GAMMA_AUTHORS, "COPYING": GAMMA_COPYING},
    "epsilon": {"LICENSE": EPSILON_LICENSE},
    "pyinstaller": {"COPYING.txt": PYI_COPYING},
}


def _tree(folder: pathlib.Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob("*") if p.is_file()}


class _TempBuild(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="notices-audit-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def rows(self, b: _Build):
        toc, _ = na.read_pyz_toc(b.work / na.SPEC_NAME / "PYZ-00.toc")
        base = na.read_base_library(b.work / na.SPEC_NAME / "base_library.zip")
        bundle, _ = na.read_bundle(b.internal)
        dists = na.installed([str(b.site), str(b.elsewhere)])
        rows = na.measure(dists, toc, base, bundle, na.executables_beside(b.internal))
        return {r.name: r for r in rows}, bundle


class TestTheShippingSet(_TempBuild):

    def test_the_fixture_installs_what_it_says(self):
        """The floor. Every assertion below is about a subset of these, and a
        site-packages that read as empty would make every 'does not ship' true."""
        rows, _ = self.rows(standard(self.root).finish())
        self.assertEqual(set(rows), SHIPS | {"delta", "setuptools", "decoy"})

    def test_ships_is_exactly_the_distributions_that_reach_the_bundle(self):
        rows, _ = self.rows(standard(self.root).finish())
        self.assertEqual({n for n, r in rows.items() if r.ships}, SHIPS)

    def test_each_route_counts_as_its_own_number(self):
        rows, _ = self.rows(standard(self.root).finish())
        got = {n: (r.modules, r.files, r.record) for n, r in rows.items()}
        self.assertEqual(got["alpha"], (1, 0, 3))
        self.assertEqual(got["beta"], (0, 1, 3))
        self.assertEqual(got["gamma"], (0, 1, 4), "gamma.libs/ by basename")
        self.assertEqual(got["epsilon"], (1, 0, 3), "a module in base_library.zip")
        self.assertEqual(got["pydrc"], (1, 1, 4))
        self.assertEqual(got["pyinstaller"], (1, 1, 4), "_pyi_rth_utils, then the bootloader")
        self.assertEqual(got["delta"], (0, 0, 3))

    def test_a_module_is_matched_by_its_real_path_not_its_name(self):
        """`decoy` installs `alpha/__init__.py` too, from another directory.
        The toc names alpha's file, so the name agreeing is not a match."""
        rows, _ = self.rows(standard(self.root).finish())
        self.assertEqual((rows["decoy"].modules, rows["decoy"].files), (0, 0))
        self.assertFalse(rows["decoy"].ships)

    def test_pyinstaller_ships_on_its_bootloader_alone(self):
        """A build with no runtime hook has no `_pyi_rth_utils` in the PYZ,
        and its executable is still PyInstaller's bootloader."""
        rows, _ = self.rows(standard(self.root, rth_utils=False).finish())
        self.assertEqual((rows["pyinstaller"].modules, rows["pyinstaller"].files), (0, 1))
        self.assertTrue(rows["pyinstaller"].ships)

    def test_the_files_no_distribution_claims_are_grouped_by_top_level_entry(self):
        rows, bundle = self.rows(standard(self.root).finish())
        self.assertEqual(na.unclaimed_files(list(rows.values()), bundle), {
            "base_library.zip": 1, "docs/": 2, "libpython3.11.so.1.0": 1, "licenses/": 1})

    def test_a_namespace_package_is_counted_and_never_taken_as_a_file(self):
        """PyInstaller writes `-` as a namespace package's path. Five of them
        collapsed onto `realpath("-")` in the v1.8.1 build before this."""
        b = standard(self.root).finish()
        toc, pathless = na.read_pyz_toc(b.work / na.SPEC_NAME / "PYZ-00.toc")
        self.assertEqual(pathless, 1)
        self.assertNotIn("ns_package", toc.values())
        self.assertEqual(len(toc), 4)

    def test_a_symlink_is_resolved_to_the_file_it_names(self):
        """PyInstaller on Linux writes `libQt6Core.so.6` at the top of
        `_internal/` as a link into `PySide6/Qt/lib/`. One file, two names."""
        b = standard(self.root).finish()
        try:
            os.symlink(b.internal / "beta" / "_native.so", b.internal / "_native.so")
        except (OSError, NotImplementedError):
            self.skipTest("this platform cannot create a symlink without privileges")
        bundle, links = na.read_bundle(b.internal)
        self.assertEqual(links, 1)
        self.assertNotIn("_native.so", bundle)
        self.assertIn("beta/_native.so", bundle)


class TestTheLicenseFiles(_TempBuild):

    def setUp(self):
        super().setUp()
        self.b = standard(self.root).finish()

    def files(self, wheel):
        files, _ = na.license_files(self.b.wheels / wheel)
        return files

    def test_dist_info_licenses_win_and_keep_their_paths(self):
        files = self.files("alpha-1.0-py3-none-any.whl")
        self.assertEqual(set(files), set(WRITTEN["alpha"]))
        self.assertNotIn(ALPHA_ROOT, files.values(),
                         "the dist-info root was read although licenses/ answered")

    def test_license_file_is_read_when_there_is_no_licenses_directory(self):
        self.assertEqual(self.files("beta-2.0-cp311-cp311-win_amd64.whl"),
                         {"LICENSE.txt": BETA_WIN})

    def test_the_dist_info_root_is_the_last_resort(self):
        self.assertEqual(self.files("gamma-3.0-cp311-cp311-win_amd64.whl"), WRITTEN["gamma"])

    def test_a_vendored_file_is_added_once_and_code_never(self):
        files = self.files("alpha-1.0-py3-none-any.whl")
        self.assertEqual(files.get("alpha/_vendor/thing/LICENSE"), ALPHA_VENDORED)
        self.assertNotIn("alpha/LICENSE", files, "the same bytes shipped twice")
        self.assertNotIn("alpha/license.py", files, "a module was taken for a license")

    def test_the_bytes_are_copied_exactly(self):
        """CRLF and a Latin-1 byte, which a text round trip would change."""
        self.assertEqual(self.files("alpha-1.0-py3-none-any.whl")["LICENSE"], ALPHA_LICENSE)

    def test_a_path_out_of_the_directory_is_refused(self):
        self.b.wheel("evil-1.0-py3-none-any.whl", {
            "evil-1.0.dist-info/METADATA": _meta("evil", "1.0"),
            "evil-1.0.dist-info/licenses/../../../outside": b"x"})
        with self.assertRaises(na.Refusal):
            na.license_files(self.b.wheels / "evil-1.0-py3-none-any.whl")

    def test_the_windows_wheel_is_the_one_read(self):
        self.assertEqual(na.find_wheel(self.b.wheels, "beta", "2.0").name,
                         "beta-2.0-cp311-cp311-win_amd64.whl")
        self.assertIsNone(na.find_wheel(self.b.wheels, "beta", "2.1"),
                          "a wheel of another version was taken")


class TestTheRefusals(_TempBuild):
    """Exit 2 and nothing written, never an empty or partial `licenses/`.

    Each test starts from the build that passes (the first test proves it
    does), breaks one thing, and asserts the refusal names that thing.
    """

    def setUp(self):
        super().setUp()
        self.b = standard(self.root)
        self.b.licenses.mkdir()
        (self.b.licenses / "Apache-2.0.txt").write_bytes(b"supplied by hand\n")
        (self.b.licenses / "stale").mkdir()
        (self.b.licenses / "stale" / "LICENSE").write_bytes(b"left the bundle\n")
        (self.b.licenses / "alpha").mkdir()
        (self.b.licenses / "alpha" / "OLD").write_bytes(b"an older alpha\n")
        self.before = _tree(self.b.licenses)

    def main(self, *extra, windows=False):
        args = ["--workpath", str(self.b.work), "--distpath", str(self.b.dist),
                "--wheels", str(self.b.wheels), "--licenses", str(self.b.licenses),
                "--site-packages", str(self.b.site),
                "--site-packages", str(self.b.elsewhere), *extra]
        if "--online" in extra:
            args.remove("--online")
        else:
            args.append("--offline")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(na, "_is_windows", return_value=windows), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = na.main(args)
        return code, out.getvalue(), err.getvalue()

    def assertRefused(self, phrase, *extra, windows=False):
        code, out, err = self.main(*extra, windows=windows)
        self.assertEqual(code, 2, f"expected a refusal naming {phrase!r}\n{out}\n{err}")
        self.assertIn(phrase, err)
        self.assertEqual(_tree(self.b.licenses), self.before,
                         "a refusal wrote into licenses/")
        return out

    def test_the_complete_build_is_written(self):
        """The positive control. Without it, every refusal below could be a
        tool that refuses everything."""
        self.b.finish()
        code, out, err = self.main()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(_tree(self.b.licenses),
                         {"Apache-2.0.txt": b"supplied by hand\n",
                          **{f"{d}/{rel}": body for d, files in WRITTEN.items()
                             for rel, body in files.items()}})
        self.assertFalse((self.b.licenses / "pydrc").exists(), "DSI's own was copied")
        self.assertFalse((self.b.licenses / "stale").exists(), "a stale directory stayed")
        for name in SHIPS:
            self.assertRegex(out, rf"(?m)^SHIPS +{name} ")

    def test_no_pyz_toc(self):
        self.b.finish(toc=False)
        self.assertRefused("no PYZ toc")

    def test_a_toc_that_lists_no_module_with_a_file(self):
        """It parses, so it is not absent, and it measures nothing."""
        self.b.toc = [("ns_package", "-")]
        self.b.finish()
        self.assertRefused("lists no module with a file")

    def test_no_base_library(self):
        self.b.finish(base_library=False)
        self.assertRefused("no base_library.zip")

    def test_no_internal_folder(self):
        self.b.finish(internal=False)
        self.assertRefused("no _internal/")

    def test_no_executable_beside_internal(self):
        self.b.finish(executable=False)
        self.assertRefused("no executable beside")

    def test_no_distribution_installed(self):
        self.b.finish()
        empty = self.root / "empty-site"
        empty.mkdir()
        self.b.site = self.b.elsewhere = empty
        self.assertRefused("no installed distribution found")

    def test_a_distribution_with_no_record(self):
        """Whether it ships cannot be measured, which is a third state and not
        a 'does not ship'."""
        (self.b.site / "delta-4.0.dist-info" / "RECORD").unlink()
        self.b.finish()
        out = self.assertRefused("could not read the RECORD of delta")
        self.assertRegex(out, r"(?m)^UNREAD +delta ")

    def test_nothing_ships(self):
        b = _Build(self.root / "empty")
        b.install("delta", "4.0", {"delta/__init__.py": b""})
        b.install("setuptools", na.RUNNER_SETUPTOOLS, {"setuptools/__init__.py": b""})
        stdlib = self.root / "empty" / "stdlib" / "json.py"
        stdlib.parent.mkdir(parents=True)
        stdlib.write_bytes(b"")
        b.in_pyz("json", stdlib)
        b.in_internal("docs/a.md", b"# a\n")
        b.licenses = self.b.licenses
        self.b = b.finish()
        self.b.elsewhere.mkdir(parents=True)
        self.assertRefused("no installed distribution reaches the bundle")

    def test_a_missing_wheel(self):
        self.b.finish()
        for p in self.b.wheels.glob("beta-*.whl"):
            p.unlink()
        self.assertRefused("beta==2.0")

    def test_a_wheel_with_no_license_file(self):
        self.b.wheel("gamma-3.0-cp311-cp311-win_amd64.whl", {
            "gamma/__init__.py": b"",
            "gamma-3.0.dist-info/METADATA": _meta("gamma", "3.0", "2.1"),
            "gamma-3.0.dist-info/README.rst": b"readme\n"})
        self.b.finish()
        self.assertRefused("gamma==3.0")

    def test_a_wheel_with_only_a_vendored_file(self):
        """A vendored notice covers the vendored code, not the package."""
        self.b.wheel("gamma-3.0-cp311-cp311-win_amd64.whl", {
            "gamma/_vendor/LICENSE": b"someone else's\n",
            "gamma-3.0.dist-info/METADATA": _meta("gamma", "3.0", "2.1")})
        self.b.finish()
        self.assertRefused("vendored only")

    def test_the_wrong_setuptools_off_windows(self):
        b = self.b
        shutil.rmtree(b.site / f"setuptools-{na.RUNNER_SETUPTOOLS}.dist-info")
        b.install("setuptools", "79.0.1", {"setuptools/__init__.py": b""})
        b.finish()
        self.assertRefused("setuptools 79.0.1")

    def test_no_setuptools_off_windows(self):
        shutil.rmtree(self.b.site / f"setuptools-{na.RUNNER_SETUPTOOLS}.dist-info")
        self.b.finish()
        self.assertRefused("setuptools none")

    def test_a_windows_build_is_not_held_to_the_runners_setuptools(self):
        """The rule exists because a Linux build stands in for the Windows one.
        A Windows build measures itself, so it says so and goes on."""
        shutil.rmtree(self.b.site / f"setuptools-{na.RUNNER_SETUPTOOLS}.dist-info")
        self.b.install("setuptools", "79.0.1", {"setuptools/__init__.py": b""})
        self.b.finish()
        code, out, err = self.main(windows=True)
        self.assertEqual(code, 0, out + err)
        self.assertIn("setuptools: not checked", out)

    def test_a_build_without_pydrc(self):
        self.b.toc = [(n, p) for n, p in self.b.toc if n != "pydrc"]
        shutil.rmtree(self.b.internal / "pydrc")
        self.b.finish()
        self.assertRefused("pydrc does not ship")

    def test_the_bootloader_with_no_pyinstaller_installed(self):
        shutil.rmtree(self.b.site / "pyinstaller-6.22.3.dist-info")
        self.b.toc = [(n, p) for n, p in self.b.toc if n != "_pyi_rth_utils"]
        self.b.finish()
        self.assertRefused("no pyinstaller distribution is installed")

    def test_pip_is_asked_for_the_windows_wheel(self):
        """Online, every wheel comes from `pip download` with the Windows
        tags. pip answering no is a missing wheel, and pip's words are kept."""
        self.b.finish()
        for p in self.b.wheels.glob("*.whl"):
            p.unlink()
        calls = []

        def pip(argv, **_):
            calls.append(argv)
            return mock.Mock(returncode=1, stdout="",
                             stderr="ERROR: No matching distribution found\n")

        with mock.patch.object(na, "_run", pip):
            self.assertRefused("No matching distribution found", "--online")
        self.assertEqual(len(calls), len(WRITTEN))
        argv = next(c for c in calls if "alpha==1.0" in c)
        for flag, value in (("--platform", "win_amd64"), ("--python-version", "3.11"),
                            ("--implementation", "cp"), ("-d", str(self.b.wheels))):
            with self.subTest(flag):
                self.assertEqual(argv[argv.index(flag) + 1], value)
        abis = [argv[i + 1] for i, a in enumerate(argv) if a == "--abi"]
        self.assertEqual(sorted(abis), ["abi3", "cp311", "none"])
        self.assertIn("--no-deps", argv)
        self.assertIn("--only-binary=:all:", argv)
        self.assertNotIn("pydrc==0.23.1", sum(calls, []), "DSI's own was downloaded")


if __name__ == "__main__":
    unittest.main()
