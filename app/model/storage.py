"""Hybrid storage: PyMuPDF annotation I/O + SQLite sidecar (Phase 3).

* The **marked PDF** (``<name>.marked.pdf``) is the portable artifact - every
  mark is written as a standard PDF annotation so anyone can view it, and any
  *external* annotations found in an opened PDF (e.g. markups received from a
  colleague) are imported with their real author.
* The **sidecar** (``<name>.markup.db``) is the source of truth for app-only
  state (TODO done/undone, tags, priority, extra text-box styling, the wire
  cache) and stores the full annotation model so nothing is lost on round-trip.

GUI-free.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

import fitz  # PyMuPDF

from .annotations import (
    Annotation, now_iso,
    KIND_HIGHLIGHT, KIND_PEN, KIND_COMMENT, KIND_TEXTBOX, KIND_RECT, KIND_CIRCLE,
    KIND_ARROW, KIND_LINE, KIND_CALLOUT, KIND_CLOUD,
)

# Seeded SHX / AutoCAD junk ignore-patterns (regex, may use inline (?i)).
DEFAULT_IGNORE_PATTERNS = [
    r"SHX",
    r"(?i)font.*could not",
    r"(?i)could not be displayed",
    r"(?i)comment from autocad",
    r"(?i)autocad",
    r"(?i)produced by an autodesk",
]

# Map PyMuPDF annotation type-name -> our kind.
_PDF_TYPE_TO_KIND = {
    "Text": KIND_COMMENT,
    "FreeText": KIND_TEXTBOX,
    "Highlight": KIND_HIGHLIGHT,
    "Ink": KIND_PEN,
    "Square": KIND_RECT,
    "Circle": KIND_CIRCLE,
    "Line": KIND_ARROW,   # refined to KIND_LINE when it has no arrowhead
    "Polygon": KIND_CLOUD,
}

# /NM suffix marking an auxiliary sticky-note we emit for a *noted* non-text mark
# (so the note shows as a comment in every viewer). Skipped on reload — the note
# text already round-trips on the parent mark's /Contents.
_NOTE_SUFFIX = "#note"


# --- date helpers -----------------------------------------------------------


def pdf_date_to_iso(value: Optional[str]) -> str:
    """Convert a PDF date (``D:YYYYMMDDHHmmSS+hh'mm'``) to ISO-8601.

    Falls back to the current time when the value is missing/unparseable.
    """
    if not value:
        return now_iso()
    s = value.strip()
    if s.startswith("D:"):
        s = s[2:]
    s = s.replace("'", "")
    m = re.match(r"(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", s)
    if not m:
        return now_iso()
    y = int(m.group(1))
    mo = int(m.group(2) or 1)
    d = int(m.group(3) or 1)
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    ss = int(m.group(6) or 0)
    try:
        dt = datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
        return dt.astimezone().isoformat(timespec="seconds")
    except ValueError:
        return now_iso()


# --- ignore (SHX junk) filter ----------------------------------------------


def compile_ignore_patterns(patterns: Iterable[str]) -> list:
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p))
        except re.error:
            continue
    return compiled


def text_is_ignored(text: str, compiled_patterns: list) -> bool:
    if not text:
        return False
    return any(rx.search(text) for rx in compiled_patterns)


# --- reading PDF annotations ------------------------------------------------


def _color_or_default(colors: dict, key: str, default):
    seq = (colors or {}).get(key) or []
    if len(seq) >= 3:
        return (float(seq[0]), float(seq[1]), float(seq[2]))
    return default


def load_pdf_annotations(
    doc: "fitz.Document",
    ignore_patterns: Optional[Iterable[str]] = None,
) -> list:
    """Read existing PDF annotations into :class:`Annotation` objects.

    Authors come from the annotation ``title`` (PDF ``/T``); creation/mod dates
    are parsed from the PDF date strings.  Marks matching the junk filter are
    flagged ``ignored=True`` (hidden, never deleted).
    """
    compiled = compile_ignore_patterns(
        ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS
    )
    out: list = []
    for pno in range(doc.page_count):
        page = doc[pno]
        # PDF annotation geometry is in unrotated user space; rotate it into the
        # viewer's (visual) space so it lines up on rotated pages. Identity when
        # the page isn't rotated.
        rotm = page.rotation_matrix
        for annot in page.annots() or []:
            try:
                tname = annot.type[1]
            except Exception:
                continue
            kind = _PDF_TYPE_TO_KIND.get(tname)
            if kind is None:
                continue
            info = annot.info or {}
            # skip the auxiliary sticky-notes we emit for noted non-text marks —
            # the note already lives on its parent mark's /Contents
            if (info.get("name") or "").endswith(_NOTE_SUFFIX):
                continue
            rect = annot.rect * rotm
            colors = annot.colors or {}
            ann = Annotation(
                page=pno,
                kind=kind,
                rect=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                color=_color_or_default(colors, "stroke", (1.0, 0.85, 0.0)),
                author=info.get("title", "") or "",
                created=pdf_date_to_iso(info.get("creationDate")),
                modified=pdf_date_to_iso(info.get("modDate")),
                text=info.get("content", "") or "",
                source="pdf",
                pdf_xref=annot.xref,
            )
            # geometry refinements
            if kind == KIND_PEN:
                try:
                    verts = annot.vertices or []
                    # ink vertices come as a list of strokes
                    pts = []
                    for stroke in verts:
                        if isinstance(stroke, (list, tuple)) and stroke and isinstance(stroke[0], (list, tuple)):
                            pts.extend(tuple(fitz.Point(p[0], p[1]) * rotm) for p in stroke)
                        else:
                            pts.append(tuple(fitz.Point(stroke[0], stroke[1]) * rotm))
                    ann.points = pts
                except Exception:
                    pass
            if kind == KIND_CLOUD:
                try:
                    verts = annot.vertices or []
                    ann.points = [tuple(fitz.Point(p[0], p[1]) * rotm) for p in verts]
                except Exception:
                    pass
            if kind == KIND_TEXTBOX:
                ann.font_size = float(info.get("fontsize", 11) or 11)
                # A FreeText's fill is stored in /C (reported under 'stroke'); its
                # text color lives in /DA (not exposed here) so default it black.
                fc = _color_or_default(colors, "stroke", None)
                if fc is not None:
                    ann.fill_color = fc
                    ann.color = (0.0, 0.0, 0.0)
                    try:
                        op = annot.opacity
                        if op is not None and 0.0 <= float(op) <= 1.0:
                            ann.fill_opacity = float(op)
                    except Exception:
                        pass
            elif kind == KIND_ARROW:
                # both arrows and plain lines are PDF "Line" annots — an arrow is
                # the one carrying an arrowhead line-ending
                try:
                    ends = annot.line_ends
                except Exception:
                    ends = None
                if not (ends and any(int(e) != 0 for e in ends)):
                    ann.kind = kind = KIND_LINE
            elif kind in (KIND_RECT, KIND_CIRCLE):
                fill = _color_or_default(colors, "fill", None)   # /IC
                if fill is not None:
                    ann.fill_color = fill
                    try:
                        op = annot.opacity
                        if op is not None and 0.0 <= float(op) <= 1.0:
                            ann.fill_opacity = float(op)
                    except Exception:
                        pass
            # carry the /NM name so the sidecar can re-link app state
            name = info.get("name") or ""
            if name:
                ann.id = name
            # junk filter
            if text_is_ignored(ann.text, compiled) or text_is_ignored(ann.author, compiled):
                ann.ignored = True
            out.append(ann)
    return out


# --- writing PDF annotations ------------------------------------------------


def _apply_common(annot, ann: Annotation) -> None:
    info = {"title": ann.author or "", "content": ann.text or ""}
    try:
        annot.set_info(info)
    except Exception:
        pass
    try:
        annot.set_name(ann.id)  # /NM - links back to the sidecar on reload
    except Exception:
        pass


def write_annotations_to_pdf(doc: "fitz.Document", annotations: Iterable[Annotation],
                             include_ignored: bool = False) -> int:
    """Write our marks into ``doc`` as standard PDF annotations.

    The caller is responsible for saving ``doc`` to the ``.marked.pdf`` path.
    Returns the number of annotations written.
    """
    written = 0
    # write in stacking order so higher-z marks are added last (drawn on top)
    annotations = sorted(annotations, key=lambda a: getattr(a, "z_order", 0.0))
    for ann in annotations:
        if ann.ignored and not include_ignored:
            continue
        if ann.page < 0 or ann.page >= doc.page_count:
            continue
        page = doc[ann.page]
        # Our model coordinates are in the *rotated* (visual) page space - the
        # same space the viewer renders and get_text() reports. PDF annotations,
        # however, live in unrotated user space, so transform by the page's
        # derotation matrix (identity when the page isn't rotated). FreeText also
        # needs the page rotation applied so the text reads upright.
        derot = page.derotation_matrix
        prot = page.rotation
        x0, y0, x1, y1 = ann.rect
        rect = fitz.Rect(x0, y0, x1, y1) * derot
        p0 = fitz.Point(x0, y0) * derot
        p1 = fitz.Point(x1, y1) * derot
        annot = None
        try:
            if ann.kind == KIND_HIGHLIGHT:
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=ann.color)
                try:
                    annot.set_opacity(ann.opacity)
                except Exception:
                    pass
            elif ann.kind == KIND_PEN and ann.points:
                stroke = [tuple(fitz.Point(px, py) * derot) for px, py in ann.points]
                annot = page.add_ink_annot([stroke])
                annot.set_colors(stroke=ann.color)
                annot.set_border(width=ann.width)
            elif ann.kind == KIND_COMMENT:
                annot = page.add_text_annot(p0, ann.text or "", icon="Comment")
                # an explicit popup makes the note open as a genuine comment in
                # Adobe / Chrome / other PDF viewers
                try:
                    annot.set_popup(fitz.Rect(x0 + 20, y0, x0 + 220, y0 + 90) * derot)
                except Exception:
                    pass
            elif ann.kind == KIND_TEXTBOX:
                ft_kwargs = dict(fontsize=ann.font_size, text_color=ann.color,
                                 rotate=prot)
                if ann.fill_color is not None:
                    ft_kwargs["fill_color"] = ann.fill_color
                annot = page.add_freetext_annot(rect, ann.text or "", **ft_kwargs)
                if ann.fill_color is not None and ann.fill_opacity < 1.0:
                    try:
                        annot.set_opacity(ann.fill_opacity)
                    except Exception:
                        pass
            elif ann.kind in (KIND_RECT, KIND_CIRCLE):
                annot = (page.add_circle_annot(rect) if ann.kind == KIND_CIRCLE
                         else page.add_rect_annot(rect))
                if ann.fill_color is not None:
                    annot.set_colors(stroke=ann.color, fill=ann.fill_color)
                else:
                    annot.set_colors(stroke=ann.color)
                annot.set_border(width=ann.width)
                if ann.fill_color is not None and ann.fill_opacity < 1.0:
                    try:
                        annot.set_opacity(ann.fill_opacity)
                    except Exception:
                        pass
            elif ann.kind in (KIND_ARROW, KIND_LINE):
                annot = page.add_line_annot(p0, p1)
                annot.set_colors(stroke=ann.color)
                annot.set_border(width=ann.width)
                if ann.kind == KIND_ARROW:
                    try:
                        annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE,
                                            fitz.PDF_ANNOT_LE_OPEN_ARROW)
                    except Exception:
                        pass
            elif ann.kind == KIND_CALLOUT:
                # a FreeText with a leader (CL) from the box to the tip point
                tip = ann.callout_point or (x0 - 36.0, y1 + 36.0)
                ax = min(max(tip[0], min(x0, x1)), max(x0, x1))
                ay = min(max(tip[1], min(y0, y1)), max(y0, y1))
                cl = [fitz.Point(tip[0], tip[1]) * derot,
                      fitz.Point(ax, ay) * derot]
                base_kwargs = dict(fontsize=ann.font_size, text_color=ann.color,
                                   rotate=prot)
                if ann.fill_color is not None:
                    base_kwargs["fill_color"] = ann.fill_color
                try:
                    # the callout leader (CL/FreeTextCallout) needs PyMuPDF >= 1.25
                    annot = page.add_freetext_annot(
                        rect, ann.text or "", callout=cl,
                        line_end=fitz.PDF_ANNOT_LE_OPEN_ARROW, **base_kwargs)
                except TypeError:
                    # older PyMuPDF: degrade to a plain text box (no leader)
                    annot = page.add_freetext_annot(rect, ann.text or "",
                                                    **base_kwargs)
                if ann.fill_color is not None and ann.fill_opacity < 1.0:
                    try:
                        annot.set_opacity(ann.fill_opacity)
                    except Exception:
                        pass
            elif ann.kind == KIND_CLOUD and ann.points and len(ann.points) >= 3:
                poly = [tuple(fitz.Point(px, py) * derot) for px, py in ann.points]
                annot = page.add_polygon_annot(poly)
                annot.set_colors(stroke=ann.color)
                try:
                    annot.set_border(width=ann.width, clouds=2)  # revision-cloud BE
                except Exception:
                    annot.set_border(width=ann.width)
        except Exception:
            annot = None
        if annot is not None:
            _apply_common(annot, ann)
            try:
                annot.update()
            except Exception:
                pass
            written += 1
            # A note on a non-text mark (highlight / pen / rect / arrow / cloud)
            # also gets a standalone sticky-note comment so it's visibly a comment
            # in every viewer (Adobe, browsers, Preview). It carries a distinct
            # /NM so it's skipped on reload — the note text already round-trips on
            # the parent mark's /Contents.
            if (ann.kind not in (KIND_COMMENT, KIND_TEXTBOX, KIND_CALLOUT)
                    and (ann.text or "").strip()):
                try:
                    note_pt = fitz.Point(max(x0, x1), min(y0, y1)) * derot
                    note = page.add_text_annot(note_pt, ann.text, icon="Comment")
                    note.set_info({"title": ann.author or "", "content": ann.text})
                    note.set_name(f"{ann.id}{_NOTE_SUFFIX}")
                    try:
                        note.set_popup(fitz.Rect(note_pt.x + 18, note_pt.y,
                                                 note_pt.x + 218, note_pt.y + 90))
                    except Exception:
                        pass
                    note.update()
                except Exception:
                    pass
    return written


# --- SQLite sidecar ---------------------------------------------------------


class SidecarDB:
    """``<name>.markup.db`` - app-only state, full annotation cache, wire cache."""

    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        c = self.conn
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS annotations (
                id TEXT PRIMARY KEY,
                page INTEGER,
                kind TEXT,
                is_todo INTEGER,
                todo_done INTEGER,
                ignored INTEGER,
                "order" INTEGER,
                json TEXT
            );
            CREATE TABLE IF NOT EXISTS wires (
                label TEXT,
                sheet INTEGER,
                rung INTEGER,
                wire_index INTEGER,
                wire_type TEXT,
                page INTEGER,
                source TEXT,
                count INTEGER,
                included INTEGER,
                flags TEXT
            );
            CREATE TABLE IF NOT EXISTS components (
                label TEXT,
                family TEXT,
                number TEXT,
                sheet INTEGER,
                rung INTEGER,
                comp_type TEXT,
                page INTEGER,
                source TEXT,
                count INTEGER,
                included INTEGER,
                flags TEXT
            );
            CREATE TABLE IF NOT EXISTS findings (
                key TEXT PRIMARY KEY,
                rule_id TEXT,
                severity TEXT,
                status TEXT,
                page INTEGER,
                sheet TEXT,
                subject_id TEXT,
                message TEXT,
                clause TEXT,
                json TEXT
            );
            CREATE TABLE IF NOT EXISTS waivers (
                key TEXT PRIMARY KEY,
                rule_id TEXT,
                subject_id TEXT,
                reason TEXT,
                author TEXT,
                created TEXT,
                json TEXT
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        c.commit()

    # -- annotations ---------------------------------------------------------

    def save_annotations(self, annotations: Iterable[Annotation]) -> None:
        rows = [
            (
                a.id, a.page, a.kind, int(a.is_todo), int(a.todo_done),
                int(a.ignored), a.order, json.dumps(a.to_dict()),
            )
            for a in annotations
        ]
        self.conn.execute("DELETE FROM annotations")
        self.conn.executemany(
            'INSERT OR REPLACE INTO annotations '
            '(id, page, kind, is_todo, todo_done, ignored, "order", json) '
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def load_annotations(self) -> list:
        cur = self.conn.execute("SELECT json FROM annotations")
        out = []
        for row in cur.fetchall():
            try:
                out.append(Annotation.from_dict(json.loads(row["json"])))
            except Exception:
                continue
        return out

    def app_state_map(self) -> dict:
        """``id -> {app-only fields}`` for re-linking imported PDF annots."""
        cur = self.conn.execute("SELECT id, json FROM annotations")
        out: dict = {}
        for row in cur.fetchall():
            try:
                out[row["id"]] = json.loads(row["json"])
            except Exception:
                continue
        return out

    # -- wire cache ----------------------------------------------------------

    def save_wires(self, wires: Iterable) -> None:
        self.conn.execute("DELETE FROM wires")
        rows = [
            (
                w.label, w.sheet, w.rung, w.wire_index, w.wire_type,
                w.page, w.source, w.count, int(w.included),
                json.dumps(list(w.flags)),
            )
            for w in wires
        ]
        self.conn.executemany(
            "INSERT INTO wires (label, sheet, rung, wire_index, wire_type, "
            "page, source, count, included, flags) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def load_wires(self) -> list:
        from ..extraction.wire_parser import WireNumber
        cur = self.conn.execute("SELECT * FROM wires")
        out = []
        for r in cur.fetchall():
            try:
                out.append(WireNumber(
                    label=r["label"], sheet=r["sheet"], rung=r["rung"],
                    wire_index=r["wire_index"], wire_type=r["wire_type"],
                    page=r["page"], source=r["source"], count=r["count"],
                    included=bool(r["included"]),
                    flags=json.loads(r["flags"] or "[]"),
                ))
            except Exception:
                continue
        return out

    # -- component cache -----------------------------------------------------

    def save_components(self, components: Iterable) -> None:
        self.conn.execute("DELETE FROM components")
        rows = [
            (
                c.label, c.family, c.number, c.sheet, c.rung, c.comp_type,
                c.page, c.source, c.count, int(c.included),
                json.dumps(list(c.flags)),
            )
            for c in components
        ]
        self.conn.executemany(
            "INSERT INTO components (label, family, number, sheet, rung, "
            "comp_type, page, source, count, included, flags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def load_components(self) -> list:
        from ..extraction.component_parser import ComponentLabel
        try:
            cur = self.conn.execute("SELECT * FROM components")
        except Exception:
            return []
        out = []
        for r in cur.fetchall():
            try:
                out.append(ComponentLabel(
                    label=r["label"], family=r["family"], number=r["number"],
                    sheet=r["sheet"], rung=r["rung"], comp_type=r["comp_type"],
                    page=r["page"], source=r["source"], count=r["count"],
                    included=bool(r["included"]),
                    flags=json.loads(r["flags"] or "[]"),
                ))
            except Exception:
                continue
        return out

    # -- audit findings ------------------------------------------------------

    def save_findings(self, findings: Iterable) -> None:
        """Replace the stored findings wholesale.

        An audit re-run is the authority on what is currently wrong, so this
        clears first: a rule that no longer fires must not leave a stale finding
        behind. Waivers are deliberately a separate table for exactly this
        reason -- they outlive the findings they were made about.
        """
        self.conn.execute("DELETE FROM findings")
        rows = [
            (
                f.key, f.rule_id, f.severity, f.status, int(f.page or 0),
                f.sheet, f.subject_id, f.message, f.clause,
                json.dumps(f.to_dict()),
            )
            for f in findings
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO findings (key, rule_id, severity, status, "
            "page, sheet, subject_id, message, clause, json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def load_findings(self) -> list:
        from ..audit.findings import Finding
        try:
            cur = self.conn.execute("SELECT json FROM findings")
        except Exception:
            return []
        out = []
        for r in cur.fetchall():
            try:
                out.append(Finding.from_dict(json.loads(r["json"] or "{}")))
            except Exception:
                continue
        return out

    def save_waiver(self, waiver) -> None:
        """Record one waiver, replacing any earlier decision on the same finding."""
        self.conn.execute(
            "INSERT OR REPLACE INTO waivers (key, rule_id, subject_id, reason, "
            "author, created, json) VALUES (?,?,?,?,?,?,?)",
            (waiver.key, waiver.rule_id, waiver.subject_id, waiver.reason,
             waiver.author, waiver.created, json.dumps(waiver.to_dict())),
        )
        self.conn.commit()

    def delete_waiver(self, key: str) -> None:
        self.conn.execute("DELETE FROM waivers WHERE key=?", (key,))
        self.conn.commit()

    def replace_waivers(self, waivers) -> None:
        """Make the table mirror ``waivers`` exactly, dropping anything else.

        Named to be hard to reach for by accident: an audit re-run must never
        clear waivers. This exists for Save As, where the destination may reuse
        a sidecar carrying another document's decisions.
        """
        self.conn.execute("DELETE FROM waivers")
        rows = [
            (w.key, w.rule_id, w.subject_id, w.reason, w.author, w.created,
             json.dumps(w.to_dict()))
            for w in (waivers.values() if hasattr(waivers, "values") else waivers)
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO waivers (key, rule_id, subject_id, reason, "
            "author, created, json) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def load_waivers(self) -> dict:
        """``{finding key: Waiver}``."""
        from ..audit.findings import Waiver
        try:
            cur = self.conn.execute("SELECT key, json FROM waivers")
        except Exception:
            return {}
        out = {}
        for r in cur.fetchall():
            try:
                out[r["key"]] = Waiver.from_dict(json.loads(r["json"] or "{}"))
            except Exception:
                continue
        return out

    # -- meta ----------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value)
        )
        self.conn.commit()

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cur = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


class NullSidecar:
    """A no-op stand-in for :class:`SidecarDB` used when the sidecar database
    can't be created — e.g. the PDF's name is too long or has characters the
    filesystem/SQLite won't accept for the ``<name>.markup.db`` path.

    It lets a document open for **viewing** (render / search / navigate) instead
    of failing the whole open: every read returns empty and every write is
    silently dropped, so no code path that expects a sidecar crashes. The UI
    greys out the markup/persistence features and tells the user to rename the
    file. Any real save is blocked upstream (see :meth:`Document.save`)."""

    def load_annotations(self) -> list:
        return []

    def save_annotations(self, annotations: Iterable[Annotation]) -> None:
        pass

    def load_wires(self) -> list:
        return []

    def save_wires(self, wires: Iterable) -> None:
        pass

    def load_components(self) -> list:
        return []

    def save_components(self, components: Iterable) -> None:
        pass

    def save_findings(self, findings: Iterable) -> None:
        pass

    def load_findings(self) -> list:
        return []

    def save_waiver(self, waiver) -> None:
        pass

    def delete_waiver(self, key: str) -> None:
        pass

    def replace_waivers(self, waivers) -> None:
        pass

    def load_waivers(self) -> dict:
        return {}

    def set_meta(self, key: str, value: str) -> None:
        pass

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return default

    def close(self) -> None:
        pass


# --- path helpers -----------------------------------------------------------


def _canonical_stem(pdf_path: str) -> str:
    """The stem shared by a document and its ``.marked.pdf`` / ``.markup.db``.

    Opening either ``foo.pdf`` or ``foo.marked.pdf`` maps to the same stem
    ``foo`` — so there is only ever ONE ``foo.marked.pdf`` (never
    ``foo.marked.marked.pdf``) and ONE ``foo.markup.db`` sidecar.
    """
    base, _ = os.path.splitext(pdf_path)
    if base.lower().endswith(".marked"):
        base = base[: -len(".marked")]
    return base


def is_marked_pdf(pdf_path: str) -> bool:
    """True when the path is a ``*.marked.pdf`` produced by this app."""
    base, _ = os.path.splitext(pdf_path)
    return base.lower().endswith(".marked")


def original_pdf_path(pdf_path: str) -> str:
    return _canonical_stem(pdf_path) + ".pdf"


def marked_pdf_path(pdf_path: str) -> str:
    return _canonical_stem(pdf_path) + ".marked.pdf"


def sidecar_path(pdf_path: str) -> str:
    return _canonical_stem(pdf_path) + ".markup.db"


class ProtectedPathError(Exception):
    """A write was aimed at a file this application must never overwrite.

    Raised rather than returned so no caller can forget to check it, and caught
    by the window's existing ``except Exception`` around every save/export, which
    already shows ``str(e)`` to the user.  The message IS the user interface, so
    it names the file, says what it is, and says what to do instead.
    """


def same_path(a: Optional[str], b: Optional[str]) -> bool:
    """True when two paths name the same file, **for paths that need not exist**.

    ``os.path.samefile`` is the correct answer and raises when either side is
    missing -- and an export destination usually IS missing, which is exactly
    the case that has to be judged.  So: ask the filesystem when it can answer,
    and fall back to the normalised-real-path comparison ``main_window`` already
    uses to decide "is this the same document" (main_window.py:1340).

    ``os.path.abspath`` alone is NOT enough, and ``Document.save`` used it:
    Windows paths are case-insensitive, so ``C:\\Drawings\\Foo.pdf`` and
    ``c:\\drawings\\foo.pdf`` are one file that ``abspath`` calls two.
    ``normcase`` handles the case, ``realpath`` handles a symlink or a junction.
    """
    if not a or not b:
        return False
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass

    def key(p: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(p)))

    return key(a) == key(b)


def protected_reason(out_path: str, doc_path: Optional[str] = None) -> str:
    """Why ``out_path`` must not be written, or ``""`` when it may be.

    The application's first boundary is *the original file is never
    overwritten*.  That is a promise about the SOURCE DRAWING, so it is not
    enough to protect the document currently open -- a reviewer with a folder
    of drawings can aim an export at any of them.

    Two rules, and both are about an ORIGINAL rather than about a
    ``.marked.pdf``.  A ``.marked.pdf`` is this app's own artifact, rewritten on
    every save by design, so overwriting one is the normal case and must keep
    working.

    1. ``out_path`` is the open document's own original.  Refused even when the
       file is absent, because writing it would CREATE the pristine base that
       every future open reads from -- and it would be full of marks, so the
       next save would write them a second time on top.  Measured: after this
       happens once, the ``.marked.pdf`` carries two copies of every mark for
       ever.
    2. ``out_path`` is the original of some other drawing that carries MARKS in
       this app.  A reviewer works on a folder of drawings, and a save dialog
       opened in that folder puts every one of them a single click away.

    Rule 2 asks whether the sidecar holds ANNOTATIONS, not whether it exists,
    and the difference is not pedantic: **merely opening a PDF creates its
    ``.markup.db``** (the constructor builds a ``SidecarDB`` unconditionally),
    so "a sidecar is present" means "this file has been opened here" and nothing
    more.  Testing for existence refused an ordinary re-export onto a file the
    user had only looked at, and broke two of this repository's own regression
    tests, which fork onto a name whose sidecar was pre-seeded with wires and
    waivers.  Both are cases with nothing to lose.

    Where the sidecar cannot be read the answer is "not protected", which
    UNDER-claims deliberately: rule 1 still covers the file this markup belongs
    to, the save dialog has already asked about replacing the file, and a guard
    that cannot be got past is worse than one that occasionally lets a
    deliberate overwrite through.
    """
    if doc_path and same_path(out_path, original_pdf_path(doc_path)):
        return (
            f"\u201c{os.path.basename(out_path)}\u201d is the original drawing this "
            f"markup belongs to, and DSI Redline never writes over an original. "
            f"Choose another name \u2014 the marked-up copy is saved beside it as "
            f"\u201c{os.path.basename(marked_pdf_path(doc_path))}\u201d."
        )
    n = _marks_in_sidecar(out_path)
    if n:
        return (
            f"\u201c{os.path.basename(out_path)}\u201d is a drawing with {n} mark"
            f"{'' if n == 1 else 's'} in DSI Redline, and an original is never "
            f"written over. Choose another name."
        )
    return ""


def _marks_in_sidecar(pdf_path: str) -> int:
    """How many marks this app holds for ``pdf_path``, or 0 if it holds none.

    0 for a ``.marked.pdf`` by design: that is this app's own artifact, rewritten
    on every save, so overwriting one is the normal case rather than a loss.
    """
    if is_marked_pdf(pdf_path):
        return 0
    sc = sidecar_path(pdf_path)
    if not os.path.exists(sc):
        return 0
    db = None
    try:
        db = SidecarDB(sc)
        return len(db.load_annotations())
    except Exception:
        return 0
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def refuse_protected(out_path: str, doc_path: Optional[str] = None) -> None:
    """Raise :class:`ProtectedPathError` when ``out_path`` is an original."""
    reason = protected_reason(out_path, doc_path)
    if reason:
        raise ProtectedPathError(reason)


def refuse_overwriting_input(out_path: str, *inputs: Optional[str]) -> None:
    """Raise when a tool would write over a file it is reading from.

    Separate from :func:`refuse_protected` because it is a different question:
    that one asks *is this an original*, this one asks *is this my own input*.
    A page tool has no Document and no sidecar to consult; all it knows is what
    it was handed.

    PyMuPDF already refuses SOME of these with
    ``ValueError: save to original must be incremental`` -- but only where the
    output is saved from the very ``fitz.Document`` that opened it.  Where a
    tool builds a NEW document from the pages it read, that check never fires
    and the write succeeds.  Measured on this codebase: ``extract_pages`` took
    a four-page drawing to one page, and ``combine_pdfs`` replaced its own input
    with the combination.  So this guard is not decoration over the library's --
    it covers the cases the library cannot see, and it turns the ones it can
    into a sentence that names the file.
    """
    for src in inputs:
        if src and same_path(out_path, src):
            raise ProtectedPathError(
                f"\u201c{os.path.basename(out_path)}\u201d is the file being read "
                f"from, so writing there would destroy it. Choose another name."
            )


def strip_annotations(doc: "fitz.Document") -> None:
    """Remove every annotation from ``doc`` (used when a ``.marked.pdf`` is the
    only available base, so re-saving the store doesn't double the marks)."""
    for page in doc:
        for annot in list(page.annots() or []):
            try:
                page.delete_annot(annot)
            except Exception:
                pass
