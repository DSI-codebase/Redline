"""A calculator's result as plain text: what the tab shows and what Copy copies.

Everything PyDRC returns is shown, in the order a reader checks it: the tier,
then the values or the reasons there are none, then the arithmetic, the clauses
it rests on, and the sign-off state of every table it read. A table nobody has
signed says so on every result, here as in the library.
"""

from __future__ import annotations

from typing import List

#: What each tier means, in the words the PyDRC plan gives it.
TIERS = {
    "code": "code: cites a clause and a table of a published code",
    "method": "method: a named engineering method, not a code table",
    "estimate": "estimate: a placeholder or an approximation. It never feeds a "
                "design rule finding",
}
ADVISORY = ("Advisory. Confirm against the code book and the product listing: "
            "this is not a determination of compliance.")

#: Unit suffixes PyDRC's value names carry, longest first.
_UNITS = (
    ("_ohm_per_kft", "ohm/kft"), ("_lb_per_kft", "lb/kft"), ("_lb_per_ft", "lb/ft"),
    ("_usd_per_kft", "USD/kft"), ("_usd_per_year", "USD a year"),
    ("_kwh_per_year", "kWh a year"), ("_btu_hr", "BTU/hr"), ("_in2", "in2"), ("_ft2", "ft2"),
    ("_cmil", "cmil"), ("_pct", "%"), ("_usd", "USD"), ("_kwh", "kWh"), ("_kvar", "kVAR"),
    ("_kva", "kVA"), ("_kw", "kW"), ("_hp", "hp"), ("_ka", "kA"), ("_hr", "h"),
    ("_ft", "ft"), ("_in", "in"), ("_lb", "lb"), ("_a", "A"), ("_v", "V"), ("_c", "C"),
    ("_f", "F"), ("_w", "W"),
)


def label(key: str) -> str:
    """``"voltage_drop_pct"`` -> ``"voltage drop (%)"``."""
    for suffix, unit in _UNITS:
        if key.endswith(suffix) and len(key) > len(suffix):
            return f"{key[:-len(suffix)].replace('_', ' ')} ({unit})"
    return key.replace("_", " ")


def value_text(value) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".") if abs(value) >= 0.0001 else f"{value:.3g}"
    return str(value)


def _value_lines(key, value, indent) -> List[str]:
    pad = " " * indent
    if isinstance(value, dict):
        out = [f"{pad}{label(key)}:"]
        for k, v in value.items():
            out += _value_lines(k, v, indent + 2)
        return out
    if isinstance(value, (list, tuple)) and value and all(isinstance(v, dict) for v in value):
        out = [f"{pad}{label(key)}:"]
        for i, item in enumerate(value, 1):
            out.append(f"{pad}  {i}.")
            for k, v in item.items():
                out += _value_lines(k, v, indent + 4)
        return out
    if isinstance(value, (list, tuple)):
        return [f"{pad}{label(key)}: {', '.join(value_text(v) for v in value) or 'none'}"]
    return [f"{pad}{label(key)}: {value_text(value)}"]


def result_lines(result, advisory=True) -> List[str]:
    """The result, one line per item."""
    lines = [TIERS.get(result.tier, result.tier)]
    if result.computed:
        lines += ["", "RESULT"]
        for k, v in result.values.items():
            lines += _value_lines(k, v, 2)
        if result.steps:
            lines += ["", "HOW"]
            lines += [f"  {i}. {s}" for i, s in enumerate(result.steps, 1)]
    else:
        lines += ["", "NOT COMPUTED, because:"]
        lines += [f"  - {r}" for r in result.reasons]
    if result.cites:
        lines += ["", "CITED"]
        lines += [f"  {c.render()}" for c in result.cites]
    if result.tables:
        lines += ["", "TABLES"]
        lines += [f"  {note}" for note in dict.fromkeys(t.note for t in result.tables)]
    if advisory:
        lines += ["", ADVISORY]
    return lines


def sections_lines(sections) -> List[str]:
    """``[(heading, Result)]`` as text: one section each, the advisory once."""
    if len(sections) == 1 and not sections[0][0]:
        return result_lines(sections[0][1])
    lines = []
    for heading, result in sections:
        if lines:
            lines.append("")
        lines += [f"== {heading} =="] + result_lines(result, advisory=False)
    return lines + ["", ADVISORY]


def input_lines(calc, raw: dict) -> List[str]:
    """What the form held, blank fields included, so a copied result shows
    what was not given."""
    out = []
    for f in calc.fields:
        v = raw.get(f.name)
        if f.kind == "table":
            rows = [r for r in (v or ()) if any(str(x).strip() for x in r.values() if x is not None)]
            out.append(f"  {f.label}: " + ("(none)" if not rows else f"{len(rows)} rows"))
            for i, r in enumerate(rows, 1):
                cells = [f"{c.label} {str(r.get(c.name)).strip()}" + (f" {c.unit}" if c.unit else "")
                         for c in f.columns if r.get(c.name) is not None and str(r.get(c.name)).strip()]
                out.append(f"    {i}. " + ", ".join(cells))
            continue
        if f.kind == "bool":
            shown = "yes" if v else "no"
        else:
            shown = str(v).strip() if v is not None and str(v).strip() else "(blank)"
        unit = f" {f.unit}" if f.unit and shown != "(blank)" else ""
        out.append(f"  {f.label}: {shown}{unit}")
    return out


def copy_text(calc, raw: dict, result, pydrc_version: str = "") -> str:
    """``result`` is a Result, or ``[(heading, Result)]`` from a page that runs
    several."""
    lines = [calc.title + (f" (PyDRC {pydrc_version}, {calc.id})" if pydrc_version else
                           f" ({calc.id})"), "", "INPUTS"]
    lines += input_lines(calc, raw)
    sections = result if isinstance(result, list) else [("", result)]
    lines += [""] + sections_lines(sections)
    return "\n".join(lines) + "\n"
