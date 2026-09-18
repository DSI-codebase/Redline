"""Without PySide6 the suite SKIPS. It must never ERROR.

`CONTRIBUTING.md` calls a machine without Qt's system libraries "not a failure",
and `CLAUDE.md` records the exact shape: `import PySide6.QtGui` dies with
`libEGL.so.1: cannot open shared object file`. Seven modules did not honour that
-- they errored -- and an error on a missing OPTIONAL input reads as a broken
checkout, which is what a new contributor sees before they have installed
anything.

Measured when it was found: test_cli_open (6 errors), test_crop_tags, test_help,
test_region_export, test_v12_author, test_v12_recent, test_v14_search, against
28 sibling modules that skipped cleanly. Two different shapes with one cause --
three died at module scope importing `app.config` / `app.help`, and four died
inside a test importing `main`, `app.tools.wizards` or `app.viewer.command_stack`
-- and in every case Qt arrived THROUGH `app.*` rather than from the direct
`PySide6` import those modules were guarding.

THIS SWEEPS THE ARTIFACT, NOT A LIST. A gate naming those seven covers what was
broken the day it was written; the eighth module to reach Qt through a new
`app.*` import has to fail here instead. That is the same argument
`test_suite_is_discoverable.py` already makes one file over.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The blocker refuses PySide6 and nothing else -- measured to be the single
# cause of all seven failures, so a wider block would prove less, not more.
_BLOCKER = textwrap.dedent("""
    import sys
    class _NoQt:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "PySide6":
                raise ImportError("PySide6 blocked by the degradation gate")
    sys.meta_path.insert(0, _NoQt())
""")


def _run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + textwrap.dedent(body)],
        cwd=ROOT, capture_output=True, text=True, timeout=900)


class TestTheBlockerIsLive(unittest.TestCase):
    """Falsify the instrument before believing anything it says.

    Every assertion below is vacuous over a blocker that does not block, and
    "the sweep found no errors" is exactly what that looks like.
    """

    def test_pyside6_really_is_unimportable_under_it(self):
        r = _run("""
            try:
                import PySide6
                print("NOT BLOCKED")
            except ImportError:
                print("BLOCKED")
        """)
        self.assertIn("BLOCKED", r.stdout)
        self.assertNotIn("NOT BLOCKED", r.stdout)

    def test_without_it_pyside6_imports_here(self):
        """If Qt is absent from this machine anyway, the sweep proves nothing."""
        r = subprocess.run([sys.executable, "-c", "import PySide6; print('OK')"],
                           cwd=ROOT, capture_output=True, text=True)
        if "OK" not in r.stdout:
            self.skipTest("PySide6 is not installed here, so blocking it is not "
                          "a controlled experiment — install it to run this gate")


class TestEveryModuleSkipsRatherThanErrors(unittest.TestCase):
    def test_no_module_errors_without_qt(self):
        r = _run(f"""
            import unittest, pathlib, json, io
            root = pathlib.Path({str(ROOT)!r})
            mods = sorted(p.stem for p in (root / "tests").glob("test_*.py"))
            mods = [m for m in mods if m != {Path(__file__).stem!r}]
            bad, skips, ran = [], 0, 0
            for m in mods:
                try:
                    suite = unittest.TestLoader().loadTestsFromName("tests." + m)
                except Exception as exc:
                    bad.append((m, "failed to LOAD: %s" % exc))
                    continue
                res = unittest.TextTestRunner(
                    verbosity=0, stream=io.StringIO()).run(suite)
                ran += res.testsRun
                skips += len(res.skipped)
                for t, tb in res.errors:
                    bad.append((m, "%s: %s" % (t, tb.strip().splitlines()[-1])))
            print(json.dumps({{"bad": bad, "skips": skips, "modules": len(mods)}}))
        """)
        self.assertEqual(
            r.returncode, 0,
            # NOT {{...}} -- this f-string is the TEST's, not the generated
            # subprocess source's. Doubling the braces here printed the
            # literal text `{r.stderr[-3000:]}` instead of the traceback,
            # so the one message written to explain a dead sweep explained
            # nothing, and the CI log carried no cause at all.
            f"the sweep itself died:\n{r.stderr[-3000:]}")
        payload = json.loads(r.stdout.strip().splitlines()[-1])

        self.assertEqual(
            payload["bad"], [],
            "these modules ERROR rather than skip without PySide6 — a missing "
            "optional dependency reading as a broken repo:\n  "
            + "\n  ".join(f"{m}: {why}" for m, why in payload["bad"]))

        # Without this the check passes over a sweep that silently ran nothing.
        self.assertGreater(payload["modules"], 40,
                           "the sweep found almost no modules — it is not "
                           "looking where the tests are")
        self.assertGreater(payload["skips"], 0,
                           "nothing skipped, so Qt was evidently still "
                           "reachable and this proves nothing")


if __name__ == "__main__":
    unittest.main()
