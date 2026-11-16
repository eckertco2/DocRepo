"""The ``**label,`` and ``**agenda,`` lists in the capture window and the pinned window (release 5.144, decisions 620 to
625): the @ and # list, opened by the words after the operator's comma, with its keys, levels and picks. Offscreen, over
the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import _HEAD, _OPTION  # noqa: E402

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


def names(popup) -> list[str]:
    return [popup.item(i).data(_OPTION).label for i in range(popup.count())]


@pytest.mark.parametrize("pinned", [False, True])
def test_the_label_comma_opens_the_list_and_enter_picks(window, pinned):
    box, popup = typed(window, "- @Mike fit the guard rail **label, ", pinned)
    assert popup.isVisible() and names(popup) == ["Line 1", "Line 2", "Strategic Plan", "Safety", "Profitability"]
    assert popup.subtasks is None and popup.task_info is None  # labels have no levels and no marks
    box.insertPlainText("saf")
    assert names(popup) == ["Safety", "Create label “saf”"] and popup.currentRow() == 0
    assert box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "- @Mike fit the guard rail **label, Safety " and not popup.isVisible()


def test_tab_picks_too_and_esc_hides_it(window):
    box, popup = typed(window, "**label, li")
    box.list_keys(Qt.Key.Key_Down)
    assert box.list_keys(Qt.Key.Key_Tab)
    assert box.toPlainText() == "**label, Line 2 "
    box.insertPlainText("and ")
    assert popup.isVisible()
    assert box.list_keys(Qt.Key.Key_Escape) and not popup.isVisible()
    assert not box.list_keys(Qt.Key.Key_Return)  # with it hidden, Enter is the text box's again


def test_a_new_label_is_offered_and_put_in_as_typed(window):
    box, popup = typed(window, "**label, Fire safety")
    assert names(popup) == ["Create label “Fire safety”"]
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "**label, Fire safety "


def test_picking_the_operator_from_the_star_list_opens_its_list(window):
    box, popup = typed(window, "Fit the rail **lab")
    assert names(popup)[0] == "**label,"
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "Fit the rail **label, "
    assert popup.isVisible() and names(popup)[0] == "Line 1"  # at once, as # alone opens its list
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "Fit the rail **label, Line 1 " and not popup.isVisible()


def test_no_list_after_the_sentence(window):
    box, popup = typed(window, "**label, Safety. Rails are in")
    assert not popup.isVisible()


@pytest.mark.parametrize("pinned", [False, True])
def test_the_agenda_list_puts_in_at_and_hash_with_their_ids(window, pinned):
    box, popup = typed(window, "- @Mike book the crane **agenda, ", pinned)
    assert names(popup)[:3] == ["Today", "Business team meeting", "Priya Shah"]
    box.insertPlainText("tom")
    assert names(popup)[0] == "Tom Becker"
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "- @Mike book the crane **agenda, @Tom Becker " and not popup.isVisible()
    box.insertPlainText("and bus")
    assert popup.isVisible() and names(popup) == ["Business team meeting"]
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "- @Mike book the crane **agenda, @Tom Becker and #Business team meeting "
    assert window.ref_ids["@tom becker"] == "P003" and window.ref_ids["#business team meeting"] == "T000010"


def test_the_agenda_lists_tasks_with_their_marks_and_levels(window):
    box, popup = typed(window, "Lift plan **agenda, reac")
    assert names(popup) == ["Reactor impeller upgrade"] and popup.task_info is not None
    assert box.list_keys(Qt.Key.Key_Right)  # into its open subtasks, as the # list goes
    assert [(popup.item(i).data(_OPTION).label, bool(popup.item(i).data(_HEAD))) for i in range(2)] == [
        ("Reactor impeller upgrade", True), ("Installation", False)]
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "Lift plan **agenda, #Installation " and window.ref_ids["#installation"] == "T000008"


def test_people_and_today_line_up_with_the_tasks(window):
    box, popup = typed(window, "**agenda, ")
    delegate = popup.delegate
    rows = [popup.item(i).data(_OPTION) for i in range(popup.count())]
    assert all(delegate.slot(o, popup.mark(o)) for o in rows)  # Today, the meeting and the people: one left edge


def test_the_cards_read_what_was_picked(window):
    box, popup = typed(window, "- @Mike book the crane **agenda, tom")
    box.list_keys(Qt.Key.Key_Return)
    window.read_items()
    agenda = [it for it in window.reading.items if it.op and it.op.task_field == "agenda"]
    assert [it.value.changes for it in agenda] == [{"agenda": ["P003"]}] and not agenda[0].problem
