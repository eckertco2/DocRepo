"""Settings' Open a task in (release 5.174, the design workspace's docs/mods/today-workspace-carry-plan.md, decision 815):
its workspace to start, written to settings.json only once it's changed, and a value it can't take ignored. No Qt."""
from __future__ import annotations

import json

from docrepo.config import OPEN_TASKS_IN, Settings, make_safe_fs


def test_it_starts_on_the_workspace_and_isnt_written_until_changed(tmp_path):
    root = tmp_path / "DocRepoData"
    Settings().save(make_safe_fs(root, Settings()), root)
    assert Settings().open_tasks_in == "workspace" and set(OPEN_TASKS_IN) == {"workspace", "page"}
    assert "open_tasks_in" not in json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))
    Settings(open_tasks_in="page").save(make_safe_fs(root, Settings()), root)
    assert json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))["open_tasks_in"] == "page"
    assert Settings.load(root).open_tasks_in == "page"


def test_a_value_it_cant_take_is_ignored(tmp_path):
    root = tmp_path / "DocRepoData"
    Settings().save(make_safe_fs(root, Settings()), root)
    (root / "Config" / "settings.json").write_text('{"open_tasks_in": "somewhere"}', encoding="utf-8")
    assert Settings.load(root).open_tasks_in == "workspace"
