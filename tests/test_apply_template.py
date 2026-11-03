"""Apply template (release 5.63, decisions 301 to 309): a template put into tasks that already exist, which keep all they have."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from docrepo import db, notes_page, people, tasks, templates, timing  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, Tie  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.tasks import TaskError  # noqa: E402
from docrepo.templates import Choice, Library, RowTiming  # noqa: E402
from docrepo.timing import RowTie  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.templates_view import ApplyTemplateDialog, MakeTasksDialog  # noqa: E402

AT = datetime(2026, 11, 2, 9, 0)
TODAY = AT.date()
SETTINGS = Settings(me="P001")
WORKDAYS = {0, 1, 2, 3, 4}
TOM, PRIYA, MIKE = "P003", "P002", "P004"


@pytest.fixture
def conn():
    c = db.connect_memory()
    load_sample(c)
    yield c
    c.close()


def plant_trial(conn, name="Plant trial, high complexity", anchor_on_top=False, top=None) -> dict:
    """Seven subtasks, two of them under one that spans them, tied around an anchor."""
    row = templates.new_template(conn, name, AT, top or {})
    add = lambda parent, title, **v: templates.add_row(conn, SETTINGS, parent, {"title": title, "inherit_labels": True, **v}, AT)[0]  # noqa: E731
    prep = add(row, "Trial preparation")
    change = add(prep, "Change record prep", duration=10, assignees=[TOM], assignee_hours=20.0)
    permit = add(prep, "Permit request", duration=2, leads=[PRIYA])
    window = add(row, "Trial execution window", duration=5, assignees=[TOM, MIKE], assignee_per_day=6.0, notes="Bring the checklist.")
    report = add(row, "Trial report", duration=5, leads=[PRIYA])
    review = add(row, "Management review", duration=1)
    close = add(row, "Lessons learned", duration=2)
    r = dict(top=row, prep=prep, change=change, permit=permit, window=window, report=report, review=review, close=close, template=Library(conn).rows[row].template)
    plan = {change: RowTiming({"start": RowTie(None, "start", 30)}, 10), permit: RowTiming({"start": RowTie(None, "start", 10)}, 2),
            report: RowTiming({"start": RowTie(None, "end", 1, direction="after")}, 5), review: RowTiming({"start": RowTie(report, "end", 2, direction="after")}, 1),
            close: RowTiming({"start": RowTie(review, "end", 5, direction="after")}, 2)}
    if anchor_on_top:
        plan = {change: RowTiming({"start": RowTie(None, "start", 30)}, 10), report: RowTiming({"start": RowTie(None, "end", 1, direction="after")}, 5)}
        templates.apply_row(conn, SETTINGS, row, {"title": name, "inherit_labels": True, "duration": 5, **(top or {})}, AT)
        templates.apply_timing(conn, SETTINGS, r["template"], row, plan, AT)
    else:
        plan[window] = RowTiming({}, 5)
        templates.apply_timing(conn, SETTINGS, r["template"], window, plan, AT)
    return r


def trial(conn, title="Trial 1", **fields) -> str:
    return tasks.create_task(conn, SETTINGS, title=title, at=AT, created_by="Browse tool", **fields)


def under(conn, task_id) -> dict[str, str]:
    """Its subtasks by title, and theirs."""
    m = Model(conn)
    out = {}
    for x in m.descendants_of(task_id):
        out[m.tasks[x].title] = x
    return out


def links_of(conn, task_id) -> set[str]:
    return {r["field"] for r in conn.execute("SELECT field FROM task_links WHERE task = ?", (task_id,))}


def dates(conn, task_id):
    t = Model(conn).tasks[task_id]
    return t.start, t.due


def apply(conn, r, *ids, given=None):
    return templates.apply_template(conn, SETTINGS, r["top"], {x: (given or {}).get(x) for x in ids}, AT)


# ---- what each task keeps and gains (decisions 301 and 303) ----
def test_your_six_trials_each_keep_all_they_have_and_gain_the_subtasks(conn):
    r = plant_trial(conn)
    trials = [trial(conn, f"Trial {i}", description=f"Plan for trial {i}", start=f"2027-0{i}-01", due=f"2027-0{i}-10", leads=[MIKE], labels=["Safety"]) for i in range(1, 7)]
    for i, t in enumerate(trials, start=1):
        notes_page.put(conn, t, f"Notes from trial {i}", AT)
    done = apply(conn, r, *trials)
    assert [len(x.made) for x in done] == [7] * 6
    m = Model(conn)
    for i, t in enumerate(trials, start=1):
        x = m.tasks[t]
        assert (x.title, x.description, x.start, x.due, x.leads, x.labels) == (f"Trial {i}", f"Plan for trial {i}", f"2027-0{i}-01", f"2027-0{i}-10", [MIKE], ["Safety"])
        assert notes_page.get(conn, t) == f"Notes from trial {i}"
        titles = sorted(under(conn, t))
        assert titles == sorted(["Trial preparation", "Change record prep", "Permit request", "Trial execution window", "Trial report", "Management review", "Lessons learned"])
    lib = Library(conn)
    assert sorted(c.task for c in lib.trees(r["template"])) == sorted(trials)  # each is its own tree's top
    assert lib.copies[trials[0]].tree == trials[0] and lib.copies[trials[0]].row == r["top"]


def test_the_subtasks_have_their_attributes_links_and_ties(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    apply(conn, r, t)
    kids, m = under(conn, t), Model(conn)
    window = m.tasks[kids["Trial execution window"]]
    assert window.assignees == [TOM, MIKE] and window.assignee_per_day == 6.0 and window.duration == 5 and window.assignee_hours == 30.0
    assert {"assignees", "assignee_hours", "duration"} <= links_of(conn, window.id)
    report = m.tasks[kids["Trial report"]]
    assert report.ties["start"] == Tie(window.id, "end", 1, "workdays", "after") and "start_tie" in links_of(conn, report.id)
    review = m.tasks[kids["Management review"]]
    assert review.ties["start"] == Tie(report.id, "end", 2, "workdays", "after")
    assert m.parents_of(kids["Change record prep"]) == [kids["Trial preparation"]]
    assert m.parents_of(kids["Trial preparation"]) == [t]
    assert window.created_by == "Template: Plant trial, high complexity"
    assert notes_page.get(conn, window.id) == "Bring the checklist."


def test_empty_fields_fill_and_follow_and_filled_ones_stay(conn):
    r = plant_trial(conn, top={"description": "From the template", "leads": [TOM], "labels": ["Safety"], "assignee_hours": 8.0, "urgent": True})
    t = trial(conn, description="Mine", assignees=[PRIYA])
    apply(conn, r, t)
    x = Model(conn).tasks[t]
    assert x.description == "Mine" and "description" not in links_of(conn, t)  # its own stays, and doesn't follow
    assert x.leads == [TOM] and "leads" in links_of(conn, t)  # empty: fills, and follows
    assert x.labels == ["Safety"] and "labels" in links_of(conn, t)
    assert x.assignee_hours == 8.0 and "assignee_hours" in links_of(conn, t)
    assert x.urgent and "urgent" in links_of(conn, t)
    assert x.assignees == [PRIYA] and "title" not in links_of(conn, t)


def test_a_field_that_says_the_same_follows(conn):
    r = plant_trial(conn, top={"description": "Same words"})
    t = trial(conn, description="Same words")
    apply(conn, r, t)
    assert "description" in links_of(conn, t)


def test_labels_add_to_what_it_has(conn):
    people.add_label(conn, "Reliability")
    people.add_label(conn, "Q4")
    r = plant_trial(conn, top={"labels": ["Safety", "Reliability"]})
    t = trial(conn, labels=["Reliability", "Q4"])
    apply(conn, r, t)
    assert Model(conn).tasks[t].labels == ["Reliability", "Q4", "Safety"] and "labels" not in links_of(conn, t)


@pytest.mark.parametrize("fields", [{"start": "2027-03-01"}, {"due": "2027-03-05"}, {"start": "2027-03-01", "due": "2027-03-05"}])
def test_a_task_with_a_date_takes_no_duration_so_its_dates_never_change(conn, fields):
    r = plant_trial(conn, top={"duration": 3, "calendar_days": True})
    t = trial(conn, **fields)
    apply(conn, r, t)
    x = Model(conn).tasks[t]
    assert x.duration is None and not x.calendar_days and (x.start, x.due) == (fields.get("start"), fields.get("due"))
    assert not {"duration", "calendar_days"} & links_of(conn, t)


def test_a_task_with_no_date_takes_the_duration(conn):
    r = plant_trial(conn, top={"duration": 3})
    t = trial(conn)
    apply(conn, r, t)
    assert Model(conn).tasks[t].duration == 3 and "duration" in links_of(conn, t)


def test_a_rate_fills_an_empty_role_and_people_bring_their_share(conn):
    r = plant_trial(conn, top={"assignee_per_day": 4.0, "assignees": [TOM], "involvement": {("assignee", TOM): 25}})
    t = trial(conn, start="2027-03-01", due="2027-03-05")
    apply(conn, r, t)
    x = Model(conn).tasks[t]
    assert (x.assignee_per_day, x.assignee_hours, x.involvement) == (4.0, 20.0, {("assignee", TOM): 25})
    assert (x.start, x.due) == ("2027-03-01", "2027-03-05")


def test_the_status_log_says_what_happened(conn):
    r = plant_trial(conn, top={"leads": [TOM]})
    t = trial(conn)
    apply(conn, r, t)
    logged = {(x["field"], x["via"]) for x in conn.execute("SELECT field, via FROM status_log WHERE task = ?", (t,))}
    assert ("Template link", "Template: Plant trial, high complexity") in logged and ("Lead", "Template: Plant trial, high complexity") in logged


def test_starting_notes_go_at_the_end_of_the_page(conn):
    r = plant_trial(conn, top={"notes": "Template's notes"})
    mine, blank = trial(conn, "Mine"), trial(conn, "Blank")
    notes_page.put(conn, mine, "My notes\n\nMore of them", AT)
    apply(conn, r, mine, blank)
    assert notes_page.get(conn, mine) == "My notes\n\nMore of them\nTemplate's notes"
    assert notes_page.get(conn, blank) == "Template's notes"


# ---- the anchor (decision 302) ----
def test_the_anchor_starts_the_day_the_task_starts_and_moving_the_task_moves_the_tree(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01", due="2027-03-12")
    apply(conn, r, t)
    kids = under(conn, t)
    window = kids["Trial execution window"]
    assert Model(conn).tasks[window].ties["start"] == Tie(t, "start", 0, "workdays", "after")
    assert "start_tie" not in links_of(conn, window)  # a tie of its own: the template's Timing doesn't own it
    assert dates(conn, window) == ("2027-03-01", "2027-03-05")
    assert dates(conn, kids["Trial report"]) == ("2027-03-08", "2027-03-12")
    assert dates(conn, kids["Management review"]) == ("2027-03-16", "2027-03-16")
    assert dates(conn, kids["Change record prep"])[0] == "2027-01-18"
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", start="2027-04-05", due="2027-04-16")
    assert dates(conn, window) == ("2027-04-05", "2027-04-09")
    assert dates(conn, kids["Trial report"]) == ("2027-04-12", "2027-04-16")
    assert dates(conn, kids["Change record prep"])[0] == "2027-02-22"


def test_moving_the_anchor_itself_moves_what_follows_it_and_leaves_the_task(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01", due="2027-03-12")
    apply(conn, r, t)
    kids = under(conn, t)
    tasks.update_task(conn, SETTINGS, kids["Trial execution window"], at=AT, via="Browse tool", start="2027-03-08")
    assert dates(conn, kids["Trial report"]) == ("2027-03-15", "2027-03-19")
    assert dates(conn, t) == ("2027-03-01", "2027-03-12")
    assert Model(conn).tasks[kids["Trial execution window"]].ties["start"].amount == 5  # a different gap, and still tied


def test_a_task_with_no_start_waits_and_lands_when_the_anchor_gets_a_date(conn):
    r = plant_trial(conn)
    t = trial(conn, due="2027-03-12")
    apply(conn, r, t)
    kids = under(conn, t)
    window = kids["Trial execution window"]
    assert dates(conn, window) == (None, None) and not Model(conn).tasks[window].ties
    assert dates(conn, kids["Trial report"]) == (None, None)
    tasks.update_task(conn, SETTINGS, window, at=AT, via="Browse tool", start="2027-03-01")
    assert dates(conn, kids["Trial report"]) == ("2027-03-08", "2027-03-12")


def test_a_date_typed_for_the_anchor_is_plain(conn):
    r = plant_trial(conn)
    t = trial(conn)
    apply(conn, r, t, given={t: {r["window"]: Choice(start="2027-05-03")}})
    kids = under(conn, t)
    assert dates(conn, kids["Trial execution window"]) == ("2027-05-03", "2027-05-07") and not Model(conn).tasks[kids["Trial execution window"]].ties
    assert dates(conn, kids["Trial report"]) == ("2027-05-10", "2027-05-14")


def test_a_date_typed_over_the_tie_keeps_it_with_a_new_gap(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    tie = Tie(t, "start", 0, "workdays", "after")
    apply(conn, r, t, given={t: {r["window"]: Choice(start="2027-03-08", tie=tie)}})
    kids = under(conn, t)
    x = Model(conn).tasks[kids["Trial execution window"]]
    assert x.start == "2027-03-08" and x.ties["start"] == Tie(t, "start", 5, "workdays", "after")
    assert dates(conn, kids["Trial report"]) == ("2027-03-15", "2027-03-19")
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", start="2027-03-15")
    assert Model(conn).tasks[kids["Trial execution window"]].start == "2027-03-22"


def test_when_the_top_row_is_the_anchor_the_tasks_own_dates_are_it(conn):
    r = plant_trial(conn, anchor_on_top=True)
    t = trial(conn, start="2027-03-01", due="2027-03-05")
    apply(conn, r, t)
    kids = under(conn, t)
    assert Model(conn).tasks[t].ties == {} and (Model(conn).tasks[t].duration is None)
    assert Model(conn).tasks[kids["Trial report"]].ties["start"] == Tie(t, "end", 1, "workdays", "after")
    assert dates(conn, kids["Trial report"]) == ("2027-03-08", "2027-03-12")
    assert dates(conn, kids["Change record prep"])[0] == "2027-01-18"
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", due="2027-03-12")
    assert dates(conn, kids["Trial report"]) == ("2027-03-15", "2027-03-19")


def test_a_template_with_no_anchor_still_applies(conn):
    row = templates.new_template(conn, "Plain one", AT)
    templates.add_row(conn, SETTINGS, row, {"title": "First", "inherit_labels": True, "duration": 2}, AT)
    t = trial(conn, start="2027-03-01")
    templates.apply_template(conn, SETTINGS, row, {t: None}, AT)
    assert dates(conn, under(conn, t)["First"]) == (None, None)


# ---- a subtask of the same name (decision 304) ----
def test_a_subtask_of_the_same_name_is_kept_and_follows(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    mine = trial(conn, "trial REPORT", parents=[t], description="My draft", start="2027-06-01", due="2027-06-02", assignees=[MIKE])
    other = trial(conn, "Something of mine", parents=[t])
    done = apply(conn, r, t)
    assert done[0].kept == [mine] and len(done[0].made) == 6
    kids, m = under(conn, t), Model(conn)
    assert kids["trial REPORT"] == mine and "Trial report" not in kids and kids["Something of mine"] == other
    x = m.tasks[mine]
    assert (x.title, x.description, x.start, x.due, x.assignees, x.ties) == ("trial REPORT", "My draft", "2027-06-01", "2027-06-02", [MIKE], {})
    assert x.leads == [PRIYA] and "leads" in links_of(conn, mine) and "title" not in links_of(conn, mine)
    assert "duration" not in links_of(conn, mine) and "start_tie" not in links_of(conn, mine)
    lib = Library(conn)
    assert lib.copies[mine].row == r["report"] and lib.copies[mine].tree == t
    assert other not in lib.copies
    assert dates(conn, kids["Management review"]) == ("2027-06-04", "2027-06-04")  # what's tied to it counts from your dates


def test_a_kept_subtask_with_no_dates_takes_the_rows_tie(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    mine = trial(conn, "Trial report", parents=[t])
    apply(conn, r, t)
    x = Model(conn).tasks[mine]
    assert (x.start, x.due, x.duration) == ("2027-03-08", "2027-03-12", 5) and "start_tie" in links_of(conn, mine) and "title" in links_of(conn, mine)


def test_a_kept_anchor_with_dates_stays_and_the_rest_count_from_it(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    mine = trial(conn, "Trial execution window", parents=[t], start="2027-04-05", due="2027-04-09")
    apply(conn, r, t)
    kids, x = under(conn, t), Model(conn).tasks[mine]
    assert (x.start, x.due, x.ties) == ("2027-04-05", "2027-04-09", {})
    assert dates(conn, kids["Trial report"]) == ("2027-04-12", "2027-04-16")


def test_a_kept_anchor_with_no_dates_ties_to_the_task(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    mine = trial(conn, "Trial execution window", parents=[t])
    apply(conn, r, t)
    assert Model(conn).tasks[mine].ties["start"] == Tie(t, "start", 0, "workdays", "after")
    assert dates(conn, mine) == ("2027-03-01", "2027-03-05")


def test_a_nested_row_finds_its_name_under_where_its_parent_landed(conn):
    r = plant_trial(conn)
    t = trial(conn)
    prep = trial(conn, "Trial preparation", parents=[t])
    permit = trial(conn, "Permit request", parents=[prep])
    stray = trial(conn, "Change record prep", parents=[t])  # at the wrong level: no match
    done = apply(conn, r, t)
    assert sorted(done[0].kept) == sorted([prep, permit])
    lib = Library(conn)
    assert lib.copies[permit].row == r["permit"] and stray not in lib.copies
    assert sum(x.title == "Change record prep" for x in Model(conn).tasks.values()) == 2


def test_a_row_that_repeats_a_subtask_that_repeats_and_one_that_follows_arent_matched(conn):
    r = plant_trial(conn)
    weekly = templates.add_row(conn, SETTINGS, r["top"], {"title": "Weekly check", "inherit_labels": True, "recurrence": "Weekly"}, AT)[0]
    t = trial(conn)
    a = trial(conn, "Weekly check", parents=[t])
    b = trial(conn, "Trial report", parents=[t], recurrence="Weekly")
    plan = templates.plan_apply(Library(conn), Model(conn), r["top"], t)
    assert weekly not in plan.kept and r["report"] not in plan.kept and a and b
    other = plant_trial(conn, "Another")
    u = trial(conn, "Trial 2")
    following = templates.make_tasks(conn, SETTINGS, other["report"], "Trial report", u, {}, AT)[0]
    assert r["report"] not in templates.plan_apply(Library(conn), Model(conn), r["top"], u).kept and following


def test_a_subtask_under_two_tasks_goes_to_the_first(conn):
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A"), trial(conn, "Trial B")
    shared = trial(conn, "Trial report", parents=[a, b])
    done = apply(conn, r, a, b)
    assert done[0].kept == [shared] and done[1].kept == [] and len(done[1].made) == 7
    assert Library(conn).copies[shared].tree == a


# ---- what it refuses (decision 306) ----
def test_a_task_it_cant_go_into_says_why(conn):
    r = plant_trial(conn)
    closed, routine, gone = trial(conn, "Closed", state="Closed"), trial(conn, "Routine", recurrence="Weekly"), trial(conn, "Gone")
    tasks.set_discarded(conn, SETTINGS, gone, "No", at=AT, via="Browse tool")
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Already", None, {}, AT)
    lib, m = Library(conn), Model(conn)
    said = {x: templates.plan_apply(lib, m, r["top"], x).refused for x in (closed, routine, gone, made[0], made[1], "T999999")}
    assert said == {closed: "It's closed.", routine: "It's a routine task.", gone: "It's discarded.", made[0]: "It already follows Plant trial, high complexity.",
                    made[1]: "It already follows Plant trial, high complexity.", "T999999": "There's no task T999999."}


def test_applying_it_twice_is_refused(conn):
    r = plant_trial(conn)
    t = trial(conn)
    apply(conn, r, t)
    with pytest.raises(TaskError, match="already follows"):
        apply(conn, r, t)


def test_one_refusal_changes_nothing(conn):
    r = plant_trial(conn)
    good, closed = trial(conn, "Good"), trial(conn, "Shut", state="Closed")
    before = len(Model(conn).tasks)
    with pytest.raises(TaskError, match="Shut: It's closed"):
        apply(conn, r, good, closed)
    assert len(Model(conn).tasks) == before and good not in Library(conn).copies


def test_a_template_it_cant_apply_says_why(conn):
    r = plant_trial(conn)
    t = trial(conn)
    weekly = templates.new_template(conn, "Weekly one", AT, {"recurrence": "Weekly"})
    assert templates.template_refusal(Library(conn), weekly) == "Weekly one repeats, so it would turn each task into a routine one."
    with pytest.raises(TaskError, match="repeats"):
        templates.apply_template(conn, SETTINGS, weekly, {t: None}, AT)
    templates.set_discarded(conn, r["template"], "Old", AT)
    with pytest.raises(TaskError, match="is discarded"):
        apply(conn, r, t)
    plain = templates.new_template(conn, "Plain one", AT)
    with pytest.raises(TaskError, match="Tick a task"):
        templates.apply_template(conn, SETTINGS, plain, {}, AT)


# ---- afterwards: a tree like any other ----
def test_a_template_change_reaches_the_subtasks_and_leaves_what_the_task_has_alone(conn):
    r = plant_trial(conn, top={"description": "From the template", "leads": [TOM]})
    a, b = trial(conn, "Trial A", description="Mine"), trial(conn, "Trial B")
    apply(conn, r, a, b)
    row = Library(conn).rows[r["report"]]
    templates.apply_row(conn, SETTINGS, r["report"], {"title": row.title, "inherit_labels": True, "duration": 5, "leads": [MIKE], "ties": dict(row.ties)}, AT)
    assert Model(conn).tasks[under(conn, a)["Trial report"]].leads == [MIKE]
    assert Model(conn).tasks[under(conn, b)["Trial report"]].leads == [MIKE]
    templates.apply_row(conn, SETTINGS, r["top"], {"title": "Plant trial, high complexity", "inherit_labels": True, "description": "New words", "leads": [TOM]}, AT)
    m = Model(conn)
    assert m.tasks[a].description == "Mine" and m.tasks[b].description == "New words"


def test_a_new_row_is_offered_to_the_tasks_and_a_timing_change_reaches_them(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    apply(conn, r, t)
    plan = templates.preview_new_row(conn, r["top"], {"title": "Extra", "inherit_labels": True, "duration": 1}, AT)
    assert [x.task for x in plan.trees] == [t]
    templates.add_row(conn, SETTINGS, r["top"], {"title": "Extra", "inherit_labels": True, "duration": 1}, AT)
    assert "Extra" in under(conn, t)
    lib = Library(conn)
    rows = {x.id: RowTiming(dict(x.ties), x.days) for x in lib.lines(r["template"]) if x.placeable}
    rows[r["report"]] = RowTiming({"start": RowTie(None, "end", 3, direction="after")}, 5)
    templates.apply_timing(conn, SETTINGS, r["template"], r["window"], rows, AT)
    assert dates(conn, under(conn, t)["Trial report"]) == ("2027-03-10", "2027-03-16")
    assert Model(conn).tasks[under(conn, t)["Trial execution window"]].ties["start"].source == t  # its tie to the task stays


def test_a_new_anchor_keeps_the_tree_tied_to_the_task(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01")
    apply(conn, r, t)
    held = {k: dates(conn, v) for k, v in under(conn, t).items()}
    lib = Library(conn)
    lines = timing.rebased(lib.lines(r["template"]), r["window"], r["report"], 5)
    rows = {x.id: RowTiming(dict(x.ties), x.days) for x in lines if x.placeable}
    templates.apply_timing(conn, SETTINGS, r["template"], r["report"], rows, AT)
    assert {k: dates(conn, v) for k, v in under(conn, t).items()} == held
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", start="2027-03-08")
    assert dates(conn, under(conn, t)["Trial execution window"])[0] == "2027-03-08"


def test_detach_lets_it_go_and_keeps_what_it_has(conn, sample_root):
    conn, root, fs = sample_root
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01", description="Mine")
    apply(conn, r, t)
    templates.detach(conn, root, fs, t, AT)
    x = Model(conn).tasks[t]
    assert t not in Library(conn).copies and x.description == "Mine" and x.start == "2027-03-01"


def test_the_templates_changes_list_says_so(conn):
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A"), trial(conn, "Trial B")
    apply(conn, r, a, b)
    line = Library(conn).changes[r["template"]][0]
    assert line.text == "Applied to Trial A, Trial B" and line.said() == "To 2 trees"


# ---- what the window says before anything changes ----
def test_the_plans_words(conn):
    r = plant_trial(conn, top={"leads": [TOM], "labels": ["Safety"]})
    t = trial(conn, description="Mine")
    trial(conn, "Trial report", parents=[t])
    plan = templates.plan_apply(Library(conn), Model(conn), r["top"], t)
    assert plan.words() == "Adds 6 subtasks. Uses your Trial report. Fills Labels and Lead. Keeps all it has."
    assert (plan.adds, plan.uses, plan.refused) == (6, ["Trial report"], "")
    plain = trial(conn, "Plain", leads=[MIKE], labels=["Safety"])
    assert templates.plan_apply(Library(conn), Model(conn), r["top"], plain).words() == "Adds 7 subtasks. Keeps all it has."


@pytest.mark.parametrize("fields, mine", [({"start": "2027-03-01", "due": "2027-03-12"}, None), ({}, None), ({"due": "2027-03-12"}, None),
                                          ({"start": "2027-03-01"}, {"title": "Trial report", "start": "2027-06-01", "due": "2027-06-02"}),
                                          ({"start": "2027-03-01"}, {"title": "Trial execution window"}), ({"start": "2027-03-01"}, {"title": "Trial report"})])
def test_what_the_window_works_out_is_what_applying_it_does(conn, fields, mine):
    r = plant_trial(conn)
    t = trial(conn, **fields)
    if mine:
        trial(conn, parents=[t], **mine)
    lib, m = Library(conn), Model(conn)
    plan = templates.plan_apply(lib, m, r["top"], t)
    said = timing.make_dates(templates.plan_typed(lib, m, r["top"], plan), lib.template_of(r["top"]).anchor, WORKDAYS)
    apply(conn, r, t)
    lib = Library(conn)
    for row, (start, due) in said.items():
        task = lib.copy_in(row, t)
        if lib.spans(lib.rows[row]) or row == r["top"]:
            continue
        assert dates(conn, task) == (start, due), lib.rows[row].title


def test_the_warning_when_subtasks_fall_outside_its_dates(conn):
    r = plant_trial(conn)
    t = trial(conn, start="2027-03-01", due="2027-03-05")
    lib, m = Library(conn), Model(conn)
    plan = templates.plan_apply(lib, m, r["top"], t)
    said = timing.make_dates(templates.plan_typed(lib, m, r["top"], plan), lib.template_of(r["top"]).anchor, WORKDAYS)
    words, warning = templates.tree_words(m.tasks[t], r["top"], said, date(2027, 1, 1))
    assert words == "Its subtasks run Mon 18 Jan to Wed 24 Mar." and warning == "That's outside its own dates, which stay as they are."
    assert templates.tree_words(m.tasks[t], r["top"], {r["top"]: (None, None)}, date(2027, 1, 1)) == ("Its subtasks have no dates yet.", "")


def test_saving_writes_the_pages_and_says_what_it_did(sample_root):
    conn, root, fs = sample_root
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A", start="2027-03-01"), trial(conn, "Trial B")
    trial(conn, "Trial report", parents=[b])
    done, out = templates.apply_to_tasks(conn, root, fs, SETTINGS, r["top"], {a: None, b: None}, AT)
    assert out.message == "Applied Plant trial, high complexity to 2 tasks: 13 subtasks added. 1 subtask of your own now follows it. 7 undated, waiting for dates."
    assert len(done) == 2 and (root / "Tasks" / under(conn, a)["Trial report"] / "Task.md").exists()


def test_the_corporate_tests_numbers(sample_root):
    """The dates, words and counts in release-5-63-test.md's steps, as the same calls."""
    conn, root, fs = sample_root
    top = templates.new_template(conn, "Plant trial", AT, {"labels": ["Safety"]})
    add = lambda title, **v: templates.add_row(conn, SETTINGS, top, {"title": title, "inherit_labels": True, **v}, AT)[0]  # noqa: E731
    change, win = add("Change record prep", duration=10), add("Trial execution window", duration=5, notes="Bring the checklist.")
    report, review = add("Trial report", duration=5, leads=[PRIYA]), add("Management review", duration=1)
    template = Library(conn).rows[top].template
    templates.apply_timing(conn, SETTINGS, template, win, {change: RowTiming({"start": RowTie(None, "start", 30)}, 10), win: RowTiming({}, 5),
                                                           report: RowTiming({"start": RowTie(None, "end", 1, direction="after")}, 5),
                                                           review: RowTiming({"start": RowTie(report, "end", 2, direction="after")}, 1)}, AT)
    a = trial(conn, "Trial A", start="2027-03-01", due="2027-03-05", description="My plan for trial A")
    b, c, d = trial(conn, "Trial B", start="2027-05-03"), trial(conn, "Trial C"), trial(conn, "Trial D", start="2027-06-07")
    e = trial(conn, "Trial E", state="Closed")
    mine = trial(conn, "Trial report", parents=[d], start="2027-07-01", due="2027-07-02", description="My draft")
    lib, m = Library(conn), Model(conn)
    plans = {x: templates.plan_apply(lib, m, top, x) for x in (a, b, c, d, e)}
    assert plans[e].refused == "It's closed."
    assert plans[a].words() == "Adds 4 subtasks. Fills Labels. Keeps all it has."
    assert plans[d].words() == "Adds 3 subtasks. Uses your Trial report. Fills Labels. Keeps all it has."
    said = timing.make_dates(templates.plan_typed(lib, m, top, plans[a]), win, WORKDAYS)
    assert templates.tree_words(m.tasks[a], top, said, TODAY) == ("Its subtasks run Mon 18 Jan 2027 to Tue 16 Mar 2027.", "That's outside its own dates, which stay as they are.")
    done, out = templates.apply_to_tasks(conn, root, fs, SETTINGS, top, {a: None, b: None, c: {win: Choice(start="2027-08-02")}, d: None}, AT)
    assert out.message == "Applied Plant trial to 4 tasks: 15 subtasks added. 1 subtask of your own now follows it."
    x, day = under(conn, a), lambda *k: dates(conn, under(conn, k[0])[k[1]])
    assert Model(conn).tasks[a].description == "My plan for trial A" and dates(conn, a) == ("2027-03-01", "2027-03-05") and Model(conn).tasks[a].labels == ["Safety"]
    assert dates(conn, x["Change record prep"])[0] == "2027-01-18"
    assert day(a, "Trial execution window") == ("2027-03-01", "2027-03-05") and notes_page.get(conn, x["Trial execution window"]) == "Bring the checklist."
    assert day(a, "Trial report") == ("2027-03-08", "2027-03-12") and Model(conn).tasks[x["Trial report"]].leads == [PRIYA]
    assert day(a, "Management review") == ("2027-03-16", "2027-03-16")
    assert (day(b, "Trial execution window"), day(b, "Trial report"), day(b, "Management review")) == (("2027-05-03", "2027-05-07"), ("2027-05-10", "2027-05-14"), ("2027-05-18", "2027-05-18"))
    assert dates(conn, c) == (None, None) and not Model(conn).tasks[under(conn, c)["Trial execution window"]].ties
    assert (day(c, "Trial execution window"), day(c, "Trial report"), day(c, "Management review")) == (("2027-08-02", "2027-08-06"), ("2027-08-09", "2027-08-13"), ("2027-08-17", "2027-08-17"))
    assert under(conn, d)["Trial report"] == mine and dates(conn, mine) == ("2027-07-01", "2027-07-02") and Model(conn).tasks[mine].leads == [PRIYA]
    assert day(d, "Trial execution window") == ("2027-06-07", "2027-06-11") and day(d, "Management review") == ("2027-07-06", "2027-07-06")
    tasks.update_task(conn, SETTINGS, a, at=AT, via="Browse tool", start="2027-04-05", due="2027-04-09")
    assert (day(a, "Trial execution window"), day(a, "Trial report"), day(a, "Management review")) == (("2027-04-05", "2027-04-09"), ("2027-04-12", "2027-04-16"), ("2027-04-20", "2027-04-20"))
    assert dates(conn, x["Change record prep"])[0] == "2027-02-22" and day(b, "Trial execution window")[0] == "2027-05-03"
    bw = under(conn, b)["Trial execution window"]
    tasks.update_task(conn, SETTINGS, bw, at=AT, via="Browse tool", start="2027-05-10")
    assert Model(conn).tasks[bw].ties["start"] == Tie(b, "start", 5, "workdays", "after") and day(b, "Trial report") == ("2027-05-17", "2027-05-21") and dates(conn, b)[0] == "2027-05-03"
    tasks.update_task(conn, SETTINGS, b, at=AT, via="Browse tool", start="2027-05-17")
    assert dates(conn, bw)[0] == "2027-05-24"
    row = Library(conn).rows[report]
    plan = templates.preview_row(conn, SETTINGS, report, {"title": row.title, "inherit_labels": True, "duration": 5, "leads": [MIKE], "ties": dict(row.ties)}, AT)
    assert len(plan.items) == 4
    templates.apply_row(conn, SETTINGS, report, {"title": row.title, "inherit_labels": True, "duration": 5, "leads": [MIKE], "ties": dict(row.ties)}, AT)
    assert Model(conn).tasks[mine].leads == [MIKE]
    desc = {"title": "Plant trial", "inherit_labels": True, "labels": ["Safety"], "description": "From the template"}
    plan = templates.preview_row(conn, SETTINGS, top, desc, AT)
    assert sorted(i.task for i in plan.items) == sorted([b, c, d]) and [n.task for n in plan.not_changing] == [a]
    templates.apply_row(conn, SETTINGS, top, desc, AT)
    assert Model(conn).tasks[a].description == "My plan for trial A" and Model(conn).tasks[b].description == "From the template"
    assert any(x.text == "Applied to Trial A, Trial B, Trial C, Trial D" for x in Library(conn).changes[template])


# ---- the window ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT))
    w.confirm = lambda title, text: True
    w.shown = []
    w.show_browse()
    yield w
    w.deleteLater()


def answer(w, fill):
    def run(dialog):
        w.shown.append(dialog)
        said = fill(dialog)
        problem = dialog.problem() if hasattr(dialog, "problem") else None
        assert problem is None, problem
        return said is not False
    w.run_dialog = run


def window(browse, ids, row=None) -> ApplyTemplateDialog:
    browse.refresh()
    return ApplyTemplateDialog(browse, browse.model(), Library(browse.conn), browse._people_options, lambda a, p: None, WORKDAYS, TODAY, ids, row)


def test_the_window_lists_each_task_and_counts_them(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a = trial(conn, "Trial A", start="2027-03-01", due="2027-03-05")
    b = trial(conn, "Trial B", start="2027-04-05")
    shut = trial(conn, "Shut", state="Closed")
    d = window(browse, [a, b, shut], r["top"])
    assert d.commit_button.text() == "Apply to 2 tasks" and d.commit_button.isEnabled()
    first, second, third = d.sections
    assert first.tick.text() == "Trial A" and first.tick.isChecked()
    assert first.dates.text() == "Mon 1 Mar 2027 to Fri 5 Mar 2027"
    assert first.says.text() == "Adds 7 subtasks. Keeps all it has."
    assert first.lands.text() == "Trial execution window starts Mon 1 Mar 2027. Its subtasks run Mon 18 Jan 2027 to Wed 24 Mar 2027."
    assert "outside its own dates" in first.warning.text() and not first.warning.isHidden()
    assert not third.tick.isChecked() and not third.tick.isEnabled() and third.says.text() == "It's closed." and third.fold_button is None
    assert first.rows is None  # its rows aren't made until they're unfolded
    second.tick.setChecked(False)
    assert d.commit_button.text() == "Apply to 1 task"
    first.tick.setChecked(False)
    assert d.commit_button.text() == "Apply" and not d.commit_button.isEnabled()
    assert list(d.targets()) == []


def test_unfolding_shows_the_rows_with_the_anchor_tied_to_the_task(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A", start="2027-03-01", due="2027-03-12"), trial(conn, "Trial B", start="2027-04-05")
    d = window(browse, [a, b], r["top"])
    s = d.sections[0]
    s.toggle()
    assert s.rows is not None and s.rows.isVisibleTo(s)
    lines = {x.row.id: x for x in s.rows.lines}
    assert lines[r["top"]].kept is not None and lines[r["top"]].kept_text.text() == "Mon 1 Mar 2027 to Fri 12 Mar 2027"
    assert s.rows.top_title.text() == "Trial A"
    anchor = lines[r["window"]]
    assert not anchor.is_anchor and anchor.own_tie == Tie(a, "start", 0, "workdays", "after") and anchor.says.text() == "The day Trial A starts"
    assert anchor.start.value() == "2027-03-01" and lines[r["report"]].start.value() == "2027-03-08"
    assert [x.text() for x in s.rows.body.findChildren(QLabel, "anchorPill")] == ["Anchor"]
    s.toggle()
    assert not s.rows.isVisibleTo(s)


def test_typing_over_the_anchor_gives_a_new_gap_and_the_section_follows(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A", start="2027-03-01", due="2027-03-31"), trial(conn, "Trial B", start="2027-04-05")
    d = window(browse, [a, b], r["top"])
    s = d.sections[0]
    s.toggle()
    anchor = next(x for x in s.rows.lines if x.row.id == r["window"])
    anchor.start.set_value("2027-03-08")
    s.rows._typed_over(anchor)
    assert s.lands.text().startswith("Trial execution window starts Mon 8 Mar 2027.")
    assert anchor.back.isVisibleTo(s.rows)
    targets = d.targets()
    assert targets[b] is None and targets[a][r["window"]] == Choice(start="2027-03-08", leads=[], assignees=[TOM, MIKE], duration=5, due=None, tie=Tie(a, "start", 0, "workdays", "after"))
    templates.apply_template(conn, SETTINGS, r["top"], targets, AT)
    x = Model(conn).tasks[under(conn, a)["Trial execution window"]]
    assert x.start == "2027-03-08" and x.ties["start"].amount == 5
    assert Model(conn).tasks[under(conn, b)["Trial execution window"]].start == "2027-04-05"


def test_a_task_with_no_start_opens_for_the_anchors_date(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A"), trial(conn, "Trial B", start="2027-04-05")
    d = window(browse, [a, b], r["top"])
    assert d.sections[0].rows is not None and d.sections[1].rows is None
    anchor = next(x for x in d.sections[0].rows.lines if x.row.id == r["window"])
    assert anchor.is_anchor and anchor.own_tie is None and anchor.due_box is not None and anchor.tie_button is not None
    assert d.sections[0].lands.text() == "Its subtasks have no dates yet."
    anchor.start.set_value("2027-05-03")
    s = d.sections[0].rows
    s._edited(anchor, "start")
    assert d.sections[0].lands.text().startswith("Trial execution window starts Mon 3 May 2027.")
    templates.apply_template(conn, SETTINGS, r["top"], d.targets(), AT)
    assert dates(conn, under(conn, a)["Trial execution window"]) == ("2027-05-03", "2027-05-07")


def test_one_task_opens_with_its_rows_showing_and_a_bad_date_stops_it(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a = trial(conn, "Trial A")
    d = window(browse, [a], r["top"])
    assert d.sections[0].rows is not None and d.commit_button.text() == "Apply to 1 task"
    anchor = next(x for x in d.sections[0].rows.lines if x.row.id == r["window"])
    anchor.start.line.setText("soon")
    assert d.problem() == "Trial A: The Start of Trial execution window isn't a date. Use YYYY-MM-DD."
    d._accept()
    assert not d.error.isHidden()


def test_a_kept_subtask_says_so_and_asks_nothing(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a = trial(conn, "Trial A", start="2027-03-01")
    trial(conn, "Trial report", parents=[a], start="2027-06-01", due="2027-06-02")
    d = window(browse, [a], r["top"])
    s = d.sections[0]
    assert s.says.text() == "Adds 6 subtasks. Uses your Trial report. Keeps all it has."
    line = next(x for x in s.rows.lines if x.row.id == r["report"])
    assert line.kept_text.text() == "Tue 1 Jun 2027 to Wed 2 Jun 2027" and not line.has_start
    assert sorted(x.text() for x in s.rows.body.findChildren(QLabel, "anchorPill")) == ["Anchor", "Yours"]
    assert next(x for x in s.rows.lines if x.row.id == r["review"]).start.value() == "2027-06-04"
    assert d.problem() is None


def test_changing_the_template_redraws_and_one_that_repeats_stops_it(browse):
    conn = browse.conn
    r = plant_trial(conn)
    other = templates.new_template(conn, "Short one", AT)
    templates.add_row(conn, SETTINGS, other, {"title": "Only row", "inherit_labels": True}, AT)
    weekly = templates.new_template(conn, "Weekly one", AT, {"recurrence": "Weekly"})
    a = trial(conn, "Trial A", start="2027-03-01")
    d = window(browse, [a], r["top"])
    assert d.row_id() == r["top"] and d.sections[0].says.text().startswith("Adds 7")
    d.template_box.setCurrentIndex(d.template_box.findData(other))
    assert d.row_id() == other and d.sections[0].says.text().startswith("Adds 1")
    d.template_box.setCurrentIndex(d.template_box.findData(weekly))
    assert d.refusal.text().endswith("routine one.") and not d.commit_button.isEnabled() and d.sections == []


def test_add_a_task_adds_its_section(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A", start="2027-03-01"), trial(conn, "Trial B", start="2027-04-05")
    d = window(browse, [a], r["top"])
    d.add_task(b)
    d.add_task(b)
    d.add_task(None)
    assert [s.plan.task for s in d.sections] == [a, b] and d.commit_button.text() == "Apply to 2 tasks"


def test_no_template_says_so(browse):
    conn = browse.conn
    for tid in list(Library(conn).templates):
        templates.set_discarded(conn, tid, "Old", AT)
    d = window(browse, [trial(conn, "Trial A")])
    assert d.row_id() is None and "no templates" in d.refusal.text() and not d.commit_button.isEnabled()


def test_select_mode_applies_it_to_what_is_ticked(browse):
    conn = browse.conn
    r = plant_trial(conn)
    trials = [trial(conn, f"Trial {i}", start=f"2027-0{i}-01", description=f"Plan {i}") for i in range(1, 7)]
    browse.refresh()
    browse.set_selecting(True)
    assert browse.apply_template_button.text() == "Apply template…" and not browse.apply_template_button.isEnabled()
    browse.ticked.update(trials)
    browse._sync_edit_selected()
    assert browse.apply_template_button.text() == "Apply template (6)…" and browse.apply_template_button.isEnabled()

    def fill(d: ApplyTemplateDialog):
        assert [s.plan.task for s in d.sections] == trials or sorted(s.plan.task for s in d.sections) == sorted(trials)
        d.template_box.setCurrentIndex(d.template_box.findData(r["top"]))
        assert d.commit_button.text() == "Apply to 6 tasks"
    answer(browse, fill)
    browse.apply_template_to_ticked()
    m = Model(conn)
    for i, t in enumerate(trials, start=1):
        assert m.tasks[t].description == f"Plan {i}" and len(m.children_of(t)) == 5 and len(m.descendants_of(t)) == 7
    assert "Applied Plant trial, high complexity to 6 tasks: 42 subtasks added." in browse.status.text()


def test_the_templates_page_and_the_tasks_menu_open_it(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a = trial(conn, "Trial A", start="2027-03-01")
    browse.refresh()

    def fill(d):
        assert d.row_id() == r["top"] and d.sections == []
        d.add_task(a)
    answer(browse, fill)
    browse.templates.apply((), r["top"])
    assert browse.sel == ("task", a) and len(Model(conn).descendants_of(a)) == 7

    b = trial(conn, "Trial B", start="2027-04-05")
    browse.refresh()

    def fill2(d):
        assert [s.plan.task for s in d.sections] == [b] and d.sections[0].rows is not None
        d.template_box.setCurrentIndex(d.template_box.findData(r["top"]))
    answer(browse, fill2)
    browse.templates.apply([b])
    assert len(Model(conn).descendants_of(b)) == 7


def test_the_chevron_turns_in_a_window_thats_showing(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A", start="2027-03-01"), trial(conn, "Trial B", start="2027-04-05")
    d = window(browse, [a, b], r["top"])
    d.show()
    QApplication.processEvents()
    s = d.sections[0]
    s.toggle()
    assert s.rows.isVisibleTo(s)
    s.toggle()
    assert not s.rows.isVisibleTo(s)
    d.mark_clean()
    d.reject()


def test_unfolding_isnt_a_change_but_typing_is(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a, b = trial(conn, "Trial A", start="2027-03-01"), trial(conn, "Trial B", start="2027-04-05")
    d = window(browse, [a, b], r["top"])
    s = d.sections[0]
    s.toggle()
    assert not d.changed()
    s.tick.setChecked(False)
    assert d.changed()
    s.tick.setChecked(True)
    assert not d.changed()
    next(x for x in s.rows.lines if x.row.id == r["window"]).days.setText("9")
    assert d.changed()


def test_closing_it_changes_nothing(browse):
    conn = browse.conn
    r = plant_trial(conn)
    a = trial(conn, "Trial A")
    browse.refresh()
    answer(browse, lambda d: False)
    browse.templates.apply([a], r["top"])
    assert Model(conn).children_of(a) == [] and a not in Library(conn).copies


def test_make_tasks_still_draws_as_it_did(browse):
    conn = browse.conn
    r = plant_trial(conn)
    d = MakeTasksDialog(browse, browse.model(), Library(conn), r["top"], browse._people_options, lambda a, p: None, WORKDAYS, lambda a, p: None, TODAY)
    d.name.setText("Trial 5")
    assert d.tree.top_title.text() == "Trial 5"
    line = next(x for x in d.lines if x.row.id == r["window"])
    assert line.is_anchor and line.tie_button is not None and d.tie_panel is not None and d.tree.plan is None
