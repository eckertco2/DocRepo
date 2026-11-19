"""The Log progress window (release 5.139; the design workspace's ``docs/mods/email-progress-plan.md``, decisions 580 to 598,
and its mock; release 5.155, ``docs/mods/log-progress-choices-plan.md``, decisions 695 to 697, and its mock).

A window of its own, on top while it's open, from the Log progress hotkey, the Execution wheel's NE (``progress.log``),
the status card's **Log progress…**, a tick on a Today task (release 5.166) or the state menu's **Waiting on a reply…**
(5.166). At the top, the email it's for: the draft in front in Outlook when the hotkey was pressed (decision 584), or
"No email in front" (decision 592), where an email selected in Outlook can be attached (5.166). Then, in the order they're
read:
- **Task** (decision 585): from the email's conversation, "from conversation", else the ``#`` list (the shared
  ``TaskPicker``), which opens by itself when no task is known;
- **What you did** (decision 586): one line, typed, the task's current status;
- **State** (decision 695, since 5.155): a dropdown of ``progress.STATES``, In progress, Waiting on a reply, Parked and
  Closed, opening on Waiting on a reply when Waiting on has people, else In progress; the line under it says what Enter
  does to the task's state;
- **Waiting on** (decision 587): people chips, from the email's To where its copy gave it, a name typed from People;
- **Today** (release 5.166, decision 757, ``ui.back_row``): Back on Today, one row in place of 5.139's Follow up and
  5.155's Today: Stays or Done for today when the task is on Today, None when it isn't, and Back: Tomorrow to 1 month or
  Other…, Later's choices. With a wait the last choice is remembered and comes first.

State is kept in step with Waiting on (decision 695): another state empties Waiting on, the row dimmed, with "Pick Waiting
on a reply to wait on someone"; a person added picks Waiting on a reply, and the last one taken away picks In progress;
Waiting on a reply picked with nobody takes the email's To people back, or puts the cursor in Waiting on. With Closed the
Today row is off.

Enter keeps it all (``docrepo.progress.log_progress``) and then, for a draft in its own window under decision 590 A,
sends it; an inline reply, or a send Outlook refuses, comes back to the front for the owner to send. Esc closes it,
keeping nothing. ``ui.wheels`` keeps one window, as it keeps the quick summary.

Since release 5.164 (the design workspace's ``docs/mods/log-progress-whole-plan.md``, decisions 750 to 754):
- the draft is sent with nothing set on it first (750), and once sent, or shown, the window holds nothing of Outlook's;
  the kept draft is marked as sent by DocRepo just before, so nothing reads it on its way out (751);
- Enter checks, keeps, hides the window, and only then asks Outlook, so a prompt of Outlook's never sits under it (752);
- Enter always answers (753): in Waiting on it adds the person typed, or with the box empty logs; on Cancel it cancels;
  what stops a save is said by its row in the caution colour, with the cursor put there; any other error is caught and
  said ("Nothing was kept: the database is busy. Try again."); while it runs the button says "Logging…" and takes no
  second press;
- all or nothing (754): when the Update is kept and the rest isn't, it says so, and the next Enter keeps only the rest.

Since release 5.166 (the same plan, decisions 755 and 757 to 762):
- **Dates and reminder…** (758), a quiet link at the lower left, opens Edit task at More options for the task; closing it
  comes back here, the Today row reading the Reminder as it now is. It's Edit task's form, not a second editor of dates;
- **Attach the selected email** (759, Alt+E), with no draft in front: the one email selected in Outlook, kept on the
  Update; its subject and sender in the email line, with a cross to take it off; the task from its conversation when
  none is picked;
- **Log, then next…** (761, Ctrl+Enter) logs as Enter does, then opens again in the **next step** mode: "New task under"
  the logged task's parent, the line its title, State Not started, In progress or Waiting on a reply, the Today row with
  Put it on Today; Enter makes it (``progress.log_next``), Esc makes nothing;
- ``open_for`` takes a starting state: Closed from a Today tick (755), Waiting on a reply from the state menu (762).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import current, outlook, progress, waits
from docrepo.dates import long_date
from docrepo.detail import esc
from docrepo.edits import _workdays
from docrepo.model import Model
from docrepo.save import EmailItem, SaveError
from docrepo.ui import back_row, tokens
from docrepo.ui.back_row import BackRow
from docrepo.ui.front import bring_to_front
from docrepo.ui.icons import icon
from docrepo.ui.state_menu import open_below, state_icon
from docrepo.ui.style import style_sheet
from docrepo.ui.task_picker import TaskPicker

#: How the task picker says its task came from the current task (release 5.177, decision 830), as "from conversation" does.
CURRENT_HOW = "current task"

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

log = logging.getLogger(__name__)

WIDTH = 600
#: How far a row that doesn't apply is dimmed (decision 695), as the mock's.
DIM = 0.45
#: The Waiting on row's line while another state is picked (decision 695).
PICK_WAITING = "Pick Waiting on a reply to wait on someone."
#: What Enter's button says while it runs (decision 753).
LOGGING = "Logging…"
#: What a busy database says (decision 753): nothing was kept.
BUSY = "Nothing was kept: the database is busy. Try again."
#: The keys of the problem lines (decision 753): SaveError's focus, the Today row's ("back", 5.166), and "" for the foot's.
PROBLEM_ROWS = ("task", "content", "who", "back", "")
#: Other…'s words that aren't a day (release 5.166).
NOT_A_DAY = "Type a day after today in Other…: Fri, 15 Dec, in 3 weeks, or a number of workdays."
#: The next step's parent picker's entry for a task of its own (decision 761).
TOP_LEVEL = ("Top level", "A task of its own, under nothing")


def email_of(draft: outlook.FrontDraft | None) -> progress.Email | None:
    """What the save keeps of the draft: its subject, index and place, and from its copy, To and what it answers."""
    if draft is None:
        return None
    c = draft.copy
    return progress.Email(draft.subject, draft.index, draft.entry_id, draft.store_id, draft.inline, c.to if c else "",
                          c.in_reply_to if c else "", c.refs if c else "", c.message_id if c else "")


def email_of_item(item: EmailItem) -> progress.Email:
    """An attached email (decision 759) as ``progress.task_for`` reads it: its conversation and what it answers."""
    return progress.Email(item.subject, item.conversation_index, item.entry_id, item.store_id, False, item.to, item.in_reply_to,
                          item.refs, item.message_id)


def first_names(m: Model, people: list[str]) -> str:
    """Who, short, as a wait reads: "Dana", "Dana and Mike", "Dana and 2 more"."""
    names = [m.person_name(p).split()[0] for p in people]
    if len(names) <= 2:
        return " and ".join(names)
    return f"{names[0]} and {len(names) - 1} more"


class LogProgress(QWidget):
    """One window per DocRepo, kept and brought back."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.app, self.ctx = app, app.ctx
        self.setObjectName("browse")
        self.setStyleSheet(style_sheet())
        self.setWindowTitle(progress.LABEL)
        self.setWindowIcon(icon("mail"))
        self.setFixedWidth(WIDTH)
        self.draft: outlook.FrontDraft | None = None
        self.email: progress.Email | None = None
        self.attached: EmailItem | None = None  # an email selected in Outlook, kept on the Update (decision 759)
        self.task: str | None = None
        self.task_how = ""
        self.people: list[str] = []
        self.to_people: list[str] = []  # Waiting on as the email's To gave it, for Waiting on a reply picked again
        self.state_key = progress.IN_PROGRESS
        self.picked = False  # whether the owner picked on the Today row, so a wait doesn't change it (decision 757)
        self.next_step = False  # Log, then next…'s second window (decision 761)
        self.next_parent: str | None = None
        self.next_after = ""  # the task just logged, for the email line
        self.then_next = False
        self._dimmed: list[QGraphicsOpacityEffect] = []
        self.problems: dict[str, QLabel] = {}  # what stops a save, by its row (decision 753)
        self.kept: str | None = None  # the Update an Enter kept when the rest wasn't (decision 754)
        self.busy = False  # while Enter runs (decision 753)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(12)
        self._build_email(lay)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self._build_task(grid)
        self._build_state(grid)
        self._build_waiting(grid)
        self._build_back(grid)
        lay.addLayout(grid)
        self._build_foot(lay)

        self.picker = TaskPicker(self, self.ctx.model, none_entry=None)
        self.picker.picked.connect(self._task_picked)
        self.parent_picker = TaskPicker(self, self.ctx.model, none_entry=TOP_LEVEL)  # the next step's (decision 761)
        self.parent_picker.picked.connect(self._parent_picked)
        QShortcut(QKeySequence("Escape"), self, self.hide)
        QShortcut(QKeySequence("Ctrl+T"), self, self.pick_task)
        QShortcut(QKeySequence("Alt+E"), self, self.attach)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, self.log_then_next)

    # ---- building ----
    def _build_email(self, lay: QVBoxLayout) -> None:
        """The email line, with Attach the selected email and its cross (decision 759)."""
        row = QHBoxLayout()
        row.setSpacing(8)
        self.email_line = QLabel(objectName="progressEmail")
        self.email_line.setTextFormat(Qt.TextFormat.RichText)
        self.email_line.setWordWrap(True)
        row.addWidget(self.email_line, 1)
        self.attach_button = QPushButton("Attach the selected email", objectName="link")
        self.attach_button.setToolTip("Alt+E: the email selected in Outlook, kept on the update with the line")
        self.attach_button.clicked.connect(self.attach)
        row.addWidget(self.attach_button, 0, Qt.AlignmentFlag.AlignTop)
        self.detach_button = QPushButton("✕", objectName="link")
        self.detach_button.setToolTip("Take the email off")
        self.detach_button.clicked.connect(self.detach)
        row.addWidget(self.detach_button, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(row)

    def _build_task(self, grid: QGridLayout) -> None:
        self.task_button = QPushButton(objectName="progressTask")
        self.task_button.setStyleSheet("text-align: left; padding: 6px 10px;")
        self.task_button.setToolTip("The task (Ctrl+T, or #): the # list")
        self.task_button.clicked.connect(self.pick_task)
        self._row(grid, 0, "Task", self.task_button)
        self._problem_line(grid, 1, "task")
        self.line = QLineEdit(objectName="progressLine")
        self.line.textEdited.connect(self._line_typed)
        self.line_name = self._row(grid, 2, "What you did", self.line)
        self._problem_line(grid, 3, "content")

    def _build_state(self, grid: QGridLayout) -> None:
        """State (decision 695): a dropdown under What you did, each choice with its mark and, in its tooltip, what it does."""
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.state_box = QComboBox(objectName="progressState")
        self.state_box.setMinimumWidth(220)
        self.state_box.setToolTip("Where this line leaves the task")
        self.state_box.activated.connect(lambda n: self.pick_state(self.state_box.itemData(n)))
        self._fill_states(progress.STATES)
        bl.addWidget(self.state_box)
        bl.addStretch()
        self._row(grid, 4, "State", box)
        self.state_note = QLabel(objectName="hint")
        self.state_note.setWordWrap(True)
        grid.addWidget(self.state_note, 5, 1)

    def _fill_states(self, states: tuple[tuple[str, str, str], ...]) -> None:
        self.state_box.clear()
        for n, (key, words, does) in enumerate(states):
            mark = icon("waiting", tokens.LIGHT["accent"]) if key == progress.WAITING else state_icon(
                progress.TASK_STATE.get(key) or progress.NEXT_STATE[key])
            self.state_box.addItem(mark, words, key)
            self.state_box.setItemData(n, does, Qt.ItemDataRole.ToolTipRole)

    def _build_waiting(self, grid: QGridLayout) -> None:
        who = QWidget()
        wl = QHBoxLayout(who)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(4)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        wl.addLayout(self.chips)
        self.who = QLineEdit(objectName="progressWho")
        self.who.returnPressed.connect(self.add_person)  # with the completer's list open, Enter comes this way
        self.who.installEventFilter(self)  # otherwise, Enter is the filter's (decision 753)
        wl.addWidget(self.who, 1)
        self.who_name = self._row(grid, 6, "Waiting on", who, "")
        self._problem_line(grid, 7, "who")
        self.who_note = QLabel(objectName="hint")
        self.who_note.setWordWrap(True)
        grid.addWidget(self.who_note, 8, 1)
        self._dim(self.who_name, who)

    def _build_back(self, grid: QGridLayout) -> None:
        """Today: Back on Today (decision 757), one row in place of Follow up's and Today's."""
        self.back = BackRow(self.today, lambda: _workdays(self.ctx.settings))
        self.back.changed.connect(self._back_picked)
        self.today_name = self._row(grid, 9, "Today", self.back)
        self.today_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.today_name.setContentsMargins(0, 6, 0, 0)
        self._problem_line(grid, 10, "back")
        self.today_note = self.back.note

    def _build_foot(self, lay: QVBoxLayout) -> None:
        foot = QHBoxLayout()
        self.dates_link = QPushButton("Dates and reminder…", objectName="link")
        self.dates_link.setToolTip("Edit task, at More options: its key dates, Reminder and the reminder's repeat")
        self.dates_link.clicked.connect(self.open_dates)
        self.message = self._problem_label("")  # what has no row: an error that isn't a field's (decision 753)
        self.cancel = QPushButton("Cancel")
        self.cancel.setToolTip("Esc: close it, keeping nothing")
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.hide)
        self.cancel.installEventFilter(self)  # Enter on Cancel cancels (decision 753)
        self.next_button = QPushButton("Log, then next…")
        self.next_button.setToolTip("Ctrl+Enter: log it, then the task that comes next")
        self.next_button.setAutoDefault(False)
        self.next_button.clicked.connect(self.log_then_next)
        self.enter = QPushButton(objectName="primary")
        self.enter.setDefault(True)
        self.enter.clicked.connect(self.submit)
        foot.addWidget(self.dates_link)
        foot.addWidget(self.message, 1)
        foot.addWidget(self.cancel)
        foot.addWidget(self.next_button)
        foot.addWidget(self.enter)
        lay.addLayout(foot)
        self.after = QLabel(objectName="hint")
        self.after.setWordWrap(True)
        self.after.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.after)

    @staticmethod
    def _row(grid: QGridLayout, row: int, label: str, widget: QWidget, tip: str = "") -> QLabel:
        name = QLabel(label, objectName="hint")
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(name, row, 0)
        grid.addWidget(widget, row, 1)
        if tip:
            widget.setToolTip(tip)
        return name

    def _problem_label(self, key: str) -> QLabel:
        """A problem line (decision 753): in the caution colour. A row's is hidden until there's something to say; the
        foot's ("") stays, empty, so Cancel and Enter keep to the right."""
        label = QLabel(objectName="progressProblem")
        label.setWordWrap(True)
        label.setVisible(not key)
        self.problems[key] = label
        return label

    def _problem_line(self, grid: QGridLayout, row: int, key: str) -> None:
        grid.addWidget(self._problem_label(key), row, 1)

    def say(self, key: str, words: str) -> None:
        """Say what stops the save by its row (``key``: task, content, who, back, or "" for the foot), the others cleared."""
        for k, label in self.problems.items():
            label.setText(words if k == key else "")
            label.setVisible(not k or (k == key and bool(words)))

    def clear_problems(self) -> None:
        self.say("", "")

    def _dim(self, *widgets: QWidget) -> None:
        """Widgets dimmed while another state than Waiting on a reply is picked (decision 695)."""
        for w in widgets:
            effect = QGraphicsOpacityEffect(w)
            effect.setOpacity(DIM)
            effect.setEnabled(False)
            w.setGraphicsEffect(effect)
            self._dimmed.append(effect)

    def model(self) -> Model:
        return self.ctx.model()

    def today(self) -> date:
        return self.ctx.now().date()

    # ---- what the Today row means (decision 757) ----
    @property
    def choice(self) -> str:
        """The Today row's pick: ``back_row``'s Stays, Done for today, None or Put it on Today, or a Back key."""
        return self.back.key

    @property
    def done_today(self) -> bool:
        return self.back.key == back_row.DONE and self.state_key != progress.CLOSED

    def back_day(self) -> date | None:
        """The day it comes back, for a Back pick; None otherwise, or with Closed."""
        return None if self.state_key == progress.CLOSED else self.back.day()

    def _default_back(self) -> None:
        """The row's pick when the owner hasn't made one: with a wait, the last Back chosen with one (as Follow up's was),
        else Stays, None or Put it on Today."""
        if self.picked:
            return
        self.back.pick(progress.last_follow_up(self.ctx.conn) if self.people else self.back.first())

    # ---- opening ----
    def open_for(self, draft: outlook.FrontDraft | None, task: str | None = None, screen=None, state: str | None = None) -> None:
        """Open for the draft (or none, a call or a talk) on ``task``, or the task its email's conversation names. ``state``
        (release 5.166) is where State starts: Closed from a Today tick (decision 755), Waiting on a reply from the state
        menu (decision 762)."""
        m = self.model()
        self._leave_next_step()
        self.draft, self.email, self.attached = draft, email_of(draft), None
        self.task, self.task_how = None, ""
        if task in m.tasks:
            self.task = task
        elif self.email is not None:
            self.task, self.task_how = progress.task_for(m, self.email)
        if self.task is None:  # no conversation to go by: the task you're working on (release 5.177, decision 830)
            now = current.get(self.ctx.conn, m)
            if now is not None:
                self.task, self.task_how = now, CURRENT_HOW
        self.to_people = progress.people_in(m, self.email.to, self.ctx.settings.me) if self.email and self.email.to else []
        self.people = list(self.to_people)
        self.state_key = progress.WAITING if self.people else progress.IN_PROGRESS  # decision 695
        if state in progress.TASK_STATE:
            self.state_key = state
            if state != progress.WAITING:
                self.people = []
        self.picked = False
        self.back.set_mode(back_row.ON_TODAY if self.on_today(m) else back_row.OFF_TODAY)
        self._default_back()
        self.line.clear()
        self.who.clear()
        self.clear_problems()
        self.kept, self.busy = None, False
        self.enter.setEnabled(True)
        self._completer(m)
        self.render()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.x() + (area.width() - self.width()) // 2, area.y() + max(0, (area.height() - 420) // 3))
        bring_to_front(self)
        if not self.task:
            self.pick_task()
        else:
            self.line.setFocus()  # the line first, even waiting with nobody: Enter then asks who

    def _completer(self, m: Model) -> None:
        names = [p.name for p in m.people.values() if p.status == "active" and p.id != self.ctx.settings.me]
        completer = QCompleter(sorted(names), self.who)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.who.setCompleter(completer)

    def open_next(self, after: str) -> None:
        """Log, then next…'s second window (decision 761): the next step after ``after``, under its parent (its first, as the
        tree lists it), or a top-level task when it has none."""
        m = self.model()
        parents = m.parents_of(after) if after in m.tasks else []
        self.next_step, self.next_after = True, after
        self.next_parent = parents[0] if parents else None
        self.draft = self.email = self.attached = None
        self.task, self.task_how = None, ""
        self.people, self.to_people = [], []
        self.state_key = progress.NOT_STARTED
        self._fill_states(progress.NEXT_STATES)
        self.picked = False
        self.back.set_mode(back_row.NEXT)
        self.back.pick(back_row.PUT)
        self.line.clear()
        self.who.clear()
        self.clear_problems()
        self.kept, self.busy = None, False
        self.enter.setEnabled(True)
        self._completer(m)
        self.render()
        bring_to_front(self)
        self.line.setFocus()

    def _leave_next_step(self) -> None:
        if self.next_step:
            self.next_step = False
            self._fill_states(progress.STATES)

    # ---- drawing ----
    def render(self) -> None:
        m = self.model()
        self._render_email(m)
        self._render_task(m)
        waiting = self.state_key == progress.WAITING
        states = progress.NEXT_STATES if self.next_step else progress.STATES
        self.state_box.setCurrentIndex(next(n for n, s in enumerate(states) if s[0] == self.state_key))
        self.state_note.setText(self.state_words(m))
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w is not None:
                w.hide()  # gone at once, under the dimmed row's effect too, not when Qt next deletes
                w.deleteLater()
        for p in self.people:
            chip = QPushButton(f"{m.person_name(p)}  ✕", objectName="today")
            chip.setToolTip(f"Not waiting on {m.person_name(p)}")
            chip.clicked.connect(lambda _=False, who=p: self.drop_person(who))
            self.chips.addWidget(chip)
        self.who.setPlaceholderText("Add a person" if self.people else "Nobody: just log it")
        if not waiting:
            self.who_note.setText(PICK_WAITING)
        else:
            self.who_note.setText("From the email's To, matched in People." if self.to_people else "Type a name from People.")
        for effect in self._dimmed:
            effect.setEnabled(not waiting)
        self._render_back(m)
        self._render_foot()
        self.adjustSize()

    def _render_email(self, m: Model) -> None:
        e, a = self.email, self.attached
        strong = f"color:{tokens.LIGHT['text']}; font-weight:600"
        soft = f"color:{tokens.LIGHT['text2']}"
        if self.next_step:
            after = m.tasks[self.next_after].title if self.next_after in m.tasks else "the task"
            self.email_line.setText(f"<span style='{strong}'>Next step, after {esc(after)}</span><br>"
                                    f"<span style='{soft}'>Logged. Now the task that comes next: Enter makes it, Esc makes "
                                    "nothing.</span>")
        elif e is not None:
            where = "a reply in the reading pane" if e.inline else "a draft in its own window"
            to = f"To {esc(e.to.split(';')[0].split('<')[0].strip())}" + (" and others" if ";" in e.to else "") if e.to else "To: DocRepo couldn't read it"
            self.email_line.setText(f"<span style='{strong}'>{esc(e.subject or '(no subject yet)')}</span><br>"
                                    f"<span style='{soft}'>{to} · {where}</span>")
        elif a is not None:
            sender = a.sender.split("<")[0].strip() or "an unknown sender"
            self.email_line.setText(f"<span style='{strong}'>{esc(a.subject or '(no subject)')}</span><br>"
                                    f"<span style='{soft}'>From {esc(sender)} · attached: kept on the update with the line</span>")
        else:
            self.email_line.setText(f"<span style='{strong}'>No email in front</span><br>"
                                    f"<span style='{soft}'>A call, a talk or a message: logged the same way, with nothing to "
                                    "send.</span>")
        free = e is None and not self.next_step
        self.attach_button.setVisible(free and a is None)
        self.detach_button.setVisible(free and a is not None)

    def _render_task(self, m: Model) -> None:
        if self.next_step:
            under = m.tasks[self.next_parent].title if self.next_parent in m.tasks else ""
            self.task_button.setText(f"New task under {under}" if under else "New top-level task")
            self.task_button.setToolTip("Where the next step goes (Ctrl+T): the # list, or Top level")
            self.line_name.setText("Next step")
            self.line.setPlaceholderText("The next step: the new task's title")
            self.line.setToolTip("The new task's title.")
            return
        self.task_button.setToolTip("The task (Ctrl+T, or #): the # list")
        self.line_name.setText("What you did")
        self.line.setPlaceholderText("What you sent or asked, in a line")
        self.line.setToolTip("Becomes the task's current status, a line in its status log.")
        if self.task and self.task in m.tasks:
            how = f"  ·  {self.task_how}" if self.task_how else ""
            self.task_button.setText(f"{m.tasks[self.task].title}{how}")
        else:
            self.task_button.setText("# a task")

    def _render_foot(self) -> None:
        sends = self.sends()
        nxt = self.next_step
        self.enter.setText("Make it" if nxt else "Send and log" if sends else "Log")
        self.enter.setToolTip("Enter")
        self.next_button.setVisible(not nxt)
        self.dates_link.setVisible(not nxt)
        if nxt:
            self.after.setText("Nothing is logged on it: it's a task to do, with no update yet.")
        elif self.email is None:
            self.after.setText("Nothing is sent: the line and the email you attached are kept on the task." if self.attached is not None
                               else "Nothing is sent: the line, the wait and the day it comes back are kept.")
        elif sends:
            self.after.setText("DocRepo sends this email for you once it's logged.")
        elif self.email.inline:
            self.after.setText("Outlook won't let a program send a reply in the reading pane: Enter logs, then press Send there.")
        else:
            self.after.setText("Then the email comes to the front: press Send.")

    def state_words(self, m: Model) -> str:
        """The line under State: what Enter does to the task's state (decisions 589, 695 and 696)."""
        key = self.state_key
        if self.next_step:
            return {progress.NOT_STARTED: "Not started: nothing done on it yet.", progress.IN_PROGRESS: "In progress: started.",
                    progress.WAITING: "In progress, with the hourglass while you wait."}[key]
        t = m.tasks.get(self.task or "")
        if key in (progress.IN_PROGRESS, progress.WAITING):
            how = ", with the hourglass while you wait." if key == progress.WAITING else ", with nothing to wait for."
            if t is None:
                return f"In progress{how}"
            return f"It stays In progress{how}" if t.state == "In progress" else f"Was {t.state}: it goes In progress{how}"
        if key == progress.PARKED:
            return "Parked, with this line as its current status. No wait."
        below = len(open_below(m, t.id)) if t is not None else 0
        more = f" Its {below} open subtask{'s stay' if below != 1 else ' stays'} open." if below else ""
        return f"Closed, with this line as its last status. No wait.{more}"

    def on_today(self, m: Model) -> bool:
        return bool(self.task) and any(a.subject == self.task for a in m.today_items())

    def _render_back(self, m: Model) -> None:
        """The Today row (decision 757): its mode, live or off with Closed, and its line."""
        if not self.next_step:
            self.back.set_mode(back_row.ON_TODAY if self.on_today(m) else back_row.OFF_TODAY)
        closed = self.state_key == progress.CLOSED
        self.back.setEnabled(not closed)
        self.today_note.setText(self.back_words(m))

    def back_words(self, m: Model) -> str:
        """What the Today row's pick does, in a line."""
        key, today = self.back.key, self.today()
        on = self.on_today(m)
        if self.state_key == progress.CLOSED:
            return "Closed: its Today item closes as done with it." if on else "Closed: nothing comes back on Today."
        if self.back.is_day():
            day = self.back.day()
            if day is None:
                return NOT_A_DAY
            when = long_date(day, today)
            if self.next_step:
                if self.people:
                    return f"On Today {when}, if {first_names(m, self.people)} hasn't replied: the follow-up."
                return f"On Today {when}: its Reminder."
            if self.people:
                back = waits.reminder_for(m, self.task, day) if self.task in m.tasks else day.isoformat()
                if back and back != day.isoformat():
                    return (f"{'Off Today now; back' if on else 'On Today'} {long_date(date.fromisoformat(back), today)}, its own "
                            f"reminder, before the follow-up {when}.")
                return f"{'Off Today now; back' if on else 'On Today'} {when} if {first_names(m, self.people)} hasn't replied: the follow-up."
            return f"Off Today now, back {when}: its Reminder." if on else f"On Today {when}: its Reminder."
        if key == back_row.STAYS:
            return "It stays on Today."
        if key == back_row.DONE:
            return "Off Today now, under Done today, where Back on Today puts it back."
        if key == back_row.PUT:
            return "It goes on Today now."
        if self.next_step:
            return "Not on Today."
        return "No follow-up: nothing brings it back by itself." if self.people else "Not on Today: nothing brings it back by itself."

    def sends(self) -> bool:
        """Whether Enter sends (decision 590 A): a draft in its own window, with Settings' Log progress sends on."""
        return self.email is not None and not self.email.inline and self.ctx.settings.progress_sends and not self.next_step

    # ---- the fields ----
    def pick_task(self) -> None:
        picker = self.parent_picker if self.next_step else self.picker
        picker.popup(self.task_button.mapToGlobal(QPoint(0, self.task_button.height())))

    def _task_picked(self, task_id: str | None) -> None:
        if task_id:
            if task_id != self.task:
                self.kept = None  # an Update kept on the other task stays there; this one gets its own
                self.clear_problems()
                if not self.picked and self.back.key == back_row.DONE:
                    self.back.pick(back_row.STAYS)  # another task: its Today row starts as it is
            self.task, self.task_how = task_id, ""
            self.render()
            self.line.setFocus()

    def _parent_picked(self, task_id: str | None) -> None:
        """The next step's parent (decision 761): a task, or None for Top level."""
        self.next_parent = task_id
        self.render()
        self.line.setFocus()

    def _line_typed(self, text: str) -> None:
        if text == "#":  # # in an empty line picks the task, as in the capture window
            self.line.clear()
            self.pick_task()

    def pick_state(self, key: str) -> None:
        """A state picked (decision 695). Another than Waiting on a reply empties Waiting on; Waiting on a reply with nobody
        takes back the email's To people, or puts the cursor in Waiting on. The Today row follows a wait's default
        (decision 757) until the owner picks on it."""
        self.state_key = key
        if key != progress.WAITING:
            self.people = []
            self._default_back()
            self.render()
            return
        if not self.people:
            self.people = list(self.to_people)
        self._default_back()
        self.say("who", "")
        self.render()
        if not self.people:
            self.who.setFocus()

    def add_person(self) -> None:
        """Enter in Waiting on (decision 753): with words in the box, the person they name is added; with the box empty,
        it logs."""
        words = self.who.text().strip().casefold()
        if not words:
            self.submit()
            return
        m = self.model()
        found = [p.id for p in m.people.values() if p.status == "active" and (p.name.casefold() == words or words in p.name.casefold())]
        if len(found) != 1:
            self.say("who", "Type a name from People, as the list shows it." if not found else "Several match: type more of the name.")
            return
        first = not self.people
        if found[0] not in self.people:
            self.people.append(found[0])
        self.state_key = progress.WAITING  # a person added picks Waiting on a reply (decision 695)
        if first:
            self._default_back()
        self.who.clear()
        self.clear_problems()
        self.render()
        self.who.setFocus()

    def drop_person(self, person: str) -> None:
        self.people = [p for p in self.people if p != person]
        self._nobody_left()
        self.render()

    def _nobody_left(self) -> None:
        """The last person taken away picks In progress, as the mock has it."""
        if not self.people and self.state_key == progress.WAITING:
            self.state_key = progress.IN_PROGRESS
            self._default_back()

    def _back_picked(self) -> None:
        self.picked = True
        self.say("back", "")
        self.render()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        from PySide6.QtCore import QEvent

        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if watched is self.who and enter:  # decision 753: adds the person typed, or with the box empty logs
            self.add_person()
            return True
        if watched is self.cancel and enter:  # decision 753: Enter on Cancel cancels
            self.hide()
            return True
        if watched is self.who and event.key() == Qt.Key.Key_Backspace and not self.who.text() and self.people:
            self.people.pop()
            self._nobody_left()
            self.render()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """Enter anywhere else logs: Waiting on's and Cancel's are the event filter's (decision 753)."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.focusWidget() not in (self.who, self.cancel):
            self.submit()
            return
        super().keyPressEvent(event)

    # ---- Dates and reminder…, and an attached email (decisions 758 and 759) ----
    def open_dates(self) -> None:
        """Edit task at More options for the task (decision 758); closing it comes back here, the Today row reading the
        Reminder as it now is. Edit task's own form: no second editor of dates."""
        if not self.task or self.next_step:
            self.pick_task()
            return
        edit = getattr(self.app, "edit_task_dates", None)
        if edit is None:
            return
        self.hide()
        try:
            edit(self.task)
        finally:
            self.render()
            bring_to_front(self)
            self.line.setFocus()

    def attach(self) -> None:
        """Attach the selected email (decision 759, Alt+E): the one email selected in Outlook, read as Add selected Outlook
        email reads it. Never without the key or a click; with several selected, it says to select one."""
        if self.email is not None or self.next_step:
            return
        try:
            found = outlook.selected_emails(outlook.copy_path(self.ctx.fs, self.ctx.data_root))
        except outlook.OutlookError as e:
            self.say("", f"Outlook didn't give DocRepo the email ({e}).")
            return
        except Exception as e:  # noqa: BLE001 - COM or pywin32: said, and the window stays as it was
            self.say("", f"Outlook didn't give DocRepo the email ({outlook.record_problem('reading the selected email for Log progress', e)}).")
            return
        if not found:
            self.say("", "Select an email in Outlook first: none is selected.")
            return
        if len(found) > 1:
            self.say("", f"{len(found)} emails are selected in Outlook: select one.")
            return
        self.attached = found[0]
        self.clear_problems()
        if not self.task:
            self.task, self.task_how = progress.task_for(self.model(), email_of_item(self.attached))
        self.render()
        if self.task:
            self.line.setFocus()
        else:
            self.pick_task()

    def detach(self) -> None:
        self.attached = None
        self.render()
        self.line.setFocus()

    # ---- Enter ----
    def log_then_next(self) -> None:
        """Log, then next… (decision 761, Ctrl+Enter): log as Enter does, then the next step."""
        if self.next_step:
            self.submit()
            return
        self.then_next = True
        try:
            self.submit()
        finally:
            self.then_next = False

    def submit(self) -> None:
        """Check, keep, hide, then send (decision 590 A) or bring the draft back for the owner to send, then tell the app
        (decision 752). What stops it is said by its row (753); while it runs, a second press does nothing."""
        if self.busy:
            return
        if not self.task and not self.next_step:
            self.pick_task()
            return
        if self.state_key == progress.WAITING and not self.people:
            self.stop("who", progress.NOBODY)
            return
        if self.back.key == back_row.OTHER and self.back_day() is None and self.state_key != progress.CLOSED:
            self.stop("back", NOT_A_DAY)
            return
        then_next = self.then_next
        self.busy = True
        label = self.enter.text()
        self.enter.setText(LOGGING)
        self.enter.setEnabled(False)
        self.enter.repaint()
        try:
            done = self._keep_next() if self.next_step else self._keep()
        finally:
            self.busy = False
            self.enter.setText(label)
            self.enter.setEnabled(True)
        if done is None:
            return
        if isinstance(done, progress.Next):
            self._after_next(done)
            return
        self._after(done)
        if then_next:
            self.open_next(done.task)

    def stop(self, key: str, words: str) -> None:
        """Say what stops the save by its row, and put the cursor there."""
        self.say(key, words)
        {"task": self.task_button, "who": self.who, "content": self.line,
         "back": self.back.other if self.back.key == back_row.OTHER else self.line}.get(key, self.line).setFocus()

    def _guarded(self, keep):
        """Run ``keep``, or say why not and return None. Every error is caught (decision 753)."""
        try:
            return keep()
        except progress.NotAllKept as e:  # decision 754: the next Enter keeps the rest, with no second Update
            self.kept = e.capture
            self.stop(e.focus, str(e))
            return None
        except SaveError as e:
            self.stop(e.focus if e.focus in self.problems else "content", str(e))
            return None
        except sqlite3.OperationalError as e:  # locked or busy: nothing kept, since the Update is first
            log.warning("Log progress on %s: nothing kept (%s)", self.task, type(e).__name__)
            self.stop("", BUSY if "lock" in str(e) or "busy" in str(e) else f"Nothing was kept ({type(e).__name__}). Try again.")
            return None
        except Exception as e:  # noqa: BLE001 - said in the window, logged without the capture's words
            log.warning("Log progress on %s: nothing kept (%s)", self.task, type(e).__name__)
            self.stop("", f"Nothing was kept ({type(e).__name__}). Try again.")
            return None

    def _keep(self) -> progress.Logged | None:
        """Keep it (``progress.log_progress``)."""
        back = self.back_day() if self.back.is_day() else None
        choice = self.back.key if self.back.key in dict(progress.BACK) else ""
        done = self._guarded(lambda: progress.log_progress(
            self.ctx.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id=self.task or "", line=self.line.text(),
            on=self.people, follow_up=None, at=self.ctx.now(), email=self.email, choice=choice, state=self.state_key,
            done_today=self.done_today, kept=self.kept, back=back, attached=self.attached))
        if done is not None:
            self.kept = None
            self.clear_problems()
        return done

    def _keep_next(self) -> progress.Next | None:
        """Make the next step (``progress.log_next``, decision 761)."""
        back = self.back.day() if self.back.is_day() else None
        choice = self.back.key if self.back.key in dict(progress.BACK) else ""
        done = self._guarded(lambda: progress.log_next(
            self.ctx.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, parent=self.next_parent, title=self.line.text(),
            state=self.state_key, on=self.people, at=self.ctx.now(), today=self.back.key == back_row.PUT, back=back, choice=choice))
        if done is not None:
            self.clear_problems()
        return done

    def _after_next(self, done: progress.Next) -> None:
        """The next step made: the window goes, and the app is told."""
        self.hide()
        m = self.model()
        t = m.task(done.task)
        under = m.tasks[self.next_parent].title if self.next_parent in m.tasks else ""
        where = f" under {under}" if under else ", a top-level task"
        wait = f", waiting on {waits.who(m, waits.current(m, done.task))}" if done.wait and waits.current(m, done.task) else ""
        when = ", on Today" if done.on_today else f", on Today {long_date(date.fromisoformat(done.reminder), self.today())}" if done.reminder else ""
        self._leave_next_step()
        self.app.progress_logged(done, f"Next step made{where}: {t.title}{wait}{when}.", False)

    def _after(self, done: progress.Logged) -> None:
        """Kept: the window goes first, then Outlook is asked (decision 752), then the app is told. The window holds
        nothing of Outlook's after (decision 751)."""
        sends = self.sends()
        draft, subject = self.draft, self.email.subject if self.email else ""
        attached = self.attached is not None
        self.draft = self.email = self.attached = None  # the window holds nothing of Outlook's (decision 751)
        self.hide()  # before Outlook is asked, so no prompt of Outlook's sits under it (decision 752)
        m = self.model()
        title = m.tasks[done.task].title
        wait = f": waiting on {waits.who(m, waits.current(m, done.task))}" if done.wait and waits.current(m, done.task) else ""
        follow = f", follow up {long_date(date.fromisoformat(done.follow_up), self.today())}" if done.follow_up else ""
        if done.back and not done.follow_up:
            follow = f", back on Today {long_date(date.fromisoformat(done.back), self.today())}"
        state = {progress.PARKED: ": parked", progress.CLOSED: ": closed"}.get(self.state_key, "")
        said, trouble = f"Logged on {title}{state}{wait}{follow}.", False
        if attached:
            said = f"{said} The email is kept with it."
        if draft is not None:
            sent = False
            if sends:
                self._mark(progress.sending, done, subject, self.ctx.now())  # nothing of DocRepo's reads it on its way out (751)
                try:
                    outlook.send_draft(draft)
                    sent = True
                except outlook.OutlookError as e:
                    self._mark(progress.not_sent, done)  # the owner sends it: watched as before
                    said, trouble = f"{said} Outlook didn't send it ({e}): press Send in Outlook.", True
            if sent:
                said = f"Sent, and l{said[1:]}"
            else:
                outlook.show_draft(draft)
                if not trouble:
                    said = f"{said} Press Send in Outlook."
            del draft
            self.ctx.t_mail_opened()  # its sent copy is watched for (release 5.123)
        if done.done_today and not done.back:  # decision 697: what Enter did says so, last
            said = f"{said} Done for today."
        self.app.progress_logged(done, said, trouble)

    def _mark(self, how, done: progress.Logged, *args) -> None:
        """Mark the kept draft around the send (decision 751). The log is kept already, so a database too busy for the
        mark is only logged: the draft is then looked at as before."""
        try:
            how(self.ctx.conn, done, *args)
        except sqlite3.Error as e:
            log.warning("Log progress: the draft's mark wasn't kept (%s)", type(e).__name__)
