"""Optional TypeSafe Jev client - strictly opt-in.

Jev is TypeSafe's System One model: it takes a ``state`` and typed questions
and returns typed answers with probabilities, rather than prose to be parsed.
Used to decide each sheet's role from the text of its title block
(:mod:`app.extraction.sheet_role`); the keyword table stays the answer whenever
Jev is off, unconfigured, unreachable or unsure.

Stdlib only (``urllib`` and ``json``), so there is no package to be missing:
the key is the only thing that can be absent, and every entry point reports
that rather than raising. The wire contract, from ``docs.typesafe.ai/api.md``
(read 2026-10-03):

- ``POST {base}/v1/systemone``, ``Authorization: Bearer <key>``, JSON body
  ``{state, model, questions}``; the answer is ``answers.<id>``.
- Retry 408, 429 and 5xx (529 is TypeSafe's "overloaded"), honoring
  ``retry-after-ms`` then ``retry-after``; anything else is fatal.

The model is pinned to a version, never an alias: ``jev-latest`` moves when a
release ships, and a confidence threshold tuned against one version is not a
threshold for the next.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

DEFAULT_MODEL = "jev-1.13.0"
BASE_URL = "https://api.typesafe.ai"
ENV_KEY = "TYPESAFE_API_KEY"

RETRY_STATUSES = frozenset({408, 429})
MAX_ATTEMPTS = 4
# A server asking for a longer pause than this is not going to be waited out by
# a person watching a progress bar; give up on that request and fall back.
MAX_WAIT_S = 30.0
TIMEOUT_S = 30.0


def resolve_key(explicit: Optional[str] = None) -> str:
    """The key to use: an explicit one (the Settings field) wins, else the
    ``TYPESAFE_API_KEY`` environment variable."""
    key = (explicit or "").strip()
    if key:
        return key
    return (os.environ.get(ENV_KEY) or "").strip()


def available(api_key: Optional[str] = None) -> bool:
    """True when a key is present. There is no SDK to be missing."""
    return bool(resolve_key(api_key))


def status(api_key: Optional[str] = None) -> tuple:
    """Network-free ``(state, message)``; state is ``"missing"`` or ``"present"``.

    Use :func:`validate_key` for an authoritative check.
    """
    if not resolve_key(api_key):
        return ("missing", f"No TypeSafe key set (field or {ENV_KEY})")
    return ("present", "Key set (not yet verified)")


def _urllib_transport(method: str, url: str, body: Optional[bytes],
                      headers: dict, timeout: float) -> tuple:
    """``(status, headers, body)`` for one HTTP exchange.

    An HTTP error status is a response, not an exception, so it comes back as a
    tuple like any other; only a failure to exchange at all raises.
    """
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (resp.status, {k.lower(): v for k, v in resp.headers.items()},
                    resp.read())
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
        try:
            data = e.read()
        except Exception:
            data = b""
        return (e.code, hdrs, data)


def _retryable(code: int) -> bool:
    return code in RETRY_STATUSES or 500 <= code <= 599


def _wait_seconds(headers: dict, attempt: int) -> float:
    """How long to wait before the next attempt: ``retry-after-ms`` first, then
    ``retry-after`` (seconds), else exponential backoff from one second."""
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            return max(0.0, float(raw) * scale)
        except (TypeError, ValueError):
            continue
    return float(2 ** attempt)


def ask(state, questions: dict, model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None, *,
        transport: Optional[Callable] = None,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = BASE_URL,
        max_attempts: int = MAX_ATTEMPTS,
        timeout: float = TIMEOUT_S) -> Optional[dict]:
    """Ask Jev ``questions`` about ``state``; the parsed response, or ``None``.

    Never raises: no key, a network failure, a fatal status, a body that is not
    JSON, or retries exhausted all return ``None`` so the caller keeps its
    offline answer. The key travels in the ``Authorization`` header only.
    """
    key = resolve_key(api_key)
    if not key:
        return None
    try:
        body = json.dumps({"state": state, "model": model,
                           "questions": questions}).encode("utf-8")
    except (TypeError, ValueError):
        return None
    headers = {"Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Accept": "application/json"}
    send = transport or _urllib_transport
    url = base_url.rstrip("/") + "/v1/systemone"
    for attempt in range(max(1, int(max_attempts))):
        try:
            code, resp_headers, data = send("POST", url, body, headers, timeout)
        except Exception:
            return None
        if code == 200:
            try:
                parsed = json.loads(data.decode("utf-8"))
            except Exception:
                return None
            return parsed if isinstance(parsed, dict) else None
        if not _retryable(int(code)) or attempt + 1 >= max_attempts:
            return None
        wait = _wait_seconds(resp_headers or {}, attempt)
        if wait > MAX_WAIT_S:
            return None
        sleep(wait)
    return None


def choice_answer(response: Optional[dict], question_id: str) -> Optional[dict]:
    """``{choice, confidence, probabilities}`` for one Choice question, or
    ``None`` when the response lacks a well-formed one."""
    if not isinstance(response, dict):
        return None
    ans = (response.get("answers") or {}).get(question_id)
    if not isinstance(ans, dict):
        return None
    choice = ans.get("choice")
    try:
        confidence = float(ans.get("confidence"))
    except (TypeError, ValueError):
        return None
    probs = ans.get("probabilities")
    if not isinstance(choice, str) or not isinstance(probs, dict):
        return None
    return {"choice": choice, "confidence": confidence,
            "probabilities": dict(probs),
            "model": str(response.get("model") or "")}


def validate_key(api_key: Optional[str] = None, *,
                 transport: Optional[Callable] = None,
                 base_url: str = BASE_URL,
                 timeout: float = 15.0) -> tuple:
    """Authoritative check via ``GET /v1/models``: ``(valid, message)``.

    Never raises. Costs nothing: listing models sends no input tokens.
    """
    key = resolve_key(api_key)
    if not key:
        return (False, "No TypeSafe key set")
    send = transport or _urllib_transport
    try:
        code, _hdrs, _data = send(
            "GET", base_url.rstrip("/") + "/v1/models", None,
            {"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout)
    except Exception as e:
        return (False, f"Could not reach TypeSafe: {type(e).__name__}")
    if code == 200:
        return (True, "Key is valid")
    if code == 401:
        return (False, "Invalid TypeSafe key (authentication failed)")
    return (False, f"Could not verify key: HTTP {code}")
