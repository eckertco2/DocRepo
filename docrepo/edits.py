"""Changes made in the browse tool: filing a capture, fixing one, clearing a reminder and closing an agenda item.

Each change happens in one database transaction, then its files are written:
the capture's capture.md, any saved copies, the search index and the generated
pages. A file that fails never undoes the change; it's reported and logged.

Fixing a capture keeps the previous capture.md in the capture's ``_old versions``
folder, so no captured text is ever lost (the hard rules).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docrepo import agenda, captures, search, tasks
from docrepo.config import Settings
from docrepo.dates import stamp
from docrepo.db import transaction
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.safe_fs import SafeFS
from docrepo.text import capture_title

log = logging.getLogger(__name__)

#: Where browse tool changes come from, in the status log.
BROWSE = "Browse tool"


class EditError(ValueError):
    """A change the browse tool can't make as asked."""


@dataclass
class Outcome:
    """What a change did, for the browse tool to say. ``problems`` lists files that couldn't be written."""

    message: str
    problems: list[str] = field(default_factory=list)


def write_all_pages(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, at: datetime, problems: list[str]) -> None:
    try:
        write_pages(Model(conn), data_root, fs, at.date(), at)
    except OSError as e:
        problems.append(f"The generated pages weren't all updated ({type(e).__name__}).")


# ---- saved copies ----
def source_of(data_root: Path, model: Model, document_id: str) -> Path | None:
    """Where a document's file is: its tracked original, or an email attachment in its capture's folder."""
    d = model.documents[document_id]
    if d.original:
        return Path(d.original)
    if d.capture and d.capture in model.captures:
        c = model.captures[d.capture]
        return captures.capture_folder(data_root, c.id, c.saved) / "attachments" / d.name
    return None


def plan_copies(conn: sqlite3.Connection, task_id: str, documents: list[str], day: str, from_capture: str) -> list[tuple[str, str]]:
    """Record a saved copy in the task's Files folder for each document. Returns (document, file name) for each."""
    from docrepo.save import copy_name  # save imports this module

    taken = {r["name"] for r in conn.execute("SELECT name FROM saved_copies WHERE task = ?", (task_id,))}
    out = []
    for doc in documents:
        name = copy_name(day, conn.execute("SELECT name FROM documents WHERE id = ?", (doc,)).fetchone()["name"], taken)
        taken.add(name)
        captures.add_saved_copy(conn, task=task_id, name=name, document=doc, from_capture=from_capture)
        out.append((doc, name))
    return out


def copy_files(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, copies: list[tuple[str, str]], problems: list[str]) -> None:
    """Copy each planned saved copy into the task's Files folder."""
    model = Model(conn)
    for doc, name in copies:
        source = source_of(data_root, model, doc)
        if source is None:
            continue
        try:
            fs.copy_file(source, data_root / "Tasks" / task_id / "Files" / name)
        except (OSError, FileExistsError) as e:
            problems.append(f"The copy of {source.name} couldn't be saved ({type(e).__name__}).")
            log.warning("saved copy %s for %s failed: %s", name, task_id, type(e).__name__)


# ---- filing a capture ----
def file_capture_records(conn: sqlite3.Connection, capture_id: str, task_id: str, at: datetime) -> list[tuple[str, str]]:
    """Link an unfiled capture to a task in docs.db, and plan its saved copies. Returns the copies to make."""
    model = Model(conn)
    c = model.captures.get(capture_id)
    if c is None:
        raise EditError(f"There's no capture {capture_id}.")
    if task_id not in model.tasks:
        raise EditError(f"There's no task {task_id}.")
    if not model.is_unfiled(c):
        raise EditError(f"{capture_id} is already filed.")
    with transaction(conn):
        conn.execute("UPDATE captures SET filed_to = ?, filed = ? WHERE id = ?", (task_id, stamp(at), capture_id))
        # Save a copy waited for filing: the copies go into the task's Files folder now.
        wanted = [d.document for d in c.documents if d.save_a_copy]
        return plan_copies(conn, task_id, wanted, at.date().isoformat(), capture_id)


def rewrite_capture_md(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, content: str | None, problems: list[str]) -> None:
    """Write a capture's capture.md again from docs.db, with its content text. Never with content it couldn't read."""
    if content is None:
        problems.append(f"{capture_id}'s capture.md couldn't be read, so it wasn't updated.")
        return
    try:
        captures.write_capture_md(fs, data_root, Model(conn), capture_id, content)
    except OSError as e:
        problems.append(f"capture.md couldn't be written ({type(e).__name__}).")


def file_capture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, task_id: str, at: datetime) -> Outcome:
    """File an unfiled capture to a task. Its folder stays where it is; capture.md gets the task and the time it was filed."""
    c = Model(conn).captures.get(capture_id)
    content = captures.read_content(data_root, c) if c else None  # read before anything changes
    copies = file_capture_records(conn, capture_id, task_id, at)
    out = Outcome("")
    rewrite_capture_md(conn, data_root, fs, capture_id, content, out.problems)
    copy_files(conn, data_root, fs, task_id, copies, out.problems)
    search.index_items(conn, data_root, captures=[capture_id])
    write_all_pages(conn, data_root, fs, at, out.problems)
    title = Model(conn).task(task_id).title
    out.message = f"Filed {capture_id} to {title}." + (f" {len(copies)} saved cop{'ies' if len(copies) > 1 else 'y'} made." if copies else "")
    log.info("capture %s filed to %s, %d saved copies", capture_id, task_id, len(copies))
    return out


# ---- fixing a capture ----
def old_version_name(at: datetime, taken: set[str]) -> str:
    """The previous capture.md's name in _old versions: "capture 2026-10-08 1410.md", made unique."""
    base = f"capture {at:%Y-%m-%d %H%M}"
    name, n = f"{base}.md", 2
    while name.lower() in {t.lower() for t in taken}:
        name, n = f"{base} ({n}).md", n + 1
    return name


def edit_capture(
    conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, content: str, summary: str, summary_type: str | None,
    at: datetime,
) -> Outcome:
    """Fix a capture's content text or summary. The previous capture.md is kept in its _old versions folder first."""
    model = Model(conn)
    c = model.captures.get(capture_id)
    if c is None:
        raise EditError(f"There's no capture {capture_id}.")
    old = captures.read_content(data_root, c)
    if old is None:
        raise EditError(f"{capture_id}'s capture.md can't be read, so it can't be edited here.")
    content, summary = content.rstrip(), summary.strip()
    if content == old.rstrip() and summary == (c.summary or ""):
        return Outcome("Nothing changed.")
    if not content.strip() and not c.documents:
        raise EditError("The content text can't be empty for a capture with no files.")
    folder = captures.capture_folder(data_root, c.id, c.saved)
    old_dir = folder / "_old versions"
    taken = {p.name for p in old_dir.iterdir()} if old_dir.is_dir() else set()
    keep = old_dir / old_version_name(at, taken)
    fs.copy_file(folder / "capture.md", keep)  # if this fails, nothing is changed
    first_doc = next((model.documents[d].name for d in c.document_ids if d in model.documents), None)
    with transaction(conn):
        conn.execute("UPDATE captures SET edited = ?, title = ?, summary = ?, summary_type = ? WHERE id = ?",
                     (stamp(at), capture_title(c.source, content, first_doc, c.id), summary or None,
                      (summary_type or c.summary_type) if summary else None, capture_id))
    out = Outcome(f"Saved {capture_id}. The previous version is in its _old versions folder.")
    rewrite_capture_md(conn, data_root, fs, capture_id, content, out.problems)
    search.index_items(conn, data_root, captures=[capture_id])
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("capture %s edited; previous version kept as %s", capture_id, keep.name)
    return out


# ---- tasks and agendas ----
def clear_reminder(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime) -> Outcome:
    """Clear a task's reminder from the Reminders list. Its status log records it."""
    tasks.update_task(conn, settings, task_id, at=at, via="Reminders list", reminder=None)
    out = Outcome(f"{Model(conn).task(task_id).title}: reminder cleared. The change is in its status log.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def close_agenda_item(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, how: str, at: datetime) -> Outcome:
    """Close an agenda item as Discussed or Removed, from the Agendas view. Its task stays as it is."""
    agenda.close_item(conn, item_id, how=how, closed=stamp(at), closed_by="Agenda view")
    m = Model(conn)
    a = next(x for x in m.agenda if x.id == item_id)
    what = m.task(a.subject).title if a.subject else "The note"
    out = Outcome(f"{what}: {how.lower()}. It's off the {m.target_name(a.target)} agenda" + (", and its status log says so." if a.subject else "."))
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("agenda item %d closed as %s", item_id, how)
    return out


def change_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime, **changes) -> Outcome:
    """Change a task's fields from the browse tool, such as its title, description or labels."""
    logged = tasks.update_task(conn, settings, task_id, at=at, via=BROWSE, **changes)
    out = Outcome(f"{len(logged)} change{'s' if len(logged) != 1 else ''} in the status log." if logged else "Nothing changed.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def move_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, old_parent: str | None, new_parent: str | None,
              at: datetime) -> Outcome:
    """Move a task under another parent, add a parent, or take it out from under one."""
    change = tasks.move_parent(conn, task_id, old_parent, new_parent, at=at, via=BROWSE)
    m = Model(conn)
    where = change.to_value or "nothing: it's a top-level task now"
    out = Outcome(f"{m.task(task_id).title} is now under {where}.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out
