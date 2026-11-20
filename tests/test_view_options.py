"""Release 5.184, Filter and Display (the redesign plan's decision 855): every list view's header is one 48 px row with its
title, its count, its commands, Filter, Display and the fold buttons; the filters are in the Filter panel and the
arrangements in the Display panel, as the widgets they always were; a filter off its default is a chip under the row; and
what fits neither panel is in a tool row. Driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QPushButton, QWidget  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.filter_chips import FilterChips  # noqa: E402
from docrepo.ui.lists.common import TODAY_MINE_KEY  # noqa: E402
from docrepo.ui.view_options import PLACES, ROW_HEIGHT  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


def close_popups() -> None:
    """A popup left open by an earlier test (a panel, a menu) would take the next one's place on Qt's stack of popups."""
    for _ in range(10):
        popup = QApplication.activePopupWidget()
        if popup is None:
            return
        popup.close()
        QApplication.processEvents()


@pytest.fixture
def browse(ctx):
    close_popups()
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1440, 900)
    for _ in range(5):  # its own showing and activation, settled before a panel opens: a popup closes when another window activates
        QApplication.processEvents()
    yield w
    for panel in (w.head.filter_panel, w.head.display_panel):
        panel.hide()
    close_popups()
    capture.deleteLater()
    w.deleteLater()


def name_of(w: QWidget) -> str:
    """What a control is called here: its accessible name, its noun, its words, or its kind."""
    if w.accessibleName():
        return w.accessibleName()
    if getattr(w, "noun", ""):
        return w.noun
    words = w.text() if hasattr(w, "text") and not isinstance(w, QLineEdit) else ""
    return words or type(w).__name__


def places(browse) -> dict[str, str]:
    """Each control the view put in its header, by name, and where it is."""
    h = browse.head
    out: dict[str, str] = {}
    for w in h.filter_panel.controls:
        out[name_of(w)] = "filter"
    for w in h.display_panel.controls:
        out[name_of(w)] = "display"
    for w in h.commands():
        out[name_of(w)] = "command"
    for i in range(h.folds_layout.count()):
        out[name_of(h.folds_layout.itemAt(i).widget())] = "fold"
    for i in range(h.tools_layout.count()):
        w = h.tools_layout.itemAt(i).widget()
        if not (isinstance(w, QLabel) and w.objectName() == "fieldLabel"):
            out[name_of(w)] = "tool"
    return out


FOLDS = {"Collapse a level": "fold", "Expand a level": "fold"}
#: Every list view's controls and where each goes: the plan's table (redesign-lane-b-plan.md, 5.184's "Every list view").
#: A control a view adds that isn't here fails its test, so a new filter can't land in the tool row unnoticed.
TABLE = {
    "tasks": {"Urgent only": "filter", "Show parked": "filter", "Show closed": "filter", "Show routine": "filter", "Labels": "filter",
              "People": "filter", "Priority": "filter", "Sort": "display", "Group by": "display", "Select": "display", **FOLDS},
    "due": {"Sort": "display", "Group by": "display", "Select": "display", **FOLDS},
    "today": {"Task": "tool", "Note": "tool", "Quick task or note": "tool", "Add": "tool", "Mine only": "filter", **FOLDS},
    "agenda": {"Agenda for": "tool", "Copy as Markdown": "command", "Quick summary": "command", "Discussion or meeting": "command", **FOLDS},
    "activity": {"Show": "filter", "People": "filter", "Labels": "filter", "What": "filter", "Group by": "display", "Select": "display",
                 "Copy as Markdown": "command", **FOLDS},
    "docs": {"Task": "filter", **FOLDS},
    "people": {"Show retired": "filter", "Add person": "command", "Import people…": "command"},
    "labels": {"Show retired": "filter", "Add label": "command", **FOLDS},
    "tagged": {"Mentioned only": "filter", "Import…": "command", "Export…": "command", "Add…": "command", "Patterns…": "command"},
    "glossaries": {"Find in the picked glossary's rows": "tool", "Import…": "command"},
    "templates": {"New template": "command", "Import…": "command", **FOLDS},
    "unfiled": {}, "discarded": {}, "search": {},
}


@pytest.mark.parametrize("view", sorted(TABLE))
def test_each_views_controls_are_where_the_table_says(browse, view):
    if view == "search":  # Search everything's view is what a search opens
        browse.search_box.setText("impeller")
        browse._run_search()
    else:
        browse.set_view(view)
    QApplication.processEvents()
    got = places(browse)
    want = TABLE[view]
    # Group by shows on a list only when there's a parent label, and a fold only where something nests: what's there must be
    # in the table, in its place, and what the table has that's there must be in its place too.
    assert set(got) <= set(want), f"{view}: not in the table: {set(got) - set(want)}"
    for name, where in got.items():
        assert where == want[name], (view, name)
    assert set(want) - set(got) <= {"Group by", "Collapse a level", "Expand a level", "Mentioned only"}, (view, set(want) - set(got))
    assert all(p in PLACES for p in got.values())
    assert browse.head.row.height() == ROW_HEIGHT


def test_select_moves_to_the_tool_row_with_its_commands_and_back(browse):
    browse.set_view("tasks")
    browse.set_selecting(True)
    got = places(browse)
    assert [name_of(w) for w in tool_widgets(browse)][:3] == ["Select", "Select all shown", "Clear"]
    assert got["Select"] == "tool" and len([w for w in tool_widgets(browse) if isinstance(w, QPushButton)]) == 4
    browse.set_selecting(False)
    assert places(browse)["Select"] == "display"
    assert not tool_widgets(browse)


def tool_widgets(browse) -> list[QWidget]:
    lay = browse.head.tools_layout
    return [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]


def test_activity_with_a_range_and_select(browse):
    browse.act["win"], browse.act["select"] = "range", True
    browse.set_view("activity")
    got = places(browse)
    assert got["From"] == got["To"] == "tool" and got["Select"] == "tool" and got["Add to"] == "tool"
    assert got["Add to agenda"] == got["Clear ticks"] == "tool"
    assert [c.text() for c in browse.head.chips.buttons()] == ["Show: from and to…  ×"]


# ---- the panels ----
def test_a_panel_opens_under_its_button_and_stays_open_while_used(browse):
    browse.set_view("tasks")
    head = browse.head
    head.filter_button.click()
    QApplication.processEvents()
    assert head.filter_panel.isVisible()
    assert head.filter_panel.focusWidget() is not None and name_of(head.filter_panel.focusWidget()) == "Urgent only"
    parked = next(w for w in head.filter_panel.controls if name_of(w) == "Show parked")
    parked.setFocus()
    parked.click()  # the list is drawn again: the panel is refilled in place
    QApplication.processEvents()
    assert browse.tree_filter["parked"] and head.filter_panel.isVisible()
    now = next(w for w in head.filter_panel.controls if name_of(w) == "Show parked")
    assert now is not parked and now.isChecked() and head.filter_panel.focusWidget() is now  # the keyboard back on it
    assert head.filter_button.text() == "Filter · 1"


def test_tab_goes_through_a_panel_and_esc_goes_back_to_its_button(browse):
    browse.set_view("tasks")
    head = browse.head
    head.display_button.click()
    QApplication.processEvents()
    panel = head.display_panel
    seen = []
    for _ in range(len(panel.controls)):
        seen.append(name_of(QApplication.focusWidget() or panel.focusWidget()))
        panel.focusNextChild()
    assert set(seen) == {"Sort", "Group by", "Select"}
    panel.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not panel.isVisible()


def test_changing_the_view_closes_an_open_panel(browse):
    browse.set_view("tasks")
    browse.head.filter_button.click()
    QApplication.processEvents()
    assert browse.head.filter_panel.isVisible()
    browse.set_view("people")
    assert not browse.head.filter_panel.isVisible()


# ---- the chips ----
def test_a_tick_off_its_default_is_a_chip_whose_cross_puts_it_back(browse):
    browse.set_view("tasks")
    assert not browse.head.chips.isVisibleTo(browse) and browse.head.filter_button.text() == "Filter"
    browse._set_filter("parked", True)
    browse._set_filter("routine", False)
    chips = browse.head.chips.buttons()
    assert [c.text() for c in chips] == ["Parked shown  ×", "Routine hidden  ×"]
    assert browse.head.filter_button.text() == "Filter · 2"
    chips[1].click()
    assert browse.tree_filter["routine"] is True
    browse.head.chips.buttons()[0].click()
    assert browse.tree_filter["parked"] is False and not browse.head.chips.buttons()
    assert not browse.head.chips.isVisibleTo(browse)


def test_a_check_menu_with_a_pick_is_a_chip(browse):
    browse.set_view("tasks")
    browse._set_filter("people", ["P002"])
    chip = browse.head.chips.buttons()[0]
    assert chip.text().startswith("People: ") and chip.text().endswith("  ×")
    chip.click()
    assert browse.tree_filter["people"] == []


def test_activitys_show_is_a_chip_of_its_words(browse):
    browse.act["win"] = "last"
    browse.set_view("activity")
    chip = browse.head.chips.buttons()[0]
    assert chip.text() == "Show: last week  ×"
    chip.click()
    assert browse.act["win"] == "week" and not browse.head.chips.buttons()


def test_display_has_no_chips(browse):
    browse.sorts["tasks"] = "due"
    browse.set_view("tasks")
    assert not browse.head.chips.buttons() and browse.head.filter_button.text() == "Filter"


def test_mine_only_is_kept_as_before_and_is_a_chip(browse, ctx):
    browse.set_view("today")
    box = next(w for w in browse.head.filter_panel.controls if isinstance(w, QCheckBox) and w.text() == "Mine only")
    box.setChecked(True)
    assert db.get_state(ctx.conn, TODAY_MINE_KEY) == "1"  # the same key as before (release 5.184 changes no state)
    assert [c.text() for c in browse.head.chips.buttons()] == ["Mine only  ×"]
    browse.head.chips.buttons()[0].click()
    assert db.get_state(ctx.conn, TODAY_MINE_KEY) == "0"


def test_documents_task_picker_from_inside_the_panel(browse, monkeypatch):
    browse.set_view("docs")
    m = browse.model()
    task = next(iter(t for t in m.tasks.values() if not t.discarded))
    # The picker is a popup of its own: picking from it is the same callback, whatever this computer's popups do.
    monkeypatch.setattr(browse, "_pick_task", lambda anchor, done, none=None: done(task.id))
    browse.head.filter_button.click()
    picker = next(w for w in browse.head.filter_panel.controls if name_of(w) == "Task")
    picker.click()
    QApplication.processEvents()
    texts = [c.text() for c in browse.head.chips.buttons()]
    assert f"Task: {task.title}  ×" in texts
    assert {"Include subtasks", "Show all"} <= {name_of(w) for w in browse.head.filter_panel.controls}


# ---- the row: one height, the commands folding under More ----
def test_commands_fold_under_more_in_order_when_narrow(browse):
    browse.set_view("tagged")
    head = browse.head
    names = [b.text() for b in head.commands()]
    assert names == ["Import…", "Export…", "Add…", "Patterns…"]
    browse.split.setSizes([248, 900, 292])
    browse.resize(1440, 900)
    QApplication.processEvents()
    assert not head.folded() and not head.more_button.isVisibleTo(browse)
    head.resize(320, head.height())
    QApplication.processEvents()
    folded = [b.text() for b in head.folded()]
    assert folded and names[-len(folded):] == folded  # from the right
    assert head.more_button.isVisibleTo(browse)
    head._fill_more()
    actions = head.more_menu.actions()
    assert [a.text() for a in actions] == folded
    clicked = []
    head.folded()[-1].clicked.connect(lambda: clicked.append(True))
    actions[-1].trigger()
    assert clicked


def test_the_title_is_cut_last(browse):
    """As the row narrows the commands fold, the count is cut, and the title is cut only once the count has gone; nothing on
    the row overlaps."""
    browse.set_view("activity")
    head = browse.head
    natural = head.title.fontMetrics().horizontalAdvance("Activity") + 2
    cut_seen = False
    for width in range(900, 200, -20):
        head.resize(width, head.height())
        QApplication.processEvents()
        if head.title.maximumWidth() < natural:
            assert head.count.maximumWidth() == 0, width  # the title is cut only after the count
            cut_seen = True
        if head.count.maximumWidth() > 0:
            assert head.title.maximumWidth() >= natural, width
    assert cut_seen and not head.commands()[0].isVisibleTo(browse)


def test_the_commands_hold_the_pane_no_wider(browse):
    """The commands fold rather than hold the list pane wide: the row's least width is its fixed parts' alone (the title's
    first letters, Filter, Display, the folds and More), and the header asks for its whole row only as its natural size."""
    browse.set_view("tagged")
    head = browse.head
    least = head.row.minimumSizeHint().width()
    commands = sum(b.sizeHint().width() for b in head.commands())
    assert least == head._row_least() and least + commands <= head._row_natural() + head.more_button.sizeHint().width() + 8
    assert head.sizeHint().width() >= least


def test_file_search_chips_still_draw_through_show_chips(qapp):
    seen = []
    chips = FilterChips(lambda: seen.append("changed"))
    chips.show_chips([("Type: Word", lambda: seen.append("undo"))])
    assert [b.text() for b in chips.buttons()] == ["Type: Word  ×"] and chips.isVisibleTo(chips)
    chips.buttons()[0].click()
    assert seen == ["undo", "changed"]


def test_the_old_names_still_reach_the_header(browse):
    assert browse.filters is browse.head and browse.filters_layout is browse.head.tools_layout
    assert browse.pane_title is browse.head.title and browse.pane_count is browse.head.count and browse.pane_note is browse.head.note
    browse.set_view("tasks")
    assert browse.pane_title.text() == "Task tree" and browse.pane_count.text().endswith("open")
