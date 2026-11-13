"""Release 5.128, the Review view in the browse window, offscreen (the cold-eyes plan's section 6, decisions 496 to 503):
the steps a list at a time with Next and Back passing over empty ones, Waiting on others' Ask for an update, step 4's
Mark reviewed (R) with Undo, Close and Review every…, Done and Plan next week, Today's line on the review day, Settings'
card and Edit task's Review every. The sample's today is Thursday 8 October 2026; these run on Friday the 9th. Every name
here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import review, tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.lists import review as review_list  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402
from docrepo.ui.tree_view import ACTIONS_ROLE, HTML_ROLE, KEY_ROLE, LINE_ROLE  # noqa: E402

FRI = datetime(2026, 10, 9, 9, 0)
REACTOR, WALKTHROUGH, HOLIDAY, RIGGING = "T000001", "T000002", "T000016", "T000012"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def clock():
    return {"now": FRI}


@pytest.fixture
def ctx(qapp, sample_root, clock):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: clock["now"])


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


def keys(browse) -> list:
    return [i.data(0, KEY_ROLE) for i in browse.tree.items()]


def row(browse, key):
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == key)


def bar(browse) -> list[str]:
    lay = browse.filters_layout
    return [w.text() for w in (lay.itemAt(i).widget() for i in range(lay.count())) if isinstance(w, QPushButton) and not w.isHidden()]


def page_bar(browse) -> list[str]:
    lay = browse.actions_layout
    out = []
    for w in (lay.itemAt(i).widget() for i in range(lay.count())):
        for b in [w] if isinstance(w, QPushButton) else (w.findChildren(QPushButton) if w is not None else []):
            out.append(b.text() or b.accessibleName())
    return out


def step(browse) -> str:
    return review.STEPS[review_list.session(browse).step].id


def actions(item) -> dict:
    return {label: clicked for label, clicked, _ in item.data(0, ACTIONS_ROLE).actions}


def test_review_walks_the_steps_and_passes_over_empty_ones(browse):
    browse.set_view("review")
    assert step(browse) == "unfiled"
    assert "Step 1 of 7 · Unfiled · 3" in browse.pane_title.text()
    assert bar(browse) == ["Back", "Next: Overdue and due in the next 7 days"]
    assert all(k[0] == "capture" for k in keys(browse) if k) and len([k for k in keys(browse) if k]) == 3
    assert browse.sel == ("capture", keys(browse)[0][1])  # its first capture is open, with File to task on its page
    assert "File to task" in page_bar(browse)
    review_list.go(browse)
    assert step(browse) == "due" and "Step 2 of 7 · Overdue and due in the next 7 days · 3" in browse.pane_title.text()
    review_list.go(browse)
    assert step(browse) == "waiting" and browse._asks()
    review_list.go(browse)
    assert step(browse) == "projects"
    assert [k[1] for k in keys(browse) if k and k[0] == "task" and row(browse, k).parent() is None] == [REACTOR, WALKTHROUGH, HOLIDAY]
    review_list.go(browse)  # Gone quiet and No next step are empty in the sample: passed over, and said so
    assert step(browse) == "done"
    assert browse.status.text() == "Nothing gone quiet and no project without a next step. On to Done."
    review_list.go(browse, back=True)
    assert step(browse) == "projects" and browse.status.text().startswith("No project without a next step and nothing gone quiet.")
    review_list.go(browse, back=True)
    review_list.go(browse, back=True)
    review_list.go(browse, back=True)
    assert step(browse) == "unfiled" and not browse.filters_layout.itemAt(0).widget().isEnabled()  # Back, on the first step


def test_review_carries_on_where_it_was_left(browse):
    browse.set_view("review")
    review_list.go(browse)
    review_list.go(browse)
    browse.set_view("tasks")
    browse.set_view("review")
    assert step(browse) == "waiting"


def test_waiting_on_others_has_ask_for_an_update_and_the_longest_wait_first(browse):
    browse.set_view("review")
    review_list.go(browse)
    review_list.go(browse)
    menu = browse.tree.row_menu(row(browse, ("task", RIGGING)))
    assert next(a for a in menu.actions() if not a.isSeparator()).text() == "Ask for an update"
    line = row(browse, ("task", RIGGING)).data(0, LINE_ROLE)
    assert "no change for 3 d" in line.muted
    shown = [i.data(0, KEY_ROLE)[1] for i in browse.tree.items()
             if i.data(0, KEY_ROLE) and i.data(0, LINE_ROLE) is not None and not i.data(0, LINE_ROLE).dim]
    assert browse.sel == ("task", shown[0])  # the first row in the step's order is open
    m = browse.model()
    tops = [browse.tree.topLevelItem(i).data(0, KEY_ROLE)[1] for i in range(browse.tree.topLevelItemCount())]
    longest = [max(review.waited_days(m, x, FRI.date()) for x in [t, *m.descendants_of(t)] if x in shown) for t in tops]
    assert longest == sorted(longest, reverse=True)  # each project's longest wait, the longest first


def test_step_4_marks_a_project_reviewed_with_undo(browse):
    browse.set_view("review")
    for _ in range(3):
        review_list.go(browse)
    assert step(browse) == "projects" and browse.sel == ("task", REACTOR)
    assert page_bar(browse)[0] == "Mark reviewed"  # first on its page's bar
    top = row(browse, ("task", REACTOR))
    assert list(actions(top)) == ["Mark reviewed", "Update", "Park", "Close", "Review every…"]
    assert any(k and k[0] == "actline" for k in (top.child(i).data(0, KEY_ROLE) for i in range(top.childCount())))  # what's happened
    review_list.mark_reviewed(browse)  # R
    assert Model(browse.conn).task(REACTOR).reviewed == "2026-10-09 09:00:00"
    assert ("task", REACTOR) not in keys(browse) and browse.sel == ("task", WALKTHROUGH)
    assert "Step 4 of 7 · Projects due for review · 2" in browse.pane_title.text()
    assert browse.status.text().startswith("Reactor impeller upgrade: reviewed. It comes up again in the week of Mon 12 Oct.")
    browse._status_link("undo")
    assert Model(browse.conn).task(REACTOR).reviewed is None and ("task", REACTOR) in keys(browse)


def test_r_says_where_it_works_outside_step_4(browse):
    browse.set_view("tasks")
    browse.select("task", REACTOR)
    review_list.mark_reviewed(browse)
    assert Model(browse.conn).task(REACTOR).reviewed is None
    assert "step 4" in browse.status.text()


def test_close_asks_before_closing_open_subtasks_and_review_every_sets_the_interval(browse):
    asked = []
    browse.confirm = lambda title, text: asked.append((title, text)) or True
    browse.set_view("review")
    for _ in range(3):
        review_list.go(browse)
    actions(row(browse, ("task", WALKTHROUGH)))["Close"]()
    assert asked[0][0] == "Close all 3"
    m = Model(browse.conn)
    assert m.task(WALKTHROUGH).state == "Closed" and all(m.task(x).state == "Closed" for x in m.children_of(WALKTHROUGH))
    picked = []
    browse.run_menu = lambda menu, at: picked.append([a.text() for a in menu.actions()]) or menu.actions()[2].trigger()
    actions(row(browse, ("task", HOLIDAY)))["Review every…"]()
    assert picked[0] == ["As Settings has it (every week)", "Every week", "Every 2 weeks", "Every 4 weeks", "Never"]
    assert Model(browse.conn).task(HOLIDAY).review_every == 2
    assert any(e.field == "Review every" and e.to_value == "Every 2 weeks" for e in Model(browse.conn).status_log_of(HOLIDAY))


def test_done_says_what_the_review_did_and_plans_next_week(browse, ctx, clock):
    browse.set_view("review")
    browse.set_view("today")
    assert "Weekly review" in browse.tree.topLevelItem(0).data(0, HTML_ROLE)  # Friday: Today's first line
    assert list(actions(browse.tree.topLevelItem(0))) == ["Carry on"]
    browse.set_view("review")
    for _ in range(3):
        review_list.go(browse)
    clock["now"] = datetime(2026, 10, 9, 9, 20)
    review_list.mark_reviewed(browse)
    review_list.go(browse)
    assert step(browse) == "done"
    texts = [i.data(0, HTML_ROLE) for i in browse.tree.items()]
    assert any("Reviewed 1." in t for t in texts) and any("since you started it at 09:00" in t for t in texts)
    assert bar(browse) == ["Back", "Plan next week"]
    s = review_list.session(browse)
    assert s.finished == "2026-10-09 09:20:00"
    browse.set_view("today")
    assert "Weekly review" not in (browse.tree.topLevelItem(0).data(0, HTML_ROLE) or "")  # finished: the line goes
    browse.set_view("review")
    review_list.goto(browse, 6)
    next(b for b in browse.filters.findChildren(QPushButton) if b.text() == "Plan next week").click()
    assert browse.view == "priorities"


def test_todays_line_is_only_on_the_review_day(browse, ctx, clock):
    clock["now"] = datetime(2026, 10, 8, 9, 0)  # Thursday
    browse.set_view("today")
    assert "Weekly review" not in (browse.tree.topLevelItem(0).data(0, HTML_ROLE) or "")
    ctx.settings.review_day = "Thu"
    browse.render_list()
    first = browse.tree.topLevelItem(0)
    assert "Weekly review" in first.data(0, HTML_ROLE) and first.data(0, KEY_ROLE) is None
    actions(first)["Start"]()
    assert browse.view == "review" and step(browse) == "unfiled"


def test_settings_card_saves_the_review_settings(browse, ctx):
    browse.set_view("settings")
    sv = browse.settings_view
    sv.review_day.setCurrentIndex(sv.review_day.findData("Mon"))
    sv.review_weeks.setCurrentIndex(sv.review_weeks.findData(2))
    sv.quiet_days.setValue(30)
    changed = sv.save()
    assert set(changed) == {"review_day", "review_weeks", "quiet_days"}
    loaded = Settings.load(ctx.data_root)
    assert (loaded.review_day, loaded.review_weeks, loaded.quiet_days) == ("Mon", 2, 30)


def test_edit_task_sets_review_every(browse):
    dialog = TaskEditDialog(browse, browse.model(), REACTOR, browse._label_options, browse._people_options, review_weeks=2)
    assert dialog.review_every.itemText(0) == "As Settings has it (every 2 weeks)"
    assert dialog.values()["review_every"] is None
    dialog.review_every.setCurrentIndex(4)  # Never
    assert dialog.values()["review_every"] == 0
    assert browse.save_task_edit(REACTOR, dialog.values())
    assert Model(browse.conn).task(REACTOR).review_every == 0
    sub = TaskEditDialog(browse, browse.model(), RIGGING, browse._label_options, browse._people_options)
    assert sub.review_every.itemText(0) == "Not on its own"
    tasks.update_task(browse.conn, browse.ctx.settings, RIGGING, at=FRI, via="test", review_every=4)
    again = TaskEditDialog(browse, browse.model(), RIGGING, browse._label_options, browse._people_options)
    assert again.review_every.currentData() == 4 and not again.more.isHidden()  # More options opens for it
