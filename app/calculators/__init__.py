"""The Calculators tab's engine: PyDRC's calculators, one form each.

The arithmetic lives in PyDRC (``pydrc.calc``), never here. This package
describes each calculator's inputs (``specs``), calls the library with what the
form holds, and renders what comes back as text (``render``). It is Qt-free, so
it is testable without a QApplication, and it imports PyDRC only when a
calculator runs.

PyDRC is optional, as it is for the Audit tab: without it the tab reports
itself unavailable rather than breaking the app, and a calculator a PyDRC too
old to have it names the version and what is missing.
"""

from __future__ import annotations


def status() -> tuple:
    """``(ok, message)``: whether the calculators can run, and what to tell the
    user. Shares the Audit tab's install guidance, which names the interpreter
    that looked."""
    from .. import audit
    ok, message = audit.status()
    if not ok:
        return False, message
    try:
        import pydrc.calc  # noqa: F401
    except Exception as e:
        return False, (f"This PyDRC has no calculator layer ({e}). Update the "
                       f"design rule library to use the Calculators tab.")
    return True, message


def available() -> bool:
    return status()[0]
