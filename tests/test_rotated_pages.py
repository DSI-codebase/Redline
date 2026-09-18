"""Extraction on rotated pages.

Every sheet of a typical AutoCAD Electrical plot is a portrait page rotated for
landscape display. ``get_text("words")`` reports in the *unrotated* space, so
untransformed coordinates belong to a different coordinate system than the one
the viewer, the annotations and the OCR path use -- far enough out that a
jump-to-location target commonly lands off the page.

These tests exist because the whole suite passed while that was broken: nothing
covered a rotated page.
"""

import unittest

import fitz

from app.extraction.text_extract import extract_tokens
from app.extraction.sheet_number import (
    SheetNumberConfig, resolve_page, CORNER, KEYWORD)


def _rotated_page(rotation, entries, width=792.0, height=1224.0):
    """A page carrying ``(text, x, y)`` in unrotated space, then rotated."""
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    for text, x, y in entries:
        page.insert_text((x, y), text)
    page.set_rotation(rotation)
    return doc, page


class TestTokenCoordinates(unittest.TestCase):
    def test_tokens_land_inside_the_displayed_page(self):
        # The defect in one assertion: unrotated y runs to 1224, the displayed
        # page is only 792 tall, so an untransformed token is off the page.
        doc, page = _rotated_page(270, [("400790", 700.0, 1100.0)])
        self.assertEqual((page.rect.width, page.rect.height), (1224.0, 792.0))
        token = extract_tokens(page, 0)[0]
        self.assertTrue(0 <= token.x <= page.rect.width,
                        f"x={token.x} outside 0..{page.rect.width}")
        self.assertTrue(0 <= token.y <= page.rect.height,
                        f"y={token.y} outside 0..{page.rect.height}")
        doc.close()

    def test_coordinates_match_the_rotation_transform(self):
        doc, page = _rotated_page(270, [("TAG", 100.0, 900.0)])
        token = extract_tokens(page, 0)[0]
        raw = [w for w in page.get_text("words") if w[4] == "TAG"][0]
        want = (fitz.Rect(raw[0], raw[1], raw[2], raw[3]) * page.rotation_matrix).normalize()
        self.assertAlmostEqual(token.x, want.x0, places=3)
        self.assertAlmostEqual(token.y, want.y0, places=3)
        doc.close()

    def test_unrotated_pages_are_unchanged(self):
        doc, page = _rotated_page(0, [("TAG", 100.0, 200.0)], width=612.0, height=792.0)
        token = extract_tokens(page, 0)[0]
        raw = [w for w in page.get_text("words") if w[4] == "TAG"][0]
        self.assertAlmostEqual(token.x, raw[0], places=3)
        self.assertAlmostEqual(token.y, raw[1], places=3)
        doc.close()

    def test_every_quarter_turn_stays_on_page(self):
        for rotation in (0, 90, 180, 270):
            doc, page = _rotated_page(rotation, [("TAG", 100.0, 900.0)])
            token = extract_tokens(page, 0)[0]
            self.assertTrue(0 <= token.x <= page.rect.width, rotation)
            self.assertTrue(0 <= token.y <= page.rect.height, rotation)
            doc.close()

    def test_reading_order_follows_the_displayed_page(self):
        # Sorting raw coordinates on a rotated page reads the sheet sideways.
        # In displayed space these three are a left-to-right row.
        # Same unrotated x, increasing unrotated y. At 270 degrees the matrix
        # maps (x, y) -> (y, width - x), so these become one left-to-right row.
        doc, page = _rotated_page(
            270, [("A", 100.0, 100.0), ("B", 100.0, 400.0), ("C", 100.0, 700.0)])
        tokens = extract_tokens(page, 0)
        by_x = [t.text for t in sorted(tokens, key=lambda t: t.x)]
        self.assertEqual(by_x, ["A", "B", "C"])
        # Same row within a glyph-height tolerance -- the same band idea
        # WireConfig.row_band_tol encodes for reading-order sorting.
        ys = [t.y for t in tokens]
        self.assertLess(max(ys) - min(ys), 6.0,
                        f"expected one display row, got ys={ys}")
        doc.close()


class TestSheetNumberOnRotatedPages(unittest.TestCase):
    def test_corner_strategy_can_reach_the_title_block(self):
        # The original heuristic looked for text at x >= 0.70 * 1224 = 857 while
        # no unrotated word can exceed 792, so it searched a region that did not
        # exist and found nothing on every page of every rotated set.
        doc, page = _rotated_page(270, [("002", 60.0, 1150.0), ("004", 60.0, 1190.0)])
        got = resolve_page(page, SheetNumberConfig(strategies=(CORNER,)))
        self.assertEqual(got.label, "002")
        doc.close()

    def test_keyword_band_is_computed_in_displayed_space(self):
        doc, page = _rotated_page(270, [("SHEET 300", 60.0, 1150.0)])
        got = resolve_page(page, SheetNumberConfig(strategies=(KEYWORD,)))
        self.assertEqual(got.label, "300")
        doc.close()


if __name__ == "__main__":
    unittest.main()
