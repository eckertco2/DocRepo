"""The notes page on the task page (release 5.25), driven offscreen over the sample data: the editor, its saving, captures
arriving, the Captures tab's links, folds, keys, Page history and discarding."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from docrepo import db, notes_page  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import CaptureDraft, save_capture  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_edit import FOLDED, NotesEdit  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
ALT_SHIFT = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


def lines(notes: NotesEdit) -> list[tuple[str, str]]:
    return [(notes.kind(b), b.text()) for b in notes.blocks()]


def to_end(notes: NotesEdit) -> None:
    c = notes.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    notes.setTextCursor(c)


# ---- the editor on its own ----
def test_a_page_reads_in_and_out_as_docs_db_keeps_it(qapp):
    body = "\n".join(["# Design", notes_page.caption_line("Thu 8 Oct 2026 · 10:42 am · Note", "C000101"), "Vibration is **up**.",
                      "  - check the *rings*", "1. first", notes_page.file_line("File: Pump spec.docx, the datasheet", "D000012"),
                      "## Open", "<mark class=\"green\">Seal</mark> on order", notes_page.text_line("# not a heading")])
    notes = NotesEdit()
    notes.set_page(body)
    assert notes.page() == body
    assert [notes.kind(b) for b in notes.blocks()] == ["heading", "caption", "text", "text", "text", "file", "heading", "text", "text"]


def test_folding_and_the_arrow_keys(qapp):
    notes = NotesEdit()
    notes.resize(600, 400)
    notes.set_page("# Mon 5 Oct 2026\nA\nB\n# Thu 8 Oct 2026\nC", folds=["1:Mon 5 Oct 2026"])
    first = notes.document().begin()
    assert first.userState() == FOLDED and not first.next().isVisible() and notes.folds() == ["1:Mon 5 Oct 2026"]
    assert notes.section_summary(first) == "2 lines"
    notes.setTextCursor(QTextCursor(first))
    QTest.keyClick(notes, Qt.Key.Key_Down)
    assert notes.textCursor().block().text() == "Thu 8 Oct 2026"  # past the folded lines
    QTest.keyClick(notes, Qt.Key.Key_Minus, ALT_SHIFT)
    assert notes.folds() == ["1:Mon 5 Oct 2026", "1:Thu 8 Oct 2026"]
    QTest.keyClick(notes, Qt.Key.Key_Plus, ALT_SHIFT)
    assert notes.folds() == ["1:Mon 5 Oct 2026"]
    assert notes.reveal(first.next()) and notes.folds() == []  # Find or Go to opens what hides a line


def test_captions_stay_the_capture_s(qapp):
    notes = NotesEdit()
    notes.set_page("\n".join([notes_page.caption_line("Thu 8 Oct 2026 · 10:42 am · Note", "C000101"), "Text"]))
    cap = notes.document().begin()
    notes.setTextCursor(QTextCursor(cap))
    QTest.keyClicks(notes, "x")  # typing on a caption goes to the line below
    assert lines(notes) == [("caption", "Thu 8 Oct 2026 · 10:42 am · Note"), ("text", "xText")]
    removed: list[str] = []
    notes.message.connect(removed.append)
    notes.setTextCursor(QTextCursor(notes.document().begin()))
    QTest.keyClick(notes, Qt.Key.Key_Backspace)  # Backspace on a caption removes it
    assert lines(notes) == [("text", "xText")] and "no longer tied to C000101" in removed[-1]
    notes.undo()
    assert notes.kind(notes.document().begin()) == "caption"


def test_headings_today_s_heading_and_saving(qapp):
    saved: list[str] = []
    notes = NotesEdit()
    notes.changed.connect(saved.append)
    notes.set_page("Plain line")
    notes.setTextCursor(QTextCursor(notes.document().begin()))
    QTest.keyClick(notes, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert notes.page() == "## Plain line"
    QTest.keyClick(notes, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert notes.page() == "Plain line"
    to_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_D, ALT_SHIFT)
    from datetime import date

    assert notes.page() == f"Plain line\n# {notes_page.day_title(date.today())}"  # the empty line under it isn't kept
    assert notes.dirty
    notes.save_now()
    assert saved == [notes.page()] and not notes.dirty


def test_moving_lines_keeps_what_each_line_is(qapp):
    notes = NotesEdit()
    cap = notes_page.caption_line("Thu 8 Oct 2026 · 10:42 am · Note", "C000101")
    notes.set_page("\n".join(["# Two", "b", cap, "**a**"]))
    notes.setTextCursor(QTextCursor(notes.document().findBlockByNumber(3)))
    QTest.keyClick(notes, Qt.Key.Key_Up, ALT_SHIFT)
    assert notes.page() == "\n".join(["# Two", "b", "**a**", cap])
    notes.undo()
    assert notes.page() == "\n".join(["# Two", "b", cap, "**a**"])


def test_whole_lines_paste_as_they_were(qapp):
    notes = NotesEdit()
    cap = notes_page.caption_line("Thu 8 Oct 2026 · 10:42 am · Note", "C000101")
    notes.set_page("\n".join([cap, "## Mine", ""]))
    c = QTextCursor(notes.document().begin())
    c.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor, 2)
    notes.setTextCursor(c)
    notes.copy()
    to_end(notes)
    notes.paste()
    assert notes.page() == "\n".join([cap, "## Mine", cap, "## Mine"])


def test_a_heading_or_list_item_copied_first_keeps_what_it_is(qapp):
    # Qt's fragment brings its first line back as plain text (release 5.27's fix): a heading stays a heading.
    for first in ("## Head", "- Item"):
        notes = NotesEdit()
        notes.set_page("\n".join(["Before", first, "Last"]))
        c = QTextCursor(notes.document().findBlockByNumber(1))
        c.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
        notes.setTextCursor(c)
        notes.copy()
        notes.setTextCursor(QTextCursor(notes.document().begin()))
        notes.paste()
        assert notes.page() == "\n".join(["Before", first, first, "Last"])


# ---- on the task page ----
def test_the_task_page_holds_its_notes_between_its_facts_and_history(browse):
    browse.go_task("T000008")
    pane = browse.task_pane
    assert browse.detail_stack.currentIndex() == 2 and pane.task_id == "T000008"
    assert "Current status" in pane.top.toPlainText() and "Captures" not in pane.top.toPlainText()
    assert pane.bottom.toPlainText().strip().startswith("Captures") and "On the notes page" in pane.bottom.toPlainText()
    notes = pane.notes
    assert [k for k, _ in lines(notes)][:2] == ["caption", "text"] and "Install and align the new impeller" in notes.toPlainText()


def test_typing_saves_to_docs_db_task_md_and_search(browse, ctx):
    browse.go_task("T000012")
    notes = browse.task_pane.notes
    to_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_Return)
    QTest.keyClicks(notes, "Crane confirmed for the lift")
    notes.save_now()
    assert notes_page.get(ctx.conn, "T000012").endswith("\nCrane confirmed for the lift")
    assert browse.task_pane.saved.text() == "Saved 14:10"
    md = (ctx.data_root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")
    assert "Crane confirmed for the lift" in md
    from docrepo import search

    assert any(r.group == "Notes" and r.id == "T000012" for r in search.search(ctx.conn, Model(ctx.conn), "crane confirmed"))


def test_a_capture_arriving_joins_the_open_page(browse, ctx):
    browse.go_task("T000012")
    notes = browse.task_pane.notes
    save_capture(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, CaptureDraft(content="Sling drawing done.", task="T000012"), NOW)
    browse.refresh()
    assert "Sling drawing done." in notes.toPlainText()  # not typing: the page is shown again
    to_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_Return)
    QTest.keyClicks(notes, "Typed, not saved yet")
    assert notes.dirty
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, CaptureDraft(content="Second capture.", task="T000012"), NOW)
    browse.refresh()  # two writers: the typing stays, the new block comes in, and the page is saved
    text = notes.toPlainText()
    assert "Typed, not saved yet" in text and "Second capture." in text and not notes.dirty
    body = notes_page.get(ctx.conn, "T000012")
    assert "Typed, not saved yet" in body and r.capture_id in notes_page.capture_ids(body)


def test_captures_tab_goes_to_a_block_and_adds_one_again(browse, ctx):
    browse.go_task("T000012")
    browse.on_link(QUrl("goto:T000012:C000012"))
    notes = browse.task_pane.notes
    assert notes.kind(notes.textCursor().block()) == "caption" and notes.ref_of(notes.textCursor().block()) == ("capture", "C000012")
    QTest.keyClick(notes, Qt.Key.Key_Backspace)  # the caption goes
    notes.save_now()
    assert "Not on the notes page" in browse.task_pane.bottom.toPlainText()
    browse.on_link(QUrl("readd:T000012:C000012"))
    assert "C000012" in notes_page.capture_ids(notes_page.get(ctx.conn, "T000012"))
    assert notes.ref_of(notes.textCursor().block()) == ("capture", "C000012")


def test_folds_are_kept_for_each_task(browse, ctx):
    browse.go_task("T000010")  # a meeting: its sample page has a day heading
    notes = browse.task_pane.notes
    heading = next(b for b in notes.blocks() if notes.kind(b) == "heading")
    notes.toggle_fold(heading)
    assert db.get_state(ctx.conn, "notes_folds:T000010") == '["1:Fri 2 Oct 2026"]'
    browse.go_task("T000012")
    browse.go_task("T000010")
    assert browse.task_pane.notes.folds() == ["1:Fri 2 Oct 2026"]


def test_day_headings_from_the_notes_menu(browse, ctx):
    browse.go_task("T000012")
    browse.task_pane.day_action.setChecked(True)
    browse._notes_menu("day_headings")
    assert Model(ctx.conn).uses_day_headings("T000012") and browse.task_pane.notes.day_headings


def test_discarding_an_edited_capture_asks(browse, ctx):
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, CaptureDraft(content="Typed twice.", task="T000012"), NOW)
    body = notes_page.get(ctx.conn, "T000012").replace("Typed twice.", "Typed twice, reworded.")
    notes_page.put(ctx.conn, "T000012", body, NOW, by_owner=True)
    asked: list[str] = []
    browse.confirm = lambda title, text: asked.append(text) or False
    browse.ask_reason = lambda title, text: "Typed twice"
    browse.refresh()
    browse.discard_capture(r.capture_id)
    assert "was edited there" in asked[-1] and r.capture_id in notes_page.capture_ids(notes_page.get(ctx.conn, "T000012"))


def test_page_history_restores_a_day_s_page(browse, ctx, monkeypatch):
    browse.go_task("T000012")
    notes_page.put(ctx.conn, "T000012", "Older words", datetime(2026, 10, 6, 9, 0), by_owner=True)
    notes_page.put(ctx.conn, "T000012", "Newer words", datetime(2026, 10, 7, 9, 0), by_owner=True)
    monkeypatch.setattr(QDialog, "exec", lambda self: (self.findChildren(type(browse.tree))[:0], self.findChild(
        __import__("PySide6.QtWidgets", fromlist=["QListWidget"]).QListWidget).setCurrentRow(1), QDialog.DialogCode.Accepted)[-1])
    browse.page_history("T000012")
    assert notes_page.get(ctx.conn, "T000012") == "Older words" and "Restored the page" in browse.status.text()
    assert notes_page.version(ctx.conn, "T000012", "2026-10-08") == "Older words"  # the restore is today's edit
