"""The base requirements must be installable by anyone, without credentials.

A private ``git+https://`` dependency in ``requirements.txt`` fails for every
CI runner and every new developer who lacks access to that repository -- and it
fails at ``pip install``, before any of the graceful-degradation code that
makes the dependency optional in the first place ever gets to run. That
happened once; this keeps it from happening again.
"""

import ast
import os
import re
import unittest

from tests import _workflow

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lines(name):
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as fh:
        return [ln.strip() for ln in fh
                if ln.strip() and not ln.strip().startswith("#")]


class TestRequirements(unittest.TestCase):
    def test_base_requirements_need_no_credentials(self):
        for line in _lines("requirements.txt"):
            self.assertNotIn("git+", line,
                             "requirements.txt must install without repository "
                             "credentials; put VCS dependencies in "
                             "requirements-drc.txt (see CI.md)")

    def test_the_rule_library_is_still_declared_somewhere(self):
        # Optional is not the same as forgotten: dropping it from both files
        # would leave nothing telling anyone how to install it.
        self.assertTrue(any("pydrc" in ln.lower()
                            for ln in _lines("requirements-drc.txt")))

    def test_every_app_import_is_covered_by_the_base_requirements(self):
        # The app must start with only requirements.txt installed, so nothing
        # imported at module scope may live in the optional file.
        base = " ".join(_lines("requirements.txt")).lower()
        for dist in ("pyside6", "pymupdf", "pillow"):
            self.assertIn(dist, base)

    def test_the_suites_workflow_reader_is_covered_by_the_base_requirements(self):
        """PyYAML is in `requirements.txt` for the suite, not for the app.

        `pyyaml` sat in the tuple above, which names app imports, and no module
        under `app/` imports `yaml` (measured 2026-11-01). `tests/_workflow.py`
        does, and the suite reads both workflows through it, so the line is
        held to that import. Read with `ast`, so a docstring that names yaml
        cannot stand in for the import. The comment above the line names the
        module, so when the import goes, this fails and says to rewrite it.
        """
        path = os.path.join(HERE, "tests", "_workflow.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertIn("yaml", imported, (
            "tests/_workflow.py no longer imports yaml, so the reason the "
            "comment above PyYAML in requirements.txt gives is gone. Rewrite "
            "that comment, or drop the line."))
        self.assertIn("pyyaml", " ".join(_lines("requirements.txt")).lower())
        with open(os.path.join(HERE, "requirements.txt"), encoding="utf-8") as fh:
            self.assertIn("tests/_workflow.py", fh.read(),
                          "requirements.txt no longer says why it carries PyYAML")


class TestTheRuleLibrarysAccountIsNotStale(unittest.TestCase):
    """`requirements-drc.txt` names PyDRC's ACCOUNT, and pip has no expression.

    The two workflows that install the same library derive it —
    `${{ github.repository_owner }}` is whoever owns the repo the run belongs
    to, and PyDRC moves accounts alongside this repository. A requirements file
    is static text and cannot, so it carries a literal.

    **A repo RENAME leaves a redirect that `pip install git+` follows; a repo
    recreated FRESH under another account leaves none.** So the literal would go
    stale silently for every developer running the documented
    `pip install -r requirements-drc.txt` — the install fails, and the failure
    reads as a credentials problem, which is exactly what that file's own header
    tells you to suspect.

    So it is checked against **this checkout's own origin remote**, which is the
    one thing here that knows the account. The day the repo moves this fails and
    names the single line to edit, which is strictly better than a checklist
    item somebody has to remember on a day with a great deal else going on.
    """

    def _origin_owner(self):
        import subprocess
        try:
            url = subprocess.run(
                ["git", "-C", HERE, "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
            self.skipTest(f"cannot run git to read the origin remote: {exc}")
        m = re.search(r"[/:]([^/]+)/[^/]+?(?:\.git)?$", url)
        if not m:
            # Three states, never two: a tarball or a checkout with no remote
            # is not the same as a stale account, and reporting the first as
            # the second sends somebody editing a line that is correct.
            self.skipTest(
                f"no GitHub origin remote to read the account from (got {url!r})")
        return m.group(1)

    def test_the_declared_account_is_the_one_this_checkout_belongs_to(self):
        want = self._origin_owner()
        for line in _lines("requirements-drc.txt"):
            for m in re.finditer(r"github\.com/([^/]+)/", line):
                self.assertEqual(
                    m.group(1), want,
                    f"requirements-drc.txt installs from {m.group(1)}/ while "
                    f"this checkout belongs to {want}/. PyDRC moves accounts "
                    "with this repository and a fresh repo gets NO redirect, "
                    "so `pip install -r requirements-drc.txt` 404s and reads "
                    "as a credentials failure. Edit the one line.")

    def test_the_workflows_do_not_write_the_account_down_at_all(self):
        """They can derive it, so a literal there is a second copy that drifts."""
        for name in ("build-windows.yml", "tests.yml"):
            path = os.path.join(HERE, ".github", "workflows", name)
            with open(path, encoding="utf-8") as fh:
                # Comments are prose, and the paragraph above the install step
                # in tests.yml necessarily names the library it installs -- the
                # gate-fired-by-its-own-explanation trap. Tighten, never waive.
                code = "\n".join(ln for ln in fh.read().splitlines()
                                 if not ln.lstrip().startswith("#"))
            for m in re.finditer(r"github\.com/([^/$][^/]*)/PyDRC", code):
                self.fail(
                    f"{name} installs PyDRC from a written-down account "
                    f"({m.group(1)}); use "
                    "`github.com/${{ github.repository_owner }}/PyDRC`, which "
                    "is right before an account move and after one")

    def test_the_gate_can_actually_fire(self):
        """Both halves, on constructed lines, because both fire zero times today.

        The requirements half is live only on the day of a move and the
        workflow half is live only if somebody rewrites a derivation back to a
        literal, so neither can be floored against the tree as it stands.
        """
        pat = re.compile(r"github\.com/([^/$][^/]*)/PyDRC")
        self.assertTrue(pat.search(
            'pip install "pydrc @ git+https://github.com/some-org/PyDRC@main"'))
        self.assertIsNone(pat.search(
            'url="https://github.com/${{ github.repository_owner }}/PyDRC"'))
        self.assertEqual(
            re.search(r"[/:]([^/]+)/[^/]+?(?:\.git)?$",
                      "git@github.com:some-org/Redline.git").group(1),
            "some-org", "the origin-remote reader no longer parses an ssh url")


class TestTheReproducibilityClaimMatchesThePinning(unittest.TestCase):
    """`packaging/pydrc-ref.txt` said rebuilding a tag years later produces the
    same installer. It pins **one dependency of ten**.

    The rule library is genuinely pinned and resolved to a SHA before it is
    installed, which is what makes *"which rules does this installer contain"*
    answerable — the question that file exists for. Everything else is an
    unbounded `>=` floor, including the PDF engine and the whole GUI toolkit,
    so a rebuild resolves each to whatever is newest that day.

    Neither half is checked by anything else, and this is a **claim about the
    artifact** rather than about the rules, which is what made it worth
    correcting rather than shrugging at: somebody reproducing a finding from a
    year-old release reads that sentence and stops looking.

    Gated in BOTH directions on purpose. The strong sentence is refused while a
    floor remains; the narrow one is refused once they are all pinned, because
    a file that undersells a guarantee the build now gives is the same drift
    pointing the other way — and it is the one a person adding a lock file
    would otherwise have no reason to come back and fix.
    """

    #: The sentence that cannot be supported by one pin, and the correction.
    #: Matched on the words that MAKE the claim rather than on "reproducible"
    #: anywhere in the file — the correction necessarily discusses reproducing
    #: an installer, so a looser check would fire on the text explaining the
    #: defect, which is the dead gate this repo already pays for elsewhere.
    _STRONG = "produces the same installer"
    _NARROW = "PINS ONE DEPENDENCY OF TEN"

    def _ref_file(self):
        with open(os.path.join(HERE, "packaging", "pydrc-ref.txt"),
                  encoding="utf-8") as fh:
            return fh.read()

    def _unquoted(self):
        """The file with quoted text removed.

        The correction QUOTES the sentence it retracts, deliberately — the
        history is what stops it being written back — so this check fired on
        its own fix the first time it ran. The standing answer in this family
        is to tighten the check rather than waive the text explaining the
        defect: what is refused is the sentence made *as a claim*, and it may
        appear inside quotation marks and nowhere else.
        """
        return re.sub(r'"[^"]*"', "", self._ref_file())

    def _floors(self):
        """Requirements that name a lower bound and no upper one."""
        out = []
        for name in ("requirements.txt",
                     os.path.join("packaging", "requirements-build.txt")):
            for line in _lines(name):
                if "git+" in line or "@" in line:
                    continue          # the SHA-resolved one; pinned elsewhere
                if ">=" in line and "==" not in line and "<" not in line:
                    out.append(line)
        return out

    def test_the_sweep_finds_requirements_to_judge(self):
        """The floor. With no requirement lines found, every assertion below is
        satisfied by a repository that declares nothing — which is what a
        rename of either file degrades to, and it reads exactly like a project
        that has pinned everything."""
        self.assertGreaterEqual(
            len(_lines("requirements.txt")), 5,
            "requirements.txt returned almost nothing — re-aim this gate")

    def test_the_claim_does_not_outrun_the_pinning(self):
        floors, text = self._floors(), self._unquoted()
        if floors:
            self.assertNotIn(self._STRONG, text, (
                f"packaging/pydrc-ref.txt claims a rebuild {self._STRONG!r} "
                f"while {len(floors)} requirement(s) are unbounded floors: "
                f"{floors}. One pin cannot carry a claim about the artifact."))
            self.assertIn(self._NARROW, text, (
                "the unbounded floors are still there and the file no longer "
                "says so — a reader is owed the scope of what the pin buys."))
        else:
            self.assertIn(self._STRONG, text, (
                "every requirement is pinned now, so the file understates what "
                "a rebuild gives. Restore the strong claim."))

    def test_the_retraction_is_actually_QUOTED_so_that_check_is_not_vacuous(self):
        """Without the quotation the check above passes over a file that simply
        never mentions the subject — a different document from one that says
        what changed and why, and the one a rewrite would drift back into."""
        self.assertIn(f'"...and rebuilding that tag years later {self._STRONG}"',
                      self._ref_file(),
                      "the retracted sentence is no longer quoted, so the "
                      "unquoted-claim check has nothing to distinguish")

    def test_the_ref_file_still_names_a_ref_after_all_that_prose(self):
        """The comments are stripped by the workflow with `grep -v '^\\s*#'`
        and the first surviving line is installed, so a comment block that
        swallowed the value would resolve to nothing — which that step fails
        loudly on, but only on a runner, at release time."""
        body = [ln for ln in self._ref_file().splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        self.assertTrue(body, "packaging/pydrc-ref.txt names no ref at all")
        self.assertNotIn(" ", body[0].strip(),
                         f"the first non-comment line is not a git ref: {body[0]!r}")


class TestVersionIsStatedOnce(unittest.TestCase):
    """The installer carries its own copy of the version, and it must agree.

    `app/__init__.py` is what the About box and the audit report show;
    `packaging/installer.iss` is what names the setup executable and what
    Windows records in Add/Remove Programs. They are two files, so they drift
    -- the installer sat at 1.4.0 while the app moved on, which would have
    shipped `DSI_Redline_Setup_1.4.0.exe` containing 1.5.0.

    A release is tagged `vX.Y.Z` and the tag triggers the build, so a third
    copy of the number lives in the tag. This test cannot see that one; it can
    at least stop the two in the tree disagreeing.
    """

    def _installer_version(self):
        import re
        path = os.path.join(HERE, "packaging", "installer.iss")
        with open(path, encoding="utf-8", errors="replace") as fh:
            m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', fh.read())
        self.assertIsNotNone(m, "installer.iss no longer defines MyAppVersion")
        return m.group(1)

    def test_the_installer_and_the_app_agree(self):
        from app import __version__
        self.assertEqual(
            self._installer_version(), __version__,
            "packaging/installer.iss and app/__init__.py disagree about the "
            "version; bump both in the same commit.")

    def test_the_changelog_documents_the_current_version(self):
        from app import __version__
        path = os.path.join(HERE, "CHANGELOG.md")
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        self.assertIn(f"## v{__version__}", text,
                      f"CHANGELOG.md has no section for v{__version__}; the "
                      "changelog is the release notes for the tag.")


class TestTheInterpreterClaimIsExercised(unittest.TestCase):
    """"Python 3.11+" is a claim to contributors, and only 3.11 was ever run.

    `CONTRIBUTING.md` and `README.md` both say 3.11+. The CI matrix varied only
    the operating system and pinned `python-version: "3.11"` on both runners,
    so 3.12 and 3.13 -- increasingly the default on a fresh machine -- were
    advertised and never checked.

    The frozen Windows build pins its own interpreter, so a shipped installer
    is unaffected. What this is about is **running from source**, which the
    README documents as a first-class way to use the app, against a suite that
    heavily exercises PySide6 and PyMuPDF.

    This said "Parsed by hand rather than with PyYAML, which this project does
    not depend on". `requirements.txt` has declared `PyYAML>=6.0` since
    `d01d62b`, so the reason was false. The hand reading was regexes over the
    file with comment lines dropped, and it took the first `python-version:`
    list in the file whatever job held it. It reads through
    `tests/_workflow.py` now: the matrix of the job named `TEST_JOB`, each
    `actions/setup-python` step's own `with:`, and `uses:` only where GitHub
    reads one. The loader discards comments, which is what the old reader
    stripped them for, because the comment explaining this defect names the
    versions the check is hunting for. The one raw-text read left is the
    frozen build's stated reason, because that reason IS a comment.
    """

    #: The job that runs the suite across interpreters. Named rather than
    #: searched for, as `TestThePyMuPDFFloorIsExercised.JOB` is.
    TEST_JOB = "test"

    def _jobs(self, name):
        return _workflow.load(
            os.path.join(HERE, ".github", "workflows", name))["jobs"]

    def _declared_minimum(self):
        """The lowest version the documentation promises."""
        import re
        found = set()
        for doc in ("CONTRIBUTING.md", "README.md"):
            with open(os.path.join(HERE, doc), encoding="utf-8") as fh:
                found |= set(re.findall(r"Python \*{0,2}(\d+\.\d+)\+", fh.read()))
        self.assertTrue(found, "no document states a Python version any more")
        self.assertEqual(len(found), 1,
                         f"the documents promise different minimums: {found}")
        return next(iter(found))

    def test_the_test_matrix_covers_the_version_the_docs_promise(self):
        jobs = self._jobs("tests.yml")
        self.assertIn(self.TEST_JOB, jobs,
                      f"tests.yml has no `{self.TEST_JOB}` job; re-aim TEST_JOB")
        matrix = ((jobs[self.TEST_JOB] or {}).get("strategy") or {}).get("matrix") or {}
        listed = matrix.get("python-version")
        self.assertIsInstance(
            listed, list,
            f"tests.yml's `{self.TEST_JOB}` job no longer varies python-version; "
            "the docs promise a range and a single pin cannot check one")
        # str() of what YAML read, which is what GitHub hands setup-python: an
        # unquoted 3.10 is the number 3.1 to both, and must not pass as 3.10.
        versions = [str(v) for v in listed]
        self.assertIn(self._declared_minimum(), versions,
                      "the matrix does not include the minimum the docs promise")
        self.assertGreater(
            len(versions), 1,
            "the matrix names one version, so '3.11+' is still unchecked above "
            "the floor")

    def test_the_frozen_build_stays_pinned_and_says_why(self):
        """The asymmetry is deliberate; without the reason somebody 'fixes' it.

        Every `actions/setup-python` step, with a floor of one: a sweep that
        found none would agree with a build that sets up no Python at all.
        """
        pins = [((st.get("with") or {}).get("python-version"))
                for job in self._jobs("build-windows.yml").values()
                for st in (job or {}).get("steps") or []
                if str(st.get("uses", "")).startswith("actions/setup-python@")]
        self.assertTrue(pins, "build-windows.yml has no actions/setup-python step")
        for pin in pins:
            # A string, so quoted: unquoted, 3.10 reads as the number 3.1.
            self.assertIsInstance(pin, str,
                                  f"the Windows build's python-version is {pin!r}; "
                                  "quote it, or 3.10 reads as 3.1")
            self.assertRegex(pin, r"^\d+\.\d+$",
                             f"the Windows build no longer pins one interpreter: "
                             f"{pin!r}")
        # Raw text, because the reason is a YAML comment and the loader drops it.
        with open(os.path.join(HERE, ".github", "workflows", "build-windows.yml"),
                  encoding="utf-8") as fh:
            raw = fh.read()
        self.assertIn("not vary run to run", raw,
                      "the pin carries no stated reason, so it reads as the "
                      "oversight the test matrix just corrected")

    # The lowest acceptable major per first-party action: the first one running
    # on Node 24. A MINIMUM rather than a set of known-bad refs, and the
    # difference is the whole point of this table existing -- see the test below.
    MINIMUM_ACTION_MAJOR = {
        "actions/checkout": 5,
        "actions/setup-python": 6,
        "actions/setup-node": 5,
        "actions/upload-artifact": 5,
        "actions/download-artifact": 5,
        "actions/cache": 5,
    }

    def _action_pins(self):
        """Every `uses:` ref in every workflow, with where it was found.

        `.yaml` as well as `.yml`: a glob that matches neither spelling returns
        nothing, and a sweep over nothing reports no offenders. That is the
        vacuous pass the floor assertion below exists to refuse.

        A job's own `uses:` (a reusable workflow) and each step's, which are
        the two places GitHub reads one. The loader drops comments, so a
        commented-out step and a comment naming a stale ref cannot be read as
        pins, and `uses:` inside a `run:` script is text, not a pin.
        """
        import glob
        pins = []
        for path in sorted(
                glob.glob(os.path.join(HERE, ".github", "workflows", "*.yml"))
                + glob.glob(os.path.join(HERE, ".github", "workflows", "*.yaml"))):
            name = os.path.basename(path)
            for job in _workflow.load(path)["jobs"].values():
                job = job or {}
                refs = [job.get("uses")] + [st.get("uses")
                                            for st in job.get("steps") or []
                                            if isinstance(st, dict)]
                pins.extend((name, ref) for ref in refs if ref)
        return pins

    def test_every_first_party_action_pin_is_at_or_above_its_minimum(self):
        """A MINIMUM, not a list of the refs that were stale when this was written.

        GitHub is force-running Node-20 actions on Node 24 and the forcing is
        temporary. When it ends, a workflow pinned below stops working -- and
        for this repository that is the Windows build, the only path that
        produces the installer.

        THIS REPLACED A SET-MEMBERSHIP CHECK, and the replacement is the point.
        The first version compared each ref against `{checkout@v4,
        setup-python@v5, upload-artifact@v4}` -- the three that were stale the
        day it was written. That is a list of past injuries rather than a rule:
        blind to `setup-node@v4`, blind to an older `@v3` or `@v2`, and blind to
        the next deprecation, which is the one nobody is watching for. A gate
        built from what went wrong last time only ever catches last time.

        Scope: this repository. The same defect was portfolio-wide -- ten of
        fourteen repos on 2026-08-30, every one of them green -- and no single
        repo's CI can see that, so the cross-repo sweep is
        `Pathforward/scripts/action_majors.py` rather than eleven copies of
        this.
        """
        import re
        pins = self._action_pins()
        self.assertGreaterEqual(
            len(pins), 6,
            "the sweep found almost no `uses:` pins, so an empty result below "
            "would mean the glob missed the workflows rather than that they are "
            "current")

        stale, undescribed = [], []
        for name, ref in pins:
            if not ref.startswith("actions/"):
                # Third party. Nothing here knows which major of somebody
                # else's action runs on a current runtime, and inventing a
                # minimum would be a claim with nothing behind it.
                continue
            m = re.match(r"([^@]+)@v(\d+)$", ref)
            if not m:
                continue  # a SHA or branch pin: the stronger choice, not a stale one
            action, major = m.group(1), int(m.group(2))
            if action not in self.MINIMUM_ACTION_MAJOR:
                undescribed.append(f"{name}: {ref}")
            elif major < self.MINIMUM_ACTION_MAJOR[action]:
                stale.append(f"{name}: {ref}")

        self.assertEqual(stale, [],
                         "an action major below its minimum is pinned: "
                         + str(stale))
        self.assertEqual(
            undescribed, [],
            "a first-party action has no minimum major recorded, so nothing "
            "judged it -- add it to MINIMUM_ACTION_MAJOR with the first major "
            "on a current runtime: " + str(undescribed))


class TestThePyMuPDFFloorIsExercised(unittest.TestCase):
    """`requirements.txt` declares a PyMuPDF floor, and a CI job installs it.

    It said `PyMuPDF>=1.25` while the suite failed at 1.25.0 (measured
    2026-10-31): `test_export_writes_freetext_with_leader` and
    `test_printing_applies_the_line_weight_floor`, both green at 1.25.4.
    Nothing ran the floor. A fresh install takes the newest PyMuPDF and
    pdf2docx 0.5.13 requires 1.26.7, so every runner sat well above it, and
    only an install that honored the floor met the two failures.

    The `pymupdf-floor` job in `tests.yml` installs `PYMUPDF_FLOOR` as a
    constraint and runs the suite. This holds that pin to the floor in both
    directions, the way `TestTheInterpreterClaimIsExercised` holds the matrix
    to the documented interpreter. Read with comments stripped, because the
    comments in both files explain the floor and name it, and read **by job**,
    because a pin set in one job and an install in another is not a floor run.
    """

    JOB = "pymupdf-floor"

    def _floor(self):
        """The `>=` bound on the one PyMuPDF line in requirements.txt."""
        found = []
        for line in _lines("requirements.txt"):
            # The project's name, then a version specifier. pymupdf4llm and
            # pymupdf-layout are other distributions and do not match.
            m = re.match(r"pymupdf\s*([<>=!~].*)$", line, re.I)
            if m:
                found.append(m.group(1))
        self.assertEqual(len(found), 1,
                         f"requirements.txt should name PyMuPDF once, found "
                         f"{len(found)} specifier(s): {found}")
        bound = re.search(r">=\s*([0-9][^,\s;]*)", found[0])
        self.assertIsNotNone(bound, f"the PyMuPDF line has no >= floor: "
                                    f"{found[0]!r}")
        return bound.group(1)

    def _job(self):
        """The floor job's lines, comment lines dropped."""
        path = os.path.join(HERE, ".github", "workflows", "tests.yml")
        with open(path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines()
                     if not ln.lstrip().startswith("#")]
        start = next((i for i, ln in enumerate(lines)
                      if ln.rstrip() == f"  {self.JOB}:"), None)
        self.assertIsNotNone(
            start, f"tests.yml has no `{self.JOB}` job, so nothing installs "
                   "the PyMuPDF floor requirements.txt declares")
        body = []
        for ln in lines[start + 1:]:
            if ln.strip() and len(ln) - len(ln.lstrip()) <= 2:
                break  # the next job, or the end of `jobs:`
            body.append(ln)
        return "\n".join(body)

    def test_the_job_pins_the_floor_requirements_txt_declares(self):
        job = self._job()
        pins = re.findall(r'^\s+PYMUPDF_FLOOR:\s*"?([^"\s]+)"?\s*$', job, re.M)
        self.assertEqual(len(pins), 1,
                         f"the {self.JOB} job should set PYMUPDF_FLOOR once, "
                         f"found {pins}")
        floor = self._floor()
        self.assertEqual(
            pins[0], floor,
            f"requirements.txt declares PyMuPDF>={floor} and the {self.JOB} "
            f"job installs {pins[0]}. Move both in the same commit, and "
            "re-measure the release you move to.")

    def test_the_job_installs_the_pin_and_runs_the_suite(self):
        """A pin that nothing installs agrees with the floor and runs nothing.

        Each one has to BEGIN a line. The job echoes the command it runs, so
        a substring check passed with the `python tools/run_tests.py` line
        deleted: the echo above it still held the words (falsified on this
        test's first draft, 2026-10-31).
        """
        commands = [ln.strip() for ln in self._job().splitlines()]
        for command, why in (
            ('echo "PyMuPDF==${PYMUPDF_FLOOR}" > ',
             "the pin is no longer written out as an exact constraint"),
            ("pip install -r requirements.txt -c ",
             "requirements.txt is no longer installed under the constraint"),
            ('test "$installed" = "$PYMUPDF_FLOOR"',
             "nothing confirms that the installed PyMuPDF is the pin"),
            ('ARGS="--strict"',
             "the floor run no longer fails when Qt is missing"),
            ("python tools/run_tests.py $ARGS",
             "the job no longer runs the suite"),
        ):
            self.assertTrue(any(c.startswith(command) for c in commands),
                            f"{self.JOB}: {why} (no line begins {command!r})")


if __name__ == "__main__":
    unittest.main()
