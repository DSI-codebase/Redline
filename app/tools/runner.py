"""A tiny reusable background-task runner for the PDF tools.

Runs ``fn(progress, cancel)`` on a QThread and reports progress/result/error so
dialogs never block the UI (mirrors the pattern in
:mod:`app.panels.wire_panel`).
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class BackgroundTask(QThread):
    progress = Signal(int, int)   # done, total
    done = Signal(object)         # return value of fn
    failed = Signal(str)          # error message, or "__cancelled__"

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = self._fn(
                lambda d, t: self.progress.emit(int(d), int(t)),
                lambda: self._cancel,
            )
            if self._cancel:
                self.failed.emit("__cancelled__")
                return
            self.done.emit(result)
        except Exception as e:  # pragma: no cover - defensive
            self.failed.emit(str(e))


def run_with_progress(parent, title, fn, on_done, on_error=None):
    """Run ``fn(progress, cancel)`` on a thread behind a modal QProgressDialog.

    Returns the running task; the caller must keep a reference to it.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QProgressDialog

    dlg = QProgressDialog(title, "Cancel", 0, 0, parent)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)
    task = BackgroundTask(fn, parent)

    def _prog(d, t):
        dlg.setMaximum(max(1, t))
        dlg.setValue(d)

    def _done(res):
        dlg.reset()
        task.wait(2000)
        on_done(res)

    def _failed(msg):
        dlg.reset()
        task.wait(2000)
        if msg != "__cancelled__" and on_error is not None:
            on_error(msg)

    task.progress.connect(_prog)
    task.done.connect(_done)
    task.failed.connect(_failed)
    dlg.canceled.connect(task.cancel)
    task.start()
    return task
