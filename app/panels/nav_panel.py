"""Navigation side panel: page thumbnails + PDF bookmarks (outline).

Lets the user jump around a set without knowing page numbers (used generally
and by the sheet-number / crop wizards).  Thumbnails render lazily so large
sets stay responsive.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QImage, QPixmap, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QLabel,
)


def _pixmap_to_qicon(pix) -> QIcon:
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
    return QIcon(QPixmap.fromImage(img.copy()))


class NavPanel(QWidget):
    """Emits ``pageActivated(page_index)`` when the user picks a page/bookmark."""

    pageActivated = Signal(int)

    THUMB_W = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self._thumb_built = set()
        self._thumb_h = int(self.THUMB_W * 1.3)   # updated per-document to the page aspect
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.tabs = QTabWidget()

        self.pages = QListWidget()
        self.pages.setViewMode(QListWidget.IconMode)
        self.pages.setIconSize(QSize(self.THUMB_W, self._thumb_h))
        self.pages.setMovement(QListWidget.Static)
        self.pages.setResizeMode(QListWidget.Adjust)
        self.pages.setWordWrap(False)
        self.pages.setUniformItemSizes(True)
        self.pages.setSpacing(8)
        self.pages.itemClicked.connect(self._on_page_clicked)
        self.pages.verticalScrollBar().valueChanged.connect(
            lambda *_: QTimer.singleShot(0, self._render_visible_thumbs))

        self.bookmarks = QTreeWidget()
        self.bookmarks.setHeaderHidden(True)
        self.bookmarks.itemClicked.connect(self._on_bookmark_clicked)

        self.tabs.addTab(self.pages, "Pages")
        self.tabs.addTab(self.bookmarks, "Bookmarks")
        lay.addWidget(self.tabs)

    # -- wiring --------------------------------------------------------------

    def set_document(self, document):
        self.document = document
        self._thumb_built = set()
        self._update_thumb_height()
        self._build_page_list()
        self._build_bookmarks()
        QTimer.singleShot(0, self._render_visible_thumbs)

    def _update_thumb_height(self):
        """Size the icon box to the page's aspect ratio so landscape drawings
        sit snug against the page number instead of floating in a tall box."""
        aspect = 1.3
        if self.document is not None and self.document.page_count:
            try:
                r = self.document.page_rect(0)
                if r.width > 0:
                    aspect = max(0.4, min(1.4, r.height / r.width))
            except Exception:
                pass
        self._thumb_h = int(self.THUMB_W * aspect)
        self.pages.setIconSize(QSize(self.THUMB_W, self._thumb_h))

    def _build_page_list(self):
        self.pages.clear()
        if self.document is None:
            return
        for i in range(self.document.page_count):
            it = QListWidgetItem(str(i + 1))
            it.setData(Qt.UserRole, i)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            it.setSizeHint(QSize(self.THUMB_W + 16, self._thumb_h + 20))
            self.pages.addItem(it)

    def _build_bookmarks(self):
        self.bookmarks.clear()
        if self.document is None:
            return
        try:
            toc = self.document.fitz_doc.get_toc() or []
        except Exception:
            toc = []
        if not toc:
            placeholder = QTreeWidgetItem(["(no bookmarks in this PDF)"])
            placeholder.setFlags(Qt.ItemIsEnabled)
            self.bookmarks.addTopLevelItem(placeholder)
            return
        stack = [(0, None)]  # (level, parent_item)
        for level, title, page in toc:
            node = QTreeWidgetItem([title])
            node.setData(0, Qt.UserRole, max(0, page - 1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            if parent is None:
                self.bookmarks.addTopLevelItem(node)
            else:
                parent.addChild(node)
            stack.append((level, node))
        self.bookmarks.expandAll()

    # -- lazy thumbnails -----------------------------------------------------

    def _render_visible_thumbs(self):
        if self.document is None:
            return
        vp = self.pages.viewport().rect()
        for row in range(self.pages.count()):
            it = self.pages.item(row)
            if row in self._thumb_built:
                continue
            rect = self.pages.visualItemRect(it)
            if rect.bottom() < -50 or rect.top() > vp.height() + 50:
                continue
            page = it.data(Qt.UserRole)
            try:
                zoom = self.THUMB_W / max(1.0, self.document.page_rect(page).width)
                pix = self.document.get_pixmap(page, zoom=max(0.05, zoom))
                it.setIcon(_pixmap_to_qicon(pix))
                self._thumb_built.add(row)
            except Exception:
                pass

    # -- interaction ---------------------------------------------------------

    def _on_page_clicked(self, item):
        page = item.data(Qt.UserRole)
        if page is not None:
            self.pageActivated.emit(int(page))

    def _on_bookmark_clicked(self, item, _col):
        page = item.data(0, Qt.UserRole)
        if page is not None:
            self.pageActivated.emit(int(page))

    def highlight_page(self, page_index: int):
        if 0 <= page_index < self.pages.count():
            self.pages.setCurrentRow(page_index)
