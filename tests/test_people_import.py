"""Import people (release 5.151, decisions 658 to 662), with no Qt: reading a .csv or an .xlsx as text, the columns, each kind
of line, matching by email then by name, an update filling in and a change ticked or not, and the caps. Over the sample
data, with made-up people and example.com addresses."""
from __future__ import annotations

import logging
from datetime import datetime

import pytest

from docrepo import people
from docrepo import people_import as pi
from docrepo.excel_import import WorkbookError
from docrepo.model import Model

AT = datetime(2026, 11, 15, 9, 30)


def csv_file(tmp_path, text: str, name: str = "people.csv", encoding: str = "utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def preview_of(conn, rows: list[list[str]]) -> pi.Preview:
    return pi.preview(Model(conn), pi.Table(rows))


def by_row(p: pi.Preview) -> dict[int, pi.Line]:
    return {x.row: x for x in p.lines}


# ---- the columns (decision 658) ----
def test_the_columns_are_found_by_name_case_and_spaces_aside():
    found, left = pi.find_columns(["  NAME ", "e mail", "Phone", "Role", "", "group", "ALIASES", "Notes"])
    assert found == {"name": 0, "email": 1, "role": 3, "group": 5, "aliases": 6}
    assert left == ["Phone", "Notes"]  # an empty header is nobody's column


@pytest.mark.parametrize(("header", "read"), [
    (["Name"], ["Name"]),
    (["Name", "Email"], ["Name", "Email"]),
    (["Role", "Name"], ["Name", "Role"]),
    (["Name", "Group", "Aliases"], ["Name", "Group", "Aliases"]),
    (["Name", "Email", "Role", "Group", "Aliases"], ["Name", "Email", "Role", "Group", "Aliases"]),
])
def test_each_column_read_when_the_file_has_it(sample_conn, header, read):
    p = preview_of(sample_conn, [header, ["Lena Fischer" if h == "Name" else "" for h in header]])
    assert p.columns_words() == f"Read: {', '.join(read)}."
    assert p.lines[0].kind == pi.NEW and (p.lines[0].email, p.lines[0].role, p.lines[0].group, p.lines[0].aliases) == ("", "", "", [])


def test_other_columns_are_left_alone_and_said(sample_conn):
    p = preview_of(sample_conn, [["Name", "Phone", "Email", "Email", "Office"], ["Lena Fischer", "555-0100", "lena.fischer@example.com",
                                                                                 "other@example.com", "B2"]])
    assert p.columns_words() == "Read: Name, Email. Left alone: Phone, Email (a second one), Office."
    assert p.lines[0].email == "lena.fischer@example.com"  # the first Email column


def test_a_file_without_a_name_column_is_refused(sample_conn):
    with pytest.raises(WorkbookError, match="no Name column"):
        preview_of(sample_conn, [["Full name", "Email"], ["Lena Fischer", "lena.fischer@example.com"]])
    with pytest.raises(WorkbookError, match="first row is empty"):
        preview_of(sample_conn, [["", ""], ["Lena Fischer", "lena.fischer@example.com"]])


# ---- each kind of line (decision 659) ----
def test_each_kind_of_line(sample_conn):
    p = preview_of(sample_conn, [
        ["Name", "Email", "Role", "Group"],
        ["Lena Fischer", "lena.fischer@example.com", "Lead planner", "Maintenance"],  # 2: nobody here
        ["Tom Becker", "tom.becker@example.com", "Lead planner", "Maintenance"],  # 3: his role differs
        ["Priya Shah", "priya.shah@example.com", "Reliability engineer", "Engineering"],  # 4: all as DocRepo has it
        ["", "nobody@example.com", "Buyer", ""],  # 5: no name
        ["Omar Haddad", "omar.haddad.example.com", "", ""],  # 6: not an email
        ["", "", "", ""],  # 7: a blank row, not a line
        ["Lena Fischer", "", "", ""],  # 8: row 2 again
    ])
    lines = by_row(p)
    assert sorted(lines) == [2, 3, 4, 5, 6, 8]
    assert [(n, lines[n].kind, lines[n].ticked) for n in sorted(lines)] == [
        (2, pi.NEW, True), (3, pi.UPDATE, True), (4, pi.SAME, False), (5, pi.PROBLEM, False), (6, pi.PROBLEM, False), (8, pi.PROBLEM, False)]
    assert lines[2].words() == "lena.fischer@example.com · Lead planner · Maintenance"
    assert lines[3].words() == "Role: Planner → Lead planner"
    assert lines[4].words() == "Nothing to change"
    assert lines[5].problem == "It has no name."
    assert lines[6].problem == "“omar.haddad.example.com” isn't an email address."
    assert lines[8].problem == "Row 2 is for the same person."
    assert p.summary() == "6 rows: 1 new, 1 update, 1 the same, 3 problems."
    assert [x.row for x in p.ticked] == [2, 3]


def test_a_name_or_an_email_that_matches_two_people_is_a_problem(sample_conn):
    people.add_person(sample_conn, "Tom Ortiz", aliases=["Tom"])
    people.add_person(sample_conn, "Pat Shah", email="PRIYA.SHAH@example.com")
    lines = by_row(preview_of(sample_conn, [["Name", "Email"], ["tom", ""], ["Priya", "priya.shah@example.com"]]))
    assert lines[2].kind == pi.PROBLEM and lines[2].problem == "Its name matches 2 people: Tom Becker and Tom Ortiz."
    assert lines[3].kind == pi.PROBLEM and lines[3].problem == "Its email matches 2 people: Priya Shah and Pat Shah."


def test_two_rows_for_one_person(sample_conn):
    lines = by_row(preview_of(sample_conn, [
        ["Name", "Email"],
        ["Tom Becker", ""],  # 2: Tom, by name
        ["Thomas", "tom.becker@example.com"],  # 3: Tom again, by email
        ["Lena Fischer", "lena.fischer@example.com"],  # 4: new
        ["Lena Fisher", "LENA.FISCHER@example.com"],  # 5: row 4's email
        ["Omar Haddad", "omar.haddad@example.com"],  # 6: new
        ["omar  haddad", ""],  # 7: row 6's name, case and spaces aside
        ["Priya Shah", "omar.haddad@example.com"],  # 8: Priya by name, with row 6's email
    ]))
    assert {n: (x.kind, x.problem) for n, x in lines.items() if x.kind == pi.PROBLEM} == {
        3: (pi.PROBLEM, "Row 2 is for the same person."), 5: (pi.PROBLEM, "Row 4 is for the same person."),
        7: (pi.PROBLEM, "Row 6 is for the same person."), 8: (pi.PROBLEM, "Row 6 is for the same person.")}


# ---- matching (decision 660) ----
def test_matched_by_email_first_case_aside(sample_conn):
    lines = by_row(preview_of(sample_conn, [["Name", "Email", "Role"], ["Thomas Becker", "TOM.BECKER@EXAMPLE.COM", "Planner"],
                                            ["Tom Becker", "priya.shah@example.com", ""]]))
    assert (lines[2].person, lines[2].by, lines[2].kind) == ("P003", "email", pi.SAME)
    assert lines[2].words() == "DocRepo's Tom Becker, found by email · Nothing to change"
    assert (lines[3].person, lines[3].by) == ("P002", "email")  # the email wins over the name


def test_else_by_name_or_alias_case_and_spaces_aside(sample_conn):
    lines = by_row(preview_of(sample_conn, [["Name", "Email"], ["  mike   ORTIZ ", ""], ["TylerNguyen", ""], ["Thomas", "tom.b@example.com"],
                                            ["ps", ""], ["Dana Kowalski", "dana.kowalski@example.com"], ["MikeOrtiz", ""]]))
    assert [(lines[n].person, lines[n].by) for n in (2, 3, 4, 5)] == [("P004", "name"), ("P005", "name"), ("P003", "name"), ("P002", "name")]
    assert lines[2].name == "mike ORTIZ" and lines[2].kind == pi.SAME
    assert lines[4].changes == [pi.Change("email", "tom.becker@example.com", "tom.b@example.com")]  # no one has this email: by name
    assert (lines[6].kind, lines[6].person, lines[6].by) == (pi.NEW, None, "")
    assert lines[7].problem == "Row 2 is for the same person."


def test_a_retired_person_is_matched_and_stays_retired(sample_conn):
    line = preview_of(sample_conn, [["Name", "Role"], ["Rob", "Inspector"]]).lines[0]
    assert (line.person, line.kind, line.retired) == ("P007", pi.UPDATE, True)
    assert line.words() == "DocRepo's Rob Lee, found by name · Role filled in: Inspector · stays retired"


# ---- an update (decision 661) ----
def test_an_update_fills_in_and_changes_only_when_ticked(sample_conn):
    p = preview_of(sample_conn, [
        ["Name", "Email", "Role", "Group", "Aliases"],
        ["Todd", "todd.brandt@example.com", "Electrician", "maintenance", "Todd B.; Toddy"],  # 2: Todd has nothing yet
        ["Tom Becker", "", "Lead planner", "", "Tom; Tommy"],  # 3: a change, an alias added, an empty email not clearing his
        ["Tyler Nguyen", "tyler.n@example.com", "Senior buyer", "", ""],  # 4: unticked below
    ])
    lines = by_row(p)
    assert [c.words() for c in lines[2].changes] == ["Email filled in: todd.brandt@example.com", "Role filled in: Electrician",
                                                     "Group filled in: Maintenance"]  # the group as DocRepo spells it
    assert lines[2].added_aliases == ["Todd B.", "Toddy"]
    assert lines[3].words() == "Role: Planner → Lead planner · Aliases added: Tommy"
    lines[4].ticked = False
    assert pi.run_import(sample_conn, p, AT) == "0 people added, 2 updated, 1 left out."
    m = Model(sample_conn)
    todd, tom, tyler = m.people["P006"], m.people["P003"], m.people["P005"]
    assert (todd.email, todd.role, todd.group, todd.aliases) == ("todd.brandt@example.com", "Electrician", "Maintenance", ["Todd B.", "Toddy"])
    assert (tom.email, tom.role, tom.group, tom.aliases) == ("tom.becker@example.com", "Lead planner", "Maintenance", ["Tom", "Thomas", "Tommy"])
    assert (tyler.email, tyler.role) == ("tyler.nguyen@example.com", "Buyer")  # unticked: nothing changed
    assert todd.added_note.startswith("Added on 2026-10-07 by Parse and populate")  # an update leaves the person's note as it was


def test_nobody_is_removed_retired_or_cleared(sample_conn):
    before = {p.id: (p.name, p.email, p.role, p.group, p.aliases, p.status, p.hours) for p in Model(sample_conn).people.values()}
    p = preview_of(sample_conn, [["Name", "Email", "Role", "Group", "Aliases"], ["Priya Shah", "", "", "", ""], ["Rob Lee", "", "", "", ""],
                                 ["Lena Fischer", "", "", "", ""]])
    assert [x.kind for x in p.lines] == [pi.SAME, pi.SAME, pi.NEW]
    assert pi.run_import(sample_conn, p, AT) == "1 person added, 0 updated, 2 already the same."
    after = {q.id: (q.name, q.email, q.role, q.group, q.aliases, q.status, q.hours) for q in Model(sample_conn).people.values()}
    assert {k: v for k, v in after.items() if k in before} == before


def test_new_people_are_added_with_their_fields(sample_conn):
    p = preview_of(sample_conn, [["Name", "Email", "Role", "Group", "Aliases"],
                                 ["Lena Fischer", "Lena.Fischer@example.com", "Lead planner", "purchasing", "Lena; LF; lena fischer; Lena"]])
    assert p.lines[0].aliases == ["Lena", "LF"]  # each once, without the name itself
    assert pi.run_import(sample_conn, p, AT) == "1 person added, 0 updated."
    lena = next(x for x in Model(sample_conn).people.values() if x.name == "Lena Fischer")
    assert (lena.email, lena.role, lena.group, lena.aliases, lena.status, lena.hours) == (
        "Lena.Fischer@example.com", "Lead planner", "Purchasing", ["Lena", "LF"], "active", None)
    assert lena.added_note == "Added on 2026-11-15 by Import people. Hours aren't set yet."


def test_the_import_is_one_transaction(sample_conn, monkeypatch):
    p = preview_of(sample_conn, [["Name", "Role"], ["Lena Fischer", "Lead planner"], ["Tom Becker", "Lead planner"]])
    count = sample_conn.execute("SELECT count(*) FROM people").fetchone()[0]

    def refused(*args, **kwargs):
        raise people.PeopleError("refused")

    monkeypatch.setattr(people, "update_person", refused)
    with pytest.raises(people.PeopleError):
        pi.run_import(sample_conn, p, AT)
    assert sample_conn.execute("SELECT count(*) FROM people").fetchone()[0] == count  # Lena's add was rolled back


def test_the_log_has_counts_only(sample_conn, caplog):
    p = preview_of(sample_conn, [["Name", "Email"], ["Lena Fischer", "lena.fischer@example.com"], ["Tom Becker", ""], ["", "x"]])
    with caplog.at_level(logging.INFO):
        pi.run_import(sample_conn, p, AT)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "people import: 1 added, 0 updated, 1 the same, 1 left out" in logged
    assert not any(word in logged for word in ("Lena", "Fischer", "Becker", "example.com", "people.csv"))


# ---- reading the file (decision 662) ----
TEXT = "Name,Email,Role\nZoë Müller,zoe.muller@example.com,Planerin\nJosé Peña,jose.pena@example.com,Técnico\n"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252"])
def test_csv_in_utf8_and_windows_1252(tmp_path, encoding):
    table = pi.read_file(csv_file(tmp_path, TEXT, encoding=encoding))
    assert table.rows == [["Name", "Email", "Role"], ["Zoë Müller", "zoe.muller@example.com", "Planerin"],
                          ["José Peña", "jose.pena@example.com", "Técnico"]]
    assert not table.cut


def test_csv_with_semicolons_tabs_and_quoted_cells(tmp_path):
    assert pi.read_file(csv_file(tmp_path, "Name;Email;Aliases\nLena Fischer;lena@example.com;\"Lena; LF\"\n")).rows[1] == [
        "Lena Fischer", "lena@example.com", "Lena; LF"]
    assert pi.read_file(csv_file(tmp_path, "Name\tRole\nLena Fischer\tLead planner, nights\n", "tabs.csv")).rows[1] == [
        "Lena Fischer", "Lead planner, nights"]


def test_a_cell_holding_a_formula_is_never_a_value(sample_conn, tmp_path):
    table = pi.read_file(csv_file(tmp_path, 'Name,Email,Role\nLena Fischer,lena@example.com,"=HYPERLINK(""x"",""y"")"\n'))
    line = pi.preview(Model(sample_conn), table).lines[0]
    assert (line.kind, line.problem) == (pi.PROBLEM, "Its Role is a formula (it starts with =), and a formula's text is never read.")


def test_an_xlsx_is_read_as_values_from_its_first_sheet_or_the_one_picked(sample_conn, tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    first = book.active
    first.title = "Contacts"
    first.append(["Name", "Email", "Role", "Group"])
    first.append(["Lena Fischer", "lena.fischer@example.com", "=UPPER(\"planner\")", 4410])
    other = book.create_sheet("Contractors")
    other.append(["Name", "Email"])
    other.append(["Omar Haddad", "omar.haddad@example.com"])
    path = tmp_path / "people.xlsx"
    book.save(path)
    assert pi.sheets(path) == ["Contacts", "Contractors"]
    rows = pi.read_file(path).rows
    # The formula has no value kept (openpyxl wrote it, Excel never calculated it), and its text isn't one; a number is text.
    assert rows == [["Name", "Email", "Role", "Group"], ["Lena Fischer", "lena.fischer@example.com", "", "4410"]]
    assert pi.read_file(path, "Contractors").rows == [["Name", "Email"], ["Omar Haddad", "omar.haddad@example.com"]]
    line = pi.preview(Model(sample_conn), pi.read_file(path)).lines[0]
    assert (line.kind, line.role, line.group) == (pi.NEW, "", "4410")


def test_files_that_cannot_be_read(tmp_path):
    with pytest.raises(WorkbookError, match="isn't a .csv or an .xlsx"):
        pi.sheets(tmp_path / "people.txt")
    with pytest.raises(WorkbookError, match="can't be opened"):
        pi.read_file(tmp_path / "missing.csv")
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a workbook")
    with pytest.raises(WorkbookError, match="can't be read as an Excel workbook"):
        pi.sheets(bad)


# ---- the caps (decision 662) ----
def test_at_most_5000_rows_are_read(tmp_path):
    rows = "".join(f"Person {i},p{i}@example.com\n" for i in range(pi.MAX_ROWS))
    exactly = pi.read_file(csv_file(tmp_path, "Name,Email\n" + rows + "\n\n", "exactly.csv"))
    assert (len(exactly.rows), exactly.cut) == (pi.MAX_ROWS + 1, False)  # blank rows after them aren't more
    over = pi.read_file(csv_file(tmp_path, "Name,Email\n" + rows + "One more,more@example.com\n", "over.csv"))
    assert (len(over.rows), over.cut) == (pi.MAX_ROWS + 1, True)


def test_at_most_200_characters_a_cell(sample_conn):
    lines = by_row(preview_of(sample_conn, [["Name", "Role", "Notes"], ["Lena Fischer", "R" * 200, "N" * 900], ["Omar Haddad", "R" * 201, ""]]))
    assert lines[2].kind == pi.NEW  # a long cell in a column left alone doesn't matter
    assert (lines[3].kind, lines[3].problem) == (pi.PROBLEM, "Its Role is longer than 200 characters.")


def test_a_huge_cell_is_cut_as_it_is_read(tmp_path):
    table = pi.read_file(csv_file(tmp_path, "Name,Notes\nLena Fischer," + "x" * 50_000 + "\n"))
    assert len(table.rows[1][1]) == pi.MAX_CELL * 5
