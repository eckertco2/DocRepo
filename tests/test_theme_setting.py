"""Settings' Theme (release 5.194, the redesign's decision 869): light to start, written to settings.json only once it's
changed, and a value it can't take read as light. No Qt."""
from __future__ import annotations

import json

from docrepo.config import THEMES, Settings, make_safe_fs


def test_it_starts_light_and_isnt_written_until_changed(tmp_path):
    root = tmp_path / "DocRepoData"
    Settings().save(make_safe_fs(root, Settings()), root)
    assert Settings().theme == "light" and list(THEMES) == ["light", "dark", "system"]
    assert THEMES["system"] == "As Windows is set"
    assert "theme" not in json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))
    for theme in ("dark", "system"):
        Settings(theme=theme).save(make_safe_fs(root, Settings()), root)
        assert json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))["theme"] == theme
        assert Settings.load(root).theme == theme


def test_a_file_without_it_or_with_a_value_it_cant_take_is_light(tmp_path):
    root = tmp_path / "DocRepoData"
    Settings().save(make_safe_fs(root, Settings()), root)
    (root / "Config" / "settings.json").write_text('{"me": "P001"}', encoding="utf-8")
    assert Settings.load(root).theme == "light"
    (root / "Config" / "settings.json").write_text('{"theme": "sepia"}', encoding="utf-8")
    assert Settings.load(root).theme == "light"
