"""Tests for the optional Claude assist helpers (no network)."""

import base64
import contextlib
import importlib
import json
import os
import unittest
from unittest import mock

import pymupdf

from app.extraction import claude_api

try:
    import anthropic
    _HAVE_ANTHROPIC = True
except Exception:
    anthropic = None
    _HAVE_ANTHROPIC = False

# Names the library, so tools/run_tests.py prints this skip as its own line.
_NO_SDK = "needs the anthropic SDK, which is not installed"
_KEY = "sk-ant-test-not-a-real-key"

# The SDK reads each of these from the environment, and each one changes the
# request under test: another host, another credential, another header. A
# developer's shell can set any of them, so the request tests run without them.
_SDK_ENVIRONMENT = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                    "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS")


def _http_package():
    """The HTTP package the installed SDK builds its client on.

    Asked of the SDK rather than written here, because it moved inside the
    range ``requirements.txt`` allows: anthropic 0.40 builds on ``httpx``, and
    2.3.0 builds on ``httpx2`` and does not install ``httpx`` at all (both
    read 2026-11-01). A test that imported ``httpx`` by name, or handed the
    client an ``httpx.MockTransport``, would error at the newest release.
    """
    for cls in anthropic.DefaultHttpxClient.__mro__:
        package = cls.__module__.partition(".")[0]
        if package != "anthropic" and cls.__name__ == "Client":
            return importlib.import_module(package)
    raise AssertionError("anthropic.DefaultHttpxClient derives from no HTTP "
                         "Client class, so there is no transport to patch")


@contextlib.contextmanager
def _anthropic_answers(status, body):
    """Answer every request the SDK sends with ``status`` and JSON ``body``.

    Yields the list each request is appended to. The patch is on the HTTP
    package's own ``HTTPTransport.handle_request``, so the app's
    ``anthropic.Anthropic(api_key=key)`` is built exactly as the app builds
    it, default HTTP client included. Passing ``http_client=`` instead would
    replace the SDK's own client construction, which is the step a new
    release of the SDK or of its HTTP package is most likely to break.
    """
    http = _http_package()
    sent = []

    def answer(request):
        sent.append(request)
        return http.Response(status, json=body)

    transport = http.MockTransport(answer)

    def handle_request(_self, request):
        return transport.handle_request(request)

    with mock.patch.object(http.HTTPTransport, "handle_request",
                           handle_request):
        yield sent


def _message(text):
    """A Messages API response carrying one text block."""
    return {
        "id": "msg_test", "type": "message", "role": "assistant",
        "model": claude_api.DEFAULT_MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _pixmap(width, height):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height),
                         False)
    pix.clear_with(255)
    return pix


class TestClaudeApi(unittest.TestCase):
    def test_resolve_key_prefers_explicit(self):
        self.assertEqual(claude_api.resolve_key("sk-explicit"), "sk-explicit")

    def test_resolve_key_env_fallback(self):
        old = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "sk-env"
        try:
            self.assertEqual(claude_api.resolve_key(""), "sk-env")
            self.assertEqual(claude_api.resolve_key(None), "sk-env")
        finally:
            if old is None:
                del os.environ["ANTHROPIC_API_KEY"]
            else:
                os.environ["ANTHROPIC_API_KEY"] = old

    def test_status_states(self):
        state, msg = claude_api.status("")  # no explicit key
        self.assertIn(state, ("no_sdk", "missing", "present"))
        self.assertTrue(msg)

    def test_available_requires_key(self):
        # with the SDK possibly absent and no key, never available
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            self.assertFalse(claude_api.available(""))
        finally:
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old

    def test_read_region_graceful_without_key(self):
        # returns [] rather than raising when no key/SDK
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            self.assertEqual(claude_api.read_wire_region(None, api_key=""), [])
        finally:
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old


@unittest.skipUnless(_HAVE_ANTHROPIC, _NO_SDK)
class TestTheInstalledSdkCarriesTheAppsCalls(unittest.TestCase):
    """The app's calls into ``anthropic`` through a real client, with only the
    HTTP transport answered in-process.

    ``TestClaudeApi`` passes with the SDK absent and never builds a client, so
    the ``floors`` job installed anthropic 0.40 and ran nothing that used it.
    Every entry point in ``claude_api`` returns ``[]``, ``""`` or ``False`` on
    any exception, so a call the installed SDK refuses looks exactly like a
    model that found nothing. Each test asserts that one request was SENT, and
    what it carried, before it reads the result.
    """

    def setUp(self):
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for name in _SDK_ENVIRONMENT:
            os.environ.pop(name, None)

    def _the_one_request(self, sent):
        self.assertEqual(
            len(sent), 1,
            f"the SDK sent {len(sent)} requests. None means the call raised "
            "before anything was sent, and claude_api swallowed the error.")
        return sent[0], json.loads(sent[0].content)

    def test_read_wire_region_sends_the_region_and_parses_the_reply(self):
        pix = _pixmap(40, 20)
        wire = {"label": "432141", "is_wire": True, "confidence": 0.97,
                "bbox": [1, 2, 30, 12]}
        # Fenced, as a model often answers whatever the prompt asks.
        reply = "```json\n" + json.dumps([wire]) + "\n```"
        with _anthropic_answers(200, _message(reply)) as sent:
            got = claude_api.read_wire_region(pix, api_key=_KEY)

        request, body = self._the_one_request(sent)
        self.assertEqual(
            (request.method, request.url.host, request.url.path),
            ("POST", "api.anthropic.com", "/v1/messages"))
        # anthropic 0.40 sends the key as x-api-key and 2.3.0 sends it as
        # "Authorization: Bearer" (read 2026-11-01). Either way it must be
        # the key the app was handed.
        credential = (request.headers.get("x-api-key")
                      or request.headers.get("authorization", "")
                      .removeprefix("Bearer "))
        self.assertEqual(credential, _KEY)
        self.assertEqual(body["model"], claude_api.DEFAULT_MODEL)
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual(body["messages"], [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png",
                                         "data": mock.ANY}},
            {"type": "text", "text": mock.ANY},
        ]}])
        image, prompt = body["messages"][0]["content"]
        self.assertEqual(base64.b64decode(image["source"]["data"]),
                         pix.tobytes("png"))
        self.assertIn("The image is 40x20 pixels.", prompt["text"])
        self.assertIn("sheet (3 digits), rung (2 digits, zero-padded)",
                      prompt["text"])

        self.assertEqual(got, [wire])

    def test_validate_key_tells_a_valid_key_from_a_rejected_one(self):
        with _anthropic_answers(200, _message("pong")) as sent:
            self.assertEqual(claude_api.validate_key(_KEY),
                             (True, "Key is valid"))
        _, body = self._the_one_request(sent)
        self.assertEqual(body["max_tokens"], 1)
        self.assertEqual(body["messages"],
                         [{"role": "user", "content": "ping"}])

        rejected = {"type": "error", "error": {
            "type": "authentication_error", "message": "invalid x-api-key"}}
        with _anthropic_answers(401, rejected) as sent:
            self.assertEqual(claude_api.validate_key(_KEY),
                             (False, "Invalid API key (authentication failed)"))
        # The SDK does not retry a 401, so one request is the whole exchange.
        self._the_one_request(sent)

    def test_tag_descriptions_sends_every_crop_in_order(self):
        # Two widths, so two different PNGs, so the order is checkable.
        crops = [_pixmap(30, 10), _pixmap(50, 10)]
        rows = [{"tag": "MTR_101", "description": "MOTOR 101"},
                {"tag": "PB_2", "description": "PUSH BUTTON 2"}]
        with _anthropic_answers(200, _message(json.dumps(rows))) as sent:
            got = claude_api.tag_descriptions(
                crops, extra_prompt="Prefix each tag with the area.",
                api_key=_KEY)

        _, body = self._the_one_request(sent)
        content = body["messages"][0]["content"]
        self.assertEqual([b["type"] for b in content],
                         ["image", "image", "text"])
        self.assertEqual(
            [base64.b64decode(b["source"]["data"]) for b in content[:2]],
            [p.tobytes("png") for p in crops])
        self.assertTrue(content[2]["text"].startswith(claude_api.TAG_PROMPT))
        self.assertTrue(
            content[2]["text"].endswith("Prefix each tag with the area."))

        self.assertEqual(got, rows)


if __name__ == "__main__":
    unittest.main()
