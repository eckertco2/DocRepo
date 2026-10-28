"""Key dates (release 5.31; the key dates plan in the design workspace, decisions 146 to 155): dated line items on a task.

A task keeps its own Start, Due and Deadline, which drive the lists, Today, reminders, Capacity and the timeline's bar
(decision 146). Beside them it has any number of key dates, each a start, an end or both, an optional description, and
three ticks: a plant activity, which makes it a plant event of its own (decision 149); a hard deadline, a red diamond at
its end (147); and done, the day it was ticked (148). What's filled says what kind it is: a start alone is a beginning
("from"), an end alone a target ("by"), both a window, and the same day at both ends a milestone ("on").

An open key date with an end is due on it, on Today and the Overdue and next 7 days list, and overdue once it's passed;
one with only a start shows on the days before it starts and on the day, and is never overdue. Each is a row of its own
there (decision 150). Key dates carry no hours, so Capacity doesn't change (151). Done ones stay on the task page and the
timeline, grey (153). Nothing here writes: ``edits`` saves and logs them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from docrepo.dates import long_date, to_date
from docrepo.model import KeyDate, Model, Task
from docrepo.schedule import is_open

#: How far ahead a key date shows on Today and the list, as the task's Due does.
SOON_DAYS = 7


def first_last(kd: KeyDate) -> tuple[date, date]:
    """Its first and last day: a start or an end alone is one day."""
    a = to_date(kd.start or kd.end)
    b = to_date(kd.end or kd.start)
    return a, b


def kind(kd: KeyDate) -> str:
    """"window", "on" (a milestone: one day, both ends), "from" (a start alone) or "by" (an end alone)."""
    if kd.start and kd.end:
        return "on" if kd.start == kd.end else "window"
    return "from" if kd.start else "by"


def when_text(kd: KeyDate, today: date | None = None) -> str:
    """Its dates in words: "Tue 1 Dec to Sat 5 Dec", "on Tue 1 Dec", "from Thu 1 Oct" or "by Wed 25 Nov". Without
    ``today`` every date has its year, as the status log keeps them."""
    k, (a, b) = kind(kd), first_last(kd)
    today = today or date.min
    if k == "window":
        return f"{long_date(a, today)} to {long_date(b, today)}"
    return f"{k} {long_date(a if k != 'by' else b, today)}"


def label(kd: KeyDate, today: date | None = None) -> str:
    """Its description and dates: "Trial execution window, Tue 1 Dec to Sat 5 Dec"; "Key date" when it has no description."""
    return f"{kd.description or 'Key date'}, {when_text(kd, today)}"


def log_text(kd: KeyDate) -> str:
    """As the status log keeps it, with full dates: "Trial execution window, Tue 1 Dec 2026 to Sat 5 Dec 2026, plant
    activity, deadline"."""
    marks = [x for x, on in (("plant activity", kd.plant), ("deadline", kd.deadline)) if on]
    return ", ".join([label(kd), *marks])


def problem(start: str | None, end: str | None) -> str | None:
    """What makes a key date's dates unusable, or None: neither given, one not a date, or the end before the start."""
    if not start and not end:
        return "A key date needs a start, an end or both."
    try:
        a = date.fromisoformat(start) if start else None
        b = date.fromisoformat(end) if end else None
    except ValueError:
        return "A key date's dates must be YYYY-MM-DD."
    if a and b and b < a:
        return "A key date's end is before its start."
    return None


@dataclass(frozen=True)
class Due:
    """An open key date on Today or the Overdue and next 7 days list: when it's due (its end, or its start when it has
    only one), whether it's a start, and whether it's overdue."""

    task: Task
    key_date: KeyDate
    day: date
    starts: bool
    overdue: bool

    def text(self, today: date) -> str:
        """Its line: "Trial execution window, by Fri 5 Dec", "Starts today: Trial planning period"."""
        what = self.key_date.description or "Key date"
        if self.starts:
            return f"Starts today: {what}" if self.day == today else f"{what}, from {long_date(self.day, today)}"
        return f"{what}, {'was due' if self.overdue else 'by'} {long_date(self.day, today)}"


def due(m: Model, today: date, days: int = SOON_DAYS, task_ids: set[str] | None = None) -> list[Due]:
    """The open key dates of open tasks that are overdue or due in the next ``days`` days (an end), or start in them,
    soonest first. ``task_ids`` keeps only those tasks'."""
    out: list[Due] = []
    for task_id, kds in m.key_dates.items():
        t = m.tasks.get(task_id)
        if t is None or not is_open(t) or (task_ids is not None and task_id not in task_ids):
            continue
        for kd in kds:
            if kd.done:
                continue
            if kd.end:
                day = to_date(kd.end)
                if (day - today).days <= days:
                    out.append(Due(t, kd, day, False, day < today))
            else:
                day = to_date(kd.start)
                if 0 <= (day - today).days <= days:
                    out.append(Due(t, kd, day, True, False))
    return sorted(out, key=lambda d: (d.day, d.task.title.lower(), d.key_date.pos))


def span(m: Model, task_id: str) -> tuple[date, date] | None:
    """The first and last day of a task's key dates, for its row and its parents' summary bars."""
    days = [d for kd in m.key_dates_of(task_id) for d in first_last(kd)]
    return (min(days), max(days)) if days else None
