"""Tests for component-label parsing, classification, and export."""

import os
import tempfile
import unittest

from app.extraction.wire_parser import Token, SOURCE_TEXT, SOURCE_AI
from app.extraction.component_parser import (
    ComponentConfig, ComponentParser, parse_component_label, build_component_label,
    dedupe, numerical_order, TYPE_CONFORMING, TYPE_NONCONFORMING,
    FLAG_UNKNOWN_FAMILY,
)
from app.export import component_export as cex


CFG = ComponentConfig(sheet_width=3, rung_width=2, families=("LT", "CR", "PB"))


def _tok(text, source=SOURCE_TEXT, page=0, x=0.0, y=0.0):
    return Token(text=text, x=x, y=y, page=page, source=source)


class TestComponentParse(unittest.TestCase):
    def test_parse_conforming(self):
        self.assertEqual(parse_component_label("LT-10010", CFG), ("LT", "10010", 100, 10))
        self.assertEqual(parse_component_label("CR-30024", CFG), ("CR", "30024", 300, 24))

    def test_parse_separators(self):
        self.assertEqual(parse_component_label("LT 10010", CFG)[0], "LT")
        self.assertEqual(parse_component_label("LT10010", CFG), ("LT", "10010", 100, 10))

    def test_parse_nonconforming_length(self):
        fam, num, sheet, rung = parse_component_label("YC-301", CFG)
        self.assertEqual((fam, num), ("YC", "301"))
        self.assertIsNone(sheet)
        self.assertIsNone(rung)

    def test_parse_rejects_non_tag(self):
        self.assertIsNone(parse_component_label("HELLO", CFG))
        self.assertIsNone(parse_component_label("123456", CFG))

    def test_build_roundtrip(self):
        lbl = build_component_label("LT", 100, 10, CFG)
        self.assertEqual(lbl, "LT-10010")
        self.assertEqual(parse_component_label(lbl, CFG), ("LT", "10010", 100, 10))


class TestComponentClassify(unittest.TestCase):
    def setUp(self):
        self.p = ComponentParser(CFG)

    def test_known_family_conforming(self):
        out = self.p.parse([_tok("LT-10010")])
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual((c.family, c.sheet, c.rung), ("LT", 100, 10))
        self.assertEqual(c.comp_type, TYPE_CONFORMING)
        self.assertNotIn(FLAG_UNKNOWN_FAMILY, c.flags)

    def test_unknown_family_conforming_captured_and_flagged(self):
        # ZZ not in families, but the number is a conforming length -> captured
        out = self.p.parse([_tok("ZZ-30024")])
        self.assertEqual(len(out), 1)
        self.assertIn(FLAG_UNKNOWN_FAMILY, out[0].flags)
        self.assertEqual(out[0].comp_type, TYPE_CONFORMING)

    def test_unknown_family_nonconforming_dropped_for_text(self):
        # unknown family AND off-length -> noise, dropped from text layer
        out = self.p.parse([_tok("REV-2023")])
        self.assertEqual(out, [])

    def test_ai_source_always_accepted(self):
        # unknown family + off-length: dropped from the text layer, but accepted
        # when AI vision has already vetted it as a component
        self.assertEqual(self.p.parse([_tok("XY-300")]), [])
        out = self.p.parse([_tok("XY-300", source=SOURCE_AI)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].comp_type, TYPE_NONCONFORMING)
        self.assertIn(FLAG_UNKNOWN_FAMILY, out[0].flags)

    def test_known_family_nonconforming_length(self):
        out = self.p.parse([_tok("LT-301")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].comp_type, TYPE_NONCONFORMING)
        self.assertIsNone(out[0].sheet)

    def test_dedupe_counts(self):
        out = dedupe(self.p.parse([_tok("LT-10010"), _tok("LT-10010"), _tok("CR-30024")]))
        self.assertEqual(len(out), 2)
        lt = next(c for c in out if c.family == "LT")
        self.assertEqual(lt.count, 2)

    def test_numerical_order(self):
        items = self.p.parse([_tok("CR-30024"), _tok("LT-10010"), _tok("PB-10005")])
        ordered = numerical_order(items)
        self.assertEqual([c.label for c in ordered], ["PB-10005", "LT-10010", "CR-30024"])


class TestComponentExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.items = ComponentParser(CFG).parse(
            [_tok("LT-10010"), _tok("CR-30024"), _tok("PB-10005")])

    def test_single_file_full(self):
        out = os.path.join(self.tmp, "c.csv")
        opts = cex.ComponentExportOptions(fmt="csv", labels_only=False)
        cex.export_single_file(self.items, out, opts)
        with open(out) as fh:
            text = fh.read()
        self.assertIn("LT-10010", text)
        self.assertIn("Family", text)        # header present
        self.assertIn("~100~", text)         # sheet separator

    def test_single_file_labels_only_repeats(self):
        out = os.path.join(self.tmp, "c2.csv")
        opts = cex.ComponentExportOptions(fmt="csv", labels_only=True,
                                          labels_per_device=3)
        cex.export_single_file(self.items, out, opts)
        with open(out) as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
        self.assertEqual(sum(1 for l in lines if l == "LT-10010"), 3)

    def test_per_sheet(self):
        opts = cex.ComponentExportOptions(fmt="csv")
        paths = cex.export_per_sheet(self.items, os.path.join(self.tmp, "ps"), opts)
        names = sorted(os.path.basename(p) for p in paths)
        self.assertIn("COMPONENTS_100.csv", names)
        self.assertIn("COMPONENTS_300.csv", names)


class TestComponentSidecar(unittest.TestCase):
    def test_save_load_roundtrip(self):
        from app.model.storage import SidecarDB
        tmp = tempfile.mkdtemp()
        items = ComponentParser(CFG).parse([_tok("LT-10010"), _tok("ZZ-30024")])
        db = SidecarDB(os.path.join(tmp, "x.markup.db"))
        try:
            db.save_components(items)
            back = db.load_components()
        finally:
            db.close()
        self.assertEqual(len(back), 2)
        lt = next(c for c in back if c.family == "LT")
        self.assertEqual((lt.sheet, lt.rung, lt.comp_type), (100, 10, TYPE_CONFORMING))
        zz = next(c for c in back if c.family == "ZZ")
        self.assertIn(FLAG_UNKNOWN_FAMILY, zz.flags)


if __name__ == "__main__":
    unittest.main()
