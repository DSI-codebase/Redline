"""Graphics items for each annotation kind (Phase 2).

Items are children of a :class:`PageItem`, so their local coordinates are PDF
points in page space.  A model :class:`Annotation` is the single source of
truth; items sync geometry/style back to it and push undo commands on edit.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import (
    QColor, QPen, QBrush, QPainterPath, QFont, QPolygonF, QPainterPathStroker,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsPathItem, QGraphicsObject,
    QGraphicsEllipseItem, QGraphicsLineItem, QStyle,
)

from ..model.annotations import (
    Annotation, KIND_HIGHLIGHT, KIND_PEN, KIND_COMMENT, KIND_TEXTBOX,
    KIND_RECT, KIND_CIRCLE, KIND_ARROW, KIND_LINE, KIND_CALLOUT, KIND_CLOUD,
    COPYABLE_KINDS,
)
from .command_stack import ModifyAnnotationCommand, capture

HANDLE = 7.0      # resize-grip size in points
ROT_ARM = 22.0    # distance of the rotate grip above the top edge

# annotation items draw above the page bitmap (which sits at z=1 in PageItem)
ANNOT_Z = 10.0


def qcolor(rgb, alpha=255) -> QColor:
    r, g, b = rgb
    return QColor(int(r * 255), int(g * 255), int(b * 255), alpha)


def fill_brush(ann):
    """Interior brush for a rect / text box, or ``None`` when there is no fill."""
    fc = getattr(ann, "fill_color", None)
    if fc is None:
        return None
    alpha = int(max(0.0, min(1.0, getattr(ann, "fill_opacity", 1.0))) * 255)
    if alpha <= 0:
        return None
    return QBrush(qcolor(fc, alpha))


class _NoteBadge(QGraphicsEllipseItem):
    """A small orange dot pinned to a mark's corner to flag that it carries a
    note (highlights, pens, arrows and rectangles don't otherwise show text)."""

    _R = 5.0

    def __init__(self, parent):
        super().__init__(-self._R, -self._R, 2 * self._R, 2 * self._R, parent)
        self.setBrush(QBrush(QColor(232, 119, 46)))
        self.setPen(QPen(QColor("white"), 1.0))
        self.setZValue(70)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setToolTip("Has a note — right-click ▸ Edit note…")


class _DoneStrike(QGraphicsLineItem):
    """A strikethrough line drawn across a mark whose TODO has been completed
    (the on-sheet counterpart to the struck-out row in the TODO audit list)."""

    def __init__(self, parent):
        super().__init__(parent)
        pen = QPen(QColor(200, 40, 40), 2.5)
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)
        self.setZValue(69)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setToolTip("TODO completed")


# --- selectable / movable base ---------------------------------------------


class _BaseMixin:
    """Shared selection, move-undo and model-sync behaviour."""

    def init_base(self, ann: Annotation, view):
        self.ann = ann
        self.view = view
        self._press_snap = None
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

    def _selectable(self) -> bool:
        return getattr(self.view, "select_mode", True)

    def mousePressEvent(self, event):
        self._press_snap = capture(self.ann)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._press_snap is not None:
            self.write_geometry_to_model()
            after = capture(self.ann)
            if after != self._press_snap:
                self.view.push_command(
                    ModifyAnnotationCommand(self.view, self.ann,
                                            self._press_snap, after, "Move"))
            self._press_snap = None

    def contextMenuEvent(self, event):
        # A read-only reference pane offers no mark actions at all — every entry
        # in this menu either edits, restyles, reorders or deletes the mark.
        if getattr(self.view, "read_only", False):
            event.ignore()
            return
        from PySide6.QtWidgets import QMenu
        ann = self.ann
        menu = QMenu()
        show_act = menu.addAction("Show comment contents") if ann.is_comment_like else None
        # Any non-text mark (highlight, pen, arrow, rectangle, …) can carry a note.
        note_act = None
        if not ann.is_comment_like:
            note_act = menu.addAction("Edit note…" if ann.has_note else "Add note…")
        # rectangles/circles have no double-click editor, so expose fill here
        fill_act = (menu.addAction("Fill…")
                    if ann.kind in (KIND_RECT, KIND_CIRCLE) else None)
        todo_act = menu.addAction("Reveal in TODO list") if ann.is_todo else None
        cmt_act = (menu.addAction("Reveal in Comments")
                   if (ann.is_comment_like or ann.has_note) else None)

        # copy / paste (whole object) + copy / paste formatting, for the kinds
        # that support it (text box, callout, rectangle, arrow, cloud)
        copy_act = fmt_copy_act = fmt_paste_act = paste_act = None
        if ann.kind in COPYABLE_KINDS:
            menu.addSeparator()
            copy_act = menu.addAction("Copy\tCtrl+C")
            fmt_copy_act = menu.addAction("Copy formatting")
            fmt_paste_act = menu.addAction("Paste formatting")
            fmt_paste_act.setEnabled(self.view.has_format_for(ann.kind))
            if self.view.can_paste():
                paste_act = menu.addAction("Paste\tCtrl+V")

        # stacking order (any mark)
        menu.addSeparator()
        order_menu = menu.addMenu("Order")
        front_act = order_menu.addAction("Bring to Front")
        up_act = order_menu.addAction("Bring Forward")
        down_act = order_menu.addAction("Send Backward")
        back_act = order_menu.addAction("Send to Back")

        menu.addSeparator()
        del_act = menu.addAction("Delete")
        chosen = menu.exec(event.screenPos())
        if chosen is None:
            pass
        elif chosen == show_act:
            self.view.show_comment_contents(ann)
        elif chosen == note_act:
            self.view.edit_note_annotation(ann)
        elif chosen == fill_act:
            self.view.edit_fill_annotation(ann)
        elif chosen == todo_act:
            self.view.reveal_in_panel(ann, "todo")
        elif chosen == cmt_act:
            self.view.reveal_in_panel(ann, "comment")
        elif chosen == copy_act:
            self.view.copy_annotation(ann)
        elif chosen == fmt_copy_act:
            self.view.copy_format(ann)
        elif chosen == fmt_paste_act:
            self.view.paste_format(ann)
        elif chosen == paste_act:
            self.view.paste_clipboard()
        elif chosen == front_act:
            self.view.reorder_annotation(ann, "front")
        elif chosen == up_act:
            self.view.reorder_annotation(ann, "up")
        elif chosen == down_act:
            self.view.reorder_annotation(ann, "down")
        elif chosen == back_act:
            self.view.reorder_annotation(ann, "back")
        elif chosen == del_act:
            self.view.request_delete_annotation(ann)
        event.accept()

    # subclasses override
    def write_geometry_to_model(self):
        pass

    def sync_from_model(self):
        pass

    def _refresh_note_badge(self):
        """Show a small badge at the corner when a non-text mark carries a note
        (comment/text-box already display their text)."""
        if self.ann.is_comment_like:
            return
        want = self.ann.has_note
        badge = getattr(self, "_note_badge", None)
        if want and badge is None:
            badge = _NoteBadge(self)
            self._note_badge = badge
        if badge is not None:
            badge.setVisible(want)
            if want:
                br = self.boundingRect()
                badge.setPos(br.right(), br.top())

    def _refresh_done_overlay(self):
        """Strike a line across the mark once its TODO is checked off, matching
        the struck-out row in the TODO audit list."""
        want = bool(getattr(self.ann, "is_todo", False)
                    and getattr(self.ann, "todo_done", False))
        line = getattr(self, "_done_strike", None)
        if want and line is None:
            line = _DoneStrike(self)
            self._done_strike = line
        if line is not None:
            line.setVisible(want)
            if want:
                br = self.boundingRect()
                y = br.center().y()
                line.setLine(br.left(), y, br.right(), y)


# --- rect-based, resizable --------------------------------------------------


class _HandleItem(QGraphicsRectItem):
    """A small resize grip living on a resizable parent."""

    _is_grip = True   # so the view lets a grip click act, not start text-select

    _CURSORS = {
        "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
        "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
    }

    def __init__(self, parent, role):
        super().__init__(-HANDLE / 2, -HANDLE / 2, HANDLE, HANDLE, parent)
        self.role = role  # 'nw','ne','sw','se'
        self.setBrush(QBrush(QColor(30, 120, 230)))
        self.setPen(QPen(QColor("white"), 0))
        self.setCursor(self._CURSORS.get(role, Qt.SizeFDiagCursor))
        self.setZValue(60)
        self.setVisible(False)

    def mousePressEvent(self, event):
        self.parentItem()._begin_resize(self.role)
        event.accept()

    def mouseMoveEvent(self, event):
        self.parentItem()._resize_to(self.role, event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        self.parentItem()._end_resize()
        event.accept()


class _RotateHandle(QGraphicsEllipseItem):
    """A round grip above the top edge that rotates the parent (Word-style)."""

    _is_grip = True   # the rotate grip sits ABOVE the mark, outside its bbox

    def __init__(self, parent):
        super().__init__(-HANDLE / 2, -HANDLE / 2, HANDLE, HANDLE, parent)
        self.setBrush(QBrush(QColor(40, 170, 90)))
        self.setPen(QPen(QColor("white"), 0))
        self.setCursor(Qt.CrossCursor)
        self.setZValue(60)
        self.setVisible(False)

    def mousePressEvent(self, event):
        self.parentItem()._begin_rotate()
        event.accept()

    def mouseMoveEvent(self, event):
        self.parentItem()._rotate_to(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        self.parentItem()._end_rotate()
        event.accept()


class ResizableRectItem(_BaseMixin, QGraphicsRectItem):
    """Base for highlight / textbox / rect marks with corner + rotate handles."""

    def __init__(self, ann: Annotation, view):
        super().__init__()
        self.init_base(ann, view)
        self.setZValue(ANNOT_Z)
        self._handles = {r: _HandleItem(self, r) for r in ("nw", "ne", "sw", "se")}
        self._rotate_handle = _RotateHandle(self)
        self._resize_snap = None
        self._rotate_snap = None
        self.sync_from_model()

    # geometry --------------------------------------------------------------

    def sync_from_model(self):
        x0, y0, x1, y1 = self.ann.rect
        w, h = abs(x1 - x0), abs(y1 - y0)
        self.setRotation(0)
        self.setPos(min(x0, x1), min(y0, y1))
        self.setRect(0, 0, max(w, 1.0), max(h, 1.0))
        self.setTransformOriginPoint(self.rect().center())
        self.setRotation(self.ann.rotation)
        self._place_handles()
        self.update()

    def write_geometry_to_model(self):
        p = self.pos()
        r = self.rect()
        self.ann.rect = (p.x(), p.y(), p.x() + r.width(), p.y() + r.height())
        self.ann.rotation = self.rotation()

    def _place_handles(self):
        r = self.rect()
        pts = {"nw": r.topLeft(), "ne": r.topRight(),
               "sw": r.bottomLeft(), "se": r.bottomRight()}
        for role, h in self._handles.items():
            h.setPos(pts[role])
        self._rotate_handle.setPos(QPointF(r.center().x(), r.top() - ROT_ARM))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            vis = bool(value)
            for h in self._handles.values():
                h.setVisible(vis)
            self._rotate_handle.setVisible(vis)
        return super().itemChange(change, value)

    # resize ----------------------------------------------------------------

    _OPPOSITE = {"nw": "se", "se": "nw", "ne": "sw", "sw": "ne"}

    def _corner(self, role):
        r = self.rect()
        return {"nw": r.topLeft(), "ne": r.topRight(),
                "sw": r.bottomLeft(), "se": r.bottomRight()}[role]

    def _begin_resize(self, role):
        self._resize_snap = capture(self.ann)
        # the corner opposite the dragged one stays fixed in page space,
        # even while the mark is rotated
        self._resize_anchor = self.mapToParent(self._corner(self._OPPOSITE[role]))

    def _resize_to(self, role, scene_pos):
        theta = self.rotation()
        anchor_parent = self._resize_anchor
        anchor_local = self._corner(self._OPPOSITE[role])      # current local frame
        mouse_local = self.mapFromScene(scene_pos)             # rotation inverted

        dirx = 1.0 if mouse_local.x() >= anchor_local.x() else -1.0
        diry = 1.0 if mouse_local.y() >= anchor_local.y() else -1.0
        w = max(4.0, abs(mouse_local.x() - anchor_local.x()))
        h = max(4.0, abs(mouse_local.y() - anchor_local.y()))

        far = QPointF(anchor_local.x() + dirx * w, anchor_local.y() + diry * h)
        new_rect = QRectF(anchor_local, far).normalized()
        tl = new_rect.topLeft()
        center = QPointF(w / 2.0, h / 2.0)                     # new rect's centre
        anchor_new = QPointF(anchor_local.x() - tl.x(), anchor_local.y() - tl.y())

        rot = QTransform()
        rot.rotate(theta)
        rv = rot.map(QPointF(anchor_new.x() - center.x(), anchor_new.y() - center.y()))
        # solve mapToParent(anchor_new) == anchor_parent for the new position
        pos = QPointF(anchor_parent.x() - center.x() - rv.x(),
                      anchor_parent.y() - center.y() - rv.y())

        self.setRect(0, 0, w, h)
        self.setTransformOriginPoint(center)
        self.setRotation(theta)
        self.setPos(pos)
        self._place_handles()

    def _end_resize(self):
        # Unreachable in a read-only pane (the grip that drives this can never be
        # shown), but this writes the model and calls store.update() directly —
        # outside push_command — so guard it too rather than rely on that.
        if getattr(self.view, "read_only", False):
            self._resize_snap = None
            return
        self.write_geometry_to_model()
        after = capture(self.ann)
        if self._resize_snap is not None and after != self._resize_snap:
            self.view.push_command(
                ModifyAnnotationCommand(self.view, self.ann,
                                        self._resize_snap, after, "Resize"))
        self._resize_snap = None
        self.view.store.update(self.ann)

    # rotate -----------------------------------------------------------------

    def _begin_rotate(self):
        self._rotate_snap = capture(self.ann)

    def _rotate_to(self, scene_pos):
        centre = self.mapToScene(self.rect().center())
        dx = scene_pos.x() - centre.x()
        dy = scene_pos.y() - centre.y()
        angle = math.degrees(math.atan2(dy, dx)) + 90.0  # handle points "up"
        self.setRotation(angle)

    def _end_rotate(self):
        if getattr(self.view, "read_only", False):
            self._rotate_snap = None
            return
        self.write_geometry_to_model()
        after = capture(self.ann)
        if self._rotate_snap is not None and after != self._rotate_snap:
            self.view.push_command(
                ModifyAnnotationCommand(self.view, self.ann,
                                        self._rotate_snap, after, "Rotate"))
        self._rotate_snap = None
        self.view.store.update(self.ann)


class HighlightItem(ResizableRectItem):
    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(qcolor(self.ann.color, int(self.ann.opacity * 255))))
        painter.drawRect(self.rect())
        if self.isSelected():
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())


class RectShapeItem(ResizableRectItem):
    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        brush = fill_brush(self.ann)
        painter.setPen(QPen(qcolor(self.ann.color), self.ann.width))
        painter.setBrush(brush if brush is not None else Qt.NoBrush)
        painter.drawRect(self.rect())
        if self.isSelected():
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())


class EllipseShapeItem(ResizableRectItem):
    """A circle/ellipse drawn in its bounding box — identical to the rectangle
    in every way (move, resize, rotate, fill, opacity), just a different shape."""

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        brush = fill_brush(self.ann)
        painter.setPen(QPen(qcolor(self.ann.color), self.ann.width))
        painter.setBrush(brush if brush is not None else Qt.NoBrush)
        painter.drawEllipse(self.rect())
        if self.isSelected():
            # the selection hint stays a rectangle: it's the bounding box you drag
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())


class TextBoxItem(ResizableRectItem):
    """FreeText-style mark: renders its text directly on the page."""

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        # opaque / translucent background behind the text (redaction cover)
        brush = fill_brush(self.ann)
        if brush is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.drawRect(self.rect())
        font = QFont("Helvetica", max(4, int(self.ann.font_size)))
        font.setBold(self.ann.bold)
        font.setItalic(self.ann.italic)
        painter.setFont(font)
        painter.setPen(QPen(qcolor(self.ann.color)))
        painter.drawText(self.rect().adjusted(2, 2, -2, -2),
                         Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
                         self.ann.text or "")
        # dashed border matches the text color (blue only while selected)
        border = QColor(30, 120, 230) if self.isSelected() else qcolor(self.ann.color)
        painter.setPen(QPen(border, 0, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect())

    def mouseDoubleClickEvent(self, event):
        if getattr(self.view, "read_only", False):
            event.ignore()
            return
        self.view.edit_text_annotation(self.ann)
        event.accept()


# --- callout (text box + leader arrow) --------------------------------------


class _LeaderTipHandle(QGraphicsEllipseItem):
    """Draggable grip at the callout's arrow tip (target point)."""

    _is_grip = True

    def __init__(self, parent):
        super().__init__(-HANDLE / 2, -HANDLE / 2, HANDLE, HANDLE, parent)
        self.setBrush(QBrush(QColor(232, 119, 46)))
        self.setPen(QPen(QColor("white"), 0))
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(61)
        self.setVisible(False)

    def mousePressEvent(self, event):
        self.parentItem()._begin_tip()
        event.accept()

    def mouseMoveEvent(self, event):
        self.parentItem()._tip_to(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        self.parentItem()._end_tip()
        event.accept()


class CalloutItem(TextBoxItem):
    """A text box with a leader arrow to a target point. The box behaves exactly
    like a :class:`TextBoxItem` (move / resize / edit / fill); an extra grip at
    the arrow tip repositions the leader. Callouts are not rotated."""

    def __init__(self, ann: Annotation, view):
        self._tip_handle = None
        self._tip_snap = None
        # >0 while a pos() change must NOT drag the leader along with the box
        # (model sync and resizing both move pos; only a *move* takes the tip)
        self._hold_tip = 0
        self._last_pos = None
        super().__init__(ann, view)
        self._rotate_handle.setVisible(False)   # callouts don't rotate
        self._tip_handle = _LeaderTipHandle(self)
        self._last_pos = QPointF(self.pos())
        self._place_tip()

    # geometry --------------------------------------------------------------

    def _default_tip(self):
        x0, y0, x1, y1 = self.ann.rect
        return (min(x0, x1) - 36.0, max(y0, y1) + 36.0)

    def _tip_local(self) -> QPointF:
        # Never persist a default here — writing the model during paint()/
        # boundingRect() would freeze a new callout's tip at the tiny first-
        # preview rect and defeat the final-rect default set on commit.
        cp = self.ann.callout_point
        if cp is None:
            cp = self._default_tip()
        tx, ty = cp
        p = self.pos()
        return QPointF(tx - p.x(), ty - p.y())

    def sync_from_model(self):
        self.ann.rotation = 0.0          # never rotate a callout
        self._hold_tip += 1              # model->item: pos moves, tip must not
        try:
            super().sync_from_model()
        finally:
            self._hold_tip -= 1
        self._last_pos = QPointF(self.pos())
        self._place_tip()

    def _resize_to(self, role, scene_pos):
        # resizing the box repositions pos() for the top/left grips, but the
        # leader keeps pointing where it pointed — only moving takes it along
        self._hold_tip += 1
        try:
            super()._resize_to(role, scene_pos)
        finally:
            self._hold_tip -= 1
        self._last_pos = QPointF(self.pos())

    def _place_tip(self):
        if self._tip_handle is not None:
            self._tip_handle.setPos(self._tip_local())

    def _place_handles(self):
        super()._place_handles()
        self._place_tip()

    def itemChange(self, change, value):
        res = super().itemChange(change, value)
        if self._tip_handle is not None:
            if change == QGraphicsItem.ItemSelectedHasChanged:
                self._tip_handle.setVisible(bool(value))
                self._rotate_handle.setVisible(False)
            elif change == QGraphicsItem.ItemPositionHasChanged:
                # Moving the box takes its leader with it: the arrow keeps the
                # same offset from the box rather than staying pinned to the page
                # point it was drawn at. (Suppressed for model sync and resize —
                # both of which also shift pos(); see _hold_tip.)
                new = self.pos()
                if (self._hold_tip == 0 and self._last_pos is not None
                        and self.ann.callout_point is not None):
                    dx = new.x() - self._last_pos.x()
                    dy = new.y() - self._last_pos.y()
                    if dx or dy:
                        tx, ty = self.ann.callout_point
                        self.ann.callout_point = (tx + dx, ty + dy)
                self._last_pos = QPointF(new)
                self._place_tip()
        return res

    # tip drag --------------------------------------------------------------

    def _begin_tip(self):
        self._tip_snap = capture(self.ann)

    def _tip_to(self, scene_pos):
        local = self.mapFromScene(scene_pos)
        p = self.pos()
        self.ann.callout_point = (local.x() + p.x(), local.y() + p.y())
        self.prepareGeometryChange()
        self._place_tip()
        self.update()

    def _end_tip(self):
        if getattr(self.view, "read_only", False):
            self._tip_snap = None
            return
        after = capture(self.ann)
        if self._tip_snap is not None and after != self._tip_snap:
            self.view.push_command(
                ModifyAnnotationCommand(self.view, self.ann,
                                        self._tip_snap, after, "Move callout"))
        self._tip_snap = None
        self.view.store.update(self.ann)

    # rendering -------------------------------------------------------------

    def _attach_point(self, tip: QPointF) -> QPointF:
        """The point on the box border closest to ``tip``."""
        r = self.rect()
        return QPointF(min(max(tip.x(), r.left()), r.right()),
                       min(max(tip.y(), r.top()), r.bottom()))

    def boundingRect(self) -> QRectF:
        r = QRectF(self.rect())
        tip = self._tip_local()
        return r.united(QRectF(tip.x() - 8, tip.y() - 8, 16, 16))

    def paint(self, painter, option, widget=None):
        # leader first (under the box), then the box + text on top
        tip = self._tip_local()
        attach = self._attach_point(tip)
        pen = QPen(qcolor(self.ann.color), max(1.0, self.ann.width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(attach, tip)
        ang = math.atan2(tip.y() - attach.y(), tip.x() - attach.x())
        ah = max(8.0, self.ann.width * 4)
        for da in (math.radians(150), math.radians(-150)):
            painter.drawLine(tip, QPointF(tip.x() + ah * math.cos(ang + da),
                                          tip.y() + ah * math.sin(ang + da)))
        super().paint(painter, option, widget)


# --- pen stroke -------------------------------------------------------------


class PenItem(_BaseMixin, QGraphicsPathItem):
    def __init__(self, ann: Annotation, view):
        super().__init__()
        self.init_base(ann, view)
        self.sync_from_model()

    def sync_from_model(self):
        path = QPainterPath()
        pts = self.ann.points
        if pts:
            path.moveTo(*pts[0])
            if len(pts) == 1:
                path.lineTo(pts[0][0] + 0.1, pts[0][1] + 0.1)
            else:
                # smooth with quadratics through midpoints
                for i in range(1, len(pts)):
                    x0, y0 = pts[i - 1]
                    x1, y1 = pts[i]
                    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                    path.quadTo(x0, y0, mx, my)
                path.lineTo(*pts[-1])
        self.setPath(path)
        pen = QPen(qcolor(self.ann.color), self.ann.width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self.setPen(pen)
        # position is encoded in the points themselves
        self.setPos(0, 0)

    def write_geometry_to_model(self):
        # translate points by the item's accumulated offset, then reset pos
        dx, dy = self.pos().x(), self.pos().y()
        if dx or dy:
            self.ann.points = [(x + dx, y + dy) for x, y in self.ann.points]
            self.setPos(0, 0)
            self.sync_from_model()

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.ann.width, 6.0))
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())


# --- revision cloud ---------------------------------------------------------


def cloud_path(points, radius: float = 9.0, closed: bool = True) -> QPainterPath:
    """A scalloped (revision-cloud) path following ``points``.

    Outward semicircular bumps are drawn along each edge; bump direction is away
    from the polygon centroid so the scallops face outward.  ``closed`` links the
    last point back to the first (used for finished clouds; open while drawing).
    """
    path = QPainterPath()
    pts = [QPointF(x, y) for x, y in points]
    if len(pts) < 2:
        if pts:
            path.addEllipse(pts[0], radius, radius)
        return path
    cx = sum(p.x() for p in pts) / len(pts)
    cy = sum(p.y() for p in pts) / len(pts)
    seq = pts + [pts[0]] if closed else pts
    first = True
    for i in range(len(seq) - 1):
        a, b = seq[i], seq[i + 1]
        seg_len = math.hypot(b.x() - a.x(), b.y() - a.y())
        n = max(1, int(round(seg_len / (radius * 1.6))))
        for k in range(n):
            t0, t1 = k / n, (k + 1) / n
            p0 = QPointF(a.x() + (b.x() - a.x()) * t0, a.y() + (b.y() - a.y()) * t0)
            p1 = QPointF(a.x() + (b.x() - a.x()) * t1, a.y() + (b.y() - a.y()) * t1)
            mid = QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
            dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
            nlen = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / nlen, dx / nlen
            if (mid.x() - cx) * nx + (mid.y() - cy) * ny < 0:
                nx, ny = -nx, -ny
            ctrl = QPointF(mid.x() + nx * radius, mid.y() + ny * radius)
            if first:
                path.moveTo(p0)
                first = False
            path.quadTo(ctrl, p1)
    if closed:
        path.closeSubpath()
    return path


class CloudItem(_BaseMixin, QGraphicsPathItem):
    """An outline-only revision cloud following a freehand or polygon path."""

    def __init__(self, ann: Annotation, view):
        super().__init__()
        self.init_base(ann, view)
        self.sync_from_model()

    def sync_from_model(self):
        self.setPath(cloud_path(self.ann.points, radius=9.0, closed=True))
        pen = QPen(qcolor(self.ann.color), max(1.0, self.ann.width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self.setPen(pen)
        self.setBrush(Qt.NoBrush)
        self.setPos(0, 0)

    def write_geometry_to_model(self):
        dx, dy = self.pos().x(), self.pos().y()
        if dx or dy:
            self.ann.points = [(x + dx, y + dy) for x, y in self.ann.points]
            self.setPos(0, 0)
            self.sync_from_model()

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.ann.width, 6.0))
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())


# --- arrow ------------------------------------------------------------------


class ArrowItem(ResizableRectItem):
    """An arrow drawn across its bounding box, reusing the rect resize/rotate
    handles so it manipulates exactly like a rectangle.

    The model stores the two *endpoints* (start -> end, un-normalised) in
    ``ann.rect``; orientation is recovered from the sign of the drag so resizing
    the box keeps the arrow pointing the same way.
    """

    def __init__(self, ann: Annotation, view):
        # fractions (0/1) locating start & end on the bounding box corners
        self._sx = self._sy = 0.0
        self._ex = self._ey = 1.0
        super().__init__(ann, view)

    def sync_from_model(self):
        x0, y0, x1, y1 = self.ann.rect
        self._sx, self._ex = (0.0, 1.0) if x1 >= x0 else (1.0, 0.0)
        self._sy, self._ey = (0.0, 1.0) if y1 >= y0 else (1.0, 0.0)
        super().sync_from_model()

    def _arrow_points(self):
        r = self.rect()
        start = QPointF(r.x() + self._sx * r.width(), r.y() + self._sy * r.height())
        end = QPointF(r.x() + self._ex * r.width(), r.y() + self._ey * r.height())
        return start, end

    def boundingRect(self):
        # pad so the arrowhead (drawn past the box corner) is not clipped
        return self.rect().adjusted(-16, -16, 16, 16)

    def write_geometry_to_model(self):
        start, end = self._arrow_points()
        p = self.pos()
        self.ann.rect = (p.x() + start.x(), p.y() + start.y(),
                         p.x() + end.x(), p.y() + end.y())
        self.ann.rotation = self.rotation()

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        start, end = self._arrow_points()
        pen = QPen(qcolor(self.ann.color), self.ann.width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(start, end)
        ang = math.atan2(end.y() - start.y(), end.x() - start.x())
        ah = max(8.0, self.ann.width * 4)
        for da in (math.radians(150), math.radians(-150)):
            painter.drawLine(
                end, QPointF(end.x() + ah * math.cos(ang + da),
                             end.y() + ah * math.sin(ang + da)))
        if self.isSelected():
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())


# --- comment (sticky note bubble) ------------------------------------------


class LineItem(ArrowItem):
    """A plain line — an arrow without the head. Endpoints, resize/rotate and
    every other behaviour are the arrow's."""

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        start, end = self._arrow_points()
        pen = QPen(qcolor(self.ann.color), self.ann.width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(start, end)
        if self.isSelected():
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())


class CommentItem(_BaseMixin, QGraphicsObject):
    SIZE = 18.0

    def __init__(self, ann: Annotation, view):
        super().__init__()
        self.init_base(ann, view)
        self.sync_from_model()

    def sync_from_model(self):
        x0, y0, _, _ = self.ann.rect
        self.setPos(x0, y0)
        self.update()

    def write_geometry_to_model(self):
        p = self.pos()
        s = self.SIZE
        self.ann.rect = (p.x(), p.y(), p.x() + s, p.y() + s)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.SIZE, self.SIZE + 5)

    def paint(self, painter, option, widget=None):
        s = self.SIZE
        body = QColor(255, 209, 71) if not self.ann.is_todo else QColor(120, 190, 255)
        if self.ann.todo_done:
            body = QColor(150, 220, 150)
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(body))
        painter.setPen(QPen(QColor(90, 70, 0), 1.0))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, s, s), 4, 4)
        # little tail
        tail = QPolygonF([QPointF(4, s - 1), QPointF(4, s + 5), QPointF(10, s - 1)])
        path.addPolygon(tail)
        painter.drawPath(path.simplified())
        # speech lines
        painter.setPen(QPen(QColor(90, 70, 0), 1.0))
        for i, yy in enumerate((6, 9, 12)):
            painter.drawLine(QPointF(4, yy), QPointF(s - 4 - i, yy))
        if self.isSelected():
            painter.setPen(QPen(QColor(30, 120, 230), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())

    def mouseDoubleClickEvent(self, event):
        if getattr(self.view, "read_only", False):
            event.ignore()
            return
        self.view.edit_comment_annotation(self.ann)
        event.accept()


# --- factory ----------------------------------------------------------------

_FACTORY = {
    KIND_HIGHLIGHT: HighlightItem,
    KIND_PEN: PenItem,
    KIND_COMMENT: CommentItem,
    KIND_TEXTBOX: TextBoxItem,
    KIND_RECT: RectShapeItem,
    KIND_CIRCLE: EllipseShapeItem,
    KIND_ARROW: ArrowItem,
    KIND_LINE: LineItem,
    KIND_CALLOUT: CalloutItem,
    KIND_CLOUD: CloudItem,
}


def make_item(ann: Annotation, view):
    cls = _FACTORY.get(ann.kind)
    if cls is None:
        return None
    return cls(ann, view)
