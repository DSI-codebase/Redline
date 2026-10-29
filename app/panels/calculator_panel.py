"""The Calculators tab: PyDRC's calculators, one form each.

A calculator that takes a list (conductors, segments, loads, components) holds
it in a table: one row each, **Add row** and **Remove row** beneath it, and a
row left empty is not an entry.

Built from ``app.calculators.specs`` and nothing else: a list of pages on the
left, the chosen calculator's form on the right, and the result below it,
shown whole (the tier, the values or the reasons there are none, the
arithmetic, the clauses and every table's sign-off note) by
``app.calculators.render``. The arithmetic is PyDRC's.

Three rules the tab keeps, each the library's own:

* **Blank means unanswered.** Fields start blank on every launch and nothing is
  filled in for the user; what is typed is kept while the app runs, so moving
  between calculators loses nothing, and is gone on the next launch.
* **Not computed is not zero.** A calculator that lacks an input shows PyDRC's
  reasons in place of a result.
* **No library, no tab.** Without PyDRC the tab says so, with the Audit tab's
  install instructions, rather than breaking the app.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QSplitter, QTableWidget,
                               QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..calculators import render, specs, status


class CalculatorPanel(QWidget):
    """Every calculator in ``specs.PAGES``, as a form and a result."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = {}           # calculator id -> {field name: value}, this session only
        self._widgets = {}          # field name -> widget, for the shown calculator
        self.calc = None
        self.result = None
        self.raw = {}
        self._build_ui()
        self._load_status()

    # -- construction --------------------------------------------------------

    def _build_ui(self):
        lay = QVBoxLayout(self)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status_label)

        self.split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._on_pick)
        for page in specs.PAGES:
            top = QTreeWidgetItem([page.title])
            top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
            for calc in page.calculators:
                item = QTreeWidgetItem([calc.title])
                item.setData(0, Qt.UserRole, calc.id)
                top.addChild(item)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
        self.split.addWidget(self.tree)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("Choose a calculator on the left.")
        f = self.title_label.font()
        f.setBold(True)
        self.title_label.setFont(f)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        rlay.addWidget(self.title_label)
        rlay.addWidget(self.summary_label)

        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_host)
        rlay.addWidget(scroll, 2)

        bar = QHBoxLayout()
        self.btn_calc = QPushButton("Calculate")
        self.btn_calc.clicked.connect(self.calculate)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setToolTip("Empty every field of this calculator")
        self.btn_clear.clicked.connect(self.clear)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setToolTip("Copy the inputs and the whole result as text")
        self.btn_copy.clicked.connect(self.copy)
        for b in (self.btn_calc, self.btn_clear, self.btn_copy):
            bar.addWidget(b)
        bar.addStretch(1)
        rlay.addLayout(bar)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        rlay.addWidget(self.output, 3)
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([330, 870])       # the calculator names, unclipped
        lay.addWidget(self.split, 1)
        self._set_buttons()

    def _load_status(self):
        ok, message = status()
        self.available = ok
        if ok:
            self.status_label.setText(
                f"{message}. The arithmetic and every citation are the design rule "
                f"library's. A table nobody has signed says so under each result.")
        else:
            self.status_label.setText("The calculators are unavailable.\n\n" + message)
        self.split.setEnabled(ok)

    # -- the form ------------------------------------------------------------

    def _on_pick(self, item, _previous=None):
        calc_id = item.data(0, Qt.UserRole) if item is not None else None
        calc = specs.find(calc_id) if calc_id else None
        if calc is None:
            return
        self.show_calculator(calc)

    def show_calculator(self, calc):
        """Build the form for ``calc``, refilled with what was typed this session."""
        self._remember()
        self.calc, self.result, self.raw = calc, None, {}
        while self.form.rowCount():
            self.form.removeRow(0)
        self._widgets = {}
        self.title_label.setText(calc.title)
        self.summary_label.setText(calc.summary)
        kept = self._values.get(calc.id, {})
        for f in calc.fields:
            w = self._make_field(f, kept.get(f.name))
            self._widgets[f.name] = w
            text = f"{f.label} ({f.unit})" if f.unit else f.label
            self.form.addRow(text, w)
        self.output.setPlainText("")
        self._set_buttons()

    def _make_field(self, f, kept):
        if f.kind == specs.TABLE:
            return _TableField(f, kept)
        if f.kind == specs.BOOL:
            w = QCheckBox()
            w.setChecked(bool(kept))
        elif f.kind == specs.CHOICE:
            w = QComboBox()
            w.setEditable(f.editable)
            w.addItem("")
            try:
                w.addItems(list(f.options()))
            except Exception as e:     # a PyDRC without the list: typed text still works
                w.setEditable(True)
                w.setToolTip(f"The choices could not be read from PyDRC: {e}")
            if kept:
                i = w.findText(str(kept))
                if i >= 0:
                    w.setCurrentIndex(i)
                elif w.isEditable():
                    w.setEditText(str(kept))
        else:
            w = QLineEdit()
            w.setPlaceholderText(f.hint)
            w.returnPressed.connect(self.calculate)
            if kept:
                w.setText(str(kept))
        if f.hint and not isinstance(w, QLineEdit):
            w.setToolTip(f.hint if not w.toolTip() else w.toolTip())
        return w

    def form_values(self) -> dict:
        """``{field name: text or bool}`` as the form holds it now."""
        out = {}
        for name, w in self._widgets.items():
            if isinstance(w, _TableField):
                out[name] = w.rows()
            elif isinstance(w, QCheckBox):
                out[name] = w.isChecked()
            elif isinstance(w, QComboBox):
                out[name] = w.currentText()
            else:
                out[name] = w.text()
        return out

    def _remember(self):
        if self.calc is not None:
            self._values[self.calc.id] = self.form_values()

    def set_field(self, name, value):
        """Fill one field, as typing it would (tests and future prefill)."""
        w = self._widgets[name]
        if isinstance(w, _TableField):
            w.set_rows(value)
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            i = w.findText(str(value))
            if i >= 0:
                w.setCurrentIndex(i)
            else:
                w.setEditable(True)
                w.setEditText(str(value))
        else:
            w.setText(str(value))

    # -- actions -------------------------------------------------------------

    def calculate(self):
        if self.calc is None or not self.available:
            return
        self.raw = self.form_values()
        self._remember()
        try:
            self.result = specs.run(self.calc, self.raw)
        except specs.Missing as e:
            self.result = None
            self.output.setPlainText(str(e))
            self._set_buttons()
            return
        except Exception as e:           # a library fault must not take the app down
            self.result = None
            self.output.setPlainText(f"The calculator stopped with an error: {e}")
            self._set_buttons()
            return
        self.output.setPlainText("\n".join(render.sections_lines(self.result)))
        self._set_buttons()

    def clear(self):
        for w in self._widgets.values():
            if isinstance(w, _TableField):
                w.set_rows([])
            elif isinstance(w, QCheckBox):
                w.setChecked(False)
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(0)
                if w.isEditable():
                    w.setEditText("")
            else:
                w.clear()
        self.result = None
        self.output.setPlainText("")
        self._remember()
        self._set_buttons()

    def copy_text(self) -> str:
        if self.calc is None or self.result is None:
            return ""
        try:
            import pydrc
            version = getattr(pydrc, "__version__", "")
        except Exception:
            version = ""
        return render.copy_text(self.calc, self.raw, self.result, version)

    def copy(self):
        text = self.copy_text()
        if text:
            QApplication.clipboard().setText(text)

    def _set_buttons(self):
        has = self.calc is not None and getattr(self, "available", False)
        self.btn_calc.setEnabled(has)
        self.btn_clear.setEnabled(has)
        self.btn_copy.setEnabled(self.result is not None)


class _TableField(QWidget):
    """A list input: one row per item, a column per ``Field`` in ``columns``.

    Choice columns are drop-downs of the same lists the plain fields use. A
    row with nothing in it is not an entry (``specs.table_rows``).
    """

    def __init__(self, field, kept=None, parent=None):
        super().__init__(parent)
        self.field = field
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(field.columns))
        self.table.setHorizontalHeaderLabels(
            [f"{c.label} ({c.unit})" if c.unit else c.label for c in field.columns])
        for i, c in enumerate(field.columns):
            if c.hint:
                self.table.horizontalHeaderItem(i).setToolTip(c.hint)
        self.table.setMinimumHeight(150)
        lay.addWidget(self.table)
        bar = QHBoxLayout()
        self.btn_add = QPushButton("Add row")
        self.btn_add.clicked.connect(lambda: self.add_row())
        self.btn_remove = QPushButton("Remove row")
        self.btn_remove.setToolTip("Remove the selected row, or the last one")
        self.btn_remove.clicked.connect(self.remove_row)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_remove)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.set_rows(kept or [])

    def add_row(self, values=None):
        values = values or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        for i, c in enumerate(self.field.columns):
            text = "" if values.get(c.name) is None else str(values.get(c.name))
            if c.kind == specs.CHOICE:
                box = QComboBox()
                box.setEditable(c.editable)
                box.addItem("")
                try:
                    box.addItems(list(c.options()))
                except Exception:
                    box.setEditable(True)
                k = box.findText(text)
                if k >= 0:
                    box.setCurrentIndex(k)
                elif text:
                    box.setEditable(True)
                    box.setEditText(text)
                self.table.setCellWidget(r, i, box)
            else:
                self.table.setItem(r, i, QTableWidgetItem(text))

    def remove_row(self):
        if not self.table.rowCount():
            return
        r = self.table.currentRow()
        self.table.removeRow(r if r >= 0 else self.table.rowCount() - 1)

    def rows(self) -> list:
        out = []
        for r in range(self.table.rowCount()):
            row = {}
            for i, c in enumerate(self.field.columns):
                w = self.table.cellWidget(r, i)
                if isinstance(w, QComboBox):
                    row[c.name] = w.currentText()
                else:
                    item = self.table.item(r, i)
                    row[c.name] = item.text() if item is not None else ""
            out.append(row)
        return out

    def set_rows(self, rows):
        self.table.setRowCount(0)
        for row in rows or [{}]:
            self.add_row(row)
