"""The consolidation plan's releases 5.97 to 5.100 (the design workspace's ``docs/mods/consolidation-plan.md``, decisions
386 to 397), driven offscreen over the sample data: the Urgent view gone into the task tree's filter, Find files, one Edit
and one Add to, the two ways to a quick task, and dates edited in Quick edit and Edit task's More options."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton  # noqa: E402

from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE, LINE_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.revealed = []
    w.reveal = lambda path: w.revealed.append(path) or True
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    for view in list(w.task_views.values()):
        view.deleteLater()
    capture.deleteLater()
    w.deleteLater()


def task_rows(w) -> list[str]:
    return [k[1] for k in w.tree.keys() if k and k[0] == "task"]


def row(w, task_id: str):
    return next(i for i in w.tree.items() if i.data(0, KEY_ROLE) == ("task", task_id))


def check_box(w, label: str) -> QCheckBox:
    """The filter row's tick box: the newest, as the row is built again with each drawing."""
    return [b for b in w.filters.findChildren(QCheckBox) if b.text() == label][-1]


# ================= release 5.97: the Urgent view retired (decisions 386 and 387) =================
def test_the_sidebar_has_no_urgent_view(browse):
    assert "urgent" not in browse.nav.rows and "due" in browse.nav.rows


def test_the_urgent_views_name_leads_to_the_task_tree_urgent_only(browse):
    browse.set_view("urgent")
    assert browse.view == "tasks" and browse.tree_filter["urgent"]
    box = check_box(browse, "Urgent only")
    assert box.isChecked()
    m = Model(browse.conn)
    matched = [t for t in task_rows(browse) if m.task(t).urgent]
    assert matched == ["T000019"]  # what the Urgent view listed, with its parents dimmed around it
    assert browse.tree.is_shown(row(browse, "T000019"))  # its branch open down to it
    box.setChecked(False)
    assert not browse.tree_filter["urgent"] and "T000010" in task_rows(browse)


def test_a_wheel_or_a_link_naming_the_urgent_view_still_works(browse):
    """An old slot, "browse.view" with "view": "urgent", is allowed and goes to the filtered tree."""
    from docrepo import wheels_config as wc
    from docrepo.ui.wheel_commands import SPECS, icon_names

    data = {"wheels": [{"id": "w", "name": "W", "slots": {"N": {"label": "Urgent", "command": "browse.view", "args": {"view": "urgent"}}}}]}
    slot = wc.check(data, SPECS, icon_names()).wheels[0].slots["N"]
    assert slot.args == {"view": "urgent"}
    browse.set_view("today")
    browse.show_browse("urgent")
    assert browse.view == "tasks" and browse.tree_filter["urgent"]


def test_the_palette_still_finds_urgent(browse):
    from docrepo.ui.palette import rank

    commands = browse.palette_commands()
    assert not any(c.name == "Urgent" for c in commands)
    best = rank("urgent", commands)[0]
    best.run()
    assert browse.view == "tasks" and browse.tree_filter["urgent"]


def test_todays_due_shows_urgent_tasks_first_with_their_chip(browse, ctx):
    ctx.conn.execute("UPDATE tasks SET urgent = 1 WHERE id = 'T000012'")
    ctx.conn.execute("UPDATE tasks SET urgent = 0 WHERE id = 'T000019'")
    ctx.conn.execute("UPDATE tasks SET reminder = NULL WHERE id = 'T000019'")  # its reminder would keep it off the list (decision 418)
    browse.refresh()
    browse.set_view("today")
    head = next(i for i in browse.tree.items() if "Due in the next 7 days" in str(i.data(0, HTML_ROLE)))
    due = [head.child(n).data(0, KEY_ROLE)[1] for n in range(head.childCount()) if head.child(n).data(0, KEY_ROLE)]
    assert due == ["T000012", "T000019"]
    assert row(browse, "T000012").data(0, LINE_ROLE).chips == (("Urgent", "urgent"),)
    assert row(browse, "T000019").data(0, LINE_ROLE).chips == ()


# ================= release 5.98: Find files, and one Edit and one Add to (decisions 389 to 392) =================
def menu_words(menu) -> list[str]:
    return ["—" if a.isSeparator() else a.text().split("\t")[0].split("   ")[0] for a in menu.actions()]


def bar(browse) -> dict:
    """The bar's buttons by their words or accessible name, a split button's two among them."""
    lay = browse.actions_layout
    out = {}
    for w in (lay.itemAt(i).widget() for i in range(lay.count())):
        for b in [w] if isinstance(w, QPushButton) else (w.findChildren(QPushButton) if w is not None else []):
            out[b.text() or b.accessibleName()] = b
    return out


def test_the_task_pages_bar_has_add_to_and_edit_from_the_shared_lists(browse):
    from docrepo import task_commands

    browse.select("task", "T000008")
    buttons = bar(browse)
    assert "Task view" not in buttons and "Find files" not in buttons  # Find files is the Files group's (decision 389)
    m = Model(browse.conn)
    expected_edit = ["—" if e.separator else e.label for e in task_commands.edit_entries(m, "T000008")]
    expected_add = ["—" if e.separator else e.label.split("   ")[0] for e in task_commands.add_to_entries(m, "T000008", NOW.date())]
    assert buttons["Edit"].menu() is None and menu_words(buttons["More ways to edit"].menu()) == expected_edit  # a split button
    edited = []
    browse.edit_task = edited.append
    buttons["Edit"].click()
    assert edited == ["T000008"]  # its words are Edit task
    assert menu_words(buttons["Add to"].menu()) == expected_add


def test_a_task_rows_menu_has_add_to_and_edit_then_state(browse):
    browse.set_view("tasks")
    menu = browse.tree.row_menu(row(browse, "T000008"))
    subs = [a.menu().title() for a in menu.actions() if a.menu() is not None]
    assert subs == ["Add to", "Edit", "State"]
    edit = next(a.menu() for a in menu.actions() if a.menu() is not None and a.menu().title() == "Edit")
    assert menu_words(edit)[0] == "Edit task…"
    menu.deleteLater()


def test_a_today_rows_own_edit_is_left_to_the_edit_menu(browse):
    browse.add_to_today("T000008")
    browse.set_view("today")
    menu = browse.tree.row_menu(row(browse, "T000008"))
    plain = [a.text() for a in menu.actions() if a.menu() is None and not a.isSeparator()]
    assert "Edit" not in plain and "Done" in plain and "Note" in plain
    assert [a.menu().title() for a in menu.actions() if a.menu() is not None][:2] == ["Add to", "Edit"]
    menu.deleteLater()


def test_the_files_group_opens_find_files(browse):
    from PySide6.QtCore import QUrl

    browse.select("task", "T000008")
    parts = browse.pages().task_parts("T000008", browse.state, 600)
    assert 'href="taskview:T000008"' in parts["files_summary"] and "Find files" in parts["files_summary"]
    browse.on_link(QUrl("taskview:T000008"))
    view = browse.task_views["T000008"]
    assert view.windowTitle() == "Find files: Installation"


def test_find_files_has_one_task_page_button_and_no_task_letters(browse):
    from PySide6.QtGui import QShortcut

    browse.open_task_view("T000008")
    view = browse.task_views["T000008"]
    lay = view.commands
    words = [lay.itemAt(i).widget().text() for i in range(lay.count()) if lay.itemAt(i).widget()]
    assert words == ["Task page"]
    keys = {s.key().toString() for s in view.findChildren(QShortcut)}
    assert not keys & {"N", "U", "T", "A", "D", "E", "M", "Alt+N", "Alt+E"} and {"P", "Ctrl+O", "Ctrl+W"} <= keys
    opened = []
    browse.open_capture = lambda **kw: opened.append(kw)
    view.task_page_button.click()
    assert browse.sel == ("task", "T000008") and opened == []


def test_find_files_task_rows_have_add_to_and_edit(browse):
    browse.open_task_view("T000001")
    view = browse.task_views["T000001"]
    view.set_kind("task")
    i = next(n for n, r in enumerate(view.list.rows) if r.record is not None and r.record.kind == "task")
    shown = []
    browse.run_menu = lambda menu, at: shown.append([a.menu().title() for a in menu.actions() if a.menu() is not None])
    view._row_menu(i, None)
    assert shown == [["Add to", "Edit", "State"]]


# ================= release 5.99: the two ways to a quick task (decisions 393 and 394) =================
def test_a_quick_tasks_row_menu_has_put_under_and_it_files_the_task(browse, ctx):
    from docrepo import quick
    from docrepo.save import add_quick_task

    r = add_quick_task(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, "Call the vendor about seals", NOW)
    browse.refresh()
    browse.set_view("today")
    menu = browse.tree.row_menu(row(browse, r.created_task))
    put = next(a for a in menu.actions() if a.text().startswith("Put under…"))
    assert [a.menu().title() for a in menu.actions() if a.menu() is not None][:2] == ["Add to", "Edit"]
    browse._pick_task = lambda anchor, picked, none, keep=None: picked("T000008")
    put.trigger()
    m = Model(ctx.conn)
    assert m.parents_of(r.created_task) == ["T000008"] and quick.parent_id(ctx.conn) not in m.parents_of(r.created_task)
    assert [a.subject for a in m.today_items()] == [r.created_task]  # still on Today
    menu.deleteLater()
    again = browse.tree.row_menu(row(browse, r.created_task))
    assert not any(a.text().startswith("Put under…") for a in again.actions())  # filed: no longer a quick task
    again.deleteLater()


def test_move_and_put_under_leave_out_the_task_and_whats_under_it(browse):
    """Release 5.98 with 5.103's ``keep`` (the owner's yes of 2026-11-07): a task can't go under itself or its own subtasks,
    so the picker doesn't offer them."""
    m = Model(browse.conn)
    under = m.descendants_of("T000008")
    assert under  # Installation has subtasks in the sample
    browse.go_task("T000008")
    browse._pick_parent("T000008", "T000001")
    picker = browse._picker
    assert not picker._kept("T000008") and not any(picker._kept(t) for t in under)
    assert picker._kept("T000001") and picker._kept("T000002")
    picker.hide()


def test_d_on_a_row_is_add_to_today_not_a_quick_task(browse, ctx):
    browse.set_view("tasks")
    browse.select("task", "T000008")
    browse.capture_for_selected("today")  # what D runs (its key is ignored while a box elsewhere has the keyboard)
    m = Model(ctx.conn)
    assert [a.subject for a in m.today_items()] == ["T000008"] and m.parents_of("T000008") == ["T000001"]


# ================= release 5.100: where dates are edited (decisions 395 and 396) =================
def test_edit_tasks_duration_and_ties_are_under_more_options(browse, ctx):
    from docrepo.ui.task_forms import WHEN_HINT, TaskEditDialog

    plain = TaskEditDialog(browse, browse.model(), "T000001", browse._label_options, browse._people_options)
    for w in (plain.duration_field, plain.calendar, plain.tie_panel, *plain.tie_buttons.values(), plain.key_dates):
        assert plain.more.isAncestorOf(w)
    assert not plain.more.isAncestorOf(plain.start) and not plain.more.isAncestorOf(plain.due) and not plain.more.isAncestorOf(plain.deadline)
    assert plain.when_hint.text() == WHEN_HINT and "Quick edit" in WHEN_HINT and not plain.when_hint.isHidden()
    assert [b.text() for b in plain.tie_buttons.values()] == ["Tie Start…", "Tie Due…"]
    plain.deleteLater()
    ctx.conn.execute("UPDATE tasks SET duration = 5 WHERE id = 'T000001'")
    browse.refresh()
    with_duration = TaskEditDialog(browse, browse.model(), "T000001", browse._label_options, browse._people_options)
    assert not with_duration.more.isHidden()  # it opens by itself when one of its fields is set
    with_duration.deleteLater()


def test_quick_edits_more_options_opens_edit_task_there(browse, ctx):
    shown = []
    browse.run_dialog = lambda dialog: shown.append(not dialog.more.isHidden()) or False
    browse.quick_edit("T000001", browse.geometry())
    qe = browse.quick_window
    assert qe.more_button.text() == "More options…" and not hasattr(qe, "duration")
    qe.more_options()
    assert shown == [True] and not qe.isVisible()


def test_the_capture_windows_key_dates_sit_inside_more_fields_with_no_fold(browse):
    from PySide6.QtWidgets import QLabel

    capture = browse.capture
    for editor, more in ((capture.n_keydates, capture.n_more), (capture.u_keydates, capture.u_more)):
        assert more.isAncestorOf(editor) and isinstance(editor.toggle, QLabel) and not editor.body.isHidden()
    capture.show_capture(mode="new_task")
    assert capture.n_more.isHidden()  # behind More fields, as Edit task's are behind More options


def test_the_rule_against_new_date_kinds_is_in_claude_md():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "CLAUDE.md").read_text(encoding="utf-8")
    assert "No new date kind without a decision that retires one" in text and "decision 396" in text


# ================= release 5.118: Undo after a move (the design workspace's undo-moves plan, decisions 435 to 439) =================
def edit_entry(menu, label: str):
    """The Edit submenu of a row's menu, and its entry that starts with ``label``."""
    edit = next(a.menu() for a in menu.actions() if a.menu() is not None and a.menu().title() == "Edit")
    return next(a for a in edit.actions() if a.text().startswith(label))


def test_remove_from_under_on_a_rows_menu_says_so_with_undo_which_puts_it_back(browse):
    browse.set_view("tasks")
    siblings = Model(browse.conn).children_of("T000001")
    menu = browse.tree.row_menu(row(browse, "T000008"))
    edit_entry(menu, "Remove from under…").trigger()
    assert Model(browse.conn).parents_of("T000008") == []
    assert browse.status.text().startswith("Installation is a top-level task now.") and 'href="undo"' in browse.status.text()
    browse._status_link("undo")
    m = Model(browse.conn)
    assert m.parents_of("T000008") == ["T000001"] and m.children_of("T000001") == siblings  # second of four again
    assert browse.status.text() == "Set back: Installation is under Reactor impeller upgrade again. The status log keeps both changes."
    assert [(e.from_value, e.to_value) for e in m.status_log_of("T000008") if getattr(e, "field", None) == "Parents"] == [
        ("Reactor impeller upgrade", None), (None, "Reactor impeller upgrade")]
    menu.deleteLater()


def test_move_on_the_task_pages_edit_menu_has_undo_until_the_next_message(browse):
    browse.select("task", "T000008")
    move = next(a for a in bar(browse)["More ways to edit"].menu().actions() if a.text().startswith("Move…"))
    browse._pick_task = lambda anchor, picked, none, keep=None: picked("T000002")
    move.trigger()
    assert browse.status.text().startswith("Installation moved from under Reactor impeller upgrade to Verification walkthrough readiness.")
    assert 'href="undo"' in browse.status.text()
    browse.say("Something else.")  # a new line: the Undo was for the last one (decision 363's)
    browse._status_link("undo")
    assert Model(browse.conn).parents_of("T000008") == ["T000002"]


def find_files_move(browse, task_id: str, label: str, to: str | None):
    """Find files on Reactor impeller upgrade, ``label`` picked on ``task_id``'s row's Edit menu, ``to`` picked."""
    browse.open_task_view("T000001")
    view = browse.task_views["T000001"]
    view.set_kind("task")
    i = next(n for n, r in enumerate(view.list.rows) if r.record is not None and r.record.kind == "task" and r.record.id == task_id)
    menus = []
    browse.run_menu = lambda menu, at: menus.append(menu)
    view._row_menu(i, None)
    browse._pick_task = lambda anchor, picked, none, keep=None: picked(to)
    edit_entry(menus[0], label).trigger()
    return view


def test_a_move_from_find_files_says_so_in_its_footer_with_undo(browse):
    view = find_files_move(browse, "T000012", "Move…", "T000002")
    assert view.foot.text() == "Rigging plan moved from under Installation to Verification walkthrough readiness."
    assert view.foot_undo.isVisibleTo(view) and "where it was" in view.foot_undo.toolTip()
    assert 'href="undo"' in browse.status.text()  # the browse tool's status line says it too
    view.foot_undo.click()
    assert Model(browse.conn).parents_of("T000012") == ["T000008"]
    assert view.foot.text().startswith("Set back: Rigging plan is under Installation again.") and not view.foot_undo.isVisibleTo(view)
    assert 'href="undo"' not in browse.status.text()  # once, from either place
    view.foot_undo.offer(lambda: None)
    assert view.foot_undo.toolTip().startswith("Set the state back")  # a state pick's own tip, as before


def test_undo_from_find_files_after_another_move_says_why_and_changes_nothing(browse):
    view = find_files_move(browse, "T000012", "Move…", "T000002")
    undo = view.foot_undo._undo
    browse.move_task("T000012", "T000002", "T000003")  # moved again, from the browse tool
    undo()
    assert Model(browse.conn).parents_of("T000012") == ["T000003"] and "changed since" in view.foot.text()
