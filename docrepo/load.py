"""What Capacity's half of the Timeline page says (release 5.40; round 5's items 71 and 72, the visual review's stage V5).

Nothing here works hours out: it reads ``capacity.week_cells``, the hours in ``work_calendar``, as person, week and task. A
person's row is a heat strip on the timeline's own dates (decision 230): each week a cell, or each month once a week would
be too narrow to see, when a cell shows its worst week so a peak isn't averaged away. Over them, one sentence says who is
over and when, counting this week onwards, since a past week can't be changed (decisions 231 and 289), and the team chart
counts the hours over each person's own capacity, so spare time elsewhere can't hide one person's overload.

Nothing here draws anything: ``docrepo/ui/capacity_strip.py`` paints it. The mock is ``plancap.js``.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from docrepo.dates import monday_of, short
from docrepo.model import Person

#: A week narrower than this on screen becomes a month (decision 230).
WEEK_MIN_PX = 8.0
#: A cell's steps, as a share of the person's hours a week: grey in two steps, caution from 80%, red over 100%, and a strong
#: red from 125% (decisions 18, 230 and 288).
LOW, NEAR, FULL, FAR = 0.4, 0.8, 1.0, 1.25

Cells = dict[str, dict[date, dict[str, float]]]


@dataclass(frozen=True)
class Bucket:
    """One cell across a person's row: a week, or a month of them. ``end`` is the day after it."""

    first: date
    end: date
    weeks: tuple[date, ...]
    month: bool = False

    def holds(self, day: date) -> bool:
        return self.first <= day < self.end


@dataclass(frozen=True)
class TeamWeek:
    """Everyone's hours in a week, and those over each person's own capacity."""

    total: float = 0.0
    over: float = 0.0


@dataclass
class Case:
    """What the sentence says, counting from this week."""

    over_weeks: list[date] = field(default_factory=list)
    worst: date | None = None
    most: float = 0.0
    by_person: dict[str, int] = field(default_factory=dict)
    busiest: tuple[str, date, float] | None = None  # who, which week and what share, when nobody is over


def mondays(start: date, end: date) -> list[date]:
    """The Mondays of the weeks from ``start`` up to the day before ``end``."""
    out, week = [], monday_of(start)
    while week < end:
        out.append(week)
        week += timedelta(days=7)
    return out


def buckets(start: date, end: date, week_px: float) -> list[Bucket]:
    """The cells across a row: a week each, or a month each when a week is under ``WEEK_MIN_PX`` wide. A week belongs to the
    month its Monday is in."""
    weeks = mondays(start, end)
    if week_px >= WEEK_MIN_PX:
        return [Bucket(w, w + timedelta(days=7), (w,)) for w in weeks]
    out: list[Bucket] = []
    for w in weeks:
        if out and (out[-1].first.year, out[-1].first.month) == (w.year, w.month):
            out[-1] = Bucket(out[-1].first, w + timedelta(days=7), (*out[-1].weeks, w), True)
        else:
            out.append(Bucket(w, w + timedelta(days=7), (w,), True))
    return out


def week_hours(cells: Cells, person: str, week: date) -> float:
    return sum(cells.get(person, {}).get(week, {}).values())


def worst_week(cells: Cells, person: str, bucket: Bucket) -> tuple[float, date]:
    """The bucket's fullest week for a person: its hours, and which."""
    return max(((week_hours(cells, person, w), w) for w in bucket.weeks), key=lambda x: x[0], default=(0.0, bucket.first))


def tint(hours: float, hours_a_week: float | None) -> str:
    """A cell's step: "" with nothing scheduled, "none" when their hours a week aren't set, or "t1" to "t5"."""
    if not hours:
        return ""
    if not hours_a_week:
        return "none"
    use = hours / hours_a_week
    return "t5" if use >= FAR else "t4" if use > FULL else "t3" if use >= NEAR else "t2" if use >= LOW else "t1"


def cell_text(hours: float, hours_a_week: float | None, unit: str) -> str:
    """One number (the review's decision V5): a percent, or whole hours. With no hours a week to count against, it's hours."""
    if not hours:
        return ""
    if unit == "pct" and hours_a_week:
        return f"{round(hours / hours_a_week * 100)}%"
    return str(round(hours))


def _h(x: float) -> str:
    return f"{round(x, 1):g}"


def cell_tip(person: Person, cells: Cells, bucket: Bucket, today: date) -> str:
    """A cell's tooltip: the other number, and for a month, which week it's showing."""
    hours, week = worst_week(cells, person.id, bucket)
    if not hours:
        return f"{person.name}, {when(bucket, today)}: nothing scheduled"
    share = f", {round(hours / person.hours * 100)}%" if person.hours else ""
    if bucket.month:
        total = sum(week_hours(cells, person.id, w) for w in bucket.weeks)
        return f"{person.name}, {when(bucket, today)}: {_h(total)} h. Worst week {short(week, today)}: {_h(hours)} h{share}"
    capacity = f" of {person.hours:g} h" if person.hours else " (hours a week not set)"
    return f"{person.name}, {when(bucket, today)}: {_h(hours)} h{capacity}{share}"


def when(bucket: Bucket, today: date) -> str:
    return bucket.first.strftime("%B %Y") if bucket.month else f"week of {short(bucket.first, today)}"


def team_week(cells: Cells, people: Iterable[Person], week: date) -> TeamWeek:
    total = over = 0.0
    for p in people:
        hours = week_hours(cells, p.id, week)
        total += hours
        if p.hours and hours > p.hours:
            over += hours - p.hours
    return TeamWeek(total, over)


def team_bucket(cells: Cells, people: list[Person], bucket: Bucket) -> tuple[TeamWeek, date]:
    """The week the team chart shows for a bucket: the one with the most hours over, then the most hours."""
    return max(((team_week(cells, people, w), w) for w in bucket.weeks), key=lambda x: (x[0].over, x[0].total),
               default=(TeamWeek(), bucket.first))


def capacity_of(people: Iterable[Person]) -> float:
    return sum(p.hours or 0 for p in people)


def case(cells: Cells, people: list[Person], weeks: list[date], today: date) -> Case:
    """Who is over and when, from this week on."""
    out = Case()
    this_week = monday_of(today)
    top = 0.0
    for week in weeks:
        if week < this_week:
            continue
        team = team_week(cells, people, week)
        if team.over > 0:
            out.over_weeks.append(week)
            if team.over > out.most:
                out.most, out.worst = team.over, week
        for p in people:
            hours = week_hours(cells, p.id, week)
            if not p.hours:
                continue
            if hours > p.hours:
                out.by_person[p.id] = out.by_person.get(p.id, 0) + 1
            if hours / p.hours > top:
                top = hours / p.hours
                out.busiest = (p.id, week, top)
    return out


def sentence(c: Case, name: Callable[[str], str], today: date) -> tuple[str, str]:
    """The case in words: what goes in bold, then who. For example "Over in 9 weeks, the worst the week of 29 Mar, by 62 h."
    and "Tom Becker 7 weeks, Mike Ortiz 5.\""""
    n = len(c.over_weeks)
    if not n:
        if c.busiest is None:
            return "Nobody is over in this range.", ""
        who, week, use = c.busiest
        return "Nobody is over in this range.", f"Busiest: {name(who)}, {round(use * 100)}% in the week of {short(week, today)}."
    first, last = c.over_weeks[0], c.over_weeks[-1]
    hours = f"{round(c.most)} h"
    if n == 1:
        lead = f"Over in the week of {short(first, today)}, by {hours}."
    elif (last - first).days == (n - 1) * 7:
        lead = f"Over in {n} weeks, {short(first, today)} to {short(last + timedelta(days=6), today)}, by up to {hours}."
    else:
        assert c.worst is not None
        lead = f"Over in {n} weeks, the worst the week of {short(c.worst, today)}, by {hours}."
    ranked = sorted(c.by_person.items(), key=lambda x: -x[1])
    words = [f"{name(p)} {count if i else f'{count} week' + ('s' if count != 1 else '')}" for i, (p, count) in enumerate(ranked[:3])]
    more = f" and {len(ranked) - 3} more" if len(ranked) > 3 else ""
    return lead, ", ".join(words) + more + "."


def cell_tasks(cells: Cells, people: Iterable[str], weeks: Iterable[date]) -> list[tuple[str, float]]:
    """The tasks behind some people's weeks, biggest first (the spotlight's card, decision 233)."""
    weeks = list(weeks)
    hours: dict[str, float] = {}
    for p in people:
        for w in weeks:
            for task, h in cells.get(p, {}).get(w, {}).items():
                hours[task] = hours.get(task, 0.0) + h
    return sorted(hours.items(), key=lambda x: -x[1])


def adds_to(cells: Cells, tasks: set[str]) -> set[tuple[str, date]]:
    """The people's weeks these tasks add to, which selecting a bar outlines (decision 233)."""
    return {(p, w) for p, weeks in cells.items() for w, by_task in weeks.items() if tasks & by_task.keys()}
