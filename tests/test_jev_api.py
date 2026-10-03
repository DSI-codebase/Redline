"""The TypeSafe Jev client: what it sends, when it retries, and that it never
raises.

Every test drives :func:`app.extraction.jev_api.ask` through a fake transport,
so nothing here touches the network and no test skips for want of a key. What
these prove is the plumbing; what Jev decides is measured against real sheets
(HANDOFF-JEV.md), never here.
"""

import json
import os
import unittest
from unittest import mock

from app.extraction import jev_api

KEY = "ts-test-key-0123456789"
OK_BODY = {
    "model": "jev-1.13.0",
    "answers": {"role": {"type": "choice", "choice": "bom",
                         "probabilities": {"bom": 0.9, "index": 0.1},
                         "confidence": 0.87}},
    "usage": {"input_tokens": 640, "output_tokens": 86},
}


class FakeTransport:
    """Replays ``(status, headers, body)`` tuples and records every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "body": body,
                           "headers": dict(headers)})
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


def ok(body=None):
    return (200, {}, json.dumps(body or OK_BODY).encode("utf-8"))


def ask(transport, sleeps=None, **kw):
    return jev_api.ask({"title_block": "BILL OF MATERIALS"},
                       {"role": {"type": "choice", "instructions": "x",
                                 "criteria": {"bom": "y", "index": "z"}}},
                       api_key=KEY, transport=transport,
                       sleep=(sleeps.append if sleeps is not None else lambda s: None),
                       **kw)


class TestRequestShape(unittest.TestCase):
    def test_posts_state_model_questions_to_systemone(self):
        t = FakeTransport(ok())
        self.assertEqual(ask(t)["model"], "jev-1.13.0")
        call = t.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://api.typesafe.ai/v1/systemone")
        body = json.loads(call["body"].decode("utf-8"))
        self.assertEqual(sorted(body), ["model", "questions", "state"])

    def test_the_model_is_the_pinned_version_never_an_alias(self):
        # An alias moves when a release ships, and the threshold was set
        # against one version. Inject: DEFAULT_MODEL = "jev-latest".
        t = FakeTransport(ok())
        ask(t)
        self.assertEqual(json.loads(t.calls[0]["body"])["model"], "jev-1.13.0")
        self.assertEqual(jev_api.DEFAULT_MODEL, "jev-1.13.0")

    def test_the_key_is_in_the_header_and_never_in_the_body(self):
        # Inject: put the key in `state`.
        t = FakeTransport(ok())
        ask(t)
        call = t.calls[0]
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertNotIn(KEY.encode("utf-8"), call["body"])
        self.assertGreater(len(call["body"]), 0)


class TestNeverRaises(unittest.TestCase):
    def test_a_transport_that_raises_returns_none(self):
        # Inject: remove the try around the transport call.
        t = FakeTransport(OSError("connection refused"))
        self.assertIsNone(ask(t))
        self.assertEqual(len(t.calls), 1)

    def test_a_body_that_is_not_json_returns_none(self):
        self.assertIsNone(ask(FakeTransport((200, {}, b"<html>proxy</html>"))))

    def test_a_json_body_that_is_not_an_object_returns_none(self):
        self.assertIsNone(ask(FakeTransport((200, {}, b"[1, 2]"))))

    def test_unserializable_state_returns_none_without_sending(self):
        t = FakeTransport(ok())
        self.assertIsNone(jev_api.ask({"x": object()}, {}, api_key=KEY,
                                      transport=t))
        self.assertEqual(t.calls, [])

    def test_no_key_sends_nothing(self):
        t = FakeTransport(ok())
        with mock.patch.dict(os.environ, {jev_api.ENV_KEY: ""}):
            self.assertIsNone(jev_api.ask("s", {}, api_key="", transport=t))
        self.assertEqual(t.calls, [])


class TestRetry(unittest.TestCase):
    def test_429_waits_retry_after_ms_then_succeeds(self):
        sleeps = []
        t = FakeTransport((429, {"retry-after-ms": "250", "retry-after": "9"}, b""),
                          ok())
        self.assertIsNotNone(ask(t, sleeps))
        self.assertEqual(sleeps, [0.25])          # -ms wins over seconds
        self.assertEqual(len(t.calls), 2)

    def test_retry_after_seconds_when_there_is_no_ms_header(self):
        sleeps = []
        ask(FakeTransport((529, {"retry-after": "2"}, b""), ok()), sleeps)
        self.assertEqual(sleeps, [2.0])

    def test_408_and_5xx_are_retried_with_backoff_when_no_header(self):
        sleeps = []
        t = FakeTransport((408, {}, b""), (503, {}, b""), ok())
        self.assertIsNotNone(ask(t, sleeps))
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_400_401_422_are_fatal_and_sent_once(self):
        # Inject: retry on 400.
        for code in (400, 401, 422):
            t = FakeTransport((code, {}, b'{"detail": "bad"}'), ok())
            self.assertIsNone(ask(t), code)
            self.assertEqual(len(t.calls), 1, code)

    def test_retries_are_bounded(self):
        t = FakeTransport(*[(429, {"retry-after-ms": "1"}, b"")] * 10)
        self.assertIsNone(ask(t))
        self.assertEqual(len(t.calls), jev_api.MAX_ATTEMPTS)

    def test_a_wait_longer_than_the_cap_gives_up_instead_of_blocking(self):
        sleeps = []
        t = FakeTransport((429, {"retry-after": "600"}, b""), ok())
        self.assertIsNone(ask(t, sleeps))
        self.assertEqual(sleeps, [])
        self.assertEqual(len(t.calls), 1)


class TestChoiceAnswer(unittest.TestCase):
    def test_reads_choice_confidence_probabilities_and_model(self):
        got = jev_api.choice_answer(OK_BODY, "role")
        self.assertEqual(got["choice"], "bom")
        self.assertAlmostEqual(got["confidence"], 0.87)
        self.assertEqual(got["probabilities"]["index"], 0.1)
        self.assertEqual(got["model"], "jev-1.13.0")

    def test_malformed_answers_are_none(self):
        for resp in (None, {}, {"answers": {}},
                     {"answers": {"role": {"choice": "bom"}}},
                     {"answers": {"role": {"choice": 3, "confidence": 1,
                                           "probabilities": {}}}},
                     {"answers": {"role": {"choice": "bom", "confidence": "high",
                                           "probabilities": {}}}}):
            self.assertIsNone(jev_api.choice_answer(resp, "role"), resp)


class TestKeyAndStatus(unittest.TestCase):
    def test_explicit_key_wins_over_the_environment(self):
        with mock.patch.dict(os.environ, {jev_api.ENV_KEY: "from-env"}):
            self.assertEqual(jev_api.resolve_key(" typed "), "typed")
            self.assertEqual(jev_api.resolve_key(""), "from-env")
            self.assertTrue(jev_api.available(""))

    def test_status_is_missing_without_a_key(self):
        with mock.patch.dict(os.environ, {jev_api.ENV_KEY: ""}):
            self.assertEqual(jev_api.status("")[0], "missing")
            self.assertFalse(jev_api.available(""))
        self.assertEqual(jev_api.status(KEY)[0], "present")

    def test_validate_key_lists_models_and_never_raises(self):
        t = FakeTransport((200, {}, b'{"models": []}'))
        self.assertEqual(jev_api.validate_key(KEY, transport=t),
                         (True, "Key is valid"))
        self.assertEqual(t.calls[0]["method"], "GET")
        self.assertTrue(t.calls[0]["url"].endswith("/v1/models"))
        self.assertFalse(jev_api.validate_key(
            KEY, transport=FakeTransport((401, {}, b"")))[0])
        self.assertFalse(jev_api.validate_key(
            KEY, transport=FakeTransport(OSError("down")))[0])


if __name__ == "__main__":
    unittest.main()
