"""The @ and # list (release 5.65, round 6's items 85 and 86, decisions 310 to 313): whole rows, never a sideways scroll
bar, and Right into a task's subtasks, in the full capture window and the pinned window. Offscreen, over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, items, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import _HEAD, _OPTION, REF_MAX_W, REF_MIN_W, REF_ROWS  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


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
    ctx = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW)
    w = CaptureWindow(ctx)
    w.resize(900, 700)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w._items_timer.stop()  # a reading left waiting would run after the database is closed
    w.hide()
    if w.pin_window is not None:
        w.pin_window.hide()
        w.pin_window.deleteLater()
    w.deleteLater()
    conn.close()


def typed(window, text: str, pinned: bool = False):
    """Type ``text`` at the end of the box the list follows, and give back the box and its list."""
    if pinned:
        window.pin()
        box, popup = window.pin_window.text, window.pin_window.ref_popup
        window.pin_window.activateWindow()
    else:
        box, popup = window.content, window.ref_popup
    box.setFocus()
    QApplication.processEvents()
    box.insertPlainText(text)
    return box, popup


def rows(popup) -> list[tuple[str, bool]]:
    return [(popup.item(i).data(_OPTION).label, bool(popup.item(i).data(_HEAD))) for i in range(popup.count())]


@pytest.mark.parametrize("pinned", [False, True])
def test_a_lone_row_is_whole(window, pinned):
    """The bug in the memo of 2026-11-03: one result, wider than the list, put a scroll bar over its own row."""
    box, popup = typed(window, "#book the al", pinned)
    assert rows(popup) == [("Book the alignment contractor", False)]
    QApplication.processEvents()
    assert not popup.horizontalScrollBar().isVisible()
    assert popup.viewport().height() >= popup.delegate.row_height()
    assert popup.visualItemRect(popup.item(0)).bottom() < popup.viewport().height()
    # Its row with its path is wider than 320 px, so the list widens, up to 480 px.
    natural = popup.delegate.natural_width(popup.item(0).data(_OPTION), False)
    assert popup.width() == max(REF_MIN_W, min(natural + 2 * popup.frameWidth(), REF_MAX_W))
    assert "Reactor impeller upgrade › Installation" in popup.item(0).toolTip()


def test_the_list_is_one_row_tall_per_row_up_to_eight(window):
    box, popup = typed(window, "#")
    assert popup.count() > 0
    QApplication.processEvents()
    shown = min(REF_ROWS, popup.count())
    assert popup.viewport().height() == shown * popup.delegate.row_height()
    assert not popup.horizontalScrollBar().isVisible()


def test_hash_alone_lists_the_top_level_tasks_in_the_trees_order(window):
    """Decision 313: so the tree can be walked from the top with Right. Closed ones are left out."""
    box, popup = typed(window, "#")
    m = window.ctx.model()
    want = [t.title for t in m.top_level() if t.state != "Closed" and not t.discarded]
    assert [label for label, _ in rows(popup)] == want
    assert "Cooling tower fan gearbox" not in want  # closed


def test_items_options_for_hash_alone():
    """Without a Model the old list stands, so nothing that reads names without one changes."""
    names = items.Names([], [items.RefTask("T1", "Pump seal"), items.RefTask("T2", "Valve", open=False)])
    assert [o.ref for o in items.options(items.typing("#"), names)] == ["T1"]


@pytest.mark.parametrize("pinned", [False, True])
def test_right_goes_into_a_tasks_subtasks_and_left_comes_back(window, pinned):
    box, popup = typed(window, "#reac", pinned)
    assert rows(popup)[0] == ("Reactor impeller upgrade", False) and popup.opens(popup.item(0).data(_OPTION))
    assert box.list_keys(Qt.Key.Key_Right)
    # The task itself first, then its open subtasks in the tree's order (the closed seal order is left out).
    assert rows(popup) == [("Reactor impeller upgrade", True), ("Installation", False), ("Vendor drawing package", False),
                           ("Draft monitoring plan", False)]
    assert popup.currentRow() == 1 and popup.depth == 1
    assert box.toPlainText().endswith("#reac")  # the text doesn't change until a pick
    assert box.list_keys(Qt.Key.Key_Right)  # Installation has its own
    assert rows(popup)[0] == ("Installation", True) and popup.depth == 2
    # A level's rows have no grey path of their own; the tooltip has it.
    assert popup.item(1).data(_OPTION).sub == "" and popup.item(1).toolTip() == "Rigging plan\nReactor impeller upgrade › Installation"
    assert box.list_keys(Qt.Key.Key_Left)
    assert popup.depth == 1 and popup.currentItem().data(_OPTION).label == "Installation"
    assert box.list_keys(Qt.Key.Key_Left)
    assert popup.depth == 0 and popup.currentItem().data(_OPTION).label == "Reactor impeller upgrade"
    assert not box.list_keys(Qt.Key.Key_Left)  # at the top, Left moves the cursor (decision 312)


@pytest.mark.parametrize("pinned", [False, True])
def test_picking_a_subtask_puts_it_in_with_its_id(window, pinned):
    box, popup = typed(window, "Crane booked. #reac", pinned)
    box.list_keys(Qt.Key.Key_Right)
    box.list_keys(Qt.Key.Key_Right)  # into Installation, on its first subtask
    assert popup.currentItem().data(_OPTION).label == "Rigging plan"
    box.list_keys(Qt.Key.Key_Down)
    assert popup.currentItem().data(_OPTION).label == "Q4 overtime budget"
    assert box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "Crane booked. #Q4 overtime budget " and not popup.isVisible()
    assert window.ref_ids["#q4 overtime budget"] == "T000015"


def test_enter_on_the_first_row_picks_the_task_itself(window):
    box, popup = typed(window, "#reac")
    box.list_keys(Qt.Key.Key_Right)
    box.list_keys(Qt.Key.Key_Up)
    assert popup.currentRow() == 0
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "#Reactor impeller upgrade "


def test_right_on_a_task_with_no_open_subtasks_moves_the_cursor(window):
    box, popup = typed(window, "#rigg")
    assert rows(popup) == [("Rigging plan", False)] and not popup.opens(popup.item(0).data(_OPTION))
    assert not box.list_keys(Qt.Key.Key_Right)  # the text box takes it, as before (decision 312)


def test_typing_goes_back_to_the_search(window):
    box, popup = typed(window, "#reac")
    box.list_keys(Qt.Key.Key_Right)
    assert popup.depth == 1
    box.insertPlainText("t")
    assert popup.depth == 0 and rows(popup)[0] == ("Reactor impeller upgrade", False)


def test_the_at_list_has_no_levels(window):
    box, popup = typed(window, "@ty")
    assert popup.subtasks is None and not box.list_keys(Qt.Key.Key_Right)
    assert rows(popup)[0][0] == "Tyler Nguyen"


def _click(popup, row: int, x: int) -> None:
    rect = popup.visualItemRect(popup.item(row))
    at = QPointF(x, rect.center().y())
    glob = QPointF(popup.viewport().mapToGlobal(at.toPoint()))
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(popup.viewport(), QMouseEvent(kind, at, glob, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                                              Qt.KeyboardModifier.NoModifier))


def test_the_chevrons_click(window):
    box, popup = typed(window, "#reac")
    _click(popup, 0, popup.viewport().width() - 8)  # the chevron goes in
    assert popup.depth == 1 and popup.isVisible() and box.toPlainText() == "#reac"
    _click(popup, 0, 6)  # the back chevron comes up
    assert popup.depth == 0 and popup.isVisible()
    _click(popup, 0, 40)  # anywhere else picks
    assert box.toPlainText() == "#Reactor impeller upgrade "


def test_a_level_longer_than_eight_rows_scrolls_down_not_across(window):
    box, popup = typed(window, "#reac")
    popup.subtasks = lambda ref: [items.Option(f"Step {i}", f"Step {i}", "Reactor impeller upgrade", ref=f"X{i}") for i in range(12)]
    popup._opens = {}
    box.list_keys(Qt.Key.Key_Right)
    QApplication.processEvents()
    assert popup.count() == 13 and popup.viewport().height() == REF_ROWS * popup.delegate.row_height()
    assert not popup.horizontalScrollBar().isVisible()


def test_the_list_stays_inside_the_window(window):
    """The full window's list moves left to stay inside the window, and above the cursor when it can't fit under it."""
    box, popup = typed(window, "#book the al")
    assert popup.geometry().right() <= window.width() - 4 and popup.geometry().left() >= 4
    assert popup.geometry().bottom() <= window.height() - 4
