"""The "PDF Tools" tab — an iLovePDF-style visual workspace.

Layout: a file bar across the top (drag a PDF in, or open one), an operation
rail on the left, a live **thumbnail grid** of every page in the centre, and a
per-operation options panel on the right.  Page operations (extract, split into
ranges, delete, rotate) are driven by *clicking page thumbnails* — the visual
selection stays two-way synced with a page-spec text box.  Multi-file and
region operations (combine, insert, swap, sheet-number split, crop, PDF→Word)
launch their existing dialogs / wizards from the rail.

The same launch methods back the Tools menu in the main window.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
    QCheckBox, QSpinBox, QComboBox, QListWidget, QListWidgetItem, QStackedWidget,
    QButtonGroup, QFileDialog, QMessageBox, QProgressBar, QSizePolicy,
)

from .. import theme
from ..tools import dialogs as dlg
from ..tools import pdf_ops as ops
from ..tools.runner import BackgroundTask
from ..tools.wizards import SheetNumberWizard, CropWizard
from .thumb_grid import ThumbnailGrid


class ToolsPanel(QWidget):
    # operation rail: (key, label, group)  — group "page" uses the grid
    OPS = [
        ("extract", "Extract pages", "page"),
        ("split", "Split into ranges", "page"),
        ("delete", "Delete pages", "page"),
        ("rotate", "Rotate", "page"),
        ("combine", "Combine PDFs…", "file"),
        ("insert", "Insert PDF…", "file"),
        ("swap", "Swap a page…", "file"),
        ("sheet", "Sheet-number split…", "file"),
        ("crop", "Crop / extract…", "file"),
        ("convert", "PDF → Word…", "file"),
    ]

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.current_pdf = ""
        self._wizard = None
        self._task = None
        self._syncing = False
        self._spec_edits = {}           # op key -> QLineEdit (synced to grid)
        self._rail_btns = {}            # op key -> QPushButton
        self._opt_index = {}            # op key -> stacked-widget page index
        self.setObjectName("ToolsWorkspace")
        self.setAcceptDrops(True)
        self._build_ui()
        self.setStyleSheet(theme.workspace_qss() + theme.grid_qss())
        self._select_op("extract")
        self._update_enabled()

    # -- layout --------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_file_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail())
        self.grid = ThumbnailGrid()
        self.grid.selectionPagesChanged.connect(self._on_grid_selection)
        body.addWidget(self.grid, 1)
        body.addWidget(self._build_options())
        outer.addLayout(body, 1)

    def _build_file_bar(self):
        bar = QFrame(); bar.setObjectName("FileBar")
        bar.setFixedHeight(58)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 16, 8)
        self.file_name = QLabel("No PDF loaded"); self.file_name.setObjectName("FileName")
        self.file_hint = QLabel("Drag a PDF here, or"); self.file_hint.setObjectName("FileHint")
        col = QVBoxLayout(); col.setSpacing(0)
        col.addWidget(self.file_name); col.addWidget(self.file_hint)
        h.addLayout(col)
        h.addStretch(1)
        self.btn_open = QPushButton("Open PDF…")
        self.btn_open.clicked.connect(self._open_pdf_dialog)
        h.addWidget(self.btn_open)
        return bar

    def _build_rail(self):
        rail = QFrame(); rail.setObjectName("Rail")
        rail.setFixedWidth(196)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(8, 12, 8, 12)
        lay.setSpacing(2)
        self._rail_group = QButtonGroup(self)
        self._rail_group.setExclusive(True)
        last_group = None
        for key, label, group in self.OPS:
            if last_group is not None and group != last_group:
                line = QFrame(); line.setFrameShape(QFrame.HLine)
                line.setStyleSheet(f"color: {theme.LINE}; margin: 6px 4px;")
                lay.addWidget(line)
            last_group = group
            btn = QPushButton(label); btn.setObjectName("RailBtn"); btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self._select_op(k))
            self._rail_group.addButton(btn)
            self._rail_btns[key] = btn
            lay.addWidget(btn)
        lay.addStretch(1)
        return rail

    def _build_options(self):
        panel = QFrame(); panel.setObjectName("Options")
        panel.setFixedWidth(300)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self.opt_title = QLabel(); self.opt_title.setObjectName("OptTitle")
        self.opt_desc = QLabel(); self.opt_desc.setObjectName("OptDesc")
        self.opt_desc.setWordWrap(True)
        lay.addWidget(self.opt_title)
        lay.addWidget(self.opt_desc)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        for key, _label, _group in self.OPS:
            page = self._make_options_page(key)
            self._opt_index[key] = self.stack.addWidget(page)

        # shared status + progress at the bottom
        self.status = QLabel(""); self.status.setWordWrap(True)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        lay.addWidget(self.status)
        lay.addWidget(self.progress)
        return panel

    # -- options pages -------------------------------------------------------

    def _make_options_page(self, key):
        builder = {
            "extract": self._page_extract,
            "split": self._page_split,
            "delete": self._page_delete,
            "rotate": self._page_rotate,
            "combine": lambda: self._page_launch(
                "Combine PDFs", self.open_combine),
            "insert": lambda: self._page_launch(
                "Insert one PDF into another", self.open_insert),
            "swap": lambda: self._page_launch(
                "Replace a single page with a one-page PDF", self.open_swap),
            "sheet": lambda: self._page_launch(
                "Guided wizard: box the title-block sheet number and split, "
                "naming each file by its sheet. Uses the document open in the "
                "Viewer tab.", self.start_sheet_wizard, needs_viewer=True),
            "crop": lambda: self._page_launch(
                "Box regions across pages → PNGs, and optionally a TAG/"
                "DESCRIPTION table via Claude. Uses the document open in the "
                "Viewer tab.", self.start_crop_wizard, needs_viewer=True),
            "convert": lambda: self._page_launch(
                "Convert this PDF to an editable .docx", self.open_convert),
        }[key]
        return builder()

    def _spec_row(self, key, placeholder="e.g. 1,3,5-7"):
        """A 'pages' text box that stays synced with the thumbnail selection."""
        edit = QLineEdit(); edit.setPlaceholderText(placeholder)
        edit.textEdited.connect(lambda t, k=key: self._on_spec_edited(k, t))
        self._spec_edits[key] = edit
        return edit

    def _select_buttons(self):
        row = QHBoxLayout()
        b_all = QPushButton("Select all"); b_all.clicked.connect(self.grid.select_all_pages)
        b_clr = QPushButton("Clear"); b_clr.clicked.connect(self.grid.clear_page_selection)
        row.addWidget(b_all); row.addWidget(b_clr); row.addStretch(1)
        w = QWidget(); w.setLayout(row)
        return w

    def _page_extract(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Pages to extract:"))
        lay.addWidget(self._spec_row("extract"))
        lay.addWidget(self._select_buttons())
        self.extract_merge = QCheckBox("Merge extracted pages into one PDF")
        self.extract_merge.setChecked(True)
        lay.addWidget(self.extract_merge)
        lay.addStretch(1)
        self.btn_extract = self._action_button("Extract pages", self._run_extract)
        lay.addWidget(self.btn_extract)
        return w

    def _page_split(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("From"))
        self.split_from = QSpinBox(); self.split_from.setRange(1, 99999)
        self.split_to = QSpinBox(); self.split_to.setRange(1, 99999)
        row.addWidget(self.split_from); row.addWidget(QLabel("to")); row.addWidget(self.split_to)
        rw = QWidget(); rw.setLayout(row); lay.addWidget(rw)
        add_row = QHBoxLayout()
        b_add = QPushButton("Add range"); b_add.clicked.connect(self._add_range)
        b_sel = QPushButton("From selection"); b_sel.clicked.connect(self._add_range_from_selection)
        add_row.addWidget(b_add); add_row.addWidget(b_sel)
        aw = QWidget(); aw.setLayout(add_row); lay.addWidget(aw)
        self.range_list = QListWidget(); self.range_list.setMaximumHeight(120)
        lay.addWidget(self.range_list)
        b_del = QPushButton("Remove selected range"); b_del.clicked.connect(self._remove_range)
        lay.addWidget(b_del)
        self.split_merge = QCheckBox("Merge all ranges into one PDF")
        lay.addWidget(self.split_merge)
        lay.addStretch(1)
        self.btn_split = self._action_button("Split PDF", self._run_split)
        lay.addWidget(self.btn_split)
        return w

    def _page_delete(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Pages to delete:"))
        lay.addWidget(self._spec_row("delete"))
        lay.addWidget(self._select_buttons())
        lay.addStretch(1)
        self.btn_delete = self._action_button("Delete pages", self._run_delete)
        lay.addWidget(self.btn_delete)
        return w

    def _page_rotate(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        self.rotate_hint = QLabel(
            "Select pages to rotate (none selected = all pages), then turn:")
        self.rotate_hint.setWordWrap(True)
        lay.addWidget(self.rotate_hint)
        row = QHBoxLayout()
        b_l = QPushButton("↺ Left"); b_l.clicked.connect(lambda: self._nudge_rotation(270))
        b_r = QPushButton("↻ Right"); b_r.clicked.connect(lambda: self._nudge_rotation(90))
        row.addWidget(b_l); row.addWidget(b_r)
        rw = QWidget(); rw.setLayout(row); lay.addWidget(rw)
        b_reset = QPushButton("Reset rotation"); b_reset.clicked.connect(self._reset_rotation)
        lay.addWidget(b_reset)
        lay.addStretch(1)
        self.btn_rotate = self._action_button("Apply rotation", self._run_rotate)
        lay.addWidget(self.btn_rotate)
        return w

    def _page_launch(self, desc, handler, needs_viewer=False):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        d = QLabel(desc); d.setWordWrap(True); d.setObjectName("OptDesc")
        lay.addWidget(d)
        lay.addStretch(1)
        btn = self._action_button("Open…", handler)
        if needs_viewer:
            btn.setProperty("needs_viewer", True)
        lay.addWidget(btn)
        return w

    def _action_button(self, text, handler):
        btn = QPushButton(text); btn.setObjectName("ActionBtn")
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.clicked.connect(handler)
        return btn

    # -- operation selection -------------------------------------------------

    def _select_op(self, key):
        btn = self._rail_btns.get(key)
        if btn is not None:
            btn.setChecked(True)
        self.stack.setCurrentIndex(self._opt_index[key])
        labels = {k: l for k, l, _g in self.OPS}
        descs = {
            "extract": "Pick pages by clicking thumbnails (Shift/Ctrl for groups) "
                       "and pull them into a new PDF.",
            "split": "Define page ranges; each range becomes its own PDF "
                     "(or merge them all into one).",
            "delete": "Pick the pages to remove; the rest are saved to a new PDF.",
            "rotate": "Rotate selected pages (or all) — the thumbnails preview it.",
            "combine": "Merge several PDFs into one (drag to reorder).",
            "insert": "Drop one PDF into another at a chosen position.",
            "swap": "Replace a single page with another PDF page.",
            "sheet": "Split a set into files named by each drawing's sheet number.",
            "crop": "Capture regions across pages as PNGs (+ optional AI tag table).",
            "convert": "Convert a PDF to an editable Word document.",
        }
        self.opt_title.setText(labels.get(key, key))
        self.opt_desc.setText(descs.get(key, ""))
        self._active_op = key
        self._update_enabled()

    def show_operation(self, key):
        """Switch to the PDF Tools tab and select an operation (Tools menu)."""
        try:
            self.window.tabs.setCurrentWidget(self)
        except Exception:
            pass
        self._select_op(key)

    # -- file loading --------------------------------------------------------

    def load_pdf(self, path):
        if not path or not os.path.isfile(path):
            return
        self.current_pdf = path
        self.grid.set_pdf(path)
        n = self.grid.page_count
        self.file_name.setText(os.path.basename(path))
        self.file_hint.setText(f"{n} page(s) · drag another PDF to switch")
        self.split_from.setRange(1, max(1, n)); self.split_to.setRange(1, max(1, n))
        self.split_to.setValue(max(1, n))
        self.range_list.clear()
        self.grid.set_rotation_overrides({})
        self.status.setText("")
        self._update_enabled()

    def set_default_pdf(self, path):
        """Called when the Viewer opens a document — adopt it as the tools file."""
        self.load_pdf(path)

    def _open_pdf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", self.current_pdf or "", "PDF (*.pdf)")
        if path:
            self.load_pdf(path)

    def _default_pdf(self):
        if self.current_pdf:
            return self.current_pdf
        doc = getattr(self.window, "document", None)
        return doc.path if doc is not None else ""

    def _update_enabled(self):
        has = bool(self.current_pdf)
        for key in ("extract", "split", "delete", "rotate"):
            btn = getattr(self, f"btn_{key}", None)
            if btn is not None:
                btn.setEnabled(has)

    # -- drag & drop ---------------------------------------------------------

    def dragEnterEvent(self, event):
        if pdf_path_from_mime(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if pdf_path_from_mime(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = pdf_path_from_mime(event.mimeData())
        if path:
            self.load_pdf(path)
            event.acceptProposedAction()

    # -- selection <-> spec sync --------------------------------------------

    def _on_grid_selection(self, pages):
        if self._syncing:
            return
        spec = ops.pages_to_spec(pages)
        self._syncing = True
        try:
            for edit in self._spec_edits.values():
                edit.setText(spec)
        finally:
            self._syncing = False

    def _on_spec_edited(self, key, text):
        if self._syncing:
            return
        pages = ops.parse_page_ranges(text, max_page=self.grid.page_count or None)
        self._syncing = True
        try:
            self.grid.set_selected_pages(pages)
            spec = ops.pages_to_spec(pages)
            for k, edit in self._spec_edits.items():
                if k != key:
                    edit.setText(spec)
        finally:
            self._syncing = False

    # -- split range builder -------------------------------------------------

    def _add_range_item(self, a, b):
        it = QListWidgetItem(f"Pages {a + 1}–{b + 1}" if b > a else f"Page {a + 1}")
        it.setData(Qt.UserRole, (a, b))
        self.range_list.addItem(it)

    def _add_range(self):
        a = self.split_from.value() - 1
        b = self.split_to.value() - 1
        if a > b:
            a, b = b, a
        self._add_range_item(a, b)

    def _add_range_from_selection(self):
        pages = self.grid.selected_pages()
        if not pages:
            QMessageBox.information(self, "No selection",
                                    "Click page thumbnails to select a range first.")
            return
        self._add_range_item(pages[0], pages[-1])

    def _remove_range(self):
        for it in self.range_list.selectedItems():
            self.range_list.takeItem(self.range_list.row(it))

    def _ranges(self):
        return [self.range_list.item(i).data(Qt.UserRole)
                for i in range(self.range_list.count())]

    # -- rotate preview ------------------------------------------------------

    def _rotate_targets(self):
        sel = self.grid.selected_pages()
        return sel if sel else list(range(self.grid.page_count))

    def _nudge_rotation(self, delta):
        overrides = self.grid.rotation_overrides()
        for p in self._rotate_targets():
            overrides[p] = (overrides.get(p, 0) + delta) % 360
        self.grid.set_rotation_overrides(overrides)

    def _reset_rotation(self):
        self.grid.set_rotation_overrides({})

    # -- run operations ------------------------------------------------------

    def _run_extract(self):
        pages = self.grid.selected_pages()
        if not pages:
            QMessageBox.information(self, "No pages", "Select pages to extract first.")
            return
        merge = self.extract_merge.isChecked()
        src = self.current_pdf
        base, _ = os.path.splitext(src)
        if merge:
            out, _ = QFileDialog.getSaveFileName(
                self, "Save extracted PDF", base + "_extracted.pdf", "PDF (*.pdf)")
            if not out:
                return
            if not out.lower().endswith(".pdf"):
                out += ".pdf"
            loc = os.path.dirname(out)
        else:
            out = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if not out:
                return
            loc = out
        self._start(
            lambda p, c: ops.extract_pages(src, out, pages, merge=merge, progress=p, cancel=c),
            lambda r: (f"Extracted {len(pages)} page(s) into {os.path.basename(out)}."
                       if merge else f"Wrote {len(r)} file(s)."), loc)

    def _run_split(self):
        ranges = self._ranges()
        if not ranges:
            QMessageBox.information(self, "No ranges", "Add at least one range.")
            return
        merge = self.split_merge.isChecked()
        src = self.current_pdf
        base, _ = os.path.splitext(src)
        if merge:
            out, _ = QFileDialog.getSaveFileName(
                self, "Save merged ranges", base + "_ranges.pdf", "PDF (*.pdf)")
            if not out:
                return
            if not out.lower().endswith(".pdf"):
                out += ".pdf"
            loc = os.path.dirname(out)
        else:
            out = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if not out:
                return
            loc = out
        self._start(
            lambda p, c: ops.split_ranges(src, out, ranges, merge=merge, progress=p, cancel=c),
            lambda r: (f"Merged {len(ranges)} range(s) into {os.path.basename(out)}."
                       if merge else f"Wrote {len(r)} file(s)."), loc)

    def _run_delete(self):
        pages = self.grid.selected_pages()
        if not pages:
            QMessageBox.information(self, "No pages", "Select pages to delete first.")
            return
        if len(pages) >= self.grid.page_count:
            QMessageBox.warning(self, "Too many", "Refusing to delete every page.")
            return
        src = self.current_pdf
        base, _ = os.path.splitext(src)
        out, _ = QFileDialog.getSaveFileName(
            self, "Save trimmed PDF", base + "_deleted.pdf", "PDF (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        spec = ops.pages_to_spec(pages)
        self._start(
            lambda p, c: ops.delete_pages(src, out, spec),
            lambda r: f"Removed {len(pages)} page(s) → {os.path.basename(out)}.",
            os.path.dirname(out))

    def _run_rotate(self):
        overrides = {p: a for p, a in self.grid.rotation_overrides().items() if a}
        if not overrides:
            QMessageBox.information(self, "No rotation",
                                    "Use ↺ / ↻ to rotate pages first.")
            return
        src = self.current_pdf
        base, _ = os.path.splitext(src)
        out, _ = QFileDialog.getSaveFileName(
            self, "Save rotated PDF", base + "_rotated.pdf", "PDF (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        self._start(
            lambda p, c: ops.rotate_pdf_map(src, out, overrides, progress=p, cancel=c),
            lambda r: f"Rotated {len(overrides)} page(s) → {os.path.basename(out)}.",
            os.path.dirname(out))

    # -- background task plumbing -------------------------------------------

    def _start(self, fn, success_msg, output_loc):
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.setText("Working…")
        self._set_actions_enabled(False)
        self._success_msg = success_msg
        self._output_loc = output_loc
        self._task = BackgroundTask(fn, self)
        self._task.progress.connect(self._on_progress)
        self._task.done.connect(self._on_done)
        self._task.failed.connect(self._on_failed)
        self._task.start()

    def _on_progress(self, d, t):
        self.progress.setRange(0, max(1, t))
        self.progress.setValue(d)

    def _on_done(self, result):
        self._finish_task()
        msg = self._success_msg(result)
        self.status.setText("✓ " + msg)
        loc = self._output_loc
        if loc and os.path.isdir(loc):
            if QMessageBox.question(self, "Done", msg + "\n\nOpen the output folder?") \
                    == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(loc))

    def _on_failed(self, msg):
        self._finish_task()
        if msg == "__cancelled__":
            self.status.setText("Cancelled.")
        else:
            self.status.setText("Failed.")
            QMessageBox.warning(self, "Failed", msg)

    def _finish_task(self):
        self.progress.setVisible(False)
        self._set_actions_enabled(True)
        if self._task is not None:
            self._task.wait(2000)
            self._task = None

    def _set_actions_enabled(self, on):
        for key in ("extract", "split", "delete", "rotate"):
            btn = getattr(self, f"btn_{key}", None)
            if btn is not None:
                btn.setEnabled(on and bool(self.current_pdf))

    # -- file→file dialogs (also used by the Tools menu) ---------------------

    def open_split_pages(self):
        self.show_operation("extract")

    def open_delete(self):
        self.show_operation("delete")

    def open_rotate(self):
        self.show_operation("rotate")

    def open_combine(self):
        dlg.CombineDialog("Combine PDFs", self.window, self._default_pdf()).exec()

    def open_insert(self):
        dlg.InsertDialog("Insert PDF", self.window, self._default_pdf()).exec()

    def open_swap(self):
        dlg.SwapDialog("Swap a page", self.window, self._default_pdf()).exec()

    def open_convert(self):
        dlg.ConvertDialog("PDF → Word", self.window, self._default_pdf()).exec()

    # -- wizards (need the open document + viewer) ---------------------------

    def start_sheet_wizard(self):
        self._wizard = SheetNumberWizard(self.window)
        self._wizard.start()

    def start_crop_wizard(self):
        self._wizard = CropWizard(self.window)
        self._wizard.start()


# -- drag/drop helper (shared with the main window) --------------------------


def pdf_path_from_mime(mime) -> str:
    """Return the first dropped local ``.pdf`` path, or "" if none."""
    if mime is None or not mime.hasUrls():
        return ""
    for u in mime.urls():
        if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf"):
            return u.toLocalFile()
    return ""
