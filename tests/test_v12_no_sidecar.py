"""Invalid filenames (too long / unsupported characters) that can't back a
markup-database sidecar: the PDF still opens for viewing, markup + saving are
turned off, and the user is told why."""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import KIND_COMMENT
from app.model.storage import NullSidecar

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.viewer import tools as T
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _make_pdf(dirpath, name="d.pdf"):
    src = os.path.join(dirpath, name)
    d = fitz.open(); d.new_page(width=400, height=300)
    # give it a bit of text so "view / find" has something to work with
    d[0].insert_text((72, 72), "hello wire 300")
    d.save(src); d.close()
    return src


class TestNullSidecar(unittest.TestCase):
    def test_reads_empty_writes_noop(self):
        s = NullSidecar()
        self.assertEqual(s.load_annotations(), [])
        self.assertEqual(s.load_wires(), [])
        self.assertEqual(s.load_components(), [])
        self.assertIsNone(s.get_meta("sheet_labels"))
        # writes/close must not raise
        s.save_annotations([]); s.save_wires([]); s.save_components([])
        s.set_meta("k", "v"); s.close()

    def test_audit_methods_have_stubs(self):
        # NullSidecar is duck-typed, not a subclass, so nothing catches a
        # missing method: a view-only document would crash at runtime instead.
        # This test is the parity contract -- extend it with every new
        # SidecarDB method app code calls.
        from app.audit.findings import Waiver
        s = NullSidecar()
        self.assertEqual(s.load_findings(), [])
        self.assertEqual(s.load_waivers(), {})
        s.save_findings([])
        s.save_waiver(Waiver(key="k"))
        s.delete_waiver("k")
        s.replace_waivers({})
        s.close()

    def test_every_sidecar_method_app_code_calls_has_a_twin(self):
        from app.model.storage import SidecarDB
        public = {n for n in dir(SidecarDB)
                  if not n.startswith("_") and callable(getattr(SidecarDB, n))}
        missing = {n for n in public if not hasattr(NullSidecar, n)}
        # app_state_map is a known, dead exception (no call sites anywhere).
        self.assertEqual(missing - {"app_state_map"}, set(),
                         f"NullSidecar is missing: {sorted(missing)}")


class TestDocumentFallback(unittest.TestCase):
    def test_open_falls_back_and_still_loads(self):
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp)
        with mock.patch("app.model.document.SidecarDB",
                        side_effect=sqlite3.OperationalError("unable to open")):
            doc = Document(src)
            doc.load()                       # must not raise
        self.assertFalse(doc.sidecar_available)
        self.assertIsInstance(doc.sidecar, NullSidecar)
        self.assertTrue(doc.sidecar_error)
        self.assertEqual(doc.page_count, 1)  # viewing works

    def test_save_blocked_with_clear_error(self):
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp)
        with mock.patch("app.model.document.SidecarDB",
                        side_effect=sqlite3.OperationalError("unable to open")):
            doc = Document(src); doc.load()
        with self.assertRaises(RuntimeError):
            doc.save()

    def test_normal_open_is_available(self):
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp)
        doc = Document(src); doc.load()
        self.assertTrue(doc.sidecar_available)
        doc.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestWindowGreysOut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _load_without_sidecar(self, win, src):
        with mock.patch("app.model.document.SidecarDB",
                        side_effect=sqlite3.OperationalError("unable to open")), \
             mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok):
            win.load_document(src)

    def test_tools_and_saving_greyed_but_view_alive(self):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp)
        win = MainWindow()
        self._load_without_sidecar(win, src)
        self.assertFalse(win.document.sidecar_available)
        # saving / exporting off
        for a in (win.act_save, win.act_save_as, win.act_export_pdf,
                  win.act_export_flat):
            self.assertFalse(a.isEnabled())
        # drawing tools off, Select still on
        for tool, act in win._tool_actions.items():
            if tool == T.TOOL_SELECT:
                self.assertTrue(act.isEnabled())
            else:
                self.assertFalse(act.isEnabled())
        # styling widgets off
        for w in (win.color_btn, win.fill_btn, win.pen_width, win.font_size,
                  win.bold, win.italic):
            self.assertFalse(w.isEnabled())
        # the document (viewing) is loaded
        self.assertIsNotNone(win.document)
        self.assertEqual(win.document.page_count, 1)

    def test_warning_popup_shown_once(self):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp)
        win = MainWindow()
        with mock.patch("app.model.document.SidecarDB",
                        side_effect=sqlite3.OperationalError("unable to open")), \
             mock.patch.object(QMessageBox, "warning",
                               return_value=QMessageBox.Ok) as warn:
            win.load_document(src)
        self.assertEqual(warn.call_count, 1)

    def test_valid_file_keeps_tools_enabled(self):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp)
        win = MainWindow()
        win.load_document(src)               # real sidecar
        self.assertTrue(win.document.sidecar_available)
        self.assertTrue(win.act_save.isEnabled())
        self.assertTrue(win._tool_actions[T.TOOL_HIGHLIGHT].isEnabled())


if __name__ == "__main__":
    unittest.main()
