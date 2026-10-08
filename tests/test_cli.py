"""The command line."""
from __future__ import annotations

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


def test_try_write_allows_inside_and_refuses_outside(tmp_path):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "try-write", str(root / "test.txt")]) == 0
    assert main(["--data-root", str(root), "try-write", str(tmp_path / "outside.txt")]) == 1
    assert not (tmp_path / "outside.txt").exists()
    log_text = (root / "System" / "logs" / "docrepo.log").read_text(encoding="utf-8")
    assert "Write refused" in log_text
