"""A navigation wheel's window and the wheels as a whole (release 5.41), driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt, QVariantAnimation  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import capacity, db, hotkey, prompts, wheels_config as wc  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.settings_view import SettingsProblem, check_values  # noqa: E402
from docrepo.ui.wheel_commands import SPECS, icon_names  # noqa: E402
from docrepo.ui.wheel_window import WheelWindow  # noqa: E402
from docrepo.ui.wheels import USAGE_HEADER, USAGE_LOG  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
CONFIG = wc.parse(wc.DEFAULT_TEXT, SPECS, icon_names())
UP, RIGHT, DOWN, LEFT = Qt.Key.Key_Up, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Left


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Clock:
    def __init__(self) -> None:
        self.t = 1000

    def __call__(self) -> int:
        return self.t


@pytest.fixture
def wheel_window(qapp):
    """A wheel's window with its clock in the test's hands."""
    picks, cancels, palettes = [], [], []
    w = WheelWindow(picks.append, cancels.append, palettes.append)
    w.clock = Clock()
    w.picks, w.cancels, w.palettes = picks, cancels, palettes
    yield w
    w.hide()
    w.deleteLater()


def key(w, k, down=True, modifiers=Qt.KeyboardModifier.NoModifier, repeat=False):
    event = QKeyEvent(QEvent.Type.KeyPress if down else QEvent.Type.KeyRelease, k, modifiers, "", repeat)
    QApplication.sendEvent(w, event)
    QApplication.processEvents()  # a pick hides the wheel just after its command has run


def press(w, k, **kw):
    key(w, k, True, **kw)


def release(w, k, **kw):
    key(w, k, False, **kw)


def open_tapped(w, wheel="capture"):
    w.open_wheel(CONFIG.wheel(wheel), CONFIG.timing, QPointF(500, 400), None)


def test_an_arrow_runs_its_slot_as_it_comes_up(wheel_window):
    w = wheel_window
    open_tapped(w)
    press(w, UP)
    assert w.lit == "N" and w.isVisible() and not w.picks
    w.clock.t += 60
    release(w, UP)
    assert [p.slot.command for p in w.picks] == ["capture.new"]
    assert not w.isVisible() and not w.is_open()
    assert w.picks[0].how == "arrows" and w.picks[0].pick_ms == 60 and w.picks[0].drawn


def test_the_whole_wheel_is_there_before_it_shows(wheel_window, monkeypatch):
    """Decision 175 as the owner changed it (release 5.43.1): no wait and no fade, from its first paint."""
    w = wheel_window
    at_show = []
    monkeypatch.setattr(w, "show", lambda: at_show.append(w.ring))
    open_tapped(w)
    assert at_show == [1.0] and w.ring == 1.0
    assert not w._draw_timer.isActive() and w._fade.state() != QVariantAnimation.State.Running


def test_a_wait_in_the_config_holds_the_ring_back(wheel_window):
    w = wheel_window
    w.open_wheel(CONFIG.wheel("capture"), wc.Timing(draw_ms=333), QPointF(500, 400), None)
    assert w.ring == 0 and w._draw_timer.isActive()
    press(w, UP)
    release(w, UP)
    assert not w.picks[0].drawn and not w._draw_timer.isActive()


def test_a_pick_after_the_wait_says_the_wheel_had_drawn(wheel_window):
    w = wheel_window
    w.open_wheel(CONFIG.wheel("capture"), wc.Timing(draw_ms=333, animation_ms=0), QPointF(500, 400), None)
    w._draw_timer.stop()
    w.draw_ring()
    assert w.ring == 1.0
    press(w, RIGHT)
    release(w, RIGHT)
    assert w.picks[0].drawn and w.picks[0].direction == "E"


def test_the_next_wheel_after_a_wait_doesnt_keep_it(wheel_window):
    w = wheel_window
    w.open_wheel(CONFIG.wheel("capture"), wc.Timing(draw_ms=333), QPointF(500, 400), None)
    open_tapped(w, "browse")
    assert w.ring == 1.0 and not w._draw_timer.isActive()


def test_each_wheel_is_painted_once_unseen_so_the_first_opening_is_quick(wheel_window):
    w = wheel_window
    w.prepare(CONFIG.wheels)
    assert not w.isVisible() and w.wheel is None and w.ring == 0 and not w.is_open()
    painted = {name for name, _colour, _scale in w._icons}
    assert {"add", "mail", "sun", "people", "tasks", "task", "file", "search", "sidebar", "open"} <= painted
    open_tapped(w)
    w.prepare(CONFIG.wheels)  # a wheel that's open is left alone
    assert w.wheel.id == "capture" and w.ring == 1.0


def test_a_chord_on_a_cross_selects_nothing_and_stays_open(wheel_window):
    """Decision 170."""
    w = wheel_window
    open_tapped(w)
    press(w, UP)
    press(w, RIGHT)
    assert w.lit is None
    release(w, UP)
    release(w, RIGHT)
    assert not w.picks and w.isVisible()


def test_a_chord_on_an_eight_way_wheel_runs_the_diagonal(wheel_window):
    w = wheel_window
    wheel = wc.check({"wheels": [{"id": "x", "name": "X", "slots": {"N": {"label": "A", "command": "capture.pin"}, "NE": {"label": "B", "command": "capture.meeting"}}}]},
                     SPECS, icon_names()).wheels[0]
    w.open_wheel(wheel, CONFIG.timing, QPointF(500, 400), None)
    press(w, UP)
    w.clock.t += 20
    press(w, RIGHT)
    assert w.lit == "NE"
    w.clock.t += 50
    release(w, UP)
    w.clock.t += 20
    release(w, RIGHT)
    assert w.picks[0].direction == "NE" and w.picks[0].slot.command == "capture.meeting"


def test_an_empty_slot_on_an_eight_way_wheel_nudges(wheel_window):
    w = wheel_window
    wheel = wc.check({"wheels": [{"id": "x", "name": "X", "slots": {"N": {"label": "A", "command": "capture.pin"}, "NE": {"label": "B", "command": "capture.meeting"}}}]},
                     SPECS, icon_names()).wheels[0]
    w.open_wheel(wheel, CONFIG.timing, QPointF(500, 400), None)
    press(w, DOWN)
    release(w, DOWN)
    assert not w.picks and w.isVisible() and w.note == "Nothing there"


def test_a_held_slot_says_later_and_stays_open(wheel_window):
    w = wheel_window
    open_tapped(w, "execution")
    press(w, DOWN)
    release(w, DOWN)
    assert not w.picks and w.isVisible() and w.note == "Later"


def test_a_slot_marked_confirm_waits_for_enter(wheel_window):
    w = wheel_window
    wheel = wc.check({"wheels": [{"id": "x", "name": "X", "slots": {"N": {"label": "A", "command": "capture.pin", "confirm": True}}}]}, SPECS, icon_names()).wheels[0]
    w.open_wheel(wheel, CONFIG.timing, QPointF(500, 400), None)
    press(w, UP)
    release(w, UP)
    assert not w.picks and w.note == "Enter to run" and w.lit == "N"
    press(w, Qt.Key.Key_Return)
    assert [p.direction for p in w.picks] == ["N"]


def test_enter_runs_what_is_lit_while_an_arrow_is_held(wheel_window):
    w = wheel_window
    open_tapped(w)
    press(w, LEFT)
    press(w, Qt.Key.Key_Return)
    assert [p.direction for p in w.picks] == ["W"]


def test_esc_cancels_and_gives_the_keyboard_back(wheel_window):
    w = wheel_window
    open_tapped(w)
    press(w, Qt.Key.Key_Escape)
    assert w.cancels == [True] and not w.isVisible()


def test_numpad_is_spatial_and_commits_on_key_up(wheel_window):
    w = wheel_window
    keypad = Qt.KeyboardModifier.KeypadModifier
    open_tapped(w)
    press(w, Qt.Key.Key_8, modifiers=keypad)
    assert w.lit == "N" and not w.picks
    release(w, Qt.Key.Key_8, modifiers=keypad)
    assert w.picks[0].direction == "N" and w.picks[0].how == "numpad"


def test_numpad_with_numlock_off_is_the_same(wheel_window):
    w = wheel_window
    keypad = Qt.KeyboardModifier.KeypadModifier
    open_tapped(w)
    press(w, Qt.Key.Key_Right, modifiers=keypad)
    release(w, Qt.Key.Key_Right, modifiers=keypad)
    assert w.picks[0].direction == "E" and w.picks[0].how == "numpad"


def test_numpad_five_cancels_with_numlock_on_or_off(wheel_window):
    w = wheel_window
    keypad = Qt.KeyboardModifier.KeypadModifier
    open_tapped(w)
    press(w, Qt.Key.Key_5, modifiers=keypad)
    assert w.cancels == [True]
    open_tapped(w)
    press(w, Qt.Key.Key_Clear, modifiers=keypad)
    assert w.cancels == [True, True]


def test_the_top_row_digit_is_swallowed(wheel_window):
    w = wheel_window
    open_tapped(w)
    press(w, Qt.Key.Key_8)
    press(w, Qt.Key.Key_A)
    assert w.lit is None and w.isVisible() and not w.picks and not w.cancels


def test_auto_repeat_is_ignored(wheel_window):
    w = wheel_window
    open_tapped(w)
    press(w, UP)
    release(w, UP, repeat=True)
    assert not w.picks and w.lit == "N"


def test_ctrl_k_closes_it_and_opens_the_palette(wheel_window):
    w = wheel_window
    open_tapped(w)
    press(w, Qt.Key.Key_K, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert not w.isVisible() and [x.id for x in w.palettes] == ["capture"]


def test_a_hold_lasts_while_the_hotkey_is_down(wheel_window):
    """Decision 168: letting go after the tap time, with nothing down, cancels."""
    w = wheel_window
    held = [True]
    w.open_wheel(CONFIG.wheel("capture"), CONFIG.timing, QPointF(500, 400), lambda: held[0])
    w.clock.t += 400
    w._read_hotkey()
    assert w.isVisible()
    held[0] = False
    w._read_hotkey()
    assert w.cancels == [True] and not w.isVisible()


def test_a_tap_stays_open(wheel_window):
    w = wheel_window
    held = [True]
    w.open_wheel(CONFIG.wheel("capture"), CONFIG.timing, QPointF(500, 400), lambda: held[0])
    w.clock.t += 100
    held[0] = False
    w._read_hotkey()
    assert w.isVisible() and not w.cancels and w.session.tapped


def test_a_tap_released_before_the_wheel_was_in_front_is_noticed(wheel_window):
    w = wheel_window
    w.open_wheel(CONFIG.wheel("capture"), CONFIG.timing, QPointF(500, 400), lambda: False)
    assert w.isVisible() and w.session.tapped


def test_rolling_off_the_hotkey_with_an_arrow_down_commits_on_its_way_up(wheel_window):
    w = wheel_window
    held = [True]
    w.open_wheel(CONFIG.wheel("capture"), CONFIG.timing, QPointF(500, 400), lambda: held[0])
    w.clock.t += 300
    press(w, UP)
    held[0] = False
    w._read_hotkey()
    assert w.isVisible() and not w.cancels
    release(w, UP)
    assert w.picks[0].direction == "N"


def test_rolling_off_the_hotkey_with_a_numpad_key_down_commits_on_its_way_up(wheel_window):
    w = wheel_window
    keypad = Qt.KeyboardModifier.KeypadModifier
    held = [True]
    w.open_wheel(CONFIG.wheel("capture"), CONFIG.timing, QPointF(500, 400), lambda: held[0])
    w.clock.t += 300
    press(w, Qt.Key.Key_8, modifiers=keypad)
    held[0] = False
    w._read_hotkey()
    assert w.isVisible() and not w.cancels
    release(w, Qt.Key.Key_8, modifiers=keypad)
    assert w.picks[0].direction == "N" and w.picks[0].how == "numpad"


def test_the_grace_timer_re_aims(wheel_window):
    w = wheel_window
    wheel = wc.check({"wheels": [{"id": "x", "name": "X", "slots": {"N": {"label": "A", "command": "capture.pin"}, "E": {"label": "E", "command": "capture.pin"},
                                                                     "NE": {"label": "B", "command": "capture.meeting"}}}]}, SPECS, icon_names()).wheels[0]
    w.open_wheel(wheel, CONFIG.timing, QPointF(500, 400), None)
    press(w, UP)
    press(w, RIGHT)
    assert w.lit == "NE"
    release(w, UP)
    assert w.lit == "NE" and w._grace_timer.isActive()
    w.clock.t += 100
    w._grace_over()
    assert w.lit == "E"
    release(w, RIGHT)
    assert w.picks[0].direction == "E"


def test_it_draws_in_every_state(wheel_window, qapp):
    """Nothing lit, lit, held and empty slots, 4-way and 8-way: painting never raises."""
    w = wheel_window
    open_tapped(w, "execution")
    w.ring = 1.0
    w.grab()
    w.lit = "E"
    picture = w.grab()
    assert picture.width() >= 380
    wheel = wc.check({"wheels": [{"id": "x", "name": "A longer name", "slots": {"N": {"label": "A long label for one slot", "icon": "add", "command": "capture.pin"},
                                                                                 "NE": {"label": "B", "held": True}}}]}, SPECS, icon_names()).wheels[0]
    w.open_wheel(wheel, CONFIG.timing, QPointF(500, 400), None)
    w.ring = 0.5
    w.grab()


# ---- the wheels as a whole ----
@pytest.fixture
def app(qapp, data_root, fs, monkeypatch):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001", wheel_hotkeys={"capture": "Ctrl+Alt+Shift+F13"})
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    messages: list[tuple[str, str]] = []
    ctx = AppContext(conn, data_root, fs, settings, now=lambda: NOW)
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    a = CaptureApp(qapp, ctx)
    ctx.notify = lambda t, m: messages.append((t, m))
    a.messages = messages
    yield a
    a.wheels.window.hide()
    a.window.hide()
    a.browse.hide()
    a.tray.hide()
    qapp.removeNativeEventFilter(a.filter)
    conn.close()


def pick(app, wheel, k):
    app.wheels.open(wheel)
    w = app.wheels.window
    press(w, k)
    release(w, k)


def test_the_files_are_written_at_the_first_start(app, data_root):
    assert (data_root / wc.CONFIG_FILE).exists() and (data_root / wc.SCHEMA_FILE).exists()


def test_a_wheel_with_keys_set_is_registered_and_others_arent(app):
    wheel_ids = [i for i in app.registered if i >= hotkey.WHEEL_ID_BASE]
    assert wheel_ids == [hotkey.WHEEL_ID_BASE]
    assert hotkey.WHEEL_ID_BASE in app.hotkey_actions


def test_blank_capture_from_the_wheel(app):
    pick(app, "capture", UP)
    assert app.window.isVisible() and not app.window.content.value()[0]


def test_new_today_item_from_the_wheel(app):
    pick(app, "capture", DOWN)
    assert app.window.isVisible() and "new_task" in app.window.types and app.window.today_on


def test_a_meeting_from_the_wheel(app):
    pick(app, "capture", LEFT)
    assert app.window.isVisible() and app.window.meeting_on


def test_the_task_tree_and_today_from_the_wheels(app):
    pick(app, "browse", UP)
    assert app.browse.isVisible() and app.browse.view == "tasks"
    pick(app, "execution", UP)
    assert app.browse.view == "today"


def test_search_everything_puts_the_cursor_in_its_box(app):
    pick(app, "browse", LEFT)
    assert app.browse.isVisible()


def test_the_task_view_of_the_selected_task(app):
    app.show_browse("tasks", "T000008")
    pick(app, "execution", LEFT)
    assert "T000008" in app.browse.task_views
    for view in list(app.browse.task_views.values()):
        view.hide()


def test_the_task_view_falls_back_on_the_last_one_opened(app):
    app.browse.open_task_view("T000008")
    app.browse.sel = None
    assert app.browse.current_task_for_view() == "T000008"
    for view in list(app.browse.task_views.values()):
        view.hide()


def test_the_hotkey_again_cancels_and_another_wheels_changes(app):
    app.wheels.open("capture")
    w = app.wheels.window
    assert w.is_open() and w.wheel.id == "capture"
    app.wheels.open("browse")
    assert w.is_open() and w.wheel.id == "browse"
    app.wheels.open("browse")
    assert not w.is_open()


def test_the_usage_log_holds_no_content(app, data_root):
    pick(app, "browse", UP)
    text = (data_root / USAGE_LOG).read_bytes().decode("utf-8")
    lines = text.splitlines()
    assert text.startswith(USAGE_HEADER) and len(lines) == 2
    assert lines[1].split(",")[:6] == ["2026-10-08T14:10:00", "browse", "N", "browse.view", "arrows", "1"]


def test_a_bad_save_names_the_field_and_keeps_the_last_good_wheels(app, data_root, fs):
    before = app.wheels.config
    fs.write_text(data_root / wc.CONFIG_FILE, wc.DEFAULT_TEXT.replace('"command": "capture.new"', '"command": "capture.nwe"'))
    assert not app.wheels.reload()
    assert app.wheels.config == before
    title, text = app.messages[-1]
    assert title == "Wheels config" and "wheels[0].slots.N.command" in text and "capture.new" in text and "last good" in text


def test_the_same_problem_isnt_repeated_when_the_folder_changes(app, data_root, fs):
    fs.write_text(data_root / wc.CONFIG_FILE, wc.DEFAULT_TEXT.replace('"command": "capture.new"', '"command": "capture.nwe"'))
    app.wheels._file_changed()
    assert len(app.messages) == 1
    app.wheels._file_changed()  # settings.json saved, say, in the same folder
    assert len(app.messages) == 1
    assert not app.wheels.reload()  # Reload wheels, from the tray, says it again
    assert len(app.messages) == 2


def test_nothing_is_said_when_the_folder_changes_and_the_file_hasnt(app):
    app.wheels._file_changed()
    assert app.messages == []


def test_a_good_save_is_used_at_once(app, data_root, fs):
    fs.write_text(data_root / wc.CONFIG_FILE, wc.DEFAULT_TEXT.replace('"label": "Blank capture"', '"label": "Fresh"'))
    assert app.wheels.reload()
    assert app.wheels.config.wheel("capture").slots["N"].label == "Fresh"


def test_a_new_wheel_gets_its_settings_box_and_a_hotkey(app, data_root, fs):
    settings = app.browse.settings_view
    settings.load()
    assert list(settings.wheel_hotkeys) == ["capture", "browse", "execution"]
    data = json.loads(wc.strip_comments(wc.DEFAULT_TEXT))
    data["wheels"].append({"id": "extra", "name": "Extra", "slots": {"N": {"label": "A", "command": "capture.pin"}}})
    fs.write_text(data_root / wc.CONFIG_FILE, json.dumps(data))
    assert app.wheels.reload()
    assert list(settings.wheel_hotkeys) == ["capture", "browse", "execution", "extra"]
    assert settings.wheel_hotkeys["capture"].text() == "Ctrl+Alt+Shift+F13"


def test_settings_keeps_the_wheels_hotkeys_with_no_defaults(app):
    settings = app.browse.settings_view
    settings.load()
    assert settings.wheel_hotkeys["browse"].text() == "" and "Ctrl+Shift+2" in settings.wheel_hotkeys["browse"].placeholderText()
    settings.suggest_hotkeys()
    assert settings.wheel_hotkeys["browse"].text() == "" and settings.more_hotkeys["today_panel_hotkey"].text() == ""
    settings.wheel_hotkeys["browse"].setText("Ctrl+Alt+Shift+F14")
    assert "wheel_hotkeys" in settings.save()
    assert app.ctx.settings.wheel_hotkeys == {"capture": "Ctrl+Alt+Shift+F13", "browse": "Ctrl+Alt+Shift+F14"}
    assert hotkey.WHEEL_ID_BASE + 1 in app.registered


def test_settings_refuses_a_wheel_hotkey_thats_taken(app):
    with pytest.raises(SettingsProblem, match="already the hotkey"):
        check_values(app.ctx, {"hotkey": "Ctrl+Alt+Shift+F13", "wheel_hotkeys": {"capture": "Ctrl+Alt+Shift+F13"}})
    with pytest.raises(SettingsProblem, match="can't be used"):
        check_values(app.ctx, {"hotkey": "Ctrl+Shift+Space", "wheel_hotkeys": {"capture": "Nonsense+Q"}})


def test_pause_covers_the_wheels(app):
    assert hotkey.WHEEL_ID_BASE in app.registered
    app.toggle_pause()
    assert not app.registered
    app.toggle_pause()
    assert hotkey.WHEEL_ID_BASE in app.registered


def test_the_palette_lists_each_slot_with_its_wheel_and_direction(app):
    labels = [c.label for c in app.wheels.palette_commands()]
    assert "Capture wheel, up: Blank capture" in labels and "Execution wheel, left: Task view" in labels
    assert "Wheel: Open the Browse wheel" in labels
    assert not any("Agent window" in x for x in labels)  # a held slot does nothing
    assert any(c.label == "Capture wheel, up: Blank capture" for c in app.browse.palette_commands())
    assert any(c.label == "Capture wheel, up: Blank capture" for c in app.window.palette_commands())


def test_from_the_palette_there_is_no_selection_to_read(app):
    app.wheels.snapshot = object()
    next(c for c in app.wheels.palette_commands() if c.label == "Capture wheel, right: Email or file").run()
    assert app.wheels.snapshot is None and app.window.pinned
    app.window.pin_window.hide()


def test_ctrl_k_opens_the_capture_windows_palette_from_the_capture_wheel(app, monkeypatch):
    opened = []
    monkeypatch.setattr(app.window, "open_palette", lambda: opened.append("capture"))
    monkeypatch.setattr(app.browse, "open_palette", lambda: opened.append("browse"))
    app.wheels.open("capture")
    press(app.wheels.window, Qt.Key.Key_K, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert app.window.isVisible() and opened == ["capture"]
    app.wheels._palette(app.wheels.config.wheel("browse"))
    assert app.browse.isVisible() and opened == ["capture", "browse"]


def test_a_command_that_fails_says_so_and_doesnt_stop_the_app(app, monkeypatch):
    monkeypatch.setattr(app, "show_browse", lambda *a: 1 / 0)
    pick(app, "browse", UP)
    assert app.messages[-1][0] == "Wheel" and "ZeroDivisionError" in app.messages[-1][1]


def test_the_config_opener_starts_only_that_file(tmp_path):
    from docrepo.opener import start_own_file

    started = []
    config = tmp_path / "Config" / "wheels.jsonc"
    assert start_own_file(config, started.append) is None and started == [str(config)]
    assert "isn't the wheels' config" in start_own_file(tmp_path / "Config" / "evil.exe", started.append)
    assert len(started) == 1

    def refuses(_path):
        raise OSError("no program")

    assert "no program for it" in start_own_file(config, refuses)


# ---- the blank capture, with a draft set aside (decision 215) ----
@pytest.fixture
def capture(app):
    return app.window


def type_draft(capture, text="A draft about the pump"):
    capture._set_plain(capture.content, text)
    capture.draft_dirty = True


def test_a_draft_is_set_aside_and_the_window_is_blank(capture, data_root):
    capture.show_capture()
    type_draft(capture)
    capture.title.setText("Its title")
    capture.open_blank()
    assert capture.content.value()[0] == "" and capture.title.text() == ""
    assert "set aside" in capture.draft_label.text()
    kept = json.loads((data_root / "System" / "capture-draft-aside.json").read_text(encoding="utf-8"))
    assert kept["content"] == "A draft about the pump"


def test_closing_the_blank_capture_empty_brings_the_draft_back(capture):
    capture.show_capture()
    type_draft(capture)
    capture.today_on = False
    capture.n_due.set_value("2026-11-02")
    capture.types = {"new_task"}
    capture.open_blank()
    assert capture.n_due.value() is None
    capture.hide()
    assert capture.content.value()[0] == "A draft about the pump" and capture.n_due.value() == "2026-11-02"
    assert "came back" in capture.draft_label.text() and capture.aside.data is None


def test_a_draft_set_aside_keeps_its_duration_and_hours_unit(capture):
    """Release 5.46's fields in the capture window come back with the rest of the form."""
    capture.show_capture()
    type_draft(capture)
    capture.types = {"new_task"}
    capture.n_duration.setText("5")
    capture.n_calendar.setChecked(True)
    capture.n_asg_hours.setText("6")
    capture.n_asg_row.set_per_day(True)
    capture.open_blank()
    assert capture.n_duration.text() == "" and not capture.n_calendar.isChecked() and not capture.n_asg_row.per_day()
    capture.hide()
    assert capture.n_duration.text() == "5" and capture.n_calendar.isChecked()
    assert capture.n_asg_hours.text() == "6" and capture.n_asg_row.per_day()


def test_saving_the_blank_capture_brings_the_draft_back(capture):
    capture.show_capture()
    type_draft(capture)
    capture.open_blank()
    type_draft(capture, "A quick other note")
    capture.save()
    assert capture.content.value()[0] == "A draft about the pump"
    assert capture.aside.data is None


def test_hiding_the_blank_capture_with_something_typed_keeps_both(capture):
    capture.show_capture()
    type_draft(capture)
    capture.open_blank()
    type_draft(capture, "Something new")
    capture.hide()
    assert capture.content.value()[0] == "Something new" and capture.aside.data is not None
    capture.save()
    assert capture.content.value()[0] == "A draft about the pump"


def test_a_window_with_nothing_in_it_sets_nothing_aside(capture):
    capture.show_capture()
    capture.set_task("T000008")
    capture.open_blank()
    assert capture.aside.data is None and capture.task is None


def test_its_files_come_back_while_docrepo_runs(capture, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("x", encoding="utf-8")
    capture.show_capture()
    capture.add_paths([str(f)])
    capture.open_blank()
    assert not capture.files
    capture.hide()
    assert [e.row.name for e in capture.files] == ["notes.txt"]


def test_a_restart_keeps_the_draft_set_aside(capture, data_root, tmp_path):
    from docrepo.ui.draft_aside import DraftAside

    f = tmp_path / "notes.txt"
    f.write_text("x", encoding="utf-8")
    capture.show_capture()
    type_draft(capture)
    capture.add_paths([str(f)])
    capture.open_blank()
    capture.aside = DraftAside(capture)  # as a new start reads it
    assert capture.aside.data["content"] == "A draft about the pump"
    capture.hide()
    assert capture.content.value()[0] == "A draft about the pump" and "notes.txt" in capture.draft_label.text()


def test_it_comes_back_in_the_pinned_window_if_that_is_where_it_was(capture):
    capture.show_capture()
    type_draft(capture)
    capture.pin()
    capture.open_blank()
    assert not capture.pinned
    capture.hide()
    assert capture.pinned and capture.content.value()[0] == "A draft about the pump"
    capture.pin_window.hide()


def test_one_already_aside_asks_about_this_one(capture, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    capture.show_capture()
    type_draft(capture)
    capture.open_blank()
    type_draft(capture, "A second one")
    # Keep working on this one: nothing moves
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.defaultButton())
    capture.open_blank()
    assert capture.content.value()[0] == "A second one" and capture.aside.data["content"] == "A draft about the pump"
    # Clear this one
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[1])
    capture.open_blank()
    assert capture.content.value()[0] == "" and capture.aside.data["content"] == "A draft about the pump"
