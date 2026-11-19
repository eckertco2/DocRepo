"""Stock headings in the windows, offscreen (release 5.169, the design workspace's stock headings plan, decisions 789 to
792): Ctrl+Space on an empty level 1 heading of a task with no notes lists them under "Stock headings"; one the page has
is listed with the task's own, its tooltip saying what belongs under it; what belongs under one shows on the empty line
below and never in the text (not saved, searched or matched for tagged labels), going once something is written; the
capture window lists them before a task is picked; Settings' Stock headings card adds, removes, restores and saves them,
writing the agents' page. Made up; ``test_stock_headings.py`` has the rules, without Qt."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from docrepo import notes_page, search, tagged, topics  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.pages import STOCK_PAGE  # noqa: E402
from docrepo.stock_headings import DEFAULTS  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.heading_list import STOCK  # noqa: E402
from docrepo.ui.notes_edit import NotesEdit  # noqa: E402
from docrepo.ui.settings_view import SettingsView  # noqa: E402
from docrepo.ui.task_list import OPTION_ROLE, can_pick  # noqa: E402
from notes_example import SETTINGS, build  # noqa: E402

NOW = datetime(2026, 11, 18, 9, 0)
PATH_FORWARD = "What happens next, in order, and who does each step."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ex(sample_root):
    conn, root, fs = sample_root
    return build(conn, root, fs)


def editor(qapp, model, task_id: str, page: str):
    host = QWidget()
    host.resize(760, 520)
    notes = NotesEdit()
    QVBoxLayout(host).addWidget(notes)
    notes.page_task = task_id
    notes.heading_options = lambda level, typed, under, own: topics.options(model, task_id, level, typed, under, own, own_page=task_id,
                                                                            stock=DEFAULTS)
    notes.stock_headings = lambda: list(DEFAULTS)
    notes.set_page(page)
    host.show()
    host.activateWindow()
    notes.setFocus()
    QApplication.processEvents()
    return host, notes


def to_end(notes: NotesEdit) -> None:
    c = notes.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    notes.setTextCursor(c)


def ctrl_space(notes: NotesEdit) -> list:
    QTest.keyClick(notes, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    hl = notes._heading_list
    return hl.rows() if hl is not None and hl.isVisible() else []


def test_ctrl_space_on_an_empty_heading_of_a_task_with_no_notes_lists_them(qapp, sample_root, ex):
    host, notes = editor(qapp, Model(sample_root[0]), ex.crane, "")
    try:
        notes.set_heading(1)
        rows = ctrl_space(notes)
        assert [r.label for r in rows] == [STOCK, "Background", "Path forward", "Decisions", "Open questions"]
        assert not can_pick(rows[0]) and rows[2].sub == PATH_FORWARD
        tips = [notes._heading_list.item(i).toolTip() for i in range(notes._heading_list.count())]
        assert PATH_FORWARD in tips[2]
        notes._heading_list.picked.emit(rows[2])
        assert notes.textCursor().block().text() == "Path forward"
    finally:
        host.close()
        host.deleteLater()


def test_one_the_page_has_is_the_task_s_own_with_what_belongs_under_it(qapp, sample_root, ex):
    host, notes = editor(qapp, Model(sample_root[0]), ex.crane, "# Wed 18 Nov 2026\n# Background\nTwo cranes quoted.")
    try:
        to_end(notes)
        QTest.keyClick(notes, Qt.Key.Key_Return)
        notes.set_heading(1)
        rows = ctrl_space(notes)
        labels = [r.label for r in rows]
        assert labels[0] == "Background" and labels.count("Background") == 1 and labels[1] == STOCK
        hl = notes._heading_list
        first = next(hl.item(i) for i in range(hl.count()) if hl.item(i).data(OPTION_ROLE).label == "Background")
        assert "Stock heading: Why this task exists" in first.toolTip()
    finally:
        host.close()
        host.deleteLater()


def test_the_muted_line_is_never_in_the_text_and_goes_once_written(qapp, sample_root, ex):
    conn, root, fs = sample_root
    host, notes = editor(qapp, Model(conn), ex.crane, "# Wed 18 Nov 2026\n# Path forward\n\n# Vendor\nTwo cranes.")
    try:
        doc = notes.document()
        blocks = [doc.findBlockByNumber(i) for i in range(doc.blockCount())]
        hints = {b.text() or f"(empty {b.blockNumber()})": notes.stock_hint(b) for b in blocks}
        assert [w for w in hints.values() if w] == [PATH_FORWARD]
        empty = next(b for b in blocks if not b.text())
        assert notes.stock_hint(empty) == PATH_FORWARD
        notes.grab()  # painted without error
        saved = notes.page()
        assert "What happens next" not in saved and "What happens next" not in doc.toPlainText()
        # Saved as the page, it isn't searched or matched for tagged labels: it isn't in the text they read.
        notes_page.put(conn, ex.crane, saved, NOW)
        conn.commit()
        search.rebuild(conn, root)
        assert not [r for r in search.search(conn, Model(conn), "happens") if r.id == ex.crane]
        assert "happens" not in tagged.words_of(saved)
        c = QTextCursor(empty)
        notes.setTextCursor(c)
        QTest.keyClicks(notes, "C")
        QApplication.processEvents()
        assert notes.stock_hint(notes.textCursor().block()) == ""
        # A heading the owner made that isn't a stock heading, or one with words under it, shows nothing.
        assert all(not notes.stock_hint(doc.findBlockByNumber(i)) for i in range(doc.blockCount()))
    finally:
        host.close()
        host.deleteLater()


def test_a_heading_with_words_below_its_empty_line_shows_nothing(qapp, sample_root, ex):
    host, notes = editor(qapp, Model(sample_root[0]), ex.crane, "# Wed 18 Nov 2026\n# Decisions\n\nGo with vendor B.")
    try:
        doc = notes.document()
        assert all(not notes.stock_hint(doc.findBlockByNumber(i)) for i in range(doc.blockCount()))
    finally:
        host.close()
        host.deleteLater()


def test_the_capture_window_lists_them_before_a_task_is_picked(qapp, sample_root, ex):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, replace(SETTINGS), now=lambda: NOW)
    capture = CaptureWindow(ctx)
    try:
        assert capture.heading_task() is None
        got = capture.content.heading_options(1, "", "", [])
        assert [r.words for r in got.stock] == ["Background", "Path forward", "Decisions", "Open questions"]
        assert capture.content.stock_headings() == list(DEFAULTS)
        capture.task = ex.fill
        assert [r.words for r in capture.content.heading_options(1, "pa", "", []).stock] == ["Path forward"]
    finally:
        capture.deleteLater()


def test_the_settings_card_adds_removes_restores_and_saves(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, replace(SETTINGS), now=lambda: NOW)
    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    card = view.stock
    assert [r[0].text() for r in card.rows] == ["Background", "Path forward", "Decisions", "Open questions"]
    assert view.save() == []  # nothing changed
    card.add.click()
    name, level, about, _remove = card.rows[-1]
    name.setText("Risks")
    level.setCurrentIndex(level.findData(2))
    about.setText("What could go wrong, and what's being done about it.")
    card.rows[0][3].click()  # Remove Background
    assert view.save() == ["stock_headings"]
    assert [h.name for h in ctx.settings.stock()] == ["Path forward", "Decisions", "Open questions", "Risks"]
    data = json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert data["stock_headings"][-1] == {"name": "Risks", "level": 2, "description": "What could go wrong, and what's being done about it."}
    page = root.joinpath(*STOCK_PAGE).read_text(encoding="utf-8")
    assert "| Risks | 2 |" in page and "| Background |" not in page
    assert "Stock headings: Path forward, Decisions, Open questions and Risks." in (root / "Contents.md").read_text(encoding="utf-8")
    card.add.click()
    card.rows[-1][2].setText("Words with no name")
    assert view.save() == [] and "needs a name" in view.error.text()
    card.restore.click()
    assert [r[0].text() for r in card.rows] == ["Background", "Path forward", "Decisions", "Open questions"]
    assert view.save() == ["stock_headings"]
    assert "stock_headings" not in json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert "| Background | 1 |" in root.joinpath(*STOCK_PAGE).read_text(encoding="utf-8")
