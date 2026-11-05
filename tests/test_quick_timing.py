"""Thread A's fields and ties as ** lines (release 5.62, decisions 293 to 300): read, refused and saved."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from docrepo import captures, items, tasks, templates  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, Tie  # noqa: E402
from docrepo.save import CaptureDraft, FileRow, NewTaskFields, item_names, save_capture  # noqa: E402
from docrepo.templates import Library, RowTiming  # noqa: E402
from docrepo.timing import RowTie  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

TODAY = date(2026, 10, 8)
AT = datetime(2026, 10, 8, 9, 30)
SETTINGS = Settings(me="P001")
TOM, PRIYA = "P003", "P002"


def task(conn, title="Blank one", **fields) -> str:
    return tasks.create_task(conn, SETTINGS, title=title, at=AT, created_by="Browse tool", **fields)


@pytest.fixture
def world(sample_root):
    """The sample data, an outage with dates, and a task with none. Fridays and weekends as in Settings' default."""
    conn, root, fs = sample_root
    return conn, root, fs, task(conn, "Line 2 outage", start="2026-11-09", due="2026-11-11"), task(conn)


def names_in(conn, week=None) -> items.Names:
    names = item_names(Model(conn), SETTINGS)
    if week:
        names.week = week
    return names


def read(conn, text, **kw) -> list[items.Item]:
    return items.read(text, names_in(conn), TODAY, **{"home": True, **kw}).items


def card(conn, text, **kw) -> items.Item:
    return read(conn, text, **kw)[-1]


def save(world, draft):
    conn, root, fs, *_ = world
    return save_capture(conn, root, fs, SETTINGS, draft, AT), Model(conn)


# ---- reading each form ----
@pytest.mark.parametrize("line, label, shown, changes", [
    ("**duration, 5.", "Duration", "5 days", {"duration": 5}),
    ("**duration, 5 days.", "Duration", "5 days", {"duration": 5}),
    ("**Duration, 1 day.", "Duration", "1 day", {"duration": 1}),
    ("**duration, 5 workdays.", "Duration", "5 days", {"duration": 5}),
    ("**duration, 2 weeks.", "Duration", "2 weeks (10 days)", {"weeks": 2}),
    ("**weekends, yes.", "Runs through weekends", "Yes", {"calendar_days": True}),
    ("**runs through weekends, no.", "Runs through weekends", "No", {"calendar_days": False}),
    ("**hours, 6 h a day.", "Assignee hours", "6 h a day", {"assignee_per_day": 6.0}),
    ("**hours, 6 a day.", "Assignee hours", "6 h a day", {"assignee_per_day": 6.0}),
    ("**assignee hours, 6 hours per day.", "Assignee hours", "6 h a day", {"assignee_per_day": 6.0}),
    ("**hours, 3 h a week.", "Assignee hours", "3 h a week", {"assignee_per_week": 3.0}),
    ("**hours, 2.5 a week.", "Assignee hours", "2.5 h a week", {"assignee_per_week": 2.5}),
    ("**lead hours, 3 h a week.", "Lead hours", "3 h a week", {"lead_per_week": 3.0}),
    ("**lead hours, 4 a day.", "Lead hours", "4 h a day", {"lead_per_day": 4.0}),
    ("**hours, 12.", "Assignee hours", "12", {"assignee_hours": 12.0}),
    ("**hours, 12 hours.", "Assignee hours", "12", {"assignee_hours": 12.0}),
    ("**involvement, Tom 25%.", "Involvement", "Tom Becker 25%", {"involvement": {TOM: 25}}),
    ("**involvement, Tom 25%, Priya 50%.", "Involvement", "Tom Becker 25%, Priya Shah 50%", {"involvement": {TOM: 25, PRIYA: 50}}),
    ("**involvement, Tom 25% and Priya 50%.", "Involvement", "Tom Becker 25%, Priya Shah 50%", {"involvement": {TOM: 25, PRIYA: 50}}),
    ("**involvement, @Tom 0%.", "Involvement", "Tom Becker 0%", {"involvement": {TOM: 0}}),
])
def test_each_new_form_reads(world, line, label, shown, changes):
    it = card(world[0], line)
    assert (it.label, it.value.shown, it.title, dict(it.value.changes), it.problem, it.on) == (label, shown, shown, changes, "", True)


@pytest.mark.parametrize("line, problem", [
    ("**duration, soon.", "Say how many days, such as 5"),
    ("**duration, 0.", "Say how many days, such as 5"),
    ("**duration, 2.5 days.", "Say how many days, such as 5"),
    ("**duration,", "Nothing after the comma"),
    ("**weekends, maybe.", "Say yes or no"),
    ("**hours, 3 h a month.", "Give a total, or hours a day or a week, such as 6 h a day"),
    ("**hours, 0 a day.", "Give a number above zero"),
    ("**hours, plenty.", "No hours: add a number, such as 12"),
    ("**involvement, Tom.", "Say who and how much, such as Tom 25%"),
    ("**involvement, Tom 25.5%.", "Say who and how much, such as Tom 25%"),
    ("**involvement, Tom 120%.", "Involvement is a whole number from 0 to 100"),
    ("**involvement, Nobody Known 25%.", "Nobody Known isn't on the people list"),
    ("**involvement,", "Nothing after the comma"),
])
def test_what_cant_be_read_says_why(world, line, problem):
    it = card(world[0], line)
    assert (it.problem, it.on) == (problem, False)


@pytest.mark.parametrize("sentence, point, amount, unit, direction, shown", [
    ("3 workdays after #Line 2 outage ends", "end", 3, "workdays", "after", "3 workdays after Line 2 outage ends"),
    ("1 workday before #Line 2 outage starts", "start", 1, "workdays", "before", "1 workday before Line 2 outage starts"),
    ("the day #Line 2 outage starts", "start", 0, "workdays", "after", "The day Line 2 outage starts"),
    ("The day #Line 2 outage ends", "end", 0, "workdays", "after", "The day Line 2 outage ends"),
    ("2 weeks before #Line 2 outage ends", "end", 2, "weeks", "before", "2 weeks before Line 2 outage ends"),
    ("1 week after #Line 2 outage starts", "start", 1, "weeks", "after", "1 week after Line 2 outage starts"),
    ("2 days after #Line 2 outage ends", "end", 2, "workdays", "after", "2 workdays after Line 2 outage ends"),
    ("2 days after #Line 2 outage", "end", 2, "workdays", "after", "2 workdays after Line 2 outage ends"),  # after: after it ends
    ("2 weeks before #Line 2 outage", "start", 2, "weeks", "before", "2 weeks before Line 2 outage starts"),  # before: before it starts
])
@pytest.mark.parametrize("name, key", [("start", "start"), ("due", "due"), ("start date", "start")])
def test_a_tie_reads_in_edit_tasks_words(world, name, key, sentence, point, amount, unit, direction, shown):
    conn, *_, outage, blank = world
    it = card(conn, f"#{blank} **{name}, {sentence}.")
    assert (it.value.shown, it.problem, it.on) == (shown, "", True)
    assert it.value.changes == {"ties": {key: Tie(outage, point, amount, unit, direction)}}


def test_a_tie_can_count_from_a_key_date(world):
    conn, *_, outage, blank = world
    tasks.add_key_dates(conn, outage, [tasks.KeyDateRow("2026-11-02", "2026-11-05", "Trial window", False, False)], at=AT, via="Browse tool")
    kd = Model(conn).key_dates_of(outage)[0]
    it = card(conn, "**start, 2 weeks before #Line 2 outage: trial window starts.", own=blank)
    assert it.value.changes == {"ties": {"start": Tie(outage, "start", 2, "weeks", "before", kd.id)}}
    assert it.value.shown == "2 weeks before Line 2 outage: Trial window starts"
    assert card(conn, "**start, 1 workday after #Line 2 outage: nothing ends.", own=blank).problem == "No key date called nothing on Line 2 outage"


def test_a_key_dates_description_may_end_in_a_verb(world):
    conn, *_, outage, blank = world
    tasks.add_key_dates(conn, outage, [tasks.KeyDateRow("2026-11-02", "2026-11-05", "Trial ends", False, False)], at=AT, via="Browse tool")
    kd = Model(conn).key_dates_of(outage)[0]
    it = card(conn, "**start, 1 workday after #Line 2 outage: trial ends.", own=blank)
    assert it.value.changes == {"ties": {"start": Tie(outage, "end", 1, "workdays", "after", kd.id)}}


@pytest.mark.parametrize("sentence, problem", [
    ("3 workdays after Line 2 outage ends", "Name the task with #, such as 3 workdays after #Rigging plan ends"),
    ("the day Line 2 outage starts", "Name the task with #, such as 3 workdays after #Rigging plan ends"),
    ("3 workdays after #Prep ends", "No task called Prep"),
    ("3 workdays after #Prep: a window starts", "No task called Prep"),
    ("the day #Line 2 outage", "Say whether it starts or ends"),
    ("3 workdays after #Line 2 outage sometime", "Say whether it starts or ends"),
])
def test_a_tie_that_cant_be_read_says_why(world, sentence, problem):
    conn, *_, outage, blank = world
    assert card(conn, f"**start, {sentence}.", own=blank).problem == problem
    assert card(conn, f"**due, {sentence}.", own=blank).problem == problem


# ---- what stays as it was ----
@pytest.mark.parametrize("line, shown", [
    ("**start, 5 Nov.", "2026-11-05"),
    ("**start, the day after tomorrow.", "2026-10-10"),
    ("**due, the day after tomorrow.", "2026-10-10"),
    ("**due, 3 weeks from today.", None),
])
def test_a_date_still_reads_as_a_date(world, line, shown):
    it = card(world[0], line)
    assert "ties" not in it.value.changes
    assert shown is None or it.value.shown == shown


def test_a_hash_in_a_dates_sentence_still_says_where_it_goes(world):
    conn, *_, outage, blank = world
    it = card(conn, f"**start, 5 Nov #{outage}.", own=blank)
    assert it.where == [items.Where("task", outage)]


def test_a_title_with_a_period_doesnt_end_the_sentence(world):
    conn, *_, outage, blank = world
    other = task(conn, "Ver. Two outage", start="2026-11-09", due="2026-11-11")
    it = read(conn, "**start, 3 workdays after #Ver. Two outage ends. Then the rest.", own=blank)[-1]
    assert it.value.changes == {"ties": {"start": Tie(other, "end", 3, "workdays", "after")}}
    assert it.value.shown == "3 workdays after Ver. Two outage ends"
    assert card(conn, "**parent, #Ver. Two outage.", own=blank).value.changes == {"parents": [other]}  # the same sentence rule


# ---- where a tie goes (decision 294) ----
def test_a_ties_hash_isnt_where_it_goes(world):
    conn, *_, outage, blank = world
    assert card(conn, "**start, 3 workdays after #Line 2 outage ends.", own=blank).where == [items.Where("home")]
    assert card(conn, f"#{blank} **start, 3 workdays after #Line 2 outage ends.").where == [items.Where("task", blank)]
    under = read(conn, f"#{blank}\n**due, 1 week after #Line 2 outage ends.")
    assert under[-1].where == [items.Where("task", blank)]


def test_a_ties_hash_files_nothing(world):
    conn, *_, outage, blank = world
    made, param = read(conn, "@Tom check the pump **start, 3 workdays after #Line 2 outage ends.")
    assert made.kind == "task" and made.title == "Check the pump" and made.tasks == []
    assert made.where == [items.Where("home")]
    assert param.where == [items.Where("item", made.key)]
    assert not [x for x in read(conn, "**start, 3 workdays after #Line 2 outage ends.", own=blank) if x.kind != "param"]


# ---- what a task already has (decisions 295 and 297 to 299) ----
def test_a_filled_date_stays_and_says_where_to_tie_it(world):
    conn, *_, outage, blank = world
    other = task(conn, "Dated one", start="2026-11-16")
    it = card(conn, f"#{other} **start, 3 workdays after #Line 2 outage ends.")
    assert (it.problem, it.on) == ("Start is already 2026-11-16: tie it in Edit task", False)


def test_a_tied_date_waiting_for_its_source_counts_as_filled(world):
    conn, *_, outage, blank = world
    undated = task(conn, "Undated source")
    waiting = task(conn, "Waiting one")
    tasks.update_task(conn, SETTINGS, waiting, at=AT, via="Browse tool", ties={"start": Tie(undated, "end", 1)})
    assert not Model(conn).tasks[waiting].start
    assert card(conn, f"#{waiting} **start, 5 Nov.").problem == "Start is already tied: change it with Update or Edit task"
    assert card(conn, f"#{waiting} **start, 1 workday after #Line 2 outage ends.").problem == "Start is already tied: tie it in Edit task"
    assert card(conn, f"#{waiting} **due, 5 Nov.").problem == ""


@pytest.mark.parametrize("fields, line, problem", [
    ({"duration": 5}, "**duration, 3.", "Duration is already 5 days: change it with Update or Edit task"),
    ({"assignee_hours": 12.0}, "**hours, 6 h a day.", "Assignee hours is already 12: change it with Update or Edit task"),
    ({"assignee_per_day": 6.0}, "**hours, 12.", "Assignee hours is already 6 h a day: change it with Update or Edit task"),
    ({"lead_per_week": 3.0}, "**lead hours, 1 a day.", "Lead hours is already 3 h a week: change it with Update or Edit task"),
    ({"start": "2026-11-16", "due": "2026-11-20"}, "**duration, 3.", "Start and Due already set its length: change it in Edit task"),
    ({"start": "2026-11-16", "duration": 5}, "**weekends, yes.", "That would move its dates: change it in Edit task"),
    ({"recurrence": "Weekly"}, "**duration, 3.", "A routine task has no Duration or rate: its hours are for each time"),
    ({"recurrence": "Weekly"}, "**hours, 3 a week.", "A routine task has no Duration or rate: its hours are for each time"),
    ({"recurrence": "Weekly"}, "**weekends, yes.", "A routine task has no Duration or rate: its hours are for each time"),
    ({"recurrence": "Weekly"}, "**start, 1 workday after #Line 2 outage ends.", "A routine task has no one date to tie"),
])
def test_what_a_task_already_has_stops_it(world, fields, line, problem):
    conn = world[0]
    t = task(conn, "Dated one", **fields)
    it = card(conn, f"#{t} {line}")
    assert (it.problem, it.on) == (problem, False)


@pytest.mark.parametrize("fields, line", [
    ({"start": "2026-11-16"}, "**duration, 3."),  # it works out the Due
    ({"due": "2026-11-20"}, "**duration, 3."),
    ({"start": "2026-11-16", "due": "2026-11-20"}, "**weekends, yes."),  # no Duration holds them
    ({"recurrence": "Weekly"}, "**hours, 3."),  # a routine task's hours are for each time
    ({"due": "2026-11-20"}, "**start, 3 workdays after #Line 2 outage ends."),
])
def test_what_fills_a_gap_goes_ahead(world, fields, line):
    conn = world[0]
    t = task(conn, "Dated one", **fields)
    assert card(conn, f"#{t} {line}").problem == ""


def test_a_tie_that_cant_take_says_what_edit_task_says(world):
    conn, *_, outage, blank = world
    routine = task(conn, "Routine one", recurrence="Weekly")
    assert card(conn, f"#{blank} **start, 1 workday after #{blank} ends.").problem.startswith("A task's date can't be tied to its own dates")
    assert card(conn, f"#{blank} **start, 1 workday after #{routine} ends.").problem.startswith("Routine one repeats")
    follower = task(conn, "Follower")
    tasks.update_task(conn, SETTINGS, follower, at=AT, via="Browse tool", ties={"start": Tie(blank, "end", 1)})
    assert card(conn, f"#{blank} **start, 1 workday after #{follower} ends.").problem.startswith("That would go in a circle")


def test_a_share_needs_its_person_on_the_task(world):
    conn, *_, outage, blank = world
    assert card(conn, f"#{blank} **involvement, Tom 25%.").problem == "Tom Becker isn't on this task: add them first"
    assert card(conn, "@Tom check the pump **involvement, Tom 25%.").problem == ""
    assert card(conn, "@L.Tom check the pump **involvement, Tom 25%.").problem == ""
    assert card(conn, "@Priya check the pump **involvement, Tom 25%.").problem == "Tom Becker isn't on this task: add them first"
    assert card(conn, f"#{blank} **assignee, Tom. **involvement, Tom 25%.").problem == ""
    assert read(conn, f"#{blank} **involvement, Tom 25%. **lead, Tom.")[0].problem == ""  # wherever on the line it's written
    assert card(conn, "**involvement, Tom 25%.", new_task=True).problem == ""  # a new task's form isn't known here: Save checks


def test_a_share_of_their_own_stays(world):
    conn = world[0]
    t = task(conn, "Shared one", assignees=[TOM, PRIYA], involvement={("assignee", TOM): 50})
    assert card(conn, f"#{t} **involvement, Tom 25%.").problem == "Tom Becker's involvement is already 50%: change it in Edit task"
    assert card(conn, f"#{t} **involvement, Tom 50%.").problem == ""  # it says the same
    assert card(conn, f"#{t} **involvement, Priya 25%.").problem == ""


# ---- what the cards on one task say together ----
@pytest.mark.parametrize("line", [
    "@Tom check the pump **start, 16 Nov. **due, 20 Nov. **duration, 3.",
    "@Tom check the pump **duration, 3. **start, 16 Nov. **due, 20 Nov.",
    "@Tom check the pump, 16 to 20 Nov **duration, 3.",
    "@Tom check the pump **start, 1 workday after #Line 2 outage ends. **due, 2 weeks after #Line 2 outage ends. **duration, 3.",
])
def test_all_three_cant_go_together(world, line):
    its = read(world[0], line)
    duration = next(x for x in its if x.label == "Duration")
    assert (duration.problem, duration.on) == ("Start and Due already set its length: change it in Edit task", False)
    assert [x.problem for x in its if x.label in ("Start", "Due")] in ([], ["", ""])


def test_an_unticked_card_doesnt_count(world):
    conn = world[0]
    its = read(conn, "@Tom check the pump **start, 16 Nov. **due, 20 Nov. **duration, 3.")
    due = next(x for x in its if x.label == "Due")
    again = items.read("@Tom check the pump **start, 16 Nov. **due, 20 Nov. **duration, 3.", names_in(conn), TODAY, home=True, overrides={due.key: {"off": True}}).items
    assert next(x for x in again if x.label == "Duration").problem == ""


def test_on_an_existing_task_a_date_on_the_line_counts_too(world):
    conn = world[0]
    t = task(conn, "Started one", start="2026-11-16")
    assert read(conn, f"#{t} **due, 20 Nov. **duration, 3.")[-1].problem == "Start and Due already set its length: change it in Edit task"


def test_a_routine_task_on_the_line_stops_a_duration(world):
    conn = world[0]
    assert read(conn, "@Tom check the pump **recurrence, weekly. **duration, 3.")[-1].problem == "A routine task has no Duration or rate: its hours are for each time"
    assert read(conn, "@Tom check the pump every week **hours, 3 a week.")[-1].problem == "A routine task has no Duration or rate: its hours are for each time"


def test_weeks_count_by_the_tasks_calendar(world):
    conn, *_, outage, blank = world
    assert card(conn, f"#{blank} **duration, 2 weeks.").value.shown == "2 weeks (10 days)"
    assert read(conn, f"#{blank} **duration, 2 weeks. **weekends, yes.")[0].value.shown == "2 weeks (14 days)"
    assert read(conn, f"#{blank} **weekends, yes. **duration, 2 weeks.")[-1].value.shown == "2 weeks (14 days)"
    every = task(conn, "Every day", calendar_days=True)
    assert card(conn, f"#{every} **duration, 1 week.").value.shown == "1 week (7 days)"
    assert items.read(f"#{blank} **duration, 2 weeks.", names_in(conn, week=4), TODAY, home=True).items[-1].value.shown == "2 weeks (8 days)"


# ---- saving ----
def test_your_example_makes_the_whole_task(world):
    conn, root, fs, outage, blank = world
    r, m = save(world, CaptureDraft(content="@Tom check the pump **duration, 5. **hours, 6 h a day. **involvement, Tom 25%. **start, 1 workday after #Line 2 outage ends.", task=blank))
    t = next(x for x in m.tasks.values() if x.title == "Check the pump")
    assert t.ties == {"start": Tie(outage, "end", 1, "workdays", "after")}
    assert (t.start, t.due, t.duration, t.assignee_per_day, t.assignee_hours) == ("2026-11-12", "2026-11-18", 5, 6.0, 30.0)
    assert t.involvement == {("assignee", TOM): 25}
    parents = [x["parent"] for x in conn.execute("SELECT parent FROM task_parents WHERE child = ?", (t.id,))]
    assert parents == [blank] and outage not in parents  # the # names its source, and files nothing
    assert r.made.get("param") == 4 and r.unused == 0


def test_the_notes_keep_the_ties_hash_with_its_id(world):
    conn, root, fs, outage, blank = world
    # A link keeps the note a capture (release 5.69), whose capture.md keeps each # with its ID.
    r, m = save(world, CaptureDraft(content="Plan.\n**start, 3 workdays after #Line 2 outage ends.", task=blank, files=[FileRow("Spec sheet", "https://example.com/spec", "the spec")]))
    assert f"#[Line 2 outage]({outage})" in captures.read_content(root, m.captures[r.capture_id]).replace("\r\n", "\n")
    assert m.tasks[blank].start == "2026-11-16"


def test_a_tied_task_follows_its_source_after_saving(world):
    conn, root, fs, outage, blank = world
    save(world, CaptureDraft(content="**start, 3 workdays after #Line 2 outage ends. **duration, 2.", task=blank))
    assert (Model(conn).tasks[blank].start, Model(conn).tasks[blank].due) == ("2026-11-16", "2026-11-17")
    tasks.update_task(conn, SETTINGS, outage, at=AT, via="Browse tool", due="2026-11-18")
    assert (Model(conn).tasks[blank].start, Model(conn).tasks[blank].due) == ("2026-11-23", "2026-11-24")


def test_a_tie_to_a_task_with_no_date_waits(world):
    conn, root, fs, outage, blank = world
    undated = task(conn, "Undated source")
    r, m = save(world, CaptureDraft(content=f"**start, 3 workdays after #{undated} ends.", task=blank))
    t = m.tasks[blank]
    assert not t.start and t.ties["start"].source == undated and r.unused == 0
    tasks.update_task(conn, SETTINGS, undated, at=AT, via="Browse tool", due="2026-11-11")
    assert Model(conn).tasks[blank].start == "2026-11-16"


def test_both_dates_tied_take_their_length_from_them(world):
    conn, root, fs, outage, blank = world
    r, m = save(world, CaptureDraft(content="**start, the day #Line 2 outage ends. **due, 1 week after #Line 2 outage ends.", task=blank))
    t = m.tasks[blank]
    assert (t.start, t.due, t.duration) == ("2026-11-11", "2026-11-18", None) and set(t.ties) == {"start", "due"}


def test_a_second_tie_keeps_the_first(world):
    conn, root, fs, outage, blank = world
    save(world, CaptureDraft(content="**start, the day #Line 2 outage ends.", task=blank))
    save(world, CaptureDraft(content="**due, 1 week after #Line 2 outage ends.", task=blank))
    assert set(Model(conn).tasks[blank].ties) == {"start", "due"}


def test_a_key_date_as_the_source_saves(world):
    conn, root, fs, outage, blank = world
    tasks.add_key_dates(conn, outage, [tasks.KeyDateRow("2026-11-02", "2026-11-05", "Trial window", False, False)], at=AT, via="Browse tool")
    save(world, CaptureDraft(content="**start, 1 workday after #Line 2 outage: trial window ends.", task=blank))
    t = Model(conn).tasks[blank]
    assert t.start == "2026-11-06" and t.ties["start"].key_date == Model(conn).key_dates_of(outage)[0].id


def test_a_filled_field_stays_on_save_and_counts_as_unused(world):
    conn, root, fs, outage, blank = world
    t = task(conn, "Dated one", start="2026-11-16", due="2026-11-20")
    r, m = save(world, CaptureDraft(content="Plan.\n**duration, 3.\n**start, 1 workday after #Line 2 outage ends.", task=t))
    x = m.tasks[t]
    assert (x.start, x.due, x.duration, x.ties) == ("2026-11-16", "2026-11-20", None, {}) and r.unused == 2


def test_a_duration_on_one_date_works_out_the_other(world):
    conn = world[0]
    t = task(conn, "Started one", start="2026-11-16")
    r, m = save(world, CaptureDraft(content="**duration, 5.", task=t))
    assert (m.tasks[t].due, m.tasks[t].duration, r.made) == ("2026-11-20", 5, {"param": 1})


def test_weeks_and_weekends_save_in_either_order(world):
    conn, root, fs, outage, blank = world
    other = task(conn, "Other one", start="2026-11-16")
    save(world, CaptureDraft(content="**duration, 2 weeks. **weekends, yes.", task=blank))
    save(world, CaptureDraft(content="**weekends, yes. **duration, 2 weeks.", task=other))
    m = Model(conn)
    assert (m.tasks[blank].duration, m.tasks[blank].calendar_days) == (14, True)
    assert (m.tasks[other].duration, m.tasks[other].due) == (14, "2026-11-29")


def test_weeks_save_by_the_workdays_in_settings(world):
    conn, root, fs, outage, blank = world
    four = Settings(me="P001", workdays=["Mon", "Tue", "Wed", "Thu"])
    save_capture(conn, root, fs, four, CaptureDraft(content="**duration, 2 weeks.", task=blank), AT)
    assert Model(conn).tasks[blank].duration == 8


def test_a_rate_saves_and_the_total_follows(world):
    conn = world[0]
    t = task(conn, "Rated one", start="2026-11-16", due="2026-11-20")
    r, m = save(world, CaptureDraft(content="**hours, 6 h a day. **lead hours, 3 h a week.", task=t))
    x = m.tasks[t]
    assert (x.assignee_per_day, x.assignee_hours, x.lead_per_week, x.lead_hours) == (6.0, 30.0, 3.0, 3.0)


def test_a_share_saves_on_each_role_they_hold(world):
    conn = world[0]
    t = task(conn, "Shared one", leads=[TOM], assignees=[TOM, PRIYA])
    r, m = save(world, CaptureDraft(content="**involvement, Tom 25%, Priya 50%.", task=t))
    assert m.tasks[t].involvement == {("lead", TOM): 25, ("assignee", TOM): 25, ("assignee", PRIYA): 50}
    log = [x["field"] for x in conn.execute("SELECT field FROM status_log WHERE task = ? AND via = 'Capture window'", (t,))]  # no capture (5.69)
    assert sorted(log) == ["Priya Shah's involvement", "Tom Becker's involvement", "Tom Becker's involvement"]


def test_a_share_written_before_its_person_still_saves(world):
    conn, root, fs, outage, blank = world
    r, m = save(world, CaptureDraft(content="**involvement, Tom 25%. **assignee, Tom.", task=blank))
    assert m.tasks[blank].assignees == [TOM] and m.tasks[blank].involvement == {("assignee", TOM): 25} and r.unused == 0


def test_a_new_tasks_form_gets_the_lines_value(world):
    """Decision 200: nothing is being edited on a task this capture is making, so the line's value is used, even over the form."""
    r, m = save(world, CaptureDraft(content="Plan.\n**duration, 3.\n**start, 1 workday after #Line 2 outage ends.", types={"new_task"},
                                    new_task=NewTaskFields(title="New one", start="2026-12-01", due="2026-12-10")))
    t = m.tasks[r.created_task]
    assert (t.start, t.due, t.duration) == ("2026-11-12", "2026-11-16", 3) and r.unused == 0


def test_what_save_finds_on_a_new_task_it_doesnt_use(world):
    """A new task's form isn't known when it's read: Save checks, and says so."""
    r, m = save(world, CaptureDraft(content="Plan.\n**duration, 3.\n**involvement, Tom 25%.", types={"new_task"},
                                    new_task=NewTaskFields(title="New one", recurrence="Weekly")))
    t = m.tasks[r.created_task]
    assert t.duration is None and t.involvement == {} and r.unused == 2
    assert "2 lines weren't used" in r.message


def test_a_tie_of_its_own_stays(world):
    conn, root, fs, outage, blank = world
    t = task(conn, "Tied one")
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", ties={"start": Tie(outage, "end", 1)})
    r, m = save(world, CaptureDraft(content="**start, 2 weeks after #Line 2 outage ends.", task=t))
    assert m.tasks[t].ties["start"].amount == 1 and r.unused == 1


def test_on_a_tree_from_a_template_a_rows_tie_stays_and_a_gap_fills(world):
    conn, root, fs, outage, blank = world
    top = templates.new_template(conn, "Product trial", AT)
    add = lambda title, **v: templates.add_row(conn, SETTINGS, top, {"title": title, "inherit_labels": True, **v}, AT)[0]  # noqa: E731
    window, report, loose = add("Trial window", duration=5), add("Trial report", duration=5), add("Loose end", duration=2)
    template = Library(conn).rows[top].template
    plan = {window: RowTiming({}, 5), report: RowTiming({"start": RowTie(None, "end", 1, direction="after")}, 5), loose: RowTiming({}, 2)}
    templates.apply_timing(conn, SETTINGS, template, window, plan, AT)
    made = templates.make_tasks(conn, SETTINGS, top, "Trial 1", None, {window: templates.Choice(start="2026-11-16")}, AT)
    lib = Library(conn)
    copy = {lib.copies[x].row: x for x in made}
    tied, free = copy[report], copy[loose]
    r, m = save(world, CaptureDraft(content="**start, 1 week after #Line 2 outage ends.", task=tied))
    assert m.tasks[tied].ties["start"].source == copy[window] and r.unused == 1  # the row's tie stays
    r, m = save(world, CaptureDraft(content="**start, 1 week after #Line 2 outage ends.", task=free))
    assert m.tasks[free].ties["start"].source == outage and m.tasks[free].start == "2026-11-18" and r.unused == 0
    assert (m.tasks[free].due, m.tasks[free].duration) == ("2026-11-19", 2)
    tasks.update_task(conn, SETTINGS, copy[window], at=AT, via="Browse tool", start="2026-11-23")
    assert Model(conn).tasks[tied].start == "2026-11-30"  # and the tree still moves by its row's tie


def test_the_corporate_tests_numbers(sample_root):
    """The dates and counts in release-5-62-test.md's steps, as the same calls."""
    conn, root, fs = sample_root
    world = (conn, root, fs)
    r, m = save(world, CaptureDraft(content="Plan.", types={"new_task"}, new_task=NewTaskFields(title="Line 2 outage", start="2027-03-01", due="2027-03-03")))
    outage = r.created_task
    r, m = save(world, CaptureDraft(content="@Tom check the pump **duration, 5. **hours, 6 h a day. **involvement, Tom 25%. **start, 1 workday after #Line 2 outage ends."))
    assert r.made == {"task": 1, "param": 4}
    pump = next(x for x in m.tasks.values() if x.title == "Check the pump")
    assert (pump.start, pump.due, pump.duration, pump.assignee_hours) == ("2027-03-04", "2027-03-10", 5, 30.0)
    assert [x.id for x in m.tied_to(outage)] == [pump.id]
    assert "Quick tasks" in [m.tasks[x["parent"]].title for x in conn.execute("SELECT parent FROM task_parents WHERE child = ?", (pump.id,))]
    tasks.update_task(conn, SETTINGS, outage, at=AT, via="Browse tool", due="2027-03-10")
    pump = Model(conn).tasks[pump.id]
    assert (pump.start, pump.due) == ("2027-03-11", "2027-03-17")
    save(world, CaptureDraft(content="#Line 2 outage **key date, trial window 15 to 19 Mar 2027."))
    r, m = save(world, CaptureDraft(content="@Priya write up the trial **start, 2 weeks before #Line 2 outage: trial window starts. **duration, 2 weeks."))
    trial = next(x for x in m.tasks.values() if x.title == "Write up the trial")
    assert (trial.start, trial.due, trial.duration) == ("2027-03-01", "2027-03-12", 10)
    assert card(conn, "@Priya write up the trial **start, 2 weeks before #Line 2 outage: trial window starts.").value.shown == "2 weeks before Line 2 outage: Trial window starts"
    all_three = "@Tom plan it **start, 1 Mar 2027. **due, 5 Mar 2027. **duration, 3."
    assert read(conn, all_three)[-1].problem == "Start and Due already set its length: change it in Edit task"
    report = next(x for x in Model(conn).tasks.values() if x.title == "Monthly safety report")
    assert card(conn, f"#{report.id} **duration, 3.").problem == "A routine task has no Duration or rate: its hours are for each time"
    r, m = save(world, CaptureDraft(content="@Tom run it **duration, 2 weeks. **weekends, yes. **start, 1 Mar 2027."))
    run = next(x for x in m.tasks.values() if x.title == "Run it")
    assert (run.duration, run.calendar_days, run.start, run.due) == (14, True, "2027-03-01", "2027-03-14")
    r, m = save(world, CaptureDraft(content="**involvement, Tom 25%. **assignee, Tom.", task=outage))
    assert m.tasks[outage].involvement == {("assignee", TOM): 25}
    rigging = next(x for x in Model(conn).tasks.values() if x.title == "Rigging plan")
    assert (rigging.start, rigging.due) == ("2026-10-05", "2026-10-14")  # steps 10 and 11's message
    assert card(conn, f"#{rigging.id} **start, 3 workdays after #Line 2 outage ends.").problem == "Start is already 2026-10-05: tie it in Edit task"


# ---- the capture window ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, world):
    conn, root, fs, *_ = world
    ctx = AppContext(conn, root, fs, SETTINGS, notify=lambda t, m: None, now=lambda: AT)
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()


def test_the_cards_show_what_was_read(window, world):
    window.set_task(world[4])
    window.content.setPlainText("**duration, 2 weeks.\n**start, 2 days after #Line 2 outage.\n**involvement, Tom 25%.\n**hours, 6 a day.")
    window.read_items()
    cards = window.item_cards.cards
    assert [c.tick.text() for c in cards] == ["Duration", "Start", "Involvement", "Assignee hours"]
    assert [c.tick.isChecked() for c in cards] == [True, True, False, True]
    assert [cards[i].title.text() for i in (0, 1, 3)] == ["2 weeks (10 days)", "2 workdays after Line 2 outage ends", "6 h a day"]
    assert "on this task: add them first" in " ".join(x.text() for x in cards[2].findChildren(QLabel))
    assert cards[1].findChild(QLabel, "itemValue").text() == "2 workdays after Line 2 outage ends" and cards[1].title.isHidden()  # it keeps its last word
    assert cards[0].findChild(QLabel, "itemValue") is None and not cards[0].title.isHidden()


def test_saving_from_the_window_ties_the_date(window, world):
    conn, root, fs, outage, blank = world
    window.set_task(blank)
    window.content.setPlainText("**start, 2 days after #Line 2 outage.")
    window.read_items()
    window.save()
    assert Model(conn).tasks[blank].ties["start"] == Tie(outage, "end", 2, "workdays", "after")
    assert Model(conn).tasks[blank].start == "2026-11-13"
