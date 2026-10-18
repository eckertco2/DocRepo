"""The capture window and the capture app, driven offscreen (no window appears) over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
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


def test_files_need_a_description(window, ctx, tmp_path):
    report = tmp_path / "Pump curve.txt"
    report.write_text("Design point 38 kW", encoding="utf-8")
    window.set_task("T000008")
    window.add_paths([str(report)])
    assert len(window.files) == 1 and window.files_label.isVisible()
    window.save()
    assert window.error.text().startswith("Describe each file before saving") and window.isVisible()
    window.files[0].desc.setText("Pump curve at 62 rpm.")
    window.files[0].copy.setChecked(True)
    window.save()
    assert (ctx.data_root / "Tasks" / "T000008" / "Files" / "2026-10-08 Pump curve.txt").exists()
    assert Model(ctx.conn).documents["D000005"].description == "Pump curve at 62 rpm."


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


def test_set_hotkey_command(tmp_path, capsys):
    from docrepo.cli import main

    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "set-hotkey", "Ctrl+Alt+Space"]) == 0
    assert Settings.load(root).hotkey == "Ctrl+Alt+Space"
    assert main(["--data-root", str(root), "set-hotkey", "Shift+A"]) == 1
    assert "needs Ctrl, Alt or Win" in capsys.readouterr().err
