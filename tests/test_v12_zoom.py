"""Zoom sharpness: the page bitmap must render past 400% (not stay a blurry 4x
upscale), while a per-page pixel budget keeps very large sheets bounded."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

try:
    from PySide6.QtWidgets import QApplication
    from app.viewer.page_item import PageItem
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _doc_with_page(w, h):
    from app.model.document import Document
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "d.pdf")
    d = fitz.open(); d.new_page(width=w, height=h); d.save(src); d.close()
    doc = Document(src); doc.load()
    return doc


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestZoomRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_renders_past_400_percent(self):
        # a normal (letter) page must actually rasterise at >4x, not stay 4x
        doc = _doc_with_page(612, 792)
        item = PageItem(doc, 0, 0.0)
        item.render(6.0)
        self.assertGreaterEqual(item._render_scale, 5.9)   # was hard-capped at 4.0
        doc.close()

    def test_budget_caps_a_huge_page_but_not_a_small_one(self):
        # shrink the budget so the cap is testable with tiny, fast renders
        orig = PageItem._PX_BUDGET
        PageItem._PX_BUDGET = 4_000_000
        try:
            small = _doc_with_page(240, 240)      # area 57.6k -> max_scale ~8.3
            it_s = PageItem(small, 0, 0.0)
            it_s.render(8.0)
            self.assertAlmostEqual(it_s._render_scale, 8.0, delta=0.2)

            big = _doc_with_page(1000, 1000)      # area 1M -> max_scale 2.0
            it_b = PageItem(big, 0, 0.0)
            it_b.render(8.0)
            self.assertLess(it_b._render_scale, 4.0)      # capped well below 8
            self.assertAlmostEqual(it_b._render_scale, 2.0, delta=0.2)
            small.close(); big.close()
        finally:
            PageItem._PX_BUDGET = orig

    def test_default_budget_keeps_e_size_near_4x(self):
        # E-size (34x44in = 2448x3168pt) should still reach ~4x (no regression)
        area = 2448 * 3168
        max_scale = (PageItem._PX_BUDGET / area) ** 0.5
        self.assertGreaterEqual(max_scale, 3.9)


if __name__ == "__main__":
    unittest.main()
