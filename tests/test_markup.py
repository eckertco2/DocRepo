"""Formatted content text (mods log round 2, M0045): the markup in capture.md, and the box that edits it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import markup  # noqa: E402

TRICKY = [
    "Plain text.", "Rate *2* and 3*4", "~~not struck~~ and ~one", "<u>not a tag</u> <b>", "C:\\Docs\\Pump curve.txt",
    "\\\\server\\share\\a.pdf", "ends with a backslash \\", "a\\*b and a\\-b", "- not a list", "  12. not a list either",
    "-5 C overnight", "1.5 bar", "", "  ", "**Closed. operators stay text**", "Line one\nLine two\n\n- dash line",
]


@pytest.mark.parametrize("text", TRICKY)
def test_plain_text_survives_escaping(text):
    escaped = markup.escape(text)
    assert markup.to_plain(escaped) == text and not markup.is_formatted(escaped)


def test_reading_markup():
    m = ("Pump **curve** at *62 rpm*, <u>check</u> ~~Friday~~ <mark class=\"green\">today</mark>\n"
         "- first\n  - nested \\*star\n1. one\n2. two\nC:\\Docs\\a.pdf")
    assert markup.to_plain(m) == "Pump curve at 62 rpm, check Friday today\n- first\n  - nested *star\n1. one\n2. two\nC:\\Docs\\a.pdf"
    assert markup.is_formatted(m) and markup.is_formatted("- a list") and not markup.is_formatted("\\- not a list")
    page = markup.to_html(m)
    assert "<b>curve</b>" in page and "<i>62 rpm</i>" in page and "<u>check</u>" in page and "<s>Friday</s>" in page
    assert "background-color:#cdeccd" in page and page.count("<ul") == 2 and page.count("<ol") == 1
    assert page.index("nested") < page.index("</li></ul></li></ul>")  # the nested list sits inside its item


def test_marks_always_nest():
    line = markup.marks_text([("a", frozenset({"b"}), None), ("b", frozenset({"b", "i"}), None), ("c", frozenset({"i", "mark"}), "pink"),
                              ("d", frozenset(), None)])
    assert line == '**a*b**<mark class="pink">c</mark>*d'
    assert markup.to_plain(line) == "abcd" and markup.inline_html(line).startswith("<b>a</b>")


def test_clip_and_the_title_line():
    m = "Coupling guard notes\n- **guard** fitted\n- rails painted\n- bolts torqued"
    assert markup.without_title_line(m, "Coupling guard notes") == "- **guard** fitted\n- rails painted\n- bolts torqued"
    assert markup.without_title_line(m, "Something else") == m
    assert markup.clip(m, 40) == "Coupling guard notes\n- **guard** fitted"
    assert markup.clip(m, 5) == "Coupling guard notes"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def edit(qapp):
    from docrepo.ui.rich_edit import RichEdit

    e = RichEdit()
    yield e
    e.deleteLater()


def test_the_box_keeps_its_markup(edit):
    m = ("Pump **curve** at *62 rpm*, <u>check</u> ~~Friday~~ <mark class=\"green\">today</mark>\n"
         "- first\n  - nested \\*star\n- second\n\n1. one\n2. two\nC:\\Docs\\a.pdf\n\\- dash line")
    edit.set_value(m, True)
    assert edit.value() == (m, True)
    assert edit.plain() == markup.to_plain(m)
    edit.set_value("Just text with *stars* and - dashes\n- even this", False)
    assert edit.value() == ("Just text with *stars* and - dashes\n- even this", False)  # nothing formatted: kept as plain text


def test_formatting_from_the_keys_and_the_toolbar(edit):
    from docrepo.ui.rich_edit import FormatBar

    bar = FormatBar(edit)
    edit.setPlainText("Torque the bolts")
    cursor = edit.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(6, cursor.MoveMode.KeepAnchor)  # "Torque"
    edit.setTextCursor(cursor)
    edit.toggle_bold()
    bar.buttons["mark"].menu().actions()[2].trigger()  # pink
    assert edit.value() == ('**<mark class="pink">Torque</mark>** the bolts', True)
    edit.toggle_list(False)
    edit.toggle_list(True)  # a bulleted line becomes numbered
    assert edit.value()[0] == '1. **<mark class="pink">Torque</mark>** the bolts'
    edit.toggle_list(True)
    assert edit.value()[0] == '**<mark class="pink">Torque</mark>** the bolts'
    edit.toggle_highlight()  # Ctrl+Shift+H takes it off
    assert edit.value()[0] == "**Torque** the bolts"


def test_typing_a_list(edit):
    edit.clear()

    def key(k, text="", mods=Qt.KeyboardModifier.NoModifier):
        edit.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, k, mods, text))

    for ch in "- ":
        key(Qt.Key.Key_Space if ch == " " else Qt.Key.Key_Minus, ch)
    edit.insertPlainText("Guard")
    key(Qt.Key.Key_Return, "\r")
    key(Qt.Key.Key_Tab, "\t")
    edit.insertPlainText("Rails")
    key(Qt.Key.Key_Return, "\r")
    key(Qt.Key.Key_Return, "\r")  # Enter on an empty item: up a level
    edit.insertPlainText("Bolts")
    key(Qt.Key.Key_Return, "\r")
    key(Qt.Key.Key_Return, "\r")  # and out of the list
    edit.insertPlainText("Done.")
    assert edit.value() == ("- Guard\n  - Rails\n- Bolts\nDone.", True)


def _typed_list(cls, first: str = "- "):
    """A box on screen, with two list items typed into it through real key presses, and the caret on the second."""
    box = cls()
    box.resize(600, 400)
    box.show()
    box.setFocus()
    QTest.keyClicks(box, f"{first}Guard")
    QTest.keyClick(box, Qt.Key.Key_Return)
    QTest.keyClicks(box, "Rails")
    return box


def _left(box) -> int:
    """How far in the caret's line sits on screen: what the owner sees, which the markup alone doesn't show."""
    return box.cursorRect(QTextCursor(box.textCursor().block())).left()


BACK = {"Backtab": (Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier), "Tab and Shift": (Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)}


@pytest.mark.parametrize("back", BACK, ids=list(BACK))
@pytest.mark.parametrize("cls_name", ["RichEdit", "ContentEdit"])
def test_shift_tab_undoes_tab_on_screen_and_in_the_markup(qapp, cls_name, back):
    """Item 74: Shift+Tab sends a list item back where it came from, and ends the list at the first level. It used to move
    the words further in, since QTextList.remove hands the list's indent to the line and the two add up on screen."""
    from docrepo.ui.capture_window import ContentEdit
    from docrepo.ui.rich_edit import INDENT, RichEdit

    box = _typed_list({"RichEdit": RichEdit, "ContentEdit": ContentEdit}[cls_name])
    start = _left(box)
    QTest.keyClick(box, Qt.Key.Key_Tab)
    assert box.value()[0] == "- Guard\n  - Rails"
    assert _left(box) == start + INDENT
    QTest.keyClick(box, Qt.Key.Key_Tab)
    assert box.value()[0] == "- Guard\n    - Rails"
    assert _left(box) == start + 2 * INDENT
    QTest.keyClick(box, *BACK[back])
    assert box.value()[0] == "- Guard\n  - Rails"
    assert _left(box) == start + INDENT
    QTest.keyClick(box, *BACK[back])
    assert box.value()[0] == "- Guard\n- Rails"
    assert _left(box) == start
    QTest.keyClick(box, *BACK[back])  # out of the first level: a line of text, at the box's edge
    assert box.value()[0] == "- Guard\nRails"
    assert _left(box) < start
    box.deleteLater()


def test_a_level_on_screen_is_where_the_saved_text_shows_it(qapp):
    from docrepo.ui.rich_edit import RichEdit

    box = _typed_list(RichEdit)
    QTest.keyClick(box, Qt.Key.Key_Tab)
    typed = _left(box)
    box.set_value(box.value()[0], True)
    assert _left(box) == typed
    QTest.keyClick(box, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)  # and from saved text, back too
    assert box.value()[0] == "- Guard\n- Rails"
    assert _left(box) == typed - 20
    box.deleteLater()


def test_shift_tab_keeps_the_numbers_going_and_is_one_undo(qapp):
    from docrepo.ui.rich_edit import RichEdit

    box = _typed_list(RichEdit, "1. ")
    start = _left(box)
    QTest.keyClick(box, Qt.Key.Key_Tab)
    assert box.value()[0] == "1. Guard\n  1. Rails"
    QTest.keyClick(box, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert box.value()[0] == "1. Guard\n2. Rails" and _left(box) == start
    box.undo()  # one Ctrl+Z puts the level back
    assert box.value()[0] == "1. Guard\n  1. Rails" and _left(box) == start + 20
    box.deleteLater()


def test_alt_shift_left_and_right_move_the_item_the_same_way(qapp):
    from docrepo.ui.rich_edit import RichEdit

    box = _typed_list(RichEdit)
    start = _left(box)
    keys = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(box, Qt.Key.Key_Right, keys)
    assert box.value()[0] == "- Guard\n  - Rails" and _left(box) == start + 20
    QTest.keyClick(box, Qt.Key.Key_Left, keys)
    assert box.value()[0] == "- Guard\n- Rails" and _left(box) == start
    box.deleteLater()


def test_pasting_keeps_what_docrepo_keeps(edit):
    edit.clear()
    onenote = ('<html><body><p style="font-family:Calibri;font-size:11pt;color:#1f3864">Notes from the <b>walkthrough</b></p>'
               '<ul><li><span style="background:yellow">Guard</span> fitted</li><li>Rails <i>painted</i><ul><li>red</li></ul></li></ul></body></html>')
    mime = QMimeData()
    mime.setHtml(onenote)
    mime.setText("Notes from the walkthrough\nGuard fitted\nRails painted\nred")
    edit.insertFromMimeData(mime)
    assert edit.value() == ('Notes from the **walkthrough**\n- <mark class="yellow">Guard</mark> fitted\n- Rails *painted*\n  - red', True)
    edit.clear()
    from test_paste import WORD

    mime = QMimeData()
    mime.setHtml(WORD.replace("Two spares", "Two spares *each*"))
    edit.insertFromMimeData(mime)
    assert edit.value() == ("- Order the seal kit\n  - Two spares \\*each\\*\n1. Confirm the price\nThanks", True)


def test_removing_a_line_keeps_the_rest(edit):
    edit.set_value("**Bold** first\nC:\\Docs\\a.pdf\n- item", True)
    edit.remove_line("c:\\docs\\A.pdf")
    assert edit.value() == ("**Bold** first\n- item", True)


def _press(edit, keys: str) -> None:
    """Press ``keys`` ("Ctrl+.", "Alt+Shift+Up") in the box, as the keyboard would."""
    from PySide6.QtGui import QKeySequence

    combo = QKeySequence(keys)[0]
    edit.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, combo.key(), combo.keyboardModifiers(), ""))


def test_onenotes_keys(edit):
    """Mods log round 3 (M0055, decisions 55 and 56): OneNote's list and formatting keys, with release 5.7's still working,
    and a 20 px list level."""
    from docrepo.ui.rich_edit import INDENT

    edit.setPlainText("Guard fitted")
    _press(edit, "Ctrl+.")
    assert edit.value() == ("- Guard fitted", True)
    _press(edit, "Ctrl+/")
    assert edit.value() == ("1. Guard fitted", True)
    _press(edit, "Ctrl+/")
    _press(edit, "Ctrl+Shift+L")  # release 5.7's key for bullets
    assert edit.value() == ("- Guard fitted", True)
    cursor = edit.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(5, cursor.MoveMode.KeepAnchor)  # "Guard"
    edit.setTextCursor(cursor)
    _press(edit, "Ctrl+-")
    _press(edit, "Ctrl+Alt+H")
    assert edit.value() == ('- ~~<mark class="yellow">Guard</mark>~~ fitted', True)
    assert edit.document().indentWidth() == INDENT == 20


def test_ctrl_up_and_down_go_by_paragraph(edit):
    edit.setPlainText("First line\nSecond line\nThird")
    cursor = edit.textCursor()
    cursor.setPosition(15)  # inside "Second line"
    edit.setTextCursor(cursor)
    _press(edit, "Ctrl+Up")
    assert edit.textCursor().position() == 11  # the start of its own paragraph
    _press(edit, "Ctrl+Up")
    assert edit.textCursor().position() == 0  # then the one above
    _press(edit, "Ctrl+Down")
    _press(edit, "Ctrl+Shift+Down")
    assert edit.textCursor().selectedText() == "Second line "
    _press(edit, "Ctrl+Down")
    _press(edit, "Ctrl+Down")
    assert edit.textCursor().atEnd()


def test_alt_shift_up_and_down_move_a_line_with_its_items(edit):
    edit.set_value("Walkdown\n- Guard\n  - bolts\n- **Rails**\nDone.", True)
    block = edit.document().findBlockByNumber(3)  # "Rails"
    cursor = edit.textCursor()
    cursor.setPosition(block.position() + 2)
    edit.setTextCursor(cursor)
    _press(edit, "Alt+Shift+Up")  # above Guard, which takes its own item with it
    assert edit.value() == ("Walkdown\n- **Rails**\n- Guard\n  - bolts\nDone.", True)
    assert edit.textCursor().block().text() == "Rails" and edit.textCursor().positionInBlock() == 2
    block = edit.document().findBlockByNumber(2)  # "Guard", with "bolts" under it
    cursor.setPosition(block.position())
    edit.setTextCursor(cursor)
    _press(edit, "Alt+Shift+Down")
    assert edit.value() == ("Walkdown\n- **Rails**\nDone.\n- Guard\n  - bolts", True)
    edit.undo()  # one Ctrl+Z puts it back
    assert edit.value() == ("Walkdown\n- **Rails**\n- Guard\n  - bolts\nDone.", True)
    edit.setPlainText("one\ntwo")
    cursor = edit.textCursor()
    cursor.setPosition(5)
    edit.setTextCursor(cursor)
    _press(edit, "Alt+Shift+Up")
    assert edit.value() == ("two\none", False)  # plain text stays plain
    _press(edit, "Alt+Shift+Up")
    assert edit.value() == ("two\none", False)  # nothing above the first line
