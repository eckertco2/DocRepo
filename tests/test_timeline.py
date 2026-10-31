"""The timeline view (mods log round 1, M0019; round 4, M0067, releases 5.29 and 5.30): its rows from the sample data,
and the view in the browse tool, Plan mode's drags included."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QDate, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from docrepo import people, tasks, timeline  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.timeline_view import TimelineView, week_from  # noqa: E402

TODAY = date(2026, 10, 8)  # a Thursday
START = timeline.default_start(TODAY)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def rows(tl: timeline.Timeline) -> list[str]:
    return [("  " * r.depth) + r.task + (" ctx" if r.ctx else "") + (" undated" if r.undated else "") for r in tl.rows]


def every(m: Model) -> set[str]:
    return set(m.tasks)


def test_the_range_and_its_scale():
    tl = timeline.Timeline(START, 9, (), ())
    assert (START, tl.end, tl.days) == (date(2026, 9, 28), date(2026, 11, 30), 63)
    assert tl.months() == [date(2026, 10, 1), date(2026, 11, 1)]  # September has only three days in view, so it's not named
    assert tl.week_starts()[:3] == [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)]
    long = timeline.Timeline(date(2026, 9, 7), 26, (), ())
    assert long.months()[0] == date(2026, 9, 7) and len(long.week_starts()) == 7  # every fourth week
    assert [n for n, _ in timeline.RANGES] == [9, 13, 26, 52]  # 3 and 12 months (decision 133)
    assert [timeline.step(n) for n in (9, 13, 26, 52)] == [4, 4, 13, 26]


def test_a_typed_range_is_its_exact_days():
    """Decision 225: from any day of the week; the scale still marks Mondays, and a short range still names its month."""
    tl = timeline.Timeline(date(2027, 1, 13), 2, (), (), typed_days=10)  # a Wednesday, ten days
    assert (tl.end, tl.days) == (date(2027, 1, 23), 10)
    assert tl.week_starts() == [date(2027, 1, 18)]
    assert tl.months() == [date(2027, 1, 13)]
    assert timeline.Timeline(date(2027, 1, 29), 1, (), (), typed_days=2).months() == [date(2027, 1, 29)]  # under a week, no new month
    assert timeline.Timeline(date(2027, 1, 29), 1, (), (), typed_days=6).months() == [date(2027, 2, 1)]
    assert len(timeline.Timeline(date(2027, 1, 1), 157, (), (), typed_days=1095).week_starts()) == 12  # every thirteenth over two years
    # Earlier and Later: as Show's ranges, but never further than the range, so no days are skipped.
    assert [timeline.step_days(9), timeline.step_days(52)] == [28, 182]
    assert [timeline.step_days(9, 3), timeline.step_days(9, 10), timeline.step_days(9, 63), timeline.step_days(9, 365)] == [3, 10, 28, 182]


@pytest.mark.parametrize("text, first, last", [
    ("2027-01-31", date(2027, 1, 31), date(2027, 1, 31)),
    ("31 Jan 2027", date(2027, 1, 31), date(2027, 1, 31)),
    ("1 Jan 2027", date(2027, 1, 1), date(2027, 1, 1)),  # ten characters, as a YYYY-MM-DD is
    ("Sun 31 Jan 2027", date(2027, 1, 31), date(2027, 1, 31)),
    ("31 January 2027", date(2027, 1, 31), date(2027, 1, 31)),
    ("Jan 31, 2027", date(2027, 1, 31), date(2027, 1, 31)),
    ("  feb 2028 ", date(2028, 2, 1), date(2028, 2, 29)),  # a month: its first day, or its last for To
    ("February 2027", date(2027, 2, 1), date(2027, 2, 28)),
])
def test_read_range_day(text, first, last):
    assert timeline.read_range_day(text) == first
    assert timeline.read_range_day(text, last=True) == last


@pytest.mark.parametrize("text", ["", "soon", "2027-13-01", "31 Feb 2027", "Jan", "0207-01-01", "1 Jan 1066"])
def test_read_range_day_leaves_what_it_cant_read(text):
    assert timeline.read_range_day(text) is None


def test_a_typed_range_finds_what_falls_in_it(sample_conn):
    m = Model(sample_conn)
    tl = timeline.build(m, TODAY, date(2026, 10, 19), 9, typed_days=3, open_ids={"T000001", "T000008"})
    assert (tl.weeks, tl.days, tl.end) == (1, 3, date(2026, 10, 22))
    by_id = {r.task: r for r in tl.rows}
    assert by_id["T000008"].windows == ((date(2026, 10, 19), date(2026, 10, 30)),)  # it reaches into view
    assert by_id["T000008"].deadline is None  # its deadline, 30 Oct, is past the range's last day


def test_one_row_per_project_folded_to_start_with(sample_conn):
    """Decision 133: no group headers; each top-level task is a row, its subtasks shown when it's open."""
    m = Model(sample_conn)
    tl = timeline.build(m, TODAY, START, 9)
    assert rows(tl) == ["T000001", "T000002", "T000006", "T000010"]
    assert tl.undated == ("T000015", "T000016")
    top = {r.task: r for r in tl.rows}
    assert (top["T000001"].kids, top["T000001"].open) == (3, False)
    # The summary bar: its subtasks' span, with their deadlines in view.
    assert top["T000001"].span == (date(2026, 9, 22), date(2026, 10, 30))
    assert top["T000001"].sub_deadlines == (date(2026, 10, 19), date(2026, 10, 30))
    opened = timeline.build(m, TODAY, START, 9, open_ids={"T000001", "T000008"})
    # The tree's shape; parked and closed tasks are left out, and so are tasks with no dates, named below instead.
    assert rows(opened) == ["T000001", "  T000008", "    T000012", "    T000019", "  T000009", "  T000011", "T000002", "T000006", "T000010"]
    by_id = {r.task: r for r in opened.rows}
    assert by_id["T000008"].windows == ((date(2026, 10, 19), date(2026, 10, 30)),) and by_id["T000008"].deadline == date(2026, 10, 30)
    assert by_id["T000008"].sub_deadlines == (date(2026, 10, 19),) and by_id["T000008"].open
    assert by_id["T000019"].not_started and by_id["T000019"].deadline == date(2026, 10, 19)
    assert len(by_id["T000010"].windows) == 8 and by_id["T000010"].routine  # weekly, one dot each
    assert by_id["T000006"].windows[0] == (date(2026, 9, 26), date(2026, 9, 30))  # a routine window that spans days
    assert [by_id[x].colour for x in ("T000001", "T000012", "T000002", "T000006", "T000010")] == [0, 0, 1, 5, 6]  # the tree's colours
    assert not any(r.late for r in by_id.values())
    later = timeline.build(m, date(2026, 10, 20), timeline.default_start(date(2026, 10, 20)), 9, open_ids=every(m))
    assert [r.task for r in later.rows if r.late] == ["T000012", "T000019", "T000017"]  # due 14, 9 and 16 Oct, still open
    assert "Lead: Me\nAssignees: Tom Becker, Mike Ortiz" in timeline.tooltip(m, "T000008", TODAY)


def test_hours_on_the_bars(sample_conn):
    """Decision 135: the total, or that a week over its workdays; nothing without hours."""
    m = Model(sample_conn)
    impeller, rings = m.task("T000001"), m.task("T000019")
    assert timeline.hours(impeller, TODAY) == (36.0, 2.8125)  # Me 20 h as lead, Tom 16 h as assignee, over 64 workdays
    assert (timeline.hours_label(impeller, TODAY, False), timeline.hours_label(impeller, TODAY, True)) == ("36 h", "2.8 h/wk")
    assert timeline.hours_words(m, impeller, TODAY) == "36 h: Me 20 h as lead, Tom Becker 16 h as assignee · about 2.8 h a week"
    assert "Tom Becker and Mike Ortiz 60 h each as assignees" in timeline.hours_words(m, m.task("T000008"), TODAY)
    assert (timeline.hours(rings, TODAY), timeline.hours_label(rings, TODAY, False), timeline.hours_words(m, rings, TODAY)) == (None, "", "No hours yet")
    assert [timeline.hour_bin(t, TODAY) for t in (impeller, m.task("T000008"), rings)] == [1, 4, -1]
    assert timeline.workdays(date(2026, 10, 9), date(2026, 10, 12)) == 2  # Friday to Monday


def test_plant_events_are_bands_and_name_the_dates_in_them(sample_conn):
    """Release 5.9 (M0028): a plant event is shaded down the whole chart, whatever the filters, and a date inside one
    is named under the dates where they're picked. Release 5.29: it's in the events lane, with the tasks in it."""
    event = tasks.create_task(sample_conn, Settings(me="P001"), title="Spring outage", at=datetime(2026, 10, 8, 9, 0), created_by="Excel import",
                              start="2026-11-03", due="2026-11-14", plant_event=True)
    m = Model(sample_conn)
    tl = timeline.build(m, TODAY, START, 9, labels=("Safety",))
    assert tl.events == (timeline.Band(event, "Spring outage", date(2026, 11, 3), date(2026, 11, 14)),)
    assert timeline.tasks_during(m, tl.events[0], TODAY) == 2  # the weekly meeting and the monthly safety report come round in it
    assert timeline.bands(m, date(2026, 9, 28), date(2026, 11, 3)) == ()
    assert any(r.task == event and r.plant_event for r in timeline.build(m, TODAY, START, 9).rows)
    tasks.update_task(sample_conn, Settings(me="P001"), event, at=datetime(2026, 10, 8, 9, 0), via="Browse tool", recurrence="Monthly")
    assert [b.start for b in timeline.bands(Model(sample_conn), date(2026, 11, 1), date(2027, 1, 1))] == [date(2026, 11, 3), date(2026, 12, 3)]
    assert timeline.during(m, date(2026, 11, 14)).task == event and timeline.during(m, date(2026, 11, 15)) is None
    assert timeline.during(m, date(2026, 11, 5), event) is None  # its own dates don't count
    assert (timeline.during_text(m, [("Start", "2026-10-30"), ("Due", "2026-11-06"), ("Deadline", "not a date")], TODAY)
            == "Due falls during Spring outage, Tue 3 Nov to Sat 14 Nov.")


def test_order_by_sorts_rows_under_their_parent_and_colours_them(sample_conn):
    """Decision 133: Order by label, person, group or a parent label sorts the rows that share a parent by their key,
    then their first date, and gives each its key's place, for its title's colour."""
    m = Model(sample_conn)
    by_label = timeline.build(m, TODAY, START, 9, "label", open_ids={"T000001"})
    assert by_label.keys[:4] == ("Line 1", "Line 2", "Strategic Plan", "Safety")
    assert rows(by_label) == ["T000001", "  T000009", "  T000011", "  T000008", "T000002", "T000006", "T000010"]
    assert [r.key for r in by_label.rows] == [0, 0, 0, 0, 3, 3, None]  # Business team meeting has no label: last, grey
    by_group = timeline.build(m, TODAY, START, 9, "group", open_ids=every(m))
    assert by_group.keys == ("Engineering", "Maintenance", "Purchasing")
    assert rows(by_group)[-2:] == ["T000010", "T000006"]
    people.add_label(sample_conn, "Production line")
    for name in ("Line 1", "Line 2"):
        people.update_label(sample_conn, name, parent="Production line")
    m = Model(sample_conn)
    assert timeline.order_choices(m)[3:] == [("group", "group"), ("parent:Production line", "Production line")]
    lines = timeline.build(m, TODAY, START, 9, "parent:Production line")
    assert lines.keys == ("Line 1", "Line 2") and lines.rows[0].key == 0
    tip = timeline.tooltip(m, "T000001", TODAY, "label")
    assert "36 h: Me 20 h as lead" in tip


def test_filters_and_focus(sample_conn):
    m = Model(sample_conn)
    assert rows(timeline.build(m, TODAY, START, 9, people=("P002",), open_ids=every(m))) == ["T000001 ctx", "  T000009", "  T000011", "T000010"]
    assert rows(timeline.build(m, TODAY, START, 9, "person", people=("P005",), open_ids=every(m))) == ["T000001 ctx", "  T000008 ctx", "    T000019"]
    assert rows(timeline.build(m, TODAY, START, 9, routine=False)) == ["T000001", "T000002"]
    assert rows(timeline.build(m, TODAY, START, 9, focus="T000008", open_ids={"T000008"})) == ["T000008", "  T000012", "  T000019"]


def test_plan_mode_shows_undated_tasks_as_rows(sample_conn):
    """Decision 136: in Plan mode an open task with no dates is a row, under its parent (a parked parent dimmed)."""
    m = Model(sample_conn)
    tl = timeline.build(m, TODAY, START, 9, plan=True, open_ids=every(m))
    assert rows(tl)[rows(tl).index("T000003 ctx") + 1] == "  T000015 undated"
    assert "T000016 undated" in rows(tl) and "  T000015 undated" in rows(tl) and tl.undated == ()
    assert "drag its name onto the chart" in timeline.tooltip(m, "T000016", TODAY, plan=True)
    # A dropped name is a working week: Saturday moves to Monday, Wednesday runs to Tuesday.
    assert week_from(date(2026, 10, 10)) == (date(2026, 10, 12), date(2026, 10, 16))
    assert week_from(date(2026, 10, 14)) == (date(2026, 10, 14), date(2026, 10, 20))


# ---- the view in the browse tool ----
@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: datetime(2026, 10, 8, 14, 10))
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    w.set_view("timeline")
    w.resize(1400, 900)
    QApplication.processEvents()
    yield w
    QApplication.processEvents()
    capture.deleteLater()
    w.deleteLater()


def _row_point(chart, task_id: str, x: float) -> QPoint:
    top = chart.top_of(task_id)
    assert top is not None, task_id
    return QPoint(int(x), top + chart.ROW_H // 2)


def test_the_view_folds_selects_and_opens(browse):
    w = browse
    view, chart = w.timeline, w.timeline.chart
    assert w.middle.currentWidget() is view and not w.detail.isVisible()
    assert [r.task for r in chart.rows] == ["T000001", "T000002", "T000006", "T000010"]
    # The arrow opens a project, and the choice is kept in docs.db.
    QTest.mouseClick(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _row_point(chart, "T000001", 15))
    assert "T000008" in [r.task for r in chart.rows] and "T000001" in view.open_ids
    assert "T000001" in (w.ctx.conn.execute("SELECT value FROM app_state WHERE key = 'timeline_open'").fetchone()[0])
    # A click selects and shows the card; a second click doesn't open the task any more (decision 138).
    QTest.mouseClick(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _row_point(chart, "T000008", 120))
    assert view.sel == "T000008" and "Installation" in view.card_text.text() and "128 h" in view.card_text.text()
    QTest.mouseClick(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _row_point(chart, "T000008", 120))
    assert w.view == "timeline"
    # Left folds it, Right opens it; Collapse and Expand a level.
    QTest.keyClick(chart, Qt.Key.Key_Left)  # T000008 is open? no: it moves to its parent
    view.level(1)
    assert "T000012" in [r.task for r in chart.rows]
    view.level(-1)
    assert "T000012" not in [r.task for r in chart.rows] and "T000008" in [r.task for r in chart.rows]
    view.shift(1)
    assert view.start == date(2026, 10, 26)
    view.shift(0)
    assert view.start == date(2026, 9, 28)
    for order, bars, a_week, weeks in (("label", "hours", True, 52), ("group", "priority", False, 13)):
        view._set("order", order)
        view._set("bars", bars)
        view._set("a_week", a_week)
        view._set("weeks", weeks)
        chart.grab()  # paints without errors
        view.head.grab()
    # Enter opens the selected task.
    view._pick("T000002")
    QTest.keyClick(chart, Qt.Key.Key_Return)
    assert (w.view, w.sel) == ("tasks", ("task", "T000002"))


def _type_range(field, text: str) -> None:
    field.line.setFocus()
    field.line.selectAll()
    QTest.keyClicks(field.line, text)
    QTest.keyClick(field.line, Qt.Key.Key_Return)


def _kept(browse) -> dict:
    return json.loads(browse.ctx.conn.execute("SELECT value FROM app_state WHERE key = 'timeline_view'").fetchone()[0])


def _show_box(view):
    return next(view.time_layout.itemAt(i).widget() for i in range(view.time_layout.count())
                if isinstance(view.time_layout.itemAt(i).widget(), QComboBox) and view.time_layout.itemAt(i).widget().accessibleName() == "Show")


def test_a_range_typed_by_hand(browse):
    """Item 70, decision 225: From and To say what's in view; a typed day shows exactly those days, kept until a Show choice
    replaces them, and Earlier, Later and This week keep its length."""
    view, chart = browse.timeline, browse.timeline.chart
    from docrepo.ui.widgets import parse_day

    def boxes() -> tuple[date | None, date | None]:
        return parse_day(view.range_from.line.text()), parse_day(view.range_to.line.text())

    assert boxes() == (date(2026, 9, 28), date(2026, 11, 29))  # a Show choice's range, in the boxes
    assert view.typed_days is None and _show_box(view).currentData() == 9
    # To alone: the range ends there, from the same first day; From alone next: exactly those days.
    _type_range(view.range_to, "2026-12-16")
    assert (view.start, view.typed_days) == (date(2026, 9, 28), 80)
    _type_range(view.range_from, "14 Oct 2026")  # a Wednesday
    assert (view.start, view.typed_days, chart.tl.end) == (date(2026, 10, 14), 64, date(2026, 12, 17))
    assert _show_box(view).currentData() == 0 and _show_box(view).currentText() == "Show these dates"
    chart.grab()
    view.head.grab()
    # It's kept for next time, and read back.
    assert _kept(browse)["range"] == ["2026-10-14", "2026-12-16"]
    fresh = TimelineView()
    fresh.restore(_kept(browse))
    assert (fresh.start, fresh.typed_days) == (date(2026, 10, 14), 64)
    # Later, Earlier and This week keep its length.
    view.shift(1)
    assert (view.start, view.typed_days) == (date(2026, 11, 11), 64)
    assert boxes() == (date(2026, 11, 11), date(2027, 1, 13))
    assert _kept(browse)["range"] == ["2026-11-11", "2027-01-13"]
    view.shift(-1)
    assert view.start == date(2026, 10, 14)
    view.shift(0)
    assert (view.start, view.typed_days) == (date(2026, 9, 28), 64)
    # A From past To takes To along, and a To before From takes From back, so retyping both never stops at a wrong range.
    _type_range(view.range_from, "2027-01-01")
    assert (view.start, view.typed_days) == (date(2027, 1, 1), 64)
    _type_range(view.range_to, "Dec 2027")
    assert (view.start, view.typed_days) == (date(2027, 1, 1), 365)
    _type_range(view.range_to, "2026-11-30")
    assert (view.start, view.typed_days) == (date(2025, 12, 1), 365)
    # A Show choice replaces it, from the Monday of its first week, and it's no longer kept.
    _type_range(view.range_from, "2026-10-14")
    view._set("weeks", 13)
    assert (view.start, view.typed_days, view.weeks) == (date(2026, 10, 12), None, 13)
    assert "range" not in _kept(browse)
    assert _show_box(view).currentData() == 13 and _show_box(view).findData(0) == -1


def test_a_range_typed_wrongly_says_so_and_changes_nothing(browse):
    view, chart = browse.timeline, browse.timeline.chart
    before = chart.tl
    _type_range(view.range_from, "soon")
    assert chart.tl is before and view.typed_days is None
    assert not view.range_note.isHidden() and view.range_note.text().startswith("From:")
    assert view.range_from.line.text() == "soon"  # left as typed, to fix
    # A redraw doesn't lose it.
    view.render(view.model, view.today)
    assert view.range_from.line.text() == "soon" and view.range_from.line.isModified()
    _type_range(view.range_from, "1 Jan 2020")
    assert "five years" in view.range_note.text() and view.typed_days is None
    _type_range(view.range_from, "2026-09-28")  # the first day it already shows: nothing new, and a Show choice stays one
    assert view.range_note.isHidden() and view.typed_days is None and _show_box(view).currentData() == 9
    # A range kept that makes no sense is left out.
    fresh = TimelineView()
    for nonsense in (["2027-01-02", "2027-01-01"], ["2027-01-01"], ["soon", "later"], None, ["2020-01-01", "2029-01-01"]):
        fresh.restore({"range": nonsense})
        assert fresh.typed_days is None and fresh.start is None


def test_the_boxes_survive_a_redraw_and_the_calendar_picks(browse):
    view = browse.timeline
    box = view.range_box
    view._set("bars", "hours")
    QApplication.processEvents()
    assert view.range_box is box and not box.isHidden()
    assert view.time_layout.indexOf(box) > 0
    view.range_to.calendar.setSelectedDate(QDate(2026, 12, 31))
    view.range_to.calendar.clicked.emit(QDate(2026, 12, 31))
    assert (view.start, view.typed_days) == (date(2026, 9, 28), 95)


def test_double_click_asks_for_quick_edit(browse):
    view, chart = browse.timeline, browse.timeline.chart
    asked = []
    view.quick_edit.disconnect()
    view.quick_edit.connect(lambda task_id, rect: asked.append((task_id, rect.width() > 0)))
    QTest.mouseDClick(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _row_point(chart, "T000002", 120))
    assert asked == [("T000002", True)]


def test_plan_mode_drags_save_log_and_undo(browse):
    w = browse
    view, chart = w.timeline, w.timeline.chart
    QTest.keyClick(chart, Qt.Key.Key_P)
    assert view.plan and view.plan_strip.isVisible()
    view.set_open("T000003", True)
    assert "T000015" in [r.task for r in chart.rows if r.undated]
    # Drag the undated subtask's name onto the chart: a working week from where it's let go.
    grip = _row_point(chart, "T000015", chart._grip_rect(next(r for r in chart.rows if r.task == "T000015"), 0).center().x())
    target = chart.scale.x(chart, date(2026, 10, 14)) + 2
    QTest.mousePress(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
    QTest.mouseMove(chart, QPoint(int(grip.x() + 20), grip.y()))
    QTest.mouseMove(chart, QPoint(int(target), grip.y()))
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(target), grip.y()))
    t = Model(w.ctx.conn).task("T000015")
    assert (t.start, t.due) == ("2026-10-14", "2026-10-20")
    log = w.ctx.conn.execute("SELECT field, via FROM status_log WHERE task = 'T000015' ORDER BY id").fetchall()
    assert sorted(tuple(x) for x in log[-2:]) == [("Due", "Browse tool"), ("Start", "Browse tool")]  # logged as Edit task's edits are
    assert "Start and Due set" in w.status.text()
    # Stretch its end by two days.
    bar = chart.bar_rect(next(r for r in chart.rows if r.task == "T000015"), chart.top_of("T000015"))
    end = QPoint(int(bar.right() - 2), int(bar.center().y()))
    QTest.mousePress(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    QTest.mouseMove(chart, QPoint(end.x() + 5, end.y()))
    QTest.mouseMove(chart, QPoint(int(end.x() + 2 * chart.scale.px_per_day(chart)), end.y()))
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(end.x() + 2 * chart.scale.px_per_day(chart)), end.y()))
    assert Model(w.ctx.conn).task("T000015").due == "2026-10-22"
    # Ctrl+Z, twice: back to no dates at all.
    QTest.keyClick(chart, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert Model(w.ctx.conn).task("T000015").due == "2026-10-20"
    QTest.keyClick(chart, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    t = Model(w.ctx.conn).task("T000015")
    assert (t.start, t.due) == (None, None)
    # Outside Plan mode nothing drags.
    QTest.keyClick(chart, Qt.Key.Key_P)
    assert not view.plan and not chart._hit(target, grip.y())[1] in ("grip", "move", "start", "end")


def test_double_click_opens_quick_edit_and_its_save_redraws_the_chart(browse):
    """Decision 138 with item 55: the browse window opens Quick edit beside the bar; what it saves shows on the chart."""
    w = browse
    chart = w.timeline.chart
    QTest.mouseDClick(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _row_point(chart, "T000002", 120))
    qe = w.quick_window
    assert qe is not None and qe.isVisible() and qe.task.id == "T000002"
    QTest.keyClicks(qe.box, "due 20 Nov")
    qe.save()
    QApplication.processEvents()
    assert Model(w.ctx.conn).task("T000002").due == "2026-11-20"
    row = next(r for r in chart.rows if r.task == "T000002")
    assert row.windows[0][1] == date(2026, 11, 20) and w.timeline.sel == "T000002"


def test_a_plant_event_without_a_start_is_one_day(sample_root):
    """Release 5.30 (the owner's hand test): a plant event typed with only its date is that day, not a range from the day
    it was noted; one with a Start, even today's, is a range. Other tasks still start the day they were made."""
    from docrepo.save import CaptureDraft, NewTaskFields, save_capture

    conn, root, fs = sample_root
    s = Settings(me="P001")
    at = datetime(2026, 10, 8, 9, 0)
    one = save_capture(conn, root, fs, s, CaptureDraft(content="Boiler inspection", types={"new_task"}, new_task=NewTaskFields(
        title="Boiler inspection", due="2026-10-30", plant_event=True)), at).created_task
    today = save_capture(conn, root, fs, s, CaptureDraft(content="Fall turnaround", types={"new_task"}, new_task=NewTaskFields(
        title="Fall turnaround", start="2026-10-08", due="2026-10-16", plant_event=True)), at).created_task
    work = save_capture(conn, root, fs, s, CaptureDraft(content="Order gaskets", types={"new_task"}, new_task=NewTaskFields(
        title="Order gaskets", start="2026-10-08", due="2026-10-16")), at).created_task
    m = Model(conn)
    assert (m.task(one).start, m.task(today).start, m.task(work).start) == (None, "2026-10-08", None)
    tl = timeline.build(m, TODAY, START, 9)
    assert [(b.title, b.start, b.end) for b in tl.events] == [("Fall turnaround", date(2026, 10, 8), date(2026, 10, 16)),
                                                              ("Boiler inspection", date(2026, 10, 30), date(2026, 10, 30))]
    assert timeline.during(m, date(2026, 10, 20)) is None and timeline.during(m, date(2026, 10, 30)).title == "Boiler inspection"
    from docrepo.schedule import start_of, windows

    assert start_of(m.task(work)) == date(2026, 10, 8) and windows(m.task(work), date(2027, 1, 1)) == [(date(2026, 10, 8), date(2026, 10, 16))]


def test_ordered_by_a_field_the_lane_column_names_it(browse):
    """The owner's hand test of 5.29: ordered by a field, a band in a lane column left of the names stretches down each run
    of rows with the same key and names it; the view's choices are kept for next time."""
    view, chart = browse.timeline, browse.timeline.chart
    view.level(1)
    assert chart.runs == [] and chart.scale.key_w == 0
    view._set("order", "person")
    assert chart.scale.key_w > 0 and view.head.field == "Person"
    names = [name for _, _, _, name in chart.runs]
    assert names[0] == "Me" and "Priya Shah" in names
    first, last, key, _ = chart.runs[0]
    assert all(chart.rows[i].key == key for i in range(first, last + 1)) and last > first  # a band over several rows
    assert all(a[1] + 1 == b[0] for a, b in zip(chart.runs, chart.runs[1:]))  # every row is in one band
    chart.grab()
    view._set("weeks", 13)
    view._set("bars", "hours")
    kept = json.loads(browse.ctx.conn.execute("SELECT value FROM app_state WHERE key = 'timeline_view'").fetchone()[0])
    assert kept == {"weeks": 13, "order": "person", "bars": "hours", "a_week": False, "routine": True}
    fresh = TimelineView()
    fresh.restore(kept | {"weeks": 7, "bars": "nonsense"})  # a value it no longer offers is left at its default
    assert (fresh.weeks, fresh.order, fresh.bars) == (9, "person", "project")


# ---- key dates on the timeline (release 5.31, the key dates plan, item 58 and decision 152) ----
def _key_dates(conn, task_id: str, *rows) -> None:
    from docrepo.tasks import set_key_dates

    set_key_dates(conn, task_id, list(rows), at=datetime(2026, 10, 8, 9, 0), via="Browse tool")


def test_key_dates_are_marks_on_their_task_s_row(sample_conn):
    """A task whose only dates are key dates has a row of its own, with its marks; a parent's summary bar takes in its
    subtasks' key dates, their deadlines among its diamonds; the tooltip lists them."""
    from docrepo.tasks import KeyDateRow

    _key_dates(sample_conn, "T000016",
               KeyDateRow("2026-10-01", None, "Planning period"),
               KeyDateRow("2026-10-12", "2026-10-16", "Rota drafted"),
               KeyDateRow(None, "2026-10-20", "Rota signed off", deadline=True),
               KeyDateRow(None, "2026-10-07", "Old draft", done=True),
               KeyDateRow(None, "2027-03-01", "Too far off"))
    _key_dates(sample_conn, "T000012", KeyDateRow(None, "2026-11-20", "Lift plan approved", deadline=True))
    m = Model(sample_conn)
    tl = timeline.build(m, TODAY, START, 9, open_ids={"T000001", "T000008"})
    rows_ = {r.task: r for r in tl.rows}
    assert "T000016" in rows_ and not rows_["T000016"].ctx and "T000016" not in tl.undated
    marks_ = [(k.kind, k.description, k.deadline, k.done) for k in rows_["T000016"].key_dates]
    assert marks_ == [("from", "Planning period", False, False), ("window", "Rota drafted", False, False),
                      ("by", "Rota signed off", True, False), ("by", "Old draft", False, True)]  # the one off the chart left out
    assert rows_["T000016"].windows == () and rows_["T000016"].deadline is None
    # The parent's summary bar reaches its subtask's key date, with its deadline as a diamond.
    assert rows_["T000008"].span[1] == date(2026, 11, 20) and date(2026, 11, 20) in rows_["T000008"].sub_deadlines
    assert rows_["T000001"].span[1] == date(2026, 11, 20)
    assert rows_["T000012"].key_dates[0].kind == "by" and rows_["T000012"].windows
    tip = timeline.tooltip(m, "T000016", TODAY)
    assert "Key dates:\n  Planning period, from Thu 1 Oct" in tip and "◆ Rota signed off, by Tue 20 Oct" in tip
    assert "Old draft, by Wed 7 Oct (done)" in tip
    # In Plan mode a task with key dates but no dates of its own isn't an undated row with a grip.
    assert not next(r for r in timeline.build(m, TODAY, START, 9, plan=True).rows if r.task == "T000016").undated


def test_plant_activities_are_plant_events(sample_conn):
    """Decision 149: a key date ticked as a plant activity is a band, in the lane, and in the lines naming what falls in
    one; its own task doesn't count it."""
    from docrepo.schedule import windows
    from docrepo.tasks import KeyDateRow

    _key_dates(sample_conn, "T000008", KeyDateRow("2026-10-20", "2026-10-22", "Crane lift", plant=True),
               KeyDateRow(None, "2026-10-26", plant=True))
    m = Model(sample_conn)
    kds = m.key_dates_of("T000008")
    tl = timeline.build(m, TODAY, START, 9)
    assert tl.events == (timeline.Band("T000008", "Crane lift", date(2026, 10, 20), date(2026, 10, 22), kds[0].id),
                         timeline.Band("T000008", "Installation", date(2026, 10, 26), date(2026, 10, 26), kds[1].id))
    assert timeline.during(m, date(2026, 10, 21)).title == "Crane lift"
    assert timeline.during(m, date(2026, 10, 21), "T000008") is None  # its own task's dates don't count
    assert timeline.during_text(m, [("Due", "2026-10-21")], TODAY, "T000002") == "Due falls during Crane lift, Tue 20 Oct to Thu 22 Oct."
    far = date(2036, 1, 1)
    expected = sum(1 for t in m.tasks.values() if t.id != "T000008" and t.state in ("Not started", "In progress") and not t.plant_event
                   and not t.discarded and any(a <= date(2026, 10, 22) and b >= date(2026, 10, 20) for a, b in windows(t, far)))
    assert timeline.tasks_during(m, tl.events[0], TODAY) == expected > 0
    assert [b.title for b in timeline.bands(m, date(2026, 10, 23), date(2026, 10, 30))] == ["Installation"]


def test_plan_mode_drags_a_key_date_and_undoes_it(browse):
    """Decision 152: in Plan mode a key date's window moves, or its ends stretch, and a start alone moves; each drop is
    sent as set_key_date and saved, and Ctrl+Z puts it back. A done key date doesn't drag."""
    from docrepo import edits, tasks
    from docrepo.tasks import KeyDateRow

    w = browse
    _key_dates(w.ctx.conn, "T000008", KeyDateRow("2026-10-12", "2026-10-14", "Crane booked"), KeyDateRow("2026-10-05", None, "Planning"),
               KeyDateRow(None, "2026-10-09", "Old", done=True))
    w.refresh()
    view, chart = w.timeline, w.timeline.chart
    sent = []

    def save(task_id, key_id, start, end, said):  # the browse window saves it (set_timeline_key_date); this records what was sent
        sent.append((key_id, start, end, said))

    view.set_key_date.connect(save)
    view.set_open("T000001", True)
    view.set_plan(True)
    QApplication.processEvents()
    ids = [k.id for k in Model(w.ctx.conn).key_dates_of("T000008")]
    top = chart.top_of("T000008")
    row = next(r for r in chart.rows if r.task == "T000008")
    cy = int(chart._key_strip(row, top)[0])
    day = chart.scale.px_per_day(chart)
    # The window's middle, two days later.
    x = int((chart.scale.x(chart, date(2026, 10, 12)) + chart.scale.x(chart, date(2026, 10, 15))) / 2)
    assert chart._hit(x, cy)[1] == "kd-move" and chart.hit_key.id == ids[0]
    QTest.mousePress(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, cy))
    QTest.mouseMove(chart, QPoint(x + 6, cy))
    QTest.mouseMove(chart, QPoint(int(x + 2 * day), cy))
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x + 2 * day), cy))
    kd = Model(w.ctx.conn).key_dates_of("T000008")[0]
    assert (kd.start, kd.end) == ("2026-10-14", "2026-10-16")
    assert sent[-1][3].startswith("Installation: Crane booked now Wed 14 Oct to Fri 16 Oct")
    # The start alone moves a day earlier, and stays a start alone.
    bx = int(chart.scale.x(chart, date(2026, 10, 5)) + 3)
    assert chart._hit(bx, cy)[1] == "kd-move" and chart.hit_key.id == ids[1]
    QTest.mousePress(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(bx, cy))
    QTest.mouseMove(chart, QPoint(bx - 6, cy))
    QTest.mouseMove(chart, QPoint(int(bx - day), cy))
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(bx - day), cy))
    assert [(k.start, k.end) for k in Model(w.ctx.conn).key_dates_of("T000008")][1] == ("2026-10-04", None)
    # The done one doesn't drag.
    ex = int(chart.scale.x(chart, date(2026, 10, 10)) - 3)
    assert chart._hit(ex, cy)[1] not in ("kd-move", "kd-start", "kd-end")
    # Ctrl+Z, twice: both back as they were, through the same signal.
    QTest.keyClick(chart, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(chart, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    kds = Model(w.ctx.conn).key_dates_of("T000008")
    assert [(k.start, k.end) for k in kds[:2]] == [("2026-10-12", "2026-10-14"), ("2026-10-05", None)]
    view._pick("T000008")
    assert "Key dates:" in view.card_text.text() and "Crane booked" in view.card_text.text()
    chart.grab()
    view.head.grab()
