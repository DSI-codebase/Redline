"""Importing a project's source drawings.

The user points at the AutoCAD Electrical project directory.  From there:

1. Every drawing gets a DXF.  One that already sits beside its DWG (and is not
   older than it) is used as-is; otherwise the ODA File Converter turns the DWG
   into one, in a cache folder so the project directory is never littered.
2. PyDRC's ACADE adapter reads the DXFs into a model document.
3. The model is stored in the sidecar, and every subsequent audit merges it
   into the plot-derived model before the rules run.

The converter is detected, never bundled: ODA's freeware license does not allow
redistribution, so the pattern is the one OCR already uses for Tesseract — the
user installs it, this module finds it (or Settings points at it), and without
it the import still works on directories that already contain DXFs.

Qt-free, and safe to run on a worker thread: nothing here touches the sidecar
or the open document.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

# Converter CLI: input dir, output dir, output version, output type,
# recurse (0/1), audit (0/1), optional filter.
_ODA_ARGS = ("ACAD2018", "DXF", "0", "1", "*.DWG")

# Where an installer normally puts it.  A Settings override always wins.
_ODA_GLOBS = (
    r"C:\Program Files\ODA\*\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe",
    "/usr/bin/ODAFileConverter",
    "/opt/ODAFileConverter/ODAFileConverter",
)

CACHE_DIR_NAME = ".dsi_dxf"


def find_converter(configured: str = "") -> str:
    """The ODA File Converter's path, or empty when none is available."""
    if configured and os.path.isfile(configured):
        return configured
    for pattern in _ODA_GLOBS:
        hits = sorted(glob.glob(pattern), reverse=True)   # newest version first
        if hits:
            return hits[0]
    return ""


@dataclass
class ImportPlan:
    """What a directory holds and what has to happen to read it."""

    directory: str = ""
    usable_dxfs: list = field(default_factory=list)
    needs_conversion: list = field(default_factory=list)   # DWGs without a DXF

    @property
    def empty(self) -> bool:
        return not (self.usable_dxfs or self.needs_conversion)


def plan_import(directory: str) -> ImportPlan:
    """Inventory a project directory.

    A DXF is usable when no sibling DWG is newer than it; a stale DXF is
    treated as absent, because auditing last month's conversion of this month's
    drawing produces confident findings about the wrong revision.
    """
    plan = ImportPlan(directory=directory)
    entries = os.listdir(directory)
    by_stem: dict = {}
    for name in entries:
        stem, ext = os.path.splitext(name)
        by_stem.setdefault(stem.lower(), {})[ext.lower()] = name

    cache = os.path.join(directory, CACHE_DIR_NAME)
    for stem, exts in sorted(by_stem.items()):
        dwg = exts.get(".dwg")
        dxf = exts.get(".dxf")
        cached = os.path.join(cache, stem + ".dxf")
        dwg_path = os.path.join(directory, dwg) if dwg else None
        candidates = []
        if dxf:
            candidates.append(os.path.join(directory, dxf))
        if os.path.isfile(cached):
            candidates.append(cached)
        fresh = None
        for c in candidates:
            if dwg_path and os.path.getmtime(c) < os.path.getmtime(dwg_path):
                continue
            fresh = c
            break
        if fresh:
            plan.usable_dxfs.append(fresh)
        elif dwg_path:
            plan.needs_conversion.append(dwg_path)
    return plan


def convert(plan: ImportPlan, converter: str,
            progress: Optional[Callable] = None,
            cancel: Optional[Callable] = None,
            runner: Optional[Callable] = None) -> tuple:
    """Convert the DWGs the plan flagged.  Returns ``(converted, errors)``.

    ``runner`` exists for tests; it defaults to ``subprocess.run``.  The
    converter is invoked once on the whole directory — that is its native mode —
    with output into the cache folder.
    """
    if not plan.needs_conversion:
        return [], []
    run = runner or (lambda args: subprocess.run(
        args, capture_output=True, timeout=600))
    cache = os.path.join(plan.directory, CACHE_DIR_NAME)
    os.makedirs(cache, exist_ok=True)

    if progress is not None:
        progress(0, 1)
    try:
        run([converter, plan.directory, cache, *_ODA_ARGS])
    except Exception as e:
        return [], [f"Converter failed: {e}"]
    if cancel is not None and cancel():
        return [], []
    if progress is not None:
        progress(1, 1)

    converted, errors = [], []
    for dwg in plan.needs_conversion:
        stem = os.path.splitext(os.path.basename(dwg))[0]
        out = os.path.join(cache, stem + ".dxf")
        if os.path.isfile(out):
            converted.append(out)
        else:
            errors.append(f"{os.path.basename(dwg)}: no DXF was produced")
    return converted, errors


@dataclass
class ImportResult:
    model_json: str = ""
    wire_format: str = ""
    sheets_read: int = 0
    converted: int = 0
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        if not self.sheets_read:
            return "No drawings could be read."
        bits = [f"Read {self.sheets_read} drawing(s)"]
        if self.converted:
            bits.append(f"converted {self.converted} from DWG")
        if self.errors:
            bits.append(f"{len(self.errors)} problem(s)")
        return ", ".join(bits) + "."


def import_project(directory: str, converter_path: str = "",
                   project_number: str = "",
                   progress: Optional[Callable] = None,
                   cancel: Optional[Callable] = None,
                   runner: Optional[Callable] = None) -> ImportResult:
    """The whole pipeline: inventory, convert what needs it, read, serialize."""
    from pydrc.adapters import acade_dxf
    from pydrc.model import dumps

    result = ImportResult()
    plan = plan_import(directory)
    if plan.empty:
        result.errors.append("No DWG or DXF drawings in this directory.")
        return result

    dxfs = list(plan.usable_dxfs)
    if plan.needs_conversion:
        converter = find_converter(converter_path)
        if converter:
            converted, errors = convert(plan, converter, progress=progress,
                                        cancel=cancel, runner=runner)
            dxfs.extend(converted)
            result.converted = len(converted)
            result.errors.extend(errors)
        else:
            result.errors.append(
                f"{len(plan.needs_conversion)} DWG(s) need conversion, but the "
                "ODA File Converter is not installed. Install it (free, from "
                "opendesign.com) or export DXFs beside the DWGs.")
    if cancel is not None and cancel():
        return result
    if not dxfs:
        return result

    sheets = []
    total = len(dxfs)
    for i, path in enumerate(sorted(dxfs)):
        if cancel is not None and cancel():
            return result
        try:
            sheets.append(acade_dxf.read_sheet(path))
        except acade_dxf.DxfUnavailable:
            result.errors.append(
                "Reading drawings requires the ezdxf package.")
            return result
        except Exception as e:
            result.errors.append(f"{os.path.basename(path)}: {e}")
        if progress is not None:
            progress(i + 1, total)

    if not sheets:
        return result
    model = acade_dxf.build_model(sheets, project_number)
    result.model_json = dumps(model)
    result.sheets_read = len(sheets)
    formats = {s.wire_format for s in sheets if s.wire_format}
    result.wire_format = formats.pop() if len(formats) == 1 else ""
    return result
