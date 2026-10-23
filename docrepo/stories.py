"""The status log and the raw text log as stories: dated prose, oldest first.

A task's status log story opens with how the task began, then tells each update
in words ("Due date moved to Fri 23 Oct."), with its direct subtasks as one-line
milestones and, for an agenda target, its agenda items as they're added and
closed. Its raw text log reads like a journal: each capture and document version
with what it is, its title and its text. The browse tool shows each subtask's
story as a chapter of its own.

Ported from the mockup's ``model.js`` (``updatesOf``, ``storyOf``, ``fieldSentence``,
``stateWords``, ``gist``, ``initialOf``, ``joinedAt``, ``descTree``) and ``detail.js``
(``noteItem``, ``versionItem``).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from docrepo import items, markup
from docrepo.dates import long_date, short, to_date
from docrepo.model import TODAY, Capture, Model, StatusEntry, Version, is_person
from docrepo.text import is_file_line, plain_text, sentences

#: A capture's content text, by its ID ("" when its capture.md can't be read).
ContentOf = Callable[[str], str]

_DATE = re.compile(r"\d{4}-\d\d-\d\d\Z")


def is_none(value: str | None) -> bool:
    return value is None or value == "" or value == "None"


def list_of(value: str | None, sep: str = r",\s*") -> list[str]:
    return [] if is_none(value) else [x for x in re.split(sep, str(value)) if x]


def and_list(items: list[str]) -> str:
    return "".join(items) if len(items) < 2 else ", ".join(items[:-1]) + " and " + items[-1]


def clip(text: str, limit: int = 140) -> str:
    """Text cut at a word before ``limit`` characters, ending in …"""
    return text if len(text) <= limit else re.sub(r"\s+\S*\Z", "", text[:limit]) + "…"


def state_words(from_state: str, to_state: str) -> str:
    """What a state change means, in words. The story shows it as a chip."""
    if to_state in ("Closed", "Parked"):
        return to_state
    if to_state == "In progress":
        return "Picked back up" if from_state == "Parked" else "Reopened" if from_state == "Closed" else "Work started"
    return "Reopened" if from_state == "Closed" else "Set back to Not started"


@dataclass(frozen=True)
class Update:
    """One update to a task: the changes made together (same time, same source), and the state and status after it."""

    at: str
    via: str
    changes: list[StatusEntry]
    state: str
    status: str
    state_changed: bool
    status_changed: bool
    others: list[StatusEntry]


@dataclass
class Event:
    """One entry in a status log story.

    ``kind`` is "created" (how the task began), "update" (one update in words) or "sub" (a one-line milestone: a
    subtask, or an agenda item on this task's agenda). ``task`` is the subtask or the agenda item's subject; it's None
    for a note-only agenda item, whose note is ``text``.
    """

    at: str
    kind: str
    state: str = ""
    state_words: str = ""
    main: str = ""
    facts: list[str] = field(default_factory=list)
    via: str | None = None
    parents: list[str] = field(default_factory=list)
    how: str = ""  # created: new, import or unfiled
    text: str = ""
    status: str = ""
    task: str | None = None
    verb: str = ""
    note: str = ""


@dataclass(frozen=True)
class RawItem:
    """One raw text log entry as a journal entry: what it is, its title, then its summary or text."""

    at: str
    lead: str  # "Note", "Update · Due date moved to Fri 23 Oct.", "Email from …", "Document version · …"
    title: str
    capture: str | None  # the capture it is (its title opens it)
    document: str | None  # for a document version, its document
    text: str  # the text shown; with a summary, the original behind a toggle
    summary: str | None
    summary_type: str | None
    original_label: str  # what the toggle for the original says
    documents: tuple[tuple[str, str, str], ...] = ()  # (id, name, description) of the capture's files
    formatted: bool = False  # ``text`` is markup (mods log round 2, M0045; ``docrepo.markup``)
    from_notes: str | None = None  # an item (release 5.8): the notes it came from, and the notes' task
    from_title: str = ""


class Stories:
    """Stories for the tasks in one Model, as of ``today``. ``me_name`` is the owner's name, told as "I"."""

    def __init__(self, model: Model, today: date, content_of: ContentOf, me_name: str | None = None) -> None:
        self.m = model
        self.today = today
        self.content_of = content_of
        self.me_name = me_name
        self._logs: dict[str, list[StatusEntry]] = {}

    # ---- values in words ----
    def as_date(self, value: str) -> str:
        return long_date(to_date(value), self.today) if _DATE.match(value or "") else value

    def names(self, person_ids: list[str]) -> str:
        return ", ".join(self.m.person_name(p) for p in person_ids) or "None"

    def _is_me(self, name: str) -> bool:
        return name == "Me" or (self.me_name is not None and name == self.me_name)

    def field_sentence(self, e: StatusEntry) -> str:
        """One changed field as a sentence. Only the new value is named; "moved" says it had one before."""
        f, before, after = e.field, e.from_value, e.to_value

        def dated(what: str) -> str:
            if is_none(after):
                return f"{what} cleared."
            return f"{what} {'set for' if is_none(before) else 'moved to'} {self.as_date(after)}."

        def diff(sep: str) -> tuple[list[str], list[str]]:
            a, b = list_of(before, sep), list_of(after, sep)
            return [x for x in b if x not in a], [x for x in a if x not in b]

        def who(xs: list[str]) -> str:
            return and_list(["I" if self._is_me(n) else n for n in xs])

        def many(xs: list[str]) -> bool:
            return len(xs) > 1 or self._is_me(xs[0])

        if f == "Agenda":
            if e.target == TODAY:  # mods log round 1, M0016
                return "Added to Today." if is_none(before) else "Done for today." if after == "Done" else "Taken off Today."
            person = is_person(e.target)
            name = self.m.person_name(e.target) if person else after if is_none(before) else before
            if is_none(before):
                return f"Added to {name}'s agenda." if person else f"Added to the agenda of {name}."
            if after == "Discussed":
                return f"Discussed with {name}." if person else f"Discussed at {name}."
            return f"Taken off {name}'s agenda." if person else f"Taken off the agenda of {name}."
        if f == "Due":
            return dated("Due date")
        if f in ("Deadline", "Start"):
            return dated(f)
        if f == "Reminder":
            return "Reminder cleared." if is_none(after) else f"Reminder set for {self.as_date(after)}."
        if f == "Repeat until":
            return "Repeats with no end date." if is_none(after) else f"Repeats until {self.as_date(after)}."
        if f == "Deadline description":
            return "Deadline description cleared." if is_none(after) else f"Deadline: {after}."
        if f == "Lead":
            add, rm = diff(r",\s*")
            return " ".join(x for x in (add and f"{who(add)} now lead{'' if many(add) else 's'}.",
                                        rm and f"{who(rm)} no longer lead{'' if many(rm) else 's'}.") if x)
        if f == "Assignees":
            add, rm = diff(r",\s*")
            return " ".join(x for x in (add and f"{who(add)} {'were' if len(add) > 1 else 'was'} assigned.",
                                        rm and f"{who(rm)} {'were' if len(rm) > 1 else 'was'} unassigned.") if x)
        if f in ("Lead hours", "Assignee hours"):
            if is_none(after):
                return f"{f} cleared."
            value = f"{after} h" if re.fullmatch(r"\d+(\.\d+)?", after or "") else after
            return f"{f} set to {value}."
        if f == "Urgent":
            return "Marked urgent." if after == "Yes" else "No longer urgent."
        if f == "Meeting":
            return "Made a meeting." if after == "Yes" else "No longer a meeting."
        if f == "Recurrence":
            return "No longer repeats." if is_none(after) else f"Now repeats {(after or '').lower()}."
        if f == "Parents":
            add, rm = diff(r";\s*")
            return " ".join(x for x in (add and f"Also put under {and_list(add)}.", rm and f"No longer under {and_list(rm)}.") if x)
        # Fields only the browse tool changes.
        if f == "Title":
            return f"Renamed “{after}”."
        if f == "Description":
            return "Description edited."
        if f == "Labels":
            add, rm = diff(r",\s*")
            return " ".join(x for x in (add and f"Label{'s' if len(add) > 1 else ''} {and_list(add)} added.",
                                        rm and f"Label{'s' if len(rm) > 1 else ''} {and_list(rm)} removed.") if x)
        if f == "Inherit parent labels":
            return "Inherits its parents' labels again." if after == "Yes" else "No longer inherits its parents' labels."
        if f == "Discarded":  # mods log round 1, M0021: the value is the reason
            return "Brought back." if is_none(after) else f"Discarded: {(after or '').rstrip('.')}."
        return f"{f}: {'cleared' if is_none(after) else after}."

    # ---- the status log, as updates ----
    def log(self, task_id: str) -> list[StatusEntry]:
        """The task's status log, oldest first."""
        if task_id not in self._logs:
            self._logs[task_id] = sorted(self.m.status_log_of(task_id), key=lambda e: e.at)
        return self._logs[task_id]

    def initial(self, task_id: str, field_name: str, now: str) -> str:
        """A field's value when the task was created: the "from" of its first change, or its value now if it never changed."""
        e = next((x for x in self.log(task_id) if x.field == field_name), None)
        if e is None:
            return now
        return "" if is_none(e.from_value) else e.from_value or ""

    def updates(self, task_id: str) -> list[Update]:
        """The task's updates, oldest first: one per capture or edit, with the state and status right after each.
        An update capture with no field changes still counts."""
        t = self.m.task(task_id)
        entries = self.log(task_id)
        groups: list[dict] = []
        for e in entries:
            g = next((x for x in groups if x["at"] == e.at and x["via"] == e.via), None)
            if g is None:
                g = {"at": e.at, "via": e.via, "changes": []}
                groups.append(g)
            g["changes"].append(e)
        for c in self.m.captures.values():
            if c.task == task_id and c.has("update") and not any(g["via"] == c.id for g in groups):
                groups.append({"at": c.saved, "via": c.id, "changes": []})
        groups.sort(key=lambda g: g["at"])

        def first(name: str) -> StatusEntry | None:
            return next((e for e in entries if e.field == name), None)

        first_state, first_status = first("State"), first("Current status")
        state = first_state.from_value if first_state else t.state
        status = ("" if is_none(first_status.from_value) else first_status.from_value) if first_status else t.current_status or ""
        out = []
        for g in groups:
            for e in g["changes"]:
                if e.field == "State":
                    state = e.to_value or ""
                if e.field == "Current status":
                    status = "" if is_none(e.to_value) else e.to_value or ""
            out.append(Update(
                g["at"], g["via"], g["changes"], state or "", status,
                any(e.field == "State" for e in g["changes"]), any(e.field == "Current status" for e in g["changes"]),
                [e for e in g["changes"] if e.field not in ("State", "Current status")],
            ))
        return out

    # ---- stories ----
    def capture_of(self, via: str | None) -> Capture | None:
        return self.m.captures.get(via) if via else None

    def created_at(self, task_id: str) -> str:
        t = self.m.task(task_id)
        c = self.capture_of(t.created_by)
        return c.saved if c else f"{t.created} 00:00:00"

    def gist(self, c: Capture, limit: int = 240) -> str:
        """A capture's own words: the first paragraph of typed text, cut at a sentence end; else its title."""
        if c.source != "typed":
            return c.title
        p = re.split(r"\n\s*\n", self.words_of(c))[0].strip()
        if len(p) <= limit:
            return p
        cut = p[:limit]
        end = cut.rfind(". ")
        return cut[:end + 1] if end > 60 else re.sub(r"\s+\S*\Z", "", cut) + "…"

    def joined_at(self, child: str, parent: str) -> str | None:
        """When ``parent`` became a parent of ``child`` through a Parents change; None if it was one from the start."""
        title = self.m.task(parent).title
        e = next((x for x in self.log(child) if x.field == "Parents" and title in list_of(x.to_value, r";\s*")
                  and title not in list_of(x.from_value, r";\s*")), None)
        return e.at if e else None

    def story(self, task_id: str) -> list[Event]:
        """The task's status log as a story, oldest first."""
        m, t = self.m, self.m.task(task_id)
        via = t.created_by if self.capture_of(t.created_by) else None
        parents = [p for p in m.parents_of(task_id) if not self.joined_at(task_id, p)]

        def init(name: str, now: str) -> str:
            return self.initial(task_id, name, now)

        recurrence = init("Recurrence", t.recurrence or "")
        deadline_desc = init("Deadline description", t.deadline_desc or "")
        facts = [
            recurrence and f"Repeats {recurrence.lower()}",
            init("Meeting", "Yes" if t.meeting else "") == "Yes" and "Meeting",
            not is_none(init("Lead", self.names(t.leads))) and f"Lead: {init('Lead', self.names(t.leads))}",
            not is_none(init("Assignees", self.names(t.assignees))) and f"Assignees: {init('Assignees', self.names(t.assignees))}",
            init("Due", t.due or "") and f"Due {self.as_date(init('Due', t.due or ''))}",
            init("Deadline", t.deadline or "") and f"Deadline {self.as_date(init('Deadline', t.deadline or ''))}"
            + (f", {deadline_desc}" if deadline_desc else ""),
        ]
        state = init("State", t.state) or t.state
        source = self.capture_of(via)
        how = "import" if t.created_by == "Excel import" else "unfiled" if source and source.filed_to == task_id and source.created_task != task_id else "new"
        events = [Event(self.created_at(task_id), "created", state=state, parents=parents, via=via, text=t.description or "",
                        status=init("Current status", (t.current_status or "") if how == "import" else ""),
                        facts=[x for x in facts if x], how=how)]
        for u in self.updates(task_id):
            before, state = state, u.state
            c = self.capture_of(u.via)
            main = (u.status or "Status cleared.") if u.status_changed else self.gist(c) if c and c.created_task != task_id else ""
            events.append(Event(u.at, "update", state=u.state, state_words=state_words(before, u.state) if u.state_changed else "",
                                main=main, facts=[s for s in (self.field_sentence(e) for e in u.others) if s], via=u.via))
        for k in m.children_of(task_id):
            s = m.task(k)
            joined = self.joined_at(k, task_id)
            verb = "New subtask" if m.parents_of(k)[0] == task_id and not joined else "Also under this task"
            asg = self.initial(k, "Assignees", self.names(s.assignees))
            due = self.initial(k, "Due", s.due or "")
            who = ", ".join("me" if self._is_me(n) else n for n in list_of(asg))
            note = ", ".join(x for x in (who, not is_none(due) and f"due {short(to_date(due), self.today)}") if x)
            events.append(Event(joined or self.created_at(k), "sub", task=k, verb=verb, note=note))
            st = self.initial(k, "State", s.state) or s.state
            for u in self.updates(k):
                before, st = st, u.state
                if not u.state_changed or not any(x in (u.state, before) for x in ("Closed", "Parked")):
                    continue  # starting work isn't a milestone
                c = self.capture_of(u.via)
                word = "Subtask closed" if u.state == "Closed" else "Subtask parked" if u.state == "Parked" else "Subtask reopened"
                events.append(Event(u.at, "sub", task=k, verb=word,
                                    note=u.status if u.status_changed and u.status else self.gist(c, 140) if c else ""))
        for a in m.agenda:
            if a.target != task_id:
                continue
            events.append(Event(a.added, "sub", task=a.subject, text=a.note, verb="Added to the agenda",
                                note=clip(a.note) if a.subject and a.note else ""))
            if a.closed:
                events.append(Event(a.closed, "sub", task=a.subject, text=a.note,
                                    verb="Taken off the agenda" if a.how == "Removed" else "Discussed"))
        return sorted(events, key=lambda e: (e.at, 0 if e.kind == "created" else 1))

    def subtask_tree(self, task_id: str) -> list[tuple[str, int]]:
        """Every subtask below a task, once each, in tree order, with its depth below the task (0 for a direct subtask)."""
        out: list[tuple[str, int]] = []
        seen: set[str] = set()

        def go(x: str, depth: int) -> None:
            for k in self.m.children_of(x):
                if k not in seen:
                    seen.add(k)
                    out.append((k, depth))
                    go(k, depth + 1)

        go(task_id, 0)
        return out

    # ---- the raw text log ----
    def words_of(self, c: Capture) -> str:
        """A capture's content text in words: a formatted capture's markup without its marks."""
        content = self.content_of(c.id)
        return items.unstore(markup.to_plain(content) if c.formatted else content)

    def capture_body(self, c: Capture) -> str:
        """The text under a capture's title: for typed text, what follows its first sentence; for an email, its body. A
        formatted capture's is markup: its lines but its file lines, and but its first when that's just its title.
        Release 5.8: meeting notes show all their text, and an item its block when it's more than its one line."""
        content = items.unstore(self.content_of(c.id))
        if c.from_notes or c.item == "notes":
            whole = content.strip("\n") if c.formatted else plain_text(content)
            return "" if c.from_notes and "\n" not in whole.strip() else whole
        if c.formatted:
            lines = [line for line in content.split("\n") if not is_file_line(markup.to_plain(line))]
            kept = "\n".join(lines).strip("\n")
            return kept if c.source == "outlook_email" else markup.without_title_line(kept, c.title)
        text = plain_text(content)
        if c.source == "outlook_email":
            return text
        found = sentences(text)
        first = found[0].text if found else ""
        return text[text.index(first) + len(first):].strip() if len(first) <= 100 else text

    def raw_items(self, task_id: str) -> list[RawItem]:
        """The task's raw text log as journal entries, oldest first."""
        out = []
        for e in self.m.raw_log_of(task_id):
            out.append(self.note_item(e.capture, task_id) if e.capture else self.version_item(e.version))
        return out

    def note_item(self, c: Capture, task_id: str) -> RawItem:
        content = self.words_of(c)
        sender = re.search(r"^From:\s*(.+)$", content, re.M) if c.source == "outlook_email" else None
        is_update = c.has("update") and c.task == task_id
        kind = (f"Email from {sender.group(1).strip()}" if sender else "Email") if c.source == "outlook_email" \
            else "File" if c.source == "file_path" else "Update" if is_update else "Decision" if c.item == "decision" else "Note"
        # What the capture did here, in the story's words: "Due date moved to Fri 23 Oct.", "Closed."
        said = []
        for e in self.m.status:
            if e.via == c.id and e.task == task_id:
                said.append(state_words(e.from_value or "", e.to_value or "") + "." if e.field == "State"
                            else "New current status." if e.field == "Current status" else self.field_sentence(e))
        for a in self.m.agenda:
            if a.added_by == c.id and a.subject == task_id:
                said.append(self.field_sentence(StatusEntry(task_id, a.added, "Agenda", None, self.m.target_name(a.target), c.id, a.target)))
        update = " ".join(s for s in said if s)
        did = ("Started this task" if c.created_task == task_id
               else ("" if c.source == "typed" else "Update: ") + update if is_update
               else f"Filed {short(to_date(c.filed), self.today)}" if c.filed_to == task_id and c.filed else "")
        docs = tuple((d, self.m.documents[d].name, self.m.documents[d].description or "") for d in c.document_ids if d in self.m.documents)
        notes = self.m.captures.get(c.from_notes) if c.from_notes else None
        held = self.m.capture_tasks(notes) if notes else []
        return RawItem(c.saved, " · ".join(x for x in (kind, did) if x), c.title, c.id, None, self.capture_body(c), c.summary,
                       c.summary_type, "The email" if c.source == "outlook_email" else "The full text", docs, c.formatted,
                       notes.id if notes else None, (self.m.task(held[0]).title if held else notes.id) if notes else "")

    def version_item(self, v: Version) -> RawItem:
        d = self.m.documents[v.document]
        return RawItem(v.at, "Document version · found by the document check", f"{d.name} changed", None, d.id, v.difference,
                       v.summary, v.summary_type, "What changed")
