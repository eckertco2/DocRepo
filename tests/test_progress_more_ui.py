"""Release 5.166, Log progress: the rest, offscreen (the design workspace's docs/mods/log-progress-whole-plan.md, decisions 757
to 762): Dates and reminder… opening Edit task and coming back, an email attached, Log, then next… and its next step, the
window opened on a state, the state menu's Waiting on a reply…, and Waiting on a reply in the capture window's State
lists. A fake Outlook stands in for Outlook. Every name here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import types  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, outlook, progress, prompts, tasks, waits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import EmailItem  # noqa: E402
from docrepo.ui import capture_waiting  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.log_progress import LogProgress  # noqa: E402
from docrepo.ui.state_menu import WAITING, state_menu  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)  # a Thursday
RIGGING, MIKE = "T000012", "P004"


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
    edited: list[str] = []

    def edit_dates(task_id: str) -> None:  # Edit task, the owner setting a Reminder and saving
        edited.append(task_id)
        tasks.update_task(conn, settings, task_id, at=NOW, via="Browse tool", reminder="2026-10-20")

    app = types.SimpleNamespace(ctx=ctx, progress_logged=lambda done, text, trouble: said.append((text, trouble)), edit_task_dates=edit_dates)
    w = LogProgress(app)
    w.said, w.edited = said, edited
    monkeypatch.setattr(outlook, "send_draft", lambda draft: None, raising=False)
    monkeypatch.setattr(outlook, "show_draft", lambda draft: True, raising=False)
    monkeypatch.setattr(outlook, "copy_path", lambda fs, root: None, raising=False)
    yield w
    QApplication.processEvents()
    w.picker.hide()
    w.parent_picker.hide()
    w.hide()
    w.deleteLater()
    QApplication.processEvents()


# ================= Dates and reminder… (decision 758) =================
def test_dates_opens_edit_task_and_comes_back_with_the_reminder(window):
    window.open_for(None, task=RIGGING)
    assert window.dates_link.isVisibleTo(window) and window.dates_link.text() == "Dates and reminder…"
    window.dates_link.click()
    assert window.edited == [RIGGING] and window.isVisible()
    assert Model(window.ctx.conn).task(RIGGING).reminder == "2026-10-20"


def test_dates_with_no_task_opens_the_list(window):
    window.open_for(None)
    window.picker.hide()
    window.dates_link.click()
    assert window.edited == [] and window.picker.isVisible()


# ================= an email attached (decision 759) =================
def email(subject: str = "Lift points") -> EmailItem:
    return EmailItem(subject, "Mike Ortiz <mike.ortiz@example.com>", "2026-10-08 08:40", "Me", "Points B and D moved 200 mm.")


def test_attach_keeps_the_selected_email_on_the_update(window, monkeypatch):
    monkeypatch.setattr(outlook, "selected_emails", lambda scratch=None: [email()], raising=False)
    window.open_for(None, task=RIGGING)
    assert window.attach_button.isVisibleTo(window) and not window.detach_button.isVisibleTo(window)
    window.attach()
    assert window.attached is not None and "Lift points" in window.email_line.text() and "From Mike Ortiz" in window.email_line.text()
    assert window.detach_button.isVisibleTo(window) and not window.attach_button.isVisibleTo(window)
    window.line.setText("Mike moved the lift points")
    window.submit()
    m = Model(window.ctx.conn)
    c = next(c for c in m.captures.values() if c.task == RIGGING and "update" in c.types and c.emails)
    assert [e.subject for e in c.emails] == ["Lift points"]
    assert window.said[-1][0] == "Logged on Rigging plan. The email is kept with it."


def test_attach_says_when_none_or_several_are_selected_and_the_cross_takes_it_off(window, monkeypatch):
    window.open_for(None, task=RIGGING)
    monkeypatch.setattr(outlook, "selected_emails", lambda scratch=None: [], raising=False)
    window.attach()
    assert window.attached is None and window.problems[""].text() == "Select an email in Outlook first: none is selected."
    monkeypatch.setattr(outlook, "selected_emails", lambda scratch=None: [email(), email("Crane quote")], raising=False)
    window.attach()
    assert window.attached is None and window.problems[""].text() == "2 emails are selected in Outlook: select one."
    monkeypatch.setattr(outlook, "selected_emails", lambda scratch=None: [email()], raising=False)
    window.attach()
    window.detach()
    assert window.attached is None and "No email in front" in window.email_line.text()


def test_attach_is_off_with_a_draft_in_front(window, monkeypatch):
    calls = []
    monkeypatch.setattr(outlook, "selected_emails", lambda scratch=None: calls.append(1) or [email()], raising=False)
    copy = EmailItem(subject="RE: Crane quote", sender="", sent="", to="", body="", conversation_index="")
    window.open_for(types.SimpleNamespace(item=object(), inline=False, subject="RE: Crane quote", index="", entry_id="D1", store_id="S1",
                                          copy=copy), task=RIGGING)
    assert not window.attach_button.isVisibleTo(window)
    window.attach()
    assert calls == [] and window.attached is None


# ================= Log, then next… (decision 761) =================
def test_log_then_next_opens_the_next_step_under_the_parent(window):
    conn = window.ctx.conn
    parent = Model(conn).parents_of(RIGGING)[0]
    window.open_for(None, task=RIGGING)
    window.line.setText("Sent the lift plan")
    window.log_then_next()
    assert window.next_step and window.isVisible() and window.next_parent == parent
    assert window.task_button.text() == f"New task under {Model(conn).task(parent).title}"
    assert [window.state_box.itemText(i) for i in range(window.state_box.count())] == ["Not started", "In progress", "Waiting on a reply"]
    assert window.choice == "today" and window.enter.text() == "Make it" and not window.next_button.isVisibleTo(window)
    assert window.said[-1][0] == "Logged on Rigging plan."
    window.line.setText("Book the crane")
    window.submit()
    m = Model(conn)
    made = next(t for t in m.tasks.values() if t.title == "Book the crane")
    assert m.parents_of(made.id) == [parent] and made.state == "Not started" and any(a.subject == made.id for a in m.today_items())
    assert not window.isVisible() and window.said[-1][0].startswith("Next step made under")
    window.open_for(None, task=RIGGING)  # the next open is Log progress again
    assert not window.next_step and window.state_box.count() == 4


def test_esc_in_the_next_step_makes_nothing(window):
    conn = window.ctx.conn
    window.open_for(None, task=RIGGING)
    window.line.setText("Sent the lift plan")
    window.log_then_next()
    before = len(Model(conn).tasks)
    window.hide()  # Esc
    assert len(Model(conn).tasks) == before
    assert Model(conn).task(RIGGING).current_status == "Sent the lift plan"  # the first log is kept


def test_the_next_step_can_wait_and_go_top_level(window):
    conn = window.ctx.conn
    window.open_for(None, task=RIGGING)
    window.line.setText("Sent the lift plan")
    window.log_then_next()
    window._parent_picked(None)
    assert window.task_button.text() == "New top-level task"
    window.who.setText("Mike")
    window.add_person()
    assert window.state_key == progress.WAITING and window.choice == "3d"
    window.line.setText("Hear back on the crane")
    window.submit()
    m = Model(conn)
    made = next(t for t in m.tasks.values() if t.title == "Hear back on the crane")
    w = waits.current(m, made.id)
    assert m.parents_of(made.id) == [] and w is not None and w.on == (MIKE,) and made.reminder == "2026-10-13"


# ================= opened on a state (decisions 755 and 762) =================
def test_open_on_closed_and_on_waiting(window):
    window.open_for(None, task=RIGGING, state=progress.CLOSED)
    assert window.state_key == progress.CLOSED and not window.back.isEnabled() and window.line.text() == ""
    window.open_for(None, task=RIGGING, state=progress.WAITING)
    assert window.state_key == progress.WAITING and window.people == []
    window.line.setText("Asked Mike")
    window.submit()
    assert window.problems["who"].text() == progress.NOBODY


def test_the_state_menu_offers_waiting_on_a_reply(qapp, sample_root):
    conn = sample_root[0]
    asked = []
    menu = state_menu(None, Model(conn), RIGGING, lambda *a: None, wait=lambda: asked.append(RIGGING))
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels[:4] == ["Not started", "In progress", WAITING, "Parked"]
    next(a for a in menu.actions() if a.text() == WAITING).trigger()
    assert asked == [RIGGING]
    plain = state_menu(None, Model(conn), RIGGING, lambda *a: None)  # no wait given: no entry
    assert WAITING not in [a.text() for a in plain.actions()]
    menu.deleteLater()
    plain.deleteLater()


# ================= the capture window's State lists (decision 762) =================
@pytest.fixture
def capture(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, now=lambda: NOW)
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()
    conn.close()


def test_both_state_lists_offer_waiting_on_a_reply(capture):
    for box in (capture.u_state, capture.n_state):
        assert [box.itemText(i) for i in range(box.count())] == ["Not started", "In progress", capture_waiting.WAITING, "Parked", "Closed"]


def test_an_update_waiting_on_a_reply_starts_the_wait_with_the_reminder_as_its_follow_up(capture):
    conn = capture.ctx.conn
    capture.set_task(RIGGING)
    capture.set_type("update", True)
    capture.u_state.setCurrentText(capture_waiting.WAITING)
    assert capture.u_waiting.isVisibleTo(capture)
    capture.u_waiting.box.setText("Mike")
    capture.u_waiting.add()
    capture.u_reminder.set_value("2026-10-13")
    capture.content.setPlainText("Asked Mike for the crane quote.")
    capture.save()
    m = Model(conn)
    w = waits.current(m, RIGGING)
    assert m.task(RIGGING).state == "In progress" and w is not None and w.on == (MIKE,) and w.follow_up == "2026-10-13"
    assert w.line == "Asked Mike for the crane quote."


def test_waiting_with_nobody_is_said_and_keeps_nothing(capture):
    conn = capture.ctx.conn
    capture.set_task(RIGGING)
    capture.set_type("update", True)
    capture.u_state.setCurrentText(capture_waiting.WAITING)
    capture.content.setPlainText("Asked about the crane.")
    capture.save()
    assert "Who are you waiting on?" in capture.error.text() and waits.current(Model(conn), RIGGING) is None


def test_a_new_task_waiting_on_a_reply(capture):
    conn = capture.ctx.conn
    capture.set_type("new_task", True)
    capture.title.setText("Crane quote from the vendor")
    capture.n_state.setCurrentText(capture_waiting.WAITING)
    assert capture.n_waiting.isVisibleTo(capture) or capture.n_more.isHidden()
    capture.n_waiting.box.setText("Mike")
    capture.n_waiting.add()
    capture.save()
    m = Model(conn)
    made = next(t for t in m.tasks.values() if t.title == "Crane quote from the vendor")
    w = waits.current(m, made.id)
    assert made.state == "In progress" and w is not None and w.on == (MIKE,) and w.follow_up is None
