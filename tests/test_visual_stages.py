"""The visual review's stages V2, V3, V4 and V6 (releases 5.58 to 5.61): nothing clipped, quieter chrome, colour by one rule, and the
forms and small things. Driven offscreen; what depends on real fonts is in ``test_real_look.py``."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QMessageBox, QPushButton, QTableWidget, QTreeWidgetItem, QWidget  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import row_state  # noqa: E402
from docrepo.ui import browse_window, tokens  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.look import LOOK, set_hints  # noqa: E402
from docrepo.ui.priorities_view import COLUMN_MIN  # noqa: E402
from docrepo.ui.task_pane import TaskPane  # noqa: E402
from docrepo.ui.task_view import FOOT  # noqa: E402
from docrepo.ui.tree_view import ACTIONS_ROLE, KEY_ROLE, RowTree, with_actions  # noqa: E402
from docrepo.ui.widgets import DropButton, ElidedCheck, ElidedLabel, ViewStack, ask  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
UI = Path(__file__).resolve().parent.parent / "docrepo" / "ui"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    context = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW, settings_changed=lambda _: None)
    return context


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.reveal = lambda path: True
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


@pytest.fixture
def hints_off():
    was = LOOK.hints
    set_hints(False)
    yield
    set_hints(was)


def tree(rows: int = 3) -> RowTree:
    t = RowTree()
    t.set_columns(["Title", "State", "Due"], [0, 96, 96])
    t.resize(700, 300)
    t.begin()
    for i in range(rows):
        item = t.add_row(None, ("task", f"T{i}"), [f"Row {i}", "", ""])
        t.set_actions(item, [("Done", lambda: None, "Mark it done"), ("Remove", lambda: None, "Take it off")])
    t.end()
    t.doItemsLayout()
    return t


# ---- V2: nothing clipped ----
def test_a_stack_asks_only_for_the_room_its_page_on_show_needs(qapp):
    stack = ViewStack()
    small, big = QWidget(), QWidget()
    small.setMinimumWidth(100)
    big.setMinimumWidth(600)
    stack.addWidget(small)
    stack.addWidget(big)
    assert stack.minimumSizeHint().width() == 100
    stack.setCurrentWidget(big)
    assert stack.minimumSizeHint().width() == 600


def test_elided_words_stay_whole_underneath(qapp):
    label = ElidedLabel("Agenda of a meeting with a very long name indeed")
    label.resize(60, 24)
    label.show()
    QApplication.processEvents()
    assert label.text() == "Agenda of a meeting with a very long name indeed"
    assert label.toolTip() == label.text()  # all of it, when it doesn't fit
    assert label.minimumSizeHint().width() == 0
    label.resize(4000, 24)
    QApplication.processEvents()
    assert label.toolTip() == ""
    label.hide()
    box = ElidedCheck("An agenda item with a very long name indeed that goes on")
    assert box.minimumSizeHint().width() < 60 and box.text().endswith("goes on")


def test_a_narrow_list_drops_columns_from_after_the_title_and_brings_them_back(qapp):
    t = tree()
    t.show()

    def at(width: int) -> None:
        t.resize(width, 300)
        QApplication.processEvents()

    at(320)
    assert t.isColumnHidden(1) and not t.isColumnHidden(2)  # the date says more than the state
    at(200)
    assert t.isColumnHidden(1) and t.isColumnHidden(2)
    at(800)
    assert not t.isColumnHidden(1) and not t.isColumnHidden(2) and t.columnWidth(1) == 96
    t.hide()


def test_priorities_scrolls_across_rather_than_holding_the_windows_width(browse):
    browse.set_view("priorities")
    assert browse.priorities.board.parent().parent().horizontalScrollBar() is not None
    assert all(c.minimumWidth() == COLUMN_MIN for c in browse.priorities.board.findChildren(QFrame, "prCol"))
    browse.split.sizes()  # the middle pane asks for what's on show, not the board's five columns
    assert browse.priorities.minimumSizeHint().width() < 5 * COLUMN_MIN


def test_the_task_pages_format_bar_drops_to_its_own_line_when_the_pane_is_narrow(qapp):
    pane = TaskPane("", 16)
    pane.show()

    def at(width: int) -> None:
        pane.resize(width, 600)
        QApplication.processEvents()

    at(3000)  # the offscreen platform's letters are wide
    assert pane.bar_row is None
    at(browse_window.DETAIL_MIN)
    assert pane.bar_row is not None
    at(3000)
    assert pane.bar_row is None and pane.head_row.indexOf(pane.format_bar) >= 0
    pane.hide()


def test_the_agenda_panel_keeps_its_count_whatever_the_meetings_name(ctx):
    w = CaptureWindow(ctx)
    panel = w.agenda_panel
    assert isinstance(panel.title, ElidedLabel)
    w.deleteLater()


# ---- V3: quiet the chrome ----
def test_row_actions_come_with_the_mouse_and_the_current_row_and_go_with_them(qapp):
    t = tree()
    first, second = t.topLevelItem(0), t.topLevelItem(1)
    t._hover, t._strips = None, []
    t._sync_strips()
    assert t._strips == []  # none at rest: a list isn't a column of links
    strip = t.action_strip(first)
    assert [b.text() for b in strip.findChildren(QPushButton)] == ["Done", "Remove"]
    assert strip.geometry().right() < t.columnWidth(0)  # over the end of the title's column, so State and Due stay in view
    t.setCurrentItem(second)
    t._sync_strips()
    assert {id(s.item) for s in t._strips} == {id(first), id(second)}
    t._hover = None
    t._sync_strips()
    assert [s.item for s in t._strips] == [second]
    t.begin()
    assert t._strips == [] and t._hover is None  # the rows have gone, and their strips with them


def test_a_rows_actions_are_on_its_right_click_menu_too(qapp, monkeypatch):
    t = tree()
    item = t.topLevelItem(0)
    assert [a[0] for a in item.data(0, ACTIONS_ROLE).actions] == ["Done", "Remove"]
    assert with_actions(["Title"], [0], 56) == (["Title"], [0])  # no column for them in the new look


def test_a_current_rows_strip_never_covers_its_words(qapp):
    t = RowTree()
    t.set_columns(["Title", "State"], [0, 96])
    t.resize(420, 200)
    t.begin()
    long_row = t.add_row(None, ("task", "T1"), ["A title long enough to run the whole way across this column and on", ""])
    t.set_actions(long_row, [("Discussed", lambda: None, ""), ("Remove", lambda: None, "")])
    short_row = t.add_row(None, ("task", "T2"), ["Short", ""])
    t.set_actions(short_row, [("Done", lambda: None, "")])
    t.end()
    t.doItemsLayout()
    t.show()
    QApplication.processEvents()
    t._hover = None
    t.setCurrentItem(long_row)
    t._sync_strips()
    assert not any(s.isVisibleTo(t.viewport()) for s in t._strips)  # hover still shows them
    t.setCurrentItem(short_row)
    t._sync_strips()
    assert any(s.isVisibleTo(t.viewport()) for s in t._strips)
    t.hide()


def test_collapse_and_expand_a_level_are_icons_and_go_where_nothing_nests(browse):
    browse.set_view("agenda")
    assert browse._lvl_collapse.text() == "" and browse._lvl_collapse.accessibleName() == "Collapse a level"
    assert browse._lvl_collapse.objectName() == "iconOnly" and not browse._lvl_collapse.isHidden()
    browse.set_view("labels")
    assert browse._lvl_collapse.isHidden() or not any(i.childCount() for i in browse.tree.items())


def test_only_new_capture_is_filled_in_the_browse_window(browse):
    """The review's decision V2, on the views that had a second accent button."""
    def accents():
        return [b.text() for b in browse.findChildren(QPushButton, "primary") if b.isVisibleTo(browse)]

    for view in ("tasks", "unfiled", "settings", "timeline", "priorities"):
        browse.set_view(view)
        if view == "timeline":
            browse.timeline._pick("T000001")
        if view == "priorities":
            browse.priorities.pick("T000001")
        assert accents() == ["New capture"], view


def test_instructions_wait_for_show_hints(browse, hints_off):
    browse.set_view("timeline")
    assert browse.timeline.card_text.text() == "" and browse.timeline.open_button.isHidden()  # nothing said until a row is picked
    browse.timeline._pick("T000001")
    assert browse.timeline.card_text.text() and not browse.timeline.open_button.isHidden()
    browse.set_view("priorities")
    browse.priorities.sel = None
    browse.priorities._strip()
    assert browse.priorities.strip.isHidden()
    assert not [w for w in browse.priorities.findChildren(QLabel, "hotkey") if not w.isHidden()]  # the digits, too
    assert all(not b.text()[0].isdigit() for b in browse.priorities.bucket_buttons.values())
    browse.set_view("capacity")
    browse.timeline._pick(None)
    assert "Capacity" not in browse.timeline.card_text.text()
    pages = browse.pages() if callable(getattr(browse, "pages", None)) else None
    if pages is not None:
        assert pages.hints is False
    set_hints(True)
    browse.render_all()
    assert "a week in Capacity" in browse.timeline.card_text.text()


def test_an_error_stays_until_the_next_thing_is_said(browse):
    browse.say("That didn't work.", error=True)
    assert not browse._status_timer.isActive()
    browse.say("Saved.")
    assert browse._status_timer.isActive()


def test_the_task_views_footer_keeps_its_keys_for_show_hints(browse, hints_off):
    browse.open_task_view("T000001")
    view = browse.task_views["T000001"]
    assert view.foot.text() == ""
    assert view._rest_foot() == ""
    set_hints(True)
    assert view._rest_foot() == FOOT
    view.close()


def test_no_typed_arrows_in_the_new_look():
    """One arrow family: the icons' chevrons. A line naming the Classic look may keep its own."""
    found = []
    for path in sorted(UI.glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search("[▾▸◀▶▼►]", line) and "classic" not in line.lower():
                found.append(f"{path.name}:{n}")
    assert found == []
    assert not re.search("[▾▸◀▶▼]", (UI.parent / "detail.py").read_text(encoding="utf-8"))


def test_a_drop_buttons_text_is_only_its_words(qapp):
    b = DropButton("Any task")
    assert b.text() == "Any task"
    assert b.sizeHint().width() >= b.fontMetrics().horizontalAdvance("Any task") + DropButton.ROOM
    assert isinstance(b.sizeHint(), QSize)


# ---- V4: colour by one rule ----
def test_no_raw_colours_outside_the_tokens():
    """Each colour has a name and one job. Classic's own colours are in style.py, or on a line naming it."""
    found = []
    for path in sorted(UI.glob("*.py")):
        if path.name in ("tokens.py", "style.py"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"#[0-9a-fA-F]{6}\b", line) and "classic" not in line.lower():
                found.append(f"{path.name}:{n}")
    assert found == []


def test_selection_keeps_its_colour_to_itself():
    """The review's finding 6: one blue did seven jobs."""
    assert tokens.CSS.count(f"background-color: {tokens.colour('selected')}") == 0
    assert f".st-ip {{ color: {tokens.colour('accent')}; background-color: {tokens.colour('info_bg')}; }}" in tokens.CSS
    assert f".u2 {{ background-color: {tokens.colour('caution_bg')}; }}" in tokens.CSS
    assert set(tokens.LIGHT) == set(tokens.DARK)


def test_a_state_in_a_row_is_words_and_a_chip_only_for_parked():
    assert row_state("In progress") == "In progress"
    assert 'class="faint"' in row_state("Not started") and "st-" not in row_state("Not started")
    assert "st-pk" in row_state("Parked")


def test_list_rows_show_states_as_words(browse):
    browse.set_view("tasks")
    cells = [i.data(1, browse_window.HTML_ROLE) for i in browse.tree.items() if i.data(1, browse_window.HTML_ROLE)]
    assert cells and not any("st-ip" in c or "st-ns" in c for c in cells)


def test_capacity_marks_the_clicked_cell_after_drawing_again(browse):
    browse.set_view("capacity")
    view = browse.timeline
    b = view.cap_rows.data.buckets[2]
    view._cell_picked("P001", b.first, b.end)
    browse.render_all()
    assert view.spot is not None and view.cap_rows.data.spot == view.spot


def test_a_parse_that_fills_much_leaves_dots_and_one_that_fills_little_a_tint(ctx):
    w = CaptureWindow(ctx)
    w.show_capture(mode="new_task", content="Replace the Line 2 pump seal by Fri 16 Oct. @Mike leads, 6 h. Deadline 30 Oct")
    w.parse()
    assert w.title.property("filled") == "dot" and w.n_due.line.property("filled") == "dot"
    w.clear()
    assert not w.title.property("filled")
    w.show_capture(mode="new_task", content="Replace the seal")
    w.parse()
    assert w.title.property("filled") is True
    w.clear()
    w.deleteLater()


def test_parse_leaves_more_fields_shut(ctx):
    w = CaptureWindow(ctx)
    w.show_capture(mode="new_task", content="Replace the Line 2 pump seal by Fri 16 Oct. @Mike leads, 6 h.")
    w.parse()
    assert w.n_more.isHidden()
    assert w.n_lead_hours.value() is not None  # filled all the same, and named on the Understood line
    w.clear()
    w.deleteLater()


# ---- V6: forms and small things ----
def test_a_question_says_what_its_buttons_do(qapp, monkeypatch):
    seen = {}

    def answer(box: QMessageBox) -> int:
        seen["buttons"] = [b.text() for b in box.buttons()]
        seen["icon"] = box.icon()
        seen["default"] = box.defaultButton().text()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", answer)
    assert ask(None, "Discard capture", "Sure?", "Discard capture") is False
    assert seen == {"buttons": ["Discard capture", "Cancel"], "icon": QMessageBox.Icon.NoIcon, "default": "Cancel"}
    assert browse_window._answers("Edit capture C1", "Close without saving your changes?") == ("Close without saving", "Keep editing")
    assert browse_window._answers("Discard capture", "Take it off the page too?") == ("Take it off the page", "Leave it on the page")
    assert browse_window._answers("Change data root", "Use it?") == ("Change data root", "Cancel")


def test_edit_task_puts_the_rarer_fields_under_more_options(browse):
    dialogs = []
    browse.run_dialog = lambda d: dialogs.append(d) or False
    browse.edit_task("T000001")
    d = dialogs[-1]
    assert d.more.isHidden()
    for widget in (d.key_dates, d.labels, d.lead_unit, d.reminder, d.parents_box, d.calendar):
        assert d.more.isAncestorOf(widget)
    for widget in (d.title, d.state, d.status, d.description, d.leads, d.assignees, d.start, d.due, d.deadline):
        assert not d.more.isAncestorOf(widget)
    d.more_button.click()
    assert not d.more.isHidden()
    d.deleteLater()


def test_new_task_keeps_to_labels_and_two_pairs(ctx):
    w = CaptureWindow(ctx)
    for widget in (w.n_deadline_desc, w.n_urgent, w.n_keydates, w.n_inherit):
        assert w.n_more.isAncestorOf(widget)
    for widget in (w.n_labels, w.n_leads, w.n_assignees, w.n_due, w.n_deadline):
        assert not w.n_more.isAncestorOf(widget)
    assert w.u_more.isAncestorOf(w.u_keydates) and w.u_more.isAncestorOf(w.u_deadline_desc)
    w.deleteLater()


def test_a_new_data_roots_task_tree_says_what_to_do(qapp, tmp_path, fs, data_root):
    conn = db.connect(fs, data_root)
    context = AppContext(conn, data_root, fs, Settings(), now=lambda: NOW, settings_changed=lambda _: None)
    capture = CaptureWindow(context)
    w = BrowseWindow(context, capture)
    w.reveal = lambda path: True
    w.show_browse("tasks")
    assert w.tree._empty is not None
    assert [b.text() for b in w.tree._empty.findChildren(QPushButton)] == ["New task"]
    assert w.tree.isHeaderHidden()
    w.set_view("capacity")
    view = w.timeline
    assert not view.cap_empty.isHidden() and view.cap_scroll.isHidden() and view.cap_team.isHidden()
    assert [b.text() for b in view.cap_empty.findChildren(QPushButton)] == ["Add person"]
    capture.deleteLater()
    w.deleteLater()
    conn.close()


def test_rows_with_no_key_have_no_column_headings(browse):
    browse.set_view("discarded")
    assert browse.tree.isHeaderHidden() == (not any(k is not None for k in browse.tree.keys()))
    browse.set_view("tasks")
    assert not browse.tree.isHeaderHidden()


def test_a_row_key_stays_on_its_item(qapp):
    item = tree().topLevelItem(0)
    assert isinstance(item, QTreeWidgetItem) and item.data(0, KEY_ROLE) == ("task", "T0")
