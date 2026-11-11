"""Reminders onto Today, Later and the due list waiting for a reminder (release 5.116, decisions 415, 417 and 418; the
design workspace's ``docs/mods/today-reminders-plan.md``). No Qt."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import capacity, db, edits, later
from docrepo.config import Settings
from docrepo.model import TODAY, Model
from docrepo.sample import load_sample
from docrepo.views import due_this_week, today_due_entries, entry_task

NOW = datetime(2026, 10, 8, 14, 10)  # a Thursday; the sample's reminders: T000016 yesterday, T000018 today, T000019 tomorrow
WEEK = frozenset(range(5))
SETTINGS = Settings(me="P001")


# ---- the days ----
@pytest.mark.parametrize("choice, day", [("1d", date(2026, 10, 9)), ("3d", date(2026, 10, 13)), ("1w", date(2026, 10, 15)),
                                         ("2w", date(2026, 10, 22)), ("1m", date(2026, 11, 9))])  # 8 Nov is a Sunday
def test_the_menus_days_from_a_thursday(choice, day):
    assert later.later_day(choice, NOW.date(), WEEK) == day


def test_tomorrow_on_a_friday_is_monday():
    friday = date(2026, 10, 9)
    assert later.later_day("1d", friday, WEEK) == date(2026, 10, 12)
    assert later.later_day("3d", friday, WEEK) == date(2026, 10, 14)


def test_a_month_on_from_the_31st_is_the_months_last_day_or_the_next_workday():
    assert later.later_day("1m", date(2027, 1, 29), WEEK) == date(2027, 3, 1)  # 28 Feb 2027 is a Sunday
    assert later.later_day("1m", date(2026, 12, 15), WEEK) == date(2027, 1, 15)


def test_other_reads_workdays_or_a_date():
    today = NOW.date()
    assert later.read_later("3", today, WEEK) == later.later_day("3d", today, WEEK)
    assert later.read_later("Tue", today, WEEK) == date(2026, 10, 13)
    assert later.read_later("15 Dec", today, WEEK) == date(2026, 12, 15)
    assert later.read_later("Sat", today, WEEK) == date(2026, 10, 12)  # moved to a workday
    for words in ("rubbish", "0", "today", "yesterday", ""):
        assert later.read_later(words, today, WEEK) is None


def test_with_no_workdays_set_every_day_counts():
    assert later.later_day("1d", date(2026, 10, 9), frozenset()) == date(2026, 10, 10)


# ---- the records ----
@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, NOW.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def test_a_reminder_puts_its_task_on_today_and_is_used_up(env):
    conn, root, fs = env
    used = edits.reminders_to_today(conn, root, fs, SETTINGS, NOW)
    m = Model(conn)
    assert used == ["T000016", "T000018"]  # not T000019, tomorrow's
    items = m.today_items()
    assert [(a.subject, a.added_by) for a in items] == [("T000016", edits.REMINDER), ("T000018", edits.REMINDER)]
    assert m.task("T000016").reminder is None and m.task("T000018").reminder is None and m.task("T000019").reminder == "2026-10-09"
    assert [e.via for e in m.status_log_of("T000018") if e.field == "Reminder"][-1] == edits.PUT_ON_TODAY
    assert edits.reminders_to_today(conn, root, fs, SETTINGS, NOW) == []  # nothing twice
    tomorrow = datetime(2026, 10, 9, 8, 0)
    assert edits.reminders_to_today(conn, root, fs, SETTINGS, tomorrow) == ["T000019"]


def test_a_task_already_on_today_just_has_its_reminder_cleared(env):
    conn, root, fs = env
    edits.add_to_today(conn, root, fs, "T000018", "", NOW)
    edits.reminders_to_today(conn, root, fs, SETTINGS, NOW)
    m = Model(conn)
    assert [a.subject for a in m.today_items()].count("T000018") == 1 and m.task("T000018").reminder is None


def test_a_closed_tasks_reminder_waits(env):
    conn, root, fs = env
    edits.change_task(conn, root, fs, SETTINGS, "T000018", NOW, state="Closed")
    edits.reminders_to_today(conn, root, fs, SETTINGS, NOW)
    m = Model(conn)
    assert "T000018" not in [a.subject for a in m.today_items()] and m.task("T000018").reminder == "2026-10-08"


def test_later_takes_an_item_off_today_and_its_reminder_brings_it_back(env):
    conn, root, fs = env
    edits.add_to_today(conn, root, fs, "T000012", "", NOW)
    item = next(a for a in Model(conn).today_items() if a.subject == "T000012")
    out = edits.later(conn, root, fs, SETTINGS, "T000012", date(2026, 10, 13), NOW, item.id)
    assert out.message == "Rigging plan: off Today until Tue 13 Oct, when its reminder puts it back on Today."
    m = Model(conn)
    closed = next(a for a in m.agenda if a.id == item.id)
    assert closed.how == "Removed" and closed.closed_by == edits.LATER and m.task("T000012").reminder == "2026-10-13"
    assert [e.via for e in m.status_log_of("T000012") if e.field == "Reminder"][-1] == edits.LATER
    assert edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 10, 12, 9, 0)) == ["T000016", "T000018", "T000019"]
    assert "T000012" not in [a.subject for a in Model(conn).today_items()]  # not before its day
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 10, 13, 9, 0))
    assert "T000012" in [a.subject for a in Model(conn).today_items()]


def test_laters_undo(env):
    conn, root, fs = env
    edits.add_to_today(conn, root, fs, "T000019", "", NOW)
    item = next(a for a in Model(conn).today_items() if a.subject == "T000019")
    edits.later(conn, root, fs, SETTINGS, "T000019", date(2026, 10, 20), NOW, item.id)
    edits.undo_later(conn, root, fs, SETTINGS, "T000019", "2026-10-09", NOW, item.id)
    m = Model(conn)
    assert any(a.id == item.id for a in m.today_items()) and m.task("T000019").reminder == "2026-10-09"


def test_later_needs_a_day_after_today(env):
    conn, root, fs = env
    with pytest.raises(edits.EditError):
        edits.later(conn, root, fs, SETTINGS, "T000012", NOW.date(), NOW)


def test_the_due_list_waits_for_a_reminder_still_to_come(env):
    conn, root, fs = env
    m = Model(conn)
    due = [t.id for t in due_this_week(m, NOW.date(), "P001")]
    assert due, "the sample has tasks due in the next 7 days"
    first = due[0]
    edits.later(conn, root, fs, SETTINGS, first, date(2026, 10, 12), NOW)  # Later from a due row: no Today item
    m = Model(conn)
    assert first not in [t.id for t in due_this_week(m, NOW.date(), "P001")]
    assert first not in [entry_task(e).id for e in today_due_entries(m, NOW.date(), "P001")]  # its key dates too
    assert not [a for a in m.agenda if a.target == TODAY and a.subject == first]
    assert first in [t.id for t in due_this_week(m, date(2026, 10, 12), "P001")] or m.task(first).reminder == "2026-10-12"
