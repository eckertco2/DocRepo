"""Search: the index of captures' and documents' text, and what a search finds."""
from __future__ import annotations

from datetime import date, datetime

from docrepo import overview, pins, search, tagged, tasks
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


TODAY = date(2026, 10, 8)


def test_read_takes_the_filters_and_the_task(sample_root):
    """Release 5.121 (decisions 447, 449 and 450): File search's filters anywhere, a "#task" at the start of the words, and
    the words; 5.108's place words are words now."""
    conn, _, _ = sample_root
    m = Model(conn)

    def read(q):
        scope, rest = search.read(q, m, TODAY)
        return (scope.name if scope else None, rest)

    assert read("type:excel pump curve data") == ("Excel files", "pump curve data")
    assert read("pump curve type:excel data") == ("Excel files", "pump curve data")  # anywhere in it
    assert read("type:links approval forms") == ("Links", "approval forms")
    assert read("type:notes V-110") == ("Notes", "V-110")
    assert read("type:pdf type:word datasheet") == ("PDF files and Word files", "datasheet")
    assert read("pump .xlsx") == ("Excel files", "pump")
    assert read("type:people buyer") == ("People", "buyer")
    assert read("type:copies rev") == ("Saved copies", "rev")
    assert read("type:emails") == ("Emails", "")  # the filter alone
    assert read("type:PDFs datasheet") == ("PDF files", "datasheet")
    assert read("from:tom after:1 sep pump") == ("from tom after 1 Sep", "pump")
    assert read("since:last week crane") == ("since 28 Sep", "crane")
    assert read('before:"1 oct" crane') == ("before 1 Oct", "crane")
    assert read("is:pinned") == ("pinned files", "")
    # A task after "#": its whole title as the # list writes it, its ID, or its first word; in: names one too.
    title = m.task("T000012").title
    assert read(f"#{title} crane") == (f"in {title}", "crane")
    assert read(f"type:links #{title}") == (f"Links in {title}", "")
    assert read(f"type:excel #{title.upper()} pump") == (f"Excel files in {title}", "pump")
    assert read("#T000012 crane") == (f"in {title}", "crane")
    scope, rest = search.read(f"#{title.split()[0]} crane", m, TODAY)
    assert "T000012" in scope.tasks and rest == "crane"
    scope, rest = search.read(f"in:{title.split()[0].lower()} crane", m, TODAY)
    assert "T000012" in scope.tasks and rest == "crane"
    scope, rest = search.read("#zzzqqq crane", m, TODAY)
    assert scope.tasks == frozenset() and rest == "crane"
    scope, _ = search.read(f"#{m.task('T000001').title}", m, TODAY)
    assert scope.tasks == {"T000001", *m.descendants_of("T000001")}
    # With no filter and no task at the start, the whole of it is searched for.
    assert read("search excel files pump") == (None, "search excel files pump")  # decision 449: the place words went
    assert read(f"search #{title} crane") == (None, f"search #{title} crane")
    assert read("work order #48213") == (None, "work order #48213")  # a "#" later on is a word (decision 450)
    assert read("re: pump curve") == (None, "re: pump curve")
    assert read("crane booking") == (None, "crane booking")


def test_a_filter_being_typed_or_naming_nothing(sample_root):
    """Decision 452: one being typed at the end is left out and hinted; one that names nothing lists nothing."""
    conn, _, _ = sample_root
    m = Model(conn)
    scope, rest = search.read("crane type:ex", m, TODAY)
    assert rest == "crane" and scope.hints[0].startswith("type:ex isn't a kind yet.") and not scope.applied
    assert found(conn, "crane type:ex") == found(conn, "crane")  # the words alone, while it's typed
    assert found(conn, "type:ex") == [] and found(conn, "since:1") == []  # nothing to keep yet
    scope, rest = search.read("type:xyz crane", m, TODAY)
    assert rest == "crane" and scope.hints[0].startswith("type:xyz isn't a kind. type: takes") and not scope.groups
    assert found(conn, "type:xyz crane") == []
    assert found(conn, "since:soon crane") == [] and found(conn, "tag:zzz crane") == []
    scope, _ = search.read("is:missing", m, TODAY)  # decision 451: Find files' and File search's
    assert "Find files" in scope.hints[0] and found(conn, "is:missing") == []
    scope, rest = search.read("type: crane", m, TODAY)
    assert rest == "crane" and scope.hints == (search.HINTS["type"],)


def _with_a_link(sample_root):
    conn, root, fs = sample_root
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="Gasket facts.", task="T000008", files=[
        FileRow("Zircon spec sheet", "https://example.com/spec", "the zircon spec")]), datetime(2026, 10, 8, 15, 0))
    return conn, next(i for g, i in found(conn, "zircon") if g == "Document")


def test_type_lists_only_its_own(sample_root):
    conn, _, _ = sample_root
    assert found(conn, "type:tasks crane") == [("Task", "T000012")]
    assert found(conn, "type:captures crane") == [("Capture", "C000013"), ("Capture", "C000012")]
    assert found(conn, "type:people crane") == []
    assert found(conn, "type:people Thomas") == [("Person", "P003")]
    m = Model(conn)
    # A filter alone lists everything it keeps.
    assert found(conn, "type:people") == [("Person", p) for p in m.people]
    assert {i for _, i in found(conn, "type:tasks")} == {t.id for t in m.tasks.values() if not t.discarded}
    # Files by type: a link is found under links, and under no other type.
    conn, link = _with_a_link(sample_root)
    assert found(conn, "type:links zircon") == [("Document", link)]
    assert found(conn, "type:excel zircon") == []
    assert found(conn, "type:files zircon") == [("Document", link)]
    assert found(conn, "type:notes zircon") == [("Notes", "T000008")]  # its row on the task's notes page
    assert found(conn, "type:notes crane") == [("Capture", "C000013"), ("Capture", "C000012")]
    assert ("Document", link) in found(conn, "type:links")
    # Every result of a file type is of that type, and two types add up.
    m = Model(conn)
    for typed, kind in (("pdf", "pdf"), ("excel", "sheet"), ("word", "doc"), ("links", "link")):
        for g, i in found(conn, f"type:{typed}"):
            assert g in ("Document", "Saved copy")
            if g == "Document":
                assert overview.file_type(m.documents[i].name, m.documents[i].original) == kind
    assert set(found(conn, "type:pdf type:word")) == set(found(conn, "type:pdf")) | set(found(conn, "type:word"))
    # Notes leave emails out; emails keep only them, by their rows or, from before release 5.74, by their source.
    for g, i in found(conn, "type:notes"):
        assert g == "Notes" or not (m.captures[i].emails or m.captures[i].source == "outlook_email")
    mails = [i for g, i in found(conn, "type:emails") if g == "Capture"]
    assert mails and all(m.captures[i].emails or m.captures[i].source == "outlook_email" for i in mails)


def test_the_other_filters_keep_what_they_name(sample_root):
    """Decision 451: dates by each item's day, from: by an email's sender or a file's source, is:pinned, tag:."""
    conn, root, fs = sample_root
    m = Model(conn)
    live = {c.id for c in m.captures.values() if not c.discarded}
    after = {i for g, i in found(conn, "type:captures since:1 oct")}
    before = {i for g, i in found(conn, "type:captures before:1 oct")}
    assert after and before and after | before == live and not after & before
    assert all(m.captures[i].saved[:10] >= "2026-10-01" for i in after)
    assert {i for g, i in found(conn, "type:tasks since:1 oct")} == {t.id for t in m.tasks.values() if not t.discarded and t.created >= "2026-10-01"}
    assert not [g for g, _ in found(conn, "since:1 sep Thomas")]  # people have no day
    # from: a sender, by the From line of an email from before release 5.74.
    email = next(c for c in m.captures.values() if c.source == "outlook_email" and not c.discarded)
    body = conn.execute("SELECT body FROM search_text WHERE kind = 'capture' AND id = ?", (email.id,)).fetchone()[0]
    sender = overview.sender_of(body)
    hits = found(conn, f"from:{sender.split()[0].lower()}")
    assert ("Capture", email.id) in hits
    assert all(g in ("Capture", "Document", "Saved copy") for g, _ in hits)
    for g, i in hits:
        if g == "Capture":
            assert m.captures[i].source == "outlook_email"
    assert found(conn, "from:zzzqqq") == []
    for g, i in found(conn, "from:attachment"):  # a file's source
        assert g == "Document" and not m.documents[i].original
    # is:pinned
    assert found(conn, "is:pinned") == []
    pins.set_pinned(conn, "T000001", "D000001", True)
    assert found(conn, "is:pinned") == [("Document", "D000001")]
    # tag: what mentions a tagged label, however it's typed.
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="V110 alarmed twice on the night shift."), datetime(2026, 10, 8, 15, 0))
    tagged.add_label(conn, "V-110", datetime(2026, 10, 8, 15, 5), "Feed drum")
    cid = max(Model(conn).captures)
    assert ("Capture", cid) in found(conn, "tag:v110") and ("Capture", cid) in found(conn, "tag:V-110 night")
    assert ("Capture", cid) not in found(conn, "tag:V-110 crane")


def test_a_task_scope_keeps_to_the_task_and_what_is_under_it(sample_root):
    conn, link = _with_a_link(sample_root)
    m = Model(conn)
    family = {"T000008", *m.descendants_of("T000008")}
    here = m.task("T000008").title
    above = [m.task(a).title for a in m.ancestors_of("T000008")]
    other = next(t.title for t in m.tasks.values() if not t.discarded and t.id not in family and "T000008" not in m.descendants_of(t.id))
    assert found(conn, f"type:links #{here} zircon") == [("Document", link)]
    assert found(conn, f"type:links #{here}") == [("Document", link)]
    assert found(conn, f"#{here} type:links") == [("Document", link)]  # a filter may follow the task too
    for title in above:  # a task above it holds it too
        assert ("Document", link) in found(conn, f"#{title} zircon")
    assert found(conn, f"#{other} zircon") == []
    assert found(conn, "#zzzqqq zircon") == []
    # Everything listed in a task is the task's: never a person or a label.
    listed = found(conn, f"#{here}")
    assert ("Task", "T000008") in listed and ("Document", link) in listed
    for g, i in listed:
        assert g in ("Task", "Notes", "Capture", "Document", "Saved copy")
        if g == "Capture":
            assert m.captures[i].task in family
        if g in ("Task", "Notes", "Saved copy"):
            assert i in family
