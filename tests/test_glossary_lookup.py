"""The glossary lookup (release 5.172, the design workspace's glossaries plan, decisions 807 to 809), without Qt: the match
(every word, any column, case and accents aside, a tag however it's typed); the order; 50 listed; what Enter and Ctrl+C
copy; the last used first; how many places mention a row's tag; its hotkey last; and its budget. The Browse wheel's
NE, which needs Qt's list of commands, is in ``test_glossary_lookup_ui.py``. The glossaries are made up: P-204A, V-110 and Line 2 are nobody's plant."""
from __future__ import annotations

import json
from datetime import datetime

from docrepo import glossaries, hotkey, sample_scale, tagged, timings
from docrepo.config import Settings
from docrepo.glossaries import Glossary
from docrepo.model import Model
from docrepo.save import CaptureDraft, save_capture

AT = datetime(2026, 11, 19, 9, 0)
COLUMNS = ("Line", "Tag No.", "Description", "Service")
ROWS = [
    ["Line 2", "P-204A", "Reactor feed pump A", "Feed"],
    ["Line 2", "P-204B", "Reactor feed pump B", "Feed"],
    ["Line 1", "V-110", "Knock-out drum", ""],
    ["Line 1", "E-301", "Overhead condenser for P-204A's loop", "Cooling"],
    ["Line 3", "XP-2040", "Pump skid", "Drain"],
    ["Line 1", "TK-12", "Café water tank", "Utilités"],
]


def made(conn, rows=ROWS, columns=COLUMNS, tag: int | None = 1, name: str = "Equipment") -> Glossary:
    gid = glossaries.create(conn, name, columns, tag, rows, f"{name}.csv", AT)
    g = glossaries.get(conn, gid)
    assert g is not None
    return g


def tags(found) -> list[str]:
    return [f.cells[1] for f in found]


# ---- the match (decision 807) ----
def test_every_word_somewhere_in_any_column(sample_conn):
    g = made(sample_conn)
    found, total = glossaries.lookup(sample_conn, g, "feed pump line 2")
    assert tags(found) == ["P-204A", "P-204B"] and total == 2
    assert tags(glossaries.lookup(sample_conn, g, "drum line 1")[0]) == ["V-110"]
    assert glossaries.lookup(sample_conn, g, "drum line 2") == ([], 0)  # every word, not any


def test_case_and_accents_aside(sample_conn):
    g = made(sample_conn)
    assert tags(glossaries.lookup(sample_conn, g, "CAFE utilites")[0]) == ["TK-12"]
    assert tags(glossaries.lookup(sample_conn, g, "café")[0]) == ["TK-12"]


def test_a_tag_however_it_is_typed(sample_conn):
    g = made(sample_conn)
    for typed in ("p204a", "P-204A", "p 204a", "p.204a", "P204"):
        found, _ = glossaries.lookup(sample_conn, g, typed)
        assert found and found[0].cells[1] == "P-204A", typed
    assert tags(glossaries.lookup(sample_conn, g, "v110")[0]) == ["V-110"]


def test_percent_and_underscore_are_characters(sample_conn):
    g = made(sample_conn, rows=[["Line 1", "V-1", "50% open", ""], ["Line 1", "V-2", "500 open", ""], ["Line 1", "V_3", "x", ""]])
    assert tags(glossaries.lookup(sample_conn, g, "50%")[0]) == ["V-1"]
    assert tags(glossaries.lookup(sample_conn, g, "v_3")[0]) == ["V_3"]


# ---- the order (decision 807) ----
def test_the_tag_typed_first_then_tags_starting_with_it_then_the_rest(sample_conn):
    g = made(sample_conn)
    # E-301's description mentions P-204A, and comes earlier in no tier: the tag itself first, then the tag that starts
    # the same, then the row that only mentions it.
    assert tags(glossaries.lookup(sample_conn, g, "p-204a")[0]) == ["P-204A", "E-301"]
    # XP-2040 holds "p204" with its hyphen left out, so it's found too, last, in the sheet's order with E-301.
    assert tags(glossaries.lookup(sample_conn, g, "p-204")[0]) == ["P-204A", "P-204B", "E-301", "XP-2040"]
    # A cell starting with the first word comes before one that only holds it: XP-2040's "Pump skid" before nothing else,
    # the pumps' own tags not starting with "pump".
    assert tags(glossaries.lookup(sample_conn, g, "pump")[0]) == ["XP-2040", "P-204A", "P-204B"]


def test_nothing_typed_lists_the_sheet_in_its_order(sample_conn):
    g = made(sample_conn)
    found, total = glossaries.lookup(sample_conn, g, "")
    assert tags(found) == [r[1] for r in ROWS] and total == len(ROWS)


def test_fifty_are_listed_and_the_count_is_of_all(sample_conn):
    rows = [["Line 1", f"FT-{n:03d}", "Flow transmitter", ""] for n in range(120)]
    g = made(sample_conn, rows=rows)
    found, total = glossaries.lookup(sample_conn, g, "flow")
    assert len(found) == glossaries.LOOKUP_SHOWN == 50 and total == 120
    assert tags(found)[:2] == ["FT-000", "FT-001"]  # the sheet's order within a tier
    assert len(glossaries.lookup(sample_conn, g, "")[0]) == 50


# ---- what Enter and Ctrl+C copy (decision 807) ----
def test_enter_copies_the_tag_or_the_first_cell_and_ctrl_c_the_row(sample_conn):
    g = made(sample_conn)
    assert glossaries.tag_of(g, ROWS[0]) == "P-204A"
    assert glossaries.row_text(["Line 2", "P-204A", "Reactor  feed\npump", ""]) == "Line 2\tP-204A\tReactor feed pump\t"
    acronyms = made(sample_conn, rows=[["HAZOP", "Hazard and operability study"]], columns=("Term", "Meaning"), tag=None, name="Acronyms")
    assert glossaries.tag_of(acronyms, ["HAZOP", "Hazard and operability study"]) == "HAZOP"


def test_a_row_is_drawn_with_its_tag_first_and_bold(sample_conn):
    g = made(sample_conn)
    assert glossaries.shown_cells(g, ROWS[2]) == [("V-110", True), ("Line 1", False), ("Knock-out drum", False)]
    acronyms = made(sample_conn, rows=[["HAZOP", "Hazard study"]], columns=("Term", "Meaning"), tag=None, name="Acronyms")
    assert glossaries.shown_cells(acronyms, ["HAZOP", "Hazard study"]) == [("HAZOP", False), ("Hazard study", False)]


# ---- the last used first (decision 807) ----
def test_the_last_used_first_then_by_name(sample_conn):
    a = made(sample_conn, name="Acronyms")
    e = made(sample_conn, name="Equipment")
    i = made(sample_conn, name="Instruments")
    listed = glossaries.all_glossaries(sample_conn)
    assert [g.name for g in glossaries.by_recent(listed, [])] == ["Acronyms", "Equipment", "Instruments"]
    recent = glossaries.remember(glossaries.remember([], e.id), i.id)
    assert recent == [str(i.id), str(e.id)]
    assert [g.name for g in glossaries.by_recent(listed, recent)] == ["Instruments", "Equipment", "Acronyms"]
    assert glossaries.remember(recent, e.id) == [str(e.id), str(i.id)]
    assert [g.name for g in glossaries.by_recent(listed, ["999", str(a.id)])] == ["Acronyms", "Equipment", "Instruments"]


def test_its_settings_are_written_once_set(data_root, fs):
    st = Settings(me="P001")
    st.save(fs, data_root)
    saved = json.loads((data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert "glossary_recent" not in saved and "lookup_hotkey" not in saved
    st.glossary_recent, st.lookup_hotkey = ["3", "1"], "Ctrl+Alt+G"
    st.save(fs, data_root)
    back = Settings.load(data_root)
    assert back.glossary_recent == ["3", "1"] and back.lookup_hotkey == "Ctrl+Alt+G"


# ---- how many places mention a row's tag (decision 807) ----
def test_places_counts_as_the_tag_s_page_does(sample_root):
    conn, root, fs = sample_root
    for tag, description in (("P-204A", "Reactor feed pump A"), ("P-204B", "Reactor feed pump B"), ("V-110", "Knock-out drum")):
        tagged.add_label(conn, tag, AT, description)
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="Seal faces for P-204A/B are late. V110 alarmed twice."), AT)
    conn.execute("UPDATE tasks SET description = 'Swap the seals on P-204B first.' WHERE id = 'T000007'")
    m = Model(conn)
    hits = glossaries.task_hits(m)
    counted = {lb.label: glossaries.places_of(m, lb, hits) for lb in m.tagged.labels.values()}
    assert counted == {lb.label: len(tagged.uses_of(m, lb)) for lb in m.tagged.labels.values()}
    assert counted["P-204B"] >= 2 and counted["V-110"] >= 1  # the capture, and the task's own words


# ---- its hotkey (decision 808) ----
def test_its_hotkey_is_last_and_off_until_set():
    assert hotkey.HOTKEYS[-1][0] == "lookup_hotkey"
    assert hotkey.HOTKEY_IDS["progress_hotkey"] == 11 and hotkey.HOTKEY_IDS["lookup_hotkey"] == len(hotkey.HOTKEYS)
    assert Settings().lookup_hotkey == ""


# ---- fast enough to type against (decision 809) ----
def test_the_budget_s_glossary_is_made_up_and_the_same_each_time():
    rows = sample_scale.glossary_rows(500)
    assert rows == sample_scale.glossary_rows(500) and all(len(r) == len(sample_scale.GLOSSARY_COLUMNS) for r in rows)
    assert len({r[1] for r in rows}) == 500
    assert timings.BUDGET["lookup"].seconds == 0.05


def test_the_lookup_is_timed_on_20000_rows():
    x = timings._lookup(1)
    assert x.key == "lookup" and x.note.startswith("20,000 rows")
    assert x.seconds < 1.0  # the budget itself is the scale run's; this only says it ran
