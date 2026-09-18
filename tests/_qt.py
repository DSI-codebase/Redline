"""Is a working PySide6 importable? One answer, asked by every module.

The suite already had this idiom, inline, in 28 modules -- and seven others
ERRORED instead of skipping, which is the state `CONTRIBUTING.md` calls "not a
failure". They were not missing the idiom out of carelessness: three of the
seven carry a `try/except` around their own `PySide6` import and still failed,
because what they actually import at module scope is `app.config` or `app.help`,
and Qt arrives THROUGH those. A guard that probes the direct import cannot see a
transitive one.

So the probe is shared rather than copied a twenty-ninth time, and it probes the
thing rather than a proxy for it: whether `PySide6` imports at all. Measured --
blocking `PySide6` and nothing else is enough to reproduce every one of the
seven failures, so it is the single cause.

`except Exception`, not `except ImportError`, and that is deliberate: the
documented Linux failure is `libEGL.so.1: cannot open shared object file` raised
from inside the extension module, which is not always an ImportError. Both
states -- the package absent, and the package present without its system
libraries -- must skip rather than error.
"""

from __future__ import annotations

try:  # pragma: no cover - the outcome is the point, not the branch
    import PySide6.QtCore  # noqa: F401
    import PySide6.QtGui  # noqa: F401
    import PySide6.QtWidgets  # noqa: F401

    QT_OK = True
except Exception:  # pragma: no cover
    QT_OK = False

REASON = "PySide6 (or its system libraries) not available"
