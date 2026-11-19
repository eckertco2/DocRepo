"""The current task (release 5.177, the design workspace's docs/mods/current-task-plan.md, decisions 825 to 831).

One task at a time is the **current task**: the one the owner has said they're working on, with **Work on it** (the tile
menu's line, the W key, the page's action) or the workspace bar's **Work on this**. Opening a task (a double-click, Enter,
Task search, a link) doesn't make it current: since release 5.174 every task opens in its workspace, so looking a task
up would otherwise take the place of the one being worked on (decision 826). Making another task current takes the place
of the one before.

It's kept in docs.db's ``app_state`` under ``KEY``, so it's still there after a restart (decision 825), and it isn't
written in the task's status log: it's where the owner's attention is, not a fact about the task.

What ends it (decision 827): **Stop working on it** (the current task's menu, or the workspace's toggle pressed again);
Log progress on it with Done for today or Closed (``progress.log_progress``, in the same transaction as the rest); and
the task closed, discarded or made a collection by any route, which ``get`` finds and clears, so nothing else has to
remember to end it. Taking it off Today doesn't end it.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from docrepo.db import get_state, set_state, transaction

if TYPE_CHECKING:
    from docrepo.model import Model

#: The ``app_state`` key holding the current task's ID, or "" for none.
KEY = "current_task"


def stored(conn: sqlite3.Connection) -> str | None:
    """The ID kept, as it is, without checking the task: None for none."""
    return get_state(conn, KEY) or None


def get(conn: sqlite3.Connection, m: Model) -> str | None:
    """The current task's ID, or None. A task that's gone, discarded, Closed or a collection isn't current any more: the
    key is cleared, and None is the answer (decision 825)."""
    task_id = stored(conn)
    if task_id is None:
        return None
    t = m.tasks.get(task_id)
    if t is None or t.discarded or t.state == "Closed" or t.collection:
        if not conn.in_transaction:
            stop(conn)
        return None
    return task_id


def start(conn: sqlite3.Connection, task_id: str) -> None:
    """Make a task the current one, in the place of the one before."""
    set_state(conn, KEY, task_id)


def stop(conn: sqlite3.Connection) -> None:
    """No current task. Joins the caller's transaction, if there is one."""
    with transaction(conn):
        set_state(conn, KEY, "")


def is_current(conn: sqlite3.Connection, m: Model, task_id: str) -> bool:
    """Whether ``task_id`` is the current task."""
    return get(conn, m) == task_id
