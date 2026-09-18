"""TODO tab (Phase 5).

Top-level tab listing every TODO-flagged mark with a done/undone checkbox,
inline-editable text, page, sheet, commenter, date and tag, plus group-by
(page / sheet / commenter), filter, sort, drag-reorder and Markdown / DOCX
export.

Double-click edits a cell (Text / Sheet / Tag); the Pg cell is read-only and
double-clicking it jumps to the mark on the PDF.  Right-click → "Go to in PDF"
also jumps.  The Sheet column is a per-page value (all TODOs on a page share it),
auto-detected from the drawing title block on searchable PDFs and editable so it
can be corrected or filled in manually.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
    QAbstractItemView, QMenu,
)

from ..model.annotations import Annotation
from ..export.todo_export import (
    export_markdown, export_docx,
    GROUP_PAGE, GROUP_SHEET, GROUP_COMMENTER, GROUP_NONE,
)

_DATE = lambda iso: (iso or "")[:16].replace("T", " ")


class TodoPanel(QWidget):
    activated = Signal(object)
    authorEditRequested = Signal(object)   # Annotation (double-clicked Commenter)

    # column layout
    COL_DONE, COL_TEXT, COL_PG, COL_SHEET, COL_COMMENTER, COL_DATE, COL_TAG = range(7)
    _EDITABLE_COLS = {COL_TEXT, COL_SHEET, COL_TAG}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = None
        self.config = None
        self.document = None
        self._loading = False
        self._sort_col = None                  # None -> natural (order, page)
        self._sort_order = Qt.AscendingOrder
        self._done_width_user = None           # honoured if the user resizes col 0
        self._setting_done_width = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.group_by = QComboBox()
        self.group_by.addItems(
            ["Group: Page", "Group: Sheet", "Group: Commenter", "No grouping"])
        self.group_by.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit(placeholderText="Filter…")
        self.search.textChanged.connect(self.refresh)
        self.hide_done = QPushButton("Hide done")
        self.hide_done.setCheckable(True)
        self.hide_done.toggled.connect(self.refresh)
        self.btn_md = QPushButton("Export Markdown…")
        self.btn_md.clicked.connect(self._export_md)
        self.btn_docx = QPushButton("Export DOCX…")
        self.btn_docx.clicked.connect(self._export_docx)
        bar.addWidget(self.group_by)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.hide_done)
        bar.addWidget(self.btn_md)
        bar.addWidget(self.btn_docx)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(
            ["Done", "Text", "Pg", "Sheet", "Commenter", "Date", "Tag"])
        self.tree.setRootIsDecorated(self.group_by.currentIndex() < 3)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        # Rows are not drag-reorderable / groupable — filter + sort cover it,
        # and dragging risked accidental nesting.
        self.tree.setDragDropMode(QAbstractItemView.NoDragDrop)
        # No automatic edit triggers: we route double-click ourselves so editing
        # a cell never also jumps to the PDF (and read-only cells stay put).
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.setColumnWidth(self.COL_DONE, 44)
        self.tree.setColumnWidth(self.COL_TEXT, 300)
        self.tree.setColumnWidth(self.COL_PG, 44)
        self.tree.setColumnWidth(self.COL_SHEET, 56)
        # clickable headers sort items within each group (grouping stays primary)
        hdr = self.tree.header()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.sectionClicked.connect(self._on_header_clicked)
        hdr.sectionResized.connect(self._on_section_resized)
        lay.addWidget(self.tree, 1)

        self.count_label = QLabel("")
        lay.addWidget(self.count_label)

    # -- wiring --------------------------------------------------------------

    def set_store(self, store, config=None, document=None):
        self.store = store
        self.config = config
        self.document = document
        store.add_listener(lambda *_: QTimer.singleShot(0, self.refresh))
        self.refresh()

    def _group_mode(self):
        return [GROUP_PAGE, GROUP_SHEET, GROUP_COMMENTER, GROUP_NONE][
            self.group_by.currentIndex()]

    def _sheet_of(self, page) -> str:
        return self.document.sheet_label(page) if self.document is not None else ""

    def _sheet_map(self) -> dict:
        return dict(self.document.sheet_labels) if self.document is not None else {}

    # column -> sort key over an Annotation (Sheet handled specially below)
    _SORT_KEYS = {
        COL_DONE: lambda a: (a.todo_done,),
        COL_TEXT: lambda a: ((a.text or "").lower(),),
        COL_PG: lambda a: (a.page,),
        COL_COMMENTER: lambda a: ((a.author or "").lower(),),
        COL_DATE: lambda a: (a.created,),
        COL_TAG: lambda a: (",".join(a.tags).lower(),),
    }

    def _on_header_clicked(self, col):
        if col == self._sort_col:
            self._sort_order = (Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder
                                else Qt.AscendingOrder)
        else:
            self._sort_col = col
            self._sort_order = Qt.AscendingOrder
        self.tree.header().setSortIndicator(self._sort_col, self._sort_order)
        self.refresh()

    def _sheet_sort_key(self, a):
        s = self._sheet_of(a.page)
        try:
            return (0, int(s), "")
        except (ValueError, TypeError):
            return (1, 0, s.lower())

    def _sort_within_group(self, items):
        """Apply the active column sort to one group's items (grouping is primary)."""
        if self._sort_col is None:
            return items
        if self._sort_col == self.COL_SHEET:
            key = self._sheet_sort_key
        else:
            key = self._SORT_KEYS.get(self._sort_col)
        if key is None:
            return items
        return sorted(items, key=key,
                      reverse=self._sort_order == Qt.DescendingOrder)

    def _row_haystack(self, a) -> str:
        """All visible columns joined, for the Filter box to match across
        text, page, sheet, commenter, date and tags."""
        parts = [a.text or a.snippet(), str(a.page + 1), self._sheet_of(a.page),
                 a.author or "", _DATE(a.created), ",".join(a.tags)]
        return " ".join(p for p in parts if p).lower()

    def _todos(self):
        if self.store is None:
            return []
        show_ignored = bool(self.config and self.config.show_ignored)
        items = self.store.todos(show_ignored)
        needle = self.search.text().lower().strip()
        if needle:
            items = [a for a in items if needle in self._row_haystack(a)]
        if self.hide_done.isChecked():
            items = [a for a in items if not a.todo_done]
        items.sort(key=lambda a: (a.order, a.page, a.created))
        return items

    def refresh(self):
        if self.store is None:
            return
        self._loading = True
        self.tree.clear()
        todos = self._todos()
        mode = self._group_mode()
        self.tree.setRootIsDecorated(mode != GROUP_NONE)

        groups = {}
        order = []
        for a in todos:
            if mode == GROUP_PAGE:
                k = f"Page {a.page + 1}"
            elif mode == GROUP_SHEET:
                lbl = self._sheet_of(a.page)
                k = f"Sheet {lbl}" if lbl else "(no sheet)"
            elif mode == GROUP_COMMENTER:
                k = a.author or "(unknown)"
            else:
                k = None
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(a)

        for k in order:
            parent = self.tree
            if k is not None:
                node = QTreeWidgetItem([k])
                node.setFirstColumnSpanned(True)
                node.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(node)
                node.setExpanded(True)
                parent = node
            for a in self._sort_within_group(groups[k]):
                self._make_row(parent, a)

        self.count_label.setText(
            f"{sum(len(v) for v in groups.values())} TODO(s), "
            f"{sum(1 for a in todos if a.todo_done)} done")
        self._adjust_done_width([k for k in order if k is not None])
        self._loading = False

    # -- "Done" column auto-width (fits group names) -------------------------

    def _on_section_resized(self, idx, _old, new):
        if idx == 0 and not self._setting_done_width:
            self._done_width_user = new  # remember a manual adjustment

    def _adjust_done_width(self, group_names):
        from PySide6.QtGui import QFontMetrics
        if group_names:
            fm = QFontMetrics(self.tree.font())
            text_w = max(fm.horizontalAdvance(str(n)) for n in group_names)
            min_w = text_w + self.tree.indentation() + 28
        else:
            min_w = 44  # checkbox-only width when not grouping
        target = max(int(min_w), self._done_width_user or 0)
        self._setting_done_width = True
        self.tree.setColumnWidth(0, target)
        self._setting_done_width = False

    def _make_row(self, parent, a: Annotation):
        it = QTreeWidgetItem(["", a.text or a.snippet(), str(a.page + 1),
                              self._sheet_of(a.page), a.author or "",
                              _DATE(a.created), ",".join(a.tags)])
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
        it.setCheckState(0, Qt.Checked if a.todo_done else Qt.Unchecked)
        it.setData(0, Qt.UserRole, a)
        if a.todo_done:
            self._apply_done_style(it)
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(it)
        else:
            parent.addChild(it)

    def _apply_done_style(self, it: QTreeWidgetItem):
        """Strike out and dim a completed TODO row (the list side of the audit)."""
        from PySide6.QtGui import QBrush, QColor
        dim = QBrush(QColor(140, 140, 140))
        for col in range(self.tree.columnCount()):
            f = it.font(col)
            f.setStrikeOut(True)
            it.setFont(col, f)
            it.setForeground(col, dim)

    # -- interaction ---------------------------------------------------------

    def _on_item_changed(self, item, col):
        if self._loading:
            return
        a = item.data(0, Qt.UserRole)
        if a is None:
            return
        # Sheet is a per-page value stored on the document, not on the mark.
        if col == self.COL_SHEET and self.document is not None:
            val = item.text(self.COL_SHEET).strip()
            if val != self._sheet_of(a.page):
                self.document.set_sheet_label(a.page, val)
                QTimer.singleShot(0, self.refresh)  # all rows on this page + grouping
            return

        changed = False
        done = item.checkState(0) == Qt.Checked
        if done != a.todo_done:
            a.todo_done = done
            changed = True
        if col == self.COL_TEXT and item.text(self.COL_TEXT) != a.text:
            a.text = item.text(self.COL_TEXT)
            changed = True
        if col == self.COL_TAG:
            new_tags = [t.strip() for t in item.text(self.COL_TAG).split(",") if t.strip()]
            if new_tags != a.tags:
                a.tags = new_tags
                changed = True
        if changed:
            self.store.update(a)

    def _on_double(self, item, col):
        a = item.data(0, Qt.UserRole)
        if a is None:
            return  # group header
        if col in self._EDITABLE_COLS:
            self.tree.editItem(item, col)        # edit the cell, do not jump
        elif col == self.COL_COMMENTER:
            self.authorEditRequested.emit(a)     # change who the mark is by
        elif col == self.COL_PG:
            self.activated.emit(a)               # Pg is read-only -> jump to PDF

    def _show_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        a = item.data(0, Qt.UserRole)
        if a is None:
            return  # group header
        menu = QMenu(self)
        act_jump = menu.addAction("Go to in PDF")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == act_jump:
            self.activated.emit(a)

    def reveal(self, ann):
        """Select and scroll to ``ann`` (used when jumping in from the PDF)."""
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if self._reveal_in(top, ann):
                return True
        return False

    def _reveal_in(self, node, ann):
        if node.data(0, Qt.UserRole) is ann:
            self.tree.setCurrentItem(node)
            self.tree.scrollToItem(node)
            return True
        for j in range(node.childCount()):
            if self._reveal_in(node.child(j), ann):
                return True
        return False

    # -- export --------------------------------------------------------------

    def _export_md(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export TODO (Markdown)",
                                              "todo.md", "Markdown (*.md)")
        if not path:
            return
        try:
            export_markdown(self._todos(), path, group_by=self._group_mode(),
                            sheet_labels=self._sheet_map())
            QMessageBox.information(self, "Exported", f"Wrote {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def _export_docx(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export TODO (DOCX)",
                                              "todo.docx", "Word (*.docx)")
        if not path:
            return
        try:
            export_docx(self._todos(), path, group_by=self._group_mode(),
                        sheet_labels=self._sheet_map())
            QMessageBox.information(self, "Exported", f"Wrote {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
