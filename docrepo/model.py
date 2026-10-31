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
from docrepo.links import is_link
from docrepo.schedule import due_of, is_open, start_of

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
    #: When it was discarded, and why (mods log round 1, M0021). A discarded task is hidden, never deleted.
    discarded: str | None = None
    discard_reason: str | None = None
    #: A plant event (mods log round 2, M0028): an outage or turnaround, drawn as a band across the timeline.
    plant_event: bool = False
    #: Its priority (mods log round 2, M0029, M0030, release 5.23): a bucket (``priorities.BUCKETS``) and its place in it.
    priority: str | None = None
    priority_rank: int | None = None
    #: Whether new captures go under a heading for their day on its notes page (release 5.25, decision 119): None is the
    #: default, which is on for a meeting and off for any other task (``uses_day_headings``).
    day_headings: bool | None = None
    #: Release 5.46 (decisions 189 to 191): its length in days, kept when its dates move, whether those days run through
    #: weekends, and each role's hours a day. With a rate, ``lead_hours`` or ``assignee_hours`` is the total worked out from it.
    duration: int | None = None
    calendar_days: bool = False
    lead_per_day: float | None = None
    assignee_per_day: float | None = None
    #: Release 5.49 (decision 260): each role's hours a week, instead of a day. A role has one rate at most.
    lead_per_week: float | None = None
    assignee_per_week: float | None = None
    leads: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    #: Its reference fields (M0034), named in Settings, such as a change record's number: {name: value}.
    references: dict[str, str] = field(default_factory=dict)
    #: Release 5.47 (decision 196): each person's Involvement where it isn't 100: {(role, person): percent}, role being "lead" or "assignee".
    involvement: dict[tuple[str, str], int] = field(default_factory=dict)
    #: Release 5.50 (decision 245): its Start or Due set from another date: {"start": Tie, "due": Tie}.
    ties: dict[str, Tie] = field(default_factory=dict)

    def rate_of(self, role: str) -> tuple[float, str] | None:
        """A role's rate and what it's per, ``(6.0, "day")`` or ``(3.0, "week")``, or None when its hours are a total."""
        day, week = (self.lead_per_day, self.lead_per_week) if role == "lead" else (self.assignee_per_day, self.assignee_per_week)
        return (day, "day") if day is not None else (week, "week") if week is not None else None

    def share(self, role: str, person: str) -> int:
        """How much of a role's hours land on one person: their Involvement, 100 by default."""
        return self.involvement.get((role, person), 100)


@dataclass(frozen=True)
class Tie:
    """A date set from another date (release 5.50, decision 245): ``amount`` workdays or weeks, ``direction`` "before" or "after",
    the ``point``, "start" or "end", of task ``source``, or of its key date ``key_date``."""

    source: str
    point: str = "end"
    amount: int = 0
    unit: str = "workdays"
    direction: str = "after"
    key_date: int | None = None


@dataclass(frozen=True)
class TemplateOrigin:
    """Where a task made from a template came from (release 5.44, decision 180): the row, and the titles from the template's
    top row, which names it, down to that row. Only this reaches the Model: a template is never a Task."""

    row: int
    tree: str
    path: tuple[str, ...]
    discarded: bool = False

    @property
    def template(self) -> str:
        return self.path[0]

    def words(self) -> str:
        """As Task.md says it: "Product trial, Trial execution window", or the template's name for its top row."""
        return self.path[0] if len(self.path) == 1 else f"{self.path[0]}, {self.path[-1]}"


@dataclass
class KeyDate:
    """A key date on a task (release 5.31, the key dates plan): a start, an end or both (YYYY-MM-DD), a description, and
    whether it's a plant activity (a plant event of its own), a hard deadline, or done (the day it was ticked)."""

    id: int
    task: str
    start: str | None
    end: str | None
    description: str = ""
    plant: bool = False
    deadline: bool = False
    done: str | None = None
    pos: int = 0


@dataclass
class Person:
    id: str
    name: str
    hours: float | None
    status: str
    added_note: str | None
    aliases: list[str] = field(default_factory=list)
    #: Release 5.9 (mods log round 2, M0031, M0033, M0038): an email address DocRepo only keeps, one group, and a role.
    email: str | None = None
    group: str | None = None
    role: str | None = None


@dataclass
class Label:
    id: int
    name: str
    status: str
    keywords: list[str] = field(default_factory=list)
    #: The label it's under (mods log round 2, M0051): one level, so a parent label is a heading with sublabels.
    parent: int | None = None


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
    #: When it was discarded, and why. A discarded capture leaves its task's logs, the views and search; its folder stays.
    discarded: str | None = None
    discard_reason: str | None = None
    #: Email layer 0's line (mods log round 1, M0024): what it kept from the email and what it left out.
    email_layer_0: str | None = None
    #: Whether its content text in capture.md is markup (mods log round 2, M0045; ``docrepo.markup``), not plain text.
    formatted: bool = False
    #: Items and meeting notes (mods log round 2, M0048 phase 2, M0052; release 5.8): the notes an item came from, what
    #: it is (task, note, update or decision; "notes" for a meeting's notes), and the meeting the notes made.
    from_notes: str | None = None
    item: str | None = None
    meeting: str | None = None
    #: Made on a notes page (release 5.27): a picture pasted there, or a file dropped there.
    page_made: bool = False
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
    text_status: str | None = None  # ok, partial, none or error
    text_chars: int | None = None
    text_note: str | None = None
    size: int | None = None
    modified: str | None = None
    sha256: str | None = None


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
    kind: str  # Saved copy, Old version, Tracked original, Link or Email attachment
    name: str
    document: str
    task: str


#: Today (mods log round 1, M0016): the built-in agenda target that is the owner's list for the day.
TODAY = "today"
#: The priorities (mods log round 2, M0029, M0030, decision 23), in order: each bucket's key and name. A task with none
#: is Not ranked. ``docrepo/priorities.py`` ranks tasks.
PRIORITY_NAMES = {"critical": "Critical", "high": "High", "medium": "Medium", "parking": "Parking lot"}


def is_person(item_id: str | None) -> bool:
    return bool(item_id and re.match(r"P\d", item_id))


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


_TASK_COLUMNS = (
    "id, title, state, closed, urgent, meeting, recurrence, repeat_until, start, due, deadline, deadline_desc, reminder, "
    "lead_hours, assignee_hours, inherit_labels, description, current_status, created, created_by, discarded, discard_reason, plant_event, "
    "priority, priority_rank, day_headings, duration, calendar_days, lead_per_day, assignee_per_day, lead_per_week, assignee_per_week"
)


def template_origins(conn: sqlite3.Connection) -> dict[str, TemplateOrigin]:
    """Each task made from a template: where it came from (release 5.44)."""
    made = conn.execute("SELECT task, row_id, tree FROM task_template").fetchall()
    if not made:
        return {}
    rows = {r["id"]: r for r in conn.execute("SELECT id, parent, title, template FROM template_rows")}
    gone = {r["id"] for r in conn.execute("SELECT id FROM templates WHERE discarded IS NOT NULL")}
    out: dict[str, TemplateOrigin] = {}
    for r in made:
        path, x = [], rows[r["row_id"]]
        while x is not None:
            path.insert(0, x["title"])
            x = rows.get(x["parent"])
        out[r["task"]] = TemplateOrigin(r["row_id"], r["tree"], tuple(path), rows[r["row_id"]]["template"] in gone)
    return out


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
        t.urgent, t.meeting, t.inherit_labels, t.plant_event = bool(t.urgent), bool(t.meeting), bool(t.inherit_labels), bool(t.plant_event)
        t.calendar_days = bool(t.calendar_days)
        t.day_headings = None if t.day_headings is None else bool(t.day_headings)
    for r in conn.execute("SELECT * FROM task_ties"):
        if r["task"] in tasks:
            tasks[r["task"]].ties[r["field"]] = Tie(r["source"], r["point"], r["amount"], r["unit"], r["direction"], r["key_date"])
    for r in conn.execute("SELECT task, person, role, involvement FROM task_people ORDER BY id"):
        if r["task"] in tasks:
            (tasks[r["task"]].leads if r["role"] == "lead" else tasks[r["task"]].assignees).append(r["person"])
            if r["involvement"] != 100:
                tasks[r["task"]].involvement[(r["role"], r["person"])] = r["involvement"]
    for r in conn.execute("SELECT tl.task, l.name FROM task_labels tl JOIN labels l ON l.id = tl.label ORDER BY tl.id"):
        if r["task"] in tasks:
            tasks[r["task"]].labels.append(r["name"])
    for r in conn.execute("SELECT task, name, value FROM task_references ORDER BY task, rowid"):
        if r["task"] in tasks:
            tasks[r["task"]].references[r["name"]] = r["value"]
    return tasks


class Model:
    """Everything in docs.db, as of one moment."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        q = conn.execute
        self.tasks = load_tasks(conn)
        self.people: dict[str, Person] = {
            r["id"]: Person(r["id"], r["name"], r["hours_per_week"], r["status"], r["added_note"], email=r["email"], group=r["person_group"],
                            role=r["role"])
            for r in q("SELECT * FROM people ORDER BY id")
        }
        for r in q("SELECT person, alias FROM person_aliases ORDER BY person, pos"):
            self.people[r["person"]].aliases.append(r["alias"])
        labels = {r["id"]: Label(r["id"], r["name"], r["status"], parent=r["parent"]) for r in q("SELECT * FROM labels ORDER BY id")}
        for r in q("SELECT label, keyword FROM label_keywords ORDER BY label, pos"):
            labels[r["label"]].keywords.append(r["keyword"])
        self.labels: list[Label] = list(labels.values())
        self.links: list[tuple[str, str]] = [(r["child"], r["parent"]) for r in q("SELECT child, parent FROM task_parents ORDER BY id")]
        #: Each task's key dates (release 5.31), in its own order.
        self.key_dates: dict[str, list[KeyDate]] = {}
        for r in q("SELECT * FROM task_dates ORDER BY task, pos, id"):
            self.key_dates.setdefault(r["task"], []).append(KeyDate(r["id"], r["task"], r["start_day"], r["end_day"], r["description"],
                                                                    bool(r["plant"]), bool(r["deadline"]), r["done"], r["pos"]))
        self._parents: dict[str, list[str]] = {}
        self._children: dict[str, list[str]] = {}
        for child, parent in self.links:
            self._parents.setdefault(child, []).append(parent)
            self._children.setdefault(parent, []).append(child)
        self.captures: dict[str, Capture] = {}
        for r in q("SELECT * FROM captures ORDER BY id"):
            values = {k: r[k] for k in r.keys()}
            values["types"] = values["types"].split(",") if values["types"] else []
            values["formatted"] = bool(values.get("formatted"))
            values["page_made"] = bool(values.get("page_made"))
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
        self._holders: dict[str, list[str]] | None = None  # document -> tasks, worked out when first asked
        self.status: list[StatusEntry] = [
            StatusEntry(r["task"], r["at"], r["field"], r["from_value"], r["to_value"], r["via"])
            for r in q("SELECT * FROM status_log ORDER BY id")
        ]
        #: Each task's notes page (release 5.25; ``docrepo.notes_page``), and the days the owner edited it, with the time
        #: of the day's last edit.
        self.pages: dict[str, str] = {r["task"]: r["body"] for r in q("SELECT task, body FROM task_pages")}
        #: Each task's pinned files, its key documents, in order (the Task view, release 5.35).
        self.pins: dict[str, list[str]] = {}
        for r in q("SELECT task, document FROM task_pins ORDER BY task, pos"):
            self.pins.setdefault(r["task"], []).append(r["document"])
        self.page_edits: list[tuple[str, str, str]] = [(r["task"], r["day"], r["at"]) for r in q(
            "SELECT task, day, at FROM task_page_versions WHERE by_owner = 1 ORDER BY day, task")]
        #: The tasks made from a template, and where each came from (release 5.44).
        self.origins: dict[str, TemplateOrigin] = template_origins(conn)

    # ---- names ----
    def uses_day_headings(self, task_id: str) -> bool:
        """Whether the task's new captures go under a heading for their day (decision 119): off by default, on for a
        meeting, unless set on the task in Edit task."""
        t = self.tasks[task_id]
        return t.meeting if t.day_headings is None else t.day_headings

    def task(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def person_name(self, person_id: str) -> str:
        p = self.people.get(person_id)
        return p.name if p else person_id

    def target_name(self, target: str) -> str:
        """An agenda target's name: Today, a person's name or a task's title."""
        if target == TODAY:
            return "Today"
        if is_person(target):
            return self.person_name(target)
        return self.tasks[target].title if target in self.tasks else target

    def active_people(self) -> list[Person]:
        return [p for p in self.people.values() if p.status == "active"]

    def active_labels(self) -> list[Label]:
        return [label for label in self.labels if label.status == "active"]

    # ---- groups, label nesting and plant events (release 5.9) ----
    def groups(self) -> list[str]:
        """The groups active people are in, A to Z (mods log round 2, M0033)."""
        return sorted({p.group for p in self.active_people() if p.group}, key=str.lower)

    def group_people(self, group: str) -> list[str]:
        """The active people in a group."""
        return [p.id for p in self.active_people() if p.group == group]

    def label(self, name: str) -> Label | None:
        return next((lb for lb in self.labels if lb.name.lower() == name.lower()), None)

    def parent_label(self, name: str) -> str | None:
        """The label a sublabel is under (M0051)."""
        lb = self.label(name)
        parent = next((x for x in self.labels if lb and x.id == lb.parent), None)
        return parent.name if parent else None

    def sublabels(self, name: str, active: bool = True) -> list[str]:
        """The labels under a parent label."""
        lb = self.label(name)
        return [x.name for x in self.labels if lb and x.parent == lb.id and (x.status == "active" or not active)]

    def is_parent_label(self, name: str) -> bool:
        """A label with labels under it: a heading that tasks don't get on their own."""
        return bool(self.sublabels(name, active=False))

    def label_path(self, name: str) -> str:
        """A label as pickers show it: "Production line › Line 1"."""
        parent = self.parent_label(name)
        return f"{parent} › {name}" if parent else name

    def tied_to(self, task_id: str) -> list[Task]:
        """The tasks with a date tied to this one's dates or key dates (release 5.50), but not discarded ones."""
        return [t for t in self.tasks.values() if not t.discarded and any(x.source == task_id for x in t.ties.values())]

    def key_dates_of(self, task_id: str) -> list[KeyDate]:
        """A task's key dates (release 5.31), in its own order."""
        return self.key_dates.get(task_id, [])

    def plant_activities(self) -> list[tuple[Task, KeyDate]]:
        """The key dates ticked as a plant activity (release 5.31, decision 149), on tasks that aren't discarded: each a
        plant event of its own."""
        return [(t, kd) for t in self.tasks.values() if not t.discarded for kd in self.key_dates.get(t.id, []) if kd.plant]

    def plant_events(self) -> list[Task]:
        """The plant events (M0028): tasks with Plant event ticked, but discarded ones, soonest first."""
        return sorted((t for t in self.tasks.values() if t.plant_event and not t.discarded), key=lambda t: (start_of(t), t.title.lower()))

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
        """No task, and no agenda item: it waits in the Unfiled view. A discarded capture doesn't."""
        return not c.discarded and not self.capture_tasks(c) and not any(a.added_by == c.id for a in self.agenda)

    def unfiled_captures(self) -> list[Capture]:
        return [c for c in self.captures.values() if self.is_unfiled(c)]

    def live_captures(self) -> list[Capture]:
        """Every capture that isn't discarded."""
        return [c for c in self.captures.values() if not c.discarded]

    def notes_of(self, task_id: str) -> list[Capture]:
        return [c for c in self.live_captures() if task_id in self.capture_tasks(c)]

    # ---- discarded tasks and captures (mods log round 1, M0021) ----
    def discarded_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.discarded]

    def discarded_captures(self) -> list[Capture]:
        return [c for c in self.captures.values() if c.discarded]

    def only_in_discarded(self, document_id: str) -> bool:
        """True for a document that came in only with discarded captures, and has no saved copy."""
        holding = [c for c in self.captures.values() if document_id in c.document_ids]
        return bool(holding) and all(c.discarded for c in holding) and not any(f.document == document_id for f in self.copies)

    def document_holders(self, document_id: str) -> list[str]:
        """The tasks a document belongs to: those of the captures it came in with, and those it has saved copies in."""
        if self._holders is None:
            holders: dict[str, list[str]] = {}
            for c in self.live_captures():
                for d in c.document_ids:
                    holders.setdefault(d, []).extend(self.capture_tasks(c))
            for f in self.copies:
                holders.setdefault(f.document, []).append(f.task)
            self._holders = {d: _unique(ts) for d, ts in holders.items()}
        return self._holders.get(document_id, [])

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
               for c in self.live_captures() if c.summary and task_id in self.capture_tasks(c)]
        out += [Summary(task_id, v.at, v.summary_type, v.summary, v.document) for v in self.versions_of(task_id) if v.summary]
        return sorted(out, key=lambda s: s.at)

    def files_of(self, task_id: str) -> list[FileEntry]:
        """Every file connected to a task: its saved copies, then the documents of its captures."""
        out = [FileEntry("Old version" if f.old else "Saved copy", f.name, f.document, task_id) for f in self.copies if f.task == task_id]
        for doc_id in _unique(d for c in self.notes_of(task_id) for d in c.document_ids):
            d = self.documents[doc_id]
            kind = "Link" if is_link(d.original) else "Tracked original" if d.original else "Email attachment"
            out.append(FileEntry(kind, d.name, doc_id, task_id))
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
        """Open meetings first, then any other task or person with open items. Today has a view of its own."""
        out = [t.id for t in self.open_meetings()]
        for a in self.agenda:
            if not a.closed and a.target != TODAY and a.target not in out:
                out.append(a.target)
        return out

    # ---- Today (mods log round 1, M0016) ----
    def today_items(self) -> list[AgendaItem]:
        """Today's open items, the oldest first: they carry over until they're closed."""
        return sorted(self.open_items_for(TODAY), key=lambda a: a.added)

    def done_on(self, day: date) -> list[AgendaItem]:
        """Today's items marked Done on ``day``, the latest first."""
        done = [a for a in self.agenda if a.target == TODAY and a.how == "Done" and (a.closed or "")[:10] == day.isoformat()]
        return sorted(done, key=lambda a: a.closed or "", reverse=True)

    def meeting_when(self, target: str, today: date) -> str:
        """When a task target next happens, such as "Tue 13 Oct"; "" for a person or Today."""
        if is_person(target) or target == TODAY:
            return ""
        due = due_of(self.tasks[target], today)
        return long_date(due.date, today) if due else "no date set"
