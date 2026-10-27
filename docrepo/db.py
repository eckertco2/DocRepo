"""The database, ``System\\docs.db``: DocRepo's source of truth.

The schema is created here, and its version is kept in SQLite's ``user_version``.
SQLite writes the file itself, so its path goes through ``SafeFS.checked_path``
first. Connections run in autocommit mode; every change is made inside
``transaction()``, so a save either happens completely or not at all.
"""
from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from docrepo.safe_fs import SafeFS

DB_FILE = Path("System") / "docs.db"
SCHEMA_VERSION = 10

#: Each kind of ID: its letter and how many digits follow it.
ID_FORMATS = {"T": 6, "C": 6, "D": 6, "P": 3}

STATES = ("Not started", "In progress", "Parked", "Closed")
RECURRENCES = ("Daily", "Weekly", "Bi-weekly", "Monthly", "Quarterly", "Yearly")

SCHEMA = """
CREATE TABLE people (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    hours_per_week REAL CHECK (hours_per_week IS NULL OR hours_per_week >= 0),
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    added_note     TEXT
);
CREATE TABLE person_aliases (
    person TEXT NOT NULL REFERENCES people(id),
    pos    INTEGER NOT NULL,
    alias  TEXT NOT NULL,
    PRIMARY KEY (person, pos)
);
CREATE TABLE labels (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired'))
);
CREATE TABLE label_keywords (
    label   INTEGER NOT NULL REFERENCES labels(id),
    pos     INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    PRIMARY KEY (label, pos)
);
CREATE TABLE tasks (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL CHECK (title <> ''),
    state          TEXT NOT NULL CHECK (state IN ('Not started', 'In progress', 'Parked', 'Closed')),
    closed         TEXT,
    urgent         INTEGER NOT NULL DEFAULT 0,
    meeting        INTEGER NOT NULL DEFAULT 0,
    recurrence     TEXT CHECK (recurrence IN ('Daily', 'Weekly', 'Bi-weekly', 'Monthly', 'Quarterly', 'Yearly')),
    repeat_until   TEXT,
    start          TEXT,
    due            TEXT,
    deadline       TEXT,
    deadline_desc  TEXT,
    reminder       TEXT,
    lead_hours     REAL CHECK (lead_hours IS NULL OR lead_hours >= 0),
    assignee_hours REAL CHECK (assignee_hours IS NULL OR assignee_hours >= 0),
    inherit_labels INTEGER NOT NULL DEFAULT 1,
    description    TEXT NOT NULL DEFAULT '',
    current_status TEXT NOT NULL DEFAULT '',
    created        TEXT NOT NULL,
    created_by     TEXT NOT NULL,
    CHECK (repeat_until IS NULL OR recurrence IS NOT NULL),
    CHECK ((state = 'Closed') = (closed IS NOT NULL))
);
-- Parent links, oldest first. A task's first link is its first parent.
CREATE TABLE task_parents (
    id     INTEGER PRIMARY KEY,
    child  TEXT NOT NULL REFERENCES tasks(id),
    parent TEXT NOT NULL REFERENCES tasks(id),
    UNIQUE (child, parent),
    CHECK (child <> parent)
);
CREATE TABLE task_people (
    id     INTEGER PRIMARY KEY,
    task   TEXT NOT NULL REFERENCES tasks(id),
    person TEXT NOT NULL REFERENCES people(id),
    role   TEXT NOT NULL CHECK (role IN ('lead', 'assignee')),
    UNIQUE (task, person, role)
);
CREATE TABLE task_labels (
    id    INTEGER PRIMARY KEY,
    task  TEXT NOT NULL REFERENCES tasks(id),
    label INTEGER NOT NULL REFERENCES labels(id),
    UNIQUE (task, label)
);
-- Field changes, as shown in the status log. Values are display text, and NULL shows as "None".
-- via is the capture that made the change, or where it was made (Browse tool, Capture window, Reminders list).
-- (No semicolons in these comments: the schema is split on them.)
CREATE TABLE status_log (
    id         INTEGER PRIMARY KEY,
    task       TEXT NOT NULL REFERENCES tasks(id),
    at         TEXT NOT NULL,
    field      TEXT NOT NULL,
    from_value TEXT,
    to_value   TEXT,
    via        TEXT NOT NULL
);
-- Captures. The content text is in the capture's capture.md, and the title is how it's listed.
CREATE TABLE captures (
    id           TEXT PRIMARY KEY,
    saved        TEXT NOT NULL,
    source       TEXT NOT NULL CHECK (source IN ('typed', 'outlook_email', 'file_path')),
    task         TEXT REFERENCES tasks(id),
    types        TEXT NOT NULL,
    created_task TEXT REFERENCES tasks(id),
    filed_to     TEXT REFERENCES tasks(id),
    filed        TEXT,
    title        TEXT NOT NULL,
    summary      TEXT,
    summary_type TEXT,
    edited       TEXT
);
CREATE TABLE documents (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    original    TEXT,
    capture     TEXT REFERENCES captures(id),
    status      TEXT NOT NULL DEFAULT 'Current',
    checked     TEXT,
    CHECK (original IS NOT NULL OR capture IS NOT NULL)
);
CREATE TABLE capture_documents (
    capture     TEXT NOT NULL REFERENCES captures(id),
    document    TEXT NOT NULL REFERENCES documents(id),
    pos         INTEGER NOT NULL,
    save_a_copy INTEGER NOT NULL DEFAULT 0,
    extract     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (capture, document)
);
CREATE TABLE capture_attachments (
    capture TEXT NOT NULL REFERENCES captures(id),
    pos     INTEGER NOT NULL,
    name    TEXT NOT NULL,
    PRIMARY KEY (capture, pos)
);
-- A tracked original that changed. It isn't a capture. It joins the raw text log of its document's tasks.
CREATE TABLE document_versions (
    id           INTEGER PRIMARY KEY,
    document     TEXT NOT NULL REFERENCES documents(id),
    at           TEXT NOT NULL,
    difference   TEXT NOT NULL,
    summary      TEXT,
    summary_type TEXT
);
CREATE TABLE saved_copies (
    id           INTEGER PRIMARY KEY,
    task         TEXT NOT NULL REFERENCES tasks(id),
    name         TEXT NOT NULL,
    document     TEXT NOT NULL REFERENCES documents(id),
    from_capture TEXT REFERENCES captures(id),
    replaced     TEXT,
    old          INTEGER NOT NULL DEFAULT 0
);
-- Agenda items: a task (subject), or a note with no task, on the agenda of a task or a person (target).
CREATE TABLE agenda_items (
    id        INTEGER PRIMARY KEY,
    subject   TEXT REFERENCES tasks(id),
    target    TEXT NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    added     TEXT NOT NULL,
    added_by  TEXT NOT NULL,
    closed    TEXT,
    how       TEXT CHECK (how IN ('Discussed', 'Removed')),
    closed_by TEXT,
    CHECK ((closed IS NULL) = (how IS NULL))
);
-- The capacity calendar: a cache rebuilt from the task fields.
CREATE TABLE work_calendar (
    person TEXT NOT NULL REFERENCES people(id),
    date   TEXT NOT NULL,
    task   TEXT NOT NULL REFERENCES tasks(id),
    hours  REAL NOT NULL,
    PRIMARY KEY (person, date, task)
);
CREATE INDEX work_calendar_by_date ON work_calendar(date);
CREATE INDEX work_calendar_by_task ON work_calendar(task);
CREATE TABLE id_counters (
    prefix TEXT PRIMARY KEY,
    last   INTEGER NOT NULL
);
"""

#: Changes from one schema version to the next. Version 2 (phase 3): how each document's text was pulled out, and its
#: size, modified time and checksum for the document checks; the app's daily state; reminders already shown.
#: Version 3 (phase 4): the search index. Version 4 (release 5.3): discarded tasks and captures, and agenda items closed
#: as Done (the Today list). Version 5 (release 5.4): each email capture's email layer 0 line.
MIGRATIONS = {
    2: """
ALTER TABLE documents ADD COLUMN text_status TEXT;
ALTER TABLE documents ADD COLUMN text_chars INTEGER;
ALTER TABLE documents ADD COLUMN text_note TEXT;
ALTER TABLE documents ADD COLUMN size INTEGER;
ALTER TABLE documents ADD COLUMN modified TEXT;
ALTER TABLE documents ADD COLUMN sha256 TEXT;
CREATE TABLE app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE reminders_shown (
    task     TEXT NOT NULL REFERENCES tasks(id),
    reminder TEXT NOT NULL,
    shown    TEXT NOT NULL,
    PRIMARY KEY (task, reminder)
);
""",
    3: """
-- The search index: a cache of each capture's and document's text, from its capture.md or extracted.txt.
-- It can be rebuilt at any time (the rebuild command).
CREATE TABLE search_text (
    kind TEXT NOT NULL CHECK (kind IN ('capture', 'document')),
    id   TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
""",
    4: """
-- Discard (mods log round 1, M0021): a task or capture made by mistake is hidden, never deleted.
-- discarded is when, and discard_reason why. Bringing it back clears both.
ALTER TABLE tasks ADD COLUMN discarded TEXT;
ALTER TABLE tasks ADD COLUMN discard_reason TEXT;
ALTER TABLE captures ADD COLUMN discarded TEXT;
ALTER TABLE captures ADD COLUMN discard_reason TEXT;
-- Today (mods log round 1, M0016): the built-in agenda target today, whose items close as Done.
-- SQLite can't change a CHECK, so agenda_items is made again with Done allowed, keeping its rows and IDs.
CREATE TABLE agenda_items_new (
    id        INTEGER PRIMARY KEY,
    subject   TEXT REFERENCES tasks(id),
    target    TEXT NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    added     TEXT NOT NULL,
    added_by  TEXT NOT NULL,
    closed    TEXT,
    how       TEXT CHECK (how IN ('Discussed', 'Removed', 'Done')),
    closed_by TEXT,
    CHECK ((closed IS NULL) = (how IS NULL))
);
INSERT INTO agenda_items_new (id, subject, target, note, added, added_by, closed, how, closed_by)
    SELECT id, subject, target, note, added, added_by, closed, how, closed_by FROM agenda_items;
DROP TABLE agenda_items;
ALTER TABLE agenda_items_new RENAME TO agenda_items;
""",
    5: """
-- Email layer 0 (mods log round 1, M0024): what it kept from an email and what it left out, in words.
ALTER TABLE captures ADD COLUMN email_layer_0 TEXT;
""",
    6: """
-- Formatted content text (mods log round 2, M0045): the capture's content text in capture.md is markup (docrepo/markup.py).
ALTER TABLE captures ADD COLUMN formatted INTEGER NOT NULL DEFAULT 0;
""",
    7: """
-- Items and meeting notes (mods log round 2, M0048 phase 2, M0052, release 5.8): an item's notes and what it is (task,
-- note, update or decision, or "notes" for a meeting's notes), and the meeting the notes made.
ALTER TABLE captures ADD COLUMN from_notes TEXT REFERENCES captures(id);
ALTER TABLE captures ADD COLUMN item TEXT;
ALTER TABLE captures ADD COLUMN meeting TEXT REFERENCES tasks(id);
""",
    8: """
-- People, labels and task fields (mods log round 2, M0028, M0031, M0033, M0034, M0038, M0051, release 5.9): a person's
-- email, group and role, a label's parent label, a task's Plant event tick, and its reference fields, named in Settings.
ALTER TABLE people ADD COLUMN email TEXT;
ALTER TABLE people ADD COLUMN person_group TEXT;
ALTER TABLE people ADD COLUMN role TEXT;
ALTER TABLE labels ADD COLUMN parent INTEGER REFERENCES labels(id);
ALTER TABLE tasks ADD COLUMN plant_event INTEGER NOT NULL DEFAULT 0;
CREATE TABLE task_references (
    task  TEXT NOT NULL REFERENCES tasks(id),
    name  TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (task, name)
);
""",
    9: """
-- Priorities (mods log round 2, M0029, M0030, decision 23, release 5.23): a task's bucket, and its place in the bucket.
ALTER TABLE tasks ADD COLUMN priority TEXT CHECK (priority IN ('critical', 'high', 'medium', 'parking'));
ALTER TABLE tasks ADD COLUMN priority_rank INTEGER;
""",
    10: """
-- The notes page (release 5.25, the notes page plan's decisions 95 to 120): each task's notes as one page of markup
-- (docrepo/notes_page.py), and the page as it stood at the end of each day it changed (at, its last change), by_owner when
-- the owner edited it.
-- day_headings is whether new captures go under a heading for their day: NULL is the default, on for a meeting.
CREATE TABLE task_pages (
    task    TEXT PRIMARY KEY REFERENCES tasks(id),
    body    TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE task_page_versions (
    task     TEXT NOT NULL REFERENCES tasks(id),
    day      TEXT NOT NULL,
    body     TEXT NOT NULL,
    by_owner INTEGER NOT NULL DEFAULT 0,
    at       TEXT NOT NULL,
    PRIMARY KEY (task, day)
);
ALTER TABLE tasks ADD COLUMN day_headings INTEGER;
-- The search index learns pages. It's a cache, so it's made again and rebuilt (search.needs_rebuild).
DROP TABLE search_text;
CREATE TABLE search_text (
    kind TEXT NOT NULL CHECK (kind IN ('capture', 'document', 'page')),
    id   TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
""",
}


class DatabaseError(Exception):
    """docs.db can't be used: it's from a newer DocRepo, or isn't a DocRepo database."""


def db_path(data_root: Path) -> Path:
    return data_root / DB_FILE


def connect(fs: SafeFS, data_root: Path) -> sqlite3.Connection:
    """Open docs.db, creating it with the current schema if it doesn't exist yet."""
    path = fs.checked_path(db_path(data_root))
    fs.makedirs(path.parent)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _ensure_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def connect_memory() -> sqlite3.Connection:
    """An empty in-memory database with the schema, for tests."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    return conn


def _run(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the schema in a new database, or bring an older DocRepo database up to date."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version > SCHEMA_VERSION:
        raise DatabaseError(f"docs.db was made by a newer DocRepo (schema {version}). Update DocRepo before using it.")
    if version == 0 and conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
        raise DatabaseError("docs.db holds tables but no DocRepo schema version, so it isn't a DocRepo database.")
    with transaction(conn):
        if version == 0:
            _run(conn, SCHEMA)
            version = 1
        for step in range(version + 1, SCHEMA_VERSION + 1):
            _run(conn, MIGRATIONS[step])
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    """A value the app keeps between runs, such as the day it last did its daily work."""
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the block as one transaction: committed if it finishes, rolled back if it raises.

    Nested use joins the outer transaction.
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def format_id(prefix: str, number: int) -> str:
    return f"{prefix}{number:0{ID_FORMATS[prefix]}d}"


def next_id(conn: sqlite3.Connection, prefix: str) -> str:
    """The next unused ID of a kind, such as T000020. IDs are never reused."""
    with transaction(conn):
        conn.execute("INSERT OR IGNORE INTO id_counters (prefix, last) VALUES (?, 0)", (prefix,))
        conn.execute("UPDATE id_counters SET last = last + 1 WHERE prefix = ?", (prefix,))
        number = conn.execute("SELECT last FROM id_counters WHERE prefix = ?", (prefix,)).fetchone()[0]
    return format_id(prefix, number)


def note_used_id(conn: sqlite3.Connection, item_id: str) -> None:
    """Record that an ID is taken, so next_id never hands it out. Used when importing records with their IDs."""
    prefix, number = item_id[0], int(item_id[1:])
    with transaction(conn):
        conn.execute("INSERT OR IGNORE INTO id_counters (prefix, last) VALUES (?, 0)", (prefix,))
        conn.execute("UPDATE id_counters SET last = max(last, ?) WHERE prefix = ?", (number, prefix))
