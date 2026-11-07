"""Release 5.48 (round 5's thread A, items 64 to 66; the task templates design's Plan mode, decisions 189 to 191 and 196): the
Timeline's hours text counts each person's Involvement, so it agrees with Capacity, and a Plan mode drop is worked out and said
as it will be saved. No window is needed: the view's own drags are in ``test_timeline_drags.py``."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import capacity, tasks, timeline, whatif
from docrepo.config import Settings
from docrepo.model import Model, load_tasks

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")
WEEK = frozenset(range(5))
PRIYA, TOM, MIKE = "P002", "P003", "P004"


def task(conn, **values) -> str:
    return tasks.create_task(conn, SETTINGS, title="Trial execution window", at=NOW, created_by="Browse tool", **values)


def get(conn, task_id: str):
    return load_tasks(conn, [task_id])[task_id]


def calendar_hours(conn, task_id: str) -> float:
    return conn.execute("SELECT coalesce(sum(hours), 0) FROM work_calendar WHERE task = ?", (task_id,)).fetchone()[0]


def week_of_calendar(conn, task_id: str, monday: str) -> float:
    cells = capacity.week_cells(conn, [date.fromisoformat(monday)])
    return sum(w.get(date.fromisoformat(monday), {}).get(task_id, 0) for w in cells.values())


# ---- the hours text, with Involvement (decision 196) ----
def test_the_total_counts_each_persons_share_as_capacity_does(sample_conn):
    """The design's example: on 12 h in all, Priya at 100% has 12 h, Tom at 25% 3 h and Mike at 50% 6 h, so 21 h in all."""
    t = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=[PRIYA, TOM, MIKE], assignee_hours=12,
             involvement={("assignee", TOM): 25, ("assignee", MIKE): 50})
    x = get(sample_conn, t)
    assert timeline.hours(x, TODAY) == (21.0, 21.0)  # five workdays: a week's worth
    assert timeline.hours(x, TODAY)[0] == pytest.approx(calendar_hours(sample_conn, t))
    assert timeline.hours(x, TODAY)[1] == pytest.approx(week_of_calendar(sample_conn, t, "2026-11-02"))
    assert (timeline.hours_label(x, TODAY, False), timeline.hours_label(x, TODAY, True)) == ("21 h", "21 h/wk")


def test_the_words_give_each_persons_own_hours(sample_conn):
    t = task(sample_conn, start="2026-11-02", due="2026-11-06", leads=["P001"], lead_hours=4, assignees=[PRIYA, TOM, MIKE], assignee_hours=12,
             involvement={("assignee", TOM): 25, ("assignee", MIKE): 50, ("lead", "P001"): 50})
    m = Model(sample_conn)
    assert timeline.hours_words(m, m.task(t), TODAY) == ("23 h: Me 2 h (50%) as lead, Priya Shah 12 h, Tom Becker 3 h (25%) and Mike Ortiz "
                                                        "6 h (50%) as assignees · about 23 h a week")
    assert "Priya Shah 12 h, Tom Becker 3 h (25%)" in timeline.tooltip(m, t, TODAY)


def test_tasks_at_100_read_as_they_did(sample_conn):
    t = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=[PRIYA, TOM], assignee_hours=6)
    m = Model(sample_conn)
    assert timeline.hours_words(m, m.task(t), TODAY) == "12 h: Priya Shah and Tom Becker 6 h each as assignees · about 12 h a week"


def test_someone_at_0_has_no_hours_and_everyone_at_0_none_at_all(sample_conn):
    some = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=[PRIYA, TOM], assignee_hours=10, involvement={("assignee", TOM): 0})
    none = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=[TOM], assignee_hours=10, involvement={("assignee", TOM): 0})
    m = Model(sample_conn)
    assert timeline.hours_words(m, m.task(some), TODAY).startswith("10 h: Priya Shah 10 h and Tom Becker 0 h (0%) as assignees")
    assert timeline.hours(m.task(none), TODAY) is None and timeline.hours_label(m.task(none), TODAY, False) == ""
    assert timeline.hour_bin(m.task(none), TODAY) == -1 and calendar_hours(sample_conn, none) == 0


def test_shares_set_the_bars_colour_for_hours_a_week(sample_conn):
    whole = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=[PRIYA], assignee_hours=24)
    quarter = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=[PRIYA], assignee_hours=24, involvement={("assignee", PRIYA): 25})
    m = Model(sample_conn)
    assert (timeline.hour_bin(m.task(whole), TODAY), timeline.hour_bin(m.task(quarter), TODAY)) == (4, 2)  # 24 h/wk, and 6


def test_a_week_counts_every_day_for_a_task_that_runs_through_weekends(sample_conn):
    """Thu 5 to Mon 9 Nov is five days with the tick: 6 h on each, so 42 h a week where Capacity has 6 h every day."""
    every = task(sample_conn, start="2026-11-05", duration=5, calendar_days=True, assignees=[PRIYA], assignee_per_day=6)
    weekdays = task(sample_conn, start="2026-11-05", duration=5, assignees=[PRIYA], assignee_per_day=6)
    m = Model(sample_conn)
    assert timeline.hours(m.task(every), TODAY) == (30.0, 42.0)
    assert timeline.hours(m.task(weekdays), TODAY) == (30.0, 30.0)  # Thu 5 to Wed 11 Nov, its five workdays
    per_day = sample_conn.execute("SELECT DISTINCT round(hours, 6) FROM work_calendar WHERE task = ?", (every,)).fetchall()
    assert [r[0] for r in per_day] == [6.0] and timeline.hours(m.task(every), TODAY)[1] == 6 * 7


def test_a_routine_tasks_hours_are_each_time_with_shares(sample_conn):
    t = task(sample_conn, start="2026-11-02", recurrence="Weekly", assignees=[PRIYA, TOM], assignee_hours=2, involvement={("assignee", TOM): 50})
    m = Model(sample_conn)
    assert timeline.hours(m.task(t), TODAY) == (3.0, None)
    assert timeline.hours_words(m, m.task(t), TODAY) == "3 h each time: Priya Shah 2 h and Tom Becker 1 h (50%) as assignees"


# ---- a drop, as it will be saved (decisions 136, 137 and 191) ----
def drop(conn, task_id: str, start: str, end: str, mode: str) -> tuple:
    """What the view works out for a drop, then what the save makes of the same dates: they must agree."""
    before = get(conn, task_id)
    sent = timeline.drop_dates(before, date.fromisoformat(start), date.fromisoformat(end), mode)
    after = timeline.dropped(before, *sent, WEEK)
    said = timeline.drop_said(before, after, mode, TODAY)
    tasks.update_task(conn, SETTINGS, task_id, at=NOW, via="Browse tool", dragged=True, start=sent[0], due=sent[1])
    saved = get(conn, task_id)
    fields = ("start", "due", "duration", "lead_hours", "assignee_hours", "assignee_per_day")
    assert {f: getattr(saved, f) for f in fields} == {f: getattr(after, f) for f in fields}
    return (saved.start, saved.due, saved.duration), said


def test_a_bar_moved_across_a_weekend_keeps_its_workdays(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_per_day=6)  # Mon to Fri
    assert drop(sample_conn, t, "2026-11-05", "2026-11-09", "move") == (("2026-11-05", "2026-11-11", 5), "now Thu 5 Nov to Wed 11 Nov, still 5 workdays")
    assert get(sample_conn, t).assignee_hours == 30  # wider, but no more work


def test_runs_through_weekends_counts_every_day(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, calendar_days=True)  # Mon to Fri
    assert drop(sample_conn, t, "2026-11-05", "2026-11-09", "move") == (("2026-11-05", "2026-11-09", 5), "now Thu 5 Nov to Mon 9 Nov, still 5 days")


def test_an_end_stretched_says_the_duration_and_a_rates_total(sample_conn):
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_per_day=6)
    assert drop(sample_conn, t, "2026-11-02", "2026-11-04", "end") == (
        ("2026-11-02", "2026-11-04", 3), "Due moved to Wed 4 Nov, Duration 5 → 3 workdays, assignee hours 30 → 18")
    assert drop(sample_conn, t, "2026-10-30", "2026-11-04", "start") == (
        ("2026-10-30", "2026-11-04", 4), "Start moved to Fri 30 Oct, Duration 3 → 4 workdays, assignee hours 18 → 24")


def test_with_h_in_all_the_total_stays(sample_conn):
    """Decision 137, narrowed: the total stays only for h in all."""
    t = task(sample_conn, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_hours=30, leads=["P001"], lead_per_week=5)
    assert drop(sample_conn, t, "2026-11-02", "2026-11-11", "end") == (
        ("2026-11-02", "2026-11-11", 8), "Due moved to Wed 11 Nov, Duration 5 → 8 workdays, lead hours 5 → 8")
    assert get(sample_conn, t).assignee_hours == 30


def test_a_rate_with_plain_dates_follows_a_stretch_too(sample_conn):
    t = task(sample_conn, start="2026-11-02", due="2026-11-06", assignees=[PRIYA], assignee_per_day=6)
    assert drop(sample_conn, t, "2026-11-02", "2026-11-09", "end") == (("2026-11-02", "2026-11-09", None), "Due moved to Mon 9 Nov, assignee hours 30 → 36")


def test_an_undated_task_dropped_takes_its_own_duration(sample_conn):
    t = task(sample_conn, duration=3, assignees=[PRIYA], assignee_per_day=4)
    assert timeline.drop_room(get(sample_conn, t)) == "its 3 workdays"
    assert get(sample_conn, t).assignee_hours == 12  # a rate over its Duration has its total before it has dates
    assert drop(sample_conn, t, "2026-11-02", "2026-11-06", "new") == (("2026-11-02", "2026-11-04", 3), "Start and Due set: Mon 2 Nov to Wed 4 Nov, its own 3 workdays")


def test_with_no_duration_a_drop_is_as_it_was(sample_conn):
    t = task(sample_conn)
    assert timeline.drop_room(get(sample_conn, t)) == "a week"
    assert drop(sample_conn, t, "2026-11-02", "2026-11-06", "new") == (("2026-11-02", "2026-11-06", None), "Start and Due set: Mon 2 Nov to Fri 6 Nov")
    assert drop(sample_conn, t, "2026-11-04", "2026-11-10", "move") == (("2026-11-04", "2026-11-10", None), "now Wed 4 Nov to Tue 10 Nov")


def test_a_bar_ending_at_its_deadline_keeps_its_one_end(sample_conn):
    t = task(sample_conn, start="2026-11-02", deadline="2026-11-13")
    before = get(sample_conn, t)
    assert timeline.drop_dates(before, date(2026, 11, 4), date(2026, 11, 13), "start") == ("2026-11-04", None)
    assert timeline.drop_dates(before, date(2026, 11, 4), date(2026, 11, 16), "move") == ("2026-11-04", "2026-11-16")


def test_the_words_for_an_undated_task(sample_conn):
    every = task(sample_conn, duration=1, calendar_days=True)
    plain = task(sample_conn)
    m = Model(sample_conn)
    assert timeline.drop_room(m.task(every)) == "its 1 day"
    assert "drag its name onto the chart to give it its 1 day" in timeline.tooltip(m, every, TODAY, plan=True)
    assert "drag its name onto the chart to give it a week" in timeline.tooltip(m, plain, TODAY, plan=True)
    assert [timeline.length_words(n, e) for n, e in ((1, False), (5, False), (5, True))] == ["1 workday", "5 workdays", "5 days"]


def test_workdays_from_settings_are_the_ones_counted(sample_conn):
    """Settings with a four-day week (Monday to Thursday): a 5-day bar moved to Thursday runs to the next Thursday."""
    t = task(sample_conn, start="2026-11-02", duration=5)
    after = timeline.dropped(get(sample_conn, t), "2026-11-05", "2026-11-09", frozenset(range(4)))
    assert (after.start, after.due, after.duration) == ("2026-11-05", "2026-11-12", 5)


# ---- a what-if's review says it too ----
def test_a_what_ifs_review_says_the_duration_and_the_total(sample_conn):
    capacity.rebuild_all(sample_conn, TODAY, SETTINGS)
    rate = task(sample_conn, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_per_day=6)
    whole = task(sample_conn, start="2026-11-02", duration=5, assignees=[PRIYA], assignee_hours=30)
    m = Model(sample_conn)
    w = whatif.WhatIf("W1", "Shorter")
    whatif.add(w, whatif.move(m, rate, "2026-11-02", "2026-11-04"))
    whatif.add(w, whatif.move(m, whole, "2026-11-02", "2026-11-04"))
    said = whatif.lines(m, w, whatif.picture(sample_conn, SETTINGS, w, NOW, m), TODAY)
    assert said[0].says == ["Now 2 Nov to 4 Nov, Duration 5 → 3 workdays, assignee hours 30 → 18."]
    assert said[1].says == ["Now 2 Nov to 4 Nov, Duration 5 → 3 workdays, hours kept."]
