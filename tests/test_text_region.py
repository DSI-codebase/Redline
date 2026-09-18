"""Telling the drawing apart from the prose written on it.

A drafting note is English that happens to contain tag-shaped and wire-shaped
text. On a real plot one note block produced three false findings on its own.
But over-masking is the worse failure: hiding a real wire hides any finding
about it, and a false negative in a safety audit costs more than noise. Both
directions are tested here.
"""

import unittest

import fitz

from app.extraction.text_extract import extract_tokens
from app.extraction.wire_parser import Token
from app.extraction.text_region import (
    TextRegionConfig, classify_tokens, prose_token_ids,
    DRAWING, NOTES, INDEX, LEGEND, NON_DRAWING, FUNCTION_WORDS)
from app.extraction import sheet_role


NOTE = ("ALL WIRE SHALL BE TYPE MTW UNLESS OTHERWISE SPECIFIED AND EVERY WIRE "
        "SUCH AS 300140 MUST BE LABELED")
# An off-page connector row: real drawing content that reads a little like prose.
ARROW_ROW = "300150 to 70004 DRIVE POWER to 70006 N TB1"
# A PLC I/O list: a long, tightly spaced row of entirely real wire numbers.
IO_ROW = "600030   600070   600110   600150   600190   600230   600270"


def _page(lines):
    doc = fitz.open()
    page = doc.new_page(width=1224.0, height=792.0)
    for i, line in enumerate(lines):
        page.insert_text((60.0, 100.0 + i * 100.0), line, fontsize=8)
    return doc, page


def _roles(tokens, sheet_roles=None, config=None):
    return dict(zip((t.text for t in tokens),
                    classify_tokens(tokens, sheet_roles or {}, config)))


class TestProseDetection(unittest.TestCase):
    def test_masks_a_note_on_a_schematic_sheet(self):
        doc, page = _page([NOTE])
        tokens = extract_tokens(page, 0)
        got = _roles(tokens, {0: sheet_role.SCHEMATIC})
        self.assertEqual(got["300140"], NOTES)
        doc.close()

    def test_keeps_an_off_page_connector_row(self):
        # "to" labels a signal arrow here; it is not a preposition. Treating it
        # as prose masked a real wire.
        doc, page = _page([ARROW_ROW])
        tokens = extract_tokens(page, 0)
        got = _roles(tokens, {0: sheet_role.SCHEMATIC})
        self.assertEqual(got["300150"], DRAWING)
        doc.close()

    def test_keeps_a_plc_io_list(self):
        doc, page = _page([IO_ROW])
        tokens = extract_tokens(page, 0)
        got = _roles(tokens, {0: sheet_role.SCHEMATIC})
        for label in ("600030", "600110", "600270"):
            self.assertEqual(got[label], DRAWING, label)
        doc.close()

    def test_all_three_together(self):
        doc, page = _page([NOTE, ARROW_ROW, IO_ROW])
        tokens = extract_tokens(page, 0)
        got = _roles(tokens, {0: sheet_role.SCHEMATIC})
        self.assertEqual(got["300140"], NOTES)
        self.assertEqual(got["300150"], DRAWING)
        self.assertEqual(got["600110"], DRAWING)
        doc.close()

    def test_function_words_exclude_drawing_notation(self):
        # Each of these means something specific on a drawing.
        for word in ("TO", "FROM", "A", "N", "NO", "IN", "ON", "AT", "OR", "IS"):
            self.assertNotIn(word, FUNCTION_WORDS, word)

    def test_a_long_row_without_english_is_never_prose(self):
        tokens = [Token(text=f"6000{i}0", x=50.0 + i * 40.0, y=100.0, page=0, w=30.0)
                  for i in range(12)]
        self.assertEqual(prose_token_ids(tokens), set())

    def test_detection_can_be_switched_off(self):
        doc, page = _page([NOTE])
        tokens = extract_tokens(page, 0)
        got = _roles(tokens, {0: sheet_role.SCHEMATIC},
                     TextRegionConfig(enable_prose_runs=False))
        self.assertEqual(got["300140"], DRAWING)
        doc.close()


class TestSheetRoleRegions(unittest.TestCase):
    def test_everything_on_an_index_sheet_is_non_drawing(self):
        doc, page = _page([ARROW_ROW])
        tokens = extract_tokens(page, 0)
        got = _roles(tokens, {0: sheet_role.INDEX})
        self.assertEqual(got["300150"], INDEX)
        self.assertIn(INDEX, NON_DRAWING)
        doc.close()

    def test_legend_sheets_too(self):
        doc, page = _page([ARROW_ROW])
        tokens = extract_tokens(page, 0)
        self.assertEqual(_roles(tokens, {0: sheet_role.LEGEND})["300150"], LEGEND)
        doc.close()

    def test_schematic_sheets_are_drawing_by_default(self):
        doc, page = _page([ARROW_ROW])
        tokens = extract_tokens(page, 0)
        self.assertEqual(_roles(tokens, {0: sheet_role.SCHEMATIC})["300150"], DRAWING)
        doc.close()

    def test_terminal_detail_sheets_stay_drawing(self):
        # These are dense with real references; masking them wholesale would
        # hide findings rather than noise.
        doc, page = _page([IO_ROW])
        tokens = extract_tokens(page, 0)
        got = _roles(tokens, {0: sheet_role.TERMINAL_DETAIL})
        self.assertEqual(got["600110"], DRAWING)
        doc.close()


class TestTitleBlockMasking(unittest.TestCase):
    """Title-block text is metadata, not the drawing.

    An address's ZIP code parses exactly like a wire number once the
    variable-width numbering is on, and it appears on every sheet.
    """

    def _page(self):
        doc = fitz.open()
        page = doc.new_page(width=1224.0, height=792.0)
        page.insert_text((60.0, 400.0), "300140", fontsize=8)       # drawing
        page.insert_text((950.0, 730.0), "THOMASVILLE,NC, 27022", fontsize=6)
        return doc, page

    def test_masks_the_strip_when_page_sizes_are_known(self):
        from app.extraction.text_region import TITLEBLOCK
        doc, page = self._page()
        tokens = extract_tokens(page, 0)
        roles = dict(zip((t.text for t in tokens),
                         classify_tokens(tokens, {0: sheet_role.SCHEMATIC},
                                         None, {0: (1224.0, 792.0)})))
        self.assertEqual(roles["27022"], TITLEBLOCK)
        self.assertEqual(roles["300140"], DRAWING)
        self.assertIn(TITLEBLOCK, NON_DRAWING)
        doc.close()

    def test_no_page_sizes_no_masking(self):
        doc, page = self._page()
        tokens = extract_tokens(page, 0)
        roles = dict(zip((t.text for t in tokens),
                         classify_tokens(tokens, {0: sheet_role.SCHEMATIC})))
        self.assertEqual(roles["27022"], DRAWING)
        doc.close()

    def test_the_ladder_bottom_rows_stay_unmasked(self):
        # A two-column ladder's last lines sit around 0.85 of the page height;
        # the mask must start below them.
        doc = fitz.open()
        page = doc.new_page(width=1224.0, height=792.0)
        page.insert_text((900.0, 792.0 * 0.85), "601740", fontsize=8)
        tokens = extract_tokens(page, 0)
        roles = classify_tokens(tokens, {0: sheet_role.SCHEMATIC}, None,
                                {0: (1224.0, 792.0)})
        self.assertEqual(roles[0], DRAWING)
        doc.close()


class TestOrdering(unittest.TestCase):
    def test_result_is_positional(self):
        doc, page = _page([NOTE, IO_ROW])
        tokens = extract_tokens(page, 0)
        roles = classify_tokens(tokens, {0: sheet_role.SCHEMATIC})
        self.assertEqual(len(roles), len(tokens))
        doc.close()


if __name__ == "__main__":
    unittest.main()
