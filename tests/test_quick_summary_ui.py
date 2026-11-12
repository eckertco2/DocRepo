"""Release 5.131, the quick summary's window, offscreen (the design workspace's ``docs/mods/quick-summary-plan.md``, decisions
517 to 539): opening it from the wheel and the pages, the box and its keys, the sections, ticking an item and its answer,
Undo, the add box with # picking a task, Copy, pins and recents, the links, Open page, and the pictures it draws. Every name
here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
import types  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import capacity, db, hotkey, prompts  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import SETTINGS_FILE, Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import page_view  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_summary import QuickSummary  # noqa: E402
from docrepo.ui.wheel_commands import REGISTRY  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TOM, MIKE, MEETING, MONITORING, RIGGING = "P003", "P004", "T000010", "T000011", "T000012"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    settings = Settings(me="P001")
    settings.save(fs, root)
    return AppContext(conn, root, fs, settings, now=lambda: NOW)


@pytest.fixture
def window(ctx):
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    browse.said = []
    browse.say = lambda text, error=False: browse.said.append((text, error))
    shown: list[tuple] = []
    app = types.SimpleNamespace(ctx=ctx, browse=browse, show_browse=lambda view=None, task=None: shown.append((view, task)))
    w = QuickSummary(app)
    w.shown = shown
    yield w
    # Everything it opened goes, so no window or popup of ours holds the focus in a later test (a wheel closes when it loses it).
    QApplication.processEvents()
    for shown_window in (w.picker, w, browse, capture):
        shown_window.hide()
    for widget in (w, browse, capture):
        widget.deleteLater()
    QApplication.processEvents()


def press(widget, key, text: str = "") -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))


def titles(w: QuickSummary) -> list[str]:
    return [g.button.text() for g in w.sections.values()]


# ---- opening it (decisions 517 and 518) ----
def test_the_wheel_command_opens_it_with_the_box(qapp, data_root, fs, monkeypatch):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, now=lambda: NOW)
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    app = CaptureApp(qapp, ctx)
    try:
        assert "summary.open" in REGISTRY
        assert app.wheels.config.wheel("execution").slots["S"].command == "summary.open"
        REGISTRY["summary.open"].run(app, {})
        w = app.wheels._quick_summary
        assert w is not None and w.isVisible() and w.stack.currentWidget() is w.list
        ctx.open_summary("person:P003")  # from a person's page, a label's, or the Agendas view
        assert w.subject.key == "person:P003" and w.stack.currentWidget() is w.scroll
        w.hide()
        assert any(c.label.startswith("Quick summary") for c in app.browse.palette_commands())
    finally:  # the app's minute timer would go on ticking into later tests, loading a model as they type
        app.timer.stop()
        for window in (app.wheels.window, app.window, app.browse, app.tray):
            window.hide()
        qapp.removeNativeEventFilter(app.filter)


def test_the_pages_link_to_their_quick_summary(ctx):
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    opened = []
    ctx.open_summary = opened.append
    page = browse.pages().person_page(TOM)
    assert 'href="summary:person:P003"' in page and "Quick summary" in page
    assert 'href="summary:label:Line%201"' in browse.pages().label_page("Line 1")
    browse.on_link(QUrl("summary:label:Line%201"))
    assert opened == ["label:Line 1"]
    browse.deleteLater()
    capture.deleteLater()


# ---- the box (decision 519) ----
def test_the_empty_box_lists_pinned_then_recent_numbered(window, ctx):
    ctx.settings.summary_pins = [f"agenda:{MEETING}"]
    ctx.settings.summary_recent = [f"person:{TOM}", "label:Safety"]
    window.open_it()
    rows = window.list.rows()
    assert [r[2].get("title") for r in rows if r[0] == "head"] == ["Pinned", "Recent"]
    assert [(r[1], r[2]["number"]) for r in rows if r[0] != "head"] == [(f"agenda:{MEETING}", "1"), (f"person:{TOM}", "2"), ("label:Safety", "3")]
    assert rows[1][2]["count"] == "4 to raise" and rows[1][2]["pinned"]
    press(window.box, Qt.Key.Key_2, "2")
    assert window.subject.key == f"person:{TOM}"


def test_typing_finds_and_enter_opens_the_first(window):
    window.open_it()
    window.box.setText("mi")
    window._typed("mi")
    picks = [r for r in window.list.rows() if r[0] != "head"]
    assert picks[0][1] == f"person:{MIKE}" and picks[-1][0] == "new"
    press(window.box, Qt.Key.Key_Return)
    assert window.subject.key == f"person:{MIKE}" and window.box.text() == ""
    assert chips(window) == ["Mike Ortiz  ✕"]  # the subject shows as a chip before the box (decision 555)


def chips(w: QuickSummary) -> list[str]:
    return [w.chips_lay.itemAt(i).widget().text() for i in range(w.chips_lay.count())]


def test_esc_clears_then_goes_back_then_closes(window):
    window.open_it(None, f"person:{TOM}")
    window.show()
    window.box.setText("saf")
    window._typed("saf")
    assert window.stack.currentWidget() is window.list
    press(window.box, Qt.Key.Key_Escape)
    assert window.box.text() == "" and window.stack.currentWidget() is window.scroll  # cleared, and back to Tom
    press(window.box, Qt.Key.Key_Down)
    assert window.stack.currentWidget() is window.list
    press(window.box, Qt.Key.Key_Escape)
    assert window.stack.currentWidget() is window.scroll
    press(window.box, Qt.Key.Key_Escape)
    assert not window.isVisible()


# ---- several together (decisions 555 to 562) ----
def test_ctrl_enter_adds_and_backspace_takes_off(window, ctx):
    window.open_it(None, f"person:{MIKE}")
    window.box.setText("safe")
    window._typed("safe")
    assert window.list.rows()[-1][2]["title"] == "Enter opens it · Ctrl+Enter adds it to Mike Ortiz"
    QApplication.sendEvent(window.box, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier))
    assert window.subject.key == f"person:{MIKE} + label:Safety" and chips(window) == ["Mike Ortiz  ✕", "Safety  ✕"]
    assert window.view.kind_line == "Together · 1 person · 1 label" and not window.page_button.isEnabled()
    window.box.setText("+tom")
    window._typed("+tom")
    press(window.box, Qt.Key.Key_Return)  # a + before the words adds too
    assert [p.name for p in window.subject.each()] == ["Mike Ortiz", "Safety", "Tom Becker"]
    press(window.box, Qt.Key.Key_Backspace)
    assert window.subject.key == f"person:{MIKE} + label:Safety"
    window.chips_lay.itemAt(0).widget().click()  # Mike's ✕
    assert window.subject.key == "label:Safety" and window.page_button.isEnabled()
    window.box.setText("")
    window._typed("")
    press(window.box, Qt.Key.Key_Escape)
    press(window.box, Qt.Key.Key_Backspace)
    assert window.subject is None and window.stack.currentWidget() is window.list


def test_two_agendas_each_with_their_own_add_box(window, ctx):
    window.open_it(None, f"person:{TOM} + agenda:{MEETING}")
    assert titles(window)[:2] == ["Tom's agenda", "Business team meeting"]
    assert set(window.agenda_bodies) == {TOM, MEETING}
    window.agenda_bodies[MEETING].add_box.setText("Shutdown crew sizes")
    press(window.agenda_bodies[MEETING].add_box, Qt.Key.Key_Return)
    assert Model(ctx.conn).open_items_for(MEETING)[-1].note == "Shutdown crew sizes"
    item = window.view.section(f"agenda:{TOM}").agenda[0].item
    window.agenda_bodies[TOM].ticks[item].click()
    assert window.agenda_bodies[TOM].answer_box is not None and window.agenda_bodies[MEETING].answer_box is None
    assert not any(a.id == item for a in Model(ctx.conn).open_items_for(TOM))


def test_a_combination_can_be_pinned_and_opened_by_its_number(window, ctx):
    window.open_it(None, f"person:{MIKE} + person:{TOM}")
    window.toggle_pin()
    assert ctx.settings.summary_pins[0] == f"person:{MIKE} + person:{TOM}"
    window.subject = None
    window.open_it()
    first = next(r for r in window.list.rows() if r[0] != "head")
    assert first[2]["name"] == "Mike Ortiz + Tom Becker" and first[2]["number"] == "1" and first[0] == "many"
    press(window.box, Qt.Key.Key_1, "1")
    assert window.subject.key == f"person:{MIKE} + person:{TOM}"


def test_new_agenda_opens_a_new_meeting_task(window):
    window.open_it()
    window.box.setText("Control room")
    window._typed("Control room")
    new = [r for r in window.list.rows() if r[0] == "new"]
    assert new and new[0][2]["name"] == "New agenda “Control room”…"
    window._picked("new", "Control room")
    capture = window.app.browse.capture
    assert capture.n_meeting.isChecked() and "Control room" in capture.content.toPlainText()


def test_the_subject_is_remembered_as_recent(window, ctx):
    window.open_it(None, "label:Safety")
    saved = json.loads((ctx.data_root / SETTINGS_FILE).read_text(encoding="utf-8"))
    assert saved["summary_recent"][0] == "label:Safety"


# ---- the summary (decisions 521 to 525) ----
def test_a_persons_sections_in_order_other_work_folded(window):
    window.open_it(None, f"person:{TOM}")
    assert titles(window)[:2] == ["Agenda", "Waiting on Tom"]
    assert "Tom's other work" not in titles(window)  # his one other task is on his agenda, so it's there alone
    assert window.sections["waiting_on"].is_open
    assert "Tom Becker" in window.header.toPlainText() and "1 to raise" in window.header.toPlainText()
    assert window.windowTitle() == "Tom Becker: quick summary"
    window.open_it(None, f"person:{MIKE}")
    assert "Mike's other work" in titles(window) and not window.sections["other"].is_open


def test_more_shows_the_rest_in_place(window):
    window.open_it(None, "label:Line 1")
    body = window.sections["rest"].body.toHtml()
    assert "1 more" in body
    window.on_link(QUrl("more:rest"))
    assert "1 more" not in window.sections["rest"].body.toHtml()


def test_a_fold_is_kept_while_the_window_is_open(window):
    window.open_it(None, f"person:{TOM}")
    window.sections["waiting_on"].toggle()
    window.render()
    assert not window.sections["waiting_on"].is_open


# ---- the agenda (decisions 526 and 527) ----
def test_tick_answer_and_the_note_on_its_task(window, ctx):
    window.open_it(None, f"person:{TOM}")
    item = window.view.section("agenda").agenda[0].item
    window.agenda_body.ticks[item].click()
    a = next(x for x in Model(ctx.conn).agenda if x.id == item)
    assert a.how == "Discussed" and a.closed_by == "Quick summary"
    assert window.agenda_body.answer_box is not None and window.undo_button.isVisible()
    assert window.view.section("agenda").extra == "all discussed"
    window.agenda_body.answer_box.setText("It should, and the pump too.")
    press(window.agenda_body.answer_box, Qt.Key.Key_Return)
    assert "It should, and the pump too." in Model(ctx.conn).pages[MONITORING]
    assert window.message.text() == "Kept as a note on Draft monitoring plan."
    assert "It should, and the pump too." in window.agenda_body.findChild(type(window.message), "agendaSaid").text()


def test_esc_skips_the_answer_and_undo_opens_it_again(window, ctx):
    window.open_it(None, f"person:{TOM}")
    item = window.view.section("agenda").agenda[0].item
    window.tick(item, True)
    press(window.agenda_body.answer_box, Qt.Key.Key_Escape)
    assert window.agenda_body.answer_box is None and "no answer" in window.message.text()
    window.do_undo()
    assert any(x.id == item for x in Model(ctx.conn).open_items_for(TOM))
    assert not window.view.section("agenda").agenda[0].discussed


def test_the_add_box_adds_a_note_and_hash_picks_a_task(window, ctx):
    window.open_it(None, f"person:{TOM}")
    window.agenda_body.add_box.setText("Gearbox spares?")
    press(window.agenda_body.add_box, Qt.Key.Key_Return)
    items = Model(ctx.conn).open_items_for(TOM)
    assert items[-1].note == "Gearbox spares?" and items[-1].subject is None and items[-1].added_by == "Quick summary"
    assert window.message.text() == "Added to Tom Becker's agenda as a note."
    window.agenda_body.add_box.setText("Crane quote? #")
    window.agenda_body._typed("Crane quote? #")
    assert window.picker.isVisible() and window.agenda_body.add_box.text() == "Crane quote? "
    window._task_picked(RIGGING)
    assert not window.agenda_body.task_chip.isHidden() and "Rigging plan" in window.agenda_body.task_chip.text()
    press(window.agenda_body.add_box, Qt.Key.Key_Return)
    last = Model(ctx.conn).open_items_for(TOM)[-1]
    assert last.subject == RIGGING and last.note == "Crane quote?"
    assert window.agenda_body.task_chip.isHidden()


# ---- the commands (decisions 533 and 534) ----
def test_copy_puts_rich_text_and_markdown_on_the_clipboard(window):
    window.open_it(None, f"person:{TOM}")
    window.copy()
    data = QGuiApplication.clipboard().mimeData()
    assert data.text().startswith("## Tom Becker: to raise") and "<ul>" in data.html()


def test_pin_keeps_it_first_in_the_box(window, ctx):
    window.open_it(None, "label:Safety")
    window.toggle_pin()
    assert ctx.settings.summary_pins[0] == "label:Safety" and window.pin_button.isChecked()
    saved = json.loads((ctx.data_root / SETTINGS_FILE).read_text(encoding="utf-8"))
    assert saved["summary_pins"] == ["label:Safety"]
    window.toggle_pin()
    assert "label:Safety" not in ctx.settings.summary_pins


def test_links_open_in_the_browse_tool(window):
    window.open_it(None, "label:Line 1")
    window.on_link(QUrl(f"task:{RIGGING}"))
    assert window.shown[-1] == (None, RIGGING)
    window.on_link(QUrl("activity:label:Line%201:2026-09-08"))
    act = window.app.browse.act
    assert act["win"] == "range" and act["from"] == "2026-09-08" and act["labels"] == ["Line 1"] and window.app.browse.view == "activity"


def test_open_page_shows_its_page(window):
    window.open_it(None, f"person:{TOM}")
    window.open_page()
    assert window.app.browse.view == "people" and window.app.browse.sel == ("person", TOM)
    window.open_it(None, f"agenda:{MEETING}")
    window.open_page()
    assert window.app.browse.view == "agenda"


# ---- the pictures (decision 532) ----
def test_the_pictures_it_draws(qapp):
    assert page_view.picture(QUrl("stack:2,1,0,0,3:120"), 1.0).width() == 120
    assert page_view.picture(QUrl("spark:18,17,16,14"), 1.0).width() == page_view.SPARK_W
    assert page_view.picture(QUrl("swatch:critical"), 1.0) is not None
    assert page_view.picture(QUrl("edge:high"), 1.0).height() == 18 and page_view.picture(QUrl("edge:none"), 1.0) is None
    assert page_view.picture(QUrl("face:TB"), 1.0).width() == page_view.FACE
    assert page_view.picture(QUrl("face:label"), 2.0).width() == 2 * page_view.FACE
    assert page_view.picture(QUrl("stack:1,2:120"), 1.0) is None and page_view.picture(QUrl("spark:x"), 1.0) is None
