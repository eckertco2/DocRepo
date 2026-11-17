"""Release 5.158, Recent captures (the design workspace's ``docs/mods/recent-captures-plan.md``, decisions 722 to 727): what
the list holds and in what order, what typing finds, each row's kind, words and time, and the page each one opens on. No Qt.
Every name here is the sample data's, made up."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import capacity, db
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.recent_captures import LIMIT, OFF_PAGE, ON_AGENDA, UNFILED, kind_of, listed, page_of, recent_rows, when_text
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, save_capture

TODAY = date(2026, 10, 8)  # the sample data's day, a Thursday
AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
NOTES = """Impeller is on site.
- @Tom get the alignment report by Friday
- **decision, we go with the 50 t crane.
- @Sam to book the scaffolding"""


@pytest.fixture
def conn(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, TODAY, SETTINGS)
    yield c
    c.close()


def ids(rows) -> list[str]:
    return [r.id for r in rows]


def set_page(conn, task_id: str, body: str) -> None:
    conn.execute("UPDATE task_pages SET body = ? WHERE task = ?", (body, task_id))
    conn.commit()


def caption_of(page: str, capture_id: str) -> str:
    return next(line for line in page.split("\n") if line.endswith(f"(capture:{capture_id})"))


# ---- what it lists (decision 724) ----
def test_the_last_ten_saved_newest_first(conn):
    rows = recent_rows(Model(conn), TODAY)
    assert len(rows) == LIMIT == 10
    assert ids(rows) == ["C000025", "C000024", "C000023", "C000022", "C000021", "C000020", "C000019", "C000018", "C000017", "C000016"]


def test_a_discarded_capture_is_left_out(conn):
    conn.execute("UPDATE captures SET discarded = '2026-10-08 13:55:00', discard_reason = 'made by mistake' WHERE id = 'C000025'")
    conn.commit()
    rows = recent_rows(Model(conn), TODAY)
    assert "C000025" not in ids(rows) and ids(rows)[0] == "C000024" and len(rows) == 10


def test_meeting_notes_are_one_row_and_their_items_none(data_root, fs, conn):
    """A meeting's items are captures of their own, saved in the same second; the notes capture stands for them."""
    r = save_capture(conn, data_root, fs, SETTINGS, CaptureDraft(content=NOTES, task="T000010", meeting=True), AT)
    m = Model(conn)
    assert len(r.items) == 3 and all(not listed(m.captures[i]) for i in r.items)
    rows = recent_rows(m, TODAY)
    assert ids(rows)[:2] == [r.capture_id, "C000025"] and not set(r.items) & set(ids(rows))
    notes = rows[0]
    meeting = m.task(r.meeting)
    assert (notes.kind, notes.kind_words, notes.page, notes.where, notes.when) == ("meeting", "Meeting notes", meeting.id, meeting.title, "14:10")


def test_a_picture_made_on_a_page_is_not_listed(conn):
    conn.execute("UPDATE captures SET page_made = 1 WHERE id = 'C000025'")
    conn.commit()
    assert "C000025" not in ids(recent_rows(Model(conn), TODAY))


# ---- typing (decision 724) ----
def test_typing_finds_titles_across_every_capture_still_newest_first(conn):
    rows = recent_rows(Model(conn), TODAY, "impeller")
    # Seven, the oldest well past the last ten, each a title with a word starting "impeller".
    assert ids(rows) == ["C000014", "C000012", "C000010", "C000008", "C000005", "C000003", "C000002"]
    assert ids(recent_rows(Model(conn), TODAY, "imp new")) == ["C000010", "C000008", "C000005", "C000002"]  # words in any order
    assert ids(recent_rows(Model(conn), TODAY, "seal")) == ["C000007", "C000006", "C000002"]


def test_typing_keeps_to_ten_rows_and_finds_an_id(conn):
    m = Model(conn)
    assert len(recent_rows(m, TODAY, "t")) == 10
    assert ids(recent_rows(m, TODAY, "C000003")) == ["C000003"]
    assert recent_rows(m, TODAY, "zeppelin") == []


# ---- each row (decision 724) ----
def test_each_kind(conn):
    conn.execute("INSERT INTO t_mails (task, kind, opened, capture) VALUES ('T000001', 'new', '2026-09-10 13:50:00', 'C000003')")
    conn.commit()
    m = Model(conn)
    copies = {"C000003"}
    assert kind_of(m.captures["C000003"], copies) == "t_mail"  # a T-mail's sent copy
    assert kind_of(m.captures["C000021"], copies) == "email"
    assert kind_of(m.captures["C000020"], copies) == "new_task"
    assert kind_of(m.captures["C000025"], copies) == "update"
    assert kind_of(m.captures["C000022"], copies) == "note"
    assert kind_of(m.captures["C000023"], copies) == "note"  # a file dropped in, kept as a note
    row = recent_rows(m, TODAY, "C000003")[0]
    assert (row.kind, row.kind_words) == ("t_mail", "T-mail sent")


def test_where_each_opens_and_its_words(conn):
    rows = {r.id: r for r in recent_rows(Model(conn), TODAY)}
    assert (rows["C000025"].page, rows["C000025"].where) == ("T000011", "Draft monitoring plan")
    assert (rows["C000021"].page, rows["C000021"].where, rows["C000021"].kind) == (None, UNFILED, "email")
    assert (rows["C000024"].page, rows["C000024"].where) == (None, ON_AGENDA)  # a note put on an agenda, with no task
    assert (rows["C000025"].when, rows["C000017"].when, rows["C000016"].when) == ("13:52", "Wed", "Tue")


def test_when_in_the_browse_tool_s_short_form():
    assert when_text("2026-10-08 09:40:00", TODAY) == "9:40"
    assert when_text("2026-10-08 00:05:00", TODAY) == "0:05"
    assert when_text("2026-10-07 18:00:00", TODAY) == "Wed"
    assert when_text("2026-10-02 18:00:00", TODAY) == "Fri"
    assert when_text("2026-10-01 18:00:00", TODAY) == "1 Oct"
    assert when_text("2025-11-12 08:00:00", TODAY) == "12 Nov 2025"


def test_a_capture_with_no_title_says_what_it_is(conn):
    conn.execute("UPDATE captures SET title = '' WHERE id = 'C000025'")
    conn.commit()
    assert recent_rows(Model(conn), TODAY)[0].title == "Update C000025"


# ---- the page it opens on (decisions 725 and 726) ----
def test_the_page_that_holds_the_block(conn):
    m = Model(conn)
    assert page_of(m, m.captures["C000013"]) == "T000008"
    assert page_of(m, m.captures["C000024"]) is None  # unfiled


def test_a_block_taken_off_its_page_opens_its_own_page(conn):
    page = Model(conn).pages["T000008"]
    set_page(conn, "T000008", page.replace(caption_of(page, "C000013") + "\n", "").replace(
        "Bring up the 20 Oct crane booking at the next business team meeting.", ""))
    m = Model(conn)
    assert page_of(m, m.captures["C000013"]) is None
    row = next(r for r in recent_rows(m, TODAY, "C000013"))
    assert (row.page, row.where) == (None, OFF_PAGE)


def test_a_block_with_no_caption_is_found_by_its_file_lines(conn):
    """Release 5.83: a block can be its file lines alone; Edit capture's caption test misses it, the file lines don't."""
    page = Model(conn).pages["T000008"]
    set_page(conn, "T000008", page.replace(caption_of(page, "C000005") + "\n", ""))
    m = Model(conn)
    assert "C000005" not in m.pages["T000008"] and "(document:D000002)" in m.pages["T000008"]
    assert page_of(m, m.captures["C000005"]) == "T000008"


def test_the_first_task_it_was_filed_on_when_two_pages_hold_it(conn):
    """C000025 is an update on T000011; filed to T000001 as well, with its caption on both pages, it opens on T000011."""
    m = Model(conn)
    caption = caption_of(m.pages["T000011"], "C000025")
    conn.execute("UPDATE captures SET filed_to = 'T000001' WHERE id = 'C000025'")
    set_page(conn, "T000001", m.pages["T000001"] + "\n" + caption + "\nCopied here too.")
    m = Model(conn)
    assert m.capture_tasks(m.captures["C000025"]) == ["T000011", "T000001"]
    assert page_of(m, m.captures["C000025"]) == "T000011"
    set_page(conn, "T000011", m.pages["T000011"].replace(caption + "\n", "").replace(caption, ""))
    m = Model(conn)
    assert page_of(m, m.captures["C000025"]) == "T000001"  # only the second holds it now
