"""The browse tool's detail pane: a QTextBrowser that draws the small pictures a task page names (release 5.21, the visual
overhaul's O9), and says when its width crosses one at which the task page lays itself out differently.

The page's HTML comes from ``docrepo/detail.py``, which has no Qt in it. Qt's rich text has no rounded shapes, so the
page names its pictures and this view draws them:

- ``avatar:TB``, a person's initials in a circle; ``avatar:me``, the owner, as a figure;
- ``mark:ip``, a task's state (``ns``, ``ip``, ``pk`` or ``cl``), from the state icons;
- ``progress:1:4``, a thin bar, 1 of 4 filled;
- ``timing:...``, a lane of a template's chart, or its ruler (release 5.51);
- ``chev:right`` and ``chev:down``, the icons' chevrons for a fold or a menu (release 5.59);
- ``lk:link``, ``lk:folder``, ``lk:note``, ``lk:ref`` and ``lk:pin``, the marks of the Links group's rows (release 5.67), and
  ``lk:decision``, a decision's in the Decisions section (release 5.124);
- ``ft:pdf``, ``ft:sheet`` and the other file types, a file's mark in its type's colour, for the Files group (release 5.114).
"""
from __future__ import annotations

from urllib.parse import unquote

from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from docrepo.detail import PROGRESS_WIDTH, SIDE_BY_SIDE, WIDE_PAGE
from docrepo.file_rows import type_colour, type_icon
from docrepo.ui import tokens
from docrepo.ui.icons import tinted
from docrepo.ui.timing_chart import picture as timing_picture

AVATAR = 20
MARK = 14
PROGRESS_HEIGHT = 4
#: The state marks' colours: secondary text, the accent, Parked's, and secondary text again.
MARK_COLOURS = {"ns": "text2", "ip": "accent", "pk": "parked", "cl": "text2"}


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
        font.setPixelSize(10)  # as large as two letters fit in the circle; it's a mark, with the name beside it
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


#: The Links group's marks (release 5.67), and the Decisions section's (release 5.124): the icon each draws, and its colour.
LINK_MARKS = {"link": ("link", "text2"), "folder": ("folder", "text2"), "note": ("note", "text2"), "ref": ("link", "accent"), "pin": ("pin", "accent"),
              "decision": ("decision", "text2")}


def link_mark(key: str, scale: float) -> QImage:
    name, colour = LINK_MARKS[key]
    image, p = _canvas(MARK, MARK, scale)
    p.drawPixmap(QPointF(0, 0), tinted(name, tokens.LIGHT[colour], MARK, scale))
    p.end()
    return image


#: A file's type mark (release 5.114, decision 429): drawn at the size the lists draw it, in its type's colour.
FILE_MARK = 16


def file_mark(kind: str, scale: float) -> QImage:
    image, p = _canvas(FILE_MARK, FILE_MARK, scale)
    p.drawPixmap(QPointF(0, 0), tinted(type_icon(kind), tokens.LIGHT[type_colour(kind)], FILE_MARK, scale))
    p.end()
    return image


#: A tile's marks on a page (release 5.138, the task tile plan's decisions 566 to 570): the icon each draws, its colour and size.
TILE_MARKS = {"sun": ("sun", "text2", 14), "agenda": ("agenda", "text2", 14), "waiting": ("waiting", "text2", 14),
              "waiting-late": ("waiting", "caution", 14), "urgent": ("urgent", "critical", 13), "parents": ("parents", "text2", 13),
              "blank": ("", "", 14)}


def tile_mark(key: str, scale: float) -> QImage:
    name, colour, size = TILE_MARKS[key]
    image, p = _canvas(size, size, scale)
    if name:
        p.drawPixmap(QPointF(0, 0), tinted(name, tokens.LIGHT[colour], size, scale))
    p.end()
    return image


def chevron(direction: str, scale: float) -> QImage:
    image, p = _canvas(MARK, MARK, scale)
    p.drawPixmap(QPointF(0, 0), tinted(f"chevron-{direction}", tokens.LIGHT["text2"], MARK, scale))
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


#: The quick summary's pictures (release 5.131): a priority's colour, the trend's size and the header's face.
BUCKET_COLOURS = {"critical": "pri_critical", "high": "pri_high", "medium": "pri_medium", "parking": "pri_parking", "none": "scroll"}
SPARK_W, SPARK_H, STACK_H, SWATCH, FACE = 120, 26, 12, 10, 40
FACE_ICONS = {"label": "labels", "agenda": "agenda", "tag": "tagged", "many": "people"}


def stack(counts: list[int], width: int, scale: float) -> QImage:
    """A label's bar on Where they stand (decision 532): its segments by priority, Critical first, 2 px apart, the far end
    rounded."""
    image, p = _canvas(width, STACK_H, scale)
    p.setPen(Qt.PenStyle.NoPen)
    total = sum(counts) or 1
    gaps = 2 * max(0, sum(1 for n in counts if n) - 1)
    x = 0.0
    shown = [(b, n) for b, n in zip(BUCKET_COLOURS, counts, strict=False) if n]
    for i, (bucket, n) in enumerate(shown):
        w = (width - gaps) * n / total
        p.setBrush(_colour(BUCKET_COLOURS[bucket]))
        if i == len(shown) - 1:
            p.drawRoundedRect(QRectF(x, 0, w, STACK_H), 3, 3)
            p.drawRect(QRectF(x, 0, min(w, 4), STACK_H))  # only the far end is rounded
        else:
            p.drawRect(QRectF(x, 0, w, STACK_H))
        x += w + 2
    p.end()
    return image


def spark(values: list[int], scale: float) -> QImage:
    """The open count's last weeks (decision 532): a line in the accent over a light fill, the last point marked."""
    image, p = _canvas(SPARK_W, SPARK_H, scale)
    if len(values) >= 2:
        lo, hi = min(values) - 1, max(values) + 1
        pts = [QPointF(2 + i * (SPARK_W - 6) / (len(values) - 1), 2 + (SPARK_H - 4) * (1 - (v - lo) / (hi - lo))) for i, v in enumerate(values)]
        area = QPainterPath(QPointF(pts[0].x(), SPARK_H))
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(QPointF(pts[-1].x(), SPARK_H))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_colour("info_bg"))
        p.drawPath(area)
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        p.setPen(QPen(_colour("accent"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_colour("accent"))
        p.drawEllipse(pts[-1], 3, 3)
    p.end()
    return image


def swatch(bucket: str, scale: float) -> QImage:
    image, p = _canvas(SWATCH, SWATCH, scale)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_colour(BUCKET_COLOURS[bucket]))
    p.drawRoundedRect(QRectF(0, 0, SWATCH, SWATCH), 2, 2)
    p.end()
    return image


def face(key: str, scale: float) -> QImage:
    """The quick summary's header picture: a person's initials in a circle on the accent's tint, or a label's or an
    agenda's icon on a grey rounded square."""
    image, p = _canvas(FACE, FACE, scale)
    p.setPen(Qt.PenStyle.NoPen)
    if key in FACE_ICONS:  # a label's, an agenda's, a tag's or several's mark (release 5.131)
        p.setBrush(_colour("base"))
        p.drawRoundedRect(QRectF(0, 0, FACE, FACE), 9, 9)
        p.drawPixmap(QPointF(10, 10), tinted(FACE_ICONS[key], tokens.LIGHT["text2"], 20, scale))
    else:
        p.setBrush(_colour("info_bg"))
        p.drawEllipse(QRectF(0, 0, FACE, FACE))
        f = QFont("Segoe UI", 12)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(_colour("accent"))
        p.drawText(QRectF(0, 0, FACE, FACE), Qt.AlignmentFlag.AlignCenter, key[:3])
    p.end()
    return image


def edge(bucket: str, scale: float) -> QImage:
    """A row's priority at its left edge (release 5.81's mark), 3 by 18, on the quick summary's rows."""
    image, p = _canvas(3, 18, scale)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_colour(BUCKET_COLOURS[bucket]))
    p.drawRoundedRect(QRectF(0, 0, 3, 18), 1.5, 1.5)
    p.end()
    return image


def _ints(text: str) -> list[int] | None:
    try:
        return [int(x) for x in text.split(",") if x != ""]
    except ValueError:
        return None


def picture(url: QUrl, scale: float) -> QImage | None:
    """The picture a page names, or None for any other address."""
    kind, key = url.scheme(), unquote(url.path())
    if kind == "stack":  # "stack:0,2,2,0,0:300", the quick summary's bars (release 5.131)
        counts, _, width = key.partition(":")
        values = _ints(counts)
        return stack(values, max(4, min(int(width), 800)), scale) if values and width.isdigit() and len(values) == len(BUCKET_COLOURS) else None
    if kind == "spark":
        values = _ints(key)
        return spark(values, scale) if values else None
    if kind == "swatch" and key in BUCKET_COLOURS:
        return swatch(key, scale)
    if kind == "face" and key:
        return face(key, scale)
    if kind == "edge" and key in BUCKET_COLOURS and key != "none":
        return edge(key, scale)
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
    if kind == "timing":
        return timing_picture(key, scale)
    if kind == "tm" and key in TILE_MARKS:
        return tile_mark(key, scale)
    if kind == "chev" and key in ("right", "down"):
        return chevron(key, scale)
    if kind == "lk" and key in LINK_MARKS:
        return link_mark(key, scale)
    if kind == "ft" and key.isalpha():
        return file_mark(key, scale)
    return None


class PageView(QTextBrowser):
    """The detail pane. ``layout_changed`` fires when a resize takes the page across SIDE_BY_SIDE or WIDE_PAGE, so the
    browse window can draw a task page again in its other layout."""

    layout_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._images: dict[tuple[str, float], QImage] = {}
        self._layout = -1
        #: A right-click on a link (release 5.138, the task tile plan's decision 577): given its address and where, it shows a
        #: menu and says True, as the browse window does for a task's ``task:`` or ``state:`` link; else the page's own menu.
        self.link_menu: Callable[[str, QPoint], bool] | None = None

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

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt's name
        href = self.anchorAt(event.pos())
        if href and self.link_menu is not None and self.link_menu(href, event.globalPos()):
            event.accept()
            return
        super().contextMenuEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        now = layout_of(self.page_width())
        if self._layout not in (-1, now):
            self._layout = now
            self.layout_changed.emit()
        self._layout = now


class FitPageView(PageView):
    """A part of the task page as tall as its HTML, with no scroll bar of its own (release 5.25; here since 5.84, for
    the header's parts too)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("fitView")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.document().documentLayout().documentSizeChanged.connect(lambda _: self._fit())

    def set_margins(self, left: int, top: int, right: int, bottom: int, inner: int = 4) -> None:
        """Margins round the HTML on each side, rather than the document's one margin for all four (release 5.84): the
        header's parts keep the page's left edge without the document margin's height above and below each."""
        self.document().setDocumentMargin(inner)
        self.setViewportMargins(max(0, left - inner), max(0, top - inner), max(0, right - inner), max(0, bottom - inner))
        self._fit()

    def page_width(self) -> int:
        return self.viewport().width() - 2 * round(self.document().documentMargin())

    def _fit(self) -> None:
        h = int(self.document().size().height()) + (self.height() - self.viewport().height())
        if h != self.height():
            self.setFixedHeight(max(h, 8))
