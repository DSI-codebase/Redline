"""Launch-argument parsing for 'Open with… ▸ DSI Redline' / command-line opens."""

import os
import tempfile
import unittest

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON


@unittest.skipUnless(_QT_OK, _QT_REASON)  # its tests import `main`, which imports PySide6 (main.py:9)
class TestPdfFromArgv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.pdf = os.path.join(cls.tmp, "drawing.pdf")
        with open(cls.pdf, "wb") as fh:
            fh.write(b"%PDF-1.4\n")           # contents don't matter here
        cls.upper = os.path.join(cls.tmp, "OTHER.PDF")
        with open(cls.upper, "wb") as fh:
            fh.write(b"%PDF-1.4\n")

    def _f(self):
        from main import pdf_from_argv
        return pdf_from_argv

    def test_picks_pdf_argument(self):
        self.assertEqual(self._f()(["prog", self.pdf]), self.pdf)

    def test_skips_flags_and_finds_pdf(self):
        self.assertEqual(self._f()(["prog", "--debug", self.pdf]), self.pdf)

    def test_case_insensitive_extension(self):
        self.assertEqual(self._f()(["prog", self.upper]), self.upper)

    def test_tolerates_surrounding_quotes(self):
        self.assertEqual(self._f()(["prog", f'"{self.pdf}"']), self.pdf)

    def test_none_when_no_pdf(self):
        self.assertIsNone(self._f()(["prog", "--help"]))
        self.assertIsNone(self._f()(["prog"]))

    def test_none_when_missing_file(self):
        self.assertIsNone(self._f()(["prog", os.path.join(self.tmp, "nope.pdf")]))


if __name__ == "__main__":
    unittest.main()
