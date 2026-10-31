"""Hours a week (release 5.49; the task templates design, decision 260): a third unit beside h in all and h a day. The rules, capacity,
the pages, templates, and every form with hours."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, planning, schedule, tasks, template_pages, templates  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import Pages as DetailPages  # noqa: E402
from docrepo.model import Model, load_tasks  # noqa: E402
from docrepo.stories import Stories  # noqa: E402
from docrepo.tasks import TaskError  # noqa: E402
from docrepo.templates import Library  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_edit import QuickEdit  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402
from docrepo.ui.templates_view import MakeTasksDialog, RowDialog  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")
WEEK = range(5)
PRIYA, TOM = "P002", "P003"
ROW = {"title": "Supplier follow-up", "inherit_labels": True, "duration": 30, "assignees": [PRIYA], "assignee_per_week": 3}


def task(conn, **values) -> str:
    return tasks.create_task(conn, SETTINGS, title="Supplier follow-up", at=NOW, created_by="Browse tool", **values)


def get(conn, task_id: str):
    return load_tasks(conn, [task_id])[task_id]


def change(conn, task_id: str, **values) -> list[str]:
    return [f"{c.field}: {c.from_value} → {c.to_value}" for c in tasks.update_task(conn, SETTINGS, task_id, at=NOW, via="Browse tool", **values)]


def lines_of(conn, task_id: str) -> list[str]:
    m = Model(conn)
    stories = Stories(m, TODAY, lambda _: "")
    return [stories.field_sentence(e) for e in m.status_log_of(task_id)]


# ---- the rules ----
def test_a_week_is_the_workdays_in_settings_or_7_through_weekends():
    assert schedule.week_of(WEEK) == 5 and schedule.week_of(WEEK, True) == 7
    assert schedule.week_of(range(4)) == 4


@pytest.mark.parametrize("days, total", [(30, 18), (5, 3), (7, 4.2), (1, 0.6)])
def test_the_total_is_the_rate_times_the_weeks_part_weeks_counted(sample_conn, days, total):
    t = task(sample_conn, start="2026-11-02", duration=days, assignees=[PRIYA], assignee_per_week=3)
    assert get(sample_conn, t).assignee_hours == total
    assert tasks.stated(get(sample_conn, t), "assignee_hours") == ("a week", 3)
    assert get(sample_conn, t).rate_of("assignee") == (3, "week")


def test_runs_through_weekends_makes_a_week_7_days(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=14, calendar_days=True, assignees=[PRIYA], assignee_per_week=3)
    assert get(sample_conn, t).assignee_hours == 6


def test_plain_dates_give_the_length_too(sample_conn):
    t = task(sample_conn, start="2026-11-02", due="2026-11-13", assignees=[PRIYA], assignee_per_week=5)
    assert get(sample_conn, t).assignee_hours == 10


def test_the_total_follows_the_length_and_the_log_says_both(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_week=3)
    assert get(sample_conn, t).assignee_hours == 6
    change(sample_conn, t, duration=20)
    assert get(sample_conn, t).assignee_hours == 12
    assert "Assignee hours 6 → 12." in lines_of(sample_conn, t)


def test_a_role_has_one_rate_at_most(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_day=2)
    assert get(sample_conn, t).assignee_hours == 20
    change(sample_conn, t, assignee_per_week=5)
    x = get(sample_conn, t)
    assert (x.assignee_per_day, x.assignee_per_week, x.assignee_hours) == (None, 5, 10)
    change(sample_conn, t, assignee_per_day=4)
    x = get(sample_conn, t)
    assert (x.assignee_per_day, x.assignee_per_week, x.assignee_hours) == (4, None, 40)


def test_a_total_typed_over_a_week_rate_ends_it(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_week=3)
    change(sample_conn, t, assignee_hours=40)
    x = get(sample_conn, t)
    assert (x.assignee_per_week, x.assignee_hours) == (None, 40)


def test_hours_values_says_what_a_form_means():
    assert tasks.hours_values("lead_hours", "week", 3) == {"lead_per_week": 3, "lead_per_day": None}
    assert tasks.hours_values("lead_hours", "day", 3) == {"lead_per_day": 3, "lead_per_week": None}
    assert tasks.hours_values("lead_hours", "all", 3) == {"lead_hours": 3, "lead_per_day": None, "lead_per_week": None}
    assert tasks.hours_values("lead_hours", "week", None) == {"lead_hours": None, "lead_per_day": None, "lead_per_week": None}


def test_with_no_length_there_is_no_total(sample_conn):
    t = task(sample_conn, assignees=[PRIYA], assignee_per_week=3)
    assert get(sample_conn, t).assignee_hours is None and get(sample_conn, t).assignee_per_week == 3


def test_a_routine_task_has_no_rate(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_week=3)
    change(sample_conn, t, recurrence="Weekly")
    x = get(sample_conn, t)
    assert (x.assignee_per_week, x.duration) == (None, None) and x.assignee_hours == 6  # the total stays, as each time


def test_the_rate_can_be_given_for_a_lead(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, leads=[TOM], lead_per_week=2)
    assert get(sample_conn, t).lead_hours == 4 and get(sample_conn, t).rate_of("lead") == (2, "week")


def test_a_rate_cant_be_negative(sample_conn):
    with pytest.raises(TaskError):
        task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_week=-1)


# ---- capacity ----
def test_capacity_spreads_it_evenly(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=30, assignees=[PRIYA], assignee_per_week=3)
    days = sample_conn.execute("SELECT date, hours FROM work_calendar WHERE task = ? AND person = ? ORDER BY date", (t, PRIYA)).fetchall()
    assert len(days) == 30 and all(abs(d["hours"] - 0.6) < 1e-9 for d in days)
    assert round(sum(d["hours"] for d in days), 6) == 18


def test_involvement_shares_it_as_any_hours(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA, TOM], assignee_per_week=5, involvement={("assignee", TOM): 25})
    rows = dict(sample_conn.execute("SELECT person, sum(hours) FROM work_calendar WHERE task = ? GROUP BY person", (t,)).fetchall())
    assert (round(rows[PRIYA], 6), round(rows[TOM], 6)) == (10, 2.5)
    assert capacity.task_rows(get(sample_conn, t), TODAY, SETTINGS)


# ---- the pages and the log ----
def test_the_task_page_says_so(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=30, assignees=[PRIYA], assignee_per_week=3)
    m = Model(sample_conn)
    assert "18 h · 3 h a week" in DetailPages(m, TODAY, lambda _: "").who_rows(m.task(t))[0][1]


def test_the_task_page_asks_for_a_length(sample_conn):
    t = task(sample_conn, assignees=[PRIYA], assignee_per_week=3)
    m = Model(sample_conn)
    assert "3 h a week, needs a length" in DetailPages(m, TODAY, lambda _: "").who_rows(m.task(t))[0][1]


def test_the_log_names_the_rate(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA])
    change(sample_conn, t, assignee_per_week=3)
    assert "Assignee hours a week set to 3." in lines_of(sample_conn, t)
    change(sample_conn, t, assignee_per_week=4)
    assert "Assignee hours a week 3 → 4." in lines_of(sample_conn, t)


# ---- templates ----
@pytest.fixture
def trial(sample_conn):
    top = templates.new_template(sample_conn, "Product trial", NOW)
    row = templates.add_row(sample_conn, SETTINGS, top, ROW, NOW)[0]
    return sample_conn, top, row


def made(conn, top: int, name: str = "Trial 1") -> str:
    return templates.make_tasks(conn, SETTINGS, top, name, None, {}, NOW)[1]


def links_of(conn, task_id: str) -> set[str]:
    return {r["field"] for r in conn.execute("SELECT field FROM task_links WHERE task = ?", (task_id,))}


def test_a_row_holds_it_and_says_so(trial):
    conn, top, row = trial
    lib = Library(conn)
    r = lib.rows[row]
    assert (r.assignee_per_week, r.assignee_hours) == (3, None)
    assert templates.summary(r) == "30 days · 3 h a week"
    assert "3 h a week = 18 h each" in template_pages.row_page(lib, Model(conn), row, TODAY)


def test_a_shorter_working_week_comes_to_more():
    assert tasks.rate_total(("a week", 3), 30, range(4)) == 22.5


def test_a_row_has_one_rate_at_most(trial):
    conn, _, row = trial
    templates.apply_row(conn, SETTINGS, row, {**ROW, "assignee_per_day": 2}, NOW)
    r = Library(conn).rows[row]
    assert (r.assignee_per_day, r.assignee_per_week) == (2, None)


def test_make_tasks_copies_it_and_the_hours_link(trial):
    conn, top, _ = trial
    t = made(conn, top)
    x = get(conn, t)
    assert (x.assignee_per_week, x.duration) == (3, 30) and "assignee_hours" in links_of(conn, t)


def test_a_worked_out_total_doesnt_end_the_link(trial):
    conn, top, _ = trial
    t = made(conn, top)
    change(conn, t, start="2026-11-02", duration=10)  # its own Duration, which is a different number of days
    assert get(conn, t).assignee_hours == 6 and "assignee_hours" in links_of(conn, t)


def test_a_different_rate_on_the_row_reaches_the_task(trial):
    conn, top, row = trial
    t = made(conn, top)
    change(conn, t, start="2026-11-02")
    changed = {**ROW, "assignee_per_week": 5}
    plan = templates.preview_row(conn, SETTINGS, row, changed, NOW)
    assert plan.items[0].lines and (plan.items[0].work_before, plan.items[0].work_after) == (18, 30)
    assert any("3 h a week → 5 h a week" in x for x in plan.lines)
    templates.apply_row(conn, SETTINGS, row, changed, NOW)
    assert get(conn, t).assignee_per_week == 5 and get(conn, t).assignee_hours == 30


def test_a_row_switching_to_h_a_day_clears_the_tasks_week_rate(trial):
    conn, top, row = trial
    t = made(conn, top)
    change(conn, t, start="2026-11-02")
    templates.apply_row(conn, SETTINGS, row, {**{k: v for k, v in ROW.items() if k != "assignee_per_week"}, "assignee_per_day": 1}, NOW)
    x = get(conn, t)
    assert (x.assignee_per_day, x.assignee_per_week, x.assignee_hours) == (1, None, 30)


def test_a_different_rate_on_the_task_ends_the_link(trial):
    conn, top, _ = trial
    t = made(conn, top)
    change(conn, t, assignee_per_week=4)
    assert "assignee_hours" not in links_of(conn, t)


def test_save_as_template_carries_it(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_week=3)
    top = templates.save_as_template(sample_conn, SETTINGS, t, "Pattern", False, NOW)
    assert Library(sample_conn).rows[top].assignee_per_week == 3


# ---- Quick edit's numbers ----
def test_quick_edits_values_carry_it():
    v = planning.Values(start="2026-11-02", duration=30, assignees=[PRIYA], assignee_per_week=3, leads=["P001"], lead_hours=4)
    assert planning.role_total(v, "assignee_hours") == 18 and planning.total_hours(v) == 22
    assert planning.unit_of(v, "assignee_hours") == "week" and planning.number_of(v, "assignee_hours") == 3
    values = planning.edit_values(v)
    assert values["assignee_per_week"] == 3 and values["assignee_per_day"] is None and "assignee_hours" not in values
    assert planning.total_text(planning.Values(assignees=[PRIYA], assignee_per_week=3), None) == "3 h a week, needs a length"


def test_a_total_the_box_reads_takes_a_week_rates_place():
    v = planning.shown(planning.Values(assignees=[PRIYA], assignee_per_week=3), planning.Reading(fills={"assignee_hours": 12.0}))
    assert v.assignee_hours == 12 and v.assignee_per_week is None


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


def days(dialog, text: str) -> None:
    dialog.duration.setText(text)
    dialog.duration.textEdited.emit(text)


def switch(row, index: int) -> None:
    row.unit.setCurrentIndex(index)
    row.unit.activated.emit(index)


def test_the_form_offers_it_and_says_what_it_comes_to(browse):
    t = task(browse.conn, start="2026-11-02", duration=30, assignees=[PRIYA], assignee_hours=18)
    browse.refresh()
    d = form(browse, t)
    assert [d.asg_unit.unit.itemText(i) for i in range(d.asg_unit.unit.count())] == ["h in all", "h a day", "h a week"]
    switch(d.asg_unit, 2)
    assert d.asg_hours.text() == "3"  # switching keeps the total
    assert d.asg_unit.line.text() == "= 18 h over 30 days (6 weeks)" and d.asg_unit.total() == 18
    switch(d.asg_unit, 1)
    assert d.asg_hours.text() == "0.6"
    switch(d.asg_unit, 2)
    assert d.asg_hours.text() == "3"
    switch(d.asg_unit, 0)
    assert d.asg_hours.text() == "18"


def test_a_part_week_says_so(browse):
    t = task(browse.conn, start="2026-11-02", duration=7, assignees=[PRIYA], assignee_per_week=3)
    browse.refresh()
    d = form(browse, t)
    assert d.asg_unit.unit_name() == "week" and d.asg_hours.text() == "3"
    assert d.asg_unit.line.text() == "= 4.2 h over 7 days (1.4 weeks)"


def test_one_week_is_singular(browse):
    t = task(browse.conn, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_per_week=3)
    browse.refresh()
    assert form(browse, t).asg_unit.line.text() == "= 3 h over 5 days (1 week)"


def test_the_line_follows_runs_through_weekends(browse):
    t = task(browse.conn, start="2026-11-02", duration=14, assignees=[PRIYA], assignee_per_week=3)
    browse.refresh()
    d = form(browse, t)
    assert d.asg_unit.total() == 8.4
    d.calendar.setChecked(True)
    assert d.asg_unit.total() == 6 and d.asg_unit.line.text() == "= 6 h over 14 days (2 weeks)"


def test_saving_the_form_saves_it(browse):
    t = task(browse.conn, start="2026-11-02", duration=30, assignees=[PRIYA], assignee_hours=18)
    browse.refresh()
    d = form(browse, t)
    switch(d.asg_unit, 2)
    assert d.values()["assignee_per_week"] == 3 and d.values()["assignee_per_day"] is None
    browse.save_task_edit(t, d.values())
    x = get(browse.conn, t)
    assert (x.assignee_per_week, x.assignee_hours) == (3, 18)
    again = form(browse, t)
    assert not again.changed()
    switch(again.asg_unit, 0)
    browse.save_task_edit(t, again.values())
    x = get(browse.conn, t)
    assert (x.assignee_per_week, x.assignee_hours) == (None, 18)


def test_with_no_length_switching_keeps_the_number(browse):
    t = task(browse.conn, assignees=[PRIYA], assignee_hours=3)
    browse.refresh()
    d = form(browse, t)
    switch(d.asg_unit, 2)
    assert d.asg_hours.text() == "3" and d.asg_unit.line.text() == "3 h a week, needs a length"


def test_the_mark_shows_it_and_takes_it_back(browse):
    conn = browse.conn
    top = templates.new_template(conn, "Product trial", NOW)
    templates.add_row(conn, SETTINGS, top, ROW, NOW)
    t = made(conn, top)
    browse.refresh()
    d = form(browse, t)
    d.show()
    mark = d.marks["assignee_hours"]
    assert mark.following
    d.asg_hours.setText("5")
    d.asg_hours.textEdited.emit("5")
    assert mark.leaving.isVisible() and mark.mark.text() == "Template: 3 h a week ↺"
    mark.mark.click()
    assert d.asg_unit.stated() == ("a week", 3) and mark.following
    d.hide()
    d.deleteLater()


def test_a_row_form_holds_it(browse):
    d = RowDialog(browse, browse.model(), None, browse._label_options, browse._people_options, "Add a subtask")
    d.title_box.setText("Supplier follow-up")
    days(d, "30")
    d.asg_unit.set_unit_name("week")
    d.asg_hours.setText("3")
    d.asg_hours.textEdited.emit("3")
    assert d.asg_unit.line.text() == "= 18 h over 30 days (6 weeks)"
    values = d.values()
    assert values["assignee_per_week"] == 3 and values["assignee_per_day"] is None and values["assignee_hours"] is None


def test_a_row_form_opens_on_it(browse):
    conn = browse.conn
    top = templates.new_template(conn, "Product trial", NOW)
    row = templates.add_row(conn, SETTINGS, top, ROW, NOW)[0]
    browse.refresh()
    d = RowDialog(browse, browse.model(), Library(conn).rows[row], browse._label_options, browse._people_options, "Edit row")
    assert d.asg_unit.unit_name() == "week" and d.asg_hours.text() == "3"


def test_make_tasks_says_what_it_comes_to(browse):
    conn = browse.conn
    top = templates.new_template(conn, "Product trial", NOW)
    row = templates.add_row(conn, SETTINGS, top, ROW, NOW)[0]
    browse.refresh()
    d = MakeTasksDialog(browse, browse.model(), Library(conn), top, browse._people_options, lambda: None, browse._workdays())
    line = next(x for x in d.lines if x.row.id == row)
    line.sync()
    assert line.hours.text() == "3 h a week = 18 h"
    d.deleteLater()


def test_quick_edit_has_the_unit(ctx):
    t = task(ctx.conn, start="2026-11-02", duration=30, assignees=[PRIYA], assignee_per_week=3)
    w = QuickEdit(ctx, t)
    assert w.units["assignee_hours"].currentIndex() == 2 and w.hours["assignee_hours"].text() == "3"
    assert w.total.text().startswith("18 h in all")
    w.duration.setText("10")
    w._field_edited("duration")
    assert w.total.text().startswith("6 h in all")
    w.save()
    x = get(ctx.conn, t)
    assert (x.assignee_per_week, x.assignee_hours, x.duration) == (3, 6, 10)
    w.deleteLater()


def test_quick_edit_switches_the_unit_keeping_the_total(ctx):
    t = task(ctx.conn, start="2026-11-02", duration=30, assignees=[PRIYA], assignee_hours=18)
    w = QuickEdit(ctx, t)
    w.units["assignee_hours"].setCurrentIndex(2)
    w._unit_changed("assignee_hours")
    assert w.hours["assignee_hours"].text() == "3" and w.total.text().startswith("18 h in all")
    w.units["assignee_hours"].setCurrentIndex(1)
    w._unit_changed("assignee_hours")
    assert w.hours["assignee_hours"].text() == "0.6"
    w.save()
    x = get(ctx.conn, t)
    assert (x.assignee_per_day, x.assignee_per_week, x.assignee_hours) == (0.6, None, 18)
    w.deleteLater()


def test_quick_edit_types_a_new_rate(ctx):
    t = task(ctx.conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_week=3)
    w = QuickEdit(ctx, t)
    w.hours["assignee_hours"].setText("5")
    w._field_edited("assignee_hours")
    assert w.total.text().startswith("10 h in all")
    w.save()
    assert get(ctx.conn, t).assignee_per_week == 5
    w.deleteLater()


@pytest.fixture
def capture(ctx):
    w = CaptureWindow(ctx)
    yield w
    w.deleteLater()


def test_the_capture_window_makes_a_new_task_with_it(capture):
    capture.n_duration.setText("30")
    capture.n_asg_hours.setText("3")
    capture.n_asg_row.set_unit_name("week")
    values = capture._hours_values(capture.n_lead_row, capture.n_asg_row)
    assert values["assignee_per_week"] == 3 and values["assignee_per_day"] is None and "assignee_hours" not in values
    assert capture.n_asg_row.total() == 18


def test_the_capture_windows_week_follows_its_tick(capture):
    capture.n_duration.setText("14")
    capture.n_asg_hours.setText("3")
    capture.n_asg_row.set_unit_name("week")
    assert capture.n_asg_row.total() == 8.4
    capture.n_calendar.setChecked(True)
    assert capture.n_asg_row.total() == 6


def test_a_draft_set_aside_keeps_h_a_week(capture):
    capture.n_asg_row.set_unit_name("week")
    form = capture.aside._form()
    assert form["units"]["n_asg_row"] == "week"
    capture.n_asg_row.set_unit_name("all")
    capture.aside._restore_form(form)
    assert capture.n_asg_row.unit_name() == "week"


def test_a_draft_saved_before_h_a_week_still_reads(capture):
    capture.aside._restore_form({"units": {"n_asg_row": True, "n_lead_row": False}})
    assert capture.n_asg_row.unit_name() == "day" and capture.n_lead_row.unit_name() == "all"


def test_quick_edit_clearing_a_rate_clears_it(ctx):
    t = task(ctx.conn, start="2026-11-02", duration=10, assignees=[PRIYA], assignee_per_week=3)
    w = QuickEdit(ctx, t)
    w.hours["assignee_hours"].setText("")
    w._field_edited("assignee_hours")
    w.save()
    x = get(ctx.conn, t)
    assert (x.assignee_per_week, x.assignee_hours) == (None, None)
    w.deleteLater()
