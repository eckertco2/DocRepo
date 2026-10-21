"""The browse tool's views over the sample data. The expected rows are the mockup's, from its page in a browser."""
from __future__ import annotations

from datetime import date

import pytest

from docrepo import views
from docrepo.model import Model
from docrepo.schedule import DueDate

TODAY = date(2026, 10, 8)


@pytest.fixture
def m(sample_conn):
    return Model(sample_conn)


def ids(nodes):
    return [n.id for n in views.walk(nodes)]


def test_the_task_tree_with_everything_expanded(m):
    assert ids(views.task_tree(m, views.TreeFilter())) == [
        "T000001", "T000008", "T000012", "T000015", "T000019", "T000009", "T000011", "T000002", "T000017", "T000018", "T000006",
        "T000010", "T000016"]


def test_the_task_tree_filters(m):
    with_closed = ids(views.task_tree(m, views.TreeFilter(closed=True, parked=True)))
    assert {"T000005", "T000007", "T000003", "T000004"} <= set(with_closed)
    no_routine = ids(views.task_tree(m, views.TreeFilter(routine=False)))
    assert "T000010" not in no_routine and "T000006" not in no_routine
    by_label = views.task_tree(m, views.TreeFilter(labels=("Safety",)))
    matched = {n.id: n.match for n in views.walk(by_label)}
    assert matched["T000002"] and matched["T000017"] and not matched.get("T000001", True)


def test_several_people_or_labels_match_any_of_them(m):
    """Mods log round 1 (M0018)."""
    def matching(**f):
        return {n.id for n in views.walk(views.task_tree(m, views.TreeFilter(**f))) if n.match}

    tom, mike = matching(people=("P003",)), matching(people=("P004",))
    assert tom and mike and tom != mike
    assert matching(people=("P003", "P004")) == tom | mike
    safety, line1 = matching(labels=("Safety",)), matching(labels=("Line 1",))
    assert matching(labels=("Safety", "Line 1")) == safety | line1
    assert matching(labels=("Safety", "Line 1"), people=("P003", "P004")) == (safety | line1) & (tom | mike)


def test_sorting_keeps_the_tree_and_sorts_each_level(m):
    """Mods log round 1 (M0015)."""
    tree = views.task_tree(m, views.TreeFilter())

    def levels(nodes):
        yield nodes
        for n in nodes:
            yield from levels(n.children)

    by_title = views.sort_tree(m, views.task_tree(m, views.TreeFilter()), "title", TODAY)
    assert sorted(ids(by_title)) == sorted(ids(tree))  # the same tasks, each still under its parent
    for level in levels(by_title):
        titles = [m.task(n.id).title.casefold() for n in level]
        assert titles == sorted(titles)
    assert [n.group for n in by_title] == list(range(len(by_title)))  # colour bands in the new order
    by_due = views.sort_tree(m, views.task_tree(m, views.TreeFilter()), "due", TODAY)
    soonest = [min((d.date for x in views.walk([n]) if (d := views.due_of(m.task(x.id), TODAY))), default=date.max) for n in by_due]
    assert soonest == sorted(soonest) and soonest[-1] == date.max  # undated last
    by_state = views.sort_tree(m, views.task_tree(m, views.TreeFilter(closed=True, parked=True)), "state", TODAY)
    order = [views.STATE_ORDER[m.task(n.id).state] for n in by_state]
    assert order == sorted(order)
    updated = views.last_updated(m)
    latest = [updated[n.id] for n in views.sort_tree(m, views.task_tree(m, views.TreeFilter()), "updated", TODAY)]
    assert latest == sorted(latest, reverse=True)
    assert ids(views.sort_tree(m, views.task_tree(m, views.TreeFilter()), "default", TODAY)) == ids(tree)


def test_a_pinned_task_shows_whatever_the_filters(m):
    tree = views.task_tree(m, views.TreeFilter(pin="T000007"))  # closed, so hidden without the pin
    assert "T000007" in ids(tree)


@pytest.mark.parametrize(("list_id", "rows"), [
    ("due", [("T000001", False), ("T000008", False), ("T000019", True), ("T000012", True)]),
    ("reminders", [("T000016", True), ("T000002", False), ("T000018", True), ("T000001", False), ("T000008", False), ("T000019", True)]),
    ("waiting", [("T000001", True), ("T000008", True), ("T000019", True), ("T000012", True), ("T000009", True), ("T000011", True),
                 ("T000002", False), ("T000017", True), ("T000018", True)]),
    ("mine", [("T000010", True), ("T000006", True), ("T000016", True)]),
    ("urgent", [("T000001", False), ("T000008", False), ("T000019", True)]),
    ("unplanned", [("T000001", False), ("T000008", False), ("T000019", True), ("T000002", False), ("T000017", True), ("T000016", True)]),
])
def test_lists_in_tree_form_match_the_mockup(m, list_id, rows):
    nodes = views.list_tree(m, views.LIST_IDS[list_id], TODAY, "P001")
    assert [(n.id, n.match) for n in views.walk(nodes)] == rows


def test_documents_in_tree_form(m):
    rows = [(n.kind, n.id) for n in views.walk(views.documents_tree(m))]
    assert rows == [("task", "T000001"), ("doc", "D000001"), ("task", "T000008"), ("doc", "D000002"), ("group", ""), ("doc", "D000003"),
                    ("doc", "D000004")]
    only = [(n.kind, n.id) for n in views.walk(views.documents_tree(m, "T000008"))]
    assert only == [("task", "T000001"), ("task", "T000008"), ("doc", "D000002")]


def test_view_counts(m):
    assert views.view_counts(m, TODAY, "P001") == {"unfiled": 3, "tasks": 13, "people": 6, "labels": 5, "docs": 4, "due": 2, "reminders": 3,
                                                   "waiting": 8, "mine": 3, "urgent": 1, "unplanned": 3, "discarded": 0, "today": 0}


def test_unfiled_rows_newest_first(m):
    rows = views.unfiled_rows(m, TODAY)
    assert [(r.id, r.source, r.saved) for r in rows] == [("C000023", "File path", "13:15"), ("C000022", "Typed", "11:30"), ("C000021", "Email", "10:05")]
    assert rows[2].sub == "C000021 · 1 document"


def test_agenda_groups_and_markdown(m):
    groups = views.agenda_groups(m, "T000010")
    assert [(name, [a.subject for a in items]) for name, items in groups] == [
        ("Reactor impeller upgrade", ["T000001"]), ("Q4 cost reduction", ["T000015"]), ("Holiday coverage schedule", ["T000016"]),
        ("Other topics", [None])]
    assert views.agenda_markdown(m, "T000010", TODAY) == (
        "## Business team meeting, Tue 13 Oct\n\n### Reactor impeller upgrade\n- Reactor impeller upgrade: Bring up the reactor impeller "
        "status at the next business team meeting.\n\n### Q4 cost reduction\n- Q4 overtime budget\n\n### Holiday coverage schedule\n"
        "- Holiday coverage schedule\n\n### Other topics\n- Ask whether the December shutdown dates are confirmed.\n")
    assert [a.subject for a in views.closed_items(m, "T000010")] == ["T000008"]
    assert views.current_target(m, None) == "T000010" and views.current_target(m, "P003") == "P003"


def test_add_to_agenda_lists_meetings_with_items_first(m):
    assert [t.id for t in views.meetings_for_menu(m, "T000008")] == ["T000010"]
    assert views.meetings_for_menu(m, "T000010") == []


def test_due_cells():
    from docrepo.model import load_tasks  # noqa: F401 - a Task is built below

    class T:
        state, closed, recurrence, repeat_until, start, deadline, created = "In progress", None, None, None, None, None, "2026-10-01"
        due = "2026-10-16"

    cell = views.due_cell(T(), TODAY)
    assert (cell.text, cell.days, cell.cls, cell.tip) == ("16 Oct · 8 d", "8 d", "", "Due Fri 16 Oct, in 8 d")
    T.due = "2026-10-05"
    assert views.due_cell(T(), TODAY).text == "3 d late" and views.due_cell(T(), TODAY).cls == "over"
    reminder = views.due_cell(T(), TODAY, DueDate(date(2026, 10, 7), "Reminder"))
    assert (reminder.text, reminder.tip) == ("1 d ago", "Reminder Wed 7 Oct, 1 d ago")
    assert views.due_cell(T(), TODAY, DueDate(date(2026, 10, 9), "Reminder")).text == "Tomorrow"
    assert not views.due_cell(T(), TODAY).deadline
    T.due, T.deadline = None, "2026-10-31"  # no Due: the deadline shows in its place, marked (M0003)
    cell = views.due_cell(T(), TODAY)
    assert (cell.text, cell.tip, cell.deadline) == ("31 Oct · 23 d", "Deadline Sat 31 Oct, in 23 d", True)


def test_collapse_and_expand_a_level(m):
    nodes = views.task_tree(m, views.TreeFilter())
    opened = views.expand_level(nodes, set())
    assert opened == {"T000001", "T000002"}
    deeper = views.expand_level(nodes, opened)
    assert deeper == {"T000001", "T000002", "T000008"}
    # Each expanded task none of whose subtasks is expanded closes: Installation, and Verification walkthrough readiness.
    assert views.collapse_level(nodes, deeper) == {"T000001"}
    assert views.collapse_level(nodes, {"T000001"}) == set()


def test_capacity_grid(sample_conn, m):
    from docrepo import capacity
    from docrepo.config import Settings

    capacity.rebuild_all(sample_conn, TODAY, Settings(me="P001"))
    weeks = views.capacity_weeks(TODAY)
    assert weeks[0] == date(2026, 10, 5) and len(weeks) == 9
    rows = {r.name: r for r in views.capacity_grid(sample_conn, m, weeks)}
    mike = rows["Mike Ortiz"].cells[2]  # week of 19 Oct
    assert (round(mike.hours, 1), mike.cls) == (32.5, "u3")
    assert rows["Todd"].cells[0].use is None and rows["Todd"].cells[0].cls == "u0"
    assert views.capacity_weeks(TODAY, 1)[0] == date(2026, 12, 7)


def test_label_tasks_mark_inherited_ones(m):
    tasks = dict(views.label_tasks(m, "Safety"))
    assert tasks["T000002"] is False and tasks["T000017"] is True
