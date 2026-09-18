---
tags: [markup, tools]
---

# Markup Tools

Choose a tool from the toolbar; only one is active at a time. Each new mark
records **who** made it (your name from [[Settings]]) and **when**.

## The tools

The toolbar groups the tools by purpose: **Select** · highlight / pen / eraser ·
comment / text box / callout · rectangle / arrow / cloud.

- **Select** — click a mark to select it; drag to move; use the handles to
  resize and rotate (see below). Drag on empty space to rubber-band select.
- **Highlight** — drag a translucent box. Color and opacity from the toolbar.
- **Pen** — freehand stroke; the path is smoothed. Color + width from the toolbar.
- **Eraser** — removes whole marks. See [[Eraser]].
- **Comment** — drops a sticky-note bubble and prompts for text. See [[Comments Sidebar]].
- **Text box** — type text that renders directly on the page. The dashed border
  matches the text color. **Double-click to edit** the text *and* its font —
  size, color, **bold** and *italic* can all be changed after the fact. Give it
  an opaque **Fill** to lay a solid cover over the drawing beneath.
- **Callout** — a text box with a **leader arrow**, drawn **arrow first** in
  three clicks:
  1. **Click what the arrow should point at** (the target).
  2. **Click again where the arrow ends** — that's also where the box starts.
  3. **Drag out the box** from there and **click to finish**, then type the note.

  **Esc** cancels at any stage. Afterwards the box moves, resizes and edits like
  a text box, and the orange **tip** grip re-aims the arrow. **Moving the box
  takes the arrow with it** (it keeps the same offset); resizing the box leaves
  the arrow pointing where you put it.
- **Rectangle** and **Circle** — shapes with color + width that also take a
  **Fill** (right-click ▸ *Fill…* to change it later). The circle is drawn in a
  bounding box and behaves exactly like the rectangle.
- **Arrow** and **Line** — the same shape with and without an arrowhead; drag
  from one end to the other.
- **Cloud** — a revision cloud, outline only. **Drag** to draw it freehand,
  **Shift+drag** for a rectangular cloud, or **click** each corner and
  **double-click** (or press **Enter**) to close the loop; **Esc** cancels.

Color, pen width, font size, **B**old and *I*talic apply to the active tool. The
**Fill** button applies to rectangles, circles and text boxes/callouts and opens
a small dialog with a color picker and an **opacity slider** (0% = no fill,
100% = an opaque cover). Rectangles and circles also expose **Fill…** on
right-click.

> [!tip] Tool shortcuts
> Press **Ctrl + a number** to pick a tool: **Ctrl+1** Select, **Ctrl+2**
> Highlight, **Ctrl+3** Pen, **Ctrl+4** Eraser, **Ctrl+5** Comment, **Ctrl+6**
> Text box, **Ctrl+7** Callout, **Ctrl+8** Rectangle, **Ctrl+9** Arrow,
> **Ctrl+0** Cloud. These are pinned to the tool, so they don't shuffle when new
> tools are added — **Circle** and **Line** are a click away on the toolbar.

## Notes on any mark

Any mark — not just comments and text boxes — can carry a **note**. Right-click a
highlight, pen stroke, rectangle, arrow or cloud and choose **Add note… /
Edit note…**. Noted marks show a small orange badge and appear in the
[[Comments Sidebar]]. On export, each note also becomes a **standalone
sticky-note comment** so it's visible in any PDF viewer (Adobe, browsers,
Preview), and it round-trips back onto its mark when reopened here.

## Move, resize, rotate

Switch to **Select** and click a mark. Rectangles, highlights, text boxes and
arrows show:

- **Blue corner handles** — drag to resize.
- A **green handle** above the mark — drag to rotate (like Microsoft Word).

Move by dragging the body. Everything is undoable — see [[Undo and Redo]].

## Copy, paste & formatting

Text boxes, callouts, rectangles, arrows and clouds can be **copied and pasted**:

- Select one (or several) and press **`Ctrl+C`**, or right-click ▸ **Copy**.
- Press **`Ctrl+V`** to paste — each paste drops a copy slightly offset so they
  don't stack — or right-click empty canvas ▸ **Paste … here** to place it where
  you click. Pasted marks land selected and are undoable.

To reuse just the *look* of a mark (its **color, opacity, fill, border width and
font** — not its text or size on the page), use the **format painter**:

- Right-click a mark ▸ **Copy formatting**.
- Right-click another mark **of the same type** ▸ **Paste formatting**. (The
  option is grayed until you've copied formatting from a matching kind.)

> [!tip] Styles are remembered
> When you set a color, opacity, fill or font on a new text box or callout, the
> next one you draw **inherits those settings** — so you don't re-declare them for
> every mark. (The text itself is never carried over.)

## Stacking order (which mark is on top)

Right-click any mark ▸ **Order** to change how overlapping marks stack:

- **Bring to Front** / **Send to Back** — jump to the very top or bottom.
- **Bring Forward** / **Send Backward** — move one step.

The order is undoable, persists with your markup, and is honored in the exported
PDF.

## Editing an existing mark while a draw tool is active

If you click an **existing** mark while a drawing tool is selected, DSI Redline
asks whether you want to **Edit existing** or **Draw new**. Choosing *Edit*
switches you to the Select tool with that mark selected. Choosing **Draw new**
lets you place the new object right away — the prompt asks **once** and won't
interrupt again while you draw it.

## Live preview

While you drag, the shape previews in place; when you release, it stays exactly
as previewed and remains fully editable. Press **Esc** to cancel a mark while
you're drawing it.

## Right-click a mark on the page

Right-click any mark on the page for a quick menu: **Add note… / Edit note…**,
**Reveal in Comments**, **Delete** (with confirm), plus **Fill…** on rectangles
and **Show comment contents** on comments/text boxes. Copyable shapes also get
**Copy**, **Paste**, **Copy formatting** and **Paste formatting** (see above).
When typing a comment, text box or callout, **Ctrl+Enter** or **Shift+Enter**
saves it (same as OK), and **Esc** cancels.

## TODO audit strikethrough

When a mark is flagged as a **TODO** (via its editor or the [[TODO]] tab),
checking it off strikes it through both **on the sheet** (a line across the mark)
and **in the TODO list** (a struck-out, dimmed row), so an audit reads at a
glance.

## Shapes vs. portability

All marks are saved as standard PDF annotations so they open in Adobe, Chrome,
etc. — see [[Storage and Files]]. Sticky-note comments carry a real popup.

Related: [[Comments Sidebar]] · [[TODO]] · [[Eraser]] · [[Undo and Redo]]

#markup
