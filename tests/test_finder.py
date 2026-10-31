"""The Task view's records and search (release 5.34; docrepo.overview and docrepo.finder), on the sample data and on
the large made-up project (docrepo.sample_large), with the search's timing."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pytest

from docrepo import db, file_search, finder, overview, search
from docrepo.model import Model
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample, read_sample, write_sample_files
from docrepo.sample_large import add_large_project, project_id

TODAY = date(2026, 10, 8)


@pytest.fixture(scope="module")
def large(tmp_path_factory):
    """A data root holding the sample data and the large project, with its files and search index."""
    root = tmp_path_factory.mktemp("large") / "DocRepoData"
    root.mkdir()
    fs = SafeFS([root])
    conn = db.connect(fs, root)
    data = add_large_project(read_sample())
    load_sample(conn, data)
    write_sample_files(conn, root, fs, data)
    search.rebuild(conn, root)
    yield conn, root
    conn.close()


def records_of(conn, root: Path, task_id: str) -> tuple[Model, list[overview.Record]]:
    m = Model(conn)
    return m, overview.build(m, root, task_id, overview.capture_texts(conn, [c.id for c in m.live_captures()]))


def titles(hits) -> list[str]:
    return [h.record.title for h in hits]


# ---- the records ----
def test_a_tasks_records_take_in_its_subtasks(sample_root):
    conn, root, _ = sample_root
    m, recs = records_of(conn, root, "T000001")
    by = {r.id: r for r in recs}
    assert overview.counts(recs) == {"all": 24, "file": 2, "email": 1, "note": 14, "task": 7}
    datasheet = by["D000001"]
    assert (datasheet.kind, datasheet.type, datasheet.source, datasheet.came, datasheet.sender) == (
        "file", "pdf", "Email attachment", "Email from Norvane Pumps (vendor)", "Norvane Pumps (vendor)")
    assert datasheet.path.endswith("attachments\\Impeller datasheet rev B.pdf") or datasheet.path.endswith("attachments/Impeller datasheet rev B.pdf")
    assert datasheet.copy.endswith("2026-09-10 Impeller datasheet rev B.pdf")  # its saved copy
    procedure = by["D000002"]
    assert (procedure.task, procedure.source, procedure.came) == ("T000008", "Tracked original", "a Note")
    assert procedure.path.startswith("\\\\fileserver\\eng\\")
    email = by["C000003"]
    assert email.kind == "email" and email.desc == "From Norvane Pumps (vendor) · 1 attachment" and "Delivery is confirmed" in email.text
    assert by["T000008"].kind == "task" and by["T000008"].desc.startswith("In progress · due 2026-10-30")


def test_file_types_come_from_names_and_links():
    assert overview.file_type("Pump curve rev C.pdf") == "pdf"
    assert overview.file_type("Tie-in list.XLSX") == "sheet"
    assert overview.file_type("Kickoff.pptx") == "slides"
    assert overview.file_type("photo.jpeg") == "picture"
    assert overview.file_type("readme") == "other"
    assert overview.file_type("Team site", "https://example.sharepoint.com/sites/x") == "link"


def test_text_typed_on_the_page_and_capture_blocks_are_read_apart():
    page = "# Plan\nTyped straight on the page.\n[Thu 8 Oct 2026 · 10:42 am · Note](capture:C000101)\nThe capture's words.\n" \
           "[File: Pump spec.docx](document:D000012)\n# Later\nMore typed text."
    blocks, sections = overview.page_texts(page)
    assert blocks == {"C000101": "The capture's words."}
    assert sections == [("Plan", "Typed straight on the page."), ("Later", "More typed text.")]


def test_grouping_by_date_names_the_days_and_months():
    assert overview.date_group("2026-10-08 09:00:00", TODAY)[1] == "Today"
    assert overview.date_group("2026-10-07 09:00:00", TODAY)[1] == "Yesterday"
    assert overview.date_group("2026-10-05 09:00:00", TODAY)[1] == "Earlier this week"
    assert overview.date_group("2026-09-29 09:00:00", TODAY)[1] == "Last week"
    assert overview.date_group("2026-09-10 09:00:00", TODAY)[1] == "September 2026"


def test_overview_recent_mixes_opened_and_added(sample_root):
    conn, root, _ = sample_root
    _, recs = records_of(conn, root, "T000001")
    recent = overview.recent(recs, [("D000002", "2026-10-08 09:00:00", "open")], TODAY)
    assert [(x.record.id, x.why) for x in recent] == [("D000002", "opened today"), ("D000001", "added on 10 Sep")]


# ---- reading the box ----
def test_typed_filters_turn_into_filters_once_a_space_follows(large):
    conn, root = large
    m, recs = records_of(conn, root, project_id(conn))
    f = finder.Filters()
    subtasks = [(t, m.task(t).title) for t in overview.family(m, project_id(conn))]
    senders = {r.sender for r in recs if r.sender}
    typed = finder.take_filters("type:pdf in:vendor from:tom since:1 sep before:last week hydro", f, subtasks, senders, TODAY)
    assert typed.rest == "hydro" and typed.changed
    assert m.task(typed.scope).title == "Vendor selection"
    assert f.types == {"pdf"} and f.senders == {"Tom Becker"}
    assert f.since == date(2026, 9, 1) and f.before == date(2026, 9, 28)
    still = finder.take_filters("pump type:pd", finder.Filters(), subtasks, senders, TODAY)
    assert still.rest == "pump type:pd" and not still.changed and still.hint.startswith("Type a type")
    ext = finder.Filters()
    assert finder.take_filters(".xlsx tie ", ext, subtasks, senders, TODAY).rest == "tie " and ext.types == {"sheet"}
    unknown = finder.take_filters("type:banana ", finder.Filters(), subtasks, senders, TODAY)
    assert unknown.rest == "type:banana " and not unknown.changed


def test_quotes_and_minus():
    assert finder.terms('pump "seal flush" -rev') == (["pump", "seal flush"], ["rev"])
    assert finder.terms("type:pd pump") == (["pump"], [])


def test_dates_look_back_from_today():
    assert finder.read_day("1 sep", TODAY) == date(2026, 9, 1)
    assert finder.read_day("dec", TODAY) == date(2025, 12, 1)  # December is still to come, so last year's
    assert finder.read_day("sep 15", TODAY) == date(2026, 9, 15)
    assert finder.read_day("30d", TODAY) == date(2026, 9, 8)
    assert finder.read_day("last month", TODAY) == date(2026, 9, 1)
    assert finder.read_day("banana", TODAY) is None


# ---- matching ----
def test_one_slip():
    assert finder.one_slip("isometirc", "isometric")  # two letters swapped
    assert finder.one_slip("cuve", "curve") and finder.one_slip("curves", "curve") and finder.one_slip("curbe", "curve")
    assert not finder.one_slip("survey", "curve") and not finder.one_slip("isomet", "isometric")


def test_names_win_and_the_newest_revision_comes_first(large):
    conn, root = large
    _, recs = records_of(conn, root, project_id(conn))
    files = [r for r in recs if r.kind == "file"]
    top = titles(finder.find(files, ["pump", "cur"]))[:3]
    assert top[0] == "Pump curve rev C.pdf" and sorted(top) == ["Pump curve rev A.pdf", "Pump curve rev B.pdf", "Pump curve rev C.pdf"]
    assert titles(finder.find(files, ["scope", "wor"]))[0] == "Scope of work v3.docx"
    assert titles(finder.find(files, ["pump", "cuve"]))[0] == "Pump curve rev C.pdf"  # a slip
    assert titles(finder.find(files, ["isometirc"]))[0].startswith("Isometric ")
    assert not any(t.startswith("Survey photo") for t in titles(finder.find(files, ["curve"])))  # a slip keeps its first letter


def test_short_words_match_only_at_word_starts(large):
    conn, root = large
    _, recs = records_of(conn, root, project_id(conn))
    found = titles(finder.find(recs, ["tie", "in", "list"]))
    assert found and all("tie" in t.lower() or "list" in t.lower() for t in found[:5])
    assert not finder.has_word("line 2 debottleneck", "in")
    assert finder.has_word("tie-in list", "in")


def test_left_out_words_and_phrases(large):
    conn, root = large
    _, recs = records_of(conn, root, project_id(conn))
    assert not finder.find(recs, ["pump", "curve"], ["rev"])
    phrase = finder.find(recs, ["seal flush"])
    assert phrase and all("seal flush" in (h.record.n_title + h.record.n_desc + h.record.n_text) for h in phrase)


def test_the_second_tier_finds_only_what_needs_the_files_text(large):
    conn, root = large
    _, recs = records_of(conn, root, project_id(conn))
    m = Model(conn)
    texts = {k: overview.fold(v) for k, v in overview.file_texts(conn, m, [r.id for r in recs if r.kind == "file"]).items()}
    assert any(v.startswith("Revision") or v[:1].isupper() for v in overview.file_texts(conn, m, list(texts)).values())  # as written
    first = {h.record.id for h in finder.find(recs, ["hydrotest"])}
    second = finder.find(recs, ["hydrotest"], texts=texts)
    assert second and all(h.second and h.in_text and h.record.kind == "file" for h in second)
    assert not first & {h.record.id for h in second}


def test_filters_keep_what_they_name(large):
    conn, root = large
    _, recs = records_of(conn, root, project_id(conn))
    f = finder.Filters(types={"pdf"})
    assert {r.type for r in recs if f.keep(r) and r.kind == "file"} == {"pdf"}
    f = finder.Filters(senders={"Tom Becker"})
    kept = [r for r in recs if f.keep(r)]
    assert kept and {r.kind for r in kept} == {"email", "file"} and all(r.sender == "Tom Becker" for r in kept)
    f = finder.Filters(since=date(2026, 10, 1))
    assert all(r.day >= "2026-10-01" for r in recs if f.keep(r))


def test_highlights_snippets_and_matched_lines():
    assert finder.highlights("Pump curve rev C.pdf", ["pump", "cur"]) == [(0, 4), (5, 8)]
    assert finder.highlights("Line 2 tie-in list", ["in"]) == [(11, 13)]  # not the "in" of Line
    assert finder.highlights("Isometric 1179.pdf", [], ["isometric"]) == [(0, 9)]
    assert finder.snippet("a" * 80 + " the seal flush plan here", ["seal"]).startswith("…")
    lines = finder.matched_lines("one\ntwo\nseal flush\nfour\nfive\nsix\nseal again", ["seal"])
    assert lines == [(1, "two", False), (2, "seal flush", True), (3, "four", False), (-1, "…", False), (5, "six", False), (6, "seal again", True)]


def test_did_you_mean_only_when_it_finds_something(large):
    conn, root = large
    _, recs = records_of(conn, root, project_id(conn))
    finds = lambda words: bool(finder.find(recs, words))  # noqa: E731
    assert finder.suggestion(["isometirc"], recs, finds) is None or finder.suggestion(["isometirc"], recs, finds) == "isometric"
    assert finder.suggestion(["pump", "cuve", "zzzz"], recs, finds) is None


# ---- speed (the success target: no lag you can see) ----
def test_the_first_tier_keeps_up_with_typing_on_the_large_project(large):
    conn, root = large
    m, recs = records_of(conn, root, project_id(conn))
    assert overview.counts(recs)["file"] >= 500
    times = []
    for query in ("pump curve", "seal flush", "tie in list", "isometric", "control narrative", "scope of work", "vendor bid"):
        for i in range(1, len(query) + 1):
            words, neg = finder.terms(query[:i])
            start = time.perf_counter()
            finder.find(recs, words, neg)
            times.append(time.perf_counter() - start)
    times.sort()
    assert times[int(len(times) * 0.95)] < 0.025, f"95th percentile {times[int(len(times) * 0.95)] * 1000:.1f} ms"


def test_file_search_is_quick_on_the_large_project(large):
    """File search (release 5.42, decision 214): every task's files once, built as it opens, and keeping up with typing."""
    conn, root = large
    m = Model(conn)
    start = time.perf_counter()
    recs = file_search.records(conn, m, root)
    built = time.perf_counter() - start
    assert built < 1.0, f"built in {built * 1000:.0f} ms"
    assert sum(r.kind == "file" for r in recs) >= 500
    assert len({(r.kind, r.id) for r in recs}) == len(recs)
    times = []
    for query in ("pump curve", "seal flush", "tie in list", "isometric", "vendor bid"):
        for i in range(1, len(query) + 1):
            words, neg = finder.terms(query[:i])
            start = time.perf_counter()
            finder.find(recs, words, neg)
            times.append(time.perf_counter() - start)
    times.sort()
    assert times[int(len(times) * 0.95)] < 0.05, f"95th percentile {times[int(len(times) * 0.95)] * 1000:.1f} ms"


def test_the_records_of_the_large_project_are_quick_to_build(large):
    conn, root = large
    pid = project_id(conn)
    start = time.perf_counter()
    m = Model(conn)
    overview.build(m, root, pid, overview.capture_texts(conn, [c.id for c in m.live_captures()]))
    assert time.perf_counter() - start < 0.5
