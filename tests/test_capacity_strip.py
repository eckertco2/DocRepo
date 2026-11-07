"""Capacity's half of the Timeline page (release 5.40, ``docrepo.ui.capacity_strip``; a test of its own in release 5.102),
offscreen, over made-up hours: a row per person (under their group's heading when grouped), the team chart's words, a
click on a name or a cell, the keys moving between cells, and that both paint."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolTip  # noqa: E402

from docrepo import load  # noqa: E402
from docrepo.model import Person  # noqa: E402
from docrepo.timeline import Timeline  # noqa: E402
from docrepo.ui.capacity_strip import CapacityRows, CapacityTeam, Spot, StripData  # noqa: E402
from docrepo.ui.timeline_view import _Scale  # noqa: E402

TODAY = date(2026, 10, 8)
START = date(2026, 10, 5)  # a Monday
WEEKS = [START + timedelta(weeks=i) for i in range(6)]
PEOPLE = [Person("P001", "Ann Example", 40, "active", None, group="Mechanical"), Person("P002", "Sam Example", None, "active", None),
          Person("P003", "Kim Example", 20, "active", None, group="Mechanical")]
CELLS = {"P001": {WEEKS[0]: {"T000001": 30.0}, WEEKS[1]: {"T000001": 52.0}}, "P002": {WEEKS[1]: {"T000002": 6.0}},
         "P003": {WEEKS[1]: {"T000002": 10.0}}}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def put_away(widget) -> None:
    """Hide a widget and delete it, with its tooltip, as the wheel's tests do, so nothing is left to take a later
    window's place in front."""
    QToolTip.hideText()
    widget.hide()
    widget.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def scale():
    s = _Scale()
    s.tl = Timeline(START, 6, (), ())
    return s


def data(**kw) -> StripData:
    buckets = load.buckets(START, START + timedelta(weeks=6), 100)
    return StripData(None, TODAY, CELLS, PEOPLE, buckets, **kw)


@pytest.fixture
def rows(qapp, scale):
    w = CapacityRows(scale)
    w.resize(900, 100)
    w.set_data(data())
    w.show()
    yield w
    put_away(w)


def test_a_row_per_person_or_under_their_groups(rows):
    assert [(kind, key) for kind, key, _ in rows.lines] == [("person", "P001"), ("person", "P002"), ("person", "P003")]
    assert rows.height() == rows.natural_height() == 3 * CapacityRows.ROW_H
    rows.set_data(data(by_group=True))
    assert [(kind, key) for kind, key, _ in rows.lines] == [("group", "Mechanical"), ("person", "P001"), ("person", "P003"),
                                                            ("group", "No group"), ("person", "P002")]
    assert rows.line_of("P002") == 4 and rows.line_of("P009") is None


def test_clicking_a_name_or_a_cell(rows, scale):
    solo, picked = [], []
    rows.solo.connect(solo.append)
    rows.picked.connect(lambda who, first, end: picked.append((who, first, end)))
    QTest.mouseClick(rows, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, CapacityRows.ROW_H + 10))
    assert solo == ["P002"]
    week = rows.data.buckets[1]
    cell = rows.cell_rect(0, week).center().toPoint()
    QTest.mouseClick(rows, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cell)
    assert picked == [("P001", week.first, week.end)] and rows.cur == (0, 1)


def test_the_keys_move_between_cells_and_enter_picks(rows):
    picked = []
    rows.picked.connect(lambda who, first, end: picked.append((who, first)))
    rows.set_data(data(by_group=True))
    QTest.keyClick(rows, Qt.Key.Key_Down)
    assert rows.cur == (1, 0)  # the first key lands on this week, on the top person's row (past the group's heading)
    QTest.keyClick(rows, Qt.Key.Key_Right)
    QTest.keyClick(rows, Qt.Key.Key_Down)
    assert rows.cur == (2, 1)
    QTest.keyClick(rows, Qt.Key.Key_Down)
    assert rows.cur == (4, 1)  # past No group's heading
    assert rows.accessibleDescription().startswith("Sam Example, week of ")
    QTest.keyClick(rows, Qt.Key.Key_Return)
    assert picked == [("P002", WEEKS[1])]


def test_the_cells_say_the_load():
    week = load.buckets(START, START + timedelta(weeks=6), 100)[1]
    assert load.tint(52, 40) == "t5" and load.tint(10, 20) == "t2" and load.tint(6, None) == "none"
    assert load.cell_text(52, 40, "pct") == "130%" and load.cell_text(6, None, "pct") == "6"
    assert load.cell_tip(PEOPLE[0], CELLS, week, TODAY) == "Ann Example, week of 12 Oct: 52 h of 40 h, 130%"


def test_the_team_chart(qapp, scale):
    team = CapacityTeam(scale)
    team.resize(900, team.height())
    team.set_data(data(spot=Spot("", WEEKS[1], WEEKS[2])))
    team.show()
    try:
        week = team.data.buckets[1]
        assert team.tip(week) == "Week of 12 Oct: 68 h of 60 h, 12 h over people's own capacity"
        assert team._top() == pytest.approx(68 * 1.08)
        picked = []
        team.picked.connect(lambda who, first, end: picked.append((who, first, end)))
        at = team.column_rect(week).center().toPoint()
        QTest.mouseClick(team, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
        assert picked == [("", week.first, week.end)]
        QTest.mouseClick(team, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(at.x(), 4))
        assert len(picked) == 1  # the small dates above the chart aren't a column
        assert not team.grab().toImage().isNull()
    finally:
        put_away(team)


def test_the_rows_paint_with_a_spotlight_and_a_what_if(rows):
    rows.set_data(data(spot=Spot("P001", WEEKS[1], WEEKS[2]), adds={("P001", WEEKS[1])}, was={"P001": {WEEKS[1]: {"T000001": 40.0}}}))
    image = rows.grab().toImage()
    assert not image.isNull()
    assert len({image.pixel(x, y) for x in range(250, image.width(), 9) for y in range(0, image.height(), 5)}) > 3
