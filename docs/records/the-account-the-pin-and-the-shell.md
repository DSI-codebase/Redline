# The account in a git URL, the pin that named a tag, and the bash that was WSL

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

## The rule library is installed from git, and that URL names an account

`requirements-drc.txt` is `pip install git+…/<account>/PyDRC@<ref>`, and the two
workflows spelled the account out again in their own `pip install` lines. The
portfolio moves to a company account as **fresh repositories built from
`main`** — a rename leaves a redirect `pip` follows through git, and a recreated
repository leaves none.

**What that costs here is measured rather than guessed at, and it is not a red
build.** `pip install -r requirements-drc.txt` failing is loud; what follows is
the failure this repository already refuses everywhere: the audit tests
**skip**, `--require-drc` is what turns that into a red run, and the CI job only
passes the flag *"whenever the PyDRC token is present"*. So a stale account plus
a missing secret is a green run with the whole design-rule half unexercised —
the shape `tools/run_tests.py`'s banners exist for, arriving through the one
door they do not watch.

- **The two workflow copies are DERIVED and the requirement is GATED**, and the
  split is the standing one: a workflow step runs in this repository's own
  Actions, so `${{ github.repository_owner }}` is the owner it needs; a
  `requirements` line has no expression to derive one with at all, so it stays a
  literal with a gate that compares it against **this checkout's own remote**
  and goes red on the day it stops matching.
- **THE ORACLE IS GIT, never the other declaration.** Comparing the requirement
  against a second copy of itself says only that the two agree, which they would
  while both were stale together.
- **`test_the_gate_can_actually_fire`** exists because on a correct tree every
  URL matches and a comparison that answered a constant would be
  indistinguishable from one that works — the dead gate a sibling repository's
  copy of this check was measured to be.
- **The pin itself is untouched.** `packaging/pydrc-ref.txt` names a *ref* and
  is resolved to a SHA before installing; a ref is not an account and the move
  does not touch it.

The portfolio-wide sweep is Pathforward's `scripts/transfer_readiness.py`, which
classifies this repository at **1 gated** — the requirement line, with this test
named as what keeps it correct.

### ...and the pin was NOT untouched, because a fresh repository has no tags

The bullet above ends *"**The pin itself is untouched.** `packaging/pydrc-ref.txt`
names a *ref* and is resolved to a SHA before installing; a ref is not an
account and the move does not touch it."* The first clause is right and the
conclusion does not follow. **A ref is not an account and the move deletes the
thing it names**: the repositories are created fresh from `main` — `rm -rf .git`
and one `Import` commit — so no tag, no history and no release travels, and
`packaging/pydrc-ref.txt` names **`v0.2.0`**, one of PyDRC's two tags.

**How that fails is the finding, not that it fails.** `git ls-remote` **exits 0
when it matches nothing** — measured — so an empty answer was the only signal
that a ref is absent, and the fallback below it read that signal as *"then it
must be a commit SHA"*. Simulated with the tag gone, the log reads

    PyDRC resolved to: v0.2.0

which is a line saying the resolution succeeded, and pip then fails about
something else. A fallback written for a legitimate SHA turning *this ref is
gone* into *assume it is a SHA* is the does-it-fail-or-stop-finding shape this
file records everywhere else, and the cost is a build that reports the wrong
cause on the one day the account moves.

- **The discriminator is the ref's own SHAPE**, which is all that is available:
  hex, and at least seven characters. The false positive is stated because it
  is real and small — a *branch* named in hex and seven characters or longer
  (`deadbeef`) that is **absent** reads as a SHA and reaches pip, which fails on
  its own terms. One that resolves never reaches the test at all.
- **AND THE EMPTY-REF REFUSAL FIVE LINES ABOVE IT COULD NEVER PRINT.**
  `set -euo pipefail` plus a `grep` that matches nothing kills the script at the
  read, so a ref file that is empty, all comments or all whitespace exited **1
  with no output at all** — measured. The safe half was never in doubt (it does
  not reach the install); what was missing is the sentence, in a block whose own
  five-line comment exists to supply it. `|| true` on the read, and the refusal
  runs.
- **The pin is deliberately NOT changed here.** Editing it changes which rules
  the installer contains, which is the question that file exists to answer, so
  it is a move-day edit recorded in Pathforward's runbook rather than a silent
  one now.
- **AND MOVE DAY CAME: the pin is `main` as of 2026-09-20.** That bullet said
  *"it is a move-day edit recorded in Pathforward's runbook rather than a silent
  one now"*, which is what happened rather than something that was avoided.
  Measured on the new account: `git ls-remote
  https://github.com/DSI-codebase/PyDRC v0.2.0` returns an empty listing and
  exits 0, and `main` resolves to `09dbb19`. **`main` is the convention rather
  than a fallback** — `packaging/pydrc-ref.txt`'s own opening paragraph has
  always read *"`main` while developing … set it to a PyDRC tag before tagging
  a release"* — so what the move cost is not the pin, it is that **step 1 of the
  three-step release ordering no longer has a tag to reuse**: PyDRC's two tags
  were left behind with its history, and the next app release needs one cut in
  the new account before step 2 has anything to name.

**Two checks, because one cannot run everywhere.** `tests/test_drc_ref_resolution.py`
asserts the structure on any platform — the shape test exists, the not-a-SHA arm
exits 1, the ref is taken verbatim in exactly one place and only downstream of
that test, and the read still carries `|| true` — and **executes the step's real
`run:` block** where a bash that can run one is found, saying so where none is.
`git` and `pip` are shell **functions** prepended to the script rather than stub
files on PATH: a function needs no directory, no execute bit and no PATH edit,
so the harness runs the same under Git bash on `windows-latest`, which is the
runner this repository has been bitten by twice.

*(That paragraph read* "**executes the step's real `run:` block** where `bash`
is on PATH, saying so where it is not" *until 2026-09-12, and the section below
is what `windows-latest` said about it. The function-not-a-stub half is intact
and is what made the fix one line of resolution rather than a rewrite.)*

Falsified four ways, each on its own arm: the old fallback restored (7 tests,
including the log line claiming a resolution that did not happen), the length
floor dropped, the hex test dropped, and the `|| true` removed. **The third
fired nothing until a case existed for it** — every other ref in the module is
either hex or under seven characters, so dropping the hex half alone left all
thirteen green. *A shape test with two halves needs a case each half does not
answer*, and only injecting said which.

Verified in both directions, which is the only way to tell a fix from a
withdrawal: **758 tests across 59 modules, 345 skipped** before, **771 across
60, 345 skipped** after — the +13 is this module, and the skip reasons are
identical line for line.

### ...and `shutil.which("bash")` found WSL, so three tests passed on a shell that refuses everything

The paragraph above said the harness *"runs the same under Git bash on
`windows-latest`"*. It did not, and all three Windows legs went red saying so:
`Ran 13 tests ... FAILED (failures=8)`, every message quoting

    Windows Subsystem for Linux has no installed distributions.

**`shutil.which("bash")` on that runner finds `C:\Windows\System32\bash.exe`**
— the WSL launcher, present on every Windows image and useless without a
distribution installed. It answers *every* invocation with that sentence, in
UTF-16LE, and exits 1. So the class was not skipped, `_drive` returned
`(1, <that message>)` every time, and the harness was measuring the shell.

- **THREE OF THE NINE BEHAVIOURAL TESTS PASSED ON IT, and they are the
  dangerous half.** A bash that refuses everything satisfies any test whose
  whole claim is that the step refused —
  `test_a_branch_that_is_NOT_on_the_remote_refuses`,
  `test_a_short_hex_ref_is_not_long_enough_to_be_a_sha` and
  `test_a_long_ref_that_is_not_hex_is_not_a_sha_either`, each asserting
  `rc == 1` and no `PIP-CALLED` and nothing else. Eight failures are loud;
  three silent passes over a subject that never ran are what this repository
  is written against.
- **Found on the runner, not by reading**, which is this file's own recorded
  shape for the fourth time: green on Linux by construction, because
  `/bin/bash` is a bash. The same class as the leaked PyMuPDF handle and the
  `/dev/null` stream — a Windows-only failure the local suite cannot reach.
- **The fix is a PROBE, not a longer PATH.** `_usable_bash()` runs
  `bash -c "echo <marker>"` on each candidate and takes the first that exits 0
  **and prints the marker**. The marker is the load-bearing half: a shell that
  exits 0 and produces nothing is equally unusable, and reading the exit code
  alone is the same is-it-there-or-does-it-work confusion one level down.
- **Git bash is tried FIRST because it is the shell the workflow runs**, not
  as a fallback. Actions maps `shell: bash` to
  `C:\Program Files\Git\bin\bash.exe` on `windows-latest`, so the order is
  what makes this harness drive the same interpreter the step does.
- **And `_drive` now asserts the script RAN.** Every path through the step
  prints one of two lines — `PyDRC ref requested:` on any non-empty ref,
  `::error::` on the empty one — so output carrying neither means the shell
  never reached the script whatever it returned. That is the assertion the
  three vacuous passes were missing, and it costs nothing on a working shell.

**The floor is what turns eight confusing failures into eleven named ones**,
and that is measured rather than argued. Reproducing the runner's shape here —
a `bash` on PATH that prints a UTF-16LE complaint and exits 1:

| | failures | what a reader sees |
|---|---|---|
| floor removed | **8** | the CI board, with three tests still green |
| floor kept | **11** | every behavioural test fails, each naming the shell |

Falsified five ways, each on its own arm: the probe made permissive (2 tests —
both fakes accepted), the probe reading the **exit code alone** (1 — which is
what says the marker is load-bearing rather than belt-and-braces), Git bash no
longer tried first, and the two rows above.

**No Windows runner is reachable from here**, so what the new class asserts is
not a claim about Windows — it is that the probe rejects a shell *of the shape
`windows-latest` supplies*, driven against a constructed one. **The fake is
platform-shaped, and that is the same defect one level down**: a `#!/bin/sh`
script is not launchable on Windows, so a single POSIX fake would be rejected
by the `OSError` arm rather than by the probe — a pass on the one platform this
exists for, arriving by exactly the mechanism being fixed. Each arm asserts the
fake really is launchable before asserting anything about the probe.

*(And an arm did not apply, which the exactly-once anchor assertion caught
rather than reporting as a dead gate: the injection's search string was written
`"…\\Git\\bin\\bash.exe"` in a non-raw Python string, where `\b` is a
**backspace**. `\bin` is a real escape and `\Program` is not, so one of the
two path separators silently became a control character. Raw strings for any
anchor holding a Windows path.)*

**775 tests across 60 modules, 345 skipped** — the +4 is the probe's own class,
and the skip reasons are identical line for line.

### ...and the first tag build blamed the tag, because the checkout's own token answered for PyDRC

2026-09-27. The first **Build Windows** run in this repository — the `v1.6.0`
tag, run `36349198718` — failed in the resolve step with

    remote: Repository not found.
    fatal: repository 'https://github.com/DSI-codebase/PyDRC/' not found
    ::error::packaging/pydrc-ref.txt names 'v0.2.1', which is neither a branch or tag on DSI-codebase/PyDRC nor a commit SHA. …

The tag was there: `v0.2.1` on `09dbb19`, listed by the GitHub API that day.
The secret was there too: **Tests** on the same commit, `cafb58b`, installed
`pydrc[dxf]` from the same repository with the same `PYDRC_TOKEN` a day earlier
and passed with `--require-drc` on all six legs (run `36245807615`). Two defects,
and the second is why the first read as a missing tag.

- **`actions/checkout` persists the `GITHUB_TOKEN` in the checkout's git
  config**, as `http.https://github.com/.extraheader` — an `AUTHORIZATION`
  header, and the job's post-cleanup log unsets exactly that key. That token can
  read this repository and no other. `git ls-remote` runs inside the checkout,
  reads the local config and sends the header; GitHub authenticates it, finds no
  PyDRC it may show, and answers 404 — so git never offers the `PYDRC_TOKEN`
  written into the URL. `pip`'s `git clone` does not read the checkout's config,
  which is why `tests.yml`, whose only git call is pip's, never saw this.
  **Measured** against a local server standing in for GitHub (the scoped header
  gets a 404, no auth gets a 401 challenge, the PyDRC credential gets a
  listing): inside a repository carrying the header, the server saw
  `GITHUB_TOKEN` first and git exited 128; outside it, the server saw no auth,
  challenged, then saw `PYDRC_TOKEN`, and the tag was listed; inside with
  `-c http.<url>.extraheader=`, the same listing.
- **The listing read `|| true`**, so exit 128 arrived as the empty answer a
  missing ref gives, and the refusal written for a tag lost in the account move
  fired — the same sentence, on the day that did not happen. Unreachable is its
  own state: the step now keeps git's exit status and stops on it, naming the
  repository and saying the ref was never looked up, before anything reads the
  answer as "not there". A SHA-shaped ref stops too: the SHA fallback is for a
  ref git cannot *list*, and pip would fail on the same credential later.

The fix is `persist-credentials: false` on the build's checkout. Nothing in that
job pushes, and the release step takes `GH_TOKEN` from its own env. Gated in
`tests/test_drc_ref_resolution.py`: a structural check that every
`actions/checkout` in `build-windows.yml` sets it (with a floor, so a renamed
action cannot pass over nothing), a structural check that the one listing keeps
its exit status and tests it before the SHA arm, and two behavioral tests
driving the step with a stub `git ls-remote` that exits 128.

Falsified four ways, each on its own arm: the original `|| true` listing
restored (3 tests), the exit status kept but never tested (the same 3),
`persist-credentials` removed (1), and set to `true` (1). **The harness stubs
git, so no behavioral test can see the header** — the structural check on the
checkout is the only gate on the cause, and the local server above is the only
measurement of it.

**909 tests across 65 modules, 0 skipped**, under `--strict --require-drc` with
PyDRC 0.2.1 installed — 905 at `c0a2ad6`, and the +4 is this section's.
