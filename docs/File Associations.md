---
tags: [install, windows, file-association]
---

# File Associations

On a **Windows install** (the Inno Setup installer), DSI Redline can register
itself as a PDF viewer so you can open drawings straight from File Explorer.
When you pick it, the app launches with that PDF already loaded into the
[[Viewer]] and the [[PDF Tools]] tab.

## During install

The installer shows a **"Register DSI Redline as a PDF viewer"** checkbox (under
*File associations*), ticked by default. Leaving it on:

- **Adds** DSI Redline to the right-click **Open with** list for `.pdf` files.
- Lists it in **Settings ▸ Apps ▸ Default apps** so you can make it your default.

It is **additive** — installing does **not** change your current default PDF
app. Uncheck the box if you'd rather not register it.

## Open a single PDF with DSI Redline

Right-click any PDF ▸ **Open with ▸ DSI Redline**. If it isn't listed yet,
choose **Open with ▸ Choose another app**, pick **DSI Redline** (use *More apps*
/ *Choose an app on your PC* and browse to `DSI Redline.exe` if needed).

## Make DSI Redline the default PDF app

Windows 10/11 doesn't let an installer silently take over the default handler —
**you** confirm it once:

- **Quickest:** right-click a PDF ▸ *Open with* ▸ **Choose another app** ▸ pick
  **DSI Redline** ▸ tick **Always use this app to open .pdf files** ▸ **OK**, or
- **Settings ▸ Apps ▸ Default apps** ▸ search **DSI Redline** (or set the default
  for the `.pdf` file type) and choose it.

To revert, do the same and pick your previous PDF app.

## Running from source

The file-association entries are created by the **installer**. If you run from
source (`python main.py`) there's no registered executable, so use
**File ▸ Open PDF…**, drag-and-drop, or pass the path on the command line:

```bash
python main.py "C:\path\to\drawing.pdf"
```

## Uninstalling

Uninstalling DSI Redline removes everything it registered (its ProgID, the
*Open with* entry, the app registration and the Default-Apps capability). If it
was set as your default, Windows reverts the `.pdf` default to your next choice.

Related: [[Getting Started]] · [[Viewer]] · [[PDF Tools]]

#install #windows
