"""A rule pack that will not load is named in Settings, with the reason.

PyDRC 0.19.0 refuses ``enabled`` on a rule. A user pack that set it loaded
under 0.18.0 and now raises ``PackError``. ``available_packs`` and
``available_rules`` dropped the failure with a bare ``continue``, so the pack
and its rules left the Design rules tab without a word, while a check that ran
the pack stopped in "Design rule check failed" with the reason.
"""

import os
import shutil
import tempfile
import unittest

from app import audit
from tests._qt import QT_OK

HAVE_PYDRC = audit.available()

#: The pack's id and its file name differ on purpose: the loader's message
#: names the file, so a pack id spelled like it would be "named" by the
#: message alone and the assertions below could not tell.
PACK_ID = "switched-off"
PACK_FILE = "user-pack.yaml"
#: A rule switched off in its own pack: the key 0.19.0 refuses.
PACK_TEXT = (f"pack: {{id: {PACK_ID}, version: 1.0.0, title: Switched off}}\n"
             "rules:\n"
             "  - {id: SWITCHED-RULE-001, entity: device, enabled: false,"
             " check: {fn: expect, args: {predicate:"
             " {field: tag, op: is_not_null}}}, message: x}\n")
PROBLEM = "unexpected keys ['enabled']"


class _UserPack(unittest.TestCase):
    """A temporary ``PYDRC_PACK_PATH`` holding that pack, for each test."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pack_path = os.path.join(self.dir, PACK_FILE)
        with open(self.pack_path, "w", encoding="utf-8") as fh:
            fh.write(PACK_TEXT)
        self.saved_path = os.environ.get("PYDRC_PACK_PATH")
        os.environ["PYDRC_PACK_PATH"] = self.dir

    def tearDown(self):
        if self.saved_path is None:
            os.environ.pop("PYDRC_PACK_PATH", None)
        else:
            os.environ["PYDRC_PACK_PATH"] = self.saved_path
        shutil.rmtree(self.dir, ignore_errors=True)


@unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")
class TestTheRunnerNamesAPackThatWillNotLoad(_UserPack):
    def test_the_library_finds_the_pack(self):
        """Else every test here passes on a pack nobody looked for."""
        from pydrc.packs import loader
        from app.audit.runner import user_pack_dirs
        self.assertIn(PACK_ID, loader.discover(user_pack_dirs()))

    def test_it_is_named_with_the_loaders_reason(self):
        """Injected: the bare ``continue`` restored in ``_load_each`` (red)."""
        from app.audit.runner import available_packs, unloadable_packs
        failed = dict(unloadable_packs())
        self.assertIn(PACK_ID, failed)
        self.assertIn(PROBLEM, failed[PACK_ID])
        self.assertNotIn(PACK_ID, [p[0] for p in available_packs()])

    def test_the_reason_is_the_one_the_check_stops_with(self):
        import fitz
        from app.audit.runner import run_audit, unloadable_packs
        pdf = os.path.join(self.dir, "blank.pdf")
        doc = fitz.open()
        doc.new_page()
        doc.save(pdf)
        doc.close()
        with self.assertRaises(Exception) as raised:
            run_audit(pdf, {}, {}, {}, pack_ids=[PACK_ID])
        self.assertEqual(dict(unloadable_packs())[PACK_ID], str(raised.exception))

    def test_a_pack_the_check_names_and_the_library_cannot_find(self):
        from app.audit.runner import unloadable_packs
        failed = dict(unloadable_packs(["gone"]))
        self.assertIn("no rule pack named 'gone'", failed["gone"])

    def test_a_pack_that_loads_is_not_named(self):
        from app.audit.runner import available_packs, default_packs, unloadable_packs
        self.assertGreaterEqual(len(available_packs()), 4)
        self.assertEqual(set(dict(unloadable_packs(default_packs()))), {PACK_ID})


@unittest.skipUnless(QT_OK and HAVE_PYDRC, "needs PySide6 and PyDRC")
class TestSettingsNamesAPackThatWillNotLoad(_UserPack):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app.config import AppConfig
        self.config = AppConfig()
        self.saved_packs = self.config.audit_packs()
        self.config.set_audit_packs([])

    def tearDown(self):
        self.config.set_audit_packs(self.saved_packs)
        self.config.sync()
        super().tearDown()

    def _dialog(self):
        from app.settings_dialog import SettingsDialog
        return SettingsDialog(self.config)

    def test_the_tab_names_the_pack_and_the_problem(self):
        """Injected: the bare ``continue`` restored in ``_load_each`` (red)."""
        dlg = self._dialog()
        text = dlg.drc_pack_failed.text()
        self.assertIn(f"{PACK_ID} will not load", text)
        self.assertIn(PROBLEM, text)
        self.assertNotIn(PACK_ID, dict(dlg.drc_packs))

    def test_a_saved_pack_the_library_no_longer_finds_is_named(self):
        self.config.set_audit_packs(["drc-base", "gone"])
        text = self._dialog().drc_pack_failed.text()
        self.assertIn("gone will not load", text)
        self.assertIn("no rule pack named 'gone'", text)

    def test_with_every_pack_loading_the_tab_says_nothing(self):
        os.remove(self.pack_path)
        dlg = self._dialog()
        self.assertGreaterEqual(len(dlg.drc_packs), 4)
        self.assertEqual(dlg.drc_pack_failed.text(), "")


if __name__ == "__main__":
    unittest.main()
