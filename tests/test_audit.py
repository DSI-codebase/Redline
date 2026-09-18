"""The audit layer: model building, running rules, and persisting the result.

These tests need PyDRC, which is an optional dependency, so anything that runs
rules skips without it. The parts that do not -- finding types, persistence,
graceful degradation -- always run, because a sidecar written by a colleague who
has the library must still open for someone who does not.
"""

import os
import shutil
import tempfile
import unittest

import fitz

from app import audit
from app.audit.adapter import AdapterOptions, build_model, parse_drawing_index
from app.audit.findings import (AuditRun, Coverage, Finding, Waiver,
                                apply_waivers, sort_findings,
                                DEFINITE, POTENTIAL, INFO,
                                STATUS_OPEN, STATUS_WAIVED)
from app.model.document import Document
from app.model.storage import SidecarDB, sidecar_path

HAVE_PYDRC = audit.available()
needs_pydrc = unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")

W, H = 792.0, 1224.0


def _sheet(doc, title, drawing_number, body=()):
    # Title and drawing number sit in separate title-block cells, as they do on
    # a real plot; writing them at the same x glues them into one word.
    page = doc.new_page(width=W, height=H)
    page.insert_text((40.0, 1000.0), title, rotate=270)
    page.insert_text((70.0, 1000.0), drawing_number, rotate=270)
    for i, line in enumerate(body):
        page.insert_text((300.0, 200.0 + i * 14.0), line, rotate=270)
    page.set_rotation(270)
    return page


def _drawing(path):
    """A small set: a schematic whose wire claims a sheet that is not there."""
    doc = fitz.open()
    _sheet(doc, "TITLE PAGE", "EL2507777-000")
    _sheet(doc, "24 VDC DISTRIBUTION", "EL2507777-400",
           body=["400010", "400020", "PB-40010"])
    _sheet(doc, "TERMINAL BLOCK LAYOUT", "EL2507777-800",
           body=["400010", "999990"])
    doc.save(path)
    doc.close()
    return path


class TestFindingTypes(unittest.TestCase):
    def test_round_trip(self):
        f = Finding(key="k", rule_id="R", severity=DEFINITE, message="m",
                    sheet="500", page=8, x=1.0, y=2.0, w=3.0, h=4.0,
                    evidence={"a": [1, 2]}, clause="internal naming")
        self.assertEqual(Finding.from_dict(f.to_dict()), f)

    def test_unknown_fields_are_dropped_not_fatal(self):
        f = Finding.from_dict({"key": "k", "from_a_newer_build": 1})
        self.assertEqual(f.key, "k")

    def test_sorting_is_by_severity_then_sheet(self):
        got = sort_findings([
            Finding(key="a", severity=INFO, sheet="100"),
            Finding(key="b", severity=DEFINITE, sheet="900"),
            Finding(key="c", severity=POTENTIAL, sheet="100"),
        ])
        self.assertEqual([f.key for f in got], ["b", "c", "a"])

    def test_apply_waivers_marks_rather_than_drops(self):
        # A reviewer needs to see that a decision was made, not just its effect.
        findings = [Finding(key="a"), Finding(key="b")]
        apply_waivers(findings, {"a": Waiver(key="a", reason="ok")})
        self.assertEqual([f.status for f in findings],
                         [STATUS_WAIVED, STATUS_OPEN])
        self.assertEqual(len(findings), 2)

    def test_apply_waivers_reopens_when_a_waiver_is_gone(self):
        findings = [Finding(key="a", status=STATUS_WAIVED)]
        apply_waivers(findings, {})
        self.assertEqual(findings[0].status, STATUS_OPEN)


class TestAuditRunSummary(unittest.TestCase):
    def test_names_what_was_not_checked(self):
        run = AuditRun(eligible=507, checked=452, skipped=55, coverage=[
            Coverage(rule_id="X", skipped=55, reasons={"missing catalog": 55})])
        line = run.summary_line()
        self.assertIn("452 of 507", line)
        self.assertIn("55 not checked", line)
        self.assertIn("missing catalog", line)

    def test_complete_run_says_so_plainly(self):
        self.assertEqual(AuditRun(eligible=10, checked=10).summary_line(),
                         "10 of 10 checked.")

    def test_no_dangling_parenthetical_without_reasons(self):
        self.assertEqual(AuditRun(eligible=10, checked=8, skipped=2).summary_line(),
                         "8 of 10 checked — 2 not checked.")

    def test_empty_run(self):
        self.assertEqual(AuditRun().summary_line(), "Nothing to check.")

    def test_json_round_trip(self):
        run = AuditRun(eligible=5, checked=4, skipped=1, packs=["drc-base@1.0.0"],
                       coverage=[Coverage(rule_id="X", skipped=1,
                                          reasons={"missing size": 1})])
        back = AuditRun.from_json(run.to_json())
        self.assertEqual(back.summary_line(), run.summary_line())
        self.assertEqual(back.packs, ["drc-base@1.0.0"])

    def test_bad_json_is_none_not_an_exception(self):
        self.assertIsNone(AuditRun.from_json("{not json"))
        self.assertIsNone(AuditRun.from_json(None))


class TestDrawingIndex(unittest.TestCase):
    def test_reads_section_and_description_pairs(self):
        text = ("DRAWING SECTION INDEX\nDRAWING SECTION\nDRAWING DESCRIPTION\n"
                "000\nTITLE PAGE\n100\nNETWORK TOPOLOGY\n200\n480VAC POWER\n")
        self.assertEqual(parse_drawing_index(text),
                         [("000", "TITLE PAGE"), ("100", "NETWORK TOPOLOGY"),
                          ("200", "480VAC POWER")])

    def test_no_index_no_rows(self):
        self.assertEqual(parse_drawing_index("just a schematic"), [])


@needs_pydrc
class TestAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))
        self.doc = fitz.open(self.src)
        from app.extraction.sheet_number import resolve_document
        from app.extraction.sheet_role import detect_document_roles
        res = resolve_document(self.doc)
        self.labels = {k: v.label for k, v in res.items() if v.resolved}
        self.sources = {k: v.strategy for k, v in res.items()}
        self.roles = detect_document_roles(self.doc)

    def tearDown(self):
        self.doc.close()

    def _build(self, options=None):
        return build_model(self.doc, self.labels, self.sources, self.roles,
                           options or AdapterOptions())

    def test_builds_sheets_with_provenance(self):
        model = self._build().model
        self.assertEqual([s.number for s in model.sheets], ["000", "400", "800"])
        self.assertEqual(model.sheets[1].provenance.resolved_by, "drawing_number")
        self.assertEqual(model.sheets[1].provenance.confidence, 1.0)

    def test_carries_sheet_roles_through(self):
        model = self._build().model
        self.assertEqual([s.role for s in model.sheets],
                         ["index", "schematic", "terminal-detail"])

    def test_records_where_entities_were_found(self):
        model = self._build().model
        wires = {c.label: c for c in model.conductors}
        self.assertIn("400010", wires)
        self.assertEqual(wires["400010"].declared_sheet, 400)

    def test_extents_are_captured_for_drawing_marks(self):
        built = self._build()
        box = built.extents.get((1, "400010"))
        self.assertIsNotNone(box)
        self.assertGreater(box[2], 0.0)      # a real width, not a point

    def test_excluded_labels_are_left_out(self):
        model = self._build(AdapterOptions(
            excluded_labels=frozenset({"400010"}))).model
        self.assertNotIn("400010", {c.label for c in model.conductors})

    def test_cancellation_returns_nothing(self):
        got = build_model(self.doc, self.labels, self.sources, self.roles,
                          AdapterOptions(), cancel=lambda: True)
        self.assertIsNone(got)


@needs_pydrc
class TestRunner(unittest.TestCase):
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

    def test_finds_the_non_reciprocal_wire(self):
        # 999990 claims sheet 999, which is not in the set.
        result = self._run()
        subjects = {f.subject_id for f in result.findings}
        self.assertIn("999990", subjects)

    def test_findings_carry_a_clause_and_a_place(self):
        result = self._run()
        target = next(f for f in result.findings if f.subject_id == "999990")
        self.assertTrue(target.clause)
        self.assertTrue(target.has_location)
        self.assertGreater(target.w, 0.0)

    def test_coverage_is_reported(self):
        result = self._run()
        self.assertGreater(result.run.eligible, 0)
        self.assertTrue(result.run.summary_line())

    def test_disabled_rules_do_not_run(self):
        result = self._run(disabled_rules=["DRC-XREF-WIRE-RECIP-001"])
        rules = {f.rule_id for f in result.findings}
        self.assertNotIn("DRC-XREF-WIRE-RECIP-001", rules)

    def test_severity_override(self):
        result = self._run(severity_overrides={"DRC-TAG-FAMILY-001": DEFINITE})
        for f in result.findings:
            if f.rule_id == "DRC-TAG-FAMILY-001":
                self.assertEqual(f.severity, DEFINITE)

    def test_waivers_are_applied(self):
        first = self._run()
        key = first.findings[0].key
        again = self._run(waivers={key: Waiver(key=key, reason="ok")})
        marked = next(f for f in again.findings if f.key == key)
        self.assertEqual(marked.status, STATUS_WAIVED)
        self.assertNotIn(key, {f.key for f in again.open_findings})

    def test_cancellation(self):
        self.assertTrue(self._run(cancel=lambda: True).cancelled)

    def test_keys_are_stable_across_runs(self):
        # Waivers are keyed on this; if it moved, every waiver would evaporate
        # on the next audit.
        self.assertEqual({f.key for f in self._run().findings},
                         {f.key for f in self._run().findings})


class TestUnavailable(unittest.TestCase):
    def test_status_explains_itself(self):
        ok, message = audit.status()
        self.assertIsInstance(ok, bool)
        self.assertTrue(message)

    def test_run_audit_raises_a_named_error_without_the_library(self):
        import app.audit.runner as runner
        real = __builtins__["__import__"] if isinstance(__builtins__, dict) \
            else __builtins__.__import__

        def blocked(name, *a, **kw):
            if name.startswith("pydrc"):
                raise ImportError("simulated: pydrc not installed")
            return real(name, *a, **kw)

        import builtins
        builtins.__import__ = blocked
        try:
            with self.assertRaises(runner.AuditUnavailable):
                runner.run_audit("nope.pdf", {}, {}, {})
        finally:
            builtins.__import__ = real


class TestPersistence(unittest.TestCase):
    """Findings, waivers, and the rule that separates them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))

    def _open(self):
        doc = Document(self.src)
        doc.load()
        return doc

    def test_findings_round_trip(self):
        doc = self._open()
        doc.set_findings([Finding(key="k1", rule_id="R1", message="hello",
                                  sheet="400", page=1, x=1.0, y=2.0)],
                         AuditRun(eligible=3, checked=3))
        doc.close()

        again = self._open()
        self.assertEqual([f.key for f in again.findings], ["k1"])
        self.assertEqual(again.findings[0].message, "hello")
        self.assertEqual(again.audit_run.summary_line(), "3 of 3 checked.")
        again.close()

    def test_a_rerun_clears_findings_that_no_longer_fire(self):
        # `if self.findings:` would leave stale rows behind, so the write is
        # unconditional.
        doc = self._open()
        doc.set_findings([Finding(key="k1")], AuditRun())
        doc.set_findings([], AuditRun())
        doc.close()
        again = self._open()
        self.assertEqual(again.findings, [])
        again.close()

    def test_waivers_survive_an_audit_rerun(self):
        # The property the whole two-table split exists for.
        doc = self._open()
        doc.set_findings([Finding(key="k1", rule_id="R1")], AuditRun())
        doc.waive_finding("k1", "Accepted by client", "LWH")
        doc.set_findings([Finding(key="k1", rule_id="R1")], AuditRun())
        self.assertEqual(doc.findings[0].status, STATUS_WAIVED)
        doc.close()

        again = self._open()
        self.assertEqual(again.findings[0].status, STATUS_WAIVED)
        self.assertEqual(again.waiver_for("k1").reason, "Accepted by client")
        self.assertEqual(again.waiver_for("k1").author, "LWH")
        again.close()

    def test_clearing_a_waiver_reopens_and_persists(self):
        doc = self._open()
        doc.set_findings([Finding(key="k1")], AuditRun())
        doc.waive_finding("k1", "ok")
        doc.clear_waiver("k1")
        self.assertEqual(doc.findings[0].status, STATUS_OPEN)
        doc.close()

        again = self._open()
        self.assertIsNone(again.waiver_for("k1"))
        self.assertEqual(again.findings[0].status, STATUS_OPEN)
        again.close()

    def test_waiving_an_unknown_key_is_harmless(self):
        doc = self._open()
        doc.waive_finding("", "no key")
        doc.waive_finding("ghost", "not a finding here")
        self.assertIsNotNone(doc.waiver_for("ghost"))
        doc.close()

    def test_tables_appear_in_a_sidecar_created_before_they_existed(self):
        # There is no migration mechanism: CREATE TABLE IF NOT EXISTS on every
        # open is the whole story, which works for new tables and not for new
        # columns. This is the test that the choice was made correctly.
        path = sidecar_path(self.src)
        legacy = SidecarDB(path)
        legacy.conn.executescript("DROP TABLE findings; DROP TABLE waivers;")
        legacy.conn.commit()
        legacy.close()

        reopened = SidecarDB(path)
        try:
            self.assertEqual(reopened.load_findings(), [])
            self.assertEqual(reopened.load_waivers(), {})
            reopened.save_findings([Finding(key="k")])
            self.assertEqual(len(reopened.load_findings()), 1)
        finally:
            reopened.close()

    def test_save_as_does_not_inherit_foreign_waivers(self):
        doc = self._open()
        doc.waive_finding("k1", "mine")
        dest = os.path.join(self.tmp, "fork.pdf")
        # Pre-seed the destination sidecar with somebody else's decision.
        other = SidecarDB(sidecar_path(dest))
        other.save_waiver(Waiver(key="foreign", reason="not mine"))
        other.close()

        doc.save_as(dest)
        doc.close()

        forked = Document(dest)
        forked.load()
        self.assertIn("k1", forked.waivers)
        self.assertNotIn("foreign", forked.waivers)
        forked.close()


if __name__ == "__main__":
    unittest.main()
