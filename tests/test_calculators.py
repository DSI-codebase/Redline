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
    module = name.split(".")[0]
    return (specs.find(name) is not None or name in specs.HELPERS
            or name in specs.LATER or f"{module}.*" in specs.LATER)


VOLTAGE_DROP = {"size": "12", "current_a": "20", "length_ft": "100", "voltage": "240",
                "system": "1ph", "installation": "pvc", "power_factor": "1"}


@needs_pydrc
class TestTheDescriptionsMatchTheLibrary(unittest.TestCase):
    def test_every_field_is_a_parameter_and_every_required_parameter_a_field(self):
        """Injected: the field current_a renamed amps in a scratch description
        (red: not a parameter of conductors.voltage_drop)."""
        calcs = specs.all_calculators()
        self.assertGreaterEqual(len(calcs), 30)
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
        name exists. Injected: conductors.metal_weight's description removed
        (red: unaccounted); a HELPERS entry misspelled (red: names nothing)."""
        found = _public_functions()
        self.assertGreaterEqual(len(found), 50)
        unaccounted = sorted(n for n in found if not _accounted(n))
        self.assertEqual(unaccounted, [], "a PyDRC calculator with no page and no reason")
        for name in list(specs.HELPERS) + [n for n in specs.LATER if not n.endswith(".*")]:
            self.assertIn(name, found, f"{name} names nothing in PyDRC")
        for calc in specs.all_calculators():
            self.assertIn(calc.id, found)
        for wildcard in (n for n in specs.LATER if n.endswith(".*")):
            module = wildcard[:-2]
            self.assertTrue(any(n.startswith(module + ".") for n in found), wildcard)

    def test_every_list_of_choices_comes_from_the_library_and_is_not_empty(self):
        checked = 0
        for calc in specs.all_calculators():
            for f in calc.fields:
                if f.kind == specs.CHOICE:
                    self.assertTrue(f.options(), f"{calc.id}.{f.name}")
                    checked += 1
        self.assertGreaterEqual(checked, 40)
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
            params = inspect.signature(calc.function()).parameters
            required = any(p.default is p.empty and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
                           for p in params.values())
            r = specs.call(calc, {})
            if required or any(p.kind is p.VAR_KEYWORD for p in params.values()):
                self.assertFalse(r.computed, calc.id)
                self.assertTrue(r.reasons, calc.id)
                refused += 1
        self.assertGreaterEqual(refused, 30)

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
        manual = open(os.path.join(os.path.dirname(__file__), os.pardir, "docs",
                                   "Calculators.md"), encoding="utf-8").read()
        for page in specs.PAGES:
            self.assertIn(f"**{page.title}**", manual, page.title)
        words = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
        self.assertIn(f"grouped on {words[len(specs.PAGES)]} pages", manual)

    def test_the_descriptions_load_without_the_library(self):
        self.assertGreaterEqual(len(specs.all_calculators()), 30)
        self.assertEqual([p.title for p in specs.PAGES],
                         ["Conductors", "Voltage drop", "Raceway", "Motors", "Power", "Estimating"])


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
