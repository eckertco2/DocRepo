"""Drafts (release 5.77, round 7's item 94, decisions 333 to 338): every capture window opens empty; closing one that
holds something files it in Drafts, a folder for each in System\\Drafts, with its files, so a restart keeps it whole; the
footer's Drafts button opens one again; a saved or discarded draft moves to System\\Drafts\\Done. Offscreen, over the
sample data, with made-up emails and files."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QImage, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, captures, db, drafts, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.drop_target import DropRead, Dropped  # noqa: E402
from msg_builder import FakeAttachment, FakeEmail, build  # noqa: E402

NOW = datetime(2026, 11, 5, 10, 42)
INSTALLATION = "T000008"
RIGGING = "T000012"


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
    told: list[tuple[str, str]] = []
    c = AppContext(conn, data_root, fs, settings, notify=lambda t, m: told.append((t, m)), now=lambda: NOW)
    c.told = told
    yield c
    conn.close()


def windows(ctx):
    made: list[CaptureWindow] = []

    def make() -> CaptureWindow:
        w = CaptureWindow(ctx)
        w.resize(900, 700)
        made.append(w)
        return w

    return make, made


@pytest.fixture
def window(ctx):
    make, made = windows(ctx)
    w = make()
    w.show_capture()
    w.again = make  # another window, as after a restart
    yield w
    QApplication.processEvents()
    for x in made:
        x._items_timer.stop()
        x._draft_timer.stop()
        x._saving = True  # the end of the test: nothing more goes to Drafts
        x.hide()
        if x.pin_window is not None:
            x.pin_window.hide()
        x.deleteLater()


def typed(w: CaptureWindow, text: str) -> None:
    w.content.setFocus()
    w.content.setPlainText(text)


def listed(ctx) -> list[drafts.Draft]:
    return drafts.listed(ctx.data_root)


# ---- every open fresh, and closing files it in Drafts (decision 333) ----
def test_closing_files_it_in_drafts_and_the_next_open_is_empty(window, ctx):
    window.set_task(INSTALLATION)
    typed(window, "Walkdown notes about the guards")
    window.hide()  # X, Esc, Alt+F4 or the main hotkey
    (kept,) = listed(ctx)
    assert kept.data["content"] == "Walkdown notes about the guards" and kept.data["task"] == INSTALLATION
    assert ctx.told[-1] == ("Kept in Drafts", "The capture window's Drafts button opens it.")
    window.show_capture()
    assert window.content.toPlainText() == "" and window.task is None
    assert window.drafts_button.isVisibleTo(window) and window.drafts_button.text() == "Drafts 1"


def test_esc_closes_it_to_drafts_too(window, ctx):
    typed(window, "Pump vendor call")
    QApplication.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not window.isVisible() and [d.data["content"] for d in listed(ctx)] == ["Pump vendor call"]


def test_a_picked_task_alone_just_closes(window, ctx):
    window.set_task(INSTALLATION)
    window.hide()
    assert listed(ctx) == [] and not ctx.told
    window.show_capture()
    assert not window.drafts_button.isVisibleTo(window)


# ---- while it's open (decision 334) ----
def test_the_main_hotkey_and_a_types_hotkey_keep_it(window, ctx):
    typed(window, "Half-written note")
    window.show_capture()  # the main hotkey, with the window open
    assert window.content.toPlainText() == "Half-written note"
    window.open_with_hotkey("new_task")
    assert window.content.toPlainText() == "Half-written note" and window.types == {"new_task"} and listed(ctx) == []


def test_a_command_for_a_task_starts_afresh(window, ctx):
    typed(window, "Notes for the crane")
    window.show_capture(task=RIGGING, mode="note")  # the browse tool's N on a task
    assert window.content.toPlainText() == "" and window.task == RIGGING
    assert window.draft_label.text() == "Your other capture is in Drafts."
    assert [d.data["content"] for d in listed(ctx)] == ["Notes for the crane"]


def test_a_command_with_only_a_task_in_the_window_moves_nothing(window, ctx):
    window.set_task(INSTALLATION)
    window.show_capture(task=RIGGING)
    assert window.task == RIGGING and listed(ctx) == []


def test_the_wheels_blank_capture_is_an_ordinary_open(window, ctx):
    typed(window, "Something half done")
    window.open_blank("note")
    assert window.content.toPlainText() == "" and window.draft_label.text() == "Your other capture is in Drafts."
    assert len(listed(ctx)) == 1


# ---- the list (decision 335) ----
def test_the_list_says_what_each_draft_is(window, ctx, tmp_path):
    f = tmp_path / "Lift plan.txt"
    f.write_text("made up", encoding="utf-8")
    window.set_task(INSTALLATION)
    typed(window, "First line of the walkdown\nsecond line")
    window.add_paths([str(f)])
    window.hide()
    window.show_capture()
    window.show_drafts()
    shown = window._drafts_list
    assert shown is not None and len(shown.rows) == 1
    words = shown.texts[0]
    assert words == "First line of the walkdown\nInstallation · 1 file · changed 10:42"
    shown.close()


def test_opening_a_draft_keeps_what_the_window_held(window, ctx):
    typed(window, "The first capture")
    window.hide()
    window.show_capture()
    typed(window, "A second one")
    (first,) = listed(ctx)
    window.open_draft(first.id)
    assert window.content.toPlainText() == "The first capture" and window.draft_id == first.id
    assert window.draft_label.text() == "The capture you had is in Drafts."
    assert [d.data["content"] for d in drafts.listed(ctx.data_root, but=window.draft_id)] == ["A second one"]
    assert window.drafts_button.text() == "Drafts 1"  # not counting the one open here


def test_saving_a_draft_moves_it_to_done(window, ctx):
    window.set_task(INSTALLATION)
    typed(window, "Saved in the end")
    window.hide()
    window.show_capture()
    (kept,) = listed(ctx)
    window.open_draft(kept.id)
    window.save()
    assert listed(ctx) == [] and (ctx.data_root / drafts.DONE_DIR / kept.id / drafts.DRAFT_JSON).is_file()


# ---- discarding, and Clear (decision 338) ----
def test_discarding_has_undo(window, ctx):
    typed(window, "Not needed after all")
    window.hide()
    window.show_capture()
    (kept,) = listed(ctx)
    window.discard_draft(kept.id)
    assert listed(ctx) == [] and window.draft_label.text() == "Draft discarded." and window.undo_clear.isVisibleTo(window)
    assert (ctx.data_root / drafts.DONE_DIR / kept.id).is_dir()  # moved, not deleted
    window.undo_clear.click()
    assert [d.id for d in listed(ctx)] == [kept.id] and not window.undo_clear.isVisibleTo(window)


def test_clear_makes_no_draft_and_undo_brings_files_back(window, ctx, tmp_path):
    f = tmp_path / "Lift plan.txt"
    f.write_text("made up", encoding="utf-8")
    typed(window, "Cleared by mistake")
    window.add_paths([str(f)])
    window.files[0].desc.setText("The lift plan")
    window.clear()
    assert window.content.toPlainText() == "" and not window.files and listed(ctx) == []
    window.undo_clear.click()
    assert window.content.toPlainText() == "Cleared by mistake" and [e.row.name for e in window.files] == ["Lift plan.txt"]
    assert window.files[0].desc.text() == "The lift plan"


# ---- the folder and a restart (decisions 336 and 337) ----
def test_a_restart_keeps_a_draft_whole(window, ctx, tmp_path):
    """An email (its .msg, with an attachment's description and a part unticked), a file a program handed over, a pasted
    picture, a path and a link, after a restart."""
    data = build(FakeEmail(attachments=[FakeAttachment("Lift plan.txt", b"Lift plan, made up"),
                                        FakeAttachment("Load chart.pdf", b"%PDF made up")]))
    from docrepo import msg

    email = msg.read(data)
    email.entry_id = "ENTRY-made-up"
    f = tmp_path / "Rigging sketch.txt"
    f.write_text("made up", encoding="utf-8")
    window.set_task(INSTALLATION)
    typed(window, "Crane booking, with the vendor's email")
    window._add_email(email)
    own, *parts = [e for e in window.files]
    own.email_desc.setText("Crane for the Tuesday lift")
    parts[0].desc.setText("The vendor's lift plan")
    parts[1].keep.setChecked(False)
    window.take_drop(DropRead([Dropped("Packing list.csv", b"part,qty\nshackle,4\n")]))  # a file dragged from an email
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    window._picture_pasted(image)
    window.add_paths([str(f)])
    window.add_link_url("https://example.com/crane-booking")
    window.hide()
    (kept,) = listed(ctx)
    folder = drafts.folder(ctx.data_root, kept.id)
    assert (folder / "emails" / "1.msg").read_bytes() == data  # exactly as handed over
    saved = json.loads((folder / drafts.DRAFT_JSON).read_text(encoding="utf-8"))
    assert saved["draft"] == drafts.FORMAT and saved["emails"][0]["entry_id"] == "ENTRY-made-up"
    assert kept.file_count() == 5  # the email (its parts with it), the dropped file, the picture, the path and the link

    again = window.again()  # a restart
    again.show_capture()
    assert again.content.toPlainText() == ""
    again.open_draft(kept.id)
    rows = {e.row.name: e for e in again.files}
    assert again.content.toPlainText() == "Crane booking, with the vendor's email" and again.task == INSTALLATION
    mail = next(e for e in again.files if e.row.email)
    assert mail.email_desc.text() == "Crane for the Tuesday lift" and mail.row.email.msg_bytes == data
    assert mail.row.email.entry_id == "ENTRY-made-up"
    assert rows["Lift plan.txt"].desc.text() == "The vendor's lift plan" and not rows["Load chart.pdf"].keep.isChecked()
    assert rows["Packing list.csv"].row.part.attachment.data == b"part,qty\nshackle,4\n"
    picture = next(e for e in again.files if e.row.part and e.row.part.pasted)
    assert "Rigging sketch.txt" in rows and rows["Rigging sketch.txt"].row.path.endswith("Rigging sketch.txt")
    assert any(e.row.path == "https://example.com/crane-booking" for e in again.files)
    # It saves as it would have before the restart, and the draft goes to Done.
    again.save()
    m = Model(ctx.conn)
    c = max(m.captures.values(), key=lambda x: x.id)
    capture_folder = captures.capture_folder(ctx.data_root, c.id, c.saved)
    assert (capture_folder / "email.msg").read_bytes() == data
    assert c.emails[0].description == "Crane for the Tuesday lift"
    assert (capture_folder / "attachments" / "Packing list.csv").read_bytes() == b"part,qty\nshackle,4\n"
    assert (capture_folder / "attachments" / picture.row.name).read_bytes()[:4] == b"\x89PNG"
    assert listed(ctx) == []


def test_an_unchanged_capture_isnt_written_again(window, ctx, monkeypatch):
    typed(window, "Kept once")
    assert window.keep_draft()
    writes = []
    monkeypatch.setattr(drafts, "write", lambda *a, **k: writes.append(a))
    assert window.keep_draft() and writes == []
    typed(window, "Kept twice")
    assert window.keep_draft() and len(writes) == 1


def test_the_old_draft_files_move_in(ctx):
    system = ctx.data_root / "System"
    system.mkdir(parents=True, exist_ok=True)
    (system / "capture-draft.json").write_text(json.dumps({"saved": "2026-11-04T16:20:00", "task": INSTALLATION, "content": "Release 5.8's draft"}), encoding="utf-8")
    (system / "capture-draft-aside.json").write_text(json.dumps({"saved": "2026-11-04T09:05:00", "content": "Set aside", "file_names": ["Pump spec.pdf"],
                                                                 "form": {"texts": {"n_duration": "5"}}}), encoding="utf-8")
    make, made = windows(ctx)
    try:
        w = make()
        assert not (system / "capture-draft.json").exists() and not (system / "capture-draft-aside.json").exists()
        found = listed(ctx)
        assert [d.data["content"] for d in found] == ["Release 5.8's draft", "Set aside"]  # newest first
        assert [d.id for d in found] == ["2026-11-04 162000", "2026-11-04 090500"]
        w.show_capture()
        w.open_draft(found[1].id)
        assert w.content.toPlainText() == "Set aside" and w.n_duration.text() == "5"
        assert w.draft_label.text() == "Not everything came back: add Pump spec.pdf again."
    finally:
        for x in made:
            x._draft_timer.stop()
            x._saving = True
            x.hide()
            x.deleteLater()


def test_an_empty_old_draft_file_stays(ctx):
    system = ctx.data_root / "System"
    system.mkdir(parents=True, exist_ok=True)
    (system / "capture-draft.json").write_text("{}", encoding="utf-8")
    assert drafts.move_old_drafts(ctx.fs, ctx.data_root, NOW) == [] and (system / "capture-draft.json").exists()


def test_a_draft_cant_name_a_file_outside_its_folder(ctx):
    assert drafts.file_path(ctx.data_root, "2026-11-05 104200", "../../settings.json") is None
    assert drafts.file_path(ctx.data_root, "2026-11-05 104200", "emails/1.msg") is not None


# ---- the pinned window (decision 334) ----
def test_the_pinned_windows_esc_makes_a_draft_and_open_in_full_keeps_it(window, ctx):
    typed(window, "Dropping emails on it")
    window.pin()
    window.unpin()  # its open button, or F12: the same capture
    assert window.content.toPlainText() == "Dropping emails on it" and listed(ctx) == []
    window.pin()
    window.hide_pinned()  # Esc
    assert not window.pinned and window.content.toPlainText() == "" and [d.data["content"] for d in listed(ctx)] == ["Dropping emails on it"]


def test_the_trays_drafts_opens_the_list(window, ctx):
    typed(window, "Waiting in Drafts")
    window.hide()
    window.open_drafts()
    QApplication.processEvents()
    assert window.isVisible() and window._drafts_list is not None and window._drafts_list.isVisible()
    window._drafts_list.close()


def test_with_no_drafts_the_list_says_so(window, ctx):
    window.show_drafts()
    assert window._drafts_list is None and window.draft_label.text().startswith("There are no drafts.")
