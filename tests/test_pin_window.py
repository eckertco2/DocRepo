"""The pinned capture window (mods log round 3, M0053 and M0054; decisions 53 and 54), driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, hotkey, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow, read_drop  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    messages: list[tuple[str, str]] = []
    ctx = AppContext(conn, data_root, fs, settings, notify=lambda t, m: messages.append((t, m)), now=lambda: NOW)
    w = CaptureWindow(ctx)
    w.messages = messages  # type: ignore[attr-defined]
    w.show_capture()
    yield w
    w.hide()
    if w.pin_window is not None:
        w.pin_window.hide()
        w.pin_window.deleteLater()
    w.deleteLater()
    conn.close()


def test_a_web_link_drop_is_a_link_where_the_window_asks_for_one():
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/sites/maintenance/seal-kit")])
    assert read_drop(mime) == ("", [])  # the content text box types it in, as before
    assert read_drop(mime, links=True) == ("links", ["https://example.com/sites/maintenance/seal-kit"])


def test_pinning_keeps_the_capture(window, tmp_path):
    """Pin shrinks the capture to the small window, which shows the same text and takes drops; the main hotkey's path
    (show_capture) brings the full window back on the same capture."""
    window.set_task("T000008")
    window.content.setPlainText("Walkdown done.")
    window.pin()
    pin = window.pin_window
    assert window.pinned and not window.isVisible() and pin.isVisible()
    assert pin.text.document() is window.content.document() and pin.title.text() == "Installation"
    assert pin.drop.status.text() == "Nothing added yet"
    pin.text.insertPlainText(" Guards fitted.")
    assert window.content.toPlainText() == "Walkdown done. Guards fitted."
    (tmp_path / "Pump datasheet.pdf").write_text("x")
    window.dropped("files", [str(tmp_path / "Pump datasheet.pdf")])
    window.dropped("links", ["https://example.com/sites/maintenance/seal-kit"])
    assert pin.drop.status.text() == "1 file, 1 link added"
    window.dropped("files", [str(tmp_path)])  # a folder: the pinned window says so, and stays
    assert window.pinned and pin.message.isVisibleTo(pin) and "is a folder" in pin.message.text()
    window.dropped("files", [str(tmp_path / "Pump datasheet.pdf")])  # the next drop clears it
    assert not pin.message.isVisibleTo(pin)
    window.unpin()
    assert not window.pinned and window.isVisible() and not pin.isVisible()
    assert window.task == "T000008" and len(window.files) == 2 and "Guards fitted" in window.content.toPlainText()
    window.toggle_pin()  # F12 pins it again, and again brings it back
    assert window.pinned
    window.toggle_pin()
    assert not window.pinned and window.isVisible()


def test_saving_from_the_pinned_window(window):
    """Ctrl+Enter saves from it. When Save can't, the full window opens with the problem; Esc hides it, keeping the draft."""
    window.set_type("new_task", True)
    window.content.setPlainText("")
    window.pin()
    window.save()  # a new task needs a title
    assert not window.pinned and window.isVisible() and window.error.isVisibleTo(window)
    window.set_type("note", True)
    window.set_task("T000008")
    window.content.setPlainText("Crane inspection passed.")
    window.pin()
    window.hide_pinned()  # Esc
    assert not window.pinned and not window.pin_window.isVisible() and window.content.toPlainText() == "Crane inspection passed."
    window.pin()
    window.save()
    assert window.messages[-1][0] == "Saved" and not window.pinned and not window.isVisible() and not window.pin_window.isVisible()


def test_the_pin_hotkey_is_off_until_set():
    assert ("pin_hotkey", "Pin the capture window, or bring it back") in hotkey.HOTKEYS
    assert Settings().pin_hotkey == "" and "pin_hotkey" not in hotkey.SUGGESTED  # Use the suggested keys leaves it alone
