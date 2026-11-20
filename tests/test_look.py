"""The visual overhaul (releases 5.10 to 5.16): the tokens and their contrast, the style sheet, help that shows only with
Show hints, the date field, the command palette, and the new look's capture window and browse tool. Driven offscreen."""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QRect, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import palette, tokens  # noqa: E402
from docrepo.ui.look import LOOK, Help, KeyBadge, KeyTips, set_hints  # noqa: E402
from docrepo.ui.palette import Command, rank  # noqa: E402
from docrepo.ui.widgets import DateField, FlowLayout, InfoButton, parse_day  # noqa: E402

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
    """Decisions 11 to 13: readable greys, and status text that passes on its own tint. A field's edge no longer keeps 3:1:
    release 5.181's decision 848 (a field's even edge) gave that up, and the focus edge is the accent."""
    t = tokens.LIGHT
    for text in ("text", "text2", "accent"):
        for ground in ("content", "base", "selected"):
            assert ratio(t[text], t[ground]) >= 4.5, (text, ground)
    assert ratio(t["text3"], t["content"]) >= 4.5
    assert ratio(t["on_accent"], t["accent_fill"]) >= 4.5
    for fg, bg in (("caution", "caution_bg"), ("critical", "critical_bg"), ("success", "success_bg")):
        assert ratio(t[fg], t[bg]) >= 4.5, fg
    assert set(tokens.DARK) == set(tokens.LIGHT)  # the dark theme's names are all reserved (decision 14)


def test_the_size_scale_sits_on_the_grid_and_agrees_with_the_heights():
    """Release 5.102: SIZE, for new code, holds the heights the code already names, on a 2 px grid as SPACE is."""
    s = tokens.SIZE
    assert (s["row_tree"], s["row_list"], s["control"], s["icon_button"]) == (tokens.TREE_ROW, tokens.LIST_ROW, tokens.CONTROL, tokens.ICON_BUTTON)
    assert all(v % 2 == 0 for v in (*tokens.SPACE.values(), *s.values()))
    assert s["icon_xs"] < s["icon_s"] < s["icon"] < s["icon_l"] < s["control_s"] < s["icon_button"] < s["control"]
    from docrepo.ui import result_list

    assert (result_list.HEAD_HEIGHT, result_list.ITEM_HEIGHT, result_list.COMPACT_HEIGHT) == (s["row_head"], s["row_two_line"], s["row_list"])


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
    assert problems == [] and "$" not in tokens.qss() and "$" not in tokens.css()


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
    w.nav.headings["Lists"].click()
    assert w.nav.rows["due"].isHidden() and db.get_state(ctx.conn, NAV_FOLDED_KEY) == "Lists,Manage"  # Manage folded at first (5.182)
    w.render_nav()
    assert w.nav.headings["Lists"].folded and w.nav.rows["due"].isHidden()
    w.hide()
    cap.deleteLater()
    w.deleteLater()


def test_clear_takes_parse_and_populates_marks_with_it(ctx):
    """The filled look on a field goes with what filled it: an empty Title isn't left yellow for the next capture (release 5.57)."""
    from docrepo.ui.capture_window import CaptureWindow

    w = CaptureWindow(ctx)
    w.show_capture(mode="new_task", content="Replace the Line 2 pump seal by Fri 16 Oct. @Mike leads, 6 h")
    w.parse()
    assert w.title.text() and w.title.property("filled")
    w.clear()
    assert w.title.text() == "" and not w.title.property("filled")
    w.hide()
    w.deleteLater()


def test_the_flow_layout_keeps_its_margins_and_centres_each_line(qapp):
    """Release 5.57: a command bar stands off the pane's edge, and a tick box sits level with the taller boxes beside it."""
    box = QWidget()
    flow = FlowLayout(box, spacing=8)
    flow.setContentsMargins(16, 10, 16, 2)
    tall, short, wrapped = QWidget(box), QWidget(box), QWidget(box)
    tall.setFixedSize(100, 32)
    short.setFixedSize(60, 20)
    wrapped.setFixedSize(100, 32)
    for w in (tall, short, wrapped):
        flow.addWidget(w)
    flow.setGeometry(QRect(0, 0, 230, 200))
    assert (tall.x(), tall.y()) == (16, 10)
    assert short.geometry().center().y() == tall.geometry().center().y() and short.x() == 124
    assert (wrapped.x(), wrapped.y()) == (16, 50)  # it would end past the right margin, so it starts the next line
    assert flow.heightForWidth(230) == 10 + 32 + 8 + 32 + 2
    assert flow.minimumSize().width() == 100 + 32 and flow.minimumSize().height() == 32 + 12
    box.deleteLater()


def test_no_text_is_styled_below_the_floor():
    """Decision 2: nothing is smaller than a group label (9 pt, ``LABEL``; captions are 9.5 since release 5.181) in the style sheets."""
    from docrepo.ui.today_panel import panel_qss

    sizes = re.findall(r"font-size:\s*([\d.]+)pt", tokens.qss() + tokens.css() + panel_qss())
    assert sizes and min(float(s) for s in sizes) >= tokens.LABEL


#: The contrast of each pair the redesign plan's section 3 checked (release 5.181), light and dark, to one decimal place:
#: (foreground, ground, light, dark), None where the plan names no figure for that set.
SECTION_3 = (("text", "content", 17.7, 14.6), ("text2", "content", 6.6, 6.9), ("text3", "content", 4.6, 4.5), ("accent", "content", 6.0, 6.5),
             ("critical", "content", 5.3, None), ("caution", "content", 5.1, None), ("success", "content", 5.4, None),
             ("parked", "content", 5.5, None), ("on_accent", "accent_fill", 6.0, 5.1))


def test_the_redesigns_contrast_figures_hold_in_both_themes():
    """Release 5.181 (the new skin): the redesign plan's section 3 contrast figures, light and dark, and each at least what
    WCAG 2.2 AA asks of its job: 4.5 for words."""
    for fg, ground, light, dark in SECTION_3:
        for t, want in ((tokens.LIGHT, light), (tokens.DARK, dark)):
            got = ratio(t[fg], t[ground])
            assert got >= 4.5, (fg, ground, got)
            if want is not None:
                assert round(got, 1) == want, (fg, ground, got, want)


def test_settings_keep_show_hints_and_have_no_look_row(ctx):
    """Release 5.179 (the redesign's decision 840): the Look row went with the Classic look; Show hints stays."""
    from docrepo.ui.settings_view import SettingsView, update_settings

    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    assert not hasattr(view, "look") and "look" not in view.values()
    view.hints.setChecked(True)
    assert LOOK.hints  # Show hints applies at once
    assert set(update_settings(ctx, view.values())) == {"show_hints"}
    assert Settings.load(ctx.data_root).show_hints and Settings.load(ctx.data_root).look == "new"
    assert not hasattr(LOOK, "classic")


# ---- release 5.187: floating surfaces (decision 862) ----
def _palette_commands(ran: list) -> list[Command]:
    return [Command("Task", "Add a note", lambda: ran.append("note"), "N"), Command("Task", "Edit task", lambda: ran.append("edit"), "E"),
            Command("Go to", "Timeline", lambda: ran.append("timeline")), Command("Go to", "Today", lambda: ran.append("today"), "F5"),
            Command("", "Keys", lambda: ran.append("keys"), "F1")]


def _palette_rows(p) -> list[tuple[object, str]]:
    from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE

    return [(p.list.topLevelItem(i).data(0, KEY_ROLE), p.list.topLevelItem(i).data(0, HTML_ROLE)) for i in range(p.list.topLevelItemCount())]


def test_the_palette_names_each_group_once(qapp):
    """With nothing typed, each run of one group has a head, which never runs, and a command's row is its name alone; typed,
    the rows are ranked with no heads, each with its group after its name."""
    from docrepo.ui.palette import ROW, CommandPalette

    ran: list[str] = []
    host = QWidget()  # kept, or the palette goes with it
    p = CommandPalette(host, _palette_commands(ran))
    rows = _palette_rows(p)
    heads = [html for key, html in rows if key is None]
    assert len(heads) == 3 and "Task" in heads[0] and "Go to" in heads[1] and "More" in heads[2]
    assert all('class="pgroup"' in h for h in heads)
    assert [key for key, _ in rows] == [None, 0, 1, None, 2, 3, None, 4]
    assert all("Task" not in html and "pgroup" not in html for key, html in rows if key is not None)
    assert p.list.height() == len(rows) * ROW + 12
    assert p.box.objectName() == "paletteBox"
    p.box.setText("edit")
    rows = _palette_rows(p)
    assert all(key is not None for key, _ in rows) and "Edit task" in rows[0][1] and '<span class="pgroup">Task</span>' in rows[0][1]
    p.deleteLater()


def test_the_palettes_keys_go_past_its_heads(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from docrepo.ui.palette import CommandPalette
    from docrepo.ui.tree_view import KEY_ROLE

    ran: list[str] = []
    host = QWidget()  # kept, or the palette goes with it
    p = CommandPalette(host, _palette_commands(ran))
    assert p.list.currentItem().data(0, KEY_ROLE) == 0
    QTest.keyClick(p.box, Qt.Key.Key_Up)  # from the first command to the last, past the heads
    assert p.list.currentItem().data(0, KEY_ROLE) == 4
    QTest.keyClick(p.box, Qt.Key.Key_Down)
    assert p.list.currentItem().data(0, KEY_ROLE) == 0
    QTest.keyClick(p.box, Qt.Key.Key_Down)
    QTest.keyClick(p.box, Qt.Key.Key_Down)
    QTest.keyClick(p.box, Qt.Key.Key_Return)
    assert ran == ["timeline"]
    p._run_item(p.list.topLevelItem(0))  # a head never runs
    assert ran == ["timeline"]
    p.deleteLater()


def test_a_floating_window_asks_windows_for_its_corners_and_edge(qapp, monkeypatch):
    from docrepo.ui import look

    calls = []
    monkeypatch.setattr(look, "dwm_set", lambda window, attribute, value: calls.append((attribute, value)) or True)
    w = QWidget()
    look.dress_window(w)
    # release 5.194: every window's frame light or dark with the theme, then its caption colour
    assert [a for a, _v in calls] == [look.DWMWA_USE_IMMERSIVE_DARK_MODE, look.DWMWA_CAPTION_COLOR]
    calls.clear()
    look.floating(w)
    assert w.property("floating") is True
    look.dress_window(w)
    edge = QColor(tokens.colour("stroke_strong"))
    assert calls == [(look.DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if tokens.theme() == "dark" else 0), (look.DWMWA_WINDOW_CORNER_PREFERENCE, look.DWMWCP_ROUND),
                     (look.DWMWA_BORDER_COLOR, edge.red() | edge.green() << 8 | edge.blue() << 16)]
    calls.clear()
    look.square(w, True)
    look.square(w, False)
    assert calls == [(look.DWMWA_WINDOW_CORNER_PREFERENCE, look.DWMWCP_DONOTROUND), (look.DWMWA_WINDOW_CORNER_PREFERENCE, look.DWMWCP_ROUND)]
    w.deleteLater()
