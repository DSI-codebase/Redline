"""Run the test suite with each module in its own process.

Running the whole suite in a single process accumulates Qt GUI resources
(GDI/USER handles, pixmaps) from the many window-creating tests and hard-crashes
a late module on the headless Windows runner -- even though every module passes
on its own.  Per-module isolation keeps resource use bounded, and it names the
module that failed instead of leaving a bare crash in the log.

It also reports *why* tests were skipped, grouped by reason.  A green run that
quietly skipped the design rule checks is not the same as a green run that
checked them, and CI should not let those two look alike.

    python tools/run_tests.py [-v] [--strict] [--require-drc] [module ...]

``--strict`` (used by CI) fails the run when tests were skipped because Qt was
missing.  The workflows install Qt, so that is a broken runner, not a choice --
and a run that skipped every GUI test must not report success.

``--require-drc`` is the same rule for the optional rule library, and it is
passed only by the workflow step that has just installed it.  A contributor
without access to the private PyDRC still gets a clean local run; CI, which
provides it, goes red rather than printing a banner under a green tick.

That distinction was not academic.  The Tests workflow installed ``pydrc``
without the ``[dxf]`` extra for as long as it existed, so ezdxf was absent,
five project-import tests never ran on any runner, and every run said so in
capital letters and passed.
"""

from __future__ import annotations

import collections
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAN_RE = re.compile(r"^Ran (\d+) test", re.M)
# Verbose unittest writes: "test_x (tests.y.Z.test_x) ... skipped 'reason'"
SKIP_RE = re.compile(r"\.\.\. skipped ['\"](.*?)['\"]")
# Reasons that mean "the optional rule library was missing", as spelled by the
# skipUnless decorators in tests/.
DRC_REASON = re.compile(r"pydrc", re.I)
# Qt is guaranteed by both workflows; if it is missing the environment is
# broken, and roughly a third of the suite quietly turns into skips.
QT_REASON = re.compile(r"pyside", re.I)


def classify(reasons) -> tuple:
    """``(drc_skipped, qt_skipped)`` from a {reason: count} mapping.

    A reason naming both -- "needs PySide6 and PyDRC" -- is attributed to the
    rule library, not to Qt. It cannot say which was actually missing, but the
    rule library is the one allowed to be absent, and a genuinely missing Qt
    announces itself in dozens of unambiguous "PySide6 not available" skips
    rather than in one compound reason. Counting it as Qt failed a run whose
    Qt was fine.
    """
    drc = qt = 0
    for reason, n in reasons.items():
        if DRC_REASON.search(reason):
            drc += n
        elif QT_REASON.search(reason):
            qt += n
    return drc, qt


def modules(argv) -> list:
    named = [a for a in argv if not a.startswith("-")]
    if named:
        return named
    found = glob.glob(os.path.join(HERE, "tests", "test_*.py"))
    return sorted("tests." + os.path.basename(p)[:-3] for p in found)


# The libraries a skip reason can name. Asked of the interpreter, never
# inferred from the reason text -- see `missing_optional`.
_OPTIONAL = {
    "pydrc": "the design rule library (PyDRC)",
    "ezdxf": "ezdxf, which reads AutoCAD Electrical drawings",
}


def missing_optional() -> list:
    """Which optional libraries this interpreter cannot import.

    The skip REASONS cannot answer this. ``"needs ezdxf and pydrc"`` is one
    string naming two libraries, so `classify` has to attribute it to one of
    them -- and that guess was wrong in CI for as long as the workflow
    existed. The Tests workflow installed ``pydrc`` **without the ``[dxf]``
    extra**, so the library that was actually absent was ezdxf, while the
    banner said the rule library was missing and pointed at CI.md, about a
    token that had been configured all along. Five tests never ran there and
    the run was green.

    Asking the interpreter costs one import each and cannot be wrong.
    """
    absent = []
    for mod, described in _OPTIONAL.items():
        try:
            __import__(mod)
        except Exception:
            absent.append((mod, described))
    return absent


def drc_status() -> tuple:
    """``(available, message)`` for the optional rule library."""
    try:
        sys.path.insert(0, HERE)
        from app import audit
        return audit.status()
    except Exception as e:                       # pragma: no cover - defensive
        return False, f"could not be queried: {e}"


def main(argv) -> int:
    verbose = "-v" in argv
    strict = "--strict" in argv
    require_drc = "--require-drc" in argv
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    names = modules(argv)

    ok, message = drc_status()
    print(f"Design rule library: {message}")
    print()

    failed, ran = [], 0
    reasons = collections.Counter()
    for mod in names:
        # Always verbose in the subprocess: the skip reasons are only in the
        # verbose stream, and attributing a skip to the wrong cause is worse
        # than not counting it. The output is captured either way.
        proc = subprocess.run([sys.executable, "-m", "unittest", mod, "-v"],
                              cwd=HERE, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")

        counted = RAN_RE.search(out)
        ran += int(counted.group(1)) if counted else 0
        found = SKIP_RE.findall(out)
        reasons.update(found)

        status = "ok  " if proc.returncode == 0 else "FAIL"
        note = f" ({len(found)} skipped)" if found else ""
        print(f"{status} {mod}{note}", flush=True)
        if proc.returncode != 0 or verbose:
            print(out)
        if proc.returncode != 0:
            failed.append(mod)

    total_skipped = sum(reasons.values())
    print()
    print(f"{ran} tests across {len(names)} modules; {total_skipped} skipped.")
    for reason, n in reasons.most_common():
        print(f"    {n:4d}  {reason}")

    # Loud on purpose. "No failures" must never be read as "everything was
    # checked" -- the same rule the audit itself follows about coverage.
    drc_skipped, qt_skipped = classify(reasons)
    absent = missing_optional()

    gaps = []
    if drc_skipped:
        # Name what is MEASURED absent, not the category the reason string
        # was filed under. `"needs ezdxf and pydrc"` is one string for two
        # libraries and `classify` must pick one; in CI it picked the one that
        # was installed, and every run pointed at CI.md about a token that had
        # been configured all along.
        why = (
            " and ".join(d for _, d in absent) + " could not be imported"
            if absent else "the design rule library is absent"
        )
        gaps.append((drc_skipped, why,
                     "See CI.md to give the workflow access to it."))
    if qt_skipped:
        gaps.append((qt_skipped, "Qt (PySide6) could not be loaded",
                     "On Linux this usually means the Qt system libraries are "
                     "missing; see the Tests workflow."))
    for count, why, hint in gaps:
        print()
        print("!" * 72)
        print(f"!! {count} tests were SKIPPED because {why}.")
        print("!! That code was NOT exercised by this run.")
        print(f"!! {hint}")
        print("!" * 72)

    # CI installs every optional library, so a rule-library skip THERE is a
    # regression rather than an absent dependency -- and it is exactly the
    # shape that hid for as long as this workflow existed: a loud banner under
    # a green tick. A contributor without the private token still gets a clean
    # run, because the workflow only passes this once the install step ran.
    if require_drc and drc_skipped:
        print(f"\n--require-drc: failing because {drc_skipped} tests were "
              f"skipped for a missing optional library, which this run was "
              f"supposed to provide.")
        if absent:
            print("Absent here: " + ", ".join(m for m, _ in absent))
        return 1
    if strict and qt_skipped:
        print(f"\n--strict: failing because {qt_skipped} tests were skipped "
              f"for a missing Qt, which CI is supposed to provide.")
        return 1
    if failed:
        print(f"\nFAILED MODULES: {', '.join(failed)}")
        return 1
    print("\nAll test modules passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
