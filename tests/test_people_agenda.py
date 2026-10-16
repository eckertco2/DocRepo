"""The people list, labels and agenda items."""
from __future__ import annotations

import pytest

from docrepo import agenda, db, people
from docrepo.agenda import AgendaError
from docrepo.model import Model
from docrepo.people import PeopleError


def test_people_keep_their_ids_through_changes():
    conn = db.connect_memory()
    me = people.add_person(conn, "Me", hours=40)
    tom = people.add_person(conn, "Tom Becker", aliases=["Tom", " ", "Thomas"])
    assert (me, tom) == ("P001", "P002")
    people.update_person(conn, tom, name="Thomas Becker", hours=32)
    people.update_person(conn, tom, status="retired")
    p = Model(conn).people[tom]
    assert (p.name, p.aliases, p.hours, p.status) == ("Thomas Becker", ["Tom", "Thomas"], 32, "retired")
    assert [x.id for x in Model(conn).active_people()] == [me]
    people.update_person(conn, tom, hours=None)
    assert Model(conn).people[tom].hours is None
    with pytest.raises(PeopleError):
        people.update_person(conn, tom, hours=-1)
    with pytest.raises(PeopleError):
        people.add_person(conn, "  ")


def test_labels_rename_and_retire():
    conn = db.connect_memory()
    people.add_label(conn, "Safety")
    assert Model(conn).labels[0].keywords == ["Safety"]
    with pytest.raises(PeopleError, match="already"):
        people.add_label(conn, "safety")
    people.update_label(conn, "SAFETY", new_name="Safety and health", keywords=["safety", "LOTO"])
    people.update_label(conn, "Safety and health", status="retired")
    label = Model(conn).labels[0]
    assert (label.name, label.keywords, label.status) == ("Safety and health", ["safety", "LOTO"], "retired")
    assert Model(conn).active_labels() == []


def test_agenda_items_open_and_close(sample_conn):
    item = agenda.add_item(sample_conn, subject="T000012", target="P002", note="Ask about the slings.", added="2026-10-08 15:00:00", added_by="C000026")
    model = Model(sample_conn)
    assert [a.subject for a in model.open_items_for("P002")] == ["T000012"]
    assert "P002" in model.agenda_targets()
    agenda.close_item(sample_conn, item, how="Discussed", closed="2026-10-09 09:00:00", closed_by="Agenda view")
    log = Model(sample_conn).status_log_of("T000012")
    assert [(e.field, e.from_value, e.to_value) for e in log[-2:]] == [("Agenda", None, "Priya Shah"), ("Agenda", "Priya Shah", "Discussed")]
    with pytest.raises(AgendaError, match="already closed"):
        agenda.close_item(sample_conn, item, how="Removed", closed="2026-10-09 09:01:00", closed_by="Agenda view")


def test_agenda_items_need_a_real_target_and_something_to_discuss(sample_conn):
    with pytest.raises(AgendaError, match="no agenda target"):
        agenda.add_item(sample_conn, subject="T000012", target="P099", note="", added="2026-10-08 15:00:00", added_by="x")
    with pytest.raises(AgendaError, match="task or a note"):
        agenda.add_item(sample_conn, subject=None, target="T000010", note=" ", added="2026-10-08 15:00:00", added_by="x")
    with pytest.raises(AgendaError, match="own agenda"):
        agenda.add_item(sample_conn, subject="T000010", target="T000010", note="", added="2026-10-08 15:00:00", added_by="x")
    with pytest.raises(AgendaError, match="Discussed or Removed"):
        agenda.close_item(sample_conn, 1, how="Done", closed="2026-10-08 15:00:00", closed_by="x")
