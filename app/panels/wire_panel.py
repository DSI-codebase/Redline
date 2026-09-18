"""Wire Numbers tab (Phase 6 + 7).

Runs the extract -> parse -> classify pipeline, shows a spot-checkable table
(sheet, rung, wire-idx, label, type, page, count, source), and drives the
xlsx/csv exports in both per-sheet and single-file modes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QHeaderView, QAbstractItemView, QProgressBar,
)

from ..extraction.text_extract import collect_tokens
from ..extraction.wire_parser import (
    WireParser, dedupe, TYPE_CONFORMING, TYPE_FIXED, TYPE_JUMPER,
    FLAG_SHEET_MISMATCH,
)
from ..export.wire_export import (
    export_single_file, export_per_sheet, WireExportOptions,
    SORT_IN_ORDER, SORT_NUMERICAL, SORT_BY_SHEET,
)

_COLS = ["✓", "Label", "Sheet", "Rung", "Idx", "Type", "Pg", "Count", "Source", "Flags"]
_TYPE_COLORS = {
    TYPE_CONFORMING: "#1b7f3a",
    TYPE_FIXED: "#b8860b",
    TYPE_JUMPER: "#8a8a8a",
}
# table columns that should sort numerically (Label, Sheet, Rung, Idx, Pg, Count)
_NUMERIC_COLS = {1, 2, 3, 4, 6, 7}


class _SortItem(QTableWidgetItem):
    """Table item that sorts by a numeric key when one is present, so columns
    like Sheet order 2, 100, 110 (not the string order 100, 110, 2)."""

    def __init__(self, text, key=None):
        super().__init__(text)
        self._key = key

    def __lt__(self, other):
        a = getattr(self, "_key", None)
        b = getattr(other, "_key", None)
        if a is not None and b is not None:
            try:
                return a < b
            except TypeError:
                pass
        # explicit string fallback (the base operator< is unreliable for items
        # not attached to a table)
        try:
            return self.text() < other.text()
        except Exception:
            return super().__lt__(other)


def _num_key(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


class _ExtractWorker(QThread):
    """Runs the (potentially slow, OCR/AI-heavy) extraction off the UI thread."""

    progress = Signal(int, int, str)     # current page, total, message
    done = Signal(list, dict)            # deduped wires, summary
    failed = Signal(str)

    def __init__(self, pdf_path, wire_config, ocr_enabled=False,
                 ai_enabled=False, ai_key="", ai_model="claude-opus-4-8",
                 ai_tiles=2, ocr_zoom=3.0, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.cfg = wire_config
        self.ocr_enabled = ocr_enabled
        self.ai_enabled = ai_enabled
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
            from ..extraction.text_extract import page_has_text
            from ..extraction import ocr as _ocr, claude_api
            doc = fitz.open(self.pdf_path)
            try:
                cfg = self.cfg
                fw = ((cfg.sheet_width, cfg.rung_width, cfg.wire_width)
                      if cfg is not None else (3, 2, 1))
                zp = cfg.zero_pad if cfg is not None else True
                ai_ok = self.ai_enabled and claude_api.available(self.ai_key)
                ocr_ok = self.ocr_enabled and _ocr.available()

                mode = " (AI)" if ai_ok else (" (OCR)" if ocr_ok else "")

                def on_progress(cur, total):
                    self.progress.emit(cur, total, f"Scanning page {cur} of {total}…{mode}")

                def on_tile(cur, total, td, tt):
                    self.progress.emit(
                        cur, total,
                        f"Scanning page {cur} of {total} — AI tile {td}/{tt}…")

                tokens = collect_tokens(
                    doc, ocr_enabled=self.ocr_enabled, ocr_zoom=self.ocr_zoom,
                    ai_enabled=self.ai_enabled, ai_key=self.ai_key,
                    ai_model=self.ai_model, field_widths=fw, zero_pad=zp,
                    ai_tiles=self.ai_tiles, ai_tile_progress=on_tile,
                    progress=on_progress, should_cancel=lambda: self._cancel)
                if self._cancel:
                    self.failed.emit("__cancelled__")
                    return
                self.progress.emit(doc.page_count, doc.page_count,
                                   "Parsing & classifying wire numbers…")
                wires = dedupe(WireParser(self.cfg).parse(tokens))
                scanned = sum(1 for i in range(doc.page_count)
                              if not page_has_text(doc[i]))
                summary = {
                    "tokens": len(tokens),
                    "scanned_pages": scanned,
                    "ai_used": ai_ok,
                    "ocr_used": ocr_ok,
                }
                self.done.emit(wires, summary)
            finally:
                doc.close()
        except Exception as e:  # pragma: no cover - defensive
            self.failed.emit(str(e))


class WirePanel(QWidget):
    activated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self.config = None
        self.wires = []
        self._worker = None
        self._build_ui()

    # -- ui ------------------------------------------------------------------

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # extraction row
        top = QHBoxLayout()
        self.btn_extract = QPushButton("Extract wire numbers")
        self.btn_extract.clicked.connect(self.extract)
        top.addWidget(self.btn_extract)
        top.addWidget(QLabel("Scanned pages:"))
        self.method = QComboBox(); self.method.addItems(["AI assist", "OCR"])
        self.method.setToolTip("How to read pages that have no text layer "
                               "(scanned drawings). Vector pages always use the "
                               "text layer.")
        top.addWidget(self.method)
        self.extract_progress = QProgressBar()
        self.extract_progress.setFixedWidth(220)
        self.extract_progress.setVisible(False)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_extract)
        self.status = QLabel("Open a PDF, then extract.")
        top.addWidget(self.extract_progress)
        top.addWidget(self.btn_cancel)
        top.addWidget(self.status, 1)
        lay.addLayout(top)

        # filter row
        filt = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search label…")
        self.search.textChanged.connect(self._apply_filter)
        self.show_conforming = QCheckBox("Conforming"); self.show_conforming.setChecked(True)
        self.show_fixed = QCheckBox("Fixed/OEM"); self.show_fixed.setChecked(True)
        self.show_jumpers = QCheckBox("Jumpers"); self.show_jumpers.setChecked(False)
        for cb in (self.show_conforming, self.show_fixed, self.show_jumpers):
            cb.stateChanged.connect(self._apply_filter)
        filt.addWidget(QLabel("Show:"))
        filt.addWidget(self.show_conforming)
        filt.addWidget(self.show_fixed)
        filt.addWidget(self.show_jumpers)
        filt.addWidget(self.search, 1)
        self.btn_check_all = QPushButton("Check all")
        self.btn_check_all.setToolTip("Include every visible row in the export")
        self.btn_check_all.clicked.connect(lambda: self._set_all_visible(True))
        self.btn_uncheck_all = QPushButton("Uncheck all")
        self.btn_uncheck_all.clicked.connect(lambda: self._set_all_visible(False))
        filt.addWidget(self.btn_check_all)
        filt.addWidget(self.btn_uncheck_all)
        lay.addLayout(filt)

        # table
        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # shift/ctrl
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_double)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)  # user-resizable columns
        hdr.setStretchLastSection(True)
        for col, width in {0: 28, 1: 90, 2: 56, 3: 56, 4: 48,
                           5: 100, 6: 44, 7: 56, 8: 64}.items():
            self.table.setColumnWidth(col, width)
        self.table.setSortingEnabled(True)
        lay.addWidget(self.table, 1)

        # export row
        exp = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(["Single file (~sheet~)", "Per-sheet files"])
        self.fmt = QComboBox(); self.fmt.addItems(["xlsx", "csv"])
        self.sort = QComboBox(); self.sort.addItems(["Numerical", "In drawing order", "By sheet"])
        self.labels_per = QSpinBox(); self.labels_per.setRange(1, 99); self.labels_per.setValue(2)
        self.dedupe = QCheckBox("Dedupe"); self.dedupe.setChecked(True)
        self.labels_only = QCheckBox("Labels only"); self.labels_only.setTristate(False)
        self.btn_export = QPushButton("Export…")
        self.btn_export.clicked.connect(self.export)
        exp.addWidget(QLabel("Mode:")); exp.addWidget(self.mode)
        exp.addWidget(QLabel("Fmt:")); exp.addWidget(self.fmt)
        exp.addWidget(QLabel("Sort:")); exp.addWidget(self.sort)
        exp.addWidget(QLabel("Labels/wire:")); exp.addWidget(self.labels_per)
        exp.addWidget(self.dedupe)
        exp.addWidget(self.labels_only)
        exp.addStretch(1)
        exp.addWidget(self.btn_export)
        lay.addLayout(exp)

    # -- wiring --------------------------------------------------------------

    def set_document(self, document, config=None):
        self._stop_worker()  # never let a stale extraction land on a new doc
        self._end_extract()
        self.document = document
        self.config = config
        self.wires = list(getattr(document, "wires", []) or [])
        if config is not None:
            self.method.setCurrentIndex(0 if config.wire_extract_method == "ai" else 1)
        if self.wires:
            self._populate()
            self.status.setText(f"{len(self.wires)} cached wire numbers (re-extract to refresh).")
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
        cfg = self.config.wire_config() if self.config else None
        # the tab's dropdown picks the engine for scanned pages (overrides the
        # global enable toggles); vector pages always use the text layer
        method = "ai" if self.method.currentIndex() == 0 else "ocr"
        ai_enabled = method == "ai"
        ocr_enabled = method == "ocr"
        ai_key = self.config.ai_api_key if self.config else ""
        ai_model = self.config.ai_model if self.config else "claude-opus-4-8"
        ai_tiles = self.config.ai_tiles if self.config else 2

        # Cost guard: if AI will run over scanned pages, confirm first (each page
        # makes tiles x tiles API calls).
        if ai_enabled:
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
                        grid = (f"{ai_tiles}×{ai_tiles} tiles each"
                                if ai_tiles > 1 else "whole page")
                        resp = QMessageBox.question(
                            self, "Use AI on scanned pages?",
                            f"{scanned} page(s) have no text layer. Read them with "
                            f"Claude ({ai_model}), {grid}?\n\n"
                            f"That's about {calls} API call(s). "
                            f"Adjust 'AI tiling' in Settings to trade accuracy for cost.",
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                        if resp != QMessageBox.Yes:
                            return
            except Exception:
                pass

        # show the progress UI and start the background worker
        total = max(1, self.document.page_count)
        self.extract_progress.setRange(0, total)
        self.extract_progress.setValue(0)
        self.extract_progress.setVisible(True)
        self.btn_cancel.setVisible(True)
        self.btn_extract.setEnabled(False)
        self.status.setText("Starting extraction…")

        self._worker = _ExtractWorker(
            self.document.path, cfg, ocr_enabled=ocr_enabled,
            ai_enabled=ai_enabled, ai_key=ai_key, ai_model=ai_model,
            ai_tiles=ai_tiles, ocr_zoom=3.0)
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

    def _on_extract_done(self, wires, summary):
        self.wires = wires
        if self.document is not None:
            self.document.set_wires(self.wires)
        self._populate()
        if self.wires:
            n_conf = sum(1 for w in self.wires if w.wire_type == TYPE_CONFORMING)
            n_fix = sum(1 for w in self.wires if w.wire_type == TYPE_FIXED)
            n_jmp = sum(1 for w in self.wires if w.wire_type == TYPE_JUMPER)
            self.status.setText(
                f"{len(self.wires)} unique labels — "
                f"{n_conf} conforming, {n_fix} fixed/OEM, {n_jmp} jumpers "
                f"({summary.get('tokens', 0)} tokens scanned).")
        else:
            # explain *why* nothing was found, especially for scanned PDFs
            scanned = summary.get("scanned_pages", 0)
            if scanned and not summary.get("ai_used") and not summary.get("ocr_used"):
                self.status.setText(
                    f"No wire numbers found — {scanned} page(s) are scanned images "
                    f"with no text. Pick AI assist (or OCR) for scanned pages and "
                    f"try again.")
            elif summary.get("ai_used"):
                self.status.setText(
                    "No wire numbers found. The AI didn't return any labels — the "
                    "scan may be low-resolution; also verify the API key/quota.")
            else:
                self.status.setText("No wire numbers found.")
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
        """Cancel a running extraction and wait for it to unwind (cancellation
        is checked between pages, so this returns within ~one page)."""
        w = self._worker
        if w is None:
            return
        try:
            w.progress.disconnect()
            w.done.disconnect()
            w.failed.disconnect()
        except Exception:
            pass
        if w.isRunning():
            w.cancel()
            w.wait(30000)
        self._worker = None

    def shutdown(self):
        """Called on app close so no extraction thread outlives the window."""
        self._stop_worker()

    # -- table ---------------------------------------------------------------

    def _populate(self):
        self.table.setSortingEnabled(False)
        self.table.itemChanged.disconnect(self._on_item_changed)
        self.table.setRowCount(0)
        for w in self.wires:
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if w.included else Qt.Unchecked)
            chk.setData(Qt.UserRole, w)
            self.table.setItem(r, 0, chk)
            vals = [w.label, _i(w.sheet), _i(w.rung), _i(w.wire_index), w.wire_type,
                    str(w.page + 1), str(w.count), w.source,
                    "mismatch" if FLAG_SHEET_MISMATCH in w.flags else ""]
            for c, v in enumerate(vals, start=1):
                key = _num_key(v) if c in _NUMERIC_COLS else None
                it = _SortItem(v, key)
                if c == 5:  # type col
                    from PySide6.QtGui import QColor
                    it.setForeground(QColor(_TYPE_COLORS.get(w.wire_type, "#000")))
                self.table.setItem(r, c, it)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setSortingEnabled(True)
        self._apply_filter()

    def _apply_filter(self):
        needle = self.search.text().lower().strip()
        allowed = set()
        if self.show_conforming.isChecked():
            allowed.add(TYPE_CONFORMING)
        if self.show_fixed.isChecked():
            allowed.add(TYPE_FIXED)
        if self.show_jumpers.isChecked():
            allowed.add(TYPE_JUMPER)
        for r in range(self.table.rowCount()):
            w = self.table.item(r, 0).data(Qt.UserRole)
            show = w.wire_type in allowed and (not needle or needle in w.label.lower())
            self.table.setRowHidden(r, not show)

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        w = item.data(Qt.UserRole)
        if w is None:
            return
        checked = item.checkState() == Qt.Checked
        w.included = checked
        self._mark_dirty()
        # group toggle: if this row is part of a multi-row selection
        # (shift/ctrl+click), apply the same state to every selected row
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
                wn = cell.data(Qt.UserRole)
                if wn is not None:
                    wn.included = checked
        finally:
            self.table.blockSignals(False)

    def _set_all_visible(self, checked):
        rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        self._apply_check_to_rows(rows, checked)

    def _on_double(self, row, _col):
        w = self.table.item(row, 0).data(Qt.UserRole)
        if w is not None:
            self.activated.emit(w)

    # -- export --------------------------------------------------------------

    def _build_options(self) -> WireExportOptions:
        sort = {0: SORT_NUMERICAL, 1: SORT_IN_ORDER, 2: SORT_BY_SHEET}[self.sort.currentIndex()]
        return WireExportOptions(
            fmt=self.fmt.currentText(),
            labels_per_wire=self.labels_per.value(),
            sort=sort,
            include_fixed=self.show_fixed.isChecked(),
            include_jumpers=self.show_jumpers.isChecked(),
            dedupe=self.dedupe.isChecked(),
            only_included=True,
            labels_only=self.labels_only.isChecked() or None,
        )

    def export(self):
        if not self.wires:
            QMessageBox.information(self, "Nothing to export", "Extract wire numbers first.")
            return
        opts = self._build_options()
        single = self.mode.currentIndex() == 0
        try:
            if single:
                ext = "xlsx" if opts.fmt == "xlsx" else "csv"
                path, _ = QFileDialog.getSaveFileName(
                    self, "Export wire numbers", f"wires.{ext}",
                    f"Spreadsheet (*.{ext})")
                if not path:
                    return
                export_single_file(self.wires, path, opts)
                QMessageBox.information(self, "Exported", f"Wrote {path}")
            else:
                out_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
                if not out_dir:
                    return
                paths = export_per_sheet(self.wires, out_dir, opts)
                QMessageBox.information(self, "Exported",
                                        f"Wrote {len(paths)} file(s) to {out_dir}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))


def _i(v):
    return "" if v is None else str(v)
