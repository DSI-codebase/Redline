---
tags: [basics, install]
---

# Getting Started

## Install

DSI Redline needs **Python 3.11+**. From the app folder:

```bash
pip install -r requirements.txt
python main.py
```

You can also open a file directly: `python main.py drawings.pdf`.

Optional extras:
- **Tesseract** — only for scanned/raster pages. See [[OCR]].
- **Anthropic API key** — only for AI assist. See [[AI Assist]].
- **PyDRC** — only for [[Design Rule Check]]. Install with
  `pip install -r requirements-drc.txt`.

The app is fully functional offline without any of these.

## Open a PDF

**File ▸ Open PDF…** (`Ctrl+O`), **File ▸ Open Recent** (the last 10 drawings you
opened, newest first — pick one to reopen it, or **Clear list**), drag a PDF onto
the window, or — on a Windows install — **right-click a PDF ▸ Open with ▸ DSI
Redline**. See
[[File Associations]] to add DSI Redline to the *Open with* list and make it your
default PDF app. The drawing loads in the [[Viewer]] with continuous vertical
scroll (and into the [[PDF Tools]] tab). Any annotations already in the PDF (for
example a colleague's markup) are imported with their original authors — see
[[Storage and Files]].

## Tabs

DSI Redline is organized into these tabs:

1. **Viewer** — read and mark up the drawing. See [[Viewer]] and [[Markup Tools]].
2. **TODO** — your action items. See [[TODO]].
3. **Wire Numbers** — extract and export wire labels. See [[Wire Numbers]].
4. **Component Labels** — extract and export device tags. See [[Component Labels]].
5. **PDF Tools** — extract / split / delete / rotate / combine pages. See [[PDF Tools]].

### Moving the tabs around

Each of these tabs is a **movable pane** — just like the **Comments** and
**Navigation** panels. **Drag a tab's title bar** to:

- **pop it out into its own standalone window** (handy on a second monitor —
  keep the TODO list open beside the drawing), or
- **dock it to another edge** of the window, or split two panes side-by-side.

Drop it back onto the tab strip to re-tab it with the others. If you close a
pane with its **✕** button, bring it back from **View ▸ Panes**, and
**View ▸ Reset panel layout** snaps everything back to the default arrangement.
Your layout is remembered between sessions.

The **Comments** panel docks on the right of the Viewer — see
[[Comments Sidebar]].

## Save your work

- **File ▸ Save markup** (`Ctrl+S`) writes `<name>.marked.pdf` plus a
  `<name>.markup.db` sidecar. Your original PDF is never modified.
- **File ▸ Export annotated PDF…** writes a standalone annotated copy anywhere.
- **File ▸ Print…** (`Ctrl+P`) prints the drawing — with its marks — to any
  installed printer through the system print dialog, with page-range selection.
  Pages are rasterized at the printer's own resolution (at least 600 dpi) and
  handed to the driver at full detail — never enlarged to fit — so fine line
  work and small title-block text print crisply. A progress dialog (with **Cancel**) shows the job going.
  **Settings ▸ General ▸ Printing** sets a **minimum line weight** so AutoCAD
  hairlines don't come out anemic on paper; **Print preview…** has the same
  picker so you can judge it before committing.
- **File ▸ Print preview…** shows the pages first and has an **Include markups**
  toggle (on by default) so you can print either the marked-up or a clean drawing.

Full detail in [[Storage and Files]].

> If a file's name is too long or has characters that can't back its markup
> database, it opens **view-only** — you can still read, search and print it, but
> markup and saving are off until you rename the file. See [[Storage and Files]].

#basics
