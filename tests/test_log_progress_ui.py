"""Release 5.139, the Log progress window, offscreen (the design workspace's ``docs/mods/email-progress-plan.md``, decisions
580 to 598): opening on a draft (a reply its conversation names, a new email, an inline reply) or on none, the fields,
Enter keeping it all and then sending (590 A), an inline reply or a refused send coming back to the front, Esc keeping
nothing, and the status card's Got it. A fake Outlook draft stands in for Outlook. Every name here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import types  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import conversations, outlook, waits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import EmailItem  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.log_progress import LogProgress  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)  # a Thursday
RIGGING, MIKE = "T000012", "P004"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")


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
    w.outlook_calls = []
    monkeypatch.setattr(outlook, "send_draft", lambda draft, now: w.outlook_calls.append(("send", draft.subject)), raising=False)
    monkeypatch.setattr(outlook, "show_draft", lambda draft: w.outlook_calls.append(("show", draft.subject)) or True, raising=False)
    yield w
    QApplication.processEvents()
    w.picker.hide()
    w.hide()
    w.deleteLater()
    QApplication.processEvents()


def draft(subject: str = "RE: Crane quote", index: str = "", inline: bool = False, to: str = "Mike Ortiz <mike.ortiz@example.com>"):
    copy = EmailItem(subject=subject, sender="", sent="", to=to, body="", conversation_index=index)
    return types.SimpleNamespace(item=object(), inline=inline, subject=subject, index=index, entry_id="D1", store_id="S1", copy=copy)


def test_a_reply_in_a_known_conversation_fills_the_task_and_mike(window):
    conn = window.ctx.conn
    index = conversations.new_index(NOW, GUID)
    conversations.record_t_mail(conn, RIGGING, "new", "2026-10-07 09:00:00", index)  # the conversation is Rigging plan's
    window.open_for(draft(index=index + "8000000001"))
    assert window.task == RIGGING and window.task_how == "from conversation"
    assert window.people == [MIKE] and window.choice == "3d" and window.enter.text() == "Send and log"
    assert "Rigging plan comes back on Today" in window.follow_note.text() and "Tue 13 Oct" in window.follow_note.text()
    assert window.isVisible() and not window.picker.isVisible()


def test_enter_keeps_it_all_then_sends(window):
    conn = window.ctx.conn
    window.open_for(draft(subject="Crane quote"), task=RIGGING)
    window.line.setText("Asked Mike for the crane vendor's quote")
    window.submit()
    m = Model(conn)
    w = waits.current(m, RIGGING)
    assert w is not None and w.on == (MIKE,) and m.task(RIGGING).current_status == "Asked Mike for the crane vendor's quote"
    assert next(x for x in m.t_mails if x.id == w.t_mail).kind == "progress"
    assert window.outlook_calls == [("send", "Crane quote")] and not window.isVisible()
    assert window.said == [("Sent, and logged on Rigging plan: waiting on Mike, follow up Tue 13 Oct.", False)]


def test_an_inline_reply_is_logged_and_brought_back_to_send(window):
    window.open_for(draft(inline=True), task=RIGGING)
    assert window.enter.text() == "Log" and "reading pane" in window.after.text()
    window.line.setText("Replied to Mike in the reading pane")
    window.submit()
    assert window.outlook_calls == [("show", "RE: Crane quote")]
    assert window.said[-1][0].endswith("Press Send in Outlook.")


def test_a_refused_send_comes_back_to_the_front(window, monkeypatch):
    def refuse(draft, now):
        raise outlook.OutlookError("operation aborted")

    monkeypatch.setattr(outlook, "send_draft", refuse, raising=False)
    window.open_for(draft(), task=RIGGING)
    window.line.setText("Asked Mike again")
    window.submit()
    assert window.outlook_calls == [("show", "RE: Crane quote")] and window.said[-1][1]
    assert waits.current(Model(window.ctx.conn), RIGGING) is not None  # the log is kept either way


def test_with_progress_sends_off_enter_only_logs(window):
    window.ctx.settings.progress_sends = False
    window.open_for(draft(), task=RIGGING)
    assert window.enter.text() == "Log"


def test_a_call_with_nobody_waited_on(window):
    window.open_for(None, task=RIGGING)
    assert "No email in front" in window.email_line.text() and window.people == [] and window.choice == "none"
    assert window.follow_note.text() == "No follow-up: nothing comes back by itself." and window.enter.text() == "Log"
    window.who.setText("Mike")
    window.add_person()
    assert window.people == [MIKE] and window.choice == "3d"
    window.drop_person(MIKE)
    assert window.choice == "none"
    window.line.setText("Called the crane vendor")
    window.submit()
    assert window.outlook_calls == [] and waits.current(Model(window.ctx.conn), RIGGING) is None
    assert window.said[-1] == ("Logged on Rigging plan.", False)


def test_no_task_opens_the_list_and_no_line_says_so(window):
    window.open_for(draft(subject="Unknown thread"))
    assert window.task is None and window.picker.isVisible()
    window._task_picked(RIGGING)
    window.submit()
    assert "Say in a line" in window.message.text() and window.said == []


def test_escape_keeps_nothing(window):
    window.open_for(draft(), task=RIGGING)
    window.line.setText("Not this time")
    window.hide()
    m = Model(window.ctx.conn)
    assert m.waits == [] and m.task(RIGGING).current_status != "Not this time"
