"""The File view: an Office-style page over the whole window for finding a
drawing to open.

It covers the toolbar, the panes and the status bar -- everything below the
menu bar -- the way Office's File page covers the ribbon and the document, and
it goes away with Back, Esc, or by opening something. `Ctrl+O` shows it, and
`main.py` shows it on a launch with no file to open.

This first version holds **Recent**: pinned drawings, then Today / Yesterday /
This week / Older, a search field over both, and **Browse…** for the file
dialog. Which file a row opens, and what counts as one drawing, are
`app/model/recent.py`'s rules, so this module only draws them.

It lives in its own module rather than in `main_window.py` because
`tests/test_module_layout.py` keeps widget construction out of the window, and
it is an OVERLAY rather than a swap of the window's central widget because
every pane is a dock: hiding and restoring the docks would fight the saved
layout, while a child raised above them leaves the layout untouched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QEvent, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .model import recent as R

# item data roles on a file row
_PATH = Qt.UserRole          # the path as stored in the list
_TARGET = Qt.UserRole + 1    # the file a click opens (recent.open_target)
_GROUP = Qt.UserRole + 2     # the group / source the row sits under
_FOUND = Qt.UserRole + 3     # whether the target exists


def reveal_in_file_manager(path: str) -> None:
    """Show ``path`` in Explorer with the file selected, or open its folder
    elsewhere (no portable way to select a file in Finder or a Linux desktop)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path) or "."))


def _opened_label(opened: str, group: str) -> str:
    """The Opened column: a time for Today / Yesterday, otherwise a date."""
    if not opened:
        return ""
    try:
        when = R.local_time(datetime.fromisoformat(opened))
    except (TypeError, ValueError):
        return ""
    if group in (R.GROUP_TODAY, R.GROUP_YESTERDAY):
        return when.strftime("%H:%M")
    return when.strftime("%Y-%m-%d")


class FileView(QWidget):
    openRequested = Signal(str)     # a path to open, already resolved
    browseRequested = Signal()      # the file dialog
    backRequested = Signal()        # Back / Esc

    COL_NAME, COL_FOLDER, COL_OPENED = range(3)

    def __init__(self, config, window):
        super().__init__(window)
        self.config = config
        self._window = window
        self.now = datetime.now          # replaced in tests to fix "today"
        self.setObjectName("FileView")
        self.setAutoFillBackground(True)
        self.setAcceptDrops(True)
        self._build_ui()
        window.installEventFilter(self)
        self.hide()

    # -- layout ----------------------------------------------------------------

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("FileViewRail")
        rail.setFixedWidth(180)
        rail.setStyleSheet(
            "#FileViewRail { background: #2b5797; }"
            "#FileViewRail QPushButton { color: white; border: none;"
            " text-align: left; padding: 10px 18px; font-size: 14px; }"
            "#FileViewRail QPushButton:hover { background: #3a6ab0; }"
            "#FileViewRail QPushButton:checked { background: #1e3f6f; }")
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(0, 12, 0, 12)
        rv.setSpacing(2)
        self.btn_back = QPushButton("←  Back")
        self.btn_back.setToolTip("Back to the drawing (Esc)")
        self.btn_back.clicked.connect(self.backRequested.emit)
        self.btn_recent = QPushButton("Recent")
        self.btn_recent.setCheckable(True)
        self.btn_recent.setChecked(True)
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setToolTip("Open a PDF with the file dialog")
        self.btn_browse.clicked.connect(self.browseRequested.emit)
        rv.addWidget(self.btn_back)
        rv.addSpacing(16)
        rv.addWidget(self.btn_recent)
        rv.addStretch(1)
        rv.addWidget(self.btn_browse)
        root.addWidget(rail)

        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(28, 20, 28, 20)
        pv.setSpacing(12)
        self.title = QLabel("Recent")
        f = QFont(self.title.font())
        f.setPointSize(f.pointSize() + 10)
        self.title.setFont(f)
        pv.addWidget(self.title)
        self.search = QLineEdit(placeholderText="Search recent and pinned files")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        pv.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Folder", "Opened"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        # a long folder path keeps its tail -- the folder you recognize
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setStyleSheet("QTreeWidget::item { padding: 4px 2px; }")
        self.tree.setColumnWidth(self.COL_NAME, 320)
        self.tree.setColumnWidth(self.COL_FOLDER, 420)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        enter = QShortcut(QKeySequence(Qt.Key_Return), self.tree)
        enter.setContext(Qt.WidgetShortcut)
        enter.activated.connect(lambda: self._open_item(self.tree.currentItem()))
        pv.addWidget(self.tree, 1)

        # shown IN PLACE of the list when there is nothing to list
        self.empty = QLabel("")
        self.empty.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.empty.setStyleSheet("color: gray; font-size: 14px; padding-top: 40px;")
        self.empty.hide()
        pv.addWidget(self.empty, 1)
        root.addWidget(page, 1)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._on_escape)

    # -- showing it over the window ----------------------------------------------

    def open_page(self):
        """Refresh and cover the window below the menu bar."""
        self.refresh()
        self._fit()
        self.show()
        self.raise_()
        self.search.setFocus()

    def close_page(self):
        self.hide()

    def _fit(self):
        top = 0
        bar = getattr(self._window, "menuBar", None)
        if bar is not None and bar().isVisible():
            top = bar().geometry().bottom() + 1
        self.setGeometry(0, top, self._window.width(),
                         max(0, self._window.height() - top))

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.Resize and self.isVisible():
            self._fit()
        return False

    def _on_escape(self):
        if self.search.text():
            self.search.clear()
        else:
            self.backRequested.emit()

    # -- the list ------------------------------------------------------------------

    def _rows(self):
        """(group, path) for every row, before search: pins first, then the
        recent list in date groups with pinned drawings left out of it."""
        now = self.now()
        pinned = self.config.pinned_files
        pinned_keys = {R.drawing_key(p) for p in pinned}
        rows = [(R.GROUP_PINNED, p) for p in pinned]
        for p in self.config.recent_files:
            if R.drawing_key(p) not in pinned_keys:
                rows.append((R.date_group(self.config.recent_opened(p), now), p))
        return rows

    def refresh(self):
        query = self.search.text().strip()
        rows = self._rows()
        if query:
            # searching lists every hit under its SOURCE rather than its date
            rows = [(R.GROUP_PINNED if g == R.GROUP_PINNED else "Recent", p)
                    for g, p in rows if R.matches(query, p)]
            order = [R.GROUP_PINNED, "Recent"]
        else:
            order = [R.GROUP_PINNED] + list(R.DATE_GROUPS)
        self.tree.clear()
        for group in order:
            members = [p for g, p in rows if g == group]
            if not members:
                continue
            head = QTreeWidgetItem([group])
            head.setFirstColumnSpanned(True)
            head.setFlags(Qt.ItemIsEnabled)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            self.tree.addTopLevelItem(head)
            for p in members:
                head.addChild(self._make_row(group, p))
            head.setExpanded(True)
        n = len(rows)
        if n:
            self.empty.setText("")
        elif query:
            self.empty.setText(f"Nothing recent or pinned matches “{query}”.")
        else:
            self.empty.setText("No recent files yet — Browse… to open one, "
                               "or drop a PDF here.")
        self.empty.setVisible(not n)
        self.tree.setVisible(bool(n))

    def _make_row(self, group, path):
        target = R.open_target(path)
        found = os.path.isfile(target)
        name = os.path.basename(target)
        it = QTreeWidgetItem([
            name if found else f"{name}   (not found)",
            os.path.dirname(target),
            _opened_label(self.config.recent_opened(path), group),
        ])
        it.setData(0, _PATH, path)
        it.setData(0, _TARGET, target)
        it.setData(0, _GROUP, group)
        it.setData(0, _FOUND, found)
        it.setToolTip(0, target)
        if not found:
            for col in range(3):
                it.setForeground(col, Qt.gray)
        return it

    def file_rows(self):
        """Every file row, in display order (headers skipped)."""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            out.extend(head.child(j) for j in range(head.childCount()))
        return out

    def groups(self):
        """The group headers shown, in order."""
        return [self.tree.topLevelItem(i).text(0)
                for i in range(self.tree.topLevelItemCount())]

    # -- acting on a row -----------------------------------------------------------

    def _on_clicked(self, item, _col):
        self._open_item(item)

    def _open_item(self, item):
        if item is None or item.data(0, _TARGET) is None:
            return                              # a group header
        if not item.data(0, _FOUND):
            return                              # "(not found)" says why
        self.openRequested.emit(item.data(0, _TARGET))

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or item.data(0, _TARGET) is None:
            return
        self.tree.setCurrentItem(item)
        self._context_menu_for(item).exec(self.tree.viewport().mapToGlobal(pos))

    def _context_menu_for(self, item) -> QMenu:
        """A file row's right-click menu, built apart from ``exec`` so its
        actions can be read and triggered without a modal menu."""
        path = item.data(0, _PATH)
        target = item.data(0, _TARGET)
        found = bool(item.data(0, _FOUND))
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open_item(item)).setEnabled(found)
        if self.config.is_pinned(path):
            menu.addAction("Unpin", lambda: self._pin(path, False))
        else:
            menu.addAction("Pin", lambda: self._pin(path, True))
        menu.addSeparator()
        menu.addAction("Show in folder",
                       lambda: reveal_in_file_manager(target)).setEnabled(found)
        menu.addAction("Copy path",
                       lambda: QApplication.clipboard().setText(
                           os.path.abspath(target)))
        if item.data(0, _GROUP) != R.GROUP_PINNED:
            menu.addSeparator()
            menu.addAction("Remove from list", lambda: self._remove(path))
        return menu

    def _pin(self, path, on: bool):
        (self.config.pin_file if on else self.config.unpin_file)(path)
        self.refresh()

    def _remove(self, path):
        self.config.remove_recent_file(path)
        self.refresh()

    # -- dropping a PDF on the page opens it ------------------------------------------

    @staticmethod
    def _dropped_pdf(event) -> str:
        md = event.mimeData()
        if md is not None and md.hasUrls():
            for u in md.urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf"):
                    # Qt spells a Windows path C:/Users/...; hand on the
                    # native form, as every row of the list already does
                    return os.path.normpath(u.toLocalFile())
        return ""

    def dragEnterEvent(self, event):
        if self._dropped_pdf(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self._dropped_pdf(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = self._dropped_pdf(event)
        if path:
            self.openRequested.emit(path)
            event.acceptProposedAction()
