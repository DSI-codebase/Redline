"""A reusable iLovePDF-style page-thumbnail grid.

A :class:`QListWidget` in icon mode that shows every page of a PDF as a
thumbnail and lets the user pick pages visually (click, shift-range, ctrl-add)
instead of typing a page spec.  Thumbnails render lazily so large sets stay
responsive; the selection is two-way synced with a page-spec text box by the
workspace.  Opens its own lightweight :class:`fitz.Document` from a path so it
is independent of the annotate viewer.
"""

from __future__ import annotations

from typing import Optional

import fitz

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QImage, QPixmap, QIcon, QTransform
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView


def _pixmap_to_qpixmap(pix) -> QPixmap:
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())


class ThumbnailGrid(QListWidget):
    """Visual page picker.

    ``selectionPagesChanged(list)`` carries the sorted 0-based selection whenever
    it changes (user click or programmatic sync).
    """

    selectionPagesChanged = Signal(list)

    THUMB_W = 168
    THUMB_H = 128

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ThumbGrid")
        self.doc: Optional[fitz.Document] = None
        self._base_pix: dict = {}      # row -> base QPixmap (page visual orient.)
        self._overrides: dict = {}     # page -> extra rotation (deg)
        self._syncing = False

        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(self.THUMB_W, self.THUMB_H))
        self.setGridSize(QSize(self.THUMB_W + 28, self.THUMB_H + 40))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)

        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.verticalScrollBar().valueChanged.connect(
            lambda *_: QTimer.singleShot(0, self._render_visible_thumbs))

    # -- document -----------------------------------------------------------

    def set_pdf(self, path: str):
        """Load ``path`` and (re)build the thumbnail list."""
        self.close_doc()
        try:
            self.doc = fitz.open(path)
        except Exception:
            self.doc = None
        self._base_pix = {}
        self._overrides = {}
        self.clear()
        if self.doc is None:
            return
        for i in range(self.doc.page_count):
            it = QListWidgetItem(str(i + 1))
            it.setData(Qt.UserRole, i)
            it.setTextAlignment(Qt.AlignHCenter)
            it.setSizeHint(QSize(self.THUMB_W + 24, self.THUMB_H + 34))
            self.addItem(it)
        QTimer.singleShot(0, self._render_visible_thumbs)

    def close_doc(self):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc is not None else 0

    # -- lazy thumbnails -----------------------------------------------------

    def _render_visible_thumbs(self):
        if self.doc is None:
            return
        vp = self.viewport().rect()
        for row in range(self.count()):
            if row in self._base_pix:
                continue
            it = self.item(row)
            rect = self.visualItemRect(it)
            if rect.bottom() < -60 or rect.top() > vp.height() + 60:
                continue
            page = int(it.data(Qt.UserRole))
            try:
                pr = self.doc[page].rect
                zoom = self.THUMB_W / max(1.0, pr.width)
                # cap height too so tall pages don't overflow the icon box
                zoom = min(zoom, self.THUMB_H / max(1.0, pr.height))
                pix = self.doc[page].get_pixmap(
                    matrix=fitz.Matrix(max(0.05, zoom), max(0.05, zoom)), alpha=False)
                self._base_pix[row] = _pixmap_to_qpixmap(pix)
                self._apply_icon(row)
            except Exception:
                pass

    def _apply_icon(self, row: int):
        base = self._base_pix.get(row)
        if base is None:
            return
        it = self.item(row)
        page = int(it.data(Qt.UserRole))
        delta = self._overrides.get(page, 0) % 360
        pm = base
        if delta:
            pm = base.transformed(QTransform().rotate(delta), Qt.SmoothTransformation)
        it.setIcon(QIcon(pm))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._render_visible_thumbs)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._render_visible_thumbs)

    # -- rotation preview ----------------------------------------------------

    def set_rotation_overrides(self, overrides: dict):
        """Set per-page extra rotation (deg) and refresh affected thumbnails."""
        changed = set(self._overrides) | set(overrides)
        self._overrides = {int(p): int(a) % 360 for p, a in overrides.items() if a}
        for row in range(self.count()):
            page = int(self.item(row).data(Qt.UserRole))
            if page in changed:
                self._apply_icon(row)

    def rotation_overrides(self) -> dict:
        return dict(self._overrides)

    # -- selection <-> spec --------------------------------------------------

    def _on_selection_changed(self):
        if self._syncing:
            return
        self.selectionPagesChanged.emit(self.selected_pages())

    def selected_pages(self) -> list:
        """Sorted 0-based indices of the selected pages."""
        return sorted(int(it.data(Qt.UserRole)) for it in self.selectedItems())

    def set_selected_pages(self, pages):
        """Select exactly ``pages`` (0-based) without re-emitting per row."""
        want = {int(p) for p in pages}
        self._syncing = True
        try:
            self.clearSelection()
            for row in range(self.count()):
                page = int(self.item(row).data(Qt.UserRole))
                if page in want:
                    self.item(row).setSelected(True)
        finally:
            self._syncing = False
        self.selectionPagesChanged.emit(self.selected_pages())

    def select_all_pages(self):
        self.selectAll()

    def clear_page_selection(self):
        self.clearSelection()
