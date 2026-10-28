"""The timeline view (mods log round 1, M0019; round 4, M0067, releases 5.29 and 5.30): open tasks over the coming weeks.

One chart (decision 133): each top-level task is a row that folds, so projects sit on adjacent rows and their overlaps read
straight down. A row's bar runs from Start to Due (or to the Deadline when there's no Due), a deadline is a diamond, and a
routine task is a row of dots, one for each occurrence (a short bar when an occurrence spans days). A row with subtasks
on the chart has a summary bar, their span, with their deadlines; a parent with no dates in view has only that. There are
no group headers: Order by (top-level task, label, person, group, or a parent label's sublabels) sorts the rows that share
a parent by their key, then by their first date, and colours each title by its key. Bars are coloured by project, hours a
week or priority (``BARS``), and show their hours. The Labels and People filters work as the task tree's do. Parked,
closed and discarded tasks are left out, and open tasks with no dates are named under the chart; in Plan mode (release
5.30) they're rows of their own, to be dragged onto it. Focus shows one task and everything under it.

Key dates (release 5.31, the key dates plan) are marks on their task's row (``KeyMark``): a window a thin segment, a start
alone an opening bracket, an end alone a closing tick, a Deadline end a red diamond, a done one grey. A task whose only dates
in view are key dates has a row of its own, and a parent's summary bar takes in its subtasks' key dates. A key date ticked
as a plant activity is a plant event of its own (decision 149): a ``Band`` with its ``key_date``, in the events lane, down
the chart and in the lines naming what falls during one.

Nothing here draws anything: ``docrepo/ui/timeline_view.py`` paints it. Ported from the mockup's ``timeline.js``.
"""
from __future__ import annotations

import math
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

from docrepo import key_dates, quick
from docrepo.dates import add_months, long_date, monday_of, to_date
from docrepo.model import KeyDate, Model, Task
from docrepo.schedule import due_of, is_open, start_of, windows
from docrepo.stories import and_list

#: What the rows can be ordered and their titles coloured by (decision 133), and "parent:" with a parent label's name.
ORDERS = (("top", "Top-level task"), ("label", "Label"), ("person", "Person"), ("group", "Group"))
PARENT = "parent:"
#: What the bars can be coloured by.
BARS = (("project", "Project"), ("hours", "Hours a week"), ("priority", "Priority"))
#: Hours a week, light to dark: (below this many, its name).
HOUR_BINS = ((2.0, "Under 2"), (5.0, "2 to 5"), (10.0, "5 to 10"), (20.0, "10 to 20"), (math.inf, "20 or more"))
#: The ranges the view offers, in weeks.
RANGES = ((9, "9 weeks"), (13, "3 months"), (26, "6 months"), (52, "12 months"))
#: How far a routine task is looked ahead for occurrences, and an undated task for any window at all.
_FAR = timedelta(days=3650)
#: The days a week of work is counted over, for hours a week.
_WORKDAYS = frozenset(range(5))


def order_choices(m: Model) -> list[tuple[str, str]]:
    """What the rows can be ordered by, as (key, name in "Order by …"): the fixed ways, then each parent label."""
    return [*((k, label.lower()) for k, label in ORDERS),
            *((PARENT + lb.name, lb.name) for lb in m.active_labels() if m.is_parent_label(lb.name))]


@dataclass(frozen=True)
class Band:
    """A plant event (release 5.9, M0028), shaded down the whole chart from its start to its end, whatever the filters,
    and a bar in the events lane under the scale (release 5.29)."""

    task: str
    title: str
    start: date
    end: date  # its last day
    key_date: int | None = None  # a key date ticked as a plant activity (release 5.31): its ID; its task's own tick: None


@dataclass(frozen=True)
class KeyMark:
    """A key date on its task's row (release 5.31): its days, its kind (``key_dates.kind``) and its ticks."""

    id: int
    first: date
    last: date
    kind: str  # "window", "on", "from" or "by"
    description: str = ""
    plant: bool = False
    deadline: bool = False
    done: bool = False


@dataclass(frozen=True)
class Row:
    """One task's row: its windows and deadline in view, its subtasks' span, and how to draw them."""

    task: str
    depth: int
    own: bool  # its own dates are in view; else it's here for its subtasks, or (in Plan mode) it has none
    windows: tuple[tuple[date, date], ...] = ()  # first and last day of each window in view
    deadline: date | None = None
    routine: bool = False
    late: bool = False  # an open one-time task whose Due (or Deadline) has passed
    not_started: bool = False
    colour: int = 0  # its top-level task's place among the top-level tasks: the task tree's group colours, in turn
    kids: int = 0  # its subtasks on the chart, shown or folded
    open: bool = False  # its subtasks are shown
    span: tuple[date, date] | None = None  # its subtasks' first and last day, for the summary bar
    sub_deadlines: tuple[date, ...] = ()  # its subtasks' deadlines in view
    undated: bool = False  # it has no dates at all: in Plan mode, a row with a grip, to be dragged onto the chart
    key: int | None = None  # its Order by key's place in ``Timeline.keys``, which colours its title
    plant_event: bool = False
    key_dates: tuple[KeyMark, ...] = ()  # its key dates that reach into view (release 5.31)

    @property
    def ctx(self) -> bool:
        """A parent here only for its subtasks, its name dimmed."""
        return not self.own and not self.undated


@dataclass(frozen=True)
class Timeline:
    start: date  # a Monday
    weeks: int
    rows: tuple[Row, ...]
    undated: tuple[str, ...]  # open tasks with no dates at all, which aren't on it (outside Plan mode)
    events: tuple[Band, ...] = ()  # the plant events in view
    keys: tuple[str, ...] = ()  # Order by's keys, in order, for the titles' colours and their legend

    @property
    def end(self) -> date:
        """The day after the last one shown."""
        return self.start + timedelta(weeks=self.weeks)

    @property
    def days(self) -> int:
        return self.weeks * 7

    def week_starts(self) -> list[date]:
        """The Mondays marked on the scale: each week up to three months, every fourth beyond."""
        every = 4 if self.weeks > 13 else 1
        return [self.start + timedelta(weeks=i) for i in range(0, self.weeks, every)]

    def months(self) -> list[date]:
        """Where each month's name goes: its first day, and the range's first day when a week or more of that month is in view."""
        out = []
        first_next = add_months(self.start.replace(day=1), 1)
        if (first_next - self.start).days >= 7:
            out.append(self.start)
        d = first_next
        while d < self.end:
            out.append(d)
            d = add_months(d, 1)
        return out


def default_start(today: date) -> date:
    """The Monday of the week before this one, so the recent past shows too."""
    return monday_of(today) - timedelta(weeks=1)


def step(weeks: int) -> int:
    """How far Earlier and Later move, in weeks."""
    return 26 if weeks > 26 else 13 if weeks > 13 else 4


def _colours(m: Model) -> dict[str, int]:
    return {t.id: i for i, t in enumerate(m.top_level())}


def marks(t: Task, start: date, end: date) -> tuple[tuple[tuple[date, date], ...], date | None]:
    """A task's windows that reach into [start, end), and its deadline when that falls inside."""
    wins = tuple((a, b) for a, b in windows(t, end) if b >= start and a < end)
    dl = to_date(t.deadline) if t.deadline else None
    return wins, dl if dl and start <= dl < end else None


def is_undated(t: Task, today: date, m: Model | None = None) -> bool:
    """No deadline, no window and (given the model) no key date at all: nothing to put on the chart."""
    return not t.deadline and not windows(t, today + _FAR) and not (m is not None and m.key_dates_of(t.id))


def own_span(t: Task, today: date, m: Model | None = None) -> tuple[date, date] | None:
    """A one-time task's first and last day, its deadline included, and (given the model) its key dates (release 5.31); a
    routine one repeats, so its own dates don't count."""
    days = [] if t.recurrence else [d for w in windows(t, today + _FAR)[:1] for d in w] + ([to_date(t.deadline)] if t.deadline else [])
    if m is not None:
        days += [d for kd in m.key_dates_of(t.id) for d in key_dates.first_last(kd)]
    return (min(days), max(days)) if days else None


def key_marks(m: Model, task_id: str, start: date, end: date) -> tuple[KeyMark, ...]:
    """A task's key dates that reach into [start, end), as marks for its row."""
    out = []
    for kd in m.key_dates_of(task_id):
        a, b = key_dates.first_last(kd)
        if b >= start and a < end:
            out.append(KeyMark(kd.id, a, b, key_dates.kind(kd), kd.description, kd.plant, kd.deadline, bool(kd.done)))
    return tuple(out)


# ---- hours (item 53) ----
def workdays(first: date, last: date) -> int:
    """The workdays from ``first`` to ``last``, both counted; at least one."""
    n = sum((first + timedelta(days=i)).weekday() in _WORKDAYS for i in range((last - first).days + 1))
    return max(1, n)


def hours(t: Task, today: date) -> tuple[float, float | None] | None:
    """The task's whole work, as Capacity counts it (the lead hours for each lead, the assignee hours for each assignee),
    and that a week: the total over its workdays, times five. A routine task's hours are each time, so it has no week."""
    total = (t.lead_hours or 0) * len(t.leads) + (t.assignee_hours or 0) * len(t.assignees)
    if not total:
        return None
    if t.recurrence:
        return total, None
    w = windows(t, today + _FAR)
    return total, (total * 5 / workdays(*w[0]) if w else None)


def _h(x: float) -> str:
    return f"{round(x, 1):g}"


def hours_label(t: Task, today: date, a_week: bool) -> str:
    """What a bar says (decision 135): "36 h", or "4.5 h/wk"; nothing without hours, or for a routine task."""
    h = hours(t, today)
    if not h or t.recurrence:
        return ""
    if a_week:
        return f"{_h(h[1])} h/wk" if h[1] is not None else ""
    return f"{_h(h[0])} h"


def hours_words(m: Model, t: Task, today: date) -> str:
    """The hours in words, for the tooltip and the card: "16 h: Tom Becker 4 h as lead, Sam and Ana 6 h each as assignees ·
    about 4 h a week"."""
    h = hours(t, today)
    if not h:
        return "No hours yet"

    def part(ids: list[str], x: float | None, role: str) -> str:
        if not ids or not x:
            return ""
        many = len(ids) > 1
        return f"{and_list([m.person_name(p) for p in ids])} {_h(x)} h{' each' if many else ''} as {role}{'s' if many else ''}"

    parts = ", ".join(p for p in (part(t.leads, t.lead_hours, "lead"), part(t.assignees, t.assignee_hours, "assignee")) if p)
    if t.recurrence:
        return f"{_h(h[0])} h each time: {parts}"
    return f"{_h(h[0])} h: {parts}" + (f" · about {_h(h[1])} h a week" if h[1] is not None else "")


def hour_bin(t: Task, today: date) -> int:
    """Which of ``HOUR_BINS`` a task's hours a week fall in, or -1 without them."""
    h = hours(t, today)
    if not h or h[1] is None:
        return -1
    return next(i for i, (top, _) in enumerate(HOUR_BINS) if h[1] < top)


# ---- Order by (decision 133) ----
def order_keys(m: Model, order: str) -> list[tuple[str, str]]:
    """The keys rows are ordered by, in order, as (key, name)."""
    if order.startswith(PARENT):
        return [(x, x) for x in m.sublabels(order[len(PARENT):])]
    if order == "label":
        return [(lb.name, lb.name) for lb in m.active_labels()]
    if order == "person":
        return [(p.id, p.name) for p in m.active_people()]
    if order == "group":
        return [(g, g) for g in m.groups()]
    return [(t.id, t.title) for t in m.top_level()]


def keys_of(m: Model, task_id: str, order: str) -> list[str]:
    """A task's keys: its labels (inherited ones too), people, their groups, or its top-level task."""
    t = m.task(task_id)
    if order == "label" or order.startswith(PARENT):
        return [name for name, _ in m.labels_of(task_id)]
    if order == "person":
        return [*dict.fromkeys((*t.leads, *t.assignees))]
    if order == "group":
        return [*dict.fromkeys(m.people[p].group for p in (*t.leads, *t.assignees) if p in m.people and m.people[p].group)]
    return [m.chains_of(task_id)[0][0]]


def key_of(m: Model, task_id: str, order: str, keys: list[tuple[str, str]] | None = None) -> int | None:
    """The first of a task's keys in Order by's order, which colours its title; None when it has none."""
    keys = keys if keys is not None else order_keys(m, order)
    mine = set(keys_of(m, task_id, order))
    return next((i for i, (k, _) in enumerate(keys) if k in mine), None)


def build(m: Model, today: date, start: date, weeks: int, order: str = "top", labels: tuple[str, ...] = (),
          people: tuple[str, ...] = (), routine: bool = True, open_ids: Collection[str] = (), plan: bool = False,
          focus: str | None = None) -> Timeline:
    """The timeline from ``start`` (a Monday) for ``weeks`` weeks: the tree's rows, each shown under its parent when that's
    in ``open_ids``. In Plan mode, tasks with no dates are rows too. ``focus`` shows that task and what's under it."""
    end = start + timedelta(weeks=weeks)
    colours = _colours(m)
    keys = order_keys(m, order)

    def match(t: Task) -> bool:
        return ((not labels or any(name in labels for name, _ in m.labels_of(t.id)))
                and (not people or any(p in people for p in (*t.leads, *t.assignees))))

    def base(t: Task) -> bool:
        return is_open(t) and not quick.is_parent(t) and not (t.recurrence and not routine) and match(t)

    def dated(t: Task) -> bool:
        wins, dl = marks(t, start, end)
        return bool(wins or dl or key_marks(m, t.id, start, end))

    shown = {t.id for t in m.tasks.values() if base(t) and (dated(t) or (plan and is_undated(t, today, m)))}
    below: dict[str, list[str]] = {}

    def under(task_id: str) -> list[str]:
        if task_id not in below:
            below[task_id] = [x for x in m.descendants_of(task_id) if x in shown]
        return below[task_id]

    def has(task_id: str) -> bool:
        return task_id in shown or bool(under(task_id))

    def first(task_id: str) -> date:
        span = own_span(m.task(task_id), today, m) if task_id in shown else None
        return (span or sub_span(task_id) or (date.max, date.max))[0]

    def sub_span(task_id: str) -> tuple[date, date] | None:
        spans = [s for x in under(task_id) if (s := own_span(m.task(x), today, m))]
        return (min(s[0] for s in spans), max(s[1] for s in spans)) if spans else None

    def sub_deadlines(task_id: str) -> tuple[date, ...]:
        """Its subtasks' deadlines in view: their own, and their key dates' ticked as one (decision 147)."""
        days = {d for x in under(task_id) if (d := marks(m.task(x), start, end)[1])}
        days |= {k.last for x in under(task_id) for k in key_marks(m, x, start, end) if k.deadline and start <= k.last < end}
        return tuple(sorted(days))

    def ordered(ids: list[str]) -> list[str]:
        if order == "top":
            return ids
        place = {x: key_of(m, x, order, keys) for x in ids}
        return sorted(ids, key=lambda x: (len(keys) if place[x] is None else place[x], first(x), m.task(x).title.lower()))

    rows: list[Row] = []

    def walk(ids: list[str], depth: int) -> None:
        for task_id in ordered([x for x in ids if has(x)]):
            t = m.task(task_id)
            kids = [x for x in m.children_of(task_id) if has(x)]
            own = task_id in shown and dated(t)
            wins, dl = marks(t, start, end) if own else ((), None)
            due = due_of(t, today)
            span = sub_span(task_id) if kids else None
            subs = sub_deadlines(task_id) if kids else ()
            rows.append(Row(task_id, depth, own, wins, dl, bool(t.recurrence),
                            own and not t.recurrence and due is not None and due.date < today, t.state == "Not started",
                            colours.get(m.chains_of(task_id)[0][0], 0), len(kids), bool(kids) and task_id in open_ids,
                            span if span and span[0] < end and span[1] >= start else None, subs,
                            task_id in shown and not own, key_of(m, task_id, order, keys), t.plant_event,
                            key_marks(m, task_id, start, end) if own else ()))
            if kids and task_id in open_ids:
                walk(kids, depth + 1)

    walk([focus] if focus and focus in m.tasks else [t.id for t in m.top_level()], 0)
    # The built-in Quick tasks (mods log round 2) has no dates of its own, so it's left out of them.
    undated = () if plan else tuple(t.id for t in m.tasks.values() if base(t) and is_undated(t, today, m))
    return Timeline(start, weeks, tuple(rows), undated, bands(m, start, end), tuple(name for _, name in keys) if order != "top" else ())


def all_bands(m: Model, until: date) -> list[Band]:
    """Every plant event up to ``until``: each task ticked as one, from its Start to its Due (or Deadline), a routine one
    each time it comes round (release 5.9, M0028); and each key date ticked as a plant activity, its own days, titled by
    its description, or its task's title when it has none (release 5.31, decision 149)."""
    out = [Band(t.id, t.title, a, b) for t in m.plant_events() for a, b in windows(t, until)]
    for t, kd in m.plant_activities():
        a, b = key_dates.first_last(kd)
        if a <= until:
            out.append(Band(t.id, kd.description or t.title, a, b, kd.id))
    return out


def bands(m: Model, start: date, end: date) -> tuple[Band, ...]:
    """The plant events that reach into [start, end), in date order."""
    return tuple(sorted((b for b in all_bands(m, end) if b.end >= start and b.start < end), key=lambda b: (b.start, b.title.lower())))


def tasks_during(m: Model, band: Band, today: date) -> int:
    """How many open tasks, other than plant events and the key date's own task, have a window in a plant event's days."""
    return sum(1 for t in m.tasks.values() if is_open(t) and not t.plant_event and not quick.is_parent(t)
               and not (band.key_date is not None and t.id == band.task)
               and any(a <= band.end and b >= band.start for a, b in windows(t, today + _FAR)))


def during_text(m: Model, dates: list[tuple[str, str | None]], today: date, task_id: str | None = None) -> str:
    """The line under a form's dates naming the plant events they fall in, such as "Start and Due fall during Spring
    outage, Tue 3 Nov to Sat 14 Nov." (release 5.9, M0028). ``dates`` are (name, YYYY-MM-DD or None); the task's own
    event isn't counted."""
    hits: dict[Band, list[str]] = {}
    for name, value in dates:
        try:
            day = date.fromisoformat(value) if value else None
        except ValueError:
            continue
        band = during(m, day, task_id)
        if band:
            hits.setdefault(band, []).append(name)
    return " ".join(f"{and_list(names)} {'falls' if len(names) == 1 else 'fall'} during {band.title}, {days_text(band, today)}."
                    for band, names in hits.items())


def days_text(band: Band, today: date) -> str:
    """A plant event's days: "Tue 3 Nov to Sat 14 Nov", or its one day."""
    if band.start == band.end:
        return long_date(band.start, today)
    return f"{long_date(band.start, today)} to {long_date(band.end, today)}"


def during(m: Model, day: date | None, task_id: str | None = None) -> Band | None:
    """The plant event a day falls in, if any, for the line under a date field (release 5.9, M0028): a plant event task's,
    or a key date ticked as a plant activity (release 5.31). The task's own events don't count."""
    if day is None:
        return None
    return next((b for b in all_bands(m, day + timedelta(days=1)) if b.task != task_id and b.start <= day <= b.end), None)


def tooltip(m: Model, task_id: str, today: date, order: str = "top", plan: bool = False) -> str:
    """What hovering a row shows: its title, dates, hours and people, a line each, and its keys when it has several."""
    t = m.task(task_id)
    lines = [t.title]
    if is_undated(t, today):
        lines.append("No dates yet" + (": drag its name onto the chart to give it a week" if plan else ""))
    elif t.recurrence:
        nxt = due_of(t, today)
        lines.append(f"{t.recurrence} from {long_date(start_of(t), today)}" + (f", next {long_date(nxt.date, today)}" if nxt else ""))
    else:
        end = f" → Due {long_date(to_date(t.due), today)}" if t.due else f" → Deadline {long_date(to_date(t.deadline), today)}" if t.deadline else ""
        lines.append(f"Start {long_date(start_of(t), today)}{end}")
    if t.deadline and (t.due or t.recurrence):
        lines.append(f"Deadline {long_date(to_date(t.deadline), today)}" + (f", {t.deadline_desc}" if t.deadline_desc else ""))
    lines.append(hours_words(m, t, today))
    for label, ids in (("Lead", t.leads), ("Assignees", t.assignees)):
        if ids:
            lines.append(f"{label}: {', '.join(m.person_name(p) for p in ids)}")
    if order != "top":
        keys = order_keys(m, order)
        mine = set(keys_of(m, task_id, order))
        names = [name for k, name in keys if k in mine]
        if len(names) > 1:
            lines.append(f"{and_list(names)} (coloured by {names[0]})")
    if t.plant_event:
        lines.append("Plant event")
    lines += key_date_lines(m, task_id, today)
    return "\n".join(lines)


def key_date_text(kd: KeyDate, today: date) -> str:
    """One key date for the tooltip and the card: its marks (a flag for a plant activity, a diamond for a deadline), its
    description and dates, and "done"."""
    flags = "".join(x for x, on in (("\u2691 ", kd.plant), ("\u25c6 ", kd.deadline)) if on)
    return f"{flags}{key_dates.label(kd, today)}" + (" (done)" if kd.done else "")


def key_date_lines(m: Model, task_id: str, today: date) -> list[str]:
    """A task's key dates, a line each under "Key dates:", for the tooltip (release 5.31)."""
    kds = m.key_dates_of(task_id)
    return ["Key dates:", *(f"  {key_date_text(kd, today)}" for kd in kds)] if kds else []
