"""Release 5.166, Log progress: the rest (the design workspace's docs/mods/log-progress-whole-plan.md, decisions 757, 759 and
761), without Qt: Back on Today for each state, on Today and off it, with a wait and without; Later's choices as the
follow-up's; an email attached to the Update; and the next step's task, its parents, its Today item and its wait. Every
name here is made up."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from docrepo import capacity, db, edits, progress, tasks, waits
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import EmailItem, SaveError

SETTINGS = Settings(me="P001")
AT = datetime(2026, 10, 8, 9, 0)  # a Thursday
TODAY = AT.date()
RIGGING, MIKE = "T000012", "P004"
MONDAY, NEXT_THU = date(2026, 10, 12), date(2026, 10, 15)


@pytest.fixture
def env(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, TODAY, SETTINGS)
    yield c, data_root, fs
    c.close()


def on_today(env, task: str = RIGGING) -> int:
    conn, root, fs = env
    edits.add_to_today(conn, root, fs, task, "", AT - timedelta(hours=1))
    return next(a.id for a in Model(conn).today_items() if a.subject == task)


def item(conn, item_id: int):
    return next(a for a in Model(conn).agenda if a.id == item_id)


def log(env, state: str, on=(), back: date | None = None, choice: str = "", done_today: bool = False, attached=None,
        line: str = "Sent Mike the revised lift points") -> progress.Logged:
    conn, root, fs = env
    return progress.log_progress(conn, root, fs, SETTINGS, task_id=RIGGING, line=line, on=list(on), follow_up=None, at=AT, state=state,
                                 back=back, choice=choice, done_today=done_today, attached=attached)


# ================= Back on Today (decision 757) =================
def test_the_choices_are_laters():
    assert [k for k, _ in progress.BACK] == ["1d", "3d", "1w", "2w", "1m"]
    assert waits.FOLLOW_UPS == progress.BACK  # Follow up's own list retired
    assert progress.back_day("1d", TODAY, range(5)) == date(2026, 10, 9)
    assert progress.back_day("1m", TODAY, range(5)) == date(2026, 11, 9)  # 8 Nov is a Sunday: the next workday
    assert progress.back_day("stays", TODAY, range(5)) is None
    assert waits.follow_up_day("2d", TODAY, range(5)) == MONDAY  # a choice remembered before 5.166
    assert waits.follow_up_day("none", TODAY, range(5)) is None


@pytest.mark.parametrize("state", [progress.IN_PROGRESS, progress.PARKED])
def test_back_without_a_wait_takes_it_off_today_and_sets_its_reminder(env, state):
    conn = env[0]
    n = on_today(env)
    done = log(env, state, back=MONDAY)
    t = Model(conn).task(RIGGING)
    assert t.reminder == "2026-10-12" and t.state == progress.TASK_STATE[state]
    assert item(conn, n).closed and item(conn, n).how == "Done" and done.done_today
    assert done.back == "2026-10-12" and done.follow_up is None and done.wait is None


def test_back_with_a_wait_is_its_follow_up_and_is_remembered(env):
    conn = env[0]
    n = on_today(env)
    done = log(env, progress.WAITING, on=(MIKE,), back=NEXT_THU, choice="1w")
    w = waits.current(Model(conn), RIGGING)
    assert w is not None and w.follow_up == "2026-10-15" and done.follow_up == "2026-10-15"
    assert Model(conn).task(RIGGING).reminder == "2026-10-15" and item(conn, n).closed
    assert waits.last_follow_up(conn) == "1w"


def test_a_wait_keeps_an_earlier_reminder_of_the_tasks_own(env):
    conn = env[0]
    tasks.update_task(conn, SETTINGS, RIGGING, at=AT - timedelta(days=1), via="test", reminder="2026-10-09")
    log(env, progress.WAITING, on=(MIKE,), back=NEXT_THU, choice="1w")
    assert Model(conn).task(RIGGING).reminder == "2026-10-09"  # decision 588: the own reminder comes first


def test_back_alone_moves_a_reminder(env):
    conn = env[0]
    tasks.update_task(conn, SETTINGS, RIGGING, at=AT - timedelta(days=1), via="test", reminder="2026-10-09")
    log(env, progress.IN_PROGRESS, back=NEXT_THU)
    assert Model(conn).task(RIGGING).reminder == "2026-10-15"  # as Later sets it


def test_back_off_today_sets_the_day_it_comes_on(env):
    conn = env[0]
    done = log(env, progress.IN_PROGRESS, back=MONDAY)
    assert Model(conn).task(RIGGING).reminder == "2026-10-12" and not done.done_today


def test_stays_leaves_today_and_the_reminder_alone(env):
    conn = env[0]
    n = on_today(env)
    before = Model(conn).task(RIGGING).reminder
    done = log(env, progress.IN_PROGRESS)
    assert not item(conn, n).closed and Model(conn).task(RIGGING).reminder == before and done.back is None


def test_closed_takes_no_day(env):
    conn = env[0]
    n = on_today(env)
    done = log(env, progress.CLOSED, back=MONDAY)
    t = Model(conn).task(RIGGING)
    assert t.state == "Closed" and t.reminder != "2026-10-12" and done.back is None and item(conn, n).closed


# ================= an email attached (decision 759) =================
def test_an_attached_email_is_kept_on_the_update(env):
    conn = env[0]
    email = EmailItem("Lift points", "Mike Ortiz", "2026-10-08 08:40", "Me", "Points B and D moved 200 mm.")
    done = log(env, progress.IN_PROGRESS, attached=email, line="Mike moved the lift points")
    c = Model(conn).captures[done.capture]
    assert "update" in c.types and [e.subject for e in c.emails] == ["Lift points"] and c.task == RIGGING
    assert Model(conn).task(RIGGING).current_status == "Mike moved the lift points"


# ================= the next step (decision 761) =================
def test_the_next_step_goes_under_the_logged_tasks_parent_on_today(env):
    conn, root, fs = env
    parent = Model(conn).parents_of(RIGGING)[0]
    nxt = progress.log_next(conn, root, fs, SETTINGS, parent=parent, title="Book the crane", state=progress.NOT_STARTED, on=[], at=AT)
    m = Model(conn)
    t = m.task(nxt.task)
    assert t.title == "Book the crane" and m.parents_of(nxt.task) == [parent] and t.state == "Not started" and nxt.on_today
    assert any(a.subject == nxt.task for a in m.today_items())
    assert not any(c.task == nxt.task for c in m.captures.values())  # no Update: nothing done on it yet


def test_the_next_step_waiting_starts_its_wait_and_comes_back_on_its_day(env):
    conn, root, fs = env
    nxt = progress.log_next(conn, root, fs, SETTINGS, parent=None, title="Hear back on the crane", state=progress.WAITING, on=[MIKE],
                            at=AT, today=True, back=MONDAY, choice="1d")
    m = Model(conn)
    t = m.task(nxt.task)
    assert m.parents_of(nxt.task) == [] and t.state == "In progress" and t.reminder == "2026-10-12" and not nxt.on_today
    w = waits.current(m, nxt.task)
    assert w is not None and w.on == (MIKE,) and w.follow_up == "2026-10-12"
    assert not any(a.subject == nxt.task for a in m.today_items())


def test_the_next_step_refuses_what_it_cant_make(env):
    conn, root, fs = env
    with pytest.raises(SaveError):
        progress.log_next(conn, root, fs, SETTINGS, parent=None, title="  ", state=progress.NOT_STARTED, on=[], at=AT)
    with pytest.raises(SaveError):
        progress.log_next(conn, root, fs, SETTINGS, parent=None, title="Chase it", state=progress.WAITING, on=[], at=AT)
    tasks.update_task(conn, SETTINGS, RIGGING, at=AT, via="test", state="Closed")
    with pytest.raises(SaveError):
        progress.log_next(conn, root, fs, SETTINGS, parent=RIGGING, title="After it", state=progress.NOT_STARTED, on=[], at=AT)
