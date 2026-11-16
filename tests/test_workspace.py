"""The workspace without Qt (release 5.152, the design workspace's ``docs/mods/workspace-view-plan.md``, decisions 663 to
670, 678 to 687 and 698 to 702): the chain, what's gathered, the outline, Dates and their changes, the quick entry's note,
and the resources with their search. Over the notes consolidation's made-up project (``notes_example``), with a wait, key
dates, a link and a second parent added. Every name and line here is made up."""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

import pytest

from docrepo import edits, tasks, waits
from docrepo import workspace as ws
from docrepo.detail import Pages
from docrepo.model import Model
from notes_example import SETTINGS
from workspace_example import AT, Work, make

TODAY = AT.date()
WORKDAYS = range(5)


@pytest.fixture
def work(sample_root) -> Work:
    return make(*sample_root)


def model(sample_root) -> Model:
    return Model(sample_root[0])


def pages(sample_root) -> Pages:
    return Pages(model(sample_root), TODAY, lambda _cid: "", "P001", sample_root[0])


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("&#x27;", "'").split())


# ---- the chain and what's gathered (decisions 664, 665, 680, 686 and 700) ----
def test_the_chain_runs_from_the_project_down(sample_root, work):
    m = model(sample_root)
    c = ws.chain(m, work.crane)
    assert c.paths == ((work.project,),) and c.above == [work.project]
    assert [c.caption(n) for n in range(2)] == ["", ""]


def test_a_task_under_two_parents_has_a_path_each(sample_root, work):
    m = model(sample_root)
    c = ws.chain(m, work.rig)
    assert c.paths == ((work.project, work.crane), (work.outage,))
    assert [c.caption(n) for n in range(3)] == ["", "and under", "under both"]  # nothing about the parents' other subtasks


def test_this_task_gathers_above_and_under_but_not_its_parents_other_work(sample_root, work):
    m = model(sample_root)
    got = ws.gathered(m, work.crane)
    assert got == [work.project, work.crane, work.rig]
    assert work.survey not in got  # 665: a parent's other subtasks are other work


def test_a_parent_picked_widens_to_its_other_subtasks(sample_root, work):
    m = model(sample_root)
    got = ws.gathered(m, work.project)
    assert {work.survey, work.crane, work.rig, work.kickoff} <= set(got)  # 680


def test_the_resources_list_the_picked_tasks_own_first(sample_root, work):
    m = model(sample_root)
    assert ws.resource_order(m, work.rig) == [work.rig, work.outage, work.crane, work.project]


def test_the_words_say_whose(sample_root, work):
    m = model(sample_root)
    assert ws.scope_words(m, work.crane, work.crane) == "Of this task, everything under it (1) and the task above it."
    assert ws.scope_words(m, work.crane, work.project) == "Of Cooling tower 2 rebuild and everything under it (7)."
    assert ws.scope_words(m, work.rig, work.rig) == "Of this task and the 3 tasks above it."
    assert ws.gathered_words(m, work.crane) == "Gathered from 3 pages: this task, 1 under it and 1 above it."


def test_subtasks_list_the_open_first(sample_root, work):
    conn = sample_root[0]
    tasks.update_task(conn, SETTINGS, work.rig, at=AT, via="test", state="Closed")
    m = model(sample_root)
    assert ws.subtasks(m, work.project)[-1] != work.crane
    assert ws.subtasks(m, work.crane) == [work.rig]


# ---- the outline (decisions 669 and 683) ----
def test_the_outline_follows_the_chain_then_whats_under_then_dates(sample_root, work):
    m = model(sample_root)
    out = ws.outline(m, work.crane)
    names = [e.text for e in out if e.level == 1]
    assert names == ["Cooling tower 2 rebuild", "Crane for the fan lift", "Rig the east cell first", "Dates"]
    crane = [e for e in out if e.page == work.crane]
    assert [(e.level, e.day, e.text) for e in crane[:3]] == [(1, False, "Crane for the fan lift"), (2, True, "Tue 3 Nov 2026"),
                                                             (2, True, "Tue 10 Nov 2026")]
    booking = next(e for e in crane if e.text == "Booking")
    assert (booking.level, booking.day, booking.heading) == (3, False, 2)  # a level under its day; its place, to find it again


def test_the_outline_names_a_subtask_being_edited_even_with_no_notes(sample_root, work):
    m = model(sample_root)
    blank = tasks.create_task(sample_root[0], SETTINGS, title="Hire the riggers", at=AT, created_by="P001", parents=[work.crane])
    m = model(sample_root)
    assert blank not in ws.outline_pages(m, work.crane)
    assert blank in ws.outline_pages(m, work.crane, also=blank)


def test_headings_read_markup_as_words():
    assert ws.headings("# Thu 12 Nov 2026\n## **Quotes** and more\ntext\n### Deep") == [
        (1, True, "Thu 12 Nov 2026"), (2, False, "Quotes and more"), (3, False, "Deep")]


# ---- Dates (decisions 681, 698 and 699) ----
def test_dates_list_every_kind_soonest_first(sample_root, work):
    m = model(sample_root)
    rows = ws.dates(m, work.crane, TODAY)
    got = [(r.day.isoformat(), r.kind, r.words, r.field) for r in rows]
    assert got == [
        ("2026-11-03", "Meeting", "Cooling tower kickoff", "start"),  # the project's own meetings, with their day
        ("2026-11-10", "Meeting", "Cooling tower weekly 10 Nov", "start"),
        ("2026-11-17", "Follow-up", "Follow up with Mike", "follow_up"),
        ("2026-11-24", "Key date", "Crane on site", "key_date"),
        ("2026-11-27", "Due", "Crane for the fan lift", "due"),  # its own 30 Nov reminder waits behind the follow-up
        ("2027-03-08", "Plant event", "Spring outage", "key_date"),
        ("2027-03-26", "Due", "Cooling tower 2 rebuild", "due"),
    ]
    assert rows[3].end == date(2026, 11, 26)
    earlier, coming = ws.split_dates(rows, TODAY)
    assert len(earlier) == 2 and coming[0].kind == "Follow-up"


def test_a_closed_tasks_dates_are_done_with(sample_root, work):
    tasks.update_task(sample_root[0], SETTINGS, work.crane, at=AT, via="test", state="Closed")
    m = model(sample_root)
    assert all(r.task != work.crane for r in ws.dates(m, work.crane, TODAY))


@pytest.mark.parametrize(("words", "day"), [("tomorrow", date(2026, 11, 13)), ("fri", date(2026, 11, 13)), ("24 nov", date(2026, 11, 24)),
                                            ("+3", date(2026, 11, 17)), ("3", date(2026, 11, 17)), ("2026-12-01", date(2026, 12, 1)),
                                            ("", None), ("someday", None)])
def test_a_day_is_typed_in_quick_edits_words(words, day):
    assert ws.read_day(words, TODAY, WORKDAYS) == day


def test_the_box_shows_the_day_in_words():
    assert ws.day_text(date(2026, 11, 23), TODAY) == "mon 23 nov"


def test_a_due_changes_and_is_logged(sample_root, work):
    conn, root, fs = sample_root
    row = next(r for r in ws.dates(model(sample_root), work.crane, TODAY) if r.kind == "Due" and r.task == work.crane)
    ws.change_day(conn, root, fs, SETTINGS, row, date(2026, 11, 20), AT)
    m = model(sample_root)
    assert m.task(work.crane).due == "2026-11-20"
    assert any(e.field == "Due" and e.to_value == "2026-11-20" for e in m.status_log_of(work.crane))
    ws.change_day(conn, root, fs, SETTINGS, replace(row, day=date(2026, 11, 20)), row.day, AT)  # Undo: the same call back
    assert model(sample_root).task(work.crane).due == "2026-11-27"


def test_a_key_date_with_a_start_and_an_end_moves_both(sample_root, work):
    conn, root, fs = sample_root
    row = next(r for r in ws.dates(model(sample_root), work.crane, TODAY) if r.kind == "Key date")
    ws.change_day(conn, root, fs, SETTINGS, row, date(2026, 11, 25), AT)
    kd = model(sample_root).key_dates_of(work.crane)[0]
    assert (kd.start, kd.end) == ("2026-11-25", "2026-11-27")


def test_a_follow_up_moves_with_the_reminder_it_set(sample_root, work):
    conn, root, fs = sample_root
    m = model(sample_root)
    assert m.task(work.crane).reminder == "2026-11-17"  # the wait's follow-up, the task's own 30 Nov kept
    row = next(r for r in ws.dates(m, work.crane, TODAY) if r.kind == "Follow-up")
    ws.change_day(conn, root, fs, SETTINGS, row, date(2026, 11, 19), AT)
    m = model(sample_root)
    assert waits.current(m, work.crane).follow_up == "2026-11-19"
    assert m.task(work.crane).reminder == "2026-11-19"
    assert any(e.field == ws.FOLLOW_UP_FIELD and e.to_value == "2026-11-19" for e in m.status_log_of(work.crane))
    # After the task's own reminder, that one comes first and the follow-up waits behind it.
    row = next(r for r in ws.dates(m, work.crane, TODAY) if r.kind == "Follow-up")
    ws.change_day(conn, root, fs, SETTINGS, row, date(2026, 12, 4), AT)
    m = model(sample_root)
    assert m.task(work.crane).reminder == "2026-11-30" and waits.current(m, work.crane).reminder_before is None


def test_a_repeating_meetings_next_one_isnt_changed_here(sample_root, work):
    conn, root, fs = sample_root
    tasks.update_task(conn, SETTINGS, work.weekly, at=AT, via="test", recurrence="Weekly", due="2026-11-17")
    row = next(r for r in ws.dates(model(sample_root), work.crane, TODAY) if r.task == work.weekly)
    assert row.field == ""
    with pytest.raises(edits.EditError, match="series"):
        ws.change_day(conn, root, fs, SETTINGS, row, date(2026, 11, 18), AT)


def test_a_key_date_is_done_taken_off_and_put_back(sample_root, work):
    conn, root, fs = sample_root
    row = next(r for r in ws.dates(model(sample_root), work.crane, TODAY) if r.kind == "Key date")
    ws.key_date_done(conn, root, fs, row, True, AT)
    assert all(r.kind != "Key date" for r in ws.dates(model(sample_root), work.crane, TODAY))
    ws.key_date_done(conn, root, fs, row, False, AT)
    _out, held = ws.take_off(conn, root, fs, SETTINGS, row, AT)
    assert model(sample_root).key_dates_of(work.crane) == []
    ws.put_back(conn, root, fs, SETTINGS, work.crane, held, AT)
    kd = model(sample_root).key_dates_of(work.crane)
    assert [(k.start, k.end, k.description) for k in kd] == [("2026-11-24", "2026-11-26", "Crane on site")]


def test_add_a_key_date_reads_its_day_and_words(sample_root, work):
    conn, root, fs = sample_root
    assert ws.read_key_date("24 nov Base plate drawing", TODAY, WORKDAYS) == (date(2026, 11, 24), "Base plate drawing")
    assert ws.read_key_date("+3 Datasheet", TODAY, WORKDAYS) == (date(2026, 11, 17), "Datasheet")
    assert ws.read_key_date("Datasheet by fri", TODAY, WORKDAYS) == (date(2026, 11, 13), "Datasheet by")
    assert ws.read_key_date("no day here", TODAY, WORKDAYS) is None
    ws.add_key_date(conn, root, fs, SETTINGS, work.rig, date(2026, 11, 24), "Base plate drawing", AT)
    assert [k.description for k in model(sample_root).key_dates_of(work.rig)] == ["Base plate drawing"]


# ---- the quick entry's note (decision 701) ----
def test_a_note_goes_under_todays_day_starting_it_when_theres_none():
    page = "# Tue 10 Nov 2026\nold"
    after = ws.note_page(page, "Mike has the quote", TODAY)
    assert after == "# Tue 10 Nov 2026\nold\n# Thu 12 Nov 2026\nMike has the quote"
    assert ws.note_page(after, "and the lift plan", TODAY).endswith("Mike has the quote\nand the lift plan")
    assert ws.without_note(after, "Mike has the quote", TODAY) == page  # Undo takes the day it started too


def test_today_and_done_for_today(sample_root, work):
    conn, root, fs = sample_root
    assert ws.today_item(model(sample_root), work.crane) is None
    edits.add_to_today(conn, root, fs, work.crane, "", AT)
    item = ws.today_item(model(sample_root), work.crane)
    assert item is not None and not ws.done_today(model(sample_root), work.crane, TODAY)
    edits.close_today_item(conn, root, fs, item.id, "Done", AT)
    assert ws.today_item(model(sample_root), work.crane) is None and ws.done_today(model(sample_root), work.crane, TODAY)


# ---- the resources (decisions 664, 679, 680 and 685) ----
def test_the_resources_gather_and_say_whose(sample_root, work):
    found = ws.resources(pages(sample_root), work.rig)
    assert [(r.name, r.whose) for r in found["links"]] == [("booking", "Crane for the fan lift")]
    assert {r.name for r in found["meetings"]} >= {"Cooling tower weekly 10 Nov"}
    assert [r.whose for r in found["decisions"]] == ["Crane for the fan lift"]
    assert found["decisions"][0].href.startswith("capture:")


def test_a_meeting_row_reads_its_notes_in_the_workspace(sample_root, work):
    rows = ws.resources(pages(sample_root), work.crane)["meetings"]
    assert [(r.name, r.href) for r in rows] == [("Cooling tower weekly 10 Nov", f"wsmeet:{work.weekly}"),
                                                ("Cooling tower kickoff", f"wsmeet:{work.kickoff}")]
    assert rows[0].second.startswith("made Rig the east cell first")


def test_the_search_narrows_marks_and_counts(sample_root, work):
    m = model(sample_root)
    found = ws.resources(pages(sample_root), work.crane)
    html = ws.resources_html(m, found, work.crane, "kickoff", set())
    text = plain(html)
    assert "Meetings 1 of 2" in text and "Links" not in text and "Decisions" not in text
    assert '<span class="mark">kickoff</span>' in html
    assert ws.matches(found["links"][0], ["crane", "booking"]) and not ws.matches(found["links"][0], ["kickoff"])
    assert "Nothing here has" in plain(ws.resources_html(m, found, work.crane, "zebra", set()))


def test_a_rows_whose_counts_in_the_search(sample_root, work):
    found = ws.resources(pages(sample_root), work.rig)
    assert [r.name for r in ws.filtered(found, "fan lift")["links"]] == ["booking"]  # on Crane for the fan lift


def test_a_folded_section_shows_only_its_head(sample_root, work):
    m = model(sample_root)
    found = ws.resources(pages(sample_root), work.crane)
    html = ws.resources_html(m, found, work.crane, "", {"meetings"})
    assert "Cooling tower kickoff" not in html and 'href="wsfold:meetings"' in html


def test_whose_chip_says_above_or_under(sample_root, work):
    m = model(sample_root)
    assert "↑ on Cooling tower 2 rebuild" in plain(ws.whose_chip(m, work.project, work.crane, []))
    assert "↳ on Rig the east cell first" in plain(ws.whose_chip(m, work.rig, work.crane, []))
    assert ws.whose_chip(m, work.crane, work.crane, []) == ""


def test_marked_escapes_and_marks():
    assert ws.marked("A <b> quote", ["quote"]) == 'A &lt;b&gt; <span class="mark">quote</span>'


# ---- a parent's notes read in place (decision 668) ----
def test_a_parents_notes_read_with_edit_there(sample_root, work):
    html, places = ws.read_html(pages(sample_root), work.project)
    assert f'href="notesgo:{work.project}:' in html and "Edit there" in plain(html)
    assert places[0].day and places[0].anchor.startswith("day:2026-11-")
    banner = ws.banner_html("Fan deck, its parent")
    assert 'href="wsback:"' in banner and "Back to this task's notes" in plain(banner)
