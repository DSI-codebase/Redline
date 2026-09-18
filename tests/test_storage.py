"""Tests for PDF annotation round-trip + SHX junk filter + sidecar."""

import os
import tempfile
import unittest

import fitz

from app.model.annotations import (
    Annotation, KIND_HIGHLIGHT, KIND_PEN, KIND_COMMENT, KIND_TEXTBOX, KIND_RECT,
)
from app.model.storage import (
    write_annotations_to_pdf, load_pdf_annotations, SidecarDB,
    marked_pdf_path, sidecar_path, DEFAULT_IGNORE_PATTERNS, pdf_date_to_iso,
)
from app.model.document import Document


def _blank_pdf(path):
    doc = fitz.open()
    doc.new_page(width=600, height=400)
    doc.save(path)
    doc.close()


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "draw.pdf")
        _blank_pdf(self.src)
        self.anns = [
            Annotation(page=0, kind=KIND_HIGHLIGHT, rect=(50, 50, 200, 70),
                       color=(1, 1, 0), author="Eli", text="check"),
            Annotation(page=0, kind=KIND_PEN, points=[(100, 100), (120, 130), (140, 110)],
                       color=(1, 0, 0), width=2.0, author="Eli", text="stroke"),
            Annotation(page=0, kind=KIND_COMMENT, rect=(300, 200, 316, 216),
                       text="needs review", author="Bob", is_todo=True),
            Annotation(page=0, kind=KIND_TEXTBOX, rect=(50, 250, 250, 290),
                       text="TITLE", font_size=14, author="Eli"),
            Annotation(page=0, kind=KIND_COMMENT, rect=(10, 10, 26, 26),
                       text="SHX font could not be displayed", author="AutoCAD"),
        ]

    def test_roundtrip_all_kinds(self):
        doc = fitz.open(self.src)
        n = write_annotations_to_pdf(doc, self.anns)
        self.assertEqual(n, len(self.anns))
        mp = marked_pdf_path(self.src)
        doc.save(mp)
        doc.close()

        doc2 = fitz.open(mp)
        loaded = load_pdf_annotations(doc2, DEFAULT_IGNORE_PATTERNS)
        self.assertEqual(len(loaded), len(self.anns))
        by_kind = {a.kind: a for a in loaded}
        self.assertEqual(by_kind[KIND_HIGHLIGHT].author, "Eli")
        self.assertEqual(len(by_kind[KIND_PEN].points), 3)
        self.assertEqual(by_kind[KIND_PEN].author, "Eli")

    def test_id_linkage_preserved(self):
        doc = fitz.open(self.src)
        write_annotations_to_pdf(doc, self.anns)
        mp = marked_pdf_path(self.src)
        doc.save(mp)
        doc.close()
        loaded = load_pdf_annotations(fitz.open(mp), DEFAULT_IGNORE_PATTERNS)
        self.assertEqual({a.id for a in self.anns}, {a.id for a in loaded})

    def test_shx_filter_flags_ignored(self):
        doc = fitz.open(self.src)
        write_annotations_to_pdf(doc, self.anns)
        mp = marked_pdf_path(self.src)
        doc.save(mp)
        doc.close()
        loaded = load_pdf_annotations(fitz.open(mp), DEFAULT_IGNORE_PATTERNS)
        shx = [a for a in loaded if "SHX" in a.text]
        self.assertTrue(shx and shx[0].ignored)
        # non-junk not flagged
        self.assertFalse(any(a.ignored for a in loaded if a.text == "check"))

    def test_sidecar_roundtrip(self):
        db = SidecarDB(sidecar_path(self.src))
        db.save_annotations(self.anns)
        back = db.load_annotations()
        self.assertEqual(len(back), len(self.anns))
        self.assertEqual(sum(a.is_todo for a in back), 1)
        db.close()

    def test_document_save_does_not_touch_original(self):
        before = os.path.getsize(self.src)
        doc = Document(self.src)
        doc.load()
        for a in self.anns:
            doc.store.add(a)
        out = doc.save()
        doc.close()
        self.assertTrue(out.endswith(".marked.pdf"))
        self.assertEqual(os.path.getsize(self.src), before)  # original untouched

        # reopen via sidecar persistence
        doc2 = Document(self.src)
        doc2.load()
        self.assertEqual(len(doc2.store.all()), len(self.anns))
        doc2.close()

    def test_rotated_page_export_roundtrip(self):
        """Markup on a rotated page must export to the right place and
        round-trip back to the same (visual) coordinates."""
        from app.model.annotations import KIND_RECT, KIND_PEN
        rot_src = os.path.join(self.tmp, "rot.pdf")
        d = fitz.open()
        pg = d.new_page(width=792, height=1224)   # portrait
        pg.set_rotation(270)                       # -> visual rect 1224 x 792
        d.save(rot_src)
        d.close()

        chk = fitz.open(rot_src)
        self.assertEqual(chk[0].rotation, 270)
        self.assertAlmostEqual(chk[0].rect.width, 1224, delta=1)
        chk.close()

        rect_v = (100.0, 120.0, 300.0, 180.0)      # visual-space coords
        pts_v = [(150.0, 400.0), (180.0, 430.0)]
        anns = [
            Annotation(page=0, kind=KIND_RECT, rect=rect_v, color=(1, 0, 0), width=1),
            Annotation(page=0, kind=KIND_PEN, points=pts_v, color=(0, 0, 1), width=1),
        ]
        d = fitz.open(rot_src)
        write_annotations_to_pdf(d, anns)
        mp = marked_pdf_path(rot_src)
        d.save(mp)
        d.close()

        loaded = load_pdf_annotations(fitz.open(mp), DEFAULT_IGNORE_PATTERNS)
        rect = [a for a in loaded if a.kind == KIND_RECT][0].rect
        for got, want in zip(rect, rect_v):
            self.assertAlmostEqual(got, want, delta=2.0)  # delta covers border width
        pen = [a for a in loaded if a.kind == KIND_PEN][0].points
        self.assertEqual(len(pen), len(pts_v))
        for (gx, gy), (wx, wy) in zip(pen, pts_v):
            self.assertAlmostEqual(gx, wx, delta=1.0)
            self.assertAlmostEqual(gy, wy, delta=1.0)

    def test_pdf_date_parse(self):
        iso = pdf_date_to_iso("D:20260619204609Z")
        self.assertTrue(iso.startswith("2026-06-"))

    def test_comment_exports_genuine_popup(self):
        doc = fitz.open(self.src)
        write_annotations_to_pdf(doc, [self.anns[2]])  # the comment
        mp = marked_pdf_path(self.src)
        doc.save(mp)
        doc.close()
        d = fitz.open(mp)
        notes = [a for a in d[0].annots() if a.type[1] == "Text"]
        self.assertTrue(notes)
        self.assertEqual(notes[0].info.get("content"), "needs review")
        self.assertTrue(notes[0].has_popup)

    def test_rotation_persists_via_sidecar(self):
        from app.model.annotations import KIND_RECT
        doc = Document(self.src)
        doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_RECT, rect=(10, 10, 90, 60),
                                 color=(0, 0, 1), rotation=42.0, author="Eli"))
        doc.save()
        doc.close()
        doc2 = Document(self.src)
        doc2.load()
        rects = [a for a in doc2.store.all() if a.kind == KIND_RECT]
        self.assertEqual(rects[0].rotation, 42.0)
        doc2.close()


if __name__ == "__main__":
    unittest.main()
