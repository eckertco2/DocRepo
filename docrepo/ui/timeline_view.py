"""The browse tool's Timeline view (mods log round 1, M0019; round 4, M0067, releases 5.29 and 5.30): one chart of open
tasks over the coming weeks.

The rows come from ``docrepo/timeline.py``; this module paints them and handles the mouse and keys. Each top-level task is
a row that folds (its arrow, Right and Left, or Collapse a level and Expand a level), with a summary bar over its
subtasks. The scale and the plant events lane (``TimelineHead``) stay at the top while the rows scroll. Clicking a row
shows its dates, hours and people in a card above the chart; double-clicking a bar or a name asks for Quick edit
(``quick_edit``); Enter or the card's Open task opens the task. Plan mode (P) lets a one-time task's bar be moved, or its
ends stretched, and an undated task's name be dragged onto the chart for a working week; each drop is sent as
``set_dates`` for the browse window to save and log, and Ctrl+Z sends the step back. It takes the middle and right panes
together, as Capacity does.

Key dates (release 5.31, the key dates plan) are marks on their task's row: a window a thin segment under the bar (or in
the bar's place when the task has none in view), a start alone an opening bracket, an end alone a closing tick, a Deadline
end a red diamond, a plant activity amber, a done one grey. In Plan mode a key date that isn't done drags too (decision
152): a window moves or its ends stretch, a start or an end alone moves. Each drop is sent as ``set_key_date``, and Ctrl+Z
sends it back, in the same order as the bars' drops.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from docrepo import key_dates, timeline
from docrepo.dates import days_text, long_date, short, to_date
from docrepo.detail import esc
from docrepo.model import KeyDate, Model, Task
from docrepo.schedule import due_of, start_of
from docrepo.timeline import Band, KeyMark, Row, Timeline
from docrepo.ui.look import LOOK, Help
from docrepo.ui.tree_view import GROUP_COLOURS
from docrepo.ui.widgets import CheckMenuButton, FlowLayout, label_filter, people_filter
from docrepo.views import markers

FG, MUTED, FAINT, LINE, LINE_STRONG = "#1a1f25", "#5a6571", "#87919c", "#d6dce3", "#b8c1cb"
ACCENT, BAD, SEL, SURFACE_2, HOVER = "#1d5e98", "#b0261e", "#dbe8f5", "#f4f6f8", "#eef1f4"
#: Plant events (release 5.29): their bars, lane and band.
EV_BG, EV_LINE, EV_INK = "#f7e3b5", "#b07a12", "#6e4700"
#: Order by's keys colour the titles, in this order; a ninth key and on are grey.
KEY_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
#: Hours a week, light to dark (``timeline.HOUR_BINS``), and the text on each.
HOUR_COLOURS = ("#86b6ef", "#5598e7", "#256abf", "#184f95", "#0d366b")
HOUR_INK = ("#0b1b2e", "#0b1b2e", "#ffffff", "#ffffff", "#ffffff")
#: The Priorities board's buckets.
PRIORITY_COLOURS = {"critical": "#b0261e", "high": "#d9622b", "medium": "#1d5e98", "parking": "#87919c"}
#: The pages' chip colours, inline: a QLabel doesn't have the pages' stylesheet.
CHIP_STYLE = {"st-ns": ("#5a6571", "#eef1f4"), "st-ip": ("#1d5e98", "#dbe8f5"), "urgent": ("#b0261e", "#fbe3e1"),
              "routine": ("#1a1f25", "#e9edf1"), "multi": ("#1d5e98", "#e4eefa"), "pri-critical": ("#ffffff", "#c42b1c"),
              "event": (EV_INK, EV_BG)}
FLAG = "⚑"


def _chip(text: str, cls: str) -> str:
    fg, bg = CHIP_STYLE.get(cls, CHIP_STYLE["st-ns"])
    return f'<span style="color:{fg}; background-color:{bg}">&nbsp;{esc(text)}&nbsp;</span>'


def _mix(colour: str, strength: float, into: str = "#ffffff") -> QColor:
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
    """A drag in Plan mode: "new" (a name onto the chart), "move", "start" or "end", or a key date's "kd-move", "kd-start"
    or "kd-end" (release 5.31), and where it's got to."""

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

    def set_order(self, order: str) -> None:
        self.key_w = 0 if order == "top" else KEY_W
        self.NAME_W = NAME_W + self.key_w

    def width_of(self, widget: QWidget) -> float:
        return max(1.0, widget.width() - self.NAME_W - 10 - self.inset)

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
        self.setFixedHeight(self.SCALE_H + 8 + self.lanes * self.LANE_H)
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
        self.lanes = max(1, len(lane_end))
        right = self.width() - 10 - self.scale.inset
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
        p.fillRect(self.rect(), QColor("#ffffff"))
        right = self.width() - 10 - self.scale.inset
        bold, small = QFont(self.font()), QFont(self.font())
        bold.setBold(True)
        small.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))
        long = tl.weeks > 26
        # The months, then the weeks (or the years, over 12 months), and Today.
        p.setFont(bold)
        p.setPen(QColor(FG))
        for d in tl.months():
            name = d.strftime("%b") if long else f"{d.strftime('%B')} {d.year}"
            p.drawText(QPointF(self.scale.x(self, d) + 3, 15), name)
        p.setFont(small)
        if long:
            for d in [tl.start, *(m for m in tl.months() if m.month == 1 and m != tl.start)]:
                p.setPen(QColor(MUTED))
                p.drawText(QPointF(self.scale.x(self, d) + 3, 33), str(d.year))
        for i, w in enumerate(tl.week_starts()):
            x = self.scale.x(self, w)
            p.setPen(QColor(LINE_STRONG))
            p.drawLine(QPointF(x, 20), QPointF(x, self.SCALE_H))
            if not long and (i % 2 == 0 or right - self.scale.NAME_W > 760):
                p.setPen(QColor(MUTED))
                p.drawText(QPointF(x + 3, 33), short(w, self.today))
        if tl.start <= self.today < tl.end:  # the today line, named in the axis
            x = (self.scale.x(self, self.today) + self.scale.x(self, self.today + timedelta(days=1))) / 2
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawLine(QPointF(x, 18), QPointF(x, self.SCALE_H))
            tag = QFont(small)
            tag.setWeight(QFont.Weight.DemiBold)
            p.setFont(tag)
            w = p.fontMetrics().horizontalAdvance("Today") + 8
            pill = QRectF(x + 3, 22, w, 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(pill, 3, 3)
            p.setPen(QColor("#ffffff"))
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
        lane_top = self.SCALE_H + 2
        p.fillRect(QRectF(0, lane_top, right, self.height() - lane_top - 1), QColor(SURFACE_2))
        p.setFont(bold)
        p.setPen(QColor(EV_LINE))
        p.drawText(QRectF(8, lane_top, self.scale.NAME_W - 10, self.LANE_H + 2), Qt.AlignmentFlag.AlignVCenter, f"{FLAG} Plant events")
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

    # ---- painting ----
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        if self.tl is None or self.model is None:
            return
        tl = self.tl
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        right = self.width() - 10 - self.scale.inset
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
                    p.fillRect(QRectF(self._x(d), 0, self._x(d + timedelta(days=1)) - self._x(d), bottom), QColor(26, 31, 37, 10))
        for i, r in enumerate(self.rows):
            top = i * self.ROW_H
            if r.task == self.sel:
                p.fillRect(QRectF(left, top, right - left, self.ROW_H), QColor(SEL))
            elif i == self.hover:
                p.fillRect(QRectF(left, top, right - left, self.ROW_H), QColor(20, 32, 44, 12))
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
            p.fillRect(QRectF(x0, 0, max(2.0, x1 - x0), bottom), QColor(176, 122, 18, 26))
            p.setPen(QPen(QColor(176, 122, 18, 150), 1))
            p.drawLine(QPointF(x0, 0), QPointF(x0, bottom))
            p.drawLine(QPointF(x1, 0), QPointF(x1, bottom))
        for i, r in enumerate(self.rows):
            self._paint_row(p, i * self.ROW_H, r, base, bold, small)
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
            p.setBrush(_mix(colour, 0.13) if key is not None else QColor(SURFACE_2))
            p.drawRoundedRect(rect, 4, 4)
            p.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), QColor(colour))
            p.setPen(_mix(colour, 0.75, FG) if key is not None else QColor(MUTED))
            text = p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(rect.width() - 14))
            p.drawText(QRectF(rect.left() + 9, rect.top(), rect.width() - 12, self.ROW_H - 4), Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_row(self, p: QPainter, top: int, r: Row, base: QFont, bold: QFont, small: QFont) -> None:
        assert self.model is not None and self.tl is not None
        t = self.model.task(r.task)
        right = self.width() - 10 - self.scale.inset
        p.setPen(QPen(QColor(LINE), 1))
        p.drawLine(QPointF(0, top + self.ROW_H - 0.5), QPointF(right, top + self.ROW_H - 0.5))
        # Ordered by top-level task, its project's colour is an edge, as in the task tree; by a field, the lane column's band
        # names the key, so the title stays plain (one colour cue, with its words beside it).
        kc = key_colour(r, self.order) if not self.scale.key_w else None
        if kc:
            p.fillRect(QRectF(0, top, 3, self.ROW_H), QColor(kc))
        x = self._indent(r)
        if r.kids:  # the fold arrow: right while folded, down while open
            cx, cy, s = x + 9, top + self.ROW_H / 2, 4.0
            path = QPainterPath()
            if r.open:
                path.moveTo(cx - s, cy - s / 2)
                path.lineTo(cx + s, cy - s / 2)
                path.lineTo(cx, cy + s * 0.75)
            else:
                path.moveTo(cx - s / 2, cy - s)
                path.lineTo(cx + s * 0.75, cy)
                path.lineTo(cx - s / 2, cy + s)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(FG))
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
        late_w = 30 if r.late else 0
        badge_w = (p.fontMetrics().horizontalAdvance(badge) + 12) if badge else 0
        p.setFont(bold if not r.depth else base)
        colour = QColor(MUTED) if r.ctx else (_mix(kc, 0.6, FG) if kc else QColor(FG))
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
        if r.late:
            p.setFont(small)
            p.setPen(QColor(BAD))
            p.drawText(QRectF(self.scale.NAME_W - 32, top, 30, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, "late")
        self._paint_track(p, top, r, t, bold, small)

    def _bar_look(self, t: Task, r: Row) -> tuple[QColor | None, QColor | None, QColor, bool, bool, bool]:
        """(fill, edge, text colour, hatched, dashed outline, event stripe) for a one-time task's bar (decision 133)."""
        if t.plant_event:
            return QColor(EV_BG), _mix(EV_LINE, 0.55, EV_BG), QColor(EV_INK), False, False, True
        if self.bars == "hours":
            b = timeline.hour_bin(t, self.today)
            if b < 0:
                return None, QColor(FAINT), QColor(MUTED), False, True, False
            return QColor(HOUR_COLOURS[b]), None, QColor(HOUR_INK[b]), r.not_started, False, False
        if self.bars == "priority":
            if not t.priority or t.priority not in PRIORITY_COLOURS:
                return None, QColor(FAINT), QColor(MUTED), False, True, False
            colour = PRIORITY_COLOURS[t.priority]
        else:
            colour = GROUP_COLOURS[r.colour % len(GROUP_COLOURS)]
        if r.not_started:
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
        return GROUP_COLOURS[r.colour % len(GROUP_COLOURS)]

    def _paint_track(self, p: QPainter, top: int, r: Row, t: Task, bold: QFont, small: QFont) -> None:
        fill, edge, ink, hatched, dashed, stripe = self._bar_look(t, r)
        dot = self._dot_colour(t, r)
        label = timeline.hours_label(t, self.today, self.a_week)
        bar_font = QFont(small)
        bar_font.setWeight(QFont.Weight.DemiBold)
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
                p.setOpacity(0.35)
            p.setPen(QPen(edge, 1, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine) if edge is not None else Qt.PenStyle.NoPen)
            p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 4, 4)
            if hatched:  # Not started, whatever the colour
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(255, 255, 255, 130) if edge is None else _mix(edge.name(), 0.55), Qt.BrushStyle.BDiagPattern))
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
            elif label and rect.right() + 50 < self.width() - 10 - self.scale.inset:
                # Too narrow for its hours: they go just after the bar, never cut off (the playbook's timeline labels).
                p.setFont(small)
                p.setPen(QColor(MUTED))
                p.drawText(QRectF(rect.right() + 4, rect.top() - 2, 80, rect.height() + 4), Qt.AlignmentFlag.AlignVCenter, label)
            if self.plan and not r.routine and rect.width() > 14:  # the ends that stretch
                p.fillRect(QRectF(rect.left(), rect.top() + 4, 2, rect.height() - 8), QColor(0, 0, 0, 60))
                p.fillRect(QRectF(rect.right() - 2, rect.top() + 4, 2, rect.height() - 8), QColor(0, 0, 0, 60))
            p.setOpacity(1.0)
        if r.deadline:
            self._diamond(p, self._mid(r.deadline), top + 14.0, 6.0, QColor(BAD if r.deadline < self.today else FG), QColor("#ffffff"))
        if r.span:  # the summary bar: its subtasks' span, with their deadlines (item 51)
            only = not r.own or not r.windows
            a, b = r.span
            x0, x1 = self._x(max(a, self.tl.start)), self._x(min(b, self.tl.end - timedelta(days=1)) + timedelta(days=1))
            y, h, tick = (top + 12.0, 4.0, 12.0) if only else (top + 23.0, 3.0, 7.0)
            p.fillRect(QRectF(x0, y, max(2.0, x1 - x0), h), QColor(MUTED))
            if a >= self.tl.start:
                p.fillRect(QRectF(x0, y + h - tick, 2, tick), QColor(MUTED))
            if b < self.tl.end:
                p.fillRect(QRectF(x1 - 2, y + h - tick, 2, tick), QColor(MUTED))
            for d in r.sub_deadlines:
                self._diamond(p, self._mid(d), y + h / 2, 4.0, QColor("#ffffff"), QColor(BAD if d < self.today else FG))
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
        return GROUP_COLOURS[r.colour % len(GROUP_COLOURS)]

    def _paint_key(self, p: QPainter, top: float, r: Row, t: Task, k: KeyMark) -> None:
        """One key date's mark: a window a thin segment, a start alone an opening bracket, an end alone a closing tick, and a
        Deadline end a red diamond; faint while it's being dragged."""
        assert self.tl is not None
        cy, h = self._key_strip(r, top)
        colour = QColor(self._key_colour(t, r, k))
        dragging = self.drag is not None and self.drag.moved and self.drag.key_id == k.id
        if dragging:
            p.setOpacity(0.35)
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
            self._diamond(p, self._mid(k.last), cy, 5.0, QColor(LINE_STRONG if k.done else BAD), QColor("#ffffff"))
        p.setOpacity(1.0)

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
        "kd-end" or "kd-move" (Plan mode, release 5.31; the key date is ``hit_key``), "row" or ""."""
        self.hit_key = None
        r = self.row_at(y)
        if r is None:
            return None, ""
        top = int(y // self.ROW_H) * self.ROW_H
        if r.kids and self._fold_rect(r, top).contains(QPointF(x, y)):
            return r, "fold"
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
            if d.start and d.end:
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
        shape = {"fold": Qt.CursorShape.PointingHandCursor, "grip": Qt.CursorShape.OpenHandCursor,
                 "move": Qt.CursorShape.OpenHandCursor, "start": Qt.CursorShape.SizeHorCursor,
                 "end": Qt.CursorShape.SizeHorCursor}.get(what.removeprefix("kd-"), Qt.CursorShape.ArrowCursor)
        self.setCursor(shape)

    def _drag_to(self, d: Drag, x: float) -> None:
        """Where a drag puts the dates, snapping to days: a whole working week for a name, else the bar moved or stretched."""
        if d.mode == "new":
            if x < self.scale.NAME_W or x > self.width() - 10 - self.scale.inset:
                d.start = d.end = None
                return
            d.start, d.end = week_from(self.scale.day_at(self, x))
            return
        if d.start0 is None or d.end0 is None:
            return
        n = round((x - d.x0) / self.scale.px_per_day(self))
        s, e = d.start0, d.end0
        mode = d.mode.removeprefix("kd-")  # a key date moves and stretches as a bar does
        if mode == "move":
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


class TimelineView(QWidget):
    """The Timeline view: its controls, Plan mode's strip, the card for the row clicked last, the head and the rows, a
    legend and the undated tasks. ``open_task`` and ``update_task`` send a task to open, or to update in the capture
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
    #: Total or A week, and Show routine.
    settings_changed = Signal(dict)
    REMEMBERED = ("weeks", "order", "bars", "a_week", "routine")

    def __init__(self) -> None:
        super().__init__()
        self.model: Model | None = None
        self.today = date.today()
        self.start: date | None = None
        self.weeks = 9
        self.order = "top"
        self.bars = "project"
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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.addWidget(QLabel("Timeline", objectName="paneTitle"))
        lay.addWidget(Help("Open tasks over the coming weeks: a row per project, folded to start with, a bar from Start to Due, "
                           "a diamond for a deadline and a dot for each occurrence of a routine task. Parked and closed tasks are "
                           "left out. Click a row to see its dates and people; double-click a bar or a name for Quick edit."))
        self.controls = QWidget()
        rows = QVBoxLayout(self.controls)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        time_row, show_row = QWidget(), QWidget()
        self.time_layout = FlowLayout(time_row, spacing=8)
        self.show_layout = FlowLayout(show_row, spacing=8)
        rows.addWidget(time_row)
        rows.addWidget(show_row)
        lay.addWidget(self.controls)
        self.plan_strip = QFrame(objectName="fileRow")
        ps = QHBoxLayout(self.plan_strip)
        ps.setContentsMargins(10, 4, 6, 4)
        strip = QLabel("<b>Plan mode:</b> drag a bar, or its ends, to change its dates; drag a ⋮⋮ name onto the chart for a working "
                       "week. Saved and logged; Ctrl+Z undoes.")
        strip.setWordWrap(True)
        ps.addWidget(strip, 1)
        done = QPushButton("Done")
        done.clicked.connect(lambda: self.set_plan(False))
        ps.addWidget(done)
        self.plan_strip.setStyleSheet(f"QFrame#fileRow {{ background-color: {SEL}; border: 1px solid #9dc0e3; border-radius: 4px; }}")
        lay.addWidget(self.plan_strip)
        self.card = QFrame(objectName="fileRow")
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(10, 6, 10, 6)
        self.card_text = QLabel()
        self.card_text.setWordWrap(True)
        self.card_text.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(self.card_text, 1)
        self.open_button = QPushButton("Open task", objectName="primary")
        self.open_button.clicked.connect(lambda: self.sel and self.open_task.emit(self.sel))
        self.quick_button = QPushButton("Quick edit")
        self.quick_button.clicked.connect(self._quick_from_card)
        self.update_button = QPushButton("Update")
        self.update_button.clicked.connect(lambda: self.sel and self.update_task.emit(self.sel))
        for b in (self.open_button, self.quick_button, self.update_button):
            cl.addWidget(b)
        self.legend_slot = lay.count()  # the legend goes here, under the controls (the visual overhaul's O5)
        lay.addWidget(self.card)
        self.head = TimelineHead(self.scale)
        self.head.picked.connect(self._pick)
        lay.addWidget(self.head)
        self.chart = TimelineChart(self.scale)
        self.chart.picked.connect(self._pick)
        self.chart.opened.connect(self.open_task)
        self.chart.fold.connect(self.set_open)
        self.chart.quick_edit.connect(self.quick_edit)
        self.chart.dropped.connect(self._dropped)
        self.chart.dropped_key.connect(self._dropped_key)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.chart)
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda *_: self._sync_inset())
        lay.addWidget(self.scroll, 1)
        self.marks_legend = " &nbsp; ".join((
            '<span style="background-color:#89aedb">&nbsp;&nbsp;&nbsp;&nbsp;</span> In progress',
            '<span style="background-color:#ced9ee; border:1px solid #3b78c4">&nbsp;&nbsp;&nbsp;&nbsp;</span> Not started',
            '<span style="color:#b0261e"><b>▌</b></span> Late', "◆ Deadline", '<span style="color:#5a6571"><b>⊢⊣</b></span> Its subtasks\' span',
            '<span style="color:#3b78c4">●</span> Routine: each occurrence', '<span style="color:#1d5e98"><b>│</b></span> Today',
            f'<span style="background-color:{EV_BG}; color:{EV_LINE}">&nbsp;{FLAG}&nbsp;</span> Plant event',
            # Key dates (release 5.31): a window, a start or an end alone, a hard deadline
            '<span style="color:#3b78c4"><b>▬</b></span> Key date', "<b>[ ]</b> Its start or end",
            '<span style="color:#b0261e">◆</span> Its deadline'))
        self.legend = QLabel(self.marks_legend, objectName="hint")  # one line: the marks, then what colours the bars
        self.legend.setWordWrap(True)
        if LOOK.classic:
            lay.addWidget(self.legend)
        else:
            lay.insertWidget(self.legend_slot, self.legend)
        self.undated = QLabel(objectName="hint")
        self.undated.setWordWrap(True)
        self.undated.linkActivated.connect(self._undated_link)
        lay.addWidget(self.undated)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """P for Plan mode, and Ctrl+Z for the last drop (decisions 136 and 144), wherever the caret is in the view but a
        text box. P is free in the browse tool."""
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if event.key() == Qt.Key.Key_P and mods == Qt.KeyboardModifier.NoModifier:
            self.set_plan(not self.plan)
        elif event.key() == Qt.Key.Key_Z and mods == Qt.KeyboardModifier.ControlModifier:
            self.undo_last()
        else:
            super().keyPressEvent(event)

    def render(self, model: Model, today: date) -> None:
        """Draw the view again from the model, keeping its controls' choices."""
        self.model, self.today = model, today
        if self.start is None:
            self.start = timeline.default_start(today)
        if self.sel and self.sel not in model.tasks:
            self.sel = None
        if self.focus and self.focus not in model.tasks:
            self.focus = None
        if self.order not in {k for k, _ in timeline.order_choices(model)}:  # a parent label that's no longer one
            self.order = "top"
        self._controls()
        tl = timeline.build(model, today, self.start, self.weeks, self.order, tuple(self.labels), tuple(self.people), self.routine,
                            self.open_ids, self.plan, self.focus)
        self.scale.tl = tl
        self.scale.set_order(self.order)
        self._sync_inset()
        self.head.set_timeline(model, today, model.task(self.focus).title if self.focus else "", self.sel, field_names(self.order)[0])
        self.chart.set_timeline(model, today, self.sel, self.plan, self.bars, self.a_week, self.order)
        self.plan_strip.setVisible(self.plan)
        self._card()
        if tl.undated:
            self.undated.setText("Not on the timeline, with no dates: " + ", ".join(
                f'<a href="task:{esc(x)}">{esc(model.task(x).title)}</a>' for x in tl.undated) + '. <a href="plan:">Plan mode</a> puts them on it, '
                "to drag onto the chart.")
        self.undated.setVisible(bool(tl.undated))

    def _sync_inset(self) -> None:
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

    def _controls(self) -> None:
        """The controls in two rows, each in groups with a divider between (the playbook's toolbar groups): time and what's
        shown (Earlier, This week, Later, the range; Focus and the levels; Plan), then how it's drawn and filtered (Order
        by, Colour bars by, Hours; Labels, People, Show routine)."""
        for lay in (self.time_layout, self.show_layout):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w is not None:  # hidden now, deleted once the signal that redraws the view has returned
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
        for text, s, tip in (("◀ Earlier", -1, "Back four weeks (13 over six months, 26 over a year)"), ("This week", 0, "From last week"),
                             ("Later ▶", 1, "On four weeks (13 over six months, 26 over a year)")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=s: self.shift(s))
            lay.addWidget(b)
        combo(lay, "Show", [(n, f"Show {label}") for n, label in timeline.RANGES], self.weeks, "weeks")
        divider(lay)
        focus = combo(lay, "Focus on", [("", "Focus on all projects"), *((x, "Focus on " + name) for x, name in self._focus_choices())],
                      self.focus or "", "focus")
        focus.setMaximumWidth(280)
        for text, n in (("Collapse a level", -1), ("Expand a level", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, n=n: self.level(n))
            lay.addWidget(b)
        divider(lay)
        plan = QPushButton("✎ Plan")
        plan.setCheckable(True)
        plan.setChecked(self.plan)
        plan.setToolTip("Plan mode: drag bars and names to set dates (P)")
        plan.clicked.connect(lambda on: self.set_plan(on))
        lay.addWidget(plan)
        lay = self.show_layout
        combo(lay, "Order by", [(k, f"Order by {label}") for k, label in timeline.order_choices(m)], self.order, "order")
        combo(lay, "Colour bars by", [(k, f"Colour bars by {label.lower()}") for k, label in timeline.BARS], self.bars, "bars")
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
        return {k: getattr(self, k) for k in self.REMEMBERED}

    def restore(self, saved: dict) -> None:
        """The choices kept from last time, each only when it's still one the view offers."""
        valid = {"weeks": {n for n, _ in timeline.RANGES}, "bars": {k for k, _ in timeline.BARS}}
        for key in self.REMEMBERED:
            value = saved.get(key)
            if value is None or (key in valid and value not in valid[key]):
                continue
            if key in ("a_week", "routine"):
                value = bool(value)
            elif key == "order" and not isinstance(value, str):
                continue
            setattr(self, key, value)

    def _set(self, key: str, value) -> None:
        if key == "focus":
            value = value or None
            if value and self.model is not None:  # everything under it open
                for x in [value, *self.model.descendants_of(value)]:
                    if self.model.children_of(x):
                        self.open_ids.add(x)
                self.folds_changed.emit(sorted(self.open_ids))
        setattr(self, key, value)
        if key in self.REMEMBERED:
            self.settings_changed.emit(self.settings())
        if self.model is not None:
            self.render(self.model, self.today)

    def set_plan(self, on: bool) -> None:
        """Plan mode on or off (P, the Plan button, or Done)."""
        self.plan = bool(on)
        if self.model is not None:
            self.render(self.model, self.today)

    def set_open(self, task_id: str, open_: bool) -> None:
        """A row's subtasks shown or folded: its arrow, Right or Left."""
        (self.open_ids.add if open_ else self.open_ids.discard)(task_id)
        self.folds_changed.emit(sorted(self.open_ids))
        if self.model is not None:
            self.render(self.model, self.today)

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
            self.render(self.model, self.today)

    def shift(self, direction: int) -> None:
        """Earlier, This week or Later: by four weeks, 13 over six months, or 26 over a year."""
        if self.start is None:
            return
        self.start = timeline.default_start(self.today) if direction == 0 else self.start + timedelta(weeks=direction * timeline.step(self.weeks))
        if self.model is not None:
            self.render(self.model, self.today)

    def _pick(self, task_id: str) -> None:
        self.sel = task_id
        if self.model is not None:
            self.chart.sel = self.head.sel = task_id
            self.chart.update()
            self.head.update()
            self._card()
            top = self.chart.top_of(task_id)
            if top is not None:
                self.scroll.ensureVisible(0, top + self.chart.ROW_H // 2, 0, self.chart.ROW_H)
        self.chart.setFocus()

    def _quick_from_card(self) -> None:
        if self.sel:
            r = self.card.rect()
            self.quick_edit.emit(self.sel, QRect(self.card.mapToGlobal(r.topLeft()), r.size()))

    def _dropped(self, task_id: str, start: date, end: date, mode: str) -> None:
        """A Plan mode drop: the new dates, kept for Ctrl+Z, and sent to be saved and logged."""
        m = self.model
        if m is None:
            return
        t = m.task(task_id)
        self.undo.append(("task", task_id, t.start, t.due))
        # Stretching one end leaves the other as it was; moving a bar that ends at its deadline gives it a Due.
        new_start = t.start if mode == "end" else start.isoformat()
        new_due = t.due if mode == "start" else end.isoformat()
        said = {"new": f"Start and Due set: {long_date(start, self.today)} to {long_date(end, self.today)}",
                "start": f"Start moved to {long_date(start, self.today)}", "end": f"Due moved to {long_date(end, self.today)}",
                "move": f"now {long_date(start, self.today)} to {long_date(end, self.today)}"}[mode]
        self.set_dates.emit(task_id, new_start, new_due, f"{t.title}: {said}. Ctrl+Z undoes it.")

    def _dropped_key(self, task_id: str, key_id: int, first: date, last: date, kind: str) -> None:
        """A key date's drop in Plan mode (decision 152): its new dates, by its kind (a start alone stays one), kept for
        Ctrl+Z and sent to be saved and logged."""
        m = self.model
        kd = next((k for k in m.key_dates_of(task_id) if k.id == key_id), None) if m is not None else None
        if m is None or kd is None:
            return
        self.undo.append(("key", task_id, key_id, kd.start, kd.end))
        start = None if kind == "by" else first.isoformat()
        end = None if kind == "from" else last.isoformat()
        moved = KeyDate(kd.id, task_id, start, end, kd.description)
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

    def _card(self) -> None:
        """The card for the row clicked last: its title, state, path, dates, hours and people, with Open task, Quick edit and
        Update."""
        m, today = self.model, self.today
        t = m.tasks.get(self.sel) if m and self.sel else None
        for b in (self.open_button, self.quick_button, self.update_button):
            b.setVisible(t is not None)
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
