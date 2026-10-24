"""The timeline view (mods log round 1, M0019): its rows from the sample data, and the view in the browse tool."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import people, tasks, timeline  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

TODAY = date(2026, 10, 8)  # a Thursday


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def rows(tl: timeline.Timeline) -> list[tuple[str, list[str]]]:
    return [(g.name, [("  " * r.depth) + r.task + (" ctx" if r.ctx else "") for r in g.rows]) for g in tl.groups]


def test_the_range_and_its_scale():
    start = timeline.default_start(TODAY)
    tl = timeline.Timeline(start, 9, (), ())
    assert (start, tl.end, tl.days) == (date(2026, 9, 28), date(2026, 11, 30), 63)
    assert tl.months() == [date(2026, 10, 1), date(2026, 11, 1)]  # September has only three days in view, so it's not named
    assert tl.week_starts()[:3] == [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)]
    long = timeline.Timeline(date(2026, 9, 7), 26, (), ())
    assert long.months()[0] == date(2026, 9, 7) and len(long.week_starts()) == 7  # every fourth week
    assert (timeline.step(9), timeline.step(26)) == (4, 13)


def test_grouped_by_top_level_task(sample_conn):
    m = Model(sample_conn)
    tl = timeline.build(m, TODAY, timeline.default_start(TODAY), 9)
    # The tree's shape; parked and closed tasks are left out, and so are tasks with no dates, named below instead.
    assert rows(tl) == [
        ("Reactor impeller upgrade", ["T000001", "  T000008", "    T000012", "    T000019", "  T000009", "  T000011"]),
        ("Verification walkthrough readiness", ["T000002", "  T000017", "  T000018"]),
        ("Monthly safety report", ["T000006"]),
        ("Business team meeting", ["T000010"]),
    ]
    assert tl.undated == ("T000015", "T000016")
    by_id = {r.task: r for g in tl.groups for r in g.rows}
    assert by_id["T000008"].windows == ((date(2026, 10, 19), date(2026, 10, 30)),) and by_id["T000008"].deadline == date(2026, 10, 30)
    assert by_id["T000019"].not_started and by_id["T000019"].deadline == date(2026, 10, 19)
    assert len(by_id["T000010"].windows) == 8 and by_id["T000010"].routine  # weekly, one dot each
    assert by_id["T000006"].windows[0] == (date(2026, 9, 26), date(2026, 9, 30))  # a routine window that spans days
    assert [g.colour for g in tl.groups] == [0, 1, 5, 6]  # each top-level task's place, so the tree's colours in turn
    assert not any(r.late for r in by_id.values())
    later = timeline.build(m, date(2026, 10, 20), timeline.default_start(date(2026, 10, 20)), 9)
    assert [r.task for g in later.groups for r in g.rows if r.late] == ["T000012", "T000019", "T000017"]  # due 14, 9 and 16 Oct, still open
    assert "Lead: Me\nAssignees: Tom Becker, Mike Ortiz" in timeline.tooltip(m, "T000008", TODAY)


def test_plant_events_are_bands_and_name_the_dates_in_them(sample_conn):
    """Release 5.9 (M0028): a plant event is shaded down the whole chart, whatever the filters, and a date inside one
    is named under the dates where they're picked."""
    event = tasks.create_task(sample_conn, Settings(me="P001"), title="Spring outage", at=datetime(2026, 10, 8, 9, 0), created_by="Excel import",
                              start="2026-11-03", due="2026-11-14", plant_event=True)
    m = Model(sample_conn)
    tl = timeline.build(m, TODAY, timeline.default_start(TODAY), 9, labels=("Safety",))
    assert tl.events == (timeline.Band(event, "Spring outage", date(2026, 11, 3), date(2026, 11, 14)),)
    assert timeline.bands(m, date(2026, 9, 28), date(2026, 11, 3)) == ()
    tasks.update_task(sample_conn, Settings(me="P001"), event, at=datetime(2026, 10, 8, 9, 0), via="Browse tool", recurrence="Monthly")
    assert [b.start for b in timeline.bands(Model(sample_conn), date(2026, 11, 1), date(2027, 1, 1))] == [date(2026, 11, 3), date(2026, 12, 3)]
    assert timeline.during(m, date(2026, 11, 14)).task == event and timeline.during(m, date(2026, 11, 15)) is None
    assert timeline.during(m, date(2026, 11, 5), event) is None  # its own dates don't count
    assert (timeline.during_text(m, [("Start", "2026-10-30"), ("Due", "2026-11-06"), ("Deadline", "not a date")], TODAY)
            == "Due falls during Spring outage, Tue 3 Nov to Sat 14 Nov.")


def test_grouped_by_group_or_by_a_parent_label(sample_conn):
    """Release 5.9: by the people's groups (M0033), or under each sublabel of a parent label (M0051)."""
    people.add_label(sample_conn, "Production line")
    for name in ("Line 1", "Line 2"):
        people.update_label(sample_conn, name, parent="Production line")
    m = Model(sample_conn)
    assert timeline.group_choices(m)[3:] == [("group", "group"), ("parent:Production line", "Production line")]
    start = timeline.default_start(TODAY)
    by_group = timeline.build(m, TODAY, start, 9, "group", people=("P005",))
    assert rows(by_group) == [("Engineering", ["T000019"]), ("Purchasing", ["T000019"])]  # under each of its people's groups
    assert [g.name for g in timeline.build(m, TODAY, start, 9, "group").groups] == ["Engineering", "Maintenance", "Purchasing", "No group"]
    lines = timeline.build(m, TODAY, start, 9, "parent:Production line")
    assert [g.name for g in lines.groups] == ["Line 1", "No production line"]
    assert rows(timeline.build(m, TODAY, start, 9, "parent:Production line", labels=("Line 1",)))[0][1][:2] == ["T000001", "T000009"]


def test_grouped_by_label_or_person_and_filtered(sample_conn):
    m = Model(sample_conn)
    start = timeline.default_start(TODAY)
    safety = timeline.build(m, TODAY, start, 9, "label", labels=("Safety",))
    assert rows(safety) == [("Safety", ["T000006", "T000002", "T000017", "T000018", "T000019"])]  # soonest first, inherited labels too
    by_person = timeline.build(m, TODAY, start, 9, "person", people=("P005",))
    assert rows(by_person) == [("Tyler Nguyen", ["T000019"])]
    no_routine = timeline.build(m, TODAY, start, 9, routine=False)
    assert "Business team meeting" not in [g.name for g in no_routine.groups]
    filtered = timeline.build(m, TODAY, start, 9, people=("P002",))  # Priya: the vendor drawings and the monitoring plan
    assert rows(filtered) == [("Reactor impeller upgrade", ["T000001 ctx", "  T000009", "  T000011"]), ("Business team meeting", ["T000010"])]


def test_the_view_in_the_browse_tool(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: datetime(2026, 10, 8, 14, 10))
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    try:
        w.set_view("timeline")
        assert w.middle.currentWidget() is w.timeline and not w.detail.isVisible()
        chart = w.timeline.chart
        chart.resize(1000, chart.minimumHeight())
        top, row = next((y, r) for y, r in chart.items if isinstance(r, timeline.Row) and r.task == "T000008")
        click = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(40, top + 5), QPointF(40, top + 5), Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        chart.mousePressEvent(click)
        assert w.timeline.sel == "T000008" and "Installation" in w.timeline.card_text.text() and w.view == "timeline"
        assert "Lead: Me 8 h" in w.timeline.card_text.text()
        w.timeline.shift(1)
        assert w.timeline.start == date(2026, 10, 26)
        w.timeline.shift(0)
        assert w.timeline.start == date(2026, 9, 28)
        chart.grab()  # paints without errors
        chart.mousePressEvent(click)  # a second click opens it
        assert (w.view, w.sel) == ("tasks", ("task", "T000008"))
    finally:
        capture.deleteLater()
        w.deleteLater()
