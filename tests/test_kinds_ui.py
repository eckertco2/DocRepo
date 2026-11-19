"""Collections in the browse window (release 5.167, the design workspace's docs/mods/collections-and-kinds-plan.md,
decisions 779, 781 and 783): the row's kind lines, a collection's menu in the state's place with Archive, Restore and
Make it a task, Edit task with a collection's four fields, the tile's folder, and the Timeline's Show routine starting
off. Offscreen, over the made-up sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from docrepo import collection_edits, task_tile, tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui import collections_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.state_menu import MAKE_TASK, state_menu  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402
from docrepo.ui.timeline_view import TimelineView  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
HOLIDAY = "T000016"  # a single task with no subtasks
VERIFY = "T000002"  # with two subtasks


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW), None)
    w.menus = []
    w.show_browse()
    QApplication.processEvents()
    yield w
    w.deleteLater()


def labels(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_a_rows_kind_lines(browse):
    menu = QMenu()
    collections_ui.add_kind_lines(browse, VERIFY, menu)
    assert labels(menu) == [collection_edits.MAKE, collection_edits.MAKE_ALL]
    menu = QMenu()
    collections_ui.add_kind_lines(browse, HOLIDAY, menu)
    assert labels(menu) == [collection_edits.MAKE]  # nothing under it


def test_make_it_a_collection_from_a_row_and_back_from_its_menu(browse):
    collections_ui.run(browse, HOLIDAY, "collection")
    m = browse.model()
    assert m.task(HOLIDAY).collection
    menu = state_menu(None, m, HOLIDAY, lambda to, branch: None)
    assert labels(menu) == [collection_edits.ARCHIVE, collection_edits.MAKE_TASK]
    assert browse.set_state(HOLIDAY, MAKE_TASK)
    assert not browse.model().task(HOLIDAY).collection


def test_archive_restore_and_undo_from_the_collections_menu(browse):
    collections_ui.make_collection(browse, VERIFY)
    picked: list[tuple[str, bool]] = []
    menu = state_menu(None, browse.model(), VERIFY, lambda to, branch: picked.append((to, branch)))
    assert labels(menu) == [collection_edits.ARCHIVE, collection_edits.ARCHIVE_ALL, collection_edits.MAKE_TASK]
    menu.actions()[1].trigger()
    assert picked == [("Closed", True)]
    assert browse.set_state(VERIFY, "Closed", True)
    m = browse.model()
    assert m.task(VERIFY).state == "Closed" and m.task("T000017").state == "Closed"
    assert "Archived: Verification walkthrough readiness and 2 under it." in browse.status.text()
    menu = state_menu(None, m, VERIFY, lambda to, branch: None)
    assert labels(menu)[0] == collection_edits.RESTORE
    assert browse.set_state(VERIFY, collection_edits.RESTORED_STATE)
    assert browse.model().task(VERIFY).state == collection_edits.RESTORED_STATE


def test_the_tile_has_a_folder_and_no_days(browse):
    conn = browse.conn
    tasks.update_task(conn, browse.ctx.settings, HOLIDAY, at=NOW, via="test", due="2026-10-09", urgent=True)
    collections_ui.make_collection(browse, HOLIDAY)
    m = browse.model()
    tl = task_tile.tile(m, HOLIDAY, NOW.date())
    assert tl.state == task_tile.COLLECTION_STATE and tl.days is None and not tl.urgent and tl.priority == ""
    assert "mark:co" in task_tile.circle_html(tl)


def test_edit_task_for_a_collection_has_four_fields(browse):
    collections_ui.make_collection(browse, HOLIDAY)
    m = browse.model()
    d = TaskEditDialog(None, m, HOLIDAY, [], [])
    try:
        assert d.windowTitle() == f"Edit collection {HOLIDAY}"
        assert set(d.values()) == {"title", "description", "labels", "inherit_labels", "parents"}
        assert d.title.isVisibleTo(d) and d.description.isVisibleTo(d) and d.labels.isVisibleTo(d)
        assert not d.state.isVisibleTo(d) and not d.due.isVisibleTo(d) and not d.urgent.isVisibleTo(d)
    finally:
        d.deleteLater()
    t = Model(browse.conn).task("T000001")
    d = TaskEditDialog(None, Model(browse.conn), t.id, [], [])
    try:
        assert "state" in d.values() and d.state.isVisibleTo(d)
    finally:
        d.deleteLater()


def test_the_timelines_show_routine_starts_off(qapp):
    v = TimelineView()
    try:
        assert v.routine is False
        v.restore({"routine": True})  # saved before 5.167: not kept
        assert v.routine is False
        v.restore({"routine": True, "routine_v": 1})
        assert v.routine is True and v.settings()["routine_v"] == 1
    finally:
        v.deleteLater()
