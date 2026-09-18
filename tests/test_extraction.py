"""Tests for the scanned-page extraction path (AI vision + fallbacks)."""

import unittest

import fitz

import app.extraction.claude_api as capi
import app.extraction.text_extract as te
from app.extraction.wire_parser import (
    WireParser, WireConfig, dedupe, Token, SOURCE_AI, SOURCE_TEXT,
    TYPE_FIXED, TYPE_CONFORMING,
)


class TestAIExtraction(unittest.TestCase):
    def setUp(self):
        # a page with no text behaves like a scanned image
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=400)
        self._read = capi.read_wire_region
        self._avail = capi.available

    def tearDown(self):
        capi.read_wire_region = self._read
        capi.available = self._avail
        self.doc.close()

    def test_no_tokens_when_nothing_enabled(self):
        # reproduces the user's empty result on a scanned PDF
        self.assertEqual(te.collect_tokens(self.doc, ai_enabled=False, ocr_enabled=False), [])
        self.assertFalse(te.page_has_text(self.doc[0]))

    def test_ai_path_collects_and_classifies(self):
        capi.available = lambda key=None: True
        capi.read_wire_region = lambda pix, **k: [
            {"label": "11800", "is_wire": True, "confidence": 0.9, "bbox": [10, 20, 40, 30]},
            {"label": "432141", "is_wire": True, "confidence": 0.9, "bbox": [50, 20, 90, 30]},
            {"label": "CR12", "is_wire": False},  # device -> ignored
        ]
        toks = te.collect_tokens(self.doc, ai_enabled=True, ai_key="sk-x", ai_tiles=1)
        self.assertEqual({t.source for t in toks}, {SOURCE_AI})
        self.assertEqual(len(toks), 2)
        wires = dedupe(WireParser(WireConfig()).parse(toks))
        by_label = {w.label: w.wire_type for w in wires}
        self.assertEqual(by_label.get("11800"), TYPE_FIXED)       # non-standard kept
        self.assertEqual(by_label.get("432141"), TYPE_CONFORMING)

    def test_tiling_makes_n_squared_calls_and_maps_coords(self):
        capi.available = lambda key=None: True
        calls = []

        def fake(pix, **k):
            calls.append((pix.width, pix.height))
            return [{"label": "300050", "is_wire": True, "confidence": 0.9,
                     "bbox": [20, 15, 60, 35]}]
        capi.read_wire_region = fake

        page = self.doc[0]
        toks = te.ai_page(page, 0, tiles=2, api_key="sk", model="m")
        self.assertEqual(len(calls), 4)                    # 2x2 tiles
        # tokens land in distinct quadrants (page coords differ)
        xs = sorted({round(t.x) for t in toks})
        ys = sorted({round(t.y) for t in toks})
        self.assertEqual(len(xs), 2)
        self.assertEqual(len(ys), 2)
        # each tile renders at higher effective resolution than a single page call
        calls.clear()
        te.ai_page(page, 0, tiles=1, api_key="sk", model="m")
        self.assertEqual(len(calls), 1)

    def test_ai_token_is_candidate_regardless_of_format(self):
        p = WireParser(WireConfig())
        self.assertTrue(p.is_candidate(Token("11800", 0, 0, page=0, source=SOURCE_AI)))
        # the same 5-digit token from the text layer is NOT a candidate (6-digit rule)
        self.assertFalse(p.is_candidate(Token("11800", 0, 0, page=0, source=SOURCE_TEXT)))


if __name__ == "__main__":
    unittest.main()
