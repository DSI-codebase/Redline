"""A ``&`` in a widget title is a mnemonic marker, not a character.

Qt reads a single ``&`` in a QGroupBox title, a button's text, or a QLabel that
has a buddy (every ``QFormLayout.addRow("text", field)`` label does) as
"underline the next character and bind Alt+it". So
``QGroupBox("Comments & junk filter")`` rendered as *Comments _junk filter*:
the ampersand vanished, the space after it was underlined, and the group took
Alt+Space. Seen on 2026-11-01 in an offscreen screenshot of Settings, General
tab (Fusion, PySide6 6.11), while ``docs/Settings.md`` spelled the group
*Comments & junk filter*. The same bare ``&`` was in *OCR & AI assist* and in
the sheet-number wizard's *Finish & split* button. A literal ampersand is
written ``&&``.

The displayed text is **read from Qt, never computed here**. Qt's accessible
name for a titled widget is its title with the mnemonic markers removed, the
string a screen reader speaks, and it matches what the widget paints. A copy
of Qt's stripping rule in this file would only agree with itself.
``TestTheReadingSeesTheDefect`` proves the reading still strips on the Qt this
runs on, so a Qt that stopped stripping turns this red rather than letting the
sweep pass over nothing.

A QLabel with no buddy paints ``&`` literally and cannot have this defect, so
it is not read. A standard button (OK, Cancel) takes its text from Qt's
platform theme, where a ``&`` is Qt's own intended mnemonic, so it is counted
as skipped rather than read.
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON  # noqa: E402


def _sweep(root):
    """Read every widget under ``root`` that treats ``&`` as a marker.

    Returns ``(read, skipped, checked, wrong)``: how many titled widgets were
    read, how many standard buttons were skipped, the ``(kind, title)`` of each
    title that holds a ``&``, and ``(kind, title, shown)`` for each whose
    displayed text is not its title with ``&&`` as one literal ``&``.
    """
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import (QAbstractButton, QDialogButtonBox,
                                   QGroupBox, QLabel, QMessageBox)

    widgets = [(w, w.title()) for w in root.findChildren(QGroupBox)]
    skipped = 0
    for b in root.findChildren(QAbstractButton):
        box = b.parent()
        while box is not None and not isinstance(
                box, (QDialogButtonBox, QMessageBox)):
            box = box.parent()
        if (box is not None and box.standardButton(b)
                != type(box).StandardButton.NoButton):
            skipped += 1
            continue
        widgets.append((b, b.text()))
    widgets += [(w, w.text()) for w in root.findChildren(QLabel)
                if w.buddy() is not None]

    checked, wrong = [], []
    for w, title in widgets:
        if "&" not in title:
            continue
        kind = type(w).__name__
        checked.append((kind, title))
        shown = QAccessible.queryAccessibleInterface(w).text(
            QAccessible.Text.Name)
        if shown != title.replace("&&", "&"):
            wrong.append((kind, title, shown))
    return len(widgets), skipped, checked, wrong


def _report(read, skipped, checked, wrong):
    lines = [f"read {read}, skipped {skipped} standard buttons, "
             f"{len(checked)} titles hold a '&', {len(wrong)} display wrong:"]
    lines += [f"  {kind}({title!r}) displays {shown!r}; write '&&' for a "
              "literal ampersand" for kind, title, shown in wrong]
    return "\n".join(lines)


@unittest.skipUnless(_QT_OK, _QT_REASON)
class _QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])


class TestTheReadingSeesTheDefect(_QtCase):
    """The control. Each kind the sweep reads, built with the defect and
    without it, so the reading is shown to tell them apart on this Qt."""

    def _one(self, make):
        from PySide6.QtWidgets import QWidget
        root = QWidget()
        make(root)
        return _sweep(root)

    def _kinds(self, title):
        from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox,
                                       QLineEdit, QPushButton, QRadioButton)

        def form_label(root):
            QFormLayout(root).addRow(title, QLineEdit())

        return {
            "QGroupBox": lambda root: QGroupBox(title, root),
            "QCheckBox": lambda root: QCheckBox(title, root),
            "QPushButton": lambda root: QPushButton(title, root),
            "QRadioButton": lambda root: QRadioButton(title, root),
            "QFormLayout row label": form_label,
        }

    def test_a_bare_ampersand_is_caught_in_every_kind(self):
        for kind, make in self._kinds("Comments & junk filter").items():
            with self.subTest(kind=kind):
                read, _, checked, wrong = self._one(make)
                self.assertEqual((read, len(checked)), (1, 1), kind)
                self.assertEqual(len(wrong), 1, f"{kind}: the reading saw "
                                 "nothing wrong with a bare '&'")
                self.assertNotIn("&", wrong[0][2])

    def test_a_doubled_ampersand_passes_in_every_kind(self):
        for kind, make in self._kinds("Comments && junk filter").items():
            with self.subTest(kind=kind):
                read, _, checked, wrong = self._one(make)
                self.assertEqual((read, len(checked), wrong), (1, 1, []), kind)

    def test_a_label_without_a_buddy_is_not_read(self):
        from PySide6.QtWidgets import QLabel
        read, _, _, _ = self._one(lambda root: QLabel("Name & place", root))
        self.assertEqual(read, 0)

    def test_a_standard_button_is_skipped_and_counted(self):
        from PySide6.QtWidgets import QDialogButtonBox, QVBoxLayout
        read, skipped, _, _ = self._one(lambda root: QVBoxLayout(root).addWidget(
            QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)))
        self.assertEqual((read, skipped), (0, 2))


class TestSettingsShowsEveryAmpersand(_QtCase):
    """The dialog the screenshot came from, built for real."""

    def test_every_title_in_settings_displays_its_ampersand(self):
        from PySide6.QtWidgets import QGroupBox
        from app.config import AppConfig
        from app.settings_dialog import SettingsDialog
        d = SettingsDialog(AppConfig())
        read, skipped, checked, wrong = _sweep(d)
        report = _report(read, skipped, checked, wrong)
        # The floors. A sweep that found no widgets, or no title holding a
        # '&', reports exactly what a clean one does.
        self.assertGreaterEqual(len(d.findChildren(QGroupBox)), 8, report)
        self.assertTrue(checked, "no title in Settings holds a '&' any more, "
                        "so this sweep checks nothing. " + report)
        self.assertEqual(wrong, [], report)


class TestWizardButtonShowsItsAmpersand(_QtCase):
    """The sheet-number wizard's "more boxes?" prompt, with ``exec`` replaced
    so the box is built and kept rather than shown modally."""

    def test_finish_and_split_displays_its_ampersand(self):
        from PySide6.QtWidgets import QMessageBox, QWidget
        import app.tools.wizards as wizards

        built = []

        class _Kept(QMessageBox):
            def exec(self):
                built.append(self)
                return 0

        win = QWidget()
        win.view = None
        wiz = wizards.SheetNumberWizard(win)
        with mock.patch.object(wizards, "QMessageBox", _Kept):
            wiz._add_more_or_finish()
        self.assertEqual(len(built), 1, "the prompt was not built")
        read, skipped, checked, wrong = _sweep(built[0])
        report = _report(read, skipped, checked, wrong)
        self.assertGreaterEqual(read + skipped, 3, report)
        self.assertTrue(checked, "no button on the prompt holds a '&' any "
                        "more, so this test checks nothing. " + report)
        self.assertEqual(wrong, [], report)


if __name__ == "__main__":
    unittest.main()
