"""Design rule checking inside DSI Redline.

The rules themselves live in PyDRC, a separate pure-Python library with no Qt
and no PyMuPDF: this package is the adapter between the two.  It turns an open
drawing into the model document PyDRC evaluates, runs the rule packs, and hands
back findings for the UI to show.

PyDRC is an optional dependency, handled the same way the AI extraction path
handles the Anthropic SDK: the feature reports itself unavailable rather than
breaking the app when the library is absent.
"""

from __future__ import annotations


def available() -> bool:
    """Whether the rule library is importable."""
    try:
        import pydrc  # noqa: F401
        import pydrc.checks  # noqa: F401
    except Exception:
        return False
    return True


def status() -> tuple:
    """``(ok, message)`` describing why the audit is or is not usable.

    The not-installed message names the interpreter that did the looking and
    the exact command that installs into it. "Not installed" after a
    successful ``pip install`` is nearly always two Pythons -- the shell's and
    the app's -- and a dialog that withholds which one it searched turns a
    one-line fix into a support thread.
    """
    import sys
    try:
        import pydrc
        import pydrc.checks  # noqa: F401
    except ImportError:
        return False, (
            "The design rule library (PyDRC) is not installed for the Python "
            "this app is running:\n"
            f"    {sys.executable}\n\n"
            "Install it with that same interpreter, from the app folder:\n"
            f'    "{sys.executable}" -m pip install -r requirements-drc.txt\n\n'
            "If you already installed it, it went into a different Python "
            "(another venv, or the system install).")
    except Exception as e:                       # pragma: no cover - defensive
        return False, f"The design rule library failed to load: {e}"
    return True, f"PyDRC {getattr(pydrc, '__version__', '?')}"
