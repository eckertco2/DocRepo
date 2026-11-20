"""The message at the bottom of the browse window (release 5.182, the redesign's decision 853, the status strip goes),
driven offscreen: a plain message for 4 to 9 seconds by its length, one with Undo for Undo's ten seconds and Undo offered
once, an error that stays with its close button, its place at the bottom centre, the pointer holding it, and the
keyboard never taken. The names the rest of the code reads (``status``, ``_status_timer``, ``_status_link``) stay."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF  # noqa: E402
from PySide6.QtGui import QEnterEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.config import Settings  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.state_menu import UNDO_MS  # noqa: E402
from docrepo.ui.toast import LONGEST_MS, MARGIN, MAX_TEXT, PLAIN_MS, Toast, shown_for  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW), None)
    w.show_browse()
    w.resize(1440, 900)
    QApplication.processEvents()
    yield w
    w.hide()
    w.deleteLater()


def test_the_names_stay(browse):
    assert isinstance(browse.toast, Toast) and browse.status is browse.toast.label
    assert browse._status_timer is browse.toast.timer and browse.toast.parentWidget() is browse


def test_a_plain_message(browse):
    browse.say("Saved.")
    t = browse.toast
    assert not t.isHidden() and browse.status.text() == "Saved."
    assert t.undo.isHidden() and t.close_button.isHidden() and not t.offers_undo()
    assert browse._status_timer.isActive() and browse._status_timer.interval() == PLAIN_MS
    browse.say("x" * 200)
    assert browse._status_timer.interval() == LONGEST_MS
    assert shown_for("x" * 70) == PLAIN_MS + 500
    browse.say("")
    assert t.isHidden() and browse.status.text() == ""


def test_an_error_stays_until_dismissed(browse):
    browse.say("Outlook isn't running.", error=True)
    t = browse.toast
    assert browse.status.property("error") and t.property("error")
    assert not browse._status_timer.isActive() and not t.close_button.isHidden()
    t.close_button.click()
    assert t.isHidden() and browse.status.text() == "" and not browse.status.property("error")
    browse.say("Outlook isn't running.", error=True)
    browse.say("Saved.")  # the next thing said replaces it
    assert not browse.status.property("error") and t.close_button.isHidden() and browse._status_timer.isActive()


def test_undo_once(browse):
    ran = []
    browse.say_undo("Closed: Rigging plan.", lambda: ran.append(1))
    t = browse.toast
    assert t.offers_undo() and browse._undo is not None and browse._status_timer.interval() == UNDO_MS
    assert browse.status.text() == "Closed: Rigging plan."
    t.undo.click()
    assert ran == [1] and t.undo.isHidden() and browse._undo is None
    browse._status_link("undo")
    assert ran == [1]


def test_the_timeout_takes_it_away(browse):
    browse.say_undo("Closed: Rigging plan.", lambda: None)
    browse._status_timer.timeout.emit()
    assert browse.toast.isHidden() and browse.status.text() == "" and browse._undo is None


def test_its_place(browse):
    t = browse.toast
    browse.say("Moved under Installation.")
    QApplication.processEvents()
    assert abs(t.x() + t.width() // 2 - browse.width() // 2) <= 1
    assert t.y() + t.height() == browse.height() - MARGIN
    browse.resize(1024, 700)
    QApplication.processEvents()
    assert abs(t.x() + t.width() // 2 - browse.width() // 2) <= 1 and t.y() + t.height() == browse.height() - MARGIN
    one_line = t.height()
    browse.say("Rigging plan moved from under Installation to Reactor impeller upgrade. " * 4)
    QApplication.processEvents()
    assert browse.status.wordWrap() and browse.status.width() <= MAX_TEXT
    assert t.height() > one_line and t.y() + t.height() == browse.height() - MARGIN  # it grows upward


def test_it_never_takes_the_keyboard(browse):
    browse.activateWindow()
    browse.tree.setFocus()
    QApplication.processEvents()
    before = QApplication.focusWidget()
    browse.say_undo("Closed: Rigging plan.", lambda: None)
    QApplication.processEvents()
    assert QApplication.focusWidget() is before
    for w in (browse.toast, browse.toast.undo, browse.toast.close_button, browse.status):
        assert w.focusPolicy().name == "NoFocus"


def test_the_pointer_holds_it(browse):
    browse.say("Saved.")
    t = browse.toast
    QApplication.sendEvent(t, QEnterEvent(QPointF(4, 4), QPointF(4, 4), QPointF(4, 4)))
    assert not browse._status_timer.isActive()
    QApplication.sendEvent(t, QEvent(QEvent.Type.Leave))
    assert browse._status_timer.isActive() and browse._status_timer.interval() == PLAIN_MS
