"""Every audit with imported drawings says how much of them the plot found.

PyDRC's P4 asks for a reconciliation of the plot-derived model against the
source drawings that grades the PDF adapter continuously, not once. PyDRC
0.18.0 ships ``pydrc.adapters.reconcile``. This is the app calling it on every
run that has an import, before the two models are merged, and saying what it
found beside the coverage line and in every exported report.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fitz

from app import audit
from app.audit.findings import AuditRun
from app.export.audit_export import export_csv, export_html, export_markdown
from tests._qt import QT_OK, REASON as QT_REASON

HAVE_PYDRC = audit.available()
needs_pydrc = unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")


def _kind(name, plot, source, matched, mismatched=0, not_comparable=0,
          plot_only=0, source_only=0, mismatches=()):
    both = matched + mismatched + not_comparable
    return {"kind": name, "plot": plot, "source": source, "matched": matched,
            "mismatched": mismatched, "not_comparable": not_comparable,
            "plot_only": plot_only, "source_only": source_only,
            "recall": both / source if source else None,
            "precision": both / plot if plot else None,
            "mismatches": list(mismatches)}


RECON = {"schema": "pydrc.reconcile/1", "common_sheets": ["300", "400"],
         "plot_sheets_only": [], "source_sheets_only": [], "compared": 6,
         "kinds": [_kind("sheets", 2, 2, 2),
                   _kind("devices", 3, 4, 2, mismatched=1, source_only=1,
                         mismatches=[{"key": ["400", "PB-40010"], "field": "family",
                                      "plot": "PB", "source": "SS"}]),
                   _kind("conductors", 0, 0, 0),
                   _kind("signal_arrows", 1, 1, 0, not_comparable=1)]}


class _Doc:
    def __init__(self, run):
        self.findings = []
        self.audit_run = run
        self.waivers = {}
        self.path = "/tmp/Demo Panel.pdf"

    def waiver_for(self, key):
        return None


class TestTheSentence(unittest.TestCase):
    def test_nothing_imported_says_nothing(self):
        self.assertEqual(AuditRun().reconciliation_line(), "")

    def test_it_counts_what_the_plot_found_of_the_source(self):
        """Kinds the source has none of are left out of the sentence."""
        self.assertEqual(
            AuditRun(reconciliation=RECON).reconciliation_line(),
            "Against the imported drawings, the plot found 2 of 2 sheets, 3 of 4 "
            "devices and 1 of 1 signal arrows. 1 of them disagrees with the source.")

    def test_an_empty_comparison_is_said_rather_than_hidden(self):
        """Injected: the empty case answered with "" (red)."""
        empty = dict(RECON, compared=0, common_sheets=[], kinds=[])
        self.assertEqual(AuditRun(reconciliation=empty).reconciliation_line(),
                         "The plot and the imported drawings have nothing in common "
                         "to compare: they share 0 sheet numbers.")

    def test_it_survives_the_sidecar(self):
        run = AuditRun.from_json(AuditRun(reconciliation=RECON).to_json())
        self.assertEqual(run.reconciliation, RECON)

    def test_a_run_saved_before_it_existed_has_none(self):
        self.assertIsNone(AuditRun.from_json('{"eligible": 1}').reconciliation)


class TestTheReportsCarryTheTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = _Doc(AuditRun(eligible=3, checked=3, reconciliation=RECON))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _export(self, export, name, doc=None):
        path = export(doc or self.doc, os.path.join(self.tmp, name))
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_markdown(self):
        text = self._export(export_markdown, "r.md")
        self.assertIn("## The plot against the imported drawings", text)
        self.assertIn("| devices | 3 | 2 | 1 | 0 | 0 | 1 | 75.0% | 100.0% |", text)
        self.assertIn("| conductors | 0 | 0 | 0 | 0 | 0 | 0 | - | - |", text)
        self.assertIn("devices, ['400', 'PB-40010']: family is 'PB' on the plot and "
                      "'SS' in the source", text)

    def test_csv_and_html(self):
        """Injected: the table left out of the CSV (red)."""
        csv_text = self._export(export_csv, "r.csv")
        self.assertIn("Reconciliation,devices,3,2,1,0,0,1,75.0%,100.0%", csv_text)
        self.assertIn("Disagreement,devices", csv_text)
        html = self._export(export_html, "r.html")
        self.assertIn("<td>devices</td><td>3</td>", html)
        self.assertIn("family is &#x27;PB&#x27; on the plot", html)

    def test_no_import_adds_no_section(self):
        text = self._export(export_markdown, "r.md", _Doc(AuditRun(eligible=3, checked=3)))
        self.assertNotIn("imported drawings", text)


def _drawing(path):
    doc = fitz.open()
    for title, number, body in (
        ("TITLE PAGE", "EL2507777-000", ()),
        ("24 VDC DISTRIBUTION", "EL2507777-400", ("400010", "PB-40010")),
        ("TERMINAL BLOCK LAYOUT", "EL2507777-800", ("400010",)),
    ):
        page = doc.new_page(width=792, height=1224)
        page.insert_text((40.0, 1000.0), title, rotate=270)
        page.insert_text((70.0, 1000.0), number, rotate=270)
        for i, line in enumerate(body):
            page.insert_text((300.0, 200.0 + i * 16.0), line, rotate=270)
        page.set_rotation(270)
    doc.save(path)
    doc.close()
    return path


@needs_pydrc
class TestTheRunReconcilesBeforeMerging(unittest.TestCase):
    LABELS = {0: "000", 1: "400", 2: "800"}
    SOURCES = {0: "user", 1: "user", 2: "user"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _source(self):
        from pydrc.model import Device, ModelDocument, Provenance, Sheet
        m = ModelDocument()
        acade = Provenance(source="acade")
        for i, n in enumerate(("000", "400", "800")):
            m.sheets.append(Sheet(number=n, page_index=i, provenance=acade))
        m.devices = [Device(tag="PB-40010", family="PB", found_on_sheet="400",
                            provenance=acade),
                     Device(tag="LT-40020", family="LT", found_on_sheet="400",
                            provenance=acade)]
        return json.dumps(m.to_dict())

    def _run(self, acade_json):
        from app.audit.runner import run_audit
        return run_audit(self.src, self.LABELS, self.SOURCES, {},
                         acade_model_json=acade_json).run

    def test_the_symbol_only_the_source_draws_is_counted_as_the_sources(self):
        """After the merge LT-40020 is in the plot's model too, so a comparison
        taken there would say the plot found it. Injected: the reconciliation
        moved after merge_models (red: source_only 0)."""
        run = self._run(self._source())
        devices = next(k for k in run.reconciliation["kinds"] if k["kind"] == "devices")
        self.assertEqual((devices["matched"], devices["source_only"]), (1, 1))
        self.assertIn("1 of 2 devices", run.reconciliation_line())

    def test_no_import_no_reconciliation(self):
        self.assertIsNone(self._run("").reconciliation)

    def test_a_library_without_reconcile_shows_none_and_still_checks(self):
        import builtins
        real_import = builtins.__import__

        def no_reconcile(name, *args, **kwargs):
            if name == "pydrc.adapters.reconcile":
                raise ImportError("PyDRC before 0.18.0")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", no_reconcile):
            run = self._run(self._source())
        self.assertIsNone(run.reconciliation)
        self.assertGreater(run.eligible, 0)


@unittest.skipUnless(QT_OK, QT_REASON)
class TestThePanelSaysIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_the_line_sits_under_the_coverage_sentence(self):
        """Injected: the line left out of _update_headers (red)."""
        from app.panels.audit_panel import AuditPanel
        panel = AuditPanel()
        panel.set_document(_Doc(AuditRun(eligible=3, checked=3, reconciliation=RECON)))
        self.assertIn("the plot found 2 of 2 sheets", panel.coverage_label.text())


if __name__ == "__main__":
    unittest.main()
