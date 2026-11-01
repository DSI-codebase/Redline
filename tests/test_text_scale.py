"""Settings ▸ General ▸ Text size: every piece of UI text follows one percentage.

``app/text_scale.py`` multiplies the platform's application font. Qt carries
that change to most widgets and not to all of them, so the gates here drive the
REAL window and dialogs and measure what Qt drew, rather than reading a list of
the places that were converted on the day this was written:

- every widget in the window doubles at 200% and is back to its exact size at
  100%. Measured before ``text_scale`` existed: 143 of 602 widgets kept their
  size, 116 of them inside a stylesheet's subtree and 27 with a size written
  into the app.
- a window changed to 300% is laid out like one BUILT at 300%, widget for
  widget, and draws the same pixels, pane by pane. The layout half sees a
  size Qt measured once and kept: deleting the style-change broadcast in
  ``_refresh`` moved 119 of 230 on-screen widgets. The pixel half was added
  when every gate here was green and a 300% screenshot still showed each
  dock's title in 100% type: the bar had grown, and nothing that measures
  layout can see what is painted inside it.
- a table row holds a line of its text, a platform's per-class fonts survive,
  the splash keeps its size, and no stylesheet carries a font size outside
  ``text_scale.style``.

Each gate runs the window at a saved 100% first, whatever the machine running
it has saved, and puts the saved value back.
"""

from __future__ import annotations

import ast
import os
import pathlib
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

REPO = pathlib.Path(__file__).resolve().parent.parent
APP = REPO / "app"

if _QT_OK:
    from PySide6.QtCore import QPoint, QRect, QSize
    from PySide6.QtGui import QFont, QFontInfo
    from PySide6.QtWidgets import QApplication, QTableView, QWidget


def _settle(app, rounds=20):
    # A dock or a word-wrapped label lays out over several posted events.
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.02)


def _paths(top):
    """``{path: widget}`` for every widget in ``top``'s own window, where a
    path names each ancestor by class, object name and index among siblings
    alike. Two windows built the same way have the same paths; ``findChildren``
    ORDER is not a pairing, because Qt raises a widget to the end of its
    parent's list on relayout."""
    out = {}

    def walk(w, prefix):
        seen = {}
        for c in w.children():
            if not isinstance(c, QWidget) or QWidget.window(c) is not top:
                continue
            key = (type(c).__name__, c.objectName())
            i = seen.get(key, 0)
            seen[key] = i + 1
            path = prefix + (key + (i,),)
            out[path] = c
            walk(c, path)

    walk(top, ())
    return out


def _text_px(widget) -> int:
    return QFontInfo(widget.font()).pixelSize()


class _AtSavedSize(unittest.TestCase):
    """Saves ``ui/text_scale``, starts at 100%, and puts both back."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import text_scale
        from app.config import AppConfig
        self.ts = text_scale
        self.cfg = AppConfig()
        saved = self.cfg.s.value("ui/text_scale")
        self.addCleanup(self._restore, saved)
        self.save(100)
        text_scale.apply(100)

    def _restore(self, saved):
        self.ts.apply(100)
        if saved is None:
            self.cfg.s.remove("ui/text_scale")
        else:
            self.cfg.set("ui/text_scale", saved)
        self.cfg.sync()

    def save(self, percent):
        self.cfg.set("ui/text_scale", percent)
        self.cfg.sync()

    def window(self):
        from app.main_window import MainWindow
        win = MainWindow()
        win.show()
        self.addCleanup(win.deleteLater)
        _settle(self.app)
        return win


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestTheSetting(_AtSavedSize):
    def test_defaults_to_100_and_is_held_to_its_bounds(self):
        from app.config import TEXT_SCALE_BOUNDS
        lo, hi = TEXT_SCALE_BOUNDS
        self.assertEqual((lo, hi), (50, 300))
        self.cfg.s.remove("ui/text_scale")
        self.assertEqual(self.cfg.text_scale, 100)
        for saved, read in ((20, lo), (900, hi), (175, 175), ("junk", 100)):
            self.save(saved)
            self.assertEqual(self.cfg.text_scale, read, f"saved {saved!r}")

    def test_100_changes_nothing_at_all(self):
        """A launch at the default must leave Qt's fonts as the platform set
        them, class fonts included, so it returns before touching one."""
        self.assertFalse(self.ts.apply(100))
        self.assertEqual(self.ts.percent(), 100)

    def test_a_size_of_zero_is_refused(self):
        with self.assertRaises(ValueError):
            self.ts.apply(0)


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestTheSlider(_AtSavedSize):
    def dialog(self):
        from app.settings_dialog import SettingsDialog
        d = SettingsDialog(self.cfg)
        self.addCleanup(d.deleteLater)
        return d

    def test_ranges_over_the_bounds_and_shows_the_saved_size(self):
        from app.config import TEXT_SCALE_BOUNDS
        self.save(150)
        d = self.dialog()
        self.assertEqual((d.text_scale.minimum(), d.text_scale.maximum()),
                         TEXT_SCALE_BOUNDS)
        self.assertEqual(d.text_scale.value(), 150)
        self.assertEqual(d.text_scale_pct.text(), "150%")

    def test_snaps_to_the_step_and_resets_to_100(self):
        d = self.dialog()
        d.text_scale.setValue(137)
        self.assertEqual(d.text_scale.value(), 135)
        self.assertEqual(d.text_scale_pct.text(), "135%")
        d.btn_text_scale_reset.click()
        self.assertEqual(d.text_scale.value(), 100)

    def test_the_sample_is_drawn_at_the_slider_size(self):
        d = self.dialog()
        base = QFontInfo(self.ts.base_font()).pixelSize()
        d.text_scale.setValue(300)
        self.assertGreaterEqual(_text_px(d.text_scale_sample), base * 2.8)
        d.text_scale.setValue(100)
        self.assertEqual(_text_px(d.text_scale_sample), base)

    def test_ok_saves_it_and_cancel_changes_nothing(self):
        d = self.dialog()
        d.text_scale.setValue(200)
        self.assertEqual(self.ts.percent(), 100, "the app changed before OK")
        d.apply()
        self.assertEqual(self.cfg.text_scale, 200)

    def test_the_window_applies_it_on_ok(self):
        from PySide6.QtWidgets import QDialog
        from app import main_window
        win = self.window()

        class _Accepting(main_window.SettingsDialog):
            def exec(self_):
                self_.text_scale.setValue(200)
                return QDialog.Accepted

        original = main_window.SettingsDialog
        main_window.SettingsDialog = _Accepting
        self.addCleanup(setattr, main_window, "SettingsDialog", original)
        win.open_settings()
        self.assertEqual(self.ts.percent(), 200)

    def test_the_manual_states_the_bounds_the_code_holds(self):
        from app.config import TEXT_SCALE_BOUNDS
        text = (REPO / "docs" / "Settings.md").read_text(encoding="utf-8")
        start = text.index("### Text size")
        section = text[start:text.index("\n#", start + 1)]
        for bound in TEXT_SCALE_BOUNDS:
            self.assertIn(f"{bound}%", section)


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestEveryWidgetFollows(_AtSavedSize):
    def test_every_widget_doubles_at_200_and_comes_back_exactly(self):
        win = self.window()
        before = {p: _text_px(w) for p, w in _paths(win).items()}
        # The floor. An empty window agrees with any assertion below.
        self.assertGreater(len(before), 400, f"walked {len(before)} widgets")
        self.ts.apply(200)
        _settle(self.app)
        now = _paths(win)
        stuck = sorted(f"{p[-1]} {before[p]}px -> {_text_px(now[p])}px"
                       for p in before if p in now
                       and _text_px(now[p]) < before[p] * 1.8)
        self.assertEqual(stuck, [], "text that did not follow 200%")
        self.ts.apply(100)
        _settle(self.app)
        now = _paths(win)
        moved = sorted(f"{p[-1]} {before[p]}px -> {_text_px(now[p])}px"
                       for p in before if p in now
                       and _text_px(now[p]) != before[p])
        self.assertEqual(moved, [], "text not back to its size at 100%")

    def test_a_window_changed_to_300_looks_like_one_built_at_300(self):
        """Laid out the same, widget by widget, and then DRAWN the same, pixel
        for pixel. The layout half names the widget that moved. The pixel half
        sees what a layout cannot: a dock's title bar grew with the text while
        the words in it were painted at 100%, from a font Qt copies once."""
        changed = self.window()
        self.save(300)
        self.ts.apply(300)
        built = self.window()
        size = changed.minimumSizeHint().expandedTo(
            built.minimumSizeHint()).expandedTo(QSize(1320, 880))
        changed.resize(size)
        built.resize(size)
        compared, differ, drawn = set(), set(), []
        # Each pane in turn: a tabified dock that is not the current tab sits
        # outside the window and keeps the size it last had, so it is not on
        # screen to compare until it is brought forward.
        panes = list(zip(changed.tabs._order, built.tabs._order))
        self.assertGreaterEqual(len(panes), 5)
        for pane_a, pane_b in panes:
            changed.tabs.setCurrentWidget(pane_a)
            built.tabs.setCurrentWidget(pane_b)
            _settle(self.app, 8)
            a, b = _paths(changed), _paths(built)
            for p, w in a.items():
                if p in b and w.isVisible() and changed.rect().intersects(
                        QRect(w.mapTo(changed, QPoint(0, 0)), w.size())):
                    compared.add(p)
                    if w.geometry() != b[p].geometry():
                        differ.add(f"{p[-1]}: {w.geometry().getRect()} changed, "
                                   f"{b[p].geometry().getRect()} built")
            ia, ib = changed.grab().toImage(), built.grab().toImage()
            self.assertFalse(ia.isNull())
            if ia != ib:
                rows = [y for y in range(min(ia.height(), ib.height()))
                        if any(ia.pixel(x, y) != ib.pixel(x, y)
                               for x in range(0, min(ia.width(), ib.width()), 2))]
                drawn.append(f"{type(pane_a).__name__}: {len(rows)} rows differ, "
                             f"y {rows[:1]} to {rows[-1:]}")
        # The floor catches a walk that broke and compared nothing; it is not
        # a count of the window (227 on screen across the panes when written).
        self.assertGreater(len(compared), 150, f"compared {len(compared)}")
        self.assertEqual(sorted(differ), [])
        self.assertEqual(drawn, [], "laid out alike and drawn differently")

    def test_a_table_row_holds_a_line_of_its_text(self):
        """Rows that EXIST when the size changes. A row added afterwards takes
        the table's new default anyway, so an empty table proves nothing, and
        the first version of this gate passed on the window's empty tables.
        Falsified by deleting the style-change broadcast: rows stay 30 px."""
        win = self.window()
        tables = [t for t in win.findChildren(QTableView)
                  if hasattr(t, "setRowCount")]
        self.assertGreaterEqual(len(tables), 2, "no tables to measure")
        for t in tables:
            t.setRowCount(2)
        at_100 = {id(t): t.rowHeight(0) for t in tables}
        self.ts.apply(300)
        for t in tables:
            self.assertGreaterEqual(t.rowHeight(0), t.fontMetrics().height(),
                                    type(t.parent()).__name__)
        self.ts.apply(100)
        for t in tables:
            self.assertEqual(t.rowHeight(0), at_100[id(t)])

    def test_nothing_is_held_smaller_than_its_own_text_at_300(self):
        """A fixed width that holds text and was not scaled is the same in a
        window changed to 300% and one built there, so the comparison above
        cannot see it. This asks each widget instead: is its size capped below
        the minimum its own content asks for? Falsified by setting the zoom
        box's 72 px plainly: it needs 129 at 300%."""
        win = self.window()
        self.ts.apply(300)
        seen, capped = 0, set()
        for pane in win.tabs._order:
            win.tabs.setCurrentWidget(pane)
            _settle(self.app, 5)
            for w in win.findChildren(QWidget):
                if not w.isVisible():
                    continue
                seen += 1
                need = w.minimumSizeHint()
                if (0 < w.maximumWidth() < need.width()
                        or 0 < w.maximumHeight() < need.height()):
                    capped.add(f"{type(w).__name__} {w.objectName()!r} in "
                               f"{type(w.parentWidget()).__name__}: held to "
                               f"{w.maximumWidth()} x {w.maximumHeight()}, "
                               f"needs {need.width()} x {need.height()}")
        self.assertGreater(seen, 500, f"looked at {seen} widgets")
        self.assertEqual(sorted(capped), [])

    def test_fixed_lengths_that_hold_text_follow(self):
        win = self.window()
        carried = [w for w in QApplication.allWidgets()
                   if w.property(self.ts.PROP_SIZES)]
        self.assertGreaterEqual(len(carried), 8, "sized() is not in use")
        before = {id(w): (w.minimumWidth(), w.maximumWidth(),
                          w.minimumHeight(), w.maximumHeight()) for w in carried}
        self.ts.apply(200)
        _settle(self.app, 5)
        import json
        exact = 0
        for w in carried:
            need = w.minimumSizeHint()
            for setter, value in json.loads(w.property(self.ts.PROP_SIZES)).items():
                getter = {"setFixedWidth": w.maximumWidth,
                          "setFixedHeight": w.maximumHeight,
                          "setMinimumWidth": w.minimumWidth,
                          "setMinimumHeight": w.minimumHeight,
                          "setMaximumWidth": w.maximumWidth,
                          "setMaximumHeight": w.maximumHeight}[setter]
                # A cap follows the scale exactly, unless the widget's own
                # content asks for more, and then exactly that (point 5).
                want = value * 2
                if setter in self.ts._CAPS:
                    want = max(want, need.width() if setter.endswith("Width")
                               else need.height())
                self.assertEqual(getter(), want, f"{type(w).__name__} {setter}")
                exact += getter() == value * 2
        # The floor: lengths that simply doubled. On Ubuntu that is every one.
        self.assertGreaterEqual(exact, 4, "sized() lengths did not follow the scale")
        self.ts.apply(100)
        for w in carried:
            self.assertEqual((w.minimumWidth(), w.maximumWidth(),
                              w.minimumHeight(), w.maximumHeight()), before[id(w)])
        self.assertIsNotNone(win)

    def _frame(self, width):
        """A frame sized at 100% narrower than the one line of text it holds,
        the way the Windows runner's fonts left the PDF Tools options panel at
        300% (point 5 of app/text_scale.py)."""
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton
        frame = QFrame()
        self.ts.sized(frame, setFixedWidth=width)
        QHBoxLayout(frame).addWidget(
            QPushButton("Merge the extracted pages into one PDF file"))
        frame.show()
        self.addCleanup(self._delete_now, frame)
        _settle(self.app, 5)
        return frame

    def _delete_now(self, widget):
        # Deleted before the next test, not at some later event loop: a
        # leftover sized frame is in the allWidgets() sweeps that follow.
        from PySide6.QtCore import QEvent
        widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_a_cap_is_never_below_its_own_text(self):
        """Changed to 300% and built at 300%, the frame is as wide as its
        text, the same width both ways. At 100% it is the width written, as
        in every earlier release. Falsified by the floor removed from
        _apply_sizes, by the filter not installed (the built frame stays
        capped) and by the floor applied at 100% too, each red."""
        width = 40
        changed = self._frame(width)
        self.assertGreater(changed.minimumSizeHint().width(), width,
                           "the text fits, so this proves nothing")
        self.assertEqual(changed.maximumWidth(), width)
        self.ts.apply(300)
        _settle(self.app, 5)
        need = changed.minimumSizeHint().width()
        self.assertGreater(need, width * 3, "the text fits at 300%")
        self.assertEqual(changed.maximumWidth(), need)
        built = self._frame(width)
        self.assertEqual(built.maximumWidth(), built.minimumSizeHint().width())
        self.assertEqual(built.maximumWidth(), changed.maximumWidth())
        self.ts.apply(100)
        _settle(self.app, 5)
        self.assertEqual((changed.maximumWidth(), built.maximumWidth()),
                         (width, width))


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestWhatIsNotTheWindow(_AtSavedSize):
    def test_the_platforms_class_fonts_survive_and_scale(self):
        """``QApplication.setFont`` clears every per-class font a platform
        theme set (Windows sets the menu, message box, status bar, tooltip and
        dock-title fonts). Offscreen sets none, so one is planted."""
        saved_base = self.ts._base
        app_font = QApplication.font()
        menu = QFont(app_font)
        menu.setPointSizeF(app_font.pointSizeF() + 2)
        QApplication.setFont(menu, "QMenu")
        self.ts._base = None

        def undo():
            QApplication.setFont(app_font)      # clears the planted class font
            self.ts._base = saved_base
        self.addCleanup(undo)

        self.ts.apply(200)
        self.assertAlmostEqual(QApplication.font("QMenu").pointSizeF(),
                               menu.pointSizeF() * 2)
        self.assertAlmostEqual(QApplication.font().pointSizeF(),
                               app_font.pointSizeF() * 2)
        self.ts.apply(100)
        self.assertAlmostEqual(QApplication.font("QMenu").pointSizeF(),
                               menu.pointSizeF())

    def test_the_splash_keeps_its_size(self):
        """A fixed 440 x 280 panel shown while the window applies the size."""
        from app.splash import SplashScreen
        splash = SplashScreen("DSI Redline", "0")
        splash.show()
        self.addCleanup(splash.deleteLater)
        _settle(self.app, 3)
        before = {p: _text_px(w) for p, w in _paths(splash).items()}
        self.assertGreaterEqual(len(before), 3)
        self.ts.apply(200)
        _settle(self.app, 3)
        after = {p: _text_px(w) for p, w in _paths(splash).items()}
        self.assertEqual(after, before)

    def test_a_dialog_built_at_200_is_twice_the_one_built_at_100(self):
        from app.dialogs import FillDialog, TextEditDialog
        from app.model.annotations import Annotation, KIND_COMMENT
        from app.settings_dialog import SettingsDialog

        def build():
            out = [SettingsDialog(self.cfg),
                   FillDialog((1.0, 0.0, 0.0), 0.5),
                   TextEditDialog(Annotation(page=0, kind=KIND_COMMENT,
                                             rect=(0, 0, 10, 10)))]
            for d in out:
                d.show()
                self.addCleanup(d.deleteLater)
            _settle(self.app, 3)
            return [{p: _text_px(w) for p, w in _paths(d).items()} for d in out]

        at_100 = build()
        self.save(200)
        self.ts.apply(200)
        at_200 = build()
        self.assertGreater(sum(map(len, at_100)), 100)
        for small, big in zip(at_100, at_200):
            self.assertGreater(len(small), 4)
            stuck = sorted(f"{p[-1]} {small[p]}px -> {big[p]}px"
                           for p in small if p in big and big[p] < small[p] * 1.8)
            self.assertEqual(stuck, [])


class TestNoStylesheetCarriesItsOwnFontSize(unittest.TestCase):
    """A ``font-size`` passed straight to ``setStyleSheet`` stays that size at
    every setting, and a dialog built on demand is not in the window the sweep
    above walks. So the rule is read off the source, structurally: the string
    pieces inside a ``setStyleSheet(...)`` call's argument, never a regex over
    the file, which would match this docstring."""

    def _calls(self):
        for path in sorted(APP.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)):
                    yield path, node

    @staticmethod
    def _strings(node):
        return [n.value for arg in node.args for n in ast.walk(arg)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    def test_every_font_size_goes_through_text_scale_style(self):
        direct, routed, offenders = 0, 0, []
        for path, call in self._calls():
            name = call.func.attr
            if name == "setStyleSheet":
                direct += 1
                if any("font-size" in s or "font:" in s
                       for s in self._strings(call)):
                    offenders.append(f"{path.relative_to(REPO)}:{call.lineno}")
            elif (name == "style" and isinstance(call.func.value, ast.Name)
                  and call.func.value.id == "text_scale"):
                routed += 1
        # Floors on both halves: a sweep that found no calls passes, and so
        # does one whose route nobody takes.
        self.assertGreater(direct, 10, f"inspected {direct} setStyleSheet calls")
        self.assertGreaterEqual(routed, 5, f"found {routed} text_scale.style calls")
        self.assertEqual(offenders, [], (
            "a stylesheet font size outside text_scale.style stays that size "
            "whatever Settings ▸ Text size says"))


if __name__ == "__main__":
    unittest.main()
