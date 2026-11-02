"""Task templates (releases 5.44 and 5.45; the task templates design in the design workspace, decisions 180 to 199).

A template is a small tree of rows without dates, in tables of its own, so nothing that reads tasks can see one (decision
180). Its name and description are its top row's. **Make tasks** copies a row and what's under it into the task tree, as
ordinary tasks. Each field a row fills starts linked on the task made from it (decision 183): ``task_links`` names the fields
still following it, and an open task's linked field holds its row's value, always:

- ``tasks.update_task`` ends a link when a different value is written to the field (decision 184);
- saving a row writes the new value to the tasks following it, or ends the links of those unticked in the preview (decisions
  186 and 198). Closed and discarded tasks never change, and fall behind until they come back (decision 185).

Each change to a template works out what it would do first, with nothing changed (``preview_row``, ``preview_new_row``,
``preview_remove`` and ``preview_timing``), and the browse tool shows that before it's made. The status log of each task says what reached it, and
the template keeps a Changes list (decision 187).

Only the Templates view, Make tasks, Save as template, the previews and tree files (``docrepo/tree_files.py``) read these tables, through a
``Library``. The Model knows only where each task came from (``model.TemplateOrigin``).

Since release 5.51 a template has a timing: an anchor, and ties on its rows, whose sums are in ``timing``. A task made from a row
carries that tie as an ordinary tie, pointing at its own tree's copy of the source, and ``start_tie`` and ``due_tie`` in ``task_links``
say its gap still follows the row's number (decisions 247 and 248).
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from docrepo import agenda, edits, markup, notes_page, search, tasks, ties, timing
from docrepo.config import Settings
from docrepo.dates import long_date, short, stamp, to_date, workday_numbers
from docrepo.db import transaction
from docrepo.model import Model, Tie
from docrepo.pages import num
from docrepo.parse import Who
from docrepo.safe_fs import SafeFS
from docrepo.schedule import length_of
from docrepo.stories import clip
from docrepo.tasks import FIELD_NAMES, LINK_NAMES, RATE_FIELDS, RATES, TEMPLATE_LINK, TIE_LINKS, WEEK_RATES, Change, TaskError, _normalize, hours_values, stated, worked_out
from docrepo.timing import RowTie

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
    ties: dict[str, RowTie] = field(default_factory=dict)


@dataclass
class Template:
    id: int
    created: str
    discarded: str | None = None
    discard_reason: str | None = None
    top: int = 0  # its top row
    anchor: int | None = None  # the row other rows tie to by default (decision 248)


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
        self.templates: dict[int, Template] = {r["id"]: Template(r["id"], r["created"], r["discarded"], r["discard_reason"], anchor=r["anchor_row"])
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
        for r in q("SELECT * FROM template_row_ties"):
            self.rows[r["row_id"]].ties[r["field"]] = RowTie(r["source_row"], r["point"], r["amount"], r["unit"], r["direction"])
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

    def copy_in(self, row_id: int, tree: str) -> str | None:
        """A tree's copy of a row."""
        return next((c.task for c in self.copies.values() if c.row == row_id and c.tree == tree), None)

    def spans(self, row: Row) -> bool:
        """A row with subtasks and no dates of its own spans them, so it gives nothing to tie to and can't be the anchor (decision 250)."""
        return row.id in self._children and row.duration is None and not row.ties and self.templates[row.template].anchor != row.id

    def lines(self, template_id: int) -> list[timing.Line]:
        """Its rows, in order, as the chart and the Timing window see them."""
        return [timing.Line(x.id, x.title, d, x.parent, self.spans(x), x.duration, dict(x.ties), bool(x.recurrence))
                for x, d in self.walk(self.templates[template_id].top)]

    def titles(self, template_id: int) -> dict[int, str]:
        return {x.id: x.title for x, _ in self.walk(self.templates[template_id].top)}

    def tie_words(self, row: Row, f: str) -> str:
        """A row's tie as a sentence: "30 workdays before the anchor starts"."""
        return timing.words(row.ties[f], self.titles(row.template))


def days_text(days: int) -> str:
    return plural(days, "day")


def tie_on(lib: Library, row: Row, f: str, tree: str) -> Tie | None:
    """A row's tie as it stands on its copy in a tree, counting from that tree's copy of its source (decision 248). None if it has no
    tie there, or that source isn't in the tree, as with Make tasks from a row (decision 256)."""
    tie = row.ties.get(f)
    src = timing.source_of(tie, lib.templates[row.template].anchor) if tie else None
    task = lib.copy_in(src, tree) if src is not None and src != row.id else None
    return Tie(task, tie.point, tie.amount, tie.unit, tie.direction) if task else None


def list_summary(row: Row, titles: dict[int, str]) -> str:
    """A row in the Templates list: what it's tied to and how long it is, when it's tied, or its calm summary."""
    if not row.ties:
        return summary(row)
    return " · ".join(x for x in (timing.timing_words(row.ties, titles), days_text(row.duration) if row.duration else "") if x)


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


def own_ties(lib: Library, row: Row, task, tree: str, links: set[str]) -> list[str]:
    """The ties a row has where a task has gone its own way: no longer following, with a different gap or none (decision 247)."""
    return [TIE_LINKS[f] for f in timing.FIELDS if (tie := tie_on(lib, row, f, tree)) and TIE_LINKS[f] not in links and task.ties.get(f) != tie]


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
    given = values.get("ties")  # none given leaves a row's as they are
    out["ties"] = {} if out["recurrence"] else None if given is None else {f: x for f, x in given.items() if x}
    return out


def _settled_ties(lib: Library, template_id: int, row_id: int, title: str, v: dict) -> None:
    """A form's ties for a row, in place: one counting from an anchor there isn't goes, and with both tied the length comes from them
    (decision 251). What can't stand says why (decisions 250 and 253)."""
    if v["ties"] is None:
        return
    anchor = lib.templates[template_id].anchor
    v["ties"] = {} if row_id == anchor else {f: x for f, x in v["ties"].items() if x.source is not None or anchor is not None}
    lines = lib.lines(template_id)
    if row_id not in [x.id for x in lines]:
        lines.append(timing.Line(row_id, title))
    said = timing.problem([replace(x, ties=v["ties"]) if x.id == row_id else x for x in lines], anchor)
    if said:
        raise TaskError(said)
    if len(v["ties"]) == 2:
        v["duration"] = None


_COLUMNS = ("title", "description", "inherit_labels", "lead_hours", "assignee_hours", "urgent", "meeting", "plant_event", "recurrence", "notes", "duration",
            "calendar_days", *RATE_FIELDS)


def _store_lists(conn: sqlite3.Connection, row_id: int, v: Mapping) -> None:
    conn.execute("DELETE FROM template_row_people WHERE row_id = ?", (row_id,))
    conn.execute("DELETE FROM template_row_labels WHERE row_id = ?", (row_id,))
    for key, role in ROLES.items():
        conn.executemany("INSERT INTO template_row_people (row_id, person, role, involvement) VALUES (?, ?, ?, ?)",
                         [(row_id, p, role, v["involvement"].get((role, p), 100)) for p in v[key]])
    conn.executemany("INSERT INTO template_row_labels (row_id, label) SELECT ?, id FROM labels WHERE name = ?", [(row_id, n) for n in v["labels"]])


def _store_row_ties(conn: sqlite3.Connection, row_id: int, given: Mapping[str, RowTie]) -> None:
    conn.execute("DELETE FROM template_row_ties WHERE row_id = ?", (row_id,))
    conn.executemany("INSERT INTO template_row_ties (row_id, field, source_row, point, amount, unit, direction) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     [(row_id, f, x.source, x.point, x.amount, x.unit, x.direction) for f, x in given.items()])


def _insert_row(conn: sqlite3.Connection, template: int, parent: int | None, v: Mapping) -> int:
    place = conn.execute("SELECT coalesce(max(place), 0) + 1 FROM template_rows WHERE template = ? AND parent IS ?", (template, parent)).fetchone()[0]
    columns = {"template": template, "parent": parent, "place": place, **{k: v[k] for k in _COLUMNS}}
    cur = conn.execute(f"INSERT INTO template_rows ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", tuple(columns.values()))
    _store_lists(conn, cur.lastrowid, v)
    _store_row_ties(conn, cur.lastrowid, v.get("ties") or {})
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
        tasks.record(conn, task_id, at, f"Template: {name}", [Change(TEMPLATE_LINK, f"{LINK_NAMES[k]}: no longer follows {name}", None)
                                                              for k in (*FIELDS, *TIE_LINKS.values()) if k in keys])


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
    #: Tasks that aren't its copies but move with them, by their ties, each listed so it can be unticked (decision 257).
    moved: list[Reached] = field(default_factory=list)
    followed: int = 0  # how many moved that way when it was saved


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
        if k in TIE_LINKS.values():
            continue
        if k in RATES:
            value = stated(row, k)
            out.update(hours_values(k, value[0][2:], value[1]) if isinstance(value, tuple) else hours_values(k, "all", value))
        else:
            out[k] = getattr(row, k)
        if k in ROLES:
            shares = out.get("involvement", t.involvement)
            out["involvement"] = {x: v for x, v in shares.items() if x[0] != ROLES[k]} | {x: v for x, v in row.involvement.items() if x[0] == ROLES[k]}
    return out


def _own_words(m: Model, t, key: str) -> str:
    """What a task has of its own that a row's change leaves alone: "assignee hours 20 h", "start tie, 8 workdays before Line 2 outage ends"."""
    for f, tie_key in TIE_LINKS.items():
        if key == tie_key:
            tie = t.ties.get(f)
            return f"{f} tie, {ties.words(tie, ties.name_in(m, tie))}" if tie else f"{f} date"
    return f"{FIELD_NAMES[key].lower()} {field_text(m, key, stated(t, key))}"


def _can_repeat(lib: Library, row: Row, title: str) -> None:
    """A row that repeats has no one date to give (decision 250), so it can't be the anchor, or what another row counts from."""
    anchor = lib.templates[row.template].anchor
    if anchor == row.id:
        raise TaskError(f"{title} is the template's anchor, so it can't repeat. Choose another anchor in Timing first.")
    tied = [x.title for x in lib.lines(row.template) if any(timing.source_of(t, anchor) == row.id for t in x.ties.values())]
    if tied:
        raise TaskError(f"{', '.join(tied)} {'is' if len(tied) == 1 else 'are'} tied to {title}, so it can't repeat. Change that in Timing first.")


def _tie_line(f: str, was: RowTie | None, now: RowTie | None, titles: Mapping[int, str]) -> str:
    return f"{timing.FIELDS[f]} tie {timing.words(was, titles) if was else 'None'} → {timing.words(now, titles) if now else 'None'}"


def _plan_row(conn: sqlite3.Connection, settings: Settings, row_id: int, v: dict) -> RowPlan:
    lib, m = Library(conn), Model(conn)
    workdays = workday_numbers(settings.workdays)
    before = lib.rows.get(row_id)
    if before is None:
        raise TaskError("That row isn't in a template any more.")
    _settled_ties(lib, before.template, row_id, v["title"], v)
    if v["recurrence"]:
        _can_repeat(lib, before, v["title"])
    after = replace(before, ties=before.ties if v["ties"] is None else v["ties"], **{k: v[k] for k in (*FIELDS, "notes", *RATE_FIELDS, "involvement")})
    changed = [k for k in FIELDS if stated(before, k) != stated(after, k)]
    name = after.title if before.parent is None else lib.name(before.template)
    tied = [f for f in timing.FIELDS if before.ties.get(f) != after.ties.get(f)]
    titles = lib.titles(before.template)
    plan = RowPlan(row_id, after.title, before.template, name, [*changed, *(TIE_LINKS[f] for f in tied)],
                   [*(_change_line(m, k, stated(before, k), stated(after, k)) for k in changed), *(_tie_line(f, before.ties.get(f), after.ties.get(f), titles) for f in tied)],
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
        new_ties: dict[str, Tie] = {}
        for f in () if t.recurrence else tied:  # decision 198, as for any field: a row that starts having one reaches a task with no date there
            key, tie = TIE_LINKS[f], tie_on(lib, after, f, c.tree)
            if tie is None:
                if key in linked:
                    plan.ending.setdefault(c.task, []).append(key)
            elif key in linked or (f not in t.ties and not getattr(t, f)):
                will.append(key)
                new_ties[f] = tie
            elif t.ties.get(f) != tie:
                own.append(key)
        if t.discarded or t.state == "Closed":  # decision 185: they never change
            if will:
                why = "discarded" if t.discarded else "closed"
                plan.not_changing.append(NotChanging(c.task, tree, why, f"{why}, so it keeps what it ended with"))
            continue
        if will:
            values = _as_changes(after, will, t)
            if new_ties:
                values["ties"] = {**t.ties, **new_ties}
            sim = replace(t, **worked_out(t, values, workdays)[0])
            plan.items.append(Reached(c.task, tree, t.state, will, values, _task_lines(m, t, sim), work_of(t), work_of(sim)))
        elif own:
            plan.not_changing.append(NotChanging(c.task, tree, "own", "its own " + ", ".join(_own_words(m, t, k) for k in own)))
    return plan


def _dates_of(t) -> tuple:
    return t.start, t.due, t.duration


def _named(m: Model, task_id: str) -> str:
    """A task in a list of what moved: "Trial 3 › Change record prep", as several trees have the same titles."""
    t = m.task(task_id)
    top = sorted(ties.tops(m.parents_of, task_id))[0]
    return t.title if top == task_id else f"{m.task(top).title} › {t.title}"


def _moved_items(before: Model, after: Model, order: Sequence[str] = ()) -> list[Reached]:
    """Each task whose dates a change moved, those in ``order`` first, in that order."""
    ids = [*(x for x in order if x in after.tasks), *(x for x in after.tasks if x not in order)]
    return [Reached(x, _named(after, x), before.task(x).state, [], {}, _task_lines(before, before.task(x), after.task(x)), work_of(before.task(x)), work_of(after.task(x)))
            for x in ids if x in before.tasks and _dates_of(before.task(x)) != _dates_of(after.task(x))]


def _read_moves(plan: RowPlan, before: Model, after: Model) -> None:
    """What a row's change really did, for its preview: each copy's lines, and what moved with them."""
    mine = {i.task: i for i in plan.items}
    for x in plan.items:
        was, now = before.task(x.task), after.task(x.task)
        x.lines = _task_lines(before, was, now) + [f"{timing.FIELDS[f]} tie {ties.words(a, ties.name_in(before, a)) if a else 'None'} → {ties.words(b, ties.name_in(after, b)) if b else 'None'}"
                                                   for f in timing.FIELDS if (a := was.ties.get(f)) != (b := now.ties.get(f))]
        x.work_after = work_of(now)
    plan.moved = [x for x in _moved_items(before, after) if x.task not in mine]


class _Preview(Exception):
    """Raised to roll a preview's changes back."""


def preview_row(conn: sqlite3.Connection, settings: Settings, row_id: int, values: Mapping, at: datetime) -> RowPlan:
    """What saving a row's form would do, with nothing changed: any new person or label is made and rolled back, as Edit
    selected's preview does."""
    plan: RowPlan | None = None
    try:
        with transaction(conn):
            v = _checked(conn, _form_values(conn, values, at, []))
            plan = _plan_row(conn, settings, row_id, v)
            if plan.items:  # it's made and rolled back, so what moves with its copies can be listed too
                before = Model(conn)
                _write_row(conn, settings, plan, row_id, v, at, ())
                _read_moves(plan, before, Model(conn))
            raise _Preview
    except _Preview:
        pass
    assert plan is not None
    return plan


def _write_row(conn: sqlite3.Connection, settings: Settings, plan: RowPlan, row_id: int, v: Mapping, at: datetime, left: Collection[str]) -> None:
    """A row's change, as planned, in the caller's transaction."""
    conn.execute(f"UPDATE template_rows SET {', '.join(f'{k} = ?' for k in _COLUMNS)} WHERE id = ?", (*(v[k] for k in _COLUMNS), row_id))
    _store_lists(conn, row_id, v)
    if v["ties"] is not None:
        _store_row_ties(conn, row_id, v["ties"])
    via, name = f"Template: {plan.name}", plan.name
    reached = 0
    for item in plan.items:
        if item.task in left:
            _ended(conn, item.task, item.keys, name, at)
            continue
        logged = tasks.update_task(conn, settings, item.task, at=at, via=via, keep_links=True, leave=left, **item.fields)
        plan.followed += len(logged.followed)
        conn.executemany("INSERT OR IGNORE INTO task_links (task, field) VALUES (?, ?)", [(item.task, k) for k in item.keys])
        reached += 1
    for task_id, keys in plan.ending.items():
        _ended(conn, task_id, keys, name, at)
    words = [*plan.lines, *(["Starting notes changed"] if plan.notes_changed else [])]
    if words:
        _log_change(conn, plan.template, at, "changed", f"{plan.title} · {', '.join(words)}", reached, len(plan.items) - reached)


def apply_row(conn: sqlite3.Connection, settings: Settings, row_id: int, values: Mapping, at: datetime, left: Collection[str] = (),
              added: list[str] | None = None) -> RowPlan:
    """Save a row (decision 186): each task following it takes the new value, but those in ``left``, unticked in the
    preview, which keep their value and stop following those fields. A field the row starts filling reaches only empty
    tasks, and they then follow it; one it stops filling changes no values (decision 198). Each change is in the task's
    status log, as "Template: *name*", and the template's Changes list says so (decision 187). Returns what it did."""
    with transaction(conn):
        v = _checked(conn, _form_values(conn, values, at, added if added is not None else []))
        plan = _plan_row(conn, settings, row_id, v)
        _write_row(conn, settings, plan, row_id, v, at, left)
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
    tied: str = ""  # what it's tied to, in words, when it arrives tied (decision 257)


def _plan_add(conn: sqlite3.Connection, parent: int, v: dict) -> AddPlan:
    lib, m = Library(conn), Model(conn)
    p = lib.rows.get(parent)
    if p is None:
        raise TaskError("That row isn't in a template any more.")
    _settled_ties(lib, p.template, 0, v["title"], v)
    row = Row(0, p.template, parent, 0, ties=v["ties"] or {}, **{k: v[k] for k in (*FIELDS, "notes", *RATE_FIELDS, "involvement")})
    titles = lib.titles(p.template)
    plan = AddPlan(row.title, parent, p.title, p.template, lib.name(p.template), summary(row),
                   tied=", ".join(("" if f == "start" else "Due ") + timing.words(row.ties[f], titles).replace("The day", "the day") for f in timing.FIELDS if f in row.ties))
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
    parent, or under the tree's top task if that's gone. A row with a tie arrives tied, placed from that tree's own rows. New trees
    always have it. Returns the row, the plan, and the tasks made."""
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
            _tie_copy(conn, settings, lib, row, made[-1], tree.task, via, at)
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
    untied: list[str] = field(default_factory=list)  # the rows left that were tied to it, which are placed by hand from then on


def _tied_to(lib: Library, going: Collection[int], template_id: int) -> list[tuple[Row, str]]:
    """The ties of rows that stay, whose source is going: each row, and which of its dates."""
    anchor = lib.templates[template_id].anchor
    return [(x, f) for x, _ in lib.walk(lib.templates[template_id].top) if x.id not in going for f, tie in x.ties.items() if timing.source_of(tie, anchor) in going]


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
    plan = RemovePlan(row.title, lib.name(row.template), len(walked), untied=list(dict.fromkeys(x.title for x, _ in _tied_to(lib, [x.id for x, _ in walked], row.template))))
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
        going = [x.id for x, _ in walked]
        for x, f in _tied_to(lib, going, row.template):  # the rows left are placed by hand from now on, and their tasks stay tied, as their own
            conn.execute("DELETE FROM template_row_ties WHERE row_id = ? AND field = ?", (x.id, f))
            for c in lib.copies_of(x.id):
                if TIE_LINKS[f] in lib.links.get(c.task, ()):
                    _ended(conn, c.task, [TIE_LINKS[f]], name, at)
        if lib.templates[row.template].anchor in going:
            conn.execute("UPDATE templates SET anchor_row = NULL WHERE id = ?", (row.template,))
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
            conn.execute("DELETE FROM template_row_ties WHERE row_id = ?", (x.id,))
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
        for row, _ in lib.walk(lib.templates[template_id].top):  # its ties and anchor point inside the copy
            _store_row_ties(conn, made[row.id], {f: replace(x, source=None if x.source is None else made[x.source]) for f, x in row.ties.items()})
        if lib.templates[template_id].anchor is not None:
            conn.execute("UPDATE templates SET anchor_row = ? WHERE id = ?", (made[lib.templates[template_id].anchor], copy))
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
    ties: dict[str, Tie] = field(default_factory=dict)  # the row's ties, as they'd stand on this task
    tie_words: dict[str, str] = field(default_factory=dict)  # the same, in words


def task_link(conn: sqlite3.Connection, task_id: str) -> TaskLink | None:
    """A task's link for Edit task's marks. None for a task with no template, or while its template is discarded."""
    lib = Library(conn)
    c = lib.copies.get(task_id)
    if c is None or lib.template_of(c.row).discarded:
        return None
    row = lib.rows[c.row]
    row_ties = {f: x for f in timing.FIELDS if (x := tie_on(lib, row, f, c.tree))}
    return TaskLink(row, lib.name(row.template), " › ".join(x.title for x in lib.path(c.row)), lib.links.get(task_id, set()), c.task == c.tree, row_ties,
                    {f: lib.tie_words(row, f) for f in row_ties})


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
    """What Make tasks' dialog says for one row: its Start, and its people, when they aren't the row's. On a tied row, a Start or Due
    is a date typed over the one worked out, which gives it a new gap. ``tie`` is a tie of the task's own, as the anchor can have
    from Tie… (decision 256), and ``due`` is the Due typed there."""

    start: str | None = None
    leads: Sequence[str] | None = None
    assignees: Sequence[str] | None = None
    duration: int | None | object = ...  # ... is the row's own
    due: str | None = None
    tie: Tie | None = None


def _tie_copy(conn: sqlite3.Connection, settings: Settings, lib: Library, row: Row, task_id: str, tree: str, via: str, at: datetime) -> None:
    """A new copy in a tree already made takes its row's ties, each following the row's number, and lands where they put it (decision 257)."""
    tied = {f: x for f in timing.FIELDS if (x := tie_on(lib, row, f, tree))}
    if tied:
        tasks.update_task(conn, settings, task_id, at=at, via=via, keep_links=True, ties=tied)
        conn.executemany("INSERT OR IGNORE INTO task_links (task, field) VALUES (?, ?)", [(task_id, TIE_LINKS[f]) for f in tied])


def _copy_row(conn: sqlite3.Connection, settings: Settings, row: Row, title: str, parents: Sequence[str], created_by: str, tree: str | None,
              c: Choice, top: bool, at: datetime) -> str:
    """One task from one row, its fields linked and its starting notes copied. ``tree`` None makes it its own tree's top."""
    copy = replace(row, leads=list(row.leads if c.leads is None else c.leads), assignees=list(row.assignees if c.assignees is None else c.assignees),
                   duration=row.duration if c.duration is ... else c.duration)
    task_id = tasks.create_task(
        conn, settings, title=title, at=at, created_by=created_by, parents=parents, description=row.description, start=c.start or None, due=c.due or None,
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
    its own, as it's typed here (the design's table). Nothing goes on Today, and starting notes are copied once (decision 194).

    A row's ties come too, each following the row's number, and the tasks land where they put them, or wait until the anchor has a date.
    A tie whose source isn't among what's being made is dropped (decision 256)."""
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
    walked = [x for x, _ in lib.walk(row_id)]
    inside = {x.id for x in walked}
    anchor = template.anchor
    tied = {x.id: {f: t for f, t in x.ties.items() if timing.source_of(t, anchor) in inside - {x.id}} for x in walked}
    with transaction(conn):
        for row in walked:
            top = row.id == row_id
            c = choices.get(row.id, Choice())
            made[row.id] = _copy_row(conn, settings, row, title if top else row.title, ([under] if under else []) if top else [made[row.parent]],
                                     created_by, None if top else made[row_id], replace(c, start=None, due=None) if tied[row.id] or c.tie else c, top, at)
        _place_tree(conn, settings, walked, made, tied, anchor, choices, created_by, at)
    return list(made.values())


def _place_tree(conn: sqlite3.Connection, settings: Settings, walked: Sequence[Row], made: Mapping[int, str], tied: Mapping[int, Mapping[str, RowTie]],
                anchor: int | None, choices: Mapping[int, Choice], via: str, at: datetime) -> None:
    """A tree's ties, sources first, each following its row's number, and then any date typed over one worked out, which keeps its tie
    with a new gap (decision 256)."""
    order = ties.chain(timing.followers([timing.Line(x.id, x.title, ties=tied[x.id]) for x in walked], anchor), [x.id for x in walked])  # sources first
    for rid in order:
        c = choices.get(rid, Choice())
        if tied[rid]:
            tasks.update_task(conn, settings, made[rid], at=at, via=via, keep_links=True,
                              ties={f: Tie(made[timing.source_of(t, anchor)], t.point, t.amount, t.unit, t.direction) for f, t in tied[rid].items()})
            conn.executemany("INSERT INTO task_links (task, field) VALUES (?, ?)", [(made[rid], TIE_LINKS[f]) for f in tied[rid]])
        elif c.tie:
            tasks.update_task(conn, settings, made[rid], at=at, via=via, keep_links=True, ties={"start": c.tie})
    for rid in order:
        c = choices.get(rid, Choice())
        typed = {k: v for k, v in (("start", c.start), ("due", c.due)) if v}
        if (tied[rid] or c.tie) and typed:
            tasks.update_task(conn, settings, made[rid], at=at, via=via, **typed)


# ---- Apply template: a template into tasks that already exist (release 5.63, decisions 301 to 309) ----
def has_dates(t) -> bool:
    """Whether a task has a date of its own to keep, or a tie that will give it one."""
    return bool(t.start or t.due or t.ties)


def _landing(row: Row, t, top: bool) -> tuple[list[str], list[str], dict[str, object]]:
    """What a row does to a task that keeps all it has (decision 303): the fields that follow the row from now on, those it fills, and the
    changes. An empty field fills and follows, and one that already says the same follows. One with its own value stays, and doesn't
    follow. Labels add. A task with a date takes no Duration, so its dates never change, and Inherit parent labels stays as it is."""
    links, filled = [], []
    for k in FIELDS:
        if not fills(row, k) or (k == "title" and top) or (k in NOT_ROUTINE and has_dates(t)):
            continue
        now = stated(t, k)
        if now == stated(row, k):
            links.append(k)
        elif now is None or now is False or now == "" or now == []:
            links.append(k)
            filled.append(k)
    changes = _as_changes(row, filled, t)
    if "labels" not in filled and (more := [x for x in row.labels if x not in t.labels]):
        changes["labels"] = [*t.labels, *more]
        filled.append("labels")
    return links, filled, changes


@dataclass
class ApplyPlan:
    """What applying a template to one task comes to. ``kept`` says which rows land on a task that's already there: the task itself for the
    top row, and a subtask of the same name for any other (decision 304). ``refused`` says why it can't be applied."""

    task: str
    refused: str = ""
    kept: dict[int, str] = field(default_factory=dict)
    fills: list[str] = field(default_factory=list)  # what the task takes from the top row, by name
    adds: int = 0
    uses: list[str] = field(default_factory=list)  # the subtasks of its own that rows land on, by title

    def words(self) -> str:
        """In a line: "Adds 6 subtasks. Uses your Trial report. Fills Lead and Labels. Keeps all it has."."""
        said = [f"Adds {plural(self.adds, 'subtask')}."] if self.adds else []
        if self.uses:
            said.append(f"Uses your {_joined(self.uses)}.")
        if self.fills:
            said.append(f"Fills {_joined(self.fills)}.")
        return " ".join([*said, "Keeps all it has."])


def _joined(words: Sequence[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def template_refusal(lib: Library, row_id: int) -> str:
    """Why a template can't be applied to any task (decision 306)."""
    template = lib.template_of(row_id)
    if template.discarded:
        return f"{lib.name(template.id)} is discarded. Bring it back to apply it."
    if lib.rows[row_id].recurrence:
        return f"{lib.name(template.id)} repeats, so it would turn each task into a routine one."
    return ""


def plan_apply(lib: Library, m: Model, row_id: int, task_id: str) -> ApplyPlan:
    """What applying the template at ``row_id`` to a task comes to, or why it can't be applied to that one (decision 306). A row lands on a
    subtask with the same name under where its parent landed, and nothing else matches. A row that repeats is always a new task, as is
    one whose match repeats or follows a template already."""
    t = m.tasks.get(task_id)
    if t is None:
        return ApplyPlan(task_id, f"There's no task {task_id}.")
    why = ("It's discarded." if t.discarded else "It's closed." if t.state == "Closed" else "It's a routine task." if t.recurrence
           else f"It already follows {lib.name(lib.rows[lib.copies[task_id].row].template)}." if task_id in lib.copies else "")
    if why:
        return ApplyPlan(task_id, why)
    kept, taken = {row_id: task_id}, {task_id}
    walked = lib.walk(row_id)
    for row, _ in walked[1:]:
        under = kept.get(row.parent)
        if under is None or row.recurrence:
            continue
        name = row.title.strip().casefold()
        hit = next((x for x in m.children_of(under) if x not in taken and x not in lib.copies and not m.tasks[x].discarded and not m.tasks[x].recurrence
                    and m.tasks[x].title.strip().casefold() == name), None)
        if hit:
            kept[row.id] = hit
            taken.add(hit)
    _, filled, _ = _landing(lib.rows[row_id], t, True)
    return ApplyPlan(task_id, "", kept, [LINK_NAMES[k] for k in filled], len(walked) - len(kept), [m.tasks[x].title for r, x in kept.items() if r != row_id])


def anchor_tie(lib: Library, m: Model, row_id: int, plan: ApplyPlan) -> Tie | None:
    """The tie an anchor among the subtasks starts with: "The day Trial 1 starts", so moving the task moves its tree (decision 302). There's
    none when the task has no Start, or when the anchor landed on a subtask with dates of its own."""
    anchor = lib.template_of(row_id).anchor
    if anchor is None or anchor == row_id or anchor not in {x.id for x, _ in lib.walk(row_id)} or not m.tasks[plan.task].start:
        return None
    here = plan.kept.get(anchor)
    return None if here and has_dates(m.tasks[here]) else Tie(plan.task, "start", 0, "workdays", "after")


def _row_ties(lib: Library, row: Row, inside: Collection[int]) -> dict[str, RowTie]:
    anchor = lib.template_of(row.id).anchor
    return {f: t for f, t in row.ties.items() if timing.source_of(t, anchor) in set(inside) - {row.id}}


def plan_typed(lib: Library, m: Model, row_id: int, plan: ApplyPlan) -> dict[int, timing.Typed]:
    """What each row has for the sum of where it lands, before anything's typed: a task that's kept has its own dates, and a row its ties
    and days, with the anchor tied to the task when it has a Start (``RowTie`` naming the top row, which the task stands in for)."""
    walked = lib.walk(row_id)
    inside = {x.id for x, _ in walked}
    anchor, tie = lib.template_of(row_id).anchor, anchor_tie(lib, m, row_id, plan)
    out: dict[int, timing.Typed] = {}
    for row, _ in walked:
        t = m.tasks[plan.kept[row.id]] if row.id in plan.kept else None
        if t is not None and has_dates(t):
            out[row.id] = timing.Typed({}, None, t.calendar_days, t.start, t.due)
            continue
        tied = _row_ties(lib, row, inside)
        if tie and row.id == anchor:
            tied = {"start": RowTie(row_id, "start", 0, "workdays", "after")}
        days = None if len(tied) == 2 else (t.duration if t is not None and t.duration else None) or row.duration
        out[row.id] = timing.Typed(tied, days, bool(row.calendar_days or (t is not None and t.calendar_days)))
    return out


def tree_words(t, row_id: int, dates: Mapping[int, tuple[str | None, str | None]], today: date) -> tuple[str, str]:
    """Where a task's subtasks come to, in words, and a warning when that's outside its own dates, which stay as they are (decision 307)."""
    below = [(a or b, b or a) for r, (a, b) in dates.items() if r != row_id and (a or b)]
    if not below:
        return "Its subtasks have no dates yet.", ""
    first, last = min(x for x, _ in below), max(x for _, x in below)
    words = f"Its subtasks run {long_date(to_date(first), today)} to {long_date(to_date(last), today)}."
    if (t.start and first < t.start) or (t.due and last > t.due):
        return words, "That's outside its own dates, which stay as they are."
    return words, ""


@dataclass
class Applied:
    """What applying a template did to one task: the subtasks made, and those of its own that now follow the template."""

    task: str
    made: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def apply_template(conn: sqlite3.Connection, settings: Settings, row_id: int, targets: Mapping[str, Mapping[int, Choice] | None], at: datetime) -> list[Applied]:
    """Put a template into tasks that already exist, all or none (decisions 301 to 309). Each task becomes its tree's top and keeps all it
    has: its title, description, notes, captures, dates and people. Its empty fields fill and follow the template, starting notes go at the
    end of its notes page, and each subtask is made, or found by name, as ``plan_apply`` says. ``targets`` gives each task its rows'
    choices as Make tasks' dialog has them, or None for what it starts with."""
    lib = Library(conn)
    if row_id not in lib.rows:
        raise TaskError("That row isn't in a template any more.")
    if refused := template_refusal(lib, row_id):
        raise TaskError(refused)
    if not targets:
        raise TaskError("Tick a task to apply it to.")
    template = lib.template_of(row_id)
    name = lib.name(template.id)
    via = f"Template: {name}"
    done: list[Applied] = []
    with transaction(conn):
        for task_id, given in targets.items():
            lib, m = Library(conn), Model(conn)  # a subtask can sit under two of them, and only one can have it
            plan = plan_apply(lib, m, row_id, task_id)
            if plan.refused:
                raise TaskError(f"{m.task(task_id).title if task_id in m.tasks else task_id}: {plan.refused}")
            choices = dict(given) if given is not None else {}
            if given is None and template.anchor is not None and (tie := anchor_tie(lib, m, row_id, plan)):
                choices[template.anchor] = Choice(tie=tie)
            walked = [x for x, _ in lib.walk(row_id)]
            inside = {x.id for x in walked}
            tied = {x.id: {} if x.id in plan.kept and has_dates(m.tasks[plan.kept[x.id]]) else _row_ties(lib, x, inside) for x in walked}
            made: dict[int, str] = {}
            result = Applied(task_id)
            for row in walked:
                here = plan.kept.get(row.id)
                if here is None:
                    c = choices.get(row.id, Choice())
                    made[row.id] = _copy_row(conn, settings, row, row.title, [made[row.parent]], via, task_id,
                                             replace(c, start=None, due=None) if tied[row.id] or c.tie else c, False, at)
                    result.made.append(made[row.id])
                    continue
                made[row.id] = here
                links, _, changes = _landing(row, m.tasks[here], row.id == row_id)
                conn.execute("INSERT INTO task_template (task, row_id, tree) VALUES (?, ?, ?)", (here, row.id, task_id))
                if changes:
                    tasks.update_task(conn, settings, here, at=at, via=via, keep_links=True, **changes)
                conn.executemany("INSERT INTO task_links (task, field) VALUES (?, ?)", [(here, k) for k in links])
                tasks.record(conn, here, at, via, [Change(TEMPLATE_LINK, None, f"Follows {name}")])
                if row.notes.strip():
                    notes_page.put(conn, here, notes_page.add_block(notes_page.get(conn, here), page_body(row.notes).split("\n"), at.date(), False), at)
                if here != task_id:
                    result.kept.append(here)
            _place_tree(conn, settings, walked, made, tied, template.anchor, choices, via, at)
            done.append(result)
        titles = [Model(conn).task(x.task).title for x in done]
        _log_change(conn, template.id, at, "added", f"Applied to {clip(', '.join(titles), 160)}", reached=len(done))
    return done


def apply_to_tasks(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, row_id: int, targets: Mapping[str, Mapping[int, Choice] | None],
                   at: datetime) -> tuple[list[Applied], edits.Outcome]:
    """Apply template from the browse tool: the change, the search text and the pages. Returns what it did, and what to say."""
    done = apply_template(conn, settings, row_id, targets, at)
    made = [x for a in done for x in a.made]
    kept = [x for a in done for x in a.kept]
    new = Model(conn).tasks
    undated = [x for x in made if not new[x].start and not new[x].due and not new[x].deadline]
    said = f"Applied {Library(conn).name(Library(conn).template_of(row_id).id)} to {plural(len(done), 'task')}: {plural(len(made), 'subtask')} added."
    if kept:
        said += f" {plural(len(kept), 'subtask')} of your own now follow{'s' if len(kept) == 1 else ''} it."
    if undated:
        said += f" {len(undated)} undated, waiting for dates."
    out = edits.Outcome(said)
    search.index_pages(conn, [*(a.task for a in done), *made, *kept])
    edits.write_all_pages(conn, data_root, fs, at, out.problems)
    log.info("applied template row %d to %d tasks", row_id, len(done))
    return done, out


# ---- Save as template (decision 195) ----
def save_as_template(conn: sqlite3.Connection, settings: Settings, task_id: str, name: str, link: bool, at: datetime, via: str = edits.BROWSE) -> int:
    """A new template from a task and what's under it: their fields, without dates, state, status, notes or captures. A
    discarded subtask is left out. A task's length becomes its row's Duration, whether it's typed or what its two dates hold.
    With ``link``, these tasks then follow it, as a tree made from it does, and each takes that Duration. Ties inside the tree come
    along, as rows tied to rows, and those reaching outside it don't (decision 258). There's no anchor yet. Returns its top row."""
    workdays = workday_numbers(settings.workdays)
    m = Model(conn)
    if task_id not in m.tasks:
        raise TaskError(f"There's no task {task_id}.")
    title = " ".join(name.split())
    if not title:
        raise TaskError("A template needs a name.")
    tree = {task_id, *m.descendants_of(task_id)}

    def inside(t) -> dict[str, Tie]:
        return {f: x for f, x in t.ties.items() if x.key_date is None and x.source in tree and not m.task(x.source).discarded}

    with transaction(conn):
        template = conn.execute("INSERT INTO templates (created) VALUES (?)", (stamp(at),)).lastrowid
        seen: set[str] = set()
        top = 0
        rows_of: dict[str, int] = {}

        def walk(tid: str, parent: int | None) -> None:
            nonlocal top
            if tid in seen or m.task(tid).discarded:
                return
            seen.add(tid)
            t = m.task(tid)
            days = t.duration if t.recurrence else None if len(inside(t)) == 2 else length_of(t.start, t.due, t.duration, workdays, t.calendar_days)
            v = _checked(conn, {k: getattr(t, k) for k in FIELDS} | {"title": title if parent is None else t.title, "duration": days,
                                                                      **{k: getattr(t, k) for k in RATE_FIELDS}, "involvement": t.involvement})
            row_id = _insert_row(conn, template, parent, v)
            rows_of[tid] = row_id
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
        for tid, row_id in rows_of.items():
            tied = inside(m.task(tid))
            _store_row_ties(conn, row_id, {f: RowTie(rows_of[x.source], x.point, x.amount, x.unit, x.direction) for f, x in tied.items()})
            if link:
                conn.executemany("INSERT INTO task_links (task, field) VALUES (?, ?)", [(tid, TIE_LINKS[f]) for f in tied])
    return top


# ---- a template's timing: the Timing window (decisions 248, 255 and 257) ----
@dataclass
class RowTiming:
    """What the Timing window says for a row: its ties, and its Days."""

    ties: dict[str, RowTie] = field(default_factory=dict)
    days: int | None = None


@dataclass
class TimingPlan:
    """What saving the Timing window would do. ``items`` are the tasks whose dates move, and it's ``changed`` if anything differs at all."""

    template: int
    name: str
    what: str
    changed: bool
    items: list[Reached] = field(default_factory=list)
    not_changing: list[NotChanging] = field(default_factory=list)


def _checked_timing(lib: Library, template_id: int, anchor: int | None, rows: Mapping[int, RowTiming]) -> dict[int, RowTiming]:
    """The window's rows, settled as a row's form is, or why they can't stand. A row left out stays as it is, and a row that repeats has no ties."""
    template = lib.templates.get(template_id)
    if template is None:
        raise TaskError("That template isn't there any more.")
    out: dict[int, RowTiming] = {}
    for x, _ in lib.walk(template.top):
        r = rows.get(x.id)
        if r is not None and not x.recurrence:
            now = {} if x.id == anchor else {f: t for f, t in r.ties.items() if t and (t.source is not None or anchor is not None)}
            out[x.id] = RowTiming(now, None if len(now) == 2 else r.days)
    lines = [replace(x, ties=out[x.id].ties, days=out[x.id].days) if x.id in out else x for x in lib.lines(template_id)]
    said = timing.problem(lines, anchor)
    if said:
        raise TaskError(said)
    return out


def _timing_changes(lib: Library, template_id: int, anchor: int | None, rows: Mapping[int, RowTiming]) -> bool:
    return anchor != lib.templates[template_id].anchor or any(r.ties != lib.rows[x].ties or r.days != lib.rows[x].duration for x, r in rows.items())


def _write_timing(conn: sqlite3.Connection, settings: Settings, template_id: int, anchor: int | None, rows: Mapping[int, RowTiming], at: datetime,
                  left: Collection[str] = ()) -> None:
    """Save the window, and put it on the trees already made, by the rules of any change to a template (decisions 185, 186, 198 and 257):
    a task following its row takes the new tie and Duration, and one with no date there starts following. Each task's ties are set first,
    so that ``follow`` then moves each task once, sources first. One in ``left`` keeps its date, stays tied, and stops following. A tree
    whose old anchor has a tie of its own, such as to an outage, stays driven from there: that tie stays, and the new anchor stays tied
    to the old one, as its own, so moving the outage still moves the whole tree."""
    was = Library(conn)
    old_anchor = was.templates[template_id].anchor
    conn.execute("UPDATE templates SET anchor_row = ? WHERE id = ?", (anchor, template_id))
    for row_id, x in rows.items():
        conn.execute("UPDATE template_rows SET duration = ? WHERE id = ?", (x.days, row_id))
        _store_row_ties(conn, row_id, x.ties)
    lib = Library(conn)
    name = lib.name(template_id)
    via = f"Template: {name}"
    live: list[str] = []
    retied: list[tuple[str, str, Tie | None]] = []
    driven = {c.tree for c in lib.copies_of(old_anchor) if tasks.get_task(conn, c.task).ties} if old_anchor is not None and old_anchor != anchor else set()
    for row, _ in lib.walk(lib.templates[template_id].top):
        old = was.rows[row.id]
        for c in lib.copies_of(row.id):
            t = tasks.get_task(conn, c.task)
            if t.discarded or t.state == "Closed":
                continue
            live.append(c.task)
            links, own = lib.links.get(c.task, set()), c.task in left
            now, ending, starting = dict(t.ties), [], []
            for f, key in TIE_LINKS.items():
                tie = tie_on(lib, row, f, c.tree)
                if row.id == anchor:  # the anchor has no tie of its template's, and any it gave its copies goes. One of the task's own stays.
                    if key in links and c.tree in driven:
                        ending.append(key)
                    elif key in links:
                        now.pop(f, None)
                        conn.execute("DELETE FROM task_links WHERE task = ? AND field = ?", (c.task, key))
                elif tie is None:  # decision 198: it stays tied, as its own
                    if key in links:
                        ending.append(key)
                elif own or tasks.get_task(conn, tie.source).recurrence:
                    if key in links and t.ties.get(f) != tie:
                        ending.append(key)
                elif key in links or (f not in now and (not getattr(t, f) or row.id == old_anchor)):
                    if now.get(f) != tie:
                        retied.append((c.task, f, now.get(f)))
                    now[f] = tie
                    if key not in links:
                        starting.append(key)
            changes = {}
            if old.duration != row.duration and not t.recurrence:
                if row.duration is None or own:
                    if "duration" in links:
                        ending.append("duration")
                elif "duration" in links or (old.duration is None and t.duration is None):
                    changes["duration"] = row.duration
                    if "duration" not in links:
                        starting.append("duration")
            if now != t.ties:
                tasks.put_ties(conn, c.task, now, at, via)
            if changes or (len(now) == 2 and t.duration is not None):
                tasks.update_task(conn, settings, c.task, at=at, via=via, keep_links=True, following=True, **changes)
            _ended(conn, c.task, ending, name, at)
            conn.executemany("INSERT OR IGNORE INTO task_links (task, field) VALUES (?, ?)", [(c.task, k) for k in starting])
    for task_id, f, was_tied in retied:  # a row's ties can't make a circle, but with a task's own they can, and then the row's doesn't take
        if task_id in ties.chain(lambda x: ties.own_followers(conn, x), ties.own_followers(conn, task_id)):
            t = tasks.get_task(conn, task_id)
            tasks.put_ties(conn, task_id, {k: x for k, x in {**t.ties, f: was_tied}.items() if x}, at, via)
            _ended(conn, task_id, [TIE_LINKS[f]], name, at)
    tasks.follow(conn, settings, live, at, via, left, by_template=live)


def _timing_order(lib: Library, template_id: int) -> list[str]:
    """A template's tasks, tree by tree, each in its rows' order."""
    return [x for c in lib.trees(template_id) for r, _ in lib.walk(c.row) if (x := lib.copy_in(r.id, c.task))]


def _timing_left_alone(was: Library, lib: Library, before: Model, after: Model, template_id: int, anchor: int | None) -> list[NotChanging]:
    """What a change to the timing leaves as it is, of the rows it changed: closed and discarded tasks, and those with their own dates or gap."""
    out: list[NotChanging] = []
    moved_anchor = anchor != was.templates[template_id].anchor
    for row, _ in lib.walk(lib.templates[template_id].top):
        old = was.rows[row.id]
        if not moved_anchor and old.ties == row.ties and old.duration == row.duration:
            continue
        for c in lib.copies_of(row.id):
            t = before.tasks.get(c.task)
            if t is None:
                continue
            title = _named(before, c.task)
            if t.discarded or t.state == "Closed":
                why = "discarded" if t.discarded else "closed"
                out.append(NotChanging(c.task, title, why, f"{why}, so it keeps what it ended with"))
                continue
            links = lib.links.get(c.task, set())
            own = [TIE_LINKS[f] for f in timing.FIELDS if row.id != anchor and (x := tie_on(lib, row, f, c.tree)) and TIE_LINKS[f] not in links and after.task(c.task).ties.get(f) != x]
            if own:
                out.append(NotChanging(c.task, title, "own", "its own " + ", ".join(_own_words(after, after.task(c.task), k) for k in own)))
    return out


def preview_timing(conn: sqlite3.Connection, settings: Settings, template_id: int, anchor: int | None, rows: Mapping[int, RowTiming], at: datetime) -> TimingPlan:
    """What saving the Timing window would do, made and rolled back."""
    plan: TimingPlan | None = None
    try:
        with transaction(conn):
            was, before = Library(conn), Model(conn)
            settled = _checked_timing(was, template_id, anchor, rows)
            plan = TimingPlan(template_id, was.name(template_id), f"Timing around {was.rows[anchor].title}" if anchor else "No anchor",
                              _timing_changes(was, template_id, anchor, settled))
            if plan.changed:
                _write_timing(conn, settings, template_id, anchor, settled, at)
                lib, after = Library(conn), Model(conn)
                plan.items = _moved_items(before, after, _timing_order(lib, template_id))
                plan.not_changing = _timing_left_alone(was, lib, before, after, template_id, anchor)
            raise _Preview
    except _Preview:
        pass
    assert plan is not None
    return plan


def apply_timing(conn: sqlite3.Connection, settings: Settings, template_id: int, anchor: int | None, rows: Mapping[int, RowTiming], at: datetime,
                 left: Collection[str] = ()) -> TimingPlan:
    """Save the Timing window, each task's change in its status log and the template's Changes list. Returns what it did."""
    with transaction(conn):
        was, before = Library(conn), Model(conn)
        settled = _checked_timing(was, template_id, anchor, rows)
        what = f"Timing around {was.rows[anchor].title}" if anchor else "No anchor"
        plan = TimingPlan(template_id, was.name(template_id), what, _timing_changes(was, template_id, anchor, settled))
        if plan.changed:
            _write_timing(conn, settings, template_id, anchor, settled, at, left)
            lib, after = Library(conn), Model(conn)
            plan.items = _moved_items(before, after, _timing_order(lib, template_id))
            _log_change(conn, template_id, at, "changed", what, len(plan.items), len(left))
    return plan


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
        moved = f" {plural(plan.followed, 'more task')} moved with {'it' if reached == 1 else 'them'}." if plan.followed else ""
        message = f"{plural(reached, 'task')} changed" + (f", {stayed} left as {'it was' if stayed == 1 else 'they were'}" if stayed else "") + f".{moved} Each status log says so."
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
    dated = [t for t in Model(conn).tasks.values() if t.id in made and (t.start or t.due)]
    if n and plan.tied:
        message = f"Added to {plural(n, 'tree')}, tied." + (f" {len(dated)} placed by {'its' if len(dated) == 1 else 'their'} tie." if dated else " It waits for what it's tied to.")
    else:
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


def save_timing(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, template_id: int, anchor: int | None, rows: Mapping[int, RowTiming],
                at: datetime, left: Collection[str] = ()) -> edits.Outcome:
    """Save the Timing window, after its preview."""
    plan = apply_timing(conn, settings, template_id, anchor, rows, at, left)
    n, kept = len(plan.items), len(left)
    if not plan.changed:
        return edits.Outcome("Nothing changed.")
    if n or kept:
        message = f"{plural(n, 'task')} changed" + (f", {kept} kept {'its date' if kept == 1 else 'their dates'} with a new gap" if kept else "") + ". Each status log says so."
    else:
        message = "Saved. No task's date changes."
    out = edits.Outcome(message)
    if _timing_order(Library(conn), template_id):
        edits.write_all_pages(conn, data_root, fs, at, out.problems)
    return out


def make(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, row_id: int, name: str, under: str | None,
         choices: Mapping[int, Choice], at: datetime) -> tuple[list[str], edits.Outcome]:
    """Make tasks from the browse tool: the tasks, their search text and their pages. Returns the new tasks, and what to say."""
    made = make_tasks(conn, settings, row_id, name, under, choices, at)
    n, new = len(made), [t for t in Model(conn).tasks.values() if t.id in made]
    undated = [t for t in new if not t.start and not t.due and not t.deadline]
    placed = [t for t in new if t.ties and (t.start or t.due)]
    by_ties = ""
    if placed:
        by_ties = (" 1 placed by its tie, and it'll move with what it's tied to." if len(placed) == 1
                   else f" {len(placed)} placed by their ties, and they'll move with what they're tied to.")
    out = edits.Outcome(f"Made {n} task{'s' if n != 1 else ''}.{by_ties}" + (f" {len(undated)} undated, waiting for dates." if undated else ""))
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
