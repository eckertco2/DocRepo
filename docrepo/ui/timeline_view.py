"""The browse tool's Timeline view (mods log round 1, M0019): a chart of open tasks over the coming weeks.

The rows come from ``docrepo/timeline.py``; this module only paints them and handles the mouse. Clicking a row shows
its dates and people in a card above the chart; clicking it again, double-clicking it or Open task opens the task.
Hovering a row shows the same as a tooltip. It takes the middle and right panes together, as Capacity does.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
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

from docrepo import timeline
from docrepo.dates import days_text, long_date, short, to_date
from docrepo.detail import esc
from docrepo.model import Model
from docrepo.schedule import due_of, start_of
from docrepo.timeline import Row, Timeline
from docrepo.ui.tree_view import GROUP_COLOURS
from docrepo.ui.widgets import CheckMenuButton, FlowLayout, label_filter, people_filter
from docrepo.views import markers

FG, MUTED, LINE, LINE_STRONG = "#1a1f25", "#5a6571", "#d6dce3", "#b8c1cb"
ACCENT, BAD, SEL, SURFACE_2 = "#1d5e98", "#b0261e", "#dbe8f5", "#f4f6f8"
#: The pages' chip colours, inline: a QLabel doesn't have the pages' stylesheet.
CHIP_STYLE = {"st-ns": ("#5a6571", "#eef1f4"), "st-ip": ("#1d5e98", "#dbe8f5"), "urgent": ("#b0261e", "#fbe3e1"),
              "routine": ("#1a1f25", "#e9edf1"), "multi": ("#1d5e98", "#e4eefa")}


def _chip(text: str, cls: str) -> str:
    fg, bg = CHIP_STYLE.get(cls, CHIP_STYLE["st-ns"])
    return f'<span style="color:{fg}; background-color:{bg}">&nbsp;{esc(text)}&nbsp;</span>'


def _mix(colour: str, strength: float) -> QColor:
    """``colour`` mixed into white: at 1 the colour itself, at 0 white."""
    c = QColor(colour)
    return QColor(round(255 + (c.red() - 255) * strength), round(255 + (c.green() - 255) * strength), round(255 + (c.blue() - 255) * strength))


class TimelineChart(QWidget):
    """The chart: a name column, then a track per row with its bars placed by date. ``picked`` sends the task a click
    selects; ``opened`` the one to open (a second click, or a double-click)."""

    picked = Signal(str)
    opened = Signal(str)

    NAME_W, HEAD_H, ROW_H, GROUP_H = 230, 40, 26, 28

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.tl: Timeline | None = None
        self.model: Model | None = None
        self.today = date.today()
        self.sel: str | None = None
        self.items: list[tuple[int, object]] = []  # (top y, a Group or a Row), in order

    def set_timeline(self, model: Model, tl: Timeline, today: date, sel: str | None) -> None:
        self.model, self.tl, self.today, self.sel = model, tl, today, sel
        self.items, y = [], self.HEAD_H
        for g in tl.groups:
            self.items.append((y, g))
            y += self.GROUP_H
            for r in g.rows:
                self.items.append((y, r))
                y += self.ROW_H
        self.setMinimumHeight(y + 8)
        self.update()

    # ---- placing ----
    def _x(self, day: date) -> float:
        """Where a day starts across the track, clamped to it."""
        assert self.tl is not None
        w = max(1, self.width() - self.NAME_W - 10)
        frac = (day - self.tl.start).days / self.tl.days
        return self.NAME_W + w * min(1.0, max(0.0, frac))

    def _mid(self, day: date) -> float:
        return (self._x(day) + self._x(day + timedelta(days=1))) / 2

    def band_at(self, x: float) -> timeline.Band | None:
        """The plant event across this point of the chart, if any."""
        if self.tl is None:
            return None
        return next((b for b in self.tl.events if self._x(b.start) <= x < self._x(b.end + timedelta(days=1))), None)

    def row_at(self, y: float) -> Row | None:
        for top, item in self.items:
            if isinstance(item, Row) and top <= y < top + self.ROW_H:
                return item
        return None

    # ---- painting ----
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        if self.tl is None or self.model is None:
            return
        tl, m = self.tl, self.model
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        right = self.width() - 10
        base, bold, small = QFont(self.font()), QFont(self.font()), QFont(self.font())
        bold.setBold(True)
        small.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))
        now_in = tl.start <= self.today < tl.end
        # The scale: months, weeks and Today.
        p.setFont(bold)
        p.setPen(QColor(FG))
        for d in tl.months():
            p.drawText(QPointF(self._x(d) + 3, 15), f"{d.strftime('%B')} {d.year}")
        p.setFont(small)
        for i, w in enumerate(tl.week_starts()):
            x = self._x(w)
            p.setPen(QColor(LINE_STRONG))
            p.drawLine(QPointF(x, 20), QPointF(x, self.HEAD_H))
            if i % 2 == 0 or self.width() - self.NAME_W > 760:
                p.setPen(QColor(MUTED))
                p.drawText(QPointF(x + 3, 33), short(w, self.today))
        p.setPen(QPen(QColor(LINE_STRONG), 1))
        p.drawLine(QPointF(0, self.HEAD_H - 0.5), QPointF(right, self.HEAD_H - 0.5))
        # The rows.
        for top, item in self.items:
            if isinstance(item, timeline.Group):
                p.fillRect(QRectF(0, top, right, self.GROUP_H), QColor(SURFACE_2))
                if item.colour is not None:
                    p.fillRect(QRectF(0, top, 4, self.GROUP_H), QColor(GROUP_COLOURS[item.colour % len(GROUP_COLOURS)]))
                p.setFont(bold)
                p.setPen(QColor(FG))
                p.drawText(QRectF(10, top, self.NAME_W + 300, self.GROUP_H), Qt.AlignmentFlag.AlignVCenter,
                           f"{item.name}   {item.count}")
                continue
            self._paint_row(p, top, item, base, small, now_in)
        # Plant events (release 5.9, M0028): a shaded band down the whole chart, named at its top, whatever the filters.
        for band in tl.events:
            x0, x1 = self._x(band.start), self._x(band.end + timedelta(days=1))
            p.fillRect(QRectF(x0, self.HEAD_H, max(2.0, x1 - x0), self.height() - self.HEAD_H), QColor(192, 132, 25, 38))
            p.setPen(QPen(QColor(192, 132, 25, 140), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x0, self.HEAD_H), QPointF(x0, self.height()))
            p.drawLine(QPointF(x1, self.HEAD_H), QPointF(x1, self.height()))
            p.setFont(small)
            p.setPen(QColor("#875700"))
            p.drawText(QRectF(x0 + 3, self.HEAD_H + 1, max(40.0, x1 - x0 + 160), 14), Qt.AlignmentFlag.AlignLeft, band.title)
        p.end()

    def _paint_row(self, p: QPainter, top: int, r: Row, base: QFont, small: QFont, now_in: bool) -> None:
        assert self.model is not None and self.tl is not None
        t = self.model.task(r.task)
        right = self.width() - 10
        if r.task == self.sel:
            p.fillRect(QRectF(0, top, right, self.ROW_H), QColor(SEL))
        p.setPen(QPen(QColor(LINE), 1))
        p.drawLine(QPointF(0, top + self.ROW_H - 0.5), QPointF(right, top + self.ROW_H - 0.5))
        for i in range(self.tl.weeks):  # a line at each week's start
            x = self._x(self.tl.start + timedelta(weeks=i))
            p.drawLine(QPointF(x, top), QPointF(x, top + self.ROW_H))
        # The name, indented by its depth; a context row dimmed; "late" in red.
        p.setFont(base)
        p.setPen(QColor(MUTED if r.ctx else FG))
        indent = 8 + 12 * r.depth
        name_w = self.NAME_W - indent - (34 if r.late else 6)
        text = p.fontMetrics().elidedText(t.title, Qt.TextElideMode.ElideRight, max(20, name_w))
        p.drawText(QRectF(indent, top, name_w, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, text)
        if r.late:
            p.setFont(small)
            p.setPen(QColor(BAD))
            p.drawText(QRectF(self.NAME_W - 32, top, 30, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, "late")
        colour = GROUP_COLOURS[r.colour % len(GROUP_COLOURS)]
        for a, b in r.windows:
            x0, x1 = self._x(a), self._x(b + timedelta(days=1))
            if r.routine and a == b:  # a one-day occurrence: a dot
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(colour))
                p.drawEllipse(QPointF(self._mid(a), top + 13), 4, 4)
            elif r.routine:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_mix(colour, 0.55))
                p.drawRoundedRect(QRectF(x0, top + 9, max(2.0, x1 - x0), 8), 3, 3)
            else:
                rect = QRectF(x0, top + 6, max(3.0, x1 - x0), 14)
                p.setPen(QPen(QColor(colour), 1) if r.not_started else Qt.PenStyle.NoPen)
                p.setBrush(_mix(colour, 0.25) if r.not_started else _mix(colour, 0.72))
                p.drawRoundedRect(rect, 4, 4)
                if r.not_started:  # hatched, as in the mockup
                    p.setBrush(QBrush(_mix(colour, 0.6), Qt.BrushStyle.BDiagPattern))
                    p.drawRoundedRect(rect, 4, 4)
                if r.late:
                    p.fillRect(QRectF(rect.right() - 4, rect.top(), 4, rect.height()), QColor(BAD))
        if r.deadline:
            cx, cy, s = self._mid(r.deadline), top + 13.0, 6.0
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(QColor(BAD if r.deadline < self.today else FG))
            p.drawPolygon(QPolygonF([QPointF(cx, cy - s), QPointF(cx + s, cy), QPointF(cx, cy + s), QPointF(cx - s, cy)]))
        if now_in:
            x = self._mid(self.today)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawLine(QPointF(x, top), QPointF(x, top + self.ROW_H))

    # ---- the mouse ----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        r = self.row_at(event.position().y())
        if r is None:
            return
        if r.task == self.sel:
            self.opened.emit(r.task)
        else:
            self.picked.emit(r.task)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        r = self.row_at(event.position().y())
        if r is not None:
            self.opened.emit(r.task)

    def event(self, e) -> bool:  # noqa: D102 - hovering a row shows its dates and people
        if e.type() == QEvent.Type.ToolTip and self.model is not None:
            r = self.row_at(e.pos().y())
            band = self.band_at(e.pos().x()) if r is None or e.pos().y() < self.HEAD_H + 16 else None
            if band is not None:  # a plant event's name and dates (release 5.9)
                QToolTip.showText(e.globalPos(), f"{band.title}\nPlant event, {short(band.start, self.today)} to {short(band.end, self.today)}", self)
            elif r is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(e.globalPos(), timeline.tooltip(self.model, r.task, self.today), self)
            return True
        return super().event(e)


class TimelineView(QWidget):
    """The Timeline view: its controls, the card for the row clicked last, the chart, a legend and the undated tasks.
    ``open_task`` and ``update_task`` send a task to open, or to update in the capture window."""

    open_task = Signal(str)
    update_task = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.model: Model | None = None
        self.today = date.today()
        self.start: date | None = None
        self.weeks = 9
        self.group = "top"
        self.labels: list[str] = []
        self.people: list[str] = []
        self.routine = True
        self.sel: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.addWidget(QLabel("Timeline", objectName="paneTitle"))
        note = QLabel("Open tasks over the coming weeks: a bar from Start to Due, a diamond for a deadline, a dot for each occurrence "
                      "of a routine task. Parked and closed tasks are left out. Click a row to see its dates and people; click it "
                      "again to open it.", objectName="paneNote")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.controls = QWidget()
        self.controls_layout = FlowLayout(self.controls, spacing=8)
        lay.addWidget(self.controls)
        self.card = QFrame(objectName="fileRow")
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(10, 6, 10, 6)
        self.card_text = QLabel()
        self.card_text.setWordWrap(True)
        self.card_text.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(self.card_text, 1)
        self.open_button = QPushButton("Open task", objectName="primary")
        self.open_button.clicked.connect(lambda: self.sel and self.open_task.emit(self.sel))
        self.update_button = QPushButton("Update")
        self.update_button.clicked.connect(lambda: self.sel and self.update_task.emit(self.sel))
        cl.addWidget(self.open_button)
        cl.addWidget(self.update_button)
        lay.addWidget(self.card)
        self.chart = TimelineChart()
        self.chart.picked.connect(self._pick)
        self.chart.opened.connect(self.open_task)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.chart)
        lay.addWidget(scroll, 1)
        legend = QLabel(" &nbsp; ".join((
            '<span style="background-color:#89aedb">&nbsp;&nbsp;&nbsp;&nbsp;</span> In progress',
            '<span style="background-color:#ced9ee; border:1px solid #3b78c4">&nbsp;&nbsp;&nbsp;&nbsp;</span> Not started',
            '<span style="color:#b0261e"><b>▌</b></span> Late', "◆ Deadline", '<span style="color:#3b78c4">●</span> Routine: each occurrence',
            '<span style="color:#1d5e98"><b>│</b></span> Today', '<span style="background-color:#f3e6cc">&nbsp;&nbsp;&nbsp;&nbsp;</span> Plant event')),
            objectName="hint")
        lay.addWidget(legend)
        self.undated = QLabel(objectName="hint")
        self.undated.setWordWrap(True)
        self.undated.linkActivated.connect(lambda href: self.open_task.emit(href.partition(":")[2]))
        lay.addWidget(self.undated)

    def render(self, model: Model, today: date) -> None:
        """Draw the view again from the model, keeping its controls' choices."""
        self.model, self.today = model, today
        if self.start is None:
            self.start = timeline.default_start(today)
        if self.sel and self.sel not in model.tasks:
            self.sel = None
        self._controls()
        tl = timeline.build(model, today, self.start, self.weeks, self.group, tuple(self.labels), tuple(self.people), self.routine)
        self.chart.set_timeline(model, tl, today, self.sel)
        self._card()
        self.undated.setText("Not on the timeline, with no dates: " + ", ".join(
            f'<a href="task:{esc(x)}">{esc(model.task(x).title)}</a>' for x in tl.undated) + "." if tl.undated else "")
        self.undated.setVisible(bool(tl.undated))

    def _controls(self) -> None:
        lay = self.controls_layout
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:  # hidden now, deleted once the signal that redraws the view has returned
                w.hide()
                w.deleteLater()
        m = self.model
        assert m is not None
        group = QComboBox()
        group.setAccessibleName("Group by")
        for key, label in timeline.group_choices(m):
            group.addItem(f"Group by {label}", key)
        group.setCurrentIndex(max(0, group.findData(self.group)))
        group.currentIndexChanged.connect(lambda _: self._set("group", group.currentData()))
        lay.addWidget(group)
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
        weeks = QComboBox()
        weeks.setAccessibleName("Show")
        for n, label in timeline.RANGES:
            weeks.addItem(f"Show {label}", n)
        weeks.setCurrentIndex([n for n, _ in timeline.RANGES].index(self.weeks))
        weeks.currentIndexChanged.connect(lambda _: self._set("weeks", weeks.currentData()))
        lay.addWidget(weeks)
        for text, s in (("◀ Earlier", -1), ("This week", 0), ("Later ▶", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=s: self.shift(s))
            lay.addWidget(b)

    def _set(self, key: str, value) -> None:
        setattr(self, key, value)
        if self.model is not None:
            self.render(self.model, self.today)

    def shift(self, direction: int) -> None:
        """Earlier, This week or Later: by four weeks, or 13 over six months."""
        if self.start is None:
            return
        self.start = timeline.default_start(self.today) if direction == 0 else self.start + timedelta(weeks=direction * timeline.step(self.weeks))
        if self.model is not None:
            self.render(self.model, self.today)

    def _pick(self, task_id: str) -> None:
        self.sel = task_id
        if self.model is not None:
            self.chart.set_timeline(self.model, self.chart.tl, self.today, task_id)  # type: ignore[arg-type]
            self._card()

    def _card(self) -> None:
        """The card for the row clicked last: its title, state, path, dates and people, with Open task and Update."""
        m, today = self.model, self.today
        t = m.tasks.get(self.sel) if m and self.sel else None
        self.open_button.setVisible(t is not None)
        self.update_button.setVisible(t is not None)
        if t is None or m is None:
            self.card_text.setText(f'<span style="color:{MUTED}">Click a row to see its dates and people here; click it again, or Open task, to open it.</span>')
            return
        due = due_of(t, today)
        if t.recurrence:
            dates = f"{esc(t.recurrence)} from {esc(long_date(start_of(t), today))}" + (f", next {esc(long_date(due.date, today))}" if due else "")
        else:
            end = (f"Due {long_date(to_date(t.due), today)}" if t.due else f"Deadline {long_date(to_date(t.deadline), today)}" if t.deadline
                   else "no end date")
            dates = esc(f"{long_date(start_of(t), today)} → {end}") + (
                f' <span style="color:{MUTED}">{esc(days_text(due.date, today))}</span>' if due else "")
        if t.deadline and (t.due or t.recurrence):
            dates += esc(f" · Deadline {long_date(to_date(t.deadline), today)}" + (f", {t.deadline_desc}" if t.deadline_desc else ""))

        def people(ids: list[str], hours: float | None) -> str:
            return ", ".join(esc(m.person_name(p)) + (f" {hours:g} h" if hours else "") for p in ids) or "None"

        path = " › ".join(m.task(x).title for x in m.chains_of(t.id)[0][:-1]) or "Top-level task"
        chips = "".join(" " + _chip(text, cls) for text, cls in markers(m, t))
        state = _chip(t.state, "st-ip" if t.state == "In progress" else "st-ns")
        self.card_text.setText(f"<b>{esc(t.title)}</b> {state}{chips}<br><span style='color:{MUTED}'>{esc(path)}</span><br>{dates}"
                               f"<br><span style='color:{MUTED}'>Lead: {people(t.leads, t.lead_hours)} · Assignees: "
                               f"{people(t.assignees, t.assignee_hours)}</span>")
