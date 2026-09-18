---
tags: [wire, export]
---

# Wire Export

From the [[Wire Numbers]] tab, click **Export…**. Output is `.xlsx` or `.csv`.

## Two modes

- **Single file (`~sheet~`)** — all labels in one file, with a separator row
  before each sheet's labels using the form `~300~`. Defaults to **labels-only**
  (one column of repeated label strings) — exactly what a wire-label printer
  wants.
- **Per-sheet files** — one file per sheet (`WIRES_300.xlsx`, `WIRES_301.xlsx`,
  …) into a folder you choose. Defaults to the **full column set**:
  `Label | Sheet | Rung | WireIdx | Type | Page | Source`.

Tick **Labels only** to force single-column output in either mode.

## Options

- **Labels/wire** — how many times each label is repeated (default **2**), for
  printing multiple physical tags per wire.
- **Sort**:
  - *Numerical* — by sheet, then rung, then wire index.
  - *In drawing order* — spatial reading order (top-to-bottom by rung,
    left-to-right within a rung).
  - *By sheet* — grouped by sheet.
- **Dedupe** — write each unique label only **once** (on by default). A wire
  number is printed many times across a set (both ends of a wire, every sheet a
  bus crosses), so deduping gives one row per physical wire. Note the on-screen
  table is *already* deduped at extraction (that's what the **Count** column
  reflects), so this checkbox is a final guard — in the normal flow you'll see
  the same rows either way.
- **Show** filters (Conforming / Fixed-OEM / Jumpers) and the **✓** include
  toggles from the table are all honored.

> **Dedupe vs. Labels/wire vs. Count.** These are three different things:
> **Dedupe** removes duplicate labels; **Labels/wire** *repeats* each label N
> times so you can print several physical tags; and **Count** is informational
> only — it shows how many times a label was seen and does **not** control how
> many are exported.

Defaults for mode, format, sort and labels-per-wire come from [[Settings]].

#export #wire
