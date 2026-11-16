"""Release 5.150, notes without the operators (the design workspace's ``docs/mods/notes-syntax-plan.md``, decisions 652 to
657): a line of notes whose operators did what they say is a change line, a made task's own page shows its words with a
set line under them, a line that read as nothing or wasn't used stays as typed, the capture keeps its words as typed, and
Tidy the notes rewrites older pages, with Undo. Each row of the plan's table, saved both ways: a note that's no capture
(release 5.69) and a capture. Made up."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import captures, edits, markup, notes_page, page_lines, search
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.save import CaptureDraft, FileRow, save_capture

AT = datetime(2026, 10, 16, 9, 30)
SETTINGS = Settings(me="P001")
INSTALLATION, RIGGING, TOM = "T000008", "T000012", "P003"
#: The plan's table, on the sample's Installation (the plan's Pump trial).
ROWS = [
    "- @Tom book the 50 t crane **due, Fri **label, Rigging",
    "**task, Order spare seals **due, 20 Nov",
    "#Rigging plan **due, 30 Nov **lead, Tom",
    "Ask about the hire rate **agenda, Tom",
    "Seals look worn **label, Rigging",
]


def marked(lines: list[str]) -> str:
    """Lines as the capture window's markup keeps them: a typed ``**`` escaped, a "- " a list item."""
    return "\n".join("- " + markup.escape_inline(x[2:]) if x.startswith("- ") else markup.escape_inline(x) for x in lines)


@pytest.fixture
def root(sample_root):
    """The sample with its pages emptied, and Rigging plan without a Due, so ``**due,`` fills it."""
    conn = sample_root[0]
    conn.execute("DELETE FROM task_pages")
    conn.execute("UPDATE tasks SET due = NULL WHERE id = ?", (RIGGING,))
    conn.commit()
    return sample_root


def save(root, lines: list[str], *, as_capture: bool = False, task: str = INSTALLATION, at: datetime = AT, **kw):
    conn, data_root, fs = root
    draft = CaptureDraft(content=marked(lines), task=task, formatted=True, **kw)
    if as_capture:  # a link makes it a capture still (release 5.69, decision 345)
        draft.files = [FileRow("Spec sheet", "https://example.com/spec", "the spec")]
    return save_capture(conn, data_root, fs, SETTINGS, draft, at)


def lines(root, task_id: str) -> list[notes_page.Line]:
    return [x for x in notes_page.lines_of(notes_page.get(root[0], task_id)) if x.kind not in ("heading", "caption", "file")]


def made(root, title: str) -> str:
    return next(t.id for t in Model(root[0]).tasks.values() if t.title == title)


# ---- the lines ----
def test_change_and_set_lines_read_back_as_written():
    for line in (notes_page.change_line("Rigging plan", RIGGING, "Due Mon 30 Nov · Lead Tom Becker"),
                 notes_page.change_line("Seals look [worn]", INSTALLATION, "Rigging", 2),
                 notes_page.change_line("", INSTALLATION, "Due Fri 20 Nov"),
                 notes_page.set_line("Set from Installation's notes", INSTALLATION, "Due Fri 23 Oct · Rigging")):
        x = notes_page.read_line(line)
        assert x.kind in ("change", "set") and notes_page.write([x]) == line
    x = notes_page.read_line("  - [Seals look worn](change:T000008) · Rigging")
    assert (x.kind, x.text, x.level, x.ref, x.did) == ("change", "Seals look worn", 2, INSTALLATION, "Rigging")
    # Text that would read as one starts with a backslash, as a caption's does
    typed = notes_page.text_line("[a](change:T000001) · b")
    assert typed.startswith("\\") and notes_page.read_line(typed).kind == "text"


def test_the_words_without_the_operators():
    from docrepo import items

    names = items.Names([], [items.RefTask(RIGGING, "Rigging plan")])
    for typed, words in (("#Rigging plan **due, 30 Nov **lead, Tom", "Rigging plan"),
                         ("Ask about the hire rate **agenda, Tom", "Ask about the hire rate"),
                         ("#Rigging plan **closed, crane booked", "Rigging plan: crane booked"),
                         ("**decision, we go with the 50 t crane", "We go with the 50 t crane"),
                         ("Seals look worn **label, Rigging.", "Seals look worn")):
        assert page_lines.plain_words(typed, items.scan(typed, names), names) == words


# ---- each row of the plan's table ----
@pytest.mark.parametrize("as_capture", [False, True], ids=["page note", "capture"])
def test_each_row_of_the_table(root, as_capture):
    r = save(root, ROWS, as_capture=as_capture)
    crane, seals = made(root, "Book the 50 t crane"), made(root, "Order spare seals")
    got = lines(root, INSTALLATION)
    # Rows 1 and 2: task lines, as since release 5.83 (row 2's in a note that's no capture since this release).
    assert [(x.kind, x.ref) for x in got[:2]] == [("task", crane), ("task", seals)]
    # Rows 3 to 5: change lines (decision 654), Rigging plan the link, the page's own task none.
    assert [(x.kind, x.text, x.ref, x.did) for x in got[2:]] == [
        ("change", "Rigging plan", RIGGING, "Due Mon 30 Nov · Lead Tom Becker"),
        ("change", "Ask about the hire rate", INSTALLATION, "on Tom Becker's agenda"),
        ("change", "Seals look worn", INSTALLATION, "Rigging"),
    ]
    # The made tasks' own pages (decision 653): the words, names as names, and the set line under them.
    own = lines(root, crane)
    assert [(x.kind, markup.to_plain(x.text)) for x in own] == [("text", "- Tom Becker book the 50 t crane"), ("set", "Set from Installation's notes")]
    assert (own[1].ref, own[1].did) == (INSTALLATION, "Due Fri 23 Oct · Rigging")
    assert [(x.kind, x.did) for x in lines(root, seals)] == [("set", "Due Fri 20 Nov")]  # its words are its title (decision 115)
    # What the lines did, done
    m = Model(root[0])
    assert m.task(RIGGING).due == "2026-11-30" and TOM in m.task(RIGGING).leads and "Rigging" in m.task(INSTALLATION).labels
    assert any(a.subject == INSTALLATION and a.target == TOM and a.note == "Ask about the hire rate" for a in m.agenda)
    assert r.unused == 0


def test_the_capture_keeps_the_words_as_typed(root):
    """Decision 655: capture.md and the raw text log keep every operator."""
    conn, data_root, _ = root
    r = save(root, ROWS, as_capture=True)
    kept = captures.read_content(data_root, Model(conn).captures[r.capture_id])
    assert "**due, 30 Nov **lead, Tom" in markup.to_plain(kept) and "**agenda, Tom" in markup.to_plain(kept)
    item = next(c for c in Model(conn).captures.values() if c.from_notes == r.capture_id and c.item == "task" and "crane" in c.title)
    assert "**due, Fri **label, Rigging" in markup.to_plain(captures.read_content(data_root, item))


@pytest.mark.parametrize("as_capture", [False, True], ids=["page note", "capture"])
def test_a_line_read_as_nothing_or_not_used_stays_as_typed(root, as_capture):
    """A line whose operator read as nothing (its Unread card, release 5.92) stays as typed; so does one with an operator that
    wasn't used, here a Due already filled, so nothing on the page says it was done."""
    root[0].execute("UPDATE tasks SET due = '2026-10-14' WHERE id = ?", (RIGGING,))
    root[0].commit()
    save(root, ["Typo here **lable, Rigging", "#Rigging plan **due, 30 Nov **lead, Tom", "Seals look worn **label, Rigging"],
         as_capture=as_capture)
    got = lines(root, INSTALLATION)
    assert [(x.kind, markup.to_plain(x.text)) for x in got[:2]] == [("text", "Typo here **lable, Rigging"),
                                                                    ("text", "#Rigging plan **due, 30 Nov **lead, Tom")]
    assert got[2].kind == "change"


@pytest.mark.parametrize("as_capture", [False, True], ids=["page note", "capture"])
def test_an_update_and_a_decision_say_what_they_were(root, as_capture):
    """A ``**`` kind says what its item was; the same line reads the same on the page of the task it changed."""
    save(root, ["#Rigging plan **closed, crane booked", "**decision, we go with the 50 t crane"], as_capture=as_capture)
    got = lines(root, INSTALLATION)
    assert [(x.kind, x.text, x.ref, x.did) for x in got[:2]] == [("change", "Rigging plan: crane booked", RIGGING, "Closed"),
                                                                 ("change", "We go with the 50 t crane", INSTALLATION, "Decision")]
    assert [(x.kind, x.text, x.did) for x in lines(root, RIGGING)] == [("change", "Rigging plan: crane booked", "Closed")]


def test_every_kind_of_field_says_what_it_did(root):
    """A new task's own lines of fields, on its page: each a change line saying its field and value in words (a priority
    or a yes is no date); one not used (Duration, with a tied Start) stays as typed, as Save's message says."""
    content = ["Line 2 trial", "**due, 5 Nov.", "**lead, Tom.", "**hours, 12.", "**priority, high.", "**urgent, yes.", "**state, parked.",
               "**deadline, 19 Nov, the external audit.", "**duration, 2 weeks.", "**start, 3 workdays after #Rigging plan ends.",
               "**involvement, Tom 50%.", "**parent, #Installation", "**weekends, yes."]
    r = save(root, content, task=None, types={"new_task"})
    assert "1 line wasn't used" in r.message
    did = [x.did if x.kind == "change" else markup.to_plain(x.text) for x in lines(root, r.created_task)][1:]
    assert did == ["Due Thu 5 Nov", "Lead Tom Becker", "Assignee hours 12", "Priority High", "Urgent", "State Parked",
                   "Deadline Thu 19 Nov, the external audit", "**duration, 2 weeks.", "Start 3 workdays after Rigging plan ends",
                   "Involvement Tom Becker 50%", "Parents Installation", "Runs through weekends"]


def test_a_list_item_stays_one(root):
    save(root, ["- Seals look worn **label, Rigging", "  - #Rigging plan **lead, Tom"])
    got = lines(root, INSTALLATION)
    assert [(x.kind, x.level) for x in got] == [("change", 1), ("change", 2)]


def test_a_meeting_s_hash_task_section_stays_a_pointer(root):
    """In Meeting notes a ``#`` task's decision is a pointer line on the meeting's page (release 5.143), and its change line
    is on that task's page."""
    r = save(root, ["#Rigging plan", "**decision, use the 50 t crane"], task=INSTALLATION, meeting=True, meeting_name="Lift review")
    m = Model(root[0])
    assert [x.kind for x in lines(root, r.meeting)] == ["pointer"]
    assert [(x.kind, x.text, x.did) for x in lines(root, RIGGING)] == [("change", "Use the 50 t crane", "Decision")]
    assert m.task(r.meeting).title == "Lift review"


def test_task_md_and_search_read_the_words(root):
    conn, data_root, fs = root
    save(root, ROWS)
    m = Model(conn)
    md = notes_page.task_md(m.pages[INSTALLATION], lambda _: None, task_link=lambda t: f"../{t}/Task.md", own=INSTALLATION)
    assert "[Rigging plan](../T000012/Task.md) · _Due Mon 30 Nov · Lead Tom Becker_" in md
    assert "Seals look worn · _Rigging_" in md  # the page's own task isn't a link
    crane = made(root, "Book the 50 t crane")
    own = notes_page.task_md(m.pages[crane], lambda _: None, task_link=lambda t: f"../{t}/Task.md", own=crane)
    assert "_[Set from Installation's notes](../T000008/Task.md) · Due Fri 23 Oct · Rigging_" in own
    assert "Due Mon 30 Nov" in notes_page.words(m.pages[INSTALLATION])
    search.index_pages(conn, [INSTALLATION])
    assert [(x.group, x.id) for x in search.search(conn, Model(conn), "hire rate")][:1] == [("Notes", INSTALLATION)]


# ---- a capture's block, again ----
def test_a_capture_s_block_comes_off_as_it_was_added(root):
    """The block is written the same each time it's worked out (from the capture and what its save left), so discarding
    it takes it off; a block written before this release, in its old words, comes off too (decision 106)."""
    conn, data_root, fs = root
    r = save(root, ROWS[2:], as_capture=True)
    model, stories = edits.stories_for(conn, data_root, AT)
    assert notes_page.edited_blocks(model, stories, r.capture_id) == []
    c = model.captures[r.capture_id]
    old = notes_page.block(model, stories, c, INSTALLATION, notes_page.typed_content(c, stories.content_of(c.id)), rewrite=False)
    assert any("\\*\\*due" in x for x in old)
    notes_page.put(conn, INSTALLATION, notes_page.add_block("", old, AT.date(), True), AT)
    conn.commit()
    model, stories = edits.stories_for(conn, data_root, AT)
    assert notes_page.edited_blocks(model, stories, r.capture_id) == []
    edits.discard_capture(conn, data_root, fs, r.capture_id, "", AT)
    assert lines(root, INSTALLATION) == []


# ---- Tidy the notes (decision 656) ----
def old_pages(root, task_ids: list[str]) -> dict[str, str]:
    """The pages as release 5.149 wrote them: each capture's block as typed, and a note that's no capture as it was put."""
    conn, data_root, _ = root
    model, stories = edits.stories_for(conn, data_root, AT)
    out = {}
    for task_id in task_ids:
        body = ""
        for c in sorted(model.notes_of(task_id), key=lambda k: k.saved):
            body = notes_page.add_block(body, notes_page.block(model, stories, c, task_id, notes_page.typed_content(c, stories.content_of(c.id)),
                                                               rewrite=False), AT.date(), True)
        out[task_id] = body
    return out


def test_tidy_lists_changes_and_undoes_them(root):
    conn, data_root, fs = root
    save(root, ROWS)
    crane, seals = made(root, "Book the 50 t crane"), made(root, "Order spare seals")
    new = {t: notes_page.get(conn, t) for t in (INSTALLATION, crane, seals)}
    # The page as 5.149 put a note that's no capture: its lines as typed, the plain **task, item missed.
    typed = "\n".join(["# Fri 16 Oct 2026", new[INSTALLATION].split("\n")[1], *[markup.escape_inline(x) for x in ROWS[1:]]])
    pages = {INSTALLATION: typed, **old_pages(root, [crane, seals])}
    for task_id, body in pages.items():
        notes_page.put(conn, task_id, body, AT)
    conn.commit()
    model, stories = edits.stories_for(conn, data_root, AT)
    listed = edits.notes_to_tidy(model, stories, list(pages))
    assert {t.task for t in listed} == {INSTALLATION, crane, seals}
    assert all(t.before and t.after for t in listed)
    out, undo = edits.tidy_notes(conn, data_root, fs, listed, AT)
    assert out.message == "Tidied 6 lines on 3 pages."
    assert {t: notes_page.get(conn, t) for t in pages} == new  # as a save writes them now
    model, stories = edits.stories_for(conn, data_root, AT)
    assert edits.notes_to_tidy(model, stories, list(pages)) == []  # nothing left to tidy
    back = edits.undo_tidy_notes(conn, data_root, fs, undo, AT)
    assert back.message == "Set back: 3 pages as they were." and {t: notes_page.get(conn, t) for t in pages} == pages


def test_tidy_leaves_a_line_changed_since(root):
    conn, data_root, fs = root
    r = save(root, ROWS[2:], as_capture=True)
    model, stories = edits.stories_for(conn, data_root, AT)
    body = old_pages(root, [INSTALLATION])[INSTALLATION].replace("Seals look worn", "Seals look badly worn")
    notes_page.put(conn, INSTALLATION, body, AT)
    conn.commit()
    model, stories = edits.stories_for(conn, data_root, AT)
    listed = edits.notes_to_tidy(model, stories, [INSTALLATION])
    befores = [markup.to_plain(x) for t in listed for x in t.before]
    assert any("Rigging plan **due" in x for x in befores) and not any("Seals" in x for x in befores)
    out, undo = edits.tidy_notes(conn, data_root, fs, listed, AT)
    edits.save_page(conn, data_root, fs, INSTALLATION, notes_page.get(conn, INSTALLATION) + "\nMore typing.", AT)
    back = edits.undo_tidy_notes(conn, data_root, fs, undo, AT)
    assert "changed since, so stayed" in back.message and r.capture_id
