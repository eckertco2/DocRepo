"""The Task view's painted list (release 5.34, ``docrepo.ui.result_list``; a test of its own in release 5.102), offscreen:
its rows' heights and words for a screen reader, the keyboard's steps past headings, the quick actions on a file row,
a heading's fold and a double-click, and that every kind of row paints."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.overview import Record  # noqa: E402
from docrepo.ui.result_list import (  # noqa: E402
    ACTIONS, COMPACT_HEIGHT, HEAD_HEIGHT, ITEM_HEIGHT, MORE_HEIGHT, ROW_ROLE, ResultList, Row,
)

TODAY = date(2026, 10, 8)
PDF = Record("file", "D000001", "T000001", "2026-10-07 09:15:00", "Impeller datasheet rev B.pdf", desc="Rev B", type="pdf",
             source="Tracked original", came="an email from Ann Example")
ATTACHED = Record("file", "D000002", "T000001", "2026-10-06 10:00:00", "Lift plan.docx", type="doc", source="Email attachment",
                  came="an email from Sam Example")
LINK = Record("file", "D000003", "T000001", "2026-10-05 10:00:00", "Vendor portal", type="link", source="Link", came="a Note")
EMAIL = Record("email", "C000003", "T000001", "2026-10-07 09:15:00", "Crane booking", desc="Ann Example", type="mail", sender="Ann Example")
NOTE = Record("note", "C000001", "T000001", "2026-10-01 08:00:00", "Kickoff", text="Kickoff. Agreed the scope.", type="note")
TASK = Record("task", "T000008", "T000001", "2026-09-01 08:00:00", "Installation", state="In progress")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp):
    v = ResultList(TODAY)
    v.resize(700, 600)
    v.set_rows([Row("head", label="Files", count=3, fold="files"), Row("item", PDF), Row("item", ATTACHED, pinned=True),
                Row("item", LINK, missing=True), Row("head", label="Emails", count=1, fold="emails"), Row("item", EMAIL),
                Row("head", label="Notes", count=1), Row("item", NOTE, words=["scope"]), Row("item", TASK, subtask="Installation"),
                Row("more", label="Show all 12 notes", more="note"), Row("tip", label="Type to search"),
                Row("empty", label="Nothing here\nDrop files on this window.")], choose=1)
    v.show()
    yield v
    v.hide()  # hidden and deleted, as the wheel's tests do, so nothing is left to take a later window's place in front
    v.deleteLater()
    QApplication.processEvents()


def test_rows_have_their_heights_and_words(view):
    hint = lambda i: view.delegate.sizeHint(None, view.model_.index(i)).height()  # noqa: E731 - a short local helper
    assert [hint(i) for i in (0, 1, 8, 9)] == [HEAD_HEIGHT, ITEM_HEIGHT, COMPACT_HEIGHT, MORE_HEIGHT]  # a subtask with no facts is one line
    view.compact = True
    assert hint(1) == COMPACT_HEIGHT
    view.compact = False
    access = lambda i: view.model_.index(i).data(Qt.ItemDataRole.AccessibleTextRole)  # noqa: E731
    assert access(0) == "Files, 3"
    assert access(2) == "Lift plan.docx, DOC, added 2026-10-06, pinned"
    assert access(3) == "Vendor portal, link, added 2026-10-05, missing"
    assert access(5) == "Crane booking, email, 2026-10-07"
    assert access(8) == "Installation, subtask, Installation, 2026-09-01"
    assert view.model_.index(1).data(ROW_ROLE) is view.rows[1]
    assert not view.model_.flags(view.model_.index(0)) & Qt.ItemFlag.ItemIsSelectable
    assert view.model_.flags(view.model_.index(9)) & Qt.ItemFlag.ItemIsSelectable  # "Show all" is chosen as a row is


def test_the_keyboard_steps_past_headings(view):
    assert view.current() == 1
    view.step(1)
    assert view.current() == 2
    view.step("next group")
    assert view.current() == 5  # the first row after the Emails heading
    view.step("previous group")
    assert view.current() == 1
    view.step("last")
    assert view.current() == 9
    view.step(5)
    assert view.current() == 9  # it stays on the last
    view.step("first")
    assert view.current() == 1
    chosen = []
    view.chosen.connect(chosen.append)
    view.step(1)
    assert chosen == [2]


def test_each_kind_of_record_has_its_line_icon_and_actions(view):
    d = view.delegate
    assert d.second_line(view.rows[1]) == "Rev B · from an email from Ann Example"
    assert d.second_line(Row("item", NOTE)) == "Agreed the scope."
    assert d.second_line(Row("item", PDF, snippet="rated flow 120", where="Installation")) == "Installation · in its text: rated flow 120"
    assert d.icon_of(PDF)[0] == "type-pdf" and d.icon_of(EMAIL)[0] == "type-mail" and d.icon_of(TASK)[0] == "state-ip"
    assert d.icon_of(NOTE)[0] == "note"
    assert d.actions_for(PDF) == ACTIONS
    assert [n for n, _, _ in d.actions_for(ATTACHED)] == ["copy", "show"]  # an attachment is never opened
    assert [n for n, _, _ in d.actions_for(LINK)] == ["copylink"]
    assert d.state_rect(view.rows[8], view.visualRect(view.model_.index(8))) is not None
    assert d.state_rect(view.rows[1], view.visualRect(view.model_.index(1))) is None


def test_a_file_rows_quick_action_is_clicked(view, qapp):
    names = []
    view.action.connect(lambda row, name: names.append((row, name)))
    rect = view.visualRect(view.model_.index(1))
    open_button = QPoint(rect.right() - 12 - 28 * 3 + 14, rect.center().y())  # the third from the right: Open
    assert view.delegate.action_at(view.rows[1], rect, open_button) == "open"
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, open_button)
    assert names == [(1, "open")]
    assert view.delegate.action_at(view.rows[5], view.visualRect(view.model_.index(5)), open_button) is None  # an email has none


def test_a_heading_folds_and_a_double_click_opens(view, qapp):
    folded, opened = [], []
    view.folded.connect(folded.append)
    view.activated_row.connect(opened.append)
    head = view.visualRect(view.model_.index(4)).center()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, head)
    assert folded == ["emails"]
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, view.visualRect(view.model_.index(5)).center())
    assert opened == [5]


def test_every_kind_of_row_paints(view, qapp):
    image = view.grab().toImage()  # every row is in sight: the twelve take 538 px of the 600
    assert sum(view.delegate.sizeHint(None, view.model_.index(i)).height() for i in range(len(view.rows))) < view.viewport().height()
    assert not image.isNull() and len({image.pixel(x, y) for x in range(0, image.width(), 7) for y in range(0, image.height(), 7)}) > 3
