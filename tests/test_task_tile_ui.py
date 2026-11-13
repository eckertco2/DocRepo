"""The task tile in its places (release 5.138, the design workspace's ``docs/mods/task-tile-plan.md``, decisions 563 to 579):
the browse window's lists and tree, Today, a task page's Subtasks, the Priorities board, the `#` list, and the one menu
and the clicks they share. Driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from docrepo import edits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import tokens  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE, LINE_ROLE, TILE_GAP, Line  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
BOOK, RIGGING, OVERTIME, REACTOR, INSTALL, DRAFTING = "T000019", "T000012", "T000015", "T000001", "T000008", "T000011"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1440, 900)
    yield w
    capture.deleteLater()
    w.deleteLater()


def row(browse, task_id: str):
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", task_id))


def line(browse, task_id: str) -> Line:
    return row(browse, task_id).data(0, LINE_ROLE)


def labels(menu: QMenu) -> list[str]:
    return [a.text().split("\t")[0] for a in menu.actions() if not a.isSeparator()]


# ---- the tile's parts in the browse window (decisions 565 to 570) ----
def test_the_tree_draws_tiles_with_marks_the_flag_and_two_parents(browse):
    browse.set_view("tasks")
    browse.open.update({REACTOR, INSTALL})
    browse.render_list()
    book, overtime, reactor = line(browse, BOOK), line(browse, OVERTIME), line(browse, REACTOR)
    assert book.tile and book.flag and not book.chips  # Urgent is the flag, Critical's chip is gone (decision 569)
    assert overtime.parents.startswith("Under ") and not overtime.muted  # no "2 parents" words, no labels (569, 570)
    assert len(reactor.marks) == 3 and reactor.marks[1] is not None  # on the business team meeting's agenda (566)
    assert book.depth == -1  # the tree indents instead of ticks


def test_the_days_column_is_a_number(browse):
    browse.set_view("tasks")
    browse.open.update({REACTOR, INSTALL})
    browse.render_list()
    from docrepo.ui.tree_view import HTML_ROLE

    assert ">1</span>" in row(browse, BOOK).data(1, HTML_ROLE)  # due tomorrow (decision 568)
    assert "◆" in row(browse, INSTALL).data(1, HTML_ROLE)  # its deadline is the nearer date


def test_today_is_flat_so_its_tiles_have_depth_ticks_and_no_sun(browse, ctx):
    edits.add_to_today(ctx.conn, ctx.data_root, ctx.fs, RIGGING, "", NOW)
    browse.refresh()
    browse.set_view("today")
    rigging = line(browse, RIGGING)
    assert rigging.depth == 2 and rigging.depth_tip.startswith("2 levels down")
    assert len(rigging.marks) == 2  # the sun's slot is left out: every task on Today is on it


def test_tiled_views_set_their_rows_apart_by_the_gap(browse):
    browse.set_view("tasks")
    assert browse.tree.tiled
    QApplication.processEvents()
    browse.tree.doItemsLayout()
    assert browse.tree.visualItemRect(row(browse, REACTOR)).height() == tokens.TREE_ROW + TILE_GAP
    browse.set_view("people")
    assert not browse.tree.tiled


# ---- the clicks (decision 572) ----
def test_a_double_click_opens_the_page_not_edit_task(browse, monkeypatch):
    browse.set_view("tasks")
    monkeypatch.setattr(browse, "edit_task", lambda *_a, **_k: pytest.fail("a double-click opened Edit task"))
    browse.double_click(row(browse, REACTOR))
    assert browse.sel == ("task", REACTOR)


def test_enter_on_a_task_row_opens_its_page(browse, monkeypatch):
    opened = []
    browse.tree.task_opened = opened.append
    browse.set_view("tasks")
    browse.tree.setCurrentItem(row(browse, REACTOR))
    browse.tree.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert opened == [REACTOR]


# ---- the one menu (decision 573) ----
def tail(menu: QMenu) -> list[str]:
    words = labels(menu)
    return words[words.index("State"):]


def test_the_menu_is_the_same_from_state_on_in_the_tree_and_on_today(browse, ctx):
    edits.add_to_today(ctx.conn, ctx.data_root, ctx.fs, REACTOR, "", NOW)
    browse.refresh()
    browse.set_view("tasks")
    tree_menu = browse.tree.row_menu(row(browse, REACTOR))
    browse.set_view("today")
    today_menu = browse.tree.row_menu(row(browse, REACTOR))
    assert labels(tree_menu)[0] == "Open"
    assert tail(tree_menu) == tail(today_menu)
    assert tail(tree_menu)[:2] == ["State", "Add to"]
    assert {"Note…", "Update…", "New task under this one…", "Edit", "Priority", "Copy"} <= set(tail(tree_menu))
    assert "Done" in labels(today_menu)  # Today's own, on top


def test_ask_for_an_update_is_offered_where_someone_else_is_on_the_task(browse, ctx):
    browse.set_view("tasks")
    browse.open.update({REACTOR, INSTALL})
    browse.render_list()
    from docrepo import ask_update

    assert ask_update.LABEL in labels(browse.tree.row_menu(row(browse, RIGGING)))  # Mike Ortiz is on it
    ctx.conn.execute("DELETE FROM task_people WHERE task = ?", (DRAFTING,))
    browse.refresh()
    browse.render_list()
    assert ask_update.LABEL not in labels(browse.tree.row_menu(row(browse, DRAFTING)))


def test_the_edit_menu_has_quick_edit_after_edit_task(browse):
    browse.set_view("tasks")
    menu = browse.tree.row_menu(row(browse, REACTOR))
    edit = next(a.menu() for a in menu.actions() if a.menu() is not None and a.text().startswith("Edit"))
    assert labels(edit)[:2] == ["Edit task…", "Quick edit…"]


def test_the_priority_menu_ticks_the_bucket_and_urgent(browse):
    browse.set_view("tasks")
    browse.open.update({REACTOR, INSTALL})
    browse.render_list()
    menu = browse.tree.row_menu(row(browse, BOOK))
    pri = next(a.menu() for a in menu.actions() if a.menu() is not None and a.text() == "Priority")
    ticked = [a.text().split("\t")[0] for a in pri.actions() if a.isCheckable() and a.isChecked()]
    assert "Urgent" in ticked


def test_a_board_card_and_a_timeline_card_get_the_tile_menu(browse, monkeypatch):
    shown = []
    monkeypatch.setattr(browse, "run_menu", lambda menu, at: shown.append(labels(menu)))
    browse.card_menu(REACTOR, QPoint(0, 0))
    browse.card_menu(REACTOR, QPoint(0, 0), open_it=False)
    assert shown[0][0] == "Open" and "Priority" in shown[0]
    assert shown[1][0] != "Open" and "State" in shown[1]


# ---- pages (decision 577) ----
def test_subtasks_on_a_page_are_tiles(browse):
    from docrepo.detail import Pages, PageState

    pages = Pages(browse.model(), browse.today(), browse.content_of, "P001", browse.conn)
    html = pages.subtask_section(browse.model().task(INSTALL), PageState())
    assert f'href="state:{BOOK}"' in html and 'class="tile"' in html and "tm:urgent" in html
    assert "Also under Q4 cost reduction" in html  # the overtime budget, under Installation here


def test_a_right_click_on_a_task_link_on_a_page_is_the_tile_menu(browse, monkeypatch):
    shown = []
    monkeypatch.setattr(browse, "run_menu", lambda menu, at: shown.append(labels(menu)))
    assert browse.page_link_menu(f"task:{REACTOR}", QPoint(0, 0))
    assert shown and shown[0][0] == "Open"
    assert not browse.page_link_menu("person:P001", QPoint(0, 0))


# ---- the Priorities board (decision 575) ----
def test_a_board_card_has_its_circle_and_its_days(browse, monkeypatch):
    monkeypatch.setattr(browse, "run_menu", lambda menu, at: None)  # the state menu the click opens
    browse.set_view("priorities")
    QApplication.processEvents()
    card = browse.priorities.cards[BOOK]
    clicked = []
    browse.priorities.state_clicked.connect(lambda task, at: clicked.append(task))
    centre = card.circle.geometry().center()
    assert card.circle_at(centre) is not None
    card.mousePressEvent(_press(centre))
    assert clicked == [BOOK]


def _press(at: QPoint):
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(at), QPointF(at), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)


# ---- the `#` list keeps its rows, with the cut (decision 574) ----
def test_the_hash_list_cuts_a_long_name_at_its_first_sentence():
    from PySide6.QtGui import QFontMetrics

    from docrepo.task_tile import fit_title

    fm = QFontMetrics(tokens.ui_font())
    title = "Rigging plan for the impeller lift. Mike to confirm the crane size with the vendor"
    cut = fit_title(title, fm.horizontalAdvance("Rigging plan for the impeller lift…") + 4, fm.horizontalAdvance)
    assert cut == "Rigging plan for the impeller lift…"
