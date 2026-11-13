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
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from docrepo import activity, agenda, bulk, captures, notes_page, people, priorities, quick, repeats, search, tasks, waits, whatif
from docrepo.config import Settings
from docrepo.dates import long_date, stamp, to_date, workday_numbers
from docrepo.db import transaction
from docrepo.links import is_link
from docrepo.lists import reminders_due
from docrepo.model import TODAY, Model, is_person
from docrepo.pages import write_pages, write_task_page
from docrepo.safe_fs import SafeFS
from docrepo.schedule import is_open, start_of
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
    moved: str = ""  # release 5.50: what moved with it, in words


def write_all_pages(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, at: datetime, problems: list[str]) -> None:
    try:
        write_pages(Model(conn), data_root, fs, at.date(), at)
    except OSError as e:
        problems.append(f"The generated pages weren't all updated ({type(e).__name__}).")


def write_touched_pages(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, at: datetime, problems: list[str],
                        task_ids: Collection[str], before: Model) -> None:
    """Write only the pages a change to these tasks can reach (release 5.90): ``pages.pages_touched`` of them, in the
    Model from before the change and after it, and Contents.md."""
    from docrepo.pages import pages_touched

    try:
        after = Model(conn)
        write_pages(after, data_root, fs, at.date(), at, pages_touched(after, task_ids) | pages_touched(before, task_ids))
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


def add_note(conn: sqlite3.Connection, task_id: str, typed: str, formatted: bool, at: datetime,
             made: list[tuple[str, str]] = ()) -> list[str]:
    """A note from the capture window on its task's page, as no capture (release 5.69, the notes workspace plan's
    decisions 341 and 345): under the page's headings with the same words as its own, or under the day's heading
    (``notes_page.place_note``). It's the owner's own edit, so the day's version counts in Activity's Notes edited, and
    the page is indexed for search. ``typed`` is the text as capture.md would keep it. ``made`` is each task its items
    made, with the item's text as its capture keeps it: on the page each is one task line (release 5.83, R4b). It joins
    the caller's transaction, so a save that fails keeps nothing and the window keeps the text. Returns the headings
    it went under."""
    lines = notes_page.note_markup(typed, formatted, own=task_id)
    if made and lines:
        lines = notes_page.task_lines(lines, [(tid, notes_page.note_markup(text, formatted, "", task_id)) for tid, text in made],
                                      Model(conn), at.date())
    if not lines:
        return []
    with transaction(conn):
        page, under = notes_page.place_note(notes_page.get(conn, task_id), lines, at.date())
        notes_page.put(conn, task_id, page, at, by_owner=True)
        search.index_pages(conn, [task_id])
    return under


def save_page(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, body: str, at: datetime) -> Outcome:
    """The owner's edit of a task's notes page, saved as they type (decision 103): docs.db, the day's version, the
    search index and the task's Task.md. Nothing goes into the status log (decision 90)."""
    if task_id not in Model(conn).tasks:
        raise EditError(f"There's no task {task_id}.")
    out = Outcome("")
    if not notes_page.put(conn, task_id, body, at, by_owner=True):
        return out
    search.index_pages(conn, [task_id])
    sync_descriptions(conn, data_root, task_id, body)
    try:
        write_task_page(Model(conn), data_root, fs, task_id, at.date(), at)
    except OSError as e:
        out.problems.append(f"Task.md wasn't updated ({type(e).__name__}).")
    return out


def default_page_description(task_title: str, name: str) -> str:
    """What a picture's or a file's description left empty on the page becomes (decision 125, release 5.5's rule)."""
    kind = "Pasted picture" if name.lower().endswith(notes_page.PICTURES) else "Attached document"
    return f"{task_title} – {kind} – {name}"


def sync_descriptions(conn: sqlite3.Connection, data_root: Path, task_id: str, body: str) -> list[str]:
    """A picture's or attachment's description is the list item under it on the page (decision 125): saving the page
    keeps it as the document's file description; left empty, the made-up one. Returns the documents changed."""
    model = Model(conn)
    title = model.task(task_id).title
    changed = []
    with transaction(conn):
        for doc_id, words in notes_page.descriptions(body).items():
            d = model.documents.get(doc_id)
            if d is None:
                continue
            want = words or (d.description if notes_page.made_up(d.description, d.name) and d.description else default_page_description(title, d.name))
            if want != (d.description or ""):
                conn.execute("UPDATE documents SET description = ? WHERE id = ?", (want, doc_id))
                changed.append(doc_id)
    if changed:
        search.index_items(conn, data_root, documents=changed)
    return changed


def unique_name(folder: Path, name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    candidate, n = name, 2
    while (folder / candidate).exists():
        candidate, n = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})", n + 1
    return candidate


def add_page_picture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, png: bytes,
                     at: datetime) -> tuple[str, str, str]:
    """A picture pasted on a task's notes page (decisions 124, 125 and 127): written as a PNG in the task's Files
    folder, and kept as a capture of its own, made on the page, with the picture as its document. The page shows it at
    the caret, so nothing is added to the page here. Returns (capture, document, file name)."""
    from docrepo.save import CaptureDraft, FileRow, save_capture

    model = Model(conn)
    if task_id not in model.tasks:
        raise EditError(f"There's no task {task_id}.")
    folder = data_root / "Tasks" / task_id / "Files"
    name = unique_name(folder, f"Picture {at:%Y-%m-%d %H%M}.png")
    path = fs.write_picture(folder / name, png)
    row = FileRow(name, str(path), default_page_description(model.task(task_id).title, name))
    r = save_capture(conn, data_root, fs, settings, CaptureDraft(task=task_id, types={"note"}, files=[row], page_made=True), at)
    doc = Model(conn).captures[r.capture_id].document_ids[0]
    log.info("picture %s pasted on %s's notes page as %s", name, task_id, r.capture_id)
    return r.capture_id, doc, name


def add_page_file(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, path: str,
                  at: datetime) -> tuple[str, str, str]:
    """A file dropped on a task's notes page (decision 126): kept as a capture of its own, made on the page, with the
    file as its document, its original tracked where it is and its text read, as a dropped file is in the capture
    window. Returns (capture, document, file name)."""
    from docrepo.save import CaptureDraft, FileRow, save_capture

    if task_id not in Model(conn).tasks:
        raise EditError(f"There's no task {task_id}.")
    name = Path(path).name
    row = FileRow(name, path, "", extract=not name.lower().endswith(notes_page.PICTURES))
    r = save_capture(conn, data_root, fs, settings, CaptureDraft(task=task_id, types={"note"}, files=[row], page_made=True), at)
    doc = Model(conn).captures[r.capture_id].document_ids[0]
    log.info("file dropped on %s's notes page as %s", task_id, r.capture_id)
    return r.capture_id, doc, name


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
    before = Model(conn)
    c = before.captures.get(capture_id)
    content = captures.read_content(data_root, c) if c else None  # read before anything changes
    copies = file_capture_records(conn, capture_id, task_id, at)
    out = Outcome("")
    rewrite_capture_md(conn, data_root, fs, capture_id, content, out.problems)
    copy_files(conn, data_root, fs, task_id, copies, out.problems)
    search.index_items(conn, data_root, captures=[capture_id])
    add_to_pages(conn, data_root, at, [(capture_id, None)], out.problems)  # decision 106: on the page when it's filed
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id, *(before.capture_tasks(c) if c else [])], before)
    title = Model(conn).task(task_id).title
    out.message = f"Filed {capture_id} to {title}." + (f" {len(copies)} saved cop{'ies' if len(copies) > 1 else 'y'} made." if copies else "")
    log.info("capture %s filed to %s, %d saved copies", capture_id, task_id, len(copies))
    return out


# ---- fixing a capture's title and summary (release 5.25, decision 112) ----
def edit_capture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, capture_id: str, title: str, summary: str,
                 summary_type: str | None, at: datetime) -> Outcome:
    """Fix a capture's title or summary. Its words are read, fixed and added to on its tasks' notes pages now, so its
    capture.md stays as it arrived: written once when it's saved, and then only ever filed (the hard rules)."""
    before = Model(conn)
    c = before.captures.get(capture_id)
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
    write_touched_pages(conn, data_root, fs, at, out.problems, before.capture_tasks(c), before)
    log.info("capture %s: title or summary edited", capture_id)
    return out


# ---- tasks and agendas ----
def clear_reminder(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime,
                   via: str = "Reminders list") -> Outcome:
    """Clear a task's reminder from the Reminders list or Today. Its status log records it."""
    before = Model(conn)
    tasks.update_task(conn, settings, task_id, at=at, via=via, reminder=None)
    out = Outcome(f"{Model(conn).task(task_id).title}: reminder cleared. The change is in its status log.")
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id], before)
    return out


def close_agenda_item(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, how: str, at: datetime) -> Outcome:
    """Close an agenda item as Discussed or Removed, from the Agendas view. Its task stays as it is."""
    before = Model(conn)
    agenda.close_item(conn, item_id, how=how, closed=stamp(at), closed_by="Agenda view")
    m = Model(conn)
    a = next(x for x in m.agenda if x.id == item_id)
    what = m.task(a.subject).title if a.subject else "The note"
    out = Outcome(f"{what}: {how.lower()}. It's off the {m.target_name(a.target)} agenda" + (", and its status log says so." if a.subject else "."))
    write_touched_pages(conn, data_root, fs, at, out.problems, [x for x in (a.subject, a.target) if x], before)
    log.info("agenda item %d closed as %s", item_id, how)
    return out


def reopen_agenda_item(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, at: datetime) -> Outcome:
    """Undo for Done on Today and Discussed or Removed on an agenda (release 5.91): the item is open again, as it was."""
    before = Model(conn)
    a = next((x for x in before.agenda if x.id == item_id), None)
    agenda.reopen_item(conn, item_id)
    out = Outcome("Back on Today." if a and a.target == TODAY else "Back on the agenda.")
    write_touched_pages(conn, data_root, fs, at, out.problems, [x for x in ((a.subject, a.target) if a else ()) if x], before)
    log.info("agenda item %d opened again", item_id)
    return out


#: Who adds and closes agenda items from the quick summary (release 5.131, decisions 526 and 527), in the agenda and status log.
SUMMARY = "Quick summary"


def add_agenda_item(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, target: str, subject: str | None, note: str, at: datetime) -> Outcome:
    """The quick summary's add box (release 5.131, decision 527): a note, or a task with the note as the item's words, on a
    person's or a task's agenda. A task already open on that agenda isn't put there twice."""
    m = Model(conn)
    words = " ".join(note.split())
    if subject and any(a.subject == subject for a in m.open_items_for(target)):
        return Outcome(f"{m.task(subject).title} is on that agenda already.")
    agenda.add_item(conn, subject=subject, target=target, note=words, added=stamp(at), added_by=SUMMARY)
    where = f"{m.person_name(target)}'s agenda" if is_person(target) else f"the agenda of {m.target_name(target)}"
    out = Outcome(f"Added to {where}" + (f", on {m.task(subject).title}." if subject else " as a note."))
    write_touched_pages(conn, data_root, fs, at, out.problems, [x for x in (subject, None if is_person(target) else target) if x], m)
    log.info("quick summary: agenda item on %s", target)
    return out


def discuss_agenda_item(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, at: datetime) -> Outcome:
    """An agenda item ticked in the quick summary (release 5.131, decision 526): closed as Discussed, by the quick summary.
    Its task stays as it is; ``reopen_agenda_item`` is its Undo."""
    before = Model(conn)
    agenda.close_item(conn, item_id, how="Discussed", closed=stamp(at), closed_by=SUMMARY)
    a = next(x for x in before.agenda if x.id == item_id)
    out = Outcome("Discussed.")
    write_touched_pages(conn, data_root, fs, at, out.problems, [x for x in (a.subject, None if is_person(a.target) else a.target) if x], before)
    log.info("quick summary: agenda item %d discussed", item_id)
    return out


def add_to_today(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, subject: str | None, note: str, at: datetime) -> Outcome:
    """Put a task, or a note, on Today (mods log round 1, M0016). A task already there stays as it is."""
    m = Model(conn)
    if subject and any(a.subject == subject for a in m.today_items()):
        return Outcome(f"{m.task(subject).title} is on Today already.")
    agenda.add_item(conn, subject=subject, target=TODAY, note=" ".join(note.split()), added=stamp(at), added_by=BROWSE)
    out = Outcome(f"{m.task(subject).title} is on Today. Its status log says so." if subject else "Note added to Today.")
    write_touched_pages(conn, data_root, fs, at, out.problems, [subject] if subject else [], m)
    log.info("added to Today: %s", subject or "a note")
    return out


def close_today_item(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, how: str, at: datetime) -> Outcome:
    """Mark a Today item Done, or take it off Today. Its task stays as it is."""
    before = Model(conn)
    agenda.close_item(conn, item_id, how=how, closed=stamp(at), closed_by="Today")
    m = Model(conn)
    a = next(x for x in m.agenda if x.id == item_id)
    what = m.task(a.subject).title if a.subject else "The note"
    out = Outcome(f"{what}: {'done' if how == 'Done' else 'taken off Today'}." + (" Its status log says so." if a.subject else ""))
    write_touched_pages(conn, data_root, fs, at, out.problems, [a.subject] if a.subject else [], before)
    log.info("Today item %d closed as %s", item_id, how)
    return out


# ---- reminders onto Today, and Later (release 5.116, decisions 415 and 417) ----
#: A Today item's ``added_by`` when a reminder put its task there.
REMINDER = "Reminder"
#: The status log's word for a reminder used up by putting its task on Today.
PUT_ON_TODAY = "Put on Today"
LATER = "Later"
#: The status log's word for a repeating reminder moved on to its next time (release 5.117).
REPEATS = "Reminder repeats"


def _workdays(settings: Settings) -> frozenset[int]:
    try:
        return workday_numbers(settings.workdays)
    except ValueError:
        return frozenset(range(5))


def next_reminder(task_id: str, model: Model, settings: Settings, today: date) -> str | None:
    """The reminder a task has once today's has put it on Today: none, as a reminder is used up (decision 415), or, for one
    that repeats, its next time after today (release 5.117, decision 416), unless that's past its Until."""
    t = model.task(task_id)
    if not t.reminder_repeat:
        return None
    return repeats.following(t.reminder_repeat, t.reminder_until, to_date(t.reminder) if t.reminder else today, today, _workdays(settings))


def reminders_to_today(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, at: datetime) -> list[str]:
    """Decision 415: each open task whose reminder has come, today or before, goes on Today by itself, as an item added by
    "Reminder", and the reminder is used up: cleared, with "Put on Today" in its status log. A task already on Today just
    has its reminder cleared. Returns the tasks whose reminder it used."""
    before = Model(conn)
    today = at.date()
    due = reminders_due(before, today)
    if not due:
        return []
    on_today = {a.subject for a in before.today_items() if a.subject}
    put: list[str] = []
    for t in due:
        if t.id not in on_today:
            agenda.add_item(conn, subject=t.id, target=TODAY, note="", added=stamp(at), added_by=REMINDER)
            put.append(t.id)
        # an open wait's follow-up still to come takes the reminder's place (release 5.139, decision 588)
        tasks.update_task(conn, settings, t.id, at=at, via=PUT_ON_TODAY, reminder=waits.after_reminder(before, t.id, today, next_reminder(t.id, before, settings, today)))
    # A repeat with no reminder (Clear took this time's) moves on to its next time after today (decision 416).
    waiting = [t for t in before.tasks.values() if t.reminder_repeat and not t.reminder and is_open(t) and t not in due]
    for t in waiting:
        nxt = repeats.following(t.reminder_repeat, t.reminder_until, today, today, _workdays(settings))
        if nxt:
            tasks.update_task(conn, settings, t.id, at=at, via=REPEATS, reminder=nxt)
    problems: list[str] = []
    write_touched_pages(conn, data_root, fs, at, problems, [t.id for t in (*due, *waiting)], before)
    log.info("reminders put on Today: %s", ", ".join(put) or "none new")
    return [t.id for t in (*due, *waiting)]


def later(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, day: date, at: datetime,
          item_id: int | None = None) -> Outcome:
    """Later (decision 417): the task's Reminder set to ``day``, so it comes back on Today then (decision 415). Its Today
    item, when it has one, is taken off Today, closed as "Removed" by "Later"; from Due in the next 7 days, the reminder
    keeps it off that list until its day (decision 418)."""
    if day <= at.date():
        raise EditError("Later needs a day after today.")
    before = Model(conn)
    t = before.task(task_id)
    if item_id is not None:
        agenda.close_item(conn, item_id, how="Removed", closed=stamp(at), closed_by=LATER)
    tasks.update_task(conn, settings, task_id, at=at, via=LATER, reminder=day.isoformat())
    off = "off Today" if item_id is not None else "off Due in the next 7 days"
    out = Outcome(f"{t.title}: {off} until {long_date(day, at.date())}, when its reminder puts it back on Today.")
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id], before)
    log.info("later: %s until %s", task_id, day.isoformat())
    return out


def undo_later(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, reminder: str | None,
               at: datetime, item_id: int | None = None) -> Outcome:
    """Later's Undo: the reminder the task had, and its Today item open again."""
    before = Model(conn)
    if item_id is not None:
        agenda.reopen_item(conn, item_id)
    tasks.update_task(conn, settings, task_id, at=at, via="Undo", reminder=reminder)
    out = Outcome("Back on Today, as it was." if item_id is not None else "Back as it was.")
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id], before)
    return out


def edit_today_note(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, item_id: int, note: str, at: datetime) -> Outcome:
    """Change a note's text on Today (mods log round 2, M0040)."""
    before = Model(conn)
    agenda.set_note(conn, item_id, note)
    out = Outcome("Note changed.")
    subject = next((a.subject for a in before.agenda if a.id == item_id), None)
    write_touched_pages(conn, data_root, fs, at, out.problems, [subject] if subject else [], before)
    log.info("Today note %d edited", item_id)
    return out


def change_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime, **changes) -> Outcome:
    """Change a task's fields from the browse tool, such as its title, description or labels."""
    before = Model(conn)
    logged = tasks.update_task(conn, settings, task_id, at=at, via=BROWSE, **changes)
    moved = tasks.moved_words(logged)
    out = Outcome((f"{len(logged)} change{'s' if len(logged) != 1 else ''} in the status log." if logged else "Nothing changed.") + (f" {moved}" if moved else ""), moved=moved)
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id, *(f.task for f in logged.followed)], before)
    return out


def mark_reviewed(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime) -> Outcome:
    """Mark reviewed, in the weekly review's step 4 (release 5.128, decision 498): the task keeps the time, its facts say
    "Reviewed Fri 13 Nov", and it leaves the step until its interval comes round. Nothing goes into the status log
    (decision 503); Undo is ``set_reviewed``."""
    from docrepo import review

    before = Model(conn)
    if task_id not in before.tasks:
        raise EditError(f"There's no task {task_id}.")
    tasks.set_reviewed(conn, {task_id: stamp(at)})
    m = Model(conn)
    t = m.task(task_id)
    weeks = review.interval(m, t, settings.review_weeks)
    nxt = review.next_review(t, weeks) if weeks else None
    again = f" It comes up again in the week of {long_date(nxt, at.date())}." if nxt else ""
    out = Outcome(f"{t.title}: reviewed.{again}")
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id], before)
    log.info("task %s marked reviewed", task_id)
    return out


def set_reviewed(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, reviewed: str | None, at: datetime) -> Outcome:
    """Mark reviewed's Undo (release 5.128): the task's last review as it was before."""
    before = Model(conn)
    tasks.set_reviewed(conn, {task_id: reviewed})
    out = Outcome(f"{Model(conn).task(task_id).title}: back to " + (f"reviewed {long_date(to_date(reviewed), at.date())}." if reviewed else "not reviewed yet."))
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id], before)
    return out


def set_states(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, states: dict[str, str], at: datetime) -> Outcome:
    """Set tasks' states from a row's state menu (release 5.76, round 7's item 101, decisions 362 to 364): each change a status
    log line as "Browse tool", as Edit task's are, with no capture, all in one transaction, and the pages written once. A
    whole branch closed at once is one change to take back, and so is its Undo."""
    logged = 0
    before = Model(conn)
    with transaction(conn):
        for task_id, state in states.items():
            logged += len(tasks.update_task(conn, settings, task_id, at=at, via=BROWSE, state=state))
    out = Outcome(f"{logged} change{'s' if logged != 1 else ''} in the status log." if logged else "Nothing changed.")
    write_touched_pages(conn, data_root, fs, at, out.problems, list(states), before)
    log.info("States set from a row: %d task(s), %d change(s)", len(states), logged)
    return out


def edit_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, at: datetime, **values) -> Outcome:
    """Save the Edit task form (mods log round 1, M0008, M0011): every field on one page, in one transaction.

    Only the fields that differ change, each logged as "Browse tool". ``leads`` and ``assignees`` are Who's: someone not on
    the people list is added to it, and a label not there yet is created. A Start left at the day the task was created
    stays unset. ``parents`` puts the task under exactly those tasks (mods log round 2, M0040), as one Parents change.
    ``priority`` (release 5.23) puts it in a bucket ("" for Not ranked), at the bucket's end, when that's a change.
    ``key_dates`` (release 5.31), a list of ``tasks.KeyDateRow``, makes its key dates those, each change logged.
    ``follow`` (release 5.45, decision 184), from the form's chain marks and ↺, says which fields follow its template now.
    ``leave`` (release 5.50, decision 249) names the tasks tied to it that keep their dates.
    """
    before = Model(conn)
    with transaction(conn):
        logged, added = _edit(conn, settings, task_id, at, values)
    message = f"{len(logged)} change{'s' if len(logged) != 1 else ''} in the status log." if logged else "Nothing changed."
    moved = tasks.moved_words(logged)
    if moved:
        message += f" {moved}"
    if added:
        message += f" Added {', '.join(added)} to the people list."
    out = Outcome(message, moved=moved)
    write_touched_pages(conn, data_root, fs, at, out.problems, [task_id, *(f.task for f in logged.followed)], before)
    log.info("task %s edited in the browse tool: %d changes", task_id, len(logged))
    return out


def _edit(conn: sqlite3.Connection, settings: Settings, task_id: str, at: datetime, values: dict) -> tuple[tasks.Logged, list[str]]:
    """The change ``edit_task`` makes, in the caller's transaction, with no file written, so it can be rolled back to ask first."""
    added: list[str] = []
    parents = values.pop("parents", None)
    key_dates = values.pop("key_dates", None)
    priority = values.pop("priority", None)
    follow = values.pop("follow", None)
    leave = values.pop("leave", ())
    with transaction(conn):
        t = tasks.get_task(conn, task_id)
        if values.get("start") == start_of(t).isoformat() and not t.start:
            values.pop("start")
        for name in values.get("labels", ()):
            if conn.execute("SELECT 1 FROM labels WHERE name = ?", (name.strip(),)).fetchone() is None:
                people.add_label(conn, name)
        note = f"Added on {at.date().isoformat()} in the browse tool. Aliases and hours aren't set yet."
        named: dict[str, str] = {}
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
                    named[w.name] = person_id
                values[key] = ids
        if values.get("involvement"):  # someone just added has their Involvement under their name until now
            values["involvement"] = {(role, named.get(p, p)): share for (role, p), share in values["involvement"].items()}
        logged = tasks.update_task(conn, settings, task_id, at=at, via=BROWSE, keep_links=follow is not None, leave=leave, **values)
        if follow is not None:
            logged += tasks.set_links(conn, task_id, follow, at=at, via=BROWSE)
        moved = tasks.set_parents(conn, task_id, parents, at=at, via=BROWSE) if parents is not None else None
        if moved:
            logged.append(moved)
        if priority is not None and priority != (t.priority or ""):
            ranked = priorities.place(conn, task_id, priority, at=at, via=BROWSE)
            if ranked:
                logged.append(ranked)
        if key_dates is not None:
            logged += tasks.set_key_dates(conn, task_id, key_dates, at=at, via=BROWSE, settings=settings, leave=leave)
    return logged, added


class _Preview(Exception):
    """Raised to roll a question's changes back."""


def _what_moves(conn: sqlite3.Connection, change: Callable[[], tasks.Logged]) -> list[tasks.Followed]:
    """What a change would move, made and then rolled back, so the owner can be asked first (decision 249)."""
    if conn.in_transaction:
        raise RuntimeError("A preview can't run inside another transaction: it couldn't be rolled back on its own.")
    found: list[tasks.Followed] = []
    try:
        with transaction(conn):
            found = list(change().followed)
            raise _Preview
    except _Preview:
        pass
    return found


def edit_moves(conn: sqlite3.Connection, settings: Settings, task_id: str, at: datetime, **values) -> list[tasks.Followed]:
    """What saving Edit task, or Quick edit, would move."""
    return _what_moves(conn, lambda: _edit(conn, settings, task_id, at, dict(values))[0])


def change_moves(conn: sqlite3.Connection, settings: Settings, task_id: str, at: datetime, **changes) -> list[tasks.Followed]:
    """What ``change_task`` would move."""
    return _what_moves(conn, lambda: tasks.update_task(conn, settings, task_id, at=at, via=BROWSE, **changes))


def key_dates_move(conn: sqlite3.Connection, settings: Settings, task_id: str, rows: list[tasks.KeyDateRow], at: datetime) -> list[tasks.Followed]:
    """What ``set_key_dates`` would move."""
    return _what_moves(conn, lambda: tasks.set_key_dates(conn, task_id, rows, at=at, via=BROWSE, settings=settings))


# ---- a what-if, applied (release 5.64, decision 226) ----
def apply_whatif(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, w: whatif.WhatIf, skip: Collection[int],
                 at: datetime) -> Outcome:
    """Review and apply: a what-if's things done, but those unticked (their places in ``skip``) and those whose tasks have changed
    since, made in one transaction, through the same calls as its picture, each in its task's status log as from the what-if."""
    m = Model(conn)
    leave = {*skip, *(i for i, a in enumerate(w.actions) if whatif.stale(m, a))}
    with transaction(conn):
        done = whatif.run(conn, settings, w.actions, at, whatif.via(w.name), leave)
    made = [d for d in done if d is not None and not d.problem]
    failed = [d.problem for d in done if d is not None and d.problem]
    followed = {x for d in made for x in d.followed} - {x for d in made for x in d.changed}
    message = f"Applied {len(made)} change{'' if len(made) == 1 else 's'} from {w.name}. Each is in its task's status log."
    if followed:
        message += f" Moved {len(followed)} tied task{'' if len(followed) == 1 else 's'} with them."
    out = Outcome(message)
    if failed:
        out.problems.append(f"{len(failed)} couldn't be made: {' '.join(failed)}")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("what-if applied: %d of %d changes", len(made), len(w.actions))
    return out


# ---- key dates (release 5.31, the key dates plan) ----
def set_key_dates(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, rows: list[tasks.KeyDateRow],
                  at: datetime, leave: Collection[str] = ()) -> Outcome:
    """Make a task's key dates these, in this order, from the browse tool: each change logged as "Browse tool"."""
    logged = tasks.set_key_dates(conn, task_id, rows, at=at, via=BROWSE, settings=settings, leave=leave)
    moved = tasks.moved_words(logged)
    out = Outcome((f"{len(logged)} change{'s' if len(logged) != 1 else ''} in the status log." if logged else "Nothing changed.") + (f" {moved}" if moved else ""), moved=moved)
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def set_key_date_done(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, key_id: int, done: bool, at: datetime) -> Outcome:
    """A key date's Done tick (decision 148), from Today, the list, the task page or the timeline's card."""
    task_id, logged = tasks.set_key_date_done(conn, key_id, done, at=at, via=BROWSE)
    title = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()["title"]
    out = Outcome(f"{'Done' if done else 'Not done'}: a key date of {title}." if logged else "Nothing changed.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def key_date_subtask(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, key_id: int, at: datetime) -> Outcome:
    """Make it a subtask (item 61): a subtask of its task, titled with its description, its Start and Due its dates (a
    Deadline when it's ticked as one, Plant event when it's a plant activity); the key date is taken off. Both logged."""
    r = conn.execute("SELECT * FROM task_dates WHERE id = ?", (key_id,)).fetchone()
    if r is None:
        raise EditError(f"There's no key date {key_id}.")
    parent = tasks.get_task(conn, r["task"])
    with transaction(conn):
        end = r["end_day"] or r["start_day"]
        child = tasks.create_task(conn, settings, title=r["description"] or f"{parent.title}: key date", at=at, created_by=BROWSE,
                                  parents=[parent.id], start=r["start_day"], due=end, deadline=end if r["deadline"] else None,
                                  plant_event=bool(r["plant"]))
        if r["done"]:  # a done key date makes a closed subtask, with its day closed
            tasks.update_task(conn, settings, child, at=at, via=BROWSE, state="Closed")
        tasks.set_key_dates(conn, parent.id, [x for x in tasks.key_date_rows(conn, parent.id) if x.id != key_id], at=at, via=BROWSE, settings=settings)
    out = Outcome(f"{child} is a subtask of {parent.title} now, in place of its key date.")
    write_all_pages(conn, data_root, fs, at, out.problems)
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
    """Move a task under another parent, add a parent, or take it out from under one: the Edit menu's Move…, Put under…,
    Also put under… and Remove from under…, saying which in the mock's words (release 5.118, decision 439)."""
    had = tasks.parent_links(conn, task_id)
    tasks.move_parent(conn, task_id, old_parent, new_parent, at=at, via=BROWSE)
    m = Model(conn)
    out = Outcome(moved_line(m, task_id, old_parent, new_parent, bool(had)))
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out


# ---- Tidy: follow-ups out of their meetings (release 5.142, the notes consolidation plan's decision 612) ----
@dataclass
class Tidy:
    """A follow-up still under the meeting whose notes made it, and the parents Tidy gives it: its others, with the
    meeting's home task added when none of them is the work (decision 610)."""

    task: str
    meeting: str
    parents: list[str]


def meetings_in(m: Model, task_id: str | None) -> list[str]:
    """The live meetings Tidy looks at: on a meeting's page, it and the meetings under it (a series' occurrences); on
    another task's, the meetings under it; with none, every meeting."""
    if task_id is None:
        ids = [t.id for t in m.tasks.values() if t.meeting and not t.discarded]
    else:
        ids = ([task_id] if task_id in m.tasks and m.task(task_id).meeting else []) + m.descendants_of(task_id)
    return [x for x in dict.fromkeys(ids) if x in m.tasks and m.task(x).meeting and not m.task(x).discarded]


def follow_ups_to_tidy(m: Model, meetings: Sequence[str]) -> list[Tidy]:
    """Each live task a meeting's notes made that's still under that meeting (decision 612), oldest first, with where it
    will go: off the meeting, and under its home task unless it has another parent that isn't a meeting. A meeting with
    nothing above it is its own home, so its follow-ups stay. A task the owner put under a meeting by hand isn't one."""
    from docrepo.save import follow_up_home

    out: list[Tidy] = []
    seen: set[str] = set()
    for meeting in meetings:
        notes = {c.id for c in m.captures.values() if c.item == "notes" and c.task == meeting and not c.discarded}
        home = follow_up_home(m, meeting)
        for c in sorted(m.captures.values(), key=lambda c: c.id):
            t = c.created_task
            if c.from_notes not in notes or c.item != "task" or c.discarded or t not in m.tasks or m.task(t).discarded or t in seen:
                continue
            parents = m.parents_of(t)
            if meeting not in parents:
                continue
            rest = [p for p in parents if p != meeting]
            if not any(p in m.tasks and not m.task(p).meeting for p in rest):
                if not home or home == meeting or home == t:
                    continue
                rest.append(home)
            seen.add(t)
            out.append(Tidy(t, meeting, list(dict.fromkeys(rest))))
    return out


def tidy_follow_ups(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, moves: Sequence[Tidy], at: datetime
                    ) -> tuple[Outcome, list[tuple[str, list[tuple[int, str]], list[tuple[int, str]]]]]:
    """Move follow-ups out of their meetings (decision 612), as one change: each a Parents line in its status log as
    "Browse tool". Returns what it said, and each task's parent links before and after, for Undo."""
    undo: list[tuple[str, list[tuple[int, str]], list[tuple[int, str]]]] = []
    with transaction(conn):
        for mv in moves:
            before = tasks.parent_links(conn, mv.task)
            tasks.set_parents(conn, mv.task, mv.parents, at=at, via=BROWSE)
            undo.append((mv.task, before, tasks.parent_links(conn, mv.task)))
    m = Model(conn)
    meetings = list(dict.fromkeys(mv.meeting for mv in moves))
    out_of = m.task(meetings[0]).title if len(meetings) == 1 else f"{len(meetings)} meetings"
    n = len(moves)
    out = Outcome(f"Moved {n} follow-up{'s' if n != 1 else ''} out of {out_of}.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("tidied %d follow-ups out of %d meetings", n, len(meetings))
    return out, undo


def undo_tidy(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, undo: Sequence[tuple[str, list[tuple[int, str]], list[tuple[int, str]]]],
              at: datetime) -> Outcome:
    """Tidy's Undo (decision 612, as 5.118's): each task back under exactly the parents it had, while they're still what
    Tidy left; one whose parents have changed since stays, and the line says so."""
    back, kept = 0, []
    with transaction(conn):
        for task_id, had, left in reversed(undo):
            try:
                tasks.restore_parents(conn, task_id, had, expect=left, at=at, via=BROWSE)
                back += 1
            except tasks.TaskError:
                kept.append(task_id)
    m = Model(conn)
    words = f"Set back: {back} follow-up{'s' if back != 1 else ''} under {'its meeting' if back == 1 else 'their meetings'} again."
    if kept:
        words += f" {', '.join(m.task(t).title for t in kept if t in m.tasks)} changed since, so stayed."
    out = Outcome(words)
    write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def moved_line(m: Model, task_id: str, old_parent: str | None, new_parent: str | None, had_parents: bool) -> str:
    """What the status line says after a move (the consolidation mock's words, decision 439): "Rigging plan moved from
    under Installation to Reactor impeller upgrade.", "… is under X now, out of Quick tasks.", "… is under X now." (a
    top-level task's first parent), "… is under X too.", "… is no longer under X." or "… is a top-level task now."."""
    name = m.task(task_id).title
    title = lambda p: m.task(p).title  # noqa: E731
    if new_parent is None:
        return f"{name} is no longer under {title(old_parent)}." if m.parents_of(task_id) and old_parent else f"{name} is a top-level task now."
    if old_parent is None:
        return f"{name} is under {title(new_parent)} {'too' if had_parents else 'now'}."
    if quick.is_parent(m.task(old_parent)):
        return f"{name} is under {title(new_parent)} now, out of Quick tasks."
    return f"{name} moved from under {title(old_parent)} to {title(new_parent)}."


def undo_move(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, links: list[tuple[int, str]],
              expect: list[tuple[int, str]], at: datetime) -> Outcome:
    """Undo after a move from the Edit menu (release 5.118, decisions 435 to 438): the task back under exactly the parents it
    had, in its old place (``links``, ``tasks.parent_links`` from before the move), while its links are still ``expect``,
    what the move left. One Parents line in the status log as "Browse tool", so the log keeps both changes."""
    tasks.restore_parents(conn, task_id, links, expect=expect, at=at, via=BROWSE)
    m = Model(conn)
    name, parents = m.task(task_id).title, [m.task(p).title for p in m.parents_of(task_id)]
    where = f"under {' and '.join(parents)} again" if parents else "a top-level task again"
    out = Outcome(f"Set back: {name} is {where}. The status log keeps both changes.")
    write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("task %s set back under %d parents", task_id, len(parents))
    return out
