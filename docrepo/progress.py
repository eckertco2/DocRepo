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
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from docrepo import conversations, edits, sent_watch, tasks, waits
from docrepo.db import set_state
from docrepo.model import Model
from docrepo.save import CaptureDraft, EmailItem, SaveError, save_capture

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


def log_progress(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, *, task_id: str, line: str,
                 on: Sequence[str], follow_up: date | None, at: datetime, email: Email | None = None, choice: str = "",
                 state: str | None = None, done_today: bool = False) -> Logged:
    """Keep one Log progress (decisions 586 to 592). Raises SaveError, keeping nothing, when the task is gone or closed,
    the line is empty, or it's to wait with nobody named.

    ``state`` (release 5.155, decision 695) is one of ``STATES``' keys: Waiting starts a wait on ``on``; the others start
    none and leave ``on`` and ``follow_up`` aside; Parked and Closed set the task's state, Closed the task alone (696). None
    is 5.139's rule: Waiting when ``on`` names someone in People, else In progress; Not started or Parked is made In
    progress either way. ``done_today`` (decision 697) closes the task's Today item as Done, as the side panel's Done for
    today does, with no Update opened; Closed closes it too. A task not on Today has nothing to close."""
    line = " ".join(line.split())
    m = Model(conn)
    t = m.tasks.get(task_id)
    if t is None or t.discarded:
        raise SaveError("Pick a task first: type # or a few words.", "task")
    if t.collection:  # release 5.167, decision 780: a collection isn't work, so there's no progress to log on it
        raise SaveError(f"{t.title} is a collection, not a task: pick one of its tasks.", "task")
    if t.state == "Closed":
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
    day = follow_up if people else None
    update: dict[str, object] = {"current_status": line}
    if t.state != TASK_STATE[state]:  # Not started or Parked made In progress (decision 589); or Parked, or Closed
        update["state"] = TASK_STATE[state]
    if people:
        reminder = waits.reminder_for(m, task_id, day)
        if reminder != t.reminder:
            update["reminder"] = reminder
    result = save_capture(conn, data_root, fs, settings, CaptureDraft(content=line, task=task_id, types={"update"}, update=update), at)
    capture = result.capture_id or ""
    stamp = waits.stamp_of(at)
    t_mail = None
    if email is not None:
        t_mail = conversations.record_t_mail(conn, task_id, KIND, stamp, email.index, untagged=True)
        if t_mail is not None and not conversations.key(email.index) and email.entry_id:
            sent_watch.keep_draft(conn, t_mail, email.entry_id, email.store_id)  # a new email: known by its draft (5.141)
    wait = None
    if people:
        wait = waits.start(conn, m, task_id, at=stamp, line=line, on=people, follow_up=day, via=capture or LABEL, t_mail=t_mail,
                           capture=capture or None)
    if choice in dict(FOLLOW_UPS) and choice != "none" and people:
        set_state(conn, LAST_KEY, choice)
    closed_today = False
    if done_today or state == CLOSED:  # under Done today, where Back on Today puts it back (decision 697)
        now = Model(conn)
        item = next((a for a in now.today_items() if a.subject == task_id), None)
        if item is not None:
            edits.close_today_item(conn, data_root, fs, item.id, "Done", at, now)
            closed_today = True
    after = Model(conn).task(task_id)
    log.info("Log progress on %s: %s, capture %s, T-mail %s, wait %s, Today item closed %s", task_id, state, capture, t_mail, wait,
             closed_today)
    return Logged(task_id, capture, t_mail, wait, after.state, after.reminder, day.isoformat() if day else None, closed_today)


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
