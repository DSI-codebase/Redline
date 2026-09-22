# DSI Redline (`PDF_MarkupApp`) — working notes

A desktop reviewer for AutoCAD Electrical drawing sets: continuous-scroll PDF
viewing, markup, a comment/TODO workflow, wire-number extraction and export,
and an optional design-rule audit. PySide6 + PyMuPDF, fully functional offline.

`README.md` is the feature list. `CI.md` is the workflows, the skip rules and
the release ordering, and is authoritative for all three. `docs/` is the user
manual, served in-app by `app/help.py`. This file is the standing rules.

## Run it

```bash
pip install -r requirements.txt        # the app
pip install -r requirements-drc.txt    # ...and design rule checking (private)
python tools/run_tests.py
python main.py
```

**CI runs that on Ubuntu and Windows with `--strict`, and with `--require-drc`
whenever the PyDRC token is present — so a skip fails the run rather than hiding
under a green tick.** Gated by `tests/test_run_tests.py::TestMissingOptional`,
which reads the flag out of the workflow step's own `run:` script. **No count is written here**:
the runner prints it grouped by skip reason, and three once accreted in this file
while nothing read any of them.

## The original file is never overwritten

Storage is deliberately hybrid, and this is the one boundary a change must not
cross: marks are standard PDF annotations in a **`*.marked.pdf` copy**, so
another tool can read them and the source set is untouched, and app-only state —
TODO status, tags, the wire cache — lives in a **`*.markup.db` SQLite sidecar**
beside it. A file whose name cannot back a sidecar opens **view-only** rather
than half-working: view, search, print and the PDF tools stay, markup is off
until it is renamed. Degrading to a named, explained state beats saving somewhere
the user did not ask for.

**That was a sentence in five documents and enforced nowhere until 1.5.2.** Three
refusals in `app/model/storage.py` now, called from every write: never this
document's own original (refused even when absent, because writing it *creates*
the pristine base every later open reads from), never another drawing that holds
marks here, and `refuse_overwriting_input` so a page tool cannot eat its own
input. `app/tools/pdf_ops.py` routes all eleven writers through one `_guard_out`,
and `tests/test_never_overwrite_original.py` walks that module's AST and fails on
a writer that has none — a gate over the artifact rather than over a list of the
functions that existed when it was written.

Two things they deliberately do **not** do: rule 2 asks whether the sidecar holds
**annotations** rather than whether it exists, because opening a PDF creates one
unconditionally; and a PDF this app has never opened is not protected, being
indistinguishable from a stale export the save dialog has already asked about.

## Three optional dependencies, one pattern

`pydrc` (design rules), `ezdxf` (reading ACADE source drawings) and `anthropic`
(AI extraction) are each absent on some real installs, and every one **reports
itself unavailable in the place it would have been used** rather than raising.
Only `requirements.txt` is the app; PyDRC is in `requirements-drc.txt` because
that repository is **private**, and a plain install would otherwise fail for
anyone without credentials, CI runners included.

**`tests/_qt.py` is the one Qt probe**, and it probes the thing rather than a
proxy: whether `PySide6` imports at all, under `except Exception` and not
`except ImportError`, because the documented Linux failure is `libEGL.so.1`
raised from inside the extension module. A module reaching Qt through
`app.config` or `app.help` needs its **`app.*` import** guarded too — a decorator
cannot save a module that never loads — and `tests/test_qt_absent_degrades.py`
sweeps every `tests/test_*.py` with `PySide6` blocked, so the eighth module to do
it fails there rather than erroring on somebody's clone.

## A SKIP IS HOW COVERAGE EVAPORATES UNDER A GREEN TICK

The audit tests skip when PyDRC is missing, so a run without it goes green having
exercised none of the design-rule code. `tools/run_tests.py` prints the library's
status first, **groups every skip by its stated reason**, and ends with a loud
banner per reason naming how many tests it covered. **Build each banner from its
own gap**, or a fix that rewrites the cause on all of them makes 54 Qt skips read
*"the design rule library could not be imported"* — about the wrong thing.

## Each test module runs in its own process

Not fussiness. One process accumulates Qt GUI resources across the many
window-creating tests and **hard-crashes a late module on the headless Windows
runner**, while every module passes alone. Isolation bounds resource use and
names the module that failed instead of a bare crash in the log. The runner sets
`QT_QPA_PLATFORM=offscreen` itself; Qt's Linux system libraries are a further
prerequisite (`CI.md`), and without them a third of the suite skips.

## An open PyMuPDF handle is a Windows file lock, and Linux cannot see it

A `fitz.Document` left open holds the file: on Windows `os.remove` raises
`WinError 32` and a save onto that path raises *"cannot remove file … Permission
denied"* from inside PyMuPDF, and on Linux both succeed — so a test that leaks a
handle is **green locally and red only on `windows-latest`**. The app has always
been careful; it is **test** code that forgets. Assert the CAUSE rather than
waiting for CI to meet the effect: `assertNoOpenHandle(path)` walks the fixture's
own documents and fails when one is still open on that path.

## A release names the rules it ships

An installer that cannot say which rules it contains is one nobody can reproduce.
`packaging/pydrc-ref.txt` names the PyDRC ref, whatever it names is **resolved to
a commit SHA** before installing, and that SHA lands in the build log and the
release notes — so a branch cannot move underneath a build and two runs of one
tag cannot quietly differ. Cutting a release is three steps **in this order**:
tag PyDRC; set `packaging/pydrc-ref.txt` to that tag here and commit it; tag the
app. Tagging the app before step 2 produces a release whose notes name a moving
branch, which is the one thing the pin exists to prevent.

The version is declared in **three** places — `app/__init__.py`,
`packaging/installer.iss` and a `CHANGELOG.md` section — and
`tests/test_requirements.py::TestVersionIsStatedOnce` fails when they disagree.
This line once said "declared once", which is the claim that gate disproves.

## Where a dialog lives, and what the layout gate asserts

**A dialog lives beside the subject it serves** — `app/tools/dialogs.py` for the
page operations, `app/settings_dialog.py`, `app/dialogs.py`. The four that
accreted in `main_window.py` had no subject package to go to — the one location
the convention does not name.

`tests/test_module_layout.py` asserts a **kind** of thing rather than a line
count, which is a snapshot: the window defines no dialog class (read by BASE, so
`_ToolDialog`'s seven subclasses are in range), imports no printing library at
**any** scope (all nine printing methods imported `QtPrintSupport` or `fitz`
*inside themselves*, so a top-level scan would have called the window
printer-free), imports no widget class, and no longer constructs a `Document`.
Each has a floor, because an absence assertion agrees with an empty checkout.
`app/menus.py` names fifteen `win.<handler>` and cannot see the class, so a
renamed method would fail **when somebody clicks it**; the sweep requires
`MainWindow` to have each one.

## Documents are held to the code, never to each other

Where a fact is already decided somewhere — by a dialog's own `addTab` calls, by
a directory listing, by `requirements.txt` — a hand-kept description of it is a
copy that drifts, so the gate asks the deciding thing. **`app/help.py`'s
`load_vault` globs `docs/*.md` NON-RECURSIVELY**, so `docs/*.md` is the user
manual and `docs/history/` and `docs/records/` are not help pages — asked of the
**function**, never of the glob's spelling, because the comment above that line
names the call a source scan would hunt. `docs/` ships recursively in
`packaging/DSI_Redline.spec`, so anything added under it lands in the installer.
**A corrected claim is retracted in place and quoted**, so a sweep must strip
quoted text and a companion assertion must confirm the quotation is still there,
or the carve-out is untested.

## The records

A closed defect narrative is a **record**, not an instruction, and it does not
belong in a file loaded on every turn. Each is dated, keeps its measurements, and
is worth reading before re-opening the subject it covers.

| record | read it before |
|---|---|
| `docs/records/never-overwriting-the-original.md` | touching a writer in `app/tools/pdf_ops.py`, or the storage refusals |
| `docs/records/qt-degradation.md` | adding an import to a test module, or writing a POSIX path into `tests/` |
| `docs/records/the-god-object-split.md` | adding anything to `main_window.py`, or moving code out of it |
| `docs/records/documents-that-drifted.md` | writing a claim into `README.md`, `docs/` or a packaging file |
| `docs/records/the-account-the-pin-and-the-shell.md` | touching `requirements-drc.txt`, `packaging/pydrc-ref.txt`, or a workflow's bash |
| `docs/records/interpreters-and-action-majors.md` | changing `requires-python`, the CI matrix, or an action pin |
| `docs/records/the-suite-discovers-itself.md` | adding a test class, or an `if __name__` block |
| `docs/records/the-test-count.md` | writing a test count into any document |
| `docs/records/the-claude-md-split.md` | moving material between `CLAUDE.md` and a record, or touching the budget gate |

`tests/test_documents_are_measured.py` gates the every-turn context this file
costs and resolves that table against `docs/records/` in both directions, so a
record cannot be quietly dropped and this file cannot quietly grow back.
