"""Exporting an audit report.

Every format carries the two things that make a finding checkable — the clause
it rests on and the facts behind it — and the coverage statement, which is not
optional in any of them. Qt-free.
"""

import os
import tempfile
import unittest

from app.audit.findings import (AuditRun, Coverage, Finding, Waiver,
                                POTENTIAL, INFO)
from app.export.audit_export import (export_csv, export_html, export_markdown,
                                     export_report)


class _Doc:
    """The little a report needs from a document."""

    def __init__(self, findings, run, waivers=None):
        self.findings = findings
        self.audit_run = run
        self.waivers = waivers or {}
        self.path = "/tmp/Demo Panel.pdf"

    def waiver_for(self, key):
        return self.waivers.get(key)


def _doc(waived=False):
    findings = [
        Finding(key="k1", rule_id="DRC-XREF-WIRE-RECIP-001", severity=POTENTIAL,
                message="Wire 400790 declares sheet 400 but appears only on 500.",
                clause="internal 2026-08 wire numbering convention",
                sheet="500", page=8, subject_id="400790", x=1.0, y=2.0,
                evidence={"declared_sheet": 400, "seen_sheets": [500]},
                status="waived" if waived else "open"),
        Finding(key="k2", rule_id="DRC-TAG-FAMILY-001", severity=INFO,
                message="Tag POT-70024 uses family code POT.",
                clause="internal 2026-08 family codes",
                sheet="700", page=11, subject_id="POT-70024", x=1.0, y=2.0),
    ]
    run = AuditRun(eligible=63, checked=47, skipped=16, packs=["drc-base@1.0.0"],
                   coverage=[Coverage(rule_id="DRC-TAG-DUP-001", eligible=63,
                                      checked=47, skipped=16,
                                      reasons={"missing catalog": 16})])
    waivers = {"k1": Waiver(key="k1", reason="Accepted by client",
                            author="LWH")} if waived else {}
    return _Doc(findings, run, waivers)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _path(self, name):
        return os.path.join(self.tmp, name)

    def _read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()


class TestMarkdown(_Base):
    def test_contains_findings_clauses_and_evidence(self):
        text = self._read(export_markdown(_doc(), self._path("r.md")))
        self.assertIn("400790", text)
        self.assertIn("wire numbering convention", text)
        self.assertIn("declared_sheet=400", text)

    def test_states_coverage(self):
        text = self._read(export_markdown(_doc(), self._path("r.md")))
        self.assertIn("47 of 63", text)
        self.assertIn("Not checked", text)
        self.assertIn("missing catalog", text)

    def test_is_advisory_not_a_verdict(self):
        text = self._read(export_markdown(_doc(), self._path("r.md"))).lower()
        self.assertIn("not a determination of compliance", text)
        for banned in ("is compliant", "passes", "certified"):
            self.assertNotIn(banned, text)

    def test_records_the_waiver_and_who_made_it(self):
        text = self._read(export_markdown(_doc(waived=True), self._path("r.md")))
        self.assertIn("Accepted by client", text)
        self.assertIn("LWH", text)
        self.assertIn("waived", text.lower())

    def test_empty_report_does_not_read_as_clean(self):
        doc = _Doc([], AuditRun(eligible=10, checked=4, skipped=6))
        text = self._read(export_markdown(doc, self._path("r.md")))
        self.assertIn("No findings", text)
        self.assertIn("coverage", text.lower())


class TestCsv(_Base):
    def test_has_a_header_and_a_row_per_finding(self):
        import csv
        path = export_csv(_doc(), self._path("r.csv"))
        with open(path, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][0], "Severity")
        self.assertIn("400790", rows[1])
        self.assertEqual(rows[1][3], "9")          # page 8, shown 1-based

    def test_coverage_is_appended(self):
        text = self._read(export_csv(_doc(), self._path("r.csv")))
        self.assertIn("Coverage", text)
        self.assertIn("47 of 63", text)


class TestHtml(_Base):
    def test_is_self_contained(self):
        text = self._read(export_html(_doc(), self._path("r.html")))
        self.assertTrue(text.startswith("<!doctype html"))
        self.assertNotIn("http", text.split("</style>")[0])

    def test_escapes_content(self):
        doc = _doc()
        doc.findings[0].message = 'Tag <script>alert("x")</script> is odd'
        text = self._read(export_html(doc, self._path("r.html")))
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_shows_coverage_table_and_the_gap(self):
        text = self._read(export_html(_doc(), self._path("r.html")))
        self.assertIn("Coverage", text)
        self.assertIn("missing catalog", text)
        self.assertIn("skipped item is not a passing item", text)

    def test_waived_findings_are_marked(self):
        text = self._read(export_html(_doc(waived=True), self._path("r.html")))
        self.assertIn("waived", text)


class TestFormatChoice(_Base):
    def test_extension_picks_the_format(self):
        self.assertTrue(self._read(export_report(_doc(), self._path("a.md")))
                        .startswith("# Design rule check"))
        self.assertIn("Severity", self._read(export_report(_doc(), self._path("a.csv"))))
        self.assertTrue(self._read(export_report(_doc(), self._path("a.html")))
                        .startswith("<!doctype html"))

    def test_unknown_extension_falls_back_to_html(self):
        self.assertTrue(self._read(export_report(_doc(), self._path("a.txt")))
                        .startswith("<!doctype html"))


def _idle_run():
    """A run where nothing was skipped but a rule had nothing to look at.

    The shape that used to read as a clean bill: DSI Redline's merge dropped
    the source-derived motor circuits, so four enabled motor rules sat at
    eligible 0 -- 344 checks, 40 of them honest skips -- and every one was
    filed under "complete" and dropped from the report.
    """
    return AuditRun(
        eligible=788, checked=788, skipped=0,
        packs=["drc-base@1.23.0"],
        coverage=[
            Coverage(rule_id="DRC-TAG-LOC-001", eligible=788, checked=788,
                     skipped=0),
            Coverage(rule_id="ERC-MOTOR-DATA-001", eligible=0, checked=0,
                     skipped=0),
            Coverage(rule_id="ERC-MOTOR-OL-001", eligible=0, checked=0,
                     skipped=0),
        ])


class TestARuleThatRanAgainstNothing(unittest.TestCase):
    """"No findings" and "could not check" must never be the same answer.

    That is the rule library's own stated invariant, and a rule with nothing
    eligible defeats it: it skips nothing, so it satisfies `complete`, and a
    report that only asks `complete` files it beside a rule that examined every
    entity and found them all sound.
    """

    def test_a_rule_with_nothing_eligible_did_not_run(self):
        self.assertFalse(Coverage(rule_id="R", eligible=0).ran)
        self.assertTrue(Coverage(rule_id="R", eligible=788, checked=788).ran)

    def test_it_is_still_complete_which_is_the_whole_problem(self):
        # `complete` keeps its meaning -- it feeds AuditRun.complete and the
        # summary line -- so the distinction is drawn with a second property
        # rather than by redefining the first.
        self.assertTrue(Coverage(rule_id="R", eligible=0).complete)

    def test_the_run_names_its_idle_rules(self):
        run = _idle_run()
        self.assertEqual([c.rule_id for c in run.idle_rules],
                         ["ERC-MOTOR-DATA-001", "ERC-MOTOR-OL-001"])
        self.assertTrue(run.complete)
        self.assertFalse(run.everything_accounted_for)

    def test_the_summary_never_says_n_of_n_while_a_rule_sat_idle(self):
        # "788 of 788 checked." is what a reviewer reads as a clean bill.
        line = _idle_run().summary_line()
        self.assertIn("788 of 788 checked", line)
        self.assertIn("2 rules had nothing to check against", line)

    def test_a_genuinely_clean_run_still_says_so(self):
        run = AuditRun(eligible=63, checked=63, skipped=0,
                       coverage=[Coverage(rule_id="R", eligible=63,
                                          checked=63, skipped=0)])
        self.assertTrue(run.everything_accounted_for)
        self.assertEqual(run.summary_line(), "63 of 63 checked.")

    def _exports(self, run):
        tmp = tempfile.mkdtemp()
        doc = _Doc(_doc().findings, run)
        return {
            "md": open(export_markdown(doc, os.path.join(tmp, "a.md")),
                       encoding="utf-8").read(),
            "csv": open(export_csv(doc, os.path.join(tmp, "a.csv")),
                        encoding="utf-8").read(),
            "html": open(export_html(doc, os.path.join(tmp, "a.html")),
                         encoding="utf-8").read(),
        }

    def test_every_export_names_the_idle_rule(self):
        out = self._exports(_idle_run())
        for fmt, text in out.items():
            with self.subTest(fmt):
                self.assertIn("ERC-MOTOR-DATA-001", text)
                self.assertIn("nothing to check against", text)

    def test_the_not_checked_section_does_not_vanish(self):
        # It was gated on `complete`, so a set whose only gap was idle rules
        # printed no coverage caveat at all.
        out = self._exports(_idle_run())
        self.assertIn("## Not checked", out["md"])
        self.assertIn("class='note'", out["html"])

    def test_a_clean_run_still_has_no_not_checked_section(self):
        run = AuditRun(eligible=63, checked=63, skipped=0,
                       coverage=[Coverage(rule_id="R", eligible=63,
                                          checked=63, skipped=0)])
        out = self._exports(run)
        self.assertNotIn("## Not checked", out["md"])



class TestARuleTurnedOff(unittest.TestCase):
    """Turning a rule off has to mean everywhere, not just the panel.

    The disabled set was consulted at audit time and by the panel list, and
    nowhere else -- so a rule switched off after a run kept painting boxes on
    the drawing and kept filling rows in all three reports. On the demo pair,
    switching off one rule left 17 mentions of it in every export and all 57
    findings on the overlay.
    """

    def _doc(self):
        return _Doc(_doc().findings, None)

    def _rule_of(self, doc):
        return doc.findings[0].rule_id

    def test_its_findings_do_not_reach_any_export(self):
        doc = self._doc()
        rule = self._rule_of(doc)
        tmp = tempfile.mkdtemp()
        md = open(export_markdown(doc, os.path.join(tmp, "a.md"),
                                  disabled=[rule]), encoding="utf-8").read()
        csv_ = open(export_csv(doc, os.path.join(tmp, "a.csv"),
                               disabled=[rule]), encoding="utf-8").read()
        html = open(export_html(doc, os.path.join(tmp, "a.html"), "",
                                [rule]), encoding="utf-8").read()
        for fmt, text in (("md", md), ("csv", csv_), ("html", html)):
            with self.subTest(fmt):
                body = text.split("Turned off for this report")[-1]
                self.assertNotIn(doc.findings[0].message, body)

    def test_every_export_says_what_was_turned_off(self):
        """Rows may go; the fact must not.

        An export that silently drops rows makes "this rule found nothing" and
        "you switched this rule off" the same answer -- the confusion the
        coverage accounting exists to prevent, arriving by another door.
        """
        doc = self._doc()
        rule = self._rule_of(doc)
        tmp = tempfile.mkdtemp()
        for fmt, path, fn in (("md", "a.md", export_markdown),
                              ("csv", "a.csv", export_csv),
                              ("html", "a.html", export_html)):
            with self.subTest(fmt):
                out = fn(doc, os.path.join(tmp, path), disabled=[rule]) \
                    if fmt != "html" else fn(doc, os.path.join(tmp, path), "",
                                             [rule])
                text = open(out, encoding="utf-8").read()
                self.assertIn("Turned off for this report", text)
                self.assertIn(rule, text)

    def test_nothing_changes_when_nothing_is_turned_off(self):
        doc = self._doc()
        tmp = tempfile.mkdtemp()
        text = open(export_markdown(doc, os.path.join(tmp, "a.md")),
                    encoding="utf-8").read()
        self.assertNotIn("Turned off for this report", text)
        self.assertIn(doc.findings[0].message, text)

    def test_the_overlay_and_the_panel_read_the_same_filter(self):
        from app.audit.findings import visible_findings
        doc = self._doc()
        rule = self._rule_of(doc)
        kept = visible_findings(doc.findings, [rule])
        self.assertTrue(kept)
        self.assertNotIn(rule, [f.rule_id for f in kept])
        self.assertEqual(visible_findings(doc.findings, []), doc.findings)


if __name__ == "__main__":
    unittest.main()
