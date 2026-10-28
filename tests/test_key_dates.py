"""Key dates (release 5.31, the key dates plan, decisions 146 to 155): line items of dates on a task, saved, logged, worded,
due on Today and the lists, in Task.md, and made subtasks."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import edits, key_dates, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.pages import Pages
from docrepo.stories import Stories
from docrepo.tasks import KeyDateRow, TaskError

AT = datetime(2026, 10, 8, 9, 30)
TODAY = AT.date()
SETTINGS = Settings(me="P001")
TRIAL = [KeyDateRow("2026-10-01", None, "Trial planning period"),
         KeyDateRow(None, "2026-10-14", "Target for trial preparations", deadline=True),
         KeyDateRow("2026-12-01", "2026-12-05", "Trial execution window", plant=True)]


def test_kinds_and_words():
    kds = [tasks._key_date(r, "T1", None, i) for i, r in enumerate(TRIAL)]
    assert [key_dates.kind(k) for k in kds] == ["from", "by", "window"]
    assert [key_dates.when_text(k, TODAY) for k in kds] == ["from Thu 1 Oct", "by Wed 14 Oct", "Tue 1 Dec to Sat 5 Dec"]
    assert key_dates.log_text(kds[2]) == "Trial execution window, Tue 1 Dec 2026 to Sat 5 Dec 2026, plant activity"
    assert key_dates.log_text(kds[1]).endswith("by Wed 14 Oct 2026, deadline")
    one = tasks._key_date(KeyDateRow("2026-11-02", "2026-11-02"), "T1", None, 0)
    assert (key_dates.kind(one), key_dates.label(one, TODAY)) == ("on", "Key date, on Mon 2 Nov")
    assert key_dates.problem(None, None) and key_dates.problem("2026-10-05", "2026-10-01") and key_dates.problem("1 Oct", None)
    assert key_dates.problem("2026-10-01", None) is None


def test_saved_logged_and_worded_in_the_story(sample_conn):
    logged = tasks.set_key_dates(sample_conn, "T000008", TRIAL, at=AT, via="Browse tool")
    assert [c.field for c in logged] == ["Key date"] * 3 and all(c.from_value is None for c in logged)
    m = Model(sample_conn)
    assert [kd.description for kd in m.key_dates_of("T000008")] == [r.description for r in TRIAL]
    assert [(t.id, kd.description) for t, kd in m.plant_activities()] == [("T000008", "Trial execution window")]
    # Change one, tick another done, take the first off, in a new order: each logged, the order alone not.
    rows = tasks.key_date_rows(sample_conn, "T000008")
    rows[1].done = True
    rows[2].description = "Trial run"
    logged = tasks.set_key_dates(sample_conn, "T000008", [rows[2], rows[1]], at=datetime(2026, 10, 9, 8, 0), via="Browse tool")
    assert [(c.field, c.from_value is None, c.to_value is None) for c in logged] == [
        ("Key date", False, False), ("Key date done", True, False), ("Key date", False, True)]
    m = Model(sample_conn)
    assert [(kd.description, kd.done) for kd in m.key_dates_of("T000008")] == [("Trial run", None), ("Target for trial preparations", "2026-10-09")]
    said = Stories(m, TODAY, lambda c: "", "P001").field_sentence
    entries = [e for e in Stories(m, TODAY, lambda c: "", "P001").log("T000008") if e.field.startswith("Key date")]
    words = [said(e) for e in entries]
    assert "Key date added: Trial execution window, Tue 1 Dec 2026 to Sat 5 Dec 2026, plant activity." in words
    assert "Key date done: Target for trial preparations, by Wed 14 Oct 2026, deadline." in words
    assert "Key date taken off: Trial planning period, from Thu 1 Oct 2026." in words
    with pytest.raises(TaskError):
        tasks.set_key_dates(sample_conn, "T000008", [KeyDateRow("2026-10-05", "2026-10-01")], at=AT, via="Browse tool")


def test_due_on_today_and_the_lists(sample_conn):
    """Decisions 148 and 150: an end is due on it and overdue once passed; a start alone shows from a week before, never
    overdue; done ones and closed tasks' are left out; each is its own row."""
    tasks.set_key_dates(sample_conn, "T000008", [
        KeyDateRow(None, "2026-10-05", "Order the seals"),       # overdue
        KeyDateRow(None, "2026-10-12", "Crane booked"),          # due in 4 days
        KeyDateRow("2026-10-10", None, "Rigging starts"),        # starts in 2 days
        KeyDateRow(None, "2026-10-30", "Too far off"),
        KeyDateRow(None, "2026-10-07", "Done already", done=True),
    ], at=AT, via="Browse tool")
    tasks.set_key_dates(sample_conn, "T000016", [KeyDateRow(None, "2026-10-09", "Closed task's")], at=AT, via="Browse tool")
    tasks.update_task(sample_conn, SETTINGS, "T000016", at=AT, via="Browse tool", state="Closed")
    due = key_dates.due(Model(sample_conn), TODAY)
    assert [(d.key_date.description, d.overdue, d.starts) for d in due] == [
        ("Order the seals", True, False), ("Rigging starts", False, True), ("Crane booked", False, False)]
    assert [d.text(TODAY) for d in due] == ["Order the seals, was due Mon 5 Oct", "Rigging starts, from Sat 10 Oct", "Crane booked, by Mon 12 Oct"]
    assert key_dates.due(Model(sample_conn), date(2026, 10, 10))[1].text(date(2026, 10, 10)) == "Starts today: Rigging starts"
    assert key_dates.span(Model(sample_conn), "T000008") == (date(2026, 10, 5), date(2026, 10, 30))


def test_edit_task_saves_them_and_task_md_prints_them(sample_root):
    conn, root, fs = sample_root
    out = edits.edit_task(conn, root, fs, SETTINGS, "T000008", AT, key_dates=TRIAL)
    assert out.message == "3 changes in the status log."
    md = (root / "Tasks" / "T000008" / "Task.md").read_text(encoding="utf-8")
    assert "## Key dates" in md and "| Tue 1 Dec to Sat 5 Dec | Trial execution window | Plant activity |" in md
    assert "| by Wed 14 Oct | Target for trial preparations | Deadline |" in md
    assert edits.edit_task(conn, root, fs, SETTINGS, "T000008", AT, key_dates=tasks.key_date_rows(conn, "T000008")).message == "Nothing changed."
    key_id = tasks.key_date_rows(conn, "T000008")[1].id
    assert edits.set_key_date_done(conn, root, fs, key_id, True, AT).message == "Done: a key date of Installation."
    assert "Done 2026-10-08" in (root / "Tasks" / "T000008" / "Task.md").read_text(encoding="utf-8")


def test_make_it_a_subtask(sample_root):
    """Item 61: a subtask from a key date, its dates and ticks carried over; the key date is taken off."""
    conn, root, fs = sample_root
    tasks.set_key_dates(conn, "T000008", TRIAL, at=AT, via="Browse tool")
    window = tasks.key_date_rows(conn, "T000008")[2]
    out = edits.key_date_subtask(conn, root, fs, SETTINGS, window.id, AT)
    m = Model(conn)
    child = next(t for t in m.tasks.values() if t.title == "Trial execution window")
    assert out.message.startswith(f"{child.id} is a subtask of Installation")
    assert (child.start, child.due, child.plant_event, m.parents_of(child.id)) == ("2026-12-01", "2026-12-05", True, ["T000008"])
    assert [kd.description for kd in m.key_dates_of("T000008")] == ["Trial planning period", "Target for trial preparations"]
