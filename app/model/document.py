"""High-level document controller (GUI-free).

Owns the open :class:`fitz.Document`, the :class:`AnnotationStore`, and the
:class:`SidecarDB`, and implements the hybrid open/save workflow described in
the spec.  The viewer/panels talk to this object.
"""

from __future__ import annotations

import os
from typing import Iterable, Optional

import fitz  # PyMuPDF

from ..extraction import sheet_number, sheet_role
from .annotations import Annotation, AnnotationStore
from .storage import (
    SidecarDB, NullSidecar, load_pdf_annotations, write_annotations_to_pdf,
    compile_ignore_patterns, text_is_ignored,
    marked_pdf_path, sidecar_path, original_pdf_path, is_marked_pdf,
    refuse_protected, same_path,
    strip_annotations, DEFAULT_IGNORE_PATTERNS,
)


class Document:
    """A single open PDF plus its markup state."""

    def __init__(self, path: str, ignore_patterns: Optional[Iterable[str]] = None):
        self.path = path
        self.fitz_doc = fitz.open(path)
        self.store = AnnotationStore()
        sc_path = sidecar_path(path)
        # Opening a *.marked.pdf reuses the ORIGINAL's single sidecar. If that
        # sidecar is missing (e.g. the file was moved on its own), we create a
        # fresh one and flag it so the UI can tell the user.
        self.sidecar_recreated = is_marked_pdf(path) and not os.path.exists(sc_path)
        # The PDF itself opened, but the sidecar path may be unusable (name too
        # long, or characters the filesystem/SQLite reject). Rather than fail the
        # whole open, fall back to a no-op sidecar so the file still opens for
        # viewing; the UI greys out markup/persistence and explains why.
        try:
            self.sidecar = SidecarDB(sc_path)
            self.sidecar_available = True
            self.sidecar_error = ""
        except Exception as e:
            self.sidecar = NullSidecar()
            self.sidecar_available = False
            self.sidecar_error = str(e)
            self.sidecar_recreated = False
        self.ignore_patterns = list(
            ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS
        )
        self.wires: list = []
        self.components: list = []
        self.findings: list = []       # from the most recent audit
        self.waivers: dict = {}        # finding key -> Waiver; outlives findings
        self.audit_run = None          # AuditRun summary, or None
        self.acade_model_json = ""     # imported source-drawing model, if any
        self.acade_wire_format = ""    # its wire numbering format ("%S%N")
        self.sheet_labels: dict = {}   # page_index -> sheet number (str, e.g. "000")
        # page_index -> how that number was resolved (a sheet_number strategy
        # name, or "user"). An audit cannot report coverage honestly if it
        # cannot tell a number a human confirmed from one a heuristic guessed.
        self.sheet_sources: dict = {}
        self.sheet_roles: dict = {}    # page_index -> sheet_role name
        self._dirty = False
        # Every path a user's edit can take -- draw, move, resize, delete, edit
        # the text, undo, redo, tick a TODO -- ends in a non-silent store CRUD
        # call, and ``load`` below is the only caller that passes silent=True.
        # So this one listener *is* the "are there unsaved marks?" question,
        # and a file that was just loaded correctly comes up clean.
        #
        # Deliberately not set inside AnnotationStore.add/update/remove:
        # ``silent`` gates only the emit, not the body, so a flag set there
        # would mark a fifty-mark file dirty the instant it opened and prompt
        # to save on every close.
        self.store.add_listener(lambda *_: self.mark_dirty())

    # -- basic page access ---------------------------------------------------

    @property
    def page_count(self) -> int:
        return self.fitz_doc.page_count

    def page_rect(self, page_no: int) -> "fitz.Rect":
        return self.fitz_doc[page_no].rect

    def get_pixmap(self, page_no: int, zoom: float = 1.0) -> "fitz.Pixmap":
        """Render a page to a :class:`fitz.Pixmap` (GUI converts to QImage).

        ``annots=False`` so the bitmap is the clean page: the app draws every
        mark as its own overlay item, so a PDF that already carries annotations
        (a ``.marked.pdf`` or a colleague's markup) isn't rendered twice.
        """
        mat = fitz.Matrix(zoom, zoom)
        return self.fitz_doc[page_no].get_pixmap(matrix=mat, alpha=False, annots=False)

    # -- loading -------------------------------------------------------------

    def load(self) -> None:
        """Load sidecar (our) annotations, then import external PDF annots.

        The sidecar is authoritative for marks this app created.  Any annotation
        found in the PDF whose ``/NM`` id is *not* already known is treated as
        external (e.g. a colleague's markup or AutoCAD junk) and imported with
        its real author; junk is flagged ignored.
        """
        # 1) our marks from the sidecar
        known_ids = set()
        for ann in self.sidecar.load_annotations():
            self.store.add(ann, silent=True)
            known_ids.add(ann.id)

        # 2) external marks living in the PDF itself
        compiled = compile_ignore_patterns(self.ignore_patterns)
        for ann in load_pdf_annotations(self.fitz_doc, self.ignore_patterns):
            if ann.id in known_ids:
                continue  # sidecar copy already loaded
            # re-evaluate junk filter against the current pattern list
            if text_is_ignored(ann.text, compiled) or text_is_ignored(ann.author, compiled):
                ann.ignored = True
            self.store.add(ann, silent=True)

        # 3) cached wire numbers + component labels
        self.wires = self.sidecar.load_wires()
        self.components = self.sidecar.load_components()

        # 3b) the last audit's findings, the waivers recorded against them, and
        #     what that run could not check
        self.findings = self.sidecar.load_findings()
        self.waivers = self.sidecar.load_waivers()
        self._load_audit_run()
        self.acade_model_json = self.sidecar.get_meta("acade_model") or ""
        self.acade_wire_format = self.sidecar.get_meta("acade_wire_format") or ""

        # 4) per-page sheet numbers and roles: load saved edits, then
        #    best-effort auto-detection for pages we don't know yet
        self._load_sheet_labels()
        self._load_sheet_roles()

    # -- audit findings ------------------------------------------------------

    def _load_audit_run(self) -> None:
        from ..audit.findings import AuditRun, apply_waivers
        self.audit_run = AuditRun.from_json(self.sidecar.get_meta("audit_run"))
        apply_waivers(self.findings, self.waivers)

    def set_findings(self, findings: list, run=None) -> None:
        """Replace the findings from an audit run and persist immediately.

        Written through rather than deferred to File > Save, matching how the
        wire and component tabs persist their extractions.
        """
        from ..audit.findings import apply_waivers
        self.findings = list(findings)
        apply_waivers(self.findings, self.waivers)
        self.audit_run = run
        self.sidecar.save_findings(self.findings)
        self.sidecar.set_meta("audit_run", run.to_json() if run is not None else "")

    def waive_finding(self, key: str, reason: str, author: str = "") -> None:
        """Record that a finding is acceptable here, and persist it.

        Waivers are stored apart from findings so that re-running the audit --
        which replaces every finding -- never discards a human decision.
        """
        from ..audit.findings import Waiver, STATUS_WAIVED
        key = str(key or "")
        if not key:
            return
        rule_id = subject = ""
        for f in self.findings:
            if f.key == key:
                rule_id, subject = f.rule_id, f.subject_id
                f.status = STATUS_WAIVED
        waiver = Waiver(key=key, rule_id=rule_id, subject_id=subject,
                        reason=reason, author=author)
        self.waivers[key] = waiver
        self.sidecar.save_waiver(waiver)

    def clear_waiver(self, key: str) -> None:
        """Withdraw a waiver, returning the finding to open."""
        from ..audit.findings import STATUS_OPEN
        key = str(key or "")
        self.waivers.pop(key, None)
        self.sidecar.delete_waiver(key)
        for f in self.findings:
            if f.key == key:
                f.status = STATUS_OPEN

    def waiver_for(self, key: str):
        return self.waivers.get(str(key or ""))

    def set_acade_import(self, model_json: str, wire_format: str = "") -> None:
        """Store an imported source-drawing model and persist it.

        Every subsequent audit merges this into the plot-derived model before
        the rules run. Re-importing replaces it wholesale: the source directory
        is the authority on itself.
        """
        self.acade_model_json = model_json or ""
        self.acade_wire_format = wire_format or ""
        self.sidecar.set_meta("acade_model", self.acade_model_json)
        self.sidecar.set_meta("acade_wire_format", self.acade_wire_format)

    # -- sheet numbers (per page) -------------------------------------------

    def _load_sheet_labels(self) -> None:
        import json
        raw = self.sidecar.get_meta("sheet_labels")
        saved = {}
        if raw:
            try:
                saved = {int(k): str(v) for k, v in json.loads(raw).items()}
            except Exception:
                saved = {}
        self.sheet_labels = saved

        # Provenance lives in its own meta key rather than being folded into
        # sheet_labels, so a sidecar written here still opens in a build that
        # predates it. Labels from such a sidecar are marked "unknown": they
        # may have been typed or guessed and there is no way to tell.
        raw = self.sidecar.get_meta("sheet_label_sources")
        sources = {}
        if raw:
            try:
                sources = {int(k): str(v) for k, v in json.loads(raw).items()}
            except Exception:
                sources = {}
        self.sheet_sources = {p: sources.get(p, sheet_number.UNKNOWN)
                              for p in self.sheet_labels}
        self._autodetect_sheet_labels()

    def _autodetect_sheet_labels(self) -> None:
        """Resolve sheet numbers for pages we don't already know, recording
        which strategy answered.

        Never clobbers a saved value: a number the user confirmed outranks
        anything detection can offer.
        """
        try:
            resolved = sheet_number.resolve_document(self.fitz_doc)
        except Exception:
            return
        for page_no, got in resolved.items():
            if page_no in self.sheet_labels:
                continue
            if not got.resolved:
                continue          # leave blank rather than guess
            self.sheet_labels[page_no] = got.label
            self.sheet_sources[page_no] = got.strategy

    def sheet_label(self, page_no: int) -> str:
        return self.sheet_labels.get(int(page_no), "")

    def sheet_source(self, page_no: int) -> str:
        """Which strategy produced this page's sheet number."""
        return self.sheet_sources.get(int(page_no), sheet_number.UNKNOWN)

    def sheet_confidence(self, page_no: int) -> float:
        """How much to trust this page's sheet number, 0.0 when unresolved."""
        if not self.sheet_label(page_no):
            return 0.0
        return sheet_number.CONFIDENCE.get(self.sheet_source(page_no), 0.5)

    def set_sheet_label(self, page_no: int, label: str) -> None:
        """Set (or clear, when blank) a page's sheet number and persist it."""
        page_no = int(page_no)
        label = (label or "").strip()
        if label:
            self.sheet_labels[page_no] = label
            self.sheet_sources[page_no] = sheet_number.USER
        else:
            self.sheet_labels.pop(page_no, None)
            self.sheet_sources.pop(page_no, None)
        self._save_sheet_labels()

    def _save_sheet_labels(self) -> None:
        import json
        self.sidecar.set_meta(
            "sheet_labels",
            json.dumps({str(k): v for k, v in self.sheet_labels.items()}))
        self.sidecar.set_meta(
            "sheet_label_sources",
            json.dumps({str(k): v for k, v in self.sheet_sources.items()}))

    # -- sheet roles (per page) ---------------------------------------------

    def _load_sheet_roles(self) -> None:
        """Saved roles first, then detection for pages we don't know yet."""
        import json
        raw = self.sidecar.get_meta("sheet_roles")
        saved = {}
        if raw:
            try:
                saved = {int(k): str(v) for k, v in json.loads(raw).items()}
            except Exception:
                saved = {}
        self.sheet_roles = saved
        try:
            detected = sheet_role.detect_document_roles(self.fitz_doc)
        except Exception:
            return
        for page_no, role in detected.items():
            self.sheet_roles.setdefault(page_no, role)

    def sheet_role_of(self, page_no: int) -> str:
        return self.sheet_roles.get(int(page_no), sheet_role.SCHEMATIC)

    def set_sheet_role(self, page_no: int, role: str) -> None:
        """Override a page's detected role and persist it."""
        page_no = int(page_no)
        role = (role or "").strip()
        if role and role != sheet_role.UNKNOWN:
            self.sheet_roles[page_no] = role
        else:
            self.sheet_roles.pop(page_no, None)
        self._save_sheet_roles()

    def _save_sheet_roles(self) -> None:
        import json
        self.sidecar.set_meta(
            "sheet_roles",
            json.dumps({str(k): v for k, v in self.sheet_roles.items()}))

    # -- saving --------------------------------------------------------------

    def save(self, marked_path: Optional[str] = None,
             include_ignored: bool = False) -> str:
        """Write the ``.marked.pdf`` copy and sync the sidecar.

        The original PDF is never overwritten.  Returns the marked PDF path.
        """
        if not self.sidecar_available:
            raise RuntimeError(
                "This file has no markup database — its name is too long or uses "
                "characters that can't be saved. Rename the file to something "
                "shorter and simpler, then reopen it to enable saving.")
        out = marked_path or marked_pdf_path(self.path)
        # THE BOUNDARY, enforced where every write funnels rather than at each
        # caller. `marked_path` is caller-supplied -- `export_annotated_pdf`
        # forwards whatever path a save dialog returned -- and without this an
        # export aimed at the drawing itself REPLACED it: measured, a 3-page
        # original came back with a mark baked in, no .marked.pdf was written at
        # all, and every save after that wrote two copies of every mark, because
        # the clobbered file is what `original_pdf_path` resolves to and
        # `is_marked_pdf` says False, so `strip_annotations` is skipped.
        #
        # Unconditional, including the derived path: `marked_pdf_path` can never
        # equal `original_pdf_path` (one ends `.marked.pdf`), so this is a no-op
        # on the normal path and a guard that cannot be routed around on the
        # other one.
        refuse_protected(out, self.path)
        # Base the write on the PRISTINE original when it's available, so re-saving
        # never doubles the marks; if only the .marked.pdf exists, strip its
        # annotations first. Either way the store is the single source of truth.
        original = original_pdf_path(self.path)
        if os.path.exists(original):
            work = fitz.open(original)
        else:
            work = fitz.open(self.path)
            if is_marked_pdf(self.path):
                strip_annotations(work)
        write_annotations_to_pdf(work, self.store.all(), include_ignored=include_ignored)

        # ``out`` is the same file this Document already holds open (e.g. the user
        # opened the .marked.pdf itself) → write a temp, RELEASE our handle (on
        # Windows an open file can't be replaced), atomically swap it in, then
        # reopen on the freshly-written file.
        # `same_path`, not `abspath`: on Windows one file has many spellings
        # (case, an 8.3 name, a junction), and getting this wrong takes the
        # plain `work.save(out)` branch for a file we hold open -- which
        # PyMuPDF then refuses with "save to original must be incremental",
        # a library message about a path the user never typed.
        out_is_open = same_path(out, self.path)
        if out_is_open:
            import tempfile
            d = os.path.dirname(os.path.abspath(out)) or "."
            fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=d)
            os.close(fd)
            work.save(tmp, garbage=3, deflate=True)
            work.close()
            try:
                self.fitz_doc.close()
            except Exception:
                pass
            os.replace(tmp, out)
            self.fitz_doc = fitz.open(out)
            self.path = out
        else:
            work.save(out, garbage=3, deflate=True)
            work.close()

        # sync app state + wire cache
        self.sidecar.save_annotations(self.store.all())
        if self.wires:
            self.sidecar.save_wires(self.wires)
        if self.components:
            self.sidecar.save_components(self.components)
        self.sidecar.save_findings(self.findings)
        if self.audit_run is not None:
            self.sidecar.set_meta("audit_run", self.audit_run.to_json())
        self._save_sheet_labels()
        self._save_sheet_roles()
        self.sidecar.set_meta("source_pdf", os.path.basename(self.path))
        self._dirty = False
        return out

    def annotated_fitz(self, include_ignored: bool = False,
                       with_marks: bool = True) -> "fitz.Document":
        """Return an **in-memory** ``fitz.Document`` of the pages — for
        printing/preview. With ``with_marks`` (default) the current marks are
        written into the pages; with ``with_marks=False`` the clean drawing is
        returned (the app's markups are left off). Never touches disk or the
        sidecar, so it works even for a view-only file with no sidecar. The
        caller owns the returned doc and must close it."""
        original = original_pdf_path(self.path)
        if os.path.exists(original):
            work = fitz.open(original)
        else:
            work = fitz.open(self.path)
            if is_marked_pdf(self.path):
                strip_annotations(work)
        if with_marks:
            write_annotations_to_pdf(work, self.store.all(),
                                     include_ignored=include_ignored)
        return work

    def export_annotated_pdf(self, out_path: str, include_ignored: bool = False) -> str:
        """Explicit 'Export annotated PDF…' to an arbitrary path."""
        return self.save(marked_path=out_path, include_ignored=include_ignored)

    def export_flattened_pdf(self, out_path: str, include_ignored: bool = False) -> bool:
        """Export a *flattened* copy: every mark is baked into the page content so
        it renders in **any** viewer (browsers, Preview, thumbnails), not only
        annotation-aware readers.  The result is not re-editable here — the
        working file (sidecar) stays the source of truth.  Returns True if the
        marks were actually flattened (False if this PyMuPDF lacks ``bake``, in
        which case a normal annotated copy is written instead)."""
        # This one does not go through `save()`, so it needs the guard of its
        # own -- and it is the worst place to lose: a flattened export bakes the
        # marks into the page CONTENT, so `strip_annotations` cannot undo it and
        # a clobbered original would be gone with no route back.
        refuse_protected(out_path, self.path)
        original = original_pdf_path(self.path)
        if os.path.exists(original):
            work = fitz.open(original)
        else:
            work = fitz.open(self.path)
            if is_marked_pdf(self.path):
                strip_annotations(work)
        write_annotations_to_pdf(work, self.store.all(), include_ignored=include_ignored)
        baked = False
        if hasattr(work, "bake"):
            try:
                work.bake(annots=True, widgets=False)
                baked = True
            except Exception:
                baked = False
        work.save(out_path, garbage=3, deflate=True)
        work.close()
        return baked

    def save_as(self, dest_pdf: str, include_ignored: bool = False) -> str:
        """Fork the current markup into a NEW working file and switch to it.

        A pristine copy of the source PDF is written to ``dest_pdf`` (canonicalised
        so we never fork to a ``*.marked.pdf``), a fresh sidecar is started there
        carrying every current mark / wire / component / sheet number, its
        ``.marked.pdf`` is written, and this :class:`Document` is re-pointed at the
        copy so subsequent edits land on the fork.  The original file is left
        untouched.  Returns the new ``.marked.pdf`` path.
        """
        dest = original_pdf_path(dest_pdf)          # never fork to foo.marked.pdf
        # A fork writes a PRISTINE copy to `dest`, so aiming it at a drawing
        # that already carries markup destroys that drawing. Forking onto this
        # document's own original is refused by the same rule, which is right:
        # it is a gesture with no meaning that would otherwise quietly do
        # nothing at all.
        refuse_protected(dest, self.path)
        src = original_pdf_path(self.path)
        if not os.path.exists(src):
            src = self.path                         # only the marked copy exists

        # 1) write a pristine (annotation-free) copy of the source to dest
        if os.path.abspath(dest) != os.path.abspath(src):
            work = fitz.open(src)
            try:
                if is_marked_pdf(src):
                    strip_annotations(work)
                work.save(dest, garbage=3, deflate=True)
            finally:
                work.close()

        # 2) re-point this Document at the fork with a fresh sidecar
        try:
            self.sidecar.close()
        except Exception:
            pass
        try:
            self.fitz_doc.close()
        except Exception:
            pass
        self.path = dest
        self.fitz_doc = fitz.open(dest)
        self.sidecar = SidecarDB(sidecar_path(dest))
        self.sidecar_available = True     # the fork lives at a usable path
        self.sidecar_recreated = False

        # 3) persist all in-memory state to the new sidecar + write its marked PDF
        out = self.save(include_ignored=include_ignored)
        # If dest reused a pre-existing sidecar, its wire/component tables could
        # hold foreign rows that save() only rewrites when we actually have some.
        # Force them to mirror THIS document exactly (empty clears them).
        self.sidecar.save_wires(self.wires)
        self.sidecar.save_components(self.components)
        self.sidecar.replace_waivers(self.waivers)
        return out

    # -- wire cache ----------------------------------------------------------

    def set_wires(self, wires: list) -> None:
        self.wires = wires
        self.sidecar.save_wires(wires)

    def set_components(self, components: list) -> None:
        self.components = components
        self.sidecar.save_components(components)

    # -- lifecycle -----------------------------------------------------------

    def mark_dirty(self) -> None:
        """Record that there is work here that only :meth:`save` would keep.

        Most state writes straight through to the sidecar as it changes --
        findings, waivers, sheet numbers and roles, the imported source model.
        Two things do not, and so are what this flag is about: the marks
        themselves, and which wires and components are ticked for export.
        """
        self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def close(self) -> None:
        try:
            self.sidecar.close()
        finally:
            try:
                self.fitz_doc.close()
            except Exception:
                pass
