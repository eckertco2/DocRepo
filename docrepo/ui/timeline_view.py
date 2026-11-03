"""The browse tool's Timeline view (mods log round 1, M0019; round 4, M0067, releases 5.29 and 5.30): one chart of open
tasks over the coming weeks, and, since release 5.40 (round 5's items 71 to 73, the visual review's stage V5), each person's
load under it on the same dates, the one page the owner asked for, to show where too much is being asked. The Classic look
keeps the chart alone, with Capacity as a page of its own.

The rows come from ``docrepo/timeline.py``; this module paints them and handles the mouse and keys. Each top-level task is
a row that folds (its arrow, Right and Left, or Collapse a level and Expand a level), with a summary bar over its
subtasks. The scale and the plant events lane (``TimelineHead``) stay at the top while the rows scroll. Clicking a row
shows its dates, hours and people, on a line under the chart so nothing moves (decision 292; a card above it in the Classic
look); double-clicking a bar or a name asks for Quick edit (``quick_edit``); Enter or Open task opens the task. Plan mode (P) lets a one-time task's bar be moved, or its
ends stretched, and an undated task's name be dragged onto the chart for a working week; each drop is sent as
``set_dates`` for the browse window to save and log, and Ctrl+Z sends the step back. It takes the middle and right panes
together.

Key dates (release 5.31, the key dates plan) are marks on their task's row: a window a thin segment under the bar (or in
the bar's place when the task has none in view), a start alone an opening bracket, an end alone a closing tick, a Deadline
end a red diamond, a plant activity amber, a done one grey. In Plan mode a key date that isn't done drags too (decision
152): a window moves or its ends stretch, a start or an end alone moves. Each drop is sent as ``set_key_date``, and Ctrl+Z
sends it back, in the same order as the bars' drops.

The range can be typed (release 5.39, item 70, decision 225): From and To beside Show always say what's in view, and a day
typed in either, or picked from its calendar, shows exactly those days until a Show choice replaces them.

Capacity's half (``capacity_strip``, ``docrepo/load.py``) has the chart's dates, a sentence on who is over and when, the team
chart and a heat strip per person. Clicking a week puts the spotlight on it (decision 233): a band through the chart, the bars
behind that load strong and the rest faded, and a card listing their hours. One People control narrows the bars and the load
together (decision 232). Bars are one colour unless Display says otherwise, with a lighter solid for Not started and a thin
line under the bar for its subtasks' span (decision 234).

What-ifs (release 5.64, decisions 226 to 228 and 290; ``docrepo/whatif.py``) are on the page only. One is a named list of things
done that changes no task: Take off, from the line under the chart or the spotlight's card, and the drags, which need no Plan
mode in one, including a whole parent's subtasks' line, in whole weeks. The browse window works out what it would do
(``picture_of``), and the chart and Capacity draw that: a moved bar outlined where it was, a task taken off as a dashed row with
Put back, the team chart's real columns outlined behind, and the sentence beside the real plan's. A strip says which what-if is
showing and that no task has changed, with Undo, Review and apply, and the way back. Quick edit and Update aren't offered in one,
as they'd change the real task.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from docrepo import key_dates, load, timeline, whatif
from docrepo.dates import days_text, long_date, monday_of, short, to_date
from docrepo.detail import esc
from docrepo.model import KeyDate, Model, Task
from docrepo.schedule import due_of, is_open, start_of, windows
from docrepo.timeline import Band, KeyMark, Row, Timeline
from docrepo.ui import tokens
from docrepo.ui.capacity_strip import CapacityRows, CapacityTeam, Spot, StripData
from docrepo.ui.icons import icon, set_fold
from docrepo.ui.look import LOOK, Help
from docrepo.ui.tokens import C
from docrepo.ui.tree_view import GROUP_COLOURS
from docrepo.ui.widgets import CheckMenuButton, DateField, DropButton, FlowLayout, label_filter, people_filter
from docrepo.views import markers

#: The most room the open list of tasks with no dates takes under the chart: four lines of Caption text, then it scrolls.
UNDATED_MAX_HEIGHT = 68
FG, MUTED, FAINT, LINE, LINE_STRONG = C.text, C.text2, C.disabled, C.stroke, C.stroke_strong
ACCENT, BAD, SEL, SURFACE_2, HOVER, CONTENT = C.accent, C.critical, C.selected, C.base, C.hover, C.content
#: Plant events (release 5.29): their bars, lane and band.
EV_BG, EV_LINE, EV_INK = C.event_bg, C.event, C.event_ink
#: Order by's keys, each a lane's dot, in this order; a ninth key and on are grey.
KEY_COLOURS = tuple(tokens.colour(f"lane{i}") for i in range(1, 9))
#: Hours a week, light to dark (``timeline.HOUR_BINS``), and the text on each.
HOUR_COLOURS = tuple(tokens.colour(f"hour{i}") for i in range(1, 6))
HOUR_INK = tuple(tokens.colour(f"hour_ink{i}") for i in range(1, 6))
#: The Priorities board's buckets.
PRIORITY_COLOURS = {"critical": C.critical, "high": C.pri_high, "medium": C.accent, "parking": C.disabled}
#: The pages' chip colours, inline: a QLabel doesn't have the pages' stylesheet.
CHIP_STYLE = {"st-ns": (C.text2, C.hover), "st-ip": (C.accent, C.info_bg), "urgent": (C.critical, C.critical_bg),
              "routine": (C.text, C.hover), "multi": (C.accent, C.info_bg), "pri-critical": (C.on_accent, C.critical),
              "event": (EV_INK, EV_BG)}
FLAG = "⚑"


def _chip(text: str, cls: str) -> str:
    fg, bg = CHIP_STYLE.get(cls, CHIP_STYLE["st-ns"])
    return f'<span style="color:{fg}; background-color:{bg}">&nbsp;{esc(text)}&nbsp;</span>'


def _alpha(colour: str, alpha: int) -> QColor:
    c = QColor(colour)
    c.setAlpha(alpha)
    return c


def _mix(colour: str, strength: float, into: str = CONTENT) -> QColor:
    """``colour`` mixed into ``into`` (white): at 1 the colour itself, at 0 ``into``."""
    c, w = QColor(colour), QColor(into)
    return QColor(round(w.red() + (c.red() - w.red()) * strength), round(w.green() + (c.green() - w.green()) * strength),
                  round(w.blue() + (c.blue() - w.blue()) * strength))


def key_colour(row: Row, order: str) -> str | None:
    """The colour a row's title and its edge take from Order by: the tree's for top-level task, else its key's."""
    if order == "top":
        return GROUP_COLOURS[row.colour % len(GROUP_COLOURS)]
    if row.key is None:
        return None
    return KEY_COLOURS[row.key] if row.key < len(KEY_COLOURS) else FAINT


def _entry(mark: str, words: str) -> str:
    """A legend's entry, kept whole when the legend wraps."""
    return f"{mark}&nbsp;{words.replace(' ', '&nbsp;')}"


def week_from(day: date) -> tuple[date, date]:
    """A dropped name's working week (decision 136): from the day, a Saturday or Sunday moved to the Monday, to the fifth
    workday counting it."""
    while day.weekday() >= 5:
        day += timedelta(days=1)
    end, n = day, 1
    while n < 5:
        end += timedelta(days=1)
        n += end.weekday() < 5
    return day, end


@dataclass
class Drag:
    """A drag in Plan mode: "new" (a name onto the chart), "move", "start" or "end", a key date's "kd-move", "kd-start"
    or "kd-end" (release 5.31), or in a what-if a whole parent's "parent" (release 5.64), and where it's got to."""

    task: str
    mode: str
    x0: float
    start0: date | None
    end0: date | None
    start: date | None = None
    end: date | None = None
    moved: bool = False
    key_id: int | None = None  # a key date's drag: its ID, and its kind ("window", "on", "from" or "by")
    kind: str = ""


#: The width of the names' column, and of the lane column before it while the rows are ordered by a field.
NAME_W, KEY_W = 250, 116


def field_names(order: str) -> tuple[str, str]:
    """Order by's field, for the lane column's header, and what a row without it is called."""
    if order.startswith(timeline.PARENT):
        name = order[len(timeline.PARENT):]
        return name, f"No {name.lower()}"
    return {"label": ("Label", "No label"), "person": ("Person", "No one"), "group": ("Group", "No group")}.get(order, ("", ""))


class _Scale:
    """Placing days across the chart, shared by the head and the rows."""

    NAME_W = NAME_W

    def __init__(self) -> None:
        self.tl: Timeline | None = None
        self.inset = 0  # room on the right for the rows' scroll bar, so the head lines up with them
        self.key_w = 0  # the lane column, while the rows are ordered by a field
        self.room: int | None = None  # the page's width, so a day is in one place whatever a part's own width, scroll bar or not

    def set_order(self, order: str) -> None:
        self.key_w = 0 if order == "top" else KEY_W
        self.NAME_W = NAME_W + self.key_w

    def width_of(self, widget: QWidget) -> float:
        return max(1.0, (self.room or widget.width()) - self.NAME_W - 10 - self.inset)

    def right(self, widget: QWidget) -> float:
        """Where the track ends."""
        return self.NAME_W + self.width_of(widget)

    def x(self, widget: QWidget, day: date) -> float:
        """Where a day starts across the track, clamped to it."""
        assert self.tl is not None
        frac = (day - self.tl.start).days / self.tl.days
        return self.NAME_W + self.width_of(widget) * min(1.0, max(0.0, frac))

    def day_at(self, widget: QWidget, x: float) -> date:
        assert self.tl is not None
        n = int((x - self.NAME_W) / self.width_of(widget) * self.tl.days)
        return self.tl.start + timedelta(days=min(max(n, 0), self.tl.days - 1))

    def px_per_day(self, widget: QWidget) -> float:
        assert self.tl is not None
        return self.width_of(widget) / self.tl.days


class TimelineHead(QWidget):
    """The scale (months and weeks, or months and years over 12 months), Today, and the plant events lane under it, which
    stay at the top while the rows scroll (decisions 133 and 134). Clicking an event picks its task."""

    picked = Signal(str)

    SCALE_H, LANE_H = 40, 20

    def __init__(self, scale: _Scale) -> None:
        super().__init__()
        self.scale = scale
        self.model: Model | None = None
        self.today = date.today()
        self.focus_title = ""
        self.field = ""  # Order by's field, over the lane column
        self.sel: str | None = None
        self.placed: list[tuple[QRectF, Band, float, float]] = []  # each event's bar, the room its name has, and where it starts
        self.lanes = 1
        self.setMouseTracking(True)

    def set_timeline(self, model: Model, today: date, focus_title: str, sel: str | None, field: str = "") -> None:
        self.model, self.today, self.focus_title, self.sel, self.field = model, today, focus_title, sel, field
        self._place()
        self.setFixedHeight(self.SCALE_H + (8 + self.lanes * self.LANE_H if self.lanes else 1))
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        if self.scale.tl is not None:
            self._place()

    def _label(self, b: Band) -> str:
        days = short(b.start, self.today) if b.start == b.end else f"{short(b.start, self.today)} to {short(b.end, self.today)}"
        return f"{FLAG} {b.title}  · {days}"

    def _place(self) -> None:
        """Each event on the first of two lanes where it fits with its name, which runs on past a short bar; when neither
        lane is free, its name stops where the next event in its lane starts."""
        tl = self.scale.tl
        if tl is None:
            return
        bold = QFont(self.font())
        bold.setBold(True)
        fm = QFontMetrics(bold)  # the names are painted bold
        lane_end: list[float] = []
        placed: list[tuple[QRectF, Band, int]] = []
        for b in tl.events:
            x0, x1 = self.scale.x(self, b.start), self.scale.x(self, b.end + timedelta(days=1))
            reach = max(x1, x0 + fm.horizontalAdvance(self._label(b)) + 16)
            lane = next((i for i, last in enumerate(lane_end) if last < x0), None)
            if lane is None:
                lane = len(lane_end) if len(lane_end) < 2 else min(range(2), key=lambda i: lane_end[i])
                if lane == len(lane_end):
                    lane_end.append(0.0)
            lane_end[lane] = reach
            placed.append((QRectF(x0, self.SCALE_H + 4 + lane * self.LANE_H, max(3.0, x1 - x0), self.LANE_H - 3), b, lane))
        self.lanes = max(1 if LOOK.classic else 0, len(lane_end))  # no events in view: no lane saying so
        right = self.scale.right(self)
        self.placed = []
        ends: dict[int, float] = {}  # where the last name in each lane ends
        for i, (rect, b, lane) in enumerate(placed):
            nxt = next((r for r, _, ln in placed[i + 1:] if ln == lane), None)
            text_x, width = rect.left() + 7, fm.horizontalAdvance(self._label(b)) + 4
            if nxt is None and text_x + width > right:  # near the right edge: the name ends there instead of being cut off
                text_x = max(ends.get(lane, 0.0) + 8, self.scale.NAME_W + 4, right - width - 4, 0.0)
            room = max(24.0, (nxt.left() if nxt else right) - text_x - 2)
            ends[lane] = text_x + min(width, room)
            self.placed.append((rect, b, room, text_x))

    def event_at(self, x: float, y: float) -> Band | None:
        return next((b for rect, b, _, _ in self.placed if rect.adjusted(0, 0, 4, 0).contains(QPointF(x, y))), None)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        tl = self.scale.tl
        if tl is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(CONTENT))
        right = self.scale.right(self)
        bold, small = QFont(self.font()), QFont(self.font())
        bold.setBold(True)
        small.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))
        long = tl.weeks > 26
        # The months, then the weeks (or the years, over 12 months), and Today.
        p.setFont(bold)
        p.setPen(QColor(FG))
        free = 0.0  # where the last name ended: over a long typed range, a name that wouldn't fit is left out
        for i, d in enumerate(tl.months()):
            # Over a year the year goes with its first month and each January, so the row under it has only the Today tag.
            name = (f"{d.strftime('%b')} {d.year}" if not i or d.month == 1 else d.strftime("%b")) if long else f"{d.strftime('%B')} {d.year}"
            x = self.scale.x(self, d) + 3
            if x >= free:
                p.drawText(QPointF(x, 15), name)
                free = x + p.fontMetrics().horizontalAdvance(name) + 8
        tag = QFont(small)
        tag.setWeight(QFont.Weight.DemiBold)
        pill = None
        if tl.start <= self.today < tl.end:  # beside the today line, or before it at the chart's right edge
            x = (self.scale.x(self, self.today) + self.scale.x(self, self.today + timedelta(days=1))) / 2
            w = QFontMetrics(tag).horizontalAdvance("Today") + 8
            pill = QRectF(x + 3 if x + 3 + w <= right else x - 3 - w, 21, w, 17)
        p.setFont(small)
        for i, w in enumerate(tl.week_starts()):
            x = self.scale.x(self, w)
            p.setPen(QColor(LINE_STRONG))
            p.drawLine(QPointF(x, 20), QPointF(x, self.SCALE_H))
            if not long and (i % 2 == 0 or right - self.scale.NAME_W > 760):
                text = short(w, self.today)
                # A date the Today tag would cover is left out: the tag says where you are.
                if pill is None or not QRectF(x + 3, 21, p.fontMetrics().horizontalAdvance(text), 17).intersects(pill):
                    p.setPen(QColor(MUTED))
                    p.drawText(QPointF(x + 3, 33), text)
        if pill is not None:  # the today line, named in the axis
            x = (self.scale.x(self, self.today) + self.scale.x(self, self.today + timedelta(days=1))) / 2
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawLine(QPointF(x, 18), QPointF(x, self.SCALE_H))
            p.setFont(tag)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(pill, 3, 3)
            p.setPen(QColor(CONTENT))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, "Today")
            p.setFont(small)
        p.setPen(QPen(QColor(LINE_STRONG), 1))
        p.drawLine(QPointF(0, self.SCALE_H - 0.5), QPointF(right, self.SCALE_H - 0.5))
        p.drawLine(QPointF(0, self.height() - 0.5), QPointF(right, self.height() - 0.5))
        # The corner: Focus on its first line, and the field the rows are ordered by over its lane column.
        p.setFont(small)
        if self.focus_title:
            p.setPen(QColor(MUTED))
            text = p.fontMetrics().elidedText(f"Focus: {self.focus_title}", Qt.TextElideMode.ElideRight, self.scale.NAME_W - 14)
            p.drawText(QRectF(8, 2, self.scale.NAME_W - 10, 18), Qt.AlignmentFlag.AlignVCenter, text)
        if self.scale.key_w and self.field:
            heading = QFont(small)
            heading.setWeight(QFont.Weight.DemiBold)
            p.setFont(heading)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(8, 20, self.scale.key_w - 12, self.SCALE_H - 22), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(self.field, Qt.TextElideMode.ElideRight, self.scale.key_w - 14))
            p.drawText(QRectF(self.scale.key_w + 6, 20, NAME_W - 12, self.SCALE_H - 22), Qt.AlignmentFlag.AlignVCenter, "Task")
            p.setFont(small)
        elif not LOOK.classic:  # beside Collapse a level and Expand a level (the review's stage V5)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(8, 20, 40, self.SCALE_H - 22), Qt.AlignmentFlag.AlignVCenter, "Task")
        if not self.lanes:
            p.end()
            return
        lane_top = self.SCALE_H + 2
        p.fillRect(QRectF(0, lane_top, right, self.height() - lane_top - 1), QColor(SURFACE_2))
        p.setFont(bold)
        p.setPen(QColor(EV_LINE))
        lane_name = QRectF(8, lane_top, self.scale.NAME_W - 10, self.LANE_H + 2)
        p.drawText(lane_name, Qt.AlignmentFlag.AlignVCenter, FLAG if not LOOK.classic else f"{FLAG} Plant events")
        if not LOOK.classic:  # the flag has the colour, and the words are text, at text's contrast
            p.setPen(QColor(FG))
            p.drawText(lane_name.adjusted(p.fontMetrics().horizontalAdvance(FLAG) + 4, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "Plant events")
        if not self.placed:
            p.setFont(small)
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(self.scale.NAME_W + 6, lane_top, 200, self.LANE_H + 2), Qt.AlignmentFlag.AlignVCenter, "None in view")
        for rect, b, room, text_x in self.placed:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_mix(EV_LINE, 0.35, EV_BG) if b.task == self.sel else QColor(EV_BG))
            p.drawRoundedRect(rect, 3, 3)
            p.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), QColor(EV_LINE))
            p.setFont(bold)
            p.setPen(QColor(EV_INK))
            text = p.fontMetrics().elidedText(self._label(b), Qt.TextElideMode.ElideRight, int(room))
            p.drawText(QRectF(text_x, rect.top(), room, rect.height()), Qt.AlignmentFlag.AlignVCenter, text)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        b = self.event_at(event.position().x(), event.position().y())
        if b is not None:
            self.picked.emit(b.task)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        on = self.event_at(event.position().x(), event.position().y()) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)

    def event(self, e) -> bool:  # noqa: D102 - an event's name, dates and how many open tasks fall in it
        if e.type() == QEvent.Type.ToolTip and self.model is not None:
            b = self.event_at(e.pos().x(), e.pos().y())
            if b is None:
                QToolTip.hideText()
            else:
                n = timeline.tasks_during(self.model, b, self.today)
                QToolTip.showText(e.globalPos(), f"{b.title}\nPlant event, {timeline.days_text(b, self.today)}"
                                                 f"\n{n} open task{'s' if n != 1 else ''} fall in it", self)
            return True
        return super().event(e)


class TimelineChart(QWidget):
    """The rows: a name column, then a track per row with its bars placed by date. ``picked`` sends the task a click
    selects; ``opened`` the one to open (Enter); ``fold`` a row whose subtasks open or close; ``quick_edit`` the task and
    where its bar is, for a double-click (decision 138); ``dropped`` a Plan mode drag's task, Start and Due, and how."""

    picked = Signal(str)
    opened = Signal(str)
    fold = Signal(str, bool)
    quick_edit = Signal(str, QRect)
    dropped = Signal(str, object, object, str)
    #: A key date's drop in Plan mode (release 5.31): its task, its ID, its new first and last day, and its kind.
    dropped_key = Signal(str, int, object, object, str)
    #: In a what-if (release 5.64), a whole parent dropped: its task, and how many weeks later (earlier when below 0).
    dropped_parent = Signal(str, int)

    ROW_H, BAR_TOP, BAR_H, EDGE = 28, 6, 16, 6

    def __init__(self, scale: _Scale) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scale = scale
        self.model: Model | None = None
        self.today = date.today()
        self.sel: str | None = None
        self.plan = False
        self.bars = "project"
        self.a_week = False
        self.order = "top"
        self.rows: list[Row] = []
        self.hit_key: KeyMark | None = None  # the key date ``_hit`` found last, if any
        self.runs: list[tuple[int, int, int | None, str]] = []  # the lane column's bands: first and last row, key, name
        self.drag: Drag | None = None
        self.hover = -1  # the row under the mouse, lightly shaded
        self.strong: set[str] | None = None  # the spotlight (decision 233): the rows that stay strong, the rest faded
        self.spot: tuple[date, date] | None = None  # its week
        self.hover_week: tuple[date, date] | None = None  # the week under the mouse in Capacity
        self._fade = 1.0  # how strongly the row being painted is drawn
        # A what-if showing (release 5.64): the tasks it takes off, where its moved bars were, and those it pushes past a deadline.
        self.whatif = False
        self.off: set[str] = set()
        self.was: dict[str, tuple[date, date]] = {}
        self.past: set[str] = set()

    @property
    def tl(self) -> Timeline | None:
        return self.scale.tl

    def set_timeline(self, model: Model, today: date, sel: str | None, plan: bool, bars: str, a_week: bool, order: str) -> None:
        assert self.tl is not None
        self.model, self.today, self.sel, self.plan, self.bars, self.a_week, self.order = model, today, sel, plan, bars, a_week, order
        self.rows = list(self.tl.rows)
        self.runs = self._runs()
        self.setMinimumHeight(len(self.rows) * self.ROW_H + 8)
        self.update()

    def _runs(self) -> list[tuple[int, int, int | None, str]]:
        """Each run of rows next to each other with the same key, for a band in the lane column naming it (the owner's
        hand test of 5.29: the field the rows are ordered by is shown, as a label stretching down the rows it holds)."""
        if not self.scale.key_w or self.tl is None:
            return []
        none = field_names(self.order)[1]
        runs: list[tuple[int, int, int | None, str]] = []
        for i, r in enumerate(self.rows):
            if runs and runs[-1][2] == r.key and runs[-1][1] == i - 1:
                runs[-1] = (runs[-1][0], i, r.key, runs[-1][3])
            else:
                runs.append((i, i, r.key, self.tl.keys[r.key] if r.key is not None and r.key < len(self.tl.keys) else none))
        return runs

    def run_at(self, y: float) -> tuple[int, int, int | None, str] | None:
        i = int(y // self.ROW_H)
        return next((run for run in self.runs if run[0] <= i <= run[1]), None) if y >= 0 else None

    # ---- placing ----
    def _x(self, day: date) -> float:
        return self.scale.x(self, day)

    def _mid(self, day: date) -> float:
        return (self._x(day) + self._x(day + timedelta(days=1))) / 2

    def row_at(self, y: float) -> Row | None:
        i = int(y // self.ROW_H)
        return self.rows[i] if 0 <= i < len(self.rows) and y >= 0 else None

    def top_of(self, task_id: str) -> int | None:
        return next((i * self.ROW_H for i, r in enumerate(self.rows) if r.task == task_id), None)

    def _indent(self, r: Row) -> float:
        return self.scale.key_w + 6 + 16 * r.depth

    def _fold_rect(self, r: Row, top: float) -> QRectF:
        return QRectF(self._indent(r), top + 5, 18, 18)

    def _grip_rect(self, r: Row, top: float) -> QRectF:
        return QRectF(self._indent(r) + 20, top + 6, 14, 16)

    def bar_rect(self, r: Row, top: float) -> QRectF | None:
        """A one-time task's bar, which Plan mode drags (a routine task's dates are a rule, so it doesn't)."""
        if not r.own or r.routine or not r.windows:
            return None
        a, b = r.windows[0]
        x0, x1 = self._x(a), self._x(b + timedelta(days=1))
        return QRectF(x0, top + self.BAR_TOP, max(3.0, x1 - x0), self.BAR_H)

    def span_rect(self, r: Row, top: float) -> QRectF | None:
        """In a what-if, where a parent's subtasks' line is grabbed to move it all: the whole row when it has no bar of its own,
        else under its bar."""
        if not self.whatif or not r.kids or r.span is None or self.tl is None:
            return None
        a, b = r.span
        x0, x1 = self._x(max(a, self.tl.start)), self._x(min(b, self.tl.end - timedelta(days=1)) + timedelta(days=1))
        y = top + 2 if self.bar_rect(r, top) is None else top + self.BAR_TOP + self.BAR_H
        return QRectF(x0, y, max(6.0, x1 - x0), top + self.ROW_H - y)

    # ---- painting ----
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        if self.tl is None or self.model is None:
            return
        tl = self.tl
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(CONTENT))
        right = self.scale.right(self)
        base, bold, small = QFont(self.font()), QFont(self.font()), QFont(self.font())
        bold.setBold(True)
        small.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))
        bottom = len(self.rows) * self.ROW_H
        # Each row's ground, the week lines and the plant events' bands, under everything else.
        left = self.scale.key_w
        if tl.weeks <= 13:  # weekends a light neutral at day scale, dropped over longer ranges, where a day is a sliver
            for n in range(tl.days):
                d = tl.start + timedelta(days=n)
                if d.weekday() >= 5:
                    p.fillRect(QRectF(self._x(d), 0, self._x(d + timedelta(days=1)) - self._x(d), bottom), _alpha(FG, 10))
        for i, r in enumerate(self.rows):
            top = i * self.ROW_H
            if r.task == self.sel:
                p.fillRect(QRectF(left, top, right - left, self.ROW_H), QColor(SEL))
            elif i == self.hover:
                p.fillRect(QRectF(left, top, right - left, self.ROW_H), QColor(HOVER))
            p.setPen(QPen(QColor(LINE if r.depth else LINE_STRONG), 1))
            if not r.depth and i:
                p.drawLine(QPointF(left, top + 0.5), QPointF(right, top + 0.5))
        self._paint_runs(p, small)
        p.setPen(QPen(QColor(LINE), 1))
        for w in tl.week_starts():
            x = self._x(w)
            p.drawLine(QPointF(x, 0), QPointF(x, bottom))
        for band in tl.events:
            x0, x1 = self._x(band.start), self._x(band.end + timedelta(days=1))
            p.fillRect(QRectF(x0, 0, max(2.0, x1 - x0), bottom), _alpha(EV_LINE, 26))
            p.setPen(QPen(_alpha(EV_LINE, 150), 1))
            p.drawLine(QPointF(x0, 0), QPointF(x0, bottom))
            p.drawLine(QPointF(x1, 0), QPointF(x1, bottom))
        for i, r in enumerate(self.rows):
            self._paint_row(p, i * self.ROW_H, r, base, bold, small)
        if self.hover_week is not None:
            x0, x1 = self._x(self.hover_week[0]), self._x(self.hover_week[1])
            p.fillRect(QRectF(x0, 0, x1 - x0, bottom), _alpha(FG, 14))
        if self.spot is not None:  # the week the spotlight is on, down the chart
            x0, x1 = self._x(self.spot[0]), self._x(self.spot[1])
            p.fillRect(QRectF(x0, 0, x1 - x0, bottom), _alpha(ACCENT, 26))
            p.setPen(QPen(QColor(ACCENT), 1))
            p.drawLine(QPointF(x0, 0), QPointF(x0, bottom))
            p.drawLine(QPointF(x1, 0), QPointF(x1, bottom))
        if tl.start <= self.today < tl.end:
            x = self._mid(self.today)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, bottom))
        if self.drag and self.drag.moved and self.drag.start and self.drag.end and self.drag.key_id is not None:
            top = self.top_of(self.drag.task)  # where the dragged key date goes
            row = next((r for r in self.rows if r.task == self.drag.task), None)
            if top is not None and row is not None:
                cy, h = self._key_strip(row, top)
                x0, x1 = self._x(self.drag.start), self._x(self.drag.end + timedelta(days=1))
                p.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
                p.setBrush(_mix(ACCENT, 0.45))
                p.drawRoundedRect(QRectF(x0, cy - h / 2 - 1, max(4.0, x1 - x0), h + 2), 2, 2)
        elif self.drag and self.drag.moved and self.drag.mode == "parent" and self.drag.start and self.drag.end:  # where it all goes
            top = self.top_of(self.drag.task)
            if top is not None:
                x0, x1 = self._x(self.drag.start), self._x(self.drag.end + timedelta(days=1))
                p.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
                p.setBrush(_alpha(ACCENT, 40))
                p.drawRoundedRect(QRectF(x0, top + 3, max(6.0, x1 - x0), self.ROW_H - 6), 4, 4)
        elif self.drag and self.drag.moved and self.drag.start and self.drag.end:  # where the dragged bar goes
            top = self.top_of(self.drag.task)
            if top is not None:
                x0, x1 = self._x(self.drag.start), self._x(self.drag.end + timedelta(days=1))
                rect = QRectF(x0, top + self.BAR_TOP, max(3.0, x1 - x0), self.BAR_H)
                p.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
                p.setBrush(_mix(ACCENT, 0.45))
                p.drawRoundedRect(rect, 4, 4)
        p.end()

    def _paint_runs(self, p: QPainter, small: QFont) -> None:
        """The lane column: a band down each run of rows with the same key, a tint of its colour with a solid edge, and
        the key's name at its top, in words (the playbook's grouping ladder: one tint for the region, text with colour)."""
        if not self.runs:
            return
        heading = QFont(small)
        heading.setWeight(QFont.Weight.DemiBold)
        p.setFont(heading)
        w = self.scale.key_w
        for first, last, key, name in self.runs:
            colour = (KEY_COLOURS[key] if key < len(KEY_COLOURS) else FAINT) if key is not None else LINE_STRONG
            rect = QRectF(4, first * self.ROW_H + 2, w - 10, (last - first + 1) * self.ROW_H - 4)
            p.setPen(Qt.PenStyle.NoPen)
            if LOOK.classic:
                p.setBrush(_mix(colour, 0.13) if key is not None else QColor(SURFACE_2))
                p.drawRoundedRect(rect, 4, 4)
                p.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), QColor(colour))
                p.setPen(_mix(colour, 0.75, FG) if key is not None else QColor(MUTED))
                text_x = rect.left() + 9
            else:  # one neutral band, a small dot in the key's colour and dark words, so no one looks overdue or healthy (the review's decision V4)
                p.setBrush(QColor(SURFACE_2))
                p.drawRoundedRect(rect, 4, 4)
                p.setBrush(QColor(colour))
                p.drawEllipse(QPointF(rect.left() + 10, rect.top() + (self.ROW_H - 4) / 2), 4, 4)
                p.setPen(QColor(FG) if key is not None else QColor(MUTED))
                text_x = rect.left() + 19
            text = p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(rect.right() - text_x - 3))
            p.drawText(QRectF(text_x, rect.top(), rect.right() - text_x - 3, self.ROW_H - 4), Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_row(self, p: QPainter, top: int, r: Row, base: QFont, bold: QFont, small: QFont) -> None:
        assert self.model is not None and self.tl is not None
        t = self.model.task(r.task)
        right = self.scale.right(self)
        faded = self.strong is not None and r.task not in self.strong and not r.plant_event
        lit = self.strong is not None and r.task in self.strong
        off = r.task in self.off  # taken off in the what-if showing: still a row, to put back
        self._fade = 0.22 if faded else 0.55 if off else 1.0
        p.setPen(QPen(QColor(LINE), 1))
        p.drawLine(QPointF(0, top + self.ROW_H - 0.5), QPointF(right, top + self.ROW_H - 0.5))
        # Ordered by top-level task, its project's colour is an edge, as in the task tree; by a field, the lane column's band
        # names the key, so the title stays plain (one colour cue, with its words beside it).
        kc = key_colour(r, self.order) if not self.scale.key_w else None
        if kc:
            p.fillRect(QRectF(0, top, 3, self.ROW_H), QColor(kc))
        x = self._indent(r)
        if r.kids:  # the fold arrow: right while folded, down while open
            cx, cy, s = x + 9, top + self.ROW_H / 2, 3.5  # a chevron, as the task tree's
            path = QPainterPath()
            if r.open:
                path.moveTo(cx - s, cy - s / 2)
                path.lineTo(cx, cy + s / 2)
                path.lineTo(cx + s, cy - s / 2)
            else:
                path.moveTo(cx - s / 2, cy - s)
                path.lineTo(cx + s / 2, cy)
                path.lineTo(cx - s / 2, cy + s)
            p.setPen(QPen(QColor(MUTED), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        x += 20
        if self.plan and r.undated:  # the grip, to drag the name onto the chart
            g = self._grip_rect(r, top)
            p.setPen(QPen(QColor(LINE_STRONG), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(g, 3, 3)
            p.setFont(small)
            p.setPen(QColor(MUTED))
            p.drawText(g, Qt.AlignmentFlag.AlignCenter, "⋮⋮")
            x += 18
        if r.plant_event:
            p.setFont(bold)
            p.setPen(QColor(EV_LINE))
            p.drawText(QRectF(x, top, 14, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, FLAG)
            x += 15
        badge = f"{r.kids}" if r.kids and not r.open else ""
        late_w = 30 if r.late or off else 0
        badge_w = (p.fontMetrics().horizontalAdvance(badge) + 12) if badge else 0
        p.setFont(bold if not r.depth or lit else base)
        # Plain words beside the colour edge, as in the task tree (the review's decision V3).
        colour = QColor(FAINT) if faded else QColor(MUTED) if r.ctx or off else (_mix(kc, 0.6, FG) if kc and LOOK.classic else QColor(FG))
        p.setPen(colour)
        name_w = max(20.0, self.scale.NAME_W - x - 6 - late_w - badge_w)
        text = p.fontMetrics().elidedText(t.title, Qt.TextElideMode.ElideRight, int(name_w))
        p.drawText(QRectF(x, top, name_w, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, text)
        x += p.fontMetrics().horizontalAdvance(text) + 5
        if badge:
            p.setFont(small)
            rect = QRectF(x, top + 7, badge_w - 4, 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(HOVER))
            p.drawRoundedRect(rect, 7, 7)
            p.setPen(QColor(MUTED))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, badge)
        if off:  # a tag, as the mock's: taken off in this what-if
            p.setFont(small)
            tag = QRectF(self.scale.NAME_W - 30, top + 7, 26, 14)
            p.setPen(QPen(QColor(LINE_STRONG), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(tag, 3, 3)
            p.setPen(QColor(MUTED))
            p.drawText(tag, Qt.AlignmentFlag.AlignCenter, "off")
        elif r.late:
            p.setFont(small)
            p.setPen(QColor(BAD))
            p.drawText(QRectF(self.scale.NAME_W - 32, top, 30, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, "late")
        p.setOpacity(self._fade)
        self._paint_track(p, top, r, t, bold, small)
        p.setOpacity(1.0)

    def _bar_look(self, t: Task, r: Row) -> tuple[QColor | None, QColor | None, QColor, bool, bool, bool]:
        """(fill, edge, text colour, hatched, dashed outline, event stripe) for a one-time task's bar (decision 133)."""
        if t.id in self.off:  # taken off in a what-if: an outline where it was
            return None, QColor(MUTED), QColor(MUTED), False, True, False
        if t.plant_event:
            return QColor(EV_BG), _mix(EV_LINE, 0.55, EV_BG), QColor(EV_INK), False, False, True
        if self.bars == "hours":
            b = timeline.hour_bin(t, self.today)
            if b < 0:
                return None, QColor(FAINT), QColor(MUTED), False, True, False
            if r.not_started and not LOOK.classic:  # a lighter solid, whatever colours the bars (decision 234)
                fill = _mix(HOUR_COLOURS[b], 0.72)
                return fill, None, QColor(FG if fill.lightnessF() > 0.55 else CONTENT), False, False, False
            return QColor(HOUR_COLOURS[b]), None, QColor(HOUR_INK[b]), r.not_started, False, False
        if self.bars == "priority":
            if not t.priority or t.priority not in PRIORITY_COLOURS:
                return None, QColor(FAINT), QColor(MUTED), False, True, False
            colour = PRIORITY_COLOURS[t.priority]
        elif self.bars == "one":
            colour = C.bar
        else:
            colour = GROUP_COLOURS[r.colour % len(GROUP_COLOURS)]
        if r.not_started:
            if not LOOK.classic:
                return _mix(colour, 0.3), None, QColor(FG), False, False, False
            return _mix(colour, 0.3), QColor(colour), QColor(FG), True, False, False
        return _mix(colour, 0.72), None, QColor(FG), False, False, False

    def _dot_colour(self, t: Task, r: Row) -> str:
        """A routine task's dots: its project's or priority's colour (a routine task has no hours a week)."""
        if t.plant_event:
            return EV_LINE
        if self.bars == "priority":
            return PRIORITY_COLOURS.get(t.priority or "", FAINT)
        if self.bars == "hours":
            return FAINT
        if self.bars == "one":
            return C.bar
        return GROUP_COLOURS[r.colour % len(GROUP_COLOURS)]

    def _paint_track(self, p: QPainter, top: int, r: Row, t: Task, bold: QFont, small: QFont) -> None:
        fill, edge, ink, hatched, dashed, stripe = self._bar_look(t, r)
        dot = self._dot_colour(t, r)
        label = timeline.hours_label(t, self.today, self.a_week)
        bar_font = QFont(small)
        bar_font.setWeight(QFont.Weight.DemiBold)
        was = self.was.get(r.task)
        if was is not None and r.own and not r.routine:  # a what-if moved it: where it is on the real plan
            x0, x1 = self._x(max(was[0], self.tl.start)), self._x(min(was[1], self.tl.end - timedelta(days=1)) + timedelta(days=1))
            if was[1] >= self.tl.start and was[0] < self.tl.end:
                p.setPen(QPen(QColor(MUTED), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(x0, top + self.BAR_TOP, max(3.0, x1 - x0), self.BAR_H), 4, 4)
        for a, b in r.windows:
            x0, x1 = self._x(a), self._x(b + timedelta(days=1))
            if r.routine and a == b:  # a one-day occurrence: a dot
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(dot))
                p.drawEllipse(QPointF(self._mid(a), top + self.ROW_H / 2), 4, 4)
                continue
            if r.routine:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_mix(dot, 0.55))
                p.drawRoundedRect(QRectF(x0, top + 10, max(2.0, x1 - x0), 8), 3, 3)
                continue
            rect = QRectF(x0, top + self.BAR_TOP, max(3.0, x1 - x0), self.BAR_H)
            if self.drag and self.drag.moved and self.drag.task == r.task:
                p.setOpacity(0.35 * self._fade)
            p.setPen(QPen(edge, 1, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine) if edge is not None else Qt.PenStyle.NoPen)
            p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 4, 4)
            if hatched:  # Not started, whatever the colour
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(_alpha(CONTENT, 130) if edge is None else _mix(edge.name(), 0.55), Qt.BrushStyle.BDiagPattern))
                p.drawRoundedRect(rect, 4, 4)
            if stripe:
                p.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), QColor(EV_LINE))
            if r.late:
                p.fillRect(QRectF(rect.right() - 4, rect.top(), 4, rect.height()), QColor(BAD))
            text = f"{FLAG} {label or t.title}" if t.plant_event and rect.width() > 70 else label if rect.width() >= 34 else ""
            if text:
                p.setFont(bar_font)
                p.setPen(ink)
                p.drawText(rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - 10)))
            elif label and rect.right() + 50 < self.scale.right(self):
                # Too narrow for its hours: they go just after the bar, never cut off (the playbook's timeline labels).
                p.setFont(small)
                p.setPen(QColor(MUTED))
                at = rect.right() + 4
                if self.tl.start <= self.today < self.tl.end and at - 3 <= self._mid(self.today) <= at + p.fontMetrics().horizontalAdvance(label) + 2:
                    at = self._mid(self.today) + 4  # past the today line, so it doesn't run through the number
                p.drawText(QRectF(at, rect.top() - 2, 80, rect.height() + 4), Qt.AlignmentFlag.AlignVCenter, label)
            if self.plan and not r.routine and rect.width() > 14:  # the ends that stretch
                p.fillRect(QRectF(rect.left(), rect.top() + 4, 2, rect.height() - 8), _alpha(FG, 60))
                p.fillRect(QRectF(rect.right() - 2, rect.top() + 4, 2, rect.height() - 8), _alpha(FG, 60))
            p.setOpacity(self._fade)
        if r.deadline:
            past = r.task in self.past
            self._diamond(p, self._mid(r.deadline), top + 14.0, 6.0, QColor(BAD if r.deadline < self.today or past else FG), QColor(CONTENT))
            if past:  # a what-if moved it past its deadline, which stays put
                p.setFont(bar_font)
                words = "past its deadline"
                w = p.fontMetrics().horizontalAdvance(words) + 6
                at = self._mid(r.deadline) + 9
                if at + w > self.scale.right(self):
                    at = self._mid(r.deadline) - 9 - w
                p.fillRect(QRectF(at, top + 1, w, 13), QColor(CONTENT))
                p.setPen(QColor(BAD))
                p.drawText(QRectF(at, top + 1, w, 13), Qt.AlignmentFlag.AlignCenter, words)
        if r.span:  # the summary bar: its subtasks' span, with their deadlines (item 51)
            only = not r.own or not r.windows
            a, b = r.span
            x0, x1 = self._x(max(a, self.tl.start)), self._x(min(b, self.tl.end - timedelta(days=1)) + timedelta(days=1))
            # Under a bar of its own, a thin line, so a row isn't three marks on top of each other (decision 234).
            y, h, tick = (top + 12.0, 4.0, 12.0) if only else (top + 23.0, 3.0, 7.0) if LOOK.classic else (top + 24.0, 2.0, 4.0)
            p.fillRect(QRectF(x0, y, max(2.0, x1 - x0), h), QColor(MUTED))
            if a >= self.tl.start:
                p.fillRect(QRectF(x0, y + h - tick, 2, tick), QColor(MUTED))
            if b < self.tl.end:
                p.fillRect(QRectF(x1 - 2, y + h - tick, 2, tick), QColor(MUTED))
            for d in r.sub_deadlines:
                self._diamond(p, self._mid(d), y + h / 2, 4.0, QColor(CONTENT), QColor(BAD if d < self.today else FG))
        for k in r.key_dates:  # release 5.31
            self._paint_key(p, top, r, t, k)
        if self.plan and r.undated:
            box = QRectF(self.scale.NAME_W + 6, top + 4, self.scale.width_of(self) - 12, self.ROW_H - 8)
            p.setPen(QPen(QColor(LINE_STRONG), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 4, 4)
            p.setFont(small)
            p.setPen(QColor(FAINT))
            p.drawText(box.adjusted(8, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "Drag the name onto the chart to give it a week")

    def _key_strip(self, r: Row, top: float) -> tuple[float, float]:
        """Where a row's key dates go: the middle of a thin strip under the bar, or in the bar's place when the row has no
        dates of its own in view; and a window's thickness there."""
        return (top + 24.0, 4.0) if r.windows else (top + 14.0, 6.0)

    def _key_colour(self, t: Task, r: Row, k: KeyMark) -> str:
        """A key date's colour: grey when done (decision 153), amber for a plant activity (149), else its bar's."""
        if k.done:
            return LINE_STRONG
        if k.plant:
            return EV_LINE
        if self.bars == "priority":
            return PRIORITY_COLOURS.get(t.priority or "", MUTED)
        if self.bars == "one":
            return C.bar
        return GROUP_COLOURS[r.colour % len(GROUP_COLOURS)]

    def _paint_key(self, p: QPainter, top: float, r: Row, t: Task, k: KeyMark) -> None:
        """One key date's mark: a window a thin segment, a start alone an opening bracket, an end alone a closing tick, and a
        Deadline end a red diamond; faint while it's being dragged."""
        assert self.tl is not None
        cy, h = self._key_strip(r, top)
        colour = QColor(self._key_colour(t, r, k))
        dragging = self.drag is not None and self.drag.moved and self.drag.key_id == k.id
        if dragging:
            p.setOpacity(0.35 * self._fade)
        if k.kind in ("window", "on"):
            x0, x1 = self._x(k.first), self._x(k.last + timedelta(days=1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(colour)
            p.drawRoundedRect(QRectF(x0, cy - h / 2, max(4.0, x1 - x0), h), 2, 2)
        elif k.kind == "from" and k.first >= self.tl.start:  # [ an opening bracket at its first day's start
            x = self._x(k.first)
            p.setPen(QPen(colour, 2))
            p.drawLine(QPointF(x + 1, cy - 5), QPointF(x + 1, cy + 5))
            p.drawLine(QPointF(x + 1, cy - 5), QPointF(x + 5, cy - 5))
            p.drawLine(QPointF(x + 1, cy + 5), QPointF(x + 5, cy + 5))
        elif k.kind == "by" and k.last < self.tl.end and not k.deadline:  # ] a closing tick at its last day's end
            x = self._x(k.last + timedelta(days=1))
            p.setPen(QPen(colour, 2))
            p.drawLine(QPointF(x - 1, cy - 5), QPointF(x - 1, cy + 5))
            p.drawLine(QPointF(x - 1, cy - 5), QPointF(x - 5, cy - 5))
            p.drawLine(QPointF(x - 1, cy + 5), QPointF(x - 5, cy + 5))
        if k.deadline and k.kind != "from" and self.tl.start <= k.last < self.tl.end:  # a hard date: a red diamond (decision 147)
            self._diamond(p, self._mid(k.last), cy, 5.0, QColor(LINE_STRONG if k.done else BAD), QColor(CONTENT))
        p.setOpacity(self._fade)

    def _key_at(self, r: Row, top: float, x: float, y: float) -> tuple[KeyMark, str] | None:
        """In Plan mode, the key date under the mouse that isn't done, and where on it: "kd-start" or "kd-end" (a window's
        ends, which stretch) or "kd-move" (decision 152)."""
        cy, _ = self._key_strip(r, top)
        if abs(y - cy) > 7:
            return None
        for k in reversed(r.key_dates):  # the last drawn is on top
            if k.done:
                continue
            x0, x1 = self._x(k.first), self._x(k.last + timedelta(days=1))
            if k.kind == "from":
                x0 = x1 = self._x(k.first) + 3
            elif k.kind == "by":
                x0 = x1 = self._x(k.last + timedelta(days=1)) - 3
            if not x0 - 6 <= x <= x1 + 6:
                continue
            if k.kind == "window" or (k.kind == "on" and x1 - x0 > 3 * self.EDGE):
                if x <= x0 + self.EDGE:
                    return k, "kd-start"
                if x >= x1 - self.EDGE:
                    return k, "kd-end"
            return k, "kd-move"
        return None

    @staticmethod
    def _diamond(p: QPainter, cx: float, cy: float, s: float, fill: QColor, edge: QColor) -> None:
        p.setPen(QPen(edge, 1.5))
        p.setBrush(fill)
        p.drawPolygon(QPolygonF([QPointF(cx, cy - s), QPointF(cx + s, cy), QPointF(cx, cy + s), QPointF(cx - s, cy)]))

    # ---- the mouse ----
    def _hit(self, x: float, y: float) -> tuple[Row | None, str]:
        """What's under the mouse: "fold", "grip", "start", "end", "move" (a bar, in Plan mode), a key date's "kd-start",
        "kd-end" or "kd-move" (Plan mode, release 5.31; the key date is ``hit_key``), a whole parent's "parent" (a what-if,
        release 5.64), "row" or ""."""
        self.hit_key = None
        r = self.row_at(y)
        if r is None:
            return None, ""
        top = int(y // self.ROW_H) * self.ROW_H
        if r.kids and self._fold_rect(r, top).contains(QPointF(x, y)):
            return r, "fold"
        if r.task in self.off:  # taken off: put back before it moves
            return r, "row"
        if self.plan and r.undated and self._grip_rect(r, top).adjusted(-2, -4, 2, 4).contains(QPointF(x, y)):
            return r, "grip"
        key = self._key_at(r, top, x, y) if self.plan and x >= self.scale.NAME_W else None
        if key is not None:
            self.hit_key = key[0]
            return r, key[1]
        bar = self.bar_rect(r, top) if self.plan else None
        if bar is not None and bar.adjusted(-2, -4, 2, 4).contains(QPointF(x, y)):
            if x <= bar.left() + self.EDGE:
                return r, "start"
            if x >= bar.right() - self.EDGE:
                return r, "end"
            return r, "move"
        span = self.span_rect(r, top)
        if span is not None and span.contains(QPointF(x, y)):
            return r, "parent"
        return r, "row"

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        r, what = self._hit(x, y)
        if r is None:
            return
        if what == "fold":
            self.fold.emit(r.task, not r.open)
            return
        if what.startswith("kd-") and self.hit_key is not None:
            k = self.hit_key
            self.drag = Drag(r.task, what, x, k.first, k.last, key_id=k.id, kind=k.kind)
        elif what == "parent" and r.span is not None:
            self.drag = Drag(r.task, "parent", x, r.span[0], r.span[1])
        elif what in ("grip", "start", "end", "move") and self.model is not None:
            t = self.model.task(r.task)
            end = to_date(t.due or t.deadline) if (t.due or t.deadline) else None
            self.drag = Drag(r.task, "new" if what == "grip" else what, x, None if what == "grip" else start_of(t), end)
        self.picked.emit(r.task)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x, y = event.position().x(), event.position().y()
        d = self.drag
        if d is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if not d.moved and abs(x - d.x0) < (6 if d.mode == "new" else 4):
                return
            d.moved = True
            self._drag_to(d, x)
            if d.mode == "parent" and d.start and d.start0 and self.model is not None:
                n = (d.start - d.start0).days // 7
                words = f"{abs(n)} week{'' if abs(n) == 1 else 's'} {'later' if n > 0 else 'earlier'}, everything under it too" if n else "Where it is now"
                QToolTip.showText(event.globalPosition().toPoint(), f"{self.model.task(d.task).title}: {words}", self)
            elif d.start and d.end:
                n = sum((d.start + timedelta(days=i)).weekday() < 5 for i in range((d.end - d.start).days + 1))
                QToolTip.showText(event.globalPosition().toPoint(), f"{long_date(d.start, self.today)} → {long_date(d.end, self.today)} · "
                                                                    f"{n} workday{'s' if n != 1 else ''}", self)
            else:
                QToolTip.showText(event.globalPosition().toPoint(), "Let go over the chart to give it a week", self)
            self.update()
            return
        r, what = self._hit(x, y)
        hover = self.rows.index(r) if r is not None else -1
        if hover != self.hover:
            self.hover = hover
            self.update()
        shape = {"fold": Qt.CursorShape.PointingHandCursor, "grip": Qt.CursorShape.OpenHandCursor, "parent": Qt.CursorShape.OpenHandCursor,
                 "move": Qt.CursorShape.OpenHandCursor, "start": Qt.CursorShape.SizeHorCursor,
                 "end": Qt.CursorShape.SizeHorCursor}.get(what.removeprefix("kd-"), Qt.CursorShape.ArrowCursor)
        self.setCursor(shape)

    def _drag_to(self, d: Drag, x: float) -> None:
        """Where a drag puts the dates, snapping to days: a whole working week for a name, else the bar moved or stretched."""
        if d.mode == "new":
            if x < self.scale.NAME_W or x > self.scale.right(self):
                d.start = d.end = None
                return
            d.start, d.end = week_from(self.scale.day_at(self, x))
            return
        if d.start0 is None or d.end0 is None:
            return
        n = round((x - d.x0) / self.scale.px_per_day(self))
        s, e = d.start0, d.end0
        mode = d.mode.removeprefix("kd-")  # a key date moves and stretches as a bar does
        if mode == "parent":  # in whole weeks, so weekdays stay as they are (decision 290)
            n = 7 * round(n / 7)
            s, e = s + timedelta(days=n), e + timedelta(days=n)
        elif mode == "move":
            s, e = s + timedelta(days=n), e + timedelta(days=n)
        elif mode == "start":
            s = min(s + timedelta(days=n), e)
        else:
            e = max(e + timedelta(days=n), s)
        d.start, d.end = s, e

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.hover != -1:
            self.hover = -1
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        d, self.drag = self.drag, None
        QToolTip.hideText()
        if d is None or not d.moved:
            return
        self.update()
        if d.start is None or d.end is None or (d.mode != "new" and (d.start, d.end) == (d.start0, d.end0)):
            return
        if d.key_id is not None:
            self.dropped_key.emit(d.task, d.key_id, d.start, d.end, d.kind)
            return
        if d.mode == "parent":
            if d.start0 is not None:
                self.dropped_parent.emit(d.task, (d.start - d.start0).days // 7)
            return
        self.dropped.emit(d.task, d.start, d.end, d.mode)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        r, what = self._hit(event.position().x(), event.position().y())
        if r is None or what == "fold":
            return
        top = int(event.position().y() // self.ROW_H) * self.ROW_H
        bar = self.bar_rect(r, top) or QRectF(0, top, self.scale.NAME_W, self.ROW_H)
        self.picked.emit(r.task)
        self.quick_edit.emit(r.task, QRect(self.mapToGlobal(bar.topLeft().toPoint()), bar.size().toSize()))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - the arrows move and fold, Enter opens
        key = event.key()
        ids = [r.task for r in self.rows]
        if not ids or key not in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            super().keyPressEvent(event)
            return
        if self.sel not in ids:
            self.picked.emit(ids[0])
            return
        i = ids.index(self.sel)
        r = self.rows[i]
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.opened.emit(r.task)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.picked.emit(ids[max(0, min(len(ids) - 1, i + (-1 if key == Qt.Key.Key_Up else 1)))])
        elif key == Qt.Key.Key_Right:
            if r.kids and not r.open:
                self.fold.emit(r.task, True)
        elif r.open:
            self.fold.emit(r.task, False)
        else:
            parent = next((x.task for x in reversed(self.rows[:i]) if x.depth < r.depth), None)
            if parent:
                self.picked.emit(parent)

    def event(self, e) -> bool:  # noqa: D102 - hovering a row shows its dates, hours and people
        if e.type() == QEvent.Type.ToolTip and self.model is not None and self.drag is None:
            r = self.row_at(e.pos().y())
            run = self.run_at(e.pos().y()) if e.pos().x() < self.scale.key_w else None
            if run is not None:  # a lane's band: its name, and how many rows it holds
                n = run[1] - run[0] + 1
                QToolTip.showText(e.globalPos(), f"{run[3]}\n{n} row{'s' if n != 1 else ''} here", self)
            elif r is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(e.globalPos(), timeline.tooltip(self.model, r.task, self.today, self.order, self.plan), self)
            return True
        return super().event(e)


class Popover(QFrame):
    """A small panel under a button that goes when you click elsewhere: Display and Legend (the review's stage V5, so the
    chart keeps the room their controls took)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("popover")

    def open_under(self, button: QWidget) -> None:
        """Show it just under a button, kept on the screen."""
        self.adjustSize()
        at = button.mapToGlobal(button.rect().bottomLeft()) + QPoint(0, 3)
        screen = button.screen().availableGeometry()
        at.setX(max(screen.left(), min(at.x(), screen.right() - self.width())))
        self.move(at)
        self.show()


class FootLine(QWidget):
    """The one line that says what's selected (decision 292): its title in bold, then the rest in grey, ending in "…" when it
    doesn't fit, with all of it in the tooltip. ``text()`` is always all of it."""

    def __init__(self) -> None:
        super().__init__()
        self.title, self.rest = "", ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_line(self, title: str, rest: str, tip: str = "") -> None:
        self.title, self.rest = title, rest
        self.setToolTip(tip)
        self.setAccessibleName(self.text())
        self.update()

    def text(self) -> str:
        return f"{self.title}. {self.rest}" if self.title else self.rest

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(200, self.fontMetrics().height() + 4)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(0, self.fontMetrics().height() + 4)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        room = float(self.width())
        if self.title:
            bold = QFont(self.font())
            bold.setBold(True)
            p.setFont(bold)
            p.setPen(QColor(FG))
            shown = p.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, int(room * 0.6))
            p.drawText(QRectF(0, 0, room, self.height()), Qt.AlignmentFlag.AlignVCenter, shown)
            used = p.fontMetrics().horizontalAdvance(shown) + 10
            room -= used
            p.translate(used, 0)
        small = QFont(self.font())
        small.setPointSizeF(tokens.CAPTION)
        p.setFont(small)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, 0, room, self.height()), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.rest, Qt.TextElideMode.ElideRight, int(room)))
        p.end()


class TimelineView(QWidget):
    """The Timeline view: its controls, Plan mode's strip, the head and the rows, what's selected and the undated tasks, and
    Capacity's half under them (the Classic look: a legend, a card for the row clicked last, and no Capacity). ``open_task`` and ``update_task`` send a task to open, or to update in the capture
    window; ``quick_edit`` a task and its bar, for Quick edit; ``set_dates`` a task's new Start and Due (ISO dates, or None
    to clear), from a drag or Ctrl+Z, with what to say; ``folds_changed`` the rows now open, to remember them."""

    open_task = Signal(str)
    update_task = Signal(str)
    quick_edit = Signal(str, QRect)
    set_dates = Signal(str, object, object, str)
    #: A key date's new dates (release 5.31, decision 152): its task, its ID, its Start and End (YYYY-MM-DD or None), and what
    #: to say. The browse window saves it as ``edits.set_key_dates`` does, with the task's other key dates as they are.
    set_key_date = Signal(str, int, object, object, str)
    folds_changed = Signal(list)
    #: The view's choices that are remembered (the playbook: the zoom kept): the range, Order by, the bars' colour,
    #: Total or A week, and Show routine; and Capacity's half: open or folded, Percent or Hours, Group by group, and its height
    #: once it's been dragged.
    settings_changed = Signal(dict)
    REMEMBERED = ("weeks", "order", "bars", "a_week", "routine", "undated_open", "cap_open", "cap_unit", "cap_by_group", "cap_h")
    #: Add person, from Capacity with nobody to show.
    add_person = Signal()
    #: What-ifs (release 5.64): the list changed, to be kept; one to apply, its ID and the places of the things done left out;
    #: and a line for the status line.
    whatifs_changed = Signal()
    apply_whatif = Signal(str, list)
    said = Signal(str)
    #: The most of the page Capacity's half takes to start with, and the least either part can be dragged to.
    CAP_SHARE, CAP_MIN, TOP_MIN = 0.62, 96, 150

    def __init__(self) -> None:
        super().__init__()
        self.model: Model | None = None
        self.today = date.today()
        self.start: date | None = None
        self.weeks = 9
        self.typed_days: int | None = None  # a typed range's length (decision 225), in place of ``weeks``
        self.order = "top"
        self.bars = "project" if LOOK.classic else "one"  # decision 234
        self.a_week = False
        self.labels: list[str] = []
        self.people: list[str] = []
        self.routine = True
        self.plan = False
        self.focus: str | None = None
        self.open_ids: set[str] = set()
        self.sel: str | None = None
        # Each drop's step back: ("task", the task, its Start and Due before) or ("key", the task, the key date, its Start
        # and End before), last first.
        self.undo: list[tuple] = []
        self.scale = _Scale()
        # Capacity's half: where its hours come from (the browse window says), and its choices.
        self.load_cells: Callable[[list[date]], load.Cells] | None = None
        self.load_unplaced: Callable[[Model, date], tuple[list[str], list[str]]] | None = None
        self.cap_open = True
        self.cap_unit = "pct"
        self.cap_by_group = False
        self.cap_h: int | None = None
        self.cells: load.Cells = {}
        self.spot: Spot | None = None
        self.not_counted = ""  # the list of tasks Capacity can't count that's open: "hours", "dates" or none
        self.not_counted_ids: dict[str, list[str]] = {}
        # The tasks with no dates: all on one line when they fit on one, or else a count, with a fold that opens a short list
        # scrolling inside itself, so they never take the chart's room (the owner's comment, release 5.57).
        self.undated_ids: tuple[str, ...] = ()
        self.undated_open = False
        # What-ifs (release 5.64): the list, which the browse window keeps; the one showing, None for the real plan, which is
        # where DocRepo always starts (decision 228); each one's steps back; and what the one showing would do, from
        # ``picture_of``, which the browse window sets. ``real`` is the model as it is, ``model`` the one drawn.
        self.whatifs: list[whatif.WhatIf] = []
        self.cur: str | None = None
        self.wi_undo: dict[str, list[list[whatif.Action]]] = {}
        self.picture_of: Callable[[whatif.WhatIf], whatif.Picture] | None = None
        self.pic: whatif.Picture | None = None
        self.real: Model | None = None
        self.real_cells: load.Cells = {}
        #: Asks before a what-if with changes in it is deleted; and runs Review and apply. The browse window sets both.
        self.confirm: Callable[[str, str], bool] = lambda title, words: True
        self.run_dialog: Callable[[QWidget], bool] = lambda dialog: bool(dialog.exec())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8) if LOOK.classic else lay.setContentsMargins(16, 12, 16, 10)
        lay.addWidget(QLabel("Timeline", objectName="paneTitle"))
        lay.addWidget(Help("Open tasks over the coming weeks: a row per project, folded to start with, a bar from Start to Due, "
                           "a diamond for a deadline and a dot for each occurrence of a routine task. Parked and closed tasks are "
                           "left out. Click a row to see its dates and people; double-click a bar or a name for Quick edit."
                           + ("" if LOOK.classic else " Under it, Capacity has each person's load on the same dates: click a week "
                              "to see which tasks fill it.")))
        self.head = TimelineHead(self.scale)
        self.head.picked.connect(self._pick)
        self.chart = TimelineChart(self.scale)
        self.chart.picked.connect(self._pick)
        self.chart.opened.connect(self.open_task)
        self.chart.fold.connect(self.set_open)
        self.chart.quick_edit.connect(self._chart_quick_edit)
        self.chart.dropped.connect(self._dropped)
        self.chart.dropped_key.connect(self._dropped_key)
        self.chart.dropped_parent.connect(self._dropped_parent)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.chart)
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda *_: self._sync_inset())
        self.plan_strip = QFrame(objectName="fileRow")
        ps = QHBoxLayout(self.plan_strip)
        ps.setContentsMargins(10, 4, 6, 4)
        # It says what mode you're in. How it works is behind Show hints (decision 7, release 5.59).
        ps.addWidget(QLabel("<b>Plan mode</b>"))
        ps.addWidget(Help("Drag a bar, or its ends, to change its dates; drag a ⋮⋮ name onto the chart for a working week. Saved and "
                          "logged; Ctrl+Z undoes."), 1)
        ps.addStretch()
        done = QPushButton("Done")
        done.clicked.connect(lambda: self.set_plan(False))
        ps.addWidget(done)
        self.plan_strip.setStyleSheet(f"QFrame#fileRow {{ background-color: {SEL}; border: 1px solid {C.info_line}; border-radius: 4px; }}")
        self.open_button = QPushButton("Open task", objectName="primary" if LOOK.classic else "")
        self.open_button.clicked.connect(lambda: self.sel and self.open_task.emit(self.sel))
        self.quick_button = QPushButton("Quick edit")
        self.quick_button.clicked.connect(self._quick_from_card)
        self.update_button = QPushButton("Update")
        self.update_button.clicked.connect(lambda: self.sel and self.update_task.emit(self.sel))
        self.off_button = QPushButton("Take off")  # the page's: in a what-if, or starting one (release 5.64)
        self.off_button.setToolTip("See the load without it and everything under it, in a what-if. Your tasks don't change.")
        self.off_button.clicked.connect(lambda: self.sel and (self.put_back if self.sel in self.chart.off else self.take_off)(self.sel))
        self.off_button.hide()
        self.undated_fold = QToolButton(objectName="checkFold")
        self.undated_fold.setToolTip("Show or hide the tasks with no dates")
        self.undated_fold.setAccessibleName("Tasks with no dates")
        self.undated_fold.clicked.connect(self._toggle_undated)
        self.undated = QLabel(objectName="hint")
        self.undated.setWordWrap(True)
        self.undated.linkActivated.connect(self._undated_link)
        self.undated_names = QLabel(objectName="hint")
        self.undated_names.setWordWrap(True)
        self.undated_names.setTextFormat(Qt.TextFormat.RichText)
        self.undated_names.linkActivated.connect(self._undated_link)
        self.undated_box = QScrollArea()
        self.undated_box.setWidgetResizable(True)
        self.undated_box.setFrameShape(QFrame.Shape.NoFrame)
        self.undated_box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.undated_box.setWidget(self.undated_names)
        self.undated_box.hide()
        if LOOK.classic:
            self._build_classic(lay)
        else:
            self._build_page(lay)

    def _build_range(self, parent: QWidget) -> None:
        """From and To (decision 225), which outlive the redraws, so the caret stays in them."""
        self.range_box = QWidget(parent)
        self.range_layout = rb = QHBoxLayout(self.range_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(6)
        self.range_from, self.range_to = DateField(), DateField()
        if LOOK.classic:  # on the page the first box says what it is by what's in it, so the row has room
            rb.addWidget(QLabel("From", objectName="hint"))
        rb.addWidget(self.range_from)
        rb.addWidget(QLabel("to", objectName="hint"))
        rb.addWidget(self.range_to)
        for field, name, which, what in ((self.range_from, "First day shown", "from", "first"), (self.range_to, "Last day shown", "to", "last")):
            field.setFixedWidth(162 if LOOK.classic else 158)
            field.line.setAccessibleName(name)
            field.line.setToolTip(f"The {what} day to show. Type a date such as 2027-01-31, 31 Jan 2027 or Jan 2027, then press Enter")
            field.line.editingFinished.connect(lambda which=which: self._range_typed(which))
            field.picked.connect(lambda which=which: self._range_typed(which))
        self.range_note = QLabel(objectName="error")  # what's wrong with a typed day, on its own line so the boxes stay put
        self.range_note.hide()

    def _build_classic(self, lay: QVBoxLayout) -> None:
        """The Classic look: the chart alone, with two rows of controls, a card above it and a legend under it."""
        self.controls = QWidget()
        rows = QVBoxLayout(self.controls)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        time_row, show_row = QWidget(), QWidget()
        self.time_layout = FlowLayout(time_row, spacing=8)
        self.show_layout = FlowLayout(show_row, spacing=8)
        self._build_range(time_row)
        rows.addWidget(time_row)
        rows.addWidget(self.range_note)
        rows.addWidget(show_row)
        lay.addWidget(self.controls)
        lay.addWidget(self.plan_strip)
        self.card = QFrame(objectName="fileRow")
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(10, 6, 10, 6)
        self.card_text = QLabel()
        self.card_text.setWordWrap(True)
        self.card_text.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(self.card_text, 1)
        for b in (self.open_button, self.quick_button, self.update_button):
            cl.addWidget(b)
        lay.addWidget(self.card)
        lay.addWidget(self.head)
        lay.addWidget(self.scroll, 1)
        self.marks_legend = " &nbsp; ".join(_entry(mark, words) for mark, words in self._marks(C.g1))
        self.legend = QLabel(self.marks_legend, objectName="hint")  # one line: the marks, then what colours the bars
        self.legend.setWordWrap(True)
        lay.addWidget(self.legend)
        self.undated_bar = QWidget()
        ub = QHBoxLayout(self.undated_bar)
        ub.setContentsMargins(0, 0, 0, 0)
        ub.setSpacing(4)
        ub.addWidget(self.undated_fold)
        ub.addWidget(self.undated, 1)
        lay.addWidget(self.undated_bar)
        lay.addWidget(self.undated_box)

    @staticmethod
    def _marks(colour: str) -> list[tuple[str, str]]:
        """The chart's marks, for the legend, with the bars in ``colour``."""
        classic = LOOK.classic
        not_started = f"; border:1px solid {colour}" if classic else ""
        return [(f'<span style="background-color:{_mix(colour, 0.72).name()}">&nbsp;&nbsp;&nbsp;&nbsp;</span>', "In progress"),
                (f'<span style="background-color:{_mix(colour, 0.3).name()}{not_started}">&nbsp;&nbsp;&nbsp;&nbsp;</span>', "Not started"),
                (f'<span style="color:{BAD}"><b>▌</b></span>', "Late"), ("◆", "Deadline"), (f'<span style="color:{MUTED}"><b>⊢⊣</b></span>', "Its subtasks' span"),
                (f'<span style="color:{colour}">●</span>', "Routine: each occurrence"), (f'<span style="color:{ACCENT}"><b>│</b></span>', "Today"),
                (f'<span style="background-color:{EV_BG}; color:{EV_LINE}">&nbsp;{FLAG}&nbsp;</span>', "Plant event"),
                # Key dates (release 5.31): a window, a start or an end alone, a hard deadline
                (f'<span style="color:{colour}"><b>▬</b></span>', "Key date"), ("<b>[ ]</b>", "Its start or end"),
                (f'<span style="color:{BAD}">◆</span>', "Its deadline")]

    def _build_page(self, lay: QVBoxLayout) -> None:
        """The one page (decision 229): one row of controls, the chart, a line saying what's selected, and Capacity's half."""
        self.tools = QWidget()
        self.time_layout = FlowLayout(self.tools, spacing=8)
        self._build_range(self.tools)
        moves = QWidget()
        ml = QHBoxLayout(moves)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(4)
        for text, s, tip in (("Earlier", -1, "Back four weeks (13 over six months, 26 over a year), never more than the range shown"),
                             ("This week", 0, "From last week"),
                             ("Later", 1, "On four weeks (13 over six months, 26 over a year), never more than the range shown")):
            b = DropButton(text, arrow="chevron-right") if s > 0 else QPushButton(text)
            if s < 0:
                b.setIcon(icon("chevron-left"))
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=s: self.shift(s))
            ml.addWidget(b)
        self.time_layout.addWidget(moves)
        self.plan_button = QPushButton("Plan")
        self.plan_button.setIcon(icon("edit"))
        self.plan_button.setCheckable(True)
        self.plan_button.setToolTip("Plan mode: drag bars and names to set dates (P)")
        self.plan_button.clicked.connect(lambda on: self.set_plan(on))
        self.time_layout.addWidget(self.plan_button)
        self._build_whatifs()
        self.time_layout.addWidget(self.whatif_button)
        self.people_button: CheckMenuButton | None = None  # made when there's a model, with its people
        self.labels_button: CheckMenuButton | None = None
        self.display_button = DropButton("Display")
        self.display_button.setToolTip("Order by, Colour bars by, Hours, Focus, Show routine and Labels")
        self.legend_button = DropButton("Legend")
        self.legend_button.setToolTip("What the marks and colours mean")
        self.time_layout.addWidget(self.display_button)
        self.time_layout.addWidget(self.legend_button)
        # Show and the range at the row's right end, where most tools put them (the review's stage V5).
        self.show_box = QComboBox()
        self.show_box.setAccessibleName("Show")
        self.show_box.currentIndexChanged.connect(lambda _: self._box_changed(self.show_box, "weeks"))
        self.range_layout.insertWidget(0, self.show_box)
        self.range_box.setProperty("flowEnd", True)
        self.time_layout.addWidget(self.range_box)
        lay.addWidget(self.tools)
        lay.addWidget(self.range_note)
        self.chips = QWidget()  # the filters in use
        self.chips_layout = FlowLayout(self.chips, spacing=6)
        self.chips.hide()
        self._chips_shown: tuple = ()
        lay.addWidget(self.chips)
        lay.addWidget(self.plan_strip)
        lay.addWidget(self.whatif_strip)
        self._build_display()
        self.legend_box = Popover(self)
        self.legend = QLabel()
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        lb = QVBoxLayout(self.legend_box)
        lb.setContentsMargins(12, 10, 12, 10)
        lb.addWidget(self.legend)
        self.display_button.clicked.connect(lambda: self.display_box.open_under(self.display_button))
        self.legend_button.clicked.connect(lambda: self.legend_box.open_under(self.legend_button))
        # The levels, at the head of the names' column.
        self.level_buttons = []
        for i, (text, n, name) in enumerate((("Collapse a level", -1, "level-fold"), ("Expand a level", 1, "level-open"))):
            b = QToolButton(self.head, objectName="checkFold")
            b.setIcon(icon(name))
            b.setAccessibleName(text)
            b.setToolTip(text)
            b.setFixedSize(22, 20)
            b.clicked.connect(lambda _=False, n=n: self.level(n))
            b.move(40 + i * 24, 20)
            self.level_buttons.append(b)
        # The top part: the chart, then what's selected, on a line of its own so picking a bar moves nothing (decision 292).
        self.card = QFrame(objectName="timelineFoot")
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(0, 3, 0, 3)
        cl.setSpacing(6)
        self.card_text = FootLine()
        cl.addWidget(self.card_text, 1)
        for b in (self.open_button, self.quick_button, self.update_button, self.off_button):
            cl.addWidget(b)
        self.undated_fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        cl.addWidget(self.undated_fold)
        self.card.setMinimumHeight(tokens.CONTROL + 8)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(self.head)
        tl.addWidget(self.scroll, 1)
        tl.addWidget(self.undated_box)
        tl.addWidget(self.card)
        top.setMinimumHeight(self.TOP_MIN)
        self._build_capacity()
        self.split = QSplitter(Qt.Orientation.Vertical, objectName="timelineSplit")
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(7)
        self.split.addWidget(top)
        self.split.addWidget(self.cap_box)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.splitterMoved.connect(self._split_moved)
        lay.addWidget(self.split, 1)
        self.cap_card = QFrame(self, objectName="capCard")  # the spotlight's card, over the page
        self.cap_card.hide()
        self.scale.inset = self.scroll.verticalScrollBar().sizeHint().width()  # kept whether or not a bar shows, so nothing shifts

    def _build_display(self) -> None:
        """Display: how the chart is drawn and filtered."""
        self.display_box = Popover(self)
        grid = QGridLayout(self.display_box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        def row(n: int, words: str, widget: QWidget) -> None:
            grid.addWidget(QLabel(words, objectName="fieldLabel"), n, 0)
            grid.addWidget(widget, n, 1)

        self.order_box, self.bars_box, self.focus_box = QComboBox(), QComboBox(), QComboBox()
        for box, name, key in ((self.order_box, "Order by", "order"), (self.bars_box, "Colour bars by", "bars"), (self.focus_box, "Focus on", "focus")):
            box.setAccessibleName(name)
            box.currentIndexChanged.connect(lambda _, box=box, key=key: self._box_changed(box, key))
        self.focus_box.setMaximumWidth(280)
        row(0, "Order by", self.order_box)
        row(1, "Colour bars by", self.bars_box)
        seg, self.hours_buttons = self._seg(((False, "Total"), (True, "A week")), lambda on: self._set("a_week", on),
                                            "What each bar says: its total hours, or that a week over its workdays")
        row(2, "Hours on bars", seg)
        row(3, "Focus on", self.focus_box)
        self.routine_box = QCheckBox("Show routine")
        self.routine_box.setToolTip("Recurring tasks, such as meetings")
        self.routine_box.toggled.connect(lambda on: self._set("routine", on))
        grid.addWidget(self.routine_box, 4, 1)
        grid.addWidget(QLabel("Labels", objectName="fieldLabel"), 5, 0)
        self.display_grid = grid

    def _build_whatifs(self) -> None:
        """The what-ifs' button and its list, and the strip that stays while one is showing, so it can't be taken for the real
        plan (release 5.64)."""
        self.whatif_button = DropButton("What-ifs")
        self.whatif_button.setCheckable(True)  # pressed while one is showing
        self.whatif_button.clicked.connect(lambda: (self.whatif_button.setChecked(self.cur is not None), self._open_whatifs()))
        self.whatif_box = Popover(self)
        self.whatif_list = QGridLayout(self.whatif_box)
        self.whatif_list.setContentsMargins(8, 8, 8, 8)
        self.whatif_list.setHorizontalSpacing(8)
        self.whatif_list.setVerticalSpacing(2)
        self.whatif_strip = QFrame(objectName="fileRow")
        ws = QHBoxLayout(self.whatif_strip)
        ws.setContentsMargins(10, 4, 6, 4)
        ws.setSpacing(8)
        ws.addWidget(QLabel("<b>What-if</b>"))
        self.whatif_name = QLineEdit()
        self.whatif_name.setAccessibleName("This what-if's name")
        self.whatif_name.setFixedWidth(190)
        self.whatif_name.editingFinished.connect(self._rename)
        ws.addWidget(self.whatif_name)
        ws.addWidget(QLabel("Your tasks haven't changed."))
        self.whatif_facts = QLabel(objectName="hint")
        ws.addWidget(self.whatif_facts, 1)
        self.whatif_undo = QPushButton("Undo")
        self.whatif_undo.setToolTip("The last change in this what-if (Ctrl+Z)")
        self.whatif_undo.clicked.connect(self.undo_whatif)
        self.whatif_review = QPushButton("Review and apply")
        self.whatif_review.setToolTip("See each change, and apply those you want to your tasks")
        self.whatif_review.clicked.connect(self.review)
        back = QPushButton("Back to the real plan")
        back.clicked.connect(lambda: self.show_whatif(None))
        for b in (self.whatif_undo, self.whatif_review, back):
            ws.addWidget(b)
        self.whatif_strip.setStyleSheet(f"QFrame#fileRow {{ background-color: {SEL}; border: 1px solid {C.info_line}; border-radius: 4px; }}")
        self.whatif_strip.hide()

    @staticmethod
    def _seg(items, picked: Callable, tip: str = "") -> tuple[QWidget, dict]:
        """Two buttons of which one is on."""
        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        group = QButtonGroup(seg)
        buttons = {}
        for value, text in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            group.addButton(b)
            b.clicked.connect(lambda _=False, value=value: picked(value))
            sl.addWidget(b)
            buttons[value] = b
        return seg, buttons

    def _build_capacity(self) -> None:
        """Capacity's half: its head with the sentence, the team chart, and the people's rows, which scroll."""
        self.cap_box = QWidget()
        self.cap_box.setMinimumHeight(self.CAP_MIN)
        box = QVBoxLayout(self.cap_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.cap_head = QWidget()
        head = QHBoxLayout(self.cap_head)
        head.setContentsMargins(0, 4, 0, 4)
        head.setSpacing(8)
        self.cap_fold = QToolButton(objectName="checkFold")
        self.cap_fold.setAccessibleName("Fold Capacity")
        self.cap_fold.clicked.connect(lambda: self._set("cap_open", not self.cap_open))
        head.addWidget(self.cap_fold)
        title = QLabel("Capacity")
        title.setFont(tokens.ui_font(semibold=True))
        head.addWidget(title)
        self.cap_say = QLabel()
        self.cap_say.setWordWrap(True)
        self.cap_say.setTextFormat(Qt.TextFormat.RichText)
        self.cap_say.setAccessibleName("Who is over, and when")
        head.addWidget(self.cap_say, 1)
        seg, self.unit_buttons = self._seg((("pct", "Percent"), ("hours", "Hours")), lambda unit: self._set("cap_unit", unit),
                                           "What each cell says. The other number is in its tooltip")
        head.addWidget(seg)
        self.cap_group = QCheckBox("Group by group")
        self.cap_group.setToolTip("Put people under their groups' headings")
        self.cap_group.toggled.connect(lambda on: self._set("cap_by_group", on))
        head.addWidget(self.cap_group)
        box.addWidget(self.cap_head)
        self.cap_team = CapacityTeam(self.scale)
        self.cap_rows = CapacityRows(self.scale)
        for strip in (self.cap_team, self.cap_rows):
            strip.picked.connect(self._cell_picked)
            strip.hovered.connect(self._week_hovered)
        self.cap_rows.solo.connect(self._solo)
        box.addWidget(self.cap_team)
        self.cap_scroll = QScrollArea()
        self.cap_scroll.setWidgetResizable(True)
        self.cap_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cap_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cap_scroll.setWidget(self.cap_rows)
        box.addWidget(self.cap_scroll, 1)
        self.cap_empty = QWidget()
        el = QHBoxLayout(self.cap_empty)
        el.setContentsMargins(12, 8, 0, 8)
        el.setSpacing(12)
        el.addWidget(QLabel("Add people to see their load."))
        add = QPushButton("Add person")
        add.clicked.connect(lambda _=False: self.add_person.emit())
        el.addWidget(add)
        el.addStretch()
        self.cap_empty.hide()
        box.addWidget(self.cap_empty)
        # What isn't counted, since that work makes the load look lighter than it is.
        self.cap_note = QLabel(objectName="hint")
        self.cap_note.setWordWrap(True)
        self.cap_note.setTextFormat(Qt.TextFormat.RichText)
        self.cap_note.linkActivated.connect(self._note_link)
        self.cap_note.setContentsMargins(0, 4, 0, 2)
        box.addWidget(self.cap_note)
        self.cap_list = QLabel(objectName="hint")
        self.cap_list.setWordWrap(True)
        self.cap_list.setTextFormat(Qt.TextFormat.RichText)
        self.cap_list.linkActivated.connect(self._undated_link)
        self.cap_list_box = QScrollArea()
        self.cap_list_box.setWidgetResizable(True)
        self.cap_list_box.setFrameShape(QFrame.Shape.NoFrame)
        self.cap_list_box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cap_list_box.setWidget(self.cap_list)
        self.cap_list_box.hide()
        box.addWidget(self.cap_list_box)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._fit_room()
        if self.undated_ids:
            self._draw_undated()
        if not LOOK.classic and self.scale.tl is not None:
            self._draw_capacity()
            self._fit_split()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """P for Plan mode, and Ctrl+Z for the last drop (decisions 136 and 144), wherever the caret is in the view but a
        text box. P is free in the browse tool."""
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if event.key() == Qt.Key.Key_P and mods == Qt.KeyboardModifier.NoModifier:
            if self.cur is not None:
                self.said.emit("In a what-if, bars always drag. Nothing changes until you apply it.")
            else:
                self.set_plan(not self.plan)
        elif event.key() == Qt.Key.Key_Z and mods == Qt.KeyboardModifier.ControlModifier:
            self.undo_whatif() if self.cur is not None else self.undo_last()
        elif event.key() == Qt.Key.Key_Escape and not LOOK.classic and self.spot is not None:
            self.clear_spot()
        elif event.key() == Qt.Key.Key_Escape and not LOOK.classic and self.sel:
            self._pick(None)
        else:
            super().keyPressEvent(event)

    def render(self, model: Model, today: date) -> None:
        """Draw the view again from the model, keeping its controls' choices. In a what-if, what it would do is drawn."""
        self.real, self.today = model, today
        if self.cur is not None and (LOOK.classic or self.showing() is None):
            self.cur = None
        w = self.showing()
        self.pic = self.picture_of(w) if w is not None and self.picture_of is not None else None
        if self.pic is not None:
            model = whatif.drawn(self.pic, model)
        self.model = model
        if self.start is None:
            self.start = timeline.default_start(today)
        if self.sel and self.sel not in model.tasks:
            self.sel = None
        if self.focus and self.focus not in model.tasks:
            self.focus = None
        if self.order not in {k for k, _ in timeline.order_choices(model)}:  # a parent label that's no longer one
            self.order = "top"
        if LOOK.classic:
            self._controls()
        else:
            self._sync_tools()
        # With the page, tasks with no dates join the chart only while their fold is open, Plan mode or not (decision 291). In a
        # what-if, bars always drag.
        drags = self.plan or self.pic is not None
        rows_undated = drags and (LOOK.classic or self.undated_open)
        tl = timeline.build(model, today, self.start, self.weeks, self.order, tuple(self.labels), tuple(self.people), self.routine,
                            self.open_ids, rows_undated, self.focus, self.typed_days, list_undated=not LOOK.classic)
        self.scale.tl = tl
        self._show_range(tl)
        self.scale.set_order(self.order)
        self._fit_room()
        self._sync_inset()
        self.head.set_timeline(model, today, model.task(self.focus).title if self.focus else "", self.sel, field_names(self.order)[0])
        self._whatif_marks()
        self.chart.set_timeline(model, today, self.sel, drags, self.bars, self.a_week, self.order)
        if not LOOK.classic:  # gone where nothing nests
            for i, b in enumerate(self.level_buttons):
                b.move(self.scale.key_w + 40 + i * 24, 20)
                b.setVisible(any(r.kids for r in tl.rows))
            self._sync_whatif()
        self.plan_strip.setVisible(self.plan and self.pic is None)
        self._card()
        self.undated_ids = tl.undated
        self._draw_undated()
        if not LOOK.classic:
            self._render_capacity()
            self._fit_split()

    def _draw_undated(self) -> None:
        """The tasks with no dates: their names if they fit on one line, or else how many, with the names behind the fold. On
        the page they're a count on the line under the chart, and with the fold open in Plan mode they're rows on the chart."""
        ids = self.undated_ids
        if not LOOK.classic:
            n = len(ids)
            self.undated_fold.setVisible(bool(n))
            set_fold(self.undated_fold, f"{n} with no dates", self.undated_open)
            self.undated_box.setVisible(bool(n) and self.undated_open)
            if n and self.undated_open and self.model is not None:
                if self.plan or self.pic is not None:
                    self.undated_names.setText("They're on the chart now, each with a ⋮⋮ to drag onto the dates.")
                else:
                    names = ", ".join(f'<a href="task:{esc(x)}">{esc(self.model.task(x).title)}</a>' for x in ids)
                    self.undated_names.setText(f'{names}. <a href="plan:">Plan mode</a> puts them on the chart, to drag onto the dates.')
                self.undated_box.setFixedHeight(min(UNDATED_MAX_HEIGHT, self.undated_names.heightForWidth(max(200, self.scale.room or 200))))
            return
        self.undated_bar.setVisible(bool(ids))
        if not ids or self.model is None:
            self.undated_box.hide()
            return
        ask = "Plan mode puts them on it, to drag onto the chart."
        link = '<a href="plan:">Plan mode</a> puts them on it, to drag onto the chart.'
        titles = [self.model.task(x).title for x in ids]
        names = ", ".join(f'<a href="task:{esc(x)}">{esc(t)}</a>' for x, t in zip(ids, titles))
        words = f"Not on the timeline, with no dates: {', '.join(titles)}. {ask}"
        fits = QFontMetrics(self.undated.font()).horizontalAdvance(words) <= self.undated_bar.width()
        self.undated_fold.setVisible(not fits)
        if fits:
            self.undated.setText(f"Not on the timeline, with no dates: {names}. {link}")
            self.undated_box.hide()
            return
        count = f"{len(ids)} task" if len(ids) == 1 else f"{len(ids)} tasks"
        self.undated.setText(f"Not on the timeline, with no dates: {count}. {link}")
        self.undated_fold.setIcon(icon("chevron-down" if self.undated_open else "chevron-right"))
        self.undated_names.setText(names)
        self.undated_box.setVisible(self.undated_open)
        if self.undated_open:
            self.undated_box.setFixedHeight(min(UNDATED_MAX_HEIGHT, self.undated_names.heightForWidth(self.undated_bar.width())))

    def _toggle_undated(self) -> None:
        self.undated_open = not self.undated_open
        self.settings_changed.emit(self.settings())
        if not LOOK.classic and (self.plan or self.pic is not None) and self.model is not None:  # its rows join the chart or leave it
            self._redraw()
            return
        self._draw_undated()

    def _fit_room(self) -> None:
        """Every part of the page places a day by the page's width, so the chart, its head and Capacity's rows line up."""
        m = self.layout().contentsMargins()
        room = self.width() - m.left() - m.right()
        if room == self.scale.room:
            return
        self.scale.room = room
        if self.scale.tl is not None:
            self.head._place()
            self.head.update()
            self.chart.update()

    def _sync_inset(self) -> None:
        if not LOOK.classic:  # the page keeps the room for a scroll bar whether or not one shows
            return
        bar = self.scroll.verticalScrollBar()
        inset = bar.sizeHint().width() if bar.maximum() > 0 else 0
        if inset != self.scale.inset:
            self.scale.inset = inset
            self.head.update()
            self.chart.update()

    def _undated_link(self, href: str) -> None:
        kind, _, ref = href.partition(":")
        if kind == "plan":
            self.set_plan(True)
        else:
            self.open_task.emit(ref)

    @staticmethod
    def _fill(box: QComboBox, items: list[tuple], current) -> None:
        """A combo box's items and choice, without saying it changed. Its list changes only when it has to."""
        box.blockSignals(True)
        if [(box.itemData(i), box.itemText(i)) for i in range(box.count())] != list(items):
            box.clear()
            for value, label in items:
                box.addItem(label, value)
        box.setCurrentIndex(max(0, box.findData(current)))
        box.blockSignals(False)

    def _box_changed(self, box: QComboBox, key: str) -> None:
        value = box.currentData()
        if value == 0 and key == "weeks":  # Show these dates is what a typed range says, not a choice
            return
        self._set(key, value)

    def _sync_tools(self) -> None:
        """The page's controls say what's chosen. Those that list people or labels are made again when the list changes."""
        m = self.model
        assert m is not None
        self.plan_button.setChecked(self.plan)
        shows = [(n, f"Show {label}") for n, label in timeline.RANGES]
        self._fill(self.show_box, [*shows, (0, "Show these dates")] if self.typed_days else shows, 0 if self.typed_days else self.weeks)
        self._fill(self.order_box, [(k, label[0].upper() + label[1:]) for k, label in timeline.order_choices(m)], self.order)
        self._fill(self.bars_box, [(k, label) for k, label in timeline.BARS], self.bars)
        self._fill(self.focus_box, [("", "All projects"), *self._focus_choices()], self.focus or "")
        self.hours_buttons[self.a_week].setChecked(True)
        self.routine_box.blockSignals(True)
        self.routine_box.setChecked(self.routine)
        self.routine_box.blockSignals(False)
        choices, sets = people_filter(m)
        self.people_button = self._menu_button(self.people_button, "People", "anyone", choices, sets, self.people, "people",
                                               lambda b: self.time_layout.insert_widget(self.time_layout.indexOf(self.display_button), b))
        choices, sets = label_filter(m)
        self.labels_button = self._menu_button(self.labels_button, "Labels", "any", choices, sets, self.labels, "labels",
                                               lambda b: self.display_grid.addWidget(b, 5, 1))
        self.legend.setText(self._legend_text())
        self._sync_chips()
        for value, b in self.unit_buttons.items():
            b.setChecked(value == self.cap_unit)
        self.cap_group.blockSignals(True)
        self.cap_group.setChecked(self.cap_by_group)
        self.cap_group.blockSignals(False)

    def _menu_button(self, old: CheckMenuButton | None, noun: str, empty: str, choices, sets, picked: list[str], key: str, place: Callable) -> CheckMenuButton:
        """A filter's button, kept while its list and ticks are as they were."""
        ids = [v for _, v in choices]
        if old is not None and [a.data() for a in old.choices] == ids and [a.text() for a in old.choices] == [t for t, _ in choices] and sorted(old.values()) == sorted(picked):
            return old
        if old is not None:  # hidden now, deleted once the signal that redraws the view has returned
            self.time_layout.removeWidget(old)
            self.display_grid.removeWidget(old)
            old.hide()
            old.deleteLater()
        b = CheckMenuButton(noun, empty, choices, picked, sets)
        b.chosen.connect(lambda values, key=key: self._set(key, values))
        place(b)
        return b

    def _sync_chips(self) -> None:
        """The filters in use, each with its ×."""
        m = self.model
        assert m is not None
        wanted = [("people", p, m.person_name(p)) for p in self.people] + [("labels", n, n) for n in self.labels]
        if self.focus and self.focus in m.tasks:
            wanted.append(("focus", self.focus, f"Focus: {m.task(self.focus).title}"))
        if tuple(wanted) == self._chips_shown:
            return
        self._chips_shown = tuple(wanted)
        while self.chips_layout.count():
            w = self.chips_layout.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        for kind, value, words in wanted:
            b = QPushButton(f"{words}  ×", objectName="filterChip")
            b.setToolTip(f"Stop filtering by {words}")
            b.clicked.connect(lambda _=False, kind=kind, value=value: self._drop_filter(kind, value))
            self.chips_layout.addWidget(b)
        self.chips.setVisible(bool(wanted))

    def _drop_filter(self, kind: str, value: str) -> None:
        if kind == "focus":
            self._set("focus", "")
        else:
            self._set(kind, [x for x in getattr(self, kind) if x != value])

    def _legend_text(self) -> str:
        """What the marks and colours mean, behind the Legend button."""
        colour = C.g1 if self.bars == "project" else C.bar
        marks = "<br>".join(_entry(mark, words) for mark, words in self._marks(colour))
        keys = self._keys_legend()
        cell = '<span style="background-color:{}">&nbsp;&nbsp;&nbsp;&nbsp;</span>'
        steps = "<br>".join(_entry(cell.format(c), words) for c, words in ((C.load1, "Under 40%"), (C.load2, "40 to 79%"), (C.load3, "80 to 100%"),
                                                                            (C.load4, "Over 100%"), (C.load5, "125% or more")))
        extra = f"<br><br>{keys}" if keys else ""
        return f"<b>The bars</b><br>{marks}{extra}<br><br><b>A week's load</b><br>{steps}"

    def _controls(self) -> None:
        """The controls in two rows, each in groups with a divider between (the playbook's toolbar groups): time and what's
        shown (Earlier, This week, Later, the range; Focus and the levels; Plan), then how it's drawn and filtered (Order
        by, Colour bars by, Hours; Labels, People, Show routine)."""
        for lay in (self.time_layout, self.show_layout):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w is not None and w is not self.range_box:  # hidden now, deleted once the signal that redraws the view has returned
                    w.hide()
                    w.deleteLater()
        m = self.model
        assert m is not None

        def combo(lay, name: str, items, current, key: str) -> QComboBox:
            box = QComboBox()
            box.setAccessibleName(name)
            for value, label in items:
                box.addItem(label, value)
            box.setCurrentIndex(max(0, box.findData(current)))
            box.currentIndexChanged.connect(lambda _: self._set(key, box.currentData()))
            lay.addWidget(box)
            return box

        def divider(lay) -> None:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFixedSize(9, 22)
            line.setStyleSheet(f"color: {LINE};")
            lay.addWidget(line)

        lay = self.time_layout
        for text, s, tip in (("Earlier", -1, "Back four weeks (13 over six months, 26 over a year), never more than the range shown"),
                             ("This week", 0, "From last week"),
                             ("Later", 1, "On four weeks (13 over six months, 26 over a year), never more than the range shown")):
            b = DropButton(text, arrow="chevron-right") if s > 0 else QPushButton(text)
            if s < 0:
                b.setIcon(icon("chevron-left"))
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=s: self.shift(s))
            lay.addWidget(b)
        shows = [(n, f"Show {label}") for n, label in timeline.RANGES]
        combo(lay, "Show", [*shows, (0, "Show these dates")] if self.typed_days else shows, 0 if self.typed_days else self.weeks, "weeks")
        lay.addWidget(self.range_box)
        self.range_box.show()
        divider(lay)
        focus = combo(lay, "Focus on", [("", "Focus on all projects"), *((x, "Focus on " + name) for x, name in self._focus_choices())],
                      self.focus or "", "focus")
        focus.setMaximumWidth(280)
        for text, n, name in (("Collapse a level", -1, "level-fold"), ("Expand a level", 1, "level-open")):
            b = QPushButton(text if LOOK.classic else "", objectName="" if LOOK.classic else "iconOnly")
            if not LOOK.classic:
                b.setIcon(icon(name))
                b.setAccessibleName(text)
                b.setToolTip(text)
            b.clicked.connect(lambda _=False, n=n: self.level(n))
            lay.addWidget(b)
        divider(lay)
        plan = QPushButton("✎ Plan" if LOOK.classic else "Plan")
        if not LOOK.classic:
            plan.setIcon(icon("edit"))
        plan.setCheckable(True)
        plan.setChecked(self.plan)
        plan.setToolTip("Plan mode: drag bars and names to set dates (P)")
        plan.clicked.connect(lambda on: self.set_plan(on))
        lay.addWidget(plan)
        lay = self.show_layout
        combo(lay, "Order by", [(k, f"Order by {label}") for k, label in timeline.order_choices(m)], self.order, "order")
        combo(lay, "Colour bars by", [(k, f"Colour bars by {label.lower()}") for k, label in timeline.BARS if k != "one"], self.bars, "bars")
        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(QLabel("Hours "))
        group = QButtonGroup(seg)
        for on, text in ((False, "Total"), (True, "A week")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(self.a_week == on)
            b.setToolTip("What each bar says: its total hours, or that a week over its workdays")
            group.addButton(b)
            b.clicked.connect(lambda _=False, on=on: self._set("a_week", on))
            sl.addWidget(b)
        lay.addWidget(seg)
        divider(lay)
        # A parent label ticks its sublabels, and a group its people (release 5.9).
        choices, sets = label_filter(m)
        labels = CheckMenuButton("Labels", "any", choices, self.labels, sets)
        labels.chosen.connect(lambda values: self._set("labels", values))
        lay.addWidget(labels)
        choices, sets = people_filter(m)
        people = CheckMenuButton("People", "anyone", choices, self.people, sets)
        people.chosen.connect(lambda values: self._set("people", values))
        lay.addWidget(people)
        routine = QCheckBox("Show routine")
        routine.setToolTip("Recurring tasks, such as meetings")
        routine.setChecked(self.routine)
        routine.toggled.connect(lambda on: self._set("routine", on))
        lay.addWidget(routine)
        keys = self._keys_legend()
        self.legend.setText(self.marks_legend + (" &nbsp;·&nbsp; " + keys if keys else ""))

    def _focus_choices(self) -> list[tuple[str, str]]:
        """Every open task with open subtasks, in the tree's order, indented by depth."""
        m = self.model
        assert m is not None
        out: list[tuple[str, str]] = []
        seen: set[str] = set()

        def walk(ids: list[str], depth: int) -> None:
            for x in ids:
                t = m.task(x)
                kids = [k for k in m.children_of(x) if m.task(k).state not in ("Closed", "Parked") and not m.task(k).discarded]
                if x in seen or t.state in ("Closed", "Parked") or t.discarded or not kids:
                    continue
                seen.add(x)
                out.append((x, " " * depth + t.title))
                walk(kids, depth + 1)

        walk([t.id for t in m.top_level()], 0)
        return out

    def _keys_legend(self) -> str:
        """What colours the bars, as small squares (Order by's keys are named in the lane column, so they need none)."""
        def sq(colour: str, dashed: bool = False) -> str:
            # A label's rich text draws no borders, so a bar with nothing to colour it by (drawn dashed) is a pale square.
            return f'<span style="background-color:{HOVER if dashed else colour}">&nbsp;&nbsp;&nbsp;</span>'

        parts = []
        if self.bars == "hours":
            parts.append("Hours a week: " + " ".join(f"{sq(HOUR_COLOURS[i])} {name}" for i, (_, name) in enumerate(timeline.HOUR_BINS))
                         + f" {sq('', True)} No hours")
        elif self.bars == "priority":
            from docrepo.model import PRIORITY_NAMES

            parts.append("Priority: " + " ".join(f"{sq(PRIORITY_COLOURS[k])} {name}" for k, name in PRIORITY_NAMES.items())
                         + f" {sq('', True)} Not ranked")
        return " &nbsp;·&nbsp; ".join(parts)

    def settings(self) -> dict:
        kept = {k: getattr(self, k) for k in self.REMEMBERED}
        kept["bars_v"] = 2  # bars can be one colour: a "project" saved since then was chosen
        if self.typed_days and self.start is not None:  # a typed range: its days, until a Show choice replaces them
            kept["range"] = [self.start.isoformat(), (self.start + timedelta(days=self.typed_days - 1)).isoformat()]
        return kept

    def restore(self, saved: dict) -> None:
        """The choices kept from last time, each only when it's still one the view offers."""
        valid = {"weeks": {n for n, _ in timeline.RANGES}, "bars": {k for k, _ in timeline.BARS if k != "one" or not LOOK.classic},
                 "cap_unit": {"pct", "hours"}}
        for key in self.REMEMBERED:
            value = saved.get(key)
            if value is None or (key in valid and value not in valid[key]):
                continue
            if key == "bars" and value == "project" and not saved.get("bars_v"):  # saved before bars could be one colour (decision 234)
                continue
            if key in ("a_week", "routine", "undated_open", "cap_open", "cap_by_group"):
                value = bool(value)
            elif key == "order" and not isinstance(value, str):
                continue
            elif key == "cap_h" and not isinstance(value, int):
                continue
            setattr(self, key, value)
        try:
            first, last = (date.fromisoformat(x) for x in saved["range"])
        except (KeyError, TypeError, ValueError):
            return
        if 0 <= (last - first).days < timeline.MAX_RANGE_DAYS:
            self.start, self.typed_days = first, (last - first).days + 1

    def _show_range(self, tl: Timeline) -> None:
        """From and To say what's in view, except a box that's being typed in."""
        for field, day in ((self.range_from, tl.start), (self.range_to, tl.end - timedelta(days=1))):
            if not field.line.isModified():
                field.set_value(day.isoformat())

    def _range_typed(self, which: str) -> None:
        """A day typed in From or To, or picked from its calendar: show exactly those days. A From past To, or a To before
        From, takes the other along, so the range keeps its length and retyping both dates never stops at a wrong one."""
        tl = self.scale.tl
        if tl is None or self.model is None:
            return
        first, last = timeline.read_range_day(self.range_from.line.text()), timeline.read_range_day(self.range_to.line.text(), last=True)
        if first is None or last is None:
            bad = "From" if first is None else "To"
            self._range_says(f"{bad}: type a date such as 2027-01-31, 31 Jan 2027 or Jan 2027")
            return
        if first > last:
            length = (tl.end - tl.start).days - 1
            if which == "from":
                last = first + timedelta(days=length)
            else:
                first = last - timedelta(days=length)
        if (last - first).days >= timeline.MAX_RANGE_DAYS:
            self._range_says("The range can be up to five years")
            return
        self._range_settled()
        if (first, last) == (tl.start, tl.end - timedelta(days=1)):  # nothing new: a Show choice stays one
            self._show_range(tl)
            return
        self.start, self.typed_days = first, (last - first).days + 1
        self.settings_changed.emit(self.settings())
        self._redraw()

    def _range_says(self, text: str) -> None:
        self.range_note.setText(text)
        self.range_note.setVisible(bool(text))

    def _range_settled(self) -> None:
        """Nothing left to fix: the note goes, and what's in the boxes gives way to the next redraw."""
        self._range_says("")
        for field in (self.range_from, self.range_to):
            field.line.setModified(False)

    def _set(self, key: str, value) -> None:
        if key == "focus":
            value = value or None
            if value and self.model is not None:  # everything under it open
                for x in [value, *self.model.descendants_of(value)]:
                    if self.model.children_of(x):
                        self.open_ids.add(x)
                self.folds_changed.emit(sorted(self.open_ids))
        elif key == "weeks":  # a Show choice replaces a typed range, from the Monday of its first week
            self.typed_days = None
            self._range_settled()
            if self.start is not None:
                self.start = monday_of(self.start)
        setattr(self, key, value)
        if key in self.REMEMBERED:
            self.settings_changed.emit(self.settings())
        if self.model is not None:
            self._redraw()

    def set_plan(self, on: bool) -> None:
        """Plan mode on or off (P, the Plan button, or Done)."""
        self.plan = bool(on)
        if self.model is not None:
            self._redraw()

    def set_open(self, task_id: str, open_: bool) -> None:
        """A row's subtasks shown or folded: its arrow, Right or Left."""
        (self.open_ids.add if open_ else self.open_ids.discard)(task_id)
        self.folds_changed.emit(sorted(self.open_ids))
        if self.model is not None:
            self._redraw()

    def level(self, step: int) -> None:
        """Expand a level opens every row shown that has subtasks; Collapse a level folds the deepest open ones."""
        rows = list(self.scale.tl.rows) if self.scale.tl else []
        if step > 0:
            self.open_ids.update(r.task for r in rows if r.kids)
        else:
            open_rows = [r for r in rows if r.kids and r.open]
            deepest = max((r.depth for r in open_rows), default=-1)
            self.open_ids.difference_update(r.task for r in open_rows if r.depth == deepest)
        self.folds_changed.emit(sorted(self.open_ids))
        if self.model is not None:
            self._redraw()

    def shift(self, direction: int) -> None:
        """Earlier, This week or Later: by four weeks, 13 over six months, or 26 over a year, and a typed range likewise, by
        no more than its own length. Its length stays, and a box's unfinished typing gives way."""
        if self.start is None:
            return
        self.start = (timeline.default_start(self.today) if direction == 0
                      else self.start + timedelta(days=direction * timeline.step_days(self.weeks, self.typed_days)))
        self._range_settled()
        if self.typed_days:
            self.settings_changed.emit(self.settings())
        if self.model is not None:
            self._redraw()

    def _pick(self, task_id: str | None) -> None:
        self.sel = task_id
        if self.model is not None:
            self.chart.sel = self.head.sel = task_id
            self.chart.update()
            self.head.update()
            self._card()
            top = self.chart.top_of(task_id) if task_id else None
            if top is not None:
                self.scroll.ensureVisible(0, top + self.chart.ROW_H // 2, 0, self.chart.ROW_H)
            if not LOOK.classic:
                self._draw_capacity()
        self.chart.setFocus()

    def _quick_from_card(self) -> None:
        if not self.sel:
            return
        top = self.chart.top_of(self.sel)
        row = next((r for r in self.chart.rows if r.task == self.sel), None)
        bar = self.chart.bar_rect(row, top) if row is not None and top is not None else None
        if bar is not None and not LOOK.classic:  # beside its bar when there's one to be beside
            self.quick_edit.emit(self.sel, QRect(self.chart.mapToGlobal(bar.topLeft().toPoint()), bar.size().toSize()))
            return
        r = self.card.rect()
        self.quick_edit.emit(self.sel, QRect(self.card.mapToGlobal(r.topLeft()), r.size()))

    def _redraw(self) -> None:
        """Draw the page again from the real model, as it is."""
        if self.real is not None or self.model is not None:
            self.render(self.real or self.model, self.today)

    def _chart_quick_edit(self, task_id: str, near: QRect) -> None:
        """A double-click asks for Quick edit, but not in a what-if, where it would change the real task (decision 292)."""
        if self.cur is not None:
            self.said.emit("Quick edit changes the task itself, so it isn't offered in a what-if. Drag its bar instead.")
            return
        self.quick_edit.emit(task_id, near)

    # ---- what-ifs (release 5.64, decisions 226 to 228 and 290) ----
    def showing(self) -> whatif.WhatIf | None:
        """The what-if showing, or None for the real plan."""
        return next((w for w in self.whatifs if w.id == self.cur), None)

    def show_whatif(self, wid: str | None) -> None:
        """Show a what-if, or the real plan for None."""
        self.whatif_box.hide()
        self.cur = wid if any(w.id == wid for w in self.whatifs) else None
        self.spot = None
        self._redraw()

    def _whatif_marks(self) -> None:
        """What the chart marks for the what-if showing: the tasks it takes off, where each bar it moves is on the real plan,
        and those it pushes past their deadlines."""
        c, pic, real = self.chart, self.pic, self.real
        c.whatif = pic is not None
        c.off = set(pic.off) if pic is not None else set()
        c.past = set(whatif.past_deadline(real, pic)) if pic is not None and real is not None else set()
        c.was = {}
        if pic is None or real is None:
            return
        far = self.today + timedelta(days=3650)
        for x in pic.touched - pic.off:
            if x in real.tasks and x in pic.model.tasks and not real.task(x).recurrence:
                before, after = windows(real.task(x), far)[:1], windows(pic.model.task(x), far)[:1]
                if before and before != after:
                    c.was[x] = before[0]

    def _sync_whatif(self) -> None:
        """The what-ifs' button is pressed while one is showing, and the strip, which names it, stays; the button's words never
        change, so the row of controls doesn't move. Plan isn't offered in one, where bars always drag."""
        w = self.showing()
        self.whatif_button.setChecked(w is not None)
        self.whatif_button.setToolTip(f"Showing {w.name}. The what-ifs, and the way back to the real plan" if w else
                                      "What-ifs: change the plan without changing any task, to see what it does to the load")
        self.plan_button.setVisible(w is None)
        self.whatif_strip.setVisible(w is not None)
        if w is None or self.real is None:
            return
        if not self.whatif_name.hasFocus():
            self.whatif_name.setText(w.name)
        n, past, stale = len(w.actions), len(self.chart.past), whatif.out_of_date(self.real, w)
        facts = [f"{n} change{'' if n == 1 else 's'}", f"{past} past {'its deadline' if past == 1 else 'their deadlines'}" if past else "",
                 f"{stale} out of date" if stale else ""]
        self.whatif_facts.setText(" · ".join(x for x in facts if x))
        self.whatif_undo.setEnabled(bool(self.wi_undo.get(w.id)))
        self.whatif_review.setEnabled(bool(w.actions))

    def _in_whatif(self, w: whatif.WhatIf, a: whatif.Action, said: str) -> None:
        """A thing done in a what-if: kept, with its step back, and the page drawn again. No task changes."""
        before = copy.deepcopy(w.actions)
        if not whatif.add(w, a):
            return
        self.wi_undo.setdefault(w.id, []).append(before)
        self.whatifs_changed.emit()
        self.said.emit(said)
        self._redraw()

    def take_off(self, task_id: str) -> None:
        """Take a task off, with everything open under it (decision 227): in the what-if showing, or a new one."""
        real = self.real
        if real is None or task_id not in real.tasks:
            return
        if not is_open(real.task(task_id)):
            self.said.emit("Only an open task can be taken off.")
            return
        w = self.showing()
        started = w is None
        if w is None:
            w = whatif.new(self.whatifs)
            self.cur, self.spot = w.id, None
        a = whatif.take_off(real, task_id)
        n = len(a.off) - 1
        words = real.task(task_id).title + (f" and {n} subtask{'' if n == 1 else 's'} under it" if n else "") + " taken off"
        self._in_whatif(w, a, f"{words}, in a new what-if, {w.name}. Your tasks haven't changed." if started
                        else f"{words}. Your tasks haven't changed. Ctrl+Z undoes it.")

    def put_back(self, task_id: str) -> None:
        """Put a task back in the what-if showing, with what was taken off with it."""
        w = self.showing()
        if w is None:
            return
        before = copy.deepcopy(w.actions)
        if whatif.put_back(w, task_id):
            self.wi_undo.setdefault(w.id, []).append(before)
            self.whatifs_changed.emit()
            title = self.real.task(task_id).title if self.real is not None and task_id in self.real.tasks else task_id
            self.said.emit(f"{title} is back, in this what-if.")
            self._redraw()

    def undo_whatif(self) -> None:
        """Ctrl+Z, or Undo, in a what-if: its last change taken back. Nothing on the real plan is touched."""
        w = self.showing()
        steps = self.wi_undo.get(w.id) if w is not None else None
        if w is None or not steps:
            self.said.emit("Nothing to undo in this what-if.")
            return
        w.actions = steps.pop()
        self.whatifs_changed.emit()
        self.said.emit("Undone, in this what-if only.")
        self._redraw()

    def _rename(self) -> None:
        w = self.showing()
        if w is None:
            return
        name = " ".join(self.whatif_name.text().split())
        if name and name != w.name:
            w.name = name
            self.whatifs_changed.emit()
            self._sync_whatif()
        else:
            self.whatif_name.setText(w.name)

    def _new_whatif(self, name: str) -> None:
        w = whatif.new(self.whatifs, name)
        self.whatifs_changed.emit()
        self.said.emit(f"{w.name}: drag bars, or take tasks off. Your tasks don't change until you apply it.")
        self.show_whatif(w.id)

    def _delete_whatif(self, wid: str) -> None:
        """Delete a what-if, asking first when it has changes in it. No task ever changed."""
        self.whatif_box.hide()
        w = next((x for x in self.whatifs if x.id == wid), None)
        if w is None:
            return
        n = len(w.actions)
        if n and not self.confirm(f"Delete {w.name}", f"Its {n} change{'' if n == 1 else 's'} go with it. Your tasks never changed."):
            return
        self.whatifs.remove(w)
        self.wi_undo.pop(wid, None)
        if self.cur == wid:
            self.cur = None
        self.whatifs_changed.emit()
        self.said.emit(f"{w.name} deleted. Your tasks never changed.")
        self._redraw()

    def _open_whatifs(self) -> None:
        """The list (decision 228): the real plan, each what-if with how many changes it has and how many are out of date, and a
        box to name a new one."""
        lay = self.whatif_list
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

        def row(n: int, words: str, wid: str | None, facts: str) -> None:
            b = QPushButton(words, objectName="subtle")
            b.setProperty("menu", True)
            b.setCheckable(True)
            b.setChecked(self.cur == wid)
            b.clicked.connect(lambda _=False, wid=wid: self.show_whatif(wid))
            lay.addWidget(b, n, 0)
            if facts:
                lay.addWidget(QLabel(facts, objectName="hint"), n, 1)

        row(0, "Real plan", None, "Your tasks as they are")
        for i, w in enumerate(self.whatifs, 1):
            n, stale = len(w.actions), whatif.out_of_date(self.real, w) if self.real is not None else 0
            row(i, w.name, w.id, f"{n} change{'' if n == 1 else 's'}" + (f", {stale} out of date" if stale else ""))
            x = QToolButton(objectName="checkFold")
            x.setText("×")
            x.setAccessibleName(f"Delete {w.name}")
            x.setToolTip(f"Delete {w.name}. Your tasks never changed.")
            x.clicked.connect(lambda _=False, wid=w.id: self._delete_whatif(wid))
            lay.addWidget(x, i, 2)
        name = QLineEdit()
        name.setPlaceholderText("Name a new what-if")
        name.setAccessibleName("Name a new what-if")
        new = QPushButton("New")
        new.clicked.connect(lambda: self._new_whatif(name.text()))
        name.returnPressed.connect(lambda: self._new_whatif(name.text()))
        k = len(self.whatifs) + 1
        lay.addWidget(name, k, 0, 1, 2)
        lay.addWidget(new, k, 2)
        self.whatif_new = name  # kept, so tests can reach it
        self.whatif_box.open_under(self.whatif_button)

    def review(self) -> None:
        """Review and apply (decision 226): each thing done, ticked, with what it would do; one whose task has changed since,
        or that can't be made, is left out. Apply sends the ticked ones to be made through the usual logged route."""
        w, pic, real = self.showing(), self.pic, self.real
        if w is None or pic is None or real is None or not w.actions:
            return
        from docrepo.stories import and_list
        from docrepo.ui.templates_view import PreviewDialog, PreviewEntry

        entries = []
        for line in whatif.lines(real, w, pic, self.today):
            key = str(line.index)
            if line.problem:
                entries.append(PreviewEntry(key, line.title, [f"Can't be made: {line.problem}"], ticked=False, enabled=False))
            elif line.stale:
                changed = f"{and_list(line.stale)} {'has' if len(line.stale) == 1 else 'have'} changed since, so this is left out."
                entries.append(PreviewEntry(key, line.title, [*line.says, changed], ticked=False, enabled=False))
            else:
                entries.append(PreviewEntry(key, line.title, line.says, off_lines=["Left as it is: this change isn't applied."]))
        dialog = PreviewDialog(self, f"Apply {w.name} to your tasks?",
                               "Each change goes into its task's status log, as Plan mode's do. The what-if goes once it's applied.",
                               entries, "", lambda ticked: f"Apply {len(ticked)} change{'' if len(ticked) == 1 else 's'}", back="Keep it as a what-if")
        self.review_dialog = dialog  # kept, so tests can reach it
        if not self.run_dialog(dialog):
            return
        ticked = set(dialog.ticked())
        if not ticked:
            self.said.emit("Nothing applied. It's still a what-if.")
            return
        self.apply_whatif.emit(w.id, [i for i in range(len(w.actions)) if str(i) not in ticked])

    # ---- Capacity's half ----
    def show_capacity(self) -> None:
        """Capacity's key and its other routes: this page, with Capacity showing (decision 229)."""
        if not self.cap_open:
            self.cap_open = True
            self.settings_changed.emit(self.settings())

    def _chosen_people(self) -> list:
        m = self.model
        assert m is not None
        people = m.active_people()
        return [p for p in people if p.id in self.people] if self.people else people

    def _render_capacity(self) -> None:
        """The hours in view, read again, and everything that says them."""
        tl = self.scale.tl
        if self.model is None or tl is None:
            return
        self.cap_box.setVisible(self.load_cells is not None)
        weeks = load.mondays(tl.start, tl.end)
        self.real_cells = self.load_cells(weeks) if self.load_cells else {}
        self.cells = whatif.cells(self.real_cells, self.pic, weeks) if self.pic is not None else self.real_cells
        self._draw_capacity()

    def _draw_capacity(self) -> None:
        """Everything that says the hours: the sentence, the team chart, the rows, the spotlight and the card."""
        m, tl = self.model, self.scale.tl
        if m is None or tl is None or LOOK.classic:
            return
        people = self._chosen_people()
        week_px = self.scale.width_of(self) / max(1.0, tl.days / 7)
        buckets = load.buckets(tl.start, tl.end, week_px)
        if self.spot is not None and not any(b.first == self.spot.first and b.end == self.spot.end for b in buckets):
            self.spot = None  # out of view, or a week that's now part of a month
        if self.spot is not None and self.spot.person and all(p.id != self.spot.person for p in people):
            self.spot = None
        weeks = [w for b in buckets for w in b.weeks]
        real = load.case(self.real_cells, people, weeks, self.today) if self.pic is not None else None  # a what-if says both
        lead, who = load.sentence(load.case(self.cells, people, weeks, self.today), m.person_name, self.today, real)
        self.cap_say.setText(f"<b>{esc(lead)}</b> {esc(who)}" if people else "")
        self.cap_fold.setIcon(icon("chevron-down" if self.cap_open else "chevron-right"))
        self.cap_fold.setToolTip("Fold Capacity" if self.cap_open else "Open Capacity")
        chosen = {self.sel, *m.descendants_of(self.sel)} if self.sel and self.sel in m.tasks and self.spot is None else set()
        data = StripData(m, self.today, self.cells, people, buckets, self.cap_unit, self.cap_by_group, load.adds_to(self.cells, chosen), self.spot,
                         self.chart.hover_week, self.real_cells if self.pic is not None else None)
        self.cap_team.set_data(data)
        self.cap_rows.set_data(data)
        for w in (self.cap_team, self.cap_scroll):
            w.setVisible(self.cap_open and bool(people))
        self.cap_empty.setVisible(self.cap_open and not people)
        self._draw_not_counted(people)
        if self.spot is None:
            self.chart.strong, self.chart.spot = None, None
        else:
            who_ids = [self.spot.person] if self.spot.person else [p.id for p in people]
            behind = load.cell_tasks(self.cells, who_ids, [w for b in buckets if b.first == self.spot.first for w in b.weeks])
            self.chart.strong = {x for task, _ in behind if task in m.tasks for chain in m.chains_of(task) for x in chain}
            self.chart.spot = (self.spot.first, self.spot.end)
            self._draw_card(behind, people, next(b for b in buckets if b.first == self.spot.first))
        self.cap_card.setVisible(self.spot is not None)
        self.chart.update()

    def _draw_not_counted(self, people: list) -> None:
        """What Capacity can't count: people but no hours, or hours but no dates. It's said, as it makes the load look lighter."""
        m = self.model
        assert m is not None
        hours, dates = self.load_unplaced(self.pic.model if self.pic is not None else m, self.today) if self.load_unplaced else ([], [])
        ids = {p.id for p in people}

        def mine(found: list[str]) -> list[str]:
            return [x for x in found if not self.people or ids & {*m.task(x).leads, *m.task(x).assignees}]

        self.not_counted_ids = {"hours": mine(hours), "dates": mine(dates)}
        parts = []
        for key, words in (("hours", "with people but no hours"), ("dates", "with hours but no dates")):
            n = len(self.not_counted_ids[key])
            if n:
                parts.append(f'<a href="nc:{key}">{n} {"task" if n == 1 else "tasks"} {words}</a>')
        self.cap_note.setVisible(self.cap_open and bool(parts))
        self.cap_note.setText("Not counted, so the load could be higher: " + ", ".join(parts))
        shown = self.not_counted_ids.get(self.not_counted, [])
        self.cap_list_box.setVisible(self.cap_open and bool(shown))
        self.cap_list.setText(", ".join(f'<a href="task:{esc(x)}">{esc(m.task(x).title)}</a>' for x in shown))
        if shown:
            self.cap_list_box.setFixedHeight(min(UNDATED_MAX_HEIGHT, self.cap_list.heightForWidth(self.scale.room or self.width())))

    def _note_link(self, href: str) -> None:
        key = href.partition(":")[2]
        self.not_counted = "" if self.not_counted == key else key
        self._draw_capacity()
        self._fit_split()

    def _natural_height(self) -> int:
        """Capacity's half with all its rows showing."""
        room = self.scale.room or self.width()
        return (self._head_height() + (self.cap_team.height() if self.cap_team.isVisibleTo(self) else 0)
                + (self.cap_rows.natural_height() if self.cap_scroll.isVisibleTo(self) else 0)
                + (self.cap_empty.sizeHint().height() if self.cap_empty.isVisibleTo(self) else 0)
                + (self.cap_note.heightForWidth(room) if self.cap_note.isVisibleTo(self) else 0)
                + (self.cap_list_box.height() if self.cap_list_box.isVisibleTo(self) else 0) + 2)

    def _head_height(self) -> int:
        """Capacity's head at this width: its sentence wraps."""
        return self.cap_head.layout().totalHeightForWidth(self.scale.room or self.width())

    def _fit_split(self) -> None:
        """Its height: folded, only its head; dragged, as it was left; otherwise all its rows, up to its share of the page."""
        total = sum(self.split.sizes())
        if total <= 0 or self.load_cells is None:
            return
        if not self.cap_open:
            want = self._head_height() + 2
            self.cap_box.setMinimumHeight(want)
            self.cap_box.setMaximumHeight(want)
            self.split.handle(1).setEnabled(False)
        else:
            self.cap_box.setMinimumHeight(self.CAP_MIN)
            self.cap_box.setMaximumHeight(16777215)
            self.split.handle(1).setEnabled(True)
            want = self.cap_h if self.cap_h is not None else min(self._natural_height(), int(total * self.CAP_SHARE))
        want = max(self.cap_box.minimumHeight(), min(want, total - self.TOP_MIN))
        if self.split.sizes()[1] != want:
            self.split.blockSignals(True)
            self.split.setSizes([total - want, want])
            self.split.blockSignals(False)

    def _split_moved(self, *_) -> None:
        """The divider was dragged: its place is kept."""
        self.cap_h = self.split.sizes()[1]
        self.settings_changed.emit(self.settings())
        self._place_card()

    def _week_hovered(self, week) -> None:
        """A week under the mouse in Capacity shows through the chart and the other half, with nothing drawn again."""
        if week == self.chart.hover_week:
            return
        self.chart.hover_week = week
        self.chart.update()
        for strip in (self.cap_team, self.cap_rows):
            strip.data.hover = week
            strip.update()

    def _cell_picked(self, person: str, first: date, end: date) -> None:
        """The spotlight on a week (decision 233), or off it, for a second click on the same one."""
        spot = Spot(person, first, end)
        self.spot = None if self.spot == spot else spot
        if self.spot is not None and self.sel:
            self.sel = self.chart.sel = self.head.sel = None
            self._card()
            self.head.update()
        self._draw_capacity()

    def clear_spot(self) -> None:
        self.spot = None
        self._draw_capacity()

    def _solo(self, person: str) -> None:
        """A name in Capacity: only them, bars and load, or back to everyone (decision 232)."""
        self._set("people", [] if self.people == [person] else [person])

    def _draw_card(self, behind: list[tuple[str, float]], people: list, bucket: load.Bucket) -> None:
        """The spotlight's card: whose week it is, how full, and the tasks behind it, biggest first."""
        m, spot = self.model, self.spot
        assert m is not None and spot is not None
        old = self.cap_card.layout()
        if old is not None:
            while old.count():
                item = old.takeAt(0)
                if item.widget() is not None:
                    item.widget().hide()
                    item.widget().deleteLater()
            grid = old
        else:
            grid = QGridLayout(self.cap_card)
            grid.setContentsMargins(12, 8, 8, 10)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(4)
        who = next((p for p in people if p.id == spot.person), None)
        weeks = len(bucket.weeks)
        cap = ((who.hours or 0) if who else load.capacity_of(people)) * weeks
        total = sum(h for _, h in behind)
        when = load.when(bucket, self.today)
        title = QLabel(f"{who.name if who else 'Team'}, {when}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setFont(tokens.ui_font(semibold=True))
        grid.addWidget(title, 0, 0)
        says = QLabel(f"{round(total, 1):g} h" + (f" of {round(cap, 1):g} h, {round(total / cap * 100)}%" if cap else ""), objectName="hint")
        grid.addWidget(says, 0, 1)
        close = QToolButton(objectName="checkFold")
        close.setText("×")
        close.setAccessibleName("Close")
        close.setToolTip("Close (Esc)")
        close.clicked.connect(lambda: self.clear_spot())
        grid.addWidget(close, 0, 2, Qt.AlignmentFlag.AlignRight)
        off = self.chart.off
        for i, (task, hours) in enumerate(behind[:7], 1):
            chain = m.chains_of(task)[0][:-1] if task in m.tasks else []
            path = esc(" › ".join(m.task(x).title for x in chain))
            if len(chain) >= 2 and chain[-1] not in off:  # its trial, say, under the project: take the whole of it off (the mock's)
                parent = m.task(chain[-1]).title
                path += f' · <a href="off:{esc(chain[-1])}">Take off {esc(parent if len(parent) <= 28 else parent[:27] + "…")}</a>'
            words = m.task(task).title if task in m.tasks else task
            line = QLabel(f'<a href="task:{esc(task)}">{esc(words)}</a>' + (f'<br><span style="color:{MUTED}; font-size:{tokens.CAPTION}pt">{path}</span>' if path else ""))
            line.setTextFormat(Qt.TextFormat.RichText)
            line.linkActivated.connect(self._card_link)
            grid.addWidget(line, i, 0, 1, 1)
            amount = QLabel(f"{round(hours, 1):g} h")
            amount.setFont(tokens.numeric_font())
            grid.addWidget(amount, i, 1, Qt.AlignmentFlag.AlignRight)
            if task in m.tasks and (task in off or is_open(m.task(task))):  # decision 233: the card can take a task off
                act = QLabel(f'<a href="back:{esc(task)}">Put back</a>' if task in off else f'<a href="off:{esc(task)}">Take off</a>')
                act.setTextFormat(Qt.TextFormat.RichText)
                act.setToolTip("Put it back in this what-if" if task in off else "See the load without it and everything under it, in a what-if. Your tasks don't change.")
                act.linkActivated.connect(self._card_link)
                grid.addWidget(act, i, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        if not behind:
            grid.addWidget(QLabel("Nothing scheduled.", objectName="hint"), 1, 0, 1, 3)
        if len(behind) > 7:
            grid.addWidget(QLabel(f"and {len(behind) - 7} more, under {round(behind[7][1] + 0.05, 1):g} h each", objectName="hint"), 8, 0, 1, 3)
        grid.setColumnStretch(0, 1)
        self.cap_card.setFixedWidth(min(420, max(240, self.width() - 16)))
        self.cap_card.adjustSize()
        self.cap_card.raise_()
        self._place_card()

    def _place_card(self) -> None:
        """Over the page, above its cell, or under it when there's no room above, so nothing moves."""
        spot = self.spot
        if LOOK.classic or spot is None:
            return
        b = next((x for x in self.cap_rows.data.buckets if x.first == spot.first), None)
        if b is None:
            return
        if spot.person:
            line = self.cap_rows.line_of(spot.person)
            if line is None:
                return
            r = self.cap_rows.cell_rect(line, b).toRect()
            at = QRect(self.cap_rows.mapTo(self, r.topLeft()), r.size())
        else:
            r = self.cap_team.column_rect(b).toRect()
            at = QRect(self.cap_team.mapTo(self, r.topLeft()), r.size())
        w, h = self.cap_card.width(), self.cap_card.sizeHint().height()
        x = max(8, min(self.width() - w - 8, at.center().x() - w // 2))
        y = at.top() - h - 8
        if y < 8:
            y = min(self.height() - h - 8, at.bottom() + 8)
        self.cap_card.setGeometry(x, y, w, h)

    def _card_link(self, href: str) -> None:
        kind, _, task_id = href.partition(":")
        {"off": self.take_off, "back": self.put_back}.get(kind, self._card_task)(task_id)

    def _card_task(self, task_id: str) -> None:
        """A task on the spotlight's card: selected on the chart, with its parents opened so its row is there."""
        m = self.model
        if m is None or task_id not in m.tasks:
            return
        folded = [x for chain in m.chains_of(task_id)[:1] for x in chain[:-1] if x not in self.open_ids]
        if folded:
            self.open_ids.update(folded)
            self.folds_changed.emit(sorted(self.open_ids))
            self._redraw()
        self._pick(task_id)

    def _dropped(self, task_id: str, start: date, end: date, mode: str) -> None:
        """A Plan mode drop: the new dates, kept for Ctrl+Z, and sent to be saved and logged."""
        m = self.model
        if m is None:
            return
        t = m.task(task_id)
        # Stretching one end leaves the other as it was; moving a bar that ends at its deadline gives it a Due.
        new_start = t.start if mode == "end" else start.isoformat()
        new_due = t.due if mode == "start" else end.isoformat()
        said = {"new": f"Start and Due set: {long_date(start, self.today)} to {long_date(end, self.today)}",
                "start": f"Start moved to {long_date(start, self.today)}", "end": f"Due moved to {long_date(end, self.today)}",
                "move": f"now {long_date(start, self.today)} to {long_date(end, self.today)}"}[mode]
        w = self.showing()
        if w is not None and self.real is not None:  # a what-if keeps it, and no task changes
            self._in_whatif(w, whatif.move(self.real, task_id, new_start, new_due), f"{t.title}: {said}, in this what-if. Your tasks haven't changed.")
            return
        self.undo.append(("task", task_id, t.start, t.due))
        self.set_dates.emit(task_id, new_start, new_due, f"{t.title}: {said}. Ctrl+Z undoes it.")

    def _dropped_parent(self, task_id: str, weeks: int) -> None:
        """In a what-if, a whole parent's drop: it and what's under it moved in whole weeks, from where the what-if has them."""
        w, real = self.showing(), self.real
        if w is None or real is None or self.model is None or not weeks or task_id not in real.tasks:
            return
        a = whatif.move_parent(self.pic.model if self.pic is not None else real, task_id, weeks, real)
        if not a.dates and not a.keys:
            self.said.emit(f"Nothing under {real.task(task_id).title} has dates to move.")
            return
        words = f"{abs(weeks)} week{'' if abs(weeks) == 1 else 's'} {'later' if weeks > 0 else 'earlier'}"
        self._in_whatif(w, a, f"{real.task(task_id).title} and everything under it {words}, in this what-if. Deadlines and routine "
                              "subtasks stay put. Your tasks haven't changed.")

    def _dropped_key(self, task_id: str, key_id: int, first: date, last: date, kind: str) -> None:
        """A key date's drop in Plan mode (decision 152): its new dates, by its kind (a start alone stays one), kept for
        Ctrl+Z and sent to be saved and logged."""
        m = self.model
        kd = next((k for k in m.key_dates_of(task_id) if k.id == key_id), None) if m is not None else None
        if m is None or kd is None:
            return
        start = None if kind == "by" else first.isoformat()
        end = None if kind == "from" else last.isoformat()
        moved = KeyDate(kd.id, task_id, start, end, kd.description)
        w = self.showing()
        if w is not None and self.real is not None:
            self._in_whatif(w, whatif.move_key(self.real, task_id, key_id, start, end),
                            f"{m.task(task_id).title}: {kd.description or 'its key date'} now {key_dates.when_text(moved, self.today)}, in this "
                            "what-if. Your tasks haven't changed.")
            return
        self.undo.append(("key", task_id, key_id, kd.start, kd.end))
        self.set_key_date.emit(task_id, key_id, start, end,
                               f"{m.task(task_id).title}: {kd.description or 'its key date'} now {key_dates.when_text(moved, self.today)}. "
                               "Ctrl+Z undoes it.")

    def undo_last(self) -> None:
        """Ctrl+Z: the last drop's dates put back, a bar's or a key date's, logged too."""
        if not self.undo or self.model is None:
            return
        step = self.undo.pop()
        if step[0] == "key":
            _, task_id, key_id, start, end = step
            if task_id in self.model.tasks and any(k.id == key_id for k in self.model.key_dates_of(task_id)):
                self.set_key_date.emit(task_id, key_id, start, end, f"{self.model.task(task_id).title}: its key date is back as it was.")
            return
        _, task_id, start, due = step
        if task_id not in self.model.tasks:
            return
        self.set_dates.emit(task_id, start, due, f"{self.model.task(task_id).title}: its dates are back as they were.")

    @staticmethod
    def _card_key_dates(m: Model, t: Task, today: date) -> str:
        """The card's line of key dates (release 5.31): each with its marks, done ones grey."""
        kds = m.key_dates_of(t.id)
        if not kds:
            return ""
        items = [f"<span style='color:{FAINT if kd.done else FG}'>{esc(timeline.key_date_text(kd, today))}</span>" for kd in kds]
        return f"<br><span style='color:{MUTED}'>Key dates:</span> " + " &nbsp;·&nbsp; ".join(items)

    def _foot(self, t: Task | None) -> None:
        """The line under the chart for the row clicked last: its title, state, dates, hours and people, with the rest in its
        tooltip. It's always there, so picking a bar moves nothing (decision 292)."""
        m, today = self.model, self.today
        if t is None or m is None:
            self.card_text.set_line("", "Click a bar for its details, or a week in Capacity for what fills it." if LOOK.show_help else "")
            return
        row = next((r for r in self.chart.rows if r.task == t.id), None)
        if timeline.is_undated(t, today) and row is not None and row.span:
            dates = f"Its subtasks: {short(row.span[0], today)} to {short(row.span[1], today)}"
        elif timeline.is_undated(t, today):
            dates = "No dates of its own" if m.key_dates_of(t.id) else "No dates yet"
        elif t.recurrence:
            due = due_of(t, today)
            dates = t.recurrence + (f", next {short(due.date, today)}" if due else "")
        else:
            end = to_date(t.due or t.deadline) if (t.due or t.deadline) else None
            dates = f"{short(start_of(t), today)} to {short(end, today) if end else 'no end date'}"
        if t.deadline and (t.due or t.recurrence):
            dates += f" · Deadline {short(to_date(t.deadline), today)}"

        def people(ids: list[str]) -> str:
            return ", ".join(m.person_name(p) for p in ids) or "None"

        parts = [t.state, dates, timeline.hours_words(m, t, today)]
        if t.leads:
            parts.append(f"Lead: {people(t.leads)}")
        if t.assignees:
            parts.append(f"Assignees: {people(t.assignees)}")
        if t.plant_event:
            parts.append("Plant event")
        kds = m.key_dates_of(t.id)
        if kds:
            parts.append("Key dates: " + ", ".join(timeline.key_date_text(kd, today) for kd in kds))
        path = " › ".join(m.task(x).title for x in m.chains_of(t.id)[0][:-1]) or "Top-level task"
        self.card_text.set_line(t.title, " · ".join(parts), f"{t.title}\n{path}\n" + "\n".join(parts))

    def _card(self) -> None:
        """The card for the row clicked last: its title, state, path, dates, hours and people, with Open task, Quick edit and
        Update."""
        m, today = self.model, self.today
        t = m.tasks.get(self.sel) if m and self.sel else None
        self.open_button.setVisible(t is not None)
        for b in (self.quick_button, self.update_button):
            b.setVisible(t is not None and self.cur is None)  # in a what-if they'd change the real task
        if not LOOK.classic:
            off = t is not None and t.id in self.chart.off
            self.off_button.setVisible(t is not None and (off or is_open(t)))
            self.off_button.setText("Put back" if off else "Take off")
            self._foot(t)
            return
        self.card.setVisible(t is not None or LOOK.show_help)  # no card, and no sentence about it, until a row is picked
        if t is None or m is None:
            self.card_text.setMinimumHeight(0)
            self.card.setMinimumHeight(0)
            self.card_text.setText(f'<span style="color:{MUTED}">Click a row to see its dates, hours and people here. Double-click a bar '
                                   "or a name for Quick edit.</span>")
            return
        due = due_of(t, today)
        if timeline.is_undated(t, today):  # none of its own: its key dates (release 5.31) are on the line below, if any
            dates = f'<span style="color:{MUTED}">{"No dates of its own" if m.key_dates_of(t.id) else "No dates yet"}</span>'
        elif t.recurrence:
            dates = f"{esc(t.recurrence)} from {esc(long_date(start_of(t), today))}" + (f", next {esc(long_date(due.date, today))}" if due else "")
        else:
            end = (f"Due {long_date(to_date(t.due), today)}" if t.due else f"Deadline {long_date(to_date(t.deadline), today)}" if t.deadline
                   else "no end date")
            dates = esc(f"{long_date(start_of(t), today)} → {end}") + (
                f' <span style="color:{MUTED}">{esc(days_text(due.date, today))}</span>' if due else "")
        if t.deadline and (t.due or t.recurrence):
            dates += esc(f" · Deadline {long_date(to_date(t.deadline), today)}" + (f", {t.deadline_desc}" if t.deadline_desc else ""))

        def people(ids: list[str]) -> str:
            return ", ".join(esc(m.person_name(p)) for p in ids) or "None"

        path = " › ".join(m.task(x).title for x in m.chains_of(t.id)[0][:-1]) or "Top-level task"
        chips = "".join(" " + _chip(text, cls) for text, cls in markers(m, t))
        if t.plant_event:
            chips += " " + _chip(f"{FLAG} Plant event", "event")
        state = _chip(t.state, "st-ip" if t.state == "In progress" else "st-ns")
        self.card_text.setText(f"<b>{esc(t.title)}</b> {state}{chips}<br><span style='color:{MUTED}'>{esc(path)}</span><br>{dates}"
                               f"<br><span style='color:{MUTED}'>{esc(timeline.hours_words(m, t, today))} · Lead: {people(t.leads)} · "
                               f"Assignees: {people(t.assignees)}</span>" + self._card_key_dates(m, t, today))
        # A wrapped label's height isn't its layout's to squeeze: the card keeps room for every line.
        self.card_text.setMinimumHeight(self.card_text.heightForWidth(max(320, self.card_text.width())))
        self.card.setMinimumHeight(self.card_text.minimumHeight() + 14)
