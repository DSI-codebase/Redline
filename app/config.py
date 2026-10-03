"""Persisted settings (QSettings) + defaults.

Wraps QSettings and produces the plain, Qt-free config objects the extraction
and export layers consume (so those layers never read QSettings directly).
"""

from __future__ import annotations

import getpass
import json
import os
from typing import Any, Optional

from PySide6.QtCore import QSettings

from .extraction.wire_parser import WireConfig
from .extraction.component_parser import ComponentConfig, DEFAULT_FAMILY_CODES
from .export.wire_export import WireExportOptions, SORT_NUMERICAL
from .model.storage import DEFAULT_IGNORE_PATTERNS
from .model import recent as _recent
from .model import workspaces as _ws
from .model.annotations import now_iso

ORG = "PDFMarkup"
APP = "PDFMarkupApp"

# How many drawings the recent list remembers (Settings ▸ Files), and the bounds
# that setting is held to. The File view shows all of them; File ▸ Open Recent
# shows the newest MENU_RECENT_FILES, one per &1..&0 accelerator.
DEFAULT_RECENT_FILES = 50
RECENT_FILES_BOUNDS = (10, 200)
MENU_RECENT_FILES = 10
# each workspace's own recent list (Settings ▸ Files)
DEFAULT_WORKSPACE_RECENT = 25
WORKSPACE_RECENT_BOUNDS = (5, 100)
# the subfolders New workspace… creates (and Add to workspace offers first)
DEFAULT_QUICK_FOLDERS = ("drawings", "documentation", "notes")
MAX_RECENT_SEARCHES = 10

# Minimum line weight presets for printing, as (label, PDF points).
#
# AutoCAD plots most schematic geometry as a hairline — width 0, or 0.1-0.15 pt.
# A renderer cannot draw less than one device pixel, so at the 96 dpi the old
# print path was really using, every one of those came out 1 px = 1/96 in =
# 0.75 pt: fat, and fat is what people got used to. Rendering at 600 dpi honours
# the true width instead, and 0.12 pt on paper is anemic (many printers drop
# parts of it). CAD plotting has always solved this with a minimum pen width, so
# the app applies one too, and defaults it on.
PRINT_LINE_WEIGHTS = (
    ("As drawn (no minimum)", 0.0),
    ("Light — 0.25 pt", 0.25),
    ("Medium — 0.5 pt", 0.5),
    ("Heavy — 0.75 pt (matches older prints)", 0.75),
)


def _default_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "user"


DEFAULTS: dict = {
    "your_name": _default_user(),
    # wire field widths
    "wire/sheet_width": 3,
    "wire/rung_width": 2,
    "wire/wire_width": 1,
    "wire/zero_pad": True,
    "wire/regex_override": "",
    "wire/cross_check_sheet": False,
    "wire/extract_method": "ai",   # "ai" | "ocr" for scanned pages
    # component labels (FAMILY-SHEETRUNG, e.g. LT-10010)
    "component/sheet_width": 3,
    "component/rung_width": 2,
    "component/zero_pad": True,
    "component/families": json.dumps(list(DEFAULT_FAMILY_CODES)),
    "component/extract_method": "ai",   # "ai" | "ocr" for scanned pages
    "component/labels_per_device": 1,
    # export
    "export/labels_per_wire": 2,
    "export/mode": "single",        # "single" | "per_sheet"
    "export/format": "xlsx",         # "xlsx" | "csv"
    "export/sort": SORT_NUMERICAL,
    # comments / todo
    "comments/treat_all_as_todo": False,
    "filter/ignore_patterns": json.dumps(DEFAULT_IGNORE_PATTERNS),
    "filter/show_ignored": False,
    # ocr / ai
    "ocr/enabled": False,
    "ai/enabled": False,
    "ai/tiles": 2,          # NxN tiles per scanned page (1 = whole page)
    "ai/model": "claude-opus-4-8",
    "ai/api_key": "",
    # TypeSafe Jev decides sheet roles from title-block text when switched on;
    # off, the keyword table decides, exactly as before (docs/AI Assist.md)
    "jev/sheet_roles": False,
    "jev/api_key": "",
    # design rule check
    "audit/packs": json.dumps(["drc-base"]),
    "audit/disabled_rules": json.dumps([]),
    "audit/severity_overrides": json.dumps({}),
    "audit/draw_on_sheet": True,
    "audit/oda_path": "",
    # Recent files: most-recent-first PDF paths, one per drawing. Still a plain
    # list of paths, so a build from before open times were kept reads it.
    "recent/files": json.dumps([]),
    "recent/max": DEFAULT_RECENT_FILES,
    # {drawing key: ISO time it was last opened}, for the File view's groups
    "recent/opened": json.dumps({}),
    # pinned paths, in the order they were pinned; never aged out, never cleared
    "recent/pinned": json.dumps([]),
    # workspaces: declared folders, per user (nothing is written into them)
    "workspaces/list": json.dumps([]),
    "workspaces/selected": "",
    "workspaces/recent_max": DEFAULT_WORKSPACE_RECENT,
    "files/quick_folders": json.dumps(list(DEFAULT_QUICK_FOLDERS)),
    # Minimum printed line weight, in PDF points (0 = print widths as drawn).
    # See PRINT_LINE_WEIGHTS for why this defaults on.
    "print/min_line_pt": 0.5,
    # in-document search (Ctrl+F): option toggles + query history
    "search/case": False,
    "search/word": False,
    "search/regex": False,
    "search/marks": True,
    "search/recent": json.dumps([]),
}


class AppConfig:
    """Thin typed wrapper over QSettings."""

    def __init__(self):
        self.s = QSettings(ORG, APP)

    # -- generic get/set -----------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        if default is None:
            default = DEFAULTS.get(key)
        val = self.s.value(key, default)
        # QSettings stringifies bools/ints on some platforms - coerce by default
        if isinstance(default, bool):
            if isinstance(val, str):
                return val.lower() in ("1", "true", "yes", "on")
            return bool(val)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(val)
            except (ValueError, TypeError):
                return default
        return val

    def set(self, key: str, value: Any) -> None:
        self.s.setValue(key, value)

    def sync(self) -> None:
        self.s.sync()

    # -- typed convenience ---------------------------------------------------

    @property
    def your_name(self) -> str:
        return str(self.get("your_name"))

    @property
    def show_ignored(self) -> bool:
        return bool(self.get("filter/show_ignored"))

    @property
    def treat_all_as_todo(self) -> bool:
        return bool(self.get("comments/treat_all_as_todo"))

    def ignore_patterns(self) -> list:
        raw = self.get("filter/ignore_patterns")
        try:
            val = json.loads(raw) if isinstance(raw, str) else list(raw)
            if isinstance(val, list):
                return [str(p) for p in val]
        except Exception:
            pass
        return list(DEFAULT_IGNORE_PATTERNS)

    def set_ignore_patterns(self, patterns: list) -> None:
        self.set("filter/ignore_patterns", json.dumps(list(patterns)))

    # -- recently opened files ----------------------------------------------

    @property
    def recent_max(self) -> int:
        """How many drawings the recent list keeps (Settings ▸ Files)."""
        lo, hi = RECENT_FILES_BOUNDS
        return max(lo, min(hi, int(self.get("recent/max"))))

    def _path_list(self, key: str) -> list:
        raw = self.get(key)
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(val, list):
                return [str(p) for p in val]
        except Exception:
            pass
        return []

    @property
    def recent_files(self) -> list:
        """Recently opened PDF paths, most recent first, one per drawing."""
        return _recent.dedupe(self._path_list("recent/files"))[:self.recent_max]

    def set_recent_files(self, paths: list) -> None:
        kept = _recent.dedupe(str(p) for p in paths)[:self.recent_max]
        self.set("recent/files", json.dumps(kept))
        self._prune_opened()

    def _opened_map(self) -> dict:
        return {str(k): str(v) for k, v in
                self._json_setting("recent/opened", {}).items()}

    def _prune_opened(self) -> None:
        """Drop open times for drawings neither listed nor pinned."""
        live = {_recent.drawing_key(p) for p in
                self._path_list("recent/files") + self.pinned_files}
        times = self._opened_map()
        kept = {k: v for k, v in times.items() if k in live}
        if kept != times:
            self.set("recent/opened", json.dumps(kept))

    def recent_opened(self, path: str) -> str:
        """When the drawing ``path`` names was last opened (ISO), or ``""``."""
        return self._opened_map().get(_recent.drawing_key(path), "")

    def add_recent_file(self, path: str, when: Optional[str] = None) -> list:
        """Move ``path`` to the top of the recent list and return the new list.

        Stored absolute. Any entry for the same DRAWING goes -- a different
        spelling of the path, or ``foo.marked.pdf`` after ``foo.pdf`` -- so one
        drawing never takes two slots. ``when`` defaults to now.
        """
        p = os.path.abspath(str(path))
        key = _recent.drawing_key(p)
        times = self._opened_map()
        times[key] = when or now_iso()
        self.set("recent/opened", json.dumps(times))
        rest = [q for q in self._path_list("recent/files")
                if _recent.drawing_key(q) != key]
        self.set_recent_files([p] + rest)
        return self.recent_files

    def remove_recent_file(self, path: str) -> None:
        """Take the drawing ``path`` names off the recent list (not its pin)."""
        key = _recent.drawing_key(path)
        self.set_recent_files([q for q in self._path_list("recent/files")
                               if _recent.drawing_key(q) != key])

    def clear_recent_files(self) -> None:
        """Empty the recent list. Pins are a separate list and stay."""
        self.set_recent_files([])

    @property
    def pinned_files(self) -> list:
        """Pinned PDF paths, in the order they were pinned, one per drawing."""
        return _recent.dedupe(self._path_list("recent/pinned"))

    def is_pinned(self, path: str) -> bool:
        key = _recent.drawing_key(path)
        return any(_recent.drawing_key(p) == key for p in self.pinned_files)

    def pin_file(self, path: str) -> None:
        if not self.is_pinned(path):
            self.set("recent/pinned", json.dumps(
                self.pinned_files + [os.path.abspath(str(path))]))

    def unpin_file(self, path: str) -> None:
        key = _recent.drawing_key(path)
        self.set("recent/pinned", json.dumps(
            [p for p in self.pinned_files if _recent.drawing_key(p) != key]))
        self._prune_opened()

    # -- workspaces ----------------------------------------------------------

    def workspaces(self) -> list:
        """Every declared workspace, in the order they were added."""
        return [_ws.Workspace.from_dict(d)
                for d in self._json_setting("workspaces/list", [])
                if isinstance(d, dict) and d.get("root")]

    def _save_workspaces(self, items) -> None:
        self.set("workspaces/list", json.dumps([w.to_dict() for w in items]))

    def find_workspace(self, root: str):
        key = _ws._key(root)
        return next((w for w in self.workspaces() if _ws._key(w.root) == key), None)

    def add_workspace(self, root: str, name: str = ""):
        """Declare the folder ``root`` a workspace. Refuses a missing folder and
        one that would nest with another workspace, naming it."""
        root = _ws.norm_root(root)
        if not os.path.isdir(root):
            raise _ws.WorkspaceError(f"“{root}” is not a folder.")
        clash = _ws.overlap(root, self.workspaces())
        if clash is not None:
            raise _ws.WorkspaceError(_ws.nesting_message(root, clash))
        ws = _ws.Workspace(root=root, name=name.strip(), last_used=now_iso())
        self._save_workspaces(self.workspaces() + [ws])
        return ws

    def create_workspace(self, parent: str, name: str):
        """New workspace…: make ``parent/name`` with the quick subfolders and
        declare it. The nesting check runs FIRST, so a refusal leaves no folder
        behind on disk."""
        root = _ws.norm_root(os.path.join(parent, (name or "").strip()))
        clash = _ws.overlap(root, self.workspaces())
        if clash is not None:
            raise _ws.WorkspaceError(_ws.nesting_message(root, clash))
        _ws.create_workspace(parent, name, self.quick_folders())
        return self.add_workspace(root)

    def update_workspace(self, ws) -> None:
        """Store ``ws`` over the workspace with the same root."""
        key = _ws._key(ws.root)
        self._save_workspaces([ws if _ws._key(w.root) == key else w
                               for w in self.workspaces()])

    def relocate_workspace(self, old_root: str, new_root: str):
        """Point a workspace at its folder's new location (Locate…). Everything
        it remembers is relative, so favorites and hidden folders carry over."""
        ws = self.find_workspace(old_root)
        if ws is None:
            raise _ws.WorkspaceError(f"“{old_root}” is not a workspace.")
        new_root = _ws.norm_root(new_root)
        if not os.path.isdir(new_root):
            raise _ws.WorkspaceError(f"“{new_root}” is not a folder.")
        clash = _ws.overlap(new_root, self.workspaces(), ignore=old_root)
        if clash is not None:
            raise _ws.WorkspaceError(_ws.nesting_message(new_root, clash))
        key = _ws._key(old_root)
        was_selected = _ws._key(self.selected_workspace_root or "") == key
        items = self.workspaces()
        for w in items:
            if _ws._key(w.root) == key:
                w.root = new_root
                ws = w
        self._save_workspaces(items)
        if was_selected:
            self.set("workspaces/selected", new_root)
        return ws

    def remove_workspace(self, root: str) -> None:
        """Take a workspace off the list. The folder is never touched."""
        key = _ws._key(root)
        self._save_workspaces([w for w in self.workspaces()
                               if _ws._key(w.root) != key])
        if _ws._key(self.selected_workspace_root or "") == key:
            self.set("workspaces/selected", "")

    @property
    def selected_workspace_root(self) -> str:
        return str(self.get("workspaces/selected") or "")

    def select_workspace(self, root: str) -> None:
        """The workspace the user last opened in the File view."""
        ws = self.find_workspace(root)
        if ws is None:
            return
        self.set("workspaces/selected", ws.root)
        ws.last_used = now_iso()
        self.update_workspace(ws)

    def workspace_for(self, path: str):
        return _ws.containing(self.workspaces(), path)

    def current_workspace(self, open_path: Optional[str] = None):
        """The workspace holding the open file, else the one last selected."""
        if open_path:
            ws = self.workspace_for(open_path)
            if ws is not None:
                return ws
        return self.find_workspace(self.selected_workspace_root) \
            if self.selected_workspace_root else None

    def record_workspace_open(self, path: str, when: Optional[str] = None):
        """Put an opened file on its workspace's own recent list -- whatever
        route opened it. Returns the workspace, or ``None`` when it is in none."""
        ws = self.workspace_for(path)
        if ws is None:
            return None
        ws.record_open(_ws.relative(ws.root, path), when or now_iso(),
                       self.workspace_recent_max)
        self.update_workspace(ws)
        return ws

    @property
    def workspace_recent_max(self) -> int:
        lo, hi = WORKSPACE_RECENT_BOUNDS
        return max(lo, min(hi, int(self.get("workspaces/recent_max"))))

    def quick_folders(self) -> list:
        names = [str(n).strip() for n in self._json_setting("files/quick_folders", [])]
        return [n for n in names if n] or list(DEFAULT_QUICK_FOLDERS)

    def set_quick_folders(self, names) -> None:
        cleaned, seen = [], set()
        for n in names:
            n = str(n).strip().strip("/\\")
            if n and n.lower() not in seen:
                seen.add(n.lower())
                cleaned.append(n)
        self.set("files/quick_folders", json.dumps(cleaned))

    # -- search history ------------------------------------------------------

    @property
    def recent_searches(self) -> list:
        """Recently committed Ctrl+F queries, most recent first."""
        raw = self.get("search/recent")
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(val, list):
                return [str(q) for q in val][:MAX_RECENT_SEARCHES]
        except Exception:
            pass
        return []

    def add_recent_search(self, query: str) -> list:
        """Move ``query`` to the top of the search history (deduplicated
        case-insensitively, capped at :data:`MAX_RECENT_SEARCHES`)."""
        q = str(query).strip()
        if not q:
            return self.recent_searches
        out = [q] + [p for p in self.recent_searches if p.lower() != q.lower()]
        out = out[:MAX_RECENT_SEARCHES]
        self.set("search/recent", json.dumps(out))
        return out

    def clear_recent_searches(self) -> None:
        self.set("search/recent", json.dumps([]))

    # -- printing ------------------------------------------------------------

    @property
    def print_min_line_pt(self) -> float:
        """Minimum line weight for printing, in PDF points (0 = as drawn)."""
        try:
            v = float(self.get("print/min_line_pt"))
        except (TypeError, ValueError):
            return 0.0
        return v if 0.0 <= v <= 4.0 else 0.0

    # -- derived config objects ---------------------------------------------

    def wire_config(self) -> WireConfig:
        return WireConfig(
            sheet_width=int(self.get("wire/sheet_width")),
            rung_width=int(self.get("wire/rung_width")),
            wire_width=int(self.get("wire/wire_width")),
            zero_pad=bool(self.get("wire/zero_pad")),
            regex_override=str(self.get("wire/regex_override") or ""),
            cross_check_sheet=bool(self.get("wire/cross_check_sheet")),
        )

    def component_families(self) -> list:
        raw = self.get("component/families")
        try:
            val = json.loads(raw) if isinstance(raw, str) else list(raw)
            if isinstance(val, list):
                return [str(f).strip().upper() for f in val if str(f).strip()]
        except Exception:
            pass
        return list(DEFAULT_FAMILY_CODES)

    def set_component_families(self, families: list) -> None:
        cleaned = []
        seen = set()
        for f in families:
            f = str(f).strip().upper()
            if f and f not in seen:
                seen.add(f)
                cleaned.append(f)
        self.set("component/families", json.dumps(cleaned))

    def component_config(self) -> ComponentConfig:
        return ComponentConfig(
            sheet_width=int(self.get("component/sheet_width")),
            rung_width=int(self.get("component/rung_width")),
            zero_pad=bool(self.get("component/zero_pad")),
            families=tuple(self.component_families()),
        )

    @property
    def wire_extract_method(self) -> str:
        m = str(self.get("wire/extract_method") or "ai").lower()
        return m if m in ("ai", "ocr") else "ai"

    @property
    def component_extract_method(self) -> str:
        m = str(self.get("component/extract_method") or "ai").lower()
        return m if m in ("ai", "ocr") else "ai"

    @property
    def component_labels_per_device(self) -> int:
        return max(1, int(self.get("component/labels_per_device")))

    def export_options(self) -> WireExportOptions:
        return WireExportOptions(
            fmt=str(self.get("export/format")),
            labels_per_wire=int(self.get("export/labels_per_wire")),
            sort=str(self.get("export/sort")),
        )

    # -- design rule check ---------------------------------------------------

    def _json_setting(self, key: str, fallback):
        """A JSON-encoded setting, falling back when it is missing or corrupt.

        QSettings values are strings; the same shape as component_families and
        ignore_patterns, which store lists this way.
        """
        raw = self.get(key, DEFAULTS[key])
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return fallback
        return value if isinstance(value, type(fallback)) else fallback

    def audit_packs(self) -> list:
        packs = self._json_setting("audit/packs", ["drc-base"])
        return [str(p) for p in packs if str(p).strip()] or ["drc-base"]

    def set_audit_packs(self, packs: list) -> None:
        self.set("audit/packs", json.dumps([str(p) for p in packs]))

    def audit_disabled_rules(self) -> list:
        return [str(r) for r in self._json_setting("audit/disabled_rules", [])]

    def set_audit_disabled_rules(self, rules) -> None:
        self.set("audit/disabled_rules", json.dumps(sorted(set(map(str, rules)))))

    def audit_severity_overrides(self) -> dict:
        raw = self._json_setting("audit/severity_overrides", {})
        return {str(k): str(v) for k, v in raw.items()}

    def set_audit_severity_overrides(self, overrides: dict) -> None:
        self.set("audit/severity_overrides",
                 json.dumps({str(k): str(v) for k, v in (overrides or {}).items()}))

    def audit_draw_on_sheet(self) -> bool:
        return bool(self.get("audit/draw_on_sheet", True))

    def oda_converter_path(self) -> str:
        return str(self.get("audit/oda_path", "") or "")

    def author(self) -> str:
        """Who to attribute a waiver to — the name marks are already signed with."""
        return self.your_name

    @property
    def ocr_enabled(self) -> bool:
        return bool(self.get("ocr/enabled"))

    @property
    def ai_enabled(self) -> bool:
        return bool(self.get("ai/enabled"))

    @property
    def ai_model(self) -> str:
        return str(self.get("ai/model"))

    @property
    def ai_api_key(self) -> str:
        return str(self.get("ai/api_key") or "")

    @property
    def ai_tiles(self) -> int:
        return max(1, min(4, int(self.get("ai/tiles"))))

    @property
    def jev_sheet_roles(self) -> bool:
        return bool(self.get("jev/sheet_roles"))

    @property
    def jev_api_key(self) -> str:
        return str(self.get("jev/api_key") or "")
