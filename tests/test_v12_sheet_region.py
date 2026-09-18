"""Sheet-number split: the user-drawn box is in the viewer's *visual* (rotated)
coordinates; read_region_text derotates it for the text layer so the SAME box
reads on rotated pages (AutoCAD plots are usually rotated) — and the preview and
the split, both going through read_region_text, always agree.
"""

import unittest

import fitz

from app.tools import pdf_ops as ops


def _doc(rotation, number="305"):
    d = fitz.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((480, 760), number)
    if rotation:
        p.set_rotation(rotation)
    return d


def _viewer_box(page, number):
    """The box the viewer's region-pick emits over `number`: the word's bbox
    (get_text space) mapped into visual coords via rotation_matrix."""
    w = next(w for w in page.get_text("words") if number in w[4])
    vis = fitz.Rect(*w[:4]) * page.rotation_matrix
    vis.normalize()
    return (vis.x0 - 2, vis.y0 - 2, vis.x1 + 2, vis.y1 + 2)


class TestSheetRegionRead(unittest.TestCase):
    def test_reads_every_rotation(self):
        for rot in (0, 90, 180, 270):
            d = _doc(rot)
            box = _viewer_box(d[0], "305")
            out = ops.extract_sheet_numbers(
                d, [ops.SheetRegion(0, 0, box)], ops.SHEET_FIRST_NUMBER)
            self.assertEqual(out[0], "305", f"rotation {rot} read {out[0]!r}")
            d.close()

    def test_read_region_text_matches_split_on_rotated_page(self):
        # the preview path (read_region_text) and the split (extract_sheet_numbers
        # -> read_region_text) must return the same thing on a rotated page
        d = _doc(90, number="412")
        box = _viewer_box(d[0], "412")
        preview = ops.read_region_text(d[0], box).strip()
        split = ops.extract_sheet_numbers(
            d, [ops.SheetRegion(0, 0, box)], ops.SHEET_EXACT)[0]
        self.assertEqual(preview, "412")
        self.assertEqual(split, "412")
        d.close()

    def test_empty_box_reads_nothing(self):
        d = _doc(0)
        out = ops.extract_sheet_numbers(
            d, [ops.SheetRegion(0, 0, (5, 5, 40, 20))], ops.SHEET_FIRST_NUMBER)
        self.assertEqual(out[0], "")
        d.close()

    def test_region_accepts_tuple_or_rect(self):
        d = _doc(0, number="77")
        box = _viewer_box(d[0], "77")
        self.assertEqual(ops.read_region_text(d[0], tuple(box)).strip(), "77")
        self.assertEqual(ops.read_region_text(d[0], fitz.Rect(*box)).strip(), "77")
        d.close()


if __name__ == "__main__":
    unittest.main()
