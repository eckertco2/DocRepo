"""Migrations (release 5.88, the review of 2026-11-06, F8): a populated docs.db from each schema version that carries
data comes up to date with nothing lost; scripts are split where SQLite says a statement ends; a failed migration
leaves docs.db as it was; an older docs.db is copied to the backup folder first; and a damaged one says so.

``tests/fixtures/roots`` holds a zipped data root (docs.db and settings.json) per version, each made by that version's
own code from the made-up sample (``load-sample`` at the commit named in ``roots.json``), with two made-up key dates
from version 12 on. To add one when the schema changes: check the release out in a worktree, run ``init`` and
``load-sample`` into an empty folder there, and zip its ``System\\docs.db`` and ``Config\\settings.json``."""
from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

from docrepo import db
from docrepo.config import Settings
from docrepo.safe_fs import SafeFS

ROOTS = Path(__file__).resolve().parent / "fixtures" / "roots"
MADE = json.loads((ROOTS / "roots.json").read_text(encoding="utf-8"))
COUNTED = ("tasks", "captures", "task_pages", "task_dates")


def unzip_root(name: str, into: Path) -> Path:
    root = into / f"DocRepoData-{name}"
    with zipfile.ZipFile(ROOTS / f"{name}.zip") as z:
        z.extractall(root)
    return root


def counts(path: Path) -> tuple[int, dict[str, int]]:
    conn = sqlite3.connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return version, {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COUNTED if t in have}  # noqa: S608 - fixed names
    finally:
        conn.close()


def test_every_fixture_is_there_and_older_than_now():
    versions = sorted(int(name[1:]) for name in MADE)
    assert {9, 10, 12, 13, 21} <= set(versions) and max(versions) <= db.SCHEMA_VERSION
    assert sorted(int(p.stem[1:]) for p in ROOTS.glob("v*.zip")) == versions


@pytest.mark.parametrize("name", sorted(MADE, key=lambda n: int(n[1:])))
def test_a_populated_database_comes_up_to_date_whole(name, tmp_path):
    root = unzip_root(name, tmp_path)
    path = root / "System" / "docs.db"
    version, before = counts(path)
    assert version == int(name[1:]) and before == MADE[name]["counts"]
    conn = db.connect(SafeFS([root]), root)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
    _, after = counts(path)
    assert {t: after[t] for t in before} == before  # nothing lost
    assert after.get("task_pages", 0) >= before.get("task_pages", 0) and after.get("task_dates", 0) == before.get("task_dates", 0)
    db.connect(SafeFS([root]), root).close()  # and again, as it is now


def test_a_semicolon_in_a_string_or_a_trigger_doesnt_end_a_statement():
    script = """
-- A comment; with a semicolon in it.
CREATE TABLE notes (id INTEGER PRIMARY KEY, words TEXT NOT NULL);
CREATE TABLE seen (n INTEGER);
INSERT INTO notes (words) VALUES ('crane booked; rigging next');
CREATE TRIGGER notes_seen AFTER INSERT ON notes BEGIN
    INSERT INTO seen (n) VALUES (new.id);
    UPDATE seen SET n = n + 0;
END;
INSERT INTO notes (words) VALUES ('second')
"""
    assert len(list(db.statements(script))) == 5
    conn = sqlite3.connect(":memory:", isolation_level=None)
    with db.transaction(conn):
        db._run(conn, script)
    assert [r[0] for r in conn.execute("SELECT words FROM notes ORDER BY id")] == ["crane booked; rigging next", "second"]
    assert conn.execute("SELECT count(*) FROM seen").fetchone()[0] == 1  # the trigger ran for the second insert
    assert list(db.statements("-- only a comment;\n\n")) == []


def test_every_migration_splits_into_the_statements_it_had():
    """The old split on ";" and the new one agree on every migration so far, since none has a quoted semicolon."""
    for step, script in db.MIGRATIONS.items():
        old = [s for s in script.split(";") if s.strip() and db._has_sql(s)]
        assert len(list(db.statements(script))) == len(old), step


def test_a_failed_migration_leaves_the_database_as_it_was(tmp_path, monkeypatch):
    root = unzip_root("v20", tmp_path)
    path = root / "System" / "docs.db"
    _, before = counts(path)
    monkeypatch.setitem(db.MIGRATIONS, 21, db.MIGRATIONS[21] + "\nCREATE TABLE broken (;\n")
    with pytest.raises(sqlite3.OperationalError):
        db.connect(SafeFS([root]), root)
    version, after = counts(path)
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert version == 20 and after == before and "capture_emails" not in tables  # migration 21's table went with it


def test_an_older_database_is_copied_to_the_backup_folder_first(tmp_path):
    root = unzip_root("v13", tmp_path)
    folder = tmp_path / "Backups"
    fs = SafeFS([root])
    settings = Settings.load(root)
    settings.backup_dir = str(folder)
    settings.save(fs, root)
    db.connect(fs, root).close()
    copy = folder / "Database" / "docs-before-v13.db"
    assert copy.exists() and counts(copy) == (13, MADE["v13"]["counts"])
    assert counts(root / "System" / "docs.db")[0] == db.SCHEMA_VERSION
    db.connect(fs, root).close()  # up to date: no copy is made
    assert sorted(p.name for p in (folder / "Database").iterdir()) == ["docs-before-v13.db"]


def test_with_no_backup_folder_the_upgrade_goes_on(tmp_path, caplog):
    root = unzip_root("v12", tmp_path)
    with caplog.at_level("INFO", logger="docrepo.db"):
        db.connect(SafeFS([root]), root).close()
    assert counts(root / "System" / "docs.db")[0] == db.SCHEMA_VERSION
    assert "no backup folder is set" in caplog.text


def test_a_backup_folder_that_cant_be_used_doesnt_stop_the_upgrade(tmp_path, caplog):
    root = unzip_root("v12", tmp_path)
    fs = SafeFS([root])
    settings = Settings.load(root)
    settings.backup_dir = str(root / "Inside")  # inside the data root: refused by the backup, and the upgrade goes on
    settings.save(fs, root)
    with caplog.at_level("WARNING", logger="docrepo.db"):
        db.connect(fs, root).close()
    assert counts(root / "System" / "docs.db")[0] == db.SCHEMA_VERSION and "no copy of docs.db" in caplog.text
    assert not (root / "Inside").exists()


def test_a_damaged_database_says_so(data_root, fs):
    (data_root / "System").mkdir()
    (data_root / "System" / "docs.db").write_bytes(b"SQLite format 3\x00" + os.urandom(4096))
    with pytest.raises(db.DatabaseError, match="docs.db is damaged; restore it from the backup folder"):
        db.connect(fs, data_root)
    (data_root / "System" / "docs.db").write_bytes(os.urandom(8192))
    with pytest.raises(db.DatabaseError, match="damaged"):
        db.connect(fs, data_root)
