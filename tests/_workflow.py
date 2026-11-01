"""Every step check in tests/ reads the GitHub workflows here, with PyYAML.

Not every test. Two in `tests/test_requirements.py` read the raw text on
purpose, and neither asks about a step:
`test_the_workflows_do_not_write_the_account_down_at_all` searches each whole
file for a written-down account, and
`test_the_frozen_build_stays_pinned_and_says_why` reads the pin's reason,
which is a YAML comment this loader drops. Measured 2026-11-01 by an AST sweep
of tests/ and by an `open` audit hook over a full suite run with 0 skipped:
those two are the only reads of a workflow that do not come through here. No
test holds that, so a new hand reader would make the first line false without
failing anything.

Three tests read the workflows by hand, and each excused it with a sentence
saying PyYAML is not a dependency here. `requirements.txt` has declared
`PyYAML>=6.0` since `d01d62b`, the commit that brought the code in. The two
step readers, in `test_run_tests.py` and `test_drc_ref_resolution.py`, were
measured against `yaml.safe_load` on 2026-11-01 over every named step in both
workflows, and 5 of 40 readings differed:

- after a one-line `run:`, both took the comment block above the next step as
  part of the script, because that comment set the block's indent;
- the second copy returned an empty script for a one-line `run:`, which is how
  `build-windows.yml` writes its "Run tests" step.

No step a test read was among the five, so no check had been answered wrongly
yet. Both readers also returned the FIRST step of a name in any job, which
nothing exercised because no two steps share a name today.

So a step is found by name across every job, and a name that more than one
step carries is refused rather than answered with the first. Pass `job=` to
say which one a check is about.

Why PyYAML is in `requirements.txt` at all is the comment above its line
there. `tests/test_requirements.py` holds that line to this module's import.
"""

from __future__ import annotations

import yaml


def load(path: str) -> dict:
    """The workflow at `path` as GitHub reads it, refused if it has no jobs.

    `safe_load` maps the bare key `on:` to `True` (YAML 1.1), so read
    triggers with `doc[True]`. Nothing here reads them.
    """
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict) \
            or not doc["jobs"]:
        raise AssertionError(f"{path} defines no jobs, so it is not a workflow "
                             "this reader can answer for")
    return doc


def step(path: str, step_name: str, job: str | None = None) -> dict:
    """The one step called `step_name`, in `job` or in any job."""
    jobs = load(path)["jobs"]
    if job is not None:
        if job not in jobs:
            raise AssertionError(f"no job named {job!r} in {path}; it has "
                                 f"{sorted(jobs)}")
        jobs = {job: jobs[job]}
    found = [(name, st) for name, body in jobs.items()
             for st in (body or {}).get("steps") or []
             if isinstance(st, dict) and st.get("name") == step_name]
    where = f" job {job!r} of" if job is not None else ""
    if not found:
        raise AssertionError(f"no step named {step_name!r} in{where} {path}")
    if len(found) > 1:
        raise AssertionError(
            f"{len(found)} steps are named {step_name!r} in{where} {path}, in "
            f"jobs {[name for name, _ in found]}. The first one found is not "
            "an answer: pass job= to say which step the check is about.")
    return found[0][1]


def run_script(path: str, step_name: str, job: str | None = None) -> str:
    """The SCRIPT of that step's `run:`, exactly as the runner receives it.

    Never the whole file. A check over the file text is answered by the comment
    above the line it is hunting, which is a dead gate this repository has
    already paid for, and YAML comments are not part of the script.
    """
    run = step(path, step_name, job).get("run")
    if not isinstance(run, str):
        raise AssertionError(f"step {step_name!r} in {path} has no `run:` script")
    return run
