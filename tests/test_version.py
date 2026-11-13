"""A release identity (release 5.87, the review of 2026-11-06, F9): ``__version__`` is the highest release number in
CHANGELOG.md. Since the weekly trains (release 5.128, the first merged after a train with a lower number than one in
it), each train's section lists its releases newest first, and the trains run newest first, so a number can be lower
than one in the train below it."""
from __future__ import annotations

import re
from pathlib import Path

from docrepo import __version__

REPO = Path(__file__).resolve().parent.parent


LINE = re.compile(r"^\| (\d+\.\d+(?:\.\d+)?) \| \d{4}-\d\d-\d\d \| ", re.M)


def number(release: str) -> tuple[int, ...]:
    return tuple(int(x) for x in release.split("."))


def changelog_sections() -> list[list[str]]:
    """Each section's release numbers, as listed: a train's, or those before the trains."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    return [found for part in re.split(r"^## ", text, flags=re.M) if (found := LINE.findall(part))]


def changelog_releases() -> list[str]:
    return [r for section in changelog_sections() for r in section]


def test_the_version_is_the_highest_release_number():
    releases = changelog_releases()
    assert releases, "CHANGELOG.md has no release lines"
    assert max(releases, key=number) == __version__


def test_each_trains_releases_are_newest_first_and_none_twice():
    for section in changelog_sections():
        numbers = [number(r) for r in section]
        assert numbers == sorted(numbers, reverse=True), section
    releases = changelog_releases()
    assert len(set(releases)) == len(releases)
