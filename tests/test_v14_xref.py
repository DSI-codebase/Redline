"""Rung gutters, off-page connectors, and title-block fields.

Together these turn "this text is somewhere on sheet 300" into "this is on
sheet 300, line 14, and it says the signal goes to sheet 700 line 04" — which is
what makes a cross-reference checkable at all.
"""

import unittest

import fitz

from app.extraction.text_extract import extract_tokens
from app.extraction.rung import (RungConfig, extract_rungs, gutter_columns,
                                 index_by_line, rung_at)
from app.extraction.signal_arrow import (SignalArrowConfig, dedupe,
                                         extract_arrows)
from app.extraction.titleblock import TitleBlockFields, read_fields

W, H = 792.0, 1224.0          # portrait, as plotted; rotated 270 for display
DW, DH = 1224.0, 792.0        # the same page as displayed
PITCH = 15.7                  # measured rung spacing on the sample set
FIRST_Y = 60.0                # display y of the first rung


def _place(page, display_x, display_y, text):
    """Write ``text`` so it lands at (display_x, display_y) on the shown page.

    A sheet is plotted portrait and rotated 270 for display, and title-block and
    gutter text is written rotated so it still reads horizontally. Under that
    transform display x comes from unrotated y and display y from unrotated x,
    so fixtures are far easier to reason about stated the way a reader sees
    them and converted once, here.
    """
    page.insert_text((W - display_y, display_x), text, rotate=270)


def _ladder(sheet="300", lines=6, columns=1, extra=()):
    """A sheet with a numbered gutter, drawn the way a real plot draws it."""
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    for col in range(columns):
        base = col * 40
        x = 66.0 + col * 580.0
        for i in range(lines):
            y = FIRST_Y + i * PITCH
            _place(page, x, y, sheet)
            # Just clear of the sheet number: a gutter entry is two adjacent
            # tokens, and overlapping them is not what a plot does.
            _place(page, x + 24.0, y, f"{base + i + 1:02d}")
    for text, dx, dy in extra:
        _place(page, dx, dy, text)
    page.set_rotation(270)
    return doc, page


def _line_y(line, column=0):
    """Display y of a rung's gutter entry."""
    within = (line - 1) - column * 40
    return FIRST_Y + within * PITCH


class TestRungGutter(unittest.TestCase):
    def test_finds_every_line(self):
        doc, page = _ladder(lines=6)
        rungs = extract_rungs(extract_tokens(page, 0), "300", page.rect.width)
        self.assertEqual(sorted(r.line for r in rungs), [1, 2, 3, 4, 5, 6])
        doc.close()

    def test_reports_one_column(self):
        doc, page = _ladder(lines=4, columns=1)
        rungs = extract_rungs(extract_tokens(page, 0), "300", page.rect.width)
        self.assertEqual(len(gutter_columns(rungs)), 1)
        doc.close()

    def test_reports_two_columns(self):
        # The sample set's own title page says line numbers run "in (1) or (2)
        # columns"; on a two-column sheet one printed row carries two rungs.
        doc, page = _ladder(lines=4, columns=2)
        rungs = extract_rungs(extract_tokens(page, 0), "300", page.rect.width)
        self.assertEqual(len(gutter_columns(rungs)), 2)
        self.assertEqual(sorted(r.line for r in rungs),
                         [1, 2, 3, 4, 41, 42, 43, 44])
        doc.close()

    def test_ignores_a_number_that_is_not_the_sheet(self):
        doc, page = _ladder(sheet="300", lines=3,
                            extra=[("999 07", 300.0, 300.0)])
        rungs = extract_rungs(extract_tokens(page, 0), "300", page.rect.width)
        self.assertTrue(all(r.sheet == "300" for r in rungs))
        self.assertEqual(len(rungs), 3)
        doc.close()

    def test_no_sheet_label_means_no_rungs(self):
        doc, page = _ladder(lines=3)
        self.assertEqual(extract_rungs(extract_tokens(page, 0), ""), [])
        doc.close()

    def test_index_by_line(self):
        doc, page = _ladder(lines=3)
        rungs = extract_rungs(extract_tokens(page, 0), "300", page.rect.width)
        self.assertEqual(set(index_by_line(rungs)), {1, 2, 3})
        doc.close()


class TestRungAssignment(unittest.TestCase):
    """Which rung a mark belongs to."""

    def _rungs(self, columns=1, lines=6):
        doc, page = _ladder(lines=lines, columns=columns)
        rungs = extract_rungs(extract_tokens(page, 0), "300", page.rect.width)
        return doc, page, rungs

    def test_content_belongs_to_the_gutter_above_it(self):
        # A rung spans from its own number down to the next; drawing content
        # sits below the number that labels it.
        doc, _page, rungs = self._rungs()
        by_line = {r.line: r for r in rungs}
        target = by_line[3]
        got = rung_at(rungs, target.x + 200.0, target.y + 6.0)
        self.assertEqual(got.line, 3)
        doc.close()

    def test_content_just_above_its_label_still_belongs_to_it(self):
        doc, _page, rungs = self._rungs()
        target = {r.line: r for r in rungs}[3]
        self.assertEqual(rung_at(rungs, target.x + 200.0, target.y - 2.0).line, 3)
        doc.close()

    def test_the_right_column_is_not_filed_under_the_left(self):
        # The failure this rule exists to prevent: taking the leftmost gutter
        # files an entire column under the wrong line numbers.
        doc, _page, rungs = self._rungs(columns=2)
        right = max(r.x for r in rungs)
        target = next(r for r in rungs if r.x == right and r.line == 43)
        got = rung_at(rungs, target.x + 40.0, target.y + 6.0)
        self.assertEqual(got.line, 43)
        doc.close()

    def test_header_content_above_the_ladder_belongs_to_the_first_rung(self):
        # A PLC module's rack and slot annotation is drawn above line 01.
        doc, _page, rungs = self._rungs()
        first = min(rungs, key=lambda r: r.y)
        self.assertEqual(rung_at(rungs, first.x + 200.0, first.y - 10.0).line,
                         first.line)
        doc.close()

    def test_far_above_the_ladder_belongs_to_nothing(self):
        doc, _page, rungs = self._rungs()
        first = min(rungs, key=lambda r: r.y)
        self.assertIsNone(rung_at(rungs, first.x + 200.0, first.y - 400.0))
        doc.close()

    def test_left_of_every_gutter_belongs_to_nothing(self):
        doc, _page, rungs = self._rungs()
        first = min(rungs, key=lambda r: r.y)
        self.assertIsNone(rung_at(rungs, first.x - 50.0, first.y + 4.0))
        doc.close()


class TestSignalArrows(unittest.TestCase):
    def _arrows(self, labels, sheet="300", lines=6):
        doc, page = _ladder(sheet=sheet, lines=lines, extra=labels)
        tokens = extract_tokens(page, 0)
        rungs = extract_rungs(tokens, sheet, page.rect.width)
        return doc, dedupe(extract_arrows(tokens, rungs, sheet))

    def test_reads_a_destination(self):
        doc, arrows = self._arrows([("to 70004", 300.0, _line_y(3) + 4.0)])
        self.assertEqual(len(arrows), 1)
        a = arrows[0]
        self.assertEqual(a.direction, "to")
        self.assertEqual((a.target_sheet, a.target_line), (700, 4))
        self.assertEqual(a.target, "700-04")
        doc.close()

    def test_reads_a_source(self):
        doc, arrows = self._arrows([("from 30014", 300.0, _line_y(2) + 4.0)])
        self.assertEqual(arrows[0].direction, "from")
        self.assertEqual(arrows[0].target, "300-14")
        doc.close()

    def test_reads_the_line_wording(self):
        doc, arrows = self._arrows([("TO LINE 30041", 300.0, _line_y(2) + 4.0)])
        self.assertEqual(arrows[0].target, "300-41")
        doc.close()

    def test_reads_an_explicit_page_hint(self):
        doc, arrows = self._arrows(
            [("to 70004 PG.700", 300.0, _line_y(2) + 4.0)])
        self.assertEqual(arrows[0].target_page_hint, "700")
        doc.close()

    def test_a_six_digit_wire_number_resolves_to_its_line(self):
        doc, arrows = self._arrows([("to 400790", 300.0, _line_y(2) + 4.0)])
        self.assertEqual(arrows[0].target, "400-79")
        doc.close()

    def test_knows_which_rung_it_sits_on(self):
        doc, arrows = self._arrows([("to 70004", 300.0, _line_y(4) + 4.0)])
        self.assertIsNotNone(arrows[0].source_line)
        self.assertEqual(arrows[0].source_sheet, "300")
        doc.close()

    def test_counterpart_direction(self):
        doc, arrows = self._arrows([("to 70004", 300.0, _line_y(2) + 4.0)])
        self.assertEqual(arrows[0].counterpart_direction, "from")
        doc.close()

    def test_ignores_the_word_to_in_prose(self):
        doc, arrows = self._arrows(
            [("ALL WIRE IS TO BE OF TYPE MTW", 300.0, _line_y(2) + 4.0)])
        self.assertEqual(arrows, [])
        doc.close()

    def test_ignores_a_number_that_is_too_short(self):
        doc, arrows = self._arrows([("to 700", 300.0, _line_y(2) + 4.0)])
        self.assertEqual(arrows, [])
        doc.close()

    def test_dedupe_collapses_a_connector_drawn_twice(self):
        # A connector symbol commonly carries its label at both ends; that is
        # one signal, and counting it twice would make a missing counterpart
        # look satisfied.
        doc, page = _ladder(lines=6, extra=[
            ("to 70004", 300.0, _line_y(2) + 4.0),
            ("to 70004", 380.0, _line_y(2) + 4.0)])
        tokens = extract_tokens(page, 0)
        rungs = extract_rungs(tokens, "300", page.rect.width)
        raw = extract_arrows(tokens, rungs, "300")
        self.assertEqual(len(raw), 2)
        self.assertEqual(len(dedupe(raw)), 1)
        doc.close()


class TestTitleBlock(unittest.TestCase):
    def _page(self, this_sheet, next_sheet):
        """A title block with its labels above their values, as plotted."""
        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        # Labels in one row, their values in the row just beneath.
        _place(page, 1000.0, 740.0, "THIS SHEET:")
        _place(page, 1090.0, 740.0, "NEXT:")
        _place(page, 998.0, 754.0, this_sheet)
        _place(page, 1092.0, 754.0, next_sheet)
        page.set_rotation(270)
        return doc, page

    def test_reads_both_fields(self):
        doc, page = self._page("003", "004")
        got = read_fields(extract_tokens(page, 0), page.rect.width,
                          page.rect.height)
        self.assertEqual(got.this_sheet, "003")
        self.assertEqual(got.next_sheet, "004")
        self.assertTrue(got.resolved)
        doc.close()

    def test_missing_fields_are_blank_not_guessed(self):
        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        page.insert_text((60.0, 1080.0), "NO TITLE BLOCK HERE", rotate=270)
        page.set_rotation(270)
        got = read_fields(extract_tokens(page, 0), page.rect.width,
                          page.rect.height)
        self.assertEqual((got.this_sheet, got.next_sheet), ("", ""))
        self.assertFalse(got.resolved)
        doc.close()

    def test_ignores_schematic_content_outside_the_title_block(self):
        # A naive "value near the label" search picks up wire numbers from the
        # body of the drawing; the search is confined to the title block.
        doc, page = self._page("003", "004")
        doc2 = fitz.open()
        page2 = doc2.new_page(width=W, height=H)
        _place(page2, 200.0, 200.0, "THIS SHEET: 999")
        page2.set_rotation(270)
        got = read_fields(extract_tokens(page2, 0), page2.rect.width,
                          page2.rect.height)
        self.assertEqual(got.this_sheet, "")
        doc.close()
        doc2.close()

    def test_empty_page(self):
        self.assertEqual(read_fields([], W, H), TitleBlockFields())


if __name__ == "__main__":
    unittest.main()
