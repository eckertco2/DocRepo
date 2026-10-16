"""Dates and times as DocRepo stores and shows them.

The database keeps dates as ``YYYY-MM-DD`` and times as ``YYYY-MM-DD HH:MM:SS``.
Pages show short forms such as ``13 Oct`` and ``Tue 13 Oct``.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
#: Weekday names in Python's order (Monday is 0), as settings.json spells them.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def to_date(value: str | date) -> date:
    """A date from ``YYYY-MM-DD`` (or the date part of a stored time)."""
    return value if isinstance(value, date) else date.fromisoformat(value[:10])


def check_date(value: str) -> str:
    """Return ``value`` if it's a valid ``YYYY-MM-DD`` date, else raise ValueError."""
    if len(value) != 10:
        raise ValueError(f"{value!r} isn't a date in the form YYYY-MM-DD.")
    date.fromisoformat(value)
    return value


def stamp(moment: datetime) -> str:
    """A stored time: ``YYYY-MM-DD HH:MM:SS``."""
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def minutes(stored: str) -> str:
    """A stored time as pages show it: ``YYYY-MM-DD HH:MM``."""
    return stored[:16]


def add_months(day: date, n: int) -> date:
    """The same day ``n`` months later, or the month's last day if that month is shorter."""
    m0 = day.month - 1 + n
    year, month = day.year + m0 // 12, m0 % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def day_diff(a: date, b: date) -> int:
    """Days from ``a`` to ``b``."""
    return (b - a).days


def short(day: date, today: date) -> str:
    """``13 Oct``, with the year added when it isn't today's year."""
    text = f"{day.day} {MONTHS[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def long_date(day: date, today: date) -> str:
    """``Tue 13 Oct``."""
    return f"{WEEKDAYS[day.weekday()]} {short(day, today)}"


def days_text(day: date, today: date) -> str:
    """How far off a date is: ``in 22 d``, ``tomorrow``, ``today`` or ``3 d overdue``."""
    n = day_diff(today, day)
    if n < 0:
        return f"{-n} d overdue"
    return {0: "today", 1: "tomorrow"}.get(n, f"in {n} d")


def workday_numbers(names: list[str]) -> frozenset[int]:
    """Weekday numbers (Monday is 0) for names such as ``["Mon", "Tue"]``."""
    unknown = [n for n in names if n not in WEEKDAYS]
    if unknown:
        raise ValueError(f"Unknown workday names: {', '.join(unknown)}. Use {', '.join(WEEKDAYS)}.")
    return frozenset(WEEKDAYS.index(n) for n in names)
