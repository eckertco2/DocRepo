"""The Timing window (release 5.51; the task templates design, decision 255): a template's anchor and every row's ties, with a chart that
redraws as you type, because a relative date means little without the others. ``TieLine`` is one tie as a sentence, here and in a row's
own form. The rules are in ``docrepo.templates`` and the sums in ``docrepo.timing``.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from docrepo import ties, timing
from docrepo.templates import Library, RowTiming
from docrepo.timing import Line, RowTie, Scale
from docrepo.ui.look import Help
from docrepo.ui.style import style_sheet
from docrepo.ui.task_forms import BAD_DURATION, MON_TO_FRI, days_valid, typed_days
from docrepo.ui.timing_chart import paint_lane, paint_ruler
from docrepo.ui.widgets import FormDialog, dialog_buttons, fit_dialog

#: The columns' widths, so every row and the heading line up.
ANCHOR, TASK, TIED, DAYS, LANE = 50, 172, 516, 52, 240
NO_ANCHOR = 0  # the No anchor circle's id: rows' ids start at 1


def source_options(lines: Sequence[Line], anchor: int | None, row_id: int) -> list[tuple[str, int | None]]:
    """The rows a row can be tied to: the anchor first, and not itself, a row that gives no date, or one that would make a circle (decision 253)."""
    out: list[tuple[str, int | None]] = [("the anchor" if anchor is not None else "choose a row", None)]
    for x in lines:
        if x.id not in (row_id, anchor) and x.placeable and not timing.moves_with(lines, anchor, x.id, row_id):
            out.append((x.title, x.id))
    return out


class TieLine(QWidget):
    """A row's Start or Due as one sentence: [30] [workdays] [before] [the anchor] [starts]. A blank number is no tie, and that date's placed by hand."""

    changed = Signal()

    def __init__(self, name: str, title: str = "") -> None:
        super().__init__()
        self.name = name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.label = QLabel(ties.FIELDS[name], objectName="fieldLabel")
        self.label.setFixedWidth(28)
        self.amount = QLineEdit()
        self.amount.setValidator(QIntValidator(0, 999, self))
        self.amount.setPlaceholderText("–")
        self.amount.setFixedWidth(44)
        self.amount.setAccessibleName(f"{title} {ties.FIELDS[name]}, how many".strip())
        self.unit = QComboBox()
        self.unit.addItems(ties.UNITS)
        self.unit.setFixedWidth(100)
        self.unit.setAccessibleName("Workdays or weeks")
        self.direction = QComboBox()
        self.direction.addItems(ties.DIRECTIONS)
        self.direction.setFixedWidth(84)
        self.direction.setAccessibleName("Before or after")
        self.source = QComboBox()
        self.source.setFixedWidth(150)
        self.source.setAccessibleName("Which row")
        self.point = QComboBox()
        self.point.addItem("starts", "start")
        self.point.addItem("ends", "end")
        self.point.setFixedWidth(76)
        self.point.setAccessibleName("Starts or ends")
        for w in (self.label, self.amount, self.unit, self.direction, self.source, self.point):
            layout.addWidget(w)
        layout.addStretch()
        self._setting = False
        self.amount.textEdited.connect(lambda _: self._edited())
        for box in (self.unit, self.direction, self.source, self.point):
            box.currentIndexChanged.connect(lambda _: self._edited())

    def _edited(self) -> None:
        if not self._setting:
            self.changed.emit()

    def set_options(self, options: Sequence[tuple[str, int | None]]) -> None:
        """Which rows it offers. One it's already tied to stays, whatever else has changed."""
        now = self.source.currentData()
        self._setting = True
        try:
            self.source.clear()
            for text, value in options:
                self.source.addItem(text, value)
            at = self.source.findData(now)
            self.source.setCurrentIndex(max(0, at))
        finally:
            self._setting = False

    def set_tie(self, tie: RowTie | None) -> None:
        self._setting = True
        try:
            self.amount.setText("" if tie is None else str(tie.amount))
            t = tie or RowTie()
            self.unit.setCurrentText(t.unit)
            self.direction.setCurrentText(t.direction)
            self.source.setCurrentIndex(max(0, self.source.findData(t.source)))
            self.point.setCurrentIndex(0 if t.point == "start" else 1)
        finally:
            self._setting = False

    def tie(self) -> RowTie | None:
        text = self.amount.text().strip()
        if not text.isdigit():
            return None
        return RowTie(self.source.currentData(), self.point.currentData(), int(text), self.unit.currentText(), self.direction.currentText())


class TimingLane(QWidget):
    """A row's bar on the chart."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(LANE)
        self.scale: Scale | None = None
        self.bar: tuple[int, int] | None = None
        self.kind = "b"

    def show_bar(self, scale: Scale | None, bar: tuple[int, int] | None, kind: str) -> None:
        self.scale, self.bar, self.kind = scale, bar, kind
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        paint_lane(p, self.width(), self.height(), self.scale, self.bar, self.kind)
        p.end()


class TimingRuler(QWidget):
    """The weeks' names over the lanes."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(LANE)
        self.setFixedHeight(18)
        self.scale: Scale | None = None

    def show_scale(self, scale: Scale | None) -> None:
        self.scale = scale
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        paint_ruler(p, self.width(), self.height(), self.scale)
        p.end()


class TimingRow(QFrame):
    """One row of the window: its circle, its name, its sentences or why it has none, its Days, and its lane."""

    def __init__(self, line: Line, group: QButtonGroup, typed: Any) -> None:
        super().__init__(objectName="timingRow")
        self.line = line
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)
        holder = QWidget()
        holder.setFixedWidth(ANCHOR)
        circle = QHBoxLayout(holder)
        circle.setContentsMargins(0, 0, 0, 0)
        self.radio = QRadioButton()
        self.radio.setAccessibleName(f"Make {line.title} the anchor")
        self.radio.setVisible(line.placeable)
        circle.addWidget(self.radio, 0, Qt.AlignmentFlag.AlignCenter)
        group.addButton(self.radio, line.id)
        layout.addWidget(holder)
        self.title = QLabel(line.title)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setToolTip(line.title)
        self.title.setContentsMargins(line.depth * 12, 0, 0, 0)
        self.title.setFixedWidth(TASK)
        layout.addWidget(self.title)

        cell = QWidget()
        cell.setFixedWidth(TIED)
        stack = QVBoxLayout(cell)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(4)
        self.start, self.due = TieLine("start", line.title), TieLine("due", line.title)
        self.add_due = QPushButton("+ Tie its Due too", objectName="link")
        self.add_due.clicked.connect(self._show_due)
        pill_row = QWidget()
        pills = QHBoxLayout(pill_row)
        pills.setContentsMargins(0, 0, 0, 0)
        pills.setSpacing(6)
        badge = QLabel("Anchor", objectName="anchorPill")
        badge.setFixedHeight(18)
        pills.addWidget(badge)
        pills.addWidget(QLabel("Its date is typed when you make tasks", objectName="hint"))
        pills.addStretch()
        self.pill = pill_row
        none = "Repeats, so it has no one date" if line.routine else "Spans its subtasks"
        self.none = QLabel(none, objectName="hint")
        for w in (self.start, self.due, self.add_due, self.pill, self.none):
            stack.addWidget(w, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(cell)

        self.days = QLineEdit("" if line.days is None else str(line.days))
        self.days.setFixedWidth(DAYS)
        self.days.setAccessibleName(f"Days of {line.title}")
        self.dash = QLabel("–", objectName="hint")
        self.dash.setToolTip("Both dates are tied, so the length comes from them")
        self.dash.setFixedWidth(DAYS)
        self.gap = QWidget()
        self.gap.setFixedWidth(DAYS)
        for w in (self.days, self.dash, self.gap):
            layout.addWidget(w)
        self.lane = TimingLane()
        layout.addWidget(self.lane, 1)
        self.start.changed.connect(typed)
        self.due.changed.connect(typed)
        self.days.textEdited.connect(lambda _: typed())
        self.showing_due = "due" in line.ties

    def _show_due(self) -> None:
        self.showing_due = True
        self.show_state(False)

    def show_state(self, is_anchor: bool) -> None:
        """Which of its parts it shows, as the anchor, a row that gives no date, or any other."""
        placeable = self.line.placeable
        tied = placeable and not is_anchor
        self.none.setVisible(not placeable)
        self.pill.setVisible(placeable and is_anchor)
        self.start.setVisible(tied)
        self.due.setVisible(tied and self.showing_due)
        self.add_due.setVisible(tied and not self.showing_due)
        both = tied and self.start.tie() is not None and self.due.tie() is not None
        self.days.setVisible(placeable and not both)
        self.dash.setVisible(both)
        self.gap.setVisible(not placeable)
        self.setProperty("anchor", "true" if is_anchor else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class TimingDialog(FormDialog):
    """The Timing window: ``anchor`` and ``result`` say what's chosen. Choosing another row as the anchor keeps the picture (decision 255)."""

    def __init__(self, parent: QWidget | None, lib: Library, template_id: int, workdays: Collection[int] = MON_TO_FRI) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Timing: {lib.name(template_id)}")
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.template_id = template_id
        self.week = len(workdays) or 5
        self.anchor = lib.templates[template_id].anchor
        self.lines = lib.lines(template_id)
        self._busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        intro = QLabel("Choose the anchor: the task whose date you'll know first. You type its date when you make tasks. Every other row can be tied to it, "
                       "or to another row. Leave a number blank to place that date by hand.")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        head = QFrame(objectName="timingHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(8, 2, 8, 2)
        hl.setSpacing(8)
        for text, width in (("Anchor", ANCHOR), ("Task", TASK), ("Tied to", TIED), ("Days", DAYS)):
            label = QLabel(text, objectName="fieldLabel")
            label.setFixedWidth(width)
            hl.addWidget(label)
        self.ruler = TimingRuler()
        hl.addWidget(self.ruler, 1)

        body = QWidget(objectName="capture")
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        rows.addWidget(head)
        self.group = QButtonGroup(self)
        self.rows: dict[int, TimingRow] = {}
        for line in self.lines:
            row = TimingRow(line, self.group, self._typed)
            self.rows[line.id] = row
            rows.addWidget(row)
        rows.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.note = QLabel(objectName="tip")
        self.note.setWordWrap(True)
        self.note.hide()
        outer.addWidget(self.note)
        self.none_radio = QRadioButton("No anchor: rows tied to it are placed by hand")
        self.group.addButton(self.none_radio, NO_ANCHOR)
        outer.addWidget(self.none_radio)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        outer.addLayout(dialog_buttons(self, "Save", self._accept, self.reject, Help(self.KEYS_HINT)))

        self._load()
        (self.rows[self.anchor].radio if self.anchor in self.rows else self.none_radio).setChecked(True)
        self.group.idClicked.connect(self._chosen)
        self.mark_clean()
        fit_dialog(self, body, ANCHOR + TASK + TIED + DAYS + LANE + 120, 240)

    # ---- the boxes and the lines ----
    def _load(self) -> None:
        """Put the lines into the boxes, and draw."""
        self._busy = True
        try:
            self._offer()
            for line in self.lines:
                row = self.rows[line.id]
                row.start.set_tie(line.ties.get("start"))
                row.due.set_tie(line.ties.get("due"))
                row.showing_due = row.showing_due or "due" in line.ties
        finally:
            self._busy = False
        self._draw()

    def _offer(self) -> None:
        for line in self.lines:
            options = source_options(self.lines, self.anchor, line.id)
            self.rows[line.id].start.set_options(options)
            self.rows[line.id].due.set_options(options)

    def _read(self) -> None:
        """Take the boxes into the lines."""
        out = []
        for line in self.lines:
            row = self.rows[line.id]
            if not line.placeable or line.id == self.anchor:
                out.append(replace(line, days=typed_days(row.days) if line.placeable else line.days))
                continue
            now = {f: tie for f, tie in (("start", row.start.tie()), ("due", row.due.tie())) if tie and (tie.source is not None or self.anchor is not None)}
            out.append(replace(line, ties=now, days=typed_days(row.days)))
        self.lines = out

    def _typed(self) -> None:
        if self._busy:
            return
        self.error.hide()
        self._read()
        self._busy = True
        try:
            self._offer()
        finally:
            self._busy = False
        self._draw()

    def _draw(self) -> None:
        pos = timing.positions(self.lines, self.anchor, self.week)
        scale = timing.scale_of(pos, self.week) if self.anchor is not None else None
        self.ruler.show_scale(scale)
        for line in self.lines:
            row = self.rows[line.id]
            row.show_state(line.id == self.anchor)
            bar = timing.span_of(self.lines, line.id, pos) if line.spans else pos.get(line.id)
            row.lane.show_bar(scale, bar, "g" if line.spans else "a" if line.id == self.anchor else "b")

    def _chosen(self, row_id: int) -> None:
        """Another anchor, or none."""
        self._read()
        self.error.hide()
        if row_id == NO_ANCHOR:
            self.lines = timing.without_anchor(self.lines)
            self.anchor = None
            self.note.hide()
        elif row_id != self.anchor:
            placed = timing.positions(self.lines, self.anchor, self.week)
            kept = self.anchor is not None and row_id in placed
            self.lines = timing.rebased(self.lines, self.anchor, row_id, self.week)
            self.anchor = row_id
            title = next(x.title for x in self.lines if x.id == row_id)
            self.note.setText(f"The bars stayed where they were. What was tied to the anchor now counts from {title}.")
            self.note.setVisible(kept)
        self._load()

    # ---- saving ----
    def save(self) -> None:
        self._accept()

    def problem(self) -> str | None:
        for line in self.lines:
            row = self.rows[line.id]
            if line.placeable and len(line.ties) < 2 and not days_valid(row.days):
                return f"{BAD_DURATION} ({line.title})"
        return None

    def _accept(self) -> None:
        self._read()
        said = self.problem()
        if said:
            self.error.setText(said)
            self.error.show()
            return
        self.accept()

    def result_rows(self) -> dict[int, RowTiming]:
        """What the window says for each row that can have a date."""
        return {x.id: RowTiming({} if x.id == self.anchor else dict(x.ties), x.days) for x in self.lines if x.placeable}

    def snapshot(self) -> Any:
        self._read()
        return [self.anchor, self.result_rows()]
