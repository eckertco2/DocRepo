"""What the browse tool's views list: the rows of its middle pane, worked out from a Model.

Lists and Documents are shown in tree form: each matching task under its parents,
which show dimmed for context. The task tree keeps a task's parents visible
when a filter hides them, dimmed too. Nothing here draws anything; the browse
window turns these rows into its lists.

Ported from the mockup's ``views.js`` (``treeRows``, ``prunedTree``, ``flatView``,
``docsView``, ``agendaGroups``, ``agendaMarkdown``, ``capacityView``) and the date
cells of ``model.js`` (``dueCell``, ``remText``).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from docrepo import capacity
from docrepo.dates import day_diff, days_text, long_date, monday_of, short, to_date
from docrepo.lists import LISTS, TaskList, list_tasks
from docrepo.model import AgendaItem, Model, Task
from docrepo.schedule import DueDate, due_of, is_open

#: The capacity view's number of weeks.
CAPACITY_WEEKS = 9


@dataclass(frozen=True)
class ViewDef:
    id: str
    label: str
    section: str = ""  # the heading it's listed under in the views pane
    note: str = ""


LIST_NOTES = {
    "due": "Open one-time tasks due within a week, soonest first. Routine tasks are left out.",
    "reminders": "Open tasks with a reminder in the next 7 days, soonest first. A past reminder stays until you clear it or the task "
                 "closes. On the day, DocRepo also shows a Windows notification.",
    "waiting": "Open tasks assigned to someone other than me.",
    "mine": "Open tasks where I'm an assignee.",
    "urgent": "Open tasks with the urgent flag.",
    "unplanned": "Open tasks the capacity calendar can't place: people but no hours, or hours but no dates.",
}

TODAY_NOTE = ("Your list for today. Each item stays until you mark it Done, carrying over to the next day. Add a task with T while "
              "browsing, or Add to Today on its page; add a note here, or from the capture window's Add to agenda.")

VIEWS: tuple[ViewDef, ...] = (
    ViewDef("today", "Today", note=TODAY_NOTE),  # mods log round 1, M0016
    ViewDef("unfiled", "Unfiled"),
    ViewDef("tasks", "Task tree"),
    *(ViewDef(x.id, x.label, "Lists", LIST_NOTES[x.id]) for x in LISTS),
    ViewDef("agenda", "Agendas", "Plan"),
    ViewDef("timeline", "Timeline", "Plan"),  # mods log round 1, M0019: docrepo/timeline.py
    ViewDef("capacity", "Capacity", "Plan"),
    ViewDef("people", "People", "Manage"),
    ViewDef("labels", "Labels", "Manage"),
    ViewDef("docs", "Documents", "Manage"),
    ViewDef("discarded", "Discarded", "Manage", "Tasks and captures discarded as made by mistake, newest first. Nothing is deleted: "
                                                 "they're hidden from the other views, the lists, the pickers and search. Bring back "
                                                 "restores one."),
    ViewDef("settings", "Settings", "Manage"),
)
VIEW_IDS = {v.id: v for v in VIEWS}
LIST_IDS = {x.id: x for x in LISTS}
#: Views that show tasks, so opening a task from them stays in them.
TASK_VIEWS = ("today", "tasks", *LIST_IDS, "agenda", "search")


def view_counts(m: Model, today: date, me: str | None) -> dict[str, int]:
    """The numbers shown next to the views."""
    counts = {
        "today": len(m.today_items()),
        "unfiled": len(m.unfiled_captures()),
        "tasks": sum(1 for t in m.tasks.values() if is_open(t)),
        "people": len(m.active_people()),
        "labels": len(m.active_labels()),
        "docs": sum(1 for d in m.documents if not m.only_in_discarded(d)),
        "discarded": len(m.discarded_tasks()) + len(m.discarded_captures()),
    }
    counts.update({x.id: len(list_tasks(m, x, today, me)) for x in LISTS})
    return counts


# ---- dates in a row ----
@dataclass(frozen=True)
class DueCell:
    text: str  # "16 Oct · 8 d", "Today", "Tomorrow", "3 d late", "2 d ago"
    days: str  # the short form for a narrow list: "8 d"
    cls: str  # "over", "soon" or ""
    tip: str  # "Due Fri 16 Oct, in 8 d"
    deadline: bool = False  # the task has no Due, so this is its deadline, shown in Due's place (M0003)


def rem_text(day: date, today: date) -> str:
    """A reminder that has passed is "ago", not overdue: it's a nudge, not a date the work missed."""
    n = day_diff(today, day)
    return f"{-n} d ago" if n < 0 else days_text(day, today)


def due_cell(t: Task, today: date, d: DueDate | None = None, use_due: bool = True) -> DueCell | None:
    """The date a row shows: the task's days until due, or ``d`` (such as its reminder) instead."""
    if d is None and use_due:
        d = due_of(t, today)
    if d is None:
        return None
    n = day_diff(today, d.date)
    rem = d.label == "Reminder"
    if n < 0:
        text = days = f"{-n} d {'ago' if rem else 'late'}"
    elif n == 0:
        text = days = "Today"
    elif n == 1:
        text = days = "Tomorrow"
    else:
        text, days = f"{short(d.date, today)} · {n} d", f"{n} d"
    tip = f"{d.label} {long_date(d.date, today)}, {rem_text(d.date, today) if rem else days_text(d.date, today)}"
    return DueCell(text, days, "over" if n < 0 else "soon" if n <= 2 else "", tip, d.label == "Deadline")


def list_date(task_list: TaskList, t: Task, today: date) -> DueDate | None:
    """The date a list shows and sorts by: days until due, or the reminder for the Reminders list."""
    if task_list.date_of:
        d = task_list.date_of(t, today)
        return DueDate(d, "Reminder") if d else None
    return due_of(t, today)


def markers(m: Model, t: Task) -> list[tuple[str, str]]:
    """The chips after a task's title: (text, kind), kind being urgent, routine or multi."""
    out = []
    if t.urgent:
        out.append(("Urgent", "urgent"))
    if t.recurrence:
        out.append((f"↻ {t.recurrence}", "routine"))
    n = len(m.parents_of(t.id))
    if n > 1:
        out.append((f"{n} parents", "multi"))
    return out


def path_text(m: Model, task_id: str) -> str:
    """The first chain of parents above a task: "Reactor impeller upgrade › Installation"."""
    return " › ".join(m.task(x).title for x in m.chains_of(task_id)[0][:-1])


def full_path(m: Model, task_id: str) -> str:
    return " › ".join(m.task(x).title for x in m.chains_of(task_id)[0])


# ---- tree form ----
@dataclass
class Node:
    """A row in tree form. ``kind`` is task, doc or group. ``match`` False is a parent shown only for context, dimmed.
    ``group`` is the top-level task's group, for its colour (-1 is grey)."""

    id: str
    kind: str = "task"
    depth: int = 0
    group: int = 0
    match: bool = True
    children: list[Node] = field(default_factory=list)
    label: str = ""  # a group's heading


def walk(nodes: list[Node]):
    """Every node, depth first."""
    for n in nodes:
        yield n
        yield from walk(n.children)


@dataclass(frozen=True)
class TreeFilter:
    parked: bool = False
    closed: bool = False
    routine: bool = True
    #: Tasks with any of these labels, and any of these people as lead or assignee (several of each since mods log round 1, M0018).
    labels: tuple[str, ...] = ()
    people: tuple[str, ...] = ()
    #: A task just saved in the capture window: it shows whatever the filters, with its parents, until something else is selected.
    pin: str | None = None

    @property
    def filtered(self) -> bool:
        return bool(self.labels or self.people)


def task_tree(m: Model, f: TreeFilter) -> list[Node]:
    """The task tree: top-level tasks and their subtasks, as the filters allow.

    Show routine off hides recurring tasks, such as meetings, with their subtasks; a subtask with another parent still
    shows there. With a label or person filter on, a parent that doesn't match shows dimmed (``match`` False). A task
    matches with any of the filter's labels and any of its people.
    """
    def pass_state(t: Task) -> bool:
        return (not t.discarded and (f.parked or t.state != "Parked") and (f.closed or t.state != "Closed")
                and (f.routine or not t.recurrence))

    def pass_filter(t: Task) -> bool:
        return ((not f.labels or any(name in f.labels for name, _ in m.labels_of(t.id)))
                and (not f.people or any(p in f.people for p in (*t.leads, *t.assignees))))

    pinned = {f.pin, *m.ancestors_of(f.pin)} if f.pin and f.pin in m.tasks else set()
    seen: dict[str, bool] = {}

    def visible(task_id: str) -> bool:
        if task_id not in seen:
            t = m.task(task_id)
            seen[task_id] = task_id in pinned or (pass_state(t) and (pass_filter(t) or any(
                pass_state(m.task(d)) and pass_filter(m.task(d)) for d in m.descendants_of(task_id))))
        return seen[task_id]

    groups = 0

    def build(ids: list[str], depth: int, group: int) -> list[Node]:
        nonlocal groups
        out = []
        for task_id in ids:
            if not visible(task_id):
                continue
            g = group
            if depth == 0:
                g, groups = groups, groups + 1
            node = Node(task_id, depth=depth, group=g, match=pass_filter(m.task(task_id)) or task_id == f.pin)
            node.children = build(m.children_of(task_id), depth + 1, g)
            out.append(node)
        return out

    return build([t.id for t in m.top_level()], 0, 0)


# ---- sorting ----
#: How the task tree and the lists can be sorted (mods log round 1, M0015). Each sorts the tasks under each parent, so
#: the tree keeps its shape. "default" is the view's own order: tree order, or soonest first for a list.
SORTS: tuple[tuple[str, str], ...] = (("default", "Default order"), ("due", "Due date"), ("title", "Title"), ("state", "State"),
                                      ("updated", "Last updated"))
STATE_ORDER = {"In progress": 0, "Not started": 1, "Parked": 2, "Closed": 3}


def last_updated(m: Model) -> dict[str, str]:
    """When each task last changed: its latest status log entry or capture, else when it was created ("YYYY-MM-DD HH:MM")."""
    def norm(at: str | None) -> str:
        return (at or "").replace("T", " ")[:16]

    out = {t.id: norm(t.created) for t in m.tasks.values()}
    for e in m.status:
        out[e.task] = max(out.get(e.task, ""), norm(e.at))
    for c in m.live_captures():
        for task_id in m.capture_tasks(c):
            out[task_id] = max(out.get(task_id, ""), norm(c.saved))
    return out


def sort_tree(m: Model, nodes: list[Node], how: str, today: date) -> list[Node]:
    """``nodes`` with each task's subtasks sorted, and the top-level tasks too, their colour bands numbered again in the
    new order. Due date sorts a task by the soonest Due (else Deadline) among it and the subtasks shown under it, undated
    last; Last updated puts the latest first. Ties keep the view's own order."""
    if how == "default" or how not in dict(SORTS):
        return nodes
    updated = last_updated(m) if how == "updated" else {}

    def soonest(n: Node) -> date:
        days = [d.date for x in walk([n]) if x.kind == "task" and (d := due_of(m.task(x.id), today))]
        return min(days, default=date.max)

    def key(n: Node):
        t = m.task(n.id)
        if how == "due":
            return soonest(n)
        if how == "title":
            return t.title.casefold()
        if how == "state":
            return STATE_ORDER.get(t.state, 9)
        return updated.get(n.id, "")

    def sort(level: list[Node]) -> list[Node]:
        for n in level:
            n.children = sort(n.children)
        return sorted(level, key=key, reverse=how == "updated")

    out = sort(nodes)
    for g, top in enumerate(out):
        for x in walk([top]):
            x.group = g
    return out


def pruned_tree(m: Model, holds: Callable[[str], bool], first: Callable[[str], str] | None = None) -> list[Node]:
    """The task tree cut down to tasks that hold something, with every parent kept for context (``match`` False).
    ``first`` orders siblings (by default, tree order)."""
    keep_cache: dict[str, bool] = {}

    def keep(task_id: str) -> bool:
        if task_id not in keep_cache:
            keep_cache[task_id] = holds(task_id) or any(holds(d) for d in m.descendants_of(task_id))
        return keep_cache[task_id]

    groups = 0

    def build(ids: list[str], depth: int, group: int) -> list[Node]:
        nonlocal groups
        kept = [x for x in ids if keep(x)]
        if first:
            kept.sort(key=first)
        out = []
        for task_id in kept:
            g = group
            if depth == 0:
                g, groups = groups, groups + 1
            node = Node(task_id, depth=depth, group=g, match=holds(task_id))
            node.children = build(m.children_of(task_id), depth + 1, g)
            out.append(node)
        return out

    return build([t.id for t in m.top_level()], 0, 0)


def list_tree(m: Model, task_list: TaskList, today: date, me: str | None) -> list[Node]:
    """A list in tree form: each matching task under its parents. Groups come soonest-due first, and so do subtasks."""
    matching = {t.id for t in list_tasks(m, task_list, today, me)}

    def when(task_id: str) -> str:
        d = list_date(task_list, m.task(task_id), today)
        return d.date.isoformat() if d else "9999"

    def soonest(task_id: str) -> str:
        return min((when(x) for x in (task_id, *m.descendants_of(task_id)) if x in matching), default="9999")

    return pruned_tree(m, lambda x: x in matching, soonest)


def documents_tree(m: Model, task_filter: str | None = None, include_subtasks: bool = True) -> list[Node]:
    """Documents in tree form: each task that holds documents, under its parents, with its documents first under it.
    With a Task filter, only that task's documents (and its subtasks'); without one, documents not filed yet come last."""
    scope = None
    if task_filter:
        scope = {task_filter, *m.descendants_of(task_filter)} if include_subtasks else {task_filter}
    by_task: dict[str, list[str]] = {}
    for d in m.documents:
        for task_id in m.document_holders(d):
            by_task.setdefault(task_id, []).append(d)

    def in_scope(task_id: str) -> bool:
        return scope is None or task_id in scope

    tree = pruned_tree(m, lambda x: in_scope(x) and bool(by_task.get(x)) and not m.task(x).discarded)
    for node in walk(tree):
        if node.kind == "task" and in_scope(node.id):
            node.children[:0] = [Node(d, "doc", node.depth + 1, node.group) for d in by_task.get(node.id, [])]
    if scope is None:
        unfiled = [d for d in m.documents if not m.document_holders(d) and not m.only_in_discarded(d)]
        if unfiled:
            tree.append(Node("", "group", 0, -1, False, [Node(d, "doc", 1, -1) for d in unfiled], "Not filed yet"))
    return tree


def collapse_level(nodes: list[Node], expanded: set[str]) -> set[str]:
    """Collapse a level: close every expanded task none of whose subtasks is expanded, so each branch folds up one step."""
    shown = list(_shown(nodes, expanded))
    open_ids = {n.id for n in shown if n.children and n.id in expanded}
    closing = {n.id for n in shown if n.id in open_ids and not any(k.id in open_ids for k in n.children)}
    return expanded - closing


def expand_level(nodes: list[Node], expanded: set[str]) -> set[str]:
    """Expand a level: open every collapsed task that has subtasks, so each branch shows one more level."""
    return expanded | {n.id for n in _shown(nodes, expanded) if n.children and n.id not in expanded}


def _shown(nodes: list[Node], expanded: set[str]):
    for n in nodes:
        yield n
        if n.id in expanded:
            yield from _shown(n.children, expanded)


# ---- unfiled captures ----
SOURCE_NAMES = {"typed": "Typed", "outlook_email": "Email", "file_path": "File path"}


@dataclass(frozen=True)
class CaptureRow:
    id: str
    title: str
    sub: str
    source: str
    saved: str


def unfiled_rows(m: Model, today: date) -> list[CaptureRow]:
    """Unfiled captures, newest first."""
    rows = []
    for c in reversed(m.unfiled_captures()):
        n = len(c.documents)
        sub = c.id + (f" · {n} document{'s' if n > 1 else ''}" if n else "")
        saved = c.saved[11:16] if c.saved[:10] == today.isoformat() else short(to_date(c.saved), today)
        rows.append(CaptureRow(c.id, c.title, sub, SOURCE_NAMES.get(c.source, c.source), saved))
    return rows


# ---- discarded tasks and captures (mods log round 1, M0021) ----
@dataclass(frozen=True)
class DiscardedRow:
    kind: str  # task or capture
    id: str
    title: str
    sub: str
    reason: str
    when: str  # when it was discarded, as a row shows it


def discarded_rows(m: Model, today: date) -> list[DiscardedRow]:
    """Discarded tasks and captures, the most recently discarded first."""
    def when(at: str) -> str:
        return at[11:16] if at[:10] == today.isoformat() else short(to_date(at), today)

    items = [(t.discarded or "", DiscardedRow("task", t.id, t.title, f"Task {t.id} · {path_text(m, t.id) or 'Top-level task'}",
                                              t.discard_reason or "", when(t.discarded or ""))) for t in m.discarded_tasks()]
    items += [(c.discarded or "", DiscardedRow("capture", c.id, c.title, f"Capture {c.id} · saved {short(to_date(c.saved), today)}",
                                               c.discard_reason or "", when(c.discarded or ""))) for c in m.discarded_captures()]
    return [row for _, row in sorted(items, key=lambda x: x[0], reverse=True)]


# ---- Today (mods log round 1, M0016) ----
def since_text(added: str, today: date) -> str:
    """When a carried-over item was added, as "since Mon": the weekday within the past week, else the date."""
    day = to_date(added)
    return ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[day.weekday()] if day_diff(day, today) <= 6 else short(day, today)


def today_groups(m: Model, today: date) -> list[tuple[str, list[AgendaItem]]]:
    """Today's open items in their groups: those carried over from earlier days, then those added today."""
    items = m.today_items()
    carried = [a for a in items if a.added[:10] < today.isoformat()]
    fresh = [a for a in items if a.added[:10] >= today.isoformat()]
    return [g for g in (("Carried over", carried), ("Added today" if carried else "Today", fresh)) if g[1]]


# ---- agendas ----
def current_target(m: Model, wanted: str | None) -> str | None:
    """The agenda the Agendas view shows: the one picked, else the first open meeting."""
    targets = m.agenda_targets()
    return wanted if wanted in targets else targets[0] if targets else None


def agenda_groups(m: Model, target: str) -> list[tuple[str, list[AgendaItem]]]:
    """A target's open items, grouped under the top-level task their subject belongs to. Notes with no task come last."""
    groups: dict[str, list[AgendaItem]] = {}
    for a in m.open_items_for(target):
        name = m.task(m.chains_of(a.subject)[0][0]).title if a.subject else "Other topics"
        groups.setdefault(name, []).append(a)
    rest = groups.pop("Other topics", None)
    if rest:
        groups["Other topics"] = rest
    return list(groups.items())


def closed_items(m: Model, target: str) -> list[AgendaItem]:
    """A target's closed items, most recently closed first."""
    return sorted((a for a in m.agenda if a.target == target and a.closed), key=lambda a: a.closed or "", reverse=True)


def agenda_markdown(m: Model, target: str, today: date) -> str:
    """A target's agenda as Markdown, for Copy as Markdown."""
    when = m.meeting_when(target, today)
    lines = [f"## {m.target_name(target)}{', ' + when if when and when != 'no date set' else ''}", ""]
    for name, items in agenda_groups(m, target):
        lines.append(f"### {name}")
        for a in items:
            lines.append(f"- {m.task(a.subject).title + (': ' + a.note if a.note else '') if a.subject else a.note}")
        lines.append("")
    return "\n".join(lines)


def meetings_for_menu(m: Model, exclude: str | None) -> list[Task]:
    """Add to agenda's list: the open meetings, those with open items first."""
    meetings = [t for t in m.open_meetings() if t.id != exclude]
    return sorted(meetings, key=lambda t: not m.open_items_for(t.id))


# ---- capacity ----
@dataclass(frozen=True)
class CapacityCell:
    hours: float
    use: float | None  # hours as a share of the person's hours a week; None when those aren't set
    cls: str  # u0 (none), u1 (under 80%), u2 (80 to 100%), u3 (over 100%)
    tasks: tuple[tuple[str, float], ...]  # (task, hours), most first


@dataclass(frozen=True)
class CapacityRow:
    person: str
    name: str
    hours_a_week: float | None
    cells: tuple[CapacityCell, ...]


def capacity_weeks(today: date, offset: int = 0) -> list[date]:
    """The Mondays the capacity view shows: nine weeks from this one, moved by ``offset`` pages of nine."""
    first = monday_of(today) + timedelta(weeks=CAPACITY_WEEKS * offset)
    return [first + timedelta(weeks=i) for i in range(CAPACITY_WEEKS)]


def capacity_grid(conn: sqlite3.Connection, m: Model, weeks: list[date]) -> list[CapacityRow]:
    """Scheduled hours per active person and week, from work_calendar."""
    cells = capacity.week_cells(conn, weeks)
    rows = []
    for p in m.active_people():
        out = []
        for w in weeks:
            by_task = dict(cells.get(p.id, {}).get(w, {}))
            hours = sum(by_task.values())
            use = hours / p.hours if p.hours else None
            cls = "u0" if not hours else "u1" if use is None else "u3" if use > 1 else "u2" if use >= 0.8 else "u1"
            out.append(CapacityCell(hours, use, cls, tuple(sorted(by_task.items(), key=lambda kv: -kv[1]))))
        rows.append(CapacityRow(p.id, p.name, p.hours, tuple(out)))
    return rows


def open_count(m: Model, test: Callable[[Task], bool]) -> int:
    return sum(1 for t in m.tasks.values() if is_open(t) and test(t))


def label_tasks(m: Model, name: str) -> list[tuple[str, bool]]:
    """The tasks with a label, as (task, inherited). Discarded tasks are left out."""
    out = []
    for t in m.tasks.values():
        if t.discarded:
            continue
        found = next((inh for n, inh in m.labels_of(t.id) if n == name), None)
        if found is not None:
            out.append((t.id, found))
    return out
