# Continuous integration

Two workflows, both under `.github/workflows/`.

| Workflow | Runs on | Does |
|---|---|---|
| **Tests** (`tests.yml`) | every push, every pull request | the suite, on Ubuntu and Windows, and once more on Ubuntu at the PyMuPDF floor |
| **Build Windows** (`build-windows.yml`) | manual dispatch, `v*` tags | the suite, then the portable app, the installer, and the release |

## Running the suite

```
python tools/run_tests.py          # everything
python tools/run_tests.py -v       # everything, verbose
python tools/run_tests.py tests.test_audit
```

On Linux the runner needs Qt's system libraries, which a bare Ubuntu box does
not have — without them `import PySide6.QtGui` fails with
`libEGL.so.1: cannot open shared object file` and about a third of the suite
turns into skips. The Tests workflow installs them; locally, the short list is
`libegl1 libgl1 libglib2.0-0 libdbus-1-3 libxkbcommon-x11-0 libxcb-cursor0`
plus the other `libxcb-*` packages named in the workflow.

Each test module runs in **its own process**. This is not fussiness: running
the whole suite in one process accumulates Qt GUI resources from the many
window-creating tests and hard-crashes a late module on the headless Windows
runner, even though every module passes on its own. Per-module isolation keeps
resource use bounded and names the module that failed instead of leaving a bare
crash in the log.

Qt also needs a display. The runner sets `QT_QPA_PLATFORM=offscreen` itself, so
there is nothing to remember locally.

## The PyMuPDF floor is run, not just declared

A fresh install takes the newest PyMuPDF, so the matrix never meets the floor
`requirements.txt` declares. That floor said 1.25 while two tests failed there
(measured 2026-10-31), and no runner noticed. The **`pymupdf-floor`** job
installs `requirements.txt` with `PyMuPDF==$PYMUPDF_FLOOR` as a pip constraint,
checks that the installed PyMuPDF is that version, and runs the suite on Ubuntu
and Python 3.11, with the rule library when the token is present.

To move the floor to version X:

1. Write `PyMuPDF==X` into a file, `floor.txt` here.
2. In a new virtual environment, run
   `pip install -r requirements.txt -c floor.txt`.
3. Run `python tools/run_tests.py` and confirm it reports no failed module.
4. Change the `PyMuPDF>=` line in `requirements.txt` and `PYMUPDF_FLOOR` in
   `tests.yml` in the same commit.

`tests/test_requirements.py::TestThePyMuPDFFloorIsExercised` fails when the two
disagree.

## The design rule library is optional, and CI says so

Design rule checking lives in [PyDRC](https://github.com/DSI-codebase/PyDRC), a
separate library. It is **not** in `requirements.txt`, because that repository
is private and a plain `pip install -r requirements.txt` would fail for anyone
without credentials — including every CI runner. It lives in
`requirements-drc.txt` instead:

```
pip install -r requirements.txt        # the app
pip install -r requirements-drc.txt    # ...and design rule checking
```

Without it the app still runs and the Audit tab reports the library as
unavailable, which is the same graceful path the AI extraction takes when the
Anthropic SDK is absent.

In CI that creates a trap worth naming: the audit tests are written to **skip**
when the library is missing, so a run without it goes green having never
exercised any of the design rule code. The runner therefore prints the library's
status at the top, groups every skip by its stated reason, and ends with a loud
banner naming how many tests were skipped for that reason. A green tick that
checked nothing must not look like a green tick that checked everything — the
same rule the audit itself follows about coverage.

Qt gets the same treatment, with one difference: the workflows install it, so a
Qt skip means a broken runner rather than a choice. `--strict`, which both
workflows pass, turns those skips into a failed run.

A reason that names both, such as `needs PySide6 and PyDRC`, counts against
whichever the runner measures missing, and against both when both are. The
runner asks `app.audit` about PyDRC, the check those tests skip on, and
`tests/_qt.py` about Qt, so a missing ezdxf does not take them. Whenever Qt
loads, such a skip counts against the rule library, so a run whose Qt works
cannot fail `--strict` on it. No banner says a library is absent when it
imports.

### Giving CI access to it

Both workflows install the library when a `PYDRC_TOKEN` secret exists, and skip
it (loudly) when it does not. To set it up:

1. Create a fine-grained personal access token with **Contents: read-only** on
   `DSI-codebase/PyDRC`.
2. In `DSI-codebase/Redline` (the repository moved accounts and was
   recreated rather than transferred, so nothing under the old account
   redirects -- not a clone and not a settings page), go to
   **Settings ▸ Secrets and variables ▸
   Actions ▸ New repository secret**.
3. Name it `PYDRC_TOKEN` and paste the token.

Making PyDRC public would work equally well and needs no secret; the split
between the two requirements files is still worth keeping either way, so the
app's own dependencies never depend on a sibling project being reachable.

Note that secrets are not exposed to pull requests from forks, so a fork's PR
will always run in the skip-and-say-so mode.

## Releases

Push a `v*` tag, or run **Build Windows** manually. On a tag it also publishes a
GitHub Release with the installer and the portable zip attached. A release built
without `PYDRC_TOKEN` ships without design rule checking; the workflow logs a
warning saying so rather than producing a quietly reduced build.

### Which rules a release contains

An installer that cannot say which rules it ships is one nobody can reproduce.
`packaging/pydrc-ref.txt` names the PyDRC ref the build installs — a branch, a
tag, or a commit SHA. Whatever it names is resolved to a **commit SHA** and that
SHA is what gets installed, so a branch cannot move underneath a build in
progress and two runs of one tag cannot quietly differ. The build log prints the
library version, each rule pack the app runs when Settings names none (asked of
the app's `default_packs()`, so the line follows PyDRC's default), and the
commit; the release notes carry the same line.

The file sits at `main` during development so the app tracks the rule library.
Cutting a release is therefore three steps in this order:

1. Tag PyDRC (`v0.2.0`).
2. In this repository, set `packaging/pydrc-ref.txt` to that tag and commit it.
3. Tag the app (`v1.5.0`).

Tagging the app before step 2 produces a release whose notes name a moving
branch, which is the one thing the pin exists to prevent. **Build Windows** also
takes a `pydrc_ref` input when run manually, which overrides the file for that
one run — useful for testing a rule change against the app without committing a
pin.

The provenance line lands in the release notes whether the tag is pushed to a
repository with no release yet or the release is drafted in the GitHub UI first
and the tag pushed after. The second path is the common one and it is how
`v1.5.0` shipped with an empty body: the workflow only wrote notes when it
created the release itself. It now fills in the line either way, appending to
whatever a human wrote rather than replacing it.
