"""What each calculator asks for: one description per PyDRC function.

A description names the function, and for each input its label, its unit and
what kind of field holds it. The form is built from these and nothing else, so
adding a calculator is adding a description. ``tests/test_calculators.py``
holds every description to the function's own signature, and holds the list of
descriptions to the library: a public calculator PyDRC adds is either described
here or named in ``LATER`` or ``HELPERS`` with the reason, or the test fails.

Choices that PyDRC lists (conductor sizes, raceways, motor types) are asked of
PyDRC when the form is built, never copied here.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Tuple, Union

NUMBER, CHOICE, BOOL = "number", "choice", "bool"

MATERIALS = ("copper", "aluminum")
SYSTEMS = ("dc", "1ph", "3ph")
AC_SYSTEMS = ("1ph", "3ph")
CONDUITS = ("pvc", "aluminum", "steel")
COLUMNS = ("60", "75", "90")
WIRE_TYPES = ("THHN", "XHHW", "RHH")


def _sizes():
    from pydrc.calc import conductors
    return conductors.sizes()


def _raceways():
    from pydrc.calc import raceway
    return tuple(raceway.raceways())


def _trade_sizes():
    from pydrc.calc import tables
    return tuple(tables.load("NEC", "chapter9-4", "2026").data["trade_sizes"])


def _motor_types():
    from pydrc.calc import motors
    return tuple(motors.motor_types())


def _branch_devices():
    from pydrc.calc import tables
    return tuple(tables.load("NEC", "430.52-C1", "2026").data["devices"])


def _wire_locations():
    from pydrc.calc import tables
    entries = tables.load("DSI", "wire-type-guide", "2026").data["entries"]
    return tuple(dict.fromkeys(e["location"] for e in entries))


def _wiring_methods():
    from pydrc.calc import tables
    entries = tables.load("DSI", "wire-type-guide", "2026").data["entries"]
    return tuple(dict.fromkeys(e["wiring_method"] for e in entries))


def _lead_insulations():
    from pydrc.calc import tables
    return tuple(tables.load("DSI", "lead-wire", "2026")
                 .data["insulation_thermal_resistivity_k_m_per_w"])


def _lssi(key):
    def choices():
        from pydrc.calc import estimating
        return tuple(estimating.defaults().data["lssi.scores"]["value"][key])
    return choices


@dataclass(frozen=True)
class Field:
    name: str                 # the function's parameter
    label: str
    kind: str = NUMBER
    unit: str = ""
    choices: Union[Sequence[str], Callable[[], Sequence[str]], None] = None
    editable: bool = False    # a choice list that also takes typed text
    hint: str = ""

    def options(self) -> Tuple[str, ...]:
        c = self.choices() if callable(self.choices) else (self.choices or ())
        return tuple(str(x) for x in c)


@dataclass(frozen=True)
class Calculator:
    id: str                   # "conductors.voltage_drop": module and function
    title: str
    fields: Tuple[Field, ...]
    summary: str = ""

    @property
    def module(self) -> str:
        return "pydrc.calc." + self.id.split(".")[0]

    @property
    def function_name(self) -> str:
        return self.id.split(".", 1)[1]

    def function(self):
        """The PyDRC function, or None when this PyDRC has no such function."""
        try:
            mod = importlib.import_module(self.module)
        except ImportError:
            return None
        return getattr(mod, self.function_name, None)


@dataclass(frozen=True)
class Page:
    title: str
    calculators: Tuple[Calculator, ...] = field(default_factory=tuple)


def F(name, label, kind=NUMBER, unit="", choices=None, editable=False, hint=""):
    return Field(name, label, kind, unit, choices, editable, hint)


def C(id, title, *fields, summary=""):
    return Calculator(id, title, tuple(fields), summary)


SIZE = F("size", "Conductor size", CHOICE, choices=_sizes, editable=True, hint="AWG or kcmil")
MATERIAL = F("material", "Material", CHOICE, choices=MATERIALS)
SYSTEM = F("system", "System", CHOICE, choices=SYSTEMS)
CONDUIT = F("installation", "Conduit", CHOICE, choices=CONDUITS,
            hint="Chapter 9 Table 9's columns; leave blank for DC")
PF = F("power_factor", "Power factor", hint="0 to 1; leave blank for DC")
COLUMN = F("column_c", "Temperature column", CHOICE, "C", COLUMNS)
SETS = F("parallel_sets", "Parallel sets", hint="blank for one set")
TEMP = F("conductor_temp_c", "Conductor temperature", unit="C",
         hint="blank for the tables' 75 C")

PAGES: Tuple[Page, ...] = (
    Page("Conductors", (
        C("conductors.ampacity", "Ampacity (Table 310.16)", SIZE, COLUMN, MATERIAL),
        C("conductors.ambient_correction", "Ambient correction (310.15(B))",
          F("ambient_c", "Ambient", unit="C"), COLUMN),
        C("conductors.adjustment_factor", "Bundling adjustment (310.15(C)(1))",
          F("current_carrying", "Current-carrying conductors")),
        C("conductors.small_conductor_max_ocpd", "Small conductor protection (240.4(D))",
          SIZE, MATERIAL),
        C("conductors.next_standard_rating", "Next standard rating up (240.6(A))",
          F("amps", "Current", unit="A"), F("device", "Device", CHOICE, choices=("breaker", "fuse"))),
        C("conductors.next_lower_standard_rating", "Next standard rating down (240.6(A))",
          F("amps", "Current", unit="A"), F("device", "Device", CHOICE, choices=("breaker", "fuse"))),
        C("conductors.equipment_grounding_conductor", "Grounding conductor (Table 250.122)",
          F("ocpd_a", "Overcurrent device", unit="A"), MATERIAL),
        C("conductors.building_wire_size", "Building wire selector",
          F("continuous_a", "Continuous load", unit="A", hint="0 when there is none"),
          F("noncontinuous_a", "Noncontinuous load", unit="A", hint="0 when there is none"),
          F("insulation_c", "Insulation rating", CHOICE, "C", COLUMNS),
          F("termination_c", "Termination rating", CHOICE, "C", COLUMNS),
          F("ambient_c", "Ambient", unit="C"),
          F("current_carrying", "Current-carrying conductors"), MATERIAL,
          F("voltage", "Voltage, for a drop check", unit="V", hint="optional"),
          F("length_ft", "One-way length, for a drop check", unit="ft", hint="optional"),
          SYSTEM, CONDUIT, PF,
          F("max_drop_pct", "Maximum voltage drop", unit="%", hint="optional"),
          summary="Size, overcurrent device and grounding conductor for a load."),
        C("conductors.wire_types", "Wire type guide",
          F("location", "Location", CHOICE, choices=_wire_locations),
          F("wiring_method", "Wiring method", CHOICE, choices=_wiring_methods),
          F("insulation_c", "Insulation rating", CHOICE, "C", COLUMNS)),
        C("conductors.metal_weight", "Metal weight", SIZE, MATERIAL),
        C("conductors.cu_al_equivalent", "Copper and aluminum equivalent",
          SIZE, F("from_material", "From", CHOICE, choices=MATERIALS), COLUMN,
          F("wire_type", "Wire type, for its diameter", CHOICE, choices=WIRE_TYPES, editable=True),
          F("copper_usd_per_lb", "Copper price", unit="USD/lb", hint="optional, with aluminum"),
          F("aluminum_usd_per_lb", "Aluminum price", unit="USD/lb", hint="optional, with copper")),
        C("conductors.concentric_neutral", "Concentric neutral (MV cable)",
          F("phase_size", "Phase conductor", CHOICE, choices=_sizes, editable=True, hint="AWG or kcmil"),
          F("phase_material", "Phase material", CHOICE, choices=MATERIALS),
          F("neutral_fraction", "Neutral", CHOICE, choices=("full", "1/2", "1/3", "1/6", "1/12"),
            editable=True),
          F("neutral_wire", "Neutral wire", CHOICE, "AWG", ("16", "14", "12", "10", "8")),
          F("core_od_in", "Core diameter", unit="in", hint="optional"),
          F("fault_ka", "Fault current to check", unit="kA", hint="optional"),
          F("fault_cycles", "Fault duration", unit="cycles", hint="with both temperatures"),
          F("initial_c", "Initial temperature", unit="C"),
          F("final_c", "Final temperature", unit="C")),
        C("conductors.lead_wire_ampacity", "Lead wire ampacity",
          F("awg", "Wire size", hint="AWG, 36 to 4/0"), MATERIAL,
          F("insulation", "Insulation", CHOICE, choices=_lead_insulations),
          F("insulation_c", "Insulation rating", unit="C"),
          F("wall_in", "Insulation wall", unit="in"),
          F("ambient_c", "Ambient", unit="C"),
          F("bundled", "Current-carrying conductors in the bundle")),
        C("conductors.reliability_index", "Reliability index",
          F("load_a", "Load", unit="A"), SIZE, MATERIAL,
          F("insulation_c", "Insulation rating", CHOICE, "C", COLUMNS),
          F("ambient_c", "Ambient", unit="C"),
          F("current_carrying", "Current-carrying conductors"),
          F("system", "System", CHOICE, choices=AC_SYSTEMS),
          F("length_ft", "One-way length", unit="ft"), F("voltage", "Voltage", unit="V"),
          F("hours_per_year", "Hours a year", unit="h"),
          F("energy_usd_per_kwh", "Energy price", unit="USD/kWh"),
          F("upsize_steps", "Larger sizes to compare")),
    )),
    Page("Voltage drop", (
        C("conductors.voltage_drop", "Voltage drop",
          SIZE, F("current_a", "Current", unit="A"), F("length_ft", "One-way length", unit="ft"),
          F("voltage", "Voltage", unit="V"), SYSTEM, MATERIAL, CONDUIT, PF, SETS, TEMP),
        C("conductors.voltage_drop_min_size", "Smallest size for a drop limit",
          F("current_a", "Current", unit="A"), F("length_ft", "One-way length", unit="ft"),
          F("voltage", "Voltage", unit="V"), SYSTEM,
          F("max_drop_pct", "Maximum voltage drop", unit="%"), COLUMN, MATERIAL, CONDUIT, PF,
          SETS, TEMP),
        C("conductors.voltage_drop_max_length", "Longest run for a drop limit",
          SIZE, F("current_a", "Current", unit="A"), F("voltage", "Voltage", unit="V"), SYSTEM,
          F("max_drop_pct", "Maximum voltage drop", unit="%"), MATERIAL, CONDUIT, PF, SETS, TEMP),
        C("conductors.impedance", "Conductor impedance (Chapter 9 Tables 8 and 9)",
          SIZE, MATERIAL, SYSTEM, CONDUIT, PF, TEMP),
    )),
    Page("Raceway", (
        C("raceway.internal_diameter", "Raceway internal diameter (Chapter 9 Table 4)",
          F("raceway", "Raceway", CHOICE, choices=_raceways),
          F("trade_size", "Trade size", CHOICE, choices=_trade_sizes)),
        C("raceway.conductor_diameter", "Conductor diameter (Chapter 9 Table 5)",
          F("wire_type", "Wire type", CHOICE, choices=WIRE_TYPES, editable=True), SIZE),
        C("raceway.fill_limit", "Fill limit (Chapter 9 Table 1)",
          F("conductor_count", "Conductors"),
          F("nipple", "A nipple of 24 in or less", BOOL)),
        C("raceway.jam_ratio", "Jam ratio",
          F("raceway_id_in", "Raceway internal diameter", unit="in"),
          F("cable_od_in", "Cable diameter", unit="in")),
        C("raceway.weight_correction", "Weight correction factor",
          F("cable_count", "Cables"), F("raceway_id_in", "Raceway internal diameter", unit="in"),
          F("cable_od_in", "Cable diameter", unit="in"),
          F("configuration", "Configuration", CHOICE, choices=("triangular", "cradled"),
            hint="three cables; blank lets the method choose")),
        C("raceway.cable_weight_estimate", "Cable weight estimate",
          F("wire_type", "Wire type", CHOICE, choices=WIRE_TYPES, editable=True), SIZE, MATERIAL),
    )),
    Page("Motors", (
        C("motors.full_load_current", "Motor full-load current (Tables 430.248, 430.250)",
          F("hp", "Horsepower", hint="1/2, 1-1/2, 7.5 ..."), F("voltage", "Voltage", unit="V"),
          F("phases", "Phases", CHOICE, choices=("1", "3"))),
        C("motors.branch_protection_percent", "Branch device percent (Table 430.52(C)(1))",
          F("motor_type", "Motor type", CHOICE, choices=_motor_types),
          F("device", "Device", CHOICE, choices=_branch_devices)),
        C("motors.vfd_output_conductors", "Drive motor leads",
          F("hp", "Horsepower"), F("voltage", "Voltage", unit="V"), MATERIAL,
          F("insulation_c", "Insulation rating", CHOICE, "C", COLUMNS),
          F("termination_c", "Termination rating", CHOICE, "C", COLUMNS),
          F("ambient_c", "Ambient", unit="C"),
          F("branch_ocpd_a", "Branch device, from the drive maker", unit="A",
            hint="optional; sizes the grounding conductor")),
        C("motors.vfd_cable_guide", "Drive cable guide", F("voltage", "Voltage", unit="V")),
    )),
    Page("Power", (
        C("power.convert", "Power conversion",
          SYSTEM, F("voltage", "Voltage", unit="V"),
          F("known", "Known quantity", CHOICE, choices=("amps", "kw", "kva", "hp")),
          F("value", "Value"), F("power_factor", "Power factor", hint="0 to 1; blank for DC"),
          F("efficiency", "Efficiency", hint="0 to 1; needed for horsepower")),
    )),
    Page("Estimating", (
        C("estimating.mcap_savings", "MCAP labor savings",
          F("receptacles", "Receptacles"), F("switches", "Switches"), F("fixtures", "Fixtures"),
          F("junction_boxes", "Junction boxes"), F("panel_terminations", "Panel terminations"),
          F("labor_usd_per_hr", "Labor rate", unit="USD/h"), F("cable_ft", "Cable", unit="ft"),
          F("savings_fraction", "Savings fraction", hint="blank for the business default")),
        C("estimating.hcf_mcap_savings", "HCF MCAP labor savings",
          F("cable_ft", "Cable", unit="ft"), F("cable_ends", "Cable ends"),
          F("conductors_per_cable", "Conductors per cable"),
          F("labor_usd_per_hr", "Labor rate", unit="USD/h")),
        C("estimating.cic_labor_savings", "Cable-in-conduit labor savings",
          F("run_ft", "Run length", unit="ft"), F("ducts", "Ducts"), F("crew_size", "Crew size"),
          F("labor_usd_per_hr", "Labor rate", unit="USD/h")),
        C("estimating.led_lighting_savings", "Temporary LED lighting",
          F("fixtures", "Fixtures"), F("legacy_watts", "Legacy fixture, with ballast", unit="W"),
          F("led_watts", "LED fixture", unit="W"), F("hours_per_day", "Hours a day"),
          F("days_per_week", "Days a week"), F("weeks", "Weeks"),
          F("energy_usd_per_kwh", "Energy price", unit="USD/kWh"),
          F("legacy_lamp_life_hr", "Legacy lamp life", unit="h"),
          F("legacy_relamp_usd", "Legacy relamp cost", unit="USD"),
          F("legacy_fixture_usd", "Legacy fixture cost", unit="USD"),
          F("led_fixture_usd", "LED fixture cost", unit="USD"),
          F("circuit_voltage", "Circuit voltage", unit="V"), F("breaker_a", "Breaker", unit="A")),
        C("estimating.mv_cable_lssi", "MV cable index",
          *(F(k, k.replace("_", " ").capitalize(), CHOICE, choices=_lssi(k))
            for k in ("conductor_material", "conductor_type", "conductor_shield", "insulation",
                      "insulation_level", "insulation_shield", "metallic_shield", "jacket",
                      "water_blocking", "voltage_class"))),
    )),
)

#: Public PyDRC functions with no page yet, and why. The list-input pages come
#: next (the PyDRC plan's P8 step 7, second part); a function that appears in
#: PyDRC and in none of PAGES, LATER or HELPERS fails tests/test_calculators.py.
LATER = {
    "raceway.conduit_fill": "a list of conductors",
    "raceway.cable_pull": "a list of segments",
    "panel.*": "a list of loads",
    "sccr.*": "a list of components",
    "heat.*": "a list of components and an enclosure",
}
#: Public PyDRC functions that are not calculators: they list or spell things.
HELPERS = {
    "conductors.sizes", "conductors.normalize_size", "conductors.size_label",
    "conductors.standard_ratings", "raceway.raceways", "raceway.trade_sizes",
    "motors.horsepower", "motors.motor_types", "estimating.defaults",
}


def all_calculators():
    return [c for p in PAGES for c in p.calculators]


def find(calc_id: str) -> Optional[Calculator]:
    return next((c for c in all_calculators() if c.id == calc_id), None)


class Missing(LookupError):
    """This PyDRC has no such calculator."""


def call(calc: Calculator, raw: dict):
    """Run ``calc`` on what the form holds: ``{field name: text, bool or None}``.

    A blank field is left out of the call when the function has a default for
    it, so PyDRC's own default applies and its result says so (copper, one
    parallel set); every other blank is passed as None, which PyDRC reports as
    missing. Text goes as text: PyDRC parses it and names what it cannot.
    """
    fn = calc.function()
    if fn is None:
        import pydrc
        raise Missing(f"PyDRC {getattr(pydrc, '__version__', '?')} has no "
                      f"{calc.id}. Update the design rule library.")
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):            # pragma: no cover - builtins only
        params = {}
    kwargs = {}
    for f in calc.fields:
        value = raw.get(f.name)
        if f.kind == BOOL:
            kwargs[f.name] = bool(value)
            continue
        text = "" if value is None else str(value).strip()
        if text:
            kwargs[f.name] = text
        else:
            p = params.get(f.name)
            if p is not None and p.default is not inspect.Parameter.empty:
                continue
            kwargs[f.name] = None
    return fn(**kwargs)
