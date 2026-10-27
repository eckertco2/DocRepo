"""The made-up sample data: the browse tool mockup's tasks, people, captures and agendas.

It's for trying DocRepo and for its tests, never for real use: ``load-sample``
refuses a database that already holds anything. The data is "as of" Thursday
2026-10-08 07:58, so pages built as of then match the mockup's ``examples.md``.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from docrepo import agenda, captures, people
from docrepo.db import note_used_id, transaction
from docrepo.model import Model
from docrepo.safe_fs import SafeFS
from docrepo.text import capture_title

SAMPLE_FILE = Path(__file__).resolve().parent / "sample" / "sample-data.json"
#: The moment the sample data describes.
SAMPLE_AS_OF = datetime(2026, 10, 8, 7, 58)

_SOURCES = {"typed": "typed", "email": "outlook_email", "path": "file_path"}
_TYPES = {"note": "note", "new": "new_task", "update": "update"}


class SampleError(Exception):
    """The sample data can't be loaded here."""


def read_sample() -> dict[str, Any]:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def _time(value: str | None) -> str | None:
    """The sample's ``YYYY-MM-DD HH:MM`` as a stored time."""
    return f"{value}:00" if value and len(value) == 16 else value


def _none(value: str | None) -> str | None:
    return None if value in (None, "", "None") else value


def is_empty(conn: sqlite3.Connection) -> bool:
    return not any(conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in ("tasks", "people", "captures", "labels"))


def load_sample(conn: sqlite3.Connection, data: dict[str, Any] | None = None) -> None:
    """Put the sample data into an empty docs.db, keeping its IDs."""
    data = data or read_sample()
    docs = {d["id"]: d for d in data["documents"]}
    with transaction(conn):
        if not is_empty(conn):
            raise SampleError("docs.db already holds data. Load the sample data only into a new, empty data root.")
        for p in data["people"]:
            people.add_person(conn, p["name"], aliases=p["aliases"], hours=p["hours"], added_note=p.get("added"),
                              status=p["status"], person_id=p["id"], email=p.get("email"), group=p.get("group"), role=p.get("role"))
        for label in data["labels"]:
            people.add_label(conn, label["name"], label["keywords"])
        for t in data["tasks"]:
            note_used_id(conn, t["id"])
            conn.execute(
                "INSERT INTO tasks (id, title, state, closed, urgent, meeting, recurrence, repeat_until, start, due, deadline,"
                " deadline_desc, reminder, lead_hours, assignee_hours, inherit_labels, description, current_status, created, created_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (t["id"], t["title"], t["state"], t.get("closed"), int(t.get("urgent", False)), int(t.get("meeting", False)),
                 t.get("recurrence"), t.get("repeatUntil"), t.get("start"), t.get("due"), t.get("deadline"), t.get("deadlineDesc"),
                 t.get("reminder"), t.get("leadH"), t.get("asgH"), int(t.get("inherit", True)), t.get("desc", ""),
                 t.get("status", ""), t["created"], t["by"]),
            )
            for role, key in (("lead", "leads"), ("assignee", "assignees")):
                conn.executemany("INSERT INTO task_people (task, person, role) VALUES (?, ?, ?)", [(t["id"], p, role) for p in t.get(key, [])])
            conn.executemany("INSERT INTO task_labels (task, label) SELECT ?, id FROM labels WHERE name = ?",
                             [(t["id"], name) for name in t.get("labels", [])])
        conn.executemany("INSERT INTO task_parents (child, parent) VALUES (?, ?)", [tuple(link) for link in data["links"]])
        for c in data["captures"]:
            first_doc = docs[c["docs"][0]]["name"] if c.get("docs") else None
            source = _SOURCES[c["kind"]]
            captures.add_capture(
                conn, capture_id=c["id"], saved=_time(c["at"]), source=source, types=[_TYPES[k] for k in c["types"]],
                title=capture_title(source, c["content"], first_doc, c["id"]), task=c.get("task"), created_task=c.get("created"),
                summary=c.get("summary"), summary_type=c.get("summaryType"), filed_to=c.get("filedTo"), filed=_time(c.get("filedAt")),
                edited=_time(c.get("edited")),
            )
        for d in data["documents"]:
            captures.add_document(conn, document_id=d["id"], name=d["name"], description=d.get("desc"), original=d.get("original"),
                                  capture=d.get("capture"), status=d["status"], checked=_time(d.get("checked")))
        for c in data["captures"]:
            for doc_id in c.get("docs", []):
                captures.link_document(conn, c["id"], doc_id, save_a_copy=doc_id in c.get("copies", []), extract=doc_id in c.get("extract", []))
            for name in c.get("attachments", []):
                captures.add_attachment(conn, c["id"], name)
        for v in data["versions"]:
            captures.add_version(conn, v["doc"], at=_time(v["at"]), difference=v["text"], summary=v.get("summary"), summary_type=v.get("summaryType"))
        for f in data["copies"]:
            captures.add_saved_copy(conn, task=f["task"], name=f["name"], document=f["doc"], from_capture=f.get("from"),
                                    replaced=f.get("replaced"), old=f.get("old", False))
        for a in data["agenda"]:
            item = agenda.add_item(conn, subject=a["subject"], target=a["target"], note=a["note"], added=_time(a["at"]), added_by=a["by"])
            if a.get("closed"):
                agenda.close_item(conn, item, how=a["how"], closed=_time(a["closed"]), closed_by=a["closedBy"])
        # Field changes: those made by captures first, then those made in the browse tool, as the mockup lists them.
        log = [(c["task"], c["at"], field, old, new, c["id"]) for c in data["captures"] for field, old, new in c.get("changes", [])]
        log += [(e["task"], e["at"], e["field"], e["from"], e["to"], e["via"]) for e in data["edits"]]
        conn.executemany("INSERT INTO status_log (task, at, field, from_value, to_value, via) VALUES (?, ?, ?, ?, ?, ?)",
                         [(task, _time(at), field, _none(old), _none(new), via) for task, at, field, old, new, via in log])
        # The notes pages (release 5.25), built from the captures' text as a first run builds them (decision 107).
        from docrepo import notes_page
        from docrepo.stories import Stories

        content = {c["id"]: c["content"] for c in data["captures"]}
        model = Model(conn)
        notes_page.build_all(conn, model, Stories(model, SAMPLE_AS_OF.date(), lambda cid: content.get(cid, "")), SAMPLE_AS_OF)


def write_sample_files(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, data: dict[str, Any] | None = None) -> int:
    """Write the sample captures' capture.md files and the documents' extracted.txt. Returns how many were written.

    The sample's binary files (emails, attachments and saved copies) aren't made.
    """
    data = data or read_sample()
    model = Model(conn)
    for c in data["captures"]:
        captures.write_capture_md(fs, data_root, model, c["id"], c["content"])
    for d in data["documents"]:
        fs.write_text(data_root / "Documents" / d["id"] / "extracted.txt", d["text"])
    return len(data["captures"]) + len(data["documents"])
