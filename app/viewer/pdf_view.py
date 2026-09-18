"""Continuous-scroll PDF canvas (Phase 1 + 2).

A :class:`QGraphicsView` that lays every page vertically (Chrome-style), renders
lazily for visible/near pages, supports Ctrl+scroll zoom, space/middle-drag pan,
fit-width / fit-page, page navigation, and hosts the markup tools.
"""

from __future__ import annotations

from typing import Optional

import fitz

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QBrush, QKeySequence, QShortcut
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem

from ..model.annotations import (
    Annotation, AnnotationStore,
    KIND_HIGHLIGHT, KIND_PEN, KIND_COMMENT, KIND_TEXTBOX, KIND_RECT, KIND_CIRCLE,
    KIND_ARROW, KIND_LINE, KIND_CALLOUT, KIND_CLOUD, COPYABLE_KINDS,
)
from .page_item import PageItem
from .annotation_items import make_item, ANNOT_Z
from .command_stack import (
    QUndoStack, AddAnnotationCommand, RemoveAnnotationCommand,
    ModifyAnnotationCommand, ReorderCommand, capture,
)
from . import tools as T

PAGE_GAP = 14.0   # points between pages in the scroll


class PdfView(QGraphicsView):
    selectionInfo = Signal(str)
    pageChanged = Signal(int)
    requestCommentEdit = Signal(object)   # Annotation
    requestTextEdit = Signal(object)      # Annotation
    requestFillEdit = Signal(object)      # Annotation (rectangle fill)
    annotationActivated = Signal(object)  # Annotation (from a panel jump)
    requestTool = Signal(str)             # ask the window to switch tools
    regionPicked = Signal(int, object)    # page_index, QRectF (page points)
    requestOpen = Signal(str)             # a PDF was dropped onto the canvas
    requestReveal = Signal(object, str)   # Annotation, target ("todo" | "comment")
    zoomChanged = Signal(float)           # current zoom factor (1.0 == 100%)

    def __init__(self, parent=None, read_only: bool = False):
        super().__init__(parent)
        # A read-only view is a *reference* pane: it shows the same document and
        # the same marks (both views listen to one AnnotationStore, so edits made
        # in the editable view appear here live), but nothing can be created,
        # moved, restyled or deleted through it. Scrolling, zooming, rotating,
        # searching and selecting/copying text all still work.
        self.read_only = bool(read_only)
        # Page bitmaps are only worth building when the view is actually on
        # screen. The reference pane is created with its document loaded but its
        # dock hidden, so this stays False until it's first shown — otherwise it
        # would render (and hold) a full set of page bitmaps for a pane the user
        # may never open, roughly doubling the viewer's bitmap memory.
        self.render_enabled = True
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(QColor(82, 86, 89)))
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setAcceptDrops(True)         # open a dropped PDF

        self.document = None
        self.store: Optional[AnnotationStore] = None
        self.config = None
        self.undo_stack = QUndoStack(self)
        self.tool = T.ToolState()

        self._page_items: list = []
        self._finding_items: list = []   # audit overlay, below every user mark
        self._rotation = 0               # whole-document view rotation (0/90/180/270)
        self._item_by_ann: dict = {}     # ann.id -> graphics item
        self._zoom = 1.0
        self._panning = False
        self._space_down = False
        self._pan_start = QPointF()

        # interactive draft state
        self._draft = None
        self._draft_page = None
        self._draft_start = None
        self._erasing = False
        self._erase_macro_open = False
        # revision-cloud polygon in progress (click-to-add vertices)
        self._cloud_pts = None            # list[(lx, ly)] or None
        self._cloud_page = None           # (pno, page_item)
        self._cloud_press = None          # (scene_pt) to tell a click from a drag
        self._cloud_rect = False          # Shift+drag -> rectangular cloud
        # callout in progress: arrow-then-box, placed with three clicks
        #   0 idle -> 1 tip placed (rubber-banding the arrow)
        #          -> 2 arrow placed (rubber-banding the box) -> commit
        self._co_stage = 0
        self._co_tip = None               # (lx, ly) the arrow points AT
        self._co_tail = None              # (lx, ly) arrow end == box corner
        self._co_page = None              # (pno, page_item)
        # copy / paste
        self._obj_clip = []               # list of Annotation dicts (whole-mark copy)
        self._obj_paste_n = 0             # cascading paste offset counter
        self._fmt_clip = None             # {"kind": str, "style": dict} for format paint
        # synchronous prompt for *new* comment/text-box text, set by the window.
        # signature: prompt(ann, is_textbox) -> (accepted: bool, text, todo)
        self.new_text_prompt = None
        # one-shot: skip the existing-mark prompt on the next draw press (set
        # after the user chose "Draw new", so placing the object isn't re-prompted)
        self._suppress_existing_prompt = False
        # prompt when a drawing tool clicks an existing mark, set by the window.
        # signature: prompt(ann) -> "edit" | "new" | "cancel"
        self.existing_mark_prompt = None
        # region-pick mode (for the sheet-number / crop wizards)
        self._region_pick = False
        self._region_item = None
        self._region_page = None
        self._region_start = None

        # text selection (Chrome-style) in Select mode
        self._text_selecting = False
        self._text_sel_page = None       # (pno, page_item)
        self._text_sel_start = None      # (lx, ly) in page points
        self._text_words = []            # cached words for the page being selected
        self._text_sel_items = []        # highlight QGraphicsRectItems
        self._selected_text = ""

        # in-document search (Ctrl+F)
        self._search_bar = None
        self._search_matches = []        # [(pno, fitz.Rect)] — display coords
        self._search_hits = []           # rich Match records, same order
        self._search_capped = False
        self._search_index = -1
        self._search_items = []          # highlight QGraphicsRectItems
        self._searcher = None            # DocumentSearch engine, per document

        # Ctrl+C copies the selected mark(s), or the text selection (view focus)
        copy_sc = QShortcut(QKeySequence.Copy, self)
        copy_sc.setContext(Qt.WidgetWithChildrenShortcut)
        copy_sc.activated.connect(self.copy_selection)
        self._copy_sc = copy_sc
        # Ctrl+V pastes copied marks
        paste_sc = QShortcut(QKeySequence.Paste, self)
        paste_sc.setContext(Qt.WidgetWithChildrenShortcut)
        paste_sc.activated.connect(self.paste_clipboard)
        self._paste_sc = paste_sc

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(60)
        self._render_timer.timeout.connect(self._render_visible)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # -- properties ----------------------------------------------------------

    @property
    def select_mode(self) -> bool:
        # Drives whether marks are movable/selectable and whether their items
        # offer edit actions — always off in a read-only reference pane.
        return self.tool.is_select() and not self.read_only

    def push_command(self, cmd) -> None:
        # Backstop for the read-only reference pane: every edit in this view
        # funnels through here, so guarding it makes "a read-only view never
        # changes the document" hold structurally, not just because each of the
        # individual entry points remembers to check.
        if self.read_only:
            return
        self.undo_stack.push(cmd)

    # -- document lifecycle --------------------------------------------------

    def set_document(self, document, config=None) -> None:
        self.document = document
        self.store = document.store
        self.config = config
        self._scene.clear()
        self._page_items = []
        self._item_by_ann = {}
        self.undo_stack.clear()
        # scene.clear() destroyed the PageItems — drop any in-progress draw state
        # that still references them (a half-drawn cloud polygon survives between
        # clicks and would crash on the next click against a deleted page).
        self._draft = None
        self._draft_page = None
        self._cloud_pts = None
        self._cloud_page = None
        self._cloud_press = None
        # a half-placed callout still references the destroyed PageItems
        self._co_stage = 0
        self._co_tip = self._co_tail = self._co_page = None
        # scene.clear() destroyed any selection/search overlays — reset trackers
        self._text_sel_items = []
        self._selected_text = ""
        self._text_selecting = False
        self._search_items = []
        self._search_matches = []
        self._search_hits = []
        self._search_index = -1
        self._finding_items = []
        # a fresh engine for the new document (the old page index is stale);
        # the search panel itself deliberately stays open across loads
        from .doc_search import DocumentSearch
        self._searcher = DocumentSearch(document.fitz_doc)

        self._rotation = 0
        for pno in range(document.page_count):
            item = PageItem(document, pno, 0.0)
            self._scene.addItem(item)
            self._page_items.append(item)
        self._layout_pages()

        # build items for pre-loaded annotations
        for ann in self.store.all():
            self._add_item_for(ann)
        self.store.add_listener(self._on_store_event)

        QTimer.singleShot(0, self.fit_width)
        QTimer.singleShot(0, self._render_visible)
        # the search panel survives a document switch: re-run its query so the
        # highlights and the match index follow into the new file
        # (isHidden, not isVisible: the latter is False whenever the window
        # itself isn't shown yet — e.g. during startup restore or in tests)
        if self._search_bar is not None and not self._search_bar.isHidden():
            q = self._search_bar.input.text().strip()
            if q:
                QTimer.singleShot(0, lambda: self.run_search(q))

    # -- page layout / rotation ---------------------------------------------

    def _page_scene_rect(self, item) -> QRectF:
        """The page's own rect in scene coords (honours its rotation), excluding
        child marks/shadow — used for layout, culling and hit-testing."""
        return item.mapToScene(item.rect()).boundingRect()

    def _layout_pages(self) -> None:
        """Stack pages vertically, applying the current view rotation to each.
        Annotation items are children of their page, so they rotate and stay
        aligned with the page automatically — nothing is written to disk."""
        from PySide6.QtGui import QTransform
        rot = QTransform()
        rot.rotate(self._rotation)
        mapped = [rot.mapRect(QRectF(0, 0, it.pdf_w, it.pdf_h)) for it in self._page_items]
        max_w = max([m.width() for m in mapped], default=1.0)
        top = 0.0
        for item, mr in zip(self._page_items, mapped):
            item.setRotation(self._rotation)
            x = (max_w - mr.width()) / 2.0          # centre pages horizontally
            item.setPos(x - mr.left(), top - mr.top())
            top += mr.height() + PAGE_GAP
        self._scene.setSceneRect(0, 0, max_w, max(top - PAGE_GAP, 1.0))

    def rotate_view(self, delta: int) -> None:
        """Rotate the whole document in the viewer by ``delta`` degrees (in
        memory only — the file on disk is never modified). Marks rotate with
        their page and snap back exactly when rotated the other way."""
        if not self._page_items:
            return
        self._rotation = (self._rotation + int(delta)) % 360
        self._layout_pages()
        self.fit_width()
        self._render_visible()

    @property
    def rotation(self) -> int:
        return self._rotation

    # -- rendering -----------------------------------------------------------

    def _visible_scene_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _render_visible(self) -> None:
        if not self._page_items or not self.render_enabled:
            return
        vis = self._visible_scene_rect()
        margin = vis.height()  # render one screenful above/below
        lo, hi = vis.top() - margin, vis.bottom() + margin
        # Render at the actual zoom (up to the 8x set_zoom ceiling) so the page
        # stays crisp past 400%; PageItem.render caps the raster per-page by a
        # pixel budget so a huge sheet can't blow up memory.
        scale = max(1.0, self._zoom)
        for item in self._page_items:
            r = self._page_scene_rect(item)
            if r.bottom() >= lo and r.top() <= hi:
                item.render(scale)
            elif item.is_rendered() and (r.bottom() < vis.top() - 4 * margin
                                         or r.top() > vis.bottom() + 4 * margin):
                item.clear_render()
        self._emit_current_page()

    def set_render_enabled(self, on: bool) -> None:
        """Turn page-bitmap rendering on or off.

        Turning it off frees the bitmaps this view is holding — used to keep the
        reference pane free while its dock is hidden. Turning it on schedules a
        fresh render of whatever is in view.
        """
        self.render_enabled = bool(on)
        if self.render_enabled:
            self._render_timer.start()
            return
        for item in self._page_items:
            if item.is_rendered():
                item.clear_render()

    def _on_scroll(self, *_):
        self._render_timer.start()

    def _emit_current_page(self) -> None:
        vis = self._visible_scene_rect()
        mid = vis.center().y()
        for i, item in enumerate(self._page_items):
            r = self._page_scene_rect(item)
            if r.top() <= mid <= r.bottom():
                self.pageChanged.emit(i)
                return

    # -- zoom / fit ----------------------------------------------------------

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.1, min(zoom, 8.0))
        self._zoom = zoom
        self.resetTransform()
        self.scale(zoom, zoom)
        self._render_timer.start()
        self.zoomChanged.emit(zoom)

    def zoom_in(self):
        self.set_zoom(self._zoom * 1.25)

    def zoom_out(self):
        self.set_zoom(self._zoom / 1.25)

    def fit_width(self):
        if not self._page_items:
            return
        page_w = self._page_scene_rect(self._page_items[0]).width()  # displayed width
        avail = self.viewport().width() - 24
        if page_w > 0:
            self.set_zoom(avail / page_w)

    def fit_page(self):
        if not self._page_items:
            return
        r = self._page_scene_rect(self._page_items[0])  # displayed size (rotated)
        aw = self.viewport().width() - 24
        ah = self.viewport().height() - 24
        if r.width() > 0 and r.height() > 0:
            self.set_zoom(min(aw / r.width(), ah / r.height()))

    def go_to_page(self, page_no: int):
        if 0 <= page_no < len(self._page_items):
            r = self._page_scene_rect(self._page_items[page_no])
            self.centerOn(r.center().x(), r.top() + 20)
            self._render_timer.start()

    def go_to_location(self, page_no: int, x: float, y: float):
        """Centre on a page-local point (PDF points) — used to jump a wire /
        component row to its spot on the drawing, with a brief pulse marker."""
        if not (0 <= page_no < len(self._page_items)):
            return
        page = self._page_items[page_no]
        self.centerOn(page.mapToScene(QPointF(x, y)))
        self._render_timer.start()
        self._pulse_at(page, x, y)

    def _pulse_at(self, page, x: float, y: float):
        """A short-lived ring drawn on the page to draw the eye to a jump target."""
        from PySide6.QtWidgets import QGraphicsEllipseItem
        from PySide6.QtGui import QPen
        old = getattr(self, "_pulse_item", None)
        if old is not None:
            try:
                self._scene.removeItem(old)
            except Exception:
                pass
        ring = QGraphicsEllipseItem(-14, -14, 28, 28, page)
        ring.setPos(x, y)
        ring.setPen(QPen(QColor(232, 119, 46), 2.0))
        ring.setBrush(QBrush(QColor(232, 119, 46, 60)))
        ring.setZValue(80)
        self._pulse_item = ring
        QTimer.singleShot(900, lambda: self._clear_pulse(ring))

    def _clear_pulse(self, ring):
        try:
            self._scene.removeItem(ring)
        except Exception:
            pass
        if getattr(self, "_pulse_item", None) is ring:
            self._pulse_item = None

    # -- events --------------------------------------------------------------

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
            self.set_zoom(self._zoom * factor)
            event.accept()
        else:
            super().wheelEvent(event)

    # -- drag & drop (open a dropped PDF) ------------------------------------

    @staticmethod
    def _dropped_pdf(event) -> str:
        md = event.mimeData()
        if md is not None and md.hasUrls():
            for u in md.urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf"):
                    return u.toLocalFile()
        return ""

    def dragEnterEvent(self, event):
        if self._dropped_pdf(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._dropped_pdf(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        path = self._dropped_pdf(event)
        if path:
            self.requestOpen.emit(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def keyPressEvent(self, event):
        # finishing an in-progress revision-cloud polygon
        if self._cloud_pts is not None and event.key() in (
                Qt.Key_Return, Qt.Key_Enter):
            self._cloud_finish()
            event.accept()
            return
        if event.key() == Qt.Key_Space:
            self._space_down = True
            self.setCursor(Qt.OpenHandCursor)
        elif event.key() == Qt.Key_Delete:
            self.delete_selected()
        elif event.key() == Qt.Key_Escape:
            self.cancel_action()
        super().keyPressEvent(event)

    def cancel_action(self):
        """Abort an in-progress draw/erase/region-pick and drop any preview."""
        # Esc in the canvas cancels drawing only. The search panel is closed
        # from its own ✕ or Esc *inside* it — canvas events used to keep
        # dismissing it mid-search.
        if self._region_pick or self._region_item is not None:
            self.cancel_region_pick()
        if self._cloud_pts is not None:
            self._cloud_cancel()
        if self._co_stage:
            self._callout_cancel()
        if self._draft is not None:
            self._draft = None
            self._clear_preview()
        if self._erasing:
            self._end_erase()
        self._suppress_existing_prompt = False
        self._clear_text_selection()
        self._scene.clearSelection()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._space_down = False
            self.unsetCursor()
        super().keyReleaseEvent(event)

    def contextMenuEvent(self, event):
        # a right-click is not the placing gesture, so drop any armed "draw new"
        self._suppress_existing_prompt = False
        # A mark under the cursor shows its own menu; on empty canvas offer Paste.
        scene_pt = self.mapToScene(event.pos())
        if self.read_only or self._annotation_item_at(scene_pt) is not None \
                or not self._obj_clip:
            super().contextMenuEvent(event)
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        n = len(self._obj_clip)
        act = menu.addAction(f"Paste {n} mark{'s' if n != 1 else ''} here")
        if menu.exec(event.globalPos()) is act:
            self._paste_at(scene_pt)
        event.accept()

    def _page_at_scene(self, scene_pt: QPointF):
        for i, item in enumerate(self._page_items):
            if self._page_scene_rect(item).contains(scene_pt):
                return i, item
        return None, None

    # -- region pick (wizards) ----------------------------------------------

    def start_region_pick(self):
        """Enter a mode where the next left-drag selects a rectangular region
        (emitted via ``regionPicked``) instead of creating a mark.  Panning and
        scrolling stay available for navigation."""
        self._region_pick = True
        self.viewport().setCursor(Qt.CrossCursor)

    def cancel_region_pick(self):
        self._region_pick = False
        self.viewport().unsetCursor()
        if self._region_item is not None:
            self._scene.removeItem(self._region_item)
            self._region_item = None
        self._region_page = None
        self._region_start = None

    def _region_begin(self, scene_pt):
        from PySide6.QtWidgets import QGraphicsRectItem
        from PySide6.QtGui import QPen, QColor
        pno, page = self._page_at_scene(scene_pt)
        if page is None:
            return False
        self._region_page = (pno, page)
        _lp = page.mapFromScene(scene_pt)
        self._region_start = (_lp.x(), _lp.y())
        self._region_item = QGraphicsRectItem(page)
        self._region_item.setZValue(60)
        pen = QPen(QColor(30, 120, 230), 0, Qt.DashLine)
        self._region_item.setPen(pen)
        from PySide6.QtGui import QBrush
        self._region_item.setBrush(QBrush(QColor(30, 120, 230, 40)))
        return True

    def _region_update(self, scene_pt):
        if self._region_item is None:
            return
        _, page = self._region_page
        _lp = page.mapFromScene(scene_pt); lx, ly = _lp.x(), _lp.y()
        sx, sy = self._region_start
        self._region_item.setRect(min(sx, lx), min(sy, ly), abs(lx - sx), abs(ly - sy))

    def _region_finish(self):
        from PySide6.QtCore import QRectF
        if self._region_item is None:
            return
        r = self._region_item.rect()
        pno = self._region_page[0]
        self._scene.removeItem(self._region_item)
        self._region_item = None
        self._region_pick = False
        self.viewport().unsetCursor()
        if r.width() >= 4 and r.height() >= 4:
            self.regionPicked.emit(pno, QRectF(r))

    def mousePressEvent(self, event):
        # pan with middle button or space-drag
        if event.button() == Qt.MiddleButton or (self._space_down and event.button() == Qt.LeftButton):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if self._region_pick and event.button() == Qt.LeftButton:
            scene_pt = self.mapToScene(event.position().toPoint())
            if self._region_begin(scene_pt):
                event.accept()
                return

        if event.button() == Qt.LeftButton and self.tool.current == T.TOOL_CALLOUT:
            # callout is placed with clicks (arrow target -> arrow end -> box),
            # not a drag, so it never goes through _begin_draft
            scene_pt = self.mapToScene(event.position().toPoint())
            if self._callout_click(scene_pt):
                event.accept()
                return

        if event.button() == Qt.LeftButton and self.tool.current == T.TOOL_CLOUD:
            # cloud is press-drag (freehand, or Shift+drag = rectangle) OR
            # click-to-add-vertices (polygon); decide on move/release, so just
            # record the press (and whether Shift picks the rectangle mode) here
            self._cloud_press = self.mapToScene(event.position().toPoint())
            self._cloud_rect = bool(event.modifiers() & Qt.ShiftModifier)
            event.accept()
            return

        if event.button() == Qt.LeftButton and not self.tool.is_select():
            scene_pt = self.mapToScene(event.position().toPoint())
            if self._begin_draft(scene_pt):
                event.accept()
                return

        # Select tool: drag on empty page area selects text (Chrome-style).
        # But a click on a mark — or on one of its resize/rotate grips (which can
        # sit *outside* the mark's box, e.g. the rotate grip above it) — must act
        # on the mark, never start a text selection that would steal the gesture.
        if event.button() == Qt.LeftButton and self.tool.is_select():
            scene_pt = self.mapToScene(event.position().toPoint())
            on_mark = self._annotation_item_at(scene_pt) is not None
            on_grip = self._grip_item_at(scene_pt)
            if not on_mark and not on_grip:
                pno, page = self._page_at_scene(scene_pt)
                if page is not None:
                    self._scene.clearSelection()
                    _lp = page.mapFromScene(scene_pt)
                    self._begin_text_selection(pno, page, _lp.x(), _lp.y())
                    event.accept()
                    return
            else:
                self._clear_text_selection()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        if self._text_selecting and (event.buttons() & Qt.LeftButton):
            scene_pt = self.mapToScene(event.position().toPoint())
            _, page = self._text_sel_page
            _lp = page.mapFromScene(scene_pt); lx, ly = _lp.x(), _lp.y()
            self._update_text_selection(lx, ly)
            event.accept()
            return
        if self._region_item is not None and (event.buttons() & Qt.LeftButton):
            self._region_update(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        if self._co_stage and self._co_page is not None:
            _, page = self._co_page
            _lp = page.mapFromScene(self.mapToScene(event.position().toPoint()))
            self._callout_preview((_lp.x(), _lp.y()))
            event.accept()
            return
        if self._erasing and (event.buttons() & Qt.LeftButton):
            self._erase_at(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        if self._draft is not None:
            scene_pt = self.mapToScene(event.position().toPoint())
            self._update_draft(scene_pt)
            event.accept()
            return
        if (self.tool.current == T.TOOL_CLOUD
                and (event.buttons() & Qt.LeftButton)):
            if self._cloud_on_move(self.mapToScene(event.position().toPoint())):
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.OpenHandCursor if self._space_down else Qt.ArrowCursor)
            event.accept()
            return
        if self._text_selecting:
            self._text_selecting = False   # keep the highlight + copied text
            event.accept()
            return
        if self._region_item is not None:
            self._region_finish()
            event.accept()
            return
        if self._erasing:
            self._end_erase()
            event.accept()
            return
        if self._draft is not None:
            was_cloud = self._draft.kind == KIND_CLOUD
            self._finish_draft()
            if was_cloud:
                self._cloud_press = None   # freehand done; no trailing vertex
            event.accept()
            return
        if self.tool.current == T.TOOL_CLOUD:
            self._cloud_on_release(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- draft creation ------------------------------------------------------

    def _annotation_item_at(self, scene_pt: QPointF):
        """Return the topmost existing annotation item under a scene point."""
        for it in self._scene.items(scene_pt):
            ann = getattr(it, "ann", None)
            if ann is not None:
                return it
        return None

    def _grip_item_at(self, scene_pt: QPointF) -> bool:
        """True if a resize/rotate grip is under the point (so a click there
        should resize/rotate the mark, not start a text selection)."""
        return any(getattr(it, "_is_grip", False)
                   for it in self._scene.items(scene_pt))

    def _begin_draft(self, scene_pt: QPointF) -> bool:
        if self.read_only:
            return False
        # The "Draw new" one-shot is consumed by *any* draw press, even one that
        # misses a page — otherwise a stray off-page click would leave it armed
        # and silently swallow a later edit/draw-new prompt.
        suppress = self._suppress_existing_prompt
        self._suppress_existing_prompt = False
        pno, page = self._page_at_scene(scene_pt)
        if page is None:
            return False
        _lp = page.mapFromScene(scene_pt); lx, ly = _lp.x(), _lp.y()
        self._draft_page = (pno, page)
        self._draft_start = (lx, ly)
        author = self.config.your_name if self.config else ""
        tool = self.tool.current

        # Clicking an existing mark with a drawing tool: ask edit vs draw-new.
        # The prompt is a one-shot: after "Draw new", the *next* press draws
        # without re-asking, so the modal never interrupts the placing gesture.
        if tool != T.TOOL_ERASER:
            existing = self._annotation_item_at(scene_pt)
            if existing is not None and not suppress:
                choice = "new"
                if self.existing_mark_prompt is not None:
                    choice = self.existing_mark_prompt(existing.ann)
                if choice == "cancel":
                    return True
                if choice == "edit":
                    self.requestTool.emit(T.TOOL_SELECT)
                    existing.setSelected(True)
                    return True
                # choice == "new": don't draw on this modal-interrupted press —
                # let the user press again to place the object, without a re-prompt
                self._suppress_existing_prompt = True
                return True

        if tool == T.TOOL_COMMENT:
            ann = Annotation(page=pno, kind=KIND_COMMENT, rect=(lx, ly, lx + 18, ly + 18),
                             author=author, is_todo=self._default_todo())
            if self.new_text_prompt is not None:
                ok, text, todo = self.new_text_prompt(ann, False)
                if not ok:
                    return True  # cancelled -> never added to the document
                ann.text = text
                ann.is_todo = todo
            self._commit_new(ann)
            return True
        if tool == T.TOOL_PEN:
            self._draft = Annotation(page=pno, kind=KIND_PEN, points=[(lx, ly)],
                                     color=self.tool.pen_color, width=self.tool.pen_width,
                                     author=author)
            return True
        if tool in (T.TOOL_HIGHLIGHT, T.TOOL_RECT, T.TOOL_CIRCLE, T.TOOL_ARROW,
                    T.TOOL_LINE, T.TOOL_TEXTBOX, T.TOOL_CALLOUT):
            kind = {T.TOOL_HIGHLIGHT: KIND_HIGHLIGHT, T.TOOL_RECT: KIND_RECT,
                    T.TOOL_CIRCLE: KIND_CIRCLE,
                    T.TOOL_ARROW: KIND_ARROW, T.TOOL_LINE: KIND_LINE,
                    T.TOOL_TEXTBOX: KIND_TEXTBOX,
                    T.TOOL_CALLOUT: KIND_CALLOUT}[tool]
            text_like = kind in (KIND_TEXTBOX, KIND_CALLOUT)
            color = (self.tool.highlight_color if kind == KIND_HIGHLIGHT else
                     self.tool.text_color if text_like else self.tool.shape_color)
            fill, fill_op = None, 1.0
            if kind in (KIND_RECT, KIND_CIRCLE):
                fill, fill_op = self.tool.shape_fill, self.tool.shape_fill_opacity
            elif text_like:
                fill, fill_op = self.tool.text_fill, self.tool.text_fill_opacity
            self._draft = Annotation(page=pno, kind=kind, rect=(lx, ly, lx, ly),
                                     color=color, author=author,
                                     width=self.tool.shape_width,
                                     font_size=self.tool.font_size,
                                     bold=self.tool.bold, italic=self.tool.italic,
                                     opacity=self.tool.highlight_opacity,
                                     fill_color=fill, fill_opacity=fill_op)
            return True
        if tool == T.TOOL_ERASER:
            self._erasing = True
            self._erase_macro_open = False
            self._erase_at(scene_pt)
            return True
        return False

    def _update_draft(self, scene_pt: QPointF):
        if self._draft is None:
            return
        _, page = self._draft_page
        _lp = page.mapFromScene(scene_pt); lx, ly = _lp.x(), _lp.y()
        if self._draft.kind == KIND_PEN:
            self._draft.points.append((lx, ly))
        elif self._draft.kind == KIND_CLOUD and self._cloud_rect:
            # rectangle mode: the four bbox corners follow the drag
            sx, sy = self._draft_start
            self._draft.points = [(sx, sy), (lx, sy), (lx, ly), (sx, ly)]
        elif self._draft.kind == KIND_CLOUD:
            # thin the freehand path so the scallop generator stays cheap
            if self._draft.points:
                px, py = self._draft.points[-1]
                if abs(lx - px) + abs(ly - py) < 6:
                    return
            self._draft.points.append((lx, ly))
        else:
            sx, sy = self._draft_start
            self._draft.rect = (sx, sy, lx, ly)
        self._refresh_preview()

    def _refresh_preview(self):
        # cheap live preview: rebuild the draft item (drawn above the page)
        self._clear_preview()
        item = make_item(self._draft, self)
        if item is not None:
            _, page = self._draft_page
            item.setParentItem(page)
            item.setZValue(12)
            item.setOpacity(0.7)
            self._item_by_ann["__draft__"] = item

    def _clear_preview(self):
        prev = self._item_by_ann.pop("__draft__", None)
        if prev is not None:
            self._scene.removeItem(prev)

    def _finish_draft(self):
        draft = self._draft
        self._draft = None
        if draft is None:
            self._clear_preview()
            return
        # discard degenerate marks
        degenerate = draft.kind == KIND_PEN and len(draft.points) < 2
        if draft.kind == KIND_CLOUD and len(draft.points) < 3:
            degenerate = True
        if draft.kind in (KIND_HIGHLIGHT, KIND_RECT, KIND_CIRCLE, KIND_ARROW,
                          KIND_LINE, KIND_TEXTBOX, KIND_CALLOUT):
            x0, y0, x1, y1 = draft.rect
            if abs(x1 - x0) < 3 and abs(y1 - y0) < 3:
                degenerate = True
            elif draft.kind not in (KIND_ARROW, KIND_LINE):
                draft.rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        if degenerate:
            self._clear_preview()
            return

        # text boxes / callouts: prompt for text *before* committing (keep the
        # live preview visible meanwhile); a cancel discards the mark entirely.
        if draft.kind in (KIND_TEXTBOX, KIND_CALLOUT):
            if draft.kind == KIND_CALLOUT and draft.callout_point is None:
                x0, y0, x1, y1 = draft.rect
                draft.callout_point = (min(x0, x1) - 36.0, max(y0, y1) + 36.0)
            draft.is_todo = self._default_todo()
            ok, text, todo = (True, "", draft.is_todo)
            if self.new_text_prompt is not None:
                ok, text, todo = self.new_text_prompt(draft, True)
            self._clear_preview()
            if not ok:
                return
            draft.text = text
            draft.is_todo = todo
            self._commit_new(draft)
            return

        self._clear_preview()
        self._commit_new(draft)

    def _default_todo(self) -> bool:
        return bool(self.config and getattr(self.config, "treat_all_as_todo", False))

    def _commit_new(self, ann: Annotation):
        if self.read_only:
            return
        self._assign_top_z(ann)
        self.push_command(AddAnnotationCommand(self, ann, f"Add {ann.kind}"))

    # -- revision cloud (freehand drag OR click-polygon) ---------------------

    def mouseDoubleClickEvent(self, event):
        if (self.tool.current == T.TOOL_CLOUD and event.button() == Qt.LeftButton
                and self._cloud_pts):
            self._cloud_press = None
            self._cloud_finish()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _cloud_on_move(self, scene_pt: QPointF) -> bool:
        """A drag with the cloud tool (and no polygon under way) starts a
        freehand cloud.  Returns True when the gesture is handled."""
        if self._cloud_press is None or self._cloud_pts:
            return True  # mid-polygon: ignore drags (vertices are click-placed)
        moved = (scene_pt - self._cloud_press).manhattanLength()
        if moved <= 6:
            return True  # not yet a drag
        pno, page = self._page_at_scene(self._cloud_press)
        if page is None:
            return False
        sp = page.mapFromScene(self._cloud_press)
        cp = page.mapFromScene(scene_pt)
        author = self.config.your_name if self.config else ""
        self._draft_page = (pno, page)
        self._draft_start = (sp.x(), sp.y())
        if self._cloud_rect:
            pts = [(sp.x(), sp.y()), (cp.x(), sp.y()),
                   (cp.x(), cp.y()), (sp.x(), cp.y())]
        else:
            pts = [(sp.x(), sp.y()), (cp.x(), cp.y())]
        self._draft = Annotation(page=pno, kind=KIND_CLOUD, points=pts,
                                 color=self.tool.shape_color,
                                 width=self.tool.shape_width, author=author)
        self._refresh_preview()
        return True

    def _cloud_on_release(self, scene_pt: QPointF):
        """A click with the cloud tool places / closes a polygon vertex."""
        if self._cloud_press is None:
            return  # already consumed (e.g. by a double-click finish)
        self._cloud_press = None
        pno, page = self._page_at_scene(scene_pt)
        if page is None:
            return
        lp = page.mapFromScene(scene_pt)
        pt = (lp.x(), lp.y())
        if self._cloud_pts and self._cloud_page and self._cloud_page[0] == pno:
            first_scene = self._cloud_page[1].mapToScene(QPointF(*self._cloud_pts[0]))
            if (len(self._cloud_pts) >= 3
                    and (scene_pt - first_scene).manhattanLength() < 12):
                self._cloud_finish()
                return
            self._cloud_pts.append(pt)
        else:
            self._cloud_pts = [pt]
            self._cloud_page = (pno, page)
        self._show_cloud_preview()

    def _cloud_finish(self):
        pts = self._cloud_pts
        page_info = self._cloud_page
        self._clear_cloud_preview()
        self._cloud_pts = None
        self._cloud_page = None
        if not pts or len(pts) < 3 or page_info is None:
            return
        author = self.config.your_name if self.config else ""
        ann = Annotation(page=page_info[0], kind=KIND_CLOUD, points=list(pts),
                         color=self.tool.shape_color, width=self.tool.shape_width,
                         author=author)
        self._commit_new(ann)

    # -- callout: arrow first, then the box (three clicks) -------------------

    def _callout_click(self, scene_pt: QPointF) -> bool:
        """Advance the arrow-then-box placement. Returns True if handled."""
        if self.read_only:
            return False
        pno, page = self._page_at_scene(scene_pt)
        if self._co_stage == 0:
            if page is None:
                return False
            _lp = page.mapFromScene(scene_pt)
            self._co_page = (pno, page)
            self._co_tip = (_lp.x(), _lp.y())      # what the arrow points AT
            self._co_tail = self._co_tip
            self._co_stage = 1
            self._callout_preview(self._co_tip)
            return True
        if page is None or self._co_page is None:
            return True                             # ignore clicks off the page
        _, co_page = self._co_page
        _lp = co_page.mapFromScene(scene_pt)
        pt = (_lp.x(), _lp.y())
        if self._co_stage == 1:
            self._co_tail = pt                      # arrow ends here…
            self._co_stage = 2                      # …and the box starts here
            self._callout_preview(pt)
            return True
        self._callout_commit(pt)
        return True

    def _callout_preview(self, cursor):
        """Stage 1 previews the arrow; stage 2 previews the box + its leader."""
        if self._co_page is None:
            return
        pno, page = self._co_page
        author = (self.config.your_name if self.config else "") or ""
        if self._co_stage == 1:
            tx, ty = self._co_tip
            draft = Annotation(page=pno, kind=KIND_ARROW,
                               rect=(cursor[0], cursor[1], tx, ty),
                               color=self.tool.shape_color, author=author,
                               width=self.tool.shape_width)
        else:
            sx, sy = self._co_tail
            draft = Annotation(
                page=pno, kind=KIND_CALLOUT,
                rect=(min(sx, cursor[0]), min(sy, cursor[1]),
                      max(sx, cursor[0]), max(sy, cursor[1])),
                callout_point=self._co_tip, color=self.tool.text_color,
                author=author, width=self.tool.shape_width,
                font_size=self.tool.font_size, bold=self.tool.bold,
                italic=self.tool.italic, fill_color=self.tool.text_fill,
                fill_opacity=self.tool.text_fill_opacity)
        self._draft = draft
        self._draft_page = self._co_page
        self._refresh_preview()

    def _callout_commit(self, corner):
        sx, sy = self._co_tail
        x0, y0 = min(sx, corner[0]), min(sy, corner[1])
        x1, y1 = max(sx, corner[0]), max(sy, corner[1])
        if abs(x1 - x0) < 3 and abs(y1 - y0) < 3:
            return                                  # keep drawing; box too small
        draft = self._draft
        self._callout_cancel(keep_draft=True)
        if draft is None:
            return
        draft.rect = (x0, y0, x1, y1)
        draft.is_todo = self._default_todo()
        ok, text, todo = (True, "", draft.is_todo)
        if self.new_text_prompt is not None:
            ok, text, todo = self.new_text_prompt(draft, True)
        self._clear_preview()
        if not ok:
            return
        draft.text = text
        draft.is_todo = todo
        self._commit_new(draft)

    def _callout_cancel(self, keep_draft: bool = False):
        self._co_stage = 0
        self._co_tip = None
        self._co_tail = None
        self._co_page = None
        self._draft = None
        self._draft_page = None
        if not keep_draft:
            self._clear_preview()

    def _cloud_cancel(self):
        self._clear_cloud_preview()
        self._cloud_pts = None
        self._cloud_page = None
        self._cloud_press = None
        self._cloud_rect = False

    def _show_cloud_preview(self):
        self._clear_cloud_preview()
        if not self._cloud_pts or self._cloud_page is None:
            return
        pno, page = self._cloud_page
        tmp = Annotation(page=pno, kind=KIND_CLOUD, points=list(self._cloud_pts),
                         color=self.tool.shape_color, width=self.tool.shape_width)
        item = make_item(tmp, self)
        if item is not None:
            item.setParentItem(page)
            item.setZValue(12)
            item.setOpacity(0.7)
            self._item_by_ann["__cloudpreview__"] = item

    def _clear_cloud_preview(self):
        prev = self._item_by_ann.pop("__cloudpreview__", None)
        if prev is not None:
            self._scene.removeItem(prev)

    # -- erasing -------------------------------------------------------------

    def _erase_at(self, scene_pt: QPointF):
        """Remove the whole mark under the point (live), grouping a drag into a
        single undo step.  Removal is a true delete via the model, so erased
        marks are dropped from the saved PDF/sidecar, not merely hidden."""
        if self.read_only:
            return
        existing = self._annotation_item_at(scene_pt)
        if existing is None:
            return
        if not self._erase_macro_open:
            self.undo_stack.beginMacro("Erase")
            self._erase_macro_open = True
        self.push_command(RemoveAnnotationCommand(self, existing.ann, "Erase"))

    def _end_erase(self):
        self._erasing = False
        if self._erase_macro_open:
            self.undo_stack.endMacro()
            self._erase_macro_open = False

    def delete_selected(self):
        if self.read_only:
            return
        from PySide6.QtWidgets import QMessageBox
        anns = [a for a in (getattr(it, "ann", None)
                            for it in self._scene.selectedItems()) if a is not None]
        if not anns:
            return
        if len(anns) == 1:
            msg = f"Delete this {anns[0].kind}?\n\n{anns[0].snippet(80)}"
        else:
            msg = f"Delete these {len(anns)} marks?"
        resp = QMessageBox.question(self, "Delete", msg,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp != QMessageBox.Yes:
            return
        for ann in anns:
            self.push_command(RemoveAnnotationCommand(self, ann, "Delete"))

    def request_delete_annotation(self, ann: Annotation):
        """Confirm, then delete a mark from the canvas (undoable)."""
        from PySide6.QtWidgets import QMessageBox
        resp = QMessageBox.question(
            self, "Delete", f"Delete this {ann.kind}?\n\n{ann.snippet(80)}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp == QMessageBox.Yes:
            self.push_command(RemoveAnnotationCommand(self, ann, "Delete"))

    def show_comment_contents(self, ann: Annotation):
        from PySide6.QtWidgets import QMessageBox
        when = (ann.created or "")[:16].replace("T", " ")
        meta = " · ".join(p for p in (ann.author, when) if p)
        QMessageBox.information(self, "Comment contents",
                                f"{meta}\n\n{ann.text or '(no text)'}")

    def reveal_in_panel(self, ann: Annotation, target: str):
        """Ask the window to reveal this mark in the TODO list / comment sidebar."""
        self.requestReveal.emit(ann, target)

    # -- store sync ----------------------------------------------------------

    def _on_store_event(self, event: str, ann: Annotation):
        if event == "add":
            self._add_item_for(ann)
        elif event == "remove":
            self._remove_item_for(ann)
        elif event == "update":
            self._refresh_item_for(ann)

    def _add_item_for(self, ann: Annotation):
        if ann.id in self._item_by_ann:
            self._refresh_item_for(ann)
            return
        if ann.ignored and not (self.config and self.config.show_ignored):
            return
        if ann.page < 0 or ann.page >= len(self._page_items):
            return
        item = make_item(ann, self)
        if item is None:
            return
        item.setParentItem(self._page_items[ann.page])
        item.setZValue(ANNOT_Z + ann.z_order)  # marks stack above the page (z=1)
        select = self.select_mode      # False in a read-only reference pane
        item.setFlag(QGraphicsItem.ItemIsMovable, select)
        item.setFlag(QGraphicsItem.ItemIsSelectable, select)
        if hasattr(item, "_refresh_note_badge"):
            item._refresh_note_badge()
        if hasattr(item, "_refresh_done_overlay"):
            item._refresh_done_overlay()
        self._item_by_ann[ann.id] = item

    def _remove_item_for(self, ann: Annotation):
        item = self._item_by_ann.pop(ann.id, None)
        if item is not None:
            self._scene.removeItem(item)

    def _refresh_item_for(self, ann: Annotation):
        item = self._item_by_ann.get(ann.id)
        if item is None:
            self._add_item_for(ann)
            return
        if hasattr(item, "sync_from_model"):
            item.sync_from_model()
        if hasattr(item, "_refresh_note_badge"):
            item._refresh_note_badge()
        if hasattr(item, "_refresh_done_overlay"):
            item._refresh_done_overlay()
        item.setZValue(ANNOT_Z + ann.z_order)
        item.update()

    def apply_z_order(self, ann: Annotation):
        """Reflect a mark's ``z_order`` on its graphics item's stacking."""
        item = self._item_by_ann.get(ann.id)
        if item is not None:
            item.setZValue(ANNOT_Z + ann.z_order)

    def _assign_top_z(self, ann: Annotation):
        """Put a newly-created mark on top of the others on its page."""
        peers = [a for a in self.store.all()
                 if a.page == ann.page and a.id != ann.id]
        ann.z_order = max((a.z_order for a in peers), default=0.0) + 1.0

    def reorder_annotation(self, ann: Annotation, where: str):
        """Restack ``ann`` among the marks on its page (undoable).
        ``where`` is 'front' | 'back' | 'up' | 'down'."""
        if self.read_only:
            return
        # only reorder among the *visible* marks so a step never swaps with a
        # hidden (ignored/SHX) mark and appears to do nothing
        show_ignored = bool(self.config and self.config.show_ignored)
        page_marks = [a for a in self.store.on_page(ann.page, show_ignored)]
        if len(page_marks) < 2:
            return
        ordered = sorted(page_marks, key=lambda a: a.z_order)  # stable = visual order
        idx = next((i for i, a in enumerate(ordered) if a is ann), -1)
        if idx < 0:
            return
        if where == "front":
            ordered.append(ordered.pop(idx))
        elif where == "back":
            ordered.insert(0, ordered.pop(idx))
        elif where == "up" and idx < len(ordered) - 1:
            ordered[idx], ordered[idx + 1] = ordered[idx + 1], ordered[idx]
        elif where == "down" and idx > 0:
            ordered[idx], ordered[idx - 1] = ordered[idx - 1], ordered[idx]
        else:
            return
        before = {a.id: a.z_order for a in page_marks}
        after = {a.id: float(i) for i, a in enumerate(ordered)}
        if before == after:
            return
        labels = {"front": "Bring to front", "back": "Send to back",
                  "up": "Bring forward", "down": "Send backward"}
        self.push_command(ReorderCommand(self, before, after, labels[where]))

    def rebuild_all_items(self):
        for item in list(self._item_by_ann.values()):
            self._scene.removeItem(item)
        self._item_by_ann.clear()
        for ann in self.store.all():
            self._add_item_for(ann)

    # -- editing hooks (wired by main window) --------------------------------

    def edit_comment_annotation(self, ann: Annotation):
        self.requestCommentEdit.emit(ann)

    def edit_text_annotation(self, ann: Annotation):
        self.requestTextEdit.emit(ann)

    def edit_note_annotation(self, ann: Annotation):
        """Attach/edit a free note on a non-text mark (arrow, rect, …)."""
        self.requestCommentEdit.emit(ann)

    def edit_fill_annotation(self, ann: Annotation):
        """Edit a rectangle's interior fill color + opacity."""
        self.requestFillEdit.emit(ann)

    # -- panel jump ----------------------------------------------------------

    def flash_annotation(self, ann: Annotation):
        self.go_to_page(ann.page)
        x0, y0, x1, y1 = ann.rect
        page = self._page_items[ann.page]
        self.centerOn(page.mapToScene(QPointF((x0 + x1) / 2, (y0 + y1) / 2)))
        item = self._item_by_ann.get(ann.id)
        if item is not None:
            item.setSelected(True)
            self._flash_item = item
            QTimer.singleShot(700, lambda: item.setSelected(False) if item else None)

    # -- text selection (Chrome-style, in Select mode) ----------------------

    def _begin_text_selection(self, pno, page, lx, ly):
        self._clear_text_selection()
        self._text_selecting = True
        self._text_sel_page = (pno, page)
        self._text_sel_start = (lx, ly)
        self._text_words = self._visual_words(pno)

    def _visual_words(self, pno):
        """Page words with bboxes mapped into the viewer's visual coordinate
        system.  PyMuPDF returns word boxes in *unrotated* coords, but the page
        bitmap (and mouse points) are in the rotated/visual system, so we apply
        ``page.rotation_matrix`` to keep highlights aligned on rotated pages."""
        try:
            page = self.document.fitz_doc[pno]
            rm = page.rotation_matrix
            out = []
            for w in page.get_text("words"):
                r = fitz.Rect(w[0], w[1], w[2], w[3]) * rm
                r.normalize()
                out.append((r.x0, r.y0, r.x1, r.y1, w[4], w[5], w[6], w[7]))
            return out
        except Exception:
            return []

    @staticmethod
    def _word_index_at(words, lx, ly):
        """Index of the word under (lx, ly), else the nearest word; -1 if none."""
        if not words:
            return -1
        for i, w in enumerate(words):
            if w[0] <= lx <= w[2] and w[1] <= ly <= w[3]:
                return i
        best, bi = None, -1
        for i, w in enumerate(words):
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            d = (cx - lx) ** 2 + (cy - ly) ** 2
            if best is None or d < best:
                best, bi = d, i
        return bi

    def _update_text_selection(self, lx, ly):
        words = self._text_words
        if not words or self._text_sel_start is None:
            return
        sx, sy = self._text_sel_start
        i0 = self._word_index_at(words, sx, sy)
        i1 = self._word_index_at(words, lx, ly)
        if i0 < 0 or i1 < 0:
            return
        lo, hi = (i0, i1) if i0 <= i1 else (i1, i0)
        selected = words[lo:hi + 1]
        self._draw_text_selection(selected)
        self._selected_text = _words_to_text(selected)

    def _draw_text_selection(self, selected):
        from PySide6.QtWidgets import QGraphicsRectItem
        from PySide6.QtGui import QPen
        self._remove_sel_items()
        _, page = self._text_sel_page
        brush = QBrush(QColor(70, 130, 230, 80))
        for w in selected:
            r = QGraphicsRectItem(w[0], w[1], w[2] - w[0], w[3] - w[1], page)
            r.setBrush(brush)
            r.setPen(QPen(Qt.NoPen))
            r.setZValue(5)  # above the page bitmap (1), below marks (10)
            self._text_sel_items.append(r)

    def _remove_sel_items(self):
        for it in self._text_sel_items:
            self._scene.removeItem(it)
        self._text_sel_items = []

    def _clear_text_selection(self):
        self._remove_sel_items()
        self._selected_text = ""
        self._text_selecting = False
        self._text_sel_page = None
        self._text_sel_start = None

    def copy_selection(self):
        """Ctrl+C: copy the selected mark(s) if any, else the text selection."""
        marks = self._selected_copyable_marks()
        if marks:
            self.copy_marks(marks)
            return
        if self._selected_text:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._selected_text)
            self.selectionInfo.emit(f"Copied {len(self._selected_text)} characters")

    # -- copy / paste marks --------------------------------------------------

    def _selected_copyable_marks(self) -> list:
        out = []
        for it in self._scene.selectedItems():
            a = getattr(it, "ann", None)
            if a is not None and a.kind in COPYABLE_KINDS:
                out.append(a)
        return out

    def _current_page_index(self) -> int:
        """The page nearest the middle of the viewport (0 if none)."""
        if not self._page_items:
            return 0
        mid = self._visible_scene_rect().center().y()
        for i, item in enumerate(self._page_items):
            r = self._page_scene_rect(item)
            if r.top() <= mid <= r.bottom():
                return i
        return 0

    def copy_marks(self, anns: list):
        """Copy whole marks to the in-app clipboard (for paste)."""
        anns = [a for a in anns if a.kind in COPYABLE_KINDS]
        if not anns:
            return
        self._obj_clip = [a.to_dict() for a in anns]
        self._obj_paste_n = 0
        self.selectionInfo.emit(
            f"Copied {len(anns)} mark{'s' if len(anns) != 1 else ''}")

    def copy_annotation(self, ann: Annotation):
        """Right-click Copy: copy this mark, or the whole selection if it's part
        of a multi-selection."""
        sel = self._selected_copyable_marks()
        self.copy_marks(sel if (ann in sel and len(sel) > 1) else [ann])

    def can_paste(self) -> bool:
        return bool(self._obj_clip)

    def _anchor_of(self, ann: Annotation):
        """The geometric top-left of a mark (used to place a paste at the cursor)."""
        xs, ys = [], []
        x0, y0, x1, y1 = ann.rect
        if (x0, y0, x1, y1) != (0.0, 0.0, 0.0, 0.0):
            xs += [x0, x1]; ys += [y0, y1]
        for px, py in ann.points:
            xs.append(px); ys.append(py)
        if not xs:
            return 0.0, 0.0
        return min(xs), min(ys)

    def _paste_annotations(self, place):
        """Clone every clipboard mark, let ``place(ann)`` position it, and commit
        them as one undo step; the pasted marks end up selected."""
        if not self._obj_clip:
            return
        new_ids = []
        self.undo_stack.beginMacro("Paste")
        try:
            for d in self._obj_clip:
                a = Annotation.from_dict(d).clone(new_id=True)
                place(a)
                if self.config is not None and getattr(self.config, "your_name", ""):
                    a.author = self.config.your_name
                self._assign_top_z(a)          # pasted marks land on top
                self.push_command(AddAnnotationCommand(self, a, "Paste"))
                new_ids.append(a.id)
        finally:
            self.undo_stack.endMacro()
        self._scene.clearSelection()
        for aid in new_ids:
            it = self._item_by_ann.get(aid)
            if it is not None:
                it.setSelected(True)

    def paste_clipboard(self):
        """Ctrl+V: paste onto the current page, cascaded so repeated pastes don't
        stack exactly."""
        if self.read_only:
            return
        if not self._obj_clip:
            return
        self._obj_paste_n += 1
        off = 14.0 * self._obj_paste_n
        page_no = self._current_page_index()

        def place(a):
            if a.page < 0 or a.page >= len(self._page_items):
                a.page = page_no
            a.translate(off, off)
        self._paste_annotations(place)

    def _paste_at(self, scene_pt: QPointF):
        """Right-click 'Paste here': anchor the paste at the clicked point."""
        if self.read_only:
            return
        pno, page = self._page_at_scene(scene_pt)
        if page is None:
            self.paste_clipboard()
            return
        lp = page.mapFromScene(scene_pt)
        ax, ay = self._anchor_of(Annotation.from_dict(self._obj_clip[0]))
        dx, dy = lp.x() - ax, lp.y() - ay

        def place(a):
            a.page = pno
            a.translate(dx, dy)
        self._paste_annotations(place)

    # -- copy / paste formatting (format painter) ----------------------------

    def copy_format(self, ann: Annotation):
        """Remember this mark's visual style for 'paste formatting'."""
        self._fmt_clip = {"kind": ann.kind, "style": ann.style_dict()}
        self.selectionInfo.emit(f"Copied {ann.kind} formatting")

    def has_format_for(self, kind: str) -> bool:
        return bool(self._fmt_clip and self._fmt_clip.get("kind") == kind)

    def paste_format(self, ann: Annotation):
        """Apply the copied style onto a mark of the *same* kind (undoable)."""
        if self.read_only:
            return
        if not self.has_format_for(ann.kind):
            return
        before = capture(ann)
        ann.apply_style(self._fmt_clip["style"])
        after = capture(ann)
        if after != before:
            self.push_command(ModifyAnnotationCommand(
                self, ann, before, after, "Paste formatting"))

    # -- in-document search (Ctrl+F) ----------------------------------------

    def show_search(self):
        if self._search_bar is None:
            from .search_bar import SearchBar
            # Parented to the view frame, NOT the viewport: scrolling a
            # QGraphicsView calls viewport().scroll(), which drags viewport
            # children along with the content — so a viewport-parented panel
            # was carried off-screen by the very jump-to-match it triggered.
            self._search_bar = SearchBar(self, config=self.config)
            self._search_bar.queryChanged.connect(self.run_search)
            self._search_bar.nextRequested.connect(self.search_next)
            self._search_bar.prevRequested.connect(self.search_prev)
            self._search_bar.closed.connect(self.hide_search)
            self._search_bar.optionsChanged.connect(self._research_current)
            self._search_bar.matchActivated.connect(self.search_activate)
        self._position_search_bar()
        self._search_bar.show()
        self._search_bar.raise_()
        self._search_bar.focus_input()
        # Re-run any text left in the box so reopening Ctrl+F re-highlights it
        # (otherwise the stale query sat there with no matches shown).
        text = self._search_bar.input.text().strip()
        if text:
            self.run_search(text)

    def hide_search(self):
        self._clear_search_highlights()
        self._search_matches = []
        self._search_hits = []
        self._search_index = -1
        if self._search_bar is not None:
            self._search_bar.hide()
        self.setFocus()

    def _position_search_bar(self):
        if self._search_bar is None:
            return
        # viewport geometry is in view coords: hug its top-right corner, which
        # also keeps the panel clear of the vertical scrollbar
        vg = self.viewport().geometry()
        bw = self._search_bar.width()
        self._search_bar.move(max(vg.left() + 8, vg.right() - bw - 15),
                              vg.top() + 12)

    def run_search(self, query):
        self._clear_search_highlights()
        self._search_matches = []
        self._search_hits = []
        self._search_capped = False
        self._search_index = -1
        q = (query or "").strip()
        if q and self.document is not None:
            from .doc_search import (DocumentSearch, SearchOptions,
                                     BadPatternError)
            if self._searcher is None:
                self._searcher = DocumentSearch(self.document.fitz_doc)
            opts = (self._search_bar.options() if self._search_bar is not None
                    else SearchOptions())
            try:
                result = self._searcher.search(
                    q, opts,
                    store=self.store if opts.include_marks else None,
                    component_config=(self.config.component_config()
                                      if self.config else None),
                    wire_config=(self.config.wire_config()
                                 if self.config else None))
            except BadPatternError as e:
                if self._search_bar is not None:
                    self._search_bar.set_error(str(e))
                    self._search_bar.set_matches([], {})
                return
            self._search_hits = result.matches
            self._search_capped = result.capped
            rms: dict = {}                     # unrotated -> visual, per page
            for m in result.matches:
                if m.source == "text":
                    rm = rms.get(m.page)
                    if rm is None:
                        try:
                            rm = self.document.fitz_doc[m.page].rotation_matrix
                        except Exception:
                            rm = fitz.Matrix(1.0, 1.0)
                        rms[m.page] = rm
                    vr = fitz.Rect(m.rect) * rm
                else:
                    vr = fitz.Rect(m.rect)     # marks are already page-local
                vr.normalize()
                self._search_matches.append((m.page, vr))
        # fill the results index first: _focus_current_match syncs the list's
        # selection, which only works once the rows exist
        if self._search_bar is not None:
            self._search_bar.set_matches(
                self._search_hits,
                dict(getattr(self.document, "sheet_labels", None) or {}),
                self._search_capped)
        if self._search_matches:
            self._draw_search_highlights()
            self._search_index = 0
            self._focus_current_match()
        self._update_search_count()

    def _research_current(self):
        """Re-run the live query after an option toggle changed."""
        if self._search_bar is not None:
            self.run_search(self._search_bar.input.text())

    def _remember_query(self):
        if self._search_bar is not None:
            self._search_bar.remember(self._search_bar.input.text())

    def search_activate(self, i: int):
        """Jump to match ``i`` picked from the results list."""
        if not (0 <= i < len(self._search_matches)):
            return
        self._search_index = i
        self._focus_current_match()
        self._update_search_count()
        self._remember_query()
        pno, r = self._search_matches[i]
        if 0 <= pno < len(self._page_items):
            self._pulse_at(self._page_items[pno],
                           (r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0)

    def _research_if_stale(self) -> bool:
        """If there are no matches but the box still holds a query, search it
        now (lands on the first match). Returns True when it re-ran."""
        if self._search_matches or self._search_bar is None:
            return False
        q = self._search_bar.input.text().strip()
        if q:
            self.run_search(q)
            return True
        return False

    def search_next(self):
        if not self._search_matches:
            self._research_if_stale()
            return
        self._search_index = (self._search_index + 1) % len(self._search_matches)
        self._focus_current_match()
        self._update_search_count()
        self._remember_query()

    def search_prev(self):
        if not self._search_matches:
            self._research_if_stale()
            return
        self._search_index = (self._search_index - 1) % len(self._search_matches)
        self._focus_current_match()
        self._update_search_count()
        self._remember_query()

    def _draw_search_highlights(self):
        from PySide6.QtWidgets import QGraphicsRectItem
        from PySide6.QtGui import QPen
        self._clear_search_highlights()
        for pno, r in self._search_matches:
            if pno < 0 or pno >= len(self._page_items):
                self._search_items.append(None)
                continue
            page = self._page_items[pno]
            item = QGraphicsRectItem(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0, page)
            item.setBrush(QBrush(QColor(255, 213, 0, 90)))
            item.setPen(QPen(Qt.NoPen))
            item.setZValue(6)
            self._search_items.append(item)

    # -- audit findings ------------------------------------------------------

    # Findings are drawn as plain scene items rather than as Annotations, which
    # matters in three ways. They are regenerated by every audit run, so they
    # must not end up in the annotation store, which `Document.save()` bakes
    # into the .marked.pdf -- on reopen they would load back as ordinary user
    # markup and be indistinguishable from it. They sit at z=7: above the page
    # bitmap, below every user mark (z=10), so a finding structurally cannot
    # obscure something a person drew. And the eraser and hit-testing key on an
    # item's `.ann` attribute, which these deliberately do not have, so they
    # cannot be selected, moved or rubbed out by accident.
    FINDING_Z = 7

    _FINDING_COLORS = {
        "definite": (179, 38, 30),
        "potential": (154, 103, 0),
        "info": (11, 92, 173),
    }

    def draw_findings(self, findings) -> None:
        """Outline every place each finding covers.

        A finding can cover more than one, since the rule library reports a
        repeated drafting event once and names all of it. Outlining only the
        first would leave the other sheets looking clean -- which is worse than
        the un-rolled report it replaced, because the rows that used to be
        there are gone too.
        """
        from PySide6.QtWidgets import QGraphicsRectItem
        from PySide6.QtGui import QPen
        self.clear_findings()
        for f in findings or []:
            rgb = self._FINDING_COLORS.get(getattr(f, "severity", ""),
                                           (154, 103, 0))
            waived = bool(getattr(f, "waived", False))
            for place in self._places_of(f):
                pno = int(getattr(place, "page", -1) or 0)
                if not getattr(place, "has_location", False):
                    continue
                if pno < 0 or pno >= len(self._page_items):
                    continue
                page = self._page_items[pno]
                # A zero-size extent still deserves a visible target.
                w = float(getattr(place, "w", 0.0) or 0.0) or 26.0
                h = float(getattr(place, "h", 0.0) or 0.0) or 10.0
                pad = 2.5
                item = QGraphicsRectItem(float(place.x) - pad,
                                         float(place.y) - pad,
                                         w + pad * 2, h + pad * 2, page)
                pen = QPen(QColor(*rgb, 110 if waived else 235), 1.4)
                if waived:
                    pen.setStyle(Qt.DotLine)
                item.setPen(pen)
                item.setBrush(QBrush(QColor(*rgb, 18 if waived else 34)))
                item.setZValue(self.FINDING_Z)
                item.setToolTip(getattr(f, "message", ""))
                self._finding_items.append(item)

    @staticmethod
    def _places_of(f):
        """A finding's places, or the finding itself where it has none.

        Sidecars written before findings could cover more than one place carry
        no `places`, and a caller may hand this view any object with x/y.
        """
        return getattr(f, "places", None) or [f]

    def clear_findings(self) -> None:
        for it in getattr(self, "_finding_items", []):
            try:
                self._scene.removeItem(it)
            except Exception:
                pass
        self._finding_items = []

    def go_to_rect(self, page_no: int, x0: float, y0: float,
                   x1: float, y1: float) -> None:
        """Centre on a page-local rect, zooming out if it does not fit."""
        if not (0 <= page_no < len(self._page_items)):
            return
        page = self._page_items[page_no]
        cx, cy = (float(x0) + float(x1)) / 2.0, (float(y0) + float(y1)) / 2.0
        self.centerOn(page.mapToScene(QPointF(cx, cy)))
        self._render_timer.start()

    def _clear_search_highlights(self):
        for it in self._search_items:
            if it is not None:
                self._scene.removeItem(it)
        self._search_items = []

    def _focus_current_match(self):
        if not (0 <= self._search_index < len(self._search_matches)):
            return
        cur = QBrush(QColor(232, 119, 46, 170))   # orange accent
        other = QBrush(QColor(255, 213, 0, 90))    # yellow
        for i, it in enumerate(self._search_items):
            if it is not None:
                it.setBrush(cur if i == self._search_index else other)
        pno, r = self._search_matches[self._search_index]
        if 0 <= pno < len(self._page_items):
            page = self._page_items[pno]
            self.centerOn(page.mapToScene(QPointF((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)))
            self._render_timer.start()
        if self._search_bar is not None:
            self._search_bar.set_current(self._search_index)

    def _update_search_count(self):
        if self._search_bar is not None:
            n = len(self._search_matches)
            i = self._search_index + 1 if n else 0
            self._search_bar.set_count(i, n, self._search_capped)

    # -- keep the floating search bar pinned on resize ----------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._search_bar is not None and self._search_bar.isVisible():
            self._position_search_bar()


def _words_to_text(words) -> str:
    """Join selected ``get_text('words')`` tuples back into text, preserving
    line breaks (words are (x0,y0,x1,y1, text, block, line, word_no))."""
    lines = {}
    order = []
    for w in words:
        key = (w[5], w[6])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(w[4])
    return "\n".join(" ".join(lines[k]) for k in order)
