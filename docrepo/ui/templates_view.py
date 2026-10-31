"""The Templates view (release 5.44; the task templates design, decisions 180 to 199): its list and pages in the browse
window's panes, and its forms: a row, Make tasks, New template and Save as template.

``TemplatesPane`` keeps it apart from the browse window, which only hands it the list, the detail pane's bar and the
``tplrow:`` links. Changes go through ``docrepo.templates``, and the browse window's ``_do`` says what they did. Since release
5.45 a change that reaches tasks shows what it would do first, in ``PreviewDialog``.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from docrepo import markup, template_pages, templates
from docrepo.db import RECURRENCES
from docrepo.detail import esc
from docrepo.edits import Outcome
from docrepo.model import Model
from docrepo.dates import long_date, to_date
from docrepo.pages import num
from docrepo.schedule import due_after
from docrepo.tasks import TaskError
from docrepo.templates import Choice, Library, Row, plural
from docrepo.ui import tokens
from docrepo.ui.dialogs import _Form
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK, Help
from docrepo.ui.rich_edit import FormatBar, RichEdit
from docrepo.ui.style import style_sheet
from docrepo.ui.task_forms import BAD_DURATION, MON_TO_FRI, HoursRow, PeoplePicker, PickTask, chips_people, days_valid, people_chips, typed_days
from docrepo.ui.task_picker import full_path
from docrepo.ui.widgets import Chip, ChipPicker, DateField, FormDialog, HoursField, Option, dialog_buttons, field, fit_dialog, section
from docrepo.views import TEMPLATES_NOTE

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

Options = Callable[[str, list[str]], list[Option]]
NO_REPEAT = "No recurrence"


def _hint(text: str) -> QLabel:
    label = QLabel(text, objectName="hint")
    label.setWordWrap(True)
    return label


class RowDialog(FormDialog):
    """A template row: Edit task's form with a task's own fields taken out, and Starting notes added (decision 182). State,
    current status, priority, dates and reference fields are each task's own."""

    def __init__(self, parent: QWidget | None, m: Model, row: Row | None, labels: Options, people: Options, heading: str, top: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(heading)
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.top = top
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
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

        self.title_box = QLineEdit(row.title if row else "")
        self.title_box.setPlaceholderText("Product trial" if top else "Pre-trial safety review")
        g.addWidget(field("Name" if top else "Title", self.title_box))
        self.description = QPlainTextEdit(row.description if row else "")
        self.description.setFixedHeight(72)
        g.addWidget(field("Description", self.description))
        self.labels = ChipPicker(labels, "Search or add", "Create label “{}”")
        self.labels.set_chips([Chip(name, name) for name in (row.labels if row else ())])
        g.addWidget(field("Labels", self.labels, "labels"))
        self.inherit = QCheckBox("Inherit parent labels")
        self.inherit.setChecked(row.inherit_labels if row else True)
        g.addWidget(self.inherit)

        section(g, "Length")
        self.duration = QLineEdit("" if not row or row.duration is None else str(row.duration))
        self.duration.setFixedWidth(64)
        self.duration.setAccessibleName("Duration in days")
        self.calendar = QCheckBox("Runs through weekends")
        self.calendar.setChecked(bool(row and row.calendar_days))
        self.calendar.setToolTip("Count every day, for its Due and where its hours land, not only workdays")
        self.length_box = QWidget()
        days = QHBoxLayout(self.length_box)
        days.setContentsMargins(0, 0, 0, 0)
        days.setSpacing(6)
        days.addWidget(self.duration)
        days.addWidget(QLabel("days", objectName="hint"))
        days.addSpacing(10)
        days.addWidget(self.calendar)
        days.addStretch()
        g.addWidget(field("Duration", self.length_box))
        g.addWidget(_hint("A template has no dates. Leave anything blank to fill it in on each task."))

        section(g, "People and hours")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self.leads = PeoplePicker(people, "Search names and aliases", "Add “{}” to people", "lead", lambda: self.lead_unit.total())
        self.assignees = PeoplePicker(people, "Search names and aliases", "Add “{}” to people", "assignee", lambda: self.asg_unit.total())
        self.lead_hours, self.asg_hours = HoursField(), HoursField()
        self.lead_unit = HoursRow(self.lead_hours, lambda: typed_days(self.duration), lambda: len(self.leads.chips()), self.leads.shares_text)
        self.asg_unit = HoursRow(self.asg_hours, lambda: typed_days(self.duration), lambda: len(self.assignees.chips()), self.assignees.shares_text)
        if row:
            self.leads.shares = {p: s for (r, p), s in row.involvement.items() if r == "lead"}
            self.assignees.shares = {p: s for (r, p), s in row.involvement.items() if r == "assignee"}
            self.leads.set_chips(people_chips(m, row.leads))
            self.assignees.set_chips(people_chips(m, row.assignees))
            self.lead_unit.set_stated(templates.stated(row, "lead_hours"))
            self.asg_unit.set_stated(templates.stated(row, "assignee_hours"))
        for w in (self.lead_hours, self.asg_hours):
            w.setFixedWidth(72)
        self.duration.textEdited.connect(lambda _: (self.lead_unit.show_line(), self.asg_unit.show_line()))
        self.leads.changed.connect(self.lead_unit.show_line)
        self.assignees.changed.connect(self.asg_unit.show_line)
        top_edge = Qt.AlignmentFlag.AlignTop  # the two labels stay level however many chips one box holds
        grid.addWidget(field("Lead", self.leads, "leads"), 0, 0, top_edge)
        grid.addWidget(field("Assignees", self.assignees, "assignees"), 0, 1, top_edge)
        grid.addWidget(field("Lead hours", self.lead_unit, "hours"), 1, 0, top_edge)
        grid.addWidget(field("Assignee hours", self.asg_unit), 1, 1, top_edge)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        g.addLayout(grid)

        section(g, "Starting notes")
        self.notes = RichEdit()
        self.notes.setMinimumHeight(96)
        self.notes.setPlaceholderText("Any text, or “[] ” at a line's start for a checklist line")
        if row and row.notes:
            self.notes.set_value(row.notes, True)
        bar = FormatBar(self.notes)
        editor = QFrame(objectName="editor")  # as the capture window's: one outlined box, its buttons along the top
        el = QVBoxLayout(editor)
        el.setContentsMargins(1, 1, 1, 1)
        el.setSpacing(0)
        bar.layout().setContentsMargins(4, 2, 4, 2)
        el.addWidget(bar)
        el.addWidget(self.notes, 1)
        if not LOOK.classic:
            bar.show_on_use(editor)
        g.addWidget(editor)
        g.addWidget(_hint("Copied onto each new task's notes page. The page is the task's own from then on, so changes here reach only new tasks."))

        self.more_button = QPushButton("More options ▸", objectName="moreLink")
        g.addWidget(self.more_button)
        self.more = QWidget()
        ml = QHBoxLayout(self.more)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(16)
        self.urgent, self.meeting, self.plant_event = QCheckBox("Urgent"), QCheckBox("Meeting"), QCheckBox("Plant event")
        self.recurrence = QComboBox()
        self.recurrence.addItems([NO_REPEAT, *RECURRENCES])
        self.recurrence.setFixedWidth(200)
        self.recurrence.setAccessibleName("Recurrence")
        self.recurrence.currentIndexChanged.connect(self._sync_routine)
        if row:
            self.urgent.setChecked(row.urgent)
            self.meeting.setChecked(row.meeting)
            self.plant_event.setChecked(row.plant_event)
            self.recurrence.setCurrentText(row.recurrence or NO_REPEAT)
        for w in (self.urgent, self.meeting, self.plant_event, self.recurrence):
            ml.addWidget(w)
        ml.addStretch()
        g.addWidget(self.more)
        open_more = bool(row and (row.urgent or row.meeting or row.plant_event or row.recurrence))
        self.more.setVisible(open_more)
        self.more_button.setText("More options ▾" if open_more else "More options ▸")
        self.more_button.clicked.connect(self._toggle_more)
        g.addStretch()

        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        outer.addLayout(dialog_buttons(self, "Save", self._accept, self.reject, Help(self.KEYS_HINT)))
        self._sync_routine()
        self.mark_clean()
        self.title_box.setFocus()
        fit_dialog(self, body, 608)

    def _sync_routine(self) -> None:
        """A row that repeats has no Duration or rate: its hours are for each time."""
        routine = self.recurrence.currentIndex() > 0
        self.length_box.parentWidget().setVisible(not routine)
        self.lead_unit.set_routine(routine)
        self.asg_unit.set_routine(routine)

    def _toggle_more(self) -> None:
        on = self.more.isHidden()
        self.more.setVisible(on)
        self.more_button.setText("More options ▾" if on else "More options ▸")

    def save(self) -> None:
        self._accept()

    def snapshot(self) -> dict[str, Any]:
        return self.values()

    def problem(self) -> str | None:
        if not self.title_box.text().strip():
            return "A template needs a name." if self.top else "A row needs a title."
        for w, name in ((self.lead_hours, "Lead hours"), (self.asg_hours, "Assignee hours")):
            if not w.is_valid():
                return f"{name} isn't a number of hours."
        return None if days_valid(self.duration) else BAD_DURATION

    def _accept(self) -> None:
        problem = self.problem()
        if problem:
            self.error.setText(problem)
            self.error.show()
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        """The form's values, as ``templates`` takes them. Its starting notes are always markup."""
        text, formatted = self.notes.value()
        hours = {}
        for unit, total, rate in ((self.lead_unit, "lead_hours", "lead_per_day"), (self.asg_unit, "assignee_hours", "assignee_per_day")):
            n = unit.number()
            hours.update({rate: n, total: None} if unit.per_day() and n is not None else {total: n, rate: None})
        return {"title": self.title_box.text(), "description": self.description.toPlainText(), "labels": self.labels.values(),
                "inherit_labels": self.inherit.isChecked(), "leads": chips_people(self.leads), "assignees": chips_people(self.assignees),
                "involvement": {**self.leads.involvement(), **self.assignees.involvement()},
                **hours, "duration": typed_days(self.duration), "calendar_days": self.calendar.isChecked(),
                "urgent": self.urgent.isChecked(), "meeting": self.meeting.isChecked(), "plant_event": self.plant_event.isChecked(),
                "recurrence": self.recurrence.currentText() if self.recurrence.currentIndex() else None,
                "notes": text if formatted else markup.escape(text)}


class MakeRow:
    """One row of Make tasks' dialog: its Start, its days, and its people, in one box as the mock has them, with the Due and
    hours they come to. A person added here is an assignee; one taken off leaves whichever role they had. Days kept as offered
    stay linked to the template; days typed differently are the task's own."""

    def __init__(self, row: Row, has_rows: bool, m: Model, people: Options, workdays: Collection[int]) -> None:
        self.row, self.workdays = row, workdays
        self.start = DateField()
        self.start.line.setAccessibleName(f"Start of {row.title}")
        self.days = QLineEdit("" if row.duration is None else str(row.duration))
        self.days.setAccessibleName(f"Days of {row.title}")
        self.days.setFixedWidth(48)
        self.due = _hint("")
        self.hours = _hint("")
        self.has_start = not row.recurrence and (not has_rows or row.duration is not None or templates.stated(row, "lead_hours") is not None
                                                 or templates.stated(row, "assignee_hours") is not None)
        if row.recurrence:
            self.has_start = not has_rows
        self.start.edited.connect(self.sync)
        self.days.textEdited.connect(lambda _: self.sync())
        self.people = ChipPicker(people, "Add")
        self.people.setAccessibleName(f"People on {row.title}")
        self.people.edit.setMinimumWidth(60)
        self.people.set_chips([Chip(p, m.person_name(p) + next((f" {s}%" for (_, x), s in row.involvement.items() if x == p), ""))
                               for p in dict.fromkeys([*row.leads, *row.assignees])])
        self.sync()

    def sync(self) -> None:
        """The Due a Start and days come to, and the hours a rate comes to over them."""
        days, row = typed_days(self.days), self.row
        due = ""
        if days and self.start.is_valid() and self.start.value():
            day = to_date(self.start.value())
            due = long_date(due_after(day, days, self.workdays, row.calendar_days), day)
        self.due.setText(due)
        rate = row.assignee_per_day if row.assignee_per_day is not None else row.lead_per_day
        if rate is None:
            self.hours.setText(templates.summary(replace(row, duration=None)))
        elif days:
            self.hours.setText(f"{num(rate)} h a day = {num(round(rate * days, 2))} h")
        else:
            self.hours.setText(f"{num(rate)} h a day")

    def choice(self) -> Choice:
        chosen = self.people.values()
        leads = [p for p in self.row.leads if p in chosen]
        assignees = [p for p in self.row.assignees if p in chosen]
        assignees += [p for p in chosen if p not in leads and p not in assignees]
        return Choice(self.start.value() if self.has_start else None, leads, assignees, typed_days(self.days))


class MakeTasksDialog(FormDialog):
    """Make tasks: the top task's name, where it goes, and a line a task with its Start and people. Anything left blank
    stays blank."""

    def __init__(self, parent: QWidget | None, m: Model, lib: Library, row_id: int, people: Options, pick_task: PickTask,
                 workdays: Collection[int] = MON_TO_FRI) -> None:
        super().__init__(parent)
        self.m, self._pick_task = m, pick_task
        self.under: str | None = None
        root = lib.rows[row_id]
        walked = lib.walk(row_id)
        path = " › ".join(x.title for x in lib.path(row_id))
        self.setWindowTitle(f"Make tasks from {path}")
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        self.name = QLineEdit("" if root.parent is None else root.title)
        self.name.setPlaceholderText("Trial 5: gloss finish")
        self.under_button = QPushButton()
        self.under_button.clicked.connect(lambda: self._pick_task(self.under_button, self.set_under))
        head = QGridLayout()
        head.setHorizontalSpacing(16)
        head.addWidget(field("Name", self.name), 0, 0)
        head.addWidget(field("Under", self.under_button), 0, 1)
        head.setColumnStretch(0, 1)
        head.setColumnStretch(1, 1)
        outer.addLayout(head)
        self._draw_under()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(objectName="capture")
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for c, text in enumerate(("Task", "Start", "Days", "Due", "Hours", "People")):
            grid.addWidget(QLabel(text, objectName="fieldLabel"), 0, c)
        self.lines: list[MakeRow] = []
        for i, (row, depth) in enumerate(walked, start=1):
            line = MakeRow(row, bool(lib.children(row.id)), m, people, workdays)
            self.lines.append(line)
            title = QLabel(row.title)
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setContentsMargins(depth * 14, 0, 0, 0)
            title.setToolTip(row.title)
            if i == 1:  # the top task, in bold, named as it's typed above
                font = title.font()
                font.setBold(True)
                title.setFont(font)
                self.name.textChanged.connect(lambda text, t=title, r=row: t.setText(text.strip() or r.title))
            grid.addWidget(title, i, 0, Qt.AlignmentFlag.AlignTop)
            if line.has_start:
                grid.addWidget(line.start, i, 1, Qt.AlignmentFlag.AlignTop)
                if not row.recurrence:
                    grid.addWidget(line.days, i, 2, Qt.AlignmentFlag.AlignTop)
                    grid.addWidget(line.due, i, 3, Qt.AlignmentFlag.AlignTop)
            else:
                grid.addWidget(_hint("–"), i, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(line.hours, i, 4, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(line.people, i, 5, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(5, 4)
        grid.setRowStretch(len(walked) + 1, 1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(_hint("Anything left blank stays blank. Undated tasks wait under No dates or hours, and in the timeline's Plan mode. Days kept as "
                              "offered stay linked to the template."))
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        n = len(walked)
        outer.addLayout(dialog_buttons(self, f"Make {n} task{'s' if n != 1 else ''}", self._accept, self.reject, Help("Ctrl+Enter makes them.")))
        self.commit_button.setMinimumWidth(120)
        self.mark_clean()
        self.name.setFocus()
        fit_dialog(self, body, 940, 240)

    def set_under(self, task_id: str | None) -> None:
        self.under = task_id
        self._draw_under()

    def _draw_under(self) -> None:
        self.under_button.setText(f"{full_path(self.m, self.under)}  ▾" if self.under else "None: a top-level task  ▾")

    def save(self) -> None:
        self._accept()

    def snapshot(self) -> Any:
        return [self.name.text(), self.under, [(x.start.line.text(), x.days.text(), x.people.values()) for x in self.lines]]

    def problem(self) -> str | None:
        if not self.name.text().strip() and self.lines[0].row.parent is None:
            return "Give the new task a name, such as Trial 5: gloss finish."
        for x in self.lines:
            if x.has_start and not x.start.is_valid():
                return f"The Start of {x.row.title} isn't a date. Use YYYY-MM-DD."
            if not days_valid(x.days):
                return f"{BAD_DURATION} ({x.row.title})"
        return None

    def _accept(self) -> None:
        problem = self.problem()
        if problem:
            self.error.setText(problem)
            self.error.show()
            return
        self.accept()

    def choices(self) -> dict[int, Choice]:
        return {x.row.id: x.choice() for x in self.lines}


class NewTemplateDialog(_Form):
    """A new template: its name, and then its subtasks."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent, "New template")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Product trial")
        self.form.addRow("Name", self.name)
        self.form.addRow(_hint("Then add its subtasks. Or use Save as template on a task you've already built, from its More menu."))
        self.check = lambda: None if self.name.text().strip() else "A template needs a name."
        self.mark_clean()


class SaveAsDialog(_Form):
    """Save as template (decision 195): from a task and what's under it, linked to it by default."""

    def __init__(self, parent: QWidget | None, name: str, count: int, already: str | None) -> None:
        super().__init__(parent, "Save as template")
        self.name = QLineEdit(name)
        self.name.selectAll()
        self.link = QCheckBox("Link this tree to the new template")
        self.link.setChecked(True)
        self.form.addRow("Name", self.name)
        self.form.addRow(_hint(f"Takes {count} task{'s' if count != 1 else ''}. Dates, state, status, notes and captures aren't carried over."))
        self.form.addRow(self.link)
        moved = f" It already came from {already}, and linking moves it to this one." if already else ""
        self.form.addRow(_hint(f"Linked, these tasks follow the template, as any tree made from it does.{moved}"))
        self.check = lambda: None if self.name.text().strip() else "A template needs a name."
        self.mark_clean()


@dataclass
class PreviewEntry:
    """A task or a tree in a preview. ``lines`` say what ticking it does, and ``off_lines`` what unticking it does (the same
    words, dimmed, when it's None). One not ``enabled`` can't be ticked."""

    key: str
    title: str
    lines: list[str]
    state: str = ""
    ticked: bool = True
    enabled: bool = True
    off_lines: list[str] | None = None


class PreviewDialog(FormDialog):
    """What a change to a template would do, before it's made, in one of its three forms (decisions 186 and 188): a field
    changed, a subtask added, or a subtask taken out. Each lists tasks or trees with ticks. ``commit`` words the button for
    what's ticked, ``total`` a line under the list, and ``folded`` is a folded line for what isn't changing: its words, and
    its entries. Closing it is Back: nothing was changed, so it never asks."""

    def __init__(self, parent: QWidget | None, heading: str, lead: str, entries: list[PreviewEntry], hint: str, commit: Callable[[list[str]], str],
                 back: str = "Back", folded: tuple[str, list[str]] | None = None, total: Callable[[list[str]], str] | None = None) -> None:
        super().__init__(parent)
        self.entries, self._commit, self._total = entries, commit, total
        self.setWindowTitle(heading)
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        title = QLabel(heading, objectName="heading")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        outer.addWidget(title)
        if lead:
            words = QLabel(lead)
            words.setWordWrap(True)
            outer.addWidget(words)
        self.ticks: dict[str, QCheckBox] = {}
        self._lines: dict[str, QLabel] = {}
        body = QWidget(objectName="capture")
        g = QVBoxLayout(body)
        g.setContentsMargins(0, 0, 8, 0)
        g.setSpacing(6)
        for e in entries:
            g.addWidget(self._row(e))
        g.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        scroll.setMinimumHeight(min(len(entries), 3) * 62)  # three rows stay in sight, however little room the rest leaves
        if entries:
            outer.addWidget(scroll, 1)
        self.fold_button: QPushButton | None = None
        if folded:
            words, items = folded
            self.fold_button = QPushButton(f"{words} ▸", objectName="moreLink")
            self.folded = _hint("\n".join(items))
            self.folded.setTextFormat(Qt.TextFormat.PlainText)
            self.folded.hide()
            self.fold_button.clicked.connect(lambda: self._toggle_folded(words))
            outer.addWidget(self.fold_button, 0, Qt.AlignmentFlag.AlignLeft)
            outer.addWidget(self.folded)
        self.total_line = QLabel()
        font = self.total_line.font()
        font.setBold(True)
        self.total_line.setFont(font)
        outer.addWidget(self.total_line)
        if hint:
            outer.addWidget(_hint(hint))
        outer.addLayout(dialog_buttons(self, "", self.accept, self.reject, cancel=back))
        self.commit_button.setMinimumWidth(180)
        self._sync()
        fit_dialog(self, body, 640, 300)

    def _row(self, e: PreviewEntry) -> QFrame:
        row = QFrame(objectName="fileRow")
        grid = QGridLayout(row)
        grid.setContentsMargins(10, 6, 10, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        tick = QCheckBox(e.title.replace("&", "&&"))
        tick.setChecked(e.ticked)
        tick.setEnabled(e.enabled)
        tick.toggled.connect(lambda _: self._sync())
        self.ticks[e.key] = tick
        grid.addWidget(tick, 0, 0)
        if e.state:
            grid.addWidget(_hint(e.state), 0, 1, Qt.AlignmentFlag.AlignRight)
        lines = _hint("")
        lines.setTextFormat(Qt.TextFormat.PlainText)
        lines.setContentsMargins(26, 0, 0, 0)
        self._lines[e.key] = lines
        grid.addWidget(lines, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        return row

    def _toggle_folded(self, words: str) -> None:
        on = self.folded.isHidden()
        self.folded.setVisible(on)
        self.fold_button.setText(f"{words} {'▾' if on else '▸'}")
        room = self.folded.sizeHint().height() + 12  # the window grows to hold it, so the list keeps its room
        self.resize(self.width(), self.height() + (room if on else -room))

    def _sync(self) -> None:
        ticked = self.ticked()
        for e in self.entries:
            on = e.key in ticked
            label = self._lines[e.key]
            label.setText("\n".join(e.lines if on or e.off_lines is None else e.off_lines))
            label.setEnabled(on or e.off_lines is not None)
        self.commit_button.setText(self._commit(ticked))
        words = self._total(ticked) if self._total else ""
        self.total_line.setText(words)
        self.total_line.setVisible(bool(words))

    def ticked(self) -> list[str]:
        return [key for key, tick in self.ticks.items() if tick.isChecked()]

    def unticked(self) -> list[str]:
        return [e.key for e in self.entries if e.enabled and not self.ticks[e.key].isChecked()]

    def save(self) -> None:
        self.accept()

    def changed(self) -> bool:
        return False


class TemplatesPane:
    """The Templates view, in the browse window's list and detail panes."""

    def __init__(self, browse: BrowseWindow) -> None:
        self.w = browse

    def library(self) -> Library:
        return Library(self.w.conn)

    def exists(self, item: str) -> bool:
        return item.isdigit() and int(item) in self.library().rows

    def first(self) -> tuple[str, str] | None:
        """What the view selects when it opens: the first template."""
        lib = self.library()
        live = lib.live()
        return ("tplrow", str(live[0].top)) if live else None

    # ---- the list pane ----
    def render_list(self) -> None:
        w, lib = self.w, self.library()
        live = lib.live()
        w._set_head("Templates", TEMPLATES_NOTE, f"{len(live)} template{'s' if len(live) != 1 else ''}" if live else "")
        w._button("New template", self.new_template, tip="A new template, with its name. Then add its subtasks.")
        w.tree.set_columns(["Template", ""], [0, 130])
        for t in live:
            n = len([c for c in lib.trees(t.id) if c.task in w.model().tasks and not w.model().task(c.task).discarded])
            used = f"{n} tree{'s' if n != 1 else ''}" if n else "Not used yet"
            item = w.tree.add_row(None, ("tplrow", str(t.top)), [f"<b>{esc(lib.name(t.id))}</b>", f'<p align="right" class="sub">{esc(used)}</p>'])
            self._add_rows(lib, t.top, item)
            item.setExpanded(True)
        if not live:
            w.tree.add_row(None, None, ['<span class="sub">No templates yet. New template starts one, or use Save as template on a task, from '
                                        'its More menu.</span>'], selectable=False, span=True)

    def _add_rows(self, lib: Library, row_id: int, parent) -> None:
        for child in lib.children(row_id):
            item = self.w.tree.add_row(parent, ("tplrow", str(child.id)), [esc(child.title), f'<p align="right" class="sub">{esc(templates.summary(child))}</p>'])
            self._add_rows(lib, child.id, item)
            item.setExpanded(True)

    def discarded(self) -> list[tuple[str, str, str, str, str, str]]:
        """The discarded templates, for the Discarded view."""
        lib = self.library()
        return [("tplrow", str(t.top), lib.name(t.id), f"Template · {len(lib.walk(t.top))} rows", t.discard_reason or "", t.discarded)
                for t in lib.templates.values() if t.discarded]

    # ---- the detail pane ----
    def page(self, item: str) -> str:
        return template_pages.row_page(self.library(), self.w.model(), int(item), self.w.today())

    def actions(self, item: str) -> None:
        w, lib, row_id = self.w, self.library(), int(item)
        row = lib.rows[row_id]
        template = lib.templates[row.template]
        if template.discarded:
            w._action("Bring back", lambda: self.bring_back(template.id), "Restore it to Templates, as it was", primary=True)
            return
        top = template.top == row_id
        make = w._action("Make tasks" if top else "Make tasks from here", lambda: self.make(row_id),
                         "Copy this template into the task tree" if top else "Copy this row and what's under it into the task tree", primary=True)
        if not LOOK.classic:
            make.setIcon(icon("add", tokens.colour("on_accent")))
        w._action("Add subtask", lambda: self.add_subtask(row_id), "A new row under this one", icon_name="task")
        w._action("Edit", lambda: self.edit_row(row_id), "Change what this row fills", icon_name="edit")
        if top:
            w._action("Discard…", lambda: self.discard(template.id), "Hide this template. Its tasks keep their values, and nothing is deleted.")
            return
        menu = QMenu(w)
        beside = lib.children(row.parent)
        at = [x.id for x in beside].index(row_id)
        menu.addAction("Move up", lambda: self.shift(row_id, -1)).setEnabled(at > 0)
        menu.addAction("Move down", lambda: self.shift(row_id, 1)).setEnabled(at < len(beside) - 1)
        under = menu.addMenu("Move under")
        below = {x.id for x, _ in lib.walk(row_id)}
        for x, depth in lib.walk(template.top):
            if x.id not in below and x.id != row.parent:
                under.addAction("    " * depth + x.title, lambda p=x.id: self.reparent(row_id, p))
        under.setEnabled(bool(under.actions()))
        w._action("Move", tip="Only trees made afterwards see a move", menu=menu)
        w._action("Take out…", lambda: self.take_out(row_id), "Take this row out of the template. Tasks made from it stay.")

    def open_row(self, item: str) -> None:
        """A ``tplrow:`` link: the row, in Templates, or in Discarded while its template is discarded."""
        if not self.exists(item):
            return
        lib = self.library()
        self.w.view = "discarded" if lib.template_of(int(item)).discarded else "templates"
        self.w.select("tplrow", item, update_list=True)

    # ---- forms ----
    def _dialog(self, row: Row | None, heading: str, top: bool = False) -> RowDialog:
        dialog = RowDialog(self.w, self.w.model(), row, self.w._label_options, self.w._people_options, heading, top)
        self.w._row_dialog = dialog  # kept, so tests can reach it
        return dialog

    def new_template(self) -> None:
        w = self.w
        dialog = NewTemplateDialog(w)
        w._new_template_dialog = dialog
        if not w.run_dialog(dialog):
            return
        made: list[int] = []

        def change():
            made.append(templates.new_template(w.conn, dialog.name.text(), w._now()))
            return Outcome("Saved. Now add its subtasks.")
        if w._do(change):
            self.open_row(str(made[0]))

    def _preview(self, dialog: PreviewDialog) -> bool:
        self.w._preview_dialog = dialog  # kept, so tests can reach it
        return self.w.run_dialog(dialog)

    def _field_preview(self, plan: templates.RowPlan) -> PreviewDialog:
        """A field changed (decision 186): each task it reaches, ticked, with a total for the hours; those left alone folded."""
        items = {i.task: i for i in plan.items}

        def total(ticked: list[str]) -> str:
            before, after = sum(items[k].work_before for k in ticked), sum(items[k].work_after for k in ticked)
            return f"Work across these tasks: {num(before)} h → {num(after)} h" if before != after else ""

        closed = sum(1 for x in plan.not_changing if x.why == "closed")
        discarded = sum(1 for x in plan.not_changing if x.why == "discarded")
        own = sum(1 for x in plan.not_changing if x.why == "own")
        words = [f"{closed} closed" if closed else "", f"{discarded} discarded" if discarded else "",
                 f"{own} with {'its' if own == 1 else 'their'} own value" if own else ""]
        folded = (f"Not changing: {', '.join(x for x in words if x)}", [f"{x.tree}: {x.text}" for x in plan.not_changing]) if plan.not_changing else None
        return PreviewDialog(self.w, f"This change reaches {plural(len(plan.items), 'task')}",
                             f"<b>{esc(plan.title)}</b>: {esc(', '.join(plan.lines))}",
                             [PreviewEntry(i.task, i.tree, i.lines, i.state) for i in plan.items],
                             f"Unticked tasks keep their value and stop following. Each change goes in the task's status log, as Template: {plan.name}.",
                             lambda ticked: f"Apply to {plural(len(ticked), 'task')}" if ticked else "Save, changing no tasks", folded=folded, total=total)

    def _add_preview(self, plan: templates.AddPlan) -> PreviewDialog:
        """A subtask added (decision 188): each open tree with its progress, ticked."""
        folded = (f"Not offered: {plural(len(plan.closed_trees), 'closed tree')}", plan.closed_trees) if plan.closed_trees else None
        carrying = f", with {plan.summary}" if plan.summary else ""
        return PreviewDialog(self.w, f"Add “{plan.title}” to existing trees?", "",
                             [PreviewEntry(t.task, t.title, [f"{t.closed} of {t.total} closed"], t.state) for t in plan.trees],
                             f"It arrives undated, under {plan.parent_title}{carrying}, and its fields linked. Trees you untick don't get it. New trees always do.",
                             lambda ticked: f"Add to {plural(len(ticked), 'tree')}" if ticked else "Add to new trees only", folded=folded)

    def add_subtask(self, parent: int) -> None:
        """Add a subtask: its form, then, when trees have its parent, which of them get it. Back returns to the form as typed."""
        w, lib = self.w, self.library()
        dialog = self._dialog(None, f"Add a subtask under {lib.rows[parent].title}")
        while w.run_dialog(dialog):
            try:
                plan = templates.preview_new_row(w.conn, parent, dialog.values(), w._now())
            except (TaskError, ValueError, sqlite3.Error) as e:
                w.say(str(e), error=True)
                return
            left: list[str] = []
            if plan.trees:
                pv = self._add_preview(plan)
                if not self._preview(pv):
                    continue
                left = pv.unticked()
            made: list[int] = []

            def change():
                row_id, out = templates.new_row(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, parent, dialog.values(), w._now(), left)
                made.append(row_id)
                return out
            if w._do(change):
                w.select("tplrow", str(made[0]), update_list=True)
            return

    def edit_row(self, row_id: int) -> None:
        """Edit a row: its form, then, when it reaches any task, the preview (decision 186). Back returns to the form as typed."""
        w, lib = self.w, self.library()
        row = lib.rows[row_id]
        top = row.parent is None
        dialog = self._dialog(row, "Edit template" if top else "Edit template row", top)
        while w.run_dialog(dialog):
            try:
                plan = templates.preview_row(w.conn, w.ctx.settings, row_id, dialog.values(), w._now())
            except (TaskError, ValueError, sqlite3.Error) as e:
                w.say(str(e), error=True)
                return
            left: list[str] = []
            if plan.items:
                pv = self._field_preview(plan)
                if not self._preview(pv):
                    continue
                left = pv.unticked()
            w._do(lambda: templates.save_row(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, row_id, dialog.values(), w._now(), left), ("tplrow", str(row_id)))
            return

    def make(self, row_id: int) -> None:
        w, lib = self.w, self.library()
        dialog = MakeTasksDialog(w, w.model(), lib, row_id, w._people_options, lambda anchor, picked: w._pick_task(anchor, picked, ("None", "A top-level task")),
                                 w._workdays())
        w._make_dialog = dialog
        if not w.run_dialog(dialog):
            return
        made: list[str] = []

        def change():
            ids, out = templates.make(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, row_id, dialog.name.text(), dialog.under, dialog.choices(), w._now())
            made.extend(ids)
            return out
        if w._do(change):
            w.open.update(made)
            w.go_task(made[0])

    def take_out(self, row_id: int) -> None:
        """Take a row out (decision 188): its copies stay and stop following, and those not started with nothing on them are
        offered for discarding, ticked."""
        w, lib = self.w, self.library()
        row = lib.rows[row_id]
        try:
            plan = templates.preview_remove(w.conn, row_id)
        except TaskError as e:
            w.say(str(e), error=True)
            return
        stays = "Stays, no longer following."
        entries = [PreviewEntry(c.task, c.tree, ["Discarded. Bring back restores it."] if c.can else [f"{stays} It's started or has things on it."], c.state,
                                ticked=c.can, enabled=c.can, off_lines=[stays]) for c in plan.copies]
        lead = ("DocRepo doesn't delete tasks. These copies stay and stop following, unless you discard the ones not started with nothing on them."
                if entries else "No tasks were made from it.")
        pv = PreviewDialog(w, f"Take “{plan.title}” out of the template?", lead, entries,
                           f"This takes out what's under it too: {plan.rows} rows." if plan.rows > 1 else "", lambda _: "Take it out", back="Cancel")
        if self._preview(pv):
            w._do(lambda: templates.take_out(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, row_id, w._now(), pv.ticked()), ("tplrow", str(row.parent)))

    # ---- a task's link: Edit task's marks, and Detach (decision 184) ----
    def link_of(self, task_id: str) -> templates.TaskLink | None:
        return templates.task_link(self.w.conn, task_id)

    def after_form(self, task_id: str, dialog) -> None:
        """Edit task closed for its From template line: to open the row, or to detach."""
        after = getattr(dialog, "after", None)
        if after and after[0] == "row":
            self.open_row(str(after[1]))
        elif after and after[0] == "detach":
            self.detach(task_id)

    def detach(self, task_id: str) -> None:
        """Detach from template: all of a task's links end, and its values stay."""
        w = self.w
        name = w.model().origins[task_id].template if task_id in w.model().origins else None
        if name and w.confirm("Detach from template", f"Detach {w.model().task(task_id).title} from {name}? Its values stay, and it won't follow {name} any more."):
            w._do(lambda: templates.detach(w.conn, w.ctx.data_root, w.ctx.fs, task_id, w._now()))

    def shift(self, row_id: int, step: int) -> None:
        self.w._do(lambda: templates.shift_row(self.w.conn, row_id, step), ("tplrow", str(row_id)))

    def reparent(self, row_id: int, parent: int) -> None:
        self.w._do(lambda: templates.reparent_row(self.w.conn, row_id, parent) or True, ("tplrow", str(row_id)))

    def discard(self, template_id: int) -> None:
        w, lib = self.w, self.library()
        name = lib.name(template_id)
        reason = w.ask_reason("Discard template", f"Discard {name}? It's hidden from Templates and kept in the Discarded view, where Bring back "
                                                  "restores it. Its tasks keep their values. Nothing is deleted.\n\nWhy?")
        if reason is None:
            return

        def change():
            templates.set_discarded(w.conn, template_id, reason.strip() or "Made by mistake", w._now())
            return Outcome(f"{name} is discarded. Its tasks keep their values.")
        if w._do(change):
            w.sel = self.first()
            w.render_all()

    def bring_back(self, template_id: int) -> None:
        w, lib = self.w, self.library()

        def change():
            templates.set_discarded(w.conn, template_id, None, w._now())
            return Outcome(f"{lib.name(template_id)} is back in Templates.")
        if w._do(change):
            self.open_row(str(lib.templates[template_id].top))

    def save_as(self, task_id: str) -> None:
        """Save as template, from a task's More menu."""
        w = self.w
        m = w.model()
        count = len([x for x in {task_id, *m.descendants_of(task_id)} if not m.task(x).discarded])
        origin = m.origins.get(task_id)
        dialog = SaveAsDialog(w, m.task(task_id).title, count, origin.template if origin else None)
        w._save_as_dialog = dialog
        if not w.run_dialog(dialog):
            return
        made: list[int] = []

        def change():
            top, out = templates.save_as(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, task_id, dialog.name.text(), dialog.link.isChecked(), w._now())
            made.append(top)
            return out
        if w._do(change):
            self.open_row(str(made[0]))
