"""Urgency within a priority (release 5.176, the design workspace's ``docs/mods/urgency-plan.md``, decisions 819 to 823),
without Qt: what makes a task on Today urgent, Today's one order with the urgent tasks first in each band, moves kept to
their half, and a bin's drop that ticks or unticks Urgent with its Undo. The sample's day is Thursday 8 October 2026, so
the second workday on is Monday 12 October."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pytest

from docrepo import agenda, edits, priorities, urgency, views
from docrepo.config import Settings
from docrepo.model import TODAY, Model

AT = datetime(2026, 10, 8, 15, 20)
DAY = AT.date()
WORK = frozenset(range(5))
SETTINGS = Settings(me="P001")


def dated(conn: sqlite3.Connection, task_id: str, due: str | None = None, deadline: str | None = None, urgent: bool = False,
          recurrence: str | None = None, start: str | None = None) -> None:
    conn.execute("UPDATE tasks SET due = ?, deadline = ?, urgent = ?, recurrence = ?, repeat_until = NULL, start = ? WHERE id = ?",
                 (due, deadline, int(urgent), recurrence, start, task_id))


def add(conn, subject=None, note="", added="2026-10-08 09:00:00") -> int:
    return agenda.add_item(conn, subject=subject, target=TODAY, note=note, added=added, added_by="Browse tool")


def order(conn) -> list[int]:
    return [a.id for a in views.today_order(Model(conn), DAY, WORK)]


# ---- what's urgent (decision 819) ----
@pytest.mark.parametrize(("fields", "urgent", "words"), [
    ({"urgent": True, "due": "2026-11-30"}, True, "ticked Urgent"),
    ({"due": "2026-10-07"}, True, "overdue since Wed 7 Oct"),
    ({"due": "2026-10-08"}, True, "due Thu 8 Oct"),
    ({"due": "2026-10-12"}, True, "due Mon 12 Oct"),  # the second workday on, across the weekend
    ({"due": "2026-10-10"}, True, "due Sat 10 Oct"),  # a weekend day before it
    ({"due": "2026-10-13"}, False, ""),  # the third workday on
    ({"deadline": "2026-10-09"}, True, "due Fri 9 Oct"),  # a Deadline with no Due
    ({}, False, ""),  # no date, no tick
])
def test_what_makes_a_task_on_today_urgent(sample_conn, fields, urgent, words):
    dated(sample_conn, "T000012", **fields)
    m = Model(sample_conn)
    assert urgency.is_urgent(m, "T000012", DAY, WORK) is urgent
    assert urgency.why(m, "T000012", DAY, WORK) == words


def test_a_routine_tasks_next_time_and_a_note(sample_conn):
    dated(sample_conn, "T000012", recurrence="Weekly", start="2026-10-05")  # Mondays: next on Mon 12 Oct
    m = Model(sample_conn)
    assert urgency.is_urgent(m, "T000012", DAY, WORK)
    assert not urgency.is_urgent(m, None, DAY, WORK) and urgency.why(m, None, DAY, WORK) == ""
    assert urgency.horizon(date(2026, 10, 9), WORK) == date(2026, 10, 13)  # Friday: Monday, then Tuesday
    assert urgency.horizon(DAY, frozenset({0, 1, 2, 3, 4, 5})) == date(2026, 10, 10)  # Saturdays worked


# ---- one order (decision 820) ----
@pytest.fixture
def band(sample_conn):
    """Four made-up tasks in High, in the owner's order a, b, c, d; b is due tomorrow and d ticked Urgent."""
    conn = sample_conn
    names = {"a": "T000012", "b": "T000016", "c": "T000018", "d": "T000019"}
    for k, t in names.items():
        dated(conn, t, due="2026-10-09" if k == "b" else "2026-11-30", urgent=k == "d")
        priorities.place(conn, t, "high", None, at=AT, via=priorities.VIA)
    ids = {k: add(conn, t, added=f"2026-10-08 08:0{n}:00") for n, (k, t) in enumerate(names.items())}
    note = add(conn, note="Sign the overtime sheets", added="2026-10-08 09:00:00")
    return conn, ids, note


def test_inside_a_band_the_urgent_tasks_come_first_each_half_in_the_owners_order(band):
    conn, i, note = band
    m = Model(conn)
    assert order(conn) == [i["b"], i["d"], i["a"], i["c"], note]
    (high, items), (none, notes) = [(k, its) for k, _, its in views.today_bands(m, DAY, WORK)]
    assert high == "high" and [a.id for a in items] == [i["b"], i["d"], i["a"], i["c"]] and [a.id for a in notes] == [note]
    assert [a.id for a in views.today_bands(m)[0][2]] == [i["a"], i["b"], i["c"], i["d"]]  # no day given: the owner's order alone
    assert [a.id for a in m.today_items()][:4] == [i["a"], i["b"], i["c"], i["d"]]  # the Model has no clock, and stays as it was
    assert views.today_half(m, next(a for a in items if a.id == i["b"]), urgency.urgent_ids(m, items, DAY, WORK)) == ("high", True)


def test_a_date_that_arrives_or_moves_out_changes_its_half_and_keeps_its_place(band):
    conn, i, _ = band
    dated(conn, "T000016", due="2026-11-30")  # b's date moved out: back among the rest, in its place
    assert order(conn)[:4] == [i["d"], i["a"], i["b"], i["c"]]
    dated(conn, "T000018", due="2026-10-12")  # c's arrives (Monday is the second workday on)
    assert order(conn)[:4] == [i["c"], i["d"], i["a"], i["b"]]


def test_a_move_stays_in_its_half(band, data_root, fs):
    conn, i, _ = band
    with pytest.raises(edits.EditError, match="Urgent tasks stay first in their band. Drop it on a bin to change that."):
        edits.move_today_item(conn, data_root, fs, i["a"], AT, beside=(i["b"], "before"), workdays=WORK)
    edits.move_today_item(conn, data_root, fs, i["c"], AT, beside=(i["a"], "before"), workdays=WORK)  # inside the rest
    assert order(conn)[:4] == [i["b"], i["d"], i["c"], i["a"]]
    out = edits.move_today_item(conn, data_root, fs, i["d"], AT, to="top", workdays=WORK)  # the top of the urgent half
    assert order(conn)[:4] == [i["d"], i["b"], i["c"], i["a"]] and "moved to the top" in out.message
    assert edits.move_today_item(conn, data_root, fs, i["a"], AT, to="down", workdays=WORK).message == ""  # the bottom of its half
    edits.move_today_item(conn, data_root, fs, i["c"], AT, to="bottom", workdays=WORK)
    assert order(conn)[:4] == [i["d"], i["b"], i["a"], i["c"]]
    with pytest.raises(edits.EditError):  # Monday to Friday when not given: the same halves
        edits.move_today_item(conn, data_root, fs, i["a"], AT, beside=(i["d"], "after"))


# ---- a bin's two parts (decision 822) ----
def test_a_bins_upper_part_ticks_urgent_and_its_lower_part_unticks_it(band, data_root, fs):
    conn, i, note = band
    out = edits.today_bin(conn, data_root, fs, i["c"], "medium", AT, urgent=True, settings=SETTINGS, workdays=WORK)
    m = Model(conn)
    assert m.task("T000018").priority == "medium" and m.task("T000018").urgent and out.message.endswith("Medium, urgent.")
    log = [(e.field, e.to_value, e.via) for e in m.status_log_of("T000018")]
    assert ("Urgent", "Yes", edits.TODAY_BINS) in log and ("Priority", "Medium", edits.TODAY_BINS) in log  # as Edit task's tick writes it
    # Its own band, the other part: the tick alone, the priority kept.
    out = edits.today_bin(conn, data_root, fs, i["d"], "high", AT, urgent=False, settings=SETTINGS, workdays=WORK)
    assert not Model(conn).task("T000019").urgent and Model(conn).task("T000019").priority == "high"
    assert out.message.endswith("High, not urgent.")
    assert order(conn)[:3] == [i["b"], i["a"], i["d"]]  # the end of the rest's half
    # Dropped on the lower part while its date makes it urgent anyway.
    out = edits.today_bin(conn, data_root, fs, i["b"], "high", AT, urgent=False, settings=SETTINGS, workdays=WORK)
    assert out.message == ""  # not ticked, and High already: nothing to change
    out = edits.today_bin(conn, data_root, fs, i["b"], "medium", AT, urgent=False, settings=SETTINGS, workdays=WORK)
    assert out.message.endswith("Medium. Still first: it's due Fri 9 Oct.")
    # None keeps the tick, as before.
    out = edits.today_bin(conn, data_root, fs, i["a"], "parking", AT, settings=SETTINGS)
    assert out.message.endswith("Parking lot. Its status log says so.") and not Model(conn).task("T000012").urgent


def test_a_bin_drop_is_undone_priority_tick_and_place(band, data_root, fs):
    conn, i, _ = band
    before = order(conn)
    out = edits.today_bin(conn, data_root, fs, i["a"], "critical", AT, urgent=True, settings=SETTINGS, workdays=WORK)
    assert out.undo is not None
    back = edits.undo_today_bin(conn, data_root, fs, out.undo, AT, settings=SETTINGS)
    m = Model(conn)
    assert m.task("T000012").priority == "high" and not m.task("T000012").urgent and order(conn) == before
    assert back.message == "Set back. The status log keeps both changes."
