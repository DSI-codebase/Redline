"""Check that the frozen build carries every data file a package installed.

    python tools/bundle_check.py --dist "dist/DSI Redline" pydrc

A source install has a package's data files beside its modules, and the
PyInstaller bundle has only the ones the spec's `collect_data_files` filter
matched. v1.8.1's spec collected PyDRC's YAML and none of its JSON, so the
bundle carried the rule packs and not the 28 calculator tables or the part
ratings file, and every calculator stopped with "no NEC 2026 table ...". The
suite runs from source and `--self-test` builds the window without reading a
table, so neither could see it.

This reads the oracle the bundle is meant to reproduce: the package as the
interpreter that built the bundle has it installed. Every file under the
package's directory that is not a module (`.py`, `.pyc`, `__pycache__/`) must
exist at the same relative path under `<dist>/_internal/<package>/`. Run it
under that interpreter, after PyInstaller.

Exit 0 when every data file is in the bundle, 1 listing each one that is not,
2 when it refuses: no `_internal/` in `--dist`, a package that is not
installed, or one with no data files at all. A package with nothing to compare
reads the same as one that is complete, so that answer is never given.

Stdlib only, like tools/run_tests.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys

REFUSED = 2
MISSING = 1

NOT_DATA = (".py", ".pyc")


class Refusal(Exception):
    pass


def package_dir(name: str) -> pathlib.Path:
    """Where ``name`` is installed, found without importing it."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        raise Refusal(f"{name} is not installed as a package under {sys.executable}, "
                      "so there is nothing to compare the bundle with. Run this under "
                      "the interpreter that built the bundle.")
    return pathlib.Path(list(spec.submodule_search_locations)[0])


def data_files(root: pathlib.Path) -> list[str]:
    """Every file under ``root`` that is not a module, relative and in POSIX form."""
    out = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if not p.is_file() or "__pycache__" in rel.parts or p.suffix in NOT_DATA:
            continue
        out.append(rel.as_posix())
    return sorted(out)


def compare(name: str, dist: pathlib.Path) -> tuple[list[str], list[str]]:
    """``(installed, missing)``: the package's data files, and those the bundle lacks."""
    internal = dist / "_internal"
    if not internal.is_dir():
        raise Refusal(f"no _internal/ in {dist}. --dist is the one-folder app, "
                      "the folder that holds DSI Redline.exe.")
    installed = data_files(package_dir(name))
    if not installed:
        raise Refusal(f"{name} has no data files installed, so a bundle without "
                      "any would pass. Nothing was compared.")
    bundled = internal / name
    missing = [rel for rel in installed if not (bundled / rel).is_file()]
    return installed, missing


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bundle_check.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--dist", required=True, type=pathlib.Path,
                   help="the one-folder app PyInstaller wrote, e.g. \"dist/DSI Redline\"")
    p.add_argument("packages", nargs="+", help="the installed packages to compare, e.g. pydrc")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code = 0
    for name in args.packages:
        try:
            installed, missing = compare(name, args.dist)
        except Refusal as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return REFUSED
        print(f"{name}: {len(installed)} data files installed, "
              f"{len(installed) - len(missing)} in the bundle, {len(missing)} missing")
        for rel in missing:
            print(f"  missing from _internal/{name}/: {rel}")
        if missing:
            code = MISSING
    return code


if __name__ == "__main__":
    sys.exit(main())
