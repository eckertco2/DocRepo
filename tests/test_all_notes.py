"""All notes (release 5.140, the design workspace's notes consolidation plan, decisions 602 to 606 and 609): a task's page
and every page under it read as one, by day, each meeting as it was said, over a made-up project (``notes_example``)."""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from docrepo import all_notes, edits
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


def words(blocks) -> str:
    return "\n".join(x.text for b in blocks for x in b.lines)


def test_a_page_is_cut_into_blocks_by_day_and_caption(sample_root, ex):
    m = Model(sample_root[0])
    blocks = all_notes.blocks_of(m, ex.survey)
    assert [(b.day, b.capture is not None) for b in blocks] == [(date(2026, 11, 3), True), (date(2026, 11, 10), True), (date(2026, 11, 11), False)]
    assert blocks[0].label == "New task from the notes of Cooling tower kickoff" and blocks[0].time == "10:00 am"
    assert blocks[2].at == "00:00" and "rev C" in blocks[2].lines[0].text  # typed on the page: no caption, no time


def test_a_project_reads_its_meetings_as_said(sample_root, ex):
    m = Model(sample_root[0])
    an = all_notes.compose(m, ex.project)
    assert [d for d, _ in an.days] == [date(2026, 11, 3), date(2026, 11, 10), date(2026, 11, 11)]  # the empty New task caption says nothing
    pages = [b.page for b in an.blocks()]
    assert pages == [ex.kickoff, ex.weekly, ex.survey]
    # Each follow-up's block shows in its meeting's place, so not again on its own; nor the weekly's copy on the survey.
    assert ex.fill not in pages and ex.crane not in pages and ex.blades not in pages
    text = words(an.blocks())
    assert "Vendor says fill lead time" in text and "rev C" in text and text.count("drawings found") == 1
    assert an.pages == [ex.kickoff, ex.survey, ex.weekly]  # the tree's order; the project's own page says nothing here


def test_a_task_line_opens_into_the_follow_ups_block(sample_root, ex):
    m = Model(sample_root[0])
    b = all_notes.follow_up_block(m, ex.kickoff_notes, ex.survey)
    assert b is not None and b.page == ex.survey
    assert [x.text.strip(" \\-") for x in b.lines] == ["Structural survey of the fan deck @Priya Shah \\*\\*due, 20 Nov",
                                                       "get the 2019 drawings from the archive", "check the cracked panels at the east cell"]
    assert all_notes.follow_up_block(m, ex.weekly_notes, ex.survey) is None  # the weekly didn't make it


def test_a_copied_section_is_known_by_its_heading(sample_root, ex):
    m = Model(sample_root[0])
    assert all_notes.copied_to(m, ex.weekly_notes) == {"#structural survey of the fan deck": ex.survey, "#crane for the fan lift": ex.crane}


def test_a_follow_up_s_all_notes_shows_where_it_came_from(sample_root, ex):
    """Fill media order's meeting isn't under it, so its block from the kickoff shows as it is, with its caption's words."""
    m = Model(sample_root[0])
    an = all_notes.compose(m, ex.fill)
    assert [(b.page, b.label) for b in an.blocks()] == [(ex.fill, "New task from the notes of Cooling tower kickoff")]
    assert not all_notes.has_more(m, ex.fill)  # nothing under it, no task line on its page: no switch
    assert all_notes.has_more(m, ex.project) and all_notes.has_more(m, ex.kickoff) and all_notes.has_more(m, ex.crane)


def test_one_page_alone(sample_root, ex):
    m = Model(sample_root[0])
    an = all_notes.compose(m, ex.project, only=ex.survey)
    assert an.only == ex.survey and {b.page for b in an.blocks()} == {ex.survey} and ex.kickoff in an.pages
    assert all_notes.compose(m, ex.project, only="T999999").only == ""  # a page that isn't in it narrows nothing


def test_the_window_of_weeks(sample_root, ex):
    conn, root, fs = sample_root
    save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="An old note on the deck, from the spring survey.", task=ex.survey),
                 datetime(2026, 6, 2, 9, 0))
    m = Model(conn)
    an = all_notes.compose(m, ex.project)
    assert an.earlier and an.since == date(2026, 11, 11).replace(month=9, day=16) and date(2026, 6, 2) not in [d for d, _ in an.days]
    assert date(2026, 6, 2) in [d for d, _ in all_notes.compose(m, ex.project, weeks=None).days]
    assert not all_notes.compose(m, ex.project, weeks=40).earlier


def test_a_discarded_task_s_page_is_left_out(sample_root, ex):
    conn, root, fs = sample_root
    edits.discard_task(conn, root, fs, SETTINGS, ex.survey, "made by mistake", datetime(2026, 11, 12, 9, 0))
    m = Model(conn)
    assert ex.survey not in all_notes.compose(m, ex.project).pages


def test_the_page_draws_it(sample_root, ex):
    conn, root, _fs = sample_root
    m = Model(conn)
    pages = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]))
    html, an = pages.all_notes(ex.project, PageState())
    text = " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").split())
    assert "Cooling tower kickoff Meeting notes · 10:00 am Edit there Attendees: Priya, Tom, Mike." in text
    assert "Structural survey of the fan deck follow-up, on its page - Structural survey of the fan deck" in text
    assert "#Structural survey of the fan deck · also on Structural survey of the fan deck 's page" in text
    assert f'name="block:{ex.kickoff}:{ex.kickoff_notes}"' in html and 'name="day:2026-11-03"' in html
    assert f'href="notesgo:{ex.kickoff}:{ex.kickoff_notes}"' in html and f'href="task:{ex.survey}"' in html
    html, _an = pages.all_notes(ex.project, PageState(notes_only=ex.survey))
    assert "Only Structural survey of the fan deck's page." in html and "allnotes:only:" in html
