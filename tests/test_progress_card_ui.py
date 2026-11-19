"""Release 5.175, the workspace's status card opens into Log progress's form (the design workspace's
docs/mods/log-progress-whole-plan.md, decisions 763 and 764), offscreen over the sample data with the made-up work of
``workspace_example``: one form in two homes; the card closed keeps an Update as before; opened (More, or Alt+Down), it
shows State, Waiting on and Today under its line, and Enter logs what Log progress would. Every name here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import types  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from docrepo import edits, progress, waits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui import back_row  # noqa: E402
from docrepo.ui import workspace as workspace_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.log_progress import LogProgress  # noqa: E402
from docrepo.ui.progress_form import ProgressForm  # noqa: E402
from workspace_example import AT, make  # noqa: E402

MIKE = "P004"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qapp, sample_root):
    conn, root, fs = sample_root
    work = make(conn, root, fs)
    edits.add_to_today(conn, root, fs, work.crane, "", AT)
    ctx = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1500, 900)
    w.set_view("today")
    workspace_ui.open_workspace(w, work.crane)
    settle()
    yield w, work
    if getattr(w, "workspace", None) is not None:
        w.workspace.pane.notes.save_now()
    capture.deleteLater()
    w.deleteLater()


def settle() -> None:
    for _ in range(5):
        QApplication.processEvents()


def key(widget, k, mods=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, k, mods))


@pytest.fixture(autouse=True)
def modifiers_let_go(qapp):
    """Qt keeps the modifiers of the last key press it was handed (a release doesn't clear them), and opening a task reads
    them (release 5.174's ``task_open.shift_held``): a test's Shift+Enter or Alt+Down, never let go, would make the next
    file's opens go the other way. A keyboard lets go of Shift itself; here a plain key press does."""
    yield
    QApplication.sendEvent(QLineEdit(), QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier))
    assert QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier


def updates(conn, task: str) -> int:
    return sum(1 for c in Model(conn).captures.values() if c.task == task and "update" in c.types)


# ================= one form, two homes (decision 763) =================
def test_the_window_and_the_card_hold_the_same_form(setup):
    browse, work = setup
    card = browse.workspace.card
    form = browse.workspace.card_form
    assert isinstance(form, ProgressForm) and form.line is card.box and not form.own_line
    window = LogProgress(types.SimpleNamespace(ctx=browse.ctx, progress_logged=lambda *a: None))
    assert isinstance(window.form, ProgressForm) and window.line is window.form.line and window.form.own_line
    assert type(window.form.back) is type(form.back) and window.state_box.count() == form.state_box.count() == 4
    window.deleteLater()


# ================= the card closed (decision 764) =================
def test_closed_the_card_keeps_an_update_as_before(setup):
    browse, work = setup
    w = browse.workspace
    card = w.card
    assert not card.more_open and card.form_box.isHidden() and card.state_button.isVisibleTo(card)
    before = updates(browse.conn, work.crane)
    card.box.setText("Crane vendor called back")
    key(card.box, Qt.Key.Key_Return)
    settle()
    assert updates(browse.conn, work.crane) == before + 1 and Model(browse.conn).task(work.crane).current_status == "Crane vendor called back"


# ================= opened (decision 764) =================
def test_more_opens_the_form_under_the_line_and_alt_down_toggles_it(setup):
    browse, work = setup
    card = browse.workspace.card
    card.box.setText("Asked Mike")
    card.more_action.trigger()
    settle()
    form = browse.workspace.card_form
    assert card.more_open and not card.form_box.isHidden() and card.box.text() == "Asked Mike"  # the words typed stay
    assert not card.state_button.isVisibleTo(card) and not card.later_button.isVisibleTo(card) and not card.add_button.isVisibleTo(card)
    assert form.task == work.crane and form.back.mode == back_row.ON_TODAY and form.choice == back_row.STAYS
    assert card.hint.text() == "Enter logs it all · Shift+Enter note"
    key(card.box, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    settle()
    if card.more_open:  # Alt+Down is a shortcut: offscreen it fires only when the box has the keyboard
        card.set_more(False)
    assert not card.more_open and card.form_box.isHidden() and card.state_button.isVisibleTo(card)


def test_opened_enter_logs_it_all_as_log_progress_would(setup):
    browse, work = setup
    conn = browse.conn
    w = browse.workspace
    card, form = w.card, w.card_form
    card.set_more(True)
    form.who.setText("Mike")
    form.add_person()
    assert form.state_key == progress.WAITING and form.choice == "3d"
    card.box.setText("Asked Mike for the crane vendor's quote")
    key(card.box, Qt.Key.Key_Return)
    settle()
    m = Model(conn)
    wait = waits.current(m, work.crane)
    assert wait is not None and wait.on == (MIKE,) and m.task(work.crane).current_status == "Asked Mike for the crane vendor's quote"
    assert not any(a.subject == work.crane for a in m.today_items())  # Back 3 days: off Today now, back by its Reminder
    assert m.task(work.crane).reminder == wait.follow_up
    assert card.box.text() == "" and not card.more_open and "waiting on Mike" in browse.status.text()


def test_opened_a_stop_is_said_in_the_card_and_keeps_nothing(setup):
    browse, work = setup
    w = browse.workspace
    card, form = w.card, w.card_form
    card.set_more(True)
    form.pick_state(progress.WAITING)
    card.box.setText("Asked about the crane")
    before = updates(browse.conn, work.crane)
    key(card.box, Qt.Key.Key_Return)
    settle()
    assert form.problems["who"].text() == progress.NOBODY and not form.problems["who"].isHidden()
    assert updates(browse.conn, work.crane) == before and card.more_open


def test_opened_done_for_today_and_parked(setup):
    browse, work = setup
    conn = browse.conn
    w = browse.workspace
    card, form = w.card, w.card_form
    card.set_more(True)
    form.pick_state(progress.PARKED)
    form.back.buttons["done"].click()
    card.box.setText("On hold until the crane is booked")
    key(card.box, Qt.Key.Key_Return)
    settle()
    m = Model(conn)
    assert m.task(work.crane).state == "Parked" and not any(a.subject == work.crane for a in m.today_items())
    assert browse.status.text().startswith("Logged on") and "parked" in browse.status.text()


def test_esc_in_the_empty_box_closes_the_form_first(setup):
    browse, work = setup
    card = browse.workspace.card
    card.set_more(True)
    key(card.box, Qt.Key.Key_Escape)
    settle()
    assert not card.more_open and workspace_ui.is_open(browse)


def test_shift_enter_keeps_a_note_even_opened(setup):
    browse, work = setup
    card = browse.workspace.card
    card.set_more(True)
    before = updates(browse.conn, work.crane)
    card.box.setText("Lift plan needs the east cell first")
    key(card.box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    settle()
    assert updates(browse.conn, work.crane) == before and "Lift plan needs the east cell first" in Model(browse.conn).pages.get(work.crane, "")
