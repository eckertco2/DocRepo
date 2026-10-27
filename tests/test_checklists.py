"""Checklists (release 5.26): checklist lines in the markup, the capture window's box and the notes page, the Checklist
summary bound to the page's lines, Edit task's checklist, and Task.md."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db, items, markup, notes_page  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import CaptureDraft, first_line, item_names, save_capture  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.checklist_summary import ChecklistSummary  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_edit import NotesEdit  # noqa: E402
from docrepo.ui.rich_edit import MARKER, FormatBar, RichEdit  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
PAGE = "\n".join(["# Before the lift", "- [x] Confirm the outage window", "- [ ] Book the **crane** for the 20th",
                  "  - [ ] Check the sling certificates", "Some text", "## Later", "- [ ] Write the lift plan"])


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---- the markup, items and descriptions ----
def test_checklist_lines_in_the_markup():
    assert [markup.check_of(x) for x in ("- [ ] a", "- [x] b", "  - [X] c", "- a", "1. [ ] d", "[ ] e")] == [False, True, True, None, None, None]
    html = markup.to_html("- [ ] Order the seal\n- [x] Check the guards")
    assert '<li class="unchecked"' in html and '<li class="checked"' in html and "[ ]" not in html and "color:#5a6571" in html
    assert "☐&nbsp;Order the seal" in markup.to_line_html("- [ ] Order the seal")
    assert markup.to_plain("- [x] **Done** it") == "- [x] Done it"


def test_a_checklist_line_never_makes_a_task_and_isn_t_a_description(sample_conn):
    names = item_names(Model(sample_conn), Settings(me="P001"))
    from datetime import date

    r = items.read("Walkdown\n- [ ] @Tom check the guards\n@Tom order the seal", names, date(2026, 10, 8), home=True)
    kinds = [(it.kind, it.text) for it in r.items]
    assert kinds == [("task", "Order the seal")]  # only the line that isn't a checklist line
    assert first_line("- [ ] a box first\nThe real description") == "The real description"


def test_task_md_has_the_checklist_summary_open_lines_first():
    out = notes_page.task_md(PAGE, lambda _: None)
    assert out[:6] == ["**Checklist** · 1 of 4 done", "", "- [ ] Book the **crane** for the 20th", "- [ ] Check the sling certificates",
                       "- [ ] Write the lift plan", "- [x] Confirm the outage window"]
    lines = notes_page.checklist(PAGE)
    assert [(x.done, x.level, x.heading) for x in lines] == [(True, 1, "Before the lift"), (False, 1, "Before the lift"), (False, 2, "Before the lift"),
                                                             (False, 1, "Later")]


# ---- the box (RichEdit: the capture window's, the page's) ----
def test_ctrl_1_brackets_ticks_and_enter(qapp):
    e = RichEdit()
    e.set_value("Intro\n- [ ] Order the seal\n- [x] Check the guards", True)
    assert e.value() == ("Intro\n- [ ] Order the seal\n- [x] Check the guards", True)
    b = e.document().begin().next()
    e.resize(400, 200)
    e.show()  # offscreen: laid out, so the box has its place
    QApplication.processEvents()
    QTest.mouseClick(e.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, e.checkbox_point(b))
    assert b.blockFormat().marker() == MARKER.Checked and b.begin().fragment().charFormat().foreground().color().name() == "#5a6571"
    e.undo()
    assert b.blockFormat().marker() == MARKER.Unchecked
    c = QTextCursor(b.next())
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    e.setTextCursor(c)
    QTest.keyClick(e, Qt.Key.Key_Return)  # after a ticked line, the next starts unticked and not grey
    QTest.keyClicks(e, "Next")
    assert e.value()[0].endswith("- [x] Check the guards\n- [ ] Next")
    QTest.keyClick(e, Qt.Key.Key_Return)
    QTest.keyClick(e, Qt.Key.Key_Return)  # Enter on an empty one ends the list
    QTest.keyClicks(e, "[] Bracket start")
    assert e.value()[0].endswith("\n- [ ] Bracket start")
    QTest.keyClick(e, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)  # again: out of the list
    assert e.value()[0].endswith("\nBracket start")
    QTest.keyClick(e, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert e.value()[0].endswith("\n- [ ] Bracket start")
    bar = FormatBar(e)
    assert bar.buttons["check"].isChecked() and "Ctrl+1" in bar.buttons["check"].toolTip()


def test_a_capture_s_checklist_lines_reach_capture_md_and_the_page(sample_root):
    conn, root, fs = sample_root
    r = save_capture(conn, root, fs, Settings(me="P001"),
                     CaptureDraft(content="Walkdown\n- [ ] Check the guards\n- [x] Order the seal", formatted=True, task="T000012"), NOW)
    from docrepo import captures

    assert captures.read_content(root, Model(conn).captures[r.capture_id]).endswith("- [ ] Check the guards\n- [x] Order the seal")
    page = notes_page.get(conn, "T000012")
    assert [(x.done, x.text) for x in notes_page.checklist(page)] == [(False, "Check the guards"), (True, "Order the seal")]


# ---- the page and the summary ----
def test_the_page_keeps_checklist_lines_and_adds_and_removes_them(qapp):
    notes = NotesEdit()
    notes.set_page(PAGE)
    assert notes.page() == PAGE
    first = next(b for b, _ in notes.checklist_blocks())
    assert notes.kind(first) == "text" and first.begin().fragment().charFormat().foreground().color().name() == "#5a6571"
    added = notes.add_check_item("Sling *drawing* done")
    assert notes.page().endswith("\n- [ ] Sling \\*drawing\\* done") and notes.is_check(added)
    notes.remove_line(added)
    assert notes.page() == PAGE
    notes.day_headings = True
    notes.add_check_item("Under today")
    from datetime import date

    assert notes.page().endswith(f"\n# {notes_page.day_title(date.today())}\n- [ ] Under today")
    heading = notes.document().begin()
    notes.setTextCursor(QTextCursor(heading))
    QTest.keyClick(notes, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)  # a heading never becomes a checklist line
    assert notes.kind(heading) == "heading"


def test_the_summary_is_the_page_s_lines(qapp):
    notes = NotesEdit()
    notes.set_page(PAGE)
    s = ChecklistSummary(notes)
    assert s.count.text() == "1 of 4 done" and s.done_button.text() == "Show 1 done"
    assert [r.text.toPlainText() for r in s._rows] == ["Book the crane for the 20th", "Check the sling certificates", "Write the lift plan"]
    row = s._rows[0]
    row.box.setChecked(True)  # a tick in the summary ticks the line on the page
    assert row.block.blockFormat().marker() == MARKER.Checked and "- [x] Book the **crane** for the 20th" in notes.page()
    s.refresh()
    assert len(s._rows) == 2 and s.count.text() == "2 of 4 done"  # done lines hide (decision 122)
    s.toggle_done()
    assert len(s._rows) == 4 and s.done_button.text() == "Hide done"
    row = s.row_for(next(b for b, _ in notes.checklist_blocks() if "lift plan" in b.text()))
    c = row.text.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    row.text.setTextCursor(c)
    QTest.keyClicks(row.text, " today")  # rewording in the summary rewords the page's line
    assert notes.page().endswith("- [ ] Write the lift plan today")
    target = next(b for b, _ in notes.checklist_blocks() if "sling" in b.text())
    notes.toggle_tick(target)  # a tick on the page shows in the summary
    s.refresh()
    assert s.row_for(target).box.isChecked()
    s.add.setText("Order slings")  # Add item takes words: format them on the page or in the row
    s.add_item()
    assert notes.page().endswith("\n- [ ] Order slings") and s.count.text() == "3 of 5 done"
    s.remove(s.row_for(next(b for b, _ in notes.checklist_blocks() if "Order slings" in b.text())))
    assert "Order slings" not in notes.page()
    s.set_folded(True)
    assert s.body.isHidden() and s.arrow.text() == "▸"


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


def test_the_task_page_has_the_summary_and_the_format_bar(browse):
    conn = browse.conn
    notes_page.put(conn, "T000012", PAGE, NOW)
    browse.refresh()
    browse.go_task("T000012")
    pane = browse.task_pane
    assert pane.summary.count.text() == "1 of 4 done" and "check" in pane.format_bar.buttons
    pane.summary._rows[0].box.setChecked(True)
    pane.notes.save_now()
    assert "- [x] Book the **crane** for the 20th" in notes_page.get(conn, "T000012")
    assert len([e for e in Model(conn).status_log_of("T000012") if e.at.startswith("2026-10-08 14:10")]) == 0  # no status log (90)
    pane.summary.set_folded(True, emit=True)
    assert db.get_state(conn, "checklist_folded:T000012") == "1"
    browse.go_task("T000008")
    browse.go_task("T000012")
    assert pane.summary.is_folded


def test_edit_task_s_checklist_is_the_page_s_and_cancel_keeps_a_tick(browse):
    conn = browse.conn
    notes_page.put(conn, "T000012", PAGE, NOW)
    browse.refresh()
    browse.go_task("T000012")
    seen = []

    def run(dialog):
        seen.append(dialog.checklist is not None and dialog.checklist.count.text())
        dialog.checklist._rows[0].box.setChecked(True)
        return False  # Cancel

    browse.run_dialog = run
    browse.edit_task("T000012")
    assert seen == ["1 of 4 done"]
    assert "- [x] Book the **crane** for the 20th" in notes_page.get(conn, "T000012")
    browse.task_pane.summary.refresh()
    assert browse.task_pane.summary.count.text() == "2 of 4 done"  # the task page's summary shows the dialog's tick
