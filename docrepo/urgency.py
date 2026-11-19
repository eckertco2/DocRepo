"""Urgent on Today, worked out (release 5.176, the design workspace's ``docs/mods/urgency-plan.md``, decisions 819 to 823).
No Qt, and nothing read from docs.db: the Model and a day are enough.

A task on Today is **urgent** when any of these holds (decision 819):

- it has the Urgent tick (the owner's override);
- its date (``schedule.due_of``: its Due, else its Deadline, else a routine task's next occurrence) is before today;
- its date is on or before the second workday from today (``later.workdays_after(today, 2, workdays)``).

A note is never urgent. Importance is a judgement that holds, and is the band; urgency is about time, so the dates do most
of it. Inside each of Today's priority bands the urgent tasks come first, each half in the owner's order (decision 820).
Only Today's bands use it: the Priorities board, the lists, Due in the next 7 days and the quick summary keep their own
rules for the tick (decision 823).
"""
from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date

from docrepo.dates import long_date
from docrepo.later import workdays_after
from docrepo.model import AgendaItem, Model, Task
from docrepo.schedule import due_of

#: Monday to Friday, when no workdays are given.
WEEKDAYS = frozenset(range(5))
#: How many workdays on a date still counts as urgent (decision 819): today, the next workday and the one after.
WORKDAYS_AHEAD = 2


def horizon(today: date, workdays: Collection[int] | None = None) -> date:
    """The last day a date makes a task urgent: the second workday from today."""
    return workdays_after(today, WORKDAYS_AHEAD, workdays or WEEKDAYS)


def by_date(task: Task, today: date, workdays: Collection[int] | None = None) -> bool:
    """Whether a task's date alone makes it urgent: before today, or on or before the second workday on."""
    d = due_of(task, today)
    return d is not None and d.date <= horizon(today, workdays)


def is_urgent(m: Model, task: Task | str | None, today: date, workdays: Collection[int] | None = None) -> bool:
    """Whether a task on Today is urgent: the tick, or its date (decision 819). None (a note's) never is."""
    t = m.tasks.get(task) if isinstance(task, str) else task
    if t is None:
        return False
    return bool(t.urgent) or by_date(t, today, workdays)


def why(m: Model, task: Task | str | None, today: date, workdays: Collection[int] | None = None) -> str:
    """Why a task is urgent, in words ("ticked Urgent", "overdue since Mon 16 Nov", "due Thu 19 Nov"), or "" when it isn't.
    The tick comes first: it's the owner's own word."""
    t = m.tasks.get(task) if isinstance(task, str) else task
    if t is None:
        return ""
    if t.urgent:
        return "ticked Urgent"
    d = due_of(t, today)
    if d is None or d.date > horizon(today, workdays):
        return ""
    if d.date < today:
        return f"overdue since {long_date(d.date, today)}"
    return f"due {long_date(d.date, today)}"


def urgent_ids(m: Model, items: Iterable[AgendaItem], today: date, workdays: Collection[int] | None = None) -> set[int]:
    """The IDs of Today's items whose task is urgent, walking them once."""
    last = horizon(today, workdays)
    out: set[int] = set()
    for a in items:
        t = m.tasks.get(a.subject) if a.subject else None
        if t is None:
            continue
        if t.urgent:
            out.add(a.id)
            continue
        d = due_of(t, today)
        if d is not None and d.date <= last:
            out.add(a.id)
    return out
