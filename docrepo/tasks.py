"""Creating and changing tasks: their fields, people, labels and parent links.

Every change to an existing task goes into its status log, with the old and new
values as they're shown and where the change came from (a capture's ID, or
"Browse tool", "Capture window" and so on). The task's rows in the capacity
calendar are rebuilt in the same transaction, so the calendar always matches.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docrepo import capacity
from docrepo.config import Settings
from docrepo.dates import check_date, stamp
from docrepo.db import RECURRENCES, STATES, next_id, transaction
from docrepo.model import Task, load_tasks
from docrepo.pages import num

#: The fields a change can set, with their names in the status log, in the order the log lists them.
FIELDS = (
    ("state", "State"), ("current_status", "Current status"), ("due", "Due"), ("deadline", "Deadline"),
    ("deadline_desc", "Deadline description"), ("leads", "Lead"), ("assignees", "Assignees"), ("lead_hours", "Lead hours"),
    ("assignee_hours", "Assignee hours"), ("urgent", "Urgent"), ("meeting", "Meeting"), ("plant_event", "Plant event"), ("start", "Start"),
    ("reminder", "Reminder"), ("recurrence", "Recurrence"), ("repeat_until", "Repeat until"), ("title", "Title"),
    ("description", "Description"), ("labels", "Labels"), ("inherit_labels", "Inherit parent labels"),
)
FIELD_NAMES = dict(FIELDS)
DATE_FIELDS = ("due", "deadline", "start", "reminder", "repeat_until")
TEXT_FIELDS = ("title", "current_status", "deadline_desc", "description")
FLAG_FIELDS = ("urgent", "meeting", "inherit_labels", "plant_event")
#: Reference fields (mods log round 2, M0034, release 5.9): named in Settings, each logged under its own name.
REFERENCES = "references"
HOUR_FIELDS = ("lead_hours", "assignee_hours")
ROLES = {"leads": "lead", "assignees": "assignee"}


class TaskError(ValueError):
    """A task change that isn't allowed, such as an unknown person or a parent link that would make a loop."""


@dataclass(frozen=True)
class Change:
    """One status log entry: a field, and its value before and after, as shown. None shows as "None"."""

    field: str
    from_value: str | None
    to_value: str | None


# ---- checking values ----
def _normalize(conn: sqlite3.Connection, key: str, value: Any) -> Any:
    if key in DATE_FIELDS:
        return check_date(value) if value else None
    if key in TEXT_FIELDS:
        text = (value or "").strip()
        if key == "title" and not text:
            raise TaskError("A task needs a title.")
        if key == "deadline_desc":
            return text or None
        return text
    if key in FLAG_FIELDS:
        return bool(value)
    if key in HOUR_FIELDS:
        if value is None or value == "":
            return None
        hours = float(value)
        if hours < 0:
            raise TaskError("Hours can't be negative.")
        return hours
    if key == "state":
        if value not in STATES:
            raise TaskError(f"Unknown state {value!r}. Use {', '.join(STATES)}.")
        return value
    if key == "recurrence":
        if value and value not in RECURRENCES:
            raise TaskError(f"Unknown recurrence {value!r}. Use {', '.join(RECURRENCES)}.")
        return value or None
    if key in ROLES:
        people = list(dict.fromkeys(value or ()))
        for person in people:
            if conn.execute("SELECT 1 FROM people WHERE id = ?", (person,)).fetchone() is None:
                raise TaskError(f"There's no person {person}.")
        return people
    if key == "labels":
        names = []
        for name in value or ():
            row = conn.execute("SELECT name FROM labels WHERE name = ?", (name.strip(),)).fetchone()
            if row is None:
                raise TaskError(f"There's no label called {name}.")
            names.append(row["name"])
        return list(dict.fromkeys(names))
    raise TaskError(f"{key!r} isn't a task field.")


def _shown(conn: sqlite3.Connection, key: str, value: Any) -> str | None:
    """A value as the status log shows it."""
    if key in FLAG_FIELDS:
        return "Yes" if value else "No"
    if key in HOUR_FIELDS:
        return None if value is None else num(value)
    if key in ROLES:
        names = [conn.execute("SELECT name FROM people WHERE id = ?", (p,)).fetchone()["name"] for p in value]
        return ", ".join(names) or None
    if key == "labels":
        return ", ".join(value) or None
    return value or None


def _apply_lists(conn: sqlite3.Connection, task_id: str, key: str, value: list[str]) -> None:
    """Replace a task's leads, assignees or labels."""
    if key in ROLES:
        conn.execute("DELETE FROM task_people WHERE task = ? AND role = ?", (task_id, ROLES[key]))
        conn.executemany("INSERT INTO task_people (task, person, role) VALUES (?, ?, ?)", [(task_id, p, ROLES[key]) for p in value])
    else:
        conn.execute("DELETE FROM task_labels WHERE task = ?", (task_id,))
        conn.executemany("INSERT INTO task_labels (task, label) SELECT ?, id FROM labels WHERE name = ?", [(task_id, n) for n in value])


def _references(value: Any) -> dict[str, str]:
    """Reference field values by name, trimmed; an empty value clears that field."""
    out: dict[str, str] = {}
    for name, v in dict(value or {}).items():
        name = str(name).strip()
        if not name:
            raise TaskError("A reference field needs a name.")
        out[name] = str(v or "").strip()
    return out


def _apply_references(conn: sqlite3.Connection, task_id: str, task_refs: dict[str, str], new: dict[str, str]) -> list[Change]:
    """Set a task's reference fields; returns their status log entries."""
    logged = []
    for name, value in new.items():
        old = task_refs.get(name, "")
        if old == value:
            continue
        logged.append(Change(name, old or None, value or None))
        conn.execute("DELETE FROM task_references WHERE task = ? AND name = ?", (task_id, name))
        if value:
            conn.execute("INSERT INTO task_references (task, name, value) VALUES (?, ?, ?)", (task_id, name, value))
    return logged


def _apply_columns(conn: sqlite3.Connection, task_id: str, columns: dict[str, Any]) -> None:
    """Set a task's own fields in one statement, so the table's checks see them all changed together."""
    if columns:
        stored = {k: int(v) if k in FLAG_FIELDS else v for k, v in columns.items()}
        assignments = ", ".join(f"{k} = ?" for k in stored)
        conn.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", (*stored.values(), task_id))


def _check_repeat(recurrence: str | None, repeat_until: str | None) -> None:
    if repeat_until and not recurrence:
        raise TaskError("Repeat until can only be set on a task with a recurrence.")


# ---- creating ----
def create_task(
    conn: sqlite3.Connection, settings: Settings, *, title: str, at: datetime, created_by: str,
    parents: Sequence[str] = (), description: str = "", state: str = "Not started", current_status: str = "",
    start: str | None = None, due: str | None = None, deadline: str | None = None, deadline_desc: str | None = None,
    reminder: str | None = None, recurrence: str | None = None, repeat_until: str | None = None,
    urgent: bool = False, meeting: bool = False, leads: Sequence[str] = (), assignees: Sequence[str] = (),
    lead_hours: float | None = None, assignee_hours: float | None = None, labels: Sequence[str] = (),
    inherit_labels: bool = True, plant_event: bool = False, references: dict[str, str] | None = None,
) -> str:
    """Create a task, under ``parents`` if any are given (a top-level task if not). Returns its ID.

    ``created_by`` is the capture that created it, or "Excel import" and so on.
    """
    values = {
        "title": title, "state": state, "current_status": current_status, "start": start, "due": due,
        "deadline": deadline, "deadline_desc": deadline_desc, "reminder": reminder, "recurrence": recurrence,
        "repeat_until": repeat_until, "urgent": urgent, "meeting": meeting, "lead_hours": lead_hours,
        "assignee_hours": assignee_hours, "inherit_labels": inherit_labels, "plant_event": plant_event,
    }
    with transaction(conn):
        values = {k: _normalize(conn, k, v) for k, v in values.items()}
        people = {k: _normalize(conn, k, v) for k, v in (("leads", leads), ("assignees", assignees))}
        label_names = _normalize(conn, "labels", labels)
        _check_repeat(values["recurrence"], values["repeat_until"])
        for parent in parents:
            if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (parent,)).fetchone() is None:
                raise TaskError(f"There's no parent task {parent}.")
        task_id = next_id(conn, "T")
        today = at.date().isoformat()
        columns = {**values, "id": task_id, "description": description.strip(), "created": today, "created_by": created_by,
                   "closed": today if values["state"] == "Closed" else None}
        columns = {k: int(v) if k in FLAG_FIELDS else v for k, v in columns.items()}
        conn.execute(f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", tuple(columns.values()))
        for key, ids in people.items():
            _apply_lists(conn, task_id, key, ids)
        _apply_lists(conn, task_id, "labels", label_names)
        _apply_references(conn, task_id, {}, _references(references))
        conn.executemany("INSERT INTO task_parents (child, parent) VALUES (?, ?)", [(task_id, p) for p in dict.fromkeys(parents)])
        capacity.rebuild_task(conn, task_id, at.date(), settings)
    return task_id


# ---- changing ----
def get_task(conn: sqlite3.Connection, task_id: str) -> Task:
    task = load_tasks(conn, [task_id]).get(task_id)
    if task is None:
        raise TaskError(f"There's no task {task_id}.")
    return task


def update_task(conn: sqlite3.Connection, settings: Settings, task_id: str, *, at: datetime, via: str, **changes: Any) -> list[Change]:
    """Change a task's fields. Fields not given stay as they are. Returns what changed, as logged.

    Closing a task records the day it closed; reopening clears it. Clearing the
    recurrence clears Repeat until too.
    """
    unknown = sorted(set(changes) - set(FIELD_NAMES) - {REFERENCES})
    if unknown:
        raise TaskError(f"Not task fields: {', '.join(unknown)}.")
    with transaction(conn):
        task = get_task(conn, task_id)
        refs = _references(changes.pop(REFERENCES, None))
        new = {k: _normalize(conn, k, v) for k, v in changes.items()}
        if "recurrence" in new and not new["recurrence"]:
            new["repeat_until"] = None
        _check_repeat(new.get("recurrence", task.recurrence), new.get("repeat_until", task.repeat_until))
        logged: list[Change] = []
        columns: dict[str, Any] = {}
        for key, name in FIELDS:
            if key not in new or getattr(task, key) == new[key]:
                continue
            logged.append(Change(name, _shown(conn, key, getattr(task, key)), _shown(conn, key, new[key])))
            if key in ROLES or key == "labels":
                _apply_lists(conn, task_id, key, new[key])
            else:
                columns[key] = new[key]
        if "state" in columns:
            columns["closed"] = at.date().isoformat() if columns["state"] == "Closed" else None
        _apply_columns(conn, task_id, columns)
        logged += _apply_references(conn, task_id, task.references, refs)
        _log(conn, task_id, at, via, logged)
        capacity.rebuild_task(conn, task_id, at.date(), settings)
    return logged


def set_discarded(conn: sqlite3.Connection, settings: Settings, task_id: str, reason: str | None, *, at: datetime, via: str) -> Change:
    """Discard a task, with the reason (mods log round 1, M0021), or bring it back (``reason`` None). It's never deleted.
    The status log shows "Discarded" with the reason; the capacity calendar leaves a discarded task out."""
    with transaction(conn):
        t = get_task(conn, task_id)
        if bool(t.discarded) == bool(reason):
            raise TaskError(f"{t.title} is {'already' if t.discarded else 'not'} discarded.")
        conn.execute("UPDATE tasks SET discarded = ?, discard_reason = ? WHERE id = ?", (stamp(at) if reason else None, reason, task_id))
        change = Change("Discarded", t.discard_reason or None, reason)
        _log(conn, task_id, at, via, [change])
        capacity.rebuild_task(conn, task_id, at.date(), settings)
    return change


def record(conn: sqlite3.Connection, task_id: str, at: datetime, via: str, changes: list[Change]) -> None:
    """Put changes made outside ``update_task`` into the status log, such as a move on the Priorities board."""
    _log(conn, task_id, at, via, changes)


def _log(conn: sqlite3.Connection, task_id: str, at: datetime, via: str, changes: list[Change]) -> None:
    conn.executemany(
        "INSERT INTO status_log (task, at, field, from_value, to_value, via) VALUES (?, ?, ?, ?, ?, ?)",
        [(task_id, stamp(at), c.field, c.from_value, c.to_value, via) for c in changes],
    )


# ---- parent links ----
def parent_titles(conn: sqlite3.Connection, task_id: str) -> str | None:
    rows = conn.execute("SELECT t.title FROM task_parents p JOIN tasks t ON t.id = p.parent WHERE p.child = ? ORDER BY p.id", (task_id,))
    return "; ".join(r["title"] for r in rows) or None


def descendant_ids(conn: sqlite3.Connection, task_id: str) -> set[str]:
    rows = conn.execute(
        "WITH RECURSIVE d(id) AS (SELECT child FROM task_parents WHERE parent = ?"
        " UNION SELECT p.child FROM task_parents p JOIN d ON p.parent = d.id) SELECT id FROM d",
        (task_id,),
    )
    return {r["id"] for r in rows}


def add_parent(conn: sqlite3.Connection, task_id: str, parent_id: str, *, at: datetime, via: str) -> Change:
    """Put a task under another parent as well. A task can't end up under itself."""
    with transaction(conn):
        get_task(conn, task_id)
        get_task(conn, parent_id)
        if parent_id == task_id or parent_id in descendant_ids(conn, task_id):
            raise TaskError("That would put the task under itself.")
        if conn.execute("SELECT 1 FROM task_parents WHERE child = ? AND parent = ?", (task_id, parent_id)).fetchone():
            raise TaskError(f"{task_id} is already under {parent_id}.")
        before = parent_titles(conn, task_id)
        conn.execute("INSERT INTO task_parents (child, parent) VALUES (?, ?)", (task_id, parent_id))
        change = Change("Parents", before, parent_titles(conn, task_id))
        _log(conn, task_id, at, via, [change])
    return change


def move_parent(conn: sqlite3.Connection, task_id: str, old_parent: str | None, new_parent: str | None, *, at: datetime, via: str) -> Change:
    """Move a task from under ``old_parent`` to under ``new_parent``, as one change. Its other parent links stay.

    ``old_parent`` None adds a parent to a top-level task; ``new_parent`` None makes the task top-level (if
    ``old_parent`` was its only parent). A task can't end up under itself.
    """
    with transaction(conn):
        get_task(conn, task_id)
        before = parent_titles(conn, task_id)
        if old_parent is not None:
            cur = conn.execute("DELETE FROM task_parents WHERE child = ? AND parent = ?", (task_id, old_parent))
            if cur.rowcount == 0:
                raise TaskError(f"{task_id} isn't under {old_parent}.")
        if new_parent is not None:
            get_task(conn, new_parent)
            if new_parent == task_id or new_parent in descendant_ids(conn, task_id):
                raise TaskError("That would put the task under itself.")
            if conn.execute("SELECT 1 FROM task_parents WHERE child = ? AND parent = ?", (task_id, new_parent)).fetchone():
                raise TaskError(f"{task_id} is already under {new_parent}.")
            conn.execute("INSERT INTO task_parents (child, parent) VALUES (?, ?)", (task_id, new_parent))
        change = Change("Parents", before, parent_titles(conn, task_id))
        if change.from_value != change.to_value:
            _log(conn, task_id, at, via, [change])
    return change


def set_parents(conn: sqlite3.Connection, task_id: str, parents: Sequence[str], *, at: datetime, via: str) -> Change | None:
    """Put a task under exactly these parents (none makes it top-level), as one change. Returns it, or None if nothing changed.
    A task can't end up under itself."""
    parents = list(dict.fromkeys(parents))
    with transaction(conn):
        get_task(conn, task_id)
        below = descendant_ids(conn, task_id)
        for p in parents:
            get_task(conn, p)
            if p == task_id or p in below:
                raise TaskError("That would put the task under itself.")
        current = [r["parent"] for r in conn.execute("SELECT parent FROM task_parents WHERE child = ? ORDER BY id", (task_id,))]
        if current == parents:
            return None
        before = parent_titles(conn, task_id)
        conn.execute("DELETE FROM task_parents WHERE child = ?", (task_id,))
        conn.executemany("INSERT INTO task_parents (child, parent) VALUES (?, ?)", [(task_id, p) for p in parents])
        change = Change("Parents", before, parent_titles(conn, task_id))
        _log(conn, task_id, at, via, [change])
    return change


def remove_parent(conn: sqlite3.Connection, task_id: str, parent_id: str, *, at: datetime, via: str) -> Change:
    """Take a task out from under one parent. With no parents left, it becomes a top-level task."""
    with transaction(conn):
        before = parent_titles(conn, task_id)
        cur = conn.execute("DELETE FROM task_parents WHERE child = ? AND parent = ?", (task_id, parent_id))
        if cur.rowcount == 0:
            raise TaskError(f"{task_id} isn't under {parent_id}.")
        change = Change("Parents", before, parent_titles(conn, task_id))
        _log(conn, task_id, at, via, [change])
    return change


# ---- key dates (release 5.31, the key dates plan) ----
@dataclass
class KeyDateRow:
    """A key date as a form or a capture has it: its ID when it's one already (None for a new one), its dates as
    YYYY-MM-DD or None, its description, and its ticks."""

    start: str | None
    end: str | None
    description: str = ""
    plant: bool = False
    deadline: bool = False
    done: bool = False
    id: int | None = None


def _key_date(row: KeyDateRow, task_id: str, done: str | None, pos: int, key_id: int = 0):
    from docrepo.model import KeyDate

    return KeyDate(key_id, task_id, row.start or None, row.end or None, " ".join(row.description.split()), row.plant, row.deadline, done, pos)


def set_key_dates(conn: sqlite3.Connection, task_id: str, rows: Sequence[KeyDateRow], *, at: datetime, via: str) -> list[Change]:
    """Make a task's key dates these, in this order: new ones added, changed ones changed, those left out taken off, a
    Done tick set or cleared. Each is logged ("Key date", or "Key date done"); a new order alone isn't. Returns what was."""
    from docrepo import key_dates

    for row in rows:
        p = key_dates.problem(row.start, row.end)
        if p:
            raise TaskError(p)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
            raise TaskError(f"There's no task {task_id}.")
        old = {r["id"]: r for r in conn.execute("SELECT * FROM task_dates WHERE task = ?", (task_id,))}
        logged: list[Change] = []
        kept: set[int] = set()
        day = at.date().isoformat()
        for pos, row in enumerate(rows):
            before = old.get(row.id) if row.id is not None else None
            if before is None:
                kd = _key_date(row, task_id, day if row.done else None, pos)
                conn.execute("INSERT INTO task_dates (task, start_day, end_day, description, plant, deadline, done, pos) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (task_id, kd.start, kd.end, kd.description, int(kd.plant), int(kd.deadline), kd.done, pos))
                logged.append(Change("Key date", None, key_dates.log_text(kd)))
                if kd.done:
                    logged.append(Change("Key date done", None, key_dates.log_text(kd)))
                continue
            kept.add(before["id"])
            was = _key_date(KeyDateRow(before["start_day"], before["end_day"], before["description"], bool(before["plant"]),
                                       bool(before["deadline"])), task_id, before["done"], before["pos"], before["id"])
            done = (before["done"] or day) if row.done else None
            kd = _key_date(row, task_id, done, pos, before["id"])
            conn.execute("UPDATE task_dates SET start_day = ?, end_day = ?, description = ?, plant = ?, deadline = ?, done = ?, pos = ? WHERE id = ?",
                         (kd.start, kd.end, kd.description, int(kd.plant), int(kd.deadline), kd.done, pos, kd.id))
            if key_dates.log_text(was) != key_dates.log_text(kd):
                logged.append(Change("Key date", key_dates.log_text(was), key_dates.log_text(kd)))
            if bool(was.done) != bool(kd.done):
                logged.append(Change("Key date done", None if kd.done else key_dates.log_text(kd), key_dates.log_text(kd) if kd.done else None))
        for key_id, r in old.items():
            if key_id not in kept:
                conn.execute("DELETE FROM task_dates WHERE id = ?", (key_id,))
                was = _key_date(KeyDateRow(r["start_day"], r["end_day"], r["description"], bool(r["plant"]), bool(r["deadline"])),
                                task_id, r["done"], r["pos"], key_id)
                logged.append(Change("Key date", key_dates.log_text(was), None))
        _log(conn, task_id, at, via, logged)
    return logged


def key_date_rows(conn: sqlite3.Connection, task_id: str) -> list[KeyDateRow]:
    """A task's key dates as rows, in its order, to change some and give them all back to ``set_key_dates``."""
    return [KeyDateRow(r["start_day"], r["end_day"], r["description"], bool(r["plant"]), bool(r["deadline"]), bool(r["done"]), r["id"])
            for r in conn.execute("SELECT * FROM task_dates WHERE task = ? ORDER BY pos, id", (task_id,))]


def add_key_dates(conn: sqlite3.Connection, task_id: str, rows: Sequence[KeyDateRow], *, at: datetime, via: str) -> list[Change]:
    """Add key dates at the end of a task's own, as a capture's ``**date`` lines do. Returns what was logged."""
    return set_key_dates(conn, task_id, [*key_date_rows(conn, task_id), *rows], at=at, via=via)


def set_key_date_done(conn: sqlite3.Connection, key_id: int, done: bool, *, at: datetime, via: str) -> tuple[str, list[Change]]:
    """Tick or untick a key date's Done (decision 148): from Today, the list, the task page or a form. Returns its task and
    what was logged."""
    r = conn.execute("SELECT task FROM task_dates WHERE id = ?", (key_id,)).fetchone()
    if r is None:
        raise TaskError(f"There's no key date {key_id}.")
    rows = key_date_rows(conn, r["task"])
    for row in rows:
        if row.id == key_id:
            row.done = done
    return r["task"], set_key_dates(conn, r["task"], rows, at=at, via=via)
