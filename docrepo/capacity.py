"""The capacity calendar: ``work_calendar`` in docs.db, one row per person, workday and task.

It's a cache built from the task fields, and can be rebuilt at any time:

1. Skip the task if it's Parked, or if nobody on it has hours.
2. Work out its windows (see ``schedule.windows``). Routine tasks repeat until
   Repeat until, the horizon (``capacity_horizon_years`` from today) or the day
   they were closed.
3. For each window and person, spread their hours evenly over the window's
   workdays. A window with no workdays spreads over its calendar days. A lead
   gets the lead hours, an assignee the assignee hours, and someone who is both
   gets both. A closed task's days after its close date are dropped.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from docrepo.config import Settings
from docrepo.dates import add_months, monday_of, to_date, workday_numbers
from docrepo.db import transaction
from docrepo.model import Model, Task, load_tasks
from docrepo.schedule import is_open, windows


def horizon(today: date, settings: Settings) -> date:
    """How far ahead routine tasks fill the calendar."""
    return add_months(today, 12 * settings.capacity_horizon_years)


def roles_of(task: Task) -> list[tuple[str, float]]:
    """(person, hours) for each lead, then each assignee."""
    return [(p, task.lead_hours or 0) for p in task.leads] + [(p, task.assignee_hours or 0) for p in task.assignees]


def task_rows(task: Task, today: date, settings: Settings) -> dict[tuple[str, date], float]:
    """The task's hours per (person, day)."""
    roles = roles_of(task)
    if task.state == "Parked" or not any(h for _, h in roles):
        return {}
    workdays = workday_numbers(settings.workdays)
    closed = to_date(task.closed) if task.closed else None
    rows: dict[tuple[str, date], float] = defaultdict(float)
    for first, last in windows(task, horizon(today, settings)):
        span = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        days = [d for d in span if d.weekday() in workdays] or span
        for person, hours in roles:
            if not hours:
                continue
            for d in days:
                if closed and d > closed:
                    continue
                rows[(person, d)] += hours / len(days)
    return dict(rows)


def rebuild_task(conn: sqlite3.Connection, task_id: str, today: date, settings: Settings) -> int:
    """Replace one task's rows. Call it inside the transaction that saves the task. Returns the number of rows."""
    tasks = load_tasks(conn, [task_id])
    with transaction(conn):
        conn.execute("DELETE FROM work_calendar WHERE task = ?", (task_id,))
        rows = task_rows(tasks[task_id], today, settings) if task_id in tasks else {}
        conn.executemany(
            "INSERT INTO work_calendar (person, date, task, hours) VALUES (?, ?, ?, ?)",
            [(p, d.isoformat(), task_id, h) for (p, d), h in sorted(rows.items())],
        )
    return len(rows)


def rebuild_all(conn: sqlite3.Connection, today: date, settings: Settings) -> int:
    """Rebuild the whole calendar from the task fields. Returns the number of rows."""
    count = 0
    with transaction(conn):
        conn.execute("DELETE FROM work_calendar")
        for task_id in [r[0] for r in conn.execute("SELECT id FROM tasks ORDER BY id")]:
            count += rebuild_task(conn, task_id, today, settings)
    return count


def week_cells(conn: sqlite3.Connection, weeks: list[date]) -> dict[str, dict[date, dict[str, float]]]:
    """Scheduled hours as person -> week (its Monday) -> task -> hours, for the weeks starting on the given Mondays."""
    cells: dict[str, dict[date, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    wanted = set(weeks)
    rows = conn.execute(
        "SELECT person, date, task, hours FROM work_calendar WHERE date BETWEEN ? AND ? ORDER BY task, date, person",
        (min(weeks).isoformat(), (max(weeks) + timedelta(days=6)).isoformat()),
    )
    for r in rows:
        week = monday_of(to_date(r["date"]))
        if week in wanted:
            cells[r["person"]][week][r["task"]] += r["hours"]
    return cells


def week_total(cells: dict[str, dict[date, dict[str, float]]], person: str, week: date) -> float:
    return sum(cells.get(person, {}).get(week, {}).values())


def unplaced(model: Model, today: date, settings: Settings) -> tuple[list[str], list[str]]:
    """Open tasks the calendar can't place: unestimated (people but no hours) and unscheduled (hours but no dates)."""
    unestimated, unscheduled = [], []
    for t in model.tasks.values():
        roles = roles_of(t)
        if t.state == "Parked" or not roles:
            continue
        if not any(h for _, h in roles):
            if is_open(t):
                unestimated.append(t.id)
        elif not windows(t, horizon(today, settings)) and is_open(t):
            unscheduled.append(t.id)
    return unestimated, unscheduled
