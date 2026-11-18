"""The heading list in the windows, offscreen (release 5.156, the design workspace's notes topics plan, decisions 704 to
708): typing in a topic heading on a notes page lists the topic headings already used; Enter keeps what's typed unless a
row is highlighted, Tab takes the top row, Esc closes it, Ctrl+Space shows it at once; no list on a day heading or a
line of text; the browse window's task page and the capture window (a picked task, Meeting notes' home task). Made up;
``test_topics.py`` has the rows' rules, without Qt."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from docrepo import notes_page, topics  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_edit import NotesEdit  # noqa: E402
from docrepo.ui.task_list import can_pick  # noqa: E402
from notes_example import SETTINGS, build  # noqa: E402

NOW = datetime(2026, 11, 17, 9, 0)
FILL = "\n".join(["# Tue 10 Nov 2026", "# Vendor", "## Quotes", "Vendor B 18 % under vendor A.", "## Lead time", "12 weeks.",
                  "# Thu 12 Nov 2026", "# Vendor", "## Lead time", "10 weeks for a premium.", "# Delivery", "By 1 Dec.",
                  "# Tue 17 Nov 2026", "Today's line."])
PROJECT = "# Mon 2 Nov 2026\n# Schedule\nOutage 9 to 20 Mar.\n# Safety\nA standby person."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ex(sample_root):
    conn, root, fs = sample_root
    out = build(conn, root, fs)
    notes_page.put(conn, out.fill, FILL, NOW)
    notes_page.put(conn, out.project, PROJECT, NOW)
    return out


@pytest.fixture
def page(qapp, sample_root, ex):
    """Fill media order's page in a notes editor of its own, in a window that holds the list."""
    host = QWidget()
    host.resize(760, 520)
    notes = NotesEdit()
    QVBoxLayout(host).addWidget(notes)
    notes.page_task = ex.fill
    model = Model(sample_root[0])
    notes.heading_options = lambda level, typed, under, own: topics.options(model, ex.fill, level, typed, under, own, own_page=ex.fill)
    notes.set_page(FILL)
    host.show()
    host.activateWindow()
    notes.setFocus()
    QApplication.processEvents()
    yield notes
    host.close()
    host.deleteLater()


def new_heading(notes: NotesEdit, level: int = 1) -> None:
    """A new line at the page's end, made a heading as Ctrl+Alt+1, 2 or 3 does."""
    c = notes.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    notes.setTextCursor(c)
    QTest.keyClick(notes, Qt.Key.Key_Return)
    notes.set_heading(level)


def typed(notes: NotesEdit, words: str) -> None:
    QTest.keyClicks(notes, words)
    QApplication.processEvents()
    QApplication.processEvents()


def shown(notes: NotesEdit) -> list[str]:
    hl = notes._heading_list
    if hl is None or not hl.isVisible():
        return []
    return [r.label for r in hl.rows()]


def test_typing_in_a_heading_lists_the_task_s_headings_then_its_project_s(page, ex):
    new_heading(page)
    assert shown(page) == []  # nothing typed yet (decision 704)
    typed(page, "s")
    assert shown(page) == ["Elsewhere in Cooling tower 2 rebuild", "Safety", "Schedule"]  # both last used Mon 2 Nov: by their words
    typed(page, "a")
    assert shown(page) == ["Elsewhere in Cooling tower 2 rebuild", "Safety"]
    page.textCursor().block()  # the line being typed isn't a row of its own
    QTest.keyClick(page, Qt.Key.Key_Backspace)
    QTest.keyClick(page, Qt.Key.Key_Backspace)
    QApplication.processEvents()
    QApplication.processEvents()
    assert shown(page) == []  # nothing typed: no list
    typed(page, "d")
    assert shown(page) == ["Delivery"]
    assert page._heading_list.highlighted() is None  # nothing highlighted until Down (decision 706)
    rows = page._heading_list.rows()
    assert rows[0].sub == "once · Thu 12 Nov 2026" or rows[0].sub.startswith("once · Thu 12 Nov")


def test_enter_keeps_what_s_typed_unless_a_row_is_highlighted(page):
    new_heading(page)
    typed(page, "Del")
    QTest.keyClick(page, Qt.Key.Key_Return)
    QApplication.processEvents()
    block = page.textCursor().block()
    assert block.previous().text() == "Del" and page.topic_level(block.previous()) == 1  # kept as typed
    assert block.text() == "" and not block.blockFormat().headingLevel()  # and a line of text below, as Enter on a heading starts
    assert shown(page) == []
    new_heading(page)
    typed(page, "de")
    assert shown(page) == ["Del", "Delivery"]  # the heading just kept is one of the page's now, the latest
    typed(page, "l")
    QTest.keyClick(page, Qt.Key.Key_Down)
    QTest.keyClick(page, Qt.Key.Key_Down)
    assert page._heading_list.highlighted().value == "Delivery"
    QTest.keyClick(page, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert page.textCursor().block().text() == "Delivery" and page.topic_level(page.textCursor().block()) == 1
    assert shown(page) == []
    assert "\n# Delivery" in page.page()


def test_tab_takes_the_top_row_and_esc_closes_it(page):
    new_heading(page)
    typed(page, "sa")
    QTest.keyClick(page, Qt.Key.Key_Tab)
    QApplication.processEvents()
    assert page.textCursor().block().text() == "Safety"
    new_heading(page)
    typed(page, "s")
    QTest.keyClick(page, Qt.Key.Key_Escape)
    assert shown(page) == []
    QTest.keyClick(page, Qt.Key.Key_Right)  # moving along the line doesn't bring it back
    QApplication.processEvents()
    assert shown(page) == []
    typed(page, "c")
    assert shown(page) == ["Elsewhere in Cooling tower 2 rebuild", "Schedule"]  # typing does


def test_ctrl_space_shows_it_at_once_and_a_level_2_line_starts_with_its_heading_s(page):
    new_heading(page)
    typed(page, "Vendor")
    QTest.keyClick(page, Qt.Key.Key_Escape)
    QTest.keyClick(page, Qt.Key.Key_Return)
    page.set_heading(2)
    QTest.keyClick(page, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    rows = page._heading_list.rows()
    assert [r.label for r in rows if can_pick(r)] == ["Lead time", "Quotes"]
    assert rows[0].sub.startswith("under Vendor · twice · last Thu 12 Nov")
    page._heading_list.picked.emit(rows[1])  # a click
    assert page.textCursor().block().text() == "Quotes"


def test_no_list_on_text_or_a_day_heading(page):
    c = page.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    page.setTextCursor(c)
    typed(page, " sa")
    assert shown(page) == []  # a line of text
    QTest.keyClick(page, Qt.Key.Key_Return)
    page.set_heading(1)
    typed(page, "Wed 18 Nov 2026")
    assert shown(page) == []  # a day heading is never a topic
    QTest.keyClick(page, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert shown(page) == []


def test_the_browse_window_s_task_page_has_the_list(qapp, sample_root, ex):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    try:
        w.go_task(ex.survey)
        QApplication.processEvents()
        notes = w.task_pane.notes
        assert notes.page_task == ex.survey
        got = notes.heading_options(1, "", "", [])
        assert got.here == [] and [r.words for r in got.others] == ["Delivery", "Vendor", "Safety", "Schedule"]
        assert got.elsewhere == "Cooling tower 2 rebuild"
    finally:
        w.close()
        capture.deleteLater()


def test_the_capture_window_lists_its_task_s_or_the_meeting_s_home_task_s(qapp, sample_root, ex):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    try:
        assert capture.content.heading_options is not None
        assert capture.heading_task() is None  # no task picked: no list
        capture.task = ex.fill
        assert capture.heading_task() == ex.fill
        assert [r.words for r in capture.content.heading_options(1, "v", "", []).here] == ["Vendor"]
        capture.task = ex.weekly  # Meeting notes on a meeting under the project: its home task's headings (decision 610)
        capture.meeting_on = True
        assert capture.heading_task() == ex.project
        assert {r.words for r in capture.content.heading_options(1, "", "", []).here} >= {"Schedule", "Safety", "Vendor", "Delivery"}
        capture.show()
        capture.ref_popup.show()
        assert capture.content.other_list_open()  # the @ and # list wins
    finally:
        capture.deleteLater()
