"""Changing several tasks at once: Edit selected (mods log round 1, M0009) and a label's matching tasks (M0014).

Edit selected changes only what it's told to, on every ticked task, in one
transaction, and each task gets its own status log entries. Its preview makes
the same changes and rolls them back, so the preview is exactly what Apply does.
A task a change can't be made on (a move that would put it under itself) is left
as it was, and the preview and Apply say why.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from docrepo import people, tasks
from docrepo.config import Settings
from docrepo.db import transaction
from docrepo.model import Model
from docrepo.schedule import is_open

#: The fields Edit selected sets the same on every task. A date set to None is cleared.
SET_FIELDS = ("state", "due", "deadline", "reminder")
#: Where a label's keywords are looked for, with their names in the list of matches.
SEARCHED = (("title", "Title"), ("description", "Description"), ("current_status", "Current status"))


@dataclass
class BulkEdit:
    """What Edit selected changes. Whatever is left at its default stays as it is on every task."""

    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)  # some of SET_FIELDS
    #: ("add", person IDs) adds them to those there; ("set", person IDs) puts them in their place.
    leads: tuple[str, list[str]] | None = None
    assignees: tuple[str, list[str]] | None = None
    parent: str | None = None
    #: "move": under ``parent`` instead of under its parents; "also": under it as well.
    parent_how: str = "move"

    @property
    def empty(self) -> bool:
        return not (self.add_labels or self.remove_labels or self.fields or self.leads or self.assignees or self.parent)


@dataclass
class TaskOutcome:
    """What the edit does to one task: its status log entries, or why it couldn't be made."""

    task: str
    changes: list[tasks.Change] = field(default_factory=list)
    problem: str | None = None


def _edit_one(conn: sqlite3.Connection, settings: Settings, task_id: str, edit: BulkEdit, at: datetime, via: str) -> list[tasks.Change]:
    t = tasks.get_task(conn, task_id)
    unknown = set(edit.fields) - set(SET_FIELDS)
    if unknown:
        raise tasks.TaskError(f"Edit selected doesn't set {', '.join(sorted(unknown))}.")
    changes: dict[str, Any] = dict(edit.fields)
    if edit.add_labels or edit.remove_labels:
        removed = {n.strip().lower() for n in edit.remove_labels}
        own = [n for n in t.labels if n.lower() not in removed]
        have = {n.lower() for n in own}
        changes["labels"] = own + [n.strip() for n in edit.add_labels if n.strip().lower() not in have]
    for key in ("leads", "assignees"):
        how = getattr(edit, key)
        if how:
            mode, ids = how
            now = getattr(t, key)
            changes[key] = now + [p for p in ids if p not in now] if mode == "add" else list(ids)
    logged = tasks.update_task(conn, settings, task_id, at=at, via=via, **changes) if changes else []
    if edit.parent:
        now = [r["parent"] for r in conn.execute("SELECT parent FROM task_parents WHERE child = ? ORDER BY id", (task_id,))]
        wanted = [edit.parent] if edit.parent_how == "move" else [*now, edit.parent]
        moved = tasks.set_parents(conn, task_id, wanted, at=at, via=via)
        if moved:
            logged.append(moved)
    return logged


def run(conn: sqlite3.Connection, settings: Settings, task_ids: list[str], edit: BulkEdit, at: datetime, via: str) -> list[TaskOutcome]:
    """Make the edit on each task, inside one transaction. A task it can't be made on is left as it was, with its problem."""
    out: list[TaskOutcome] = []
    with transaction(conn):
        for name in edit.add_labels:
            if conn.execute("SELECT 1 FROM labels WHERE name = ?", (name.strip(),)).fetchone() is None:
                people.add_label(conn, name)
        for task_id in dict.fromkeys(task_ids):
            conn.execute("SAVEPOINT edit_one")
            try:
                changes = _edit_one(conn, settings, task_id, edit, at, via)
            except tasks.TaskError as e:
                conn.execute("ROLLBACK TO edit_one")
                conn.execute("RELEASE edit_one")
                out.append(TaskOutcome(task_id, problem=str(e)))
                continue
            conn.execute("RELEASE edit_one")
            out.append(TaskOutcome(task_id, changes))
    return out


class _Preview(Exception):
    """Raised to roll the preview's changes back."""


def preview(conn: sqlite3.Connection, settings: Settings, task_ids: list[str], edit: BulkEdit, at: datetime, via: str) -> list[TaskOutcome]:
    """What Apply would do, made and then rolled back, so nothing changes."""
    if conn.in_transaction:
        raise RuntimeError("A preview can't run inside another transaction: it couldn't be rolled back on its own.")
    out: list[TaskOutcome] = []
    try:
        with transaction(conn):
            out = run(conn, settings, task_ids, edit, at, via)
            raise _Preview
    except _Preview:
        pass
    return out


def summary(outcomes: list[TaskOutcome], done: bool = False) -> str:
    """One line on what an edit does ("2 tasks change, 3 changes in their status logs.") or did, once ``done``
    ("Changed 2 tasks: 3 changes in their status logs.")."""
    changed = [o for o in outcomes if o.changes]
    count = sum(len(o.changes) for o in outcomes)
    one = len(changed) == 1
    logs = f"{count} change{'s' if count != 1 else ''} in {'its status log' if one else 'their status logs'}"
    if not changed:
        text = "Nothing changed." if done else "Nothing changes."
    elif done:
        text = f"Changed {len(changed)} task{'' if one else 's'}: {logs}."
    else:
        text = f"{len(changed)} task{'' if one else 's'} change{'s' if one else ''}, {logs}."
    skipped = [o for o in outcomes if o.problem]
    if skipped:
        n = len(skipped)
        text += f" {n} {'was' if n == 1 else 'were'} left as {'it was' if n == 1 else 'they were'}" if done else \
            f" {n} can't be changed and {'stays as it is' if n == 1 else 'stay as they are'}"
        text += f": {skipped[0].problem}" if n == 1 else "."
    return text


# ---- a label's matching tasks ----
def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """A label keyword, as Parse and populate finds it: a whole word, with -s, -es, -ing or -ed allowed."""
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?:s|es|ing|ed)?(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class Found:
    """Where a keyword was found: the field's name, and the text around it with the keyword at ``start`` to ``end``."""

    field: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class LabelMatch:
    task: str
    found: tuple[Found, ...]


def _around(text: str, start: int, end: int, width: int = 50) -> Found:
    a, b = max(0, start - width), min(len(text), end + width)
    lead, tail = ("…" if a else ""), ("…" if b < len(text) else "")
    part = text[a:b].replace("\n", " ")
    return Found("", lead + part + tail, len(lead) + start - a, len(lead) + end - a)


def label_matches(m: Model, name: str) -> list[LabelMatch]:
    """Open tasks whose title, description or current status holds one of the label's keywords, and that don't have the
    label yet (their own or inherited). Each says where a keyword was found."""
    label = next((lb for lb in m.labels if lb.name.lower() == name.lower()), None)
    if label is None:
        return []
    patterns = [keyword_pattern(k) for k in (label.keywords or [label.name]) if k.strip()]
    out = []
    for t in m.tasks.values():
        if not is_open(t) or any(n.lower() == label.name.lower() for n, _ in m.labels_of(t.id)):
            continue
        found = []
        for key, field_name in SEARCHED:
            text = getattr(t, key) or ""
            hit = min((x for p in patterns if (x := p.search(text))), key=lambda x: x.start(), default=None)
            if hit:
                f = _around(text, hit.start(), hit.end())
                found.append(Found(field_name, f.text, f.start, f.end))
        if found:
            out.append(LabelMatch(t.id, tuple(found)))
    return out
