"""Component Labels tab.

Sibling of the Wire Numbers tab: runs the extract -> parse -> classify pipeline
for *device/component* tags (e.g. ``LT-10010``), shows a spot-checkable table
with the same select / search / sort / filter controls, and drives the
xlsx/csv exports.  Scanned pages are read with the user's choice of OCR or
Claude AI assist.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QHeaderView, QAbstractItemView, QProgressBar,
)

from ..extraction.component_parser import (
    ComponentParser, dedupe, TYPE_CONFORMING, TYPE_NONCONFORMING,
    FLAG_UNKNOWN_FAMILY,
)
from ..export.component_export import (
    export_single_file, export_per_sheet, ComponentExportOptions,
    SORT_IN_ORDER, SORT_NUMERICAL, SORT_BY_SHEET,
)
# reuse the numeric-sorting table item from the wire panel
from .wire_panel import _SortItem, _num_key, _i

_COLS = ["✓", "Label", "Family", "Sheet", "Rung", "Type", "Pg", "Count", "Source", "Flags"]
_TYPE_COLORS = {TYPE_CONFORMING: "#1b7f3a", TYPE_NONCONFORMING: "#b8860b"}
# Sheet, Rung, Pg, Count sort numerically
_NUMERIC_COLS = {3, 4, 6, 7}


class _ComponentWorker(QThread):
    """Runs the (OCR/AI-heavy) component extraction off the UI thread."""

    progress = Signal(int, int, str)
    done = Signal(list, dict)
    failed = Signal(str)

    def __init__(self, pdf_path, comp_config, method="ai", ai_key="",
                 ai_model="claude-opus-4-8", ai_tiles=2, ocr_zoom=3.0, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.cfg = comp_config
        self.method = method
        self.ai_key = ai_key
        self.ai_model = ai_model
        self.ai_tiles = max(1, int(ai_tiles))
        self.ocr_zoom = ocr_zoom
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            import fitz
            from ..extraction.text_extract import collect_component_tokens, page_has_text
            from ..extraction import ocr as _ocr, claude_api
            doc = fitz.open(self.pdf_path)
            try:
                families = tuple(self.cfg.families) if self.cfg else ()
                ai_ok = self.method == "ai" and claude_api.available(self.ai_key)
                ocr_ok = self.method == "ocr" and _ocr.available()
                tag = " (AI)" if ai_ok else (" (OCR)" if ocr_ok else "")

                def on_progress(cur, total):
                    self.progress.emit(cur, total, f"Scanning page {cur} of {total}…{tag}")

                def on_tile(cur, total, td, tt):
                    self.progress.emit(
                        cur, total,
                        f"Scanning page {cur} of {total} — AI tile {td}/{tt}…")

                tokens = collect_component_tokens(
                    doc, method=self.method, ai_key=self.ai_key,
                    ai_model=self.ai_model, ai_tiles=self.ai_tiles,
                    families=families, ocr_zoom=self.ocr_zoom,
                    progress=on_progress, should_cancel=lambda: self._cancel,
                    ai_tile_progress=on_tile)
                if self._cancel:
                    self.failed.emit("__cancelled__")
                    return
                self.progress.emit(doc.page_count, doc.page_count,
                                   "Parsing & classifying component labels…")
                comps = dedupe(ComponentParser(self.cfg).parse(tokens))
                scanned = sum(1 for i in range(doc.page_count)
                              if not page_has_text(doc[i]))
                summary = {"tokens": len(tokens), "scanned_pages": scanned,
                           "ai_used": ai_ok, "ocr_used": ocr_ok}
                self.done.emit(comps, summary)
            finally:
                doc.close()
        except Exception as e:  # pragma: no cover - defensive
            self.failed.emit(str(e))


class ComponentPanel(QWidget):
    activated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self.config = None
        self.components = []
        self._worker = None
        self._build_ui()

    # -- ui ------------------------------------------------------------------

    def _build_ui(self):
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_extract = QPushButton("Extract component labels")
        self.btn_extract.clicked.connect(self.extract)
        top.addWidget(self.btn_extract)
        top.addWidget(QLabel("Scanned pages:"))
        self.method = QComboBox(); self.method.addItems(["AI assist", "OCR"])
        self.method.setToolTip("How to read pages that have no text layer "
                               "(scanned drawings). Vector pages always use the "
                               "text layer.")
        top.addWidget(self.method)
        self.extract_progress = QProgressBar()
        self.extract_progress.setFixedWidth(200)
        self.extract_progress.setVisible(False)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_extract)
        self.status = QLabel("Open a PDF, then extract.")
        top.addWidget(self.extract_progress)
        top.addWidget(self.btn_cancel)
        top.addWidget(self.status, 1)
        lay.addLayout(top)

        filt = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search label…")
        self.search.textChanged.connect(self._apply_filter)
        self.show_conforming = QCheckBox("Conforming"); self.show_conforming.setChecked(True)
        self.show_nonconforming = QCheckBox("Other length"); self.show_nonconforming.setChecked(True)
        self.show_unknown = QCheckBox("Unknown family"); self.show_unknown.setChecked(True)
        for cb in (self.show_conforming, self.show_nonconforming, self.show_unknown):
            cb.stateChanged.connect(self._apply_filter)
        filt.addWidget(QLabel("Show:"))
        filt.addWidget(self.show_conforming)
        filt.addWidget(self.show_nonconforming)
        filt.addWidget(self.show_unknown)
        filt.addWidget(self.search, 1)
        self.btn_check_all = QPushButton("Check all")
        self.btn_check_all.clicked.connect(lambda: self._set_all_visible(True))
        self.btn_uncheck_all = QPushButton("Uncheck all")
        self.btn_uncheck_all.clicked.connect(lambda: self._set_all_visible(False))
        filt.addWidget(self.btn_check_all)
        filt.addWidget(self.btn_uncheck_all)
        lay.addLayout(filt)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_double)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        for col, width in {0: 28, 1: 110, 2: 64, 3: 56, 4: 56,
                           5: 110, 6: 44, 7: 56, 8: 64}.items():
            self.table.setColumnWidth(col, width)
        self.table.setSortingEnabled(True)
        lay.addWidget(self.table, 1)

        exp = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(["Single file (~sheet~)", "Per-sheet files"])
        self.fmt = QComboBox(); self.fmt.addItems(["xlsx", "csv"])
        self.sort = QComboBox(); self.sort.addItems(["Numerical", "In drawing order", "By sheet"])
        self.labels_per = QSpinBox(); self.labels_per.setRange(1, 99); self.labels_per.setValue(1)
        self.dedupe = QCheckBox("Dedupe"); self.dedupe.setChecked(True)
        self.labels_only = QCheckBox("Labels only")
        self.btn_export = QPushButton("Export…")
        self.btn_export.clicked.connect(self.export)
        exp.addWidget(QLabel("Mode:")); exp.addWidget(self.mode)
        exp.addWidget(QLabel("Fmt:")); exp.addWidget(self.fmt)
        exp.addWidget(QLabel("Sort:")); exp.addWidget(self.sort)
        exp.addWidget(QLabel("Labels/device:")); exp.addWidget(self.labels_per)
        exp.addWidget(self.dedupe)
        exp.addWidget(self.labels_only)
        exp.addStretch(1)
        exp.addWidget(self.btn_export)
        lay.addLayout(exp)

    # -- wiring --------------------------------------------------------------

    def set_document(self, document, config=None):
        self._stop_worker()
        self._end_extract()
        self.document = document
        self.config = config
        self.components = list(getattr(document, "components", []) or [])
        if config is not None:
            self.method.setCurrentIndex(0 if config.component_extract_method == "ai" else 1)
            self.labels_per.setValue(config.component_labels_per_device)
        if self.components:
            self._populate()
            self.status.setText(
                f"{len(self.components)} cached component labels (re-extract to refresh).")
        else:
            self.table.setRowCount(0)
            self.status.setText("Open a PDF, then extract.")

    # -- extraction ----------------------------------------------------------

    def extract(self):
        if self.document is None:
            QMessageBox.information(self, "No document", "Open a PDF first.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        cfg = self.config.component_config() if self.config else None
        method = "ai" if self.method.currentIndex() == 0 else "ocr"
        ai_key = self.config.ai_api_key if self.config else ""
        ai_model = self.config.ai_model if self.config else "claude-opus-4-8"
        ai_tiles = self.config.ai_tiles if self.config else 2

        if method == "ai":
            try:
                from ..extraction import claude_api
                from ..extraction.text_extract import page_has_text
                if not claude_api.available(ai_key):
                    QMessageBox.information(
                        self, "AI not available",
                        "Claude AI assist isn't configured. Add an API key in "
                        "Settings, or choose OCR for scanned pages.")
                else:
                    scanned = sum(1 for i in range(self.document.page_count)
                                  if not page_has_text(self.document.fitz_doc[i]))
                    if scanned > 0:
                        calls = scanned * ai_tiles * ai_tiles
                        grid = (f"{ai_tiles}×{ai_tiles} tiles each" if ai_tiles > 1
                                else "whole page")
                        resp = QMessageBox.question(
                            self, "Use AI on scanned pages?",
                            f"{scanned} page(s) have no text layer. Read them with "
                            f"Claude ({ai_model}), {grid}?\n\nThat's about {calls} "
                            f"API call(s). Adjust 'AI tiling' in Settings to trade "
                            f"accuracy for cost.",
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                        if resp != QMessageBox.Yes:
                            return
            except Exception:
                pass

        total = max(1, self.document.page_count)
        self.extract_progress.setRange(0, total)
        self.extract_progress.setValue(0)
        self.extract_progress.setVisible(True)
        self.btn_cancel.setVisible(True)
        self.btn_extract.setEnabled(False)
        self.status.setText("Starting extraction…")

        self._worker = _ComponentWorker(
            self.document.path, cfg, method=method, ai_key=ai_key,
            ai_model=ai_model, ai_tiles=ai_tiles, ocr_zoom=3.0)
        self._worker.progress.connect(self._on_extract_progress)
        self._worker.done.connect(self._on_extract_done)
        self._worker.failed.connect(self._on_extract_failed)
        self._worker.start()

    def _cancel_extract(self):
        if self._worker is not None and self._worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.status.setText("Cancelling…")
            self._worker.cancel()

    def _on_extract_progress(self, current, total, message):
        self.extract_progress.setRange(0, total)
        self.extract_progress.setValue(current)
        self.status.setText(message)

    def _on_extract_done(self, comps, summary):
        self.components = comps
        if self.document is not None:
            self.document.set_components(self.components)
        self._populate()
        if self.components:
            n_conf = sum(1 for c in self.components if c.comp_type == TYPE_CONFORMING)
            n_unk = sum(1 for c in self.components if FLAG_UNKNOWN_FAMILY in c.flags)
            self.status.setText(
                f"{len(self.components)} unique labels — {n_conf} conforming, "
                f"{n_unk} unknown-family ({summary.get('tokens', 0)} tokens scanned).")
        else:
            scanned = summary.get("scanned_pages", 0)
            if scanned and not summary.get("ai_used") and not summary.get("ocr_used"):
                self.status.setText(
                    f"No component labels found — {scanned} page(s) are scanned "
                    f"images with no text. Pick AI assist (or OCR) and try again.")
            else:
                self.status.setText("No component labels found.")
        self._end_extract()

    def _on_extract_failed(self, message):
        if message == "__cancelled__":
            self.status.setText("Extraction cancelled.")
        else:
            QMessageBox.warning(self, "Extraction failed", message)
            self.status.setText("Extraction failed.")
        self._end_extract()

    def _end_extract(self):
        self.extract_progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(True)
        self.btn_extract.setEnabled(True)
        if self._worker is not None:
            self._worker.wait(3000)
            self._worker = None

    def _stop_worker(self):
        w = self._worker
        if w is None:
            return
        try:
            w.progress.disconnect(); w.done.disconnect(); w.failed.disconnect()
        except Exception:
            pass
        if w.isRunning():
            w.cancel()
            w.wait(30000)
        self._worker = None

    def shutdown(self):
        self._stop_worker()

    # -- table ---------------------------------------------------------------

    def _populate(self):
        self.table.setSortingEnabled(False)
        self.table.itemChanged.disconnect(self._on_item_changed)
        self.table.setRowCount(0)
        for c in self.components:
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if c.included else Qt.Unchecked)
            chk.setData(Qt.UserRole, c)
            self.table.setItem(r, 0, chk)
            flag_txt = "unknown family" if FLAG_UNKNOWN_FAMILY in c.flags else ""
            vals = [c.label, c.family, _i(c.sheet), _i(c.rung), c.comp_type,
                    str(c.page + 1), str(c.count), c.source, flag_txt]
            for col, v in enumerate(vals, start=1):
                key = _num_key(v) if col in _NUMERIC_COLS else None
                it = _SortItem(v, key)
                if col == 5:
                    from PySide6.QtGui import QColor
                    it.setForeground(QColor(_TYPE_COLORS.get(c.comp_type, "#000")))
                self.table.setItem(r, col, it)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setSortingEnabled(True)
        self._apply_filter()

    def _apply_filter(self):
        needle = self.search.text().lower().strip()
        allowed = set()
        if self.show_conforming.isChecked():
            allowed.add(TYPE_CONFORMING)
        if self.show_nonconforming.isChecked():
            allowed.add(TYPE_NONCONFORMING)
        hide_unknown = not self.show_unknown.isChecked()
        for r in range(self.table.rowCount()):
            c = self.table.item(r, 0).data(Qt.UserRole)
            show = c.comp_type in allowed and (not needle or needle in c.label.lower())
            if hide_unknown and FLAG_UNKNOWN_FAMILY in c.flags:
                show = False
            self.table.setRowHidden(r, not show)

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        c = item.data(Qt.UserRole)
        if c is None:
            return
        checked = item.checkState() == Qt.Checked
        c.included = checked
        self._mark_dirty()
        sel_rows = {ix.row() for ix in self.table.selectionModel().selectedRows()}
        if item.row() in sel_rows and len(sel_rows) > 1:
            self._apply_check_to_rows(sel_rows, checked)

    def _mark_dirty(self):
        """A tick is a decision, and it only reaches disk on File > Save."""
        if self.document is not None:
            self.document.mark_dirty()

    def _apply_check_to_rows(self, rows, checked):
        self._mark_dirty()
        self.table.blockSignals(True)
        try:
            state = Qt.Checked if checked else Qt.Unchecked
            for r in rows:
                cell = self.table.item(r, 0)
                if cell is None:
                    continue
                cell.setCheckState(state)
                c = cell.data(Qt.UserRole)
                if c is not None:
                    c.included = checked
        finally:
            self.table.blockSignals(False)

    def _set_all_visible(self, checked):
        rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        self._apply_check_to_rows(rows, checked)

    def _on_double(self, row, _col):
        c = self.table.item(row, 0).data(Qt.UserRole)
        if c is not None:
            self.activated.emit(c)

    # -- export --------------------------------------------------------------

    def _build_options(self) -> ComponentExportOptions:
        sort = {0: SORT_NUMERICAL, 1: SORT_IN_ORDER, 2: SORT_BY_SHEET}[self.sort.currentIndex()]
        return ComponentExportOptions(
            fmt=self.fmt.currentText(),
            labels_per_device=self.labels_per.value(),
            sort=sort,
            include_nonconforming=self.show_nonconforming.isChecked(),
            include_unknown_family=self.show_unknown.isChecked(),
            dedupe=self.dedupe.isChecked(),
            only_included=True,
            labels_only=self.labels_only.isChecked() or None,
        )

    def export(self):
        if not self.components:
            QMessageBox.information(self, "Nothing to export",
                                    "Extract component labels first.")
            return
        opts = self._build_options()
        single = self.mode.currentIndex() == 0
        try:
            if single:
                ext = "xlsx" if opts.fmt == "xlsx" else "csv"
                path, _ = QFileDialog.getSaveFileName(
                    self, "Export component labels", f"components.{ext}",
                    f"Spreadsheet (*.{ext})")
                if not path:
                    return
                export_single_file(self.components, path, opts)
                QMessageBox.information(self, "Exported", f"Wrote {path}")
            else:
                out_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
                if not out_dir:
                    return
                paths = export_per_sheet(self.components, out_dir, opts)
                QMessageBox.information(self, "Exported",
                                        f"Wrote {len(paths)} file(s) to {out_dir}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
