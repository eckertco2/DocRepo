"""The timeline view (mods log round 1, M0019, with M0015's sorting by label): open tasks over the coming weeks.

A bar runs from Start to Due (or to the Deadline when there's no Due), a deadline is a diamond, and a routine task is
a row of dots, one for each occurrence (a short bar when an occurrence spans days). Rows group by top-level task,
keeping the tree's shape with undated parents dimmed for context, or by label or person, soonest first, a task
showing under each of its labels (inherited ones too) or people. The Labels and People filters work as the task
tree's do: a task matches with any of the ticked labels and any of the ticked people. Parked, closed and discarded
tasks are left out, and open tasks with no dates are named under the chart.

Nothing here draws anything: ``docrepo/ui/timeline_view.py`` paints it. Ported from the mockup's ``timeline.js``
(``tlRows``, ``tlMarks``, ``tlScale``, ``tlTip``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from docrepo import quick
from docrepo.dates import add_months, long_date, monday_of, to_date
from docrepo.model import Model, Task
from docrepo.schedule import due_of, is_open, start_of, windows

GROUPS = (("top", "Top-level task"), ("label", "Label"), ("person", "Person"))
#: The ranges the view offers, in weeks.
RANGES = ((9, "9 weeks"), (26, "6 months"))
#: How far a routine task is looked ahead for occurrences, and an undated task for any window at all.
_FAR = timedelta(days=3650)


@dataclass(frozen=True)
class Row:
    """One task's row: its windows and deadline in view, and how to draw them."""

    task: str
    depth: int
    ctx: bool  # a parent with no dates in view, shown dimmed so its subtasks have their place
    windows: tuple[tuple[date, date], ...] = ()  # first and last day of each window in view
    deadline: date | None = None
    routine: bool = False
    late: bool = False  # an open one-time task whose Due (or Deadline) has passed
    not_started: bool = False
    colour: int = 0  # its top-level task's place among the top-level tasks: the task tree's group colours, in turn


@dataclass(frozen=True)
class Group:
    name: str
    rows: tuple[Row, ...]
    colour: int | None = None  # a top-level task's group has its colour

    @property
    def count(self) -> int:
        return sum(not r.ctx for r in self.rows)


@dataclass(frozen=True)
class Timeline:
    start: date  # a Monday
    weeks: int
    groups: tuple[Group, ...]
    undated: tuple[str, ...]  # open tasks with no dates at all, which aren't on it

    @property
    def end(self) -> date:
        """The day after the last one shown."""
        return self.start + timedelta(weeks=self.weeks)

    @property
    def days(self) -> int:
        return self.weeks * 7

    def week_starts(self) -> list[date]:
        """The Mondays labelled on the scale: each week over nine weeks, every fourth over six months."""
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
    return 13 if weeks > 13 else 4


def _colours(m: Model) -> dict[str, int]:
    return {t.id: i for i, t in enumerate(m.top_level())}


def marks(t: Task, start: date, end: date) -> tuple[tuple[tuple[date, date], ...], date | None]:
    """A task's windows that reach into [start, end), and its deadline when that falls inside."""
    wins = tuple((a, b) for a, b in windows(t, end) if b >= start and a < end)
    dl = to_date(t.deadline) if t.deadline else None
    return wins, dl if dl and start <= dl < end else None


def build(m: Model, today: date, start: date, weeks: int, group: str = "top", labels: tuple[str, ...] = (),
          people: tuple[str, ...] = (), routine: bool = True) -> Timeline:
    """The timeline from ``start`` (a Monday) for ``weeks`` weeks, grouped by top-level task, label or person."""
    end = start + timedelta(weeks=weeks)
    colours = _colours(m)

    def match(t: Task) -> bool:
        return ((not labels or any(name in labels for name, _ in m.labels_of(t.id)))
                and (not people or any(p in people for p in (*t.leads, *t.assignees))))

    def shown(t: Task) -> bool:
        if not is_open(t) or (t.recurrence and not routine) or not match(t):
            return False
        wins, dl = marks(t, start, end)
        return bool(wins or dl)

    def row(task_id: str, depth: int, ctx: bool) -> Row:
        t = m.task(task_id)
        wins, dl = marks(t, start, end)
        due = due_of(t, today)
        return Row(task_id, depth, ctx, () if ctx else wins, None if ctx else dl, bool(t.recurrence),
                   not ctx and not t.recurrence and due is not None and due.date < today, t.state == "Not started",
                   colours.get(m.chains_of(task_id)[0][0], 0))

    on = {t.id for t in m.tasks.values() if shown(t)}
    groups: list[Group] = []
    if group == "top":
        for top in m.top_level():
            rows: list[Row] = []

            def add(task_id: str, depth: int) -> None:
                if task_id not in on and not any(d in on for d in m.descendants_of(task_id)):
                    return
                rows.append(row(task_id, depth, task_id not in on))
                for kid in m.children_of(task_id):
                    add(kid, depth + 1)

            add(top.id, 0)
            if rows:
                groups.append(Group(top.title, tuple(rows), colours[top.id]))
    else:
        by_label = group == "label"
        picked = labels if by_label else people
        keys = [(lb.name, lb.name) for lb in m.active_labels()] if by_label else [(p.id, p.name) for p in m.active_people()]

        def of(task_id: str) -> list[str]:
            t = m.task(task_id)
            return [name for name, _ in m.labels_of(task_id)] if by_label else [*dict.fromkeys((*t.leads, *t.assignees))]

        def first(task_id: str) -> date:
            wins, dl = marks(m.task(task_id), start, end)
            return wins[0][0] if wins else dl or end

        def sorted_rows(ids: list[str]) -> tuple[Row, ...]:
            return tuple(row(x, 0, False) for x in sorted(ids, key=lambda x: (first(x), m.task(x).title.lower())))

        for key, name in keys:
            if picked and key not in picked:
                continue
            ids = [x for x in on if key in of(x)]
            if ids:
                groups.append(Group(name, sorted_rows(ids)))
        none = [x for x in on if not of(x)]
        if none and not picked:
            groups.append(Group("No label" if by_label else "No one", sorted_rows(none)))
    # The built-in Quick tasks (mods log round 2) has no dates of its own, so it's left out of them.
    undated = tuple(t.id for t in m.tasks.values()
                    if is_open(t) and match(t) and not t.deadline and not windows(t, today + _FAR) and not quick.is_parent(t))
    return Timeline(start, weeks, tuple(groups), undated)


def tooltip(m: Model, task_id: str, today: date) -> str:
    """What hovering a row shows: its title, dates and people, a line each."""
    t = m.task(task_id)
    lines = [t.title]
    if t.recurrence:
        nxt = due_of(t, today)
        lines.append(f"{t.recurrence} from {long_date(start_of(t), today)}" + (f", next {long_date(nxt.date, today)}" if nxt else ""))
    else:
        end = f" → Due {long_date(to_date(t.due), today)}" if t.due else f" → Deadline {long_date(to_date(t.deadline), today)}" if t.deadline else ""
        lines.append(f"Start {long_date(start_of(t), today)}{end}")
    if t.deadline and (t.due or t.recurrence):
        lines.append(f"Deadline {long_date(to_date(t.deadline), today)}" + (f", {t.deadline_desc}" if t.deadline_desc else ""))
    for label, ids in (("Lead", t.leads), ("Assignees", t.assignees)):
        if ids:
            lines.append(f"{label}: {', '.join(m.person_name(p) for p in ids)}")
    return "\n".join(lines)
