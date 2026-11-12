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
from docrepo import drafts  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
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
    before = set(Model(window.ctx.conn).captures)
    window.save()
    m = Model(window.ctx.conn)
    made = [c for cid, c in m.captures.items() if cid not in before]  # the notes are on the page, no capture (release 5.69)
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
    """Every 30 seconds, in its own folder in System\\Drafts (release 5.77): after a crash or a restart it's in Drafts, and
    the window opens empty."""
    window.set_task("T000008")
    window.content.setPlainText("Walkdown notes\n- @Tom check the guards")
    assert window.draft_dirty
    assert window.keep_draft()
    data = json.loads((drafts.folder(ctx.data_root, window.draft_id) / drafts.DRAFT_JSON).read_text(encoding="utf-8"))
    assert (data["task"], data["content"], data["formatted"]) == ("T000008", "Walkdown notes\n- @Tom check the guards", False)
    assert window.draft_label.text() == "Draft kept at 14:10:00." and not window.draft_dirty
    again = CaptureWindow(ctx)  # as after a crash or a restart
    try:
        assert again.content.toPlainText() == "" and again.drafts_button.isVisibleTo(again)
        (kept,) = drafts.listed(ctx.data_root)
        again.open_draft(kept.id)
        assert again.task == "T000008" and again.content.toPlainText() == "Walkdown notes\n- @Tom check the guards"
        assert len(again.item_cards.cards) == 1
    finally:
        again._draft_timer.stop()
        again.hide()
        again.deleteLater()
    window.clear()
    assert drafts.listed(ctx.data_root) == [] and (ctx.data_root / drafts.DONE_DIR).is_dir()  # moved to Done, not deleted


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


# ---- files on meeting notes (release 5.135, decision 547) ----
def _drop_files(widget, paths):
    """A drag of files from File Explorer, dropped on ``widget``."""
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    where = widget.rect().center()
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    QApplication.sendEvent(widget, QDragEnterEvent(where, actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    drop = QDropEvent(QPointF(where), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, drop)
    return drop


def _picture(window) -> None:
    from PySide6.QtGui import QImage

    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    window._picture_pasted(image)


def test_meeting_notes_take_files_as_any_capture_does(window, ctx, tmp_path, monkeypatch):
    """Attach's Files…, a drop on the notes, a path and a link each on its own line, the email selected in Outlook and a
    pasted picture: each row shows under the notes while they're expanded, and Save keeps them on the notes, on the
    meeting, with Save a copy in the meeting's Files folder."""
    from PySide6.QtWidgets import QFileDialog

    from docrepo import captures, outlook
    from docrepo.save import EmailItem

    report, sketch, drawings = tmp_path / "Pump curve.txt", tmp_path / "Seal sketch.txt", tmp_path / "Drawings"
    report.write_text("Design point 38 kW", encoding="utf-8")
    sketch.write_text("Made-up seal sketch", encoding="utf-8")
    drawings.mkdir()
    window.show_capture(task="T000010", meeting=True)
    assert window.expanded and not window.files_area.isVisibleTo(window)  # no files, no room taken
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(report)], ""))
    window._pick_files()
    assert _drop_files(window.content.viewport(), [drawings]).isAccepted()
    window.content.setPlainText(f"Impeller is on site.\n{sketch}\nhttps://example.com/crane-booking")
    window._sync_paths()
    email = EmailItem("Revised guard delivery", "Ann Example", "2026-10-08 09:30", "", "The guards arrive Friday.")
    monkeypatch.setattr(outlook, "selected_emails", lambda scratch=None: [email])
    window.add_outlook()
    _picture(window)
    type_text(window, "\nThe vendor's drawings are in.")  # typing on after the picture keeps it (decision 548)
    window._sync_paths()
    QApplication.processEvents()  # a row added to a shown layout is shown on the next pass
    assert [e.row.name for e in window.files][-1] == "Picture 2026-10-08 1410.png"
    assert len(window.files) == 6 and window.task == "T000010"  # an email doesn't move meeting notes to its conversation's task
    assert window.files_area.isVisibleTo(window) and all(e.widget.isVisibleTo(window) for e in window.files)
    assert window.meeting_on and window.expanded and not window.lower.isVisibleTo(window)  # the rest stays folded away
    assert window.files[0].desc.placeholderText() == (
        "What's in this file? Left empty: Business team meeting 8 Oct – Attached document – Pump curve.txt")
    assert "and keeps these notes on it, with 1 email, 3 files, 1 folder and 1 link." in window.does.text()
    assert window.copy_hint.text().startswith("Save a copy puts the file in the meeting's Files folder, once Save makes the meeting,")
    window.files[0].copy.setChecked(True)
    window.save()
    assert not window.isVisible() and ctx.messages[-1][1].startswith("Saved C000026. Made the meeting Business team meeting 8 Oct")
    m = Model(ctx.conn)
    notes = m.captures["C000026"]
    meeting = notes.task
    assert m.task(meeting).title == "Business team meeting 8 Oct" and notes.item == "notes"
    assert sorted(m.documents[d.document].name for d in notes.documents) == sorted(
        ["Pump curve.txt", "Drawings", "Seal sketch.txt", "example.com", "Picture 2026-10-08 1410.png"])
    assert [e.subject for e in notes.emails] == ["Revised guard delivery"]
    assert (ctx.data_root / "Tasks" / meeting / "Files" / "2026-10-08 Pump curve.txt").exists()
    folder = captures.capture_folder(ctx.data_root, notes.id, notes.saved)
    assert (folder / "attachments" / "Picture 2026-10-08 1410.png").read_bytes()[:4] == b"\x89PNG"


def test_expand_alone_still_folds_the_files_away(window, tmp_path):
    """Only meeting notes keep the files in view while expanded; Expand on its own folds them away, as before."""
    report = tmp_path / "Pump curve.txt"
    report.write_text("Design point 38 kW", encoding="utf-8")
    window.set_task("T000008")
    window.add_paths([str(report)])
    assert window.files_area.isVisibleTo(window)
    window.toggle_expand()
    assert window.expanded and not window.files_area.isVisibleTo(window)
    assert window.folded.text().startswith("While expanded, 1 file and Copy prompt and the summary are folded away. Drop files")
    window.toggle_expand()
    window.toggle_meeting()
    QApplication.processEvents()
    assert window.meeting_on and window.expanded and window.files[0].widget.isVisibleTo(window)
    assert window.folded.text().startswith("While expanded, Copy prompt and the summary is folded away. Files you add are listed under the notes.")
    assert window.files[0].desc.placeholderText().endswith("Left empty: (the meeting's name) – Attached document – Pump curve.txt")
    window.meet_name.setText("Pump vendor call")
    window._meet_typed("Pump vendor call")
    assert window.files[0].desc.placeholderText().endswith("Left empty: Pump vendor call – Attached document – Pump curve.txt")
    window.toggle_meeting()
    assert not window.meeting_on and not window.expanded and window.files_area.isVisibleTo(window) and window.lower.isVisibleTo(window)


def test_a_meeting_notes_draft_keeps_its_files(window, ctx, tmp_path):
    """Closed before it's saved, meeting notes go to System\\Drafts with their files, and come back as meeting notes with
    their rows in view."""
    report = tmp_path / "Pump curve.txt"
    report.write_text("Design point 38 kW", encoding="utf-8")
    window.show_capture(task="T000010", meeting=True)
    window.content.setPlainText("Impeller is on site.")
    window.add_paths([str(report)])
    _picture(window)
    window.hide()  # to Drafts
    (kept,) = drafts.listed(ctx.data_root)
    assert kept.data["meeting"] and kept.file_count() == 2
    again = CaptureWindow(ctx)  # as after a restart
    try:
        again.show_capture()
        again.open_draft(kept.id)
        assert again.meeting_on and again.expanded and again.task == "T000010"
        assert [e.row.name for e in again.files] == ["Pump curve.txt", "Picture 2026-10-08 1410.png"]
        QApplication.processEvents()
        assert all(e.widget.isVisibleTo(again) for e in again.files)
        again.save()
        m = Model(ctx.conn)
        notes = max(m.captures.values(), key=lambda c: c.id)
        assert notes.item == "notes" and m.task(notes.task).title == "Business team meeting 8 Oct" and len(notes.documents) == 2
        assert drafts.listed(ctx.data_root) == []
    finally:
        again._draft_timer.stop()
        again.hide()
        again.deleteLater()
