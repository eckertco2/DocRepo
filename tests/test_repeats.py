"""A reminder that repeats (release 5.117, decision 416; the design workspace's ``docs/mods/today-reminders-plan.md``):
its rules, the task's two fields, and each time putting the task on Today. No Qt."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import capacity, db, edits, repeats, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.sample import load_sample

WEEK = frozenset(range(5))
TUE = date(2026, 11, 10)
SETTINGS = Settings(me="P001")


# ---- the rules ----
@pytest.mark.parametrize("rule, words", [
    ("week:mon,thu", "Every week on Mon and Thu"), ("week:fri", "Every week on Fri"), ("month:15", "Every month on the 15th"),
    ("month:last", "Every month on its last day"), ("workday:3", "Every month on its 3rd workday"),
    ("workday:last", "Every month on its last workday"), ("days:5", "Every 5 days"), ("days:1", "Every day"),
    ("month:22", "Every month on the 22nd"), ("month:11", "Every month on the 11th")])
def test_each_rule_in_words(rule, words):
    assert repeats.describe(rule) == words and repeats.normal(rule) == rule


def test_rules_are_kept_in_one_form():
    assert repeats.normal(" Week:Thu,Mon ") == "week:mon,thu" and repeats.normal("") is None and repeats.normal(None) is None


@pytest.mark.parametrize("rule", ["week:", "week:funday", "month:0", "month:32", "workday:24", "days:0", "fortnight:1", "month:first"])
def test_what_isnt_a_rule(rule):
    with pytest.raises(repeats.RepeatError):
        repeats.parse(rule)


@pytest.mark.parametrize("rule, after, then", [
    ("week:mon,thu", TUE, date(2026, 11, 12)),
    ("week:mon,thu", date(2026, 11, 12), date(2026, 11, 16)),
    ("month:15", TUE, date(2026, 11, 15)),
    ("month:31", TUE, date(2026, 11, 30)),  # a short month: its last day
    ("month:last", date(2027, 2, 1), date(2027, 2, 28)),
    ("workday:3", TUE, date(2026, 12, 3)),  # November's 3rd workday was the 4th
    ("workday:1", date(2026, 11, 30), date(2026, 12, 1)),
    ("workday:last", TUE, date(2026, 11, 30)),
    ("workday:23", TUE, date(2026, 11, 30)),  # November has 21 workdays: its last
])
def test_the_next_time(rule, after, then):
    assert repeats.next_after(rule, after, WEEK) == then


def test_every_n_days_counts_from_the_last_time():
    assert repeats.next_after("days:5", TUE, WEEK, last=date(2026, 11, 3)) == date(2026, 11, 13)
    assert repeats.next_after("days:5", TUE, WEEK) == date(2026, 11, 15)
    assert repeats.first_from("days:5", TUE, WEEK) == TUE


def test_a_new_repeat_can_start_today():
    assert repeats.first_from("week:tue", TUE, WEEK) == TUE and repeats.first_from("week:wed", TUE, WEEK) == date(2026, 11, 11)


def test_until_ends_it():
    assert repeats.following("month:15", "2026-12-01", date(2026, 11, 15), date(2026, 11, 15), WEEK) is None
    assert repeats.following("month:15", "2026-12-15", date(2026, 11, 15), date(2026, 11, 15), WEEK) == "2026-12-15"


# ---- the task's fields ----
@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, TUE, SETTINGS)
    yield conn, data_root, fs
    conn.close()


AT = datetime(2026, 11, 10, 9, 0)


def test_a_repeat_with_no_reminder_starts_from_today(env):
    conn, root, fs = env
    logged = tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="week:thu")
    t = Model(conn).task("T000012")
    assert t.reminder_repeat == "week:thu" and t.reminder == "2026-11-12"
    assert ("Reminder repeats", None, "Every week on Thu") in [(c.field, c.from_value, c.to_value) for c in logged]


def test_until_needs_a_repeat_and_goes_with_it(env):
    conn, root, fs = env
    with pytest.raises(tasks.TaskError):
        tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_until="2026-12-31")
    with pytest.raises(tasks.TaskError):
        tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="fortnightly")
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="month:15", reminder_until="2026-12-31")
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat=None)
    t = Model(conn).task("T000012")
    assert t.reminder_repeat is None and t.reminder_until is None and t.reminder == "2026-11-15"  # the next one stays, as a plain reminder


def test_each_time_it_comes_round_the_task_goes_on_today_and_the_reminder_moves_on(env):
    conn, root, fs = env
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="week:tue")
    assert Model(conn).task("T000012").reminder == "2026-11-10"
    edits.reminders_to_today(conn, root, fs, SETTINGS, AT)
    m = Model(conn)
    assert "T000012" in [a.subject for a in m.today_items()] and m.task("T000012").reminder == "2026-11-17"
    assert [e.via for e in m.status_log_of("T000012") if e.field == "Reminder"][-1] == edits.PUT_ON_TODAY
    item = next(a for a in m.today_items() if a.subject == "T000012")
    edits.close_today_item(conn, root, fs, item.id, "Done", AT)
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 11, 17, 9, 0))
    m = Model(conn)
    assert "T000012" in [a.subject for a in m.today_items()] and m.task("T000012").reminder == "2026-11-24"


def test_a_missed_time_comes_once_and_the_next_is_after_today(env):
    conn, root, fs = env
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="week:mon,thu")
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 11, 25, 9, 0))  # away since the 12th: one item, not five
    m = Model(conn)
    assert [a.subject for a in m.today_items()].count("T000012") == 1 and m.task("T000012").reminder == "2026-11-26"


def test_clear_takes_this_time_and_the_repeat_goes_on(env):
    conn, root, fs = env
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="month:15")
    edits.clear_reminder(conn, root, fs, SETTINGS, "T000012", AT)
    assert Model(conn).task("T000012").reminder is None
    edits.reminders_to_today(conn, root, fs, SETTINGS, AT)
    m = Model(conn)
    assert m.task("T000012").reminder == "2026-11-15" and "T000012" not in [a.subject for a in m.today_items()]
    assert [e.via for e in m.status_log_of("T000012") if e.field == "Reminder"][-1] == edits.REPEATS


def test_later_holds_this_time_only(env):
    conn, root, fs = env
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="week:mon")
    edits.later(conn, root, fs, SETTINGS, "T000012", date(2026, 11, 18), AT)  # a Wednesday
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 11, 18, 9, 0))
    m = Model(conn)
    assert "T000012" in [a.subject for a in m.today_items()] and m.task("T000012").reminder == "2026-11-23"  # Mondays again


def test_it_ends_at_its_until_and_waits_while_closed(env):
    conn, root, fs = env
    tasks.update_task(conn, SETTINGS, "T000019", at=AT, via="Browse tool", reminder_repeat="week:tue", state="Closed")
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="month:15", reminder_until="2026-12-01")
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 11, 16, 9, 0))
    m = Model(conn)
    assert m.task("T000012").reminder is None  # the 15th came, and the next, 15 Dec, is past its Until
    assert "T000019" not in [a.subject for a in m.today_items()] and m.task("T000019").reminder == "2026-10-09"  # closed: it waits


def test_task_md_says_how_it_repeats(env, data_root, fs):
    conn, root, _ = env
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", reminder_repeat="workday:3", reminder_until="2027-06-30")
    from docrepo.pages import write_pages

    write_pages(Model(conn), root, fs, TUE, AT)
    page = next(root.rglob("T000012*/Task.md"), None) or next(p for p in root.rglob("Task.md") if "Rigging plan" in p.read_text(encoding="utf-8"))
    assert "Every month on its 3rd workday, until 2027-06-30" in page.read_text(encoding="utf-8")
