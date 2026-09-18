"""The test runner's own skip attribution, and the gate over it.

It has been wrong three times: once counting every skip against the design
rule library when most were Qt; once failing a run whose Qt was fine because a
compound reason named PySide6 alongside PyDRC; and once -- for as long as the
Tests workflow existed -- telling every CI run that the rule library was
absent when the library was installed and **ezdxf** was the thing missing,
because the workflow installed `pydrc` without its `[dxf]` extra.

The third is why `classify` is no longer the last word. It reads a reason
string and a compound reason forces it to pick; `missing_optional()` asks the
interpreter, which cannot be wrong about what it can import.
"""

import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "run_tests", os.path.join(HERE, "tools", "run_tests.py"))
run_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_tests)


def _run_script(step_name: str) -> str:
    """The `run:` block of the named step in the Tests workflow.

    Hand-parsed rather than via PyYAML, which is not a dependency of this
    repository. What matters is that it returns the SCRIPT and not the whole
    file -- see the docstring on the test that needed it.
    """
    wf = os.path.join(HERE, ".github", "workflows", "tests.yml")
    with open(wf, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    try:
        i = next(n for n, ln in enumerate(lines)
                 if ln.strip() == f"- name: {step_name}")
    except StopIteration:
        raise AssertionError(f"no step named {step_name!r} in {wf}")
    out, in_run, indent = [], False, None
    for ln in lines[i + 1:]:
        if ln.strip().startswith("- name:"):
            break
        if not in_run:
            if ln.strip().startswith("run:"):
                in_run = True
                rest = ln.split("run:", 1)[1].strip()
                if rest and rest != "|":
                    out.append(rest)
            continue
        if not ln.strip():
            out.append("")
            continue
        lead = len(ln) - len(ln.lstrip())
        if indent is None:
            indent = lead
        if lead < indent:
            break
        out.append(ln[indent:])
    return "\n".join(out)


class TestClassify(unittest.TestCase):
    def test_splits_the_two_causes(self):
        drc, qt = run_tests.classify(
            {"PyDRC is not installed": 15, "PySide6 not available": 47})
        self.assertEqual((drc, qt), (15, 47))

    def test_a_reason_naming_both_counts_against_the_rule_library(self):
        # Qt is installed by both workflows, so attributing this to Qt fails a
        # run that is working exactly as intended when no token is configured.
        drc, qt = run_tests.classify({"needs PySide6 and PyDRC": 2})
        self.assertEqual((drc, qt), (2, 0))

    def test_ezdxf_and_pydrc_is_a_rule_library_skip(self):
        # Still attributed to the rule library, because from the STRING alone
        # that is the better guess. What changed is that the banner no longer
        # stops there -- see TestMissingOptional.
        drc, qt = run_tests.classify({"needs ezdxf and pydrc": 5})
        self.assertEqual((drc, qt), (5, 0))

    def test_unrelated_reasons_count_as_neither(self):
        drc, qt = run_tests.classify({"needs a display": 3})
        self.assertEqual((drc, qt), (0, 0))

    def test_nothing_skipped(self):
        self.assertEqual(run_tests.classify({}), (0, 0))


class TestMissingOptional(unittest.TestCase):
    """The measured answer, which is what the banner should print.

    `classify` guesses from a reason string; this imports. The distinction
    cost five tests that never ran in CI while every run announced the wrong
    cause and passed.
    """

    def test_it_names_only_what_cannot_be_imported(self):
        absent = dict(run_tests.missing_optional())
        for mod in absent:
            with self.subTest(mod):
                with self.assertRaises(Exception):
                    __import__(mod)
        for mod in run_tests._OPTIONAL:
            if mod in absent:
                continue
            with self.subTest(mod):
                __import__(mod)   # must not raise: it was reported present

    def test_every_optional_library_is_described(self):
        # The description is what a reader sees instead of "the design rule
        # library" when the absent thing is ezdxf.
        for mod, described in run_tests._OPTIONAL.items():
            with self.subTest(mod):
                self.assertTrue(described.strip(), f"{mod} has no description")
                self.assertNotEqual(described, mod)

    def test_the_dxf_extra_is_what_the_workflow_installs(self):
        """The one-word regression that hid for the life of the workflow.

        `requirements-drc.txt` installs `pydrc[dxf]`; the workflow installed
        bare `pydrc`, so ezdxf was absent on every runner and the five tests
        guarded by `HAVE_EZDXF and HAVE_PYDRC` never ran. Asserted against the
        requirements file rather than a literal, so the two cannot drift.
        """
        req = os.path.join(HERE, "requirements-drc.txt")
        with open(req, encoding="utf-8") as fh:
            spec = [ln for ln in fh if ln.strip() and not ln.startswith("#")]
        self.assertTrue(spec, "requirements-drc.txt declares nothing")
        name = spec[0].split("@")[0].strip()          # e.g. "pydrc[dxf]"
        self.assertIn("[", name, f"{name!r} names no extra; this test is stale")
        install = [
            ln for ln in _run_script("Install the design rule library (optional)").splitlines()
            if "PyDRC@main" in ln and not ln.strip().startswith("#")
        ]
        self.assertTrue(install, "the workflow no longer installs PyDRC")
        for ln in install:
            self.assertIn(
                name, ln,
                f"the workflow installs PyDRC without the extra that "
                f"requirements-drc.txt asks for ({name})",
            )

    def test_require_drc_is_passed_only_when_the_library_was_installed(self):
        """A fork with no token must still get a clean run.

        Read from the step's `run:` SCRIPT, never from the file text. The
        first draft searched the whole workflow and **passed with the flag
        deleted**, because the comment explaining why the flag exists also
        names it -- a gate satisfied by the documentation of the thing it
        exists to catch. Comment lines are stripped for the same reason.
        """
        script = _run_script("Run tests")
        code = "\n".join(
            ln for ln in script.splitlines() if not ln.strip().startswith("#")
        )
        self.assertIn("--require-drc", code, "the CI gate is gone")
        self.assertIn(
            'if [ -n "$PYDRC_TOKEN" ]', code,
            "--require-drc is no longer conditional on the token, so a fork "
            "without access would fail for a reason that is not its fault",
        )


if __name__ == "__main__":
    unittest.main()
