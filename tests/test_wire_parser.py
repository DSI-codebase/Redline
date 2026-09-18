"""Tests for wire-number parsing / classification (the core differentiator)."""

import unittest

from app.extraction.wire_parser import (
    WireConfig, WireParser, Token, parse_label, build_label,
    dedupe, reading_order, numerical_order,
    TYPE_CONFORMING, TYPE_FIXED, TYPE_JUMPER, FLAG_SHEET_MISMATCH,
)


class TestEncoding(unittest.TestCase):
    def setUp(self):
        self.cfg = WireConfig()  # 3/2/1

    def test_worked_example(self):
        # 2nd wire on rung 14 of sheet 432 -> 432141 (index 1, 0-based)
        self.assertEqual(parse_label("432141", self.cfg), (432, 14, 1))
        # 1st wire on that rung -> 432140
        self.assertEqual(parse_label("432140", self.cfg), (432, 14, 0))

    def test_real_drawing_examples(self):
        self.assertEqual(parse_label("300350", self.cfg), (300, 35, 0))
        self.assertEqual(parse_label("300351", self.cfg), (300, 35, 1))
        self.assertEqual(parse_label("261201", self.cfg), (261, 20, 1))
        self.assertEqual(parse_label("261202", self.cfg), (261, 20, 2))

    def test_build_label_roundtrip(self):
        self.assertEqual(build_label(432, 14, 1, self.cfg), "432141")
        self.assertEqual(build_label(300, 5, 0, self.cfg), "300050")
        for label in ("432141", "300050", "609231"):
            s, r, w = parse_label(label, self.cfg)
            self.assertEqual(build_label(s, r, w, self.cfg), label)

    def test_rejects_wrong_width(self):
        self.assertIsNone(parse_label("30041", self.cfg))    # 5 digits
        self.assertIsNone(parse_label("3001234", self.cfg))  # 7 digits
        self.assertIsNone(parse_label("EL2503", self.cfg))   # non-numeric

    def test_configurable_widths(self):
        cfg = WireConfig(sheet_width=4, rung_width=3, wire_width=2)
        self.assertEqual(cfg.total_width, 9)
        self.assertEqual(parse_label("123456789", cfg), (1234, 567, 89))

    def test_no_zero_pad(self):
        cfg = WireConfig(zero_pad=False)
        self.assertEqual(build_label(300, 5, 0, cfg), "30050")


class TestClassification(unittest.TestCase):
    def test_conforming_via_pattern(self):
        parser = WireParser(WireConfig())
        toks = [Token("432141", 10, 20, page=0)]
        res = parser.parse(toks)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].wire_type, TYPE_CONFORMING)
        self.assertEqual((res[0].sheet, res[0].rung, res[0].wire_index), (432, 14, 1))

    def test_non_matching_ignored_without_layer(self):
        # a 5-digit cross-reference token is not a candidate without layer data
        parser = WireParser(WireConfig())
        res = parser.parse([Token("30041", 0, 0, page=0)])
        self.assertEqual(res, [])

    def test_fixed_on_wire_layer(self):
        parser = WireParser(WireConfig())
        toks = [Token("ABC12", 0, 0, page=0, layer="WIRENO")]
        res = parser.parse(toks)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].wire_type, TYPE_FIXED)

    def test_jumper_layer(self):
        parser = WireParser(WireConfig())
        toks = [Token("432141", 0, 0, page=0, layer="JUMPER_WIRES")]
        res = parser.parse(toks)
        self.assertEqual(res[0].wire_type, TYPE_JUMPER)

    def test_sheet_mismatch_flag(self):
        cfg = WireConfig(cross_check_sheet=True)
        parser = WireParser(cfg)
        # page sheet resolves to 300 (modal); 999141 mismatches
        toks = [Token("300050", 0, 0, page=0), Token("300120", 0, 1, page=0),
                Token("999141", 0, 2, page=0)]
        res = parser.parse(toks)
        odd = [w for w in res if w.label == "999141"][0]
        self.assertIn(FLAG_SHEET_MISMATCH, odd.flags)
        ok = [w for w in res if w.label == "300050"][0]
        self.assertNotIn(FLAG_SHEET_MISMATCH, ok.flags)

    def test_no_false_mismatch_by_default(self):
        # default cross_check_sheet=False -> never flag (multi-sheet pages)
        parser = WireParser(WireConfig())
        toks = [Token("300050", 0, 0, page=0), Token("301120", 0, 1, page=0)]
        res = parser.parse(toks)
        self.assertTrue(all(not w.flags for w in res))


class TestPostProcessing(unittest.TestCase):
    def test_dedupe_counts_and_collapses_pages(self):
        parser = WireParser(WireConfig())
        toks = [Token("300050", 0, 0, page=0), Token("300050", 5, 5, page=0),
                Token("300050", 0, 0, page=3)]  # same wire, two pages
        res = dedupe(parser.parse(toks))
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].count, 3)

    def test_numerical_order(self):
        parser = WireParser(WireConfig())
        labels = ["300351", "300050", "301120", "300120"]
        res = numerical_order(parser.parse([Token(l, 0, 0, page=0) for l in labels]))
        self.assertEqual([w.label for w in res], ["300050", "300120", "300351", "301120"])

    def test_reading_order_bands(self):
        parser = WireParser(WireConfig())
        # two rows; within a row, sort left-to-right
        toks = [
            Token("300120", x=200, y=100, page=0),
            Token("300130", x=50, y=102, page=0),   # same band as above
            Token("300140", x=50, y=300, page=0),   # lower band
        ]
        res = reading_order(parser.parse(toks), y_tol=6.0)
        self.assertEqual([w.label for w in res], ["300130", "300120", "300140"])


if __name__ == "__main__":
    unittest.main()
