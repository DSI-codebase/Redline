---
tags: [components, extraction]
---

# Component Labels

The **Component Labels** tab finds **device/component tags** in a drawing set —
the same way the [[Wire Numbers]] tab finds conductors — and lets you spot-check
before exporting.

## The labeling scheme

A component tag is a **family code** plus a number::

    [FAMILY] [-] [ S S S ][ R R ]
     letters  sep  sheet    rung

e.g. **`LT-10010`** → family `LT` (a light), **sheet 100**, **rung 10**. The
separator may be a hyphen, a space, or nothing (`LT10010`). The sheet/rung field
widths are set in [[Settings]] (default 3 + 2) — separate from the wire-number
widths.

### Family codes

A list of known family codes lives in **[[Settings]] ▸ Component labels**
(seeded with codes found in the sample sets plus common electrical/ISA families
like `LT`, `CR`, `PB`, `FU`, `LS`, `PS`). Drafters sometimes invent their own
codes, so a tag whose family **isn't** in the list is still captured — it's just
flagged **unknown family** so you can review it. Edit the list any time.

## Extract

Click **Extract component labels**. Vector pages are read from the text layer;
for **scanned pages with no text**, pick the engine next to the button —
**AI assist** (Claude vision, see [[AI Assist]]) or **OCR** (Tesseract, see
[[OCR]]). A progress bar with **Cancel** runs the work in the background; for AI
on scanned pages you're warned about the number of API calls first.

## The table

Columns: include ✓ · Label · Family · Sheet · Rung · Type · Pg · Count · Source
· Flags. **Click a header to sort** (numbers sort numerically); **drag borders to
resize**. Types are color-coded:

- **conforming** — the number is exactly sheet+rung wide and splits cleanly.
- **other length** — a family+number tag of a different length (kept, not split).

The **Flags** column is a review *warning* (blank = no issue). It shows
**`unknown family`** for tags whose family code isn't in your known-codes list —
the tag is still captured, the flag just asks you to confirm it's a real device
and, if so, add the code in [[Settings]]. (The [[Wire Numbers]] tab has a
parallel Flags column whose value is `mismatch`.)

## Spot-check, then export

The controls match the [[Wire Numbers]] tab: the **✓** column picks what's
exported; **Show** checkboxes and the search box filter rows; **Check all /
Uncheck all** toggle every visible row; **Shift/Ctrl-click** selects groups;
**double-click** jumps to the page in the [[Viewer]].

Export to **.xlsx / .csv**, single-file (with `~sheet~` separators) or one file
per sheet, labels-only or full columns, with a configurable **labels-per-device**
repeat — mirroring [[Wire Export]]. **Dedupe** (on by default) writes each unique
tag once; **labels-per-device** then repeats it for printing, and the **Count**
column is informational only (see the Dedupe note in [[Wire Export]]).

Related: [[Wire Numbers]] · [[Settings]] · [[AI Assist]]

#components
