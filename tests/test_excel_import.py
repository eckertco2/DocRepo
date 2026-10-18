"""The one-time import of the project list from Excel, over the sample data and a made-up workbook."""
from __future__ import annotations

import hashlib
from datetime import date, datetime

import pytest
from sample_workbook import make_workbook

from docrepo import excel_import as xi
from docrepo.captures import read_content
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.stories import Stories

TODAY = date(2026, 10, 18)
AT = datetime(2026, 10, 18, 10, 0)


@pytest.fixture
def workbook(tmp_path):
    return make_workbook(tmp_path / "projects.xlsx")


def plan_for(path):
    rows = xi.read_sheet(path, "PROJECTS")
    header = xi.guess_header_row(rows)
    return rows, xi.Plan(xi.propose(rows, header), header)


def test_reading_the_workbook_and_proposing_a_mapping(workbook):
    assert xi.sheet_names(workbook) == ["PROJECTS", "Notes"]
    rows, plan = plan_for(workbook)
    assert plan.header_row == 2  # the title row and a blank row come first
    assert [(c.header, c.field) for c in plan.columns] == [
        ("Project", "title"), ("Description", "description"), ("Status", "current_status"), ("Due date", "due"), ("Start", "start"),
        ("Owner", "leads"), ("Team", "assignees"), ("Category", "labels"), ("Strategic", "label"), ("Priority", "urgent"),
        ("Budget code", "extra")]
    assert plan.column_for("label").label == "Strategic" and plan.columns[0].samples[0] == "Boiler feedwater pump overhaul"


@pytest.mark.parametrize(("header", "values", "field"), [
    ("Project lead", ["Tom"], "leads"), ("Owner name", ["Tom"], "leads"), ("Kick-off", ["2026-10-01"], "start"),
    ("Line 1", ["x", "", "x"], "label"), ("Notes", ["Waiting"], "current_status"), ("Phase", ["Design"], "state"),
    ("Anything", [None, None], "ignore"), ("Cost centre", ["4410"], "extra"),
])
def test_guessing_fields_from_headers_and_values(header, values, field):
    assert xi.guess_field(header, values) == field


def test_the_preview(sample_conn, workbook):
    rows, plan = plan_for(workbook)
    p = xi.preview(rows, plan, Model(sample_conn), TODAY)
    by_title = {r.title: r for r in p.rows}
    assert [r.line for r in p.rows] == [4, 5, 6, 7, 8]  # Excel's row numbers; the empty and notes-only rows are left out
    boiler = by_title["Boiler feedwater pump overhaul"]
    assert boiler.fields == {"description": "Overhaul both feedwater pumps during the spring outage.\nBudget code: BC-114",
                             "current_status": "Vendor quote received; waiting on the PO.", "due": "2027-04-30", "start": "2027-03-01",
                             "urgent": True, "state": "In progress"}
    assert (boiler.leads, boiler.assignees, boiler.labels) == (["Priya Shah"], ["Mike Ortiz", "Tom"], ["Line 1", "Strategic"])
    assert by_title["Control room HVAC upgrade"].fields["due"] == "2027-03-31"  # "Q1 2027", read as Parse and populate reads it
    survey = by_title["Compressed air leak survey"]
    assert "Due date: TBD" in survey.fields["description"] and any("isn't a date" in x for x in survey.problems)
    assert survey.assignees == [] and any("Rob Lee is retired" in x for x in survey.problems)
    assert survey.labels == ["Line 1", "Line 2"] and survey.fields["urgent"] is False
    assert by_title["Reactor impeller upgrade"].skip.startswith("Already imported")
    assert (p.new_people, p.new_labels) == (["Dana Kim"], ["Strategic"])


def test_a_state_column(sample_conn, workbook):
    rows, plan = plan_for(workbook)
    status = next(c for c in plan.columns if c.header == "Status")
    status.field = "state"
    values = xi.state_values(rows, plan.header_row, status)
    assert ("Complete. Report filed.", 1, "Closed") in values and ("On hold until the budget is approved.", 1, "Parked") in values
    plan.state_map = {v: s for v, _, s in values}
    plan.state_map["Design review scheduled."] = "Not started"
    states = {r.title: r.fields["state"] for r in xi.preview(rows, plan, Model(sample_conn), TODAY).rows}
    assert states["Warehouse racking inspection"] == "Closed" and states["Control room HVAC upgrade"] == "Not started"


def test_the_mapping_is_checked(sample_conn, workbook):
    rows, plan = plan_for(workbook)
    plan.columns[0].field = "ignore"
    with pytest.raises(xi.WorkbookError, match="Title"):
        xi.preview(rows, plan, Model(sample_conn), TODAY)
    plan.columns[0].field = "title"
    plan.columns[1].field = "title"
    with pytest.raises(xi.WorkbookError, match="Only one column"):
        xi.preview(rows, plan, Model(sample_conn), TODAY)


def test_importing(sample_root, workbook):
    conn, root, fs = sample_root
    before = hashlib.sha256(workbook.read_bytes()).hexdigest()
    rows, plan = plan_for(workbook)
    found = xi.preview(rows, plan, Model(conn), TODAY)
    message = xi.run_import(conn, Settings(me="P001"), root, fs, found, AT, workbook.name)
    assert message == "Imported 4 tasks from Excel, added 1 person, 1 label. 1 row was skipped."
    assert hashlib.sha256(workbook.read_bytes()).hexdigest() == before  # the workbook is only read
    m = Model(conn)
    new = [t for t in m.tasks.values() if t.created_by == "Excel import" and t.created == "2026-10-18"]
    assert len(new) == 4 and all(not m.parents_of(t.id) for t in new)
    boiler = next(t for t in new if t.title == "Boiler feedwater pump overhaul")
    dana = next(p for p in m.people.values() if p.name == "Dana Kim")
    assert boiler.leads == ["P002"] and boiler.assignees == ["P004", "P003"] and boiler.urgent and boiler.labels == ["Line 1", "Strategic"]
    assert dana.added_note.startswith("Added on 2026-10-18 by the Excel import")
    story = Stories(m, TODAY, lambda c: read_content(root, m.captures[c]) or "").story(boiler.id)
    assert story[0].how == "import" and story[0].status == "Vendor quote received; waiting on the PO."
    assert (root / "Tasks" / boiler.id / "Task.md").exists()
    assert conn.execute("SELECT count(*) FROM work_calendar WHERE task = ?", (boiler.id,)).fetchone()[0] == 0  # no hours, no rows
    assert xi.last_import(conn) == {"at": "2026-10-18 10:00:00", "tasks": 4, "file": "projects.xlsx"}
    again = xi.preview(rows, plan, Model(conn), TODAY)
    assert not again.to_import and xi.run_import(conn, Settings(), root, fs, again, AT) == "Nothing to import: every row is skipped."


def test_a_workbook_that_cant_be_read(tmp_path):
    bad = tmp_path / "not a workbook.xlsx"
    bad.write_text("plain text", encoding="utf-8")
    with pytest.raises(xi.WorkbookError, match="can't be read"):
        xi.sheet_names(bad)


def test_dates_and_hours():
    assert xi._date(datetime(2027, 1, 5, 0, 0), TODAY) == "2027-01-05"
    assert xi._date(46388, TODAY) == "2027-01-01"  # a date stored as Excel's day number
    assert xi._date("2027-02-26", TODAY) == "2027-02-26" and xi._date("10/30/2026", TODAY) == "2026-10-30"
    assert xi._date("end of March", TODAY) == "2027-03-31" and xi._date("TBD", TODAY) is None
    assert (xi._hours(6), xi._hours("2.5 h"), xi._hours("lots")) == (6.0, 2.5, None)
