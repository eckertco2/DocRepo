"""Opening a task (release 5.174, the design workspace's docs/mods/today-workspace-carry-plan.md, decision 815): one
helper, ``task_open.open_task``, that every place a task is opened calls, as Settings' Open a task in says, Shift the other
way; a collection at its page; a link inside a page still at the task's page. Offscreen, over made-up sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import task_open, task_search, today_panel  # noqa: E402
from docrepo.ui import workspace as workspace_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
RIGGING, HOLIDAY = "T000012", "T000016"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW), None)
    w.menus = []
    w.show_browse()
    w.resize(1440, 900)
    yield w
    if getattr(w, "workspace", None) is not None:
        w.workspace.pane.notes.save_now()
    w.deleteLater()


def opened(browse) -> str:
    """Where the last open went: "workspace" with its task, or "page" with the selected task."""
    if workspace_ui.is_open(browse):
        return f"workspace:{browse.workspace.here}"
    return f"page:{browse.sel[1]}" if browse.sel and browse.sel[0] == "task" else "nowhere"


def back(browse) -> None:
    if workspace_ui.is_open(browse):
        browse.workspace.close_to_origin()


def test_the_helper_follows_the_setting_and_shift_gives_the_other(browse):
    task_open.open_task(browse, RIGGING)
    assert opened(browse) == f"workspace:{RIGGING}"
    back(browse)
    task_open.open_task(browse, RIGGING, other=True)
    assert opened(browse) == f"page:{RIGGING}"
    browse.ctx.settings.open_tasks_in = "page"
    task_open.open_task(browse, HOLIDAY)
    assert opened(browse) == f"page:{HOLIDAY}"
    task_open.open_task(browse, HOLIDAY, other=True)
    assert opened(browse) == f"workspace:{HOLIDAY}"


def test_shift_with_a_double_click_opens_the_other(browse, monkeypatch):
    browse.set_view("tasks")
    browse.render_list()
    monkeypatch.setattr(task_open, "shift_held", lambda: True)
    workspace_ui.open_row(browse, HOLIDAY)
    assert opened(browse) == f"page:{HOLIDAY}"
    monkeypatch.setattr(task_open, "shift_held", lambda: False)
    workspace_ui.open_row(browse, HOLIDAY)
    assert opened(browse) == f"workspace:{HOLIDAY}"


def test_a_collection_opens_at_its_page_either_way(browse):
    c = tasks.create_task(browse.conn, browse.ctx.settings, title="Job aids", at=NOW, created_by="test", collection=True)
    browse.refresh()
    assert not task_open.opens_workspace(browse, c) and not task_open.opens_workspace(browse, c, other=True)
    task_open.open_task(browse, c)
    assert opened(browse) == f"page:{c}"


def test_the_board_the_side_panel_and_task_search_open_it_so(browse, monkeypatch):
    browse.priorities.open_task.emit(HOLIDAY)
    assert opened(browse) == f"workspace:{HOLIDAY}"
    back(browse)
    monkeypatch.setattr(today_panel, "_full_screen_candidates", lambda own: [])
    panel = SimpleNamespace(browse=browse)
    today_panel.TodayPanel.open_in_browse(panel, RIGGING)
    assert opened(browse) == f"workspace:{RIGGING}" and browse.workspace.from_today
    back(browse)
    search = SimpleNamespace(then="page", app=SimpleNamespace(browse=browse))
    task_search.TaskSearch.open_task(search, HOLIDAY)
    assert opened(browse) == f"workspace:{HOLIDAY}"
    back(browse)
    task_search.TaskSearch.open_task(search, HOLIDAY, shift=True)
    assert opened(browse) == f"page:{HOLIDAY}"


def test_a_link_inside_a_page_still_goes_to_the_page(browse):
    browse.set_view("tasks")
    browse.go_task(RIGGING)
    assert opened(browse) == f"page:{RIGGING}" and not workspace_ui.is_open(browse)


def test_shift_enter_in_the_tree_opens_the_page(browse):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from docrepo.ui.tree_view import KEY_ROLE

    browse.set_view("tasks")
    browse.render_list()
    item = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", HOLIDAY))
    browse.tree.setCurrentItem(item)
    QTest.keyClick(browse.tree, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert opened(browse) == f"page:{HOLIDAY}"
    QTest.keyClick(browse.tree, Qt.Key.Key_Return)
    assert opened(browse) == f"workspace:{HOLIDAY}"
