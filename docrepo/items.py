"""Items from operators (mods log round 2, M0048 phase 2, M0049, M0052, with M0023; release 5.8).

In any capture, a block of the content text with an operator becomes an item: a task, a note, an update or a
decision. A block is a line, with the list items under it that have no operator of their own; a list item under it
with an operator is a block of its own, inside it. Operators are read from the content text's words (never from an
added email), and only after a space, a "(" or the start of a line, so an address such as tom@example.com stays text.

- ``@Tom``, ``@Tom Becker``: a task, with Tom an assignee (several allowed). ``@L.Tom``: a task, with Tom its lead.
  ``@__``: a task with no one yet.
- ``#Rigging plan``, ``#T000012``: a link to that task, as a parent. With no ``@`` or ``**``, the block is a note on
  it. On a line of its own (a heading), it covers the lines under it, until the next heading.
- ``**t``, ``**n``: a task, or a note, said outright. ``**Closed.``, ``**Done.``, ``**Parked.``, ``**In progress.``,
  ``**Started.``: an update to the ``#`` task with that state; the rest is its current status. ``**u``: an update with
  no state change. ``**Decision.``: a decision, on the ``#`` task, else on the capture's task or meeting.

A ``**`` type wins; else an ``@`` makes a task; else a ``#`` alone makes a note; a block with none stays in the notes.
``**`` and a space is never an operator, and ``#`` is a link only when it names a task, so "Pump #3" stays text.

capture.md keeps each ``@`` and ``#`` with its ID (M0049): ``@[Tom Becker](P003)``, ``@L.[Priya Shah](P002)``,
``#[Rigging plan](T000012)``, so renaming a person or a task never breaks it (``store``, ``unstore``).

Ported from the mockup's ``items.js``; decisions 37 to 52 of the round 2 plan.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from docrepo import markup
from docrepo.parse import EVENT_WORDS, STATE_WORDS, ParseLabel, ParsePerson, Who, parse_capture, quick_update
from docrepo.text import first_sentence

KIND_NAMES = {"task": "Task", "note": "Note", "update": "Update", "decision": "Decision"}
TYPE_RE = re.compile(rf"^\*\*(?:([tnu])(?![A-Za-z0-9_])|(decision)\b[.:]?|({STATE_WORDS})\b[.:]?)", re.I)
LIST_RE = re.compile(r"^([ \t]*)([-*•]|\d+[.)])\s+")
#: An @ or # kept with its ID in capture.md.
STORED = re.compile(r"(@L\.|@|#)\[([^\]\n]+)\]\(([PT]\d+)\)", re.I)
_STORED_PERSON = re.compile(r"\[([^\]\n]+)\]\((P\d+)\)")
_STORED_TASK = re.compile(r"\[([^\]\n]+)\]\((T\d+)\)")
_SEP = re.compile(r"[\s,;:&–—-]*(?:and\s*)?\Z", re.I)
_TRAIL = re.compile(r"[\s,;:&.!?–—-]*(?:and\b[\s,;:&.!?–—-]*)?\Z", re.I)
# A name ending the line after "with", "for", "see" and so on is part of the sentence: "done with @Mike" keeps Mike.
_PREP = re.compile(r"\b(?:with|to|for|from|by|of|at|about|ask|tell|call|email|and|see|on|in|under)\s*\Z", re.I)
_LEAD_IN = re.compile(r"^(?:to|will|should|please|needs? to|has to|must)\s+", re.I)
_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)
_TYPING = re.compile(r"(?:^|[\s(])(@L\.|@|#)([^\s@#*]*(?: [^\s@#*]+){0,4})\Z", re.I)


def _is_word(ch: str) -> bool:
    return bool(ch) and (ch.isascii() and (ch.isalnum() or ch == "_"))


# ---- the people and tasks operators can name ----
@dataclass(frozen=True)
class RefTask:
    id: str
    title: str
    open: bool = True  # not Closed: offered in the # list


class Names:
    """The people and tasks operators can name. ``prefer`` maps a name as written ("@tom becker", "#rigging plan", in
    lower case) to the ID it was picked as, or kept as in capture.md, ahead of the lists."""

    def __init__(self, people: Sequence[ParsePerson], tasks: Sequence[RefTask], prefer: Mapping[str, str] | None = None) -> None:
        self.people = list(people)
        self.active = [p for p in self.people if p.status == "active"]
        self.person_by_id = {p.id: p for p in self.people}
        self.person_names = sorted(((n, p.id) for p in self.active for n in (p.name, *p.aliases) if n), key=lambda x: -len(x[0]))
        self.tasks = {t.id: t for t in tasks}
        self.task_names = sorted(((t.title, t.id) for t in tasks), key=lambda x: -len(x[0]))
        prefer = prefer or {}
        self.prefer_people = sorted(((k[1:], v) for k, v in prefer.items() if k.startswith("@")), key=lambda x: -len(x[0]))
        self.prefer_tasks = sorted(((k[1:], v) for k, v in prefer.items() if k.startswith("#")), key=lambda x: -len(x[0]))

    def person_name(self, person_id: str) -> str:
        p = self.person_by_id.get(person_id)
        return p.name if p else person_id

    def task_title(self, task_id: str) -> str:
        t = self.tasks.get(task_id)
        return t.title if t else task_id


def names_of(model, people: Sequence[ParsePerson], prefer: Mapping[str, str] | None = None) -> Names:
    """The Names for a Model: its people (as Parse and populate sees them) and its tasks, but discarded ones."""
    return Names(people, [RefTask(t.id, t.title, t.state != "Closed") for t in model.tasks.values() if not t.discarded], prefer)


# ---- reading operators ----
@dataclass(frozen=True)
class Token:
    kind: str  # "type", "person" or "task"
    start: int = 0
    end: int = 0
    typed: str = ""  # the name as written
    item_type: str = ""  # a ** type: task, note, update or decision
    state: str = ""  # a ** state word's state
    id: str | None = None  # the person or task
    name: str = ""  # the person's name (a new person's as written)
    lead: bool = False  # @L.
    none: bool = False  # @__
    size: int = 0

    @property
    def is_new(self) -> bool:
        return self.kind == "person" and not self.id and not self.none

    def who(self) -> Who:
        return Who(self.id, self.name) if self.id else Who(None, self.name)


def _match_name(after: str, entries: list[tuple[str, str]]) -> tuple[str, str] | None:
    low = after.lower()
    for name, ref in entries:
        if low[:len(name)] == name.lower() and not _is_word(after[len(name):len(name) + 1]):
            return after[:len(name)], ref
    return None


def _type(rest: str) -> Token | None:
    m = TYPE_RE.match(rest)
    if not m:
        return None
    kind = {"t": "task", "n": "note", "u": "update"}[m.group(1).lower()] if m.group(1) else "decision" if m.group(2) else "update"
    state = quick_update(m.group(3) + ".").state if m.group(3) else ""
    return Token("type", item_type=kind, state=state, size=m.end())


def _person(rest: str, names: Names) -> Token | None:
    lead = rest[:3].lower() == "@l."
    off = 3 if lead else 1
    after = rest[off:]
    stored = _STORED_PERSON.match(after)
    if stored:
        pid = stored.group(2)
        return Token("person", typed=stored.group(1), id=pid, name=names.person_name(pid) if pid in names.person_by_id else stored.group(1),
                     lead=lead, size=off + stored.end())
    none = re.match(r"_{2,}", after)
    if none:
        return Token("person", none=True, lead=lead, size=off + none.end())
    hit = _match_name(after, [(n.lower(), v) for n, v in names.prefer_people]) or _match_name(after, names.person_names)
    if hit:
        typed, pid = hit
        return Token("person", typed=typed, id=pid, name=names.person_name(pid), lead=lead, size=off + len(typed))
    word = re.match(r"[A-Za-z][A-Za-z'-]*", after)
    return Token("person", typed=word.group(0), name=word.group(0), lead=lead, size=off + word.end()) if word else None


def _task(rest: str, names: Names) -> Token | None:
    after = rest[1:]
    stored = _STORED_TASK.match(after)
    if stored:
        return Token("task", typed=stored.group(1), id=stored.group(2), size=1 + stored.end())
    tid = re.match(r"T\d{6}(?![0-9])", after, re.I)
    if tid and tid.group(0).upper() in names.tasks:
        return Token("task", typed=tid.group(0), id=tid.group(0).upper(), size=1 + tid.end())
    hit = _match_name(after, names.prefer_tasks) or _match_name(after, names.task_names)
    if hit:
        typed, task_id = hit
        return Token("task", typed=typed, id=task_id, size=1 + len(typed))
    return None


def scan(text: str, names: Names) -> list[Token]:
    """The operators in one line's text, in order."""
    out: list[Token] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch not in "@#*" or (i > 0 and not (text[i - 1].isspace() or text[i - 1] == "(")):
            i += 1
            continue
        rest = text[i:]
        tok = _type(rest) if ch == "*" else _person(rest, names) if ch == "@" else _task(rest, names)
        if tok:
            out.append(replace(tok, start=i, end=i + tok.size))
            i += tok.size
        else:
            i += 1
    return out


def clean(text: str, toks: list[Token], names: Names) -> str:
    """A line's text without its operators, for a title or a description. An operator at the start or the end of the
    line goes; one inside a sentence keeps its name, without the @ or # ("Ask @Tom about it" reads "Ask Tom about it")."""
    out, at, named = [], 0, False  # named: a person's operator at the start went, so "to" or "will" after it goes too
    for i, x in enumerate(toks):
        before = text[toks[i - 1].end if i else 0:x.start]
        after = text[x.end:toks[i + 1].start if i + 1 < len(toks) else len(text)]
        leading = all(_SEP.match(text[toks[j - 1].end if j else 0:toks[j].start]) for j in range(i)) and bool(_SEP.match(before))
        trailing = (bool(_TRAIL.match(after))
                    and all(_TRAIL.match(text[toks[j].end:toks[j + 1].start if j + 1 < len(toks) else len(text)]) for j in range(i + 1, len(toks)))
                    and not (x.kind != "type" and _PREP.search(before)))
        out.append(text[at:x.start])
        if x.kind != "type" and not leading and not trailing and not x.none:
            out.append(names.task_title(x.id) if x.kind == "task" else x.typed)  # a task by its title, even when written as its ID
        if x.kind == "person" and leading:
            named = True
        at = x.end
    out.append(text[at:])
    s = re.sub(r"\s+", " ", "".join(out))
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"^[\s,;:&–—-]+", "", s)
    s = re.sub(r"^and\s+", "", s, flags=re.I).strip()
    if named:
        s = _LEAD_IN.sub("", s, count=1)
    return s[:1].upper() + s[1:] if s else ""


# ---- blocks and items ----
@dataclass
class Heading:
    line: int
    tasks: list[str]
    block: int | None = None


@dataclass
class Line:
    n: int
    raw: str
    is_list: bool
    level: int  # -1 for a line that isn't a list item
    off: int  # where its text starts, after any list marker
    text: str
    toks: list[Token]
    block: int | None = None
    heading: Heading | None = None


@dataclass
class Block:
    i: int
    owner: int | None  # the line with its operators; None for the lines under a heading
    lines: list[int]
    parent: int | None
    heading: Heading | None
    is_self: bool = False  # New task's own first line


@dataclass(frozen=True)
class Where:
    """Where an item goes: the capture's task, meeting or new task ("home"), the task item it's listed under ("item"),
    a # task ("task"), or Quick tasks ("quick")."""

    kind: str
    ref: str | None = None


@dataclass
class Item:
    key: str
    block: int
    kind: str  # task, note, update or decision
    text: str  # its block, without the operators of its own line
    raw: str  # its block, as written
    line: int
    lines: list[int]
    heading: bool  # the lines under a heading
    state: str = ""
    assignees: list[Token] = field(default_factory=list)
    leads: list[Token] = field(default_factory=list)
    none: bool = False
    tasks: list[str] = field(default_factory=list)
    parent_item: str | None = None
    parent_self: bool = False
    title: str = ""
    due: str | None = None
    deadline: str | None = None
    deadline_desc: str = ""
    urgent: bool = False
    labels: list[str] = field(default_factory=list)
    lead_hours: str = ""
    assignee_hours: str = ""
    recurrence: str = ""
    reminder: str | None = None
    start: str | None = None
    where: list[Where] = field(default_factory=list)
    on: bool = True
    changed: bool = False
    problem: str = ""


@dataclass
class Reading:
    lines: list[Line]
    blocks: list[Block]
    items: list[Item]
    headings: list[Heading]
    self_block: Block | None


@dataclass
class SelfFields:
    leads: list[Token]
    assignees: list[Token]
    tasks: list[str]
    text: str
    any: bool


def _tasks_of(toks: list[Token]) -> list[str]:
    return list(dict.fromkeys(x.id for x in toks if x.kind == "task" and x.id))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def read(content: str, names: Names, today: date, *, labels: Sequence[ParseLabel] = (), events: Sequence[str] = EVENT_WORDS,
         home: bool = False, new_task: bool = False, overrides: Mapping[str, Mapping[str, object]] | None = None) -> Reading:
    """The content text's lines, blocks and items. ``home``: there's a task the items go under (the picked task, the
    meeting or the new task). ``new_task``: the first line is the new task itself. ``overrides``: the cards' changes,
    by item key ({"off": True, "title": …, "due": …})."""
    lines = []
    for n, raw in enumerate(content.split("\n")):
        m = LIST_RE.match(raw)
        text = raw[m.end():] if m else raw
        lines.append(Line(n, raw, bool(m), len(m.group(1).replace("\t", "  ")) // 2 if m else -1, m.end() if m else 0, text, scan(text, names)))
    blocks: list[Block] = []
    headings: list[Heading] = []
    heading: Heading | None = None
    stack: list[tuple[int, int]] = []  # open list items: (level, block)
    for L in lines:
        if not L.raw.strip():
            stack = []
            continue
        if L.is_list:
            while stack and stack[-1][0] >= L.level:
                stack.pop()
        else:
            stack = []
        parent = blocks[stack[-1][1]] if stack else None
        only_tasks = bool(L.toks) and all(x.kind == "task" for x in L.toks) and not re.sub(r"[:.\s]", "", clean(L.text, L.toks, names))
        if not L.is_list and only_tasks:  # a heading: it covers the lines under it, until the next heading
            heading = Heading(L.n, _tasks_of(L.toks))
            headings.append(heading)
            L.heading = heading
            continue
        b: Block | None = None
        if L.toks:
            b = Block(len(blocks), L.n, [L.n], parent.i if parent else None, None if parent else heading)
            blocks.append(b)
        elif parent:
            b = parent
            b.lines.append(L.n)
        elif heading:
            if heading.block is None:
                heading.block = len(blocks)
                blocks.append(Block(len(blocks), None, [], None, heading))
            b = blocks[heading.block]
            b.lines.append(L.n)
        L.block = b.i if b else None
        if L.is_list and b:  # a plain list item outside any block stays in the notes, and holds nothing under it
            stack.append((L.level, b.i))
    first = next((L for L in lines if L.raw.strip()), None)
    self_block = None
    if new_task and first:
        self_block = blocks[first.block] if first.block is not None else Block(-1, first.n, [first.n], None, None)
        self_block.is_self = True

    def ctx_tasks(b: Block) -> list[str]:
        own = _tasks_of(lines[b.owner].toks) if b.owner is not None else []
        return own or (ctx_tasks(blocks[b.parent]) if b.parent is not None else b.heading.tasks if b.heading else [])

    def text_of(b: Block) -> str:
        base = lines[b.owner].level + 1 if b.owner is not None else 0
        parts = []
        for n in b.lines:
            L = lines[n]
            if n == b.owner:
                parts.append(clean(L.text, L.toks, names))
            else:
                parts.append("  " * max(0, L.level - base) + L.raw.strip() if L.is_list else L.raw.strip())
        return "\n".join(p for p in parts if p)

    items: list[Item] = []
    for b in blocks:
        if b.is_self:
            continue
        toks = lines[b.owner].toks if b.owner is not None else []
        typ = next((x for x in toks if x.kind == "type"), None)
        people = [x for x in toks if x.kind == "person"]
        kind = typ.item_type if typ else "task" if people else "note"
        parent_item = next((x for x in items if x.block == b.parent), None) if b.parent is not None else None
        it = Item(str(len(items)), b.i, kind, text_of(b), "\n".join(lines[n].raw for n in b.lines), b.owner if b.owner is not None else b.lines[0],
                  list(b.lines), b.owner is None, state=typ.state if typ else "", assignees=[x for x in people if not x.lead and not x.none],
                  leads=[x for x in people if x.lead and not x.none], none=any(x.none for x in people), tasks=ctx_tasks(b),
                  parent_item=parent_item.key if parent_item and parent_item.kind == "task" else None,
                  parent_self=b.parent is not None and blocks[b.parent].is_self)
        if kind == "task":
            r = parse_capture(it.text, "new_task", today, names.people, labels, events)
            it.title = r.title or first_sentence(it.text) or "Untitled task"
            it.due, it.deadline, it.deadline_desc, it.urgent = _iso(r.due), _iso(r.deadline), r.deadline_desc, r.urgent
            it.labels, it.lead_hours, it.assignee_hours = list(r.labels), r.lead_hours, r.assignee_hours
            it.recurrence, it.reminder, it.start = r.recurrence, _iso(r.reminder), _iso(r.start)
        else:
            it.title = first_sentence(_MARKER.sub("", it.text)) or (it.state if kind == "update" and it.state else "")
        # Where it goes. A task: under the item it's listed under, else the capture's task (or meeting, or new task),
        # and under each # task; with none, under Quick tasks. A note, update or decision: on each # task, else on the
        # task item it's listed under, else on the capture's task.
        up = [Where("item", it.parent_item)] if it.parent_item else [Where("home")] if it.parent_self or home else []
        if kind == "task":
            it.where = [*up, *(Where("task", t) for t in it.tasks)] or [Where("quick")]
        else:
            it.where = [Where("task", t) for t in it.tasks] if it.tasks else up
        # A card's changes stay, even when the block is edited later.
        ov = (overrides or {}).get(it.key, {})
        it.on = not ov.get("off")
        if ov.get("title") is not None:
            it.title = str(ov["title"])
        if ov.get("due") is not None:
            it.due = str(ov["due"]) or None
        it.changed = ov.get("title") is not None or ov.get("due") is not None
        if kind != "task" and not it.where:
            it.problem = "Needs a #task to update" if kind == "update" else "No task to put it on: it stays in the notes"
        elif kind == "update" and not it.state and not it.text:
            it.problem = "Nothing to update: add a state or some text"
        elif kind == "note" and not it.text:
            it.problem = "Nothing under it yet"
        if it.problem:
            it.on = False
        items.append(it)
    return Reading(lines, blocks, items, headings, self_block)


def self_fields(r: Reading, names: Names) -> SelfFields | None:
    """The new task's own first line: what its operators add to the new task's fields."""
    if not r.self_block or r.self_block.owner is None:
        return None
    L = r.lines[r.self_block.owner]
    people = [x for x in L.toks if x.kind == "person" and not x.none]
    return SelfFields([x for x in people if x.lead], [x for x in people if not x.lead], _tasks_of(L.toks), clean(L.text, L.toks, names), bool(L.toks))


def line_kinds(r: Reading) -> dict[int, str]:
    """Each line's part, for the colours: "task", "note", "update" or "decision" (its item's kind), "self", "heading",
    or "off" (an item that's unticked or can't be made). Lines that stay in the notes aren't listed."""
    out: dict[int, str] = {}
    by_block = {it.block: it for it in r.items}
    for L in r.lines:
        if L.heading:
            out[L.n] = "heading"
        elif L.block is not None:
            b = r.blocks[L.block]
            it = by_block.get(L.block)
            out[L.n] = "self" if b.is_self else ("off" if not it.on else it.kind) if it else ""
    if r.self_block and r.self_block.i == -1:
        out[r.self_block.owner] = "self"
    return {k: v for k, v in out.items() if v}


def parse_text(r: Reading, names: Names) -> str:
    """What Parse and populate reads for the capture's own fields: the lines that aren't items, with the new task's
    own operators taken out (its @ and # fill its fields when it's saved)."""
    item_blocks = {it.block for it in r.items}
    out = []
    for L in r.lines:
        if L.block is not None and L.block in item_blocks or L.heading:
            continue
        if r.self_block and L.n == r.self_block.owner:
            out.append(L.raw[:L.off] + clean(L.text, L.toks, names))
        else:
            out.append(L.raw)
    return "\n".join(out)


def discussed(r: Reading, subject: str | None) -> bool:
    """Whether the notes discussed an agenda item's task: its heading has lines under it, or a ticked item names it."""
    return bool(subject) and (any(subject in h.tasks and h.block is not None for h in r.headings)
                              or any(it.on and subject in it.tasks for it in r.items))


# ---- typing aids: @ and # open a list that narrows as you type ----
@dataclass(frozen=True)
class Typing:
    sigil: str  # "@", "@L." or "#"
    q: str
    start: int  # where the sigil starts, in the text before the cursor


@dataclass(frozen=True)
class Option:
    value: str  # what goes in after the sigil
    label: str
    sub: str = ""
    ref: str | None = None  # the person's or task's ID
    add: bool = False  # a new person


def typing(before: str) -> Typing | None:
    """The @, @L. or # word being typed, from the text before the cursor in its line."""
    m = _TYPING.search(before)
    if not m or len(m.group(2)) > 30:
        return None
    return Typing(m.group(1), m.group(2), len(before) - len(m.group(1)) - len(m.group(2)))


def options(t: Typing, names: Names) -> list[Option]:
    """The list for what's being typed: open tasks for #; people for @ and @L., then @__ and "Add … to people"."""
    q = t.q.lower()

    def hit(ns: Sequence[str]) -> bool:
        return not q or any(any(w.startswith(q) for w in n.lower().split()) or n.lower().startswith(q) for n in ns)

    if t.sigil == "#":
        return [Option(x.title, x.title, ref=x.id) for x in names.tasks.values() if x.open and hit([x.title, x.id])][:8]
    out = [Option(p.name, p.name + (" (me)" if p.me else ""), ", ".join(p.aliases), p.id) for p in names.active if hit([p.name, *p.aliases])][:7]
    if t.sigil == "@" and "__".startswith(q or "_"):
        out.append(Option("__", "@__  no one yet", "A task to assign later"))
    if q and re.fullmatch(r"[a-z][a-z'-]*", q) and not any(n.lower() == q for p in names.people for n in (p.name, *p.aliases)):
        out.append(Option(t.q, f"Add “{t.q}” to people", "Added when you save", add=True))
    return out


# ---- capture.md: each @ and # with its ID ----
def _stored(x: Token, names: Names) -> str | None:
    if x.kind == "person" and x.id:
        return f"@{'L.' if x.lead else ''}[{names.person_name(x.id)}]({x.id})"
    if x.kind == "task" and x.id:
        return f"#[{names.task_title(x.id)}]({x.id})"
    return None


def store(text: str, names: Names, formatted: bool = False) -> str:
    """The content text as capture.md keeps it: each @ and # as its name and ID. ``formatted``: the text is markup, and
    its marks stay as they are around each name."""
    out = []
    for line in text.split("\n"):
        if formatted:
            m = markup.LIST_LINE.match(line)
            head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
            words = "".join(t for t, _, _ in markup._segments(rest))
            spans = [(x.start, x.end, s) for x in scan(words, names) if (s := _stored(x, names))]
            if not spans:
                out.append(line)
            else:
                new = markup.replace_spans(rest, spans)
                out.append(head + new if m else markup.escape_line_start(new))
        else:
            m = LIST_RE.match(line)
            head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
            parts, at = [head], 0
            for x in scan(rest, names):
                parts.append(rest[at:x.start])
                parts.append(_stored(x, names) or rest[x.start:x.end])
                at = x.end
            out.append("".join(parts) + rest[at:])
    return "\n".join(out)


def unstore(text: str) -> str:
    """The content text as it's shown and edited: ``@[Tom Becker](P003)`` reads ``@Tom Becker``."""
    return STORED.sub(lambda m: m.group(1) + m.group(2), text)


def refs_of(text: str) -> dict[str, str]:
    """The names and IDs kept in a capture's text, to keep its links when it's edited: {"@tom becker": "P003", …}."""
    return {("#" if m.group(1) == "#" else "@") + m.group(2).lower(): m.group(3) for m in STORED.finditer(text)}


def words(text: str, names: Names) -> str:
    """The content text without its operators, for a capture's title."""
    out = []
    for line in text.split("\n"):
        m = LIST_RE.match(line)
        head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
        toks = scan(rest, names)
        out.append(head + clean(rest, toks, names) if toks else line)
    return "\n".join(out)
