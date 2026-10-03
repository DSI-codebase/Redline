"""Sheet roles decided by Jev, behind a flag that defaults off.

The keyword table (``sheet_role.ROLE_KEYWORDS``) stays the answer whenever Jev
is off, unconfigured, failing or unsure, and a role a person set is never
replaced. Jev is faked throughout: these prove what is sent, recorded and
applied, and nothing about what Jev decides.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.extraction import jev_api, sheet_role
from app.extraction.sheet_role import (
    BOM, INDEX, LAYOUT, PLC_IO, SCHEMATIC, TOPOLOGY, UNKNOWN,
    JEV_QUESTION_ID, JEV_THRESHOLD, JEV_WORDING, ROLES,
)
from app.model.document import Document
from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

TITLES = ("TITLE PAGE", "BACK PANEL LAYOUT", "24 VDC DISTRIBUTION")
KEYWORD_ROLES = {0: INDEX, 1: LAYOUT, 2: SCHEMATIC}


def _drawing(path, titles=TITLES, blank_last=False):
    doc = fitz.open()
    for title in titles:
        page = doc.new_page(width=792, height=1224)
        page.insert_text((40.0, 1000.0), title, rotate=270)
        page.set_rotation(270)
    if blank_last:
        doc.new_page(width=792, height=1224)       # a scanned sheet: no text
    doc.save(path)
    doc.close()
    return path


def _response(choice, confidence=0.95, model="jev-1.13.0"):
    return {"model": model,
            "answers": {JEV_QUESTION_ID: {
                "type": "choice", "choice": choice, "confidence": confidence,
                "probabilities": {choice: confidence}}},
            "usage": {"input_tokens": 650, "output_tokens": 86}}


class FakeJev:
    """Answers each page from a script keyed by a word in its title block."""

    def __init__(self, script):
        self.script = script
        self.states = []

    def __call__(self, state, questions, model=None, api_key=None):
        self.states.append(state)
        text = state.get("title_block", "")
        for word, reply in self.script.items():
            if word in text:
                if isinstance(reply, BaseException):
                    raise reply
                return reply
        return None


def _answer(role, confidence=0.95, model="jev-1.13.0", wording=JEV_WORDING):
    return {"role": role, "confidence": confidence, "probabilities": {},
            "model": model, "wording": wording}


class TestQuestion(unittest.TestCase):
    def test_one_choice_over_every_role_with_unknown_last(self):
        q = sheet_role.jev_question()[JEV_QUESTION_ID]
        self.assertEqual(q["type"], "choice")
        self.assertEqual(tuple(q["criteria"]), ROLES)
        self.assertEqual(list(q["criteria"])[-1], UNKNOWN)
        self.assertLessEqual(len(q["criteria"]), 255)


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = fitz.open(_drawing(os.path.join(self.tmp, "s.pdf"),
                                      blank_last=True))

    def tearDown(self):
        self.doc.close()

    def test_reads_the_title_block_the_keyword_path_reads(self):
        state = sheet_role.jev_state(self.doc[1])
        self.assertEqual(state["title_block"], "BACK PANEL LAYOUT")
        self.assertEqual(state["page_text"], "BACK PANEL LAYOUT")   # sparse

    def test_a_page_with_no_text_is_not_asked(self):
        self.assertIsNone(sheet_role.jev_state(self.doc[3]))

    def test_a_busy_page_sends_only_its_title_block(self):
        doc = fitz.open()
        page = doc.new_page(width=1224, height=792)
        page.insert_text((900.0, 760.0), "NETWORK TOPOLOGY")
        for i in range(60):
            page.insert_text((40.0, 20.0 + i * 11), "NOTE " * 4 + str(i))
        state = sheet_role.jev_state(page)
        doc.close()
        self.assertEqual(state, {"title_block": "NETWORK TOPOLOGY"})


class TestDocumentRoles(unittest.TestCase):
    """``jev_document_roles``: every branch, Jev failing mid-run included."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = fitz.open(_drawing(os.path.join(self.tmp, "s.pdf"),
                                      blank_last=True))

    def tearDown(self):
        self.doc.close()

    def test_answers_carry_role_confidence_model_and_wording(self):
        fake = FakeJev({"TITLE": _response(INDEX, 0.99)})
        got = sheet_role.jev_document_roles(self.doc, [0], ask=fake)
        self.assertEqual(got[0]["role"], INDEX)
        self.assertEqual(got[0]["model"], "jev-1.13.0")
        self.assertEqual(got[0]["wording"], JEV_WORDING)

    def test_failures_leave_pages_out_and_the_run_continues(self):
        fake = FakeJev({"TITLE": _response(INDEX),
                        "PANEL": None,                         # request failed
                        "24 VDC": RuntimeError("transport bug")})
        got = sheet_role.jev_document_roles(self.doc, [0, 1, 2, 3], ask=fake)
        self.assertEqual(sorted(got), [0])
        self.assertEqual(len(fake.states), 3)       # the blank page is not sent

    def test_a_choice_outside_the_roles_is_dropped(self):
        fake = FakeJev({"TITLE": _response("cover-sheet")})
        self.assertEqual(sheet_role.jev_document_roles(self.doc, [0], ask=fake), {})

    def test_cancel_stops_before_the_next_request(self):
        fake = FakeJev({"": _response(SCHEMATIC)})
        asked = []
        got = sheet_role.jev_document_roles(
            self.doc, [0, 1, 2], ask=fake,
            progress=lambda d, t: asked.append(d),
            should_cancel=lambda: len(asked) >= 2)
        self.assertEqual(sorted(got), [0, 1])

    def test_the_real_client_with_no_key_sends_nothing(self):
        with mock.patch.dict(os.environ, {jev_api.ENV_KEY: ""}):
            self.assertEqual(sheet_role.jev_document_roles(self.doc, [0, 1]), {})


class TestApplies(unittest.TestCase):
    def test_at_or_above_the_threshold_applies(self):
        self.assertEqual(sheet_role.jev_role_applies(_answer(BOM, JEV_THRESHOLD)), BOM)

    def test_below_the_threshold_does_not(self):
        # Inject: ignore the threshold.
        self.assertIsNone(sheet_role.jev_role_applies(_answer(BOM, JEV_THRESHOLD - 0.01)))

    def test_the_measured_wrong_band_does_not_apply(self):
        # On four real sets, 2 of the 3 answers between 0.60 and 0.75 were
        # wrong, both 0.64; none of the 100 at 0.75 or above was.
        self.assertIsNone(sheet_role.jev_role_applies(_answer(PLC_IO, 0.64)))
        self.assertEqual(sheet_role.jev_role_applies(_answer(PLC_IO, 0.75)), PLC_IO)

    def test_unknown_never_applies(self):
        self.assertIsNone(sheet_role.jev_role_applies(_answer(UNKNOWN, 1.0)))

    def test_an_answer_from_other_wording_or_another_model_is_stale(self):
        self.assertIsNone(sheet_role.jev_role_applies(
            _answer(BOM, 1.0, wording=JEV_WORDING - 1)))
        self.assertIsNone(sheet_role.jev_role_applies(
            _answer(BOM, 1.0, model="jev-1.12.0")))


class TestDocumentState(unittest.TestCase):
    """Recorded answers, the source map, and what the audit is handed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "roles.pdf"))
        self._docs = []

    def tearDown(self):
        for d in self._docs:
            d.close()

    def _open(self):
        d = Document(self.src)
        d.load()
        self._docs.append(d)
        return d

    def _reopen(self, d):
        d.close()
        self._docs.remove(d)
        return self._open()

    def test_flag_off_hands_the_audit_heads_roles(self):
        # Inject: route through Jev with the flag off.
        d = self._open()
        d.set_jev_roles({p: _answer(TOPOLOGY, 1.0) for p in range(3)})
        self.assertEqual(d.roles_for_audit(), KEYWORD_ROLES)
        self.assertEqual(d.roles_for_audit(use_jev=False), KEYWORD_ROLES)
        self.assertEqual({p: d.sheet_role_of(p) for p in range(3)}, KEYWORD_ROLES)

    def test_flag_on_applies_answers_at_or_above_the_threshold(self):
        d = self._open()
        d.set_jev_roles({0: _answer(BOM, 0.9), 2: _answer(PLC_IO, 0.8)})
        self.assertEqual(d.roles_for_audit(use_jev=True),
                         {0: BOM, 1: LAYOUT, 2: PLC_IO})

    def test_below_the_threshold_the_keyword_role_is_kept(self):
        # Inject: drop the page, or apply Jev's role anyway.
        d = self._open()
        d.set_jev_roles({1: _answer(TOPOLOGY, 0.3)})
        self.assertEqual(d.roles_for_audit(use_jev=True), KEYWORD_ROLES)

    def test_a_role_a_person_set_is_never_replaced_or_sent(self):
        # Inject: let set_jev_roles or roles_for_audit overwrite a user role.
        d = self._open()
        d.set_sheet_role(2, PLC_IO)
        self.assertEqual(d.sheet_role_source(2), "user")
        self.assertEqual(d.pages_needing_jev(), [0, 1])
        d.set_jev_roles({2: _answer(LAYOUT, 1.0)})
        self.assertEqual(d.roles_for_audit(use_jev=True)[2], PLC_IO)
        self.assertNotIn(2, d.sheet_role_jev)
        # ...and the same holds when the answer reached the sidecar some other way
        d.sheet_role_jev[2] = _answer(LAYOUT, 1.0)
        self.assertEqual(d.roles_for_audit(use_jev=True)[2], PLC_IO)

    def test_answers_and_sources_survive_reopening(self):
        d = self._open()
        d.set_sheet_role(0, BOM)
        d.set_jev_roles({1: _answer(TOPOLOGY, 0.8)})
        d = self._reopen(d)
        self.assertEqual(d.sheet_role_source(0), "user")
        self.assertEqual(d.sheet_role_source(1), "detected")
        self.assertEqual(d.roles_for_audit(use_jev=True), {0: BOM, 1: TOPOLOGY, 2: SCHEMATIC})
        self.assertEqual(d.pages_needing_jev(), [2])          # 1 is not re-asked

    def test_clearing_a_role_clears_its_source_and_hands_it_back_to_jev(self):
        d = self._open()
        d.set_sheet_role(1, PLC_IO)
        d.set_sheet_role(1, "")
        d = self._reopen(d)
        self.assertEqual(d.sheet_role_source(1), "detected")
        self.assertIn(1, d.pages_needing_jev())

    def test_a_page_with_no_text_is_never_counted_as_waiting(self):
        # It can never be answered, so counting it re-prompts on every check.
        self.src = _drawing(os.path.join(self.tmp, "scan.pdf"), blank_last=True)
        d = self._open()
        self.assertEqual(d.pages_needing_jev(), [0, 1, 2])

    def test_a_stale_answer_is_asked_again(self):
        d = self._open()
        d.set_jev_roles({0: _answer(INDEX, 1.0, model="jev-1.12.0"),
                         1: _answer(LAYOUT, 1.0)})
        self.assertEqual(d.pages_needing_jev(), [0, 2])

    def test_a_saved_role_without_a_source_is_detected_again(self):
        # What every sidecar from before sheet_role_sources holds: save()
        # wrote detected roles, and keeping them froze the keyword table of
        # the day the drawing was first saved. Inject: keep unsourced roles.
        d = self._open()
        d.sidecar.set_meta("sheet_roles", '{"1": "plc-io", "2": "plc-io"}')
        d.sidecar.set_meta("sheet_role_sources", '{"1": "user"}')
        d.sidecar.set_meta("sheet_role_jev", "")
        d = self._reopen(d)
        self.assertEqual(d.sheet_role_of(1), PLC_IO)           # a person set it
        self.assertEqual(d.sheet_role_of(2), SCHEMATIC)        # detected again
        self.assertEqual(d.sheet_role_source(2), "detected")
        self.assertEqual(d.sheet_role_jev, {})

    def test_a_corrected_keyword_table_reaches_a_drawing_saved_before_it(self):
        self.src = _drawing(os.path.join(self.tmp, "plcio.pdf"),
                            titles=("PLCIO RACK 2 WIRING DETAIL",))
        old = sheet_role.ROLE_KEYWORDS
        sheet_role.ROLE_KEYWORDS = tuple(
            (r, tuple(k for k in kws if k != "PLCIO")) for r, kws in old)
        try:
            d = self._open()
            self.assertEqual(d.sheet_role_of(0), SCHEMATIC)    # the old table
            d.save()
        finally:
            sheet_role.ROLE_KEYWORDS = old
        d = self._reopen(d)
        self.assertEqual(d.sheet_role_of(0), PLC_IO)

    def test_a_corrupt_meta_value_is_ignored(self):
        d = self._open()
        d.sidecar.set_meta("sheet_role_jev", "{not json")
        d.sidecar.set_meta("sheet_role_sources", '{"0": "jev", "1": "user"}')
        d = self._reopen(d)
        self.assertEqual(d.sheet_role_jev, {})
        # only "user" is a source; and only for a page with a saved role
        self.assertEqual(d.sheet_role_sources, {})


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestAuditWiring(unittest.TestCase):
    """``MainWindow.run_audit`` with the rule library and the worker faked, so
    the wiring is exercised whether or not PyDRC is installed."""

    _KEYS = ("jev/sheet_roles", "jev/api_key")

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.config import AppConfig
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))
        cfg = AppConfig()
        self._saved = {k: cfg.s.value(k) for k in self._KEYS}
        self.roles_seen = []
        self.patches = [
            mock.patch("app.audit.status", lambda: (True, "faked")),
            mock.patch("app.audit.runner.run_audit", self._fake_audit),
            mock.patch("app.tools.runner.run_with_progress", self._sync),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        from app.config import AppConfig
        cfg = AppConfig()
        for k, v in self._saved.items():
            if v is None:
                cfg.s.remove(k)
            else:
                cfg.s.setValue(k, v)

    def _fake_audit(self, pdf_path, labels, sources, roles, **kw):
        self.roles_seen.append(dict(roles))
        return None                               # done() returns early on None

    @staticmethod
    def _sync(parent, title, fn, on_done, on_error=None):
        on_done(fn(lambda d, t: None, lambda: False))

    def _window(self, jev_on, key=""):
        from app.main_window import MainWindow
        win = MainWindow()
        win.config.set("jev/sheet_roles", jev_on)
        win.config.set("jev/api_key", key)
        win.load_document(self.src)
        return win

    def _run(self, win, reply, script):
        from PySide6.QtWidgets import QMessageBox
        fake = FakeJev(script)
        with mock.patch.object(QMessageBox, "question", return_value=reply) as q, \
                mock.patch.object(QMessageBox, "information") as info, \
                mock.patch.object(jev_api, "ask", fake):
            win.run_audit()
        return fake, q, info

    def test_flag_off_sends_nothing_and_audits_keyword_roles(self):
        from PySide6.QtWidgets import QMessageBox
        win = self._window(False, "k")
        fake, q, _info = self._run(win, QMessageBox.Yes, {"": _response(BOM)})
        self.assertEqual(fake.states, [])
        q.assert_not_called()
        self.assertEqual(self.roles_seen, [KEYWORD_ROLES])
        win.close()

    def test_flag_on_asks_then_audits_jev_roles_and_keeps_answers(self):
        from PySide6.QtWidgets import QMessageBox
        win = self._window(True, "k")
        win.document.set_sheet_role(0, BOM)
        fake, q, _info = self._run(win, QMessageBox.Yes, {
            "PANEL": _response(TOPOLOGY, 0.9),
            "24 VDC": _response(PLC_IO, 0.2)})        # below the threshold
        q.assert_called_once()
        self.assertIn("TypeSafe", q.call_args[0][2])
        self.assertEqual(len(fake.states), 2)       # the user-set page is not sent
        self.assertEqual(self.roles_seen, [{0: BOM, 1: TOPOLOGY, 2: SCHEMATIC}])
        self.assertEqual(sorted(win.document.sheet_role_jev), [1, 2])
        # a second check sends nothing: every page has a current answer
        fake2, q2, _ = self._run(win, QMessageBox.Yes, {"": _response(BOM)})
        self.assertEqual(fake2.states, [])
        q2.assert_not_called()
        self.assertEqual(self.roles_seen[-1], {0: BOM, 1: TOPOLOGY, 2: SCHEMATIC})
        win.close()

    def test_declining_runs_the_check_with_keyword_roles(self):
        from PySide6.QtWidgets import QMessageBox
        win = self._window(True, "k")
        fake, _q, _info = self._run(win, QMessageBox.No, {"": _response(BOM)})
        self.assertEqual(fake.states, [])
        self.assertEqual(self.roles_seen, [KEYWORD_ROLES])
        self.assertEqual(win.document.sheet_role_jev, {})
        win.close()

    def test_no_key_says_so_and_runs_with_keyword_roles(self):
        from PySide6.QtWidgets import QMessageBox
        with mock.patch.dict(os.environ, {jev_api.ENV_KEY: ""}):
            win = self._window(True, "")
            fake, q, info = self._run(win, QMessageBox.Yes, {"": _response(BOM)})
        info.assert_called_once()
        q.assert_not_called()
        self.assertEqual(fake.states, [])
        self.assertEqual(self.roles_seen, [KEYWORD_ROLES])
        win.close()


if __name__ == "__main__":
    unittest.main()
