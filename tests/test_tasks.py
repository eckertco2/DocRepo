"""Creating and changing tasks: the status log, closing, parent links, labels and the capacity rows that follow."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import db, people, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.tasks import TaskError

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")


@pytest.fixture
def conn():
    c = db.connect_memory()
    people.add_person(c, "Me", hours=40)
    people.add_person(c, "Tom Becker", aliases=["Tom"], hours=40)
    people.add_label(c, "Safety", ["safety", "guard"])
    people.add_label(c, "Line 1", ["line 1"])
    yield c
    c.close()


def rows(conn, task_id):
    return conn.execute("SELECT person, date, hours FROM work_calendar WHERE task = ? ORDER BY date, person", (task_id,)).fetchall()


def test_create_a_task_and_a_subtask(conn):
    parent = tasks.create_task(conn, SETTINGS, title="Pump upgrade", at=AT, created_by="Excel import", labels=["line 1"])
    child = tasks.create_task(conn, SETTINGS, title="Order the seal", at=AT, created_by="C000001", parents=[parent],
                              assignees=["P002"], assignee_hours=4, start="2026-10-12", due="2026-10-16", labels=["Safety"])
    assert (parent, child) == ("T000001", "T000002")
    model = Model(conn)
    assert model.parents_of(child) == [parent]
    assert model.labels_of(child) == [("Safety", False), ("Line 1", True)]
    assert model.task(child).created == "2026-10-08"
    assert [(r["person"], r["date"], r["hours"]) for r in rows(conn, child)] == [
        ("P002", f"2026-10-{d}", 0.8) for d in (12, 13, 14, 15, 16)
    ]


def test_create_checks_its_values(conn):
    with pytest.raises(TaskError, match="title"):
        tasks.create_task(conn, SETTINGS, title=" ", at=AT, created_by="x")
    with pytest.raises(TaskError, match="no person"):
        tasks.create_task(conn, SETTINGS, title="A", at=AT, created_by="x", leads=["P009"])
    with pytest.raises(TaskError, match="no label"):
        tasks.create_task(conn, SETTINGS, title="A", at=AT, created_by="x", labels=["Quality"])
    with pytest.raises(TaskError, match="Repeat until"):
        tasks.create_task(conn, SETTINGS, title="A", at=AT, created_by="x", repeat_until="2027-01-01")
    with pytest.raises(ValueError):
        tasks.create_task(conn, SETTINGS, title="A", at=AT, created_by="x", due="2026-13-01")
    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_updates_go_into_the_status_log(conn):
    t = tasks.create_task(conn, SETTINGS, title="Rigging plan", at=AT, created_by="C000001", due="2026-10-14")
    later = datetime(2026, 10, 9, 9, 30)
    changes = tasks.update_task(conn, SETTINGS, t, at=later, via="C000002", state="In progress", due="2026-10-21",
                                assignees=["P002"], assignee_hours=6, urgent=True, current_status="Lift study done.")
    assert [(c.field, c.from_value, c.to_value) for c in changes] == [
        ("State", "Not started", "In progress"), ("Current status", None, "Lift study done."), ("Due", "2026-10-14", "2026-10-21"),
        ("Assignees", None, "Tom Becker"), ("Assignee hours", None, "6"), ("Urgent", "No", "Yes"),
    ]
    log = Model(conn).status_log_of(t)
    assert [(e.at, e.field, e.via) for e in log][0] == ("2026-10-09 09:30:00", "State", "C000002")
    assert tasks.update_task(conn, SETTINGS, t, at=later, via="C000003", due="2026-10-21") == []


def test_closing_records_the_day_and_reopening_clears_it(conn):
    t = tasks.create_task(conn, SETTINGS, title="Seal", at=AT, created_by="x", assignees=["P002"], assignee_hours=5,
                          start="2026-10-12", due="2026-10-16")
    tasks.update_task(conn, SETTINGS, t, at=datetime(2026, 10, 13, 17, 0), via="Browse tool", state="Closed")
    task = tasks.get_task(conn, t)
    assert (task.state, task.closed) == ("Closed", "2026-10-13")
    assert [r["date"] for r in rows(conn, t)] == ["2026-10-12", "2026-10-13"]  # days after closing are dropped
    tasks.update_task(conn, SETTINGS, t, at=datetime(2026, 10, 14, 8, 0), via="Browse tool", state="In progress")
    assert tasks.get_task(conn, t).closed is None
    assert len(rows(conn, t)) == 5


def test_clearing_the_recurrence_clears_repeat_until(conn):
    t = tasks.create_task(conn, SETTINGS, title="Weekly check", at=AT, created_by="x", recurrence="Weekly", repeat_until="2026-12-31")
    changes = tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", recurrence=None)
    assert [(c.field, c.to_value) for c in changes] == [("Recurrence", None), ("Repeat until", None)]
    with pytest.raises(TaskError, match="Repeat until"):
        tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", repeat_until="2027-01-01")


def test_unknown_fields_change_nothing(conn):
    t = tasks.create_task(conn, SETTINGS, title="A", at=AT, created_by="x")
    with pytest.raises(TaskError, match="Not task fields"):
        tasks.update_task(conn, SETTINGS, t, at=AT, via="x", title="B", colour="red")
    with pytest.raises(TaskError):
        tasks.update_task(conn, SETTINGS, t, at=AT, via="x", title="B", leads=["P404"])
    assert tasks.get_task(conn, t).title == "A"
    assert conn.execute("SELECT count(*) FROM status_log").fetchone()[0] == 0


def test_a_second_parent_and_no_loops(conn):
    a = tasks.create_task(conn, SETTINGS, title="Cost work", at=AT, created_by="x")
    b = tasks.create_task(conn, SETTINGS, title="Installation", at=AT, created_by="x")
    c = tasks.create_task(conn, SETTINGS, title="Overtime budget", at=AT, created_by="x", parents=[a])
    change = tasks.add_parent(conn, c, b, at=AT, via="Browse tool")
    assert (change.from_value, change.to_value) == ("Cost work", "Cost work; Installation")
    assert Model(conn).chains_of(c) == [[a, c], [b, c]]
    with pytest.raises(TaskError, match="under itself"):
        tasks.add_parent(conn, a, c, at=AT, via="Browse tool")
    with pytest.raises(TaskError, match="under itself"):
        tasks.add_parent(conn, a, a, at=AT, via="Browse tool")
    with pytest.raises(TaskError, match="already"):
        tasks.add_parent(conn, c, a, at=AT, via="Browse tool")
    tasks.remove_parent(conn, c, a, at=AT, via="Browse tool")
    tasks.remove_parent(conn, c, b, at=AT, via="Browse tool")
    assert c in [t.id for t in Model(conn).top_level()]
    assert [e.to_value for e in Model(conn).status_log_of(c)] == ["Cost work; Installation", "Installation", None]


def test_labels_inherit_unless_switched_off(conn):
    a = tasks.create_task(conn, SETTINGS, title="Upgrade", at=AT, created_by="x", labels=["Line 1"])
    b = tasks.create_task(conn, SETTINGS, title="Guards", at=AT, created_by="x", parents=[a], labels=["Safety"], inherit_labels=False)
    assert Model(conn).labels_of(b) == [("Safety", False)]
    tasks.update_task(conn, SETTINGS, b, at=AT, via="Browse tool", inherit_labels=True)
    assert Model(conn).labels_of(b) == [("Safety", False), ("Line 1", True)]


def test_ids_are_never_reused(conn):
    first = tasks.create_task(conn, SETTINGS, title="A", at=AT, created_by="x")
    conn.execute("DELETE FROM tasks WHERE id = ?", (first,))
    assert tasks.create_task(conn, SETTINGS, title="B", at=AT, created_by="x") == "T000002"


def test_reference_fields_and_plant_events(conn):
    """Release 5.9 (mods log round 2, M0034, M0028): reference field values by name, and the Plant event tick box."""
    t = tasks.create_task(conn, SETTINGS, title="Swap the seal", at=AT, created_by="C000001", references={"Work order #": " 48213 ", "Permit no.": ""})
    event = tasks.create_task(conn, SETTINGS, title="Spring outage", at=AT, created_by="C000002", start="2026-11-03", due="2026-11-14", plant_event=True)
    m = Model(conn)
    assert m.task(t).references == {"Work order #": "48213"} and not m.task(t).plant_event
    assert m.task(event).plant_event and [x.id for x in m.plant_events()] == [event]
    changes = tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", references={"Work order #": "48213", "Permit no.": "7781"}, plant_event=True)
    assert [(c.field, c.from_value, c.to_value) for c in changes] == [("Plant event", "No", "Yes"), ("Permit no.", None, "7781")]
    tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", references={"Work order #": ""})
    assert Model(conn).task(t).references == {"Permit no.": "7781"}
    log = [(e.field, e.from_value, e.to_value) for e in Model(conn).status_log_of(t)]
    assert ("Work order #", "48213", None) in log and ("Permit no.", None, "7781") in log
    with pytest.raises(TaskError, match="needs a name"):
        tasks.update_task(conn, SETTINGS, t, at=AT, via="Browse tool", references={" ": "1"})
