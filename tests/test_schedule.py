"""Windows, next occurrences and the capacity rules at their edges."""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from docrepo.capacity import task_rows
from docrepo.config import Settings
from docrepo.dates import add_months, days_text, long_date, short
from docrepo.model import Task
from docrepo.schedule import due_of, windows

TODAY = date(2026, 10, 8)
BASE = Task(id="T1", title="t", state="In progress", closed=None, urgent=False, meeting=False, recurrence=None, repeat_until=None,
            start="2026-10-12", due="2026-10-23", deadline=None, deadline_desc=None, reminder=None, lead_hours=None,
            assignee_hours=None, inherit_labels=True, description="", current_status="", created="2026-10-01", created_by="x")


def task(**fields) -> Task:
    return replace(BASE, **fields)


def test_months_keep_the_day_or_use_the_last_day():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 2, 29), 12) == date(2029, 2, 28)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_one_time_window_uses_due_then_deadline():
    assert windows(task(), TODAY) == [(date(2026, 10, 12), date(2026, 10, 23))]
    assert windows(task(due=None, deadline="2026-10-31"), TODAY) == [(date(2026, 10, 12), date(2026, 10, 31))]
    assert windows(task(due=None), TODAY) == []
    assert windows(task(start=None, due="2026-10-02"), TODAY) == [(date(2026, 10, 1), date(2026, 10, 2))]


def test_routine_windows_repeat_until_the_end():
    monthly = task(recurrence="Monthly", start="2026-01-30", due=None)
    assert [w[0] for w in windows(monthly, date(2026, 4, 30))] == [date(2026, 1, 30), date(2026, 2, 28), date(2026, 3, 30), date(2026, 4, 30)]
    weekly = task(recurrence="Weekly", start="2026-10-06", due=None, repeat_until="2026-10-20")
    assert [w[0] for w in windows(weekly, date(2027, 1, 1))] == [date(2026, 10, 6), date(2026, 10, 13), date(2026, 10, 20)]
    closed = task(recurrence="Weekly", start="2026-10-06", due=None, state="Closed", closed="2026-10-14")
    assert len(windows(closed, date(2027, 1, 1))) == 2


def test_next_occurrence_and_days_until_due():
    weekly = task(recurrence="Weekly", start="2026-10-06", due=None)
    assert due_of(weekly, TODAY).date == date(2026, 10, 13) and due_of(weekly, TODAY).label == "Next"
    assert due_of(task(), TODAY).label == "Due"
    assert due_of(task(state="Closed", closed="2026-10-07"), TODAY) is None
    assert days_text(date(2026, 10, 30), TODAY) == "in 22 d"
    assert days_text(date(2026, 10, 9), TODAY) == "tomorrow"
    assert days_text(date(2026, 10, 5), TODAY) == "3 d overdue"


def test_short_dates():
    assert short(date(2026, 10, 13), TODAY) == "13 Oct"
    assert short(date(2027, 1, 11), TODAY) == "11 Jan 2027"
    assert long_date(date(2026, 10, 13), TODAY) == "Tue 13 Oct"


def test_hours_spread_over_workdays():
    t = task(leads=["P1"], lead_hours=2, assignees=["P2"], assignee_hours=12)
    rows = task_rows(t, TODAY, Settings())
    assert len(rows) == 20 and rows[("P1", date(2026, 10, 12))] == 0.2 and rows[("P2", date(2026, 10, 23))] == 1.2
    assert ("P1", date(2026, 10, 17)) not in rows  # a Saturday


def test_someone_in_both_roles_gets_both():
    t = task(leads=["P1"], lead_hours=2, assignees=["P1"], assignee_hours=8)
    assert sum(task_rows(t, TODAY, Settings()).values()) == 10


def test_a_weekend_window_spreads_over_its_days():
    t = task(start="2026-10-17", due="2026-10-18", assignees=["P1"], assignee_hours=4)
    assert task_rows(t, TODAY, Settings()) == {("P1", date(2026, 10, 17)): 2.0, ("P1", date(2026, 10, 18)): 2.0}


def test_parked_and_unestimated_tasks_have_no_rows():
    assert task_rows(task(state="Parked", assignees=["P1"], assignee_hours=4), TODAY, Settings()) == {}
    assert task_rows(task(assignees=["P1"]), TODAY, Settings()) == {}


def test_routine_tasks_stop_at_the_horizon():
    weekly = task(recurrence="Weekly", start="2026-10-06", due=None, assignees=["P1"], assignee_hours=1)
    days = sorted(d for _, d in task_rows(weekly, TODAY, Settings(capacity_horizon_years=1)))
    assert days[0] == date(2026, 10, 6) and days[-1] == date(2027, 10, 5) and len(days) == 53


def test_workdays_come_from_settings():
    t = task(start="2026-10-12", due="2026-10-18", assignees=["P1"], assignee_hours=6)
    rows = task_rows(t, TODAY, Settings(workdays=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]))
    assert len(rows) == 6 and rows[("P1", date(2026, 10, 17))] == 1.0
