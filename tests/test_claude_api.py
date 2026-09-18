"""Tests for the optional Claude assist helpers (no network)."""

import os
import unittest

from app.extraction import claude_api


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


if __name__ == "__main__":
    unittest.main()
