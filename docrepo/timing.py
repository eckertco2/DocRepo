"""A template's timing (release 5.51; the task templates design, decisions 248 and 255 to 258): the ties on its rows, and the sums
the Timing window, its chart and Make tasks do with them.

A row's tie reads as a task's does, a number of workdays or weeks before or after another date, but its source is another row, or
the template's anchor. A template has no dates, so its chart counts in workdays around the anchor's start, with a week as however
many workdays Settings has. Nothing here reads docs.db or touches Qt, so all of it is tested as sums.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from docrepo import ties
from docrepo.dates import to_date
from docrepo.schedule import due_after, start_before

FIELDS = ties.FIELDS


@dataclass(frozen=True)
class RowTie:
    """A template row's Start or Due, set from another row's start or end. ``source`` None is the anchor."""

    source: int | None = None
    point: str = "start"
    amount: int = 0
    unit: str = "workdays"
    direction: str = "before"


@dataclass
class Line:
    """A row as the chart and the Timing window see it. ``spans`` is a row with subtasks and no dates of its own, which gives nothing
    to tie to and can't be the anchor (decision 250), and ``routine`` one that repeats, which has no one date to give."""

    id: int
    title: str
    depth: int = 0
    parent: int | None = None
    spans: bool = False
    days: int | None = None
    ties: dict[str, RowTie] = field(default_factory=dict)
    routine: bool = False

    @property
    def placeable(self) -> bool:
        return not self.spans and not self.routine


# ---- in words ----
def source_name(tie: RowTie, titles: Mapping[int, str]) -> str:
    return "the anchor" if tie.source is None else titles.get(tie.source, "another row")


def words(tie: RowTie, titles: Mapping[int, str]) -> str:
    """A row's tie as a sentence: "30 workdays before the anchor starts", or "1 workday after Trial report ends"."""
    return ties.words(tie, source_name(tie, titles))


def brief(tie: RowTie, titles: Mapping[int, str]) -> str:
    """A row's tie where room is short: "30 workdays before start" counts from the anchor, as most do. Others name their row."""
    if tie.source is not None or not tie.amount:
        return words(tie, titles)
    unit = "week" if tie.unit == "weeks" else "workday"
    return f"{tie.amount} {unit}{'' if tie.amount == 1 else 's'} {tie.direction} {tie.point}"


def timing_words(row_ties: Mapping[str, RowTie], titles: Mapping[int, str]) -> str:
    """A row's ties in one line, its Due's saying so: "Due 1 workday before start". A row tied at both ends gives its Start's first."""
    return " · ".join(("" if f == "start" else "Due ") + brief(row_ties[f], titles) for f in FIELDS if f in row_ties)


# ---- what can be tied to what (decisions 250 and 253) ----
def source_of(tie: RowTie, anchor: int | None) -> int | None:
    return anchor if tie.source is None else tie.source


def followers(lines: Sequence[Line], anchor: int | None) -> Callable[[int], list[int]]:
    """Which rows count from a row: what ``ties.chain`` walks, so sources come first."""
    out: dict[int, list[int]] = {}
    for x in lines:
        for tie in x.ties.values():
            src = source_of(tie, anchor)
            if src is not None and x.id != anchor and x.id not in out.setdefault(src, []):
                out[src].append(x.id)
    return lambda row: out.get(row, [])


def moves_with(lines: Sequence[Line], anchor: int | None, row: int, source: int) -> bool:
    """Whether a row counts from another, near or far: a tie to it would go in a circle."""
    return row in ties.chain(followers(lines, anchor), [source]) and row != source


def problem(lines: Sequence[Line], anchor: int | None) -> str | None:
    """Why a template's timing can't stand, or None: what the Timing window doesn't offer, in case it's asked for another way."""
    by_id = {x.id: x for x in lines}
    if anchor is not None:
        a = by_id.get(anchor)
        if a is None:
            return "That row isn't in this template."
        if not a.placeable:
            return f"{a.title} {'repeats' if a.routine else 'spans its subtasks'}, so it can't be the anchor."
    for x in lines:
        for tie in x.ties.values():
            if tie.amount < 0 or tie.unit not in ties.UNITS or tie.direction not in ties.DIRECTIONS or tie.point not in ties.POINTS:
                return "A tie is a whole number of workdays or weeks, before or after, a start or an end."
            src = source_of(tie, anchor)
            if src is None:
                continue
            if src == x.id:
                return f"{x.title} can't be tied to itself."
            s = by_id.get(src)
            if s is None:
                return f"{x.title} is tied to a row that isn't in this template."
            if s.routine:
                return f"{s.title} repeats, so it has no one date to tie to."
            if moves_with(lines, anchor, src, x.id):
                return f"That would go in a circle: {s.title} already moves with {x.title}."
    return None


# ---- the chart ----
def positions(lines: Sequence[Line], anchor: int | None, week: int) -> dict[int, tuple[int, int]]:
    """Where each row falls, as its first day and how many days, counted in workdays from the anchor's start. A week is ``week``
    workdays. A row with nothing to count from has no place."""
    by_id = {x.id: x for x in lines}
    found: dict[int, tuple[int, int] | None] = {}
    busy: set[int] = set()

    def land(tie: RowTie) -> int | None:
        src = place(source_of(tie, anchor))
        if src is None:
            return None
        ref = src[0] if tie.point == "start" else src[0] + src[1] - 1
        return ref + (-1 if tie.direction == "before" else 1) * tie.amount * (week if tie.unit == "weeks" else 1)

    def place(row: int | None) -> tuple[int, int] | None:
        if row is None or row in busy:
            return None
        if row in found:
            return found[row]
        x = by_id.get(row)
        if x is None or not x.placeable:
            return None
        busy.add(row)
        days = x.days or 1
        s, d = x.ties.get("start"), x.ties.get("due")
        out: tuple[int, int] | None = None
        if row == anchor:
            out = (0, days)
        elif s and d:
            a, b = land(s), land(d)
            if a is not None and b is not None:
                out = (a, max(1, b - a + 1))
        elif s:
            a = land(s)
            if a is not None:
                out = (a, days)
        elif d:
            b = land(d)
            if b is not None:
                out = (b - days + 1, days)
        busy.discard(row)
        found[row] = out
        return out

    for x in lines:
        place(x.id)
    return {k: v for k, v in found.items() if v}


def span_of(lines: Sequence[Line], row: int, pos: Mapping[int, tuple[int, int]]) -> tuple[int, int] | None:
    """Where a row that spans its subtasks falls: from the first of them to the last, as its first day and how many days."""
    low, high = None, None
    for x in lines:
        if x.parent != row:
            continue
        if x.spans:
            q = span_of(lines, x.id, pos)
        else:
            q = pos.get(x.id)
        if q:
            low = q[0] if low is None else min(low, q[0])
            high = q[0] + q[1] if high is None else max(high, q[0] + q[1])
    return None if low is None else (low, high - low)


@dataclass(frozen=True)
class Scale:
    """The chart's width: from ``low`` to ``high`` in workdays, with a line each ``step`` weeks."""

    low: float
    high: float
    step: int
    week: int

    def at(self, day: float) -> float:
        """Where a day falls across the chart, from 0 to 1."""
        return (day - self.low) / (self.high - self.low)

    def ticks(self) -> list[int]:
        """The lines, in weeks from the anchor."""
        first = -int(-self.low // (self.step * self.week))
        last = int(self.high // (self.step * self.week))
        return [k * self.step for k in range(first, last + 1)]


def scale_of(pos: Mapping[int, tuple[int, int]], week: int, labels: int = 6) -> Scale:
    """A chart wide enough for every row, the anchor always in it, with no more than ``labels`` lines."""
    low = min([0, *(p[0] for p in pos.values())])
    high = max([week, *(p[0] + p[1] for p in pos.values())])
    pad = (high - low) * 0.09
    step = next((w for w in (1, 2, 4, 8, 13, 26) if (high - low) / week / w <= labels), 52)
    return Scale(round(low - pad, 2), round(high + pad, 2), step, week)


#: The size of a lane on a template's page. Its pictures are named by what they show, and ``docrepo/ui/timing_chart.py`` draws them.
LANE_WIDTH, LANE_HEIGHT = 170, 18


def lane_address(scale: Scale, bar: tuple[int, int] | None, kind: str) -> str:
    """How a page names a lane, or with ``kind`` ``r`` the ruler: its scale, its bar and what it is."""
    first, days = bar or ("", "")
    return f"timing:{scale.low}:{scale.high}:{scale.step}:{scale.week}:{first}:{days}:{kind}"


def parse_lane(address: str) -> tuple[Scale, tuple[int, int] | None, str] | None:
    """A lane's name, read back. None if it isn't one."""
    try:
        low, high, step, week, first, days, kind = address.split(":")
        return Scale(float(low), float(high), int(step), int(week)), (int(first), int(days)) if first else None, kind
    except ValueError:
        return None


def tick_label(weeks: int) -> str:
    return "Anchor" if weeks == 0 else f"{'+' if weeks > 0 else '−'}{abs(weeks)} wk"


def rebased(lines: Sequence[Line], anchor: int | None, new: int, week: int) -> list[Line]:
    """Another row as the anchor keeps the picture (decision 255): the bars stay where they are, the old anchor gets a tie of its own,
    and what was tied to the anchor counts from the new one."""
    pos = positions(lines, anchor, week)
    zero = pos[new][0] if new in pos and anchor is not None else None

    def again(tie: RowTie | None, day: int) -> RowTie:
        gap = day - zero
        weeks = bool(tie and tie.unit == "weeks") and gap % week == 0
        return RowTie(None, "start", abs(gap // week if weeks else gap), "weeks" if weeks else "workdays", "before" if gap < 0 else "after")

    out = []
    for x in lines:
        now = dict(x.ties)
        q = pos.get(x.id)
        if zero is not None and q and x.id != new and not x.spans:
            if x.id == anchor:
                now = {"start": again(None, q[0])}
            else:
                if "start" in now and now["start"].source is None:
                    now["start"] = again(now["start"], q[0])
                if "due" in now and now["due"].source is None:
                    now["due"] = again(now["due"], q[0] + q[1] - 1)
        now = {f: replace(t, source=None) if t.source == new else t for f, t in now.items()}
        out.append(replace(x, ties={} if x.id == new else now))
    return out


def without_anchor(lines: Sequence[Line]) -> list[Line]:
    """No anchor: the rows tied to it are placed by hand."""
    return [replace(x, ties={f: t for f, t in x.ties.items() if t.source is not None}) for x in lines]


# ---- Make tasks: the dates a tree would get ----
@dataclass
class Typed:
    """What Make tasks' dialog has for a row. ``start`` and ``due`` are typed on a row with no tie, and ``over`` a date typed over a
    tied row's worked-out one, which gives it a new gap (decision 256)."""

    ties: Mapping[str, RowTie] = field(default_factory=dict)
    days: int | None = None
    every: bool = False
    start: str | None = None
    due: str | None = None
    over: str | None = None


def make_dates(typed: Mapping[int, Typed], anchor: int | None, workdays: Collection[int]) -> dict[int, tuple[str | None, str | None]]:
    """The Start and Due each row comes to, worked out as ``templates.make_tasks`` will make them, so the dialog can show them."""
    dates: dict[int, tuple[date | None, date | None]] = {row: (None, None) for row in typed}

    def land(tie: RowTie) -> date | None:
        src = source_of(tie, anchor)
        if src not in dates:
            return None
        ref = dates[src][0 if tie.point == "start" else 1]
        return ties.landing(ref, tie, workdays) if ref else None

    def after(start: date | None, x: Typed) -> date | None:
        return due_after(start, x.days, workdays, x.every) if start and x.days else None

    def before(due: date | None, x: Typed) -> date | None:
        return start_before(due, x.days, workdays, x.every) if due and x.days else None

    for _ in range(len(typed) + 1):  # each pass settles one more link of a chain, and no chain is longer than the rows
        for row, x in typed.items():
            s, d = x.ties.get("start"), x.ties.get("due")
            if x.over:
                start = to_date(x.over)
                dates[row] = (start, after(start, x) or (land(d) if d else None))
            elif s and d:
                dates[row] = (land(s), land(d))
            elif s:
                start = land(s)
                dates[row] = (start, after(start, x))
            elif d:
                due = land(d)
                dates[row] = (before(due, x), due)
            else:
                start, due = to_date(x.start) if x.start else None, to_date(x.due) if x.due else None
                if start and x.days:
                    due = after(start, x)
                elif due and x.days:
                    start = before(due, x)
                dates[row] = (start, due)
    return {row: (a.isoformat() if a else None, b.isoformat() if b else None) for row, (a, b) in dates.items()}
