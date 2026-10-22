"""Quick tasks (mods log round 2, M0039, M0040): one-line tasks put straight on Today.

A quick task is an ordinary task. With no parent of its own it waits under the built-in top-level task Quick tasks,
so it doesn't sit among the projects in the task tree, until Edit task puts it under its real task. Quick tasks is
made the first time it's needed. DocRepo knows it by its creator, ``CREATOR``, so renaming it changes nothing; if it's
discarded, the next quick task makes a new one.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from docrepo import tasks
from docrepo.config import Settings
from docrepo.db import transaction
from docrepo.model import Task

TITLE = "Quick tasks"
CREATOR = "DocRepo"
DESCRIPTION = "Built in. Quick tasks made on Today wait here until you put them under their real task with Edit task."


def is_parent(t: Task) -> bool:
    """Whether the task is the built-in Quick tasks."""
    return t.created_by == CREATOR


def parent_id(conn: sqlite3.Connection) -> str | None:
    """The built-in Quick tasks' ID, or None before the first quick task (or after it was discarded)."""
    row = conn.execute("SELECT id FROM tasks WHERE created_by = ? AND discarded IS NULL ORDER BY id DESC LIMIT 1", (CREATOR,)).fetchone()
    return str(row["id"]) if row else None


def ensure_parent(conn: sqlite3.Connection, settings: Settings, at: datetime) -> str:
    """Quick tasks' ID, making it first if it isn't there. Joins the caller's transaction."""
    with transaction(conn):
        return parent_id(conn) or tasks.create_task(conn, settings, title=TITLE, at=at, created_by=CREATOR, description=DESCRIPTION,
                                                    state="In progress")
