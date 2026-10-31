"""Today (mods log round 1, M0016): the built-in agenda target that is the owner's list for the day."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import agenda, edits, views
from docrepo.config import Settings
from docrepo.detail import PageState
from docrepo.detail import Pages as TaskPages
from docrepo.model import TODAY, Model
from docrepo.pages import Pages
from docrepo.save import CaptureDraft, save_capture
from docrepo.stories import Stories

AT = datetime(2026, 10, 8, 15, 20)
SETTINGS = Settings(me="P001")


def test_reminders_due_are_those_whose_day_has_come(sample_conn):
    """Item 77: today's and past ones, oldest first; open tasks only. The Reminders list also has the next 7 days'."""
    from docrepo.lists import LISTS, list_tasks, reminders_due

    m = Model(sample_conn)
    assert [t.id for t in reminders_due(m, AT.date())] == ["T000016", "T000018"]
    assert [t.id for t in reminders_due(m, date(2026, 10, 6))] == []
    assert [t.id for t in reminders_due(m, date(2026, 10, 9))] == ["T000016", "T000018", "T000019"]
    assert [t.id for t in list_tasks(m, next(x for x in LISTS if x.id == "reminders"), AT.date(), "P001")] == ["T000016", "T000018", "T000019"]
    sample_conn.execute("UPDATE tasks SET state = 'Closed', closed = '2026-10-08' WHERE id = 'T000016'")
    assert [t.id for t in reminders_due(Model(sample_conn), AT.date())] == ["T000018"]


def test_today_items_carry_over_until_done(sample_conn):
    conn = sample_conn
    first = agenda.add_item(conn, subject="T000019", target=TODAY, note="", added="2026-10-05 08:05:00", added_by="Browse tool")
    assert agenda.add_item(conn, subject="T000019", target=TODAY, note="", added="2026-10-08 08:00:00", added_by="Browse tool") == first  # once only
    note = agenda.add_item(conn, subject=None, target=TODAY, note="Sign the overtime sheets", added="2026-10-08 07:50:00", added_by="Browse tool")
    m = Model(conn)
    assert [a.id for a in m.today_items()] == [first, note] and TODAY not in m.agenda_targets()
    assert m.target_name(TODAY) == "Today" and m.meeting_when(TODAY, AT.date()) == ""
    assert [(g, [a.id for a in items]) for g, items in views.today_groups(m, AT.date())] == [("Carried over", [first]), ("Added today", [note])]
    assert views.since_text("2026-10-05 08:05:00", AT.date()) == "Mon" and views.since_text("2026-09-20 08:05:00", AT.date()) == "20 Sep"
    with pytest.raises(agenda.AgendaError, match="closes as Done or Removed"):
        agenda.close_item(conn, first, how="Discussed", closed="2026-10-08 15:20:00", closed_by="Today")
    agenda.close_item(conn, first, how="Done", closed="2026-10-08 15:20:00", closed_by="Today")
    m = Model(conn)
    assert [a.id for a in m.today_items()] == [note] and [a.id for a in m.done_on(AT.date())] == [first] and m.done_on(date(2026, 10, 9)) == []
    meeting_item = next(a for a in m.open_items_for("T000010"))
    with pytest.raises(agenda.AgendaError, match="closes as Discussed or Removed"):
        agenda.close_item(conn, meeting_item.id, how="Done", closed="2026-10-08 15:20:00", closed_by="Agenda view")
    stories = Stories(m, AT.date(), lambda _: "")
    assert [stories.field_sentence(e) for e in m.status_log_of("T000019") if e.field == "Agenda"] == ["Added to Today.", "Done for today."]


def test_adding_from_the_browse_tool_and_the_pages(sample_root):
    conn, root, fs = sample_root
    assert edits.add_to_today(conn, root, fs, "T000012", "", AT).message == "Rigging plan is on Today. Its status log says so."
    assert edits.add_to_today(conn, root, fs, "T000012", "", AT).message == "Rigging plan is on Today already."
    assert edits.add_to_today(conn, root, fs, None, "  Call the crane company  back ", AT).message == "Note added to Today."
    m = Model(conn)
    assert [(a.subject, a.note) for a in m.today_items()] == [("T000012", ""), (None, "Call the crane company back")]
    contents = (root / "Contents.md").read_text(encoding="utf-8")
    assert "### Today\n\n- [Rigging plan](Tasks/T000012/Task.md)\n- Call the crane company back\n" in contents
    assert "| On agendas | Today |" in (root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")
    page = TaskPages(m, AT.date(), lambda _: "", "P001", conn).task_page("T000012", PageState())
    assert 'href="agenda:today"' in page  # its On agendas row links to the Today view
    item = m.today_items()[0]
    assert edits.close_today_item(conn, root, fs, item.id, "Done", AT).message == "Rigging plan: done. Its status log says so."
    later = Pages(Model(conn), date(2026, 10, 9), AT).contents_page()
    assert "- Call the crane company back · since 2026-10-08" in later  # carried over to the next day


def test_a_note_on_today_from_the_capture_window(sample_root):
    conn, root, fs = sample_root
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Book the meeting room for Friday.", types={"note"}, agenda=[TODAY]), AT)
    assert r.message == f"Saved {r.capture_id}. On Today."
    m = Model(conn)
    a = m.today_items()[-1]
    assert (a.subject, a.note, a.added_by) == (None, "Book the meeting room for Friday.", r.capture_id)
    assert not m.is_unfiled(m.captures[r.capture_id])
    r2 = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Bring it up.", task="T000012", types={"update"}, agenda=[TODAY, "T000010"]), AT)
    assert r2.message.endswith("On Today and the agenda of Business team meeting.")
