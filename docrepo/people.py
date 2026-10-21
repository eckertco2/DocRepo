"""The people list and the labels.

People have stable IDs (P001), so renaming someone changes nothing else. Retired
people and labels are hidden from pickers but never deleted.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from docrepo.db import next_id, note_used_id, transaction

STATUSES = ("active", "retired")
_UNSET: object = object()


class PeopleError(ValueError):
    """A person or label change that isn't allowed."""


def _clean(name: str, what: str) -> str:
    name = name.strip()
    if not name:
        raise PeopleError(f"A {what} needs a name.")
    return name


def _check_hours(hours: float | None) -> float | None:
    if hours is not None and hours < 0:
        raise PeopleError("Hours a week can't be negative.")
    return hours


def _set_list(conn: sqlite3.Connection, table: str, key: str, owner: object, column: str, values: Sequence[str]) -> None:
    conn.execute(f"DELETE FROM {table} WHERE {key} = ?", (owner,))
    conn.executemany(f"INSERT INTO {table} ({key}, pos, {column}) VALUES (?, ?, ?)",
                     [(owner, i, v.strip()) for i, v in enumerate(values) if v.strip()])


def add_person(
    conn: sqlite3.Connection, name: str, *, aliases: Sequence[str] = (), hours: float | None = None,
    added_note: str | None = None, status: str = "active", person_id: str | None = None,
) -> str:
    """Add someone to the people list. Returns their ID."""
    name = _clean(name, "person")
    if status not in STATUSES:
        raise PeopleError(f"Unknown status {status!r}.")
    with transaction(conn):
        if person_id:
            note_used_id(conn, person_id)
        else:
            person_id = next_id(conn, "P")
        conn.execute("INSERT INTO people (id, name, hours_per_week, status, added_note) VALUES (?, ?, ?, ?, ?)",
                     (person_id, name, _check_hours(hours), status, added_note))
        _set_list(conn, "person_aliases", "person", person_id, "alias", aliases)
    return person_id


def find_or_add(conn: sqlite3.Connection, name: str, added_note: str) -> tuple[str, bool]:
    """The person with this name (any case), or someone new added with ``added_note``. Returns (their ID, whether they're new)."""
    row = conn.execute("SELECT id FROM people WHERE lower(name) = lower(?)", (name.strip(),)).fetchone()
    if row:
        return str(row["id"]), False
    return add_person(conn, name, added_note=added_note), True


def update_person(
    conn: sqlite3.Connection, person_id: str, *, name: str | None = None, aliases: Sequence[str] | None = None,
    hours: float | None | object = _UNSET, status: str | None = None,
) -> None:
    """Change a person's name, aliases, hours a week or status. Only what's given changes."""
    with transaction(conn):
        if conn.execute("SELECT 1 FROM people WHERE id = ?", (person_id,)).fetchone() is None:
            raise PeopleError(f"There's no person {person_id}.")
        if name is not None:
            conn.execute("UPDATE people SET name = ? WHERE id = ?", (_clean(name, "person"), person_id))
        if aliases is not None:
            _set_list(conn, "person_aliases", "person", person_id, "alias", aliases)
        if hours is not _UNSET:
            new_hours = None if hours is None else float(hours)  # type: ignore[arg-type]
            conn.execute("UPDATE people SET hours_per_week = ? WHERE id = ?", (_check_hours(new_hours), person_id))
        if status is not None:
            if status not in STATUSES:
                raise PeopleError(f"Unknown status {status!r}.")
            conn.execute("UPDATE people SET status = ? WHERE id = ?", (status, person_id))


def add_label(conn: sqlite3.Connection, name: str, keywords: Sequence[str] = ()) -> int:
    """Add a label. With no keywords given, its name is its first keyword. Returns its number."""
    name = _clean(name, "label")
    with transaction(conn):
        if conn.execute("SELECT 1 FROM labels WHERE name = ?", (name,)).fetchone():
            raise PeopleError(f"There's already a label called {name}.")
        label_id = int(conn.execute("INSERT INTO labels (name) VALUES (?)", (name,)).lastrowid)
        _set_list(conn, "label_keywords", "label", label_id, "keyword", list(keywords) or [name])
    return label_id


def label_id(conn: sqlite3.Connection, name: str) -> int:
    """A label's number, found by name (any case)."""
    row = conn.execute("SELECT id FROM labels WHERE name = ?", (name.strip(),)).fetchone()
    if row is None:
        raise PeopleError(f"There's no label called {name}.")
    return int(row["id"])


def update_label(
    conn: sqlite3.Connection, name: str, *, new_name: str | None = None, keywords: Sequence[str] | None = None, status: str | None = None
) -> None:
    """Rename a label, change its keywords, or retire it. Tasks keep it under its new name."""
    with transaction(conn):
        number = label_id(conn, name)
        if new_name is not None:
            new_name = _clean(new_name, "label")
            clash = conn.execute("SELECT id FROM labels WHERE name = ? AND id <> ?", (new_name, number)).fetchone()
            if clash:
                raise PeopleError(f"There's already a label called {new_name}.")
            conn.execute("UPDATE labels SET name = ? WHERE id = ?", (new_name, number))
        if keywords is not None:
            _set_list(conn, "label_keywords", "label", number, "keyword", keywords)
        if status is not None:
            if status not in STATUSES:
                raise PeopleError(f"Unknown status {status!r}.")
            conn.execute("UPDATE labels SET status = ? WHERE id = ?", (status, number))
