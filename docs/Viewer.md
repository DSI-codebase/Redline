---
tags: [viewer]
---

# Viewer

The Viewer renders every page in one continuous vertical scroll, like the
Chrome PDF viewer. Pages render lazily and sharpen as you zoom in.

## Open a PDF

Use **File ▸ Open PDF…**, pass a file on the command line, or simply **drag a
PDF from your file manager and drop it onto the window** — it opens straight
into the Viewer.

## Navigate

| Action | How |
|--------|-----|
| Scroll | Mouse wheel / trackpad |
| Zoom in / out | `Ctrl` + scroll, or the `+` / `−` buttons, or `Ctrl` `+` / `Ctrl` `-` |
| Set an exact zoom | Type a percentage (or pick a preset) in the toolbar **zoom %** box |
| Fit width | **Fit W** button or **View ▸ Fit width** |
| Fit page | **Fit P** button or **View ▸ Fit page** |
| Pan | Hold **Space** and drag, or drag with the **middle mouse button** |
| Go to page | Type a page number in the toolbar **Page** box |

The toolbar's **zoom %** box always shows the current zoom and updates as you
zoom; type any percentage and press **Enter** to jump to it.

### Rotate the view

The **↺ / ↻** buttons rotate the whole document 90° counter-clockwise /
clockwise **in the viewer only** — handy for reading a sideways drawing. It is
**in-memory and non-destructive**: nothing is written to disk, and rotating back
(or a full turn) returns everything exactly as it was. Your **markups, comments
and highlights rotate with their page** and stay correctly placed. To bake a
rotation into a saved file instead, use the visual **Rotate** tool in
[[PDF Tools]], which writes a new rotated PDF.

The current page number updates automatically as you scroll. The left
**Navigation** pane (page thumbnails + bookmarks) and the right **Comments**
pane toggle with **F9** and **F10**. Clicking a **page thumbnail or bookmark**
jumps the Viewer to it — and if you're on another tab (TODO, Wire Numbers, …)
it switches back to the Viewer automatically.

## Arranging the panels

The **Navigation** and **Comments** panes — **and the five main tabs** (Viewer,
TODO, Wire Numbers, Component Labels, PDF Tools) — are dockable,
Visual-Studio-style: **drag a pane's title bar** to snap it to any edge (left,
right, top or bottom), drop it onto another pane to **tab** them together, split
panes side-by-side, or pull one out of the window to **float** it on a second
monitor. Reopen a closed pane from **View ▸ Panes**. Your arrangement (and the
window size) is **remembered between sessions**; **View ▸ Reset panel layout**
puts everything back to the default. See [[Getting Started]] for more on moving
the tabs around.

## Second view (reference pane)

Need to check a **legend**, **TOC** or **cover sheet** while you work on another
page? Turn on **View ▸ Reference viewer** (**`F8`**) for a second view of the
**same** PDF.

- It **scrolls independently**, and **`Ctrl`+scroll** zooms it on its own — park
  it on the legend and keep marking up page 47 in the main viewer.
- Marks you add in the main viewer **appear in it live**, so it doubles as a
  second look at your redlines.
- It's **read-only**: you can scroll, zoom and select/copy text there, but
  drawing, editing and deleting always happen in the main viewer — so there's
  never any doubt about what `Ctrl+Z` or the toolbar will affect.

> The toolbar and menus always drive the **main** viewer: the zoom box, **Fit
> W/P**, the **↺ / ↻** rotate buttons, the **Page** box and **Find** (`Ctrl+F`)
> all act there, not on the reference pane. In the pane itself, use scrolling
> and `Ctrl`+scroll.

Like every other pane it's dockable: drag its title bar to put it side-by-side,
below the main viewer, or **float it onto a second monitor** (see
[[Getting Started]]). It stays hidden until you ask for it.

## Select & copy text

With the **Select** tool active, **drag across text** to highlight it (just like
a web browser) and press **`Ctrl+C`** to copy it to the clipboard. Line breaks
are preserved. Clicking an existing mark still selects/moves it; dragging on
empty page area selects text.

## Find in the document

Press **`Ctrl+F`** to open the search panel (pinned top-right of the viewer). It
searches as you type and stays open until **you** close it — the **✕**, or
**`Esc`** pressed inside the panel. Clicking or drawing on the drawing, loading
another file, or pressing `Esc` on the canvas never dismisses it. Step through
matches with **`Enter`** / **`Shift+Enter`**, **`F3`** / **`Shift+F3`**, or the
▲ / ▼ buttons; the current match is highlighted in orange and scrolled into
view, with an *i/n* counter.

**Match list.** Every hit is listed in a scrollable dropdown under the search
box, grouped by page (with the detected **sheet number**) and shown with the
surrounding line of text. Click a row to jump straight to that match — it lands
with a pulse ring so your eye finds it.

**Options.** Toggles under the box:

- **Aa** — match case.
- **Word** — whole words only (`10` no longer matches inside `10412`).
- **`.*`** — regular expressions, e.g. `CB-\d+` for every breaker tag or
  `30{2}\d{3}` for a wire range. A bad pattern shows a — in the counter with
  the reason as its tooltip, never an error popup.
- **Marks** — also searches your markups: comments, text boxes, callouts and
  the notes attached to any mark. Those hits carry a small ✎ and show the mark's
  kind and author in the tooltip.

**It knows the drawing's language.** When a matched token parses as a component
tag or wire number under your naming convention (see [[Settings]]), the row
decodes it inline — `CB-10412` shows *tag CB · sheet 104 · rung 12* — so you can
tell at a glance which hits are device tags and where they claim to live.

**History.** Recent searches (the last 10) come back as a dropdown while you
type, remembered between sessions.

## Marking up

Pick a tool from the toolbar to start annotating — see [[Markup Tools]]. The
**Comments** dock lists everything you add ([[Comments Sidebar]]).

See also [[Keyboard Shortcuts]].

#viewer
