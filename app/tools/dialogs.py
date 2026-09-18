"""Modern PySide6 dialogs for the merged file-to-file PDF tools.

Each dialog collects inputs, runs the matching :mod:`app.tools.pdf_ops` function
on a :class:`app.tools.runner.BackgroundTask` (progress bar + Cancel), and never
blocks the UI. Region-based tools (sheet-number split, crop) are handled by the
wizards instead.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QFileDialog, QMessageBox, QWidget, QComboBox,
    QSpinBox, QListWidget, QListWidgetItem, QAbstractItemView,
)

from . import pdf_ops as ops
from .runner import BackgroundTask


# --- base -------------------------------------------------------------------


class _ToolDialog(QDialog):
    def __init__(self, title, parent=None, default_pdf=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(580)
        self.default_pdf = default_pdf or ""
        self._task = None
        self._outer = QVBoxLayout(self)
        self.form = QFormLayout()
        self._outer.addLayout(self.form)
        self.build()                                  # subclass adds rows
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.btn_run = QPushButton("Run")
        self.btn_run.setDefault(True)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setVisible(False)
        self.btn_close = QPushButton("Close")
        self.btn_run.clicked.connect(self._on_run)
        self.btn_cancel.clicked.connect(lambda: self._task and self._task.cancel())
        self.btn_close.clicked.connect(self.reject)
        self._outer.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(self.progress, 1)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_close)
        self._outer.addLayout(row)

    # subclass hooks
    def build(self):
        raise NotImplementedError

    def build_task(self):
        """Return ``fn(progress, cancel)`` or raise ValueError for bad input."""
        raise NotImplementedError

    def success_message(self, result):
        return "Done."

    def output_location(self, result):
        """Folder to offer to open on success (or None)."""
        return None

    # input helpers
    def _row(self, label, line_edit, button):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(line_edit, 1)
        h.addWidget(button)
        self.form.addRow(label, w)

    def add_open_pdf(self, label, default=""):
        le = QLineEdit(default)
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._pick_open(le))
        self._row(label, le, btn)
        return le

    def add_save_pdf(self, label, default="", ext="pdf"):
        le = QLineEdit(default)
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._pick_save(le, ext))
        self._row(label, le, btn)
        return le

    def add_dir(self, label, default=""):
        le = QLineEdit(default)
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._pick_dir(le))
        self._row(label, le, btn)
        return le

    def _pick_open(self, le):
        p, _ = QFileDialog.getOpenFileName(self, "Select PDF", le.text() or "", "PDF (*.pdf)")
        if p:
            le.setText(p)

    def _pick_save(self, le, ext):
        p, _ = QFileDialog.getSaveFileName(self, "Save as", le.text() or "",
                                           f"{ext.upper()} (*.{ext})")
        if p:
            if not p.lower().endswith("." + ext):
                p += "." + ext
            le.setText(p)

    def _pick_dir(self, le):
        p = QFileDialog.getExistingDirectory(self, "Select folder", le.text() or "")
        if p:
            le.setText(p)

    @staticmethod
    def _default_out(src, suffix, ext="pdf"):
        if not src:
            return ""
        base, _ = os.path.splitext(src)
        return f"{base}{suffix}.{ext}"

    # run lifecycle
    def _on_run(self):
        try:
            fn = self.build_task()
        except ValueError as e:
            QMessageBox.warning(self, "Check inputs", str(e))
            return
        if fn is None:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.status.setText("Working…")
        self._task = BackgroundTask(fn, self)
        self._task.progress.connect(self._on_progress)
        self._task.done.connect(self._on_done)
        self._task.failed.connect(self._on_failed)
        self._task.start()

    def _on_progress(self, d, t):
        self.progress.setRange(0, max(1, t))
        self.progress.setValue(d)

    def _on_done(self, result):
        self._finish()
        self.status.setText("✓ " + self.success_message(result))
        loc = self.output_location(result)
        if loc and os.path.isdir(loc):
            if QMessageBox.question(self, "Done", self.success_message(result) +
                                    "\n\nOpen the output folder?") == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(loc))

    def _on_failed(self, msg):
        self._finish()
        if msg == "__cancelled__":
            self.status.setText("Cancelled.")
        else:
            self.status.setText("Failed.")
            QMessageBox.warning(self, "Failed", msg)

    def _finish(self):
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_run.setEnabled(True)
        if self._task is not None:
            self._task.wait(2000)
            self._task = None


# --- concrete dialogs -------------------------------------------------------


class SplitPagesDialog(_ToolDialog):
    def build(self):
        self.src = self.add_open_pdf("PDF to split:", self.default_pdf)
        self.out = self.add_dir("Output folder:")

    def build_task(self):
        src, out = self.src.text().strip(), self.out.text().strip()
        if not src or not out:
            raise ValueError("Choose a PDF and an output folder.")
        return lambda p, c: ops.split_pdf(src, out, naming="page", progress=p, cancel=c)

    def success_message(self, result):
        return f"Split into {len(result)} page file(s)."

    def output_location(self, result):
        return self.out.text().strip()


class CombineDialog(_ToolDialog):
    def build(self):
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.form.addRow(QLabel("Files to combine (drag to reorder):"))
        self.form.addRow(self.list)
        btns = QHBoxLayout()
        for text, fn in [("Add files…", self._add_files), ("Add folder…", self._add_folder),
                         ("Remove", self._remove), ("↑", lambda: self._move(-1)),
                         ("↓", lambda: self._move(1))]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        bw = QWidget(); bw.setLayout(btns)
        self.form.addRow(bw)
        self.out = self.add_save_pdf("Output PDF:")

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF (*.pdf)")
        for f in files:
            self.list.addItem(f)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder (sorted by number)")
        if not d:
            return
        files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".pdf")]
        files.sort(key=ops._numeric_key)
        for f in files:
            self.list.addItem(f)

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _move(self, delta):
        row = self.list.currentRow()
        if row < 0:
            return
        nr = row + delta
        if 0 <= nr < self.list.count():
            it = self.list.takeItem(row)
            self.list.insertItem(nr, it)
            self.list.setCurrentRow(nr)

    def build_task(self):
        files = [self.list.item(i).text() for i in range(self.list.count())]
        out = self.out.text().strip()
        if len(files) < 2 or not out:
            raise ValueError("Add at least two files and an output path.")
        return lambda p, c: ops.combine_pdfs(files, out, progress=p, cancel=c)

    def success_message(self, result):
        return f"Combined into {os.path.basename(result)}."

    def output_location(self, result):
        return os.path.dirname(result)


class InsertDialog(_ToolDialog):
    def build(self):
        self.target = self.add_open_pdf("Target PDF:", self.default_pdf)
        self.insert = self.add_open_pdf("PDF to insert:")
        self.index = QSpinBox(); self.index.setRange(1, 99999); self.index.setValue(1)
        self.form.addRow("Insert before page (1-based):", self.index)
        self.out = self.add_save_pdf("Output PDF:")

    def build_task(self):
        t, ins, out = self.target.text().strip(), self.insert.text().strip(), self.out.text().strip()
        if not (t and ins and out):
            raise ValueError("Choose target, insert, and output PDFs.")
        idx = self.index.value() - 1
        return lambda p, c: ops.insert_pdf(t, ins, out, idx)

    def success_message(self, result):
        return f"Saved {os.path.basename(result)}."

    def output_location(self, result):
        return os.path.dirname(result)


class SwapDialog(_ToolDialog):
    def build(self):
        self.src = self.add_open_pdf("Original PDF:", self.default_pdf)
        self.newpage = self.add_open_pdf("Replacement page (1-page PDF):")
        self.index = QSpinBox(); self.index.setRange(1, 99999); self.index.setValue(1)
        self.form.addRow("Replace page # (1-based):", self.index)
        self.out = self.add_save_pdf("Output PDF:")

    def build_task(self):
        src, new, out = self.src.text().strip(), self.newpage.text().strip(), self.out.text().strip()
        if not (src and new and out):
            raise ValueError("Choose original, replacement, and output PDFs.")
        idx = self.index.value() - 1
        return lambda p, c: ops.swap_page(src, new, out, idx)

    def success_message(self, result):
        return f"Saved {os.path.basename(result)}."

    def output_location(self, result):
        return os.path.dirname(result)


class DeleteDialog(_ToolDialog):
    def build(self):
        self.src = self.add_open_pdf("PDF:", self.default_pdf)
        self.spec = QLineEdit()
        self.spec.setPlaceholderText("e.g. 1,3,5-7")
        self.form.addRow("Pages to remove (1-based):", self.spec)
        self.out = self.add_save_pdf("Output PDF:")

    def build_task(self):
        src, out, spec = self.src.text().strip(), self.out.text().strip(), self.spec.text().strip()
        if not (src and out and spec):
            raise ValueError("Choose a PDF, an output path, and pages to remove.")
        return lambda p, c: ops.delete_pages(src, out, spec)

    def success_message(self, result):
        return f"Saved {os.path.basename(result)}."

    def output_location(self, result):
        return os.path.dirname(result)


class RotateDialog(_ToolDialog):
    _ANGLES = {"Clockwise 90°": 90, "180°": 180, "Counter-clockwise 90°": 270}

    def build(self):
        self.src = self.add_open_pdf("PDF:", self.default_pdf)
        self.angle = QComboBox(); self.angle.addItems(list(self._ANGLES))
        self.form.addRow("Rotate by:", self.angle)
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("blank = all pages, or e.g. 2,4-6")
        self.form.addRow("Pages (1-based):", self.pages)
        self.out = self.add_save_pdf("Output PDF:")

    def build_task(self):
        src, out = self.src.text().strip(), self.out.text().strip()
        if not (src and out):
            raise ValueError("Choose a PDF and an output path.")
        angle = self._ANGLES[self.angle.currentText()]
        spec = self.pages.text().strip()
        pages = ops.parse_page_ranges(spec) if spec else None
        return lambda p, c: ops.rotate_pdf(src, out, angle, pages=pages)

    def success_message(self, result):
        return f"Saved {os.path.basename(result)}."

    def output_location(self, result):
        return os.path.dirname(result)


class ConvertDialog(_ToolDialog):
    def build(self):
        self.src = self.add_open_pdf("PDF:", self.default_pdf)
        self.out = self.add_save_pdf("Output Word file:", ext="docx")

    def build_task(self):
        src, out = self.src.text().strip(), self.out.text().strip()
        if not (src and out):
            raise ValueError("Choose a PDF and an output .docx path.")
        try:
            import pdf2docx  # noqa: F401
        except Exception:
            raise ValueError("PDF→Word needs the 'pdf2docx' package (pip install pdf2docx).")
        return lambda p, c: ops.pdf_to_docx(src, out)

    def success_message(self, result):
        return f"Saved {os.path.basename(result)}."

    def output_location(self, result):
        return os.path.dirname(result)
