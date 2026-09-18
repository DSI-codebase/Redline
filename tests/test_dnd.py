"""Drag-and-drop regression tests.

The Viewer canvas is a QGraphicsView, which enables drops on its viewport and
forwards them to the scene — so it must handle PDF drops itself (emitting
``requestOpen``) rather than relying on the window's handler.  These tests guard
both the URL parsing and that a drop on the view emits the open request.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QMimeData, QUrl, QPointF, QEvent, Qt
    from PySide6.QtGui import QDropEvent
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestDragDrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _pdf_mime(self):
        path = os.path.join(tempfile.mkdtemp(), "x.pdf")
        open(path, "wb").close()
        m = QMimeData(); m.setUrls([QUrl.fromLocalFile(path)])
        return m, path

    def test_view_detects_pdf(self):
        from app.viewer.pdf_view import PdfView
        m, path = self._pdf_mime()

        class _E:
            def mimeData(self_inner):
                return m
        # QUrl.toLocalFile() yields forward slashes even on Windows; compare
        # OS-normalised so the test is cross-platform (functionally equivalent).
        self.assertEqual(os.path.normpath(PdfView._dropped_pdf(_E())),
                         os.path.normpath(path))

    def test_view_ignores_non_pdf(self):
        from app.viewer.pdf_view import PdfView
        m = QMimeData(); m.setUrls([QUrl.fromLocalFile("/tmp/notes.txt")])

        class _E:
            def mimeData(self_inner):
                return m
        self.assertEqual(PdfView._dropped_pdf(_E()), "")

    def test_view_drop_emits_request_open(self):
        from app.viewer.pdf_view import PdfView
        view = PdfView()
        self.assertTrue(view.acceptDrops())
        m, path = self._pdf_mime()
        seen = []
        view.requestOpen.connect(seen.append)
        evt = QDropEvent(QPointF(10, 10), Qt.CopyAction, m,
                         Qt.LeftButton, Qt.NoModifier, QEvent.Drop)
        view.dropEvent(evt)
        self.assertEqual([os.path.normpath(p) for p in seen],
                         [os.path.normpath(path)])
        self.assertTrue(evt.isAccepted())


if __name__ == "__main__":
    unittest.main()
