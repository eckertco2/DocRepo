"""A release identity (release 5.87, the review of 2026-11-06, F9): ``__version__`` is the newest release in CHANGELOG.md."""
from __future__ import annotations

import re
from pathlib import Path

from docrepo import __version__

REPO = Path(__file__).resolve().parent.parent


def changelog_releases() -> list[str]:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"^\| (\d+\.\d+(?:\.\d+)?) \| \d{4}-\d\d-\d\d \| ", text, re.M)


def test_the_version_is_the_newest_changelog_line():
    releases = changelog_releases()
    assert releases, "CHANGELOG.md has no release lines"
    assert releases[0] == __version__


def test_the_changelog_is_newest_first():
    releases = changelog_releases()
    numbers = [tuple(int(x) for x in r.split(".")) for r in releases]
    assert numbers == sorted(numbers, reverse=True) and len(set(numbers)) == len(numbers)
