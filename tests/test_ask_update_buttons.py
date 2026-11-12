"""Release 5.125, Ask for an update in the windows, offscreen with a fake Outlook (the cold-eyes plan's decisions 481 to
486): on New T-mail's arrow and on a row's right-click menu in Waiting on others, kept as a T-mail of kind ``ask``, its
"asked" on the rows and the status card until a capture lands, and the words on the clipboard when Outlook won't take
them. Every name, address and email here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import captures, conversations, outlook  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE, LINE_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
RIGGING, SEAL = "T000012", "T000007"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)


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
    """outlook.ask_t_mail, recorded: it opens the ask with a made-up index, To filled and the words in by the editor,
    unless ``how["words"]`` says otherwise."""
    calls: list[tuple] = []
    how = {"words": "editor"}

    def ask(now, to, subject, words):
        calls.append((now, tuple(to), subject, words))
        return outlook.AskOpened(outlook.Opened(conversations.new_index(now, GUID), "saved"), bool(to), how["words"])

    monkeypatch.setattr(outlook, "ask_t_mail", ask)
    return calls, how


def bar(browse) -> dict:
    lay = browse.actions_layout
    out = {}
    for w in (lay.itemAt(i).widget() for i in range(lay.count())):
        for b in [w] if isinstance(w, QPushButton) else (w.findChildren(QPushButton) if w is not None else []):
            out[b.text() or b.accessibleName()] = b
    return out


def row(browse, task_id: str):
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", task_id))


def ask_action(menu):
    return next((a for a in menu.actions() if a.text() == "Ask for an update"), None)


def test_the_arrow_asks_for_an_update_and_keeps_it_on_the_task(browse, fake_outlook):
    calls, _ = fake_outlook
    browse.select("task", RIGGING)
    menu = bar(browse)["More T-mails"].menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Reply all to the latest email", "Ask for an update"]  # Reply all stays first, greyed with no email
    ask = ask_action(menu)
    assert ask.isEnabled() and ask.toolTip().startswith("To Mike Ortiz. A new email in Outlook to the people on this task")
    ask.trigger()
    ((now, to, subject, words),) = calls
    assert now == NOW and to == ("mike.ortiz@example.com",) and subject == "Rigging plan: where does it stand?"
    assert words.startswith("Hi Mike,\n\nWhere does the rigging plan stand? The last I have (5 Oct): ") and words.endswith("\n\nThanks,")
    t = Model(browse.conn).t_mails[-1]
    assert (t.task, t.kind, t.conversation, t.opened) == (RIGGING, "ask", GUID.hex().upper(), "2026-10-08 14:10:00")
    assert browse.status.text() == ("Opened Ask for an update on Rigging plan in Outlook. To Mike Ortiz. "
                                    "When you capture the reply, it'll go to Rigging plan.")
    assert not browse.status.property("error")
    # The status card says so, until a capture lands on the task.
    header = browse.task_pane.header
    assert header.status_asked.isVisibleTo(header) and header.status_asked.text() == "· asked today"
    assert header.status_asked.toolTip().startswith("You asked for an update on Thu 8 Oct.")
    captures.add_capture(browse.conn, saved="2026-10-08 15:00:00", source="typed", types=["note"], title="Mike's answer", task=RIGGING)
    browse.refresh()
    assert not header.status_asked.isVisibleTo(header)


def test_waiting_on_others_has_it_on_a_rows_menu_and_says_asked(browse, fake_outlook):
    calls, _ = fake_outlook
    browse.set_view("waiting")
    menu = browse.tree.row_menu(row(browse, RIGGING))
    first = next(a for a in menu.actions() if not a.isSeparator())
    assert first.text() == "Ask for an update"
    first.trigger()
    assert calls[-1][1] == ("mike.ortiz@example.com",)
    assert browse.view == "waiting"
    assert row(browse, RIGGING).data(0, LINE_ROLE).context == "asked today · Mike Ortiz"  # before the person waited on
    # The task tree's menu has no Ask for an update; its row says asked, as every list's does.
    browse.set_view("tasks")
    browse.open.update(Model(browse.conn).tasks)
    browse.render_list()
    assert ask_action(browse.tree.row_menu(row(browse, RIGGING))) is None
    assert "asked today" in row(browse, RIGGING).data(0, LINE_ROLE).muted


def test_a_closed_task_isnt_asked_about(browse, fake_outlook):
    browse.select("task", SEAL)  # Order spare mechanical seal is closed
    assert Model(browse.conn).task(SEAL).state == "Closed"
    assert ask_action(bar(browse)["More T-mails"].menu()) is None


def test_words_outlook_wont_take_go_on_the_clipboard(browse, fake_outlook):
    calls, how = fake_outlook
    how["words"] = ""
    QGuiApplication.clipboard().setText("")
    browse.select("task", RIGGING)
    ask_action(bar(browse)["More T-mails"].menu()).trigger()
    assert QGuiApplication.clipboard().text() == calls[-1][3]
    assert "Outlook didn't take the words, so they're on the clipboard: paste them above your signature." in browse.status.text()
    assert browse.status.property("error")


def test_it_says_why_when_outlook_isnt_there(browse, monkeypatch):
    def refuse(now, to, subject, words):
        raise outlook.OutlookError("Outlook isn't open. Open classic Outlook, select the email, and try again.")

    monkeypatch.setattr(outlook, "ask_t_mail", refuse)
    browse.select("task", RIGGING)
    ask_action(bar(browse)["More T-mails"].menu()).trigger()
    assert browse.status.text().startswith("Ask for an update: Outlook isn't open") and browse.status.property("error")
    assert Model(browse.conn).t_mails == []
