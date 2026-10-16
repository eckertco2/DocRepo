"""A read-only snapshot of docs.db, and the questions DocRepo asks of it.

The generated pages, the lists and the capacity report all read from a ``Model``.
It loads every table at once, which is quick at DocRepo's scale (hundreds of
tasks), and keeps the rules in one place. The rules are ported from the mockup's
``model.js``. Changes are made by the write modules (``tasks``, ``people``,
``agenda``, ``captures``), never through a Model.
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

from docrepo.dates import long_date
from docrepo.schedule import due_of, is_open

TYPE_NAMES = {"note": "Note", "new_task": "New task", "update": "Update"}


@dataclass
class Task:
    id: str
    title: str
    state: str
    closed: str | None
    urgent: bool
    meeting: bool
    recurrence: str | None
    repeat_until: str | None
    start: str | None
    due: str | None
    deadline: str | None
    deadline_desc: str | None
    reminder: str | None
    lead_hours: float | None
    assignee_hours: float | None
    inherit_labels: bool
    description: str
    current_status: str
    created: str
    created_by: str
    leads: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


@dataclass
class Person:
    id: str
    name: str
    hours: float | None
    status: str
    added_note: str | None
    aliases: list[str] = field(default_factory=list)


@dataclass
class Label:
    id: int
    name: str
    status: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class CaptureDocument:
    document: str
    save_a_copy: bool
    extract: bool


@dataclass
class Capture:
    id: str
    saved: str
    source: str
    task: str | None
    types: list[str]
    created_task: str | None
    filed_to: str | None
    filed: str | None
    title: str
    summary: str | None
    summary_type: str | None
    edited: str | None
    documents: list[CaptureDocument] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)

    def has(self, capture_type: str) -> bool:
        return capture_type in self.types

    @property
    def document_ids(self) -> list[str]:
        return [d.document for d in self.documents]


@dataclass
class Document:
    id: str
    name: str
    description: str | None
    original: str | None
    capture: str | None
    status: str
    checked: str | None


@dataclass
class Version:
    id: int
    document: str
    at: str
    difference: str
    summary: str | None
    summary_type: str | None


@dataclass
class SavedCopy:
    id: int
    task: str
    name: str
    document: str
    from_capture: str | None
    replaced: str | None
    old: bool


@dataclass
class AgendaItem:
    id: int
    subject: str | None
    target: str
    note: str
    added: str
    added_by: str
    closed: str | None
    how: str | None
    closed_by: str | None


@dataclass(frozen=True)
class StatusEntry:
    """One line of a task's status log. A value of None shows as "None"."""

    task: str
    at: str
    field: str
    from_value: str | None
    to_value: str | None
    via: str
    target: str | None = None


@dataclass(frozen=True)
class RawEntry:
    """One raw text log entry: a capture, or a document version."""

    at: str
    capture: Capture | None = None
    version: Version | None = None


@dataclass(frozen=True)
class Summary:
    task: str
    at: str
    type: str | None
    text: str
    via: str


@dataclass(frozen=True)
class FileEntry:
    kind: str  # Saved copy, Old version, Tracked original or Email attachment
    name: str
    document: str
    task: str


def is_person(item_id: str | None) -> bool:
    return bool(item_id and re.match(r"P\d", item_id))


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


_TASK_COLUMNS = (
    "id, title, state, closed, urgent, meeting, recurrence, repeat_until, start, due, deadline, deadline_desc, reminder, "
    "lead_hours, assignee_hours, inherit_labels, description, current_status, created, created_by"
)


def load_tasks(conn: sqlite3.Connection, task_ids: Iterable[str] | None = None) -> dict[str, Task]:
    """Tasks with their leads, assignees and own labels, in ID order. All of them, or only ``task_ids``."""
    where, params = "", ()
    if task_ids is not None:
        params = tuple(task_ids)
        where = f" WHERE id IN ({','.join('?' * len(params))})" if params else " WHERE 0"
    tasks: dict[str, Task] = {}
    for r in conn.execute(f"SELECT {_TASK_COLUMNS} FROM tasks{where} ORDER BY id", params):
        tasks[r["id"]] = Task(**{k: r[k] for k in r.keys()})
        t = tasks[r["id"]]
        t.urgent, t.meeting, t.inherit_labels = bool(t.urgent), bool(t.meeting), bool(t.inherit_labels)
    for r in conn.execute("SELECT task, person, role FROM task_people ORDER BY id"):
        if r["task"] in tasks:
            (tasks[r["task"]].leads if r["role"] == "lead" else tasks[r["task"]].assignees).append(r["person"])
    for r in conn.execute("SELECT tl.task, l.name FROM task_labels tl JOIN labels l ON l.id = tl.label ORDER BY tl.id"):
        if r["task"] in tasks:
            tasks[r["task"]].labels.append(r["name"])
    return tasks


class Model:
    """Everything in docs.db, as of one moment."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        q = conn.execute
        self.tasks = load_tasks(conn)
        self.people: dict[str, Person] = {
            r["id"]: Person(r["id"], r["name"], r["hours_per_week"], r["status"], r["added_note"])
            for r in q("SELECT * FROM people ORDER BY id")
        }
        for r in q("SELECT person, alias FROM person_aliases ORDER BY person, pos"):
            self.people[r["person"]].aliases.append(r["alias"])
        labels = {r["id"]: Label(r["id"], r["name"], r["status"]) for r in q("SELECT * FROM labels ORDER BY id")}
        for r in q("SELECT label, keyword FROM label_keywords ORDER BY label, pos"):
            labels[r["label"]].keywords.append(r["keyword"])
        self.labels: list[Label] = list(labels.values())
        self.links: list[tuple[str, str]] = [(r["child"], r["parent"]) for r in q("SELECT child, parent FROM task_parents ORDER BY id")]
        self._parents: dict[str, list[str]] = {}
        self._children: dict[str, list[str]] = {}
        for child, parent in self.links:
            self._parents.setdefault(child, []).append(parent)
            self._children.setdefault(parent, []).append(child)
        self.captures: dict[str, Capture] = {}
        for r in q("SELECT * FROM captures ORDER BY id"):
            values = {k: r[k] for k in r.keys()}
            values["types"] = values["types"].split(",") if values["types"] else []
            self.captures[r["id"]] = Capture(**values)
        for r in q("SELECT * FROM capture_documents ORDER BY capture, pos"):
            self.captures[r["capture"]].documents.append(CaptureDocument(r["document"], bool(r["save_a_copy"]), bool(r["extract"])))
        for r in q("SELECT capture, name FROM capture_attachments ORDER BY capture, pos"):
            self.captures[r["capture"]].attachments.append(r["name"])
        self.documents: dict[str, Document] = {r["id"]: Document(**{k: r[k] for k in r.keys()}) for r in q("SELECT * FROM documents ORDER BY id")}
        self.versions: list[Version] = [Version(**{k: r[k] for k in r.keys()}) for r in q("SELECT * FROM document_versions ORDER BY id")]
        self.copies: list[SavedCopy] = [
            SavedCopy(r["id"], r["task"], r["name"], r["document"], r["from_capture"], r["replaced"], bool(r["old"]))
            for r in q("SELECT * FROM saved_copies ORDER BY id")
        ]
        self.agenda: list[AgendaItem] = [AgendaItem(**{k: r[k] for k in r.keys()}) for r in q("SELECT * FROM agenda_items ORDER BY id")]
        self.status: list[StatusEntry] = [
            StatusEntry(r["task"], r["at"], r["field"], r["from_value"], r["to_value"], r["via"])
            for r in q("SELECT * FROM status_log ORDER BY id")
        ]

    # ---- names ----
    def task(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def person_name(self, person_id: str) -> str:
        p = self.people.get(person_id)
        return p.name if p else person_id

    def target_name(self, target: str) -> str:
        """An agenda target's name: a person's name or a task's title."""
        if is_person(target):
            return self.person_name(target)
        return self.tasks[target].title if target in self.tasks else target

    def active_people(self) -> list[Person]:
        return [p for p in self.people.values() if p.status == "active"]

    def active_labels(self) -> list[Label]:
        return [label for label in self.labels if label.status == "active"]

    # ---- the tree ----
    def parents_of(self, task_id: str) -> list[str]:
        return self._parents.get(task_id, [])

    def children_of(self, task_id: str) -> list[str]:
        return self._children.get(task_id, [])

    def top_level(self) -> list[Task]:
        return [t for t in self.tasks.values() if not self.parents_of(t.id)]

    def _walk(self, task_id: str, step: Callable[[str], list[str]]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()

        def go(x: str) -> None:
            for y in step(x):
                if y not in seen:
                    seen.add(y)
                    out.append(y)
                    go(y)

        go(task_id)
        return out

    def ancestors_of(self, task_id: str) -> list[str]:
        return self._walk(task_id, self.parents_of)

    def descendants_of(self, task_id: str) -> list[str]:
        return self._walk(task_id, self.children_of)

    def chains_of(self, task_id: str) -> list[list[str]]:
        """Every chain from a top-level task down to this one."""
        parents = self.parents_of(task_id)
        if not parents:
            return [[task_id]]
        return [chain + [task_id] for p in parents for chain in self.chains_of(p)]

    def scope_ids(self, task_id: str, scope: str) -> list[str]:
        """The tasks a scope covers: self, ancestors, descendants or family (ancestors and descendants)."""
        ids = [task_id]
        if scope in ("ancestors", "family"):
            ids += self.ancestors_of(task_id)
        if scope in ("descendants", "family"):
            ids += self.descendants_of(task_id)
        return _unique(ids)

    def labels_of(self, task_id: str) -> list[tuple[str, bool]]:
        """The task's labels as (name, inherited): its own first, then those of every parent, unless it doesn't inherit."""
        t = self.tasks[task_id]
        out = [(name, False) for name in t.labels]
        if t.inherit_labels:
            for parent in self.parents_of(task_id):
                for name, _ in self.labels_of(parent):
                    if all(name != have for have, _ in out):
                        out.append((name, True))
        return out

    # ---- captures, documents and the raw text log ----
    def capture_tasks(self, c: Capture) -> list[str]:
        """The tasks a capture belongs to: the task it created; the task it picked, unless it only made a subtask
        there (New task without Update); and the task it was filed to."""
        out = []
        if c.created_task:
            out.append(c.created_task)
        if c.task and (not c.created_task or c.has("update")):
            out.append(c.task)
        if c.filed_to:
            out.append(c.filed_to)
        return _unique(out)

    def is_unfiled(self, c: Capture) -> bool:
        """No task, and no agenda item: it waits in the Unfiled view."""
        return not self.capture_tasks(c) and not any(a.added_by == c.id for a in self.agenda)

    def unfiled_captures(self) -> list[Capture]:
        return [c for c in self.captures.values() if self.is_unfiled(c)]

    def notes_of(self, task_id: str) -> list[Capture]:
        return [c for c in self.captures.values() if task_id in self.capture_tasks(c)]

    def document_holders(self, document_id: str) -> list[str]:
        """The tasks a document belongs to: those of the captures it came in with, and those it has saved copies in."""
        from_captures = [t for c in self.captures.values() if document_id in c.document_ids for t in self.capture_tasks(c)]
        return _unique(from_captures + [f.task for f in self.copies if f.document == document_id])

    def versions_of(self, task_id: str) -> list[Version]:
        return [v for v in self.versions if task_id in self.document_holders(v.document)]

    def raw_log_of(self, task_id: str) -> list[RawEntry]:
        """The task's raw text log, oldest first: its captures and its documents' versions."""
        entries = [RawEntry(c.saved, capture=c) for c in self.notes_of(task_id)]
        entries += [RawEntry(v.at, version=v) for v in self.versions_of(task_id)]
        return sorted(entries, key=lambda e: e.at)

    def summaries_of(self, task_id: str) -> list[Summary]:
        """The task's summary log, oldest first: pasted summaries from its captures and its documents' versions."""
        out = [Summary(task_id, c.saved, c.summary_type, c.summary, c.id)
               for c in self.captures.values() if c.summary and task_id in self.capture_tasks(c)]
        out += [Summary(task_id, v.at, v.summary_type, v.summary, v.document) for v in self.versions_of(task_id) if v.summary]
        return sorted(out, key=lambda s: s.at)

    def files_of(self, task_id: str) -> list[FileEntry]:
        """Every file connected to a task: its saved copies, then the documents of its captures."""
        out = [FileEntry("Old version" if f.old else "Saved copy", f.name, f.document, task_id) for f in self.copies if f.task == task_id]
        for doc_id in _unique(d for c in self.notes_of(task_id) for d in c.document_ids):
            d = self.documents[doc_id]
            out.append(FileEntry("Tracked original" if d.original else "Email attachment", d.name, doc_id, task_id))
        return out

    # ---- the status log ----
    def status_log_of(self, task_id: str) -> list[StatusEntry]:
        """The task's field changes, then its agenda items as they were added and closed."""
        out = [e for e in self.status if e.task == task_id]
        for a in self.agenda:
            if a.subject != task_id:
                continue
            name = self.target_name(a.target)
            out.append(StatusEntry(task_id, a.added, "Agenda", None, name, a.added_by, a.target))
            if a.closed:
                out.append(StatusEntry(task_id, a.closed, "Agenda", name, a.how, a.closed_by or "", a.target))
        return out

    # ---- agendas ----
    def open_items_for(self, target: str) -> list[AgendaItem]:
        return [a for a in self.agenda if a.target == target and not a.closed]

    def agendas_on(self, task_id: str) -> list[AgendaItem]:
        """The open agenda items that bring this task up."""
        return [a for a in self.agenda if a.subject == task_id and not a.closed]

    def open_meetings(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.meeting and is_open(t)]

    def agenda_targets(self) -> list[str]:
        """Open meetings first, then any other task or person with open items."""
        out = [t.id for t in self.open_meetings()]
        for a in self.agenda:
            if not a.closed and a.target not in out:
                out.append(a.target)
        return out

    def meeting_when(self, target: str, today: date) -> str:
        """When a task target next happens, such as "Tue 13 Oct"; "" for a person."""
        if is_person(target):
            return ""
        due = due_of(self.tasks[target], today)
        return long_date(due.date, today) if due else "no date set"
