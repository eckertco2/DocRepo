"""Notes without the operators (release 5.150; the design workspace's ``docs/mods/notes-syntax-plan.md``, decisions 652 to
657, the owner's voice memo of 2026-11-13): what a notes page writes for a line of notes whose operators did something,
so the page reads as words, not syntax.

- A **change line** (decision 654): a line that changed a ``#`` task, put something on an agenda or set a field on the
  task it's under is its words without the operators, then what it did, quietly, with the task as its link:
  ``#Rigging plan **due, 30 Nov **lead, Tom`` reads "Rigging plan · Due Mon 30 Nov · Lead Tom Becker",
  ``Ask about the hire rate **agenda, Tom`` "Ask about the hire rate · on Tom Becker's agenda", and
  ``Seals look worn **label, Rigging`` "Seals look worn · Rigging". An item said with a ``**`` kind (``**closed,``,
  ``**decision,``) says what it was: "Rigging plan: crane booked · Closed". The same line reads the same on the page of
  the task it changed, in its item's block.
- **A made task's own line** (decision 653): on the page of a task the notes made, the line it was made from without its
  operators, names written as names ("Tom Becker book the 50 t crane"), and what its ``**`` operators set in a quiet line
  under it, "Set from Pump trial's notes · Due Fri 23 Oct · Rigging" (``notes_page.set_line``). On the page it came from
  it's a task line already (release 5.83).

A line is rewritten only when every operator on it did what it says. One that read as nothing (its Unread card, release
5.92) or wasn't used (a field already filled, a card unticked, no task to put it on) stays as typed, so nothing is lost,
as Save's message says: "2 lines weren't used: they stay in the notes." The capture's ``capture.md`` and the raw text log
keep every line as typed (decision 655).

What a line did comes from the reading of the words it was saved from (``items.Reading``), never from the page: at Save,
the save's own reading and what ``save._save_items`` did (``Said``); later, for a capture's block (``notes_page.block``,
as a block is added again, a page built or a discard checks it), the capture's words read again as of the day it was
saved, each operator checked against what that save left: its status log lines, agenda items and item captures
(``recorded``). Tidy the notes (decision 656, ``tidy``) reads older pages the same way.

Nothing here touches Qt.
"""
from __future__ import annotations

import re
import weakref
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from docrepo import items, markup
from docrepo.config import Settings, SettingsError
from docrepo.dates import long_date, to_date, workday_numbers
from docrepo.model import TODAY, Capture, Model
from docrepo.parse import ParsePerson

#: What a note that's no capture is logged as coming from (``save``'s ``via`` for it, release 5.69).
WINDOW = "Capture window"
#: Between a change line's parts.
DOT = " · "
#: The kinds of item a ``**`` kind makes besides a task, as their change line says them.
KIND_WORDS = {"note": "Note", "update": "Update", "decision": "Decision"}


@dataclass(frozen=True)
class Rewrite:
    """A block's lines as a page writes them now: each line of its words to write otherwise, by its number in the words
    (``lines``), and the lines after its text (``after``, a made task's set line)."""

    lines: Mapping[int, str] = field(default_factory=dict)
    after: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.lines or self.after)


NONE = Rewrite()


@dataclass
class Said:
    """What one save's items did, for the page it writes at once (a note that's no capture): the reading of its words,
    the keys of the items that did something, the task each task item made, and the day it was read as."""

    reading: items.Reading
    names: items.Names
    used: set[str]
    made: dict[str, str]
    today: date
    formatted: bool = True


# ---- the words without the operators ----
_SPACES = re.compile(r"[ \t]+")
_BEFORE_MARK = re.compile(r"\s+([,.;:!?])")
_LEADING = re.compile(r"^[\s,;:&.–—-]+")
_TRAILING = re.compile(r"[\s,;:&–—-]+$")


def plain_words(text: str, toks: Sequence[items.Token], names: items.Names) -> str:
    """A line's words without its operators (decisions 653 and 654): a field's operator goes with its sentence, a ``**``
    kind goes (with a colon in its place when there are words on both sides: "Rigging plan: crane booked"), and a name
    stays as a name, a person's in full and a task's by its title. The first letter is made a capital when an operator
    came before it."""
    out: list[str] = []
    at, opened = 0, False
    for x in toks:
        if x.inside:  # an @ or # in a field's sentence goes with the sentence
            continue
        out.append(text[at:x.start])
        if x.kind == "param":
            at = max(x.until, x.end)
            out.append(" ")
        elif x.kind == "type":
            at = x.end
            out.append("\x00")
        elif x.kind == "person":
            out.append("" if x.none else (x.name or x.typed))
            at = x.end
        else:
            out.append(names.task_title(x.id) if x.id else x.typed)
            at = x.end
        if not "".join(out).replace("\x00", "").strip() and x.kind in ("param", "type"):
            opened = True
    out.append(text[at:])
    s = "".join(out)
    if "\x00" in s:
        head, _, tail = s.partition("\x00")
        tail = tail.replace("\x00", " ")
        head_words, tail_words = _TRAILING.sub("", head.strip()), _LEADING.sub("", tail.strip())
        s = f"{head_words}: {tail_words}" if head_words and tail_words else head_words or tail_words
    s = _SPACES.sub(" ", s)
    s = _BEFORE_MARK.sub(r"\1", s)
    s = _TRAILING.sub("", _LEADING.sub("", s.strip()))
    s = re.sub(r"\s*\.$", "", s) if s.endswith(" .") else s
    if opened and s:
        s = s[:1].upper() + s[1:]
    return s


# ---- what an item did, in words ----
def _listed(names: Sequence[str]) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}" if names else ""


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _date_words(value: object, today: date) -> str | None:
    """A field's value as a date in words, "Mon 30 Nov", when it's a day (YYYY-MM-DD); None for any other value."""
    if not isinstance(value, str) or not _ISO_DAY.fullmatch(value[:10]):
        return None
    try:
        return long_date(to_date(value), today)
    except ValueError:
        return None


def did_words(it: items.Item, model: Model, today: date) -> str:
    """What an item did, as its change line says it: "Due Mon 30 Nov", "Lead Tom Becker", a label's name, "on Tom
    Becker's agenda", "Key date Trial window, Sun 1 Nov to Thu 5 Nov", "Closed" or "Decision"."""
    if it.kind in KIND_WORDS:
        return it.state or KIND_WORDS[it.kind]
    if it.kind == "date":
        kd = it.key_date
        if kd is None:
            return "Key date"
        when = [w for w in (_date_words(kd.start, today), _date_words(kd.end, today)) if w]
        span = " to ".join(dict.fromkeys(when))
        words = it.title if it.changed else kd.description
        return "Key date " + ", ".join(x for x in (words, span) if x)
    op, v = it.op, it.value
    if op is None or v is None:
        return it.title
    ch = v.changes
    f = op.task_field
    if f == "agenda":
        return DOT.join("on Today" if t == TODAY else f"on {model.target_name(t)}'s agenda" for t in ch.get("agenda", ()))
    if f == "labels":
        return ", ".join(str(x) for x in ch.get("labels", ()))
    if f in ("leads", "assignees"):
        people = [model.person_name(w.id) if getattr(w, "id", None) else getattr(w, "name", str(w)) for w in ch.get(f, ())]
        label = "Lead" if f == "leads" else "Assignee" if len(people) == 1 else "Assignees"
        return f"{label} {_listed(people)}"
    value = ch.get(f)
    if isinstance(value, bool):
        return op.label if value else f"{op.label}: no"
    when = _date_words(value, today)
    if when:
        about = ch.get("deadline_desc") if f == "deadline" else None  # "Deadline Thu 19 Nov, the external audit"
        return f"{op.label} {when}" + (f", {about[:1].lower()}{about[1:]}" if isinstance(about, str) and about else "")
    shown = re.sub(r" \(new\)", "", v.shown or it.title or "")
    return f"{op.label} {shown}".strip()


# ---- what each item acted on ----
def targets(it: items.Item, home: str | None, made: Mapping[str, str]) -> list[str]:
    """The tasks an item went on: a ``#`` task, the task item it's on or under (by the task it made), or the home task."""
    out = []
    for w in it.where:
        ref = w.ref if w.kind == "task" else home if w.kind == "home" else made.get(w.ref or "") if w.kind == "item" else None
        if ref and ref not in out:
            out.append(ref)
    return out


def _on_line(reading: items.Reading, n: int) -> list[items.Item]:
    return [it for it in reading.items if it.line == n]


def _operators_on(L: items.Line) -> list[items.Token]:
    return [x for x in L.toks if x.kind in ("param", "type") and not x.inside]


def _unread(reading: items.Reading) -> set[int]:
    return {n for n, _ in reading.unread}


def change_line_for(L: items.Line, its: Sequence[items.Item], used: Callable[[items.Item, list[str]], bool], home: str | None,
                    made: Mapping[str, str], page_task: str, model: Model, names: items.Names, today: date,
                    listed: bool = True, under: Sequence[str] = ()) -> str | None:
    """The change line for one line of notes (decision 654), or None when it stays as typed: it has no ``**`` operator,
    it makes a task (a task line on this page), or an operator on it read as nothing or wasn't used. ``listed``: a list
    item stays one (formatted words; in plain ones a "- " is only text). ``under``: the tasks a ``#`` heading above it
    names, which it needn't name again."""
    from docrepo import notes_page

    ops = _operators_on(L)
    if not ops or not its or any(it.kind == "task" for it in its):
        return None
    if any(x.kind == "param" and x.problem for x in ops):
        return None
    typed_kind = any(x.kind == "type" for x in ops)
    parts: list[str] = []
    acted: list[str] = []
    for it in sorted(its, key=lambda x: int(x.key)):
        where = targets(it, home, made)
        if not used(it, where):
            return None
        if it.kind in KIND_WORDS and not typed_kind:
            acted += where  # a # alone made it a note: its words say so
            continue
        parts.append(did_words(it, model, today))
        acted += where
    parts = [p for p in parts if p]
    if not parts:
        return None
    words = plain_words(L.text, L.toks, names)
    other = next((t for t in acted if t != page_task and t in model.tasks), None)
    ref = other or page_task
    if other:
        title = model.task(other).title
        if not words:
            words = title
        elif title.casefold() not in words.casefold() and other not in under:
            parts.insert(0, title)
    level = L.level + 1 if L.is_list and listed else 0
    return notes_page.change_line(words, ref, DOT.join(parts), level)


# ---- the rewrites ----
def _heading_tasks(reading: items.Reading, L: items.Line) -> list[str]:
    b = reading.blocks[L.block] if L.block is not None and L.block < len(reading.blocks) else None
    while b is not None and b.parent is not None:
        b = reading.blocks[b.parent]
    return list(b.heading.tasks) if b is not None and b.heading is not None else []


def pointed(reading: items.Reading, page_task: str) -> set[int]:
    """In Meeting notes, the lines of each note, update or decision a ``#`` task took: a pointer line takes their place on
    the meeting's page (release 5.143, decision 614), and their change lines are on that task's page."""
    out: set[int] = set()
    for it in reading.items:
        if it.kind in KIND_WORDS and any(w.kind == "task" and w.ref != page_task for w in it.where):
            out.update(it.lines)
    return out


def for_notes(reading: items.Reading, used: Callable[[items.Item, list[str]], bool], home: str | None, made: Mapping[str, str],
              page_task: str, model: Model, names: items.Names, today: date, formatted: bool = True,
              skip: Iterable[int] = ()) -> dict[int, str]:
    """Each line of the notes' words that's a change line on ``page_task``'s page, by its number (decision 654). The lines
    that make tasks are left to ``notes_page.task_lines`` (release 5.83), and those in ``skip`` to the pointer lines; a
    line read as nothing stays (5.92)."""
    out: dict[int, str] = {}
    unread = _unread(reading) | set(skip)
    for L in reading.lines:
        if L.n in unread or L.heading is not None:
            continue
        line = change_line_for(L, _on_line(reading, L.n), used, home, made, page_task, model, names, today, formatted,
                               _heading_tasks(reading, L))
        if line is not None:
            out[L.n] = line
    return out


def own_line(reading: items.Reading, used: Callable[[items.Item, list[str]], bool], task_id: str, notes_task: str | None,
             model: Model, names: items.Names, today: date, formatted: bool = True) -> Rewrite:
    """A made task's own first line on its own page (decision 653): its first line of words without its operators, as a
    text line with its list marker, and the set line under its words when its ``**`` operators set anything: "Set from
    Pump trial's notes · Due Fri 23 Oct · Rigging". Every operator on the line must have done what it says, and each field
    on it must be this task's; otherwise it stays as typed. ``formatted``: the words are markup, so a list marker is a
    list item's; in plain words it's text, escaped as the page escapes it."""
    from docrepo import notes_page

    first = next((L for L in reading.lines if L.raw.strip()), None)
    if first is None or not first.toks:
        return NONE
    if first.n in _unread(reading) or any(x.kind == "param" and x.problem for x in first.toks if not x.inside):
        return NONE
    its = _on_line(reading, first.n)
    task_item = next((it for it in its if it.kind == "task"), None)
    if task_item is None:
        return NONE
    made = {task_item.key: task_id}
    parts = []
    for it in sorted(its, key=lambda x: int(x.key)):
        if it is task_item:
            continue
        where = targets(it, None, made)
        if where != [task_id] or not used(it, where):
            return NONE
        parts.append(did_words(it, model, today))
    words = plain_words(first.text, first.toks, names)
    head = first.raw[:first.off] if first.is_list else ""
    line = head + markup.escape_inline(words) if formatted else markup.escape(head + words)
    out = {first.n: notes_page.text_line(line)} if words else {}
    parts = [p for p in parts if p]
    after = ()
    if parts:
        notes_title = model.task(notes_task).title if notes_task and notes_task in model.tasks else ""
        said = f"Set from {notes_title}'s notes" if notes_title else "Set from the notes"
        after = (notes_page.set_line(said, notes_task if notes_task in model.tasks else task_id, DOT.join(parts)),)
    if not out and not after:
        return NONE
    return Rewrite(out, after)


# ---- what a save left: its records ----
def _log_fields(op: items.Operator | None) -> frozenset[str]:
    """The status log's names for the field an operator fills."""
    from docrepo import tasks

    if op is None:
        return frozenset()
    f = op.task_field
    if op.reference:
        return frozenset({op.label})
    if f in ("lead_hours", "assignee_hours"):
        return frozenset(tasks.FIELD_NAMES[k] for k in tasks.HOUR_FIELDS)
    if f == "priority":
        return frozenset({"Priority"})
    if f == "parents":
        return frozenset({"Parents"})
    if f == "involvement":
        return frozenset()  # logged per person ("Tom Becker's involvement"): matched by its ending
    if f in ("start", "due"):
        return frozenset({tasks.FIELD_NAMES[f], f"{tasks.FIELD_NAMES[f]} tie"})
    return frozenset({tasks.FIELD_NAMES.get(f, op.label)})


_RECORDS: "weakref.WeakKeyDictionary[Model, tuple[dict, dict]]" = weakref.WeakKeyDictionary()


def _records(model: Model) -> tuple[dict, dict]:
    """The model's status log lines and agenda items by what they came from, worked out once per model."""
    kept = _RECORDS.get(model)
    if kept is None:
        status: dict[str, list] = {}
        agenda: dict[str, list] = {}
        for e in model.status:
            status.setdefault(e.via, []).append(e)
        for a in model.agenda:
            agenda.setdefault(a.added_by, []).append(a)
        kept = _RECORDS[model] = (status, agenda)
    return kept


def _when(stamp_: str, at: str | None) -> bool:
    """A record's time against ``at``: any with None, the same time, or the same day when ``at`` is a day."""
    return at is None or stamp_ == at or (len(at) == 10 and stamp_[:10] == at)


def recorded(model: Model, via: str, at: str | None = None, notes: str | None = None) -> Callable[[items.Item, list[str]], bool]:
    """Whether an item did what it says, by what the save left (``via``, the capture it's logged as, and for a note that's no
    capture its time ``at``, or its day): a field, a line in the status log of a task it went on; a key date, its Key date
    line; an agenda, an agenda item it added; a note, update or decision, its item's capture, from the notes ``notes``
    (None for a note that's no capture, then by its time). A task item is a task line's, found by its capture.

    Only the records count, not the reading's own word: read again, a field this save filled reads as already filled."""
    by_via = _records(model)
    status = [e for e in by_via[0].get(via, ()) if _when(e.at, at)]
    agenda = [a for a in by_via[1].get(via, ()) if _when(a.added, at)]

    def kind_made(kind: str, where: list[str]) -> bool:
        return any(c.item == kind and not c.discarded and c.task in where and c.from_notes == notes
                   and (notes is not None or _when(c.saved, at)) for c in model.captures.values())

    def used(it: items.Item, where: list[str]) -> bool:
        if it.kind in KIND_WORDS:
            return bool(where) and kind_made(it.kind, where)
        if it.kind == "date":
            return any(e.field == "Key date" and e.task in where for e in status)
        if it.kind != "param" or it.op is None:
            return False
        if it.op.task_field == "agenda":
            wanted = set(it.value.changes.get("agenda", ())) if it.value else set()
            return any(a.target in wanted and (a.subject in where if where else a.subject is None) for a in agenda)
        names = _log_fields(it.op)
        if it.op.task_field == "involvement":
            return any(e.task in where and e.field.endswith("'s involvement") for e in status)
        return any(e.task in where and e.field in names for e in status)

    return used


def save_used(said: Said) -> Callable[[items.Item, list[str]], bool]:
    """``Said``'s answer: an item did something when Save says it did."""
    return lambda it, _where: it.key in said.used


# ---- reading a capture's words again ----
_SETTINGS: dict[Path, tuple[float, Settings]] = {}


def settings_of(data_root: Path | None) -> Settings:
    """The data root's Settings, read once while settings.json is unchanged (the reference fields name operators); the
    defaults when there's none, or it can't be read."""
    if data_root is None:
        return Settings()
    file = data_root / "Config" / "settings.json"
    try:
        mtime = file.stat().st_mtime
    except OSError:
        return Settings()
    kept = _SETTINGS.get(file)
    if kept is not None and kept[0] == mtime:
        return kept[1]
    try:
        s = Settings.load(data_root)
    except SettingsError:
        s = Settings()
    _SETTINGS[file] = (mtime, s)
    return s


def names_for(model: Model, settings: Settings, refs: Mapping[str, str] | None = None) -> items.Names:
    """The people and tasks operators can name, as Save's are (``save.item_names``)."""
    people = [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == settings.me) for p in model.people.values()]
    return items.names_of(model, people, refs, settings.reference_fields, len(workday_numbers(settings.workdays)))


def words_of(c: Capture, content: str) -> str:
    """A capture's words line for line, as Save read them: names as written, marks dropped from a formatted one."""
    text = items.unstore(content)
    return "\n".join(markup.to_plain(x) for x in text.split("\n")) if c.formatted else text


def reread(model: Model, c: Capture, content: str, settings: Settings, *, own: str | None = None, home: bool = True,
           new_task: bool = False) -> tuple[items.Reading, items.Names]:
    """A capture's words read again as of the day it was saved, its names by the IDs its capture.md keeps."""
    names = names_for(model, settings, items.refs_of(content))
    today = datetime.fromisoformat(c.saved).date()
    return items.read(words_of(c, content), names, today, events=settings.event_words, home=home, new_task=new_task, own=own), names


def has_operator(text: str) -> bool:
    """Whether words may hold a ``**`` operator: as typed, or as markup keeps it (``\\*\\*``)."""
    return "**" in text or "\\*\\*" in text


def notes_via(c: Capture) -> tuple[str, str | None]:
    """What an item's save is logged as: the notes' capture, or for a note that's no capture the capture window, at its time."""
    return (c.from_notes, None) if c.from_notes else (WINDOW, c.saved)


def capture_rewrite(model: Model, c: Capture, task_id: str, content: str | None, settings: Settings,
                    content_of: Callable[[str], str | None]) -> Rewrite:
    """A capture's block's rewrite on ``task_id``'s page (``notes_page.block``): a made task's own line (653) when it's a
    task item's capture on its task's page, else the change lines among its words (654). NONE for a capture with no
    operator to take out, an email's or one discarded. ``content_of`` reads an item capture's words."""
    if not content or c.discarded or c.source == "outlook_email":
        return NONE
    day = datetime.fromisoformat(c.saved).date()
    if c.item == "task" and c.created_task == task_id:
        if not any(ch in content for ch in "@#*"):
            return NONE
        reading, names = reread(model, c, content, settings, home=True)
        via, at = notes_via(c)
        notes = model.captures.get(c.from_notes or "")
        notes_task = (notes.task if notes is not None else None) or c.task
        return own_line(reading, recorded(model, via, at), task_id, notes_task, model, names, day, c.formatted)
    if not has_operator(content):
        return NONE
    if c.item in KIND_WORDS:  # a note, update or decision from notes, in its own block: its own line, read alone
        reading, names = reread(model, c, content, settings, home=True)
        via, at = notes_via(c)
        notes_used = recorded(model, via, at, c.from_notes)  # its fields were logged as the notes'

        def used(it: items.Item, where: list[str]) -> bool:
            if it.kind in KIND_WORDS:  # its own capture is the record that it was made
                return bool(where) and (task_id in where or c.task in where)
            return notes_used(it, where)

        return Rewrite(for_notes(reading, used, c.task, {}, task_id, model, names, day, c.formatted))
    new_task = c.has("new_task") and bool(c.created_task)
    own = c.task if c.task and c.item != "notes" and (not new_task or c.has("update")) else None
    reading, names = reread(model, c, content, settings, own=own, home=bool(c.task or c.created_task), new_task=new_task)
    home = c.created_task or c.task
    made = _made_items(model, c, reading, content, content_of)
    skip = pointed(reading, task_id) if c.item == "notes" else set()
    return Rewrite(for_notes(reading, recorded(model, c.id, notes=c.id), home, made, task_id, model, names, day, c.formatted, skip))


def _made_items(model: Model, c: Capture, reading: items.Reading, content: str, content_of: Callable[[str], str | None]) -> dict[str, str]:
    """A capture's task items, each by the task its item's capture made: the item's block as written is that capture's words."""
    from docrepo.notes_page import _same_line

    lines = content.split("\n")
    mine = sorted((x for x in model.captures.values() if x.from_notes == c.id and x.item == "task" and x.created_task), key=lambda x: x.id)
    if not mine:
        return {}
    texts = {x.id: [_same_line(y) for y in (content_of(x.id) or "").split("\n") if y.strip()] for x in mine}
    out: dict[str, str] = {}
    taken: set[str] = set()
    for it in reading.items:
        if it.kind != "task":
            continue
        key = [_same_line(lines[n]) for n in it.lines if n < len(lines) and lines[n].strip()]
        hit = next((x for x in mine if x.id not in taken and texts[x.id] == key), None)
        if hit is not None:
            taken.add(hit.id)
            out[it.key] = hit.created_task
    return out


def said_rewrite(said: Said, page_task: str, model: Model) -> dict[int, str]:
    """A note that's no capture, as Save puts it on its page (``edits.add_note``): its change lines, from the save's own
    reading and what its items did."""
    return for_notes(said.reading, save_used(said), page_task, said.made, page_task, model, said.names, said.today, said.formatted)


# ---- Tidy the notes: older pages (decision 656) ----
@dataclass(frozen=True)
class TidyLine:
    """A change Tidy the notes would make on a page: its lines from ``start`` to ``end`` (``before``, as they are) written
    as ``after``. One or more lines: a made task's item and its bullets become one task line, a set line comes in under
    the line it's for."""

    task: str
    start: int
    end: int
    before: tuple[str, ...]
    after: tuple[str, ...]


def _changes(old: list[str], new: list[str]) -> list[tuple[list[str], list[str]]]:
    """Where ``new`` differs from ``old``, each as (its old lines, its new lines): a line written otherwise is a change of
    its own, so one edited since doesn't hold back the lines beside it; lines that became fewer (a made task's item and
    its bullets, one task line) are one change; a line only added comes with the line before it, so it has a place."""
    import difflib

    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if i1 == i2:
            if i1 == 0 or j1 == 0:
                continue
            i1, j1 = i1 - 1, j1 - 1
        if i2 - i1 == j2 - j1:
            out += [([old[i]], [new[j]]) for i, j in zip(range(i1, i2), range(j1, j2))]
        else:
            out.append((old[i1:i2], new[j1:j2]))
    return out


def _find(lines: Sequence[str], want: Sequence[str], lo: int, hi: int, taken: set[int]) -> int | None:
    n = len(want)
    for i in range(lo, max(lo, hi - n + 1)):
        if list(lines[i:i + n]) == list(want) and not taken.intersection(range(i, i + n)):
            return i
    return None


def tidy_lines(model: Model, stories, task_id: str) -> list[TidyLine]:
    """What Tidy the notes would change on a task's page (decision 656), in page order: each line still as it was typed
    that release 5.150 writes otherwise, and, on pages from before release 5.83, each made task's lines as typed that are a
    task line now. A line the owner has changed since isn't listed; neither is anything moved there (5.143).

    A capture's block is compared with that block as it was written then: only lines still exactly so are listed. Lines
    typed on the page, with no capture behind them (release 5.69), are read with the day heading they're under, and what
    each operator did is looked for in the status log and agenda of that day, as the capture window's."""
    from docrepo import notes_page as npg

    page = model.pages.get(task_id, "")
    if not page or task_id not in model.tasks:
        return []
    raw = page.split("\n")
    read = [npg.read_line(x) for x in raw]
    out: list[TidyLine] = []
    taken: set[int] = set()

    def ends(i: int) -> bool:
        x = read[i]
        return x.kind in ("caption", "lead", "pointer") or (x.kind == "heading" and npg.day_of(x.text) is not None)

    def keep(start: int, before: list[str], after: list[str]) -> None:
        taken.update(range(start, start + len(before)))
        out.append(TidyLine(task_id, start, start + len(before), tuple(before), tuple(after)))

    in_block: set[int] = set()
    for i, x in enumerate(read):
        if x.kind != "caption":
            continue
        end = i + 1
        while end < len(read) and not ends(end):
            end += 1
        in_block.update(range(i, end))
        c = model.captures.get(x.ref)
        content = npg.typed_content(c, stories.content_of(c.id)) if c is not None and not c.discarded else None
        if not content or not any(ch in content for ch in "*@#"):
            continue
        new = npg.block(model, stories, c, task_id, content)
        for old in (npg.block(model, stories, c, task_id, content, rewrite=False, made_lines=False),
                    npg.block(model, stories, c, task_id, content, rewrite=False)):
            for before, after in _changes(old, new):
                at = _find(raw, before, i, end, taken)
                if at is not None:
                    keep(at, before, after)
    # Lines typed on the page (a note that's no capture), a run of text under a day heading at a time.
    settings = getattr(stories, "settings", None) or Settings()
    day: date | None = None
    lead = False
    run: list[int] = []

    def flush() -> None:
        if run and day is not None:
            _tidy_run(model, stories, settings, task_id, day, raw, run, taken, keep)
        run.clear()

    for i, x in enumerate(read):
        if x.kind == "heading" and (d := npg.day_of(x.text)):
            flush()
            day, lead = d, False
            continue
        if x.kind == "lead":
            flush()
            lead = True  # lines moved here: not this page's typing
            continue
        if x.kind == "text" and i not in in_block and not lead:
            run.append(i)
            continue
        flush()
    flush()
    return sorted(out, key=lambda t: t.start)


def _tidy_run(model: Model, stories, settings: Settings, task_id: str, day: date, raw: Sequence[str], run: Sequence[int],
              taken: set[int], keep: Callable[[int, list[str], list[str]], None]) -> None:
    """A run of lines typed on a page, as Save would write them now: its made tasks' lines (by their captures of that day)
    as task lines, and its change lines from what the status log and agenda say that day's capture window did."""
    from docrepo import notes_page as npg

    lines = [raw[i] for i in run]
    if not any("\\*\\*" in x or "**" in x or "@" in x for x in lines):
        return
    words = "\n".join(markup.to_plain(npg.read_line(x).text) for x in lines)
    names = names_for(model, settings)
    reading = items.read(words, names, day, events=settings.event_words, home=True, own=task_id)
    rewrites = for_notes(reading, recorded(model, WINDOW, day.isoformat()), task_id, {}, task_id, model, names, day, True)
    new = [rewrites.get(n, line) for n, line in enumerate(lines)]
    made = [(x.created_task, npg.note_markup(stories.content_of(x.id), x.formatted, "", task_id))
            for x in sorted(model.captures.values(), key=lambda x: x.id)
            if x.item == "task" and x.created_task and not x.from_notes and not x.discarded and x.task == task_id
            and x.saved[:10] == day.isoformat()]
    if made:
        new = npg.task_lines(new, made, model, stories.today)
    for before, after in _changes(lines, new):
        at = _find(raw, before, run[0], run[-1] + 1, taken)
        if at is not None and all(i in run for i in range(at, at + len(before))):
            keep(at, before, after)


def apply_tidy(page: str, chosen: Sequence[TidyLine]) -> tuple[str, int]:
    """The page with the chosen changes made, last first so each keeps its place; one whose lines aren't as listed any
    more is left. Returns the page and how many of its lines were tidied."""
    raw = page.split("\n")
    n = 0
    for t in sorted(chosen, key=lambda t: t.start, reverse=True):
        if tuple(raw[t.start:t.end]) != t.before:
            continue
        raw[t.start:t.end] = list(t.after)
        n += len(t.before)
    return "\n".join(raw), n
