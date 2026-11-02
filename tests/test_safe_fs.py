"""The guarded write module: everything stays inside DocRepo's folders."""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import pytest

from docrepo import safe_fs
from docrepo.safe_fs import SafeFS, WriteRefused, path_problem


def make_junction(link: Path, target: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    winapi.CreateJunction(str(target), str(link))


def test_writes_inside_the_root(fs, data_root):
    target = fs.write_text(data_root / "Config" / "settings.json", '{"a": 1}\n')
    assert target.read_text(encoding="utf-8") == '{"a": 1}\n'


def test_rewrites_replace_the_file_and_leave_no_temporary_files(fs, data_root):
    note = data_root / "note.md"
    fs.write_text(note, "first")
    fs.write_text(note, "second")
    assert note.read_text(encoding="utf-8") == "second"
    assert [p.name for p in data_root.iterdir()] == ["note.md"]


def test_writes_utf8_and_keeps_line_endings(fs, data_root):
    note = fs.write_text(data_root / "note.md", "café\nline\r\n")
    assert note.read_bytes() == "café\nline\r\n".encode("utf-8")


@pytest.mark.parametrize("name", ["outside.md", "DocRepoData2/note.md"])
def test_refuses_paths_outside_the_root(fs, data_root, name):
    with pytest.raises(WriteRefused):
        fs.write_text(data_root.parent / name, "x")


def test_refuses_dot_dot_escapes(fs, data_root):
    with pytest.raises(WriteRefused):
        fs.write_text(data_root / ".." / "escaped.md", "x")
    assert not (data_root.parent / "escaped.md").exists()


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("relative\\note.md", "full path"),
        ("\\no-drive\\note.md", "full path"),
        ("\\\\?\\C:\\x\\note.md", "device"),
        ("\\\\.\\C:\\x\\note.md", "device"),
        ("C:\\x\\note.md:hidden", "alternate data streams"),
        ("C:\\x\\NUL", "reserves"),
        ("C:\\x\\con.md", "reserves"),
        ("C:\\x\\COM1.txt", "reserves"),
        ("C:\\x\\name.\\note.md", "dot or a space"),
        ("C:\\x\\name \\note.md", "dot or a space"),
        ("C:\\x\\a|b.md", "character"),
    ],
)
def test_spots_paths_windows_treats_specially(raw, fragment):
    assert fragment in (path_problem(raw) or "")


def test_ordinary_paths_are_fine():
    assert path_problem("C:\\Users\\someone\\DocRepoData\\Tasks\\T000001\\Task.md") is None
    assert path_problem("\\\\server\\share\\folder\\file.md") is None
    assert path_problem("C:/Users/someone/DocRepoData/Contents.md") is None


@pytest.mark.parametrize("name", ["tool.exe", "script.py", "report.docx", "no-extension"])
def test_refuses_kinds_of_file_docrepo_never_writes(fs, data_root, name):
    with pytest.raises(WriteRefused):
        fs.write_text(data_root / name, "x")


def test_creates_folders_only_inside(fs, data_root):
    assert fs.makedirs(data_root / "Tasks" / "T000001").is_dir()
    with pytest.raises(WriteRefused):
        fs.makedirs(data_root.parent / "elsewhere")
    assert not (data_root.parent / "elsewhere").exists()


def test_refuses_writes_through_a_junction_that_leads_outside(fs, data_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    make_junction(data_root / "sneaky", outside)
    with pytest.raises(WriteRefused):
        fs.write_text(data_root / "sneaky" / "note.md", "x")
    assert not any(outside.iterdir())


def test_allows_a_junction_that_stays_inside(fs, data_root):
    real = data_root / "real"
    real.mkdir()
    make_junction(data_root / "alias", real)
    fs.write_text(data_root / "alias" / "note.md", "x")
    assert (real / "note.md").exists()


def test_refuses_writes_through_a_symlink_that_leads_outside(fs, data_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, data_root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account can't create symlinks.")
    with pytest.raises(WriteRefused):
        fs.write_text(data_root / "link" / "note.md", "x")


def test_copies_only_read_the_source_and_never_overwrite(fs, data_root, tmp_path):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"%PDF sample")
    digest, mtime = hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns
    copy = fs.copy_file(original, data_root / "Tasks" / "T000001" / "Files" / "2026-10-08 Original.pdf")
    assert copy.read_bytes() == b"%PDF sample"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    assert original.stat().st_mtime_ns == mtime
    with pytest.raises(FileExistsError):
        fs.copy_file(original, copy)


def test_refuses_copies_to_outside(fs, tmp_path):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"x")
    with pytest.raises(WriteRefused):
        fs.copy_file(original, tmp_path / "copy.pdf")


def test_moves_only_within_the_roots(fs, data_root, tmp_path):
    old = fs.write_text(data_root / "Files" / "a.md", "x")
    moved = fs.move(old, data_root / "Files" / "_old versions" / "a.md")
    assert moved.exists() and not old.exists()
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(WriteRefused):
        fs.move(outside, data_root / "in.md")
    with pytest.raises(WriteRefused):
        fs.move(moved, tmp_path / "out.md")
    assert outside.exists() and moved.exists()


def test_allows_every_root_given(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fs = SafeFS([a, b])
    fs.write_text(a / "x.md", "1")
    fs.write_text(b / "y.md", "2")
    with pytest.raises(WriteRefused):
        fs.write_text(tmp_path / "c" / "z.md", "3")


def test_has_no_way_to_delete():
    for name in ("delete", "remove", "unlink", "rmtree", "rmdir"):
        assert not hasattr(SafeFS, name)


def test_logs_refusals(fs, data_root, caplog):
    with caplog.at_level(logging.WARNING, logger="docrepo.safe_fs"), pytest.raises(WriteRefused):
        fs.write_text(data_root.parent / "outside.md", "x")
    assert "Write refused" in caplog.text


def test_rejects_unusable_roots():
    with pytest.raises(ValueError):
        SafeFS(["relative"])
    with pytest.raises(ValueError):
        SafeFS([])


# ---- a replace waits out a brief refusal (release 5.40.1) ----
def _refused(monkeypatch, times: int, error: type[OSError] = PermissionError) -> list:
    """``os.replace`` refusing the next ``times`` calls, with the waits not really taken. Returns the waits asked for."""
    real, waits = os.replace, []
    left = [times]

    def fake(src, dst):
        if left[0]:
            left[0] -= 1
            raise error(5, "Access is denied")
        real(src, dst)

    monkeypatch.setattr(safe_fs.os, "replace", fake)
    monkeypatch.setattr(safe_fs.time, "sleep", waits.append)
    return waits


def _leftovers(folder: Path) -> list[str]:
    return [x.name for x in folder.iterdir() if x.suffix == ".tmp"]


def test_a_save_waits_out_a_brief_refusal(tmp_path, monkeypatch):
    fs = SafeFS([tmp_path])
    target = fs.write_text(tmp_path / "a.md", "before")
    waits = _refused(monkeypatch, 3)
    fs.write_text(target, "after")
    assert target.read_text(encoding="utf-8") == "after" and not _leftovers(tmp_path)
    assert waits == [safe_fs.REPLACE_FIRST_WAIT, safe_fs.REPLACE_FIRST_WAIT * 2, safe_fs.REPLACE_FIRST_WAIT * 4]


def test_a_refusal_that_doesnt_clear_says_so_and_leaves_the_file_as_it_was(tmp_path, monkeypatch):
    fs = SafeFS([tmp_path])
    target = fs.write_text(tmp_path / "a.md", "before")
    monkeypatch.setattr(safe_fs, "REPLACE_PATIENCE", 0.05)
    real_sleep = safe_fs.time.sleep
    _refused(monkeypatch, 10_000)
    monkeypatch.setattr(safe_fs.time, "sleep", real_sleep)
    with pytest.raises(PermissionError):
        fs.write_text(target, "after")
    assert target.read_text(encoding="utf-8") == "before" and not _leftovers(tmp_path)


def test_only_a_refusal_is_waited_out(tmp_path, monkeypatch):
    fs = SafeFS([tmp_path])
    target = fs.write_text(tmp_path / "a.md", "before")
    waits = _refused(monkeypatch, 1, FileNotFoundError)
    with pytest.raises(FileNotFoundError):
        fs.write_text(target, "after")
    assert not waits


def test_a_new_file_and_a_backup_wait_too(tmp_path, monkeypatch):
    fs = SafeFS([tmp_path], replace_roots=[tmp_path])
    source = fs.write_text(tmp_path / "source.md", "words")
    waits = _refused(monkeypatch, 1)
    assert fs.write_picture(tmp_path / "a.png", b"png").read_bytes() == b"png" and len(waits) == 1
    _refused(monkeypatch, 1)
    assert fs.write_copy(tmp_path / "a.msg", b"mail").read_bytes() == b"mail"
    _refused(monkeypatch, 1)
    assert fs.replace_file(source, tmp_path / "copy.md").read_text(encoding="utf-8") == "words"


@pytest.mark.skipif(os.name != "nt", reason="Windows refuses to replace a file that's open")
def test_saving_a_file_qt_is_watching_never_fails(tmp_path):
    """The real thing: Qt's watcher looks at the file as it changes, and without the wait about one save in twenty was refused."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QFileSystemWatcher
    from PySide6.QtWidgets import QApplication

    assert QCoreApplication.instance() or QApplication([])
    fs = SafeFS([tmp_path])
    target = fs.write_text(tmp_path / "wheels.jsonc", "{}")
    watcher = QFileSystemWatcher([str(target), str(tmp_path)])
    for i in range(400):
        fs.write_text(target, "x" * 20000 + str(i))
    assert target.read_text(encoding="utf-8").endswith("399") and not _leftovers(tmp_path)
    del watcher
