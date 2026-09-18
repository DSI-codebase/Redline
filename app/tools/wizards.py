"""Viewer-driven wizards: the sheet-number region wizard and the crop/extract
wizard.  Both reuse the main viewer for region drawing and the Pages+Bookmarks
dock for navigation.
"""

from __future__ import annotations

import os

import fitz
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSpinBox, QButtonGroup, QMessageBox, QFileDialog,
    QCheckBox,
)

from . import pdf_ops as ops
from .runner import run_with_progress

_MODES = [("First number", ops.SHEET_FIRST_NUMBER),
          ("Smaller of two numbers", ops.SHEET_SMALLER_OF_TWO),
          ("Exact text", ops.SHEET_EXACT)]


def _rect_tuple(qrect):
    return (qrect.x(), qrect.y(), qrect.x() + qrect.width(), qrect.y() + qrect.height())


class _PreviewDialog(QDialog):
    """Shows the raw text read from the box and the parsed sheet number, with a
    chooser for the parse rule.  Result: Accepted (use), or .redraw set."""

    def __init__(self, parent, raw_text, mode, page):
        super().__init__(parent)
        self.setWindowTitle(f"Sheet number — page {page + 1}")
        self.setMinimumWidth(420)
        self.redraw = False
        self.mode = mode
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Text read from the box:"))
        self.raw = QPlainTextEdit(raw_text or "(nothing found)")
        self.raw.setReadOnly(True)
        self.raw.setMaximumHeight(80)
        lay.addWidget(self.raw)
        row = QHBoxLayout()
        row.addWidget(QLabel("Rule:"))
        self.combo = QComboBox()
        for label, val in _MODES:
            self.combo.addItem(label, val)
        idx = max(0, [v for _, v in _MODES].index(mode) if mode in [v for _, v in _MODES] else 0)
        self.combo.setCurrentIndex(idx)
        self.combo.currentIndexChanged.connect(self._update)
        row.addWidget(self.combo, 1)
        lay.addLayout(row)
        self.result = QLabel()
        f = self.result.font(); f.setBold(True); self.result.setFont(f)
        lay.addWidget(self.result)
        self._raw_text = raw_text or ""
        self._update()
        btns = QHBoxLayout()
        ok = QPushButton("Use this"); ok.setDefault(True); ok.clicked.connect(self.accept)
        rd = QPushButton("Redraw box"); rd.clicked.connect(self._on_redraw)
        cx = QPushButton("Cancel"); cx.clicked.connect(self.reject)
        btns.addWidget(ok); btns.addWidget(rd); btns.addStretch(1); btns.addWidget(cx)
        lay.addLayout(btns)

    def _update(self):
        self.mode = self.combo.currentData()
        val = ops.sheet_from_text(self._raw_text, self.mode)
        self.result.setText(f"Sheet number → {val!r}" if val else "Sheet number → (empty)")

    def _on_redraw(self):
        self.redraw = True
        self.reject()


class _RangeDialog(QDialog):
    """Ask which pages a newly drawn box applies to.  exec_choice() -> (start,end)
    0-based inclusive, or None on cancel."""

    def __init__(self, parent, page, last):
        super().__init__(parent)
        self.setWindowTitle("Apply this box to…")
        self.page, self.last = page, last
        lay = QVBoxLayout(self)
        self.grp = QButtonGroup(self)
        self.r_one = QRadioButton(f"This page only (page {page + 1})")
        self.r_end = QRadioButton(f"This page to the end (pages {page + 1}–{last + 1})")
        self.r_to = QRadioButton("This page through page:")
        self.r_end.setChecked(True)
        for r in (self.r_one, self.r_end, self.r_to):
            self.grp.addButton(r)
        self.to_spin = QSpinBox(); self.to_spin.setRange(page + 1, last + 1); self.to_spin.setValue(last + 1)
        lay.addWidget(self.r_one)
        lay.addWidget(self.r_end)
        row = QHBoxLayout(); row.addWidget(self.r_to); row.addWidget(self.to_spin); row.addStretch(1)
        lay.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton("OK"); ok.setDefault(True); ok.clicked.connect(self.accept)
        cx = QPushButton("Cancel"); cx.clicked.connect(self.reject)
        btns.addStretch(1); btns.addWidget(ok); btns.addWidget(cx)
        lay.addLayout(btns)

    def exec_choice(self):
        if self.exec() != QDialog.Accepted:
            return None
        if self.r_one.isChecked():
            return (self.page, self.page)
        if self.r_to.isChecked():
            return (self.page, self.to_spin.value() - 1)
        return (self.page, self.last)


class SheetNumberWizard(QObject):
    """Guides the user to box the sheet-number cell(s) and splits the set,
    naming each file by its sheet number."""

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.view = window.view
        self.regions = []
        self.mode = ops.SHEET_FIRST_NUMBER
        self._kind = "first"
        self._task = None

    # -- flow ----------------------------------------------------------------

    def start(self):
        if getattr(self.win, "document", None) is None:
            QMessageBox.information(self.win, "No PDF", "Open a PDF set first.")
            return
        self.regions = []
        QMessageBox.information(
            self.win, "Sheet-number split",
            "We'll mark where the sheet number appears.\n\n"
            "Click OK, then drag a box around the sheet number on page 1.\n"
            "Use the Pages/Bookmarks panel and scroll to navigate when you define "
            "boxes for other title-block styles.")
        self.view.go_to_page(0)
        self._begin_pick("first")

    def _begin_pick(self, kind):
        self._kind = kind
        try:
            self.view.regionPicked.disconnect(self._on_region)
        except (RuntimeError, TypeError):
            pass
        self.view.regionPicked.connect(self._on_region)
        self.view.start_region_pick()

    def _extract_opts(self):
        """The read options shared by the preview and the actual split, so they
        always agree. OCR is enabled whenever it's *available* (Tesseract
        installed) — not only when a Settings flag is on — so scanned sets read
        their sheet numbers out of the box; searchable pages never invoke it
        (it only runs when the text layer is empty)."""
        cfg = self.win.config
        from ..extraction import ocr as _ocr
        ocr = bool(getattr(cfg, "ocr_enabled", False)) or _ocr.available()
        ai = bool(getattr(cfg, "ai_enabled", False))
        ai_key = getattr(cfg, "ai_api_key", "")
        ai_model = getattr(cfg, "ai_model", "")
        return ocr, ai, ai_key, ai_model

    def _read(self, page, rect):
        ocr, ai, ai_key, ai_model = self._extract_opts()
        try:
            return ops.read_region_text(
                self.win.document.fitz_doc[page], rect,
                ocr=ocr, ai=ai, ai_key=ai_key, ai_model=ai_model)
        except Exception:
            return ""

    def _on_region(self, page, qrect):
        try:
            self.view.regionPicked.disconnect(self._on_region)
        except (RuntimeError, TypeError):
            pass
        rect = _rect_tuple(qrect)
        raw = self._read(page, rect)
        dlg = _PreviewDialog(self.win, raw, self.mode, page)
        if dlg.exec() != QDialog.Accepted:
            if dlg.redraw:
                self._begin_pick(self._kind)
            return
        self.mode = dlg.mode
        last = self.win.document.page_count - 1
        if self._kind == "first":
            self.regions = [ops.SheetRegion(0, last, rect)]
            self._scope_dialog()
        else:
            choice = _RangeDialog(self.win, page, last).exec_choice()
            if choice is not None:
                self.regions.append(ops.SheetRegion(choice[0], choice[1], rect))
            self._add_more_or_finish()

    def _scope_dialog(self):
        box = QMessageBox(self.win)
        box.setWindowTitle("Title-block layout")
        box.setText("Is the sheet number in this same spot on every page?")
        same = box.addButton("Same box for all pages", QMessageBox.AcceptRole)
        more = box.addButton("Some pages differ — add boxes…", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is same:
            self._finish()
        elif clicked is more:
            self._prompt_navigate_then_pick()

    def _prompt_navigate_then_pick(self):
        QMessageBox.information(
            self.win, "Add a box",
            "Navigate to a page that uses a different title block (Pages/Bookmarks "
            "panel or scroll), then drag a box around its sheet number.")
        self._begin_pick("add")

    def _add_more_or_finish(self):
        box = QMessageBox(self.win)
        box.setWindowTitle("More boxes?")
        box.setText("Add another title-block box, or finish and split?")
        add = box.addButton("Add another box", QMessageBox.ActionRole)
        fin = box.addButton("Finish & split", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is add:
            self._prompt_navigate_then_pick()
        elif clicked is fin:
            self._finish()

    def _finish(self):
        out_dir = QFileDialog.getExistingDirectory(self.win, "Choose output folder")
        if not out_dir:
            return
        src = self.win.document.path
        regions = list(self.regions)
        mode = self.mode
        ocr, ai, ai_key, ai_model = self._extract_opts()

        def fn(progress, cancel):
            return ops.split_pdf(src, out_dir, naming="sheet", regions=regions,
                                 mode=mode, ocr=ocr, ai=ai, ai_key=ai_key,
                                 ai_model=ai_model, progress=progress, cancel=cancel)

        def done(paths):
            # report any pages that fell back to page-numbering
            fell_back = sum(1 for p in paths if "-page" in os.path.basename(p))
            msg = f"Split into {len(paths)} file(s) in:\n{out_dir}"
            if fell_back:
                msg += (f"\n\n{fell_back} page(s) had no readable sheet number and "
                        f"were named by page number — re-run and adjust the box if needed.")
            QMessageBox.information(self.win, "Done", msg)

        self._task = run_with_progress(
            self.win, "Reading sheet numbers and splitting…", fn, done,
            on_error=lambda m: QMessageBox.warning(self.win, "Split failed", m))


class CropWizard(QObject):
    """Box one or more regions across pages, then export PNGs and/or build a
    TAG/DESCRIPTION table with Claude."""

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.view = window.view
        self.regions_by_page = {}
        self._task = None

    def start(self):
        if getattr(self.win, "document", None) is None:
            QMessageBox.information(self.win, "No PDF", "Open a PDF first.")
            return
        self.regions_by_page = {}
        QMessageBox.information(
            self.win, "Crop / extract",
            "Drag a box around anything you want to pull out of the drawing — a "
            "table/BOM, a block of notes or instructions, a device label. Add as "
            "many regions across pages as you like (navigate with the "
            "Pages/Bookmarks panel or scroll). At the end you choose the output: "
            "tables → Excel, text → Word, or everything → Markdown.")
        self._begin_pick()

    def _begin_pick(self):
        try:
            self.view.regionPicked.disconnect(self._on_region)
        except (RuntimeError, TypeError):
            pass
        self.view.regionPicked.connect(self._on_region)
        self.view.start_region_pick()

    def _on_region(self, page, qrect):
        try:
            self.view.regionPicked.disconnect(self._on_region)
        except (RuntimeError, TypeError):
            pass
        self.regions_by_page.setdefault(page, []).append(_rect_tuple(qrect))
        n = sum(len(v) for v in self.regions_by_page.values())
        box = QMessageBox(self.win)
        box.setWindowTitle("Region added")
        box.setText(f"{n} region(s) captured. Add another, or finish?")
        add = box.addButton("Add another", QMessageBox.ActionRole)
        fin = box.addButton("Finish…", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is add:
            self._begin_pick()
        elif clicked is fin:
            self._finish()

    def _finish(self):
        if not self.regions_by_page:
            return
        cfg = self.win.config
        from ..extraction import claude_api
        ai_ok = bool(getattr(cfg, "ai_enabled", False)) and \
            claude_api.available(getattr(cfg, "ai_api_key", ""))
        try:
            from ..extraction import ocr as _ocr
            ocr_ok = _ocr.available()
        except Exception:
            ocr_ok = False

        dlg = QDialog(self.win)
        dlg.setWindowTitle("Export captured regions")
        lay = QVBoxLayout(dlg)
        if ai_ok:
            note = ("Claude reads each region and splits it into tables (→ Excel) "
                    "and prose/notes (→ Word). Markdown puts everything in one file.")
        elif ocr_ok:
            note = ("No AI key — regions are OCR-read; tables are reconstructed "
                    "best-effort from text alignment (less reliable than Claude). "
                    "Enable Claude in Settings for the most accurate tables.")
        else:
            note = ("No AI or OCR available — only the cropped PNGs can be saved. "
                    "Enable Claude or Tesseract in Settings to capture text.")
        nlbl = QLabel(note); nlbl.setWordWrap(True); lay.addWidget(nlbl)

        cb_excel = QCheckBox("Tables → Excel (.xlsx)")
        cb_word = QCheckBox("Text → Word (.docx)")
        cb_md = QCheckBox("Everything → Markdown (.md)")
        cb_png = QCheckBox("Also save cropped PNGs")
        cb_excel.setChecked(ai_ok or ocr_ok)
        cb_word.setChecked(ai_ok or ocr_ok)
        cb_png.setChecked(not (ai_ok or ocr_ok))
        for cb in (cb_excel, cb_word, cb_md, cb_png):
            lay.addWidget(cb)

        btns = QHBoxLayout()
        ok = QPushButton("Export"); ok.setDefault(True); ok.clicked.connect(dlg.accept)
        cx = QPushButton("Cancel"); cx.clicked.connect(dlg.reject)
        btns.addStretch(1); btns.addWidget(ok); btns.addWidget(cx)
        lay.addLayout(btns)
        if dlg.exec() != QDialog.Accepted:
            return

        formats = set()
        if cb_excel.isChecked():
            formats.add("excel")
        if cb_word.isChecked():
            formats.add("word")
        if cb_md.isChecked():
            formats.add("markdown")
        save_png = cb_png.isChecked()
        if not formats and not save_png:
            QMessageBox.information(self.win, "Nothing selected",
                                    "Choose at least one output.")
            return

        out_dir = QFileDialog.getExistingDirectory(self.win, "Choose output folder")
        if not out_dir:
            return
        src = self.win.document.path
        regions = dict(self.regions_by_page)
        ai_key = getattr(cfg, "ai_api_key", "")
        ai_model = getattr(cfg, "ai_model", "claude-opus-4-8")
        base = os.path.splitext(os.path.basename(src))[0]

        def fn(progress, cancel):
            from . import region_export
            results = []
            if formats:
                items = [(pg, i, r) for pg in sorted(regions)
                         for i, r in enumerate(regions[pg])]
                total = len(items)
                doc = fitz.open(src)
                try:
                    for done_n, (pg, i, rect) in enumerate(items, 1):
                        if cancel():
                            break
                        pix = doc[pg].get_pixmap(matrix=fitz.Matrix(3, 3),
                                                 clip=fitz.Rect(*rect), alpha=False)
                        results.append(_classify_region(
                            pix, pg, i, ai_ok, ocr_ok, ai_key, ai_model))
                        progress(done_n, total)
                finally:
                    doc.close()
            written = region_export.export_regions(results, out_dir, base, formats) \
                if formats else []
            pngs = []
            if save_png and not cancel():
                pngs = ops.crop_regions_to_png(src, out_dir, regions, cancel=cancel)
            return (written, pngs, results)

        def done(result):
            written, pngs, results = result
            n_tab = sum(1 for r in results if r.get("type") == "table")
            n_txt = len(results) - n_tab
            lines = [f"Captured {len(results)} region(s) "
                     f"({n_tab} table, {n_txt} text)."]
            for p in written:
                lines.append(f"• {os.path.basename(p)}")
            if pngs:
                lines.append(f"• {len(pngs)} PNG(s)")
            lines.append(f"\nIn: {out_dir}")
            QMessageBox.information(self.win, "Done", "\n".join(lines))

        self._task = run_with_progress(
            self.win, "Reading captured regions…", fn, done,
            on_error=lambda m: QMessageBox.warning(self.win, "Capture failed", m))


def _classify_region(pix, page, index, ai_ok, ocr_ok, ai_key, ai_model) -> dict:
    """Turn one rendered region into a result dict for region_export.

    Uses Claude to classify table vs prose when available; otherwise OCR's the
    region as plain text (type='text').  Never raises.
    """
    res = {}
    if ai_ok:
        try:
            from ..extraction import claude_api
            res = claude_api.extract_region_content(
                pix, model=ai_model, api_key=ai_key) or {}
        except Exception:
            res = {}
    if not res and ocr_ok:
        # best-effort: reconstruct a table from OCR geometry, else prose text
        try:
            from ..extraction import ocr as _ocr
            res = _ocr.ocr_structured(pix) or {}
        except Exception:
            res = {}
    if not res:
        res = {"type": "text", "title": "", "rows": [], "text": ""}
    return {
        "page": page,
        "index": index,
        "type": "table" if res.get("type") == "table" else "text",
        "title": res.get("title", ""),
        "rows": res.get("rows", []),
        "text": res.get("text", ""),
    }


def _write_tag_table(rows, path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Tags"
    ws.append(["TAG", "DESCRIPTION"])
    for r in rows:
        ws.append([r.get("tag", ""), r.get("description", "")])
    wb.save(path)
