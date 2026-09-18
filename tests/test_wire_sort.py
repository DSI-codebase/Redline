"""Regression: Wire Numbers table columns sort in true numeric order."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestWireTableSort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from app.panels.wire_panel import WirePanel
        from app.extraction.wire_parser import WireNumber, TYPE_CONFORMING
        wp = WirePanel()
        wp.wires = [
            WireNumber(label="2000", sheet=2, rung=5, wire_index=0,
                       wire_type=TYPE_CONFORMING, page=9, count=3),
            WireNumber(label="100050", sheet=100, rung=5, wire_index=0,
                       wire_type=TYPE_CONFORMING, page=1, count=110),
            WireNumber(label="110200", sheet=110, rung=20, wire_index=0,
                       wire_type=TYPE_CONFORMING, page=20, count=2),
        ]
        wp._populate()
        return wp

    def _col(self, wp, col, order=None):
        from PySide6.QtCore import Qt as _Qt
        wp.table.sortItems(col, order or _Qt.AscendingOrder)
        return [wp.table.item(r, col).text() for r in range(wp.table.rowCount())]

    def test_sheet_sorts_numerically(self):
        wp = self._panel()
        self.assertEqual(self._col(wp, 2), ["2", "100", "110"])
        self.assertEqual(self._col(wp, 2, Qt.DescendingOrder), ["110", "100", "2"])

    def test_other_numeric_columns(self):
        wp = self._panel()
        self.assertEqual(self._col(wp, 1), ["2000", "100050", "110200"])  # Label
        self.assertEqual(self._col(wp, 6), ["2", "10", "21"])             # Pg
        self.assertEqual(self._col(wp, 7), ["2", "3", "110"])             # Count

    def test_sortitem_string_fallback(self):
        from app.panels.wire_panel import _SortItem
        items = [_SortItem("beta"), _SortItem("alpha")]
        items.sort()
        self.assertEqual([i.text() for i in items], ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
