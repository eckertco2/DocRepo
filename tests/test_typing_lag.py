"""Typing in the capture window stays cheap (release 5.52): one Model until the database changes, and only the item cards
and line colours that changed are made again. Driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from docrepo import capacity, db, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import ITEMS_WAIT_MS, CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import REF_COLOURS, TINTS, OperatorHighlighter  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TASK = "T000008"


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
    messages: list[tuple[str, str]] = []
    context = AppContext(conn, data_root, fs, settings, notify=lambda t, m: messages.append((t, m)), now=lambda: NOW)
    context.messages = messages  # type: ignore[attr-defined]
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


def fill(window, text: str) -> None:
    window.content.setPlainText(text)
    window.read_items()


def press(window, text: str) -> None:
    """Keys as the box gets them, each followed by what it queued."""
    for ch in text:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(window.content, QKeyEvent(kind, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, ch))
        QApplication.processEvents()


def to_line_end(window, n: int) -> None:
    cursor = window.content.textCursor()
    cursor.setPosition(window.content.document().findBlockByNumber(n).position())
    cursor.movePosition(cursor.MoveOperation.EndOfBlock)
    window.content.setTextCursor(cursor)


def backgrounds(window, n: int) -> list[tuple[int, int, str]]:
    """What's drawn behind a line's text: (start, length, colour)."""
    block = window.content.document().findBlockByNumber(n)
    return sorted((r.start, r.length, r.format.background().color().name()) for r in block.layout().formats())


def boxed(window) -> list:
    """The cards as the layout holds them, in order."""
    box = window.item_cards.cards_box
    return [box.itemAt(i).widget() for i in range(box.count())]


# ---- one Model until the database changes ----
def test_the_model_is_kept_until_the_database_changes(ctx):
    m = ctx.model()
    assert ctx.model() is m
    ctx.conn.execute("UPDATE tasks SET title = 'A new title' WHERE id = ?", (TASK,))
    fresh = ctx.model()
    assert fresh is not m and fresh.tasks[TASK].title == "A new title"
    assert ctx.model() is fresh


def test_another_connection_s_write_is_seen(ctx, fs, data_root):
    m = ctx.model()
    other = db.connect(fs, data_root)
    other.execute("UPDATE tasks SET title = 'Written elsewhere' WHERE id = ?", (TASK,))
    other.close()
    assert ctx.model() is not m and ctx.model().tasks[TASK].title == "Written elsewhere"


def test_nothing_is_kept_inside_a_transaction(ctx):
    was = ctx.model().tasks[TASK].title
    ctx.conn.execute("BEGIN")
    ctx.conn.execute("UPDATE tasks SET title = 'Rolled back' WHERE id = ?", (TASK,))
    assert ctx.model().tasks[TASK].title == "Rolled back"
    assert ctx.model() is not ctx.model()
    ctx.conn.execute("ROLLBACK")
    assert ctx.model().tasks[TASK].title == was


@pytest.mark.parametrize("task", [None, TASK])
def test_typing_loads_no_model(window, monkeypatch, task):
    if task:
        window.set_task(task)
    fill(window, "Walkdown done.\n@Tom check the guards\n**decision, rails go red.\nThe last line")
    window.content.setFocus()
    to_line_end(window, 3)
    loads = []
    init = Model.__init__
    monkeypatch.setattr(Model, "__init__", lambda self, conn: (loads.append(1), init(self, conn))[1])
    press(window, " and a few more words")
    window.read_items()
    QApplication.processEvents()
    assert loads == []


def test_a_saved_task_shows_at_once_in_the_next_capture(window, ctx):
    assert ctx.model().tasks[TASK].title != "Renamed while it was open"
    window.ctx.conn.execute("UPDATE tasks SET title = 'Renamed while it was open' WHERE id = ?", (TASK,))
    window.set_task(TASK)
    assert "Renamed while it was open" in window.task_button.text()


# ---- the wait ----
def test_typing_waits_for_a_pause_before_it_reads(window):
    fill(window, "@Tom check the guards")
    window.content.setFocus()
    to_line_end(window, 0)
    was = window.reading
    press(window, " today")
    assert window.reading is was and window._items_timer.isActive() and window._items_timer.interval() == ITEMS_WAIT_MS


def test_the_list_doesn_t_wait(window):
    window.content.setFocus()
    QApplication.processEvents()
    window.content.insertPlainText("@ty")
    assert window._items_timer.isActive() and window.ref_popup.isVisibleTo(window)


def test_save_straight_after_typing_reads_what_s_waiting(window, ctx):
    window.content.setFocus()
    window.content.insertPlainText("#Installation the crane came on site")
    assert window._items_timer.isActive() and window.task is None
    window.save()
    assert "Installation" in ctx.messages[-1][1]
    assert not window._items_timer.isActive() and [c.task for c in Model(ctx.conn).captures.values()][-1] == TASK


# ---- the cards ----
def test_a_read_that_changes_nothing_keeps_the_cards(window):
    fill(window, "@Tom check the guards\nA plain line\n**decision, rails go red.")
    cards = list(window.item_cards.cards)
    assert len(cards) == 2
    window.read_items()
    assert window.item_cards.cards == cards
    to_line_end(window, 1)
    window.content.insertPlainText(" with more words")
    window.read_items()
    assert window.item_cards.cards == cards and boxed(window) == cards


def test_typing_on_an_item_s_line_makes_only_its_card_again(window):
    fill(window, "@Tom check the guards\n@Mike paint the rails\n**decision, rails go red.")
    first, second, third = window.item_cards.cards
    to_line_end(window, 1)
    window.content.insertPlainText(" and the steps")
    window.read_items()
    now = window.item_cards.cards
    assert now[0] is first and now[2] is third and now[1] is not second
    assert now[1].title.text() == "Paint the rails and the steps"
    assert boxed(window) == now  # in its place


def test_cards_come_and_go_at_the_end(window):
    window.set_task(TASK)
    fill(window, "@Tom check the guards")
    first = window.item_cards.cards[0]
    assert window.item_cards.count.text() == "Save makes 1 task"
    to_line_end(window, 0)
    window.content.insertPlainText("\n**decision, rails go red.")
    window.read_items()
    assert window.item_cards.cards[0] is first and [c.tick.text() for c in window.item_cards.cards] == ["Task", "Decision"]
    assert window.item_cards.count.text() == "Save makes 1 task and 1 decision"
    assert boxed(window) == window.item_cards.cards
    fill(window, "@Tom check the guards")
    assert window.item_cards.cards == [first] and boxed(window) == [first]
    assert window.item_cards.count.text() == "Save makes 1 task"
    fill(window, "No items now")
    assert window.item_cards.cards == [] and boxed(window) == []
    assert window.item_cards.count.text() == "" and window.item_cards.property("empty") is True


def test_a_new_item_above_keeps_the_cards_below_it(window):
    fill(window, "@Tom check the guards\n@Mike paint the rails")
    first, second = window.item_cards.cards
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    cursor.insertText("@Tom first of all\n")
    window.read_items()
    QApplication.processEvents()
    now = window.item_cards.cards
    assert [c.title.text() for c in now] == ["First of all", "Check the guards", "Paint the rails"]
    assert now[1] is first and now[2] is second and now[0].isVisibleTo(window) and boxed(window) == now


def test_a_card_that_moves_follows_its_line(window):
    fill(window, "@Tom check the guards\n@Mike paint the rails")
    first, second = window.item_cards.cards
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    cursor.insertText("A plain line\nAnother\n")  # no new item: the same cards, on lines 3 and 4
    window.read_items()
    assert window.item_cards.cards == [first, second]
    assert first.line_button.text() == "line 3" and second.line_button.text() == "line 4"
    wanted = []
    window.item_cards.go.connect(wanted.append)
    second.line_button.click()
    assert wanted == [3]


def test_a_line_taken_away_above_keeps_the_cards_below_it(window):
    fill(window, "A plain line\n@Tom check the guards\n@Mike paint the rails")
    first, second = window.item_cards.cards
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
    cursor.removeSelectedText()
    window.read_items()
    assert window.item_cards.cards == [first, second] and first.line_button.text() == "line 1"


def test_a_card_taken_out_of_the_middle_leaves_the_rest(window):
    fill(window, "@Tom check the guards\n@Mike paint the rails\n@Tom sweep the deck")
    first, _, third = window.item_cards.cards
    fill(window, "@Tom check the guards\n@Tom sweep the deck")
    assert window.item_cards.cards == [first, third] == boxed(window) and third.line_button.text() == "line 2"


def test_lines_that_swap_places_swap_their_cards(window):
    fill(window, "@Tom check the guards\n@Mike paint the rails")
    first, second = window.item_cards.cards
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    window.content.setTextCursor(cursor)
    window.content.move_lines(1)
    window.read_items()
    assert window.item_cards.cards == [second, first] == boxed(window)
    assert [c.line_button.text() for c in window.item_cards.cards] == ["line 1", "line 2"]


def test_items_alike_each_keep_a_card(window):
    fill(window, "@Tom check the guards\n@Tom check the guards")
    first, second = window.item_cards.cards
    assert first is not second
    fill(window, "@Tom check the guards")
    assert window.item_cards.cards == [first] == boxed(window)
    fill(window, "@Tom check the guards\n@Tom check the guards\n@Tom check the guards")
    assert window.item_cards.cards[0] is first and len(set(map(id, window.item_cards.cards))) == 3


def test_a_moved_card_s_change_goes_by_its_new_place(window):
    window.set_task(TASK)
    fill(window, "@Tom check the guards\n@Mike paint the rails")
    second = window.item_cards.cards[1]
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    cursor.insertText("@Tom first of all\n")
    window.read_items()
    assert window.item_cards.cards[2] is second and second.key == window.reading.items[2].key
    second.tick.setChecked(False)
    assert window.item_ov == {window.reading.items[2].key: {"off": True}}
    assert [c.tick.isChecked() for c in window.item_cards.cards] == [True, True, False]


def test_what_a_card_shows_is_all_in_what_it_s_kept_by(window):
    # Each thing a card draws, changed on its own line, must make that card again and leave its neighbour.
    window.set_task(TASK)
    base = "@Tom check the guards\n@Mike paint the rails"
    for changed in ("@Tom check the guards today", "@Tom check the guards deadline Friday", "@Priya check the guards",
                    "@L.Tom check the guards", "@Tom check the rails"):
        fill(window, base)
        first, second = window.item_cards.cards
        fill(window, changed + "\n@Mike paint the rails")
        assert window.item_cards.cards[0] is not first, changed
        assert window.item_cards.cards[1] is second, changed


def test_a_card_s_changes_stay_and_its_tick_makes_it_again(window):
    fill(window, "@Tom check the guards\n@Mike paint the rails")
    first, second = window.item_cards.cards
    first.title.textEdited.emit("Check the guards and rails")
    window.read_items()
    assert window.item_cards.cards[0].title.text() == "Check the guards and rails"
    assert window.item_cards.cards[1] is second
    window.item_cards.cards[0].tick.setChecked(False)
    QApplication.processEvents()
    assert not window.item_cards.cards[0].tick.isChecked() and window.item_cards.cards[1] is second
    assert window.item_cards.count.text() == "Save makes 1 task"


def test_a_card_being_edited_isn_t_made_again_under_you(window):
    fill(window, "@Tom check the guards")
    card = window.item_cards.cards[0]
    window.item_cards.editing = lambda: True
    to_line_end(window, 0)
    window.content.insertPlainText(" and rails")
    window.read_items()
    assert window.item_cards.cards == [card]
    window.item_cards.editing = lambda: False
    window.read_items()
    assert window.item_cards.cards != [card]  # what it missed comes when you're done
    assert window.item_cards.cards[0].title.text() == "Check the guards and rails"


def test_the_new_task_s_own_card(window):
    window.set_type("new_task", True)
    fill(window, "Paint the rails @Tom\n@Mike check them")
    box = window.item_cards.cards_box.itemAt(0).widget()
    assert box.property("kind") == "self" and "Assignees: Tom" in box.findChildren(QLabel)[1].text()
    assert window.item_cards.cards_box.count() == 2
    card = window.item_cards.cards[0]
    to_line_end(window, 0)  # words that don't change what it says leave it as it is
    window.content.insertPlainText(" and the steps")
    window.read_items()
    assert window.item_cards.cards_box.itemAt(0).widget() is box and window.item_cards.cards[0] is card
    fill(window, "Paint the rails @Mike\n@Mike check them")  # it says something else: only it changes, still first
    now = window.item_cards.cards_box.itemAt(0).widget()
    assert now is not box and "Assignees: Mike" in now.findChildren(QLabel)[1].text() and window.item_cards.cards[0] is card
    fill(window, "Paint the rails\n@Mike check them")  # the first line says nothing now: the card goes, the item's stays
    assert all(w.property("kind") != "self" for w in boxed(window)) and boxed(window) == window.item_cards.cards
    assert [c.title.text() for c in window.item_cards.cards] == ["Check them"]


# ---- the colours ----
def spy_on_colouring(monkeypatch) -> list[int]:
    coloured: list[int] = []
    original = OperatorHighlighter.highlightBlock

    def highlight(self, text):
        coloured.append(self.currentBlock().blockNumber())
        original(self, text)
    monkeypatch.setattr(OperatorHighlighter, "highlightBlock", highlight)
    return coloured


def test_a_read_that_changes_no_colours_colours_nothing(window, monkeypatch):
    fill(window, "@Tom check the guards\nA plain line\n**decision, rails go red.")
    coloured = spy_on_colouring(monkeypatch)
    window.read_items()
    assert coloured == []


def test_only_the_lines_whose_colours_change_are_coloured_again(window, monkeypatch):
    fill(window, "@Tom check the guards\nA plain line\nAnother plain line")
    coloured = spy_on_colouring(monkeypatch)
    cursor = window.content.textCursor()
    cursor.setPosition(window.content.document().findBlockByNumber(2).position())
    cursor.insertText("@Mike ")
    coloured.clear()  # the line being edited, as Qt does
    window.read_items()
    assert coloured == [2]


def test_a_line_gets_its_colours_and_loses_them(window):
    fill(window, "@Tom check the guards\nA plain line")
    tint, (_, person) = TINTS["task"], REF_COLOURS["person"]
    assert backgrounds(window, 0) == sorted([(0, 4, person), (4, len(" check the guards"), tint)])
    assert backgrounds(window, 1) == []
    fill(window, "Tom check the guards\nA plain line")
    assert backgrounds(window, 0) == []


def test_colours_stay_with_their_lines_when_one_is_added_above(window):
    fill(window, "@Tom check the guards\nA plain line")
    before = backgrounds(window, 0)
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    cursor.insertText("A new first line\n")
    window.read_items()
    assert backgrounds(window, 0) == [] and backgrounds(window, 1) == before and backgrounds(window, 2) == []


def test_colours_follow_lines_that_swap_places(window):
    # Two lines of the same shape: the colours at each number are the same before and after, and must still be right.
    fill(window, "@Tom check the guards\nA plain line\n@Tom paint the rails")
    item, plain = backgrounds(window, 0), backgrounds(window, 1)
    cursor = window.content.textCursor()
    cursor.setPosition(0)
    window.content.setTextCursor(cursor)
    window.content.move_lines(1)
    window.read_items()
    assert [window.content.document().findBlockByNumber(n).text() for n in range(3)][1].startswith("@Tom check")
    assert backgrounds(window, 0) == plain and backgrounds(window, 1) == item


def test_lines_added_and_removed_between_reads_end_up_right(window):
    fill(window, "@Tom one\nplain\n@Tom two\nplain\n@Tom three")
    cursor = window.content.textCursor()
    cursor.setPosition(window.content.document().findBlockByNumber(1).position())
    cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
    cursor.removeSelectedText()  # "plain" goes, so each line below moves up one
    cursor.setPosition(0)
    cursor.insertText("first\n")  # and a line above brings them back to the same numbers
    window.read_items()
    tint = TINTS["task"]
    for n in range(window.content.document().blockCount()):
        text = window.content.document().findBlockByNumber(n).text()
        assert (tint in [c for _, _, c in backgrounds(window, n)]) == text.startswith("@"), text


def test_new_text_gets_all_its_colours(window):
    window.set_task(TASK)
    fill(window, "@Tom check the guards")
    fill(window, "A plain line\n**decision, rails go red.\n@Tom paint the rails")
    assert backgrounds(window, 0) == []
    assert TINTS["decision"] in [c for _, _, c in backgrounds(window, 1)]
    assert TINTS["task"] in [c for _, _, c in backgrounds(window, 2)]


def test_colours_go_when_the_reading_does(window):
    fill(window, "@Tom check the guards")
    window.highlighter.set_reading(None)
    assert backgrounds(window, 0) == []


def test_colouring_is_no_change_to_the_text(window):
    window.content.setPlainText("A plain line\n@Tom check the guards")
    window.draft_dirty = False
    window._items_timer.stop()
    undo_steps = window.content.document().availableUndoSteps()
    window.read_items()
    assert TINTS["task"] in [c for _, _, c in backgrounds(window, 1)]  # its colours came
    assert not window.draft_dirty and not window._items_timer.isActive()
    assert window.content.document().availableUndoSteps() == undo_steps
