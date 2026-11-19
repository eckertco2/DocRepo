"""The glossary lookup (release 5.172, the design workspace's glossaries plan, decisions 807 to 809), offscreen: the Browse
wheel's NE, the palettes and its hotkey; the popup on the list of glossaries, the last used first, or straight on the only
one; rows narrowing as words are typed, the tag first and bold, and how many places mention it; Enter copying the tag,
Ctrl+C the row and Ctrl+Enter opening the tag's page; Backspace back to the glossaries and Esc closing; and the Browse
wheel's NE added once to a file from before. The glossaries are made up: P-204A, V-110 and Line 2 are nobody's plant."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import types  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import glossaries, hotkey, tagged  # noqa: E402
from docrepo import wheels_config as wc  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.save import CaptureDraft, save_capture  # noqa: E402
from docrepo.ui import glossary_lookup as gl  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.palette import GLOSSARY_LOOKUP  # noqa: E402
from docrepo.ui.task_list import Words  # noqa: E402
from docrepo.ui.wheel_commands import REGISTRY, SPECS, icon_names  # noqa: E402

ICONS = icon_names()
NOW = datetime(2026, 11, 19, 9, 0)
COLUMNS = ("Line", "Tag No.", "Description", "Service")
ROWS = [
    ["Line 2", "P-204A", "Reactor feed pump A", "Feed"],
    ["Line 2", "P-204B", "Reactor feed pump B", "Feed"],
    ["Line 1", "V-110", "Knock-out drum", ""],
    ["Line 1", "E-301", "Overhead condenser", "Cooling"],
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    settings = Settings(me="P001")
    settings.save(fs, root)
    return AppContext(conn, root, fs, settings, now=lambda: NOW)


def add(ctx, name: str, rows=ROWS, columns=COLUMNS, tag: int | None = 1) -> int:
    return glossaries.create(ctx.conn, name, columns, tag, rows, f"{name}.csv", NOW)


@pytest.fixture
def host(ctx):
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    given_back: list[bool] = []
    shown: list[tuple] = []
    app = types.SimpleNamespace(ctx=ctx, browse=browse, show_browse=lambda *a: shown.append(a),
                                wheels=types.SimpleNamespace(give_back=lambda: given_back.append(True)))
    h = gl.GlossaryLookup(app)
    h.given_back, h.shown = given_back, shown
    yield h
    QApplication.processEvents()
    for widget in (h.popup, h, browse, capture):
        widget.hide()
    for widget in (h, browse, capture):
        widget.deleteLater()
    QApplication.processEvents()


def open_it(h: gl.GlossaryLookup) -> gl.GlossaryPopup:
    h.open_it(QApplication.primaryScreen())
    return h.popup


def press(widget, key, text: str = "", mods=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, mods, text))


def type_in(p: gl.GlossaryPopup, text: str) -> None:
    p.search.setText(text)


def labels(p: gl.GlossaryPopup) -> list[str]:
    return [o.label for o in p.list.rows()]


def tags_listed(p: gl.GlossaryPopup) -> list[str]:
    return [o.value for o in p.list.rows() if not isinstance(o, Words)]


# ---- where it's reached (decision 808) ----
def test_the_browse_wheel_s_ne_the_palettes_and_its_hotkey_open_it(qapp, ctx, monkeypatch):
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    add(ctx, "Equipment")
    app = CaptureApp(qapp, ctx)
    try:
        slot = app.wheels.config.wheel("browse").slots["NE"]
        assert (slot.label, slot.icon, slot.command) == ("Glossary lookup", "tagged", "glossary.lookup")
        REGISTRY["glossary.lookup"].run(app, {})
        h = app.wheels._glossary_lookup
        assert h is not None and h.popup.isVisible() and h.popup.glossary is not None  # the only one, opened straight
        h.popup.close()
        for window in (app.browse, app.window):
            names = [c.name for c in window.palette_commands()]
            assert GLOSSARY_LOOKUP in names and "Glossary lookup" in names, window  # its own row, and the wheel's slot
        app.wheels.snapshot = object()
        next(c for c in app.browse.palette_commands() if c.name == GLOSSARY_LOOKUP).run()
        assert app.wheels.snapshot is None and h.popup.isVisible()  # from Ctrl+K, Esc gives the keyboard to no other program
        h.popup.close()
        app.hotkey_actions[hotkey.HOTKEY_IDS["lookup_hotkey"]]()
        assert h.popup.isVisible()
        h.popup.close()
    finally:  # the app's minute timer would go on ticking into later tests
        app.timer.stop()
        for window in (app.wheels.window, app.window, app.browse, app.tray):
            window.hide()
        qapp.removeNativeEventFilter(app.filter)


# ---- the list of glossaries (decision 807) ----
def test_with_none_it_says_where_to_import_one(host):
    p = open_it(host)
    assert p.glossary is None and labels(p) == [gl.NONE_YET]


def test_the_last_used_first_and_enter_opens_one(host, ctx):
    add(ctx, "Acronyms", rows=[["HAZOP", "Hazard and operability study"]], columns=("Term", "Meaning"), tag=None)
    eq = add(ctx, "Equipment")
    add(ctx, "Instruments", rows=[["Line 1", "FT-101", "Feed flow", ""]])
    p = open_it(host)
    assert labels(p) == ["Acronyms", "Equipment", "Instruments"] and p.note.text() == gl.HINT_LIST
    type_in(p, "equip")
    assert labels(p) == ["Equipment"]
    press(p.search, Qt.Key.Key_Return)
    assert p.glossary is not None and p.glossary.id == eq and p.search.text() == "" and p.note.text() == gl.HINT_ROWS
    assert ctx.settings.glossary_recent == [str(eq)]
    assert Settings.load(ctx.data_root).glossary_recent == [str(eq)]  # kept for the next time DocRepo starts
    p.close()
    p = open_it(host)
    assert labels(p) == ["Equipment", "Acronyms", "Instruments"]
    press(p.search, Qt.Key.Key_Down)
    press(p.search, Qt.Key.Key_Tab)  # Tab opens one too
    assert p.glossary is not None and p.glossary.name == "Acronyms"


def test_backspace_in_an_empty_box_goes_back_and_esc_closes(host, ctx):
    add(ctx, "Equipment")
    add(ctx, "Instruments", rows=[["Line 1", "FT-101", "Feed flow", ""]])
    p = open_it(host)
    press(p.search, Qt.Key.Key_Return)
    assert p.glossary is not None
    type_in(p, "p")
    press(p.search, Qt.Key.Key_Backspace)  # with words in the box, Backspace is the box's
    assert p.glossary is not None
    type_in(p, "")
    press(p.search, Qt.Key.Key_Backspace)
    assert p.glossary is None and labels(p)[:1] == ["Equipment"]
    press(p.search, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not p.isVisible() and host.given_back == [True]


# ---- a glossary's rows (decision 807) ----
def test_the_rows_narrow_as_words_are_typed(host, ctx):
    add(ctx, "Equipment")
    p = open_it(host)
    assert p.glossary is not None and p.glossary.name == "Equipment"  # the only one: opened straight on it
    assert tags_listed(p) == ["P-204A", "P-204B", "V-110", "E-301"] and p.title.text() == "Equipment · 4 rows"
    type_in(p, "feed pump")
    assert tags_listed(p) == ["P-204A", "P-204B"] and p.title.text() == "Equipment · 2 rows"
    type_in(p, "v110")
    assert tags_listed(p) == ["V-110"]
    parts, right = p.parts(p.list.rows()[0])
    assert parts[0] == ("V-110", "bold") and ("Knock-out drum", "text") in parts and right == ""
    type_in(p, "nothing like it")
    assert isinstance(p.list.rows()[0], Words) and "No row of Equipment" in labels(p)[0]


def test_a_tag_on_the_tag_list_says_how_often_it_is_mentioned(host, ctx):
    add(ctx, "Equipment")
    tagged.add_label(ctx.conn, "P-204A", NOW, "Reactor feed pump A")
    save_capture(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, CaptureDraft(content="Seal faces for P-204A are late."), NOW)
    p = open_it(host)
    type_in(p, "p-204")
    rows = p.list.rows()
    assert p.parts(rows[0])[1] == "in 1 place" and p.parts(rows[1])[1] == ""  # P-204B isn't on the tag list


def test_fifty_are_listed_of_more(host, ctx):
    add(ctx, "Instruments", rows=[["Line 1", f"FT-{n:03d}", "Flow transmitter", ""] for n in range(80)])
    p = open_it(host)
    type_in(p, "flow")
    assert len(tags_listed(p)) == 50 and p.title.text() == "Instruments · 50 of 80 rows"


# ---- Enter, Ctrl+C and Ctrl+Enter (decision 807) ----
def test_enter_copies_the_tag_and_closes_giving_the_keyboard_back(host, ctx):
    add(ctx, "Equipment")
    p = open_it(host)
    type_in(p, "drum")
    press(p.search, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert QGuiApplication.clipboard().text() == "V-110" and not p.isVisible() and host.given_back == [True]


def test_with_no_tag_column_enter_copies_the_first_cell(host, ctx):
    add(ctx, "Acronyms", rows=[["HAZOP", "Hazard and operability study"], ["P&ID", "Piping and instrument diagram"]],
        columns=("Term", "Meaning"), tag=None)
    p = open_it(host)
    assert p.note.text() == gl.HINT_NO_TAGS
    type_in(p, "piping")
    press(p.search, Qt.Key.Key_Enter)
    assert QGuiApplication.clipboard().text() == "P&ID"


def test_ctrl_c_copies_the_whole_row_tab_separated(host, ctx):
    add(ctx, "Equipment")
    p = open_it(host)
    type_in(p, "p-204b")
    press(p.search, Qt.Key.Key_C, "c", Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    assert QGuiApplication.clipboard().text() == "Line 2\tP-204B\tReactor feed pump B\tFeed" and not p.isVisible()


def test_ctrl_enter_opens_the_tag_s_page_or_says_it_has_none(host, ctx):
    add(ctx, "Equipment")
    tagged.add_label(ctx.conn, "P-204A", NOW, "Reactor feed pump A")
    p = open_it(host)
    type_in(p, "p-204b")
    press(p.search, Qt.Key.Key_Return, mods=Qt.KeyboardModifier.ControlModifier)
    assert p.isVisible() and p.note.text() == "P-204B isn't on the tag list, so it has no page."
    type_in(p, "p-204a")
    press(p.search, Qt.Key.Key_Return, mods=Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    browse = host.app.browse
    assert not p.isVisible() and browse.sel == ("tagged", "P204A") and host.shown == [()]
    assert host.given_back == []  # the browse tool has the keyboard now


def test_it_changes_nothing_in_docs_db(host, ctx):
    add(ctx, "Equipment")
    before = ctx.conn.total_changes
    p = open_it(host)
    for typed in ("p", "p-204", "feed pump", ""):
        type_in(p, typed)
    press(p.search, Qt.Key.Key_Return)
    assert ctx.conn.total_changes == before


# ---- the Browse wheel's NE (decision 808) ----
OLD_BROWSE = wc._OLD_BROWSE_END.replace("{nl}", "\n")
NEW_BROWSE = wc._LOOKUP_END.replace("{nl}", "\n")


def test_the_default_has_the_lookup_on_the_browse_wheel_s_ne():
    slot = wc.parse(wc.DEFAULT_TEXT, SPECS, ICONS).wheel("browse").slots["NE"]
    assert (slot.label, slot.icon, slot.command) == ("Glossary lookup", "tagged", "glossary.lookup")


def test_a_file_from_before_gets_the_lookup_once(data_root, fs):
    old = wc.DEFAULT_TEXT.replace(NEW_BROWSE, OLD_BROWSE)
    assert "glossary.lookup" not in old and wc.lookup_slot(old) == wc.DEFAULT_TEXT
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    path = data_root / wc.CONFIG_FILE
    path.write_bytes(("// mine\n" + old).encode("utf-8"))
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    assert path.read_bytes().decode("utf-8") == "// mine\n" + wc.DEFAULT_TEXT
    assert wc.load(data_root, SPECS, ICONS).wheel("browse").slots["NE"].command == "glossary.lookup"
    path.write_bytes(old.replace("\n", "\r\n").encode("utf-8"))  # Windows' line endings stay
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    assert path.read_bytes().decode("utf-8") == wc.DEFAULT_TEXT.replace("\n", "\r\n")
    assert wc.lookup_slot(wc.DEFAULT_TEXT) == wc.DEFAULT_TEXT  # once is enough


def test_a_browse_wheel_you_changed_or_whose_ne_is_taken_stays(data_root, fs):
    old = wc.DEFAULT_TEXT.replace(NEW_BROWSE, OLD_BROWSE)
    taken = old.replace('"N": { "label": "Task tree"', '"NE": { "label": "Mine", "icon": "tasks", "command": "capture.pin" },\n        "N": { "label": "Task tree"')
    assert wc.parse(taken, SPECS, ICONS).wheel("browse").slots["NE"].label == "Mine"
    relabelled = old.replace('"label": "Search everything"', '"label": "Everything"')
    named = old.replace("// search.files:", "// glossary.lookup is on my Execution wheel. search.files:")
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    path = data_root / wc.CONFIG_FILE
    for mine in (taken, relabelled, named, "{ not json"):
        assert wc.lookup_slot(mine) == mine
        path.write_bytes(mine.encode("utf-8"))
        wc.write_defaults(fs, data_root, SPECS, ICONS)
        assert path.read_bytes().decode("utf-8") == mine


