"""Involvement (release 5.47; the task templates design, decision 196): how much of a role's hours land on one person. The rules,
capacity, the pages, templates, and the chip box on a form."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QToolButton  # noqa: E402

from docrepo import capacity, planning, tasks, template_pages, templates  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import Pages as DetailPages  # noqa: E402
from docrepo.model import Model, load_tasks  # noqa: E402
from docrepo.pages import Pages  # noqa: E402
from docrepo.stories import Stories  # noqa: E402
from docrepo.tasks import TaskError  # noqa: E402
from docrepo.templates import Choice, Library  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_edit import QuickEdit  # noqa: E402
from docrepo.ui.task_forms import PersonChip, TaskEditDialog, people_chips  # noqa: E402
from docrepo.ui.templates_view import MakeTasksDialog, RowDialog  # noqa: E402
from docrepo.ui.widgets import Chip  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")
PRIYA, TOM, MIKE = "P002", "P003", "P004"
QUARTER = {("assignee", TOM): 25}
ROW = {"title": "Trial execution window", "inherit_labels": True, "assignees": [PRIYA, TOM], "assignee_hours": 12, "involvement": QUARTER}


def task(conn, **values) -> str:
    return tasks.create_task(conn, SETTINGS, title="Trial execution window", at=NOW, created_by="Browse tool", **values)


def get(conn, task_id: str):
    return load_tasks(conn, [task_id])[task_id]


def change(conn, task_id: str, **values) -> list[str]:
    return [f"{c.field}: {c.from_value} → {c.to_value}" for c in tasks.update_task(conn, SETTINGS, task_id, at=NOW, via="Browse tool", **values)]


def hours_of(conn, task_id: str) -> dict[str, float]:
    rows = conn.execute("SELECT person, sum(hours) FROM work_calendar WHERE task = ? GROUP BY person", (task_id,))
    return {r[0]: round(r[1], 6) for r in rows}


def spread(conn, **values) -> str:
    return task(conn, start="2026-11-02", due="2026-11-06", **values)


def sentences(conn, task_id: str) -> list[str]:
    m = Model(conn)
    stories = Stories(m, TODAY, lambda _: "")
    return [stories.field_sentence(e) for e in m.status_log_of(task_id)]


# ---- the rules ----
def test_the_designs_example(sample_conn):
    """On 12 h in all: Priya at 100% has 12 h, Tom at 25% has 3 h and Mike at 50% has 6 h. It isn't a split."""
    t = spread(sample_conn, assignees=[PRIYA, TOM, MIKE], assignee_hours=12, involvement={("assignee", TOM): 25, ("assignee", MIKE): 50})
    assert hours_of(sample_conn, t) == {PRIYA: 12, TOM: 3, MIKE: 6}
    assert get(sample_conn, t).involvement == {("assignee", TOM): 25, ("assignee", MIKE): 50}
    days = sample_conn.execute("SELECT date, hours FROM work_calendar WHERE task = ? AND person = ? ORDER BY date", (t, TOM)).fetchall()
    assert len(days) == 5 and all(abs(d["hours"] - 0.6) < 1e-9 for d in days)


def test_someone_in_both_roles_has_one_for_each(sample_conn):
    t = spread(sample_conn, leads=[TOM], lead_hours=10, assignees=[TOM], assignee_hours=20, involvement={("lead", TOM): 50, ("assignee", TOM): 25})
    assert hours_of(sample_conn, t) == {TOM: 10}
    x = get(sample_conn, t)
    assert (x.share("lead", TOM), x.share("assignee", TOM)) == (50, 25)


def test_100_is_the_default_and_isnt_kept(sample_conn):
    t = spread(sample_conn, assignees=[TOM], assignee_hours=12, involvement={("assignee", TOM): 100})
    assert get(sample_conn, t).involvement == {} and get(sample_conn, t).share("assignee", TOM) == 100
    assert hours_of(sample_conn, t) == {TOM: 12}
    assert change(sample_conn, t, involvement={("assignee", TOM): 100}) == []


def test_a_person_at_0_has_no_hours_and_the_task_is_still_estimated(sample_conn):
    t = spread(sample_conn, assignees=[TOM], assignee_hours=12, involvement={("assignee", TOM): 0})
    assert hours_of(sample_conn, t) == {}
    assert t not in capacity.unplaced(Model(sample_conn), TODAY, SETTINGS)[0]


@pytest.mark.parametrize("share", [101, -1, 2.5, "a lot"])
def test_involvement_is_a_whole_number_from_0_to_100(sample_conn, share):
    t = spread(sample_conn, assignees=[TOM], assignee_hours=12)
    with pytest.raises(TaskError, match="whole number from 0 to 100"):
        change(sample_conn, t, involvement={("assignee", TOM): share})
    assert get(sample_conn, t).involvement == {}


def test_a_change_is_logged_by_name_and_capacity_follows(sample_conn):
    t = spread(sample_conn, assignees=[PRIYA, TOM], assignee_hours=12)
    assert change(sample_conn, t, involvement=QUARTER) == ["Tom Becker's involvement: 100% → 25%"]
    assert hours_of(sample_conn, t) == {PRIYA: 12, TOM: 3}
    assert "Tom Becker's involvement 100% → 25%." in sentences(sample_conn, t)
    assert change(sample_conn, t, involvement={}) == ["Tom Becker's involvement: 25% → 100%"]
    assert hours_of(sample_conn, t) == {PRIYA: 12, TOM: 12}


def test_someone_kept_on_keeps_theirs_and_someone_taken_off_loses_it(sample_conn):
    t = spread(sample_conn, assignees=[PRIYA, TOM], assignee_hours=12, involvement=QUARTER)
    lines = change(sample_conn, t, assignees=[TOM, MIKE])  # Update captures and Edit selected change the people and no more
    assert lines == ["Assignees: Priya Shah, Tom Becker → Tom Becker, Mike Ortiz"]
    assert get(sample_conn, t).involvement == QUARTER and hours_of(sample_conn, t) == {TOM: 3, MIKE: 12}
    change(sample_conn, t, assignees=[MIKE])
    change(sample_conn, t, assignees=[MIKE, TOM])
    assert get(sample_conn, t).involvement == {}  # back at 100%


def test_other_changes_leave_it_alone(sample_conn):
    t = spread(sample_conn, assignees=[TOM], assignee_hours=12, involvement=QUARTER)
    change(sample_conn, t, assignee_hours=20, title="Trial window")
    assert get(sample_conn, t).involvement == QUARTER and hours_of(sample_conn, t) == {TOM: 5}


def test_a_rate_is_shared_the_same_way(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=[TOM], assignee_per_day=6, involvement=QUARTER)
    assert get(sample_conn, t).assignee_hours == 30
    assert hours_of(sample_conn, t) == {TOM: 7.5}


# ---- the pages ----
def test_task_md_and_the_task_page_show_each_persons_own_hours(sample_conn):
    t = spread(sample_conn, assignees=[PRIYA, TOM], assignee_hours=12, involvement=QUARTER)
    m = Model(sample_conn)
    assert "| Assignees | Priya Shah (12 h), Tom Becker (3 h, 25%) |" in Pages(m, TODAY, NOW).task_page(m.task(t))
    who = DetailPages(m, TODAY, lambda _: "").who_rows(m.task(t))[0][1]
    assert "12 h" in who and "3 h · 25%" in who


def test_the_pages_show_a_share_with_no_hours(sample_conn):
    t = task(sample_conn, leads=[TOM], involvement={("lead", TOM): 25})
    m = Model(sample_conn)
    assert "| Lead | Tom Becker (25%) |" in Pages(m, TODAY, NOW).task_page(m.task(t))
    assert "25%" in DetailPages(m, TODAY, lambda _: "").who_rows(m.task(t))[0][1]


def test_tasks_at_100_read_as_they_did(sample_conn):
    t = spread(sample_conn, assignees=[TOM], assignee_hours=12)
    m = Model(sample_conn)
    assert "| Assignees | Tom Becker (12 h) |" in Pages(m, TODAY, NOW).task_page(m.task(t))
    assert "%" not in DetailPages(m, TODAY, lambda _: "").who_rows(m.task(t))[0][1]


# ---- templates ----
@pytest.fixture
def trial(sample_conn):
    top = templates.new_template(sample_conn, "Product trial", NOW)
    window = templates.add_row(sample_conn, SETTINGS, top, ROW, NOW)[0]
    return sample_conn, top, window


def made(conn, top: int, name: str = "Trial 1", choices: dict | None = None) -> str:
    """The window's task, in a new tree."""
    return templates.make_tasks(conn, SETTINGS, top, name, None, choices or {}, NOW)[1]


def test_a_row_holds_it_and_its_page_says_so(trial):
    conn, _, window = trial
    lib = Library(conn)
    assert lib.rows[window].involvement == QUARTER
    assert "25%" in template_pages.row_page(lib, Model(conn), window, TODAY)


def test_a_row_only_keeps_shares_for_its_people(trial):
    conn, _, window = trial
    templates.apply_row(conn, SETTINGS, window, {**ROW, "assignees": [PRIYA]}, NOW)
    assert Library(conn).rows[window].involvement == {}


def test_make_tasks_copies_it_and_the_field_links(trial):
    conn, top, window = trial
    t = made(conn, top)
    assert get(conn, t).involvement == QUARTER
    assert hours_of(conn, t) == {} and get(conn, t).assignee_hours == 12  # no dates yet
    assert conn.execute("SELECT 1 FROM task_links WHERE task = ? AND field = 'assignees'", (t,)).fetchone()


def test_make_tasks_with_other_people_keeps_shares_for_those_retained(trial):
    conn, top, window = trial
    t = made(conn, top, choices={window: Choice(assignees=[TOM, MIKE])})
    assert get(conn, t).involvement == QUARTER and get(conn, t).assignees == [TOM, MIKE]
    assert not conn.execute("SELECT 1 FROM task_links WHERE task = ? AND field = 'assignees'", (t,)).fetchone()


def test_a_share_on_the_row_reaches_the_tasks_following_it(trial):
    conn, top, window = trial
    t = made(conn, top)
    changed = {**ROW, "involvement": {("assignee", TOM): 50}}
    plan = templates.preview_row(conn, SETTINGS, window, changed, NOW)
    assert plan.changed == ["assignees"]
    item = plan.items[0]
    assert "Tom Becker's involvement 25% → 50%" in item.lines
    assert (item.work_before, item.work_after) == (15, 18)
    assert get(conn, t).share("assignee", TOM) == 25  # only a preview
    templates.apply_row(conn, SETTINGS, window, changed, NOW)
    assert get(conn, t).share("assignee", TOM) == 50
    assert conn.execute("SELECT 1 FROM task_links WHERE task = ? AND field = 'assignees'", (t,)).fetchone()
    assert "Tom Becker's involvement 25% → 50% · Template: Product trial." in sentences(conn, t)


def test_a_rows_share_doesnt_touch_the_other_role(sample_conn):
    top = templates.new_template(sample_conn, "Product trial", NOW)
    window = templates.add_row(sample_conn, SETTINGS, top, {"title": "Window", "inherit_labels": True, "leads": [TOM], "assignees": [TOM], "assignee_hours": 8}, NOW)[0]
    t = made(sample_conn, top)
    tasks.update_task(sample_conn, SETTINGS, t, at=NOW, via="Browse tool", involvement={("lead", TOM): 50})  # ends the lead's link
    templates.apply_row(sample_conn, SETTINGS, window, {"title": "Window", "inherit_labels": True, "leads": [TOM], "assignees": [TOM], "assignee_hours": 8,
                                                        "involvement": {("assignee", TOM): 25}}, NOW)
    assert get(sample_conn, t).involvement == {("lead", TOM): 50, ("assignee", TOM): 25}


def test_setting_a_tasks_own_share_ends_the_link_and_the_preview_says_so(trial):
    conn, top, window = trial
    t = made(conn, top)
    lines = change(conn, t, involvement={("assignee", TOM): 75})
    assert "Tom Becker's involvement: 25% → 75%" in lines and any(x.startswith("Template link") for x in lines)
    assert not conn.execute("SELECT 1 FROM task_links WHERE task = ? AND field = 'assignees'", (t,)).fetchone()
    plan = templates.preview_row(conn, SETTINGS, window, {**ROW, "involvement": {("assignee", TOM): 50}}, NOW)
    assert not plan.items and "Tom Becker 75%" in plan.not_changing[0].text


def test_a_closed_task_keeps_its_share(trial):
    conn, top, window = trial
    t = made(conn, top)
    change(conn, t, state="Closed")
    templates.apply_row(conn, SETTINGS, window, {**ROW, "involvement": {("assignee", TOM): 50}}, NOW)
    assert get(conn, t).share("assignee", TOM) == 25


def test_save_as_template_carries_it(sample_conn):
    t = spread(sample_conn, assignees=[PRIYA, TOM], assignee_hours=12, involvement=QUARTER)
    top = templates.save_as_template(sample_conn, SETTINGS, t, "Pattern", False, NOW)
    assert Library(sample_conn).rows[top].involvement == QUARTER


# ---- Quick edit's numbers ----
def test_quick_edits_total_counts_shares():
    v = planning.Values(assignees=[PRIYA, TOM], assignee_hours=12, involvement=dict(QUARTER))
    assert planning.total_hours(v) == 15
    assert planning.edit_values(v)["involvement"] == QUARTER
    assert v.copy().involvement == QUARTER and v.copy().involvement is not v.involvement


# ---- the forms ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    w = BrowseWindow(ctx)
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    w.deleteLater()


def form(browse, task_id) -> TaskEditDialog:
    return TaskEditDialog(browse, browse.model(), task_id, browse._label_options, browse._people_options, reference_fields=(),
                          link=browse.templates.link_of(task_id), workdays=browse._workdays(), today=TODAY)


def chip_of(picker, value: str) -> PersonChip:
    return next(picker._flow.itemAt(i).widget() for i in range(picker._flow.count())
                if isinstance(picker._flow.itemAt(i).widget(), PersonChip) and picker._flow.itemAt(i).widget().value == value)


def chip_words(picker, value: str) -> list[str]:
    return [x.text() for x in chip_of(picker, value).findChildren(QLabel)]


def test_a_chip_opens_its_box_and_says_what_a_share_comes_to(browse):
    t = spread(browse.conn, assignees=[PRIYA, TOM], assignee_hours=12)
    browse.refresh()
    d = form(browse, t)
    assert d.assignees.share_box.isHidden()
    QTest.keyClick(chip_of(d.assignees, TOM), Qt.Key.Key_F2)
    box = d.assignees.share_box
    assert not box.isHidden() and box.name.text() == "Tom Becker" and box.isWindow()  # a popup: it takes no room in the form
    assert d.assignees.spin.value() == 100 and box.says.text() == "= 12 h of 12 h"
    d.assignees.spin.setValue(25)
    assert box.says.text() == "= 3 h of 12 h"
    assert chip_words(d.assignees, TOM) == ["Tom Becker", "25%"] and chip_words(d.assignees, PRIYA) == ["Priya Shah"]
    assert "Tom Becker 3 h" in d.asg_unit.line.text()
    assert d.values()["involvement"] == QUARTER
    d.assignees.close_share()


def test_double_clicking_a_chip_opens_its_box(browse):
    t = spread(browse.conn, assignees=[TOM], assignee_hours=12)
    browse.refresh()
    d = form(browse, t)
    QTest.mouseDClick(chip_of(d.assignees, TOM), Qt.MouseButton.LeftButton)
    assert not d.assignees.share_box.isHidden() and d.assignees.editing == TOM
    d.assignees.close_share()


@pytest.mark.parametrize("key, share", [(Qt.Key.Key_Return, 40), (Qt.Key.Key_Enter, 40), (Qt.Key.Key_F2, 40), (Qt.Key.Key_Escape, 25)])
def test_the_boxs_keys_close_it_and_not_the_form(browse, key, share):
    t = spread(browse.conn, assignees=[TOM], assignee_hours=12, involvement=QUARTER)
    browse.refresh()
    d = form(browse, t)
    d.show()
    d.assignees.open_share(TOM)
    d.assignees.spin.setValue(40)
    QTest.keyClick(d.assignees.spin, key)
    assert d.assignees.share_box.isHidden() and d.isVisible() and d.result() == 0
    assert d.assignees.share(TOM) == share and d.assignees.editing is None  # Esc puts back the number it opened with
    d.hide()
    d.deleteLater()


def test_a_click_elsewhere_keeps_the_number(browse):
    t = spread(browse.conn, assignees=[TOM], assignee_hours=12)
    browse.refresh()
    d = form(browse, t)
    d.assignees.open_share(TOM)
    d.assignees.spin.setValue(40)
    d.assignees.share_box.hide()  # what Qt does to a popup on a click elsewhere
    assert d.assignees.editing is None and d.assignees.share(TOM) == 40
    d.assignees.spin.setValue(60)  # nothing's open, so this changes no one
    assert d.assignees.share(TOM) == 40


def test_with_no_hours_the_box_says_of_this_roles_hours(browse):
    t = spread(browse.conn, assignees=[TOM])
    browse.refresh()
    d = form(browse, t)
    d.assignees.open_share(TOM)
    assert d.assignees.share_box.says.text() == "of this role's hours"
    d.assignees.spin.setValue(25)
    assert "Tom Becker 25%" in d.asg_unit.line.text()
    d.assignees.close_share()


def test_each_role_has_its_own_box_and_share(browse):
    t = spread(browse.conn, leads=[TOM], lead_hours=8, assignees=[TOM], assignee_hours=12)
    browse.refresh()
    d = form(browse, t)
    d.leads.open_share(TOM)
    d.leads.spin.setValue(50)
    assert d.leads.share_box.says.text() == "= 4 h of 8 h"
    d.leads.close_share()
    assert d.values()["involvement"] == {("lead", TOM): 50}


def test_saving_the_form_saves_the_share(browse):
    t = spread(browse.conn, assignees=[PRIYA, TOM], assignee_hours=12)
    browse.refresh()
    d = form(browse, t)
    d.assignees.open_share(TOM)
    d.assignees.spin.setValue(25)
    d.assignees.close_share()
    assert d.changed()
    browse.save_task_edit(t, d.values())
    assert get(browse.conn, t).involvement == QUARTER and hours_of(browse.conn, t) == {PRIYA: 12, TOM: 3}
    again = form(browse, t)
    assert chip_words(again.assignees, TOM) == ["Tom Becker", "25%"]
    assert not again.changed()


def test_taking_someone_off_drops_their_share(browse):
    t = spread(browse.conn, assignees=[PRIYA, TOM], assignee_hours=12, involvement=QUARTER)
    browse.refresh()
    d = form(browse, t)
    d.assignees.open_share(TOM)
    d.assignees.remove(1)
    assert d.assignees.shares == {} and d.assignees.share_box.isHidden() and d.values()["involvement"] == {}


def test_someone_new_can_have_a_share(browse):
    t = spread(browse.conn, assignees=[TOM], assignee_hours=12)
    browse.refresh()
    d = form(browse, t)
    d.assignees.add(Chip("Dana Reyes", "Dana Reyes", new=True))
    d.assignees.open_share("Dana Reyes")
    d.assignees.spin.setValue(50)
    d.assignees.close_share()
    browse.save_task_edit(t, d.values())
    x = get(browse.conn, t)
    dana = next(p for p in x.assignees if p != TOM)
    assert browse.model().person_name(dana) == "Dana Reyes" and x.involvement == {("assignee", dana): 50}


def test_a_different_share_warns_on_the_mark_and_the_back_mark_restores_it(browse):
    conn = browse.conn
    top = templates.new_template(conn, "Product trial", NOW)
    templates.add_row(conn, SETTINGS, top, ROW, NOW)
    t = made(conn, top)
    browse.refresh()
    d = form(browse, t)
    d.show()
    mark = d.marks["assignees"]
    assert mark.following and mark.mark.text() == ""
    d.assignees.open_share(TOM)
    d.assignees.spin.setValue(75)
    d.assignees.close_share()
    assert mark.leaving.isVisible() and mark.mark.text() == "Template: Priya Shah, Tom Becker 25% ↺"
    assert "assignees" not in d.values()["follow"]
    mark.mark.click()
    assert d.assignees.stated() == [(PRIYA, 100), (TOM, 25)] and mark.following and mark.mark.text() == ""
    assert "assignees" in d.values()["follow"] and not d.changed()
    d.hide()
    d.deleteLater()


def test_a_row_form_holds_shares(browse):
    d = RowDialog(browse, browse.model(), None, browse._label_options, browse._people_options, "Add a subtask")
    d.title_box.setText("Window")
    d.assignees.set_chips(people_chips(browse.model(), [TOM]))
    d.asg_hours.setText("12")
    d.assignees.open_share(TOM)
    d.assignees.spin.setValue(25)
    assert d.assignees.share_box.says.text() == "= 3 h of 12 h" and d.values()["involvement"] == QUARTER
    d.assignees.close_share()


def test_quick_edit_shows_it_counts_it_and_keeps_it(ctx):
    t = spread(ctx.conn, assignees=[PRIYA, TOM], assignee_hours=12, involvement=QUARTER)
    w = QuickEdit(ctx, t)
    assert w.total.text().startswith("15 h in all")
    chips = {b.toolTip(): b.text() for b in w.rows["assignees"].findChildren(QToolButton) if b.objectName() == "chip"}
    assert chips["Take Tom Becker off"].endswith(" 25% ×") and chips["Take Priya Shah off"].endswith("  ×")  # the names as there's room
    w.hours["assignee_hours"].setText("20")
    w._field_edited("assignee_hours")
    w.save()
    assert get(ctx.conn, t).involvement == QUARTER and hours_of(ctx.conn, t) == {PRIYA: 20, TOM: 5}
    w.deleteLater()


def test_quick_edit_shortens_a_name_too_long_for_its_chip(ctx):
    conn = ctx.conn
    conn.execute("INSERT INTO people (id, name) VALUES ('P900', 'Alexandria Montgomery-Fitzgerald')")
    t = spread(conn, assignees=["P900"], assignee_hours=12, involvement={("assignee", "P900"): 25})
    w = QuickEdit(ctx, t)
    chip = next(b for b in w.rows["assignees"].findChildren(QToolButton) if b.objectName() == "chip" and b.text().endswith("×"))
    assert chip.text().startswith("A") and "…" in chip.text() and chip.text().endswith(" 25% ×")
    assert "Alexandria Montgomery-Fitzgerald" in chip.toolTip()
    w.deleteLater()


def test_make_tasks_says_who_has_a_share(browse):
    conn = browse.conn
    top = templates.new_template(conn, "Product trial", NOW)
    window = templates.add_row(conn, SETTINGS, top, ROW, NOW)[0]
    browse.refresh()
    d = MakeTasksDialog(browse, browse.model(), Library(conn), top, browse._people_options, lambda: None, browse._workdays())
    lines = [x for x in d.lines if x.row.id == window]
    assert [c.label for c in lines[0].people.chips()] == ["Priya Shah", "Tom Becker 25%"]
    d.deleteLater()
