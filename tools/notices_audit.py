"""Measure what the frozen build ships, for THIRD-PARTY-NOTICES.md and licenses/.

The notices must name every distribution the installer carries, and `licenses/`
must carry each one's own license files. Neither can be read off
`requirements.txt`: the 2026-09-01 notices named ten packages and the v1.8.1
bundle carried 39, most of them installed by those ten. So this reads the
BUILD, not the requirements.

    python tools/notices_audit.py shipped --build build/DSI_Redline --dist "dist/DSI Redline" --write shipped.txt
    python tools/notices_audit.py fetch shipped.txt --dest wheels
    python tools/notices_audit.py copy shipped.txt --wheels wheels --licenses licenses [--check] [--prune]
    python tools/notices_audit.py holders shipped.txt --wheels wheels [--licenses licenses]

`shipped` must run under the interpreter that built the bundle, because it
reads that interpreter's installed distributions. The order, and the two traps
measured on 2026-10-31, are in CI.md under "The notices name what the build
ships". Build Windows runs `shipped`, `fetch` and `copy --check` on every build
that installs PyDRC, and fails a tag build on a difference.

`shipped` reads three places the build put code and files: the PYZ archive
(`PYZ-00.toc`), the archive appended to `DSI Redline.exe` (`PKG-00.toc`, which
holds `main.py`, PyInstaller's bootstrap and the run-time hooks), and the files
under `_internal/`.

A wheel that ships no license file has its text supplied by hand at the top of
licenses/, and `SUPPLIED_BY_HAND` below names it. Such a package is reported as
supplied by hand, its own state, and never as copied or clean.

Exit 0 when done, 1 when `copy --check` finds licenses/ out of step with the
wheels, 2 when it refuses: a missing or empty input, a build with no PYZ or no
PKG table of contents or one that lists no code, no installed distribution
read, nothing shipping, a wheel that is missing or holds no license file and is
not supplied by hand, or a `SUPPLIED_BY_HAND` entry whose text is not there,
whose wheel ships a license file again, or whose package no longer ships. An
empty answer reads the same as a clean one, so it is never written.

Stdlib only, like tools/run_tests.py.
"""

from __future__ import annotations

import argparse
import ast
import email.parser
import hashlib
import importlib.metadata as md
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field

REFUSED = 2
DRIFT = 1

# DSI's own code is not a third-party notice. PyDRC is bundled whenever the
# build installs it, and it is named in the notices' "Not covered here".
DEFAULT_EXCLUDE = ("pydrc",)

# The installer is Windows, and a wheel's license file can differ by platform:
# numpy 2.4.6's LICENSE.txt is 914 lines in the win_amd64 wheel and 935 in the
# Linux one. So the texts come from the Windows wheels, whatever builds here.
WINDOWS = ("--platform", "win_amd64", "--python-version", "3.11",
           "--implementation", "cp", "--abi", "cp311", "--abi", "abi3", "--abi", "none")

# A package whose wheel ships no license file, mapped to the file at the top of
# licenses/ that carries its text instead, and why. The PySide6 and shiboken6
# 6.11.2 wheels were that case (2026-09-01), and an entry for one reads
#     "PySide6": ("LGPL-3.0.txt", "the 6.11.2 wheel ships no license file"),
# ONLY A WHEEL THE TOOL WOULD OTHERWISE REFUSE NEEDS AN ENTRY. The 6.11.3 Qt
# wheels ship LicenseRef-Qt-Commercial.txt, so the list is empty, although
# licenses/LGPL-3.0.txt is supplied for them too. An entry is refused when its
# text is not there, when its wheel ships a license file again, and when its
# package no longer ships, so it cannot outlive its reason. Keys match package
# names the way pip matches them (norm). tests/test_notices_ship.py reads this.
SUPPLIED_BY_HAND: dict[str, tuple[str, str]] = {}

# The code in the archive appended to the executable. The rest of PKG-00.toc is
# the archive's options and the PYZ itself, and none of that is a file a
# distribution's RECORD names.
PKG_CODE = ("PYSOURCE", "PYMODULE")

LICENSE_NAME = re.compile(r"^(licen[cs]e|copying|notice|authors)", re.I)
NOT_A_TEXT = (".py", ".pyc", ".pyi", ".pyd", ".dll", ".so", ".dylib",
              ".h", ".c", ".cpp", ".pyx", ".pxd")


class Refusal(Exception):
    """An input this cannot measure. Printed, and the exit code is 2."""


def norm(name: str) -> str:
    """PEP 503 name normalization, so `PyYAML`, `pyyaml` and `py_yaml` match."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _same(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


# ---------------------------------------------------------------- shipped

@dataclass
class Row:
    name: str
    version: str
    pyz: int
    pkg: int
    files: int
    record: int

    @property
    def ships(self) -> bool:
        return bool(self.pyz or self.pkg or self.files)


@dataclass
class Measurement:
    rows: list[Row]
    bundle_files: int
    unclaimed: dict[str, int] = field(default_factory=dict)
    pkg_code: int = 0
    pkg_unclaimed: list[str] = field(default_factory=list)


def toc_entries(data: object) -> list:
    """The `(name, path, typecode)` list inside a PyInstaller toc literal.

    Found by its shape, never by its position: `PYZ-00.toc` is `(archive,
    entries)` with the list second, and `PKG-00.toc` is eleven fields with the
    list third and an empty list (`upx_exclude`) seventh. So the list is the
    one field that is a non-empty list of three-item entries. None, or two,
    returns None and the caller refuses.
    """
    fields = data if isinstance(data, tuple) else ()
    found = [f for f in fields if isinstance(f, list) and f
             and all(isinstance(e, (tuple, list)) and len(e) == 3 for e in f)]
    return found[0] if len(found) == 1 else None


def _toc_paths(toc: pathlib.Path, typecodes: tuple[str, ...] | None = None) -> dict[str, str]:
    """`{source path: entry name}` for the toc's entries that have a source path,
    of `typecodes` only when it is given."""
    try:
        data = ast.literal_eval(toc.read_text(encoding="utf-8"))
    except (ValueError, SyntaxError) as exc:
        raise Refusal(f"{toc} is not a Python literal: {exc}")
    entries = toc_entries(data)
    if entries is None:
        raise Refusal(f"{toc} holds no single list of (name, path, typecode) "
                      "entries, so it is not a PyInstaller table of contents")
    return {_same(path): name for name, path, code in entries
            if isinstance(path, str) and path
            and (typecodes is None or code in typecodes)}


def pyz_paths(build: pathlib.Path) -> set[str]:
    """The source path of every module PyInstaller put in the PYZ archive."""
    toc = build / "PYZ-00.toc"
    if not toc.is_file():
        raise Refusal(f"no PYZ-00.toc in {build}. --build is the PyInstaller "
                      "workpath's spec folder, e.g. build/DSI_Redline")
    paths = set(_toc_paths(toc))
    if not paths:
        raise Refusal(f"{toc} lists no module with a source path")
    return paths


def pkg_paths(build: pathlib.Path) -> dict[str, str]:
    """`{source path: name}` for the scripts and modules in the archive
    appended to the executable.

    That archive is neither the PYZ nor `_internal/`. It holds `main.py`,
    PyInstaller's bootstrap and the run-time hooks, small scripts that run
    before the app does. A hook from `pyinstaller-hooks-contrib`, or from a
    package that ships its own, ships inside `DSI Redline.exe`, so without
    this its distribution reads as not shipping. Only `PYSOURCE` and
    `PYMODULE` entries are code. Measured on a Linux build on 2026-11-01:
    10 of them, 5 of which are PyInstaller's (its bootstrap and four hooks).
    """
    toc = build / "PKG-00.toc"
    if not toc.is_file():
        raise Refusal(f"no PKG-00.toc in {build}, so the archive appended to the "
                      "executable cannot be read. --build is the PyInstaller "
                      "workpath's spec folder, e.g. build/DSI_Redline")
    paths = _toc_paths(toc, PKG_CODE)
    if not paths:
        raise Refusal(f"{toc} lists no {' or '.join(PKG_CODE)} entry with a "
                      "source path, so the executable's own code is not read")
    return paths


def bundle_listing(dist: pathlib.Path) -> set[str]:
    """Every file under _internal/, as a path relative to it."""
    internal = dist / "_internal"
    if not internal.is_dir():
        raise Refusal(f"no _internal/ in {dist}. --dist is the one-folder app, "
                      'e.g. "dist/DSI Redline"')
    listing = {p.relative_to(internal).as_posix() for p in internal.rglob("*")
               if p.is_file() or p.is_symlink()}
    if not listing:
        raise Refusal(f"{internal} holds no file")
    return listing


def measure(build: pathlib.Path, dist: pathlib.Path,
            site: list[str] | None = None) -> Measurement:
    """Which installed distributions reach the bundle, and by how much.

    A distribution reaches it when a file its RECORD lists does: a module whose
    source is in the PYZ, a script or module in the archive appended to the
    executable, a file at the same relative path under _internal/, or a
    vendored native library (`<dist>.libs/<lib>`) present by basename.
    """
    in_pyz = pyz_paths(build)
    in_pkg = pkg_paths(build)
    files = bundle_listing(dist)
    by_basename: dict[str, list[str]] = {}
    for rel in files:
        by_basename.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
    found = md.distributions(path=site) if site is not None else md.distributions()
    claimed: set[str] = set()
    pkg_claimed: set[str] = set()
    rows = []
    for d in found:
        record = list(d.files or [])
        pyz = pkg = hits = 0
        for f in record:
            rel = f.as_posix()
            real = _same(str(d.locate_file(f)))
            if real in in_pyz:
                pyz += 1
            if real in in_pkg:
                pkg += 1
                pkg_claimed.add(real)
            if rel in files:
                hits += 1
                claimed.add(rel)
            # A vendored library can land both at its own path and flattened
            # beside the executable, so it claims every copy by basename.
            if ".libs/" in rel and f.name in by_basename:
                hits += rel not in files
                claimed.update(by_basename[f.name])
        rows.append(Row(d.metadata["Name"], d.version, pyz, pkg, hits, len(record)))
    if not rows:
        raise Refusal("no installed distribution was read. Run this under the "
                      "interpreter that built the bundle, or pass --site")
    unclaimed: dict[str, int] = {}
    for rel in files:
        if rel not in claimed:
            top = rel.split("/", 1)[0]
            unclaimed[top] = unclaimed.get(top, 0) + 1
    rows.sort(key=lambda r: r.name.lower())
    pkg_unclaimed = sorted(name for real, name in in_pkg.items() if real not in pkg_claimed)
    return Measurement(rows, len(files), unclaimed, len(in_pkg), pkg_unclaimed)


def cmd_shipped(args: argparse.Namespace) -> int:
    m = measure(pathlib.Path(args.build), pathlib.Path(args.dist), args.site)
    exclude = {norm(x) for x in args.exclude}
    # pkg counts the scripts and modules in the archive appended to the exe.
    print(f"{'distribution':32} {'version':14} {'pyz':>5} {'pkg':>4} {'files':>6} {'record':>7}")
    for r in m.rows:
        mark = "SHIPS" if r.ships else "-"
        if r.ships and norm(r.name) in exclude:
            mark = "SHIPS, excluded"
        print(f"{r.name:32} {r.version:14} {r.pyz:5} {r.pkg:4} {r.files:6} {r.record:7}  {mark}")
    shipping = [r for r in m.rows if r.ships]
    listed = [r for r in shipping if norm(r.name) not in exclude]
    print(f"\n{len(m.rows)} installed distributions checked, {len(shipping)} ship, "
          f"{len(shipping) - len(listed)} of those excluded, {len(listed)} listed")
    print(f"{m.pkg_code} scripts and modules in the executable's archive (PKG-00.toc), "
          f"{m.pkg_code - len(m.pkg_unclaimed)} claimed by a distribution, "
          f"{len(m.pkg_unclaimed)} by none: {', '.join(m.pkg_unclaimed) or 'nothing'}")
    left = sum(m.unclaimed.values())
    print(f"{left} of {m.bundle_files} files in _internal/ claimed by no distribution:")
    for top, n in sorted(m.unclaimed.items()):
        print(f"  {n:5}  {top}")
    if any(norm(r.name) == "setuptools" for r in listed):
        print("\nNOTE setuptools ships in this build. On the Windows runner it did not "
              "(2026-10-31, setuptools 65.5.0): a newer setuptools vendors `backports`, "
              "and httpx2's `from backports.zstd import` pulls the whole package in. "
              "Install setuptools==65.5.0 in the build venv and rebuild before trusting this.")
    if not listed:
        raise Refusal("nothing ships, so there is nothing to list")
    if args.write:
        pathlib.Path(args.write).write_text(
            "".join(f"{r.name}=={r.version}\n" for r in listed), encoding="utf-8")
        print(f"\nwrote {len(listed)} lines to {args.write}")
    return 0


# ------------------------------------------------------------------ fetch

def read_names(path: str) -> list[tuple[str, str]]:
    p = pathlib.Path(path)
    if not p.is_file():
        raise Refusal(f"{path} is not a file. `shipped --write` makes it")
    pairs = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise Refusal(f"{path}: {line!r} is not name==version")
        name, version = line.split("==", 1)
        pairs.append((name.strip(), version.strip()))
    if not pairs:
        raise Refusal(f"{path} names no distribution")
    return pairs


def fetch_command(names: list[tuple[str, str]], dest: str,
                  python: str = sys.executable) -> list[str]:
    return [python, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
            *WINDOWS, "--dest", dest, *(f"{n}=={v}" for n, v in names)]


def cmd_fetch(args: argparse.Namespace) -> int:
    names = read_names(args.names)
    argv = fetch_command(names, args.dest)
    print("running:", " ".join(argv[:12]), f"... {len(names)} requirements")
    code = subprocess.call(argv)
    if code:
        print(f"pip download exited {code}. Nothing below is measured.", file=sys.stderr)
        return REFUSED
    return 0


# ------------------------------------------------------------ the wheels

@dataclass
class Wheel:
    path: pathlib.Path
    name: str          # METADATA Name, which names the licenses/ folder
    version: str
    meta: email.message.Message
    members: list[tuple[str, str]]   # (path in the wheel, path under licenses/<name>/)
    by_hand: str = ""  # the text at the top of licenses/ that SUPPLIED_BY_HAND names
    why: str = ""


def find_wheel(wheels: pathlib.Path, name: str, version: str) -> pathlib.Path:
    want = (norm(name), version)
    for whl in sorted(wheels.glob("*.whl")):
        parts = whl.name.split("-")
        if (norm(parts[0]), parts[1]) == want:
            return whl
    raise Refusal(f"no wheel for {name}=={version} in {wheels}")


def license_members(z: zipfile.ZipFile) -> tuple[str, email.message.Message, list[tuple[str, str]]]:
    """Which members are the distribution's license files, by a fixed rule.

    1. everything under `<dist-info>/licenses/` (PEP 639), path kept
    2. else each `License-File` the METADATA names, from the dist-info root
    3. else LICENSE/LICENCE/COPYING/NOTICE/AUTHORS files at the dist-info root
    4. plus a license or notice file anywhere else in the wheel (a vendored
       component) whose bytes are not already taken, path kept
    """
    names = z.namelist()
    info = next((n.split("/")[0] for n in names if n.endswith(".dist-info/METADATA")), None)
    if info is None:
        raise Refusal(f"{z.filename} has no .dist-info/METADATA")
    meta = email.parser.Parser().parsestr(z.read(f"{info}/METADATA").decode("utf-8"))
    prefix = f"{info}/licenses/"
    taken = [(n, n[len(prefix):]) for n in names
             if n.startswith(prefix) and not n.endswith("/")]
    if not taken:
        declared = meta.get_all("License-File") or []
        taken = [(f"{info}/{d}", d) for d in declared if f"{info}/{d}" in names]
    if not taken:
        taken = [(n, n.split("/", 1)[1]) for n in names
                 if n.count("/") == 1 and n.startswith(info + "/")
                 and LICENSE_NAME.match(n.split("/", 1)[1])]
    seen = {hashlib.sha256(z.read(src)).hexdigest() for src, _ in taken}
    for n in names:
        if n.startswith(info + "/") or n.endswith("/") or n.lower().endswith(NOT_A_TEXT):
            continue
        if LICENSE_NAME.match(n.rsplit("/", 1)[-1]):
            digest = hashlib.sha256(z.read(n)).hexdigest()
            if digest not in seen:
                seen.add(digest)
                taken.append((n, n))
    return info, meta, taken


def open_wheels(names: list[tuple[str, str]], wheels: pathlib.Path,
                licenses: pathlib.Path,
                supplied: dict[str, tuple[str, str]] | None = None) -> list[Wheel]:
    """Each listed distribution's wheel and its license members.

    A wheel with no license file is refused unless `supplied` (by default
    `SUPPLIED_BY_HAND`) names its package, and then it is that package's own
    state: no members, and the text at the top of `licenses/` that covers it.
    An entry is refused when that text is not there, when the wheel holds a
    license file after all, and when the package is not in `names`, the
    shipping set `shipped --write` made.
    """
    if not wheels.is_dir():
        raise Refusal(f"{wheels} is not a directory. `fetch` fills it")
    supplied = SUPPLIED_BY_HAND if supplied is None else supplied
    by_hand = {norm(k): (k, text, why) for k, (text, why) in supplied.items()}
    listed = {norm(name) for name, _ in names}
    gone = sorted(k for key, (k, _, _) in by_hand.items() if key not in listed)
    if gone:
        raise Refusal(f"SUPPLIED_BY_HAND names {', '.join(gone)}, which the shipping "
                      "set does not list, so it no longer ships. Remove the entry from "
                      "tools/notices_audit.py, and its text from licenses/ if nothing "
                      "else needs it")
    out = []
    for name, version in names:
        whl = find_wheel(wheels, name, version)
        with zipfile.ZipFile(whl) as z:
            _, meta, members = license_members(z)
        hand = by_hand.get(norm(name))
        if hand is None:
            if not members:
                raise Refusal(f"{whl.name} holds no license file. Supply its text at "
                              "the top of licenses/, give it a row in the notices, and "
                              "name both in SUPPLIED_BY_HAND in tools/notices_audit.py")
            out.append(Wheel(whl, meta["Name"], version, meta, members))
            continue
        listed_as, text, why = hand
        if members:
            raise Refusal(f"SUPPLIED_BY_HAND names {listed_as}, and {whl.name} ships "
                          f"{len(members)} license files, so the entry is stale. Remove "
                          "it from tools/notices_audit.py and copy the wheel's own files")
        if pathlib.PurePath(text).name != text or not (licenses / text).is_file():
            raise Refusal(f"SUPPLIED_BY_HAND names licenses/{text} for {listed_as}, "
                          f"which is not a file at the top of {licenses}")
        out.append(Wheel(whl, meta["Name"], version, meta, [], text, why))
    return out


def by_hand_lines(wheels: list[Wheel]) -> list[str]:
    return [f"by hand: {w.name}=={w.version}  licenses/{w.by_hand}  ({w.why})"
            for w in wheels if w.by_hand]


def declared_license(meta: email.message.Message) -> tuple[str, str]:
    """The license string as the METADATA declares it, and where it came from."""
    if meta.get("License-Expression"):
        return meta["License-Expression"].strip(), "License-Expression"
    if (meta.get("License") or "").strip():
        return meta["License"].strip().splitlines()[0], "License"
    classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License")]
    if classifiers:
        return "; ".join(classifiers), "classifier"
    return "", "nothing declared"


# ------------------------------------------------------------------- copy

def expected_files(wheels: list[Wheel]) -> dict[str, bytes]:
    expected: dict[str, bytes] = {}
    for w in wheels:
        with zipfile.ZipFile(w.path) as z:
            for src, rel in w.members:
                expected[f"{w.name}/{rel}"] = z.read(src)
    return expected


def compare(expected: dict[str, bytes], licenses: pathlib.Path,
            owned: set[str]) -> list[str]:
    """Differences between licenses/ and the wheels, inside the folders this owns.

    Top-level files (the project-supplied FSF and Apache texts) are never this
    tool's, so they are never reported or touched. A folder no listed
    distribution owns is reported as stale.
    """
    out = []
    on_disk = {p.relative_to(licenses).as_posix(): p for p in licenses.rglob("*")
               if p.is_file() and "/" in p.relative_to(licenses).as_posix()}
    for rel, data in sorted(expected.items()):
        if rel not in on_disk:
            out.append(f"missing: {rel}")
        elif on_disk[rel].read_bytes() != data:
            out.append(f"changed: {rel}")
    for rel in sorted(on_disk):
        top = rel.split("/", 1)[0]
        if top in owned and rel not in expected:
            out.append(f"extra:   {rel}")
    for d in sorted(p.name for p in licenses.iterdir() if p.is_dir()):
        if d not in owned:
            out.append(f"stale:   {d}/  (no listed distribution owns it)")
    return out


def _tally(wheels: list[Wheel]) -> str:
    hand = sum(1 for w in wheels if w.by_hand)
    return (f"{len(wheels)} distributions: {len(wheels) - hand} with license files "
            f"of their own, {hand} supplied by hand")


def cmd_copy(args: argparse.Namespace) -> int:
    names = read_names(args.names)
    licenses = pathlib.Path(args.licenses)
    if not licenses.is_dir():
        raise Refusal(f"{licenses} is not a directory")
    wheels = open_wheels(names, pathlib.Path(args.wheels), licenses)
    expected = expected_files(wheels)
    # A package supplied by hand owns no folder, so one under its name is stale.
    owned = {w.name for w in wheels if not w.by_hand}
    diffs = compare(expected, licenses, owned)
    for line in by_hand_lines(wheels):
        print(line)
    if args.check:
        for line in diffs:
            print(line)
        print(f"{_tally(wheels)}. {len(expected)} files compared, "
              f"{len(diffs)} differences")
        return DRIFT if diffs else 0
    for rel, data in expected.items():
        target = licenses / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for line in diffs:
        rel = line.split(":", 1)[1].strip().split()[0]
        if line.startswith("extra"):
            (licenses / rel).unlink()
            print(f"removed {rel}")
        elif line.startswith("stale"):
            if args.prune:
                shutil.rmtree(licenses / rel.rstrip("/"))
                print(f"removed {rel}")
            else:
                print(f"kept    {rel}  no listed distribution owns it. --prune removes it")
    print(f"{_tally(wheels)}. {len(expected)} files written to {licenses}")
    return 0


# ---------------------------------------------------------------- holders

_LEAD = re.compile(r"^[\s>*#/\-•|]*(\*\*)?")
# "(c)" opens a statement only before a year: Apache's clause 4 is lettered,
# and its "(c) You must retain..." is the clause, not a holder.
_START = re.compile(r"^(copyright\b|\(c\)\s*\d|©|portions copyright)", re.I)
_INLINE = re.compile(r"copyright\s*(\(c\)|©|\d{4})", re.I)
_CLAUSE = re.compile(r"notice|holder|owner|license\b|licen[cs]e,|permission", re.I)
_TEMPLATE = re.compile(r"\[yyyy\]|\[name of copyright owner\]|<year>|\$COPYRIGHT\$", re.I)


def statements(text: str) -> list[str]:
    """Lines that state a copyright, not clause text that mentions one.

    A candidate list for a person to read, not an answer: a notice that wraps
    across lines, or one inside a quoted sentence, needs reading in place.
    """
    out = []
    for line in text.splitlines():
        if _TEMPLATE.search(line):
            continue
        body = _LEAD.sub("", line)
        if (_START.match(body) or _INLINE.search(body)) and not _CLAUSE.search(body):
            out.append(line.strip())
    return out


def required_by(wheels: list[Wheel]) -> dict[str, list[str]]:
    """Which listed distribution requires which, from each wheel's Requires-Dist,
    skipping requirements that only an extra brings in."""
    listed = {norm(w.name): w.name for w in wheels}
    out: dict[str, list[str]] = {w.name: [] for w in wheels}
    for w in wheels:
        for req in w.meta.get_all("Requires-Dist") or []:
            if "extra ==" in req:
                continue
            target = norm(re.split(r"[ ;<>=!~\[(]", req.strip(), maxsplit=1)[0])
            if target in listed and listed[target] != w.name:
                out[listed[target]].append(w.name)
    return out


def _print_statements(label: str, text: str) -> None:
    found = statements(text)
    print(f"- {label}, {len(text.splitlines())} lines, {len(found)} copyright statements")
    for s in found[:12]:
        print(f"  > {s}")
    if len(found) > 12:
        print(f"  ... {len(found) - 12} more, read the file")


def cmd_holders(args: argparse.Namespace) -> int:
    names = read_names(args.names)
    licenses = pathlib.Path(args.licenses)
    wheels = open_wheels(names, pathlib.Path(args.wheels), licenses)
    needs = required_by(wheels)
    for w in sorted(wheels, key=lambda w: w.name.lower()):
        lic, source = declared_license(w.meta)
        print(f"#### {w.name} {w.version}\n")
        print(f"- **License**: `{lic}`    <- {source}")
        if needs[w.name]:
            print(f"- a requirement of {', '.join(sorted(needs[w.name], key=str.lower))}")
        if w.by_hand:
            print(f"- the wheel holds no license file. Supplied by hand: {w.why}")
            _print_statements(f"`licenses/{w.by_hand}`",
                              (licenses / w.by_hand).read_text(encoding="utf-8", errors="replace"))
        with zipfile.ZipFile(w.path) as z:
            for src, rel in w.members:
                _print_statements(f"`{rel}`", z.read(src).decode("utf-8", "replace"))
        print()
    print(f"{_tally(wheels)}, read")
    return 0


# ------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notices_audit.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("shipped", help="list the distributions that reach the bundle")
    s.add_argument("--build", required=True, help="the workpath's spec folder, e.g. build/DSI_Redline")
    s.add_argument("--dist", required=True, help='the one-folder app, e.g. "dist/DSI Redline"')
    s.add_argument("--write", help="write name==version for each listed distribution here")
    s.add_argument("--exclude", nargs="*", default=list(DEFAULT_EXCLUDE),
                   help="DSI's own distributions, kept out of the list (default: pydrc)")
    s.add_argument("--site", nargs="*", help=argparse.SUPPRESS)
    s.set_defaults(run=cmd_shipped)

    f = sub.add_parser("fetch", help="download each listed distribution's Windows wheel")
    f.add_argument("names", help="the file `shipped --write` made")
    f.add_argument("--dest", required=True)
    f.set_defaults(run=cmd_fetch)

    c = sub.add_parser("copy", help="copy each wheel's license files into licenses/<name>/")
    c.add_argument("names")
    c.add_argument("--wheels", required=True)
    c.add_argument("--licenses", default="licenses")
    c.add_argument("--check", action="store_true",
                   help="compare only, exit 1 on any difference")
    c.add_argument("--prune", action="store_true",
                   help="remove licenses/ folders no listed distribution owns")
    c.set_defaults(run=cmd_copy)

    h = sub.add_parser("holders", help="print each wheel's license string and copyright lines")
    h.add_argument("names")
    h.add_argument("--wheels", required=True)
    h.add_argument("--licenses", default="licenses",
                   help="where a text SUPPLIED_BY_HAND names is read from")
    h.set_defaults(run=cmd_holders)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
