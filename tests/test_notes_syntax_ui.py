"""Release 5.150 in the windows, offscreen (the design workspace's notes syntax plan, decisions 652 to 657): a task line
drawn as its task's tile in the notes editor (its circle's state menu, its right-click menu, its words kept), a change
line kept whole (typing below it, Backspace, no heading, a click on its task), All notes' tiles and change lines, and
Tidy the notes from the browse window with Undo. ``test_notes_syntax.py`` has the rest, without Qt. Made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QContextMenuEvent, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import edits, markup, notes_page, task_tile  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import CaptureDraft, save_capture  # noqa: E402
from docrepo.ui import tidy_notes  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_edit import NotesEdit  # noqa: E402

SAVED = datetime(2026, 10, 16, 9, 30)
NOW = datetime(2026, 10, 16, 9, 45)
SETTINGS = Settings(me="P001")
INSTALLATION, RIGGING = "T000008", "T000012"
ROWS = ["- @Tom book the 50 t crane **due, Fri **label, Rigging", "#Rigging plan **due, 30 Nov **lead, Tom",
        "Seals look worn **label, Rigging", "Check the guard **lable, Safety"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def marked(lines: list[str]) -> str:
    return "\n".join("- " + markup.escape_inline(x[2:]) if x.startswith("- ") else markup.escape_inline(x) for x in lines)


@pytest.fixture
def setup(qapp, sample_root):
    conn, root, fs = sample_root
    conn.execute("UPDATE tasks SET due = NULL WHERE id = ?", (RIGGING,))
    conn.commit()
    save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=marked(ROWS), task=INSTALLATION, formatted=True), SAVED)
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.said = []
    w.say = lambda text, error=False: w.said.append((text, error))
    w.show_browse()
    w.resize(1440, 900)
    crane = next(t.id for t in Model(conn).tasks.values() if t.title == "Book the 50 t crane")
    yield w, crane
    capture.deleteLater()


def blocks(notes: NotesEdit) -> list:
    return list(notes.blocks())


def block_of(notes: NotesEdit, kind: str, n: int = 0):
    return [b for b in blocks(notes) if notes.kind(b) == kind][n]


# ---- the editor alone ----
def tile_for(task_id: str, title: str = "Book the 50 t crane, with the long spreader bar", state: str = "Not started"):
    return task_tile.Tile(task_id, title, state, "", False, "", -1, "", (None, None, None), None, state == "Closed")


@pytest.fixture
def notes(qapp):
    e = NotesEdit()
    e.resize(700, 400)
    e.page_task = INSTALLATION
    e.tile_of = lambda task_id: tile_for(task_id) if task_id == "T000020" else None
    e.show()
    yield e
    e.close()
    e.deleteLater()


PAGE = "\n".join([
    "# Fri 16 Oct 2026",
    notes_page.task_line("Task: Book the 50 t crane · Tom Becker · due Fri 23 Oct", "T000020"),
    notes_page.change_line("Rigging plan", RIGGING, "Due Mon 30 Nov · Lead Tom Becker"),
    notes_page.change_line("Seals look worn", INSTALLATION, "Rigging", 1),
    notes_page.set_line("Set from Installation's notes", INSTALLATION, "Due Fri 23 Oct"),
    "Last line.",
])


def test_the_page_comes_back_as_it_was_kept(notes):
    notes.set_page(PAGE)
    assert [notes.kind(b) for b in blocks(notes)] == ["heading", "task", "change", "change", "set", "text"]
    assert block_of(notes, "task").text() == "Book the 50 t crane, with the long spreader bar"  # the tile's title (decision 652)
    assert block_of(notes, "change").text() == "Rigging plan · Due Mon 30 Nov · Lead Tom Becker"
    assert notes.page() == PAGE  # the task line kept as it was written, the change line at its list level


def test_a_task_line_is_drawn_as_its_tile(notes):
    notes.set_page(PAGE)
    QApplication.processEvents()
    b = block_of(notes, "task")
    parts = notes.tile_parts(b)
    assert parts and parts[0][1] == "circle" and parts[0][2] == "T000020"
    picked = []
    notes.tile_state.connect(lambda task, at: picked.append(task))
    QTest.mouseClick(notes.viewport(), Qt.MouseButton.LeftButton, pos=parts[0][0].center())
    assert picked == ["T000020"]
    menus = []
    notes.tile_menu.connect(lambda task, at: menus.append(task))
    pos = notes.cursorRect(QTextCursor(b)).center() + QPoint(30, 0)
    notes.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, notes.viewport().mapToGlobal(pos)))
    assert menus == ["T000020"]
    notes.tile_of = None  # a task gone: its words, as written
    notes.set_page(PAGE)
    assert block_of(notes, "task").text() == "Task: Book the 50 t crane · Tom Becker · due Fri 23 Oct" and not notes.tile_parts(block_of(notes, "task"))


def test_a_change_line_is_kept_whole(notes):
    """Decision 657: typing on a change line goes to the line below, Backspace removes it, and it's never a heading."""
    notes.set_page(PAGE)
    c = QTextCursor(block_of(notes, "change"))
    notes.setTextCursor(c)
    QTest.keyClicks(notes, "x")
    assert "[Rigging plan](change:T000012) · Due Mon 30 Nov · Lead Tom Becker" in notes.page().split("\n")
    notes.setTextCursor(QTextCursor(block_of(notes, "change")))
    notes.set_heading(2)
    assert notes.kind(block_of(notes, "change")) == "change"
    notes.setTextCursor(QTextCursor(block_of(notes, "change")))
    QTest.keyClick(notes, Qt.Key.Key_Backspace)
    assert "change:T000012" not in notes.page()


def test_a_click_on_a_change_line_opens_the_task_it_changed(notes):
    notes.set_page(PAGE)
    QApplication.processEvents()
    opened = []
    notes.open_ref.connect(opened.append)
    for b in (block_of(notes, "change", 0), block_of(notes, "change", 1)):
        QTest.mouseClick(notes.viewport(), Qt.MouseButton.LeftButton, pos=notes.cursorRect(QTextCursor(b)).center() + QPoint(8, 0))
    assert opened == [RIGGING]  # not the page's own task


# ---- in the browse window ----
def test_the_task_page_draws_tiles_and_their_menus(setup, monkeypatch):
    w, crane = setup
    w.go_task(INSTALLATION)
    QApplication.processEvents()
    notes = w.task_pane.notes
    assert notes.page_task == INSTALLATION and notes.tile_of is not None
    b = block_of(notes, "task")
    assert b.text() == "Book the 50 t crane" and notes.tile_parts(b)
    shown = []
    monkeypatch.setattr(w, "run_menu", lambda menu, at: shown.append([a.text().split("\t")[0] for a in menu.actions() if a.text()]))
    notes.tile_menu.emit(crane, QPoint(0, 0))
    notes.tile_state.emit(crane, QPoint(0, 0))
    assert shown[0][0] == "Open" and "In progress" in shown[1]
    assert [notes.kind(x) for x in blocks(notes) if notes.kind(x) == "change"] == ["change", "change"]


def test_all_notes_draws_tiles_and_change_lines(setup):
    w, crane = setup
    w.go_task(INSTALLATION)
    QApplication.processEvents()
    w._set_notes_mode("all")
    QApplication.processEvents()
    view = w.task_pane.all_view
    html, text = view.toHtml(), view.toPlainText()
    assert f"state:{crane}" in html  # the tile's circle opens the state menu (decision 652)
    assert "Rigging plan · Due Mon 30 Nov · Lead Tom Becker" in text and "Seals look worn · Rigging" in text
    assert "Set from Installation's notes · Due Fri 23 Oct · Rigging" in text  # the made task's block, under the meeting's day
    assert "Check the guard **lable, Safety" in text  # read as nothing: as typed
    w._set_notes_mode("page")


def test_tidy_the_notes_from_the_browse_window_with_undo(setup):
    w, crane = setup
    conn, data_root = w.conn, w.ctx.data_root
    model, stories = edits.stories_for(conn, data_root, SAVED)
    c = next(x for x in model.notes_of(crane))
    old = notes_page.block(model, stories, c, crane, notes_page.typed_content(c, stories.content_of(c.id)), rewrite=False)
    new = notes_page.get(conn, crane)
    notes_page.put(conn, crane, notes_page.add_block("", old, SAVED.date(), True), SAVED)
    conn.commit()
    w.refresh()
    seen = []

    def accept(dialog) -> bool:
        seen.append([dialog.rows.item(i).text() for i in range(dialog.rows.count())])
        return True

    w.run_dialog = accept
    w.go_task(crane)
    QApplication.processEvents()
    assert tidy_notes.run(w, crane)
    assert seen[0] == ["@Tom Becker book the 50 t crane **due, Fri **label, Rigging  →  "
                       "Tom Becker book the 50 t crane / Set from Installation's notes · Due Fri 23 Oct · Rigging"]
    assert notes_page.get(conn, crane) == new and "Tidied 1 line on Book the 50 t crane's notes." in w.said[-1][0]
    w._undo()
    QApplication.processEvents()
    assert "\\*\\*due, Fri" in notes_page.get(conn, crane)
    w.run_dialog = lambda dialog: False
    assert not tidy_notes.run(w, crane)  # cancelled: nothing changes
    assert "\\*\\*due, Fri" in notes_page.get(conn, crane)
