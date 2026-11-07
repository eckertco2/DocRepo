"""Release 5.48 on the Timeline page (the task templates design's Plan mode, decisions 136, 137 and 191): a bar with a Duration keeps
its workdays while it's dragged, an undated task's name takes its own Duration, and the drop says what changed. Driven offscreen."""
from __future__ import annotations

import os
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Tie, load_tasks  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
PRIYA = "P002"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def window(qapp, sample_root, settings: Settings):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, settings, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    w.set_view("timeline")
    w.resize(1500, 950)
    QApplication.processEvents()
    return w, capture


@pytest.fixture
def browse(qapp, sample_root):
    w, capture = window(qapp, sample_root, Settings(me="P001"))
    yield w
    QApplication.processEvents()
    capture.deleteLater()
    w.deleteLater()


def make(browse, **values) -> str:
    values.setdefault("title", "Trial execution window")
    t = tasks.create_task(browse.ctx.conn, browse.ctx.settings, at=NOW, created_by="Test", **values)
    browse.refresh()
    browse.set_view("timeline")
    QApplication.processEvents()
    return t


def saved(browse, task_id: str):
    return load_tasks(browse.ctx.conn, [task_id])[task_id]


def mouse(widget, kind: QEvent.Type, at: QPointF, buttons) -> None:
    QApplication.sendEvent(widget, QMouseEvent(kind, at, widget.mapToGlobal(at), Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))


def drag_to(chart, a: QPointF, b: QPointF) -> None:
    """Press and move, without letting go, so the drag can be looked at."""
    mouse(chart, QEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton)
    for i in range(1, 6):
        mouse(chart, QEvent.Type.MouseMove, a + (b - a) * (i / 5), Qt.MouseButton.LeftButton)


def let_go(chart, at: QPointF) -> None:
    mouse(chart, QEvent.Type.MouseButtonRelease, at, Qt.MouseButton.NoButton)
    QApplication.processEvents()


def bar_of(chart, task_id: str):
    return chart.bar_rect(next(r for r in chart.rows if r.task == task_id), chart.top_of(task_id))


def plan(browse) -> None:
    view = browse.timeline
    if not view.plan:
        QTest.keyClick(view.chart, Qt.Key.Key_P)
    assert view.plan


def test_a_bar_with_a_duration_keeps_its_workdays_while_its_dragged(browse):
    t = make(browse, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_per_day=6)  # Mon to Fri
    plan(browse)
    chart = browse.timeline.chart
    bar = bar_of(chart, t)
    a = bar.center()
    b = a + QPointF(3 * chart.scale.px_per_day(chart), 0)  # three days along: Thursday
    drag_to(chart, a, b)
    assert (chart.drag.start, chart.drag.end) == (date(2026, 11, 5), date(2026, 11, 11))  # across the weekend, wider: Thu to Wed
    assert chart._drag_tip(chart.drag) == "Thu 5 Nov → Wed 11 Nov · 5 workdays"
    let_go(chart, b)
    x = saved(browse, t)
    assert (x.start, x.due, x.duration, x.assignee_hours) == ("2026-11-05", "2026-11-11", 5, 30)  # no more work
    assert "Trial execution window: now Thu 5 Nov to Wed 11 Nov, still 5 workdays. Ctrl+Z undoes it." in browse.status.text()
    day = chart.scale.px_per_day(chart)
    assert bar.width() == pytest.approx(5 * day, abs=1) and bar_of(chart, t).width() == pytest.approx(7 * day, abs=1)  # Thu to Wed, drawn as dragged
    QTest.keyClick(chart, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    x = saved(browse, t)
    assert (x.start, x.due, x.duration) == ("2026-11-02", "2026-11-06", 5)


def test_runs_through_weekends_counts_every_day_while_dragged(browse):
    t = make(browse, start="2026-11-02", duration=5, calendar_days=True)
    plan(browse)
    chart = browse.timeline.chart
    a = bar_of(chart, t).center()
    b = a + QPointF(3 * chart.scale.px_per_day(chart), 0)
    drag_to(chart, a, b)
    assert (chart.drag.start, chart.drag.end) == (date(2026, 11, 5), date(2026, 11, 9))
    assert chart._drag_tip(chart.drag) == "Thu 5 Nov → Mon 9 Nov · 5 days"
    let_go(chart, b)
    assert "still 5 days" in browse.status.text()


def test_stretching_an_end_says_the_new_duration_and_total(browse):
    t = make(browse, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_per_day=6)
    plan(browse)
    chart = browse.timeline.chart
    bar = bar_of(chart, t)
    a = QPointF(bar.right() - 2, bar.center().y())
    b = a - QPointF(2 * chart.scale.px_per_day(chart), 0)
    drag_to(chart, a, b)
    assert (chart.drag.start, chart.drag.end) == (date(2026, 11, 2), date(2026, 11, 4))  # the end follows the pointer
    assert chart._drag_tip(chart.drag) == "Mon 2 Nov → Wed 4 Nov · 3 workdays · Duration 5 → 3 workdays · assignee hours 30 → 18"
    let_go(chart, b)
    x = saved(browse, t)
    assert (x.due, x.duration, x.assignee_hours) == ("2026-11-04", 3, 18)
    assert "Due moved to Wed 4 Nov, Duration 5 → 3 workdays, assignee hours 30 → 18. Ctrl+Z undoes it." in browse.status.text()


def test_an_undated_tasks_name_takes_its_own_duration(browse):
    t = make(browse, duration=3)
    plan(browse)
    view, chart = browse.timeline, browse.timeline.chart
    if t not in [r.task for r in chart.rows]:
        view.undated_fold.click()
        QApplication.processEvents()
    row = next(r for r in chart.rows if r.task == t and r.undated)
    grip = chart._grip_rect(row, chart.top_of(t)).center()
    target = QPointF(chart.scale.x(chart, date(2026, 11, 7)) + 2, grip.y())  # a Saturday: counting starts on Monday
    drag_to(chart, grip, target)
    assert (chart.drag.start, chart.drag.end) == (date(2026, 11, 9), date(2026, 11, 11))
    let_go(chart, target)
    x = saved(browse, t)
    assert (x.start, x.due, x.duration) == ("2026-11-09", "2026-11-11", 3)
    assert "Start and Due set: Mon 9 Nov to Wed 11 Nov, its own 3 workdays." in browse.status.text()


def test_a_name_with_no_duration_still_gets_a_working_week(browse):
    t = make(browse)
    plan(browse)
    view, chart = browse.timeline, browse.timeline.chart
    if t not in [r.task for r in chart.rows]:
        view.undated_fold.click()
        QApplication.processEvents()
    row = next(r for r in chart.rows if r.task == t and r.undated)
    grip = chart._grip_rect(row, chart.top_of(t)).center()
    target = QPointF(chart.scale.x(chart, date(2026, 11, 4)) + 2, grip.y())
    drag_to(chart, grip, target)
    assert (chart.drag.start, chart.drag.end) == (date(2026, 11, 4), date(2026, 11, 10))
    let_go(chart, target)
    assert (saved(browse, t).start, saved(browse, t).due) == ("2026-11-04", "2026-11-10")


def test_the_workdays_in_settings_reach_the_chart(qapp, sample_root):
    """A four-day week, Monday to Thursday: a 5-day bar moved to Thursday runs to the next Thursday while it's dragged."""
    w, capture = window(qapp, sample_root, Settings(me="P001", workdays=["Mon", "Tue", "Wed", "Thu"]))
    try:
        t = make(w, start="2026-11-02", duration=5)
        plan(w)
        chart = w.timeline.chart
        assert chart.workdays == w._workdays() == frozenset(range(4))
        a = bar_of(chart, t).center()
        b = a + QPointF(3 * chart.scale.px_per_day(chart), 0)
        drag_to(chart, a, b)
        assert (chart.drag.start, chart.drag.end) == (date(2026, 11, 5), date(2026, 11, 12))
        let_go(chart, b)
        assert (saved(w, t).start, saved(w, t).due) == ("2026-11-05", "2026-11-12")
        # An undated task's name let go on a Friday starts on the Monday, the next workday.
        u = make(w, duration=2)
        plan(w)
        if u not in [r.task for r in chart.rows]:
            w.timeline.undated_fold.click()
            QApplication.processEvents()
        row = next(r for r in chart.rows if r.task == u and r.undated)
        grip = chart._grip_rect(row, chart.top_of(u)).center()
        target = QPointF(chart.scale.x(chart, date(2026, 11, 13)) + 2, grip.y())
        drag_to(chart, grip, target)
        assert (chart.drag.start, chart.drag.end) == (date(2026, 11, 16), date(2026, 11, 17))
        let_go(chart, target)
        assert (saved(w, u).start, saved(w, u).due) == ("2026-11-16", "2026-11-17")
    finally:
        QApplication.processEvents()
        capture.deleteLater()
        w.deleteLater()


def test_in_a_what_if_the_drop_says_the_same_and_no_task_changes(browse):
    t = make(browse, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_per_day=6)
    view = browse.timeline
    view._new_whatif("Shorter")
    QApplication.processEvents()
    chart = view.chart
    bar = bar_of(chart, t)
    a = QPointF(bar.right() - 2, bar.center().y())
    b = a - QPointF(2 * chart.scale.px_per_day(chart), 0)
    drag_to(chart, a, b)
    let_go(chart, b)
    assert saved(browse, t).due == "2026-11-06"  # nothing changed
    assert view.model.task(t).due == "2026-11-04" and view.model.task(t).assignee_hours == 18
    assert ("Trial execution window: Due moved to Wed 4 Nov, Duration 5 → 3 workdays, assignee hours 30 → 18, in this what-if. "
            "Your tasks haven't changed.") in browse.status.text()


# ---- ties on the chart (decision 259) ----
def trial(browse) -> tuple[str, str, str, str]:
    """A trial with three steps in one tree, so a move asks nothing: set up the line (Mon 2 to Fri 6 Nov), run it the workday after
    (3 workdays), and write the report 2 workdays after that, with two plain dates."""
    top = make(browse, title="Trial 7")
    conn = browse.ctx.conn
    a = tasks.create_task(conn, browse.ctx.settings, title="Set up the line", parents=[top], start="2026-11-02", duration=5, at=NOW, created_by="Test")
    b = tasks.create_task(conn, browse.ctx.settings, title="Run the trial", parents=[top], start="2026-11-09", duration=3, at=NOW, created_by="Test")
    c = tasks.create_task(conn, browse.ctx.settings, title="Write the report", parents=[top], start="2026-11-16", due="2026-11-18", at=NOW, created_by="Test")
    tasks.update_task(conn, browse.ctx.settings, b, at=NOW, via="Test", ties={"start": Tie(a, amount=1)})
    tasks.update_task(conn, browse.ctx.settings, c, at=NOW, via="Test", ties={"start": Tie(b, amount=2)})
    browse.refresh()
    browse.set_view("timeline")
    browse.timeline.set_open(top, True)
    QApplication.processEvents()
    return top, a, b, c


def at(chart, task_id: str, day: date) -> tuple[float, float]:
    return (round(chart.scale.x(chart, day), 1), round(chart.top_of(task_id) + chart.ROW_H / 2, 1))


def ends(lines) -> list[tuple]:
    return [((round(a.x(), 1), round(a.y(), 1)), (round(b.x(), 1), round(b.y(), 1))) for a, b in lines]


def test_a_selected_bar_draws_lines_to_its_ties_and_nothing_otherwise(browse):
    top, a, b, c = trial(browse)
    view, chart = browse.timeline, browse.timeline.chart
    view._pick(None)
    assert chart.tie_lines() == []
    view._pick(top)
    assert chart.tie_lines() == []  # the trial itself has no ties
    view._pick(b)
    a_ends, b_starts = at(chart, a, date(2026, 11, 7)), at(chart, b, date(2026, 11, 9))  # Fri 6 Nov's right edge, Mon 9 Nov's left
    b_ends, c_starts = at(chart, b, date(2026, 11, 12)), at(chart, c, date(2026, 11, 13))
    assert ends(chart.tie_lines()) == [(a_ends, b_starts), (b_ends, c_starts)]  # what it's tied to, and what's tied to it
    view._pick(a)
    assert ends(chart.tie_lines()) == [(a_ends, b_starts)]
    assert not chart.grab().isNull()  # painted, lines and all
    view.set_open(top, False)
    QApplication.processEvents()
    view._pick(top)
    assert chart.tie_lines() == []  # their rows are folded away


def test_a_key_dates_line_starts_on_the_key_dates_strip(browse):
    from docrepo.tasks import KeyDateRow

    outage = make(browse, title="Line 2 outage", start="2026-11-02", due="2026-11-20")
    conn = browse.ctx.conn
    tasks.set_key_dates(conn, outage, [KeyDateRow("2026-11-09", "2026-11-13", "Shutdown")], at=NOW, via="Test")
    key_id = browse.model().key_dates_of(outage)[0].id
    checks = make(browse, title="Restart checks", start="2026-11-16", duration=2)
    tasks.update_task(conn, browse.ctx.settings, checks, at=NOW, via="Test", ties={"start": Tie(outage, amount=1, key_date=key_id)})
    browse.refresh()
    QApplication.processEvents()
    view, chart = browse.timeline, browse.timeline.chart
    view._pick(checks)
    row = next(r for r in chart.rows if r.task == outage)
    strip = chart._key_strip(row, chart.top_of(outage))[0]
    assert ends(chart.tie_lines()) == [((round(chart.scale.x(chart, date(2026, 11, 14)), 1), round(strip, 1)), at(chart, checks, date(2026, 11, 16)))]


def test_dragging_a_source_shows_what_follows_it_where_the_save_puts_it(browse):
    top, a, b, c = trial(browse)
    plan(browse)
    chart = browse.timeline.chart
    start = bar_of(chart, a).center()
    week = QPointF(7 * chart.scale.px_per_day(chart), 0)
    drag_to(chart, start, start + week)
    shown = {x: (t.start, t.due) for x, t in chart.preview.items()}
    assert shown == {b: ("2026-11-16", "2026-11-18"), c: ("2026-11-20", "2026-11-24")}
    assert chart._drag_tip(chart.drag).endswith("· 2 tasks tied to it move with it")
    b_starts = at(chart, b, date(2026, 11, 16))
    assert (at(chart, a, date(2026, 11, 14)), b_starts) in ends(chart.tie_lines())  # the line goes where they'll be
    assert not chart.grab().isNull()
    let_go(chart, start + week)
    assert {x: (saved(browse, x).start, saved(browse, x).due) for x in (b, c)} == shown
    assert chart.preview == {} and chart.moved == {}
    assert "Moved 2 tasks with it." in browse.status.text()


def test_in_a_what_if_a_drag_shows_what_follows_it_too(browse):
    top, a, b, c = trial(browse)
    view = browse.timeline
    view._new_whatif("Later")
    QApplication.processEvents()
    chart = view.chart
    bar = bar_of(chart, a)
    end = QPointF(bar.right() - 2, bar.center().y())
    target = end - QPointF(2 * chart.scale.px_per_day(chart), 0)  # ends Wednesday
    drag_to(chart, end, target)
    shown = {x: (t.start, t.due) for x, t in chart.preview.items()}
    assert shown == {b: ("2026-11-05", "2026-11-09"), c: ("2026-11-11", "2026-11-13")}
    let_go(chart, target)
    assert {x: (view.model.task(x).start, view.model.task(x).due) for x in (b, c)} == shown  # the what-if's own picture agrees
    assert saved(browse, b).start == "2026-11-09"  # and no task changed
