"""Project assumptions: what a person states for a drawing's electrical rules.

A drawing does not say what temperature its panel runs at or what its
terminations are rated, so PyDRC's ampacity correction reports every conductor
as not checked until somebody states it. The owner's decision of 2026-10-30
puts that statement in this app, per drawing, saved in the sidecar beside the
drawing and written into the model the rules read. A blank is not stated, and
nothing here ever fills one in.
"""

import json
import os
import shutil
import tempfile
import unittest

import pymupdf

from app import audit
from app.audit.adapter import build_model
from app.model.document import Document, parse_project_assumptions
from tests._qt import QT_OK, REASON as QT_REASON

HAVE_PYDRC = audit.available()
needs_pydrc = unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")


def _drawing(path):
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((72.0, 72.0), "EL2507777-400")
    doc.save(path)
    doc.close()
    return path


class TestWhatASidecarHolds(unittest.TestCase):
    """Only a value the field takes survives a read: a damaged sidecar still
    opens, and the rule that needed the value says it is missing."""

    def test_both_fields_round_trip(self):
        raw = json.dumps({"internal_max_c": 40, "termination_c": 75})
        self.assertEqual(parse_project_assumptions(raw),
                         {"internal_max_c": 40.0, "termination_c": 75})

    def test_a_value_the_field_does_not_take_is_not_stated(self):
        """Injected: the 60/75/90 check removed (red: 70 kept)."""
        for raw in ('{"termination_c": 70}', '{"termination_c": "75"}',
                    '{"termination_c": true}', '{"internal_max_c": "40"}',
                    '{"internal_max_c": true}', '{"internal_max_c": Infinity}',
                    '{"internal_max_c": NaN}'):
            with self.subTest(raw=raw):
                self.assertEqual(parse_project_assumptions(raw), {})

    def test_a_damaged_or_foreign_value_reads_as_nothing_stated(self):
        for raw in (None, "", "not json", "[40]", '"40"'):
            with self.subTest(raw=raw):
                self.assertEqual(parse_project_assumptions(raw), {})

    def test_an_unknown_field_is_not_carried(self):
        self.assertEqual(parse_project_assumptions(
            '{"internal_max_c": 40, "ambient_max_c": 25}'), {"internal_max_c": 40.0})


class TestTheDrawingKeepsThem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stated_values_survive_a_reopen(self):
        doc = Document(self.src)
        doc.load()
        self.assertEqual(doc.project_assumptions, {})
        doc.set_project_assumptions({"internal_max_c": 45.0, "termination_c": 75})
        doc.close()

        again = Document(self.src)
        again.load()
        self.assertEqual(again.project_assumptions,
                         {"internal_max_c": 45.0, "termination_c": 75})
        again.close()

    def test_clearing_a_value_removes_it(self):
        doc = Document(self.src)
        doc.load()
        doc.set_project_assumptions({"internal_max_c": 45.0, "termination_c": 75})
        doc.set_project_assumptions({"termination_c": 75})
        doc.close()

        again = Document(self.src)
        again.load()
        self.assertEqual(again.project_assumptions, {"termination_c": 75})
        again.close()


@needs_pydrc
class TestTheModelCarriesThem(unittest.TestCase):
    """What a person stated reaches the model the rules read, and nothing else
    does: a drawing states none of the other assumptions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _model(self, assumptions):
        with pymupdf.open(self.src) as doc:
            return build_model(doc, {0: "400"}, {0: "user"}, {},
                               assumptions=assumptions).model

    def test_the_stated_values_are_the_models(self):
        """Injected: the adapter ignoring ``assumptions`` (red)."""
        a = self._model({"internal_max_c": 45.0, "termination_c": 75}).assumptions
        self.assertEqual((a.internal_max_c, a.termination_c), (45.0, 75))
        self.assertEqual(a.provenance.source, "user")

    def test_nothing_stated_leaves_every_assumption_blank(self):
        a = self._model({}).assumptions
        self.assertEqual((a.internal_max_c, a.termination_c, a.ambient_max_c,
                          a.system_voltage), (None, None, None, None))

    def test_the_model_document_writes_them(self):
        d = self._model({"internal_max_c": 45.0}).to_dict()
        self.assertEqual(d["assumptions"]["internal_max_c"], 45.0)


@unittest.skipUnless(QT_OK, QT_REASON)
class TestTheDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, values=None):
        from app.dialogs import ProjectAssumptionsDialog
        return ProjectAssumptionsDialog(values or {})

    def test_a_blank_form_states_nothing(self):
        self.assertEqual(self._dialog().values(), {})

    def test_it_shows_what_is_stated(self):
        dlg = self._dialog({"internal_max_c": 45.0, "termination_c": 90})
        self.assertEqual(dlg.internal.text(), "45")
        self.assertEqual(dlg.termination.currentData(), 90)
        self.assertEqual(dlg.values(), {"internal_max_c": 45.0, "termination_c": 90})

    def test_what_is_typed_is_what_is_kept(self):
        dlg = self._dialog()
        dlg.internal.setText(" 40.5 ")
        dlg.termination.setCurrentIndex(dlg.termination.findData(75))
        self.assertEqual(dlg.values(), {"internal_max_c": 40.5, "termination_c": 75})

    def test_ok_refuses_what_is_not_a_temperature(self):
        """Injected: problem() returning "" for every text (red: accepted)."""
        from PySide6.QtWidgets import QDialog
        dlg = self._dialog()
        dlg.internal.setText("hot")
        dlg._accept()
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        self.assertIn("not a temperature", dlg.error.text())
        self.assertEqual(dlg.values(), {})

    def test_the_window_and_the_menu_reach_it(self):
        from app.main_window import MainWindow
        win = MainWindow()
        try:
            self.assertTrue(callable(getattr(win, "edit_project_assumptions")))
            self.assertEqual(win.act_project_assumptions.text(), "Project assumptions…")
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
