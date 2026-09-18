"""Document search engine — GUI-free.

Powers the viewer's Ctrl+F panel. Unlike a plain ``page.search_for`` loop this
engine also:

- supports **match case**, **whole words** and **regular expressions** (PyMuPDF's
  ``search_for`` is always case-insensitive and literal);
- returns the **context line** around every hit, so a results list can show
  "…PANEL FEED FROM CB-10412 VIA…" instead of a bare page number;
- optionally searches the **marks** (comments, text boxes, callouts, notes on
  any mark) alongside the page text — something no stock PDF viewer does;
- **decodes** a matched token that parses as a component tag or wire number
  ("tag LT · sheet 100 · rung 10"), reusing the app's own naming knowledge.

Coordinates: text matches are reported in **unrotated** PDF coordinates — the
same space ``page.search_for`` uses — and the caller applies
``page.rotation_matrix`` for display, exactly as the viewer always has. Mark
matches carry the annotation's page-local rect, which is already in display
space, so ``Match.source`` tells the caller which transform applies.

The per-page character index is built lazily from ``get_text("rawdict")`` and
cached, so typing in the search box re-scans strings, not the PDF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz


MAX_MATCHES = 1000       # hard cap so ".*" cannot hang the UI
_CONTEXT_CHARS = 48      # context kept on each side of a hit


@dataclass(frozen=True)
class SearchOptions:
    case_sensitive: bool = False
    whole_word: bool = False
    regex: bool = False
    include_marks: bool = True

    @property
    def needs_index(self) -> bool:
        """True when ``search_for`` can't honour the options and the char
        index must be used instead."""
        return self.case_sensitive or self.whole_word or self.regex


@dataclass
class Match:
    page: int
    rect: tuple                  # (x0, y0, x1, y1) — see module docstring
    text: str                    # the matched text itself
    before: str = ""             # same-line context, already trimmed
    after: str = ""
    source: str = "text"         # "text" | "mark"
    ann_id: str = ""             # annotation id for source == "mark"
    kind: str = ""               # mark kind ("comment", "callout", ...)
    author: str = ""
    decode: str = ""             # e.g. "tag LT · sheet 100 · rung 10"


@dataclass
class SearchResult:
    matches: list = field(default_factory=list)
    capped: bool = False


class BadPatternError(ValueError):
    """The regex the user typed does not compile."""


def _compile(query: str, options: SearchOptions) -> "re.Pattern[str]":
    pat = query if options.regex else re.escape(query)
    if options.whole_word:
        pat = r"(?<!\w)(?:%s)(?!\w)" % pat
    flags = 0 if options.case_sensitive else re.IGNORECASE
    try:
        return re.compile(pat, flags)
    except re.error as e:
        raise BadPatternError(str(e)) from e


def _trim_context(line: str, start: int, end: int) -> tuple:
    before = line[:start]
    after = line[end:]
    if len(before) > _CONTEXT_CHARS:
        before = "…" + before[-_CONTEXT_CHARS:]
    if len(after) > _CONTEXT_CHARS:
        after = after[:_CONTEXT_CHARS] + "…"
    return before, after


class DocumentSearch:
    """Searches one open ``fitz`` document, caching a per-page char index."""

    def __init__(self, fitz_doc):
        self.doc = fitz_doc
        self._lines: dict = {}     # pno -> [(line_text, [fitz.Rect per char])]

    def invalidate(self) -> None:
        self._lines.clear()

    # -- the per-page line/char index ----------------------------------------

    def _page_lines(self, pno: int) -> list:
        cached = self._lines.get(pno)
        if cached is not None:
            return cached
        lines = []
        try:
            raw = self.doc[pno].get_text("rawdict")
        except Exception:
            raw = {}
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                chars: list = []
                text_parts: list = []
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        text_parts.append(ch.get("c", ""))
                        chars.append(fitz.Rect(ch.get("bbox")))
                text = "".join(text_parts)
                if text.strip():
                    lines.append((text, chars))
        self._lines[pno] = lines
        return lines

    # -- public API ----------------------------------------------------------

    def search(self, query: str, options: SearchOptions = SearchOptions(),
               store=None, component_config=None,
               wire_config=None) -> SearchResult:
        """All matches for ``query``, page order, top-to-bottom within a page.

        ``store`` (an ``AnnotationStore``) is only consulted when
        ``options.include_marks`` is set. Raises :class:`BadPatternError` for
        an uncompilable regex.
        """
        result = SearchResult()
        q = (query or "").strip()
        if not q:
            return result
        pattern = _compile(q, options)      # validate even on the plain path

        for pno in range(self.doc.page_count):
            page_hits = (self._index_matches(pno, pattern)
                         if options.needs_index
                         else self._plain_matches(pno, q))
            if options.include_marks and store is not None:
                page_hits.extend(self._mark_matches(pno, pattern, store))
            page_hits.sort(key=lambda m: (m.rect[1], m.rect[0]))
            for m in page_hits:
                m.decode = _decode_token(m.text, component_config, wire_config)
                result.matches.append(m)
                if len(result.matches) >= MAX_MATCHES:
                    result.capped = True
                    return result
        return result

    # -- text matching -------------------------------------------------------

    def _plain_matches(self, pno: int, q: str) -> list:
        """Default path: ``search_for`` (case-insensitive, literal, and aware
        of line-wrapped phrases), with context recovered from the index."""
        try:
            rects = self.doc[pno].search_for(q)
        except Exception:
            rects = []
        out = []
        for r in rects:
            before, after = self._context_for(pno, fitz.Rect(r))
            out.append(Match(page=pno, rect=(r.x0, r.y0, r.x1, r.y1),
                             text=q, before=before, after=after))
        return out

    def _index_matches(self, pno: int, pattern) -> list:
        out = []
        for text, chars in self._page_lines(pno):
            pos = 0
            while True:
                m = pattern.search(text, pos)
                if m is None:
                    break
                start, end = m.span()
                if end == start:            # zero-width regex match
                    if start >= len(text):  # ...at the end: re.search keeps
                        break               # returning it whatever pos is
                    pos = start + 1
                    continue
                pos = end
                span_rects = [chars[i] for i in range(start, min(end, len(chars)))]
                if not span_rects:
                    continue
                rect = span_rects[0]
                for r in span_rects[1:]:
                    rect |= r
                before, after = _trim_context(text, start, end)
                out.append(Match(page=pno,
                                 rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                                 text=m.group(0), before=before, after=after))
        return out

    def _context_for(self, pno: int, rect: fitz.Rect) -> tuple:
        """Locate the index line containing ``rect`` and split it around the
        matched characters."""
        cy = (rect.y0 + rect.y1) / 2.0
        for text, chars in self._page_lines(pno):
            hit = [i for i, cr in enumerate(chars) if cr.intersects(rect)]
            if not hit:
                continue
            # the hit chars must sit on the match's own line, not merely share
            # horizontal extent with it
            ly0 = min(chars[i].y0 for i in hit)
            ly1 = max(chars[i].y1 for i in hit)
            if not (ly0 - 2 <= cy <= ly1 + 2):
                continue
            return _trim_context(text, hit[0], hit[-1] + 1)
        return "", ""

    # -- mark matching -------------------------------------------------------

    def _mark_matches(self, pno: int, pattern, store) -> list:
        out = []
        for ann in store.on_page(pno):
            hay = ann.text or ""
            m = pattern.search(hay)
            if m is None:
                continue
            before, after = _trim_context(hay, m.start(), m.end())
            r = tuple(float(v) for v in (ann.rect or (0, 0, 0, 0)))
            out.append(Match(page=pno, rect=r, text=m.group(0),
                             before=before, after=after, source="mark",
                             ann_id=str(ann.id), kind=ann.kind,
                             author=ann.author or ""))
        return out


def _decode_token(text: str, component_config, wire_config) -> str:
    """Human-readable decode when the matched text is a tag the app's naming
    conventions understand. Empty string otherwise."""
    token = (text or "").strip()
    if not token or len(token) > 24:
        return ""
    if component_config is not None:
        try:
            from ..extraction.component_parser import parse_component_label
            parsed = parse_component_label(token, component_config)
        except Exception:
            parsed = None
        if parsed:
            family, _number, sheet, rung = parsed
            if sheet is not None:
                return f"tag {family} · sheet {sheet} · rung {rung}"
            return f"tag {family}"
    if wire_config is not None:
        try:
            from ..extraction.wire_parser import parse_label
            parsed = parse_label(token, wire_config)
        except Exception:
            parsed = None
        if parsed:
            sheet, rung, wire_index = parsed
            return f"wire · sheet {sheet} · rung {rung} · #{wire_index}"
    return ""
