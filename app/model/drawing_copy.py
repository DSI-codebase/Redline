"""Copying a drawing into a workspace folder -- all of it, and over nothing.

A drawing here is up to three files sharing a stem: `foo.pdf`, the
`foo.marked.pdf` that carries the marks as standard annotations, and the
`foo.markup.db` sidecar that is their source of truth (TODO state, tags, the
wire cache). Copying `foo.pdf` alone leaves every mark behind, and the copy
opens with an empty sidecar. So `plan_copy` gathers whichever of the three
exist and `copy_drawing` writes them together.

**Nothing is ever replaced.** A destination whose stem is taken gets the next
free `foo (2)`, `foo (3)` ... for ALL three files, so a renamed set still
shares one stem and still finds its own sidecar. Each file is then created
with exclusive-create (`open(..., "xb")`), so a file that appears between the
plan and the write fails the copy rather than being overwritten -- and every
destination goes through `storage.refuse_overwriting_input` and
`storage.refuse_protected` first, the refusals every writer in this app calls.

**Order matters for that second refusal.** It refuses a PDF whose sidecar holds
marks, so the PDFs are written before the sidecar: written after, the
destination's own new sidecar would make its PDF refuse itself.

**The sidecar is copied with SQLite's backup API**, not as bytes: the app holds
it open while the drawing is, and the backup reads one consistent, committed
snapshot however the file is being used. What is committed is what was saved,
which is why the caller asks to save first.

A copy that fails part-way removes only the files it created itself.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import sqlite3
from dataclasses import dataclass, field

from .storage import (
    marked_pdf_path, original_pdf_path, refuse_overwriting_input, refuse_protected,
    sidecar_path,
)
from .recent import open_target

KIND_PDF, KIND_MARKED, KIND_DB = "pdf", "marked", "db"
_SUFFIX = {KIND_PDF: ".pdf", KIND_MARKED: ".marked.pdf", KIND_DB: ".markup.db"}
_ORDER = (KIND_PDF, KIND_MARKED, KIND_DB)      # PDFs before the sidecar; see above


class CopyError(Exception):
    """A copy that cannot be made; the message is shown to the user."""


def drawing_set(path: str) -> dict:
    """{kind: path} for each of the drawing's files that exists."""
    candidates = {KIND_PDF: original_pdf_path(path), KIND_MARKED: marked_pdf_path(path),
                  KIND_DB: sidecar_path(path)}
    return {k: os.path.normpath(p) for k, p in candidates.items() if os.path.isfile(p)}


def _dests(folder: str, stem: str) -> dict:
    return {k: os.path.join(folder, stem + s) for k, s in _SUFFIX.items()}


def _taken(folder: str, stem: str) -> bool:
    return any(os.path.exists(p) for p in _dests(folder, stem).values())


@dataclass
class CopyPlan:
    sources: dict                   # {kind: source path}
    folder: str                     # destination folder
    stem: str                       # destination stem, "foo" or "foo (2)"
    natural_stem: str               # the source's own stem
    identical: str = ""             # a byte-identical copy already there, or ""
    written: list = field(default_factory=list)

    @property
    def clash(self) -> bool:
        return self.stem != self.natural_stem

    @property
    def dests(self) -> dict:
        """{kind: destination} for the files this plan copies."""
        all_ = _dests(self.folder, self.stem)
        return {k: all_[k] for k in self.sources}

    @property
    def open_path(self) -> str:
        """The copy to open afterward -- the same choice a Recent row makes."""
        return open_target(os.path.join(self.folder, self.stem + ".pdf"))


def plan_copy(source: str, folder: str) -> CopyPlan:
    """What copying the drawing ``source`` names into ``folder`` would write."""
    sources = drawing_set(source)
    if KIND_PDF not in sources and KIND_MARKED not in sources:
        raise CopyError(f"“{os.path.basename(source)}” can't be found.")
    folder = os.path.normpath(os.path.abspath(folder))
    natural = os.path.basename(original_pdf_path(source))[:-len(".pdf")]
    plan = CopyPlan(sources=sources, folder=folder, stem=natural, natural_stem=natural)
    if not _taken(folder, natural):
        return plan
    # The name is taken. The same drawing already there is "already in the
    # workspace", decided on the PDF's bytes rather than its name.
    primary = KIND_PDF if KIND_PDF in sources else KIND_MARKED
    there = _dests(folder, natural)[primary]
    if os.path.isfile(there) and filecmp.cmp(sources[primary], there, shallow=False):
        plan.identical = there
    n = 2
    while _taken(folder, f"{natural} ({n})"):
        n += 1
    plan.stem = f"{natural} ({n})"
    return plan


def _backup(src: str, dst: str) -> None:
    source = sqlite3.connect(src)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def copy_drawing(plan: CopyPlan) -> dict:
    """Write the plan's files; return {kind: destination}. All or nothing."""
    os.makedirs(plan.folder, exist_ok=True)
    dests = plan.dests
    try:
        for kind in _ORDER:
            if kind not in plan.sources:
                continue
            src, dst = plan.sources[kind], dests[kind]
            refuse_overwriting_input(dst, src)
            if kind != KIND_DB:
                refuse_protected(dst)      # the rule is about PDFs
            # exclusive create, and recorded the moment it exists, so a failure
            # after this point still removes it
            with open(dst, "xb") as fout:
                plan.written.append(dst)
                if kind != KIND_DB:
                    with open(src, "rb") as fin:
                        shutil.copyfileobj(fin, fout)
            if kind == KIND_DB:
                _backup(src, dst)          # into the empty file just claimed
            else:
                shutil.copystat(src, dst)
    except FileExistsError as e:
        _undo(plan)
        raise CopyError(f"“{e.filename}” appeared while copying; nothing was "
                        f"replaced and the copy was undone.") from e
    except Exception:
        _undo(plan)
        raise
    return dests


def _undo(plan: CopyPlan) -> None:
    for p in reversed(plan.written):
        try:
            os.remove(p)
        except OSError:
            pass
    plan.written.clear()
