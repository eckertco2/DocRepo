"""The browse window's one content surface (release 5.182, the redesign's decision 851, the content as an inset card).

The list and the page sit on one white card with round corners, set into the window's grey frame at the right and the
bottom, with one hairline between them. The card holds the browse window's one splitter (``browse.split``, read as one
splitter of three or four panes by the workspace and the task tile) and paints behind it; it never wraps a pane.

Every pane stays opaque and square, ``CARD_PAD`` px in from the card's outer edge: a square set ``d`` px in from both
edges of a corner of radius ``r`` lies wholly inside the curve when ``d >= r * (1 - 1/sqrt(2))``, 2.93 px for 10. So no
pane, scroll bar or row's fill reaches a corner, nothing is drawn over a pane, and Qt keeps scrolling a list by moving
its pixels.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from docrepo.ui import tokens

CARD_GAP = 8                  # between the card and the window's right and bottom edges (and its left, with no sidebar)
CARD_EDGE = 1                 # the card's hairline
CARD_CLEAR = 3                # white between the hairline and a pane, so a square pane clears a 10 px corner
CARD_PAD = CARD_EDGE + CARD_CLEAR


class ContentCard(QWidget):
    """The browse window's one content surface (release 5.182, decision 851). ``split``'s first child is the sidebar,
    which sits on the frame; the rest are the card's panes."""

    def __init__(self, split: QSplitter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contentCard")
        self.split = split
        lay = QVBoxLayout(self)
        lay.setSpacing(0)
        lay.addWidget(split)
        split.splitterMoved.connect(lambda *_: self.update())
        split.installEventFilter(self)
        self.sync()

    def _sidebar_shown(self) -> bool:
        return self.split.count() > 0 and not self.split.widget(0).isHidden()

    def sync(self) -> None:
        """The left margin, by whether the sidebar shows: none beside it, the frame's 8 px without it."""
        left = 0 if self._sidebar_shown() else CARD_GAP + CARD_PAD
        self.layout().setContentsMargins(left, CARD_PAD, CARD_GAP + CARD_PAD, CARD_GAP + CARD_PAD)
        self.update()

    def _panes(self) -> list[QWidget]:
        """The card's panes on show, left to right: the splitter's children after the sidebar."""
        return [w for w in (self.split.widget(i) for i in range(1, self.split.count())) if not w.isHidden()]

    def card_rect(self) -> QRect | None:
        """The card, in this widget's coordinates; None with no pane on show."""
        panes = self._panes()
        if not panes:
            return None
        left = panes[0].mapTo(self, panes[0].rect().topLeft()).x() - CARD_PAD
        return QRect(left, 0, self.width() - CARD_GAP - left, self.height() - CARD_GAP)

    def hairlines(self) -> list[int]:
        """The x of each line between two panes on show: one between the list and the page, none while a view has no
        page or the workspace is open alone. Never the handle between the sidebar and the card."""
        out: list[int] = []
        seen = False
        for i in range(1, self.split.count()):
            if self.split.widget(i).isHidden():
                continue
            if seen:
                handle = self.split.handle(i)
                out.append(handle.mapTo(self, handle.rect().topLeft()).x() + handle.width() // 2)
            seen = True
        return out

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        rect = self.card_rect()
        if rect is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(tokens.colour("stroke")), CARD_EDGE))
        p.setBrush(QColor(tokens.colour("content")))
        p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), tokens.RADIUS_L, tokens.RADIUS_L)
        # the splitter's handle is only as tall as the panes: the card draws the whole line, to its edge at the top and bottom
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(QColor(tokens.colour("stroke")), CARD_EDGE))
        for x in self.hairlines():
            p.drawLine(x, rect.top() + 1, x, rect.bottom() - 1)
        p.end()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        # Qt posts a LayoutRequest to the splitter when a pane is shown or hidden
        if watched is self.split and event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize):
            self.update()
        return super().eventFilter(watched, event)


__all__ = ["CARD_CLEAR", "CARD_EDGE", "CARD_GAP", "CARD_PAD", "ContentCard"]
