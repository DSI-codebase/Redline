"""The every-turn context budget, and the records carved out of `CLAUDE.md`.

WHY THIS IS A GATE AND NOT A SENTENCE
-------------------------------------
`CLAUDE.md` was **1,088 lines** and every session paid for all of it, whether or
not it opened a PDF writer or a workflow. Most of it was closed defect
narrative — true, dated, worth keeping, and not an instruction. Eight records
came out; the standing rule each produced stayed. A note saying "keep this
short" is what the file had; it grew anyway.

ONE CEILING, AND IT IS ON WHAT IS LOADED
----------------------------------------
Capping `CLAUDE.md` *and* the loaded total makes the first unreachable by
construction, because the total is the larger number. What costs a session is
`CLAUDE.md` plus every **unscoped** `.claude/rules/*.md`: a rule whose first
five lines carry `paths:` loads only when its files are opened, and one without
it is loaded at launch at `CLAUDE.md` priority. So the ceiling is on the sum,
and moving a section into an unscoped rule file buys nothing — which is the
point.

`house-voice.md` is the one exemption, granted by the owner rather than by this
repository: it is portfolio-wide and installed from Pathforward's kit byte for
byte. `gates.md` is **not** exempt, deliberately — it is 32 lines from the same
kit, and it is part of what a turn costs.

THE FLOOR IS ON `CLAUDE.md` ALONE
---------------------------------
A file cut to nothing satisfies a ceiling perfectly. The floor is what says the
standing rules are still here rather than all in `docs/records/`.

THREE NUMBERS, NEVER TWO
------------------------
The message names `CLAUDE.md`, each counted rule with its own line count, and
the exempt ones separately — because "loaded 210" does not say which file to cut.

WHAT THIS DOES NOT CHECK
------------------------
Whether a record says anything true, and whether a standing rule that should
have stayed in `CLAUDE.md` went into one. Those are judgements. What is
checkable is the cost and the reachability, and both were unchecked.
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLAUDE = ROOT / "CLAUDE.md"
RULES = ROOT / ".claude" / "rules"
RECORDS = ROOT / "docs" / "records"

EXEMPT = {
    "house-voice.md": (
        "portfolio-wide, installed from Pathforward's kit byte for byte, and "
        "exempted by the owner rather than by this repository"
    ),
}

# Derived from RECORDS rather than written twice, so the directory and the
# pattern that reads the table cannot part company.
_REL = RECORDS.relative_to(ROOT).as_posix()
_ROW = re.compile(r"^\|\s*`(" + re.escape(_REL) + r"/[^`]+)`\s*\|", re.M)


def _lines(path: pathlib.Path) -> int:
    """`wc -l`: a trailing newline does not start a line."""
    text = path.read_text(encoding="utf-8")
    return len(text.split("\n")) - (1 if text.endswith("\n") else 0)


def _scoped(path: pathlib.Path) -> bool:
    """A rule with `paths:` frontmatter loads only when its files are opened."""
    head = path.read_text(encoding="utf-8").split("\n")[:5]
    return any(line.startswith("paths:") for line in head)


class TestTheEveryTurnBudget(unittest.TestCase):
    MIN_CLAUDE_LINES = 60
    MAX_LOADED_LINES = 200

    def _split(self):
        claude = _lines(CLAUDE)
        rules, exempt, swept = {}, {}, 0
        for path in sorted(RULES.glob("*.md")):
            swept += 1
            if _scoped(path):
                continue
            (exempt if path.name in EXEMPT else rules)[path.name] = _lines(path)
        return claude, rules, exempt, swept

    def test_the_loaded_context_is_under_two_hundred_lines(self):
        claude, rules, exempt, swept = self._split()
        self.assertGreater(swept, 0, f"no rule file found under {RULES} — the "
                                     "sweep is measuring nothing, not finding nothing")
        loaded = claude + sum(rules.values())
        detail = ", ".join(f"{n} {v}" for n, v in sorted(rules.items())) or "none"
        self.assertLessEqual(
            loaded, self.MAX_LOADED_LINES,
            f"every turn loads {loaded} lines against a ceiling of "
            f"{self.MAX_LOADED_LINES}: CLAUDE.md {claude}, unscoped rules "
            f"[{detail}]. Exempt and not counted: "
            f"{sorted(exempt) or 'none'}. Carve a closed narrative into "
            f"{_REL}/ and add its row, or scope a rule with `paths:`.",
        )

    def test_claude_md_is_still_above_the_floor(self):
        claude, _, _, _ = self._split()
        self.assertGreaterEqual(
            claude, self.MIN_CLAUDE_LINES,
            f"CLAUDE.md is {claude} lines, under the {self.MIN_CLAUDE_LINES}-line "
            "floor. A file cut to nothing satisfies the ceiling perfectly; the "
            "standing rules belong here rather than all in a record.",
        )

    def test_every_exemption_still_names_a_file_that_exists(self):
        for name, reason in EXEMPT.items():
            with self.subTest(name=name):
                self.assertTrue(
                    (RULES / name).exists(),
                    f"EXEMPT names {name}, which is not in {RULES} — an exemption "
                    "nobody re-measures is how a real cost stops being counted.",
                )
                self.assertTrue(reason.strip(), f"{name} is exempt for no stated reason")


class TestTheRecordsAreReachable(unittest.TestCase):
    """Both directions. A row naming a missing file sends a reader nowhere; a
    record the table does not name is written, kept and unreachable."""

    def _rows(self):
        return set(_ROW.findall(CLAUDE.read_text(encoding="utf-8")))

    def _files(self):
        return {p.relative_to(ROOT).as_posix() for p in RECORDS.glob("*.md")}

    def test_the_table_named_something(self):
        rows = self._rows()
        self.assertTrue(
            rows,
            f"CLAUDE.md's records table matched no `{_REL}/…` row. A sweep that "
            "matched nothing reports what a clean one reports — check the table "
            "is still there and still written as a markdown row.",
        )

    def test_every_row_names_a_record_that_is_there(self):
        missing = sorted(self._rows() - self._files())
        self.assertEqual(missing, [], f"CLAUDE.md sends a reader to {missing}, "
                                      f"which is not in {_REL}/")

    def test_every_record_is_named_by_the_table(self):
        orphans = sorted(self._files() - self._rows())
        self.assertEqual(orphans, [], f"{orphans} is in {_REL}/ and named by no row "
                                      "in CLAUDE.md — findable only by somebody "
                                      "already listing the directory")


if __name__ == "__main__":
    unittest.main()
