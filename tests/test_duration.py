"""Duration, Runs through weekends and hours a day (release 5.46; the task templates design, decisions 189 to 191): the rules,
capacity, templates, and every form that has them."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, edits, planning, schedule, tasks, templates  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, load_tasks  # noqa: E402
from docrepo.pages import Pages  # noqa: E402
from docrepo.stories import Stories  # noqa: E402
from docrepo.tasks import TaskError  # noqa: E402
from docrepo.templates import Choice, Library  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_edit import QuickEdit  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402
from docrepo.ui.templates_view import MakeTasksDialog, RowDialog  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")
WEEK = frozenset(range(5))
THU, FRI, SAT, MON, TUE, WED = (date(2026, 11, d) for d in (5, 6, 7, 9, 10, 11))


def task(conn, **values) -> str:
    return tasks.create_task(conn, SETTINGS, title="Trial execution window", at=NOW, created_by="Browse tool", **values)


def get(conn, task_id: str):
    return load_tasks(conn, [task_id])[task_id]


def change(conn, task_id: str, **values) -> list[str]:
    return [f"{c.field}: {c.from_value} → {c.to_value}" for c in tasks.update_task(conn, SETTINGS, task_id, at=NOW, via="Browse tool", **values)]


def dates(conn, task_id: str) -> tuple:
    t = get(conn, task_id)
    return t.start, t.due, t.duration


# ---- counting days (decision 190) ----
def test_the_designs_example():
    """A 5-day trial starting Thu 5 Nov ends Wed 11 Nov, or with the tick Mon 9 Nov."""
    assert schedule.due_after(THU, 5, WEEK) == WED
    assert schedule.due_after(THU, 5, WEEK, True) == MON
    assert schedule.start_before(WED, 5, WEEK) == THU
    assert schedule.days_in(THU, WED, WEEK) == 5 and schedule.days_in(THU, MON, WEEK, True) == 5


def test_a_start_on_a_weekend_stays_and_counts_from_monday():
    assert schedule.due_after(SAT, 1, WEEK) == MON and schedule.due_after(SAT, 2, WEEK) == TUE
    assert schedule.days_in(SAT, MON, WEEK) == 1


def test_a_span_with_no_workday_counts_its_calendar_days():
    assert schedule.days_in(SAT, date(2026, 11, 8), WEEK) == 2  # as the capacity calendar spreads its hours
    assert schedule.days_in(WED, MON, WEEK) == 0


def test_settings_workdays_count():
    four = frozenset(range(4))  # Monday to Thursday
    assert schedule.due_after(THU, 2, four) == MON


# ---- dates (decision 191) ----
def test_with_a_duration_a_date_moves_the_block(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5)
    assert dates(sample_conn, t) == ("2026-11-02", "2026-11-06", 5)
    change(sample_conn, t, start="2026-11-05")
    assert dates(sample_conn, t) == ("2026-11-05", "2026-11-11", 5)  # Due moves, Duration stays
    change(sample_conn, t, due="2026-11-20")
    assert dates(sample_conn, t) == ("2026-11-16", "2026-11-20", 5)  # Start moves
    change(sample_conn, t, duration=3)
    assert dates(sample_conn, t) == ("2026-11-16", "2026-11-18", 3)  # Due moves, Start stays


def test_with_no_start_a_duration_moves_start(sample_conn):
    t = task(sample_conn, due="2026-11-06")
    change(sample_conn, t, duration=5)
    assert dates(sample_conn, t) == ("2026-11-02", "2026-11-06", 5)


def test_clearing_either_date_clears_both_keeping_the_size(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5)
    change(sample_conn, t, due=None)
    assert dates(sample_conn, t) == (None, None, 5)
    change(sample_conn, t, start="2026-11-09")
    assert dates(sample_conn, t) == ("2026-11-09", "2026-11-13", 5)
    change(sample_conn, t, start=None)
    assert dates(sample_conn, t) == (None, None, 5)


def test_clearing_the_duration_leaves_plain_dates(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5)
    change(sample_conn, t, duration=None)
    assert dates(sample_conn, t) == ("2026-11-02", "2026-11-06", None)
    change(sample_conn, t, start="2026-11-03")
    assert dates(sample_conn, t) == ("2026-11-03", "2026-11-06", None)  # Due stays, as on any task


def test_existing_tasks_dont_change(sample_conn):
    """With no Duration typed, today's behaviour."""
    t = task(sample_conn, start="2026-11-02", due="2026-11-20")
    change(sample_conn, t, due="2026-11-27")
    assert dates(sample_conn, t) == ("2026-11-02", "2026-11-27", None)


def test_two_dates_typed_together_are_the_new_length(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5)
    change(sample_conn, t, start="2026-11-09", due="2026-11-11")
    assert dates(sample_conn, t) == ("2026-11-09", "2026-11-11", 3)


def test_runs_through_weekends_moves_due(sample_conn):
    t = task(sample_conn, start="2026-11-05", duration=5)
    assert get(sample_conn, t).due == "2026-11-11"
    change(sample_conn, t, calendar_days=True)
    assert get(sample_conn, t).due == "2026-11-09"
    logged = [e.field for e in Model(sample_conn).status_log_of(t)]
    assert "Runs through weekends" in logged and "Due" in logged


def test_a_deadline_is_never_touched(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, deadline="2026-11-06")
    change(sample_conn, t, start="2026-11-16")
    assert get(sample_conn, t).deadline == "2026-11-06"


def test_duration_is_a_whole_number_of_days(sample_conn):
    t = task(sample_conn)
    for bad in (0, -1, 1.5, "soon"):
        with pytest.raises(TaskError):
            change(sample_conn, t, duration=bad)
    change(sample_conn, t, duration="3")
    assert get(sample_conn, t).duration == 3


def test_a_duration_with_no_dates_isnt_placed(sample_conn):
    """Even with a Deadline, rather than spreading its hours from the day it was made."""
    t = task(sample_conn, duration=5, deadline="2026-11-20", assignees=["P002"], assignee_hours=10)
    m = Model(sample_conn)
    assert schedule.windows(m.task(t), date(2027, 1, 1)) == []
    assert not sample_conn.execute("SELECT 1 FROM work_calendar WHERE task = ?", (t,)).fetchone()
    assert t in capacity.unplaced(m, TODAY, SETTINGS)[1]
    change(sample_conn, t, duration=None)  # without one, its window runs to the Deadline again
    assert sample_conn.execute("SELECT 1 FROM work_calendar WHERE task = ?", (t,)).fetchone()


# ---- Plan mode ----
def test_a_bar_moved_keeps_its_days(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5)  # Mon to Fri
    tasks.update_task(sample_conn, SETTINGS, t, at=NOW, via="Browse tool", dragged=True, start="2026-11-05", due="2026-11-09")  # three days along
    assert dates(sample_conn, t) == ("2026-11-05", "2026-11-11", 5)  # across a weekend: wider, but no more work


def test_a_bar_stretched_takes_the_new_length_and_its_total_follows(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    tasks.update_task(sample_conn, SETTINGS, t, at=NOW, via="Browse tool", dragged=True, start="2026-11-02", due="2026-11-04")
    x = get(sample_conn, t)
    assert (x.start, x.due, x.duration, x.assignee_hours) == ("2026-11-02", "2026-11-04", 3, 18)
    tasks.update_task(sample_conn, SETTINGS, t, at=NOW, via="Browse tool", dragged=True, start="2026-11-02", due="2026-11-06")  # Ctrl+Z
    x = get(sample_conn, t)
    assert (x.duration, x.assignee_hours) == (5, 30)


def test_a_dropped_task_takes_its_own_duration(sample_conn):
    t = task(sample_conn, duration=3)
    tasks.update_task(sample_conn, SETTINGS, t, at=NOW, via="Browse tool", dragged=True, start="2026-11-02", due="2026-11-06")
    assert dates(sample_conn, t) == ("2026-11-02", "2026-11-04", 3)


def test_a_drag_with_no_duration_is_as_it_was(sample_conn):
    t = task(sample_conn, start="2026-11-02", due="2026-11-06")
    tasks.update_task(sample_conn, SETTINGS, t, at=NOW, via="Browse tool", dragged=True, start="2026-11-03", due="2026-11-09")
    assert dates(sample_conn, t) == ("2026-11-03", "2026-11-09", None)


# ---- hours (decisions 189 and 190) ----
def test_a_rate_makes_the_total(sample_conn):
    t = task(sample_conn, start="2026-11-05", duration=5, assignees=["P002", "P003"], assignee_per_day=6, leads=["P001"], lead_hours=4)
    x = get(sample_conn, t)
    assert (x.assignee_hours, x.assignee_per_day, x.lead_hours, x.lead_per_day) == (30, 6, 4, None)


def test_the_total_follows_the_length_and_both_lines_are_logged(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6, leads=["P001"], lead_hours=4)
    logged = change(sample_conn, t, duration=3)
    assert "Duration: 5 → 3" in logged and "Assignee hours: 30 → 18" in logged
    x = get(sample_conn, t)
    assert x.assignee_hours == 18 and x.lead_hours == 4  # h in all stays
    m = Model(sample_conn)
    words = [Stories(m, TODAY, lambda _: "").field_sentence(e) for e in m.status_log_of(t)]
    assert "Duration 5 → 3 days." in words and "Assignee hours 30 → 18." in words


def test_a_length_from_two_dates_counts_too(sample_conn):
    t = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=["P002"], assignee_per_day=2)
    assert get(sample_conn, t).assignee_hours == 10
    change(sample_conn, t, due="2026-11-13")
    assert get(sample_conn, t).assignee_hours == 20  # ten workdays


def test_a_rate_with_no_length_stays_off_capacity_until_it_has_one(sample_conn):
    t = task(sample_conn, assignees=["P002"], assignee_per_day=6)
    x = get(sample_conn, t)
    assert x.assignee_hours is None and x.assignee_per_day == 6
    assert not sample_conn.execute("SELECT 1 FROM work_calendar WHERE task = ?", (t,)).fetchone()
    assert t in capacity.unplaced(Model(sample_conn), TODAY, SETTINGS)[0]
    change(sample_conn, t, start="2026-11-02", duration=5)
    assert get(sample_conn, t).assignee_hours == 30


def test_a_total_typed_over_a_rate_ends_the_rate(sample_conn):
    """An Update capture or Quick edit's box types a total: the rate stops, and the total stays as typed."""
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    change(sample_conn, t, assignee_hours=25)
    x = get(sample_conn, t)
    assert (x.assignee_hours, x.assignee_per_day) == (25, None)
    change(sample_conn, t, duration=2)
    assert get(sample_conn, t).assignee_hours == 25


def test_hours_land_on_workdays_or_every_day(sample_conn):
    t = task(sample_conn, start="2026-11-05", duration=5, assignees=["P002"], assignee_per_day=6)
    rows = sample_conn.execute("SELECT date, hours FROM work_calendar WHERE task = ? ORDER BY date", (t,)).fetchall()
    assert [r["date"] for r in rows] == ["2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11"] and all(r["hours"] == 6 for r in rows)
    change(sample_conn, t, calendar_days=True)
    rows = sample_conn.execute("SELECT date, hours FROM work_calendar WHERE task = ? ORDER BY date", (t,)).fetchall()
    assert [r["date"] for r in rows] == ["2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09"] and all(r["hours"] == 6 for r in rows)


def test_a_routine_task_has_no_duration_or_rate(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    change(sample_conn, t, recurrence="Weekly")
    x = get(sample_conn, t)
    assert (x.duration, x.calendar_days, x.assignee_per_day) == (None, False, None) and x.assignee_hours == 30  # each time
    r = task(sample_conn, recurrence="Weekly", start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6, assignee_hours=2)
    x = get(sample_conn, r)
    assert (x.duration, x.assignee_per_day, x.assignee_hours) == (None, None, 2)


def test_the_task_page_and_task_md_say_so(sample_conn):
    from docrepo.detail import Pages as DetailPages

    t = task(sample_conn, start="2026-11-05", duration=5, assignees=["P002"], assignee_per_day=6)
    m = Model(sample_conn)
    assert "| Duration | 5 workdays |" in Pages(m, TODAY, NOW).task_page(m.task(t))
    page = DetailPages(m, TODAY, lambda _: "")
    assert ("Duration", "5 workdays") in page.when_rows(m.task(t))
    assert "30 h · 6 h a day" in page.who_rows(m.task(t))[0][1]
    change(sample_conn, t, calendar_days=True, duration=1)
    m = Model(sample_conn)
    assert "| Duration | 1 day, through weekends |" in Pages(m, TODAY, NOW).task_page(m.task(t))
    needs = task(sample_conn, assignees=["P002"], assignee_per_day=6)
    m = Model(sample_conn)
    assert "6 h a day, needs a length" in DetailPages(m, TODAY, lambda _: "").who_rows(m.task(needs))[0][1]


def test_a_task_with_no_length_says_the_same_as_ever(sample_conn):
    """The sample data's stories don't change."""
    m = Model(sample_conn)
    stories = Stories(m, TODAY, lambda _: "")
    from docrepo.model import StatusEntry

    entry = StatusEntry("T000001", "2026-10-01 09:00:00", "Assignee hours", "4", "6", "Browse tool")
    assert stories.field_sentence(entry) == "Assignee hours set to 6 h."


# ---- templates ----
def row(title: str, **values) -> dict:
    return {"title": title, "inherit_labels": True, **values}


@pytest.fixture
def trial(sample_conn):
    conn = sample_conn
    top = templates.new_template(conn, "Product trial", NOW)
    window = templates.add_row(conn, SETTINGS, top, row("Trial window", duration=5, leads=["P001"], lead_per_day=2, assignees=["P002", "P003"], assignee_per_day=6), NOW)[0]
    report = templates.add_row(conn, SETTINGS, top, row("Trial report", duration=3, assignees=["P002"], assignee_hours=12), NOW)[0]
    return conn, top, window, report


def links(conn, task_id: str) -> set[str]:
    return {r["field"] for r in conn.execute("SELECT field FROM task_links WHERE task = ?", (task_id,))}


def test_a_row_holds_a_length_and_a_rate(trial):
    conn, top, window, report = trial
    lib = Library(conn)
    r = lib.rows[window]
    assert (r.duration, r.calendar_days, r.assignee_per_day, r.assignee_hours, r.lead_per_day) == (5, False, 6, None, 2)
    assert templates.summary(r) == "5 days · 6 h a day"
    assert templates.summary(lib.rows[report]) == "3 days · 12 h"


def test_a_row_that_repeats_has_no_length(trial):
    conn, top, _, _ = trial
    r = templates.add_row(conn, SETTINGS, top, row("Weekly check", recurrence="Weekly", duration=5, assignee_per_day=6, assignee_hours=2), NOW)[0]
    x = Library(conn).rows[r]
    assert (x.duration, x.assignee_per_day, x.assignee_hours) == (None, None, 2)


def test_make_tasks_arrives_undated_keeping_its_size(trial):
    """Decision 193: placed by hand. Its totals come from its rate and Duration."""
    conn, top, window, report = trial
    made = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {}, NOW)
    t = get(conn, made[1])
    assert (t.start, t.due, t.duration, t.assignee_hours, t.lead_hours, t.assignee_per_day) == (None, None, 5, 30, 10, 6)
    assert {"duration", "calendar_days", "assignee_hours", "lead_hours"} <= links(conn, made[1])


def test_make_tasks_takes_a_start_and_days(trial):
    conn, top, window, report = trial
    made = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {window: Choice("2026-11-05", None, None, 3), report: Choice("2026-11-09", None, None, 3)}, NOW)
    t = get(conn, made[1])
    assert (t.start, t.due, t.duration, t.assignee_hours) == ("2026-11-05", "2026-11-09", 3, 18)
    assert "duration" not in links(conn, made[1]) and "assignee_hours" in links(conn, made[1])  # days typed differently are its own
    r = get(conn, made[2])
    assert (r.due, r.duration, r.assignee_hours) == ("2026-11-11", 3, 12) and "duration" in links(conn, made[2])  # kept as offered


def test_a_worked_out_total_doesnt_end_a_link(trial):
    """A total worked out from h a day is simply calculated: what's stated is the rate."""
    conn, top, window, report = trial
    made = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {}, NOW)
    logged = change(conn, made[1], duration=3)
    assert "Assignee hours: 30 → 18" in logged and "Duration: 5 → 3" in logged
    assert "Template link: Duration: no longer follows Product trial → None" in logged
    assert "assignee_hours" in links(conn, made[1]) and "duration" not in links(conn, made[1])
    assert templates.own_fields(Library(conn).rows[window], get(conn, made[1]), links(conn, made[1]), False) == ["duration"]
    # A different rate, or a total typed over it, does end it.
    change(conn, made[1], assignee_per_day=4)
    assert "assignee_hours" not in links(conn, made[1])
    change(conn, made[1], lead_hours=20)
    assert "lead_hours" not in links(conn, made[1]) and get(conn, made[1]).lead_per_day is None


def test_a_rate_change_reaches_the_tasks_following(trial):
    conn, top, window, report = trial
    a = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {window: Choice("2026-11-02")}, NOW)
    b = templates.make_tasks(conn, SETTINGS, top, "Trial 2", None, {}, NOW)
    changed = row("Trial window", duration=5, leads=["P001"], lead_per_day=2, assignees=["P002", "P003"], assignee_per_day=4)
    plan = templates.preview_row(conn, SETTINGS, window, changed, NOW)
    assert plan.lines == ["Assignee hours 6 h a day → 4 h a day"]
    item = next(i for i in plan.items if i.task == a[1])
    assert item.lines == ["Assignee hours 30 h → 20 h"] and (item.work_before, item.work_after) == (10 + 60, 10 + 40)
    templates.apply_row(conn, SETTINGS, window, changed, NOW)
    x = get(conn, a[1])
    assert (x.assignee_per_day, x.assignee_hours) == (4, 20) and "assignee_hours" in links(conn, a[1])
    assert "Assignee hours a day 6 → 4 · Template: Product trial." in [Stories(Model(conn), TODAY, lambda _: "").field_sentence(e) for e in Model(conn).status_log_of(a[1])]
    assert get(conn, b[1]).assignee_per_day == 4


def test_a_duration_change_shows_the_dates_it_moves(trial):
    conn, top, window, report = trial
    a = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {window: Choice("2026-11-02")}, NOW)
    changed = row("Trial window", duration=3, leads=["P001"], lead_per_day=2, assignees=["P002", "P003"], assignee_per_day=6)
    plan = templates.preview_row(conn, SETTINGS, window, changed, NOW)
    assert plan.lines == ["Duration 5 days → 3 days"]
    item = next(i for i in plan.items if i.task == a[1])
    assert item.lines == ["Duration 5 days → 3 days", "Due 6 Nov → 4 Nov", "Lead hours 10 h → 6 h", "Assignee hours 30 h → 18 h"]
    assert (item.work_before, item.work_after) == (10 + 60, 6 + 36)
    templates.apply_row(conn, SETTINGS, window, changed, NOW)
    x = get(conn, a[1])
    assert (x.due, x.duration, x.assignee_hours) == ("2026-11-04", 3, 18) and "duration" in links(conn, a[1])


def test_a_unit_change_on_the_row_reaches_as_a_stated_change(trial):
    conn, top, window, report = trial
    a = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {report: Choice("2026-11-02")}, NOW)
    changed = row("Trial report", duration=3, assignees=["P002"], assignee_per_day=4)  # 12 h in all is 4 h a day over 3 days
    plan = templates.preview_row(conn, SETTINGS, report, changed, NOW)
    item = next(i for i in plan.items if i.task == a[2])
    assert item.lines == ["Assignee hours 12 h → 4 h a day"]  # the total's the same, so the rate is what changed
    templates.apply_row(conn, SETTINGS, report, changed, NOW)
    x = get(conn, a[2])
    assert (x.assignee_hours, x.assignee_per_day) == (12, 4)


def test_a_routine_task_isnt_reached_by_a_length(trial):
    conn, top, window, report = trial
    a = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {}, NOW)
    change(conn, a[1], recurrence="Weekly")
    changed = row("Trial window", duration=3, leads=["P001"], lead_per_day=2, assignees=["P002", "P003"], assignee_per_day=4)
    plan = templates.preview_row(conn, SETTINGS, window, changed, NOW)
    assert a[1] not in [i.task for i in plan.items]
    templates.apply_row(conn, SETTINGS, window, changed, NOW)
    assert get(conn, a[1]).duration is None


def test_a_closed_task_that_fell_behind_on_its_rate_keeps_its_hours(trial):
    conn, top, window, report = trial
    a = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {window: Choice("2026-11-02")}, NOW)
    change(conn, a[1], state="Closed")
    templates.apply_row(conn, SETTINGS, window, row("Trial window", duration=5, leads=["P001"], lead_per_day=2, assignees=["P002", "P003"], assignee_per_day=4), NOW)
    assert get(conn, a[1]).assignee_hours == 30
    logged = change(conn, a[1], state="In progress")
    x = get(conn, a[1])
    assert (x.assignee_per_day, x.assignee_hours) == (6, 30) and "assignee_hours" not in links(conn, a[1])
    assert any("fell behind" in line for line in logged)


def test_save_as_template_takes_the_length_from_two_dates(sample_conn):
    conn = sample_conn
    parent = task(conn, start="2026-11-02", due="2026-11-06", assignees=["P002"], assignee_hours=20)
    child = tasks.create_task(conn, SETTINGS, title="Child", at=NOW, created_by="Browse tool", parents=[parent], start="2026-11-09", duration=3, calendar_days=True,
                              assignees=["P003"], assignee_per_day=2)
    top = templates.save_as_template(conn, SETTINGS, parent, "Pattern", True, NOW)
    lib = Library(conn)
    rows = [x for x, _ in lib.walk(top)]
    assert rows[0].duration == 5 and rows[0].assignee_hours == 20 and rows[0].assignee_per_day is None
    assert (rows[1].duration, rows[1].calendar_days, rows[1].assignee_per_day) == (3, True, 2)
    x = get(conn, parent)
    assert (x.duration, x.start, x.due) == (5, "2026-11-02", "2026-11-06")  # linked, it takes that Duration, and its dates stay
    assert "duration" in links(conn, parent) and "duration" in links(conn, child)


def test_the_row_page_says_what_a_rate_comes_to(trial):
    from docrepo import template_pages

    conn, top, window, report = trial
    lib, m = Library(conn), Model(conn)
    page = template_pages.row_page(lib, m, window, TODAY)
    assert "6 h a day = 30 h each" in page and "5 days" in page
    assert "Left blank" in template_pages.row_page(lib, m, top, TODAY)


# ---- Quick edit's rules ----
def test_quick_edit_values_carry_the_length():
    v = planning.Values(start="2026-11-02", duration=5, assignees=["P002", "P003"], assignee_per_day=6, leads=["P001"], lead_hours=4)
    assert planning.length(v) == 5 and planning.role_total(v, "assignee_hours") == 30
    assert planning.total_hours(v) == 4 + 60
    values = planning.edit_values(v)
    assert values["assignee_per_day"] == 6 and "assignee_hours" not in values and values["lead_hours"] == 4 and values["lead_per_day"] is None
    assert values["duration"] == 5
    t = planning.total_text(planning.Values(assignees=["P002"], assignee_per_day=6), None)
    assert t == "6 h a day, needs a length"


def test_a_total_the_box_reads_takes_a_rates_place():
    base = planning.Values(assignees=["P002"], assignee_per_day=6)
    v = planning.shown(base, planning.Reading(fills={"assignee_hours": 12.0}))
    assert v.assignee_hours == 12 and v.assignee_per_day is None


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


def typed(field, text: str) -> None:
    field.line.setText(text)
    field.edited.emit()


def days(dialog, text: str) -> None:
    dialog.duration.setText(text)
    dialog.duration.textEdited.emit(text)


def test_edit_task_moves_the_block(browse, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5)
    browse.refresh()
    d = form(browse, t)
    assert d.due.value() == "2026-11-06" and d.date_hint.isVisibleTo(d)
    typed(d.start, "2026-11-05")
    assert d.due.value() == "2026-11-11" and d.due.line.property("worked") and "Worked out" in d.due.line.toolTip()
    typed(d.due, "2026-11-20")
    assert d.start.value() == "2026-11-16" and d.start.line.property("worked") and not d.due.line.property("worked")
    days(d, "3")
    assert d.due.value() == "2026-11-18" and d.start.value() == "2026-11-16"
    d.calendar.setChecked(True)
    assert d.due.value() == "2026-11-18"
    browse.save_task_edit(t, d.values())
    x = get(ctx.conn, t)
    assert (x.start, x.due, x.duration, x.calendar_days) == ("2026-11-16", "2026-11-18", 3, True)


def test_clearing_a_date_in_the_form_clears_both(browse, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5)
    browse.refresh()
    d = form(browse, t)
    typed(d.due, "")
    assert d.start.value() is None and d.due.value() is None and d.duration.text() == "5"
    browse.save_task_edit(t, d.values())
    assert dates(ctx.conn, t) == (None, None, 5)


def test_an_empty_duration_shows_the_length_in_grey(browse, ctx):
    t = task(ctx.conn, start="2026-11-02", due="2026-11-06")
    browse.refresh()
    d = form(browse, t)
    assert d.duration.text() == "" and d.duration.placeholderText() == "5" and "Type a number" in d.duration.toolTip()
    assert not d.date_hint.isVisibleTo(d)
    typed(d.due, "2026-11-13")  # no Duration typed: Start stays
    assert d.start.value() == "2026-11-02" and d.duration.placeholderText() == "10"
    browse.save_task_edit(t, d.values())
    assert dates(ctx.conn, t) == ("2026-11-02", "2026-11-13", None)


def test_a_task_with_no_start_shows_none_once_it_has_a_duration(browse, ctx):
    t = task(ctx.conn)
    browse.refresh()
    d = form(browse, t)
    assert d.start.value() == TODAY.isoformat()  # the day it was made, as ever
    days(d, "5")
    assert d.start.value() is None
    typed(d.start, "2026-11-02")
    assert d.due.value() == "2026-11-06"


def test_a_due_past_the_deadline_warns(browse, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5, deadline="2026-11-06")
    browse.refresh()
    d = form(browse, t)
    assert not d.date_warn.isVisibleTo(d)
    typed(d.start, "2026-11-16")
    assert d.date_warn.isVisibleTo(d) and "after the Deadline" in d.date_warn.text()


def test_a_bad_duration_stops_the_save(browse, ctx):
    t = task(ctx.conn)
    browse.refresh()
    d = form(browse, t)
    d.duration.setText("2.5")
    assert d.problem() == "Duration is a whole number of days, 1 or more."


def test_the_form_states_hours_a_day_and_says_what_they_come_to(browse, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002", "P003"], assignee_hours=30)
    browse.refresh()
    d = form(browse, t)
    assert not d.asg_unit.per_day() and d.asg_hours.text() == "30"
    d.asg_unit.unit.setCurrentIndex(1)
    d.asg_unit.unit.activated.emit(1)
    assert d.asg_hours.text() == "6" and d.asg_unit.line.text() == "= 30 h each over 5 days"  # switching keeps the total
    browse.save_task_edit(t, d.values())
    x = get(ctx.conn, t)
    assert (x.assignee_per_day, x.assignee_hours) == (6, 30)
    d = form(browse, t)
    assert d.asg_unit.per_day() and d.asg_hours.text() == "6"
    d.asg_unit.unit.setCurrentIndex(0)
    d.asg_unit.unit.activated.emit(0)
    assert d.asg_hours.text() == "30" and d.asg_unit.line.text() == ""
    browse.save_task_edit(t, d.values())
    x = get(ctx.conn, t)
    assert (x.assignee_per_day, x.assignee_hours) == (None, 30)


def test_switching_with_no_length_keeps_the_number(browse, ctx):
    t = task(ctx.conn, assignees=["P002"], assignee_hours=6)
    browse.refresh()
    d = form(browse, t)
    d.asg_unit.unit.setCurrentIndex(1)
    d.asg_unit.unit.activated.emit(1)
    assert d.asg_hours.text() == "6" and d.asg_unit.line.text() == "6 h a day, needs a length"


def test_a_routine_task_has_no_duration_in_the_form(browse, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    browse.refresh()
    d = form(browse, t)
    assert d.duration_field.isVisibleTo(d)
    d.recurrence.setCurrentText("Weekly")
    assert not d.duration_field.isVisibleTo(d) and not d.asg_unit.unit.isVisibleTo(d) and d.asg_unit.line.text() == "each time"
    assert d.values()["duration"] is None


def test_the_marks_cover_duration_and_a_rate(browse, ctx, sample_root):
    conn = ctx.conn
    top = templates.new_template(conn, "Product trial", NOW)
    row_id = templates.add_row(conn, SETTINGS, top, row("Trial window", duration=5, assignees=["P002"], assignee_per_day=6), NOW)[0]
    made = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {row_id: Choice("2026-11-02")}, NOW)
    browse.refresh()
    d = form(browse, made[1])
    assert {"duration", "calendar_days", "assignee_hours"} <= set(d.marks)
    assert d.marks["duration"].mark.text() == "" and d.marks["assignee_hours"].mark.text() == ""
    assert "6 h a day" in d.marks["assignee_hours"].mark.toolTip() and "5 days" in d.marks["duration"].mark.toolTip()
    days(d, "3")
    assert d.marks["duration"].mark.text() == "Template: 5 days ↺" and d.marks["duration"].leaving.isVisibleTo(d)
    assert d.marks["assignee_hours"].mark.text() == ""  # its total follows; its rate is what's stated
    assert d.due.value() == "2026-11-04"
    d.marks["duration"].mark.click()
    assert d.duration.text() == "5" and d.due.value() == "2026-11-06" and d.marks["duration"].following
    d.asg_hours.setText("4")
    d.asg_hours.textEdited.emit("4")
    assert d.marks["assignee_hours"].mark.text() == "Template: 6 h a day ↺" and d.marks["assignee_hours"].leaving.isVisibleTo(d)
    assert "assignee_hours" not in d.values()["follow"]
    d.marks["assignee_hours"].mark.click()
    assert d.asg_hours.text() == "6" and d.asg_unit.per_day()


def test_a_row_form_has_a_length_and_a_rate(browse, ctx):
    conn = ctx.conn
    top = templates.new_template(conn, "Product trial", NOW)
    browse.refresh()
    d = RowDialog(browse, browse.model(), None, browse._label_options, browse._people_options, "Add a subtask")
    d.title_box.setText("Trial window")
    d.duration.setText("5")
    d.duration.textEdited.emit("5")
    d.calendar.setChecked(True)
    d.asg_unit.set_per_day(True)
    d.asg_hours.setText("6")
    d.asg_hours.textEdited.emit("6")
    d.assignees.set_chips([])
    values = d.values()
    assert (values["duration"], values["calendar_days"], values["assignee_per_day"], values["assignee_hours"]) == (5, True, 6, None)
    assert d.asg_unit.line.text() == "= 30 h over 5 days"
    d.recurrence.setCurrentText("Weekly")
    assert not d.length_box.isVisibleTo(d) and not d.asg_unit.unit.isVisibleTo(d)
    d.recurrence.setCurrentIndex(0)
    d.duration.setText("x")
    assert d.problem() == "Duration is a whole number of days, 1 or more."
    r = templates.add_row(conn, SETTINGS, top, {**values, "duration": 5}, NOW)[0]
    again = RowDialog(browse, browse.model(), Library(conn).rows[r], browse._label_options, browse._people_options, "Edit template row")
    assert again.duration.text() == "5" and again.calendar.isChecked() and again.asg_hours.text() == "6" and again.asg_unit.per_day()


def test_make_tasks_shows_the_due_and_hours_a_start_comes_to(browse, ctx):
    conn = ctx.conn
    top = templates.new_template(conn, "Product trial", NOW)
    row_id = templates.add_row(conn, SETTINGS, top, row("Trial window", duration=5, assignees=["P002"], assignee_per_day=6), NOW)[0]
    other = templates.add_row(conn, SETTINGS, top, row("Report", assignees=["P002"], assignee_hours=12), NOW)[0]
    browse.refresh()
    d = MakeTasksDialog(browse, browse.model(), Library(conn), top, browse._people_options, lambda a, p: None, browse._workdays())
    line = next(x for x in d.lines if x.row.id == row_id)
    assert line.days.text() == "5" and line.hours.text() == "6 h a day = 30 h" and line.due.text() == ""
    typed(line.start, "2026-11-05")
    assert line.due.text() == "Wed 11 Nov"
    line.days.setText("3")
    line.days.textEdited.emit("3")
    assert line.due.text() == "Mon 9 Nov" and line.hours.text() == "6 h a day = 18 h"
    d.name.setText("Trial 1")
    assert d.problem() is None
    line.days.setText("x")
    assert "whole number" in d.problem()
    line.days.setText("3")
    assert d.choices()[row_id].duration == 3 and next(x for x in d.lines if x.row.id == other).hours.text() == "12 h"


def test_plan_mode_is_marked_as_a_drag(browse, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    browse.refresh()
    browse.set_timeline_dates(t, "2026-11-02", "2026-11-04", "said")  # an end stretched
    x = get(ctx.conn, t)
    assert (x.due, x.duration, x.assignee_hours) == ("2026-11-04", 3, 18)
    browse.set_timeline_dates(t, "2026-11-05", "2026-11-09", "said")  # moved
    x = get(ctx.conn, t)
    assert (x.start, x.due, x.duration) == ("2026-11-05", "2026-11-09", 3)


def test_quick_edit_moves_the_block_and_saves(ctx, qapp):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    w = QuickEdit(ctx, t)
    assert w.duration.text() == "5" and w.units["assignee_hours"].currentIndex() == 1 and w.hours["assignee_hours"].text() == "6"
    assert w.total.text().startswith("30 h in all")
    w.dates["start"].set_value("2026-11-05")
    w._field_edited("start")
    assert w.dates["due"].value() == "2026-11-11"
    w.duration.setText("3")
    w._field_edited("duration")
    assert w.dates["due"].value() == "2026-11-09" and w.total.text().startswith("18 h in all")
    w.save()
    x = get(ctx.conn, t)
    assert (x.start, x.due, x.duration, x.assignee_hours, x.assignee_per_day) == ("2026-11-05", "2026-11-09", 3, 18, 6)
    w.deleteLater()


def test_quick_edit_switches_the_unit_keeping_the_total(ctx, qapp):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_hours=30)
    w = QuickEdit(ctx, t)
    assert w.units["assignee_hours"].currentIndex() == 0
    w.units["assignee_hours"].setCurrentIndex(1)
    w._unit_changed("assignee_hours")
    assert w.hours["assignee_hours"].text() == "6" and w.values().assignee_per_day == 6 and w.values().assignee_hours is None
    w.hours["assignee_hours"].setText("4")
    w._field_edited("assignee_hours")
    assert w.values().assignee_per_day == 4
    w.save()
    x = get(ctx.conn, t)
    assert (x.assignee_per_day, x.assignee_hours) == (4, 20)
    w.deleteLater()


def test_quick_edit_hides_them_for_a_routine_task(ctx, qapp):
    t = task(ctx.conn, recurrence="Weekly", start="2026-11-02", assignees=["P002"], assignee_hours=1.5)
    w = QuickEdit(ctx, t)
    assert not w.length_row.isVisibleTo(w) and not w.units["assignee_hours"].isVisibleTo(w)
    w.deleteLater()


def test_quick_edit_rejects_a_bad_duration(ctx, qapp):
    t = task(ctx.conn, start="2026-11-02")
    w = QuickEdit(ctx, t)
    w.duration.setText("soon")
    w._field_edited("duration")
    w.save()
    assert "whole number" in w.message.text() and get(ctx.conn, t).duration is None
    w.deleteLater()


@pytest.fixture
def capture(ctx):
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()


def test_a_new_task_can_have_a_duration_and_hours_a_day(capture, ctx):
    capture.title.setText("Trial window")
    capture.n_duration.setText("5")
    capture.n_due.set_value("2026-11-06")
    capture.n_asg_hours.setText("6")
    capture.n_asg_row.set_per_day(True)
    draft = capture.draft().new_task
    assert (draft.duration, draft.assignee_per_day, draft.assignee_hours) == (5, 6.0, None)
    assert draft.lead_per_day is None and draft.calendar_days is False


def test_an_update_can_change_the_duration_and_hours_a_day(capture, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    capture.show_capture(task=t, mode="update")
    assert capture.u_duration.text() == "5" and capture.u_asg_row.per_day() and capture.u_asg_hours.text() == "6"
    current = ctx.model().task(t)
    assert capture.update_changes(current) == {}  # nothing changed, so nothing to save
    capture.u_duration.setText("3")
    capture.u_asg_hours.setText("4")
    changes = capture.update_changes(current)
    assert changes == {"duration": 3, "assignee_per_day": 4.0}
    tasks.update_task(ctx.conn, SETTINGS, t, at=NOW, via="C000001", **changes)
    x = get(ctx.conn, t)
    assert (x.due, x.assignee_hours) == ("2026-11-04", 12)


def test_an_update_typing_a_total_ends_the_rate(capture, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    capture.show_capture(task=t, mode="update")
    capture.u_asg_row.set_per_day(False)
    capture.u_asg_hours.setText("25")
    changes = capture.update_changes(ctx.model().task(t))
    assert changes == {"assignee_hours": 25.0, "assignee_per_day": None}


def test_a_bad_duration_stops_a_capture(capture):
    capture.title.setText("Trial")
    capture.types.add("new_task")
    capture.n_duration.setText("two")
    assert capture._check_fields() is False
    assert "whole number" in capture.error.text()


def test_clearing_the_capture_window_clears_them(capture, ctx):
    t = task(ctx.conn, start="2026-11-02", duration=5, assignees=["P002"], assignee_per_day=6)
    capture.show_capture(task=t, mode="update")
    capture.show_capture()
    assert capture.n_duration.text() == "" and not capture.n_asg_row.per_day() and not capture.n_calendar.isChecked()


def test_a_routine_new_task_has_no_length_in_the_capture_window(capture):
    capture.n_recurrence.setCurrentText("Weekly")
    capture.refresh()
    assert not capture.n_length.isVisibleTo(capture) and capture.n_asg_row.line.text() == "each time"
    capture.n_recurrence.setCurrentIndex(0)
    capture.refresh()
    assert capture.n_asg_row.line.text() == ""


def test_edits_stay_logged_as_a_browse_tool_change(sample_root):
    conn, root, fs = sample_root
    t = task(conn, start="2026-11-02", duration=5)
    edits.change_task(conn, root, fs, SETTINGS, t, NOW, due="2026-11-20")
    assert dates(conn, t) == ("2026-11-16", "2026-11-20", 5)
    fields = [e.field for e in Model(conn).status_log_of(t)]
    assert "Due" in fields and "Start" in fields
