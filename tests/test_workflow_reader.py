"""`tests/_workflow.py` returns one step's script, or refuses.

The two hand parsers it replaced were measured against `yaml.safe_load` on
2026-11-01 over every named step in both workflows, and 5 of 40 readings
differed. Each fixture below is the shape of one difference, or of the match
the old readers made that nothing exercised: a name two jobs share answered
with the first step found.
"""

import os
import shutil
import tempfile
import textwrap
import unittest

from tests import _workflow

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TWO_JOBS = """\
jobs:
  first:
    steps:
      - name: Run tests
        run: echo first
  second:
    steps:
      - name: Run tests
        run: |
          echo second
"""

# A one-line `run:`, then the comment block the next step opens with. Both old
# readers took that comment as the script's next lines; it is how
# build-windows.yml writes "Build app (PyInstaller)".
ONE_LINE_THEN_COMMENT = """\
jobs:
  build:
    steps:
      - name: Build
        run: echo build

      # The next step explains itself here, and this is YAML, not script.
      - name: After
        run: |
          echo after
          # and this one IS script
"""


class TestTheWorkflowReader(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, text):
        path = os.path.join(self.dir, "wf.yml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(text))
        return path

    def test_a_name_two_jobs_share_is_refused_rather_than_answered_first(self):
        path = self.write(TWO_JOBS)
        with self.assertRaises(AssertionError) as cm:
            _workflow.run_script(path, "Run tests")
        self.assertIn("'first', 'second'", str(cm.exception))
        self.assertIn("job=", str(cm.exception))

    def test_job_says_which_one(self):
        path = self.write(TWO_JOBS)
        self.assertEqual(_workflow.run_script(path, "Run tests", job="first"),
                         "echo first")
        self.assertEqual(_workflow.run_script(path, "Run tests", job="second"),
                         "echo second\n")

    def test_a_one_line_run_is_the_whole_script_and_the_next_comment_is_not(self):
        path = self.write(ONE_LINE_THEN_COMMENT)
        self.assertEqual(_workflow.run_script(path, "Build"), "echo build")

    def test_a_comment_inside_a_block_is_script_and_stays(self):
        path = self.write(ONE_LINE_THEN_COMMENT)
        self.assertEqual(_workflow.run_script(path, "After"),
                         "echo after\n# and this one IS script\n")

    def test_an_absent_step_a_step_without_run_and_an_absent_job_are_refused(self):
        path = self.write("""\
            jobs:
              build:
                steps:
                  - name: Upload
                    uses: actions/upload-artifact@v5
            """)
        for call, words in (
                (lambda: _workflow.run_script(path, "Missing"), "no step named"),
                (lambda: _workflow.run_script(path, "Upload"), "no `run:` script"),
                (lambda: _workflow.run_script(path, "Upload", job="nope"),
                 "no job named")):
            with self.subTest(words=words):
                with self.assertRaises(AssertionError) as cm:
                    call()
                self.assertIn(words, str(cm.exception))

    def test_a_file_with_no_jobs_is_refused_rather_than_read_as_empty(self):
        for text in ("", "name: x\n", "jobs: {}\n", "- 1\n"):
            with self.subTest(text=text):
                with self.assertRaises(AssertionError):
                    _workflow.load(self.write(text))

    def test_the_build_windows_one_line_run_is_read(self):
        """The live case the second old reader returned '' for."""
        path = os.path.join(HERE, ".github", "workflows", "build-windows.yml")
        script = _workflow.run_script(path, "Run tests").strip()
        self.assertTrue(script.startswith("python tools/run_tests.py"), script)
        self.assertNotIn("\n", script, "a one-line `run:` came back as more")


if __name__ == "__main__":
    unittest.main()
