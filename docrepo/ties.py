"""Ties (release 5.50; the task templates design, decisions 245 to 259): a task's Start or Due set from another date, a number of
workdays or weeks before or after another task's start or end, or a key date's on any task.

The dates a tie works out are kept in the task's own Start and Due, so everything that reads dates reads them as any other. Moving
the source keeps the gap, earlier or later (decision 246), and changing a tied date by hand keeps the tie with a new gap (decision
247). This module has the rules and what they read. ``tasks.follow`` does the moving, in the transaction that changed the source,
so every path that changes a date moves what's tied to it.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Collection, Iterable
from dataclasses import replace
from datetime import date, timedelta

from docrepo.dates import to_date
from docrepo.model import Model, Task, Tie
from docrepo.schedule import days_in, due_after, start_before

#: The dates that can be tied, as the forms and the status log name them.
FIELDS = {"start": "Start", "due": "Due"}
UNITS = ("workdays", "weeks")
DIRECTIONS = ("before", "after")
POINTS = ("start", "end")


# ---- the sum, with nothing to read ----
def landing(ref: date, tie: Tie, workdays: Collection[int]) -> date:
    """Where a tie lands, given the date it counts from. Workdays count by Settings, and a week is 7 days, so it's the same weekday."""
    sign = -1 if tie.direction == "before" else 1
    if tie.unit == "weeks":
        return ref + timedelta(days=7 * tie.amount * sign)
    day, left = ref, tie.amount
    while left:
        day += timedelta(days=sign)
        if not workdays or day.weekday() in workdays:
            left -= 1
    return day


def regapped(tie: Tie, ref: date, day: date, workdays: Collection[int]) -> Tie:
    """The same tie with the gap that puts it on ``day`` (decision 247). It stays in weeks when that's still a whole number of them."""
    apart, direction = abs((day - ref).days), "before" if day < ref else "after"
    if tie.unit == "weeks" and apart % 7 == 0:
        return replace(tie, amount=apart // 7, direction=direction)
    first = min(ref, day)
    amount = sum(1 for i in range(1, apart + 1) if not workdays or (first + timedelta(days=i)).weekday() in workdays)
    return replace(tie, amount=amount, unit="workdays", direction=direction)


def words(tie: Tie, name: str) -> str:
    """The tie as a sentence: "3 workdays after Line 2 outage ends", or "The day Line 2 outage starts"."""
    verb = "starts" if tie.point == "start" else "ends"
    if not tie.amount:
        return f"The day {name} {verb}"
    unit = "week" if tie.unit == "weeks" else "workday"
    return f"{tie.amount} {unit}{'' if tie.amount == 1 else 's'} {tie.direction} {name} {verb}"


def placement(t: Task, lands: dict[str, str | None], workdays: Collection[int]) -> dict[str, object]:
    """What a task's dates become once what it's tied to has moved, as ``tasks.update_task`` takes them. ``lands`` has where each of
    its ties lands. One tied date moves the whole task (decisions 251, 252): with a Duration the other date follows, and two plain
    dates keep their length. No date takes it off the calendar, keeping its size."""
    if len(t.ties) == 2:
        return {f: value for f, value in lands.items() if value != getattr(t, f)}
    if not lands:
        return {}
    (f, value), = lands.items()
    if value == getattr(t, f):
        return {}
    if t.duration:
        return {f: value}
    other = "due" if f == "start" else "start"
    length = days_in(to_date(t.start), to_date(t.due), workdays, t.calendar_days) if t.start and t.due and t.due >= t.start else None
    if value is None:
        return {f: None, other: None, **({"duration": length} if length else {})}
    if not length:
        return {f: value}
    moved = due_after(to_date(value), length, workdays, t.calendar_days) if f == "start" else start_before(to_date(value), length, workdays, t.calendar_days)
    return {f: value, other: moved.isoformat()}


def chain(followers_of: Callable[[str], Iterable[str]], starts: Iterable[str]) -> list[str]:
    """Everything reached from ``starts``, near or far, each after what it's tied to."""
    seen: set[str] = set()
    out: list[str] = []

    def visit(task_id: str) -> None:
        if task_id in seen:
            return
        seen.add(task_id)
        for x in followers_of(task_id):
            visit(x)
        out.insert(0, task_id)
    for s in starts:
        visit(s)
    return out


def tops(parents_of: Callable[[str], Iterable[str]], task_id: str) -> set[str]:
    """The top-level tasks over a task, or itself: its tree, for decision 249. A task can have several parents, so several tops."""
    seen, found, todo = set(), set(), [task_id]
    while todo:
        x = todo.pop()
        if x in seen:
            continue
        seen.add(x)
        up = list(parents_of(x))
        if not up:
            found.add(x)
        todo += up
    return found


# ---- reading docs.db ----
def _chosen(point: str, start: str | None, end: str | None, either: bool) -> str | None:
    """A source's date: a key date with one date has it at both ends, and a task's own dates are as they are."""
    return (start or (end if either else None)) if point == "start" else (end or (start if either else None))


def ref_date(conn: sqlite3.Connection, tie: Tie) -> date | None:
    """The date a tie counts from, or None while it has none."""
    if tie.key_date is not None:
        r = conn.execute("SELECT start_day, end_day FROM task_dates WHERE id = ?", (tie.key_date,)).fetchone()
        value = _chosen(tie.point, r["start_day"], r["end_day"], True) if r else None
    else:
        r = conn.execute("SELECT start, due FROM tasks WHERE id = ?", (tie.source,)).fetchone()
        value = _chosen(tie.point, r["start"], r["due"], False) if r else None
    return to_date(value) if value else None


def counts(conn: sqlite3.Connection, tie: Tie) -> bool:
    """A discarded source moves nothing, and what's tied to it keeps its dates until it's brought back (decision 258)."""
    r = conn.execute("SELECT discarded FROM tasks WHERE id = ?", (tie.source,)).fetchone()
    return r is not None and not r["discarded"]


def lands_of(conn: sqlite3.Connection, t: Task, workdays: Collection[int]) -> dict[str, str | None]:
    """Where each of a task's ties lands, leaving out those that don't count just now."""
    out: dict[str, str | None] = {}
    for f, tie in t.ties.items():
        if counts(conn, tie):
            ref = ref_date(conn, tie)
            out[f] = landing(ref, tie, workdays).isoformat() if ref else None
    return out


def source_name(conn: sqlite3.Connection, tie: Tie) -> str:
    r = conn.execute("SELECT title FROM tasks WHERE id = ?", (tie.source,)).fetchone()
    title = r["title"] if r else "a task"
    if tie.key_date is None:
        return title
    k = conn.execute("SELECT description FROM task_dates WHERE id = ?", (tie.key_date,)).fetchone()
    return f"{title}: {(k['description'] if k else '') or 'its key date'}"


def said(conn: sqlite3.Connection, tie: Tie | None) -> str | None:
    """A tie as the status log keeps it, or None for no tie."""
    return words(tie, source_name(conn, tie)) if tie else None


def own_followers(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """The tasks tied to a task's own dates. A tie to its key date isn't one: key dates don't follow its dates."""
    return [r["task"] for r in conn.execute("SELECT DISTINCT task FROM task_ties WHERE source = ? AND key_date IS NULL ORDER BY task", (task_id,))]


def every_follower(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """The tasks tied to a task's own dates or its key dates."""
    return [r["task"] for r in conn.execute("SELECT DISTINCT task FROM task_ties WHERE source = ? ORDER BY task", (task_id,))]


def key_followers(conn: sqlite3.Connection, key_ids: Iterable[int]) -> list[str]:
    ids = list(key_ids)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [r["task"] for r in conn.execute(f"SELECT DISTINCT task FROM task_ties WHERE key_date IN ({marks}) ORDER BY task", ids)]


def problem(conn: sqlite3.Connection, task_id: str, tie: Tie) -> str | None:
    """Why a date can't be tied there, or None. Decisions 250 and 253."""
    r = conn.execute("SELECT title, recurrence, discarded FROM tasks WHERE id = ?", (tie.source,)).fetchone()
    if r is None:
        return f"There's no task {tie.source}."
    if tie.amount < 0 or tie.unit not in UNITS or tie.direction not in DIRECTIONS or tie.point not in POINTS:
        return "A tie is a whole number of workdays or weeks, before or after, a start or an end."
    if tie.key_date is not None:
        k = conn.execute("SELECT 1 FROM task_dates WHERE id = ? AND task = ?", (tie.key_date, tie.source)).fetchone()
        return None if k else f"That key date isn't on {r['title']} any more."
    if tie.source == task_id:
        return "A task's date can't be tied to its own dates. Choose one of its key dates, or another task."
    if r["recurrence"]:
        return f"{r['title']} repeats, so it has no one date to tie to. Tie to one of its key dates, or to another task."
    if tie.source in chain(lambda x: own_followers(conn, x), own_followers(conn, task_id)):
        return f"That would go in a circle: {r['title']} already moves with this task."
    return None


# ---- reading the model, for the forms and the pages ----
def own_followers_in(m: Model, task_id: str) -> list[str]:
    return [t.id for t in m.tied_to(task_id) if any(x.source == task_id and x.key_date is None for x in t.ties.values())]


def ref_in(m: Model, tie: Tie) -> date | None:
    if tie.key_date is not None:
        k = next((x for x in m.key_dates_of(tie.source) if x.id == tie.key_date), None)
        value = _chosen(tie.point, k.start, k.end, True) if k else None
    else:
        t = m.tasks.get(tie.source)
        value = _chosen(tie.point, t.start, t.due, False) if t else None
    return to_date(value) if value else None


def name_in(m: Model, tie: Tie) -> str:
    t = m.tasks.get(tie.source)
    title = t.title if t else "a task"
    if tie.key_date is None:
        return title
    k = next((x for x in m.key_dates_of(tie.source) if x.id == tie.key_date), None)
    return f"{title}: {(k.description if k else '') or 'its key date'}"


def counts_in(m: Model, tie: Tie) -> bool:
    t = m.tasks.get(tie.source)
    return t is not None and not t.discarded


def landing_in(m: Model, tie: Tie, workdays: Collection[int]) -> str | None:
    """Where a tie lands, or None while it has nothing to count from."""
    ref = ref_in(m, tie) if counts_in(m, tie) else None
    return landing(ref, tie, workdays).isoformat() if ref else None


def problem_in(m: Model, task_id: str, tie: Tie) -> str | None:
    """Why a form can't tie there, as ``problem`` says it."""
    t = m.tasks.get(tie.source)
    if t is None:
        return f"There's no task {tie.source}."
    if tie.key_date is not None:
        return None
    if tie.source == task_id:
        return "A task's date can't be tied to its own dates. Choose one of its key dates, or another task."
    if t.recurrence:
        return f"{t.title} repeats, so it has no one date to tie to. Tie to one of its key dates, or to another task."
    if tie.source in chain(lambda x: own_followers_in(m, x), own_followers_in(m, task_id)):
        return f"That would go in a circle: {t.title} already moves with this task."
    return None
