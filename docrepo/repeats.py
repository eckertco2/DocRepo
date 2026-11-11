"""A reminder that repeats (release 5.117, decision 416; the design workspace's ``docs/mods/today-reminders-plan.md``).

A task's Reminder can repeat: every week on chosen weekdays, every month on a day, every month on a workday, or every
n days. Each time it comes round, the reminder puts the task on Today (decision 415), and the next time is worked out.
It's kept as the task's ``reminder_repeat``, a short rule, and ``reminder_until``, the last day it may come round:

- ``week:mon,thu``: every week on those weekdays;
- ``month:15``, ``month:last``: every month on that day, or the month's last day when it's shorter;
- ``workday:3``, ``workday:last``: every month on its 3rd workday, or its last, counted on the workdays in Settings;
- ``days:5``: every 5 days, counted from the last time.

It's not a task's Recurrence, which makes a routine task for Capacity's hours. No Qt, so the tests feed it directly.
"""
from __future__ import annotations

import calendar
import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

from docrepo.dates import WEEKDAYS

KINDS = ("week", "month", "workday", "days")
LAST = -1
#: How far ahead a rule is looked for, in days: past it, a rule that can't come round (a weekday that isn't one) gives up.
LOOK_AHEAD = 800
_RULE = re.compile(r"(week|month|workday|days):([a-z0-9,]+)")


class RepeatError(ValueError):
    """A rule that isn't one of the four."""


@dataclass(frozen=True)
class Repeat:
    kind: str
    weekdays: tuple[int, ...] = ()  # "week": Monday is 0
    n: int = 0  # "month" and "workday": the day or the workday, LAST for the last; "days": every how many


def parse(text: str) -> Repeat:
    """A rule, checked: ``week:mon,thu``, ``month:15``, ``month:last``, ``workday:3``, ``workday:last`` or ``days:5``."""
    m = _RULE.fullmatch((text or "").strip().lower())
    if not m:
        raise RepeatError(f"{text!r} isn't a repeat: use week:mon,thu, month:15, workday:3 or days:5.")
    kind, value = m.groups()
    if kind == "week":
        names = [WEEKDAYS[i].lower() for i in range(7)]
        days = value.split(",")
        if not days or any(d not in names for d in days):
            raise RepeatError(f"{value!r} isn't a list of weekdays, such as mon,thu.")
        return Repeat("week", tuple(sorted({names.index(d) for d in days})))
    if value == "last" and kind in ("month", "workday"):
        return Repeat(kind, n=LAST)
    if not value.isdigit():
        raise RepeatError(f"{value!r} isn't a number.")
    n = int(value)
    if kind == "month" and not 1 <= n <= 31:
        raise RepeatError("A day of the month is 1 to 31, or last.")
    if kind == "workday" and not 1 <= n <= 23:
        raise RepeatError("A workday of the month is 1 to 23, or last.")
    if kind == "days" and not 1 <= n <= 366:
        raise RepeatError("Every n days takes 1 to 366.")
    return Repeat(kind, n=n)


def text_of(r: Repeat) -> str:
    """A rule as it's kept."""
    if r.kind == "week":
        return "week:" + ",".join(WEEKDAYS[d].lower() for d in r.weekdays)
    return f"{r.kind}:{'last' if r.n == LAST else r.n}"


def normal(text: str | None) -> str | None:
    """A rule in its kept form, or None for none."""
    return text_of(parse(text)) if text and text.strip() else None


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def describe(text: str | None) -> str:
    """A rule in words: "Every week on Mon and Thu", "Every month on the 15th", "Every month on its 3rd workday"…"""
    if not text:
        return ""
    r = parse(text)
    if r.kind == "week":
        names = [WEEKDAYS[d] for d in r.weekdays]
        return "Every week on " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0])
    if r.kind == "month":
        return "Every month on its last day" if r.n == LAST else f"Every month on the {_ordinal(r.n)}"
    if r.kind == "workday":
        return "Every month on its last workday" if r.n == LAST else f"Every month on its {_ordinal(r.n)} workday"
    return "Every day" if r.n == 1 else f"Every {r.n} days"


def _workdays(workdays: Collection[int]) -> frozenset[int]:
    return frozenset(workdays) or frozenset(range(7))


def _month_workdays(year: int, month: int, workdays: Collection[int]) -> list[date]:
    days = _workdays(workdays)
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1) if date(year, month, d).weekday() in days]


def comes_on(r: Repeat, day: date, workdays: Collection[int]) -> bool:
    """Whether a week, month or workday rule comes round on ``day``."""
    if r.kind == "week":
        return day.weekday() in r.weekdays
    if r.kind == "month":
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == (last if r.n == LAST else min(r.n, last))
    if r.kind == "workday":
        listed = _month_workdays(day.year, day.month, workdays)
        if not listed:
            return False
        return day == (listed[-1] if r.n == LAST else listed[min(r.n, len(listed)) - 1])
    raise RepeatError("Every n days counts from the last time, not by the calendar.")


def next_after(text: str, after: date, workdays: Collection[int], last: date | None = None) -> date | None:
    """The first time the rule comes round after ``after``. Every n days counts on from ``last``, the time that just came
    round, or from ``after`` when there's none. None when it can't come round (no weekdays)."""
    r = parse(text)
    if r.kind == "days":
        day = last or after
        while day <= after:
            day += timedelta(days=r.n)
        return day
    day = after
    for _ in range(LOOK_AHEAD):
        day += timedelta(days=1)
        if comes_on(r, day, workdays):
            return day
    return None


def first_from(text: str, day: date, workdays: Collection[int]) -> date | None:
    """The first time the rule comes round on ``day`` or after it: where a new repeat starts."""
    if parse(text).kind == "days":
        return day
    return next_after(text, day - timedelta(days=1), workdays)


def following(text: str, until: str | None, came: date, today: date, workdays: Collection[int]) -> str | None:
    """The reminder after the one that came on ``came``, seen ``today``: the first time after today, as an ISO date, or
    None when that's past ``until``."""
    nxt = next_after(text, today, workdays, last=came)
    if nxt is None or (until and nxt.isoformat() > until):
        return None
    return nxt.isoformat()
