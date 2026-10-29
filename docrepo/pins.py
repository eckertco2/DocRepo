"""Pinned files and what was opened (release 5.35; the task overview design's decisions 159 and 160).

A task's **pins** are its key documents, in the owner's order (``task_pins``): first on its Task view's Overview, and a
Key documents line in its Task.md. **Uses** (``document_uses``) record each time a file was opened, shown in File
Explorer or had its path or link copied from DocRepo, for Recent, Last opened and the search's tie-breaks. Neither goes
into the status log: they're the owner's arrangement and habits, not the task's history. Both hold IDs and times only.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime

from docrepo.dates import stamp
from docrepo.db import transaction

ACTIONS = ("open", "show", "copy_path", "copy_link")


def pins_of(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """A task's pinned documents, in order."""
    return [r["document"] for r in conn.execute("SELECT document FROM task_pins WHERE task = ? ORDER BY pos", (task_id,))]


def _renumber(conn: sqlite3.Connection, task_id: str, docs: list[str]) -> None:
    conn.execute("DELETE FROM task_pins WHERE task = ?", (task_id,))
    conn.executemany("INSERT INTO task_pins (task, document, pos) VALUES (?, ?, ?)", [(task_id, d, i) for i, d in enumerate(docs)])


def set_pinned(conn: sqlite3.Connection, task_id: str, document_id: str, on: bool) -> bool:
    """Pin a document to a task (at the end) or take its pin off. Returns whether anything changed."""
    with transaction(conn):
        docs = pins_of(conn, task_id)
        if on == (document_id in docs):
            return False
        _renumber(conn, task_id, [*docs, document_id] if on else [d for d in docs if d != document_id])
        return True


def move_pin(conn: sqlite3.Connection, task_id: str, document_id: str, step: int) -> bool:
    """Move a pin up (-1) or down (+1) in its task's order. Returns whether it moved."""
    with transaction(conn):
        docs = pins_of(conn, task_id)
        if document_id not in docs:
            return False
        i = docs.index(document_id)
        j = max(0, min(len(docs) - 1, i + step))
        if i == j:
            return False
        docs.insert(j, docs.pop(i))
        _renumber(conn, task_id, docs)
        return True


def record_use(conn: sqlite3.Connection, document_id: str, task_id: str | None, action: str, at: datetime) -> None:
    """Note that a file was opened, shown or copied from DocRepo."""
    if action not in ACTIONS:
        raise ValueError(f"not a use: {action}")
    with transaction(conn):
        conn.execute("INSERT INTO document_uses (document, task, at, action) VALUES (?, ?, ?, ?)", (document_id, task_id, stamp(at), action))


def uses_of(conn: sqlite3.Connection, document_ids: Iterable[str], limit: int = 100) -> list[tuple[str, str, str]]:
    """The latest uses of these documents, newest first: (document, when, action)."""
    ids = list(document_ids)
    out: list[tuple[str, str, str]] = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        out += [(r["document"], r["at"], r["action"]) for r in conn.execute(
            f"SELECT document, at, action FROM document_uses WHERE document IN ({','.join('?' * len(chunk))}) ORDER BY at DESC, id DESC LIMIT ?",
            (*chunk, limit))]
    return sorted(out, key=lambda x: x[1], reverse=True)[:limit]


def last_uses(conn: sqlite3.Connection) -> dict[str, str]:
    """Each document's last use, for Sort by last opened and the preview's Opened."""
    return {r["document"]: r["at"] for r in conn.execute("SELECT document, max(at) AS at FROM document_uses GROUP BY document")}
