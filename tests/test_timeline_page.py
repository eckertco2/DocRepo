"""The Timeline page (release 5.40; decisions 228 to 234, 288 to 292 and the review's V5): Capacity under the chart on the same
dates, one People control, the spotlight, the calmer bars and the one row of controls. Driven offscreen."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from docrepo import capacity, load, tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import tokens  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.look import configure  # noqa: E402
from docrepo.ui.timeline_view import TimelineView  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    w.set_view("timeline")
    w.resize(1500, 950)
    QApplication.processEvents()
    yield w
    capture.deleteLater()
    w.deleteLater()


def over_week(browse, person: str = "P004"):
    """A task that makes a person very busy in the week of 12 Oct, for the tests that need someone over."""
    conn = browse.ctx.conn
    t = tasks.create_task(conn, SETTINGS, title="Big job", at=NOW, created_by="Test", assignees=[person], assignee_hours=60,
                          start="2026-10-12", due="2026-10-16")
    capacity.rebuild_task(conn, t, TODAY, SETTINGS)
    browse.refresh()
    browse.set_view("timeline")
    QApplication.processEvents()
    return t


def bucket_of(view, day: date) -> load.Bucket:
    return next(b for b in view.cap_rows.data.buckets if b.holds(day))


def click_cell(view, person: str, day: date) -> None:
    rows, b = view.cap_rows, bucket_of(view, day)
    QTest.mouseClick(rows, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rows.cell_rect(rows.line_of(person), b).center().toPoint())
    QApplication.processEvents()


# ---- one page ----
def test_one_sidebar_entry_and_capacitys_routes_lead_to_it(browse):
    """Decision 229."""
    assert "capacity" not in browse.nav.members["Plan"] and "timeline" in browse.nav.members["Plan"]
    view = browse.timeline
    view._set("cap_open", False)
    browse.set_view("today")
    browse.set_view("capacity")
    assert browse.view == "timeline" and browse.middle.currentWidget() is view and view.cap_open
    assert view.cap_rows.isVisibleTo(view)


def test_a_wheels_slice_naming_capacity_opens_the_page(browse):
    view = browse.timeline
    view._set("cap_open", False)
    browse.show_browse("capacity")
    assert browse.view == "timeline" and browse.middle.currentWidget() is view and view.cap_open


def test_settings_still_opens_with_no_capacity_page(browse):
    browse.set_view("settings")
    assert browse.middle.currentWidget() is browse.settings_view
    assert not hasattr(browse, "cap_table")


def test_a_day_is_in_one_place_all_down_the_page(browse):
    """The shared axis: head, rows and Capacity's two parts place a day alike, with a scroll bar in a part or not."""
    view = browse.timeline
    view.level(1)
    view.level(1)
    browse.resize(1300, 600)  # short, so the rows scroll
    QApplication.processEvents()
    assert view.scroll.verticalScrollBar().maximum() > 0
    day = date(2026, 10, 26)
    xs = {w: view.scale.x(w, day) for w in (view.head, view.chart, view.cap_team, view.cap_rows)}
    assert len(set(xs.values())) == 1
    assert view.chart.width() < view.head.width()  # the bar is there, and it makes no difference
    room_before = view.scale.room
    browse.resize(1500, 950)
    QApplication.processEvents()
    assert view.scale.room > room_before


def test_a_range_moves_both_halves_together(browse):
    view = browse.timeline
    first = view.cap_rows.data.buckets[0].first
    view.shift(1)
    assert view.cap_rows.data.buckets[0].first == first + timedelta(days=28)
    view._set("weeks", 52)
    assert len(view.cap_rows.data.buckets) >= 52 and not view.cap_rows.data.buckets[0].month


def test_a_long_range_on_a_narrow_track_goes_to_months(browse):
    """Decision 230: a typed range up to five years, with a cell for each month and its worst week's tint."""
    view = browse.timeline
    view.start, view.typed_days = date(2026, 9, 28), 1825
    view.render(view.model, view.today)
    assert view.cap_rows.data.buckets[0].month and len(view.cap_rows.data.buckets) in range(59, 63)
    over_week(browse)
    b = bucket_of(view, date(2026, 10, 12))
    assert load.tint(load.worst_week(view.cells, "P004", b)[0], 32) == "t5"
    view.cap_rows.grab()
    view.cap_team.grab()


# ---- Capacity's half ----
def test_a_cell_has_one_number_and_percent_starts(browse):
    """The review's decision V5."""
    view = browse.timeline
    assert view.cap_unit == "pct" and view.unit_buttons["pct"].isChecked()
    view.unit_buttons["hours"].click()
    assert view.cap_unit == "hours" and view.cap_rows.data.unit == "hours"
    assert json.loads(browse.ctx.conn.execute("SELECT value FROM app_state WHERE key = 'timeline_view'").fetchone()[0])["cap_unit"] == "hours"
    fresh = TimelineView()
    fresh.restore(view.settings())
    assert fresh.cap_unit == "hours"
    view.cap_rows.grab()


def test_the_sentence_says_whos_over_and_when(browse):
    """Decision 231."""
    view = browse.timeline
    over_week(browse)
    assert "Over in" in view.cap_say.text() and "Mike Ortiz" in view.cap_say.text()


def test_the_team_chart_counts_each_persons_own_overload(browse):
    view = browse.timeline
    over_week(browse)
    team, _ = load.team_bucket(view.cells, view.cap_team.data.people, bucket_of(view, date(2026, 10, 12)))
    assert team.over >= 60 - 32 and team.total < load.capacity_of(view.cap_team.data.people)
    view.cap_team.grab()
    assert "over people's own capacity" in view.cap_team.tip(bucket_of(view, date(2026, 10, 12)))


def test_group_by_group_puts_people_under_their_groups(browse):
    view = browse.timeline
    view.cap_group.click()
    assert view.cap_by_group and view.cap_rows.lines[0][0] == "group" and view.cap_rows.lines[1][0] == "person"
    assert view.settings()["cap_by_group"] is True
    view.cap_rows.grab()


def test_what_isnt_counted_is_said_and_its_tasks_open(browse):
    view = browse.timeline
    assert "Not counted" in view.cap_note.text() and not view.cap_list_box.isVisibleTo(view)
    view._note_link("nc:hours")
    assert view.cap_list_box.isVisibleTo(view) and view.cap_list.text().count("task:") == len(view.not_counted_ids["hours"])
    opened = []
    view.open_task.disconnect()
    view.open_task.connect(opened.append)
    view._undated_link(f"task:{view.not_counted_ids['hours'][0]}")
    assert opened == [view.not_counted_ids["hours"][0]]
    view._note_link("nc:hours")
    assert not view.cap_list_box.isVisibleTo(view)


def test_capacity_folds_and_keeps_its_head(browse):
    view = browse.timeline
    open_height = view.cap_box.height()
    view.cap_fold.click()
    QApplication.processEvents()
    assert not view.cap_open and not view.cap_rows.isVisibleTo(view) and view.cap_say.isVisibleTo(view)
    assert view.cap_box.height() < open_height and view.split.sizes()[0] > 300
    assert view.settings()["cap_open"] is False
    view.cap_fold.click()
    QApplication.processEvents()
    assert view.cap_open and view.cap_rows.isVisibleTo(view) and view.cap_box.height() >= view.CAP_MIN


def test_the_divider_is_remembered(browse):
    view = browse.timeline
    assert view.cap_h is None
    total = sum(view.split.sizes())
    view.split.setSizes([total - 200, 200])
    view._split_moved()
    assert view.cap_h == view.split.sizes()[1]
    fresh = TimelineView()
    fresh.restore(view.settings())
    assert fresh.cap_h == view.cap_h


def test_capacity_doesnt_take_more_than_its_share_to_start_with(browse):
    view = browse.timeline
    top, bottom = view.split.sizes()
    assert bottom <= int((top + bottom) * view.CAP_SHARE) and top >= view.TOP_MIN
    # All its rows show when there's room: no gap under them and no bar.
    assert view.cap_scroll.verticalScrollBar().maximum() == 0


# ---- one People control ----
def test_people_narrows_the_bars_and_the_load_together(browse):
    """Decision 232."""
    view = browse.timeline
    all_rows = len(view.chart.rows)
    view._set("people", ["P004"])
    assert [p.id for p in view.cap_rows.data.people] == ["P004"] and len(view.chart.rows) < all_rows
    assert [b.text() for b in view.chips.findChildren(QPushButton) if b.isVisibleTo(view.chips)] == ["Mike Ortiz  ×"]
    assert "Mike Ortiz" in view.people_button.text()
    next(b for b in view.chips.findChildren(QPushButton) if b.isVisibleTo(view.chips)).click()
    QApplication.processEvents()
    assert view.people == [] and len(view.chart.rows) == all_rows and view.chips.isHidden()


def test_clicking_a_name_picks_just_them_and_again_goes_back(browse):
    view = browse.timeline
    rows = view.cap_rows
    at = rows.cell_rect(rows.line_of("P003"), rows.data.buckets[0]).center().toPoint()
    at.setX(20)
    QTest.mouseClick(rows, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert view.people == ["P003"]
    QApplication.processEvents()
    at = rows.cell_rect(0, rows.data.buckets[0]).center().toPoint()
    at.setX(20)
    QTest.mouseClick(rows, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert view.people == []


# ---- the spotlight ----
def test_clicking_a_week_spotlights_whats_behind_it(browse):
    """Decision 233: a band through the chart, the bars behind it strong and the rest faded, and a card; nothing moves."""
    view = browse.timeline
    job = over_week(browse)
    view.level(1)
    rows_before = [r.task for r in view.chart.rows]
    sizes = view.split.sizes()
    click_cell(view, "P004", date(2026, 10, 12))
    assert view.spot is not None and view.spot.person == "P004" and view.chart.spot == (view.spot.first, view.spot.end)
    assert job in view.chart.strong and view.chart.strong != set(rows_before)
    assert [r.task for r in view.chart.rows] == rows_before and view.split.sizes() == sizes
    assert view.cap_card.isVisibleTo(view)
    words = " ".join(x.text() for x in view.cap_card.findChildren(QLabel) if x.isVisibleTo(view.cap_card))
    assert "Mike Ortiz, week of 12 Oct" in words and "Big job" in words and "60 h" in words
    assert view.cap_card.geometry().top() >= 0 and view.rect().contains(view.cap_card.geometry())
    view.chart.grab()
    view.cap_rows.grab()
    # A second click on it, or Esc, clears it.
    click_cell(view, "P004", date(2026, 10, 12))
    assert view.spot is None and view.chart.strong is None and not view.cap_card.isVisibleTo(view)
    click_cell(view, "P004", date(2026, 10, 12))
    QTest.keyClick(view.cap_rows, Qt.Key.Key_Escape)
    assert view.spot is None and view.chart.strong is None


def test_the_teams_column_spotlights_everyones_week(browse):
    view = browse.timeline
    job = over_week(browse)
    team = view.cap_team
    b = bucket_of(view, date(2026, 10, 12))
    QTest.mouseClick(team, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, team.column_rect(b).center().toPoint())
    QApplication.processEvents()
    assert view.spot is not None and view.spot.person == "" and job in view.chart.strong
    words = " ".join(x.text() for x in view.cap_card.findChildren(QLabel) if x.isVisibleTo(view.cap_card))
    assert "Team, week of 12 Oct" in words
    team.grab()


def test_a_task_on_the_card_opens_its_parents_and_is_selected(browse):
    view = browse.timeline
    conn = browse.ctx.conn
    t = tasks.create_task(conn, SETTINGS, title="Deep job", at=NOW, created_by="Test", parents=["T000003"], assignees=["P005"], assignee_hours=50,
                          start="2026-10-12", due="2026-10-16")
    capacity.rebuild_task(conn, t, TODAY, SETTINGS)
    browse.refresh()
    browse.set_view("timeline")
    view.open_ids.discard("T000003")
    view.render(view.model, view.today)
    click_cell(view, "P005", date(2026, 10, 12))
    assert t not in [r.task for r in view.chart.rows]
    view._card_task(t)
    assert view.sel == t and t in [r.task for r in view.chart.rows] and "T000003" in view.open_ids and view.spot is not None


def test_selecting_a_bar_outlines_the_weeks_it_adds_to(browse):
    view = browse.timeline
    job = over_week(browse)
    view._pick(job)
    assert ("P004", date(2026, 10, 12)) in view.cap_rows.data.adds and len(view.cap_rows.data.adds) == 1
    view._pick(None)
    assert not view.cap_rows.data.adds


def test_a_spot_goes_when_its_week_leaves_the_view(browse):
    view = browse.timeline
    click_cell(view, "P001", date(2026, 10, 12))
    assert view.spot is not None
    view.shift(1)
    view.shift(1)
    view.shift(1)
    assert view.spot is None and view.chart.spot is None


def test_the_keys_move_between_cells_and_pick_one(browse):
    view = browse.timeline
    rows = view.cap_rows
    rows.setFocus()
    QTest.keyClick(rows, Qt.Key.Key_Right)  # the first key lands on this week, on the top row
    assert rows.cur == (0, next(i for i, b in enumerate(rows.data.buckets) if b.holds(TODAY)))
    start = rows.cur[1]
    QTest.keyClick(rows, Qt.Key.Key_Right)
    QTest.keyClick(rows, Qt.Key.Key_Down)
    assert rows.cur == (1, start + 1) and "Priya Shah" in rows.accessibleDescription()
    rows.grab()
    QTest.keyClick(rows, Qt.Key.Key_Return)
    assert view.spot is not None and view.spot.person == "P002" and view.spot.first == rows.data.buckets[start + 1].first


def test_a_week_under_the_mouse_shows_through_the_chart(browse):
    view = browse.timeline
    view._week_hovered((date(2026, 10, 12), date(2026, 10, 19)))
    assert view.chart.hover_week == (date(2026, 10, 12), date(2026, 10, 19)) and view.cap_team.data.hover == view.chart.hover_week
    view.chart.grab()
    view._week_hovered(None)
    assert view.chart.hover_week is None


# ---- the bars ----
def test_bars_are_one_colour_by_default_and_a_lighter_solid_when_not_started(browse):
    """Decision 234."""
    view, chart = browse.timeline, browse.timeline.chart
    assert view.bars == "one" and view.bars_box.currentData() == "one"
    row = next(r for r in chart.rows if r.own and not r.routine)
    t = view.model.task(row.task)
    from dataclasses import replace

    fill, edge, _, hatched, dashed, _ = chart._bar_look(t, replace(row, not_started=False))
    light, ledge, _, lhatched, _, _ = chart._bar_look(t, replace(row, not_started=True))
    assert not hatched and not lhatched and edge is None and ledge is None and not dashed
    assert fill.lightness() < light.lightness()
    # Colour bars by stays, and it's kept.
    view._set("bars", "project")
    assert view.settings()["bars"] == "project" and view.settings()["bars_v"] == 2
    chart.grab()


def test_a_saved_project_colour_from_before_gives_way_once(browse):
    """Saved before bars could be one colour, "project" was only the default, so the new default takes over; chosen since, it stays."""
    old = TimelineView()
    old.restore({"weeks": 13, "bars": "project"})
    assert old.bars == "one" and old.weeks == 13
    chosen = TimelineView()
    chosen.restore({"bars": "project", "bars_v": 2})
    assert chosen.bars == "project"


def test_load_tints_can_be_read():
    """Each step's number at text's contrast, and the five steps tell apart without it."""

    def lum(c: str) -> float:
        q = QColor(c)
        return sum(w * ((v / 12.92) if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for w, v in zip((0.2126, 0.7152, 0.0722), (q.redF(), q.greenF(), q.blueF())))

    def contrast(a: str, b: str) -> float:
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    for look in (tokens.LIGHT, tokens.DARK):
        for step in ("load1", "load2", "load3", "load4"):
            assert contrast(look["text"], look[step]) >= 4.5, step
        assert contrast(look["load5_ink"], look["load5"]) >= 4.5
        assert contrast(look["load5"], look["content"]) >= 3  # a mark that means something, with no number on it


# ---- the row of controls ----
def test_the_controls_are_there_with_the_range_at_the_rows_end(browse):
    """That they fit on one row is checked on the real platform, in ``test_real_look.py``."""
    view = browse.timeline
    for name in ("Plan", "Display", "Legend"):
        assert any(b.text() == name for b in view.tools.findChildren(QPushButton))
    assert view.range_box.property("flowEnd") is True


def test_display_holds_how_its_drawn(browse):
    view = browse.timeline
    view.display_button.click()
    QApplication.processEvents()
    assert view.display_box.isVisible()
    view.order_box.setCurrentIndex(view.order_box.findData("person"))
    assert view.order == "person" and view.head.field == "Person"
    view.display_box.hide()
    # Picking in it doesn't lose it: the same boxes are kept across the redraw.
    assert view.order_box.currentData() == "person"
    view.routine_box.click()
    assert view.routine is False
    view.hours_buttons[True].click()
    assert view.a_week is True


def test_the_legend_says_what_the_marks_and_tints_mean(browse):
    view = browse.timeline
    view.legend_button.click()
    QApplication.processEvents()
    assert view.legend_box.isVisible()
    words = view.legend.text()
    for part in ("Not&nbsp;started", "Deadline", "Plant&nbsp;event", "80&nbsp;to&nbsp;100%", "125%&nbsp;or&nbsp;more"):
        assert part in words
    view.legend_box.hide()


def test_filters_in_use_show_as_chips_and_focus_is_one(browse):
    view = browse.timeline
    view._set("focus", "T000003")
    chips = [b.text() for b in view.chips.findChildren(QPushButton) if b.isVisibleTo(view.chips)]
    assert len(chips) == 1 and chips[0].startswith("Focus: ")
    next(b for b in view.chips.findChildren(QPushButton) if b.isVisibleTo(view.chips)).click()
    QApplication.processEvents()
    assert view.focus is None


def test_the_levels_are_at_the_head_of_the_names_and_go_where_nothing_nests(browse):
    view = browse.timeline
    assert all(not b.isHidden() for b in view.level_buttons)
    view._set("people", ["P006"])
    if not any(r.kids for r in view.chart.rows):
        assert all(b.isHidden() for b in view.level_buttons)


# ---- what's selected ----
def test_picking_a_bar_moves_nothing(browse):
    """Decision 292: a line under the chart, always there."""
    view = browse.timeline
    before = view.scroll.height(), view.head.y(), view.card.height()
    view._pick("T000002")
    QApplication.processEvents()
    assert (view.scroll.height(), view.head.y(), view.card.height()) == before
    assert not view.open_button.isHidden() and view.model.task("T000002").title in view.card_text.text()
    assert view.model.task("T000002").title in view.card_text.toolTip()
    view.card_text.grab()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.sel is None and view.open_button.isHidden()


def test_tasks_with_no_dates_join_the_chart_only_while_their_fold_is_open(browse):
    """Decision 291."""
    view = browse.timeline
    n = len(view.undated_ids)
    assert n and view.undated_fold.text() == f"{n} with no dates"
    view.set_plan(True)
    assert not any(r.undated for r in view.chart.rows) and len(view.undated_ids) == n  # still counted
    view.undated_fold.click()
    assert view.undated_box.isVisibleTo(view) and "on the chart now" in view.undated_names.text()
    view.level(1)
    assert any(r.undated for r in view.chart.rows)
    view.undated_fold.click()
    view.set_plan(False)
    view.undated_fold.click()
    assert "Plan mode" in view.undated_names.text() and view.undated_names.text().count("task:") == n


# ---- the Classic look keeps its own ----
def test_the_classic_look_keeps_the_chart_alone_and_capacitys_page(qapp, sample_root):
    conn, root, fs = sample_root
    configure("classic", False)
    try:
        ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
        capture = CaptureWindow(ctx)
        w = BrowseWindow(ctx, capture)
        w.show_browse()
        w.set_view("capacity")
        assert w.view == "capacity" and w.middle.currentWidget() is w.cap_page and w.cap_table.rowCount() == 6
        w.set_view("timeline")
        view = w.timeline
        assert view.bars == "project" and not hasattr(view, "cap_box") and view.legend.isVisibleTo(view)
        assert w.middle.currentWidget() is view
        view._set("bars", "hours")
        view.chart.grab()
        view.head.grab()
        w.set_view("settings")
        assert w.middle.currentWidget() is w.settings_view
        capture.deleteLater()
        w.deleteLater()
    finally:
        configure("new", False)
