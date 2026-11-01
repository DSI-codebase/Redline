"""A name from data, put into text that Qt reads ``&`` markers in.

Qt treats a single ``&`` in a menu item, a button, a group-box title or a
QLabel with a buddy as a mnemonic: the ``&`` is not shown, the next character
is underlined, and Alt+it is bound. ``&&`` shows one ``&``. So a drawing named
*Pump & Valve.pdf* appeared in File > Open Recent as *Pump _Valve.pdf*, and a
commenter named *R&D* on a button as *RD*.

A file, folder, workspace, author or rule-pack name goes through ``literal``
before it joins such a text. A deliberate mnemonic around it, such as Open
Recent's ``&1``, is written by the caller outside the call.

``tests/test_ampersand_titles.py`` reads the displayed text back from Qt for
each place this is used.
"""

from __future__ import annotations


def literal(text: str) -> str:
    """``text`` written so Qt displays every ``&`` in it: each one doubled."""
    return text.replace("&", "&&")
