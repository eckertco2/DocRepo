"""Later, on Today (release 5.116, decision 417; the design workspace's ``docs/mods/today-reminders-plan.md``): the day an item
comes back, from the menu's choices or the words typed in Other…. Later sets the task's Reminder to that day, and a reminder
puts its task on Today on its day (decision 415). No Qt, so the tests feed it directly.

"Tomorrow" and "3 days" count workdays, the ones set in Settings; "1 week", "2 weeks" and "1 month" keep the weekday or the
day of the month, moved to the next workday when that isn't one.
"""
from __future__ import annotations

import calendar
import re
from collections.abc import Collection
from datetime import date, timedelta

from docrepo.parse import find_dates

#: The menu's choices, as (key, label).
CHOICES: tuple[tuple[str, str], ...] = (("1d", "Tomorrow"), ("3d", "3 days"), ("1w", "1 week"), ("2w", "2 weeks"), ("1m", "1 month"))
EVERY_DAY = frozenset(range(7))
#: Other…'s box: a whole number of workdays.
NUMBER = re.compile(r"\d{1,3}")


def _days(workdays: Collection[int]) -> frozenset[int]:
    return frozenset(workdays) or EVERY_DAY


def on_a_workday(day: date, workdays: Collection[int]) -> date:
    """``day``, or the next workday after it."""
    days = _days(workdays)
    while day.weekday() not in days:
        day += timedelta(days=1)
    return day


def workdays_after(today: date, n: int, workdays: Collection[int]) -> date:
    """The ``n``th workday after ``today``."""
    days, day = _days(workdays), today
    while n > 0:
        day += timedelta(days=1)
        if day.weekday() in days:
            n -= 1
    return day


def month_after(today: date) -> date:
    """The same day next month, or that month's last day when it's shorter."""
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def later_day(choice: str, today: date, workdays: Collection[int]) -> date:
    """The day one of the menu's choices brings an item back."""
    if choice == "1d":
        return workdays_after(today, 1, workdays)
    if choice == "3d":
        return workdays_after(today, 3, workdays)
    if choice in ("1w", "2w"):
        return on_a_workday(today + timedelta(days=7 if choice == "1w" else 14), workdays)
    if choice == "1m":
        return on_a_workday(month_after(today), workdays)
    raise ValueError(f"Unknown choice {choice!r}.")


def read_later(text: str, today: date, workdays: Collection[int]) -> date | None:
    """Other…'s box: a whole number is that many workdays on ("3" is the same as 3 days); anything else is the first date in
    the words, read as Parse and populate reads dates ("Fri", "15 Dec", "in 3 weeks"), moved to a workday. None when it's
    neither, or not after today."""
    words = text.strip()
    if NUMBER.fullmatch(words):
        n = int(words)
        return workdays_after(today, n, workdays) if n > 0 else None
    hits = find_dates(words, today)
    if not hits or hits[0].date <= today:
        return None
    return on_a_workday(hits[0].date, workdays)
