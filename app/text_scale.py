"""Settings ▸ General ▸ Text size: all UI text as a percentage of the platform's.

100% is the size the platform gives the app, which is what every release before
this one drew. The percentage multiplies that one font, and everything else is
made to follow it rather than given its own size.

Three things in Qt do NOT follow ``QApplication.setFont`` on their own, and each
was measured on the real window before it was written down here (602 widgets,
doubling the application font):

1. **A stylesheeted subtree keeps its old font.** Qt hands a font change to a
   child with ``WA_StyleSheet`` only through its parent's stylesheet style, so
   the topmost widget of a subtree whose stylesheet was set on it is skipped,
   and so is everything under it: 116 widgets, the whole PDF Tools workspace
   and the File view's lists among them. :func:`apply` sets each stylesheet
   again, top down, which repolishes the subtree against the new font.
2. **A size written into the app stays that size.** ``font-size: 14px`` in a
   stylesheet, an explicit ``QFont`` size, and a fixed width that holds text
   (the zoom box, the PDF Tools rail) are each written at 100% and go through
   :func:`style`, :func:`set_font` or :func:`sized`, which keep the 100% value
   on the widget and apply it scaled, now and after every change. 27 widgets
   carried one.
3. **A size Qt measured from the font once is kept until a style change.**
   A dock's title bar height and a table's rows keep what they were built
   with (a row is 30 px from the style, so a 300% line in a table built at
   100% is cut in half). :func:`apply` sends every widget the event a style
   change would, and both measure again.
4. **A dock paints its title with a font it copied once and never again.**
   ``QDockWidgetPrivate::init`` stores ``QApplication::font("QDockWidgetTitle")``
   and the paint reads that copy, so the bar grows and the words in it do not.
   Each dock that exists at a change gets a paint filter that draws the title
   the way Qt does, with the font read when it paints. A dock built later
   copies the right one, and a launch at 100% installs nothing.
5. **A length written at 100% and multiplied does not hold the same text on
   every platform.** The PDF Tools options panel is 300 px at 100%, and at
   300% the Windows CI runner's fonts asked 1276 px of it where Ubuntu's ask
   675 (Tests run 168, 2026-11-01). So at any size but 100%, a fixed or
   maximum length from :func:`sized` is never less than the widget's own
   minimum size hint. That is read again whenever the widget's layout asks,
   because a window BUILT at 300% sets the length before its children
   exist, and has to arrive where a window changed to 300% does. At 100% the length is exactly the one written, as in every
   earlier release.

``tests/test_text_scale.py`` builds the window, changes the size, and fails on
any widget whose text did not follow, on a window laid out differently from
one built at the new size, and on a table row shorter than its text. Nothing
here touches the drawing: page rendering and the marks on it are the zoom's,
in page units.
"""

from __future__ import annotations

import json
import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QStyle, QStyleOptionDockWidget, QStylePainter,
)

# The per-class fonts a platform theme may set beside the application font
# (QApplicationPrivate::initializeWidgetFontHash). Windows sets several: menus,
# message boxes, the status bar, tooltips, dock titles. `QApplication.setFont`
# with no class name CLEARS every one of them, so each that differs from the
# application font is captured once, before the first change, and put back
# scaled after each.
_CLASS_FONTS = (
    "QMenu", "QMenuBar", "QMenuItem", "QMessageBox", "QLabel", "QTipLabel",
    "QStatusBar", "QMdiSubWindowTitleBar", "QDockWidgetTitle", "QPushButton",
    "QCheckBox", "QRadioButton", "QToolButton", "QAbstractItemView",
    "QListView", "QHeaderView", "QListBox", "QComboMenuItem", "QComboLineEdit",
    "QSmallFont", "QMiniFont",
)

# Dynamic properties holding a widget's 100% values (the only state kept, and
# it lives on the widget, so a deleted widget takes its own with it).
PROP_QSS = "textScaleQss"
PROP_FONT = "textScaleFont"
PROP_SIZES = "textScaleSizes"

# What sized() may set: the six size setters that hold text in this app.
SIZE_SETTERS = frozenset((
    "setFixedWidth", "setFixedHeight", "setMinimumWidth", "setMinimumHeight",
    "setMaximumWidth", "setMaximumHeight",
))

_FONT_SIZE = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(px|pt)", re.I)

# The setters that cap a length, so a capped widget can be held smaller than
# its own text (point 5). A minimum cannot hold anything smaller.
_CAPS = frozenset((
    "setFixedWidth", "setFixedHeight", "setMaximumWidth", "setMaximumHeight",
))

_base = None        # (application font, {class name: font}) at 100%
_percent = 100
_dock_titles = None  # the one _DockTitle filter, made at the first change
_fit = None          # the one _Fit filter, made at the first sized()


# -- the scale ------------------------------------------------------------------

def percent() -> int:
    """The text size in force, as a percentage of the platform's."""
    return _percent


def factor() -> float:
    return _percent / 100.0


def px(value: int) -> int:
    """A length written at 100%, at the size in force. Exact at 100%."""
    return round(value * factor())


def scaled_font(font: QFont, by: float) -> QFont:
    """A copy of ``font`` with its size multiplied by ``by``; every other
    attribute, and whether it was sized in points or pixels, kept."""
    out = QFont(font)
    if font.pointSizeF() > 0:
        out.setPointSizeF(font.pointSizeF() * by)
    elif font.pixelSize() > 0:
        out.setPixelSize(max(1, round(font.pixelSize() * by)))
    return out


def _capture():
    global _base
    if _base is None:
        app_font = QFont(QApplication.font())
        classes = {}
        for name in _CLASS_FONTS:
            font = QApplication.font(name)
            if font != app_font:
                classes[name] = QFont(font)
        _base = (app_font, classes)
    return _base


def base_font() -> QFont:
    """The application font at 100%, whatever the size in force.

    Its size is SET rather than inherited, so a widget given this font keeps
    it through a change: a plain copy of ``QApplication.font()`` carries no
    size of its own and follows the application font like any other widget,
    which is how the splash's labels doubled before it was written this way.
    """
    return scaled_font(_capture()[0], 1.0)


def apply(new_percent: int) -> bool:
    """Make ``new_percent`` the text size of every window, open or not yet built.

    Returns whether anything changed. At the size already in force it does
    nothing at all, so a launch at 100% leaves Qt's fonts exactly as the
    platform set them.
    """
    global _percent
    new_percent = int(new_percent)
    if new_percent <= 0:
        raise ValueError(f"a text size must be above 0%, not {new_percent}%")
    app_font, classes = _capture()
    if new_percent == _percent:
        return False
    _percent = new_percent
    by = factor()
    QApplication.setFont(scaled_font(app_font, by))
    for name, font in classes.items():
        QApplication.setFont(scaled_font(font, by), name)
    # Qt POSTS the change rather than sending it, so until it is delivered
    # every widget still reports its old font, and whatever is measured from
    # one in _refresh (a wrapped label's height) comes out one change late.
    QApplication.sendPostedEvents(None, QEvent.ApplicationFontChange)
    _refresh()
    return True


# -- the three things that would otherwise stay put ---------------------------

def scale_qss(qss: str) -> str:
    """``qss`` with every ``font-size`` in px or pt at the size in force."""
    by = factor()

    def one(m):
        value = float(m.group(2)) * by
        text = str(max(1, round(value))) if m.group(3).lower() == "px" \
            else f"{round(value, 2):g}"
        return f"{m.group(1)}{text}{m.group(3)}"

    return _FONT_SIZE.sub(one, qss)


def style(widget, qss: str) -> None:
    """Set a stylesheet written at 100%. Its font sizes follow the scale.

    A widget styled this way keeps being styled this way: a later plain
    ``setStyleSheet`` on it is replaced by this one at the next change.
    """
    widget.setProperty(PROP_QSS, qss)
    widget.setStyleSheet(scale_qss(qss))


def set_font(widget, font: QFont) -> None:
    """Set an explicit font whose size is the 100% size. It follows the scale."""
    if font.pointSizeF() > 0:
        widget.setProperty(PROP_FONT, f"pt:{font.pointSizeF()!r}")
    else:
        widget.setProperty(PROP_FONT, f"px:{font.pixelSize()}")
    widget.setFont(scaled_font(font, factor()))


def sized(widget, **lengths: int) -> None:
    """Set fixed, minimum or maximum lengths written at 100%, scaled.

    ``sized(rail, setFixedWidth=196)``. Only for a length that holds text: a
    width an icon or a color swatch needs is not a text size. At any size but
    100%, a fixed or maximum length is never less than the widget's own
    minimum size hint (point 5 of the module docstring).
    """
    global _fit
    unknown = set(lengths) - SIZE_SETTERS
    if unknown:
        raise ValueError(f"sized() sets only {sorted(SIZE_SETTERS)}, "
                         f"not {sorted(unknown)}")
    widget.setProperty(PROP_SIZES, json.dumps(lengths, sort_keys=True))
    if _fit is None:
        _fit = _Fit(QApplication.instance())
    widget.installEventFilter(_fit)        # once: Qt drops a repeat
    _apply_sizes(widget, lengths)


def _apply_sizes(widget, lengths: dict) -> None:
    need = widget.minimumSizeHint() if _percent != 100 else None
    for setter, value in sorted(lengths.items()):
        length = px(int(value))
        if need is not None and setter in _CAPS:
            length = max(length, need.width() if setter.endswith("Width")
                         else need.height())
        getattr(widget, setter)(length)


class _Fit(QObject):
    """Reads a sized widget's minimum size hint again when its layout asks,
    so its caps follow the text it holds (point 5)."""

    def eventFilter(self, widget, event):
        if _percent != 100 and event.type() == QEvent.LayoutRequest:
            sizes = widget.property(PROP_SIZES)
            if sizes:
                _apply_sizes(widget, json.loads(str(sizes)))
        return False


def _depth(widget) -> int:
    n = 0
    while widget.parentWidget() is not None:
        widget = widget.parentWidget()
        n += 1
    return n


def _refresh() -> None:
    by = factor()
    for w in sorted(QApplication.allWidgets(), key=_depth):
        font = w.property(PROP_FONT)
        if font:
            kind, _, size = str(font).partition(":")
            f = QFont(w.font())
            if kind == "pt":
                f.setPointSizeF(float(size) * by)
            else:
                f.setPixelSize(max(1, round(int(size) * by)))
            w.setFont(f)
        sizes = w.property(PROP_SIZES)
        if sizes:
            _apply_sizes(w, json.loads(str(sizes)))
        # Setting a stylesheet again is Qt's public way to repolish a subtree,
        # and top-down order has each widget resolve against a parent that is
        # already at the new size (point 1 of the module docstring).
        template = w.property(PROP_QSS)
        qss = scale_qss(str(template)) if template else w.styleSheet()
        if qss:
            w.setStyleSheet(qss)
    # Point 3: a dock's title bar and a table's row height are measured from
    # the font once and kept until a style change arrives. Send each widget the
    # event a style change would, so it measures again.
    for w in QApplication.allWidgets():
        QApplication.sendEvent(w, QEvent(QEvent.StyleChange))
    global _dock_titles
    if _dock_titles is None:
        _dock_titles = _DockTitle(QApplication.instance())
    for w in QApplication.allWidgets():
        if isinstance(w, QDockWidget):
            w.installEventFilter(_dock_titles)   # once: Qt drops a repeat
            w.update()


class _DockTitle(QObject):
    """Paints a docked title as ``QDockWidget::paintEvent`` does, except that
    the title font is read now rather than from the copy made at construction
    (point 4). Floating docks and custom title bars are left to Qt: a floating
    dock's title is the window's own frame on Windows."""

    def eventFilter(self, dock, event):
        if (event.type() != QEvent.Paint or not isinstance(dock, QDockWidget)
                or dock.isFloating() or dock.titleBarWidget() is not None
                # Qt itself paints with the dock's own font in this case
                or dock.font() != QApplication.font("QDockWidget")):
            return False
        font = QApplication.font("QDockWidgetTitle")
        opt = QStyleOptionDockWidget()
        dock.initStyleOption(opt)
        opt.fontMetrics = QFontMetrics(font)
        p = QStylePainter(dock)
        p.setFont(font)
        p.drawControl(QStyle.CE_DockWidgetTitle, opt)
        p.end()
        return True


__all__ = [
    "apply", "base_font", "factor", "percent", "px", "scale_qss",
    "scaled_font", "set_font", "sized", "style", "SIZE_SETTERS",
    "PROP_FONT", "PROP_QSS", "PROP_SIZES",
]
