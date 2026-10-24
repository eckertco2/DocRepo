"""Saving a capture from the capture window.

Everything that goes into docs.db happens in one transaction: new people and labels,
the new task or the update, the capture's record, its documents and saved copies,
and its agenda items. Then the files are written: capture.md, each document's
extracted text, the saved copies, an Outlook email's email.msg and attachments,
and the generated pages. A file that fails never undoes the capture; it's reported
in the result and the log.

Ported from the mockup's ``capture.js`` (``save``). SPEC section 7 describes it.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from docrepo import agenda, captures, edits, items, layer0, markup, people, quick, search, tasks
from docrepo.config import Settings
from docrepo.dates import long_date, short, stamp
from docrepo.db import next_id, transaction
from docrepo.extract import extract_text, file_info
from docrepo.links import NO_TEXT, is_link
from docrepo.model import TODAY, Model
from docrepo.pages import write_pages
from docrepo.parse import ParseLabel, ParsePerson, Who, parse_capture
from docrepo.safe_fs import SafeFS
from docrepo.text import capture_title, first_sentence, plain_text

log = logging.getLogger(__name__)

TYPE_ORDER = ("note", "new_task", "update")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class SaveError(ValueError):
    """The capture can't be saved as it is. ``focus`` names the field to fix: task, title, content or file:<n>."""

    def __init__(self, message: str, focus: str = "content") -> None:
        super().__init__(message)
        self.focus = focus


@dataclass
class Attachment:
    """An Outlook email's attachment. ``save`` writes it to a path (Outlook's SaveAsFile). Email layer 0 reads its size,
    its content ID (a picture in the body has one) and whether Outlook hides it."""

    name: str
    save: Callable[[Path], None]
    size: int = 0
    content_id: str = ""
    hidden: bool = False


@dataclass
class EmailItem:
    """An Outlook email added to a capture. ``save_msg`` writes it as a .msg file (Outlook's SaveAs)."""

    subject: str
    sender: str
    sent: str
    to: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)
    save_msg: Callable[[Path], None] | None = None
    refused: tuple[str, ...] = ()  # fields Outlook didn't give DocRepo, such as "Body"
    html: str = ""  # the HTML body, where email layer 0 finds the links and pictures

    def text(self) -> str:
        """The email as it goes into the content text: its header lines, then its body."""
        head = [f"From: {self.sender}", *([f"Sent: {self.sent}"] if self.sent else []), *([f"To: {self.to}"] if self.to else []),
                f"Subject: {self.subject}"]
        return "\n".join(head) + "\n\n" + self.body.strip()


@dataclass
class FileRow:
    """A file, link or email added to the capture, with its description and choices. ``path`` is its original: a file's
    path, or a link (``links.is_link``), which has nothing to copy or read, so its choices are always off.

    An email's row (``email``) holds its text and becomes email.msg; it has no description of its own. Each part email
    layer 0 finds in it (``part``: an attachment, a link or a picture) is a row of its own, ``of`` that email, kept only
    while ``keep`` is ticked (mods log round 1, M0024)."""

    name: str
    path: str | None = None
    description: str = ""
    save_a_copy: bool = False
    extract: bool = False
    email: EmailItem | None = None
    part: layer0.Part | None = None
    of: EmailItem | None = None
    keep: bool = True

    @property
    def described(self) -> bool:
        """Whether the row needs a description and becomes a document: not an email's own row, nor an unticked part."""
        return self.email is None and self.keep


def default_description(row: FileRow, task_title: str | None) -> str:
    """What a description left empty becomes (mods log round 2, M0041): "*task* – Attached document – *file name*", with
    "Attached link" or "Attached picture" for those, or just the file name when the capture has no task."""
    kind = "picture" if row.part and row.part.kind == "picture" else "link" if is_link(row.path) else "document"
    return f"{task_title.strip()} – Attached {kind} – {row.name}" if task_title and task_title.strip() else row.name


def email_rows(email: EmailItem) -> list[FileRow]:
    """An email's row, then a row for each part email layer 0 finds in it, ticked or not as layer 0 starts them."""
    return [FileRow(email.subject, email=email),
            *(FileRow(p.name, p.url or None, part=p, of=email, keep=p.keep) for p in layer0.find(email).parts)]


@dataclass
class NewTaskFields:
    title: str = ""
    labels: list[str] = field(default_factory=list)  # names; one that doesn't exist yet is created
    inherit_labels: bool = True
    leads: list[Who] = field(default_factory=list)  # people on the list, or new names to add
    assignees: list[Who] = field(default_factory=list)
    due: str | None = None
    deadline: str | None = None
    deadline_desc: str | None = None
    urgent: bool = False
    meeting: bool = False
    state: str = "Not started"
    start: str | None = None
    reminder: str | None = None
    recurrence: str | None = None
    repeat_until: str | None = None
    lead_hours: float | None = None
    assignee_hours: float | None = None
    plant_event: bool = False  # release 5.9
    references: dict[str, str] = field(default_factory=dict)  # reference field values by name (release 5.9)


@dataclass
class CaptureDraft:
    """Everything in the capture window when Save is pressed."""

    content: str = ""
    task: str | None = None
    types: set[str] = field(default_factory=lambda: {"note"})
    files: list[FileRow] = field(default_factory=list)
    agenda: list[str] = field(default_factory=list)  # agenda targets: task or person IDs
    summary: str = ""
    summary_type: str | None = None
    new_task: NewTaskFields = field(default_factory=NewTaskFields)
    #: The Update fields, prefilled with the task's values; only those that differ are changed.
    update: dict[str, Any] = field(default_factory=dict)
    #: Make it a task: the unfiled capture the new task is made from. It's filed to the new task; no new capture is kept.
    from_capture: str | None = None
    #: A quick task (mods log round 2, M0039): with no task picked, the new task goes under the built-in Quick tasks. A new
    #: task with no task picked that goes on Today is one too.
    quick: bool = False
    #: The content text is markup (mods log round 2, M0045; ``docrepo.markup``): it has formatting or lists.
    formatted: bool = False
    #: Meeting notes (release 5.8): the notes go on the meeting the picked task decides (``meeting_case``). This time's
    #: meeting of a regular meeting, or a new meeting, is made, named ``meeting_name`` (empty: the name it starts with).
    meeting: bool = False
    meeting_name: str = ""
    #: The meeting's agenda items ticked or unticked as discussed by hand, by ID; the rest follow the notes.
    agenda_ticks: dict[int, bool] = field(default_factory=dict)
    #: The item cards' changes, by item key: {"0": {"off": True}, "2": {"title": "…", "due": "2026-10-23"}}.
    item_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Names picked from the @ and # lists, or kept with their IDs in the text: {"@tom becker": "P003", "#rigging plan": "T000012"}.
    refs: dict[str, str] = field(default_factory=dict)

    def words(self) -> str:
        """The content text's words, without its marks: what titles, descriptions and Parse and populate read."""
        content = self.content.strip()
        return markup.to_plain(content).strip() if self.formatted else content

    def lines(self) -> str:
        """The content text's words, line for line with the content text as it's kept: what items are read from."""
        content = self.content.strip()
        return markup.to_plain(content) if self.formatted else content

    def agenda_shown(self) -> bool:
        """Add to agenda applies with New task, with Update on a picked task, or with no task picked."""
        return "new_task" in self.types or ("update" in self.types and bool(self.task)) or not self.task


@dataclass
class SaveResult:
    capture_id: str | None
    created_task: str | None
    updated_task: str | None
    changes: list[tasks.Change]
    added_people: list[str]
    message: str
    problems: list[str] = field(default_factory=list)
    agenda_targets: list[str] = field(default_factory=list)
    filed_capture: str | None = None  # Make it a task: the capture filed to the new task
    picked_task: str | None = None  # the task picked in the window
    # Release 5.8: the meeting the notes made, or went on; the items' captures; how many of each kind; agenda items discussed.
    meeting: str | None = None
    items: list[str] = field(default_factory=list)
    made: dict[str, int] = field(default_factory=dict)
    discussed: int = 0


def meeting_case(model: Model, task_id: str | None) -> str:
    """Which meeting the notes go on (release 5.8): "regular" (this time's meeting, made as a subtask of the picked
    regular meeting), "oneoff" (the picked one-off meeting, as it is) or "new" (a new meeting, under the picked task)."""
    t = model.tasks.get(task_id) if task_id else None
    return "new" if not t or not t.meeting else "regular" if t.recurrence else "oneoff"


def meeting_name(model: Model, task_id: str | None, today: date) -> str:
    """The name the meeting starts with: a regular meeting's with today's date, a one-off meeting's own, else none."""
    case = meeting_case(model, task_id)
    return f"{model.task(task_id).title} {short(today, today)}" if case == "regular" else model.task(task_id).title if case == "oneoff" else ""


def item_names(model: Model, settings: Settings, refs: dict[str, str] | None = None) -> items.Names:
    """The people and tasks the content text's operators can name."""
    return items.names_of(model, _parse_people(model, settings), refs)


def copy_name(day: str, name: str, taken: set[str]) -> str:
    """A saved copy's file name: "YYYY-MM-DD name", cleaned of characters Windows forbids, at most 100 characters, and unique."""
    stem, dot, ext = _FORBIDDEN.sub("", name).rpartition(".")
    if not dot:
        stem, ext = ext, ""
    ext = f".{ext}" if ext else ""
    base = f"{day} {stem}".rstrip(". ")[: 100 - len(ext)].rstrip(". ")
    candidate, n = base + ext, 2
    while candidate.lower() in {t.lower() for t in taken}:
        candidate = f"{base[: 100 - len(ext) - 4]} ({n}){ext}"
        n += 1
    return candidate


def quick_task_draft(model: Model, settings: Settings, line: str, today: date, on_today: bool = True) -> CaptureDraft:
    """A quick task from one line (mods log round 2, M0039): Parse and populate reads it as a new task, so "Call the vendor
    about seals by Fri" gets its title and Due date. Only people already on the list are kept: a one-liner adds no one.
    ``on_today`` puts it on Today; Make it a task, on a note already there, leaves that to the note's own item."""
    r = parse_capture(line, "new_task", today, _parse_people(model, settings), _parse_labels(model), settings.event_words)

    def iso(d: date | None) -> str | None:
        return d.isoformat() if d else None

    fields = NewTaskFields(
        title=r.title or first_sentence(plain_text(line)) or line.strip(), labels=list(r.labels), leads=[w for w in r.leads if w.id],
        assignees=[w for w in r.assignees if w.id], due=iso(r.due), deadline=iso(r.deadline), deadline_desc=r.deadline_desc or None,
        reminder=iso(r.reminder), start=iso(r.start), recurrence=r.recurrence or None, urgent=r.urgent,
        lead_hours=float(r.lead_hours) if r.lead_hours else None, assignee_hours=float(r.assignee_hours) if r.assignee_hours else None,
    )
    return CaptureDraft(content=line.strip(), types={"new_task"}, agenda=[TODAY] if on_today else [], new_task=fields, quick=True)


def _and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _check(draft: CaptureDraft, task_exists: bool) -> None:
    is_new, is_upd = "new_task" in draft.types, "update" in draft.types
    content = draft.words()
    has_body = bool(content or draft.files)
    targets = draft.agenda if draft.agenda_shown() else []
    if draft.task and not task_exists:
        raise SaveError(f"There's no task {draft.task}.", "task")
    if is_new and not draft.new_task.title.strip() and not content and not any(f.email for f in draft.files):
        raise SaveError("A new task needs a title or some content text.", "title")
    if is_upd and not draft.task:
        raise SaveError("Pick a task to update first.", "task")
    if not draft.types:
        raise SaveError("Check Note, New task or Update.", "content")
    if not is_new and not is_upd and not has_body:
        raise SaveError("There's nothing to save yet. Type or paste something, or add a file or an email.", "content")
    if targets and not is_new and not is_upd and not draft.task and not content:
        raise SaveError("A note on an agenda needs some content text: it's what goes on the agenda.", "content")


def save_capture(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, draft: CaptureDraft, at: datetime) -> SaveResult:
    """Save what's in the capture window. Raises SaveError, changing nothing, if something is missing."""
    if draft.from_capture:
        draft.types = {"new_task"}
    for row in draft.files:
        if is_link(row.path):
            row.save_a_copy = row.extract = False  # DocRepo keeps only a link's address (mods log round 1, M0001)
        if row.part and row.part.kind == "picture":
            row.extract = False  # a picture has no text to read
    if draft.meeting:
        draft.types, draft.agenda = {"note"}, []  # meeting notes are a note on the meeting
    is_new, is_upd, is_note = ("new_task" in draft.types, "update" in draft.types, "note" in draft.types)
    t = draft.task
    task_row = conn.execute("SELECT title FROM tasks WHERE id = ?", (t,)).fetchone() if t else None
    _check(draft, task_row is not None)
    model0 = Model(conn)
    case = meeting_case(model0, t) if draft.meeting else ""
    meet_name = (draft.meeting_name.strip() or meeting_name(model0, t, at.date())) if draft.meeting else ""
    if draft.meeting and not meet_name:
        raise SaveError("Name the meeting first: Save makes it as a task.", "meeting")
    words = draft.words()
    formatted = draft.formatted and bool(words)
    content = draft.content.strip() if formatted else words
    emails = [f.email for f in draft.files if f.email]
    # Items (release 5.8): read from the content text's words, never from an email. capture.md keeps each @ and # with
    # its ID; titles read the words without the operators.
    names = item_names(model0, settings, draft.refs)
    reading = None if draft.from_capture else items.read(
        draft.lines(), names, at.date(), labels=_parse_labels(model0), events=settings.event_words,
        home=bool(t) or is_new or draft.meeting, new_task=is_new, overrides=draft.item_overrides)
    own = items.self_fields(reading, names) if reading and is_new else None
    # capture.md keeps the markup, with each email's text escaped so it reads as itself; the rest reads the words.
    full_content = "\n\n".join([items.store(content, names, formatted)] * bool(content)
                               + [markup.escape(e.text()) if formatted else e.text() for e in emails])
    full_words = "\n\n".join([words] * bool(words) + [e.text() for e in emails])
    title_words = "\n\n".join([items.words(words, names)] * bool(words) + [e.text() for e in emails])
    summary = draft.summary.strip()
    targets = list(dict.fromkeys(draft.agenda)) if draft.agenda_shown() else []
    keep = bool(content or draft.files or summary) and not draft.from_capture
    when, day = stamp(at), at.date().isoformat()
    source_capture = Model(conn).captures.get(draft.from_capture) if draft.from_capture else None
    if draft.from_capture and source_capture is None:
        raise SaveError(f"There's no capture {draft.from_capture}.", "content")
    # Make it a task rewrites the capture's own capture.md, with its own content text, not the window's.
    source_content = captures.read_content(data_root, source_capture) if source_capture else None
    filed_copies: list[tuple[str, str]] = []
    added_people: list[str] = []
    documents: list[tuple[str, FileRow, Attachment | None]] = []  # (document ID, its row, the attachment it came from)
    copies: list[tuple[str, str]] = []  # (document ID, file name) for saved copies
    changes: list[tasks.Change] = []
    created = None
    quick_task = is_new and not t and not draft.from_capture and (draft.quick or TODAY in targets)
    holder_title = task_row["title"] if task_row else None  # the task the files belong to, for descriptions left empty
    with transaction(conn):
        capture_id = next_id(conn, "C") if keep else None
        via = capture_id or draft.from_capture or "Capture window"

        def person(w: Who) -> str:
            if w.id:
                return w.id
            note = f"Added on {day} {'from ' + capture_id if capture_id else 'in the capture window'}. Aliases and hours aren't set yet."
            person_id, new = people.find_or_add(conn, w.name, note)
            if new:
                added_people.append(w.name.strip())
            return person_id

        if is_new:
            nt = draft.new_task
            for name in nt.labels:
                if conn.execute("SELECT 1 FROM labels WHERE name = ?", (name.strip(),)).fetchone() is None:
                    people.add_label(conn, name)
            source = full_words
            # With operators on its first line (release 5.8), that line without them gives the title, and its @ and #
            # fill the new task's people and parents.
            title = (nt.title.strip() or _parsed_title(conn, own.text if own and own.any else title_words, at, settings)
                     or first_sentence(plain_text(title_words)) or "Untitled task")
            holder_title = title
            parents = [t] if t else [quick.ensure_parent(conn, settings, at)] if quick_task else []
            parents += [p for p in (own.tasks if own else []) if p not in parents]
            leads = list(dict.fromkeys([person(w) for w in nt.leads] + [person(x.who()) for x in (own.leads if own else [])]))
            assignees = list(dict.fromkeys([person(w) for w in nt.assignees] + [person(x.who()) for x in (own.assignees if own else [])]))
            created = tasks.create_task(
                conn, settings, title=title, at=at, created_by=via, parents=parents, description=plain_text(source),
                state=nt.state, start=nt.start if nt.start and nt.start != day else None, due=nt.due, deadline=nt.deadline,
                deadline_desc=nt.deadline_desc, reminder=nt.reminder, recurrence=nt.recurrence, repeat_until=nt.repeat_until,
                urgent=nt.urgent, meeting=nt.meeting, leads=leads, assignees=assignees,
                lead_hours=nt.lead_hours, assignee_hours=nt.assignee_hours, labels=nt.labels, inherit_labels=nt.inherit_labels,
                plant_event=nt.plant_event, references=nt.references,
            )
        # Meeting notes (release 5.8): this time's meeting of a regular meeting, or a new meeting, is made first, and
        # the notes go on it. It stays In progress until it's closed by hand.
        agenda_task = t if draft.meeting and case != "new" else None  # the meeting whose agenda the notes worked through
        meeting_made = None
        if draft.meeting and case != "oneoff":
            meeting_made = tasks.create_task(
                conn, settings, title=meet_name, at=at, created_by=via, parents=[t] if t else [], state="In progress", meeting=True, due=day,
                description=f"{task_row['title'] + ', ' if task_row else ''}{long_date(at.date(), at.date())}. Its notes are in its raw text log.")
            t = meeting_made
            holder_title = meet_name
        if source_capture and created:
            filed_copies = edits.file_capture_records(conn, source_capture.id, created, at)
            if summary and not source_capture.summary:
                conn.execute("UPDATE captures SET summary = ?, summary_type = ? WHERE id = ?", (summary, draft.summary_type, source_capture.id))
        if is_upd and t:
            update = dict(draft.update)
            for key in ("leads", "assignees"):
                if key in update:
                    update[key] = [person(w) if isinstance(w, Who) else w for w in update[key]]
            changes = tasks.update_task(conn, settings, t, at=at, via=via, **update)
            if not is_new and not keep and not changes and not targets:
                raise SaveError("There's nothing to save yet. Change a field, add an agenda, or type the update in the content text.", "content")
        if capture_id:
            first_file = next((f.name for f in draft.files if f.described), None)
            source_kind = "outlook_email" if emails else "file_path" if any(not is_link(f.path) for f in draft.files) else "typed"
            captures.add_capture(
                conn, capture_id=capture_id, saved=when, source=source_kind,
                types=[k for k in TYPE_ORDER if k in draft.types and (k != "update" or t)],
                title=f"Notes of {meet_name}" if draft.meeting else capture_title(source_kind, title_words, first_file, capture_id),
                task=t, created_task=created, formatted=formatted,
                summary=summary or None, summary_type=draft.summary_type if summary else None,
                email_layer_0=" ".join(email_layer0_line(e, draft.files) for e in emails) or None,
                item="notes" if draft.meeting else None, meeting=meeting_made,
            )
            for row in draft.files:
                if not row.described:
                    continue  # an email's own row is its text and email.msg; an unticked part is left out
                desc = row.description.strip() or default_description(row, holder_title)
                row.description = desc
                if row.part and row.part.attachment:
                    # An email's attachment or picture (email layer 0): saved in the capture's attachments folder.
                    a = row.part.attachment
                    doc = captures.add_document(conn, name=a.name, description=desc, capture=capture_id)
                    captures.add_attachment(conn, capture_id, a.name)
                    captures.link_document(conn, capture_id, doc, save_a_copy=row.save_a_copy, extract=row.extract)
                    documents.append((doc, row, a))
                    continue
                link = is_link(row.path)  # a link is matched exactly; a path in any case, as Windows does
                same = "original = ?" if link else "lower(original) = lower(?)"
                existing = conn.execute(f"SELECT id FROM documents WHERE {same}", (row.path,)).fetchone()
                if existing:
                    doc = str(existing["id"])
                    conn.execute("UPDATE documents SET description = ? WHERE id = ?", (desc, doc))
                else:
                    doc = captures.add_document(conn, name=row.name, description=desc, original=row.path)
                    if link:
                        conn.execute("UPDATE documents SET text_status = 'none', text_note = ? WHERE id = ?", (NO_TEXT, doc))
                if conn.execute("SELECT 1 FROM capture_documents WHERE capture = ? AND document = ?", (capture_id, doc)).fetchone():
                    continue
                captures.link_document(conn, capture_id, doc, save_a_copy=row.save_a_copy, extract=row.extract)
                documents.append((doc, row, None))
            # Save a copy goes into the task's Files folder now, or when an unfiled capture is filed.
            holder = created or t
            if holder:
                taken = {r["name"] for r in conn.execute("SELECT name FROM saved_copies WHERE task = ?", (holder,))}
                for doc, row, _ in documents:
                    if row.save_a_copy:
                        name_row = conn.execute("SELECT name FROM documents WHERE id = ?", (doc,)).fetchone()
                        name = copy_name(day, name_row["name"], taken)
                        taken.add(name)
                        captures.add_saved_copy(conn, task=holder, name=name, document=doc, from_capture=capture_id)
                        copies.append((doc, name))
        subject = created if is_new else t if is_upd else None
        note_text = "" if is_new else plain_text(words)
        for target in targets:
            agenda.add_item(conn, subject=subject, target=target, note=note_text, added=when, added_by=via)
        item_files: list[tuple[str, str, bool]] = []  # (item capture, its block, whether it's markup)
        made: dict[str, int] = {}
        if capture_id and reading:
            item_files, made = _save_items(conn, settings, reading, names, content, formatted, capture_id, created or t, when, at, person)
        # Meeting notes: the agenda items the notes worked through close as Discussed.
        discussed = 0
        if agenda_task and capture_id:
            for a in Model(conn).open_items_for(agenda_task):
                if draft.agenda_ticks.get(a.id, items.discussed(reading, a.subject) if reading else False):
                    agenda.close_item(conn, a.id, how="Discussed", closed=when, closed_by=capture_id)
                    discussed += 1

    result = SaveResult(capture_id, created, t if is_upd else None, changes, added_people, "", agenda_targets=targets,
                        filed_capture=source_capture.id if source_capture else None, picked_task=draft.task,
                        meeting=t if draft.meeting else None, items=[cid for cid, _, _ in item_files], made=made, discussed=discussed)
    if capture_id:
        model = Model(conn)
        if names.people != (now := _parse_people(model, settings)):  # someone was added: their @ is kept with their ID too
            names = items.names_of(model, now, draft.refs)
            full_content = "\n\n".join([items.store(content, names, formatted)] * bool(content)
                                       + [markup.escape(e.text()) if formatted else e.text() for e in emails])
        _write_files(conn, data_root, fs, settings, capture_id, full_content, emails, documents, copies, created or t, result)
        for cid, block, block_formatted in item_files:
            try:
                fs.makedirs(captures.capture_folder(data_root, cid, model.captures[cid].saved))
                captures.write_capture_md(fs, data_root, model, cid, items.store(block, names, block_formatted))
            except OSError as e:
                result.problems.append(f"{cid}'s capture.md couldn't be written ({type(e).__name__}).")
        search.index_items(conn, data_root, captures=[capture_id, *result.items], documents=[d for d, _, _ in documents])
    if source_capture and created:
        edits.rewrite_capture_md(conn, data_root, fs, source_capture.id, source_content, result.problems)
        edits.copy_files(conn, data_root, fs, created, filed_copies, result.problems)
        search.index_items(conn, data_root, captures=[source_capture.id])
    try:
        write_pages(Model(conn), data_root, fs, at.date(), at)
    except OSError as e:
        result.problems.append(f"The generated pages weren't all updated ({type(e).__name__}).")
    result.message = _message(conn, draft, result, targets, bool(draft.new_task.title.strip()))
    log.info("capture %s saved: %s", capture_id or "(none kept)", _log_line(draft, result, targets, [d for d, _, _ in documents]))
    return result


def _save_items(conn: sqlite3.Connection, settings: Settings, reading: items.Reading, names: items.Names, content: str, formatted: bool,
                notes_id: str, home: str | None, when: str, at: datetime, person: Callable[[Who], str]) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Each ticked item as a small capture of its own, linked to the notes (release 5.8). A task item makes its task,
    under the capture's task (or meeting, or new task) and its # tasks; a note, an update or a decision is filed to each
    of its tasks. Returns each item's capture with its block as written (and whether that's markup), and how many of
    each kind were made."""
    lines = content.split("\n")
    files: list[tuple[str, str, bool]] = []
    made: dict[str, int] = {}
    item_task: dict[str, str] = {}  # a task item's task, by its key, for the items listed under it
    day = at.date().isoformat()
    for it in (x for x in reading.items if x.on):
        block = "\n".join(lines[n] for n in it.lines if n < len(lines))
        block_formatted = formatted and markup.is_formatted(block)
        text = block if block_formatted or not formatted else markup.to_plain(block)
        where: list[str] = []
        for w in it.where:
            ref = (quick.ensure_parent(conn, settings, at) if w.kind == "quick" else home if w.kind == "home"
                   else item_task.get(w.ref or "") if w.kind == "item" else w.ref)
            if ref and ref not in where:
                where.append(ref)
        title = it.title or items.KIND_NAMES[it.kind]
        if it.kind == "task":
            cid = next_id(conn, "C")
            task_id = tasks.create_task(
                conn, settings, title=title, at=at, created_by=cid, parents=where, description=it.text, due=it.due, deadline=it.deadline,
                deadline_desc=it.deadline_desc or None, reminder=it.reminder, recurrence=it.recurrence or None,
                start=it.start if it.start and it.start != day else None, urgent=it.urgent, leads=[person(x.who()) for x in it.leads],
                assignees=[person(x.who()) for x in it.assignees], lead_hours=float(it.lead_hours) if it.lead_hours else None,
                assignee_hours=float(it.assignee_hours) if it.assignee_hours else None, labels=it.labels, plant_event=it.plant_event)
            item_task[it.key] = task_id
            captures.add_capture(conn, capture_id=cid, saved=when, source="typed", types=["new_task"], title=title, task=where[0] if where else None,
                                 created_task=task_id, formatted=block_formatted, from_notes=notes_id, item="task")
            files.append((cid, text, block_formatted))
        else:
            for task_id in where:
                cid = next_id(conn, "C")
                if it.kind == "update":
                    changes = {"state": it.state} if it.state else {}
                    if it.text:
                        changes["current_status"] = it.text
                    tasks.update_task(conn, settings, task_id, at=at, via=cid, **changes)
                captures.add_capture(conn, capture_id=cid, saved=when, source="typed", types=["update" if it.kind == "update" else "note"],
                                     title=title, task=task_id, formatted=block_formatted, from_notes=notes_id, item=it.kind)
                files.append((cid, text, block_formatted))
        made[it.kind] = made.get(it.kind, 0) + 1
    return files, {k: made[k] for k in items.KIND_NAMES if k in made}


def add_quick_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, line: str, at: datetime) -> SaveResult:
    """A quick task on Today from Today's box (mods log round 2, M0039): a capture of the one line, which makes the task
    under Quick tasks and puts it on Today."""
    if not line.strip():
        raise SaveError("Type the task first.", "content")
    return save_capture(conn, data_root, fs, settings, quick_task_draft(Model(conn), settings, line, at.date()), at)


def note_to_task(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, item_id: int, at: datetime) -> SaveResult:
    """Make it a task, on a note on Today (mods log round 2, M0040): the note's text makes a quick task, which takes the
    note's place on Today, so it still carries over from the day the note was added."""
    a = next((x for x in Model(conn).agenda if x.id == item_id), None)
    if a is None or a.target != TODAY or a.subject or a.closed:
        raise SaveError("That isn't an open note on Today.", "content")
    result = save_capture(conn, data_root, fs, settings, quick_task_draft(Model(conn), settings, a.note, at.date(), on_today=False), at)
    agenda.make_task(conn, item_id, result.created_task)
    try:
        write_pages(Model(conn), data_root, fs, at.date(), at)
    except OSError as e:
        result.problems.append(f"The generated pages weren't all updated ({type(e).__name__}).")
    result.message += " It's on Today in the note's place."
    return result


def email_layer0_line(email: EmailItem, rows: list[FileRow]) -> str:
    """Email layer 0's line for one email: the parts its rows kept, and what it and the unticked rows left out."""
    parts = [r for r in rows if r.of is email and r.part]
    return layer0.line(layer0.find(email), [r.part.kind for r in parts if r.keep], sum(not r.keep for r in parts))


def _parsed_title(conn: sqlite3.Connection, source: str, at: datetime, settings: Settings) -> str:
    """The title Parse and populate would give, when the Title box was left empty."""
    model = Model(conn)
    found = parse_capture(source, "new_task", at.date(), _parse_people(model, settings), _parse_labels(model), settings.event_words)
    return found.title


def _parse_people(model: Model, settings: Settings) -> list[ParsePerson]:
    return [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == settings.me) for p in model.people.values()]


def _parse_labels(model: Model) -> list[ParseLabel]:
    return [ParseLabel(label.name, tuple(label.keywords)) for label in model.active_labels()]


def _write_files(
    conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, capture_id: str, content: str, emails: list[EmailItem],
    documents: list[tuple[str, FileRow, Attachment | None]], copies: list[tuple[str, str]], holder: str | None, result: SaveResult,
) -> None:
    """Write the capture's files. Each step that fails is noted in ``result.problems`` and the log, and the rest go on."""
    model = Model(conn)
    folder = captures.capture_folder(data_root, capture_id, model.captures[capture_id].saved)
    try:
        fs.makedirs(folder)
        captures.write_capture_md(fs, data_root, model, capture_id, content)
    except OSError as e:
        result.problems.append(f"capture.md couldn't be written ({type(e).__name__}).")
    for email in emails:
        if email.save_msg:
            try:
                email.save_msg(fs.checked_path(folder / "email.msg"))
            except Exception as e:  # noqa: BLE001 - Outlook can fail in many ways; the capture stays saved
                result.problems.append(f"The email couldn't be saved as email.msg ({type(e).__name__}).")
                log.warning("capture %s: email.msg not saved: %s", capture_id, type(e).__name__)
    sources: dict[str, Path] = {}
    for doc, row, attachment in documents:
        if attachment:
            target = fs.checked_path(folder / "attachments" / attachment.name)
            try:
                fs.makedirs(target.parent)
                attachment.save(target)
                sources[doc] = target
            except Exception as e:  # noqa: BLE001
                result.problems.append(f"The attachment {attachment.name} couldn't be saved ({type(e).__name__}).")
                continue
        elif row.path and not is_link(row.path):
            sources[doc] = Path(row.path)
    for doc, source in sources.items():
        _record_text(conn, data_root, fs, settings, doc, source, result)
    for doc, name in copies:
        source = sources.get(doc)
        if not source or not holder:
            continue
        try:
            fs.copy_file(source, data_root / "Tasks" / holder / "Files" / name)
        except (OSError, FileExistsError) as e:
            result.problems.append(f"The copy of {source.name} couldn't be saved ({type(e).__name__}).")
            log.warning("capture %s: saved copy %s failed: %s", capture_id, name, type(e).__name__)


def _record_text(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, doc: str, source: Path, result: SaveResult) -> None:
    """Pull a document's plain text into Documents/<id>/extracted.txt, and note its size, time and checksum."""
    try:
        info = file_info(source)
    except OSError as e:
        result.problems.append(f"{source.name} couldn't be opened ({type(e).__name__}), so its text wasn't saved.")
        conn.execute("UPDATE documents SET text_status = 'error', text_note = ? WHERE id = ?", (f"couldn't open it ({type(e).__name__})", doc))
        return
    found = extract_text(source, settings.extracted_text_cap_chars)
    if found.text:
        try:
            fs.write_text(data_root / "Documents" / doc / "extracted.txt", found.text)
        except OSError as e:
            result.problems.append(f"The text of {source.name} couldn't be saved ({type(e).__name__}).")
    if found.status in ("none", "error"):
        result.problems.append(f"{source.name}: {found.note}.")
    with transaction(conn):
        conn.execute(
            "UPDATE documents SET text_status = ?, text_chars = ?, text_note = ?, size = ?, modified = ?, sha256 = ?, checked = ? WHERE id = ?",
            (found.status, len(found.text), found.note or None, info.size, info.modified, info.sha256, stamp(datetime.now()), doc),
        )


def _message(conn: sqlite3.Connection, draft: CaptureDraft, r: SaveResult, targets: list[str], typed_title: bool) -> str:
    """What Save did, in a sentence or two, for the notification."""
    model = Model(conn)
    t = model.tasks.get(draft.task) if draft.task else None
    bits = []
    if r.created_task and r.filed_capture:
        new = model.task(r.created_task)
        bits.append(f"Created {new.id}, {new.title}{f', under {t.title}' if t else ''}, and filed {r.filed_capture} to it.")
    elif r.created_task:
        new = model.task(r.created_task)
        under = t.title if t else model.task(model.parents_of(new.id)[0]).title if model.parents_of(new.id) else ""  # a quick task's
        bits.append(f"Created {new.id}, {new.title}{f', under {under}' if under else ''}." + ("" if typed_title else " The title came from the content text."))
    if r.updated_task and t:
        n = len(r.changes)
        bits.append(f"{n} change{'s' if n != 1 else ''} in the status log of {t.title}." if n else f"Added to the status log of {t.title}." if r.capture_id else "")
    if "note" in draft.types and not r.created_task and not r.updated_task and not r.meeting:
        bits.append(f"Added to the raw text log of {t.title}." if t else "" if targets else "Kept as an unfiled capture, listed under Unfiled.")
    if targets:
        others = [model.target_name(x) for x in targets if x != TODAY]
        bits.append("On " + " and ".join(["Today"] * (TODAY in targets) + [f"the agenda of {_and_list(others)}"] * bool(others)) + ".")
    # Meeting notes and items (release 5.8).
    if r.meeting:
        m = model.task(r.meeting)
        if r.meeting != draft.task:
            bits.insert(0, f"Made the meeting {m.title}{f', under {t.title}' if t else ''}.")
        bits.append(f"Added to the raw text log of {m.title}.")
    counts = [f"{n} {items.KIND_NAMES[k].lower()}{'s' if n > 1 else ''}" for k, n in r.made.items() if n]
    if counts:
        bits.append(f"Made {_and_list(counts)} from its items.")
    if r.discussed:
        bits.append(f"{r.discussed} agenda item{'s' if r.discussed > 1 else ''} closed as Discussed.")
    text = (f"Saved {r.capture_id}. " if r.capture_id else "") + " ".join(b for b in bits if b)
    if r.added_people:
        text += f" Added {' and '.join(r.added_people)} to people."
    return text.strip()


def _log_line(draft: CaptureDraft, r: SaveResult, targets: list[str], documents: list[str]) -> str:
    """The log's account of a save: IDs and counts only, never content."""
    parts = []
    if r.created_task:
        parts.append(f"new task {r.created_task}" + (f" under {draft.task}" if draft.task else ""))
    if r.updated_task:
        parts.append(f"update to {r.updated_task}, {len(r.changes)} changes")
    if "note" in draft.types and draft.task and not r.created_task and not r.updated_task:
        parts.append(f"raw text log of {draft.task}")
    if targets:
        parts.append(f"agenda items for {', '.join(targets)}")
    if documents:
        parts.append(f"documents {', '.join(documents)}")
    if r.meeting:
        parts.append(f"meeting {r.meeting}")
    if r.items:
        parts.append(f"items {', '.join(r.items)}")
    if r.discussed:
        parts.append(f"{r.discussed} agenda items discussed")
    if r.problems:
        parts.append(f"{len(r.problems)} problems with files")
    return "; ".join(parts) or "unfiled"
