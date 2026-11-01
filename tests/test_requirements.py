"""The base requirements must be installable by anyone, without credentials.

A private ``git+https://`` dependency in ``requirements.txt`` fails for every
CI runner and every new developer who lacks access to that repository -- and it
fails at ``pip install``, before any of the graceful-degradation code that
makes the dependency optional in the first place ever gets to run. That
happened once; this keeps it from happening again.
"""

import os
import re
import unittest

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
        for dist in ("pyside6", "pymupdf", "pyyaml", "pillow"):
            self.assertIn(dist, base)


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

    Parsed by hand rather than with PyYAML, which this project does not depend
    on -- and read with comments stripped, because the comment explaining this
    defect necessarily names the versions the check is hunting for.
    """

    def _workflow(self, name):
        with open(os.path.join(HERE, ".github", "workflows", name),
                  encoding="utf-8") as fh:
            return "\n".join(ln for ln in fh.read().splitlines()
                              if not ln.lstrip().startswith("#"))

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
        import re
        text = self._workflow("tests.yml")
        m = re.search(r"python-version:\s*\[([^\]]+)\]", text)
        self.assertIsNotNone(
            m, "tests.yml no longer varies python-version; the docs promise a "
               "range and a single pin cannot check one")
        versions = re.findall(r"\d+\.\d+", m.group(1))
        self.assertIn(self._declared_minimum(), versions,
                      "the matrix does not include the minimum the docs promise")
        self.assertGreater(
            len(versions), 1,
            "the matrix names one version, so '3.11+' is still unchecked above "
            "the floor")

    def test_the_frozen_build_stays_pinned_and_says_why(self):
        """The asymmetry is deliberate; without the reason somebody 'fixes' it."""
        import re
        raw = open(os.path.join(HERE, ".github", "workflows",
                                "build-windows.yml"), encoding="utf-8").read()
        text = self._workflow("build-windows.yml")
        self.assertRegex(text, r'python-version:\s*"\d+\.\d+"',
                         "the Windows build no longer pins one interpreter")
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
        """
        import glob
        import re
        pins = []
        for path in sorted(
                glob.glob(os.path.join(HERE, ".github", "workflows", "*.yml"))
                + glob.glob(os.path.join(HERE, ".github", "workflows", "*.yaml"))):
            name = os.path.basename(path)
            # `_workflow` drops comment lines, so a commented-out step and a
            # comment naming a stale ref -- including the ones in this file's
            # own docstrings -- cannot be read as pins.
            for line in self._workflow(name).splitlines():
                for ref in re.findall(r"uses:\s*(\S+)", line):
                    pins.append((name, ref))
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


def _dist(name):
    """A distribution's name as pip compares it (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


class TestTheFloorsAreExercised(unittest.TestCase):
    """Every floor `requirements.txt` declares is installed by one CI job.

    The Tests matrix installs the newest release of everything, so a `>=`
    line is a claim no runner meets. `PyMuPDF>=1.25` failed two tests at
    1.25.0 (measured 2026-10-31) and `PySide6>=6.6` failed two at 6.6.0
    (measured 2026-11-01), and every run was green above them.

    The `floors` job installs `requirements.txt` under `.github/floors.txt`,
    which pins every floor at once, confirms the installed versions, and runs
    the suite. This holds that file to `requirements.txt` in BOTH directions,
    line by line: a floor with no pin is a claim nothing installs, and a pin
    with no floor is a version the job installs for no stated reason. The job
    is read with comment lines dropped, because the comments explain the
    floors and name them, and read **by job**, because a pin installed in one
    job and a suite run in another is not a floor run.
    """

    JOB = "floors"
    #: As the job's bash spells it. Read through os.path.join, because the
    #: suite also runs on Windows.
    PINS = ".github/floors.txt"

    def _declared(self):
        """``{dist: (name, floor)}``, one per line of requirements.txt."""
        out = {}
        for line in _lines("requirements.txt"):
            m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$",
                         line)
            self.assertIsNotNone(m, f"requirements.txt: unreadable {line!r}")
            bound = re.search(r">=\s*([0-9][^,\s;]*)", m.group(3))
            self.assertIsNotNone(
                bound, f"requirements.txt: {line!r} declares no >= floor, so it "
                       "claims every release works and the floor job cannot "
                       "install a lowest one")
            key = _dist(m.group(1))
            self.assertNotIn(key, out, f"requirements.txt names {m.group(1)} twice")
            out[key] = (m.group(1), bound.group(1))
        # The floor. Both directions below agree with a file that declares
        # nothing, which is what a rename of requirements.txt degrades to.
        self.assertGreaterEqual(len(out), 8, f"requirements.txt yielded {out}")
        return out

    def _pins(self):
        """``{dist: (name, version)}`` from the job's constraint file."""
        out = {}
        for line in _lines(os.path.join(*self.PINS.split("/"))):
            m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*(\S+)$", line)
            self.assertIsNotNone(
                m, f"{self.PINS}: {line!r} is not `name==version`, and only an "
                   "exact pin installs a floor")
            key = _dist(m.group(1))
            self.assertNotIn(key, out, f"{self.PINS} pins {m.group(1)} twice")
            out[key] = (m.group(1), m.group(2))
        self.assertGreaterEqual(len(out), 8, f"{self.PINS} yielded {out}")
        return out

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
                   "the floors requirements.txt declares")
        body = []
        for ln in lines[start + 1:]:
            if ln.strip() and len(ln) - len(ln.lstrip()) <= 2:
                break  # the next job, or the end of `jobs:`
            body.append(ln)
        return "\n".join(body)

    def test_every_floor_is_pinned_at_the_version_requirements_txt_declares(self):
        pins = self._pins()
        for key, (name, floor) in sorted(self._declared().items()):
            self.assertIn(
                key, pins, f"requirements.txt declares {name}>={floor} and "
                           f"{self.PINS} does not pin it, so the floor job "
                           "installs the newest release and the floor is a "
                           "claim nothing runs")
            self.assertEqual(
                pins[key][1], floor,
                f"requirements.txt declares {name}>={floor} and {self.PINS} "
                f"pins {pins[key][1]}. Move both in the same commit, and "
                "re-measure the release you move to (CI.md).")

    def test_every_pin_is_a_floor_requirements_txt_declares(self):
        declared = self._declared()
        for key, (name, version) in sorted(self._pins().items()):
            self.assertIn(
                key, declared, f"{self.PINS} pins {name}=={version}, which "
                               "requirements.txt does not declare. A transitive "
                               "pin is a version this job chose for no stated "
                               "reason, and a lowest-direct run leaves those to "
                               "the resolver.")

    def test_the_job_installs_the_pins_confirms_them_and_runs_the_suite(self):
        """A pin file nothing installs agrees with every floor and runs nothing.

        Each command has to BEGIN a line. The job echoes the command it runs,
        so a substring check passed with the `python tools/run_tests.py` line
        deleted: the echo above it still held the words (falsified on the
        PyMuPDF version of this test, 2026-10-31).
        """
        commands = [ln.strip() for ln in self._job().splitlines()]
        for command, why in (
            (f"pip install -r requirements.txt -c {self.PINS}",
             "requirements.txt is no longer installed under the pins"),
            (f'pip install -c {self.PINS} "pydrc[dxf]',
             "the rule library is no longer installed under the pins, so a "
             "PyDRC that declares a newer PyYAML would lift that floor without "
             "a word"),
            (f"python tools/check_floors.py {self.PINS}",
             "nothing confirms that the installed versions are the pins"),
            ('ARGS="--strict"',
             "the floor run no longer fails when Qt is missing"),
            ("python tools/run_tests.py $ARGS",
             "the job no longer runs the suite"),
        ):
            self.assertTrue(any(c.startswith(command) for c in commands),
                            f"{self.JOB}: {why} (no line begins {command!r})")

    def test_the_job_runs_the_interpreter_the_documents_promise(self):
        """Some floors have no wheel on a newer interpreter: PyYAML 6.0
        publishes them up to Python 3.11 and Pillow 10.0.0 up to 3.12. The
        floors are a claim about the minimum the documents promise, so that is
        where they are installed."""
        found = set()
        for doc in ("CONTRIBUTING.md", "README.md"):
            with open(os.path.join(HERE, doc), encoding="utf-8") as fh:
                found |= set(re.findall(r"Python \*{0,2}(\d+\.\d+)\+", fh.read()))
        self.assertEqual(len(found), 1, f"the documents promise {found}")
        pins = re.findall(r'python-version:\s*"([^"]+)"', self._job())
        self.assertEqual(pins, [next(iter(found))],
                         f"the {self.JOB} job runs {pins}, not the "
                         f"Python {next(iter(found))}+ the documents promise")


class TestCheckFloors(unittest.TestCase):
    """`tools/check_floors.py` is the floor job's oracle, so it is tested here
    rather than trusted: a check that reported every pin installed over an
    empty file would let a job that installed nothing pass as a floor run."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_floors", os.path.join(HERE, "tools", "check_floors.py"))
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def _main(self, text):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "floors.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.tool.main([path])
        return code, out.getvalue()

    def test_a_release_compares_as_pep_440_compares_it(self):
        r = self.tool.release
        self.assertEqual(r("6.6"), r("6.6.0"))
        self.assertNotEqual(r("1.25.4"), r("1.25.40"))
        self.assertNotEqual(r("6.0"), r("6.0.1"))
        self.assertIsNone(r("6.0.1rc1"), "a pre-release is not the floor")

    def test_three_outcomes_are_told_apart(self):
        from importlib import metadata
        installed = {"a": "1.2.0", "b": "2.0"}

        def version_of(name):
            if name not in installed:
                raise metadata.PackageNotFoundError(name)
            return installed[name]

        at, elsewhere, absent = self.tool.check(
            [("a", "1.2"), ("b", "1.9"), ("c", "3.0")], version_of)
        self.assertEqual((len(at), len(elsewhere), len(absent)), (1, 1, 1))

    def test_an_empty_file_is_refused_rather_than_reported_clean(self):
        code, out = self._main("# every pin was deleted\n\n")
        self.assertEqual(code, 2, out)
        self.assertIn("names no pin", out)

    def test_a_line_it_cannot_read_is_refused(self):
        code, out = self._main("PySide6>=6.6\n")
        self.assertEqual(code, 2, out)

    def test_a_pin_not_installed_fails(self):
        code, out = self._main("no-such-distribution-here==1.0\n")
        self.assertEqual(code, 1, out)
        self.assertIn("1 not installed", out)

    def test_it_reads_every_pin_in_the_job_s_file(self):
        """The tool and the gate parse the same file separately. This asserts
        the tool reads every line the gate does, so the job cannot confirm a
        subset of the pins and report the rest as checked."""
        rel = os.path.join(*TestTheFloorsAreExercised.PINS.split("/"))
        with open(os.path.join(HERE, rel), encoding="utf-8") as fh:
            pins, unreadable = self.tool.read_pins(fh.read())
        self.assertEqual(unreadable, [])
        self.assertGreaterEqual(len(pins), 8)
        self.assertEqual(len(pins), len(_lines(rel)))


if __name__ == "__main__":
    unittest.main()
