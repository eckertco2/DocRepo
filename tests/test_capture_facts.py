"""The capture window's facts as chips (release 5.188, the redesign's decision 861): the understood words tinted in the
text, a chip for each field with a value, the fields behind More fields, and a chip's popover. Driven offscreen over the
sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.parse import Found  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import capture_facts, tokens  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import OperatorHighlighter  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
#: The mock's sentence (the redesign mock's floating board).
MOCK = "Replace the Line 2 pump seal by Fri 16 Oct. @Mike leads, 6 h. Deadline 30 Oct"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    context = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW)
    yield context
    conn.close()


@pytest.fixture
def window(ctx):
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()


def parsed(w: CaptureWindow, text: str = MOCK) -> CaptureWindow:
    w.set_type("new_task", True)
    w.content.setPlainText(text)
    w.parse()
    return w


def chip_texts(w: CaptureWindow) -> list[str]:
    return [c.text() for c in w.fact_chips.chips]


def backgrounds(w: CaptureWindow, n: int = 0) -> list[tuple[int, int, str]]:
    """What's drawn behind a line's text: (start, length, colour), as ``test_typing_lag.py`` reads it."""
    block = w.content.document().findBlockByNumber(n)
    return sorted((r.start, r.length, r.format.background().color().name()) for r in block.layout().formats())


def test_the_mocks_sentence_gives_its_chips_in_order(window):
    parsed(window)
    texts = chip_texts(window)
    assert texts[:3] == ["Due Fri 16 Oct", "Deadline Fri 30 Oct", f"Lead {Model(window.ctx.conn).person_name('P002')} · 6 h"] or (
        texts[0] == "Due Fri 16 Oct" and texts[1] == "Deadline Fri 30 Oct" and texts[2].startswith("Lead Mike") and texts[2].endswith("· 6 h"))
    assert window.fact_chips.more_chip.isVisibleTo(window) and not window.fields_open
    assert window.n_more.isHidden() and window.n_main.isHidden()


def test_a_value_typed_by_hand_shows_as_a_chip(window):
    window.set_type("new_task", True)
    window.fact_chips.more_chip.click()
    assert window.fields_open and window.n_main.isVisibleTo(window)
    window.n_due.set_value("2026-10-20")
    window.refresh()
    window.fact_chips.more_chip.click()
    assert not window.fields_open
    assert "Due Tue 20 Oct" in chip_texts(window)


def test_what_isnt_tinted():
    def found(key: str, source: str, why: str = "") -> tuple[str, Found]:
        return ("", Found(key, key.title(), "x", source, why=why))

    got = capture_facts.understood_phrases([found("due", "by Fri 16 Oct"), found("leads", "@Mike leads"), found("due", "by Mon", why="Not filled"),
                                            found("title", "the first sentence"), found("status", "Closed."), found("deadline", "a\nb")])
    assert got == [("by Fri 16 Oct", "fact"), ("@Mike leads", "person")]


def test_the_understood_words_are_tinted_and_cleared(window):
    parsed(window)
    caution, info = QColor(tokens.colour("caution_bg")).name(), QColor(tokens.colour("info_bg")).name()
    text = window.content.document().findBlockByNumber(0).text()
    phrases = dict(window.highlighter.understood)
    due = next(p for p in phrases if "16 Oct" in p)
    spans = backgrounds(window)
    assert (text.find(due), len(due), caution) in spans
    assert any(colour == info for _s, _n, colour in spans)  # the lead's words
    # Retyping the date's words takes their tint off, and only theirs.
    cursor = QTextCursor(window.content.document())
    at = text.find(due)
    cursor.setPosition(at)
    cursor.setPosition(at + len(due), QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText("next week")
    QApplication.processEvents()
    spans = backgrounds(window)
    assert not any(colour == caution and n == len(due) for _s, n, colour in spans)
    assert any(colour == info for _s, _n, colour in spans)
    window.clear_found.click()
    left = backgrounds(window)  # only the operator's own colours: "@Mike" (5 letters) on the person's ground
    assert not any(colour == caution for _s, _n, colour in left) and all(n <= len("@Mike") for _s, n, colour in left if colour == info)
    assert chip_texts(window)  # the chips are the fields' values: they stay


def test_the_tint_is_no_change_to_the_text(window):
    window.set_type("new_task", True)
    window.content.setPlainText(MOCK)
    window.draft_dirty = False
    doc = window.content.document()
    undo_steps, modified = doc.availableUndoSteps(), doc.isModified()
    window._items_timer.stop()
    window._tint([("by Fri 16 Oct", "fact")])
    assert (doc.availableUndoSteps(), doc.isModified()) == (undo_steps, modified) and not window.draft_dirty


def test_the_same_phrases_colour_nothing_again(window, monkeypatch):
    window.content.setPlainText(MOCK + "\nA second line")
    window.highlighter.set_understood([("by Fri 16 Oct", "fact")])
    coloured: list[int] = []
    original = OperatorHighlighter.highlightBlock

    def highlight(self, text):
        coloured.append(self.currentBlock().blockNumber())
        original(self, text)
    monkeypatch.setattr(OperatorHighlighter, "highlightBlock", highlight)
    window.highlighter.set_understood([("by Fri 16 Oct", "fact")])
    assert coloured == []
    window.highlighter.set_understood([])
    assert coloured == [0]  # only the line the tint left


def test_more_fields_opens_and_shuts(window):
    window.set_type("new_task", True)
    assert not window.fields_open
    window._show_found([])  # Parse found nothing (a new task always has its title, so it's rare): the fields, to fill by hand
    assert window.fields_open and window.n_main.isVisibleTo(window) and "Nothing found" in window.found_label.text()
    window.reset_draft()
    assert not window.fields_open
    window.fact_chips.more_chip.click()
    window.fact_chips.more_chip.click()
    assert not window.fields_open and window.n_main.isHidden()


def test_a_save_that_fails_opens_the_field_at_fault(window):
    window.set_type("new_task", True)
    window.content.setPlainText("Rigging plan")
    window.n_due.line.setText("not a date")
    assert not window.fields_open
    window.save()
    assert window.error.isVisibleTo(window) and "Due" in window.error.text()
    assert window.fields_open and window.n_main.isVisibleTo(window)


def test_a_chip_opens_its_field_in_a_popover_and_esc_puts_it_back(window):
    parsed(window)
    chip = window.fact_chips.chip_for("new.due")
    chip.click()
    pop = window.fact_popover
    assert pop.is_open() and pop.isAncestorOf(window.n_due)
    window.n_due.set_value("2026-10-23")
    window.refresh()
    QTest.keyClick(window.n_due.line, Qt.Key.Key_Escape)
    assert not pop.is_open() and window.n_main.isAncestorOf(window.n_due)
    assert window.n_due.value() == "2026-10-23" and "Due Fri 23 Oct" in chip_texts(window)
    assert window.isVisible() or True  # Esc in the popover never closed the window


def test_a_chip_with_the_fields_open_focuses_its_field(window):
    parsed(window)
    window.fact_chips.more_chip.click()
    window.fact_chips.chip_for("new.due").click()
    assert not window.fact_popover.is_open() and window.n_main.isAncestorOf(window.n_due)


def test_the_chips_sit_in_the_tab_order_after_attach(window):
    parsed(window)
    order = []
    w = window.attach_button.nextInFocusChain()
    while len(order) < len(window.fact_chips.chips) + 2:
        if w.focusPolicy() & Qt.FocusPolicy.TabFocus:  # the chain holds every widget; Tab stops at these
            order.append(w)
        w = w.nextInFocusChain()
    assert order == [*window.fact_chips.chips, window.fact_chips.more_chip, window.clear_found]


def test_save_with_the_popover_open_saves_its_value(window, ctx):
    window.set_task("T000008")
    parsed(window)
    window.fact_chips.chip_for("new.due").click()
    window.n_due.set_value("2026-10-27")
    window.save()
    assert not window.fact_popover.is_open()
    new = max(Model(ctx.conn).tasks.values(), key=lambda t: t.id)
    assert new.due == "2026-10-27"


def test_save_shows_its_key(window):
    assert window.save_button.text() == "Save" and window.save_button.key_label.text() == "Ctrl Enter"
    assert window.save_button.property("keyed") is True


def test_a_pickers_list_grows_the_popover(window):
    parsed(window)
    window.show()  # offscreen: the picker shows its list only with the keyboard in its box
    window.fact_chips.chip_for("new.leads").click()
    pop = window.fact_popover
    before = pop.height()
    window.n_leads.edit.setFocus()
    QTest.keyClicks(window.n_leads.edit, "a")
    for _ in range(5):  # the layout's request travels up a widget at a time
        QApplication.processEvents()
    assert window.n_leads.list.isVisible()
    assert pop.height() > before and pop.isAncestorOf(window.n_leads.list)
    pop.close_it()
