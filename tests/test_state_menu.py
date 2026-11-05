"""A task's state from its row (release 5.76, round 7's item 101, decisions 360 to 364): the State cell as a button that
opens a menu of the four states, a State submenu on every task row's right-click menu and on the Priorities and timeline
cards, a pick saved at once as "Browse tool" with no capture, Undo for ten seconds, and "Closed, with its n open subtasks".
Offscreen, over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QAction, QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from docrepo import edits, wheels_config  # noqa: E402
from docrepo.activity import Activity, window  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.state_menu import UNDO_MS, open_below, state_menu  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE, LINE_ROLE, ROW_ICON, STATE_ICONS, STATE_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
INSTALLATION = "T000008"
RIGGING = "T000012"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW), None)
    w.menus = []
    w.show_browse()
    w.resize(1600, 900)  # wide enough for the State column, which a narrow list drops (release 5.58)
    QApplication.processEvents()
    yield w
    for view in list(w.task_views.values()):
        view.close()
    w.deleteLater()


def labels(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def find(menu: QMenu, label: str) -> QAction | None:
    """An action by its words, in a menu or its submenus."""
    for a in menu.actions():
        if a.text() == label or label.endswith("…") and a.text().startswith(label[:-1]):
            return a
        if a.menu() is not None:
            found = find(a.menu(), label)
            if found is not None:
                return found
    return None


def picking(w: BrowseWindow, label: str | None) -> None:
    """Menus shown from now on are noted and, with ``label``, the action with those words is picked, as a click would."""
    def run(menu: QMenu, at: QPoint) -> None:
        w.menus.append([labels(menu), *[labels(a.menu()) for a in menu.actions() if a.menu() is not None]])
        a = find(menu, label) if label else None
        if a is not None:
            a.trigger()
    w.run_menu = run


def row(w: BrowseWindow, task_id: str):
    return next(item for item in w.tree.items() if item.data(0, KEY_ROLE) == ("task", task_id))


def shown(w: BrowseWindow) -> str:
    """The status line's words, without its Undo link."""
    return w.status.text().split(" &nbsp;<a ")[0]


def undo_offered(w: BrowseWindow) -> bool:
    return 'href="undo"' in w.status.text() and w._undo is not None


def states(w: BrowseWindow, *ids: str) -> list[str]:
    m = w.model()
    return [m.task(x).state for x in ids]


# ---- the menu ----
def test_the_menu_has_the_four_states_and_the_branch(qapp, sample_root):
    conn, _, _ = sample_root
    m = Model(conn)
    picked = []
    menu = state_menu(None, m, INSTALLATION, lambda s, branch: picked.append((s, branch)))
    below = open_below(m, INSTALLATION)
    assert len(below) >= 2 and all(m.task(x).state != "Closed" for x in below)
    assert labels(menu) == ["Not started", "In progress", "Parked", "Closed", f"Closed, with its {len(below)} open subtasks"]
    assert [a.text() for a in menu.actions() if a.isChecked()] == [m.task(INSTALLATION).state]  # the current one ticked
    assert menu.activeAction().text() == m.task(INSTALLATION).state  # where the keyboard starts
    find(menu, "Parked").trigger()
    find(menu, "Closed, with its…").trigger()
    assert picked == [("Parked", False), ("Closed", True)]
    # Every open level below counts, not only the children.
    assert set(below) >= set(m.children_of(INSTALLATION)) - {x for x in m.children_of(INSTALLATION) if m.task(x).state == "Closed"}


def test_a_closed_task_has_no_branch_line_and_one_with_no_subtasks_neither(qapp, sample_root):
    conn, root, fs = sample_root
    edits.set_states(conn, root, fs, Settings(me="P001"), {RIGGING: "Closed"}, NOW)
    m = Model(conn)
    assert labels(state_menu(None, m, RIGGING, lambda *a: None)) == ["Not started", "In progress", "Parked", "Closed"]


def test_set_states_logs_as_the_browse_tool_with_no_capture(sample_root):
    conn, root, fs = sample_root
    before = Model(conn)
    out = edits.set_states(conn, root, fs, Settings(me="P001"), {RIGGING: "Closed", INSTALLATION: "Parked"}, NOW)
    m = Model(conn)
    assert out.message == "2 changes in the status log." and len(m.captures) == len(before.captures)
    new = [e for e in m.status if e not in before.status]
    assert {(e.task, e.field, e.to_value, e.via) for e in new} >= {(RIGGING, "State", "Closed", "Browse tool"), (INSTALLATION, "State", "Parked", "Browse tool")}
    assert m.task(RIGGING).closed  # the day it closed, as Edit task records it
    # Activity lists them as changes made outside a capture.
    lines = Activity(m, NOW.date()).lines(*window("week", NOW.date()))
    assert any(x.kinds == ["change"] and x.task == RIGGING and NOW.strftime("%Y-%m-%d") == x.at[:10] for x in lines)


# ---- the browse window's lists ----
def icon_at(w: BrowseWindow, item) -> QPoint:
    """The middle of a row's icon, before its title: in the new look, the state's button (release 5.78's decision L7)."""
    rect = w.tree.visualRect(w.tree.indexFromItem(item, 0))
    return QPoint(rect.left() + w.tree.cell_pad + 2 + ROW_ICON // 2, rect.center().y())


def title_at(w: BrowseWindow, item) -> QPoint:
    """A point on a row's title, after its icon."""
    rect = w.tree.visualRect(w.tree.indexFromItem(item, 0))
    return QPoint(rect.left() + w.tree.cell_pad + 2 + ROW_ICON + 30, rect.center().y())


def in_sight(w: BrowseWindow, item) -> None:
    parent = item.parent()
    while parent is not None:  # its row in sight, under its open parents
        parent.setExpanded(True)
        parent = parent.parent()
    w.tree.scrollToItem(item)
    QApplication.processEvents()


def test_a_task_rows_state_icon_is_a_button(browse):
    """The new look has no State column (release 5.78): the state's icon before the title is the button."""
    browse.show_browse(view="tasks")
    header = browse.tree.headerItem()
    assert "State" not in [header.text(i) for i in range(browse.tree.columnCount())]
    item = row(browse, INSTALLATION)
    assert item.data(0, STATE_ROLE) == INSTALLATION
    line = item.data(0, LINE_ROLE)
    assert line.icon_tip == states(browse, INSTALLATION)[0] and line.icon == STATE_ICONS[line.icon_tip][0]
    assert browse.tree.row_task(item) == INSTALLATION


def test_a_click_opens_the_menu_and_doesnt_pick_the_row(browse):
    picking(browse, "Parked")
    item = row(browse, RIGGING)
    in_sight(browse, item)
    current = browse.tree.currentItem()
    QTest.mouseClick(browse.tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, icon_at(browse, item))
    assert browse.menus and browse.menus[0][0][:4] == ["Not started", "In progress", "Parked", "Closed"]
    assert states(browse, RIGGING) == ["Parked"]
    assert browse.tree.currentItem() is current or browse.tree.currentItem().data(0, KEY_ROLE) != ("task", RIGGING)
    assert shown(browse) == "Parked: Rigging plan." and undo_offered(browse)


def test_closed_leaves_the_open_list_and_undo_brings_it_back(browse):
    picking(browse, "Closed")
    was = states(browse, RIGGING)[0]
    browse.popup_state_menu(RIGGING, QPoint(0, 0))
    assert states(browse, RIGGING) == ["Closed"]
    assert ("task", RIGGING) not in browse.tree.keys()  # the task tree shows open tasks: it's gone at once
    assert shown(browse) == "Closed: Rigging plan."
    assert undo_offered(browse) and browse._status_timer.interval() == UNDO_MS
    browse.status.linkActivated.emit("undo")
    assert states(browse, RIGGING) == [was] and ("task", RIGGING) in browse.tree.keys()
    assert browse.status.text() == "Set back. The status log keeps both changes." and not undo_offered(browse)
    changes = [(e.from_value, e.to_value) for e in browse.model().status if e.task == RIGGING and e.field == "State" and e.at.startswith("2026-10-08 14:10")]
    assert changes == [(was, "Closed"), ("Closed", was)]


def test_picking_the_state_it_has_changes_nothing(browse):
    picking(browse, states(browse, INSTALLATION)[0])
    count = len(browse.model().status)
    browse.popup_state_menu(INSTALLATION, QPoint(0, 0))
    assert len(browse.model().status) == count and not undo_offered(browse)


def test_a_branch_closes_every_open_level_and_one_undo_takes_it_back(browse):
    m = browse.model()
    below = open_below(m, INSTALLATION)
    was = states(browse, INSTALLATION, *below)
    picking(browse, "Closed, with its…")
    browse.popup_state_menu(INSTALLATION, QPoint(0, 0))
    assert set(states(browse, INSTALLATION, *below)) == {"Closed"}
    n = len(below)
    assert shown(browse) == f"Closed: Installation and its {n} open subtask{'s' if n != 1 else ''}."
    browse.status.linkActivated.emit("undo")
    assert states(browse, INSTALLATION, *below) == was


def test_every_task_rows_right_click_menu_has_state(browse):
    item = row(browse, INSTALLATION)
    menu = browse.tree.row_menu(item)
    assert labels(menu) == ["State"]  # the task tree's rows have no other commands
    assert labels(next(a.menu() for a in menu.actions() if a.menu()))[:4] == ["Not started", "In progress", "Parked", "Closed"]
    edits.add_to_today(browse.conn, browse.ctx.data_root, browse.ctx.fs, INSTALLATION, "", NOW)
    browse.refresh(render=False)
    browse.show_browse(view="today")
    today_row = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", INSTALLATION) and i.data(0, STATE_ROLE))
    menu = browse.tree.row_menu(today_row)
    assert labels(menu)[-1] == "State" and len(labels(menu)) > 1  # Today's own commands, then State


def test_a_key_dates_row_isnt_a_state_button(browse):
    """Only a row whose icon is its task's own state is a button: a key date's, a reminder's or a note's icon isn't."""
    from docrepo import tasks

    tasks.add_key_dates(browse.conn, INSTALLATION, [tasks.KeyDateRow("2026-10-09", None, "Crane on site")], at=NOW, via="Browse tool")
    browse.refresh(render=False)
    browse.show_browse(view="due")
    lines = [(i, i.data(0, LINE_ROLE)) for i in browse.tree.items() if i.data(0, LINE_ROLE) is not None]
    states_shown = {icon for icon, _ in STATE_ICONS.values()}
    assert any(line.icon == "calendar" for _, line in lines)  # the key date due tomorrow has a row of its own
    assert all(i.data(0, STATE_ROLE) is None for i, line in lines if line.icon not in states_shown)
    assert all(line.icon in states_shown for i, line in lines if i.data(0, STATE_ROLE))


# ---- the task page, the Priorities board and the timeline ----
def test_the_task_pages_state_opens_the_menu(browse):
    browse.go_task(INSTALLATION)
    assert f'href="state:{INSTALLATION}"' in browse.task_pane.top.toHtml()
    picking(browse, "In progress")
    browse.on_link(QUrl(f"state:{INSTALLATION}"))
    assert browse.menus and states(browse, INSTALLATION) == ["In progress"]


def test_the_cards_right_click_menus_have_state(browse):
    picking(browse, None)
    browse.priorities.card_menu.emit(INSTALLATION, QPoint(0, 0))
    assert browse.menus[-1][0] == ["Open task", "Edit task…", "State"]
    browse.timeline.render(browse.model(), NOW.date())
    browse.timeline.sel = INSTALLATION
    browse.timeline._card_menu(QPoint(0, 0))
    assert browse.menus[-1][0] == ["Open task", "Edit task…", "State"] and len(browse.menus) == 2


# ---- the Task view and the Today side panel ----
def test_the_task_views_task_rows(browse):
    browse.open_task_view(INSTALLATION)
    view = browse.task_views[INSTALLATION]
    view.kind = "task"  # Subtasks
    view.refresh()
    rows = view.list.rows
    i = next(k for k, r in enumerate(rows) if r.kind == "item" and r.record is not None and r.record.kind == "task" and r.record.id == RIGGING)
    rect = view.list.delegate.state_rect(rows[i], view.list.visualRect(view.list.model_.index(i)))
    assert rect is not None
    picking(browse, "Parked")
    view.list.state_clicked.emit(i, QPoint(0, 0))
    assert states(browse, RIGGING) == ["Parked"]
    assert view.foot.text() == "Parked: Rigging plan." and view.foot_undo.isVisibleTo(view)
    view.foot_undo.click()
    assert states(browse, RIGGING) != ["Parked"]
    picking(browse, None)
    i = next(k for k, r in enumerate(view.list.rows) if r.kind == "item" and r.record is not None and r.record.kind == "task")
    view.list.row_menu.emit(i, QPoint(0, 0))
    assert browse.menus[-1][0][-1] == "State"


def test_the_today_side_panels_rows(browse):
    from docrepo.ui.today_panel import TodayPanel
    from docrepo.ui.wheel_commands import SPECS, icon_names

    edits.add_to_today(browse.conn, browse.ctx.data_root, browse.ctx.fs, INSTALLATION, "", NOW)
    browse.refresh(render=False)
    wheels = SimpleNamespace(config=wheels_config.parse(wheels_config.DEFAULT_TEXT, SPECS, icon_names()), open_config=lambda: None)
    panel = TodayPanel(browse.ctx, browse, wheels)
    try:
        panel.refresh()
        r = next(x for x in panel.rows if x.task_id == INSTALLATION)
        assert r.state_button is not None and r.state_button.text() == states(browse, INSTALLATION)[0]
        assert states(browse, INSTALLATION)[0] not in r.subtitle.full  # the state is the button, not words in the line
        picking(browse, "Parked")
        panel.state_clicked(r)
        assert states(browse, INSTALLATION) == ["Parked"]
        assert panel.note_row.isVisibleTo(panel) and panel.note_label.text() == "Parked: Installation." and panel.note_undo.isVisibleTo(panel)
        r = next(x for x in panel.rows if x.task_id == INSTALLATION)
        assert r.state_button.text() == "Parked"  # drawn again
    finally:
        panel.deleteLater()


def test_hovering_a_state_lights_it_and_shows_a_hand(browse):
    item = row(browse, INSTALLATION)
    in_sight(browse, item)
    index = browse.tree.indexFromItem(item, 0)
    move(browse.tree.viewport(), icon_at(browse, item))
    assert browse.tree.state_lit(index)
    assert browse.tree.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor
    move(browse.tree.viewport(), title_at(browse, item))  # the rest of the row is the row, not the button
    assert not browse.tree.state_lit(index)


def test_a_click_on_the_title_picks_the_row_and_opens_no_menu(browse):
    picking(browse, "Parked")
    item = row(browse, RIGGING)
    in_sight(browse, item)
    was = states(browse, RIGGING)
    QTest.mouseClick(browse.tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, title_at(browse, item))
    assert not browse.menus and states(browse, RIGGING) == was
    assert browse.tree.currentItem() is not None and browse.tree.currentItem().data(0, KEY_ROLE) == ("task", RIGGING)


def move(widget, at: QPoint) -> None:
    """The mouse moving to a point, with no button down, as the offscreen platform doesn't send it for QTest.mouseMove."""
    QApplication.sendEvent(widget, QMouseEvent(QEvent.Type.MouseMove, QPointF(at), QPointF(widget.mapToGlobal(at)), Qt.MouseButton.NoButton,
                                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_the_classic_look_keeps_its_state_cell_as_the_button(qapp, sample_root):
    """The Classic look keeps its State column (release 5.78), so the cell is the button there, as 5.76 built it."""
    from docrepo.ui.look import configure

    conn, root, fs = sample_root
    configure("classic", False)
    try:
        w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW), None)
        w.menus = []
        w.show_browse(view="tasks")
        w.resize(1600, 900)
        QApplication.processEvents()
        header = w.tree.headerItem()
        column = [header.text(i) for i in range(w.tree.columnCount())].index("State")
        item = row(w, INSTALLATION)
        assert item.data(column, STATE_ROLE) == INSTALLATION and item.data(0, STATE_ROLE) is None
        assert item.toolTip(column).endswith("Click to change the state.")
        picking(w, "Parked")
        w.tree.open_state_menu(item, column)
        assert w.menus and states(w, INSTALLATION) == ["Parked"]
        w.hide()
        w.deleteLater()
    finally:
        configure("new", False)
