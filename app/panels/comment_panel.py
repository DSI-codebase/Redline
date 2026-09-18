"""Comment sidebar (Phase 4).

A dockable, Chrome-bookmarks-style list of every non-ignored comment / text box
(and optionally highlights & pen strokes) with live filter + sort.  Clicking a
row asks the viewer to scroll to and flash the mark.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QLabel,
    QTreeWidget, QTreeWidgetItem, QCheckBox, QPushButton, QMenu, QMessageBox,
)

from ..model.annotations import (
    Annotation, KIND_COMMENT, KIND_TEXTBOX, KIND_HIGHLIGHT, KIND_PEN,
    KIND_RECT, KIND_ARROW, KIND_CALLOUT, KIND_CLOUD,
)

_KIND_ICON = {
    KIND_COMMENT: "💬", KIND_TEXTBOX: "🅣", KIND_HIGHLIGHT: "🖍", KIND_PEN: "✎",
    KIND_RECT: "▭", KIND_ARROW: "↗", KIND_CALLOUT: "🗨", KIND_CLOUD: "☁",
}
_DATE = lambda iso: (iso or "")[:16].replace("T", " ")

SORTS = ["Page", "Commenter", "Datetime", "Type"]


class CommentPanel(QWidget):
    activated = Signal(object)       # Annotation
    todoToggled = Signal(object)     # Annotation
    deleteRequested = Signal(object)  # Annotation (already user-confirmed)
    authorEditRequested = Signal(object)  # Annotation (double-clicked the "By" column)

    _COL_BY = 3                      # the "By" (commenter) column

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = None
        self.config = None
        self._build_ui()

    # -- ui ------------------------------------------------------------------

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        self.search = QLineEdit(placeholderText="Search comments…")
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)

        row = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItems(["All types", "Comment", "Text box", "Highlight",
                                   "Pen", "Rectangle", "Arrow", "Callout", "Cloud"])
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.commenter_filter = QComboBox()
        self.commenter_filter.addItem("All commenters")
        self.commenter_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.type_filter)
        row.addWidget(self.commenter_filter)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.sort_by = QComboBox()
        self.sort_by.addItems(SORTS)
        self.sort_by.currentIndexChanged.connect(self.refresh)
        self.sort_desc = QCheckBox("Desc")
        self.sort_desc.stateChanged.connect(self.refresh)
        self.todo_only = QCheckBox("TODO only")
        self.todo_only.stateChanged.connect(self.refresh)
        row2.addWidget(QLabel("Sort:"))
        row2.addWidget(self.sort_by, 1)
        row2.addWidget(self.sort_desc)
        row2.addWidget(self.todo_only)
        self.btn_delete = QPushButton("🗑")
        self.btn_delete.setToolTip("Delete selected comment (Del)")
        self.btn_delete.setFixedWidth(34)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete_selected)
        row2.addWidget(self.btn_delete)
        lay.addLayout(row2)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["", "Comment", "Pg", "By"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.itemSelectionChanged.connect(self._update_delete_enabled)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.setColumnWidth(0, 26)
        self.tree.setColumnWidth(1, 220)
        self.tree.setColumnWidth(2, 32)
        lay.addWidget(self.tree, 1)

        # Delete key (scoped to the list)
        sc = QShortcut(QKeySequence.Delete, self.tree)
        sc.setContext(Qt.WidgetShortcut)
        sc.activated.connect(self._delete_selected)

        self.count_label = QLabel("")
        lay.addWidget(self.count_label)

    # -- wiring --------------------------------------------------------------

    def set_store(self, store, config=None):
        self.store = store
        self.config = config
        store.add_listener(self._on_store_event)
        self.refresh()

    def _on_store_event(self, event, ann):
        # debounce-ish: refresh on the event loop
        QTimer.singleShot(0, self.refresh)

    # -- filtering -----------------------------------------------------------

    def _included_kinds(self):
        idx = self.type_filter.currentIndex()
        return {
            0: None,
            1: {KIND_COMMENT}, 2: {KIND_TEXTBOX},
            3: {KIND_HIGHLIGHT}, 4: {KIND_PEN},
            5: {KIND_RECT}, 6: {KIND_ARROW}, 7: {KIND_CALLOUT}, 8: {KIND_CLOUD},
        }[idx]

    def _refresh_commenters(self, anns):
        current = self.commenter_filter.currentText()
        names = sorted({a.author for a in anns if a.author})
        self.commenter_filter.blockSignals(True)
        self.commenter_filter.clear()
        self.commenter_filter.addItem("All commenters")
        self.commenter_filter.addItems(names)
        i = self.commenter_filter.findText(current)
        self.commenter_filter.setCurrentIndex(i if i >= 0 else 0)
        self.commenter_filter.blockSignals(False)

    def refresh(self):
        if self.store is None:
            return
        show_ignored = bool(self.config and self.config.show_ignored)
        base = [a for a in self.store.visible(show_ignored) if a.shows_in_comments]
        self._refresh_commenters(base)

        kinds = self._included_kinds()
        needle = self.search.text().lower().strip()
        commenter = self.commenter_filter.currentText()

        rows = []
        for a in base:
            if kinds is not None and a.kind not in kinds:
                continue
            if self.todo_only.isChecked() and not a.is_todo:
                continue
            if commenter != "All commenters" and a.author != commenter:
                continue
            if needle and needle not in (a.text or "").lower():
                continue
            rows.append(a)

        key = {0: lambda a: a.page, 1: lambda a: a.author.lower(),
               2: lambda a: a.created, 3: lambda a: a.kind}[self.sort_by.currentIndex()]
        rows.sort(key=key, reverse=self.sort_desc.isChecked())

        self.tree.clear()
        for a in rows:
            it = QTreeWidgetItem([
                _KIND_ICON.get(a.kind, "•"),
                a.snippet(48) + ("  ✓" if a.is_todo and a.todo_done else
                                 "  ☐" if a.is_todo else ""),
                str(a.page + 1),
                a.author or "",
            ])
            it.setData(0, Qt.UserRole, a)
            it.setToolTip(1, f"{a.text}\n{a.author} · {_DATE(a.created)}")
            self.tree.addTopLevelItem(it)
        self.count_label.setText(f"{len(rows)} item(s)")

    # -- interaction ---------------------------------------------------------

    def _on_click(self, item, _col):
        ann = item.data(0, Qt.UserRole)
        if ann is not None:
            self.activated.emit(ann)

    def _on_double(self, item, col):
        # double-click the "By" column to change who the comment is by
        ann = item.data(0, Qt.UserRole)
        if ann is not None and col == self._COL_BY:
            self.authorEditRequested.emit(ann)

    def _selected_annotation(self):
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole)

    def reveal(self, ann):
        """Select and scroll to ``ann`` (used when jumping in from the PDF)."""
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.UserRole) is ann:
                self.tree.setCurrentItem(it)
                self.tree.scrollToItem(it)
                return True
        return False

    def _update_delete_enabled(self):
        self.btn_delete.setEnabled(self._selected_annotation() is not None)

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        item.setSelected(True)
        menu = QMenu(self)
        act = menu.addAction("Delete comment")
        if menu.exec(self.tree.viewport().mapToGlobal(pos)) == act:
            self._delete_selected()

    def _delete_selected(self):
        ann = self._selected_annotation()
        if ann is None:
            return
        resp = QMessageBox.question(
            self, "Delete comment",
            f"Delete this {ann.kind}?\n\n{ann.snippet(80)}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp == QMessageBox.Yes:
            self.deleteRequested.emit(ann)
