"""The # list's marks (release 5.75, round 7's item 92, decisions 327 to 330): a top-level task's dot and Semibold name, a
ring in its top-level task's colour for the rest, how many open subtasks before the chevron, the chevron's backplate under
the pointer, and a level's header row with its subtasks indented. Offscreen, over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import _HEAD, _OPTION, task_colour  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
REACTOR, INSTALLATION, OVERTIME = "T000001", "T000008", "T000015"  # Q4 overtime budget is under Installation and Q4 cost reduction


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    w = CaptureWindow(AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW))
    w.resize(900, 700)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w._items_timer.stop()
    w.hide()
    w.deleteLater()
    conn.close()


def typed(w: CaptureWindow, text: str):
    w.content.setFocus()
    QApplication.processEvents()
    w.content.insertPlainText(text)
    return w.ref_popup


def row(popup, i: int):
    item = popup.item(i)
    o, head = item.data(_OPTION), bool(item.data(_HEAD))
    return o, head, popup.delegate.parts(o, head)


def test_top_level_tasks_have_a_dot_and_a_semibold_name(window):
    popup = typed(window, "#")
    m = window.ctx.model()
    o, head, (mark, kid, sub, right) = row(popup, 0)
    assert o.ref == REACTOR and mark == (True, task_colour(m, REACTOR)) and not kid
    assert sub == "" and "Top-level task" in popup.item(0).toolTip()  # the words go to its tooltip (decision 327)
    assert popup.delegate.name_font(o, head).bold() and right == "3"  # three open subtasks (decision 329)
    assert "3 open subtasks" in popup.item(0).text() and "3 open subtasks" in popup.item(0).toolTip()


def test_other_tasks_have_a_ring_in_their_top_level_tasks_colour(window):
    popup = typed(window, "#rigging")
    m = window.ctx.model()
    o, head, (mark, kid, sub, right) = row(popup, 0)
    assert o.label == "Rigging plan" and mark == (False, task_colour(m, REACTOR))  # decision 328
    assert sub == "Reactor impeller upgrade › Installation" and right == ""
    assert not popup.delegate.name_font(o, head).bold()


def test_a_level_has_a_header_and_its_subtasks_indented(window):
    popup = typed(window, "#")
    popup.go_into(0)
    o, head, (mark, kid, sub, right) = row(popup, 0)
    assert head and o.ref == REACTOR and right == "3 open subtasks" and popup.delegate.name_font(o, head).bold()  # decision 330
    o, head, (mark, kid, sub, right) = row(popup, 1)
    assert o.label == "Installation" and kid and sub == "" and mark == (False, task_colour(window.ctx.model(), REACTOR))
    assert right == "3"  # kid: drawn 16 px in, the task tree's indent


def test_inside_a_level_a_task_with_two_parents_takes_the_colour_its_listed_under(window):
    popup = typed(window, "#")
    m = window.ctx.model()
    popup.go_into(0)  # Reactor impeller upgrade
    popup.go_into(1)  # Installation
    labels = [popup.item(i).data(_OPTION).label for i in range(popup.count())]
    i = labels.index("Q4 overtime budget")
    o, head, (mark, kid, sub, right) = row(popup, i)
    assert o.ref == OVERTIME and mark == (False, task_colour(m, REACTOR))
    popup.go_up()
    popup.go_up()
    assert popup.depth == 0 and popup.mark(popup.item(0).data(_OPTION))[1] == task_colour(m, REACTOR)


def test_people_have_no_mark(window):
    popup = typed(window, "@to")
    o, head, (mark, kid, sub, right) = row(popup, 0)
    assert mark is None and right == "" and not kid


def _move(popup, i: int, x: float, kind=QEvent.Type.MouseMove) -> None:
    rect = popup.visualItemRect(popup.item(i))
    at = QPointF(x, rect.center().y())
    glob = QPointF(popup.viewport().mapToGlobal(at.toPoint()))
    QApplication.sendEvent(popup.viewport(), QMouseEvent(kind, at, glob, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                                          Qt.KeyboardModifier.NoModifier))


def test_the_chevron_under_the_pointer_has_a_backplate(window):
    popup = typed(window, "#")
    _move(popup, 1, popup.viewport().width() - 10)
    assert popup.hot == (1, "into") and popup.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor
    _move(popup, 1, 40)
    assert popup.hot is None
    _move(popup, 4, popup.viewport().width() - 10)  # Line 2 extruder screw replacement: nothing to go into
    assert popup.hot is None
    popup.go_into(0)
    _move(popup, 0, 6)
    assert popup.hot == (0, "back")
    QApplication.sendEvent(popup, QEvent(QEvent.Type.Leave))
    assert popup.hot is None
