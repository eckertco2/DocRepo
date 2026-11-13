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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 26
        assert conn.execute("SELECT count(*) FROM capture_emails").fetchone()[0] == 0  # version 21 (release 5.74): no rows for older emails
        assert conn.execute("SELECT count(*) FROM tagged_labels").fetchone()[0] == 0  # version 22 (release 5.79): no glossary yet
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
        assert conn.execute("SELECT count(*) FROM task_pages").fetchone()[0] == 0  # version 10: pages are built after
        assert conn.execute("SELECT count(*) FROM tasks WHERE day_headings IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM task_dates").fetchone()[0] == 0  # version 12: key dates
        assert conn.execute("SELECT count(*) FROM document_uses").fetchone()[0] == 0  # version 13: the Task view's uses and pins
        assert conn.execute("SELECT count(*) FROM task_pins").fetchone()[0] == 0
        for table in ("templates", "template_rows", "template_row_people", "template_row_labels", "task_template", "task_links"):  # version 14
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0  # noqa: S608 - a column or table name of DocRepo's own; values are parameters
        assert conn.execute("SELECT count(*) FROM template_log").fetchone()[0] == 0  # version 15
        assert conn.execute("SELECT count(*) FROM tasks WHERE duration IS NOT NULL OR calendar_days <> 0 OR lead_per_day IS NOT NULL").fetchone()[0] == 0  # version 16
        assert conn.execute("SELECT count(*) FROM task_people WHERE involvement <> 100").fetchone()[0] == 0  # version 17
        assert conn.execute("SELECT count(*) FROM tasks WHERE lead_per_week IS NOT NULL OR assignee_per_week IS NOT NULL").fetchone()[0] == 0  # version 18
        assert conn.execute("SELECT count(*) FROM task_ties").fetchone()[0] == 0  # version 19
        assert conn.execute("SELECT count(*) FROM template_row_ties").fetchone()[0] == 0  # version 20
        assert conn.execute("SELECT count(*) FROM templates WHERE anchor_row IS NOT NULL").fetchone()[0] == 0
        conn.execute("INSERT INTO search_text (kind, id, body) VALUES ('page', 'T000001', 'x')")  # pages are searched
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


# ---- release 5.102: a busy timeout, a read-only connection and checked names ----
def test_a_connection_waits_for_a_busy_database(data_root, fs):
    conn = db.connect(fs, data_root)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == int(db.BUSY_TIMEOUT * 1000) == 30000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"  # not WAL: the data root may be in a synced folder
    finally:
        conn.close()


def test_a_save_made_while_a_backup_reads_waits_and_then_succeeds(data_root, fs):
    """A backup's copy holds docs.db with a read lock for as long as it takes. A save made then waits for it, rather
    than failing after Python's default five seconds."""
    import threading
    import time

    conn = db.connect(fs, data_root)
    locked = threading.Event()

    def backup_reading() -> None:
        reader = db.connect_read_only(data_root)
        reader.isolation_level = None
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM tasks").fetchone()  # the read lock a copy holds
        locked.set()
        time.sleep(1.0)
        reader.execute("COMMIT")
        reader.close()

    thread = threading.Thread(target=backup_reading)
    thread.start()
    try:
        assert locked.wait(10)
        started = time.monotonic()
        with db.transaction(conn):
            conn.execute("INSERT INTO people (id, name) VALUES ('P001', 'Me')")
        assert time.monotonic() - started >= 0.5  # it waited for the reader
        assert conn.execute("SELECT name FROM people").fetchone()[0] == "Me"
    finally:
        thread.join()
        conn.close()

def test_the_read_only_connection_changes_nothing(data_root, fs):
    with pytest.raises(sqlite3.OperationalError):
        db.connect_read_only(data_root).execute("SELECT 1 FROM tasks")  # no docs.db yet, and none is made
    assert not db.db_path(data_root).exists()
    db.connect(fs, data_root).close()
    reader = db.connect_read_only(data_root)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.execute("INSERT INTO people (id, name) VALUES ('P001', 'Me')")
    finally:
        reader.close()


def test_names_outside_the_allow_list_are_refused():
    db.check_names("tasks", ("tasks", "people"))
    db.check_names(["title", "due"], ("title", "due", "start"))
    with pytest.raises(ValueError, match="'tasks; DROP TABLE people'"):
        db.check_names("tasks; DROP TABLE people", ("tasks", "people"))
    with pytest.raises(ValueError, match="'nope'"):
        db.check_names({"title": 1, "nope": 2}, ("title",))


def test_the_task_columns_are_the_tasks_tables():
    from docrepo.model import TASK_COLUMNS

    conn = db.connect_memory()
    assert sorted(TASK_COLUMNS) == sorted(r["name"] for r in conn.execute("PRAGMA table_info(tasks)"))


def test_the_helpers_that_build_sql_refuse_other_names(sample_conn):
    from datetime import datetime

    from docrepo import agenda, people, tasks

    with pytest.raises(ValueError, match="DocRepo builds SQL with"):
        agenda._exists(sample_conn, "captures", "C000001")
    with pytest.raises(ValueError, match="DocRepo builds SQL with"):
        people._set_list(sample_conn, "people", "id", "P001", "name", ["x"])
    with pytest.raises(ValueError, match="DocRepo builds SQL with"):
        people._set_list(sample_conn, "person_aliases", "person", "P001", "name", ["x"])
    with pytest.raises(ValueError, match="DocRepo builds SQL with"):
        tasks._apply_columns(sample_conn, "T000001", {"title": "x", "title = 'y' --": "z"})
    with pytest.raises(ValueError, match="DocRepo builds SQL with"):
        tasks._end_ties(sample_conn, "task", "T000001", datetime(2026, 10, 8, 9, 0), "test")
    assert agenda._exists(sample_conn, "people", "P001")
