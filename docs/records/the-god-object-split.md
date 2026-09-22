# `main_window.py` was 2,506 lines, and what came out of it

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

## The window held four dialogs, and the convention says where a dialog lives

`app/main_window.py` was **2,506 lines** — 718 more than the next largest
module, and 8.6% of a 29,260-line codebase — holding the preferences dialog,
five panes, the toolbar, the menus and the file lifecycle. The README's own
layout block described it that way (*"Window: five … panes, toolbar,
Settings"*), so the document was right about a thing that was wrong.

**The finding is not the line count, and it is not a home that was ignored
either** — which is what a first draft of this section claimed, before the
package was measured. The rule this repository already follows is *a dialog
lives beside the subject it serves*: `app/tools/dialogs.py` holds
`_ToolDialog` and seven page-operation dialogs, `app/tools/wizards.py` two
more, and the README names both under `tools/`. That convention is intact and
was never broken. **The four in the window are the ones with no subject
package to go to** — preferences, the text/callout editor, the fill picker,
waive-a-finding — so they accreted at the place they happened to be opened
from, which is the one location the convention does not name.

- **Cut by AST span, and the grouping was MEASURED rather than eyeballed.**
  Asking which top-level names each unit references gives
  `TextEditDialog -> {FillDialog, _swatch, _fill_swatch}`,
  `FillDialog -> {_fill_swatch}`, and **`SettingsDialog -> {}`** — so the
  preferences dialog is a clean standalone and gets its own file, while the
  editor, the fill picker and their swatch icons genuinely travel together.
  `_apply_font` and `WaiveDialog` reference nothing and travel with them
  because they are the same subject, which is stated rather than implied.
- **2,506 → 1,879**, and the rest is **named rather than glossed**: the five
  panes, the toolbar, the menus and the lifecycle are all still in there. The
  module docstring says so, and the row is recorded `partial` for that reason —
  half the value of recording a partial is naming the other half.
- **Eighteen imports went dead the moment the dialogs left**, and every one was
  cross-checked with a text scan before removal: each appeared exactly once,
  which is the import itself. `annotations` stays — it is `from __future__`.
- **The tests were re-pointed at the new homes, and that is the half that makes
  the split checked.** Four modules imported these names `from app.main_window`,
  and they would have gone on passing untouched, because `main_window` legitimately
  imports what it opens — so the names are still in its namespace. A green suite
  there proves the window still works, not that the new module does.
- **Verified in BOTH directions, which is the only way to tell a fix from a
  withdrawal** — this file's own rule from the Qt-degradation round. Before:
  **735 tests across 57 modules, 28 skipped**. After: **740 across 58, 28
  skipped**, identical skip reasons, every module passing under `--strict`. The
  +5 is the new gate module; no test was lost and no skip was added.

### The gate is a KIND of thing, never a line count

A count is a snapshot — wrong by the next commit, and this file already
removed three of them from its own header for exactly that. What
`tests/test_module_layout.py` asserts instead is that **no dialog class is
defined in `app/main_window.py`**, which is permanent, is what was extracted,
and is what an accumulation would look like on its first step.

- **By base class, not by the class's own name.** A class called `FooDialog`
  subclassing `QWidget` is not one and a `QDialog` subclass called `Prefs` is,
  so the sweep reads the bases.
- **...and the first draft read DIRECT bases only, which left a reachable
  hole.** `app/tools/dialogs.py` declares `_ToolDialog(QDialog)` and seven
  subclasses **of it**, all importable — so a `class Foo(_ToolDialog)` back in
  `main_window` was exactly the accumulation this gate exists to catch and
  exactly what it could not see. A base whose *name* ends in `Dialog` counts
  too, which is not the name-check the bullet above argues against: it is a
  claim about what the class derives from rather than about what it is called.
  **Measured before it was taken**, because a widening that admits noise is a
  gate people learn to dismiss: across `app/` it admits those seven and
  **nothing else**, 7 classes over four files becoming 14, zero false
  positives. That number is what made it a fix rather than a stated limit.
- **Two floors, because an absence assertion agrees with an empty checkout.**
  The extracted classes must be findable in their new homes, and the sweep must
  still find dialogs across `app/` at all — without the second, renaming the Qt
  base names the sweep knows switches the whole module off while every
  assertion above it still passes. That arm fires, measured.
- **The README block is gated against the filesystem, never against a second
  document.** Every `.py` it names must exist, and the two new modules must be
  named — the block described the god-object accurately for as long as it was
  true, and a layout block that stops matching the tree sends a reader to the
  wrong file.
- **And one of those floors was a COUNT ASSERTION WEARING A FLOOR'S MESSAGE.**
  The block names five modules and the floor read `> 4`, so removing any line
  from the README fired it — reporting *"the parse is not finding module
  names"* about a block that had parsed perfectly, which is a note carrying a
  reason that is not its own. It is `> 2` now: what it has to catch is the
  parse breaking, which takes it to zero or one. Caught because the arm that
  deletes a README line fired **two** tests where one was expected, so the
  expectation was the thing that was wrong.

Falsified seven ways, each on its own arm and every one firing: a dialog moved
back into the window, an **indirect** dialog moved back into it, each extracted
class stripped of its Qt base in turn, the sweep's base names renamed away
(which fires the floor **and** the new-home check, correctly — one injection,
two things it makes vacuous), the README no longer naming a new module, and the
README naming a module that does not exist.

### The base-rename arm was net-ZERO bytes, and Python's cache could not see it

That arm reported `DEAD` against a gate that fires two failures when the same
injection is made by hand — this repository's own standing rule arriving on
schedule: **if a falsification says nothing fired, suspect the reading before
the gate.**

The cause is arithmetic and worth keeping, because nothing about it looks like
a trap. The rename is `QDialog`→`QNotADialog` (+4), `QMessageBox`→`QNope` (−6),
`QFileDialog`→`QAlsoNope` (−2), `QColorDialog`→`QStillNope` (−2) and then
`"Dialog"`→`"NoSuchSuffix"` (+6) — **exactly 0**, measured rather than noticed:
6,899 bytes before and 6,899 after. CPython invalidates a `.pyc` on
**`(mtime, size)`** at one-second resolution, so a restore-then-edit-then-run
inside one second handed the subprocess **stale bytecode of the uninjected
file**. Every other arm edited an `app/` module whose length changed, which is
why four of seven were unaffected and the two that were not looked like dead
gates.

**A falsification loop that injects into the TEST file must purge
`__pycache__` and run `-B`.** The arms that edit the *subject* are safe by
luck — they change a length — and the arm that edits the *instrument* is the
one nobody thinks to protect, which is the same shape as the snapshot rule one
line over: it is the instrument rather than the subject.

## ...and then printing, which is a subject rather than a property of a window

409 contiguous lines of `main_window.py` — nine methods and four class
constants — were the printer, the two print dialogs and the page raster. They
are `app/printing.py` now, and the module is **1,879 → 1,492**.

- **One contiguous span, which is what made "nothing was lost" assertable.**
  `_new_printer` at 903 through the end of `_print_page` at 1311, with no
  non-printing method between them, so the cut is a slice and the check is that
  the slice put back beside what stayed reproduces the file it came from.
- **The conversion is a parameter list rather than a redesign, and that was
  MEASURED before the cut.** Every one of the nine either already carried
  `@staticmethod`/`@classmethod` or touched `self` for nothing but `document`
  and the two print settings. So the pure half — `fit`, `render_dpi`,
  `paint_page` — is callable with no Qt window at all, which is what
  `tests/test_v12_print.py` had always driven it as.
- **`PrintOptions` exists because the preview WRITES the settings.** The
  toolbar's markups checkbox and line-weight picker set them and the job reads
  them; with the code out of the window, two window attributes it wrote back
  into would be the printing code half out of the window. One small mutable
  object, held by `MainWindow` as `self.print_options`.
- **The status bar stayed the window's.** `run_print_dialog` returns the
  sentence and `MainWindow.print_document` shows it — a printing module that
  knew which widget has a status bar would be the window's business back in
  here under another name.
- **`self._preview_weight_combo` did not travel, because it is write-only —
  measured, not reasoned.** Assigned once and read nowhere in the repository.
  Driven under Qt: a combo added with `QToolBar.addWidget` and then dropped on
  the Python side survives `gc.collect()` and is still usable through
  `widgetForAction`, because the toolbar takes ownership — and the `_changed`
  closure holds it as well. A keep-alive that keeps nothing alive.
- **A clause of the module docstring was WRONG and had been carried forward
  unread.** It named "the five panes" as still in the window; `app/panels/`
  holds eight pane modules and has for a long time. What the window holds is
  their DOCKING. That is the same drift this file already gates one document
  over, in the docstring of the module being unwound.

### The gate is the same KIND of claim, in printing's vocabulary

*The window neither drives a printer nor rasterises a page.* Permanent,
exactly what was extracted, and what an accumulation looks like on its FIRST
step — a print helper written back into the window reaches for
`PySide6.QtPrintSupport` or for `fitz` on its first line, because those are
the two libraries the job needs. Measured before it was taken: every one of
those imports in `main_window.py` was inside the printing block, so the claim
is **zero** rather than a threshold.

- **Function-local imports are walked, which is the whole point.** All nine
  methods imported `QtPrintSupport` or `fitz` *inside* themselves, so a
  top-level scan would have called the window printer-free while it drove a
  printer nine times.
- **Two floors, pointing opposite ways.** The names must be findable in
  `app/printing.py` — an absence assertion is satisfied by a checkout where
  printing was deleted — and `MainWindow` must still offer both print actions,
  because a window that stopped offering them satisfies every other assertion
  here and is not what moving it meant.

### Re-pointing the tests is what found the two real defects

The previous extraction records why the tests must move: `main_window`
legitimately imports what it opens, so `win._print_fit` still resolves and a
green suite there proves the window works rather than that the new module
does. Doing it turned up two things a reading would not have:

- **A monkey-patched class constant SEGFAULTED the interpreter.**
  `test_bands_join_when_raster_outruns_the_viewport` saves and restores
  `MainWindow._PRINT_BAND_PX`, which no longer exists — and the `keep = …` line
  sits *before* its own `try`, so the `AttributeError` escaped with a `QPainter`
  still active on a `QImage`. Qt printed `QPaintDevice: Cannot destroy paint
  device that is being painted` and the process died. Loud, and loud about the
  wrong thing: a `SIGSEGV` reads as a Qt problem, not as a test patching a name
  the code stopped reading.
- **A second test called `win._add_markups_toggle`**, which is now the module's
  and takes the options. It failed by name, which is the good direction.

**Verified in BOTH directions**, this file's own rule from the Qt-degradation
round, because a skip added where a test used to run looks exactly like a fix:
HEAD **740 tests across 58 modules, 28 skipped**; after the extraction and the
re-pointing, **740 / 58 / 28** with identical skip reasons — no test lost, no
skip added — and **745 / 58 / 28** with the five tests this round added.

### ...and two DEAD arms were coverage gaps rather than dead gates

Twelve injections, ten firing. The two that did not are the ones worth the
space, because in both cases the code was right and **nothing was asking it**:

- **`MainWindow.print_preview` was driven by no test at all.** Passing `None`
  where the window hands over its `print_options` fired nothing: the preview's
  own controls are exercised directly against the module, and the wrapper —
  which is now the window's entire remaining half of printing — was covered
  only by the AST gate asserting it exists. `print_document` had a test and
  its sibling did not.
- **The line-weight picker's WRITE was untested while its READ was covered
  four ways.** Deleting `options.min_line_pt = …` left every weight test
  green, because those set the option directly and paint with it. The markups
  toggle beside it had both halves; this one had one, and the asymmetry is
  invisible until something breaks the half nobody drives.

Both now have a test, and re-run they fire — as does passing the wrong
document to the other wrapper, and dropping the picker's signal connection.
**Fourteen arms, every one firing on its own defect**: a print helper written
back into the window reaching for `QtPrintSupport`, the same reaching only for
`fitz`, the sweep narrowed to top-level imports, printing deleted rather than
moved, the window no longer offering the actions, either wrapper handing over
the wrong thing, the toggle and the picker each writing nowhere the job reads,
the picker's signal dropped, the README losing the module, the README naming
one that does not exist, the band margin removed, and `render_dpi` falling
back to the paint viewport.

## ...and the last three, where the row asked for a measurement before the cut

The backlog row's own `remains` named the toolbar, the menus and the file
lifecycle, and said of the first two that they *"build the same actions and may
not be separable, which is a measurement somebody has to take before cutting"*.
**The measurement refutes it**, and it is a better answer than a guess either
way:

- **They write 11 self-attributes each and share NONE.** The toolbar owns
  `tool_group`, `_tool_actions` and the nine style/zoom/page widgets; the menu
  owns ten `act_*` QActions and `m_recent`. Neither reads what the other
  writes.
- **They overlap in exactly ONE import** (`QKeySequence`). The toolbar needs
  eleven widget classes the menu needs none of — because the toolbar
  **constructs** widgets where the menu **wires** methods that already exist.
  So the split is by kind, which is a fact about them, rather than by line
  count, which is a fact about nothing.

`app/toolbar.py`, `app/menus.py` and `app/lifecycle.py`. **2,506 → 1,879 →
1,492 → 1,081**, and each carries the same *kind* of claim the printing gate
does rather than a number:

- **The window imports no widget class.** Measured before it was taken: moving
  the toolbar out leaves **ten** imports unused, so the assertion is zero
  rather than a threshold. (`QApplication` was already dead and went with them;
  it is not counted as freed by the cut.)
- **The window no longer imports `Document` at all** — the sharper of the two,
  because it is about the model rather than the furniture. It asks
  `lifecycle.open_document` for one.
- **A wrapper exists on the window exactly where a consumer names it.**
  `load_document` is named by `main.py` and twenty test modules, `closeEvent`
  is Qt's own hook, `save_as_fork` and `_rebuild_recent_menu` are named by
  tests — all four keep their names. `_build_toolbar` and `_build_menu` were
  named by `__init__` and nothing else, so they kept none, and **both halves
  are asserted**: a wrapper reappearing for them is a second place to look for
  one builder.

**And the wiring got a gate it never had.** `app/menus.py` names fifteen
`win.<handler>` and cannot see the class, so a renamed method fails **when
somebody clicks it** — not at import, not at build. The sweep walks for a bare
`win.<name>` handed to a call and requires `MainWindow` to have it; measured at
zero today, with `close` the one declared exemption (QWidget's, and the Quit
action is meant to use it) gated in both directions.

### The falsification found the guard nothing was checking

Two arms came back DEAD, and they are the two `lifecycle.py`'s own docstring
calls *the hard-won orderings*. They are not the same kind of DEAD:

- **"closes the old document before building the new one" was a fact about my
  READING.** It is covered — in `tests/test_v12_refview.py`, where two views
  made the symptom worse — and my falsification subset did not include that
  module. *If a falsification says nothing fired, suspect the reading before
  the gate*, and here the reading was which modules I ran.
- **"refuses to open the document that is already open" was a real gap.**
  Measured on the whole suite rather than the subset: with the guard replaced
  by `if False:` it is **751 tests across 58 modules, 28 skipped, all modules
  passed**. A feature the code numbers *Feature 1* could have been deleted
  without a red tick.

What that guard prevents is not cosmetic, which is why it is worth a module of
its own. `foo.pdf` and `foo.marked.pdf` resolve to **one** `foo.markup.db`, so
opening the second over the first puts two `Document` objects on one SQLite
sidecar — the thing `app/model/storage.py` exists to make impossible. It reads
to a user as an ordinary *open a file* and it is a second writer on the marks.
`tests/test_lifecycle.py` asserts the premise first (the two really do share a
sidecar, or the guard would be refusing two different documents), then both
refusals, then the complement — because a guard that refused everything
satisfies both and leaves the application unable to open a second file.

**Nineteen arms, every one firing on its own defect** — a widget class imported
back, `Document` imported back, each module's entry point renamed, the
`load_document` wrapper dropped, `_build_toolbar` back as a wrapper, a menu
handler naming a method the window lacks, `MainWindow` growing a `close()` of
its own, nothing wiring `close` any more, the handler walk finding nothing, the
README losing a module and naming one that does not exist, `__init__` no longer
building either, `on_close` no longer asking, the recent list never rebuilt,
the already-open guard removed, that guard comparing PATHS rather than sidecars
(the case `foo.marked.pdf` is about), and the complement's second open deleted.

Verified in both directions, which is the only way to tell a cut from a
withdrawal: **745 tests across 58 modules, 28 skipped before and after the move
itself**, identical skip reasons, then 755 across 59 with the ten new gates.
