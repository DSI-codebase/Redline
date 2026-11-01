"""Two pieces of PyDRC's P2 that were not built until 2026-10-30.

The coverage line names the pages with no sheet number. A rule that needs a
sheet number skips such a page, and the counts said how many items that cost
without saying which pages, which is half of what PyDRC's P2 exit asked for.

Settings chooses the rule packs. ``Config.audit_packs()`` had been read on
every run and written by nothing, so the app always ran PyDRC's default packs.
"""

import os
import shutil
import tempfile
import unittest

import pymupdf

from app import audit
from app.audit.findings import AuditRun, UNNUMBERED_NAMED
from app.export.audit_export import export_csv, export_html, export_markdown
from tests._qt import QT_OK, REASON as QT_REASON

HAVE_PYDRC = audit.available()
needs_pydrc = unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")


class _Doc:
    def __init__(self, run):
        self.findings = []
        self.audit_run = run
        self.waivers = {}
        self.path = "/tmp/Demo Panel.pdf"

    def waiver_for(self, key):
        return None


class TestTheSentence(unittest.TestCase):
    def test_none_says_nothing(self):
        self.assertEqual(AuditRun().unnumbered_line(), "")

    def test_one_page(self):
        self.assertEqual(AuditRun(unnumbered_pages=[3]).unnumbered_line(),
                         "Page 3 has no sheet number. A rule that needs one did "
                         "not check it.")

    def test_several_pages_in_order(self):
        self.assertEqual(AuditRun(unnumbered_pages=[7, 2, 5]).unnumbered_line(),
                         "Pages 2, 5 and 7 have no sheet number. A rule that "
                         "needs one did not check them.")

    def test_a_long_list_says_how_many_it_left_out(self):
        pages = list(range(1, UNNUMBERED_NAMED + 4))
        line = AuditRun(unnumbered_pages=pages).unnumbered_line()
        self.assertIn(f"{UNNUMBERED_NAMED} and 3 more have no sheet number", line)

    def test_it_survives_the_sidecar(self):
        run = AuditRun.from_json(AuditRun(unnumbered_pages=[2, 9]).to_json())
        self.assertEqual(run.unnumbered_pages, [2, 9])

    def test_a_run_saved_before_it_existed_names_none(self):
        old = '{"eligible": 4, "checked": 4, "skipped": 0, "coverage": []}'
        self.assertEqual(AuditRun.from_json(old).unnumbered_pages, [])


class TestTheReportsSayIt(unittest.TestCase):
    """The panel's line and every export say the same sentence."""

    LINE = "Page 4 has no sheet number."

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = _Doc(AuditRun(eligible=3, checked=3, unnumbered_pages=[4]))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_markdown_csv_and_html(self):
        """Injected: the sentence left out of the CSV (red)."""
        for name, export in (("r.md", export_markdown), ("r.csv", export_csv),
                             ("r.html", export_html)):
            with self.subTest(name):
                text = self._read(export(self.doc, os.path.join(self.tmp, name)))
                self.assertIn(self.LINE, text)

    def test_a_run_with_every_page_numbered_adds_nothing(self):
        doc = _Doc(AuditRun(eligible=3, checked=3))
        text = self._read(export_markdown(doc, os.path.join(self.tmp, "r.md")))
        self.assertNotIn("sheet number", text)


def _drawing(path):
    doc = pymupdf.open()
    for title, number in (("TITLE PAGE", "EL2507777-000"),
                          ("NOTES", ""),
                          ("24 VDC DISTRIBUTION", "EL2507777-400")):
        page = doc.new_page(width=792, height=612)
        page.insert_text((72.0, 72.0), title)
        if number:
            page.insert_text((600.0, 580.0), number)
    doc.save(path)
    doc.close()
    return path


@needs_pydrc
class TestTheRunnerReadsTheModel(unittest.TestCase):
    """The pages come from the model the rules ran on, the oracle that
    decided the skips, not from a second reading of the labels."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_page_with_no_number_is_named(self):
        """Injected: unnumbered_pages left empty in run_audit (red)."""
        from app.audit.runner import run_audit
        result = run_audit(self.src, {0: "000", 2: "400"}, {0: "user", 2: "user"}, {})
        self.assertEqual(result.run.unnumbered_pages, [2])
        self.assertTrue(result.run.unnumbered_line().startswith("Page 2 "))

    def test_every_page_numbered_names_none(self):
        from app.audit.runner import run_audit
        result = run_audit(self.src, {0: "000", 1: "100", 2: "400"},
                           {0: "user", 1: "user", 2: "user"}, {})
        self.assertEqual(result.run.unnumbered_pages, [])


@unittest.skipUnless(QT_OK, QT_REASON)
class TestThePanelSaysIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_the_coverage_line_names_the_page(self):
        """Injected: the line left out of _update_headers (red)."""
        from app.panels.audit_panel import AuditPanel
        panel = AuditPanel()
        panel.set_document(_Doc(AuditRun(eligible=3, checked=3, unnumbered_pages=[4])))
        self.assertIn("Page 4 has no sheet number.", panel.coverage_label.text())


@unittest.skipUnless(QT_OK and HAVE_PYDRC, "needs PySide6 and PyDRC")
class TestSettingsChoosesThePacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.config import AppConfig
        self.config = AppConfig()
        self.saved = (self.config.audit_packs(), self.config.audit_disabled_rules(),
                      self.config.audit_severity_overrides())
        self.config.set_audit_packs([])
        self.config.set_audit_disabled_rules([])
        self.config.set_audit_severity_overrides({})

    def tearDown(self):
        packs, disabled, overrides = self.saved
        self.config.set_audit_packs(packs)
        self.config.set_audit_disabled_rules(disabled)
        self.config.set_audit_severity_overrides(overrides)
        self.config.sync()

    def _dialog(self):
        from app.settings_dialog import SettingsDialog
        return SettingsDialog(self.config)

    def _box(self, dlg, pack_id):
        return dict(dlg.drc_packs)[pack_id]

    def _rules(self, dlg):
        return {row[0] for row in dlg.drc_rows}

    def test_every_pack_the_library_finds_is_offered(self):
        from app.audit.runner import available_packs, default_packs
        dlg = self._dialog()
        offered = [pack_id for pack_id, _box in dlg.drc_packs]
        self.assertEqual(offered, [p[0] for p in available_packs()])
        self.assertGreaterEqual(len(offered), 4, offered)
        ticked = [pack_id for pack_id, box in dlg.drc_packs if box.isChecked()]
        self.assertEqual(sorted(ticked), sorted(default_packs()))

    def test_ticking_a_pack_lists_its_rules_and_saves_the_choice(self):
        """Injected: _apply_audit not writing the packs (red)."""
        dlg = self._dialog()
        self.assertNotIn("ERC-HEAT-COOL-001", self._rules(dlg))
        self._box(dlg, "erc-heat").setChecked(True)
        self.assertIn("ERC-HEAT-COOL-001", self._rules(dlg))
        dlg.apply()
        self.assertIn("erc-heat", self.config.audit_packs())

    def test_the_default_packs_are_saved_as_no_choice(self):
        """So the app follows PyDRC when it moves a rule between packs."""
        self.config.set_audit_packs(["drc-base"])
        dlg = self._dialog()
        self._box(dlg, "erc-nec-2026").setChecked(True)
        dlg.apply()
        self.assertEqual(self.config.audit_packs(), [])

    def test_no_pack_ticked_runs_the_default_and_says_so(self):
        dlg = self._dialog()
        for _pack_id, box in dlg.drc_packs:
            box.setChecked(False)
        self.assertIn("default packs", dlg.drc_pack_note.text())
        self.assertTrue(dlg.drc_rows)
        dlg.apply()
        self.assertEqual(self.config.audit_packs(), [])

    def test_a_rule_switched_off_in_a_pack_left_out_stays_off(self):
        """Injected: the saved list rebuilt from the rows shown alone (red)."""
        self.config.set_audit_disabled_rules(["ERC-AMP-COL-001"])
        dlg = self._dialog()
        self._box(dlg, "erc-nec-2026").setChecked(False)
        self.assertNotIn("ERC-AMP-COL-001", self._rules(dlg))
        dlg.apply()
        self.assertIn("ERC-AMP-COL-001", self.config.audit_disabled_rules())

    def test_a_choice_made_here_survives_a_pack_toggled_off_and_on(self):
        from PySide6.QtCore import Qt
        dlg = self._dialog()
        row = next(r for r in dlg.drc_rows if r[0] == "ERC-AMP-COL-001")
        row[2].setCheckState(Qt.Unchecked)
        box = self._box(dlg, "erc-nec-2026")
        box.setChecked(False)
        box.setChecked(True)
        row = next(r for r in dlg.drc_rows if r[0] == "ERC-AMP-COL-001")
        self.assertEqual(row[2].checkState(), Qt.Unchecked)


if __name__ == "__main__":
    unittest.main()
