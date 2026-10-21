"""When a task happens: its working windows, its next occurrence and its days until due.

A one-time task has one window, from Start to Due (or to Deadline if there's no
Due). A routine task's first window runs from Start to Due, or is just the Start
day, and repeats every interval until Repeat until, the end of the horizon, or
the day it was closed.
"""
from __future__ import annotations

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
    """The task's Start, or the day it was created if Start isn't set."""
    return to_date(task.start or task.created)


def windows(task: Dated, until: date) -> list[tuple[date, date]]:
    """The task's working windows, first day and last day. A routine task's stop at ``until``."""
    start = start_of(task)
    if not task.recurrence:
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
