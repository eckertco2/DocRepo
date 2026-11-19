"""Log progress's form (release 5.175, the design workspace's ``docs/mods/log-progress-whole-plan.md``, decision 763): one
form in two homes, the Log progress window and the workspace's status card (decision 764).

Its rows, as Log progress has had them since release 5.166:
- **What you did** (decision 586): one line, the task's current status. A home with a line of its own (the status card's
  quick entry box) hands it in, and the form places no row for it;
- **State** (decision 695): a dropdown of ``progress.STATES`` (or, for Log, then next…'s next step, ``NEXT_STATES``), the
  line under it saying what Enter does to the task's state;
- **Waiting on** (decision 587): people chips and a box for a name from People; Enter in the box adds the person typed,
  or with the box empty asks its home to log (``submit``, decision 753);
- **Today** (decision 757, ``ui.back_row``): Back on Today, Stays, Done for today, None or Put it on Today, and Back.

State is kept in step with Waiting on (decision 695), and the Today row with a wait's default (757), as the window kept
them. What stops a save is said by its row (``say``, decision 753). ``values`` is what ``progress.log_progress`` takes, so
both homes keep the same thing. The form is a set of rows its home places in a grid of its own (``place``), not a widget,
so the window's grid stays one grid, with its Task row above the form's.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from docrepo import progress, waits
from docrepo.dates import long_date
from docrepo.edits import _workdays
from docrepo.model import Model
from docrepo.save import SaveError
from docrepo.ui import back_row, tokens
from docrepo.ui.back_row import BackRow
from docrepo.ui.icons import icon
from docrepo.ui.state_menu import open_below, state_icon

if TYPE_CHECKING:
    from docrepo.ui.context import AppContext

log = logging.getLogger(__name__)

#: How far a row that doesn't apply is dimmed (decision 695), as the mock's.
DIM = 0.45
#: The Waiting on row's line while another state is picked (decision 695).
PICK_WAITING = "Pick Waiting on a reply to wait on someone."
#: Other…'s words that aren't a day (release 5.166).
NOT_A_DAY = "Type a day after today in Other…: Fri, 15 Dec, in 3 weeks, or a number of workdays."
#: The form's problem lines (decision 753): a SaveError's focus, and the Today row's.
ROWS = ("content", "who", "back")
#: What a busy database says (decision 753): nothing was kept.
BUSY = "Nothing was kept: the database is busy. Try again."


def first_names(m: Model, people: list[str]) -> str:
    """Who, short, as a wait reads: "Dana", "Dana and Mike", "Dana and 2 more"."""
    names = [m.person_name(p).split()[0] for p in people]
    if len(names) <= 2:
        return " and ".join(names)
    return f"{names[0]} and {len(names) - 1} more"


def guarded(keep, task: str | None, stop, kept_back=None):
    """Run ``keep`` (a log), or say why not through ``stop(row, words)`` and return None: every error is caught (decision
    753), and the window and the status card say them the same way. ``kept_back`` takes the Update kept when the rest
    wasn't (decision 754)."""
    try:
        return keep()
    except progress.NotAllKept as e:  # decision 754: the next Enter keeps the rest, with no second Update
        if kept_back is not None:
            kept_back(e.capture)
        stop(e.focus, str(e))
    except SaveError as e:
        stop(e.focus, str(e))
    except sqlite3.OperationalError as e:  # locked or busy: nothing kept, since the Update is first
        log.warning("Log progress on %s: nothing kept (%s)", task, type(e).__name__)
        stop("", BUSY if "lock" in str(e) or "busy" in str(e) else f"Nothing was kept ({type(e).__name__}). Try again.")
    except Exception as e:  # noqa: BLE001 - said where it was typed, logged without the capture's words
        log.warning("Log progress on %s: nothing kept (%s)", task, type(e).__name__)
        stop("", f"Nothing was kept ({type(e).__name__}). Try again.")
    return None

def said_after(m: Model, done: progress.Logged, state: str, today: date) -> str:
    """What a log says once it's kept, the window's notice and the status card's alike: "Logged on Rigging plan: waiting on
    Mike, follow up Tue 13 Oct.", "…, back on Today Thu 15 Oct.", "…: parked."."""
    title = m.tasks[done.task].title
    wait = f": waiting on {waits.who(m, waits.current(m, done.task))}" if done.wait and waits.current(m, done.task) else ""
    follow = f", follow up {long_date(date.fromisoformat(done.follow_up), today)}" if done.follow_up else ""
    if done.back and not done.follow_up:
        follow = f", back on Today {long_date(date.fromisoformat(done.back), today)}"
    words = {progress.PARKED: ": parked", progress.CLOSED: ": closed"}.get(state, "")
    return f"Logged on {title}{words}{wait}{follow}."


class ProgressForm(QObject):
    """The rows, their state and what they mean. ``submit`` asks the home to log (Enter in an empty Waiting on box);
    ``changed`` is sent after each pick, so the home can redraw its own parts and its size."""

    submit = Signal()
    changed = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget, line: QLineEdit | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.own_line = line is None
        self.line = line if line is not None else QLineEdit(objectName="progressLine")
        self.task: str | None = None
        self.people: list[str] = []
        self.to_people: list[str] = []  # Waiting on as an email's To gave it, for Waiting on a reply picked again
        self.state_key = progress.IN_PROGRESS
        self.picked = False  # whether the owner picked on the Today row, so a wait doesn't change it (decision 757)
        self.next_step = False  # Log, then next…'s next step (decision 761)
        self._dimmed: list[QGraphicsOpacityEffect] = []
        self.problems: dict[str, QLabel] = {}
        self._build()

    # ---- building ----
    def _build(self) -> None:
        self.line_name = QLabel("What you did", objectName="hint")
        for key in ROWS:
            label = QLabel(objectName="progressProblem")
            label.setWordWrap(True)
            label.hide()
            self.problems[key] = label
        self.state_box = QComboBox(objectName="progressState")
        self.state_box.setMinimumWidth(220)
        self.state_box.setToolTip("Where this line leaves the task")
        self.state_box.activated.connect(lambda n: self.pick_state(self.state_box.itemData(n)))
        self.fill_states(progress.STATES)
        self.state_note = QLabel(objectName="hint")
        self.state_note.setWordWrap(True)
        self.who_widget = QWidget()
        wl = QHBoxLayout(self.who_widget)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(4)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        wl.addLayout(self.chips)
        self.who = QLineEdit(objectName="progressWho")
        self.who.returnPressed.connect(self.add_person)  # with the completer's list open, Enter comes this way
        self.who.installEventFilter(self)  # otherwise, Enter is the filter's (decision 753)
        wl.addWidget(self.who, 1)
        self.who_name = QLabel("Waiting on", objectName="hint")
        self.who_note = QLabel(objectName="hint")
        self.who_note.setWordWrap(True)
        self._dim(self.who_name, self.who_widget)
        self.back = BackRow(self.today, lambda: _workdays(self.ctx.settings))
        self.back.changed.connect(self._back_picked)
        self.today_name = QLabel("Today", objectName="hint")
        self.today_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.today_name.setContentsMargins(0, 6, 0, 0)
        self.today_note = self.back.note
        self.state_name = QLabel("State", objectName="hint")
        for name in (self.line_name, self.state_name, self.who_name):
            name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def place(self, grid: QGridLayout, row: int) -> int:
        """Put the rows in ``grid`` from ``row``: names in column 0, fields in column 1. Returns the next free row."""
        def put(name: QLabel | None, widget: QWidget) -> None:
            nonlocal row
            if name is not None:
                grid.addWidget(name, row, 0)
            grid.addWidget(widget, row, 1)
            row += 1

        if self.own_line:
            put(self.line_name, self.line)
        put(None, self.problems["content"])
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.state_box)
        bl.addStretch()
        put(self.state_name, box)
        put(None, self.state_note)
        put(self.who_name, self.who_widget)
        put(None, self.problems["who"])
        put(None, self.who_note)
        put(self.today_name, self.back)
        put(None, self.problems["back"])
        return row

    def fill_states(self, states: tuple[tuple[str, str, str], ...]) -> None:
        self.state_box.clear()
        for n, (key, words, does) in enumerate(states):
            mark = icon("waiting", tokens.LIGHT["accent"]) if key == progress.WAITING else state_icon(
                progress.TASK_STATE.get(key) or progress.NEXT_STATE[key])
            self.state_box.addItem(mark, words, key)
            self.state_box.setItemData(n, does, Qt.ItemDataRole.ToolTipRole)

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

    # ---- opening ----
    def reset(self, task: str | None, to_people: list[str], state: str | None = None, keep_line: bool = False) -> None:
        """Start over for ``task``: Waiting on from an email's To, State as decision 695 opens it (or ``state``), the Today
        row's default (decision 757), and no problem said. ``keep_line`` leaves the line's words: the status card's, opened
        with words typed."""
        m = self.model()
        self.next_step = False
        self.fill_states(progress.STATES)
        self.task = task
        self.to_people = list(to_people)
        self.people = list(to_people)
        self.state_key = progress.WAITING if self.people else progress.IN_PROGRESS
        if state in progress.TASK_STATE:
            self.state_key = state
            if state != progress.WAITING:
                self.people = []
        self.picked = False
        self.back.set_mode(back_row.ON_TODAY if self.on_today(m) else back_row.OFF_TODAY)
        self.default_back()
        if not keep_line:
            self.line.clear()
        self.who.clear()
        self.clear()
        self.completer(m)

    def reset_next(self) -> None:
        """Log, then next…'s next step (decision 761): no task yet, Not started, Put it on Today."""
        self.next_step = True
        self.task = None
        self.people, self.to_people = [], []
        self.state_key = progress.NOT_STARTED
        self.fill_states(progress.NEXT_STATES)
        self.picked = False
        self.back.set_mode(back_row.NEXT)
        self.back.pick(back_row.PUT)
        self.line.clear()
        self.who.clear()
        self.clear()
        self.completer(self.model())

    def leave_next_step(self) -> None:
        if self.next_step:
            self.next_step = False
            self.fill_states(progress.STATES)

    def completer(self, m: Model) -> None:
        names = [p.name for p in m.people.values() if p.status == "active" and p.id != self.ctx.settings.me]
        completer = QCompleter(sorted(names), self.who)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.who.setCompleter(completer)

    def set_task(self, task: str | None) -> None:
        """Another task picked: its Today row starts as it is, unless the owner picked on it."""
        if task != self.task and not self.picked and self.back.key == back_row.DONE:
            self.back.pick(back_row.STAYS)
        self.task = task

    # ---- drawing ----
    def render(self, m: Model) -> None:
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
        if self.next_step:
            self.line_name.setText("Next step")
            self.line.setPlaceholderText("The next step: the new task's title")
            self.line.setToolTip("The new task's title.")
        elif self.own_line:
            self.line_name.setText("What you did")
            self.line.setPlaceholderText("What you sent or asked, in a line")
            self.line.setToolTip("Becomes the task's current status, a line in its status log.")
        if not self.next_step:
            self.back.set_mode(back_row.ON_TODAY if self.on_today(m) else back_row.OFF_TODAY)
        self.back.setEnabled(self.state_key != progress.CLOSED)
        self.today_note.setText(self.back_words(m))

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

    # ---- what it means ----
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

    def check(self) -> tuple[str, str] | None:
        """What stops Enter before anything is kept, as (row, words): waiting with nobody, or Other…'s words not a day."""
        if self.state_key == progress.WAITING and not self.people:
            return "who", progress.NOBODY
        if self.back.key == back_row.OTHER and self.back_day() is None and self.state_key != progress.CLOSED:
            return "back", NOT_A_DAY
        return None

    def values(self) -> dict:
        """What ``progress.log_progress`` takes from the form (decision 763): the same in both homes."""
        return {"line": self.line.text(), "on": list(self.people), "state": self.state_key, "follow_up": None,
                "back": self.back_day() if self.back.is_day() else None, "done_today": self.done_today,
                "choice": self.back.key if self.back.key in dict(progress.BACK) else ""}

    def default_back(self) -> None:
        """The row's pick when the owner hasn't made one: with a wait, the last Back chosen with one (as Follow up's was),
        else Stays, None or Put it on Today."""
        if self.picked:
            return
        self.back.pick(progress.last_follow_up(self.ctx.conn) if self.people else self.back.first())

    # ---- the rows' own say (decision 753) ----
    def say(self, key: str, words: str) -> None:
        for k, label in self.problems.items():
            label.setText(words if k == key else "")
            label.setVisible(k == key and bool(words))

    def clear(self) -> None:
        self.say("", "")

    def focus(self, key: str) -> None:
        """The cursor where a problem is: the line, Waiting on, or Other…'s box."""
        {"who": self.who, "content": self.line,
         "back": self.back.other if self.back.key == back_row.OTHER else self.line}.get(key, self.line).setFocus()

    # ---- the fields ----
    def pick_state(self, key: str) -> None:
        """A state picked (decision 695). Another than Waiting on a reply empties Waiting on; Waiting on a reply with nobody
        takes back the email's To people, or puts the cursor in Waiting on. The Today row follows a wait's default
        (decision 757) until the owner picks on it."""
        self.state_key = key
        if key != progress.WAITING:
            self.people = []
            self.default_back()
            self.changed.emit()
            return
        if not self.people:
            self.people = list(self.to_people)
        self.default_back()
        self.problems["who"].setText("")
        self.problems["who"].hide()
        self.changed.emit()
        if not self.people:
            self.who.setFocus()

    def add_person(self) -> None:
        """Enter in Waiting on (decision 753): with words in the box, the person they name is added; with the box empty,
        the home logs."""
        words = self.who.text().strip().casefold()
        if not words:
            self.submit.emit()
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
            self.default_back()
        self.who.clear()
        self.clear()
        self.changed.emit()
        self.who.setFocus()

    def drop_person(self, person: str) -> None:
        self.people = [p for p in self.people if p != person]
        self._nobody_left()
        self.changed.emit()

    def _nobody_left(self) -> None:
        """The last person taken away picks In progress, as the mock has it."""
        if not self.people and self.state_key == progress.WAITING:
            self.state_key = progress.IN_PROGRESS
            self.default_back()

    def _back_picked(self) -> None:
        self.picked = True
        self.problems["back"].setText("")
        self.problems["back"].hide()
        self.changed.emit()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if watched is self.who and event.type() == QEvent.Type.KeyPress:
            enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if enter:  # decision 753: adds the person typed, or with the box empty logs
                self.add_person()
                return True
            if event.key() == Qt.Key.Key_Backspace and not self.who.text() and self.people:
                self.people.pop()
                self._nobody_left()
                self.changed.emit()
                return True
        return super().eventFilter(watched, event)
