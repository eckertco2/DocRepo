"""Release 5.183, rows and group heads (the redesign plan's decisions 850, 856 and 857): flat rows on white with a rounded
ground, inset from the pane's edges; group heads as small grey labels with no band; column heads only on the real tables;
and a tile's days with their unit. Driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import edits, task_tile  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import tokens  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.lists.common import HEADINGS  # noqa: E402
from docrepo.ui.tree_view import ACTIONS_ROLE, HEAD_ROLE, KEY_ROLE, ROW_END, ROW_INSET, head_of  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
RIGGING = "T000012"  # Rigging plan, a subtask two levels down: no branch arrow of its own


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


def item_of(browse, key):
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == key)


def grab(browse):
    QApplication.processEvents()
    browse.tree.doItemsLayout()
    return browse.tree.viewport().grab().toImage()


def on_today(ctx) -> None:
    for task_id in (RIGGING, "T000009", "T000016"):  # Rigging plan, Vendor drawing package, Holiday coverage schedule
        edits.add_to_today(ctx.conn, ctx.data_root, ctx.fs, task_id, "", NOW)
    edits.set_priority(ctx.conn, ctx.data_root, ctx.fs, "T000009", "high", None, NOW)


def open_rigging(browse) -> None:
    browse.set_view("tasks")
    browse.open.update(browse.model().tasks)
    browse.render_list()
    browse.select("task", RIGGING)
    browse.tree.scrollToItem(item_of(browse, ("task", RIGGING)))
    browse.tree._hover = None


# ---- the ground (decision 850) ----
def test_the_selected_rows_ground_is_rounded_and_inset(browse):
    open_rigging(browse)
    rect = browse.tree.visualItemRect(item_of(browse, ("task", RIGGING)))
    img = grab(browse)
    content, selected = tokens.colour("content"), tokens.colour("selected")
    assert img.pixelColor(ROW_INSET, rect.top() + 1).name() == content  # the fill's corner is round
    assert img.pixelColor(ROW_INSET + 8, rect.center().y()).name() == selected
    w = browse.tree.viewport().width()
    assert {img.pixelColor(x, rect.center().y()).name() for x in range(w - ROW_INSET, w)} == {content}  # nothing at the pane's edge
    assert img.pixelColor(ROW_INSET + 8, rect.top()).name() == content  # a pixel off its top, so two grounds don't run together


def test_a_hovered_row_has_the_hover_ground_and_a_head_none(browse, ctx):
    on_today(ctx)
    browse.refresh(render=False)
    browse.set_view("today")
    browse.select("task", "T000016")
    row = item_of(browse, ("task", RIGGING))
    browse.tree._hover = row
    browse.tree.viewport().update()
    img = grab(browse)
    rect = browse.tree.visualItemRect(row)
    assert img.pixelColor(browse.tree.viewport().width() - ROW_INSET - 2, rect.center().y()).name() == tokens.colour("hover")
    head = next(i for i in browse.tree.items() if i.data(0, HEAD_ROLE) is not None)
    hrect = browse.tree.visualItemRect(head)
    assert img.pixelColor(browse.tree.viewport().width() - 40, hrect.center().y()).name() == tokens.colour("content")


# ---- group heads (decision 856) ----
@pytest.mark.parametrize(("markup", "want"), [
    ("<b>Today</b>", ("Today", "", "")),
    ('<b>Line 1</b> &nbsp;<span class="sub">12</span>', ("Line 1", "12", "")),
    ('<b>Suggested</b> <span class="sub">3 · found by a tag pattern…</span>', ("Suggested", "", "3 · found by a tag pattern…")),
    ('<b>Tag list</b> <span class="sub">1,204</span>', ("Tag list", "1,204", "")),
    ('<b>Due in the next 7 days</b> <span class="sub">· yours</span>', ("Due in the next 7 days", "", "yours")),
])
def test_head_of_reads_each_shape_the_callers_write(markup, want):
    h = head_of(markup)
    assert (h.name, h.count, h.sub) == want


def test_a_head_is_a_row_with_no_band_that_cant_be_selected(browse, ctx):
    on_today(ctx)
    browse.refresh(render=False)
    browse.set_view("today")
    heads = [i for i in browse.tree.items() if i.data(0, HEAD_ROLE) is not None]
    assert heads
    for h in heads:
        assert not h.flags() & Qt.ItemFlag.ItemIsSelectable
        assert all(h.background(c).style() == Qt.BrushStyle.NoBrush for c in range(browse.tree.columnCount()))
    bands = [h.data(0, HEAD_ROLE) for h in heads if h.data(0, HEAD_ROLE).tag]
    assert bands and all(b.dot and b.count.isdigit() for b in bands)
    assert "high" in {b.tag for b in bands}
    browse.set_view("tasks")  # the task tree's groups by label are heads too, with no band
    assert all(i.background(0).style() == Qt.BrushStyle.NoBrush for i in browse.tree.items())


@pytest.mark.parametrize("view", ["tasks", "today", "due", "agenda", "activity", "docs", "people", "labels", "tagged", "glossaries", "templates",
                                  "discarded", "unfiled"])
def test_column_heads_only_on_the_real_tables(browse, view):
    browse.set_view(view)
    keyed = any(k is not None for k in browse.tree.keys())
    assert browse.tree.isHeaderHidden() == (view not in HEADINGS or not keyed), view
    if view == "people":
        assert not browse.tree.isHeaderHidden()


# ---- the days with their unit (decision 857) ----
def test_the_days_carry_their_unit():
    today = date(2026, 10, 8)
    shown = {n: task_tile.days_to(today + timedelta(days=n), today).shown for n in (0, 1, -3, 150)}
    assert shown == {0: "0 d", 1: "1 d", -3: "−3 d", 150: "99+ d"}
    assert task_tile.days_to(today + timedelta(days=1), today).text == "1"  # the bare number stays


def test_a_rows_last_words_stop_inside_its_ground(browse):
    open_rigging(browse)
    browse.select("task", "T000016")  # one row selected, the rest on the white
    img = grab(browse)
    w = browse.tree.viewport().width()
    for item in browse.tree.items():
        rect = browse.tree.visualItemRect(item)
        if not rect.isValid() or item.isSelected() or rect.bottom() > browse.tree.viewport().height():
            continue
        colours = {img.pixelColor(x, y).name() for x in range(w - ROW_INSET - ROW_END, w) for y in range(rect.top(), rect.bottom())}
        assert colours <= {tokens.colour("content")}, item.data(0, KEY_ROLE)


def test_the_action_strip_sits_inside_the_ground(browse, ctx):
    on_today(ctx)
    browse.refresh(render=False)
    browse.set_view("today")
    row = next(i for i in browse.tree.items() if i.data(0, ACTIONS_ROLE) is not None)
    strip = browse.tree.action_strip(row)
    assert strip is not None
    assert strip.geometry().right() + 1 == browse.tree.viewport().width() - ROW_INSET
    rect = browse.tree.fill_rect(browse.tree.visualItemRect(row))
    assert (strip.geometry().top(), strip.geometry().height()) == (rect.top(), rect.height())
