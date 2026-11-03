"""Capacity's half of the Timeline page (release 5.40): the team chart and a row per person, on the timeline's own dates.

The chart above and these two widgets share one scale (``timeline_view._Scale``), so a week's cell lies straight under its
place on the chart, and the room for a scroll bar is kept whether or not one shows. ``docrepo/load.py`` says what's in each
cell; this module paints it and handles the mouse and keys. A cell is a tint with one number when it fits (decisions 230 and
V5); clicking one sends ``picked`` for the spotlight (decision 233), and a person's name sends ``solo`` (decision 232).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from docrepo import load
from docrepo.dates import short
from docrepo.load import Bucket, Cells
from docrepo.model import Model, Person
from docrepo.timeline import Band, Timeline
from docrepo.ui import tokens
from docrepo.ui.tokens import C

TINTS = {"t1": C.load1, "t2": C.load2, "t3": C.load3, "t4": C.load4, "t5": C.load5, "none": C.load1}
INKS = {"t5": C.load5_ink, "none": C.text2}
#: A number shows only when its cell has this much to spare.
PAD = 6


def _faint(colour: str, alpha: int) -> QColor:
    c = QColor(colour)
    c.setAlpha(alpha)
    return c


@dataclass(frozen=True)
class Spot:
    """The week the spotlight is on (decision 233): whose ("" is the team's), and its days, the last being the day before ``end``."""

    person: str
    first: date
    end: date


@dataclass
class StripData:
    """What both widgets draw."""

    model: Model | None = None
    today: date = date.min
    cells: Cells = field(default_factory=dict)
    people: list[Person] = field(default_factory=list)
    buckets: list[Bucket] = field(default_factory=list)
    unit: str = "pct"
    by_group: bool = False
    adds: set[tuple[str, date]] = field(default_factory=set)  # the weeks the selected bar adds to
    spot: Spot | None = None
    hover: tuple[date, date] | None = None
    was: Cells | None = None  # in a what-if (release 5.64), the real plan's hours, outlined behind the team chart's columns


class _Strip(QWidget):
    """What the two widgets share: the data, placing days, the bands down them, and hovering a cell."""

    picked = Signal(str, object, object)
    hovered = Signal(object)

    def __init__(self, scale) -> None:
        super().__init__()
        self.scale = scale
        self.data = StripData()
        self.setMouseTracking(True)

    @property
    def tl(self) -> Timeline | None:
        return self.scale.tl

    def _x(self, day: date) -> float:
        return self.scale.x(self, day)

    def _right(self) -> float:
        return self.scale.right(self)

    def _bucket_at(self, x: float) -> Bucket | None:
        if self.tl is None or x < self.scale.NAME_W or x >= self._right():
            return None
        day = self.scale.day_at(self, x)
        return next((b for b in self.data.buckets if b.holds(day)), None)

    def _small(self) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(tokens.CAPTION)
        return f

    def _paint_bands(self, p: QPainter, top: float, bottom: float) -> None:
        """Over the cells: the plant events' bands, the spotlight, the week under the mouse and the today line."""
        tl = self.tl
        if tl is None:
            return
        band: Band
        for band in tl.events:
            x0, x1 = self._x(band.start), self._x(band.end + timedelta(days=1))
            p.fillRect(QRectF(x0, top, max(2.0, x1 - x0), bottom - top), _faint(C.event, 26))
            p.setPen(QPen(_faint(C.event, 150), 1))
            p.drawLine(QPointF(x0, top), QPointF(x0, bottom))
            p.drawLine(QPointF(x1, top), QPointF(x1, bottom))
        d = self.data
        if d.hover is not None:
            x0, x1 = self._x(d.hover[0]), self._x(d.hover[1])
            p.fillRect(QRectF(x0, top, x1 - x0, bottom - top), _faint(C.text, 14))
        if d.spot is not None:
            x0, x1 = self._x(d.spot.first), self._x(d.spot.end)
            p.fillRect(QRectF(x0, top, x1 - x0, bottom - top), _faint(C.accent, 26))
            p.setPen(QPen(QColor(C.accent), 1))
            p.drawLine(QPointF(x0, top), QPointF(x0, bottom))
            p.drawLine(QPointF(x1, top), QPointF(x1, bottom))
        if tl.start <= d.today < tl.end:
            x = (self._x(d.today) + self._x(d.today + timedelta(days=1))) / 2
            p.setPen(QPen(QColor(C.accent), 2))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.hovered.emit(None)
        super().leaveEvent(event)


class CapacityTeam(_Strip):
    """The dates again, small, and the team chart: a column for each cell, the hours within people's capacity, those over it in
    red on top, and a line at the team's capacity (decision 231). It stays in place while the people's rows scroll."""

    MINI_H, TEAM_H = 18, 60

    def __init__(self, scale) -> None:
        super().__init__(scale)
        self.setFixedHeight(self.MINI_H + self.TEAM_H)

    def set_data(self, data: StripData) -> None:
        self.data = data
        self.update()

    def _top(self) -> float:
        """The chart's scale, in hours: room for the tallest column and the capacity line."""
        d = self.data
        tallest = max((load.team_bucket(c, d.people, b)[0].total for c in (d.cells, d.was or {}) for b in d.buckets), default=0.0)
        return max(load.capacity_of(d.people), tallest, 1.0) * 1.08

    def column_rect(self, bucket: Bucket) -> QRectF:
        return QRectF(self._x(bucket.first), self.MINI_H, self._x(bucket.end) - self._x(bucket.first), self.TEAM_H)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        tl, d = self.tl, self.data
        if tl is None:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.content))
        right = self._right()
        small = self._small()
        p.setFont(small)
        p.setPen(QPen(QColor(C.stroke_strong), 1))
        p.drawLine(QPointF(0, 0.5), QPointF(right, 0.5))
        p.drawLine(QPointF(0, self.MINI_H - 0.5), QPointF(right, self.MINI_H - 0.5))
        # The dates, small: weeks while they fit, or months.
        p.setPen(QColor(C.text2))
        free = 0.0
        for day in (tl.week_starts() if tl.weeks <= 26 else tl.months()):
            x = self._x(day) + 3
            text = short(day, d.today) if tl.weeks <= 26 else (f"{day.strftime('%b')} {day.year}" if day.month == 1 or not free else day.strftime("%b"))
            if x >= free:
                p.drawText(QRectF(x, 0, 90, self.MINI_H), Qt.AlignmentFlag.AlignVCenter, text)
                free = x + p.fontMetrics().horizontalAdvance(text) + 10
        # Who it's about.
        bold = QFont(self.font())
        bold.setBold(True)
        p.setFont(bold)
        p.setPen(QColor(C.text))
        p.drawText(QRectF(12, self.MINI_H + 6, 60, 20), Qt.AlignmentFlag.AlignVCenter, "Team")
        p.setFont(small)
        p.setPen(QColor(C.text2))
        n, cap = len(d.people), load.capacity_of(d.people)
        unset = sum(1 for x in d.people if not x.hours)
        words = f"{n} {'person' if n == 1 else 'people'}" + (f", {cap:g} h a week" if cap else "")
        p.drawText(QRectF(12, self.MINI_H + 26, self.scale.NAME_W - 20, 16), Qt.AlignmentFlag.AlignVCenter, words)
        if unset:
            p.drawText(QRectF(12, self.MINI_H + 41, self.scale.NAME_W - 20, 16), Qt.AlignmentFlag.AlignVCenter, f"{unset} with no hours set")
        # The columns.
        top = self._top()
        floor = float(self.height() - 1)
        height = self.TEAM_H - 3
        for b in d.buckets:
            team, _ = load.team_bucket(d.cells, d.people, b)
            x0, x1 = self._x(b.first), self._x(b.end)
            w = max(1.0, x1 - x0 - (1 if x1 - x0 > 3 else 0))
            within, over = (team.total - team.over) / top * height, team.over / top * height
            if within > 0:
                p.fillRect(QRectF(x0, floor - within, w, within), QColor(C.bar_soft))
            if over > 0:
                p.fillRect(QRectF(x0, floor - within - over, w, over), QColor(C.critical))
            if d.was is not None:  # a what-if: the real plan's column, outlined behind, so the change shows
                real = load.team_bucket(d.was, d.people, b)[0].total / top * height
                if real > 0 and abs(real - within - over) > 0.5:
                    p.setPen(QPen(QColor(C.text2), 1, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(QRectF(x0 + 0.5, floor - real, w - 1, real))
        p.setPen(QPen(QColor(C.stroke), 1))
        p.drawLine(QPointF(0, floor + 0.5), QPointF(right, floor + 0.5))
        self._paint_bands(p, self.MINI_H, floor)
        if cap:
            y = floor - cap / top * height
            p.setPen(QPen(QColor(C.text), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(self.scale.NAME_W, y), QPointF(right, y))
        if d.spot is not None and not d.spot.person:
            bucket = next((b for b in d.buckets if b.first == d.spot.first), None)
            if bucket is not None:
                p.setPen(QPen(QColor(C.accent), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(self.column_rect(bucket).adjusted(1, 1, -1, -2))
        p.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        b = self._bucket_at(event.position().x())
        self.hovered.emit((b.first, b.end) if b else None)
        self.setCursor(Qt.CursorShape.PointingHandCursor if b else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        b = self._bucket_at(event.position().x())
        if b is not None and event.button() == Qt.MouseButton.LeftButton and event.position().y() >= self.MINI_H:
            self.picked.emit("", b.first, b.end)

    def event(self, e) -> bool:  # noqa: D102 - a column's hours
        if e.type() == QEvent.Type.ToolTip:
            b = self._bucket_at(e.pos().x())
            if b is None or e.pos().y() < self.MINI_H:
                QToolTip.hideText()
            else:
                QToolTip.showText(e.globalPos(), self.tip(b), self)
            return True
        return super().event(e)

    def tip(self, b: Bucket) -> str:
        d = self.data
        team, week = load.team_bucket(d.cells, d.people, b)
        when = f"{b.first.strftime('%B %Y')}, worst week {short(week, d.today)}" if b.month else f"Week of {short(b.first, d.today)}"
        cap = load.capacity_of(d.people)
        words = f"{when}: {round(team.total, 1):g} h" + (f" of {cap:g} h" if cap else "")
        words += f", {round(team.over, 1):g} h over people's own capacity" if team.over else ""
        if d.was is not None:
            real = load.team_week(d.was, d.people, week).total
            words += f". On the real plan: {round(real, 1):g} h" if abs(real - team.total) > 0.05 else ""
        return words


class CapacityRows(_Strip):
    """A row per person, under their group's heading when grouped: their name and hours a week, then a cell for each week or
    month. Up, Down, Left and Right move between cells, and Enter or Space picks one."""

    solo = Signal(str)

    ROW_H = 28

    def __init__(self, scale) -> None:
        super().__init__(scale)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Capacity: a row per person, a cell per week")
        self.lines: list[tuple[str, str, list[Person]]] = []  # ("group", its name, its people) or ("person", its ID, [the person])
        self.cur: tuple[int, int] | None = None  # the cell the keys are on: its line and its bucket
        self.hover_name = -1

    def set_data(self, data: StripData) -> None:
        self.data = data
        self.lines = []
        if data.by_group:
            groups = [g for g in dict.fromkeys(p.group or "" for p in data.people)]
            for g in sorted(groups, key=lambda x: (not x, x.lower())):
                members = [p for p in data.people if (p.group or "") == g]
                self.lines.append(("group", g or "No group", members))
                self.lines.extend(("person", p.id, [p]) for p in members)
        else:
            self.lines = [("person", p.id, [p]) for p in data.people]
        self.setFixedHeight(max(1, len(self.lines) * self.ROW_H))
        if self.cur is not None and (self.cur[0] >= len(self.lines) or self.cur[1] >= len(data.buckets)):
            self.cur = None
        self.update()

    def natural_height(self) -> int:
        return len(self.lines) * self.ROW_H

    def cell_rect(self, line: int, bucket: Bucket) -> QRectF:
        return QRectF(self._x(bucket.first), line * self.ROW_H, self._x(bucket.end) - self._x(bucket.first), self.ROW_H - 1)

    def line_of(self, person: str) -> int | None:
        return next((i for i, (kind, key, _) in enumerate(self.lines) if kind == "person" and key == person), None)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        tl, d = self.tl, self.data
        if tl is None:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.content))
        right = self._right()
        small, number = self._small(), tokens.numeric_font(tokens.CAPTION)
        strong = QFont(number)
        strong.setBold(True)
        for i, (kind, key, people) in enumerate(self.lines):
            top = i * self.ROW_H
            if kind == "group":
                p.fillRect(QRectF(0, top, right, self.ROW_H), QColor(C.base))
            elif i == self.hover_name:
                p.fillRect(QRectF(0, top, self.scale.NAME_W, self.ROW_H), QColor(C.hover))
            name, cap = (key, load.capacity_of(people)) if kind == "group" else (people[0].name, people[0].hours)
            font = QFont(self.font())
            font.setBold(kind == "group")
            p.setFont(font)
            p.setPen(QColor(C.text))
            words = f"{cap:g} h" if cap else "Hours not set"
            room = self.scale.NAME_W - 12 - 10 - 8 - p.fontMetrics().horizontalAdvance(words) * 0.9
            p.drawText(QRectF(12, top, room, self.ROW_H), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(room)))
            p.setFont(small)
            p.setPen(QColor(C.text2))
            p.drawText(QRectF(0, top, self.scale.NAME_W - 10, self.ROW_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, words)
            for b in d.buckets:
                self._paint_cell(p, i, kind, key, people, b, number, strong)
            p.setPen(QPen(QColor(C.stroke), 1))
            p.drawLine(QPointF(0, top + self.ROW_H - 0.5), QPointF(right, top + self.ROW_H - 0.5))
        self._paint_bands(p, 0, self.natural_height())
        # What's marked goes over the bands: the spotlight's cell, and the keys' cell while they're here.
        if d.spot is not None and d.spot.person:
            line = self.line_of(d.spot.person)
            b = next((x for x in d.buckets if x.first == d.spot.first), None)
            if line is not None and b is not None:
                p.setPen(QPen(QColor(C.accent), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(self.cell_rect(line, b).adjusted(1, 1, -1, -1))
        if self.hasFocus() and self.cur is not None and self.cur[1] < len(d.buckets):
            p.setPen(QPen(QColor(C.text), 2, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.cell_rect(self.cur[0], d.buckets[self.cur[1]]).adjusted(2, 2, -2, -2))
        p.end()

    def _paint_cell(self, p: QPainter, line: int, kind: str, key: str, people: list[Person], b: Bucket, number: QFont, strong: QFont) -> None:
        d = self.data
        if kind == "group":
            hours = max((sum(load.week_hours(d.cells, x.id, w) for x in people) for w in b.weeks), default=0.0)
            cap = load.capacity_of(people) or None
        else:
            hours, _ = load.worst_week(d.cells, key, b)
            cap = people[0].hours
        step = load.tint(hours, cap)
        if not step:
            return
        rect = self.cell_rect(line, b)
        fill = rect.adjusted(0, 0, -1 if rect.width() > 3 else 0, 0)
        p.fillRect(fill, QColor(TINTS[step]))
        if kind == "person" and any((key, w) in d.adds for w in b.weeks):  # the selected bar adds to this week
            p.fillRect(QRectF(fill.left(), fill.top(), fill.width(), 2), QColor(C.text2))
            p.fillRect(QRectF(fill.left(), fill.bottom() - 2, fill.width(), 2), QColor(C.text2))
        text = load.cell_text(hours, cap, d.unit)
        p.setFont(strong if step in ("t4", "t5") else number)
        if p.fontMetrics().horizontalAdvance(text) + PAD <= fill.width():
            p.setPen(QColor(INKS.get(step, C.text)))
            p.drawText(fill.adjusted(0, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)

    # ---- the mouse ----
    def _line_at(self, y: float) -> int:
        i = int(y // self.ROW_H)
        return i if 0 <= i < len(self.lines) and y >= 0 else -1

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x, y = event.position().x(), event.position().y()
        line = self._line_at(y)
        person_line = line >= 0 and self.lines[line][0] == "person"
        b = self._bucket_at(x) if person_line else None
        self.hovered.emit((b.first, b.end) if b else None)
        name = line if person_line and x < self.scale.NAME_W else -1
        if name != self.hover_name:
            self.hover_name = name
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor if (b or name >= 0) else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.hover_name != -1:
            self.hover_name = -1
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        line = self._line_at(y)
        if line < 0 or self.lines[line][0] != "person":
            return
        key = self.lines[line][1]
        if x < self.scale.NAME_W:
            self.solo.emit(key)
            return
        b = self._bucket_at(x)
        if b is not None:
            self.cur = (line, self.data.buckets.index(b))
            self.picked.emit(key, b.first, b.end)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        key, d = event.key(), self.data
        lines = [i for i, x in enumerate(self.lines) if x[0] == "person"]
        if key not in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) or not lines or not d.buckets:
            super().keyPressEvent(event)
            return
        if self.cur is None:  # the first key lands on this week, on the top row
            now = next((i for i, b in enumerate(d.buckets) if b.holds(d.today)), 0)
            self.cur = (lines[0], now)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            b = d.buckets[self.cur[1]]
            self.picked.emit(self.lines[self.cur[0]][1], b.first, b.end)
            return
        elif key == Qt.Key.Key_Left:
            self.cur = (self.cur[0], max(0, self.cur[1] - 1))
        elif key == Qt.Key.Key_Right:
            self.cur = (self.cur[0], min(len(d.buckets) - 1, self.cur[1] + 1))
        else:
            at = lines.index(self.cur[0]) + (-1 if key == Qt.Key.Key_Up else 1)
            self.cur = (lines[max(0, min(len(lines) - 1, at))], self.cur[1])
        b = d.buckets[self.cur[1]]
        person = self.lines[self.cur[0]][2][0]
        self.hovered.emit((b.first, b.end))
        tip = load.cell_tip(person, d.cells, b, d.today)
        self.setAccessibleDescription(tip)  # what a screen reader, and the tooltip, say about the cell the keys are on
        r = self.cell_rect(self.cur[0], b).toRect()
        QToolTip.showText(self.mapToGlobal(r.bottomLeft() + QPoint(0, 4)), tip, self, QRect(), 2500)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.update()
        super().focusOutEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.update()
        super().focusInEvent(event)

    def event(self, e) -> bool:  # noqa: D102 - a cell's other number, or what clicking a name does
        if e.type() == QEvent.Type.ToolTip:
            line = self._line_at(e.pos().y())
            if line < 0:
                QToolTip.hideText()
                return True
            kind, key, people = self.lines[line]
            b = self._bucket_at(e.pos().x())
            if e.pos().x() < self.scale.NAME_W and kind == "person":
                only = [p.id for p in self.data.people] == [key]
                QToolTip.showText(e.globalPos(), "Back to everyone" if only else f"Show only {people[0].name}: their bars and their load", self)
            elif b is not None and kind == "person":
                QToolTip.showText(e.globalPos(), load.cell_tip(people[0], self.data.cells, b, self.data.today), self)
            elif b is not None:
                cap = load.capacity_of(people)
                hours = max((sum(load.week_hours(self.data.cells, x.id, w) for x in people) for w in b.weeks), default=0.0)
                QToolTip.showText(e.globalPos(), f"{key}, {load.when(b, self.data.today)}: {round(hours, 1):g} h" + (f" of {cap:g} h" if cap else ""), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)
