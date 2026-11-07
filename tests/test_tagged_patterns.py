"""Tag patterns and new tagged labels (release 5.80, the tagged labels plan's items 106 and 107, decisions 372 to 375 and
377): masks, Never a tag, suggested labels kept current, Add to glossary, Same as and Not a tag, the tester and Try on
everything, and the settings. Every tag and convention here is made up."""
from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

from docrepo import search, tagged
from docrepo import tagged_import as ti
from docrepo import tagged_masks as tm
from docrepo.config import Settings
from docrepo.db import get_state
from docrepo.detail import Pages
from docrepo.model import Model
from docrepo.pages import Pages as MdPages
from docrepo.save import CaptureDraft, save_capture
from docrepo.tagged import Finder, Label

AT = datetime(2026, 10, 8, 9, 0)
INSTRUMENT = tm.Pattern("Instrument tag", "XX[X][X]-####")
EQUIPMENT = tm.Pattern("Equipment tag", "X[X]-###[X]")


def spelled(mask: str, text: str, space: bool = False) -> list[tuple[str, str]]:
    c = tm.compile_mask(mask, space)
    return [(m.group(), tm.spell(m, c)) for m in c.regex.finditer(text)]


# ---- the mask language (decision 372) ----
def test_marks_are_never_required_and_a_new_label_is_spelled_as_the_mask_is():
    text = "FIC221, FIC-221, FIC_221, FIC–221 and fic221"
    assert spelled("XXX###", text) == [("FIC221", "FIC221"), ("FIC-221", "FIC221"), ("FIC_221", "FIC221"), ("FIC–221", "FIC221")]
    assert [s for _, s in spelled("XXX-###", text)] == ["FIC-221"] * 4
    assert spelled("XXX###", "FIC 221 and API 610") == []  # a space only with Allow a space
    assert spelled("XXX###", "FIC 221 and API 610", space=True) == [("FIC 221", "FIC221"), ("API 610", "API610")]


def test_optional_parts_quotes_literals_and_joiners():
    assert spelled("X[X]-###[X]", "P-204A, PT-101, P204 and PTX-101") == [("P-204A", "P-204A"), ("PT-101", "PT-101"), ("P204", "P-204")]
    assert spelled("XX[X][X]-####", "TIC2215, PDT_4410 and AB-12345") == [("TIC2215", "TIC-2215"), ("PDT_4410", "PDT-4410")]
    assert spelled("'XV'-####", "XV-1001, XV1001 and FV-1001") == [("XV-1001", "XV-1001"), ("XV1001", "XV-1001")]
    assert spelled("##-XX-###", "22-PT-101 and 22PT101") == [("22-PT-101", "22-PT-101"), ("22PT101", "22-PT-101")]
    assert spelled("TK-##/#", "TK-12/3 and TK-12") == [("TK-12/3", "TK-12/3")]
    assert spelled("XX ###", "AB 123 and AB123") == [("AB 123", "AB 123"), ("AB123", "AB 123")]  # the mask's own space


def test_a_mask_is_read_in_capitals_but_the_text_needs_them():
    assert spelled("xx-####", "TT-2215") == [("TT-2215", "TT-2215")]  # x is X
    assert spelled("v-###", "V-110 and v-110") == [("V-110", "V-110")]
    assert spelled("XX-####", "tt-2215") == []


def test_a_tag_inside_a_longer_run_isnt_found():
    assert spelled("XX-####", "ATT-2215, TT-22150 and TT-2215A") == []


@pytest.mark.parametrize("mask, why", [
    ("", "Type a mask"), ("XX", "needs a digit"), ("####", "needs a letter"), ("[X]#", "needs a letter (X) outside brackets"),
    ("X[X", "isn't closed"), ("X]#", "has no ["), ("X[]#", "brackets are empty"), ("[[X]]#", "inside brackets"),
    ("'XV-#", "quote ' isn't closed"), ("''X#", "nothing between the quotes"), ("-X#", "can't start or end"), ("X#_", "can't start or end"),
    ("X--#", "Two marks in a row"), ("X(#)", "can't hold"), ("X[X][X][X][X][X]#", "at most 4 optional"), ("X" * 30 + "###", "at most 32"),
])
def test_a_mask_that_cant_be_used_says_why(mask, why):
    with pytest.raises(tm.MaskError, match=why.replace("(", r"\(").replace(")", r"\)").replace("[", r"\[")):
        tm.parse(mask)


def test_examples_show_what_a_mask_means():
    assert tm.examples("XXX###") == "FTI204"
    assert tm.examples("XX[X][X]-####") == "FT-2041 to FTIC-2041"
    assert tm.examples("'XV'-####") == "XV-2041"
    assert all(tm.examples(mask) for mask, _ in tm.EXAMPLES)


def test_no_mask_can_hang_on_a_big_document():
    """The worst masks DocRepo allows, over half a megabyte of text made to make them try hardest at every place."""
    texts = ["-".join(["A"] * 250_000), "A1 " * 170_000, " ".join(["AAAAAAAA"] * 60_000), "-".join(["AB12"] * 100_000)]
    for mask in ("[X-][X-][X-][X-]X-#", "X[*]-[*]-[*]-[*]-#", "[*][*][*][*]*X#", "*[*]*[*]*[*]*[*]*X#"):
        for space in (False, True):
            c = tm.compile_mask(mask, space)
            for text in texts:
                start = time.perf_counter()
                sum(1 for _ in c.regex.finditer(text))
                assert time.perf_counter() - start < 3, (mask, space, text[:12])


# ---- Never a tag (decision 375) ----
def test_never_a_tag_is_whole_tags_or_starts():
    never = tm.Never(["API*", "abc-123", "ISO*"])
    assert "API610" in never and "ABC123" in never and "ISO-9001" in never and "AB12" not in never
    assert tm.never_of([" api* ", "API*", "", "*", "A*B", "ABC123"]) == ["API*", "ABC123"]
    assert tm.never_problem("*") and tm.never_problem("A*B") and tm.never_problem("API*") is None


def test_patterns_come_from_settings_leaving_out_one_with_no_mask():
    assert tm.patterns_of([{"name": "Instrument tag", "mask": "XX-####"}, {"name": "No mask"}, "XX", {"mask": " X-### ", "space": True}]) == [
        tm.Pattern("Instrument tag", "XX-####"), tm.Pattern("X-###", "X-###", True)]


# ---- the finder with patterns ----
GLOSSARY = [Label(1, "FIC-2210", "FIC2210"), Label(2, "V-110", "V110", aliases=("feed drum",)), Label(3, "TIC-2216", "TIC2216", status="suggested")]


def test_a_glossary_label_is_found_first_and_never_applies_to_patterns_only():
    f = Finder(GLOSSARY, [INSTRUMENT], ["FIC*", "API*"])
    hits = f.find_all("FIC2210 holds the feed; TIC-2216 reads high; FIC-2299 is new; API-6100 is a standard; the feed drum")
    assert [(h.written, h.how, h.label, h.spelled) for h in hits] == [
        ("FIC2210", "label", 1, ""), ("TIC-2216", "new", 3, "TIC-2216"), ("FIC-2299", "never", 0, "FIC-2299"),
        ("API-6100", "never", 0, "API-6100"), ("feed drum", "word", 2, "")]
    # find() keeps what has a row: the glossary's, and a suggested label's
    assert [h.label for h in f.find("FIC2210, TIC2216 and PDT-4410")] == [1, 3]
    assert [(h.spelled, h.label, h.pattern) for h in f.find_all("PDT-4410") if h.how == "new"] == [("PDT-4410", 0, "Instrument tag")]


def test_what_a_pattern_spells_as_a_glossary_labels_key_is_that_label():
    f = Finder([Label(1, "E-12", "E12")], [tm.Pattern("Short", "X##", space=True)])
    assert [(h.written, h.how, h.label) for h in f.find_all("E 12 is booked")] == [("E 12", "label", 1)]


def test_words_are_joined_across_a_slash_or_a_dot_so_a_mask_with_one_is_found_in_them():
    words = tagged.words_of("TK-12/3 is full; Rev.2 of P-204A/B; see page 4.5 and V-110. Next")
    assert words == {"TK-12/3": 1, "Rev.2": 1, "P-204A/B": 1, "V-110": 1}
    f = Finder([], [tm.Pattern("Tank", "XX-##/#")])
    assert [h.spelled for w in words for h in f.find_patterns(w)] == ["TK-12/3"]


# ---- suggested labels in docs.db (decisions 374 and 377) ----
def test_a_pair_a_pattern_finds_is_both_tags():
    """"P-204A/B" is P-204A and P-204B for a pattern too, as for a glossary label (decision 370): only a capital after the
    slash, each letter after one (A/B/C is three), and only when the mask allows that letter where the first one was."""
    f = Finder([], [EQUIPMENT])
    found = lambda text: [(h.written, h.how, h.spelled) for h in f.find_patterns(text)]  # noqa: E731
    assert found("Seal faces for P-204A/B are late.") == [("P-204A", "new", "P-204A"), ("/B", "new", "P-204B")]
    assert found("P-204A/b and P-204/B") == [("P-204A", "new", "P-204A"), ("P-204", "new", "P-204")]  # no capital, no letter
    assert found("P-204A/B/C") == [("P-204A", "new", "P-204A"), ("/B", "new", "P-204B"), ("/C", "new", "P-204C")]
    fixed = Finder([], [tm.Pattern("Tank", "XX-##'A'")])  # the mask's last letter is always A
    assert [(h.written, h.spelled) for h in fixed.find_patterns("TK-12A/B")] == [("TK-12A", "TK-12A")]
    known = Finder([Label(1, "P-204B", "P204B")], [EQUIPMENT], ["P-204A"])
    assert [(h.written, h.how, h.label) for h in known.find_all("P-204A/B")] == [("P-204A", "never", 0), ("/B", "pair", 1)]


def test_a_saved_pair_makes_both_suggestions(sample_root):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [EQUIPMENT], [])
    cid = save(conn, root, fs, "Seal faces for P-204A/B are late.")
    assert {"P-204A", "P-204B"} <= set(suggested(conn))  # with what the sample's own text has of that shape
    assert sorted(lb.label for lb, _ in Model(conn).tagged.item("capture", cid)) == ["P-204A", "P-204B"]
    found, _items = tagged.try_everything(conn, Model(conn), [EQUIPMENT], [])
    assert {"P-204A", "P-204B"} <= {t.label for t in found}


def suggested(conn) -> dict[str, tagged.Label]:
    return {lb.label: lb for lb in tagged.read_labels(conn) if lb.status == "suggested"}


def save(conn, root, fs, text, task=None):
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=text, task=task), datetime(2026, 10, 8, 15, 0))
    return max(Model(conn).captures)


def test_a_pattern_puts_a_new_label_on_what_mentions_it_at_once(sample_root):
    conn, root, fs = sample_root
    assert tagged.set_patterns(conn, [INSTRUMENT, EQUIPMENT], []) is not None
    assert set(suggested(conn)) == {"R-101"}  # the sample's own document mentions it
    cid = save(conn, root, fs, "TIC-2216 reads 4 °C high, and FIC221 is the old loop. PDT_4410 too.")
    m = Model(conn)
    assert [(lb.label, lb.status, x.how) for lb, x in m.tagged.item("capture", cid)] == [
        ("PDT-4410", "suggested", "new"), ("TIC-2216", "suggested", "new")]
    tic = suggested(conn)["TIC-2216"]
    assert tic.came == "pattern" and tic.pattern == "Instrument tag" and tic.added
    page = Pages(m, AT.date(), lambda c: "", conn=conn).capture_page(cid, "")
    assert 'class="tgn"' in page and "New: found by the Instrument tag pattern" in page and "&nbsp;new</span>" in page


def test_a_pattern_change_matches_the_kept_words_without_reading_any_file(sample_root, monkeypatch):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    cid = save(conn, root, fs, "TIC-2216 reads high; PDT_4410 too.")
    words = sorted(tuple(r) for r in conn.execute("SELECT kind, id, word, n FROM tagged_words"))

    def no(*_a, **_k):
        raise AssertionError("a file was read")
    monkeypatch.setattr(search, "read_content", no)
    monkeypatch.setattr(search, "extracted_text", no)
    monkeypatch.setattr(tagged, "item_texts", no)  # nor the search index: no glossary has word aliases here
    tagged.set_patterns(conn, [tm.Pattern("Instrument tag", "'P'XX-####")], [])
    assert sorted(tuple(r) for r in conn.execute("SELECT kind, id, word, n FROM tagged_words")) == words
    assert [lb.label for lb, _ in Model(conn).tagged.item("capture", cid)] == ["PDT-4410"]
    assert set(suggested(conn)) == {"PDT-4410"}


def test_items_indexed_together_change_the_glossarys_version_once(sample_root, monkeypatch):
    conn, _, _ = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    conn.execute("INSERT INTO task_pages (task, body, updated) VALUES ('T000007', 'PDT-4410 and TT-2215', ?), ('T000008', 'FT-3301 and PDT-4410', ?) "
                 "ON CONFLICT(task) DO UPDATE SET body = excluded.body", (AT.isoformat(), AT.isoformat()))
    calls = []
    real = tagged.glossary_changed
    monkeypatch.setattr(tagged, "glossary_changed", lambda c: (calls.append(1), real(c)))
    search.index_pages(conn, ["T000007", "T000008"])
    assert len(calls) == 1 and {"PDT-4410", "TT-2215", "FT-3301"} <= set(suggested(conn))
    assert conn.execute("SELECT count(*) FROM tagged_labels WHERE key = 'PDT4410'").fetchone()[0] == 1  # made once, met twice


def test_a_changed_mask_respells_and_a_removed_pattern_drops_its_suggestions(sample_root):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    cid = save(conn, root, fs, "TT-2215 and TIC-2216 read high.")
    assert set(suggested(conn)) == {"TT-2215", "TIC-2216"}
    tagged.set_patterns(conn, [tm.Pattern("Temperature", "'T'XX-####")], [])
    assert set(suggested(conn)) == {"TIC-2216"} and suggested(conn)["TIC-2216"].pattern == "Temperature"  # renamed with its pattern
    tagged.set_patterns(conn, [], [])
    assert suggested(conn) == {} and Model(conn).tagged.item("capture", cid) == []


def test_never_a_tag_removes_a_suggestion_everywhere_but_never_a_glossary_label(sample_root):
    conn, root, fs = sample_root
    tagged.add_label(conn, "API-6100", AT, "A glossary label that looks like a standard")
    tagged.set_patterns(conn, [INSTRUMENT], [])
    cid = save(conn, root, fs, "ABC-1234 and API-6100 and API-6200.")
    assert set(suggested(conn)) == {"ABC-1234", "API-6200"}
    tagged.set_patterns(conn, [INSTRUMENT], ["API*", "ABC1234"])
    assert suggested(conn) == {}
    assert [lb.label for lb, _ in Model(conn).tagged.item("capture", cid)] == ["API-6100"]


def test_an_old_cache_is_read_again_from_the_search_index(sample_root):
    conn, root, fs = sample_root
    conn.execute("UPDATE app_state SET value = '1' WHERE key = ?", (tagged.WORDS_KEY,))
    tagged.set_patterns(conn, [tm.Pattern("Tank", "XX-##/#")], [])
    assert get_state(conn, tagged.WORDS_KEY) == tagged.WORDS_FORM


def test_a_tasks_own_fields_get_new_labels_at_once(sample_root):
    from docrepo import tasks

    conn, _, _ = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    t = tasks.create_task(conn, Settings(me="P001"), title="Recalibrate PT-3301", at=AT, created_by="test")
    assert "PT-3301" in suggested(conn)
    tasks.update_task(conn, Settings(me="P001"), "T000007", at=AT, via="test", description="Swap FT-4410's transmitter.")
    m = Model(conn)
    assert "FT-4410" in suggested(conn)
    assert ("FT-4410", 1) in [(lb.label, n) for lb, n in tagged.task_tags(m, "T000007")]
    assert ("PT-3301", 1) in [(lb.label, n) for lb, n in tagged.task_tags(m, t)]
    assert "| Tagged labels | PT-3301 (1) |" in MdPages(m, AT.date(), AT).task_page(m.task(t))


# ---- Add to glossary, Same as… and Not a tag (item 107) ----
def test_add_to_glossary_makes_it_an_ordinary_label_and_export_has_it(sample_root):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    cid = save(conn, root, fs, "TIC-2216 reads high; tic 2216 later.")
    tagged.accept(conn, "TIC2216", "Jacket temperature controller", ["jacket loop"])
    lb = Model(conn).tagged.by_key["TIC2216"]
    assert (lb.status, lb.came, lb.pattern, lb.description, lb.aliases) == ("glossary", "pattern", "Instrument tag", "Jacket temperature controller", ("jacket loop",))
    x = dict((lb.label, m) for lb, m in Model(conn).tagged.item("capture", cid))["TIC-2216"]
    assert x.how == "label" and x.written == {"TIC-2216": 1}  # found as a glossary label now; lower case needs a word alias
    assert "TIC-2216,Jacket temperature controller,jacket loop" in ti.export_csv(conn)
    with pytest.raises(tagged.TaggedError, match="isn't a suggested tagged label"):
        tagged.accept(conn, "TIC2216")


def test_export_leaves_out_what_is_only_suggested(sample_root):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    save(conn, root, fs, "TIC-2216 reads high.")
    assert "TIC-2216" not in ti.export_csv(conn)


def test_same_as_makes_it_an_alias_and_moves_its_mentions_and_the_owners_changes(sample_root):
    conn, root, fs = sample_root
    v = tagged.add_label(conn, "V-110", AT, "Feed surge drum")
    tagged.set_patterns(conn, [EQUIPMENT], [])
    cid = save(conn, root, fs, "VS-110 is what operations call it.")
    tagged.choose(conn, "capture", cid, "VS110", "removed", AT)
    target = tagged.same_as(conn, "VS110", v)
    assert target.label == "V-110" and "VS-110" not in suggested(conn)
    tg = Model(conn).tagged
    assert tg.by_key["V110"].aliases == ("VS-110",)
    assert [lb.label for lb in tg.removed("capture", cid)] == ["V-110"]  # the owner's removal moved with it
    tagged.choose(conn, "capture", cid, "V110", None, AT)
    assert [(lb.label, m.how) for lb, m in Model(conn).tagged.item("capture", cid)] == [("V-110", "alias")]


def test_not_a_tag_forgets_the_owners_changes_and_never_a_tag_removes_it(sample_root):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    cid = save(conn, root, fs, "ABC-1234 is a part number.")
    tagged.choose(conn, "capture", cid, "ABC1234", "added", AT)
    tagged.forget(conn, "ABC1234")
    tagged.set_patterns(conn, [INSTRUMENT], ["ABC1234"])
    assert suggested(conn) == {} and Model(conn).tagged.item("capture", cid) == []


def test_a_suggestion_added_by_hand_or_imported_joins_the_glossary(sample_root, tmp_path):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    save(conn, root, fs, "TIC-2216 and PDT_4410 read high.")
    tagged.add_label(conn, "PDT-4410", AT, "Filter dP")
    assert Model(conn).tagged.by_key["PDT4410"].status == "glossary"
    path = tmp_path / "tags.csv"
    path.write_text("Tag,Description\nTIC-2216,Jacket temperature\n", encoding="utf-8")
    rows = ti.read_rows(path)
    p = ti.preview(conn, rows, ti.Plan(0, ti.propose(rows, 0)))
    assert p.added == ["TIC-2216"]
    ti.run_import(conn, p, "tags.csv", AT)
    lb = Model(conn).tagged.by_key["TIC2216"]
    assert (lb.status, lb.came, lb.description, lb.source) == ("glossary", "import", "Jacket temperature", "tags.csv")


def test_an_alias_may_take_a_suggestions_name(sample_root):
    conn, root, fs = sample_root
    v = tagged.add_label(conn, "V-110", AT)
    tagged.set_patterns(conn, [EQUIPMENT], [])
    save(conn, root, fs, "VS-110 again.")
    tagged.edit_label(conn, v, "", ["VS-110"])  # not refused as "taken": it's only suggested
    assert "VS-110" not in suggested(conn)


# ---- Suggested, search, the tester and Try on everything ----
def test_suggested_lists_the_most_mentioned_first_with_where_each_is_seen(sample_root):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    save(conn, root, fs, "PDT-4410 reads high.", task="T000008")
    save(conn, root, fs, "PDT-4410 again, and TT-2215.", task="T000007")
    save(conn, root, fs, "PDT-4410, unfiled.")
    m = Model(conn)
    out = [(s.label.label, s.items, s.unfiled) for s in tagged.suggestions(m)]
    assert out == [("PDT-4410", 3, 1), ("TT-2215", 1, 0)]  # typed on a task, a note lands on its notes page (release 5.69)
    s = tagged.suggestions(m)[0]
    assert set(s.places) == {m.chains_of("T000008")[0][0], m.chains_of("T000007")[0][0]}


def test_search_finds_a_suggestion(sample_root):
    conn, root, fs = sample_root
    tagged.set_patterns(conn, [INSTRUMENT], [])
    cid = save(conn, root, fs, "PDT-4410 reads high.")
    results = search.search(conn, Model(conn), "pdt4410")
    assert (results[0].group, results[0].id, results[0].sub) == ("Tagged label", "PDT4410", "New, from the Instrument tag pattern · mentioned in 1 item")
    assert ("Capture", cid) in [(r.group, r.id) for r in results]


def test_the_tester_says_how_each_was_found():
    hits = tagged.tester(GLOSSARY, [INSTRUMENT, EQUIPMENT], ["ABC*"], "V110 and the feed drum; P-204A/B; FIC-2210; ABC-1234; TT-2215")
    assert [(h.written, h.how, h.pattern) for h in hits] == [
        ("V110", "label", ""), ("feed drum", "word", ""), ("P-204A", "new", "Equipment tag"), ("/B", "new", "Equipment tag"),
        ("FIC-2210", "label", ""), ("ABC-1234", "never", "Instrument tag"), ("TT-2215", "new", "Instrument tag")]


def test_try_on_everything_counts_new_labels_before_anything_is_saved(sample_root):
    conn, root, fs = sample_root
    tagged.add_label(conn, "TT-2215", AT)
    save(conn, root, fs, "API-6100 and ABC-1234 and TT-2215.")
    save(conn, root, fs, "API-6100 again.")
    gone = save(conn, root, fs, "XYZ-9999 in a capture that's discarded.")
    conn.execute("UPDATE captures SET discarded = '2026-10-08 16:00' WHERE id = ?", (gone,))
    before = [tuple(r) for r in conn.execute("SELECT * FROM tagged_labels")]
    found, items = tagged.try_everything(conn, Model(conn), [INSTRUMENT], ["ABC*"])
    assert [(t.label, t.items, t.pattern) for t in found] == [("API-6100", 2, "Instrument tag")]
    assert items == 2
    assert [tuple(r) for r in conn.execute("SELECT * FROM tagged_labels")] == before and get_state(conn, tagged.PATTERNS_KEY) is None
    assert tagged.try_everything(conn, Model(conn), [], []) == ([], 0)


# ---- the settings ----
def test_the_patterns_and_never_a_tag_are_kept_in_settings_json(data_root, fs):
    s = Settings()
    s.save(fs, data_root)
    assert "tagged_patterns" not in json.loads((data_root / "Config" / "settings.json").read_text(encoding="utf-8"))  # none shipped
    s.tagged_patterns = [INSTRUMENT.as_setting()]
    s.tagged_never = ["API*"]
    s.save(fs, data_root)
    back = Settings.load(data_root)
    assert back.tagged_patterns == [{"name": "Instrument tag", "mask": "XX[X][X]-####", "space": False}] and back.tagged_never == ["API*"]
    (data_root / "Config" / "settings.json").write_text(json.dumps({"tagged_patterns": [{"name": "x"}, {"mask": "X-###"}], "tagged_never": "API"}),
                                                        encoding="utf-8")
    back = Settings.load(data_root)
    assert back.tagged_patterns == [{"name": "X-###", "mask": "X-###", "space": False}] and back.tagged_never == []


def test_use_settings_keeps_docs_dbs_copy_as_settings_json_has_it(sample_root):
    conn, _, _ = sample_root
    s = Settings(tagged_patterns=[EQUIPMENT.as_setting()], tagged_never=["api*"])
    assert tagged.use_settings(conn, s) is not None
    assert tagged.patterns_state(conn) == ([EQUIPMENT], ["API*"])
    assert tagged.use_settings(conn, s) is None  # as kept already: nothing matched again
    assert tagged.use_settings(conn, Settings()) is not None and tagged.patterns_state(conn) == ([], [])
