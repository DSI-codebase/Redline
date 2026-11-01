"""What each calculator asks for: one description per PyDRC function.

A description names the function, and for each input its label, its unit and
what kind of field holds it. The form is built from these and nothing else, so
adding a calculator is adding a description. ``tests/test_calculators.py``
holds every description to the function's own signature, and holds the list of
descriptions to the library: a public calculator PyDRC adds is either described
here, covered by a page that runs several (``covers``), or named in ``HELPERS``
with the reason, or the test fails.

Most calculators take plain fields. A few take a list (conductors in a
raceway, a pull's segments, a panel's loads or components), held in a TABLE
field whose columns are described the same way. Four calculators run several
PyDRC functions on one form: a transformer's overcurrent protection, the panel
load schedule, the panel SCCR and the enclosure's heat. They are described here
with the rest, and their builders,
which turn the rows into PyDRC's own input types, are
``app/calculators/lists.py``. That module imports this one, so this one
imports it only when such a page runs (``_runner``).

Choices that PyDRC lists (conductor sizes, raceways, motor types) are asked of
PyDRC when the form is built, never copied here.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Tuple, Union

NUMBER, CHOICE, BOOL, TABLE = "number", "choice", "bool", "table"
#: A yes-or-no answer that may be left unanswered, unlike BOOL's checkbox.
YES_NO = ("yes", "no")

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


def _panel_choices(name):
    def choices():
        from pydrc.calc import panel
        return tuple(getattr(panel, name))
    return choices


def _transformer_choices(name):
    def choices():
        from pydrc.calc import transformer
        return tuple(getattr(transformer, name))
    return choices


def _sccr_kinds():
    from pydrc.calc import sccr
    return tuple(sccr.kinds())


def _lssi(key):
    def choices():
        from pydrc.calc import estimating
        return tuple(estimating.defaults().data["lssi.scores"]["value"][key])
    return choices


@dataclass(frozen=True)
class Field:
    name: str                 # the function's parameter, or a TABLE column's key
    label: str
    kind: str = NUMBER
    unit: str = ""
    choices: Union[Sequence[str], Callable[[], Sequence[str]], None] = None
    editable: bool = False    # a choice list that also takes typed text
    hint: str = ""
    columns: Tuple["Field", ...] = ()   # a TABLE's columns, each a Field

    def options(self) -> Tuple[str, ...]:
        c = self.choices() if callable(self.choices) else (self.choices or ())
        return tuple(str(x) for x in c)


@dataclass(frozen=True)
class Calculator:
    id: str                   # "conductors.voltage_drop": module and function
    title: str
    fields: Tuple[Field, ...]
    summary: str = ""
    #: A page that runs several PyDRC functions: runner(raw) -> [(heading, Result)].
    runner: Optional[Callable] = None
    #: The PyDRC functions such a page runs, "module.function" each.
    covers: Tuple[str, ...] = ()

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


def F(name, label, kind=NUMBER, unit="", choices=None, editable=False, hint="", columns=()):
    return Field(name, label, kind, unit, choices, editable, hint, tuple(columns))


def C(id, title, *fields, summary="", runner=None, covers=()):
    return Calculator(id, title, tuple(fields), summary, runner, tuple(covers))


SIZE = F("size", "Conductor size", CHOICE, choices=_sizes, editable=True, hint="AWG or kcmil")
MATERIAL = F("material", "Material", CHOICE, choices=MATERIALS)
SYSTEM = F("system", "System", CHOICE, choices=SYSTEMS)
CONDUIT = F("installation", "Conduit", CHOICE, choices=CONDUITS,
            hint="Chapter 9 Table 9's columns. Leave blank for DC")
PF = F("power_factor", "Power factor", hint="0 to 1, blank for DC")
COLUMN = F("column_c", "Temperature column", CHOICE, "C", COLUMNS)
SETS = F("parallel_sets", "Parallel sets", hint="blank for one set")
TEMP = F("conductor_temp_c", "Conductor temperature", unit="C",
         hint="blank for the tables' 75 C")



def _runner(name):
    """The builder ``lists.<name>``, imported when its page runs: ``lists``
    imports this module, so importing it while this one loads is a cycle."""
    def run_page(raw):
        from . import lists
        return getattr(lists, name)(raw)
    run_page.__name__ = name
    return run_page


#: The Panel page's lists. A blank yes or no takes PyDRC's stated default
#: where its type has one, and each column's hint says which.
LOAD_COLUMNS = (
    F("tag", "Tag", "text"), F("kind", "Kind", CHOICE, choices=_panel_choices("LOAD_KINDS")),
    F("connection", "Connection", CHOICE, choices=_panel_choices("CONNECTIONS")),
    F("voltage", "Volts", unit="V"), F("hp", "hp"), F("current_a", "Amps", unit="A"),
    F("kva", "kVA"), F("kw", "kW"), F("power_factor", "PF"),
    F("simultaneous", "Runs with the others", CHOICE, choices=YES_NO,
      hint="blank: yes, the larger totals"),
    F("motor_type", "Motor type", CHOICE, choices=_motor_types),
    F("branch_device", "Branch device", CHOICE, choices=_panel_choices("BRANCH_DEVICES")),
    F("branch_rating_a", "Branch rating", unit="A"),
)

#: The hint on a rating a blank row reads from PyDRC's part ratings file.
_LOOKED_UP = "blank: read from the part ratings file by manufacturer and catalog"

COMPONENT_COLUMNS = (
    F("tag", "Tag", "text"), F("kind", "Kind", CHOICE, choices=_sccr_kinds),
    F("circuit", "Circuit", "text", hint="feeder, or the branch circuit's name"),
    F("manufacturer", "Manufacturer", "text"), F("catalog", "Catalog", "text"),
    F("sccr_ka", "Marked SCCR", unit="kA", hint=_LOOKED_UP), F("voltage_v", "At", unit="V"),
    F("rating_source", "Source", "text"), F("sb41_row", "SB4.1 row"),
    F("control_circuit", "Control circuit", CHOICE, choices=YES_NO, hint="blank: no"),
)

HEAT_COLUMNS = (
    F("tag", "Tag", "text"), F("quantity", "Qty"),
    F("watts_each", "Watts each", unit="W", hint=_LOOKED_UP),
    F("manufacturer", "Manufacturer", "text"), F("catalog", "Catalog", "text"),
    F("source", "Source of the watts", "text"),
    F("verified", "Checked against a datasheet", CHOICE, choices=YES_NO, hint="blank: no"),
)


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
            hint="three cables. Blank lets the method choose")),
        C("raceway.cable_weight_estimate", "Cable weight estimate",
          F("wire_type", "Wire type", CHOICE, choices=WIRE_TYPES, editable=True), SIZE, MATERIAL),
        C("raceway.conduit_fill", "Conduit fill (Chapter 9)",
          F("raceway", "Raceway", CHOICE, choices=_raceways),
          F("conductor_list", "Conductors", TABLE, columns=(
              F("qty", "Qty"), F("wire_type", "Wire type", CHOICE, choices=WIRE_TYPES, editable=True),
              F("size", "Size", CHOICE, choices=_sizes, editable=True),
              F("od_in", "Or diameter", unit="in"), F("label", "Label", "text"))),
          F("trade_size", "Trade size to evaluate", CHOICE, choices=_trade_sizes,
            hint="blank for the smallest that holds them"),
          F("nipple", "A nipple of 24 in or less", BOOL),
          summary="Each row is a wire type and size, or a cable by its diameter."),
        C("raceway.cable_pull", "Cable pulling tension",
          F("raceway_id_in", "Raceway internal diameter", unit="in"),
          F("cable_count", "Cables"), F("cable_od_in", "Cable diameter", unit="in"),
          F("cable_weight_lb_per_ft", "Weight per cable", unit="lb/ft"),
          F("segments", "Segments, from the pulling end", TABLE, columns=(
              F("type", "Type", CHOICE, choices=("straight", "bend")),
              F("length_ft", "Length", unit="ft"), F("incline_deg", "Incline", unit="deg"),
              F("angle_deg", "Bend angle", unit="deg"), F("radius_ft", "Bend radius", unit="ft"))),
          F("friction", "Coefficient of friction", hint="the lubricant's and the jacket's"),
          F("configuration", "Configuration", CHOICE, choices=("triangular", "cradled"),
            hint="three cables. Blank lets the method choose"),
          F("conductor_cmil", "Conductor area", unit="cmil", hint="with material, for the tension limit"),
          F("material", "Conductor material", CHOICE, choices=MATERIALS),
          F("max_sidewall_lb_per_ft", "Sidewall pressure limit", unit="lb/ft", hint="optional"),
          F("device_limit_lb", "Pulling device limit", unit="lb", hint="optional"),
          F("min_clearance_in", "Minimum clearance", unit="in", hint="optional"),
          summary="Straight segments take a length and an incline (uphill positive). "
                  "Bends take an angle and a radius."),
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
            hint="optional, sizes the grounding conductor")),
        C("motors.vfd_cable_guide", "Drive cable guide", F("voltage", "Voltage", unit="V")),
    )),
    Page("Transformers", (
        C("transformer.protection", "Transformer overcurrent protection (Table 450.3(B))",
          F("kva", "Rating", unit="kVA"),
          F("phases", "Phases", CHOICE, choices=("1", "3")),
          F("primary_voltage", "Primary voltage", unit="V"),
          F("secondary_voltage", "Secondary voltage", unit="V"),
          F("method", "Protection", CHOICE, choices=_transformer_choices("METHODS"),
            hint="primary only, or primary and secondary"),
          F("primary_device", "Primary device", CHOICE,
            choices=_transformer_choices("DEVICES"),
            hint="adjustable is a setting, which Note 1 does not raise"),
          F("secondary_device", "Secondary device", CHOICE,
            choices=_transformer_choices("DEVICES")),
          F("thermal_protection", "Coordinated thermal overload protection", CHOICE,
            choices=YES_NO, hint="blank: not stated, so Note 3 is not applied"),
          F("impedance_pct", "Impedance", unit="%", hint="with thermal protection, for Note 3"),
          summary="The rated currents, and the largest primary and secondary devices for a "
                  "transformer of 1000 V or less, with Notes 1 to 3.",
          runner=_runner("transformer_protection"),
          covers=("transformer.rated_current", "transformer.max_primary",
                  "transformer.max_secondary")),
    )),
    Page("Panel", (
        C("panel.load_schedule", "Panel load schedule",
          F("supply_voltage", "Supply voltage", unit="V"),
          F("supply_phases", "Supply phases", CHOICE, choices=("1", "3")),
          F("supply_ocpd_device", "Supply overcurrent device", CHOICE,
            choices=_panel_choices("SUPPLY_DEVICES")),
          F("hundred_percent_rated", "Listed for 100% operation", CHOICE, choices=YES_NO,
            hint="blank: no"),
          F("load_side_ampacity_a", "Load-side ampacity, UL 508A 32.3.1(b)", unit="A",
            hint="optional"),
          F("loads", "Loads", TABLE, columns=LOAD_COLUMNS),
          summary="The full-load current, the supply conductor, and the largest and smallest "
                  "supply device, under the NEC and UL 508A, with each load and branch.",
          runner=_runner("load_schedule"),
          covers=("panel.schedule", "panel.full_load_current", "panel.supply_conductor_ampacity",
                  "panel.max_supply_ocpd", "panel.min_supply_ocpd", "panel.load_current",
                  "panel.branch_check")),
        C("sccr.panel_rating", "Panel SCCR",
          F("system_voltage_v", "System voltage", unit="V"),
          F("available_fault_ka", "Available fault current", unit="kA", hint="optional"),
          F("required_sccr_ka", "Required SCCR", unit="kA", hint="optional"),
          F("components", "Power circuit components", TABLE, columns=COMPONENT_COLUMNS),
          summary="UL 508A's basic method: each circuit takes its lowest-rated component, "
                  "and the panel its lowest circuit.",
          runner=_runner("panel_rating"),
          covers=("sccr.panel_sccr", "sccr.panel_sccr_ceiling", "sccr.compare", "sccr.circuit_sccr",
                  "sccr.component_rating")),
        C("heat.enclosure_heat", "Enclosure heat and cooling",
          F("components", "Parts that give off heat", TABLE, columns=HEAT_COLUMNS),
          F("margin_pct", "Safety margin", unit="%", hint="0 for none"),
          F("height_in", "Height", unit="in"), F("width_in", "Width", unit="in"),
          F("depth_in", "Depth", unit="in"),
          F("sealed", "Sealed", CHOICE, choices=YES_NO), F("indoor", "Indoors", CHOICE, choices=YES_NO),
          F("insulated", "Insulated", CHOICE, choices=YES_NO),
          F("unit", "Temperature unit", CHOICE, choices=("C", "F")),
          F("outside_max", "Highest outside"), F("inside_max", "Highest wanted inside"),
          F("rated_btu_hr", "Selected cooling, rated", unit="BTU/hr", hint="optional"),
          summary="Hoffman's method: watts plus the walls' share, for a sealed indoor "
                  "enclosure.",
          runner=_runner("enclosure_heat"),
          covers=("heat.heat_load", "heat.heat_load_floor", "heat.surface_area",
                  "heat.required_cooling", "heat.temperature_rise", "heat.cooling_check")),
    )),
    Page("Power", (
        C("power.convert", "Power conversion",
          SYSTEM, F("voltage", "Voltage", unit="V"),
          F("known", "Known quantity", CHOICE, choices=("amps", "kw", "kva", "hp")),
          F("value", "Value"), F("power_factor", "Power factor", hint="0 to 1, blank for DC"),
          F("efficiency", "Efficiency", hint="0 to 1, needed for horsepower")),
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

#: The ``pydrc.calc`` modules that hold no calculator, and why. Every other
#: module's public functions are held to the pages, so a module PyDRC adds is
#: described or named here, or tests/test_calculators.py fails.
NOT_CALCULATORS = {
    "result": "the result every calculator returns",
    "tables": "reads the code tables the calculators look up",
}

#: Public PyDRC functions that are not calculators: they list or spell things.
#: A function that appears in PyDRC and on no page, in no page's ``covers`` and
#: not here fails tests/test_calculators.py.
HELPERS = {
    "conductors.sizes", "conductors.normalize_size", "conductors.size_label",
    "conductors.standard_ratings", "raceway.raceways", "raceway.trade_sizes",
    "motors.horsepower", "motors.motor_types", "estimating.defaults",
    "sccr.kinds", "sccr.sb41_supplied",
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
        if f.kind == TABLE:
            kwargs[f.name] = table_rows(value)
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


def table_rows(value) -> list:
    """A TABLE field's rows as dicts of the cells that hold something; a row
    with nothing in it is left out, so an empty row added by mistake is not a
    blank entry."""
    rows = []
    for row in value or ():
        cells = {k: str(v).strip() for k, v in (row or {}).items()
                 if v is not None and str(v).strip()}
        if cells:
            rows.append(cells)
    return rows


def run(calc: Calculator, raw: dict) -> list:
    """``[(heading, Result)]``: one section for a single function, several for a
    page that runs more than one."""
    if calc.runner is not None:
        return calc.runner(raw)
    return [("", call(calc, raw))]
