"""A release identity (release 5.87, the review of 2026-11-06, F9): ``__version__`` is the newest release in CHANGELOG.md.

Since the weekly trains (release 5.127, when the first release merged for a later train had a lower number than the train
before it's), the newest is the highest number, and each heading's releases (a train's, or those merged and waiting for
theirs) are newest first under it."""
from __future__ import annotations

import re
from pathlib import Path

from docrepo import __version__

REPO = Path(__file__).resolve().parent.parent
RELEASE = re.compile(r"^\| (\d+\.\d+(?:\.\d+)?) \| \d{4}-\d\d-\d\d \| ", re.M)


def number(release: str) -> tuple[int, ...]:
    return tuple(int(x) for x in release.split("."))


def changelog_sections() -> list[list[str]]:
    """Each heading's releases, in the file's order."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    return [RELEASE.findall(part) for part in re.split(r"^## ", text, flags=re.M)]


def changelog_releases() -> list[str]:
    return [r for section in changelog_sections() for r in section]


def test_the_version_is_the_newest_changelog_line():
    releases = changelog_releases()
    assert releases, "CHANGELOG.md has no release lines"
    assert __version__ == max(releases, key=number)


def test_the_changelog_is_newest_first():
    for section in changelog_sections():
        numbers = [number(r) for r in section]
        assert numbers == sorted(numbers, reverse=True), section
    releases = changelog_releases()
    assert len(set(releases)) == len(releases)
