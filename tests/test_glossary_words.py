"""One set of verbs in the windows (release 5.91, the review of 2026-11-06, F12): Discard for a record, Remove for a link
and Clear for a field. The retired words don't come back."""
from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "docrepo" / "ui"
OTHERS = [UI.parent / name for name in ("activity.py", "stories.py", "detail.py")]  # their words are shown in the windows too
RETIRED = ("New subtask", "Take off", "Take out", "Put back")


def retired_words(text: str) -> list[str]:
    return [w for w in RETIRED if w in text]


def test_the_windows_use_none_of_the_retired_words():
    found = {f.name: words for f in [*sorted(UI.rglob("*.py")), *OTHERS] if (words := retired_words(f.read_text(encoding="utf-8")))}
    assert found == {}


def test_the_check_catches_them():
    assert retired_words('menu.addAction("Take out from under Installation")') == ["Take out"]
    assert retired_words('QPushButton("Put back")') == ["Put back"] and retired_words("Remove, Add back") == []
