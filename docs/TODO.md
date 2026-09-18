---
tags: [todo, panel, export]
---

# TODO

The **TODO** tab is your punch list. Any comment or text box flagged as a TODO
appears here.

## Flagging

- Tick **Flag as TODO** in the comment/text-box editor, **or**
- turn on **Treat all comments as TODO** in [[Settings]] so every new comment
  starts as a TODO.

## Working the list

- **Checkbox** — mark an item done/undone.
- **Double-click a cell to edit it** — the **Text**, **Sheet** and **Tag**
  columns are editable. Double-clicking no longer jumps to the PDF, so you can
  edit without the view moving away.
- **Double-click the Commenter** to change who the mark is by (confirm, then
  edit; optionally rename everyone by that name). Undoable.
- **Jump to the mark** in the [[Viewer]] (scrolls there and flashes) by either
  **right-clicking the row → "Go to in PDF"**, or **double-clicking the Pg
  cell** (the page number is read-only and kept as the quick-jump shortcut).
- **Group** by **Page**, **Sheet**, or **Commenter**, or turn grouping off.
- **Hide done** to focus on what's left.
- **Click a column header** to sort items *within* each group; an ↑/↓ arrow
  shows the direction. Grouping always stays the primary order.
- The **Filter** box matches across **all** columns — text, page, sheet,
  commenter and tags — so typing a tag shows only items with that tag.

> **Jumping the other way:** right-click a mark on the PDF and choose
> **Reveal in TODO list** (for TODO marks) or **Reveal in Comments** to select
> it in the matching panel.

The **Done** column widens automatically to show the full group name; you can
still resize it, but it won't shrink below the widest group name.

### Tag column

The **Tag** column is a free-form, comma-separated set of labels you attach to a
TODO for your own triage — there's no fixed vocabulary. Type values like
`electrical, RFI, priority` into the cell. Tags are saved in the markup sidecar
(see [[Storage and Files]]), you can **sort** by them via the header, and they
appear on export as `#tag1,tag2`. The **Filter** box matches tags too (along
with every other column).

### Sheet column

The **Sheet** column is the drawing's sheet number from its **title block** —
a *per-page* value, so every TODO on the same page shows the same sheet.

- On **searchable** PDFs it's **auto-detected** from the title block (e.g. the
  cover page reads `000`).
- It's **editable**: correct a mis-read sheet, or type one in by hand on
  **scanned** PDFs where it can't be detected. Editing it updates that page's
  sheet for every TODO on the page, and the value is saved in the sidecar.
- Choose **Group: Sheet** to bucket the list by these numbers (`(no sheet)`
  collects pages with no sheet set).

## Export

- **Export Markdown…** — a GitHub task list grouped by your current grouping
  (Page / Sheet / Commenter): `- [ ] text — p.5, sheet 300, Author, date`, with
  done items as `- [x]`.
- **Export DOCX…** — a Word table: Done | Text | Page | Sheet | Commenter |
  Date, with ☐/☑ glyphs and a generated-on line.

See [[Wire Export]] for the separate wire-number exports.

#todo
