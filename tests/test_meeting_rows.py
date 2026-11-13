"""The task page's Meetings section (release 5.140, the design workspace's notes consolidation plan, decision 607): every
meeting under a task or whose notes made, named or decided something on it or a task under it, over a made-up project
(``notes_example``)."""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from docrepo import meeting_rows
from docrepo.captures import read_content
from docrepo.detail import Pages, PageState
from docrepo.model import Model
from docrepo.save import CaptureDraft, save_capture
from notes_example import SETTINGS, build

TODAY = date(2026, 11, 12)


@pytest.fixture
def ex(sample_root):
    conn, root, fs = sample_root
    return build(conn, root, fs)


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").split())


def said(root, m: Model, task_id: str) -> list[tuple[str, str, bool, str]]:
    content = lambda cid: read_content(root, m.captures[cid])  # noqa: E731 - a short reader
    return [(r.meeting, r.day, r.under, meeting_rows.words(m, r, task_id, content)) for r in meeting_rows.rows(m, task_id)]


def test_a_project_lists_its_meetings_newest_first(sample_root, ex):
    m = Model(sample_root[0])
    assert said(sample_root[1], m, ex.project) == [
        (ex.weekly, "2026-11-10", True, "made Fan blade inspection, Rig the east cell first · a decision · a note on Structural survey of the fan deck"),
        (ex.kickoff, "2026-11-03", True, "made Structural survey of the fan deck, Fill media order, Crane for the fan lift"),
    ]


def test_a_follow_up_lists_the_meetings_that_made_and_named_it(sample_root, ex):
    m = Model(sample_root[0])
    assert said(sample_root[1], m, ex.fill) == [(ex.kickoff, "2026-11-03", False, "made this task")]
    assert said(sample_root[1], m, ex.survey) == [(ex.weekly, "2026-11-10", False, "a note here"), (ex.kickoff, "2026-11-03", False, "made this task")]
    assert said(sample_root[1], m, ex.crane) == [(ex.weekly, "2026-11-10", False, "made Rig the east cell first · a decision"),
                                                 (ex.kickoff, "2026-11-03", False, "made this task")]


def test_a_meeting_never_lists_itself(sample_root, ex):
    """Since release 5.142 (decision 610) a meeting's follow-ups are under its home task, not under it, so the kickoff
    holds no task the weekly named, and neither meeting lists anything; never itself."""
    m = Model(sample_root[0])
    assert meeting_rows.rows(m, ex.kickoff) == [] and meeting_rows.rows(m, ex.weekly) == []


def test_a_meeting_that_did_nothing_here_says_its_first_words(sample_root, ex):
    conn, root, fs = sample_root
    save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Walkdown of the basin; nothing new.", task=ex.project, meeting=True,
                                                        meeting_name="Basin walkdown"), datetime(2026, 11, 11, 15, 0))
    m = Model(conn)
    first = said(root, m, ex.project)[0]
    assert first[2] and first[3] == "Walkdown of the basin; nothing new."


def test_the_unfolded_notes_mark_the_lines_about_the_task(sample_root, ex):
    conn, root, _fs = sample_root
    m = Model(conn)
    row = next(r for r in meeting_rows.rows(m, ex.survey) if r.meeting == ex.weekly)
    lines = meeting_rows.marked_lines(m, row, ex.survey, lambda cid: read_content(root, m.captures[cid]))
    assert [x.text for x, hit in lines if hit] == ["Structural survey of the fan deck · 1 line there"]  # 614's pointer line (5.143)
    row = next(r for r in meeting_rows.rows(m, ex.fill) if r.meeting == ex.kickoff)
    lines = meeting_rows.marked_lines(m, row, ex.fill, lambda cid: read_content(root, m.captures[cid]))
    assert [x.ref for x, hit in lines if hit] == [ex.fill]  # its task line


def test_the_section_on_the_page(sample_root, ex):
    conn, root, _fs = sample_root
    m = Model(conn)
    pages = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]))
    parts = pages.task_parts(ex.project, PageState())
    assert plain(parts["meetings_summary"]) == "2 · last 10 Nov Meeting notes" and parts["meetings_short"] == "2 · last 10 Nov"
    assert f'href="meetingnotes:{ex.project}"' in parts["meetings_summary"]
    body = plain(parts["meetings"])
    assert body.startswith("Cooling tower weekly 10 Nov made Fan blade inspection") and "Attendees" not in body
    opened = pages.task_parts(ex.project, PageState(meeting_open=ex.kickoff))["meetings"]
    assert "Attendees: Priya, Tom, Mike." in plain(opened) and f'href="task:{ex.kickoff}"' in opened and "Open its notes" in opened
    assert "meetings" not in pages.task_parts(ex.weekly, PageState())  # no meetings: no section


def test_show_all_after_five(sample_root, ex):
    conn, root, fs = sample_root
    for n in range(5):
        save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=f"Check-in {n + 1}.", task=ex.project, meeting=True,
                                                            meeting_name=f"Check-in {n + 1}"), datetime(2026, 11, 4 + n, 15, 0))
    m = Model(conn)
    pages = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]))
    body = pages.task_parts(ex.project, PageState())["meetings"]
    assert "Show all 7 meetings" in body and body.count('src="lk:meeting"') == 5
    assert pages.task_parts(ex.project, PageState(meetings=True))["meetings"].count('src="lk:meeting"') == 7


def test_task_md_lists_the_meetings(sample_root, ex):
    """Decision 608: each Task.md has its meetings as a table, written as the notes are saved; a meeting's notes rewrite
    the pages of every task its items touched, and those above them."""
    conn, root, _fs = sample_root
    from docrepo.pages import pages_touched

    md = (root / "Tasks" / ex.project / "Task.md").read_text(encoding="utf-8")
    assert "## Meetings\n\n| Date | Meeting | What it did here |\n|---|---|---|\n" in md
    assert f"| 2026-11-10 | [Cooling tower weekly 10 Nov](../{ex.weekly}/Task.md) | made Fan blade inspection" in md
    assert md.index("## Meetings") < md.index("## Decisions")
    survey = (root / "Tasks" / ex.survey / "Task.md").read_text(encoding="utf-8")
    assert f"| 2026-11-10 | [Cooling tower weekly 10 Nov](../{ex.weekly}/Task.md) | a note here |" in survey
    assert "## Meetings" not in (root / "Tasks" / ex.weekly / "Task.md").read_text(encoding="utf-8")
    assert {ex.survey, ex.crane, ex.blades, ex.project} <= pages_touched(Model(conn), [ex.weekly])
