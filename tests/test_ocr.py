"""The app's calls into ``pytesseract`` at the installed release, with a
stand-in for the Tesseract binary.

No test imported pytesseract before these, so the ``floors`` job installed
0.3.10 and ran nothing that used it. The workflows install no Tesseract
binary, and without one ``ocr.available()`` answers False and every OCR path
in the app returns nothing.

The stand-in is ``tests/_tesseract_stand_in.py``, run as a real process.
pytesseract is pointed at it through ``tesseract_cmd``, its documented
setting, so every line of pytesseract between the app and the binary runs:
the version check, the image saved to a temporary file, the command line, the
output file read back, and the TSV parsed into the dict ``ocr`` reads.

Windows will not start a ``.py`` file as a program, so ``subprocess.Popen``
is wrapped to start the interpreter on the stand-in when, and only when, the
program named is ``_PROGRAM``. Nothing by that name exists.
If the wrapper stops applying, pytesseract reports the binary missing and
these tests fail. They cannot reach a real Tesseract by accident.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import pymupdf

from app.extraction import ocr
from app.extraction.wire_parser import SOURCE_OCR
from app.tools import pdf_ops

try:
    import pytesseract
    _HAVE_PYTESSERACT = True
except Exception:
    pytesseract = None
    _HAVE_PYTESSERACT = False

# Names the library, so tools/run_tests.py prints this skip as its own line.
_NO_WRAPPER = "needs pytesseract, which is not installed"
_STAND_IN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "_tesseract_stand_in.py")
_PROGRAM = "redline-tesseract-stand-in"

# What Tesseract 5 writes as TSV for a 600 x 300 px image: one row for the
# page and for each block, paragraph and line, with conf -1 and no text, then
# one row per word. The two lines sit in different blocks, each numbered
# line 1, which is how Tesseract numbers them. Every pixel value is three
# times the PDF points the tests expect back, because ocr_page renders at
# DEFAULT_OCR_ZOOM, which is 3.
_TSV_HEADER = ("level", "page_num", "block_num", "par_num", "line_num",
               "word_num", "left", "top", "width", "height", "conf", "text")
_TSV_ROWS = (
    (1, 1, 0, 0, 0, 0, 0, 0, 600, 300, "-1", ""),
    (2, 1, 1, 0, 0, 0, 30, 60, 390, 45, "-1", ""),
    (3, 1, 1, 1, 0, 0, 30, 60, 390, 45, "-1", ""),
    (4, 1, 1, 1, 1, 0, 30, 60, 390, 45, "-1", ""),
    (5, 1, 1, 1, 1, 1, 30, 60, 120, 45, "96.517265", "432141"),
    (5, 1, 1, 1, 1, 2, 300, 60, 120, 45, "54.250000", "43214l"),
    (5, 1, 1, 1, 1, 3, 450, 60, 30, 45, "95.000000", ""),
    (2, 1, 2, 0, 0, 0, 30, 165, 360, 45, "-1", ""),
    (3, 1, 2, 1, 0, 0, 30, 165, 360, 45, "-1", ""),
    (4, 1, 2, 1, 1, 0, 30, 165, 360, 45, "-1", ""),
    (5, 1, 2, 1, 1, 1, 30, 165, 120, 45, "88.000000", "CR-301"),
    (5, 1, 2, 1, 1, 2, 300, 165, 90, 45, "91.250000", "TB1"),
)
_TSV = "".join("\t".join(str(v) for v in row) + "\n"
               for row in (_TSV_HEADER,) + _TSV_ROWS)

# Each word with text, in points, and the confidence ocr_page reports.
# pytesseract 0.3.10 and 0.3.13 both hand back conf as int(float(...)), so
# 96.517265 arrives as 96 (read 2026-11-01). The delta in the assertions
# allows either, because the app reads it with float() and must not care.
_WORDS = (
    ("432141", 10.0, 20.0, 40.0, 15.0, 0.96),
    ("43214l", 100.0, 20.0, 40.0, 15.0, 0.54),
    ("CR-301", 10.0, 55.0, 40.0, 15.0, 0.88),
    ("TB1", 100.0, 55.0, 30.0, 15.0, 0.91),
)


def _forget_the_version():
    """Clear the Tesseract version pytesseract keeps for the process.

    0.3.10 runs ``tesseract --version`` once per process and never again.
    0.3.13 runs it again unless the caller passes ``cached=True``, which
    ``image_to_data`` does (both read 2026-11-01). Without this, a test that
    changes the binary is answered about the one a previous test used.
    """
    remembered = pytesseract.pytesseract.get_tesseract_version
    remembered._result = remembered


def _install_stand_in(test, tsv="", txt="", version=None):
    """Point pytesseract at the stand-in until ``test`` ends.

    The stand-in answers with ``tsv`` or ``txt``, and answers ``--version``
    with ``version`` when one is given. Returns a function that lists the
    stand-in's runs, one dict per OCR call, version checks excluded.
    """
    workdir = tempfile.mkdtemp(prefix="redline-tesseract-")
    test.addCleanup(shutil.rmtree, workdir, True)
    answers = [("answer.tsv", tsv), ("answer.txt", txt)]
    if version is not None:
        answers.append(("version.txt", version))
    for name, text in answers:
        with open(os.path.join(workdir, name), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(text)

    real_popen = subprocess.Popen

    def popen(args, *more, **kwargs):
        if isinstance(args, (list, tuple)) and args and args[0] == _PROGRAM:
            args = [sys.executable, _STAND_IN, workdir, *args[1:]]
        return real_popen(args, *more, **kwargs)

    for patcher in (
            mock.patch.object(pytesseract.pytesseract, "tesseract_cmd",
                              _PROGRAM),
            mock.patch.object(subprocess, "Popen", popen)):
        patcher.start()
        test.addCleanup(patcher.stop)
    _forget_the_version()
    test.addCleanup(_forget_the_version)

    def runs():
        path = os.path.join(workdir, "runs.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    return runs


def _blank_page(test, width, height):
    doc = pymupdf.open()
    test.addCleanup(doc.close)
    return doc.new_page(width=width, height=height)


@unittest.skipUnless(_HAVE_PYTESSERACT, _NO_WRAPPER)
class TestAvailableAsksForTheBinary(unittest.TestCase):
    def setUp(self):
        _forget_the_version()
        self.addCleanup(_forget_the_version)

    def test_the_wrapper_alone_is_not_enough(self):
        with mock.patch.object(pytesseract.pytesseract, "tesseract_cmd",
                               _PROGRAM + "-absent"):
            self.assertFalse(
                ocr.available(),
                "OCR reported available with no Tesseract binary. If the "
                "app still asks for the version, pytesseract answered from "
                "a version it kept, and _forget_the_version no longer "
                "clears it.")

        _install_stand_in(self)
        self.assertTrue(ocr.available())

    # pytesseract 0.3.10 and 0.3.13 raise SystemExit, which is not an
    # Exception, from get_tesseract_version() when --version does not parse
    # or parses below 3.05 (both read 2026-11-01).
    def test_a_version_that_does_not_parse_is_unavailable(self):
        self._assert_unavailable_answering("tesseract v-unknown\n")

    def test_a_version_below_3_05_is_unavailable(self):
        self._assert_unavailable_answering("tesseract 3.04\n")

    def _assert_unavailable_answering(self, version):
        _install_stand_in(self, version=version)
        _forget_the_version()
        try:
            reported = ocr.available()
        except SystemExit as exc:
            self.fail(f"ocr.available() raised {exc!r} for a binary "
                      f"answering --version with {version!r}, where it "
                      "should report OCR unavailable.")
        self.assertFalse(
            reported,
            f"OCR reported available for a binary answering --version with "
            f"{version!r}. If the stand-in answered 5.3.4 instead, it no "
            "longer reads version.txt.")

    def test_an_interrupt_is_not_swallowed(self):
        with mock.patch.object(pytesseract, "get_tesseract_version",
                               side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ocr.available()


@unittest.skipUnless(_HAVE_PYTESSERACT, _NO_WRAPPER)
class TestAScannedPageIsReadThroughImageToData(unittest.TestCase):
    def setUp(self):
        self.runs = _install_stand_in(self, tsv=_TSV)
        self.page = _blank_page(self, 200, 100)

    def test_every_word_comes_back_at_its_place_on_the_page(self):
        tokens = ocr.ocr_page(self.page, 3)

        self.assertEqual(
            [(t.text, t.x, t.y, t.w, t.h) for t in tokens],
            [w[:5] for w in _WORDS])
        for token, word in zip(tokens, _WORDS):
            self.assertAlmostEqual(token.confidence, word[5], delta=0.01,
                                   msg=token.text)
            self.assertEqual((token.page, token.source), (3, SOURCE_OCR))
        # One OCR run, asking for TSV, on a PNG of the page at the OCR zoom.
        self.assertEqual(self.runs(), [
            {"output": "tsv", "png": True, "size": [600, 300]}])

    def test_min_conf_keeps_a_word_at_the_threshold(self):
        tokens = ocr.ocr_page(self.page, 0, min_conf=88)
        self.assertEqual([t.text for t in tokens],
                         ["432141", "CR-301", "TB1"])

    def test_low_confidence_is_judged_on_tesseracts_0_to_100_scale(self):
        tokens = ocr.ocr_page(self.page, 0)
        self.assertEqual(
            [(t.text, ocr.is_low_confidence(t)) for t in tokens],
            [("432141", False), ("43214l", True), ("CR-301", False),
             ("TB1", False)])

    def test_a_cropped_region_comes_back_as_its_table(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 600, 300),
                             False)
        pix.clear_with(255)
        self.assertEqual(ocr.ocr_structured(pix), {
            "type": "table", "title": "", "text": "",
            "rows": [["432141", "43214l"], ["CR-301", "TB1"]]})


@unittest.skipUnless(_HAVE_PYTESSERACT, _NO_WRAPPER)
class TestTheSplitWizardReadsAScannedBoxThroughImageToString(unittest.TestCase):
    def test_a_box_with_no_text_layer_is_read_by_ocr(self):
        # Tesseract ends plain-text output with a form feed.
        runs = _install_stand_in(self, txt="SHEET 432\n\f")
        page = _blank_page(self, 200, 100)

        text = pdf_ops.read_region_text(page, (10, 10, 60, 30), ocr=True)

        self.assertEqual(text, "SHEET 432")
        # The box alone, 50 x 20 pt, rendered at 3x.
        self.assertEqual(runs(), [
            {"output": "txt", "png": True, "size": [150, 60]}])


if __name__ == "__main__":
    unittest.main()
