"""Search: the index of captures' and documents' text, and what a search finds."""
from __future__ import annotations

from datetime import datetime

from docrepo import search
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.save import CaptureDraft, save_capture


def found(conn, query):
    return [(r.group, r.id) for r in search.search(conn, Model(conn), query)]


def test_every_word_must_be_in_the_item(sample_root):
    conn, _, _ = sample_root
    assert found(conn, "crane") == [("Task", "T000012"), ("Capture", "C000013"), ("Capture", "C000012")]
    assert found(conn, "CRANE booking") == [("Capture", "C000013")]
    assert found(conn, "crane zebra") == []
    assert found(conn, "c") == []  # two letters at least


def test_it_finds_documents_by_their_text_people_by_alias_and_labels(sample_root):
    conn, root, _ = sample_root
    assert ("Document", "D000002") in found(conn, "laser-align")  # in its extracted.txt
    assert found(conn, "Thomas") == [("Person", "P003")]
    assert ("Label", "Safety") in found(conn, "walkthrough")
    assert ("Saved copy", "T000001") in found(conn, "datasheet rev")


def test_results_carry_the_text_around_the_match(sample_root):
    conn, _, _ = sample_root
    r = next(x for x in search.search(conn, Model(conn), "rigging plan") if x.id == "C000012")
    assert r.title == "Mike to write the rigging plan for the impeller lift" and "rigging plan" in r.snippet


def test_a_saved_capture_is_searchable_at_once(sample_root):
    conn, root, fs = sample_root
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="The flange gasket is spiral wound.", task="T000008"),
                 datetime(2026, 10, 8, 15, 0))
    assert found(conn, "spiral wound") == [("Capture", "C000026")]


def test_rebuild_and_needs_rebuild(sample_root):
    conn, root, _ = sample_root
    assert not search.needs_rebuild(conn)
    conn.execute("DELETE FROM search_text")
    assert search.needs_rebuild(conn)
    m = Model(conn)
    assert search.rebuild(conn, root) == len(m.captures) + len(m.documents) == 28
    assert not search.needs_rebuild(conn)


def test_like_wildcards_are_taken_literally(sample_root):
    conn, _, _ = sample_root
    assert found(conn, "100%") == []
    assert found(conn, "__") == []


def test_snippet():
    assert search.snippet("a" * 100 + " needle " + "b" * 200, ["needle"]).startswith("…aaaa")
    assert search.snippet("short text", ["text"]) == "short text"
    assert search.snippet("nothing here", ["zzz"]) == ""
