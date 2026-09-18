"""Brand palette + small stylesheet helpers (DSI Redline).

Centralizes the colors used by the iLovePDF-style PDF Tools workspace.  The
workspace uses a neutral dark-grey base so it blends with the rest of the app's
panels, with the orange brand accent reserved for selection and the primary
action button.
"""

from __future__ import annotations

# Neutral dark-grey base (matches the app's other panels) + orange accent.
BG = "#2D2D2D"            # primary background
PANEL = "#353535"         # raised panel (file bar, rail, options)
RAISED = "#434343"        # hover / row / secondary button
ORANGE = "#E8772E"        # accent
ORANGE_DIM = "#C96523"    # accent pressed
WHITE = "#FFFFFF"
TEXT = "#E6E6E6"
TEXT_DIM = "#9A9A9A"
LINE = "#555555"          # subtle borders


def workspace_qss() -> str:
    """Stylesheet for the PDF Tools workspace (file bar, rail, grid, options)."""
    return f"""
    QWidget#ToolsWorkspace {{
        background: {BG};
        color: {TEXT};
    }}
    QFrame#FileBar {{
        background: {PANEL};
        border-bottom: 1px solid {LINE};
    }}
    QLabel#FileName {{ color: {WHITE}; font-size: 14px; font-weight: bold; }}
    QLabel#FileHint {{ color: {TEXT_DIM}; }}
    QFrame#Rail {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
    QFrame#Options {{ background: {PANEL}; border-left: 1px solid {LINE}; }}
    QLabel#OptTitle {{ color: {WHITE}; font-size: 15px; font-weight: bold; }}
    QLabel#OptDesc {{ color: {TEXT_DIM}; }}
    QLabel {{ color: {TEXT}; }}

    /* operation rail buttons */
    QPushButton#RailBtn {{
        text-align: left;
        padding: 9px 12px;
        border: none;
        border-radius: 6px;
        background: transparent;
        color: {TEXT};
    }}
    QPushButton#RailBtn:hover {{ background: {RAISED}; }}
    QPushButton#RailBtn:checked {{ background: {ORANGE}; color: {WHITE}; font-weight: bold; }}

    /* primary action button */
    QPushButton#ActionBtn {{
        background: {ORANGE};
        color: {WHITE};
        border: none;
        border-radius: 6px;
        padding: 10px 16px;
        font-weight: bold;
        font-size: 14px;
    }}
    QPushButton#ActionBtn:hover {{ background: {ORANGE_DIM}; }}
    QPushButton#ActionBtn:disabled {{ background: {RAISED}; color: {TEXT_DIM}; }}

    /* secondary buttons */
    QPushButton {{
        background: {RAISED};
        color: {TEXT};
        border: 1px solid {LINE};
        border-radius: 5px;
        padding: 6px 12px;
    }}
    QPushButton:hover {{ border-color: {ORANGE}; }}

    QLineEdit, QSpinBox, QComboBox {{
        background: {BG};
        color: {TEXT};
        border: 1px solid {LINE};
        border-radius: 5px;
        padding: 5px 7px;
        selection-background-color: {ORANGE};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ORANGE}; }}
    QCheckBox, QRadioButton {{ color: {TEXT}; spacing: 6px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {ORANGE};
    }}
    QProgressBar {{
        background: {BG}; border: 1px solid {LINE}; border-radius: 4px;
        text-align: center; color: {TEXT};
    }}
    QProgressBar::chunk {{ background: {ORANGE}; border-radius: 3px; }}
    """


def grid_qss() -> str:
    """Stylesheet for the thumbnail grid (orange selection highlight)."""
    return f"""
    QListWidget#ThumbGrid {{
        background: {BG};
        border: none;
        outline: 0;
    }}
    QListWidget#ThumbGrid::item {{
        color: {TEXT_DIM};
        border: 2px solid transparent;
        border-radius: 6px;
        margin: 4px;
        padding: 4px;
    }}
    QListWidget#ThumbGrid::item:hover {{
        border-color: {LINE};
        background: {PANEL};
    }}
    QListWidget#ThumbGrid::item:selected {{
        color: {WHITE};
        border-color: {ORANGE};
        background: {RAISED};
    }}
    """
