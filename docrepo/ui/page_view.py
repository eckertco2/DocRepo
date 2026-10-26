"""The browse tool's detail pane: a QTextBrowser that draws the small pictures a task page names (release 5.21, the visual
overhaul's O9), and says when its width crosses one at which the task page lays itself out differently.

The page's HTML comes from ``docrepo/detail.py``, which has no Qt in it. Qt's rich text has no rounded shapes, so the
page names its pictures and this view draws them:

- ``avatar:TB``, a person's initials in a circle; ``avatar:me``, the owner, as a figure;
- ``mark:ip``, a task's state (``ns``, ``ip``, ``pk`` or ``cl``), from the state icons;
- ``progress:1:4``, a thin bar, 1 of 4 filled.
"""
from __future__ import annotations

from urllib.parse import unquote

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from docrepo.detail import PROGRESS_WIDTH, SIDE_BY_SIDE, WIDE_PAGE
from docrepo.ui import tokens
from docrepo.ui.icons import tinted

AVATAR = 20
MARK = 14
PROGRESS_HEIGHT = 4
#: The state marks' colours: secondary text, the accent, Parked's, and secondary text again.
MARK_COLOURS = {"ns": "text2", "ip": "accent", "pk": "#585a70", "cl": "text2"}


def layout_of(width: int) -> int:
    """Which way a task page of this width lays itself out: stacked, When and Who side by side, or two columns."""
    return 2 if width >= WIDE_PAGE else 1 if width >= SIDE_BY_SIDE else 0


def _colour(name: str) -> QColor:
    return QColor(tokens.LIGHT.get(name, name))


def _canvas(width: int, height: int, scale: float) -> tuple[QImage, QPainter]:
    image = QImage(round(width * scale), round(height * scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    image.setDevicePixelRatio(scale)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return image, painter


def avatar(key: str, scale: float) -> QImage:
    """Initials in a neutral circle, or the owner's figure on the selected tint."""
    image, p = _canvas(AVATAR, AVATAR, scale)
    me = key == "me"
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_colour("selected" if me else "pressed"))
    p.drawEllipse(QRectF(0, 0, AVATAR, AVATAR))
    if me:
        p.drawPixmap(QPointF(3, 3), tinted("person", tokens.LIGHT["accent"], AVATAR - 6, scale))
    else:
        font = QFont("Segoe UI")
        font.setPixelSize(8 if len(key) > 1 else 9)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_colour("text"))
        p.drawText(QRectF(0, 0, AVATAR, AVATAR), Qt.AlignmentFlag.AlignCenter, key[:2])
    p.end()
    return image


def mark(state: str, scale: float) -> QImage:
    image, p = _canvas(MARK, MARK, scale)
    colour = MARK_COLOURS.get(state, "text2")
    p.drawPixmap(QPointF(0, 0), tinted(f"state-{state}", tokens.LIGHT.get(colour, colour), MARK, scale))
    p.end()
    return image


def progress(done: int, total: int, width: int, scale: float) -> QImage:
    """A thin bar on the hover grey, the closed share filled in the success green."""
    image, p = _canvas(width, PROGRESS_HEIGHT, scale)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_colour("pressed"))
    p.drawRoundedRect(QRectF(0, 0, width, PROGRESS_HEIGHT), 2, 2)
    if total and done:
        p.setBrush(_colour("success"))
        p.drawRoundedRect(QRectF(0, 0, width * min(done, total) / total, PROGRESS_HEIGHT), 2, 2)
    p.end()
    return image


def picture(url: QUrl, scale: float) -> QImage | None:
    """The picture a page names, or None for any other address."""
    kind, key = url.scheme(), unquote(url.path())
    if kind == "avatar" and key:
        return avatar(key, scale)
    if kind == "mark" and key in MARK_COLOURS:
        return mark(key, scale)
    if kind == "progress":
        try:
            done, total = (int(x) for x in key.split(":"))
        except ValueError:
            return None
        return progress(done, total, PROGRESS_WIDTH, scale)
    return None


class PageView(QTextBrowser):
    """The detail pane. ``layout_changed`` fires when a resize takes the page across SIDE_BY_SIDE or WIDE_PAGE, so the
    browse window can draw a task page again in its other layout."""

    layout_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._images: dict[tuple[str, float], QImage] = {}
        self._layout = -1

    def page_width(self) -> int:
        """The width the page's HTML has: the viewport's, less the document's margins."""
        return self.viewport().width() - 2 * round(self.document().documentMargin())

    def loadResource(self, kind: int, url: QUrl):  # noqa: N802 - Qt's name
        if getattr(kind, "value", kind) == QTextDocument.ResourceType.ImageResource.value:
            scale = max(1.0, self.devicePixelRatioF())
            key = (url.toString(), scale)
            if key not in self._images:
                image = picture(url, scale)
                if image is None:
                    return super().loadResource(kind, url)
                self._images[key] = image
            return self._images[key]
        return super().loadResource(kind, url)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        now = layout_of(self.page_width())
        if self._layout not in (-1, now):
            self._layout = now
            self.layout_changed.emit()
        self._layout = now
