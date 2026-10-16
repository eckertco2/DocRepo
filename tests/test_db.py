"""docs.db: the schema, its version, transactions and IDs."""
from __future__ import annotations

import sqlite3

import pytest

from docrepo import db
from docrepo.safe_fs import SafeFS, WriteRefused


def test_connect_creates_the_schema(data_root, fs):
    conn = db.connect(fs, data_root)
    try:
        assert (data_root / "System" / "docs.db").exists()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"tasks", "task_parents", "people", "labels", "captures", "agenda_items", "work_calendar", "status_log"} <= tables
    finally:
        conn.close()
    db.connect(fs, data_root).close()  # opening it again keeps it


def test_a_newer_database_is_refused(data_root, fs):
    conn = db.connect(fs, data_root)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(db.DatabaseError, match="newer"):
        db.connect(fs, data_root)


def test_another_programs_database_is_refused(data_root, fs):
    (data_root / "System").mkdir()
    other = sqlite3.connect(data_root / "System" / "docs.db")
    other.execute("CREATE TABLE notes (x)")
    other.close()
    with pytest.raises(db.DatabaseError, match="isn't a DocRepo database"):
        db.connect(fs, data_root)


def test_the_database_must_be_inside_an_allowed_folder(tmp_path):
    with pytest.raises(WriteRefused):
        db.connect(SafeFS([tmp_path / "elsewhere"]), tmp_path / "DocRepoData")


def test_a_failed_transaction_changes_nothing():
    conn = db.connect_memory()
    with pytest.raises(RuntimeError):
        with db.transaction(conn):
            conn.execute("INSERT INTO people (id, name) VALUES ('P001', 'Me')")
            raise RuntimeError("stop")
    assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == 0


def test_ids_count_up_and_skip_used_ones():
    conn = db.connect_memory()
    assert db.next_id(conn, "T") == "T000001"
    assert db.next_id(conn, "P") == "P001"
    db.note_used_id(conn, "T000041")
    assert db.next_id(conn, "T") == "T000042"
    db.note_used_id(conn, "T000005")
    assert db.next_id(conn, "T") == "T000043"


def test_a_closed_task_needs_its_close_date():
    conn = db.connect_memory()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tasks (id, title, state, created, created_by) VALUES ('T000001', 'A', 'Closed', '2026-10-08', 'x')")
