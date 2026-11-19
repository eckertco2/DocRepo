"""Agenda items: temporary links that put a task, or a note with no task, on the agenda of a meeting,
another task or a person (the agenda target). An item stays open, carrying over from meeting to meeting,
until it's closed by hand as Discussed or Removed. Closing an item never closes its task.

Today (mods log round 1, M0016) is a built-in target, ``TODAY``: the owner's list for the day. Its items
carry over the same way until they're closed as Done (or Removed), and a task is on it at most once.

Since release 5.148 (the design workspace's ``docs/mods/today-order-plan.md``, decisions 643 to 648) Today is in the
owner's order: each open item's ``pos``, empty until the first move, then set for every open item at once, so the
order shown is the order kept. A new item, and one put back with Back on Today, goes after the last. A move changes
no task, so it goes in no status log, and it has no Undo: it's moved back the same way.

The subject task's status log shows each item as it's added and closed; that's derived from this table.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from docrepo.db import check_names, transaction
from docrepo.model import TODAY, is_person

HOW = ("Discussed", "Removed")
#: How a Today item closes.
TODAY_HOW = ("Done", "Removed")
#: How a list's open items are ordered (decision 647), as ``model.place_key`` orders them: by their places, then any
#: without one by when they were added.
ORDER = "pos IS NULL, coalesce(pos, 0), added, id"


class AgendaError(ValueError):
    """An agenda item can't be added or closed as asked."""


#: Why a collection isn't put on Today (release 5.167, decision 780): it isn't work. Every way onto Today comes here.
COLLECTION_NOT_ON_TODAY = "{title} is a collection, not a task, so it isn't put on Today."


def is_collection(conn: sqlite3.Connection, task_id: str) -> bool:
    """Whether a task tree entry is a collection (release 5.167)."""
    row = conn.execute("SELECT collection FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return bool(row and row[0])


#: The tables an agenda item's subject or target can be in.
_TARGET_TABLES = ("tasks", "people")


def _exists(conn: sqlite3.Connection, table: str, item_id: str) -> bool:
    """True when ``table`` (tasks or people) holds ``item_id``."""
    check_names(table, _TARGET_TABLES)
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (item_id,)).fetchone() is not None  # noqa: S608 - a column or table name of DocRepo's own; values are parameters


def add_item(conn: sqlite3.Connection, *, subject: str | None, target: str, note: str, added: str, added_by: str) -> int:
    """Put ``subject`` (a task ID), or the note alone, on ``target``'s agenda. ``added`` is a stored time.
    A task already open on Today isn't added again: its item's number is returned. Once the list has an order of the
    owner's, a new item goes after the last (release 5.148, decision 645); until then it's last as the newest."""
    if not subject and not note.strip():
        raise AgendaError("An agenda item needs a task or a note.")
    if subject and not _exists(conn, "tasks", subject):
        raise AgendaError(f"There's no task {subject}.")
    if target != TODAY and not _exists(conn, "people" if is_person(target) else "tasks", target):
        raise AgendaError(f"There's no agenda target {target}.")
    if subject == target:
        raise AgendaError("A task can't be on its own agenda.")
    if target == TODAY and subject and is_collection(conn, subject):
        raise AgendaError(COLLECTION_NOT_ON_TODAY.format(title=conn.execute("SELECT title FROM tasks WHERE id = ?", (subject,)).fetchone()[0]))
    with transaction(conn):
        if target == TODAY and subject:
            row = conn.execute("SELECT id FROM agenda_items WHERE target = ? AND subject = ? AND closed IS NULL", (TODAY, subject)).fetchone()
            if row:
                return int(row["id"])
        cur = conn.execute(
            "INSERT INTO agenda_items (subject, target, note, added, added_by, pos) VALUES (?, ?, ?, ?, ?, ?)",
            (subject, target, note, added, added_by, _after_last(conn, target)),
        )
    return int(cur.lastrowid)


def _open_note(conn: sqlite3.Connection, item_id: int) -> None:
    row = conn.execute("SELECT subject, closed FROM agenda_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise AgendaError(f"There's no agenda item {item_id}.")
    if row["subject"] or row["closed"]:
        raise AgendaError(f"Agenda item {item_id} isn't an open note.")


def set_note(conn: sqlite3.Connection, item_id: int, note: str) -> None:
    """Change an open note's text (mods log round 2, M0040)."""
    if not note.strip():
        raise AgendaError("A note needs some text.")
    with transaction(conn):
        _open_note(conn, item_id)
        conn.execute("UPDATE agenda_items SET note = ? WHERE id = ?", (" ".join(note.split()), item_id))


def make_task(conn: sqlite3.Connection, item_id: int, task_id: str) -> None:
    """Make it a task (mods log round 2, M0040): an open note becomes an item for ``task_id``, made from its text. It keeps
    when it was added, so it still carries over from that day, and its place on the list."""
    with transaction(conn):
        _open_note(conn, item_id)
        if not _exists(conn, "tasks", task_id):
            raise AgendaError(f"There's no task {task_id}.")
        conn.execute("UPDATE agenda_items SET subject = ?, note = '' WHERE id = ?", (task_id, item_id))


def close_item(conn: sqlite3.Connection, item_id: int, *, how: str, closed: str, closed_by: str) -> None:
    """Close an open agenda item as Discussed or Removed, or a Today item as Done or Removed. It keeps its place, so Undo
    puts it back where it was."""
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


def reopen_item(conn: sqlite3.Connection, item_id: int, *, at_end: bool = False) -> None:
    """Undo a close (release 5.91): the item is open again, as it was, in its place. Its task's status log reads the
    agenda's own rows, so the closing line goes with it. ``at_end``: Back on Today's (release 5.148, decision 645), which
    puts it after the last instead, as a new item goes, giving every open item its place if they had none."""
    with transaction(conn):
        row = conn.execute("SELECT target, closed FROM agenda_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise AgendaError(f"There's no agenda item {item_id}.")
        if not row["closed"]:
            raise AgendaError(f"Agenda item {item_id} is open already.")
        conn.execute("UPDATE agenda_items SET closed = NULL, how = NULL, closed_by = NULL WHERE id = ?", (item_id,))
        if at_end:
            order = [i for i in order_of(conn, row["target"]) if i != item_id]
            _place(conn, [*order, item_id])


# ---- the owner's order (release 5.148, decisions 643 to 647) ----
def order_of(conn: sqlite3.Connection, target: str = TODAY) -> list[int]:
    """A list's open items, by number, in its order: Today's as the owner put them."""
    return [int(r["id"]) for r in conn.execute(f"SELECT id FROM agenda_items WHERE target = ? AND closed IS NULL ORDER BY {ORDER}", (target,))]  # noqa: S608 - ORDER is DocRepo's own; values are parameters


def _after_last(conn: sqlite3.Connection, target: str) -> int | None:
    """The place after a list's last, once its items have places; None while they have none."""
    last = conn.execute("SELECT max(pos) FROM agenda_items WHERE target = ? AND closed IS NULL", (target,)).fetchone()[0]
    return None if last is None else int(last) + 1


def _place(conn: sqlite3.Connection, ids: Sequence[int]) -> None:
    for pos, item_id in enumerate(ids, start=1):
        conn.execute("UPDATE agenda_items SET pos = ? WHERE id = ?", (pos, item_id))


def place_items(conn: sqlite3.Connection, ids: Sequence[int], target: str = TODAY) -> None:
    """Put a list's open items in this order, the first at the top, giving each its place (decision 647). ``ids`` must be
    every open item of the list, each once, so nothing is left without a place."""
    with transaction(conn):
        now = order_of(conn, target)
        if len(ids) != len(set(ids)) or set(ids) != set(now):
            raise AgendaError("The list has changed since it was shown. Try again.")
        _place(conn, ids)


def move_item(conn: sqlite3.Connection, item_id: int, to: int) -> list[int]:
    """Move an open item to the ``to``-th place of its list (0 is the top; past the end is the bottom), giving every open
    item its place, as the first drag does. Alt+Up and Alt+Down, Move to top and Move to bottom, and a drag (``move_beside``)
    come here. Returns the new order."""
    with transaction(conn):
        row = conn.execute("SELECT target, closed FROM agenda_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise AgendaError(f"There's no agenda item {item_id}.")
        if row["closed"]:
            raise AgendaError(f"Agenda item {item_id} is closed, so it has no place to move from.")
        order = [i for i in order_of(conn, row["target"]) if i != item_id]
        to = max(0, min(len(order), to))
        order.insert(to, item_id)
        _place(conn, order)
    return order


def move_beside(conn: sqlite3.Connection, item_id: int, other: int, where: str) -> list[int]:
    """A drag's drop (decision 643): ``item_id`` put just "before" or "after" ``other``, an open item of the same list."""
    if where not in ("before", "after"):
        raise AgendaError(f"An item goes before or after another, not {where!r}.")
    with transaction(conn):
        rows = {int(r["id"]): r for r in conn.execute("SELECT id, target, closed FROM agenda_items WHERE id IN (?, ?)", (item_id, other))}
        if item_id not in rows or other not in rows or rows[other]["closed"] or rows[item_id]["target"] != rows[other]["target"]:
            raise AgendaError("An item moves only beside another open item of its own list.")
        if item_id == other:
            return order_of(conn, rows[item_id]["target"])
        order = [i for i in order_of(conn, rows[item_id]["target"]) if i != item_id]
        return move_item(conn, item_id, order.index(other) + (where == "after"))


def can_move_beside(conn: sqlite3.Connection, item_id: int, other: int) -> bool:
    """Whether a drag of ``item_id`` may land beside ``other``: both open, on the same list."""
    rows = list(conn.execute("SELECT target FROM agenda_items WHERE id IN (?, ?) AND closed IS NULL", (item_id, other)))
    return item_id != other and len(rows) == 2 and rows[0]["target"] == rows[1]["target"]
