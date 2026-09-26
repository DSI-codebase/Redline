"""The File view: an Office-style page over the whole window for finding a
drawing to open.

It covers the toolbar, the panes and the status bar -- everything below the
menu bar -- the way Office's File page covers the ribbon and the document, and
it goes away with Back, Esc, or by opening something. `Ctrl+O` shows it, and
`main.py` shows it on a launch with no file to open.

Two selections on the left rail:

* **Recent** -- pinned drawings, then Today / Yesterday / This week / Older,
  and a search field over those AND every workspace's PDFs, each hit listed
  under its source.
* **Workspaces** -- the project folders the user declared, and a page per
  workspace: its Favorites, its own recent list (which casual viewing
  elsewhere never pushes a file off), and every PDF under the folder as a tree
  by subfolder.

The rules -- which file a row opens, what one drawing is, what a workspace
holds -- are `app/model/recent.py` and `app/model/workspaces.py`; this module
draws them. Scanning a workspace runs on a background thread (a project on a
network share can take seconds), so a page shows what it last found at once
and fills in when the scan finishes.

It lives in its own module because `tests/test_module_layout.py` keeps widget
construction out of the window, and it is an OVERLAY rather than a swap of the
window's central widget because every pane is a dock: hiding and restoring the
docks would fight the saved layout, while a child raised above them leaves the
layout untouched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QEvent, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .model import recent as R
from .model import workspaces as W
from .tools.runner import BackgroundTask

# item data roles
_PATH = Qt.UserRole          # a file row: the path as stored
_TARGET = Qt.UserRole + 1    # a file row: the file a click opens
_GROUP = Qt.UserRole + 2     # the group / section header the row sits under
_FOUND = Qt.UserRole + 3     # a file row: whether the target exists
_KIND = Qt.UserRole + 4      # "file" | "folder" | "workspace"
_SOURCE = Qt.UserRole + 5    # a file row: which list it came from (SRC_*)
_REL = Qt.UserRole + 6       # relative to the workspace root
_ROOT = Qt.UserRole + 7      # a workspace row: its root

SRC_PINNED, SRC_RECENT, SRC_WORKSPACE = "pinned", "recent", "workspace"
SRC_FAVORITE, SRC_WS_RECENT, SRC_WS_ALL = "ws-favorite", "ws-recent", "ws-all"

SEC_FAVORITES = "Favorites"
SEC_WS_RECENT = "Recent in this workspace"
SEC_ALL = "All files"

PAGE_RECENT, PAGE_WORKSPACES, PAGE_WORKSPACE = "recent", "workspaces", "workspace"
_PAGES = (PAGE_RECENT, PAGE_WORKSPACES, PAGE_WORKSPACE)

_GRAY = Qt.gray


def reveal_in_file_manager(path: str) -> None:
    """Show ``path`` in Explorer with the file selected, or open its folder
    elsewhere (no portable way to select a file in Finder or a Linux desktop)."""
    if sys.platform == "win32":
        if os.path.isdir(path):
            subprocess.Popen(["explorer", os.path.normpath(path)])
        else:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return
    folder = path if os.path.isdir(path) else (os.path.dirname(path) or ".")
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def _opened_label(opened: str, group: str) -> str:
    """A time for Today / Yesterday, otherwise a date."""
    if not opened:
        return ""
    try:
        when = R.local_time(datetime.fromisoformat(opened))
    except (TypeError, ValueError):
        return ""
    if group in (R.GROUP_TODAY, R.GROUP_YESTERDAY):
        return when.strftime("%H:%M")
    return when.strftime("%Y-%m-%d")


def _modified_label(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""


def _header(tree, text):
    head = QTreeWidgetItem([text])
    head.setFirstColumnSpanned(True)
    head.setFlags(Qt.ItemIsEnabled)
    f = head.font(0)
    f.setBold(True)
    head.setFont(0, f)
    head.setData(0, _GROUP, text)
    tree.addTopLevelItem(head)
    head.setExpanded(True)
    return head


def _gray(item, columns=3):
    for col in range(columns):
        item.setForeground(col, _GRAY)


def _list_tree(headers, widths):
    tree = QTreeWidget()
    tree.setColumnCount(len(headers))
    tree.setHeaderLabels(headers)
    tree.setUniformRowHeights(True)
    # a long folder path keeps its tail -- the folder you recognize
    tree.setTextElideMode(Qt.ElideMiddle)
    tree.setStyleSheet("QTreeWidget::item { padding: 4px 2px; }")
    for col, w in enumerate(widths):
        tree.setColumnWidth(col, w)
    tree.setContextMenuPolicy(Qt.CustomContextMenu)
    return tree


def _title_label(text):
    lab = QLabel(text)
    f = QFont(lab.font())
    f.setPointSize(f.pointSize() + 10)
    lab.setFont(f)
    return lab


def _empty_label():
    # shown IN PLACE of a list when there is nothing to list
    lab = QLabel("")
    lab.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: gray; font-size: 14px; padding-top: 40px;")
    lab.hide()
    return lab


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
        self._scans = {}                 # (root key, show hidden) -> ScanResult
        self._tasks = {}                 # same key -> running BackgroundTask
        self._ws_root = None             # the workspace the page shows
        self.setObjectName("FileView")
        self.setAutoFillBackground(True)
        self.setAcceptDrops(True)
        self._build_ui()
        window.installEventFilter(self)
        self.hide()

    # -- the questions the page asks; replaced in tests ------------------------

    def ask_folder(self, title: str) -> str:
        return QFileDialog.getExistingDirectory(self, title, os.path.expanduser("~"))

    def ask_text(self, title: str, label: str, text: str = ""):
        return QInputDialog.getText(self, title, label, text=text)

    def warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

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
        self.btn_recent.clicked.connect(self.show_recent)
        self.btn_workspaces = QPushButton("Workspaces")
        self.btn_workspaces.setCheckable(True)
        self.btn_workspaces.clicked.connect(self.show_workspaces)
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setToolTip("Open a PDF with the file dialog")
        self.btn_browse.clicked.connect(self.browseRequested.emit)
        rv.addWidget(self.btn_back)
        rv.addSpacing(16)
        rv.addWidget(self.btn_recent)
        rv.addWidget(self.btn_workspaces)
        rv.addStretch(1)
        rv.addWidget(self.btn_browse)
        root.addWidget(rail)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_recent_page())
        self.stack.addWidget(self._build_workspaces_page())
        self.stack.addWidget(self._build_workspace_page())
        root.addWidget(self.stack, 1)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._on_escape)

    @staticmethod
    def _page_layout():
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(28, 20, 28, 20)
        pv.setSpacing(12)
        return page, pv

    def _connect_tree(self, tree):
        tree.itemClicked.connect(self._on_clicked)
        tree.customContextMenuRequested.connect(
            lambda pos, t=tree: self._show_context_menu(t, pos))
        enter = QShortcut(QKeySequence(Qt.Key_Return), tree)
        enter.setContext(Qt.WidgetShortcut)
        enter.activated.connect(lambda t=tree: self._on_clicked(t.currentItem(), 0))

    def _build_recent_page(self):
        page, pv = self._page_layout()
        self.title = _title_label("Recent")
        pv.addWidget(self.title)
        self.search = QLineEdit(
            placeholderText="Search recent, pinned and workspace files")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        pv.addWidget(self.search)
        self.tree = _list_tree(["Name", "Folder", "Opened"], (320, 420))
        self.tree.setRootIsDecorated(False)
        self._connect_tree(self.tree)
        pv.addWidget(self.tree, 1)
        self.empty = _empty_label()
        pv.addWidget(self.empty, 1)
        return page

    def _build_workspaces_page(self):
        page, pv = self._page_layout()
        pv.addWidget(_title_label("Workspaces"))
        row = QHBoxLayout()
        self.btn_add_ws = QPushButton("Add workspace…")
        self.btn_add_ws.setToolTip("Use an existing project folder as a workspace")
        self.btn_add_ws.clicked.connect(self._add_workspace)
        self.btn_new_ws = QPushButton("New workspace…")
        self.btn_new_ws.setToolTip(
            "Create a project folder, with its quick subfolders, as a workspace")
        self.btn_new_ws.clicked.connect(self._new_workspace)
        row.addWidget(self.btn_add_ws)
        row.addWidget(self.btn_new_ws)
        row.addStretch(1)
        pv.addLayout(row)
        self.ws_tree = _list_tree(["Name", "Folder", "Last used"], (260, 460))
        self.ws_tree.setRootIsDecorated(False)
        self._connect_tree(self.ws_tree)
        pv.addWidget(self.ws_tree, 1)
        self.ws_empty = _empty_label()
        pv.addWidget(self.ws_empty, 1)
        return page

    def _build_workspace_page(self):
        page, pv = self._page_layout()
        up = QPushButton("‹  Workspaces")
        up.setFlat(True)
        up.setStyleSheet("text-align: left; color: #2b5797;")
        up.clicked.connect(self.show_workspaces)
        pv.addWidget(up, 0, Qt.AlignLeft)
        self.ws_title = _title_label("")
        pv.addWidget(self.ws_title)
        self.ws_path = QLabel("")
        self.ws_path.setStyleSheet("color: gray;")
        self.ws_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pv.addWidget(self.ws_path)

        self.ws_body = QWidget()
        bv = QVBoxLayout(self.ws_body)
        bv.setContentsMargins(0, 0, 0, 0)
        status = QHBoxLayout()
        self.ws_count = QLabel("")
        self.show_hidden = QCheckBox("Show hidden folders")
        self.show_hidden.toggled.connect(lambda _on: self._show_workspace_page(rescan=True))
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(lambda: self._show_workspace_page(rescan=True))
        status.addWidget(self.ws_count)
        status.addStretch(1)
        status.addWidget(self.show_hidden)
        status.addWidget(self.btn_refresh)
        bv.addLayout(status)
        self.ws_filter = QLineEdit(placeholderText="Filter files in this workspace")
        self.ws_filter.setClearButtonEnabled(True)
        self.ws_filter.textChanged.connect(lambda _t: self.refresh_workspace())
        bv.addWidget(self.ws_filter)
        self.ws_files = _list_tree(["Name", "Subfolder", "Modified"], (340, 300))
        self._connect_tree(self.ws_files)
        bv.addWidget(self.ws_files, 1)
        pv.addWidget(self.ws_body, 1)

        # a workspace whose folder is gone -- a disconnected drive, a move
        self.ws_missing = QWidget()
        mv = QVBoxLayout(self.ws_missing)
        self.ws_missing_text = QLabel("")
        self.ws_missing_text.setWordWrap(True)
        mv.addWidget(self.ws_missing_text)
        mrow = QHBoxLayout()
        self.btn_locate = QPushButton("Locate…")
        self.btn_locate.clicked.connect(lambda: self._locate(self._ws_root))
        self.btn_forget = QPushButton("Remove from list")
        self.btn_forget.clicked.connect(lambda: self._remove_workspace(self._ws_root))
        mrow.addWidget(self.btn_locate)
        mrow.addWidget(self.btn_forget)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        mv.addStretch(1)
        pv.addWidget(self.ws_missing, 1)
        return page

    # -- showing it over the window ----------------------------------------------

    def open_page(self, open_path=None):
        """Cover the window below the menu bar, on the current workspace --
        the one holding ``open_path``, else the one last opened here -- or on
        Recent when there is none."""
        ws = self.config.current_workspace(open_path)
        if ws is not None:
            self.show_workspace(ws.root)
        else:
            self.show_recent()
        self._fit()
        self.show()
        self.raise_()
        (self.ws_filter if self.page() == PAGE_WORKSPACE else self.search).setFocus()

    def close_page(self):
        self.hide()

    def page(self) -> str:
        return _PAGES[self.stack.currentIndex()]

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
        field = {PAGE_RECENT: self.search, PAGE_WORKSPACE: self.ws_filter}.get(self.page())
        if field is not None and field.text():
            field.clear()
        else:
            self.backRequested.emit()

    def _select_rail(self, page):
        self.btn_recent.setChecked(page == PAGE_RECENT)
        self.btn_workspaces.setChecked(page != PAGE_RECENT)

    def show_recent(self):
        self.stack.setCurrentIndex(_PAGES.index(PAGE_RECENT))
        self._select_rail(PAGE_RECENT)
        self.refresh()

    def show_workspaces(self):
        self.stack.setCurrentIndex(_PAGES.index(PAGE_WORKSPACES))
        self._select_rail(PAGE_WORKSPACES)
        self.refresh_workspaces()

    def show_workspace(self, root):
        ws = self.config.find_workspace(root)
        if ws is None:
            self.show_workspaces()
            return
        if self._ws_root is None or W._key(self._ws_root) != W._key(ws.root):
            self.ws_filter.clear()
        self._ws_root = ws.root
        self.config.select_workspace(ws.root)
        self.stack.setCurrentIndex(_PAGES.index(PAGE_WORKSPACE))
        self._select_rail(PAGE_WORKSPACE)
        self._show_workspace_page(rescan=True)

    # -- Recent ----------------------------------------------------------------------

    def _rows(self):
        """(group, source, path) before search: pins first, then the recent
        list in date groups with pinned drawings left out of it."""
        now = self.now()
        pinned = self.config.pinned_files
        pinned_keys = {R.drawing_key(p) for p in pinned}
        rows = [(R.GROUP_PINNED, SRC_PINNED, p) for p in pinned]
        for p in self.config.recent_files:
            if R.drawing_key(p) not in pinned_keys:
                rows.append((R.date_group(self.config.recent_opened(p), now),
                             SRC_RECENT, p))
        return rows

    def _workspace_hits(self, query, seen):
        """(workspace name, path) for every scanned workspace PDF matching
        ``query`` and not already listed. Scans what is not cached yet; a
        finished scan re-runs the search."""
        hits = []
        for ws in W.ordered(self.config.workspaces()):
            if not ws.available:
                continue
            result = self._scans.get((W._key(ws.root), False))
            if result is None:
                self._scan(ws, show_hidden=False)
                continue
            for wf in result.files:
                if R.matches(query, wf.rel) and R.drawing_key(wf.path) not in seen:
                    seen.add(R.drawing_key(wf.path))
                    hits.append((ws.display_name, wf.path))
        return hits

    def refresh(self):
        query = self.search.text().strip()
        rows = self._rows()
        if query:
            # searching lists every hit under its SOURCE rather than its date
            rows = [(R.GROUP_PINNED if s == SRC_PINNED else "Recent", s, p)
                    for g, s, p in rows if R.matches(query, p)]
            seen = {R.drawing_key(p) for _g, _s, p in rows}
            hits = self._workspace_hits(query, seen)
            rows += [(name, SRC_WORKSPACE, p) for name, p in hits]
            order = [R.GROUP_PINNED, "Recent"] + [n for n, _p in hits]
        else:
            order = [R.GROUP_PINNED] + list(R.DATE_GROUPS)
        self.tree.clear()
        done = set()
        for group in order:
            if group in done:
                continue
            done.add(group)
            members = [(s, p) for g, s, p in rows if g == group]
            if not members:
                continue
            head = _header(self.tree, group)
            for source, p in members:
                head.addChild(self._make_row(group, source, p))
        n = len(rows)
        if n:
            self.empty.setText("")
        elif query:
            self.empty.setText(f"Nothing recent, pinned or in a workspace "
                               f"matches “{query}”.")
        else:
            self.empty.setText("No recent files yet — Browse… to open one, "
                               "or drop a PDF here.")
        self.empty.setVisible(not n)
        self.tree.setVisible(bool(n))

    def _file_item(self, cells, stored, group, source, target=None, rel=None):
        target = target or R.open_target(stored)
        found = os.path.isfile(target)
        if not found:
            cells[0] = f"{cells[0]}   (not found)"
        it = QTreeWidgetItem(cells)
        it.setData(0, _KIND, "file")
        it.setData(0, _PATH, stored)
        it.setData(0, _TARGET, target)
        it.setData(0, _GROUP, group)
        it.setData(0, _FOUND, found)
        it.setData(0, _SOURCE, source)
        it.setData(0, _REL, rel)
        it.setToolTip(0, target)
        if not found:
            _gray(it)
        return it

    def _make_row(self, group, source, path):
        target = R.open_target(path)
        return self._file_item(
            [os.path.basename(target), os.path.dirname(target),
             _opened_label(self.config.recent_opened(path), group)],
            path, group, source, target)

    def file_rows(self, tree=None):
        """Every file row of ``tree`` (default: Recent), in display order."""
        out = []

        def walk(node):
            for j in range(node.childCount()):
                child = node.child(j)
                if child.data(0, _KIND) == "file":
                    out.append(child)
                walk(child)

        tree = tree or self.tree
        for i in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(i))
        return out

    def groups(self, tree=None):
        """The group / section headers shown, in order."""
        tree = tree or self.tree
        return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]

    # -- the workspace list ------------------------------------------------------------

    def refresh_workspaces(self):
        self.ws_tree.clear()
        items = W.ordered(self.config.workspaces())
        for group, members in (("Pinned", [w for w in items if w.pinned]),
                               ("Workspaces", [w for w in items if not w.pinned])):
            if not members:
                continue
            head = _header(self.ws_tree, group)
            for ws in members:
                head.addChild(self._workspace_item(ws, group))
        n = len(items)
        self.ws_empty.setText(
            "" if n else "No workspaces yet — Add workspace… to use a project "
                         "folder, or New workspace… to start one.")
        self.ws_empty.setVisible(not n)
        self.ws_tree.setVisible(bool(n))

    def _workspace_item(self, ws, group):
        available = ws.available
        name = ws.display_name if available else f"{ws.display_name}   (unavailable)"
        it = QTreeWidgetItem([name, ws.root,
                              _opened_label(ws.last_used, R.date_group(ws.last_used, self.now()))])
        it.setData(0, _KIND, "workspace")
        it.setData(0, _ROOT, ws.root)
        it.setData(0, _GROUP, group)
        it.setData(0, _FOUND, available)
        it.setToolTip(0, ws.root)
        if not available:
            _gray(it)
        return it

    def workspace_rows(self):
        return [self.ws_tree.topLevelItem(i).child(j)
                for i in range(self.ws_tree.topLevelItemCount())
                for j in range(self.ws_tree.topLevelItem(i).childCount())]

    # -- one workspace ----------------------------------------------------------------

    def _show_workspace_page(self, rescan=False):
        ws = self.config.find_workspace(self._ws_root) if self._ws_root else None
        if ws is None:
            self.show_workspaces()
            return
        if rescan and ws.available:
            self._scan(ws, self.show_hidden.isChecked())
        self.refresh_workspace()

    def refresh_workspace(self):
        """Draw the workspace page from what the last scan found."""
        ws = self.config.find_workspace(self._ws_root) if self._ws_root else None
        if ws is None:
            return
        self.ws_title.setText(ws.display_name)
        self.ws_path.setText(ws.root)
        available = ws.available
        self.ws_body.setVisible(available)
        self.ws_missing.setVisible(not available)
        if not available:
            self.ws_missing_text.setText(
                f"This workspace's folder can't be found:\n{ws.root}\n\n"
                f"It may be on a drive that isn't connected, or it was moved or "
                f"renamed. Locate… points the workspace at its new place and keeps "
                f"its favorites and hidden folders.")
            return

        show_hidden = self.show_hidden.isChecked()
        key = (W._key(ws.root), show_hidden)
        scan = self._scans.get(key)
        running = key in self._tasks
        if scan is None:
            self.ws_count.setText("Scanning…" if running else "")
        else:
            self.ws_count.setText(scan.summary() + ("  (refreshing…)" if running else ""))

        query = self.ws_filter.text().strip()
        now = self.now()
        tree = self.ws_files
        tree.clear()

        favorites = [r for r in ws.favorites if R.matches(query, r)]
        if favorites:
            head = _header(tree, SEC_FAVORITES)
            for rel in favorites:
                head.addChild(self._workspace_file_item(ws, rel, SEC_FAVORITES,
                                                        SRC_FAVORITE, scan))
        fav_keys = {R.drawing_key(W.absolute(ws.root, r)) for r in ws.favorites}
        recent = [(rel, when) for rel, when in ws.recent
                  if R.drawing_key(W.absolute(ws.root, rel)) not in fav_keys
                  and R.matches(query, rel)]
        if recent:
            head = _header(tree, SEC_WS_RECENT)
            for rel, when in recent:
                it = self._workspace_file_item(ws, rel, SEC_WS_RECENT, SRC_WS_RECENT,
                                               scan, opened=when, now=now)
                head.addChild(it)

        files = [wf for wf in (scan.files if scan else []) if R.matches(query, wf.rel)]
        head = _header(tree, SEC_ALL)
        folders = {"": head}

        def folder_node(rel_folder):
            if rel_folder in folders:
                return folders[rel_folder]
            parent_rel, _sep, name = rel_folder.rpartition("/")
            parent = folder_node(parent_rel)
            node = QTreeWidgetItem([name])
            node.setData(0, _KIND, "folder")
            node.setData(0, _REL, rel_folder)
            node.setData(0, _GROUP, SEC_ALL)
            if ws.is_hidden(rel_folder):
                node.setText(0, f"{name}   (hidden)")
                _gray(node)
            parent.addChild(node)
            folders[rel_folder] = node
            return node

        for wf in files:
            parent = folder_node(wf.folder)
            it = self._file_item([wf.name, wf.folder, _modified_label(wf.modified)],
                                 wf.path, SEC_ALL, SRC_WS_ALL, wf.path, wf.rel)
            if wf.hidden:
                _gray(it)
            parent.addChild(it)
        for rel_folder, node in folders.items():
            if rel_folder:
                n = sum(1 for wf in files
                        if wf.folder == rel_folder or wf.folder.startswith(rel_folder + "/"))
                node.setText(1, f"{n} PDF{'s' if n != 1 else ''}")
                node.setExpanded(bool(query))
        if scan is not None and not files:
            placeholder = QTreeWidgetItem(
                [f"No PDF matches “{query}”." if query else "No PDFs in this folder yet."])
            placeholder.setFlags(Qt.ItemIsEnabled)
            _gray(placeholder)
            head.addChild(placeholder)

    def _workspace_file_item(self, ws, rel, group, source, scan, opened="", now=None):
        stored = W.absolute(ws.root, rel)
        target = R.open_target(stored)
        folder = rel.rpartition("/")[0]
        if opened:
            third = _opened_label(opened, R.date_group(opened, now or self.now()))
        else:
            mtime = next((wf.modified for wf in (scan.files if scan else [])
                          if R.drawing_key(wf.path) == R.drawing_key(target)), 0.0)
            third = _modified_label(mtime)
        return self._file_item([os.path.basename(target), folder, third],
                               stored, group, source, target, rel)

    def workspace_file_rows(self):
        return self.file_rows(self.ws_files)

    # -- scanning ----------------------------------------------------------------------

    def _scan(self, ws, show_hidden):
        """Scan ``ws`` on a background thread unless one is already running."""
        key = (W._key(ws.root), bool(show_hidden))
        if key in self._tasks:
            return
        snapshot = W.Workspace.from_dict(ws.to_dict())
        task = BackgroundTask(
            lambda _progress, cancel: W.scan(snapshot, show_hidden, cancel), self)
        self._tasks[key] = task
        task.done.connect(lambda result, k=key: self._scan_done(k, result))
        task.failed.connect(lambda message, k=key: self._scan_failed(k, message))
        task.start()

    def _scan_done(self, key, result):
        task = self._tasks.pop(key, None)
        if task is not None:
            task.wait(2000)
        if result is not None and not result.canceled:
            self._scans[key] = result
        self._after_scan(key)

    def _scan_failed(self, key, message):
        task = self._tasks.pop(key, None)
        if task is not None:
            task.wait(2000)
        if message != "__cancelled__" and self.page() == PAGE_WORKSPACE:
            self.ws_count.setText(f"Couldn't scan this folder: {message}")
            return
        self._after_scan(key)

    def _after_scan(self, key):
        if self.page() == PAGE_WORKSPACE and self._ws_root and \
                key == (W._key(self._ws_root), self.show_hidden.isChecked()):
            self.refresh_workspace()
        elif self.page() == PAGE_RECENT and self.search.text().strip():
            self.refresh()

    def wait_for_scans(self, timeout_ms: int = 10000) -> bool:
        """Let running scans finish and land (used by tests)."""
        waited = 0
        while self._tasks and waited < timeout_ms:
            QApplication.processEvents()
            QThread.msleep(5)
            waited += 5
        QApplication.processEvents()
        return not self._tasks

    def stop_scans(self) -> None:
        """Cancel and join every scan -- a QThread deleted while it runs takes
        the process down, so the window calls this as it closes."""
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            task.wait(5000)
        self._tasks.clear()

    # -- acting on a row ---------------------------------------------------------------

    def _on_clicked(self, item, _col=0):
        if item is None:
            return
        kind = item.data(0, _KIND)
        if kind == "workspace":
            self.show_workspace(item.data(0, _ROOT))
        elif kind == "file":
            self._open_item(item)
        elif kind == "folder":
            item.setExpanded(not item.isExpanded())

    def _open_item(self, item):
        if item is None or item.data(0, _KIND) != "file":
            return                              # a header or a folder
        if not item.data(0, _FOUND):
            return                              # "(not found)" says why
        self.openRequested.emit(item.data(0, _TARGET))

    def _show_context_menu(self, tree, pos):
        item = tree.itemAt(pos)
        if item is None or item.data(0, _KIND) is None:
            return
        tree.setCurrentItem(item)
        self._context_menu_for(item).exec(tree.viewport().mapToGlobal(pos))

    def _context_menu_for(self, item) -> QMenu:
        """A row's right-click menu, built apart from ``exec`` so its actions
        can be read and triggered without a modal menu."""
        kind = item.data(0, _KIND)
        if kind == "workspace":
            return self._workspace_menu(item.data(0, _ROOT))
        if kind == "folder":
            return self._folder_menu(item.data(0, _REL))
        return self._file_menu(item)

    def _file_menu(self, item) -> QMenu:
        path = item.data(0, _PATH)
        target = item.data(0, _TARGET)
        found = bool(item.data(0, _FOUND))
        source = item.data(0, _SOURCE)
        rel = item.data(0, _REL)
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open_item(item)).setEnabled(found)
        if self.config.is_pinned(path):
            menu.addAction("Unpin", lambda: self._pin(path, False))
        else:
            menu.addAction("Pin", lambda: self._pin(path, True))
        if source in (SRC_FAVORITE, SRC_WS_RECENT, SRC_WS_ALL) and rel:
            ws = self.config.find_workspace(self._ws_root)
            if ws is not None and ws.is_favorite(rel):
                menu.addAction("Unfavorite", lambda: self._favorite(rel, False))
            else:
                menu.addAction("Favorite", lambda: self._favorite(rel, True))
        menu.addSeparator()
        menu.addAction("Show in folder",
                       lambda: reveal_in_file_manager(target)).setEnabled(found)
        menu.addAction("Copy path",
                       lambda: QApplication.clipboard().setText(
                           os.path.abspath(target)))
        if source == SRC_RECENT:
            menu.addSeparator()
            menu.addAction("Remove from list", lambda: self._remove(path))
        elif source == SRC_WS_RECENT:
            menu.addSeparator()
            menu.addAction("Remove from this list",
                           lambda: self._forget_workspace_recent(rel))
        return menu

    def _folder_menu(self, rel_folder) -> QMenu:
        ws = self.config.find_workspace(self._ws_root)
        menu = QMenu(self)
        if ws is not None and ws.is_hidden(rel_folder):
            menu.addAction("Show in workspace",
                           lambda: self._hide_folder(rel_folder, False))
        else:
            menu.addAction("Hide from workspace",
                           lambda: self._hide_folder(rel_folder, True))
        menu.addSeparator()
        folder = W.absolute(self._ws_root, rel_folder)
        menu.addAction("Show in folder", lambda: reveal_in_file_manager(folder))
        menu.addAction("Copy path", lambda: QApplication.clipboard().setText(folder))
        return menu

    def _workspace_menu(self, root) -> QMenu:
        ws = self.config.find_workspace(root)
        menu = QMenu(self)
        if ws is None:
            return menu
        menu.addAction("Open", lambda: self.show_workspace(root))
        if ws.pinned:
            menu.addAction("Unpin", lambda: self._pin_workspace(root, False))
        else:
            menu.addAction("Pin", lambda: self._pin_workspace(root, True))
        menu.addAction("Rename…", lambda: self._rename_workspace(root))
        menu.addAction("Locate…", lambda: self._locate(root))
        menu.addSeparator()
        menu.addAction("Remove from list", lambda: self._remove_workspace(root))
        return menu

    def _refresh_current(self):
        {PAGE_RECENT: self.refresh, PAGE_WORKSPACES: self.refresh_workspaces,
         PAGE_WORKSPACE: self.refresh_workspace}[self.page()]()

    def _pin(self, path, on: bool):
        (self.config.pin_file if on else self.config.unpin_file)(path)
        self._refresh_current()

    def _remove(self, path):
        self.config.remove_recent_file(path)
        self.refresh()

    def _favorite(self, rel, on: bool):
        ws = self.config.find_workspace(self._ws_root)
        if ws is not None:
            ws.set_favorite(rel, on)
            self.config.update_workspace(ws)
        self.refresh_workspace()

    def _forget_workspace_recent(self, rel):
        ws = self.config.find_workspace(self._ws_root)
        if ws is not None:
            ws.forget_recent(rel)
            self.config.update_workspace(ws)
        self.refresh_workspace()

    def _hide_folder(self, rel_folder, on: bool):
        ws = self.config.find_workspace(self._ws_root)
        if ws is None:
            return
        ws.set_hidden(rel_folder, on)
        self.config.update_workspace(ws)
        # what a scan leaves out changed, so both cached scans are stale
        for show in (False, True):
            self._scans.pop((W._key(ws.root), show), None)
        self._show_workspace_page(rescan=True)

    # -- workspace actions -------------------------------------------------------------

    def _pin_workspace(self, root, on: bool):
        ws = self.config.find_workspace(root)
        if ws is not None:
            ws.pinned = on
            self.config.update_workspace(ws)
        self.refresh_workspaces()

    def _rename_workspace(self, root):
        ws = self.config.find_workspace(root)
        if ws is None:
            return
        text, ok = self.ask_text("Rename workspace", "Name:", ws.display_name)
        if not ok:
            return
        text = text.strip()
        # the folder's own name (or nothing) means "follow the folder"
        ws.name = "" if text in ("", os.path.basename(ws.root)) else text
        self.config.update_workspace(ws)
        self._refresh_current()

    def _add_workspace(self):
        folder = self.ask_folder("Choose the project folder to use as a workspace")
        if not folder:
            return
        try:
            ws = self.config.add_workspace(folder)
        except W.WorkspaceError as e:
            self.warn("Add workspace", str(e))
            return
        self.show_workspace(ws.root)

    def _new_workspace(self):
        parent = self.ask_folder("Where should the new workspace folder go?")
        if not parent:
            return
        name, ok = self.ask_text("New workspace", "Folder name:", "")
        if not ok or not name.strip():
            return
        try:
            ws = self.config.create_workspace(parent, name)
        except (W.WorkspaceError, OSError) as e:
            self.warn("New workspace", str(e))
            return
        self.show_workspace(ws.root)

    def _locate(self, root):
        ws = self.config.find_workspace(root)
        if ws is None:
            return
        folder = self.ask_folder(f"Where is the “{ws.display_name}” folder now?")
        if not folder:
            return
        try:
            moved = self.config.relocate_workspace(root, folder)
        except W.WorkspaceError as e:
            self.warn("Locate workspace", str(e))
            return
        self._scans = {k: v for k, v in self._scans.items() if k[0] != W._key(root)}
        self.show_workspace(moved.root)

    def _remove_workspace(self, root):
        ws = self.config.find_workspace(root)
        if ws is None:
            return
        if not self.confirm(
                "Remove workspace",
                f"Remove “{ws.display_name}” from your workspaces?\n\n"
                f"The folder and its files are not touched. Its favorites, hidden "
                f"folders and recent list here are forgotten."):
            return
        self.config.remove_workspace(root)
        self._scans = {k: v for k, v in self._scans.items() if k[0] != W._key(root)}
        if self._ws_root and W._key(self._ws_root) == W._key(root):
            self._ws_root = None
        self.show_workspaces()

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
