---
title: DSI Redline — Pre-Beta UI Test Suite
tags: [qa, checklist, beta]
version: "1.0.2"
---

# DSI Redline — Pre-Beta UI Test Suite

A full manual run-through of **every function reachable from the UI**, to confirm the
build is solid before beta. Tick each box as you verify it; jot a note on anything
odd. Headers map to the app's areas and to the [[Home|user manual]] pages.

> [!note] How to use this checklist
> - Work top to bottom — later sections assume a PDF is open.
> - `- [ ]` → not tested · tick when it behaves as described · add `❌ <note>` inline on a failure.
> - Test on the **installed build** (`DSI_Redline_Setup_<ver>.exe`) at least once, and ideally the **portable zip** too.
> - Record results in [[#Sign-off]] at the bottom.

> [!warning] Prepare test material first
> - [ ] A **vector** AutoCAD-Electrical PDF (real text layer, multi-sheet, wire numbers + device tags).
> - [ ] A **scanned / image-only** PDF (no text layer) to exercise OCR / AI paths.
> - [ ] A **multi-page** PDF for the page tools (combine/insert/split/swap).
> - [ ] *(Optional)* **Tesseract** installed → OCR available.
> - [ ] *(Optional)* **Anthropic API key** set in Settings → AI Assist available.
> - [ ] A second machine user / colleague's annotated PDF to test external-annotation import (optional).

---

## 1. Install, launch & identity

- [ ] Installer runs; app installs to `Program Files`; Start-menu shortcut created.
- [ ] *(If ticked at install)* desktop shortcut created.
- [ ] First launch shows the **splash screen** with app name + version, then the main window.
- [ ] **Help ▸ About** shows the correct version (matches the release, e.g. `1.0.2`).
- [ ] **Help ▸ User Manual** opens the manual window and pages render / links work.
- [ ] Window title shows the app name (and the file name once a PDF is open).
- [ ] Taskbar/window icon is the DSI Redline brand icon (not a generic Python icon).
- [ ] Uninstall (Add/Remove Programs) removes the app cleanly.

### File association ("Open with") — [[File Associations]]
- [ ] After install, right-click a `.pdf` ▸ **Open with** lists **DSI Redline**.
- [ ] Choosing it launches the app **with that PDF loaded** in the Viewer and PDF Tools tabs.
- [ ] **Settings ▸ Default apps** lists DSI Redline and lets you set it as the `.pdf` default.
- [ ] Installing did **not** change your previous default PDF app on its own.

---

## 2. Opening & saving documents — [[Getting Started]] · [[Storage and Files]]

- [ ] **File ▸ Open PDF…** (`Ctrl+O`) opens a vector PDF; first page renders.
- [ ] **Drag-and-drop** a PDF onto the window opens it.
- [ ] Open a second PDF — the first closes cleanly, no leftover marks/threads.
- [ ] Make a mark, then **File ▸ Save markup** (`Ctrl+S`) → writes `*.marked.pdf` **and** `*.markup.db`; **original file is untouched**.
- [ ] **File ▸ Export annotated PDF…** writes a flattened/annotated copy to a chosen path.
- [ ] Re-open the `*.marked.pdf` (or original) → marks, TODO state, tags, wire/component cache, and sheet numbers persist.
- [ ] Open a PDF that already contains **external annotations** → they import with their real author and show in the sidebar.
- [ ] **SHX / AutoCAD junk** ("SHX font could not be displayed") is hidden by default; **Show ignored** reveals it.

---

## 3. Viewer — navigation, zoom & pan — [[Viewer]]

- [ ] Continuous vertical scroll through all pages; pages render lazily and sharpen on zoom.
- [ ] Toolbar **Page** box: typing a page number jumps there; the number **updates as you scroll**.
- [ ] **Fit W** / **Fit P** (and **View ▸ Fit width / Fit page**) size the page correctly.
- [ ] Zoom: `Ctrl`+scroll, toolbar `+` / `−`, and `Ctrl` `+` / `Ctrl` `-` all zoom.
- [ ] **Zoom %** box shows current zoom and updates live; typing a % + `Enter` jumps to it; an invalid entry reverts.
- [ ] **Pan** with **Space**+drag and with **middle-mouse** drag.

### Rotate the view (in-memory) — [[Viewer#Rotate the view]]
- [ ] Ribbon **↻** rotates the whole document 90° clockwise **in the viewer**; **↺** counter-clockwise.
- [ ] Existing **markups/comments/highlights rotate with the page and stay correctly placed**.
- [ ] Rotating the opposite way (or a full 4× turn) returns everything **exactly** to normal.
- [ ] Rotation is **not written to disk**: Save/close & re-open → document is back in its original orientation.
- [ ] You can still scroll, zoom and draw correctly **while rotated** (e.g. add a mark, it lands where clicked).

---

## 4. Viewer — text selection & search — [[Viewer]]

- [ ] With **Select** tool, drag across text → text highlights like a browser.
- [ ] `Ctrl+C` copies the selection (paste elsewhere to confirm; line breaks preserved).
- [ ] **Find** (`Ctrl+F`) opens the search bar (top-right).
- [ ] Typing searches live; **i/n** counter shows; current match highlighted orange and scrolled into view.
- [ ] `Enter` / `Shift+Enter` (and ▲/▼) step through matches; wraps around.
- [ ] `Esc` / **✕** closes the search bar.

---

## 5. Markup tools — [[Markup Tools]]

Select each tool from the toolbar and create a mark on the page:

- [ ] **Select** — default; click a mark to select, drag to move.
- [ ] **Highlight** — drag a translucent box; opacity looks right.
- [ ] **Pen** — freehand stroke follows the cursor.
- [ ] **Eraser** — removes strokes/marks it passes over.
- [ ] **Comment** — places a comment marker; the new-comment editor prompts for text + **Flag as TODO**.
- [ ] **Text box** — places editable text; respects font size / bold / italic.
- [ ] **Rectangle** — draws a rectangle outline.
- [ ] **Arrow** — draws a directional arrow (head at the release point).

### Tool options (toolbar)
- [ ] **Color** button changes the active color (swatch updates); new marks use it.
- [ ] **Pen** width spinner changes stroke width.
- [ ] **Font** size spinner + **B** / **I** affect text boxes.

### Editing existing marks
- [ ] Select a mark → drag to **move**; corner handles **resize**; rotate-grip **rotates** it.
- [ ] Resizing a **rotated** mark keeps the opposite corner anchored (no drift).
- [ ] **Delete** removes the selected mark (`Delete` key).
- [ ] **Undo** (`Ctrl+Z`) / **Redo** (`Ctrl+Shift+Z`) reverse/replay create, move, resize, delete.
- [ ] `Esc` cancels an in-progress mark.

### Right-click a mark on the page
- [ ] **Show comment contents** (comment/text marks) shows the text + author/date.
- [ ] **Reveal in TODO list** (TODO marks) switches to the TODO tab and selects the row.
- [ ] **Reveal in Comments** selects the row in the Comments sidebar.
- [ ] **Delete** removes it (with confirm).

---

## 6. Comments sidebar — [[Comments Sidebar]]

- [ ] `F10` (and **View ▸ Toggle comment sidebar**) shows/hides the dock.
- [ ] Every comment / text box / highlight / pen mark appears with type icon, snippet, page, author.
- [ ] **Click a row** scrolls the Viewer to that mark and flashes it.
- [ ] **Search** filters by text; **type** and **commenter** filters work; **TODO only** narrows to flagged items.
- [ ] **Sort** by page / commenter / datetime / type, ascending & descending.
- [ ] Delete a comment three ways — **right-click ▸ Delete**, select + `Delete`, select + **🗑** — each confirms and is undoable.
- [ ] List updates live as you add/edit/delete marks.

---

## 7. TODO tab — [[TODO]]

- [ ] Comments flagged TODO (or all comments if **Treat all as TODO** is on in Settings) appear here.
- [ ] **Done** checkbox toggles an item done/undone (and reflects in the sidebar glyph).
- [ ] **Double-click** the **Text**, **Sheet** or **Tag** cell edits it in place (the view does **not** jump away).
- [ ] **Pg** cell is read-only; **double-clicking Pg** jumps to the mark in the Viewer.
- [ ] **Right-click a row ▸ Go to in PDF** jumps to the mark.
- [ ] **Group:** **Page**, **Sheet**, **Commenter**, and **No grouping** all regroup correctly (headers read "Page N" / "Sheet N").
- [ ] **Sheet** column auto-fills from the title block on a **searchable** PDF (e.g. cover = `000`); editing it updates all rows on that page and persists.
- [ ] On a **scanned** PDF the Sheet column is blank and can be typed in manually.
- [ ] **Tag** column accepts comma-separated tags; sorting by the Tag header works.
- [ ] **Hide done** hides completed items.
- [ ] Clicking a **column header** sorts within each group (↑/↓ indicator).
- [ ] **Drag** rows to reorder.
- [ ] **Export Markdown…** writes a grouped task list (`- [ ] … — p.N, sheet …`).
- [ ] **Export DOCX…** writes a Word table (Done | Text | Page | Sheet | Commenter | Date).

---

## 8. Navigation pane — [[Viewer]]

- [ ] `F9` (and **View ▸ Toggle navigation panel**) shows/hides the dock.
- [ ] **Pages** tab: thumbnails render; **landscape pages sit snug against the page number** (no big gap).
- [ ] Clicking a **thumbnail** jumps the Viewer to that page.
- [ ] Clicking a thumbnail/bookmark **from another tab** (TODO, Wire Numbers, …) **switches back to the Viewer** and shows it.
- [ ] **Bookmarks** tab: the PDF outline shows (or "no bookmarks"); clicking a bookmark jumps to its page.

---

## 9. Wire Numbers tab — [[Wire Numbers]] · [[Wire Export]] · [[Wire Encoding]]

### Extract
- [ ] **Extract wire numbers** on a vector PDF populates the table; status reports totals.
- [ ] **Scanned pages** dropdown offers **AI assist** / **OCR**; default matches Settings.
- [ ] On a scanned PDF with **OCR** selected → OCR reads the pages (requires Tesseract).
- [ ] On a scanned PDF with **AI assist** selected → cost confirmation appears; Claude reads the pages (requires key).
- [ ] **Progress bar** advances page-by-page; **Cancel** stops cleanly.
- [ ] Picking **AI assist** with no key configured shows the "AI not available" notice.
- [ ] A scanned PDF with neither engine usable reports the "scanned images, pick AI/OCR" message.

### Table & spot-check
- [ ] Columns present: ✓ · Label · Sheet · Rung · Idx · Type · Pg · Count · Source · Flags.
- [ ] **Click headers** to sort (numeric columns sort numerically); **drag borders** to resize.
- [ ] Types color-coded: **conforming** / **fixed-OEM** / **jumper**.
- [ ] `Source` shows `text` / `ocr` / `ai` appropriately.
- [ ] With **Cross-check sheet** ON in Settings, off-sheet labels show the **`mismatch`** flag.
- [ ] **✓** include toggles; **Show** filters (Conforming/Fixed-OEM/Jumpers); **search** filters by label.
- [ ] **Check all / Uncheck all** affect only visible rows; **Shift/Ctrl-click** multi-select + one toggle applies to all selected.
- [ ] **Double-click** a row jumps to its page in the Viewer.

### Export
- [ ] **Export…** in **Single file (`~sheet~`)** mode (labels-only) writes one column with `~sheet~` separators.
- [ ] **Per-sheet files** mode writes one file per sheet with the full column set.
- [ ] **Format** xlsx / csv both write; **Sort** Numerical / In-order / By-sheet all work.
- [ ] **Labels/wire** repeats each label N times; **Dedupe** on = one row per unique label.
- [ ] Re-open the file later → cached wire numbers reload (status says "cached …").

---

## 10. Component Labels tab — [[Component Labels]]

- [ ] **Extract component labels** finds device tags (e.g. `LT-10010`); status reports totals.
- [ ] **Scanned pages** AI/OCR dropdown behaves like the Wire tab.
- [ ] Columns: ✓ · Label · Family · Sheet · Rung · Type · Pg · Count · Source · Flags.
- [ ] Types color-coded: **conforming** / **other length**.
- [ ] A tag whose family code isn't in the known list shows the **`unknown family`** flag.
- [ ] **Show** filters (Conforming / Other length / Unknown family), search, check/uncheck, multi-select, double-click jump all work.
- [ ] **Export…** (single / per-sheet, xlsx/csv, labels-only, **labels/device**, dedupe) writes correctly.
- [ ] Editing the **family codes** list in Settings changes which tags are flagged on the next extract.

---

## 11. PDF Tools tab — [[PDF Tools]]

> [!note] These operate on the source PDF and write **new** files (originals untouched).

- [ ] Opening a PDF in the Viewer also loads it into **PDF Tools** (thumbnail grid).
- [ ] **Extract pages (visual)** — select thumbnails (or type a page spec); the two stay in sync; writes the selected pages.
- [ ] **Split into ranges** — define ranges; writes one file per range.
- [ ] **Delete pages (visual)** — selected pages removed; the rest saved to a new PDF.
- [ ] **Rotate pages (visual)** — ↺/↻ preview on thumbnails; **Apply rotation** writes a rotated PDF (this one *is* saved, unlike the Viewer's in-memory rotate).
- [ ] **Combine PDFs…** — merge multiple files in chosen order.
- [ ] **Insert PDF…** — insert another PDF at a chosen position.
- [ ] **Swap a page…** — replace one page with another.
- [ ] **PDF → Word…** — converts to `.docx`.
- [ ] **Split by sheet number… (wizard)** — splits the set by detected sheet numbers.

### Crop / extract wizard — [[PDF Tools]]
- [ ] **Crop / extract… (wizard)** lets you drag a region on a page.
- [ ] With a key: regions classify into **table → Excel**, **prose → Word**, or **everything → Markdown**.
- [ ] Without a key (OCR): tables are reconstructed **best-effort** from text alignment; prose comes through as text.
- [ ] Optionally keeps the raw **PNG** crops.
- [ ] Region pick works correctly even when the **Viewer is rotated** (crop matches what you boxed).

---

## 12. Settings dialog — [[Settings]]

- [ ] **File ▸ Settings…** opens a **tabbed** dialog that fits on screen (no overflow).
- [ ] **General:** Your name (commenter), Export defaults (labels/wire, mode, format), Comments & junk (treat-all-as-TODO, show-ignored, ignore patterns).
- [ ] **Wire numbers:** Sheet/Rung/Wire-index widths, Zero-pad, Full-label regex, Cross-check sheet, **Scanned-page method**.
- [ ] **Component labels:** widths, zero-pad, **Scanned-page method**, labels-per-device, **Family codes** list.
- [ ] **OCR / AI:** Enable OCR, Enable Claude, **API key** (show/hide), **Check API status**, AI model, AI tiling.
- [ ] **Check API status** reports a sensible state (present / missing / no-SDK) for your key.
- [ ] Changing a setting and clicking **OK** persists it; **Cancel** discards.
- [ ] Settings **survive an app restart** (e.g. change your name, restart, confirm).

---

## 13. Panels, layout & menus

- [ ] Tabs present: **Viewer · TODO · Wire Numbers · Component Labels · PDF Tools**.
- [ ] **Navigation** and **Comments** docks can be dragged to any edge, tabbed, split, or floated.
- [ ] **View ▸ Reset panel layout** restores the default arrangement.
- [ ] The window size and panel layout **persist between sessions**.
- [ ] **Tools** menu items all open the matching PDF-tool operation/wizard.
- [ ] Menus: **File / Edit / View / Tools / Help** all present and functional.

---

## 14. Keyboard shortcuts — [[Keyboard Shortcuts]]

- [ ] `Ctrl+O` Open · `Ctrl+S` Save · `Ctrl+F` Find · `Ctrl+C` Copy text.
- [ ] `Ctrl+Z` Undo · `Ctrl+Shift+Z` Redo.
- [ ] `Ctrl`+scroll / `Ctrl` `+` / `Ctrl` `-` Zoom.
- [ ] **Space**+drag and middle-drag Pan.
- [ ] `F9` Navigation · `F10` Comments.
- [ ] `Esc` cancels mark / clears selection / closes search.
- [ ] `Ctrl+Enter` / `Shift+Enter` saves the comment / text-box editor.
- [ ] `Delete` deletes the selected mark / comment.

---

## 15. Robustness & edge cases

- [ ] Open a **large / many-page** set — scrolling stays responsive (lazy render).
- [ ] **Cancel** a long extraction mid-run → app stays responsive, no stale results land.
- [ ] Run with **no Tesseract and no API key** → app works fully on vector PDFs; scanned-page paths degrade gracefully with clear messaging.
- [ ] A page that references **multiple sheets** doesn't spam false `mismatch` flags (cross-check off by default).
- [ ] Close the app with **unsaved marks** — no crash (and behaves per design re: prompting/saving).
- [ ] Open a **corrupt / non-PDF** file → graceful error, no crash.
- [ ] Portable **zip** build: unzip and run `DSI Redline.exe` directly (no install) — core features work (note: no Open-with registration in portable).

---

## Sign-off

| Field | Value |
|-------|-------|
| Tester | |
| Date | |
| Build / version | `v1.0.2` (installer / portable) |
| OS | Windows ___ |
| Tesseract installed? | yes / no |
| API key configured? | yes / no |

- [ ] **All sections passed** — ready for beta.
- [ ] Issues logged (list below):

```
1.
2.
3.
```

#qa #checklist #beta
