"""DSI Redline — PDF markup + wire-number extractor."""

from __future__ import annotations

import sys
from pathlib import Path

__app_name__ = "DSI Redline"
__version__ = "1.5.2"
__copyright__ = "© DSI Innovations, LLC 2026"


def asset_path(name: str) -> str:
    """Locate a bundled asset (e.g. the app icon), from source or a frozen build."""
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "app" / "assets" / name)
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "app" / "assets" / name)
        candidates.append(exe_dir / "_internal" / "app" / "assets" / name)
    candidates.append(Path(__file__).resolve().parent / "assets" / name)
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[-1])


def app_icon():
    """Return the application :class:`QIcon` (multi-resolution)."""
    from PySide6.QtGui import QIcon
    icon = QIcon(asset_path("app.ico"))
    if icon.isNull():
        icon = QIcon(asset_path("app.png"))
    return icon
