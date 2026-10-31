"""The browse tool's task forms: Edit task, with every field on one page (mods log round 1, M0008, M0011), Edit selected
for several tasks at once (M0009), and a label's matching tasks (M0014).

Edit task reuses the capture window's fields and pickers, and saves through
``edits.edit_task``, so each change goes into the status log as "Browse tool".
An Update capture stays the way to make changes that come with a note. Edit
selected and the matching tasks change tasks through ``bulk``, with a preview
first.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from datetime import date
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import priorities, quick, templates, timeline
from docrepo.bulk import BulkEdit, LabelMatch, TaskOutcome, summary
from docrepo.db import RECURRENCES, STATES
from docrepo.dates import long_date, to_date
from docrepo.detail import esc
from docrepo.model import Model
from docrepo.pages import num
from docrepo.parse import Who
from docrepo.schedule import length_of, placed, start_of, week_of
from docrepo.tasks import KeyDateRow, hours_values
from docrepo.ui.icons import icon
from docrepo.ui.look import Help
from docrepo.ui.style import page_css, style_sheet
from docrepo.ui.task_picker import full_path, path_text
from docrepo.ui.tree_view import RowTree
from docrepo.ui.widgets import (
    Chip,
    ChipPicker,
    DateField,
    FlowLayout,
    FormDialog,
    HoursField,
    InfoButton,
    Option,
    dialog_buttons,
    field,
    fit_dialog,
    section,
    set_filled,
)

Options = Callable[[str, list[str]], list[Option]]
#: Opens the task picker under a widget; the callback gets the picked task's ID, or None.
PickTask = Callable[[QWidget, Callable[[str | None], None]], None]
LEAVE = "Leave as it is"
#: A week's workdays, for a form that isn't told Settings' own.
MON_TO_FRI = frozenset(range(5))
BAD_DURATION = "Duration is a whole number of days, 1 or more."


def typed_days(box: QLineEdit) -> int | None:
    """A Duration box's whole days, or None when it's empty or isn't one (``days_valid`` says which)."""
    text = box.text().strip()
    return int(text) if text.isdigit() and int(text) >= 1 else None


def days_valid(box: QLineEdit) -> bool:
    return not box.text().strip() or typed_days(box) is not None


class ShareSpin(QSpinBox):
    """The Involvement box's number. Its keys close the box, rather than saving or closing the form around it."""

    done = Signal(bool)  # False puts the number back

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2):
            self.interpretText()
            self.done.emit(True)
        elif event.key() == Qt.Key.Key_Escape:
            self.done.emit(False)
        else:
            super().keyPressEvent(event)


class ShareBox(QFrame):
    """The small box a person's chip opens, as a popup, so it takes no room in the form: "Tom Becker  Involvement [25 %]
    = 3 h of 12 h". It changes the chip as it's typed. Enter, F2 or a click elsewhere keeps the number, and Esc puts back the
    one it opened with."""

    closed = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("involvementBox")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.name = QLabel()
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        font = self.name.font()
        font.setBold(True)
        self.name.setFont(font)
        self.spin = ShareSpin()
        self.spin.setRange(0, 100)
        self.spin.setSingleStep(5)
        self.spin.setSuffix(" %")
        self.spin.setFixedWidth(78)
        self.says = QLabel(objectName="hint")
        self.says.setMinimumWidth(self.says.fontMetrics().horizontalAdvance("of this role's hours"))  # stays put as the number changes
        for w in (self.name, QLabel("Involvement", objectName="hint"), self.spin, self.says):
            row.addWidget(w)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().hideEvent(event)
        self.closed.emit()

    def open_under(self, widget: QWidget) -> None:
        """Show it just under a chip, kept on the screen."""
        self.adjustSize()
        at = widget.mapToGlobal(widget.rect().bottomLeft()) + QPoint(0, 3)
        screen = widget.screen().availableGeometry()
        if at.y() + self.height() > screen.bottom():
            at.setY(widget.mapToGlobal(widget.rect().topLeft()).y() - self.height() - 3)
        at.setX(max(screen.left(), min(at.x(), screen.right() - self.width())))
        self.move(at)
        self.show()
        self.spin.setFocus()
        self.spin.selectAll()


class PersonChip(QFrame):
    """A person in a form: their name, their Involvement when it isn't 100, and × to take them off. Double-click, or F2 with it
    focused, opens the Involvement box (release 5.47, decision 196)."""

    def __init__(self, picker: PeoplePicker, i: int, chip: Chip) -> None:
        super().__init__(objectName="personChip")
        self.picker, self.value = picker, chip.value
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Double-click, or F2: how much of this role's hours land on them")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 1, 2, 1)
        lay.setSpacing(3)
        lay.addWidget(QLabel(f"{chip.label}{'  new' if chip.new else ''}"))
        share = picker.share(chip.value)
        if share != 100:
            lay.addWidget(QLabel(f"{share}%", objectName="personShare"))
        take_off = QToolButton(text="×")
        take_off.setAccessibleName(f"Take {chip.label} off")
        take_off.setToolTip(take_off.accessibleName())
        take_off.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        take_off.clicked.connect(lambda _=False: picker.remove(i))
        lay.addWidget(take_off)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.picker.open_share(self.value)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.key() == Qt.Key.Key_F2:
            self.picker.open_share(self.value)
        else:
            super().keyPressEvent(event)


class PeoplePicker(ChipPicker):
    """A form's lead or assignees, each with their Involvement: the percentage of the role's hours that land on them, 100 by
    default and not a split. ``role`` is "lead" or "assignee", and ``total`` gives the role's hours, for what a share comes to."""

    def __init__(self, options: Options, placeholder: str, create_text: str | None, role: str, total: Callable[[], float | None]) -> None:
        self.shares: dict[str, int] = {}
        super().__init__(options, placeholder, create_text)
        self.role, self._total = role, total
        self.editing: str | None = None
        self._opened_with = 100
        self.share_box = ShareBox(self)
        self.spin = self.share_box.spin
        self.spin.valueChanged.connect(self._share_edited)
        self.spin.done.connect(self.close_share)
        self.share_box.closed.connect(self._share_closed)

    def _chip_widget(self, i: int, chip: Chip) -> QWidget:
        return PersonChip(self, i, chip)

    def share(self, value: str) -> int:
        return self.shares.get(value, 100)

    def set_shares(self, shares: dict[str, int]) -> None:
        self.shares = {k: v for k, v in shares.items() if v != 100}
        self._render()

    def stated(self) -> list[tuple[str, int]]:
        """The people as a template row's are compared: each with their Involvement."""
        return [(c.value, self.share(c.value)) for c in self.chips()]

    def set_stated(self, m: Model, value: list[tuple[str, int]]) -> None:
        self.shares = {p: share for p, share in value if share != 100}
        self.set_chips(people_chips(m, [p for p, _ in value]))
        self.close_share()
        self.changed.emit()

    def involvement(self) -> dict[tuple[str, str], int]:
        return {(self.role, c.value): self.share(c.value) for c in self.chips() if self.share(c.value) != 100}

    def remove(self, index: int) -> None:
        value = self.chips()[index].value
        self.shares.pop(value, None)
        if self.editing == value:
            self.close_share()
        super().remove(index)

    def shares_text(self, total: float | None) -> str:
        """Who has less than the whole: "Tom Becker 3 h", or their percentage while the role has no hours."""
        parts = []
        for c in self.chips():
            share = self.share(c.value)
            if share != 100:
                parts.append(f"{c.label} {num(round(total * share / 100, 2))} h" if total is not None else f"{c.label} {share}%")
        return ", ".join(parts)

    def _chip_of(self, value: str) -> PersonChip | None:
        for i in range(self._flow.count()):
            chip = self._flow.itemAt(i).widget()
            if isinstance(chip, PersonChip) and chip.value == value:
                return chip
        return None

    def open_share(self, value: str) -> None:
        chip = self._chip_of(value)
        if chip is None:
            return
        self.editing, self._opened_with = value, self.share(value)
        self.share_box.name.setText(next(c.label for c in self.chips() if c.value == value))
        self.spin.setAccessibleName(f"Involvement of {self.share_box.name.text()}")
        self.spin.blockSignals(True)
        self.spin.setValue(self._opened_with)
        self.spin.blockSignals(False)
        self._say_share()
        self.share_box.open_under(chip)

    def close_share(self, keep: bool = True) -> None:
        """Close the box from the keyboard, or as its person goes, and go back to their chip."""
        value = self.editing
        if value is None:
            return
        if not keep:
            self.spin.setValue(self._opened_with)
        self.share_box.hide()
        chip = self._chip_of(value)
        if chip is not None:
            chip.setFocus()

    def _share_closed(self) -> None:
        self.editing = None

    def _say_share(self) -> None:
        total = self._total()
        share = self.spin.value()
        self.share_box.says.setText(f"= {num(round(total * share / 100, 2))} h of {num(total)} h" if total is not None else "of this role's hours")

    def _share_edited(self, share: int) -> None:
        if self.editing is None:
            return
        if share == 100:
            self.shares.pop(self.editing, None)
        else:
            self.shares[self.editing] = share
        self._render()
        self._say_share()
        self.changed.emit()


class HoursRow(QWidget):
    """A role's hours with their unit (release 5.46, decision 189; release 5.49, decision 260): the box, h in all, h a day or h a
    week, and a line saying what a rate comes to. Switching the unit keeps the total, when the task has a length; without one, it
    keeps the number, read as the new unit. A routine task's hours are for each time, so it has no unit to choose. ``length``
    gives the task's days, ``shares`` who has less than the whole, given the total, and ``week`` how many days make a week."""

    changed = Signal()

    UNITS = ("all", "day", "week")

    def __init__(self, hours: HoursField, length: Callable[[], int | None], people: Callable[[], int] = lambda: 1,
                 shares: Callable[[float | None], str] = lambda _: "", week: Callable[[], int] = lambda: 5) -> None:
        super().__init__()
        self.hours, self._length, self._people, self._shares, self._week = hours, length, people, shares, week
        self._was = "all"
        self.unit = QComboBox()
        self.unit.addItems(["h in all", "h a day", "h a week"])
        self.unit.setAccessibleName("Hours unit")
        self.unit.setFixedWidth(108)
        self.line = QLabel(objectName="hint")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(hours)
        row.addWidget(self.unit)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(self.line)
        self.setFocusProxy(hours)
        self.routine = False
        hours.textEdited.connect(lambda _: self._edited())
        self.unit.activated.connect(self._switched)

    def unit_name(self) -> str:
        """"all", "day" or "week". A routine task's hours are a total, for each time."""
        return "all" if self.routine else self.UNITS[self.unit.currentIndex()]

    def set_unit_name(self, name: str) -> None:
        self.unit.setCurrentIndex(self.UNITS.index(name))
        self._was = name

    def per_day(self) -> bool:
        return self.unit_name() == "day"

    def set_per_day(self, on: bool) -> None:
        self.set_unit_name("day" if on else "all")

    def number(self) -> float | None:
        return self.hours.value() if self.hours.is_valid() else None

    def stated(self) -> Any:
        """The hours as they're stated: a rate as ``("a day", n)`` or ``("a week", n)``, as a template row's are compared; else the number."""
        n, unit = self.number(), self.unit_name()
        return (f"a {unit}", n) if unit != "all" and n is not None else n

    def set_stated(self, value: Any) -> None:
        self.set_unit_name(value[0][2:] if isinstance(value, tuple) else "all")
        self.hours.set_value(value[1] if isinstance(value, tuple) else value)
        self._edited()

    def set_routine(self, on: bool) -> None:
        self.routine = on
        self.unit.setVisible(not on)
        self.show_line()

    def _edited(self) -> None:
        self.show_line()
        self.changed.emit()

    def _span(self, unit: str, days: int) -> float:
        return days if unit == "day" else days / self._week() if unit == "week" else 1

    def _switched(self, _index: int) -> None:
        n, days, unit = self.number(), self._length(), self.unit_name()
        if n is not None and days:
            self.hours.set_value(round(n * self._span(self._was, days) / self._span(unit, days), 2))
        self._was = unit
        self._edited()

    def total(self) -> float | None:
        """The role's total: as typed, or the rate times the task's days or weeks, or None until it has a length."""
        n, days, unit = self.number(), self._length(), self.unit_name()
        if n is None or unit == "all":
            return n
        return round(n * self._span(unit, days), 2) if days else None

    def show_line(self) -> None:
        n, days, unit = self.number(), self._length(), self.unit_name()
        if self.routine:
            text = "each time"
        elif unit == "all" or n is None:
            text = ""
        elif days:
            weeks = self._span("week", days)
            weeks_text = f" ({num(round(weeks, 2))} week{'' if weeks == 1 else 's'})" if unit == "week" else ""
            text = f"= {num(self.total())} h{' each' if self._people() > 1 else ''} over {days} day{'' if days == 1 else 's'}{weeks_text}"
        else:
            text = f"{num(n)} h a {unit}, needs a length"
        shares = self._shares(self.total())
        text = " · ".join(x for x in (text, shares) if x)
        self.line.setText(text)
        self.line.setVisible(bool(text))


def people_chips(m: Model, ids: list[str]) -> list[Chip]:
    return [Chip(p, m.person_name(p)) for p in ids]


def chips_people(chips: ChipPicker) -> list[Who]:
    """A people picker's chips as Who's: an ID, or the name of someone to add to the people list."""
    return [Who(name=c.value) if c.new else Who(c.value) for c in chips.chips()]


class KeyDateLine(QFrame):
    """One key date in a form (release 5.31, the key dates plan): Start and End, a description, and its Plant activity,
    Deadline and Done ticks, with up, down and remove. ``compact`` (Quick edit) puts the description on a line of its own,
    shortens the ticks' names and leaves out up and down, so it fits the small window; Edit task orders them."""

    changed = Signal()
    moved = Signal(object, int)
    removed = Signal(object)

    def __init__(self, row: KeyDateRow, compact: bool = False) -> None:
        super().__init__(objectName="fileRow")
        self.key_id = row.id
        self.start, self.end = DateField(), DateField()
        for f, value, name in ((self.start, row.start, "Start"), (self.end, row.end, "End")):
            f.set_value(value)
            f.line.setPlaceholderText(name)
            f.line.setAccessibleName(f"Key date {name.lower()}")
            f.setToolTip(f"{name}, YYYY-MM-DD; leave it empty for a key date with only {'an end' if name == 'Start' else 'a start'}")
            f.edited.connect(self.changed)
            if compact:
                f.setMaximumWidth(16777215)
        self.desc = QLineEdit(row.description)
        self.desc.setPlaceholderText("Description, such as Trial execution window")
        self.desc.setAccessibleName("Key date description")
        self.desc.textEdited.connect(lambda _: self.changed.emit())
        self.plant = QCheckBox("⚑ Plant" if compact else "⚑ Plant activity")
        self.plant.setToolTip("A plant event of its own: in the timeline's events lane, as a band down the chart, and named "
                              "under other tasks' dates that fall in it")
        self.deadline = QCheckBox("◆ Deadline")
        self.deadline.setToolTip("A hard date: a red diamond at its end")
        self.done = QCheckBox("Done")
        self.done.setToolTip("Off Today and the Overdue list; it stays on the task page and the timeline, grey")
        for box, on in ((self.plant, row.plant), (self.deadline, row.deadline), (self.done, row.done)):
            box.setChecked(on)
            box.toggled.connect(lambda _: self.changed.emit())
        self.done.toggled.connect(self._grey)
        buttons = []
        moves = () if compact else (("↑", "Move it up", lambda: self.moved.emit(self, -1)), ("↓", "Move it down", lambda: self.moved.emit(self, 1)))
        for text, tip_text, action in (*moves, ("✕", "Take it off", lambda: self.removed.emit(self))):
            b = QToolButton(text=text)
            b.setToolTip(tip_text)
            b.setAccessibleName(tip_text)
            b.setAutoRaise(True)
            b.clicked.connect(action)
            buttons.append(b)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 4, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        ticks = QHBoxLayout()
        ticks.setSpacing(6 if compact else 12)
        for box in (self.plant, self.deadline, self.done):
            ticks.addWidget(box)
        ticks.addStretch()
        for b in buttons:
            ticks.addWidget(b)
        if compact:
            grid.addWidget(self.start, 0, 0)
            grid.addWidget(self.end, 0, 1)
            grid.addWidget(self.desc, 1, 0, 1, 2)
            grid.addLayout(ticks, 2, 0, 1, 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
        else:
            grid.addWidget(self.start, 0, 0)
            grid.addWidget(self.end, 0, 1)
            grid.addWidget(self.desc, 0, 2)
            grid.addLayout(ticks, 1, 0, 1, 3)
            grid.setColumnStretch(2, 1)
        self._grey(row.done)

    def _grey(self, done: bool) -> None:
        self.desc.setStyleSheet("color: #87919c;" if done else "")

    def is_blank(self) -> bool:
        """A new line with nothing typed in it yet, which isn't saved."""
        return (self.key_id is None and not self.start.line.text().strip() and not self.end.line.text().strip()
                and not self.desc.text().strip())

    def row(self) -> KeyDateRow:
        return KeyDateRow(self.start.value(), self.end.value(), " ".join(self.desc.text().split()), self.plant.isChecked(),
                          self.deadline.isChecked(), self.done.isChecked(), self.key_id)

    def problem(self, n: int) -> str | None:
        """What stops it being saved, as key date ``n``."""
        for f, which in ((self.start, "start"), (self.end, "end")):
            if not f.is_valid():
                return f"Key date {n}'s {which} isn't a date. Use YYYY-MM-DD."
        start, end = self.start.value(), self.end.value()
        if not start and not end:
            return f"Key date {n} needs a start, an end or both."
        if start and end and end < start:
            return f"Key date {n} ends before it starts."
        return None


class KeyDatesEditor(QWidget):
    """A task's key dates in a form (release 5.31, the key dates plan, decision 146): a line each, in its order, and Add key
    date. ``rows`` gives them as ``edits.edit_task`` takes them; ``problem`` says what stops a save."""

    changed = Signal()

    def __init__(self, rows: Sequence[KeyDateRow] = (), compact: bool = False) -> None:
        super().__init__()
        self.compact = compact
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.list = QVBoxLayout()
        self.list.setSpacing(6)
        lay.addLayout(self.list)
        self.empty = QLabel("None. A key date is a date in the task's story: a start, a target or a window, without a subtask.",
                            objectName="hint")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        self.add_button = QPushButton("+ Add key date")
        self.add_button.setToolTip("A start, an end or both, with a description: such as a trial's execution window")
        self.add_button.clicked.connect(lambda: self.add_row())
        lay.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.lines: list[KeyDateLine] = []
        for row in rows:
            self.add_row(row, focus=False)
        self._sync()

    def add_row(self, row: KeyDateRow | None = None, focus: bool = True) -> KeyDateLine:
        line = KeyDateLine(row or KeyDateRow(None, None), self.compact)
        line.changed.connect(self.changed)
        line.moved.connect(self._move)
        line.removed.connect(self._remove)
        self.lines.append(line)
        self.list.addWidget(line)
        self._sync()
        if focus:
            line.start.line.setFocus()
            self.changed.emit()
        return line

    def _move(self, line: KeyDateLine, step: int) -> None:
        i = self.lines.index(line)
        j = i + step
        if not 0 <= j < len(self.lines):
            return
        self.lines[i], self.lines[j] = self.lines[j], self.lines[i]
        for x in self.lines:
            self.list.removeWidget(x)
        for x in self.lines:
            self.list.addWidget(x)
        self.changed.emit()

    def _remove(self, line: KeyDateLine) -> None:
        self.lines.remove(line)
        self.list.removeWidget(line)
        line.hide()
        line.deleteLater()
        self._sync()
        self.changed.emit()

    def _sync(self) -> None:
        self.empty.setVisible(not self.lines)

    def rows(self) -> list[KeyDateRow]:
        """The lines as rows, in order; a new line left empty isn't one."""
        return [line.row() for line in self.lines if not line.is_blank()]

    def problem(self) -> str | None:
        n = 0
        for line in self.lines:
            if line.is_blank():
                continue
            n += 1
            p = line.problem(n)
            if p:
                return p
        return None


def key_date_rows(m: Model, task_id: str) -> list[KeyDateRow]:
    """A task's key dates as a form's rows."""
    return [KeyDateRow(kd.start, kd.end, kd.description, kd.plant, kd.deadline, bool(kd.done), kd.id) for kd in m.key_dates_of(task_id)]


class FieldLink:
    """One field's mark in Edit task (release 5.45, decision 184), for a task made from a template. It follows: a quiet chain
    mark, and clicking it keeps the task's value and stops following. It doesn't, or differs from the row: a faint "Template:
    6 h ↺", and clicking it takes the row's value and follows it again. Typing a different value on a field that follows
    shows a small line under it, and it stops on Save."""

    def __init__(self, m: Model, key: str, link: templates.TaskLink, saved: Any, get: Callable[[], Any], put: Callable[[Any], None],
                 sync: Callable[[], None]) -> None:
        self.m, self.key, self.link, self.saved, self.get, self.put, self._sync = m, key, link, saved, get, put, sync
        self.following = key in link.links
        self.mark = QToolButton(objectName="linkMark")
        self.mark.setIconSize(QSize(14, 14))
        self.mark.clicked.connect(self.clicked)
        self.leaving = QLabel("This task will stop following the template.", objectName="linkLeaving")
        self.leaving.hide()

    @property
    def row_value(self) -> Any:
        return templates.stated(self.link.row, self.key)

    def differs(self) -> bool:
        return self.get() != self.row_value

    def clicked(self) -> None:
        if self.following and not self.differs():
            self.following = False
        else:
            self.put(self.row_value)
            self.following = True
        self._sync()

    def show(self) -> None:
        """Draw the mark as the field now stands."""
        differs = self.differs()
        if self.following and not differs:
            self.mark.setIcon(icon("link"))
            self.mark.setText("")
            self.mark.setAccessibleName(f"Linked to {self.link.name}. Click to stop following.")
            self.mark.setToolTip(f"Linked to {self.link.name}: {templates.field_text(self.m, self.key, self.row_value)}. Click to keep this task's own value.")
        else:
            self.mark.setIcon(QIcon())
            self.mark.setText(f"Template: {templates.field_text(self.m, self.key, self.row_value)} ↺" if differs else "Follow template ↺")
            self.mark.setAccessibleName(self.mark.text())
            self.mark.setToolTip("Take the template's value and follow it again")
        self.leaving.setVisible(self.following and differs and self.get() != self.saved)

    def follows_after_save(self, reopening: bool) -> bool:
        """Whether it follows once the form is saved: it stops if it was given a different value. A field that fell behind
        while the task was closed still follows while it stays closed; reopening makes it its own (decision 185)."""
        if not self.following:
            return False
        return not self.differs() or (self.get() == self.saved and not reopening)


class TaskEditDialog(FormDialog):
    """Edit task: a task's title, description, state, current status, parents (mods log round 2, M0040), labels, people and
    hours, dates, recurrence and flags. For a task made from a template, ``link`` (release 5.45) adds its marks and the line
    naming its row; ``after`` then says what the form closed for: ``("row", id)`` to open the row, or ``("detach",)``."""

    def __init__(self, parent: QWidget | None, m: Model, task_id: str, labels: Options, people: Options, pick_task: PickTask | None = None,
                 reference_fields: Sequence[str] = (), today: date | None = None, checklist: QWidget | None = None,
                 link: templates.TaskLink | None = None, workdays: Collection[int] = MON_TO_FRI) -> None:
        super().__init__(parent)
        t = m.task(task_id)
        self.m, self.task_id, self._pick_task, self.link = m, task_id, pick_task, link
        self.after: tuple | None = None
        self._was_closed = t.state == "Closed"
        self.workdays = workdays
        self._default_start = None if t.start else start_of(t).isoformat()  # a Start not set shows the day it was made
        self._moving = False
        self._worked: set[str] = set()
        self.today = today or date.today()
        self.parents: list[str] = list(m.parents_of(task_id))
        self.setWindowTitle(f"Edit task {task_id}")
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        # The visual overhaul's O4: one column of 560 px in sections, labels above fields, 8, 16 and 32 px apart, each field
        # as wide as what goes in it, the rarer fields under More options, and no scrolling unless the screen is small.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(Help("Each change goes into the task's status log as Browse tool. For a change that comes with a note, use Update "
                             "in the capture window instead."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(objectName="capture")
        g = QVBoxLayout(body)
        g.setContentsMargins(0, 0, 8, 0)
        g.setSpacing(16)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self._scroll = scroll
        if link:
            g.addLayout(self._origin_line(link))

        # ---- the task itself ----
        self.title = QLineEdit(t.title)
        title_field = field("Title", self.title, "title")
        g.addWidget(title_field)
        self.state = QComboBox()
        self.state.addItems(list(STATES))
        self.state.setCurrentText(t.state)
        self.state.setFixedWidth(170)
        self.urgent, self.meeting, self.plant_event = QCheckBox("Urgent"), QCheckBox("Meeting"), QCheckBox("Plant event")
        self.urgent.setChecked(t.urgent)
        self.meeting.setChecked(t.meeting)
        self.plant_event.setChecked(t.plant_event)
        # Priority (release 5.23, mods log round 2, M0029, M0030): a new bucket puts it at that bucket's end, ordered on the board.
        self.priority = QComboBox()
        for key, label, _ in priorities.COLUMNS:
            self.priority.addItem(label, key)
        self.priority.setCurrentIndex(max(0, self.priority.findData(t.priority or "")))
        self.priority.setToolTip("Its bucket on the Priorities board. A new bucket puts it at that bucket's end; order it on the board.")
        self.priority.setFixedWidth(140)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(field("State", self.state, "state"))
        row.addWidget(field("Priority", self.priority))
        flags = QHBoxLayout()
        flags.setSpacing(16)
        notes = []
        for box, key in ((self.urgent, "urgent"), (self.meeting, "meeting")):
            flags.addWidget(box)
            note = QLabel()
            flags.addWidget(InfoButton(key, note))
            notes.append(note)
        row.addLayout(flags)
        row.addStretch()
        row.setAlignment(flags, Qt.AlignmentFlag.AlignBottom)
        g.addLayout(row)
        for note in notes:
            g.addWidget(note)
        self.status = QPlainTextEdit(t.current_status)
        self.status.setFixedHeight(64)
        g.addWidget(field("Current status", self.status, "status"))
        self.description = QPlainTextEdit(t.description)
        self.description.setFixedHeight(96)
        description_field = field("Description", self.description)
        g.addWidget(description_field)
        # Its checklist (release 5.26, decision 88 as redone): the notes page's checklist lines, bound to them. A tick or
        # a rewording here changes the page at once, so Cancel leaves it; nothing goes into the status log.
        self.checklist = checklist
        if checklist is not None:
            section(g, "Checklist")
            g.addWidget(checklist)

        # ---- people ----
        section(g, "People")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self.leads = PeoplePicker(people, "Search names and aliases", "Add “{}” to people", "lead", lambda: self.lead_unit.total())
        self.leads.shares = {p: s for (r, p), s in t.involvement.items() if r == "lead"}
        self.leads.set_chips(people_chips(m, t.leads))
        self.assignees = PeoplePicker(people, "Search names and aliases", "Add “{}” to people", "assignee", lambda: self.asg_unit.total())
        self.assignees.shares = {p: s for (r, p), s in t.involvement.items() if r == "assignee"}
        self.assignees.set_chips(people_chips(m, t.assignees))
        self.lead_hours, self.asg_hours = HoursField(), HoursField()
        self.lead_hours.set_value(t.rate_of("lead")[0] if t.rate_of("lead") else t.lead_hours)
        self.asg_hours.set_value(t.rate_of("assignee")[0] if t.rate_of("assignee") else t.assignee_hours)
        for w in (self.lead_hours, self.asg_hours):
            w.setFixedWidth(72)
        week = lambda: week_of(self.workdays, self.calendar.isChecked())  # noqa: E731
        self.lead_unit = HoursRow(self.lead_hours, self._length_now, lambda: len(self.leads.chips()), self.leads.shares_text, week)
        self.asg_unit = HoursRow(self.asg_hours, self._length_now, lambda: len(self.assignees.chips()), self.assignees.shares_text, week)
        self.lead_unit.set_unit_name(t.rate_of("lead")[1] if t.rate_of("lead") else "all")
        self.asg_unit.set_unit_name(t.rate_of("assignee")[1] if t.rate_of("assignee") else "all")
        leads_field, assignees_field = field("Lead", self.leads, "leads"), field("Assignees", self.assignees, "assignees")
        lead_hours_field, asg_hours_field = field("Lead hours", self.lead_unit, "hours"), field("Assignee hours", self.asg_unit)
        top_edge = Qt.AlignmentFlag.AlignTop  # the labels stay level, however many chips or lines one of them holds
        grid.addWidget(leads_field, 0, 0, top_edge)
        grid.addWidget(assignees_field, 0, 1, top_edge)
        grid.addWidget(lead_hours_field, 1, 0, top_edge)
        grid.addWidget(asg_hours_field, 1, 1, top_edge)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        g.addLayout(grid)

        # ---- dates ----
        section(g, "Dates")
        self.start, self.due, self.deadline, self.reminder, self.repeat = DateField(), DateField(), DateField(), DateField(), DateField()
        for w, value in ((self.start, t.start or (None if t.duration else start_of(t).isoformat())), (self.due, t.due), (self.deadline, t.deadline),
                         (self.reminder, t.reminder), (self.repeat, t.repeat_until)):
            w.set_value(value)
        self.deadline_desc = QLineEdit(t.deadline_desc or "")
        self.recurrence = QComboBox()
        self.recurrence.addItems(["No recurrence", *RECURRENCES])
        self.recurrence.setCurrentText(t.recurrence or "No recurrence")
        self.recurrence.setFixedWidth(200)
        self.recurrence.currentIndexChanged.connect(self._sync)
        self.repeat_field = field("Repeat until", self.repeat, "repeatUntil")
        recurrence_field = field("Recurrence", self.recurrence, "recurrence")
        # Start, Duration and Due (release 5.46, decision 191): with a Duration, a date moves the block.
        self.duration = QLineEdit("" if t.duration is None else str(t.duration))
        self.duration.setFixedWidth(64)
        self.duration.setAccessibleName("Duration in days")
        self.calendar = QCheckBox("Runs through weekends")
        self.calendar.setChecked(t.calendar_days)
        self.calendar.setToolTip("Count every day, for its Due and where its hours land, not only workdays")
        days_box = QWidget()
        days_row = QHBoxLayout(days_box)
        days_row.setContentsMargins(0, 0, 0, 0)
        days_row.setSpacing(6)
        days_row.addWidget(self.duration)
        days_row.addWidget(QLabel("days", objectName="hint"))
        days_row.addStretch()
        self.duration_field = field("Duration", days_box)
        duration_field, start_field, due_field = self.duration_field, field("Start", self.start, "start"), field("Due", self.due, "due")
        when = QHBoxLayout()
        when.setSpacing(16)
        for box in (self.start, self.due):
            box.setMinimumWidth(DateField.WIDTH)  # room for a date in words, in a row that doesn't stretch them
        for w in (start_field, duration_field, due_field):
            when.addWidget(w)
        when.addStretch()
        g.addLayout(when)
        calendar_row = QHBoxLayout()
        calendar_row.addWidget(self.calendar)
        calendar_row.addStretch()
        g.addLayout(calendar_row)
        self.date_hint = QLabel("With a Duration, changing Start or Due moves the block, and only the Duration changes its length. Clear a date to take "
                                "it off the calendar, keeping its size.", objectName="hint")
        self.date_hint.setWordWrap(True)
        g.addWidget(self.date_hint)
        self.date_warn = QLabel(objectName="linkLeaving")
        self.date_warn.setWordWrap(True)
        g.addWidget(self.date_warn)
        dates = QGridLayout()
        dates.setHorizontalSpacing(16)
        dates.setVerticalSpacing(16)
        for w, r, c in ((field("Deadline", self.deadline, "deadline"), 0, 0), (field("Deadline description", self.deadline_desc, "deadlineDesc"), 0, 1),
                        (field("Reminder", self.reminder, "reminder"), 1, 0), (recurrence_field, 1, 1),
                        (self.repeat_field, 2, 1)):
            dates.addWidget(w, r, c)
        dates.setColumnStretch(0, 1)
        dates.setColumnStretch(1, 1)
        g.addLayout(dates)
        self.start.edited.connect(lambda: self._date_edited("start"))
        self.due.edited.connect(lambda: self._date_edited("due"))
        self.deadline.edited.connect(self._sync_dates)
        self.duration.textEdited.connect(lambda _: self._date_edited("duration"))
        self.calendar.toggled.connect(lambda _: self._date_edited("duration"))
        self.leads.changed.connect(self.lead_unit.show_line)
        self.assignees.changed.connect(self.asg_unit.show_line)
        # A date inside a plant event says so (release 5.9, mods log round 2, M0028).
        self.during = QLabel(objectName="hint")
        self.during.setWordWrap(True)
        g.addWidget(self.during)
        for w in (self.start, self.due, self.deadline):
            w.edited.connect(self._show_during)
        self._show_during()

        # ---- key dates (release 5.31, the key dates plan) ----
        section(g, "Key dates")
        self.key_dates = KeyDatesEditor(key_date_rows(m, task_id))
        g.addWidget(self.key_dates)

        # ---- where it sits: parents (mods log round 2, M0040) and labels ----
        section(g, "Where it sits")
        self.parents_box = QWidget()
        self.parents_layout = FlowLayout(self.parents_box, spacing=8)
        self.parents_hint = QLabel(objectName="hint")
        self.parents_hint.setWordWrap(True)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.parents_box)
        bl.addWidget(self.parents_hint)
        g.addWidget(field("Parents", box, sub="none makes it a top-level task"))
        self._draw_parents()
        self.labels = ChipPicker(labels, "Search or add", "Create label “{}”")
        self.labels.set_chips([Chip(name, name) for name in t.labels])
        labels_field = field("Labels", self.labels, "labels")
        g.addWidget(labels_field)
        self.inherit = QCheckBox("Inherit parent labels")
        self.inherit.setChecked(t.inherit_labels)
        inherited = list(dict.fromkeys(n for p in m.parents_of(task_id) for n, _ in m.labels_of(p)))
        row = QHBoxLayout()
        row.addWidget(self.inherit)
        inherit_row = row
        if inherited:
            row.addWidget(QLabel("Its parents have: " + ", ".join(inherited), objectName="hint"), 1)
        row.addStretch()
        g.addLayout(row)

        # ---- More options: the plant event and the reference fields (release 5.9) ----
        self.more_button = QPushButton("More options ▸", objectName="moreLink")
        g.addWidget(self.more_button)
        self.more = QWidget()
        ml = QVBoxLayout(self.more)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(16)
        plant = QHBoxLayout()
        plant.addWidget(self.plant_event)
        plant_note = QLabel()
        plant.addWidget(InfoButton("plantEvent", plant_note))
        plant.addStretch()
        ml.addLayout(plant)
        ml.addWidget(plant_note)
        self.references: dict[str, QLineEdit] = {}
        if reference_fields:
            refs = QGridLayout()
            refs.setHorizontalSpacing(16)
            refs.setVerticalSpacing(16)
            for i, name in enumerate(reference_fields):
                box = QLineEdit(t.references.get(name, ""))
                self.references[name] = box
                refs.addWidget(field(name, box, "references" if i == 0 else None), i // 2, i % 2)
            ml.addLayout(refs)
        g.addWidget(self.more)
        open_more = t.plant_event or any(t.references.get(n) for n in reference_fields)
        self.more.setVisible(open_more)
        self.more_button.setText("More options ▾" if open_more else "More options ▸")
        self.more_button.clicked.connect(self._toggle_more)
        g.addStretch()

        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        outer.addLayout(dialog_buttons(self, "Save", self._accept, self.reject, Help(self.KEYS_HINT)))
        self.marks: dict[str, FieldLink] = {}
        if link:
            self._add_marks(link, {"title": title_field, "description": description_field, "labels": labels_field, "leads": leads_field,
                                   "assignees": assignees_field, "lead_hours": lead_hours_field, "assignee_hours": asg_hours_field,
                                   "recurrence": recurrence_field, "duration": duration_field},
                            {"urgent": (flags, self.urgent), "meeting": (flags, self.meeting), "plant_event": (plant, self.plant_event),
                             "inherit_labels": (inherit_row, self.inherit), "calendar_days": (calendar_row, self.calendar)})
        self._sync()
        self.mark_clean()
        self.title.setFocus()
        fit_dialog(self, body, 640 if link else 608)  # a mark on each tick needs the room

    # ---- a task made from a template: the line naming its row, and each field's mark (release 5.45, decision 184) ----
    def _origin_line(self, link: templates.TaskLink) -> QHBoxLayout:
        line = QHBoxLayout()
        line.setSpacing(6)
        chain = QLabel()
        chain.setPixmap(icon("link").pixmap(14, 14))
        line.addWidget(chain)
        line.addWidget(QLabel("From template:", objectName="hint"))
        self.row_button = QPushButton(link.path, objectName="link")
        self.row_button.setToolTip("Open it in Templates")
        self.row_button.clicked.connect(lambda: self._leave(("row", link.row.id)))
        line.addWidget(self.row_button)
        self.detach_button = QPushButton("Detach", objectName="link")
        self.detach_button.setToolTip("End all its links. Its values stay.")
        self.detach_button.clicked.connect(lambda: self._leave(("detach",)))
        line.addWidget(self.detach_button)
        line.addStretch()
        return line

    def _leave(self, after: tuple) -> None:
        """Close the form for the row or Detach, asking first if something was changed."""
        if self.changed() and not self.ask_discard():
            return
        self.after = after
        QDialog.reject(self)

    def _field_values(self) -> dict[str, tuple[Callable[[], Any], Callable[[Any], None]]]:
        """Each field a row can fill, as the form reads and sets it, in a task's own terms."""
        def set_days(days: Any) -> None:
            self.duration.setText("" if days is None else str(days))
            self._date_edited("duration")

        return {
            "title": (lambda: self.title.text().strip(), self.title.setText),
            "description": (lambda: self.description.toPlainText().strip(), self.description.setPlainText),
            "labels": (self.labels.values, lambda names: self.labels.set_chips([Chip(n, n) for n in names])),
            "inherit_labels": (self.inherit.isChecked, self.inherit.setChecked),
            "leads": (self.leads.stated, lambda value: self.leads.set_stated(self.m, value)),
            "assignees": (self.assignees.stated, lambda value: self.assignees.set_stated(self.m, value)),
            "lead_hours": (self.lead_unit.stated, self.lead_unit.set_stated),
            "assignee_hours": (self.asg_unit.stated, self.asg_unit.set_stated),
            "duration": (lambda: typed_days(self.duration), set_days),
            "calendar_days": (self.calendar.isChecked, self.calendar.setChecked),
            "urgent": (self.urgent.isChecked, self.urgent.setChecked),
            "meeting": (self.meeting.isChecked, self.meeting.setChecked),
            "plant_event": (self.plant_event.isChecked, self.plant_event.setChecked),
            "recurrence": (lambda: self.recurrence.currentText() if self.recurrence.currentIndex() else None,
                           lambda v: self.recurrence.setCurrentText(v or "No recurrence")),
        }

    def _add_marks(self, link: templates.TaskLink, fields: dict[str, QWidget], checks: dict[str, tuple]) -> None:
        """A mark for each field the row fills, but the top task's title, which is its own. A field's goes beside its label,
        with the line under it; a tick's goes beside the tick."""
        values = self._field_values()
        for key in templates.FIELDS:
            if not templates.fills(link.row, key) or (key == "title" and link.top):
                continue
            get, put = values[key]
            mark = FieldLink(self.m, key, link, get(), get, put, self._sync_marks)
            self.marks[key] = mark
            if key in fields:
                box = fields[key]
                box.layout().itemAt(0).layout().insertWidget(1, mark.mark)
                box.layout().addWidget(mark.leaving)
            else:
                layout, widget = checks[key]
                layout.insertWidget(layout.indexOf(widget) + 1, mark.mark)
        self.title.textEdited.connect(lambda _: self._sync_marks())
        self.lead_unit.changed.connect(self._sync_marks)
        self.asg_unit.changed.connect(self._sync_marks)
        self.duration.textEdited.connect(lambda _: self._sync_marks())
        self.calendar.toggled.connect(lambda _: self._sync_marks())
        self.description.textChanged.connect(self._sync_marks)
        for picker in (self.labels, self.leads, self.assignees):
            picker.changed.connect(self._sync_marks)
        for tick in (self.inherit, self.urgent, self.meeting, self.plant_event):
            tick.toggled.connect(lambda _: self._sync_marks())
        self.recurrence.currentIndexChanged.connect(lambda _: self._sync_marks())
        self._sync_marks()

    def _sync_marks(self) -> None:
        for mark in self.marks.values():
            mark.show()

    def _toggle_more(self) -> None:
        on = self.more.isHidden()
        self.more.setVisible(on)
        self.more_button.setText("More options ▾" if on else "More options ▸")

    # ---- Duration and dates (release 5.46, decisions 190 and 191) ----
    def _start_value(self) -> str | None:
        """The Start as a date. The day it was made, shown for a Start that isn't set, doesn't count."""
        value = self.start.value() if self.start.is_valid() else None
        return None if value == self._default_start else value

    def _due_value(self) -> str | None:
        return self.due.value() if self.due.is_valid() else None

    def _length_now(self) -> int | None:
        start, due = self._start_value(), self._due_value()
        return length_of(start, due, typed_days(self.duration), self.workdays, self.calendar.isChecked())

    def _date_edited(self, what: str) -> None:
        """Start, Due or the Duration changed by hand: with a Duration typed, the block moves (decision 191). Black is kept:
        a date worked out here shows muted, with a tooltip saying so."""
        if self._moving:
            return
        self._moving = True
        try:
            self._worked.discard(what)
            days = typed_days(self.duration)
            box = {"start": self.start, "due": self.due}.get(what)
            if days is not None and (box is None or box.is_valid()):
                if self.start.value() == self._default_start and what != "start":
                    self.start.set_value(None)  # the day it was made is no Start to count from
                start, due = placed(self._start_value(), self._due_value(), days, what, self.workdays, self.calendar.isChecked())
                self._put_date(self.start, "start", start, what)
                self._put_date(self.due, "due", due, what)
        finally:
            self._moving = False
        self._sync_dates()

    def _put_date(self, box: DateField, name: str, value: str | None, what: str) -> None:
        if name != what and (box.value() or None) != value:
            box.set_value(value)
            if value:
                self._worked.add(name)
            else:
                self._worked.discard(name)

    def _sync_dates(self) -> None:
        """The grey length in an empty Duration, the muted dates, and the lines under them."""
        days = typed_days(self.duration)
        length = None if days is not None or not self.duration.text().strip() == "" else self._length_now()
        self.duration.setPlaceholderText(str(length) if length else "")
        self.duration.setToolTip(f"{length} day{'' if length == 1 else 's'} from its dates. Type a number to keep it when the dates move." if length
                                 else "How many days it takes. Typed, it's kept when the dates move.")
        for name, box, other in (("start", self.start, "Due"), ("due", self.due, "Start")):
            worked = name in self._worked
            set_filled(box.line, worked, name="worked")
            box.line.setToolTip(f"Worked out from {other} and Duration" if worked else "")
        self.date_hint.setVisible(days is not None and not self.recurrence.currentIndex())
        due, deadline = self._due_value(), self.deadline.value() if self.deadline.is_valid() else None
        late = bool(days is not None and due and deadline and due > deadline)
        self.date_warn.setText(f"Due is after the Deadline, {long_date(to_date(deadline), self.today)}." if late else "")
        self.date_warn.setVisible(late)
        self.lead_unit.show_line()
        self.asg_unit.show_line()
        self._show_during()

    def _sync(self) -> None:
        routine = self.recurrence.currentIndex() > 0
        self.repeat_field.setVisible(routine)
        self.duration_field.setVisible(not routine)  # a routine task has no Duration or rate: its hours are for each time
        self.calendar.setVisible(not routine)
        self.lead_unit.set_routine(routine)
        self.asg_unit.set_routine(routine)
        self._sync_dates()

    def _show_during(self) -> None:
        text = timeline.during_text(self.m, [("Start", self.start.value()), ("Due", self.due.value()), ("Deadline", self.deadline.value())],
                                    self.today, self.task_id)
        self.during.setText(text)
        self.during.setVisible(bool(text))

    def _draw_parents(self) -> None:
        while self.parents_layout.count():
            w = self.parents_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for p in self.parents:
            b = QPushButton(f"{full_path(self.m, p)}  ×")
            b.setToolTip(f"Take it out from under {self.m.task(p).title}")
            b.clicked.connect(lambda _=False, p=p: self.remove_parent(p))
            self.parents_layout.addWidget(b)
        if not self.parents:
            self.parents_layout.addWidget(QLabel("None: a top-level task", objectName="hint"))
        self.put_button = QPushButton("Put under a task…")
        self.put_button.setEnabled(self._pick_task is not None)
        self.put_button.clicked.connect(lambda: self._pick_task(self.put_button, self.put_under) if self._pick_task else None)
        self.parents_layout.addWidget(self.put_button)
        only_quick = len(self.parents) == 1 and quick.is_parent(self.m.task(self.parents[0]))
        self.parents_hint.setText("It's a quick task. Putting it under a task takes it out of Quick tasks." if only_quick else "")
        self.parents_hint.setVisible(only_quick)

    def put_under(self, task_id: str | None) -> None:
        """Put the task under another task as well; a quick task's only parent, Quick tasks, is replaced."""
        if not task_id or task_id in self.parents:
            return
        if len(self.parents) == 1 and quick.is_parent(self.m.task(self.parents[0])):
            self.parents = [task_id]
        else:
            self.parents.append(task_id)
        self._draw_parents()

    def remove_parent(self, task_id: str) -> None:
        self.parents = [p for p in self.parents if p != task_id]
        self._draw_parents()

    def save(self) -> None:
        self._accept()

    def snapshot(self) -> dict[str, Any]:
        return self.values()

    def problem(self) -> str | None:
        """What's wrong with the form, if anything: the first field that can't be saved."""
        if not self.title.text().strip():
            return "A task needs a title."
        for w, name in ((self.start, "Start"), (self.due, "Due"), (self.deadline, "Deadline"), (self.reminder, "Reminder"),
                        (self.repeat, "Repeat until")):
            if not w.is_valid():
                return f"{name} isn't a date. Use YYYY-MM-DD."
        for w, name in ((self.lead_hours, "Lead hours"), (self.asg_hours, "Assignee hours")):
            if not w.is_valid():
                return f"{name} isn't a number of hours."
        if not days_valid(self.duration):
            return BAD_DURATION
        return self.key_dates.problem()

    def _accept(self) -> None:
        problem = self.problem()
        if problem:
            self.error.setText(problem)
            self.error.show()
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        """The form's values, as edits.edit_task takes them."""
        recurrence = self.recurrence.currentText() if self.recurrence.currentIndex() else None
        return {
            "title": self.title.text(), "description": self.description.toPlainText(), "state": self.state.currentText(),
            "current_status": self.status.toPlainText(), "labels": self.labels.values(), "inherit_labels": self.inherit.isChecked(),
            "leads": chips_people(self.leads), "assignees": chips_people(self.assignees), "involvement": {**self.leads.involvement(), **self.assignees.involvement()},
            **self._hours_values(),
            "duration": typed_days(self.duration) if not recurrence else None, "calendar_days": self.calendar.isChecked() and not recurrence,
            "start": self.start.value(), "due": self.due.value(), "deadline": self.deadline.value(),
            "deadline_desc": self.deadline_desc.text(), "reminder": self.reminder.value(), "recurrence": recurrence,
            "repeat_until": self.repeat.value() if recurrence else None, "urgent": self.urgent.isChecked(), "meeting": self.meeting.isChecked(),
            "plant_event": self.plant_event.isChecked(), "parents": list(self.parents), "priority": self.priority.currentData(),
            "key_dates": self.key_dates.rows(),
            **({"references": {name: box.text() for name, box in self.references.items()}} if self.references else {}),
            **({"follow": self._following()} if self.link else {}),
        }

    def _hours_values(self) -> dict[str, Any]:
        """Each role's hours: a rate, whose total is worked out, or a total, with no rate (decision 189)."""
        out: dict[str, Any] = {}
        for unit, hours in ((self.lead_unit, "lead_hours"), (self.asg_unit, "assignee_hours")):
            out.update(hours_values(hours, unit.unit_name(), unit.number()))
        return out

    def _following(self) -> list[str]:
        """The fields that follow its template once this is saved (decision 184)."""
        reopening = self._was_closed and self.state.currentText() != "Closed"
        return [k for k, mark in self.marks.items() if mark.follows_after_save(reopening)]


def _preview_html(m: Model, outcomes: list[TaskOutcome]) -> str:
    """What an edit does to each task, for the preview: its status log entries, or why it can't be made."""
    def value(v: str | None) -> str:
        return esc(" ".join((v or "None").split()))

    parts = [f"<p><b>{esc(summary(outcomes))}</b></p>"]
    for o in outcomes:
        t = m.tasks.get(o.task)
        head = f"<b>{esc(t.title if t else o.task)}</b> <span class=\"sub\">{esc(o.task)}</span>"
        if o.problem:
            lines = [f'<span style="color:#b0261e">Left as it is: {esc(o.problem)}</span>']
        elif o.changes:
            lines = [f"{esc(c.field)}: {value(c.from_value)} → {value(c.to_value)}" for c in o.changes]
        else:
            lines = ['<span class="sub">Nothing changes.</span>']
        parts.append(f"<p>{head}<br>{'<br>'.join(lines)}</p>")
    return "".join(parts)


class BulkEditDialog(FormDialog):
    """Edit selected (mods log round 1, M0009): changes only what's set here, on every ticked task, after a preview.

    ``preview(edit)`` gives what an edit would do, without doing it; ``pick_task(anchor, picked)`` opens the task picker.
    """

    def __init__(self, parent: QWidget | None, m: Model, task_ids: list[str], labels: Options, people: Options,
                 preview: Callable[[BulkEdit], list[TaskOutcome]], pick_task: Callable[[QWidget, Callable[[str | None], None]], None]) -> None:
        super().__init__(parent)
        self.m, self.task_ids, self._preview_fn, self._pick_task = m, list(task_ids), preview, pick_task
        self.parent_task: str | None = None
        self.outcomes: list[TaskOutcome] = []
        n = len(self.task_ids)
        self.setWindowTitle(f"Edit {n} selected task{'s' if n != 1 else ''}")
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.resize(640, 720)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(Help("Only what you set here changes; everything else stays as it is on each task. Each task gets its own "
                             "status log entries, as Browse tool. Check the preview, then Apply."))
        form = QWidget(objectName="capture")
        g = QVBoxLayout(form)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(16)

        own = list(dict.fromkeys(name for x in self.task_ids if x in m.tasks for name in m.task(x).labels))
        self.add_labels = ChipPicker(labels, "Search or add", "Create label “{}”")
        self.remove_labels = ChipPicker(lambda text, picked: [Option(n, n) for n in own if n not in picked and text.strip().lower() in n.lower()],
                                        "Labels the tasks have" if own else "None of them has a label of its own")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(field("Add labels", self.add_labels, "labels"), 0, 0)
        grid.addWidget(field("Remove labels", self.remove_labels, sub="their own, not inherited ones"), 0, 1)
        self.state = QComboBox()
        self.state.addItems([LEAVE, *STATES])
        grid.addWidget(field("State", self.state, "state"), 1, 0)
        # Plant event (release 5.9, mods log round 2, M0028): tick or untick it on every task.
        self.plant_event = QComboBox()
        self.plant_event.addItems([LEAVE, "Tick it", "Untick it"])
        self.plant_event.currentIndexChanged.connect(self._changed)
        grid.addWidget(field("Plant event", self.plant_event, "plantEvent"), 1, 1)
        self.people: dict[str, tuple[QComboBox, ChipPicker]] = {}
        for row, (key, label, help_key) in enumerate((("leads", "Lead", "leads"), ("assignees", "Assignees", "assignees")), start=2):
            how = QComboBox()
            how.addItems([LEAVE, "Add these", "Replace with these"])
            chips = ChipPicker(people, "Search names and aliases")
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(how)
            lay.addWidget(chips)
            grid.addWidget(field(label, box, help_key), row // 2 + 1, (row - 2) % 2)
            self.people[key] = (how, chips)
            how.currentIndexChanged.connect(self._changed)
            chips.changed.connect(self._changed)
        self.dates: dict[str, tuple[QCheckBox, DateField]] = {}
        for i, (key, label) in enumerate((("due", "Due"), ("deadline", "Deadline"), ("reminder", "Reminder"))):
            on = QCheckBox(f"Set {label}")
            on.setToolTip("Tick to set it on every task. Left empty, it's cleared.")
            date = DateField()
            date.setEnabled(False)
            on.toggled.connect(date.setEnabled)
            on.toggled.connect(self._changed)
            date.edited.connect(self._changed)
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(on)
            lay.addWidget(date)
            grid.addWidget(box, 3 + i // 2, i % 2)
            self.dates[key] = (on, date)
        # Priority (release 5.23): each task goes to the end of the bucket, in the order they're ticked.
        self.priority = QComboBox()
        self.priority.addItem(LEAVE, None)
        for key, label, _ in priorities.COLUMNS:
            self.priority.addItem(label, key)
        self.priority.currentIndexChanged.connect(self._changed)
        grid.addWidget(field("Priority", self.priority), 4, 1)
        g.addLayout(grid)
        self.parent_button = QPushButton("Leave them where they are  ▾")
        self.parent_button.clicked.connect(lambda: self._pick_task(self.parent_button, self.set_parent))
        self.parent_how = QComboBox()
        self.parent_how.addItems(["Move there, out from under their parents", "Also put there, keeping their parents"])
        self.parent_how.currentIndexChanged.connect(self._changed)
        under = QHBoxLayout()
        under.addWidget(self.parent_button, 1)
        under.addWidget(self.parent_how)
        under_box = QWidget()
        under_box.setLayout(under)
        g.addWidget(field("Put under a task", under_box))
        for chips in (self.add_labels, self.remove_labels):
            chips.changed.connect(self._changed)
        self.state.currentIndexChanged.connect(self._changed)
        outer.addWidget(form)

        outer.addWidget(QLabel("Preview", objectName="heading"))
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.document().setDefaultStyleSheet(page_css())
        outer.addWidget(self.preview, 1)
        outer.addLayout(dialog_buttons(self, "Apply", self.accept, self.reject,
                                       Help("Ctrl+Enter applies. Esc closes, asking first if you've set something.")))
        self.apply_button = self.commit_button
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh_preview)
        self._sync_parent()
        self.refresh_preview()

    def save(self) -> None:
        self.refresh_preview()  # a change made a moment ago may not be in the preview yet
        if self.apply_button.isEnabled():
            self.accept()

    def changed(self) -> bool:
        return not self.edit().empty

    def set_parent(self, task_id: str | None) -> None:
        self.parent_task = task_id
        self._sync_parent()
        self._changed()

    def _sync_parent(self) -> None:
        picked = self.parent_task in self.m.tasks
        self.parent_button.setText((full_path(self.m, self.parent_task) if picked else "Leave them where they are") + "  ▾")
        self.parent_how.setEnabled(picked)

    def _changed(self) -> None:
        self._timer.start()

    def problem(self) -> str | None:
        for key, (on, date) in self.dates.items():
            if on.isChecked() and not date.is_valid():
                return f"{key.capitalize()} isn't a date. Use YYYY-MM-DD."
        return None

    def edit(self) -> BulkEdit:
        """The changes set in the form."""
        e = BulkEdit(add_labels=self.add_labels.values(), remove_labels=self.remove_labels.values())
        if self.state.currentIndex():
            e.fields["state"] = self.state.currentText()
        if self.plant_event.currentIndex():
            e.fields["plant_event"] = self.plant_event.currentIndex() == 1
        if self.priority.currentIndex():
            e.priority = self.priority.currentData()
        for key, (on, date) in self.dates.items():
            if on.isChecked():
                e.fields[key] = date.value()
        for key, (how, chips) in self.people.items():
            if how.currentIndex():
                setattr(e, key, ("add" if how.currentIndex() == 1 else "set", chips.values()))
        if self.parent_task in self.m.tasks:
            e.parent, e.parent_how = self.parent_task, "move" if self.parent_how.currentIndex() == 0 else "also"
        return e

    def refresh_preview(self) -> None:
        self._timer.stop()
        problem = self.problem()
        edit = self.edit()
        if problem:
            self.outcomes = []
            self.preview.setHtml(f'<p style="color:#b0261e">{esc(problem)}</p>')
        elif edit.empty:
            self.outcomes = []
            self.preview.setHtml('<p class="note">Set something above to change it on every ticked task. The preview shows what each '
                                 "task's status log would get.</p>")
        else:
            self.outcomes = self._preview_fn(edit)
            self.preview.setHtml(_preview_html(self.m, self.outcomes))
        self.apply_button.setEnabled(any(o.changes for o in self.outcomes))


class LabelMatchDialog(FormDialog):
    """A label's matching tasks (mods log round 1, M0014): open tasks that mention its keywords but don't have it. Tick the
    ones to label; nothing is labelled until Apply. ``apply(task_ids)`` adds the label to them."""

    def __init__(self, parent: QWidget | None, m: Model, label: str, matches: list[LabelMatch], apply: Callable[[list[str]], None]) -> None:
        super().__init__(parent)
        self.m, self.label, self._apply = m, label, apply
        self.setWindowTitle(f"Tasks for the label {label}")
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        keywords = next((lb.keywords for lb in m.labels if lb.name == label), [])
        note = QLabel(f"Open tasks whose title, description or current status mentions {', '.join(keywords) or label}, and that don't have "
                      f"the label {label} yet. A keyword can catch more than it should, so tick the ones to label. Nothing is labelled until "
                      "you click Apply.", objectName="hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.rows = RowTree()
        self.rows.set_columns(["Task"])
        self.rows.setHeaderHidden(True)
        self.rows.setRootIsDecorated(False)
        self.rows.ticked.connect(lambda *_: self._sync())
        self.rows.begin()
        for match in matches:
            found = "<br>".join(f'<span class="sub">{esc(f.field)}:</span> {esc(f.text[:f.start])}<b>{esc(f.text[f.start:f.end])}</b>'
                                f"{esc(f.text[f.end:])}" for f in match.found)
            where = esc(path_text(m, match.task) or "Top-level task")
            item = self.rows.add_row(None, ("task", match.task), [f'<b>{esc(m.task(match.task).title)}</b> <span class="sub">{where}</span><br>{found}'])
            self.rows.add_tick(item, False)
        self.rows.end()
        lay.addWidget(self.rows, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(Help("Ctrl+Enter applies."))
        for text, on in (("Tick all", True), ("Clear", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, on=on: self.tick_all(on))
            buttons.addWidget(b)
        buttons.addStretch()
        self.apply_button = QPushButton("Apply", objectName="primary")
        self.apply_button.clicked.connect(self.apply)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        self._sync()

    def save(self) -> None:
        self.apply()

    def changed(self) -> bool:
        return bool(self.ticked())

    def ticked(self) -> list[str]:
        from PySide6.QtCore import Qt

        return [item.data(0, Qt.ItemDataRole.UserRole)[1] for item in self.rows.items() if item.checkState(0) == Qt.CheckState.Checked]

    def tick_all(self, on: bool) -> None:
        for item in self.rows.items():
            self.rows.add_tick(item, on)
        self._sync()

    def _sync(self) -> None:
        n = len(self.ticked())
        self.apply_button.setEnabled(n > 0)
        self.apply_button.setText(f"Apply to {n} task{'s' if n != 1 else ''}" if n else "Apply")

    def apply(self) -> None:
        if self.ticked():
            self._apply(self.ticked())
            self.accept()
