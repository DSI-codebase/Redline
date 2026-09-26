---
tags: [basics, files]
---

# File View

The **File view** is where you pick a drawing to open, the way **File** works in
Microsoft Office. It covers the whole window below the menu bar.

- It appears when DSI Redline starts **without a file** to open.
- **`Ctrl+O`** or **File ▸ Open…** brings it up at any time.
- **← Back** or **`Esc`** returns to the drawing. Opening anything also closes it.

**File ▸ Open PDF…** still goes straight to the file dialog, and **File ▸ Open
Recent** still lists the newest 10 — both skip the File view.

The left side has two selections: **Recent**, below, and **Workspaces** — your
project folders. See [[Workspaces]]. When you have a current workspace, the File
view opens on it.

## Recent

Your recently opened drawings, newest first, in four groups: **Today**,
**Yesterday**, **This week** and **Older**, with each file's name, folder and
when you last opened it. **Click a row to open it.** Up to 50 are kept; change
that under **Files** in [[Settings]].

**One drawing is one row.** A drawing and its `.marked.pdf` copy share one
markup database (see [[Storage and Files]]), so opening either one updates the
same row. Clicking it opens the original `drawing.pdf`, which shows every mark.
The exception is a `.marked.pdf` whose database is missing: then the marked copy
opens, because it is the file that still carries the marks.

A file that has been moved or deleted — or is on a drive that isn't connected —
stays listed, grayed out as **(not found)**, rather than disappearing.

## Pinned

**Right-click a row ▸ Pin** keeps a drawing in the **Pinned** group at the top.
Pinned files never age out of the list and are not removed by **File ▸ Open
Recent ▸ Clear list**. **Unpin** to let one go.

## Search

The search field filters **Recent**, **Pinned** and every workspace's PDFs as
you type, and lists each hit under where it came from. Every word you type must
appear in the file's name or folder, so `2417 panel` finds
`E-101 Panel Schedule.pdf` in a `Project 2417` folder.

## Right-click a row

- **Open**
- **Pin / Unpin**
- **Add to workspace ▸** — copy it into a workspace folder. See
  [[Workspaces]].
- **Show in folder** — opens the file's folder (on Windows, with the file
  selected).
- **Copy path**
- **Remove from list** — takes it off Recent. The file itself is never touched.

## Browse… and drag and drop

**Browse…** at the bottom left opens the normal file dialog. You can also drop a
PDF anywhere on the File view to open it.

Related: [[Workspaces]] · [[Getting Started]] · [[Keyboard Shortcuts]]

#files
