"""Log progress (release 5.139, the design workspace's ``docs/mods/email-progress-plan.md``, decisions 580 to 598): what the
Log progress window keeps, with no Qt, so the tests feed it directly.

With a finished draft in front in Outlook, or none (a call or a talk, decision 592), the owner gives a task, a line, who
they're waiting on and when to follow up. Enter keeps, in one go:
- **an Update capture** on the task (decision 591): the line as its text and the task's current status (decision 586),
  Not started or Parked made In progress (decision 589), and the Reminder the follow-up wants (decision 588);
- **the email** as a T-mail of kind ``progress``, so its sent copy is captured on the task when Outlook files it (release
  5.123) and its replies find the task: by its index, or, a new email Outlook wouldn't let DocRepo tag, by its draft (5.141);
- **a wait** on the people named (decision 580, ``docrepo.waits``), with the T-mail and the capture.

Sending is the window's (decision 590), once this is kept. ``got_it`` ends a wait by the owner's word.

Since release 5.155 (the design workspace's ``docs/mods/log-progress-choices-plan.md``, decisions 695 to 697) the owner
picks the **state** the line leaves the task in (``STATES``): In progress, Waiting on a reply (In progress with a wait, as
decision 580 has it, and the only choice that starts one), Parked or Closed (the task alone: its open subtasks stay open,
as Edit task's State leaves them). **Done for today** closes the task's Today item as Done, as the Today side panel's does
(decision 420), with no Update opened, since the line is the update; Closed always closes it.

Since release 5.164 (the design workspace's ``docs/mods/log-progress-whole-plan.md``, decisions 751 and 754) it's all or
nothing as far as it can be. ``save_capture`` keeps the Update first; it writes capture.md and the pages too, so it can't
join a transaction of its caller's. Everything after it (the T-mail, its draft, the wait, the last follow-up and the
Today item) is then one transaction: a failure there keeps none of it and raises ``NotAllKept``, which says so and names
the Update kept, and the window's next Enter passes it back as ``kept``, so it keeps no second Update. ``sending`` and
``not_sent`` mark a kept draft as sent by DocRepo around Log progress's send, so nothing of DocRepo's reads it on its
way out (``docrepo.sent_watch``).

Since release 5.166 (the same plan, decisions 757, 759 and 761):
- **Back on Today** (757): ``back``, the day the task comes back, whatever the state but Closed. It takes the task off
  Today now (its item closed as Done, under Done today) and sets its Reminder to that day, which puts it back (decision
  415); with a wait, that day is the wait's follow-up too, and the task's own earlier reminder still comes first (588).
  Its choices are Later's (``later.CHOICES``, or a day typed in Other…); the last one made with a wait is remembered.
- **An attached email** (759): ``attached``, the email selected in Outlook, read as Add selected Outlook email reads it,
  kept on the Update capture, so the task's page and its conversation show it with the line.
- **The next step** (761): ``log_next`` makes the task that comes next, under the logged task's parents, with no Update
  (nothing has been done on it), on Today or back on its day, with its wait.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from docrepo import agenda, conversations, edits, later, sent_watch, tasks, waits
from docrepo.db import set_state, transaction
from docrepo.layer0 import LinkRules
from docrepo.model import TODAY, Model
from docrepo.save import CaptureDraft, EmailItem, SaveError, email_rows, save_capture

if TYPE_CHECKING:
    from docrepo.config import Settings
    from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

#: The T-mail kind an email logged here is kept as (``t_mails.kind``, schema 26).
KIND = "progress"
#: The command's name and the window's title.
LABEL = "Log progress"
#: Follow up (decision 588), from ``docrepo.waits``.
FOLLOW_UPS, DEFAULT_FOLLOW_UP, LAST_KEY = waits.FOLLOW_UPS, waits.DEFAULT_FOLLOW_UP, waits.LAST_KEY
follow_up_day, last_follow_up = waits.follow_up_day, waits.last_follow_up

#: State's choices (release 5.155, decisions 695 and 696): the key ``log_progress`` takes, the dropdown's words, and what
#: each does. Not started isn't one: something was just done.
IN_PROGRESS, WAITING, PARKED, CLOSED = "In progress", "Waiting", "Parked", "Closed"
STATES: tuple[tuple[str, str, str], ...] = (
    (IN_PROGRESS, "In progress", "Logged, nothing to wait for"),
    (WAITING, "Waiting on a reply", "In progress, with a wait on someone"),
    (PARKED, "Parked", "Off the board until you pick it up"),
    (CLOSED, "Closed", "Finished: off Today too"),
)
#: The task's state after each choice: Waiting on a reply is In progress with a wait (decision 580).
TASK_STATE = {IN_PROGRESS: "In progress", WAITING: "In progress", PARKED: "Parked", CLOSED: "Closed"}
#: Back on Today's choices (decision 757): Later's, then Other…, a day typed.
BACK = later.CHOICES
OTHER = "other"
#: The next step's states (decision 761): something not yet done, or begun.
NOT_STARTED = "Not started"
NEXT_STATES: tuple[tuple[str, str, str], ...] = (
    (NOT_STARTED, "Not started", "Nothing done on it yet"),
    (IN_PROGRESS, "In progress", "Started"),
    (WAITING, "Waiting on a reply", "In progress, with a wait on someone"),
)
NEXT_STATE = {NOT_STARTED: "Not started", IN_PROGRESS: "In progress", WAITING: "In progress"}
#: What Enter says to Waiting on a reply with nobody in Waiting on.
NOBODY = "Who are you waiting on? Type a name from People, or pick another state."


@dataclass(frozen=True)
class Email:
    """The draft the window is for, as DocRepo could read it: its subject and conversation index (Outlook's guard allows
    both), its place in Drafts, whether it's an inline reply in the reading pane, and, from its copy read without Outlook,
    its To line and what it answers."""

    subject: str
    index: str = ""
    entry_id: str = ""
    store_id: str = ""
    inline: bool = False
    to: str = ""
    in_reply_to: str = ""
    refs: str = ""
    message_id: str = ""


def task_for(m: Model, email: Email) -> tuple[str | None, str]:
    """The task an email is for (decision 585), by K8's rule as the capture window fills its picker: its conversation, or
    the email it answers. With the words that say how; (None, "") when nothing says."""
    item = EmailItem(subject=email.subject, sender="", sent="", to=email.to, body="", conversation_index=email.index,
                     message_id=email.message_id, in_reply_to=email.in_reply_to, refs=email.refs)
    pick = conversations.pick_emails(m, [item])
    t = m.tasks.get(pick.task or "")
    if t is None or t.discarded or t.state == "Closed":
        return None, ""
    return t.id, "from conversation"


def people_in(m: Model, to: str, me: str | None) -> list[str]:
    """Waiting on, from an email's To line (decision 587): each active person in People whose address, or whole name, is
    in it, in the order they're written there; never the owner."""
    text = to.casefold()
    found: list[tuple[int, str]] = []
    for p in m.people.values():
        if p.id == me or p.status != "active":
            continue
        for needle in (p.email or "", p.name):
            at = text.find(needle.casefold()) if needle else -1
            if at >= 0:
                found.append((at, p.id))
                break
    return [p for _, p in sorted(found)]


class NotAllKept(SaveError):
    """The Update was kept and what comes after it wasn't (decision 754): ``capture`` is the Update, for ``kept`` on the
    next try."""

    def __init__(self, message: str, capture: str) -> None:
        super().__init__(message, "content")
        self.capture = capture


@dataclass(frozen=True)
class Logged:
    """What Enter kept: the Update capture, the T-mail, the wait, the task's state and Reminder after, and whether its Today
    item closed as Done (release 5.155, decision 697)."""

    task: str
    capture: str
    t_mail: int | None
    wait: int | None
    state: str
    reminder: str | None
    follow_up: str | None
    done_today: bool = False
    #: The day it comes back on Today (release 5.166, decision 757), or None.
    back: str | None = None


def log_progress(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, *, task_id: str, line: str,
                 on: Sequence[str], follow_up: date | None, at: datetime, email: Email | None = None, choice: str = "",
                 state: str | None = None, done_today: bool = False, kept: str | None = None, back: date | None = None,
                 attached: EmailItem | None = None) -> Logged:
    """Keep one Log progress (decisions 586 to 592). Raises SaveError, keeping nothing, when the task is gone or closed,
    the line is empty, or it's to wait with nobody named.

    ``state`` (release 5.155, decision 695) is one of ``STATES``' keys: Waiting starts a wait on ``on``; the others start
    none and leave ``on`` and ``follow_up`` aside; Parked and Closed set the task's state, Closed the task alone (696). None
    is 5.139's rule: Waiting when ``on`` names someone in People, else In progress; Not started or Parked is made In
    progress either way. ``done_today`` (decision 697) closes the task's Today item as Done, as the side panel's Done for
    today does, with no Update opened; Closed closes it too. A task not on Today has nothing to close.

    ``kept`` (release 5.164, decision 754) is the Update capture an earlier try kept before the rest failed
    (``NotAllKept``): this try keeps the rest only, with no second Update. Any other error (a busy database) is raised as
    it is, with nothing kept when it comes from the Update.

    ``back`` (release 5.166, decision 757) is the day the task comes back on Today, whatever the state but Closed: its
    Reminder is set to it, and its Today item closes as Done now; with a wait it's the follow-up, in place of
    ``follow_up``, which is 5.139's (a wait's follow-up, leaving Today as it is). ``attached`` (decision 759) is an email
    kept on the Update capture."""
    line = " ".join(line.split())
    m = Model(conn)
    t = m.tasks.get(task_id)
    if t is None or t.discarded:
        raise SaveError("Pick a task first: type # or a few words.", "task")
    if t.state == "Closed" and not kept:  # on a second try, Closed may be the Update's own doing
        raise SaveError(f"{t.title} is closed. Reopen it, or pick another task.", "task")
    if not line:
        raise SaveError("Say in a line what you sent or asked.", "content")
    people = [p for p in dict.fromkeys(on) if p in m.people]
    if state is None:
        state = WAITING if people else IN_PROGRESS
    if state not in TASK_STATE:
        raise ValueError(f"Not a Log progress state: {state!r}.")
    if state != WAITING:
        people = []
    elif not people:
        raise SaveError(NOBODY, "who")
    leaves = back is not None and state != CLOSED  # Back on Today (decision 757)
    day = back if leaves else follow_up if people else None
    update: dict[str, object] = {"current_status": line}
    if t.state != TASK_STATE[state]:  # Not started or Parked made In progress (decision 589); or Parked, or Closed
        update["state"] = TASK_STATE[state]
    if day is not None:  # a wait's follow-up keeps an earlier reminder of the task's own (588); Back alone sets it (757)
        reminder = waits.reminder_for(m, task_id, day) if people else day.isoformat()
        if reminder != t.reminder:
            update["reminder"] = reminder
    if kept:
        capture = kept
    else:
        files = email_rows(attached, LinkRules.of(settings)) if attached is not None else []
        result = save_capture(conn, data_root, fs, settings,
                              CaptureDraft(content=line, task=task_id, types={"update"}, update=update, files=files), at)
        capture = result.capture_id or ""
    stamp = waits.stamp_of(at)
    t_mail = wait = None
    closed_today = False
    try:
        with transaction(conn):  # the rest, all or nothing (decision 754)
            if email is not None:
                t_mail = conversations.record_t_mail(conn, task_id, KIND, stamp, email.index, untagged=True)
                if t_mail is not None and not conversations.key(email.index) and email.entry_id:
                    sent_watch.keep_draft(conn, t_mail, email.entry_id, email.store_id)  # a new email: known by its draft (5.141)
            if people:
                wait = waits.start(conn, m, task_id, at=stamp, line=line, on=people, follow_up=day, via=capture or LABEL, t_mail=t_mail,
                                   capture=capture or None)
            if choice in dict(FOLLOW_UPS) and people:
                set_state(conn, LAST_KEY, choice)
            if done_today or state == CLOSED or leaves:  # under Done today, where Back on Today puts it back (697, 757)
                now = Model(conn)
                item = next((a for a in now.today_items() if a.subject == task_id), None)
                if item is not None:
                    edits.close_today_item(conn, data_root, fs, item.id, "Done", at, now)
                    closed_today = True
    except Exception as e:  # noqa: BLE001 - whatever it was, the Update is kept and the rest isn't: said, and tried again
        log.warning("Log progress on %s: capture %s kept, the rest rolled back (%s)", task_id, capture, type(e).__name__)
        raise NotAllKept(f"The update was kept. {_missing(people, email, done_today or state == CLOSED or leaves)}: press Enter to try again.",
                         capture) from e
    after = Model(conn).task(task_id)
    log.info("Log progress on %s: %s, capture %s, T-mail %s, wait %s, Today item closed %s", task_id, state, capture, t_mail, wait,
             closed_today)
    return Logged(task_id, capture, t_mail, wait, after.state, after.reminder, day.isoformat() if day and people else None, closed_today,
                  day.isoformat() if leaves and day else None)


def back_day(choice: str, today: date, workdays: Collection[int]) -> date | None:
    """The day a Back on Today choice brings the task back (decision 757), as Later's (``later.later_day``); None for
    any other key."""
    return later.later_day(choice, today, workdays) if choice in dict(BACK) else None


@dataclass(frozen=True)
class Next:
    """What Log, then next… kept (decision 761): the new task, its wait, whether it's on Today, and its Reminder."""

    task: str
    wait: int | None
    on_today: bool
    reminder: str | None


def log_next(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, *, parent: str | None, title: str,
             state: str, on: Sequence[str], at: datetime, today: bool = True, back: date | None = None, choice: str = "") -> Next:
    """The next step (release 5.166, decision 761): a new task under ``parent`` (None: a top-level task), named ``title``,
    in ``state`` (``NEXT_STATES``: Waiting starts a wait on ``on``), with no Update, since nothing has been done on it.
    ``today`` puts it on Today; ``back`` instead sets its Reminder to that day, which puts it on Today then (decision 415),
    and is a wait's follow-up too. Raises SaveError, making nothing, when the title is empty, the parent is gone or
    closed, or it's to wait with nobody named."""
    title = " ".join(title.split())
    m = Model(conn)
    if not title:
        raise SaveError("Name the next step in a line.", "content")
    if parent is not None:
        p = m.tasks.get(parent)
        if p is None or p.discarded or p.state == "Closed":
            raise SaveError("The task to put it under is gone or closed: pick another.", "task")
    if state not in NEXT_STATE:
        raise ValueError(f"Not a next step's state: {state!r}.")
    people = [x for x in dict.fromkeys(on) if x in m.people] if state == WAITING else []
    if state == WAITING and not people:
        raise SaveError(NOBODY, "who")
    reminder = back.isoformat() if back is not None else None
    put = today and back is None
    stamp = waits.stamp_of(at)
    with transaction(conn):
        task = tasks.create_task(conn, settings, title=title, at=at, created_by=LABEL, parents=[parent] if parent else [],
                                 state=NEXT_STATE[state], reminder=reminder)
        if put:
            agenda.add_item(conn, subject=task, target=TODAY, note="", added=stamp, added_by=LABEL)
        wait = None
        if people:
            wait = waits.start(conn, Model(conn), task, at=stamp, line=title, on=people, follow_up=back, via=LABEL)
            if choice in dict(BACK):
                set_state(conn, LAST_KEY, choice)
    problems: list[str] = []
    edits.write_touched_pages(conn, data_root, fs, at, problems, [task, *([parent] if parent else [])], m)
    log.info("Log progress, next step: %s under %s, %s, on Today %s, wait %s", task, parent or "(top level)", state, put, wait)
    return Next(task, wait, put, reminder)


def _missing(people: list[str], email: Email | None, today: bool) -> str:
    """What ``NotAllKept`` says wasn't kept: the first of what there was to keep after the Update."""
    if people:
        return "The wait wasn't started"
    if email is not None:
        return "The email wasn't kept with it"
    return "Its Today item wasn't closed" if today else "The rest wasn't kept"


def sending(conn: sqlite3.Connection, done: Logged, subject: str, at: datetime) -> None:
    """Just before Log progress sends the draft (decision 751): a kept draft is marked as sent by DocRepo, so nothing of
    DocRepo's fetches it again on its way out."""
    if done.t_mail is not None:
        sent_watch.sent_by_docrepo(conn, done.t_mail, subject, at)


def not_sent(conn: sqlite3.Connection, done: Logged) -> None:
    """Outlook refused the send: the draft is watched as before, for the owner to send."""
    if done.t_mail is not None:
        sent_watch.not_sent(conn, done.t_mail)


def got_it(conn: sqlite3.Connection, settings: Settings, task_id: str, at: datetime) -> bool:
    """Got it (decision 581): the task's wait ends by the owner's word, and the reminder it set goes with it. False when
    the task isn't waiting."""
    m = Model(conn)
    w = waits.current(m, task_id)
    if w is None:
        return False
    back = waits.end(conn, m, w, waits.stamp_of(at), waits.GOT_IT, waits.GOT_IT_VIA)
    if back is not None:
        tasks.update_task(conn, settings, task_id, at=at, via=waits.GOT_IT_VIA, reminder=back or None)
    return True


def replies_landed(conn: sqlite3.Connection, settings: Settings, capture_ids: list[str], at: datetime, via: str) -> list[str]:
    """After captures land on tasks: the waits they answer end (decision 581), each taking away the reminder it set.
    Returns the tasks whose wait ended."""
    ended = waits.ended_by_captures(conn, capture_ids, waits.stamp_of(at), via)
    for task, back in ended:
        if back is not None:
            tasks.update_task(conn, settings, task, at=at, via=via, reminder=back or None)
    return [task for task, _ in ended]
