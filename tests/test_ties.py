"""Ties (release 5.50; the task templates design, decisions 245 to 259): a task's Start or Due set from another date, and everything
that moves with it. The rules, every path that changes a date, the asking first, the page, the log and the forms."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import activity, bulk, capacity, edits, save, tasks, ties  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, Tie, load_tasks  # noqa: E402
from docrepo.stories import Stories  # noqa: E402
from docrepo.tasks import KeyDateRow, TaskError  # noqa: E402
from docrepo.detail import Pages as DetailPages  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_edit import QuickEdit  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")
WEEK = range(5)
MON_2, TUE_3, FRI_6, MON_9, MON_16, MON_23 = "2026-11-02", "2026-11-03", "2026-11-06", "2026-11-09", "2026-11-16", "2026-11-23"


@pytest.fixture
def conn(sample_conn):
    return sample_conn


def make(conn, title: str = "Line 2 outage", **values) -> str:
    return tasks.create_task(conn, SETTINGS, title=title, at=NOW, created_by="Browse tool", **values)


def get(conn, task_id: str):
    return load_tasks(conn, [task_id])[task_id]


def change(conn, task_id: str, **values):
    return tasks.update_task(conn, SETTINGS, task_id, at=NOW, via="Browse tool", **values)


def tied(conn, source: str, **values) -> str:
    """A task with its Start tied the day after ``source`` ends."""
    wanted = values.pop("wanted", {"start": Tie(source, amount=1)})
    made = make(conn, values.pop("title", "Trial report"), **values)
    change(conn, made, ties=wanted)
    return made


def sentences(conn, task_id: str) -> list[str]:
    m = Model(conn)
    stories = Stories(m, TODAY, lambda _: "")
    return [stories.field_sentence(e) for e in m.status_log_of(task_id)]


# ---- the sum ----
@pytest.mark.parametrize("ref, tie, lands", [
    (date(2026, 11, 6), Tie("x", amount=0), date(2026, 11, 6)),
    (date(2026, 11, 6), Tie("x", amount=1), date(2026, 11, 9)),  # over the weekend
    (date(2026, 11, 9), Tie("x", amount=1, direction="before"), date(2026, 11, 6)),
    (date(2026, 11, 6), Tie("x", amount=6), date(2026, 11, 16)),
    (date(2026, 11, 6), Tie("x", amount=2, unit="weeks"), date(2026, 11, 20)),  # 14 days, whatever the workdays
    (date(2026, 11, 6), Tie("x", amount=1, unit="weeks", direction="before"), date(2026, 10, 30)),
])
def test_where_a_tie_lands(ref, tie, lands):
    assert ties.landing(ref, tie, WEEK) == lands


def test_workdays_come_from_settings():
    assert ties.landing(date(2026, 11, 5), Tie("x", amount=1), range(4)) == date(2026, 11, 9)  # Thursday, then Monday in a 4-day week


@pytest.mark.parametrize("was, day, now", [
    (Tie("x", amount=3), date(2026, 11, 6), Tie("x", amount=0)),
    (Tie("x", amount=3), date(2026, 11, 9), Tie("x", amount=1)),
    (Tie("x", amount=3), date(2026, 11, 5), Tie("x", amount=1, direction="before")),
    (Tie("x", amount=1, unit="weeks"), date(2026, 11, 20), Tie("x", amount=2, unit="weeks")),
    (Tie("x", amount=1, unit="weeks"), date(2026, 11, 9), Tie("x", amount=1)),  # no longer whole weeks
    (Tie("x", amount=1, unit="weeks"), date(2026, 10, 30), Tie("x", amount=1, unit="weeks", direction="before")),
])
def test_the_new_gap_that_puts_a_tie_on_a_day(was, day, now):
    assert ties.regapped(was, date(2026, 11, 6), day, WEEK) == now


def test_a_new_gap_lands_where_it_was_put():
    for day in (date(2026, 11, 2), date(2026, 11, 16), date(2026, 10, 19)):
        for tie in (Tie("x", amount=3), Tie("x", amount=2, unit="weeks")):
            assert ties.landing(date(2026, 11, 6), ties.regapped(tie, date(2026, 11, 6), day, WEEK), WEEK) == day


def test_a_tie_in_words():
    assert ties.words(Tie("x", amount=3), "Line 2 outage") == "3 workdays after Line 2 outage ends"
    assert ties.words(Tie("x", amount=1, point="start", direction="before"), "Line 2 outage") == "1 workday before Line 2 outage starts"
    assert ties.words(Tie("x", amount=1, unit="weeks"), "Line 2 outage") == "1 week after Line 2 outage ends"
    assert ties.words(Tie("x", amount=2, unit="weeks"), "Line 2 outage") == "2 weeks after Line 2 outage ends"
    assert ties.words(Tie("x", point="start"), "Line 2 outage") == "The day Line 2 outage starts"


# ---- making one ----
def test_a_new_tie_puts_its_date_where_it_lands_and_says_so(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = make(conn, "Trial report", duration=2)
    logged = change(conn, report, ties={"start": Tie(outage, amount=1)})
    t = get(conn, report)
    assert t.ties == {"start": Tie(outage, amount=1)}
    assert (t.start, t.due, t.duration) == (MON_9, "2026-11-10", 2)
    assert ("Start tie", None, "1 workday after Line 2 outage ends") in [(c.field, c.from_value, c.to_value) for c in logged]
    assert "Start tie: 1 workday after Line 2 outage ends." in sentences(conn, report)


def test_a_date_given_with_a_new_tie_keeps_the_tie_and_sets_the_gap(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = make(conn, "Trial report")
    change(conn, report, start=MON_16, ties={"start": Tie(outage, amount=1)})
    t = get(conn, report)
    assert t.start == MON_16 and t.ties["start"] == Tie(outage, amount=6)


def test_one_tie_per_date_and_both_can_be_tied(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = make(conn, "Trial report", duration=4)
    change(conn, report, ties={"start": Tie(outage, amount=1), "due": Tie(outage, amount=5)})
    t = get(conn, report)
    assert (t.start, t.due) == (MON_9, "2026-11-13")
    assert t.duration is None  # both tied, the length comes from them (decision 251)
    change(conn, report, ties={"start": Tie(outage, amount=2), "due": Tie(outage, amount=5)})
    assert get(conn, report).start == "2026-11-10"
    assert conn.execute("SELECT count(*) FROM task_ties WHERE task = ?", (report,)).fetchone()[0] == 2


def test_remove_ends_the_tie_and_the_date_stays(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    logged = change(conn, report, ties={})
    t = get(conn, report)
    assert t.ties == {} and t.start == MON_9
    assert [c.field for c in logged] == ["Start tie"] and logged[0].to_value is None
    assert sentences(conn, report)[-1] == "Start tie removed."
    change(conn, outage, due=MON_23)
    assert get(conn, report).start == MON_9


def test_a_routine_task_cant_be_a_source(conn):
    routine = make(conn, "Weekly review", recurrence="Weekly")
    report = make(conn, "Trial report")
    with pytest.raises(TaskError, match="Weekly review repeats"):
        change(conn, report, ties={"start": Tie(routine, amount=1)})
    assert get(conn, report).ties == {}


def test_a_task_cant_be_tied_to_its_own_dates_but_can_to_its_own_key_date(conn):
    report = make(conn, "Trial report")
    with pytest.raises(TaskError, match="own dates"):
        change(conn, report, ties={"start": Tie(report)})
    tasks.set_key_dates(conn, report, [KeyDateRow(start=MON_16, end=None, description="Sign-off")], at=NOW, via="Browse tool")
    key = tasks.key_date_rows(conn, report)[0].id
    change(conn, report, ties={"due": Tie(report, key_date=key)})
    assert get(conn, report).due == MON_16


def test_circles_are_refused_near_and_far(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    c = tied(conn, b, title="Trial report")
    with pytest.raises(TaskError, match="That would go in a circle: Trial report already moves with this task."):
        change(conn, a, ties={"start": Tie(c)})
    with pytest.raises(TaskError, match="That would go in a circle: Outage permit already moves with this task."):
        change(conn, a, ties={"due": Tie(b)})
    assert get(conn, a).ties == {}


def test_a_key_date_makes_no_circle_because_it_doesnt_follow(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    tasks.set_key_dates(conn, a, [KeyDateRow(start=MON_16, end=None, description="Sign-off")], at=NOW, via="Browse tool")
    key = tasks.key_date_rows(conn, a)[0].id
    b = make(conn, "Trial report")
    change(conn, b, ties={"start": Tie(a, key_date=key)})
    change(conn, a, ties={"start": Tie(b, point="start", amount=2, unit="weeks", direction="before")})
    assert get(conn, a).start == MON_2  # 14 days before Monday the 16th


# ---- moving ----
def test_the_gap_is_kept_later_and_earlier(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    logged = change(conn, outage, due=MON_9)
    assert get(conn, report).start == "2026-11-10"
    assert [f.task for f in logged.followed] == [report]
    change(conn, outage, due=TUE_3)
    assert get(conn, report).start == "2026-11-04"
    assert get(conn, report).ties["start"] == Tie(outage, amount=1)


def test_the_log_says_what_it_follows(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    change(conn, outage, due=MON_9)
    entry = Model(conn).status_log_of(report)[-1]
    assert (entry.field, entry.via) == ("Start", "Follows Line 2 outage")
    assert sentences(conn, report)[-1].endswith("· Follows Line 2 outage.")
    assert "→" in sentences(conn, report)[-1]


@pytest.mark.parametrize("values, wanted, after", [
    ({"duration": 3}, "start", (MON_9, "2026-11-11")),  # a Duration: the other date follows
    ({"start": MON_16, "due": "2026-11-20"}, "start", (MON_9, "2026-11-13")),  # two plain dates keep their length
    ({"start": MON_16}, "start", (MON_9, None)),  # no Due to keep
])
def test_the_rest_of_a_task_follows_a_tied_start(conn, values, wanted, after):
    outage = make(conn, start=MON_2, due="2026-10-30")
    report = make(conn, "Trial report", **values)
    change(conn, report, ties={wanted: Tie(outage, amount=1)})
    change(conn, outage, due=FRI_6)
    t = get(conn, report)
    assert (t.start, t.due) == after


def test_a_tied_due_brings_the_start_with_it(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    plain = make(conn, "Plain", start=MON_2, due="2026-11-03")
    with_days = make(conn, "Sized", duration=3)
    for task_id in (plain, with_days):
        change(conn, task_id, ties={"due": Tie(outage, amount=1, point="start", direction="before")})
    assert get(conn, with_days).due == "2026-10-30"
    change(conn, outage, start=MON_9, due=MON_16)
    t = get(conn, with_days)
    assert (t.start, t.due, t.duration) == ("2026-11-04", FRI_6, 3)
    t = get(conn, plain)
    assert t.due == FRI_6 and t.start == "2026-11-05"  # two days, as it was


def test_changing_the_duration_of_a_due_tied_task_moves_its_start(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = make(conn, "Trial report", duration=3)
    change(conn, report, ties={"due": Tie(outage)})
    change(conn, report, duration=5)
    t = get(conn, report)
    assert (t.start, t.due) == (MON_2, FRI_6) and t.ties["due"] == Tie(outage)


def test_with_both_tied_each_keeps_to_its_own(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = make(conn, "Outage permit", start=MON_2, due=MON_16)
    report = make(conn, "Trial report")
    change(conn, report, ties={"start": Tie(a, amount=1), "due": Tie(b)})
    assert (get(conn, report).start, get(conn, report).due) == (MON_9, MON_16)
    change(conn, a, due=TUE_3)
    assert (get(conn, report).start, get(conn, report).due) == ("2026-11-04", MON_16)
    change(conn, b, due=MON_23)
    assert (get(conn, report).start, get(conn, report).due) == ("2026-11-04", MON_23)


def test_a_move_runs_through_a_chain(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit", duration=2)
    c = tied(conn, b, title="Trial report")
    assert (get(conn, b).start, get(conn, b).due) == (MON_9, "2026-11-10")
    assert get(conn, c).start == "2026-11-11"
    logged = change(conn, a, due=MON_9)
    assert sorted(f.task for f in logged.followed) == sorted([b, c])
    assert get(conn, c).start == "2026-11-12"
    assert Model(conn).status_log_of(c)[-1].via == "Follows Outage permit"


def test_a_diamond_lands_once_each_on_the_final_dates(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Left", duration=2)
    c = tied(conn, a, title="Right", duration=3)
    d = make(conn, "Trial report")
    change(conn, d, ties={"start": Tie(b, amount=1), "due": Tie(c, amount=1)})
    assert (get(conn, d).start, get(conn, d).due) == ("2026-11-11", "2026-11-12")
    logged = change(conn, a, due=MON_9)
    assert [f.task for f in logged.followed].count(d) == 1
    assert (get(conn, d).start, get(conn, d).due) == ("2026-11-12", "2026-11-13")


def test_capacity_is_rebuilt_for_what_moves(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = make(conn, "Trial report", duration=1, assignees=["P002"], assignee_hours=8)
    change(conn, report, ties={"start": Tie(outage, amount=1)})
    days = lambda: [r["date"] for r in conn.execute("SELECT date FROM work_calendar WHERE task = ?", (report,))]  # noqa: E731
    capacity.rebuild_task(conn, report, TODAY, SETTINGS)
    before = days()
    change(conn, outage, due=MON_9)
    assert days() != before and "2026-11-10" in days()


# ---- by hand ----
def test_a_hand_change_keeps_the_tie_with_a_new_gap(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    logged = change(conn, report, start=MON_16)
    t = get(conn, report)
    assert t.start == MON_16 and t.ties["start"] == Tie(outage, amount=6)
    assert ("Start tie", "1 workday after Line 2 outage ends", "6 workdays after Line 2 outage ends") in [(c.field, c.from_value, c.to_value) for c in logged]
    change(conn, outage, due=MON_9)  # and it moves by that gap from now on
    assert get(conn, report).start == "2026-11-17"


def test_a_hand_change_before_the_source_turns_the_gap_round(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    change(conn, report, start=TUE_3)
    assert get(conn, report).ties["start"] == Tie(outage, amount=3, direction="before")


def test_weeks_stay_weeks_when_they_can(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage, wanted={"start": Tie(outage, amount=1, unit="weeks")})
    assert get(conn, report).start == "2026-11-13"
    change(conn, report, start="2026-11-20")
    assert get(conn, report).ties["start"] == Tie(outage, amount=2, unit="weeks")
    change(conn, report, start=MON_23)
    assert get(conn, report).ties["start"] == Tie(outage, amount=11)


def test_clearing_a_tied_date_puts_it_back(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    assert not change(conn, report, start=None)
    assert get(conn, report).start == MON_9


def test_a_drag_keeps_the_tie_and_takes_a_new_gap(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage, duration=2)
    tasks.update_task(conn, SETTINGS, report, at=NOW, via="Browse tool", dragged=True, start=MON_16, due="2026-11-17")
    t = get(conn, report)
    assert (t.start, t.due, t.duration) == (MON_16, "2026-11-17", 2) and t.ties["start"] == Tie(outage, amount=6)


def test_moving_a_tied_task_by_hand_moves_what_follows_it(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    c = tied(conn, b, title="Trial report")
    logged = change(conn, b, due=MON_16, start=MON_16)
    assert get(conn, c).start == "2026-11-17"
    assert [f.task for f in logged.followed] == [c]
    assert get(conn, a).due == FRI_6


# ---- with no date ----
def test_a_tie_waits_with_no_source_date_and_lands_when_it_gets_one(conn):
    outage = make(conn)
    report = make(conn, "Trial report", duration=2)
    change(conn, report, ties={"start": Tie(outage, amount=1)})
    t = get(conn, report)
    assert t.ties and t.start is None and t.due is None
    logged = change(conn, outage, start=MON_2, due=FRI_6)
    assert [f.task for f in logged.followed] == [report]
    assert (get(conn, report).start, get(conn, report).due) == (MON_9, "2026-11-10")


def test_clearing_a_source_takes_followers_off_the_calendar_keeping_their_size(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    sized = tied(conn, outage, title="Sized", duration=2)
    plain = make(conn, "Plain", start=MON_9, due="2026-11-11")
    change(conn, plain, ties={"start": Tie(outage, amount=1)})
    change(conn, outage, start=None, due=None)
    t = get(conn, sized)
    assert (t.start, t.due, t.duration) == (None, None, 2) and t.ties
    t = get(conn, plain)
    assert (t.start, t.due, t.duration) == (None, None, 3) and t.ties  # three days, kept as a Duration
    change(conn, outage, start=MON_2, due=FRI_6)
    assert (get(conn, plain).start, get(conn, plain).due) == (MON_9, "2026-11-11")


def test_a_cleared_date_stays_cleared_while_the_source_has_none(conn):
    outage = make(conn)
    report = make(conn, "Trial report")
    change(conn, report, ties={"start": Tie(outage)})
    change(conn, report, start=MON_2)  # a date with nothing to count from: it stays, and the tie still waits
    assert get(conn, report).start == MON_2 and get(conn, report).ties["start"] == Tie(outage)
    change(conn, outage, due=FRI_6)
    assert get(conn, report).start == FRI_6


# ---- key dates ----
def key_task(conn, title: str = "Line 2 outage") -> tuple[str, int]:
    t = make(conn, title, start=MON_2, due=FRI_6)
    tasks.set_key_dates(conn, t, [KeyDateRow(start=MON_16, end="2026-11-18", description="Shutdown")], at=NOW, via="Browse tool")
    return t, tasks.key_date_rows(conn, t)[0].id


def keyed(conn, source: str, key: int, **kw) -> str:
    return tied(conn, source, wanted={"start": Tie(source, key_date=key, **kw)})


def test_a_key_date_is_a_source_and_its_name_says_so(conn):
    t, key = key_task(conn)
    report = keyed(conn, t, key, amount=1)
    assert get(conn, report).start == "2026-11-19"
    assert sentences(conn, report)[-1] == "Start tie: 1 workday after Line 2 outage: Shutdown ends."


def test_moving_a_key_date_moves_what_is_tied_to_it(conn):
    t, key = key_task(conn)
    report = keyed(conn, t, key, amount=1)
    rows = tasks.key_date_rows(conn, t)
    logged = tasks.set_key_dates(conn, t, [KeyDateRow(id=rows[0].id, start=MON_23, end="2026-11-25", description="Shutdown")], at=NOW, via="Browse tool", settings=SETTINGS)
    assert get(conn, report).start == "2026-11-26"
    assert [f.task for f in logged.followed] == [report]
    assert Model(conn).status_log_of(report)[-1].via == "Follows Line 2 outage: Shutdown"


def test_a_key_date_doesnt_follow_its_tasks_dates(conn):
    t, key = key_task(conn)
    report = keyed(conn, t, key, amount=1)
    logged = change(conn, t, start=MON_9, due=MON_16)
    assert not logged.followed and get(conn, report).start == "2026-11-19"
    assert tasks.key_date_rows(conn, t)[0].start == MON_16


def test_a_key_date_with_one_date_has_it_at_both_ends(conn):
    t = make(conn, start=MON_2, due=FRI_6)
    tasks.set_key_dates(conn, t, [KeyDateRow(start=None, end=MON_16, description="Deadline")], at=NOW, via="Browse tool")
    key = tasks.key_date_rows(conn, t)[0].id
    assert get(conn, keyed(conn, t, key, point="start")).start == MON_16
    assert get(conn, keyed(conn, t, key, point="end")).start == MON_16


def test_removing_a_key_date_ends_its_ties_and_the_dates_stay(conn):
    t, key = key_task(conn)
    report = keyed(conn, t, key, amount=1)
    other = keyed(conn, t, key, amount=2)
    tasks.set_key_dates(conn, t, [], at=NOW, via="Browse tool", settings=SETTINGS)
    for x, start in ((report, "2026-11-19"), (other, "2026-11-20")):
        assert get(conn, x).ties == {} and get(conn, x).start == start
    assert sentences(conn, report)[-1] == "Start tie removed."
    assert conn.execute("SELECT count(*) FROM task_ties WHERE key_date = ?", (key,)).fetchone()[0] == 0


def test_a_new_key_date_row_order_changes_nothing_tied(conn):
    t, key = key_task(conn)
    report = keyed(conn, t, key, amount=1)
    rows = tasks.key_date_rows(conn, t)
    tasks.set_key_dates(conn, t, [KeyDateRow(start=MON_9, end=None, description="New"), *rows], at=NOW, via="Browse tool", settings=SETTINGS)
    assert get(conn, report).ties["start"].key_date == key and get(conn, report).start == "2026-11-19"


# ---- closed, discarded and routine ----
def test_a_closed_task_never_moves_and_is_counted(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    change(conn, report, state="Closed")
    logged = change(conn, outage, due=MON_16)
    assert get(conn, report).start == MON_9 and logged.closed == 1 and not logged.followed
    assert tasks.moved_words(logged) == "1 closed task stayed."


def test_a_closed_task_takes_a_new_gap_when_it_comes_back_behind(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    change(conn, report, state="Closed")
    change(conn, outage, due=MON_16)
    change(conn, report, state="Not started")
    t = get(conn, report)
    assert t.start == MON_9 and t.ties["start"] == Tie(outage, amount=5, direction="before")


def test_a_closed_source_still_counts(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    change(conn, outage, state="Closed")
    change(conn, outage, due=MON_9)
    assert get(conn, report).start == "2026-11-10"


def test_a_discarded_source_moves_nothing_until_its_back(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    tasks.set_discarded(conn, SETTINGS, outage, "Not needed", at=NOW, via="Browse tool")
    logged = change(conn, outage, due=MON_16)
    assert get(conn, report).start == MON_9 and not logged.followed and get(conn, report).ties
    change(conn, report, start=TUE_3)  # by hand: the date changes, and the gap can't be worked out, so it stays
    assert get(conn, report).ties["start"] == Tie(outage, amount=1)
    tasks.set_discarded(conn, SETTINGS, outage, None, at=NOW, via="Browse tool")
    assert get(conn, report).start == "2026-11-17"  # back, and it catches up


def test_a_discarded_source_brings_key_date_ties_back_too(conn):
    t, key = key_task(conn)
    report = keyed(conn, t, key, amount=1)
    tasks.set_discarded(conn, SETTINGS, t, "Not needed", at=NOW, via="Browse tool")
    rows = tasks.key_date_rows(conn, t)
    tasks.set_key_dates(conn, t, [KeyDateRow(id=rows[0].id, start=MON_23, end="2026-11-25", description="Shutdown")], at=NOW, via="Browse tool", settings=SETTINGS)
    assert get(conn, report).start == "2026-11-19"
    tasks.set_discarded(conn, SETTINGS, t, None, at=NOW, via="Browse tool")
    assert get(conn, report).start == "2026-11-26"


def test_a_discarded_follower_stays_and_takes_a_new_gap_when_back(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    tasks.set_discarded(conn, SETTINGS, report, "Not needed", at=NOW, via="Browse tool")
    logged = change(conn, outage, due=MON_16)
    assert get(conn, report).start == MON_9 and not logged.followed
    tasks.set_discarded(conn, SETTINGS, report, None, at=NOW, via="Browse tool")
    assert get(conn, report).start == MON_9 and get(conn, report).ties["start"].direction == "before"


def test_gaining_a_recurrence_ends_ties_both_ways(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    c = tied(conn, b, title="Trial report")
    start = get(conn, c).start
    change(conn, b, recurrence="Weekly")
    assert get(conn, b).ties == {}
    assert get(conn, c).ties == {} and get(conn, c).start == start
    assert sentences(conn, c)[-1] == "Start tie removed."


def test_a_routine_task_keeps_ties_to_its_key_dates(conn):
    routine = make(conn, "Weekly review", recurrence="Weekly")
    tasks.set_key_dates(conn, routine, [KeyDateRow(start=MON_16, end=None, description="Audit")], at=NOW, via="Browse tool")
    key = tasks.key_date_rows(conn, routine)[0].id
    report = keyed(conn, routine, key)
    change(conn, routine, title="Weekly check")
    assert get(conn, report).start == MON_16 and get(conn, report).ties


# ---- every path, and asking first ----
def test_what_moves_can_be_seen_first_and_nothing_changes(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    conn.commit()
    found = edits.change_moves(conn, SETTINGS, a, NOW, due=MON_9)
    assert [f.task for f in found] == [b]
    assert any(c.field == "Start" for c in found[0].changes)
    assert get(conn, a).due == FRI_6 and get(conn, b).start == MON_9
    assert found[0].changes[0].to_value  # what it would become, shown


def test_what_edit_task_would_move_and_a_key_date(conn):
    t, key = key_task(conn)
    report = keyed(conn, t, key)
    conn.commit()
    rows = tasks.key_date_rows(conn, t)
    moved = [KeyDateRow(id=rows[0].id, start=MON_23, end="2026-11-25", description="Shutdown")]
    assert [f.task for f in edits.key_dates_move(conn, SETTINGS, t, moved, NOW)] == [report]
    assert [f.task for f in edits.edit_moves(conn, SETTINGS, t, NOW, key_dates=moved)] == [report]
    assert tasks.key_date_rows(conn, t)[0].start == MON_16
    assert not edits.edit_moves(conn, SETTINGS, t, NOW, title="Renamed")


def test_a_task_left_keeps_its_date_stays_tied_and_takes_a_new_gap(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit", duration=1)
    c = tied(conn, b, title="Trial report")
    d = tied(conn, a, title="Other")
    logged = tasks.update_task(conn, SETTINGS, a, at=NOW, via="Browse tool", due=MON_16, leave={b})
    assert get(conn, b).start == MON_9 and get(conn, b).ties["start"] == Tie(a, amount=5, direction="before")
    assert get(conn, c).start == "2026-11-10"  # what follows it stays too
    assert get(conn, d).start == "2026-11-17"
    assert [f.task for f in logged.followed] == [d]


def test_edit_task_saves_ties_and_says_what_moved(sample_root):
    conn, root, fs = sample_root
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = make(conn, "Outage permit")
    out = edits.edit_task(conn, root, fs, SETTINGS, b, NOW, ties={"start": Tie(a, amount=1)})
    assert not out.problems and get(conn, b).start == MON_9
    out = edits.edit_task(conn, root, fs, SETTINGS, a, NOW, due=MON_9)
    assert out.message.endswith("Moved 1 task with it.") and out.moved == "Moved 1 task with it."
    assert get(conn, b).start == "2026-11-10"


def test_edit_task_leaves_what_it_was_told_to(sample_root):
    conn, root, fs = sample_root
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    out = edits.edit_task(conn, root, fs, SETTINGS, a, NOW, due=MON_16, leave={b})
    assert not out.moved and get(conn, b).start == MON_9


def test_a_task_page_is_written_for_what_moved(sample_root):
    conn, root, fs = sample_root
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    edits.edit_task(conn, root, fs, SETTINGS, a, NOW, due=MON_9)
    page = (root / "Tasks" / b / "Task.md").read_text(encoding="utf-8")
    assert "2026-11-10" in page or "10 Nov" in page
    assert "Start tied" in page and "1 workday after Outage plan ends" in page
    source = (root / "Tasks" / a / "Task.md").read_text(encoding="utf-8")
    assert "Tied to this" in source and "Outage permit" in source


def test_bulk_moves_what_is_tied_and_says_so(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    conn.commit()
    edit = bulk.BulkEdit(fields={"due": MON_9})
    seen = bulk.preview(conn, SETTINGS, [a], edit, NOW, "Browse tool")
    assert "1 tied task moves with it" in bulk.summary(seen)
    assert get(conn, b).start == MON_9
    done = bulk.run(conn, SETTINGS, [a], edit, NOW, "Browse tool")
    assert "Moved 1 tied task with it" in bulk.summary(done, done=True)
    assert get(conn, b).start == "2026-11-10"


def test_a_model_knows_what_is_tied_to_a_task(conn):
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    m = Model(conn)
    assert [t.id for t in m.tied_to(a)] == [b]
    assert ties.own_followers_in(m, a) == [b]
    assert ties.ref_in(m, m.task(b).ties["start"]) == date(2026, 11, 6)
    assert ties.name_in(m, m.task(b).ties["start"]) == "Outage plan"
    assert "circle" in ties.problem_in(m, a, Tie(b))
    assert ties.problem_in(m, b, Tie(a)) is None


# ---- a plain date beside a tied one ----
def test_a_plain_date_cleared_comes_back_with_a_tied_one_and_a_duration(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage, duration=2)
    change(conn, report, due=None)
    assert (get(conn, report).start, get(conn, report).due) == (MON_9, "2026-11-10")
    change(conn, report, start=None, due=None)  # Quick edit clears both when a date is cleared
    assert (get(conn, report).start, get(conn, report).due) == (MON_9, "2026-11-10")


def test_a_plain_date_cleared_with_no_duration_stays_cleared(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = make(conn, "Trial report", due=MON_16)
    change(conn, report, ties={"start": Tie(outage, amount=1)})
    change(conn, report, due=None)
    assert (get(conn, report).start, get(conn, report).due) == (MON_9, None)


# ---- the task page ----
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
    yield w
    w.close()


def when_rows(conn, task_id: str) -> dict[str, str]:
    m = Model(conn)
    pages = DetailPages(m, TODAY, lambda _: "", SETTINGS.me, conn)
    return dict(pages.when_rows(m.task(task_id)))


def test_the_page_says_how_a_date_is_tied_with_a_link(sample_root):
    conn = sample_root[0]
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    row = when_rows(conn, report)["Start tied"]
    assert "1 workday after" in row and f"task:{outage}" in row and "Line 2 outage" in row and row.endswith("ends")


def test_the_page_says_what_is_tied_to_a_task_and_its_tree_when_another(sample_root):
    conn = sample_root[0]
    outage = make(conn, start=MON_2, due=FRI_6)
    other_tree = make(conn, "Audit programme")
    report = tied(conn, outage)
    tasks.set_parents(conn, report, [other_tree], at=NOW, via="Browse tool")
    near = tied(conn, outage, title="Near")
    tasks.set_parents(conn, outage, [other_tree], at=NOW, via="Browse tool")
    tasks.set_parents(conn, near, [outage], at=NOW, via="Browse tool")
    row = when_rows(conn, outage)["Tied to this"]
    assert f"task:{report}" in row and f"task:{near}" in row and "Audit programme" not in row  # all in the one tree
    tasks.set_parents(conn, outage, [], at=NOW, via="Browse tool")
    row = when_rows(conn, outage)["Tied to this"]
    assert "Audit programme" in row


def test_the_page_says_a_tie_is_waiting_or_its_source_discarded(sample_root):
    conn = sample_root[0]
    outage = make(conn)
    report = tied(conn, outage)
    assert "Waiting for that date" in when_rows(conn, report)["Start tied"]
    change(conn, outage, start=MON_2, due=FRI_6)
    assert "Waiting" not in when_rows(conn, report)["Start tied"]
    tasks.set_discarded(conn, SETTINGS, outage, "Not needed", at=NOW, via="Browse tool")
    assert "discarded" in when_rows(conn, report)["Start tied"]


def test_a_task_with_no_ties_has_no_tie_rows(sample_root):
    conn = sample_root[0]
    plain = make(conn, start=MON_2, due=FRI_6)
    assert not {"Start tied", "Due tied", "Tied to this"} & set(when_rows(conn, plain))


def test_the_log_shows_a_changed_tie_and_a_followed_date(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    change(conn, report, start=MON_16)
    assert "Start tie: 1 workday after Line 2 outage ends → 6 workdays after Line 2 outage ends." in sentences(conn, report)
    change(conn, outage, due=MON_9)
    last = sentences(conn, report)[-1]
    assert last.startswith("Start ") and last.endswith("· Follows Line 2 outage.")


def test_activity_says_what_a_date_followed(conn):
    outage = make(conn, start=MON_2, due=FRI_6)
    report = tied(conn, outage)
    change(conn, outage, due=MON_9)
    lines = activity.Activity(Model(conn), TODAY).lines(TODAY, TODAY)
    facts = [x.facts for x in lines if x.task == report and "Start" in x.text]
    assert ["Follows Line 2 outage"] in facts


# ---- Edit task ----
def form(browse, task_id: str, pick=None) -> TaskEditDialog:
    return TaskEditDialog(browse, browse.model(), task_id, browse._label_options, browse._people_options, pick, reference_fields=(), today=TODAY, workdays=frozenset(WEEK))


def choosing(task_id: str):
    return lambda anchor, picked: picked(task_id)


def outage_and_report(conn, **values) -> tuple[str, str]:
    return make(conn, start=MON_2, due=FRI_6), make(conn, "Trial report", **values)


def test_tie_sets_the_date_as_soon_as_a_task_is_chosen(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    f = form(browse, report, choosing(outage))
    assert not f.tie_buttons["start"].isHidden() and not f.tie_buttons["due"].isHidden()
    f.tie_buttons["start"].click()
    assert f.tie_panel.editing == "start" and not f.tie_panel.box.isHidden() and f.tie_buttons["start"].isHidden()
    assert f.tie_panel.source.text().startswith("Choose a task…")
    f.tie_panel.source.click()
    assert f.start.value() == MON_9 and f.due.value() == "2026-11-10"  # 1 workday after it ends, and the Duration follows
    f.tie_panel.amount.setValue(3)
    assert f.start.value() == "2026-11-11"
    f.tie_panel.direction.setCurrentText("before")
    assert f.start.value() == TUE_3
    f.tie_panel.point.setCurrentIndex(0)
    assert f.start.value() == "2026-10-28"
    f.tie_panel.unit.setCurrentText("weeks")
    assert f.start.value() == "2026-10-12"
    assert f.values()["ties"] == {"start": Tie(outage, "start", 3, "weeks", "before")}
    f.tie_panel.done.click()
    assert f.tie_panel.box.isHidden() and not f.tie_panel.rows["start"].isHidden()
    assert "Start tied:" in f.tie_panel.lines["start"].text() and "3 weeks before Line 2 outage starts" in f.tie_panel.lines["start"].text()
    assert f.tie_buttons["start"].isHidden()


def test_done_with_no_task_makes_no_tie(ctx, browse):
    _, report = outage_and_report(ctx.conn)
    f = form(browse, report, choosing(None))
    f.tie_buttons["due"].click()
    f.tie_panel.source.click()
    f.tie_panel.done.click()
    assert f.values()["ties"] == {} and not f.tie_buttons["due"].isHidden()


def test_a_tied_date_is_muted_and_says_what_changing_it_does(ctx, browse):
    outage, report = outage_and_report(ctx.conn)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    f = form(browse, report)
    assert f.start.line.property("worked") is True and f.due.line.property("worked") is not True
    assert f.start.line.toolTip() == "Tied: 1 workday after Line 2 outage ends. Change it, and the tie stays with a new gap."


def test_a_typed_date_gives_a_new_gap_in_the_line_at_once(ctx, browse):
    outage, report = outage_and_report(ctx.conn)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    f = form(browse, report)
    f.start.set_value(MON_16)
    f._date_edited("start")
    assert "6 workdays after" in f.tie_panel.lines["start"].text()
    assert f.values()["ties"]["start"] == Tie(outage, amount=6)


def test_a_cleared_tied_date_goes_back_once_finished_with(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    f = form(browse, report)
    f.start.line.clear()
    f._date_edited("start")
    assert not f.start.value()  # still typing
    f.start.line.editingFinished.emit()
    assert f.start.value() == MON_9 and f.due.value() == "2026-11-10"
    assert f.values()["ties"]["start"] == Tie(outage, amount=1)


def test_clearing_a_plain_date_with_a_duration_leaves_the_tied_one(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    f = form(browse, report)
    f.due.line.clear()
    f._date_edited("due")
    assert f.start.value() == MON_9


def test_remove_keeps_the_date_and_offers_tie_again(ctx, browse):
    outage, report = outage_and_report(ctx.conn)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    f = form(browse, report)
    f.tie_panel.remove_buttons["start"].click()
    assert f.values()["ties"] == {} and f.start.value() == MON_9
    assert not f.tie_buttons["start"].isHidden() and f.tie_panel.rows["start"].isHidden()
    assert f.start.line.property("worked") is not True


def test_with_both_tied_duration_greys_and_comes_from_the_dates(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    f = form(browse, report, choosing(outage))
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    f.tie_panel.done.click()
    assert f.duration.isEnabled() and f.duration.text() == "2"
    f.tie_buttons["due"].click()
    f.tie_panel.source.click()
    f.tie_panel.amount.setValue(5)
    assert not f.duration.isEnabled() and f.duration.text() == ""
    assert f.duration.toolTip() == "Both dates are tied, so the length comes from them."
    assert (f.start.value(), f.due.value()) == (MON_9, "2026-11-13")
    assert f.duration.placeholderText() == "5"
    f.tie_panel.remove_buttons["start"].click()
    assert f.duration.isEnabled()


def test_a_new_tie_keeps_two_plain_dates_length_in_the_form(ctx, browse):
    outage, report = outage_and_report(ctx.conn, start=MON_16, due="2026-11-20")
    f = form(browse, report, choosing(outage))
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    assert (f.start.value(), f.due.value()) == (MON_9, "2026-11-13")
    assert f.due.line.property("worked") is True


@pytest.mark.parametrize("way", ["own", "circle", "routine"])
def test_what_cant_be_tied_says_why_and_changes_nothing(ctx, browse, way):
    conn = ctx.conn
    a = make(conn, "Outage plan", start=MON_2, due=FRI_6)
    b = tied(conn, a, title="Outage permit")
    routine = make(conn, "Weekly review", recurrence="Weekly")
    picked, says = {"own": (a, "own dates"), "circle": (b, "That would go in a circle: Outage permit already moves with this task."), "routine": (routine, "Weekly review repeats")}[way]
    f = form(browse, a, choosing(picked))
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    assert says in f.tie_panel.refused.text() and not f.tie_panel.refused.isHidden()
    assert f.values()["ties"] == {} and f.start.value() == MON_2


def test_a_source_with_key_dates_offers_them(ctx, browse):
    t, key = key_task(ctx.conn)
    report = make(ctx.conn, "Trial report")
    f = form(browse, report, choosing(t))
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    assert [f.tie_panel.key.itemText(i) for i in range(f.tie_panel.key.count())] == ["its dates", "Shutdown"]
    assert not f.tie_panel.key.isHidden() and f.start.value() == MON_9
    f.tie_panel.key.setCurrentIndex(1)
    assert f.values()["ties"]["start"].key_date == key and f.start.value() == "2026-11-19"
    assert "Line 2 outage: Shutdown" in f.tie_panel.sentence(f.values()["ties"]["start"])


def test_a_source_with_no_key_dates_has_no_key_box(ctx, browse):
    outage, report = outage_and_report(ctx.conn)
    f = form(browse, report, choosing(outage))
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    assert f.tie_panel.key.isHidden()


def test_a_task_can_tie_to_its_own_key_date(ctx, browse):
    t, key = key_task(ctx.conn)
    f = form(browse, t, choosing(t))
    f.tie_buttons["due"].click()
    f.tie_panel.source.click()
    assert f.tie_panel.refused.isHidden() and f.values()["ties"]["due"].key_date == key
    assert [f.tie_panel.key.itemText(i) for i in range(f.tie_panel.key.count())] == ["Shutdown"]


def test_a_routine_task_has_no_tie_and_says_what_repeating_does(ctx, browse):
    outage, report = outage_and_report(ctx.conn)
    follower = tied(ctx.conn, outage, title="Follower")
    f = form(browse, outage)
    assert f.tied_note.text() == "1 task is tied to this task's dates, and will move with them."
    assert not f.tied_note.isHidden()
    f.recurrence.setCurrentText("Weekly")
    assert f.tie_buttons["start"].isHidden() and f.tie_panel.isHidden()
    assert "Making it repeat ends those ties" in f.tied_note.text()
    assert f.values()["ties"] == {}
    assert follower and form(browse, report).tied_note.isHidden()


def test_a_waiting_tie_says_so_and_shows_no_date(ctx, browse):
    conn = ctx.conn
    source = make(conn)
    report = make(conn, "Trial report")
    change(conn, report, ties={"start": Tie(source)})
    f = form(browse, report)
    assert f.start.value() is None and "(waiting for that date)" in f.tie_panel.lines["start"].text()
    assert f.values()["start"] is None


def test_a_new_tie_with_nothing_to_count_from_empties_the_date(ctx, browse):
    conn = ctx.conn
    source = make(conn, "No date yet")
    report = make(conn, "Trial report")
    f = form(browse, report, choosing(source))
    assert f.start.value()  # the day it was made, shown for a Start that isn't set
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    assert f.start.value() is None
    out = edits.edit_task(conn, ctx.data_root, ctx.fs, SETTINGS, report, NOW, **f.values())
    assert not out.problems and get(conn, report).start is None and get(conn, report).ties


def test_a_new_tie_with_nothing_to_count_from_takes_two_plain_dates_off_the_calendar(ctx, browse):
    conn = ctx.conn
    source = make(conn, "No date yet")
    report = make(conn, "Trial report", start=MON_2, due=FRI_6)
    f = form(browse, report, choosing(source))
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    assert (f.start.value(), f.due.value(), f.duration.text()) == (None, None, "5")


def test_an_untouched_form_is_clean_and_saves_nothing(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    f = form(browse, report)
    assert not f.changed()
    out = edits.edit_task(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, report, NOW, **f.values())
    assert out.message == "Nothing changed."


def test_a_form_change_to_a_tie_counts_as_a_change(ctx, browse):
    outage, report = outage_and_report(ctx.conn)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    f = form(browse, report)
    before = f.snapshot()
    f.tie_panel.remove_buttons["start"].click()
    assert f.snapshot() != before


def test_edit_task_saves_a_tie_from_the_form(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    f = form(browse, report, choosing(outage))
    f.tie_buttons["start"].click()
    f.tie_panel.source.click()
    out = edits.edit_task(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, report, NOW, **f.values())
    assert not out.problems
    t = get(ctx.conn, report)
    assert t.ties["start"] == Tie(outage, amount=1) and (t.start, t.due) == (MON_9, "2026-11-10")
    ctx.conn.commit()


# ---- asking first ----
def in_two_trees(conn) -> tuple[str, str, str, str]:
    """A tree, with a task and what follows it in the same tree, and what follows it in another tree."""
    top = make(conn, "Outage programme")
    other = make(conn, "Audit programme")
    outage = make(conn, start=MON_2, due=FRI_6)
    tasks.set_parents(conn, outage, [top], at=NOW, via="Browse tool")
    near = tied(conn, outage, title="Near", duration=1)
    tasks.set_parents(conn, near, [top], at=NOW, via="Browse tool")
    far = tied(conn, near, title="Far")
    tasks.set_parents(conn, far, [other], at=NOW, via="Browse tool")
    conn.commit()
    return outage, near, far, other


def answering(browse, answer):
    """The dialog's answer: a function of the dialog that returns whether it was accepted."""
    seen = []

    def run(dialog):
        seen.append(dialog)
        return answer(dialog)
    browse.run_dialog = run
    return seen


def test_a_move_within_its_tree_doesnt_ask(ctx, browse):
    conn = ctx.conn
    top = make(conn, "Outage programme")
    outage = make(conn, start=MON_2, due=FRI_6)
    near = tied(conn, outage, title="Near")
    for x in (outage, near):
        tasks.set_parents(conn, x, [top], at=NOW, via="Browse tool")
    conn.commit()
    seen = answering(browse, lambda d: pytest.fail("It asked"))
    assert browse.save_task_edit(outage, {"due": MON_9}) is True
    assert not seen and get(conn, near).start == "2026-11-10"


def test_a_move_reaching_another_tree_lists_all_it_would_move(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    seen = answering(browse, lambda d: True)
    assert browse.save_task_edit(outage, {"due": MON_9}) is True
    d = seen[0]
    assert d.windowTitle() == "This move reaches 1 task in other trees"
    assert set(d.ticks) == {near, far} and all(x.isChecked() for x in d.ticks.values())
    assert d.ticks[far].text() == "Far · Audit programme"
    assert d.commit_button.text() == "Move 2 tasks"
    assert "Start:" in d._lines[far].text() and "→" in d._lines[far].text()
    assert get(conn, far).start == "2026-11-11"


def test_unticking_shows_what_it_means_and_the_button_follows(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)

    def answer(d):
        d.ticks[far].setChecked(False)
        assert d._lines[far].text() == "Keeps its date, stays tied, and takes a new gap."
        assert d.commit_button.text() == "Move 1 task"
        d.ticks[near].setChecked(False)
        assert d.commit_button.text() == "Move only this one"
        d.ticks[near].setChecked(True)
        return True
    answering(browse, answer)
    was = get(conn, far).start
    browse.save_task_edit(outage, {"due": MON_9})
    assert get(conn, near).start == "2026-11-10"
    assert get(conn, far).start == was and get(conn, far).ties  # it stayed, tied, with a new gap


def test_back_saves_nothing(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    answering(browse, lambda d: False)
    assert browse.save_task_edit(outage, {"due": MON_9}) is False
    assert get(conn, outage).due == FRI_6 and get(conn, near).start == MON_9


def test_back_from_edit_task_opens_the_form_again(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    order = []

    def answer(d):
        if isinstance(d, TaskEditDialog):
            order.append("form")
            d.due.set_value(MON_9)
            return len(order) < 3
        order.append("ask")
        return False
    answering(browse, answer)
    browse.edit_task(outage)
    assert order == ["form", "ask", "form"]
    assert get(conn, outage).due == FRI_6


def test_a_timeline_drag_asks_and_back_undoes_it(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    browse.timeline.undo.append(("task", outage, MON_2, FRI_6))
    answering(browse, lambda d: False)
    browse.set_timeline_dates(outage, MON_9, MON_16, "Moved")
    assert browse.timeline.undo == [] and get(conn, outage).due == FRI_6


def test_a_timeline_drag_ticked_moves_and_says_so(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    said = []
    browse.say = lambda text, error=False: said.append(text)
    answering(browse, lambda d: True)
    browse.set_timeline_dates(outage, MON_9, MON_16, "Line 2 outage moved.")
    assert get(conn, outage).due == MON_16 and get(conn, far).start != "2026-11-10"
    assert said[-1] == "Line 2 outage moved. Moved 2 tasks with it."


def test_undo_on_the_timeline_doesnt_ask(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    answering(browse, lambda d: pytest.fail("It asked"))
    browse.set_timeline_dates(outage, MON_9, MON_16, "Line 2 outage: its dates are back as they were.")
    assert get(conn, near).start == "2026-11-17"


def test_a_timeline_key_date_asks_too(ctx, browse):
    conn = ctx.conn
    t, key = key_task(conn)
    other = make(conn, "Audit programme")
    report = keyed(conn, t, key)
    tasks.set_parents(conn, report, [other], at=NOW, via="Browse tool")
    conn.commit()
    browse.timeline.undo.append(("key", t, key, MON_16, "2026-11-18"))
    seen = answering(browse, lambda d: False)
    browse.set_timeline_key_date(t, key, MON_23, "2026-11-25", "Moved")
    assert seen and browse.timeline.undo == [] and tasks.key_date_rows(conn, t)[0].start == MON_16
    seen = answering(browse, lambda d: True)
    browse.set_timeline_key_date(t, key, MON_23, "2026-11-25", "Moved")
    assert seen and tasks.key_date_rows(conn, t)[0].start == MON_23 and get(conn, report).start == "2026-11-25"


# ---- Quick edit ----
def test_quick_edit_shows_a_tied_date_and_typing_gives_a_new_gap(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1)})
    ctx.conn.commit()
    w = QuickEdit(ctx, report)
    assert w.dates["start"].line.property("worked") is True
    assert "Tied: 1 workday after Line 2 outage ends." in w.dates["start"].line.toolTip()
    w.dates["start"].set_value(MON_16)
    w._field_edited("start")
    w.save()
    t = get(ctx.conn, report)
    assert t.start == MON_16 and t.ties["start"] == Tie(outage, amount=6)


def test_quick_edit_greys_duration_with_both_tied(ctx, browse):
    outage, report = outage_and_report(ctx.conn)
    change(ctx.conn, report, ties={"start": Tie(outage, amount=1), "due": Tie(outage, amount=2)})
    ctx.conn.commit()
    w = QuickEdit(ctx, report)
    assert not w.duration.isEnabled()


def test_quick_edit_duration_moves_the_start_of_a_due_tied_task(ctx, browse):
    outage, report = outage_and_report(ctx.conn, duration=2)
    change(ctx.conn, report, ties={"due": Tie(outage)})
    ctx.conn.commit()
    w = QuickEdit(ctx, report)
    w.duration.setText("5")
    w._field_edited("duration")
    w.save()
    t = get(ctx.conn, report)
    assert (t.start, t.due, t.duration) == (MON_2, FRI_6, 5) and t.ties["due"] == Tie(outage)


def test_quick_edit_asks_first_and_back_keeps_it_open(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    w = QuickEdit(ctx, outage)
    w.ask_move = browse.ask_move
    seen = answering(browse, lambda d: False)
    w.dates["due"].set_value(MON_9)
    w._field_edited("due")
    w.save()
    assert seen and get(conn, outage).due == FRI_6
    seen = answering(browse, lambda d: True)
    w.save()
    assert seen and get(conn, far).start == "2026-11-11"


def test_quick_edit_with_no_one_to_ask_moves_them(ctx, browse):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    w = QuickEdit(ctx, outage)
    w.dates["due"].set_value(MON_9)
    w._field_edited("due")
    w.save()
    assert get(conn, far).start == "2026-11-11"


# ---- no one to ask ----
def test_a_capture_update_moves_them_and_says_so(ctx):
    conn = ctx.conn
    outage, near, far, _ = in_two_trees(conn)
    result = save.save_capture(conn, ctx.data_root, ctx.fs, SETTINGS, save.CaptureDraft(content="Outage moved a week.", task=outage, types={"note", "update"}, update={"due": MON_9}), NOW)
    assert result.message.endswith("Moved 2 tasks with it.")
    assert get(conn, far).start == "2026-11-11"
    assert Model(conn).status_log_of(near)[-1].via == "Follows Line 2 outage"
