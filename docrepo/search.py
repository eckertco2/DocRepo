"""Search in the browse tool: tasks, captures, documents, saved copies, people and labels.

A capture's content text is in its capture.md and a document's text in its
extracted.txt, so their text is copied into a search index in docs.db
(``search_text``) when they're saved, and the whole index can be rebuilt from
the files (the ``rebuild`` command). It's a cache, like the capacity calendar.
Tasks, people and labels are searched straight from their tables.

A search matches items that hold every word typed, in any case, anywhere in
their text: "seal ord" finds "Order a spare mechanical seal". Discarded tasks and
captures aren't found.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from docrepo.captures import read_content
from docrepo.db import transaction
from docrepo.model import Model

log = logging.getLogger(__name__)

#: The most results shown for each kind of item.
LIMIT = 40
GROUPS = ("Task", "Capture", "Document", "Saved copy", "Person", "Label")


@dataclass(frozen=True)
class Result:
    group: str  # one of GROUPS
    kind: str  # what selecting it opens: task, capture, doc, person or label
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


def _put(conn: sqlite3.Connection, kind: str, item_id: str, body: str) -> None:
    conn.execute("INSERT INTO search_text (kind, id, body) VALUES (?, ?, ?) ON CONFLICT(kind, id) DO UPDATE SET body = excluded.body",
                 (kind, item_id, body))


def capture_body(model: Model, data_root: Path, capture_id: str) -> str:
    c = model.captures[capture_id]
    return "\n".join(x for x in (c.id, c.title, c.summary or "", read_content(data_root, c) or "") if x)


def document_body(model: Model, data_root: Path, document_id: str) -> str:
    d = model.documents[document_id]
    return "\n".join(x for x in (d.id, d.name, d.description or "", d.original or "", extracted_text(data_root, document_id)) if x)


def index_items(conn: sqlite3.Connection, data_root: Path, captures: list[str] = (), documents: list[str] = ()) -> None:
    """Bring the index up to date for these captures and documents."""
    model = Model(conn)
    with transaction(conn):
        for c in captures:
            if c in model.captures:
                _put(conn, "capture", c, capture_body(model, data_root, c))
        for d in documents:
            if d in model.documents:
                _put(conn, "document", d, document_body(model, data_root, d))


def rebuild(conn: sqlite3.Connection, data_root: Path) -> int:
    """Rebuild the whole index from the capture.md and extracted.txt files. Returns the number of items."""
    model = Model(conn)
    with transaction(conn):
        conn.execute("DELETE FROM search_text")
        for c in model.captures:
            _put(conn, "capture", c, capture_body(model, data_root, c))
        for d in model.documents:
            _put(conn, "document", d, document_body(model, data_root, d))
    count = len(model.captures) + len(model.documents)
    log.info("search index rebuilt: %d items", count)
    return count


def needs_rebuild(conn: sqlite3.Connection) -> bool:
    """True when the index is missing items, as after DocRepo is first updated to phase 4."""
    have = conn.execute("SELECT count(*) FROM search_text").fetchone()[0]
    want = conn.execute("SELECT (SELECT count(*) FROM captures) + (SELECT count(*) FROM documents)").fetchone()[0]
    return have < want


# ---- searching ----
def words_of(query: str) -> list[str]:
    return [w for w in query.lower().split() if w]


def _has_all(words: list[str], *texts: str | None) -> bool:
    hay = "\n".join(t for t in texts if t).lower()
    return all(w in hay for w in words)


def snippet(text: str, words: list[str], width: int = 110) -> str:
    """The text around the first word found, on one line."""
    low = text.lower()
    at = min((i for i in (low.find(w) for w in words) if i >= 0), default=-1)
    if at < 0:
        return ""
    start = max(0, at - 40)
    part = " ".join(text[start:start + width].split())
    return ("…" if start else "") + part + ("…" if start + width < len(text) else "")


def _after_title(body: str) -> str:
    """An indexed body without its first two lines, the ID and the title or name, which the result shows anyway."""
    return body.split("\n", 2)[2] if body.count("\n") >= 2 else ""


def _like(word: str) -> str:
    return "%" + re.sub(r"([%_\\])", r"\\\1", word) + "%"


def _indexed(conn: sqlite3.Connection, kind: str, words: list[str]) -> list[tuple[str, str]]:
    where = " AND ".join("body LIKE ? ESCAPE '\\'" for _ in words)
    rows = conn.execute(f"SELECT id, body FROM search_text WHERE kind = ? AND {where} ORDER BY id", (kind, *map(_like, words)))
    return [(r["id"], r["body"]) for r in rows]


def search(conn: sqlite3.Connection, model: Model, query: str) -> list[Result]:
    """Everything that holds every word of ``query``, grouped as GROUPS lists them. Two letters at least."""
    words = words_of(query)
    if len("".join(words)) < 2:
        return []
    m, out = model, []
    tasks = [t for t in m.tasks.values() if not t.discarded and _has_all(words, t.id, t.title, t.description, t.current_status, t.deadline_desc)]
    for t in tasks[:LIMIT]:
        out.append(Result("Task", "task", t.id, t.title, f"{t.id} · {t.state}", snippet(f"{t.description}\n{t.current_status}", words)))
    found = [(i, b) for i, b in _indexed(conn, "capture", words) if i in m.captures and not m.captures[i].discarded]
    for cid, body in sorted(found, key=lambda x: m.captures[x[0]].saved, reverse=True)[:LIMIT]:
        c = m.captures[cid]
        out.append(Result("Capture", "capture", c.id, c.title, f"{c.id} · {c.saved[:16]}", snippet(_after_title(body), words)))
    docs = [(i, b) for i, b in _indexed(conn, "document", words) if i in m.documents]
    for did, body in docs[:LIMIT]:
        d = m.documents[did]
        out.append(Result("Document", "doc", d.id, d.name, f"{d.id} · {d.description or d.status}", snippet(_after_title(body), words)))
    for f in [f for f in m.copies if not m.task(f.task).discarded and _has_all(words, f.name)][:LIMIT]:
        out.append(Result("Saved copy", "task", f.task, f.name, f"In {m.task(f.task).title}"))
    for p in [p for p in m.people.values() if _has_all(words, p.id, p.name, *p.aliases)][:LIMIT]:
        out.append(Result("Person", "person", p.id, p.name, ", ".join(p.aliases) + (" · retired" if p.status == "retired" else "")))
    for lb in [lb for lb in m.labels if _has_all(words, lb.name, *lb.keywords)][:LIMIT]:
        out.append(Result("Label", "label", lb.name, lb.name, "Keywords: " + ", ".join(lb.keywords)))
    return out
