"""Regression test: resizing a rotated mark keeps the opposite corner fixed."""

import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestRotatedResize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from app.viewer.annotation_items import make_item
        cls.make_item = staticmethod(make_item)

    def _make(self, kind, rotation):
        from app.model.annotations import Annotation
        from app.model.annotations import AnnotationStore

        class _View:
            def __init__(self):
                self.store = AnnotationStore()
                self.select_mode = True
            def push_command(self, cmd):
                pass

        ann = Annotation(page=0, kind=kind, rect=(120, 140, 300, 240),
                         rotation=rotation)
        item = self.make_item(ann, _View())
        item.sync_from_model()
        return item

    def test_anchor_stays_fixed_when_rotated(self):
        from app.model.annotations import KIND_RECT, KIND_ARROW
        for kind in (KIND_RECT, KIND_ARROW):
            for rot in (0, 30, 90, 135, 200, -45):
                for role in ("se", "nw", "ne", "sw"):
                    item = self._make(kind, rot)
                    opp = item._OPPOSITE[role]
                    before = item.mapToScene(item._corner(opp))
                    item._begin_resize(role)
                    cur = item.mapToScene(item._corner(role))
                    item._resize_to(role, QPointF(cur.x() + 40, cur.y() + 25))
                    after = item.mapToScene(item._corner(opp))
                    drift = math.hypot(after.x() - before.x(), after.y() - before.y())
                    self.assertLess(drift, 0.5,
                                    f"{kind} rot={rot} role={role} drift={drift:.3f}")


if __name__ == "__main__":
    unittest.main()
