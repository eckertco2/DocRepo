"""The Log progress window (release 5.139; the design workspace's ``docs/mods/email-progress-plan.md``, decisions 580 to 598,
and its mock).

A window of its own, on top while it's open, from the Log progress hotkey, the Execution wheel's NE (``progress.log``)
or the status card's **Log progress…**. At the top, the email it's for: the draft in front in Outlook when the hotkey was
pressed (decision 584), or "No email: a call or a talk" (decision 592). Then:
- **Task** (decision 585): from the email's conversation, "from conversation", else the ``#`` list (the shared
  ``TaskPicker``), which opens by itself when no task is known;
- **What you did** (decision 586): one line, typed, the task's current status;
- **Waiting on** (decision 587): people chips, from the email's To where its copy gave it, a name typed from People;
  empty means no wait;
- **Follow up** (decision 588): Tomorrow to 2 weeks, or None, the last choice remembered; the day it means beside it;
- **State** (decision 589): what Enter does to it.

Enter keeps it all (``docrepo.progress.log_progress``) and then, for a draft in its own window under decision 590 A,
sends it, a minute deferred; an inline reply, or a send Outlook refuses, comes back to the front for the owner to send.
Esc closes it, keeping nothing. ``ui.wheels`` keeps one window, as it keeps the quick summary.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import outlook, progress, waits
from docrepo.dates import long_date
from docrepo.detail import esc
from docrepo.edits import _workdays
from docrepo.model import Model
from docrepo.save import SaveError
from docrepo.ui import tokens
from docrepo.ui.front import bring_to_front
from docrepo.ui.icons import icon
from docrepo.ui.style import style_sheet
from docrepo.ui.task_picker import TaskPicker

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

log = logging.getLogger(__name__)

WIDTH = 600


def email_of(draft: outlook.FrontDraft | None) -> progress.Email | None:
    """What the save keeps of the draft: its subject, index and place, and from its copy, To and what it answers."""
    if draft is None:
        return None
    c = draft.copy
    return progress.Email(draft.subject, draft.index, draft.entry_id, draft.store_id, draft.inline, c.to if c else "",
                          c.in_reply_to if c else "", c.refs if c else "", c.message_id if c else "")


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
        self.task: str | None = None
        self.task_how = ""
        self.people: list[str] = []
        self.choice = progress.DEFAULT_FOLLOW_UP

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(12)
        self.email_line = QLabel(objectName="progressEmail")
        self.email_line.setTextFormat(Qt.TextFormat.RichText)
        self.email_line.setWordWrap(True)
        lay.addWidget(self.email_line)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.task_button = QPushButton(objectName="progressTask")
        self.task_button.setStyleSheet("text-align: left; padding: 6px 10px;")
        self.task_button.setToolTip("The task (Ctrl+T, or #): the # list")
        self.task_button.clicked.connect(self.pick_task)
        self._row(grid, 0, "Task", self.task_button)
        self.line = QLineEdit(objectName="progressLine")
        self.line.setPlaceholderText("What you sent or asked, in a line")
        self.line.textEdited.connect(self._line_typed)
        self._row(grid, 1, "What you did", self.line, "Becomes the task's current status, a line in its status log.")
        who = QWidget()
        wl = QHBoxLayout(who)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(4)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        wl.addLayout(self.chips)
        self.who = QLineEdit(objectName="progressWho")
        self.who.returnPressed.connect(self.add_person)
        self.who.installEventFilter(self)
        wl.addWidget(self.who, 1)
        self.who_note = QLabel(objectName="hint")
        self._row(grid, 2, "Waiting on", who, "")
        grid.addWidget(self.who_note, 3, 1)
        follow = QWidget()
        fl = QHBoxLayout(follow)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(4)
        self.follow = QButtonGroup(self)
        self.follow.setExclusive(True)
        for n, (key, label) in enumerate(progress.FOLLOW_UPS):
            b = QPushButton(label, objectName="today")  # the checkable chip of the capture window's Today
            b.setCheckable(True)
            b.setProperty("key", key)
            self.follow.addButton(b, n)
            fl.addWidget(b)
        fl.addStretch()
        self.follow.idClicked.connect(self._followed)
        self._row(grid, 4, "Follow up", follow)
        self.follow_note = QLabel(objectName="hint")
        self.follow_note.setWordWrap(True)
        grid.addWidget(self.follow_note, 5, 1)
        self.state_line = QLabel(objectName="hint")
        self._row(grid, 6, "State", self.state_line)
        lay.addLayout(grid)

        foot = QHBoxLayout()
        self.message = QLabel(objectName="hint")
        self.message.setWordWrap(True)
        self.cancel = QPushButton("Cancel")
        self.cancel.setToolTip("Esc: close it, keeping nothing")
        self.cancel.clicked.connect(self.hide)
        self.enter = QPushButton(objectName="primary")
        self.enter.setDefault(True)
        self.enter.clicked.connect(self.submit)
        foot.addWidget(self.message, 1)
        foot.addWidget(self.cancel)
        foot.addWidget(self.enter)
        lay.addLayout(foot)
        self.after = QLabel(objectName="hint")
        self.after.setWordWrap(True)
        self.after.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.after)

        self.picker = TaskPicker(self, self.ctx.model, none_entry=None)
        self.picker.picked.connect(self._task_picked)
        QShortcut(QKeySequence("Escape"), self, self.hide)
        QShortcut(QKeySequence("Ctrl+T"), self, self.pick_task)

    @staticmethod
    def _row(grid: QGridLayout, row: int, label: str, widget: QWidget, tip: str = "") -> None:
        name = QLabel(label, objectName="hint")
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(name, row, 0)
        grid.addWidget(widget, row, 1)
        if tip:
            widget.setToolTip(tip)

    def model(self) -> Model:
        return self.ctx.model()

    def today(self) -> date:
        return self.ctx.now().date()

    # ---- opening ----
    def open_for(self, draft: outlook.FrontDraft | None, task: str | None = None, screen=None) -> None:
        """Open for the draft (or none, a call or a talk) on ``task``, or the task its email's conversation names."""
        m = self.model()
        self.draft, self.email = draft, email_of(draft)
        self.task, self.task_how = None, ""
        if task in m.tasks:
            self.task = task
        elif self.email is not None:
            self.task, self.task_how = progress.task_for(m, self.email)
        self.people = progress.people_in(m, self.email.to, self.ctx.settings.me) if self.email and self.email.to else []
        self.choice = progress.last_follow_up(self.ctx.conn) if self.people else "none"
        self.line.clear()
        self.who.clear()
        self.message.clear()
        names = [p.name for p in m.people.values() if p.status == "active" and p.id != self.ctx.settings.me]
        completer = QCompleter(sorted(names), self.who)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.who.setCompleter(completer)
        self.render()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.x() + (area.width() - self.width()) // 2, area.y() + max(0, (area.height() - 420) // 3))
        bring_to_front(self)
        if self.task:
            self.line.setFocus()
        else:
            self.pick_task()

    # ---- drawing ----
    def render(self) -> None:
        m = self.model()
        e = self.email
        if e is None:
            self.email_line.setText(f"<span style='color:{tokens.LIGHT['text']}; font-weight:600'>No email in front</span><br>"
                                    "<span style='color:%s'>A call, a talk or a message: logged the same way, "
                                    "with nothing to send.</span>" % tokens.LIGHT["text2"])
        else:
            where = "a reply in the reading pane" if e.inline else "a draft in its own window"
            to = f"To {esc(e.to.split(';')[0].split('<')[0].strip())}" + (" and others" if ";" in e.to else "") if e.to else "To: DocRepo couldn't read it"
            self.email_line.setText(f"<span style='color:{tokens.LIGHT['text']}; font-weight:600'>{esc(e.subject or '(no subject yet)')}</span><br>"
                                    f"<span style='color:{tokens.LIGHT['text2']}'>{to} · {where}</span>")
        if self.task and self.task in m.tasks:
            how = f"  ·  {self.task_how}" if self.task_how else ""
            self.task_button.setText(f"{m.tasks[self.task].title}{how}")
        else:
            self.task_button.setText("# a task")
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for p in self.people:
            chip = QPushButton(f"{m.person_name(p)}  ✕", objectName="today")
            chip.setToolTip(f"Not waiting on {m.person_name(p)}")
            chip.clicked.connect(lambda _=False, who=p: self.drop_person(who))
            self.chips.addWidget(chip)
        self.who.setPlaceholderText("Add a person" if self.people else "Nobody: just log it")
        self.who_note.setText(("From the email's To, matched in People. " if self.email and self.email.to else "Type a name from People. ")
                              + "Empty: no wait, only the line.")
        if not self.people and self.choice != "none":
            self.choice = "none"
        for b in self.follow.buttons():
            key = b.property("key")
            b.setChecked(key == self.choice)
            b.setEnabled(bool(self.people) or key == "none")
        day = self.follow_day()
        name = ", ".join(m.person_name(p).split()[0] for p in self.people[:2]) + (" and others" if len(self.people) > 2 else "")
        title = m.tasks[self.task].title if self.task in m.tasks else "the task"
        self.follow_note.setText(f"If {name} hasn't replied by {long_date(day, self.today())}, {title} comes back on Today." if day and self.people
                                 else "No follow-up: nothing comes back by itself.")
        t = m.tasks.get(self.task or "")
        self.state_line.setText(f"{t.state} → In progress" if t and t.state in ("Not started", "Parked") else (t.state if t else ""))
        sends = self.sends()
        self.enter.setText("Send and log" if sends else "Log")
        self.enter.setToolTip("Enter")
        if self.email is None:
            self.after.setText("Nothing is sent: the line, the wait and the follow-up are kept.")
        elif sends:
            self.after.setText("DocRepo sends this email for you, held a minute in the Outbox.")
        elif self.email.inline:
            self.after.setText("Outlook won't let a program send a reply in the reading pane: Enter logs, then press Send there.")
        else:
            self.after.setText("Then the email comes to the front: press Send.")

    def sends(self) -> bool:
        """Whether Enter sends (decision 590 A): a draft in its own window, with Settings' Log progress sends on."""
        return self.email is not None and not self.email.inline and self.ctx.settings.progress_sends

    def follow_day(self) -> date | None:
        return progress.follow_up_day(self.choice, self.today(), _workdays(self.ctx.settings))

    # ---- the fields ----
    def pick_task(self) -> None:
        self.picker.popup(self.task_button.mapToGlobal(QPoint(0, self.task_button.height())))

    def _task_picked(self, task_id: str | None) -> None:
        if task_id:
            self.task, self.task_how = task_id, ""
            self.render()
            self.line.setFocus()

    def _line_typed(self, text: str) -> None:
        if text == "#":  # # in an empty line picks the task, as in the capture window
            self.line.clear()
            self.pick_task()

    def add_person(self) -> None:
        words = self.who.text().strip().casefold()
        if not words:
            return
        m = self.model()
        found = [p.id for p in m.people.values() if p.status == "active" and (p.name.casefold() == words or words in p.name.casefold())]
        if len(found) != 1:
            self.message.setText("Type a name from People, as the list shows it." if not found else "Several match: type more of the name.")
            return
        if found[0] not in self.people:
            self.people.append(found[0])
            if self.choice == "none":
                self.choice = progress.last_follow_up(self.ctx.conn)
        self.who.clear()
        self.message.clear()
        self.render()
        self.who.setFocus()

    def drop_person(self, person: str) -> None:
        self.people = [p for p in self.people if p != person]
        self.render()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        from PySide6.QtCore import QEvent

        if watched is self.who and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Backspace and not self.who.text() and self.people:
            self.people.pop()
            self.render()
            return True
        return super().eventFilter(watched, event)

    def _followed(self, n: int) -> None:
        self.choice = progress.FOLLOW_UPS[n][0]
        self.render()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.focusWidget() is not self.who:
            self.submit()
            return
        super().keyPressEvent(event)

    # ---- Enter ----
    def submit(self) -> None:
        """Keep it all, then send (decision 590 A) or bring the draft back for the owner to send."""
        if not self.task:
            self.pick_task()
            return
        now = self.ctx.now()
        try:
            done = progress.log_progress(self.ctx.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id=self.task,
                                         line=self.line.text(), on=self.people, follow_up=self.follow_day() if self.people else None,
                                         at=now, email=self.email, choice=self.choice)
        except SaveError as e:
            self.message.setText(str(e))
            (self.task_button if e.focus == "task" else self.line).setFocus()
            return
        m = self.model()
        title = m.tasks[done.task].title
        wait = f": waiting on {waits.who(m, waits.current(m, done.task))}" if done.wait and waits.current(m, done.task) else ""
        follow = f", follow up {long_date(date.fromisoformat(done.follow_up), self.today())}" if done.follow_up else ""
        said, trouble = f"Logged on {title}{wait}{follow}.", False
        if self.draft is not None:
            sent = False
            if self.sends():
                try:
                    outlook.send_draft(self.draft, now)
                    sent = True
                except outlook.OutlookError as e:
                    said, trouble = f"{said} Outlook didn't send it ({e}): press Send in Outlook.", True
            if sent:
                said = f"Sent, and l{said[1:]}"
            else:
                outlook.show_draft(self.draft)
                if not trouble:
                    said = f"{said} Press Send in Outlook."
            self.ctx.t_mail_opened()  # its sent copy is watched for (release 5.123)
        self.hide()
        self.app.progress_logged(done, said, trouble)
