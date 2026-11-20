"""Today's drop targets as a rule (release 5.189, the redesign's decision 864, keeping decision 822's urgent part):
``today_bins.target_at`` over made-up groups. No window."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect

from docrepo.model import TODAY_BANDS
from docrepo.ui.today_bins import chip_rect, insert_at, make_group, target_at

WIDTH = 300


def group(band: str, top: int, urgent: int, rest: int):
    """A band at ``top``: a 26 px head, then ``urgent`` and ``rest`` rows of 30 px."""
    head = QRect(6, top, WIDTH, 26 if urgent + rest else 30)
    y = head.bottom() + 1
    u = [QRect(6, y + 30 * n, WIDTH, 30) for n in range(urgent)]
    y += 30 * urgent
    r = [QRect(6, y + 30 * n, WIDTH, 30) for n in range(rest)]
    return make_group(band, head, chip_rect(head), u, r, urgent + rest)


def layout():
    """Critical empty, High with one urgent and one rest row, Medium with two rest rows, Not ranked empty, Parking lot one."""
    out, top = [], 0
    for band, urgent, rest in (("critical", 0, 0), ("high", 1, 1), ("medium", 0, 2), ("", 0, 0), ("parking", 0, 1)):
        g = group(band, top, urgent, rest)
        out.append(g)
        top = g.whole.bottom() + 8
    return {g.band: g for g in out}


def middle(r: QRect) -> QPoint:
    return r.center()


def head_left(g) -> QPoint:
    return QPoint(g.head.left() + 20, g.head.center().y())


def test_away_from_every_group_is_nothing():
    g = layout()
    assert target_at(list(g.values()), "medium", False, QPoint(5000, 5000)) is False


def test_another_bands_head_chip_and_halves():
    g = layout()
    groups = list(g.values())
    high = g["high"]
    assert target_at(groups, "medium", False, head_left(high)) == ("high", False)
    assert target_at(groups, "medium", False, middle(high.chip)) == ("high", True)
    assert target_at(groups, "medium", False, middle(high.urgent_rows)) == ("high", True)
    assert target_at(groups, "medium", False, middle(high.rest_rows)) == ("high", False)


def test_the_own_band():
    g = layout()
    groups = list(g.values())
    high = g["high"]
    # Dragging High's rest row: its own half reorders, the urgent half and the chip tick Urgent, the head is nothing.
    assert target_at(groups, "high", False, middle(high.rest_rows)) is False
    assert target_at(groups, "high", False, middle(high.urgent_rows)) == ("high", True)
    assert target_at(groups, "high", False, middle(high.chip)) == ("high", True)
    assert target_at(groups, "high", False, head_left(high)) is None
    # Dragging High's urgent row: its own half reorders, the rest and the head untick it, the chip is nothing.
    assert target_at(groups, "high", True, middle(high.urgent_rows)) is False
    assert target_at(groups, "high", True, middle(high.rest_rows)) == ("high", False)
    assert target_at(groups, "high", True, head_left(high)) == ("high", False)
    assert target_at(groups, "high", True, middle(high.chip)) is None


def test_an_empty_bands_head_and_chip_are_its_two_targets():
    g = layout()
    groups = list(g.values())
    critical = g["critical"]
    assert critical.urgent_rows.isNull() and critical.rest_rows.isNull()
    assert target_at(groups, "medium", False, head_left(critical)) == ("critical", False)
    assert target_at(groups, "medium", False, middle(critical.chip)) == ("critical", True)


def test_five_bands_give_ten_targets_less_the_dragged_tasks_own():
    g = layout()
    groups = list(g.values())
    found = set()
    for grp in groups:
        for point in (head_left(grp), middle(grp.chip)):
            hit = target_at(groups, "medium", False, point)
            if isinstance(hit, tuple):
                found.add(hit)
    every = {(b, u) for b in TODAY_BANDS for u in (True, False)}
    assert found == every - {("medium", False)}


def test_the_insert_line_is_at_the_foot_of_the_target_half():
    g = layout()
    high, critical, medium = g["high"], g["critical"], g["medium"]
    assert insert_at(high, True) == high.urgent_rows.bottom() + 1  # between the urgent rows and the rest
    assert insert_at(high, False) == high.rest_rows.bottom() + 1
    assert insert_at(critical, True) == insert_at(critical, False) == critical.head.bottom() + 1  # under an empty head
    assert insert_at(medium, True) == medium.head.bottom() + 1  # an empty urgent half: under the head
