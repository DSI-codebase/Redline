# Three documents that described something other than the code

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

## Three documents that described something other than the code

Each was true when written and read by nobody since. They are together because
the answer is the same in all three: **where a fact is already decided
somewhere, a hand-kept description of it is a copy that drifts**, so the fix is
a gate that asks the deciding thing rather than a better sentence.

### A shipped-release document must not become a help page

`app/help.py`'s `load_vault` reads `folder.glob("*.md")` — non-recursive — so
`docs/*.md` is the user manual and the write-once records in `docs/history/`
do not reach it. **That invariant was stated in `docs/history/README.md` and
enforced by nothing**, and it fails quietly two ways:

- the glob going recursive publishes **seven test plans and feature summaries
  as help pages in one edit**, and every existing assertion in `test_help.py`
  still passes, because they are all about pages that *are* present;
- a record moved up into `docs/` is invisible to any check about
  `docs/history/`, because by then it is no longer in it.

So the first is asked of the **function** — a temp directory with a
subdirectory in it — never of the glob's spelling, because the comment above
that line names the very call a source scan would be hunting for. The second
is asked of the **directory's own manifest**, which is the only thing that
knows what belongs there. Both carry a floor: an empty vault satisfies *"no
history page is in it"* perfectly.

Falsified three ways, each on its own arm: `glob` → `rglob` (2 fail),
`git mv docs/history/V1.3.0_FEATURES.md docs/` (the manifest test, and
**pointedly not** the absence test — which is the design), and the manifest
table emptied.

**And the manifest check was scoped to the page before it was scoped to the
table.** Swept whole, the README also names `docs/*.md` and the five living
documents at the repository root, so it reported six phantom absences on its
first run. Table rows only, and a name carrying a separator or a glob is prose
about a path rather than a file in that directory.

### `docs/Settings.md` named four tabs where the dialog builds five

No section for **Component labels** or **Design rules** — so the family-code
list, the per-rule enable, the severity override and the ODA converter path
were undocumented in the one page a user opens to find out what a setting
does. The page is organised by tab now, one `##` per tab.

- **The tab names are read off the RUNNING dialog**, never off a second
  reading of `app/main_window.py`. `tests/test_settings_layout.py` already
  builds the real `SettingsDialog`, so the gate asks it: the document
  describes what a person sees, and a source scan would form its own opinion
  about which `addTab` calls run.
- **Order as well as membership**, because a manual whose sections are in a
  different order from the tabs is a manual you cannot read alongside the
  dialog.
- **A heading is cheap, so the content is gated too** — the six controls that
  had no mention anywhere are asserted by name. Falsified three ways: the old
  four-tab page restored (2 fail), a tab dropped from the dialog, and the
  sections reordered.

### The reproducibility claim, and the one pin behind it

`packaging/pydrc-ref.txt` ended *"...and rebuilding that tag years later
produces the same installer"*. **It pins one dependency of ten.** Measured:
nine unbounded floors in `requirements.txt` — the PDF engine and the whole GUI
toolkit among them — and a tenth in `packaging/requirements-build.txt`, so a
rebuild resolves each to whatever is newest that day.

The rule library really is pinned and resolved to a SHA before it is
installed, which makes *"which rules does this installer contain"* answerable
— the question that file exists for, and the one a design-rule finding turns
on. What it cannot carry is a claim about the **artifact**, and that is who it
costs: somebody reproducing a finding from a year-old release reads the
sentence and stops looking.

- **Corrected rather than pinned, and the limit is stated.** A lock file for
  the other ten is the fix for the artifact, and it cannot be produced or
  verified from this container — the build is Windows-only.
- **Gated in BOTH directions**: the strong sentence is refused while a floor
  remains, and the narrow one is refused the day they are all pinned, because
  a file underselling a guarantee the build now gives is the same drift
  pointing the other way — and it is the one a person adding a lock file has
  no reason to come back and fix.
- **THE GATE FIRED ON ITS OWN CORRECTION.** The retraction quotes the sentence
  it retracts, deliberately, because the history is what stops it being
  written back. The standing answer here is to tighten the check and never
  waive the text explaining the defect, so what is refused is the sentence
  made **as a claim** — outside quotation marks — with a companion test
  asserting the quotation is still there, or the carve-out passes over a file
  that simply never mentions the subject.
- Falsified five ways, each on its own arm: the strong claim restored, every
  requirement pinned with the narrow claim left standing, the scope sentence
  deleted, the quotation removed, and the ref swallowed by the comment block.

### ...and the suite runs in full in this container now

`CLAUDE.md` has said *"no interpreter in this container has PySide6"* since the
interpreter matrix landed. `pip install PySide6` and `pip install -r
requirements.txt` both succeed here — measured, **735 tests across 57 modules,
28 skipped**, every module passing, with the only skips being PyDRC (private)
and `ezdxf`. So a Qt change no longer has to be shipped on a reading.

What that does **not** cover is unchanged: only 3.11 is installed, so the 3.12
and 3.13 legs are still CI's to verify, and nothing here builds the Windows
installer.
