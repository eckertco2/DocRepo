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

A search may say where to look (release 5.108, decisions 409 to 414): "search excel files pump curve", "search links
approval forms", "search notes V-110", "search #Reactor impeller upgrade seal". ``read`` takes the scope off the front of
what was typed (a place, a task after ``#``, or both), and ``search`` then lists only that scope's groups, its file types
and its task's items. A scope with no words after it lists everything in it.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from docrepo.captures import plain, read_content
from docrepo.db import transaction
from docrepo.model import Model
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
    """Where a search looks (release 5.108): the groups it lists, for files the types it keeps (none means every type), and
    the tasks it keeps to (None means any)."""

    name: str  # as the heading says it: "Excel files", "Links", "Notes in Reactor impeller upgrade"
    groups: frozenset[str]
    types: frozenset[str] = frozenset()  # overview.TYPES' keys, "link", "folder"
    emails: bool | None = None  # captures: True keeps only those with an email, False only those without
    tasks: frozenset[str] | None = None  # a task after "#", with every task under it; empty when no task matched

    def lists(self, group: str) -> bool:
        return group in self.groups


_FILES = frozenset({"Document", "Saved copy"})
#: What a task holds: a search in a task lists these, and never people or labels.
_IN_TASK = frozenset({"Task", "Notes", "Capture", "Document", "Saved copy"})
_MAIL = Scope("Emails", frozenset({"Capture", "Document", "Saved copy"}), frozenset({"mail"}), emails=True)
#: What a place may be called, each in the singular. A file type's words are File search's own (``finder.TYPE_WORDS``).
_SCOPES: dict[str, Scope] = {
    "file": Scope("Files", _FILES), "document": Scope("Files", _FILES), "doc": Scope("Files", _FILES),
    "link": Scope("Links", frozenset({"Document"}), frozenset({"link"})),
    "folder": Scope("Folders", frozenset({"Document"}), frozenset({"folder"})),
    "note": Scope("Notes", frozenset({"Notes", "Capture"}), emails=False),
    "email": _MAIL, "mail": _MAIL,
    "capture": Scope("Captures", frozenset({"Capture"})),
    "task": Scope("Tasks", frozenset({"Task"})), "project": Scope("Tasks", frozenset({"Task"})),
    "person": Scope("People", frozenset({"Person"})), "people": Scope("People", frozenset({"Person"})),
    "label": Scope("Labels", frozenset({"Label"})),
    "tag": Scope("Tagged labels", frozenset({"Tagged label"})), "tagged label": Scope("Tagged labels", frozenset({"Tagged label"})),
    "saved copy": Scope("Saved copies", frozenset({"Saved copy"})), "copy": Scope("Saved copies", frozenset({"Saved copy"})),
}
_TYPE_SCOPE_NAMES = {"doc": "Word files", "sheet": "Excel files", "slides": "PowerPoint files", "pdf": "PDF files", "picture": "Pictures",
                     "drawing": "Drawings"}
#: "search" starts a scope; a task's "#" does too, on its own.
_VERB = re.compile(r"^\s*search(?:\s+|$)", re.I)
_NOUN = re.compile(r"\s+(?:files?|documents?|docs?|sheets?|workbooks?)$")
#: Words passed over around a place and a task: "search all my excel files in #Reactor for seal".
_SMALL = ("my", "the", "all", "every", "in", "on", "under", "for")


def _scope_named(phrase: str) -> Scope | None:
    """The place a phrase names: "excel files", "PDFs", "links", "saved copies", or None."""
    from docrepo.finder import TYPE_WORDS

    phrase = " ".join(phrase.lower().split())
    tries = [phrase, _NOUN.sub("", phrase)]
    for p in list(tries):
        if p.endswith("ies"):
            tries.append(p[:-3] + "y")
        if p.endswith("s"):
            tries.append(p[:-1])
    for p in tries:
        if p in _SCOPES:
            return _SCOPES[p]
        kind = TYPE_WORDS.get(p)
        if kind in _TYPE_SCOPE_NAMES:
            return Scope(_TYPE_SCOPE_NAMES[kind], _FILES, frozenset({kind}))
    return None


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


def read(query: str, model: Model | None = None) -> tuple[Scope | None, str]:
    """What was typed, as where to look and what to find (decisions 409 and 414).

    "search", then a place ("excel files", "links", "notes"), a task after "#", or both in either order, then the words:
    "search excel files pump curve", "search links #Reactor impeller upgrade", "search #Reactor impeller upgrade seal".
    A "#task" may start it without "search". Small words around them ("in", "for", "my", "all") are passed over. With no
    place or task it knows, the whole of what was typed is words to find, so "search for the pump" searches as it always did.
    A task's scope holds it and every task under it; ``model`` gives the tasks (without it, a "#" names none)."""
    verb = _VERB.match(query)
    rest = query[verb.end():] if verb else query.lstrip()
    if not verb and not rest.startswith("#"):
        return None, query
    place: Scope | None = None
    tasks: frozenset[str] | None = None
    task_name = ""
    while rest:
        words = rest.split()
        if rest.startswith("#") and tasks is None:
            ids, task_name, rest = task_named(model, rest[1:])
            tasks = frozenset(x for i in ids for x in [i, *model.descendants_of(i)]) if model is not None else frozenset()
            continue
        if words[0].lower() in _SMALL and (place or tasks is not None or len(words) > 1 and (
                words[1].startswith("#") or any(_scope_named(" ".join(words[1:1 + n])) for n in (3, 2, 1)) or words[1].lower() in _SMALL)):
            rest = rest.split(None, 1)[1] if len(words) > 1 else ""
            continue
        n = next((n for n in (3, 2, 1) if len(words) >= n and _scope_named(" ".join(words[:n]))), 0) if place is None else 0
        if not n:
            break
        place = _scope_named(" ".join(words[:n]))
        rest = rest.split(None, n)[n] if len(words) > n else ""
    if place is None and tasks is None:
        return None, query
    if tasks is None:
        return place, rest.strip()
    base = place or Scope(task_name, _IN_TASK)
    name = f"{place.name} in {task_name}" if place else task_name
    return Scope(name, base.groups & _IN_TASK, base.types, base.emails, tasks), rest.strip()


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


def search(conn: sqlite3.Connection, model: Model, query: str) -> list[Result]:
    """Everything that holds every word of ``query``, grouped as GROUPS lists them. Two letters at least. A query that
    says where to look ("search links for …", release 5.108) lists only that scope."""
    from docrepo.overview import file_type

    scope, query = read(query, model)
    words = words_of(query)
    if len("".join(words)) < 2 and (scope is None or words):  # a scope alone lists everything in it
        return []
    m, out = model, []
    in_tasks = scope.tasks if scope else None
    # The documents on a scope's tasks: those their captures brought, and their saved copies.
    on_tasks = {d for c in m.captures.values() if c.task in in_tasks for d in c.document_ids} | {
        f.document for f in m.copies if f.task in in_tasks} if in_tasks is not None else set()

    def here(task_id: str | None) -> bool:
        return in_tasks is None or task_id in in_tasks

    limit = SCOPED_LIMIT if scope else LIMIT

    def lists(group: str) -> bool:
        return scope is None or scope.lists(group)

    def typed(name: str, original: str | None = None) -> bool:
        return scope is None or not scope.types or file_type(name, original) in scope.types

    def wanted(capture_id: str) -> bool:  # notes leave emails out, and emails keep only them
        return scope is None or scope.emails is None or bool(m.captures[capture_id].emails) == scope.emails

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
        words, t.id, t.title, t.description, t.current_status, t.deadline_desc, *(f"{k} {v}" for k, v in t.references.items())))]
    for t in tasks[:limit] if lists("Task") else ():
        out.append(Result("Task", "task", t.id, t.title, f"{t.id} · {t.state}", snippet(f"{t.description}\n{t.current_status}", words)))
    found = [(i, b) for i, b in _indexed(conn, "capture", words) if i in m.captures and not m.captures[i].discarded]
    found += _bodies(conn, "capture", mentioned.get("capture", set()) - {i for i, _ in found})
    found = [(i, b) for i, b in found if wanted(i) and here(m.captures[i].task)] if lists("Capture") else []
    # Notes pages (release 5.25): a page's hit, unless its task is listed already or a capture on it is found.
    from docrepo import notes_page

    listed, hit = {t.id for t in tasks} if lists("Task") else set(), {i for i, _ in found}
    pages = [(i, b) for i, b in [*_indexed(conn, "page", words), *_bodies(conn, "page", mentioned.get("page", set()))]
             if i in m.tasks and not m.tasks[i].discarded and here(i) and i not in listed and not hit & set(notes_page.capture_ids(m.pages.get(i, "")))]
    pages = list(dict(pages).items()) if lists("Notes") else []
    for tid, body in pages[:limit]:
        t = m.tasks[tid]
        out.append(Result("Notes", "task", t.id, f"Notes of {t.title}", f"{t.id} · its notes page", snippet(_after_title(body), words)))
    for cid, body in sorted(found, key=lambda x: m.captures[x[0]].saved, reverse=True)[:limit]:
        c = m.captures[cid]
        out.append(Result("Capture", "capture", c.id, c.title, f"{c.id} · {c.saved[:16]}", snippet(_after_title(body), words)))
    docs = [(i, b) for i, b in _indexed(conn, "document", words) if i in m.documents]
    docs += _bodies(conn, "document", mentioned.get("document", set()) - {i for i, _ in docs})
    docs = [(i, b) for i, b in docs if typed(m.documents[i].name, m.documents[i].original) and (in_tasks is None or i in on_tasks)] if lists(
        "Document") else []
    for did, body in docs[:limit]:
        d = m.documents[did]
        out.append(Result("Document", "doc", d.id, d.name, f"{d.id} · {d.description or d.status}", snippet(_after_title(body), words)))
    copies = [f for f in m.copies if not m.task(f.task).discarded and _has_all(words, f.name) and typed(f.name) and here(f.task)] if lists("Saved copy") else []
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
