"""Importing source drawings: discovery, conversion, reading, persistence.

The ODA File Converter is exercised through a fake runner -- the real one is a
user-installed executable, found rather than bundled, exactly as OCR finds
Tesseract.  Reading uses tiny synthetic DXFs when ezdxf is available.
"""

import os
import tempfile
import time
import unittest

from app.audit import project_import as pi
from app.extraction.wire_parser import WireConfig, WireParser, Token, parse_label

try:
    import ezdxf
    HAVE_EZDXF = True
except Exception:
    HAVE_EZDXF = False

try:
    import pydrc  # noqa: F401
    HAVE_PYDRC = True
except Exception:
    HAVE_PYDRC = False


def _touch(path, mtime=None):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("x")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _make_dxf(path, sheet="300", tag="FU-30014", claim="300290"):
    """A one-component ACADE-shaped drawing (only used when ezdxf exists)."""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    blk = doc.blocks.new("WD_M")
    for t in ("SHEET", "WIRELAYS", "WIREFMT"):
        blk.add_attdef(t).dxf.insert = (0, 0)
    msp.add_blockref("WD_M", (0, 0)).add_auto_attribs(
        {"SHEET": sheet, "WIRELAYS": "BLU*", "WIREFMT": "%S%N"})
    comp = doc.blocks.new("HFU1")
    for t in ("TAG1", "FAMILY", "RATING1", "X1TERM02"):
        comp.add_attdef(t).dxf.insert = (0, 0)
    msp.add_blockref("HFU1", (5, 18)).add_auto_attribs(
        {"TAG1": tag, "FAMILY": "FU", "RATING1": "16 A", "X1TERM02": claim})
    wn = doc.blocks.new("WD_WNH")
    wn.add_attdef("WIRENO").dxf.insert = (0, 0)
    msp.add_blockref("WD_WNH", (3, 18.2)).add_auto_attribs({"WIRENO": "300140"})
    msp.add_line((1, 18), (4.6, 18), dxfattribs={"layer": "BLU_#14"})
    doc.saveas(path)


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_dxf_beside_its_dwg_is_used(self):
        now = time.time()
        _touch(os.path.join(self.tmp, "a.dwg"), now - 100)
        _touch(os.path.join(self.tmp, "a.dxf"), now)
        plan = pi.plan_import(self.tmp)
        self.assertEqual(len(plan.usable_dxfs), 1)
        self.assertEqual(plan.needs_conversion, [])

    def test_a_stale_dxf_is_treated_as_absent(self):
        # Auditing last month's conversion of this month's drawing produces
        # confident findings about the wrong revision.
        now = time.time()
        _touch(os.path.join(self.tmp, "a.dxf"), now - 100)
        _touch(os.path.join(self.tmp, "a.dwg"), now)
        plan = pi.plan_import(self.tmp)
        self.assertEqual(plan.usable_dxfs, [])
        self.assertEqual(len(plan.needs_conversion), 1)

    def test_a_fresh_cached_conversion_is_reused(self):
        now = time.time()
        _touch(os.path.join(self.tmp, "a.dwg"), now - 100)
        cache = os.path.join(self.tmp, pi.CACHE_DIR_NAME)
        os.makedirs(cache)
        _touch(os.path.join(cache, "a.dxf"), now)
        plan = pi.plan_import(self.tmp)
        self.assertEqual(len(plan.usable_dxfs), 1)
        self.assertIn(pi.CACHE_DIR_NAME, plan.usable_dxfs[0])

    def test_dxf_without_any_dwg_is_used(self):
        _touch(os.path.join(self.tmp, "a.dxf"))
        plan = pi.plan_import(self.tmp)
        self.assertEqual(len(plan.usable_dxfs), 1)

    def test_empty_directory(self):
        self.assertTrue(pi.plan_import(self.tmp).empty)


class TestConvert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _touch(os.path.join(self.tmp, "a.dwg"))
        self.plan = pi.plan_import(self.tmp)

    def test_invokes_the_converter_and_collects_output(self):
        calls = []

        def fake_runner(args):
            calls.append(args)
            out_dir = args[2]
            _touch(os.path.join(out_dir, "a.dxf"))

        converted, errors = pi.convert(self.plan, "/fake/ODAFileConverter",
                                       runner=fake_runner)
        self.assertEqual(len(converted), 1)
        self.assertEqual(errors, [])
        self.assertEqual(calls[0][0], "/fake/ODAFileConverter")
        self.assertEqual(calls[0][1], self.tmp)                # input dir
        self.assertIn("DXF", calls[0])

    def test_missing_output_is_an_error_per_drawing(self):
        converted, errors = pi.convert(self.plan, "/fake/conv",
                                       runner=lambda args: None)
        self.assertEqual(converted, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("a.dwg", errors[0])

    def test_a_crashing_converter_is_an_error_not_an_exception(self):
        def boom(args):
            raise OSError("no such executable")

        converted, errors = pi.convert(self.plan, "/fake/conv", runner=boom)
        self.assertEqual(converted, [])
        self.assertTrue(errors and "Converter failed" in errors[0])


class TestFindConverter(unittest.TestCase):
    def test_a_configured_path_wins(self):
        with tempfile.NamedTemporaryFile() as fh:
            self.assertEqual(pi.find_converter(fh.name), fh.name)

    def test_a_configured_path_that_does_not_exist_is_ignored(self):
        got = pi.find_converter("/no/such/converter")
        self.assertIsInstance(got, str)


@unittest.skipUnless(HAVE_EZDXF and HAVE_PYDRC, "needs ezdxf and pydrc")
class TestImportProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_reads_a_directory_of_dxfs(self):
        _make_dxf(os.path.join(self.tmp, "EL2507777-300.dxf"))
        result = pi.import_project(self.tmp)
        self.assertEqual(result.sheets_read, 1)
        self.assertEqual(result.wire_format, "%S%N")
        self.assertTrue(result.model_json)
        self.assertIn("FU-30014", result.model_json)

    def test_dwgs_without_a_converter_get_a_clear_message(self):
        _touch(os.path.join(self.tmp, "only.dwg"))
        result = pi.import_project(self.tmp, converter_path="/no/such")
        self.assertEqual(result.sheets_read, 0)
        self.assertTrue(any("ODA File Converter" in e for e in result.errors))

    def test_an_empty_directory_says_so(self):
        result = pi.import_project(self.tmp)
        self.assertTrue(any("No DWG or DXF" in e for e in result.errors))

    def test_summary_reads_sensibly(self):
        _make_dxf(os.path.join(self.tmp, "EL2507777-300.dxf"))
        result = pi.import_project(self.tmp)
        self.assertIn("Read 1 drawing", result.summary())


@unittest.skipUnless(HAVE_EZDXF and HAVE_PYDRC, "needs ezdxf and pydrc")
class TestDocumentPersistence(unittest.TestCase):
    def test_import_survives_a_reopen(self):
        import fitz
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "a.pdf")
        pdf = fitz.open()
        pdf.new_page(width=612, height=792).insert_text((72, 72), "x")
        pdf.save(src)
        pdf.close()

        doc = Document(src)
        doc.load()
        doc.set_acade_import('{"schema": "pydrc.model/1.0"}', "%S%N")
        doc.close()

        again = Document(src)
        again.load()
        self.assertEqual(again.acade_wire_format, "%S%N")
        self.assertIn("pydrc.model", again.acade_model_json)
        again.close()


class TestUnpaddedRung(unittest.TestCase):
    """The %S%N wire format writes the line number unpadded."""

    def test_off_by_default(self):
        self.assertIsNone(parse_label("30080", WireConfig()))

    def test_variable_widths_parse(self):
        cfg = WireConfig(unpadded_rung=True)
        self.assertEqual(parse_label("30080", cfg), (300, 8, 0))
        self.assertEqual(parse_label("300140", cfg), (300, 14, 0))

    def test_too_short_and_too_long_stay_out(self):
        cfg = WireConfig(unpadded_rung=True)
        self.assertIsNone(parse_label("3001", cfg))
        self.assertIsNone(parse_label("3000000", cfg))

    def test_the_parser_accepts_both_widths_from_tokens(self):
        cfg = WireConfig(unpadded_rung=True)
        tokens = [Token(text="30080", x=1, y=1, page=0),
                  Token(text="300140", x=2, y=1, page=0)]
        wires = WireParser(cfg).parse(tokens)
        self.assertEqual({w.label for w in wires}, {"30080", "300140"})
        self.assertTrue(all(w.is_conforming for w in wires))


if __name__ == "__main__":
    unittest.main()
