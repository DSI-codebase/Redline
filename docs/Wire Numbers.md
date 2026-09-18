---
tags: [wire, extraction]
---

# Wire Numbers

The **Wire Numbers** tab finds the wire labels in your drawing set, classifies
them, and lets you spot-check before exporting. For the numbering scheme see
[[Wire Encoding]].

## Extract

Click **Extract wire numbers**. DSI Redline reads the text layer of every page;
for **scanned pages with no text** it uses the engine chosen in the
**Scanned pages** dropdown next to the button — **AI assist** (Claude vision,
see [[AI Assist]]) or **OCR** (Tesseract, see [[OCR]]). It then parses,
classifies and de-duplicates the candidates. The dropdown defaults to whatever
you set in [[Settings]] and can be changed per extraction.

A **progress bar** shows it scanning page-by-page, with a **Cancel** button —
important for scanned sets, where reading can take a while. The work runs in the
background so the app never freezes.

The status line reports totals, e.g.
*"247 unique labels — 247 conforming, 0 fixed/OEM, 0 jumpers."* If you pick
**AI assist** but no API key is configured, it says so — add a key in
[[Settings]] or switch the dropdown to **OCR**.

> **Non-standard sets:** AI reads labels even when they don't match the
> configured width (e.g. 5-digit codes). Those come through as **fixed/OEM** so
> you still capture them; adjust the field widths in [[Settings]] to make them
> *conforming*.

## The table

Columns: include ✓ · Label · Sheet · Rung · Idx · Type · Pg · Count · Source ·
Flags. **Click a header to sort**; **drag column borders to resize** them.

Types are color-coded:
- **conforming** — parses cleanly to the field layout.
- **fixed/OEM** — a wire-ish token that doesn't follow the rule; still captured.
- **jumper** — on a "jumper" layer (excluded by default; only when the PDF
  exposes layers).

`Source` is `text`, `ocr` or `ai` depending on how the label was read.

### The Flags column

**Flags** surfaces a data-quality *warning* about a label; a blank cell means no
issue. The wire flag is **`mismatch`**: the sheet encoded in the label's leading
digits doesn't match the sheet DSI Redline resolved for that page from its title
block (e.g. a `300xxx` label found on a page resolved as sheet 432).

- It's **opt-in** — flags only appear when you enable **Cross-check sheet** in
  [[Settings]]. It's off by default because drawings legitimately reference
  wires from *other* sheets on one page (cross-references, bus continuations),
  which would otherwise raise false mismatches.
- Treat a flag as "eyeball this one": it's either a legitimate off-sheet
  reference or a mis-read/mislabeled wire worth verifying.
- Only **conforming** labels are cross-checked; jumpers and fixed/OEM are never
  flagged this way.

(The [[Component Labels]] tab has a parallel Flags column whose value is
`unknown family`.)

## Spot-check before export

- The **✓** column controls whether a row is exported. Untick anything you
  don't want (e.g. legend examples on a notes page).
- **Show** checkboxes filter the visible rows by type; the search box filters by
  label.
- **Check all / Uncheck all** toggle every *visible* row at once.
- Select multiple rows with **Shift/Ctrl-click**, then toggle one checkbox to
  apply the same state to the whole selection.
- **Double-click** a row to jump to that label's **location on the drawing** in
  the [[Viewer]] (the first occurrence for labels that appear more than once),
  with a brief pulse marker.

When you're happy, see [[Wire Export]].

#wire
