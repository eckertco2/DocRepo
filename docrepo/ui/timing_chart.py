"""The chart of a template's timing (release 5.51, decision 255), painted the same in the Timing window's lanes and as pictures on the
template's page. Qt's rich text has no shapes, so a page names its pictures, as ``docrepo/ui/page_view.py`` says, and they're drawn here."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from docrepo import timing
from docrepo.timing import Scale
from docrepo.ui import tokens


def _colour(name: str) -> QColor:
    return QColor(tokens.LIGHT[name])


def paint_lines(p: QPainter, width: float, height: float, scale: Scale) -> None:
    """The weeks' faint lines, and the anchor's in the accent."""
    for weeks in scale.ticks():
        x = scale.at(weeks * scale.week) * width
        p.setPen(QPen(_colour("accent") if weeks == 0 else _colour("stroke"), 1))
        p.drawLine(QPointF(x, 0), QPointF(x, height))


def paint_lane(p: QPainter, width: float, height: float, scale: Scale | None, bar: tuple[int, int] | None, kind: str) -> None:
    """One row's lane: its bar across the weeks' lines. ``kind`` is ``a`` for the anchor, ``g`` for a row that spans its subtasks, a thin
    line, or ``b`` for any other."""
    if scale is None:
        return
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_lines(p, width, height, scale)
    if bar is None:
        return
    left, right = scale.at(bar[0]) * width, scale.at(bar[0] + bar[1]) * width
    span = max(3.0, right - left)
    p.setPen(Qt.PenStyle.NoPen)
    if kind == "g":
        p.setBrush(_colour("text2"))
        p.drawRoundedRect(QRectF(left, height / 2 - 1, span, 2), 1, 1)
        return
    p.setBrush(_colour("accent") if kind == "a" else _colour("control"))
    p.drawRoundedRect(QRectF(left, height / 2 - 5, span, 10), 2, 2)


def paint_ruler(p: QPainter, width: float, height: float, scale: Scale | None) -> None:
    """The weeks' names over the lanes: "−4 wk", "Anchor", "+2 wk"."""
    if scale is None:
        return
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Segoe UI")
    font.setPixelSize(10)
    for weeks in scale.ticks():
        text = timing.tick_label(weeks)
        font.setWeight(QFont.Weight.DemiBold if weeks == 0 else QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(_colour("accent") if weeks == 0 else _colour("text2"))
        room = p.fontMetrics().horizontalAdvance(text) + 2
        x = min(max(0.0, scale.at(weeks * scale.week) * width - room / 2), width - room)
        p.drawText(QRectF(x, 0, room, height), Qt.AlignmentFlag.AlignCenter, text)


def picture(address: str, scale: float) -> QImage | None:
    """A lane or the ruler, as a page names it. None if the address isn't one."""
    parsed = timing.parse_lane(address)
    if parsed is None:
        return None
    chart, bar, kind = parsed
    height = timing.LANE_HEIGHT
    image = QImage(round(timing.LANE_WIDTH * scale), round(height * scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    image.setDevicePixelRatio(scale)
    p = QPainter(image)
    if kind == "r":
        paint_ruler(p, timing.LANE_WIDTH, height, chart)
    else:
        paint_lane(p, timing.LANE_WIDTH, height, chart, bar, kind)
    p.end()
    return image
