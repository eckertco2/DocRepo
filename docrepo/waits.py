"""Waits (release 5.139, the design workspace's ``docs/mods/email-progress-plan.md``, decisions 580, 581, 588 and 593).

**Waiting** is a mark on a task, not a state (decision 580): the owner sent or asked something and waits for an answer
from one or more people, since a day, until the wait ends. A task has at most one open wait; the task stays In progress.

- **What starts one:** Log progress with someone in Waiting on (``docrepo.progress``), and Ask for an update, whose
  "asked Mon" this replaces (decision 593).
- **What ends it** (decision 581): a reply (``replied_by``: an email captured on the task in the wait's email
  conversation, other than the owner's own sent copy, or any email captured on the task from a person waited on, by their
  address or name in People); **Got it**; a newer wait on the task; or the task closed or discarded, which ``current``
  treats as ended. The follow-up day doesn't end it: from that day it's late.
- **The follow-up** (decision 588) is the task's Reminder, so decision 415's rule brings the task back on Today (decision
  396: no new date kind). An earlier reminder of the task's own stays and comes first, and when it's used the follow-up
  takes its place (``after_reminder``); a later one is kept with the wait and comes back once the follow-up has come, or
  when the wait ends first. A wait that ends before its follow-up day takes away the reminder it set.

How it reads (``words``): "waiting on Dana since Thu · follow up Tue" on the status card, "waiting on Dana · Thu" on a
row, "no reply from Dana since Thu" once the follow-up day has come. This module is what the task tile reads.
"""
from __future__ import annotations

import logging
import sqlite3
import weakref
from collections.abc import Collection
from datetime import date, datetime, timedelta

from docrepo import conversations
from docrepo.dates import WEEKDAYS, long_date, short, to_date
from docrepo.db import get_state, transaction
from docrepo.later import on_a_workday, workdays_after
from docrepo.model import Capture, Model, Wait

log = logging.getLogger(__name__)

#: How a wait ended (``waits.ended_by``).
REPLY, GOT_IT, LOGGED_AGAIN = "reply", "got it", "logged again"
#: The status log's field for a wait's start and end, and the ``via`` of Got it.
FIELD = "Waiting"
GOT_IT_VIA = "Got it"

__all__ = ["Wait", "current", "open_waits", "start", "end", "reminder_for", "after_reminder", "replied_by", "ended_by_captures",
           "words", "tip", "row_text", "who"]

_OPEN: "weakref.WeakKeyDictionary[Model, dict[str, Wait]]" = weakref.WeakKeyDictionary()


def stamp_of(at: datetime) -> str:
    return at.strftime("%Y-%m-%d %H:%M:%S")


def open_waits(m: Model) -> dict[str, Wait]:
    """Each task's open wait, on a task that's open and not discarded. Worked out once per model."""
    cached = _OPEN.get(m)
    if cached is not None:
        return cached
    out: dict[str, Wait] = {}
    for w in m.waits:
        t = m.tasks.get(w.task)
        if w.ended or t is None or t.discarded or t.state == "Closed":
            continue
        out[w.task] = w  # the newest wins; starting one ends the one before anyway
    _OPEN[m] = out
    return out


def current(m: Model, task_id: str) -> Wait | None:
    """The task's open wait, or None."""
    return open_waits(m).get(task_id)


# ---- the follow-up and the reminder (decision 588) ----
#: Follow up's choices, the first three in workdays.
FOLLOW_UPS: tuple[tuple[str, str], ...] = (("1d", "Tomorrow"), ("2d", "2 days"), ("3d", "3 days"), ("1w", "1 week"), ("2w", "2 weeks"),
                                           ("none", "None"))
DEFAULT_FOLLOW_UP = "3d"
#: The last choice, remembered between runs.
LAST_KEY = "progress_follow_up"


def follow_up_day(choice: str, today: date, workdays: Collection[int]) -> date | None:
    """The day a choice brings the task back: 1 to 3 workdays on, or a week or two on (moved to a workday); None for None."""
    if choice in ("1d", "2d", "3d"):
        return workdays_after(today, int(choice[0]), workdays)
    if choice in ("1w", "2w"):
        return on_a_workday(today + timedelta(days=7 if choice == "1w" else 14), workdays)
    return None


def last_follow_up(conn: sqlite3.Connection) -> str:
    """The last Follow up chosen, other than None; 3 days at first."""
    value = get_state(conn, LAST_KEY)
    return value if value in dict(FOLLOW_UPS) and value != "none" else DEFAULT_FOLLOW_UP


def _own_reminder(m: Model, task_id: str) -> str | None:
    """The task's own reminder, apart from one its open wait set: the one that wait keeps, when the task's reminder is
    its follow-up."""
    t = m.task(task_id)
    w = current(m, task_id)
    if w is not None and w.follow_up and t.reminder == w.follow_up:
        return w.reminder_before
    return t.reminder


def reminder_for(m: Model, task_id: str, follow_up: date | None) -> str | None:
    """The Reminder a task should have when a wait with this follow-up starts: the follow-up day, unless the task's own
    reminder comes first, which then stays."""
    own = _own_reminder(m, task_id)
    day = follow_up.isoformat() if follow_up else None
    if day is None or (own and own <= day):
        return own
    return day


def after_reminder(m: Model, task_id: str, today: date, following: str | None) -> str | None:
    """The Reminder a task should have once today's has put it on Today, given what it would have with no wait
    (``following``: none, or a repeat's next time). An open wait's follow-up still to come takes the place of an earlier
    reminder of the task's own; once the follow-up has come, the task's own later reminder the wait kept comes back."""
    w = current(m, task_id)
    if w is None or not w.follow_up:
        return following
    day = today.isoformat()
    if w.follow_up > day:
        return min(following, w.follow_up) if following else w.follow_up
    kept = w.reminder_before if w.reminder_before and w.reminder_before > day else None
    if following and kept:
        return min(following, kept)
    return following or kept


# ---- starting and ending ----
def _log(conn: sqlite3.Connection, task: str, at: str, before: str | None, after: str | None, via: str) -> None:
    conn.execute("INSERT INTO status_log (task, at, field, from_value, to_value, via) VALUES (?, ?, ?, ?, ?, ?)",
                 (task, at, FIELD, before, after, via))


def _names(m: Model, people: tuple[str, ...] | list[str]) -> str:
    return ", ".join(m.person_name(p) for p in people)


def start(conn: sqlite3.Connection, m: Model, task_id: str, *, at: str, line: str, on: list[str], follow_up: date | None, via: str,
          t_mail: int | None = None, capture: str | None = None) -> int:
    """Start a wait on a task, ending the one it has (``logged again``), with the status log's line. ``m`` is the model as
    it was before the task's Reminder was set for it (``reminder_for``), so the wait keeps the task's own later reminder.
    Returns its ID."""
    old = current(m, task_id)
    own = _own_reminder(m, task_id)
    if old is not None:
        end(conn, m, old, at, LOGGED_AGAIN, via)
    day = follow_up.isoformat() if follow_up else None
    kept = own if day and own and own > day else None
    with transaction(conn):
        cur = conn.execute("INSERT INTO waits (task, since, line, t_mail, capture, follow_up, reminder_before) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (task_id, at, line, t_mail, capture, day, kept))
        conn.executemany("INSERT OR IGNORE INTO wait_people (wait, person) VALUES (?, ?)", [(cur.lastrowid, p) for p in dict.fromkeys(on)])
        _log(conn, task_id, at, None, _names(m, on), via)
    log.info("wait %s started on %s, on %d people, follow-up %s", cur.lastrowid, task_id, len(on), day or "none")
    return int(cur.lastrowid)


def end(conn: sqlite3.Connection, m: Model, w: Wait, at: str, by: str, via: str) -> str | None:
    """End a wait (decision 581), with the status log's line. Returns the Reminder the task should have now when the wait
    set the one it has: the task's own later one it kept, or "" for none; None leaves the reminder as it is."""
    with transaction(conn):
        conn.execute("UPDATE waits SET ended = ?, ended_by = ? WHERE id = ? AND ended IS NULL", (at, by, w.id))
        _log(conn, w.task, at, _names(m, w.on), None, via)
    log.info("wait %s on %s ended: %s", w.id, w.task, by)
    t = m.tasks.get(w.task)
    if by == LOGGED_AGAIN or t is None or not w.follow_up or t.reminder != w.follow_up:
        return None
    back = w.reminder_before if w.reminder_before and w.reminder_before > at[:10] else None
    return back or ""


# ---- what a reply is (decision 581) ----
def _from(sender: str, addresses: set[str], names: set[str]) -> bool:
    s = sender.casefold()
    return any(a in s for a in addresses) or s.split("<")[0].strip().strip('"') in names


def replied_by(m: Model, w: Wait, c: Capture) -> bool:
    """Whether a capture on the wait's task answers it: an email in the wait's email conversation, sent since the wait
    started, that isn't the owner's own sent copy (whose whole conversation index is the T-mail's); or an email from a
    person waited on, by their address or whole name in People."""
    tm = next((x for x in m.t_mails if x.id == w.t_mail), None) if w.t_mail else None
    own_index = conversations.clean_hex(tm.conversation_index) if tm else ""
    key = tm.conversation if tm else ""
    addresses = {m.people[p].email.casefold() for p in w.on if p in m.people and m.people[p].email}  # type: ignore[union-attr]
    names = {m.person_name(p).casefold() for p in w.on}
    for e in c.emails:
        index = conversations.clean_hex(e.conversation_index)
        recent = not e.sent or e.sent[:10] >= w.since[:10]
        if key and recent and conversations.key(index) == key and index != own_index:
            return True
        if e.sender and _from(e.sender, addresses, names):
            return True
    return False


def ended_by_captures(conn: sqlite3.Connection, capture_ids: list[str], at: str, via: str) -> list[tuple[str, str | None]]:
    """After captures land (saved, or filed to a task): each open wait on their tasks that one of them answers ends, as a
    reply. Returns (task, the Reminder it should have now: "" for none, None to leave it) for each wait ended."""
    m = Model(conn)
    out: list[tuple[str, str | None]] = []
    for cid in capture_ids:
        c = m.captures.get(cid)
        if c is None or c.discarded or not c.emails:
            continue
        for task in m.capture_tasks(c):
            w = current(m, task)
            if w is None or max(c.saved, c.filed or "") < w.since or not replied_by(m, w, c):
                continue
            out.append((task, end(conn, m, w, at, REPLY, via)))
            m = Model(conn)
    return out


# ---- the words (decision 580) ----
def _first(m: Model, p: str) -> str:
    name = m.person_name(p)
    return name.split()[0] if name.split() else name


def who(m: Model, w: Wait, full: bool = False) -> str:
    """"Dana", "Dana and Mike", "Dana and 2 more"; with ``full``, everyone's whole name."""
    names = [m.person_name(p) if full else _first(m, p) for p in w.on]
    if not names:
        return "nobody"
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1] if full else f"{names[0]} and {len(names) - 1} more"


def day_words(stamp: str, today: date) -> str:
    """"today", "Mon" within the week, else "4 Nov"."""
    day = to_date(stamp[:10])
    n = (today - day).days
    if n <= 0:
        return "today"
    return WEEKDAYS[day.weekday()] if n < 7 else short(day, today)


def _ahead(day: date, today: date) -> str:
    """A day to come: its weekday within the week, else "24 Nov"."""
    return WEEKDAYS[day.weekday()] if 0 < (day - today).days < 7 else short(day, today)


def words(m: Model, w: Wait, today: date, row: bool = False) -> str:
    """The mark's words: "waiting on Dana since Thu · follow up Tue" (the status card), "waiting on Dana · Thu" (a row),
    "no reply from Dana since Thu" once the follow-up day has come."""
    since = day_words(w.since, today)
    if w.late(today):
        return f"no reply from {who(m, w)} since {since}"
    if row:
        return f"waiting on {who(m, w)} · {since}"
    follow = f" · follow up {_ahead(to_date(w.follow_up), today)}" if w.follow_up else ""
    return f"waiting on {who(m, w)} since {since}{follow}"


def tip(m: Model, w: Wait, today: date) -> str:
    """The longer words, for a tooltip: "Waiting on Dana Ortiz since Thu 12 Nov: asked Dana for the drawings. Follow up
    Tue 17 Nov."."""
    line = f": {w.line.rstrip('.')}" if w.line else ""
    follow = f" Follow up {long_date(to_date(w.follow_up), today)}." if w.follow_up else " No follow-up set."
    return f"Waiting on {who(m, w, full=True)} since {long_date(to_date(w.since[:10]), today)}{line}.{follow}"


def row_text(m: Model, task_id: str, today: date) -> str:
    """A row's quiet mark, or "" when the task isn't waiting."""
    w = current(m, task_id)
    return words(m, w, today, row=True) if w else ""
