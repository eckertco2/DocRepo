"""The capture window and the capture app, driven offscreen (no window appears) over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, hotkey, mods, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.widgets import Chip  # noqa: E402

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
    w.hide()  # a window left showing can take focus in a later test, after its database is closed
    w.deleteLater()


def test_a_quick_note(window, ctx):
    window.set_task("T000008")
    window.content.setPlainText("Crane inspection passed.")
    assert "adds this to the raw text log of <b>Installation</b>" in window.does.text()
    window.save()
    assert ctx.messages[-1] == ("Saved", "Saved C000026. Added to the raw text log of Installation.")
    assert window.content.toPlainText() == "" and window.task is None and not window.isVisible()


def test_capture_types(window):
    assert window.types == {"note"}
    window.set_type("new_task", True)
    assert window.types == {"new_task"}  # Note was only the default
    window.set_type("note", True)
    window.set_type("update", True)  # no task picked
    assert "update" not in window.types and window.error.text() == "Pick a task to update first."
    window.set_task("T000008")
    window.set_type("update", True)
    assert window.types == {"note", "new_task", "update"}  # Note was checked by hand, so it stays
    window.set_type("new_task", False)
    window.set_type("update", False)
    window.set_type("note", False)
    assert window.types == {"note"}  # with nothing checked, Note comes back


def test_a_new_task_filled_by_parse_and_populate(window, ctx):
    window.set_task("T000008")
    window.set_type("new_task", True)
    window.content.setPlainText("Remind Tyler tomorrow that he needs to book the alignment contractor. Urgent: hard deadline is the turnaround on Oct 19.")
    window.n_deadline_desc.setText("Turnaround start")
    window._touch("new.deadline_desc", window.n_deadline_desc)  # as if typed
    window.parse()
    assert window.title.text() == "Book the alignment contractor"
    assert (window.n_due.value(), window.n_deadline.value(), window.n_reminder.value()) == ("2026-10-09", "2026-10-19", "2026-10-09")
    assert window.n_deadline_desc.text() == "Turnaround start"  # typed fields are never overwritten
    assert "Not filled: you typed in this field." in window.found_label.text()
    assert window.n_leads.values() == ["P001"] and window.n_assignees.values() == ["P005"] and window.n_urgent.isChecked()
    assert window.n_more.isVisible()  # the reminder is under More fields
    window.agenda.add(Chip("T000010", "Business team meeting"))
    window.save()
    new = Model(ctx.conn).task("T000020")
    assert (new.title, new.due, new.deadline, new.deadline_desc, new.reminder) == ("Book the alignment contractor", "2026-10-09", "2026-10-19",
                                                                                  "Turnaround start", "2026-10-09")
    assert [(a.subject, a.target) for a in Model(ctx.conn).agenda][-1] == ("T000020", "T000010")


def test_a_quick_update_checks_update_itself(window, ctx):
    window.set_task("T000012")
    window.content.setPlainText("Closed. Sling drawing approved by Tom.")
    window.parse()
    assert window.types == {"update"} and window.u_state.currentText() == "Closed"
    assert window.u_status.toPlainText() == "Sling drawing approved by Tom."
    assert "2 changed fields go into its status log" in window.does.text()
    window.save()
    assert Model(ctx.conn).task("T000012").state == "Closed"


def test_an_updates_first_sentence_is_its_current_status(window, ctx):
    """Mods log round 1: Update takes the first sentence as Current status, but not when New task is checked too, since
    then the first sentence is the new task's description."""
    window.set_task("T000009")
    window.set_type("update", True)
    window.content.setPlainText("Vendor confirmed the parts ship Friday. Install is the week after.")
    window.parse()
    assert window.u_status.toPlainText() == "Vendor confirmed the parts ship Friday."
    window.set_type("new_task", True)
    window.u_status.setPlainText(Model(ctx.conn).task("T000009").current_status or "")
    window.parse()
    assert window.u_status.toPlainText() == (Model(ctx.conn).task("T000009").current_status or "")
    assert "Update: Current status" not in window.found_label.text()


def test_an_update_changes_only_what_differs(window, ctx):
    window.set_task("T000009")
    window.set_type("update", True)
    assert window.update_changes(Model(ctx.conn).task("T000009")) == {}
    window.u_due.set_value("2026-10-30")
    changes = window.update_changes(Model(ctx.conn).task("T000009"))
    assert changes == {"due": "2026-10-30"}
    window.save()
    entry = Model(ctx.conn).status_log_of("T000009")[-1]
    assert (entry.field, entry.from_value, entry.to_value, entry.via) == ("Due", "2026-10-23", "2026-10-30", "Capture window")


def test_a_file_description_is_optional(window, ctx, tmp_path):
    report = tmp_path / "Pump curve.txt"
    report.write_text("Design point 38 kW", encoding="utf-8")
    window.add_paths([str(report)])
    assert len(window.files) == 1 and window.files_label.isVisible()
    assert window.files[0].desc.placeholderText() == "What's in this file? Left empty: Pump curve.txt"
    window.set_task("T000008")  # the placeholder follows the task, and a new task's title
    assert window.files[0].desc.placeholderText().endswith("Left empty: Installation – Attached document – Pump curve.txt")
    window.set_type("new_task", True)
    window.title.setText("Check the pump curve")
    assert window.files[0].desc.placeholderText().endswith("Left empty: Check the pump curve – Attached document – Pump curve.txt")
    window.set_type("new_task", False)
    window.files[0].copy.setChecked(True)
    window.save()
    assert not window.isVisible()
    assert (ctx.data_root / "Tasks" / "T000008" / "Files" / "2026-10-08 Pump curve.txt").exists()  # named from the file, not the description
    assert Model(ctx.conn).documents["D000005"].description == "Installation – Attached document – Pump curve.txt"


def test_a_pasted_path_line_adds_the_file(window, tmp_path):
    report = tmp_path / "Checklist.txt"
    report.write_text("Area 3", encoding="utf-8")
    window.content.setPlainText(f"See the list.\n{report}")
    window._sync_paths()
    assert [e.row.name for e in window.files] == ["Checklist.txt"] and window.files[0].src == "pasted"
    window.content.setPlainText("See the list.")
    window._sync_paths()
    assert window.files == []


def test_a_pasted_path_on_a_mapped_drive_stays_put(window, tmp_path, monkeypatch):
    from docrepo.ui import capture_window

    report = tmp_path / "Survey.txt"
    report.write_text("Traps", encoding="utf-8")
    monkeypatch.setattr(capture_window, "to_unc", lambda p: "\\\\server\\share\\Survey.txt")  # as if on a mapped drive
    window.content.setPlainText(str(report))
    window._sync_paths()
    window._sync_paths()  # the network path differs from the typed line; the row must not come and go
    assert [(e.row.path, e.line) for e in window.files] == [("\\\\server\\share\\Survey.txt", str(report))]
    window._remove_file(window.files[0])
    assert window.content.toPlainText() == "" and window.files == []


def test_a_bad_date_is_caught_before_saving(window):
    window.set_type("new_task", True)
    window.title.setText("Check the guards")
    window.n_due.set_value("next week")
    window.save()
    assert window.error.text() == "Due isn't a date. Use YYYY-MM-DD." and window.isVisible()


def test_a_note_on_an_agenda(window, ctx):
    window.content.setPlainText("Ask about the holiday rota.")
    window.agenda.add(Chip("T000010", "Business team meeting"))
    assert window.does.text() == "Save puts this note on the agenda of <b>Business team meeting</b>."
    window.save()
    assert Model(ctx.conn).agenda[-1].note == "Ask about the holiday rota."


def test_a_note_on_today(window, ctx):
    """Mods log round 1 (M0016), with Today a button beside the capture types (round 2, M0037): one click, or Alt+D."""
    window.show_capture()
    assert "today" not in [o.value for o in window._agenda_options("", [])]  # it has its own button
    window.content.setPlainText("Sign the overtime sheets.")
    window._alt_today()
    assert window.today_button.isChecked() and window.today_on
    window.agenda.add(Chip("T000010", "Business team meeting"))
    assert window.does.text() == "Save puts this note on <b>Today</b> and the agenda of <b>Business team meeting</b>."
    window.save()
    assert [(a.target, a.note) for a in Model(ctx.conn).agenda[-2:]] == [("today", "Sign the overtime sheets."), ("T000010", "Sign the overtime sheets.")]


def test_copy_prompt(window, ctx):
    window.set_task("T000008")
    window.content.setPlainText("Rev 2 of the procedure arrived.")
    window.prompt_type.setCurrentText("General summary")
    window.copy_prompt()
    text = QGuiApplication.clipboard().text()
    assert text.startswith(prompts.PREAMBLE) and "Rev 2 of the procedure arrived." in text
    assert window.summary_field.isVisible() and ctx.messages[-1][0] == "Prompt copied"


def test_the_mods_log_panel(window, ctx):
    window.show_capture(mods=True)
    window.mods.text.setPlainText("Make the window wider.")
    window.save()  # Ctrl+Enter on the panel saves the entry
    assert [e.text for e in mods.read_log(ctx.data_root)] == ["Make the window wider."]
    window.content.setPlainText("Draft stays.")
    window.show_mods(False)
    assert window.content.toPlainText() == "Draft stays."


def test_hotkeys_are_parsed():
    assert hotkey.parse_hotkey("Ctrl+Shift+Space") == (hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0x20)
    assert hotkey.parse_hotkey("ctrl + alt + d") == (hotkey.MOD_CONTROL | hotkey.MOD_ALT, ord("D"))
    assert hotkey.parse_hotkey("Win+F12") == (hotkey.MOD_WIN, 0x7B)
    for bad in ("Shift+A", "Ctrl+Banana", "Hyper+A", ""):
        with pytest.raises(ValueError):
            hotkey.parse_hotkey(bad)


def test_the_app_does_its_daily_work_once_and_shows_reminders(ctx, monkeypatch):
    from docrepo import app as app_module

    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    capture_app = app_module.CaptureApp(QApplication.instance(), ctx)
    try:
        assert capture_app.daily() is True and capture_app.daily() is False
        assert (ctx.data_root / "Contents.md").exists()
        assert capture_app.show_reminders() == 2  # T000016 (yesterday's) and T000018 (today's); T000019's is tomorrow
        assert capture_app.show_reminders() == 0  # each reminder shows once
    finally:
        capture_app.quit()


def test_the_other_hotkeys_are_registered_when_set_and_do_their_own_thing(ctx, monkeypatch):
    """Mods log round 1 (M0002, M0010, M0020)."""
    from docrepo import app as app_module

    registered = []
    monkeypatch.setattr(hotkey, "register", lambda hwnd, hotkey_id, keys: registered.append((hotkey_id, keys)) or True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    ctx.settings.browse_hotkey, ctx.settings.update_hotkey = "Ctrl+Alt+B", "Ctrl+Alt+U"
    capture_app = app_module.CaptureApp(QApplication.instance(), ctx)
    opened = []
    monkeypatch.setattr(capture_app, "show_browse", lambda *a: opened.append("browse"))
    monkeypatch.setattr(capture_app.window, "open_with_hotkey", lambda kind: opened.append(kind))
    try:
        assert registered == [(1, "Ctrl+Shift+Space"), (2, "Ctrl+Alt+B"), (5, "Ctrl+Alt+U")]  # the others are off
        for setting in ("browse_hotkey", "note_hotkey", "new_task_hotkey", "update_hotkey", "agenda_hotkey"):
            capture_app.hotkey_actions[hotkey.HOTKEY_IDS[setting]]()
        assert opened == ["browse", "note", "new_task", "update", "agenda"]
    finally:
        capture_app.quit()


def test_a_capture_types_hotkey_opens_the_window_for_it(window, ctx):
    window.open_with_hotkey("new_task")
    assert window.types == {"new_task"}
    window.hide()  # Esc keeps the draft, New task and all
    window.open_with_hotkey("update")  # no task picked: the task picker opens first
    assert window.types == {"new_task"} and window._after_pick == "update"
    window._picked("T000008")
    assert window.types == {"update"} and window._after_pick is None  # only Update, as with a task already picked
    window.reset_draft()
    window.set_task("T000008")
    window.open_with_hotkey("agenda")  # a task already picked: Update at once, ready for Add to agenda
    assert window.types == {"update"} and window.agenda.isEnabled()


def test_set_hotkey_command(tmp_path, capsys):
    from docrepo.cli import main

    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "set-hotkey", "Ctrl+Alt+Space"]) == 0
    assert Settings.load(root).hotkey == "Ctrl+Alt+Space"
    assert main(["--data-root", str(root), "set-hotkey", "Shift+A"]) == 1
    assert "needs Ctrl, Alt or Win" in capsys.readouterr().err


# ---- drops: what File Explorer and Outlook put on a drag ----
EXPLORER_FORMATS = ("Shell IDList Array", "FileName", "FileContents", "FileNameW", "FileGroupDescriptorW", "ZoneIdentifier")


def _mime(paths=(), formats=()):
    from PySide6.QtCore import QMimeData, QUrl

    mime = QMimeData()
    if paths:
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    for f in formats:
        mime.setData(f'application/x-qt-windows-mime;value="{f}"', b"")
    return mime


def _drop(widget, mime):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    where = widget.rect().center()
    enter = QDragEnterEvent(where, Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, enter)
    drop = QDropEvent(QPointF(where), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, drop)
    return enter, drop


def test_a_file_dragged_from_file_explorer_becomes_a_file_row(window, tmp_path, monkeypatch):
    from docrepo import outlook
    from docrepo.ui.capture_window import read_drop

    monkeypatch.setattr(outlook, "selected_emails", lambda: pytest.fail("a file drop must not ask Outlook"))
    report = tmp_path / "Pump curve.pdf"
    report.write_bytes(b"%PDF-1.4")
    mime = _mime([report], EXPLORER_FORMATS)  # Explorer carries Outlook's virtual-file format too
    assert read_drop(mime) == ("files", [str(report).replace("\\", "/")])
    for target in (window.content.viewport(), window):
        window.reset_draft()
        enter, drop = _drop(target, mime)
        assert enter.isAccepted() and drop.isAccepted() and drop.dropAction().name == "CopyAction"  # a copy, never a move
        assert [e.row.name for e in window.files] == ["Pump curve.pdf"] and window.files[0].desc is not None
    assert window.content.toPlainText() == ""  # the path isn't pasted into the content text


def test_an_email_dragged_from_outlook_is_read_from_outlook(window, monkeypatch):
    from docrepo import outlook
    from docrepo.ui.capture_window import read_drop

    asked = []
    monkeypatch.setattr(outlook, "selected_emails", lambda: asked.append(True) or [])
    mime = _mime([], ("RenPrivateSourceFolder", "RenPrivateMessages", "FileGroupDescriptorW", "FileContents"))
    assert read_drop(mime) == ("outlook", [])
    _drop(window.content.viewport(), mime)
    assert asked == [True]


def test_an_outlook_failure_always_shows_in_the_window(window, monkeypatch):
    """Mods log round 1 (M0004): an error outlook.py didn't expect used to escape the button and, under pythonw, show nowhere."""
    from docrepo import outlook

    outlook.PROBLEMS.clear()
    monkeypatch.setattr(outlook, "selected_emails", lambda: (_ for _ in ()).throw(AttributeError("Selection")))
    window.add_outlook()
    assert window.error.text().startswith("Outlook didn't give DocRepo the email (AttributeError: Selection).")
    assert outlook.PROBLEMS[-1].step == "adding the selected Outlook email"
    monkeypatch.setattr(outlook, "selected_emails", lambda: (_ for _ in ()).throw(outlook.OutlookError("No email is selected in Outlook.")))
    window.add_outlook()
    assert window.error.text() == "No email is selected in Outlook."


def test_an_email_with_refused_fields_is_added_and_says_so(window, monkeypatch):
    from docrepo import outlook
    from docrepo.save import EmailItem

    email = EmailItem("Revised guard delivery", "", "2026-10-08 09:30", "", "", refused=("Body", "SenderName"))
    monkeypatch.setattr(outlook, "selected_emails", lambda: [email])
    window.add_outlook()
    assert [e.row.name for e in window.files] == ["Revised guard delivery"]
    assert window.error.text().startswith("Outlook didn't let DocRepo read the email's text and sender, so they are left out;")


def test_drags_are_noted_for_the_troubleshooting_report(window, monkeypatch):
    from docrepo import diagnose, outlook

    diagnose.DRAGS.clear()
    monkeypatch.setattr(outlook, "selected_emails", lambda: [])
    _drop(window.content.viewport(), _mime([], ("RenPrivateMessages", "FileGroupDescriptorW")))
    assert [(d.stage, d.taken_as, d.urls) for d in diagnose.DRAGS] == [("enter", "outlook", 0), ("drop", "outlook", 0)]
    assert 'application/x-qt-windows-mime;value="RenPrivateMessages"' in diagnose.DRAGS[-1].formats


def test_a_pasted_onenote_list_keeps_its_bullets(window):
    from PySide6.QtCore import QMimeData
    from test_paste import ONENOTE

    mime = QMimeData()
    mime.setText("Pump 7 walkdown\nCheck the coupling guard\nBolts torqued")  # OneNote's plain text: no bullets
    mime.setHtml(ONENOTE)
    window.content.insertFromMimeData(mime)
    # A real list now (release 5.7), kept as markup; Parse and populate reads its words, with the markers.
    text, formatted = window.content.value()
    assert formatted and text.startswith("Pump 7 walkdown\n- Check the coupling guard\n  - Bolts torqued\n")
    assert window.content.plain().startswith("Pump 7 walkdown\n- Check the coupling guard\n")
    window.content.clear()
    plain = QMimeData()
    plain.setText("•\tGuard\n•\tBolts")
    window.content.insertFromMimeData(plain)
    assert window.content.value() == ("- Guard\n- Bolts", False)  # plain text pasted stays plain text


def test_drops_that_bring_no_file_say_why(window, tmp_path):
    from docrepo.ui.capture_window import read_drop

    virtual = _mime([], ("FileGroupDescriptorW", "FileContents"))  # such as a file inside a zip folder
    assert read_drop(virtual) == ("virtual", [])
    _drop(window.content.viewport(), virtual)
    assert "doesn't hand DocRepo a file" in window.error.text() and not window.files
    folder = tmp_path / "Drawings"
    folder.mkdir()
    _drop(window.content.viewport(), _mime([folder], EXPLORER_FORMATS))
    assert "Drawings is a folder" in window.error.text() and not window.files


def test_editing_a_mods_log_entry_from_the_panel(window, ctx):
    """Mods log round 2 (M0047): Edit puts an open entry back in the box; Save replaces it, and Esc first stops an edit."""
    mods.add_entry(ctx.fs, ctx.data_root, "Capture window", "Make the window wider.", datetime(2026, 10, 8, 9, 0))
    window.show_capture(mods=True)
    window.mods.start_edit(mods.read_log(ctx.data_root)[0])
    assert (window.mods.editing, window.mods.text.toPlainText(), window.mods.save_button.text()) == ("M0001", "Make the window wider.", "Save M0001")
    assert window.mods.cancel_button.isVisibleTo(window.mods)
    window.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert window.mods.editing is None and window.pages.currentIndex() == 1  # still on the panel
    window.mods.start_edit(mods.read_log(ctx.data_root)[0])
    window.mods.text.setPlainText("Make the window wider, with the found list beside the text.")
    window.save()  # Ctrl+Enter on the panel saves the edit
    entries = mods.read_log(ctx.data_root)
    assert [(e.id, e.text, e.edited) for e in entries] == [("M0001", "Make the window wider, with the found list beside the text.", "2026-10-08")]
    assert window.mods.editing is None and window.mods.save_button.text() == "Save" and ctx.messages[-1][1] == r"M0001 is updated in Mods\mods-log.md."


def test_what_parse_and_populate_understood_sits_under_the_content_text(window):
    """The visual overhaul's O3: what Parse and populate found is one line under the content text, shown once it has run;
    the items' column beside the text goes under it when the window is narrow (mods log round 2, M0042)."""
    from PySide6.QtWidgets import QBoxLayout

    window.resize(940, 700)
    assert window.main_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert not window.found_box.isVisibleTo(window) and window.found_label.text() == ""  # nothing until it runs (decision 7)
    window.set_task("T000008")
    window.set_type("update", True)
    window.content.setPlainText("Closed. The coupling is in.")
    window.parse()
    assert window.found_box.isVisibleTo(window) and window.clear_found.isVisibleTo(window)
    assert "Understood" in window.found_label.text() and "Current status" in window.found_label.text()
    window.clear_found.click()
    assert not window.found_box.isVisibleTo(window)
    window._arrange(600)
    assert window.main_layout.direction() == QBoxLayout.Direction.TopToBottom
    window._arrange(940)
    assert window.main_layout.direction() == QBoxLayout.Direction.LeftToRight


def test_alt_and_the_topics_letter(window):
    """Mods log round 2 (M0036): Alt+N, Alt+T and Alt+U tick the capture types; Alt+A goes to the agenda picker."""
    window._alt_type("new_task")
    assert window.types == {"new_task"}
    window._alt_type("note")
    assert window.types == {"new_task", "note"}
    window._alt_type("new_task")
    assert window.types == {"note"}
    window.set_task("T000008")  # a note on a picked task can't go on an agenda
    window._alt_agenda()
    assert window.error.text().startswith("With a task picked, check New task or Update") and not window.today_button.isEnabled()
    window._alt_today()
    assert not window.today_on


def test_expand_folds_the_rest_away(window, ctx):
    """Mods log round 2 (M0046, M0048 phase 1): F11 makes the content text fill the window; the rest folds away and comes back."""
    window.set_task("T000008")
    window._show_summary(True)
    window.summary.setPlainText("A short summary.")
    window.toggle_expand()
    assert window.expanded and not window.lower.isVisibleTo(window) and not window.folded.isVisibleTo(window)  # help: Show hints only
    assert "Copy prompt and the summary" in window.folded.text() and window.expand_button.toolTip().startswith("Back")
    assert window.draft().summary == "A short summary."  # folded away, not lost
    window.toggle_expand()
    assert not window.expanded and window.lower.isVisibleTo(window) and not window.folded.isVisibleTo(window)


def test_a_quick_task_from_the_capture_window(window, ctx):
    """Mods log round 2 (M0039): a new task with no task picked that goes on Today waits under Quick tasks."""
    from docrepo import quick

    window.open_with_hotkey("today")  # Ctrl+Shift+D
    assert window.types == {"new_task"} and window.today_on and window._quick()
    assert window.task_button.text() == "None: a quick task, under Quick tasks"
    assert "a quick task, under <b>Quick tasks</b>" in window.does.text()
    window.title.setText("Order seal kits")
    window.save()
    m = Model(ctx.conn)
    t = next(x for x in m.tasks.values() if x.title == "Order seal kits")
    assert m.parents_of(t.id) == [quick.parent_id(ctx.conn)] and [a.subject for a in m.today_items()] == [t.id]
    assert ctx.messages[-1][1].endswith("under Quick tasks. On Today.")


def test_formatted_content_text(window, ctx, tmp_path):
    """Release 5.7 (mods log round 2, M0045): the content text box keeps formatting and lists, saved as markup."""
    from docrepo import captures

    window.set_task("T000008")
    window.content.setPlainText("Guard fitted and signed off")
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(5, cursor.MoveMode.KeepAnchor)  # "Guard"
    window.content.setTextCursor(cursor)
    ctrl_b = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier, "")
    assert QApplication.sendEvent(window.content, ctrl_b) and ctrl_b.isAccepted()  # it's the box's key, not a shortcut
    window.content.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier, ""))
    assert window.format_bar.buttons["b"].isChecked()
    report = tmp_path / "Checklist.txt"
    report.write_text("Area 3", encoding="utf-8")
    cursor.movePosition(cursor.MoveOperation.End)
    window.content.setTextCursor(cursor)
    window.content.insertPlainText(f"\n{report}")
    window._sync_paths()
    window._remove_file(window.files[0])  # the path line goes; the formatting stays
    assert window.content.value() == ("**Guard** fitted and signed off", True)
    window.save()
    c = Model(ctx.conn).captures["C000026"]
    assert c.formatted and c.title == "Guard fitted and signed off"
    assert captures.read_content(ctx.data_root, c) == "**Guard** fitted and signed off"
    window.show_capture()
    window.content.insertPlainText("Next one")
    assert window.content.value() == ("Next one", False)  # the next capture starts with no formatting
    window.make_task_from("C000026")
    assert window.content.value() == ("**Guard** fitted and signed off", True) and window.title.text() == "Guard fitted and signed off"


def test_reference_fields_and_plant_events_in_the_capture_window(window, ctx):
    """Release 5.9 (M0034, M0028): a box per reference field under More fields, filled by Parse and populate, and a
    Plant event tick box beside Urgent and Meeting. A date inside a plant event is named under the dates."""
    ctx.settings.reference_fields = ["Work order #"]
    window.show_capture()
    assert list(window.n_refs) == ["Work order #"] and list(window.u_refs) == ["Work order #"]
    assert window.n_more_button.text() == "More fields: state, start, reminder, recurrence, hours and Work order # ▸"
    window.set_type("new_task", True)
    window.content.setPlainText("Spring outage prep under work order 48213, due Oct 30.")
    window.parse()
    assert window.n_refs["Work order #"].text() == "48213" and window.n_more.isVisible()
    assert "<b>Work order #</b> 48213" in window.found_label.text()
    window.n_plant.setChecked(True)
    window.save()
    new = Model(ctx.conn).task("T000020")
    assert new.plant_event and new.references == {"Work order #": "48213"} and new.due == "2026-10-30"
    # An update: the task's values are prefilled, and only a changed reference is logged.
    window.set_task("T000008")
    window.set_type("update", True)
    assert window.update_changes(Model(ctx.conn).task("T000008")) == {}
    window.u_refs["Work order #"].setText("50001")
    window.u_due.set_value("2026-10-27")
    window.refresh()
    assert window.update_changes(Model(ctx.conn).task("T000008")) == {"due": "2026-10-27", "references": {"Work order #": "50001"}}
    assert "Work order # → 50001" in window.changes_label.text()
    assert window.u_during.text() == "Start, Due and Deadline fall during Spring outage prep under work order 48213, Thu 8 Oct to Fri 30 Oct."
    window.save()
    assert Model(ctx.conn).task("T000008").references == {"Work order #": "50001"}
    ctx.settings.reference_fields = []
    window.show_capture()
    assert window.n_refs == {} and window.n_more_button.text()[:-2] == "More fields: state, start, reminder, recurrence and hours"


def test_parse_ticks_plant_event(window, ctx):
    """Mods log round 3 (M0059, decision 58): Parse and populate ticks Plant event from "plant event" or "major event",
    or from **event on the new task's own line, as a field it filled; the event's end date is its Due."""
    window.set_task("T000010")
    window.set_type("new_task", True)
    window.content.setPlainText("Plant event: Spring outage, 2 to 6 Nov.")
    window.parse()
    assert window.n_plant.isChecked() and window.n_plant.property("filled") and window.n_more.isVisibleTo(window)
    assert window.title.text() == "Spring outage" and (window.n_start.value(), window.n_due.value()) == ("2026-11-02", "2026-11-06")
    window.clear()
    window.set_task("T000010")
    window.set_type("new_task", True)
    window.content.setPlainText("**event Fall turnaround, 2 to 6 Nov")
    window.parse()
    assert window.n_plant.isChecked() and "Plant event" in window.found_label.text()
    window.save()
    t = next(t for t in Model(ctx.conn).tasks.values() if t.title == "Fall turnaround")
    assert t.plant_event and t.due == "2026-11-06"


def test_an_event_line_makes_a_plant_event(window, ctx):
    """Release 5.9 (decision 22): **event. makes its line a task with Plant event ticked, from its Start to its Due."""
    window.set_task("T000010")
    window.content.setPlainText("Planning review.\n**event. Spring outage, 3 to 14 Nov")
    window.read_items()
    card = window.item_cards.cards[0]
    assert card.tick.text() == "Plant event" and card.title.text() == "Spring outage"
    window.save()
    m = Model(ctx.conn)
    event = next(t for t in m.tasks.values() if t.title == "Spring outage")
    assert event.plant_event and (event.start, event.due, event.deadline) == ("2026-11-03", "2026-11-14", None)
    assert m.parents_of(event.id) == ["T000010"]
