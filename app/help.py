"""In-app user-manual reader — a read-only, Obsidian-style vault.

Renders the markdown files in ``docs/`` (kept next to the app so they ship with
it) with working ``[[wikilinks]]``, clickable ``#tags`` and a simple graph view.
Falls back gracefully if the vault folder is missing.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QUrl, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QDesktopServices, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTextBrowser, QListWidget, QTabWidget,
    QToolBar, QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsSimpleTextItem, QLabel, QVBoxLayout,
)

_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
_TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9_][\w/-]*)")
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_FM_TAGS_RE = re.compile(r"tags:\s*\[([^\]]*)\]")


def vault_dir() -> Path:
    """Locate the docs vault, working both from source and a frozen build.

    PyInstaller bundles ``docs/`` next to the app, so check the frozen
    locations (``sys._MEIPASS`` and the executable folder) before the
    source-tree path.
    """
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "docs")
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "docs")
        candidates.append(exe_dir / "_internal" / "docs")
    candidates.append(Path(__file__).resolve().parent.parent / "docs")
    candidates.append(Path.cwd() / "docs")
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _frontmatter_tags(text: str) -> set:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return set()
    mt = _FM_TAGS_RE.search(m.group(0))
    if not mt:
        return set()
    return {t.strip() for t in mt.group(1).split(",") if t.strip()}


def _strip_code(text: str) -> str:
    """Blank out fenced and inline code so examples like `[[link]]`/`#tag`
    aren't mistaken for real links/tags."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    return text


def _link_sub(m) -> str:
    page = m.group(1).strip()
    alias = (m.group(2) or page).strip()
    return f"[{alias}](vault:{quote(page)})"


def _tag_sub(m) -> str:
    return f"[#{m.group(1)}](tag:{quote(m.group(1))})"


def load_vault(folder: Path) -> dict:
    """Return ``{page_name: {raw, tags:set, links:set}}``."""
    pages: dict = {}
    if not folder.is_dir():
        return pages
    for path in sorted(folder.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        clean = _strip_code(_strip_frontmatter(raw))
        pages[path.stem] = {
            "raw": raw,
            "tags": _frontmatter_tags(raw) | set(_TAG_RE.findall(clean)),
            "links": {m.group(1).strip() for m in _LINK_RE.finditer(clean)},
        }
    return pages


def to_markdown(raw: str) -> str:
    """Convert vault markdown to QTextBrowser markdown with working links.

    Headings and code (fenced or inline) are left untouched so literal
    ``[[link]]`` / ``#tag`` examples render verbatim.
    """
    text = _strip_frontmatter(raw)
    out_lines = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            out_lines.append(line)
            continue
        # a real ATX heading is "# text" (hashes + space); "#home" is a tag line
        if in_code or re.match(r"#{1,6}\s", stripped):
            out_lines.append(line)
            continue
        # convert only outside inline-code segments (odd indices are code)
        parts = line.split("`")
        for i in range(0, len(parts), 2):
            parts[i] = _TAG_RE.sub(_tag_sub, _LINK_RE.sub(_link_sub, parts[i]))
        out_lines.append("`".join(parts))
    return "\n".join(out_lines)


class _NodeItem(QGraphicsEllipseItem):
    """Clickable, hover-aware page node in the graph view."""

    R = 9.0
    DEFAULT = QColor(40, 120, 220)
    HOVER = QColor(232, 145, 30)      # the node being hovered
    NEIGHBOR = QColor(40, 170, 90)    # nodes linked to the hovered one

    def __init__(self, name, graph, text_color):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R)
        self.name = name
        self._graph = graph
        self.setBrush(QBrush(self.DEFAULT))
        self.setPen(QPen(QColor("white"), 1))
        self.setZValue(2)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptHoverEvents(True)
        self.label = QGraphicsSimpleTextItem(name, self)
        self.label.setBrush(QBrush(text_color))
        br = self.label.boundingRect()
        self.label.setPos(-br.width() / 2, self.R + 2)

    def set_fill(self, color):
        self.setBrush(QBrush(color))

    def mousePressEvent(self, event):
        self._graph.on_click(self.name)
        event.accept()

    def hoverEnterEvent(self, event):
        self._graph.set_hover(self.name)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._graph.clear_hover()
        super().hoverLeaveEvent(event)


class HelpWindow(QMainWindow):
    """Read-only vault reader: Pages / Tags / Graph + a markdown view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DSI Redline — User Manual")
        try:
            from . import app_icon
            self.setWindowIcon(app_icon())
        except Exception:
            pass
        self.resize(1040, 720)
        self.pages = load_vault(vault_dir())
        self._history = []
        self._hindex = -1

        tb = QToolBar("nav")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_back = QAction("← Back", self); self.act_back.triggered.connect(self.go_back)
        self.act_fwd = QAction("Forward →", self); self.act_fwd.triggered.connect(self.go_forward)
        self.act_home = QAction("Home", self); self.act_home.triggered.connect(lambda: self.load_page("Home"))
        tb.addAction(self.act_back); tb.addAction(self.act_fwd); tb.addSeparator(); tb.addAction(self.act_home)

        split = QSplitter(self)
        self.setCentralWidget(split)

        self.nav = QTabWidget()
        self.nav.setMinimumWidth(180)
        self.page_list = QListWidget(); self.page_list.addItems(sorted(self.pages))
        self.page_list.itemClicked.connect(lambda it: self.load_page(it.text()))
        self.tag_list = QListWidget()
        all_tags = sorted({t for p in self.pages.values() for t in p["tags"]})
        self.tag_list.addItems([f"#{t}" for t in all_tags])
        self.tag_list.itemClicked.connect(lambda it: self.show_tag(it.text().lstrip("#")))
        self.graph = _GraphView(self.pages, self.load_page)
        self.nav.addTab(self.page_list, "Pages")
        self.nav.addTab(self.tag_list, "Tags")
        self.nav.addTab(self.graph, "Graph")
        split.addWidget(self.nav)

        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setOpenExternalLinks(False)
        self.view.setMinimumWidth(380)
        self.view.anchorClicked.connect(self._on_anchor)
        split.addWidget(self.view)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 780])  # ensure the reading pane is populated
        self._split = split

        if self.pages:
            self.load_page("Home" if "Home" in self.pages else sorted(self.pages)[0])
        else:
            self.view.setMarkdown("# User manual not found\n\nThe `docs/` folder "
                                  "was not found next to the application.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # the left pane may be dragged out, but never past half the window
        self.nav.setMaximumWidth(max(220, self.width() // 2))

    # -- rendering -----------------------------------------------------------

    def _render(self, entry):
        kind, value = entry
        if kind == "page":
            data = self.pages.get(value)
            self.view.setMarkdown(to_markdown(data["raw"]) if data else f"# {value}\n\n*Missing page.*")
            self.setWindowTitle(f"DSI Redline — User Manual — {value}")
        else:  # tag
            names = sorted(n for n, p in self.pages.items() if value in p["tags"])
            body = "\n".join(f"- [[{n}]]" for n in names) or "*No pages.*"
            self.view.setMarkdown(to_markdown(f"# Tag: #{value}\n\nPages tagged `#{value}`:\n\n{body}"))
            self.setWindowTitle(f"DSI Redline — User Manual — #{value}")
        self._update_nav_actions()

    def _push(self, entry):
        # truncate any forward history, then append
        self._history = self._history[: self._hindex + 1]
        self._history.append(entry)
        self._hindex = len(self._history) - 1
        self._render(entry)

    def load_page(self, name, record=True):
        if record:
            self._push(("page", name))
        else:
            self._render(("page", name))

    def show_tag(self, tag):
        self._push(("tag", tag))

    def go_back(self):
        if self._hindex > 0:
            self._hindex -= 1
            self._render(self._history[self._hindex])

    def go_forward(self):
        if self._hindex < len(self._history) - 1:
            self._hindex += 1
            self._render(self._history[self._hindex])

    def _update_nav_actions(self):
        self.act_back.setEnabled(self._hindex > 0)
        self.act_fwd.setEnabled(self._hindex < len(self._history) - 1)

    # -- links ---------------------------------------------------------------

    def _on_anchor(self, url: QUrl):
        s = url.toString()
        if s.startswith("vault:"):
            self.load_page(unquote(s[len("vault:"):]))
        elif s.startswith("tag:"):
            self.show_tag(unquote(s[len("tag:"):]))
        else:
            QDesktopServices.openUrl(url)


class _GraphView(QGraphicsView):
    """Force-directed graph of pages and their [[links]].

    Connected pages cluster together (so the layout reads like an Obsidian graph
    rather than a rigid ring). Theme-aware, zoomable with Ctrl+wheel, fits the
    pane as it's resized, and hovering a node highlights its linked neighbours.
    """

    EDGE = QColor(140, 140, 140)
    EDGE_HI = QColor(232, 145, 30)

    def __init__(self, pages: dict, on_click):
        super().__init__()
        from PySide6.QtGui import QPainter, QPalette
        self.setRenderHint(QPainter.Antialiasing)
        self.on_click = on_click
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        pal = self.palette()
        self.setBackgroundBrush(pal.base())              # match the OS theme
        text_color = pal.color(QPalette.WindowText)      # contrasts the base

        scene = QGraphicsScene(self)
        self.setScene(scene)
        names = sorted(pages)

        # adjacency + undirected edge list (names only)
        self._adj = {nm: set() for nm in names}
        edge_pairs = []
        seen = set()
        for name in names:
            for tgt in pages[name]["links"]:
                if tgt in self._adj and (name, tgt) not in seen and (tgt, name) not in seen:
                    seen.add((name, tgt))
                    edge_pairs.append((name, tgt))
                    self._adj[name].add(tgt)
                    self._adj[tgt].add(name)

        pos = self._force_layout(names, self._adj)

        self._edges = []           # (a, b, lineItem)
        for a, b in edge_pairs:
            line = scene.addLine(pos[a].x(), pos[a].y(), pos[b].x(), pos[b].y(),
                                 QPen(self.EDGE, 0))
            line.setZValue(0)
            self._edges.append((a, b, line))

        self._nodes = {}
        for name in names:
            node = _NodeItem(name, self, text_color)
            node.setPos(pos[name])
            scene.addItem(node)
            self._nodes[name] = node

        margin = 60
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))

    # -- layout --------------------------------------------------------------

    @staticmethod
    def _force_layout(names, adj, iterations=160):
        """Deterministic Fruchterman-Reingold layout (connected nodes cluster)."""
        n = len(names)
        if n == 0:
            return {}
        if n == 1:
            return {names[0]: QPointF(0, 0)}
        # deterministic seed: a tight circle, then relax
        pos = {nm: [120 * math.cos(2 * math.pi * i / n),
                    120 * math.sin(2 * math.pi * i / n)]
               for i, nm in enumerate(names)}
        k = math.sqrt((640.0 * 640.0) / n)      # ideal edge length
        temp = 180.0
        for _ in range(iterations):
            disp = {nm: [0.0, 0.0] for nm in names}
            for i in range(n):
                for j in range(i + 1, n):
                    u, v = names[i], names[j]
                    dx = pos[u][0] - pos[v][0]
                    dy = pos[u][1] - pos[v][1]
                    dist = math.hypot(dx, dy) or 0.01
                    rep = (k * k) / dist
                    ux, uy = dx / dist, dy / dist
                    disp[u][0] += ux * rep; disp[u][1] += uy * rep
                    disp[v][0] -= ux * rep; disp[v][1] -= uy * rep
            for u in names:
                for v in adj[u]:
                    if u < v:
                        dx = pos[u][0] - pos[v][0]
                        dy = pos[u][1] - pos[v][1]
                        dist = math.hypot(dx, dy) or 0.01
                        att = (dist * dist) / k
                        ux, uy = dx / dist, dy / dist
                        disp[u][0] -= ux * att; disp[u][1] -= uy * att
                        disp[v][0] += ux * att; disp[v][1] += uy * att
            for nm in names:
                dx, dy = disp[nm]
                d = math.hypot(dx, dy) or 0.01
                step = min(d, temp)
                pos[nm][0] += dx / d * step
                pos[nm][1] += dy / d * step
            temp = max(2.0, temp * 0.95)
        return {nm: QPointF(p[0], p[1]) for nm, p in pos.items()}

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        rect = self.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if not rect.isEmpty():
            self.fitInView(rect, Qt.KeepAspectRatio)

    # -- hover highlighting --------------------------------------------------

    def set_hover(self, name):
        neighbors = self._adj.get(name, set())
        for nm, node in self._nodes.items():
            if nm == name:
                node.set_fill(_NodeItem.HOVER)
            elif nm in neighbors:
                node.set_fill(_NodeItem.NEIGHBOR)
            else:
                node.set_fill(_NodeItem.DEFAULT)
        for a, b, line in self._edges:
            on = name in (a, b)
            line.setPen(QPen(self.EDGE_HI if on else self.EDGE, 2 if on else 0))

    def clear_hover(self):
        for node in self._nodes.values():
            node.set_fill(_NodeItem.DEFAULT)
        for _a, _b, line in self._edges:
            line.setPen(QPen(self.EDGE, 0))

    # -- zoom ----------------------------------------------------------------

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)
