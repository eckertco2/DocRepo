"""Tagged labels (release 5.79, the tagged labels plan, items 102 to 105): the matching rules, the kept words and
mentions, the glossary's import and export, the owner's own changes, search, Task.md and the pages. Every tag here is made up."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import search, tagged
from docrepo import tagged_import as ti
from docrepo.config import Settings
from docrepo.detail import Pages
from docrepo.model import Model
from docrepo.pages import Pages as MdPages
from docrepo.save import CaptureDraft, FileRow, save_capture
from docrepo.tagged import Finder, Label, words_of

AT = datetime(2026, 10, 8, 9, 0)
GLOSSARY = [Label(1, "V-110", "V110", aliases=("feed drum", "D-10")), Label(2, "P-204A", "P204A"), Label(3, "P-204B", "P204B"),
            Label(4, "E-12", "E12"), Label(5, "FIC-2210", "FIC2210"), Label(6, "F-301", "F301", aliases=("CT fan 1",)), Label(7, "PT-101", "PT101")]
NAMES = {lb.id: lb.label for lb in GLOSSARY}


def found(text: str) -> list[str]:
    return [f"{h.written}={NAMES[h.label]}" for h in Finder(GLOSSARY).find(text)]


# ---- the matching rules (decisions 368 to 370) ----
def test_a_label_is_found_however_its_parts_are_joined():
    assert found("V-110, V110, v-110, V_110, V–110 and V 110") == ["V-110=V-110", "V110=V-110", "v-110=V-110", "V_110=V-110", "V–110=V-110", "V 110=V-110"]
    assert found("FIC2210 and FIC-2210") == ["FIC2210=FIC-2210", "FIC-2210=FIC-2210"]


def test_a_space_joins_parts_only_between_capitals():
    assert found("See page 101, and p 101. Also v 110.") == []
    assert found("PT 101 and F 301") == ["PT 101=PT-101", "F 301=F-301"]


def test_a_short_tag_needs_capitals_and_no_space():
    assert found("E-12 is down. e12? E12, e-12 and E 12.") == ["E-12=E-12", "E12=E-12"]
    assert found("D-10 and d-10") == ["D-10=V-110"]  # a short alias too


def test_a_tag_inside_a_longer_one_is_not_found():
    assert found("AV-110, V-1100, V-110A and 22-PT-101") == ["PT-101=PT-101"]


def test_a_pair_and_a_suffix():
    assert found("Seals for P-204A/B, and P204 B runs rough.") == ["P-204A=P-204A", "/B=P-204B", "P204 B=P-204B"]
    assert found("P-204 and P-204C") == []  # P-204A is its own label, not P-204
    assert found("P-204A/C/B") == ["P-204A=P-204A", "/B=P-204B"]  # each letter after a slash; P-204C isn't a label


def test_word_aliases_match_as_whole_words_in_any_case():
    assert found("The Feed  Drum is full; ct fan 1 tripped; the feed drummer") == ["Feed  Drum=V-110", "ct fan 1=F-301"]


def test_words_of_keeps_every_tag_like_run_once_with_its_count():
    words = words_of("Seal faces for P-204A/B, P204 B and the 22-PT-101 loop; page 101; FEED V 110 OK; P204 B")
    assert words == {"P-204A/B": 1, "P204 B": 2, "22-PT-101": 1, "FEED V 110 OK": 1}
    f = Finder(GLOSSARY)
    # Every tag the text has is in its runs, so a glossary change needs only them (decision 377).
    assert sorted(NAMES[h.label] for w in words for h in f.find_tags(w)) == ["P-204A", "P-204B", "P-204B", "PT-101", "V-110"]


@pytest.mark.parametrize("alias, ok", [("1001", False), ("10-01", False), ("D-10", True), ("feed drum", True)])
def test_an_alias_of_only_digits_is_refused(alias, ok):
    assert (not tagged.only_digits(alias)) is ok


# ---- the glossary in docs.db, kept current ----
def import_csv(conn, tmp_path, text, name="tags.csv", keep=False):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    rows = ti.read_rows(path)
    plan = ti.Plan(ti.guess_header(rows), ti.propose(rows, ti.guess_header(rows)), keep)
    p = ti.preview(conn, rows, plan)
    return p, ti.run_import(conn, p, name, AT)


TAGS = ("Tag No.,Service,Other names,Area\nV-110,Feed surge drum,feed drum; D-10,Area 2\nR-101,Reactor 1,,Area 1\n"
        "P-204A,Charge pump A,charge pump,Area 2\nP-204B,Charge pump B,charge pump,Area 2\nV110,Feed surge drum,,Area 2\n,,,\n"
        "XV-1001,Feed isolation valve,1001,Area 2\n")


def test_the_import_guesses_columns_and_says_what_it_will_do(sample_root, tmp_path):
    conn, _, _ = sample_root
    path = tmp_path / "tags.csv"
    path.write_text(TAGS, encoding="utf-8")
    rows = ti.read_rows(path)
    assert ti.propose(rows, 0) == ["label", "description", "aliases", "skip"]
    p = ti.preview(conn, rows, ti.Plan(0, ti.propose(rows, 0)))
    assert p.added == ["V-110", "R-101", "P-204A", "P-204B", "XV-1001"]
    assert p.merged == ["V110 is V-110 written another way: kept as its alias"]
    assert p.refused == ['The alias "charge pump": P-204A and P-204B both have it',
                         'XV-1001\'s alias "1001": only digits, so it would match every such number']
    assert p.empty == 1 and not tagged.read_labels(conn)  # nothing written yet


def test_importing_again_merges_and_removes_nothing(sample_root, tmp_path):
    conn, _, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    tagged.edit_label(conn, tagged.read_labels(conn)[0].id, "Feed surge drum", ["feed drum", "D-10", "V110", "TIC-2216"])
    again = "Tagged label,Tagged label description,Tagged label aliases\nV-110,Feed drum (vessel),old feed drum\nTIC-2216,Jacket temperature,\n"
    p, said = import_csv(conn, tmp_path, again, "updated.csv")
    assert p.added == ["TIC-2216"] and p.changed == [("V-110", "Feed surge drum", "Feed drum (vessel)")]
    assert p.aliases_added == [("V-110", "old feed drum")]
    assert p.merged == ["TIC-2216 was an alias of V-110: it's a label of its own now, and V-110 loses the alias"]
    labels = {lb.label: lb for lb in tagged.read_labels(conn)}
    assert set(labels) == {"V-110", "R-101", "P-204A", "P-204B", "XV-1001", "TIC-2216"}  # nothing removed
    assert labels["V-110"].aliases == ("feed drum", "D-10", "V110", "old feed drum") and labels["V-110"].description == "Feed drum (vessel)"
    assert said.startswith("Imported updated.csv: 1 added, 1 description differed, 1 alias added.")


def test_keep_docrepos_descriptions(sample_root, tmp_path):
    conn, _, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    import_csv(conn, tmp_path, "Tag,Description\nV-110,Something else\n", "b.csv", keep=True)
    assert next(lb for lb in tagged.read_labels(conn) if lb.label == "V-110").description == "Feed surge drum"


def test_an_xlsx_and_a_semicolon_csv_are_read(tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Tags"
    for row in (["Tag", "Description"], ["V-110", "Feed surge drum"], [2210, "Just a number"]):
        book.active.append(row)
    book.save(tmp_path / "tags.xlsx")
    assert ti.workbook_sheets(tmp_path / "tags.xlsx") == ["Tags"]
    assert ti.read_rows(tmp_path / "tags.xlsx", "Tags") == [["Tag", "Description"], ["V-110", "Feed surge drum"], ["2210", "Just a number"]]
    (tmp_path / "semi.csv").write_bytes("Tag;Beschreibung\nV-110;Behälter\n".encode("cp1252"))
    assert ti.read_rows(tmp_path / "semi.csv") == [["Tag", "Beschreibung"], ["V-110", "Behälter"]]


def test_what_is_already_indexed_is_matched_when_the_glossary_comes(sample_root, tmp_path):
    conn, _, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    m = Model(conn)
    r101 = next(lb for lb in m.tagged.labels.values() if lb.label == "R-101")
    assert [(u.kind, u.id) for u in tagged.uses_of(m, r101)] == [("document", "D000002")]  # its extracted text


def test_a_saved_capture_is_matched_at_once_and_its_words_kept(sample_root, tmp_path):
    conn, root, fs = sample_root
    import_csv(conn, tmp_path, TAGS)
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="Seal faces for P-204A/B are late. V110 alarmed twice, and TIC-2216 reads high."),
                 datetime(2026, 10, 8, 15, 0))
    m = Model(conn)
    cid = max(m.captures)
    assert [(lb.label, x.n if x else 0) for lb, x in m.tagged.item("capture", cid)] == [("P-204A", 1), ("P-204B", 1), ("V-110", 1)]
    # TIC-2216 isn't in the glossary yet; adding it finds it from the kept words, with no text read again.
    assert ("capture", cid, "TIC-2216") in {(r["kind"], r["id"], r["word"]) for r in conn.execute("SELECT * FROM tagged_words")}
    tagged.add_label(conn, "TIC-2216", AT, "Jacket temperature")
    assert "TIC-2216" in [lb.label for lb, _ in Model(conn).tagged.item("capture", cid)]


def test_text_on_a_task_is_found_on_its_notes_page_and_counts_for_the_task(sample_root, tmp_path):
    conn, root, fs = sample_root
    import_csv(conn, tmp_path, TAGS)
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="The feed drum level is high.", task="T000008"), datetime(2026, 10, 8, 15, 0))
    m = Model(conn)
    v110 = next(lb for lb in m.tagged.labels.values() if lb.label == "V-110")
    assert ("page", "T000008") in [(u.kind, u.id) for u in tagged.uses_of(m, v110)]
    assert ("V-110", 1) in [(lb.label, n) for lb, n in tagged.task_tags(m, "T000008")]


def test_a_tasks_own_fields_are_read_as_they_are(sample_root, tmp_path):
    conn, _, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    conn.execute("UPDATE tasks SET description = 'Swap the seals on P-204B first.' WHERE id = 'T000007'")
    m = Model(conn)
    assert ("P-204B", 1) in [(lb.label, n) for lb, n in tagged.task_tags(m, "T000007")]
    pb = next(lb for lb in m.tagged.labels.values() if lb.label == "P-204B")
    assert ("task", "T000007") in [(u.kind, u.id) for u in tagged.uses_of(m, pb)]


def test_the_owners_own_changes_outlive_a_rebuild(sample_root, tmp_path):
    conn, root, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    tagged.choose(conn, "document", "D000002", "R101", "removed", AT)
    tagged.choose(conn, "document", "D000002", "V110", "added", AT)
    search.rebuild(conn, root)
    m = Model(conn)
    assert [(lb.label, x) for lb, x in m.tagged.item("document", "D000002")] == [("V-110", None)]
    assert [lb.label for lb in m.tagged.removed("document", "D000002")] == ["R-101"]
    tagged.choose(conn, "document", "D000002", "R101", None, AT)  # Put back
    assert "R-101" in [lb.label for lb, _ in Model(conn).tagged.item("document", "D000002")]


def test_a_discarded_capture_mentions_nothing(sample_root, tmp_path):
    conn, root, fs = sample_root
    import_csv(conn, tmp_path, TAGS)
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="XV-1001 closes on high level."), datetime(2026, 10, 8, 15, 0))
    cid = max(Model(conn).captures)
    conn.execute("UPDATE captures SET discarded = '2026-10-08 16:00' WHERE id = ?", (cid,))
    m = Model(conn)
    xv = next(lb for lb in m.tagged.labels.values() if lb.label == "XV-1001")
    assert tagged.uses_of(m, xv) == []


def test_adding_and_editing_check_what_they_are_given(sample_root, tmp_path):
    conn, _, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    with pytest.raises(tagged.TaggedError, match="V-110 is in the glossary already, and V 110 is it written another way"):
        tagged.add_label(conn, "V 110", AT)
    v110 = next(lb for lb in tagged.read_labels(conn) if lb.label == "V-110")
    with pytest.raises(tagged.TaggedError, match="is R-101's already"):
        tagged.edit_label(conn, v110.id, "", ["R-101"])
    with pytest.raises(tagged.TaggedError, match="only digits"):
        tagged.edit_label(conn, v110.id, "", ["110"])


# ---- search, Task.md, the pages, export ----
def test_search_names_a_tag_however_typed_and_finds_what_mentions_it(sample_root, tmp_path):
    conn, _, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    results = search.search(conn, Model(conn), "r101")
    assert [(r.group, r.id) for r in results] == [("Tagged label", "R101"), ("Document", "D000002")]
    assert [r.title for r in search.search(conn, Model(conn), "P-204") if r.group == "Tagged label"] == ["P-204A", "P-204B"]
    assert [r.title for r in search.search(conn, Model(conn), "feed drum") if r.group == "Tagged label"] == ["V-110"]


def test_task_md_lists_a_tasks_tagged_labels_only_once_there_is_a_glossary(sample_root, tmp_path):
    conn, _, _ = sample_root
    t = Model(conn).task("T000001")
    assert "Tagged labels" not in MdPages(Model(conn), AT.date(), AT).task_page(t)
    import_csv(conn, tmp_path, TAGS)
    holders = Model(conn).document_holders("D000002")
    page = MdPages(Model(conn), AT.date(), AT).task_page(Model(conn).task(holders[0]))
    assert "| Labels |" in page and "| Tagged labels | R-101 (1) |" in page
    assert page.index("| Labels |") < page.index("| Tagged labels |")


def test_the_pages_show_chips_and_a_labels_page_lists_its_mentions(sample_root, tmp_path):
    conn, _, _ = sample_root
    import_csv(conn, tmp_path, TAGS)
    pages = Pages(Model(conn), AT.date(), lambda c: "", conn=conn)
    doc = pages.document_page("D000002")
    assert 'href="tagged:R101"' in doc and "taggedrm:document:D000002:R101" in doc and "taggedadd:document:D000002" in doc
    page = pages.tagged_page("R101")
    assert "Reactor 1" in page and "D000002 · Document" in page and "<b>R-101</b>" in page
    holder = Model(conn).document_holders("D000002")[0]
    assert 'href="tagged:R101"' in pages.task_page(holder, __import__("docrepo.detail", fromlist=["PageState"]).PageState(details=True))


def test_export_writes_a_csv_in_exports(sample_root, tmp_path):
    conn, root, fs = sample_root
    import_csv(conn, tmp_path, TAGS)
    text = ti.export_csv(conn)
    assert text.splitlines()[:3] == ["Tagged label,Tagged label description,Tagged label aliases", "P-204A,Charge pump A,",
                                     "P-204B,Charge pump B,"]
    assert "V-110,Feed surge drum,feed drum; D-10; V110" in text
    path = ti.save_export(fs, root, text, AT)
    assert path.parent == root / "Exports" and path.name == "2026-10-08 0900 Tagged labels.csv"
    assert ti.save_export(fs, root, text, AT).name == "2026-10-08 0900 Tagged labels (2).csv"  # never over an earlier one


def test_the_import_reads_a_long_list_quickly(sample_root, tmp_path):
    import time

    conn, _, _ = sample_root
    lines = ["Tag,Description"] + [f"PT-{n},Pressure {n}" for n in range(10000, 30000)]
    start = time.perf_counter()
    p, _ = import_csv(conn, tmp_path, "\n".join(lines) + "\n")
    assert len(p.added) == 20000 and time.perf_counter() - start < 20
    assert tagged.Finder(tagged.read_labels(conn)).find("PT-12345 and PT 29999") and FileRow  # noqa: B015


def test_a_captures_words_count_once_though_its_block_is_on_the_notes_page(sample_root, tmp_path):
    from docrepo import notes_page

    conn, root, fs = sample_root
    import_csv(conn, tmp_path, TAGS)
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="V-110 runs hot.", task="T000008",
                 files=[FileRow("Level sheet", "https://example.com/level", "The level readings.")]), datetime(2026, 10, 8, 15, 0))
    m = Model(conn)
    cid = max(m.captures)
    assert cid in notes_page.capture_ids(m.pages["T000008"])  # its block is on the page
    assert "V-110" not in tagged.page_text(m.pages["T000008"])  # and the page's own text leaves it out
    assert ("V-110", 1) in [(lb.label, n) for lb, n in tagged.task_tags(m, "T000008")]


def test_spellings_show_how_a_label_is_found():
    assert tagged.spellings("V-110") == ["V-110", "V110", "V 110"]
    assert tagged.spellings("E-12") == ["E-12", "E12"]  # a short tag isn't found with a space
    assert tagged.spellings("FLARE") == ["FLARE"]
