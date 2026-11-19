"""The kind on the tile, drawn (release 5.168, decision 786): the painted tile, the lists' rows, a Priorities card and a page
all draw a parent's branches and a routine task's loop from one recipe, between the circle and the title; a single task
draws none; the state circles are defined once. Offscreen, over the made-up sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from docrepo import task_tile  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import page_view, tree_view  # noqa: E402
from docrepo.ui import task_tile as tile_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE, LINE_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
REACTOR, REPORT, HOLIDAY = "T000001", "T000006", "T000016"  # a parent, a monthly routine task, a single task


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
    w.deleteLater()


def line(browse, task_id: str):
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", task_id)).data(0, LINE_ROLE)


def test_the_state_circles_are_defined_once():
    assert tree_view.STATE_ICONS is tile_ui.STATE_ICONS


def test_the_tree_rows_carry_the_mark(browse):
    browse.set_view("tasks")
    browse.render_list()
    assert line(browse, REACTOR).kind == "kind-parent" and line(browse, REACTOR).kind_tip.startswith("Parent task: ")
    assert line(browse, REPORT).kind == "kind-routine" and line(browse, REPORT).kind_tip == "Routine task: Monthly"
    assert line(browse, HOLIDAY).kind == ""


def test_the_painted_tile_draws_it_and_says_it(browse):
    m = browse.model()
    w = tile_ui.TileWidget(task_tile.tile(m, REPORT, NOW.date(), task_tile.marks(m, NOW.date())))
    w.resize(320, 26)
    w.grab()  # paints it
    assert any(tip == "Routine task: Monthly" for _, tip in w._hits)
    single = tile_ui.TileWidget(task_tile.tile(m, HOLIDAY, NOW.date(), task_tile.marks(m, NOW.date())))
    single.resize(320, 26)
    single.grab()
    assert not any(tip.startswith(("Routine", "Parent")) for _, tip in single._hits)
    w.deleteLater()
    single.deleteLater()


def test_a_priorities_card_has_the_mark(browse):
    browse.set_view("priorities")
    kind = browse.priorities.cards[REACTOR].findChild(QLabel, "prKind")
    assert kind is not None and kind.toolTip().startswith("Parent task: ")
    assert browse.priorities.cards[HOLIDAY].findChild(QLabel, "prKind") is None


def test_a_page_draws_the_marks_pictures():
    for key in ("kind-parent", "kind-routine"):
        assert not page_view.tile_mark(key, 1.0).isNull()
