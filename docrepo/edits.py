"""Changes made in the browse tool: filing a capture, fixing one, clearing a reminder, closing an agenda item and editing a task.

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

from docrepo import agenda, bulk, captures, people, search, tasks
from docrepo.config import Settings
from docrepo.dates import stamp
from docrepo.db import transaction
from docrepo.links import is_link
from docrepo.model import TODAY, Model
from docrepo.pages import write_pages
from docrepo.safe_fs import SafeFS
from docrepo.schedule import start_of
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
    """Where a document's file is: its tracked original, or an email attachment in its capture's folder. A link has
    no file, so None: DocRepo never hands one to File Explorer, which would open it in the browser."""
    d = model.documents[document_id]
    if is_link(d.original):
        return None
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


def add_to_today(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, subject: str | None, note: str, at: datetime) -> Outcome:
    """Put a task, or a note, on Today (mods log round 1, M0016). A task already there stays as it is."""
    m = Model(conn)
    if subject and any(a.subject == subject for a in m.today_items()):
        return Outcome(f"{m.task(subject).title} is on Today already.")
    agenda.add_item(conn, subject=subject, target=TODAY, note=" ".join(note.split()), added=stamp(at), added_by=BROWSE)
    out = Outcome(f"{m.task(subject).title} is on Today. Its status log says so." if subject else "Note added to Today.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("added to Today: %s", subject or "a note")
    return out


def close_today_item(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, how: str, at: datetime) -> Outcome:
    """Mark a Today item Done, or take it off Today. Its task stays as it is."""
    agenda.close_item(conn, item_id, how=how, closed=stamp(at), closed_by="Today")
    m = Model(conn)
    a = next(x for x in m.agenda if x.id == item_id)
    what = m.task(a.subject).title if a.subject else "The note"
    out = Outcome(f"{what}: {'done' if how == 'Done' else 'taken off Today'}." + (" Its status log says so." if a.subject else ""))
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("Today item %d closed as %s", item_id, how)
    return out


def change_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime, **changes) -> Outcome:
    """Change a task's fields from the browse tool, such as its title, description or labels."""
    logged = tasks.update_task(conn, settings, task_id, at=at, via=BROWSE, **changes)
    out = Outcome(f"{len(logged)} change{'s' if len(logged) != 1 else ''} in the status log." if logged else "Nothing changed.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def edit_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime, **values) -> Outcome:
    """Save the Edit task form (mods log round 1, M0008, M0011): every field on one page, in one transaction.

    Only the fields that differ change, each logged as "Browse tool". ``leads`` and ``assignees`` are Who's: someone not on
    the people list is added to it, and a label not there yet is created. A Start left at the day the task was created
    stays unset.
    """
    added: list[str] = []
    with transaction(conn):
        t = tasks.get_task(conn, task_id)
        if values.get("start") == start_of(t).isoformat() and not t.start:
            values.pop("start")
        for name in values.get("labels", ()):
            if conn.execute("SELECT 1 FROM labels WHERE name = ?", (name.strip(),)).fetchone() is None:
                people.add_label(conn, name)
        note = f"Added on {at.date().isoformat()} in the browse tool. Aliases and hours aren't set yet."
        for key in ("leads", "assignees"):
            if key in values:
                ids = []
                for w in values[key]:
                    if w.id:
                        ids.append(w.id)
                        continue
                    person_id, new = people.find_or_add(conn, w.name, note)
                    if new:
                        added.append(w.name.strip())
                    ids.append(person_id)
                values[key] = ids
        logged = tasks.update_task(conn, settings, task_id, at=at, via=BROWSE, **values)
    message = f"{len(logged)} change{'s' if len(logged) != 1 else ''} in the status log." if logged else "Nothing changed."
    if added:
        message += f" Added {', '.join(added)} to the people list."
    out = Outcome(message)
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("task %s edited in the browse tool: %d changes", task_id, len(logged))
    return out


def bulk_edit(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_ids: list[str], edit: bulk.BulkEdit,
              at: datetime) -> Outcome:
    """Edit selected (mods log round 1, M0009): the same change on several tasks, in one transaction."""
    outcomes = bulk.run(conn, settings, task_ids, edit, at, BROWSE)
    out = Outcome(bulk.summary(outcomes, done=True))
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("edit selected: %d tasks, %d changes", len(outcomes), sum(len(o.changes) for o in outcomes))
    return out


# ---- discarding (mods log round 1, M0021) ----
#: The reason given when none is typed.
DISCARD_REASON = "Made by mistake"


def discard_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, reason: str, at: datetime) -> Outcome:
    """Discard a task made by mistake. It's hidden from the task tree, the lists, the pickers, search and the capacity
    calendar, and kept in the Discarded view; nothing is deleted. A task with subtasks that aren't discarded, or with open
    items on its own agenda, has to lose them first. It comes off the agendas it's on, as Removed."""
    reason = " ".join(reason.split()) or DISCARD_REASON
    with transaction(conn):
        m = Model(conn)
        t = m.tasks.get(task_id)
        if t is None:
            raise EditError(f"There's no task {task_id}.")
        if any(not m.task(k).discarded for k in m.children_of(task_id)):
            raise EditError(f"{t.title} has subtasks. Move them somewhere else, or discard them first.")
        if m.open_items_for(task_id):
            raise EditError(f"{t.title}'s agenda has open items. Mark them Discussed or Remove them first.")
        removed = m.agendas_on(task_id)
        for a in removed:
            agenda.close_item(conn, a.id, how="Removed", closed=stamp(at), closed_by=BROWSE)
        tasks.set_discarded(conn, settings, task_id, reason, at=at, via=BROWSE)
    off = f" It's off {len(removed)} agenda{'s' if len(removed) > 1 else ''}." if removed else ""
    out = Outcome(f"Discarded {t.title}.{off} It's in the Discarded view, where Bring back restores it.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("task %s discarded", task_id)
    return out


def bring_back_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime) -> Outcome:
    """Bring a discarded task back, as it was. One whose parents are all discarded waits until one of them is back."""
    m = Model(conn)
    t = m.tasks.get(task_id)
    if t is None:
        raise EditError(f"There's no task {task_id}.")
    parents = m.parents_of(task_id)
    if parents and all(m.task(p).discarded for p in parents):
        raise EditError(f"{t.title}'s parent is discarded too. Bring {m.task(parents[0]).title} back first.")
    tasks.set_discarded(conn, settings, task_id, None, at=at, via=BROWSE)
    out = Outcome(f"Brought back {t.title}.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("task %s brought back", task_id)
    return out


def discard_capture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, reason: str, at: datetime) -> Outcome:
    """Discard a capture saved by mistake. It leaves its tasks' raw text logs, summaries and files, the Unfiled view and
    search, and is kept in the Discarded view. Its folder and capture.md stay as they are, and changes it made to tasks
    stay in their status logs."""
    c = Model(conn).captures.get(capture_id)
    if c is None:
        raise EditError(f"There's no capture {capture_id}.")
    if c.discarded:
        raise EditError(f"{capture_id} is already discarded.")
    with transaction(conn):
        conn.execute("UPDATE captures SET discarded = ?, discard_reason = ? WHERE id = ?",
                     (stamp(at), " ".join(reason.split()) or DISCARD_REASON, capture_id))
    out = Outcome(f"Discarded {capture_id}. Its folder stays; it's in the Discarded view, where Bring back restores it.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("capture %s discarded", capture_id)
    return out


def bring_back_capture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, at: datetime) -> Outcome:
    c = Model(conn).captures.get(capture_id)
    if c is None or not c.discarded:
        raise EditError(f"{capture_id} isn't discarded.")
    with transaction(conn):
        conn.execute("UPDATE captures SET discarded = NULL, discard_reason = NULL WHERE id = ?", (capture_id,))
    out = Outcome(f"Brought back {capture_id}.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("capture %s brought back", capture_id)
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
