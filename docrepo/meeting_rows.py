"""The task page's Meetings section (release 5.140; the design workspace's ``docs/mods/notes-consolidation-plan.md``,
decision 607, the owner's voice memo of 2026-11-12).

A task's meetings are every meeting under it, at any depth, and every meeting whose notes made, named or decided
something on it or on a task under it: its follow-ups (task items), notes, updates and decisions, each an item
capture whose ``from_notes`` is the meeting's notes capture (release 5.8). The page itself is never one of its own
meetings. A regular meeting's page lists its occurrences, which are under it.

Each row says what the meeting did here, from the items alone ("made Fill media order, Crane for the fan lift · a
decision · a note on Structural survey of the fan deck"); a meeting that did nothing to the task's tasks says its
notes' first words. A row unfolds into the meeting's notes page, its lines about this task or a task under it marked.

Everything is read from the model (the captures and the pages it holds), so it's quick and tested in the fast run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from docrepo import items, markup, notes_page
from docrepo.model import Capture, Model

#: How many meetings the section lists before "Show all" (as Email conversations and Decisions).
SHOWN = 5
#: How many characters of a meeting's notes a row shows when it did nothing to the task's tasks.
SNIPPET = 80
#: What each kind of item did, as a row says it.
KINDS = ("made", "note", "update", "decision")


@dataclass
class Touch:
    """One item a meeting's notes made on a task in view: a follow-up it ``made``, or a ``note``, ``update`` or
    ``decision`` on it, with the item's capture."""

    task: str
    kind: str
    capture: str


@dataclass
class MeetingRow:
    """A meeting in a task's Meetings section: the meeting, the day its notes were taken (its first notes capture's
    day, else its Start), whether it's under the task, its notes captures, and what its items did to the task's tasks."""

    meeting: str
    day: str
    under: bool = False
    notes: list[str] = field(default_factory=list)
    touches: list[Touch] = field(default_factory=list)


def meeting_of(model: Model, notes_id: str | None) -> str | None:
    """The live meeting a notes capture is on (its task, a task with Meeting ticked), or None."""
    notes = model.captures.get(notes_id or "")
    if notes is None or notes.discarded or notes.item != "notes":
        return None
    t = model.tasks.get(notes.task or "")
    return t.id if t is not None and t.meeting and not t.discarded else None


def item_task(c: Capture) -> str | None:
    """The task an item is about: the task a task item made, or the task a note, update or decision is filed to."""
    return c.created_task if c.item == "task" else c.task


def rows(model: Model, task_id: str) -> list[MeetingRow]:
    """The task's meetings (decision 607), the newest first."""
    scope = [x for x in model.scope_ids(task_id, "descendants") if x in model.tasks and not model.tasks[x].discarded]
    in_scope = set(scope)
    found: dict[str, MeetingRow] = {}

    def row(meeting: str) -> MeetingRow:
        if meeting not in found:
            found[meeting] = MeetingRow(meeting, "")
        return found[meeting]

    for x in scope:
        if x != task_id and model.tasks[x].meeting:
            row(x).under = True
    for c in model.captures.values():
        if c.discarded or not c.from_notes or c.item not in ("task", "note", "update", "decision"):
            continue
        target = item_task(c)
        if target not in in_scope:
            continue
        meeting = meeting_of(model, c.from_notes)
        if meeting is None or meeting == task_id or (target == meeting and c.item == "task"):
            continue
        row(meeting).touches.append(Touch(target, "made" if c.item == "task" else c.item, c.id))
    for c in model.captures.values():  # each meeting's notes, for its day and its unfolded lines
        if c.item == "notes" and not c.discarded and c.task in found:
            found[c.task].notes.append(c.id)
    for r in found.values():
        r.notes.sort(key=lambda n: model.captures[n].saved)
        t = model.tasks[r.meeting]
        r.day = (model.captures[r.notes[0]].saved[:10] if r.notes else (t.start or t.due or t.created or "")[:10])
        r.touches.sort(key=lambda x: (KINDS.index(x.kind), model.captures[x.capture].saved))
    return sorted(found.values(), key=lambda r: (r.day, model.tasks[r.meeting].title.lower()), reverse=True)


def _a(n: int, word: str) -> str:
    return f"a {word}" if n == 1 else f"{n} {word}s"


def words(model: Model, r: MeetingRow, task_id: str, content_of=None) -> str:
    """What a row says the meeting did here: the follow-ups it made, its decisions, and its notes and updates on each
    task, "this task" for the page's own. With none, the first words of its notes (``content_of`` reads them)."""
    def name(x: str) -> str:
        return "this task" if x == task_id else model.tasks[x].title

    made = list(dict.fromkeys(x.task for x in r.touches if x.kind == "made"))
    parts = [f"made {', '.join(name(x) for x in made)}"] if made else []
    decided = sum(1 for x in r.touches if x.kind == "decision")
    if decided:
        parts.append(_a(decided, "decision"))
    for kind, word, on in (("note", "note", "on"), ("update", "update", "to")):
        per: dict[str, int] = {}
        for x in r.touches:
            if x.kind == kind:
                per[x.task] = per.get(x.task, 0) + 1
        parts += [f"{_a(n, word)} {'here' if x == task_id else f'{on} {name(x)}'}" for x, n in per.items()]
    if parts:
        return " · ".join(parts)
    if content_of is not None and r.notes:
        text = " ".join(markup.to_plain(items.unstore(content_of(r.notes[0]) or "")).split())
        return text if len(text) <= SNIPPET else text[:SNIPPET - 1].rstrip() + "…"
    return ""


def _same(line: str) -> str:
    """A line's words, to match an item's lines in its meeting's page: names as written, no marks, no list marker."""
    words_ = " ".join(markup.to_plain(items.unstore(line)).split())
    return words_[2:] if words_.startswith(("- ", "* ", "• ")) else words_


def marked_lines(model: Model, r: MeetingRow, task_id: str, content_of) -> list[tuple[notes_page.Line, bool]]:
    """The meeting's notes page as lines, each with whether it's about this task or a task under it (decision 607): its
    task lines for them, a ``#`` line naming one, and the lines of their notes, updates and decisions."""
    scope = set(model.scope_ids(task_id, "descendants"))
    titles = {f"#{model.tasks[x].title}".casefold() for x in scope if x in model.tasks}
    wanted: set[str] = set()
    for x in r.touches:
        if x.kind != "made" and x.task in scope:
            wanted |= {w for line in (content_of(x.capture) or "").split("\n") if (w := _same(line))}
    out = []
    for line in notes_page.lines_of(model.pages.get(r.meeting, "")):
        if line.kind == "task":
            hit = line.ref in scope
        elif line.kind == "text":
            plain = _same(line.text)
            hit = bool(plain) and (plain in wanted or plain.casefold() in titles)
        else:
            hit = False
        out.append((line, hit))
    return out
