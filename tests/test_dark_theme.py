"""The dark theme (release 5.194, the redesign's decision 869): Settings' Theme, ``apply_look`` picking the set, Windows' dark
title bar, the wheel and the style sheet's file icons following the theme, and no colour bound when a module loads."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import icons, look, tokens, wheel_window  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "docrepo" / "ui"
NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def keep_theme():
    """Each test leaves the theme as it found it, so no other test sees dark."""
    before = tokens.theme()
    yield
    tokens.use(before)


@pytest.fixture
def ctx(qapp, data_root, fs):
    from docrepo.ui.context import AppContext

    conn = db.connect(fs, data_root)
    load_sample(conn)
    context = AppContext(conn, data_root, fs, Settings(me="P001"), notify=lambda t, m: None, now=lambda: NOW)
    yield context
    conn.close()


def test_settings_has_a_theme_row_that_saves_for_the_next_start(ctx, keep_theme):
    """Theme sits first on the Look card, says it changes at the next start, and saving it changes nothing now."""
    from docrepo.ui.settings_view import SettingsView, update_settings

    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    assert [view.theme.itemText(i) for i in range(view.theme.count())] == ["Light", "Dark", "As Windows is set"]
    assert view.theme.currentData() == "light" and view.values()["theme"] == "light"
    view.theme.setCurrentIndex(view.theme.findData("dark"))
    assert set(update_settings(ctx, view.values())) == {"theme"}
    assert Settings.load(ctx.data_root).theme == "dark"
    assert tokens.theme() == "light"  # taken at the next start, not now
    view.deleteLater()


def run_app(script: str) -> dict:
    done = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True, timeout=300,  # noqa: S603 - this repo's own Python, with a fixed script
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_apply_look_picks_the_set_for_each_theme_and_asks_windows_for_as_windows_is_set():
    """Light and dark as they say; "system" reads the colour scheme Windows gives Qt with nothing asked of it (made dark and
    then light here, the offscreen platform having none of its own), and asks for that scheme back."""
    out = run_app("""
import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QStyleHints
from PySide6.QtWidgets import QApplication
from docrepo.ui import tokens
from docrepo.ui.style import apply_look
windows = [Qt.ColorScheme.Light]
asked = []
QStyleHints.colorScheme = lambda self: windows[0]
QStyleHints.unsetColorScheme = lambda self: asked.append("unset")
QStyleHints.setColorScheme = lambda self, scheme: asked.append(scheme == Qt.ColorScheme.Dark)
app = QApplication([])
out = {}
for theme, os_dark in (("light", True), ("dark", False), ("system", True), ("system", False)):
    windows[0] = Qt.ColorScheme.Dark if os_dark else Qt.ColorScheme.Light
    asked.clear()
    apply_look(app, theme, False)
    out[f"{theme}-{os_dark}"] = [tokens.theme(), list(asked)]
print(json.dumps(out))
""")
    assert out["light-True"] == ["light", [False]]
    assert out["dark-False"] == ["dark", [True]]
    assert out["system-True"] == ["dark", ["unset", True]]
    assert out["system-False"] == ["light", ["unset", False]]


def test_windows_draws_a_dark_frame_in_the_dark_theme(qapp, keep_theme, monkeypatch):
    """``dress_window`` asks for Windows' dark title bar and frame (DWMWA_USE_IMMERSIVE_DARK_MODE, 20) in dark, and not in
    light, beside the caption colour it set before."""
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(look, "dwm_set", lambda window, attribute, value: calls.append((attribute, value)) or True)
    w = QWidget()
    for theme, want in (("dark", 1), ("light", 0)):
        tokens.use(theme)
        calls.clear()
        look.dress_window(w)
        assert (look.DWMWA_USE_IMMERSIVE_DARK_MODE, want) in calls and look.DWMWA_USE_IMMERSIVE_DARK_MODE == 20
        assert any(a == look.DWMWA_CAPTION_COLOR for a, _v in calls)
    w.deleteLater()


def test_the_wheel_and_the_style_sheets_file_icons_follow_the_theme(qapp, keep_theme, monkeypatch):
    """The wheel's colours are the theme's (Windows' own only under high contrast), and the icons the style sheet takes from
    files are the dark copies while dark is on, the same files as before in light."""
    monkeypatch.setattr(wheel_window, "_high_contrast", lambda: False)
    for theme in ("light", "dark"):
        tokens.use(theme)
        assert wheel_window.colours() is tokens.THEMES[theme]
    tokens.use("light")
    light = {n: icons.file_url(n) for n in ("arrow-down-grey", "chevron-right", "chevron-down", "chevron-left", "filled-marker", "tick-white")}
    assert all("/dark/" not in url for url in light.values())
    tokens.use("dark")
    for name, url in light.items():
        dark = icons.file_url(name)
        assert (dark != url and "/icons/dark/" in dark and Path(dark).exists()) if name != "tick-white" else dark == url
    assert "/icons/dark/" in tokens.qss()


def _binds_a_colour(node: ast.AST) -> list[str]:
    """What in an expression reads a colour now: a token's colour by name (``C.x``, ``colour()``, ``active()``, ``LIGHT``,
    ``DARK``), not a live table of names."""
    found = []
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "C":
            found.append(f"C.{n.attr}")
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name in ("colour", "active", "group_colour", "css", "qss", "palette", "page_css"):
                found.append(f"{name}()")
        if isinstance(n, ast.Attribute) and n.attr in ("LIGHT", "DARK"):
            found.append(n.attr)
    return found


def test_no_module_binds_a_colour_when_it_loads():
    """A colour read when a module loads (or a class is made, or as a default argument) would stay the theme of that moment:
    every module in docrepo/ui reads its colours when it draws (release 5.180, decision 841, checked here since 5.194)."""
    found = []
    for path in sorted(UI.rglob("*.py")):
        if path.name in ("tokens.py",):
            continue
        found += _bound_in(ast.parse(path.read_text(encoding="utf-8")).body, str(path.relative_to(UI)), "module")
    assert found == []


def _bound_in(body: list, where: str, scope: str) -> list[str]:
    """Each place in a module's or a class's body that reads a colour as it runs: an assignment, or a default argument."""
    found = []
    for node in body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and _binds_a_colour(node.value):
            found.append(f"{where}:{node.lineno} {scope}")
        if isinstance(node, ast.ClassDef):
            found += _bound_in(node.body, where, "class " + node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in [*node.args.defaults, *node.args.kw_defaults]:
                if d is not None and _binds_a_colour(d):
                    found.append(f"{where}:{node.lineno} default of {node.name}")
    return found
