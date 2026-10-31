"""When a task happens: its working windows, its next occurrence and its days until due.

A one-time task has one window, from Start to Due (or to Deadline if there's no
Due). A routine task's first window runs from Start to Due, or is just the Start
day, and repeats every interval until Repeat until, the end of the horizon, or
the day it was closed.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from docrepo.dates import add_months, to_date

#: Each recurrence's step: (days, months).
STEPS = {"Daily": (1, 0), "Weekly": (7, 0), "Bi-weekly": (14, 0), "Monthly": (0, 1), "Quarterly": (0, 3), "Yearly": (0, 12)}

#: How far ahead a routine task's next occurrence is looked for.
NEXT_LOOKAHEAD_DAYS = 400


class Dated(Protocol):
    """The task fields scheduling needs."""

    state: str
    closed: str | None
    recurrence: str | None
    repeat_until: str | None
    start: str | None
    due: str | None
    deadline: str | None
    created: str


@dataclass(frozen=True)
class DueDate:
    """The date that drives days until due, and what it is: Due, Deadline or Next (a routine task's next occurrence)."""

    date: date
    label: str


def is_open(task: Dated) -> bool:
    """Not started or In progress, and not discarded (mods log round 1, M0021)."""
    return task.state in ("Not started", "In progress") and not getattr(task, "discarded", None)


def start_of(task: Dated) -> date:
    """The task's Start, or the day it was created if Start isn't set. A plant event without a Start of its own is one
    day, its Due (or Deadline): an outage typed with only its date isn't a range from the day it was noted (release 5.30)."""
    if not task.start and getattr(task, "plant_event", False) and (task.due or task.deadline):
        return to_date(task.due or task.deadline)
    return to_date(task.start or task.created)


def _counts(day: date, workdays: Collection[int], every_day: bool) -> bool:
    return every_day or not workdays or day.weekday() in workdays


def days_in(first: date, last: date, workdays: Collection[int], every_day: bool = False) -> int:
    """How many days a task from ``first`` to ``last`` has: its workdays, or every day with Runs through weekends (decision
    190). One that holds no workday counts its calendar days, as the capacity calendar spreads its hours over them."""
    span = (last - first).days + 1
    if span <= 0:
        return 0
    return sum(_counts(first + timedelta(days=i), workdays, every_day) for i in range(span)) or span


def due_after(start: date, days: int, workdays: Collection[int], every_day: bool = False) -> date:
    """The last of ``days`` days from ``start``. A Start that isn't a workday stays as typed, and counting starts on the first
    workday after it (the design's Dates)."""
    day, counted = start, 1 if _counts(start, workdays, every_day) else 0
    while counted < days:
        day += timedelta(days=1)
        counted += _counts(day, workdays, every_day)
    return day


def start_before(due: date, days: int, workdays: Collection[int], every_day: bool = False) -> date:
    """The first of ``days`` days up to ``due``."""
    day, counted = due, 1 if _counts(due, workdays, every_day) else 0
    while counted < days:
        day -= timedelta(days=1)
        counted += _counts(day, workdays, every_day)
    return day


def placed(start: str | None, due: str | None, days: int | None, edited: str, workdays: Collection[int], every_day: bool = False) -> tuple[str | None, str | None]:
    """A block's dates once one thing about it was edited, ``edited`` being "start", "due" or "duration" (decision 191). With a
    Duration, changing Start moves Due, changing Due moves Start, and changing the Duration moves Due, or Start if there's no
    Start. Clearing either date clears both: it's off the calendar, keeping its size. With none, the dates are plain dates."""
    if days is None:
        return start, due
    if edited == "start":
        return (start, due_after(to_date(start), days, workdays, every_day).isoformat()) if start else (None, None)
    if edited == "due":
        return (start_before(to_date(due), days, workdays, every_day).isoformat(), due) if due else (None, None)
    if start:
        return start, due_after(to_date(start), days, workdays, every_day).isoformat()
    return (start_before(to_date(due), days, workdays, every_day).isoformat(), due) if due else (None, None)


def length_of(start: str | None, due: str | None, days: int | None, workdays: Collection[int], every_day: bool = False) -> int | None:
    """A task's length in days: its Duration, or what its two dates hold, or None when it hasn't one."""
    if days is not None:
        return days
    if start and due and to_date(due) >= to_date(start):
        return days_in(to_date(start), to_date(due), workdays, every_day)
    return None


def windows(task: Dated, until: date) -> list[tuple[date, date]]:
    """The task's working windows, first day and last day. A routine task's stop at ``until``. A task with a Duration and no
    Start or Due isn't placed, even with a Deadline, rather than spreading its hours from the day it was made (the design's
    Dates)."""
    start = start_of(task)
    if not task.recurrence:
        if getattr(task, "duration", None) and not task.start and not task.due:
            return []
        end = task.due or task.deadline
        return [(start, to_date(end))] if end else []
    length = (to_date(task.due) - start).days if task.due else 0
    days, months = STEPS[task.recurrence]
    repeat_until = to_date(task.repeat_until) if task.repeat_until else None
    closed = to_date(task.closed) if task.closed else None
    out: list[tuple[date, date]] = []
    i = 0
    while True:
        first = add_months(start, months * i) if months else start + timedelta(days=days * i)
        if first > until or (repeat_until and first > repeat_until) or (closed and first > closed):
            return out
        out.append((first, first + timedelta(days=length)))
        i += 1


def due_of(task: Dated, today: date) -> DueDate | None:
    """Due, else Deadline. A routine task counts to the end of its next occurrence. Closed and discarded tasks have none."""
    if task.state == "Closed" or getattr(task, "discarded", None):
        return None
    if task.recurrence:
        for _first, last in windows(task, today + timedelta(days=NEXT_LOOKAHEAD_DAYS)):
            if last >= today:
                return DueDate(last, "Next")
        return None
    if task.due:
        return DueDate(to_date(task.due), "Due")
    if task.deadline:
        return DueDate(to_date(task.deadline), "Deadline")
    return None
