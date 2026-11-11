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
from docrepo.save import CaptureDraft, FileRow, save_capture  # noqa: E402
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


def test_a_long_page_is_laid_out_once_as_it_opens(qapp):
    """Release 5.68: set_page writes a page as one edit, so a page already shown at a width is laid out once, not again
    after every line. It's as tall as its text, so each line was a relayout of the whole page: a year of weekly meetings
    (1,508 lines) took 4 to 5 s to open."""
    week = ["# Tue 3 Nov 2026", "Attendees: Tom Becker, Priya Nair", "## Pumps", "- Seal on order", "  - due **Fri**",
            "- [ ] Book the crane", "- [x] Drawings back", notes_page.caption_line("Tue 3 Nov · 10:42 am · Note", "C000101")]
    body = "\n".join(week * 40)
    notes = NotesEdit()
    notes.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    notes.resize(700, 400)
    notes.show()
    notes.set_page("Before")
    QApplication.processEvents()
    relayouts = []
    notes.document().documentLayout().documentSizeChanged.connect(lambda _: relayouts.append(1))
    notes.set_page(body)
    assert notes.page() == body
    assert len(relayouts) <= 2  # one for each of its 320 lines before


def test_moving_lines_keeps_what_each_line_is(qapp):
    notes = NotesEdit()
    cap = notes_page.caption_line("Thu 8 Oct 2026 · 10:42 am · Note", "C000101")
    notes.set_page("\n".join(["# Two", "b", cap, "**a**"]))
    notes.setTextCursor(QTextCursor(notes.document().findBlockByNumber(3)))
    QTest.keyClick(notes, Qt.Key.Key_Up, ALT_SHIFT)
    assert notes.page() == "\n".join(["# Two", cap, "**a**", "b"])  # the block's tucked caption moves with it (release 5.85)
    notes.undo()
    assert notes.page() == "\n".join(["# Two", "b", cap, "**a**"])
    notes.setTextCursor(QTextCursor(notes.document().findBlockByNumber(1)))
    QTest.keyClick(notes, Qt.Key.Key_Down, ALT_SHIFT)  # and past a captioned block as one unit
    assert notes.page() == "\n".join(["# Two", cap, "**a**", "b"])


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
    assert "Current status" in pane.header.text() and "Captures" not in pane.header.text()  # the header (release 5.84)
    assert pane.bottom.toPlainText().strip().startswith("Captures") and "On the notes page" in pane.bottom.toPlainText()
    notes = pane.notes
    # Its blocks under their days' headings: every page has them since release 5.69.
    assert [k for k, _ in lines(notes)][:3] == ["heading", "caption", "text"] and "Install and align the new impeller" in notes.toPlainText()


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
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, CaptureDraft(content="Second capture.", task="T000012", files=[FileRow("Spec sheet", "https://example.com/spec", "the spec")]), NOW)
    browse.refresh()  # two writers: the typing stays, the new block comes in, and the page is saved
    text = notes.toPlainText()
    assert "Typed, not saved yet" in text and "Second capture." in text and not notes.dirty
    body = notes_page.get(ctx.conn, "T000012")
    assert "Typed, not saved yet" in body and r.capture_id in notes_page.capture_ids(body)


def test_the_capture_window_saves_an_open_page_before_a_note_lands(browse, ctx):
    """Release 5.69: a note that's no capture goes straight onto its page, and only captures' blocks are merged into a
    page with unsaved typing, so the capture window's Save saves every open page first: neither is lost."""
    browse.go_task("T000012")
    notes = browse.task_pane.notes
    to_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_Return)
    QTest.keyClicks(notes, "Typed, not saved yet")
    assert notes.dirty
    window = browse.capture
    window.show_capture()
    window.set_task("T000012")
    window.content.setPlainText("A note from the capture window.")
    window.save()
    browse.refresh()
    body = notes_page.get(ctx.conn, "T000012")
    assert "Typed, not saved yet" in body and body.endswith("A note from the capture window.")
    assert "A note from the capture window." in notes.toPlainText() and not notes.dirty
    window.hide()


def test_captures_tab_goes_to_a_block_and_adds_one_again(browse, ctx):
    browse.go_task("T000012")
    browse.on_link(QUrl("goto:T000012:C000012"))
    notes = browse.task_pane.notes
    # The caption is tucked behind its mark (release 5.85): the caret lands at the start of the line under it.
    at = notes.textCursor().block()
    assert notes.kind(at) == "text" and notes.ref_of(notes.mark_of(at)) == ("capture", "C000012") and notes.textCursor().positionInBlock() == 0
    QTest.keyClick(notes, Qt.Key.Key_Backspace)  # Backspace at the block's start takes the caption off
    notes.save_now()
    assert "Not on the notes page" in browse.task_pane.bottom.toPlainText()
    browse.on_link(QUrl("readd:T000012:C000012"))
    assert "C000012" in notes_page.capture_ids(notes_page.get(ctx.conn, "T000012"))
    assert notes.ref_of(notes.mark_of(notes.textCursor().block())) == ("capture", "C000012")  # back, behind its mark


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
    # Release 5.69: every page has day headings, so the Notes menu has no switch for them.
    menu = [a.text() for a in browse.task_pane.menu_button.menu().actions() if a.text()]
    assert menu == ["Fold all headings", "Unfold all", "Fold days older than two weeks", "Page history…"]  # the last option: release 5.86
    assert Model(ctx.conn).uses_day_headings("T000012") and browse.task_pane.notes.day_headings


def test_discarding_an_edited_capture_asks(browse, ctx):
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, CaptureDraft(content="Typed twice.", task="T000012", files=[FileRow("Spec sheet", "https://example.com/spec", "the spec")]), NOW)
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


def test_captions_tuck_behind_a_mark_and_day_headings_are_dividers(qapp):
    """Release 5.85 (the task pane review's R3 and R5): a caption with a line under it is hidden and its mark is drawn in
    the gutter beside that line (a click opens the capture, the Captures tab's jump lands on the line, Backspace at
    its start takes the caption off, and the page is kept as it was); a caption with nothing under it stays a line;
    a day heading is a quiet divider, the owner's headings as before."""
    from PySide6.QtCore import QPoint

    from docrepo.ui import tokens
    from docrepo.ui.notes_edit import LEFT
    from docrepo.ui.rich_edit import HEADING_SIZES

    cap = notes_page.caption_line("Thu 8 Oct 2026 · 10:42 am · Email from Tom Becker: Re: seals", "C000101")
    lone = notes_page.caption_line("Thu 8 Oct 2026 · 11:00 am · New task", "C000102")
    body = "\n".join(["# Thu 8 Oct 2026", cap, "Seals are in.", "## Design", lone])
    notes = NotesEdit()
    notes.resize(600, 400)
    notes.set_page(body)
    notes.show()  # laid out, so the rows have places
    QApplication.processEvents()
    doc = notes.document()
    day, c1, text, design, c2 = (doc.findBlockByNumber(i) for i in range(5))
    assert notes.tucked(c1) and not c1.isVisible() and notes.mark_of(text) == c1 and notes.mark_name(c1.text()) == "mail"
    assert not notes.tucked(c2) and c2.isVisible() and notes.mark_of(c2) is None and notes.mark_name(c2.text()) == "task"
    assert notes.page() == body  # kept as docs.db has it
    r = notes._row(text)
    assert notes.mark_at(QPoint(LEFT // 2, r.center().y())) == c1 and notes.mark_at(QPoint(LEFT + 40, r.center().y())) is None
    opened: list[str] = []
    notes.open_ref.connect(opened.append)
    QTest.mouseClick(notes.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(LEFT // 2, r.center().y()))
    assert opened == ["C000101"]
    assert notes.go_to("C000101") and notes.textCursor().block() == text and notes.textCursor().positionInBlock() == 0
    assert day.begin().fragment().charFormat().fontPointSize() == tokens.CAPTION  # a divider
    assert design.begin().fragment().charFormat().fontPointSize() == tokens.BODY + HEADING_SIZES[2]
    removed: list[str] = []
    notes.message.connect(removed.append)
    QTest.keyClick(notes, Qt.Key.Key_Backspace)
    assert lines(notes)[1] == ("text", "Seals are in.") and "no longer tied to C000101" in removed[-1]
    notes.undo()
    assert notes.page() == body and notes.tucked(doc.findBlockByNumber(1))


def test_the_outline_landmarks_latest_and_old_days_in_the_editor(qapp):
    """Release 5.86 (the task pane review's R9 and decision P7): the outline lists every heading, the landmarks only those
    that show, Latest goes to the end, and folding the days before a cutoff leaves the owner's own folds alone."""
    from datetime import date

    body = "\n".join(["# Mon 7 Sep 2026", "Old.", "## Design", "Lines.", "# Thu 8 Oct 2026", "New.", "## Site", "Here."])
    notes = NotesEdit()
    notes.resize(600, 400)
    notes.set_page(body)
    notes.show()
    QApplication.processEvents()
    assert [(b.text(), level, day) for b, level, day in notes.outline()] == \
        [("Mon 7 Sep 2026", 1, True), ("Design", 2, False), ("Thu 8 Oct 2026", 1, True), ("Site", 2, False)]
    marks = notes.landmarks()
    assert [m[3] for m in marks] == ["Mon 7 Sep 2026", "Design", "Thu 8 Oct 2026", "Site"] and marks[0][0] < marks[1][0] < marks[2][0] < marks[3][0]
    cutoff = date(2026, 9, 24)
    assert notes.fold_old_days(cutoff) == 1 and notes.folds() == ["1:Mon 7 Sep 2026"]
    assert [m[3] for m in notes.landmarks()] == ["Mon 7 Sep 2026", "Thu 8 Oct 2026", "Site"]  # Design is under the fold
    assert notes.fold_old_days(cutoff) == 0  # already folded
    site = notes.outline()[3][0]
    notes.toggle_fold(site)  # the owner's own fold stays as the old days unfold
    assert notes.fold_old_days(cutoff, False) == 1 and notes.folds() == ["2:Site"]
    notes.go_to_end()
    assert notes.textCursor().atEnd() and notes.textCursor().block().text() == "Here."


def test_ways_down_a_long_page(browse, ctx):
    """Release 5.86 (R9, decision P7): Jump to lists the page's headings and days and scrolls one to the top of the pane,
    the sticky title line shows once the facts have scrolled off, Latest goes to the end, the scroll bar has a landmark
    per heading, and Fold days older than two weeks folds them as the page opens, remembered per task."""
    import json

    body = "\n".join(["# Mon 7 Sep 2026", "Old.", "## Design", *["A line of notes."] * 60, "# Thu 8 Oct 2026", "New.", "## Site", "Here."])
    notes_page.put(ctx.conn, "T000012", body, NOW)
    browse.refresh()
    browse.go_task("T000012")
    pane = browse.task_pane
    notes, bar = pane.notes, pane.verticalScrollBar()
    QApplication.processEvents()
    assert pane.jump_button.isHidden() == pane.outline_shown() and not pane.sticky.isVisible()  # the outline stands in for it
    pane.show_jump_menu()
    assert [a.text() for a in pane._jump_menu.actions() if a.text()] == \
        ["Top of the page", "Mon 7 Sep 2026", "\u2003Design", "Thu 8 Oct 2026", "\u2003Site", "Latest"]
    pane._jump_menu.close()
    site = notes.outline()[3][0]
    pane.jump_to(site)
    QApplication.processEvents()
    assert notes.textCursor().block() == site and bar.value() > 0
    assert pane.sticky.isVisible() and pane.sticky_name.text() and pane.sticky_name.toolTip() == Model(ctx.conn).task("T000012").title
    bar.setValue(0)
    assert not pane.sticky.isVisible()
    pane.latest()
    QApplication.processEvents()
    assert notes.textCursor().atEnd() and bar.value() > 0
    for _ in range(3):
        QApplication.processEvents()  # the page's last resize, then the landmarks' timer
    assert [m[3] for m in bar.marks] == ["Mon 7 Sep 2026", "Design", "Thu 8 Oct 2026", "Site"] and bar.total > 0  # the page's height as of its last layout
    assert "Thu 8 Oct 2026" in bar.marks_near(bar.bar_y(bar.marks[2][0])) and bar.marks_near(bar.bar_y(bar.marks[1][0]) + 40) == []
    # Days older than two weeks: off until asked for, then folded as the page opens, per task.
    assert not pane.old_days_action.isChecked() and notes.folds() == []
    pane.old_days_action.trigger()
    assert notes.folds() == ["1:Mon 7 Sep 2026"] and json.loads(db.get_state(ctx.conn, "page_folds:T000012"))["old_days"] is True
    browse.go_task("T000010")
    assert not browse.task_pane.old_days_action.isChecked()
    browse.go_task("T000012")
    assert pane.old_days_action.isChecked() and notes.folds() == ["1:Mon 7 Sep 2026"]
    pane.jump_to(notes.outline()[1][0])  # Design, under the folded day: Jump to opens it
    assert notes.folds() == [] and notes.textCursor().block().text() == "Design"
    pane.old_days_action.trigger()
    assert not pane.old_days_action.isChecked() and json.loads(db.get_state(ctx.conn, "page_folds:T000012"))["old_days"] is False


def test_the_outline_beside_the_notes(browse, ctx, monkeypatch):
    """Release 5.113 (the notes workspace plan's decision 349, at the owner's ask of 2026-11-10): a column at the notes'
    left lists the page's headings and days, marks the one you're in, goes to one on a click, stays in view as the page
    scrolls, follows the page shown, and is shown or hidden for every task by its button; where it doesn't fit, Jump to's
    button stands in."""
    body = "\n".join(["# Mon 7 Sep 2026", "Old.", "## Design", *["A line of notes."] * 60, "# Thu 8 Oct 2026", "New.", "## Site", "Here."])
    notes_page.put(ctx.conn, "T000012", body, NOW)
    browse.refresh()
    browse.go_task("T000012")
    pane = browse.task_pane
    monkeypatch.setattr(pane, "outline_fits", lambda: True)  # the offscreen platform's letters are wide
    pane._fit_outline()
    QApplication.processEvents()
    o, bar = pane.outline, pane.verticalScrollBar()
    assert pane.outline_shown() and pane.jump_button.isHidden() and pane.outline_button.isChecked()
    assert [x[3] for x in o.entries()] == ["Mon 7 Sep 2026", "Design", "Thu 8 Oct 2026", "Site"]
    assert [o.item(i).text() for i in range(o.count())] == ["Mon 7 Sep", "Design", "Thu 8 Oct", "Site"]  # one year, so no year
    assert o.current == o.entries()[0][0]  # the first, at the top of the page
    site = o.entries()[3][0]
    o.picked.emit(site)
    for _ in range(3):
        QApplication.processEvents()
    assert pane.notes.textCursor().block().blockNumber() == site and o.current == site and bar.value() > 0
    if pane._outline_offset() > 8:
        assert o.y() > 8  # moved down its slot, so it's still in view
    bar.setValue(0)
    QApplication.processEvents()
    assert o.y() <= 8
    # It follows the page shown at once: never the page before's headings.
    browse.go_task("T000001")
    assert [x[3] for x in o.entries()] == [b.text() for b, _level, _day in pane.notes.outline()]
    # Hidden by its button, and kept so for every task; Jump to's button comes back.
    pane.outline_button.click()
    assert not pane.outline_shown() and not pane.jump_button.isHidden() and db.get_state(ctx.conn, "notes_outline") == "0"
    browse.go_task("T000012")
    assert not pane.outline_shown()
    pane.outline_button.click()
    assert pane.outline_shown() and db.get_state(ctx.conn, "notes_outline") == "1"
    # Where it doesn't fit, it steps aside.
    monkeypatch.setattr(pane, "outline_fits", lambda: False)
    pane._fit_outline()
    assert not pane.outline_shown() and pane.outline_button.isHidden() and not pane.jump_button.isHidden()
