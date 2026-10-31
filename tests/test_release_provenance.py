"""A release names every rule pack it ships, not one of them.

The Windows build writes one line into the release notes saying which rules the
installer carries (`PYDRC_BUILT`). It asked PyDRC for `drc-base` by name, and
the app has run PyDRC's default packs since PyDRC 0.9.0 moved the electrical
rules into `erc-nec-2026` (`app/audit/runner.py`'s `default_packs`). So the
v1.8.0 notes read `pydrc 0.23.1 | drc-base@1.38.0 | 6360563...` for an
installer that runs `drc-base` and `erc-nec-2026` (measured on the published
release, 2026-10-31).

This runs the step's real `run:` block, as `tests/test_drc_ref_resolution.py`
does for the step before it, and holds the line it writes to PyDRC's own
`loader.DEFAULT_PACKS`: the library decides, not this file and not the
workflow's text. It needs a bash that can run a script and PyDRC, and says
which one it did not have.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from tests import test_drc_ref_resolution as R

STEP = "Report whether design rule checking is included"
HERE = R.HERE

try:
    import pydrc
    from pydrc.packs import loader
    HAVE_PYDRC = True
except Exception:                    # absent, or present and failing to load
    HAVE_PYDRC = False

# `python` is a shell FUNCTION, for the reason the sibling harness gives for
# `git` and `pip`: no directory, no PATH edit, and the same under Git bash.
_HARNESS = 'python() { "$PYEXE" "$@"; }\n'


def _drive(tmpdir):
    script = R._run_script(R.WORKFLOW, STEP)
    path = os.path.join(tmpdir, "step.sh")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_HARNESS + script)
    env_file = os.path.join(tmpdir, "env")
    env = dict(os.environ, PYEXE=sys.executable, PYDRC_TOKEN="tok",
               PYDRC_SHA="abc1234def", PYDRC_REF="v9.9.9", GITHUB_ENV=env_file,
               QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=os.pathsep.join(p for p in (HERE, os.environ.get("PYTHONPATH", ""))
                                          if p))
    r = subprocess.run([R.BASH, path], cwd=HERE, env=env, capture_output=True,
                       text=True, errors="replace")
    written = ""
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as fh:
            written = fh.read()
    return r.returncode, r.stdout + r.stderr, written


class TestTheStepAsksTheApp(unittest.TestCase):
    """Structural, on any platform: the script asks the app which packs it runs
    and names no pack itself. Comments are stripped first, because the comment
    above the line says which pack it used to name."""

    def test_it_asks_default_packs_and_names_no_pack(self):
        code = R._code_only(R._run_script(R.WORKFLOW, STEP))
        self.assertIn("default_packs()", code)
        self.assertNotIn("load_by_id('drc-base')", code)
        self.assertNotIn('load_by_id("drc-base")', code)


@unittest.skipUnless(R.BASH, "no bash here can run a script, so the step's line "
                             "was not produced")
@unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")
class TestTheLineNamesEveryDefaultPack(unittest.TestCase):

    def test_the_release_line_is_every_default_pack_with_its_version(self):
        """Injected: the step's `drc-base` lookup restored (red: one pack of
        two named)."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, written = _drive(tmp)
        self.assertEqual(rc, 0, out)
        packs = ", ".join(loader.load_by_id(p).ref for p in loader.DEFAULT_PACKS)
        self.assertGreaterEqual(len(loader.DEFAULT_PACKS), 2, loader.DEFAULT_PACKS)
        self.assertIn(f"PYDRC_BUILT=pydrc {pydrc.__version__} | {packs} | abc1234def "
                      f"(ref v9.9.9)", written)
        self.assertIn(f"Design rule checking: pydrc {pydrc.__version__}, {packs}, "
                      f"commit abc1234def (ref v9.9.9)", out)

    def test_with_no_token_the_line_says_none(self):
        """The other arm: a build without PyDRC says so rather than naming
        rules it does not carry."""
        script = R._run_script(R.WORKFLOW, STEP)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "step.sh")
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(_HARNESS + script)
            env_file = os.path.join(tmp, "env")
            env = dict(os.environ, PYDRC_TOKEN="", GITHUB_ENV=env_file)
            r = subprocess.run([R.BASH, path], cwd=HERE, env=env, capture_output=True,
                               text=True, errors="replace")
            with open(env_file, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(written.strip(), "PYDRC_BUILT=none")
        self.assertIn("Built WITHOUT design rule checking", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
