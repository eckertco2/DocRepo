"""The dump (release 5.102): every table of docs.db as JSON in System\\export\\<date>, read through a read-only connection,
written through SafeFS, and the database left as it was."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime

import pytest

from docrepo import db
from docrepo.cli import main
from docrepo.dump import INDEX_FILE, dump, dump_folder, read_tables
from docrepo.safe_fs import SafeFS, WriteRefused

AT = datetime(2026, 10, 8, 9, 30)


def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_table_is_dumped_with_its_rows(sample_root):
    conn, root, fs = sample_root
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite%' ORDER BY name")]
    result = dump(root, fs, AT)
    assert result.folder == root / "System" / "export" / "2026-10-08" == dump_folder(root, AT)
    assert sorted(p.name for p in result.folder.iterdir()) == sorted([INDEX_FILE, *(f"{t}.json" for t in tables)])
    for t in tables:
        data = json.loads((result.folder / f"{t}.json").read_text(encoding="utf-8"))
        assert data["table"] == t
        assert len(data["rows"]) == result.tables[t] == conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608 - the test's own table names
    assert {"templates", "task_ties", "task_pins", "document_uses", "task_page_versions", "label_keywords", "task_references"} <= set(tables)
    people = json.loads((result.folder / "people.json").read_text(encoding="utf-8"))
    assert people["columns"] == [r["name"] for r in conn.execute("PRAGMA table_info(people)")]
    assert people["rows"] == [dict(r) for r in conn.execute("SELECT * FROM people")]
    index = json.loads((result.folder / INDEX_FILE).read_text(encoding="utf-8"))
    assert index["made"] == "2026-10-08 09:30:00" and index["schema_version"] == db.SCHEMA_VERSION
    assert index["made_by"].startswith("DocRepo ") and index["tables"] == result.tables
    assert result.rows == sum(result.tables.values()) > 0


def test_the_database_is_left_as_it_was(sample_root):
    conn, root, fs = sample_root
    before = digest(db.db_path(root))
    dump(root, fs, AT)
    assert digest(db.db_path(root)) == before


def test_a_second_dump_on_one_day_replaces_the_first(sample_root):
    conn, root, fs = sample_root
    dump(root, fs, AT)
    conn.execute("INSERT INTO people (id, name) VALUES ('P900', 'Sam Example')")
    result = dump(root, fs, AT.replace(hour=11))
    rows = json.loads((result.folder / "people.json").read_text(encoding="utf-8"))["rows"]
    assert any(r["name"] == "Sam Example" for r in rows)
    assert len(list((root / "System" / "export").iterdir())) == 1


def test_the_dump_writes_only_through_safe_fs(sample_root, tmp_path):
    _conn, root, _fs = sample_root
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(WriteRefused):
        dump(root, SafeFS([elsewhere]), AT)


def test_the_tables_are_read_in_one_transaction(sample_root):
    _conn, root, _fs = sample_root
    reader = db.connect_read_only(root)
    reader.isolation_level = None
    try:
        tables = read_tables(reader)
        assert not reader.in_transaction
    finally:
        reader.close()
    assert tables["tasks"]["columns"][0] == "id"


def test_the_command_dumps_without_upgrading(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "load-sample"]) == 0
    old = db.SCHEMA_VERSION - 1
    raw = sqlite3.connect(db.db_path(root))
    raw.execute(f"PRAGMA user_version = {old}")
    raw.close()
    before = {p: digest(p) for p in root.rglob("*") if p.is_file() and "logs" not in p.parts}
    capsys.readouterr()
    assert main(["--data-root", str(root), "dump"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Dumped ") and "export" in out
    after = {p: digest(p) for p in root.rglob("*") if p.is_file() and "logs" not in p.parts}
    made = set(after) - set(before)
    assert {k: v for k, v in after.items() if k in before} == before  # docs.db wasn't upgraded or changed, nor anything else
    assert made and all(p.parent.parent == root / "System" / "export" for p in made)
    index = json.loads(next(p for p in made if p.name == INDEX_FILE).read_text(encoding="utf-8"))
    assert index["schema_version"] == old


def test_the_command_needs_a_data_root_that_is_set_up(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "dump"]) == 1
    assert "isn't set up yet" in capsys.readouterr().err
    assert not root.exists()
