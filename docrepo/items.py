"""Items from operators (mods log round 2, M0048 phase 2, M0049, M0052, with M0023; release 5.8).

In any capture, a block of the content text with an operator becomes an item: a task, a note, an update or a
decision. A block is a line, with the list items under it that have no operator of their own; a list item under it
with an operator is a block of its own, inside it. Operators are read from the content text's words (never from an
added email), and only after a space, a "(" or the start of a line, so an address such as tom@example.com stays text.

- ``@Tom``, ``@Tom Becker``: a task, with Tom an assignee (several allowed). ``@L.Tom``: a task, with Tom its lead.
  ``@__``: a task with no one yet.
- ``#Rigging plan``, ``#T000012``: a link to that task, as a parent. With no ``@`` or ``**``, the block is a note on
  it. On a line of its own (a heading), it covers the lines under it, until the next heading. With no task picked, one
  ``#`` task fills the task picker, and several split a note into a capture per task (release 5.32: ``named_tasks``,
  ``sections``); a note naming only the capture's own task makes no item (``own``).
- ``**name,``, then the rest: a name from ``OPERATORS`` (release 5.38, round 5's item 67, decisions 200 to 209). Either it
  says what a line is, and takes its whole line and the list items under it (decision 203):
  ``**t,`` or ``**task,``, ``**n,`` or ``**note,``: a task, or a note, said outright. ``**closed,``, ``**done,``,
  ``**parked,``, ``**in progress,``, ``**started,``: an update to the ``#`` task with that state; the rest is its current
  status. ``**u,`` or ``**update,``: an update with no state change. ``**decision,``: a decision, on the ``#`` task, else
  on the capture's task or meeting. ``**event,``: a task with Plant event ticked (release 5.9, decision 22):
  ``**event, Spring outage, 3 to 14 Nov.`` With nothing to say, these need no comma: ``#Rigging plan **closed.``
- Or it fills a parameter, from one sentence up to its period or the line's end (decision 204): ``**due, 5 Nov.``,
  ``**lead, Tom.``, ``**key date, trial window from 1 Nov to 5 Nov 2027, plant activity.`` (``read_key_date``), or a
  reference field by the name Settings gives it. A filled field on an existing task stays, and a list adds (decision
  200). It goes on the nearest of: a ``#`` task in its sentence, the task item on its line, a ``#`` task on its line, the
  task item it's listed under, the new task it's listed under, a ``#`` above, the capture's task (decision 208).

A ``**`` kind wins; else an ``@`` makes a task; else a ``#`` alone makes a note; a block with none stays in the notes.
Parameters make their own cards beside whatever the rest of their line makes. ``**`` and a space is never an operator, and
``#`` is a link only when it names a task, so "Pump #3" stays text. A name not in the table, and an old form such as
``**Closed. Mike confirmed``, make a card that can't be ticked, saying what to write (decisions 205 and 206).

capture.md keeps each ``@`` and ``#`` with its ID (M0049): ``@[Tom Becker](P003)``, ``@L.[Priya Shah](P002)``,
``#[Rigging plan](T000012)``, so renaming a person or a task never breaks it (``store``, ``unstore``).

Ported from the mockup's ``items.js``; decisions 37 to 52 of the round 2 plan, and 200 to 209 of round 5's quick input plan.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from docrepo import markup
from docrepo.db import RECURRENCES
from docrepo.model import PRIORITY_NAMES
from docrepo.parse import (
    EVENT_WORDS, REF_SUFFIX, DateHit, ParseLabel, ParsePerson, Who, find_dates, find_hours, ok_day, one_decimal, parse_capture, quick_update,
)
from docrepo.text import first_sentence, sentences

KIND_NAMES = {"task": "Task", "note": "Note", "update": "Update", "decision": "Decision", "date": "Key date", "param": "Field"}
#: The kinds of item a parameter makes: they go on a task, with no capture of their own.
PARAM_KINDS = ("date", "param")
_NAME = re.compile(r"\*\*([A-Za-z][^,*\n]{0,40}),")
_UNKNOWN_NAME = re.compile(r"[a-z0-9][a-z0-9 '#&/-]*")
_NEXT_STAR = re.compile(r"(?:^|\s)\*\*[A-Za-z]")
# A key date's ticks and the words before its date (release 5.31).
_KD_PLANT = re.compile(r"\b(?:major\s+)?plant\s+(?:activity|event)\b", re.I)
_KD_DEADLINE = re.compile(r"\b(?:hard\s+)?deadline\b", re.I)
_KD_WORD = re.compile(r"\b(from|starting|starts?|by|due|until|till|before|ends?|on)\s*\Z", re.I)
_KD_FROM = re.compile(r"(?:from|starting|starts?)\Z", re.I)
_KD_BY = re.compile(r"(?:by|due|until|till|before|ends?)\Z", re.I)
_KD_JOIN = re.compile(r"\s*\.?\s*(?:-|–|—|to|until|till|through|thru)\s*", re.I)
_YEAR_TYPED = re.compile(r"\b\d{4}\b|\d/\d{2}\b")
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

    def __init__(self, people: Sequence[ParsePerson], tasks: Sequence[RefTask], prefer: Mapping[str, str] | None = None,
                 fields: Sequence[str] = (), records: Mapping[str, Any] | None = None, labels: Sequence[str] = ()) -> None:
        self.field_ops = {key: op for op in map(_field_op, fields) for key in op.names}  # the reference fields, named in Settings
        self.records = records or {}  # the tasks themselves, for what a field already holds
        self.labels = list(labels)
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


def names_of(model, people: Sequence[ParsePerson], prefer: Mapping[str, str] | None = None, fields: Sequence[str] = ()) -> Names:
    """The Names for a Model: its people (as Parse and populate sees them) and its tasks, but discarded ones; ``fields``
    are the reference fields Settings names."""
    return Names(people, [RefTask(t.id, t.title, t.state != "Closed") for t in model.tasks.values() if not t.discarded], prefer, fields,
                 model.tasks, [x.name for x in model.labels])


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
    event: bool = False  # **event,: a task that's a plant event
    size: int = 0
    # A parameter: its entry in the table (none for a name it can't take), what its card says, its sentence and where that
    # ends, and what stops it. ``inside``: an @ or # inside a parameter's sentence, which is the sentence's own.
    op: Operator | None = None
    label: str = ""
    sentence: str = ""
    until: int = 0
    problem: str = ""
    inside: bool = False

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


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _value_token(rest: str, head: int, *, op: Operator | None = None, label: str, problem: str = "", sentenced: bool = True) -> Token:
    """A parameter's token: what its value is read from runs up to the next ** word, and a value is one sentence, up to its
    end by ``text.sentences`` or the line's (decision 204). ``sentenced`` False takes all of it: an old form's words."""
    after = rest[head:]
    cut = _NEXT_STAR.search(after)
    held = after[:cut.start()] if cut else after
    if not sentenced:
        return Token("param", op=op, label=label, problem=problem, size=head, until=head + len(held), sentence=re.sub(r"^[.:]\s*", "", held).strip())
    found = sentences(held)
    first = found[0] if found else None
    return Token("param", op=op, label=label, problem=problem, size=head, until=head + (first.end if first else 0),
                 sentence=re.sub(r"[.!?]+\Z", "", first.text).strip() if first else "")


def _kind_token(op: Operator, size: int) -> Token:
    return Token("type", item_type=op.item, state=op.state, event=op.event, size=size)


def _nothing_after(after: str, names: Names) -> bool:
    """Whether a kind has nothing to say: the line's end, or only # tasks and other operators."""
    t = re.sub(r"^[.:]", "", after)
    return not re.sub(r"[\s.:;,]", "", clean(t, scan(t, names), names))


def _star(rest: str, names: Names) -> Token | None:
    """A ** at the start of ``rest``: a name from the table and its comma; a kind with nothing to say; or a name written
    the old way, or not in the table, which makes a card saying so (decisions 205 and 206)."""
    m = _NAME.match(rest)
    if m:
        name = _norm(m.group(1))
        op = _op_of(name, names)
        label = f"**{name}"
        if op and op.item:
            return _kind_token(op, m.end())
        if op and op.gone:
            return _value_token(rest, m.end(), label=label, problem=op.gone)
        if op:
            return _value_token(rest, m.end(), op=op, label=op.label)
        if _UNKNOWN_NAME.fullmatch(name) and len(name.split(" ")) <= 4:
            return _value_token(rest, m.end(), label=label, problem=f"No field called {name}")
    bare = next((n for n in _names_longest(names) if rest[2:2 + len(n)].lower() == n and not _is_word(rest[2 + len(n):3 + len(n)])
                 and rest[2 + len(n):3 + len(n)] != "*"), None)
    if not bare:
        return None
    op = _op_of(bare, names)
    head = 2 + len(bare)
    after = rest[head:]
    mark = 1 if after[:1] in (".", ":") else 0
    if op.item and _nothing_after(after, names):
        return _kind_token(op, head + mark)
    return _value_token(rest, head + mark, label=f"**{bare}", problem=op.gone or f"Now written **{bare}, then your sentence", sentenced=False)


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
    """The operators in one line's text, in order. A parameter's ``end`` is its name and comma's and its ``until`` its
    sentence's; the @ and # inside that sentence are marked ``inside``, except that a parent's sentence is all value."""
    out: list[Token] = []
    i = held = 0
    while i < len(text):
        ch = text[i]
        if ch not in "@#*" or (i > 0 and not (text[i - 1].isspace() or text[i - 1] == "(")):
            i += 1
            continue
        rest = text[i:]
        tok = _star(rest, names) if ch == "*" else _person(rest, names) if ch == "@" else _task(rest, names)
        if not tok:
            i += 1
            continue
        until = i + tok.until if tok.kind == "param" else 0
        out.append(replace(tok, start=i, end=i + tok.size, until=until, inside=i < held))
        if tok.kind == "param":
            held = until
            if tok.op and tok.op.whole:
                i = max(until, i + tok.size)
                continue
        i += tok.size
    return out


def clean(text: str, toks: list[Token], names: Names) -> str:
    """A line's text without its operators, for a title or a description. An operator at the start or the end of the
    line goes; one inside a sentence keeps its name, without the @ or # ("Ask @Tom about it" reads "Ask Tom about it"). A
    parameter goes with its sentence."""
    if any(x.kind == "param" for x in toks):
        left, at = [], 0
        for x in toks:
            if x.kind == "param":
                left.append(text[at:x.start])
                at = x.until
        text = "".join(left) + text[at:]
        toks = [x for x in scan(text, names) if x.kind != "param"]
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
    if not re.search(r"[^\s.,;:!?&–—-]", s):
        return ""
    return s[:1].upper() + s[1:] if s else ""


# ---- a key date's sentence (release 5.31, the key dates plan, item 60; decision 209) ----
@dataclass(frozen=True)
class KeyDateText:
    """What a key date's sentence says: its dates (YYYY-MM-DD, or None), description, ticks, and what stops it, if anything."""

    start: str | None
    end: str | None
    description: str
    plant: bool = False
    deadline: bool = False
    problem: str = ""


def _window_start(a: DateHit, b: DateHit) -> date:
    """A window's start takes its end's year when only the end has one: "1 Nov to 5 Nov 2027", "28 Dec to 3 Jan 2028"."""
    if not _YEAR_TYPED.search(b.text) or _YEAR_TYPED.search(a.text):
        return a.date

    def on(year: int) -> date | None:
        return date(year, a.date.month, a.date.day) if ok_day(year, a.date.month - 1, a.date.day) else None

    same = on(b.date.year)
    return same if same and same <= b.date else on(b.date.year - 1) or a.date


def read_key_date(text: str, today: date) -> KeyDateText:
    """A ``**key date,`` sentence as a key date: its first date phrase, read with Parse and populate's
    date rules ("from" makes it a start, "by" or "due" an end, a range or two dates joined by "to" or a dash a window, "on"
    or a bare date one day); "plant activity" (or "plant event") and "deadline" as its ticks; the rest its description.
    Ported from the mockup's ``keyDate``."""
    plant, deadline = bool(_KD_PLANT.search(text)), bool(_KD_DEADLINE.search(text))
    hits = find_dates(text, today)
    start = end = None
    problem = ""
    rest = text
    if hits:
        h = hits[0]
        w = _KD_WORD.search(text[:h.start])
        nxt = hits[1] if len(hits) > 1 else None
        joined = bool(nxt and _KD_JOIN.fullmatch(text[h.end:nxt.start]))
        stop = nxt.end if joined and nxt else h.end
        cut_from, cut_to = (h.start - len(w.group(0))) if w else h.start, stop + (text[stop:stop + 1] == ".")
        if h.from_:
            start, end = h.from_.isoformat(), h.date.isoformat()
        elif joined and nxt:
            start, end = _window_start(h, nxt).isoformat(), nxt.date.isoformat()
        elif w and _KD_FROM.match(w.group(1)):
            start = h.date.isoformat()
        elif w and _KD_BY.match(w.group(1)):
            end = h.date.isoformat()
        else:
            start = end = h.date.isoformat()
        if start and end and end < start:
            problem = "Its end is before its start"
        rest = text[:cut_from] + " " + text[cut_to:]
    else:
        problem = "No date: add one, such as by 25 Nov"
    rest = _KD_DEADLINE.sub(" ", _KD_PLANT.sub(" ", rest))
    rest = re.sub(r"\s+", " ", rest)
    rest = re.sub(r"\s+([,.;:!?])", r"\1", rest)
    rest = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", rest)
    rest = re.sub(r"^[\s,;:.–—-]+", "", rest)
    rest = re.sub(r"[\s,;:–—-]+\Z", "", rest).strip()
    return KeyDateText(start, end, rest[:1].upper() + rest[1:], plant, deadline, problem)


def key_date_text(kd: KeyDateText) -> str:
    """A key date in words, as the test vectors list it: ``Start 2026-12-01. End 2026-12-05. Description "…". Plant
    activity.``"""
    parts = [kd.start and f"Start {kd.start}", kd.end and f"End {kd.end}", kd.description and f'Description "{kd.description}"',
             kd.plant and "Plant activity", kd.deadline and "Deadline", kd.problem]
    return ". ".join(p for p in parts if p) + "."


# ---- reading a parameter's sentence ----
@dataclass(frozen=True)
class Value:
    """What a parameter's sentence says: the changes it makes (``tasks.update_task``'s names, with "parents" and "priority"
    beside them), how it reads, and what stops it, if anything."""

    changes: Mapping[str, Any] = field(default_factory=dict)
    shown: str = ""
    problem: str = ""
    key_date: KeyDateText | None = None


@dataclass(frozen=True)
class ReadWith:
    today: date
    names: Names
    events: Sequence[str] = EVENT_WORDS


_NOTHING = Value(problem="Nothing after the comma")
_NO_DATE = Value(problem="No date: add one, such as 25 Nov")
_CHUNK = re.compile(r"\s*(?:,|;|&|\band\b)\s*", re.I)


def _chunks(x: str) -> list[str]:
    return [c.strip() for c in _CHUNK.split(x) if c.strip()]


def _read_date(x: str, c: ReadWith, op: Operator) -> Value:
    hits = find_dates(x, c.today)
    return Value({op.task_field: hits[0].date.isoformat()}, hits[0].date.isoformat()) if hits else _NO_DATE if x else _NOTHING


def _read_start(x: str, c: ReadWith, op: Operator) -> Value:
    hits = find_dates(x, c.today)
    if not hits:
        return _NO_DATE if x else _NOTHING
    day = (hits[0].from_ or hits[0].date).isoformat()
    return Value({op.task_field: day}, day)


def _read_deadline(x: str, c: ReadWith, op: Operator) -> Value:
    k = read_key_date(x, c.today)
    day = k.end or k.start
    if not day:
        return _NO_DATE if x else _NOTHING
    return Value({op.task_field: day, **({"deadline_desc": k.description} if k.description else {})}, day + (f": {k.description}" if k.description else ""))


def _read_key_date(x: str, c: ReadWith, op: Operator) -> Value:
    if not x:
        return _NOTHING
    kd = read_key_date(clean(x, scan(x, c.names), c.names), c.today)
    return Value(problem=kd.problem, key_date=kd)


def _read_text(x: str, c: ReadWith, op: Operator) -> Value:
    t = clean(x, scan(x, c.names), c.names)
    return Value({op.task_field: t}, t) if t else _NOTHING


def _read_people(x: str, c: ReadWith, op: Operator) -> Value:
    who, shown = [], []
    known = [(n.lower(), v) for n, v in (*c.names.prefer_people, *c.names.person_names)]
    for chunk in _chunks(x):
        after = re.sub(r"^@(?:L\.)?", "", chunk, flags=re.I)
        low = after.lower()
        pid = next((p.id for p in c.names.active if p.me), None) if low in ("me", "i") else next((v for n, v in known if n == low), None)
        if pid:
            who.append(Who(pid, c.names.person_name(pid)))
            shown.append(c.names.person_name(pid))
        elif re.fullmatch(r"[A-Za-z][A-Za-z'-]*(?: [A-Za-z][A-Za-z'-]*)?", after):
            who.append(Who(None, after))
            shown.append(f"{after} (new)")
        else:
            return Value(problem=f"Can't read a name in: {chunk}")
    return Value({op.task_field: who}, ", ".join(shown)) if who else _NOTHING


def _read_hours(x: str, c: ReadWith, op: Operator) -> Value:
    if re.fullmatch(r"\d+(?:\.\d+)?|\.\d+", x):
        return Value({op.task_field: float(x)}, one_decimal(float(x)))
    if not x:
        return _NOTHING
    hits = find_hours(x)
    if not hits:
        return Value(problem="No hours: add a number, such as 12")
    if hits[0].per:
        return Value(problem="Give a total, such as 12 hours")
    return Value({op.task_field: hits[0].hours}, one_decimal(hits[0].hours))


def _read_state(x: str, c: ReadWith, op: Operator) -> Value:
    q = quick_update(x + ".")
    return Value({op.task_field: q.state}, q.state) if q and not q.rest else Value(problem="Say Not started, In progress, Parked or Closed")


def _read_priority(x: str, c: ReadWith, op: Operator) -> Value:
    low = _norm(x)
    key = next((k for k, name in PRIORITY_NAMES.items() if low in (k, name.lower())), None)
    return Value({op.task_field: key}, PRIORITY_NAMES[key]) if key else Value(problem="Say Critical, High, Medium or Parking lot")


def _read_recurrence(x: str, c: ReadWith, op: Operator) -> Value:
    low = _norm(x)
    hit = next((r for r in RECURRENCES if r.lower() == low), "") or (parse_capture(x, "new_task", c.today, (), (), c.events).recurrence if x else "")
    return Value({op.task_field: hit}, hit) if hit else Value(problem="Say Daily, Weekly, Bi-weekly, Monthly, Quarterly or Yearly")


def _read_yes_no(x: str, c: ReadWith, op: Operator) -> Value:
    if re.fullmatch(r"y(?:es)?", x, re.I):
        return Value({op.task_field: True}, "Yes")
    if re.fullmatch(r"no?", x, re.I):
        return Value({op.task_field: False}, "No")
    return Value(problem="Say yes or no")


def _read_labels(x: str, c: ReadWith, op: Operator) -> Value:
    known = {n.lower(): n for n in c.names.labels}
    chunks = _chunks(x)
    return (Value({op.task_field: [known.get(k.lower(), k) for k in chunks]}, ", ".join(known.get(k.lower(), f"{k} (new)") for k in chunks))
            if chunks else _NOTHING)


def _read_parents(x: str, c: ReadWith, op: Operator) -> Value:
    def found(chunk: str) -> str | None:
        low = chunk.removeprefix("#").strip().lower()
        if re.fullmatch(r"t\d{6}", low) and low.upper() in c.names.tasks:
            return low.upper()
        return next((v for n, v in c.names.task_names if n.lower() == low), None)

    whole = found(x)
    if whole:
        return Value({op.task_field: [whole]}, c.names.task_title(whole))
    chunks = _chunks(x)
    miss = next((k for k in chunks if not found(k)), None)
    if not chunks:
        return _NOTHING
    if miss:
        return Value(problem=f"No task called {miss.removeprefix('#')}")
    ids = [found(k) for k in chunks]
    return Value({op.task_field: ids}, ", ".join(c.names.task_title(i) for i in ids))


def _read_reference(x: str, c: ReadWith, op: Operator) -> Value:
    v = re.sub(r"^(?:#|no\.?(?=\s|\d|\Z)|number)\s*[:#-]?\s*", "", x, flags=re.I).strip()
    return Value({"references": {op.label: v}}, v) if v else _NOTHING


# ---- the ** names: one entry each (decisions 202, 206 and 207) ----
@dataclass(frozen=True)
class Operator:
    """A ** name. A kind says what a line is: ``item``, with an update's ``state`` or an event's tick. A parameter has its
    card's ``label``, how its sentence is read, and the task's field: a filled field stays (decision 200), and ``adds``
    marks a list, which never fills. ``whole``: its sentence is all value, so a # in it is no link. ``gone``: no longer an
    operator, and what to say instead (decision 206). A new parameter that's a field ``tasks.update_task`` knows needs
    only an entry here, and its match in the mockup's ``items.js``."""

    names: tuple[str, ...]
    item: str = ""
    state: str = ""
    event: bool = False
    label: str = ""
    task_field: str = ""
    read: Callable[[str, ReadWith, Operator], Value] | None = None
    kind: str = "param"
    adds: bool = False
    whole: bool = False
    gone: str = ""
    reference: bool = False  # a reference field, whose label is its name in Settings


OPERATORS: tuple[Operator, ...] = (
    Operator(("t", "task"), item="task"),
    Operator(("n", "note"), item="note"),
    Operator(("u", "update"), item="update"),
    Operator(("decision",), item="decision"),
    Operator(("event",), item="task", event=True),
    Operator(("closed", "done", "complete", "completed", "finished"), item="update", state="Closed"),
    Operator(("in progress", "started", "under way", "underway", "reopened", "re-opened"), item="update", state="In progress"),
    Operator(("parked", "on hold"), item="update", state="Parked"),
    Operator(("not started",), item="update", state="Not started"),
    Operator(("start", "start date"), label="Start", task_field="start", read=_read_start),
    Operator(("due", "due date"), label="Due", task_field="due", read=_read_date),
    Operator(("deadline",), label="Deadline", task_field="deadline", read=_read_deadline),
    Operator(("deadline description",), label="Deadline description", task_field="deadline_desc", read=_read_text),
    Operator(("reminder", "remind"), label="Reminder", task_field="reminder", read=_read_date),
    Operator(("repeat until",), label="Repeat until", task_field="repeat_until", read=_read_date),
    Operator(("key date", "keydate"), label="Key date", kind="date", adds=True, read=_read_key_date),
    Operator(("lead", "leads"), label="Lead", task_field="leads", adds=True, read=_read_people),
    Operator(("assignee", "assignees"), label="Assignees", task_field="assignees", adds=True, read=_read_people),
    Operator(("lead hours",), label="Lead hours", task_field="lead_hours", read=_read_hours),
    Operator(("assignee hours", "hours"), label="Assignee hours", task_field="assignee_hours", read=_read_hours),
    Operator(("title",), label="Title", task_field="title", read=_read_text),
    Operator(("description",), label="Description", task_field="description", read=_read_text),
    Operator(("status", "current status"), label="Current status", task_field="current_status", read=_read_text),
    Operator(("state",), label="State", task_field="state", read=_read_state),
    Operator(("priority",), label="Priority", task_field="priority", read=_read_priority),
    Operator(("recurrence", "repeat"), label="Recurrence", task_field="recurrence", read=_read_recurrence),
    Operator(("urgent",), label="Urgent", task_field="urgent", read=_read_yes_no),
    Operator(("plant event",), label="Plant event", task_field="plant_event", read=_read_yes_no),
    Operator(("meeting",), label="Meeting", task_field="meeting", read=_read_yes_no),
    Operator(("label", "labels"), label="Labels", task_field="labels", adds=True, read=_read_labels),
    Operator(("parent", "parents"), label="Parents", task_field="parents", adds=True, whole=True, read=_read_parents),
    # An old form still in the hands (decision 206): this entry comes out once the habit has gone.
    Operator(("date",), gone="Say which date: **start, **due, **deadline or **key date"),
)
_BY_NAME = {name: op for op in OPERATORS for name in op.names}


def _field_op(name: str) -> Operator:
    """A reference field's entry: named in Settings, with or without its "#" or "no."."""
    return Operator(tuple(dict.fromkeys((_norm(name), _norm(REF_SUFFIX.sub("", name))))), label=name, read=_read_reference, reference=True)


def _op_of(name: str, names: Names) -> Operator | None:
    return _BY_NAME.get(name) or names.field_ops.get(name)


def _names_longest(names: Names) -> list[str]:
    return sorted((*_BY_NAME, *names.field_ops), key=lambda n: -len(n))


def value_now(task: Any, op: Operator) -> str:
    """What a task already has in a parameter's field, in words, or "" when it's empty (decision 200)."""
    v = task.references.get(op.label, "") if op.reference else getattr(task, op.task_field, None)
    if op.adds or v is None or v is False or v == "" or (op.task_field == "state" and v == "Not started"):
        return ""
    if v is True:
        return "Yes"
    if op.task_field == "priority":
        return PRIORITY_NAMES.get(v, v)
    return one_decimal(v) if isinstance(v, float) else str(v)


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
    plant_event: bool = False  # made by **event, (release 5.9)
    key_date: KeyDateText | None = None  # made by **key date, (release 5.31)
    # A parameter (release 5.38): what its card is called, its entry in the table, and what its sentence says.
    label: str = ""
    op: Operator | None = None
    value: Value | None = None
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
    plant_event: bool = False  # **event, on the new task's own line (mods log round 3, M0059)


def _tasks_of(toks: list[Token]) -> list[str]:
    return list(dict.fromkeys(x.id for x in toks if x.kind == "task" and x.id))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def read(content: str, names: Names, today: date, *, labels: Sequence[ParseLabel] = (), events: Sequence[str] = EVENT_WORDS,
         home: bool = False, new_task: bool = False, overrides: Mapping[str, Mapping[str, object]] | None = None,
         own: str | None = None) -> Reading:
    """The content text's lines, blocks and items. ``home``: there's a task the items go under (the picked task, the
    meeting or the new task). ``new_task``: the first line is the new task itself. ``overrides``: the cards' changes,
    by item key ({"off": True, "title": …, "due": …}). ``own``: the capture's own task, a note's or an update's picked
    task: a note naming only it makes no item, since its lines are already the capture's note on it (the knowledge
    base's decision 28, release 5.32)."""
    lines = []
    for n, raw in enumerate(content.split("\n")):
        m = LIST_RE.match(raw)
        text = raw[m.end():] if m else raw
        toks = scan(text, names)
        if m and markup.CHECK.match(text):  # a checklist line (decision 87): its @ names stay names; it never makes a task
            toks = [x for x in toks if x.kind == "task"]
        lines.append(Line(n, raw, bool(m), len(m.group(1).replace("\t", "  ")) // 2 if m else -1, m.end() if m else 0, text, toks))
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
    first = next((L for L in lines if L.raw.strip() and not (any(x.kind == "param" for x in L.toks) and not clean(L.text, L.toks, names))), None)
    self_block = None
    if new_task and first:
        self_block = blocks[first.block] if first.block is not None else Block(-1, first.n, [first.n], None, None)
        self_block.is_self = True

    def ctx_tasks(b: Block) -> list[str]:
        own = _tasks_of([x for x in lines[b.owner].toks if not x.inside]) if b.owner is not None else []
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

    reading_with = ReadWith(today, names, events)
    home_task = None if new_task else own

    def param_item(p: Token, b: Block, mine: Item | None, parent_item: Item | None) -> Item:
        """A parameter's card (decision 208): nearest first, a # in its sentence, the task item on its line, a # on its
        line, the task item it's listed under, the new task it's listed under, a # above, the capture's task."""
        L = lines[b.owner]
        up_block = blocks[b.parent] if b.parent is not None else None
        inner = _tasks_of([x for x in L.toks if x.inside and p.start <= x.start < p.until])
        on_line = _tasks_of([x for x in L.toks if not x.inside])
        above = ctx_tasks(b)
        if inner:
            where = [Where("task", t) for t in inner]
        elif mine and mine.kind == "task":
            where = [Where("item", mine.key)]
        elif not b.is_self and on_line:
            where = [Where("task", t) for t in on_line]
        elif parent_item and parent_item.kind == "task":
            where = [Where("item", parent_item.key)]
        elif b.is_self or (up_block and up_block.is_self):
            where = [Where("home")]
        else:
            where = [Where("task", t) for t in above] if above else [Where("home")] if home else []
        op = p.op
        v = Value() if p.problem else op.read(p.sentence, reading_with, op)
        it = Item(str(len(items)), b.i, op.kind if op else "param", p.sentence, L.raw, b.owner, [b.owner], False, tasks=inner or above, where=where,
                  label=p.label, op=op, value=v, key_date=v.key_date)
        it.title = (v.key_date.description or KIND_NAMES["date"]) if v.key_date else v.shown or p.sentence
        ov = (overrides or {}).get(it.key, {})
        it.on = not ov.get("off")
        if v.key_date and ov.get("title") is not None:
            it.title, it.changed = str(ov["title"]), True
        ids = [w.ref if w.kind == "task" else home_task if w.kind == "home" else None for w in where]
        filled = [value_now(names.records[i], op) if i in names.records else "" for i in ids] if op and not p.problem and not v.problem else []
        it.problem = (p.problem or v.problem or ("" if where else "No task to put it on: it stays in the notes")
                      or (f"{p.label} is already {filled[0]}: change it with Update or Edit task" if filled and all(filled) else ""))
        if it.problem:
            it.on = False
        return it

    items: list[Item] = []
    for b in blocks:
        all_toks = lines[b.owner].toks if b.owner is not None else []
        params = [x for x in all_toks if x.kind == "param"]
        toks = [x for x in all_toks if x.kind != "param" and not x.inside]
        typ = next((x for x in toks if x.kind == "type"), None)
        people = [x for x in toks if x.kind == "person"]
        parent_item = next((x for x in items if x.block == b.parent), None) if b.parent is not None else None
        text = text_of(b)
        mine = None
        # A line of parameters makes only their cards, unless the rest of it says more.
        if not b.is_self and (not params or typ or people or (toks and text)):
            kind = typ.item_type if typ else "task" if people else "note"
            it = Item(str(len(items)), b.i, kind, text, "\n".join(lines[n].raw for n in b.lines), b.owner if b.owner is not None else b.lines[0],
                      list(b.lines), b.owner is None, state=typ.state if typ else "", assignees=[x for x in people if not x.lead and not x.none],
                      leads=[x for x in people if x.lead and not x.none], none=any(x.none for x in people), tasks=ctx_tasks(b),
                      parent_item=parent_item.key if parent_item and parent_item.kind == "task" else None,
                      parent_self=b.parent is not None and blocks[b.parent].is_self, plant_event=bool(typ and typ.event))
            if kind == "task":
                r = parse_capture(it.text, "new_task", today, names.people, labels, events)
                it.title = r.title or first_sentence(it.text) or "Untitled task"
                it.due, it.deadline, it.deadline_desc, it.urgent = _iso(r.due), _iso(r.deadline), r.deadline_desc, r.urgent
                it.labels, it.lead_hours, it.assignee_hours = list(r.labels), r.lead_hours, r.assignee_hours
                it.recurrence, it.reminder, it.start = r.recurrence, _iso(r.reminder), _iso(r.start)
                it.plant_event = it.plant_event or r.plant_event  # "plant event" in its block, as for the new task (M0059)
                # A plant event runs from its Start to its Due: the end date its own name made a Deadline ("Spring outage,
                # 3 to 14 Nov") is its Due.
                if it.plant_event and it.deadline and not it.due:
                    it.due, it.deadline, it.deadline_desc = it.deadline, None, ""
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
            # A note naming only the capture's own task is its own note, with no item of its own.
            if kind == "note" and own and it.tasks:
                it.where = [w for w in it.where if w.ref != own]
            if not (kind == "note" and own and it.tasks and not it.where):
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
                mine = it
        for p in params:
            items.append(param_item(p, b, mine, parent_item))
    return Reading(lines, blocks, items, headings, self_block)


def self_fields(r: Reading, names: Names) -> SelfFields | None:
    """The new task's own first line: what its operators add to the new task's fields."""
    if not r.self_block or r.self_block.owner is None:
        return None
    L = r.lines[r.self_block.owner]
    people = [x for x in L.toks if x.kind == "person" and not x.none and not x.inside]
    return SelfFields([x for x in people if x.lead], [x for x in people if not x.lead], _tasks_of([x for x in L.toks if not x.inside]), clean(L.text, L.toks, names), bool(L.toks),
                      any(x.kind == "type" and x.event for x in L.toks))


def line_kinds(r: Reading) -> dict[int, str]:
    """Each line's part, for the colours: "task", "note", "update" or "decision" (its item's kind), "date" or "param" (a
    parameter's own line), "self", "heading", or "off" (an item that's unticked or can't be made). Lines that stay in the
    notes aren't listed."""
    out: dict[int, str] = {}
    by_block: dict[int, Item] = {}
    for it in r.items:
        by_block.setdefault(it.block, it)
    for L in r.lines:
        if L.heading:
            out[L.n] = "heading"
        elif L.block is not None:
            b = r.blocks[L.block]
            it = by_block.get(L.block)
            out[L.n] = "self" if b.is_self else ("off" if not it.on else it.kind) if it and L.n in it.lines else ""
    if r.self_block and r.self_block.i == -1:
        out[r.self_block.owner] = "self"
    return {k: v for k, v in out.items() if v}


def parse_text(r: Reading, names: Names) -> str:
    """What Parse and populate reads for the capture's own fields: the lines that aren't items, with the new task's
    own operators taken out (its @ and # fill its fields when it's saved)."""
    item_blocks = {it.block for it in r.items if it.kind not in PARAM_KINDS}
    out = []
    for L in r.lines:
        if L.block is not None and L.block in item_blocks or L.heading:
            continue
        if r.self_block and L.n == r.self_block.owner:
            out.append(L.raw[:L.off] + clean(L.text, L.toks, names))
        elif any(x.kind == "param" for x in L.toks):  # a parameter's sentence is its own; the rest of its line isn't
            words_left = clean(L.text, L.toks, names)
            if words_left:
                out.append(L.raw[:L.off] + words_left)
        else:
            out.append(L.raw)
    return "\n".join(out)


# ---- # choosing the task (the knowledge base's phase 0, decisions 28 to 30; release 5.32) ----
@dataclass
class Section:
    """A task's part of the content text, when several # tasks split a note (decision 29): a # heading with the lines
    under it, or a note whose own line names a # task, outside any heading. ``task`` is the first task it names; the
    parts of one task are joined, in the order written."""

    task: str
    lines: list[int]


def named_tasks(r: Reading) -> list[str]:
    """The tasks the content text names with #, on a heading or on a line, each once, in the order they first appear.
    One fills the task picker (decision 28); two or more split a note (decision 29)."""
    return list(dict.fromkeys(x.id for L in r.lines for x in L.toks if x.kind == "task" and x.id))


def sections(r: Reading) -> tuple[list[Section], list[int]]:
    """The content text by # task (decision 29): each task's section, and the lines under no # task. A line under a
    heading is its heading's first task's; before the first heading, a note block naming a # task (with the list items
    under it) is that task's, and anything else is under no task."""
    by_block = {it.block: it for it in r.items if it.kind not in PARAM_KINDS}
    parts: dict[str, Section] = {}
    rest: list[int] = []
    heading: Heading | None = None
    for L in r.lines:
        heading = L.heading or heading
        task = heading.tasks[0] if heading and heading.tasks else None
        if task is None and L.block is not None:
            b = r.blocks[L.block]
            while b.parent is not None:
                b = r.blocks[b.parent]
            it = by_block.get(b.i)
            if it and it.on and it.kind == "note" and it.tasks:
                task = it.tasks[0]
        if task:
            parts.setdefault(task, Section(task, [])).lines.append(L.n)
        else:
            rest.append(L.n)
    return list(parts.values()), rest


def section_at(r: Reading, line: int) -> str | None:
    """The task whose section holds ``line`` (the text cursor's): where a file added there goes in a split (decision 30)."""
    return next((s.task for s in sections(r)[0] if line in s.lines), None)


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
        h = markup.heading_of(line) if formatted else None
        if h:  # a heading's words are kept as typed, without marks (release 5.28)
            level, words = h
            parts, at = [], 0
            for x in scan(words, names):
                parts.append(words[at:x.start])
                parts.append(_stored(x, names) or words[x.start:x.end])
                at = x.end
            out.append(f"{'#' * level} {''.join(parts)}{words[at:]}")
            continue
        if formatted:
            m = markup.LIST_LINE.match(line)
            head, rest = (line[:m.end()], line[m.end():]) if m else ("", markup.text_of(line))
            words = "".join(t for t, _, _ in markup._segments(rest))
            spans = [(x.start, x.end, s) for x in scan(words, names) if (s := _stored(x, names))]
            if not spans:
                out.append(line)
            else:
                new = markup.replace_spans(rest, spans)
                out.append(head + new if m else markup.escape_heading(markup.escape_line_start(new)))
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
    """The content text without its operators, for a capture's title. A line of parameters only gives its name and
    sentence: a capture of nothing else is still called something."""
    out = []
    for line in text.split("\n"):
        m = LIST_RE.match(line)
        head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
        toks = scan(rest, names)
        left = clean(rest, toks, names) if toks else line
        p = next((x for x in toks if x.kind == "param"), None)
        if p and not left:
            said = rest[p.start + 2:p.until]
            left = said[:1].upper() + said[1:]
        out.append(head + left if toks else line)
    return "\n".join(out)


def without_params(text: str, names: Names) -> str:
    """The content text without its parameters and their sentences, for a new task's title and description: a line of
    parameters only goes, and any other line stays as it is."""
    out = []
    for line in text.split("\n"):
        m = LIST_RE.match(line)
        head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
        toks = scan(rest, names)
        if not any(x.kind == "param" for x in toks):
            out.append(line)
            continue
        left, at = [], 0
        for x in toks:
            if x.kind == "param":
                left.append(rest[at:x.start])
                at = x.until
        kept = re.sub(r"\s+", " ", "".join(left) + rest[at:]).strip()
        if kept:
            out.append(head + kept)
    return "\n".join(out)


def item_text(it: Item, names: Names) -> str:
    """An item in words, as the test vectors list it (the mockup's ``itemText``)."""
    where = ", ".join("quick" if w.kind == "quick" else "home" if w.kind == "home" else f"item {w.ref}" if w.kind == "item" else w.ref or "" for w in it.where)
    on = f" [{where}]" if where else ""
    if it.kind in PARAM_KINDS:
        kd = it.key_date
        said = key_date_text(kd) if kd else f"{it.value.shown}." if it.value and it.value.shown else ""
        more = f"{it.problem}." if it.problem and not (kd and kd.problem == it.problem) else ""
        return f"{it.label}: {' '.join(x for x in (said, more) if x)}{on}"
    name = "Plant event" if it.plant_event else KIND_NAMES[it.kind] + (f" {it.state}" if it.state else "")
    who = lambda xs: ", ".join(names.person_name(x.id) if x.id else x.name for x in xs)  # noqa: E731
    facts = [] if it.kind != "task" else [it.start and f"start {it.start}", it.due and f"due {it.due}", it.deadline and f"deadline {it.deadline}",
                                          it.assignees and f"for {who(it.assignees)}", it.leads and f"lead {who(it.leads)}"]
    tail = "".join(f" {f}" for f in facts if f)
    return f'{name} "{it.title if it.kind == "task" else it.text}"{tail}{f" {it.problem}." if it.problem else ""}{on}'
