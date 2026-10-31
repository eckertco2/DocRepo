"""Task templates (releases 5.44 and 5.45; the task templates design, decisions 180 to 199): rows, Make tasks, links, what a
change to a template reaches, Save as template, and templates staying out of everything that reads tasks."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import bulk, capacity, db, edits, notes_page, search, tasks, template_pages, templates, views
from docrepo.config import Settings
from docrepo.model import Model, load_tasks
from docrepo.pages import Pages
from docrepo.stories import Stories
from docrepo.tasks import TaskError
from docrepo.templates import Choice, Library

AT = datetime(2026, 10, 8, 9, 30)
LATER = datetime(2026, 10, 9, 11, 0)
TODAY = AT.date()
SETTINGS = Settings(me="P001")
WINDOW = {"title": "Trial execution window", "inherit_labels": True, "leads": ["P001"], "lead_hours": 2, "assignees": ["P002", "P003"], "assignee_hours": 6,
          "urgent": True, "notes": "- [ ] Book the room\n- [ ] Get sign-off\n\nPlain words\n"}


def row(title: str, **values) -> dict:
    return {"title": title, "inherit_labels": True, **values}


def add(conn, parent: int, values: dict) -> int:
    return templates.add_row(conn, SETTINGS, parent, values, AT, left=_every_tree(conn, parent))[0]


def _every_tree(conn, parent: int) -> list[str]:
    """A row added while setting a test up reaches no tree."""
    lib = Library(conn)
    return [c.task for c in lib.trees(lib.rows[parent].template)]


@pytest.fixture
def trial(sample_conn):
    """A made-up trial template: a top row and three more, one under another, with hours, people, labels and starting notes."""
    conn = sample_conn
    top = templates.new_template(conn, "Product trial", AT, {"description": "A trial, from planning to the report.", "labels": ["Safety"], "leads": ["P001"]})
    prep = add(conn, top, row("Trial preparation", description="What has to be ready."))
    prep_a = add(conn, prep, row("Change record prep", assignees=["P002"], assignee_hours=30))
    window = add(conn, top, WINDOW)
    return conn, {"top": top, "prep": prep, "prep_a": prep_a, "window": window}


def links_of(conn, task_id: str) -> set[str]:
    return {r["field"] for r in conn.execute("SELECT field FROM task_links WHERE task = ?", (task_id,))}


def hours(conn, task_id: str) -> float:
    return load_tasks(conn, [task_id])[task_id].assignee_hours


def lines_of(conn, task_id: str) -> list[str]:
    m = Model(conn)
    stories = Stories(m, TODAY, lambda _: "")
    return [stories.field_sentence(e) for e in m.status_log_of(task_id)]


def test_a_template_is_its_own_records(trial):
    conn, r = trial
    lib = Library(conn)
    t = lib.live()[0]
    assert lib.name(t.id) == "Product trial" and t.top == r["top"]
    assert [(x.title, d) for x, d in lib.walk(r["top"])] == [("Product trial", 0), ("Trial preparation", 1), ("Change record prep", 2),
                                                              ("Trial execution window", 1)]
    assert [x.title for x in lib.path(r["prep_a"])] == ["Product trial", "Trial preparation", "Change record prep"]
    assert lib.rows[r["window"]].assignees == ["P002", "P003"] and lib.rows[r["top"]].labels == ["Safety"]
    assert templates.summary(lib.rows[r["prep_a"]]) == "30 h"
    assert templates.summary(lib.rows[r["window"]]) == "6 h"


def test_rows_are_checked_as_task_fields_are(trial):
    conn, r = trial
    with pytest.raises(TaskError):
        add(conn, r["top"], row(""))
    with pytest.raises(TaskError):
        add(conn, r["top"], row("Bad", leads=["P999"]))
    with pytest.raises(TaskError):
        add(conn, r["top"], row("Bad", assignee_hours=-1))
    with pytest.raises(TaskError):
        templates.new_template(conn, "  ", AT)


def test_nothing_that_reads_tasks_sees_a_template(trial, data_root, fs):
    """Decision 180: until tasks are made, a template is on no list, in no count, on no page."""
    conn, _ = trial
    plain = db.connect_memory()
    from docrepo.sample import load_sample

    load_sample(plain)
    m, empty = Model(conn), Model(plain)
    assert set(m.tasks) == set(empty.tasks) and m.origins == {}
    assert views.view_counts(m, TODAY, "P001") == views.view_counts(empty, TODAY, "P001")
    assert capacity.rebuild_all(conn, TODAY, SETTINGS) == capacity.rebuild_all(plain, TODAY, SETTINGS)
    assert Pages(m, TODAY, AT).contents_page() == Pages(empty, TODAY, AT).contents_page()
    assert not any("Product trial" in t.title or "Trial execution" in t.title for t in m.tasks.values())
    plain.close()


def test_make_tasks_copies_the_tree(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1: blue resin", None, {}, AT)
    assert len(made) == 4
    ts = load_tasks(conn, made)
    top, prep, prep_a, window = (ts[x] for x in made)
    assert top.title == "Trial 1: blue resin" and top.labels == ["Safety"] and top.leads == ["P001"] and top.description.startswith("A trial")
    assert (prep.title, prep_a.title, window.title) == ("Trial preparation", "Change record prep", "Trial execution window")
    assert prep_a.assignees == ["P002"] and prep_a.assignee_hours == 30 and window.urgent and window.lead_hours == 2
    assert all(t.created_by == "Template: Product trial" for t in ts.values())
    assert all(t.state == "Not started" and not t.start and not t.due for t in ts.values())
    m = Model(conn)
    assert m.parents_of(made[0]) == [] and m.parents_of(made[1]) == [made[0]] and m.parents_of(made[2]) == [made[1]] and m.parents_of(made[3]) == [made[0]]
    assert not m.today_items() or all(a.subject not in made for a in m.today_items())  # nothing goes on Today


def test_make_tasks_writes_the_links(trial):
    """Decision 183: whatever the template fills starts linked; a field it leaves blank is the task's. The top task's title
    is its own, as it's typed at Make tasks."""
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    assert links_of(conn, made[0]) == {"description", "labels", "leads"}
    assert links_of(conn, made[2]) == {"title", "assignees", "assignee_hours"}
    assert links_of(conn, made[3]) == {"title", "leads", "assignees", "lead_hours", "assignee_hours", "urgent"}
    lib = Library(conn)
    assert lib.copies[made[2]].row == r["prep_a"] and lib.copies[made[2]].tree == made[0]
    assert [c.task for c in lib.trees(lib.rows[r["top"]].template)] == [made[0]]
    assert set(lib.in_tree(made[0])) == set(made)


def test_make_tasks_takes_what_the_dialog_says(trial):
    """Anything typed is the task's; people left as offered stay linked."""
    conn, r = trial
    choices = {r["prep_a"]: Choice("2026-11-02", ["P003"], ["P002"]), r["window"]: Choice(None, ["P001"], ["P002"])}
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 2", "T000001", choices, AT)
    ts = load_tasks(conn, made)
    assert ts[made[2]].start == "2026-11-02" and ts[made[2]].leads == ["P003"] and "assignees" in links_of(conn, made[2])
    assert "leads" not in links_of(conn, made[2])
    assert ts[made[3]].assignees == ["P002"] and "assignees" not in links_of(conn, made[3]) and "leads" in links_of(conn, made[3])
    assert Model(conn).parents_of(made[0]) == ["T000001"]


def test_make_tasks_needs_a_name_at_the_top_but_not_from_a_row(trial):
    conn, r = trial
    with pytest.raises(TaskError):
        templates.make_tasks(conn, SETTINGS, r["top"], "  ", None, {}, AT)
    made = templates.make_tasks(conn, SETTINGS, r["prep"], "", "T000001", {}, AT)  # decision 197: from any row
    ts = load_tasks(conn, made)
    assert [ts[x].title for x in made] == ["Trial preparation", "Change record prep"]
    assert Model(conn).origins[made[0]].tree == made[0] and Model(conn).origins[made[1]].tree == made[0]


def test_starting_notes_are_copied_once(trial):
    """Decision 194: onto the notes page when the task is made, checklist lines included; the page is the task's from then on."""
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    page = notes_page.get(conn, made[3])
    assert page == "- [ ] Book the room\n- [ ] Get sign-off\n\nPlain words"
    assert [c.text for c in notes_page.checklist(page)] == ["Book the room", "Get sign-off"]
    assert notes_page.get(conn, made[0]) == ""
    plan = templates.apply_row(conn, SETTINGS, r["window"], {**WINDOW, "notes": "Other words"}, AT)
    assert plan.notes_changed and not plan.items  # starting notes reach no task
    assert notes_page.get(conn, made[3]) == page
    again = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 2", None, {}, AT)
    assert notes_page.get(conn, again[3]) == "Other words"


# ---- what breaks a link (decision 184) ----
def test_typing_a_different_value_ends_that_link_only(trial):
    """In tasks.update_task, so Update captures, Edit selected and the rest all keep to it."""
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    t = made[2]
    assert tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", assignee_hours=30) == []
    assert "assignee_hours" in links_of(conn, t)
    logged = tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", assignee_hours=20)
    assert [c.field for c in logged] == ["Assignee hours", "Template link"]
    assert logged[1].from_value == "Assignee hours: no longer follows Product trial" and logged[1].to_value is None
    assert links_of(conn, t) == {"title", "assignees"}
    # A state, a date or a parent isn't a linked field, so they don't end anything.
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", state="In progress", start="2026-11-02", due="2026-11-06")
    assert links_of(conn, t) == {"title", "assignees"}
    outcomes = bulk.run(conn, SETTINGS, [t], bulk.BulkEdit(add_labels=["Safety"]), AT, "Browse tool")
    assert outcomes[0].changes and links_of(conn, t) == {"title", "assignees"}  # labels: the row leaves them blank, so no link to end
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", title="Change record: first draft")
    assert links_of(conn, t) == {"assignees"}


def test_the_link_line_reads_as_a_sentence_in_the_story(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    tasks.update_task(conn, SETTINGS, made[2], at=AT, via="Browse tool", assignee_hours=20)
    assert "Assignee hours: no longer follows Product trial." in lines_of(conn, made[2])


def test_edit_tasks_marks_set_what_follows(trial, data_root, fs):
    """The chain mark and ↺: a value kept but no longer followed, and a value taken back and followed again."""
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    t = made[2]
    edits.edit_task(conn, data_root, fs, SETTINGS, t, AT, follow=["title", "assignees"])  # the chain mark on hours
    assert links_of(conn, t) == {"title", "assignees"} and hours(conn, t) == 30
    assert "Assignee hours: no longer follows Product trial." in lines_of(conn, t)
    edits.edit_task(conn, data_root, fs, SETTINGS, t, LATER, assignee_hours=20, follow=["title", "assignees"])
    assert hours(conn, t) == 20
    edits.edit_task(conn, data_root, fs, SETTINGS, t, LATER, assignee_hours=30, follow=["title", "assignees", "assignee_hours"])  # ↺
    assert links_of(conn, t) == {"title", "assignees", "assignee_hours"} and hours(conn, t) == 30
    assert "Assignee hours: follows Product trial again." in lines_of(conn, t)


def test_detach_ends_every_link_and_keeps_the_values(trial, data_root, fs):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    out = templates.detach(conn, data_root, fs, made[2], AT)
    assert "Its values stay" in out.message and links_of(conn, made[2]) == set() and hours(conn, made[2]) == 30
    m = Model(conn)
    assert made[2] not in m.origins and "No longer follows Product trial." in lines_of(conn, made[2])
    assert "From template" not in Pages(m, TODAY, AT).task_page(m.task(made[2]))
    with pytest.raises(TaskError):
        templates.detach(conn, data_root, fs, made[2], AT)


def test_task_link_is_for_a_live_templates_tasks(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    link = templates.task_link(conn, made[2])
    assert link.name == "Product trial" and link.path == "Product trial › Trial preparation › Change record prep"
    assert link.links == {"title", "assignees", "assignee_hours"} and not link.top and link.row.id == r["prep_a"]
    assert templates.task_link(conn, made[0]).top and templates.task_link(conn, "T000001") is None
    templates.set_discarded(conn, Library(conn).rows[r["top"]].template, "Not needed", AT)
    assert templates.task_link(conn, made[2]) is None  # no marks until it's back


# ---- a field changed: the preview and what it reaches (decisions 186, 187 and 198) ----
def _two_trees(conn, r) -> tuple[list[str], list[str]]:
    return (templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT), templates.make_tasks(conn, SETTINGS, r["top"], "Trial 2", None, {}, AT))


CHANGED = row("Change record prep", assignees=["P002"], assignee_hours=10)


def test_the_preview_changes_nothing(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    before = (conn.execute("SELECT count(*) FROM status_log").fetchone()[0], conn.execute("SELECT count(*) FROM labels").fetchone()[0])
    plan = templates.preview_row(conn, SETTINGS, r["prep_a"], {**CHANGED, "labels": ["Brand new label"]}, AT)
    assert [i.task for i in plan.items] == [a[2], b[2]] and plan.lines[0] == "Labels None → Brand new label"
    assert (conn.execute("SELECT count(*) FROM status_log").fetchone()[0], conn.execute("SELECT count(*) FROM labels").fetchone()[0]) == before
    assert hours(conn, a[2]) == 30 and Library(conn).rows[r["prep_a"]].assignee_hours == 30


def test_the_preview_says_what_each_task_would_become(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    plan = templates.preview_row(conn, SETTINGS, r["prep_a"], CHANGED, AT)
    assert plan.lines == ["Assignee hours 30 h → 10 h"]
    item = plan.items[0]
    assert item.tree == "Trial 1" and item.lines == ["Assignee hours 30 h → 10 h"] and item.state == "Not started"
    assert (item.work_before, item.work_after) == (30, 10)
    window = {**WINDOW, "assignee_hours": 8}
    item = templates.preview_row(conn, SETTINGS, r["window"], window, AT).items[0]
    assert (item.work_before, item.work_after) == (2 + 2 * 6, 2 + 2 * 8)  # each person's hours, as Capacity counts them


def test_a_change_reaches_the_tasks_still_following(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    assert hours(conn, a[2]) == 10 and hours(conn, b[2]) == 10
    assert "assignee_hours" in links_of(conn, a[2])  # still following
    assert Library(conn).rows[r["prep_a"]].assignee_hours == 10
    m = Model(conn)
    entry = next(e for e in m.status_log_of(a[2]) if e.field == "Assignee hours")
    assert entry.via == "Template: Product trial" and (entry.from_value, entry.to_value) == ("30", "10")
    assert "Assignee hours 30 → 10 · Template: Product trial." in lines_of(conn, a[2])  # decision 187
    # The capacity calendar follows, as it reads the task's own field.
    tasks.update_task(conn, SETTINGS, a[2], at=LATER, via="Browse tool", start="2026-11-02", due="2026-11-06")
    total = conn.execute("SELECT sum(hours) FROM work_calendar WHERE task = ?", (a[2],)).fetchone()[0]
    assert total == pytest.approx(10)
    newer = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 3", None, {}, LATER)
    assert hours(conn, newer[2]) == 10


def test_an_unticked_task_keeps_its_value_and_stops_following(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    plan = templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER, left=[b[2]])
    assert len(plan.items) == 2
    assert hours(conn, a[2]) == 10 and hours(conn, b[2]) == 30
    assert "assignee_hours" in links_of(conn, a[2]) and "assignee_hours" not in links_of(conn, b[2])
    assert "Assignee hours: no longer follows Product trial." in lines_of(conn, b[2])
    line = Library(conn).changes[Library(conn).rows[r["top"]].template][0]
    assert line.text == "Change record prep · Assignee hours 30 h → 10 h" and line.said() == "1 task changed, 1 left as it was"


def test_a_task_with_its_own_value_doesnt_change(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    tasks.update_task(conn, SETTINGS, b[2], at=AT, via="Browse tool", assignee_hours=20)
    plan = templates.preview_row(conn, SETTINGS, r["prep_a"], CHANGED, AT)
    assert [i.task for i in plan.items] == [a[2]]
    own = plan.not_changing[0]
    assert (own.task, own.why, own.tree) == (b[2], "own", "Trial 2") and own.text == "its own assignee hours 20 h"
    templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    assert hours(conn, b[2]) == 20
    # Its own value, the same as the new one: nothing to say.
    tasks.update_task(conn, SETTINGS, b[2], at=LATER, via="Browse tool", assignee_hours=10)
    assert not templates.preview_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER).not_changing


def test_a_top_tasks_name_is_its_own(trial):
    conn, r = trial
    a, _ = _two_trees(conn, r)
    plan = templates.preview_row(conn, SETTINGS, r["top"], row("Product trial, revised", description="A trial, from planning to the report.", labels=["Safety"], leads=["P001"]), AT)
    assert plan.items == [] and plan.lines == ["Title Product trial → Product trial, revised"]
    templates.apply_row(conn, SETTINGS, r["top"], row("Product trial, revised", description="A trial, from planning to the report.", labels=["Safety"], leads=["P001"]), LATER)
    assert load_tasks(conn, [a[0]])[a[0]].title == "Trial 1" and Model(conn).origins[a[0]].template == "Product trial, revised"
    # A subtask's title is linked.
    plan = templates.apply_row(conn, SETTINGS, r["prep_a"], {**CHANGED, "title": "Change record", "assignee_hours": 30}, LATER)
    assert len(plan.items) == 2 and load_tasks(conn, [a[2]])[a[2]].title == "Change record"


def test_closed_tasks_never_change_and_their_field_is_their_own_when_they_come_back(trial):
    """Decision 185, by any route: a reopened task's hours don't jump."""
    conn, r = trial
    a, b = _two_trees(conn, r)
    tasks.update_task(conn, SETTINGS, a[2], at=AT, via="Browse tool", state="Closed")
    plan = templates.preview_row(conn, SETTINGS, r["prep_a"], CHANGED, AT)
    assert [i.task for i in plan.items] == [b[2]] and [(x.task, x.why) for x in plan.not_changing] == [(a[2], "closed")]
    templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    assert hours(conn, a[2]) == 30 and "assignee_hours" in links_of(conn, a[2])  # untouched while it's closed
    logged = tasks.update_task(conn, SETTINGS, a[2], at=LATER, via="Browse tool", state="In progress")
    assert hours(conn, a[2]) == 30 and "assignee_hours" not in links_of(conn, a[2]) and "assignees" in links_of(conn, a[2])
    assert logged[-1].from_value == "Assignee hours: fell behind Product trial while closed, and stays as it is"
    # Nothing behind: reopening ends nothing.
    fresh = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 3", None, {}, LATER)
    tasks.update_task(conn, SETTINGS, fresh[2], at=LATER, via="Browse tool", state="Closed")
    tasks.update_task(conn, SETTINGS, fresh[2], at=LATER, via="Browse tool", state="In progress")
    assert "assignee_hours" in links_of(conn, fresh[2])


def test_discarded_tasks_never_change_and_stay_as_they_were_when_brought_back(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    tasks.set_discarded(conn, SETTINGS, a[2], "Made by mistake", at=AT, via="Browse tool")
    plan = templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    assert [(x.task, x.why) for x in plan.not_changing] == [(a[2], "discarded")] and hours(conn, a[2]) == 30
    tasks.set_discarded(conn, SETTINGS, a[2], None, at=LATER, via="Browse tool")
    assert hours(conn, a[2]) == 30 and "assignee_hours" not in links_of(conn, a[2])
    assert "Assignee hours: fell behind Product trial while discarded, and stays as it is." in lines_of(conn, a[2])


def test_parked_tasks_keep_following(trial):
    conn, r = trial
    a, _ = _two_trees(conn, r)
    tasks.update_task(conn, SETTINGS, a[2], at=AT, via="Browse tool", state="Parked")
    templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    assert hours(conn, a[2]) == 10


def test_a_field_the_template_starts_filling_reaches_only_empty_tasks(trial):
    """Decision 198, and they then follow it."""
    conn, r = trial
    a, b = _two_trees(conn, r)
    tasks.update_task(conn, SETTINGS, b[2], at=AT, via="Browse tool", lead_hours=9)
    filling = {**CHANGED, "assignee_hours": 30, "lead_hours": 4}
    plan = templates.preview_row(conn, SETTINGS, r["prep_a"], filling, AT)
    assert [i.task for i in plan.items] == [a[2]] and [x.why for x in plan.not_changing] == ["own"]
    templates.apply_row(conn, SETTINGS, r["prep_a"], filling, LATER)
    ts = load_tasks(conn, [a[2], b[2]])
    assert ts[a[2]].lead_hours == 4 and "lead_hours" in links_of(conn, a[2])
    assert ts[b[2]].lead_hours == 9 and "lead_hours" not in links_of(conn, b[2])


def test_a_field_the_template_stops_filling_changes_no_values(trial):
    """Decision 198: tasks keep what they have, as their own."""
    conn, r = trial
    a, _ = _two_trees(conn, r)
    plain = {**CHANGED, "assignee_hours": None}
    plan = templates.preview_row(conn, SETTINGS, r["prep_a"], plain, AT)
    assert plan.items == [] and plan.ending == {a[2]: ["assignee_hours"], _[2]: ["assignee_hours"]}
    templates.apply_row(conn, SETTINGS, r["prep_a"], plain, LATER)
    assert hours(conn, a[2]) == 30 and "assignee_hours" not in links_of(conn, a[2])
    assert "Assignee hours: no longer follows Product trial." in lines_of(conn, a[2])
    line = Library(conn).changes[Library(conn).rows[r["top"]].template][0]
    assert line.said() == "No task changed" and line.text == "Change record prep · Assignee hours 30 h → None"


def test_the_changes_list_is_newest_first_and_says_what_each_did(trial):
    conn, r = trial
    _two_trees(conn, r)
    t = Library(conn).rows[r["top"]].template
    templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    templates.apply_row(conn, SETTINGS, r["prep_a"], {**CHANGED, "notes": "Check the form"}, LATER)
    templates.apply_row(conn, SETTINGS, r["prep_a"], {**CHANGED, "notes": "Check the form"}, LATER)  # nothing changed, so no line
    lines = Library(conn).changes[t]
    assert [x.text for x in lines[:2]] == ["Change record prep · Starting notes changed", "Change record prep · Assignee hours 30 h → 10 h"]
    assert lines[1].said() == "2 tasks changed" and lines[0].said() == "No task changed"
    assert len(lines) == 2  # what was built before any tree isn't a change


def test_changes_to_a_template_nothing_was_made_from_arent_listed(trial):
    conn, r = trial
    t = Library(conn).rows[r["top"]].template
    templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    assert t not in Library(conn).changes
    templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, LATER)
    _, plan, made = templates.add_row(conn, SETTINGS, r["window"], row("Under the window"), LATER)
    assert made and Library(conn).changes[t][0].said() == "To 1 tree"
    fresh = templates.make_tasks(conn, SETTINGS, r["prep"], "", None, {}, LATER)  # a tree of only part of it
    assert fresh
    templates.add_row(conn, SETTINGS, r["prep"], row("Under preparation"), LATER, left=[fresh[0]])
    line = Library(conn).changes[t][0]
    assert line.text == "Added Under preparation" and line.said() == "To 1 tree, 1 left without it"


# ---- a subtask added (decision 188) ----
NEW = row("Pre-trial review", assignees=["P003"], assignee_hours=4, notes="- [ ] Check")


def test_a_new_subtask_is_offered_to_open_trees(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    tasks.update_task(conn, SETTINGS, b[0], at=AT, via="Browse tool", state="Closed")
    tasks.update_task(conn, SETTINGS, a[3], at=AT, via="Browse tool", state="Closed")
    plan = templates.preview_new_row(conn, r["top"], NEW, AT)
    assert [(t.task, t.title, t.closed, t.total) for t in plan.trees] == [(a[0], "Trial 1", 1, 4)]
    assert plan.closed_trees == ["Trial 2"] and plan.summary == "4 h" and plan.parent_title == "Product trial"


def test_a_new_subtask_arrives_undated_under_its_parent_with_its_fields_linked(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    row_id, plan, made = templates.add_row(conn, SETTINGS, r["prep"], NEW, LATER, left=[b[0]])
    assert len(made) == 1
    t = load_tasks(conn, made)[made[0]]
    m = Model(conn)
    assert m.parents_of(made[0]) == [a[1]] and t.title == "Pre-trial review" and t.assignee_hours == 4 and not t.start and not t.due
    assert t.created_by == "Template: Product trial" and links_of(conn, made[0]) == {"title", "assignees", "assignee_hours"}
    assert m.origins[made[0]].tree == a[0] and notes_page.get(conn, made[0]) == "- [ ] Check"
    assert "Pre-trial review added to this tree from Product trial." in lines_of(conn, a[1])
    assert not any(t.title == "Pre-trial review" and m.parents_of(t.id) == [b[1]] for t in m.tasks.values())  # the tree left out
    line = Library(conn).changes[Library(conn).rows[r["top"]].template][0]
    assert line.text == "Added Pre-trial review" and line.said() == "To 1 tree, 1 left without it"
    newer = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 3", None, {}, LATER)  # new trees always have it
    assert "Pre-trial review" in [load_tasks(conn, newer)[x].title for x in newer]


def test_a_new_subtask_goes_under_the_top_task_when_its_parent_is_gone(trial, data_root, fs):
    conn, r = trial
    a, _ = _two_trees(conn, r)
    templates.detach(conn, data_root, fs, a[1], AT)  # that tree's copy of the parent no longer comes from it
    _, _, made = templates.add_row(conn, SETTINGS, r["prep"], NEW, LATER)
    assert Model(conn).parents_of(made[0]) == [a[0]]


def test_a_row_only_offered_to_trees_that_have_its_parent(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["window"], "", None, {}, AT)  # a tree of only the window row
    plan = templates.preview_new_row(conn, r["prep"], NEW, AT)
    assert plan.trees == []
    assert [t.task for t in templates.preview_new_row(conn, r["window"], NEW, AT).trees] == [made[0]]


# ---- a subtask taken out (decision 188) ----
def test_taking_a_row_out_offers_to_discard_copies_with_nothing_on_them(trial, data_root, fs):
    conn, r = trial
    a, b = _two_trees(conn, r)
    tasks.update_task(conn, SETTINGS, b[3], at=AT, via="Browse tool", state="In progress")
    plan = templates.preview_remove(conn, r["window"])
    assert plan.rows == 1 and [(c.task, c.tree, c.can) for c in plan.copies] == [(a[3], "Trial 1", True), (b[3], "Trial 2", False)]
    assert notes_page.get(conn, a[3])  # its starting notes aren't something on it
    out = templates.take_out(conn, data_root, fs, SETTINGS, r["window"], AT, [a[3], b[3]])
    assert "1 copy discarded" in out.message and "1 task made from it stays" in out.message
    m = Model(conn)
    assert m.task(a[3]).discarded and m.task(a[3]).discard_reason == "Taken out of template Product trial"
    assert not m.task(b[3]).discarded and b[3] not in m.origins and links_of(conn, b[3]) == set()
    assert "No longer follows Product trial: its row was taken out." in lines_of(conn, b[3])
    line = Library(conn).changes[Library(conn).rows[r["top"]].template][0]
    assert line.text == "Took out Trial execution window" and line.said() == "1 task discarded, 1 kept"
    edits.bring_back_task(conn, data_root, fs, SETTINGS, a[3], AT)  # Bring back restores it
    assert not Model(conn).task(a[3]).discarded


def test_a_copy_with_something_on_it_cant_be_discarded(trial):
    conn, r = trial
    a, b = _two_trees(conn, r)
    notes_page.put(conn, a[3], "Words of the owner's own", AT)
    tasks.update_task(conn, SETTINGS, b[3], at=AT, via="Browse tool", current_status="Waiting on the room")
    plan = templates.preview_remove(conn, r["window"])
    assert [c.can for c in plan.copies] == [False, False]
    kept, gone = templates.remove_row(conn, SETTINGS, r["window"], AT, [a[3], b[3]])
    assert gone == [] and set(kept) == {a[3], b[3]}


def test_taking_a_row_out_takes_what_is_under_it_and_leaves_its_tasks(trial):
    """The copies stay, and their links end. A top row can't go."""
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    plan = templates.preview_remove(conn, r["prep"])
    assert plan.rows == 2 and all(c.can for c in plan.copies)  # the parent's only subtask goes with it
    kept, gone = templates.remove_row(conn, SETTINGS, r["prep"], AT)
    assert gone == [] and set(kept) == {made[1], made[2]}
    lib = Library(conn)
    assert r["prep"] not in lib.rows and r["prep_a"] not in lib.rows
    assert made[1] not in lib.copies and made[2] not in lib.copies and links_of(conn, made[2]) == set()
    m = Model(conn)
    assert made[2] in m.tasks and made[2] not in m.origins and m.origins[made[3]].path[-1] == "Trial execution window"
    assert any("its row was taken out" in (e.from_value or "") for e in m.status_log_of(made[2]))
    with pytest.raises(TaskError):
        templates.remove_row(conn, SETTINGS, r["top"], AT)


def test_a_parent_and_its_subtask_are_discarded_together(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    kept, gone = templates.remove_row(conn, SETTINGS, r["prep"], AT, [made[1], made[2]])
    assert kept == [] and set(gone) == {made[1], made[2]}
    # Unticking the subtask keeps the parent too, as it can't be discarded with a subtask left.
    other = templates.new_template(conn, "Other", AT)
    parent = add(conn, other, row("Parent"))
    add(conn, parent, row("Child"))
    tree = templates.make_tasks(conn, SETTINGS, other, "Tree", None, {}, AT)
    kept, gone = templates.remove_row(conn, SETTINGS, parent, AT, [tree[1]])
    assert gone == [] and set(kept) == {tree[1], tree[2]}


def test_moving_rows_only_affects_new_trees(trial):
    """Decision 188."""
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    assert not templates.shift_row(conn, r["prep"], -1) and templates.shift_row(conn, r["prep"], 1)
    lib = Library(conn)
    assert [x.id for x in lib.children(r["top"])] == [r["window"], r["prep"]]
    templates.reparent_row(conn, r["prep_a"], r["window"])
    lib = Library(conn)
    assert [x.id for x in lib.children(r["window"])] == [r["prep_a"]] and lib.children(r["prep"]) == []
    with pytest.raises(TaskError):
        templates.reparent_row(conn, r["window"], r["prep_a"])
    with pytest.raises(TaskError):
        templates.reparent_row(conn, r["top"], r["prep"])
    assert Model(conn).parents_of(made[2]) == [made[1]]  # the tree made before stays as it was
    newer = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 2", None, {}, AT)
    ts = load_tasks(conn, newer)
    assert [ts[x].title for x in newer] == ["Trial 2", "Trial execution window", "Change record prep", "Trial preparation"]


def test_a_discarded_template_stays_and_comes_back(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    t = Library(conn).rows[r["top"]].template
    templates.set_discarded(conn, t, "Made by mistake", AT)
    lib = Library(conn)
    assert lib.live() == [] and lib.templates[t].discard_reason == "Made by mistake"
    assert Model(conn).origins[made[0]].discarded and load_tasks(conn, [made[2]])[made[2]].assignee_hours == 30
    with pytest.raises(TaskError):
        templates.make_tasks(conn, SETTINGS, r["top"], "Trial 2", None, {}, AT)
    templates.set_discarded(conn, t, None, AT)
    assert Library(conn).live() and not Model(conn).origins[made[0]].discarded


def test_task_md_and_the_task_page_say_where_it_came_from(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    m = Model(conn)
    pages = Pages(m, TODAY, AT)
    assert "| From template | Product trial, Change record prep |" in pages.task_page(m.task(made[2]))
    assert "| From template | Product trial |" in pages.task_page(m.task(made[0]))
    assert "From template" not in pages.task_page(m.task("T000001"))
    from docrepo.detail import PageState, Pages as DetailPages

    html = DetailPages(m, TODAY, lambda _: "").page_head(m.task(made[2]), PageState())
    assert "From template:" in html and f'tplrow:{r["prep_a"]}' in html and "Product trial › Trial preparation › Change record prep" in html
    assert "From template" not in DetailPages(m, TODAY, lambda _: "").page_head(m.task("T000001"), PageState())


def test_save_as_template_with_a_link(sample_conn):
    """Decision 195: a task and what's under it, without dates, state, status, notes or captures; linked by default."""
    conn = sample_conn
    m = Model(conn)
    task = next(t.id for t in m.tasks.values() if m.children_of(t.id) and not t.discarded)
    below = [x for x in m.descendants_of(task) if not m.task(x).discarded]
    top = templates.save_as_template(conn, SETTINGS, task, "Installation pattern", True, AT)
    lib = Library(conn)
    walked = lib.walk(top)
    assert lib.rows[top].title == "Installation pattern" and len(walked) == 1 + len(below)
    assert all(not x.notes for x, _ in walked)
    after = Model(conn)
    assert after.origins[task].path == ("Installation pattern",) and after.origins[task].tree == task
    assert "title" not in links_of(conn, task)
    assert all(after.origins[x].tree == task for x in below)
    # Its values are unchanged, and each link holds its row's value.
    for x in [task, *below]:
        t, was = after.task(x), m.task(x)
        assert (t.title, t.start, t.due, t.state, t.current_status) == (was.title, was.start, was.due, was.state, was.current_status)
        for k in links_of(conn, x):
            assert getattr(t, k) == getattr(lib.rows[lib.copies[x].row], k)
    assert any(e.field == "Template link" and e.to_value == "Follows Installation pattern" for e in after.status_log_of(task))


def test_save_as_template_without_a_link_touches_no_task(sample_conn):
    conn = sample_conn
    m = Model(conn)
    task = next(t.id for t in m.tasks.values() if m.children_of(t.id))
    log_before = len(m.status)
    top = templates.save_as_template(conn, SETTINGS, task, "Pattern", False, AT)
    assert Library(conn).rows[top].title == "Pattern"
    after = Model(conn)
    assert after.origins == {} and len(after.status) == log_before


def test_save_as_moves_a_tree_to_the_new_template(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    tasks.update_task(conn, SETTINGS, made[2], at=AT, via="Browse tool", assignee_hours=20)
    top = templates.save_as_template(conn, SETTINGS, made[0], "Trial, revised", True, AT)
    m = Model(conn)
    assert m.origins[made[2]].template == "Trial, revised" and "assignee_hours" in links_of(conn, made[2])
    lib = Library(conn)
    assert lib.rows[lib.copies[made[2]].row].assignee_hours == 20
    assert templates.make_tasks(conn, SETTINGS, top, "Trial 2", None, {}, AT)


def test_from_the_browse_tool_new_people_and_labels_are_made(trial, data_root, fs):
    conn, r = trial
    from docrepo.parse import Who

    values = {**row("Pre-trial review"), "labels": ["Brand new label"], "leads": [Who(name="Sam Rivers")], "assignees": [Who("P002")]}
    row_id, out = templates.new_row(conn, data_root, fs, SETTINGS, r["top"], values, AT)
    assert "Sam Rivers" in out.message
    lib = Library(conn)
    assert lib.rows[row_id].labels == ["Brand new label"] and lib.rows[row_id].assignees == ["P002"]
    assert Model(conn).person_name(lib.rows[row_id].leads[0]) == "Sam Rivers"


def test_saving_from_the_browse_tool_says_what_it_did(trial, data_root, fs):
    conn, r = trial
    a, b = _two_trees(conn, r)
    out = templates.save_row(conn, data_root, fs, SETTINGS, r["prep_a"], CHANGED, AT, [b[2]])
    assert out.message == "1 task changed, 1 left as it was. Each status log says so." and not out.problems
    assert "| Assignees | Priya Shah (10 h) |" in (data_root / "Tasks" / a[2] / "Task.md").read_text(encoding="utf-8")
    assert templates.save_row(conn, data_root, fs, SETTINGS, r["prep_a"], {**CHANGED, "notes": "Words"}, AT).message == "Saved. Starting notes reach only new tasks."
    assert templates.save_row(conn, data_root, fs, SETTINGS, r["prep_a"], {**CHANGED, "notes": "Words"}, AT).message == "Nothing changed."
    other = templates.new_template(conn, "Other", AT)
    row_id = add(conn, other, row("Lonely"))
    assert templates.save_row(conn, data_root, fs, SETTINGS, row_id, row("Lonely", assignee_hours=1), AT).message == "Saved. No tasks follow it yet."


def test_make_from_the_browse_tool_indexes_and_writes(trial, data_root, fs):
    conn, r = trial
    made, out = templates.make(conn, data_root, fs, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    assert out.message == "Made 4 tasks. 4 undated, waiting for dates." and not out.problems
    assert (data_root / "Tasks" / made[3] / "Task.md").exists()
    assert conn.execute("SELECT 1 FROM search_text WHERE kind = 'page' AND id = ?", (made[3],)).fetchone()
    assert any(made[3] in str(h) for h in search.search(conn, Model(conn), "Book the room"))


def test_row_and_template_pages(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, AT)
    templates.make_tasks(conn, SETTINGS, r["top"], "Trial 2", None, {}, AT)
    tasks.update_task(conn, SETTINGS, made[2], at=AT, via="Browse tool", assignee_hours=20)
    tasks.update_task(conn, SETTINGS, made[3], at=AT, via="Browse tool", state="Closed")
    lib, m = Library(conn), Model(conn)
    page = template_pages.row_page(lib, m, r["top"], TODAY)
    assert "Product trial" in page and "Trees made from it" in page and "Trial 1" in page and "Trial 2" in page and "1 of 4 closed" in page and "0 of 4 closed" in page
    assert "Each task&#x27;s own" in page and f'tplrow:{r["prep"]}' in page
    row_page = template_pages.row_page(lib, m, r["prep_a"], TODAY)
    assert "Who follows it" in row_page and "1 task follows · 1 with its own values" in row_page and "own: assignee hours 20 h" in row_page
    assert "Template row" in row_page and "Trial preparation" in row_page
    window = template_pages.row_page(lib, m, r["window"], TODAY)
    assert "Starting notes" in window and "1 task follows · 1 closed" in window and "Urgent" in window


def test_the_template_page_lists_its_changes(trial):
    conn, r = trial
    _two_trees(conn, r)
    fresh = templates.new_template(conn, "Fresh", AT)
    page = template_pages.row_page(Library(conn), Model(conn), fresh, TODAY)
    assert "Changes" in page and "None yet" in page
    templates.apply_row(conn, SETTINGS, r["prep_a"], CHANGED, LATER)
    page = template_pages.row_page(Library(conn), Model(conn), r["top"], TODAY)
    assert "Change record prep · Assignee hours 30 h → 10 h" in page and "2 tasks changed" in page and "None yet" not in page
    assert "Changes" not in template_pages.row_page(Library(conn), Model(conn), r["prep_a"], TODAY)


def test_starting_notes_with_escaped_lines_stay_text():
    assert templates.page_body("\n\n# A heading\nwords\n\n") == "# A heading\nwords"
    assert templates.page_body("\\# not a heading") == "\\# not a heading"
