"""Exporting an audit report.

Three formats for three audiences: HTML to file with a project record, Markdown
to paste into a review, CSV to sort in a spreadsheet.  All three carry the same
two things that make a finding checkable — the clause it rests on and the
arithmetic or facts behind it — plus the coverage statement, which is not
optional in any of them.

GUI-free, like its siblings in this package.
"""

from __future__ import annotations

import csv
import html as _html
import os

from ..audit.findings import DEFINITE, POTENTIAL, INFO, SEVERITY_LABELS

# Deliberate wording: this is a review, not a determination of compliance.
#
# Held in two pieces because the HTML export bolds the lead and prints the rest
# after it. It used to do that by slicing ADVISORY at a hand-counted offset,
# which was one past the space -- so every HTML report ever exported opened with
# "Advisory review. indings identify things to confirm...".
ADVISORY_LEAD = "Advisory review."
ADVISORY_BODY = ("Findings identify things to confirm against the governing "
                 "standard and the authority having jurisdiction. This report "
                 "is not a determination of compliance.")
ADVISORY = f"{ADVISORY_LEAD} {ADVISORY_BODY}"

NOT_CHECKED = ("A skipped item is not a passing item. The rules below could not "
               "run on part of the drawing; supply the missing data to check them.")

_ORDER = (DEFINITE, POTENTIAL, INFO)


def _where(f) -> str:
    """"sheet 232", "sheets 232-240" or "set-wide".

    A finding can cover more than one sheet since the rule library reports a
    repeated drafting event once and names every place. An export that prints
    only the first sends a contractor to one of nine sheets, which is the same
    failure the report was rolled up to avoid.
    """
    seen = getattr(f, "sheets", None) or ([f.sheet] if f.sheet else [])
    if not seen:
        return "set-wide"
    if len(seen) == 1:
        return f"sheet {seen[0]}"
    return "sheets " + ", ".join(seen)


def _rows(document, disabled=()) -> list:
    from ..audit.findings import sort_findings, visible_findings
    return sort_findings(visible_findings(
        getattr(document, "findings", []) or [], disabled))


def _turned_off(disabled) -> str:
    """One sentence naming the rules a reader is not seeing.

    An export that silently drops rows makes "this rule found nothing" and
    "you switched this rule off" the same answer -- which is the one confusion
    the coverage accounting exists to prevent, arriving by another door. So the
    rows go and the sentence stays.
    """
    rules = sorted(set(disabled or ()))
    if not rules:
        return ""
    return ("Turned off for this report, so their findings are not listed: "
            + ", ".join(rules) + ".")


def _run(document):
    return getattr(document, "audit_run", None)


def _packs_line(run) -> str:
    """Which rule packs produced this report.

    Stated in every format, not just Markdown. The pack version is how a
    report says which rules it was checked against -- two reports carrying one
    version string while disagreeing about a finding is a question nobody can
    answer afterwards -- and for a long while the HTML export, which is the one
    people actually keep, did not print it anywhere.
    """
    packs = list(getattr(run, "packs", None) or ()) if run is not None else []
    return "Rule packs: " + ", ".join(packs) if packs else ""


def _problems(run) -> list:
    """What went wrong during the run, for the reader of the report.

    A run records these in ``errors`` and, until this existed, displayed them
    in no format at all -- so a check that ran on the PDF alone because the
    imported source drawings would not load produced a report indistinguishable
    from one where they had. ``summary_line`` already carries the first line of
    a blocked run.
    """
    if run is None:
        return []
    return list(run.errors[1:] if run.blocked else run.errors)


def export_markdown(document, path: str, disabled=()) -> str:
    findings = _rows(document, disabled)
    run = _run(document)
    out = ["# Design rule check", "", f"> {ADVISORY}", ""]
    off = _turned_off(disabled)
    if off:
        out += [f"**{off}**", ""]
    if run is not None:
        out += [f"**Coverage.** {run.summary_line()}", ""]
        for problem in _problems(run):
            out += [f"> **{problem}**", ""]
        packs = _packs_line(run)
        if packs:
            out += [packs, ""]

    for severity in _ORDER:
        group = [f for f in findings if f.severity == severity]
        if not group:
            continue
        out += [f"## {SEVERITY_LABELS[severity]} ({len(group)})", ""]
        for f in group:
            where = _where(f)
            mark = " *(waived)*" if f.waived else ""
            out.append(f"- **{f.message}**{mark}")
            out.append(f"  - `{f.rule_id}` · {where} · {f.subject_id}")
            if f.clause:
                out.append(f"  - Cited: {f.clause}")
            if f.evidence:
                out.append("  - Evidence: "
                           + ", ".join(f"{k}={v}" for k, v in f.evidence.items()))
            waiver = document.waiver_for(f.key) if hasattr(document, "waiver_for") else None
            if waiver is not None:
                who = f" — {waiver.author}" if waiver.author else ""
                out.append(f"  - Waived: {waiver.reason}{who}")
        out.append("")

    if not findings:
        # A blocked run has no findings because it did not look, which is not
        # what "No findings" says to anyone reading it.
        if run is not None and run.blocked:
            out += ["## No findings were produced", "",
                    "This report is not a result. The check did not run — see "
                    "the coverage statement above.", ""]
        else:
            out += ["No findings.", "",
                    "Read the coverage statement above before treating that "
                    "as a clean result.", ""]

    # Gated on everything_accounted_for, not complete: a rule with nothing
    # eligible skips nothing, so `complete` is true of it, and this whole
    # section used to vanish for a set whose only gap was four motor rules
    # having been handed no motor circuits at all.
    if run is not None and not run.everything_accounted_for:
        out += ["## Not checked", "", NOT_CHECKED, ""]
        for cov in run.coverage:
            if not cov.ran:
                out.append(f"- `{cov.rule_id}`: nothing to check against — "
                           f"the model carries no entity this rule applies to")
                continue
            if cov.complete:
                continue
            why = ", ".join(f"{n} {r}" for r, n in (cov.reasons or {}).items())
            out.append(f"- `{cov.rule_id}`: {cov.checked} of {cov.eligible} "
                       f"checked, {cov.skipped} skipped ({why})")
        out.append("")

    text = "\n".join(out)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def export_csv(document, path: str, disabled=()) -> str:
    findings = _rows(document, disabled)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        off = _turned_off(disabled)
        if off:
            w.writerow([off])
            w.writerow([])
        w.writerow(["Severity", "Rule", "Sheet", "Page", "Subject", "Finding",
                    "Cited", "Status", "Evidence"])
        for f in findings:
            w.writerow([
                f.severity_label, f.rule_id,
                ", ".join(getattr(f, "sheets", None) or ([f.sheet] if f.sheet
                                                         else [])),
                f.page + 1 if f.has_location else "",
                f.subject_id, f.message, f.clause,
                "Waived" if f.waived else "Open",
                "; ".join(f"{k}={v}" for k, v in (f.evidence or {}).items()),
            ])
        run = _run(document)
        if run is not None:
            w.writerow([])
            w.writerow(["Coverage", run.summary_line()])
            for problem in _problems(run):
                w.writerow(["Problem", problem])
            if run.packs:
                w.writerow(["Rule packs", ", ".join(run.packs)])
            for cov in run.coverage:
                if not cov.ran:
                    w.writerow(["", f"{cov.rule_id}: nothing to check against"])
                    continue
                if cov.complete:
                    continue
                w.writerow(["", f"{cov.rule_id}: {cov.checked} of {cov.eligible} "
                                f"checked, {cov.skipped} skipped"])
    return path


_CSS = """
body{margin:0;padding:2rem 1.25rem;background:#fff;color:#1a1a1a;
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:60rem;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 .25rem}
h2{font-size:1.05rem;margin:2rem 0 .75rem;padding-bottom:.35rem;
border-bottom:1px solid #e2e5ea}
.note{background:#f7f8fa;border-left:3px solid #5b6470;padding:.75rem 1rem;
margin:1rem 0;color:#5b6470;font-size:.9rem}
.f{border:1px solid #e2e5ea;border-radius:6px;padding:.9rem 1rem;margin:.6rem 0}
.f.waived{opacity:.55}.f.waived .msg{text-decoration:line-through}
.tag{display:inline-block;font-size:.72rem;font-weight:600;letter-spacing:.03em;
text-transform:uppercase;padding:.12rem .45rem;border-radius:3px;color:#fff}
.definite{background:#b3261e}.potential{background:#9a6700}.info{background:#0b5cad}
.waivedtag{background:#8a9099}
.rid{font-family:ui-monospace,Menlo,monospace;font-size:.8rem;color:#5b6470;
margin-left:.5rem}
.msg{margin:.5rem 0 .35rem}.sub{color:#5b6470;font-size:.85rem}
.ev{font-family:ui-monospace,Menlo,monospace;font-size:.78rem;color:#5b6470;
margin-top:.4rem;word-break:break-word}
table{border-collapse:collapse;width:100%;font-size:.875rem}
th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e2e5ea}
th{color:#5b6470}.gap{color:#b3261e;font-weight:600}
.scroll{overflow-x:auto}
.foot{margin-top:2rem;padding-top:.75rem;border-top:1px solid #e2e5ea;
color:#5b6470;font-size:.8rem}
"""


def export_html(document, path: str, title: str = "", disabled=()) -> str:
    findings = _rows(document, disabled)
    run = _run(document)
    esc = lambda v: _html.escape(str(v), quote=True)          # noqa: E731
    name = title or os.path.basename(getattr(document, "path", "") or "Drawing")

    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           f"<title>Design rule check — {esc(name)}</title>",
           f"<style>{_CSS}</style></head><body><div class='wrap'>",
           f"<h1>Design rule check</h1><p class='sub'>{esc(name)}</p>",
           f"<div class='note'><strong>{esc(ADVISORY_LEAD)}</strong> "
           f"{esc(ADVISORY_BODY)}</div>"]

    off = _turned_off(disabled)
    if off:
        out.append(f"<div class='note'>{esc(off)}</div>")
    if run is not None:
        out.append(f"<p><strong>Coverage.</strong> {esc(run.summary_line())}</p>")
        for problem in _problems(run):
            out.append(f"<div class='note'><strong>{esc(problem)}</strong></div>")

    shown = False
    for severity in _ORDER:
        group = [f for f in findings if f.severity == severity]
        if not group:
            continue
        shown = True
        out.append(f"<h2>{esc(SEVERITY_LABELS[severity])} ({len(group)})</h2>")
        for f in group:
            cls = " waived" if f.waived else ""
            out.append(f"<div class='f{cls}'>")
            out.append(f"<span class='tag {severity}'>"
                       f"{esc(SEVERITY_LABELS[severity])}</span>")
            if f.waived:
                out.append("<span class='tag waivedtag'>waived</span>")
            out.append(f"<span class='rid'>{esc(f.rule_id)}</span>")
            out.append(f"<div class='msg'>{esc(f.message)}</div>")
            where = _where(f)
            sub = f"{esc(where)} &nbsp;·&nbsp; {esc(f.subject_id)}"
            if f.clause:
                sub += f" &nbsp;·&nbsp; cited: {esc(f.clause)}"
            out.append(f"<div class='sub'>{sub}</div>")
            if f.evidence:
                out.append("<div class='ev'>" + "  ·  ".join(
                    f"{esc(k)}={esc(v)}" for k, v in f.evidence.items()) + "</div>")
            out.append("</div>")

    if not shown:
        if run is not None and run.blocked:
            out.append("<h2>No findings were produced</h2><p>This report is "
                       "not a result. The check did not run — see the "
                       "coverage statement above.</p>")
        else:
            out.append("<h2>No findings</h2><p>Read the coverage statement "
                       "above before treating that as a clean result.</p>")

    if run is not None:
        out.append("<h2>Coverage</h2>")
        if not run.everything_accounted_for:
            out.append(f"<div class='note'>{esc(NOT_CHECKED)}</div>")
        out.append("<div class='scroll'><table><thead><tr><th>Rule</th>"
                   "<th>Eligible</th><th>Checked</th><th>Skipped</th><th>Why</th>"
                   "</tr></thead><tbody>")
        for cov in run.coverage:
            why = ", ".join(f"{n} {r}" for r, n in (cov.reasons or {}).items())
            # An idle rule is marked like a gap, because that is what it is:
            # the table already lists it, and without this it reads as a row of
            # zeroes a reader skims past.
            cls = " class='gap'" if (cov.skipped or not cov.ran) else ""
            if not cov.ran:
                why = "nothing to check against"
            out.append(f"<tr><td>{esc(cov.rule_id)}</td><td>{cov.eligible}</td>"
                       f"<td>{cov.checked}</td><td{cls}>{cov.skipped}</td>"
                       f"<td>{esc(why)}</td></tr>")
        out.append("</tbody></table></div>")

    packs = _packs_line(run)
    if packs:
        out.append(f"<p class='foot'>{esc(packs)}</p>")
    out.append("</div></body></html>")
    text = "\n".join(out)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def export_report(document, path: str, disabled=()) -> str:
    """Export in the format implied by ``path``'s extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".markdown"):
        return export_markdown(document, path, disabled=disabled)
    if ext == ".csv":
        return export_csv(document, path, disabled=disabled)
    return export_html(document, path, disabled=disabled)
