"""The sheet-role editor: a person sets a role, and it wins.

The design rule check reads each sheet's role to decide which rules apply, and
detection is sometimes wrong. Until this editor, ``Document.set_sheet_role``
had no caller in the app, so a wrong role could not be corrected and
``docs/Design Rule Check.md`` called roles editable when they were not.

What is held here: the editor shows the role the check will use and who decided
it, read from the same function the check reads; OK writes through
``set_sheet_role``, so the choice is recorded as the person's and survives
reopening; and a role set here beats a confident Jev answer.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.extraction.sheet_role import (
    INDEX, JEV_WORDING, LAYOUT, PLC_IO, SCHEMATIC, TOPOLOGY,
)
from app.model.document import Document
from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

TITLES = ("TITLE PAGE", "BACK PANEL LAYOUT", "24 VDC DISTRIBUTION")


def _drawing(path):
    doc = fitz.open()
    for title in TITLES:
        page = doc.new_page(width=792, height=1224)
        page.insert_text((40.0, 1000.0), title, rotate=270)
        page.set_rotation(270)
    doc.save(path)
    doc.close()
    return path


def _answer(role, confidence):
    return {"role": role, "confidence": confidence, "probabilities": {},
            "model": "jev-1.13.0", "wording": JEV_WORDING}


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))
        self._docs = []

    def tearDown(self):
        for d in self._docs:
            d.close()

    def _open(self):
        d = Document(self.src)
        d.load()
        self._docs.append(d)
        return d

    def _release(self, d):
        d.close()
        self._docs.remove(d)


class TestDecision(_Fixture):
    """``sheet_role_decision`` is what the editor shows and the check reads."""

    def test_who_decided_each_page(self):
        d = self._open()
        d.set_sheet_role(0, PLC_IO)
        d.set_jev_roles({1: _answer(TOPOLOGY, 0.9)})
        self.assertEqual(d.sheet_role_decision(0, True), (PLC_IO, "user", None))
        self.assertEqual(d.sheet_role_decision(1, True), (TOPOLOGY, "jev", 0.9))
        self.assertEqual(d.sheet_role_decision(1, False), (LAYOUT, "keywords", None))
        self.assertEqual(d.sheet_role_decision(2, True), (SCHEMATIC, "keywords", None))

    def test_the_check_reads_exactly_what_the_editor_shows(self):
        d = self._open()
        d.set_sheet_role(0, PLC_IO)
        d.set_jev_roles({1: _answer(TOPOLOGY, 0.9), 2: _answer(INDEX, 0.5)})
        for use_jev in (False, True):
            self.assertEqual(
                d.roles_for_audit(use_jev),
                {p: d.sheet_role_decision(p, use_jev)[0] for p in range(3)})

    def test_automatic_for_a_set_page_is_what_clearing_would_give(self):
        d = self._open()
        d.set_sheet_role(1, PLC_IO)
        self.assertEqual(d.automatic_sheet_role(1), (LAYOUT, "keywords", None))


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestDialog(_Fixture):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, d, use_jev=False):
        from app.dialogs import SheetRolesDialog
        return SheetRolesDialog(d, use_jev)

    def test_one_row_per_page_showing_the_role_and_who_decided(self):
        d = self._open()
        d.set_sheet_role(2, PLC_IO)
        d.set_jev_roles({1: _answer(TOPOLOGY, 0.92)})
        dlg = self._dialog(d, use_jev=True)
        self.assertEqual(dlg.table.rowCount(), 3)
        col = dlg.COL_BY
        self.assertEqual([dlg.table.item(p, col).text() for p in range(3)],
                         ["Title-block keywords", "Jev (0.92)", "You"])
        self.assertEqual(dlg._combos[0].currentText(), "Automatic: Title / index")
        self.assertEqual(dlg._combos[1].currentText(), "Automatic: Network topology")
        self.assertEqual(dlg._combos[2].currentData(), PLC_IO)
        self.assertEqual(dlg.changes(), {})

    def test_changes_are_only_the_rows_moved(self):
        d = self._open()
        d.set_sheet_role(2, PLC_IO)
        dlg = self._dialog(d)
        dlg.set_choice(0, LAYOUT)
        dlg.set_choice(2, "")
        self.assertEqual(dlg.changes(), {0: LAYOUT, 2: ""})
        self.assertEqual(dlg.table.item(0, dlg.COL_BY).text(), "You")
        self.assertEqual(dlg.table.item(2, dlg.COL_BY).text(), "Title-block keywords")
        dlg.set_choice(0, "")
        dlg.set_choice(2, PLC_IO)
        self.assertEqual(dlg.changes(), {})

    def test_a_view_only_file_cannot_be_edited(self):
        from PySide6.QtWidgets import QDialogButtonBox
        d = self._open()
        d.sidecar_available = False
        dlg = self._dialog(d)
        self.assertFalse(any(c.isEnabled() for c in dlg._combos.values()))
        self.assertFalse(dlg.findChild(QDialogButtonBox)
                         .button(QDialogButtonBox.Ok).isEnabled())


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestWindow(_Fixture):
    """``MainWindow.edit_sheet_roles``, from the Tools menu and the Audit tab."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _edit(self, choices, accept=True):
        """Open the window, run the editor making ``choices``, close it."""
        from PySide6.QtWidgets import QDialog
        from app.dialogs import SheetRolesDialog
        from app.main_window import MainWindow

        def fake_exec(dlg):
            for page, role in choices.items():
                dlg.set_choice(page, role)
            return QDialog.Accepted if accept else QDialog.Rejected

        win = MainWindow()
        win.load_document(self.src)
        with mock.patch.object(SheetRolesDialog, "exec", fake_exec):
            win.edit_sheet_roles()
        win.close()

    def test_a_role_set_in_the_editor_is_the_persons_and_survives_reopening(self):
        # Inject: write doc.sheet_roles directly instead of set_sheet_role.
        self._edit({2: PLC_IO})
        d = self._open()
        self.assertEqual(d.sheet_role_decision(2), (PLC_IO, "user", None))

    def test_it_beats_a_confident_jev_answer(self):
        self._edit({2: PLC_IO})
        d = self._open()
        d.sheet_role_jev[2] = _answer(LAYOUT, 1.0)
        self.assertEqual(d.roles_for_audit(use_jev=True)[2], PLC_IO)
        self.assertNotIn(2, d.pages_needing_jev())

    def test_automatic_hands_the_page_back_to_detection(self):
        self._edit({1: PLC_IO})
        self._edit({1: ""})
        d = self._open()
        self.assertEqual(d.sheet_role_decision(1), (LAYOUT, "keywords", None))
        self.assertIn(1, d.pages_needing_jev())

    def test_cancel_writes_nothing(self):
        self._edit({2: PLC_IO}, accept=False)
        d = self._open()
        self.assertEqual(d.sheet_role_decision(2), (SCHEMATIC, "keywords", None))

    def test_the_audit_tab_and_the_tools_menu_both_open_it(self):
        # Counts dialogs actually shown, through the real wiring: the menu and
        # the signal both hold bound methods taken at build time, so patching
        # the handler would count nothing. Inject: drop either connection.
        from PySide6.QtWidgets import QDialog
        from app.dialogs import SheetRolesDialog
        from app.main_window import MainWindow
        shown = []
        win = MainWindow()
        win.load_document(self.src)
        with mock.patch.object(SheetRolesDialog, "exec",
                               lambda dlg: shown.append(dlg) or QDialog.Rejected):
            win.audit_panel.btn_roles.click()
            self.assertEqual(len(shown), 1, "the Audit tab's button")
            win.act_sheet_roles.trigger()
            self.assertEqual(len(shown), 2, "Tools > Sheet roles...")
        win.close()


if __name__ == "__main__":
    unittest.main()
