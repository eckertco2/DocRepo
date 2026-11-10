"""Search: the index of captures' and documents' text, and what a search finds."""
from __future__ import annotations

from datetime import datetime

from docrepo import overview, search, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.save import CaptureDraft, FileRow, save_capture


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
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="The flange gasket is spiral wound.", task="T000008", files=[FileRow("Spec sheet", "https://example.com/spec", "the spec")]),
                 datetime(2026, 10, 8, 15, 0))
    assert found(conn, "spiral wound") == [("Capture", "C000026")]
    # Text alone on a task is no capture (release 5.69): it's found on its notes page.
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="The bolts are B7 studs.", task="T000008"), datetime(2026, 10, 8, 15, 5))
    assert found(conn, "B7 studs") == [("Notes", "T000008")]


def test_rebuild_and_needs_rebuild(sample_root):
    conn, root, _ = sample_root
    assert not search.needs_rebuild(conn)
    conn.execute("DELETE FROM search_text")
    assert search.needs_rebuild(conn)
    m = Model(conn)
    # Each task's notes page is indexed too (release 5.25).
    assert search.rebuild(conn, root) == len(m.captures) + len(m.documents) + len(m.pages) == 28 + len(m.tasks)
    assert not search.needs_rebuild(conn)


def test_like_wildcards_are_taken_literally(sample_root):
    conn, _, _ = sample_root
    assert found(conn, "100%") == []
    assert found(conn, "__") == []


def test_snippet():
    assert search.snippet("a" * 100 + " needle " + "b" * 200, ["needle"]).startswith("…aaaa")
    assert search.snippet("short text", ["text"]) == "short text"
    assert search.snippet("nothing here", ["zzz"]) == ""


def test_it_finds_reference_fields_and_people_by_email_group_and_role(sample_root):
    """Release 5.9: a task by its reference field values, and a person by email, group or role."""
    conn, _, _ = sample_root
    tasks.update_task(conn, Settings(me="P001"), "T000012", at=datetime(2026, 10, 8, 9, 0), via="Browse tool", references={"Work order #": "48213"})
    assert found(conn, "48213") == [("Task", "T000012")]
    assert found(conn, "work order 48213") == [("Task", "T000012")]
    assert found(conn, "millwright") == [("Person", "P004")]
    assert found(conn, "tom.becker@example") == [("Person", "P003")]
    assert [r.sub for r in search.search(conn, Model(conn), "Purchasing")] == ["Tyler, Tyler N. · Purchasing · Buyer"]


def test_read_takes_where_to_look_off_the_front(sample_root):
    """Release 5.108: "search excel files …" names a place, "#…" a task; anything else is words to find, as before."""
    conn, _, _ = sample_root
    m = Model(conn)

    def read(q):
        scope, rest = search.read(q, m)
        return (scope.name if scope else None, rest)

    assert read("search excel files pump curve data") == ("Excel files", "pump curve data")
    assert read("Search links approval forms") == ("Links", "approval forms")
    assert read("search notes V-110") == ("Notes", "V-110")
    assert read("search excel files for pump curve") == ("Excel files", "pump curve")  # "for" is passed over
    assert read("search my PDFs datasheet") == ("PDF files", "datasheet")
    assert read("search all spreadsheets for pump") == ("Excel files", "pump")
    assert read("search saved copies rev") == ("Saved copies", "rev")
    assert read("search people buyer") == ("People", "buyer")
    assert read("search emails") == ("Emails", "")  # the place alone
    # A task after "#": its whole title as the # list writes it, its ID, or its first word.
    title = m.task("T000012").title
    assert read(f"search #{title} crane") == (title, "crane")
    assert read(f"#{title} crane") == (title, "crane")
    assert read(f"search links #{title}") == (f"Links in {title}", "")
    assert read(f"search #{title} excel files pump") == (f"Excel files in {title}", "pump")
    assert read(f"search notes in #{title.upper()} for crane") == (f"Notes in {title}", "crane")
    assert read("search #T000012 crane") == (title, "crane")
    scope, rest = search.read(f"search #{title.split()[0]} crane", m)
    assert "T000012" in scope.tasks and rest == "crane"
    scope, rest = search.read("search #zzzqqq crane", m)
    assert scope.tasks == frozenset() and rest == "crane"
    scope, _ = search.read(f"search #{m.task('T000001').title}", m)
    assert scope.tasks == {"T000001", *m.descendants_of("T000001")}
    # No place or task it knows: the whole of it is searched for.
    assert read("search for the pump") == (None, "search for the pump")
    assert read("search vendors for seals") == (None, "search vendors for seals")
    assert read("notes V-110") == (None, "notes V-110")
    assert read("find links pump") == (None, "find links pump")
    assert read("crane booking") == (None, "crane booking")


def _with_a_link(sample_root):
    conn, root, fs = sample_root
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="Gasket facts.", task="T000008", files=[
        FileRow("Zircon spec sheet", "https://example.com/spec", "the zircon spec")]), datetime(2026, 10, 8, 15, 0))
    return conn, next(i for g, i in found(conn, "zircon") if g == "Document")


def test_a_scope_lists_only_its_own(sample_root):
    conn, _, _ = sample_root
    assert found(conn, "search tasks crane") == [("Task", "T000012")]
    assert found(conn, "search captures for crane") == [("Capture", "C000013"), ("Capture", "C000012")]
    assert found(conn, "search people crane") == []
    assert found(conn, "search people Thomas") == [("Person", "P003")]
    m = Model(conn)
    # A place alone lists everything in it.
    assert found(conn, "search people") == [("Person", p) for p in m.people]
    assert {i for _, i in found(conn, "search tasks")} == {t.id for t in m.tasks.values() if not t.discarded}
    # Files by type: a link is found under links, and under no other type.
    conn, link = _with_a_link(sample_root)
    assert found(conn, "search links zircon") == [("Document", link)]
    assert found(conn, "search excel files zircon") == []
    assert found(conn, "search files zircon") == [("Document", link)]
    assert found(conn, "search notes zircon") == [("Notes", "T000008")]  # its row on the task's notes page
    assert found(conn, "search notes crane") == [("Capture", "C000013"), ("Capture", "C000012")]
    assert ("Document", link) in found(conn, "search links")
    # Every result of a file type's scope is of that type.
    m = Model(conn)
    for scope, kind in (("pdfs", "pdf"), ("excel files", "sheet"), ("word documents", "doc"), ("links", "link")):
        for g, i in found(conn, f"search {scope}"):
            assert g in ("Document", "Saved copy")
            if g == "Document":
                assert overview.file_type(m.documents[i].name, m.documents[i].original) == kind
    # Notes leave emails out; emails keep only them.
    for g, i in found(conn, "search notes"):
        assert g == "Notes" or not m.captures[i].emails
    for g, i in found(conn, "search emails"):
        assert g != "Capture" or m.captures[i].emails


def test_a_task_scope_keeps_to_the_task_and_what_is_under_it(sample_root):
    conn, link = _with_a_link(sample_root)
    m = Model(conn)
    family = {"T000008", *m.descendants_of("T000008")}
    here = m.task("T000008").title
    above = [m.task(a).title for a in m.ancestors_of("T000008")]
    other = next(t.title for t in m.tasks.values() if not t.discarded and t.id not in family and "T000008" not in m.descendants_of(t.id))
    assert found(conn, f"search links #{here} zircon") == [("Document", link)]
    assert found(conn, f"search links #{here}") == [("Document", link)]
    for title in above:  # a task above it holds it too
        assert ("Document", link) in found(conn, f"search #{title} zircon")
    assert found(conn, f"search #{other} zircon") == []
    assert found(conn, "search #zzzqqq zircon") == []
    # Everything listed in a task is the task's: never a person or a label.
    listed = found(conn, f"search #{here}")
    assert ("Task", "T000008") in listed and ("Document", link) in listed
    for g, i in listed:
        assert g in ("Task", "Notes", "Capture", "Document", "Saved copy")
        if g == "Capture":
            assert m.captures[i].task in family
        if g in ("Task", "Notes", "Saved copy"):
            assert i in family
