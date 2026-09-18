"""In-memory annotation model (GUI-free).

A single :class:`Annotation` dataclass represents every kind of mark.  The
:class:`AnnotationStore` is a lightweight observable container: views (the
canvas, the comment sidebar, the TODO tab) register callbacks and are notified
on add / update / remove so they stay live without any Qt coupling here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Optional

# Annotation kinds
KIND_HIGHLIGHT = "highlight"
KIND_PEN = "pen"
KIND_COMMENT = "comment"      # sticky note (bubble icon)
KIND_TEXTBOX = "textbox"      # FreeText rendered on the page
KIND_RECT = "rect"
KIND_CIRCLE = "circle"        # ellipse drawn in its bounding box (like a rect)
KIND_ARROW = "arrow"
KIND_LINE = "line"            # a plain arrow with no head
KIND_CALLOUT = "callout"      # FreeText with a leader arrow to a target point
KIND_CLOUD = "cloud"          # revision cloud (scalloped polygon, outline only)

TEXT_KINDS = {KIND_COMMENT, KIND_TEXTBOX, KIND_CALLOUT}

# Marks the user can copy / paste as whole objects.
COPYABLE_KINDS = {KIND_TEXTBOX, KIND_CALLOUT, KIND_RECT, KIND_CIRCLE,
                  KIND_ARROW, KIND_LINE, KIND_CLOUD}

# Visual-style fields carried by "copy formatting" / "paste formatting" — colour,
# fill and text styling, but NOT the text content or the geometry.
STYLE_FIELDS = ("color", "fill_color", "fill_opacity", "width", "opacity",
                "font_size", "bold", "italic")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Annotation:
    """One mark on a page.  Coordinates are PDF points in page space."""

    page: int                                   # 0-based page index
    kind: str
    rect: tuple = (0.0, 0.0, 0.0, 0.0)          # (x0, y0, x1, y1)
    color: tuple = (1.0, 0.85, 0.0)             # RGB 0..1
    author: str = ""
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)
    text: str = ""

    # type-specific geometry / style
    points: list = field(default_factory=list)  # pen: [(x, y), ...]
    width: float = 2.0                           # pen width / border width
    font_size: float = 11.0
    bold: bool = False
    italic: bool = False
    opacity: float = 0.4                         # highlights
    rotation: float = 0.0                        # degrees, clockwise, about centre

    # interior fill for rectangles / text boxes (None = no fill / transparent).
    # ``fill_opacity`` 1.0 gives a solid cover; a white opaque fill redacts.
    fill_color: Optional[tuple] = None           # RGB 0..1, or None
    fill_opacity: float = 1.0

    # callout leader: the arrow-tip target point in page space (None until set)
    callout_point: Optional[tuple] = None        # (x, y), or None

    # stacking order among marks on the same page (higher = drawn on top)
    z_order: float = 0.0

    # app-only state (synced to the SQLite sidecar, not the PDF)
    is_todo: bool = False
    todo_done: bool = False
    tags: list = field(default_factory=list)
    priority: int = 0
    ignored: bool = False                        # SHX / junk filter match
    order: int = 0                               # TODO manual ordering

    # provenance
    source: str = "app"                          # "app" (new) | "pdf" (loaded)
    pdf_xref: Optional[int] = None               # xref when loaded from a PDF
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # ---- convenience -------------------------------------------------------

    @property
    def is_comment_like(self) -> bool:
        return self.kind in TEXT_KINDS

    @property
    def has_note(self) -> bool:
        """True when a note/comment is attached (any mark kind can carry one)."""
        return bool((self.text or "").strip())

    @property
    def shows_in_comments(self) -> bool:
        """Whether this mark belongs in the Comments sidebar: the inherently
        textual kinds, highlights/pen (historically listed), or any other mark
        that has had a note attached."""
        return (self.is_comment_like or self.kind in (KIND_HIGHLIGHT, KIND_PEN)
                or self.has_note)

    def snippet(self, n: int = 60) -> str:
        t = " ".join((self.text or "").split())
        if not t:
            return f"({self.kind})"
        return t if len(t) <= n else t[: n - 1] + "…"

    def touch(self) -> None:
        self.modified = now_iso()

    # ---- copy / paste ------------------------------------------------------

    def clone(self, *, new_id: bool = True) -> "Annotation":
        """A deep copy of this mark.  ``new_id`` gives it a fresh id and
        timestamps so it can be added as an independent new annotation (paste)."""
        copy = Annotation.from_dict(self.to_dict())
        if new_id:
            copy.id = uuid.uuid4().hex
            copy.created = copy.modified = now_iso()
        return copy

    def translate(self, dx: float, dy: float) -> None:
        """Shift the whole mark's geometry by ``(dx, dy)`` page points."""
        x0, y0, x1, y1 = self.rect
        if (x0, y0, x1, y1) != (0.0, 0.0, 0.0, 0.0):   # skip a point-only mark's unused rect
            self.rect = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        if self.points:
            self.points = [(px + dx, py + dy) for px, py in self.points]
        if self.callout_point is not None:
            cx, cy = self.callout_point
            self.callout_point = (cx + dx, cy + dy)

    def style_dict(self) -> dict:
        """The visual-style fields (for 'copy formatting') — no text, no geometry."""
        return {f: getattr(self, f) for f in STYLE_FIELDS}

    def apply_style(self, style: dict) -> None:
        """Apply a :meth:`style_dict` onto this mark ('paste formatting')."""
        for f in STYLE_FIELDS:
            if f in style:
                setattr(self, f, style[f])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Annotation":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in d.items() if k in known}
        # tuples survive JSON/round-trips as lists
        if "rect" in clean and clean["rect"] is not None:
            clean["rect"] = tuple(clean["rect"])
        if "color" in clean and clean["color"] is not None:
            clean["color"] = tuple(clean["color"])
        if clean.get("fill_color") is not None:
            clean["fill_color"] = tuple(clean["fill_color"])
        if clean.get("callout_point") is not None:
            clean["callout_point"] = tuple(clean["callout_point"])
        return cls(**clean)


class AnnotationStore:
    """Observable collection of :class:`Annotation`."""

    def __init__(self):
        self._items: dict = {}
        self._listeners: list = []

    # -- observation ---------------------------------------------------------

    def add_listener(self, fn: Callable[[str, Annotation], None]) -> None:
        """``fn(event, annotation)`` where event is add / update / remove."""
        self._listeners.append(fn)

    def _emit(self, event: str, ann: Annotation) -> None:
        for fn in list(self._listeners):
            try:
                fn(event, ann)
            except Exception:
                # a misbehaving view must never corrupt the model
                pass

    # -- CRUD ----------------------------------------------------------------

    def add(self, ann: Annotation, silent: bool = False) -> Annotation:
        self._items[ann.id] = ann
        if not silent:
            self._emit("add", ann)
        return ann

    def update(self, ann: Annotation, silent: bool = False) -> Annotation:
        ann.touch()
        self._items[ann.id] = ann
        if not silent:
            self._emit("update", ann)
        return ann

    def remove(self, ann_id: str, silent: bool = False) -> Optional[Annotation]:
        ann = self._items.pop(ann_id, None)
        if ann is not None and not silent:
            self._emit("remove", ann)
        return ann

    def get(self, ann_id: str) -> Optional[Annotation]:
        return self._items.get(ann_id)

    def clear(self) -> None:
        self._items.clear()

    # -- queries -------------------------------------------------------------

    def all(self) -> list:
        return list(self._items.values())

    def visible(self, show_ignored: bool = False) -> list:
        """Non-ignored marks (SHX junk hidden) unless ``show_ignored``."""
        return [a for a in self._items.values() if show_ignored or not a.ignored]

    def comments(self, show_ignored: bool = False) -> list:
        return [a for a in self.visible(show_ignored) if a.is_comment_like]

    def todos(self, show_ignored: bool = False) -> list:
        return [a for a in self.visible(show_ignored) if a.is_todo]

    def on_page(self, page: int, show_ignored: bool = False) -> list:
        return [a for a in self.visible(show_ignored) if a.page == page]
