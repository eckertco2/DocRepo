"""The pinned capture window (mods log round 3, M0053 and M0054; decisions 53 and 54), driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, Qt, QUrl  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
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
    assert pin.text.document() is window.content.document() and pin.task_button.text() == "Installation"
    assert pin.status.text() == "Nothing added yet" and not pin.desc_row.isVisibleTo(pin)
    pin.text.insertPlainText(" Guards fitted.")
    assert window.content.toPlainText() == "Walkdown done. Guards fitted."
    (tmp_path / "Pump datasheet.pdf").write_text("x")
    window.dropped("files", [str(tmp_path / "Pump datasheet.pdf")])
    window.dropped("links", ["https://example.com/sites/maintenance/seal-kit"])
    assert pin.status.text() == "1 file, 1 link added"
    window.dropped("files", [str(tmp_path)])  # a folder: the pinned window says so, and stays
    assert window.pinned and pin.message.isVisibleTo(pin) and "is a folder" in pin.message.text() and not pin.status.isVisibleTo(pin)
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


def test_the_pinned_window_picks_types_paths_and_descriptions(window, tmp_path, monkeypatch):
    """Mods log round 3 (M0062, M0064): the capture types, a typed or pasted path or link, and each file's description,
    one at a time, all in the same 320 x 236 px; the task picker opens under its own button."""
    from docrepo.ui import pin_window

    window.set_task("T000008")
    window.pin()
    pin = window.pin_window
    assert pin.size().width() == pin_window.WIDTH and pin.size().height() == pin_window.HEIGHT
    pin.type_boxes["new_task"].click()
    assert window.types == {"new_task"} and pin.type_boxes["new_task"].isChecked() and not pin.type_boxes["note"].isChecked()
    pin.type_boxes["new_task"].click()
    window.set_task(None)
    pin.type_boxes["update"].click()  # Update needs a task: the pinned window says so
    assert "update" not in window.types and pin.message.text() == "Pick a task to update first."
    (tmp_path / "Pump datasheet.pdf").write_text("x")
    pin.path.setText(f'"{tmp_path / "Pump datasheet.pdf"}"')  # File Explorer's Copy as path, with its quotes
    pin.add_typed()
    assert pin.path.text() == "" and [e.row.name for e in window.files] == ["Pump datasheet.pdf"]
    assert pin.desc_row.isVisibleTo(pin) and pin.desc.placeholderText().startswith("Pump datasheet.pdf:")
    pin.desc.setText("Seal kit datasheet")
    pin.desc.textEdited.emit("Seal kit datasheet")
    assert window.files[0].desc.text() == "Seal kit datasheet"  # the full window's own row
    pin.path.setText("https://example.com/sites/maintenance/seal-kit")
    pin.add_typed()
    assert pin.desc.text() == "" and pin.desc.placeholderText().startswith("example.com:")  # the new one shows
    assert pin.prev_button.isEnabled() and not pin.next_button.isEnabled()
    pin._step(-1)
    assert pin.desc.text() == "Seal kit datasheet"
    pin.path.setText(str(tmp_path / "nothing here.pdf"))
    pin.add_typed()
    assert "can't be found" in pin.message.text() and pin.path.text().endswith("nothing here.pdf")  # kept, to fix
    opened = []
    monkeypatch.setattr(window, "_open_picker", lambda anchor=None: opened.append(anchor))
    pin.task_button.click()
    assert opened == [pin.task_button]
    monkeypatch.setattr(window, "add_outlook", lambda: opened.append("outlook"))
    pin.outlook_button.click()
    assert opened[-1] == "outlook"


# ---- the text's width (item 75): the two boxes share one document, and a document has one width ----
LONG = "Walkdown of the pump guards, with enough words in it to wrap across the box somewhere along the way"


def _settle():
    for _ in range(4):
        QApplication.processEvents()


def _fills(box) -> bool:
    """The text is laid out at the width of the box it's shown in."""
    _settle()
    return box.document().pageSize().width() == box.viewport().width()


def _type_and_check(box, lines: int, words: str) -> None:
    box.setFocus()
    for n in range(lines):
        QTest.keyClicks(box, words)
        QTest.keyClick(box, Qt.Key.Key_Return)
        assert _fills(box), f"line {n + 1} of {words[:12]!r}: laid out at {box.document().pageSize().width()} in a box {box.viewport().width()} wide"


def test_the_text_stays_as_wide_as_the_box_after_a_pin(window):
    """Pinned once, the hidden small box used to set the text's width whenever its scroll bar came or went: a few lines in,
    the full window's text shrank to about a third of its box, until the box's own width next changed."""
    window.pin()
    window.unpin()
    assert _fills(window.content)  # at once
    _type_and_check(window.content, 14, "A short line")
    _type_and_check(window.content, 14, LONG)


def test_the_text_stays_as_wide_as_a_tall_box_too(window):
    window.pin()
    window.unpin()
    window.toggle_expand()  # room for lines before the box needs its own scroll bar, so nothing brings the width back
    window.resize(window.width() + 40, window.height())
    assert _fills(window.content)
    _type_and_check(window.content, 14, "A short line")
    window.toggle_expand()
    assert _fills(window.content)


def test_the_text_fits_the_pinned_box_with_lines_already_in_it(window):
    """The other way round: the hidden full box used to set the width, so the text ran off the small box's right edge."""
    _type_and_check(window.content, 3, LONG)
    window.pin()
    pin = window.pin_window
    assert _fills(pin.text) and pin.text.horizontalScrollBar().maximum() == 0
    _type_and_check(pin.text, 4, LONG)
    assert pin.text.horizontalScrollBar().maximum() == 0
    window.unpin()
    assert _fills(window.content)
    _type_and_check(window.content, 3, LONG)
    window.toggle_pin()
    assert _fills(pin.text) and pin.text.horizontalScrollBar().maximum() == 0


def test_the_next_capture_after_a_save_or_esc_fills_the_box(window):
    window.set_task("T000008")
    window.content.setPlainText("Crane inspection passed.")
    window.pin()
    window.save()
    window.show_capture()
    assert _fills(window.content)
    _type_and_check(window.content, 8, LONG)
    window.pin()
    window.hide_pinned()  # Esc
    window.content.clear()  # an emptied document is a change while both boxes are hidden
    window.show_capture()
    assert _fills(window.content)
    _type_and_check(window.content, 8, "A short line")


def test_a_box_comes_back_with_its_scroll_bar_working(window):
    """A hidden box's scroll bar is held as it is (never hidden for good), and a box shown again follows its text."""
    window.pin()
    window.unpin()
    _type_and_check(window.content, 20, LONG)
    assert window.content.verticalScrollBar().isVisible()
    window.pin()
    assert window.pin_window.text.verticalScrollBar().isVisible()
    window.unpin()
    window.content.clear()
    assert _fills(window.content) and not window.content.verticalScrollBar().isVisible()


def test_a_long_problem_takes_two_lines(window):
    """A problem longer than two lines (Outlook's refusal, say) is cut with "…" on the pinned window, all of it in its
    tooltip, and the window stays the same size."""
    from docrepo import outlook
    from docrepo.save import EmailItem

    window.pin()
    pin = window.pin_window
    note = outlook.refused_note([EmailItem("Revised guard delivery", "", "2026-10-08 09:30", "", "", refused=("Body", "SenderName", "To"))])
    pin.show_message(note)
    assert pin.message.text().endswith("…") and pin.message.toolTip() == note and not pin.status.isVisibleTo(pin)
    assert note.startswith(pin.message.text()[:-1])  # cut at a word; where depends on the font
    pin.show_message("here.pdf can't be found.")
    assert pin.message.text() == "here.pdf can't be found."
    assert (pin.width(), pin.height()) == (320, 236)
