---
tags: [tools, pdf, basics]
---

# PDF Tools

The **PDF Tools** tab is a visual workspace (inspired by iLovePDF): a **file
bar** across the top, an **operation rail** on the left, a **thumbnail grid** of
every page in the centre, and a per-operation **options panel** on the right.
The **Tools** menu jumps straight to any operation. Every operation runs in the
background with a progress bar and never overwrites your input — you always
choose an output file or folder.

## Load a PDF

**Drag a PDF onto the workspace** (or click **Open PDF…**) to load it. When you
open a drawing in the [[Viewer]], the tools workspace adopts it automatically,
so the thumbnails are ready the moment you switch tabs.

## Pick pages visually

The four page operations are driven by **clicking page thumbnails** instead of
typing page numbers:

- **Click** a thumbnail to select it; **Shift-click** for a run; **Ctrl-click**
  to add/remove individual pages. **Select all** / **Clear** are one click away.
- The selection stays two-way synced with the **Pages** box, so you can still
  type a spec like `1,3,5-7` and watch the thumbnails light up (orange border).

Operations:

- **Extract pages** — pull the selected pages into a new PDF, either **merged
  into one file** or **one file per page**.
- **Split into ranges** — define page ranges (type *from*/*to* and **Add range**,
  or **From selection**); each range becomes its own PDF, or **merge all ranges**
  into one.
- **Delete pages** — select the pages to remove; the rest are saved to a new PDF.
- **Rotate** — select pages (none selected = all) and turn them with **↺ / ↻**;
  the thumbnails preview the rotation live before you **Apply**.

## Combine & arrange (multiple files)

- **Combine PDFs** — merge several PDFs into one; add files and **drag to
  reorder**, or add a whole folder (sorted by the number in each filename).
- **Insert PDF** — drop one PDF into another before a chosen page.
- **Swap a page** — replace a single page with a one-page PDF.

## Sheet-number split (wizard)

Splits a set into one file per page **named by the drawing's sheet number**
instead of the page number — driven by a guided wizard so it works on any title
block:

1. You're prompted to drag a box around the **sheet number on page 1**.
2. A preview shows the text it read and lets you pick the rule (first number /
   smaller of two / exact text) with a live result.
3. Choose **same box for all pages**, or **add boxes** for other title-block
   styles. For extra boxes, navigate with the **Pages/Bookmarks** panel or
   scroll, draw the box, and say which pages it applies to (this page / to the
   end / through page N).
4. Pick an output folder and split. Pages whose box reads nothing fall back to
   page-number naming and are reported so you can adjust.

The box is read in the drawing's own orientation, so it works on **rotated
pages** too (AutoCAD plots are usually rotated) — the preview shows the number
the same way the split reads it. **Scanned** pages with no text layer are
**OCR'd automatically** whenever Tesseract is installed (no Settings switch
needed); **Claude** is used instead when it's enabled ([[AI Assist]], [[OCR]]).

## Convert & extract

- **PDF → Word** — convert a PDF to an editable `.docx`.
- **Crop / extract (wizard)** — box one or more regions across pages, then turn
  them into editable documents. **Claude reads each region and decides what it
  is**: a **table/BOM** is rebuilt into an **Excel** sheet (one worksheet per
  table), and a **body of prose** (a note, description, instructions) goes into a
  **Word** document for easy editing. A **Markdown** option skips the routing and
  dumps *everything* into one `.md` (tables as markdown tables, text as text).
  You can also keep the raw **PNG** crops. Without an API key it falls back to
  **OCR**, reconstructing tables **best-effort** from text alignment (less
  reliable than Claude) — enable Claude in [[AI Assist]] for the most accurate
  tables.

Related: [[Viewer]] · [[Settings]] · [[Wire Numbers]]

#tools
