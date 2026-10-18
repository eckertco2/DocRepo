"""Backups: database copies in rotating slots, a mirror of the data root's files, and the guard's replace rule."""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime

import pytest

from docrepo import backup, db
from docrepo.cli import main
from docrepo.config import Settings, make_safe_fs
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.safe_fs import SafeFS, WriteRefused

AT = datetime(2026, 10, 18, 9, 0)


@pytest.fixture
def setup(sample_root, tmp_path):
    conn, root, fs = sample_root
    write_pages(Model(conn), root, fs, AT.date(), AT)
    fs.makedirs(root / "Mods")
    settings = Settings(me="P001", backup_dir=str(tmp_path / "Backups"), backup_keep=2)
    return conn, root, settings, tmp_path / "Backups"


def test_a_backup_copies_the_database_and_every_file(setup):
    conn, root, settings, folder = setup
    r = backup.run_backup(root, settings, AT)
    assert r.database == "docs-1.db" and r.copied == r.checked > 40 and not r.problems
    copy = sqlite3.connect(folder / "Database" / "docs-1.db")
    assert copy.execute("SELECT count(*) FROM tasks").fetchone()[0] == conn.execute("SELECT count(*) FROM tasks").fetchone()[0]
    copy.close()
    assert (folder / "Files" / "Contents.md").read_text(encoding="utf-8") == (root / "Contents.md").read_text(encoding="utf-8")
    assert (folder / "Files" / "Config" / "settings.json").exists() is (root / "Config" / "settings.json").exists()
    assert not (folder / "Files" / "System").exists()  # docs.db is copied whole instead; the lock and logs stay
    log = (folder / "backup-log.md").read_text(encoding="utf-8")
    assert log.startswith("# DocRepo backups") and "- 2026-10-18 09:00 · database copy docs-1.db" in log


def test_later_backups_copy_only_what_changed_and_reuse_the_oldest_slot(setup):
    conn, root, settings, folder = setup
    backup.run_backup(root, settings, AT)
    time.sleep(0.05)
    assert backup.run_backup(root, settings, AT).copied == 0
    page = root / "Tasks" / "T000008" / "Task.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    os.utime(page, (time.time() + 5, time.time() + 5))
    third = backup.run_backup(root, settings, AT)
    assert (third.database, third.copied) == ("docs-1.db", 1)  # two slots: the third backup overwrites the oldest
    assert (folder / "Files" / "Tasks" / "T000008" / "Task.md").read_text(encoding="utf-8").endswith("changed\n")
    assert sorted(p.name for p in (folder / "Database").iterdir()) == ["docs-1.db", "docs-2.db"]
    assert (folder / "backup-log.md").read_text(encoding="utf-8").count("\n- ") == 3


def test_nothing_is_removed_from_the_mirror(setup):
    conn, root, settings, folder = setup
    extra = root / "Mods" / "note.md"
    extra.write_text("kept\n", encoding="utf-8")
    backup.run_backup(root, settings, AT)
    extra.rename(root / "Mods" / "moved.md")
    backup.run_backup(root, settings, AT)
    assert (folder / "Files" / "Mods" / "note.md").exists() and (folder / "Files" / "Mods" / "moved.md").exists()


def test_when_a_backup_is_due(setup):
    conn, root, settings, folder = setup
    assert backup.is_due(conn, settings, AT)
    backup.record(conn, backup.run_backup(root, settings, AT))
    assert not backup.is_due(conn, settings, datetime(2026, 10, 24, 9, 0))
    assert backup.is_due(conn, settings, datetime(2026, 10, 25, 8, 0))  # seven days on
    assert not backup.is_due(conn, Settings(), AT)  # no backup folder, no backups


def test_a_backup_folder_inside_the_data_root_is_refused(setup):
    conn, root, settings, folder = setup
    for bad in (str(root / "Backups"), str(root), None, "Backups"):
        with pytest.raises(backup.BackupError):
            backup.run_backup(root, Settings(backup_dir=bad), AT)


def test_replacing_is_allowed_only_in_the_backup_folder(tmp_path):
    root, back = tmp_path / "Data", tmp_path / "Backups"
    root.mkdir()
    back.mkdir()
    src = root / "a.txt"
    src.write_text("one", encoding="utf-8")
    fs = make_safe_fs(root, Settings(backup_dir=str(back)))
    fs.replace_file(src, back / "a.txt")
    src.write_text("two", encoding="utf-8")
    fs.replace_file(src, back / "a.txt")
    assert (back / "a.txt").read_text(encoding="utf-8") == "two"
    with pytest.raises(WriteRefused):
        fs.replace_file(back / "a.txt", root / "a.txt")
    with pytest.raises(WriteRefused):
        make_safe_fs(root, Settings(backup_dir=str(root / "inside"))).replace_file(src, root / "inside" / "a.txt")
    with pytest.raises(ValueError):
        SafeFS([root], replace_roots=[back])  # a replace root must be inside an allowed folder
    with pytest.raises(FileExistsError):
        fs.copy_file(src, back / "a.txt")  # copying still never overwrites


def test_the_backup_command(setup, capsys):
    conn, root, settings, folder = setup
    settings.save(SafeFS([root]), root)
    assert main(["--data-root", str(root), "backup"]) == 0
    assert "Backed up the database (docs-1.db)" in capsys.readouterr().out
    assert db.get_state(conn, backup.STATE_KEY)
    assert main(["--data-root", str(root), "backup"]) == 0
    Settings(me="P001").save(SafeFS([root]), root)
    assert main(["--data-root", str(root), "backup"]) == 1
    assert "No backup folder is set" in capsys.readouterr().err
