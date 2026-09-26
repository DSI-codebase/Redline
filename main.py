"""QApplication entry point for DSI Redline (PDF Markup + Wire-Number Extractor)."""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtWidgets import QApplication


def _set_windows_app_id():
    """Make Windows group the taskbar entry under our own icon, not python's."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DSIInnovations.DSIRedline")
    except Exception:
        pass


def pdf_from_argv(argv) -> Optional[str]:
    """The PDF to open from a launch's arguments, or ``None``.

    Used when the app is started via Windows "Open with… ▸ DSI Redline" (or any
    file-association / command-line launch): the shell passes the document path
    as an argument.  Returns the first argument that names an existing ``.pdf``
    file (case-insensitive); surrounding quotes are tolerated.
    """
    for raw in list(argv)[1:]:
        a = (raw or "").strip().strip('"')
        if a.lower().endswith(".pdf") and os.path.isfile(a):
            return a
    return None


def land(win, pdf_path: Optional[str], splash=None) -> None:
    """Where a launch lands: the PDF it was given, or the File view.

    A PDF passed on the command line / via "Open with…" opens in the Viewer and
    the PDF Tools tab (keeping the splash up for it). With nothing to open, the
    window shows the File view -- pinned and recent drawings -- as Office does,
    rather than an empty gray canvas.
    """
    if pdf_path:
        if splash is not None:
            splash.message(f"Opening {os.path.basename(pdf_path)}…", 98)
        win.load_document(pdf_path)
    else:
        win.show_file_view()


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _set_windows_app_id()
    app = QApplication(argv)

    # lightweight imports so the splash can appear before the heavy modules load
    from app import __app_name__, __version__, app_icon
    from app.splash import SplashScreen

    app.setApplicationName(__app_name__)
    app.setOrganizationName("DSI Innovations")
    icon = app_icon()
    app.setWindowIcon(icon)

    splash = SplashScreen(__app_name__, __version__, icon)
    splash.show()
    splash.message("Starting up…", 8)

    # the heavy import chain (PySide widgets, PyMuPDF, panels) lives here
    splash.message("Loading the PDF engine…", 30)
    from app.main_window import MainWindow

    splash.message("Building the workspace…", 55)
    win = MainWindow(on_progress=splash.message)

    splash.message("Finishing up…", 95)
    win.show()

    land(win, pdf_from_argv(argv), splash)

    splash.finish(win)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
