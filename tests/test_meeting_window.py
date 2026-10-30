"""Items and meeting notes in the capture window and the browse tool (release 5.8), driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import capacity, db, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import DRAFT_FILE, CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    messages: list[tuple[str, str]] = []
    context = AppContext(conn, data_root, fs, settings, notify=lambda t, m: messages.append((t, m)), now=lambda: NOW)
    context.messages = messages  # type: ignore[attr-defined]
    yield context
    conn.close()


@pytest.fixture
def window(ctx):
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    w.hide()
    w.deleteLater()


def type_text(window, text: str) -> None:
    window.content.setFocus()
    cursor = window.content.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    window.content.setTextCursor(cursor)
    window.content.insertPlainText(text)


def test_items_are_read_as_you_type(window):
    window.set_task("T000008")
    window.content.setPlainText("Walkdown done.\n- @Tom check the guards\n- **decision, rails go red.")
    window.draft_dirty = False
    window.read_items()
    assert not window.draft_dirty and not window._items_timer.isActive()  # the colours aren't a change to the text
    assert [c.tick.text() for c in window.item_cards.cards] == ["Task", "Decision"]
    assert window.item_cards.count.text() == "Save makes 1 task and 1 decision"
    assert "From its items it makes 1 task and 1 decision." in window.does.text()
    assert window.highlighter.kinds == {1: "task", 2: "decision"}
    # A card's changes go with the draft, and stay.
    window.item_cards.cards[0].title.textEdited.emit("Check the guards and rails")
    window.item_cards.cards[1].tick.setChecked(False)
    draft = window.draft()
    assert draft.item_overrides == {"0": {"title": "Check the guards and rails"}, "1": {"off": True}}
    assert [c.title.text() for c in window.item_cards.cards] == ["Check the guards and rails", "Rails go red"]
    window.save()
    m = Model(window.ctx.conn)
    made = [c for c in m.captures.values() if c.from_notes]
    assert [(c.item, c.title) for c in made] == [("task", "Check the guards and rails")]


def test_the_at_and_hash_lists(window):
    window.set_task("T000008")
    window.content.setFocus()
    QApplication.processEvents()
    type_text(window, "- @ty")
    assert window.ref_popup.isVisibleTo(window) and window.ref_popup.item(0).text().startswith("Tyler Nguyen")
    assert window.content.list_keys(Qt.Key.Key_Return)  # Enter picks
    assert window.content.toPlainText() == "- @Tyler Nguyen " and window.ref_ids == {"@tyler nguyen": "P005"}
    type_text(window, "book the alignment contractor #rigg")
    assert window.ref_popup.isVisibleTo(window) and window.ref_popup.item(0).text().startswith("Rigging plan")
    assert window.content.list_keys(Qt.Key.Key_Escape) and not window.ref_popup.isVisibleTo(window) and window.isVisible()
    type_text(window, "i")
    assert window.content.list_keys(Qt.Key.Key_Tab)
    assert window.content.toPlainText() == "- @Tyler Nguyen book the alignment contractor #Rigging plan "
    assert window.ref_ids["#rigging plan"] == "T000012"


def test_meeting_notes(window, ctx):
    window.show_capture(task="T000010", meeting=True)
    assert window.meeting_on and window.expanded and window.meeting_button.isChecked()
    assert window.meet_name.text() == "Business team meeting 8 Oct" and not window.types_box.isVisibleTo(window)
    assert window.meet_what.text().startswith("This time's meeting: a new subtask of Business team meeting")
    assert window.agenda_panel.isVisibleTo(window) and len(window.agenda_panel.boxes) == 4
    window.start_from_agenda()
    text = window.content.toPlainText()
    assert text.startswith("Agenda: Ask whether the December shutdown dates are confirmed.\n\n#Reactor impeller upgrade\n\n#Q4 overtime budget")
    window.content.setPlainText(text.replace("#Reactor impeller upgrade\n", "#Reactor impeller upgrade\nImpeller is on site.\n- @Tom get the report by Friday\n"))
    window.read_items()
    discussed = [b.text() for b in window.agenda_panel.boxes.values() if b.isChecked()]
    assert discussed == ["Reactor impeller upgrade  ·  Bring up the reactor impeller status at the next business team meeting."]
    assert window.does.text().startswith("Save makes <b>Business team meeting 8 Oct</b>, a meeting under <b>Business team meeting</b>")
    # Tick a note on its own by hand.
    note_id = next(i for i, b in window.agenda_panel.boxes.items() if b.text().startswith("Ask whether"))
    window.agenda_panel.boxes[note_id].setChecked(True)
    window.save()
    assert ctx.messages[-1][1].startswith("Saved C000026. Made the meeting Business team meeting 8 Oct, under Business team meeting.")
    assert "2 agenda items closed as Discussed." in ctx.messages[-1][1]
    assert not window.meeting_on and not window.expanded and not window.isVisible()
    m = Model(ctx.conn)
    assert {a.subject for a in m.open_items_for("T000010")} == {"T000015", "T000016"}


def test_meeting_notes_with_no_meeting_picked(window):
    window.toggle_meeting()
    assert window.meet_name.text() == "" and window.meet_name.hasFocus() is window.meet_name.hasFocus()
    assert not window.agenda_panel.isVisibleTo(window)  # a new meeting has no agenda, so no panel (the visual overhaul's O3)
    window.content.setPlainText("Pump vendor call.")
    window.save()
    assert "Name the meeting first" in window.error.text() and window.isVisible()
    window.toggle_meeting()
    assert not window.meeting_on and window.types_box.isVisibleTo(window)


def test_the_draft_keeps_itself(window, ctx):
    window.set_task("T000008")
    window.content.setPlainText("Walkdown notes\n- @Tom check the guards")
    assert window.draft_dirty
    window.keep_draft()
    path = ctx.data_root / DRAFT_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    assert (data["task"], data["content"], data["formatted"]) == ("T000008", "Walkdown notes\n- @Tom check the guards", False)
    assert window.draft_label.text() == "Draft kept at 14:10:00." and not window.draft_dirty
    again = CaptureWindow(ctx)  # as after a crash or a restart
    try:
        assert again.task == "T000008" and again.content.toPlainText() == "Walkdown notes\n- @Tom check the guards"
        assert again.draft_label.text() == "The draft from 14:10 came back." and len(again.item_cards.cards) == 1
    finally:
        again.deleteLater()
    window.clear()
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    fresh = CaptureWindow(ctx)
    try:
        assert fresh.content.toPlainText() == ""
    finally:
        fresh.deleteLater()


def test_the_browse_tool_opens_meeting_notes(ctx, monkeypatch):
    from docrepo.ui.browse_window import BrowseWindow

    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    try:
        opened = []
        monkeypatch.setattr(browse, "open_capture", lambda **options: opened.append(options))
        browse.go_task("T000010")
        button = next(b for b in browse.actions.findChildren(QPushButton) if b.text() == "Meeting notes")  # its key, M, is in its tooltip
        button.click()
        browse.go_task("T000012")
        assert "Meeting notes   M" not in [b.text() for b in browse.actions.findChildren(QPushButton)]
        assert any(s.key().toString() == "M" for s in browse.findChildren(QShortcut))
        browse.capture_for_selected("meeting")  # what M does on the selected task
        browse.show_agenda("T000010")
        next(b for b in browse.filters.findChildren(QPushButton) if b.text() == "Meeting notes").click()
        assert opened == [{"task": "T000010", "meeting": True}, {"task": "T000012", "meeting": True}, {"task": "T000010", "meeting": True}]
    finally:
        browse.deleteLater()
        capture.deleteLater()
