"""The Task view's Notes page tab (release 5.37, decisions 239 to 244), driven offscreen over the sample data: the tab and
which page it shows, the preview beside it, the search box and the jumps, what comes with the Notes frame, and the same
page open in the browse tool and the Task view at once."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDropEvent, QGuiApplication, QImage, QKeyEvent, QShortcut, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import notes_page  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.task_view import FOOT, PAGE, PAGE_FOOT  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TOP, SUB, LEAF = "T000001", "T000008", "T000012"  # Reactor impeller upgrade, its Installation, and that one's Rigging plan


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    capture = CaptureWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW))
    w = BrowseWindow(capture.ctx, capture)
    w.confirm = lambda title, text: True
    w.reveal = lambda path: True
    w.show_browse()
    yield w
    for view in list(w.task_views.values()):
        view.close()
    capture.deleteLater()
    w.deleteLater()


@pytest.fixture
def view(browse):
    browse.open_task_view(TOP)
    return browse.task_views[TOP]


def shortcut(view, keys: str):
    return next(s for s in view.findChildren(QShortcut) if s.key().toString() == keys)


def on_page(view):
    """The Notes page tab, by its key (an offscreen window is never active, so its shortcuts are fired directly)."""
    shortcut(view, "Ctrl+6").activated.emit()
    return view.pane.notes


def at_end(notes) -> None:
    c = notes.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    notes.setTextCursor(c)


def new_line(notes, words: str) -> None:
    """Words on a line of their own at the end of the page. (QTest can't type a line break as a character.)"""
    at_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_Return)
    QTest.keyClicks(notes, words)


def caption(notes, capture_id: str):
    return notes.caption_block(capture_id)


def shown_buttons(view) -> list[str]:
    return [b.text() for b in view.preview_buttons if not b.isHidden()]


# ---- the tab (decision 239) ----
def test_it_s_the_sixth_tab_and_the_window_still_opens_on_overview(view):
    assert view.is_overview() and view.pane is None and view.focusWidget() is view.box  # nothing's made till it's asked for
    assert [view.kinds.tabText(i).split("  ")[0] for i in range(view.kinds.count())] == ["All", "Files", "Emails", "Notes and updates", "Subtasks", "Notes page"]
    assert view.kinds.tabToolTip(5) == "Notes page (Ctrl+6)"
    notes = on_page(view)
    assert view.kind == PAGE and view.kinds.currentIndex() == 5 and view.stack.currentWidget() is view.pane
    assert notes.page() == Model(view.conn).pages[TOP]
    assert view.focusWidget() is notes  # you came to write


def test_the_page_takes_the_list_s_place_and_the_filters_row_goes(view):
    assert not view.filter_bar.isHidden()
    on_page(view)
    assert view.filter_bar.isHidden() and view.chips.isHidden() and view.pane.top.isHidden() and view.pane.bottom.isHidden()
    assert not view.preview_button.isHidden()  # it stays, in the tabs' row
    assert view.foot.text() == PAGE_FOOT
    view.kinds.setCurrentIndex(1)
    assert view.kind == "file" and not view.filter_bar.isHidden() and view.stack.currentWidget() is view.list and view.foot.text() == FOOT
    view.kinds.setCurrentIndex(5)
    assert view.kind == PAGE


def _accepted_as_override(notes, key, mods) -> bool:
    event = QKeyEvent(QEvent.Type.ShortcutOverride, key, mods)
    event.ignore()
    QApplication.sendEvent(notes, event)
    return event.isAccepted()


def test_in_the_page_ctrl_1_and_alt_shift_up_stay_the_page_s_keys(view):
    notes = on_page(view)
    assert _accepted_as_override(notes, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)  # before the window's shortcuts
    alt_shift = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier
    assert _accepted_as_override(notes, Qt.Key.Key_Up, alt_shift) and _accepted_as_override(notes, Qt.Key.Key_Down, alt_shift)
    assert not _accepted_as_override(notes, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)  # the other tabs' keys still work
    at_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert notes.is_check(notes.textCursor().block()) and view.kind == PAGE


def test_ctrl_1_from_the_box_is_still_all(view):
    on_page(view)
    view.focus_box()
    shortcut(view, "Ctrl+1").activated.emit()
    assert view.kind == "all" and view.stack.currentWidget() is view.list


# ---- which page (decision 240) ----
def test_the_outline_picks_whose_page_it_is(view):
    notes = on_page(view)
    assert view.pane.task_id == TOP and view.pane.title.text() == "Notes"
    view._outline_picked(view._outline_item(SUB))
    assert view.kind == PAGE and view.pane.task_id == SUB and notes.page() == Model(view.conn).pages[SUB]
    assert view.pane.title.text() == "Notes: Installation" and view.pane.title.toolTip() == "Installation"
    assert view.focusWidget() is notes
    assert "Kickoff" not in notes.toPlainText()  # no roll-up, either way
    view._outline_picked(view._outline_item(TOP))
    assert view.pane.task_id == TOP and view.pane.title.text() == "Notes" and "Install and align" not in notes.toPlainText()


def test_overview_in_the_outline_leaves_the_page(view):
    on_page(view)
    view._outline_picked(view._outline_item("overview"))
    assert view.is_overview() and view.stack.currentWidget() is view.list


def test_leaving_a_page_keeps_its_last_words(view):
    notes = on_page(view)
    at_end(notes)
    QTest.keyClicks(notes, " Last words.")
    assert notes.dirty
    view._outline_picked(view._outline_item(SUB))
    assert "Last words." in notes_page.get(view.conn, TOP) and "Last words." not in notes.toPlainText()


# ---- the preview (decision 241) ----
def test_the_preview_stays_hidden_until_something_on_the_page_is_clicked(view):
    assert not view.preview.isHidden()
    notes = on_page(view)
    assert view.preview.isHidden() and not view.preview_button.isChecked()
    notes.open_ref.emit("D000001")
    assert not view.preview.isHidden() and view.preview_button.isChecked()
    assert "Impeller datasheet rev B.pdf" in view.preview_page.toPlainText()
    assert "Copy path" in shown_buttons(view) and "Pin" in shown_buttons(view)
    assert view.browse.sel != ("doc", "D000001")  # it stayed in this window


def test_a_real_click_on_a_file_line_shows_it_beside_the_page(view, qapp):
    view.show()
    notes = on_page(view)
    qapp.processEvents()
    line = next(b for b in notes.blocks() if notes.kind(b) == "file")
    QTest.mouseClick(notes.viewport(), Qt.MouseButton.LeftButton, pos=notes.cursorRect(QTextCursor(line)).center() + QPoint(6, 0))
    assert view.page_record is not None and view.page_record.id == "D000001"


def test_captions_show_their_capture_s_facts_and_its_actions(view):
    notes = on_page(view)
    notes.open_ref.emit("C000001")
    assert view.page_record.kind == "note" and shown_buttons(view) == ["Open on the notes page", "Open capture"]
    notes.open_ref.emit("C000003")
    assert view.page_record.kind == "email" and shown_buttons(view)[-1] == "Open capture"


def test_ctrl_space_shows_and_hides_it_and_the_list_keeps_its_own(view):
    on_page(view)
    shortcut(view, "Ctrl+Space").activated.emit()
    assert not view.preview.isHidden() and view.page_preview and "Click a caption" in view.preview_page.toPlainText()
    assert shown_buttons(view) == []
    shortcut(view, "Ctrl+Space").activated.emit()
    assert view.preview.isHidden()
    view.set_kind("file")
    assert not view.preview.isHidden() and view.preview_on
    view.set_preview(False)
    on_page(view)
    view.pane.notes.open_ref.emit("D000001")
    assert not view.preview.isHidden()
    view.set_kind("file")
    assert view.preview.isHidden()  # the list's was off, and stays off


def test_the_preview_s_buttons_act_on_what_was_clicked(view):
    notes = on_page(view)
    notes.open_ref.emit("D000001")
    view.act("copy")
    assert "Impeller datasheet rev B.pdf" in QGuiApplication.clipboard().text()
    view.act("pin")
    assert "D000001" in view.pinned
    assert view.kind == PAGE


def test_what_isn_t_this_task_s_opens_in_the_browse_tool(browse):
    browse.open_task_view(LEAF)
    view = browse.task_views[LEAF]
    on_page(view).open_ref.emit("C000001")
    assert view.page_record is None and browse.sel == ("capture", "C000001")


def test_another_page_starts_with_the_preview_hidden_again(view):
    notes = on_page(view)
    notes.open_ref.emit("D000001")
    view._outline_picked(view._outline_item(SUB))
    assert view.preview.isHidden() and view.page_record is None


# ---- search and jumps (decision 242) ----
def test_typing_in_the_box_shows_results_and_esc_comes_back(view):
    notes = on_page(view)
    view.focus_box()
    QTest.keyClicks(view.box, "impeller")
    assert view.kind == "all" and view.stack.currentWidget() is view.list and any(r.record for r in view.list.rows)
    assert not view.filter_bar.isHidden()
    QTest.keyClick(view.box, Qt.Key.Key_Escape)
    assert view.kind == PAGE and view.query == "" and view.box.text() == "" and view.stack.currentWidget() is view.pane
    assert view.focusWidget() is notes


def test_emptying_the_box_comes_back_too(view):
    on_page(view)
    view.focus_box()
    QTest.keyClicks(view.box, "im")
    assert view.kind == "all"
    QTest.keyClick(view.box, Qt.Key.Key_Backspace)
    QTest.keyClick(view.box, Qt.Key.Key_Backspace)
    assert view.kind == PAGE and view.focusWidget() is view.box  # you were typing there; it stays


def test_a_typed_filter_leaves_the_page_and_esc_takes_it_away(view):
    on_page(view)
    view.focus_box()
    QTest.keyClicks(view.box, "type:pdf ")
    assert view.kind != PAGE and view.filters.types == {"pdf"}
    QTest.keyClick(view.box, Qt.Key.Key_Escape)
    assert view.kind == PAGE and not view.filters.count()


def test_esc_in_the_page_goes_to_the_box_then_unwinds_as_usual(view):
    notes = on_page(view)
    QTest.keyClick(notes, Qt.Key.Key_Escape)
    assert view.kind == PAGE and view.focusWidget() is view.box
    QTest.keyClick(view.box, Qt.Key.Key_Escape)
    assert view.is_overview() and view.isVisible()


@pytest.mark.parametrize("key", [Qt.Key.Key_Tab, Qt.Key.Key_Down, Qt.Key.Key_Return])
def test_from_the_box_into_the_page(view, key):
    notes = on_page(view)
    view.focus_box()
    QTest.keyClick(view.box, key)
    assert view.focusWidget() is notes and view.kind == PAGE


def test_enter_on_a_note_opens_its_block_here(view, browse):
    QTest.keyClicks(view.box, "rigging plan for the impeller lift")
    assert view.chosen_record().kind == "note" and view.chosen_record().capture == "C000012"
    before = browse.sel
    QTest.keyClick(view.box, Qt.Key.Key_Return)
    notes = view.pane.notes
    assert view.kind == PAGE and view.pane.task_id == LEAF and view.scope == LEAF and view.query == "" and view.box.text() == ""
    assert notes.textCursor().block() == caption(notes, "C000012") and browse.sel == before


def test_a_note_taken_off_its_page_says_so(view):
    notes = on_page(view)
    r = view.by_key[("note", "C000001")]
    notes._remove_line(caption(notes, "C000001"))
    notes.save_now()
    view.say("")
    view.open_note(r)
    assert view.kind == PAGE and "C000001 isn't on the notes page." in view.foot.text()


def test_words_typed_on_the_page_open_the_page(view):
    notes = on_page(view)
    new_line(notes, "Zebra crossing")  # under a heading of its own, so it isn't a capture's words
    QTest.keyClick(notes, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    new_line(notes, "Mind the kerb")
    notes.save_now()
    view.set_kind("note")
    r = next(x.record for x in view.list.rows if x.record and x.record.type == "page")
    view.open_note(r)
    assert view.kind == PAGE and view.pane.task_id == r.task and view.focusWidget() is notes


# ---- what comes with it (decision 243) ----
def test_the_whole_frame_comes_with_it(view):
    pane = view.page_pane()
    assert pane.card.objectName() == "notesCard" and not pane.format_bar.isHidden() and not pane.table_button.isHidden() and not pane.menu_button.isHidden()
    notes = on_page(view)
    new_line(notes, "[] Book the crane")
    assert "- [ ] Book the crane" in notes.page() and len(notes.checklist_blocks()) == 1 and view.pane.summary.isVisibleTo(view.pane)


def test_day_headings_and_page_history_answer_in_this_window(view, browse):
    on_page(view)
    view.pane.day_action.setChecked(True)
    view.pane.notes_menu.emit("day_headings")
    assert Model(view.conn).uses_day_headings(TOP) and view.pane.day_action.isChecked()
    assert view.foot.text() == "New captures go under a heading for their day."


def test_page_history_opens_over_this_window(view, browse, monkeypatch):
    from PySide6.QtWidgets import QDialog

    notes = on_page(view)
    at_end(notes)
    QTest.keyClicks(notes, " Not saved yet.")
    parents = []
    monkeypatch.setattr(QDialog, "exec", lambda self: parents.append(self.parent()) or QDialog.DialogCode.Rejected)
    view.pane.notes_menu.emit("history")
    assert "Not saved yet." in notes_page.get(view.conn, TOP)  # what's typed is kept first
    assert parents == [view]


def test_folds_are_kept_for_the_page_in_either_window(view, browse):
    browse.go_task("T000005")  # the task page is on another task, so it reads the folds when it comes to this one
    notes = on_page(view)
    new_line(notes, "A heading")
    QTest.keyClick(notes, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    notes.save_now()
    view.pane.notes_menu.emit("fold")
    browse.go_task(TOP)
    assert browse.task_pane.notes.folds() == ["1:A heading"]


def _picture() -> QImage:
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#3366aa"))
    return image


def test_a_picture_pasted_goes_on_this_page_and_says_so_here(view):
    notes = on_page(view)
    at_end(notes)
    notes.image_pasted.emit(_picture())
    assert "![Picture 2026-10-08 1410.png](document:" in notes_page.get(view.conn, TOP)
    assert any(notes.kind(b) == "picture" for b in notes.blocks()) and view.foot.text().startswith("Kept Picture 2026-10-08 1410.png")
    doc = next(c for c in Model(view.conn).captures.values() if c.page_made).document_ids[0]
    notes.open_ref.emit(doc)  # the new file's record is read when it's needed
    assert view.page_record is not None and view.page_record.id == doc


def test_a_file_dropped_on_the_page_goes_on_the_page(view, tmp_path):
    notes = on_page(view)
    at_end(notes)
    source = tmp_path / "Lift sketch.pdf"
    source.write_bytes(b"%PDF-1.4 made up")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    notes.insertFromMimeData(mime)
    assert "File: Lift sketch.pdf" in notes_page.get(view.conn, TOP) and view.foot.text().startswith("Added Lift sketch.pdf to the page")


def _drop_event(mime: QMimeData) -> QDropEvent:
    return QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def test_an_email_dropped_on_the_page_goes_to_the_capture_window_not_in_as_text(view, browse, monkeypatch):
    notes = on_page(view)
    before = notes.page()
    dropped = []
    monkeypatch.setattr(browse.capture, "dropped", lambda kind, paths: dropped.append(kind))
    monkeypatch.setattr(browse, "open_capture", lambda **kw: dropped.append(kw["task"]))
    mime = QMimeData()
    mime.setData("RenPrivateMessages", b"made up")
    mime.setText("From Subject Received")
    assert view.eventFilter(notes.viewport(), _drop_event(mime)) is True
    assert dropped == [TOP, "outlook"] and notes.page() == before


def test_files_and_text_dropped_on_the_page_are_left_to_the_page(view):
    notes = on_page(view)
    mime = QMimeData()
    mime.setText("just words")
    assert view.eventFilter(notes.viewport(), _drop_event(mime)) is False
    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile(str(Path(__file__)))])
    assert view.eventFilter(notes.viewport(), _drop_event(files)) is False


def test_edit_task_has_the_checklist_of_the_page_open_here(view, browse):
    on_page(view)
    browse.go_task("T000005")  # the task page is on another task
    browse.run_dialog = lambda dialog: False
    browse.edit_task(TOP)
    assert browse._edit_dialog.checklist is not None


def test_f6_reaches_the_page(view, qapp, monkeypatch):
    view.show()
    notes = on_page(view)
    qapp.processEvents()
    # An offscreen window is never active, so nothing in it is the application's focus: this says where the caret is.
    monkeypatch.setattr("docrepo.ui.task_view.QGuiApplication", SimpleNamespace(focusObject=lambda: view.box))
    view.cycle_panes(1)
    assert view.focusWidget() is notes


# ---- saving, and the same page in two windows (decision 244) ----
def test_it_saves_as_it_does_on_the_task_page(view):
    notes = on_page(view)
    at_end(notes)
    QTest.keyClicks(notes, " One more.")
    assert notes.dirty
    notes.save_now()
    assert "One more." in notes_page.get(view.conn, TOP) and view.pane.saved.text() == "Saved 14:10"
    assert "One more." in (view.ctx.data_root / "Tasks" / TOP / "Task.md").read_text(encoding="utf-8")


def test_closing_the_window_saves(view, browse):
    notes = on_page(view)
    at_end(notes)
    QTest.keyClicks(notes, " Closing words.")
    view.close()
    assert "Closing words." in notes_page.get(browse.conn, TOP) and TOP not in browse.task_views


def test_a_save_in_one_window_shows_in_the_other_at_once(view, browse):
    browse.go_task(TOP)
    there, here = browse.task_pane.notes, on_page(view)
    at_end(here)
    QTest.keyClicks(here, " From the Task view.")
    assert "From the Task view." not in there.toPlainText()
    here.save_now()
    assert "From the Task view." in there.toPlainText() and not there.dirty
    at_end(there)
    QTest.keyClicks(there, " From the task page.")
    there.save_now()
    assert "From the task page." in here.toPlainText() and not here.dirty and there.page() == here.page()


def test_ctrl_z_only_undoes_what_was_typed_since_the_window_last_updated(view, browse):
    browse.go_task(TOP)
    there, here = browse.task_pane.notes, on_page(view)
    at_end(there)
    QTest.keyClicks(there, " Before.")
    there.save_now()
    assert not here.document().isUndoAvailable()
    at_end(here)
    QTest.keyClicks(here, "x")
    here.undo()
    assert "Before." in here.toPlainText() and not here.toPlainText().endswith("x")


def test_a_page_on_another_task_isn_t_touched(view, browse):
    browse.go_task("T000005")
    there = browse.task_pane.notes
    before = there.page()
    here = on_page(view)
    at_end(here)
    QTest.keyClicks(here, " Elsewhere.")
    here.save_now()
    assert there.page() == before and browse.task_pane.task_id == "T000005"


def test_two_task_views_of_a_family_keep_step(view, browse):
    here = on_page(view)
    view._outline_picked(view._outline_item(SUB))
    browse.open_task_view(SUB)
    other = browse.task_views[SUB]
    there = on_page(other)
    at_end(here)
    QTest.keyClicks(here, " In step.")
    here.save_now()
    assert "In step." in there.toPlainText()


def test_a_capture_added_elsewhere_arrives_on_the_open_page(view, browse):
    notes = on_page(view)
    assert caption(notes, "C000012") is None
    browse.add_again(TOP, "C000012")
    assert caption(notes, "C000012") is not None and view.kind == PAGE


def test_what_s_typed_when_a_capture_arrives_stays_with_it(view, browse):
    from docrepo import edits

    notes = on_page(view)
    at_end(notes)
    QTest.keyClicks(notes, " Still typing.")
    assert notes.dirty
    edits.add_again(browse.conn, browse.ctx.data_root, browse.ctx.fs, "C000012", TOP, NOW)
    browse.refresh()
    page = notes_page.get(browse.conn, TOP)
    assert "Still typing." in page and "C000012" in page and not notes.dirty


def test_discarding_a_capture_saves_what_s_typed_here_first(view, browse):
    notes = on_page(view)
    at_end(notes)
    QTest.keyClicks(notes, " Keep this.")
    browse.ask_reason = lambda title, text: "Not needed"
    browse.discard_capture("C000008")
    page = notes_page.get(browse.conn, TOP)
    assert "Keep this." in page


def test_the_lists_catch_up_when_you_leave_the_page(view):
    notes = on_page(view)
    new_line(notes, "The walkway grating needs a look")
    notes.save_now()
    assert view.stale
    view.set_kind("note")
    assert not view.stale and any("walkway grating" in r.record.text for r in view.list.rows if r.record)


def test_the_page_isn_t_reread_while_it_s_being_typed(view, monkeypatch):
    notes = on_page(view)
    reads = []
    monkeypatch.setattr(view, "read_records", lambda: reads.append(1))
    at_end(notes)
    QTest.keyClicks(notes, " Words.")
    notes.save_now()
    assert view.stale and reads == []
