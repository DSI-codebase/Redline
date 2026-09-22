# "Python 3.11+" was a claim to contributors, and only 3.11 ran

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

## "Python 3.11+" was a claim to contributors, and only 3.11 ran

`CONTRIBUTING.md` and `README.md` both say it. The CI matrix varied only the
operating system and pinned `python-version: "3.11"` on both runners, so **3.12
and 3.13 — increasingly the default on a fresh machine — were advertised and
never checked.**

The frozen Windows build pins its own interpreter, so a shipped installer is
unaffected. What this is about is **running from source**, which the README
documents as a first-class way to use the app, against a suite that heavily
exercises PySide6 and PyMuPDF. `build-windows.yml` therefore stays pinned, and
**the reason is written into the file** — an asymmetry with no stated reason
reads as the oversight the test matrix just corrected, and somebody eventually
"fixes" it.

**And both workflows pinned Node-20 action majors.** Every run ended with
*"Node.js 20 is deprecated. The following actions … are being forced to run on
Node.js 24."* The forcing is GitHub's temporary accommodation; when it ends, a
workflow pinned to those majors stops working — and here that is the Windows
build, **the only path that produces the installer**. Bumped to `checkout@v5`,
`setup-python@v6`, `upload-artifact@v5`.

`tests/test_requirements.py::TestTheInterpreterClaimIsExercised` reads the
minimum out of the documents and asserts the matrix covers it *and* names more
than one version, asserts the frozen build stays pinned *with* its reason, and
sweeps both workflows for an action major below its minimum. Comments are
stripped first — the comment explaining this defect necessarily names the
versions the check is hunting, which is the dead gate this repo already paid
for once with `--require-drc`.

### ...and that action sweep was a LIST OF PAST INJURIES before it was a rule

Its first version compared each `uses:` ref against a set of the three that
were stale the day it was written — `checkout@v4`, `setup-python@v5`,
`upload-artifact@v4`. **A gate built from what went wrong last time only ever
catches last time**, and the blindness was measured rather than argued:

| pinned ref | the set | the minimum-major rule |
|---|---|---|
| `actions/checkout@v4` | CAUGHT | `STALE` |
| `actions/checkout@v2` | passed | `STALE` |
| `actions/setup-node@v4` | passed | `STALE` |
| `actions/upload-artifact@v3` | passed | `STALE` |
| `actions/labeler@v9` | passed | `UNDESCRIBED` |
| `actions/checkout@v5` | passed | ok |

One of six caught, and **four genuinely bad pins passed**. `MINIMUM_ACTION_MAJOR`
is the table now, and the two failure kinds are separate on purpose:
`UNDESCRIBED` — a first-party `actions/*` with no minimum recorded — is a
**failure, not a pass**, because a set-membership check answers *"is this one
of the three known-stale refs"*, says no, and lets an unjudged action through.
Third-party actions are left unjudged with the reason stated (nothing here can
know which major of somebody else's action runs on a current runtime), and a
SHA pin is left alone because pinning a commit is the stronger choice.

**And the sweep could pass over nothing.** The glob was `*.yml` only, so a
workflow saved as `.yaml` — or a directory rename — returns no pins and
therefore no offenders, which is a green tick over a sweep of nothing. Both
spellings are globbed and a floor assertion refuses an empty result. Falsified
five ways: each of the four rows above that the old set missed, plus the glob
pointed at an extension nothing uses.

**Scope is this repository, deliberately.** The same defect was portfolio-wide
— ten of fourteen repos on 2026-08-30, every one of them green — and no single
repo's CI can see that, so the cross-repo sweep lives in Pathforward
(`scripts/action_majors.py`) rather than as eleven copies of this.

**What is NOT verified here**: no interpreter in this container has PySide6, so
3.12 and 3.13 could not be exercised locally. CI is the verification, and
`fail-fast: false` was already set, so a failure on the new legs cannot mask the
3.11 result. Say which of the two you did.
