"""Tokens that can change theme (release 5.180, the redesign's decision 841): ``tokens.use`` sets the active set, and the
palette, the style sheet, the pages' styles, the icons and every window drawn after it answer from it. Dark is built and
exercised here, not judged: release 5.194 settles how it looks."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.ui import icons, style, tokens  # noqa: E402
from docrepo.ui.tree_view import GROUP_COLOURS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def keep_theme():
    """Each test leaves the theme as it found it, so no other test sees dark."""
    before = tokens.theme()
    yield
    tokens.use(before)


def _ink(icon, size: int = 16) -> str:
    """The colour most of an icon's solid pixels are, at 1x."""
    image = icon.pixmap(size, size).toImage()
    seen: dict[str, int] = {}
    for x in range(image.width()):
        for y in range(image.height()):
            c = image.pixelColor(x, y)
            if c.alpha() == 255:
                seen[c.name()] = seen.get(c.name(), 0) + 1
    return max(seen, key=seen.get)


def test_dark_changes_the_colours_the_sheets_and_the_palette_and_light_puts_them_back(qapp, keep_theme):
    light = (tokens.colour("content"), tokens.css(), tokens.qss(), tokens.palette().color(QPalette.ColorRole.Base).name())
    assert light[0] == tokens.LIGHT["content"] and light[3] == tokens.LIGHT["content"]
    tokens.use("dark")
    dark = (tokens.colour("content"), tokens.css(), tokens.qss(), tokens.palette().color(QPalette.ColorRole.Base).name())
    assert dark[0] == tokens.DARK["content"] == dark[3]
    assert all(a != b for a, b in zip(light, dark, strict=True))
    assert f"background: {tokens.DARK['content']}" in dark[2] and tokens.DARK["text"] in dark[1]
    assert tokens.LIGHT["text"] not in dark[1]  # nothing in the pages' styles stays light
    tokens.use("light")
    assert (tokens.colour("content"), tokens.css(), tokens.qss(), tokens.palette().color(QPalette.ColorRole.Base).name()) == light


def test_an_icon_made_after_a_switch_is_in_the_new_colours(qapp, keep_theme):
    """``icons.icon`` is kept by theme as well, so a switch can't hand back the old theme's icon."""
    light = icons.icon("state-cl")
    assert _ink(light) == tokens.LIGHT["text2"]
    tokens.use("dark")
    dark = icons.icon("state-cl")
    assert dark is not light and _ink(dark) == tokens.DARK["text2"]
    tokens.use("light")
    assert icons.icon("state-cl") is light  # each theme's is kept


def test_the_tables_made_at_import_follow_the_theme(qapp, keep_theme):
    """The modules' tables of colours (the categories', the Timeline's, the items panel's) are read when they're drawn."""
    from docrepo.ui import capacity_strip, items_panel, timeline_view

    before = (list(GROUP_COLOURS), capacity_strip.TINTS["t3"], items_panel.REF_COLOURS["person"], timeline_view.KEY_COLOURS[0],
              timeline_view.PRIORITY_COLOURS["high"], tokens.group_colour(1))
    tokens.use("dark")
    after = (list(GROUP_COLOURS), capacity_strip.TINTS["t3"], items_panel.REF_COLOURS["person"], timeline_view.KEY_COLOURS[0],
             timeline_view.PRIORITY_COLOURS["high"], tokens.group_colour(1))
    assert after == ([tokens.DARK[k] for k in tokens.GROUP_KEYS], tokens.DARK["load3"], (tokens.DARK["accent"], tokens.DARK["info_bg"]),
                     tokens.DARK["lane1"], tokens.DARK["pri_high"], tokens.DARK["g2"])
    assert all(a != b for a, b in zip(before, after, strict=True))


def test_the_style_sheet_is_kept_by_theme(qapp, keep_theme, monkeypatch):
    """``style_sheet`` makes the sheet once a theme, so one set up dark isn't the light one."""
    monkeypatch.setattr(style.LOOK, "app_sheet", True)  # as if it were on the application already: style_sheet() gives ""
    assert style.style_sheet() == ""
    monkeypatch.setattr(style, "QApplication", type("NoApp", (), {"instance": staticmethod(lambda: None)}))
    monkeypatch.setattr(style.LOOK, "app_sheet", False)
    light = style.style_sheet()
    tokens.use("dark")
    dark = style.style_sheet()
    assert light != dark and tokens.DARK["content"] in dark and style.page_css() == tokens.css()


def run_app(script: str, root: Path | None = None) -> dict:
    """Run ``script`` in a process of its own, after a QApplication and ``apply_look`` (which change the whole application);
    it prints its results as JSON."""
    done = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True, timeout=300,  # noqa: S603 - this repo's own Python, with a fixed script
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "DOCREPO_TEST_ROOT": str(root or "")})
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_apply_look_takes_the_theme_and_reads_anything_else_as_light():
    """``apply_look(app, theme, hints)``: "dark" sets the dark set, the dark palette and asks Qt for its dark colour scheme;
    the looks callers passed before ("new", "classic") and anything else are light, with the light scheme."""
    out = run_app("""
import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QStyleHints
from PySide6.QtWidgets import QApplication
from docrepo.ui import tokens
from docrepo.ui.style import apply_look
asked = []
QStyleHints.setColorScheme = lambda self, scheme: asked.append(scheme)  # the offscreen platform doesn't take it: note what's asked
app = QApplication([])
out = {}
for theme in ("dark", "new", "classic", "system", "light"):
    apply_look(app, theme, False)
    out[theme] = [tokens.theme(), asked[-1] == Qt.ColorScheme.Dark, app.palette().color(QPalette.ColorRole.Base).name(),
                  tokens.DARK["content"] in app.styleSheet()]
print(json.dumps(out))
""")
    assert out["dark"] == ["dark", True, tokens.DARK["content"], True]
    for theme in ("new", "classic", "system", "light"):
        assert out[theme] == ["light", False, tokens.LIGHT["content"], False], theme


def test_the_browse_and_capture_windows_build_in_dark(sample_root):
    """Dark is exercised, not only defined: under ``apply_look(app, "dark")`` the capture window and the browse window are
    made, shown offscreen, and every view in the sidebar opened and drawn, without an error. How they look isn't judged."""
    _conn, root, _fs = sample_root
    out = run_app("""
import json, os
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import QApplication
from docrepo import db
from docrepo.config import Settings
from docrepo.safe_fs import SafeFS
from docrepo.ui import tokens
from docrepo.ui.style import apply_look
app = QApplication([])
apply_look(app, "dark", False)
from docrepo.ui.browse_window import BrowseWindow
from docrepo.ui.capture_window import CaptureWindow
from docrepo.ui.context import AppContext
from docrepo.ui.nav_pane import ICONS
root = Path(os.environ["DOCREPO_TEST_ROOT"])
fs = SafeFS([root])
ctx = AppContext(db.connect(fs, root), root, fs, Settings(me="P001"), now=lambda: datetime(2026, 10, 8, 14, 10), settings_changed=lambda keys: None)
capture = CaptureWindow(ctx)
capture.show()
capture.grab()
browse = BrowseWindow(ctx, capture)
browse.confirm = lambda title, text: True
browse.show_browse()
seen = []
for view in ICONS:
    browse.set_view(view)
    app.processEvents()
    browse.grab()
    seen.append(view)
print(json.dumps({"theme": tokens.theme(), "seen": seen, "base": app.palette().color(app.palette().ColorRole.Base).name()}))
""", root)
    from docrepo.ui.nav_pane import ICONS

    assert out["theme"] == "dark" and out["seen"] == list(ICONS) and out["base"] == QColor(tokens.DARK["content"]).name()
