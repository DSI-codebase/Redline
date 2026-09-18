"""Tool state for the markup canvas (Phase 2).

The actual mouse handling lives in :class:`app.viewer.pdf_view.PdfView`, which
dispatches on the current tool; this module just holds the mutually-exclusive
tool selection and the active style settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

TOOL_SELECT = "select"
TOOL_HIGHLIGHT = "highlight"
TOOL_PEN = "pen"
TOOL_ERASER = "eraser"
TOOL_COMMENT = "comment"
TOOL_TEXTBOX = "textbox"
TOOL_RECT = "rect"
TOOL_CIRCLE = "circle"
TOOL_ARROW = "arrow"
TOOL_LINE = "line"
TOOL_CALLOUT = "callout"
TOOL_CLOUD = "cloud"

ERASER_OBJECT = "object"
ERASER_STROKE = "stroke"

ALL_TOOLS = (
    TOOL_SELECT, TOOL_HIGHLIGHT, TOOL_PEN, TOOL_ERASER,
    TOOL_COMMENT, TOOL_TEXTBOX, TOOL_RECT, TOOL_ARROW, TOOL_CALLOUT, TOOL_CLOUD,
)


@dataclass
class ToolState:
    current: str = TOOL_SELECT

    # styling
    highlight_color: tuple = (1.0, 0.92, 0.23)
    pen_color: tuple = (0.90, 0.10, 0.10)
    pen_width: float = 2.0
    text_color: tuple = (0.85, 0.10, 0.10)
    font_size: float = 12.0
    bold: bool = False
    italic: bool = False
    shape_color: tuple = (0.10, 0.45, 0.90)
    shape_width: float = 1.5
    highlight_opacity: float = 0.4

    # interior fill (None = no fill). Rectangles and text boxes each remember
    # their own; opacity 1.0 gives a solid cover, white opaque redacts.
    shape_fill: Optional[tuple] = None
    shape_fill_opacity: float = 1.0
    text_fill: Optional[tuple] = None
    text_fill_opacity: float = 1.0

    eraser_mode: str = ERASER_OBJECT

    def is_select(self) -> bool:
        return self.current == TOOL_SELECT
