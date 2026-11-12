"""Release 5.122 in the browse window, offscreen with a fake Outlook (the design workspace's
``docs/mods/email-section-plan.md``): the task page's Email conversations, a conversation's page and its bar, Open in
Outlook by the email's place and by its saved .msg, Reply all and New T-mail from there. Every email here is made up."""
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
from docrepo.ui import conversation_page  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from msg_builder import FakeEmail, build  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
REACTOR, INSTALLATION, RIGGING = "T000001", "T000008", "T000012"
GUID = "0F1E2D3C4B5A69788796A5B4C3D2E1F0"
OTHER = bytes.fromhex("11111111222222223333333344444444")


def index(replies: int = 0) -> bytes:
    return b"\x01" + bytes.fromhex("D9A1B2C3D4") + bytes.fromhex(GUID) + b"".join(bytes([0x80, 0, 0, 0, n]) for n in range(1, replies + 1))


def email(subject: str = "Crane booking", replies: int = 0, mid: str = "<a1@example.com>", sent: datetime = datetime(2026, 10, 2, 8, 30),
          entry: str = "") -> EmailItem:
    e = msg.read(build(FakeEmail(subject=subject, sender="Sam Kowalski", body="The crane is booked for Tuesday.", sent=sent.astimezone(),
                                 conversation_index=index(replies), message_id=mid)))
    e.entry_id, e.store_id = entry, "S1" if entry else ""
    return e


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)


def captured(ctx, e: EmailItem, task: str, at: datetime) -> str:
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, CaptureDraft(content="", task=task, files=email_rows(e)[:1]), at)
    assert r.capture_id
    return r.capture_id


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.said = []
    w.say = lambda text, error=False: w.said.append((text, error))
    w.show_browse()
    yield w
    for view in list(w.task_views.values()):
        view.deleteLater()
    capture.deleteLater()
    w.deleteLater()


@pytest.fixture
def two(ctx):
    """A conversation of two emails on Rigging plan: the first with its place in Outlook, the reply with only its .msg."""
    first = captured(ctx, email(entry="E1"), RIGGING, datetime(2026, 10, 2, 8, 40))
    reply = captured(ctx, email("RE: Crane booking", 1, "<a2@example.com>", datetime(2026, 10, 7, 16, 20)), RIGGING, datetime(2026, 10, 7, 16, 30))
    return first, reply


def bar(browse) -> dict:
    lay = browse.actions_layout
    out = {}
    for w in (lay.itemAt(i).widget() for i in range(lay.count())):
        for b in [w] if isinstance(w, QPushButton) else (w.findChildren(QPushButton) if w is not None else []):
            out[b.text() or b.accessibleName()] = b
    return out


def test_the_task_page_has_the_section_open(browse, two):
    browse.go_task(REACTOR)
    QApplication.processEvents()
    g = browse.task_pane.header.groups["emails"]
    assert g.present and g.is_open and not g.isHidden()
    words = " ".join(g.text().replace("￼", " ").split())
    assert words.startswith("Email conversations 2 · 3 emails New T-mail") and "Crane booking 2 ↗ Rigging plan" in words
    assert "Show all" not in words
    browse.go_task("T000002")  # no email on it, nor under it
    assert not browse.task_pane.header.groups["emails"].present


def test_a_conversation_opens_its_page_with_its_bar(browse, two):
    browse.go_task(INSTALLATION)
    browse.on_link(QUrl(f"conv:{INSTALLATION}/{GUID}"))
    assert browse.sel == ("conversation", f"{INSTALLATION}/{GUID}") and browse.detail_stack.currentIndex() == 0
    words = browse.page.toPlainText()
    assert words.startswith("‹ Installation\nCrane booking") and "Newest" in words
    buttons = bar(browse)
    assert {"Open in Outlook", "Reply all"} <= set(buttons) and buttons["Open in Outlook"].isEnabled()
    browse.refresh()  # the page stays, as long as the conversation is there
    assert browse.sel == ("conversation", f"{INSTALLATION}/{GUID}")
    browse.on_link(QUrl(f"task:{INSTALLATION}"))  # its first line goes back
    assert browse.sel == ("task", INSTALLATION)


def test_open_in_outlook_shows_the_email_by_its_place(browse, two, monkeypatch):
    shown = []
    monkeypatch.setattr(outlook, "show_email", lambda entry, store: shown.append((entry, store)) or True)
    started = []
    monkeypatch.setattr(conversation_page, "STARTER", started.append)
    browse.on_link(QUrl(f"outlook:{two[0]}:0"))
    assert shown == [("E1", "S1")] and started == [] and browse.said[-1] == ("Opened “Crane booking” in Outlook.", False)


def test_open_in_outlook_takes_the_saved_msg_when_outlook_cant_find_it(browse, ctx, two, monkeypatch):
    monkeypatch.setattr(outlook, "show_email", lambda entry, store: False)
    started = []
    monkeypatch.setattr(conversation_page, "STARTER", started.append)
    browse.on_link(QUrl(f"outlook:{two[0]}:0"))
    assert len(started) == 1 and started[0].endswith("email.msg") and browse.said[-1][1] is False

    def refuse(entry, store):
        raise outlook.OutlookError("Outlook isn't open.")

    monkeypatch.setattr(outlook, "show_email", refuse)
    browse.on_link(QUrl(f"outlook:{two[1]}:0"))  # no place kept: straight to its .msg
    assert len(started) == 2 and browse.said[-1] == ("Opened “RE: Crane booking” in Outlook, from its saved .msg.", False)


def test_reply_all_and_new_t_mail_from_the_page(browse, ctx, two, monkeypatch):
    calls = []
    monkeypatch.setattr(outlook, "reply_all", lambda entry, store, saved: calls.append(entry) or outlook.Opened(index(2).hex().upper(), "place"))
    monkeypatch.setattr(outlook, "new_t_mail", lambda now: calls.append("new") or outlook.Opened(conversations.new_index(now, OTHER), "saved"))
    browse.go_task(RIGGING)
    browse.on_link(QUrl(f"conv:{RIGGING}/{GUID}"))
    bar(browse)["Reply all"].click()  # the newest email that Reply all can find
    browse.on_link(QUrl(f"tmail:{RIGGING}"))
    m = Model(ctx.conn)
    assert calls == ["", "new"] and [(t.task, t.kind, t.reply_capture) for t in m.t_mails] == [(RIGGING, "reply", two[1]), (RIGGING, "new", None)]


def test_show_all_conversations(browse, ctx):
    for n in range(6):
        e = msg.read(build(FakeEmail(subject=f"Topic {n}", conversation_index=b"\x01" + bytes(5) + bytes([n + 1]) * 16,
                                     message_id=f"<t{n}@example.com>", sent=datetime(2026, 10, 1 + n, 9, 0).astimezone())))
        captured(ctx, e, INSTALLATION, datetime(2026, 10, 1 + n, 9, 30))
    browse.go_task(INSTALLATION)
    g = browse.task_pane.header.groups["emails"]
    assert "Show all 6 conversations" in " ".join(g.text().split())
    browse.on_link(QUrl("fold:conversations"))
    assert "Show fewer" in browse.task_pane.header.groups["emails"].text() and browse.state.conversations
