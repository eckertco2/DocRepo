"""The Activity view (mods log round 2, M0032; release 5.23, decisions 70 to 73): what happened in a time window, under
the tasks it happened to.

It reads only what docs.db already holds, and stores nothing new: captures (notes, emails, updates with what they
changed, new tasks), status log changes made outside a capture (in the browse tool, the Priorities board and so on),
document versions, and agenda items added, discussed or removed (decision 70). Today's own items are left out, since
what was done shows through its update. Each line goes under the task it happened to, in tree order, grouped by
top-level task, person, group or label; a new subtask goes under its parent, a note put only on an agenda under that
meeting, and captures not filed yet last (decision 71). For meeting prep, the browse window's Select ticks tasks and
lines, and Add to agenda (``edits.add_activity_to_agenda``) puts one item per task on an agenda, its ticked lines joined
as the item's note (decision 72).

Ported from the browse tool mockup's ``activity.js``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from docrepo.dates import long_date, monday_of, short, to_date
from docrepo.model import TODAY, Capture, Model, StatusEntry, is_person
from docrepo.schedule import start_of
from docrepo.stories import Stories, clip, is_none, state_words

WINDOWS = (("week", "This week"), ("last", "Last week"), ("7d", "The last 7 days"), ("range", "From and to…"))
GROUPS = (("top", "Top-level task"), ("person", "Person"), ("group", "Group"), ("label", "Label"))
#: What happened, for the What filter: each line's first kind is what it is.
KINDS = (("task", "New tasks"), ("update", "Updates"), ("note", "Notes"), ("email", "Emails"), ("change", "Changes"), ("doc", "Documents"),
         ("agenda", "Agendas"))
#: A changed field's chip: what kind of change it was.
CHANGE_CHIPS = {"State": "State", "Current status": "Status", "Due": "Date", "Deadline": "Date", "Start": "Date", "Reminder": "Date",
                "Priority": "Priority"}
#: Where a change was made, when it wasn't in a capture or on a task's page.
WHERE = {"Agenda view": "In the Agendas view", "Reminders list": "In the reminders list", "Today": "On Today", "Capture window": "In the capture window",
         "Priorities view": "On the Priorities board", "Activity view": "In the Activity view", "Excel import": "From the Excel import"}
#: Who added agenda items from this view.
VIA = "Activity view"


def window(choice: str, today: date, start: date | None = None, end: date | None = None) -> tuple[date, date]:
    """The window's first and last days, both included: This week is Monday to today."""
    mon = monday_of(today)
    if choice == "last":
        return mon - timedelta(days=7), mon - timedelta(days=1)
    if choice == "7d":
        return today - timedelta(days=6), today
    if choice == "range":
        a, b = start or mon, end or today
        return (a, b) if a <= b else (b, a)
    return mon, today


def window_text(span: tuple[date, date], today: date) -> str:
    a, b = span
    return f"{long_date(a, today)} to {'today' if b == today else long_date(b, today)}"


@dataclass
class Line:
    """One thing that happened. It's listed under ``task`` (None: not filed yet) and is about ``about``, the task the
    filters and the agenda use: a new subtask is listed under its parent and is about itself."""

    key: str
    at: str  # "YYYY-MM-DD HH:MM"
    task: str | None
    about: str | None
    kinds: list[str]
    chip: str
    text: str
    facts: list[str]
    open: tuple[str, str]  # what clicking it opens: ("task" | "capture" | "doc", its ID)

    @property
    def day(self) -> date:
        return to_date(self.at[:10])


@dataclass
class Heading:
    task: str | None
    lines: list[Line] = field(default_factory=list)


@dataclass
class Group:
    name: str
    rank: float
    task: str | None = None  # the top-level task, grouping by top-level task
    person: str | None = None
    sub: str = ""
    colour: int | None = None  # the top-level task's colour, as the tree numbers them
    unfiled: bool = False
    lines: list[Line] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)


@dataclass(frozen=True)
class Filter:
    people: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()


class Activity:
    """The lines and groups for one model, as of ``today``."""

    def __init__(self, m: Model, today: date) -> None:
        self.m = m
        self.today = today
        self.stories = Stories(m, today, lambda _: "")

    # ---- the lines ----
    def change_text(self, f: str, before: str | None, after: str | None, target: str | None = None) -> str:
        """A changed field as the line says it: a state change in words, else the story's sentence."""
        if f == "State":
            return state_words(before or "", after or "") + "."
        return self.stories.field_sentence(StatusEntry("", "", f, before, after, "", target))

    def _doc_fact(self, c: Capture) -> list[str]:
        """The documents a capture brought, unless its title is already the one document's name."""
        docs = [d for d in c.document_ids if d in self.m.documents]
        if not docs or (len(docs) == 1 and c.title == self.m.documents[docs[0]].name):
            return []
        names = ", ".join(self.m.documents[d].name for d in docs)
        return [f"{'A document' if len(docs) == 1 else f'{len(docs)} documents'}: {names}"]

    def lines(self, start: date, end: date) -> list[Line]:
        """Everything that happened from ``start`` to ``end``, both included, one line each, oldest first."""
        m = self.m
        first, last = start.isoformat(), end.isoformat()

        def in_window(at: str | None) -> bool:
            return bool(at) and first <= at[:10] <= last

        out: list[Line] = []
        live = {c.id: c for c in m.live_captures()}
        for c in live.values():
            if not in_window(c.saved):
                continue
            at, mail, docs = c.saved[:16], c.source == "outlook_email", ["doc"] if c.document_ids else []
            agenda = [a for a in m.agenda if a.added_by == c.id and a.target != TODAY]
            agenda_facts = [self.change_text("Agenda", None, m.target_name(a.target), a.target) for a in agenda if a.subject]
            if c.created_task and c.created_task in m.tasks and not m.task(c.created_task).discarded:
                t = m.task(c.created_task)
                under = c.task if c.task in m.tasks else None
                who = ", ".join(m.person_name(p) for p in (*t.leads, *t.assignees))
                when = f"due {short(to_date(t.due), self.today)}" if t.due else f"deadline {short(to_date(t.deadline), self.today)}" if t.deadline else ""
                facts = ", ".join(x for x in (who, when, "urgent" if t.urgent else "") if x)
                out.append(Line(f"c:{c.id}:new", at, under or t.id, t.id, ["task", *docs], "New subtask" if under else "New task", t.title,
                                [x for x in (facts, *self._doc_fact(c)) if x], ("task", t.id)))
            if c.has("update") and c.task in m.tasks:
                changes = [self.change_text(e.field, e.from_value, e.to_value) for e in m.status if e.via == c.id and e.task == c.task]
                out.append(Line(f"c:{c.id}:upd", at, c.task, c.task, ["update", *(["agenda"] if agenda_facts else []), *docs], "Update", c.title,
                                [*changes, *agenda_facts, *self._doc_fact(c)], ("capture", c.id)))
            if c.has("note") and not c.created_task:
                kind, chip = ("email", "Email") if mail else ("note", "Note")
                holders = [x for x in m.capture_tasks(c) if x in m.tasks and not m.task(x).discarded]
                if holders:
                    for x in holders:
                        filed = [f"Filed here on {short(to_date(c.filed[:10]), self.today)}"] if c.filed_to == x and c.filed else []
                        out.append(Line(f"c:{c.id}:{x}", at, x, x, [kind, *docs], chip, c.title, [*filed, *self._doc_fact(c)], ("capture", c.id)))
                elif m.is_unfiled(c):
                    out.append(Line(f"c:{c.id}", at, None, None, [kind, *docs], chip, c.title, self._doc_fact(c), ("capture", c.id)))
                else:  # a note put only on an agenda: under the meeting or task whose agenda it's on
                    for a in agenda:
                        where = a.target if a.target in m.tasks else None
                        fact = f"On {m.person_name(a.target)}'s agenda" if is_person(a.target) else "Put on its agenda, as a note"
                        out.append(Line(f"c:{c.id}:{a.target}", at, where, where, ["agenda"], "Agenda", c.title, [fact], ("capture", c.id)))
        # Changes made outside a capture: the browse tool, the Priorities board, the reminders list and so on.
        for i, e in enumerate(m.status):
            if not in_window(e.at) or e.task not in m.tasks or m.task(e.task).discarded or e.via in m.captures:
                continue
            text = ("Status cleared." if is_none(e.to_value) else e.to_value or "") if e.field == "Current status" \
                else self.change_text(e.field, e.from_value, e.to_value)
            facts = [WHERE.get(e.via, f"By {e.via}")] if e.via and e.via != "Browse tool" and not re.match(r"C\d", e.via) else []
            out.append(Line(f"e:{i}", e.at[:16], e.task, e.task, ["change"], CHANGE_CHIPS.get(e.field, "Changed"), text, facts, ("task", e.task)))
        # The notes page (release 5.25, decision 111): a line for each day the owner edited a task's page. Nothing goes
        # into the status log for it (decision 90).
        for task_id, day, at in m.page_edits:
            if in_window(day) and task_id in m.tasks and not m.task(task_id).discarded:
                out.append(Line(f"p:{task_id}:{day}", at[:16], task_id, task_id, ["note"], "Notes", "Notes edited", [], ("task", task_id)))
        for v in m.versions:
            if not in_window(v.at) or v.document not in m.documents:
                continue
            for x in m.document_holders(v.document):
                if x in m.tasks and not m.task(x).discarded:
                    out.append(Line(f"v:{v.id}:{x}", v.at[:16], x, x, ["doc"], "Document", f"{m.documents[v.document].name} changed",
                                    [clip(v.summary, 160)] if v.summary else [], ("doc", v.document)))
        for a in m.agenda:
            if a.target == TODAY:
                continue
            where = a.subject or (a.target if a.target in m.tasks else None)
            if where and (where not in m.tasks or m.task(where).discarded):
                continue
            target = m.target_name(a.target)
            opens = ("task", a.subject) if a.subject else ("capture", a.added_by) if a.added_by in live else ("task", a.target)
            # Added from a capture in the window: that capture's line says so. Added another way: a line of its own.
            by = live.get(a.added_by)
            if in_window(a.added) and not (by and in_window(by.saved)):
                text = self.change_text("Agenda", None, target, a.target) if a.subject else a.note
                facts = [clip(a.note)] if a.subject and a.note else [] if a.subject else [f"On the agenda of {target}"]
                out.append(Line(f"a:{a.id}", a.added[:16], where, where, ["agenda"], "Agenda", text, facts, opens))
            if a.closed and in_window(a.closed):
                text = self.change_text("Agenda", target, a.how, a.target) if a.subject else a.note
                out.append(Line(f"a:{a.id}:x", a.closed[:16], where, where, ["agenda"], "Agenda", text,
                                [] if a.subject else [f"{a.how} at {target}"], ("task", a.subject or a.target)))
        return sorted(out, key=lambda x: x.at)

    def passes(self, line: Line, f: Filter) -> bool:
        """Whether a line matches the filters: its task's people and labels, and what kind of thing it is."""
        kind_ok = not f.kinds or any(k in f.kinds for k in line.kinds)
        t = self.m.tasks.get(line.about) if line.about else None
        if t is None:
            return not f.people and not f.labels and kind_ok
        return ((not f.people or any(p in f.people for p in (*t.leads, *t.assignees)))
                and (not f.labels or any(n in f.labels for n, _ in self.m.labels_of(t.id))) and kind_ok)

    # ---- the groups ----
    def tree_order(self) -> dict[str, int]:
        order: dict[str, int] = {}

        def go(task_id: str) -> None:
            if task_id not in order:
                order[task_id] = len(order)
                for child in self.m.children_of(task_id):
                    go(child)

        for t in self.m.top_level():
            if not t.discarded:
                go(t.id)
        return order

    def groups(self, lines: list[Line], how: str = "top", f: Filter = Filter()) -> list[Group]:
        """The lines in groups: by top-level task (the tree's colours), or by person, group or label, where a line shows
        under each of its task's people, groups or labels. Within a group, a heading per task in tree order, each with its
        lines, oldest first; a top-level task's own lines come straight under its group's header."""
        m, order = self.m, self.tree_order()
        tops = [t.id for t in m.top_level() if not t.discarded]
        groups: dict[str, Group] = {}

        def add(key: str, make, line: Line) -> None:
            if key not in groups:
                groups[key] = make()
            groups[key].lines.append(line)

        people = m.active_people()
        group_names = m.groups()
        for line in (x for x in lines if x.task):
            if how == "top":
                top = m.chains_of(line.task)[0][0]
                add(top, lambda top=top: Group(m.task(top).title, order.get(top, 1e6), task=top,
                                               colour=tops.index(top) if top in tops else None), line)
                continue
            t = m.task(line.about or line.task)
            if how == "label":
                names = [n for n, _ in m.labels_of(t.id) if not f.labels or n in f.labels]
                for n in names or [""]:
                    rank = next((i for i, lb in enumerate(m.labels) if lb.name == n), 1e5) if n else 1e6
                    add("l:" + n, lambda n=n, rank=rank: Group(n or "No label", rank), line)
                continue
            ids = [p for p in dict.fromkeys((*t.leads, *t.assignees)) if p in m.people and m.people[p].status == "active"
                   and (not f.people or p in f.people)]
            if how == "group":
                gs = list(dict.fromkeys(m.people[p].group or "" for p in ids))
                for g in gs or ["-"]:
                    rank = group_names.index(g) if g in group_names else 1e5 if g == "" else 1e6
                    add("g:" + g, lambda g=g, rank=rank: Group("No one" if g == "-" else g or "No group", rank), line)
                continue
            for p in ids or [""]:
                if p:
                    person = m.people[p]
                    add("p:" + p, lambda p=p, person=person: Group(person.name, next(i for i, x in enumerate(people) if x.id == p), person=p,
                                                                     sub=", ".join(x for x in (person.group, person.role) if x)), line)
                else:
                    add("p:", lambda: Group("No one", 1e6), line)
        out = sorted(groups.values(), key=lambda g: g.rank)
        unfiled = [x for x in lines if not x.task]
        if unfiled:
            out.append(Group("Not filed yet", 1e7, unfiled=True, lines=unfiled))
        for g in out:
            heads: dict[str | None, Heading] = {}
            for line in g.lines:
                heads.setdefault(line.task, Heading(line.task)).lines.append(line)
            g.headings = sorted(heads.values(), key=lambda h: (-1 if h.task == g.task else order.get(h.task or "", 1e6)))
        return out

    def plant_events(self, start: date, end: date):
        """Plant events whose dates overlap the window: they come first."""
        out = []
        for t in self.m.plant_events():
            last = to_date(t.due or t.deadline) if (t.due or t.deadline) else start_of(t)
            if start_of(t) <= end and last >= start:
                out.append((t, start_of(t), last))
        return out

    # ---- copying and agendas ----
    def markdown(self, groups: list[Group], span: tuple[date, date]) -> str:
        """What's shown, as Markdown: a heading per group, a bullet per task, a line per thing that happened."""
        out = [f"## Activity, {window_text(span, self.today)}", ""]

        def bullet(line: Line, pad: str) -> str:
            words = ". ".join([line.text.rstrip("."), *[x.rstrip(".") for x in line.facts]])
            return f"{pad}- {short(line.day, self.today)}, {line.chip.lower()}: {words}."

        for g in groups:
            out.append(f"### {g.name}")
            for h in g.headings:
                if h.task and h.task != g.task:
                    out.append(f"- **{self.m.task(h.task).title}**")
                    out += [bullet(x, "  ") for x in h.lines]
                else:
                    out += [bullet(x, "") for x in h.lines]
            out.append("")
        return "\n".join(out)

    def note_of(self, line: Line) -> str:
        """A ticked line as an agenda item's note. A new task's own line says only that it's new: the item names it."""
        when = short(line.day, self.today)
        facts = ". ".join(x.rstrip(".") for x in line.facts)
        if line.kinds[0] == "task":
            return f"New on {when}" + (f": {facts}." if facts else ".")
        return f"{line.chip}, {when}: {line.text.rstrip('.')}." + (f" {facts}." if facts else "")

    def agenda_items(self, lines: list[Line], picked: set[str]) -> list[tuple[str | None, str]]:
        """What Add to agenda adds for the ticked keys ("t:" a task, "l:" a line): one (task, note) per task, its ticked
        lines joined as the note; a ticked line that isn't filed yet goes on as a note of its own, (None, its text)."""
        by_key = {x.key: x for x in lines}
        items: dict[str, list[Line]] = {}
        for k in sorted(picked):
            if k.startswith("l:"):
                line = by_key.get(k[2:])
                if line is not None:
                    items.setdefault(line.about or "note:" + line.key, []).append(line)
            elif k.startswith("t:"):
                items.setdefault(k[2:], [])
        out: list[tuple[str | None, str]] = []
        for subject, ls in items.items():
            ls.sort(key=lambda x: x.at)
            if subject.startswith("note:"):
                out.append((None, ls[0].text))
            else:
                out.append((subject, " ".join(self.note_of(x) for x in ls)))
        return out
