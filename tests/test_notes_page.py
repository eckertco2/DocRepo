"""The notes page (release 5.25): its lines, where captures' blocks go, and how saving, filing, discarding, the owner's
edits, Task.md and search use it."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from docrepo import db, edits, notes_page, search
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.notes_page import add_block, caption_line, file_line, heading_line, lines_of, read_line, remove_block, text_line, write
from docrepo.save import CaptureDraft, EmailItem, FileRow, email_rows, first_line, save_capture

AT = datetime(2026, 10, 16, 9, 30)
SETTINGS = Settings(me="P001")


def save(root, draft: CaptureDraft, at: datetime = AT):
    conn, data_root, fs = root
    return save_capture(conn, data_root, fs, SETTINGS, draft, at)


def page(root, task_id: str) -> str:
    return notes_page.get(root[0], task_id)


# ---- lines ----
def test_lines_read_and_write_as_they_were():
    page_text = "\n".join([
        heading_line("Thu 8 Oct 2026", 1), heading_line("Design", 2), caption_line("Thu 8 Oct 2026 · 10:42 am · Note", "C000101"),
        "Vibration is **up** again.", "  - Check the [old] wear rings", file_line("File: Pump spec.docx, the vendor's datasheet", "D000012"),
        text_line("# not a heading"), text_line("[not](capture:C000001)"), "",
    ])
    lines = lines_of(page_text)
    assert [(x.kind, x.level, x.ref) for x in lines] == [
        ("heading", 1, ""), ("heading", 2, ""), ("caption", 0, "C000101"), ("text", 0, ""), ("text", 0, ""), ("file", 0, "D000012"),
        ("text", 0, ""), ("text", 0, ""), ("text", 0, "")]
    assert lines[6].text == "# not a heading" and lines[7].text == "[not](capture:C000001)"
    assert write(lines) == page_text


def test_a_link_s_text_keeps_its_brackets():
    line = caption_line("Email from A: Re: [ext] quote \\ v2", "C000003")
    assert read_line(line).text == "Email from A: Re: [ext] quote \\ v2" and read_line(line).ref == "C000003"


def test_a_heading_of_any_text_and_a_day_heading():
    assert notes_page.day_of("Thu 8 Oct 2026") == date(2026, 10, 8)
    assert notes_page.day_of("Design") is None and notes_page.day_of("Thu 31 Feb 2026") is None


# ---- where a block goes ----
BLOCK = [caption_line("Fri 16 Oct 2026 · 9:30 am · Note", "C000900"), "New text."]


def test_without_day_headings_a_block_goes_at_the_end():
    assert add_block("# Design\nOld text.\n\n", BLOCK, date(2026, 10, 16), False) == "# Design\nOld text.\n" + "\n".join(BLOCK)
    assert add_block("", BLOCK, date(2026, 10, 16), False) == "\n".join(BLOCK)


def test_with_day_headings_a_block_finds_its_day():
    before = "# Thu 8 Oct 2026\nA\n# Thu 22 Oct 2026\nB"
    # its own day: a new heading in date order (decision 113)
    assert add_block(before, BLOCK, date(2026, 10, 16), True) == "# Thu 8 Oct 2026\nA\n# Fri 16 Oct 2026\n" + "\n".join(BLOCK) + "\n# Thu 22 Oct 2026\nB"
    # a day that's there: at the end of its section, under any headings of the owner's own
    assert add_block("# Fri 16 Oct 2026\nA\n## Mine\nC\n\n# Thu 22 Oct 2026\nB", BLOCK, date(2026, 10, 16), True) == (
        "# Fri 16 Oct 2026\nA\n## Mine\nC\n" + "\n".join(BLOCK) + "\n\n# Thu 22 Oct 2026\nB")
    # the latest day: at the end
    assert add_block(before, BLOCK, date(2026, 10, 30), True).endswith("B\n# Fri 30 Oct 2026\n" + "\n".join(BLOCK))
    # the earliest: at the top
    assert add_block(before, BLOCK, date(2026, 10, 1), True).startswith("# Thu 1 Oct 2026\n" + "\n".join(BLOCK) + "\n# Thu 8 Oct 2026")


def test_a_block_comes_off_only_as_it_was_added():
    p = "# Fri 16 Oct 2026\n" + "\n".join(BLOCK) + "\n# Thu 22 Oct 2026\nB"
    assert remove_block(p, "C000900", BLOCK) == ("# Thu 22 Oct 2026\nB", "removed")  # its day heading, left empty, goes too
    edited = p.replace("New text.", "New text, reworded.")
    assert remove_block(edited, "C000900", BLOCK) == (edited, "edited")
    assert remove_block(edited, "C000900", BLOCK, force=True)[1] == "removed"
    assert remove_block(p, "C000999", BLOCK) == (p, "absent")


# ---- saving captures ----
@pytest.fixture
def root(sample_root):
    """The sample, its pages emptied, so each test sees only what it adds."""
    sample_root[0].execute("DELETE FROM task_pages")
    return sample_root


#: A link makes a note a capture still (release 5.69, the notes workspace plan's decision 345), for the tests of captures' blocks.
LINK = "https://example.com/spec"


def linked(**kw) -> CaptureDraft:
    return CaptureDraft(files=[FileRow("Spec sheet", LINK, "the spec")], **kw)


def test_a_note_goes_on_its_task_s_page_under_its_day(root):
    """Release 5.69 (decisions 341 and 345): text alone on a task is no capture. It goes on the page under the day's
    heading, made the first time that day; the next day's goes under a heading of its own."""
    conn = root[0]
    r = save(root, CaptureDraft(content="Wear rings checked: 0.9 mm.\n- Replace both", task="T000012", formatted=True))
    assert r.capture_id is None and r.noted_under == ["Fri 16 Oct 2026"]
    lines = lines_of(page(root, "T000012"))
    assert [(x.kind, x.text) for x in lines] == [("heading", "Fri 16 Oct 2026"), ("text", "Wear rings checked: 0.9 mm."), ("text", "- Replace both")]
    save(root, CaptureDraft(content="Later that day.", task="T000012"), datetime(2026, 10, 16, 15, 0))
    save(root, CaptureDraft(content="Second note.", task="T000012"), datetime(2026, 10, 17, 14, 5))
    assert page(root, "T000012").endswith("- Replace both\nLater that day.\n# Sat 17 Oct 2026\nSecond note.")
    assert notes_page.versions(conn, "T000012") == [("2026-10-17", True), ("2026-10-16", True)]  # the owner's own edits, in Activity
    assert [(x.group, x.id) for x in search.search(conn, Model(conn), "Second note")] == [("Notes", "T000012")]


def test_a_note_s_headings_go_at_the_end_unless_the_last_heading_has_their_words(root):
    """Decision 345 with release 5.94's rule (the review of 2026-11-06, F13): new text goes at the page's end. A note's
    heading goes under the page's heading with the same words (case and spacing aside) only when that's the page's last
    heading; a match higher up doesn't move it, and a heading the page hasn't got is made at the end too."""
    conn, data_root, fs = root
    edits.save_page(conn, data_root, fs, "T000012", "# Seals\n- Old seal noted\n## Rigging\n- Crane booked\n# Other\n- x", AT)
    r = save(root, CaptureDraft(content="Loose line\n# SEALS\n- New seal fitted\n## Lifting plan\n- Two cranes", task="T000012", formatted=True))
    assert r.noted_under == ["Fri 16 Oct 2026", "SEALS", "Lifting plan"]
    assert r.message == "Added to the notes of Rigging plan, under Fri 16 Oct 2026, SEALS and Lifting plan."
    assert page(root, "T000012").split("\n") == [
        "# Seals", "- Old seal noted", "## Rigging", "- Crane booked", "# Other", "- x",
        "# Fri 16 Oct 2026", "Loose line", "# SEALS", "- New seal fitted", "## Lifting plan", "- Two cranes"]
    r = save(root, CaptureDraft(content="## lifting plan\n- Slings tested", task="T000012", formatted=True))  # the last heading: under it
    assert r.noted_under == ["Lifting plan"] and page(root, "T000012").endswith("## Lifting plan\n- Two cranes\n- Slings tested")


def test_an_update_s_caption_says_what_changed_and_its_text_follows(root):
    save(root, CaptureDraft(content="Vendor drawings came in late.", task="T000009", types={"update"},
                            update={"due": "2026-10-30", "current_status": "Vendor drawings came in late."}))
    lines = lines_of(page(root, "T000009"))
    assert lines[0].text == "Fri 16 Oct 2026" and lines[0].kind == "heading"  # every capture under its day (release 5.69)
    assert lines[1].text == "Fri 16 Oct 2026 · 9:30 am · Update: Due date moved to Fri 30 Oct."
    assert lines[2].text == "Vendor drawings came in late."  # decision 114


def test_a_new_task_s_text_goes_on_its_page_and_its_first_line_is_its_description(root):
    r = save(root, CaptureDraft(content="Coupling guard is cracked.\nOrder a new one from the vendor.", task="T000008", types={"new_task"}))
    t = Model(root[0]).task(r.created_task)
    assert t.description == "Coupling guard is cracked."  # decision 115
    lines = lines_of(page(root, r.created_task))
    assert [x.text for x in lines] == ["Fri 16 Oct 2026", "Fri 16 Oct 2026 · 9:30 am · New task", "Coupling guard is cracked.",
                                       "Order a new one from the vendor."]
    assert page(root, "T000008") == ""  # a new subtask's capture is the subtask's, not its parent's


def test_a_one_line_new_task_doesn_t_repeat_its_title(root):
    r = save(root, CaptureDraft(content="Call the vendor about seals", types={"new_task"}, quick=True))
    assert [x.kind for x in lines_of(page(root, r.created_task))] == ["heading", "caption"]
    assert first_line("  - First item\nSecond") == "First item"


def test_an_email_s_caption_names_it_and_its_text_stays_with_it(root):
    email = EmailItem(subject="Revised coupling guard delivery", sender="Norvane Pumps (vendor)", sent="2026-10-15 16:02", to="Me",
                      body="The guard ships Monday.", save_msg=lambda path: Path(path).write_bytes(b"MSG"))
    save(root, CaptureDraft(content="Check the date against the outage.", task="T000012", files=email_rows(email)))
    lines = lines_of(page(root, "T000012"))
    assert lines[1].text.startswith("Fri 16 Oct 2026 · 9:30 am · Email from Norvane Pumps (vendor): ")
    assert [x.text for x in lines[2:] if x.kind == "text"] == ["Check the date against the outage."]
    assert "The guard ships Monday." not in page(root, "T000012")


def test_a_file_is_a_line_with_its_description(root, tmp_path):
    f = tmp_path / "Pump spec.docx"
    f.write_bytes(b"x")
    save(root, CaptureDraft(task="T000012", files=[FileRow("Pump spec.docx", str(f), "the vendor's datasheet")]))
    lines = lines_of(page(root, "T000012"))
    # A file with no words of its own has no caption (release 5.83, R4): its day heading and file line say it all.
    assert [(x.kind, x.text) for x in lines] == [("heading", "Fri 16 Oct 2026"), ("file", "File: Pump spec.docx, the vendor's datasheet")]


def test_meeting_notes_go_on_the_meeting_and_an_item_on_its_task(root):
    r = save(root, CaptureDraft(content="Crane is booked.\n#Rigging plan **decision, Lift on the 20th.", task="T000010", meeting=True))
    meeting = r.meeting
    lines = lines_of(page(root, meeting))
    assert lines[0].kind == "heading" and lines[0].text == "Fri 16 Oct 2026"  # every page's day headings are on (release 5.69)
    assert lines[1].text == "Fri 16 Oct 2026 · 9:30 am · Meeting notes"
    item_page = page(root, "T000012")
    assert "Decision from the notes of" in item_page and "Lift on the 20th." in item_page


def test_every_page_has_day_headings(root):
    """Release 5.69 retires decision 119's per-task choice: every task's captures go under their day's heading, a late
    one under its own day in date order (decision 113), whatever the task's old setting."""
    conn, data_root, fs = root
    conn.execute("UPDATE tasks SET day_headings = 0 WHERE id = 'T000012'")  # set off before 5.69: no longer read
    assert Model(conn).uses_day_headings("T000012") and Model(conn).uses_day_headings("T000011")
    save(root, linked(content="Under its day.", task="T000012"))
    save(root, linked(content="Two days before.", task="T000012"), datetime(2026, 10, 14, 8, 0))
    p = page(root, "T000012")
    assert p.startswith("# Wed 14 Oct 2026\n") and p.index("# Wed 14 Oct 2026") < p.index("# Fri 16 Oct 2026")


# ---- the first pages, filing, discarding ----
def test_the_first_pages_are_built_from_the_raw_text_logs(root):
    conn, data_root, fs = root
    assert not notes_page.needs_build(conn)  # the sample's were built with it
    conn.execute("DELETE FROM app_state WHERE key = ?", (notes_page.BUILT,))
    assert notes_page.needs_build(conn)
    model, stories = edits.stories_for(conn, data_root, AT)
    made = notes_page.build_all(conn, model, stories, AT)
    assert made == len([t for t in model.tasks.values() if not t.discarded]) and not notes_page.needs_build(conn)
    p = page(root, "T000001")
    assert notes_page.capture_ids(p) == [c.id for c in sorted(model.notes_of("T000001"), key=lambda c: c.saved)]
    assert "Email from Norvane Pumps (vendor): Impeller datasheet rev B" in p and "Please" not in p  # the email's text stays with it
    assert "Kickoff with Tom and Priya." in p
    assert notes_page.build_all(conn, Model(conn), stories, AT) == 0  # once only


def test_filing_puts_a_capture_on_the_page_and_discarding_takes_it_off(root):
    conn, data_root, fs = root
    edits.file_capture(conn, data_root, fs, "C000022", "T000012", AT)
    assert "C000022" in notes_page.capture_ids(page(root, "T000012"))  # decision 106
    edits.discard_capture(conn, data_root, fs, "C000022", "", AT)
    assert "C000022" not in notes_page.capture_ids(page(root, "T000012"))
    edits.bring_back_capture(conn, data_root, fs, "C000022", AT)
    assert "C000022" in notes_page.capture_ids(page(root, "T000012"))


def test_a_block_edited_on_the_page_stays_unless_asked(root):
    conn, data_root, fs = root
    r = save(root, linked(content="Typed twice.", task="T000012"))
    edits.save_page(conn, data_root, fs, "T000012", page(root, "T000012").replace("Typed twice.", "Typed twice, then reworded."), AT)
    model, stories = edits.stories_for(conn, data_root, AT)
    assert notes_page.edited_blocks(model, stories, r.capture_id) == ["T000012"]
    out = edits.discard_capture(conn, data_root, fs, r.capture_id, "", AT)
    assert r.capture_id in notes_page.capture_ids(page(root, "T000012")) and "as you'd edited it there" in out.message
    edits.bring_back_capture(conn, data_root, fs, r.capture_id, AT)
    edits.discard_capture(conn, data_root, fs, r.capture_id, "", AT, off_edited_pages=True)
    assert r.capture_id not in notes_page.capture_ids(page(root, "T000012"))


def test_add_it_again(root):
    conn, data_root, fs = root
    r = save(root, linked(content="Gone and back.", task="T000012"))
    edits.save_page(conn, data_root, fs, "T000012", "", AT)
    assert edits.add_again(conn, data_root, fs, r.capture_id, "T000012", AT).message == f"{r.capture_id} is on the page again."
    assert "Gone and back." in page(root, "T000012")


# ---- the owner's edits, versions, Task.md and search ----
def test_the_owner_s_edit_keeps_the_day_s_version_and_updates_task_md_and_search(root):
    conn, data_root, fs = root
    edits.save_page(conn, data_root, fs, "T000012", "# Lift\nSling **drawing** checked.", datetime(2026, 10, 16, 9, 0))
    edits.save_page(conn, data_root, fs, "T000012", "# Lift\nSling **drawing** checked twice.", datetime(2026, 10, 16, 17, 0))
    assert notes_page.versions(conn, "T000012") == [("2026-10-16", True)]  # the page as it stood at the day's end
    assert notes_page.version(conn, "T000012", "2026-10-16").endswith("checked twice.")
    assert Model(conn).page_edits == [("T000012", "2026-10-16", "2026-10-16 17:00:00")]
    from docrepo.activity import Activity

    lines = [x for x in Activity(Model(conn), date(2026, 10, 16)).lines(date(2026, 10, 12), date(2026, 10, 16)) if x.key.startswith("p:")]
    assert [(x.at, x.task, x.chip, x.text, x.open) for x in lines] == [("2026-10-16 17:00", "T000012", "Notes", "Notes edited", ("task", "T000012"))]
    md = (data_root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")
    assert "## Notes\n\n### Lift\n\nSling **drawing** checked twice.\n\n## " in md
    found = search.search(conn, Model(conn), "checked twice")
    assert [(x.group, x.id) for x in found] == [("Notes", "T000012")]


def test_task_md_links_captions_and_lists_captures_not_on_the_page(root):
    conn, data_root, fs = root
    r = save(root, linked(content="Linked.", task="T000012"))
    md = (data_root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")
    assert f"_[Fri 16 Oct 2026 · 9:30 am · Note](../../Captures/2026/10/{r.capture_id}/capture.md)_" in md
    assert "## Captures\n" in md and "## Raw text log" not in md
    edits.save_page(conn, data_root, fs, "T000012", "", AT)
    md = (data_root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")
    line = next(x for x in md.split("\n") if r.capture_id in x and x.startswith("- "))
    assert line.endswith(" · not on the notes page") and "## Notes\n\n_No notes yet._" in md


def test_the_schema_upgrade_leaves_pages_to_be_built(data_root, fs):
    conn = db.connect(fs, data_root)
    assert notes_page.needs_build(conn) and conn.execute("SELECT count(*) FROM task_pages").fetchone()[0] == 0
    conn.close()


# ---- release 5.83: the task pane review's R4 and R4b ----
def test_a_file_s_text_that_only_repeats_its_description_isn_t_written_twice(root, tmp_path):
    f = tmp_path / "Pump spec.docx"
    f.write_bytes(b"x")
    save(root, CaptureDraft(task="T000012", content="The vendor's datasheet.", files=[FileRow("Pump spec.docx", str(f), "the vendor's datasheet")]))
    lines = lines_of(page(root, "T000012"))
    assert [(x.kind, x.text) for x in lines] == [("heading", "Fri 16 Oct 2026"), ("file", "File: Pump spec.docx, the vendor's datasheet")]


def test_a_block_with_no_caption_is_on_the_page_and_comes_off_with_its_capture(root, tmp_path):
    conn, data_root, fs = root
    f = tmp_path / "Pump spec.docx"
    f.write_bytes(b"x")
    r = save(root, CaptureDraft(task="T000012", files=[FileRow("Pump spec.docx", str(f), "the vendor's datasheet")]))
    model, stories = edits.stories_for(conn, data_root, AT)
    assert r.capture_id in notes_page.on_page(model, "T000012", page(root, "T000012"), stories)
    assert r.capture_id in notes_page.on_page(model, "T000012", page(root, "T000012"))  # Task.md's reading, without the text
    assert notes_page.edited_blocks(model, stories, r.capture_id) == []
    edits.discard_capture(conn, data_root, fs, r.capture_id, "", AT)
    assert "Pump spec.docx" not in page(root, "T000012")
    edits.bring_back_capture(conn, data_root, fs, r.capture_id, AT)
    assert "File: Pump spec.docx, the vendor's datasheet" in page(root, "T000012")
    model, stories = edits.stories_for(conn, data_root, AT)
    assert r.capture_id in notes_page.on_page(model, "T000012", page(root, "T000012"), stories)


def test_a_note_with_words_of_its_own_keeps_its_caption(root):
    r = save(root, linked(content="Typed with the link.", task="T000012"))
    assert r.capture_id in notes_page.capture_ids(page(root, "T000012"))


def test_a_task_made_from_meeting_notes_is_one_line_on_the_meeting_s_page(root):
    conn, data_root, fs = root
    r = save(root, CaptureDraft(content="Crane is booked.\n@Tom get the alignment report by Friday", task="T000010", meeting=True))
    made = Model(conn).captures[r.items[0]]
    p = page(root, r.meeting)
    task = next(x for x in lines_of(p) if x.kind == "task")
    assert task.ref == made.created_task and task.text.startswith("Task: ") and "alignment report" in task.text.lower() and "Tom Becker" in task.text
    assert "get the alignment report by Friday" not in p and "Crane is booked." in p
    assert "get the alignment report" in page(root, made.created_task).lower()  # the task's own page keeps the words
    assert notes_page.read_line(notes_page.task_line(task.text, task.ref)).text == task.text
    printed = notes_page.task_md(p, lambda _: None, task_link=lambda t: f"../{t}/Task.md")
    assert any(line.startswith("- [Task: ") and f"](../{made.created_task}/Task.md)" in line for line in printed)


def test_a_task_made_from_a_note_on_the_page_is_one_line_there(root):
    conn, data_root, fs = root
    r = save(root, CaptureDraft(content="Plan.\n@Tom get the alignment report by Friday", task="T000012"))
    assert r.capture_id is None and r.items  # the note is no capture (release 5.69); its item made a task
    lines = lines_of(page(root, "T000012"))
    assert [x.kind for x in lines] == ["heading", "text", "task"] and lines[2].ref == Model(conn).captures[r.items[0]].created_task


# ---- a task in a sub-bullet has its bullet tree as its notes (release 5.120, decision 446) ----
TREE = ("Crane is booked.\n"
        "- Pump overhaul prep @Priya\n"
        "  - parts list from the vendor\n"
        "  - @Tom book the 50 t crane\n"
        "    - for the 20th\n"
        "  - spares in the store\n"
        "- Seal kit, not in the tree")


def test_a_task_from_a_sub_bullet_has_its_whole_bullet_tree_on_its_page(root):
    conn = root[0]
    r = save(root, CaptureDraft(content=TREE, task="T000010", meeting=True))
    m = Model(conn)
    prep, crane = (m.captures[c].created_task for c in r.items)
    assert [p for p in m.parents_of(crane)] == [prep]
    crane_page = page(root, crane)
    for words in ("Pump overhaul prep", "parts list from the vendor", "book the 50 t crane", "for the 20th", "spares in the store"):
        assert words in crane_page
    assert "Seal kit" not in crane_page and "Crane is booked." not in crane_page
    assert "parts list from the vendor" in page(root, prep) and "50 t crane" not in page(root, prep)  # a top bullet's: its own lines
    # Its capture.md keeps its own lines, so the meeting's page still shows it as one task line where they were (R4b).
    assert any(x.kind == "task" and x.ref == crane for x in lines_of(page(root, r.meeting)))
    assert "for the 20th" not in page(root, r.meeting)
    # Its block is found on its page as it was added, so discarding it takes it off with no question (decision 106).
    model, stories = edits.stories_for(conn, root[1], AT)
    assert notes_page.edited_blocks(model, stories, r.items[1]) == []
