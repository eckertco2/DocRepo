"""Release 5.105 in the windows, offscreen with a fake Outlook (the knowledge base's stage K8): the capture window's fill
with two emails in one drop and with a reply whose subject was changed, the task page's New T-mail and its arrow, Reply
all in Find files and on a capture's page, each kept as a T-mail. Every email here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import conversations, msg, outlook  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import CaptureDraft, EmailItem, email_rows, save_capture  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from msg_builder import FakeEmail, build  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
INSTALLATION, RIGGING, REACTOR = "T000008", "T000012", "T000001"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")
OTHER = bytes.fromhex("11111111222222223333333344444444")


def index(guid: bytes = GUID, replies: int = 0) -> bytes:
    return b"\x01" + bytes.fromhex("D9A1B2C3D4") + guid + b"".join(bytes([0x80, 0, 0, 0, n]) for n in range(1, replies + 1))


def email(subject: str = "Crane booking", guid: bytes = GUID, replies: int = 0, message_id: str = "<a1@example.com>",
          in_reply_to: str | None = None, sent: datetime = datetime(2026, 10, 7, 9, 15)) -> EmailItem:
    return msg.read(build(FakeEmail(subject=subject, conversation_index=index(guid, replies), message_id=message_id,
                                    in_reply_to=in_reply_to, sent=sent.astimezone())))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)


def captured(ctx, e: EmailItem, task: str | None, at: datetime = datetime(2026, 10, 7, 9, 30), entry: str = "") -> str:
    e.entry_id, e.store_id = entry, "S1" if entry else ""
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, CaptureDraft(content="", task=task, files=email_rows(e)[:1]), at)
    assert r.capture_id
    return r.capture_id


@pytest.fixture
def window(ctx):
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    yield w
    for view in list(w.task_views.values()):
        view.deleteLater()
    capture.deleteLater()
    w.deleteLater()


@pytest.fixture
def fake_outlook(monkeypatch):
    """outlook.new_t_mail and outlook.reply_all, recorded: each opens a T-mail with a made-up index."""
    calls: list[tuple] = []

    def new(now):
        calls.append(("new", now))
        return outlook.Opened(conversations.new_index(now, OTHER), "saved")

    def reply(entry, store, saved):
        calls.append(("reply", entry, store, saved))
        return outlook.Opened(index(GUID, 1).hex().upper(), "place" if entry else "msg")

    monkeypatch.setattr(outlook, "new_t_mail", new)
    monkeypatch.setattr(outlook, "reply_all", reply)
    return calls


# ================= the fill =================
def test_two_emails_in_one_drop_from_two_tasks_empty_the_picker(window, ctx):
    """The corporate computer's case (2026-11-09): two emails, each already captured, of one conversation filed to two
    tasks, dropped together."""
    first, reply = email(), email("Re: crane booking", replies=1, message_id="<a2@example.com>")
    captured(ctx, first, RIGGING)
    captured(ctx, reply, INSTALLATION, datetime(2026, 10, 8, 9, 0))
    window._read_emails(lambda: [first, reply], "a test drop")
    assert window.task is None and not window.task_conv
    assert window.task_button.text().startswith("None: these emails belong to ") and "pick the task" in window.task_button.text()


def test_two_emails_in_one_drop_of_one_task_fill_it(window, ctx):
    captured(ctx, email(), RIGGING)
    window._read_emails(lambda: [email("Re: crane booking", replies=1, message_id="<a2@example.com>"),
                                 email("Re: crane booking", replies=2, message_id="<a3@example.com>")], "a test drop")
    assert window.task == RIGGING and window.task_conv


def test_a_reply_with_a_changed_subject_fills_the_picker_from_the_email_it_answers(window, ctx):
    cid = captured(ctx, email(), RIGGING)
    window._add_email(email("Crane moved to Thursday", OTHER, message_id="<b1@example.com>", in_reply_to="<a1@example.com>"))
    assert window.task == RIGGING and window.task_button.text().endswith("Rigging plan  (from conversation)")
    assert window.task_button.toolTip().startswith(f"The email this one answers was filed to Rigging plan on 2026-10-07 ({cid})")


# ================= the task page's New T-mail =================
def bar(browse) -> dict:
    lay = browse.actions_layout
    out = {}
    for w in (lay.itemAt(i).widget() for i in range(lay.count())):
        for b in [w] if isinstance(w, QPushButton) else (w.findChildren(QPushButton) if w is not None else []):
            out[b.text() or b.accessibleName()] = b
    return out


def test_new_t_mail_opens_an_email_and_keeps_it_on_the_task(browse, fake_outlook):
    browse.select("task", RIGGING)
    buttons = bar(browse)
    assert buttons["New T-mail"].menu() is None and buttons["More T-mails"].menu() is not None  # a split button
    buttons["New T-mail"].click()
    assert fake_outlook == [("new", NOW)]
    t = Model(browse.conn).t_mails[-1]
    assert (t.task, t.kind, t.conversation, t.opened) == (RIGGING, "new", OTHER.hex().upper(), "2026-10-08 14:10:00")
    assert browse.status.text() == "Opened a new T-mail from Rigging plan in Outlook. When you send it, it's captured on Rigging plan, and so are the replies you capture."
    # Its replies now fill the capture window's picker with the task.
    answer = email("Re: hello", OTHER, replies=1, message_id="<c1@example.com>")
    assert conversations.pick_emails(Model(browse.conn), [answer]).task == RIGGING


def test_new_t_mail_says_why_when_outlook_isnt_there(browse, monkeypatch):
    def refuse(now):
        raise outlook.OutlookError("Outlook isn't open. Open classic Outlook, select the email, and try again.")

    monkeypatch.setattr(outlook, "new_t_mail", refuse)
    browse.select("task", RIGGING)
    bar(browse)["New T-mail"].click()
    assert browse.status.text().startswith("New T-mail: Outlook isn't open") and browse.status.property("error")
    assert Model(browse.conn).t_mails == []


def test_the_arrow_replies_to_the_tasks_latest_email(browse, ctx, fake_outlook):
    browse.select("task", RIGGING)
    menu = bar(browse)["More T-mails"].menu()
    only, ask = [a for a in menu.actions() if not a.isSeparator()]  # Ask for an update after it since release 5.125
    assert only.text() == "Reply all to the latest email" and not only.isEnabled() and ask.text() == "Ask for an update"
    captured(ctx, email(sent=datetime(2026, 10, 1, 8, 0)), RIGGING)
    newest = captured(ctx, email("Re: crane booking", replies=1, message_id="<a2@example.com>"), RIGGING,
                      datetime(2026, 10, 7, 10, 0), entry="E2")
    browse.select("task", RIGGING)
    menu = bar(browse)["More T-mails"].menu()
    only = [a for a in menu.actions() if not a.isSeparator()][0]
    assert only.isEnabled() and only.text() == "Reply all to the latest email: “Re: crane booking”, Ann Example, 2026-10-07"
    only.trigger()
    assert fake_outlook[-1][:3] == ("reply", "E2", "S1") and fake_outlook[-1][3].name == "email.msg"
    t = Model(browse.conn).t_mails[-1]
    assert (t.task, t.kind, t.reply_capture, t.reply_pos) == (RIGGING, "reply", newest, 0)
    assert browse.status.text() == "Opened a Reply all from Rigging plan in Outlook. When you send it, it's captured on Rigging plan, and so are the replies you capture."


# ================= Reply all in Find files and on a capture's page =================
def test_find_files_email_rows_have_reply_all(browse, ctx, fake_outlook):
    cid = captured(ctx, email(), RIGGING)
    browse.open_task_view(RIGGING)
    view = browse.task_views[RIGGING]
    view.set_kind("email")
    i = next(n for n, r in enumerate(view.list.rows) if r.record is not None and r.record.capture == cid)
    assert [a[1] for a in view._actions_for(view.list.rows[i].record)] == ["open", "replyall", "capture"]
    view.act("replyall", i)
    assert fake_outlook[-1][:3] == ("reply", "", "") and fake_outlook[-1][3].name == "email.msg"  # no place kept: the .msg
    t = Model(browse.conn).t_mails[-1]
    assert (t.task, t.kind, t.reply_capture) == (RIGGING, "reply", cid)
    assert view.foot.text().startswith("Opened a Reply all from Rigging plan in Outlook.")


def test_a_capture_page_has_reply_all_beside_each_email(browse, ctx, fake_outlook):
    cid = captured(ctx, email(), RIGGING, entry="E1")
    browse.go_capture(cid)
    html = browse.pages().capture_page(cid, "")
    assert f'href="replyall:{cid}:0"' in html
    browse.on_link(QUrl(f"replyall:{cid}:0"))
    assert fake_outlook[-1][:3] == ("reply", "E1", "S1")
    assert Model(browse.conn).t_mails[-1].reply_capture == cid


def test_an_unfiled_captures_reply_is_opened_but_not_kept(browse, ctx, fake_outlook):
    cid = captured(ctx, email("Loose", OTHER, message_id="<l1@example.com>"), None)
    browse.on_link(QUrl(f"replyall:{cid}:0"))
    assert fake_outlook[-1][0] == "reply" and Model(browse.conn).t_mails == []
    assert "isn't filed to a task" in browse.status.text()
