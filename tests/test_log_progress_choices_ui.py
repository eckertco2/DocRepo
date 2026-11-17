"""Release 5.155, Log progress's State and Done for today, offscreen (the design workspace's
``docs/mods/log-progress-choices-plan.md``, decisions 695 to 697, and its mock): the dropdown under What you did and the
state it opens on, Waiting on and Follow up kept in step with it, Enter with nobody to wait on, Parked and Closed, and the
Today row: shown only when the task is on Today, unticked each time, ticked and fixed with Closed, its line, and what Enter
says. A fake Outlook draft stands in for Outlook. Every name here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import types  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import edits, outlook, progress, tasks, waits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import EmailItem  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.log_progress import LogProgress  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)  # a Thursday
RIGGING, INSTALLATION, MIKE = "T000012", "T000008", "P004"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, sample_root, monkeypatch):
    conn, root, fs = sample_root
    settings = Settings(me="P001")
    settings.save(fs, root)
    ctx = AppContext(conn, root, fs, settings, now=lambda: NOW)
    said: list[tuple[str, bool]] = []
    app = types.SimpleNamespace(ctx=ctx, progress_logged=lambda done, text, trouble: said.append((text, trouble)))
    w = LogProgress(app)
    w.said = said
    monkeypatch.setattr(outlook, "send_draft", lambda draft, now: None, raising=False)
    monkeypatch.setattr(outlook, "show_draft", lambda draft: True, raising=False)
    yield w
    QApplication.processEvents()
    w.picker.hide()
    w.hide()
    w.deleteLater()
    QApplication.processEvents()


def draft(to: str = "Mike Ortiz <mike.ortiz@example.com>"):
    copy = EmailItem(subject="RE: Crane quote", sender="", sent="", to=to, body="", conversation_index="")
    return types.SimpleNamespace(item=object(), inline=False, subject="RE: Crane quote", index="", entry_id="D1", store_id="S1", copy=copy)


def put_on_today(window, task: str = RIGGING) -> int:
    ctx = window.ctx
    edits.add_to_today(ctx.conn, ctx.data_root, ctx.fs, task, "", NOW - timedelta(hours=3))
    return next(a.id for a in Model(ctx.conn).today_items() if a.subject == task)


def pick(window, key: str) -> None:
    """Pick a state as the owner does: the dropdown's activated."""
    n = next(i for i in range(window.state_box.count()) if window.state_box.itemData(i) == key)
    window.state_box.setCurrentIndex(n)
    window.state_box.activated.emit(n)


def dimmed(window) -> bool:
    return all(e.isEnabled() for e in window._dimmed)


# ================= the dropdown (decision 695) =================
def test_state_is_a_dropdown_under_what_you_did(window):
    window.open_for(draft(), task=RIGGING)
    box = window.state_box
    assert [box.itemText(i) for i in range(box.count())] == ["In progress", "Waiting on a reply", "Parked", "Closed"]
    assert box.itemData(3, Qt.ItemDataRole.ToolTipRole) == "Finished: off Today too"
    grid = window.layout().itemAt(1).layout()
    rows = {grid.itemAtPosition(r, 0).widget().text(): r for r in range(grid.rowCount()) if grid.itemAtPosition(r, 0)}
    assert rows["What you did"] < rows["State"] < rows["Waiting on"] < rows["Follow up"] < rows["Today"]


def test_it_opens_on_waiting_with_the_emails_people_else_in_progress(window):
    window.open_for(draft(), task=RIGGING)
    assert window.state_key == progress.WAITING and window.state_box.currentText() == "Waiting on a reply"
    assert window.people == [MIKE] and not dimmed(window) and "hourglass" in window.state_note.text()
    window.open_for(None, task=RIGGING)
    assert window.state_key == progress.IN_PROGRESS and window.state_box.currentText() == "In progress" and dimmed(window)
    assert window.who_note.text() == "Pick Waiting on a reply to wait on someone."
    window.open_for(draft(to="Someone Else <someone@example.com>"), task=RIGGING)
    assert window.state_key == progress.IN_PROGRESS and window.people == []


def test_another_state_empties_waiting_on_and_follow_up(window):
    window.open_for(draft(), task=RIGGING)
    assert window.choice == "3d"
    pick(window, progress.PARKED)
    assert window.people == [] and window.choice == "none" and dimmed(window)
    assert window.follow_note.text() == "No follow-up: nothing comes back by itself."
    assert window.state_note.text() == "Parked, with this line as its current status. No wait."
    assert not any(b.isEnabled() for b in window.follow.buttons() if b.property("key") != "none")
    pick(window, progress.WAITING)  # back: Mike from the email's To, and the last follow-up
    assert window.people == [MIKE] and window.choice == "3d" and not dimmed(window)


def test_waiting_with_nobody_puts_the_cursor_in_waiting_on(window, qapp):
    window.open_for(None, task=RIGGING)
    window.show()
    qapp.processEvents()
    pick(window, progress.WAITING)
    qapp.processEvents()
    assert window.state_key == progress.WAITING and window.people == [] and window.focusWidget() is window.who
    window.line.setText("Asked Mike about the crane")
    window.submit()
    assert window.message.text() == progress.NOBODY and window.said == [] and window.isVisible()


def test_a_person_added_picks_waiting_and_the_last_taken_picks_in_progress(window):
    window.open_for(None, task=RIGGING)
    window.who.setText("Mike")
    window.add_person()
    assert window.state_key == progress.WAITING and window.state_box.currentText() == "Waiting on a reply" and window.choice == "3d"
    window.drop_person(MIKE)
    assert window.state_key == progress.IN_PROGRESS and window.choice == "none" and dimmed(window)


def test_backspace_on_the_last_person_picks_in_progress(window):
    window.open_for(draft(), task=RIGGING)
    window.who.setFocus()
    QTest.keyClick(window.who, Qt.Key.Key_Backspace)
    assert window.people == [] and window.state_key == progress.IN_PROGRESS


def test_the_state_line_says_what_enter_does(window):
    window.open_for(None, task="T000003")  # a parked task
    assert window.state_note.text() == "Was Parked: it goes In progress, with nothing to wait for."
    window.open_for(None, task=INSTALLATION)
    pick(window, progress.CLOSED)
    assert window.state_note.text() == "Closed, with this line as its last status. No wait. Its 3 open subtasks stay open."


# ================= Enter =================
def test_parked_enter_parks_it_with_no_wait(window):
    window.open_for(draft(), task=RIGGING)
    pick(window, progress.PARKED)
    window.line.setText("On hold until the crane is booked")
    window.submit()
    m = Model(window.ctx.conn)
    assert m.task(RIGGING).state == "Parked" and waits.current(m, RIGGING) is None
    assert window.said[-1] == ("Sent, and logged on Rigging plan: parked.", False)


def test_closed_closes_the_task_and_its_today_item(window):
    item_id = put_on_today(window, INSTALLATION)
    window.open_for(None, task=INSTALLATION)
    pick(window, progress.CLOSED)
    assert window.done_box.isChecked() and not window.done_box.isEnabled()
    assert window.today_note.text() == "Closed: its Today item closes as done with it."
    window.line.setText("Installation signed off")
    window.submit()
    m = Model(window.ctx.conn)
    assert m.task(INSTALLATION).state == "Closed" and next(a for a in m.agenda if a.id == item_id).how == "Done"
    assert window.said[-1] == ("Logged on Installation: closed. Done for today.", False)


# ================= the Today row (decision 697) =================
def test_the_today_row_shows_only_when_the_task_is_on_today(window):
    window.open_for(None, task=RIGGING)
    assert window.done_box.isHidden() and window.today_name.isHidden()
    put_on_today(window)
    window.open_for(None, task=RIGGING)
    assert not window.done_box.isHidden() and not window.done_box.isChecked() and window.done_box.isEnabled()
    assert window.today_note.text() == "It's on Today. Tick to take it off as done once this is logged."


def test_done_for_today_is_unticked_each_time_and_closed_ticks_it_only_while_picked(window):
    put_on_today(window)
    window.open_for(draft(), task=RIGGING)
    window.done_box.setChecked(True)
    assert window.done_today
    window.open_for(draft(), task=RIGGING)
    assert not window.done_box.isChecked() and not window.done_today
    pick(window, progress.CLOSED)
    assert window.done_box.isChecked()
    pick(window, progress.IN_PROGRESS)
    assert not window.done_box.isChecked() and window.done_box.isEnabled()


def test_done_for_today_with_a_follow_up_says_when_it_comes_back(window):
    item_id = put_on_today(window)
    window.open_for(draft(), task=RIGGING)
    window.done_box.setChecked(True)
    assert window.today_note.text() == "Off Today until Tue 13 Oct, if Mike hasn't replied: the follow-up brings it back."
    window.line.setText("Asked Mike for the crane vendor's quote")
    window.submit()
    m = Model(window.ctx.conn)
    assert next(a for a in m.agenda if a.id == item_id).how == "Done" and waits.current(m, RIGGING) is not None
    assert window.said[-1] == ("Sent, and logged on Rigging plan: waiting on Mike, follow up Tue 13 Oct. Done for today.", False)


def test_an_earlier_reminder_of_the_tasks_own_is_the_day_it_comes_back(window):
    ctx = window.ctx
    tasks.update_task(ctx.conn, ctx.settings, RIGGING, at=NOW - timedelta(days=1), via="test", reminder="2026-10-12")
    put_on_today(window)
    window.open_for(draft(), task=RIGGING)  # follow up in 3 days: Tue 13 Oct, after the task's own Mon 12 Oct
    window.done_box.setChecked(True)
    assert window.today_note.text() == "Off Today until Mon 12 Oct: its reminder brings it back."


def test_done_for_today_with_no_follow_up_stays_under_done_today(window):
    item_id = put_on_today(window)
    window.open_for(None, task=RIGGING)
    window.done_box.setChecked(True)
    assert window.today_note.text() == "It stays under Done today, where Back on Today puts it back."
    window.line.setText("Called the crane company")
    window.submit()
    assert next(a for a in Model(window.ctx.conn).agenda if a.id == item_id).how == "Done"
    assert window.said[-1] == ("Logged on Rigging plan. Done for today.", False)


def test_unticked_the_item_stays_and_enter_says_nothing_of_today(window):
    item_id = put_on_today(window)
    window.open_for(None, task=RIGGING)
    window.line.setText("Called the crane company")
    window.submit()
    assert not next(a for a in Model(window.ctx.conn).agenda if a.id == item_id).closed
    assert window.said[-1] == ("Logged on Rigging plan.", False)
