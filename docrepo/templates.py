"""Task templates (releases 5.44 and 5.45; the task templates design in the design workspace, decisions 180 to 199).

A template is a small tree of rows without dates, in tables of its own, so nothing that reads tasks can see one (decision
180). Its name and description are its top row's. **Make tasks** copies a row and what's under it into the task tree, as
ordinary tasks. Each field a row fills starts linked on the task made from it (decision 183): ``task_links`` names the fields
still following it, and an open task's linked field holds its row's value, always:

- ``tasks.update_task`` ends a link when a different value is written to the field (decision 184);
- saving a row writes the new value to the tasks following it, or ends the links of those unticked in the preview (decisions
  186 and 198). Closed and discarded tasks never change, and fall behind until they come back (decision 185).

Each change to a template works out what it would do first, with nothing changed (``preview_row``, ``preview_new_row`` and
``preview_remove``), and the browse tool shows that before it's made. The status log of each task says what reached it, and
the template keeps a Changes list (decision 187).

Only the Templates view, Make tasks, Save as template and the previews read these tables, through a ``Library``. The Model
knows only where each task came from (``model.TemplateOrigin``).
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from docrepo import agenda, edits, markup, notes_page, search, tasks
from docrepo.config import Settings
from docrepo.dates import short, stamp, to_date, workday_numbers
from docrepo.db import transaction
from docrepo.model import Model
from docrepo.pages import num
from docrepo.parse import Who
from docrepo.safe_fs import SafeFS
from docrepo.schedule import length_of
from docrepo.stories import clip
from docrepo.tasks import FIELD_NAMES, RATE_FIELDS, RATES, TEMPLATE_LINK, WEEK_RATES, Change, TaskError, _normalize, hours_values, stated, worked_out

log = logging.getLogger(__name__)

#: The fields a row can fill, as ``tasks.update_task`` names them. A row and a task have them under the same names.
FIELDS = ("title", "description", "labels", "inherit_labels", "leads", "assignees", "lead_hours", "assignee_hours", "urgent", "meeting",
          "plant_event", "recurrence", "duration", "calendar_days")
FLAGS = ("inherit_labels", "urgent", "meeting", "plant_event", "calendar_days")
#: The fields a routine task doesn't have: its hours are for each time it comes round (decisions 189 and 191).
NOT_ROUTINE = ("duration", "calendar_days")
ROLES = {"leads": "lead", "assignees": "assignee"}


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


@dataclass
class Row:
    """One task in a template. ``notes`` are its starting notes, as notes page markup."""

    id: int
    template: int
    parent: int | None
    place: int
    title: str
    description: str = ""
    inherit_labels: bool = True
    lead_hours: float | None = None
    assignee_hours: float | None = None
    urgent: bool = False
    meeting: bool = False
    plant_event: bool = False
    recurrence: str | None = None
    notes: str = ""
    duration: int | None = None
    calendar_days: bool = False
    lead_per_day: float | None = None
    assignee_per_day: float | None = None
    lead_per_week: float | None = None
    assignee_per_week: float | None = None
    leads: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    involvement: dict[tuple[str, str], int] = field(default_factory=dict)  # as on a task: only where it isn't 100


@dataclass
class Template:
    id: int
    created: str
    discarded: str | None = None
    discard_reason: str | None = None
    top: int = 0  # its top row


@dataclass(frozen=True)
class Copy:
    """A task made from a row: the task, its row, and its tree's top task."""

    task: str
    row: int
    tree: str


@dataclass(frozen=True)
class LogLine:
    """A line of a template's Changes list."""

    at: str
    what: str  # changed, added or removed
    text: str
    reached: int = 0
    left_out: int = 0

    def said(self) -> str:
        """What it did to the tasks, in words."""
        if self.what == "removed":
            return f"{plural(self.reached, 'task')} discarded, {self.left_out} kept"
        if self.what == "added":
            if not self.reached and not self.left_out:
                return "New trees only"
            return f"To {plural(self.reached, 'tree')}" + (f", {self.left_out} left without it" if self.left_out else "")
        if not self.reached and not self.left_out:
            return "No task changed"
        return f"{plural(self.reached, 'task')} changed" + (f", {self.left_out} left as {'it was' if self.left_out == 1 else 'they were'}" if self.left_out else "")


def fills(row, key: str) -> bool:
    """Whether a row fills a field (decision 183), or a task has one. A tick fills it when it's ticked, and Inherit parent
    labels, on by default, when it's off. Runs through weekends comes with a Duration, and hours are filled by a rate or a total."""
    if key == "inherit_labels":
        return not row.inherit_labels
    if key == "calendar_days":
        return row.duration is not None or row.calendar_days
    value = stated(row, key)
    return value is not None and value is not False and value != "" and value != []


class Library:
    """Every template and row, and which tasks were made from them, as of one moment."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        q = conn.execute
        self.templates: dict[int, Template] = {r["id"]: Template(r["id"], r["created"], r["discarded"], r["discard_reason"])
                                                for r in q("SELECT * FROM templates ORDER BY id")}
        self.rows: dict[int, Row] = {}
        self._children: dict[int, list[int]] = {}
        for r in q("SELECT * FROM template_rows ORDER BY place, id"):
            row = Row(r["id"], r["template"], r["parent"], r["place"], r["title"], r["description"], bool(r["inherit_labels"]), r["lead_hours"],
                      r["assignee_hours"], bool(r["urgent"]), bool(r["meeting"]), bool(r["plant_event"]), r["recurrence"], r["notes"],
                      r["duration"], bool(r["calendar_days"]), r["lead_per_day"], r["assignee_per_day"], r["lead_per_week"], r["assignee_per_week"])
            self.rows[row.id] = row
            if row.parent is None:
                self.templates[row.template].top = row.id
            else:
                self._children.setdefault(row.parent, []).append(row.id)
        for r in q("SELECT row_id, person, role, involvement FROM template_row_people ORDER BY id"):
            (self.rows[r["row_id"]].leads if r["role"] == "lead" else self.rows[r["row_id"]].assignees).append(r["person"])
            if r["involvement"] != 100:
                self.rows[r["row_id"]].involvement[(r["role"], r["person"])] = r["involvement"]
        for r in q("SELECT x.row_id, l.name FROM template_row_labels x JOIN labels l ON l.id = x.label ORDER BY x.id"):
            self.rows[r["row_id"]].labels.append(r["name"])
        self.copies: dict[str, Copy] = {r["task"]: Copy(r["task"], r["row_id"], r["tree"])
                                        for r in q("SELECT task, row_id, tree FROM task_template ORDER BY task")}
        self.links: dict[str, set[str]] = {}
        for r in q("SELECT task, field FROM task_links"):
            self.links.setdefault(r["task"], set()).add(r["field"])
        self.changes: dict[int, list[LogLine]] = {}
        for r in q("SELECT * FROM template_log ORDER BY id DESC"):
            self.changes.setdefault(r["template"], []).append(LogLine(r["at"], r["what"], r["text"], r["reached"], r["left_out"]))

    def live(self) -> list[Template]:
        return [t for t in self.templates.values() if not t.discarded]

    def name(self, template_id: int) -> str:
        return self.rows[self.templates[template_id].top].title

    def template_of(self, row_id: int) -> Template:
        return self.templates[self.rows[row_id].template]

    def children(self, row_id: int) -> list[Row]:
        return [self.rows[x] for x in self._children.get(row_id, [])]

    def walk(self, row_id: int, depth: int = 0) -> list[tuple[Row, int]]:
        """A row and everything under it, in order, each with how deep it is."""
        out = [(self.rows[row_id], depth)]
        for child in self.children(row_id):
            out += self.walk(child.id, depth + 1)
        return out

    def path(self, row_id: int) -> list[Row]:
        """The rows from the template's top down to this one."""
        out, x = [], self.rows.get(row_id)
        while x is not None:
            out.insert(0, x)
            x = self.rows.get(x.parent) if x.parent is not None else None
        return out

    def copies_of(self, row_id: int) -> list[Copy]:
        return [c for c in self.copies.values() if c.row == row_id]

    def trees(self, template_id: int) -> list[Copy]:
        """The trees made from a template: each copy that's its own tree's top, oldest first."""
        return [c for c in self.copies.values() if c.task == c.tree and self.rows[c.row].template == template_id]

    def in_tree(self, top: str) -> list[str]:
        return [c.task for c in self.copies.values() if c.tree == top]


def days_text(days: int) -> str:
    return plural(days, "day")


def summary(row: Row) -> str:
    """A row's calm summary in a list: "5 days · 6 h a day", and that it repeats."""
    length = (days_text(row.duration) + (", every day" if row.calendar_days else "")) if row.duration else ""
    if stated(row, "assignee_hours") is not None:
        hours = field_text(None, "assignee_hours", stated(row, "assignee_hours"))
    elif stated(row, "lead_hours") is not None:
        hours = field_text(None, "lead_hours", stated(row, "lead_hours")) + " lead"
    else:
        hours = ""
    return " · ".join(x for x in (length, hours, row.recurrence or "") if x)


def own_fields(row: Row, task, links: set[str], top: bool) -> list[str]:
    """The fields a row fills where a task has gone its own way: no longer linked, and with a different value."""
    return [k for k in FIELDS if fills(row, k) and k not in links and stated(task, k) != stated(row, k) and not (k == "title" and top)]


def field_text(m: Model | None, key: str, value) -> str:
    """A field's value in a preview or beside a mark: "30 h", "6 h a day", "5 days", "Tom Becker, Mike Ortiz", "Yes"."""
    if key in FLAGS:
        return "Yes" if value else "No"
    if value is None or value == "" or value == []:
        return "None"
    if key in RATES:
        return f"{num(value[1])} h {value[0]}" if isinstance(value, tuple) else f"{num(value)} h"
    if key == "duration":
        return days_text(value)
    if key in ("start", "due"):
        day = to_date(value)
        return short(day, day)
    if key in ROLES:  # people, each with their Involvement when they've one
        pairs = [x if isinstance(x, tuple) else (x, 100) for x in value]
        return ", ".join(m.person_name(p) + (f" {share}%" if share != 100 else "") for p, share in pairs)
    if key == "labels":
        return ", ".join(value)
    return clip(str(value), 40)


def _change_line(m: Model, key: str, before, after) -> str:
    """One field's change in a preview: "Assignee hours 30 h → 10 h", or "Duration 5 days → 3 days"."""
    if key == "description":
        return "Description reworded"
    return f"{FIELD_NAMES[key]} {field_text(m, key, before)} → {field_text(m, key, after)}"


def work_of(t) -> float:
    """The hours on a task, as Capacity counts them: each person's share of their role's hours."""
    return (sum((t.lead_hours or 0) * t.involvement.get(("lead", p), 100) / 100 for p in t.leads)
            + sum((t.assignee_hours or 0) * t.involvement.get(("assignee", p), 100) / 100 for p in t.assignees))


# ---- rows ----
def _checked(conn: sqlite3.Connection, values: Mapping) -> dict:
    """A form's values for a row, checked as a task's are. ``notes`` is markup. A rate stands for its total, and a row that
    repeats has no Duration or rate, as a routine task hasn't."""
    out = {k: _normalize(conn, k, values.get(k)) for k in ("title", "description", "lead_hours", "assignee_hours", "recurrence", "leads", "assignees", "labels",
                                                            "duration", *RATE_FIELDS)}
    out.update(inherit_labels=bool(values.get("inherit_labels", True)), urgent=bool(values.get("urgent")), meeting=bool(values.get("meeting")),
               plant_event=bool(values.get("plant_event")), calendar_days=bool(values.get("calendar_days")), notes=(values.get("notes") or "").strip("\n"))
    if out["recurrence"]:
        out.update(duration=None, calendar_days=False, **dict.fromkeys(RATE_FIELDS))
    for hours in RATES:  # one rate at most, and it stands for the total
        if out[RATES[hours]] is not None:
            out[WEEK_RATES[hours]] = None
        if out[RATES[hours]] is not None or out[WEEK_RATES[hours]] is not None:
            out[hours] = None
    out["involvement"] = {(role, p): share for (role, p), share in tasks.shares_of(values.get("involvement")).items()
                          if p in out["leads" if role == "lead" else "assignees"]}
    return out


_COLUMNS = ("title", "description", "inherit_labels", "lead_hours", "assignee_hours", "urgent", "meeting", "plant_event", "recurrence", "notes", "duration",
            "calendar_days", *RATE_FIELDS)


def _store_lists(conn: sqlite3.Connection, row_id: int, v: Mapping) -> None:
    conn.execute("DELETE FROM template_row_people WHERE row_id = ?", (row_id,))
    conn.execute("DELETE FROM template_row_labels WHERE row_id = ?", (row_id,))
    for key, role in ROLES.items():
        conn.executemany("INSERT INTO template_row_people (row_id, person, role, involvement) VALUES (?, ?, ?, ?)",
                         [(row_id, p, role, v["involvement"].get((role, p), 100)) for p in v[key]])
    conn.executemany("INSERT INTO template_row_labels (row_id, label) SELECT ?, id FROM labels WHERE name = ?", [(row_id, n) for n in v["labels"]])


def _insert_row(conn: sqlite3.Connection, template: int, parent: int | None, v: Mapping) -> int:
    place = conn.execute("SELECT coalesce(max(place), 0) + 1 FROM template_rows WHERE template = ? AND parent IS ?", (template, parent)).fetchone()[0]
    columns = {"template": template, "parent": parent, "place": place, **{k: v[k] for k in _COLUMNS}}
    cur = conn.execute(f"INSERT INTO template_rows ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", tuple(columns.values()))
    _store_lists(conn, cur.lastrowid, v)
    return cur.lastrowid


def _log_change(conn: sqlite3.Connection, template: int, at: datetime, what: str, text: str, reached: int = 0, left_out: int = 0) -> None:
    """A line in the template's Changes list, once tasks have been made from it. Building a template isn't a change to anything."""
    if conn.execute("SELECT 1 FROM task_template x JOIN template_rows r ON r.id = x.row_id WHERE r.template = ? LIMIT 1", (template,)).fetchone() is None:
        return
    conn.execute("INSERT INTO template_log (template, at, what, text, reached, left_out) VALUES (?, ?, ?, ?, ?, ?)",
                 (template, stamp(at), what, text, reached, left_out))


def new_template(conn: sqlite3.Connection, name: str, at: datetime, values: Mapping | None = None) -> int:
    """A new template, with only its top row. Returns that row."""
    with transaction(conn):
        v = _checked(conn, {"inherit_labels": True, **(values or {}), "title": name})
        template = conn.execute("INSERT INTO templates (created) VALUES (?)", (stamp(at),)).lastrowid
        return _insert_row(conn, template, None, v)


def _ended(conn: sqlite3.Connection, task_id: str, keys: Collection[str], name: str, at: datetime) -> None:
    """These fields stop following the template, each with a line in the task's status log."""
    if keys:
        conn.executemany("DELETE FROM task_links WHERE task = ? AND field = ?", [(task_id, k) for k in keys])
        tasks.record(conn, task_id, at, f"Template: {name}", [Change(TEMPLATE_LINK, f"{FIELD_NAMES[k]}: no longer follows {name}", None) for k in FIELDS if k in keys])


# ---- a row changed: who it reaches (decisions 185, 186 and 198) ----
@dataclass
class Reached:
    """A task a row's change would reach: the fields, what they'd become, and the change in words."""

    task: str
    tree: str  # its tree's title, which names it in the preview, as all its row's copies share a title
    state: str
    keys: list[str]  # the linked fields it reaches
    fields: dict[str, object]  # what they become, as tasks.update_task takes them
    lines: list[str]
    work_before: float
    work_after: float


@dataclass
class NotChanging:
    """A task the change leaves alone, and why: "closed", "discarded" or "own"."""

    task: str
    tree: str
    why: str
    text: str


@dataclass
class RowPlan:
    """What saving a row's form would do."""

    row: int
    title: str
    template: int
    name: str
    changed: list[str]
    lines: list[str]
    notes_changed: bool
    items: list[Reached] = field(default_factory=list)
    not_changing: list[NotChanging] = field(default_factory=list)
    #: Links that end because the row stops filling the field (decision 198), though no value changes.
    ending: dict[str, list[str]] = field(default_factory=dict)


#: What a preview says changed on a task, in order: a Duration's change shows the dates it moves, and a rate's the total it comes to.
_LINE_FIELDS = ("title", "description", "labels", "inherit_labels", "leads", "assignees", "duration", "calendar_days", "start", "due", "lead_hours", "assignee_hours",
                "urgent", "meeting", "plant_event", "recurrence")


def _task_lines(m: Model, t, sim) -> list[str]:
    """What a change does to a task, in words. A rate changed with its total left as it was says so."""
    lines = [_change_line(m, k, getattr(t, k), getattr(sim, k)) for k in _LINE_FIELDS if getattr(t, k) != getattr(sim, k)]
    for hours in RATES:
        if getattr(t, hours) == getattr(sim, hours) and stated(t, hours) != stated(sim, hours):
            lines.append(_change_line(m, hours, stated(t, hours), stated(sim, hours)))
    for key, role in ROLES.items():
        for p in getattr(sim, key):
            old, new = t.involvement.get((role, p), 100), sim.involvement.get((role, p), 100)
            if p in getattr(t, key) and old != new:
                lines.append(f"{m.person_name(p)}'s involvement {old}% → {new}%")
    return lines


def _as_changes(row: Row, keys: Sequence[str], t) -> dict[str, object]:
    """Linked fields' values, as ``tasks.update_task`` takes them: hours as a rate, or as a total with no rate, and people with
    their Involvement, the other role's left as the task has it."""
    out: dict[str, object] = {}
    for k in keys:
        if k in RATES:
            value = stated(row, k)
            out.update(hours_values(k, value[0][2:], value[1]) if isinstance(value, tuple) else hours_values(k, "all", value))
        else:
            out[k] = getattr(row, k)
        if k in ROLES:
            shares = out.get("involvement", t.involvement)
            out["involvement"] = {x: v for x, v in shares.items() if x[0] != ROLES[k]} | {x: v for x, v in row.involvement.items() if x[0] == ROLES[k]}
    return out


def _plan_row(conn: sqlite3.Connection, settings: Settings, row_id: int, v: Mapping) -> RowPlan:
    lib, m = Library(conn), Model(conn)
    workdays = workday_numbers(settings.workdays)
    before = lib.rows.get(row_id)
    if before is None:
        raise TaskError("That row isn't in a template any more.")
    after = replace(before, **{k: v[k] for k in (*FIELDS, "notes", *RATE_FIELDS, "involvement")})
    changed = [k for k in FIELDS if stated(before, k) != stated(after, k)]
    name = after.title if before.parent is None else lib.name(before.template)
    plan = RowPlan(row_id, after.title, before.template, name, changed, [_change_line(m, k, stated(before, k), stated(after, k)) for k in changed],
                   before.notes != after.notes)
    for c in lib.copies_of(row_id):
        t = m.tasks.get(c.task)
        if t is None:
            continue
        linked, top = lib.links.get(c.task, set()), c.task == c.tree
        tree = m.tasks[c.tree].title if c.tree in m.tasks else t.title
        will, own = [], []
        for k in changed:
            if k == "title" and top:  # the top task's name is its own
                continue
            if t.recurrence and (k in NOT_ROUTINE or (k in RATES and isinstance(stated(after, k), tuple))):
                continue  # a routine task has no length, so these don't reach it
            was, now = fills(before, k), fills(after, k)
            if was and not now:  # decision 198: no value changes, and the task keeps what it has as its own
                if k in linked:
                    plan.ending.setdefault(c.task, []).append(k)
            elif was and now and k in linked or not was and now and not fills(t, k):
                will.append(k)
            elif now and stated(t, k) != stated(after, k):
                own.append(k)
        if t.discarded or t.state == "Closed":  # decision 185: they never change
            if will:
                why = "discarded" if t.discarded else "closed"
                plan.not_changing.append(NotChanging(c.task, tree, why, f"{why}, so it keeps what it ended with"))
            continue
        if will:
            values = _as_changes(after, will, t)
            sim = replace(t, **worked_out(t, values, workdays)[0])
            plan.items.append(Reached(c.task, tree, t.state, will, values, _task_lines(m, t, sim), work_of(t), work_of(sim)))
        elif own:
            plan.not_changing.append(NotChanging(c.task, tree, "own", "its own " + ", ".join(f"{FIELD_NAMES[k].lower()} {field_text(m, k, stated(t, k))}" for k in own)))
    return plan


class _Preview(Exception):
    """Raised to roll a preview's changes back."""


def preview_row(conn: sqlite3.Connection, settings: Settings, row_id: int, values: Mapping, at: datetime) -> RowPlan:
    """What saving a row's form would do, with nothing changed: any new person or label is made and rolled back, as Edit
    selected's preview does."""
    plan: RowPlan | None = None
    try:
        with transaction(conn):
            plan = _plan_row(conn, settings, row_id, _checked(conn, _form_values(conn, values, at, [])))
            raise _Preview
    except _Preview:
        pass
    assert plan is not None
    return plan


def apply_row(conn: sqlite3.Connection, settings: Settings, row_id: int, values: Mapping, at: datetime, left: Collection[str] = (),
              added: list[str] | None = None) -> RowPlan:
    """Save a row (decision 186): each task following it takes the new value, but those in ``left``, unticked in the
    preview, which keep their value and stop following those fields. A field the row starts filling reaches only empty
    tasks, and they then follow it; one it stops filling changes no values (decision 198). Each change is in the task's
    status log, as "Template: *name*", and the template's Changes list says so (decision 187). Returns what it did."""
    with transaction(conn):
        v = _checked(conn, _form_values(conn, values, at, added if added is not None else []))
        plan = _plan_row(conn, settings, row_id, v)
        conn.execute(f"UPDATE template_rows SET {', '.join(f'{k} = ?' for k in _COLUMNS)} WHERE id = ?", (*(v[k] for k in _COLUMNS), row_id))
        _store_lists(conn, row_id, v)
        via, name = f"Template: {plan.name}", plan.name
        reached = 0
        for item in plan.items:
            if item.task in left:
                _ended(conn, item.task, item.keys, name, at)
                continue
            tasks.update_task(conn, settings, item.task, at=at, via=via, keep_links=True, **item.fields)
            conn.executemany("INSERT OR IGNORE INTO task_links (task, field) VALUES (?, ?)", [(item.task, k) for k in item.keys])
            reached += 1
        for task_id, keys in plan.ending.items():
            _ended(conn, task_id, keys, name, at)
        words = [*plan.lines, *(["Starting notes changed"] if plan.notes_changed else [])]
        if words:
            _log_change(conn, plan.template, at, "changed", f"{plan.title} · {', '.join(words)}", reached, len(plan.items) - reached)
    return plan


# ---- a row added: which trees it's offered to (decision 188) ----
@dataclass
class TreeOffer:
    task: str
    title: str
    state: str
    closed: int  # how many of its tasks are closed
    total: int


@dataclass
class AddPlan:
    """What adding a row would offer: the open trees that have its parent, and the closed trees that aren't offered."""

    title: str
    parent: int
    parent_title: str
    template: int
    name: str
    summary: str
    trees: list[TreeOffer] = field(default_factory=list)
    closed_trees: list[str] = field(default_factory=list)


def _plan_add(conn: sqlite3.Connection, parent: int, v: Mapping) -> AddPlan:
    lib, m = Library(conn), Model(conn)
    p = lib.rows.get(parent)
    if p is None:
        raise TaskError("That row isn't in a template any more.")
    row = Row(0, p.template, parent, 0, **{k: v[k] for k in (*FIELDS, "notes", *RATE_FIELDS, "involvement")})
    plan = AddPlan(row.title, parent, p.title, p.template, lib.name(p.template), summary(row))
    for c in lib.trees(p.template):
        t = m.tasks.get(c.task)
        if t is None or t.discarded or parent not in [x.id for x, _ in lib.walk(c.row)]:
            continue
        if t.state == "Closed":
            plan.closed_trees.append(t.title)
            continue
        ids = [x for x in lib.in_tree(c.task) if x in m.tasks and not m.task(x).discarded]
        plan.trees.append(TreeOffer(c.task, t.title, t.state, sum(1 for x in ids if m.task(x).state == "Closed"), len(ids)))
    return plan


def preview_new_row(conn: sqlite3.Connection, parent: int, values: Mapping, at: datetime) -> AddPlan:
    """What adding a row would offer, with nothing changed."""
    plan: AddPlan | None = None
    try:
        with transaction(conn):
            plan = _plan_add(conn, parent, _checked(conn, _form_values(conn, values, at, [])))
            raise _Preview
    except _Preview:
        pass
    assert plan is not None
    return plan


def add_row(conn: sqlite3.Connection, settings: Settings, parent: int, values: Mapping, at: datetime, left: Collection[str] = (),
            added: list[str] | None = None) -> tuple[int, AddPlan, list[str]]:
    """A new row, at the end of those under ``parent``, and a copy of it in each open tree that has its parent, but those in
    ``left``, unticked in the preview (decision 188). A copy arrives undated, with its fields linked, under the copy of its
    parent, or under the tree's top task if that's gone. New trees always have it. Returns the row, the plan, and the tasks made."""
    with transaction(conn):
        v = _checked(conn, _form_values(conn, values, at, added if added is not None else []))
        plan = _plan_add(conn, parent, v)
        row_id = _insert_row(conn, plan.template, parent, v)
        lib = Library(conn)
        row, m = lib.rows[row_id], Model(conn)
        via = f"Template: {plan.name}"
        made = []
        for tree in plan.trees:
            if tree.task in left:
                continue
            under = next((x for x in lib.in_tree(tree.task) if lib.copies[x].row == parent and x in m.tasks and not m.task(x).discarded), tree.task)
            made.append(_copy_row(conn, settings, row, row.title, [under], via, tree.task, Choice(), False, at))
            tasks.record(conn, under, at, via, [Change(TEMPLATE_LINK, None, f"{row.title} added to this tree from {plan.name}")])
        _log_change(conn, plan.template, at, "added", f"Added {row.title}", len(made), len(plan.trees) - len(made))
    return row_id, plan, made


# ---- a row taken out (decision 188) ----
@dataclass
class CopyOffer:
    """A task made from a row being taken out. ``can`` says it's not started with nothing on it, so it can be discarded."""

    task: str
    tree: str
    state: str
    can: bool


@dataclass
class RemovePlan:
    title: str
    name: str
    rows: int
    copies: list[CopyOffer] = field(default_factory=list)


def preview_remove(conn: sqlite3.Connection, row_id: int) -> RemovePlan:
    """What taking a row out would do, with nothing changed. A top row can't go: discard the template instead."""
    lib, m = Library(conn), Model(conn)
    row = lib.rows.get(row_id)
    if row is None:
        raise TaskError("That row isn't in a template any more.")
    if row.parent is None:
        raise TaskError("A template's top row can't be taken out. Discard the template instead.")
    walked = lib.walk(row_id)
    going = {c.task for x, _ in walked for c in lib.copies_of(x.id)}
    plan = RemovePlan(row.title, lib.name(row.template), len(walked))
    for x, _ in walked:
        for c in lib.copies_of(x.id):
            t = m.tasks.get(c.task)
            if t is None or t.discarded:
                continue
            page = m.pages.get(c.task, "")
            can = (t.state == "Not started" and not t.current_status and not m.notes_of(c.task) and not m.key_dates_of(c.task)
                   and not any(f.task == c.task for f in m.copies) and not m.open_items_for(c.task) and page in ("", page_body(x.notes))
                   and all(k in going or m.task(k).discarded for k in m.children_of(c.task)))
            plan.copies.append(CopyOffer(c.task, m.tasks[c.tree].title if c.tree in m.tasks else t.title, t.state, can))
    return plan


def remove_row(conn: sqlite3.Connection, settings: Settings, row_id: int, at: datetime, discard: Collection[str] = ()) -> tuple[list[str], list[str]]:
    """Take a row and what's under it out of its template. The tasks made from them stay and stop following, but those in
    ``discard``, which are discarded with the reason "Taken out of template *name*" if they can be (decision 188): Bring back
    restores them. Returns the tasks kept and those discarded."""
    plan = preview_remove(conn, row_id)
    lib = Library(conn)
    row = lib.rows[row_id]
    name, via = plan.name, f"Template: {plan.name}"
    walked = lib.walk(row_id)
    can = {c.task for c in plan.copies if c.can}
    wanted = [c.task for x, _ in reversed(walked) for c in lib.copies_of(x.id) if c.task in discard and c.task in can]  # those under them first
    with transaction(conn):
        for x, _ in walked:
            for c in lib.copies_of(x.id):
                conn.execute("DELETE FROM task_links WHERE task = ?", (c.task,))
                conn.execute("DELETE FROM task_template WHERE task = ?", (c.task,))
                if c.task not in wanted:
                    tasks.record(conn, c.task, at, via, [Change(TEMPLATE_LINK, f"No longer follows {name}: its row was taken out", None)])
        gone: list[str] = []
        m = Model(conn)
        for task_id in wanted:
            if all(k in gone or m.task(k).discarded for k in m.children_of(task_id)):
                for a in m.agendas_on(task_id):
                    agenda.close_item(conn, a.id, how="Removed", closed=stamp(at), closed_by=via)
                tasks.set_discarded(conn, settings, task_id, f"Taken out of template {name}", at=at, via=via)
                gone.append(task_id)
            else:
                tasks.record(conn, task_id, at, via, [Change(TEMPLATE_LINK, f"No longer follows {name}: its row was taken out", None)])
        for x, _ in reversed(walked):  # those under it first
            conn.execute("DELETE FROM template_row_people WHERE row_id = ?", (x.id,))
            conn.execute("DELETE FROM template_row_labels WHERE row_id = ?", (x.id,))
            conn.execute("DELETE FROM template_rows WHERE id = ?", (x.id,))
        kept = [c.task for c in plan.copies if c.task not in gone]
        _log_change(conn, row.template, at, "removed", f"Took out {row.title}", len(gone), len(kept))
    return kept, gone


def _renumber(conn: sqlite3.Connection, ids: Sequence[int]) -> None:
    conn.executemany("UPDATE template_rows SET place = ? WHERE id = ?", [(i + 1, x) for i, x in enumerate(ids)])


def shift_row(conn: sqlite3.Connection, row_id: int, step: int) -> bool:
    """Move a row up (-1) or down (1) among those beside it. Only trees made afterwards see it (decision 188). Says whether it moved."""
    with transaction(conn):
        lib = Library(conn)
        row = lib.rows[row_id]
        if row.parent is None:
            return False
        ids = [r.id for r in lib.children(row.parent)]
        i = ids.index(row_id)
        j = i + step
        if not 0 <= j < len(ids):
            return False
        ids[i], ids[j] = ids[j], ids[i]
        _renumber(conn, ids)
    return True


def reparent_row(conn: sqlite3.Connection, row_id: int, parent: int) -> None:
    """Put a row under another row of its template, at the end. Only trees made afterwards see it (decision 188)."""
    with transaction(conn):
        lib = Library(conn)
        row, new = lib.rows[row_id], lib.rows[parent]
        if row.parent is None:
            raise TaskError("A template's top row can't go under another row.")
        if new.template != row.template or parent in [x.id for x, _ in lib.walk(row_id)]:
            raise TaskError("That would put the row under itself.")
        if row.parent == parent:
            return
        place = conn.execute("SELECT coalesce(max(place), 0) + 1 FROM template_rows WHERE parent = ?", (parent,)).fetchone()[0]
        conn.execute("UPDATE template_rows SET parent = ?, place = ? WHERE id = ?", (parent, place, row_id))


def place_row(conn: sqlite3.Connection, row_id: int, target: int, where: str) -> bool:
    """Put a row before or after another, or ``in`` it, at its end: what dragging a row does (decision 261). Only trees made afterwards
    see it (decision 188). Says whether it moved."""
    with transaction(conn):
        lib = Library(conn)
        if not can_place(lib, row_id, target, where):
            raise TaskError("A row can only go beside or under another row of its template, and not under itself.")
        row, near = lib.rows[row_id], lib.rows[target]
        parent = near.id if where == "in" else near.parent
        before = [r.id for r in lib.children(parent)]
        ids = [x for x in before if x != row_id]
        ids.insert(len(ids) if where == "in" else ids.index(target) + (where == "after"), row_id)
        if ids == before and row.parent == parent:
            return False
        conn.execute("UPDATE template_rows SET parent = ? WHERE id = ?", (parent, row_id))
        _renumber(conn, ids)
    return True


def can_place(lib: Library, row_id: int, target: int, where: str) -> bool:
    """Whether a row can go there: not the top row, not into another template, not under itself, and not beside a top row."""
    row, near = lib.rows.get(row_id), lib.rows.get(target)
    if row is None or near is None or row.parent is None or row.template != near.template or target in [x.id for x, _ in lib.walk(row_id)]:
        return False
    return where == "in" or near.parent is not None


def duplicate(conn: sqlite3.Connection, template_id: int, name: str, at: datetime) -> int:
    """A new template with the same rows, in the same order, and all they hold (decision 262). It's a template of its own: no trees,
    no Changes, and no tie to the original. Returns its top row."""
    name = name.strip()
    if not name:
        raise TaskError("A template needs a name.")
    with transaction(conn):
        lib = Library(conn)
        copy = conn.execute("INSERT INTO templates (created) VALUES (?)", (stamp(at),)).lastrowid
        made: dict[int, int] = {}
        for row, _ in lib.walk(lib.templates[template_id].top):
            values = {k: getattr(row, k) for k in (*_COLUMNS, "leads", "assignees", "labels", "involvement")}
            if row.parent is None:
                values["title"] = name
            made[row.id] = _insert_row(conn, copy, made.get(row.parent), values)
    return made[lib.templates[template_id].top]


def set_discarded(conn: sqlite3.Connection, template_id: int, reason: str | None, at: datetime) -> None:
    """Discard a template, with the reason, or bring it back (``reason`` None). It's never deleted, and its tasks keep their
    values and stop showing marks until it's back."""
    conn.execute("UPDATE templates SET discarded = ?, discard_reason = ? WHERE id = ?", (stamp(at) if reason else None, reason, template_id))


# ---- a task's own link: Edit task's marks, and Detach (decision 184) ----
@dataclass
class TaskLink:
    """What Edit task's marks need: the row, the template's name, the row's path in words, the fields that follow it now, and
    whether the task is its tree's top, whose title is its own."""

    row: Row
    name: str
    path: str
    links: set[str]
    top: bool


def task_link(conn: sqlite3.Connection, task_id: str) -> TaskLink | None:
    """A task's link for Edit task's marks. None for a task with no template, or while its template is discarded."""
    lib = Library(conn)
    c = lib.copies.get(task_id)
    if c is None or lib.template_of(c.row).discarded:
        return None
    return TaskLink(lib.rows[c.row], lib.name(lib.rows[c.row].template), " › ".join(x.title for x in lib.path(c.row)), lib.links.get(task_id, set()), c.task == c.tree)


def detach(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, at: datetime) -> edits.Outcome:
    """Detach from template: all of a task's links end, and its values stay (decision 184)."""
    name = tasks.template_name(conn, task_id)
    if name is None:
        raise TaskError("That task didn't come from a template.")
    with transaction(conn):
        conn.execute("DELETE FROM task_links WHERE task = ?", (task_id,))
        conn.execute("DELETE FROM task_template WHERE task = ?", (task_id,))
        tasks.record(conn, task_id, at, edits.BROWSE, [Change(TEMPLATE_LINK, f"No longer follows {name}", None)])
    out = edits.Outcome(f"Detached. Its values stay, and it won't follow {name} any more.")
    edits.write_all_pages(conn, data_root, fs, at, out.problems)
    return out


# ---- making tasks ----
def page_body(notes: str) -> str:
    """Starting notes as a task's notes page: the same lines a capture's text makes there."""
    lines = notes.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(notes_page.heading_line(h[1], h[0]) if (h := markup.heading_of(line)) else notes_page.text_line(markup.text_of(line))
                     for line in lines)


@dataclass
class Choice:
    """What Make tasks' dialog says for one row: its Start, and its people, when they aren't the row's."""

    start: str | None = None
    leads: Sequence[str] | None = None
    assignees: Sequence[str] | None = None
    duration: int | None | object = ...  # ... is the row's own


def _copy_row(conn: sqlite3.Connection, settings: Settings, row: Row, title: str, parents: Sequence[str], created_by: str, tree: str | None,
              c: Choice, top: bool, at: datetime) -> str:
    """One task from one row, its fields linked and its starting notes copied. ``tree`` None makes it its own tree's top."""
    copy = replace(row, leads=list(row.leads if c.leads is None else c.leads), assignees=list(row.assignees if c.assignees is None else c.assignees),
                   duration=row.duration if c.duration is ... else c.duration)
    task_id = tasks.create_task(
        conn, settings, title=title, at=at, created_by=created_by, parents=parents, description=row.description, start=c.start or None,
        recurrence=row.recurrence, urgent=row.urgent, meeting=row.meeting, plant_event=row.plant_event, leads=copy.leads, assignees=copy.assignees,
        lead_hours=row.lead_hours, assignee_hours=row.assignee_hours, labels=row.labels, inherit_labels=row.inherit_labels, duration=copy.duration,
        calendar_days=row.calendar_days, **{k: getattr(row, k) for k in RATE_FIELDS}, involvement=row.involvement)
    conn.execute("INSERT INTO task_template (task, row_id, tree) VALUES (?, ?, ?)", (task_id, row.id, tree or task_id))
    conn.executemany("INSERT INTO task_links (task, field) VALUES (?, ?)",
                     [(task_id, k) for k in FIELDS if fills(row, k) and stated(copy, k) == stated(row, k) and not (k == "title" and top)])
    if row.notes.strip():
        notes_page.put(conn, task_id, page_body(row.notes), at)
    return task_id


def make_tasks(conn: sqlite3.Connection, settings: Settings, row_id: int, name: str, under: str | None, choices: Mapping[int, Choice],
               at: datetime) -> list[str]:
    """Copy a row and what's under it into the task tree, under ``under`` if it's given. Returns the new tasks, the top one
    first. Each field the row fills starts linked, unless ``choices`` gives it a value of its own; the top task's title is
    its own, as it's typed here (the design's table). Nothing goes on Today, and starting notes are copied once (decision 194)."""
    lib = Library(conn)
    root = lib.rows.get(row_id)
    if root is None:
        raise TaskError("That row isn't in a template any more.")
    template = lib.templates[root.template]
    if template.discarded:
        raise TaskError(f"{lib.name(template.id)} is discarded. Bring it back to make tasks from it.")
    title = " ".join(name.split()) or (root.title if root.parent is not None else "")
    if not title:
        raise TaskError("Give the new task a name, such as Trial 5: gloss finish.")
    created_by = f"Template: {lib.name(template.id)}"
    made: dict[int, str] = {}
    with transaction(conn):
        for row, _ in lib.walk(row_id):
            top = row.id == row_id
            made[row.id] = _copy_row(conn, settings, row, title if top else row.title, ([under] if under else []) if top else [made[row.parent]],
                                     created_by, None if top else made[row_id], choices.get(row.id, Choice()), top, at)
    return list(made.values())


# ---- Save as template (decision 195) ----
def save_as_template(conn: sqlite3.Connection, settings: Settings, task_id: str, name: str, link: bool, at: datetime, via: str = edits.BROWSE) -> int:
    """A new template from a task and what's under it: their fields, without dates, state, status, notes or captures. A
    discarded subtask is left out. A task's length becomes its row's Duration, whether it's typed or what its two dates hold.
    With ``link``, these tasks then follow it, as a tree made from it does, and each takes that Duration. Returns its top row."""
    workdays = workday_numbers(settings.workdays)
    m = Model(conn)
    if task_id not in m.tasks:
        raise TaskError(f"There's no task {task_id}.")
    title = " ".join(name.split())
    if not title:
        raise TaskError("A template needs a name.")
    with transaction(conn):
        template = conn.execute("INSERT INTO templates (created) VALUES (?)", (stamp(at),)).lastrowid
        seen: set[str] = set()
        top = 0

        def walk(tid: str, parent: int | None) -> None:
            nonlocal top
            if tid in seen or m.task(tid).discarded:
                return
            seen.add(tid)
            t = m.task(tid)
            days = t.duration if t.recurrence else length_of(t.start, t.due, t.duration, workdays, t.calendar_days)
            v = _checked(conn, {k: getattr(t, k) for k in FIELDS} | {"title": title if parent is None else t.title, "duration": days,
                                                                      **{k: getattr(t, k) for k in RATE_FIELDS}, "involvement": t.involvement})
            row_id = _insert_row(conn, template, parent, v)
            top = top or row_id
            if link:
                conn.execute("DELETE FROM task_links WHERE task = ?", (tid,))
                conn.execute("INSERT INTO task_template (task, row_id, tree) VALUES (?, ?, ?) "
                             "ON CONFLICT(task) DO UPDATE SET row_id = excluded.row_id, tree = excluded.tree", (tid, row_id, task_id))
                row = Row(row_id, template, parent, 0, v["title"], **{k: v[k] for k in (*FIELDS, *RATE_FIELDS, "involvement") if k != "title"})
                conn.executemany("INSERT INTO task_links (task, field) VALUES (?, ?)",
                                 [(tid, k) for k in FIELDS if fills(row, k) and not (k == "title" and parent is None)])
                tasks.record(conn, tid, at, via, [Change(TEMPLATE_LINK, None, f"Follows {title}")])
                if days != t.duration:
                    tasks.update_task(conn, settings, tid, at=at, via=via, keep_links=True, duration=days)
            for child in m.children_of(tid):
                walk(child, row_id)

        walk(task_id, None)
    return top


# ---- from the browse tool: the change, then its files ----
def _people_ids(conn: sqlite3.Connection, who: Sequence[Who | str], at: datetime, added: list[str]) -> list[str]:
    """Names the owner typed in a form are added to the people list, as Edit task does."""
    from docrepo import people

    note = f"Added on {at.date().isoformat()} in the browse tool. Aliases and hours aren't set yet."
    out = []
    for w in who:
        if isinstance(w, str):
            out.append(w)
        elif w.id:
            out.append(w.id)
        else:
            person_id, new = people.find_or_add(conn, w.name, note)
            if new:
                added.append(w.name.strip())
            out.append(person_id)
    return out


def _form_values(conn: sqlite3.Connection, values: Mapping, at: datetime, added: list[str]) -> dict:
    """A row's form, with any new label or person made: a label not there yet is created, as in Edit task."""
    from docrepo import people

    out = dict(values)
    for name in out.get("labels", ()):
        if conn.execute("SELECT 1 FROM labels WHERE name = ?", (name.strip(),)).fetchone() is None:
            people.add_label(conn, name)
    named: dict[str, str] = {}
    for key in ROLES:
        who = list(out.get(key, ()))
        ids = _people_ids(conn, who, at, added)
        named.update({w.name: i for w, i in zip(who, ids) if not isinstance(w, str) and not w.id})
        out[key] = ids
    if out.get("involvement"):  # someone just added has their Involvement under their name until now
        out["involvement"] = {(role, named.get(p, p)): share for (role, p), share in out["involvement"].items()}
    return out


def _said_added(message: str, added: list[str]) -> str:
    return message + (f" Added {', '.join(added)} to the people list." if added else "")


def save_row(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, row_id: int, values: Mapping, at: datetime,
             left: Collection[str] = ()) -> edits.Outcome:
    """Save a row's form, after its preview."""
    added: list[str] = []
    plan = apply_row(conn, settings, row_id, values, at, left, added)
    reached = len(plan.items) - sum(1 for i in plan.items if i.task in left)
    stayed = len(plan.items) - reached
    if plan.items:
        message = f"{plural(reached, 'task')} changed" + (f", {stayed} left as {'it was' if stayed == 1 else 'they were'}" if stayed else "") + ". Each status log says so."
    elif not plan.changed and plan.notes_changed:
        message = "Saved. Starting notes reach only new tasks."
    elif not plan.changed:
        message = "Nothing changed."
    elif plan.not_changing or plan.ending:
        message = "Saved. No task's value changes."
    else:
        message = "Saved. No tasks follow it yet."
    out = edits.Outcome(_said_added(message, added))
    if added or plan.items or plan.ending:
        edits.write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def new_row(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, parent: int, values: Mapping, at: datetime,
            left: Collection[str] = ()) -> tuple[int, edits.Outcome]:
    """Add a row from its form, after its preview. Returns the row, and what to say."""
    added: list[str] = []
    row_id, plan, made = add_row(conn, settings, parent, values, at, left, added)
    n = len(made)
    message = f"Added to {plural(n, 'tree')}, undated, so it shows in Plan mode's undated rows." if n else "Added. New trees will have it."
    out = edits.Outcome(_said_added(message, added))
    if made:
        search.index_pages(conn, made)
    if added or made:
        edits.write_all_pages(conn, data_root, fs, at, out.problems)
    return row_id, out


def take_out(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, row_id: int, at: datetime,
             discard: Collection[str] = ()) -> edits.Outcome:
    """Take a row out, after its preview."""
    kept, gone = remove_row(conn, settings, row_id, at, discard)
    words = []
    if gone:
        words.append(f"{plural(len(gone), 'copy').replace('copys', 'copies')} discarded, and Bring back restores {'it' if len(gone) == 1 else 'them'}")
    if kept:
        words.append(f"{plural(len(kept), 'task')} made from it stay{'' if len(kept) != 1 else 's'}, no longer following")
    out = edits.Outcome("Taken out." + (f" {'; '.join(words).capitalize()}." if words else ""))
    if kept or gone:
        edits.write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def make(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, row_id: int, name: str, under: str | None,
         choices: Mapping[int, Choice], at: datetime) -> tuple[list[str], edits.Outcome]:
    """Make tasks from the browse tool: the tasks, their search text and their pages. Returns the new tasks, and what to say."""
    made = make_tasks(conn, settings, row_id, name, under, choices, at)
    n, undated = len(made), [t for t in Model(conn).tasks.values() if t.id in made and not t.start and not t.due and not t.deadline]
    out = edits.Outcome(f"Made {n} task{'s' if n != 1 else ''}." + (f" {len(undated)} undated, waiting for dates." if undated else ""))
    search.index_pages(conn, made)
    edits.write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("made %d tasks from template row %d", n, row_id)
    return made, out


def save_as(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, name: str, link: bool, at: datetime) -> tuple[int, edits.Outcome]:
    """Save as template from the browse tool. Returns its top row, and what to say."""
    top = save_as_template(conn, settings, task_id, name, link, at)
    rows = len(Library(conn).walk(top))
    out = edits.Outcome(f"Saved {' '.join(name.split())}, with {rows} row{'s' if rows != 1 else ''}." + (" This tree now follows it." if link else ""))
    if link:
        edits.write_all_pages(conn, data_root, fs, at, out.problems)
    return top, out
