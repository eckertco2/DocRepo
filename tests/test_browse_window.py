"""The browse tool, driven offscreen (no window appears) over the sample data, with the real capture window."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton  # noqa: E402

from docrepo import captures, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


def shown(browse) -> str:
    """What the detail pane shows, in words: a task's page is three parts since the notes page (release 5.25)."""
    return browse.task_pane.text() if browse.detail_stack.currentIndex() == 2 else browse.page.toPlainText()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    changed: list[list[str]] = []
    context = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW, settings_changed=changed.append)
    context.changed = changed  # type: ignore[attr-defined]
    return context


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.revealed = []
    w.reveal = lambda path: w.revealed.append(path) or True
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


def rows(w) -> list:
    return w.tree.keys()


def test_it_opens_on_the_task_tree(browse):
    assert browse.view == "tasks" and browse.sel == ("task", "T000001")
    assert ("task", "T000001") in rows(browse) and ("task", "T000010") in rows(browse)
    assert "unfiled" in browse.nav.rows and "settings" in browse.nav.rows
    assert "Reactor impeller upgrade" in shown(browse)


def test_the_views_pane_hides_and_stays_hidden(browse, ctx):
    """Mods log round 1 (M0012): Ctrl+B or ≡ Views, remembered in docs.db's app_state."""
    from docrepo import db

    assert browse.nav.isVisible() and browse.views_button.isChecked()
    browse.views_button.click()
    assert not browse.nav.isVisible() and db.get_state(ctx.conn, "browse_views_hidden") == "1"
    again = BrowseWindow(ctx, None)
    try:
        again.show_browse()
        assert not again.nav.isVisible() and not again.views_button.isChecked()
        again.show_views_pane(True)
        assert again.nav.isVisible() and db.get_state(ctx.conn, "browse_views_hidden") == "0"
    finally:
        again.deleteLater()


def test_filter_by_several_people_and_sort(browse):
    """Mods log round 1 (M0018, M0015)."""
    from PySide6.QtWidgets import QComboBox

    from docrepo.ui.widgets import CheckMenuButton

    people = next(w for w in browse.filters.findChildren(CheckMenuButton) if w.noun == "People")
    assert people.text() == "People: anyone"
    for action in people.choices:
        if action.data() in ("P003", "P004"):
            action.trigger()  # ticking doesn't redraw the list; closing the menu does
    assert people.text() == "People: Tom Becker, Mike Ortiz" and browse.tree_filter["people"] == []
    people.picks.aboutToHide.emit()
    QApplication.processEvents()
    assert browse.tree_filter["people"] == ["P003", "P004"]
    shown = browse.filters.findChildren(CheckMenuButton)
    assert any(w.text() == "People: Tom Becker, Mike Ortiz" for w in shown)  # drawn again, still ticked
    sort = next(w for w in browse.filters.findChildren(QComboBox) if w.accessibleName() == "Sort")
    sort.setCurrentIndex(sort.findData("title"))
    assert browse.sorts == {"tasks": "title"}
    browse.set_view("due")
    due_sort = next(w for w in browse.filters.findChildren(QComboBox) if w.accessibleName() == "Sort")
    assert due_sort.currentText() == "Sort: soonest first"  # each view keeps its own order


def test_g_puts_the_selected_task_on_an_agenda(browse, monkeypatch):
    opened = []
    monkeypatch.setattr(browse, "open_capture", lambda **options: opened.append(options))
    browse.capture_for_selected("agenda")
    assert opened == [{"task": "T000001", "mode": "update", "agenda_focus": True}]


def test_each_view_selects_its_first_item(browse):
    expected = {"unfiled": ("capture", "C000023"), "due": ("task", "T000019"), "reminders": ("task", "T000016"), "people": ("person", "P001"),
                "labels": ("label", "Line 1"), "docs": ("doc", "D000001"), "agenda": ("task", "T000010")}
    for view, sel in expected.items():
        browse.set_view(view)
        assert browse.sel == sel, view
        if view != "agenda":  # the agenda's own meeting isn't one of its rows
            assert browse.tree.currentItem().data(0, KEY_ROLE) == sel
    browse.set_view("capacity")
    assert not browse.detail.isVisible() and browse.cap_table.rowCount() == 6
    browse.set_view("settings")
    assert browse.middle.currentIndex() == 2 and browse.settings_view.hotkey.text() == "Ctrl+Shift+Space"


def test_opening_a_hidden_task_turns_its_filter_on(browse):
    assert ("task", "T000005") not in rows(browse)  # closed
    browse.go_task("T000005")
    assert browse.tree_filter["closed"] and ("task", "T000005") in rows(browse) and browse.sel == ("task", "T000005")
    browse.go_task("T000004")
    assert browse.tree_filter["parked"]


def test_links_change_the_tab_scope_and_chapters(browse):
    browse.go_task("T000008")
    browse.on_link(QUrl("tab:log"))
    browse.on_link(QUrl("scope:family"))
    browse.on_link(QUrl("chap:T000012"))
    assert (browse.state.tab, browse.state.scope, browse.state.chapters) == ("log", "family", {"T000012"})
    assert "Work started" in shown(browse)
    browse.go_task("T000009")  # another task: the scope goes back to With subtasks, the chapters close, the tab stays
    assert (browse.state.tab, browse.state.scope, browse.state.chapters) == ("log", "descendants", set())
    browse.on_link(QUrl("person:P003"))
    assert browse.sel == ("person", "P003")
    browse.on_link(QUrl("label:Line%201"))
    assert browse.sel == ("label", "Line 1")


def test_a_n_and_u_open_the_capture_window_on_the_selected_task(browse):
    browse.go_task("T000008")
    for mode in ("note", "new_task", "update"):
        browse.task_pane.top.setFocus()
        browse._key(mode)
        assert browse.capture.isVisible() and browse.capture.task == "T000008" and browse.capture.types == {mode}
        browse.capture.hide()
    browse.set_view("people")
    browse.capture_for_selected("update")
    assert "Select a task first" in browse.status.text()


def test_a_saved_capture_shows_in_the_browse_tool(browse):
    browse.go_task("T000008")
    browse.capture_for_selected("new_task")
    browse.capture.title.setText("Order shims for the alignment")
    browse.capture.save()
    new = Model(browse.conn).tasks["T000020"]
    assert new.title == "Order shims for the alignment"
    assert browse.sel == ("task", "T000020") and browse.pin == "T000020" and browse.state.tab == "notes"
    assert ("task", "T000020") in rows(browse) and "Created T000020" in browse.status.text()


def test_filing_an_unfiled_capture(browse):
    browse.set_view("unfiled")
    browse.select("capture", "C000022")
    labels = [b.text() for b in browse.actions.findChildren(QPushButton)]
    assert "File to task" in labels and "Make it a task" in labels
    browse._set_file_to("C000022", "T000018")
    browse.file_capture("C000022")
    assert Model(browse.conn).captures["C000022"].filed_to == "T000018"
    assert ("capture", "C000022") not in rows(browse) and browse.sel == ("capture", "C000022")
    assert browse.status.text() == "Filed C000022 to Update area 3 guard drawings."


def test_make_it_a_task(browse):
    browse.set_view("unfiled")
    browse.select("capture", "C000022")
    browse.open_capture(from_capture="C000022")
    cw = browse.capture
    assert cw.from_capture == "C000022" and cw.types == {"new_task"} and "files C000022 to it" in cw.does.text()
    cw.save()
    m = Model(browse.conn)
    assert m.captures["C000022"].filed_to == "T000020" and m.task("T000020").created_by == "C000022"
    assert browse.sel == ("task", "T000020")


def test_fixing_a_capture(browse, ctx):
    """Release 5.25 (decision 112): Edit fixes the title and summary; the text stays as it arrived, read-only."""
    before = captures.capture_md_path(ctx.data_root, Model(browse.conn).captures["C000017"]).read_text(encoding="utf-8")
    browse.go_capture("C000017")
    browse.start_capture_edit("C000017")
    assert browse.detail_stack.currentIndex() == 1 and browse.edit_content.isReadOnly()
    assert browse.edit_content.value()[0] == "Vendor drawings came in late, so the package is now due Oct 23."
    browse.edit_capture_title.setText("Drawings late")
    browse.save_capture_edit()
    assert browse.detail_stack.currentIndex() == 0 and browse.status.text().startswith("Saved C000017.")
    c = Model(browse.conn).captures["C000017"]
    assert c.title == "Drawings late" and captures.capture_md_path(ctx.data_root, c).read_text(encoding="utf-8") == before


def test_clearing_a_reminder_from_the_list(browse):
    browse.set_view("reminders")
    item = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", "T000018"))
    button = browse.tree.itemWidget(item, 3)
    assert button.text() == "Clear"
    button.click()
    assert Model(browse.conn).task("T000018").reminder is None
    assert ("task", "T000018") not in rows(browse)


def _title_cell(browse, task_id: str) -> str:
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", task_id)).data(0, HTML_ROLE)


def test_the_task_tree_s_rows_name_their_own_labels(browse):
    """Item 76 (decision 235): quiet words after the title, not chips, on the task tree only."""
    browse.set_view("tasks")
    browse.open.update(Model(browse.conn).tasks)
    browse.render_list()
    assert 'class="sub">&nbsp;Line 1 · Strategic Plan</span>' in _title_cell(browse, "T000001")
    assert "Safety</span>" in _title_cell(browse, "T000019") and "Urgent" in _title_cell(browse, "T000019")  # after its chips
    assert "Line 1" not in _title_cell(browse, "T000012")  # a subtask doesn't repeat what it inherits
    assert 'class="sub"' not in _title_cell(browse, "T000016")  # no labels, nothing added
    browse.set_view("due")
    assert "Safety" not in _title_cell(browse, "T000019")  # the other lists are as they were


def test_a_dimmed_parent_and_a_label_s_own_section_leave_the_words_off(browse):
    browse.set_view("tasks")
    browse._set_filter("labels", ["Safety"])
    assert "Line 1" not in _title_cell(browse, "T000001")  # there for context, as the row of a parent that doesn't match
    assert "Safety</span>" in _title_cell(browse, "T000019")
    browse._set_filter("labels", [])
    browse._set_tree_group("label")
    assert "Line 1" not in _title_cell(browse, "T000001") and "Strategic Plan</span>" in _title_cell(browse, "T000001")  # first under Line 1
    browse._set_tree_group("group")
    assert "Line 1 · Strategic Plan</span>" in _title_cell(browse, "T000001")


def _today_heading(browse, name: str):
    return next((i for i in browse.tree.items() if i.data(0, KEY_ROLE) is None and f"<b>{name}</b>" in (i.data(0, HTML_ROLE) or "")), None)


def test_reminders_whose_day_has_come_are_on_today(browse):
    """Item 77 (decisions 236 to 238): under their own heading, oldest first, with Add to Today and Clear. Tomorrow's stays
    on the Reminders list until its day."""
    browse.set_view("today")
    head = _today_heading(browse, "Reminders")
    rows_under = [head.child(i) for i in range(head.childCount())]
    assert [r.data(0, KEY_ROLE) for r in rows_under] == [("task", "T000016"), ("task", "T000018")]  # not T000019, tomorrow's
    assert "1 d ago" in rows_under[0].data(2, HTML_ROLE) and "Today" in rows_under[1].data(2, HTML_ROLE) and "Reminder" in rows_under[0].data(1, HTML_ROLE)
    links = [b.text() for b in browse.tree.itemWidget(rows_under[1], 3).findChildren(QPushButton)]
    assert links == ["Add to Today", "Clear"]
    today_rows = browse.tree.keys()
    assert today_rows.index(("task", "T000018")) < today_rows.index(("task", "T000012"))  # above what's due in the next 7 days


def test_a_reminder_on_today_can_be_added_and_cleared(browse):
    browse.set_view("today")
    head = _today_heading(browse, "Reminders")
    buttons = {b.text(): b for b in browse.tree.itemWidget(head.child(1), 3).findChildren(QPushButton)}
    buttons["Add to Today"].click()
    m = Model(browse.conn)
    assert [a.subject for a in m.today_items()] == ["T000018"] and m.task("T000018").reminder == "2026-10-08"  # on Today, reminder kept
    head = _today_heading(browse, "Reminders")
    row = next(head.child(i) for i in range(head.childCount()) if head.child(i).data(0, KEY_ROLE) == ("task", "T000018"))
    buttons = {b.text(): b for b in browse.tree.itemWidget(row, 3).findChildren(QPushButton)}
    assert list(buttons) == ["Clear"]  # already on Today
    buttons["Clear"].click()
    m = Model(browse.conn)
    assert m.task("T000018").reminder is None and [e.via for e in m.status_log_of("T000018") if e.field == "Reminder"][-1] == "Today"
    browse.clear_reminder("T000016", "Today")
    assert _today_heading(browse, "Reminders") is None  # the heading goes with its last reminder


def test_discussed_closes_the_item_and_opens_an_update(browse):
    browse.set_view("agenda")
    item = next(a for a in Model(browse.conn).open_items_for("T000010") if a.subject == "T000001")
    browse.close_agenda_item(item.id, "Discussed")
    cw = browse.capture
    assert cw.isVisible() and cw.task == "T000001" and cw.types == {"update"}
    assert cw.content.toPlainText() == "Discussed at Business team meeting: "
    assert ("task", "T000001") not in [k for k in rows(browse)[:4]]
    assert Model(browse.conn).status_log_of("T000001")[-1].to_value == "Discussed"


def test_copy_as_markdown_and_copy_prompt(browse):
    browse.copy_agenda("T000010")
    assert QGuiApplication.clipboard().text().startswith("## Business team meeting, Tue 13 Oct")
    browse.go_task("T000009")
    browse.summary_type.setCurrentText("General summary")
    browse.copy_prompt("T000009")
    text = QGuiApplication.clipboard().text()
    assert text.startswith(prompts.PREAMBLE) and "Vendor drawings came in late, so the package is now due Oct 23." in text
    assert browse.status.text().startswith("Prompt copied (")


def test_search(browse):
    browse.search_box.setText("crane booking")
    browse._run_search()
    assert browse.view == "search" and rows(browse) == [None, ("capture", "C000013")]
    browse.search_box.clear()
    browse._run_search()
    assert browse.view == "tasks"


def test_show_in_file_explorer(browse, ctx):
    browse.reveal_key(("task", "T000008"))
    browse.go_task("T000001")
    copy = next(f for f in Model(browse.conn).copies if f.task == "T000001")
    browse.on_link(QUrl(f"show:copy:{copy.id}"))
    assert browse.revealed == [ctx.data_root / "Tasks" / "T000008", ctx.data_root / "Tasks" / "T000001" / "Files" / copy.name]


def test_people_and_labels(browse, ctx):
    browse.set_view("people")
    browse.save_person(None, "Dana Kim", ["Dana", "DK"], 36)
    dana = next(p for p in Model(browse.conn).people.values() if p.name == "Dana Kim")
    assert browse.sel == ("person", dana.id) and dana.aliases == ["Dana", "DK"] and dana.hours == 36
    browse.set_person_status(dana.id, "retired")
    assert ("person", dana.id) not in rows(browse)
    browse.set_person_status("P001", "retired")
    assert "can't retire yourself" in browse.status.text()
    browse.set_view("labels")
    browse.save_label("Safety", "Site safety", ["safety", "guard"])
    m = Model(browse.conn)
    assert any(name == "Site safety" for name, _ in m.labels_of("T000002")) and browse.sel == ("label", "Site safety")
    assert "Site safety" in (ctx.data_root / "Tasks" / "T000002" / "Task.md").read_text(encoding="utf-8")


def test_task_edits(browse, monkeypatch):
    """The Edit task form (mods log round 1, M0008, M0011), and moves in the tree."""
    from docrepo.ui.task_forms import TaskEditDialog
    from docrepo.ui.widgets import Chip

    browse.go_task("T000012")
    edit_menu = next(b for b in browse.actions.findChildren(QPushButton) if b.text() == "Edit").menu()
    assert edit_menu.actions()[0].text() == "Edit task…	E"  # its key in the menu's key column (the visual overhaul's O2)
    dialog = TaskEditDialog(browse, browse.model(), "T000012", browse._label_options, browse._people_options)
    assert (dialog.title.text(), dialog.state.currentText(), dialog.assignees.values(), dialog.start.value()) == (
        "Rigging plan", "In progress", ["P004"], "2026-10-05")
    assert not dialog.repeat_field.isVisibleTo(dialog)
    dialog.title.setText("Rigging plan for the lift")
    dialog.description.setPlainText("Mike writes the rigging plan.")
    dialog.labels.add(Chip("Safety", "Safety"))
    dialog.labels.add(Chip("Lifting", "Lifting", new=True))
    dialog.inherit.setChecked(False)
    dialog.leads.add(Chip("P003", "Tom Becker"))
    dialog.due.set_value("2026-10-16")
    dialog.lead_hours.setText("lots")
    assert dialog.problem() == "Lead hours isn't a number of hours."
    dialog.lead_hours.setText("4")
    assert dialog.problem() is None
    opened = []
    browse.run_dialog = lambda d: opened.append(d.windowTitle()) or True
    typed = dialog.values()
    monkeypatch.setattr(TaskEditDialog, "values", lambda self: typed)
    browse.task_pane.top.setFocus()
    browse._key("edit")  # E opens the form on the selected task
    m = Model(browse.conn)
    t = m.task("T000012")
    assert opened == ["Edit task T000012"]
    assert (t.title, t.description, t.labels, t.inherit_labels, t.leads, t.lead_hours, t.due) == (
        "Rigging plan for the lift", "Mike writes the rigging plan.", ["Safety", "Lifting"], False, ["P003"], 4.0, "2026-10-16")
    assert any(lb.name == "Lifting" for lb in m.labels) and browse.status.text() == "7 changes in the status log."
    browse.move_task("T000012", "T000008", "T000001")
    assert Model(browse.conn).parents_of("T000012") == ["T000001"]
    browse.move_task("T000001", None, "T000012")
    assert "under itself" in browse.status.text()


def test_select_and_edit_selected(browse):
    """Mods log round 1 (M0009): Select puts a tick box on each task row; Edit selected changes the ticked ones after a preview."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QCheckBox

    def checkable():
        return [i for i in browse.tree.items() if i.data(0, Qt.ItemDataRole.CheckStateRole) is not None]

    assert not checkable()
    next(w for w in browse.filters.findChildren(QCheckBox) if w.text() == "Select").setChecked(True)
    assert browse.selecting and len(checkable()) == len([k for k in rows(browse) if k and k[0] == "task"])
    for item in checkable():
        if item.data(0, KEY_ROLE) in (("task", "T000016"), ("task", "T000017")):
            item.setCheckState(0, Qt.CheckState.Checked)  # as a click does
    assert browse.ticked == {"T000016", "T000017"} and browse.edit_selected_button.text() == "Edit selected (2)…"
    previews = []

    def run(dialog):
        dialog.state.setCurrentText("Parked")
        dialog.dates["reminder"][0].setChecked(True)
        dialog.dates["reminder"][1].set_value("2026-10-1")
        dialog.refresh_preview()
        assert "Reminder isn't a date" in dialog.preview.toPlainText() and not dialog.apply_button.isEnabled()
        dialog.dates["reminder"][1].set_value("2026-10-12")
        dialog.refresh_preview()
        previews.append(dialog.preview.toPlainText())
        return True

    browse.run_dialog = run
    browse.edit_selected_button.click()
    assert previews[0].startswith("2 tasks change, 4 changes in their status logs.") and "State: Not started → Parked" in previews[0]
    m = Model(browse.conn)
    assert [(m.task(x).state, m.task(x).reminder) for x in ("T000016", "T000017")] == [("Parked", "2026-10-12")] * 2
    assert browse.status.text() == "Changed 2 tasks: 4 changes in their status logs."
    browse.tick_shown(False)
    browse.tick_shown(True)  # the task tree opens collapsed: only the rows you can see
    assert "T000001" in browse.ticked and "T000012" not in browse.ticked
    browse.set_view("due")
    assert browse.selecting and not browse.ticked and checkable()


def test_a_new_labels_matching_tasks(browse):
    """Mods log round 1 (M0014): saving a label with new keywords lists the open tasks that mention them."""
    shown = []

    def run(dialog):
        keys = dialog.rows.keys()
        shown.append(keys)
        assert not dialog.apply_button.isEnabled()
        for item in dialog.rows.items():
            if item.data(0, KEY_ROLE) == ("task", "T000012"):
                dialog.rows.add_tick(item, True)
        assert dialog.ticked() == ["T000012"]
        dialog.apply()
        return True

    browse.run_dialog = run
    browse.set_view("labels")
    browse.save_label(None, "Lifting", ["crane", "rigging"])
    assert ("task", "T000012") in shown[0]
    assert "Lifting" in Model(browse.conn).task("T000012").labels and browse.status.text() == "Changed 1 task: 1 change in its status log."
    browse.save_label("Lifting", "Lifting", ["crane", "rigging"])  # the same keywords: nothing to list again
    assert len(shown) == 1
    browse.find_label_tasks("Line 2")
    assert "No open task mentions Line 2's keywords" in browse.status.text()


def test_discard_and_bring_back(browse):
    """Mods log round 1 (M0021): Discard hides a task or capture made by mistake; the Discarded view brings it back."""
    asked = []
    browse.ask_reason = lambda title, text: asked.append(title) or "Typed twice"
    browse.go_task("T000017")
    edit_menu = next(b for b in browse.actions.findChildren(QPushButton) if b.text() == "Edit").menu()
    assert edit_menu.actions()[-1].text() == "Discard…"
    browse.discard_task("T000017")
    assert asked == ["Discard task"] and ("task", "T000017") not in rows(browse) and browse.sel == ("task", "T000002")
    assert "Discarded Rails need to be painted red." in browse.status.text()
    browse.go_task("T000017")  # opening it from elsewhere shows it in the Discarded view
    assert browse.view == "discarded" and rows(browse) == [("task", "T000017")] and "Typed twice" in shown(browse)
    labels = [b.text() for b in browse.actions.findChildren(QPushButton)]
    assert labels == ["Bring back", "Open folder"]
    browse.go_capture("C000022")
    browse.discard_capture("C000022")
    browse.set_view("discarded")
    assert rows(browse) == [("task", "T000017"), ("capture", "C000022")]  # discarded at the same minute: tasks first
    browse.bring_back_task("T000017")
    assert browse.view == "tasks" and browse.sel == ("task", "T000017") and browse.status.text() == "Brought back Rails need to be painted red."
    browse.ask_reason = lambda title, text: None  # Cancel
    browse.discard_task("T000008")
    assert not Model(browse.conn).task("T000008").discarded
    browse.ask_reason = lambda title, text: ""
    browse.discard_task("T000008")
    assert "has subtasks" in browse.status.text()


def test_the_today_list(browse, monkeypatch):
    """Mods log round 1 (M0016): T puts the selected task on Today; Done asks whether to update it too."""
    from docrepo.model import TODAY

    browse.go_task("T000012")
    browse.task_pane.top.setFocus()
    browse._key("today")
    assert browse.status.text() == "Rigging plan is on Today. Its status log says so."
    add_to = next(b for b in browse.actions.findChildren(QPushButton) if b.text() == "Add to").menu()
    assert add_to.actions()[0].text().startswith("On Today ✓")  # in Add to's menu (release 5.21)
    browse.set_view("today")
    assert browse.view == "today" and browse.sel == ("task", "T000012") and ("task", "T000012") in rows(browse)
    browse.today_note.setText("Sign the overtime sheets")
    browse.add_today_note()
    m = Model(browse.conn)
    assert [(a.subject, a.note) for a in m.today_items()] == [("T000012", ""), (None, "Sign the overtime sheets")]
    item = m.today_items()[0]
    opened = []
    monkeypatch.setattr(browse, "open_capture", lambda **options: opened.append(options))
    browse.close_today_item(item.id, "Done")
    assert browse.today_ask == "T000012" and "is done for today" in " ".join(w.text() for w in browse.filters.findChildren(QLabel))
    # Done today holds the item marked done (release 5.24: each heading holds its items, so it folds).
    done = next(browse.tree.topLevelItem(i) for i in range(browse.tree.topLevelItemCount())
                if "Done today" in browse.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1))
    assert done.childCount() == 1 and done.child(0).data(0, Qt.ItemDataRole.UserRole) == ("task", "T000012")
    browse.answer_today("update")
    assert opened == [{"task": "T000012", "mode": "update", "content": "Done today: "}] and browse.today_ask is None
    browse.set_view("agenda")
    pick = next(w for w in browse.filters.findChildren(QComboBox))
    assert pick.itemData(0) == TODAY
    pick.setCurrentIndex(0)
    assert browse.view == "today"


def test_settings(browse, ctx):
    browse.set_view("settings")
    view = browse.settings_view
    rows_before = browse.conn.execute("SELECT count(*) FROM work_calendar").fetchone()[0]
    view.hotkey.setText("Ctrl+Alt+K")
    view.workdays["Fri"].setChecked(False)
    assert view.save() == ["hotkey", "workdays"]
    saved = json.loads((ctx.data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert saved["hotkey"] == "Ctrl+Alt+K" and saved["workdays"] == ["Mon", "Tue", "Wed", "Thu"]
    assert ctx.changed == [["hotkey", "workdays"]]
    assert browse.conn.execute("SELECT count(*) FROM work_calendar").fetchone()[0] != rows_before
    view.hotkey.setText("K")
    assert view.save() == [] and view.error.isVisibleTo(view) and "can't be used" in view.error.text()
    view.load()
    view.more_hotkeys["browse_hotkey"].setText("ctrl+alt+k")  # the capture window's, in other words
    assert view.save() == [] and "Ctrl+Alt+K is already the hotkey for the capture window" in view.error.text().replace("ctrl+alt+k", "Ctrl+Alt+K")
    view.more_hotkeys["browse_hotkey"].setText("Ctrl+Alt+B")
    view.more_hotkeys["agenda_hotkey"].setText("Ctrl+Alt+G")
    assert view.save() == ["browse_hotkey", "agenda_hotkey"] and "The hotkeys work from now on." in browse.status.text()
    assert (ctx.settings.browse_hotkey, ctx.settings.note_hotkey) == ("Ctrl+Alt+B", "")
    view.load()
    view.backup.setText(str(ctx.data_root / "Backups"))
    assert view.save() == [] and "inside the data root" in view.error.text()


def test_setting_up_another_data_root(tmp_path, monkeypatch):
    from docrepo.config import read_location
    from docrepo.ui import settings_view

    monkeypatch.setattr("docrepo.config.CODE_DIR", tmp_path / "code")  # pytest's folder is inside the code folder
    target = tmp_path / "NewData"
    message = settings_view.set_up_data_root(target)
    assert "from its next start" in message and read_location() == target
    assert (target / "System" / "docs.db").exists() and (target / "Config" / "settings.json").exists()
    with pytest.raises(settings_view.SettingsProblem):
        settings_view.set_up_data_root(tmp_path.relative_to(tmp_path.anchor))


def test_the_window_only_hides_when_closed(browse):
    browse.close()
    assert not browse.isVisible()
    browse.show_browse("reminders", "T000018")
    assert browse.isVisible() and browse.view == "reminders" and browse.sel == ("task", "T000018")


def test_the_windows_stay_light_in_dark_mode(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette

    from docrepo.ui.style import use_light_theme

    use_light_theme(qapp)
    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Base).name() == "#ffffff" and palette.color(QPalette.ColorRole.Text).name() == "#1a1f25"
    # The offscreen platform has no colour schemes (Unknown); on Windows this is Light, never Dark.
    assert qapp.styleHints().colorScheme() != Qt.ColorScheme.Dark


def test_back_up_now_from_settings(browse, ctx, tmp_path):
    view = browse.settings_view
    browse.set_view("settings")
    view.backup.setText(str(tmp_path / "Backups"))
    view.backup_now()
    assert "Save the settings first" in browse.status.text()
    assert "backup_dir" in view.save()
    assert "Backups:</b> none yet" in view.backup_status.text()
    view.backup_now()
    assert browse.status.text().startswith("Backed up the database (docs-1.db)")
    assert (tmp_path / "Backups" / "Database" / "docs-1.db").exists() and "the last was on" in view.backup_status.text()


def test_the_startup_shortcut_button(browse, ctx, tmp_path, monkeypatch):
    from docrepo import startup

    from docrepo.config import make_safe_fs

    monkeypatch.setattr(startup, "startup_folder", lambda: tmp_path / "Startup")
    ctx.fs = make_safe_fs(ctx.data_root, ctx.settings)  # the app's guard, which includes DocRepo's own folder
    browse.set_view("settings")
    browse.settings_view.make_shortcut()
    assert browse.revealed == [startup.shortcut_path(), tmp_path / "Startup"]
    assert "Drag it" in browse.status.text() and startup.shortcut_path().exists()


def test_the_import_form(browse, ctx, tmp_path):
    from sample_workbook import make_workbook

    from docrepo.ui.import_dialog import ImportDialog

    dialog = ImportDialog(browse, ctx)
    dialog.set_workbook(make_workbook(tmp_path / "projects.xlsx"))
    assert dialog.sheet.currentText() == "PROJECTS" and dialog.header.value() == 3 and dialog.table.rowCount() == 11
    assert dialog.preview.toPlainText().startswith("4 tasks to import, 1 row skipped. New people: Dana Kim. New labels: Strategic.")
    dialog.set_field("Strategic", "label", "Strategic Plan")  # the label that's already there
    assert "New labels" not in dialog.preview.toPlainText()
    dialog.set_field("Status", "state")
    assert dialog.states.rowCount() == 5 and dialog.states.isVisibleTo(dialog)
    dialog.set_field("Status", "current_status")
    assert dialog.import_button.isEnabled()
    dialog.import_now()
    assert dialog.outcome == "Imported 4 tasks from Excel, added 1 person. 1 row was skipped."
    m = Model(browse.conn)
    boiler = next(t for t in m.tasks.values() if t.title == "Boiler feedwater pump overhaul")
    assert boiler.labels == ["Line 1", "Strategic Plan"] and boiler.created_by == "Excel import"
    again = ImportDialog(browse, ctx)
    assert again.last.isVisibleTo(again) and "4 tasks" in again.last.text()


def test_the_app_backs_up_on_its_own_thread(ctx, tmp_path, monkeypatch):
    from docrepo import app as app_module
    from docrepo import hotkey

    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    ctx.settings.backup_dir = str(tmp_path / "Backups")
    from docrepo.config import make_safe_fs

    ctx.fs = make_safe_fs(ctx.data_root, ctx.settings)
    capture_app = app_module.CaptureApp(QApplication.instance(), ctx)
    notes: list[tuple[str, str]] = []
    capture_app.notify = lambda title, text: notes.append((title, text))
    try:
        assert capture_app.daily() is True  # a backup is due: there's never been one
        capture_app._backup_thread.join(30)
        for _ in range(50):
            QApplication.processEvents()
            if notes:
                break
        assert notes and notes[-1][0] == "Backup" and notes[-1][1].startswith("Backed up the database")
        from docrepo import backup

        assert backup.last_backup(ctx.conn) and not backup.is_due(ctx.conn, ctx.settings, ctx.now())
    finally:
        capture_app.quit()


def _item(w, key):
    return next(item for item in w.tree.items() if item.data(0, KEY_ROLE) == key)


def test_today_shows_what_is_due_this_week(browse):
    """Mods log round 2 (M0050): Due in the next 7 days, under Today's items, each with Add to Today; Mine only is remembered."""
    from PySide6.QtWidgets import QCheckBox

    from docrepo import db

    browse.set_view("today")
    assert rows(browse).count(("task", "T000019")) == 1 and ("task", "T000012") in rows(browse)
    add = browse.tree.itemWidget(_item(browse, ("task", "T000012")), 3).findChild(QPushButton)
    assert add.text() == "Add to Today"
    add.click()
    m = Model(browse.conn)
    assert [a.subject for a in m.today_items()] == ["T000012"] and rows(browse).count(("task", "T000012")) == 1  # now on Today, not below
    mine = next(b for b in browse.filters.findChildren(QCheckBox) if b.text() == "Mine only")
    mine.setChecked(True)
    assert db.get_state(browse.conn, "today_due_mine") == "1"
    browse.set_view("tasks")
    browse.set_view("today")
    mine = next(b for b in browse.filters.findChildren(QCheckBox) if b.text() == "Mine only")
    assert mine.isChecked() and ("task", "T000019") in rows(browse)  # I lead it
    mine.setChecked(False)
    assert db.get_state(browse.conn, "today_due_mine") == "0"


def test_double_click_opens_the_rows_edit_form(browse, ctx):
    """Mods log round 3 (M0056, decision 57): double-clicking a row opens its edit form, not its subtasks or File Explorer;
    a document still shows its file."""
    opened = []
    for name in ("edit_task", "start_capture_edit", "edit_person", "edit_label", "edit_today_note"):
        setattr(browse, name, lambda x, name=name: opened.append((name, x)))
    item = _item(browse, ("task", "T000001"))
    was = item.isExpanded()
    browse.double_click(item)
    assert opened == [("edit_task", "T000001")] and item.isExpanded() == was and browse.revealed == []
    for view, kind, form in (("unfiled", "capture", "start_capture_edit"), ("people", "person", "edit_person"), ("labels", "label", "edit_label")):
        browse.set_view(view)
        row = next(i for i in browse.tree.items() if (i.data(0, KEY_ROLE) or ("",))[0] == kind)
        browse.double_click(row)
        assert opened[-1] == (form, row.data(0, KEY_ROLE)[1])
    browse.copy_link = lambda doc: opened.append(("copy_link", doc))
    browse.set_view("docs")
    browse.double_click(next(i for i in browse.tree.items() if (i.data(0, KEY_ROLE) or ("",))[0] == "doc"))
    assert len(browse.revealed) == 1 or opened[-1][0] == "copy_link"  # a file shows in File Explorer; a link's address is copied


def _shortcut(widget, keys: str):
    from PySide6.QtGui import QKeySequence, QShortcut

    return next(s for s in widget.findChildren(QShortcut) if s.key() == QKeySequence(keys))


def test_ctrl_enter_saves_the_forms_and_esc_asks_first(browse):
    """Mods log round 2 (M0035): Ctrl+Enter saves and closes the browse tool's forms; Esc closes, asking first when something changed."""
    from docrepo.ui.dialogs import LabelDialog, PersonDialog
    from docrepo.ui.task_forms import BulkEditDialog, TaskEditDialog

    dialog = TaskEditDialog(browse, browse.model(), "T000012", browse._label_options, browse._people_options)
    closed: list[int] = []
    dialog.finished.connect(closed.append)
    asked: list[bool] = []
    dialog.ask_discard = lambda: asked.append(True) or False
    dialog.reject()  # nothing changed: it closes without asking
    assert closed == [0] and asked == []
    dialog = TaskEditDialog(browse, browse.model(), "T000012", browse._label_options, browse._people_options)
    dialog.finished.connect(closed.append)
    dialog.ask_discard = lambda: asked.append(True) or False
    dialog.title.setText("Rigging plan for the lift")
    dialog.reject()  # changed: it asks, and No keeps it open
    assert closed == [0] and asked == [True]
    dialog.title.setText("")
    _shortcut(dialog, "Ctrl+Return").activated.emit()  # a form that can't be saved stays open and says why
    assert closed == [0] and dialog.error.text() == "A task needs a title."
    dialog.title.setText("Rigging plan for the lift")
    _shortcut(dialog, "Ctrl+Enter").activated.emit()
    assert closed == [0, 1] and dialog.values()["title"] == "Rigging plan for the lift"

    person = PersonDialog(browse, "Dana Kim")
    person.finished.connect(closed.append)
    person.hours.setText("lots")
    _shortcut(person, "Ctrl+Return").activated.emit()
    assert closed == [0, 1] and person.error.isVisibleTo(person)
    person.hours.setText("36")
    _shortcut(person, "Ctrl+Return").activated.emit()
    assert closed == [0, 1, 1]
    label = LabelDialog(browse, "Safety", ["safety"])
    label.ask_discard = lambda: False
    label.keywords.setText("safety, guard")
    label.reject()
    assert label.result() == 0 and label.changed()

    bulk = BulkEditDialog(browse, browse.model(), ["T000012"], browse._label_options, browse._people_options, lambda e: [],
                          lambda anchor, picked: None)
    bulk.finished.connect(closed.append)
    assert not bulk.changed()
    _shortcut(bulk, "Ctrl+Return").activated.emit()  # nothing set: nothing to apply, so it stays open
    assert closed == [0, 1, 1]


def test_ctrl_enter_and_esc_in_a_capture_edit(browse):
    """Mods log round 2 (M0035): in the capture edit form, Ctrl+Enter saves and Esc cancels, asking first when something changed."""
    browse.go_capture("C000017")
    browse.start_capture_edit("C000017")
    form = browse.detail_stack.widget(1)
    asked: list[str] = []
    browse.confirm = lambda title, text: asked.append(title) or False
    browse.edit_capture_title.setText("Drawings late")
    _shortcut(form, "Escape").activated.emit()
    assert asked == ["Edit capture C000017"] and browse.editing == "C000017"  # No keeps the edit open
    _shortcut(form, "Ctrl+Return").activated.emit()
    assert browse.editing is None and browse.status.text().startswith("Saved C000017.")
    browse.start_capture_edit("C000017")
    _shortcut(form, "Escape").activated.emit()  # nothing changed: it closes without asking
    assert browse.editing is None and asked == ["Edit capture C000017"]


def test_one_letter_per_topic(browse, monkeypatch):
    """Mods log round 2 (M0036): N note, T new task, U update, A agenda, D Today and E edit act on the selected task; F1 lists them."""
    from PySide6.QtGui import QShortcut

    keys = {s.key().toString(): s for s in browse.findChildren(QShortcut)}
    assert {"N", "T", "U", "A", "D", "E", "Ctrl+F", "Ctrl+Shift+F", "F1"} <= set(keys) and "G" not in keys
    assert browse.tb_new.text() == "New task" and browse.tb_new.isHidden()  # on the command bar, its key in the tooltip
    opened = []
    monkeypatch.setattr(browse, "open_capture", lambda **options: opened.append(options))
    browse.go_task("T000012")
    browse.task_pane.top.setFocus()
    for k in ("N", "T", "U", "A"):
        keys[k].activated.emit()
    assert [(o["mode"], o.get("agenda_focus", False)) for o in opened] == [("note", False), ("new_task", False), ("update", False), ("update", True)]
    keys["D"].activated.emit()
    assert browse.status.text() == "Rigging plan is on Today. Its status log says so."
    shown = []
    browse.run_dialog = lambda d: shown.append(d.windowTitle()) or False
    keys["F1"].activated.emit()
    keys["E"].activated.emit()
    assert shown == ["Keys", "Edit task T000012"]
    labels = [b.text() for b in browse.actions.findChildren(QPushButton)]
    assert labels == ["Note", "Update", "Add to", "Edit", "Task view", ""]  # More is an icon at the row's end (release 5.21); Task view, 5.34


def test_the_task_page_bar_and_its_links(browse, monkeypatch):
    """The visual overhaul's O9 (release 5.21, decisions 64 to 69): the bar, the page's folds and menus, and two columns once
    the page is 760 px wide."""
    from PySide6.QtCore import QRect

    browse.go_task("T000008")
    browse.actions_layout.setGeometry(QRect(0, 0, 900, 40))  # the bar at a usual pane's width
    buttons = browse.actions.findChildren(QPushButton)
    more = buttons[-1]
    assert more.accessibleName() == "More" and more.property("flowEnd") and more.menu().actions()[0].text() == "New subtask\tT"
    assert len({b.y() for b in buttons}) == 1 and more.geometry().right() == 899  # one row, More at its end
    add_to = next(b for b in buttons if b.text() == "Add to").menu().actions()
    assert add_to[0].text().startswith("Today") and add_to[-1].text() == "Someone else or another task…"
    opened = []
    monkeypatch.setattr(browse, "open_capture", lambda **options: opened.append(options))
    browse.on_link(QUrl("new:T000008"))
    browse.on_link(QUrl("update:T000008"))
    assert opened == [{"task": "T000008", "mode": "new_task"}, {"task": "T000008", "mode": "update"}]
    assert "Folder" not in shown(browse)
    browse.on_link(QUrl("fold:details"))
    assert browse.state.details and "Tasks\\T000008" in shown(browse)
    browse.on_link(QUrl("menu:scope"))
    assert [a.text() for a in browse._menu.actions() if a.isChecked()] == ["With subtasks"]
    browse._menu.actions()[0].trigger()
    assert browse.state.scope == "self" and "This task ▾" in shown(browse)
    browse._menu.close()
    browse.on_link(QUrl("menu:order"))
    browse._menu.actions()[1].trigger()
    assert browse.state.order == "new"
    browse._menu.close()
    browse.on_link(QUrl("fold:anything"))  # only the page's own folds
    browse.go_task("T000012")  # another task: its folds start closed; the tab and order stay
    assert not browse.state.details and browse.state.order == "new"
    browse.task_pane.setFixedWidth(1040)  # the pane made wide: the page is drawn again in two columns
    QApplication.processEvents()
    assert browse.task_pane.page_width() >= 760 and "Folder" in shown(browse)  # the rail, with Details open
    browse.task_pane.setFixedWidth(520)
    QApplication.processEvents()
    assert "Folder" not in shown(browse)


def test_find_in_this_view(browse):
    """Mods log round 2 (M0026): Ctrl+F narrows the view you're in; a tree keeps its parents, faded, and opens closed branches."""
    from docrepo.ui.tree_view import DIM_ROLE

    browse.set_view("tasks")
    browse.open_find()
    assert browse.find_bar.isVisibleTo(browse)
    browse.find_box.setText("rigging plan")
    rows = {i.data(0, KEY_ROLE): i for i in browse.tree.items()}
    rig, top = rows[("task", "T000012")], rows[("task", "T000001")]
    assert not rig.isHidden() and not rig.data(0, DIM_ROLE) and browse.tree.is_shown(rig)
    assert not top.isHidden() and top.data(0, DIM_ROLE)  # a parent, kept for context
    assert rows[("task", "T000019")].isHidden() and browse.find_count.text().endswith(("match", "matches"))
    browse.find_box.setText("Mike Ortiz")  # people count too
    assert not rows_after(browse)[("task", "T000012")].isHidden()
    browse.find_box.setText("nothing like this")
    assert browse.find_count.text() == "Nothing in this view matches"
    browse.set_view("today")  # another view clears it
    assert browse.find_bar.isHidden() and browse.find_box.text() == ""
    browse.set_view("timeline")
    browse.open_find()
    assert browse.find_bar.isHidden() and "own filters" in browse.status.text()


def rows_after(w) -> dict:
    return {i.data(0, KEY_ROLE): i for i in w.tree.items()}


def test_quick_tasks_on_today(browse):
    """Mods log round 2 (M0039, M0040): Today's box makes a quick task, or a note; a note can be edited or made a task, and
    Edit task's Parents files a quick task under its real task."""
    from docrepo import quick
    from docrepo.ui.task_forms import TaskEditDialog

    browse.set_view("today")
    browse.today_note.setText("Call the vendor about seals by Fri")
    browse.add_today_item()
    m = Model(browse.conn)
    t = next(x for x in m.tasks.values() if x.title == "Call the vendor about seals")
    parent = quick.parent_id(browse.conn)
    assert (t.due, m.parents_of(t.id), browse.sel) == ("2026-10-09", [parent], ("task", t.id)) and "under Quick tasks" in browse.status.text()
    browse.set_today_kind("note")
    browse.today_note.setText("Sign the overtime sheets")
    browse.add_today_item()
    note = next(a for a in Model(browse.conn).today_items() if not a.subject)
    browse.ask_text = lambda title, label, text: "Sign the overtime sheets by noon"
    browse.edit_today_note(note.id)
    assert next(a for a in Model(browse.conn).agenda if a.id == note.id).note == "Sign the overtime sheets by noon"
    browse.make_today_task(note.id)
    m = Model(browse.conn)
    made = next(a for a in m.agenda if a.id == note.id).subject
    assert m.task(made).title == "Sign the overtime sheets by noon" and m.parents_of(made) == [parent]
    dialog = TaskEditDialog(browse, browse.model(), t.id, browse._label_options, browse._people_options, lambda anchor, picked: picked("T000008"))
    assert dialog.parents_hint.text().startswith("It's a quick task")
    dialog.put_button.click()
    assert dialog.parents == ["T000008"] and dialog.changed()
    browse.save_task_edit(t.id, dialog.values())
    assert Model(browse.conn).parents_of(t.id) == ["T000008"] and browse.status.text() == "1 change in the status log."


def test_the_suggested_hotkeys(browse):
    """Mods log round 2 (M0036): Use the suggested keys fills each empty hotkey box with Ctrl+Shift and its letter."""
    browse.set_view("settings")
    view = browse.settings_view
    view.more_hotkeys["browse_hotkey"].setText("Ctrl+Alt+B")
    view.suggest_hotkeys()
    assert {k: box.text() for k, box in view.more_hotkeys.items()} == {
        "browse_hotkey": "Ctrl+Alt+B", "note_hotkey": "Ctrl+Shift+N", "new_task_hotkey": "Ctrl+Shift+T", "update_hotkey": "Ctrl+Shift+U",
        "agenda_hotkey": "Ctrl+Shift+A", "today_hotkey": "Ctrl+Shift+D", "pin_hotkey": "",  # Pin has no suggested key (round 3)
        "outlook_hotkey": "Ctrl+Shift+E",  # E for email (release 5.33.1)
        "today_panel_hotkey": ""}  # no default (release 5.43, decision 216)
    assert browse.status.text() == "Filled 6 hotkeys. Save settings to use them."
    assert view.save() == ["browse_hotkey", "note_hotkey", "new_task_hotkey", "update_hotkey", "agenda_hotkey", "today_hotkey", "outlook_hotkey"]


def test_a_capture_s_edit_shows_its_text_and_goes_to_its_block(browse, ctx):
    """Release 5.25 (decision 112): the text shows with its formatting, read-only; Go to it on the page opens its block."""
    from docrepo.save import CaptureDraft, save_capture

    r = save_capture(browse.conn, ctx.data_root, ctx.fs, Settings(me="P001"),
                     CaptureDraft(content="Guard **fitted**.\n- rails next", formatted=True, task="T000012"), NOW)
    browse.refresh()
    browse.go_capture(r.capture_id)
    browse.start_capture_edit(r.capture_id)
    assert browse.edit_content.value() == ("Guard **fitted**.\n- rails next", True) and not browse.edit_goto.isHidden()
    browse.edit_goto.click()
    notes = browse.task_pane.notes
    assert browse.editing is None and browse.sel == ("task", "T000012") and browse.detail_stack.currentIndex() == 2
    assert notes.textCursor().block().text().endswith("· Note") and notes.kind(notes.textCursor().block()) == "caption"


def test_release_59_people_labels_reference_fields_and_capacity(browse, ctx):
    """Release 5.9: people's email, group and role, Copy emails, nested labels in the Labels view, pickers and filters,
    reference fields named in Settings, and the capacity view grouped by group with plant event weeks named."""
    from docrepo import tasks
    from docrepo.ui.widgets import CheckMenuButton, label_filter, label_options, people_filter

    browse.set_view("people")
    browse.save_person(None, "Dana Kim", ["Dana"], 36, email="dana.kim@example.com", group="Quality", role="Inspector")
    dana = next(p for p in Model(browse.conn).people.values() if p.name == "Dana Kim")
    browse.save_person(dana.id, "Dana Kim", ["Dana"], 32)  # None leaves email, group and role as they are
    dana = Model(browse.conn).people[dana.id]
    assert (dana.email, dana.group, dana.role, dana.hours) == ("dana.kim@example.com", "Quality", "Inspector", 32)
    assert browse.tree.columnCount() == 5
    browse.copy_emails(["P003", "P004", "P006"])
    assert QGuiApplication.clipboard().text() == "tom.becker@example.com; mike.ortiz@example.com"
    assert browse.status.text() == "Copied 2 email addresses. Paste into Outlook's To box. No address set for Todd."
    choices, sets = people_filter(Model(browse.conn))
    assert ("Group: Maintenance", ["P003", "P004"]) in sets
    browse.set_view("labels")
    browse.save_label(None, "Production line", ["production line"])
    for name in ("Line 1", "Line 2"):
        browse.save_label(name, name, [name.lower()], under="Production line")
    m = Model(browse.conn)
    assert m.sublabels("Production line") == ["Line 1", "Line 2"] and "Line 1" not in browse._parent_choices()
    assert [o.label for o in label_options(m, "line", [])] == ["Production line › Line 1", "Production line › Line 2"]
    assert [o.label for o in label_options(m, "production", [])] == ["Production line › Line 1", "Production line › Line 2"]
    assert label_filter(m)[1] == [("Production line: all", ["Line 1", "Line 2"])]
    browse.set_view("tasks")
    labels = next(w for w in browse.filters.findChildren(CheckMenuButton) if w.noun == "Labels")
    labels.sets[0][0].trigger()  # ticks both sublabels
    assert labels.values() == ["Line 1", "Line 2"] and labels.sets[0][0].isChecked()
    # Reference fields: named in Settings, a box each in Edit task.
    browse.set_view("settings")
    browse.settings_view.references.setText("Work order #, Permit no.")
    assert "reference_fields" in browse.settings_view.save()
    assert ctx.settings.reference_fields == ["Work order #", "Permit no."]
    tasks.update_task(browse.conn, ctx.settings, "T000012", at=NOW, via="Browse tool", references={"Work order #": "48213"})
    tasks.create_task(browse.conn, ctx.settings, title="Spring outage", at=NOW, created_by="Excel import", start="2026-10-19",
                      due="2026-10-23", plant_event=True)
    browse.refresh()
    browse.copy_reference("T000012", "Work order #")
    assert QGuiApplication.clipboard().text() == "48213"
    # Capacity: each group's people under its heading, and a plant event's weeks named.
    browse.set_view("capacity")
    browse.cap_by_group.setChecked(True)
    heads = [x if isinstance(x, str) else x.person for x in browse._cap_line_rows]
    assert heads[:4] == ["Engineering", "P001", "P002", "Maintenance"] and heads[-2:] == ["No group", "P006"]
    weeks = [browse.cap_table.horizontalHeaderItem(i).text() for i in range(1, browse.cap_table.columnCount())]
    assert [w.split("\n")[1] for w in weeks if "\n" in w] == ["Spring outage"]


def test_edit_task_and_edit_selected_have_plant_event_and_reference_fields(browse, ctx):
    """Release 5.9: Edit task's Plant event tick box and a box per reference field, with the line naming a plant event
    its dates fall in; Edit selected ticks or unticks Plant event."""
    from docrepo import tasks
    from docrepo.ui.task_forms import BulkEditDialog, TaskEditDialog

    tasks.create_task(browse.conn, ctx.settings, title="Spring outage", at=NOW, created_by="Excel import", start="2026-10-12",
                      due="2026-10-16", plant_event=True)
    browse.refresh()
    dialog = TaskEditDialog(browse, browse.model(), "T000012", browse._label_options, browse._people_options,
                            reference_fields=["Work order #"], today=NOW.date())
    assert dialog.during.text() == "Due falls during Spring outage, Mon 12 Oct to Fri 16 Oct."
    dialog.references["Work order #"].setText("48213")
    dialog.plant_event.setChecked(True)
    values = dialog.values()
    assert values["references"] == {"Work order #": "48213"} and values["plant_event"] is True
    plain = TaskEditDialog(browse, browse.model(), "T000012", browse._label_options, browse._people_options)
    assert "references" not in plain.values()  # no reference fields in Settings: no boxes, nothing changed
    bulk = BulkEditDialog(browse, browse.model(), ["T000012"], browse._label_options, browse._people_options, lambda e: [],
                          lambda anchor, picked: None)
    bulk.plant_event.setCurrentIndex(2)
    assert bulk.edit().fields == {"plant_event": False}


def test_a_list_grouped_by_a_parent_label(browse):
    """Release 5.9 (M0051): with a parent label, the lists gain a Group by that puts each task under its sublabel's heading."""
    import re

    assert browse._group_box("due") is None  # no parent label yet: no Group by
    browse.save_label(None, "Production line", ["production line"])
    for name in ("Line 1", "Line 2"):
        browse.save_label(name, name, [name.lower()], under="Production line")
    browse.set_view("due")
    browse._set_list_group("due", "Production line")
    heads = [re.sub(r"<[^>]+>|&nbsp;", " ", item.data(0, HTML_ROLE)).split()[:-1] for item in browse.tree.items() if item.data(0, KEY_ROLE) is None]
    assert heads == [["Line", "1"]]  # both tasks in the list are under Reactor impeller upgrade, which has Line 1
    assert rows(browse) == [None, ("task", "T000019"), ("task", "T000012")]


def test_the_page_view_draws_the_pages_pictures(qapp):
    """Release 5.21: initials, the owner's figure, state marks and the progress bar, drawn for the task page; nothing else."""
    from docrepo.ui.page_view import PageView, picture

    assert picture(QUrl("avatar:TB"), 2.0).size().width() == 40 and picture(QUrl("avatar:me"), 1.0).width() == 20
    assert picture(QUrl("mark:ip"), 1.0).width() == 14 and picture(QUrl("mark:zz"), 1.0) is None
    assert picture(QUrl("progress:1:4"), 1.0).width() == 72 and picture(QUrl("progress:x"), 1.0) is None
    assert picture(QUrl("https://example.com/a.png"), 1.0) is None
    view = PageView()
    view.setHtml('<img src="avatar:TB" width="20" height="20"> <img src="mark:cl" width="14" height="14">')
    assert view.document().resource(2, QUrl("avatar:TB")) is not None
    view.deleteLater()
