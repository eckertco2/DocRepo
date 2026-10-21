"""Agenda items: temporary links that put a task, or a note with no task, on the agenda of a meeting,
another task or a person (the agenda target). An item stays open, carrying over from meeting to meeting,
until it's closed by hand as Discussed or Removed. Closing an item never closes its task.

Today (mods log round 1, M0016) is a built-in target, ``TODAY``: the owner's list for the day. Its items
carry over the same way until they're closed as Done (or Removed), and a task is on it at most once.

The subject task's status log shows each item as it's added and closed; that's derived from this table.
"""
from __future__ import annotations

import sqlite3

from docrepo.db import transaction
from docrepo.model import TODAY, is_person

HOW = ("Discussed", "Removed")
#: How a Today item closes.
TODAY_HOW = ("Done", "Removed")


class AgendaError(ValueError):
    """An agenda item can't be added or closed as asked."""


def _exists(conn: sqlite3.Connection, table: str, item_id: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (item_id,)).fetchone() is not None


def add_item(conn: sqlite3.Connection, *, subject: str | None, target: str, note: str, added: str, added_by: str) -> int:
    """Put ``subject`` (a task ID), or the note alone, on ``target``'s agenda. ``added`` is a stored time.
    A task already open on Today isn't added again: its item's number is returned."""
    if not subject and not note.strip():
        raise AgendaError("An agenda item needs a task or a note.")
    if subject and not _exists(conn, "tasks", subject):
        raise AgendaError(f"There's no task {subject}.")
    if target != TODAY and not _exists(conn, "people" if is_person(target) else "tasks", target):
        raise AgendaError(f"There's no agenda target {target}.")
    if subject == target:
        raise AgendaError("A task can't be on its own agenda.")
    with transaction(conn):
        if target == TODAY and subject:
            row = conn.execute("SELECT id FROM agenda_items WHERE target = ? AND subject = ? AND closed IS NULL", (TODAY, subject)).fetchone()
            if row:
                return int(row["id"])
        cur = conn.execute(
            "INSERT INTO agenda_items (subject, target, note, added, added_by) VALUES (?, ?, ?, ?, ?)",
            (subject, target, note, added, added_by),
        )
    return int(cur.lastrowid)


def close_item(conn: sqlite3.Connection, item_id: int, *, how: str, closed: str, closed_by: str) -> None:
    """Close an open agenda item as Discussed or Removed, or a Today item as Done or Removed."""
    with transaction(conn):
        row = conn.execute("SELECT target, closed FROM agenda_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise AgendaError(f"There's no agenda item {item_id}.")
        allowed = TODAY_HOW if row["target"] == TODAY else HOW
        if how not in allowed:
            raise AgendaError(f"{'A Today item' if row['target'] == TODAY else 'An agenda item'} closes as {' or '.join(allowed)}, not {how!r}.")
        if row["closed"]:
            raise AgendaError(f"Agenda item {item_id} is already closed.")
        conn.execute("UPDATE agenda_items SET closed = ?, how = ?, closed_by = ? WHERE id = ?", (closed, how, closed_by, item_id))
