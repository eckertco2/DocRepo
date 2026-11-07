"""Release 5.48, decision 259: a selected bar's lines to what it's tied to and what's tied to it, and what a drag takes with it
before it's saved, worked out by the same rules the save uses. No window is needed: the chart's own lines and preview are in
``test_timeline_drags.py``."""
from __future__ import annotations

from datetime import date, datetime

from docrepo import tasks, timeline
from docrepo.config import Settings
from docrepo.model import Model, Tie, load_tasks
from docrepo.tasks import KeyDateRow

NOW = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
WEEK = frozenset(range(5))


def make(conn, title: str, **values) -> str:
    return tasks.create_task(conn, SETTINGS, title=title, at=NOW, created_by="Test", **values)


def tie(conn, task_id: str, **ties) -> None:
    tasks.update_task(conn, SETTINGS, task_id, at=NOW, via="Test", ties=ties)


def dates(conn, *ids: str) -> dict[str, tuple]:
    found = load_tasks(conn, list(ids))
    return {x: (found[x].start, found[x].due, found[x].duration) for x in ids}


def shown(after: dict, *ids: str) -> dict[str, tuple]:
    return {x: (after[x].start, after[x].due, after[x].duration) for x in ids if x in after}


def chain(conn) -> tuple[str, str, str]:
    """Set up the line (Mon 2 to Fri 6 Nov, 5 workdays); run the trial, 3 workdays, starting the workday after it ends; and write the
    report, two plain dates three workdays apart, starting 2 workdays after the trial ends: Fri 13 to Tue 17 Nov."""
    a = make(conn, "Set up the line", start="2026-11-02", duration=5)
    b = make(conn, "Run the trial", start="2026-11-09", duration=3)
    c = make(conn, "Write the report", start="2026-11-16", due="2026-11-18")
    tie(conn, b, start=Tie(a, amount=1))
    tie(conn, c, start=Tie(b, amount=2))
    return a, b, c


def drag(conn, task_id: str, start: str, end: str, mode: str) -> tuple[dict, dict]:
    """What the chart shows for a drop, then what saving it makes: both, for the tasks that follow."""
    m = Model(conn)
    before = m.task(task_id)
    after = timeline.dropped(before, *timeline.drop_dates(before, date.fromisoformat(start), date.fromisoformat(end), mode), WEEK)
    preview = timeline.follows(m, {task_id: after}, {}, WEEK)
    sent = timeline.drop_dates(before, date.fromisoformat(start), date.fromisoformat(end), mode)
    tasks.update_task(conn, SETTINGS, task_id, at=NOW, via="Browse tool", dragged=True, start=sent[0], due=sent[1])
    return preview, dates(conn, *preview)


def test_a_chain_of_two_ties_previews_as_its_saved(sample_conn):
    a, b, c = chain(sample_conn)
    assert dates(sample_conn, b, c) == {b: ("2026-11-09", "2026-11-11", 3), c: ("2026-11-13", "2026-11-17", None)}
    preview, saved = drag(sample_conn, a, "2026-11-09", "2026-11-13", "move")  # a week later
    assert shown(preview, b, c) == saved
    assert saved == {b: ("2026-11-16", "2026-11-18", 3), c: ("2026-11-20", "2026-11-24", None)}


def test_a_stretched_source_moves_what_follows_its_end(sample_conn):
    a, b, c = chain(sample_conn)
    preview, saved = drag(sample_conn, a, "2026-11-02", "2026-11-04", "end")  # ends Wednesday
    assert shown(preview, b, c) == saved
    assert saved == {b: ("2026-11-05", "2026-11-09", 3), c: ("2026-11-11", "2026-11-13", None)}


def test_a_due_tied_before_a_start_moves_its_start(sample_conn):
    trial = make(sample_conn, "Run the trial", start="2026-11-09", due="2026-11-13")
    prep = make(sample_conn, "Order the parts", start="2026-11-02", duration=2)
    tie(sample_conn, prep, due=Tie(trial, point="start", amount=3, direction="before"))
    preview, saved = drag(sample_conn, trial, "2026-11-16", "2026-11-20", "move")
    assert shown(preview, prep) == saved
    assert saved == {prep: ("2026-11-10", "2026-11-11", 2)}


def test_a_closed_task_stays_and_so_does_what_follows_it(sample_conn):
    a, b, c = chain(sample_conn)
    tasks.update_task(sample_conn, SETTINGS, b, at=NOW, via="Test", state="Closed")
    preview, saved = drag(sample_conn, a, "2026-11-09", "2026-11-13", "move")
    assert preview == {} and saved == {}
    assert dates(sample_conn, b, c) == {b: ("2026-11-09", "2026-11-11", 3), c: ("2026-11-13", "2026-11-17", None)}


def test_a_key_dates_move_previews_as_its_saved(sample_conn):
    outage = make(sample_conn, "Line 2 outage")
    tasks.set_key_dates(sample_conn, outage, [KeyDateRow("2026-11-09", "2026-11-13", "Shutdown")], at=NOW, via="Test")
    key_id = Model(sample_conn).key_dates_of(outage)[0].id
    restart = make(sample_conn, "Restart checks", start="2026-11-16", duration=2)
    tie(sample_conn, restart, start=Tie(outage, amount=1, key_date=key_id))
    m = Model(sample_conn)
    preview = timeline.follows(m, {}, {key_id: ("2026-11-16", "2026-11-20")}, WEEK)
    tasks.set_key_dates(sample_conn, outage, [KeyDateRow("2026-11-16", "2026-11-20", "Shutdown", id=key_id)], at=NOW, via="Test", settings=SETTINGS)
    assert shown(preview, restart) == dates(sample_conn, restart) == {restart: ("2026-11-23", "2026-11-24", 2)}
    assert timeline.follows(m, {outage: m.task(outage)}, {}, WEEK) == {}  # a task's key dates don't follow its dates


def test_a_selected_bars_lines_go_both_ways(sample_conn):
    a, b, c = chain(sample_conn)
    outage = make(sample_conn, "Line 2 outage")
    tasks.set_key_dates(sample_conn, outage, [KeyDateRow("2026-11-09", "2026-11-13", "Shutdown")], at=NOW, via="Test")
    key_id = Model(sample_conn).key_dates_of(outage)[0].id
    tie(sample_conn, c, start=Tie(b, amount=2), due=Tie(outage, amount=1, key_date=key_id))
    m = Model(sample_conn)
    assert timeline.tie_links(m, b) == [timeline.TieLink(a, None, "end", b, "start"), timeline.TieLink(b, None, "end", c, "start")]
    assert timeline.tie_links(m, outage) == [timeline.TieLink(outage, key_id, "end", c, "due")]
    assert timeline.tie_links(m, c) == [timeline.TieLink(outage, key_id, "end", c, "due"), timeline.TieLink(b, None, "end", c, "start")]
    assert timeline.tie_links(m, make(sample_conn, "Untied")) == []  # nothing otherwise


def test_where_a_tie_counts_from():
    assert timeline.tie_day("start", "2026-11-02", "2026-11-06") == date(2026, 11, 2)
    assert timeline.tie_day("end", "2026-11-02", "2026-11-06") == date(2026, 11, 6)
    assert timeline.tie_day("start", None, "2026-11-06") is None  # a task with no Start has no start yet
    assert timeline.tie_day("start", None, "2026-11-06", either=True) == date(2026, 11, 6)  # a key date with one date has it at both ends
