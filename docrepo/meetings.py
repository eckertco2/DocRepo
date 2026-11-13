"""Today's meetings from the Outlook calendar (release 5.127; the design workspace's ``docs/mods/cold-eyes-plan.md``, section 5,
decisions 488 to 495). No Qt here: the windows draw what this works out.

- **What's read** (488): ``Appointment``, today's appointments in the default calendar with only their subject, start,
  end, location, whether all day, busy status, meeting status, sensitivity and whether recurring. ``outlook.todays_appointments``
  reads them, never starting Outlook, and writes nothing there.
- **Which show** (489, 490; ``day_view``): timed ones in order, Free ones in grey, all-day ones in one line, cancelled ones
  left out (the read leaves them out), a private one with its time and "Private appointment" only. Past ones fold into
  "2 earlier", and the next one is marked with the minutes until it starts.
- **Links** (491): a subject's key (``subject_key``: case, RE:, FW:, Updated: and the like set aside) linked once to a task or
  a person, in ``meeting_links`` (schema 26), so a weekly meeting is linked once. ``suggest`` offers the meeting task whose
  title has the subject's words, for the owner to confirm once with Link.
- **When it's read** (493; ``TodayCalendar``): when Today is drawn and the list is 5 minutes old, and on F5. A read that
  fails keeps the last list, and its problem is said once.
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from docrepo.db import transaction
from docrepo.model import Model, Task, is_person

log = logging.getLogger(__name__)

#: Outlook's BusyStatus (OlBusyStatus): Free shows in grey; Tentative says so.
FREE, TENTATIVE, BUSY = 0, 1, 2
#: How old the list may get while Today or the side panel is showing before it's read again (decision 493).
STALE_AFTER = timedelta(minutes=5)

#: What Outlook and mail programs put before a subject, set aside in its key (decision 491): replies and forwards, in English
#: and the common European forms, an update or cancellation of an invitation, and a reply to one.
_PREFIX_WORDS = ("re", "fw", "fwd", "aw", "wg", "sv", "vs", "tr", "rv", "antw", "updated", "update", "canceled", "cancelled",
                 "accepted", "declined", "tentative", "tentatively accepted", "new time proposed", "copy", "invitation",
                 "updated invitation", "reminder")
_PREFIX = re.compile(r"^\s*(?:\[[^\]]{0,40}\]\s*|(?:" + "|".join(re.escape(w) for w in sorted(_PREFIX_WORDS, key=len, reverse=True))
                     + r")\s*:\s*)", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]+")
#: Small words left out when a subject's words are matched with a meeting task's title.
FILLER = frozenset({"a", "an", "and", "the", "of", "for", "with", "to", "on", "in", "at", "re"})


@dataclass(frozen=True)
class Appointment:
    """One appointment of today's, as read (decision 488). Times are local wall-clock times, to the minute. A private one's
    subject and location aren't read, so they're empty."""

    subject: str
    start: datetime
    end: datetime
    location: str = ""
    all_day: bool = False
    busy: int = BUSY
    private: bool = False
    recurring: bool = False

    @property
    def free(self) -> bool:
        return self.busy == FREE

    @property
    def title(self) -> str:
        """What a row says: the subject, or "Private appointment" (decision 489)."""
        return "Private appointment" if self.private else (self.subject or "(no subject)")

    @property
    def key(self) -> str:
        """Its subject's key, how its link is found; "" for a private one, which is never linked."""
        return "" if self.private else subject_key(self.subject)


def subject_key(subject: str) -> str:
    """A subject's key (decision 491): without RE:, FW:, Updated: and the like (and a tag in brackets) at its start, as many
    as there are, its spaces made single, in lower case. "RE: Updated: Business  Team meeting" is "business team meeting"."""
    text = subject or ""
    while (m := _PREFIX.match(text)) and m.end():
        text = text[m.end():]
    return " ".join(text.casefold().split())


def words_of(text: str) -> frozenset[str]:
    """A text's words, in lower case, without the small ones (``FILLER``)."""
    return frozenset(_WORD.findall(text.casefold())) - FILLER


# ---- links (schema 26) ----
@dataclass(frozen=True)
class Link:
    """A meeting link: the subject's key, the subject as it was when linked, and the task or the person it's linked to."""

    key: str
    subject: str
    task: str | None
    person: str | None
    linked: str

    @property
    def target(self) -> str:
        return self.task or self.person or ""


def links(conn: sqlite3.Connection) -> dict[str, Link]:
    """Every meeting link, by its key, in the order they were made."""
    rows = conn.execute("SELECT key, subject, task, person, linked FROM meeting_links ORDER BY linked, key").fetchall()
    return {r["key"]: Link(r["key"], r["subject"], r["task"], r["person"], r["linked"]) for r in rows}


class LinkError(ValueError):
    """A link that can't be made as asked."""


def set_link(conn: sqlite3.Connection, subject: str, target: str, at: datetime) -> Link:
    """Link a subject to a task or a person, in place of any link its key had. Raises LinkError when the subject has no key
    or the target isn't there."""
    key = subject_key(subject)
    if not key:
        raise LinkError("This appointment has no subject to remember a link by.")
    table = "people" if is_person(target) else "tasks"
    found = conn.execute("SELECT 1 FROM people WHERE id = ?" if table == "people" else "SELECT 1 FROM tasks WHERE id = ?", (target,)).fetchone()
    if found is None:
        raise LinkError(f"There's no {'person' if table == 'people' else 'task'} {target}.")
    task, person = (None, target) if table == "people" else (target, None)
    stamp = at.strftime("%Y-%m-%d %H:%M:%S")
    with transaction(conn):
        conn.execute("INSERT INTO meeting_links (key, subject, task, person, linked) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET subject = excluded.subject, task = excluded.task, person = excluded.person, "
                     "linked = excluded.linked", (key, " ".join(subject.split()), task, person, stamp))
    log.info("meeting link made to %s", target)  # the subject is the calendar's words, so only the target's ID is logged
    return Link(key, " ".join(subject.split()), task, person, stamp)


def remove_link(conn: sqlite3.Connection, key: str) -> Link | None:
    """Forget a link (Settings' Remove). Returns it as it was, for Undo, or None when there was none."""
    old = links(conn).get(key)
    if old is None:
        return None
    with transaction(conn):
        conn.execute("DELETE FROM meeting_links WHERE key = ?", (key,))
    log.info("meeting link to %s removed", old.target)
    return old


def put_back(conn: sqlite3.Connection, link: Link | None, key: str) -> str:
    """Undo a link or a Remove: the key's link as it was before (``link``), or none. Returns the key."""
    with transaction(conn):
        conn.execute("DELETE FROM meeting_links WHERE key = ?", (key,))
        if link is not None:
            conn.execute("INSERT INTO meeting_links (key, subject, task, person, linked) VALUES (?, ?, ?, ?, ?)",
                         (link.key, link.subject, link.task, link.person, link.linked))
    return key


def live_target(model: Model, link: Link | None) -> str | None:
    """The link's task or person while it's still there to open: a discarded task's link counts as none (it stays in
    Settings' list until it's removed or linked again)."""
    if link is None:
        return None
    if link.person:
        return link.person if link.person in model.people else None
    t = model.tasks.get(link.task or "")
    return t.id if t is not None and not t.discarded else None


def target_name(model: Model, target: str) -> str:
    """A link's task's title or person's name, as Settings and the rows name it."""
    if is_person(target):
        p = model.people.get(target)
        return p.name if p else target
    t = model.tasks.get(target)
    return t.title if t else target


# ---- the suggestion ----
def occurrence(model: Model, t: Task) -> bool:
    """A regular meeting's occurrence (made by Meeting notes, "Business team meeting 8 Oct"): never suggested or offered first."""
    return any(model.task(p).meeting and model.task(p).recurrence for p in model.parents_of(t.id) if p in model.tasks)


def meeting_tasks(model: Model) -> list[Task]:
    """The open meeting tasks a link is offered to, without regular meetings' occurrences, in title order."""
    return sorted((t for t in model.open_meetings() if not occurrence(model, t)), key=lambda t: t.title.casefold())


def suggest(model: Model, subject: str, recurring: bool = False) -> str | None:
    """The meeting task whose title has the subject's words (decision 491): every word of its title is in the subject, small
    words aside, in any order and case. The one with exactly the same words comes first, then the one with the most, then
    a regular meeting for a recurring appointment (or a one-off for a single one). None when nothing matches, or two match
    as well as each other, as DocRepo doesn't guess."""
    want = words_of(subject_key(subject))
    if not want:
        return None
    scored: list[tuple[tuple[bool, int, bool], str]] = []
    for t in meeting_tasks(model):
        have = words_of(t.title)
        if have and have <= want:
            scored.append(((have == want, len(have), bool(t.recurrence) == recurring), t.id))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


# ---- the day's view (decisions 489 and 490) ----
@dataclass(frozen=True)
class Meeting:
    """A timed appointment as Today shows it: ``when`` is "past" (ended), "now" (under way), "next" (the next one to start, not
    a Free one) or "later"; its live link's task or person (``target``), or the suggested meeting task; and how many open
    items are on the agenda it's linked to."""

    appointment: Appointment
    when: str
    target: str | None = None
    suggestion: str | None = None
    agenda: int = 0
    minutes: int = 0  # until it starts, for the next one

    @property
    def linked(self) -> bool:
        return self.target is not None


@dataclass(frozen=True)
class DayMeetings:
    """Today's meetings: the all-day ones (one line), the past ones (folded as "2 earlier"), and the rest in order."""

    day: date
    all_day: tuple[Appointment, ...] = ()
    earlier: tuple[Meeting, ...] = ()
    rest: tuple[Meeting, ...] = ()

    @property
    def lead(self) -> Meeting | None:
        """The side panel's first line (decision 490): the meeting under way (the latest to start, not a Free one), else
        the next one; None when none is left today."""
        now = [x for x in self.rest if x.when == "now" and not x.appointment.free]
        if now:
            return now[-1]
        return next((x for x in self.rest if x.when == "next"), None)

    @property
    def count(self) -> int:
        return len(self.earlier) + len(self.rest)


def _ordered(appointments: Sequence[Appointment]) -> list[Appointment]:
    return sorted(appointments, key=lambda a: (a.start, a.end, a.title.casefold()))


def minutes_until(start: datetime, now: datetime) -> int:
    """Whole minutes until ``start``, rounded up, so 10:40:30 to 11:00 is 20."""
    return max(0, math.ceil((start - now).total_seconds() / 60))


def until_text(minutes: int) -> str:
    """"in 20 min", "in 1 h", "in 2 h 5 min"."""
    if minutes < 60:
        return f"in {max(1, minutes)} min"
    hours, rest = divmod(minutes, 60)
    return f"in {hours} h" + (f" {rest} min" if rest else "")


def time_text(a: Appointment, day: date) -> str:
    """"09:00–10:00"; "until 01:00" for one that started before today; "from 23:00" for one that ends after it."""
    if a.start.date() < day:
        return f"until {a.end:%H:%M}"
    if a.end.date() > day and a.end != datetime.combine(day + timedelta(days=1), time()):
        return f"from {a.start:%H:%M}"
    return f"{a.start:%H:%M}–{a.end:%H:%M}"


def mark_text(meeting: Meeting) -> str:
    """The mark after its subject: "now" while it's under way, "in 20 min" for the next one, else ""."""
    if meeting.appointment.free:
        return ""
    return "now" if meeting.when == "now" else until_text(meeting.minutes) if meeting.when == "next" else ""


def all_day_line(day: DayMeetings) -> str:
    """"All day: Spring outage · Plant tour"; a private one is "Private appointment"."""
    return "All day: " + " · ".join(a.title for a in day.all_day) if day.all_day else ""


def day_view(appointments: Sequence[Appointment], model: Model, known: dict[str, Link], now: datetime) -> DayMeetings:
    """Today's meetings as Today shows them (decisions 489 to 491), at ``now``."""
    day = now.date()
    all_day = tuple(a for a in _ordered(appointments) if a.all_day)
    earlier: list[Meeting] = []
    rest: list[Meeting] = []
    next_found = False
    for a in _ordered([a for a in appointments if not a.all_day]):
        link = known.get(a.key) if a.key else None
        target = live_target(model, link)
        suggestion = None if target or not a.key else suggest(model, a.subject, a.recurring)
        agenda = len(model.open_items_for(target)) if target else 0
        if a.end <= now:
            earlier.append(Meeting(a, "past", target, suggestion, agenda))
        elif a.start <= now:
            rest.append(Meeting(a, "now", target, suggestion, agenda))
        elif not next_found and not a.free:
            next_found = True
            rest.append(Meeting(a, "next", target, suggestion, agenda, minutes_until(a.start, now)))
        else:
            rest.append(Meeting(a, "later", target, suggestion, agenda))
    return DayMeetings(day, all_day, tuple(earlier), tuple(rest))


def agenda_words(model: Model, meeting: Meeting) -> str:
    """How many items are on the linked agenda (decision 490): "3 on its agenda", "nothing on its agenda"; a person's is
    named: "1 on Tom Becker's agenda"."""
    if not meeting.target:
        return ""
    whose = f"{target_name(model, meeting.target)}'s agenda" if is_person(meeting.target) else "its agenda"
    return f"{meeting.agenda} on {whose}" if meeting.agenda else f"nothing on {whose}"


def context_words(model: Model, meeting: Meeting) -> str:
    """A row's quiet words: its place; the task it's linked to when that's named otherwise; how many are on the agenda; or
    the suggested meeting task, with a question mark, for Link to confirm."""
    a = meeting.appointment
    if a.private:
        return ""
    parts = [a.location]
    if meeting.target and not is_person(meeting.target) and not same_words(model, meeting.target, a.subject):
        parts.append(target_name(model, meeting.target))
    parts.append(agenda_words(model, meeting))
    if meeting.suggestion:
        parts.append("Link to its meeting task?" if same_words(model, meeting.suggestion, a.subject)
                     else f"Link to {target_name(model, meeting.suggestion)}?")
    return " · ".join(p for p in parts if p)


def same_words(model: Model, target: str, subject: str) -> bool:
    """Whether a task's title has just the subject's words, so naming it again would only repeat the subject."""
    return words_of(target_name(model, target)) == words_of(subject_key(subject))


# ---- reading, at most every 5 minutes (decision 493) ----
#: What a failed read's kind says in the status line, once, and the quiet line under Meetings.
PROBLEM_WORDS = {
    "closed": "Outlook isn't open",
    "busy": "Outlook is busy (a dialog may be open in it)",
    "refused": "Outlook refused to give DocRepo the calendar",
    "failed": "Outlook couldn't give DocRepo the calendar",
}


def read_today(day: date) -> list[Appointment]:
    """Today's appointments from Outlook (``outlook.todays_appointments``, looked up when called, so the tests can stand in
    for it). Raises ``outlook.CalendarProblem``."""
    from docrepo import outlook

    return outlook.todays_appointments(day)


@dataclass
class TodayCalendar:
    """The day's appointments, read from Outlook when asked and the last try is 5 minutes old, or another day's, or on F5
    (``forget``). A read that fails keeps the list it had for the day (decision 493), and its problem is said once
    (``tell``). ``read`` reads a day's appointments; by default Outlook's."""

    read: Callable[[date], list[Appointment]] = read_today
    appointments: tuple[Appointment, ...] = ()
    day: date | None = None
    read_at: datetime | None = None  # when the list was read
    tried_at: datetime | None = None  # when it was last tried
    kind: str = ""  # the last try's problem: "closed", "busy", "refused", "failed", or "" when it worked
    detail: str = ""  # what Outlook said, for the troubleshooting report's words
    _told: str = field(default="", repr=False)

    def due(self, now: datetime) -> bool:
        return self.tried_at is None or self.day != now.date() or not (timedelta(0) <= now - self.tried_at < STALE_AFTER)

    def forget(self) -> None:
        """F5: the next ``get`` reads again."""
        self.tried_at = None

    def get(self, now: datetime, force: bool = False) -> TodayCalendar:
        """Read again when it's due (or ``force``), then return itself."""
        if not (force or self.due(now)):
            return self
        if self.day != now.date():
            self.appointments, self.read_at, self.day = (), None, now.date()
        self.tried_at = now
        try:
            found = self.read(now.date())
        except Exception as e:  # noqa: BLE001 - Outlook's own errors, and any surprise, keep the list and say why
            self.kind = getattr(e, "kind", "failed")
            self.detail = getattr(e, "detail", "") or type(e).__name__
            if self.kind == "failed" and not hasattr(e, "kind"):
                log.warning("today's meetings: the read failed: %s", type(e).__name__)
            return self
        self.appointments, self.read_at, self.kind, self.detail, self._told = tuple(found), now, "", "", ""
        return self

    def tell(self) -> str:
        """The last try's problem in words for the status line, the first time it's seen; "" otherwise, and for Outlook not
        being open, which the quiet line says (decision 493)."""
        if not self.kind or self.kind == "closed" or self._told == self.kind:
            return ""
        self._told = self.kind
        kept = f"so the list is the one read at {self.read_at:%H:%M}" if self.read_at else "so there are no meetings to show"
        more = " Settings → Troubleshooting report has the details." if self.kind != "busy" else ""
        return f"Today's meetings: {PROBLEM_WORDS[self.kind]}, {kept}.{more}"

    def quiet_line(self, shown: int) -> str:
        """The quiet line under Meetings: why there are none, or how old the list is when a read failed; "" when all's well
        and there's something to show. ``shown``: how many appointments the group lists."""
        if self.kind:
            why = PROBLEM_WORDS[self.kind]
            if self.read_at:
                return f"{why} now; this is the list read at {self.read_at:%H:%M}."
            return f"{why}, so there are no meetings here. They show once it's open." if self.kind == "closed" else f"{why}, so there are no meetings here."
        return "" if shown else "No meetings on your calendar today."
