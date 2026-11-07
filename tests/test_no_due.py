"""Release 5.82: a task gets no Due it wasn't given. A meeting's day is its Start, meetings stay off Today's Due in the
next 7 days and the Overdue and next 7 days list, whatever their dates, and "today" alone in a capture's text isn't a date."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import capacity, db, tasks, timeline
from docrepo.config import Settings
from docrepo.dates import long_date
from docrepo.detail import Pages
from docrepo.lists import LISTS, list_tasks
from docrepo.model import Model, Task
from docrepo.parse import parse_capture
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, NewTaskFields, save_capture
from docrepo.schedule import held_on, windows
from docrepo.views import today_due_entries

AT = datetime(2026, 10, 8, 14, 10)
TODAY = AT.date()
SETTINGS = Settings(me="P001")
DUE = next(x for x in LISTS if x.id == "due")
NOTES = """#Installation
- @Tom get the alignment report by Friday
- @Tom check the crane anchors today
Spoke with the vendor today about the seals."""


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, TODAY, SETTINGS)
    yield conn, data_root, fs
    conn.close()


def save(env, draft: CaptureDraft):
    conn, root, fs = env
    return save_capture(conn, root, fs, SETTINGS, draft, AT)


def on_lists(conn) -> tuple[set[str], set[str]]:
    """The task IDs on Overdue and next 7 days, and on Today's Due in the next 7 days."""
    m = Model(conn)
    return ({t.id for t in list_tasks(m, DUE, TODAY, "P001")},
            {t.id for t in today_due_entries(m, TODAY, "P001") if isinstance(t, Task)})


def test_a_new_meeting_has_its_day_as_its_start_and_no_due(env):
    conn = env[0]
    r = save(env, CaptureDraft(content=NOTES, task="T000008", meeting=True, meeting_name="Crane lift review"))
    m = Model(conn)
    meeting = m.task(r.meeting)
    assert (meeting.meeting, meeting.state, meeting.start, meeting.due, meeting.deadline) == (True, "In progress", "2026-10-08", None, None)
    made = {m.task(c.created_task).title: m.task(c.created_task) for c in (m.captures[x] for x in r.items) if c.created_task}
    report, anchors = made["Get the alignment report"], made["Check the crane anchors"]
    assert report.due == "2026-10-09"  # a date it was given
    assert (anchors.due, anchors.deadline) == (None, None)  # "today" alone isn't one
    listed, today = on_lists(conn)
    assert meeting.id not in listed and meeting.id not in today
    assert report.id in listed and report.id in today and anchors.id not in listed


def test_a_meetings_day_shows_where_its_due_did(env):
    conn = env[0]
    r = save(env, CaptureDraft(content=NOTES, task="T000008", meeting=True, meeting_name="Crane lift review"))
    m = Model(conn)
    meeting = m.task(r.meeting)
    assert held_on(meeting) == TODAY
    assert m.meeting_when(meeting.id, TODAY) == long_date(TODAY, TODAY)  # the Add to menu's date, not "no date set"
    assert windows(meeting, date(2026, 12, 31)) == [(TODAY, TODAY)]  # one day on the timeline
    assert not timeline.is_undated(meeting, TODAY, m)
    rows = dict(Pages(m, TODAY, lambda cid: "").when_rows(meeting))
    assert rows["Meeting"] == long_date(TODAY, TODAY) and "Due" not in rows and "Starts" not in rows


def test_this_times_meeting_of_a_regular_meeting_has_no_due(env):
    conn = env[0]
    r = save(env, CaptureDraft(content="Impeller is on site.", task="T000010", meeting=True))
    meeting = Model(conn).task(r.meeting)
    assert (meeting.title, meeting.start, meeting.due) == ("Business team meeting 8 Oct", "2026-10-08", None)
    assert meeting.id not in on_lists(conn)[0]


def test_a_meeting_with_a_due_stays_off_the_lists_and_its_subtasks_stay_on(env):
    """Meetings made before release 5.82 have today as their Due: they leave Today too, and what's under them stays."""
    conn = env[0]
    meeting = tasks.create_task(conn, SETTINGS, title="Vendor kickoff", at=AT, created_by="C000001", state="In progress",
                                meeting=True, due="2026-10-06")
    follow_up = tasks.create_task(conn, SETTINGS, title="Send the vendor the tie-in list", at=AT, created_by="C000001",
                                  parents=[meeting], due="2026-10-09")
    undated = tasks.create_task(conn, SETTINGS, title="Ask about spares", at=AT, created_by="C000001", parents=[meeting])
    listed, today = on_lists(conn)
    assert meeting not in listed and meeting not in today
    assert follow_up in listed and follow_up in today
    assert undated not in listed and undated not in today
    assert held_on(Model(conn).task(meeting)) is None  # its Due is still its day


def test_a_task_saved_with_no_due_has_none(env):
    conn = env[0]
    r = save(env, CaptureDraft(content="Spoke with Tom today about the seals.", types={"new_task"}, task="T000008",
                               new_task=NewTaskFields(title="Order spare seals")))
    t = Model(conn).task(r.created_task)
    assert (t.due, t.deadline, t.start) == (None, None, None)
    assert t.id not in on_lists(conn)[1]


@pytest.mark.parametrize(("text", "due", "deadline"), [
    # When something happened, or a day with nothing to meet: no date.
    ("Spoke with Tom today about the seals.", None, None),
    ("Met the vendor today; they'll send the drawings.", None, None),
    ("Today I need to sort out the vendor list.", None, None),
    ("Order the seals today.", None, None),
    ("Discussed tonight: the crane lift plan.", None, None),
    ("Spoke with Tom today about the outage.", None, None),  # an event word after it doesn't make it one
    # A word that makes it a date to meet.
    ("Call the vendor by today.", "2026-10-08", None),
    ("Due today: the permit form.", "2026-10-08", None),
    ("The permit form is due today.", "2026-10-08", None),
    ("The deadline is today.", None, "2026-10-08"),
    ("We must order the seals today.", None, "2026-10-08"),
    ("Today at the latest: the permit form.", None, "2026-10-08"),
    # Dates of their own, as before.
    ("Send the permit form by EOD today.", "2026-10-08", None),
    ("Get the quote a week from today.", "2026-10-15", None),
    ("Talked to Tom today; he needs the drawings by Friday.", "2026-10-09", None),
])
def test_today_alone_isnt_a_date(text, due, deadline):
    for kind in ("new_task", "update"):
        r = parse_capture(text, kind, TODAY, [], [], SETTINGS.event_words)
        assert (r.due and r.due.isoformat(), r.deadline and r.deadline.isoformat()) == (due, deadline), (kind, text)


def test_today_still_starts_and_reminds():
    r = parse_capture("Starting today, Tom covers the night shift.", "new_task", TODAY, [], [], SETTINGS.event_words)
    assert (r.start, r.due) == (TODAY, None)
    r = parse_capture("Remind Tyler today to book the crane.", "new_task", TODAY, [], [], SETTINGS.event_words)
    assert r.reminder == TODAY  # a reminder is asked for outright, and is the Due when there's no other
