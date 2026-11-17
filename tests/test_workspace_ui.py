"""The workspace in the browse window (release 5.152, the design workspace's ``docs/mods/workspace-view-plan.md``,
decisions 663 to 670, 678 to 687 and 698 to 702), driven offscreen over the sample data with the made-up work of
``workspace_example``: how it opens and goes back, the chain, the middle column with its quick entry bar, its notes and
Dates, and the resources with their search."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from docrepo import edits, waits  # noqa: E402
from docrepo import workspace as ws  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import workspace as workspace_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE  # noqa: E402
from workspace_example import AT, make  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qapp, sample_root):
    conn, root, fs = sample_root
    work = make(conn, root, fs)
    edits.add_to_today(conn, root, fs, work.crane, "", AT)
    ctx = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1500, 900)
    w.set_view("today")
    yield w, work
    if getattr(w, "workspace", None) is not None:
        w.workspace.pane.notes.save_now()
    capture.deleteLater()
    w.deleteLater()


def settle() -> None:
    for _ in range(5):
        QApplication.processEvents()


def row(browse, task_id: str):
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", task_id))


def labels(menu: QMenu) -> list[str]:
    return [a.text().split("\t")[0] for a in menu.actions() if not a.isSeparator()]


def key(widget, k, mods=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, k, mods))


def opened(browse, task_id: str):
    workspace_ui.open_workspace(browse, task_id)
    settle()
    return browse.workspace


# ---- opening it and going back (decisions 663, 667, 682 and 687) ----
def test_a_today_rows_double_click_opens_the_workspace(setup):
    browse, work = setup
    browse.double_click(row(browse, work.crane))
    settle()
    assert workspace_ui.is_open(browse) and browse.workspace.here == work.crane
    assert browse.middle.isHidden() and browse.detail.isHidden() and browse.nav.isVisible()  # beside the places (682)
    assert browse.view == "today" and browse.sel == ("task", work.crane)
    assert "Gathered from 3 pages: this task, 1 under it and 1 above it." in browse.status.text()


def test_enter_on_a_today_row_opens_it_but_elsewhere_opens_the_page(setup):
    browse, work = setup
    browse.tree.task_opened(work.crane)
    assert workspace_ui.is_open(browse)
    browse.workspace.close_to_origin()
    browse.set_view("tasks")
    browse.open.add(work.project)
    browse.render_list()
    browse.double_click(row(browse, work.crane))
    assert not workspace_ui.is_open(browse) and browse.sel == ("task", work.crane)


def test_w_opens_the_selected_tasks_workspace(setup):
    browse, work = setup
    browse.set_view("tasks")
    browse.go_task(work.rig)
    browse.tree.setFocus()
    workspace_ui.work_key(browse)
    assert workspace_ui.is_open(browse) and browse.workspace.here == work.rig
    assert browse.workspace.origin == "tasks" and not browse.workspace.from_today


def test_every_tiles_menu_has_work_on_it_first_on_today(setup):
    browse, work = setup
    from docrepo.ui import task_tile as tile_ui

    menu = QMenu()
    tile_ui.fill_menu(browse, work.crane, menu, work_first=True)
    assert labels(menu)[:2] == ["Work on it", "Open the task page"] and menu.defaultAction().text().startswith("Work on it")
    other = QMenu()
    tile_ui.fill_menu(browse, work.crane, other)
    assert labels(other)[:2] == ["Open", "Work on it"] and other.defaultAction().text().startswith("Open")
    menu.actions()[0].trigger()
    assert workspace_ui.is_open(browse) and browse.workspace.here == work.crane


def test_the_task_page_bar_has_work_on_it(setup):
    browse, work = setup
    browse.set_view("tasks")
    browse.go_task(work.crane)
    buttons = [b for b in browse.actions.findChildren(type(browse.tb_new)) if b.text() == "Work on it"]
    assert buttons and "W" in buttons[0].toolTip()
    buttons[0].click()
    assert workspace_ui.is_open(browse) and browse.workspace.origin == "tasks"


def test_esc_goes_back_to_today_with_the_task_picked(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    key(w, Qt.Key.Key_Escape)
    assert not workspace_ui.is_open(browse)
    assert browse.view == "today" and browse.sel == ("task", work.crane) and browse.middle.isVisible()
    assert browse.tree.currentItem().data(0, KEY_ROLE) == ("task", work.crane)


def test_a_place_picked_in_the_sidebar_leaves_it(setup):
    browse, work = setup
    opened(browse, work.crane)
    browse.set_view("tasks")
    assert not workspace_ui.is_open(browse) and browse.view == "tasks"


def test_done_for_today_shows_from_today_and_keeps_you_here(setup):
    browse, work = setup
    browse.capture = None  # Done's Update opens no window here
    w = opened(browse, work.crane)
    assert w.buttons["done"].isVisibleTo(w)
    w.buttons["done"].click()
    settle()
    assert workspace_ui.is_open(browse) and ws.done_today(browse.model(), work.crane, browse.today())
    assert not w.buttons["done"].isVisibleTo(w)  # only while it's on Today
    w.close_to_origin()
    assert browse.view == "today"


def test_the_agent_buttons_place_shows_nothing_yet(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    assert w.agents.isHidden()


# ---- the chain (decisions 664, 684 and 686) ----
def test_the_chain_shows_the_project_this_task_and_its_subtasks(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    assert list(w.chain.cards) == [work.project, work.crane, work.rig]
    assert "THIS TASK" in w.chain.cards[work.crane].text()
    assert "waiting on Mike" in w.chain.cards[work.crane].text()
    assert "Survey booked for 17 Nov." in w.chain.cards[work.project].text()


def test_two_parents_show_a_path_each(setup):
    browse, work = setup
    w = opened(browse, work.rig)
    assert list(w.chain.cards) == [work.project, work.crane, work.outage, work.rig]
    captions = [lb.text() for lb in w.chain.findChildren(type(w.title)) if lb.objectName() == "wsCaption"]
    assert "and under" in captions and "under both" in captions


def test_a_click_on_a_parent_reads_its_notes_in_place(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.chain.cards[work.project].clicked.emit(work.project)
    assert w.picked == work.project and w.reading() == work.project
    assert w.pane.all_mode and "read only" in w.pane.of_label.text()
    assert "Edit there" in w.pane.all_view.toPlainText()
    assert not w.card.entry_row.isVisibleTo(w)  # a parent is read only (668)
    assert w.acting == work.crane  # the bar stays on this task
    assert "Of Cooling tower 2 rebuild and everything under it (" in w.scope.text()


def test_a_click_on_a_subtask_edits_its_notes_and_the_bar_acts_on_it(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.chain.cards[work.rig].clicked.emit(work.rig)
    assert w.acting == work.rig and w.pane.task_id == work.rig and not w.pane.all_mode
    assert w.on_label.isVisibleTo(w) and "On Rig the east cell first" in w.on_label.text()
    assert w.card.entry_row.isVisibleTo(w) and browse.sel == ("task", work.rig)
    QApplication.sendEvent(w, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier))
    w.back()
    assert w.picked == work.crane and w.acting == work.crane


def test_a_double_click_works_on_that_task(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.chain.cards[work.rig].opened.emit(work.rig)
    assert w.here == work.rig and w.origin == "today"


# ---- the quick entry bar (decisions 678, 701 and 702) ----
def test_enter_keeps_an_update_as_the_status_with_undo(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.card.box.setText("Mike has the quote: 90 t crane on 24 Nov")
    key(w.card.box, Qt.Key.Key_Return)
    m = browse.model()
    assert m.task(work.crane).current_status == "Mike has the quote: 90 t crane on 24 Nov"
    assert w.card.box.text() == "" and workspace_ui.is_open(browse)
    newest = max(m.notes_of(work.crane), key=lambda c: c.id)
    assert newest.types == ["update"] and newest.saved.startswith("2026-11-12")  # an Update capture on the task
    browse._undo()
    m = browse.model()
    assert m.task(work.crane).current_status == "Asked Mike for the crane vendor's quote"
    assert m.captures[newest.id].discarded


def test_shift_enter_keeps_a_note_under_today_with_undo(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    before = browse.model().task(work.crane).current_status
    w.card.box.setText("Lift plan needs the east cell first")
    key(w.card.box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    m = browse.model()
    page = m.pages[work.crane]
    assert page.rstrip().endswith("Lift plan needs the east cell first") and "# Thu 12 Nov 2026" in page
    assert m.task(work.crane).current_status == before
    assert "Lift plan needs the east cell first" in w.pane.notes.toPlainText()
    browse._undo()
    assert "Lift plan needs" not in browse.model().pages[work.crane]


def test_later_shows_while_on_today_and_add_to_today_while_not(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    assert w.card.later_button.isVisibleTo(w) and not w.card.add_button.isVisibleTo(w)
    w.pick(work.rig)
    assert w.card.add_button.isVisibleTo(w) and not w.card.later_button.isVisibleTo(w)
    w.card.add_button.click()
    assert ws.today_item(browse.model(), work.rig) is not None
    assert w.card.later_button.isVisibleTo(w)


# ---- the notes and the outline (decisions 668, 669 and 683) ----
def test_the_outline_lists_the_chain_and_dates(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    words = [e[3] for e in w.pane.outline.entries()]
    assert words[0] == "Cooling tower 2 rebuild" and "Crane for the fan lift" in words and "Rig the east cell first" in words
    assert words[-1] == "Dates" and "Booking" in words


def test_picking_a_parents_heading_in_the_outline_reads_it(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    number = next(n for n, place in w.pane.places.items() if place[0] == "page" and place[1] == work.project)
    w.pane._outline_picked(number)
    settle()
    assert w.picked == work.project and w.pane.all_mode


def test_edit_there_opens_its_page_and_alt_left_comes_back(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.pick(work.project)
    w.on_link(f"notesgo:{work.project}:")
    assert not workspace_ui.is_open(browse) and browse.sel == ("task", work.project)
    assert "Alt+Left goes back to the workspace of Crane for the fan lift" in browse.status.text()
    browse._back_to_all_notes()
    assert workspace_ui.is_open(browse) and w.here == work.crane and w.picked == work.project


def test_a_saved_capture_keeps_the_workspace(setup):
    browse, work = setup
    opened(browse, work.crane)
    from docrepo.save import SaveResult

    browse.capture_saved(SaveResult(None, None, work.crane, [], [], "Saved."))
    assert workspace_ui.is_open(browse)


# ---- Dates (decisions 681, 698 and 699) ----
def test_a_click_on_a_day_changes_it_in_words_with_undo(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    due = next(k for k, (r, _parts) in w.dates.shown.items() if r.kind == "Due" and r.task == work.crane)
    w.dates.shown[due][1]["day"].click()
    assert w.dates.box is not None and w.dates.box.text() == "fri 27 nov"
    assert ws.DAY_HINT in [p.text() for p in w.dates.shown[due][1].values() if hasattr(p, "text")]
    w.dates.box.setText("mon 23 nov")
    key(w.dates.box, Qt.Key.Key_Return)
    assert browse.model().task(work.crane).due == "2026-11-23"
    assert workspace_ui.is_open(browse)
    browse._undo()
    assert browse.model().task(work.crane).due == "2026-11-27"


def test_esc_leaves_a_day_unchanged(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    due = next(k for k, (r, _parts) in w.dates.shown.items() if r.kind == "Due" and r.task == work.crane)
    w.dates.shown[due][1]["day"].click()
    w.dates.box.setText("tomorrow")
    key(w.dates.box, Qt.Key.Key_Escape)
    assert w.dates.box is None and w.editing == "" and browse.model().task(work.crane).due == "2026-11-27"
    assert workspace_ui.is_open(browse)


def test_a_follow_up_moves_from_dates(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    k = next(k for k, (r, _parts) in w.dates.shown.items() if r.kind == "Follow-up")
    w.change_day(w._rows[k], date(2026, 11, 19))
    assert waits.current(browse.model(), work.crane).follow_up == "2026-11-19"


def test_earlier_dates_fold_behind_show_earlier(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    assert all(r.day >= browse.today() for r, _ in w.dates.shown.values())
    w._toggle_earlier()
    assert any(r.kind == "Meeting" and r.day < browse.today() for r, _ in w.dates.shown.values())


def test_add_a_key_date_on_the_task_being_edited(setup):
    browse, work = setup
    browse.ask_text = lambda title, label, text: "fri 4 dec Lift drawing to Mike"
    w = opened(browse, work.crane)
    w.add_key_date()
    assert [k.description for k in browse.model().key_dates_of(work.crane)][-1] == "Lift drawing to Mike"
    assert any(r.words == "Lift drawing to Mike" for r, _ in w.dates.shown.values())


# ---- the resources (decisions 679, 680 and 685) ----
def test_the_search_narrows_the_resources_and_esc_clears_it(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.search.setText("kickoff")
    text = w.resources.toPlainText()
    assert "Meetings  1 of 2" in text or "Meetings 1 of 2" in " ".join(text.split())
    assert "booking" not in text
    key(w.search, Qt.Key.Key_Escape)  # Esc clears the search first
    assert w.search.text() == "" and workspace_ui.is_open(browse)
    assert "booking" in w.resources.toPlainText()
    key(w.search, Qt.Key.Key_Escape)  # then goes back
    assert not workspace_ui.is_open(browse)


def test_a_meeting_row_reads_its_notes_in_the_middle(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.on_link(f"wsmeet:{work.kickoff}")
    assert w.meeting == work.kickoff and w.pane.all_mode
    assert "Cooling tower kickoff" in w.pane.banner.text() and "Open its notes" in w.pane.banner.text()
    assert "Attendees" in w.pane.all_view.toPlainText()
    w.back()
    assert w.meeting == "" and not w.pane.all_mode


def test_a_whose_chip_picks_that_task(setup):
    browse, work = setup
    w = opened(browse, work.rig)
    w.on_link(f"wspick:{work.crane}")
    assert w.picked == work.crane and w.reading() == work.crane


def test_a_section_folds(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    w.on_link("wsfold:meetings")
    assert "Cooling tower kickoff" not in w.resources.toPlainText()
    w.on_link("wsfold:meetings")
    assert "Cooling tower kickoff" in w.resources.toPlainText()


def test_the_page_says_its_words(setup):
    browse, work = setup
    w = opened(browse, work.crane)
    text = w.text()
    for words in ("Crane for the fan lift", "Current status", "Asked Mike for the crane vendor's quote", "Follow up with Mike",
                  "Crane on site", "Cooling tower weekly 10 Nov"):
        assert words in text, words
    assert w.pane.facts.isHidden() and w.pane.history.isHidden()
