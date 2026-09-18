"""The in-document search panel (Ctrl+F).

A floating panel pinned to the viewer's top-right corner. Beyond the classic
find bar (search-as-you-type, *i/n* count, Enter / Shift+Enter, ✕ to close) it
adds what drawing sets actually need:

- **option toggles** — match case, whole words, regex, and "include marks"
  (search the comments/text boxes/callouts too);
- a **results index**: a scrollable dropdown listing every match with its
  surrounding line, grouped by page/sheet, click to jump. Matched tokens the
  app recognizes as component tags or wire numbers show their decoded
  sheet/rung inline;
- **search history**: recent queries come back via the input's dropdown
  completer, remembered across sessions.

The panel closes only from its own ✕ or Esc pressed inside it — deliberately
not from events elsewhere in the canvas, which is what kept hiding the old bar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QSize, QRect
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLineEdit, QLabel, QToolButton,
    QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle, QCompleter,
    QSizePolicy,
)

ROLE_INDEX = Qt.UserRole            # int: match index, or -1 for a header row
ROLE_PARTS = Qt.UserRole + 1        # (before, match, after, decode, is_mark)

_ACCENT = QColor(232, 119, 46)      # the app's orange accent
_MATCH_BG = QColor(255, 213, 0, 120)


class _ResultDelegate(QStyledItemDelegate):
    """Paints match rows as context with the hit emphasized, and page/sheet
    header rows as slim separators."""

    PAD_X = 8
    ROW_H = 22
    HEADER_H = 20

    # Extra px granted beyond each segment's measured advance. elidedText()
    # at a width exactly equal to horizontalAdvance() still elides — integer
    # metrics round below the true float advance — so a zero-slack budget
    # elided every row by a character or two even with the whole row free.
    SLACK = 4

    @classmethod
    def _budget(cls, fm, fmb, before, match, after, avail):
        """Split ``avail`` px between the three context segments. The match
        gets what it needs first; the leftovers go to before/after, either of
        which may borrow the other's unused half."""
        adv_b = fm.horizontalAdvance(before) + (cls.SLACK if before else 0)
        adv_m = fmb.horizontalAdvance(match) + cls.SLACK
        adv_a = fm.horizontalAdvance(after) + (cls.SLACK if after else 0)
        match_w = min(adv_m, avail)
        side = max(0, avail - match_w)
        before_w = min(adv_b, side // 2 + max(0, side // 2 - adv_a))
        after_w = min(adv_a, avail - match_w - before_w)
        return before_w, match_w, after_w

    def sizeHint(self, option, index):
        is_header = index.data(ROLE_INDEX) == -1
        return QSize(option.rect.width(),
                     self.HEADER_H if is_header else self.ROW_H)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        pal = option.palette
        r = option.rect

        if index.data(ROLE_INDEX) == -1:                      # header row
            painter.fillRect(r, pal.color(QPalette.AlternateBase))
            f = QFont(option.font)
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1))
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(pal.color(QPalette.PlaceholderText))
            painter.drawText(r.adjusted(self.PAD_X, 0, -self.PAD_X, 0),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             index.data(Qt.DisplayRole) or "")
            painter.restore()
            return

        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.fillRect(r, pal.color(QPalette.Highlight))
        elif option.state & QStyle.State_MouseOver:
            hov = pal.color(QPalette.Highlight)
            hov.setAlpha(28)
            painter.fillRect(r, hov)

        before, match, after, decode, is_mark = index.data(ROLE_PARTS)
        base_pen = (pal.color(QPalette.HighlightedText) if selected
                    else pal.color(QPalette.Text))
        dim_pen = QColor(base_pen)
        dim_pen.setAlpha(150)

        fm = QFontMetrics(option.font)
        bold = QFont(option.font)
        bold.setBold(True)
        fmb = QFontMetrics(bold)

        x = r.x() + self.PAD_X
        right = r.right() - self.PAD_X
        text_rect = lambda w: QRect(int(x), r.y(), int(w), r.height())

        # a small glyph marks hits found in marks/comments rather than the page
        if is_mark:
            painter.setPen(_ACCENT if not selected else base_pen)
            painter.drawText(text_rect(14), Qt.AlignVCenter, "✎")
            x += 14

        # decoded tag info is right-aligned and drawn first so the context can
        # elide against whatever room is left
        decode_w = 0
        if decode:
            f = QFont(option.font)
            f.setItalic(True)
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1))
            dfm = QFontMetrics(f)
            decode_w = min(dfm.horizontalAdvance(decode) + 10, (right - x) // 2)
            painter.setFont(f)
            painter.setPen(dim_pen if not selected else base_pen)
            painter.drawText(QRect(int(right - decode_w), r.y(),
                                   int(decode_w), r.height()),
                             Qt.AlignVCenter | Qt.AlignRight,
                             dfm.elidedText(decode, Qt.ElideRight, decode_w))
        avail = right - decode_w - x - 4
        before_w, match_w, after_w = self._budget(fm, fmb, before, match,
                                                  after, avail)

        painter.setFont(option.font)
        painter.setPen(dim_pen)
        el_before = fm.elidedText(before, Qt.ElideLeft, int(before_w)) \
            if before_w > 12 else ""
        painter.drawText(text_rect(before_w), Qt.AlignVCenter, el_before)
        x += fm.horizontalAdvance(el_before)

        el_match = fmb.elidedText(match, Qt.ElideRight, int(match_w))
        mw = fmb.horizontalAdvance(el_match)
        if not selected:
            painter.fillRect(QRect(int(x) - 1, r.y() + 3, int(mw) + 2,
                                   r.height() - 6), _MATCH_BG)
        painter.setFont(bold)
        painter.setPen(base_pen)
        painter.drawText(text_rect(mw + 2), Qt.AlignVCenter, el_match)
        x += mw

        painter.setFont(option.font)
        painter.setPen(dim_pen)
        if after_w > 12:
            painter.drawText(text_rect(after_w), Qt.AlignVCenter,
                             fm.elidedText(after, Qt.ElideRight, int(after_w)))
        painter.restore()


class SearchBar(QFrame):
    queryChanged = Signal(str)   # debounced (or forced) query text
    nextRequested = Signal()
    prevRequested = Signal()
    closed = Signal()
    optionsChanged = Signal()
    matchActivated = Signal(int)  # index into the current match list

    PANEL_W = 400
    LIST_MAX_H = 300

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("SearchBar")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(self.PANEL_W)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(
            lambda: self.queryChanged.emit(self.input.text()))

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 6, 6)
        root.setSpacing(4)

        # -- row 1: input / count / nav / close ------------------------------
        top = QHBoxLayout()
        top.setSpacing(4)

        self.input = QLineEdit()
        self.input.setObjectName("SearchInput")
        self.input.setPlaceholderText("Find in document")
        self.input.setClearButtonEnabled(True)
        self.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input.textChanged.connect(lambda *_: self._debounce.start())
        self.input.returnPressed.connect(self._on_return)
        self.input.installEventFilter(self)

        self.count = QLabel("0/0")
        self.count.setObjectName("SearchCount")
        self.count.setMinimumWidth(52)
        self.count.setAlignment(Qt.AlignCenter)

        self.btn_prev = self._tool("▲", "Previous match (Shift+Enter / Shift+F3)",
                                   self.prevRequested)
        self.btn_next = self._tool("▼", "Next match (Enter / F3)",
                                   self.nextRequested)
        self.btn_close = self._tool("✕", "Close (Esc)", self.closed)

        for w in (self.input, self.count, self.btn_prev, self.btn_next,
                  self.btn_close):
            top.addWidget(w)
        root.addLayout(top)

        # -- row 2: option toggles + results collapse ------------------------
        opts = QHBoxLayout()
        opts.setSpacing(3)
        self.opt_case = self._toggle("Aa", "Match case", "search/case")
        self.opt_word = self._toggle("Word", "Whole words only", "search/word")
        self.opt_regex = self._toggle(".*", "Regular expression", "search/regex")
        self.opt_marks = self._toggle("Marks", "Also search comments, text "
                                      "boxes, callouts and notes",
                                      "search/marks", default=True)
        for b in (self.opt_case, self.opt_word, self.opt_regex, self.opt_marks):
            opts.addWidget(b)
        opts.addStretch(1)
        self.btn_list = QToolButton()
        self.btn_list.setCheckable(True)
        self.btn_list.setChecked(True)
        self.btn_list.setToolTip("Show the match list")
        self.btn_list.toggled.connect(self._update_list_visibility)
        opts.addWidget(self.btn_list)
        root.addLayout(opts)

        # -- results index ---------------------------------------------------
        self.results = QListWidget()
        self.results.setObjectName("SearchResults")
        self.results.setUniformItemSizes(False)
        self.results.setMouseTracking(True)
        self.results.setMaximumHeight(self.LIST_MAX_H)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setItemDelegate(_ResultDelegate(self.results))
        self.results.itemClicked.connect(self._activate_item)
        self.results.itemActivated.connect(self._activate_item)
        self.results.installEventFilter(self)
        self.results.hide()
        root.addWidget(self.results)

        self._match_rows: dict = {}       # match index -> list row
        self._have_matches = False

        self._completer = QCompleter(self._recent(), self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self.input.setCompleter(self._completer)

        self.setStyleSheet("""
            QFrame#SearchBar {
                background: #fbfbfb; border: 1px solid #b4b4b4; border-radius: 7px;
            }
            QLineEdit#SearchInput {
                border: 1px solid #cfcfcf; border-radius: 4px; padding: 3px 6px;
                background: white; color: #1d1d1d;
            }
            QLabel#SearchCount { color: #6a6a6a; }
            QToolButton { border: none; padding: 2px 6px; color: #2a2a2a; font-size: 12px; }
            QToolButton:hover { background: #e7e7e7; border-radius: 4px; }
            QToolButton:checked { background: #ffe3cd; border-radius: 4px; color: #b35310; }
            QListWidget#SearchResults {
                border: 1px solid #d6d6d6; border-radius: 4px; background: white;
                color: #1d1d1d; font-size: 12px;
            }
        """)
        self._update_list_button()
        self.adjustSize()

    # -- construction helpers ------------------------------------------------

    def _tool(self, text, tip, signal):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.clicked.connect(lambda: signal.emit())
        return b

    def _toggle(self, text, tip, key, default=False):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(True)
        checked = default
        if self.config is not None:
            try:
                checked = str(self.config.get(key)).lower() in ("1", "true")
            except Exception:
                checked = default
        b.setChecked(checked)

        def _changed(on, key=key):
            if self.config is not None:
                try:
                    self.config.set(key, "true" if on else "false")
                except Exception:
                    pass
            self.optionsChanged.emit()

        b.toggled.connect(_changed)
        return b

    # -- public API ----------------------------------------------------------

    def focus_input(self):
        self.input.setFocus()
        self.input.selectAll()

    def options(self):
        from .doc_search import SearchOptions
        return SearchOptions(
            case_sensitive=self.opt_case.isChecked(),
            whole_word=self.opt_word.isChecked(),
            regex=self.opt_regex.isChecked(),
            include_marks=self.opt_marks.isChecked(),
        )

    def set_count(self, index: int, total: int, capped: bool = False):
        n = f"{total}+" if capped else str(total)
        self.count.setText(f"{index}/{n}")
        empty = total == 0 and bool(self.input.text())
        self.count.setStyleSheet("color:#c0392b;" if empty else "color:#6a6a6a;")
        self.count.setToolTip(
            "Only the first %d matches are listed" % total if capped else "")

    def set_error(self, message: str):
        """Show a query problem (e.g. a bad regex) without spamming a dialog."""
        self.count.setText("—")
        self.count.setStyleSheet("color:#c0392b;")
        self.count.setToolTip(message)

    def set_matches(self, matches, sheet_labels=None, capped=False):
        """Rebuild the results index from engine matches."""
        sheet_labels = sheet_labels or {}
        self.results.clear()
        self._match_rows = {}
        self._have_matches = bool(matches)
        page = None
        counts: dict = {}
        for m in matches:
            counts[m.page] = counts.get(m.page, 0) + 1
        for i, m in enumerate(matches):
            if m.page != page:
                page = m.page
                sheet = sheet_labels.get(page, "")
                label = f"Page {page + 1}"
                if sheet:
                    label += f" · Sheet {sheet}"
                label += f" — {counts[page]}"
                head = QListWidgetItem(label)
                head.setData(ROLE_INDEX, -1)
                head.setFlags(Qt.NoItemFlags)
                self.results.addItem(head)
            it = QListWidgetItem("")
            it.setData(ROLE_INDEX, i)
            it.setData(ROLE_PARTS, (m.before, m.text, m.after, m.decode,
                                    m.source == "mark"))
            tip = (m.before + m.text + m.after).strip()
            if m.source == "mark":
                tip = f"{m.kind} by {m.author or '?'}:  {tip}"
            if m.decode:
                tip += f"\n{m.decode}"
            it.setToolTip(tip)
            self.results.addItem(it)
            self._match_rows[i] = self.results.count() - 1
        self._update_list_button(len(matches), capped)
        self._update_list_visibility()

    def set_current(self, index: int):
        row = self._match_rows.get(index)
        if row is None:
            return
        self.results.blockSignals(True)
        self.results.setCurrentRow(row)
        self.results.blockSignals(False)
        self.results.scrollToItem(self.results.item(row))

    def remember(self, query: str):
        """Record a committed query in the persistent search history."""
        q = (query or "").strip()
        if not q or self.config is None:
            return
        try:
            self.config.add_recent_search(q)
            self._completer.model().setStringList(self._recent())
        except Exception:
            pass

    # -- behaviour -----------------------------------------------------------

    def _recent(self) -> list:
        if self.config is None:
            return []
        try:
            return list(self.config.recent_searches)
        except Exception:
            return []

    def _update_list_button(self, n: int = 0, capped: bool = False):
        arrow = "▾" if self.btn_list.isChecked() else "▸"
        label = f"{arrow} {n}{'+' if capped else ''} matches" if n else arrow
        self.btn_list.setText(label)

    def _update_list_visibility(self):
        show = self._have_matches and self.btn_list.isChecked()
        if show:
            # size the dropdown to its rows (up to the cap) instead of leaving
            # a block of empty list under a handful of matches
            d = _ResultDelegate
            content = 2 * self.results.frameWidth()
            for i in range(self.results.count()):
                is_header = self.results.item(i).data(ROLE_INDEX) == -1
                content += d.HEADER_H if is_header else d.ROW_H
            self.results.setFixedHeight(min(content, self.LIST_MAX_H))
        self.results.setVisible(show)
        self._update_list_button(len(self._match_rows),
                                 "+" in self.count.text())
        self.adjustSize()

    def _activate_item(self, item):
        idx = item.data(ROLE_INDEX)
        if idx is not None and idx >= 0:
            self.matchActivated.emit(int(idx))

    def _on_return(self):
        # If the query changed and hasn't been searched yet, search it now
        # (lands on the first match); otherwise advance to the next match.
        self.remember(self.input.text())      # Enter commits it to history
        if self._debounce.isActive():
            self._debounce.stop()
            self.queryChanged.emit(self.input.text())
        else:
            self.nextRequested.emit()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                if obj is self.results:
                    self.input.setFocus()
                else:
                    self.closed.emit()
                return True
            if obj is self.input:
                if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                        and (event.modifiers() & Qt.ShiftModifier)):
                    self.prevRequested.emit()
                    return True
                if event.key() == Qt.Key_Down and self.results.isVisible():
                    self.results.setFocus()
                    if self.results.currentRow() < 0 and self._match_rows:
                        self.results.setCurrentRow(min(self._match_rows.values()))
                    return True
            if obj is self.results and event.key() in (Qt.Key_Return,
                                                       Qt.Key_Enter):
                item = self.results.currentItem()
                if item is not None:
                    self._activate_item(item)
                return True
        return super().eventFilter(obj, event)
