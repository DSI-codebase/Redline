---
tags: [storage, files, reference]
---

# Storage and Files

DSI Redline uses a **hybrid** model so your marks are both portable and lossless.

## What gets written

Next to your PDF (`drawing.pdf`):

- **`drawing.marked.pdf`** — a copy with every mark written as a **standard PDF
  annotation**. Open it in Adobe, Chrome, etc. Sticky-note comments carry a real
  popup. Your **original PDF is never modified**.
- **`drawing.markup.db`** — a SQLite **sidecar** holding app-only state: TODO
  status, tags, extra styling, rotation, and the cached wire numbers. This is the
  source of truth for marks this app created.

Save with **File ▸ Save markup** (`Ctrl+S`). Use **Export annotated PDF…**
(`Ctrl+Shift+E`) to write a copy anywhere.

> [!warning] Exporting onto a drawing is refused
> If you point an export — or any **PDF Tools** operation — at the drawing you
> are marking up, or at another drawing that carries marks in DSI Redline, the
> app refuses and says which file it is. Your originals are the one thing it
> will not write over, so choose another name. Exporting onto a previous export,
> or onto a `.marked.pdf`, is fine: those are copies.

> [!warning] Closing with unsaved marks
> Marks live in memory until you save. If you close the window — or open a
> different drawing — with marks you haven't saved, the app asks first and
> offers **Save**, **Discard** or **Cancel**. Discard really does throw away
> every change made since your last save. Which wires and components are
> **ticked** for export counts as unsaved work too, so it's covered by the same
> prompt.
>
> A few things don't wait for a save and so are never at risk: audit findings
> and the waivers you record against them, sheet numbers and roles you set by
> hand, and an imported source drawing. Those are written to the sidecar the
> moment you make them.

> [!tip] Sharing to viewers that don't show annotations
> Most PDF apps (Adobe, Chrome/Edge) render the exported marks fine. If you're
> sharing to a viewer that ignores annotations — some built-in previews, file
> thumbnails — use **File ▸ Export flattened PDF (for sharing)…**. It bakes the
> marks into the page so they show **everywhere**. A flattened copy isn't
> re-editable here, so keep your working file for edits.

> [!tip] Save As — fork to a new working file
> **File ▸ Save As…** (`Ctrl+Shift+S`) copies your current markup into a brand
> new working file (its own `.pdf`, `.marked.pdf` and `.markup.db`) and switches
> you to editing the **copy** — handy for a "what-if" revision or a per-reviewer
> branch. The file you forked *from* is left completely untouched.

> [!note] One database, one marked copy
> There is only ever **one** `drawing.markup.db` and **one** `drawing.marked.pdf`
> per drawing. If you open the `drawing.marked.pdf` itself, the app reuses the
> original sidecar and keeps updating the same marked file — it never makes a
> `drawing.marked.marked.pdf`, and re-saving never doubles your marks. If the
> original `.markup.db` can't be found next to a `.marked.pdf` you open, a new
> one is started and you're told.

> [!warning] When a filename can't back a sidecar (view-only mode)
> The sidecar lives right beside the PDF as `<name>.markup.db`. If the file's
> name is **too long**, or contains characters the filesystem/database won't
> accept, that sidecar can't be created. In that case the PDF still **opens for
> viewing** — you can view, search, navigate, **print** (`Ctrl+P`) and use the
> [[PDF Tools]] — but the **markup tools and saving are grayed out**, and a
> popup explains why. To turn markup back on, **rename the file** to something
> shorter and simpler (avoid very long names and the characters `\ / : * ? " < > |`)
> and open it again.

## Opening a marked-up PDF from someone else

When you open a PDF, DSI Redline imports any annotations already inside it
(highlights, notes, text boxes) **with their original authors and dates**, so
received markups show up correctly in the [[Comments Sidebar]].

## SHX / AutoCAD junk filter

AutoCAD's PDF export often injects "SHX font could not be displayed" notices.
These match the **ignore patterns** in [[Settings]] and are **hidden, never
deleted** — excluded from the sidebar, TODO and counts. Toggle **Show ignored**
to see them.

#storage #reference
