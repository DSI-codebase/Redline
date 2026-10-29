"""The Calculators tab: PyDRC's calculators, described once, run as the library runs them.

The descriptions in ``app/calculators/specs.py`` are held to the library they
describe, never to a copy: every field is a parameter of its function, every
required parameter has a field, and every public calculator PyDRC has is either
on a page or named, with the reason, as coming later or as a helper. The panel
is then driven the way a person would drive it.

Anything that runs a calculator needs PyDRC and skips without it; the panel
tests need Qt as well. What degrades without PyDRC always runs.
"""

import builtins
import importlib
import inspect
import os
import unittest

from app import audit
from app.calculators import render, specs
from tests._qt import QT_OK, REASON as QT_REASON

HAVE_PYDRC = audit.available()
needs_pydrc = unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")

#: The PyDRC modules whose public functions must each be accounted for.
MODULES = ("conductors", "raceway", "motors", "power", "estimating", "panel", "sccr", "heat")


def _public_functions():
    out = set()
    for m in MODULES:
        mod = importlib.import_module("pydrc.calc." + m)
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ == mod.__name__ and not name.startswith("_"):
                out.add(f"{m}.{name}")
    return out


def _accounted(name):
    return (specs.find(name) is not None or name in specs.HELPERS
            or any(name in c.covers for c in specs.all_calculators()))


def _single():
    """The calculators that are one PyDRC function, not a page that runs several."""
    return [c for c in specs.all_calculators() if c.runner is None]


def _all_fields(calc):
    for f in calc.fields:
        yield f
        yield from f.columns


VOLTAGE_DROP = {"size": "12", "current_a": "20", "length_ft": "100", "voltage": "240",
                "system": "1ph", "installation": "pvc", "power_factor": "1"}


@needs_pydrc
class TestTheDescriptionsMatchTheLibrary(unittest.TestCase):
    def test_every_field_is_a_parameter_and_every_required_parameter_a_field(self):
        """Injected: the field current_a renamed amps in a scratch description
        (red: not a parameter of conductors.voltage_drop)."""
        calcs = _single()
        self.assertGreaterEqual(len(calcs), 36)
        for calc in calcs:
            fn = calc.function()
            self.assertIsNotNone(fn, calc.id)
            params = inspect.signature(fn).parameters
            takes_any = any(p.kind is p.VAR_KEYWORD for p in params.values())
            names = [f.name for f in calc.fields]
            self.assertEqual(len(names), len(set(names)), calc.id)
            for n in names:
                self.assertTrue(n in params or takes_any, f"{calc.id}: {n} is not a parameter")
            required = [n for n, p in params.items()
                        if p.default is p.empty and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]
            for n in required:
                self.assertIn(n, names, f"{calc.id}: required {n} has no field")

    def test_every_public_calculator_is_on_a_page_or_named_with_its_reason(self):
        """Both directions: what PyDRC has is accounted for, and what the lists
        name exists. Every public function of the eight modules is on a page,
        run by a page (``covers``) or a helper. Injected: conductors.metal_weight's
        description removed (red: unaccounted); a HELPERS entry misspelled (red:
        names nothing); heat.temperature_rise dropped from its page's covers (red)."""
        found = _public_functions()
        self.assertGreaterEqual(len(found), 50)
        unaccounted = sorted(n for n in found if not _accounted(n))
        self.assertEqual(unaccounted, [], "a PyDRC calculator with no page and no reason")
        covered = [n for c in specs.all_calculators() for n in c.covers]
        for name in list(specs.HELPERS) + covered:
            self.assertIn(name, found, f"{name} names nothing in PyDRC")
        for calc in _single():
            self.assertIn(calc.id, found)
        self.assertGreaterEqual(len(covered), 18)

    def test_every_list_of_choices_comes_from_the_library_and_is_not_empty(self):
        checked = 0
        for calc in specs.all_calculators():
            for f in _all_fields(calc):
                if f.kind == specs.CHOICE:
                    self.assertTrue(f.options(), f"{calc.id}.{f.name}")
                    checked += 1
        self.assertGreaterEqual(checked, 55)
        from pydrc.calc import conductors
        self.assertEqual(specs.find("conductors.voltage_drop").fields[0].options(),
                         conductors.sizes())


@needs_pydrc
class TestRunning(unittest.TestCase):
    def test_a_result_is_the_library_s_with_its_arithmetic_and_its_tables(self):
        calc = specs.find("conductors.voltage_drop")
        r = specs.call(calc, VOLTAGE_DROP)
        self.assertEqual(r["voltage_drop_v"], 8.0)      # 2 x 20 A x 100 ft x 2.0 ohm/kft / 1000
        lines = render.result_lines(r)
        self.assertEqual(lines[0], render.TIERS["code"])
        self.assertIn("  voltage drop (V): 8", lines)
        self.assertIn("HOW", lines)
        self.assertIn("  NEC 2026 Chapter 9, Table 9: NEC 2023 values, not yet confirmed "
                      "against 2026.", lines)
        self.assertEqual(lines[-1], render.ADVISORY)

    def test_a_blank_the_library_has_a_default_for_takes_it_and_says_so(self):
        """Material is left blank here: PyDRC's default, copper, applies, and the
        arithmetic names it. Injected: call() passing every blank as None (red:
        PyDRC refused the blank parallel sets and material it has defaults for)."""
        r = specs.call(specs.find("conductors.voltage_drop"), VOLTAGE_DROP)
        self.assertTrue(r.computed, r.reasons)
        self.assertIn("12 AWG copper", r.steps[0])
        self.assertEqual(r["parallel_sets"], 1)

    def test_any_other_blank_is_reported_missing_never_filled(self):
        raw = dict(VOLTAGE_DROP, power_factor="", installation="")
        r = specs.call(specs.find("conductors.voltage_drop"), raw)
        self.assertFalse(r.computed)
        lines = render.result_lines(r)
        self.assertIn("NOT COMPUTED, because:", lines)
        self.assertIn("  - missing power factor", lines)
        self.assertNotIn("RESULT", lines)

    def test_every_calculator_answers_an_empty_form_with_reasons_not_a_crash(self):
        """An empty form is the first thing every page sees: a calculator with a
        required input answers it with reasons, and none raises."""
        refused = 0
        for calc in specs.all_calculators():
            if calc.runner is not None:
                sections = specs.run(calc, {})
                self.assertTrue(sections and not any(r.computed for _h, r in sections), calc.id)
                refused += 1
                continue
            params = inspect.signature(calc.function()).parameters
            required = any(p.default is p.empty and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
                           for p in params.values())
            r = specs.call(calc, {})
            if required or any(p.kind is p.VAR_KEYWORD for p in params.values()):
                self.assertFalse(r.computed, calc.id)
                self.assertTrue(r.reasons, calc.id)
                refused += 1
        self.assertGreaterEqual(refused, 35)

    def test_copy_holds_the_inputs_blanks_included_and_the_whole_result(self):
        calc = specs.find("conductors.voltage_drop")
        r = specs.call(calc, VOLTAGE_DROP)
        text = render.copy_text(calc, VOLTAGE_DROP, r, "0.14.0")
        self.assertTrue(text.startswith("Voltage drop (PyDRC 0.14.0, conductors.voltage_drop)"))
        self.assertIn("  Current: 20 A\n", text)
        self.assertIn("  Material: (blank)\n", text)
        self.assertIn("RESULT", text)
        self.assertIn(render.ADVISORY, text)

    def test_an_estimate_says_it_never_feeds_a_finding(self):
        r = specs.call(specs.find("power.convert"), {"system": "dc", "voltage": "125",
                                                     "known": "amps", "value": "40"})
        self.assertEqual(render.result_lines(r)[0], render.TIERS["method"])
        r = specs.call(specs.find("motors.vfd_cable_guide"), {"voltage": "480"})
        self.assertIn("never feeds a design rule finding", render.result_lines(r)[0])

    def test_a_calculator_this_pydrc_lacks_names_the_version(self):
        ghost = specs.Calculator("conductors.no_such_calculator", "Ghost", ())
        with self.assertRaises(specs.Missing) as cm:
            specs.call(ghost, {})
        self.assertIn("has no conductors.no_such_calculator", str(cm.exception))


#: A 10 hp motor at 480 V on a 30 A breaker, fed through a breaker.
SCHEDULE = {"supply_voltage": "480", "supply_phases": "3",
            "supply_ocpd_device": "inverse_time_breaker",
            "loads": [{"tag": "M1", "kind": "motor_table", "connection": "3PH", "voltage": "480",
                       "hp": "10", "motor_type": "squirrel_cage",
                       "branch_device": "inverse_time_breaker", "branch_rating_a": "30"},
                      {}]}
#: A 10 kA contactor on a branch and a 65 kA feeder breaker, against 22 kA.
SCCR = {"system_voltage_v": "480", "available_fault_ka": "22",
        "components": [{"tag": "K1", "kind": "contactor", "circuit": "M1", "sccr_ka": "10",
                        "voltage_v": "480", "rating_source": "label"},
                       {"tag": "CB1", "kind": "molded_case_circuit_breaker", "circuit": "feeder",
                        "sccr_ka": "65", "voltage_v": "480", "rating_source": "label"}]}
#: 500 W in a sealed indoor 48 x 36 x 12 in enclosure, 40 C outside, 35 C wanted inside.
HEAT = {"components": [{"tag": "VFD1", "quantity": "1", "watts_each": "500",
                        "source": "datasheet", "verified": "yes"}],
        "margin_pct": "0", "height_in": "48", "width_in": "36", "depth_in": "12",
        "sealed": "yes", "indoor": "yes", "insulated": "no", "unit": "C",
        "outside_max": "40", "inside_max": "35", "rated_btu_hr": "2500"}


def _sections(calc_id, raw):
    return dict(specs.run(specs.find(calc_id), raw))


@needs_pydrc
class TestTheListPages(unittest.TestCase):
    """A table's cells are text, and a row left empty is not an entry. Every
    expected figure here was worked by hand, not read back from PyDRC."""

    def test_a_table_is_passed_to_the_library_as_its_own_rows(self):
        """The form's text cells, with an empty row added by mistake, give what
        a direct call with numbers gives. Injected: table_rows keeping empty
        rows (red: conduit fill refused conductor 2, the empty row, as having
        no quantity)."""
        from pydrc.calc import raceway
        fill = specs.call(specs.find("raceway.conduit_fill"), {
            "raceway": "emt", "nipple": False,
            "conductor_list": [{"qty": "3", "wire_type": "THHN", "size": "4/0", "od_in": "",
                                "label": ""}, {"qty": "", "wire_type": "", "size": ""}]})
        self.assertTrue(fill.computed, fill.reasons)
        self.assertEqual(dict(fill.values),
                         dict(raceway.conduit_fill("emt", [{"qty": 3, "wire_type": "THHN",
                                                            "size": "4/0"}]).values))
        self.assertEqual(fill["minimum_trade_size"], "2")
        segments = [{"type": "straight", "length_ft": 200, "incline_deg": 0},
                    {"type": "bend", "angle_deg": 90, "radius_ft": 3},
                    {"type": "straight", "length_ft": 100, "incline_deg": 0}]
        pull = specs.call(specs.find("raceway.cable_pull"), {
            "raceway_id_in": "4.026", "cable_count": "3", "cable_od_in": "1.2",
            "cable_weight_lb_per_ft": "1.5", "friction": "0.35",
            "segments": [{k: str(v) for k, v in seg.items()} for seg in segments] + [{}]})
        self.assertTrue(pull.computed, pull.reasons)
        self.assertEqual(dict(pull.values),
                         dict(raceway.cable_pull(4.026, 3, 1.2, 1.5, segments, 0.35).values))

    def test_the_load_schedule_by_hand(self):
        """Table 430.250 gives 14 A for 10 hp in the 460 V column, and the
        supply conductor carries 125% of the largest motor: 17.5 A."""
        s = _sections("panel.load_schedule", SCHEDULE)
        self.assertEqual(s["Panel full-load current"]["flc_a"], 14.0)
        self.assertEqual(s["Supply conductor ampacity, NEC"]["ampacity_a"], 17.5)
        self.assertEqual(s["Supply conductor ampacity, UL 508A"]["ampacity_a"], 17.5)
        self.assertEqual(s["Load M1"]["current_a"], 14)
        self.assertIn("Branch M1", s)
        self.assertEqual(len(s), 8, list(s))

    def test_the_panel_sccr_by_hand(self):
        """The panel takes its lowest circuit, M1 at 10 kA, which is 12 kA short
        of the 22 kA available. Each power circuit has its own section."""
        s = _sections("sccr.panel_rating", SCCR)
        self.assertEqual(s["Panel SCCR"]["sccr_ka"], 10.0)
        self.assertEqual(s["Panel SCCR"]["limiting_component"], "K1")
        self.assertEqual(s["Against the target"]["verdict"], "falls_short")
        self.assertEqual(s["Against the target"]["short_circuits"][0]["shortfall_ka"], 12.0)
        self.assertEqual(s["Circuit M1"]["sccr_ka"], 10.0)
        self.assertEqual(s["Circuit feeder"]["sccr_ka"], 65.0)

    def test_the_enclosure_heat_by_hand(self):
        """2(48x36 + 48x12 + 36x12)/144 = 38 ft2. 500 W x 3.413 = 1706.5 BTU/hr,
        and the walls add 1.25 x 38 x 9 F = 427.5: 2134 BTU/hr, under the 2500
        rated."""
        s = _sections("heat.enclosure_heat", HEAT)
        self.assertEqual(s["Surface area"]["area_ft2"], 38.0)
        self.assertEqual(s["Cooling required"]["required_btu_hr"], 2134.0)
        self.assertTrue(s["Against the selected cooling"].computed)
        self.assertNotIn("Heat load, the rated parts alone", s)

    def test_a_part_with_no_watts_makes_the_load_a_floor_and_says_so(self):
        raw = dict(HEAT, components=HEAT["components"] + [{"tag": "PS1"}])
        s = _sections("heat.enclosure_heat", raw)
        self.assertFalse(s["Heat load"].computed)
        self.assertIn("PS1: missing watts", s["Heat load"].reasons)
        self.assertEqual(s["Heat load, the rated parts alone"]["total_w"], 500.0)
        self.assertIn("Cooling required, at least", s)
        self.assertFalse(s["Against the selected cooling"].computed)

    def test_a_cell_that_is_not_a_number_is_named_by_its_row(self):
        """Injected: _Build.number returning None for text it cannot read
        without a problem (red: the schedule ran with the volts missing)."""
        rows = [dict(SCHEDULE["loads"][0], voltage="four-eighty")]
        sections = specs.run(specs.find("panel.load_schedule"), dict(SCHEDULE, loads=rows))
        self.assertEqual(len(sections), 1)
        self.assertFalse(sections[0][1].computed)
        self.assertIn("load 1, volts: 'four-eighty' is not a number", sections[0][1].reasons)

    def test_a_yes_or_no_left_blank_is_asked_for_unless_the_library_states_a_default(self):
        """The enclosure's three answers have no default. A load running with
        the others and a supply device not 100% rated are PyDRC's stated
        defaults. Injected: yes_no(default=False) for sealed (red: no problem)."""
        sections = specs.run(specs.find("heat.enclosure_heat"),
                             dict(HEAT, sealed="", insulated="maybe"))
        reasons = sections[0][1].reasons
        self.assertEqual(len(sections), 1)
        self.assertIn("missing whether the enclosure is sealed (yes or no)", reasons)
        self.assertIn("whether it is insulated: 'maybe' is neither yes nor no", reasons)
        blank = _sections("panel.load_schedule", SCHEDULE)
        said = _sections("panel.load_schedule",
                         dict(SCHEDULE, hundred_percent_rated="no",
                              loads=[dict(SCHEDULE["loads"][0], simultaneous="yes")]))
        self.assertEqual({h: dict(r.values) for h, r in blank.items()},
                         {h: dict(r.values) for h, r in said.items()})

    def test_a_list_with_no_rows_or_a_row_with_no_circuit_is_refused(self):
        r = specs.run(specs.find("panel.load_schedule"), dict(SCHEDULE, loads=[{}]))[0][1]
        self.assertIn("no loads: add a row for each load the supply feeds", r.reasons)
        rows = [dict(SCCR["components"][0], circuit="")]
        r = specs.run(specs.find("sccr.panel_rating"), dict(SCCR, components=rows))[0][1]
        self.assertIn("missing component 1's circuit: feeder, or its branch circuit", r.reasons)

    def test_copy_holds_each_row_and_every_section_with_the_advisory_once(self):
        calc = specs.find("sccr.panel_rating")
        text = render.copy_text(calc, SCCR, specs.run(calc, SCCR), "0.14.0")
        self.assertIn("  Power circuit components: 2 rows\n", text)
        self.assertIn("    1. Tag K1, Kind contactor, Circuit M1, Marked SCCR 10 kA, At 480 V, "
                      "Source label\n", text)
        self.assertIn("== Panel SCCR ==\n", text)
        self.assertIn("== Circuit feeder ==\n", text)
        self.assertEqual(text.count(render.ADVISORY), 1)


class TestWithoutTheLibrary(unittest.TestCase):
    def test_status_reports_unavailable_with_the_install_instructions(self):
        from app import calculators
        real = builtins.__import__

        def blocked(name, *a, **kw):
            if name.startswith("pydrc"):
                raise ImportError("simulated: pydrc not installed")
            return real(name, *a, **kw)

        builtins.__import__ = blocked
        try:
            ok, message = calculators.status()
        finally:
            builtins.__import__ = real
        self.assertFalse(ok)
        self.assertIn("pip install -r requirements-drc.txt", message)

    def test_the_manual_names_every_page(self):
        with open(os.path.join(os.path.dirname(__file__), os.pardir, "docs",
                               "Calculators.md"), encoding="utf-8") as fh:
            manual = fh.read()
        for page in specs.PAGES:
            self.assertIn(f"**{page.title}**", manual, page.title)
        words = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
        self.assertIn(f"grouped on {words[len(specs.PAGES)]} pages", manual)

    def test_what_the_tab_shows_carries_no_semicolon_or_dash(self):
        """The house's rule for text a reader is handed: every title, summary,
        label, unit and hint, and the result's fixed lines. Injected: one hint
        back to "three cables; blank lets the method choose" (red)."""
        shown = list(render.TIERS.values()) + [render.ADVISORY]
        for calc in specs.all_calculators():
            shown += [calc.title, calc.summary]
            for f in _all_fields(calc):
                shown += [f.label, f.unit, f.hint]
        self.assertGreaterEqual(len(shown), 400)
        for text in shown:
            for mark in (";", "\u2014", "\u2013", " - "):
                self.assertNotIn(mark, text)

    def test_each_module_imports_first_in_a_fresh_interpreter(self):
        """``lists`` imports ``specs``, and ``specs`` runs ``lists``' builders,
        so the order the two load in is a cycle waiting to happen. Every test
        here imports ``specs`` first. Injected: specs reading a builder from
        lists while it loads (red: lists first, partially initialized)."""
        import subprocess
        import sys
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
        mods = ("app.calculators", "app.calculators.specs", "app.calculators.lists",
                "app.calculators.render")
        for mod in mods:
            r = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=root,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"import {mod} alone: {r.stderr[-400:]}")

    def test_the_descriptions_load_without_the_library(self):
        self.assertGreaterEqual(len(specs.all_calculators()), 39)
        self.assertEqual([p.title for p in specs.PAGES],
                         ["Conductors", "Voltage drop", "Raceway", "Motors", "Panel", "Power",
                          "Estimating"])


@unittest.skipUnless(QT_OK, QT_REASON)
@needs_pydrc
class TestThePanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from app.panels.calculator_panel import CalculatorPanel
        return CalculatorPanel()

    def test_every_calculator_has_its_entry_and_a_form_of_its_fields(self):
        p = self._panel()
        items = [p.tree.topLevelItem(i).child(j) for i in range(p.tree.topLevelItemCount())
                 for j in range(p.tree.topLevelItem(i).childCount())]
        self.assertEqual(len(items), len(specs.all_calculators()))
        for calc in specs.all_calculators():
            p.show_calculator(calc)
            self.assertEqual(p.form.rowCount(), len(calc.fields), calc.id)

    def test_calculate_shows_the_result_and_copy_puts_it_on_the_clipboard(self):
        from PySide6.QtWidgets import QApplication
        p = self._panel()
        p.show_calculator(specs.find("conductors.voltage_drop"))
        self.assertFalse(p.btn_copy.isEnabled())
        for k, v in VOLTAGE_DROP.items():
            p.set_field(k, v)
        p.calculate()
        self.assertIn("  voltage drop (V): 8", p.output.toPlainText())
        self.assertTrue(p.btn_copy.isEnabled())
        p.copy()
        self.assertIn("INPUTS", QApplication.clipboard().text())
        self.assertIn("  voltage drop (V): 8", QApplication.clipboard().text())

    def test_what_is_typed_survives_a_page_change_and_not_a_new_panel(self):
        """Injected: show_calculator skipping _remember (red: the current was lost)."""
        p = self._panel()
        vd, amp = specs.find("conductors.voltage_drop"), specs.find("conductors.ampacity")
        p.show_calculator(vd)
        p.set_field("current_a", "42")
        p.show_calculator(amp)
        p.show_calculator(vd)
        self.assertEqual(p.form_values()["current_a"], "42")
        fresh = self._panel()
        fresh.show_calculator(vd)
        self.assertEqual(fresh.form_values()["current_a"], "")

    def test_an_empty_form_shows_reasons_in_place_of_a_result(self):
        p = self._panel()
        p.show_calculator(specs.find("conductors.voltage_drop"))
        p.calculate()
        self.assertIn("NOT COMPUTED, because:", p.output.toPlainText())

    def test_without_the_library_the_tab_says_so_and_offers_nothing(self):
        from unittest import mock
        import app.panels.calculator_panel as cp
        with mock.patch.object(cp, "status", return_value=(False, "PyDRC is not installed here.")):
            p = self._panel()
        self.assertFalse(p.split.isEnabled())
        self.assertIn("The calculators are unavailable", p.status_label.text())
        self.assertIn("PyDRC is not installed here.", p.status_label.text())

    def test_a_list_page_takes_rows_and_shows_every_section(self):
        """Add row gives an empty row, which is not an entry; Remove row takes
        the last when none is selected."""
        from app.panels.calculator_panel import _TableField
        p = self._panel()
        p.show_calculator(specs.find("heat.enclosure_heat"))
        table = p._widgets["components"]
        self.assertIsInstance(table, _TableField)
        self.assertEqual(table.table.rowCount(), 1)
        for k, v in HEAT.items():
            p.set_field(k, v)
        table.btn_add.click()
        self.assertEqual(table.table.rowCount(), 2)
        p.calculate()
        text = p.output.toPlainText()
        self.assertIn("== Cooling required ==", text)
        self.assertIn("  required (BTU/hr): 2134", text)
        self.assertIn("  area (ft2): 38", text)
        self.assertEqual(text.count(render.ADVISORY), 1)
        table.btn_remove.click()
        self.assertEqual(table.rows()[0]["watts_each"], "500")
        self.assertEqual(table.table.rowCount(), 1)

    def test_rows_survive_a_page_change_and_clear_leaves_one_empty_row(self):
        """Injected: _TableField.rows() reading only the text cells (red: the
        choice column's yes was lost)."""
        p = self._panel()
        heat, vd = specs.find("heat.enclosure_heat"), specs.find("conductors.voltage_drop")
        p.show_calculator(heat)
        p.set_field("components", HEAT["components"])
        p.show_calculator(vd)
        p.show_calculator(heat)
        rows = specs.table_rows(p.form_values()["components"])
        self.assertEqual(rows, HEAT["components"])
        p.clear()
        self.assertEqual(p._widgets["components"].table.rowCount(), 1)
        self.assertEqual(specs.table_rows(p.form_values()["components"]), [])

    def test_the_tab_sits_with_the_main_panes(self):
        from app.main_window import MainWindow, _UI_STATE_VERSION
        win = MainWindow()
        dock = win.tabs.dock_for(win.calculator_panel)
        self.assertEqual(dock.objectName(), "CalculatorsDock")
        self.assertEqual(dock.windowTitle(), "Calculators")
        win.restoreState(win._default_state, _UI_STATE_VERSION)
        self.assertIn(dock, win.tabifiedDockWidgets(win.tabs.dock_for(win.view)))
        self.assertIn(dock, win.main_docks)


if __name__ == "__main__":
    unittest.main()
