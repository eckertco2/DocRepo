"""The timeline view (mods log round 1, M0019; round 4, M0067, releases 5.29 and 5.30): its rows from the sample data,
and the view in the browse tool, Plan mode's drags included."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

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
