"""The browse window's shell (release 5.182, the redesign's lane A, decisions 850 to 854), driven offscreen over the sample
data: one splitter still, held by one white card set into the grey frame with clean round corners and one hairline
between the list and the page; the top bar on the frame, its search box a soft fill and the Problems button in it; the
sidebar's grey selection with no accent pill; and Manage folded on a data root that never folded a group."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import tokens  # noqa: E402
from docrepo.ui.browse_window import NAV_FOLDED_KEY, BrowseWindow  # noqa: E402
from docrepo.ui.content_card import CARD_GAP, CARD_PAD, ContentCard  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


def _settle(w) -> None:
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def browse(ctx):
    w = BrowseWindow(ctx, None)
    w.show_browse()
    w.resize(1440, 900)
    _settle(w)
    yield w
    w.hide()
    w.deleteLater()


def _hex(c: QColor) -> str:
    return c.name()


def _colour(name: str) -> str:
    return QColor(tokens.colour(name)).name()


def _card_in_window(browse) -> tuple:
    """The card's rectangle in the window's coordinates, and the window's picture."""
    rect = browse.card.card_rect()
    assert rect is not None
    rect.translate(browse.card.mapTo(browse, QPoint(0, 0)))
    return rect, browse.grab().toImage()


def _corners_clean(browse, inside: bool = True) -> None:
    """The card's four corner pixels are the frame's grey; with ``inside``, the pixel ``CARD_PAD + 1`` in from each is
    the card's white (not for a view that paints a ground of its own: Settings, the workspace)."""
    rect, img = _card_in_window(browse)
    corners = [rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()]
    assert [_hex(img.pixelColor(p)) for p in corners] == [_colour("base")] * 4
    if not inside:
        return
    inside = [rect.topLeft() + QPoint(CARD_PAD + 1, CARD_PAD + 1), rect.topRight() + QPoint(-CARD_PAD - 1, CARD_PAD + 1),
              rect.bottomLeft() + QPoint(CARD_PAD + 1, -CARD_PAD - 1), rect.bottomRight() + QPoint(-CARD_PAD - 1, -CARD_PAD - 1)]
    assert [_hex(img.pixelColor(p)) for p in inside] == [_colour("content")] * 4


def test_one_splitter_held_by_the_card(browse):
    split = browse.split
    assert split.count() == 3 and [split.widget(i) for i in range(3)] == [browse.nav, browse.middle, browse.detail]
    assert isinstance(browse.card, ContentCard) and browse.card.layout().itemAt(0).widget() is split
    assert split.objectName() == "browseSplit"


def test_the_panes_clear_the_corners(browse):
    browse.go_task("T000012")
    _settle(browse)
    rect = browse.card.card_rect()
    middle = browse.middle.mapTo(browse.card, QPoint(0, 0))
    assert middle.x() - rect.left() == CARD_PAD and middle.y() - rect.top() == CARD_PAD
    detail = browse.detail.mapTo(browse.card, browse.detail.rect().bottomRight())
    assert rect.right() - detail.x() == CARD_PAD and rect.bottom() - detail.y() == CARD_PAD


def test_the_card_its_corners_its_edge_and_its_hairline(browse):
    browse.go_task("T000012")
    _settle(browse)
    _corners_clean(browse)
    rect, img = _card_in_window(browse)
    assert _hex(img.pixelColor(QPoint(rect.left(), rect.center().y()))) == _colour("stroke")
    lines = browse.card.hairlines()
    assert len(lines) == 1
    x = lines[0] + browse.card.mapTo(browse, QPoint(0, 0)).x()
    assert _hex(img.pixelColor(QPoint(x, rect.top() + 1))) == _colour("stroke")


def test_the_corners_stay_clean_scrolled(browse):
    """A scroll bar at the list's corner and at the page's: the corners still round."""
    browse.go_task("T000012")
    browse.tree.scrollToBottom()
    page = browse.task_pane
    for bar in [sb for sb in page.findChildren(type(browse.tree.verticalScrollBar()))]:
        bar.setValue(bar.maximum())
    _settle(browse)
    _corners_clean(browse)


def test_the_card_with_the_sidebar_hidden(browse):
    browse.show_views_pane(False)
    _settle(browse)
    rect = browse.card.card_rect()
    left = rect.translated(browse.card.mapTo(browse, QPoint(0, 0))).left()
    assert left == CARD_GAP
    _corners_clean(browse)
    browse.show_views_pane(True)
    _settle(browse)
    left = browse.card.card_rect().translated(browse.card.mapTo(browse, QPoint(0, 0))).left()
    assert left > CARD_GAP + 100  # beside the sidebar again


def test_hairlines_by_view(browse):
    browse.go_task("T000012")
    _settle(browse)
    assert len(browse.card.hairlines()) == 1
    before = browse.card.hairlines()[0]
    sizes = browse.split.sizes()
    browse.split.setSizes([sizes[0], sizes[1] + 80, sizes[2] - 80])
    _settle(browse)
    assert browse.card.hairlines()[0] == before + 80  # it follows the drag
    for view in ("priorities", "timeline", "settings"):
        browse.set_view(view)
        _settle(browse)
        assert browse.card.hairlines() == [], view
        _corners_clean(browse, inside=view != "settings")  # Settings paints its own ground (lane E's 5.193)


def test_no_hairline_with_the_workspace_open(browse):
    from docrepo.ui import workspace as workspace_ui

    workspace_ui.open_row(browse, "T000012")
    _settle(browse)
    if browse.middle.isHidden():  # the workspace opened in the window, alone in the card
        assert browse.card.hairlines() == []
        _corners_clean(browse, inside=False)  # the workspace's chain column has a ground of its own (lane C's 5.185)


def test_the_frame_reaches_this_window_alone(browse):
    """The grey frame in the top bar and beside the sidebar; a Task view, also named ``browse``, keeps its white."""
    from docrepo.ui.task_view import TaskView

    rect, img = _card_in_window(browse)
    bar = browse.views_button.parentWidget()
    in_bar = bar.mapTo(browse, QPoint(bar.width() // 2, 2))
    assert _hex(img.pixelColor(in_bar)) == _colour("base")
    gutter = QPoint(rect.left() - 2, rect.center().y())  # under the sidebar's right edge, beside the card
    assert _hex(img.pixelColor(gutter)) == _colour("base")
    view = TaskView(browse, "T000012")
    try:
        assert view.objectName() == "browse" and view.property("frame") is None
        view.resize(900, 640)
        _settle(view)
        assert _hex(view.grab().toImage().pixelColor(QPoint(view.width() // 2, 4))) == _colour("content")
    finally:
        view.deleteLater()


def test_the_top_bar(browse, ctx):
    assert browse.search_box.objectName() == "topSearch"
    bar = browse.views_button.parentWidget()
    assert browse.problems_line.parentWidget() is bar
    assert browse.problems_line.objectName() == "problemsLine"
    assert browse.findChild(type(browse.status), "status") is None  # the status strip is gone
    assert browse.status is browse.toast.label


def test_manage_folded_on_a_new_data_root(browse, ctx):
    nav = browse.nav
    assert nav.headings["Manage"].folded and nav.rows["people"].isHidden()
    assert db.get_state(ctx.conn, NAV_FOLDED_KEY) is None  # nothing written until a fold by hand
    browse.set_view("people")  # as the palette opens it
    _settle(browse)
    assert nav.headings["Manage"].folded and not nav.rows["people"].isHidden()


def test_nothing_folded_where_the_key_was_kept_empty(ctx):
    ctx.keep_state(NAV_FOLDED_KEY, "")
    w = BrowseWindow(ctx, None)
    try:
        w.show_browse()
        assert not any(h.folded for h in w.nav.headings.values())
    finally:
        w.hide()
        w.deleteLater()


def test_the_open_view_is_grey_with_no_pill(browse):
    browse.set_view("tasks")
    _settle(browse)
    row = browse.nav.rows["tasks"]
    img = row.grab().toImage()
    assert _hex(img.pixelColor(QPoint(6, row.height() // 2))) == _colour("nav_selected")
    accent = _colour("accent")
    assert all(_hex(img.pixelColor(QPoint(x, y))) != accent for x in range(4) for y in range(row.height()))


def test_the_problems_button_shows_in_the_top_bar(browse, ctx):
    from docrepo.ui.problems import Problems

    assert browse.problems_line.isHidden()
    ctx.problem_log.add(Problems(NOW, "a capture", ["The copy of Lift plan.pdf couldn't be saved (PermissionError)."]))
    browse.problems_line.refresh()
    _settle(browse)
    assert browse.problems_line.isVisible() and browse.problems_line.text() == "1 problem with the last save"
    bar = browse.views_button.parentWidget()
    assert browse.problems_line.parentWidget() is bar and bar.isAncestorOf(browse.problems_line)
