"""Glossaries (release 5.171, the design workspace's glossaries plan, decisions 802 to 806), without Qt: an import with every
column kept in order, its header row and tag column guessed; Import again's counts; two glossaries with the same tag; a
sheet past the row limit refused; Rename and Remove; a glossary's page, its pipes escaped, written once per change, and
Contents.md's line; the tag list from a glossary's tag column and a tagged label's page showing its row; and nothing of a
glossary read by ``Model``. The sheets are made up: P-204A, V-110 and Line 2 are nobody's plant."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from docrepo import glossaries, tagged
from docrepo import glossary_import as gi
from docrepo import tagged_import as ti
from docrepo.detail import Pages
from docrepo.model import Model
from docrepo.pages import CONTENTS_FILE, GLOSSARY_DIR, page_file, page_names, write_glossary_page, write_gone_page, write_pages

AT = datetime(2026, 11, 18, 21, 0)
EQUIPMENT = [
    ["Equipment list, made up for DocRepo's tests"],
    [],
    ["Line", "Tag No.", "Description", "Service", "Area"],
    ["Line 2", "P-204A", "Reactor feed pump A", "Feed | recycle", "North"],
    ["Line 2", "P-204B", "Reactor feed pump B", "Feed", "North"],
    ["Line 1", "V-110", "Knock-out drum", "", "South"],
    ["", "", "", "", ""],
    ["Line 1", "E-301", "Overhead condenser", "Cooling", "South"],
]


def write_csv(path: Path, rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return path


def imported(conn, tmp_path: Path, rows=EQUIPMENT, name: str = "Equipment") -> int:
    sheet = gi.read_rows(write_csv(tmp_path / f"{name}.csv", rows))
    header = gi.guess_header(sheet)
    p = gi.preview(conn, sheet, header, name, gi.guess_tag_column(sheet, header))
    assert not p.error, p.error
    return glossaries.create(conn, p.name, p.columns, p.tag_column, p.rows, f"{name}.csv", AT)


# ---- the import (decision 804) ----
def test_every_column_is_kept_in_order_with_its_header_and_tag_column_guessed(sample_conn, tmp_path):
    sheet = gi.read_rows(write_csv(tmp_path / "Equipment.csv", EQUIPMENT))
    header = gi.guess_header(sheet)
    assert header == 2  # the title row and the blank one above it aren't the header
    assert gi.columns_of(sheet, header) == ["Line", "Tag No.", "Description", "Service", "Area"]
    assert gi.guess_tag_column(sheet, header) == 1
    p = gi.preview(sample_conn, sheet, header, "Equipment", 1)
    assert not p.error and p.empty == 1
    assert p.rows[0] == ["Line 2", "P-204A", "Reactor feed pump A", "Feed | recycle", "North"]
    assert p.summary() == "4 rows in 5 columns, the tags in Tag No. · 1 empty row left out"
    gid = glossaries.create(sample_conn, p.name, p.columns, p.tag_column, p.rows, "Equipment.csv", AT)
    g = glossaries.get(sample_conn, gid)
    assert (g.name, g.columns, g.tag_column, g.tag_name, g.rows, g.source) == (
        "Equipment", ("Line", "Tag No.", "Description", "Service", "Area"), 1, "Tag No.", 4, "Equipment.csv")
    rows, total = glossaries.rows_of(sample_conn, gid)
    assert total == 4 and [r[1] for r in rows] == ["P-204A", "P-204B", "V-110", "E-301"]


def test_columns_without_a_header_or_with_the_same_one_are_named():
    rows = [["Area", "", "Area"], ["North", "x", "N", "extra"]]
    assert gi.columns_of(rows, 0) == ["Area", "Column 2", "Area (2)", "Column 4"]


def test_with_no_tag_shaped_column_there_is_no_tag_column():
    rows = [["Acronym", "Means"], ["MOC", "Management of change"], ["PSV", "Pressure safety valve"]]
    assert gi.guess_tag_column(rows, 0) is None
    rows = [["Item", "Notes"], ["V-110", "a"], ["P-204A", "b"], ["E-301", "c"]]
    assert gi.guess_tag_column(rows, 0) == 0  # the header says it ("item"), and its cells are tags


def test_a_name_is_needed_and_its_own(sample_conn, tmp_path):
    imported(sample_conn, tmp_path)
    sheet = gi.read_rows(write_csv(tmp_path / "x.csv", EQUIPMENT))
    assert "already" in gi.preview(sample_conn, sheet, 2, "equipment", 1).error
    assert "needs a name" in gi.preview(sample_conn, sheet, 2, "  ", 1).error
    with pytest.raises(glossaries.GlossaryError):
        glossaries.create(sample_conn, "EQUIPMENT", ["A"], None, [["a"]], "x.csv", AT)


def test_a_sheet_past_the_row_limit_is_refused_not_cut(sample_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(gi, "MAX_ROWS", 50)
    monkeypatch.setattr(ti, "MAX_ROWS", 50)
    rows = [["Tag", "Description"], *([f"V-{i}", f"Vessel {i}"] for i in range(51))]
    sheet = gi.read_rows(write_csv(tmp_path / "Long.csv", rows))
    p = gi.preview(sample_conn, sheet, 0, "Long", 0)
    assert "more than 50 rows" in p.error and not p.rows
    p = gi.preview(sample_conn, sheet[:51], 0, "Long", 0)  # 50 rows below the header: at the limit
    assert not p.error and len(p.rows) == 50


def test_the_limit_is_a_hundred_thousand_rows():
    assert gi.MAX_ROWS == 100_000


# ---- Import again (decision 804) ----
def test_import_again_counts_what_is_added_gone_and_changed(sample_conn, tmp_path):
    gid = imported(sample_conn, tmp_path)
    again = [row[:] for row in EQUIPMENT[2:]]
    again[1][2] = "Reactor feed pump A, rebuilt"  # P-204A changed
    del again[3]  # V-110 gone
    again.append(["Line 3", "K-401", "Air compressor", "Utility", "East"])  # added
    sheet = gi.read_rows(write_csv(tmp_path / "again.csv", again))
    p = gi.preview(sample_conn, sheet, 0, "", 1, against=glossaries.get(sample_conn, gid))
    assert not p.error
    assert (p.changes.added, p.changes.gone, p.changes.changed, p.changes.same) == (1, 1, 1, 2)
    glossaries.replace_rows(sample_conn, gid, p.columns, p.tag_column, p.rows, "again.csv", AT)
    g = glossaries.get(sample_conn, gid)
    assert g.name == "Equipment" and g.rows == 4 and g.source == "again.csv"


def test_a_column_added_counts_every_row_as_changed():
    old = glossaries.compare(["Tag"], [["V-110"]], 0, ["Tag", "Area"], [["V-110", "South"]], 0)
    assert (old.added, old.gone, old.changed) == (0, 0, 1)


# ---- two glossaries, Rename and Remove ----
def test_two_glossaries_with_the_same_tag_both_keep_it(sample_conn, tmp_path):
    a = imported(sample_conn, tmp_path, name="Equipment")
    b = imported(sample_conn, tmp_path, [["Tag", "Inspection"], ["P204A", "Due Mar 2027"]], name="Inspections")
    found = glossaries.rows_for_tag(sample_conn, tagged.key_of("P-204A"))
    assert [(r.glossary.id, r.cells[1] if r.glossary.id == a else r.cells[0]) for r in found] == [(a, "P-204A"), (b, "P204A")]
    assert glossaries.rows_for_tag(sample_conn, "P204B")[0].glossary.id == a
    assert glossaries.rows_for_tag(sample_conn, "X999") == []


def test_rename_and_remove(sample_conn, tmp_path):
    gid = imported(sample_conn, tmp_path)
    assert glossaries.rename(sample_conn, gid, "  Plant   equipment ") == "Plant equipment"
    with pytest.raises(glossaries.GlossaryError):
        glossaries.rename(sample_conn, gid, "")
    assert glossaries.remove(sample_conn, gid) == 4
    assert glossaries.get(sample_conn, gid) is None
    assert sample_conn.execute("SELECT count(*) FROM glossary_rows").fetchone()[0] == 0


def test_find_narrows_by_every_word_in_any_column_folded(sample_conn, tmp_path):
    gid = imported(sample_conn, tmp_path)
    assert [r[1] for r in glossaries.rows_of(sample_conn, gid, "feed north")[0]] == ["P-204A", "P-204B"]
    assert [r[1] for r in glossaries.rows_of(sample_conn, gid, "RECYCLE")[0]] == ["P-204A"]
    assert glossaries.rows_of(sample_conn, gid, "feed south") == ([], 0)
    assert glossaries.rows_of(sample_conn, gid, "100%")[1] == 0  # a % is a character, not a wildcard
    assert glossaries.fold("Réacteur  Pompe") == "reacteur pompe"


# ---- the pages (decision 806) ----
def test_a_glossary_s_page_is_its_table_written_once_per_change(sample_root, tmp_path):
    conn, root, fs = sample_root
    gid = imported(conn, tmp_path)
    assert write_glossary_page(conn, root, fs, gid) is True
    path = root.joinpath(*GLOSSARY_DIR, "Equipment.md")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Equipment\n") and "kept as data" in text and "not instructions" in text
    assert "| Line | Tag No. | Description | Service | Area |" in text
    assert "| Line 2 | P-204A | Reactor feed pump A | Feed \\| recycle | North |" in text
    assert "| Line 1 | V-110 | Knock-out drum |  | South |" in text
    assert write_glossary_page(conn, root, fs, gid) is False  # unchanged: not written again
    glossaries.rename(conn, gid, "Plant equipment")
    assert write_glossary_page(conn, root, fs, gid) is True and root.joinpath(*GLOSSARY_DIR, "Plant equipment.md").exists()
    assert write_gone_page(root, fs, "Equipment.md", "Equipment", "This glossary was renamed Plant equipment.") is True
    assert "renamed Plant equipment" in path.read_text(encoding="utf-8")


def test_page_names_are_safe_and_their_own():
    assert page_file('Pumps: "A/B"?') == "Pumps- -A-B--.md"
    assert page_file("CON") == "CON_.md" and page_file("  Line 2. ") == "Line 2.md"
    listed = [glossaries.Glossary(1, "A/B", ("x",), None, "", "2026-11-18"), glossaries.Glossary(2, "A-B", ("x",), None, "", "2026-11-18")]
    assert page_names(listed) == {1: "A-B.md", 2: "A-B (2).md"}


def test_contents_points_to_each_glossary_and_without_one_says_nothing(sample_root, tmp_path):
    conn, root, fs = sample_root
    write_pages(Model(conn), root, fs, AT.date(), AT, task_ids=[])
    assert "Glossaries:" not in (root / CONTENTS_FILE).read_text(encoding="utf-8")
    imported(conn, tmp_path)
    write_pages(Model(conn), root, fs, AT.date(), AT, task_ids=[])
    assert ("Glossaries: [Equipment](Views/Glossaries/Equipment.md) (4 rows). Each is a table the owner imported whole, with every "
            "column, in Views\\Glossaries.") in (root / CONTENTS_FILE).read_text(encoding="utf-8")


# ---- the tag list (decision 805) ----
def test_the_tag_column_adds_to_the_tag_list_and_its_page_shows_the_row(sample_conn, tmp_path):
    sheet = gi.read_rows(write_csv(tmp_path / "Equipment.csv", EQUIPMENT))
    p = gi.preview(sample_conn, sheet, 2, "Equipment", 1)
    glossaries.create(sample_conn, p.name, p.columns, p.tag_column, p.rows, "Equipment.csv", AT)
    assert gi.guess_description(p) == 2
    found = ti.preview(sample_conn, gi.tag_rows(p), gi.tag_plan(p, gi.guess_description(p)))
    assert not found.error and found.added == ["P-204A", "P-204B", "V-110", "E-301"]
    ti.run_import(sample_conn, found, "Equipment.csv", AT)
    m = Model(sample_conn)
    assert m.tagged.by_key["P204A"].description == "Reactor feed pump A"
    page = Pages(m, AT.date(), lambda c: "", conn=sample_conn).tagged_page("P204A")
    assert "In Equipment" in page and "Line 2" in page and "Feed | recycle" in page and "North" in page


# ---- the Model never reads them (decision 803) ----
def test_model_never_reads_a_glossary(sample_conn, tmp_path):
    imported(sample_conn, tmp_path)
    said: list[str] = []
    sample_conn.set_trace_callback(said.append)
    try:
        Model(sample_conn)
    finally:
        sample_conn.set_trace_callback(None)
    assert said and not [s for s in said if "glossaries" in s.lower() or "glossary_rows" in s.lower()]


def test_cells_are_kept_as_json_in_the_columns_order(sample_conn, tmp_path):
    gid = imported(sample_conn, tmp_path)
    r = sample_conn.execute("SELECT cells, folded FROM glossary_rows WHERE glossary = ? AND pos = 0", (gid,)).fetchone()
    assert json.loads(r["cells"]) == ["Line 2", "P-204A", "Reactor feed pump A", "Feed | recycle", "North"]
    assert r["folded"] == "line 2 | p-204a | reactor feed pump a | feed | recycle | north"
