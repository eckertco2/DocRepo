"""Release 5.155, Log progress's State and Done for today (the design workspace's docs/mods/log-progress-choices-plan.md,
decisions 695 to 697), without Qt: each state with and without people, Closed (the task alone, and its Today item), Done
for today with and without a follow-up, and 5.139's rule kept when no state is given. Every name here is made up."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from docrepo import capacity, db, edits, progress, tasks, waits
from docrepo.config import Settings
from docrepo.model import TODAY as TODAY_TARGET
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import SaveError

SETTINGS = Settings(me="P001")
AT = datetime(2026, 10, 8, 9, 0)  # a Thursday
TODAY = AT.date()
RIGGING, INSTALLATION, Q4_COST = "T000012", "T000008", "T000003"
PRIYA, MIKE = "P002", "P004"


@pytest.fixture
def env(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, TODAY, SETTINGS)
    yield c, data_root, fs
    c.close()


def logged(env, state: str | None, on=(MIKE,), choice: str = "3d", done_today: bool = False, task: str = RIGGING,
           line: str = "Sent Mike the revised lift points", at: datetime = AT) -> progress.Logged:
    conn, root, fs = env
    day = progress.follow_up_day(choice, at.date(), range(5))
    return progress.log_progress(conn, root, fs, SETTINGS, task_id=task, line=line, on=list(on), follow_up=day, at=at, choice=choice,
                                 state=state, done_today=done_today)


def on_today(env, task: str = RIGGING, at: datetime = AT - timedelta(hours=1)) -> int:
    conn, root, fs = env
    edits.add_to_today(conn, root, fs, task, "", at)
    return next(a.id for a in Model(conn).today_items() if a.subject == task)


def item(conn, item_id: int):
    return next(a for a in Model(conn).agenda if a.id == item_id)


def updates(conn, task: str) -> int:
    return sum(1 for c in Model(conn).captures.values() if c.task == task and "update" in c.types)


# ================= the choices (decision 695) =================
def test_the_four_choices_in_order():
    assert [words for _, words, _ in progress.STATES] == ["In progress", "Waiting on a reply", "Parked", "Closed"]
    assert progress.TASK_STATE[progress.WAITING] == "In progress"  # a wait is a mark, not a state (decision 580)
    assert "Not started" not in progress.TASK_STATE.values()


def test_waiting_with_people_starts_a_wait_and_its_follow_up(env):
    conn = env[0]
    done = logged(env, progress.WAITING)
    m = Model(conn)
    w = waits.current(m, RIGGING)
    assert w is not None and w.on == (MIKE,) and done.wait == w.id and done.follow_up == "2026-10-13"
    assert m.task(RIGGING).state == "In progress" and m.task(RIGGING).reminder == "2026-10-13"
    assert done.state == "In progress" and not done.done_today


def test_waiting_with_nobody_keeps_nothing(env):
    conn = env[0]
    before = updates(conn, RIGGING)
    with pytest.raises(SaveError) as e:
        logged(env, progress.WAITING, on=())
    assert e.value.focus == "who" and str(e.value) == progress.NOBODY
    with pytest.raises(SaveError):
        logged(env, progress.WAITING, on=("P999",))  # nobody in People
    m = Model(conn)
    assert updates(conn, RIGGING) == before and m.waits == [] and m.task(RIGGING).current_status != "Sent Mike the revised lift points"


def test_in_progress_with_people_starts_no_wait(env):
    conn = env[0]
    done = logged(env, progress.IN_PROGRESS, choice="1w")
    m = Model(conn)
    assert done.wait is None and done.follow_up is None and waits.current(m, RIGGING) is None
    assert m.task(RIGGING).reminder is None and m.task(RIGGING).current_status == "Sent Mike the revised lift points"
    assert progress.last_follow_up(conn) == "3d"  # no wait, so the choice isn't remembered


def test_in_progress_takes_a_parked_task_back_up(env):
    conn = env[0]
    done = logged(env, progress.IN_PROGRESS, on=(), task=Q4_COST, line="Restarted the overtime numbers")
    assert done.state == "In progress" and Model(conn).task(Q4_COST).state == "In progress"


@pytest.mark.parametrize("on", [(), (MIKE, PRIYA)])
def test_parked_parks_with_the_line_and_no_wait(env, on):
    conn = env[0]
    done = logged(env, progress.PARKED, on=on, line="On hold until the crane is booked")
    m = Model(conn)
    t = m.task(RIGGING)
    assert (t.state, t.current_status, t.reminder) == ("Parked", "On hold until the crane is booked", None)
    assert done.state == "Parked" and done.wait is None and waits.current(m, RIGGING) is None
    assert any(e.field == "State" and e.to_value == "Parked" and e.via == done.capture for e in m.status if e.task == RIGGING)
    assert m.captures[done.capture].types == ["update"]


def test_parked_on_a_parked_task_keeps_it_parked(env):
    conn = env[0]
    done = logged(env, progress.PARKED, on=(), task=Q4_COST, line="Still waiting for the budget round")
    t = Model(conn).task(Q4_COST)
    assert done.state == "Parked" and t.state == "Parked" and t.current_status == "Still waiting for the budget round"


# ================= Closed (decision 696) =================
def test_closed_closes_the_task_alone_and_its_open_subtasks_stay_open(env):
    conn = env[0]
    open_below = [x for x in Model(conn).descendants_of(INSTALLATION) if Model(conn).task(x).state != "Closed"]
    assert open_below  # Rigging plan and two more
    done = logged(env, progress.CLOSED, on=(MIKE,), task=INSTALLATION, line="Installation signed off")
    m = Model(conn)
    t = m.task(INSTALLATION)
    assert (t.state, t.closed, t.current_status) == ("Closed", "2026-10-08", "Installation signed off")
    assert all(m.task(x).state != "Closed" for x in open_below)
    assert done.state == "Closed" and done.wait is None and not done.done_today  # not on Today: nothing to close


def test_closed_closes_its_today_item_as_done(env):
    conn = env[0]
    item_id = on_today(env, INSTALLATION)
    done = logged(env, progress.CLOSED, on=(), task=INSTALLATION, line="Installation signed off")
    a = item(conn, item_id)
    assert done.done_today and a.how == "Done" and a.closed and a.closed_by == "Today"
    m = Model(conn)
    assert all(x.subject != INSTALLATION for x in m.today_items()) and item_id in [x.id for x in m.done_on(TODAY)]


def test_closed_ends_a_wait_the_task_had(env):
    conn = env[0]
    logged(env, progress.WAITING)
    logged(env, progress.CLOSED, on=(), line="Mike agreed the lift points", at=AT + timedelta(hours=2))
    m = Model(conn)
    assert waits.current(m, RIGGING) is None and m.task(RIGGING).state == "Closed"


# ================= Done for today (decision 697) =================
def test_done_for_today_closes_the_item_with_no_update_of_its_own(env):
    conn = env[0]
    item_id = on_today(env)
    before = updates(conn, RIGGING)
    done = logged(env, progress.IN_PROGRESS, on=(), done_today=True, line="Called the crane company")
    a = item(conn, item_id)
    assert done.done_today and a.how == "Done" and a.target == TODAY_TARGET
    assert updates(conn, RIGGING) == before + 1  # the line's own Update, and no other
    assert Model(conn).task(RIGGING).state == "In progress"
    edits.back_on_today(conn, env[1], env[2], item_id, AT + timedelta(hours=1))  # Back on Today puts it back
    assert any(x.id == item_id for x in Model(conn).today_items())


def test_done_for_today_with_a_follow_up_comes_back_on_its_day(env):
    conn, root, fs = env
    item_id = on_today(env)
    done = logged(env, progress.WAITING, done_today=True)
    assert done.done_today and item(conn, item_id).how == "Done" and done.follow_up == "2026-10-13"
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 10, 12, 8, 0))
    assert all(x.subject != RIGGING for x in Model(conn).today_items())  # not before its day
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 10, 13, 8, 0))
    back = [x for x in Model(conn).today_items() if x.subject == RIGGING]
    assert len(back) == 1 and back[0].id != item_id and back[0].added_by == edits.REMINDER


def test_done_for_today_off_today_does_nothing(env):
    conn = env[0]
    done = logged(env, progress.WAITING, done_today=True)
    assert not done.done_today and waits.current(Model(conn), RIGGING) is not None


def test_unticked_the_item_stays_on_today(env):
    conn = env[0]
    item_id = on_today(env)
    done = logged(env, progress.PARKED, on=())
    assert not done.done_today and not item(conn, item_id).closed


# ================= 5.139's callers, unchanged =================
def test_no_state_keeps_5_139s_rule(env):
    conn = env[0]
    item_id = on_today(env)
    done = logged(env, None)
    assert done.wait is not None and done.state == "In progress" and not done.done_today and not item(conn, item_id).closed
    started = tasks.create_task(conn, SETTINGS, title="Order the spare seal", at=AT, created_by="test", state="Not started")
    assert logged(env, None, on=(), task=started).state == "In progress"
    parked = logged(env, None, on=(), task=Q4_COST, line="Picked the overtime numbers up again")
    assert parked.state == "In progress" and parked.wait is None


def test_an_unknown_state_is_refused(env):
    with pytest.raises(ValueError, match="Not a Log progress state"):
        logged(env, "Not started", on=())

