"""Release 5.127, today's meetings from the Outlook calendar (the cold-eyes plan's decisions 488 to 495), without Qt: a subject's
key, the links (schema 26), the suggestion, the day as Today shows it, the read every 5 minutes, and the read itself with a
fake Outlook: in the plan's order, only decision 488's fields, a private one's subject never read, and Outlook never started.
Every subject, place and name here is made up."""
from __future__ import annotations

import sqlite3
import zipfile
from datetime import date, datetime, timedelta

import pytest

from docrepo import db, meetings, outlook, tasks
from docrepo.config import Settings
from docrepo.meetings import FREE, TENTATIVE, Appointment, TodayCalendar
from docrepo.model import Model
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample
from tests.test_migrations import ROOTS

#: The real read, kept before the tests' own stand-in (conftest's ``no_outlook_calendar``) replaces it.
REAL_READ = outlook.todays_appointments
NOW = datetime(2026, 10, 8, 10, 40)
BUSINESS, TOM = "T000010", "P003"


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 8, h, m)


APPTS = [
    Appointment("Contractors on site", datetime(2026, 10, 8), datetime(2026, 10, 9), all_day=True, busy=FREE),
    Appointment("Morning safety huddle", at(7, 30), at(7, 45), "Control room", recurring=True),
    Appointment("Pump trial check-in", at(8, 30), at(9), "Teams"),
    Appointment("Updated: Rigging plan review", at(10, 30), at(11), "Teams"),
    Appointment("Business team meeting", at(11), at(12), "Conf room B", recurring=True),
    Appointment("Lunch", at(12), at(13), busy=FREE),
    Appointment("Tom / Me: weekly 1:1", at(13, 30), at(14), "Tom's office", recurring=True),
    Appointment("", at(15), at(15, 30), private=True),
    Appointment("Vendor call: seal supplier", at(16), at(16, 30), "Teams", busy=TENTATIVE),
]


@pytest.fixture
def conn(sample_conn):
    return sample_conn


# ---- the subject's key (decision 491) ----
@pytest.mark.parametrize("subject, key", [
    ("Business team meeting", "business team meeting"),
    ("RE: Updated: Business  Team Meeting ", "business team meeting"),
    ("FW: fwd: re:Pump trial", "pump trial"),
    ("[EXTERNAL] Accepted: Vendor call", "vendor call"),
    ("Canceled: Tentative: Lunch & learn", "lunch & learn"),
    ("Tom / Me: weekly 1:1", "tom / me: weekly 1:1"),  # a colon later on is the subject's own
    ("RE:", ""),
    ("", ""),
])
def test_a_subjects_key_sets_aside_case_and_the_prefixes(subject, key):
    assert meetings.subject_key(subject) == key


# ---- links (schema 26) ----
def test_a_link_is_kept_by_its_key_and_replaced_by_another(conn):
    link = meetings.set_link(conn, "RE: Business team meeting", BUSINESS, NOW)
    assert (link.key, link.subject, link.task, link.person) == ("business team meeting", "RE: Business team meeting", BUSINESS, None)
    meetings.set_link(conn, "business TEAM meeting", TOM, NOW)  # the same key: the link moves to Tom
    found = meetings.links(conn)
    assert list(found) == ["business team meeting"] and found["business team meeting"].person == TOM
    assert found["business team meeting"].task is None and found["business team meeting"].target == TOM


def test_a_link_needs_a_key_and_a_target_that_is_there(conn):
    with pytest.raises(meetings.LinkError, match="no subject"):
        meetings.set_link(conn, "RE:", BUSINESS, NOW)
    with pytest.raises(meetings.LinkError, match="no task T999999"):
        meetings.set_link(conn, "Weekly", "T999999", NOW)
    with pytest.raises(meetings.LinkError, match="no person P999"):
        meetings.set_link(conn, "Weekly", "P999", NOW)
    with pytest.raises(sqlite3.IntegrityError):  # a task or a person, never both and never neither
        conn.execute("INSERT INTO meeting_links (key, subject, task, person, linked) VALUES ('x', 'x', ?, ?, '2026-10-08')", (BUSINESS, TOM))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO meeting_links (key, subject, task, person, linked) VALUES ('x', 'x', NULL, NULL, '2026-10-08')")
    assert meetings.links(conn) == {}


def test_remove_and_put_back(conn):
    meetings.set_link(conn, "Business team meeting", BUSINESS, NOW)
    old = meetings.remove_link(conn, "business team meeting")
    assert old is not None and old.task == BUSINESS and meetings.links(conn) == {}
    assert meetings.remove_link(conn, "business team meeting") is None
    meetings.put_back(conn, old, old.key)  # Undo of the Remove
    assert meetings.links(conn)["business team meeting"] == old
    meetings.put_back(conn, None, old.key)  # Undo of the first link: none
    assert meetings.links(conn) == {}


def test_a_discarded_tasks_link_isnt_live(conn):
    meetings.set_link(conn, "Business team meeting", BUSINESS, NOW)
    conn.execute("UPDATE tasks SET discarded = '2026-10-08 09:00' WHERE id = ?", (BUSINESS,))
    m = Model(conn)
    assert meetings.live_target(m, meetings.links(conn)["business team meeting"]) is None


# ---- the suggestion (decision 491) ----
def test_the_suggestion_is_the_meeting_task_with_the_subjects_words(conn):
    m = Model(conn)
    assert meetings.suggest(m, "Business team meeting") == BUSINESS
    assert meetings.suggest(m, "RE: Weekly Business Team Meeting (Ops)") == BUSINESS  # every word of its title is there
    assert meetings.suggest(m, "Business team") is None  # its title's "meeting" isn't
    assert meetings.suggest(m, "Rigging plan") is None  # a task, but not a meeting
    assert meetings.suggest(m, "") is None


def test_an_occurrence_is_never_suggested_and_a_tie_isnt_guessed(conn):
    settings = Settings(me="P001")
    occurrence = tasks.create_task(conn, settings, title="Business team meeting 8 Oct", at=NOW, created_by="test", parents=[BUSINESS],
                                   state="In progress", meeting=True, start="2026-10-08")
    m = Model(conn)
    assert meetings.occurrence(m, m.task(occurrence)) and occurrence not in [t.id for t in meetings.meeting_tasks(m)]
    assert meetings.suggest(m, "Business team meeting 8 Oct") == BUSINESS
    one_off = tasks.create_task(conn, settings, title="Business team meeting", at=NOW, created_by="test", meeting=True)
    m = Model(conn)
    assert meetings.suggest(m, "Business team meeting", recurring=True) == BUSINESS  # the regular one for a recurring appointment
    assert meetings.suggest(m, "Business team meeting", recurring=False) == one_off  # the one-off for a single one
    tasks.create_task(conn, settings, title="Meeting business team", at=NOW, created_by="test", meeting=True)
    assert meetings.suggest(Model(conn), "Business team meeting", recurring=False) is None  # two one-offs with its words


# ---- the day as Today shows it (decisions 489 and 490) ----
def test_the_day_all_day_earlier_now_next_and_later(conn):
    meetings.set_link(conn, "Tom / Me: weekly 1:1", TOM, NOW)
    m = Model(conn)
    day = meetings.day_view(APPTS, m, meetings.links(conn), NOW)
    assert [a.subject for a in day.all_day] == ["Contractors on site"] and meetings.all_day_line(day) == "All day: Contractors on site"
    assert [x.appointment.subject for x in day.earlier] == ["Morning safety huddle", "Pump trial check-in"]
    assert [(x.appointment.title, x.when) for x in day.rest] == [
        ("Updated: Rigging plan review", "now"), ("Business team meeting", "next"), ("Lunch", "later"),
        ("Tom / Me: weekly 1:1", "later"), ("Private appointment", "later"), ("Vendor call: seal supplier", "later")]
    business = day.rest[1]
    assert business.minutes == 20 and meetings.mark_text(business) == "in 20 min" and meetings.mark_text(day.rest[0]) == "now"
    assert business.suggestion == BUSINESS and not business.linked
    assert meetings.context_words(m, business) == "Conf room B · Link to its meeting task?"
    tom = day.rest[3]
    assert tom.target == TOM and tom.agenda == 1 and meetings.context_words(m, tom) == "Tom's office · 1 on Tom Becker's agenda"
    private = day.rest[4]
    assert private.appointment.key == "" and meetings.context_words(m, private) == "" and not private.suggestion
    assert day.lead is day.rest[0] and day.count == 8  # under way, so it's the side panel's line


def test_a_free_one_is_never_the_next_and_a_linked_one_counts_its_agenda(conn):
    meetings.set_link(conn, "Business team meeting", BUSINESS, NOW)
    m = Model(conn)
    noon = datetime(2026, 10, 8, 11, 30)
    day = meetings.day_view(APPTS, m, meetings.links(conn), noon)
    assert [(x.appointment.title, x.when) for x in day.rest[:3]] == [("Business team meeting", "now"), ("Lunch", "later"),
                                                                     ("Tom / Me: weekly 1:1", "next")]
    business = day.rest[0]
    assert business.target == BUSINESS and business.agenda == 4 and meetings.context_words(m, business) == "Conf room B · 4 on its agenda"
    assert meetings.mark_text(day.rest[1]) == ""  # Free: grey, and no mark
    assert day.rest[2].minutes == 120 and meetings.until_text(120) == "in 2 h" and meetings.until_text(125) == "in 2 h 5 min"
    late = meetings.day_view(APPTS, m, {}, datetime(2026, 10, 8, 17))
    assert late.rest == () and late.lead is None and len(late.earlier) == 8


def test_a_linked_task_named_otherwise_is_named(conn):
    meetings.set_link(conn, "Ops weekly", BUSINESS, NOW)
    m = Model(conn)
    day = meetings.day_view([Appointment("Ops weekly", at(11), at(12))], m, meetings.links(conn), NOW)
    assert meetings.context_words(m, day.rest[0]) == "Business team meeting · 4 on its agenda"


@pytest.mark.parametrize("start, end, text", [
    (at(9), at(10), "09:00–10:00"),
    (datetime(2026, 10, 7, 23), at(1), "until 01:00"),
    (at(23), datetime(2026, 10, 9, 1), "from 23:00"),
    (at(22), datetime(2026, 10, 9), "22:00–00:00"),
])
def test_a_meetings_time(start, end, text):
    assert meetings.time_text(Appointment("x", start, end), date(2026, 10, 8)) == text


def test_minutes_until_round_up():
    assert meetings.minutes_until(at(11), datetime(2026, 10, 8, 10, 40, 30)) == 20
    assert meetings.until_text(0) == "in 1 min"


# ---- read at most every 5 minutes (decision 493) ----
def test_the_calendar_is_read_when_due_and_on_f5():
    reads = []
    cal = TodayCalendar(read=lambda day: reads.append(day) or list(APPTS))
    cal.get(NOW)
    cal.get(NOW + timedelta(minutes=4))
    assert len(reads) == 1 and cal.appointments == tuple(APPTS) and cal.read_at == NOW
    cal.get(NOW + timedelta(minutes=5))
    assert len(reads) == 2
    cal.forget()  # F5
    cal.get(NOW + timedelta(minutes=6))
    assert len(reads) == 3
    cal.get(NOW + timedelta(minutes=6), force=True)
    assert len(reads) == 4


def test_a_failed_read_keeps_the_list_and_says_why_once():
    answers: list = [list(APPTS), outlook.CalendarProblem("busy", "busy", "reading", "0x8001010A"),
                     outlook.CalendarProblem("busy", "busy", "reading", "0x8001010A"), outlook.CalendarProblem("refused", "no", "reading", "x")]

    def read(day):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    cal = TodayCalendar(read=read)
    cal.get(NOW)
    cal.get(NOW + timedelta(minutes=5))
    assert cal.kind == "busy" and cal.appointments == tuple(APPTS)  # kept
    assert cal.tell() == "Today's meetings: Outlook is busy (a dialog may be open in it), so the list is the one read at 10:40."
    assert cal.quiet_line(8) == "Outlook is busy (a dialog may be open in it) now; this is the list read at 10:40."
    cal.get(NOW + timedelta(minutes=10))
    assert cal.tell() == ""  # the same problem: said once
    cal.get(NOW + timedelta(minutes=15))
    told = cal.tell()
    assert "refused to give DocRepo the calendar" in told and "Troubleshooting report" in told


def test_outlook_not_open_is_the_quiet_line_only_and_a_new_day_starts_afresh():
    def closed(day):
        raise outlook.CalendarProblem("closed", "Outlook isn't open.", "finding Outlook", "")

    cal = TodayCalendar(read=closed)
    cal.get(NOW)
    assert cal.tell() == "" and cal.quiet_line(0) == "Outlook isn't open, so there are no meetings here. They show once it's open."
    cal = TodayCalendar(read=lambda day: list(APPTS) if day == NOW.date() else [])
    cal.get(NOW)
    cal.get(datetime(2026, 10, 9, 8))
    assert cal.appointments == () and cal.quiet_line(0) == "No meetings on your calendar today."
    cal.read = lambda day: (_ for _ in ()).throw(RuntimeError("surprise"))
    cal.get(datetime(2026, 10, 9, 8, 6))
    assert cal.kind == "failed" and cal.appointments == ()


# ---- reading Outlook (decision 488), with a fake ----
class FakeItem:
    """An appointment that records each field read."""

    def __init__(self, log: list[str], **fields) -> None:
        self._log, self._fields = log, fields

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self._log.append(name)
        if name in self._fields.get("refuse", ()):
            raise RuntimeError("refused")
        return self._fields.get(name)


class FakeItems:
    def __init__(self, calls: list, found: list) -> None:
        object.__setattr__(self, "_calls", calls)
        object.__setattr__(self, "_found", found)

    def __setattr__(self, name, value):
        self._calls.append(("set", name, value))

    def Sort(self, key):  # noqa: N802 - Outlook's name
        self._calls.append(("Sort", key))

    def Restrict(self, text):  # noqa: N802
        self._calls.append(("Restrict", text))
        return FakeFound(self._found, self._calls)


class FakeFound:
    def __init__(self, found: list, calls: list) -> None:
        self._found, self._calls, self._n = found, calls, 0

    def GetFirst(self):  # noqa: N802
        self._calls.append(("GetFirst",))
        self._n = 0
        return self._found[0] if self._found else None

    def GetNext(self):  # noqa: N802
        self._n += 1
        return self._found[self._n] if self._n < len(self._found) else None


class FakeApp:
    def __init__(self, found: list) -> None:
        self.calls: list = []
        app = self

        class Folder:
            @property
            def Items(self):  # noqa: N802
                app.calls.append(("Items",))
                return FakeItems(app.calls, found)

        class Session:
            def GetDefaultFolder(self, n):  # noqa: N802
                app.calls.append(("GetDefaultFolder", n))
                return Folder()

        self.Session = Session()


def item(log, subject, start, end, **more):
    fields = {"Subject": subject, "Start": start, "End": end, "Location": "Room 2", "AllDayEvent": False, "BusyStatus": 2,
              "MeetingStatus": 0, "Sensitivity": 0, "IsRecurring": False}
    return FakeItem(log, **{**fields, **more})


def test_the_read_is_in_the_plans_order_and_reads_only_decision_488s_fields():
    log: list[str] = []
    found = [item(log, "Morning safety huddle", at(7, 30), at(7, 45)),
             item(log, "Cancelled review", at(9), at(10), MeetingStatus=outlook.OL_MEETING_RECEIVED_AND_CANCELED),
             item(log, "Doctor", at(11), at(12), Sensitivity=outlook.OL_PRIVATE, Location="Clinic"),
             item(log, "Yesterday's", datetime(2026, 10, 7, 9), datetime(2026, 10, 7, 10)),  # Restrict misread: dropped
             item(log, "Lunch", at(12), at(13), BusyStatus=FREE, Location=None),
             item(log, "Spring outage", datetime(2026, 10, 8), datetime(2026, 10, 9), AllDayEvent=True, refuse=("Location",))]
    app = FakeApp(found)
    got, seen, refused = outlook.read_calendar(app, date(2026, 10, 8))
    assert [c[0] for c in app.calls[:6]] == ["GetDefaultFolder", "Items", "Sort", "set", "Restrict", "GetFirst"]
    assert app.calls[0] == ("GetDefaultFolder", outlook.OL_FOLDER_CALENDAR) and app.calls[2] == ("Sort", "[Start]")
    assert app.calls[3] == ("set", "IncludeRecurrences", True)
    assert app.calls[4] == ("Restrict", outlook.calendar_filter(date(2026, 10, 8)))
    assert set(log) <= set(outlook.CALENDAR_FIELDS)  # never attendees, the organizer or the body
    assert seen == 6 and refused == {"Location"}
    assert [(a.title, a.location, a.private, a.free, a.all_day) for a in got] == [
        ("Morning safety huddle", "Room 2", False, False, False), ("Private appointment", "", True, False, False),
        ("Lunch", "", False, True, False), ("Spring outage", "", False, False, True)]
    assert log.count("Subject") == 3  # the huddle, lunch and the outage: never the private one's, the cancelled one's or yesterday's
    private_log: list[str] = []
    outlook.appointment_of(item(private_log, "Doctor", at(11), at(12), Sensitivity=outlook.OL_CONFIDENTIAL, Location="Clinic"),
                           date(2026, 10, 8), set())
    assert "Subject" not in private_log and "Location" not in private_log and "Sensitivity" == private_log[0]


def test_the_read_stops_at_its_limit():
    log: list[str] = []
    app = FakeApp([item(log, f"Stand-up {n}", at(9), at(10)) for n in range(5)])
    got, seen, _ = outlook.read_calendar(app, date(2026, 10, 8), limit=3)
    assert seen == 3 and len(got) == 3


def test_restricts_dates_are_windows_own_short_date_and_time(monkeypatch):
    text = outlook.restrict_stamp(datetime(2026, 11, 12, 0, 0))
    assert "2026" in text and "12" in text and ":00:00" not in text  # no seconds
    monkeypatch.setattr(outlook.os, "name", "posix")
    assert outlook.restrict_stamp(datetime(2026, 11, 12, 0, 0)) == "11/12/2026 12:00 AM"
    assert outlook.calendar_filter(date(2026, 11, 12)) == "[Start] < '11/13/2026 12:00 AM' AND [End] > '11/12/2026 12:00 AM'"


def test_problems_are_sorted_by_their_codes():
    class ComError(Exception):
        pass

    assert outlook.problem_kind(ComError(-2147418111, "Call was rejected by callee.", None, None)) == "busy"  # 0x80010001
    assert outlook.problem_kind(ComError(-2147352567, "Exception occurred.", (0, "Outlook", "x", None, 0, -2147467260), None)) == "refused"
    assert outlook.problem_kind(ComError(-2147467259, "Unspecified error", None, None)) == "failed"


def test_reading_never_starts_outlook(monkeypatch):
    client = pytest.importorskip("win32com.client")
    started = []
    monkeypatch.setattr(client, "GetActiveObject", lambda name: (_ for _ in ()).throw(OSError(-2147221021, "Operation unavailable")))
    monkeypatch.setattr(client, "Dispatch", lambda name: started.append(name))
    monkeypatch.setattr(outlook, "outlook_window_open", lambda: False)
    before = list(outlook.PROBLEMS)
    with pytest.raises(outlook.CalendarProblem) as caught:
        REAL_READ(date(2026, 10, 8))
    assert caught.value.kind == "closed" and started == [] and list(outlook.PROBLEMS) == before  # not kept as a problem
    assert outlook.CALENDAR_READS[-1].problem == "closed"


def test_a_running_outlook_is_read_and_a_busy_one_is_kept_once(monkeypatch):
    client = pytest.importorskip("win32com.client")
    log: list[str] = []
    app = FakeApp([item(log, "Business team meeting", at(11), at(12))])
    monkeypatch.setattr(client, "GetActiveObject", lambda name: app)
    found = REAL_READ(date(2026, 10, 8))
    assert [a.subject for a in found] == ["Business team meeting"]
    read = outlook.CALENDAR_READS[-1]
    assert (read.items, read.kept, read.problem) == (1, 1, "") and read.filter == outlook.calendar_filter(date(2026, 10, 8))

    class Busy:
        @property
        def Session(self):  # noqa: N802
            raise OSError(-2147418111, "Call was rejected by callee.")

    monkeypatch.setattr(client, "GetActiveObject", lambda name: Busy())
    outlook.PROBLEMS.clear()
    for _ in range(2):
        with pytest.raises(outlook.CalendarProblem) as caught:
            REAL_READ(date(2026, 10, 8))
        assert caught.value.kind == "busy"
    assert len(outlook.PROBLEMS) == 1 and "today's calendar" in outlook.PROBLEMS[0].step  # kept once


# ---- the upgrade (schema 26) ----
def test_the_version_25_root_comes_up_with_no_links_and_its_t_mails_kept(tmp_path):
    root = tmp_path / "DocRepoData-v25"
    with zipfile.ZipFile(ROOTS / "v25.zip") as z:
        z.extractall(root)
    conn = db.connect(SafeFS([root]), root)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 26
        assert conn.execute("SELECT count(*) FROM meeting_links").fetchone()[0] == 0
        assert [r[0] for r in conn.execute("SELECT kind FROM t_mails ORDER BY id")] == ["new", "ask"]
        meetings.set_link(conn, "Business team meeting", BUSINESS, NOW)
        assert list(meetings.links(conn)) == ["business team meeting"]
    finally:
        conn.close()


def test_the_sample_loads_with_the_link_table_empty():
    conn = db.connect_memory()
    load_sample(conn)
    assert meetings.links(conn) == {}
