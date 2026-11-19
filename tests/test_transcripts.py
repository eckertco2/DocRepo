"""Discussions and meetings: a summary and a transcript beside the notes (release 5.170, the design workspace's
``docs/mods/discussions-plan.md``, decisions 794 to 801). What Save keeps, where, and what reads it. Made-up text only."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import capacity, captures, db, notes_page, search, transcripts
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, save_capture

AT = datetime(2026, 10, 8, 14, 10)
LATER = datetime(2026, 10, 9, 9, 0)
SETTINGS = Settings(me="P001")
#: A made-up transcript's words, with a word no other text in the sample has.
SAID = "Okay so the zanderwick valve is the one we keep coming back to.\n@Tom said he would check it, but nobody wrote it down.\n"


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def save(env, draft: CaptureDraft, at: datetime = AT):
    conn, root, fs = env
    return save_capture(conn, root, fs, SETTINGS, draft, at)


def meeting(content: str = "Pump vendor call.\nSeal kit ships Friday.", **kw) -> CaptureDraft:
    return CaptureDraft(content=content, meeting=True, meeting_name="Pump vendor call", **kw)


def test_a_summary_and_a_transcript_are_kept_apart_from_the_notes(env):
    """Decisions 796 and 797: the summary in the capture's summary, the transcript a file of the meeting's, transcript.md,
    described as Transcript; nothing of the transcript in docs.db's rows, the capture.md or the notes page."""
    conn, root, _ = env
    r = save(env, meeting(summary="Agreed: seal kit Friday.", transcript=SAID))
    m = Model(conn)
    c = m.captures[r.capture_id]
    assert c.summary == "Agreed: seal kit Friday." and r.meeting
    (doc,) = [d for d in c.document_ids if transcripts.is_transcript(m, d)]
    d = m.documents[doc]
    assert (d.name, d.description) == ("transcript.md", "Transcript")
    assert [(f.task, f.name) for f in m.saved_of(doc)] == [(r.meeting, "transcript.md")]
    path = root / "Tasks" / r.meeting / "Files" / "transcript.md"
    assert path.read_text(encoding="utf-8") == SAID and captures.file_of(root, m, doc) == path
    assert "zanderwick" not in captures.read_content(root, c)
    assert "zanderwick" not in notes_page.get(conn, r.meeting)
    for table in ("captures", "documents", "tasks", "status_log"):
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 - the test's own table names
        assert not any("zanderwick" in str(v) for row in rows for v in tuple(row)), table


def test_a_transcript_or_a_summary_alone_makes_the_capture(env):
    conn = env[0]
    r = save(env, meeting(content="", transcript=SAID))
    m = Model(conn)
    assert r.capture_id and any(transcripts.is_transcript(m, d) for d in m.captures[r.capture_id].document_ids)
    s = save(env, meeting(content="", summary="Nothing decided."))
    assert Model(conn).captures[s.capture_id].summary == "Nothing decided."


def test_only_the_notes_are_read_for_operators(env):
    """Decision 795: an @ line in the transcript makes nothing."""
    r = save(env, meeting(content="Short call.", transcript=SAID))
    assert r.items == [] and not r.made


def test_the_transcript_goes_with_its_meeting_whatever_tasks_the_notes_name(env):
    """Release 5.165's decision 767 gives a file to every task a note names; a transcript is the meeting's, saved once."""
    conn = env[0]
    r = save(env, meeting(content="#Installation #Rigging plan\nCrane booked.", transcript=SAID))
    m = Model(conn)
    docs = [d for d in m.documents if transcripts.is_transcript(m, d)]
    assert len(docs) == 1 and [f.task for f in m.saved_of(docs[0])] == [r.meeting]


def test_a_long_transcript_is_indexed_whole_and_found_marked_transcript(env):
    """Decision 799: past the 200,000 characters other files are cut at, up to 2,000,000; a result says Transcript."""
    conn, root, _ = env
    long = ("we went round the agenda again " * 10_000) + "and the last word was quillfeather."
    assert len(long) > 300_000
    r = save(env, meeting(transcript=long))
    m = Model(conn)
    (doc,) = [d for d in m.captures[r.capture_id].document_ids if transcripts.is_transcript(m, d)]
    assert m.documents[doc].text_status == "ok" and search.extracted_text(root, doc).rstrip("\n") == long
    found = [x for x in search.search(conn, Model(conn), "quillfeather") if x.id == doc]
    assert found and found[0].sub.startswith("Transcript")


def test_a_transcript_added_later_never_overwrites(env):
    """Decision 798: Add transcript… on the meeting's page; a second one is transcript-2.md."""
    conn, root, fs = env
    r = save(env, meeting(transcript=SAID))
    out = transcripts.add_later(conn, root, fs, SETTINGS, r.meeting, "The second recording, made up.", LATER)
    m = Model(conn)
    names = sorted(f.name for d in m.documents if transcripts.is_transcript(m, d) for f in m.saved_of(d))
    assert names == ["transcript-2.md", "transcript.md"] and "transcript-2.md" in out.message
    assert (root / "Tasks" / r.meeting / "Files" / "transcript.md").read_text(encoding="utf-8") == SAID
    assert (root / "Tasks" / r.meeting / "Files" / "transcript-2.md").read_text(encoding="utf-8") == "The second recording, made up.\n"
    assert transcripts.meeting_transcripts(m, r.meeting)[0].name == "transcript.md"


def test_a_summary_added_later_goes_on_the_meetings_notes(env):
    conn, root, fs = env
    r = save(env, meeting())
    transcripts.set_summary(conn, root, fs, r.meeting, "From the call's own summary, made up.", LATER)
    m = Model(conn)
    assert m.captures[r.capture_id].summary == "From the call's own summary, made up."
    assert transcripts.summaries(m, r.meeting) == [(r.capture_id, "From the call's own summary, made up.")]


def test_a_meeting_with_no_notes_gets_a_capture_for_what_is_added_later(env):
    """A Zoom summary or a recording for a meeting nobody took notes in: a capture on the meeting holds it."""
    conn, root, fs = env
    meet = next(t.id for t in Model(conn).open_meetings())
    transcripts.add_later(conn, root, fs, SETTINGS, meet, SAID, LATER)
    transcripts.set_summary(conn, root, fs, meet, "Made up.", LATER)
    m = Model(conn)
    assert transcripts.meeting_transcripts(m, meet) and [s for _, s in transcripts.summaries(m, meet)] == ["Made up."]


def test_the_meetings_page_has_a_summary_section_with_its_transcripts(env):
    """Decision 796: the summary on the meeting's page, above the notes, and its transcripts; Add… at the right."""
    from docrepo.detail import Pages, PageState

    conn, root, _ = env
    r = save(env, meeting(summary="Agreed: seal kit Friday.\nTom checks the coupling.", transcript=SAID))
    m = Model(conn)
    parts = Pages(m, AT.date(), lambda cid: "").task_parts(r.meeting, PageState())
    assert parts["summary_short"] == "1 summary · 1 transcript"
    assert "Agreed: seal kit Friday.<br>Tom checks the coupling." in parts["summary"] and "opensaved:" in parts["summary"]
    assert "addsummary:" in parts["summary_summary"] and "Edit summary…" in parts["summary_summary"] and "Add transcript…" in parts["summary_summary"]
    other = next(t.id for t in m.open_meetings() if t.id != r.meeting)
    empty = Pages(m, AT.date(), lambda cid: "").task_parts(other, PageState())
    assert empty["summary_short"] == "none yet" and "Add summary…" in empty["summary_summary"]
    assert "summary" not in Pages(m, AT.date(), lambda cid: "").task_parts("T000012", PageState())  # not a meeting: none


def test_the_workspace_lists_the_summary_and_the_transcript(env):
    from docrepo import workspace
    from docrepo.detail import Pages

    conn = env[0]
    r = save(env, meeting(summary="Agreed: seal kit Friday.", transcript=SAID))
    rows = workspace.resources(Pages(Model(conn), AT.date(), lambda cid: ""), r.meeting)["summary"]
    assert [(x.name, x.href.split(":")[0]) for x in rows] == [("Agreed: seal kit Friday", "capture"), ("transcript.md", "opensaved")]
    assert rows[0].second == ""  # one sentence: nothing more under it
