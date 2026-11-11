"""Search in the browse tool: tasks, captures, documents, saved copies, people and labels.

A capture's content text is in its capture.md and a document's text in its
extracted.txt, so their text is copied into a search index in docs.db
(``search_text``) when they're saved, and the whole index can be rebuilt from
the files (the ``rebuild`` command). It's a cache, like the capacity calendar.
Tasks, people and labels are searched straight from their tables.

Each task's notes page (release 5.25) is indexed too, as its words (``notes_page.words``), and a hit on it is listed
under Notes, unless one of the page's captures, the record behind it, is found as well.

A search matches items that hold every word typed, in any case, anywhere in
their text: "seal ord" finds "Order a spare mechanical seal". Discarded tasks and
captures aren't found.

A search may say where to look with File search's filters (release 5.121, decisions 447 to 454; release 5.108's place
words, "search excel files …", retired): "type:pdf pump curve", "type:links approval", "from:tom after:1 sep", "tag:V-110",
"#Reactor impeller upgrade seal". ``read`` takes the filters and the ``#task`` out of what was typed, and ``search`` then
lists only what they keep. Filters with no words after them list everything they keep.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from docrepo.captures import plain, read_content
from docrepo.dates import short
from docrepo.db import transaction
from docrepo.model import Capture, Model, SavedCopy, Task
from docrepo.text import snip

log = logging.getLogger(__name__)

#: The most results shown for each kind of item.
LIMIT = 40
#: "Tagged label" comes first (release 5.79, decision 378): a tag typed however it's written names its label.
GROUPS = ("Tagged label", "Task", "Notes", "Capture", "Document", "Saved copy", "Person", "Label")


#: The most for each kind when a search says where to look: fewer kinds are listed, so each may be longer.
SCOPED_LIMIT = 200


@dataclass(frozen=True)
class Scope:
    """Where a search looks and what it keeps (release 5.108; File search's filters since release 5.121, decisions 447 to
    454): the groups it lists, for files the types it keeps (none means every type), the tasks it keeps to (None means
    any), and the filters. ``hints`` say what a filter still being typed takes, or why one names nothing."""

    name: str  # as the heading says it: "PDF files from tom since 1 Sep in Reactor impeller upgrade"
    groups: frozenset[str] = frozenset(GROUPS)
    types: frozenset[str] = frozenset()  # overview.TYPES' keys, "link", "folder"
    emails: bool | None = None  # captures: True keeps only those with an email, False only those without
    tasks: frozenset[str] | None = None  # a "#task" or "in:", with every task under it; empty when no task matched
    senders: frozenset[str] = frozenset()  # from: a sender, folded: an email's sender holds one of them
    sources: frozenset[str] = frozenset()  # from: a file's source (overview.SOURCES)
    since: date | None = None
    before: date | None = None
    pinned: bool = False  # is:pinned: files pinned on a task
    tagged: frozenset[str] = frozenset()  # tag: tagged labels' IDs
    hints: tuple[str, ...] = ()
    applied: bool = True  # False when every filter typed is still being typed: nothing to keep yet

    def lists(self, group: str) -> bool:
        return group in self.groups

    @property
    def dated(self) -> bool:
        return self.since is not None or self.before is not None

    def on(self, day: str | None) -> bool:
        """Whether a day (2026-09-01, or a time stamp) is within the dates; with dates typed, an item with no day isn't."""
        if not self.dated:
            return True
        if not day:
            return False
        d = day[:10]
        return (self.since is None or d >= self.since.isoformat()) and (self.before is None or d < self.before.isoformat())


_FILES = frozenset({"Document", "Saved copy"})
#: What a task holds: a search in a task lists these, and never people or labels.
_IN_TASK = frozenset({"Task", "Notes", "Capture", "Document", "Saved copy"})
#: What may have a sender (``from:``), and what has a day (the dates): people, labels and tagged labels have neither.
_SENT = frozenset({"Capture", "Document", "Saved copy"})
_DATED = frozenset({"Task", "Notes", "Capture", "Document", "Saved copy"})
#: What may mention a tagged label (``tag:``).
_MENTIONS = frozenset({"Task", "Notes", "Capture", "Document"})
_MAIL = Scope("emails", frozenset({"Capture", "Document", "Saved copy"}), frozenset({"mail"}), emails=True)
#: What ``type:`` may name besides File search's file types (decision 449), each in the singular.
_KINDS: dict[str, Scope] = {
    "file": Scope("files", _FILES), "document": Scope("files", _FILES),
    "link": Scope("links", frozenset({"Document"}), frozenset({"link"})),
    "folder": Scope("folders", frozenset({"Document"}), frozenset({"folder"})),
    "note": Scope("notes", frozenset({"Notes", "Capture"}), emails=False),
    "capture": Scope("captures", frozenset({"Capture"})),
    "task": Scope("tasks", frozenset({"Task"})), "project": Scope("tasks", frozenset({"Task"})),
    "person": Scope("people", frozenset({"Person"})), "people": Scope("people", frozenset({"Person"})),
    "label": Scope("labels", frozenset({"Label"})),
    "tag": Scope("tagged labels", frozenset({"Tagged label"})), "tagged": Scope("tagged labels", frozenset({"Tagged label"})),
    "copy": Scope("saved copies", frozenset({"Saved copy"})), "saved": Scope("saved copies", frozenset({"Saved copy"})),
}
_TYPE_SCOPE_NAMES = {"doc": "Word files", "sheet": "Excel files", "slides": "PowerPoint files", "pdf": "PDF files", "picture": "pictures",
                     "drawing": "drawings"}
#: What each filter takes, for one still being typed or one that names nothing: File search's words, with the kinds.
HINTS = {
    "type": "type: takes a kind: pdf, word, excel, powerpoint, picture, drawing, email, link, folder, file, task, note, capture, "
            "person, label, tagged or copy.",
    "in": "in: takes a word of a task's name, as # does: in:reactor.",
    "from": "from: takes part of a sender's name, or attachment, original, copy, link or pasted.",
    "after": "after: takes a date: 1 sep, sep, 2026-09-01, yesterday, last week or 30d.",
    "since": "since: takes a date: 1 sep, sep, 2026-09-01, yesterday, last week or 30d.",
    "before": "before: takes a date: 1 oct, oct, 2026-10-01 or last month.",
    "is": "is: takes pinned, email, attachment, link or picture.",
    "tag": "tag: takes a tagged label, however it's written: tag:V-110.",
}
_NAMES_NOTHING = {"type": "isn't a kind", "from": "names no sender", "in": "names no task", "tag": "names no tagged label",
                  "is": "isn't one of them", "after": "isn't a date", "since": "isn't a date", "before": "isn't a date"}
#: Any filter, read or not, so none is ever a word to find.
_ANY_FILTER = re.compile(r"(^|\s)(type|in|from|after|since|before|is|tag):(\"[^\"]*\"?|\S*)", re.I)
#: The words 5.108's convention began with (decision 454): a search starting so that finds nothing says it went.
OLD_WAY = "“search excel files …” went in release 5.121: type type:excel, type:links, type:notes or a #task first, then the words."


def type_place(value: str) -> Scope | None:
    """The place ``type:`` names (decision 449): File search's file types ("pdf", "excel", ".docx"), and the kinds a
    search lists ("notes", "people", "tasks"), singular or plural; None when it names none."""
    from docrepo.finder import TYPE_WORDS

    v = value.lower().lstrip(".")
    tries = [v]
    if v.endswith("ies"):
        tries.append(v[:-3] + "y")
    if v.endswith("s"):
        tries.append(v[:-1])
    for t in tries:
        if t in ("email", "mail", "msg"):
            return _MAIL
        kind = TYPE_WORDS.get(t)
        if kind in _TYPE_SCOPE_NAMES:
            return Scope(_TYPE_SCOPE_NAMES[kind], _FILES, frozenset({kind}))
        if t in _KINDS:
            return _KINDS[t]
    return None


def _joined(scopes: list[Scope]) -> Scope:
    """Several ``type:`` places together: what any of them lists. A capture is kept when any place that lists captures
    keeps it, and a file when any place that lists files keeps its type."""
    groups = frozenset().union(*(s.groups for s in scopes))
    typed = [s for s in scopes if s.groups & _FILES]
    types = frozenset() if any(not s.types for s in typed) else frozenset().union(*(s.types for s in typed))
    keeps = {s.emails for s in scopes if "Capture" in s.groups}
    emails = next(iter(keeps)) if len(keeps) == 1 else None
    return Scope(" and ".join(dict.fromkeys(s.name for s in scopes)), groups, types, emails)


def task_named(model: Model | None, text: str) -> tuple[list[str], str, str]:
    """The task that ``text``, what follows a ``#``, starts with: the tasks it names, what to call them, and the text left.

    A whole title, as the # list writes it, names that task (the longest title wins); a task's ID names it; otherwise the
    first word names every task with a word of its title starting that way, so "#reactor seal" looks for "seal" in the
    Reactor tasks. Discarded tasks aren't named. No match gives no tasks, and takes the first word."""
    live = [t for t in model.tasks.values() if not t.discarded] if model is not None else []
    low = text.lower()
    whole = [t for t in live if t.title and low.startswith(t.title.lower()) and (len(low) == len(t.title) or low[len(t.title)].isspace())]
    if whole:
        t = max(whole, key=lambda t: len(t.title))
        return [t.id], t.title, text[len(t.title):].strip()
    first, _, rest = text.partition(" ")
    if not first:
        return [], "#", rest.strip()
    by_id = [t for t in live if t.id.lower() == first.lower()]
    found = by_id or [t for t in live if any(w.startswith(first.lower()) for w in re.split(r"[^\w]+", t.title.lower()))]
    name = found[0].title if len(found) == 1 else f"#{first}"
    return [t.id for t in found], name, rest.strip()


@dataclass
class _Reading:
    """What ``read`` gathers as it reads the filters."""

    places: list[Scope] = field(default_factory=list)
    senders: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    since: date | None = None
    before: date | None = None
    pinned: bool = False
    tags: dict[str, str] = field(default_factory=dict)  # a tagged label's ID, and its label
    in_tasks: list[tuple[frozenset[str], str]] = field(default_factory=list)
    said_from: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    said_dates: list[str] = field(default_factory=list)
    wrong: bool = False  # a filter that names nothing: nothing is listed
    found: bool = False  # any filter word, read or not
    applied: bool = False  # a filter or a "#task" read


def _apply(r: _Reading, op: str, value: str, model: Model | None, today: date) -> bool:
    """One filter, typed whole: whether it named something, gathered into ``r``."""
    from docrepo import finder, tagged
    from docrepo.overview import fold

    v = fold(value)
    if op == "type":
        place = type_place(v)
        if place:
            r.places.append(place)
        return place is not None
    if op == "from":
        if v in finder.SOURCE_WORDS:
            r.sources.add(finder.SOURCE_WORDS[v])
        elif v:
            r.senders.add(v)
        r.said_from.append(f"from {value}")
        return bool(v)
    if op in ("after", "since", "before"):
        day = finder.read_day(value, today)
        if day and op == "before":
            r.before = day
        elif day:
            r.since = day + timedelta(days=1) if op == "after" else day
        if day:
            r.said_dates.append(f"{op} {short(day, today)}")
        return day is not None
    if op == "is":
        if v == "pinned":
            r.pinned = True
        elif v in ("email", "emails"):
            r.places.append(_MAIL)
        elif v in ("attachment", "attachments"):
            r.sources.add("Email attachment")
            r.said_from.append("from attachments")
        elif v in ("link", "links", "picture", "pictures"):
            r.places.append(type_place(v))
        elif v == "missing":  # decision 451: Find files and File search find a file missing when it won't open
            r.hints.append("is:missing works in Find files and File search, where a file is found missing when it won't open.")
            r.wrong = True
        else:
            return False
        return True
    if op == "tag":
        lb = tagged.label_named(model.tagged, value) if model is not None else None
        if lb is not None:
            r.tags[lb.id] = lb.label
        return lb is not None
    if op == "in":
        ids, name, rest = task_named(model, value)
        if ids and not rest:
            r.in_tasks.append((frozenset(x for i in ids for x in [i, *model.descendants_of(i)]), name.lstrip("#")))
            return True
    return False


def read(query: str, model: Model | None = None, today: date | None = None) -> tuple[Scope | None, str]:
    """What was typed, as where to look and what to find (release 5.121, decisions 447 to 454; 5.108's place words retired).

    File search's filters anywhere in it (``type:pdf``, ``from:tom``, ``after:1 sep``, ``is:pinned``, ``tag:V-110``,
    ``in:reactor``, a bare ``.docx``), then a ``#task`` at the start of what's left, then the words. A filter at the end
    needs no space after it when its value is whole, as a search runs as you type. One still being typed, or one that
    names nothing, is never a word to find, and its hint says what it takes; one that names nothing lists nothing.
    ``model`` gives the tasks and the tagged labels (without it, a "#" names none); ``today`` the dates' today. With no
    filter and no task, the whole of what was typed is words, and the scope is None."""
    from docrepo import finder

    today = today or date.today()
    r = _Reading()

    def whole(m: re.Match) -> str:
        if _apply(r, m.group(2).lower(), (m.group(3) or m.group(4) or "").strip(), model, today):
            r.found = r.applied = True
            return m.group(1) + " "
        return m.group(0)

    def extension(m: re.Match) -> str:
        r.places.append(type_place(m.group(2)))
        r.found = r.applied = True
        return m.group(1) + " "

    text = finder._EXTENSION.sub(extension, finder._OPERATOR.sub(whole, finder._DATE_OPERATOR.sub(whole, query.rstrip() + " ")))

    def unread(m: re.Match) -> str:
        """A filter it couldn't read: still being typed at the end, or naming nothing."""
        op, value = m.group(2).lower(), m.group(3)
        r.found = True
        if not text[m.end():].strip() and not query.endswith(" "):  # still being typed: said, and left out
            r.hints.append(f"{op}:{value} {_NAMES_NOTHING[op]} yet. {HINTS[op]}" if value else HINTS[op])
        else:
            r.hints.append(f"{op}:{value} {_NAMES_NOTHING[op]}. {HINTS[op]}" if value else HINTS[op])
            r.wrong = True
        return m.group(1) + " "

    rest = " ".join(_ANY_FILTER.sub(unread, text).split())
    tasks: frozenset[str] | None = None
    where: list[str] = []
    if rest.startswith("#"):
        ids, task_name, rest = task_named(model, rest[1:])
        tasks = frozenset(x for i in ids for x in [i, *model.descendants_of(i)]) if model is not None else frozenset()
        where.append(task_name)
        r.found = r.applied = True
    for ids, name in r.in_tasks:
        tasks = ids if tasks is None else tasks & ids
        where.append(name)
    if not r.found:
        return None, query
    base = _joined(r.places) if r.places else Scope("")
    groups = base.groups
    for on, keep in ((tasks is not None, _IN_TASK), (r.senders or r.sources, _SENT), (r.since or r.before, _DATED), (r.pinned, frozenset({"Document"})),
                     (r.tags, _MENTIONS), (r.wrong, frozenset())):
        if on:
            groups &= keep
    said = [base.name or ("pinned files" if r.pinned else ""), *r.said_from]
    said += r.said_dates
    said += ["mentioning " + " or ".join(r.tags.values())] if r.tags else []
    said += ["in " + " and ".join(dict.fromkeys(where))] if where else []
    name = " ".join(x for x in said if x)
    if base.name:
        name = name[0].upper() + name[1:]
    return Scope(name, groups, base.types, base.emails, tasks, frozenset(r.senders), frozenset(r.sources), r.since, r.before, r.pinned,
                 frozenset(r.tags), tuple(dict.fromkeys(r.hints)), r.applied), rest


@dataclass(frozen=True)
class Result:
    group: str  # one of GROUPS
    kind: str  # what selecting it opens: task, capture, doc, person, label or tagged (a tagged label, by its key)
    id: str
    title: str
    sub: str
    snippet: str = ""  # the text around the first word found, when it's in the item's body


# ---- the index ----
def extracted_text(data_root: Path, document_id: str) -> str:
    try:
        return (data_root / "Documents" / document_id / "extracted.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _put(conn: sqlite3.Connection, kind: str, item_id: str, body: str, tagged_too: bool = True) -> None:
    from docrepo import tagged

    conn.execute("INSERT INTO search_text (kind, id, body) VALUES (?, ?, ?) ON CONFLICT(kind, id) DO UPDATE SET body = excluded.body",
                 (kind, item_id, body))
    if kind != "page" and tagged_too:  # its tagged labels, from the same text (release 5.79, decision 377); a page's from its own text
        tagged.index(conn, kind, item_id, tagged.text_of_body(kind, body))


def capture_body(model: Model, data_root: Path, capture_id: str) -> str:
    c = model.captures[capture_id]
    described = [e.description for e in c.emails if e.description]  # what its emails are about (round 7's item 93)
    return "\n".join(x for x in (c.id, c.title, *described, c.summary or "", plain(c, read_content(data_root, c)) or "") if x)


def document_body(model: Model, data_root: Path, document_id: str) -> str:
    d = model.documents[document_id]
    return "\n".join(x for x in (d.id, d.name, d.description or "", d.original or "", extracted_text(data_root, document_id)) if x)


def index_items(conn: sqlite3.Connection, data_root: Path, captures: list[str] = (), documents: list[str] = ()) -> None:
    """Bring the index up to date for these captures and documents."""
    from docrepo import tagged

    model = Model(conn)
    with transaction(conn), tagged.batch(conn):  # their tagged labels together (release 5.80)
        for c in captures:
            if c in model.captures:
                _put(conn, "capture", c, capture_body(model, data_root, c))
        for d in documents:
            if d in model.documents:
                _put(conn, "document", d, document_body(model, data_root, d))


def page_body(model: Model, task_id: str) -> str:
    from docrepo import notes_page

    return "\n".join((task_id, model.task(task_id).title, notes_page.words(model.pages.get(task_id, ""))))


def index_pages(conn: sqlite3.Connection, task_ids: list[str]) -> None:
    """Bring the index up to date for these tasks' notes pages (release 5.25)."""
    if not task_ids:
        return
    model = Model(conn)
    from docrepo import tagged

    with transaction(conn), tagged.batch(conn):  # their tagged labels together (release 5.80)
        for t in dict.fromkeys(task_ids):
            if t in model.tasks:
                _put(conn, "page", t, page_body(model, t))
                tagged.index(conn, "page", t, tagged.page_text(model.pages.get(t, "")))  # release 5.79


def rebuild(conn: sqlite3.Connection, data_root: Path) -> int:
    """Rebuild the whole index from the capture.md and extracted.txt files. Returns the number of items."""
    model = Model(conn)
    with transaction(conn):
        conn.execute("DELETE FROM search_text")
        # tagged.rebuild below reads every item's tagged labels from the index, so they aren't found item by item here too
        for c in model.captures:
            _put(conn, "capture", c, capture_body(model, data_root, c), tagged_too=False)
        for d in model.documents:
            _put(conn, "document", d, document_body(model, data_root, d), tagged_too=False)
        for t in model.pages:
            if t in model.tasks:
                _put(conn, "page", t, page_body(model, t), tagged_too=False)
    count = len(model.captures) + len(model.documents) + len(model.pages)
    log.info("search index rebuilt: %d items", count)
    from docrepo import tagged

    tagged.rebuild(conn)  # its caches are read from the index (release 5.79)
    return count


def needs_rebuild(conn: sqlite3.Connection) -> bool:
    """True when the index is missing items, as after DocRepo is first updated to phase 4."""
    have = conn.execute("SELECT count(*) FROM search_text").fetchone()[0]
    want = conn.execute("SELECT (SELECT count(*) FROM captures) + (SELECT count(*) FROM documents) + (SELECT count(*) FROM task_pages)").fetchone()[0]
    return have < want


# ---- searching ----
def words_of(query: str) -> list[str]:
    return [w for w in query.lower().split() if w]


def _has_all(words: list[str], *texts: str | None) -> bool:
    hay = "\n".join(t for t in texts if t).lower()
    return all(w in hay for w in words)


def snippet(text: str, words: list[str], width: int = 160) -> str:
    """The text around the first word found, on one line: wide enough to fill a row once an email's headers and the row's own title
    are taken out (release 5.114; 110 before)."""
    low = text.lower()
    at = min((i for i in (low.find(w) for w in words) if i >= 0), default=-1)
    if at < 0:
        return ""
    return snip(text, at, 40, width)


def _after_title(body: str) -> str:
    """An indexed body without its first two lines, the ID and the title or name, which the result shows anyway."""
    return body.split("\n", 2)[2] if body.count("\n") >= 2 else ""


def _like(word: str) -> str:
    return "%" + re.sub(r"([%_\\])", r"\\\1", word) + "%"


def _indexed(conn: sqlite3.Connection, kind: str, words: list[str]) -> list[tuple[str, str]]:
    where = " AND ".join("body LIKE ? ESCAPE '\\'" for _ in words) or "1"
    rows = conn.execute(f"SELECT id, body FROM search_text WHERE kind = ? AND {where} ORDER BY id", (kind, *map(_like, words)))  # noqa: S608 - a column or table name of DocRepo's own; values are parameters
    return [(r["id"], r["body"]) for r in rows]


def _bodies(conn: sqlite3.Connection, kind: str, ids: set[str]) -> list[tuple[str, str]]:
    """These items' indexed bodies, for what a tagged label's mentions add to a search."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    query = f"SELECT id, body FROM search_text WHERE kind = ? AND id IN ({marks}) ORDER BY id"  # noqa: S608 - only ? marks are joined in
    return [(r["id"], r["body"]) for r in conn.execute(query, (kind, *sorted(ids)))]


class _Keeper:
    """What a scope's filters keep, item by item (decision 451). from: an email capture by its sender, a file by the email
    it came with or by its source. The dates: a capture's saved day, a file's first capture's day, a saved copy's day, a
    task's created day, a notes page's last edit. is:pinned: files pinned on a task. tag: what mentions a tagged label.
    What each needs is read once, and only when a filter needs it."""

    def __init__(self, conn: sqlite3.Connection, model: Model, scope: Scope) -> None:
        self.conn, self.m, self.s = conn, model, scope
        self.first: dict[str, Capture] = {}  # a document's first capture, the one that brought it
        if scope.senders or scope.sources or scope.dated:
            for c in sorted(model.captures.values(), key=lambda c: c.saved):
                if not c.discarded:
                    for d in c.document_ids:
                        self.first.setdefault(d, c)
        self.pinned = {d for ds in model.pins.values() for d in ds} if scope.pinned else set()
        self.edited: dict[str, str] = {}
        for task_id, day, _at in model.page_edits if scope.dated else ():
            self.edited[task_id] = max(day, self.edited.get(task_id, ""))
        self.mentions: dict[str, set[str]] = {}
        if scope.tagged:
            from docrepo import tagged

            for lb in model.tagged.labels.values():
                if lb.id in scope.tagged:
                    for u in tagged.uses_of(model, lb):
                        self.mentions.setdefault(u.kind, set()).add(u.id)
        self._bodies: dict[str, str] | None = None

    def _mentioned(self, kind: str, item_id: str) -> bool:
        return not self.s.tagged or item_id in self.mentions.get(kind, ())

    def _sent_by(self, c: Capture | None, body: str | None = None) -> bool:
        """Whether a capture's email is from a sender typed: by its emails' senders, else its From line."""
        if not self.s.senders:
            return True
        if c is None or not (c.emails or c.source == "outlook_email"):
            return False
        from docrepo.overview import fold, sender_of

        if body is None and not c.emails:
            if self._bodies is None:
                self._bodies = {r[0]: r[1] for r in self.conn.execute("SELECT id, body FROM search_text WHERE kind = 'capture'")}
            body = self._bodies.get(c.id, "")
        names = [fold(e.sender) for e in c.emails] + ([fold(sender_of(body))] if body else [])
        return any(s in n for s in self.s.senders for n in names if n)

    def task(self, t: Task) -> bool:
        return self.s.on(t.created) and self._mentioned("task", t.id)

    def page(self, task_id: str) -> bool:
        return self.s.on(self.edited.get(task_id)) and self._mentioned("page", task_id)

    def capture(self, c: Capture, body: str) -> bool:
        return not self.s.sources and self.s.on(c.saved) and self._sent_by(c, body) and self._mentioned("capture", c.id)

    def _source(self, doc_id: str) -> str:
        from docrepo.overview import file_type

        d, c = self.m.documents[doc_id], self.first.get(doc_id)
        kind = file_type(d.name, d.original)
        if kind == "link":
            return "Link"
        if d.original:
            return "Pasted on the notes page" if c is not None and c.page_made and kind == "picture" else "Tracked original"
        return "Email attachment"

    def document(self, doc_id: str) -> bool:
        c = self.first.get(doc_id)
        return ((not self.s.sources or self._source(doc_id) in self.s.sources) and self._sent_by(c)
                and self.s.on(c.saved if c is not None else None) and (not self.s.pinned or doc_id in self.pinned)
                and self._mentioned("document", doc_id))

    def copy(self, f: SavedCopy) -> bool:
        from docrepo.file_rows import dated_name

        c = self.m.captures.get(f.from_capture) if f.from_capture else None
        day = dated_name(f.name)[0] or (c.saved if c is not None else None)
        return ((not self.s.sources or "Saved copy" in self.s.sources) and self._sent_by(c) and self.s.on(day)
                and (not self.s.pinned or f.document in self.pinned))


def search(conn: sqlite3.Connection, model: Model, query: str, today: date | None = None) -> list[Result]:
    """Everything that holds every word of ``query``, grouped as GROUPS lists them. Two letters at least. Filters and a
    "#task" (release 5.121) list only what they keep; ``today`` is the dates' today."""
    from docrepo.overview import file_type

    scope, query = read(query, model, today)
    words = words_of(query)
    if len("".join(words)) < 2 and (scope is None or words or not scope.applied):  # a scope alone lists everything in it
        return []
    if scope is not None and not scope.groups:  # a filter that names nothing (decision 452)
        return []
    m, out = model, []
    keep = _Keeper(conn, m, scope) if scope is not None else None
    in_tasks = scope.tasks if scope else None
    # The documents on a scope's tasks: those their captures brought, and their saved copies.
    on_tasks = {d for c in m.captures.values() if c.task in in_tasks for d in c.document_ids} | {
        f.document for f in m.copies if f.task in in_tasks} if in_tasks is not None else set()

    def here(task_id: str | None) -> bool:
        return in_tasks is None or task_id in in_tasks

    limit = SCOPED_LIMIT if scope is not None and scope.applied else LIMIT

    def lists(group: str) -> bool:
        return scope is None or scope.lists(group)

    def typed(name: str, original: str | None = None) -> bool:
        return scope is None or not scope.types or file_type(name, original) in scope.types

    def wanted(capture_id: str) -> bool:  # notes leave emails out, and emails keep only them
        c = m.captures[capture_id]
        return scope is None or scope.emails is None or bool(c.emails or c.source == "outlook_email") == scope.emails

    # Tagged labels (release 5.79, decision 378): one typed however it's written ("v110" finds V-110) is listed first, and
    # what mentions it is found too, in its own group, even where it's written another way.
    from docrepo import tagged

    named = tagged.find_labels(m.tagged, query) if words else []
    for lb in named[:limit] if lists("Tagged label") else ():
        uses = tagged.uses_of(m, lb)
        what = f"New, from the {lb.pattern} pattern" if lb.status == "suggested" else lb.description  # release 5.80: suggested
        out.append(Result("Tagged label", "tagged", lb.key, lb.label, " · ".join(x for x in (what, f"mentioned in {len(uses)} item{'s' if len(uses) != 1 else ''}") if x)))
    mentioned: dict[str, set[str]] = {}
    if len(named) == 1:
        for u in tagged.uses_of(m, named[0]):
            mentioned.setdefault(u.kind, set()).add(u.id)
    # A task's reference fields (release 5.9, M0034) are found too, by their values: "work order 48213" finds Work order # 48213.
    tasks = [t for t in m.tasks.values() if not t.discarded and here(t.id) and (t.id in mentioned.get("task", ()) or _has_all(
        words, t.id, t.title, t.description, t.current_status, t.deadline_desc, *(f"{k} {v}" for k, v in t.references.items())))
        and (keep is None or keep.task(t))]
    for t in tasks[:limit] if lists("Task") else ():
        out.append(Result("Task", "task", t.id, t.title, f"{t.id} · {t.state}", snippet(f"{t.description}\n{t.current_status}", words)))
    found = [(i, b) for i, b in _indexed(conn, "capture", words) if i in m.captures and not m.captures[i].discarded]
    found += _bodies(conn, "capture", mentioned.get("capture", set()) - {i for i, _ in found})
    found = [(i, b) for i, b in found if wanted(i) and here(m.captures[i].task) and (keep is None or keep.capture(m.captures[i], b))
             ] if lists("Capture") else []
    # Notes pages (release 5.25): a page's hit, unless its task is listed already or a capture on it is found.
    from docrepo import notes_page

    listed, hit = {t.id for t in tasks} if lists("Task") else set(), {i for i, _ in found}
    pages = [(i, b) for i, b in [*_indexed(conn, "page", words), *_bodies(conn, "page", mentioned.get("page", set()))]
             if i in m.tasks and not m.tasks[i].discarded and here(i) and i not in listed and not hit & set(notes_page.capture_ids(m.pages.get(i, "")))
             and (keep is None or keep.page(i))]
    pages = list(dict(pages).items()) if lists("Notes") else []
    for tid, body in pages[:limit]:
        t = m.tasks[tid]
        out.append(Result("Notes", "task", t.id, f"Notes of {t.title}", f"{t.id} · its notes page", snippet(_after_title(body), words)))
    for cid, body in sorted(found, key=lambda x: m.captures[x[0]].saved, reverse=True)[:limit]:
        c = m.captures[cid]
        out.append(Result("Capture", "capture", c.id, c.title, f"{c.id} · {c.saved[:16]}", snippet(_after_title(body), words)))
    docs = [(i, b) for i, b in _indexed(conn, "document", words) if i in m.documents]
    docs += _bodies(conn, "document", mentioned.get("document", set()) - {i for i, _ in docs})
    docs = [(i, b) for i, b in docs if typed(m.documents[i].name, m.documents[i].original) and (in_tasks is None or i in on_tasks)
            and (keep is None or keep.document(i))] if lists("Document") else []
    for did, body in docs[:limit]:
        d = m.documents[did]
        out.append(Result("Document", "doc", d.id, d.name, f"{d.id} · {d.description or d.status}", snippet(_after_title(body), words)))
    copies = [f for f in m.copies if not m.task(f.task).discarded and _has_all(words, f.name) and typed(f.name) and here(f.task)
              and (keep is None or keep.copy(f))] if lists("Saved copy") else []
    for f in copies[:limit]:
        out.append(Result("Saved copy", "task", f.task, f.name, f"In {m.task(f.task).title}"))
    # People by their email, group and role too (release 5.9, M0031, M0033, M0038).
    people = [p for p in m.people.values() if _has_all(words, p.id, p.name, *p.aliases, p.email, p.group, p.role)] if lists("Person") else []
    for p in people[:limit]:
        sub = " · ".join(x for x in (", ".join(p.aliases), p.group, p.role) if x)
        out.append(Result("Person", "person", p.id, p.name, sub + (" · retired" if p.status == "retired" else "")))
    for lb in [lb for lb in m.labels if _has_all(words, lb.name, *lb.keywords)][:limit] if lists("Label") else ():
        out.append(Result("Label", "label", lb.name, lb.name, "Keywords: " + ", ".join(lb.keywords)))
    return out
