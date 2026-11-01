"""Confirm that every pin in a constraint file is the version installed.

    python tools/check_floors.py .github/floors.txt

The ``floors`` job in ``.github/workflows/tests.yml`` installs
``requirements.txt`` under that constraint file and then runs this, because the
oracle for "the suite ran at the floors" is the installed distribution, not the
file that asked for it. A step that installed without the constraint would
otherwise run the newest releases under the floor job's name.

Prints one line per pin and three counts: at the pin, at another version, and
not installed. Exit 0 when every pin is installed at its version, 1 when one is
not, and 2 when the file names no pin or holds a line this cannot read. A check
over nothing reports what a clean one reports, so it is refused.
"""

from __future__ import annotations

import importlib.metadata as metadata
import re
import sys

PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([0-9][0-9.]*)$")
RELEASE = re.compile(r"^([0-9]+(?:\.[0-9]+)*)$")


def release(version):
    """``(6, 6)`` for both ``"6.6"`` and ``"6.6.0"``, as PEP 440 compares a
    release, or ``None`` for anything with a pre, post, dev or local part."""
    m = RELEASE.match(version.strip())
    if not m:
        return None
    parts = [int(p) for p in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def read_pins(text):
    """``([(name, version), ...], [unreadable line, ...])`` from a constraint
    file. Comments and blank lines are neither."""
    pins, unreadable = [], []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = PIN.match(line)
        if m:
            pins.append((m.group(1), m.group(2)))
        else:
            unreadable.append(raw)
    return pins, unreadable


def check(pins, version_of=metadata.version):
    """``(at_pin, elsewhere, absent)``, each a list of report lines."""
    at_pin, elsewhere, absent = [], [], []
    for name, want in pins:
        try:
            got = version_of(name)
        except metadata.PackageNotFoundError:
            absent.append(f"{name}: not installed, floor {want}")
            continue
        line = f"{name}: installed {got}, floor {want}"
        if release(got) is not None and release(got) == release(want):
            at_pin.append(line)
        else:
            elsewhere.append(line)
    return at_pin, elsewhere, absent


def main(argv):
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    path = argv[0]
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"cannot read {path}: {exc}")
        return 2
    pins, unreadable = read_pins(text)
    if unreadable:
        print(f"{path}: {len(unreadable)} line(s) are not `name==version`: "
              f"{unreadable}")
        return 2
    if not pins:
        print(f"{path} names no pin, so there is nothing to confirm. Refusing "
              "to report a floor run that checked nothing.")
        return 2

    at_pin, elsewhere, absent = check(pins)
    for line in at_pin + elsewhere + absent:
        print(line)
    print(f"\n{len(at_pin)} at the floor, {len(elsewhere)} at another version, "
          f"{len(absent)} not installed, of {len(pins)} pinned in {path}.")
    return 0 if not elsewhere and not absent else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
