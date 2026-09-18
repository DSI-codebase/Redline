"""Optional Claude vision assist (Phase 8) - strictly opt-in.

Used only to OCR/parse wire numbers on scanned regions and to disambiguate
low-confidence candidates ("is this a wire number or a terminal/part number?").
The app is fully functional without an API key: every entry point degrades
gracefully when ``anthropic`` or ``ANTHROPIC_API_KEY`` is missing.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Optional

DEFAULT_MODEL = "claude-opus-4-8"


def resolve_key(explicit: Optional[str] = None) -> str:
    """Return the API key to use: an explicit key wins, else the env var."""
    key = (explicit or "").strip()
    if key:
        return key
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def sdk_installed() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def available(api_key: Optional[str] = None) -> bool:
    """True when the SDK is importable and an API key is present."""
    return sdk_installed() and bool(resolve_key(api_key))


def status(api_key: Optional[str] = None) -> tuple:
    """Quick, network-free status: ``(state, message)``.

    state is one of: "no_sdk", "missing", "present".  Use :func:`validate_key`
    for an authoritative (network) check.
    """
    if not sdk_installed():
        return ("no_sdk", "anthropic SDK not installed (pip install anthropic)")
    key = resolve_key(api_key)
    if not key:
        return ("missing", "No API key set")
    if not key.startswith("sk-"):
        return ("present", "Key set (format looks unusual)")
    return ("present", "Key set (not yet verified)")


def validate_key(api_key: Optional[str] = None, model: str = DEFAULT_MODEL) -> tuple:
    """Authoritative check via a minimal API call. Returns ``(valid, message)``.

    Never raises; returns ``(False, reason)`` on any error.
    """
    if not sdk_installed():
        return (False, "anthropic SDK not installed")
    key = resolve_key(api_key)
    if not key:
        return (False, "No API key set")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model=model, max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return (True, "Key is valid")
    except Exception as e:
        name = type(e).__name__
        msg = str(e)
        if "auth" in msg.lower() or "401" in msg or "AuthenticationError" in name:
            return (False, "Invalid API key (authentication failed)")
        return (False, f"Could not verify key: {name}")


def _pixmap_to_png_b64(pix) -> str:
    return base64.b64encode(pix.tobytes("png")).decode("ascii")


def _build_prompt(field_widths: tuple, zero_pad: bool,
                  img_w: int = 0, img_h: int = 0) -> str:
    sw, rw, ww = field_widths
    total = sw + rw + ww
    dims = (f"The image is {img_w}x{img_h} pixels. " if img_w and img_h else "")
    return (
        "You are reading an electrical ladder/schematic drawing sheet. Find EVERY "
        "wire-number label: the short numeric codes printed on or beside wire "
        "segments to identify a conductor. Read them exactly as printed, even if "
        "they don't all share the same length or format (sets vary).\n\n"
        f"On many sets a wire number is {total} digits encoding, left to right: "
        f"sheet ({sw} digits), rung ({rw} digits"
        f"{', zero-padded' if zero_pad else ''}), and a 0-based wire index "
        f"({ww} digit) - e.g. 432141 = sheet 432, rung 14, wire 1. Capture labels "
        "that follow this AND ones that don't.\n\n"
        f"{dims}Return ONLY a JSON array (no prose, no markdown fences). Each "
        'element: {"label": str, "is_wire": bool, "confidence": 0..1, '
        '"bbox": [x0,y0,x1,y1]} where bbox is in image pixels. Set is_wire=false '
        "for device/part/terminal numbers, rung numbers, titles and notes - only "
        "true for actual conductor/wire labels."
    )


def _extract_json(text: str):
    """Pull a JSON array out of a model response, defensively."""
    text = text.strip()
    # strip code fences if present
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return []
    return []


def read_wire_region(pix, field_widths: tuple = (3, 2, 1),
                     zero_pad: bool = True,
                     model: str = DEFAULT_MODEL,
                     max_tokens: int = 4096,
                     api_key: Optional[str] = None) -> list:
    """Send a rendered region to Claude and return parsed wire dicts.

    ``pix`` is a :class:`fitz.Pixmap`.  Returns ``[]`` on any failure so callers
    can always fall back to Tesseract + rules.
    """
    key = resolve_key(api_key)
    if not (sdk_installed() and key):
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        b64 = _pixmap_to_png_b64(pix)
        prompt = _build_prompt(field_widths, zero_pad,
                               getattr(pix, "width", 0), getattr(pix, "height", 0))
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return _extract_json("".join(parts))
    except Exception:
        return []


def _vision_call(images, instruction, model=DEFAULT_MODEL, max_tokens=4096,
                 api_key=None) -> str:
    """Low-level: send one or more pixmaps + an instruction, return the text
    reply (or '' on any failure)."""
    key = resolve_key(api_key)
    if not (sdk_installed() and key):
        return ""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        content = []
        for pix in images:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": _pixmap_to_png_b64(pix)}})
        content.append({"type": "text", "text": instruction})
        msg = client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}])
        return "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text").strip()
    except Exception:
        return ""


def read_text_region(pix, model: str = DEFAULT_MODEL, api_key: Optional[str] = None) -> str:
    """Read the plain text shown in an image region (e.g. a title-block cell).

    Used as a last-resort fallback for the sheet-number wizard on scanned pages.
    Returns '' on failure.
    """
    return _vision_call(
        [pix],
        "Transcribe exactly the text shown in this image, on one line. "
        "If it is a sheet/drawing number, return just that value. No prose.",
        model=model, api_key=api_key, max_tokens=256)


def _build_component_prompt(families, img_w=0, img_h=0) -> str:
    fam = ", ".join(sorted({str(f).strip().upper() for f in families if str(f).strip()}))
    dims = (f"The image is {img_w}x{img_h} pixels. " if img_w and img_h else "")
    return (
        "You are reading an electrical/controls drawing sheet. Find EVERY "
        "component/device tag: a short identifier of a FAMILY code (1-4 letters) "
        "followed by a number, e.g. LT-10010, CR-30024, PB-301, FU100. The number "
        "usually encodes the sheet and rung the device sits on. Read tags exactly "
        "as printed (the separator may be a hyphen, space, or nothing).\n\n"
        + (f"Common family codes on this job: {fam}.\n\n" if fam else "")
        + f"{dims}Return ONLY a JSON array (no prose, no fences). Each element: "
        '{"label": str, "family": str, "is_component": bool, "confidence": 0..1, '
        '"bbox": [x0,y0,x1,y1]} where bbox is in image pixels. Set '
        "is_component=false for wire numbers, rung numbers, notes and titles - "
        "true only for device/component tags."
    )


def read_component_region(pix, families=(), model: str = DEFAULT_MODEL,
                          max_tokens: int = 4096,
                          api_key: Optional[str] = None) -> list:
    """Send a rendered region to Claude and return parsed component dicts.

    Returns ``[]`` on any failure so callers fall back to OCR + rules.
    """
    key = resolve_key(api_key)
    if not (sdk_installed() and key):
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        b64 = _pixmap_to_png_b64(pix)
        prompt = _build_component_prompt(
            families, getattr(pix, "width", 0), getattr(pix, "height", 0))
        msg = client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": prompt},
            ]}])
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return _extract_json("".join(parts))
    except Exception:
        return []


# --- crop / extract: classify a region as a table or a body of prose --------

REGION_CONTENT_PROMPT = (
    "This image is a region cropped from an engineering/technical PDF. Read ALL "
    "of its text exactly. Decide whether the content is primarily a TABLE (e.g. a "
    "bill of materials, schedule, or grid with rows and columns) or a body of "
    "PROSE/free text (e.g. a note, description, or instructions).\n\n"
    "Return ONLY one JSON object (no prose, no fences):\n"
    '{"type": "table" | "text", "title": str, '
    '"rows": [[cell, cell, ...], ...], "text": str}\n'
    "For a table, fill \"rows\" with the cell grid (first row = headers if any) "
    "and set \"text\" to \"\". For prose, fill \"text\" with the full readable "
    "text (keep line/paragraph breaks) and set \"rows\" to []. \"title\" is a "
    "short caption if one is visible, else \"\"."
)


def extract_region_content(pix, model: str = DEFAULT_MODEL,
                           max_tokens: int = 4096,
                           api_key: Optional[str] = None) -> dict:
    """Classify + transcribe a cropped region.

    Returns ``{"type": "table"|"text", "title": str, "rows": list, "text": str}``
    or ``{}`` on failure (caller falls back to a plain OCR/text dump).
    """
    text = _vision_call([pix], REGION_CONTENT_PROMPT, model=model,
                        api_key=api_key, max_tokens=max_tokens)
    if not text:
        return {}
    obj = _extract_json_object(text)
    if not isinstance(obj, dict) or not obj:
        return {}
    kind = "table" if str(obj.get("type", "")).lower().startswith("tab") else "text"
    rows = obj.get("rows") or []
    norm_rows = []
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, list):
                norm_rows.append([("" if c is None else str(c)) for c in r])
            else:
                norm_rows.append([str(r)])
    return {
        "type": kind,
        "title": str(obj.get("title", "")).strip(),
        "rows": norm_rows,
        "text": str(obj.get("text", "")).strip(),
    }


def _extract_json_object(text: str):
    """Pull a single JSON object out of a model response, defensively."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
    return {}


# default prompt for the crop -> TAG/DESCRIPTION table (mirrors the legacy
# ChatGPT prompt the user kept in their old tool)
TAG_PROMPT = (
    "Each image is a cropped label from an engineering drawing. For EACH image, "
    "produce a TAG (an abbreviated identifier with no spaces or special "
    "characters - underscores allowed) and a DESCRIPTION (the full readable "
    "text). Return ONLY a JSON array of objects "
    '{"tag": str, "description": str} in image order. No prose, no fences.'
)


def tag_descriptions(pixmaps, extra_prompt: str = "", model: str = DEFAULT_MODEL,
                     api_key: Optional[str] = None) -> list:
    """Crop images -> rows of ``{tag, description}`` via Claude vision.

    Returns ``[]`` on failure so the caller can fall back to plain PNG export.
    """
    prompt = TAG_PROMPT + (("\n\n" + extra_prompt) if extra_prompt else "")
    text = _vision_call(list(pixmaps), prompt, model=model, api_key=api_key)
    rows = _extract_json(text)
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            out.append({"tag": str(r.get("tag", "")).strip(),
                        "description": str(r.get("description", "")).strip()})
    return out
