"""Release 5.143 in the browse window, offscreen (the design workspace's notes consolidation plan, decision 613): Move to
task from the notes editor (Alt+Shift+M and the menu), the task picked, Undo, a pointer line followed to its lines, and
Bring the lines back. ``test_move_to_task.py`` has the rest, without Qt. Made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import notes_page  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from notes_example import SETTINGS, build  # noqa: E402

NOW = datetime(2026, 11, 13, 9, 15)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qapp, sample_root):
    conn, root, fs = sample_root
    ex = build(conn, root, fs)
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.said = []
    w.say = lambda text, error=False: w.said.append((text, error))
    w.show_browse()
    w.resize(1440, 900)
    yield w, ex
    capture.deleteLater()


def pick_lines(notes, first: str, last: str) -> None:
    """Select from the line starting ``first`` to the end of the line starting ``last``."""
    blocks = list(notes.blocks())
    a = next(b for b in blocks if b.text().startswith(first))
    z = next(b for b in blocks if b.text().startswith(last))
    c = QTextCursor(a)
    c.setPosition(z.position() + z.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    notes.setTextCursor(c)


def test_move_to_task_from_the_editor_with_undo(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.kickoff)
    QApplication.processEvents()
    notes = pane.notes
    pick_lines(notes, "Shutdown window", "Vendor says")
    start, end, lines = notes.line_span()
    assert [notes_page.read_line(x).text[:15] for x in lines] == ["Shutdown window", "Vendor says fil"]
    QTest.keyClick(notes, Qt.Key.Key_M, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    QApplication.processEvents()
    assert w._picker is not None
    w._picker.picked.emit(ex.fill)
    QApplication.processEvents()
    page = notes.page()
    assert "Vendor says" not in page and "Fill media order · 2 lines moved there" in page
    pointer = next(b for b in notes.blocks() if notes.kind(b) == "pointer")
    assert pointer.text() == "↪ Fill media order · 2 lines moved there"
    assert "Moved 2 lines to Fill media order." in w.said[-1][0] and w._undo is not None
    w._undo()
    QApplication.processEvents()
    assert "Vendor says fill lead time" in notes.page() and "moved there" not in notes.page()


def test_a_pointer_opens_its_lines_and_brings_them_back(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.kickoff)
    QApplication.processEvents()
    notes = pane.notes
    pick_lines(notes, "Shutdown window", "Vendor says")
    w.move_to_task(pane)
    w._picker.picked.emit(ex.fill)
    QApplication.processEvents()
    key = notes_page.pair_of(next(x for x in notes_page.lines_of(notes.page()) if x.kind == "pointer").ref)[1]
    w.open_ref(f"moved:{ex.fill}/{key}")  # a click on the pointer line
    QApplication.processEvents()
    assert w.sel == ("task", ex.fill) and notes.kind(notes.textCursor().block()) == "lead"
    assert notes.textCursor().block().text() == "Moved from the notes of Cooling tower kickoff · Tue 3 Nov"
    w.open_ref(f"from:{ex.kickoff}/{key}")  # and the lead line goes back to its pointer
    QApplication.processEvents()
    assert w.sel == ("task", ex.kickoff) and notes.kind(notes.textCursor().block()) == "pointer"
    # The pointer's right-click menu brings the lines back.
    rect = notes.cursorRect()
    notes.contextMenuEvent(type("E", (), {"pos": lambda self: rect.center(), "globalPos": lambda self: notes.mapToGlobal(rect.center())})())
    action = next(a for a in notes._menu.actions() if a.text() == "Bring the lines back")
    notes._menu.close()
    action.trigger()
    QApplication.processEvents()
    assert "Vendor says fill lead time" in notes.page() and "moved there" not in notes.page()
    assert "Brought 2 lines back from Fill media order." in w.said[-1][0]


def test_the_menu_offers_move_to_task(setup):
    w, ex = setup
    w.go_task(ex.kickoff)
    QApplication.processEvents()
    notes = w.task_pane.notes
    rect = notes.cursorRect()
    notes.contextMenuEvent(type("E", (), {"pos": lambda self: rect.center(), "globalPos": lambda self: notes.mapToGlobal(rect.center())})())
    assert any(a.text().startswith("Move to task…") for a in notes._menu.actions())
    notes._menu.close()


def test_a_meeting_s_pointer_line_opens_the_item_s_block(setup):
    """Decision 614: a #task section's pointer line on the weekly's page opens the survey's page at that item's block."""
    w, ex = setup
    w.go_task(ex.weekly)
    QApplication.processEvents()
    notes = w.task_pane.notes
    pointer = next(x for x in notes_page.lines_of(notes.page()) if x.kind == "pointer" and x.ref.startswith(ex.survey))
    w.open_ref(f"moved:{pointer.ref}")
    QApplication.processEvents()
    assert w.sel == ("task", ex.survey)
    block = notes.textCursor().block()  # its caption is tucked (release 5.85), so the caret is on the line under it
    assert block.text() == "- drawings found; survey booked for 17 Nov"
    assert notes.ref_of(block.previous()) == ("capture", notes_page.pair_of(pointer.ref)[1])
