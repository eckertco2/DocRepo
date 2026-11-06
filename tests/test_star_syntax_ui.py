"""The ** syntax in the windows (release 5.92, the review of 2026-11-06, F6): the ** list in the capture window, the Unread
line and new person's cards in the Items panel, and the Keys dialog's Syntax tab."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, items, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import _OPTION  # noqa: E402
from docrepo.ui.keymap import KeyMapDialog  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001", reference_fields=["Change record"])
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW)
    w = CaptureWindow(ctx)
    w.resize(900, 700)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w._items_timer.stop()
    w.hide()
    w.deleteLater()
    conn.close()


def typed(window, text: str):
    window.content.setFocus()
    QApplication.processEvents()
    window.content.insertPlainText(text)
    return window.content, window.ref_popup


def test_two_stars_open_the_list_and_a_pick_puts_in_name_and_comma(window):
    box, popup = typed(window, "Crane booking.\n**")
    assert popup.isVisible()
    labels = [popup.item(i).data(_OPTION).label for i in range(popup.count())]
    assert labels[:4] == ["**task,", "**note,", "**update,", "**decision,"] and "**change record," in labels
    box.insertPlainText("du")
    assert [popup.item(i).data(_OPTION).label for i in range(popup.count())] == ["**due,", "**duration,"]
    box.list_keys(Qt.Key.Key_Return)
    assert box.toPlainText() == "Crane booking.\n**due, "
    assert not popup.isVisible()


def test_an_unread_line_has_its_card(window):
    window.set_task("T000008")
    window.content.setPlainText("Crane booking.\n**Tom to book the crane")
    window.read_items()
    cards = window.item_cards
    assert cards.isVisible() and len(cards.unread_cards) == 1
    text = " ".join(w.text() for w in cards.unread_cards[0].findChildren(type(cards.count)))
    assert "This ** line wasn't read; check its name and comma" in text and "**Tom to book the crane" in text


def test_a_new_person_is_a_ticked_card_and_unticking_keeps_them_off(window):
    window.set_task("T000008")
    window.content.setPlainText("Crane booking.\n@Zed to book the crane")
    window.read_items()
    tick = window.item_cards.people_ticks["Zed"]
    assert tick.text() == "Add Zed to people" and tick.isChecked()
    tick.setChecked(False)
    assert window.item_ov[items.PEOPLE_KEY] == {"zed": False}
    assert window.reading.items[0].assignees == [] and window.item_cards.people_ticks["Zed"].isChecked() is False
    people = len(Model(window.ctx.conn).people)
    window.save()
    assert len(Model(window.ctx.conn).people) == people


def test_the_keys_dialog_has_the_syntax_tab(window):
    dialog = KeyMapDialog(window, "Ctrl+Shift+Space", items.syntax_rows(window.names()))
    try:
        assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ["Keys", "Syntax"]
        text = dialog.syntax.toPlainText()
        for op in items.OPERATORS:
            if not op.gone:
                assert f"**{items.star_name(op)}," in text, op.names
        assert "**change record," in text and "@Tom to book the crane by Fri" in text and "turnaround" in text
    finally:
        dialog.deleteLater()
