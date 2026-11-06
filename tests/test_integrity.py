"""Data integrity (release 5.89, the review of 2026-11-06, F3): ``check`` finds what docs.db says is there and isn't; a
save whose capture.md can't be written saves nothing; backups are checked, mirror the drafts, and restore."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from docrepo import backup, captures, check, db, drafts, search
from docrepo.cli import main
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.safe_fs import SafeFS
from docrepo.save import CaptureDraft, SaveError, save_capture

AT = datetime(2026, 10, 18, 9, 0)
INSTALLATION = "T000008"


def capture_path(conn, root: Path, capture_id: str) -> Path:
    return captures.capture_md_path(root, Model(conn).captures[capture_id])


# ---- check ----
def test_a_clean_sample_has_only_its_unmade_copies(sample_root):
    conn, root, _ = sample_root
    r = check.run_check(conn, root, AT)
    assert r.database == "ok" and r.counted["captures"] == 24
    assert r.sections["Captures with no capture.md"] == [] and r.sections["The search index"] == []
    assert r.sections["Documents with no extracted text"] == []
    assert len(r.sections["Saved copies that aren't there"]) == 3  # the sample doesn't make its saved copies


def test_a_missing_capture_md_is_named_with_its_draft(sample_root):
    conn, root, fs = sample_root
    c = Model(conn).captures["C000024"]
    gone = captures.capture_md_path(root, c)
    gone.rename(gone.with_name("moved-away.md"))  # a test may move a file; DocRepo never does
    when = datetime.fromisoformat(c.saved.replace("T", " ")[:16])
    drafts.write(fs, root, "kept", {"content": "Its words", "saved": when.replace(minute=max(0, when.minute - 3)).isoformat()})
    fs.move(root / drafts.DRAFTS_DIR / "kept", root / drafts.DONE_DIR / "2026-10-08 093000")
    r = check.run_check(conn, root, AT)
    lost = r.sections["Captures with no capture.md"]
    assert len(lost) == 1 and lost[0].what.startswith("C000024 (") and "is missing" in lost[0].what
    assert "System\\Drafts\\Done\\2026-10-08 093000" in lost[0].todo
    stale = [f.what for f in r.sections["The search index"]]
    assert stale == ["C000024: its search entry is out of date."]  # its words are gone from what it would index now
    text = r.markdown()
    assert "## Captures with no capture.md" in text and "Nothing was changed." in text


def test_a_missing_extracted_text_and_search_entry_are_found(sample_root):
    conn, root, _ = sample_root
    doc = next(d for d in Model(conn).documents.values() if (root / "Documents" / d.id / "extracted.txt").exists())
    conn.execute("UPDATE documents SET text_status = 'ok' WHERE id = ?", (doc.id,))
    (root / "Documents" / doc.id / "extracted.txt").rename(root / "Documents" / doc.id / "away.txt")
    conn.execute("DELETE FROM search_text WHERE kind = 'capture' AND id = 'C000001'")
    r = check.run_check(conn, root, AT)
    assert [f.what.split(":")[0] for f in r.sections["Documents with no extracted text"]] == [f"{doc.id} ({doc.name})"]
    assert "C000001: not in the search index." in [f.what for f in r.sections["The search index"]]
    search.rebuild(conn, root)
    after = check.run_check(conn, root, AT)
    assert [f.what for f in after.sections["The search index"]] == []


def test_the_check_command_keeps_its_list(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "load-sample"]) == 0
    capsys.readouterr()
    assert main(["--data-root", str(root), "check"]) == 2  # the sample's saved copies aren't made
    out = capsys.readouterr().out
    kept = next(root.glob("System/check-*.md"))
    assert out.startswith("# Data root check") and kept.read_text(encoding="utf-8") in out


# ---- capture.md before the commit ----
def test_a_save_whose_capture_md_cant_be_written_saves_nothing(sample_root, monkeypatch):
    conn, root, fs = sample_root
    before = conn.execute("SELECT count(*) FROM captures").fetchone()[0]
    counter = conn.execute("SELECT last FROM id_counters WHERE prefix = 'C'").fetchone()[0]
    page = conn.execute("SELECT body FROM task_pages WHERE task = ?", (INSTALLATION,)).fetchone()[0]
    real = SafeFS.write_text

    def refuse(self, path, text):
        if Path(path).name == "capture.md":
            raise PermissionError("the drive refused")
        return real(self, path, text)

    monkeypatch.setattr(SafeFS, "write_text", refuse)
    draft = CaptureDraft(content="Crane booked for Tuesday.\n**task, Book the rigging crew", task=INSTALLATION, types={"note"},
                         files=[])
    with pytest.raises(SaveError, match="capture.md couldn't be written \\(PermissionError\\), so nothing was saved"):
        save_capture(conn, root, fs, Settings(me="P001"), draft, AT)
    assert conn.execute("SELECT count(*) FROM captures").fetchone()[0] == before
    assert conn.execute("SELECT last FROM id_counters WHERE prefix = 'C'").fetchone()[0] == counter  # the ID isn't used up
    assert not conn.in_transaction and not conn.execute("SELECT count(*) FROM tasks WHERE title = 'Book the rigging crew'").fetchone()[0]
    assert conn.execute("SELECT body FROM task_pages WHERE task = ?", (INSTALLATION,)).fetchone()[0] == page  # nor its note
    monkeypatch.setattr(SafeFS, "write_text", real)
    saved = save_capture(conn, root, fs, Settings(me="P001"), draft, AT)  # and it saves once the drive is back
    assert saved.noted_on == INSTALLATION and saved.items == ["C000026"]  # a note alone on a task is no capture (5.69); its item is
    assert capture_path(conn, root, "C000026").exists()


# ---- backups ----
@pytest.fixture
def backed(sample_root, tmp_path):
    conn, root, fs = sample_root
    write_pages(Model(conn), root, fs, AT.date(), AT)
    settings = Settings(me="P001", backup_dir=str(tmp_path / "Backups"), backup_keep=2)
    settings.save(fs, root)  # a data root always has its settings, and the backup mirrors them
    return conn, root, fs, settings, tmp_path / "Backups"


def test_a_backup_is_checked_and_says_so(backed):
    conn, root, _, settings, folder = backed
    r = backup.run_backup(root, settings, AT)
    backup.record(conn, r)
    assert r.database == "docs-1.db" and "checked" in r.message()
    assert "database copy docs-1.db, checked" in (folder / "backup-log.md").read_text(encoding="utf-8")
    assert backup.last_problem(conn) is None and backup.last_backup(conn)


def test_a_copy_that_fails_its_check_isnt_kept(backed, monkeypatch):
    conn, root, _, settings, folder = backed
    first = backup.run_backup(root, settings, AT)
    backup.record(conn, first)
    good = (folder / "Database" / "docs-1.db").read_bytes()
    monkeypatch.setattr(backup, "quick_check", lambda conn: "row 3 missing from index tasks_parent")
    second = backup.run_backup(root, settings, datetime(2026, 10, 25, 9, 0))
    backup.record(conn, second)
    assert second.database == "" and "failed SQLite's check" in second.problems[0] and "wasn't kept" in second.message()
    assert sorted(p.name for p in (folder / "Database").glob("docs-*.db")) == ["docs-1.db"]  # no new slot taken
    assert (folder / "Database" / "docs-1.db").read_bytes() == good
    assert "database copy not kept: it failed SQLite's check" in (folder / "backup-log.md").read_text(encoding="utf-8")
    assert backup.last_backup(conn) == first.at  # so the next start tries again
    at, what = backup.last_problem(conn)
    assert at == "2026-10-25 09:00" and "failed SQLite's check" in what
    backup.record(conn, backup.run_backup(root, settings, datetime(2026, 10, 25, 10, 0)))  # an ordinary failure goes...
    monkeypatch.undo()
    backup.record(conn, backup.run_backup(root, settings, datetime(2026, 10, 25, 11, 0)))
    assert backup.last_problem(conn) is None  # ...when a good copy is made


def test_a_backup_holds_the_drafts(backed):
    conn, root, fs, settings, folder = backed
    drafts.write(fs, root, "2026-10-18 085000", {"content": "Half a note", "saved": "2026-10-18T08:50:00"})
    fs.write_copy(drafts.folder(root, "2026-10-18 085000") / "emails" / "email.msg", b"made-up msg bytes")
    backup.run_backup(root, settings, AT)
    mirrored = folder / "Files" / "System" / "Drafts" / "2026-10-18 085000"
    assert json.loads((mirrored / "draft.json").read_text(encoding="utf-8"))["content"] == "Half a note"
    assert (mirrored / "emails" / "email.msg").read_bytes() == b"made-up msg bytes"
    assert sorted(p.name for p in (folder / "Files" / "System").iterdir()) == ["Drafts"]  # not the logs or docs.db


def test_a_backup_restores(backed, tmp_path):
    """The round trip the backup log describes: a new folder from Files, the newest database copy as docs.db, rebuild."""
    conn, root, _, settings, folder = backed
    page_before = conn.execute("SELECT body FROM task_pages WHERE task = ?", (INSTALLATION,)).fetchone()[0]
    counts = [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("tasks", "captures")]  # noqa: S608 - fixed names
    backup.record(conn, backup.run_backup(root, settings, AT))
    restored = tmp_path / "Restored"
    fs = SafeFS([restored])
    fs.makedirs(restored)
    for f in (folder / "Files").rglob("*"):
        if f.is_file():
            fs.copy_file(f, restored / f.relative_to(folder / "Files"))
    fs.makedirs(restored / "System")
    fs.copy_file(folder / "Database" / "docs-1.db", restored / "System" / "docs.db")
    assert main(["--data-root", str(restored), "rebuild", "--as-of", "2026-10-18 09:00"]) == 0
    again = db.connect(fs, restored)
    try:
        assert [again.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("tasks", "captures")] == counts  # noqa: S608
        assert again.execute("SELECT body FROM task_pages WHERE task = ?", (INSTALLATION,)).fetchone()[0] == page_before
        assert check.run_check(again, restored, AT).sections["Captures with no capture.md"] == []
    finally:
        again.close()
    assert sqlite3.connect(restored / "System" / "docs.db").execute("PRAGMA quick_check").fetchone()[0] == "ok"
