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


SELF_TEST = "--self-test"


def self_test_report(argv) -> Optional[str]:
    """Where ``--self-test`` should write its answer.

    ``None`` when the launch is not a self-test, ``""`` when the flag has no
    path after it, otherwise the path.
    """
    args = list(argv)[1:]
    if SELF_TEST not in args:
        return None
    i = args.index(SELF_TEST)
    return args[i + 1] if i + 1 < len(args) else ""


def start(argv):
    """Everything a launch does before the event loop. Returns ``(app, win)``."""
    _set_windows_app_id()
    app = QApplication.instance() or QApplication(argv)

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
    return app, win


def self_test(argv, report: str) -> int:
    """Launch, close, and write ``ok`` or the traceback to ``report``.

    For the frozen build, which the suite never runs: v1.8.0 passed the suite
    from source and died on launch (CHANGELOG, v1.8.1). A windowed build has
    no stdout, and an exception that escapes it opens a message box that a CI
    runner waits on until the job times out, so the launch runs inside this
    handler and the answer goes to a file. Exit 0 with ``ok``, or 1 with the
    traceback.
    """
    try:
        app, win = start(argv)
        app.processEvents()  # run what the window deferred to the event loop
        win.close()
        text, code = "ok\n", 0
    except BaseException:  # noqa: BLE001 -- SystemExit too: the report is the point
        import traceback
        text, code = traceback.format_exc(), 1
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(text)
    return code


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    report = self_test_report(argv)
    if report == "":
        return 2  # refused: a windowed build has nowhere else to say why
    if report is not None:
        return self_test(argv, report)
    app, _win = start(argv)  # _win keeps the window alive for the event loop
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
