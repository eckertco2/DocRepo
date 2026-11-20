"""The design tokens' colours and their themes (release 5.180, the redesign's decision 841), without Qt: ``docrepo.colours``
is read by the pages made outside ``docrepo.ui`` too, so it imports no Qt, and nor do they."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from docrepo import colours, detail, markup

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def keep_theme():
    """Each test leaves the theme as it found it, so no other test sees dark."""
    before = colours.theme()
    yield
    colours.use(before)


def test_the_two_themes_have_the_same_names():
    """Every name light has, dark has too, and no other (decision 14: a dark theme is a change of values, not of code)."""
    assert set(colours.DARK) == set(colours.LIGHT)
    assert set(colours.THEMES) == {"light", "dark"}


def test_use_sets_the_active_theme_and_refuses_any_other(keep_theme):
    assert colours.theme() == "light" and colours.colour("content") == colours.LIGHT["content"]
    colours.use("dark")
    assert colours.theme() == "dark" and colours.colour("content") == colours.DARK["content"] != colours.LIGHT["content"]
    assert colours.C.text == colours.DARK["text"] and colours.active() is colours.DARK
    colours.use("light")
    assert colours.colour("content") == colours.LIGHT["content"] and colours.C.text == colours.LIGHT["text"]
    for wrong in ("new", "classic", "system", "Dark", ""):
        with pytest.raises(ValueError, match="light and dark"):
            colours.use(wrong)
    assert colours.theme() == "light"
    with pytest.raises(AttributeError):
        colours.C.no_such_colour  # noqa: B018 - reading it is the test


def test_live_tables_answer_from_the_active_theme(keep_theme):
    """A table made when a module is imported follows a theme set after that."""
    table = colours.LiveMap({"plain": "content", "pair": ("text", "base")})
    row = colours.LiveList(["g1", "g2"])
    assert table["plain"] == colours.LIGHT["content"] and table["pair"] == (colours.LIGHT["text"], colours.LIGHT["base"])
    assert list(row) == [colours.LIGHT["g1"], colours.LIGHT["g2"]] and len(row) == 2 and row[0:1] == (colours.LIGHT["g1"],)
    assert "plain" in table and "other" not in table and table.get("other") is None
    colours.use("dark")
    assert table["plain"] == colours.DARK["content"] and row[1] == colours.DARK["g2"]


def test_the_pages_made_without_qt_follow_the_theme(keep_theme):
    """``markup``'s highlights and ticked lines, and ``detail``'s bars, are tokens read when a page is made."""
    ticked = markup.to_html("- [x] Rigging plan sent")
    assert colours.LIGHT["ticked"] in ticked
    assert markup.HIGHLIGHTS["yellow"] == colours.LIGHT["mark_yellow"]
    bar = detail.Pages._barred("words", detail.NEST_BAR, 0)
    assert f'bgcolor="{colours.LIGHT["nest_bar"]}"' in bar
    colours.use("dark")
    assert colours.DARK["ticked"] in markup.to_html("- [x] Rigging plan sent")
    assert markup.HIGHLIGHTS["yellow"] == colours.DARK["mark_yellow"]
    assert f'bgcolor="{colours.DARK["nest_bar"]}"' in detail.Pages._barred("words", detail.NEST_BAR, 0)


def test_the_colours_and_the_pages_import_no_qt():
    """The fast run imports no Qt (release 5.88), so the colours' home can't."""
    done = subprocess.run([sys.executable, "-c", "import sys, docrepo.colours, docrepo.markup, docrepo.detail\n"  # noqa: S603 - this repo's own Python, with a fixed script
                           "print(sorted(m for m in sys.modules if m.startswith(('PySide6', 'docrepo.ui'))))"],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"
