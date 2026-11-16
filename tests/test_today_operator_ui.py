"""``**today`` in the capture window (release 5.147, decisions 641 and 642): the ``**`` list offers it and puts it in with no
comma, its card is the one ``**agenda, today`` gets, Save puts the task on Today, and the Keys dialog's Syntax tab lists it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

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
    settings = Settings(me="P001")
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


def labels(popup) -> list[str]:
    return [popup.item(i).data(_OPTION).label for i in range(popup.count())]


def test_the_star_list_offers_it_and_a_pick_puts_in_no_comma(window):
    window.set_task("T000008")
    window.content.setFocus()
    QApplication.processEvents()
    window.content.insertPlainText("Crane plan.\n- @Mike book the crane **tod")
    popup = window.ref_popup
    assert popup.isVisible() and labels(popup) == ["**today"]
    window.content.list_keys(Qt.Key.Key_Return)
    assert window.content.toPlainText() == "Crane plan.\n- @Mike book the crane **today "
    assert not popup.isVisible()  # no list opens after it


def test_its_card_is_agenda_today_and_save_puts_the_task_on_today(window):
    window.set_task("T000008")
    window.content.setPlainText("Crane plan.\n- @Mike book the crane **today")
    window.read_items()
    task, card = window.item_cards.cards
    assert task.tick.text() == "Task" and card.tick.text() == "Agenda" and card.title.text() == "Today" and card.tick.isChecked()
    facts = " ".join(x.text() for x in card.findChildren(QLabel))
    assert "puts “Book the crane” on it" in facts
    window.save()
    m = Model(window.ctx.conn)
    crane = next(t.id for t in m.tasks.values() if t.title == "Book the crane")
    assert crane in [a.subject for a in m.today_items()]


def test_the_syntax_tab_lists_it(window):
    dialog = KeyMapDialog(window, "Ctrl+Shift+Space", items.syntax_rows(window.names()))
    try:
        text = dialog.syntax.toPlainText()
        assert "**today" in text and "**today," not in text and "@Mike book the crane **today" in text
        assert "needs no comma" in text
    finally:
        dialog.deleteLater()
