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

The same marker eats a ``&`` in a NAME the app puts into such a text: a drawing
in File > Open Recent, a workspace or folder in Add to workspace, a commenter
on the "All N by ..." button, a rule pack's title in Settings. Those go
through ``app.qt_text.literal``, and the second half of this module feeds a
name holding ``&`` down each of those four paths.

The displayed text is **read from Qt, never computed here**, by one of two
readers, because neither covers everything:

* **Qt's accessible name** (``_sweep``), the string a screen reader speaks.
  For a title with ONE marker it matches the paint. It strips only the FIRST
  single ``&``, measured 2026-11-01 on PySide6 6.11.3: ``"&1  Pump & Valve"``
  reads ``"1  Pump & Valve"`` while the menu paints *1  Pump _Valve*. So it is
  used only where no title wants a mnemonic, and there any single ``&`` changes
  the reading.
* **``QAction.iconText()``** (``_menu_shown``), which Qt derives by stripping
  EVERY marker and which agrees with the paint in that case. It also drops
  ``...`` and ``…`` and trims, so "New folder…" reads "New folder". Used for
  menus, where Open Recent's ``&1`` is a deliberate mnemonic beside the name.

A copy of Qt's stripping rule in this file would only agree with itself.
``TestTheReadingSeesTheDefect`` proves each reader still strips on the Qt this
runs on, so a Qt that stopped stripping turns this red rather than letting a
test pass over nothing.

A QLabel with no buddy paints ``&`` literally and cannot have this defect, so
it is not read. A standard button (OK, Cancel) takes its text from Qt's
platform theme, where a ``&`` is Qt's own intended mnemonic, so it is counted
as skipped rather than read.
"""

import os
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf  # noqa: E402

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


def _menu_shown(menu):
    """What ``menu`` displays for each item, separators left out: Qt's
    ``iconText``, the item's text with every marker removed."""
    return [a.iconText() for a in menu.actions() if not a.isSeparator()]


def _submenu(menu, shown):
    """The submenu whose item displays ``shown``."""
    return next(a.menu() for a in menu.actions()
                if a.menu() is not None and a.iconText() == shown)


def _kept_message_boxes(module):
    """Patch ``module.QMessageBox`` so ``exec`` keeps each box rather than
    showing it modally, and nothing is clicked. Returns the patcher and the
    list the boxes land in."""
    from PySide6.QtWidgets import QMessageBox
    built = []

    class _Kept(QMessageBox):
        def exec(self):
            built.append(self)
            return 0

    return mock.patch.object(module, "QMessageBox", _Kept), built


def _pdf(path):
    d = pymupdf.open()
    d.new_page(width=300, height=200)
    d.save(path)
    d.close()
    return path


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

    def test_a_menu_reading_sees_a_name_after_a_deliberate_mnemonic(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("&1  Pump & Valve.pdf")
        menu.addAction("&2  Pump && Valve.pdf")
        menu.addMenu("Plant & Site")
        self.assertEqual(_menu_shown(menu), ["1  Pump  Valve.pdf",
                                             "2  Pump & Valve.pdf",
                                             "Plant  Site"])

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
        from PySide6.QtWidgets import QWidget
        import app.tools.wizards as wizards

        win = QWidget()
        win.view = None
        wiz = wizards.SheetNumberWizard(win)
        patcher, built = _kept_message_boxes(wizards)
        with patcher:
            wiz._add_more_or_finish()
        self.assertEqual(len(built), 1, "the prompt was not built")
        read, skipped, checked, wrong = _sweep(built[0])
        report = _report(read, skipped, checked, wrong)
        self.assertGreaterEqual(read + skipped, 3, report)
        self.assertTrue(checked, "no button on the prompt holds a '&' any "
                        "more, so this test checks nothing. " + report)
        self.assertEqual(wrong, [], report)


# -- names from data ------------------------------------------------------------


class TestOpenRecentShowsTheFileName(_QtCase):
    """File > Open Recent: ``&1`` is a deliberate mnemonic, the file name
    beside it is data."""

    def test_a_file_name_keeps_its_ampersand_and_the_number_keeps_its_key(self):
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QMenu
        from app import menus

        folder = tempfile.mkdtemp()
        here = _pdf(os.path.join(folder, "Pump & Valve.pdf"))
        gone = os.path.join(folder, "R&D panel.pdf")          # never created
        win = types.SimpleNamespace(
            m_recent=QMenu(),
            config=types.SimpleNamespace(recent_files=[here, gone]),
            load_document=lambda path: None,
            _clear_recent_files=lambda: None)
        menus.rebuild_recent(win)

        self.assertEqual(_menu_shown(win.m_recent), [
            "1  Pump & Valve.pdf",
            "2  R&D panel.pdf   (not found)",
            "Clear list"])
        keys = [QKeySequence.mnemonic(a.text()).toString()
                for a in win.m_recent.actions()[:2]]
        self.assertEqual(keys, ["Alt+1", "Alt+2"])


class TestAddToWorkspaceShowsTheNames(_QtCase):
    """The Add to workspace menu: workspace names and folder names are both
    read off the disk. ``AppConfig`` is the real per-user store, so the keys
    this touches are put back exactly."""

    def setUp(self):
        from app.config import AppConfig
        from tests.test_add_to_workspace import _KEYS
        self.cfg = AppConfig()
        self._saved = {k: self.cfg.s.value(k) for k in _KEYS}
        for k in _KEYS:
            self.cfg.s.remove(k)
        self.base = tempfile.mkdtemp()
        self.rnd = os.path.join(self.base, "R&D Plant")
        self.site = os.path.join(self.base, "Site & Yard")
        for d in (os.path.join(self.rnd, "drawings"),
                  os.path.join(self.rnd, "Pumps & Valves"),
                  os.path.join(self.site, "drawings")):
            os.makedirs(d)
        self.cfg.add_workspace(self.rnd)
        self.cfg.add_workspace(self.site)
        self.cfg.select_workspace(self.rnd)
        # a quick subfolder is typed in Settings, so it is data too
        self.cfg.set_quick_folders(["drawings", "Specs & data"])
        self.win = types.SimpleNamespace(config=self.cfg)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                self.cfg.s.remove(k)
            else:
                self.cfg.s.setValue(k, v)
        self.cfg.sync()

    def _menu(self, source):
        from PySide6.QtWidgets import QMenu
        from app import add_to_workspace
        menu = QMenu()
        add_to_workspace.populate(menu, self.win, source)
        self._kept = getattr(self, "_kept", []) + [menu]
        return menu

    def test_a_drawing_outside_every_workspace(self):
        os.makedirs(os.path.join(self.base, "Downloads"))
        src = _pdf(os.path.join(self.base, "Downloads", "E-101.pdf"))
        m = self._menu(src)
        self.assertEqual(_menu_shown(m), [
            "R&D Plant", "drawings", "Specs & data",
            "Pumps & Valves", "New folder", "Other workspaces"])
        self.assertEqual(_menu_shown(_submenu(m, "Other workspaces")),
                         ["Site & Yard"])

    def test_a_drawing_already_in_the_workspace(self):
        src = _pdf(os.path.join(self.rnd, "drawings", "E-101.pdf"))
        m = self._menu(src)
        self.assertEqual(_menu_shown(m), [
            "R&D Plant", "Already in R&D Plant", "Other workspaces"])

    def test_an_unavailable_workspace(self):
        os.makedirs(os.path.join(self.base, "Downloads"))
        src = _pdf(os.path.join(self.base, "Downloads", "E-101.pdf"))
        os.rename(self.site, self.site + " moved")
        m = self._menu(src)
        self.assertEqual(_menu_shown(_submenu(m, "Other workspaces")),
                         ["Site & Yard   (unavailable)"])


class TestCommenterButtonShowsTheName(_QtCase):
    """Change commenter, when more than one mark is by the same person: the
    "All N by ..." button carries the name."""

    def test_the_all_button_displays_the_name(self):
        from app import main_window
        from app.model.annotations import Annotation, KIND_COMMENT

        src = _pdf(os.path.join(tempfile.mkdtemp(), "d.pdf"))
        win = main_window.MainWindow()
        win.load_document(src)
        try:
            marks = [Annotation(page=0, kind=KIND_COMMENT, text=t, author="R&D")
                     for t in ("a", "b")]
            for m in marks:
                win.view.store.add(m)
            patcher, built = _kept_message_boxes(main_window)
            with patcher:
                win._edit_author(marks[0])
            self.assertEqual(len(built), 1, "the question was not built")
            read, skipped, checked, wrong = _sweep(built[0])
            report = _report(read, skipped, checked, wrong)
            self.assertTrue(
                any(t.startswith("All 2 by") for _, t in checked),
                "the 'All 2 by' button was not read. " + report)
            self.assertEqual(wrong, [], report)
        finally:
            win.document._dirty = False
            win.close()


class TestRulePackBoxShowsTheTitle(_QtCase):
    """Settings > Design rules lists one box per rule pack, titled by the
    library. The library is replaced by one pack whose title holds ``&``, so
    this runs whether PyDRC is installed or not."""

    def test_a_pack_title_keeps_its_ampersand(self):
        from app.config import AppConfig
        from app.settings_dialog import SettingsDialog
        import app.audit as audit
        import app.audit.runner as runner

        pack = ("erc-heat", "Heat & cooling", "erc-heat@1.2.0", "a description")
        with mock.patch.object(audit, "status", return_value=(True, "ok")), \
                mock.patch.object(runner, "available_packs", return_value=[pack]), \
                mock.patch.object(runner, "default_packs", return_value=("erc-heat",)), \
                mock.patch.object(runner, "unloadable_packs", return_value=[]), \
                mock.patch.object(runner, "unreadable_pack_files", return_value=[]), \
                mock.patch.object(runner, "available_rules", return_value=[]):
            d = SettingsDialog(AppConfig())
        self.assertEqual([pack_id for pack_id, _ in d.drc_packs], ["erc-heat"],
                         "the dialog did not list the pack it was given")
        read, skipped, checked, wrong = _sweep(d)
        report = _report(read, skipped, checked, wrong)
        self.assertTrue(
            any(t.startswith("erc-heat@1.2.0") for _, t in checked),
            "the pack's box was not read. " + report)
        self.assertEqual(wrong, [], report)


if __name__ == "__main__":
    unittest.main()
