"""Release 5.149, saved summary sets in the quick summary's window, offscreen (the design workspace's
``docs/mods/summary-sets-plan.md``, decisions 649 to 651): Save as… and Rename… in the header, the pin's line in the box
and picking it, its right-click menu with Rename… and Unpin, Undo, changing a set by saving under its name again, the
palette's lines and a wheel slot that names one. Every name here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
import types  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import tagged  # noqa: E402
from docrepo import wheels_config as wc  # noqa: E402
from docrepo.config import SETTINGS_FILE, Settings  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_summary import QuickSummary  # noqa: E402
from docrepo.ui.wheel_commands import REGISTRY, SPECS, icon_names  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TOM, MIKE, MEETING, RIGGING = "P003", "P004", "T000010", "T000012"
MORNING = f"tag:P204B + person:{TOM} + person:{MIKE} + agenda:{MEETING}"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    tagged.add_label(conn, "P-204B", datetime(2026, 10, 1, 9, 0), "Feed pump B")
    conn.execute("UPDATE tasks SET description = 'The seal on P-204B leaks' WHERE id = ?", (RIGGING,))
    settings = Settings(me="P001")
    settings.save(fs, root)
    return AppContext(conn, root, fs, settings, now=lambda: NOW)


@pytest.fixture
def window(ctx):
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    browse.said = []
    browse.say = lambda text, error=False: browse.said.append((text, error))
    app = types.SimpleNamespace(ctx=ctx, browse=browse, show_browse=lambda view=None, task=None: None)
    w = QuickSummary(app)
    w.capture_window = capture
    w.asked = []
    w.answers = []
    w.ask_name = lambda title, words, name: (w.asked.append((title, words, name)), w.answers.pop(0) if w.answers else None)[1]
    yield w
    QApplication.processEvents()
    for shown in (w.picker, w, browse, capture):
        shown.hide()
    for widget in (w, browse, capture):
        widget.deleteLater()
    QApplication.processEvents()


def press(widget, key, text: str = "", mods=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, mods, text))


def saved_file(ctx) -> dict:
    return json.loads((ctx.data_root / SETTINGS_FILE).read_text(encoding="utf-8"))


def first_row(w: QuickSummary) -> tuple:
    return next(r for r in w.list.rows() if r[0] != "head")


def save_morning(w: QuickSummary) -> None:
    w.open_it(None, MORNING)
    w.answers.append("Morning meeting")
    w.save_or_rename()


# ---- Save as… (decision 649) ----
def test_save_as_shows_with_two_or_more_and_names_and_pins_them(window, ctx):
    window.open_it(None, f"person:{TOM}")
    assert window.save_button.isHidden()
    window.open_it(None, MORNING)
    assert not window.save_button.isHidden() and window.save_button.text() == "Save as…"
    window.answers.append("  Morning meeting ")
    window.save_or_rename()
    assert window.asked[-1][0] == "Save as" and "P-204B + Tom Becker + Mike Ortiz + Business team meeting" in window.asked[-1][1]
    assert ctx.settings.summary_pins[0] == MORNING and ctx.settings.summary_names == {MORNING: "Morning meeting"}
    assert saved_file(ctx)["summary_names"] == {MORNING: "Morning meeting"}
    assert window.subject.saved and window.view.subject.name == "Morning meeting"
    assert window.view.kind_line == "Saved set · 1 tag · 2 people · 1 agenda" and "Morning meeting" in window.header.toHtml()
    assert window.save_button.text() == "Rename…" and window.pin_button.isChecked() and not window.page_button.isEnabled()
    assert window.windowTitle() == "Morning meeting: quick summary"
    assert window.message.text() == "Saved as Morning meeting, first in the box's list." and not window.undo_button.isHidden()


def test_cancelling_save_as_changes_nothing(window, ctx):
    window.open_it(None, MORNING)
    window.save_or_rename()  # no answer: cancelled
    assert ctx.settings.summary_pins == [] and ctx.settings.summary_names == {}


def test_a_pin_of_the_same_subjects_in_another_order_is_the_one_named(window, ctx):
    other_order = f"person:{MIKE} + agenda:{MEETING} + tag:P204B + person:{TOM}"
    ctx.settings.summary_pins = ["label:Safety", other_order]
    window.open_it(None, MORNING)
    assert window.pin_button.isChecked()  # pinned, in another order
    window.answers.append("Morning meeting")
    window.save_or_rename()  # Ctrl+S's
    assert ctx.settings.summary_pins == ["label:Safety", other_order] and ctx.settings.summary_names == {other_order: "Morning meeting"}
    assert window.message.text() == "Saved as Morning meeting, where its pin was."


# ---- the pin's line and picking it (decision 649) ----
def test_the_pin_shows_its_name_with_its_parts_and_its_number_opens_it(window, ctx):
    save_morning(window)
    window.subject = None
    window.open_it()
    kind, key, words = first_row(window)
    assert (kind, key) == ("many", MORNING) and words["name"] == "Morning meeting" and words["set"] and words["pinned"]
    assert words["kind"] == "P-204B + Tom Becker + Mike Ortiz + Business team meeting" and words["number"] == "1"
    press(window.box, Qt.Key.Key_1, "1")
    assert window.subject.saved and window.subject.key == MORNING and window.view.subject.name == "Morning meeting"
    assert [window.chips_lay.itemAt(i).widget().text() for i in range(window.chips_lay.count())][0] == "P-204B  ✕"


def test_typing_finds_the_saved_set_first(window, ctx):
    save_morning(window)
    window.box.setText("morn")
    window._typed("morn")
    rows = window.list.rows()
    assert rows[0][2]["title"] == "Saved sets" and rows[1][2]["name"] == "Morning meeting" and rows[1][1] == MORNING
    press(window.box, Qt.Key.Key_Return)
    assert window.subject.saved and window.subject.key == MORNING


# ---- Rename… and Unpin (decision 650) ----
def test_the_rows_menu_has_rename_and_unpin(window, ctx):
    save_morning(window)
    window.open_it()
    menu = window.row_menu(*first_row(window)[:2])
    assert [a.text() for a in menu.actions()] == ["Rename…", "Unpin"]
    window.answers.append("Control room morning")
    menu.actions()[0].trigger()
    assert ctx.settings.summary_names == {MORNING: "Control room morning"} and first_row(window)[2]["name"] == "Control room morning"
    assert window.message.text() == "Renamed Morning meeting to Control room morning."
    window.row_menu(*first_row(window)[:2]).actions()[1].trigger()
    assert ctx.settings.summary_pins == [] and ctx.settings.summary_names == {} and "summary_names" not in saved_file(ctx)
    assert window.message.text() == "Unpinned Control room morning: its name went with it."
    window.do_undo()
    assert ctx.settings.summary_pins == [MORNING] and ctx.settings.summary_names == {MORNING: "Control room morning"}


def test_a_combinations_menu_has_save_as_and_one_subjects_has_pin(window, ctx):
    window.open_it(None, f"person:{TOM} + person:{MIKE}")
    window.open_it(None, f"person:{TOM}")
    window.subject = None
    window.open_it()
    rows = [r for r in window.list.rows() if r[0] != "head"]
    assert [a.text() for a in window.row_menu(*rows[0][:2]).actions()] == ["Pin"]  # Tom, the latest
    menu = window.row_menu(*rows[1][:2])
    assert [a.text() for a in menu.actions()] == ["Save as…", "Pin"]
    window.answers.append("Tom and Mike")
    menu.actions()[0].trigger()
    assert ctx.settings.summary_names == {f"person:{TOM} + person:{MIKE}": "Tom and Mike"} and first_row(window)[2]["name"] == "Tom and Mike"


def test_rename_refuses_a_name_another_set_has(window, ctx):
    ctx.settings.summary_pins = [MORNING, f"person:{TOM} + person:{MIKE}"]
    ctx.settings.summary_names = {MORNING: "Morning meeting", f"person:{TOM} + person:{MIKE}": "Tom and Mike"}
    window.open_it(None, MORNING)
    assert window.save_button.text() == "Rename…"
    window.answers.append("tom and mike")
    window.save_or_rename()
    assert ctx.settings.summary_names[MORNING] == "Morning meeting" and window.message.text() == "There's a saved set called tom and mike already."


def test_unpinning_from_the_star_takes_the_name_and_the_summary_loses_it(window, ctx):
    save_morning(window)
    window.toggle_pin()
    assert ctx.settings.summary_names == {} and not window.subject.saved and window.view.kind_line.startswith("Together")
    assert window.save_button.text() == "Save as…"


# ---- changing a set (decision 649) ----
def test_a_part_added_then_saving_under_its_name_changes_the_set(window, ctx):
    save_morning(window)
    window.box.setText("safe")
    window._typed("safe")
    press(window.box, Qt.Key.Key_Return, mods=Qt.KeyboardModifier.ControlModifier)
    assert not window.subject.saved and window.subject.key == f"{MORNING} + label:Safety"
    assert window.message.text() == "Not Morning meeting any more: Save as… (Ctrl+S) under its name changes the set."
    window.answers.append("Morning meeting")
    window.save_or_rename()
    assert window.asked[-1][2] == "Morning meeting"  # offered
    assert ctx.settings.summary_pins == [f"{MORNING} + label:Safety"] and ctx.settings.summary_names == {f"{MORNING} + label:Safety": "Morning meeting"}
    assert window.message.text().startswith("Saved as Morning meeting, in place of the Morning meeting before (P-204B + Tom Becker")
    window.do_undo()
    assert ctx.settings.summary_pins == [MORNING] and ctx.settings.summary_names == {MORNING: "Morning meeting"}


def test_a_set_with_a_part_gone_keeps_its_name(window, ctx):
    key = f"person:{TOM} + label:Gone"
    ctx.settings.summary_pins, ctx.settings.summary_names = [key], {key: "Morning meeting"}
    window.open_it()
    assert first_row(window)[1] == key and first_row(window)[2]["name"] == "Morning meeting" and first_row(window)[2]["pinned"]
    press(window.box, Qt.Key.Key_1, "1")
    assert window.view.subject.name == "Morning meeting" and window.view.kind_line == "Saved set · 1 person · 1 gone"
    assert window.pin_button.isChecked() and window.save_button.text() == "Rename…"


# ---- the palette and a wheel slot (decision 651) ----
def test_the_palette_lists_each_saved_set(window, ctx):
    save_morning(window)
    opened: list = []
    ctx.open_summary = lambda key=None: opened.append(key)
    browse = window.app.browse
    for cmds in (browse.palette_commands(), window.capture_window.palette_commands()):
        line = next((c for c in cmds if c.label == "Summary: Morning meeting"), None)
        assert line is not None
        line.run()
    assert opened == [MORNING, MORNING]


def test_a_wheel_slot_opens_a_saved_set_by_its_name(window, ctx):
    save_morning(window)
    window.hide()
    window.subject = None
    window.open_it(None, None, "morning MEETING")
    assert window.subject.saved and window.subject.key == MORNING
    window.open_it(None, None, "Evening meeting")
    assert window.stack.currentWidget() is window.list and window.message.property("error")
    assert window.message.text().startswith("No saved set is called Evening meeting")
    calls: list = []
    app = types.SimpleNamespace(wheels=types.SimpleNamespace(quick_summary=lambda key=None, set_name="": calls.append((key, set_name))))
    REGISTRY["summary.open"].run(app, {"set": "Morning meeting"})
    REGISTRY["summary.open"].run(app, {"set": ""})
    assert calls == [(None, "Morning meeting"), (None, "")]


def _slot(args: dict) -> str:
    slot = {"label": "Morning meeting", "icon": "people", "command": "summary.open", "args": args}
    return json.dumps({"wheels": [{"id": "execution", "name": "Execution", "slots": {"SE": slot}}]})


def test_a_wheel_slot_names_a_set_as_text():
    icons = icon_names()
    assert wc.parse(_slot({"set": "Morning meeting"}), SPECS, icons).wheel("execution").slots["SE"].args == {"set": "Morning meeting"}
    assert wc.parse(wc.DEFAULT_TEXT, SPECS, icons).wheel("execution").slots["S"].args == {"set": ""}  # the box, as before
    for bad in ({"set": ""}, {"set": 3}, {"set": "x" * 201}):
        with pytest.raises(wc.ConfigError) as e:
            wc.parse(_slot(bad), SPECS, icons)
        assert "args.set" in str(e.value) and "is a name, as text" in str(e.value)
    slots = wc.schema(SPECS, icons)["properties"]["wheels"]["items"]["properties"]["slots"]["properties"]
    rule = next(r for r in slots["S"]["allOf"] if r["if"]["properties"]["command"]["const"] == "summary.open")
    assert rule["then"]["properties"]["args"]["properties"]["set"] == {"type": "string", "minLength": 1, "maxLength": 200}
