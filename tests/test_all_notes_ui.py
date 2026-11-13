"""Release 5.140 in the browse window, offscreen (the design workspace's notes consolidation plan, decisions 602 to 607):
the Notes heading's switch, All notes in the frame with its outline, its links, Edit there and Alt+Left back, and the
Meetings section's rows. ``test_all_notes.py`` and ``test_meeting_rows.py`` have the rest, without Qt. Made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from notes_example import SETTINGS, build  # noqa: E402

NOW = datetime(2026, 11, 12, 9, 0)


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


def folds(w, task_id: str) -> dict:
    return json.loads(db.get_state(w.conn, f"page_folds:{task_id}") or "{}")


def test_the_switch_shows_where_there_s_more_to_read(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.project)
    QApplication.processEvents()
    assert not pane.mode_strip.isHidden() and pane.mode_buttons["page"].isChecked() and not pane.all_mode
    w.go_task(ex.fill)  # nothing under it and no task line on its page
    QApplication.processEvents()
    assert pane.mode_strip.isHidden() and not pane.all_mode


def test_all_notes_in_the_frame_kept_per_task(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.project)
    QApplication.processEvents()
    pane.mode_buttons["all"].click()
    QApplication.processEvents()
    assert pane.all_mode and not pane.all_row.isHidden() and pane.notes_row.isHidden() and folds(w, ex.project)["all_notes"] is True
    text = pane.text()
    assert "Shutdown window: Tom thinks" in text and "follow-up, on its page" in text and "rev C" in text
    entries = [words for _n, _level, _day, words in pane.all_outline.entries()]
    assert entries[:3] == ["Tue 3 Nov 2026", "Tue 10 Nov 2026", "Wed 11 Nov 2026"] and "Pages" in entries and "Cooling tower kickoff" in entries
    w.go_task(ex.survey)
    QApplication.processEvents()
    assert not pane.all_mode  # the survey's own choice: This page
    w.go_task(ex.project)
    QApplication.processEvents()
    assert pane.all_mode and pane.mode_buttons["all"].isChecked()
    pane.mode_buttons["page"].click()
    QApplication.processEvents()
    assert not pane.all_mode and folds(w, ex.project)["all_notes"] is False and "Outage" not in pane.text()


def test_a_page_from_the_outline_and_show_every_page(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.project)
    pane.mode_buttons["all"].click()
    QApplication.processEvents()
    number = next(n for n, (kind, key) in enumerate(pane._all_targets) if (kind, key) == ("page", ex.survey))
    pane._all_picked(number)
    QApplication.processEvents()
    assert w.state.notes_only == ex.survey and "Attendees" not in pane.text() and "rev C" in pane.text()
    w.on_link(QUrl("allnotes:only:"))
    QApplication.processEvents()
    assert w.state.notes_only == "" and "Attendees" in pane.text()


def test_edit_there_opens_the_block_on_its_page_and_alt_left_comes_back(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.project)
    pane.mode_buttons["all"].click()
    QApplication.processEvents()
    w.on_link(QUrl(f"notesgo:{ex.kickoff}:{ex.kickoff_notes}"))
    QApplication.processEvents()
    assert w.sel == ("task", ex.kickoff) and not pane.all_mode and "Alt+Left goes back" in w.said[-1][0]
    assert pane.notes.textCursor().block().text()  # the caret is on the block
    QTest.keyClick(pane, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    QApplication.processEvents()
    assert w.sel == ("task", ex.project) and pane.all_mode


def test_a_double_click_finds_its_block(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.project)
    pane.mode_buttons["all"].click()
    QApplication.processEvents()
    view = pane.all_view
    doc = view.document()
    b = doc.begin()
    while b.isValid() and "Vendor says fill lead time" not in b.text():
        b = b.next()
    rect = doc.documentLayout().blockBoundingRect(b)
    found = view.block_at(rect.center().toPoint())  # the view is as tall as its page, so its points are the document's
    assert found == (ex.kickoff, ex.kickoff_notes)


def test_a_meeting_row_unfolds(setup):
    w, ex = setup
    pane = w.task_pane
    w.go_task(ex.fill)
    QApplication.processEvents()
    assert "Cooling tower kickoff" in pane.text() and "made this task" in pane.text() and "Attendees" not in pane.text()
    w.on_link(QUrl(f"meetrow:{ex.kickoff}"))
    QApplication.processEvents()
    assert w.state.meeting_open == ex.kickoff and "Vendor says fill lead time" in pane.text()
    w.go_task(ex.survey)
    QApplication.processEvents()
    assert w.state.meeting_open == ""  # each task's own
