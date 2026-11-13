"""Follow-ups under the work (release 5.142, the design workspace's notes consolidation plan, decision 610): a task made in
meeting notes goes under its # task, else the meeting's home task, never under the meeting. Every name here is made up."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import save
from docrepo.model import Model
from docrepo.save import CaptureDraft, NewTaskFields, save_capture
from notes_example import SETTINGS, build


@pytest.fixture
def ex(sample_root):
    conn, root, fs = sample_root
    return build(conn, root, fs)


def new_task(sample_root, title: str, parent: str | None = None, **fields) -> str:
    conn, root, fs = sample_root
    return save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=title, task=parent, types={"new_task"},
                                                             new_task=NewTaskFields(title=title, **fields)), datetime(2026, 11, 2, 8, 0)).created_task


def notes(sample_root, task: str | None, text: str, name: str = "", at: datetime = datetime(2026, 11, 13, 10, 0)):
    conn, root, fs = sample_root
    return save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=text, task=task, meeting=True, meeting_name=name), at)


def made(conn, r) -> dict[str, str]:
    m = Model(conn)
    return {m.tasks[m.captures[c].created_task].title: m.captures[c].created_task for c in r.items if m.captures[c].created_task}


def test_the_example_s_follow_ups_are_under_the_project(sample_root, ex):
    m = Model(sample_root[0])
    for task in (ex.survey, ex.fill, ex.crane, ex.blades):
        assert m.parents_of(task) == [ex.project], m.tasks[task].title
    assert m.parents_of(ex.rig) == [ex.crane]  # under its # heading's task alone, not the meeting as well
    assert m.children_of(ex.kickoff) == [] and m.children_of(ex.weekly) == []
    # Each follow-up's capture is still the meeting's record, from its notes.
    item = next(c for c in m.captures.values() if c.created_task == ex.fill)
    assert item.task == ex.kickoff and item.from_notes == ex.kickoff_notes and item.item == "task"
    assert m.parents_of(ex.kickoff) == [ex.project] and m.parents_of(ex.weekly) == [ex.project]


def test_a_regular_meeting_s_follow_ups_go_under_the_task_above_its_series(sample_root, ex):
    conn = sample_root[0]
    series = new_task(sample_root, "Cooling tower weekly", ex.project, meeting=True, recurrence="Weekly")
    r = notes(sample_root, series, "- Basin drain valve @Tom")
    m = Model(conn)
    assert m.parents_of(r.meeting) == [series]  # this time's meeting, under the series
    assert m.parents_of(made(conn, r)["Basin drain valve"]) == [ex.project]
    assert save.meeting_home(conn, r.meeting) == ex.project and save.follow_up_home(m, series) == ex.project


def test_a_cross_project_series_keeps_its_follow_ups(sample_root):
    conn = sample_root[0]
    series = new_task(sample_root, "Plant operations meeting", meeting=True, recurrence="Weekly")
    r = notes(sample_root, series, "- Check the cooling water chemistry @Priya")
    assert Model(conn).parents_of(made(conn, r)["Check the cooling water chemistry"]) == [series]


def test_a_meeting_with_nothing_above_it_holds_its_follow_ups(sample_root):
    conn = sample_root[0]
    r = notes(sample_root, None, "- Order the spare impeller @Tyler", name="Vendor call")
    m = Model(conn)
    assert m.parents_of(made(conn, r)["Order the spare impeller"]) == [r.meeting]
    assert save.follow_up_home(m, None) is None


def test_a_task_under_a_task_item_and_a_named_task_are_as_before(sample_root, ex):
    conn = sample_root[0]
    conn, root, fs = sample_root
    text = "- Fan stack repair @Mike\n  - @Tom order the bolts\n- @Priya check the delivery dates #Fill media order"
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=text, task=ex.project, meeting=True, meeting_name="Fan stack check-in",
                                                          refs={"#fill media order": ex.fill}), datetime(2026, 11, 13, 10, 0))
    m = Model(conn)
    ids = made(conn, r)
    assert m.parents_of(ids["Fan stack repair"]) == [ex.project]
    assert m.parents_of(next(v for k, v in ids.items() if "bolts" in k)) == [ids["Fan stack repair"]]  # under its task item, as before
    assert m.parents_of(next(v for k, v in ids.items() if "delivery dates" in k)) == [ex.fill]  # its # task alone


def test_notes_and_decisions_with_no_task_stay_the_meeting_s(sample_root, ex):
    conn = sample_root[0]
    r = notes(sample_root, ex.project, "**decision, the basin is cleaned in the outage.", name="Basin check-in")
    m = Model(conn)
    decision = next(m.captures[c] for c in r.items if m.captures[c].item == "decision")
    assert decision.task == r.meeting


def test_where_follow_ups_will_go_before_save(sample_root, ex):
    m = Model(sample_root[0])
    assert save.follow_up_home(m, ex.project) == ex.project  # a new meeting under the project
    assert save.follow_up_home(m, ex.kickoff) == ex.project  # the one-off kickoff


# ---- decision 611: Subtasks lists the work; a meeting's page lists its Follow-ups ----
def page(sample_root, task_id: str, **state) -> dict[str, str]:
    import re

    from docrepo.captures import read_content
    from docrepo.detail import Pages, PageState

    m = Model(sample_root[0])
    parts = Pages(m, datetime(2026, 11, 13).date(), lambda cid: read_content(sample_root[1], m.captures[cid])).task_parts(task_id, PageState(**state))
    return {k: " ".join(re.sub(r"<[^>]+>", " ", v).replace("&nbsp;", " ").split()) for k, v in parts.items()}


def test_subtasks_lists_the_work_and_meetings_lists_the_meetings(sample_root, ex):
    p = page(sample_root, ex.project)
    assert p["subtasks_short"] == "4 of 4 open"
    for title in ("Structural survey of the fan deck", "Fill media order", "Crane for the fan lift", "Fan blade inspection"):
        assert title in p["subtasks"]
    assert "Cooling tower kickoff" not in p["subtasks"] and "Cooling tower kickoff" in p["meetings"]
    assert "follow_ups" not in p


def test_a_meeting_lists_its_follow_ups(sample_root, ex):
    p = page(sample_root, ex.kickoff)
    assert "subtasks" not in p and p["follow_ups_short"] == "3 made here · 3 open"
    assert p["follow_ups"].startswith("Structural survey of the fan deck · under Cooling tower 2 rebuild")
    assert "Fill media order · under Cooling tower 2 rebuild" in p["follow_ups"]
    weekly = page(sample_root, ex.weekly)["follow_ups"]
    assert "Fan blade inspection · under Cooling tower 2 rebuild" in weekly and "Rig the east cell first · under Crane for the fan lift" in weekly


def test_a_series_lists_its_occurrences_in_meetings(sample_root, ex):
    series = new_task(sample_root, "Cooling tower weekly", ex.project, meeting=True, recurrence="Weekly")
    r = notes(sample_root, series, "- Basin drain valve @Tom")
    p = page(sample_root, series)
    assert "subtasks" not in p and "follow_ups" not in p  # its occurrence is a meeting; the valve is under the project
    assert Model(sample_root[0]).task(r.meeting).title in p["meetings"]


# ---- decision 612: Tidy ----
def as_before(sample_root, ex) -> None:
    """The example's tree as Meeting notes made it before release 5.142: each follow-up under its meeting."""
    from docrepo import tasks

    conn = sample_root[0]
    at = datetime(2026, 11, 10, 10, 0)
    for task, parents in ((ex.survey, [ex.kickoff]), (ex.fill, [ex.kickoff]), (ex.crane, [ex.kickoff]),
                          (ex.blades, [ex.weekly]), (ex.rig, [ex.crane, ex.weekly])):
        tasks.set_parents(conn, task, parents, at=at, via="test")


def test_tidy_finds_the_follow_ups_still_under_their_meetings(sample_root, ex):
    from docrepo import edits

    as_before(sample_root, ex)
    hand = new_task(sample_root, "Agenda for the next session", ex.kickoff)  # put under the meeting by hand: not a follow-up
    m = Model(sample_root[0])
    moves = edits.follow_ups_to_tidy(m, edits.meetings_in(m, ex.project))
    assert [(mv.task, mv.meeting, mv.parents) for mv in moves] == [
        (ex.survey, ex.kickoff, [ex.project]), (ex.fill, ex.kickoff, [ex.project]), (ex.crane, ex.kickoff, [ex.project]),
        (ex.blades, ex.weekly, [ex.project]), (ex.rig, ex.weekly, [ex.crane])]
    assert hand not in [mv.task for mv in moves]
    assert [mv.task for mv in edits.follow_ups_to_tidy(m, edits.meetings_in(m, ex.kickoff))] == [ex.survey, ex.fill, ex.crane]
    assert edits.meetings_in(m, None) and set(edits.meetings_in(m, ex.project)) == {ex.kickoff, ex.weekly}


def test_tidy_moves_them_and_undo_puts_them_back(sample_root, ex):
    from docrepo import edits, tasks

    conn, root, fs = sample_root
    as_before(sample_root, ex)
    before = {t: tasks.parent_links(conn, t) for t in (ex.survey, ex.fill, ex.crane, ex.blades, ex.rig)}
    m = Model(conn)
    out, undo = edits.tidy_follow_ups(conn, root, fs, edits.follow_ups_to_tidy(m, edits.meetings_in(m, ex.project)), datetime(2026, 11, 13, 9, 0))
    assert out.message == "Moved 5 follow-ups out of 2 meetings."
    m = Model(conn)
    assert m.parents_of(ex.fill) == [ex.project] and m.parents_of(ex.rig) == [ex.crane] and m.children_of(ex.kickoff) == []
    assert any(e.field == "Parents" and e.via == "Browse tool" for e in m.status_log_of(ex.fill))
    assert "Fill media order · under Cooling tower 2 rebuild" in page(sample_root, ex.kickoff)["follow_ups"]  # still its Follow-ups
    back = edits.undo_tidy(conn, root, fs, undo, datetime(2026, 11, 13, 9, 1))
    assert back.message == "Set back: 5 follow-ups under their meetings again."
    assert {t: tasks.parent_links(conn, t) for t in before} == before


def test_undo_leaves_a_task_changed_since(sample_root, ex):
    from docrepo import edits, tasks

    conn, root, fs = sample_root
    as_before(sample_root, ex)
    m = Model(conn)
    out, undo = edits.tidy_follow_ups(conn, root, fs, edits.follow_ups_to_tidy(m, [ex.kickoff]), datetime(2026, 11, 13, 9, 0))
    assert out.message == "Moved 3 follow-ups out of Cooling tower kickoff."
    tasks.set_parents(conn, ex.fill, [ex.crane], at=datetime(2026, 11, 13, 9, 1), via="test")
    back = edits.undo_tidy(conn, root, fs, undo, datetime(2026, 11, 13, 9, 2))
    assert back.message == "Set back: 2 follow-ups under their meetings again. Fill media order changed since, so stayed."
    assert Model(conn).parents_of(ex.fill) == [ex.crane]


def test_a_meeting_with_nothing_above_it_keeps_its_follow_ups(sample_root):
    from docrepo import edits

    conn = sample_root[0]
    r = notes(sample_root, None, "- Order the spare impeller @Tyler", name="Vendor call")
    m = Model(conn)
    assert edits.follow_ups_to_tidy(m, [r.meeting]) == []
