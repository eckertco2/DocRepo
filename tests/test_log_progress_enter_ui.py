"""Release 5.164, Log progress: the send and Enter, offscreen (the design workspace's
``docs/mods/log-progress-whole-plan.md``, decisions 751 to 754): Enter in an empty Waiting on logs, Enter on Cancel
cancels, each stop said in the caution colour by its row with the cursor put there, a busy database said and nothing
kept, two Enters keeping one Update, the window gone before Outlook is asked, and the draft let go of once sent. A fake
Outlook draft stands in for Outlook. Every name here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3  # noqa: E402
import types  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import outlook, progress, sent_watch, tasks, waits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import EmailItem  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.log_progress import LogProgress  # noqa: E402

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
    app = types.SimpleNamespace(ctx=ctx, progress_logged=lambda done, text, trouble: said.append((text, trouble)))
    w = LogProgress(app)
    w.said = said
    w.calls = []

    def send(draft):
        w.calls.append(("send", draft.subject, w.isVisible(), dict(sent_watch.drafts(conn))))

    monkeypatch.setattr(outlook, "send_draft", send, raising=False)
    monkeypatch.setattr(outlook, "show_draft", lambda draft: w.calls.append(("show", draft.subject, w.isVisible(), {})) or True, raising=False)
    yield w
    QApplication.processEvents()
    w.picker.hide()
    w.hide()
    w.deleteLater()
    QApplication.processEvents()


def draft(subject: str = "Crane quote", to: str = "Mike Ortiz <mike.ortiz@example.com>"):
    """A new email in its own window, saved to Drafts for its place: Outlook gave it no conversation index."""
    copy = EmailItem(subject=subject, sender="", sent="", to=to, body="", conversation_index="")
    return types.SimpleNamespace(item=object(), inline=False, subject=subject, index="", entry_id="D1", store_id="S1", copy=copy)


def updates(conn) -> int:
    return sum(1 for c in Model(conn).captures.values() if c.task == RIGGING and "update" in c.types)


def enter(widget) -> None:
    QTest.keyClick(widget, Qt.Key.Key_Return)


# ================= Enter always answers (decision 753) =================
def test_enter_in_an_empty_waiting_on_logs(window):
    """The reported fault: after a person is added by Enter the cursor stays in Waiting on, and the next Enter did nothing."""
    conn = window.ctx.conn
    window.open_for(None, task=RIGGING)
    window.line.setText("Asked Mike for the crane vendor's quote")
    window.who.setText("Mike")
    enter(window.who)  # words in the box: Enter adds the person, as before
    assert window.people == [MIKE] and window.isVisible() and updates(conn) == 0
    enter(window.who)  # the box empty: Enter logs
    assert not window.isVisible() and updates(conn) == 1
    w = waits.current(Model(conn), RIGGING)
    assert w is not None and w.on == (MIKE,)
    assert window.said[-1][0].startswith("Logged on Rigging plan: waiting on Mike")


def test_enter_on_cancel_cancels(window):
    conn = window.ctx.conn
    window.open_for(None, task=RIGGING)
    window.line.setText("Not this time")
    enter(window.cancel)
    assert not window.isVisible() and updates(conn) == 0 and window.said == []


def test_enter_on_the_line_logs(window):
    window.open_for(None, task=RIGGING)
    window.line.setText("Called the crane vendor")
    enter(window.line)
    assert not window.isVisible() and window.said[-1] == ("Logged on Rigging plan.", False)


@pytest.mark.parametrize("what", ["line", "who", "closed"])
def test_each_stop_is_said_by_its_row_in_the_caution_colour(window, what):
    conn = window.ctx.conn
    if what == "closed":
        tasks.update_task(conn, window.ctx.settings, RIGGING, at=NOW, via="test", state="Closed")
    window.open_for(None, task=RIGGING)
    if what != "line":
        window.line.setText("Asked about the lift points")
    if what == "who":
        window.pick_state(progress.WAITING)
    window.submit()
    key = {"line": "content", "who": "who", "closed": "task"}[what]
    problem = window.problems[key]
    assert window.isVisible() and not problem.isHidden() and problem.objectName() == "progressProblem"
    assert {"content": "Say in a line", "who": "Who are you waiting on?", "closed": "is closed"}.get(key, "is closed") in problem.text()
    assert all(p.text() == "" and (p.isHidden() or not k) for k, p in window.problems.items() if k != key)  # one row says it
    if window.isActiveWindow():  # offscreen, focus follows only an active window
        assert window.focusWidget() is {"content": window.line, "who": window.who, "task": window.task_button}[key]
    assert updates(conn) == 0
    window.line.setText("Asked about the lift points")
    window.who.setText("Mike")
    window.add_person()
    assert window.problems["content"].isHidden()  # opened again or fixed, the words go


def test_the_caution_style_is_on_the_problem_line():
    from docrepo.ui import tokens
    from docrepo.ui.style import CLASSIC_STYLE

    assert "QLabel#progressProblem" in CLASSIC_STYLE and "QLabel#progressProblem { color: $caution" in tokens._QSS.template


def test_a_busy_database_says_so_and_keeps_nothing(window, monkeypatch, caplog):
    conn = window.ctx.conn

    def busy(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(progress, "save_capture", busy)
    window.open_for(draft(), task=RIGGING)
    window.line.setText("Asked Mike for the crane vendor's quote")
    window.submit()
    assert window.isVisible() and window.problems[""].text() == "Nothing was kept: the database is busy. Try again."
    assert not window.problems[""].isHidden() and window.enter.isEnabled() and window.enter.text() == "Send and log"
    assert updates(conn) == 0 and waits.current(Model(conn), RIGGING) is None and window.calls == [] and window.said == []
    assert "crane vendor" not in caplog.text  # logged without the capture's words


def test_any_other_error_is_caught_and_said(window, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("T000099")

    monkeypatch.setattr(progress, "log_progress", broken)
    window.open_for(None, task=RIGGING)
    window.line.setText("Asked Mike")
    window.submit()
    assert window.isVisible() and window.problems[""].text() == "Nothing was kept (KeyError). Try again."


def test_two_enters_keep_one_update(window, monkeypatch):
    conn = window.ctx.conn

    def busy(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(waits, "start", busy)
    window.open_for(None, task=RIGGING)
    window.line.setText("Asked Mike for the crane vendor's quote")
    window.who.setText("Mike")
    window.add_person()
    window.submit()
    assert window.isVisible() and updates(conn) == 1 and waits.current(Model(conn), RIGGING) is None
    assert window.problems["content"].text() == "The update was kept. The wait wasn't started: press Enter to try again."
    monkeypatch.undo()
    window.submit()
    assert not window.isVisible() and updates(conn) == 1 and waits.current(Model(conn), RIGGING) is not None


def test_while_it_runs_the_button_says_logging_and_takes_no_second_press(window, monkeypatch):
    seen = []
    real = progress.log_progress

    def slow(*args, **kwargs):
        seen.append((window.enter.text(), window.enter.isEnabled()))
        window.submit()  # a second press while the first runs does nothing
        return real(*args, **kwargs)

    monkeypatch.setattr(progress, "log_progress", slow)
    window.open_for(None, task=RIGGING)
    window.line.setText("Called the crane vendor")
    window.submit()
    assert seen == [("Logging…", False)] and updates(window.ctx.conn) == 1
    window.open_for(None, task=RIGGING)
    assert window.enter.isEnabled() and window.enter.text() == "Log"


# ================= the send (decisions 751 and 752) =================
def test_the_window_goes_before_outlook_is_asked_and_the_draft_is_let_go(window):
    window.open_for(draft(), task=RIGGING)
    window.line.setText("Asked Mike for the crane vendor's quote")
    window.submit()
    (what, subject, visible, kept), = window.calls
    assert (what, subject, visible) == ("send", "Crane quote", False)  # hidden first
    # The kept draft was marked as sent by DocRepo before Send, so the minute's look never fetches it on its way out.
    assert [d.how for d in kept.values()] == [sent_watch.BY_DOCREPO]
    assert window.draft is None and window.email is None  # the window holds nothing of Outlook's
    assert window.said[-1][0].startswith("Sent, and logged on Rigging plan")


def test_a_refused_send_keeps_the_draft_watched(window, monkeypatch):
    conn = window.ctx.conn

    def refuse(draft):
        raise outlook.OutlookError("operation aborted")

    monkeypatch.setattr(outlook, "send_draft", refuse, raising=False)
    window.open_for(draft(), task=RIGGING)
    window.line.setText("Asked Mike again")
    window.submit()
    assert [c[:3] for c in window.calls] == [("show", "Crane quote", False)] and window.said[-1][1]
    assert [d.how for d in sent_watch.drafts(conn).values()] == [""]  # the owner sends it: watched as before
    assert window.draft is None
