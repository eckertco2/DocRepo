"""Find files and the notes page (release 5.98, the consolidation plan's decision 391), driven offscreen over the sample
data. Release 5.37's Notes page tab went: a task's notes are on its task page, and Find files opens a note there, at its
block. (Until release 5.98 this file tested that tab, decisions 239 to 244.)"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QShortcut, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.config import Settings  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui import task_view  # noqa: E402

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


def at_end(notes) -> None:
    c = notes.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    notes.setTextCursor(c)


def test_the_kinds_are_the_five_with_no_notes_page_tab(view):
    assert [view.kinds.tabText(i).split("  ")[0] for i in range(view.kinds.count())] == ["All", "Files", "Emails", "Notes and updates", "Subtasks"]
    keys = {s.key().toString() for s in view.findChildren(QShortcut)}
    assert {"Ctrl+1", "Ctrl+5"} <= keys and "Ctrl+6" not in keys
    assert not hasattr(task_view, "PAGE") and view.windowTitle() == "Find files: Reactor impeller upgrade"
    assert view.browse.note_panes() == [view.browse.task_pane]  # the task page's notes are the only notes page open


def test_enter_on_a_note_opens_its_block_on_the_task_page(view, browse):
    QTest.keyClicks(view.box, "rigging plan for the impeller lift")
    assert view.chosen_record().kind == "note" and view.chosen_record().capture == "C000012"
    assert [b.text() for b in view.preview_buttons if not b.isHidden()][0] == "Open on the notes page"
    QTest.keyClick(view.box, Qt.Key.Key_Return)
    notes = browse.task_pane.notes
    assert browse.sel == ("task", LEAF) and browse.task_pane.task_id == LEAF
    assert notes.mark_of(notes.textCursor().block()) == notes.caption_block("C000012")  # at the line under its mark (5.85)


def test_a_note_taken_off_its_page_says_so_on_the_task_page(view, browse):
    r = view.by_key[("note", "C000001")]
    browse.go_task(TOP)
    notes = browse.task_pane.notes
    notes._remove_line(notes.caption_block("C000001"))
    notes.save_now()
    view.open_note(r)
    assert "C000001 isn't on the notes page." in browse.status.text()


def test_words_typed_on_the_page_open_the_task_page(view, browse):
    browse.go_task(TOP)
    notes = browse.task_pane.notes
    at_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_Return)
    QTest.keyClicks(notes, "Zebra crossing")
    QTest.keyClick(notes, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)  # a heading of its own
    QTest.keyClick(notes, Qt.Key.Key_Return)
    QTest.keyClicks(notes, "Mind the kerb")
    notes.save_now()
    browse.go_task("T000005")
    view.set_kind("note")
    r = next(x.record for x in view.list.rows if x.record and x.record.type == "page" and "kerb" in x.record.text)
    view.open_note(r)
    assert browse.sel == ("task", r.task)


def test_a_save_on_the_task_page_reaches_find_files_when_it_next_draws(view, browse):
    browse.go_task(TOP)
    notes = browse.task_pane.notes
    at_end(notes)
    QTest.keyClick(notes, Qt.Key.Key_Return)
    QTest.keyClicks(notes, "The walkway grating needs a look")
    notes.save_now()
    assert view.stale
    view.set_kind("note")
    assert not view.stale and any("walkway grating" in r.record.text for r in view.list.rows if r.record)


def test_edit_task_has_the_checklist_of_the_task_page(view, browse):
    browse.go_task(TOP)
    browse.run_dialog = lambda dialog: False
    browse.edit_task(TOP)
    assert browse._edit_dialog.checklist is not None
