"""Move to task (release 5.143, the design workspace's notes consolidation plan, decision 613): lines of a page moved to a
task's page, a pointer line left where they were, with Undo and Bring the lines back, over a made-up project
(``notes_example``)."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import edits, notes_page, search
from docrepo.captures import read_content
from docrepo.model import Model
from notes_example import build

AT = datetime(2026, 11, 13, 9, 15)


@pytest.fixture
def ex(sample_root):
    conn, root, fs = sample_root
    return build(conn, root, fs)


def page(conn, task_id: str) -> list[str]:
    return notes_page.get(conn, task_id).split("\n")


def stray(conn, ex) -> tuple[int, int]:
    """Where the kickoff's two lines about the fill media are on its page."""
    raw = page(conn, ex.kickoff)
    start = next(i for i, x in enumerate(raw) if x.startswith("Shutdown window"))
    return start, start + 2


def move(sample_root, ex):
    conn, root, fs = sample_root
    start, end = stray(conn, ex)
    return edits.move_lines(conn, root, fs, ex.kickoff, start, end, ex.fill, AT, expect=page(conn, ex.kickoff)[start:end])


def test_the_lines_go_to_the_task_and_a_pointer_stays(sample_root, ex):
    conn = sample_root[0]
    out, moved = move(sample_root, ex)
    assert out.message == "Moved 2 lines to Fill media order." and moved.key == "M20261113091500"
    kickoff = notes_page.lines_of(notes_page.get(conn, ex.kickoff))
    pointer = next(x for x in kickoff if x.kind == "pointer")
    assert pointer.text == "Fill media order · 2 lines moved there" and pointer.ref == f"{ex.fill}/M20261113091500"
    assert not any(x.text.startswith(("Shutdown window", "Vendor says")) for x in kickoff)
    fill = notes_page.get(conn, ex.fill)
    lines = notes_page.lines_of(fill)
    lead = next(i for i, x in enumerate(lines) if x.kind == "lead")
    assert lines[lead].text == "Moved from the notes of Cooling tower kickoff · Tue 3 Nov" and lines[lead].ref == f"{ex.kickoff}/M20261113091500"
    assert [x.text for x in lines[lead + 1:lead + 3]] == ["Shutdown window: Tom thinks the March outage is too tight for the fill media.",
                                                         "Vendor says fill lead time is 10 to 12 weeks, so the order has to go by 1 Dec."]
    assert fill.index("# Tue 3 Nov 2026") < fill.index("Moved from")  # under their day's heading
    assert notes_page.moved_block(fill, moved.key) == (lead, lead + 3)


def test_the_meeting_s_capture_md_keeps_its_words(sample_root, ex):
    conn, root, _fs = sample_root
    move(sample_root, ex)
    m = Model(conn)
    assert "Vendor says fill lead time" in read_content(root, m.captures[ex.kickoff_notes])


def test_both_pages_are_the_owner_s_edits_and_search_finds_the_words_once(sample_root, ex):
    conn, root, _fs = sample_root
    move(sample_root, ex)
    m = Model(conn)
    assert {t for t, _day, _at in m.page_edits} >= {ex.kickoff, ex.fill}
    found = search.search(conn, m, "lead time")
    assert ("Notes", ex.fill) in [(x.group, x.id) for x in found] and ("Notes", ex.kickoff) not in [(x.group, x.id) for x in found]
    assert not [x for x in search.search(conn, m, "moved there") if x.group == "Notes"]  # a pointer's words aren't the page's
    assert notes_page.words(notes_page.get(conn, ex.fill)).count("Moved from") == 0
    md = (root / "Tasks" / ex.kickoff / "Task.md").read_text(encoding="utf-8")
    assert f"↪ [Fill media order · 2 lines moved there](../{ex.fill}/Task.md)" in md


def test_captions_and_day_headings_stay(sample_root, ex):
    conn, root, fs = sample_root
    raw = page(conn, ex.kickoff)
    out, _moved = edits.move_lines(conn, root, fs, ex.kickoff, 0, len(raw), ex.fill, AT, expect=raw)
    kickoff = notes_page.lines_of(notes_page.get(conn, ex.kickoff))
    assert [x.kind for x in kickoff[:2]] == ["heading", "caption"] and kickoff[2].kind == "pointer"
    assert out.message == "Moved 7 lines to Fill media order."  # the two lines of words, two of text and three task lines


def test_a_page_that_changed_since_refuses(sample_root, ex):
    conn, root, fs = sample_root
    start, end = stray(conn, ex)
    with pytest.raises(edits.EditError, match="changed since"):
        edits.move_lines(conn, root, fs, ex.kickoff, start, end, ex.fill, AT, expect=["Something else", "entirely"])
    with pytest.raises(edits.EditError, match="on its page already"):
        edits.move_lines(conn, root, fs, ex.kickoff, start, end, ex.kickoff, AT)


def test_undo_sets_both_pages_back(sample_root, ex):
    conn, root, fs = sample_root
    before = {t: notes_page.get(conn, t) for t in (ex.kickoff, ex.fill)}
    _out, moved = move(sample_root, ex)
    assert edits.undo_move_lines(conn, root, fs, moved, AT).message == "Set back: the lines are where they were."
    assert {t: notes_page.get(conn, t) for t in before} == before


def test_undo_refuses_after_another_edit_and_bring_back_works(sample_root, ex):
    conn, root, fs = sample_root
    _out, moved = move(sample_root, ex)
    edits.save_page(conn, root, fs, ex.fill, notes_page.get(conn, ex.fill) + "\nTyler to call vendor B.", AT)
    with pytest.raises(edits.EditError, match="Bring the lines back"):
        edits.undo_move_lines(conn, root, fs, moved, AT)
    out = edits.bring_lines_back(conn, root, fs, ex.kickoff, moved.key, AT)
    assert out.message == "Brought 3 lines back from Fill media order."  # the two, and the line typed under them since
    kickoff = notes_page.get(conn, ex.kickoff)
    assert "Vendor says fill lead time" in kickoff and "Tyler to call vendor B." in kickoff and "moved there" not in kickoff
    assert "Moved from" not in notes_page.get(conn, ex.fill) and "Vendor says" not in notes_page.get(conn, ex.fill)


def test_two_moves_in_one_second_get_their_own_keys(sample_root, ex):
    conn, root, fs = sample_root
    _out, first = move(sample_root, ex)
    raw = page(conn, ex.kickoff)
    i = next(n for n, x in enumerate(raw) if x.startswith("Attendees"))
    _out, second = edits.move_lines(conn, root, fs, ex.kickoff, i, i + 1, ex.fill, AT, expect=raw[i:i + 1])
    assert first.key == "M20261113091500" and second.key == "M20261113091500-2"


# ---- decision 614: a meeting's #task sections point to their tasks' pages ----
def test_a_meeting_s_hash_task_sections_are_pointers(sample_root, ex):
    conn = sample_root[0]
    weekly = notes_page.lines_of(notes_page.get(conn, ex.weekly))
    pointers = [(x.text, x.ref) for x in weekly if x.kind == "pointer"]
    m = Model(conn)
    note = next(c.id for c in m.captures.values() if c.from_notes == ex.weekly_notes and c.item == "note")
    decision = next(c.id for c in m.captures.values() if c.from_notes == ex.weekly_notes and c.item == "decision")
    assert pointers == [("Structural survey of the fan deck · 1 line there", f"{ex.survey}/{note}"),
                        ("Crane for the fan lift · a decision there", f"{ex.crane}/{decision}")]
    assert not any(x.text.startswith(("#Structural", "#Crane", "\\- drawings", "\\- \\*\\*decision")) for x in weekly)
    assert "drawings found" in notes_page.get(conn, ex.survey)  # the words are on the task's page, under their caption
    assert [x.kind for x in weekly if x.kind in ("task", "pointer")] == ["task", "pointer", "pointer", "task"]


# ---- pointers in All notes and the Meetings section ----
def test_all_notes_opens_moved_lines_at_their_pointer(sample_root, ex):
    from docrepo import all_notes
    from docrepo.detail import Pages, PageState

    conn, root, _fs = sample_root
    move(sample_root, ex)
    m = Model(conn)
    an = all_notes.compose(m, ex.project)
    assert not any(b.came_from for b in an.blocks())  # the moved block shows at its pointer, not again under Fill media order
    kickoff = next(b for b in an.blocks() if b.page == ex.kickoff)
    pointer = next(x for x in kickoff.lines if x.kind == "pointer")
    block = all_notes.pointer_block(m, pointer.ref)
    assert block is not None and block.page == ex.fill and [x.text for x in block.lines][:1] == [
        "Shutdown window: Tom thinks the March outage is too tight for the fill media."]
    html = Pages(m, ex_today(), lambda cid: read_content(root, m.captures[cid])).all_notes(ex.project, PageState())[0]
    assert "moved there" in html and html.index("Fan deck is worse") < html.index("Shutdown window") < html.index("Fill media: Tyler")
    alone = all_notes.compose(m, ex.fill)  # its own All notes: the moved block is its own, led by where it came from
    assert [b.label for b in alone.blocks() if b.key] == ["Moved from the notes of Cooling tower kickoff · Tue 3 Nov"]


def test_meetings_count_the_lines_moved_from_them(sample_root, ex):
    from docrepo import meeting_rows

    conn, root, _fs = sample_root
    move(sample_root, ex)
    m = Model(conn)
    reader = lambda cid: read_content(root, m.captures[cid])  # noqa: E731 - a short reader
    fill = {r.meeting: meeting_rows.words(m, r, ex.fill, reader) for r in meeting_rows.rows(m, ex.fill)}
    assert fill[ex.kickoff] == "made this task · 2 lines moved here"
    project = {r.meeting: meeting_rows.words(m, r, ex.project, reader) for r in meeting_rows.rows(m, ex.project)}
    assert project[ex.kickoff].endswith("2 lines moved to Fill media order")


def ex_today():
    from datetime import date

    return date(2026, 11, 13)
