"""A lightweight startup splash screen with a progress bar + status line.

Kept dependency-light (Qt only) so it can be shown *before* the heavy modules
(PySide widgets, PyMuPDF, the panels) are imported, giving the user immediate
feedback while the app loads.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QProgressBar, QApplication,
)

# Brand palette (from the DSI Redline icon)
NAVY = "#16233F"
ORANGE = "#E8772E"


class SplashScreen(QWidget):
    def __init__(self, app_name: str, version: str, icon=None):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(440, 280)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 28, 30, 24)
        lay.setSpacing(8)

        if icon is not None:
            ic = QLabel()
            ic.setPixmap(icon.pixmap(QSize(96, 96)))
            ic.setAlignment(Qt.AlignCenter)
            lay.addWidget(ic)

        title = QLabel(app_name)
        title.setAlignment(Qt.AlignCenter)
        tf = QFont()
        tf.setPointSize(20)
        tf.setBold(True)
        title.setFont(tf)
        lay.addWidget(title)

        ver = QLabel(f"Version {version}")
        ver.setAlignment(Qt.AlignCenter)
        ver.setObjectName("ver")
        lay.addWidget(ver)

        lay.addStretch(1)

        self.status = QLabel("Starting up…")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)

        self.setStyleSheet(f"""
            QLabel {{ color: white; background: transparent; }}
            QLabel#ver {{ color: #9fb0cf; }}
            QProgressBar {{ background: #2a3b5f; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {ORANGE}; border-radius: 4px; }}
        """)
        self._center()

    # -- painting (rounded navy panel) --------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(NAVY))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)

    def _center(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)

    # -- public API ----------------------------------------------------------

    def message(self, text: str, percent: int | None = None):
        """Show a one-line description of the current step (and advance the bar)."""
        self.status.setText(text)
        if percent is not None:
            self.bar.setValue(max(0, min(100, int(percent))))
        QApplication.processEvents()

    def finish(self, window=None):
        self.message("Ready.", 100)
        self.close()
        if window is not None:
            try:
                window.activateWindow()
                window.raise_()
            except Exception:
                pass
