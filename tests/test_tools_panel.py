"""Regression tests for the iLovePDF-style PDF Tools workspace.

Offscreen-only: instantiate the panel, load a generated PDF, and check the
visual-selection ↔ page-spec sync, the range builder, the rotation preview
overrides, and the drag/drop mime helper.  No modal dialogs are exec()'d.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import fitz
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QMimeData, QUrl
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _make_pdf(path, pages=8):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page(width=612, height=792)
        p.insert_text((60, 60), f"PAGE {i + 1}")
    d.save(path)
    d.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestToolsWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.panels.tools_panel import ToolsPanel

        class _Win:
            document = None

            class _Tabs:
                def setCurrentWidget(self, *_):
                    pass
            tabs = _Tabs()

        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "deck.pdf")
        _make_pdf(self.src, 8)
        self.panel = ToolsPanel(_Win())
        self.panel.load_pdf(self.src)

    def tearDown(self):
        self.panel.grid.close_doc()

    def test_loads_pages(self):
        self.assertEqual(self.panel.grid.page_count, 8)
        self.assertEqual(self.panel.current_pdf, self.src)

    def test_grid_to_spec_sync(self):
        self.panel.show_operation("extract")
        self.panel.grid.set_selected_pages([0, 2, 4])
        self.assertEqual(self.panel._spec_edits["extract"].text(), "1,3,5")

    def test_spec_to_grid_sync(self):
        self.panel.show_operation("delete")
        self.panel._on_spec_edited("delete", "2,4-6")
        self.assertEqual(self.panel.grid.selected_pages(), [1, 3, 4, 5])

    def test_range_from_selection(self):
        self.panel.show_operation("split")
        self.panel.grid.set_selected_pages([2, 3, 4])
        self.panel._add_range_from_selection()
        self.assertEqual(self.panel._ranges(), [(2, 4)])

    def test_rotation_preview_overrides(self):
        self.panel.show_operation("rotate")
        self.panel.grid.set_selected_pages([0, 1])
        self.panel._nudge_rotation(90)
        ov = self.panel.grid.rotation_overrides()
        self.assertEqual(ov.get(0), 90)
        self.assertEqual(ov.get(1), 90)
        self.assertNotIn(2, ov)
        self.panel._reset_rotation()
        self.assertEqual(self.panel.grid.rotation_overrides(), {})

    def test_rotate_no_selection_targets_all(self):
        self.panel.show_operation("rotate")
        self.panel.grid.clear_page_selection()
        self.assertEqual(self.panel._rotate_targets(), list(range(8)))

    def test_drag_drop_mime_helper(self):
        from app.panels.tools_panel import pdf_path_from_mime
        m = QMimeData(); m.setUrls([QUrl.fromLocalFile(self.src)])
        # toLocalFile() uses forward slashes even on Windows -> normalise both
        self.assertEqual(os.path.normpath(pdf_path_from_mime(m)),
                         os.path.normpath(self.src))
        m2 = QMimeData(); m2.setUrls([QUrl.fromLocalFile("/x/y.txt")])
        self.assertEqual(pdf_path_from_mime(m2), "")
        self.assertEqual(pdf_path_from_mime(QMimeData()), "")

    def test_accepts_drops(self):
        self.assertTrue(self.panel.acceptDrops())


if __name__ == "__main__":
    unittest.main()
