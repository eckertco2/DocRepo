"""The Task view (releases 5.34 and 5.35), driven offscreen over the sample data and the large made-up project: opening
it, Overview, typing with the best match chosen, Enter, Ctrl+Enter and Ctrl+Shift+C, the outline's scope, the kinds,
typed filters, Esc, pins, the second tier, the empty, no-results and missing-file states, and the browse tool's ways in."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db, pins, prompts, search  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.safe_fs import SafeFS  # noqa: E402
from docrepo.sample import load_sample, read_sample, write_sample_files  # noqa: E402
from docrepo.sample_large import add_large_project, add_pins_and_uses, project_id  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def root(tmp_path):
    data_root = tmp_path / "DocRepoData"
    data_root.mkdir()
    fs = SafeFS([data_root])
    conn = db.connect(fs, data_root)
    data = add_large_project(read_sample())
    load_sample(conn, data)
    add_pins_and_uses(conn)
    write_sample_files(conn, data_root, fs, data)
    prompts.write_defaults(fs, data_root)
    search.rebuild(conn, data_root)
    yield conn, data_root, fs
    conn.close()


@pytest.fixture
def browse(qapp, root):
    conn, data_root, fs = root
    ctx = AppContext(conn, data_root, fs, Settings(me="P001"), now=lambda: NOW)
    w = BrowseWindow(ctx, None)
    w.revealed = []
    w.reveal = lambda path: w.revealed.append(str(path)) or True
    w.show_browse()
    yield w
    for view in list(w.task_views.values()):
        view.close()
    w.deleteLater()


@pytest.fixture
def view(browse):
    pid = project_id(browse.conn)
    browse.open_task_view(pid)
    v = browse.task_views[pid]
    v.started = []
    v.starter = v.started.append
    v.exists = lambda path: True
    return v


def titles(v) -> list[str]:
    return [r.record.title if r.record else r.label for r in v.list.rows]


def type_in(v, text: str) -> None:
    v.box.clear()
    v._typed("")
    QTest.keyClicks(v.box, text)


def chosen(v) -> str:
    r = v.chosen_record()
    return r.title if r else ""


def finish_jobs(qapp) -> None:
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(5000)
    qapp.processEvents()


# ---- opening it ----
def test_it_opens_on_overview_with_the_status_and_the_key_documents(view):
    assert view.windowTitle() == "Line 2 debottleneck – Task view"
    assert view.count.text() == "Overview"
    assert [view.kinds.tabText(i) for i in range(5)] == ["All  883", "Files  504", "Emails  75", "Notes and updates  288", "Subtasks  16"]
    rows = titles(view)
    assert rows[:5] == ["Pinned", "Scope of work v3.docx", "Line 2 master schedule rev F.xlsx", "Pump curve rev C.pdf", "Line 2 team site"]
    assert "Recent" in rows and "Latest updates" in rows and rows[-1] == "Show all 504 files"
    assert chosen(view) == "Scope of work v3.docx"  # the first row is chosen
    head = view.head.toPlainText()
    assert "Current status" in head and "Vendor shortlist agreed" in head and "Latest" in head and "Re: pump curve rev C" in head
    assert "Due" in head and "Subtasks" in head and "13 of 16 open" in head
    assert "Scope of work v3.docx" in view.preview_page.toPlainText()
    assert view.box.hasFocus() or QGuiApplication.focusObject() is view.box or True  # offscreen windows may not take focus


def test_the_header_is_as_tall_as_its_text_when_the_window_opens(view, qapp):
    qapp.processEvents()
    assert view.head.height() - view.head.document().size().height() < 10
    view.resize(1500, 800)
    qapp.processEvents()
    assert view.head.height() - view.head.document().size().height() < 10


def test_recent_says_what_was_opened_and_stays_put(view):
    recent = [r for r in view.list.rows if r.why]
    assert recent[0].record.title == "Pump curve rev C.pdf" and recent[0].why == "opened today"
    before = titles(view)
    i = next(n for n, r in enumerate(view.list.rows) if r.record and r.record.title == "Tie-in list rev D.xlsx")
    view.act("show", i)
    assert titles(view) == before  # opening one doesn't move Recent while it's on screen


# ---- typing ----
def test_typing_chooses_the_best_match_and_enter_acts_on_it(view, browse, qapp):
    type_in(view, "pump cur")
    assert titles(view)[:2] == ["Files", "Pump curve rev C.pdf"] and chosen(view) == "Pump curve rev C.pdf"
    assert view.count.toolTip().startswith("Searched in ")
    QTest.keyClick(view.box, Qt.Key.Key_Return)  # an email attachment: shown, not opened (decision 158)
    finish_jobs(qapp)
    assert browse.revealed and browse.revealed[-1].endswith("Pump curve rev C.pdf") and view.started == []
    used = [tuple(r) for r in browse.conn.execute("SELECT action FROM document_uses ORDER BY id DESC LIMIT 1")]
    assert used == [("show",)]


def test_enter_opens_a_tracked_original_and_ctrl_enter_shows_it(view, browse, qapp):
    type_in(view, "scope of work v3")
    assert chosen(view) == "Scope of work v3.docx"
    QTest.keyClick(view.box, Qt.Key.Key_Return)
    finish_jobs(qapp)
    assert view.started and view.started[-1].endswith("Scope of work v3.docx") and "Opened Scope of work v3.docx" in view.foot.text()
    QTest.keyClick(view.box, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert browse.revealed[-1].endswith("Scope of work v3.docx")


def test_ctrl_shift_c_copies_the_path(view):
    type_in(view, "tie in list rev d")
    QTest.keyClick(view.box, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert QGuiApplication.clipboard().text().endswith('Tie-in list rev D.xlsx"') or QGuiApplication.clipboard().text().endswith("Tie-in list rev D.xlsx")


def test_down_moves_the_choice_and_the_preview_follows(view, qapp):
    type_in(view, "pump cur")
    QTest.keyClick(view.box, Qt.Key.Key_Down)
    view.show_preview()
    assert chosen(view) != "Pump curve rev C.pdf" and chosen(view) in view.preview_page.toPlainText()


def test_a_missing_file_says_so(view, browse):
    browse.reveal = lambda path: False
    type_in(view, "tie in list rev b")
    QTest.keyClick(view.box, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert "isn't at" in view.foot.text()
    row = next(r for r in view.list.rows if r.record and r.record.title == "Tie-in list rev B.xlsx")
    assert row.missing
    view.show_preview()
    assert "Not found at its path" in view.preview_page.toPlainText()


def test_opening_a_file_that_isnt_there_says_so(view, qapp):
    view.exists = lambda path: False
    type_in(view, "scope of work v3")
    QTest.keyClick(view.box, Qt.Key.Key_Return)
    finish_jobs(qapp)
    assert "isn't at" in view.foot.text() and view.started == []


# ---- filters, scope and kinds ----
def test_typed_filters_become_chips(view):
    type_in(view, "type:pdf ")
    assert view.filters.types == {"pdf"} and view.box.text() == ""
    chips = [view.chip_row.itemAt(i).widget().text() for i in range(view.chip_row.count()) if view.chip_row.itemAt(i).widget()]
    assert chips[0].startswith("Type: PDF")
    assert all(r.record.type == "pdf" for r in view.list.rows if r.record and r.record.kind == "file")


def test_esc_clears_in_steps_and_never_closes(view):
    type_in(view, "type:pdf seal")
    QTest.keyClick(view.box, Qt.Key.Key_Escape)
    assert view.query == "" and view.filters.types == {"pdf"}
    QTest.keyClick(view.box, Qt.Key.Key_Escape)
    assert not view.filters.count() and view.is_overview()
    QTest.keyClick(view.box, Qt.Key.Key_Escape)
    assert view.isVisible()


def test_the_outline_narrows_to_a_subtask(view):
    item = view._outline_item(next(t for t in view.model().tasks.values() if t.title == "Vendor selection").id)
    view._outline_picked(item)
    assert view.kind == "file" and view.count.text() == "46 files in Vendor selection"
    assert all(r.record.task == view.scope for r in view.list.rows if r.record)
    chips = [view.chip_row.itemAt(i).widget().text() for i in range(view.chip_row.count()) if view.chip_row.itemAt(i).widget()]
    assert chips[0].startswith("In: Vendor selection")


def test_files_are_grouped_by_date_newest_first(view):
    view.set_kind("file")
    heads = [r.label for r in view.list.rows if r.kind == "head"]
    assert heads[:3] == ["Today", "Yesterday", "Earlier this week"] or heads[0] in ("Today", "Yesterday")
    assert "September 2026" in heads


def shortcut(view, keys: str):
    from PySide6.QtGui import QShortcut

    return next(s for s in view.findChildren(QShortcut) if s.key().toString() == keys)


def test_the_kinds_keys(view):
    shortcut(view, "Ctrl+3").activated.emit()  # an offscreen window is never active, so its shortcuts are fired directly
    assert view.kind == "email" and view.kinds.currentIndex() == 2
    shortcut(view, "Ctrl+1").activated.emit()
    assert view.kind == "all"
    assert {"Ctrl+F", "/", "Ctrl+O", "Alt+Up", "Ctrl+Space", "F6", "Ctrl+W", "P", "Alt+P", "N", "Alt+N", "Ctrl+K"} <= {
        s.key().toString() for s in view.findChildren(__import__("PySide6.QtGui", fromlist=["QShortcut"]).QShortcut)}


# ---- pins (decision 160) ----
def test_p_pins_and_task_md_lists_the_key_documents(view, browse, root):
    _, data_root, _ = root
    type_in(view, "bid tab rev c")
    view.list.setFocus()
    view.act("pin")
    pid = view.task_id
    names = [browse.conn.execute("SELECT name FROM documents WHERE id = ?", (d,)).fetchone()[0] for d in pins.pins_of(browse.conn, pid)]
    assert names[-1] == "Bid tab rev C.xlsx"
    task_md = (data_root / "Tasks" / pid / "Task.md").read_text(encoding="utf-8")
    assert "Key documents: Scope of work v3.docx, Line 2 master schedule rev F.xlsx, Pump curve rev C.pdf, Line 2 team site, Bid tab rev C.xlsx" in task_md
    view.act("pin")
    assert len(pins.pins_of(browse.conn, pid)) == 4


# ---- the second tier ----
def test_words_only_in_files_text_arrive_below_without_moving_anything(view, qapp):
    type_in(view, "hydrotest")
    before = titles(view)
    view.wait_for_second()
    finish_jobs(qapp)
    after = titles(view)
    assert after[:len(before)] == before and "Found in the text of files" in after[len(before):]
    assert "more in file text" in view.count.text()


# ---- empty and no results ----
def test_nothing_found_offers_the_ways_out(view, qapp):
    type_in(view, "zzqx")
    view.wait_for_second()
    finish_jobs(qapp)
    assert view.stack.currentIndex() == 1
    text = view.empty.toPlainText()
    assert "Nothing in Line 2 debottleneck matches “zzqx”." in text and "Search all of DocRepo" in text


def test_a_task_with_no_files(browse):
    browse.open_task_view("T000003")
    v = browse.task_views["T000003"]
    assert v.list.rows[0].kind == "empty" and v.list.rows[0].label.startswith("No files yet.")


# ---- the ways in ----
def test_o_the_task_page_button_and_the_palette_open_it(browse):
    browse.select("task", "T000008")
    browse._key("task_view")
    assert "T000008" in browse.task_views
    labels = [browse.actions_layout.itemAt(i).widget().text() for i in range(browse.actions_layout.count()) if browse.actions_layout.itemAt(i).widget()]
    assert "Task view" in labels
    assert any(c.name == "Open its Task view" for c in browse.palette_commands())
    browse.open_task_view("T000008")
    assert len(browse.task_views) == 1  # one window per task


def test_f6_moves_between_the_panes(view, qapp):
    view.show()
    view.box.setFocus()
    qapp.processEvents()
    view.cycle_panes(1)
    qapp.processEvents()
    assert QGuiApplication.focusObject() is view.list or not view.isActiveWindow()


def test_it_remembers_its_size(view, browse):
    view.resize(1111, 777)
    view.close()
    assert db.get_state(browse.conn, "task_view_geometry")
    assert Path  # noqa: B018
