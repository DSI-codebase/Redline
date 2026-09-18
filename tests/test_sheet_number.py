"""Sheet-number resolution.

The original title-block heuristics resolved 0 of 14 pages on a real AutoCAD
Electrical plot and reported a wrong number for the one page they did answer,
so several tests here exist to pin down exactly why, and to keep it fixed.
"""

import os
import tempfile
import unittest

import fitz

from app.extraction.sheet_number import (
    SheetNumberConfig, SheetResolution, resolve_page, resolve_document,
    dominant_prefix, drawing_number_candidates,
    DRAWING_NUMBER, KEYWORD, CORNER, UNRESOLVED, CONFIDENCE,
)

W, H = 1224.0, 792.0


def _page(doc, entries):
    """Add a landscape page; entries are ``(text, x, y)`` in PDF points."""
    page = doc.new_page(width=W, height=H)
    for text, x, y in entries:
        page.insert_text((x, y), text)
    return page


def _doc(pages):
    doc = fitz.open()
    for entries in pages:
        _page(doc, entries)
    return doc


# Somewhere inside the title-block band (x > 0.55W, y > 0.72H).
TB = (W * 0.75, H * 0.90)
# Somewhere in the body of the drawing.
BODY = (W * 0.10, H * 0.10)


class TestDrawingNumber(unittest.TestCase):
    def test_reads_the_sheet_suffix(self):
        doc = _doc([[("EL2507777-300", *BODY)]])
        got = resolve_page(doc[0], SheetNumberConfig(strategies=(DRAWING_NUMBER,)))
        self.assertEqual(got.label, "300")
        self.assertEqual(got.strategy, DRAWING_NUMBER)
        self.assertEqual(got.confidence, 1.0)
        doc.close()

    def test_preserves_leading_zeros(self):
        doc = _doc([[("EL2507777-000", *BODY)]])
        self.assertEqual(resolve_page(doc[0]).label, "000")
        doc.close()

    def test_ignores_catalog_numbers(self):
        # Bills of materials are full of things shaped like drawing numbers.
        doc = _doc([[("1783-US5T", *BODY), ("800T-QTH2B", W * 0.3, H * 0.2),
                     ("25B-V2P5N104", W * 0.3, H * 0.3)]])
        self.assertEqual(drawing_number_candidates(doc[0], SheetNumberConfig()), [])
        doc.close()

    def test_two_different_suffixes_resolve_to_nothing(self):
        # Ambiguity must produce silence, never a coin flip.
        doc = _doc([[("EL2507777-300", *BODY), ("EL2507777-400", W * 0.3, H * 0.3)]])
        self.assertFalse(resolve_page(doc[0]).resolved)
        doc.close()

    def test_prefix_pinning_rejects_a_foreign_match(self):
        doc = _doc([[("EL2507777-300", *BODY), ("XX1234567-999", W * 0.3, H * 0.3)]])
        got = resolve_page(doc[0], SheetNumberConfig(), prefix="EL2507777")
        self.assertEqual(got.label, "300")
        doc.close()


class TestExtractionQuirks(unittest.TestCase):
    def test_matches_a_drawing_number_that_only_the_word_list_preserves(self):
        # Flat text and the word list do not always agree; matching both adds
        # recall, and an anchored whole-word match adds no false positives.
        doc = _doc([[("EL2507777-300", *BODY)]])
        hits = drawing_number_candidates(doc[0], SheetNumberConfig())
        self.assertEqual(hits, [("EL2507777", "300")])
        doc.close()

    def test_a_merged_title_block_cell_falls_through_rather_than_guessing(self):
        # When PyMuPDF merges two adjacent cells into one word, the drawing
        # number is unrecoverable. Documented here because the correct behavior
        # is to say nothing and let the next strategy try -- not to loosen the
        # pattern until it matches part of a catalog number.
        doc = fitz.open()
        page = doc.new_page(width=792.0, height=1224.0)
        page.insert_text((40.0, 1000.0), "24 VDC DISTRIBUTION", rotate=270)
        page.insert_text((40.0, 1120.0), "EL2507777-400", rotate=270)
        page.set_rotation(270)
        self.assertEqual(drawing_number_candidates(page, SheetNumberConfig()), [])
        doc.close()


class TestDominantPrefix(unittest.TestCase):
    def test_finds_the_project_number(self):
        doc = _doc([[("EL2507777-000", *BODY)],
                    [("EL2507777-100", *BODY)],
                    [("EL2507777-200", *BODY)]])
        self.assertEqual(dominant_prefix(doc), "EL2507777")
        doc.close()

    def test_a_single_stray_match_is_not_a_project_number(self):
        doc = _doc([[("AB1234-99", *BODY)], [("nothing here", *BODY)]])
        self.assertIsNone(dominant_prefix(doc))
        doc.close()


class TestKeyword(unittest.TestCase):
    CFG = SheetNumberConfig(strategies=(KEYWORD,))

    def test_reads_a_title_block_label(self):
        doc = _doc([[("SHEET 300", *TB)]])
        got = resolve_page(doc[0], self.CFG)
        self.assertEqual(got.label, "300")
        self.assertEqual(got.strategy, KEYWORD)
        doc.close()

    def test_sparse_page_is_searched_everywhere(self):
        # A page with almost no text cannot hide a paragraph of notes, so the
        # keyword is trusted wherever it sits. This is the shape of the older
        # synthetic fixtures.
        doc = _doc([[("SHEET 000", *BODY)]])
        self.assertEqual(resolve_page(doc[0], self.CFG).label, "000")
        doc.close()

    def test_busy_page_ignores_the_keyword_outside_the_title_block(self):
        # The defect this whole module exists to fix: on the real plot the
        # keyword matched a drafting note and reported sheet 26 for sheet 000.
        note = ("7. PROJECT DRAWING NUMBER / SHEET LINE NUMBER / WIRE NUMBER "
                "RELATIONSHIP: THE DRAWING NUMBER SUFFIX DENOTES A SUBSET OF "
                "LIKE ITEMS. LINE NUMBERS ARE ARRANGED VERTICALLY DOWN EACH "
                "SHEET IN ONE OR TWO COLUMNS. A WIRE ON SHEET 26 LINE 12 WOULD "
                "BE ASSIGNED NUMBER 2612. CONSECUTIVE WIRES ON THE SAME SHEET "
                "AND LINE WOULD HAVE AN ADDITIONAL DIGIT APPENDED, SO 261201 "
                "IS THE FIRST ADDITIONAL WIRE AND 261202 THE SECOND.")
        doc = _doc([[(note, 20, 100)]])
        self.assertFalse(resolve_page(doc[0], self.CFG).resolved)
        doc.close()

    def test_label_and_value_in_adjacent_cells(self):
        doc = _doc([[("SHEET:", W * 0.70, H * 0.90), ("300", W * 0.80, H * 0.90)]])
        self.assertEqual(resolve_page(doc[0], self.CFG).label, "300")
        doc.close()


class TestCorner(unittest.TestCase):
    CFG = SheetNumberConfig(strategies=(CORNER,))

    def test_takes_the_lesser_of_this_sheet_and_next(self):
        doc = _doc([[("002", W * 0.80, H * 0.90), ("004", W * 0.90, H * 0.90)]])
        self.assertEqual(resolve_page(doc[0], self.CFG).label, "002")
        doc.close()

    def test_gives_up_when_the_corner_is_crowded(self):
        doc = _doc([[(str(n), W * (0.75 + i * 0.03), H * 0.90)
                     for i, n in enumerate((1, 2, 3, 4, 5))]])
        self.assertFalse(resolve_page(doc[0], self.CFG).resolved)
        doc.close()

    def test_confidence_is_lower_than_the_drawing_number(self):
        self.assertLess(CONFIDENCE[CORNER], CONFIDENCE[DRAWING_NUMBER])


def _tb_doc(entries):
    """A page whose title-block text is plotted small, as real ones are.

    The default ``insert_text`` size gives glyph boxes fifteen points tall, so
    rows five points apart -- the real spacing measured off a real block --
    overlap and "on the line below" stops meaning anything. Real plots write
    this text around five points high.
    """
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    for text, x, y in entries:
        page.insert_text((x, y), text, fontsize=5)
    return doc


class TestUnderscoreSeparator(unittest.TestCase):
    """EL2503311_011 is EL2507777-300 drawn by a different shop.

    The hyphen-only pattern sent a real 28-sheet set's every page through to
    the corner heuristic, which read the REV cell -- see TestRevisionCell.
    """

    def test_reads_an_underscore_suffix(self):
        doc = _doc([[("EL2503311_011", *BODY)]])
        got = resolve_page(doc[0], SheetNumberConfig(strategies=(DRAWING_NUMBER,)))
        self.assertEqual((got.label, got.strategy), ("011", DRAWING_NUMBER))
        doc.close()

    def test_the_prefix_pins_across_an_underscore_set(self):
        doc = _doc([[("EL2503311_000", *BODY)], [("EL2503311_609", *BODY)]])
        self.assertEqual(dominant_prefix(doc), "EL2503311")
        doc.close()

    def test_a_snake_case_identifier_is_not_a_drawing_number(self):
        # Letters-first with the digits hard against them, same as the hyphen
        # guard for catalog numbers.
        doc = _doc([[("TAG_1234_567", *BODY), ("MY_TABLE_01", W * 0.3, H * 0.2)]])
        self.assertFalse(
            resolve_page(doc[0], SheetNumberConfig(strategies=(DRAWING_NUMBER,)))
            .resolved)
        doc.close()


class TestRevisionCell(unittest.TestCase):
    """The corner heuristic's "lesser number" rule selects the revision every
    time one appears: revisions live in the same corner and are usually 0.
    One real set came back with all seventeen resolvable sheets named "0"."""

    CFG = SheetNumberConfig(strategies=(CORNER,))

    # The measured layout: "REV:" with its value on the line below, dead
    # aligned; "THIS SHEET:" / "NEXT SHEET:" labels with their values below.
    def _block(self, rev=("REV:", W * 0.945, H * 0.945),
               revval=("0", W * 0.945, H * 0.952)):
        return [
            rev, revval,
            ("THIS", W * 0.900, H * 0.964), ("SHEET:", W * 0.912, H * 0.964),
            ("NEXT", W * 0.938, H * 0.964), ("SHEET:", W * 0.950, H * 0.964),
            ("011", W * 0.910, H * 0.971), ("012", W * 0.944, H * 0.971),
        ]

    def test_the_revision_is_not_a_candidate(self):
        doc = _tb_doc(self._block())
        got = resolve_page(doc[0], self.CFG)
        self.assertEqual(got.label, "011", "the lesser of THIS and NEXT, "
                         "never the REV cell's value")
        doc.close()

    def test_a_rev_beside_its_label_is_excluded_too(self):
        doc = _tb_doc(self._block(rev=("REV:", W * 0.930, H * 0.952),
                                revval=("0", W * 0.947, H * 0.952)))
        self.assertEqual(resolve_page(doc[0], self.CFG).label, "011")
        doc.close()

    def test_a_corner_holding_only_the_revision_stays_unresolved(self):
        doc = _tb_doc([("REV:", W * 0.945, H * 0.945), ("0", W * 0.945, H * 0.952)])
        self.assertFalse(resolve_page(doc[0], self.CFG).resolved)
        doc.close()

    def test_a_bare_zero_with_no_rev_label_is_still_believed(self):
        # Exclusion needs the label: a sheet genuinely numbered 0 keeps
        # resolving, and absence of evidence excludes nothing.
        doc = _tb_doc([("0", W * 0.80, H * 0.90)])
        self.assertEqual(resolve_page(doc[0], self.CFG).label, "0")
        doc.close()


class TestKeywordValueBelow(unittest.TestCase):
    CFG = SheetNumberConfig(strategies=(KEYWORD,))

    def test_reads_the_value_on_the_line_below_the_label(self):
        doc = _tb_doc([("THIS", W * 0.900, H * 0.964),
                       ("SHEET:", W * 0.912, H * 0.964),
                       ("011", W * 0.910, H * 0.971)])
        got = resolve_page(doc[0], self.CFG)
        self.assertEqual((got.label, got.strategy), ("011", KEYWORD))
        doc.close()

    def test_next_sheet_is_not_this_sheet(self):
        # Only the NEXT cell present: its label says, in its own words, that
        # the value is the following sheet. Refusing is the honest answer.
        doc = _tb_doc([("NEXT", W * 0.938, H * 0.964),
                       ("SHEET:", W * 0.950, H * 0.964),
                       ("012", W * 0.944, H * 0.971)])
        self.assertFalse(resolve_page(doc[0], self.CFG).resolved)
        doc.close()

    def test_with_both_cells_the_this_value_wins(self):
        doc = _tb_doc([("THIS", W * 0.900, H * 0.964),
                       ("SHEET:", W * 0.912, H * 0.964),
                       ("NEXT", W * 0.938, H * 0.964),
                       ("SHEET:", W * 0.950, H * 0.964),
                       ("011", W * 0.910, H * 0.971),
                       ("012", W * 0.944, H * 0.971)])
        self.assertEqual(resolve_page(doc[0], self.CFG).label, "011")
        doc.close()


class TestStrategyOrder(unittest.TestCase):
    def test_drawing_number_wins_over_a_conflicting_keyword(self):
        doc = _doc([[("EL2507777-300", *BODY), ("SHEET 999", *TB)]])
        got = resolve_page(doc[0], SheetNumberConfig(), prefix="EL2507777")
        self.assertEqual(got.label, "300")
        self.assertEqual(got.strategy, DRAWING_NUMBER)
        doc.close()

    def test_falls_through_to_the_next_strategy(self):
        doc = _doc([[("SHEET 300", *TB)]])
        self.assertEqual(resolve_page(doc[0]).strategy, KEYWORD)
        doc.close()

    def test_unresolved_page_says_so(self):
        doc = _doc([[("no numbering anywhere", *BODY)]])
        got = resolve_page(doc[0])
        self.assertEqual(got, UNRESOLVED)
        self.assertFalse(got.resolved)
        self.assertIsNone(got.number)
        doc.close()


class TestDocument(unittest.TestCase):
    def test_resolves_a_whole_set_and_pins_the_prefix(self):
        doc = _doc([[("EL2507777-000", *BODY)],
                    [("EL2507777-100", *BODY), ("1783-US5T", W * 0.3, H * 0.3)],
                    [("EL2507777-601", *BODY)]])
        got = resolve_document(doc)
        self.assertEqual([got[i].label for i in range(3)], ["000", "100", "601"])
        self.assertTrue(all(r.strategy == DRAWING_NUMBER for r in got.values()))
        doc.close()

    def test_number_parses_padded_labels(self):
        self.assertEqual(SheetResolution(label="000").number, 0)
        self.assertEqual(SheetResolution(label="601").number, 601)


if __name__ == "__main__":
    unittest.main()
