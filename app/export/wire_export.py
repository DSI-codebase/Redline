"""Wire-number export to .xlsx / .csv (Phase 7).

Two output modes:

* **Per-sheet** - one file per drawing sheet (``WIRES_432.xlsx`` ...), full
  column set by default.
* **Single file** - all labels in one file with ``~sheet~`` separator rows,
  labels-only by default (this is what feeds a physical wire-label printer).

GUI-free so it can be unit-tested.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..extraction.wire_parser import (
    WireNumber,
    TYPE_FIXED,
    TYPE_JUMPER,
    dedupe as dedupe_wires,
    numerical_order,
    reading_order,
)

# Sort modes
SORT_IN_ORDER = "in_order"        # spatial reading order (as drawn)
SORT_NUMERICAL = "numerical"      # by sheet, rung, wire-index
SORT_BY_SHEET = "by_sheet"        # grouped by sheet, numerical within

FULL_COLUMNS = ["Label", "Sheet", "Rung", "WireIdx", "Type", "Page", "Source"]


@dataclass
class WireExportOptions:
    """Everything that controls a wire-number export run."""

    fmt: str = "xlsx"                  # "xlsx" | "csv"
    labels_per_wire: int = 2           # repeat each label N times for printing
    sort: str = SORT_NUMERICAL
    include_fixed: bool = True
    include_jumpers: bool = False
    dedupe: bool = True
    only_included: bool = True         # honour the per-row user include toggle
    sheet_min: Optional[int] = None
    sheet_max: Optional[int] = None
    rung_min: Optional[int] = None
    rung_max: Optional[int] = None
    search: str = ""
    labels_only: Optional[bool] = None  # None -> mode default
    row_band_tol: float = 6.0

    def labels_only_for_mode(self, single_file: bool) -> bool:
        if self.labels_only is not None:
            return self.labels_only
        # default: single-file -> labels only; per-sheet -> full columns
        return single_file


# --- filtering & sorting ----------------------------------------------------


def filter_wires(wires: Iterable[WireNumber], opts: WireExportOptions) -> list:
    out: list = []
    needle = opts.search.lower().strip()
    for w in wires:
        if opts.only_included and not w.included:
            continue
        if not opts.include_fixed and w.wire_type == TYPE_FIXED:
            continue
        if not opts.include_jumpers and w.wire_type == TYPE_JUMPER:
            continue
        if opts.sheet_min is not None and (w.sheet is None or w.sheet < opts.sheet_min):
            continue
        if opts.sheet_max is not None and (w.sheet is None or w.sheet > opts.sheet_max):
            continue
        if opts.rung_min is not None and (w.rung is None or w.rung < opts.rung_min):
            continue
        if opts.rung_max is not None and (w.rung is None or w.rung > opts.rung_max):
            continue
        if needle and needle not in w.label.lower():
            continue
        out.append(w)
    return out


def sort_wires(wires: Iterable[WireNumber], opts: WireExportOptions) -> list:
    items = list(wires)
    if opts.sort == SORT_IN_ORDER:
        return reading_order(items, y_tol=opts.row_band_tol)
    if opts.sort == SORT_BY_SHEET:
        # group by sheet (None last), numerical within each group
        big = float("inf")
        return sorted(
            items,
            key=lambda w: (
                w.sheet if w.sheet is not None else big,
                w.rung if w.rung is not None else big,
                w.wire_index if w.wire_index is not None else big,
                w.label,
            ),
        )
    # default numerical
    return numerical_order(items)


def prepare(wires: Iterable[WireNumber], opts: WireExportOptions) -> list:
    """Filter, optionally de-dupe, then sort."""
    items = filter_wires(wires, opts)
    if opts.dedupe:
        items = dedupe_wires(items)
    return sort_wires(items, opts)


# --- row materialisation ----------------------------------------------------


def _row_full(w: WireNumber) -> list:
    return [
        w.label,
        w.sheet if w.sheet is not None else "",
        w.rung if w.rung is not None else "",
        w.wire_index if w.wire_index is not None else "",
        w.wire_type,
        w.page + 1,  # 1-based page for humans
        w.source,
    ]


def _expand(items: list, labels_per_wire: int):
    """Yield each wire ``labels_per_wire`` times (>=1)."""
    n = max(1, int(labels_per_wire))
    for w in items:
        for _ in range(n):
            yield w


def _group_by_sheet(items: list) -> list:
    """Return ``[(sheet, [wires...]), ...]`` preserving first-seen sheet order."""
    order: list = []
    groups: dict = {}
    for w in items:
        key = w.sheet
        if key not in groups:
            groups[key] = []
            order.append(key)
    for w in items:
        groups[w.sheet].append(w)
    return [(k, groups[k]) for k in order]


def sheet_separator(sheet) -> str:
    """Sheet boundary marker, e.g. ``~300~`` (``~?~`` when sheet unknown)."""
    return f"~{sheet if sheet is not None else '?'}~"


# --- writers ----------------------------------------------------------------


def _write_rows_xlsx(path: str, rows: list, header: Optional[list] = None,
                     sheet_title: str = "Wires") -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31] or "Wires"
    if header:
        ws.append(header)
    for r in rows:
        ws.append(r if isinstance(r, list) else [r])
    wb.save(path)


def _write_rows_csv(path: str, rows: list, header: Optional[list] = None) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if header:
            writer.writerow(header)
        for r in rows:
            writer.writerow(r if isinstance(r, list) else [r])


def _write_rows(path: str, fmt: str, rows: list, header: Optional[list] = None,
                sheet_title: str = "Wires") -> None:
    if fmt == "xlsx":
        _write_rows_xlsx(path, rows, header, sheet_title)
    else:
        _write_rows_csv(path, rows, header)


# --- public API -------------------------------------------------------------


def export_single_file(wires: Iterable[WireNumber], path: str,
                       opts: WireExportOptions) -> str:
    """Mode B - one file, all sheets, ``~sheet~`` separators.

    Returns the path written.
    """
    items = prepare(wires, opts)
    labels_only = opts.labels_only_for_mode(single_file=True)

    rows: list = []
    header = None
    if labels_only:
        for sheet, group in _group_by_sheet(items):
            rows.append([sheet_separator(sheet)])
            for w in _expand(group, opts.labels_per_wire):
                rows.append([w.label])
    else:
        header = list(FULL_COLUMNS)
        for sheet, group in _group_by_sheet(items):
            rows.append([sheet_separator(sheet)])
            for w in _expand(group, opts.labels_per_wire):
                rows.append(_row_full(w))

    _write_rows(path, opts.fmt, rows, header, sheet_title="Wires")
    return path


def export_per_sheet(wires: Iterable[WireNumber], out_dir: str,
                     opts: WireExportOptions) -> list:
    """Mode A - one file per sheet (``WIRES_{sheet}.{ext}``).

    Returns the list of paths written.
    """
    os.makedirs(out_dir, exist_ok=True)
    items = prepare(wires, opts)
    labels_only = opts.labels_only_for_mode(single_file=False)
    ext = "xlsx" if opts.fmt == "xlsx" else "csv"

    written: list = []
    for sheet, group in _group_by_sheet(items):
        name = f"WIRES_{sheet if sheet is not None else 'UNKNOWN'}.{ext}"
        path = os.path.join(out_dir, name)
        if labels_only:
            rows = [[w.label] for w in _expand(group, opts.labels_per_wire)]
            header = None
        else:
            rows = [_row_full(w) for w in _expand(group, opts.labels_per_wire)]
            header = list(FULL_COLUMNS)
        _write_rows(path, opts.fmt, rows, header, sheet_title=f"Sheet {sheet}")
        written.append(path)
    return written
