"""Release 5.128, the weekly review (the cold-eyes plan's section 6, decisions 496 to 503), without Qt: schema 27's two
fields, who comes up for review and when (by the week), Mark reviewed with no status log line, Review every in the status
log, Gone quiet counting what's under a task, No next step's rule, Waiting on others' longest wait first, each step's
count and the steps Next passes over, the review in hand and Today's line, what Done counts, Settings, and the task
page's and Task.md's Reviewed. The sample's today is Thursday 8 October 2026; the review day is Friday the 9th. Every name
here is made up."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import pytest

from docrepo import capacity, conversations, db, edits, review, tasks
from docrepo.config import Settings
from docrepo.detail import Pages
from docrepo.model import TODAY as TODAY_TARGET
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.views import VIEWS, list_tree
from docrepo.lists import LISTS

SETTINGS = Settings(me="P001")
FRI = date(2026, 10, 9)
AT = datetime(2026, 10, 9, 9, 0)
REACTOR, WALKTHROUGH, COST, HOLIDAY, SAFETY, MEETING = "T000001", "T000002", "T000003", "T000016", "T000006", "T000010"
INSTALLATION, RIGGING = "T000008", "T000012"


@pytest.fixture
def conn(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, FRI, SETTINGS)
    yield c
    c.close()


def make(conn, title: str, at: datetime = AT, **kw) -> str:
    return tasks.create_task(conn, SETTINGS, title=title, at=at, created_by="test", **kw)


# ================= schema 27 =================
def test_schema_27_adds_reviewed_and_review_every(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    assert {"reviewed", "review_every"} <= cols
    assert db.SCHEMA_VERSION == 27  # 26 is 5.127's meeting links, merged first
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tasks SET review_every = 3 WHERE id = ?", (REACTOR,))
    t = Model(conn).task(REACTOR)
    assert t.reviewed is None and t.review_every is None


def test_the_version_26_root_comes_up_with_no_reviews_and_its_asks_and_meeting_link_kept(tmp_path):
    import zipfile
    from pathlib import Path

    from docrepo.safe_fs import SafeFS

    root = tmp_path / "DocRepoData-v26"  # schema 26 is 5.127's meeting links; 27 is this release's
    with zipfile.ZipFile(Path(__file__).resolve().parent / "fixtures" / "roots" / "v26.zip") as z:
        z.extractall(root)
    c = db.connect(SafeFS([root]), root)
    try:
        m = Model(c)
        assert all(t.reviewed is None and t.review_every is None for t in m.tasks.values())
        assert sorted((x.task, x.kind) for x in m.t_mails) == [("T000008", "new"), (RIGGING, "ask")]
        assert [t.id for t in review.due_for_review(m, FRI, 1)] == [REACTOR, WALKTHROUGH, HOLIDAY]
        assert c.execute("SELECT task FROM meeting_links").fetchall()[0][0] == "T000010"
    finally:
        c.close()


def test_the_review_view_is_second_in_the_sidebar():
    assert [v.id for v in VIEWS][:3] == ["today", "review", "unfiled"]


# ================= intervals (decisions 498 and 499) =================
def test_projects_come_up_weekly_and_standing_work_doesnt(conn):
    m = Model(conn)
    assert review.interval(m, m.task(REACTOR), 1) == 1
    assert review.interval(m, m.task(REACTOR), 2) == 2  # Settings' interval
    assert review.interval(m, m.task(INSTALLATION), 1) == 0  # a subtask, with none of its own
    assert review.interval(m, m.task(SAFETY), 1) == 0  # routine
    assert review.interval(m, m.task(MEETING), 1) == 0  # a meeting
    tasks.update_task(conn, SETTINGS, INSTALLATION, at=AT, via="test", review_every=2)
    tasks.update_task(conn, SETTINGS, REACTOR, at=AT, via="test", review_every=0)
    m = Model(conn)
    assert review.interval(m, m.task(INSTALLATION), 1) == 2  # its own
    assert review.interval(m, m.task(REACTOR), 1) == 0  # never


@pytest.mark.parametrize(("reviewed", "weeks", "today", "due"), [
    (None, 1, FRI, True),  # never reviewed
    ("2026-10-02 16:00:00", 1, FRI, True),  # last Friday
    ("2026-10-03 10:00:00", 1, FRI, True),  # a day late last week: still due this Friday, as counted by the week
    ("2026-10-05 08:00:00", 1, FRI, False),  # on Monday this week
    ("2026-10-02 16:00:00", 2, FRI, False),
    ("2026-10-02 16:00:00", 2, date(2026, 10, 12), True),
    ("2026-09-11 16:00:00", 4, FRI, True),
])
def test_a_project_is_due_by_the_week(conn, reviewed, weeks, today, due):
    tasks.set_reviewed(conn, {REACTOR: reviewed})
    m = Model(conn)
    assert review.is_due(m, m.task(REACTOR), today, weeks) is due


def test_due_for_review_over_the_sample_in_tree_order(conn):
    m = Model(conn)
    # Parked (Q4 cost reduction, Line 2 extruder), closed, routine and meeting tasks aren't; subtasks have no interval.
    assert [t.id for t in review.due_for_review(m, FRI, 1)] == [REACTOR, WALKTHROUGH, HOLIDAY]
    tasks.update_task(conn, SETTINGS, RIGGING, at=AT, via="test", review_every=1)
    assert [t.id for t in review.due_for_review(Model(conn), FRI, 1)] == [REACTOR, RIGGING, WALKTHROUGH, HOLIDAY]


def test_mark_reviewed_keeps_the_time_and_nothing_in_the_status_log(conn, data_root, fs):
    before = len(Model(conn).status)
    out = edits.mark_reviewed(conn, data_root, fs, SETTINGS, REACTOR, AT)
    m = Model(conn)
    assert m.task(REACTOR).reviewed == "2026-10-09 09:00:00"
    assert len(m.status) == before  # decision 503: no history
    assert out.message == "Reactor impeller upgrade: reviewed. It comes up again in the week of Mon 12 Oct."
    assert REACTOR not in {t.id for t in review.due_for_review(m, FRI, 1)}
    assert "| Reviewed | 2026-10-09 |" in (data_root / "Tasks" / REACTOR / "Task.md").read_text(encoding="utf-8")
    back = edits.set_reviewed(conn, data_root, fs, REACTOR, None, AT)  # Undo
    assert Model(conn).task(REACTOR).reviewed is None and back.message.endswith("not reviewed yet.")


def test_review_every_goes_into_the_status_log_in_words(conn):
    logged = tasks.update_task(conn, SETTINGS, REACTOR, at=AT, via="Browse tool", review_every=2)
    assert [(c.field, c.from_value, c.to_value) for c in logged] == [("Review every", None, "Every 2 weeks")]
    logged = tasks.update_task(conn, SETTINGS, REACTOR, at=AT, via="Browse tool", review_every=0)
    assert [(c.from_value, c.to_value) for c in logged] == [("Every 2 weeks", "Never")]
    assert tasks.update_task(conn, SETTINGS, REACTOR, at=AT, via="Browse tool", review_every=0) == []
    for wrong in (3, -1, True, "2"):
        with pytest.raises(tasks.TaskError):
            tasks.update_task(conn, SETTINGS, REACTOR, at=AT, via="Browse tool", review_every=wrong)


def test_the_task_pages_facts_say_reviewed(conn):
    tasks.set_reviewed(conn, {REACTOR: "2026-10-02 16:00:00"})
    tasks.update_task(conn, SETTINGS, WALKTHROUGH, at=AT, via="test", review_every=4)
    m = Model(conn)
    pages = Pages(m, FRI, lambda _: "", "P001")
    rows = dict(pages.when_rows(m.task(REACTOR)))
    assert rows["Reviewed"] == 'Fri 2 Oct <span class="rel">7 days ago</span>'
    assert dict(pages.when_rows(m.task(WALKTHROUGH)))["Review"] == "Every 4 weeks"
    assert "Reviewed" not in dict(pages.when_rows(m.task(HOLIDAY)))


# ================= gone quiet and no next step (decisions 500 and 501) =================
def test_gone_quiet_counts_whats_under_a_task(conn):
    lube = make(conn, "Lube oil analysis contract", datetime(2026, 8, 17, 10, 0), leads=["P001"])
    tags = make(conn, "Check eyewash station tags", datetime(2026, 8, 24, 11, 0), parents=[HOLIDAY])
    m = Model(conn)
    quiet = review.gone_quiet(m, FRI, 21)
    assert quiet == {lube: 53, tags: 46}  # Verification walkthrough readiness's own status is old, but its subtasks are busy
    assert review.gone_quiet(m, FRI, 50) == {lube: 53}
    assert review.gone_quiet(m, FRI, 21, {lube}) == {tags: 46}  # step 4's are left out
    # Anything on it or under it wakes it: a status change on the subtask.
    tasks.update_task(conn, SETTINGS, tags, at=datetime(2026, 10, 1, 9, 0), via="test", current_status="Half done.")
    assert tags not in review.gone_quiet(Model(conn), FRI, 21)


def test_gone_quiet_leaves_out_standing_work_and_whats_closed_or_parked(conn):
    m = Model(conn)
    quiet = review.gone_quiet(m, date(2027, 6, 1), 21)
    assert SAFETY not in quiet and MEETING not in quiet  # routine, a meeting
    assert COST not in quiet and "T000005" not in quiet  # parked, closed
    assert REACTOR in quiet


def test_a_project_marked_reviewed_in_this_review_isnt_asked_about_again(conn):
    lube = make(conn, "Lube oil analysis contract", datetime(2026, 8, 17, 10, 0), leads=["P001"])
    m = Model(conn)
    assert lube in review.looked_at(m, FRI, 1, "2026-10-09 08:50:00")  # in step 4: never reviewed
    tasks.set_reviewed(conn, {lube: "2026-10-09 09:00:00"})
    m = Model(conn)
    assert lube not in {t.id for t in review.due_for_review(m, FRI, 1)}
    assert lube in review.looked_at(m, FRI, 1, "2026-10-09 08:50:00")  # reviewed since the review started
    assert lube not in review.looked_at(m, FRI, 1, "2026-10-09 09:30:00")


def test_no_next_step_follows_decision_501(conn):
    lube = make(conn, "Lube oil analysis contract", leads=["P001"])
    m = Model(conn)
    assert [t.id for t in review.no_next_step(m, FRI)] == [lube]  # the sample's projects all have one
    for change in ({"due": "2026-11-02"}, {"deadline": "2026-11-02"}, {"reminder": "2026-10-20"}):
        tasks.update_task(conn, SETTINGS, lube, at=AT, via="test", **change)
        assert review.no_next_step(Model(conn), FRI) == []
        tasks.update_task(conn, SETTINGS, lube, at=AT, via="test", **{k: None for k in change})
    sub = make(conn, "Ask the lab for prices", parents=[lube])
    assert review.no_next_step(Model(conn), FRI) == []
    tasks.update_task(conn, SETTINGS, sub, at=AT, via="test", state="Closed")
    assert [t.id for t in review.no_next_step(Model(conn), FRI)] == [lube]  # a closed subtask isn't a next step
    conn.execute("INSERT INTO agenda_items (subject, target, note, added, added_by) VALUES (?, ?, '', '2026-10-09 08:00', 'Browse tool')",
                 (lube, TODAY_TARGET))
    assert review.no_next_step(Model(conn), FRI) == []


# ================= step 3's order =================
def test_waiting_on_others_puts_the_longest_wait_first(conn):
    m = Model(conn)
    waiting = next(x for x in LISTS if x.id == "waiting")
    nodes = review.longest_first(m, list_tree(m, waiting, FRI, "P001"))
    order = [n.id for n in review.walk(nodes) if n.match]
    updated = {n: review.waited_days(m, n, FRI) for n in order}
    tops = [n.id for n in nodes]
    assert tops == sorted(tops, key=lambda x: -max(review.waited_days(m, y, FRI) for y in [x, *m.descendants_of(x)] if y in updated))
    assert review.waited_days(m, RIGGING, FRI) == 3


# ================= each step's count, and Next =================
def test_each_steps_count_over_the_sample(conn):
    m = Model(conn)
    assert review.counts(m, FRI, "P001", 1, 21) == {"unfiled": 3, "due": 3, "waiting": 8, "projects": 3, "quiet": 0, "nonext": 0, "done": 0}
    assert review.place_line(2, 8) == "Step 3 of 7 · Waiting on others · 8"
    assert review.place_line(6, 0) == "Step 7 of 7 · Done"


def test_next_passes_over_empty_steps_and_says_so():
    have = {"unfiled": 3, "due": 0, "waiting": 8, "projects": 0, "quiet": 0, "nonext": 0}
    assert review.step_after(0, have) == (2, [1])
    assert review.step_after(2, have) == (6, [3, 4, 5])
    assert review.step_after(6, have, back=True) == (2, [5, 4, 3])
    assert review.step_after(2, have, back=True) == (0, [1])
    assert review.passed_line([1]) == "Nothing overdue or due in the next 7 days."
    assert review.passed_line([3, 4, 5]) == "No project due for review, nothing gone quiet and no project without a next step."
    assert review.passed_line([6]) == ""


# ================= the review in hand, and Today's line (decisions 502 and 503) =================
def test_a_review_carries_on_until_its_done_or_set_aside():
    s, fresh = review.begin(review.Session(), AT)
    assert fresh and s.started == "2026-10-09 09:00:00" and s.step == 0
    s.step = 3
    again, fresh = review.begin(s, datetime(2026, 10, 12, 8, 0))
    assert not fresh and again.step == 3  # carried on on Monday
    _, fresh = review.begin(s, datetime(2026, 10, 16, 8, 0))
    assert fresh  # set aside after a week
    done = review.finish(s, datetime(2026, 10, 9, 10, 0))
    assert done.finished == done.last_finished == "2026-10-09 10:00:00" and done.step == 6
    nxt, fresh = review.begin(done, datetime(2026, 10, 9, 11, 0))
    assert fresh and nxt.last_finished == "2026-10-09 10:00:00" and nxt.finished is None
    assert review.read_session(nxt.to_json()) == nxt
    assert review.read_session("not json") == review.Session()
    assert review.read_session(json.dumps({"step": 99, "other": 1})).step == 0


def test_todays_line_is_on_the_review_day_until_a_review_is_finished():
    s = review.Session()
    assert review.offer_today(s, FRI, "Fri")
    assert not review.offer_today(s, date(2026, 10, 8), "Fri")  # Thursday
    assert review.offer_today(s, date(2026, 10, 8), "Thu")
    started, _ = review.begin(s, AT)
    assert review.offer_today(started, FRI, "Fri") and review.in_hand(started, FRI)
    done = review.finish(started, datetime(2026, 10, 9, 10, 0))
    assert not review.offer_today(done, FRI, "Fri")
    early = review.finish(started, datetime(2026, 10, 8, 16, 0))  # done on Thursday: Friday doesn't ask again
    assert not review.offer_today(early, FRI, "Fri")
    assert review.offer_today(done, date(2026, 10, 16), "Fri")  # next week it does


def test_done_counts_what_happened_since_the_review_started(conn, data_root, fs):
    started = "2026-10-09 09:00:00"
    assert review.did(Model(conn), started) == []
    assert review.did_line([]) == "Nothing changed during this review."
    capture = Model(conn).unfiled_captures()[0].id
    edits.file_capture(conn, data_root, fs, capture, REACTOR, datetime(2026, 10, 9, 9, 5))
    edits.mark_reviewed(conn, data_root, fs, SETTINGS, REACTOR, datetime(2026, 10, 9, 9, 10))
    edits.mark_reviewed(conn, data_root, fs, SETTINGS, WALKTHROUGH, datetime(2026, 10, 9, 9, 12))
    conversations.record_t_mail(conn, RIGGING, "ask", "2026-10-09 09:15:00", "", untagged=True)
    edits.set_states(conn, data_root, fs, SETTINGS, {"T000015": "Parked"}, datetime(2026, 10, 9, 9, 20))
    tasks.update_task(conn, SETTINGS, "T000009", at=datetime(2026, 10, 9, 9, 25), via="test", due="2026-10-30")
    did = review.did(Model(conn), started)
    assert did == [("filed", 1), ("reviewed", 2), ("asked", 1), ("parked", 1), ("dates moved", 1)]
    assert review.did_line(did) == "Filed 1, reviewed 2, asked 1, parked 1, dates moved on 1."
    assert review.did(Model(conn), "2026-10-09 09:21:00") == [("dates moved", 1)]


def test_since_group_holds_whats_happened_since_the_last_review(conn):
    from docrepo.activity import Activity

    m = Model(conn)
    lines = Activity(m, FRI).lines(date(2026, 9, 1), FRI)
    g = review.since_group(m, lines, m.task(REACTOR), "2026-10-06 00:00", review.tree_order(m))
    assert g.lines and all(x.at > "2026-10-06 00:00" for x in g.lines)
    assert {x.task for x in g.lines} <= {REACTOR, *m.descendants_of(REACTOR)}
    assert g.headings[0].task == REACTOR or all(h.task != REACTOR for h in g.headings)
    assert review.since(m.task(REACTOR), FRI, 1) == "2026-10-02 00:00"  # never reviewed: its interval back
    tasks.set_reviewed(conn, {REACTOR: "2026-10-02 16:30:00"})
    assert review.since(Model(conn).task(REACTOR), FRI, 1) == "2026-10-02 16:30"


# ================= Settings =================
def test_settings_keep_the_review_day_and_interval(data_root, fs):
    s = Settings()
    assert (s.review_day, s.review_weeks, s.quiet_days) == ("Fri", 1, 21)
    s.save(fs, data_root)
    saved = json.loads((data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert "review_day" not in saved and "review_weeks" not in saved  # written once changed, as quiet_days is
    s.review_day, s.review_weeks = "Mon", 2
    s.save(fs, data_root)
    assert (Settings.load(data_root).review_day, Settings.load(data_root).review_weeks) == ("Mon", 2)
    (data_root / "Config" / "settings.json").write_text(json.dumps({"review_day": "Friday", "review_weeks": 3}), encoding="utf-8")
    loaded = Settings.load(data_root)
    assert (loaded.review_day, loaded.review_weeks) == ("Fri", 1)  # ignored, with a warning
