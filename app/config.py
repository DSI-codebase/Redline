"""Persisted settings (QSettings) + defaults.

Wraps QSettings and produces the plain, Qt-free config objects the extraction
and export layers consume (so those layers never read QSettings directly).
"""

from __future__ import annotations

import getpass
import json
import os
from typing import Any

from PySide6.QtCore import QSettings

from .extraction.wire_parser import WireConfig
from .extraction.component_parser import ComponentConfig, DEFAULT_FAMILY_CODES
from .export.wire_export import WireExportOptions, SORT_NUMERICAL
from .model.storage import DEFAULT_IGNORE_PATTERNS

ORG = "PDFMarkup"
APP = "PDFMarkupApp"

# how many paths the File ▸ Open Recent list remembers
MAX_RECENT_FILES = 10
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
    # design rule check
    "audit/packs": json.dumps(["drc-base"]),
    "audit/disabled_rules": json.dumps([]),
    "audit/severity_overrides": json.dumps({}),
    "audit/draw_on_sheet": True,
    "audit/oda_path": "",
    # File ▸ Open Recent (most-recent-first list of PDF paths)
    "recent/files": json.dumps([]),
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
    def recent_files(self) -> list:
        """Recently opened PDF paths, most recent first."""
        raw = self.get("recent/files")
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(val, list):
                return [str(p) for p in val][:MAX_RECENT_FILES]
        except Exception:
            pass
        return []

    def set_recent_files(self, paths: list) -> None:
        self.set("recent/files",
                 json.dumps([str(p) for p in paths][:MAX_RECENT_FILES]))

    def add_recent_file(self, path: str) -> list:
        """Move ``path`` to the top of the recent list and return the new list.

        Paths are stored absolute and de-duplicated case-insensitively (so the
        same file opened via a different spelling doesn't take two slots), and
        the list is capped at :data:`MAX_RECENT_FILES`.
        """
        p = os.path.abspath(str(path))
        key = os.path.normcase(p)
        out = [p] + [q for q in self.recent_files if os.path.normcase(q) != key]
        out = out[:MAX_RECENT_FILES]
        self.set_recent_files(out)
        return out

    def clear_recent_files(self) -> None:
        self.set_recent_files([])

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
