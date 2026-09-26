---
tags: [basics, files]
---

# Workspaces

A **workspace** is a project folder you declare — a job's root folder — and it
holds **every PDF under that folder**, at any depth. Workspaces live in the
[[File View]] under **Workspaces**.

They exist for one problem: after an afternoon of looking through unrelated
PDFs, a project's drawings have dropped off [[File View|Recent]]. A workspace
keeps **its own recent list**, which only files inside it can reach, so going
back to project work starts where you left it.

## Add one

- **Add workspace…** — pick an existing project folder.
- **New workspace…** — pick where it goes and type a name. DSI Redline creates
  the folder with its **quick subfolders** (`drawings`, `documentation` and
  `notes` unless you change them under **Files** in [[Settings]]).

Workspaces can't be inside one another. Adding a folder inside a workspace, or
one that contains a workspace, is refused with the name of the workspace in the
way.

Your workspaces are remembered for you on this computer. Nothing is written
into the folder itself — except the folders **New workspace…** creates.

## The list

Pinned workspaces first, then the rest by when you last used them. Right-click
one for **Open**, **Pin / Unpin**, **Rename…** (the folder keeps its name),
**Locate…** and **Remove from list**. Removing a workspace never touches the
folder or its files.

A workspace whose folder can't be found — a drive that isn't connected, or a
folder that was moved or renamed — stays listed as **(unavailable)**. Open it
and choose **Locate…** to point it at the new place: its favorites and hidden
folders carry over, because they are remembered relative to the folder.

## A workspace's page

When the File view opens, it goes to the **current workspace**: the one holding
the drawing you have open, otherwise the one you last opened here. Its page
has three sections:

1. **Favorites** — right-click any file ▸ **Favorite** to keep it at the top.
2. **Recent in this workspace** — every drawing inside the folder you opened,
   however you opened it (the File view, **Open PDF…**, a drop, or a
   double-click in Explorer). It keeps 25; change that under **Files** in
   [[Settings]].
3. **All files** — every PDF, as a tree by subfolder, with when each was last
   modified. A drawing and its `.marked.pdf` are one row, as on
   [[File View|Recent]].

Above them, a count such as *412 PDFs in 9 folders*, a **Refresh** button, and a
filter for the whole page. The folder is read in the background each time the
page is shown, so a large project on a network drive fills in as it goes. If a
folder can't be read, the count says so rather than leaving it out quietly.

## Hide a folder

Project folders often hold `Superseded` or `Archive` folders full of old PDFs.
Right-click a folder ▸ **Hide from workspace** to leave it out of this
workspace's list and of search. Tick **Show hidden folders** to see them again
(grayed), and right-click ▸ **Show in workspace** to un-hide one. Folders
starting with `.`, and folders Windows marks hidden or system, are never
listed.

## Search

The search on the File view's **Recent** page covers every workspace too. Hits
are listed under the workspace they came from.

Related: [[File View]] · [[Settings]]

#files
