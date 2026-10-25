"""The visual overhaul (releases 5.10 to 5.16): the tokens and their contrast, the style sheet, help that shows only with
Show hints, the date field, the command palette, and the new look's capture window and browse tool. Driven offscreen."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import palette, tokens  # noqa: E402
from docrepo.ui.look import LOOK, Help, KeyBadge, KeyTips, set_hints  # noqa: E402
from docrepo.ui.palette import Command, rank  # noqa: E402
from docrepo.ui.widgets import DateField, InfoButton, parse_day  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def hints_off():
    yield
    set_hints(False)


def ratio(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio of two #rrggbb colours."""
    def lum(c: str) -> float:
        parts = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in parts)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_tokens_meet_wcag_aa():
    """Decisions 11 to 13: two readable greys, a 3:1 edge on inputs, and status text that passes on its own tint."""
    t = tokens.LIGHT
    for text in ("text", "text2", "accent"):
        for ground in ("content", "base", "selected"):
            assert ratio(t[text], t[ground]) >= 4.5, (text, ground)
    assert ratio(t["control"], t["content"]) >= 3 and ratio(t["control"], t["base"]) >= 3
    assert ratio(t["on_accent"], t["accent"]) >= 4.5
    for fg, bg in (("caution", "caution_bg"), ("critical", "critical_bg"), ("success", "success_bg")):
        assert ratio(t[fg], t[bg]) >= 4.5, fg
    assert set(tokens.DARK) == set(tokens.LIGHT)  # the dark theme's names are all reserved (decision 14)


def test_the_style_sheet_parses(qapp):
    problems = []

    def note(_mode, _ctx, msg) -> None:
        if "parse" in msg.lower():
            problems.append(msg)

    previous = qInstallMessageHandler(note)
    try:
        w = QWidget()
        w.setStyleSheet(tokens.qss())
        w.ensurePolished()
    finally:
        qInstallMessageHandler(previous)
    assert problems == [] and "$" not in tokens.qss() and "$" not in tokens.CSS


def test_help_shows_only_with_show_hints(qapp):
    """Decision 7: help text, ⓘ buttons and key badges are off by default, and Show hints brings them back at once."""
    parent = QWidget()
    help_ = Help("Ctrl+Enter saves.", parent)
    badge = KeyBadge("Alt+N", parent)
    info = InfoButton("task", Help())
    info.setParent(parent)
    parent.show()
    assert not LOOK.hints and help_.isHidden() and badge.isHidden() and info.isHidden()
    set_hints(True)
    assert help_.isVisible() and badge.isVisible() and info.isVisible()
    help_.hide()  # its own code can still hide it; that's kept when hints go off and on again
    set_hints(False)
    set_hints(True)
    assert help_.isHidden() and badge.isVisible()
    parent.deleteLater()


def test_the_date_field_reads_like_the_rest_of_docrepo(qapp):
    """The visual overhaul's O4: "Fri 9 Oct 2026" when you're not in it, YYYY-MM-DD as its value and to type."""
    d = DateField()
    d.set_value("2026-10-09")
    assert d.line.text() == "Fri 9 Oct 2026" and d.value() == "2026-10-09" and d.is_valid()
    d.line.setText("2026-13-40")
    assert not d.is_valid() and d.value() == "2026-13-40"  # shown as typed, so it can be fixed
    d.set_value(None)
    assert d.value() is None and d.is_valid() and d.maximumWidth() == DateField.WIDTH
    assert parse_day("Fri 9 Oct 2026") == date(2026, 10, 9) == parse_day("2026-10-09") and parse_day("next week") is None


def test_the_command_palette_matches_fuzzily(monkeypatch):
    """Decision 6: Ctrl+K narrows every command as you type; without RapidFuzz the standard library does it."""
    ran = []
    commands = [Command("Task", "Add a note", lambda: ran.append("note"), "N"), Command("Task", "Edit task", lambda: ran.append("edit"), "E"),
                Command("View", "Timeline", lambda: None), Command("", "Keys", lambda: None, "F1")]
    assert rank("", commands) == commands
    assert rank("edt tsk", commands)[0].name == "Edit task"
    assert rank("timeline", commands)[0].name == "Timeline" and [c.name for c in rank("zzzz", commands)] == []
    monkeypatch.setattr(palette, "fuzz", None)
    assert rank("edit", commands)[0].name == "Edit task" and rank("task note", commands)[0].name == "Add a note"
    assert rank("edt tsk", commands)[0].name == "Edit task" and rank("zzzz", commands) == []


def test_key_tips_come_in_groups(qapp):
    w = QWidget()
    tips = KeyTips(w)
    a, b = QWidget(w), QWidget(w)
    tips.add(a, "N")
    tips.add(b, "E", group="actions")
    tips.add(b, "Ctrl+K", ctrl=True, group="actions")
    tips.clear("actions")
    assert [k for _w, k, _g in tips.alt] == ["N"] and tips.ctrl == []
    w.deleteLater()


@pytest.fixture
def ctx(qapp, data_root, fs):
    from docrepo import capacity, prompts
    from docrepo.ui.context import AppContext

    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    context = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW)
    yield context
    conn.close()


def test_the_capture_window_in_the_new_look(ctx):
    """The visual overhaul's O3: the items' column only when there are items, State beside the picker for an update,
    Clear with Undo, and a palette of every command."""
    from docrepo.ui.capture_window import CaptureWindow

    w = CaptureWindow(ctx)
    w.show_capture()
    assert not w.side.isVisibleTo(w) and not w.found_box.isVisibleTo(w)
    w.content.setPlainText("Walkdown done.\n- @Tom check the guards")
    w.read_items()
    assert w.side.isVisibleTo(w) and len(w.item_cards.cards) == 1
    w.set_task("T000008")
    w.set_type("update", True)
    assert w.state_row.isVisibleTo(w) and w.u_state.currentText()
    w.clear()
    assert w.content.toPlainText() == "" and w.undo_clear.isVisibleTo(w) and w.draft_label.text() == "Cleared."
    w.undo_clear.click()
    assert "check the guards" in w.content.toPlainText() and w.task == "T000008" and not w.undo_clear.isVisibleTo(w)
    names = [c.label for c in w.palette_commands()]
    assert {"Capture: Parse and populate", "Attach: A link", "Save", "Mods log"} <= set(names)
    w.hide()
    w.deleteLater()


def test_the_browse_tool_in_the_new_look(ctx):
    """The visual overhaul's O5: groups in the sidebar that fold and stay folded, the detail pane only once something is
    picked, and the palette's commands for the selected task and the views."""
    from docrepo.ui.browse_window import NAV_FOLDED_KEY, BrowseWindow
    from docrepo.ui.capture_window import CaptureWindow

    cap = CaptureWindow(ctx)
    w = BrowseWindow(ctx, cap)
    w.show_browse("today")
    assert w.sel is None and not w.detail.isVisibleTo(w)
    w.go_task("T000012")
    assert w.detail.isVisibleTo(w)
    names = [c.label for c in w.palette_commands()]
    assert {"Task: Edit task", "View: Timeline", "View: Capacity", "Keys"} <= set(names)
    lists = next(i for i in w.nav.items() if i.data(0, 0x100) == ("section", "Lists"))
    w._nav_clicked(lists)
    assert not lists.isExpanded() and db.get_state(ctx.conn, NAV_FOLDED_KEY) == "Lists"
    w.render_nav()
    again = next(i for i in w.nav.items() if i.data(0, 0x100) == ("section", "Lists"))
    assert not again.isExpanded()
    w.hide()
    cap.deleteLater()
    w.deleteLater()


def test_settings_keep_the_look_and_show_hints(ctx):
    from docrepo.ui.settings_view import SettingsView, update_settings

    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    view.look.setCurrentIndex(view.look.findData("classic"))
    view.hints.setChecked(True)
    assert LOOK.hints  # Show hints applies at once
    assert set(update_settings(ctx, view.values())) == {"look", "show_hints"}
    assert Settings.load(ctx.data_root).look == "classic" and Settings.load(ctx.data_root).show_hints
