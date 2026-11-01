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
missing, or skipped for a library ``requirements.txt`` declares.  Every
workflow that passes it installs ``requirements.txt`` first, so either skip
is a broken install, not a choice -- and a run that skipped every GUI test, or
every OCR test, must not report success.  The libraries are read from
``requirements.txt`` on each run, never from a list kept here, and whether
each one imports is asked of this interpreter, never read from the skip's
wording.  A ``requirements.txt`` that cannot be read or declares nothing is
refused under ``--strict`` (exit 2), because a check against no library
passes every run.

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
import importlib.metadata as metadata
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
# A requirement's name, the text before any extra, marker or version.
_REQUIREMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RAN_RE = re.compile(r"^Ran (\d+) test", re.M)
# Verbose unittest writes: "test_x (tests.y.Z.test_x) ... skipped 'reason'"
SKIP_RE = re.compile(r"\.\.\. skipped ['\"](.*?)['\"]")
# Reasons that mean "the optional rule library was missing", as spelled by the
# skipUnless decorators in tests/.
DRC_REASON = re.compile(r"pydrc", re.I)
# Qt is guaranteed by both workflows; if it is missing the environment is
# broken, and roughly a third of the suite quietly turns into skips.
QT_REASON = re.compile(r"pyside", re.I)


def classify(reasons, qt_missing=False, rule_library_missing=False) -> tuple:
    """``(drc_skipped, qt_skipped)`` from a {reason: count} mapping.

    A reason naming both -- "needs PySide6 and PyDRC" -- cannot say which was
    missing, so the two measurements decide: it counts against Qt when only Qt
    failed to load here, against both when both are absent, and otherwise
    against the rule library. Counting it as Qt whatever was measured failed a
    run whose Qt was fine. Counting it as the rule library whatever was
    measured told a run with PyDRC 0.19.0 installed and Qt missing that "13
    tests were SKIPPED because the design rule library is absent" (measured
    2026-10-30), and under ``--require-drc`` failed it for that.
    """
    drc = qt = 0
    for reason, n in reasons.items():
        names_drc = bool(DRC_REASON.search(reason))
        names_qt = bool(QT_REASON.search(reason))
        if names_drc and names_qt and qt_missing:
            qt += n
            if rule_library_missing:
                drc += n
        elif names_drc:
            drc += n
        elif names_qt:
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


def qt_missing() -> bool:
    """Whether Qt fails to load in this interpreter.

    Asked of ``tests/_qt.py``, the probe every Qt test skips on, so the runner
    and the skips cannot disagree about it. It imports QtCore, QtGui and
    QtWidgets, because the failure CI.md documents is ``import PySide6.QtGui``
    raising ``libEGL.so.1: cannot open shared object file``, which a check of
    the package alone need not see.
    """
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from tests._qt import QT_OK
    return not QT_OK


def declared(path=None) -> list:
    """Each library ``requirements.txt`` declares, spelled as it spells it.

    Read from the file on every run rather than from a list kept here, so a
    library added there is held by ``--strict`` from that commit on.
    tests/test_pdf_to_word_imports.py skips without pdf2docx, and the
    request that produced this named only pytesseract and anthropic. Raises
    OSError when the file cannot be read, and `main` refuses a strict run
    then.
    """
    names = []
    with open(path or REQUIREMENTS, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):     # -r, -c, --index-url
                continue
            m = _REQUIREMENT.match(line)
            if m:
                names.append(m.group(0))
    return names


def _dist(name) -> str:
    """A distribution's name as pip compares it (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def import_names(library, top_levels=None) -> list:
    """The modules to import to ask whether ``library`` loads.

    Asked of the installed distribution's metadata, because the names differ:
    Pillow installs ``PIL``, python-docx ``docx`` and PyYAML ``yaml``. The
    module named like the distribution wins when there is one, because a
    distribution can install more than the library. PyMuPDF 2.0 also installs
    ``pymupdf4llm``, and PyYAML installs ``_yaml``, whose ``__init__`` raises
    when PyYAML was built without LibYAML (both read 2026-11-01, at the floors
    and the newest releases). A private name, or a path such as the
    ``PySide6/QtCore`` PySide6's metadata yields, is never a candidate. With
    no metadata at all, the name as pip compares it is tried as a module.
    """
    if top_levels is None:
        top_levels = metadata.packages_distributions()
    want = _dist(library)
    mine = sorted(m for m, dists in top_levels.items()
                  if m.isidentifier() and not m.startswith("_")
                  and want in {_dist(d) for d in dists})
    same = [m for m in mine if _dist(m) == want]
    return same or mine or [want.replace("-", "_")]


def declared_libraries(path=None) -> dict:
    """``{library: [module, ...]}`` for each library `declared` reads."""
    top_levels = metadata.packages_distributions()
    return {lib: import_names(lib, top_levels) for lib in declared(path)}


def _names(reason, word) -> bool:
    """Whether ``reason`` names ``word`` whole. "pdf2docx" and "a .docx file"
    do not name docx, and "PyYAML" does not name yaml."""
    return re.search(rf"(?<![\w.-]){re.escape(word)}(?![\w-])",
                     reason, re.I) is not None


def named_libraries(reason, libraries) -> list:
    """The declared libraries a skip reason names, by distribution or module.

    None for a reason `classify` files under Qt or the rule library. PySide6
    is declared too, and those reasons already have a probe and a banner of
    their own, so filing them here as well would count each skip twice.
    """
    if DRC_REASON.search(reason) or QT_REASON.search(reason):
        return []
    return [lib for lib, mods in libraries.items()
            if any(_names(reason, w) for w in (lib, *mods))]


def missing_declared(libraries) -> list:
    """Which of ``{library: [module, ...]}`` this interpreter cannot import.

    Asked the way `missing_optional` asks, by importing, and never read from
    the skip's wording. "needs pytesseract, which is not installed" is what a
    test says whenever its own import failed, and a shadowing module or a
    broken wheel fails that import as surely as an absent library.
    """
    absent = []
    for lib, mods in libraries.items():
        for mod in mods:
            try:
                __import__(mod)
            except Exception:
                absent.append(lib)
                break
    return absent


def declared_skips(reasons, libraries, absent) -> collections.Counter:
    """``{library: skips}`` for the skip reasons naming a declared library.

    A reason naming two counts against the ones measured absent, and against
    every one it names when none is, the rule `classify` follows for a reason
    naming both Qt and the rule library.
    """
    out = collections.Counter()
    for reason, n in reasons.items():
        named = named_libraries(reason, libraries)
        for lib in [lib for lib in named if lib in absent] or named:
            out[lib] += n
    return out


def gaps(reasons, absent, qt_absent, *, rule_library_missing,
         libraries=None, declared_absent=()) -> list:
    """``(count, why, hint)`` for each banner: one per cause, each built from
    what was measured missing here rather than from the reason's wording.

    ``rule_library_missing`` is `drc_status`'s answer, never ``bool(absent)``.
    The tests that skip with "needs PySide6 and PyDRC" check
    ``audit.available()``, which imports pydrc and never ezdxf. Passing
    ``bool(absent)`` charged them to ezdxf whenever ezdxf alone was missing:
    17 skips bannered as "ezdxf ... could not be imported" with Qt missing
    and PyDRC importable (2026-10-31).

    ``libraries`` is `declared_libraries`' answer and ``declared_absent`` is
    `missing_declared`'s. Each declared library a skip names gets its own
    banner, in requirements.txt's order, saying whether it imports here.
    """
    drc_skipped, qt_skipped = classify(
        reasons, qt_missing=qt_absent,
        rule_library_missing=rule_library_missing)
    out = []
    if drc_skipped:
        # Name what is MEASURED absent, not the category the reason string
        # was filed under. `"needs ezdxf and pydrc"` is one string for two
        # libraries and `classify` must pick one; in CI it picked the one that
        # was installed, and every run pointed at CI.md about a token that had
        # been configured all along. When nothing is measured absent the
        # banner says that, never "the design rule library is absent".
        if absent:
            why = " and ".join(d for _, d in absent) + " could not be imported"
            hint = "See CI.md to give the workflow access to it."
        else:
            why = ("their skip check failed, although "
                   + " and ".join(_OPTIONAL) + " both import here")
            hint = "Run the module alone with -v to see which check skipped."
        out.append((drc_skipped, why, hint))
    if qt_skipped:
        out.append((qt_skipped, "Qt (PySide6) could not be loaded",
                    "On Linux this usually means the Qt system libraries are "
                    "missing; see the Tests workflow."))
    libraries = libraries or {}
    counted = declared_skips(reasons, libraries, declared_absent)
    for lib in libraries:
        if not counted[lib]:
            continue
        if lib in declared_absent:
            why = f"{lib}, which requirements.txt declares, could not be imported"
            hint = ("Install it with pip install -r requirements.txt. Every "
                    "workflow does, so in CI this is a broken install.")
        else:
            why = f"their skip check failed, although {lib} imports here"
            hint = "Run the module alone with -v to see which check skipped."
        out.append((counted[lib], why, hint))
    return out


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

    # Before any test runs, because a strict run against no library would
    # pass every skip it is there to catch.
    try:
        libraries = declared_libraries()
        unread = "declares no library"
    except OSError as e:
        libraries, unread = {}, f"could not be read ({e})"
    if strict and not libraries:
        print(f"--strict: {REQUIREMENTS} {unread}, so a skip for a library "
              f"it declares cannot be checked. Refusing the run rather than "
              f"reporting it clean.")
        return 2

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
    absent = missing_optional()
    qt_absent = qt_missing()
    drc_skipped, qt_skipped = classify(reasons, qt_missing=qt_absent,
                                       rule_library_missing=not ok)
    # Imported only when a skip names them: the answer is needed for the
    # banner, and a library no test skipped for has nothing to explain.
    named = {lib for reason in reasons
             for lib in named_libraries(reason, libraries)}
    declared_absent = missing_declared(
        {lib: mods for lib, mods in libraries.items() if lib in named})
    declared_skipped = declared_skips(reasons, libraries, declared_absent)
    for count, why, hint in gaps(reasons, absent, qt_absent,
                                 rule_library_missing=not ok,
                                 libraries=libraries,
                                 declared_absent=declared_absent):
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
    #
    # Every cause is printed before the run fails, so a run that skipped for
    # two reasons does not report only the first.
    refused = False
    if require_drc and drc_skipped:
        print(f"\n--require-drc: failing because {drc_skipped} tests were "
              f"skipped for a missing optional library, which this run was "
              f"supposed to provide.")
        if absent:
            print("Absent here: " + ", ".join(m for m, _ in absent))
        refused = True
    if strict and qt_skipped:
        print(f"\n--strict: failing because {qt_skipped} tests were skipped "
              f"for a missing Qt, which CI is supposed to provide.")
        refused = True
    # The same rule for every other library the app declares. pytesseract and
    # anthropic each skipped their tests with a skip line and a green run
    # under --strict (measured 2026-11-01 with both shadowed by modules that
    # raise ImportError), although both workflows install them.
    if strict and declared_skipped:
        total = sum(n for reason, n in reasons.items()
                    if named_libraries(reason, libraries))
        each = ", ".join(f"{lib} ({declared_skipped[lib]})"
                         for lib in libraries if declared_skipped[lib])
        print(f"\n--strict: failing because {total} tests were skipped for "
              f"a library requirements.txt declares, which every workflow "
              f"installs: {each}.")
        if declared_absent:
            print("Absent here: " + ", ".join(declared_absent))
        refused = True
    if failed:
        print(f"\nFAILED MODULES: {', '.join(failed)}")
        return 1
    if refused:
        return 1
    print("\nAll test modules passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
