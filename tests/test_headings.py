"""Headings in the capture window (release 5.28, mods log round 4, decision 132): kept as "# ", "## " and "### " in a
formatted capture, read as their words, put on the notes page as headings at the level typed, and folded while typing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFontInfo, QTextCursor, QTextDocument  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import captures, items, markup, notes_page  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.notes_page import add_block, lines_of  # noqa: E402
from docrepo.save import CaptureDraft, item_names, save_capture  # noqa: E402
from docrepo.ui.capture_window import ContentEdit  # noqa: E402
from docrepo.ui.rich_edit import FOLDED, GUTTER, FormatBar, RichEdit, document_markup  # noqa: E402

AT = datetime(2026, 10, 16, 9, 30)
NOTES = "Walkdown\n# Pumps\n- **seal** weeping\n## Pump 3\nBearing warm.\n# Valves\nAll fine."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---- the markup ----
def test_a_heading_line_reads_as_its_words():
    assert markup.heading_of("## Pump 3") == (2, "Pump 3") and markup.heading_of("#### Too deep") is None
    assert markup.heading_of("#Rigging plan") is None  # an @ or # item, not a heading
    assert markup.to_plain(NOTES) == "Walkdown\nPumps\n- seal weeping\nPump 3\nBearing warm.\nValves\nAll fine."
    assert markup.is_formatted("Walkdown\n# Pumps") and not markup.is_formatted("Walkdown\n\\# Pumps")
    html = markup.to_html("# Pumps\n- a\n### Detail")
    assert html.startswith("<h1 ") and "font-size:large" in html and "<h3 " in html and "</ul><h3" in html
    assert markup.to_line_html("# Pumps\nx") == "<b>Pumps</b><br>x"


def test_text_that_looks_like_a_heading_keeps_a_backslash():
    for text in ("# not a heading", "## two", "\\# a backslash first", "\\\\## two backslashes"):
        kept = markup.escape(text)
        assert markup.heading_of(kept) is None and markup.to_plain(kept) == text
    assert markup.escape("# x") == "\\# x" and markup.text_of("\\# x") == "# x"
    assert markup.from_list_lines("# x\n- item") == "\\# x\n- item"


def test_a_heading_keeps_its_hashes_when_its_names_are_kept_with_their_ids(sample_conn):
    names = item_names(Model(sample_conn), Settings(me="P001"))
    stored = items.store("## Notes on #Rigging plan\n\\# Pump #Rigging plan", names, formatted=True)
    assert stored == "## Notes on #[Rigging plan](T000012)\n\\# Pump #[Rigging plan](T000012)"
    assert items.unstore(stored) == "## Notes on #Rigging plan\n\\# Pump #Rigging plan"


# ---- the notes page ----
def test_a_capture_s_headings_are_the_page_s_at_the_level_typed(sample_root):
    conn, root, fs = sample_root
    conn.execute("DELETE FROM task_pages")
    r = save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=NOTES + "\n\\# a hash, not a heading", formatted=True,
                                                                       task="T000012"), AT)
    c = Model(conn).captures[r.capture_id]
    assert c.formatted and c.title == "Walkdown"
    assert captures.read_content(root, c).startswith("Walkdown\n# Pumps\n")
    lines = lines_of(notes_page.get(conn, "T000012"))
    assert [(x.kind, x.level, x.text) for x in lines if x.kind == "heading"] == [("heading", 1, "Pumps"), ("heading", 2, "Pump 3"),
                                                                               ("heading", 1, "Valves")]
    assert lines[-1] == notes_page.Line("text", "# a hash, not a heading")


def test_with_day_headings_a_day_s_captures_go_before_the_next_day_heading():
    block = ["[Fri 16 Oct 2026 · 2:00 pm · Note](capture:C000901)", "New."]
    page = "# Fri 16 Oct 2026\nA\n# Pumps\nC\n\n# Thu 22 Oct 2026\nB"
    assert add_block(page, block, date(2026, 10, 16), True) == "# Fri 16 Oct 2026\nA\n# Pumps\nC\n" + "\n".join(block) + "\n\n# Thu 22 Oct 2026\nB"
    assert add_block("# Fri 16 Oct 2026\nA\n# Pumps\nC", block, date(2026, 10, 16), True).endswith("C\n" + "\n".join(block))


# ---- the capture window's box ----
def _box(qapp, text: str = "", formatted: bool = True) -> ContentEdit:
    e = ContentEdit()
    e.resize(420, 300)
    e.show()
    if text:
        e.set_value(text, formatted)
    QApplication.processEvents()
    return e


def _at(e: RichEdit, n: int) -> None:
    c = QTextCursor(e.document().findBlockByNumber(n))
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    e.setTextCursor(c)


def test_keys_make_headings_and_enter_starts_text(qapp):
    e = _box(qapp)
    QTest.keyClicks(e, "Pump 3")
    QTest.keyClick(e, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert e.value() == ("## Pump 3", True) and e.heading_level() == 2
    QTest.keyClick(e, Qt.Key.Key_Return)  # Enter at a heading's end: a line of text, not another heading
    QTest.keyClicks(e, "Bearing warm.")
    assert e.value() == ("## Pump 3\nBearing warm.", True)
    assert e.document().lastBlock().charFormat().fontPointSize() in (0.0, -1.0) or not e.document().lastBlock().blockFormat().headingLevel()
    _at(e, 0)
    QTest.keyClick(e, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert e.value() == ("Pump 3\nBearing warm.", False)  # plain again: nothing's formatted
    # Typed as text, "# " stays text: saved plain, or with a backslash beside formatting.
    e.clear()
    QTest.keyClicks(e, "# not a heading")
    assert e.value() == ("# not a heading", False)
    e.set_value("**x**\n\\# not a heading", True)
    assert e.value() == ("**x**\n\\# not a heading", True)
    # A list item isn't made a heading.
    e.set_value("- item", True)
    _at(e, 0)
    e.set_heading(1)
    assert e.value() == ("- item", True)


def test_saved_headings_come_back_at_the_box_s_sizes(qapp):
    e = _box(qapp, "# Pumps\nText\n### Detail")
    base = QFontInfo(e.font()).pointSizeF()
    h1, h3 = e.document().begin(), e.document().lastBlock()
    assert h1.blockFormat().headingLevel() == 1 and h3.blockFormat().headingLevel() == 3
    assert h1.begin().fragment().charFormat().fontPointSize() == pytest.approx(base + 3.5)
    assert h3.begin().fragment().charFormat().fontPointSize() == pytest.approx(base + 0.5)
    assert e.value() == ("# Pumps\nText\n### Detail", True)


def test_folding_hides_a_section_but_keeps_its_words(qapp):
    e = _box(qapp, NOTES)
    doc = e.document()
    assert e.viewportMargins().left() == GUTTER and e._gutter.isVisible()  # the strip for the arrows
    pumps = doc.findBlockByNumber(1)
    e.toggle_fold(pumps)
    hidden = [b.blockNumber() for b in e.blocks() if not b.isVisible()]
    assert hidden == [2, 3, 4]  # down to the next level-1 heading, Pump 3's section too
    assert e.value() == (NOTES, True)  # what's folded is still saved
    # The arrow keys pass over it.
    _at(e, 1)
    QTest.keyClick(e, Qt.Key.Key_Down)
    assert e.textCursor().blockNumber() == 5
    QTest.keyClick(e, Qt.Key.Key_Up)
    assert e.textCursor().blockNumber() == 1
    # A click on the arrow opens it again; Alt+Shift+- folds the section the caret is in.
    r = e.cursorRect(QTextCursor(pumps))
    QTest.mouseClick(e._gutter, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(GUTTER // 2, r.center().y()))
    assert pumps.userState() != FOLDED and all(b.isVisible() for b in e.blocks())
    _at(e, 4)
    QTest.keyClick(e, Qt.Key.Key_Minus, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    assert doc.findBlockByNumber(3).userState() == FOLDED and not doc.findBlockByNumber(4).isVisible()
    assert e.textCursor().block().isVisible()
    # Putting the caret inside a folded section opens it.
    e.setTextCursor(QTextCursor(doc.findBlockByNumber(4)))
    assert doc.findBlockByNumber(4).isVisible()
    # With no heading left, the strip goes.
    e.set_value("Just text", True)
    QApplication.processEvents()
    assert e.viewportMargins().left() == 0 and not e._gutter.isVisible()


def test_undo_takes_back_a_heading_in_one_step(qapp):
    e = _box(qapp)
    QTest.keyClicks(e, "Pump")
    QTest.keyClick(e, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    QApplication.processEvents()
    assert e.value() == ("# Pump", True)
    e.undo()
    QApplication.processEvents()
    assert e.value() == ("Pump", False) and not e._gutter.isVisible()


def test_moving_a_folded_heading_takes_its_section(qapp):
    e = _box(qapp, "Intro\n# A\na1\na2\n# B\nb1")
    doc = e.document()
    e.toggle_fold(doc.findBlockByNumber(1))
    e.toggle_fold(doc.findBlockByNumber(4))
    _at(e, 4)
    QTest.keyClick(e, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    assert e.value() == ("Intro\n# B\nb1\n# A\na1\na2", True)
    assert [b.isVisible() for b in e.blocks()] == [True, True, False, True, False, False]
    assert doc.findBlockByNumber(1).userState() == FOLDED == doc.findBlockByNumber(3).userState()
    QTest.keyClick(e, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    assert e.value() == ("Intro\n# A\na1\na2\n# B\nb1", True) and e.textCursor().blockNumber() == 4


def test_the_format_bar_s_heading_menu(qapp):
    e = _box(qapp, "Pumps\ntext")
    bar = FormatBar(e)
    assert "heading" in bar.buttons and "Ctrl+Alt+1" in bar.buttons["heading"].toolTip()
    _at(e, 0)
    bar.buttons["heading"].menu().actions()[0].trigger()
    assert e.value() == ("# Pumps\ntext", True) and bar.buttons["heading"].isChecked() and not bar.buttons["b"].isChecked()
    assert "heading" not in FormatBar(RichEdit()).buttons  # a box that doesn't take headings has no menu


def test_a_pasted_heading_comes_in_as_bold_text(qapp):
    doc = QTextDocument()
    doc.setHtml("<h1>Agenda</h1><p>Item</p>")
    assert document_markup(doc, headings=False)[0] == "**Agenda**\nItem"
    assert document_markup(doc)[0] == "# Agenda\nItem"
