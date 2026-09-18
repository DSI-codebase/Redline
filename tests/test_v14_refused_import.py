"""A stored import that will not load must not be reported as a clean drawing.

The imported source drawings live in the sidecar as JSON. When that blob would
not parse, ``run_audit`` abandoned the whole run and returned an ``AuditRun``
with nothing in it -- so the panel header read **"Nothing to check."**, the
report listed no findings, and the reason sat in ``AuditRun.errors``, which the
panel and all three exports displayed nowhere.

Measured on the demo drawing: 29 findings and 1048 eligible checks thrown away
because a *separate* stored blob was corrupt, and the result presented as the
one sentence the coverage accounting exists to prevent.
"""

import json
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app import audit
from app.audit.findings import AuditRun, Coverage, Finding, DEFINITE
from app.export import audit_export

HAVE_PYDRC = audit.available()
needs_pydrc = unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")

W, H = 792.0, 1224.0

BAD_IMPORTS = {
    "not JSON at all": "<<corrupt>>",
    "valid JSON, wrong shape": '{"hello": "world"}',
    "an empty object": "{}",
    "truncated": '{"schema": "1.0", "sheets": [{"num',
}


def _sheet(doc, title, drawing_number, body=()):
    page = doc.new_page(width=W, height=H)
    page.insert_text((40.0, 1000.0), title, rotate=270)
    page.insert_text((70.0, 1000.0), drawing_number, rotate=270)
    for i, line in enumerate(body):
        page.insert_text((300.0, 200.0 + i * 14.0), line, rotate=270)
    page.set_rotation(270)
    return page


def _drawing(path):
    doc = fitz.open()
    _sheet(doc, "TITLE PAGE", "EL2507777-000")
    _sheet(doc, "24 VDC DISTRIBUTION", "EL2507777-400",
           body=["400010", "400020", "PB-40010"])
    _sheet(doc, "TERMINAL BLOCK LAYOUT", "EL2507777-800",
           body=["400010", "999990"])
    doc.save(path)
    doc.close()
    return path


@needs_pydrc
class TestARefusedImportStillAuditsTheDrawing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))
        doc = fitz.open(self.src)
        from app.extraction.sheet_number import resolve_document
        from app.extraction.sheet_role import detect_document_roles
        res = resolve_document(doc)
        self.labels = {k: v.label for k, v in res.items() if v.resolved}
        self.sources = {k: v.strategy for k, v in res.items()}
        self.roles = detect_document_roles(doc)
        doc.close()

    def _run(self, **kw):
        from app.audit.runner import run_audit
        return run_audit(self.src, self.labels, self.sources, self.roles, **kw)

    def test_the_plot_derived_audit_survives_a_corrupt_import(self):
        clean = self._run()
        self.assertTrue(clean.findings, "the fixture must produce findings")
        for label, blob in BAD_IMPORTS.items():
            with self.subTest(label):
                got = self._run(acade_model_json=blob)
                self.assertEqual(len(got.findings), len(clean.findings))
                self.assertEqual(got.run.eligible, clean.run.eligible)
                self.assertEqual(got.run.checked, clean.run.checked)

    def test_and_says_the_source_drawings_were_not_used(self):
        for label, blob in BAD_IMPORTS.items():
            with self.subTest(label):
                run = self._run(acade_model_json=blob).run
                self.assertTrue(run.errors)
                said = run.errors[0]
                self.assertIn("source drawings could not be read", said)
                self.assertIn("ran on the PDF alone", said)
                self.assertIn("Re-import", said)
                self.assertEqual(said, " ".join(said.split()),
                                 "one line: the panel header is one line")

    def test_a_run_with_no_import_records_nothing(self):
        self.assertEqual(self._run().run.errors, [])

    def test_a_failed_merge_is_a_hard_stop(self):
        """The other half, and it must stay a stop.

        ``merge_models`` enriches the plot-derived model in place, so a failure
        part-way through leaves a model that is neither the plot's nor the
        source's. Checking that is worse than not checking.
        """
        import pydrc.adapters.acade_dxf as A
        real = A.merge_models

        def exploding(base, acade):
            base.devices = []                  # a half-done mutation, then a fault
            raise RuntimeError("a device carried no tag")

        from pydrc.model import ModelDocument, dumps
        A.merge_models = exploding
        try:
            got = self._run(acade_model_json=dumps(ModelDocument()))
        finally:
            A.merge_models = real
        self.assertEqual(got.findings, [])
        self.assertTrue(got.run.blocked)
        self.assertIn("not safe to check", got.run.summary_line())


class TestTheHeaderSentence(unittest.TestCase):
    def test_a_blocked_run_never_says_nothing_to_check(self):
        run = AuditRun(errors=["The drawings could not be read."])
        self.assertTrue(run.blocked)
        self.assertNotIn("Nothing to check", run.summary_line())
        self.assertIn("could not be run", run.summary_line())
        self.assertIn("The drawings could not be read.", run.summary_line())

    def test_a_drawing_with_nothing_in_it_still_says_so(self):
        run = AuditRun()
        self.assertFalse(run.blocked)
        self.assertEqual(run.summary_line(), "Nothing to check.")

    def test_a_completed_run_that_recorded_a_problem_keeps_its_coverage_line(self):
        """A degraded run is not a blocked one: it has real coverage to state."""
        run = AuditRun(eligible=10, checked=10,
                       coverage=[Coverage(rule_id="R", eligible=10, checked=10)],
                       errors=["The source drawings could not be read."])
        self.assertFalse(run.blocked)
        self.assertEqual(run.summary_line(), "10 of 10 checked.")


class TestTheReportSaysSo(unittest.TestCase):
    """Until this, `errors` was written by the runner and read by nobody."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    class _Doc:
        path = "job.pdf"
        findings: list = []
        audit_run = None

        def waiver_for(self, key):
            return None

    def _doc(self, run, findings=()):
        d = self._Doc()
        d.findings = list(findings)
        d.audit_run = run
        return d

    def _export(self, run, ext, findings=()):
        path = os.path.join(self.tmp, f"r{ext}")
        audit_export.export_report(self._doc(run, findings), path)
        return open(path, encoding="utf-8").read()

    def _degraded(self):
        return AuditRun(eligible=10, checked=10,
                        coverage=[Coverage(rule_id="R", eligible=10, checked=10)],
                        errors=["The source drawings could not be read."])

    def test_every_format_carries_the_problem(self):
        run = self._degraded()
        finding = Finding(key="k", rule_id="R", severity=DEFINITE,
                          message="something to confirm", sheet="400")
        for ext in (".md", ".csv", ".html"):
            with self.subTest(ext):
                text = self._export(run, ext, [finding])
                self.assertIn("The source drawings could not be read.", text)

    def test_a_blocked_run_does_not_report_no_findings(self):
        """"No findings" describes a drawing that was looked at."""
        run = AuditRun(errors=["The drawings could not be read."])
        for ext, wanted in ((".md", "No findings were produced"),
                            (".html", "No findings were produced")):
            with self.subTest(ext):
                text = self._export(run, ext)
                self.assertIn(wanted, text)
                self.assertIn("did not run", text)

    def test_every_format_names_the_rule_pack(self):
        """The pack version is how a report says which rules produced it.

        It reached only the Markdown export for a long while -- so the HTML
        one, which is the format people actually keep, could not answer "which
        build was this checked against" at all.
        """
        run = AuditRun(eligible=10, checked=10, packs=["drc-base@1.32.0"],
                       coverage=[Coverage(rule_id="R", eligible=10, checked=10)])
        for ext in (".md", ".csv", ".html"):
            with self.subTest(ext):
                self.assertIn("drc-base@1.32.0", self._export(run, ext))

    def test_a_run_with_no_pack_says_nothing_rather_than_an_empty_label(self):
        # "Rule packs:" with nothing after it invites a reader to wonder what
        # was dropped.
        run = AuditRun(eligible=10, checked=10, packs=[])
        for ext in (".md", ".csv", ".html"):
            with self.subTest(ext):
                self.assertNotIn("Rule packs", self._export(run, ext))

    def test_the_advisory_note_keeps_its_first_letter(self):
        """The HTML export bolded the lead and printed the rest from a
        hand-counted offset one past the space, so every report ever exported
        opened with "Advisory review. indings identify things to confirm"."""
        text = self._export(AuditRun(), ".html")
        self.assertIn("Findings identify things to confirm", text)
        self.assertNotIn("indings identify things to confirm</div>", text)
        self.assertEqual(
            audit_export.ADVISORY,
            f"{audit_export.ADVISORY_LEAD} {audit_export.ADVISORY_BODY}")


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
