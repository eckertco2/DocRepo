"""The data root's location, and settings."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from docrepo import config
from docrepo.config import (
    Settings,
    SettingsError,
    app_dir,
    data_root_problem,
    init_data_root,
    make_safe_fs,
    read_location,
    resolve_data_root,
    save_location,
)


def test_app_dir_follows_localappdata(tmp_path):
    assert app_dir() == tmp_path / "localappdata" / "DocRepo"


def test_no_data_root_until_one_is_set():
    assert resolve_data_root() == config.DataRootChoice(None, "not set")


def test_location_file_round_trip(tmp_path):
    root = tmp_path / "DocRepoData"
    written = save_location(root)
    assert written.samefile(app_dir() / "location.json")
    assert read_location() == root
    choice = resolve_data_root()
    assert choice.path == root and "location.json" in choice.source


def test_command_line_beats_environment_beats_location_file(tmp_path, monkeypatch):
    save_location(tmp_path / "from-file")
    assert resolve_data_root().path == tmp_path / "from-file"
    monkeypatch.setenv("DOCREPO_DATA_ROOT", str(tmp_path / "from-env"))
    assert resolve_data_root().path == tmp_path / "from-env"
    assert resolve_data_root(str(tmp_path / "from-cli")).path == tmp_path / "from-cli"


def test_ignores_an_unreadable_location_file(caplog):
    app_dir().mkdir(parents=True)
    (app_dir() / "location.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert read_location() is None
    assert "Can't read" in caplog.text


def test_data_root_must_be_local_and_outside_the_code(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    assert "OneDrive" in data_root_problem(tmp_path / "OneDrive" / "DocRepoData")
    assert "code folder" in data_root_problem(config.CODE_DIR / "data")
    assert data_root_problem(config.CODE_DIR / "dev_data", allow_code_dir=True) is None
    assert "full path" in data_root_problem(Path("relative"))
    monkeypatch.setattr(config, "CODE_DIR", tmp_path / "code")
    assert data_root_problem(tmp_path / "DocRepoData") is None


def test_settings_defaults_and_round_trip(tmp_path):
    root = tmp_path / "DocRepoData"
    settings = Settings.load(root)
    assert settings.hotkey == "Ctrl+Shift+Space"
    assert settings.workdays == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    settings.me = "P001"
    settings.backup_dir = str(tmp_path / "Backups")
    settings.save(make_safe_fs(root, settings), root)
    assert Settings.load(root) == settings


def test_settings_file_has_the_documented_fields(tmp_path):
    root = tmp_path / "DocRepoData"
    Settings(me="P001").save(make_safe_fs(root, Settings()), root)
    data = json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert list(data) == [
        "schema_version", "me", "hotkey", "backup_dir", "doc_check_minutes",
        "extracted_text_cap_chars", "prompt_warn_chars", "capacity_horizon_years", "workdays",
    ]


def test_unreadable_settings_raise_rather_than_being_replaced(tmp_path):
    root = tmp_path / "DocRepoData"
    (root / "Config").mkdir(parents=True)
    (root / "Config" / "settings.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(SettingsError):
        Settings.load(root)
    assert (root / "Config" / "settings.json").read_text(encoding="utf-8") == "{broken"


def test_unknown_settings_are_ignored_with_a_warning(tmp_path, caplog):
    root = tmp_path / "DocRepoData"
    (root / "Config").mkdir(parents=True)
    (root / "Config" / "settings.json").write_text('{"hotkey": "Ctrl+Alt+N", "colour": "blue"}', encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert Settings.load(root).hotkey == "Ctrl+Alt+N"
    assert "colour" in caplog.text


def test_backup_folder_is_an_allowed_root(tmp_path):
    root, backups = tmp_path / "DocRepoData", tmp_path / "Backups"
    fs = make_safe_fs(root, Settings(backup_dir=str(backups)))
    fs.write_text(backups / "note.txt", "x")
    fs.write_text(app_dir() / "location.json", "{}")


def test_init_creates_the_standard_folders_once(tmp_path):
    root = tmp_path / "DocRepoData"
    created = init_data_root(root)
    for name in config.DATA_ROOT_FOLDERS:
        assert (root / name).is_dir()
    assert (root / "Config" / "settings.json").exists()
    assert created
    assert init_data_root(root) == []
