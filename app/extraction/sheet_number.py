"""Resolving each page's sheet number.

Every location-based design rule compares a tag's *declared* sheet against the
sheet it was actually found on, so this value is the input the whole audit rests
on.  Getting it wrong does not produce no findings; it produces confident wrong
ones.

Measured on a real AutoCAD Electrical plot, the original title-block heuristics
resolved **0 of 14** pages: the keyword pattern matched an explanatory note
("A WIRE ON SHEET 26 LINE 12...") rather than a title block, and the corner
fallback found no text at all because ACADE plots the title block in SHX shape
fonts, which arrive as vector geometry rather than words.

What does work on those plots is the drawing number, which carries the sheet as
a suffix (``EL2507777-300``) and resolved **14 of 14**.  So that strategy leads,
the older heuristics stay as fallbacks with the region guard they were missing,
and every answer records which strategy produced it — because a rule that cannot
tell a certain sheet number from a guessed one cannot report coverage honestly.

GUI-free, like its siblings.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

# --- strategies -------------------------------------------------------------

DRAWING_NUMBER = "drawing_number"   # "EL2507777-300" -> 300
KEYWORD = "keyword"                 # "SHEET 300" inside the title block
CORNER = "corner"                   # lesser numeric token in the bottom-right
USER = "user"                       # a human typed or confirmed it
UNKNOWN = "unknown"                 # carried over from an older sidecar

# How much a resolved sheet number can be trusted.  Surfaced as provenance on
# every finding, so a reviewer can weigh the conclusion against its input.
CONFIDENCE = {
    USER: 1.0,
    DRAWING_NUMBER: 1.0,
    KEYWORD: 0.8,
    CORNER: 0.6,
    UNKNOWN: 0.7,
}

# A project drawing number followed by a sheet suffix.  Letters first, so
# catalog numbers on a bill of materials ("1783-US5T", "800T-QTH2B",
# "25B-V2P5N104") cannot match.  The separator admits both spellings seen on
# real sets: EL2507777-300 and EL2503311_011 are the same convention drawn by
# two shops, and the hyphen-only pattern sent the second set's every page
# through to the corner heuristic -- which then read the title block's
# "REV: 0" cell and named all seventeen resolvable sheets "0".
DEFAULT_DRAWING_NUMBER_PATTERN = r"\b([A-Za-z]{1,4}\d{4,10})[-_](\d{2,4})\b"

_KEYWORD_RE = re.compile(r"^(?:SHEET|SHT)\.?$", re.IGNORECASE)
_KEYWORD_INLINE_RE = re.compile(
    r"\b(?:SHEET|SHT)\.?\s*(?:NO\.?\s*)?(\d{1,4})\b", re.IGNORECASE)


@dataclass
class SheetNumberConfig:
    """Knobs for sheet-number resolution.

    ``drawing_number_pattern`` is a *setting*, not a constant: the suffix
    convention that resolves this customer's plots is theirs, and another
    project will number its drawings differently.
    """

    strategies: tuple = (DRAWING_NUMBER, KEYWORD, CORNER)
    drawing_number_pattern: str = DEFAULT_DRAWING_NUMBER_PATTERN
    # The title-block band, as fractions of the page. The keyword and corner
    # strategies only look here -- that region guard is what stops a drafting
    # note in the body of the drawing from being read as a sheet number.
    titleblock_x_frac: float = 0.55
    titleblock_y_frac: float = 0.72
    corner_x_frac: float = 0.70
    corner_y_frac: float = 0.82
    corner_max_candidates: int = 4
    # A page with less text than this cannot contain a paragraph of drafting
    # notes, so the keyword may be trusted anywhere on it. Busier pages are
    # searched only inside the title-block band -- that is the guard that stops
    # note prose from being read as a sheet number.
    keyword_sparse_page_chars: int = 600

    def pattern(self) -> "re.Pattern[str]":
        return re.compile(self.drawing_number_pattern)


@dataclass(frozen=True)
class SheetResolution:
    """A page's sheet number, and how much to believe it."""

    label: Optional[str] = None
    strategy: str = UNKNOWN
    confidence: float = 0.0

    @property
    def resolved(self) -> bool:
        return bool(self.label)

    @property
    def number(self) -> Optional[int]:
        try:
            return int(self.label)
        except (TypeError, ValueError):
            return None


UNRESOLVED = SheetResolution()


def _made(label: Optional[str], strategy: str) -> SheetResolution:
    if not label:
        return UNRESOLVED
    return SheetResolution(label=str(label), strategy=strategy,
                           confidence=CONFIDENCE.get(strategy, 0.5))


# --- strategies -------------------------------------------------------------

def _words(page) -> list:
    """Words as ``(x0, y0, x1, y1, text)`` in the page's *displayed* space.

    ``get_text("words")`` reports in the unrotated space. On a plot rotated for
    display -- which every sheet of a typical AutoCAD Electrical set is -- that
    is a different coordinate system, and the title-block band computed from
    ``page.rect`` does not overlap it at all. The original corner heuristic
    looked for text at ``x >= 0.70 * 1224 = 857`` while no word could ever have
    an unrotated ``x`` above 792, so it was searching a region that did not
    exist and returned nothing on every page.
    """
    import fitz
    try:
        raw = page.get_text("words") or []
        rot = page.rotation_matrix
    except Exception:
        return []
    out = []
    for w in raw:
        try:
            r = (fitz.Rect(w[0], w[1], w[2], w[3]) * rot).normalize()
            out.append((r.x0, r.y0, r.x1, r.y1, w[4]))
        except Exception:
            continue
    return out


def drawing_number_candidates(page, config: SheetNumberConfig) -> list:
    """``(prefix, suffix)`` pairs of every drawing number on the page.

    Scans the flat text and, separately, each extracted word, because the two
    disagree often enough to matter: flat-text extraction can fold a line or
    drop a separator, while the word list preserves each title-block cell
    intact. An anchored whole-word match cannot pick up a fragment of something
    longer, so the second pass adds recall without adding false positives.

    Known limit: when two title-block cells are plotted close enough that
    PyMuPDF merges them into one word (``DISTRIBUTIONEL2507777-400``), neither
    pass matches, and resolution falls through to the next strategy. Separating
    the cells geometrically would need a title-block template; the fallbacks
    exist for exactly this.
    """
    pattern = config.pattern()
    try:
        text = page.get_text("text") or ""
    except Exception:
        text = ""
    hits = list(pattern.findall(text))

    anchored = re.compile(f"^(?:{pattern.pattern})$")
    try:
        words = page.get_text("words") or []
    except Exception:
        words = []
    for w in words:
        m = anchored.match(str(w[4]).strip())
        if m and m.groups() not in hits:
            hits.append(m.groups())
    return hits


def _from_drawing_number(page, config: SheetNumberConfig,
                         prefix: Optional[str] = None) -> SheetResolution:
    """The sheet suffix of the page's drawing number.

    With ``prefix`` supplied (the project's dominant drawing-number prefix, as
    established across the whole document) only that project's numbers count,
    which keeps a stray part number from ever being read as a sheet.
    """
    hits = drawing_number_candidates(page, config)
    if prefix:
        hits = [h for h in hits if h[0].upper() == prefix.upper()]
    if not hits:
        return UNRESOLVED
    suffixes = {h[1] for h in hits}
    if len(suffixes) > 1:
        return UNRESOLVED          # ambiguous: say nothing rather than guess
    return _made(hits[0][1], DRAWING_NUMBER)


def _from_keyword(page, config: SheetNumberConfig) -> SheetResolution:
    """A ``SHEET 300`` label from the title block.

    On a busy page the match must sit inside the title-block band. Without that
    guard this read the sample plot's own explanatory note -- "A WIRE ON SHEET
    26 LINE 12 WOULD BE ASSIGNED # 2612" -- and reported sheet 26 for the title
    page. On a sparse page there is no prose to confuse it with, so the whole
    page is fair game.
    """
    try:
        text = page.get_text("text") or ""
    except Exception:
        text = ""
    if len(text.strip()) < config.keyword_sparse_page_chars:
        m = _KEYWORD_INLINE_RE.search(text)
        if m:
            return _made(m.group(1), KEYWORD)

    words = _words(page)
    if not words:
        return UNRESOLVED
    try:
        rect = page.rect
    except Exception:
        return UNRESOLVED
    x_min = rect.x0 + rect.width * config.titleblock_x_frac
    y_min = rect.y0 + rect.height * config.titleblock_y_frac

    band = [w for w in words
            if _num(w[0]) >= x_min and _num(w[1]) >= y_min]
    if not band:
        return UNRESOLVED

    # "SHEET 300" as a single token run inside the band.
    joined = " ".join(str(w[4]) for w in sorted(band, key=lambda w: (w[1], w[0])))
    m = _KEYWORD_INLINE_RE.search(joined)
    if m:
        return _made(m.group(1), KEYWORD)

    # "SHEET:" in one cell and its value in the next -- to the right, or on
    # the line directly below, which is how the blocks that also print a
    # "NEXT SHEET:" cell lay theirs out. A label whose preceding word is NEXT
    # is skipped entirely: it names the following sheet, by its own words.
    for w in band:
        if not _KEYWORD_RE.match(str(w[4]).strip().rstrip(":")):
            continue
        cy = (_num(w[1]) + _num(w[3])) / 2
        line = max(_num(w[3]) - _num(w[1]), 4.0)
        left = [o for o in band
                if _num(o[2]) <= _num(w[0]) + 1
                and abs((_num(o[1]) + _num(o[3])) / 2 - cy) < line * 0.8]
        if left:
            left.sort(key=lambda o: -_num(o[2]))
            if str(left[0][4]).strip().rstrip(".:").upper() == "NEXT":
                continue
        # Half a line height, not a fixed six points: the reported glyph
        # boxes scale with the text, and at small title-block sizes a fixed
        # tolerance reaches into the line below -- where the NEXT SHEET value
        # sits, which is exactly the number this must not read.
        same_row = [o for o in band
                    if _num(o[0]) > _num(w[2])
                    and abs((_num(o[1]) + _num(o[3])) / 2 - cy) < line * 0.5
                    and str(o[4]).strip().isdigit()]
        if same_row:
            same_row.sort(key=lambda o: _num(o[0]))
            return _made(str(same_row[0][4]).strip(), KEYWORD)
        below = [o for o in band
                 if str(o[4]).strip().isdigit()
                 and line * 0.5 <= ((_num(o[1]) + _num(o[3])) / 2 - cy) < line * 3
                 and _num(o[0]) < _num(w[2]) + line
                 and _num(o[2]) > _num(w[0]) - line * 3]
        if below:
            below.sort(key=lambda o: _num(o[1]))
            return _made(str(below[0][4]).strip(), KEYWORD)
    return UNRESOLVED


_REV_LABEL_RE = re.compile(r"^REV(?:ISION)?[.:]*$", re.IGNORECASE)


def _is_revision_value(w, labels) -> bool:
    """Whether numeric word ``w`` is the value of a ``REV`` title-block cell.

    Two layouts cover the blocks seen so far: the value in the next cell to
    the right of the label, or on the line directly below it. Measured on the
    set that motivated this, "REV:" at y=748.5 with its "0" at y=754.2 in the
    same column -- under six points apart, dead-aligned in x.
    """
    wx0, wy0, wx1, wy1 = _num(w[0]), _num(w[1]), _num(w[2]), _num(w[3])
    wcy = (wy0 + wy1) / 2
    for lab in labels:
        lx0, ly0, lx1, ly1 = (_num(lab[0]), _num(lab[1]),
                              _num(lab[2]), _num(lab[3]))
        line = max(ly1 - ly0, 4.0)
        # Rows are told apart by their centres, not their edges: the reported
        # glyph boxes carry ascender/descender padding, so two visually
        # distinct lines can overlap by a point or two and an edge test calls
        # them one row.
        dcy = wcy - (ly0 + ly1) / 2
        same_row = abs(dcy) < line * 0.5
        if same_row and 0 <= wx0 - lx1 < line * 6:
            return True
        below = line * 0.5 <= dcy < line * 3
        x_overlap = wx0 < lx1 + line and wx1 > lx0 - line
        if below and x_overlap:
            return True
    return False


def _from_corner(page, config: SheetNumberConfig) -> SheetResolution:
    """The lesser numeric token in the bottom-right corner.

    AutoCAD title blocks often place ``THIS SHEET`` beside ``NEXT``; when both
    are present the current sheet is the smaller. Gives up when the corner is
    empty or crowded, because a wrong sheet number is worse than none.

    A number belonging to a ``REV`` cell is not a candidate at all. The
    revision lives in this same corner on every title block, it is small --
    usually 0 -- and "the lesser number" is a rule that selects it every
    time it appears: one real set came back with every sheet named "0" and
    thirty-three findings about a drawing set whose only defect was being at
    revision zero.
    """
    words = _words(page)
    if not words:
        return UNRESOLVED
    try:
        rect = page.rect
    except Exception:
        return UNRESOLVED
    x_min = rect.x0 + rect.width * config.corner_x_frac
    y_min = rect.y0 + rect.height * config.corner_y_frac

    band = [w for w in words if _num(w[0]) >= x_min and _num(w[1]) >= y_min]
    rev_labels = [w for w in band if _REV_LABEL_RE.match(str(w[4]).strip())]
    nums = [str(w[4]).strip() for w in band
            if str(w[4]).strip().isdigit() and 1 <= len(str(w[4]).strip()) <= 4
            and not _is_revision_value(w, rev_labels)]
    if not nums or len(nums) > config.corner_max_candidates:
        return UNRESOLVED
    return _made(min(nums, key=int), CORNER)


_STRATEGY_FNS = {
    DRAWING_NUMBER: _from_drawing_number,
    KEYWORD: _from_keyword,
    CORNER: _from_corner,
}


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# --- resolution -------------------------------------------------------------

def resolve_page(page, config: Optional[SheetNumberConfig] = None,
                 prefix: Optional[str] = None) -> SheetResolution:
    """Resolve one page, trying each configured strategy in order."""
    config = config or SheetNumberConfig()
    for name in config.strategies:
        fn = _STRATEGY_FNS.get(name)
        if fn is None:
            continue
        try:
            got = (fn(page, config, prefix) if fn is _from_drawing_number
                   else fn(page, config))
        except Exception:
            got = UNRESOLVED
        if got.resolved:
            return got
    return UNRESOLVED


def dominant_prefix(doc, config: Optional[SheetNumberConfig] = None) -> Optional[str]:
    """The project's drawing-number prefix, as used on most pages.

    A drawing set shares one project number, so the prefix that appears on the
    most pages is it. Pinning to that turns a loose pattern into a strict one
    without having to hardcode a customer's numbering scheme.
    """
    config = config or SheetNumberConfig()
    counts: Counter = Counter()
    for i in range(getattr(doc, "page_count", 0)):
        try:
            page = doc[i]
        except Exception:
            continue
        seen = {p.upper() for p, _s in drawing_number_candidates(page, config)}
        counts.update(seen)
    if not counts:
        return None
    prefix, hits = counts.most_common(1)[0]
    # One page carrying a stray match is not a project number.
    return prefix if hits >= 2 else None


def resolve_document(doc, config: Optional[SheetNumberConfig] = None) -> dict:
    """``{page_index: SheetResolution}`` for a whole document."""
    config = config or SheetNumberConfig()
    prefix = dominant_prefix(doc, config)
    out: dict = {}
    for i in range(getattr(doc, "page_count", 0)):
        try:
            page = doc[i]
        except Exception:
            out[i] = UNRESOLVED
            continue
        out[i] = resolve_page(page, config, prefix)
    return out
