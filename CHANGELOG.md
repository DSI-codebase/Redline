# Changelog

All notable changes to **DSI Redline** are documented here. Versions are tagged
`vX.Y.Z`; each tag triggers the Windows build that publishes the installer and a
portable zip to the matching GitHub release.

## v1.5.2

- **Your original drawing can no longer be overwritten — and until now it
  could.** "The original file is never overwritten" is the first thing this
  project says about itself, and it was a sentence rather than a rule: every
  write took its destination on trust. Pointing **Export annotated PDF…** at the
  drawing you were marking up **replaced it**, wrote no `.marked.pdf` at all,
  and left every later save writing *two* copies of every mark for ever — with
  nothing on screen saying anything had happened, because the app draws the
  clean page. Pointing an export at a *neighbouring* drawing replaced that one
  instead: a three-page sheet became a one-page copy of the file you had open.
  The flattened export was worse again, baking the marks into the page content
  where nothing can strip them back off.

  It reached the **PDF Tools** as well, in spite of that page promising the
  opposite: **Extract** aimed at its own source took a four-page drawing to one
  page, **Split** took five to two, **Combine** replaced an input with the
  combination, and **Rotate** aimed at an unrelated drawing replaced it with a
  rotated copy of something else.

  Every one of those is now refused, by name, before a byte is written — *"…is
  the original drawing this markup belongs to, and DSI Redline never writes over
  an original"* — and the refusals cover the drawing you have open, any other
  drawing that carries marks here, and any file a tool is reading from.
  Exporting onto a previous export, onto a `.marked.pdf`, or onto any new name
  is unchanged, and so is re-saving a `.marked.pdf` you opened directly.

  **What is deliberately not refused:** a PDF this app has never opened. It is
  indistinguishable from a stale export, and the save dialog has already asked
  about replacing it.

## v1.5.1

- **Windows prints are actually sharp now.** The v1.3.1 print fix rendered
  each page "1:1 with the printer's viewport" — but on Windows, Qt pins that
  viewport to the **screen's** 96 dpi no matter what resolution the app asks
  for, so prints were still a 96 dpi image stretched onto the sheet (confirmed
  from a Microsoft Print to PDF export). Pages are now rasterized at the
  printer's **real device resolution** (at least 600 dpi, at most 1200) and the
  full-detail bitmap is handed to the driver, independent of the viewport's
  density. Linux/macOS output is unchanged.

- **Minimum line weight for printing.** Printing at the real resolution has a
  side effect worth naming: it stops fattening your hairlines. AutoCAD plots
  schematic geometry at 0.1–0.15 pt, and no renderer can draw thinner than one
  device pixel — so at the 96 dpi the old path was really using, every hairline
  came out 1 px = **0.75 pt**, and that heaviness is what everyone got used to.
  At 600 dpi the same line is drawn at its true **0.12 pt**: correct, and far
  too thin on paper. So the app now applies a minimum pen width the way CAD
  plotting always has. **Settings ▸ General ▸ Printing** offers *As drawn*,
  *Light* (0.25 pt), *Medium* (0.5 pt, the default) and *Heavy* (0.75 pt, which
  reproduces the weight of the older prints at the new sharpness), and the same
  picker sits in **Print preview** so you can judge it before committing. It is
  a floor, not a multiplier: heavier geometry is left alone, and text is never
  touched.

## v1.5.0

Design rule checking, taken through two drawing sets it had never seen. Most
of this release is the audit growing up: findings that land where they belong,
say what they mean once instead of fifty times, and never claim to have checked
something they did not.

- **Your work is no longer lost when you close.** `Document.mark_dirty()`
  existed with no caller, so the document was *structurally* never dirty —
  nothing ever set the flag, the close path never read it, and there is no
  autosave. Measured: fifty marks across fourteen sheets, close, reopen, **zero
  survived**, with no prompt and no warning. Closing the window or opening
  another drawing now asks **Save / Discard / Cancel**, and Cancel leaves a
  working window rather than a half-torn-down one. Which wires and components
  are ticked for export counts as unsaved work too.

- **A sheet is read from its drawing number, not its revision.** On a set whose
  drawing numbers use an underscore (`EL2503311_011`) rather than a hyphen, the
  confident strategy matched nothing, the keyword strategy only knew
  value-to-the-right layouts, and everything fell through to a corner heuristic
  that takes the *smallest* number in the title block — which is the revision.
  Every resolvable sheet came back numbered **"0"**, with thirty-three findings
  about a set whose only defect was being at revision zero. All twenty-eight
  sheets now resolve to their true numbers at full confidence, and a number
  belonging to a `REV` cell is never a candidate.

- **Findings open on the page they are actually on.** A source drawing numbers
  its sheets by position in the DXF package; the PDF numbers them by page. Both
  landed on one field, so a finding followed the wrong ordinal — invisible on a
  set where the two happen to agree, and **32 of 60 findings on the wrong page**
  on one where they do not.

- **A box on every symbol a finding names.** A place is a sheet and a rung, so
  symbols with no rung shared one — sixteen field instruments across two sheets
  drew **two** boxes. Now one per symbol, and the same fix recovered boxes the
  demo set had been losing all along (three fuses on a terminal strip beside
  the one that did get a box).

- **A refused import is not a clean drawing.** A damaged stored import
  abandoned the whole audit and reported **"Nothing to check."** — 29 findings
  and 1048 eligible checks thrown away because a separate blob was corrupt,
  with the reason recorded in a field nothing displayed. The check now runs on
  the PDF alone and says so, at the top of the panel and of every export.

- **Rules say things once.** Instrument tags following FAMILY-LOOP numbering
  (48 rows → 14, one per family), protective devices with no part assigned (50
  → 2, split so that *"32 fuses carry neither a catalog assignment nor a
  rating"* is not buried among breakers that at least have ratings), and signal
  arrows with no cross-reference (61 rows → 1 — and that one reports **121**
  arrows, because two arrows on a rung used to collapse and sixty were never
  reported at all).

- **Two rules stopped reporting correct drawings as defects.** Plain text on a
  PLC I/O sheet is how an I/O sheet is drawn, not a missing symbol (70
  findings, none of them on a schematic sheet). A terminal landing on a supply
  bus with no wire number does not contradict a connection claim — an absence
  of a number is not a contradicting number (5 of 9 checked symbols).

- **Reports say which rules produced them.** Every export now carries
  `Rule packs: drc-base@1.34.0` — a footer in HTML, a line in Markdown, a row
  in CSV. The rule pack's version moves with every rule change, so two reports
  that disagree about a finding can be told apart.

- **Turning a rule off hides its boxes and its report lines too**, a withdrawn
  severity override puts the severity back, and the "PyDRC is not installed"
  dialog names the interpreter it searched and the exact command to install
  into it.

## v1.4.0

- **A real Find (`Ctrl+F`).** The search bar grew into a search panel — still
  pinned top-right, still closed from its **✕** — that no longer vanishes when
  you click the drawing, press `Esc` on the canvas, or open another file (it
  re-runs your query in the new document instead). Under the box: **match case**,
  **whole words** and **regex** toggles, plus **Marks**, which searches your
  comments, text boxes, callouts and notes alongside the page text. Every hit is
  listed in a scrollable **match list** grouped by page/sheet and shown with the
  surrounding line — click one to jump to it with a pulse. Matched tokens that
  parse as component tags or wire numbers are **decoded inline** (`CB-10412` →
  *tag CB · sheet 104 · rung 12*). Recent searches come back as a dropdown while
  you type (kept across sessions), `F3` / `Shift+F3` step matches, and a bad
  regex shows a quiet — in the counter instead of an error popup. The panel
  also **stays put while you jump between matches** — it used to ride along
  with the page scroll and vanish off-screen on `Enter` — and short context
  lines no longer lose their last characters to a needless ellipsis.

## v1.3.1

- **Sharper printing.** Printed pages were soft: each page was rasterized at a
  fixed 200 dpi and then stretched to fill the sheet, so asking the driver for
  higher quality actually made it blurrier (a bigger upscale). Pages are now
  rasterized at a 600 dpi working resolution and drawn 1:1 into the printer's
  own page geometry — no enlargement — so fine line work and small text come out
  crisp, roughly three times the detail that reached the paper before. Large
  sheets (D/E-size) are rendered in horizontal bands, so
  full resolution is kept at any size without a huge bitmap; printing now shows
  a progress dialog you can **Cancel**, and print **preview** renders at screen
  resolution so previewing a long set stays fast and light.

## v1.3.0

- **Circle and line tools.** A **Circle** that behaves exactly like the rectangle
  (fill, opacity, resize, rotate, stacking, copy/paste) and a **Line** that
  behaves exactly like the arrow — just without the arrowhead. Both export as
  real PDF annotations (Circle / Line) and round-trip on reload.
- **Callouts are drawn arrow-first.** Placing a callout is now three clicks:
  **click what the arrow should point at**, **click again to end the arrow**, then
  **drag out the box from that end point and click to finish** (`Esc` cancels at
  any stage). The box is then edited exactly as before — resize it, retype it, and
  drag the orange tip to re-aim the arrow.
- **A callout's arrow now travels with its box.** Moving a callout takes its
  leader along, keeping the same offset, instead of leaving the tip pinned to the
  page point it was drawn at. Resizing the box still leaves the arrow aimed where
  you put it.
- **Recent files.** **File ▸ Open Recent** lists the last **10** drawings you
  opened, newest first — pick one to reopen it. The list is remembered between
  sessions, reopening a file moves it back to the top instead of duplicating it,
  a file that's since been moved or deleted is shown grayed out as *(not found)*
  rather than silently vanishing, and **Clear list** empties it.
- **Second viewer (reference pane).** **View ▸ Reference viewer** (**`F8`**)
  opens a second, **read-only** view of the same PDF — for keeping a legend, TOC
  or cover sheet on screen while you work on another page. It scrolls
  independently (and `Ctrl`+scroll zooms it on its own), shows marks made in the
  main viewer live, and docks or floats like any other pane (hidden until you ask
  for it). Drawing, editing and undo — and the toolbar's zoom/rotate/page/find
  controls — always stay with the main viewer.

## v1.2.0

- **Sheet-number split reads the box on rotated pages.** The "Split by sheet
  number" wizard's **preview** now de-rotates the box you draw the same way the
  split does, so it reads the sheet number on rotated pages (AutoCAD plots are
  almost always rotated) instead of showing "(nothing found)". Preview and split
  now share one read path, so they always agree. On **scanned** PDFs the box is
  now OCR'd automatically when Tesseract is installed (it no longer requires
  flipping an OCR switch in Settings first).
- **Sharper zoom past 400%.** The page bitmap used to stop re-rendering at 400%
  and just upscale (blurry) beyond that. It now rasterizes at the actual zoom up
  to the 8× ceiling, so normal sheets stay crisp when you zoom in — bounded by a
  per-page pixel budget so very large (E-size) sheets can't exhaust memory.
- **Print (`Ctrl+P`).** Print the drawing — with its marks — straight through the
  standard system print dialog (pick printer, copies, orientation, page range),
  to any installed printer (the Windows print spooler on Windows, CUPS
  elsewhere). Pages are fitted and centered on the sheet. **Print preview…** is a
  separate menu item for seeing the pages first, with an **Include markups**
  toggle (on by default) to print either the marked-up or the clean drawing. The
  printer is created without the blocking "contacting printer…" query that could
  hang the app.
- **View-only mode for files that can't have a markup database.** If a PDF's
  name is too long or contains characters that can't back its
  `<name>.markup.db` sidecar, the file now still **opens for viewing** (view,
  search, navigate, print, PDF tools) instead of failing to open. Markup and
  saving are grayed out, and a popup explains why and how to fix it (rename the
  file to something shorter/simpler and reopen).
- **Movable tabs.** The five main panes (Viewer, TODO, Wire Numbers, Component
  Labels, PDF Tools) are now floatable, dockable panels — like the Comments and
  Navigation sidebars. Drag a tab's title bar to **pop it into its own window**
  (e.g. the TODO list on a second monitor) or **dock it to another edge**;
  closed panes reopen from **View ▸ Panes**, and **View ▸ Reset panel layout**
  restores the default. The layout is remembered between sessions.
- **Copy & paste marks.** Text boxes, callouts, rectangles, arrows and clouds can
  be copied (**`Ctrl+C`** or right-click ▸ **Copy**) and pasted (**`Ctrl+V`**, or
  right-click empty canvas ▸ **Paste … here**). Multi-select copies together;
  repeated pastes cascade so they don't stack; pasted marks land selected and are
  undoable as one step.
- **Format painter.** Right-click ▸ **Copy formatting** then **Paste formatting**
  onto another mark **of the same type** to transfer its color, opacity, fill,
  border width and font — without touching the target's text or geometry.
- **Sticky styles.** Setting a color, opacity, fill or font on a new text box or
  callout is remembered as the default for the next one, so styles don't have to
  be re-declared for every mark (the text content is never carried over).
- **Stacking order.** Right-click a mark ▸ **Order** to **Bring to Front**,
  **Bring Forward**, **Send Backward** or **Send to Back** (undoable; the order
  persists and is honored in the exported PDF).
- **Smoother "Draw new".** Choosing **Draw new** when starting a mark on top of an
  existing one no longer re-prompts as you place the object — the pop-up asks
  once, then you draw freely.
- **Rename a commenter.** Double-click a name in the Comments **By** column (or the
  TODO **Commenter** column) to change who a mark is by — after a confirm, with an
  option to rename every mark by that person at once. Undoable.

## v1.1.0

Feature release from the user-group feedback sprint.

New markup:

- **Notes on any mark.** Any mark — highlight, pen, rectangle, arrow, cloud — can
  carry a free note, not just comments and text boxes. Right-click a mark ▸ **Add
  note… / Edit note…**; noted marks get a small orange corner badge, appear in
  the Comments sidebar (now with **Rectangle / Arrow / Callout / Cloud** filters),
  and on export each note also becomes a **standalone sticky-note comment** so
  it's visible in any viewer (Adobe, browsers, Preview).
- **Fill & opacity for rectangles and text boxes.** The new toolbar **Fill**
  button opens a color picker with a plain **opacity slider** (0% = no fill →
  100% = an opaque white **cover** that redacts what's beneath). Text boxes get a
  fill control in their editor; rectangles expose **Fill…** on right-click. Fills
  render on screen and in the exported PDF.
- **Callout tool.** Draw a text box with a leader arrow: drag the box, type the
  note, then drag the orange tip to point at the target. Exports as a genuine
  PDF FreeText callout.
- **Revision-cloud tool.** Mark areas with a scalloped cloud (outline only).
  **Drag** to draw freehand, **Shift+drag** for a rectangle, or **click** corners
  and **double-click / Enter** to close (Esc cancels). Exports as a PDF polygon
  with the standard cloud border effect.
- **Tool shortcuts.** `Ctrl+1`…`Ctrl+0` pick tools in toolbar order (Select →
  Cloud).
- **Export flattened PDF (for sharing).** Bakes the marks into the page so they
  render in **every** viewer — including ones that ignore annotations (some
  built-in previews, file thumbnails). The working file stays editable.

Workflow:

- **TODO audit strikethrough.** Checking a TODO off strikes it through both on
  the sheet (a line across the mark) and in the TODO list (a struck-out,
  dimmed row).
- **Save As — fork to a new working file** (`Ctrl+Shift+S`). Copies the current
  markup into a brand-new working file and switches to editing it; the original
  is left untouched.
- **Toolbar reorganized** into logical groups: select · highlight / pen / eraser
  · comment / text box / callout · rectangle / arrow / cloud.

## v1.0.3

Bug fixes (found in pre-beta testing):

- **Rotate grip works again.** Clicking a mark's resize/rotate grip now performs
  that action instead of starting a text selection — including the rotate grip,
  which sits just above the mark, and grips that overlap nearby text.
- **Ctrl+F re-searches stale text.** Reopening Find (or pressing Enter) with text
  already in the box re-runs the search and re-highlights the matches.
- **Delete key confirms.** Pressing `Delete` on a mark now shows the same "are
  you sure?" prompt as right-click / trash-bin delete (one prompt for a
  multi-selection).
- **Sheet auto-fill** now also reads the **bottom-right corner** of the title
  block (the lesser of the two numbers there) for drawings whose `THIS SHEET:`
  label isn't in the text layer. Still best-effort; the Sheet column stays
  editable.
- **TODO rows no longer drag-reorder** (filter + sort cover it; avoids accidental
  nesting).
- **Wire / Component double-click** now jumps to the label's spot on the drawing
  (the first occurrence for labels that repeat) with a brief pulse marker.
- **More known family codes:** `CBL, DV, EN, DN, GND, PDB, PRS, PW, SCR, SE, X`.
- **Family-code edits take effect immediately** — changing the known codes (or
  widths) in Settings re-flags already-extracted component labels without a
  re-extract.

New features:

- **Opening an already-open PDF** is blocked with a notice (a file and its
  `.marked.pdf` count as the same document).
- **Export hotkey:** `Ctrl+Shift+E` exports the annotated PDF.
- **One markup database, one `.marked.pdf`.** Opening a `.marked.pdf` reuses the
  original's single `.markup.db` (never a second one), and saving always updates
  the same `.marked.pdf` (never `.marked.marked.pdf`). If the original markup
  database is missing, a new one is started and you're told.
- **TODO filter** now matches across **all** columns (text, page, sheet,
  commenter, tags).

## v1.0.2

- **Viewer rotate is now in-memory and non-destructive.** The ribbon **↺ / ↻**
  rotate the whole document in the viewer only — nothing is written to disk, and
  rotating back (or a full turn) restores everything exactly. Markups, comments
  and highlights rotate with their page and stay correctly placed. (To bake a
  rotation into a saved file, use the **Rotate** tool in PDF Tools.)
- **Navigation pane jumps to the Viewer.** Selecting a page thumbnail or
  bookmark while on another tab now switches back to the Viewer and shows it.

## v1.0.1

- **Open PDFs with DSI Redline.** The Windows installer registers the app so it
  appears in the right-click **"Open with"** list and the **Default apps**
  picker; opening a PDF that way loads it into the Viewer and PDF Tools tabs.
  (Non-destructive — it never hijacks your current default handler.)
- **TODO tab:** double-click now edits the cell (Text / Sheet / Tag); the page
  cell stays read-only and jumps to the mark (also via right-click). Right-click
  a mark on the PDF to **reveal it in the TODO list / Comments**.
- **Sheet numbers:** grouping renamed Sheet → **Page**; added a real **Group:
  Sheet** plus an editable per-page **Sheet** column, auto-detected from the
  title block on searchable PDFs.
- **Viewer ribbon:** editable **zoom %** box.
- **Settings** organized into tabs; **Wire Numbers** gained a scanned-page
  AI/OCR engine picker.
- Crop/extract reconstructs tables best-effort from OCR geometry when no AI key
  is set.

## v1.0.0

- First stable release: continuous-scroll PDF viewer with markup, a
  comment/TODO workflow, wire-number and component-label extraction/export, PDF
  page tools, viewer text search, and the crop/extract wizard.
