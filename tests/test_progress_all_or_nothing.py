"""Release 5.164, Log progress all or nothing (the design workspace's docs/mods/log-progress-whole-plan.md, decision 754),
without Qt: the Update is kept first, as ``save_capture`` keeps it (it writes capture.md and pages, so it can't join a
transaction of its own caller's); everything after it (the T-mail, the wait, the last follow-up, the Today item) is one
transaction, so a failure there keeps none of it and says so, and a second Enter, given the Update kept, keeps no second
Update. And a sent draft let go of (decision 751). Every name here is made up."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from docrepo import capacity, db, edits, progress, sent_watch, waits
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.sample import load_sample

SETTINGS = Settings(me="P001")
AT = datetime(2026, 10, 8, 9, 0)  # a Thursday
TODAY = AT.date()
RIGGING, MIKE = "T000012", "P004"


@pytest.fixture
def env(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, TODAY, SETTINGS)
    yield c, data_root, fs
    c.close()


def log(env, kept: str | None = None, email: progress.Email | None = None, done_today: bool = False) -> progress.Logged:
    conn, root, fs = env
    day = progress.follow_up_day("3d", TODAY, range(5))
    return progress.log_progress(conn, root, fs, SETTINGS, task_id=RIGGING, line="Asked Mike for the crane vendor's quote", on=[MIKE],
                                 follow_up=day, at=AT, email=email, choice="3d", state=progress.WAITING, done_today=done_today,
                                 kept=kept)


def updates(conn) -> int:
    return sum(1 for c in Model(conn).captures.values() if c.task == RIGGING and "update" in c.types)


def t_mails(conn) -> int:
    return conn.execute("SELECT count(*) FROM t_mails").fetchone()[0]


def busy(*args, **kwargs):
    raise sqlite3.OperationalError("database is locked")


def test_a_failure_after_the_update_keeps_no_half_and_says_so(env, monkeypatch):
    conn, root, fs = env
    edits.add_to_today(conn, root, fs, RIGGING, "", AT - timedelta(hours=1))
    before_t_mails = t_mails(conn)
    monkeypatch.setattr(waits, "start", busy)
    with pytest.raises(progress.NotAllKept) as e:
        log(env, email=progress.Email("Crane quote", "", "D1", "S1"), done_today=True)
    assert str(e.value) == "The update was kept. The wait wasn't started: press Enter to try again."
    assert e.value.capture and e.value.focus == "content"
    m = Model(conn)
    assert updates(conn) == 1 and m.task(RIGGING).current_status == "Asked Mike for the crane vendor's quote"
    # The T-mail made before the wait went back with it, and its draft; nothing after it was done.
    assert t_mails(conn) == before_t_mails and sent_watch.drafts(conn) == {}
    assert waits.current(m, RIGGING) is None and db.get_state(conn, progress.LAST_KEY) is None
    assert any(a.subject == RIGGING for a in m.today_items())


def test_a_second_enter_after_a_half_keeps_no_second_update(env, monkeypatch):
    conn = env[0]
    monkeypatch.setattr(waits, "start", busy)
    with pytest.raises(progress.NotAllKept) as e:
        log(env)
    monkeypatch.undo()
    done = log(env, kept=e.value.capture)
    assert updates(conn) == 1 and done.capture == e.value.capture
    w = waits.current(Model(conn), RIGGING)
    assert w is not None and w.on == (MIKE,) and w.capture == done.capture


def test_a_failure_at_the_update_keeps_nothing(env, monkeypatch):
    conn = env[0]
    monkeypatch.setattr(progress, "save_capture", busy)
    with pytest.raises(sqlite3.OperationalError):
        log(env)
    assert updates(conn) == 0 and waits.current(Model(conn), RIGGING) is None


def test_the_draft_sent_by_docrepo_is_let_go_and_kept_again_if_outlook_refuses(env):
    conn = env[0]
    done = log(env, email=progress.Email("Crane quote", "", "D1", "S1"))
    assert sent_watch.drafts(conn)[done.t_mail].gone == ""
    progress.sending(conn, done, "Crane quote", AT)
    assert sent_watch.drafts(conn)[done.t_mail].how == sent_watch.BY_DOCREPO
    progress.not_sent(conn, done)
    assert sent_watch.drafts(conn)[done.t_mail].how == ""
    progress.sending(conn, progress.Logged(RIGGING, "", None, None, "In progress", None, None), "x", AT)  # no T-mail: nothing
