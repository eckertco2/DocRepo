"""The browse tool's sidebar in the new look (the visual overhaul's O10, release 5.22), driven offscreen over the sample
data: its rows and their order, counts only where they ask for something, folding kept in docs.db, the open view kept
in sight under a folded heading, the foot, the keys, and the totals moved to the views' own headers."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui.browse_window import NAV_FOLDED_KEY, BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.look import configure  # noqa: E402
from docrepo.ui.nav_pane import Heading, NavPane  # noqa: E402
from docrepo.views import ASKS, LIST_IDS, view_counts  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TOP = ["today", "unfiled", "tasks"]
PLAN = ["agenda", "timeline", "capacity"]
MANAGE = ["people", "labels", "docs"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    w = BrowseWindow(ctx, None)
    w.show_browse()
    yield w
    w.hide()
    w.deleteLater()


def test_the_rows_their_order_and_the_foot(browse):
    """Decisions 79, 83 and 84: an icon and a name per view, the groups as headings, Discarded and Settings at the foot."""
    nav = browse.nav
    assert isinstance(nav, NavPane)
    main = [r.section if isinstance(r, Heading) else r.view_id for r in nav.order if not nav.foot.isAncestorOf(r)]
    assert main == [*TOP, "Lists", *LIST_IDS, "Plan", *PLAN, "Manage", *MANAGE]
    assert [r.view_id for r in nav.order if nav.foot.isAncestorOf(r)] == ["discarded", "settings"]
    assert nav.rows["due"].text() == "Overdue and next 7 days" and nav.headings["Plan"].accessibleName() == "Plan"
    assert all(r.height() == 32 for r in nav.rows.values()) and all(h.height() == 26 for h in nav.headings.values())


def test_counts_only_where_they_ask_for_something(browse):
    """Decision 81: Today, Unfiled and the lists; not the task tree's, People's, Labels' or Documents' totals."""
    m = browse.model()
    counts = view_counts(m, browse.today(), "P001")
    nav = browse.nav
    for vid, row in nav.rows.items():
        assert row.count == (counts.get(vid, 0) if vid in ASKS else 0), vid
    assert counts["tasks"] and counts["people"] and not nav.rows["tasks"].count and not nav.rows["people"].count
    unfiled = nav.rows["unfiled"]
    assert unfiled.count == counts["unfiled"] > 0 and unfiled.accessibleName() == f"Unfiled, {counts['unfiled']}"
    # ...and those views say their totals in their own headers
    browse.set_view("tasks")
    assert f"{counts['tasks']} open</span>" in browse.pane_title.text()
    browse.set_view("people")
    assert f"{len(m.active_people())} active" in browse.pane_title.text()
    browse.set_view("today")
    assert browse.pane_title.text() == "Today"


def test_a_click_opens_the_view_and_marks_it(browse):
    """Decision 82: the open view's row is checked; a click on it again keeps it open."""
    nav = browse.nav
    nav.rows["people"].click()
    assert browse.view == "people" and nav.rows["people"].isChecked() and not nav.rows["tasks"].isChecked()
    nav.rows["people"].click()
    assert browse.view == "people" and nav.rows["people"].isChecked()
    nav.rows["settings"].click()
    assert browse.view == "settings" and nav.rows["settings"].isChecked()
    browse.search_box.setText("impeller")
    browse._run_search()
    assert browse.view == "search" and not any(r.isChecked() for r in nav.rows.values())


def test_folding_stays_and_keeps_the_open_view_in_sight(browse, ctx):
    """Decision 80, and decision 10's folding kept in docs.db."""
    nav = browse.nav
    browse.set_view("due")
    nav.headings["Lists"].click()
    assert db.get_state(ctx.conn, NAV_FOLDED_KEY) == "Lists" and nav.headings["Lists"].folded
    assert not nav.rows["due"].isHidden() and all(nav.rows[v].isHidden() for v in LIST_IDS if v != "due")
    browse.set_view("tasks")
    assert all(nav.rows[v].isHidden() for v in LIST_IDS)
    nav.headings["Manage"].click()
    assert db.get_state(ctx.conn, NAV_FOLDED_KEY) == "Lists,Manage"
    again = BrowseWindow(ctx, None)
    try:
        again.show_browse()
        assert again.nav.headings["Lists"].folded and again.nav.rows["people"].isHidden()
        assert not again.nav.rows["discarded"].isHidden()  # the foot never folds
    finally:
        again.hide()
        again.deleteLater()
    nav.headings["Lists"].click()
    assert db.get_state(ctx.conn, NAV_FOLDED_KEY) == "Manage" and not nav.rows["urgent"].isHidden()


def test_the_keys(browse):
    """Tab has one stop in the pane, the open view's row; the arrows, Home and End move; Enter opens or folds; Left and
    Right fold and unfold a heading."""
    nav = browse.nav
    browse.set_view("tasks")
    stops = [r for r in nav.order if r.focusPolicy() & Qt.FocusPolicy.TabFocus]
    assert stops == [nav.rows["tasks"]]
    QTest.keyClick(nav.rows["tasks"], Qt.Key.Key_Down)
    assert [r for r in nav.order if r.focusPolicy() & Qt.FocusPolicy.TabFocus] == [nav.headings["Lists"]]
    QTest.keyClick(nav.headings["Lists"], Qt.Key.Key_Left)
    assert nav.headings["Lists"].folded and nav.rows["due"].isHidden()
    QTest.keyClick(nav.headings["Lists"], Qt.Key.Key_Down)  # the next row shown, past the folded group
    assert nav.headings["Plan"].focusPolicy() & Qt.FocusPolicy.TabFocus
    QTest.keyClick(nav.headings["Plan"], Qt.Key.Key_Down)
    QTest.keyClick(nav.rows["agenda"], Qt.Key.Key_Return)
    assert browse.view == "agenda"
    QTest.keyClick(nav.rows["agenda"], Qt.Key.Key_End)
    assert nav.rows["settings"].focusPolicy() & Qt.FocusPolicy.TabFocus
    QTest.keyClick(nav.rows["settings"], Qt.Key.Key_Home)
    assert nav.rows["today"].focusPolicy() & Qt.FocusPolicy.TabFocus
    QTest.keyClick(nav.headings["Lists"], Qt.Key.Key_Right)
    assert not nav.headings["Lists"].folded and not nav.rows["due"].isHidden()
    QTest.keyClick(nav.headings["Lists"], Qt.Key.Key_Return)
    assert nav.headings["Lists"].folded


def test_a_long_name_ends_in_an_ellipsis(browse):
    """A name that doesn't fit is cut short, with the full name as the tooltip. The offscreen platform's text is about
    twice as wide as Windows', so the widths come from the fonts rather than from the sidebar's (the fit at 248 px is
    checked by hand)."""
    from PySide6.QtGui import QFontMetrics

    from docrepo.ui import tokens
    from docrepo.ui.nav_pane import GAP, PAD

    browse.set_view("due")
    row = browse.nav.rows["due"]
    assert row.count  # the sample data has tasks due this week, so the count takes room too
    name = QFontMetrics(tokens.ui_font(tokens.BODY, semibold=True)).horizontalAdvance(row.text())
    count = QFontMetrics(tokens.numeric_font(tokens.CAPTION)).horizontalAdvance(str(row.count))
    row.resize(PAD + 16 + GAP + name + 8 + count + GAP + 2, 32)
    row.grab()
    assert not row._elided
    row.resize(row.width() - 30, 32)
    row.grab()
    assert row._elided


def test_the_classic_look_keeps_the_tree(ctx):
    from docrepo.ui.tree_view import RowTree

    configure("classic", False)
    try:
        w = BrowseWindow(ctx, None)
        w.show_browse()
        assert isinstance(w.nav, RowTree) and ("view", "people") in w.nav.keys()
        w.hide()
        w.deleteLater()
    finally:
        configure("new", False)
