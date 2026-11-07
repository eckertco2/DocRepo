"""The Task view's pages as text (release 5.34, ``docrepo.task_view_pages``; its first test of its own in release 5.102):
the header, the crumbs, the preview of each kind of record, the matched lines while searching, and the list's empty
states and count line. No Qt."""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from docrepo import overview
from docrepo import task_view_pages as tvp
from docrepo.model import Model

TODAY = date(2026, 10, 8)


@pytest.fixture
def records(sample_root):
    conn, root, _fs = sample_root
    m = Model(conn)
    return m, overview.build(m, root, "T000001", overview.capture_texts(conn, [c.id for c in m.live_captures()]))


def test_the_header_has_the_title_state_dates_people_subtasks_and_latest(records):
    m, recs = records
    page = tvp.header(m, m.task("T000001"), recs, TODAY, "P001")
    assert '<h2 title="T000001">Reactor impeller upgrade</h2>' in page
    assert "In progress" in page and 'href="label:Line%201"' in page
    assert "Fri 27 Nov" in page and "in 50 days" in page
    assert 'title="Tom Becker"' in page
    assert "6 of 7 open" in page and 'src="progress:1:7"' in page
    assert "Current status" in page and "Impeller arrived on site" in page
    assert 'href="pick:note:C000025"' in page  # the latest note or update, which picks it in the list


def test_a_task_with_no_status_offers_to_add_one(records):
    m, _recs = records
    page = tvp.header(m, replace(m.task("T000003"), current_status=""), [], TODAY, "P001")
    assert "No status yet." in page and 'href="do:update"' in page and "Latest" not in page
    assert "No due date" in page


def test_the_crumbs_are_the_parents_as_links(records):
    m, _recs = records
    crumbs = tvp.crumbs(m, m.task("T000012"))
    assert crumbs.index('href="task:T000001"') < crumbs.index('href="task:T000008"') and crumbs.endswith("›")
    assert tvp.crumbs(m, m.task("T000001")) == ""  # a top-level task has none


def test_the_preview_of_each_kind(records):
    m, recs = records
    by_id = {r.id: r for r in recs}
    assert "Choose something in the list" in tvp.preview(m, None, TODAY, [])
    file = tvp.preview(m, by_id["D000001"], TODAY, [], text="Rated flow 120 m3/h.\nImpeller diameter 310 mm.", last_opened="2026-10-07 10:00:00")
    assert "Impeller datasheet rev B.pdf" in file and "PDF" in file and "characters of text" in file
    assert "Opened" in file and "from DocRepo" in file and 'href="scope:T000001"' in file
    assert "Not found at its path" in tvp.preview(m, by_id["D000001"], TODAY, [], missing=True)
    email = tvp.preview(m, by_id["C000003"], TODAY, [])
    assert "From Norvane Pumps (vendor)" in email and 'href="pick:file:D000001"' in email
    note = tvp.preview(m, by_id["C000001"], TODAY, [])
    assert "Kickoff with Tom and Priya" in note and "As it reads on the notes page" in note
    task = tvp.preview(m, by_id["T000008"], TODAY, [])
    assert "Installation" in task and "In progress" in task


def test_searching_marks_the_words_and_shows_the_matching_lines(records):
    m, recs = records
    r = next(r for r in recs if r.id == "C000003")
    assert tvp.marked("Pump <3> curve", ["pump"]) == '<span class="mark">Pump</span> &lt;3&gt; curve'
    lines = "\n".join(f"line {i}" for i in range(10)) + "\nthe impeller curve\n" + "\n".join(f"after {i}" for i in range(10))
    part = tvp.text_part(lines, ["curve"], "Its text")
    assert "1 matching line" in part and '<p class="hitline">the impeller <span class="mark">curve</span></p>' in part
    assert '<p class="line">line 9</p>' in part and '<p class="line">after 0</p>' in part and "line 5" not in part  # a line either side
    apart = tvp.text_part(lines + "\nthe pump curve", ["curve"], "Its text")
    assert "2 matching lines" in apart and '<p class="gap">…</p>' in apart  # lines far apart, with a gap between
    long = tvp.text_part("\n".join(f"l{i}" for i in range(tvp.PREVIEW_LINES + 5)), [], "Text")
    assert "… 5 more lines" in long
    assert tvp.text_part("  ", [], "Text", empty="No text was pulled out of this file.") == '<p class="note">No text was pulled out of this file.</p>'
    assert '<span class="mark">' in tvp.preview(m, r, TODAY, ["datasheet"])


def test_the_empty_states_and_the_count_line():
    found = tvp.nothing_found("Installation", "crane <x>", 2, True, "crane")
    assert "Nothing in Installation matches “crane &lt;x&gt;”." in found
    assert 'href="q:crane"' in found and "Clear the 2 filters" in found and 'href="do:whole"' in found and 'href="do:everywhere"' in found
    assert "Clear the" not in tvp.nothing_found("Installation", "x", 0, False, None)
    assert tvp.nothing_of_kind("email", "Installation", False) == '<p align="center"><b>No emails in Installation.</b></p>'
    assert 'href="do:whole"' in tvp.nothing_of_kind("file", "Rigging plan", True)
    assert tvp.count_line("file", 3, "Installation", False, False, False, 0) == "3 files in Installation"
    assert tvp.count_line("all", 3, "Installation", False, True, False, 0, narrowed=False) == "Overview"
    assert tvp.count_line("all", 1, "Installation", True, False, True, 0) == "1 result in Installation · searching file text…"
    assert tvp.count_line("all", 2, "X", True, False, False, 4, narrowed=False) == "2 results · 4 more in file text"
    assert "Searching the files' text" in tvp.still_searching()
    assert "Click a caption" in tvp.nothing_clicked()
