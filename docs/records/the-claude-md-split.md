# The CLAUDE.md split, and the gate that keeps it split

Written 2026-09-22. A closed defect narrative is a **record**, not an
instruction: it keeps its measurements and its dates, and nothing here is loaded
on every turn. The standing rule it produced stays in `CLAUDE.md`.

`CLAUDE.md` was **1,088 lines** and every session paid for all of it, whether or
not it opened a PDF writer, a workflow or a dialog. Eight closed narratives came
out into `docs/records/`; the standing rule each had produced stayed. **166 lines
now, 199 loaded against a ceiling of 200.**

## The ceiling is on what is LOADED, and the floor is on `CLAUDE.md` alone

Capping `CLAUDE.md` *and* the loaded total makes the first unreachable by
construction, because the total is the larger number. What a turn costs is
`CLAUDE.md` plus every **unscoped** `.claude/rules/*.md` — a rule carrying
`paths:` in its first five lines loads only when its files are opened — so moving
a section into an unscoped rule file buys nothing, which is the point.

`house-voice.md` is exempt, granted by the owner rather than by this repository:
portfolio-wide, installed from Pathforward's kit byte for byte. **`gates.md` is
not**, deliberately — 32 lines from that same kit, and part of what a turn costs.

The floor is on `CLAUDE.md` alone at 60 lines, because **a file cut to nothing
satisfies a ceiling perfectly**. And the message names three numbers rather than
two: `CLAUDE.md`, each counted rule with its own line count, and the exempt ones
separately — "loaded 210" does not say which file to cut.

## The carve was proved lossless BEFORE anything was written

Twelve spans — four kept, eight carved — asserted to tile lines 1–1,088 with no
gap and no overlap, and their concatenation compared byte-for-byte against the
original. A carve that silently ate a paragraph is invisible in the diff of a
1,088-line file, and the eight records are 993 lines between them.

## Two passages were cut because `gates.md` already says them

Both were duplication of a file loaded on **every** turn, so removing them
shortened `CLAUDE.md` and removed a second copy at once:

- the `--require-drc`-read-through-a-pipe bullet, against gates.md's *"a
  pipeline's exit status is the last command's … Measure an exit code without a
  pipe"*;
- *"every sweep needs a floor"*, against *"An empty sweep is refused, never
  reported clean"*.

## `docs/records/` is safe here on two MEASURED facts, not by analogy

- **`app/help.py`'s `load_vault` globs `docs/*.md` non-recursively**, so a record
  is never published as an in-app help page — and the existing gate that plants
  `docs/history/V9.9.9_TEST_PLAN.md` tests the **function** with a temp directory
  rather than the glob's spelling, so it already covers `history/` and
  `records/` at once.
- **`packaging/DSI_Redline.spec:27` is `(os.path.join(ROOT, "docs"), "docs")`**,
  and a PyInstaller `datas` directory source copies recursively — so `docs/`
  already ships whole in every installer, `docs/history/` included. The records
  grow it; that is a pre-existing condition rather than a new one, and
  `CLAUDE.md` states it as a standing rule.

## The gate, and the thirteen arms

`tests/test_documents_are_measured.py`. The records table is resolved against
`docs/records/` in **both** directions: a row naming a missing file sends a
reader nowhere, and a record the table does not name is written, kept and
unreachable. `_REL` is derived from `RECORDS` so the directory and the regex that
reads the table cannot part company, and `_lines()` subtracts the trailing
newline so a hand `wc -l` agrees with the gate.

Falsified thirteen ways. Eleven fire on their own arm: 40 lines appended to
`CLAUDE.md`; `CLAUDE.md` cut under the floor; `EXEMPT` renamed to a rule file
that is gone; a record deleted with its row standing; a record kept with its row
dropped; the whole table removed; `RECORDS` pointed at a directory that is not
there; a 61-line unscoped rule planted; and `EXEMPT` gaining an entry for a file
that is not there.

**Two are a labelled pair each, and they are the evidence rather than four dead
gates.** Exempting `gates.md`, and `_scoped()` answering `True` for everything,
both *loosen* the ceiling — so on a correct tree neither can fire, and each is
paired with the regrowth arm it would otherwise hide. Alone: DEAD. With the
regrowth: FIRES.

## The loop's own reading missed every subtest failure

`EXEMPT` renamed to a gone file fired **two** tests and the loop named one. A
`subTest` failure is reported on an **indented continuation line** carrying
`(name=…)`, and the anchor required the test name at column 0 — so the verdict
was sound (the ceiling fired on the same arm) and the names column was wrong.

That is why arm 9 exists: adding a *second* bogus `EXEMPT` entry keeps
`house-voice.md` exempt, so the ceiling stays satisfied and
`test_every_exemption_still_names_a_file_that_exists` is the only thing that can
speak. **An arm that fires through a neighbour says nothing about the check it
was written for.**
