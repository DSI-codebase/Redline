# Contributing to DSI Redline

`README.md` is what the app does, `docs/` is the user manual (served in-app by
`app/help.py`), `CI.md` is the workflows and the release ordering, and
`CLAUDE.md` is the standing rules. This file is how to run it and what a good
change looks like.

## Run the gates

Python 3.11+.

```bash
pip install -r requirements.txt        # the app
pip install -r requirements-drc.txt    # ...and design rule checking (private repo)
python tools/run_tests.py              # everything
python tools/run_tests.py -v           # everything, verbose
python tools/run_tests.py tests.test_audit
```

**`.github/workflows/tests.yml` is the authority, not this file.** It runs on
Ubuntu and Windows, on every push and every pull request, with `--strict` and
— whenever the PyDRC token is present — `--require-drc`, so **a skip fails the
run** rather than hiding under a green tick.

This used to quote a test count as well. It drifted: the documented 682 was
720 when somebody next looked, and `CLAUDE.md` had three different numbers in
it by then. The runner prints the current one; a document that repeats it is a
copy nobody reads until it disagrees with the terminal in front of them.

Two things about a local run that are not failures:

- **On Linux you need Qt's system libraries.** Without them
  `import PySide6.QtGui` fails with `libEGL.so.1: cannot open shared object
  file` and about a third of the suite becomes skips. `CI.md` has the package
  list; the workflow installs them for you.
- **Without PyDRC the design-rule tests skip.** That library is in a private
  repository, so a contributor without access runs everything else and the
  audit code goes unexercised. The runner says so in a loud banner rather than
  letting it pass quietly, and CI passes `--require-drc` when a `PYDRC_TOKEN`
  secret gave it the library. A fork's PR always runs in skip-and-say-so mode,
  because secrets are not exposed to forks.

## Five things that will fail review

- **Writing to the user's original PDF.** Marks go into a `*.marked.pdf` copy
  and app-only state into a `*.markup.db` sidecar. The source drawing set is
  never modified, and a file that cannot back a sidecar opens view-only rather
  than half-working.
- **A hard import of `pydrc`, `ezdxf` or `anthropic`.** All three are optional
  and all three must report themselves unavailable *in the place they would
  have been used* — the Audit tab, the import dialog, the extraction path —
  rather than raising. A new one follows the same pattern.
- **Adding PyDRC to `requirements.txt`.** It is private, so that would make
  `pip install -r requirements.txt` fail for anyone without credentials,
  including every CI runner. It belongs in `requirements-drc.txt`.
- **A new `skipUnless` with no banner behind it.** A skip is how coverage
  evaporates under a green tick. `tools/run_tests.py` groups skips by their
  stated reason and prints a banner naming how many tests each one covered; a
  reason it does not recognise is counted but unexplained.
- **A version number in a fourth place.** There are three, and that is not a
  preference to be tidied away: `app/__init__.py` is what the About box and the
  audit report show, `packaging/installer.iss` names the setup executable and
  what Windows records in Add/Remove Programs, and `CHANGELOG.md` carries the
  section. `tests/test_requirements.py::TestVersionIsStatedOnce` fails when they
  disagree — it caught the 1.5.2 bump within a minute of it being made in one
  file. The `v*` tag is a fourth declaration no test can see; the release
  workflow checks that one.

  This bullet read *"a version number anywhere but `app/__init__.py`"* while
  the gate three feet away proved otherwise. **A rule and a gate that
  contradict each other teach people to trust neither**, and it is the rule
  that was wrong.
- **A `if __name__ == "__main__"` block anywhere but the end of the file.**
  Everything below it is invisible to a direct run — `test_requirements.py` ran
  3 of its 5 tests that way, and the two that vanished were the version gates
  above. `tests/test_suite_is_discoverable.py` sweeps for it.

## What a good PR looks like here

- **A test that fails before the fix.** Check it by reverting the change and
  watching it go red — a test written from the same assumption as the code pins
  the bug rather than catching it.
- **Say which gate passed.** "The suite passes locally" over a run that skipped
  54 Qt tests is not the same claim as "CI green on both runners", and the
  runner's own banner will tell you which one you have. Report skips and
  failures with their output rather than smoothing them over.
- **Docs move with the change.** A new tool or menu item means a page in
  `docs/`; the in-app help serves those files directly, so a feature with no
  page is a feature with no help.
- **A GUI change is worth saying you ran.** Much of `app/viewer` and
  `app/panels` is exercised headlessly with `QT_QPA_PLATFORM=offscreen`, which
  proves the code path and not what it looks like.
- **Keep a test module runnable on its own.** The runner gives each module its
  own process — running the whole suite in one accumulates Qt GUI resources and
  hard-crashes a late module on the headless Windows runner — so a module that
  depends on another having run first will fail in a way that names the wrong
  file.

## Releases

Order matters and `CI.md` has the detail. Briefly: tag PyDRC, point
`packaging/pydrc-ref.txt` at that tag and commit it, *then* tag the app. The
ref is resolved to a commit SHA before installing and that SHA is printed in
the build log and the release notes, so an installer can always say which rules
it contains. Tagging the app first produces a release whose notes name a moving
branch, which is exactly what the pin exists to prevent.
