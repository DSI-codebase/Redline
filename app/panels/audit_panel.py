"""The Audit tab: what the design rule check found, and what it could not check.

Sibling of the TODO panel, and built the same way — a grouped tree with
clickable header sorting, free-text filtering, and struck-through rows for items
somebody has already decided about.

Two things set it apart from the other panels, and both are requirements rather
than decoration:

* **Coverage sits at the top, not the bottom.** "No findings" and "could not
  check" must never look the same, so the header states what the last run could
  not evaluate before the reader gets to the list. A clean list with a quiet
  caveat underneath is how an audit tool ends up trusted for something it never
  looked at.
* **Findings are advisory.** The wording throughout is *confirm this*, never
  *this is wrong* — the authority having jurisdiction and the listing agency
  decide compliance, not this application.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget, QMenu, QApplication)

from ..audit.findings import (DEFINITE, POTENTIAL, INFO, SEVERITY_LABELS,
                              STATUS_WAIVED, sort_findings)

GROUP_SEVERITY = "severity"
GROUP_RULE = "rule"
GROUP_SHEET = "sheet"
GROUP_NONE = "none"

_SEVERITY_ORDER = {DEFINITE: 0, POTENTIAL: 1, INFO: 2}


class AuditPanel(QWidget):
    """Findings from the most recent design rule check."""

    activated = Signal(object)              # Finding (double-clicked / Go to)
    waiveRequested = Signal(object)         # Finding (right-click ▸ Waive…)
    clearWaiverRequested = Signal(object)   # Finding (right-click ▸ Remove waiver)
    runRequested = Signal()                 # the Run button

    COL_SEV, COL_RULE, COL_SHEET, COL_PG, COL_MSG, COL_CLAUSE, COL_STATUS = range(7)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self.config = None
        self._loading = False
        self._sort_col = None
        self._sort_order = Qt.AscendingOrder
        self._build_ui()

    # -- construction --------------------------------------------------------

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # Coverage first: what was not checked is the part a reader is most
        # likely to assume away.
        self.coverage_label = QLabel("No design rule check has been run.")
        self.coverage_label.setWordWrap(True)
        lay.addWidget(self.coverage_label)

        bar = QHBoxLayout()
        self.group_by = QComboBox()
        self.group_by.addItems(
            ["Group: Severity", "Group: Rule", "Group: Sheet", "No grouping"])
        self.group_by.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit(placeholderText="Filter…")
        self.search.textChanged.connect(self.refresh)
        self.show_info = QCheckBox("Informational")
        self.show_info.setChecked(True)
        self.show_info.stateChanged.connect(self.refresh)
        self.hide_waived = QPushButton("Hide waived")
        self.hide_waived.setCheckable(True)
        self.hide_waived.toggled.connect(self.refresh)
        self.btn_run = QPushButton("Run check")
        self.btn_run.clicked.connect(self.runRequested)
        self.btn_export = QPushButton("Export report…")
        self.btn_export.clicked.connect(self._export)
        bar.addWidget(self.group_by)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_info)
        bar.addWidget(self.hide_waived)
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_export)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(
            ["Severity", "Rule", "Sheet", "Pg", "Finding", "Cited", "Status"])
        self.tree.setRootIsDecorated(self.group_by.currentIndex() < 3)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.NoDragDrop)
        # Double-click is routed by hand so it always means "show me this on the
        # drawing" and never starts an edit.
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.setColumnWidth(self.COL_SEV, 130)
        self.tree.setColumnWidth(self.COL_RULE, 180)
        self.tree.setColumnWidth(self.COL_SHEET, 56)
        self.tree.setColumnWidth(self.COL_PG, 40)
        self.tree.setColumnWidth(self.COL_MSG, 420)
        self.tree.setColumnWidth(self.COL_CLAUSE, 190)
        hdr = self.tree.header()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.sectionClicked.connect(self._on_header_clicked)
        lay.addWidget(self.tree, 1)

        self.count_label = QLabel("")
        lay.addWidget(self.count_label)

    # -- wiring --------------------------------------------------------------

    def set_document(self, document, config=None):
        self.document = document
        self.config = config
        self.refresh()

    def _findings(self) -> list:
        if self.document is None:
            return []
        out = list(getattr(self.document, "findings", []) or [])
        # A rule turned off in Settings hides its findings rather than deleting
        # them, so turning it back on restores the view without a re-run. The
        # same filter serves the overlay and the exports, so all three agree.
        if self.config is not None:
            from ..audit.findings import visible_findings
            out = visible_findings(out, self.config.audit_disabled_rules())
        if not self.show_info.isChecked():
            out = [f for f in out if f.severity != INFO]
        if self.hide_waived.isChecked():
            out = [f for f in out if not f.waived]
        needle = (self.search.text() or "").strip().lower()
        if needle:
            out = [f for f in out if needle in self._haystack(f)]
        return sort_findings(out)

    def _haystack(self, f) -> str:
        # Every sheet, not just the first: searching "236" must find the
        # finding that covers 236 even where it opens on 232.
        return " ".join(str(v).lower() for v in (
            f.severity_label, f.rule_id, " ".join(f.sheets), f.subject_id,
            f.message, f.clause, f.status))

    def _group_mode(self):
        return [GROUP_SEVERITY, GROUP_RULE, GROUP_SHEET, GROUP_NONE][
            self.group_by.currentIndex()]

    # -- sorting -------------------------------------------------------------

    _SORT_KEYS = {
        COL_SEV: lambda f: (_SEVERITY_ORDER.get(f.severity, 9),),
        COL_RULE: lambda f: (f.rule_id.lower(),),
        COL_PG: lambda f: (f.page,),
        COL_MSG: lambda f: (f.message.lower(),),
        COL_CLAUSE: lambda f: (f.clause.lower(),),
        COL_STATUS: lambda f: (f.status,),
    }

    @staticmethod
    def _sheet_sort_key(f):
        s = str(f.sheet or "")
        try:
            return (0, int(s), "")
        except (ValueError, TypeError):
            return (1, 0, s.lower())

    @staticmethod
    def _sheet_group_key(sheet: str) -> str:
        return f"Sheet {sheet}" if sheet else "(set-wide)"

    @staticmethod
    def _sheet_group_sort(key: str):
        """Sheet groups in numeric order, with the set-wide bucket last."""
        number = key[6:] if key.startswith("Sheet ") else ""
        try:
            return (0, int(number), "")
        except ValueError:
            return (1, 0, key.lower())

    def _on_header_clicked(self, col):
        if self._sort_col == col:
            self._sort_order = (Qt.DescendingOrder
                                if self._sort_order == Qt.AscendingOrder
                                else Qt.AscendingOrder)
        else:
            self._sort_col = col
            self._sort_order = Qt.AscendingOrder
        self.tree.header().setSortIndicator(col, self._sort_order)
        self.refresh()

    def _sort_within_group(self, items):
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

    # -- refresh -------------------------------------------------------------

    def refresh(self):
        self._loading = True
        try:
            self.tree.clear()
            findings = self._findings()
            mode = self._group_mode()
            self.tree.setRootIsDecorated(mode != GROUP_NONE)

            groups, order = {}, []
            for f in findings:
                if mode == GROUP_SEVERITY:
                    keys = [f.severity_label]
                elif mode == GROUP_RULE:
                    keys = [f"{f.rule_id}"]
                elif mode == GROUP_SHEET:
                    # Under EVERY sheet it covers. A finding that rolls one
                    # pasted mistake across nine sheets is one decision, but a
                    # reviewer working sheet 236 has to meet it on 236 -- and
                    # before this it appeared only under the sheet it opened
                    # on, leaving eight sheets looking clean.
                    keys = [self._sheet_group_key(s) for s in f.sheets] \
                        or [self._sheet_group_key("")]
                else:
                    keys = [None]
                for k in keys:
                    if k not in groups:
                        groups[k] = []
                        order.append(k)
                    groups[k].append(f)
            if mode == GROUP_SHEET:
                order.sort(key=self._sheet_group_sort)

            for k in order:
                parent = self.tree
                if k is not None:
                    node = QTreeWidgetItem([k])
                    node.setFirstColumnSpanned(True)
                    node.setFlags(Qt.ItemIsEnabled)
                    self.tree.addTopLevelItem(node)
                    node.setExpanded(True)
                    parent = node
                sheet = (k[6:] if mode == GROUP_SHEET and k
                         and k.startswith("Sheet ") else "")
                for f in self._sort_within_group(groups[k]):
                    self._make_row(parent, f, self._place_on(f, sheet))

            self._update_headers(findings)
        finally:
            self._loading = False

    @staticmethod
    def _place_on(f, sheet: str):
        """The place this row is about, where the row is under one sheet.

        Double-clicking a row filed under Sheet 236 has to land on 236. Sending
        the reviewer to the sheet the finding happens to open at is how a
        rolled-up finding earns a reputation for lying about where things are.
        """
        if not sheet:
            return None
        for place in getattr(f, "places", None) or ():
            if str(place.sheet) == str(sheet):
                return place
        return None

    def _make_row(self, parent, f, place=None):
        it = QTreeWidgetItem([
            # "232 +8" where the finding covers nine sheets: the suffix is what
            # tells a reviewer scanning the list that this row is not the whole
            # of the problem.
            f.severity_label, f.rule_id, f.sheet_label,
            str((place or f).page + 1) if (place or f).has_location else "",
            f.message, f.clause,
            "Waived" if f.waived else "Open",
        ])
        it.setData(0, Qt.UserRole, f)
        # Where THIS row points. Only set when the row is filed under one sheet
        # of a finding that covers several; the rest navigate by the finding.
        it.setData(0, Qt.UserRole + 1, place)
        it.setToolTip(self.COL_MSG, self._tooltip(f))
        if f.waived:
            self._apply_waived_style(it)
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(it)
        else:
            parent.addChild(it)

    def _tooltip(self, f) -> str:
        bits = [f.message]
        if f.clause:
            bits.append(f"Cited: {f.clause}")
        if f.evidence:
            bits.append("  ".join(f"{k}={v}" for k, v in f.evidence.items()))
        waiver = (self.document.waiver_for(f.key)
                  if self.document is not None else None)
        if waiver is not None:
            who = f" — {waiver.author}" if waiver.author else ""
            bits.append(f"Waived: {waiver.reason}{who}")
        return "\n".join(bits)

    def _apply_waived_style(self, it: QTreeWidgetItem):
        """Strike out and dim a waived finding, as the TODO list does for done."""
        from PySide6.QtGui import QBrush, QColor
        dim = QBrush(QColor(140, 140, 140))
        for col in range(self.tree.columnCount()):
            f = it.font(col)
            f.setStrikeOut(True)
            it.setFont(col, f)
            it.setForeground(col, dim)

    def _update_headers(self, shown):
        run = getattr(self.document, "audit_run", None) if self.document else None
        all_findings = list(getattr(self.document, "findings", []) or []) \
            if self.document is not None else []
        if run is None:
            self.coverage_label.setText("No design rule check has been run.")
        else:
            note = ("Advisory review — confirm each finding against the "
                    "governing standard.")
            text = f"{run.summary_line()}  {note}"
            # A run that recorded a problem says so here, beside the coverage
            # sentence. These used to be kept in `errors` and displayed
            # nowhere -- so a check that ran on the PDF alone because the
            # imported drawings would not load read as an ordinary one.
            # `blocked` already puts the first line in the summary.
            rest = run.errors[1:] if run.blocked else list(run.errors)
            if rest:
                text += "\n" + "\n".join(rest)
            self.coverage_label.setText(text)

        waived = sum(1 for f in all_findings if f.waived)
        by = {s: sum(1 for f in all_findings if f.severity == s and not f.waived)
              for s in (DEFINITE, POTENTIAL, INFO)}
        parts = [f"{by[s]} {SEVERITY_LABELS[s].lower()}"
                 for s in (DEFINITE, POTENTIAL, INFO) if by[s]]
        summary = ", ".join(parts) if parts else "no open findings"
        tail = f", {waived} waived" if waived else ""
        hidden = len(all_findings) - waived - sum(by.values())
        self.count_label.setText(
            f"Showing {len(shown)} of {len(all_findings)} — {summary}{tail}"
            + (f" ({hidden} filtered out)" if hidden > 0 else ""))

    # -- interaction ---------------------------------------------------------

    def _selected(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else None

    def _on_double(self, item, _col):
        f = item.data(0, Qt.UserRole)
        if f is None:
            return                       # group header
        self.activated.emit(item.data(0, Qt.UserRole + 1) or f)

    def _show_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        f = item.data(0, Qt.UserRole)
        if f is None:
            return                       # group header
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        target = item.data(0, Qt.UserRole + 1) or f
        if target.has_location:
            menu.addAction("Go to in PDF", lambda: self.activated.emit(target))
        if f.waived:
            menu.addAction("Remove waiver…",
                           lambda: self.clearWaiverRequested.emit(f))
        else:
            menu.addAction("Waive…", lambda: self.waiveRequested.emit(f))
        menu.addSeparator()
        menu.addAction("Copy finding",
                       lambda: QApplication.clipboard().setText(self._as_text(f)))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _as_text(self, f) -> str:
        seen = f.sheets
        where = ("set-wide" if not seen
                 else f"sheet {seen[0]}" if len(seen) == 1
                 else f"sheets {', '.join(seen)}")
        lines = [f"{f.severity_label}: {f.message}", f"  {f.rule_id} · {where}"]
        if f.clause:
            lines.append(f"  Cited: {f.clause}")
        return "\n".join(lines)

    def reveal(self, finding):
        """Select the row for ``finding`` (the sheet-to-panel direction)."""
        key = getattr(finding, "key", None)
        if key is None:
            return
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i)
            if self._reveal_in(node, key):
                return

    def _reveal_in(self, node, key) -> bool:
        f = node.data(0, Qt.UserRole)
        if f is not None and getattr(f, "key", None) == key:
            self.tree.setCurrentItem(node)
            self.tree.scrollToItem(node)
            return True
        for i in range(node.childCount()):
            if self._reveal_in(node.child(i), key):
                return True
        return False

    # -- export --------------------------------------------------------------

    def _export(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        if self.document is None or not getattr(self.document, "findings", None):
            QMessageBox.information(self, "Export audit report",
                                    "There is nothing to export yet — run the "
                                    "design rule check first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export audit report", "audit-report.html",
            "HTML (*.html);;Markdown (*.md);;CSV (*.csv)")
        if not path:
            return
        from ..export.audit_export import export_report
        try:
            export_report(self.document, path, disabled=(
                self.config.audit_disabled_rules() if self.config else ()))
        except Exception as e:                    # pragma: no cover - defensive
            QMessageBox.warning(self, "Export failed", str(e))
