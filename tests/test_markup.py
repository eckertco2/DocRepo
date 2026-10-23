"""Formatted content text (mods log round 2, M0045): the markup in capture.md, and the box that edits it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
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
