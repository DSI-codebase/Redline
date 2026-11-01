"""Every process that runs a test keeps Redline's settings in a folder of its own.

`app.config.AppConfig` is QSettings("PDFMarkup", "PDFMarkupApp"), the developer's
own per-user store, and opening a document puts it on the File view's Recent
list there. One `python tools/run_tests.py` in a fresh container, before this
file did anything, wrote 44 keys into a store that had not existed, among them
19 Recent rows, each a `job.pdf` or `d.pdf` in a `/tmp/tmpXXXX` the test had
already deleted, all opened in the same minute (2026-11-01). `test_v12_recent`
and `test_v14_search` go further and clear the Recent list and the search
history.

Python runs this file before it imports any module under `tests/`, which is
before any test can build an AppConfig, in every process that runs one: each
`python -m unittest tests.<module>` that `tools/run_tests.py` starts, and
`python -m unittest discover` from the root. QSettings.setPath and
setDefaultFormat do not move a QSettings that already exists, so the order is
the mechanism.

It redirects the FORMAT as well as the path. QSettings.setPath cannot move
NativeFormat on Windows, where it is the registry (nor on macOS, where it is
CFPreferences), so a path alone would have moved the store on Linux and left a
Windows runner, or a Windows developer, writing the registry. AppConfig opens
QSettings.defaultFormat(), so switching that to IniFormat and pointing IniFormat
at a temporary folder moves the store on every platform. SystemScope goes there
too, so no machine-wide settings file is read as a fallback either.

Without QtCore no AppConfig can exist and there is nothing to redirect, and
`tests/test_qt_absent_degrades.py` imports this file with PySide6 blocked. The
guard is `except Exception` for the reason `tests/_qt.py` gives.

`tests/test_settings_left_alone.py` is the gate.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

try:
    from PySide6.QtCore import QSettings
except Exception:  # pragma: no cover - no QtCore, so no store to protect
    QSettings = None

# The folder this process's AppConfig reads and writes; None without QtCore.
SETTINGS_DIR = None


def _remove_settings_dir():
    """Write what every AppConfig still holds, then remove the folder.

    A QSettings writes its unsaved changes when it is destroyed, and a window a
    module keeps on its class is destroyed after atexit, so removing the folder
    alone left it to be created again: `test_v110_saveas` and `test_v110_callout`
    each left one in the temp directory (2026-11-01). Qt keeps a file's unsaved
    changes on the file, shared by every QSettings open on it, so one sync here
    leaves the late ones nothing to write, and a QSettings with nothing to
    write creates nothing.
    """
    config = sys.modules.get("app.config")
    if config is not None:
        QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope,
                  config.ORG, config.APP).sync()
    shutil.rmtree(SETTINGS_DIR, ignore_errors=True)


if QSettings is not None:
    SETTINGS_DIR = tempfile.mkdtemp(prefix="redline-test-settings-")
    atexit.register(_remove_settings_dir)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      os.path.join(SETTINGS_DIR, "user"))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.SystemScope,
                      os.path.join(SETTINGS_DIR, "system"))
