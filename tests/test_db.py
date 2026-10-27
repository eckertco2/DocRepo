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


def test_a_version_1_database_is_brought_up_to_date(data_root, fs):
    (data_root / "System").mkdir()
    old = sqlite3.connect(data_root / "System" / "docs.db")
    old.executescript(db.SCHEMA)
    old.execute("INSERT INTO documents (id, name, original) VALUES ('D000001', 'a.pdf', 'C:\\a.pdf')")
    old.execute("INSERT INTO people (id, name) VALUES ('P001', 'Me')")
    old.execute("INSERT INTO agenda_items (id, subject, target, note, added, added_by) VALUES (7, NULL, 'P001', 'Ask about it', '2026-10-01 09:00', 'C000001')")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()
    conn = db.connect(fs, data_root)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
        assert conn.execute("SELECT name, sha256, text_status FROM documents").fetchone()[:] == ("a.pdf", None, None)
        assert conn.execute("SELECT count(*) FROM search_text").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM tasks WHERE discarded IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM captures WHERE email_layer_0 IS NOT NULL").fetchone()[0] == 0  # version 5
        assert conn.execute("SELECT count(*) FROM captures WHERE formatted = 1").fetchone()[0] == 0  # version 6
        assert conn.execute("SELECT count(*) FROM captures WHERE from_notes IS NOT NULL OR item IS NOT NULL OR meeting IS NOT NULL").fetchone()[0] == 0  # 7
        assert conn.execute("SELECT count(*) FROM task_references").fetchone()[0] == 0  # version 8
        assert conn.execute("SELECT count(*) FROM tasks WHERE plant_event = 1").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM people WHERE email IS NOT NULL OR person_group IS NOT NULL OR role IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM labels WHERE parent IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM tasks WHERE priority IS NOT NULL OR priority_rank IS NOT NULL").fetchone()[0] == 0  # version 9
        # Version 4 made agenda_items again, keeping its rows and IDs, so an item can close as Done.
        assert [tuple(r) for r in conn.execute("SELECT id, target, note FROM agenda_items")] == [(7, "P001", "Ask about it")]
        conn.execute("UPDATE agenda_items SET closed = '2026-10-02 09:00', how = 'Done', closed_by = 'Today' WHERE id = 7")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        db.set_state(conn, "daily", "2026-10-16")
        db.set_state(conn, "daily", "2026-10-17")
        assert db.get_state(conn, "daily") == "2026-10-17" and db.get_state(conn, "other") is None
    finally:
        conn.close()


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
