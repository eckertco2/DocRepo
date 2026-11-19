"""Making a collection, and a collection a task again (release 5.167, the design workspace's
docs/mods/collections-and-kinds-plan.md, decisions 779 and 781).

- **Make it a collection** sets the flag (``tasks.set_collection``), takes the task off Today (its open Today item closed
  as Removed) and ends its open wait (as Got it does, taking away the reminder the wait set). Its other fields stay as they
  were, unseen. **With everything under it**, every task and collection below it that isn't discarded goes the same way.
- **Make it a task** clears the flag, so its fields come back as they were. The built-in Quick tasks stays a collection.
- **Archive** and **Restore** are a collection's state menu (``archive_ids``, ``restored_state``): stored as Closed and open
  again in the state it had, through ``edits.set_states``, which the status log says as "Archived".

Each is one transaction, with the pages written after, as ``edits``' changes are.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from docrepo import agenda, kinds, quick, tasks, waits
from docrepo.config import Settings
from docrepo.dates import stamp
from docrepo.db import transaction
from docrepo.edits import EditError, Outcome, hand_back, model_now, write_touched_pages
from docrepo.model import TODAY, Model
from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

#: Where these changes come from, in the status log and on a closed Today item.
VIA = "Browse tool"
MAKE = "Make it a collection"
MAKE_ALL = "Make it a collection, with everything under it"
MAKE_TASK = "Make it a task"
ARCHIVE = "Archive"
ARCHIVE_ALL = "Archive, with everything under it"
RESTORE = "Restore"
#: A collection's state when it's restored and nothing says what it had: it has no state to show, so the first.
RESTORED_STATE = "Not started"


class CollectionError(EditError):
    """A change of kind that can't be made as asked."""


def below(m: Model, task_id: str) -> list[str]:
    """Everything under a task or collection that isn't discarded, at every level, in the tree's order."""
    return [x for x in m.descendants_of(task_id) if x in m.tasks and not m.tasks[x].discarded]


def _off_today_and_unwaited(conn: sqlite3.Connection, settings: Settings, m: Model, task_id: str, at: datetime) -> tuple[bool, bool]:
    """Take a task off Today and end its open wait (decision 779). Returns whether each happened."""
    off = False
    for a in m.agendas_on(task_id):
        if a.target == TODAY:
            agenda.close_item(conn, a.id, how="Removed", closed=stamp(at), closed_by=MAKE)
            off = True
    w = waits.current(m, task_id)
    if w is not None:
        back = waits.end(conn, m, w, waits.stamp_of(at), waits.GOT_IT, MAKE)
        if back is not None:
            tasks.update_task(conn, settings, task_id, at=at, via=MAKE, reminder=back or None)
    return off, w is not None


def make_collection(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime, *,
                    with_below: bool = False, model: Model | None = None) -> Outcome:
    """Make a task a collection (decision 779), with everything under it when ``with_below``."""
    before = model_now(conn, model)
    t = before.tasks.get(task_id)
    if t is None or t.discarded:
        raise CollectionError(f"There's no task {task_id} to make a collection.")
    ids = [task_id, *(below(before, task_id) if with_below else [])]
    made, off, unwaited = [], 0, 0
    with transaction(conn):
        for x in ids:
            if before.task(x).collection:
                continue
            o, w = _off_today_and_unwaited(conn, settings, before, x, at)
            tasks.set_collection(conn, settings, x, True, at=at, via=VIA)
            made.append(x)
            off, unwaited = off + o, unwaited + w
    if not made:
        out = Outcome(f"{t.title} is a collection already.")
    else:
        more = len(made) - (task_id in made)
        words = f"{t.title} is a collection" + (f", with {more} more under it" if more else "") + "."
        if off:
            words += f" Off Today{f' ({off})' if off > 1 else ''}."
        if unwaited:
            words += " Its wait ended." if unwaited == 1 else f" {unwaited} waits ended."
        out = Outcome(words)
    hand_back(out, write_touched_pages(conn, data_root, fs, at, out.problems, made or [task_id], before))
    log.info("collection: %s made one, %d in all", task_id, len(made))
    return out


def make_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime, *,
              model: Model | None = None) -> Outcome:
    """Make a collection a task again (decision 779): its fields come back as they were. Quick tasks stays a collection."""
    before = model_now(conn, model)
    t = before.tasks.get(task_id)
    if t is None or t.discarded:
        raise CollectionError(f"There's no collection {task_id}.")
    if quick.is_parent(t):
        raise CollectionError(f"{t.title} is built in, and stays a collection.")
    change = tasks.set_collection(conn, settings, task_id, False, at=at, via=VIA)
    out = Outcome(f"{t.title} is a task again." if change else f"{t.title} is a task already.")
    hand_back(out, write_touched_pages(conn, data_root, fs, at, out.problems, [task_id], before))
    log.info("collection: %s made a task", task_id)
    return out


def archive_ids(m: Model, task_id: str, with_below: bool) -> dict[str, str]:
    """What Archive (or Archive, with everything under it) sets, for ``edits.set_states`` (decision 781): the collection,
    and with ``with_below`` everything open under it, collections archived and tasks closed alike."""
    ids = [task_id, *(x for x in below(m, task_id) if m.task(x).state != "Closed")] if with_below else [task_id]
    return dict.fromkeys(ids, "Closed")


def restored_state(m: Model, task_id: str) -> str:
    """The state Restore brings back: the one it had when it was archived, kept in the status log's Archived line, so Make
    it a task finds it as it was (the review of 2026-11-18); ``RESTORED_STATE`` when the log doesn't say."""
    for e in reversed(m.status_log_of(task_id)):
        if e.field == tasks.ARCHIVED and e.to_value and e.from_value in ("Not started", "In progress", "Parked"):
            return e.from_value
    return RESTORED_STATE


def can_archive(m: Model, task_id: str) -> bool:
    """Whether a collection can be archived: it's one, it's open and it isn't Quick tasks, which quick tasks need."""
    t = m.tasks.get(task_id)
    return t is not None and kinds.is_collection(t) and not t.discarded and t.state != "Closed" and not quick.is_parent(t)
