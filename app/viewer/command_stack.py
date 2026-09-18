"""QUndoStack commands for every annotation edit (Phase 2).

Commands operate on the :class:`AnnotationStore` (the model) and ask the view to
re-sync the affected graphics item.  Create / delete / move / resize / style /
text edits are all undoable via Ctrl+Z / Ctrl+Shift+Z.
"""

from __future__ import annotations

import copy
from typing import Optional

from PySide6.QtGui import QUndoCommand, QUndoStack  # noqa: F401 (re-export)

from ..model.annotations import Annotation


class AddAnnotationCommand(QUndoCommand):
    def __init__(self, view, ann: Annotation, text: str = "Add"):
        super().__init__(text)
        self.view = view
        self.ann = ann

    def redo(self):
        self.view.store.add(self.ann)

    def undo(self):
        self.view.store.remove(self.ann.id)


class RemoveAnnotationCommand(QUndoCommand):
    def __init__(self, view, ann: Annotation, text: str = "Delete"):
        super().__init__(text)
        self.view = view
        self.ann = ann

    def redo(self):
        self.view.store.remove(self.ann.id)

    def undo(self):
        self.view.store.add(self.ann)


class ReorderCommand(QUndoCommand):
    """Change the stacking (z) order of marks on a page.  ``before`` / ``after``
    map annotation-id -> z_order for every mark whose order changed."""

    def __init__(self, view, before: dict, after: dict, text: str = "Reorder"):
        super().__init__(text)
        self.view = view
        self.before = dict(before)
        self.after = dict(after)

    def _apply(self, mapping: dict):
        for aid, z in mapping.items():
            ann = self.view.store.get(aid)
            if ann is not None:
                ann.z_order = z
                self.view.apply_z_order(ann)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


def _snapshot(ann: Annotation) -> dict:
    return {
        "rect": tuple(ann.rect),
        "points": list(ann.points),
        "color": tuple(ann.color),
        "width": ann.width,
        "font_size": ann.font_size,
        "bold": ann.bold,
        "italic": ann.italic,
        "text": ann.text,
        "author": ann.author,
        "opacity": ann.opacity,
        "rotation": ann.rotation,
        "fill_color": tuple(ann.fill_color) if ann.fill_color is not None else None,
        "fill_opacity": ann.fill_opacity,
        "callout_point": (tuple(ann.callout_point)
                          if ann.callout_point is not None else None),
    }


def _restore(ann: Annotation, snap: dict) -> None:
    ann.rect = tuple(snap["rect"])
    ann.points = list(snap["points"])
    ann.color = tuple(snap["color"])
    ann.width = snap["width"]
    ann.font_size = snap["font_size"]
    ann.bold = snap["bold"]
    ann.italic = snap["italic"]
    ann.text = snap["text"]
    ann.author = snap.get("author", ann.author)
    ann.opacity = snap["opacity"]
    ann.rotation = snap.get("rotation", 0.0)
    fc = snap.get("fill_color")
    ann.fill_color = tuple(fc) if fc is not None else None
    ann.fill_opacity = snap.get("fill_opacity", 1.0)
    cp = snap.get("callout_point")
    ann.callout_point = tuple(cp) if cp is not None else None


class ModifyAnnotationCommand(QUndoCommand):
    """Generic geometry/style/text change captured as before/after snapshots."""

    def __init__(self, view, ann: Annotation, before: dict, after: dict,
                 text: str = "Edit"):
        super().__init__(text)
        self.view = view
        self.ann = ann
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self._first = True

    def redo(self):
        _restore(self.ann, self.after)
        self.view.store.update(self.ann)

    def undo(self):
        _restore(self.ann, self.before)
        self.view.store.update(self.ann)


def capture(ann: Annotation) -> dict:
    """Public helper - snapshot an annotation's editable state."""
    return _snapshot(ann)
