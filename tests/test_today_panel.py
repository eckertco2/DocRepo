"""The Today side panel (release 5.43): its rules, without Qt, and the panel, driven offscreen over the sample data. Since
release 5.106, its width at rest, dragged and kept, and drops on its tasks."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QSystemTrayIcon  # noqa: E402

from docrepo import capacity, db, edits, hotkey, panel_rules, prompts, wheels_config as wc  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.lists import reminders_due  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.panel_rules import Hover, Monitor, Place, Rect  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import today_panel  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.lists import today as today_list  # noqa: E402
from docrepo.ui.drop_target import DropRead, Dropped  # noqa: E402
from docrepo.views import today_due_entries, today_groups  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


# ---- hovering (decision 219) ----
def test_it_widens_after_resting_on_it():
    h = Hover(400, 1500)
    h.pointer_in(0)
    assert not h.tick(399)
    assert h.tick(400)


def test_one_crossing_on_its_way_past_does_nothing():
    h = Hover(400, 1500)
    h.pointer_in(0, (10, 10))
    h.pointer_moved(200, (40, 10))
    assert not h.tick(420)
    h.pointer_out(450)
    assert not h.tick(2000)


def test_a_little_drift_still_counts_as_resting():
    h = Hover(400, 1500)
    h.pointer_in(0, (10, 10))
    h.pointer_moved(200, (12, 11))
    assert h.tick(400)


def test_an_inner_edge_waits_longer():
    h = Hover(400, 1500)
    h.pointer_in(0)
    assert not h.tick(500, hover_ms=700)
    assert h.tick(700, hover_ms=700)


def test_it_contracts_after_the_pointer_leaves():
    h = Hover(400, 1500)
    h.pointer_in(0)
    h.tick(400)
    h.pointer_out(1000)
    assert h.tick(2499)
    assert not h.tick(2500)


def test_never_while_the_pointer_is_on_it():
    h = Hover(400, 1500)
    h.pointer_in(0)
    h.tick(400)
    assert h.tick(99999)


@pytest.mark.parametrize("what", ["typing in the box", "a menu", "a task's detail"])
def test_never_while_something_holds_it(what):
    h = Hover(400, 1500)
    h.pointer_in(0)
    h.tick(400)
    h.pointer_out(1000)
    assert h.tick(90000, holding=True), what
    assert not h.tick(90000)


def test_coming_back_stops_the_contraction():
    h = Hover(400, 1500)
    h.pointer_in(0)
    h.tick(400)
    h.pointer_out(1000)
    h.pointer_in(1500)
    assert h.tick(9000)


def test_hover_can_be_turned_off_and_a_click_widens_it():
    h = Hover(400, 1500, enabled=False)
    h.pointer_in(0)
    assert not h.tick(9000)
    h.open_wide()
    assert h.tick(9001)


def test_esc_contracts_under_a_resting_pointer_and_stays_narrow():
    """A pointer on the panel never stops Esc from working."""
    h = Hover(400, 1500)
    h.pointer_in(0)
    h.tick(400)
    h.contract()
    assert not h.tick(9000)
    h.pointer_out(9001)
    h.pointer_in(9002)
    assert h.tick(9402)


def test_the_timer_is_needed_only_while_something_can_change():
    h = Hover(400, 1500)
    assert not h.waiting()
    h.pointer_in(0)
    assert h.waiting()
    h.tick(400)
    assert not h.waiting()
    h.pointer_out(500)
    assert h.waiting() and not h.waiting(holding=True)


# ---- where it goes (decision 222) ----
MAIN, SECOND = Rect(0, 0, 1920, 1080), Rect(1920, 0, 1920, 1080)


@pytest.mark.parametrize(("x", "monitor", "side"), [(100, MAIN, "left"), (959, MAIN, "left"), (961, MAIN, "right"), (2000, SECOND, "left"), (3800, SECOND, "right")])
def test_a_drop_snaps_to_the_nearer_side_of_the_monitor_its_on(x, monitor, side):
    assert panel_rules.snap_side(x, monitor) == side


def test_where_each_side_is():
    assert panel_rules.edge_x("left", SECOND, 180) == 1920
    assert panel_rules.edge_x("right", SECOND, 180) == 3840 - 180


def test_an_inner_edge_is_one_that_meets_another_monitor():
    both = [MAIN, SECOND]
    assert panel_rules.is_inner_edge("right", MAIN, both) and panel_rules.is_inner_edge("left", SECOND, both)
    assert not panel_rules.is_inner_edge("left", MAIN, both) and not panel_rules.is_inner_edge("right", SECOND, both)
    assert not panel_rules.is_inner_edge("right", MAIN, [MAIN])
    above = Rect(1920, -2000, 1920, 1080)  # touching the same line, but not beside it
    assert not panel_rules.is_inner_edge("right", MAIN, [MAIN, above])


def test_next_monitor_goes_round():
    assert panel_rules.next_monitor(0, 2) == 1 and panel_rules.next_monitor(1, 2) == 0 and panel_rules.next_monitor(0, 0) == 0


A, B, C = Monitor("DISPLAY1", "S1", 1920, 1080), Monitor("DISPLAY2", "S2", 2560, 1440), Monitor("DISPLAY1", "S3", 1920, 1080)


def test_finding_a_saved_monitor():
    assert panel_rules.find_monitor(B, [A, B]) == 1
    assert panel_rules.find_monitor(Monitor("DISPLAY9", "S2", 2560, 1440), [A, B]) == 1  # its serial number, on another port
    assert panel_rules.find_monitor(Monitor("DISPLAY2", "", 2560, 1440), [A, B]) == 1  # no serial number: name and size
    assert panel_rules.find_monitor(C, [A, B]) is None or panel_rules.find_monitor(C, [A, B]) == 0
    assert panel_rules.find_monitor(Monitor("GONE", "S9", 1, 1), [A, B]) is None
    assert panel_rules.find_monitor(Monitor(), [A, B]) is None


def test_two_monitors_with_one_name_are_told_apart():
    assert panel_rules.find_monitor(C, [A, C]) == 1


def test_a_place_reads_what_it_wrote_and_survives_rubbish():
    place = Place("right", 40, B)
    assert Place.from_json(place.to_json()) == place
    assert Place.from_json("nonsense") == Place()
    assert Place.from_json({"side": "top", "top": "x"}) == Place()


def test_full_screen_means_filling_the_monitor():
    assert panel_rules.covers(Rect(0, 0, 1920, 1080), MAIN)
    assert panel_rules.covers(Rect(-8, -8, 1936, 1096), MAIN)
    assert not panel_rules.covers(Rect(0, 0, 1920, 1040), MAIN)  # maximized: it stops at the taskbar
    assert not panel_rules.covers(Rect(1920, 0, 1920, 1080), MAIN)  # full screen on the other monitor


# ---- the panel ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app(qapp, data_root, fs, monkeypatch):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, now=lambda: NOW)
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    a = CaptureApp(qapp, ctx)
    yield a
    if a.panel is not None:
        a.panel.close_panel()
        a.panel.deleteLater()
    for w in (a.wheels.window, a.window, a.browse):
        w.hide()
    a.tray.hide()
    qapp.removeNativeEventFilter(a.filter)
    conn.close()


@pytest.fixture(autouse=True)
def nothing_full_screen(monkeypatch):
    """The window in front on this computer's own desktop is no part of these tests."""
    monkeypatch.setattr(today_panel, "_full_screen_candidates", lambda own: [])


@pytest.fixture
def panel(app):
    app.today_panel_action("open")
    panel = app.panel
    panel._check_full_screen()
    assert panel.isVisible()
    return panel


def put_on_today(app, task="T000008"):
    edits.add_to_today(app.ctx.conn, app.ctx.data_root, app.ctx.fs, task, "", NOW)
    app.browse.refresh(render=False)


def note_on_today(app, text="Sign the sheets"):
    edits.add_to_today(app.ctx.conn, app.ctx.data_root, app.ctx.fs, None, text, NOW)
    app.browse.refresh(render=False)


def panel_task(app, item_id):
    return next(a.subject for a in Model(app.ctx.conn).agenda if a.id == item_id)


def key(panel, k):
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))


def test_the_row_source_is_the_today_views(app, panel):
    """One list, not two: the rows are today_groups' items, and Due in the next 7 days is the same entries."""
    m = Model(app.ctx.conn)
    expected = [a.id for _, items in today_groups(m, NOW.date()) for a in items]
    assert [r.item_id for r in panel.rows] == expected


def test_the_today_view_draws_the_same_due_rows_as_before(app):
    """The row source moved behind one function: the Today view shows what it showed."""
    from docrepo.lists import key_dates_due
    from docrepo.schedule import due_of
    from docrepo.views import due_this_week
    from datetime import date

    m, today = Model(app.ctx.conn), NOW.date()
    tasks = due_this_week(m, today, "P001", False)
    dues = key_dates_due(m, today, "P001", False)
    # Urgent ones first since release 5.97 (decision 386), then soonest first, a key date before a task on the same day.
    entries = sorted([*((not t.urgent, d.date if (d := due_of(t, today)) else date.max, 1, i, t) for i, t in enumerate(tasks)),
                      *((not d.task.urgent, d.day, 0, i, d) for i, d in enumerate(dues))], key=lambda e: e[:4])
    assert today_due_entries(m, today, "P001", False) == [e[4] for e in entries]
    app.show_browse("today")
    assert app.browse.view == "today"


def test_at_rest_it_is_narrow_and_says_the_count(app, panel):
    put_on_today(app)
    assert panel.count.text().startswith("Today · ")
    assert panel.target_width() == 180
    assert not panel.box_row.isVisibleTo(panel)


def test_widened_it_shows_more(app, panel):
    put_on_today(app)
    panel.hover.open_wide()
    panel._update_state()
    assert panel.target_width() == 320
    assert panel.box_row.isVisibleTo(panel)
    assert panel.rows and panel.rows[0].subtitle.isVisibleTo(panel.rows[0])


def test_widths_come_from_the_config(app, panel, data_root, fs):
    fs.write_text(data_root / wc.CONFIG_FILE, wc.DEFAULT_TEXT.replace('"rest_width": 180', '"rest_width": 200'))
    assert app.wheels.reload()
    assert panel.target_width() == 200


def test_a_change_elsewhere_reaches_it(app, panel):
    before = len(panel.rows)
    put_on_today(app, "T000002")
    assert len(panel.rows) == before + 1


def test_done_here_is_done_there_and_opens_an_update(app, panel):
    """Release 5.115, decision 421: no question, the capture window opens as an Update on the task."""
    put_on_today(app)
    item = next(r for r in panel.rows if r.task_id == "T000008")
    panel.done(item.item_id)
    assert not any(a.id == item.item_id for a in Model(app.ctx.conn).today_items())
    assert not any(r.item_id == item.item_id for r in panel.rows)
    w = app.window
    assert w.isVisible() and w.task == "T000008" and w.types == {"update"} and w.content.value()[0].startswith("Done today")
    assert panel.note_row.isVisibleTo(panel) and "done for today" in panel.note_label.text()  # said here, with Undo (decision 420)


def test_undo_in_the_panel_puts_it_back_and_takes_away_the_untouched_update(app, panel):
    put_on_today(app)
    item = next(r for r in panel.rows if r.task_id == "T000008").item_id
    panel.done(item)
    assert app.window.isVisible()
    panel.note_undo.click()
    assert any(a.id == item for a in Model(app.ctx.conn).today_items())
    assert not app.window.isVisible() and "Back on Today." in panel.note_label.text()


def test_undo_keeps_an_update_with_something_typed_in_it(app, panel):
    put_on_today(app)
    item = next(r for r in panel.rows if r.task_id == "T000008").item_id
    panel.done(item)
    app.window.content.setPlainText("Done today: the vendor called back.")
    panel.note_undo.click()
    assert any(a.id == item for a in Model(app.ctx.conn).today_items())
    assert app.window.isVisible() and "stays open" in panel.note_label.text()


def test_remove_in_the_panel_has_undo(app, panel):
    put_on_today(app)
    item = next(r for r in panel.rows if r.task_id == "T000008").item_id
    panel.remove(item)
    assert not app.window.isVisible() and "taken off Today" in panel.note_label.text()
    panel.note_undo.click()
    assert any(a.id == item for a in Model(app.ctx.conn).today_items())


def test_a_note_ticked_is_just_done(app, panel):
    note_on_today(app)
    item = next(r for r in panel.rows if r.task_id is None).item_id
    panel.done(item)
    assert not app.window.isVisible() and not any(a.id == item for a in Model(app.ctx.conn).today_items())


def test_put_back_from_done_today(app, panel):
    put_on_today(app)
    item = next(r for r in panel.rows if r.task_id == "T000008").item_id
    panel.done(item)
    db.set_state(app.ctx.conn, today_panel.DONE_OPEN_KEY, "1")
    panel.hover.open_wide()
    panel.refresh()
    back = next(b for w in panel.extras for b in w.findChildren(QPushButton) if b.text() == "Back on Today")
    back.click()
    assert any(a.id == item for a in Model(app.ctx.conn).today_items())
    assert any(r.item_id == item for r in panel.rows) and "Back on Today." in panel.note_label.text()


def test_remove_asks_nothing(app, panel):
    put_on_today(app)
    item = next(r for r in panel.rows if r.task_id == "T000008")
    panel.remove(item.item_id)
    assert not any(a.id == item.item_id for a in Model(app.ctx.conn).today_items())
    assert not app.window.isVisible()  # no Update opens for Remove


def test_the_box_makes_a_quick_task_or_a_note(app, panel):
    panel.hover.open_wide()
    panel._update_state()
    panel.box.setText("Call the vendor")
    panel.add_from_box()
    assert any(r.title == "Call the vendor" for r in panel.rows) and panel.box.text() == ""
    panel._switch_kind()
    panel.box.setText("Sign the sheets")
    panel.add_from_box()
    note = next(r for r in panel.rows if r.title == "Sign the sheets")
    assert note.task_id is None


def test_clicking_an_item_shows_its_page_to_read(app, panel):
    put_on_today(app)
    item = next(r for r in panel.rows if r.task_id == "T000008")
    panel.open_detail(item.item_id)
    assert panel.stack.currentIndex() == 1 and panel.target_width() == 420
    title = Model(app.ctx.conn).tasks["T000008"].title
    assert title in panel.detail_page.toPlainText()
    assert panel.detail_buttons["browse"].isVisibleTo(panel) and not panel.detail_buttons["make"].isVisibleTo(panel)
    assert panel._holding()
    panel.close_detail()
    assert panel.stack.currentIndex() == 0 and panel.target_width() == 320


def test_a_note_shows_its_text_with_make_it_a_task(app, panel):
    note_on_today(app)
    item = next(r for r in panel.rows if r.title == "Sign the sheets")
    panel.open_detail(item.item_id)
    assert "Sign the sheets" in panel.detail_page.toPlainText()
    assert panel.detail_buttons["make"].isVisibleTo(panel) and not panel.detail_buttons["browse"].isVisibleTo(panel)
    panel._make_task()
    assert any(r.title == "Sign the sheets" and r.task_id for r in panel.rows)


def test_open_in_the_browse_tool(app, panel):
    put_on_today(app)
    panel.open_detail(next(r for r in panel.rows if r.task_id == "T000008").item_id)
    panel._open_detail_in_browse()
    assert app.browse.isVisible() and app.browse.sel == ("task", "T000008")


def test_the_keyboard(app, panel, monkeypatch):
    put_on_today(app)
    put_on_today(app, "T000002")
    panel.take_keyboard()
    assert panel.hover.wide and panel.cursor == 0
    key(panel, Qt.Key.Key_Down)
    assert panel.cursor == 1
    key(panel, Qt.Key.Key_Return)
    assert panel.stack.currentIndex() == 1
    key(panel, Qt.Key.Key_Escape)
    assert panel.stack.currentIndex() == 0 and panel.hover.wide
    second = panel.rows[1].item_id
    key(panel, Qt.Key.Key_Delete)
    assert not any(a.id == second for a in Model(app.ctx.conn).today_items())
    first = panel.rows[0].item_id
    panel.cursor = 0
    key(panel, Qt.Key.Key_Space)
    assert not any(a.id == first for a in Model(app.ctx.conn).today_items())
    assert app.window.isVisible() and app.window.task == panel_task(app, first)  # Space ticks it: the Update opens (decision 421)
    app.window.hide()
    panel.hover.open_wide()
    key(panel, Qt.Key.Key_Escape)
    assert not panel.hover.wide


def test_the_toggle_and_the_hotkey(app, panel, monkeypatch):
    app.today_panel_action("toggle")
    assert not panel.isVisible() and db.get_state(app.ctx.conn, panel_rules.OPEN_KEY) == "0"
    app.today_panel_action("toggle")
    assert panel.isVisible() and db.get_state(app.ctx.conn, panel_rules.OPEN_KEY) == "1"
    taken = []
    monkeypatch.setattr(panel, "take_keyboard", lambda: taken.append(True))
    app.today_panel_action("hotkey")  # open but not active: the keyboard comes to it
    assert taken == [True] and panel.isVisible()
    monkeypatch.setattr(panel, "isActiveWindow", lambda: True)
    app.today_panel_action("hotkey")  # active: it closes
    assert not panel.isVisible()
    monkeypatch.undo()
    app.today_panel_action("hotkey")  # closed: it opens
    assert panel.isVisible()


def test_open_is_remembered_across_restarts(app, qapp, panel):
    assert db.get_state(app.ctx.conn, panel_rules.OPEN_KEY) == "1"


def test_it_comes_from_the_wheel_and_the_tray_and_the_palette(app):
    app.wheels.run("today.panel", {"do": "open"})
    assert app.panel.isVisible()
    app.wheels.run("today.panel", {"do": "close"})
    assert not app.panel.isVisible()
    palette = next(c for c in app.wheels.palette_commands() if c.label == "Execution wheel, right: Today panel")
    palette.run()
    assert app.panel.isVisible()


def test_its_hotkey_has_a_settings_box_and_no_default(app):
    assert ("today_panel_hotkey", "Open or close the Today side panel") in hotkey.HOTKEYS
    assert "today_panel_hotkey" not in hotkey.SUGGESTED and Settings().today_panel_hotkey == ""
    assert hotkey.HOTKEY_IDS["today_panel_hotkey"] in app.hotkey_actions


def test_nothing_in_it_stops_it_being_narrow(app, panel):
    """Its detail's buttons, its rows and its folded headings don't set its width: the settings do."""
    put_on_today(app)
    note_on_today(app, "A note with a very long line of text that goes on for quite a while and then some more")
    assert panel.minimumSizeHint().width() <= 180
    assert panel.geometry().width() == 180


def test_a_drop_snaps_and_remembers(app, panel):
    screen = QApplication.primaryScreen().geometry()
    panel.dropped(QPoint(screen.right() - 10, screen.y() + 200))
    assert panel.place_.side == "right"
    assert panel.geometry().right() >= screen.right() - 1
    stored = panel._read_place()
    assert stored.side == "right" and stored.monitor.name == QApplication.primaryScreen().name()
    panel.dropped(QPoint(screen.x() + 10, screen.y() + 200))
    assert panel.place_.side == "left" and panel.geometry().x() == QApplication.primaryScreen().availableGeometry().x()


def test_a_saved_monitor_thats_gone_goes_to_the_main_one(app, panel):
    panel.place_ = Place("left", 0, Monitor("GONE", "S9", 1, 1))
    assert panel._screen() is QApplication.primaryScreen()
    panel.place_window()
    assert panel.geometry().x() == QApplication.primaryScreen().availableGeometry().x()


def test_full_screen_hides_it_until_that_ends(app, panel, monkeypatch):
    covered = [True]
    monkeypatch.setattr(panel, "covered_now", lambda: covered[0])
    panel._check_full_screen()
    assert not panel.isVisible() and panel._hidden_for_full_screen
    covered[0] = False
    panel._check_full_screen()
    assert panel.isVisible()


def test_hiding_for_full_screen_can_be_turned_off(app, panel, monkeypatch, data_root, fs):
    fs.write_text(data_root / wc.CONFIG_FILE, wc.DEFAULT_TEXT.replace('"hide_on_full_screen": true', '"hide_on_full_screen": false'))
    assert app.wheels.reload()
    monkeypatch.setattr(panel, "covered_now", lambda: True)
    panel._check_full_screen()
    assert panel.isVisible()


def test_a_click_only_takes_the_keyboard_on_the_box():
    """Checked by name here; that Windows honours it is for the hand test."""
    from docrepo.ui import today_panel

    assert today_panel.MA_NOACTIVATE == 3 and today_panel.WM_MOUSEACTIVATE == 0x21 and today_panel.WS_EX_NOACTIVATE == 0x08000000


def test_folds_remember(app, panel):
    assert db.get_state(app.ctx.conn, "today_panel_due_open") in (None, "0")
    panel._fold_clicked = None
    fold = next(w for w in panel.extras if w.objectName() == "tpFold" and "Due in the next 7 days" in w.text())
    fold.click()
    assert db.get_state(app.ctx.conn, "today_panel_due_open") == "1"


def _reminder_fold(panel):
    return next((w for w in panel.extras if w.objectName() == "tpFold" and "Reminders" in w.text()), None)


def _reminder_links(panel):
    """Each reminder's row, as the names of its links, while Due in the next 7 days stays folded."""
    return [[b.text() for b in w.findChildren(QPushButton)] for w in panel.extras if w.objectName() == "tpRow"]


def _click(panel, row, name):
    rows = [w for w in panel.extras if w.objectName() == "tpRow"]
    next(b for b in rows[row].findChildren(QPushButton) if b.text() == name).click()


def test_reminders_reach_the_panel_as_today_items(app, panel):
    """Release 5.116, decision 415: no Reminders fold; a reminder whose day has come puts its task on Today, marked as a
    reminder's. The app does it each minute, once it's past the reminder time."""
    due = reminders_due(Model(app.ctx.conn), NOW.date())
    assert len(due) == 2 and _reminder_fold(panel) is None
    app.reminders_to_today()
    rows = {r.task_id: r for r in panel.rows}
    assert {t.id for t in due} <= set(rows) and "reminder" in rows[due[0].id].subtitle.full
    assert _reminder_fold(panel) is None


def test_later_from_a_panel_row(app, panel, monkeypatch):
    """Release 5.116, decision 417: a task's row has Later, whose menu is the Today view's; what it did is said here."""
    put_on_today(app)
    row = next(r for r in panel.rows if r.task_id == "T000008")
    assert [b.text() for b in row.buttons.findChildren(QPushButton)] == ["Later", "Done", "Remove"]
    monkeypatch.setattr(today_list, "show_menu", lambda menu, at: menu.actions()[0].trigger())  # Tomorrow
    row.later_clicked()
    m = Model(app.ctx.conn)
    assert "T000008" not in [a.subject for a in m.today_items()] and m.task("T000008").reminder == "2026-10-09"
    assert "off Today until Fri 9 Oct" in panel.note_label.text()
    panel.note_undo.click()
    assert "T000008" in [a.subject for a in Model(app.ctx.conn).today_items()]


def test_a_note_has_no_later(app, panel):
    note_on_today(app)
    row = next(r for r in panel.rows if r.task_id is None)
    assert [b.text() for b in row.buttons.findChildren(QPushButton)] == ["Done", "Remove"]


# ---- the width at rest (release 5.106, decision 406) ----
def test_dragging_the_inner_edge_follows_the_side_and_stays_in_bounds():
    least = panel_rules.MIN_REST_WIDTH
    assert panel_rules.dragged_width("left", 180, -50, 320) == 130  # on the left, the inner edge is the right one
    assert panel_rules.dragged_width("right", 180, -50, 320) == 230  # on the right, dragging left widens it
    assert panel_rules.dragged_width("left", 180, -500, 320) == least
    assert panel_rules.dragged_width("right", 180, -500, 320) == 320  # never wider than it widens to on hover
    assert panel_rules.dragged_width("left", 180, 0, 60) == least  # a hover width under the least doesn't squeeze it


def test_the_width_at_rest_is_the_kept_one_or_the_configs():
    assert panel_rules.rest_width(None, 180, 320) == 180
    assert panel_rules.rest_width("", 180, 320) == 180  # reset
    assert panel_rules.rest_width("rubbish", 180, 320) == 180
    assert panel_rules.rest_width("120", 180, 320) == 120
    assert panel_rules.rest_width("40", 180, 320) == panel_rules.MIN_REST_WIDTH
    assert panel_rules.rest_width("900", 180, 320) == 320


def test_the_grip_is_on_the_inner_edge_and_only_at_rest(app, panel):
    put_on_today(app)
    assert panel.place_.side == "left" and panel.grip.isVisibleTo(panel)
    assert panel.grip.geometry().right() == panel.width() - 1 and panel.grip.geometry().top() == panel.top.height()
    screen = QApplication.primaryScreen().geometry()
    panel.dropped(QPoint(screen.right() - 10, screen.y() + 200))  # moved to the right side: the grip goes to its left edge
    assert panel.place_.side == "right" and panel.grip.geometry().x() == 0
    panel.hover.open_wide()
    panel._update_state()
    assert not panel.grip.isVisibleTo(panel)
    panel.hover.contract()
    panel._update_state()
    assert panel.grip.isVisibleTo(panel)


def test_dragging_the_grip_sets_the_width_at_rest_and_its_kept(app, panel):
    put_on_today(app)
    panel.size_rest(180, -500)
    assert panel.geometry().width() == panel_rules.MIN_REST_WIDTH  # nothing in it holds it wider, not even the count
    panel.size_rest(180, -60)
    assert panel.target_width() == 120 and panel.geometry().width() == 120
    assert panel.geometry().x() == QApplication.primaryScreen().availableGeometry().x()  # still against its edge
    panel.keep_rest()
    assert db.get_state(app.ctx.conn, panel_rules.REST_WIDTH_KEY) == "120"
    again = today_panel.TodayPanel(app.ctx, app.browse, app.wheels)  # as after a restart
    try:
        assert again.target_width() == 120
    finally:
        again.drop_cover.release()
        again.deleteLater()
    panel.hover.open_wide()
    panel._update_state()
    assert panel.target_width() == 320  # it widens on hover as before
    panel.hover.contract()
    panel.reset_rest()
    assert panel.target_width() == 180 and not db.get_state(app.ctx.conn, panel_rules.REST_WIDTH_KEY)


def test_the_pointer_on_the_grip_doesnt_widen_it(app, panel):
    clock = [0]
    panel.clock = lambda: clock[0]
    panel.hover.pointer_in(0)
    panel.on_grip(True)
    clock[0] = 5000
    panel._hover_tick()
    assert not panel.hover.wide


def test_a_width_at_rest_from_the_config_still_counts_until_one_is_dragged(app, panel, data_root, fs):
    fs.write_text(data_root / wc.CONFIG_FILE, wc.DEFAULT_TEXT.replace('"rest_width": 180', '"rest_width": 150'))
    assert app.wheels.reload()
    assert panel.target_width() == 150
    panel.size_rest(150, 20)
    assert panel.target_width() == 170


# ---- drops on a task (release 5.106, decisions 407 and 408) ----
def _dropped_file(tmp_path, name="Pump curve.txt"):
    folder = tmp_path / "Inbox"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text("Made up for the test", encoding="utf-8")
    return path


def _files(path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def _at(panel, row):
    return row.mapTo(panel, row.rect().center())


def _drag(panel, mime, at: QPoint, drop: bool = True):
    """A drag of ``mime`` coming over the panel, moving to ``at``, and dropped there."""
    buttons, keys, copy = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.DropAction.CopyAction
    enter = QDragEnterEvent(QPoint(2, 2), copy, mime, buttons, keys)
    QApplication.sendEvent(panel, enter)
    QApplication.processEvents()
    move = QDragMoveEvent(at, copy, mime, buttons, keys)
    QApplication.sendEvent(panel, move)
    if not drop:
        return enter, move, None
    dropped = QDropEvent(QPointF(at), copy, mime, buttons, keys)
    QApplication.sendEvent(panel, dropped)
    QApplication.processEvents()
    return enter, move, dropped


def test_the_tasks_are_the_drop_targets_and_a_note_isnt(app, panel):
    put_on_today(app)
    note_on_today(app)
    panel.drag_in()
    targets = panel.drop_targets()
    assert [w.task_id for w in targets if w in panel.rows] == [r.task_id for r in panel.rows if r.task_id]
    assert all(w.task_id for w in targets) and any(r.task_id is None for r in panel.rows)
    panel.drag_over()


def test_a_file_dropped_on_a_task_opens_an_update_with_it(app, panel, tmp_path):
    put_on_today(app)
    path = _dropped_file(tmp_path)
    mime = _files(path)
    enter = QDragEnterEvent(QPoint(2, 2), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel, enter)
    assert enter.isAccepted() and panel.hover.wide and panel.target_width() == 320  # it widens, so the tasks can be read
    QApplication.processEvents()
    row = next(r for r in panel.rows if r.task_id == "T000008")
    _enter, move, dropped = _drag(panel, mime, _at(panel, row))
    assert move.isAccepted() and dropped.isAccepted()
    w = app.window
    assert w.isVisible() and w.task == "T000008" and w.types == {"update"}
    assert [e.row.path for e in w.files] == [str(path)] and w.files[0].src == "dropped"
    assert not panel._dragging and panel._drop_at is None


def test_the_row_under_a_drag_is_marked(app, panel, tmp_path):
    put_on_today(app)
    mime = _files(_dropped_file(tmp_path))
    QApplication.sendEvent(panel, QDragEnterEvent(QPoint(2, 2), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                                  Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()
    row = next(r for r in panel.rows if r.task_id == "T000008")
    _drag(panel, mime, _at(panel, row), drop=False)
    assert panel._drop_at is row and row.property("drop") is True
    QApplication.sendEvent(panel, QDragLeaveEvent())
    assert row.property("drop") is False and not panel._dragging


def test_a_drop_on_a_note_or_off_the_tasks_is_refused(app, panel, tmp_path):
    put_on_today(app)
    note_on_today(app)
    mime = _files(_dropped_file(tmp_path))
    QApplication.sendEvent(panel, QDragEnterEvent(QPoint(2, 2), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                                  Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()
    note = next(r for r in panel.rows if r.task_id is None)
    _enter, move, dropped = _drag(panel, mime, _at(panel, note))
    assert not move.isAccepted() and not dropped.isAccepted()
    _enter, move, dropped = _drag(panel, mime, QPoint(panel.width() // 2, 2))  # on the top line
    assert not move.isAccepted() and not dropped.isAccepted()
    assert not app.window.isVisible()


def test_a_drag_closes_a_task_page_to_show_the_list(app, panel):
    put_on_today(app)
    panel.open_detail(next(r for r in panel.rows if r.task_id == "T000008").item_id)
    assert panel.stack.currentIndex() == 1
    panel.drag_in()
    assert panel.stack.currentIndex() == 0 and panel.detail_id() is None
    panel.drag_over()


def test_a_web_link_dropped_on_a_task_is_added_as_a_link(app, panel):
    put_on_today(app)
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/pump-curves")])
    QApplication.sendEvent(panel, QDragEnterEvent(QPoint(2, 2), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                                  Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()
    row = next(r for r in panel.rows if r.task_id == "T000008")
    _drag(panel, mime, _at(panel, row))
    assert app.window.task == "T000008" and app.window.types == {"update"}
    assert any("example.com/pump-curves" in (e.row.path or "") for e in app.window.files)


def test_a_drop_on_a_due_task_goes_to_it(app, panel, tmp_path):
    db.set_state(app.ctx.conn, today_panel.DUE_OPEN_KEY, "1")
    panel.refresh()
    panel.drag_in()
    QApplication.processEvents()
    due = [w for w in panel.drop_targets() if w not in panel.rows]
    assert due, "the sample has tasks due in the next 7 days"
    path = _dropped_file(tmp_path)
    _drag(panel, _files(path), _at(panel, due[0]))
    assert app.window.task == due[0].task_id and [e.row.path for e in app.window.files] == [str(path)]


class _Pointer:
    """Where the cover asks the pointer is: a point on the screen the test sets."""

    at = QPoint(0, 0)

    @classmethod
    def pos(cls):
        return cls.at


def test_an_email_dropped_on_the_cover_goes_to_the_task_under_it(app, panel, monkeypatch):
    put_on_today(app)
    note_on_today(app)
    monkeypatch.setattr(today_panel, "QCursor", _Pointer)
    panel.drag_in()
    QApplication.processEvents()
    row = next(r for r in panel.rows if r.task_id == "T000008")
    _Pointer.at = row.mapToGlobal(row.rect().center())
    assert panel.cover_allows() and panel._cover_target is row
    note = next(r for r in panel.rows if r.task_id is None)
    _Pointer.at = note.mapToGlobal(note.rect().center())
    assert not panel.cover_allows()  # a note isn't a task: the pointer says no
    _Pointer.at = row.mapToGlobal(row.rect().center())
    assert panel.cover_allows()
    panel.drop_cover.uncover()  # the drop: the cover goes first, then what it took arrives
    assert not panel._dragging
    panel.cover_dropped(DropRead(items=[Dropped("Lift plan.txt", b"Lift plan, made up")]))
    w = app.window
    assert w.isVisible() and w.task == "T000008" and w.types == {"update"}
    assert [e.row.name for e in w.files] == ["Lift plan.txt"]


def test_the_cover_takes_nothing_off_a_task(app, panel, monkeypatch):
    put_on_today(app)
    monkeypatch.setattr(today_panel, "QCursor", _Pointer)
    panel.drag_in()
    QApplication.processEvents()
    _Pointer.at = panel.mapToGlobal(QPoint(panel.width() // 2, 2))
    assert not panel.cover_allows()
    panel.cover_dropped(DropRead(items=[Dropped("Lift plan.txt", b"x")]))
    assert not app.window.isVisible()
