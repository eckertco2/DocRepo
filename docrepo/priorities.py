"""Priorities (mods log round 2, M0029, M0030; release 5.23, decisions 23 and 74 to 78).

A priority is a task field holding a bucket, with an order inside it: Critical, High, Medium and Parking lot, plus Not
ranked (decision 23). The Priorities board (``docrepo/ui/priorities_view.py``) shows the open tasks as cards in a column
per bucket. Not ranked has no order of its own: it's sorted for you, urgent first, then the soonest due (decision 75).
A move to another bucket goes into the status log as Priority ("Ranked Critical."); a move within one doesn't (decision
76). Urgent stays a flag of its own (decision 77), and Parking lot isn't Parked: it's an open task ranked lowest, while
Parked is a state, off the board (decision 78).

Ported from the browse tool mockup's ``priorities.js``.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from docrepo import quick, tasks
from docrepo.db import transaction
from docrepo.model import PRIORITY_NAMES, Model, Task
from docrepo.schedule import due_of, is_open

#: The buckets, in order: (key, name, the key 1 to 4 that moves a card there).
BUCKETS: tuple[tuple[str, str, str], ...] = tuple((key, label, str(i + 1)) for i, (key, label) in enumerate(PRIORITY_NAMES.items()))
NOT_RANKED = ("", "Not ranked", "0")
#: The board's columns, Not ranked first.
COLUMNS = (NOT_RANKED, *BUCKETS)
NAMES = {key: label for key, label, _ in COLUMNS}
#: The key 0 to 4 that moves the selected card, to its bucket.
BY_DIGIT = {digit: key for key, _, digit in COLUMNS}
#: Each bucket's place, for Sort by priority.
ORDER = {key: i for i, (key, _, _) in enumerate(BUCKETS)}
#: The status log's name for the field.
FIELD = "Priority"
#: Who made a move on the board, in the status log.
VIA = "Priorities view"
#: The board's Due filter.
DUE_CHOICES = (("any", "Any time"), ("over", "Overdue"), ("7", "Due in 7 days"), ("30", "Due in 30 days"), ("none", "No due date"))


def name(bucket: str | None) -> str:
    return NAMES.get(bucket or "", NAMES[""])


def sort_key(t: Task) -> tuple[int, int]:
    """Sort by priority: Critical first, each bucket in its own order, Not ranked last."""
    return (ORDER.get(t.priority or "", len(BUCKETS)), t.priority_rank or 0)


def on_board(t: Task, routine: bool = False) -> bool:
    """Every open task, top-level tasks and parents too, but not routine ones (unless shown) or Quick tasks itself
    (decision 74). Parked and closed tasks aren't open."""
    return is_open(t) and not quick.is_parent(t) and (routine or not t.recurrence)


@dataclass(frozen=True)
class BoardFilter:
    """The board's filters: any of these people as lead or assignee, any of these labels, when it's due, and routine tasks."""

    people: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    due: str = "any"
    routine: bool = False


def shown(m: Model, t: Task, f: BoardFilter, today: date) -> bool:
    if not on_board(t, f.routine):
        return False
    if f.people and not any(p in f.people for p in (*t.leads, *t.assignees)):
        return False
    if f.labels and not any(n in f.labels for n, _ in m.labels_of(t.id)):
        return False
    if f.due == "any":
        return True
    d = due_of(t, today)
    if f.due == "none":
        return d is None
    if d is None:
        return False
    days = (d.date - today).days
    return days < 0 if f.due == "over" else days <= int(f.due)


def tree_order(m: Model) -> dict[str, int]:
    """Each task's place in the task tree, top to bottom, for ties."""
    order: dict[str, int] = {}

    def go(task_id: str) -> None:
        if task_id not in order:
            order[task_id] = len(order)
            for child in m.children_of(task_id):
                go(child)

    for t in m.top_level():
        go(t.id)
    return order


def bucket_ids(m: Model, bucket: str) -> list[str]:
    """A bucket's tasks in its order."""
    return [t.id for t in sorted((t for t in m.tasks.values() if t.priority == bucket), key=lambda t: (t.priority_rank or 0, t.id))]


def not_ranked(m: Model, today: date, routine: bool = False) -> list[str]:
    """The open tasks with no priority, sorted for you: urgent first, then the soonest due, then tree order (decision 75)."""
    order = tree_order(m)

    def key(t: Task):
        d = due_of(t, today)
        return (not t.urgent, d.date if d else date.max, order.get(t.id, len(order)))

    return [t.id for t in sorted((t for t in m.tasks.values() if on_board(t, routine) and not t.priority), key=key)]


@dataclass
class Column:
    key: str  # the bucket, "" for Not ranked
    name: str
    digit: str
    ids: list[str]


def columns(m: Model, today: date, f: BoardFilter) -> list[Column]:
    """The board: a column per bucket, Not ranked first, each with the tasks the filters show, in its order."""
    out = []
    for key, label, digit in COLUMNS:
        ids = not_ranked(m, today, f.routine) if not key else bucket_ids(m, key)
        out.append(Column(key, label, digit, [x for x in ids if shown(m, m.task(x), f, today)]))
    return out


# ---- moving a task ----
def _ids(conn: sqlite3.Connection, bucket: str) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM tasks WHERE priority = ? ORDER BY priority_rank, id", (bucket,))]


def _number(conn: sqlite3.Connection, bucket: str, ids: list[str]) -> None:
    conn.executemany("UPDATE tasks SET priority = ?, priority_rank = ? WHERE id = ?", [(bucket, i + 1, x) for i, x in enumerate(ids)])


def place(conn: sqlite3.Connection, task_id: str, bucket: str, before: str | None = None, *, at: datetime, via: str) -> tasks.Change | None:
    """Put a task in ``bucket`` ("" takes it out: Not ranked), just before the task ``before`` there, else at the end, and
    number the bucket again. A change of bucket goes into the status log with ``via``; a move within the bucket doesn't.
    Returns the change, or None when the bucket stayed the same."""
    if bucket and bucket not in ORDER:
        raise tasks.TaskError(f"Unknown priority {bucket!r}. Use {', '.join(ORDER)}.")
    with transaction(conn):
        old = tasks.get_task(conn, task_id).priority or ""
        if bucket:
            ids = [x for x in _ids(conn, bucket) if x != task_id]
            ids.insert(ids.index(before) if before in ids else len(ids), task_id)
            _number(conn, bucket, ids)
        else:
            conn.execute("UPDATE tasks SET priority = NULL, priority_rank = NULL WHERE id = ?", (task_id,))
        if old and old != bucket:
            _number(conn, old, _ids(conn, old))
        if old == bucket:
            return None
        change = tasks.Change(FIELD, NAMES[old] if old else None, NAMES[bucket] if bucket else None)
        tasks.record(conn, task_id, at, via, [change])
    return change


def nudge(conn: sqlite3.Connection, task_id: str, step: int, shown_ids: list[str]) -> bool:
    """Alt+Up and Alt+Down: one place up (-1) or down (+1) among the cards shown in its bucket. Not in the status log.
    False when there's nowhere to go, or the task isn't ranked."""
    with transaction(conn):
        bucket = tasks.get_task(conn, task_id).priority
        if not bucket:
            return False
        ids = _ids(conn, bucket)
        seen = [x for x in ids if x in shown_ids or x == task_id]
        j = seen.index(task_id) + step
        if not 0 <= j < len(seen):
            return False
        ids.remove(task_id)
        ids.insert(ids.index(seen[j]) + (1 if step > 0 else 0), task_id)
        _number(conn, bucket, ids)
    return True
