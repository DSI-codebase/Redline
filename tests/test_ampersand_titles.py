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

A QMenu entry does the same, measured offscreen on PySide6 6.11.3 the same
day: ``"Comments & junk"`` painted as *Comments junk* and bound Alt+Space.
Four labels are built from a user's data rather than written here, and each
now doubles the data's ``&``: the File > Open Recent entries (a drawing's file
name), the Add to workspace menu (workspace and folder names), the "All N by
<name>" button when changing a commenter, and the rule pack boxes in
Settings (a pack's ref, title or id). The tests below feed a name holding ``&`` through
each real code path.

The displayed text is **read from Qt, never computed here**. Qt's accessible
name for a titled widget is the string a screen reader speaks: its title with
the FIRST mnemonic marker removed and each ``&&`` read as one ``&``. That is
what the widget paints while the title holds at most one marker, which every
title read by ``_sweep`` does. A copy of Qt's stripping rule in this file would
only agree with itself. ``TestTheReadingSeesTheDefect`` proves the reading
still strips on the Qt this runs on, so a Qt that stopped stripping turns this
red rather than letting the sweep pass over nothing.

The accessible name cannot see a second marker, which is why the Open Recent
entries are read another way. Each starts with a deliberate ``&1``..``&0``,
and that one uses up the strip: measured 2026-11-01 on PySide6 6.11.3,
``"&1  R&D wiring.pdf"`` reads back as ``"1  R&D wiring.pdf"`` from a QMenu
entry and from a QPushButton, while the menu paints *1 RD wiring.pdf* with the
1 and the D underlined. So those entries are read by **painting**: Qt's own
text layout draws the entry's text with every marker processed and the
underline hidden, and that must be the same pixels as the intended text drawn
as is. ``TestThePaintingSeesPastADeliberateMnemonic`` is its control.

A QLabel with no buddy paints ``&`` literally and cannot have this defect, so
it is not read. A standard button (OK, Cancel) takes its text from Qt's
platform theme, where a ``&`` is Qt's own intended mnemonic, so it is counted
as skipped rather than read.
"""

import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON  # noqa: E402


def _sweep(root):
    """Read every widget and menu entry under ``root`` that treats ``&`` as a
    marker. For titles with no deliberate mnemonic in them: a title like
    ``"&1  R&&D"`` would be counted wrong, because the reading expects
    ``"&1  R&D"``.

    Returns ``(read, skipped, checked, wrong)``: how many titles were read, how
    many standard buttons were skipped, the ``(kind, title)`` of each title
    that holds a ``&``, and ``(kind, title, shown)`` for each whose displayed
    text is not its title with ``&&`` as one literal ``&``.
    """
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import (QAbstractButton, QDialogButtonBox,
                                   QGroupBox, QLabel, QMenu, QMessageBox)

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
    items = [(type(w).__name__, title, QAccessible.queryAccessibleInterface(w))
             for w, title in widgets]

    # A menu entry is a QAction, not a widget. The menu's accessible child
    # ``i`` is its action ``i``, separators included, and a submenu's title is
    # the entry in its parent that opens it.
    menus = root.findChildren(QMenu)
    if isinstance(root, QMenu):
        menus.insert(0, root)
    for menu in menus:
        iface = QAccessible.queryAccessibleInterface(menu)
        for i, action in enumerate(menu.actions()):
            if not action.isSeparator():
                items.append(("QMenu entry", action.text(), iface.child(i)))

    checked, wrong = [], []
    for kind, title, iface in items:
        if "&" not in title:
            continue
        checked.append((kind, title))
        shown = iface.text(QAccessible.Text.Name)
        if shown != title.replace("&&", "&"):
            wrong.append((kind, title, shown))
    return len(items), skipped, checked, wrong


def _shown(checked):
    """The display text each checked title is meant to have."""
    return {title.replace("&&", "&") for _kind, title in checked}


def _painted(text, flags):
    """``text`` drawn by Qt's text layout into an image, black on white."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    img = QImage(1200, 40, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setFont(QApplication.font())
    p.setPen(QColor("black"))
    p.drawText(QRect(0, 0, 1200, 40),
               int(flags) | int(Qt.AlignmentFlag.AlignLeft)
               | int(Qt.AlignmentFlag.AlignVCenter), text)
    p.end()
    return img


def _paints_as(text, visible):
    """Whether an entry whose text is ``text`` shows ``visible``.

    ``text`` is drawn with every single ``&`` read as a marker and each ``&&``
    as one ``&``, the underline hidden so a deliberate mnemonic is no
    difference. ``visible`` is drawn as is. Refuses a ``visible`` that paints
    nothing, which would make any two texts look alike.
    """
    from PySide6.QtCore import Qt
    want = _painted(visible, 0)
    if want == _painted("", 0):
        raise AssertionError(f"{visible!r} painted nothing, so the reading "
                             "cannot tell one text from another")
    return _painted(text, Qt.TextFlag.TextHideMnemonic) == want


def _private_config(case):
    """An ``AppConfig`` over an INI file of its own, so a test never writes
    the per-user settings store."""
    from PySide6.QtCore import QSettings
    from app.config import AppConfig
    folder = tempfile.mkdtemp()
    case.addCleanup(shutil.rmtree, folder, True)
    cfg = AppConfig()
    cfg.s = QSettings(os.path.join(folder, "settings.ini"),
                      QSettings.Format.IniFormat)
    return cfg


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
                                       QLineEdit, QMenu, QPushButton,
                                       QRadioButton)

        def form_label(root):
            QFormLayout(root).addRow(title, QLineEdit())

        return {
            "QGroupBox": lambda root: QGroupBox(title, root),
            "QCheckBox": lambda root: QCheckBox(title, root),
            "QPushButton": lambda root: QPushButton(title, root),
            "QRadioButton": lambda root: QRadioButton(title, root),
            "QFormLayout row label": form_label,
            "QMenu entry": lambda root: QMenu(root).addAction(title),
            "QMenu submenu": lambda root: QMenu(root).addMenu(title),
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


class TestThePaintingSeesPastADeliberateMnemonic(_QtCase):
    """The control for ``_paints_as``, on an Open Recent entry's shape."""

    VISIBLE = "1  R&D wiring.pdf"

    def test_a_bare_ampersand_after_a_mnemonic_paints_wrong(self):
        self.assertFalse(_paints_as("&1  R&D wiring.pdf", self.VISIBLE))

    def test_a_doubled_ampersand_after_a_mnemonic_paints_right(self):
        self.assertTrue(_paints_as("&1  R&&D wiring.pdf", self.VISIBLE))

    def test_the_intended_text_is_drawn_with_its_ampersand(self):
        """If ``visible`` lost its ``&`` too, the bare entry would match it."""
        self.assertNotEqual(_painted(self.VISIBLE, 0),
                            _painted("1  RD wiring.pdf", 0))

    def test_a_text_that_paints_nothing_is_refused(self):
        with self.assertRaises(AssertionError):
            _paints_as("&1", "")

    def test_a_menu_paints_the_bare_and_the_doubled_entry_differently(self):
        """The menu itself reads the second ``&`` as a marker, so what the
        painting reads is a defect the menu has."""
        from PySide6.QtWidgets import QMenu

        def grab(text):
            menu = QMenu()
            menu.addAction(text)
            menu.adjustSize()
            return menu.grab().toImage()

        self.assertNotEqual(grab("&1  R&D wiring.pdf"),
                            grab("&1  R&&D wiring.pdf"))


class TestOpenRecentShowsTheFileName(_QtCase):
    """File > Open Recent, filled by the real ``menus.rebuild_recent`` from a
    list holding one drawing that exists and one that does not."""

    def test_each_entry_shows_its_name_and_keeps_its_number_key(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QMenu
        from app import menus

        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        here = os.path.join(folder, "R&D wiring.pdf")
        with open(here, "wb") as fh:
            fh.write(b"%PDF-1.7\n")
        gone = os.path.join(folder, "Q&A notes.pdf")
        win = types.SimpleNamespace(
            m_recent=QMenu(),
            config=types.SimpleNamespace(recent_files=[here, gone]),
            load_document=lambda path: None,
            _clear_recent_files=lambda: None)
        menus.rebuild_recent(win)

        entries = [a for a in win.m_recent.actions()
                   if a.toolTip() in (here, gone)]
        self.assertEqual(len(entries), 2, [a.text() for a in
                                           win.m_recent.actions()])
        want = {here: (1, "1  R&D wiring.pdf"),
                gone: (2, "2  Q&A notes.pdf   (not found)")}
        for action in entries:
            number, visible = want[action.toolTip()]
            with self.subTest(entry=action.text()):
                self.assertTrue(
                    _paints_as(action.text(), visible),
                    f"the entry {action.text()!r} does not show {visible!r}. "
                    "Write the file name's '&' as '&&'.")
                self.assertEqual(
                    QKeySequence.mnemonic(action.text()),
                    QKeySequence(Qt.Modifier.ALT | Qt.Key(Qt.Key.Key_0 + number)),
                    f"the entry {action.text()!r} lost its Alt+{number}")


class TestAddToWorkspaceShowsTheNames(_QtCase):
    """The Add to workspace menu, filled by the real
    ``add_to_workspace.populate``. Every name in it holds a ``&``: the
    workspaces, a quick folder, and a folder on disk."""

    def setUp(self):
        from app.model import workspaces as W
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.smith = os.path.join(self.base, "Smith & Sons")
        self.plant = os.path.join(self.base, "Plant & Mill")
        gone = os.path.join(self.base, "Gone & Back")
        for d in (os.path.join(self.smith, "R&D"), self.plant, gone):
            os.makedirs(d)
        cfg = _private_config(self)
        for root in (self.smith, self.plant, gone):
            cfg.add_workspace(root)
        cfg.select_workspace(self.smith)
        cfg.set_quick_folders(["drawings", "Q&A"])
        os.rename(gone, gone + " moved")
        self.assertEqual([w.display_name for w in W.ordered(cfg.workspaces())
                          if not w.available], ["Gone & Back"])
        self.win = types.SimpleNamespace(config=cfg)

    def _read(self, source, want):
        from PySide6.QtWidgets import QMenu
        from app import add_to_workspace
        menu = QMenu()
        add_to_workspace.populate(menu, self.win, source)
        read, skipped, checked, wrong = _sweep(menu)
        report = _report(read, skipped, checked, wrong)
        self.assertEqual(want - _shown(checked), set(),
                         "an entry the menu should hold was not read. " + report)
        self.assertEqual(wrong, [], report)

    def test_a_drawing_outside_every_workspace(self):
        """The heading, a quick folder, a folder on disk, a workspace that is
        there and one that is not."""
        self._read(os.path.join(self.base, "E-101.pdf"),
                   {"Smith & Sons", "Q&A", "R&D", "Plant & Mill",
                    "Gone & Back   (unavailable)"})

    def test_a_drawing_already_in_a_workspace(self):
        self._read(os.path.join(self.plant, "E-101.pdf"),
                   {"Plant & Mill", "Already in Plant & Mill", "Smith & Sons"})


class TestCommenterButtonShowsTheName(_QtCase):
    """Changing the commenter on a mark when another mark has the same one:
    the real ``MainWindow._edit_author``, with ``exec`` replaced so the box is
    built and kept rather than shown modally."""

    def test_all_by_the_name_displays_its_ampersand(self):
        from PySide6.QtWidgets import QMessageBox, QWidget
        import app.main_window as main_window
        from app.model.annotations import Annotation, KIND_RECT

        built = []

        class _Kept(QMessageBox):
            def exec(self):
                built.append(self)
                return 0

        marks = [Annotation(page=0, kind=KIND_RECT, author="R&D")
                 for _ in range(2)]
        win = QWidget()
        win.document = types.SimpleNamespace(
            store=types.SimpleNamespace(all=lambda: marks))
        with mock.patch.object(main_window, "QMessageBox", _Kept):
            main_window.MainWindow._edit_author(win, marks[0])
        self.assertEqual(len(built), 1, "the question was not built")
        read, skipped, checked, wrong = _sweep(built[0])
        report = _report(read, skipped, checked, wrong)
        self.assertIn("All 2 by “R&D”", _shown(checked), report)
        self.assertEqual(wrong, [], report)


class TestRulePackBoxesShowTheTitle(_QtCase):
    """Settings, Design rules: one box per rule pack, labeled from the pack.
    The rule library is replaced by stand-ins so a pack title holding ``&``
    reaches the real dialog whether or not PyDRC is installed. No pack in
    PyDRC 0.24.0 has one, so a real pack cannot show this."""

    def test_each_pack_box_displays_its_ampersand(self):
        from app import audit
        from app.audit import runner
        from app.settings_dialog import SettingsDialog

        stand_ins = {
            "available_packs": lambda *a, **k: [
                ("wiring", "Wiring & labels", "WIR-1", "a pack")],
            "unloadable_packs": lambda *a, **k: [("r&d", "a reason")],
            "unreadable_pack_files": lambda *a, **k: [],
            "default_packs": lambda: ("wiring",),
            "available_rules": lambda *a, **k: [],
        }
        with mock.patch.object(audit, "status",
                               lambda: (True, "stand-in rule library")):
            with mock.patch.multiple(runner, **stand_ins):
                d = SettingsDialog(_private_config(self))
        read, skipped, checked, wrong = _sweep(d)
        report = _report(read, skipped, checked, wrong)
        self.assertEqual({"WIR-1 — Wiring & labels", "r&d (will not load)"}
                         - _shown(checked), set(),
                         "a pack box was not read. " + report)
        self.assertEqual(wrong, [], report)


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
