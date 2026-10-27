"""Changes made in the browse tool: filing a capture, fixing one, clearing a reminder, closing an agenda item, editing a
task and its notes page.

Each change happens in one database transaction, then its files are written:
the capture's capture.md, any saved copies, the search index and the generated
pages. A file that fails never undoes the change; it's reported and logged.

A capture's capture.md is written once and then only ever filed (the hard rules, since release 5.25): its title
and summary can be fixed in docs.db, and its words on its tasks' notes pages.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docrepo import activity, agenda, bulk, captures, notes_page, people, priorities, search, tasks
from docrepo.config import Settings
from docrepo.dates import stamp
from docrepo.db import transaction
from docrepo.links import is_link
from docrepo.model import TODAY, Model, is_person
from docrepo.pages import write_pages, write_task_page
from docrepo.parse import ParsePerson
from docrepo.safe_fs import SafeFS
from docrepo.schedule import start_of
from docrepo.stories import Stories

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


# ---- the notes page (release 5.25) ----
def stories_for(conn: sqlite3.Connection, data_root: Path, at: datetime, model: Model | None = None) -> tuple[Model, Stories]:
    model = model or Model(conn)
    return model, Stories(model, at.date(), lambda cid: captures.read_content(data_root, model.captures[cid]) or "")


def add_to_pages(conn: sqlite3.Connection, data_root: Path, at: datetime, added: list[tuple[str, str | None]], problems: list[str],
                 tasks_: list[str] | None = None) -> list[str]:
    """Put each capture's block on its tasks' notes pages (or ``tasks_``), given as (capture, its typed text, or None to
    read it), and index the pages for search. A page that can't be changed is a problem, not a failed change: the
    capture is kept, and its task page's Captures tab offers to add it again. Returns the tasks whose pages changed."""
    changed: list[str] = []
    try:
        model, stories = stories_for(conn, data_root, at)
        for capture_id, typed in added:
            if capture_id in model.captures:
                changed += notes_page.add_capture(conn, model, stories, capture_id, at, typed, tasks_)
        search.index_pages(conn, changed)
    except (sqlite3.Error, OSError, KeyError) as e:
        problems.append(f"The notes pages weren't all updated ({type(e).__name__}).")
    return changed


def save_page(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, body: str, at: datetime) -> Outcome:
    """The owner's edit of a task's notes page, saved as they type (decision 103): docs.db, the day's version, the
    search index and the task's Task.md. Nothing goes into the status log (decision 90)."""
    if task_id not in Model(conn).tasks:
        raise EditError(f"There's no task {task_id}.")
    out = Outcome("")
    if not notes_page.put(conn, task_id, body, at, by_owner=True):
        return out
    search.index_pages(conn, [task_id])
    try:
        write_task_page(Model(conn), data_root, fs, task_id, at.date(), at)
    except OSError as e:
        out.problems.append(f"Task.md wasn't updated ({type(e).__name__}).")
    return out


def add_again(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, task_id: str, at: datetime) -> Outcome:
    """Add it again (decision 109): a capture whose block is no longer on the page goes back, as it was first added."""
    out = Outcome("")
    changed = add_to_pages(conn, data_root, at, [(capture_id, None)], out.problems, [task_id])
    if changed:
        try:
            write_task_page(Model(conn), data_root, fs, task_id, at.date(), at)
        except OSError as e:
            out.problems.append(f"Task.md wasn't updated ({type(e).__name__}).")
    out.message = f"{capture_id} is on the page again." if changed else f"{capture_id} is on the page already."
    return out


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
    add_to_pages(conn, data_root, at, [(capture_id, None)], out.problems)  # decision 106: on the page when it's filed
    write_all_pages(conn, data_root, fs, at, out.problems)
    title = Model(conn).task(task_id).title
    out.message = f"Filed {capture_id} to {title}." + (f" {len(copies)} saved cop{'ies' if len(copies) > 1 else 'y'} made." if copies else "")
    log.info("capture %s filed to %s, %d saved copies", capture_id, task_id, len(copies))
    return out


# ---- fixing a capture's title and summary (release 5.25, decision 112) ----
def edit_capture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, title: str, summary: str,
                 summary_type: str | None, at: datetime) -> Outcome:
    """Fix a capture's title or summary. Its words are read, fixed and added to on its tasks' notes pages now, so its
    capture.md stays as it arrived: written once when it's saved, and then only ever filed (the hard rules)."""
    c = Model(conn).captures.get(capture_id)
    if c is None:
        raise EditError(f"There's no capture {capture_id}.")
    title, summary = " ".join(title.split()) or c.title, summary.strip()
    if title == c.title and summary == (c.summary or ""):
        return Outcome("Nothing changed.")
    with transaction(conn):
        conn.execute("UPDATE captures SET edited = ?, title = ?, summary = ?, summary_type = ? WHERE id = ?",
                     (stamp(at), title, summary or None, (summary_type or c.summary_type) if summary else None, capture_id))
    out = Outcome(f"Saved {capture_id}. Its text stays as it arrived; its words are edited on the notes page.")
    search.index_items(conn, data_root, captures=[capture_id])
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("capture %s: title or summary edited", capture_id)
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


def edit_today_note(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, note: str, at: datetime) -> Outcome:
    """Change a note's text on Today (mods log round 2, M0040)."""
    agenda.set_note(conn, item_id, note)
    out = Outcome("Note changed.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("Today note %d edited", item_id)
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
    stays unset. ``parents`` puts the task under exactly those tasks (mods log round 2, M0040), as one Parents change.
    ``priority`` (release 5.23) puts it in a bucket ("" for Not ranked), at the bucket's end, when that's a change.
    """
    added: list[str] = []
    parents = values.pop("parents", None)
    priority = values.pop("priority", None)
    day_headings = values.pop("day_headings", "unset")  # decision 119: a setting of the page, not logged
    with transaction(conn):
        if day_headings != "unset":
            conn.execute("UPDATE tasks SET day_headings = ? WHERE id = ?", (None if day_headings is None else int(day_headings), task_id))
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
        moved = tasks.set_parents(conn, task_id, parents, at=at, via=BROWSE) if parents is not None else None
        if moved:
            logged.append(moved)
        if priority is not None and priority != (t.priority or ""):
            ranked = priorities.place(conn, task_id, priority, at=at, via=BROWSE)
            if ranked:
                logged.append(ranked)
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


# ---- the Priorities board and the Activity view (release 5.23) ----
def set_priority(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, bucket: str, before: str | None,
                 at: datetime) -> Outcome:
    """A move on the Priorities board: into ``bucket`` ("" for Not ranked), before the task ``before`` there or at its
    end. A move to another bucket goes into the status log and the pages are written again; a move within one doesn't."""
    change = priorities.place(conn, task_id, bucket, before, at=at, via=priorities.VIA)
    title = tasks.get_task(conn, task_id).title
    if change is None:
        return Outcome(f"{title} moved within {priorities.name(bucket)}.")
    out = Outcome(f"{title}: {priorities.name(bucket)}. Its status log says so.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("task %s priority: %s", task_id, bucket or "not ranked")
    return out


def add_activity_to_agenda(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, target: str, entries: list[tuple[str | None, str]],
                           at: datetime) -> Outcome:
    """The Activity view's Add to agenda (decision 72): each (task, note) as an agenda item on ``target``, or a note alone
    for a task of None. A task already open on that agenda isn't added twice. One transaction."""
    m = Model(conn)
    added: list[str] = []
    skipped: list[str] = []
    with transaction(conn):
        for subject, note in entries:
            if subject and any(a.subject == subject for a in m.open_items_for(target)):
                skipped.append(m.task(subject).title)
                continue
            agenda.add_item(conn, subject=subject, target=target, note=" ".join(note.split()), added=stamp(at), added_by=activity.VIA)
            added.append(m.task(subject).title if subject else clip_note(note))
    where = "Today" if target == TODAY else f"{m.person_name(target)}'s agenda" if is_person(target) else f"the agenda of {m.target_name(target)}"
    message = f"Added {len(added)} to {where}: {', '.join(added)}." if added else "Nothing added."
    if skipped:
        message += f" Already on it: {', '.join(skipped)}."
    out = Outcome(message)
    if added:
        write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("activity view: %d agenda items for %s", len(added), target)
    return out


def clip_note(note: str, limit: int = 40) -> str:
    text = " ".join(note.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


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


def discard_capture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, reason: str, at: datetime,
                    off_edited_pages: bool = False) -> Outcome:
    """Discard a capture saved by mistake. It leaves its tasks' raw text logs, summaries and files, the Unfiled view and
    search, and is kept in the Discarded view. Its folder and capture.md stay as they are, and changes it made to tasks
    stay in their status logs. Its block comes off its tasks' notes pages (decision 106); a block the owner edited there
    stays, unless ``off_edited_pages`` (the browse tool asks first: ``notes_page.edited_blocks``)."""
    model, stories = stories_for(conn, data_root, at)
    c = model.captures.get(capture_id)
    if c is None:
        raise EditError(f"There's no capture {capture_id}.")
    if c.discarded:
        raise EditError(f"{capture_id} is already discarded.")
    with transaction(conn):
        pages = notes_page.remove_capture(conn, model, stories, capture_id, at, force=off_edited_pages)
        conn.execute("UPDATE captures SET discarded = ?, discard_reason = ? WHERE id = ?",
                     (stamp(at), " ".join(reason.split()) or DISCARD_REASON, capture_id))
    search.index_pages(conn, [t for t, what in pages.items() if what == "removed"])
    kept = [t for t, what in pages.items() if what == "edited"]
    out = Outcome(f"Discarded {capture_id}. Its folder stays; it's in the Discarded view, where Bring back restores it."
                  + (" Its block stays on the notes page, as you'd edited it there." if kept else ""))
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
    add_to_pages(conn, data_root, at, [(capture_id, None)], out.problems)  # its block goes back on its tasks' pages
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
