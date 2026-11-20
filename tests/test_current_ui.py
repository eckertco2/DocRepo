"""The current task on screen (release 5.177, the design workspace's docs/mods/current-task-plan.md, decisions 826 to 830):
Work on it and W make a task current and a double-click doesn't; Stop working on it; Now on Today in the view and the side
panel, on Today and off it, shown once, with Log progress and Workspace shown at rest; the command back to it, with and
without a current task. Offscreen, over made-up sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QPushButton  # noqa: E402

from docrepo import current, edits  # noqa: E402
from docrepo import wheels_config as wc  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui import current_ui, task_open, today_panel  # noqa: E402
from docrepo.ui import task_tile as tile_ui  # noqa: E402
from docrepo.ui import workspace as workspace_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE, NOW_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
RIGGING, HOLIDAY, INSTALL = "T000012", "T000016", "T000008"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root, monkeypatch):
    conn, root, fs = sample_root
    monkeypatch.setattr(task_open, "shift_held", lambda: False)
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW), None)
    w.menus = []
    w.show_browse()
    w.resize(1440, 900)
    yield w
    if getattr(w, "workspace", None) is not None:
        w.workspace.pane.notes.save_now()
    w.deleteLater()


def now(browse) -> str | None:
    return current.get(browse.conn, Model(browse.conn))


def labels(menu: QMenu) -> list[str]:
    return [a.text().split("\t")[0] for a in menu.actions() if not a.isSeparator()]


def back(browse) -> None:
    if workspace_ui.is_open(browse):
        browse.workspace.close_to_origin()


def test_work_on_it_makes_it_current_and_a_double_click_doesnt(browse):
    task_open.open_task(browse, RIGGING)  # a plain open, in its workspace (release 5.174)
    assert workspace_ui.is_open(browse) and now(browse) is None
    back(browse)
    menu = QMenu()
    tile_ui.fill_menu(browse, RIGGING, menu)
    next(a for a in menu.actions() if a.text().startswith("Work on it")).trigger()
    assert now(browse) == RIGGING and browse.workspace.here == RIGGING
    back(browse)
    task_open.open_task(browse, HOLIDAY)  # looking another task up leaves it as it was (decision 826)
    assert now(browse) == RIGGING


def test_stop_working_on_it_is_the_current_tasks_first_line(browse):
    current_ui.work_on(browse, RIGGING)
    back(browse)
    menu = QMenu()
    tile_ui.fill_menu(browse, RIGGING, menu)
    assert labels(menu)[0] == current_ui.STOP
    other = QMenu()
    tile_ui.fill_menu(browse, HOLIDAY, other)
    assert current_ui.STOP not in labels(other)
    menu.actions()[0].trigger()
    assert now(browse) is None


def test_another_task_takes_its_place(browse):
    current_ui.work_on(browse, RIGGING)
    current_ui.work_on(browse, HOLIDAY)
    assert now(browse) == HOLIDAY


def _view_rows(browse):
    return [i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", RIGGING)]


def test_now_on_the_today_view_shown_once_on_today_or_not(browse):
    edits.add_to_today(browse.conn, browse.ctx.data_root, browse.ctx.fs, RIGGING, "", NOW)
    current.start(browse.conn, RIGGING)
    browse.refresh()
    browse.set_view("today")
    browse.render_list()
    rows = _view_rows(browse)
    assert len(rows) == 1 and rows[0].data(0, NOW_ROLE)  # under Now, not again in its band
    head = rows[0].parent()
    assert "Now" in head.text(0) or "Now" in (head.data(0, 0x0101) or "")
    buttons = [b.text() for b in browse.tree.itemWidget(head.child(1), 0).findChildren(QPushButton)]
    assert buttons == [current_ui.LOG, current_ui.WORKSPACE]
    item = next(a for a in Model(browse.conn).today_items() if a.subject == RIGGING)
    edits.close_today_item(browse.conn, browse.ctx.data_root, browse.ctx.fs, item.id, "Removed", NOW)
    browse.refresh()
    browse.render_list()
    rows = [i for i in _view_rows(browse) if i.data(0, NOW_ROLE)]
    assert len(rows) == 1  # off Today, still there (Due in the next 7 days may list it too, as a task not on Today)
    current.stop(browse.conn)
    browse.refresh()
    browse.render_list()
    assert not any(i.data(0, NOW_ROLE) for i in browse.tree.items())


@pytest.fixture
def panel(browse, monkeypatch):
    monkeypatch.setattr(today_panel, "_full_screen_candidates", lambda own: [])
    p = today_panel.TodayPanel(browse.ctx, browse, SimpleNamespace(config=wc.WheelsConfig(wheels=())))
    p.open_panel()
    yield p
    p.close_panel()
    p.deleteLater()


def test_now_in_the_side_panel_at_rest_with_its_two_buttons(browse, panel):
    edits.add_to_today(browse.conn, browse.ctx.data_root, browse.ctx.fs, RIGGING, "", NOW)
    edits.add_to_today(browse.conn, browse.ctx.data_root, browse.ctx.fs, HOLIDAY, "", NOW)
    current.start(browse.conn, RIGGING)
    panel.refresh()
    assert panel.now_row is not None and panel.now_row.task_id == RIGGING
    assert RIGGING not in [r.task_id for r in panel.rows] and HOLIDAY in [r.task_id for r in panel.rows]  # shown once
    box = panel.now_row.parentWidget()
    shown = [b.text() for b in box.findChildren(QPushButton) if b.isVisibleTo(panel) and b.text() in (current_ui.LOG, current_ui.WORKSPACE)]
    assert not panel.hover.wide and shown == [current_ui.LOG, current_ui.WORKSPACE]  # at rest, always shown
    assert box.height() > panel.rows[0].height()  # the one taller row
    assert panel.count.property("total") == 2
    current.stop(browse.conn)
    panel.refresh()
    assert panel.now_row is None


def test_now_in_the_side_panel_when_its_not_on_today(browse, panel):
    current.start(browse.conn, INSTALL)
    panel.refresh()
    assert panel.now_row is not None and panel.now_row.item_id is None and not panel.now_row.tick.isVisibleTo(panel)


def test_one_read_of_the_current_task_for_a_draw(browse, panel, monkeypatch):
    """The plan's scale check: Today's drawing, the view's or the side panel's, reads the current task once."""
    edits.add_to_today(browse.conn, browse.ctx.data_root, browse.ctx.fs, RIGGING, "", NOW)
    current.start(browse.conn, RIGGING)
    browse.refresh()
    browse.set_view("today")
    reads = []
    real = current.get_state

    def counted(conn, key):
        if key == current.KEY:
            reads.append(key)
        return real(conn, key)

    monkeypatch.setattr(current, "get_state", counted)
    browse.render_list()
    assert len(reads) == 1
    reads.clear()
    panel.refresh()
    assert len(reads) == 1


def test_the_command_back_to_it(browse):
    assert current_ui.back_to_it(browse) is False and current_ui.NONE_YET in browse.status.text()
    current.start(browse.conn, RIGGING)
    assert current_ui.back_to_it(browse) and workspace_ui.is_open(browse) and browse.workspace.here == RIGGING


def test_the_hotkey_is_last_and_the_command_is_registered():
    from docrepo import hotkey
    from docrepo.ui import wheel_commands

    assert hotkey.HOTKEYS[-1][0] == "current_hotkey" and "current.open" in wheel_commands.REGISTRY


def test_the_workspace_bars_toggle_both_ways(browse):
    task_open.open_task(browse, RIGGING)
    toggle = browse.workspace.current_button
    assert toggle.text() == current_ui.WORK_ON_THIS and not toggle.isChecked()
    toggle.click()
    assert now(browse) == RIGGING and toggle.text() == current_ui.WORKING_ON_THIS and toggle.isChecked()
    toggle.click()
    assert now(browse) is None and toggle.text() == current_ui.WORK_ON_THIS


def test_w_makes_the_selected_task_current(browse):
    browse.set_view("tasks")
    browse.go_task(HOLIDAY)
    # W is a command only while nothing is being typed in (`_typing` reads the whole app's focus), so the browse window is
    # made the one in front first: a window an earlier test file left open may still hold the keyboard in a text box.
    browse.activateWindow()
    browse.tree.setFocus()
    QApplication.processEvents()
    assert not browse._typing()
    workspace_ui.work_key(browse)
    assert now(browse) == HOLIDAY and workspace_ui.is_open(browse) and browse.workspace.current_button.isChecked()
