"""The small modal dialogs the window opens, and the swatch icons they draw.

Lifted out of ``main_window`` for the reason ``settings_dialog`` was: that
module held these five alongside five panes, the menus and the file lifecycle.
``app/tools/dialogs.py`` is the declared home for the PDF-tool dialogs and had
been for releases; these are the annotation and audit ones, and they had simply
grown up beside the window instead.

Kept together because they genuinely reference each other -- measured by AST
rather than assumed: ``TextEditDialog`` opens a ``FillDialog`` and draws both
swatches, and ``FillDialog`` draws one. ``_apply_font``, ``WaiveDialog`` and
``SheetRolesDialog`` reference nothing here and travel with them only because
they are the same subject.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSlider, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from .extraction import sheet_role
from .model.annotations import (
    Annotation, KIND_CALLOUT, KIND_COMMENT, KIND_TEXTBOX,
)


class TextEditDialog(QDialog):
    def __init__(self, ann: Annotation, parent=None, is_textbox=False):
        super().__init__(parent)
        self.ann = ann
        self.is_textbox = is_textbox
        self._font_color = tuple(ann.color)
        if ann.kind == KIND_CALLOUT:
            title = "Edit callout"
        elif is_textbox or ann.kind == KIND_TEXTBOX:
            title = "Edit text box"
        elif ann.kind == KIND_COMMENT:
            title = "Edit comment"
        else:
            # a free note attached to a highlight / arrow / rectangle / pen
            title = "Edit note" if (ann.text or "").strip() else "Add note"
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(ann.text or "")
        self.edit.setMinimumSize(320, 120)
        self.edit.installEventFilter(self)  # Ctrl/Shift+Enter -> OK
        lay.addWidget(self.edit)

        # font styling — only meaningful for on-page text boxes
        if is_textbox:
            self._fill_color = tuple(ann.fill_color) if ann.fill_color else None
            self._fill_opacity = float(ann.fill_opacity)
            frow = QHBoxLayout()
            self.size_spin = QSpinBox(); self.size_spin.setRange(4, 96)
            self.size_spin.setValue(int(ann.font_size))
            self.bold_cb = QCheckBox("B"); self.bold_cb.setChecked(ann.bold)
            self.italic_cb = QCheckBox("I"); self.italic_cb.setChecked(ann.italic)
            self.color_btn = QPushButton("Font color")
            self.color_btn.clicked.connect(self._pick_color)
            self._update_color_swatch()
            self.fill_btn = QPushButton("Fill")
            self.fill_btn.setToolTip("Box background — pick color + opacity "
                                     "(alpha 0 = none, 100% = opaque cover)")
            self.fill_btn.clicked.connect(self._pick_fill)
            self._update_fill_swatch()
            frow.addWidget(QLabel("Size:")); frow.addWidget(self.size_spin)
            frow.addWidget(self.bold_cb); frow.addWidget(self.italic_cb)
            frow.addWidget(self.color_btn); frow.addWidget(self.fill_btn)
            frow.addStretch(1)
            lay.addLayout(frow)

        self.todo = QCheckBox("Flag as TODO")
        self.todo.setChecked(ann.is_todo)
        lay.addWidget(self.todo)
        hint = QLabel("Ctrl+Enter or Shift+Enter to save · Esc to cancel")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick_color(self):
        rgb = self._font_color
        col = QColorDialog.getColor(
            QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)), self,
            "Font color")
        if col.isValid():
            self._font_color = (col.redF(), col.greenF(), col.blueF())
            self._update_color_swatch()

    def _update_color_swatch(self):
        self.color_btn.setIcon(_swatch(QColor(
            int(self._font_color[0] * 255), int(self._font_color[1] * 255),
            int(self._font_color[2] * 255))))

    def _pick_fill(self):
        ok, color, opacity = FillDialog.ask(self, self._fill_color,
                                            self._fill_opacity, "Box fill")
        if not ok:
            return
        self._fill_color = color
        if color is not None:
            self._fill_opacity = opacity
        self._update_fill_swatch()

    def _update_fill_swatch(self):
        self.fill_btn.setIcon(_fill_swatch(self._fill_color, self._fill_opacity))

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.KeyPress:
            if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                    and (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))):
                self.accept()
                return True
        return super().eventFilter(obj, event)

    def values(self):
        return self.edit.toPlainText(), self.todo.isChecked()

    def font_values(self):
        """Font styling for a text box, or ``None`` for a comment."""
        if not self.is_textbox:
            return None
        return {
            "font_size": float(self.size_spin.value()),
            "bold": self.bold_cb.isChecked(),
            "italic": self.italic_cb.isChecked(),
            "color": tuple(self._font_color),
            "fill_color": tuple(self._fill_color) if self._fill_color else None,
            "fill_opacity": float(self._fill_opacity),
        }


def _apply_font(ann: Annotation, fv) -> None:
    if not fv:
        return
    ann.font_size = fv["font_size"]
    ann.bold = fv["bold"]
    ann.italic = fv["italic"]
    ann.color = tuple(fv["color"])
    if "fill_color" in fv:
        ann.fill_color = tuple(fv["fill_color"]) if fv["fill_color"] else None
        ann.fill_opacity = fv["fill_opacity"]


class WaiveDialog(QDialog):
    """Record why a finding is acceptable on this project.

    A reason is required, not optional. Every real panel has justified
    exceptions, and a waiver without one is indistinguishable from someone
    silencing an inconvenient rule — which is how audit tooling loses the trust
    that makes it worth running.
    """

    def __init__(self, finding, author: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Waive finding")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        summary = QLabel(finding.message)
        summary.setWordWrap(True)
        lay.addWidget(summary)

        # Every sheet, because the waiver covers every one of them. A reviewer
        # told "sheet 232" while agreeing to something that also stands on 233
        # through 240 has not been asked the question they are answering.
        seen = getattr(finding, "sheets", None) or (
            [finding.sheet] if finding.sheet else [])
        where = ("set-wide" if not seen
                 else f"sheet {seen[0]}" if len(seen) == 1
                 else f"sheets {', '.join(seen)}")
        detail = QLabel(f"{finding.rule_id} · {where}"
                        + (f" · cited: {finding.clause}" if finding.clause else ""))
        detail.setWordWrap(True)
        detail.setStyleSheet("color: palette(mid);")
        lay.addWidget(detail)

        form = QFormLayout()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Why is this acceptable here?")
        self.author = QLineEdit(author)
        form.addRow("Reason", self.reason)
        form.addRow("Waived by", self.author)
        lay.addLayout(form)

        note = QLabel("The finding stays on the list, struck through, so the "
                      "decision stays visible.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok = bb.button(QDialogButtonBox.Ok)
        self._ok.setEnabled(False)
        self.reason.textChanged.connect(
            lambda t: self._ok.setEnabled(bool(t.strip())))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> tuple:
        return self.reason.text().strip(), self.author.text().strip()


def decided_by_text(decided_by: str, confidence=None) -> str:
    """What the Decided by column says for a ``Document.sheet_role_decision``."""
    if decided_by == "user":
        return "You"
    if decided_by == "jev":
        return f"Jev ({confidence:.2f})" if confidence is not None else "Jev"
    return "Title-block keywords"


class SheetRolesDialog(QDialog):
    """Set a sheet's role, or hand it back to automatic detection.

    The design rule check reads a role to decide which rules apply to a sheet
    (a tag-location rule on a schematic, not on a panel layout). Detection
    reads the title block and is sometimes wrong, and the person reading the
    drawing knows better -- so a role set here wins over the keyword table and
    over Jev, and is never replaced by either.

    Each row shows what the check uses now and who decided it, read from
    ``Document.sheet_role_decision``, the same function the check reads.
    Nothing is written until OK; :meth:`changes` is what the caller applies,
    through ``Document.set_sheet_role``.
    """

    COL_PAGE, COL_SHEET, COL_ROLE, COL_BY = range(4)

    def __init__(self, document, use_jev: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sheet roles")
        self.setMinimumSize(560, 420)
        self._doc = document
        self._use_jev = use_jev
        self._initial: dict = {}
        self._combos: dict = {}
        lay = QVBoxLayout(self)

        source = "the title block and Jev" if use_jev else "the title block"
        note = QLabel(
            f"Automatic roles come from {source}. A role you choose here is used "
            "by the design rule check and is never replaced by detection. Run "
            "the check again to apply a change.")
        note.setWordWrap(True)
        lay.addWidget(note)

        n = document.page_count
        self.table = QTableWidget(n, 4)
        self.table.setHorizontalHeaderLabels(["Page", "Sheet", "Role", "Decided by"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_ROLE, QHeaderView.Stretch)
        for p in range(n):
            role, by, conf = document.sheet_role_decision(p, use_jev)
            auto_role, _auto_by, _auto_conf = document.automatic_sheet_role(p, use_jev)
            self.table.setItem(p, self.COL_PAGE, QTableWidgetItem(str(p + 1)))
            self.table.setItem(p, self.COL_SHEET,
                               QTableWidgetItem(document.sheet_label(p) or "-"))
            combo = QComboBox()
            combo.addItem(f"Automatic: {sheet_role.ROLE_LABELS[auto_role]}", "")
            for r in sheet_role.ROLES:
                if r != sheet_role.UNKNOWN:
                    combo.addItem(sheet_role.ROLE_LABELS[r], r)
            initial = role if by == "user" else ""
            combo.setCurrentIndex(max(0, combo.findData(initial)))
            combo.currentIndexChanged.connect(
                lambda _i, page=p: self._refresh_by(page))
            self.table.setCellWidget(p, self.COL_ROLE, combo)
            self.table.setItem(p, self.COL_BY, QTableWidgetItem(""))
            self._initial[p] = initial
            self._combos[p] = combo
            self._refresh_by(p)
        self.table.resizeColumnToContents(self.COL_PAGE)
        self.table.resizeColumnToContents(self.COL_SHEET)
        lay.addWidget(self.table, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        if not getattr(document, "sidecar_available", True):
            # View-only: a role set here would be saved nowhere.
            for combo in self._combos.values():
                combo.setEnabled(False)
            bb.button(QDialogButtonBox.Ok).setEnabled(False)
            ro = QLabel("This file has no markup database, so roles cannot be "
                        "saved. Rename it to something shorter and simpler, then "
                        "reopen it.")
            ro.setWordWrap(True)
            lay.addWidget(ro)
        lay.addWidget(bb)

    def _refresh_by(self, page: int) -> None:
        if self._combos[page].currentData():
            text = decided_by_text("user")
        else:
            _role, by, conf = self._doc.automatic_sheet_role(page, self._use_jev)
            text = decided_by_text(by, conf)
        self.table.item(page, self.COL_BY).setText(text)

    def set_choice(self, page: int, role: str) -> None:
        """Pick ``role`` for ``page``; ``""`` for automatic."""
        combo = self._combos[int(page)]
        combo.setCurrentIndex(max(0, combo.findData(role or "")))

    def changes(self) -> dict:
        """``{page: role}`` for every row moved from where it opened; ``""``
        hands that page back to detection."""
        return {p: (c.currentData() or "") for p, c in self._combos.items()
                if (c.currentData() or "") != self._initial[p]}


def _swatch(color: QColor) -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(color)
    return QIcon(pm)


def _fill_swatch(rgb, opacity) -> QIcon:
    """Swatch for the Fill button: a checkerboard shows through translucent /
    no-fill states so 'transparent' is visually distinct from 'white cover'."""
    from PySide6.QtGui import QPainter, QColor as _QC
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # grey checkerboard backdrop
    for i in range(0, 16, 4):
        for j in range(0, 16, 4):
            shade = 200 if ((i + j) // 4) % 2 == 0 else 235
            p.fillRect(i, j, 4, 4, _QC(shade, shade, shade))
    if rgb is not None and opacity > 0:
        a = int(max(0.0, min(1.0, opacity)) * 255)
        p.fillRect(0, 0, 16, 16,
                   _QC(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), a))
    p.setPen(_QC(120, 120, 120))
    p.drawRect(0, 0, 15, 15)
    p.end()
    return QIcon(pm)


class FillDialog(QDialog):
    """Pick an interior fill: a color plus a plain-language opacity slider
    (clearer than a raw alpha channel), or 'No fill'."""

    def __init__(self, color, opacity, parent=None, title="Fill"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._color = tuple(color) if color else (1.0, 1.0, 1.0)
        lay = QVBoxLayout(self)

        self.none_cb = QCheckBox("No fill (transparent)")
        self.none_cb.setChecked(color is None)
        self.none_cb.toggled.connect(self._on_none_toggled)
        lay.addWidget(self.none_cb)

        crow = QHBoxLayout()
        self.color_btn = QPushButton("Color…")
        self.color_btn.clicked.connect(self._pick_color)
        crow.addWidget(self.color_btn)
        self.swatch = QLabel()
        self.swatch.setFixedSize(48, 20)
        crow.addWidget(self.swatch)
        crow.addStretch(1)
        lay.addLayout(crow)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Opacity:"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(max(0.0, min(1.0, opacity)) * 100)))
        self.slider.valueChanged.connect(self._on_slider)
        srow.addWidget(self.slider, 1)
        self.pct = QLabel(f"{self.slider.value()}%")
        self.pct.setFixedWidth(40)
        srow.addWidget(self.pct)
        lay.addLayout(srow)

        hint = QLabel("0% = transparent · 100% = opaque cover")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._on_none_toggled(self.none_cb.isChecked())
        self._update_swatch()

    def _on_none_toggled(self, none_on: bool):
        for w in (self.color_btn, self.slider, self.pct):
            w.setEnabled(not none_on)
        self._update_swatch()

    def _on_slider(self, v: int):
        self.pct.setText(f"{v}%")
        self._update_swatch()

    def _pick_color(self):
        rgb = self._color
        col = QColorDialog.getColor(
            QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)),
            self, "Fill color")           # no alpha channel — opacity is the slider
        if col.isValid():
            self._color = (col.redF(), col.greenF(), col.blueF())
            self._update_swatch()

    def _update_swatch(self):
        if self.none_cb.isChecked():
            self.swatch.setPixmap(_fill_swatch(None, 0.0).pixmap(20, 20))
        else:
            self.swatch.setPixmap(
                _fill_swatch(self._color, self.slider.value() / 100.0).pixmap(20, 20))

    def result_fill(self):
        """Return (color_tuple_or_None, opacity_float)."""
        if self.none_cb.isChecked() or self.slider.value() <= 0:
            return None, 1.0
        return self._color, self.slider.value() / 100.0

    @staticmethod
    def ask(parent, color, opacity, title="Fill"):
        """Show the dialog; return (accepted, color_or_None, opacity)."""
        dlg = FillDialog(color, opacity, parent, title)
        if dlg.exec() == QDialog.Accepted:
            c, o = dlg.result_fill()
            return True, c, o
        return False, color, opacity
