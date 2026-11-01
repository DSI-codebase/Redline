"""Measure which distributions a finished build carries, and copy their license
files from the Windows wheels into ``licenses/``.

    python tools/notices_audit.py [--workpath build] [--distpath dist]
                                  [--wheels DIR] [--offline] [--licenses DIR]
                                  [--site-packages DIR ...]

Run it with the interpreter that ran PyInstaller, after
``pyinstaller packaging/DSI_Redline.spec --noconfirm`` from the repository
root. ``THIRD-PARTY-NOTICES.md`` ("How to re-run the audit") is the procedure
this belongs to, and the Build Windows workflow runs it after every build that
installs PyDRC. Stdlib only, like ``tools/run_tests.py``.

WHAT IT DOES, IN ORDER
----------------------
1. Reads the build: ``<workpath>/DSI_Redline/PYZ-00.toc`` and ``PKG-00.toc``
   (Python literals, read with ``ast.literal_eval``), ``base_library.zip``
   beside them, and every file under ``<distpath>/DSI Redline/_internal/``.
   ``PKG-00.toc`` lists the archive appended to the executable: ``main.py``,
   PyInstaller's bootstrap, and the run-time hooks.
2. For every installed distribution, counts the ``RECORD`` files that reach the
   bundle: a module or script whose real path is in either toc (or whose name
   is in ``base_library.zip``), a file at the same relative path under
   ``_internal/``, or a vendored native library (``<dist>.libs/x``) present by
   basename. Prints each distribution with those three numbers and a SHIPS
   mark, then the ``_internal/`` files and the modules no distribution claims,
   grouped, so the remainder is a number rather than an assumption.
3. ``pip download``\\s the Windows wheel of each shipping distribution. The
   installer is Windows, and a wheel's license files are platform-specific:
   numpy 2.4.6's ``LICENSE.txt`` is 914 lines on Windows and 935 on Linux.
4. Copies each wheel's license files, byte for byte, into
   ``licenses/<METADATA Name>/``: everything under ``<dist-info>/licenses/``,
   else what ``License-File`` names, else LICENSE, LICENCE, COPYING, NOTICE
   and AUTHORS at the dist-info root, plus any license or notice file
   elsewhere in the wheel whose bytes are not already taken (anthropic's
   ``_vendor/httpx_aiohttp/LICENSE`` and ``NOTICE.md``).

Every subdirectory of ``licenses/`` is this tool's output and is rewritten to
the shipping set. The files at the top of ``licenses/`` (the FSF and Apache
texts no wheel supplies) are written by hand and left alone.

A package whose wheel ships no license file of its own is refused unless
``SUPPLIED_BY_HAND`` names it and the text that covers it. That text sits at
the top of ``licenses/`` and is reported as its own state, never as copied.

IT EXITS 2 AND WRITES NOTHING rather than writing an empty or partial answer:
no PYZ toc, no PKG toc, either toc listing nothing with a file, no
``base_library.zip``, no ``_internal/``, no executable beside it, no
distributions, a distribution with no readable ``RECORD``, nothing ships,
PyDRC does not ship, the wrong setuptools on a non-Windows build, a wheel
missing, a wheel that yields no license file of its own and is not listed,
or a ``SUPPLIED_BY_HAND`` entry that is stale (its package no longer ships or
now has a license file) or names a text that is not there.

THREE TRAPS, MEASURED ON 2026-10-31, WHICH THIS HANDLES
-------------------------------------------------------
* **setuptools.** The Windows runner's Python 3.11.9 carries setuptools 65.5.0
  (job log of Build Windows run 41248171957). With setuptools 79, httpx2's
  ``from backports.zstd import`` makes PyInstaller alias ``backports`` to
  setuptools' vendored copy, and setuptools ships from a Linux build and not
  from the Windows one. A Linux build stands in for the Windows one only at the
  runner's version, so any other version is refused there.
* **PyDRC.** The release build installs it whenever ``PYDRC_TOKEN`` is set, and
  it brings ezdxf and pyparsing. A build without it measures a smaller set
  than the one that ships, so its absence is refused. It is DSI's own, so it
  is listed and never copied into ``licenses/``.
* **pyinstaller.** It is a build tool AND it ships: the executable beside
  ``_internal/`` is its bootloader, and ``_pyi_rth_utils`` is in the PYZ. The
  executable is counted against it directly, so it cannot fall out of the set
  when the app stops needing a runtime hook.

WHAT IT DOES NOT READ
---------------------
The Python interpreter's own license, which the notices record as not checked.
Until 2026-11-01 it did not read ``PKG-00.toc`` either, so a run-time hook from
any distribution but PyInstaller would have shipped inside the executable with
that distribution reported as not shipping. In the v1.8.1 build all four hooks
are PyInstaller's own (inspect, pkgutil, multiprocessing, pyside6).
"""

from __future__ import annotations

import argparse
import ast
import collections
import email.parser
import hashlib
import importlib.metadata
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SPEC_NAME = "DSI_Redline"     # packaging/DSI_Redline.spec, so the workpath subdirectory
APP_NAME = "DSI Redline"      # COLLECT(name=...), so the folder under distpath

# Distributions that are DSI's own. They are measured and listed, and never
# copied into licenses/, because there is no third-party notice to carry.
OWN = {"pydrc": "DSI's own, its pyproject.toml declares Proprietary"}

# The release build installs these, so a build without them is not the
# release build's set.
REQUIRED = {"pydrc": "the release build installs PyDRC whenever PYDRC_TOKEN is "
                     "set, and it brings ezdxf and pyparsing. Install "
                     "requirements-drc.txt at the ref packaging/pydrc-ref.txt "
                     "names, rebuild, and run this again"}

# A package whose wheel ships no license file of its own, mapped to the file at
# the top of licenses/ that supplies its text instead, and why. The PySide6 and
# shiboken6 6.11.2 wheels were that case (measured 2026-09-01 as shipping none),
# and an entry for one reads
#     "PySide6": ("LGPL-3.0.txt", "the 6.11.2 wheel ships no license file"),
# ONLY AN EMPTY WHEEL NEEDS AN ENTRY. The 6.11.3 Qt wheels ship
# LicenseRef-Qt-Commercial.txt, so they are not listed, although
# licenses/LGPL-3.0.txt is supplied for them too (tests/test_notices_ship.py
# holds that file). An entry is refused when its package's wheel ships a
# license file again and when its package no longer ships, so the list cannot
# outlive its reason.
SUPPLIED_BY_HAND: dict[str, tuple[str, str]] = {}

RUNNER_SETUPTOOLS = "65.5.0"

PIP_DOWNLOAD = ("download", "--no-deps", "--only-binary=:all:",
                "--platform", "win_amd64", "--python-version", "3.11",
                "--implementation", "cp",
                "--abi", "cp311", "--abi", "abi3", "--abi", "none")

# At the dist-info root, when neither licenses/ nor License-File answers.
ROOT_LICENSE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.I)
# Elsewhere in the wheel. A basename only, and never code or a binary.
VENDORED_LICENSE = re.compile(r"licen[cs]e|copying|notice", re.I)
NOT_A_TEXT = {".py", ".pyc", ".pyi", ".pyd", ".pyx", ".pxd", ".so", ".dll",
              ".dylib", ".exe", ".lib", ".a", ".h", ".hpp", ".c", ".cpp",
              ".js", ".qml", ".png", ".svg", ".json"}

# Both patched by tests/test_notices_audit.py: `_run` so pip is never called,
# and `_is_windows` so the setuptools rule is tested on every platform.
_run = subprocess.run


def _is_windows() -> bool:
    return sys.platform == "win32"


class Refusal(Exception):
    """The answer would be empty or partial. main() exits 2 and writes nothing."""


# --------------------------------------------------------------- the build --

def _toc_entries(data) -> list:
    """The ``(name, path, typecode)`` list inside a PyInstaller toc literal.

    ``PYZ-00.toc`` is ``(pyz path, [entries])`` and ``PKG-00.toc`` is an
    eleven-field tuple with its entries third, so the list is found by its
    shape rather than by its position.
    """
    if isinstance(data, list):
        return data
    for field in data if isinstance(data, tuple) else ():
        if (isinstance(field, list) and field
                and all(isinstance(e, (tuple, list)) and len(e) == 3 for e in field)):
            return field
    return []


def _read_toc(path: pathlib.Path, typecodes) -> tuple[dict[str, str], int]:
    """``({real path: name}, pathless)`` for the entries whose typecode starts
    with one of ``typecodes`` (every entry when it is None)."""
    toc, pathless = {}, 0
    for entry in _toc_entries(ast.literal_eval(path.read_text(encoding="utf-8"))):
        if not isinstance(entry, (tuple, list)) or len(entry) < 3:
            continue
        if typecodes and not str(entry[2]).startswith(typecodes):
            continue
        if isinstance(entry[1], str) and os.path.isabs(entry[1]):
            toc[os.path.realpath(entry[1])] = entry[0]
        else:
            pathless += 1
    return toc, pathless


def read_pyz_toc(path: pathlib.Path) -> tuple[dict[str, str], int]:
    """``({real path: module name}, pathless)`` for the modules in ``PYZ-00.toc``.

    A namespace package has no file, and PyInstaller writes its path as ``-``
    (five of them in the v1.8.1 build, ``opentelemetry`` among them). Taken
    as a path, ``realpath("-")`` is a file in the working directory, and five
    module names collapsed onto it. Only an absolute path is a module's file,
    and the rest are counted rather than dropped.
    """
    if not path.is_file():
        raise Refusal(f"no PYZ toc at {path}. Build packaging/DSI_Redline.spec "
                      "first, and pass the --workpath PyInstaller used")
    toc, pathless = _read_toc(path, None)
    if not toc:
        raise Refusal(f"{path} parsed and lists no module with a file")
    return toc, pathless


def read_pkg_toc(path: pathlib.Path) -> dict[str, str]:
    """``{real path: name}`` for the code in the archive appended to the executable.

    That archive is not under ``_internal/`` and not in the PYZ: it holds the
    app's own ``main.py``, PyInstaller's bootstrap, and the run-time hooks,
    small scripts that run before the app does. A run-time hook can come from
    a distribution other than PyInstaller (``pyinstaller-hooks-contrib``, or a
    package that ships its own hooks), and its code then ships inside the
    executable, so the scripts and modules here are matched like PYZ modules.
    The rest of the archive (its options and the PYZ itself) is not code.
    """
    if not path.is_file():
        raise Refusal(f"no PKG toc at {path}, so this is not a finished "
                      "PyInstaller build")
    toc, _ = _read_toc(path, ("PYSOURCE", "PYMODULE"))
    if not toc:
        raise Refusal(f"{path} parsed and lists no script with a file")
    return toc


def read_base_library(path: pathlib.Path) -> set[str]:
    """The dotted module names compiled into ``base_library.zip``."""
    if not path.is_file():
        raise Refusal(f"no base_library.zip at {path}, so this is not a "
                      "finished PyInstaller build")
    names = set()
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            if member.endswith(".pyc"):
                parts = member[:-4].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                names.add(".".join(parts))
    return names


def read_bundle(internal: pathlib.Path) -> tuple[set[str], int]:
    """``(files, symlinks)``: every file under ``_internal/`` as a POSIX path
    relative to it, and how many entries were symlinks.

    PyInstaller on Linux writes symlinks beside the real libraries
    (``libQt6Core.so.6`` at the top, pointing into ``PySide6/Qt/lib/``). A link
    is resolved to its target, so a file is one file however many names it has.
    """
    if not internal.is_dir():
        raise Refusal(f"no _internal/ at {internal}. Pass the --distpath "
                      "PyInstaller used")
    root = os.path.realpath(internal)
    files, links = set(), 0
    for dirpath, dirnames, filenames in os.walk(internal):
        for d in list(dirnames):
            if os.path.islink(os.path.join(dirpath, d)):
                links += 1
                dirnames.remove(d)
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                links += 1
                target = os.path.realpath(full)
                if target.startswith(root + os.sep) and os.path.isfile(target):
                    files.add(pathlib.Path(os.path.relpath(target, root)).as_posix())
                    continue
            files.add(pathlib.Path(os.path.relpath(full, internal)).as_posix())
    if not files:
        raise Refusal(f"{internal} holds no file")
    return files, links


def executables_beside(internal: pathlib.Path) -> list[str]:
    """The files beside ``_internal/``, which is where the bootloader lands."""
    return sorted(p.name for p in internal.parent.iterdir() if p.is_file())


# ------------------------------------------------------- the distributions --

def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed(paths: list[str] | None = None) -> list[importlib.metadata.Distribution]:
    """Each installed distribution once, the first on the path winning, as import does."""
    found = (importlib.metadata.distributions(path=paths) if paths is not None
             else importlib.metadata.distributions())
    seen, out = set(), []
    for dist in found:
        name = dist.metadata["Name"] if dist.metadata else None
        key = normalize(name) if name else repr(getattr(dist, "_path", dist))
        if key in seen:
            continue
        seen.add(key)
        out.append(dist)
    return out


def _module_name(rel: str) -> str | None:
    if not rel.endswith(".py") or "/__pycache__/" in rel:
        return None
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


class Row:
    """One distribution's measurement: the three numbers and what they decide."""

    def __init__(self, name, version, modules, files, record, readable=True, notes=()):
        self.name, self.version = name, version
        self.modules, self.files, self.record = modules, files, record
        self.readable = readable
        self.notes = list(notes)
        self.claimed_files: set[str] = set()
        self.claimed_modules: set[str] = set()

    @property
    def ships(self) -> bool:
        return self.modules + self.files > 0

    @property
    def key(self) -> str:
        return normalize(self.name)


def measure(dists, toc: dict[str, str], base_modules: set[str],
            bundle: set[str], executables: list[str]) -> list[Row]:
    """A Row for every distribution, in name order."""
    basenames = collections.defaultdict(set)
    for rel in bundle:
        basenames[rel.rsplit("/", 1)[-1]].add(rel)
    rows = []
    for dist in dists:
        name = dist.metadata["Name"] if dist.metadata else None
        files = dist.files
        if not name or files is None:
            rows.append(Row(name or str(getattr(dist, "_path", "?")),
                            dist.version if name else "?", 0, 0, 0, readable=False,
                            notes=["no readable RECORD"]))
            continue
        row = Row(name, dist.version, 0, 0, len(files))
        for f in files:
            rel = pathlib.PurePosixPath(*f.parts).as_posix()
            real = os.path.realpath(dist.locate_file(f))
            if real in toc:
                row.modules += 1
                row.claimed_modules.add(real)
                continue
            mod = _module_name(rel)
            if mod and mod in base_modules:
                row.modules += 1
                continue
            if rel in bundle:
                row.files += 1
                row.claimed_files.add(rel)
                continue
            first = rel.split("/", 1)[0]
            if first.endswith(".libs") and "/" in rel:
                hits = basenames.get(rel.rsplit("/", 1)[-1], set())
                if hits:
                    row.files += 1
                    row.claimed_files |= hits
        if row.key == "pyinstaller" and executables:
            row.files += len(executables)
            row.notes.append("bootloader: " + ", ".join(executables))
        if row.key in OWN:
            row.notes.append(OWN[row.key] + ", not copied")
        rows.append(row)
    return sorted(rows, key=lambda r: r.key)


def unclaimed_files(rows: list[Row], bundle: set[str]) -> dict[str, int]:
    """``{top-level entry: file count}`` for the files no distribution claims."""
    claimed = set().union(*(r.claimed_files for r in rows)) if rows else set()
    groups = collections.Counter()
    for rel in bundle - claimed:
        top, sep, _ = rel.partition("/")
        groups[top + "/" if sep else top] += 1
    return dict(sorted(groups.items()))


def unclaimed_modules(rows: list[Row], toc: dict[str, str]) -> dict[str, int]:
    """``{search-path root: module count}`` for the PYZ modules no distribution claims."""
    claimed = set().union(*(r.claimed_modules for r in rows)) if rows else set()
    groups = collections.Counter()
    for real, name in toc.items():
        if real in claimed:
            continue
        p = pathlib.Path(real)
        depth = len(name.split(".")) - (0 if p.stem == "__init__" else 1)
        try:
            root = str(p.parents[depth])
        except IndexError:
            root = str(p.parent)
        groups[root] += 1
    return dict(sorted(groups.items()))


# --------------------------------------------------------------- the wheels --

def _wheel_parts(filename: str) -> tuple[str, str, str] | None:
    """``(normalized name, version, platform tag)`` from a wheel's file name."""
    if not filename.endswith(".whl"):
        return None
    parts = filename[:-4].split("-")
    if len(parts) not in (5, 6):
        return None
    return normalize(parts[0]), parts[1], parts[-1]


def find_wheel(wheels: pathlib.Path, name: str, version: str) -> pathlib.Path | None:
    """The one wheel for ``name==version`` in ``wheels``, Windows over pure."""
    ranked = collections.defaultdict(list)
    for p in sorted(wheels.glob("*.whl")) if wheels.is_dir() else []:
        parts = _wheel_parts(p.name)
        if parts and parts[0] == normalize(name) and parts[1] == version:
            if "win_amd64" in parts[2]:
                ranked[0].append(p)
            elif parts[2] == "any":
                ranked[1].append(p)
    best = ranked[min(ranked)] if ranked else []
    return best[0] if len(best) == 1 else None


def download(name: str, version: str, wheels: pathlib.Path) -> str | None:
    """``pip download`` the Windows wheel. None on success, else pip's last words."""
    wheels.mkdir(parents=True, exist_ok=True)
    proc = _run([sys.executable, "-m", "pip", *PIP_DOWNLOAD,
                 f"{name}=={version}", "-d", str(wheels)],
                capture_output=True, text=True)
    if proc.returncode == 0:
        return None
    lines = [ln for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
    return lines[-1] if lines else f"pip exited {proc.returncode}"


def _safe(rel: str) -> str:
    p = pathlib.PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise Refusal(f"a wheel names the license file {rel!r}, which would "
                      "land outside its directory")
    return p.as_posix()


def license_files(wheel: pathlib.Path) -> tuple[dict[str, bytes], dict[str, str]]:
    """``(files, rules)``: ``{path under licenses/<Name>/: bytes}`` and which
    rule took each one, from one wheel.

    The package's own files come from the dist-info, by the first rule that
    finds any. A vendored file elsewhere in the wheel is added when its bytes
    are not already taken, which is what keeps numpy's in-package copies of
    the files its ``licenses/`` already holds from shipping twice.
    """
    with zipfile.ZipFile(wheel) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        infos = sorted({n.split("/", 1)[0] for n in names
                        if "/" in n and n.split("/", 1)[0].endswith(".dist-info")})
        if len(infos) != 1:
            raise Refusal(f"{wheel.name} holds {len(infos)} .dist-info directories")
        di = infos[0]
        meta = email.parser.HeaderParser().parsestr(
            z.read(f"{di}/METADATA").decode("utf-8", "replace"))
        files: dict[str, bytes] = {}
        rules: dict[str, str] = {}

        under = sorted(n for n in names if n.startswith(f"{di}/licenses/"))
        for n in under:
            rel = _safe(n[len(f"{di}/licenses/"):])
            files[rel], rules[rel] = z.read(n), "dist-info licenses/"
        if not files:
            for named in meta.get_all("License-File") or []:
                for candidate in (f"{di}/licenses/{named}", f"{di}/{named}"):
                    if candidate in names:
                        rel = _safe(named)
                        files[rel], rules[rel] = z.read(candidate), "License-File"
                        break
        if not files:
            for n in sorted(names):
                rest = n[len(di) + 1:]
                if n.startswith(di + "/") and "/" not in rest and ROOT_LICENSE.match(rest):
                    files[rest], rules[rest] = z.read(n), "dist-info root"

        taken = {hashlib.sha256(b).digest() for b in files.values()}
        for n in sorted(names):
            if n.startswith(di + "/"):
                continue
            base = n.rsplit("/", 1)[-1]
            if not VENDORED_LICENSE.search(base):
                continue
            if set(s.lower() for s in pathlib.PurePosixPath(base).suffixes) & NOT_A_TEXT:
                continue
            body = z.read(n)
            digest = hashlib.sha256(body).digest()
            if digest in taken:
                continue
            rel = _safe(n)
            if rel in files:
                raise Refusal(f"{wheel.name}: {rel} is both a dist-info license "
                              "file and a different vendored one")
            files[rel], rules[rel] = body, "vendored"
            taken.add(digest)
    return files, rules


# ----------------------------------------------------------------- writing --

def _tree(folder: pathlib.Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob("*") if p.is_file()} if folder.is_dir() else {}


def write_licenses(out: pathlib.Path, wanted: dict[str, dict[str, bytes]]) -> dict[str, list[str]]:
    """Make every subdirectory of ``out`` exactly ``wanted``. Top-level files stay."""
    out.mkdir(parents=True, exist_ok=True)
    report = {"added": [], "changed": [], "unchanged": [], "removed": []}
    existing = {p.name for p in out.iterdir() if p.is_dir()}
    for name in sorted(existing - set(wanted)):
        shutil.rmtree(out / name)
        report["removed"].append(name)
    for name, files in sorted(wanted.items()):
        folder = out / name
        before = _tree(folder)
        if before == files:
            report["unchanged"].append(name)
            continue
        report["changed" if name in existing else "added"].append(name)
        if folder.exists():
            shutil.rmtree(folder)
        for rel, body in files.items():
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
    return report


# -------------------------------------------------------------------- main --

def _print_table(rows: list[Row]) -> None:
    width = max([len(r.name) for r in rows] + [12])
    print(f"{'':7}{'distribution':{width}}  {'version':14}{'modules':>8}{'files':>7}{'RECORD':>8}")
    for r in rows:
        mark = "SHIPS" if r.ships else ("UNREAD" if not r.readable else "")
        note = f"   ({'; '.join(r.notes)})" if r.notes else ""
        print(f"{mark:7}{r.name:{width}}  {r.version:14}{r.modules:8d}{r.files:7d}{r.record:8d}{note}")


def run(args) -> int:
    build = pathlib.Path(args.workpath) / SPEC_NAME
    internal = pathlib.Path(args.distpath) / APP_NAME / "_internal"
    toc, pathless = read_pyz_toc(build / "PYZ-00.toc")
    pkg = read_pkg_toc(build / "PKG-00.toc")
    code = {**toc, **pkg}
    base_modules = read_base_library(build / "base_library.zip")
    bundle, links = read_bundle(internal)
    executables = executables_beside(internal)
    if not executables:
        raise Refusal(f"no executable beside {internal}, so this is not a "
                      "finished one-folder build")
    dists = installed(args.site_packages)
    if not dists:
        raise Refusal("no installed distribution found in "
                      + (", ".join(args.site_packages) if args.site_packages else "sys.path"))

    print(f"Build:  {build}  ({len(toc)} PYZ modules with a file, {pathless} "
          f"without one, {len(pkg)} scripts and modules in the executable's "
          f"archive, {len(base_modules)} in base_library.zip)")
    print(f"Folder: {internal}  ({len(bundle)} files, {links} symlinks resolved "
          f"to their targets, beside: {', '.join(executables)})")
    print()
    rows = measure(dists, code, base_modules, bundle, executables)
    _print_table(rows)
    shipping = [r for r in rows if r.ships]
    unread = [r for r in rows if not r.readable]
    print(f"\n{len(rows)} distributions: {len(shipping)} ship, "
          f"{len(rows) - len(shipping) - len(unread)} do not, {len(unread)} could not be read.")

    loose = unclaimed_files(rows, bundle)
    print(f"\n_internal/ files no distribution claims, by top-level entry "
          f"({sum(loose.values())} of {len(bundle)}):")
    for top, n in loose.items():
        print(f"  {n:5d}  {top}")
    loose_mods = unclaimed_modules(rows, code)
    print(f"\nModules in the PYZ and the executable's archive that no "
          f"distribution claims, by search-path root "
          f"({sum(loose_mods.values())} of {len(code)}):")
    for root, n in loose_mods.items():
        print(f"  {n:5d}  {root}")
    print()

    if unread:
        raise Refusal("could not read the RECORD of " + ", ".join(r.name for r in unread)
                      + ", so whether they ship is unknown")
    if not shipping:
        raise Refusal("no installed distribution reaches the bundle. Run this "
                      "with the interpreter that ran PyInstaller")
    by_key = {r.key: r for r in rows}
    if _is_windows():
        print("setuptools: not checked, because this is a Windows build and "
              "measures itself.")
    else:
        st = by_key.get("setuptools")
        if st is None or st.version != RUNNER_SETUPTOOLS:
            have = st.version if st else "none"
            raise Refusal(
                f"this build environment carries setuptools {have}, and the "
                f"Windows runner's Python 3.11.9 carries {RUNNER_SETUPTOOLS}. "
                "With setuptools 79, httpx2's `from backports.zstd import` makes "
                "PyInstaller alias `backports` to setuptools' vendored copy, so "
                "setuptools ships from a Linux build and not from the Windows "
                f"one. Run `python -m pip install setuptools=={RUNNER_SETUPTOOLS}`, "
                "rebuild, and run this again")
        print(f"setuptools: {st.version}, the Windows runner's version.")
    for key, why in REQUIRED.items():
        if key not in by_key or not by_key[key].ships:
            raise Refusal(f"{key} does not ship from this build: {why}")
    if "pyinstaller" not in by_key:
        raise Refusal(f"{', '.join(executables)} is PyInstaller's bootloader and "
                      "no pyinstaller distribution is installed here, so this is "
                      "not the interpreter that ran the build")
    supplied = {normalize(k): (k, f) for k, (f, _) in SUPPLIED_BY_HAND.items()}
    gone = sorted(name for key, (name, _) in supplied.items()
                  if key not in by_key or not by_key[key].ships)
    if gone:
        raise Refusal(f"SUPPLIED_BY_HAND names {', '.join(gone)}, which does not "
                      "ship from this build. Remove the entry from "
                      "tools/notices_audit.py, and the text from licenses/ if "
                      "nothing else needs it")

    third_party = [r for r in shipping if r.key not in OWN]
    wheels = pathlib.Path(args.wheels) if args.wheels else build.parent / "notices-wheels"
    print(f"\nWheels for {len(third_party)} distributions, in {wheels}"
          + (" (offline)" if args.offline else ""))
    found, missing = {}, []
    for r in third_party:
        why = None if args.offline else download(r.name, r.version, wheels)
        wheel = find_wheel(wheels, r.name, r.version)
        if wheel is None:
            missing.append(f"{r.name}=={r.version}: "
                           + (why or "no single wheel of that version in " + str(wheels)))
        else:
            found[r.name] = wheel
    if missing:
        raise Refusal(f"{len(missing)} of {len(third_party)} wheels are missing:\n  "
                      + "\n  ".join(missing))

    out = pathlib.Path(args.licenses)
    wanted, by_hand, empty, unsupplied, stale = {}, {}, [], [], []
    for r in third_party:
        files, rules = license_files(found[r.name])
        own = [rel for rel in files if rules[rel] != "vendored"]
        hand = supplied.get(r.key)
        if hand and own:
            stale.append(f"{r.name}=={r.version}: {found[r.name].name} ships "
                         f"{len(own)} license files of its own")
            continue
        if hand:
            if not (out / hand[1]).is_file():
                unsupplied.append(f"{r.name}=={r.version}: licenses/{hand[1]}")
                continue
            by_hand[r.name] = hand[1]
            if files:
                wanted[r.name] = files
            print(f"  {r.name} {r.version}: {found[r.name].name}, no license file "
                  f"of its own, supplied by hand as licenses/{hand[1]}")
            continue
        if not own:
            empty.append(f"{r.name}=={r.version} ({found[r.name].name}"
                         + (f", {len(files)} vendored only" if files else "") + ")")
            continue
        wanted[r.name] = files
        by_rule = collections.Counter(rules.values())
        print(f"  {r.name} {r.version}: {found[r.name].name}, {len(files)} files ("
              + ", ".join(f"{n} {rule}" for rule, n in sorted(by_rule.items())) + ")")
    if empty:
        raise Refusal(f"{len(empty)} wheels yield no license file of their own:\n  "
                      + "\n  ".join(empty)
                      + "\nSupply the text at the top of licenses/, list it in the "
                        "notices, and name it in SUPPLIED_BY_HAND in tools/notices_audit.py")
    if unsupplied:
        raise Refusal("SUPPLIED_BY_HAND names a text that is not there:\n  "
                      + "\n  ".join(unsupplied))
    if stale:
        raise Refusal("SUPPLIED_BY_HAND lists packages whose wheels now ship a "
                      "license file, so the entry no longer does anything:\n  "
                      + "\n  ".join(stale)
                      + "\nRemove each from tools/notices_audit.py")

    report = write_licenses(out, wanted)
    total = sum(len(f) for f in wanted.values())
    copied = len(third_party) - len(by_hand)
    print(f"\n{len(third_party)} third-party packages ship: {copied} with license "
          f"files of their own, {len(by_hand)} supplied by hand"
          + (f" ({', '.join(f'{n}: licenses/{f}' for n, f in sorted(by_hand.items()))})"
             if by_hand else "") + ".")
    print(f"Wrote {out}: {len(wanted)} directories, {total} files.")
    for state in ("added", "changed", "removed", "unchanged"):
        names = report[state]
        print(f"  {state:9} {len(names):3d}" + (f"  {', '.join(names)}" if names and state != "unchanged" else ""))
    if report["added"] or report["removed"]:
        print("A directory added or removed is a package that joined or left the "
              "bundle. Its entry in THIRD-PARTY-NOTICES.md is written by hand.")
    return 0


def parse(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="notices_audit.py",
        description="Measure which distributions a finished PyInstaller build "
                    "carries and copy each one's license files from its Windows "
                    "wheel into licenses/. Exits 2 and writes nothing rather than "
                    "an empty or partial answer.")
    p.add_argument("--workpath", default=str(REPO / "build"),
                   help="PyInstaller's --workpath (default: build/)")
    p.add_argument("--distpath", default=str(REPO / "dist"),
                   help="PyInstaller's --distpath (default: dist/)")
    p.add_argument("--wheels", help="where the wheels are downloaded "
                   "(default: <workpath>/notices-wheels)")
    p.add_argument("--offline", action="store_true",
                   help="do not run pip, and use the wheels already in --wheels")
    p.add_argument("--licenses", default=str(REPO / "licenses"),
                   help="the directory to rewrite (default: licenses/)")
    p.add_argument("--site-packages", action="append",
                   help="read distributions from this directory instead of "
                        "sys.path (repeatable)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except Refusal as e:
        print(f"\nnotices_audit: refused: {e}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
