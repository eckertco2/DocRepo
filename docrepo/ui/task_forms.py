"""The browse tool's task forms: Edit task, with every field on one page (mods log round 1, M0008, M0011), Edit selected
for several tasks at once (M0009), and a label's matching tasks (M0014).

Edit task reuses the capture window's fields and pickers, and saves through
``edits.edit_task``, so each change goes into the status log as "Browse tool".
An Update capture stays the way to make changes that come with a note. Edit
selected and the matching tasks change tasks through ``bulk``, with a preview
first.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from docrepo import quick, timeline
from docrepo.bulk import BulkEdit, LabelMatch, TaskOutcome, summary
from docrepo.db import RECURRENCES, STATES
from docrepo.detail import CSS, esc
from docrepo.model import Model
from docrepo.parse import Who
from docrepo.schedule import start_of
from docrepo.ui.style import STYLE
from docrepo.ui.task_picker import full_path, path_text
from docrepo.ui.tree_view import RowTree
from docrepo.ui.widgets import Chip, ChipPicker, DateField, FlowLayout, FormDialog, HoursField, InfoButton, Option, field

Options = Callable[[str, list[str]], list[Option]]
#: Opens the task picker under a widget; the callback gets the picked task's ID, or None.
PickTask = Callable[[QWidget, Callable[[str | None], None]], None]
LEAVE = "Leave as it is"


def people_chips(m: Model, ids: list[str]) -> list[Chip]:
    return [Chip(p, m.person_name(p)) for p in ids]


def chips_people(chips: ChipPicker) -> list[Who]:
    """A people picker's chips as Who's: an ID, or the name of someone to add to the people list."""
    return [Who(name=c.value) if c.new else Who(c.value) for c in chips.chips()]


class TaskEditDialog(FormDialog):
    """Edit task: a task's title, description, state, current status, parents (mods log round 2, M0040), labels, people and
    hours, dates, recurrence and flags."""

    def __init__(self, parent: QWidget | None, m: Model, task_id: str, labels: Options, people: Options, pick_task: PickTask | None = None,
                 reference_fields: Sequence[str] = (), today: date | None = None) -> None:
        super().__init__(parent)
        t = m.task(task_id)
        self.m, self.task_id, self._pick_task = m, task_id, pick_task
        self.today = today or date.today()
        self.parents: list[str] = list(m.parents_of(task_id))
        self.setWindowTitle(f"Edit task {task_id}")
        self.setObjectName("capture")
        self.setStyleSheet(STYLE)
        self.resize(640, 760)
        outer = QVBoxLayout(self)
        hint = QLabel("Each change goes into the task's status log as Browse tool. For a change that comes with a note, use Update "
                      "in the capture window instead.", objectName="hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget(objectName="capture")
        g = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.title = QLineEdit(t.title)
        g.addWidget(field("Title", self.title, "title"))
        self.description = QPlainTextEdit(t.description)
        self.description.setFixedHeight(96)
        g.addWidget(field("Description", self.description))
        self.state = QComboBox()
        self.state.addItems(list(STATES))
        self.state.setCurrentText(t.state)
        g.addWidget(field("State", self.state, "state"))
        self.status = QPlainTextEdit(t.current_status)
        self.status.setFixedHeight(56)
        g.addWidget(field("Current status", self.status, "status"))
        # Parents: a quick task is filed here, out of Quick tasks (mods log round 2, M0040).
        self.parents_box = QWidget()
        self.parents_layout = FlowLayout(self.parents_box, spacing=6)
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
        g.addWidget(field("Labels", self.labels, "labels"))
        self.inherit = QCheckBox("Inherit parent labels")
        self.inherit.setChecked(t.inherit_labels)
        inherited = list(dict.fromkeys(n for p in m.parents_of(task_id) for n, _ in m.labels_of(p)))
        row = QHBoxLayout()
        row.addWidget(self.inherit)
        if inherited:
            row.addWidget(QLabel("Its parents have: " + ", ".join(inherited), objectName="hint"), 1)
        row.addStretch()
        g.addLayout(row)

        grid = QGridLayout()
        self.leads = ChipPicker(people, "Search names and aliases", "Add “{}” to people")
        self.leads.set_chips(people_chips(m, t.leads))
        self.assignees = ChipPicker(people, "Search names and aliases", "Add “{}” to people")
        self.assignees.set_chips(people_chips(m, t.assignees))
        self.lead_hours, self.asg_hours = HoursField(), HoursField()
        self.lead_hours.set_value(t.lead_hours)
        self.asg_hours.set_value(t.assignee_hours)
        self.start, self.due, self.deadline, self.reminder, self.repeat = DateField(), DateField(), DateField(), DateField(), DateField()
        for w, value in ((self.start, start_of(t).isoformat()), (self.due, t.due), (self.deadline, t.deadline), (self.reminder, t.reminder),
                         (self.repeat, t.repeat_until)):
            w.set_value(value)
        self.deadline_desc = QLineEdit(t.deadline_desc or "")
        self.recurrence = QComboBox()
        self.recurrence.addItems(["No recurrence", *RECURRENCES])
        self.recurrence.setCurrentText(t.recurrence or "No recurrence")
        self.recurrence.currentIndexChanged.connect(self._sync)
        self.repeat_field = field("Repeat until", self.repeat, "repeatUntil")
        cells = [(field("Lead", self.leads, "leads"), 0, 0), (field("Assignees", self.assignees, "assignees"), 0, 1),
                 (field("Lead hours", self.lead_hours, "hours"), 1, 0), (field("Assignee hours", self.asg_hours), 1, 1),
                 (field("Start", self.start, "start"), 2, 0), (field("Due", self.due, "due"), 2, 1),
                 (field("Deadline", self.deadline, "deadline"), 3, 0), (field("Deadline description", self.deadline_desc, "deadlineDesc"), 3, 1),
                 (field("Reminder", self.reminder, "reminder"), 4, 0), (field("Recurrence", self.recurrence, "recurrence"), 4, 1),
                 (self.repeat_field, 5, 1)]
        for w, r, c in cells:
            grid.addWidget(w, r, c)
        g.addLayout(grid)
        # A date inside a plant event says so (release 5.9, mods log round 2, M0028).
        self.during = QLabel(objectName="hint")
        self.during.setWordWrap(True)
        g.addWidget(self.during)
        for w in (self.start, self.due, self.deadline):
            w.edited.connect(self._show_during)
        self._show_during()
        flags = QHBoxLayout()
        self.urgent, self.meeting, self.plant_event = QCheckBox("Urgent"), QCheckBox("Meeting"), QCheckBox("Plant event")
        self.urgent.setChecked(t.urgent)
        self.meeting.setChecked(t.meeting)
        self.plant_event.setChecked(t.plant_event)
        for box, key in ((self.urgent, "urgent"), (self.meeting, "meeting"), (self.plant_event, "plantEvent")):
            flags.addWidget(box)
            note = QLabel()
            flags.addWidget(InfoButton(key, note))
            g.addWidget(note)
        flags.addStretch()
        g.addLayout(flags)
        # Reference fields (release 5.9, M0034): a box for each one named in Settings.
        self.references: dict[str, QLineEdit] = {}
        if reference_fields:
            refs = QGridLayout()
            for i, name in enumerate(reference_fields):
                box = QLineEdit(t.references.get(name, ""))
                self.references[name] = box
                refs.addWidget(field(name, box, "references" if i == 0 else None), i // 2, i % 2)
            g.addLayout(refs)
        g.addStretch()

        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        footer = QHBoxLayout()
        footer.addWidget(QLabel(self.KEYS_HINT, objectName="hint"), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        outer.addLayout(footer)
        self._sync()
        self.mark_clean()
        self.title.setFocus()

    def _sync(self) -> None:
        self.repeat_field.setVisible(self.recurrence.currentIndex() > 0)

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
        return None

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
            "leads": chips_people(self.leads), "assignees": chips_people(self.assignees), "lead_hours": self.lead_hours.value(),
            "assignee_hours": self.asg_hours.value(), "start": self.start.value(), "due": self.due.value(), "deadline": self.deadline.value(),
            "deadline_desc": self.deadline_desc.text(), "reminder": self.reminder.value(), "recurrence": recurrence,
            "repeat_until": self.repeat.value() if recurrence else None, "urgent": self.urgent.isChecked(), "meeting": self.meeting.isChecked(),
            "plant_event": self.plant_event.isChecked(), "parents": list(self.parents),
            **({"references": {name: box.text() for name, box in self.references.items()}} if self.references else {}),
        }


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
        self.setStyleSheet(STYLE)
        self.resize(660, 780)
        outer = QVBoxLayout(self)
        hint = QLabel("Only what you set here changes; everything else stays as it is on each task. Each task gets its own status "
                      "log entries, as Browse tool. Check the preview, then Apply.", objectName="hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        form = QWidget(objectName="capture")
        g = QVBoxLayout(form)
        g.setContentsMargins(0, 0, 0, 0)

        own = list(dict.fromkeys(name for x in self.task_ids if x in m.tasks for name in m.task(x).labels))
        self.add_labels = ChipPicker(labels, "Search or add", "Create label “{}”")
        self.remove_labels = ChipPicker(lambda text, picked: [Option(n, n) for n in own if n not in picked and text.strip().lower() in n.lower()],
                                        "Labels the tasks have" if own else "None of them has a label of its own")
        grid = QGridLayout()
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

        outer.addWidget(QLabel("Preview", objectName="fieldLabel"))
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.document().setDefaultStyleSheet(CSS)
        outer.addWidget(self.preview, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(QLabel("Ctrl+Enter applies. Esc closes, asking first if you've set something.", objectName="hint"), 1)
        self.apply_button = QPushButton("Apply", objectName="primary")
        self.apply_button.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(cancel)
        outer.addLayout(buttons)
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
        self.setStyleSheet(STYLE)
        self.resize(640, 560)
        lay = QVBoxLayout(self)
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
        buttons.addWidget(QLabel("Ctrl+Enter applies.", objectName="hint"))
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
