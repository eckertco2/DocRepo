"""Creating and changing tasks: their fields, people, labels and parent links.

Every change to an existing task goes into its status log, with the old and new
values as they're shown and where the change came from (a capture's ID, or
"Browse tool", "Capture window" and so on). The task's rows in the capacity
calendar are rebuilt in the same transaction, so the calendar always matches.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docrepo import capacity
from docrepo.config import Settings
from docrepo.dates import check_date, stamp, to_date, workday_numbers
from docrepo.db import RECURRENCES, STATES, next_id, transaction
from docrepo.model import Task, load_tasks
from docrepo.pages import num
from docrepo.schedule import days_in, due_after, length_of, placed, week_of

#: The fields a change can set, with their names in the status log, in the order the log lists them.
FIELDS = (
    ("state", "State"), ("current_status", "Current status"), ("due", "Due"), ("deadline", "Deadline"),
    ("deadline_desc", "Deadline description"), ("duration", "Duration"), ("calendar_days", "Runs through weekends"), ("leads", "Lead"),
    ("assignees", "Assignees"), ("lead_per_day", "Lead hours a day"), ("assignee_per_day", "Assignee hours a day"), ("lead_per_week", "Lead hours a week"),
    ("assignee_per_week", "Assignee hours a week"), ("lead_hours", "Lead hours"),
    ("assignee_hours", "Assignee hours"), ("urgent", "Urgent"), ("meeting", "Meeting"), ("plant_event", "Plant event"), ("start", "Start"),
    ("reminder", "Reminder"), ("recurrence", "Recurrence"), ("repeat_until", "Repeat until"), ("title", "Title"),
    ("description", "Description"), ("labels", "Labels"), ("inherit_labels", "Inherit parent labels"),
)
FIELD_NAMES = dict(FIELDS)
DATE_FIELDS = ("due", "deadline", "start", "reminder", "repeat_until")
TEXT_FIELDS = ("title", "current_status", "deadline_desc", "description")
FLAG_FIELDS = ("urgent", "meeting", "inherit_labels", "plant_event", "calendar_days")
#: Reference fields (mods log round 2, M0034, release 5.9): named in Settings, each logged under its own name.
REFERENCES = "references"
#: Each person's Involvement (release 5.47, decision 196): {(role, person): percent}. Logged under the person's name.
INVOLVEMENT = "involvement"
#: A link to a template ending or starting, in the status log (release 5.44): its value is the whole sentence.
TEMPLATE_LINK = "Template link"
HOUR_FIELDS = ("lead_hours", "assignee_hours", "lead_per_day", "assignee_per_day", "lead_per_week", "assignee_per_week")
#: Each role's total and its rates (release 5.46, decision 189; release 5.49, decision 260). A role has one rate at most, and with
#: one the total is worked out from it and the task's days.
RATES = {"lead_hours": "lead_per_day", "assignee_hours": "assignee_per_day"}
WEEK_RATES = {"lead_hours": "lead_per_week", "assignee_hours": "assignee_per_week"}
RATE_FIELDS = (*RATES.values(), *WEEK_RATES.values())
ROLES = {"leads": "lead", "assignees": "assignee"}
_RATE_FIELD = {rate: hours for hours, rate in (*RATES.items(), *WEEK_RATES.items())}  # a rate's change is a change to the hours it states


class TaskError(ValueError):
    """A task change that isn't allowed, such as an unknown person or a parent link that would make a loop."""


@dataclass(frozen=True)
class Change:
    """One status log entry: a field, and its value before and after, as shown. None shows as "None"."""

    field: str
    from_value: str | None
    to_value: str | None


# ---- checking values ----
def stated(item: Any, key: str) -> Any:
    """A linked field's value on a task or a template row, as it was stated: hours are their rate when there is one, since
    the total worked out from it follows the task's days (decision 189)."""
    if key in RATES and getattr(item, RATES[key]) is not None:
        return ("a day", getattr(item, RATES[key]))
    if key in WEEK_RATES and getattr(item, WEEK_RATES[key]) is not None:
        return ("a week", getattr(item, WEEK_RATES[key]))
    if key in ROLES:  # the people, each with their Involvement: one field for each role (the design's table)
        return [(p, item.involvement.get((ROLES[key], p), 100)) for p in getattr(item, key)]
    return getattr(item, key)


def _normalize(conn: sqlite3.Connection, key: str, value: Any) -> Any:
    if key == "duration":
        if value is None or value == "":
            return None
        try:
            days = float(value)
        except (TypeError, ValueError):
            days = 0.0
        if days < 1 or not days.is_integer():
            raise TaskError("Duration is a whole number of days, 1 or more.")
        return int(days)
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
    if key == "duration":
        return None if value is None else str(value)
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


def shares_of(value: Any) -> dict[tuple[str, str], int]:
    """Involvement as it's kept: whole numbers from 0 to 100, with 100 left out, as it's the default."""
    out: dict[tuple[str, str], int] = {}
    for key, percent in dict(value or {}).items():
        try:
            share = float(percent)
        except (TypeError, ValueError):
            share = -1.0
        if not 0 <= share <= 100 or not share.is_integer():
            raise TaskError("Involvement is a whole number from 0 to 100.")
        if share != 100:
            out[tuple(key)] = int(share)
    return out


def _apply_involvement(conn: sqlite3.Connection, task_id: str, people: dict[str, list[str]], before: dict[tuple[str, str], int],
                       wanted: dict[tuple[str, str], int]) -> tuple[list[Change], list[str]]:
    """Set each person's Involvement, as ``_apply_lists`` makes their rows afresh. Someone taken off loses theirs. Returns a
    line for each that changed, "Tom Becker's involvement 100% → 25%", and the roles it changed in."""
    conn.execute("UPDATE task_people SET involvement = 100 WHERE task = ?", (task_id,))
    logged: list[Change] = []
    roles: list[str] = []
    for key, role in ROLES.items():
        for p in people[key]:
            old, new = before.get((role, p), 100), wanted.get((role, p), 100)
            if new != 100:
                conn.execute("UPDATE task_people SET involvement = ? WHERE task = ? AND person = ? AND role = ?", (new, task_id, p, role))
            if old != new:
                name = conn.execute("SELECT name FROM people WHERE id = ?", (p,)).fetchone()["name"]
                logged.append(Change(f"{name}'s involvement", f"{old}%", f"{new}%"))
                roles.append(key)
    return logged, roles


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


def template_name(conn: sqlite3.Connection, task_id: str) -> str | None:
    """The name of the template a task was made from: its top row's title (release 5.44)."""
    r = conn.execute("SELECT top.title FROM task_template x JOIN template_rows r ON r.id = x.row_id "
                     "JOIN template_rows top ON top.template = r.template AND top.parent IS NULL WHERE x.task = ?", (task_id,)).fetchone()
    return r["title"] if r else None


def _linked_fields(conn: sqlite3.Connection, task_id: str) -> set[str]:
    return {r["field"] for r in conn.execute("SELECT field FROM task_links WHERE task = ?", (task_id,))}


def _end_links(conn: sqlite3.Connection, task_id: str, changed: Sequence[str]) -> list[Change]:
    """A linked field given a different value stops following its template, and says so (decision 184). Every change to a
    task's fields comes through ``update_task``, so the rule is here once."""
    linked = _linked_fields(conn, task_id) & set(changed)
    if not linked:
        return []
    name = template_name(conn, task_id)
    conn.executemany("DELETE FROM task_links WHERE task = ? AND field = ?", [(task_id, k) for k in linked])
    return [Change(TEMPLATE_LINK, f"{FIELD_NAMES[k]}: no longer follows {name}", None) for k, _ in FIELDS if k in linked]


def _row_values(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    """What a task's template row states, under the task's field names."""
    r = conn.execute("SELECT r.* FROM task_template x JOIN template_rows r ON r.id = x.row_id WHERE x.task = ?", (task_id,)).fetchone()
    if r is None:
        return {}
    values: dict[str, Any] = {k: r[k] for k in ("title", "description", "recurrence", "duration")}
    values.update({k: bool(r[k]) for k in ("inherit_labels", "urgent", "meeting", "plant_event", "calendar_days")})
    values.update({hours: ("a day", r[RATES[hours]]) if r[RATES[hours]] is not None else ("a week", r[WEEK_RATES[hours]]) if r[WEEK_RATES[hours]] is not None else r[hours]
                   for hours in RATES})
    for key, role in ROLES.items():
        values[key] = [(p["person"], p["involvement"]) for p in conn.execute(
            "SELECT person, involvement FROM template_row_people WHERE row_id = ? AND role = ? ORDER BY id", (r["id"], role))]
    values["labels"] = [x["name"] for x in conn.execute("SELECT l.name FROM template_row_labels x JOIN labels l ON l.id = x.label WHERE x.row_id = ? ORDER BY x.id", (r["id"],))]
    return values


def _fallen_behind(conn: sqlite3.Connection, task_id: str, while_: str) -> list[Change]:
    """A closed or discarded task never changes, so a linked field can fall behind its template. When the task comes back,
    each such field becomes its own, with the template's value offered by Edit task's ↺, so its hours don't jump (decision 185)."""
    linked = _linked_fields(conn, task_id)
    if not linked:
        return []
    row, task = _row_values(conn, task_id), get_task(conn, task_id)
    behind = {k for k in linked if k in row and stated(task, k) != row[k]}
    if not behind:
        return []
    name = template_name(conn, task_id)
    conn.executemany("DELETE FROM task_links WHERE task = ? AND field = ?", [(task_id, k) for k in behind])
    return [Change(TEMPLATE_LINK, f"{FIELD_NAMES[k]}: fell behind {name} while {while_}, and stays as it is", None) for k, _ in FIELDS if k in behind]


def set_links(conn: sqlite3.Connection, task_id: str, fields: Collection[str], *, at: datetime, via: str) -> list[Change]:
    """Make these the fields that follow a task's template, from Edit task's marks (decision 184). Each one it stops or starts
    following goes into the status log. Returns those."""
    name = template_name(conn, task_id)
    if name is None:
        return []
    had = _linked_fields(conn, task_id)
    logged = []
    for key, field_name in FIELDS:
        if key in had and key not in fields:
            conn.execute("DELETE FROM task_links WHERE task = ? AND field = ?", (task_id, key))
            logged.append(Change(TEMPLATE_LINK, f"{field_name}: no longer follows {name}", None))
        elif key in fields and key not in had:
            conn.execute("INSERT INTO task_links (task, field) VALUES (?, ?)", (task_id, key))
            logged.append(Change(TEMPLATE_LINK, None, f"{field_name}: follows {name} again"))
    _log(conn, task_id, at, via, logged)
    return logged


# ---- dates and hours (release 5.46, decisions 189 to 191; release 5.49, decision 260) ----
def hours_values(hours: str, unit: str, number: float | None) -> dict[str, Any]:
    """A role's hours as a change takes them: a rate, with the other cleared, or a total with no rate. ``unit`` is "all", "day"
    or "week", and with no number it's a total of nothing."""
    if number is not None and unit == "day":
        return {RATES[hours]: number, WEEK_RATES[hours]: None}
    if number is not None and unit == "week":
        return {WEEK_RATES[hours]: number, RATES[hours]: None}
    return {hours: number, RATES[hours]: None, WEEK_RATES[hours]: None}


def unit_span(unit: str, days: int, workdays: Collection[int], every_day: bool = False) -> float:
    """What a number in a unit is multiplied by to make the total, over a task's days: its days, or the weeks they make, part weeks
    included, as 7 workdays is 1.4 weeks. So switching a unit can keep the total."""
    return days if unit == "day" else days / week_of(workdays, every_day) if unit == "week" else 1


def rate_total(stated_rate: tuple[str, float], days: int | None, workdays: Collection[int], every_day: bool = False) -> float | None:
    """What ``("a week", 3)`` comes to over a task's days, or None until it has a length."""
    return round(stated_rate[1] * unit_span(stated_rate[0][2:], days, workdays, every_day), 2) if days else None


def worked_out(task: Task, changes: dict[str, Any], workdays: Collection[int], dragged: bool = False) -> tuple[dict[str, Any], set[str]]:
    """What a change to a task comes to, with its dates and totals following (the rules live here once, so every form, capture
    and drag keeps to them), and which fields were worked out rather than given.

    With a Duration, changing Start moves Due, changing Due moves Start, and changing the Duration or Runs through weekends
    moves Due, or Start if there's no Start. Clearing either date clears both. Two new dates typed together are the new length.
    ``dragged`` is Plan mode's: a bar moved, or an undated one dropped, keeps its days, and one with an end stretched takes the
    new length. A total typed over a rate ends the rate. With a rate, the total is the rate times the task's days, or none
    until it has a length. A routine task has no Duration and no rate: its hours are for each time."""
    new, calculated = dict(changes), set()
    if new.get("recurrence", task.recurrence):
        new.update(duration=None, calendar_days=False, **dict.fromkeys(RATE_FIELDS))
        return new, calculated
    for hours in RATES:
        day, week = RATES[hours], WEEK_RATES[hours]
        if new.get(day) is not None:
            new[week] = None
        elif new.get(week) is not None:
            new[day] = None
        elif hours in new and new[hours] != getattr(task, hours):
            new[day] = new[week] = None
    days, every = new.get("duration", task.duration), new.get("calendar_days", task.calendar_days)
    start, due = new.get("start", task.start), new.get("due", task.due)
    if days is not None:
        length_changed = days != task.duration or every != task.calendar_days
        start_changed, due_changed = start != task.start, due != task.due
        if (start_changed and not start) or (due_changed and not due):
            start, due = None, None
        elif length_changed:
            start, due = placed(start, due, days, "duration", workdays, every)
        elif start_changed and due_changed:
            if dragged:
                due = due_after(to_date(start), days, workdays, every).isoformat()
            elif to_date(due) >= to_date(start):
                days = days_in(to_date(start), to_date(due), workdays, every)
                new["duration"] = days
        elif dragged and (start_changed or due_changed):
            if start and due and to_date(due) >= to_date(start):
                days = days_in(to_date(start), to_date(due), workdays, every)
                new["duration"] = days
        elif start_changed or due_changed:
            start, due = placed(start, due, days, "start" if start_changed else "due", workdays, every)
        if start != new.get("start", task.start):
            new["start"] = start
            calculated.add("start")
        if due != new.get("due", task.due):
            new["due"] = due
            calculated.add("due")
    length = length_of(start, due, days, workdays, every)
    for hours in RATES:
        per_day, per_week = new.get(RATES[hours], getattr(task, RATES[hours])), new.get(WEEK_RATES[hours], getattr(task, WEEK_RATES[hours]))
        if per_day is not None or per_week is not None:
            new[hours] = rate_total(("a day", per_day) if per_day is not None else ("a week", per_week), length, workdays, every)
            calculated.add(hours)
    return new, calculated


def _blank_task(state: str) -> Task:
    """A task with nothing in it, to work out a new one's dates and totals from."""
    return Task("", "", state, None, False, False, None, None, None, None, None, None, None, None, None, True, "", "", "", "")


# ---- creating ----
def create_task(
    conn: sqlite3.Connection, settings: Settings, *, title: str, at: datetime, created_by: str,
    parents: Sequence[str] = (), description: str = "", state: str = "Not started", current_status: str = "",
    start: str | None = None, due: str | None = None, deadline: str | None = None, deadline_desc: str | None = None,
    reminder: str | None = None, recurrence: str | None = None, repeat_until: str | None = None,
    urgent: bool = False, meeting: bool = False, leads: Sequence[str] = (), assignees: Sequence[str] = (),
    lead_hours: float | None = None, assignee_hours: float | None = None, labels: Sequence[str] = (),
    inherit_labels: bool = True, plant_event: bool = False, references: dict[str, str] | None = None, duration: int | None = None,
    calendar_days: bool = False, lead_per_day: float | None = None, assignee_per_day: float | None = None,
    lead_per_week: float | None = None, assignee_per_week: float | None = None, involvement: dict[tuple[str, str], int] | None = None,
) -> str:
    """Create a task, under ``parents`` if any are given (a top-level task if not). Returns its ID.

    ``created_by`` is the capture that created it, or "Excel import" and so on.
    """
    values = {
        "title": title, "state": state, "current_status": current_status, "start": start, "due": due,
        "deadline": deadline, "deadline_desc": deadline_desc, "reminder": reminder, "recurrence": recurrence,
        "repeat_until": repeat_until, "urgent": urgent, "meeting": meeting, "lead_hours": lead_hours,
        "assignee_hours": assignee_hours, "inherit_labels": inherit_labels, "plant_event": plant_event, "duration": duration,
        "calendar_days": calendar_days, "lead_per_day": lead_per_day, "assignee_per_day": assignee_per_day,
        "lead_per_week": lead_per_week, "assignee_per_week": assignee_per_week,
    }
    with transaction(conn):
        values = {k: _normalize(conn, k, v) for k, v in values.items()}
        values, _ = worked_out(_blank_task(values["state"]), values, workday_numbers(settings.workdays))
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
        _apply_involvement(conn, task_id, people, {}, shares_of(involvement))
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


def update_task(conn: sqlite3.Connection, settings: Settings, task_id: str, *, at: datetime, via: str, keep_links: bool = False, dragged: bool = False,
                **changes: Any) -> list[Change]:
    """Change a task's fields. Fields not given stay as they are. Returns what changed, as logged.

    Closing a task records the day it closed; reopening clears it. Clearing the
    recurrence clears Repeat until too. Dates and totals follow by ``worked_out``, which has ``dragged``. A different value on a
    linked field ends its link, unless ``keep_links`` says the caller sees to them: a template's own change, or Edit task's
    marks. A total worked out from a rate is no different value: the rate is what's stated.
    """
    unknown = sorted(set(changes) - set(FIELD_NAMES) - {REFERENCES, INVOLVEMENT})
    if unknown:
        raise TaskError(f"Not task fields: {', '.join(unknown)}.")
    with transaction(conn):
        task = get_task(conn, task_id)
        refs = _references(changes.pop(REFERENCES, None))
        shares = changes.pop(INVOLVEMENT, None)
        new = {k: _normalize(conn, k, v) for k, v in changes.items()}
        if "recurrence" in new and not new["recurrence"]:
            new["repeat_until"] = None
        _check_repeat(new.get("recurrence", task.recurrence), new.get("repeat_until", task.repeat_until))
        new, calculated = worked_out(task, new, workday_numbers(settings.workdays), dragged)
        logged: list[Change] = []
        columns: dict[str, Any] = {}
        changed: list[str] = []
        for key, name in FIELDS:
            if key not in new or getattr(task, key) == new[key]:
                continue
            changed.append(key)
            logged.append(Change(name, _shown(conn, key, getattr(task, key)), _shown(conn, key, new[key])))
            if key in ROLES or key == "labels":
                _apply_lists(conn, task_id, key, new[key])
            else:
                columns[key] = new[key]
        if "state" in columns:
            columns["closed"] = at.date().isoformat() if columns["state"] == "Closed" else None
        _apply_columns(conn, task_id, columns)
        if shares is not None or any(k in ROLES for k in changed):  # someone kept on keeps their Involvement
            people = {k: new.get(k, getattr(task, k)) for k in ROLES}
            share_lines, share_roles = _apply_involvement(conn, task_id, people, task.involvement, task.involvement if shares is None else shares_of(shares))
            logged += share_lines
            changed += share_roles
        logged += _apply_references(conn, task_id, task.references, refs)
        if not keep_links:
            logged += _end_links(conn, task_id, list(dict.fromkeys(_RATE_FIELD.get(k, k) for k in changed if k not in calculated)))
        if task.state == "Closed" and columns.get("state", "Closed") != "Closed":
            logged += _fallen_behind(conn, task_id, "closed")
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
        behind = _fallen_behind(conn, task_id, "discarded") if t.discarded and t.state != "Closed" else []
        _log(conn, task_id, at, via, [change, *behind])
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
    """Add key dates at the end of a task's own, as a capture's ``**key date,`` lines do. Returns what was logged."""
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
