"""Capture records in docs.db, and the capture.md file each capture keeps in its folder.

Phase 2 provides the records and the file format. Saving captures from the
capture window, with their files and emails, comes in phase 3.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from docrepo.db import next_id, note_used_id, transaction
from docrepo.model import Model
from docrepo.safe_fs import SafeFS

SOURCES = ("typed", "outlook_email", "file_path")
CAPTURE_TYPES = ("note", "new_task", "update")


def add_capture(
    conn: sqlite3.Connection, *, saved: str, source: str, types: list[str], title: str, task: str | None = None,
    created_task: str | None = None, summary: str | None = None, summary_type: str | None = None,
    filed_to: str | None = None, filed: str | None = None, edited: str | None = None, capture_id: str | None = None,
) -> str:
    """Record a capture. ``saved`` is a stored time (``YYYY-MM-DD HH:MM:SS``). Returns its ID."""
    if source not in SOURCES:
        raise ValueError(f"Unknown capture source {source!r}.")
    unknown = [t for t in types if t not in CAPTURE_TYPES]
    if unknown or not types:
        raise ValueError(f"A capture needs one or more of the types {', '.join(CAPTURE_TYPES)}; got {types}.")
    with transaction(conn):
        if capture_id:
            note_used_id(conn, capture_id)
        else:
            capture_id = next_id(conn, "C")
        conn.execute(
            "INSERT INTO captures (id, saved, source, task, types, created_task, filed_to, filed, title, summary, summary_type, edited)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (capture_id, saved, source, task, ",".join(types), created_task, filed_to, filed, title, summary, summary_type, edited),
        )
    return capture_id


def add_document(
    conn: sqlite3.Connection, *, name: str, description: str | None, original: str | None = None, capture: str | None = None,
    status: str = "Current", checked: str | None = None, document_id: str | None = None,
) -> str:
    """Record a document: a tracked original (``original`` is its path) or an email attachment (``capture`` holds it)."""
    with transaction(conn):
        if document_id:
            note_used_id(conn, document_id)
        else:
            document_id = next_id(conn, "D")
        conn.execute(
            "INSERT INTO documents (id, name, description, original, capture, status, checked) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (document_id, name, description, original, capture, status, checked),
        )
    return document_id


def link_document(conn: sqlite3.Connection, capture: str, document: str, *, save_a_copy: bool, extract: bool) -> None:
    """Add a document to a capture's list of files, with its choices."""
    with transaction(conn):
        pos = conn.execute("SELECT count(*) FROM capture_documents WHERE capture = ?", (capture,)).fetchone()[0]
        conn.execute(
            "INSERT INTO capture_documents (capture, document, pos, save_a_copy, extract) VALUES (?, ?, ?, ?, ?)",
            (capture, document, pos, int(save_a_copy), int(extract)),
        )


def add_attachment(conn: sqlite3.Connection, capture: str, name: str) -> None:
    """Note an Outlook email's attachment, saved in the capture's attachments folder."""
    with transaction(conn):
        pos = conn.execute("SELECT count(*) FROM capture_attachments WHERE capture = ?", (capture,)).fetchone()[0]
        conn.execute("INSERT INTO capture_attachments (capture, pos, name) VALUES (?, ?, ?)", (capture, pos, name))


def add_version(
    conn: sqlite3.Connection, document: str, *, at: str, difference: str, summary: str | None = None, summary_type: str | None = None
) -> int:
    """Record that a tracked original changed. It joins the raw text log of the document's tasks."""
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO document_versions (document, at, difference, summary, summary_type) VALUES (?, ?, ?, ?, ?)",
            (document, at, difference, summary, summary_type),
        )
    return int(cur.lastrowid)


def add_saved_copy(
    conn: sqlite3.Connection, *, task: str, name: str, document: str, from_capture: str | None = None,
    replaced: str | None = None, old: bool = False,
) -> int:
    """Record a saved copy in a task's Files folder, or a replaced one in its ``_old versions`` folder."""
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO saved_copies (task, name, document, from_capture, replaced, old) VALUES (?, ?, ?, ?, ?, ?)",
            (task, name, document, from_capture, replaced, int(old)),
        )
    return int(cur.lastrowid)


def capture_folder(data_root: Path, capture_id: str, saved: str) -> Path:
    """A capture's folder, ``Captures\\YYYY\\MM\\<id>``. It never moves."""
    return data_root / "Captures" / saved[:4] / saved[5:7] / capture_id


def write_capture_md(fs: SafeFS, data_root: Path, model: Model, capture_id: str, content: str) -> Path:
    """Write a capture's capture.md in its folder."""
    c = model.captures[capture_id]
    return fs.write_text(capture_folder(data_root, c.id, c.saved) / "capture.md", capture_md(model, capture_id, content))


def _iso_t(stored: str) -> str:
    """A stored time as capture.md writes it: ``2026-10-08T08:40:00``."""
    return stored.replace(" ", "T")


def capture_md(model: Model, capture_id: str, content: str) -> str:
    """The text of a capture's capture.md: front matter (JSON values, also valid YAML), the content text, then any summary."""
    c = model.captures[capture_id]
    front: dict[str, object] = {
        "id": c.id,
        "saved": _iso_t(c.saved),
        "source": c.source,
        "task": c.task or c.filed_to or None,
        "capture_types": list(c.types),
    }
    if c.filed:
        front["filed"] = _iso_t(c.filed)
    if c.edited:
        front["edited"] = _iso_t(c.edited)
    if c.created_task:
        front["created_task"] = c.created_task
    changes = [e for e in model.status if e.via == c.id]
    if changes:
        front["changes"] = [{"field": e.field, "from": e.from_value or "None", "to": e.to_value or "None"} for e in changes]
    agenda = [a for a in model.agenda if a.added_by == c.id]
    if agenda:
        front["agenda"] = [{"subject": a.subject, "target": a.target} for a in agenda]
    front["documents"] = [
        {"id": d.document, "name": model.documents[d.document].name, "original": model.documents[d.document].original,
         "description": model.documents[d.document].description, "save_a_copy": d.save_a_copy, "extract": d.extract}
        for d in c.documents
    ]
    front["summary_type"] = c.summary_type
    lines = ["---", *[f"{k}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}" for k, v in front.items()], "---", "", content]
    if c.summary:
        lines += ["", "## Summary", "", c.summary]
    return "\n".join(lines) + "\n"
