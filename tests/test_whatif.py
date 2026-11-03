"""What-ifs (release 5.64; decisions 226 to 228 and 290): changes kept by name that change no task, worked out by making them in a
transaction that's always rolled back, and applied as a deliberate last step through the same calls."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from docrepo import capacity, db, edits, load, tasks, whatif
from docrepo.config import Settings
from docrepo.model import Model, Tie, load_tasks
from docrepo.tasks import KeyDateRow

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")
WHO = "P004"


@pytest.fixture
def conn(sample_conn):
    capacity.rebuild_all(sample_conn, TODAY, SETTINGS)
    return sample_conn


def make(conn, title: str, **values) -> str:
    values.setdefault("assignees", [WHO])
    values.setdefault("assignee_hours", 20)
    return tasks.create_task(conn, SETTINGS, title=title, at=NOW, created_by="Test", **values)


def everything(conn) -> str:
    """All that a what-if must never change."""
    out = []
    for table in ("tasks", "work_calendar", "status_log", "task_dates", "task_ties", "task_parents", "app_state"):
        out.append(json.dumps([tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")], default=str))
    return "\n".join(out)


def picture(conn, w):
    return whatif.picture(conn, SETTINGS, w, NOW, Model(conn))


def week_hours(cells, week: str) -> float:
    return load.week_hours(cells, WHO, date.fromisoformat(week))


def trial(conn) -> tuple[str, str, str]:
    """A trial with two steps, the second tied to start the workday after the first ends, and a key date."""
    top = make(conn, "Trial 7", assignees=[], assignee_hours=None)
    a = make(conn, "Set up the line", parents=[top], start="2026-11-02", due="2026-11-06")
    b = make(conn, "Run the trial", parents=[top], start="2026-11-09", due="2026-11-13")
    tasks.update_task(conn, SETTINGS, b, at=NOW, via="Test", ties={"start": Tie(a, amount=1)})
    tasks.set_key_dates(conn, top, [KeyDateRow("2026-11-09", "2026-11-13", "Trial window")], at=NOW, via="Test")
    return top, a, b


# ---- a picture changes nothing ----
def test_a_picture_changes_nothing_and_shows_the_change(conn):
    t = make(conn, "Big job", start="2026-11-02", due="2026-11-06")
    before = everything(conn)
    w = whatif.WhatIf("W1", "Later")
    whatif.add(w, whatif.move(Model(conn), t, "2026-11-16", "2026-11-20"))
    pic = picture(conn, w)
    assert everything(conn) == before
    assert not conn.in_transaction
    assert pic.model.task(t).start == "2026-11-16" and Model(conn).task(t).start == "2026-11-02"
    weeks = load.mondays(date(2026, 11, 2), date(2026, 11, 23))
    real = capacity.week_cells(conn, weeks)
    cells = whatif.cells(real, pic, weeks)
    assert week_hours(real, "2026-11-02") >= 20 and week_hours(cells, "2026-11-02") == pytest.approx(week_hours(real, "2026-11-02") - 20)
    assert week_hours(cells, "2026-11-16") == pytest.approx(week_hours(real, "2026-11-16") + 20)


def test_a_picture_wont_start_inside_another_transaction(conn):
    w = whatif.WhatIf("W1", "x")
    with db.transaction(conn), pytest.raises(RuntimeError):
        picture(conn, w)


def test_taking_off_parks_a_task_and_whats_open_under_it(conn):
    top, a, b = trial(conn)
    tasks.update_task(conn, SETTINGS, a, at=NOW, via="Test", state="Closed")
    w = whatif.WhatIf("W1", "Drop trial 7")
    whatif.add(w, whatif.take_off(Model(conn), top))
    assert w.actions[0].off == [top, b]  # the closed one isn't taken off
    pic = picture(conn, w)
    assert pic.model.task(b).state == "Parked" and pic.off == {top, b}
    assert whatif.drawn(pic, Model(conn)).task(b).state == "Not started"  # still a row on the chart, to put back
    weeks = load.mondays(date(2026, 11, 9), date(2026, 11, 16))
    assert week_hours(whatif.cells(capacity.week_cells(conn, weeks), pic, weeks), "2026-11-09") == pytest.approx(
        week_hours(capacity.week_cells(conn, weeks), "2026-11-09") - 20)


def test_whats_tied_to_a_moved_task_moves_with_it(conn):
    top, a, b = trial(conn)
    w = whatif.WhatIf("W1", "Later")
    whatif.add(w, whatif.move(Model(conn), a, "2026-11-16", "2026-11-20"))
    pic = picture(conn, w)
    assert pic.model.task(b).start == "2026-11-23"
    assert pic.done[0].followed == [b] and b in pic.touched
    assert load_tasks(conn, [b])[b].start == "2026-11-09"


# ---- a whole parent (decision 290) ----
def test_a_whole_parent_moves_in_weeks_with_its_key_dates_and_no_gap_counts_twice(conn):
    top, a, b = trial(conn)
    routine = make(conn, "Weekly check", parents=[top], start="2026-11-02", recurrence="Weekly", assignee_hours=1)
    tasks.update_task(conn, SETTINGS, b, at=NOW, via="Test", deadline="2026-11-20")
    m = Model(conn)
    act = whatif.move_parent(m, top, 2)
    assert set(act.dates) == {a, b} and routine not in act.dates
    w = whatif.WhatIf("W1", "Two weeks later")
    whatif.add(w, act)
    pic = picture(conn, w)
    after = pic.model
    assert (after.task(a).start, after.task(a).due) == ("2026-11-16", "2026-11-20")
    assert (after.task(b).start, after.task(b).due) == ("2026-11-23", "2026-11-27")  # moved once, by its tie, not twice
    assert after.task(b).deadline == "2026-11-20" and after.task(routine).start == "2026-11-02"
    assert [(k.start, k.end) for k in after.key_dates_of(top)] == [("2026-11-23", "2026-11-27")]
    assert whatif.past_deadline(m, pic) == [b]


def test_done_and_deadline_key_dates_stay_put(conn):
    top = make(conn, "Trial 8", start="2026-11-02", due="2026-11-06")
    tasks.set_key_dates(conn, top, [KeyDateRow("2026-11-03", "2026-11-03", "Kick-off", done=True),
                                    KeyDateRow(None, "2026-11-20", "Report due", deadline=True),
                                    KeyDateRow("2026-11-04", "2026-11-05", "Samples")], at=NOW, via="Test")
    act = whatif.move_parent(Model(conn), top, 1)
    kds = {k.description: k.id for k in Model(conn).key_dates_of(top)}
    assert set(act.keys) == {kds["Samples"]}


# ---- out of date, and applying ----
def test_a_change_whose_task_changed_since_is_out_of_date_and_left_out(conn):
    t = make(conn, "Big job", start="2026-11-02", due="2026-11-06")
    u = make(conn, "Small job", start="2026-11-02", due="2026-11-03")
    w = whatif.WhatIf("W1", "Shuffle")
    whatif.add(w, whatif.move(Model(conn), t, "2026-11-16", "2026-11-20"))
    whatif.add(w, whatif.move(Model(conn), u, "2026-11-09", "2026-11-10"))
    tasks.update_task(conn, SETTINGS, t, at=NOW, via="Test", due="2026-11-09")
    m = Model(conn)
    assert whatif.stale(m, w.actions[0]) == [t] and not whatif.stale(m, w.actions[1])
    assert whatif.out_of_date(m, w) == 1
    lines = whatif.lines(m, w, picture(conn, w), TODAY)
    assert lines[0].stale == ["Big job"] and not lines[1].stale


def test_apply_makes_the_ticked_changes_logged_as_the_what_if(conn, data_root, fs):
    top, a, b = trial(conn)
    other = make(conn, "Big job", start="2026-11-02", due="2026-11-06")
    w = whatif.WhatIf("W1", "Plan B")
    whatif.add(w, whatif.move(Model(conn), a, "2026-11-16", "2026-11-20"))
    whatif.add(w, whatif.take_off(Model(conn), other))
    out = edits.apply_whatif(conn, data_root, fs, SETTINGS, w, {1}, NOW)
    after = load_tasks(conn)
    assert after[a].start == "2026-11-16" and after[b].start == "2026-11-23" and after[other].state == "Not started"
    assert "Applied 1 change from Plan B" in out.message and "Moved 1 tied task" in out.message
    log = {(r["task"], r["field"]): r["via"] for r in conn.execute("SELECT * FROM status_log ORDER BY id")}  # the latest of each
    assert log[(a, "Start")] == "What-if: Plan B" and log[(b, "Start")].startswith("Follows ")


def test_apply_shows_what_the_picture_showed(conn, data_root, fs):
    top, a, b = trial(conn)
    w = whatif.WhatIf("W1", "Later")
    whatif.add(w, whatif.move_parent(Model(conn), top, 3))
    pic = picture(conn, w)
    edits.apply_whatif(conn, data_root, fs, SETTINGS, w, (), NOW)
    m = Model(conn)
    for x in pic.touched:
        assert (m.task(x).start, m.task(x).due, m.task(x).state) == (pic.model.task(x).start, pic.model.task(x).due, pic.model.task(x).state)
        assert sorted((p, d.isoformat(), round(h, 6)) for p, d, h in pic.hours[x]) == sorted(
            (r["person"], r["date"], round(r["hours"], 6)) for r in conn.execute("SELECT * FROM work_calendar WHERE task = ?", (x,)))


def test_one_change_that_cant_be_made_leaves_the_rest(conn, data_root, fs):
    t = make(conn, "Big job", start="2026-11-02", due="2026-11-06")
    w = whatif.WhatIf("W1", "x")
    w.actions.append(whatif.Action("key", t, keys={99999: ("2026-11-09", "2026-11-10")}))
    whatif.add(w, whatif.move(Model(conn), t, "2026-11-16", "2026-11-20"))
    pic = picture(conn, w)
    assert pic.done[0].problem and pic.model.task(t).start == "2026-11-16"
    out = edits.apply_whatif(conn, data_root, fs, SETTINGS, w, (), NOW)
    assert load_tasks(conn, [t])[t].start == "2026-11-16" and "couldn't be made" in " ".join(out.problems)


# ---- the list ----
def test_moving_a_bar_again_replaces_its_move_and_keeps_what_it_was(conn):
    t = make(conn, "Big job", start="2026-11-02", due="2026-11-06")
    m = Model(conn)
    w = whatif.WhatIf("W1", "x")
    whatif.add(w, whatif.move(m, t, "2026-11-09", "2026-11-13"))
    whatif.add(w, whatif.take_off(m, t))
    assert not whatif.add(w, whatif.take_off(m, t))
    whatif.add(w, whatif.move(m, t, "2026-11-16", "2026-11-20"))
    assert [a.kind for a in w.actions] == ["off", "dates"]
    assert w.actions[1].base[t] == ["2026-11-02", "2026-11-06", "Not started"]
    assert whatif.put_back(w, t) and [a.kind for a in w.actions] == ["dates"]


def test_what_ifs_are_kept_and_read_back_as_data(conn):
    t = make(conn, "Big job", start="2026-11-02", due="2026-11-06")
    ws: list[whatif.WhatIf] = []
    w = whatif.new(ws, "  Drop   trial 7 ")
    whatif.add(w, whatif.move_parent(Model(conn), t, -1))
    whatif.new(ws)
    whatif.save_all(conn, ws)
    back = whatif.load_all(conn)
    assert [(x.id, x.name) for x in back] == [("W1", "Drop trial 7"), ("W2", "What-if 2")]
    assert back[0].actions[0].dates == {t: {"start": "2026-10-26", "due": "2026-10-30"}}
    db.set_state(conn, whatif.KEY, '[{"id": "W1", "name": "x", "actions": [{"kind": "rm -rf", "task": "T1"}, {"kind": "dates"}]}, 5, "x"]')
    assert [(x.name, x.actions) for x in whatif.load_all(conn)] == [("x", [])]
    db.set_state(conn, whatif.KEY, "not json")
    assert whatif.load_all(conn) == []


def test_the_review_says_each_thing_done_once(conn):
    top, a, b = trial(conn)
    other = make(conn, "Big job", start="2026-11-02", due="2026-11-06")
    m = Model(conn)
    w = whatif.WhatIf("W1", "x")
    whatif.add(w, whatif.take_off(m, top))
    whatif.add(w, whatif.move(m, other, "2026-11-16", "2026-11-20"))
    whatif.add(w, whatif.move(m, a, "2026-11-04", "2026-11-12"))
    said = whatif.lines(m, w, picture(conn, w), TODAY)
    assert said[0].title == "Trial 7 and 2 under it" and said[0].says == ["Taken off: Parked, so its hours stop counting."]
    assert said[1].says == ["Moved 2 weeks later, now 16 Nov to 20 Nov, hours kept."]
    assert said[2].says[0].startswith("Now 4 Nov to 12 Nov") and said[2].says[1] == "Run the trial tied to it moves with it."


# ---- the sentence ----
def test_the_sentence_says_the_real_plan_beside_a_what_ifs():
    w1, w2 = date(2026, 11, 2), date(2026, 11, 16)
    now, real = load.Case([w1], w1, 12.0, {WHO: 1}), load.Case([w1, w2], w2, 30.0, {WHO: 2})
    assert load.sentence(now, str, TODAY, real)[0] == "Over in the week of 2 Nov (2 weeks on the real plan), by 12 h (30 h)."
    assert load.sentence(load.Case(), str, TODAY, real)[0] == "Nobody is over in this range (2 weeks on the real plan)."
    assert load.sentence(real, str, TODAY, now)[0] == "Over in 2 weeks (1 on the real plan), the worst the week of 16 Nov, by 30 h (12 h)."
    assert load.sentence(now, str, TODAY, now)[0] == "Over in the week of 2 Nov (1 week on the real plan), by 12 h."  # the same hours aren't said twice
