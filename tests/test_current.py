"""The current task (release 5.177, the design workspace's docs/mods/current-task-plan.md, decisions 825 and 827), without Qt:
one task kept in ``app_state``, cleared by ``get`` when it's closed, discarded or made a collection; another task taking
its place; Log progress with Done for today or Closed ending it in its own transaction, and a failed one leaving it as
it was. Every name here is made up."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from docrepo import capacity, collection_edits, current, db, edits, progress, tasks, waits
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.sample import load_sample

SETTINGS = Settings(me="P001")
AT = datetime(2026, 10, 8, 9, 0)
RIGGING, HOLIDAY, INSTALL = "T000012", "T000016", "T000008"


@pytest.fixture
def env(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, AT.date(), SETTINGS)
    yield c, data_root, fs
    c.close()


def now(conn) -> str | None:
    return current.get(conn, Model(conn))


def test_start_get_and_stop(env):
    conn, _, _ = env
    assert now(conn) is None
    current.start(conn, RIGGING)
    assert now(conn) == RIGGING and current.is_current(conn, Model(conn), RIGGING)
    current.start(conn, HOLIDAY)  # another takes its place, without asking
    assert now(conn) == HOLIDAY
    current.stop(conn)
    assert now(conn) is None and current.stored(conn) is None


def test_it_clears_itself_for_a_closed_task_a_discarded_one_and_a_collection(env):
    conn, root, fs = env
    current.start(conn, RIGGING)
    tasks.update_task(conn, SETTINGS, RIGGING, at=AT, via="test", state="Closed")
    assert now(conn) is None and current.stored(conn) is None  # cleared, not only hidden
    current.start(conn, HOLIDAY)
    edits.discard_task(conn, root, fs, SETTINGS, HOLIDAY, "Made by mistake", AT)
    assert now(conn) is None
    current.start(conn, INSTALL)
    collection_edits.make_collection(conn, root, fs, SETTINGS, INSTALL, AT)
    assert now(conn) is None
    current.start(conn, "T999999")  # gone
    assert now(conn) is None


def test_taking_it_off_today_doesnt_end_it(env):
    conn, root, fs = env
    edits.add_to_today(conn, root, fs, RIGGING, "", AT)
    current.start(conn, RIGGING)
    item = next(a for a in Model(conn).today_items() if a.subject == RIGGING)
    edits.close_today_item(conn, root, fs, item.id, "Removed", AT)
    assert now(conn) == RIGGING


def log(env, state: str, done_today: bool = False) -> progress.Logged:
    conn, root, fs = env
    return progress.log_progress(conn, root, fs, SETTINGS, task_id=RIGGING, line="Crane booked for Tuesday", on=[], follow_up=None, at=AT,
                                 state=state, done_today=done_today)


@pytest.mark.parametrize(("state", "done_today", "ends"), [(progress.IN_PROGRESS, True, True), (progress.CLOSED, False, True),
                                                           (progress.IN_PROGRESS, False, False), (progress.PARKED, False, False)])
def test_log_progress_ends_it_with_done_for_today_or_closed(env, state, done_today, ends):
    conn, _, _ = env
    current.start(conn, RIGGING)
    log(env, state, done_today)
    assert (current.stored(conn) is None) is ends


def test_log_progress_on_another_task_leaves_it(env):
    conn, _, _ = env
    current.start(conn, HOLIDAY)
    log(env, progress.CLOSED)
    assert now(conn) == HOLIDAY


def test_a_failed_log_progress_leaves_it_as_it_was(env, monkeypatch):
    conn, root, fs = env
    current.start(conn, RIGGING)

    def busy(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(waits, "start", busy)
    with pytest.raises(progress.NotAllKept):
        progress.log_progress(conn, root, fs, SETTINGS, task_id=RIGGING, line="Asked Mike for the quote", on=["P004"],
                              follow_up=progress.follow_up_day("3d", AT.date(), range(5)), at=AT, state=progress.WAITING, done_today=True)
    assert current.stored(conn) == RIGGING
