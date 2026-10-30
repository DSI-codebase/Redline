"""The pages that run several PyDRC functions on one form.

The panel load schedule, the panel SCCR and the enclosure's heat each take a
list (loads, components) and some facts about the panel, build PyDRC's own
input types from them, and show every result PyDRC gives, one section each.

The builders here are the only arithmetic-free code between the form and the
library, and they hold its rules: a cell that holds something that is not a
number is named by its row and column rather than passed on as missing, and a
yes-or-no the user left blank is asked for, except where PyDRC states a
default (a load runs with the others; a supply is not 100% rated; a component
is in the power circuit), which its arithmetic then names.

One blank is filled, as an audit fills it: a part's SCCR or watts, when its row
names the manufacturer and catalog number, is read from PyDRC's part ratings
file (``Ratings.fill_sccr`` and ``fill_heat``). A rating nobody has signed is
marked so and can show an SCCR shortfall but never a pass, and the results end
with the file read, by digest, and which rows it filled.

The pages themselves, their fields and their columns, are described in
``specs`` with every other calculator, which imports this module only when one
of them runs.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import specs
from .specs import YES_NO


class _Build:
    """Collects the problems a form has before PyDRC sees it."""

    def __init__(self):
        self.problems: List[str] = []

    def number(self, value, where, whole=False) -> Optional[float]:
        text = "" if value is None else str(value).strip()
        if not text:
            return None
        try:
            n = float(text)
        except ValueError:
            self.problems.append(f"{where}: {text!r} is not a number")
            return None
        if whole:
            if n != int(n):
                self.problems.append(f"{where}: {text!r} is not a whole number")
                return None
            return int(n)
        return n

    def yes_no(self, value, where, default=None):
        text = "" if value is None else str(value).strip().lower()
        if not text:
            if default is None:
                self.problems.append(f"missing {where} (yes or no)")
            return default
        if text not in YES_NO:
            self.problems.append(f"{where}: {text!r} is neither yes nor no")
            return default
        return text == "yes"

    def text(self, value) -> str:
        return "" if value is None else str(value).strip()


def _refused(title, tier, problems):
    from pydrc.calc.result import cannot
    return [(title, cannot("redline." + title.lower().replace(" ", "_"), tier, problems))]


def _function(module, name):
    import importlib
    fn = getattr(importlib.import_module("pydrc.calc." + module), name, None)
    if fn is None:
        import pydrc
        raise specs.Missing(f"PyDRC {getattr(pydrc, '__version__', '?')} has no "
                            f"{module}.{name}. Update the design rule library.")
    return fn


class _Lookup:
    """PyDRC's part ratings file, read at the first row that needs it, and
    what it filled. A row needs it when its rating is blank and it names both
    the manufacturer and the catalog number."""

    HEADING = "Part ratings read"

    def __init__(self, build: _Build):
        self._build = build
        self._file = None
        self.filled: List[str] = []
        self.not_found: List[str] = []

    def _ratings(self):
        if self._file is None:
            try:
                from pydrc.catalog import ratings
            except ImportError:
                ratings = None
            if ratings is None or not hasattr(ratings.Ratings, "fill_sccr"):
                import pydrc
                raise specs.Missing(
                    f"PyDRC {getattr(pydrc, '__version__', '?')} cannot read a part's rating "
                    f"from its ratings file. Update the design rule library, or give every "
                    f"rating.")
            try:
                self._file = ratings.load().check()
            except (OSError, ratings.RatingsError) as e:
                self._build.problems.append(f"the part ratings file could not be read: {e}")
                self._file = False
        return self._file or None

    def _note(self, tag, found):
        (self.filled if found else self.not_found).append(tag)

    def sccr(self, comp, manufacturer, catalog):
        if comp.sccr_ka is not None or not (manufacturer and catalog):
            return comp
        r = self._ratings()
        if r is None:
            return comp
        got = r.fill_sccr(comp, manufacturer, catalog)
        self._note(comp.tag, got.sccr_ka is not None)
        return got

    def heat(self, comp):
        if comp.watts_each is not None or not (comp.manufacturer and comp.catalog):
            return comp
        r = self._ratings()
        if r is None:
            return comp
        got = r.fill_heat(comp)
        self._note(comp.tag, got.watts_each is not None)
        return got

    def section(self) -> List[Tuple[str, object]]:
        """The file read and the rows it filled, or nothing when no row
        needed it."""
        if not self._file:
            return []
        lines = [f"File: PyDRC's part ratings, {self._file.label}",
                 "Filled from it: " + (", ".join(self.filled) or "none")]
        if self.not_found:
            lines.append("Not in it: " + ", ".join(self.not_found))
        return [(self.HEADING, tuple(lines))]


# ---------------------------------------------------------------- the load schedule



def load_schedule(raw) -> List[Tuple[str, object]]:
    """Every result of PyDRC's load schedule for the supply and the loads."""
    from pydrc.calc import panel
    from pydrc.calc.result import TIER_CODE
    title = "Panel load schedule"
    b = _Build()
    phases = b.number(raw.get("supply_phases"), "supply phases", whole=True)
    supply_kwargs = {"voltage": b.number(raw.get("supply_voltage"), "supply voltage"),
                     "phases": phases,
                     "hundred_percent_rated": b.yes_no(raw.get("hundred_percent_rated"),
                                                       "whether the supply device is 100% rated",
                                                       default=False),
                     "load_side_ampacity_a": b.number(raw.get("load_side_ampacity_a"),
                                                      "load-side ampacity")}
    device = b.text(raw.get("supply_ocpd_device"))
    if device:
        supply_kwargs["ocpd_device"] = device
    else:
        b.problems.append("missing supply overcurrent device type")
    loads = []
    for i, row in enumerate(specs.table_rows(raw.get("loads")), 1):
        where = f"load {i}"
        loads.append(panel.PanelLoad(
            tag=b.text(row.get("tag")) or where, kind=b.text(row.get("kind")),
            connection=b.text(row.get("connection")),
            voltage=b.number(row.get("voltage"), f"{where}, volts"),
            hp=b.text(row.get("hp")) or None,
            current_a=b.number(row.get("current_a"), f"{where}, amps"),
            kva=b.number(row.get("kva"), f"{where}, kVA"),
            kw=b.number(row.get("kw"), f"{where}, kW"),
            power_factor=b.number(row.get("power_factor"), f"{where}, PF"),
            simultaneous=b.yes_no(row.get("simultaneous"), f"{where}, runs with the others",
                                  default=True),
            motor_type=b.text(row.get("motor_type")) or None,
            branch_device=b.text(row.get("branch_device")) or None,
            branch_rating_a=b.number(row.get("branch_rating_a"), f"{where}, branch rating")))
    if not loads:
        b.problems.append("no loads: add a row for each load the supply feeds")
    if b.problems:
        return _refused(title, TIER_CODE, b.problems)
    supply = panel.PanelSupply(**supply_kwargs)
    s = _function("panel", "schedule")(supply, loads)
    out = [("Panel full-load current", s["full_load_current"]),
           ("Supply conductor ampacity, NEC", s["supply_conductor_nec"]),
           ("Supply conductor ampacity, UL 508A", s["supply_conductor_ul"]),
           ("Maximum supply OCPD, NEC", s["max_supply_ocpd_nec"]),
           ("Maximum supply OCPD, UL 508A", s["max_supply_ocpd_ul"]),
           ("Minimum supply OCPD", s["min_supply_ocpd"])]
    out += [(f"Load {tag}", r) for tag, r in s["loads"].items()]
    out += [(f"Branch {tag}", r) for tag, r in s["branches"].items()]
    return out


# ---------------------------------------------------------------- SCCR



def panel_rating(raw) -> List[Tuple[str, object]]:
    """The panel's SCCR, the most its rated components allow, each circuit's
    rating, and the comparison with the fault current or the required SCCR."""
    from pydrc.calc import sccr
    from pydrc.calc.result import TIER_CODE
    title = "Panel SCCR"
    b = _Build()
    volts = b.number(raw.get("system_voltage_v"), "system voltage")
    available = b.number(raw.get("available_fault_ka"), "available fault current")
    required = b.number(raw.get("required_sccr_ka"), "required SCCR")
    lookup = _Lookup(b)
    comps = []
    for i, row in enumerate(specs.table_rows(raw.get("components")), 1):
        where = f"component {i}"
        comps.append(lookup.sccr(sccr.SccrComponent(
            tag=b.text(row.get("tag")) or where, kind=b.text(row.get("kind")),
            circuit=b.text(row.get("circuit")),
            sccr_ka=b.number(row.get("sccr_ka"), f"{where}, marked SCCR"),
            voltage_v=b.number(row.get("voltage_v"), f"{where}, volts"),
            rating_source=b.text(row.get("rating_source")),
            sb41_row=b.number(row.get("sb41_row"), f"{where}, SB4.1 row", whole=True),
            control_circuit=b.yes_no(row.get("control_circuit"), f"{where}, control circuit",
                                     default=False)),
            b.text(row.get("manufacturer")), b.text(row.get("catalog"))))
        if not comps[-1].circuit:
            b.problems.append(f"missing {where}'s circuit: feeder, or its branch circuit")
    if not comps:
        b.problems.append("no components: add a row for each one")
    if b.problems:
        return _refused(title, TIER_CODE, b.problems)
    out = [("Panel SCCR", _function("sccr", "panel_sccr")(comps, volts)),
           ("Ceiling from the rated components", _function("sccr", "panel_sccr_ceiling")(comps, volts)),
           ("Against the target", _function("sccr", "compare")(comps, volts, available, required))]
    circuits = list(dict.fromkeys(c.circuit for c in comps if not c.control_circuit))
    out += [(f"Circuit {cid}", _function("sccr", "circuit_sccr")(cid, comps, volts)) for cid in circuits]
    return out + lookup.section()


# ---------------------------------------------------------------- heat



def _quantity(b, value, where):
    """A part's quantity: 1 when the cell is empty, as one row is one part."""
    if not b.text(value):
        return 1
    q = b.number(value, f"{where}, quantity", whole=True)
    return q if q is not None else 1


def enclosure_heat(raw) -> List[Tuple[str, object]]:
    """The heat load (or its floor), the enclosure's area, the cooling it needs,
    its rise with no cooling, and the check against the selected product."""
    from pydrc.calc import heat
    from pydrc.calc.result import TIER_METHOD
    title = "Enclosure heat"
    b = _Build()
    lookup = _Lookup(b)
    comps = []
    for i, row in enumerate(specs.table_rows(raw.get("components")), 1):
        where = f"part {i}"
        comps.append(lookup.heat(heat.HeatComponent(
            tag=b.text(row.get("tag")) or where,
            quantity=_quantity(b, row.get("quantity"), where),
            watts_each=b.number(row.get("watts_each"), f"{where}, watts"),
            manufacturer=b.text(row.get("manufacturer")), catalog=b.text(row.get("catalog")),
            source=b.text(row.get("source")),
            verified=b.yes_no(row.get("verified"), f"{where}, checked", default=False))))
    enclosure = heat.Enclosure(
        height_in=b.number(raw.get("height_in"), "height"),
        width_in=b.number(raw.get("width_in"), "width"),
        depth_in=b.number(raw.get("depth_in"), "depth"),
        sealed=b.yes_no(raw.get("sealed"), "whether the enclosure is sealed"),
        indoor=b.yes_no(raw.get("indoor"), "whether it is indoors"),
        insulated=b.yes_no(raw.get("insulated"), "whether it is insulated"))
    margin = b.number(raw.get("margin_pct"), "safety margin")
    unit = b.text(raw.get("unit"))
    if not unit:
        b.problems.append("missing the temperatures' unit, C or F")
    outside = b.number(raw.get("outside_max"), "outside maximum")
    inside = b.number(raw.get("inside_max"), "inside maximum")
    rated = b.number(raw.get("rated_btu_hr"), "cooling product's rating")
    if b.problems:
        return _refused(title, TIER_METHOD, b.problems)
    exact = _function("heat", "heat_load")(comps, margin)
    out = [("Heat load", exact)]
    load, at_least = exact, ""
    if not exact.computed:
        load = _function("heat", "heat_load_floor")(comps, margin)
        out.append(("Heat load, the rated parts alone", load))
        at_least = ", at least"
    out.append(("Surface area", _function("heat", "surface_area")(enclosure)))
    if load.computed:
        w = load["total_w"]
        out.append((f"Cooling required{at_least}",
                    _function("heat", "required_cooling")(w, enclosure, outside, inside, unit)))
        out.append((f"Rise with no cooling{at_least}",
                    _function("heat", "temperature_rise")(w, enclosure)))
    out.append(("Against the selected cooling",
                _function("heat", "cooling_check")(comps, margin, enclosure, outside, inside,
                                                   rated, unit)))
    return out + lookup.section()
