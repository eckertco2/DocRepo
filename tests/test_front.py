"""Bringing a window to the front, restored if it was minimized (release 5.106, decision 405): the browse tool, Find files,
file search and the capture window, opened by a hotkey, a wheel or a link."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget  # noqa: E402

from docrepo import capacity, db, hotkey, prompts  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.front import bring_to_front, restored_state  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
MIN, MAX = Qt.WindowState.WindowMinimized, Qt.WindowState.WindowMaximized


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_restoring_takes_off_minimized_and_keeps_maximized():
    assert not restored_state(MIN) & MIN
    state = restored_state(MIN | MAX)
    assert state & MAX and not state & MIN and state & Qt.WindowState.WindowActive


def test_a_minimized_window_comes_back(qapp):
    w = QWidget()
    w.show()
    w.setWindowState(MIN)
    assert w.isMinimized()
    bring_to_front(w)
    assert w.isVisible() and not w.isMinimized()
    w.close()


def test_a_maximized_window_comes_back_maximized(qapp):
    w = QWidget()
    w.show()
    w.setWindowState(MAX | MIN)
    bring_to_front(w)
    assert w.isMaximized() and not w.isMinimized()
    w.close()


def test_a_hidden_window_left_minimized_opens_restored(qapp):
    """Closing a window only hides it; one closed while minimized must not open minimized."""
    w = QWidget()
    w.setWindowState(MIN)
    bring_to_front(w)
    assert w.isVisible() and not w.isMinimized()
    w.close()


@pytest.fixture
def app(qapp, data_root, fs, monkeypatch):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, now=lambda: NOW)
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    a = CaptureApp(qapp, ctx)
    yield a
    for view in a.browse.task_views.values():
        view.hide()
    for w in (a.wheels.window, a.window, a.browse):
        w.hide()
    a.tray.hide()
    qapp.removeNativeEventFilter(a.filter)
    conn.close()


def test_the_browse_tools_hotkey_restores_it(app):
    app.show_browse()
    app.browse.setWindowState(MAX | MIN)
    app.hotkey_actions[hotkey.HOTKEY_IDS["browse_hotkey"]]()
    assert app.browse.isVisible() and not app.browse.isMinimized() and app.browse.isMaximized()


def test_find_files_comes_back_when_its_opened_again(app):
    app.browse.open_task_view("T000008")
    view = app.browse.task_views["T000008"]
    view.setWindowState(MIN)
    app.browse.open_task_view("T000008")
    assert view.isVisible() and not view.isMinimized()


def test_a_link_in_find_files_restores_the_browse_tool(app):
    app.browse.open_task_view("T000008")
    view = app.browse.task_views["T000008"]
    app.browse.setWindowState(MIN)
    view.open_task_page()
    assert app.browse.isVisible() and not app.browse.isMinimized()


def test_a_capture_hotkey_restores_the_capture_window(app):
    app.window.show_capture()
    app.window.setWindowState(MIN)
    app.hotkey_actions[hotkey.HOTKEY_IDS["note_hotkey"]]()
    assert app.window.isVisible() and not app.window.isMinimized()
