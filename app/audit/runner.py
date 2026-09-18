"""Running the design rule check.

Written to run on a worker thread, which shapes the whole interface: it opens
its own PyMuPDF handle, takes the document's sheet metadata as plain
dictionaries, and never touches the sidecar.  The sidecar's sqlite connection
belongs to the thread that created it, and the open ``Document`` belongs to the
UI.  Results come back as plain data for the main thread to persist.

Qt-free, so it is testable without a QApplication.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from .adapter import AdapterOptions, build_model
from .findings import (AuditRun, Coverage, Finding, apply_waivers, sort_findings)

DEFAULT_PACK = "drc-base"


class AuditUnavailable(RuntimeError):
    """The rule library is not installed."""


@dataclass
class AuditResult:
    findings: list = field(default_factory=list)
    run: AuditRun = field(default_factory=AuditRun)
    cancelled: bool = False

    @property
    def open_findings(self) -> list:
        return [f for f in self.findings if not f.waived]


def _one_line(e: Exception) -> str:
    """An exception's text as one line.

    Model validation reports each problem on its own line, and every place
    these notices are read -- the panel header, a CSV cell -- is one line.
    """
    return " ".join(str(e).split())


def user_pack_dirs() -> list:
    """Directories to search for rule packs besides the built-in ones.

    A packaged installation lives under Program Files, which is not writable,
    so user-authored packs cannot sit beside the built-ins. ``PYDRC_PACK_PATH``
    is how the library is pointed at somewhere they can.
    """
    raw = os.environ.get("PYDRC_PACK_PATH", "")
    return [p for p in raw.split(os.pathsep) if p and os.path.isdir(p)]


def available_rules(pack_ids=(), extra_dirs=None) -> list:
    """``(rule_id, title, severity, pack)`` for every rule that could run.

    Used by Settings to list rules without running anything.
    """
    from pydrc.packs import loader
    out = []
    for pack_id in (pack_ids or (DEFAULT_PACK,)):
        try:
            pack = loader.load_by_id(pack_id, extra=extra_dirs or user_pack_dirs())
        except Exception:
            continue
        for rule in pack.rules:
            out.append((rule.id, rule.title, rule.severity, pack.ref))
    return out


def run_audit(pdf_path: str, sheet_labels: dict, sheet_sources: dict,
              sheet_roles: dict, *,
              options: Optional[AdapterOptions] = None,
              pack_ids=(), extra_pack_dirs=None,
              disabled_rules=(), severity_overrides=None,
              waivers: Optional[dict] = None,
              acade_model_json: str = "",
              project: Optional[dict] = None,
              progress: Optional[Callable] = None,
              cancel: Optional[Callable] = None) -> AuditResult:
    """Audit a drawing and return findings plus what could not be checked.

    Opens its own document handle: safe to call from a worker thread, and it
    never mutates anything the caller owns.
    """
    try:
        import fitz
        import pydrc.checks                     # noqa: F401  (registers checks)
        from pydrc.engine.evaluator import run as run_rules
        from pydrc.packs import loader
    except ImportError as e:
        raise AuditUnavailable(
            "The design rule library (PyDRC) is not installed.") from e

    dirs = list(extra_pack_dirs or user_pack_dirs())
    packs = []
    for pack_id in (pack_ids or (DEFAULT_PACK,)):
        packs.append(loader.load_by_id(pack_id, extra=dirs))

    doc = fitz.open(pdf_path)
    try:
        built = build_model(doc, sheet_labels, sheet_sources, sheet_roles,
                            options or AdapterOptions(), project,
                            progress=progress, cancel=cancel)
        if built is None:
            return AuditResult(cancelled=True)

        # Enrich the plot-derived model with the imported source drawings.
        # Read in two steps on purpose: loading the stored model cannot touch
        # anything, so a stored blob that will not parse -- the overwhelmingly
        # likely failure, and the only one measured -- leaves the plot-derived
        # model pristine and its audit worth running. Merging enriches in
        # place, so a failure part-way through leaves a model that is neither
        # the plot's nor the source's, and auditing that is worse than not
        # auditing at all.
        #
        # Both used to abort the whole run and report "Nothing to check." --
        # 29 real findings and 1048 eligible checks thrown away because a
        # separate stored blob was corrupt, with the reason recorded in
        # `errors`, which nothing displayed.
        notices = []
        if acade_model_json:
            from pydrc.model import loads as load_model
            try:
                acade = load_model(acade_model_json)
            except Exception as e:
                acade = None
                notices.append(
                    "The imported source drawings could not be read, so this "
                    "check ran on the PDF alone -- every rule that needs the "
                    "source was skipped. Re-import the drawings and run it "
                    f"again. ({_one_line(e)})")
            if acade is not None:
                try:
                    from pydrc.adapters.acade_dxf import merge_models
                    merge_models(built.model, acade)
                except Exception as e:
                    return AuditResult(run=AuditRun(errors=[
                        "The imported source drawings could not be merged "
                        "into the drawing, and the half-merged result is not "
                        "safe to check. Re-import the drawings and run the "
                        f"check again. ({_one_line(e)})"]))

        result = run_rules(built.model, packs,
                           disabled=set(disabled_rules or ()),
                           severity_overrides=dict(severity_overrides or {}))
    finally:
        doc.close()

    if cancel is not None and cancel():
        return AuditResult(cancelled=True)

    payload = result.to_dict()
    # Sheet number to page index, so a finding that covers nine sheets can be
    # placed on all nine rather than only on the one it happens to open at.
    # First occurrence wins, matching how the parsers and the extents index
    # dedupe. A plot can carry one sheet number on two pages -- a revised sheet
    # bound in beside the original -- and last-wins moved 18 of 71 places onto
    # the wrong one of the pair.
    pages_by_sheet: dict = {}
    for s in built.model.sheets:
        if s.number and s.page_index is not None:
            pages_by_sheet.setdefault(str(s.number), s.page_index)
    findings = [Finding.from_pydrc(raw, built.extents, pages_by_sheet)
                for raw in payload.get("findings", [])]
    findings = sort_findings(apply_waivers(findings, waivers or {}))

    cov_rows = (payload.get("coverage") or {}).get("rules") or []
    summary = (payload.get("coverage") or {}).get("summary") or {}
    run = AuditRun(
        packs=[p.ref for p in packs],
        eligible=int(summary.get("eligible", 0)),
        checked=int(summary.get("checked", 0)),
        skipped=int(summary.get("skipped", 0)),
        coverage=[Coverage.from_dict(c) for c in cov_rows],
        errors=notices + list((payload.get("run") or {}).get("errors") or []),
    )
    return AuditResult(findings=findings, run=run)
