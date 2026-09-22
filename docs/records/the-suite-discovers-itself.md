# A test that hides itself runs a smaller number, and nothing reports that

Carved out of `CLAUDE.md` on 2026-09-22. A closed defect narrative is a
**record**, not an instruction: it keeps its measurements and its dates, and
nothing here is loaded on every turn. The standing rule it produced stays in
`CLAUDE.md`.

## A test that hides itself runs a smaller number, and nothing reports that

Two ways a module here ran fewer tests than it holds. Neither is a failure —
both are a *smaller number*, and no runner calls that anything.

- **A misplaced `if __name__ == "__main__"` block hides everything below it
  from a direct run.** `python3 tests/test_requirements.py` ran **3** tests
  where `python3 -m unittest tests.test_requirements` ran **5**: the guard sat
  at line 44 and `TestVersionIsStatedOnce` began at 48, so the two that vanished
  were **the version-drift gates** — the ones that exist because the installer
  once sat at 1.4.0 while the app moved on.

  Four modules carried the guard mid-file. In three it was harmless *only*
  because they import `app` at module scope and cannot be run as scripts at all
  — luck rather than design, and the kind that expires the first time somebody
  moves an import.

- **A Qt-dependent class without the `skipUnless` its siblings carry errors
  instead of skipping.** `TestRolledUpFindingOnScreen` had none, so a machine
  without Qt got `FAILED (errors=1, skipped=31)` where it should get a clean
  skip. Loud, which is the safe direction — and loud about the wrong thing,
  which makes a legitimately-skipping run look broken.

`tests/test_suite_is_discoverable.py` sweeps **the artifact** for both, never a
list of the modules that had the problem when it was written — a gate scoped to
today's offenders covers what was there when the list was made.

### ...and its first draft cried wolf, which is the half worth keeping

The Qt sweep flagged `test_v12_order.py::TestDrawNewOnce`, a working class in a
module that skips cleanly (10 of 10). `unittest.skipUnless` sets
`__unittest_skip__` on the class it decorates and **a subclass inherits it** —
measured rather than assumed: a child of a skipped base reports
`OK (skipped=2)` and `Child.__unittest_skip__` is `True`. So `_Base` covers
both classes under it. Ancestry counts now, resolved within the module, which
is where these bases live.

**An audit that flags a working file is one nobody reads twice.** Calibrate
before believing it — and the stated limit is direct use only: a class calling
a module-level helper that touches a guarded name is not caught, and widening
that means resolving calls, which is a different tool.

### The version rule and the version gate had been contradicting each other

`CONTRIBUTING.md` listed *"a version number anywhere but `app/__init__.py`"*
among the things that fail review, three feet from
`TestVersionIsStatedOnce`, which exists **because there are three** and fails
when they disagree. **A rule and a gate that contradict each other teach people
to trust neither**, and here it was the rule that was wrong. `CLAUDE.md` was
corrected at the 1.5.2 bump and `CONTRIBUTING.md` was not — the same
fix-where-it-was-noticed pattern, one file over.
