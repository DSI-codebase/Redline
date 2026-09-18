"""Component-label export to .xlsx / .csv.

Mirrors :mod:`app.export.wire_export` (single-file with ``~sheet~`` separators,
or one file per sheet; labels-only or full columns; labels-per-device repeats),
but for :class:`ComponentLabel` rows.  GUI-free / unit-testable.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from ..extraction.component_parser import (
    ComponentLabel, TYPE_NONCONFORMING,
    dedupe as dedupe_components, numerical_order, reading_order,
)

# Sort modes (shared vocabulary with wire export)
SORT_IN_ORDER = "in_order"
SORT_NUMERICAL = "numerical"
SORT_BY_SHEET = "by_sheet"

FULL_COLUMNS = ["Label", "Family", "Sheet", "Rung", "Type", "Page", "Source"]


@dataclass
class ComponentExportOptions:
    fmt: str = "xlsx"                   # "xlsx" | "csv"
    labels_per_device: int = 1
    sort: str = SORT_NUMERICAL
    include_nonconforming: bool = True
    include_unknown_family: bool = True
    dedupe: bool = True
    only_included: bool = True
    search: str = ""
    labels_only: Optional[bool] = None
    row_band_tol: float = 6.0

    def labels_only_for_mode(self, single_file: bool) -> bool:
        if self.labels_only is not None:
            return self.labels_only
        return single_file


def filter_components(items: Iterable[ComponentLabel],
                      opts: ComponentExportOptions) -> list:
    out: list = []
    needle = opts.search.lower().strip()
    for c in items:
        if opts.only_included and not c.included:
            continue
        if not opts.include_nonconforming and c.comp_type == TYPE_NONCONFORMING:
            continue
        if not opts.include_unknown_family and c.unknown_family:
            continue
        if needle and needle not in c.label.lower():
            continue
        out.append(c)
    return out


def sort_components(items: Iterable[ComponentLabel],
                    opts: ComponentExportOptions) -> list:
    items = list(items)
    if opts.sort == SORT_IN_ORDER:
        return reading_order(items, y_tol=opts.row_band_tol)
    # numerical and by_sheet share the same key here (sheet, rung, family, number)
    return numerical_order(items)


def prepare(items: Iterable[ComponentLabel], opts: ComponentExportOptions) -> list:
    rows = filter_components(items, opts)
    if opts.dedupe:
        rows = dedupe_components(rows)
    return sort_components(rows, opts)


def _row_full(c: ComponentLabel) -> list:
    return [
        c.label,
        c.family,
        c.sheet if c.sheet is not None else "",
        c.rung if c.rung is not None else "",
        c.comp_type,
        c.page + 1,
        c.source,
    ]


def _expand(items: list, labels_per_device: int):
    n = max(1, int(labels_per_device))
    for c in items:
        for _ in range(n):
            yield c


def _group_by_sheet(items: list) -> list:
    order: list = []
    groups: dict = {}
    for c in items:
        if c.sheet not in groups:
            groups[c.sheet] = []
            order.append(c.sheet)
    for c in items:
        groups[c.sheet].append(c)
    return [(k, groups[k]) for k in order]


def sheet_separator(sheet) -> str:
    return f"~{sheet if sheet is not None else '?'}~"


def _write_rows_xlsx(path, rows, header=None, sheet_title="Components"):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title[:31] or "Components")
    if header:
        ws.append(header)
    for r in rows:
        ws.append(r if isinstance(r, list) else [r])
    wb.save(path)


def _write_rows_csv(path, rows, header=None):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if header:
            writer.writerow(header)
        for r in rows:
            writer.writerow(r if isinstance(r, list) else [r])


def _write_rows(path, fmt, rows, header=None, sheet_title="Components"):
    if fmt == "xlsx":
        _write_rows_xlsx(path, rows, header, sheet_title)
    else:
        _write_rows_csv(path, rows, header)


def export_single_file(items: Iterable[ComponentLabel], path: str,
                       opts: ComponentExportOptions) -> str:
    prepared = prepare(items, opts)
    labels_only = opts.labels_only_for_mode(single_file=True)
    rows: list = []
    header = None
    if labels_only:
        for sheet, group in _group_by_sheet(prepared):
            rows.append([sheet_separator(sheet)])
            for c in _expand(group, opts.labels_per_device):
                rows.append([c.label])
    else:
        header = list(FULL_COLUMNS)
        for sheet, group in _group_by_sheet(prepared):
            rows.append([sheet_separator(sheet)])
            for c in _expand(group, opts.labels_per_device):
                rows.append(_row_full(c))
    _write_rows(path, opts.fmt, rows, header, sheet_title="Components")
    return path


def export_per_sheet(items: Iterable[ComponentLabel], out_dir: str,
                     opts: ComponentExportOptions) -> list:
    os.makedirs(out_dir, exist_ok=True)
    prepared = prepare(items, opts)
    labels_only = opts.labels_only_for_mode(single_file=False)
    ext = "xlsx" if opts.fmt == "xlsx" else "csv"
    written: list = []
    for sheet, group in _group_by_sheet(prepared):
        name = f"COMPONENTS_{sheet if sheet is not None else 'UNKNOWN'}.{ext}"
        path = os.path.join(out_dir, name)
        if labels_only:
            rows = [[c.label] for c in _expand(group, opts.labels_per_device)]
            header = None
        else:
            rows = [_row_full(c) for c in _expand(group, opts.labels_per_device)]
            header = list(FULL_COLUMNS)
        _write_rows(path, opts.fmt, rows, header, sheet_title=f"Sheet {sheet}")
        written.append(path)
    return written
