"""v1.1.0 Phase 6: Save As — fork the markup to a new working file."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.document import Document
from app.model.annotations import Annotation, KIND_RECT, KIND_CLOUD
from app.model import storage

try:
    from PySide6.QtWidgets import QApplication
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _annot_count(path):
    d = fitz.open(path)
    n = sum(len(list(pg.annots() or [])) for pg in d)
    d.close()
    return n


class TestSaveAsFork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "orig.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(self.src); d.close()

    def _doc_with_marks(self):
        doc = Document(self.src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60),
                                 color=(1, 0, 0), text="n1"))
        doc.store.add(Annotation(page=0, kind=KIND_CLOUD,
                                 points=[(50, 50), (150, 40), (120, 130)],
                                 color=(0, 0, 1)))
        doc.set_sheet_label(0, "042")
        doc.save()
        return doc

    def test_fork_creates_new_working_file(self):
        doc = self._doc_with_marks()
        dest = os.path.join(self.tmp, "fork.pdf")
        out = doc.save_as(dest)
        self.assertEqual(out, storage.marked_pdf_path(dest))
        self.assertTrue(os.path.exists(dest))                      # pristine copy
        self.assertTrue(os.path.exists(storage.sidecar_path(dest)))
        self.assertTrue(os.path.exists(storage.marked_pdf_path(dest)))
        # the document now edits the fork
        self.assertEqual(os.path.abspath(doc.path), os.path.abspath(dest))
        # the pristine copy carries no baked annotations; the marked copy carries
        # the rect + its note's sticky comment + the cloud = 3
        self.assertEqual(_annot_count(dest), 0)
        self.assertEqual(_annot_count(storage.marked_pdf_path(dest)), 3)
        doc.close()

    def test_fork_carries_marks_and_sheets(self):
        doc = self._doc_with_marks()
        dest = os.path.join(self.tmp, "fork.pdf")
        doc.save_as(dest)
        doc.close()
        f = Document(dest); f.load()
        self.assertEqual(len(f.store.all()), 2)
        self.assertEqual(f.sheet_label(0), "042")
        self.assertTrue(any(a.kind == KIND_CLOUD for a in f.store.all()))
        f.close()

    def test_original_untouched_and_independent(self):
        doc = self._doc_with_marks()
        dest = os.path.join(self.tmp, "fork.pdf")
        doc.save_as(dest)
        # add another mark to the fork and save
        doc.store.add(Annotation(page=0, kind=KIND_RECT, rect=(200, 200, 260, 240),
                                 color=(0, 1, 0), text="fork-only"))
        doc.save()
        doc.close()
        # the original still has exactly its 2 marks — the fork's edit didn't leak
        orig = Document(self.src); orig.load()
        self.assertEqual(len(orig.store.all()), 2)
        self.assertFalse(any(a.text == "fork-only" for a in orig.store.all()))
        orig.close()
        # the fork has 3
        f = Document(dest); f.load()
        self.assertEqual(len(f.store.all()), 3)
        f.close()

    def test_fork_canonicalises_marked_name(self):
        doc = self._doc_with_marks()
        # user typed a .marked.pdf name -> fork to the canonical base instead
        doc.save_as(os.path.join(self.tmp, "fork.marked.pdf"))
        self.assertEqual(os.path.basename(doc.path), "fork.pdf")
        doc.close()

    def test_fork_does_not_inherit_stale_wires(self):
        # forking onto a name whose .markup.db already holds foreign wire rows
        # must not leak them into the fork (regression)
        from app.model.storage import SidecarDB, sidecar_path
        dest = os.path.join(self.tmp, "fork.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(dest); d.close()
        stale = SidecarDB(sidecar_path(dest))
        # a bare object with the attributes save_wires reads is enough
        class _W:
            label = "999"; sheet = 9; rung = 9; wire_index = 0
            wire_type = "x"; page = 0; source = "text"; count = 1
            included = True; flags = []
        stale.save_wires([_W()])
        stale.close()
        # this document has no wires; fork onto the pre-seeded dest
        doc = self._doc_with_marks()
        doc.save_as(dest)
        doc.close()
        f = Document(dest); f.load()
        self.assertEqual(f.wires, [])          # the stale wire row was cleared
        f.close()

    def test_fork_from_marked_only_source(self):
        # a working file where only the .marked.pdf exists (original moved away)
        doc = self._doc_with_marks()
        marked = storage.marked_pdf_path(self.src)
        doc.close()
        os.remove(self.src)
        doc2 = Document(marked); doc2.load()
        dest = os.path.join(self.tmp, "fork2.pdf")
        doc2.save_as(dest)
        self.assertTrue(os.path.exists(dest))
        self.assertEqual(_annot_count(dest), 0)     # pristine, stripped copy
        doc2.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestSaveAsWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_switches_to_fork(self):
        from app.main_window import MainWindow
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "orig.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(src); d.close()
        win = MainWindow(); win.load_document(src)
        win.view.store.add(Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60),
                                      text="x"))
        dest = os.path.join(tmp, "fork.pdf")
        orig_get = QFileDialog.getSaveFileName
        orig_info = QMessageBox.information
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (dest, "PDF (*.pdf)"))
        # the handler ends with a modal confirmation — stub it so tests don't block
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        try:
            win.save_as_fork()
        finally:
            QFileDialog.getSaveFileName = orig_get
            QMessageBox.information = orig_info
        self.assertEqual(os.path.abspath(win.document.path), os.path.abspath(dest))
        self.assertIn("fork.pdf", win.windowTitle())


if __name__ == "__main__":
    unittest.main()
