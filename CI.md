# Continuous integration

Two workflows, both under `.github/workflows/`.

| Workflow | Runs on | Does |
|---|---|---|
| **Tests** (`tests.yml`) | every push, every pull request | the suite, on Ubuntu and Windows |
| **Build Windows** (`build-windows.yml`) | manual dispatch, `v*` tags | the suite, then the portable app, a launch of it, a check of the notices against it, the installer, and the release |

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

### The built app is started before it is packaged

The suite runs from source, and a source install is not the bundle. v1.8.0
passed the suite and stopped on launch: PyMuPDF 2.0 loads a layout model at
`import fitz` from data files that a source install has and the PyInstaller
analysis did not collect. Nothing between the build and the release had ever
started the app.

So **Build Windows** runs `DSI Redline.exe --self-test <report>` right after
PyInstaller and before Inno Setup. `main.py`'s `self_test` runs the whole
launch (QApplication, splash, the `app.main_window` import, the window), closes
it, and writes `ok` or the traceback to the report, because a windowed exe has
no stdout. Exit 1 fails the job before anything is packaged or published. An
exception raised before `main()` runs escapes the handler and opens a message
box, so the step also stops the app at 180 s and fails. Locally:

```
"dist\DSI Redline\DSI Redline.exe" --self-test report.txt
```

A launch reads no calculator table, so the self-test passed a v1.8.1 build
whose spec collected PyDRC's YAML and none of its JSON: the bundle had the rule
packs and not the 28 calculator tables or the part ratings file, and every calculator
stopped with "no NEC 2026 table". So **Build Windows** also runs, after
PyInstaller and before Inno Setup:

```
python tools/bundle_check.py --dist "dist/DSI Redline" pydrc
```

It lists every file in the installed PyDRC that is not a module and fails,
naming each one, when `_internal/pydrc/` lacks it. It exits 2 rather than
passing when PyDRC is not installed or has no data files, and the step runs
only when `PYDRC_BUILT` is not `none`, because a build without `PYDRC_TOKEN`
has no PyDRC to compare and has already warned so.

`tests/test_frozen_build.py` holds both steps' positions, the spec's
`excludes`, and the spec's `includes` against the installed PyDRC's files, on
every push. The steps themselves run only where the exe exists.

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
branch, which is the one thing the pin exists to prevent. Between steps 2 and 3,
re-run the notices audit (next section), so the build it reads installs the
PyDRC the release will, and commit what it changes. **Build Windows** runs the
audit's check on the bundle it builds, and on a `v*` tag it fails before
anything is packaged when `licenses/` differs (next section). **Build Windows** also
takes a `pydrc_ref` input when run manually, which overrides the file for that
one run — useful for testing a rule change against the app without committing a
pin.

The provenance line lands in the release notes whether the tag is pushed to a
repository with no release yet or the release is drafted in the GitHub UI first
and the tag pushed after. The second path is the common one and it is how
`v1.5.0` shipped with an empty body: the workflow only wrote notes when it
created the release itself. It now fills in the line either way, appending to
whatever a human wrote rather than replacing it.

### The notices name what the build ships

`THIRD-PARTY-NOTICES.md` and `licenses/` ship inside the installer, and they
must name every distribution the bundle carries. `requirements.txt` cannot say
which those are: the 2026-09-01 notices named ten packages and the v1.8.1
bundle carried 39, most of them installed by those ten. `tools/notices_audit.py`
reads the build instead. Run it between steps 2 and 3 above:

1. In a fresh virtual environment on Python 3.11, install what **Build Windows**
   installs, PyDRC at the ref `packaging/pydrc-ref.txt` names, and setuptools
   at the Windows runner's version:
   ```
   pip install -r requirements.txt -r packaging/requirements-build.txt "setuptools==65.5.0"
   pip install "pydrc[dxf] @ git+https://github.com/DSI-codebase/PyDRC@<ref>"
   ```
   A newer setuptools vendors `backports`, and httpx2's `from backports.zstd
   import` then pulls all of setuptools into a bundle the Windows build does
   not carry. `shipped` prints a NOTE when it sees setuptools in the list.
2. `pyinstaller packaging/DSI_Redline.spec --noconfirm`
3. `python tools/notices_audit.py shipped --build build/DSI_Redline --dist "dist/DSI Redline" --write build/shipped.txt`,
   under the interpreter that built the bundle. It reads the PYZ archive
   (`PYZ-00.toc`), the archive appended to `DSI Redline.exe` (`PKG-00.toc`,
   which holds `main.py`, PyInstaller's bootstrap and the run-time hooks, and
   only its `PYSOURCE` and `PYMODULE` entries count) and `_internal/`. It
   prints every installed distribution with a count for each, then the
   archive's scripts and the `_internal/` files no distribution claims. On
   Linux the files are host libraries and `libpython`, and the scripts are
   `main` and the modules PyInstaller compiles into `build/` (measured
   2026-11-01: 10 scripts and modules, 5 of them PyInstaller's). Read anything
   else.
4. `python tools/notices_audit.py fetch build/shipped.txt --dest build/wheels`
   downloads each one's Windows wheel, because a wheel's license file can
   differ by platform.
5. `python tools/notices_audit.py copy build/shipped.txt --wheels build/wheels --check`
   exits 0 when `licenses/` already matches and 1 listing each difference.
   Without `--check` it rewrites the per-distribution folders, and `--prune`
   also removes the folder of a package that no longer ships. The top-level
   texts are the project's own and are never touched. A package whose wheel
   ships no license file is printed as `by hand:` with the text that covers it,
   and counted apart from the ones with files of their own (below).
6. `python tools/notices_audit.py holders build/shipped.txt --wheels build/wheels`
   prints each package's license string and the lines that look like copyright
   statements. Update the entries in `THIRD-PARTY-NOTICES.md` from it, reading
   each line in its file, because it is a candidate list.
7. `python tools/run_tests.py tests.test_notices_ship tests.test_notices_audit`.
   The first holds each quoted line to the file it came from, the table to the
   folders, and the prose to the no-semicolon rule.

Every subcommand exits 2 rather than writing an empty answer: a missing input,
a build with no PYZ or no PKG table of contents or one that lists no code, no
installed distribution read, nothing shipping, a wheel that is missing, or a
wheel that holds no license file and is not supplied by hand.

**A wheel that ships no license file** has happened once: the PySide6 and
shiboken6 6.11.2 wheels shipped none (2026-09-01). Supply the text at the top of
`licenses/`, give it a row in the notices' table, and name both in
`SUPPLIED_BY_HAND` in `tools/notices_audit.py` with the reason. The list is
empty while every shipping wheel has a file of its own. The 6.11.3 Qt wheels
ship `LicenseRef-Qt-Commercial.txt`. An entry is refused (exit 2) when its text
is not there, when its wheel ships a license file again, and when its package
no longer ships, and names match the way pip matches them.
`tests/test_notices_ship.py` reads the list from the tool, so an entry with no
`licenses/<name>/` passes only when it is listed and its text is there.

### Build Windows checks the notices before it packages

v1.8.0 was tagged with notices listing ten packages while its bundle carried 42
distributions (the 2026-10-31 audit), and the audit above was a hand step. So
**Build Windows** runs "Check the notices against the bundle" after the
self-test and before Inno Setup: `shipped`, `fetch` and `copy --check` as in
steps 3 to 5, then `git status --porcelain -- licenses/`.

`copy --check` compares without writing, and its lines name a package that
joined (`missing:`), moved (`changed:`) or left (`stale:`). `git status` says
whether `licenses/` in the checkout is still the commit, because PyInstaller
copied the checkout's folder into the bundle and a release ships what is
committed. Each exit code is kept with `|| rc=$?`, never through a pipe.

| run | a difference, a refusal, or `licenses/` not the commit | everything matches |
|---|---|---|
| `v*` tag, `PYDRC_TOKEN` set | `::error::`, and the job fails before anything is packaged | passes |
| manual, `PYDRC_TOKEN` set | `::warning::`, and the build goes on | passes |
| no `PYDRC_TOKEN` | not run, and a warning says the notices were NOT checked | not run |

Without the token nothing is checked, because the audit measures the release
set and that includes PyDRC and the packages it brings. A failure is fixed by
running steps 1 to 7, committing `licenses/` and `THIRD-PARTY-NOTICES.md`, and
tagging again.

**It compares license files, not versions.** A package that moved to a version
whose license file is byte for byte the same passes. Measured on a Linux build
on 2026-11-01: anyio resolved to 4.16.0 while the notices name 4.15.1, and
`copy --check` reported 39 distributions, 67 files and 0 differences. Step 6
is where a version heading is corrected.

`tests/test_notices_audit.py` holds the step's position and its exit-code
handling, and drives its real `run:` block under Actions' bash flags
(`--noprofile --norc -eo pipefail`) with the audit stubbed and git real.
