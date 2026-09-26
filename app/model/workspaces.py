"""Workspaces, without Qt: what one is, what is in it, and which one a file is in.

A workspace is a folder the user declares -- a project's root -- and it is made
of every PDF under that folder, at any depth. The File view (`app/file_view.py`)
lists them and `app/config.py` stores them, per user: nothing here ever writes
into a workspace folder except `create_workspace`, which the user asked for.

**Everything a workspace remembers about its files is RELATIVE to its root** --
favorites, hidden folders, its own recent list -- so pointing a workspace at the
folder's new location (Locate…) keeps all of it. Stored with ``/`` separators
and compared case-insensitively where the platform is.

**Workspaces never nest.** "The current workspace is the one holding the open
file" needs one answer, so adding a root inside another, or around one, is
refused by `overlap` with the name of the workspace in the way.

**A scan reports what it could not read.** A folder that raises on listing is
counted in `ScanResult.unreadable` rather than skipped silently, because "412
PDFs" over a folder half of which was unreadable is a count of nothing.
"""

from __future__ import annotations

import os
import stat
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

from . import recent as R
from .storage import marked_pdf_path, original_pdf_path


class WorkspaceError(Exception):
    """A workspace operation was refused; the message is shown to the user."""


# --- identity ---------------------------------------------------------------

def norm_root(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def contains(root: str, path: str) -> bool:
    """True when ``path`` is ``root`` or anywhere below it."""
    r, p = _key(root), _key(path)
    try:
        return os.path.commonpath([r, p]) == r
    except ValueError:              # different drives on Windows
        return False


def relative(root: str, path: str) -> str:
    """``path`` relative to ``root``, ``/``-separated ("" for the root itself)."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    return "" if rel == "." else rel.replace(os.sep, "/")


def rel_key(rel: str) -> str:
    """How two relative paths are compared: case follows the platform."""
    return os.path.normcase(rel.replace("/", os.sep))


def absolute(root: str, rel: str) -> str:
    return os.path.normpath(os.path.join(root, *rel.split("/"))) if rel else norm_root(root)


# --- one workspace -----------------------------------------------------------

@dataclass
class Workspace:
    root: str
    name: str = ""                                   # "" -> the folder's name
    pinned: bool = False
    last_used: str = ""                              # ISO time
    hidden: list = field(default_factory=list)       # relative folders
    favorites: list = field(default_factory=list)    # relative files
    recent: list = field(default_factory=list)       # [[relative file, ISO time]]

    @property
    def display_name(self) -> str:
        return self.name or os.path.basename(os.path.normpath(self.root)) or self.root

    @property
    def available(self) -> bool:
        return os.path.isdir(self.root)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Workspace":
        known = set(cls.__dataclass_fields__)            # type: ignore[attr-defined]
        ws = cls(**{k: v for k, v in dict(d).items() if k in known})
        ws.root = norm_root(ws.root)
        ws.hidden = [str(h) for h in ws.hidden or []]
        ws.favorites = [str(f) for f in ws.favorites or []]
        ws.recent = [[str(r[0]), str(r[1])] for r in ws.recent or []
                     if isinstance(r, (list, tuple)) and len(r) == 2]
        return ws

    # favorites and hidden folders are sets of relative paths, kept in order
    @staticmethod
    def _has(rels: list, rel: str) -> bool:
        return any(rel_key(r) == rel_key(rel) for r in rels)

    @staticmethod
    def _toggle(rels: list, rel: str, on: bool) -> list:
        kept = [r for r in rels if rel_key(r) != rel_key(rel)]
        return kept + [rel] if on else kept

    def is_favorite(self, rel: str) -> bool:
        return self._has(self.favorites, rel)

    def set_favorite(self, rel: str, on: bool) -> None:
        self.favorites = self._toggle(self.favorites, rel, on)

    def is_hidden(self, rel_folder: str) -> bool:
        """True when the folder, or one above it, is hidden."""
        parts = rel_folder.split("/") if rel_folder else []
        return any(self._has(self.hidden, "/".join(parts[:i]))
                   for i in range(1, len(parts) + 1))

    def set_hidden(self, rel_folder: str, on: bool) -> None:
        self.hidden = self._toggle(self.hidden, rel_folder, on)

    def record_open(self, rel: str, when: str, keep: int) -> None:
        """Put ``rel`` at the top of this workspace's recent list."""
        me = R.drawing_key(absolute(self.root, rel))
        rest = [r for r in self.recent
                if R.drawing_key(absolute(self.root, r[0])) != me]
        self.recent = ([[rel, when]] + rest)[:keep]
        self.last_used = when

    def forget_recent(self, rel: str) -> None:
        me = R.drawing_key(absolute(self.root, rel))
        self.recent = [r for r in self.recent
                       if R.drawing_key(absolute(self.root, r[0])) != me]


# --- a set of workspaces -----------------------------------------------------

def overlap(root: str, workspaces: Iterable[Workspace],
            ignore: Optional[str] = None) -> Optional[Workspace]:
    """The workspace ``root`` would nest with -- inside it, around it, or the
    same folder -- or ``None``. ``ignore`` is a root to leave out (Locate…
    moving a workspace must not collide with its own old self)."""
    for ws in workspaces:
        if ignore is not None and _key(ws.root) == _key(ignore):
            continue
        if contains(ws.root, root) or contains(root, ws.root):
            return ws
    return None


def nesting_message(root: str, clash: Workspace) -> str:
    """Why ``root`` was refused, naming the workspace in the way."""
    if _key(clash.root) == _key(root):
        where = "is already the workspace"
    elif contains(clash.root, root):
        where = "is inside the workspace"
    else:
        where = "contains the workspace"
    return (f"“{root}” {where} “{clash.display_name}” ({clash.root}). "
            f"Workspaces can't be inside one another — use that workspace, "
            f"or remove it from the list first.")


def containing(workspaces: Iterable[Workspace], path: str) -> Optional[Workspace]:
    """The workspace ``path`` is in, or ``None``. With nesting refused there is
    at most one; a list from before that rule gets the deepest."""
    hits = [ws for ws in workspaces if contains(ws.root, path)]
    return max(hits, key=lambda ws: len(_key(ws.root)), default=None)


def ordered(workspaces: Iterable[Workspace]) -> list:
    """Pinned first, then by last use, newest first; never used goes last."""
    by_use = sorted(workspaces, key=lambda ws: ws.last_used or "", reverse=True)
    return sorted(by_use, key=lambda ws: not ws.pinned)      # stable


def check_folder_name(name: str) -> str:
    """``name`` stripped, or WorkspaceError when it can't name one folder --
    a separator would make it a path, and Windows refuses the rest."""
    name = (name or "").strip()
    if not name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|'):
        raise WorkspaceError(f"“{name}” can't be used as a folder name.")
    return name


def create_workspace(parent: str, name: str, subfolders: Iterable[str]) -> str:
    """Make ``parent/name`` and its quick subfolders; return the new root.

    Refuses a folder that already exists -- New workspace… is for a new one,
    and Add workspace… is how an existing folder becomes a workspace.
    """
    name = check_folder_name(name)
    root = norm_root(os.path.join(parent, name))
    if os.path.exists(root):
        raise WorkspaceError(
            f"“{root}” already exists. Use Add workspace… to make an existing "
            f"folder a workspace.")
    os.makedirs(root)
    for sub in subfolders:
        sub = str(sub).strip()
        if sub:
            os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


# --- what is in one ----------------------------------------------------------

@dataclass
class WorkspaceFile:
    rel: str            # the file a click opens, relative, "/"-separated
    path: str           # the same, absolute
    folder: str         # its folder, relative ("" at the root)
    modified: float     # newest mtime among the drawing's PDFs
    hidden: bool = False  # under a hidden folder (listed only when showing them)

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass
class ScanResult:
    root: str
    files: list = field(default_factory=list)       # WorkspaceFile, by folder then name
    folders: int = 0                                # folders holding a listed PDF
    unreadable: list = field(default_factory=list)  # relative folders that raised
    hidden_skipped: int = 0                         # hidden folders left out
    canceled: bool = False

    def summary(self) -> str:
        n, f = len(self.files), self.folders
        s = (f"{n} PDF{'s' if n != 1 else ''} in {f} folder{'s' if f != 1 else ''}")
        if self.hidden_skipped:
            s += f" · {self.hidden_skipped} hidden folder" \
                 f"{'s' if self.hidden_skipped != 1 else ''} not shown"
        if self.unreadable:
            u = len(self.unreadable)
            s += f" · {u} folder{'s' if u != 1 else ''} could not be read"
        return s


def _system_hidden(dirpath: str, name: str) -> bool:
    """A dot-folder, or one Windows marks hidden or system."""
    if name.startswith("."):
        return True
    try:
        attrs = os.stat(os.path.join(dirpath, name)).st_file_attributes  # Windows
    except (AttributeError, OSError):
        return False
    return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def scan(ws: Workspace, show_hidden: bool = False,
         cancel: Optional[Callable[[], bool]] = None) -> ScanResult:
    """Every drawing under ``ws.root``, one row per drawing.

    Dot-folders and folders the OS marks hidden or system are never entered.
    Folders the user hid are left out, and counted, unless ``show_hidden``.
    """
    root = norm_root(ws.root)
    out = ScanResult(root=root)
    folders_with_files = set()

    def onerror(err):
        path = getattr(err, "filename", None) or root
        out.unreadable.append(relative(root, path))

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        if cancel is not None and cancel():
            out.canceled = True
            return out
        rel_dir = relative(root, dirpath)
        keep = []
        for d in sorted(dirnames, key=str.lower):
            if _system_hidden(dirpath, d):
                continue
            rel_sub = f"{rel_dir}/{d}" if rel_dir else d
            if ws.is_hidden(rel_sub) and not show_hidden:
                out.hidden_skipped += 1
                continue
            keep.append(d)
        dirnames[:] = keep

        pdfs = [f for f in filenames if f.lower().endswith(".pdf")]
        if not pdfs:
            continue
        present = {os.path.normcase(os.path.join(dirpath, f)) for f in filenames}

        def exists(p, present=present):
            return os.path.normcase(p) in present

        seen = {}
        for f in pdfs:
            full = os.path.join(dirpath, f)
            key = R.drawing_key(full)
            if key in seen:
                continue
            target = R.open_target(full, exists=exists)
            members = [p for p in (original_pdf_path(full), marked_pdf_path(full))
                       if exists(p)]
            try:
                modified = max(os.path.getmtime(p) for p in members)
            except (OSError, ValueError):
                modified = 0.0
            seen[key] = WorkspaceFile(
                rel=relative(root, target), path=os.path.normpath(target),
                folder=rel_dir, modified=modified,
                hidden=ws.is_hidden(rel_dir) if rel_dir else False)
        if seen:
            folders_with_files.add(rel_dir)
            out.files.extend(sorted(seen.values(), key=lambda wf: wf.name.lower()))

    out.folders = len(folders_with_files)
    out.files.sort(key=lambda wf: (wf.folder.lower(), wf.name.lower()))
    return out


# --- where a file can be added ------------------------------------------------

def subfolders(root: str) -> list:
    """The folders directly under ``root``, by name, leaving out dot-folders
    and folders the OS marks hidden or system."""
    try:
        names = [e.name for e in os.scandir(root)
                 if e.is_dir() and not _system_hidden(root, e.name)]
    except OSError:
        return []
    return sorted(names, key=str.lower)


def destinations(ws: Workspace, quick: Iterable[str]) -> tuple:
    """(quick folders, other folders) a file can be added to: the quick
    subfolders first, whether or not they exist yet -- they are created on
    first use -- then every other folder at the workspace's top level, except
    ones the user hid from it."""
    quick = [q for q in quick if q]
    taken = {rel_key(q) for q in quick}
    others = [d for d in subfolders(ws.root)
              if rel_key(d) not in taken and not ws.is_hidden(d)]
    return quick, others

