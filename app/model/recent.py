"""Recent and pinned files, without Qt: identity, what to open, grouping, search.

The File view (`app/file_view.py`) and File ▸ Open Recent both read their lists
through this module, and `app/config.py` persists them. Everything here is a
pure function of paths and times, so the rules can be tested with no window.

**One entry per drawing, not per file.** `foo.pdf` and `foo.marked.pdf` share
one `foo.markup.db`, and `lifecycle.open_document` already refuses to open one
while the other is open because they are one document. The recent list used to
key on the path instead, so opening both spent two of its slots on one drawing.
`drawing_key` is the sidecar identity that guard uses.

**Which of the two a click opens** is `open_target`: `foo.pdf` when it exists
and either its sidecar exists or there is no marked copy -- opening `foo.pdf`
loads every mark from the sidecar. Otherwise `foo.marked.pdf`. The exception is
the one that matters: `foo.pdf` and `foo.marked.pdf` copied somewhere WITHOUT
the sidecar. Opening `foo.pdf` there would show a clean sheet, because a
document never reads its marked copy's annotations, while opening
`foo.marked.pdf` imports them.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, Optional

from .storage import marked_pdf_path, original_pdf_path, sidecar_path

GROUP_PINNED = "Pinned"
GROUP_TODAY = "Today"
GROUP_YESTERDAY = "Yesterday"
GROUP_THIS_WEEK = "This week"
GROUP_OLDER = "Older"
DATE_GROUPS = (GROUP_TODAY, GROUP_YESTERDAY, GROUP_THIS_WEEK, GROUP_OLDER)


def drawing_key(path: str) -> str:
    """The identity two paths share when they are one drawing."""
    return os.path.normcase(os.path.realpath(sidecar_path(os.path.abspath(path))))


def open_target(path: str, exists=os.path.isfile) -> str:
    """The file to open for the drawing ``path`` names (see the module docstring).

    Returns ``path`` itself when neither file exists, so the caller can report
    it as not found by the name the user knows it by. ``exists`` lets a folder
    scan answer from the listing it already holds rather than stat each file
    again -- the rule stays this one function either way.
    """
    original = original_pdf_path(path)
    marked = marked_pdf_path(path)
    if exists(original) and (exists(sidecar_path(path)) or not exists(marked)):
        return original
    if exists(marked):
        return marked
    return path


def dedupe(paths: Iterable[str]) -> list:
    """``paths`` with every later entry for an already-seen drawing dropped."""
    seen, out = set(), []
    for p in paths:
        k = drawing_key(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def local_time(dt: datetime) -> datetime:
    """Naive local time: an aware stamp converted, a naive one taken as local."""
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def date_group(opened: Optional[str], now: datetime) -> str:
    """Today / Yesterday / This week / Older, by calendar day in local time.

    "This week" is two to six days ago. A time that is missing or unreadable --
    every entry recorded before times were kept -- is Older, because that is
    the one group that does not claim to know when it was.
    """
    if not opened:
        return GROUP_OLDER
    try:
        when = datetime.fromisoformat(opened)
    except (TypeError, ValueError):
        return GROUP_OLDER
    days = (local_time(now).date() - local_time(when).date()).days
    if days <= 0:
        return GROUP_TODAY
    if days == 1:
        return GROUP_YESTERDAY
    if days < 7:
        return GROUP_THIS_WEEK
    return GROUP_OLDER


def matches(query: str, path: str) -> bool:
    """Every word of ``query`` appears in the file name or its folder path,
    ignoring case. An empty query matches everything."""
    words = (query or "").lower().split()
    if not words:
        return True
    hay = path.lower()
    return all(w in hay for w in words)
