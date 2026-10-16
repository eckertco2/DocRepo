"""The command line."""
from __future__ import annotations

from conftest import example_block, table_lines, vector_lines

from docrepo import config
from docrepo.cli import main


def test_init_then_where(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert (root / "Config" / "settings.json").exists()
    assert (root / "System" / "logs" / "docrepo.log").exists()
    assert main(["--data-root", str(root), "where"]) == 0
    out = capsys.readouterr().out
    assert str(root) in out and "Status: ready" in out


def test_set_data_root_is_remembered(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CODE_DIR", tmp_path / "code")
    root = tmp_path / "DocRepoData"
    assert main(["set-data-root", str(root)]) == 0
    assert config.read_location() == root
    assert main(["init"]) == 0
    assert (root / "Tasks").is_dir()


def test_set_data_root_refuses_onedrive(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CODE_DIR", tmp_path / "code")
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    assert main(["set-data-root", str(tmp_path / "OneDrive" / "Data")]) == 1
    assert "OneDrive" in capsys.readouterr().err
    assert config.read_location() is None


def test_set_data_root_refuses_the_code_folder(capsys):
    assert main(["set-data-root", str(config.CODE_DIR / "data")]) == 1
    assert "code folder" in capsys.readouterr().err


def test_commands_explain_a_missing_data_root(capsys):
    assert main(["init"]) == 1
    assert "set-data-root" in capsys.readouterr().err


def test_init_creates_the_database(tmp_path):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert (root / "System" / "docs.db").exists()


def test_load_sample_then_rebuild_and_report(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "load-sample"]) == 0
    assert (root / "Contents.md").read_text(encoding="utf-8") == example_block("Contents.md")
    assert (root / "Tasks" / "T000010" / "Task.md").read_text(encoding="utf-8") == example_block("Tasks/T000010/Task.md")
    assert (root / "Captures" / "2026" / "10" / "C000024" / "capture.md").exists()
    assert (root / "Documents" / "D000002" / "extracted.txt").exists()
    assert config.Settings.load(root).me == "P001"
    capsys.readouterr()
    assert main(["--data-root", str(root), "rebuild", "--as-of", "2026-10-08 09:00"]) == 0
    assert "wrote 0 changed pages" in capsys.readouterr().out
    assert main(["--data-root", str(root), "report", "--as-of", "2026-10-08", "--week", "2026-10-21"]) == 0
    out = capsys.readouterr().out
    assert table_lines(out) == vector_lines("Capacity: scheduled hours per person and week", "Paths")
    log_text = (root / "System" / "logs" / "docrepo.log").read_text(encoding="utf-8")
    assert "load-sample" in log_text and "Reactor" not in log_text  # IDs and counts only, no content


def test_load_sample_refuses_a_data_root_with_data(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "load-sample"]) == 0
    assert main(["--data-root", str(root), "load-sample"]) == 1
    assert "already holds data" in capsys.readouterr().err


def test_commands_need_init_first(tmp_path, capsys):
    assert main(["--data-root", str(tmp_path / "Nothing"), "report"]) == 1
    assert "Run: python -m docrepo init" in capsys.readouterr().err
    assert not (tmp_path / "Nothing").exists()


def test_try_write_allows_inside_and_refuses_outside(tmp_path):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "try-write", str(root / "test.txt")]) == 0
    assert main(["--data-root", str(root), "try-write", str(tmp_path / "outside.txt")]) == 1
    assert not (tmp_path / "outside.txt").exists()
    log_text = (root / "System" / "logs" / "docrepo.log").read_text(encoding="utf-8")
    assert "Write refused" in log_text
