"""Discussions and meetings in the capture window (release 5.170, the design workspace's ``docs/mods/discussions-plan.md``,
decisions 794 to 800): the Notes, Summary and Transcript tabs, Save, and a draft's transcript. Offscreen, over the sample
data, with made-up text only."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, drafts, prompts, transcripts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import meeting_tabs  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SAID = "So the plan is the seal kit Friday.\n@Tom will check the coupling, he said.\n"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    yield AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW)
    conn.close()


@pytest.fixture
def window(ctx):
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    w.hide()
    w.deleteLater()


def test_the_tabs_come_with_the_mode_and_the_summary_moves_into_them(window):
    tabs = window.tabs
    assert tabs.bar.isHidden() and window.tabs.current() == meeting_tabs.NOTES
    home = window.lower_layout.indexOf(window.summary_field)
    assert home >= 0
    window.toggle_meeting()
    assert not tabs.bar.isHidden() and [tabs.bar.tabText(i) for i in range(3)] == ["Notes", "Summary", "Transcript"]
    assert window.summary_field.parent() is tabs.summary_page and not window.summary_field.isHidden()
    window.summary.setPlainText("Agreed: Friday.")
    tabs.transcript.setPlainText(SAID)
    assert [tabs.bar.tabText(i) for i in range(3)] == ["Notes", "Summary •", "Transcript •"]
    tabs.go(meeting_tabs.TRANSCRIPT)
    assert tabs.current() == meeting_tabs.TRANSCRIPT
    window.toggle_meeting()  # out of the mode: the editor alone, the summary back where it was
    assert tabs.bar.isHidden() and tabs.current() == meeting_tabs.NOTES
    assert window.lower_layout.indexOf(window.summary_field) == home and not window.summary_field.isHidden()  # it holds text


def test_alt_numbers_move_between_the_tabs(window):
    window.toggle_meeting()
    keys = {s.key().toString(): s for s in window.tabs.findChildren(meeting_tabs.QShortcut)}
    assert set(keys) == {"Alt+1", "Alt+2", "Alt+3"}
    keys["Alt+2"].activated.emit()
    assert window.tabs.current() == meeting_tabs.SUMMARY
    keys["Alt+1"].activated.emit()
    assert window.tabs.current() == meeting_tabs.NOTES


def test_save_keeps_the_notes_summary_and_transcript_apart(window, ctx):
    """Only the notes are read for operators: the @ in the transcript makes no card and no task."""
    window.toggle_meeting()
    window.meet_name.setText("Seal kit call")
    window.content.setPlainText("Seal kit ships Friday.")
    window.summary.setPlainText("Agreed: Friday.")
    window.tabs.transcript.setPlainText(SAID)
    window.read_items()
    assert not window.item_cards.cards
    d = window.draft()
    assert d.transcript == SAID and d.summary == "Agreed: Friday." and d.meeting
    window.save()
    m = Model(ctx.conn)
    c = max((c for c in m.live_captures() if c.item == "notes"), key=lambda c: c.id)
    assert c.summary == "Agreed: Friday." and not c.created_task
    (doc,) = [x for x in c.document_ids if transcripts.is_transcript(m, x)]
    path = ctx.data_root / "Tasks" / c.task / "Files" / m.documents[doc].name
    assert path.read_text(encoding="utf-8") == SAID


def test_a_draft_keeps_its_transcript_as_a_file_and_brings_it_back(window, ctx):
    window.toggle_meeting()
    window.content.setPlainText("Half-written notes.")
    window.tabs.transcript.setPlainText(SAID)
    assert window.keep_draft()
    folder = drafts.folder(ctx.data_root, window.draft_id)
    data = drafts.read(ctx.data_root, window.draft_id)
    stored = data["transcript"]
    assert stored and (folder / stored).read_text(encoding="utf-8") == SAID
    assert "coupling" not in (folder / drafts.DRAFT_JSON).read_text(encoding="utf-8")  # beside draft.json, not in it
    kept = window.draft_id
    window.tabs.transcript.setPlainText(SAID + "And one more line.\n")  # changed: a new file, the old one left
    assert window.keep_draft()
    assert drafts.read(ctx.data_root, kept)["transcript"] != stored and (folder / stored).exists()
    window.hide()  # closing keeps it in Drafts, and the next open is empty
    window.show_capture()
    assert window.tabs.transcript.toPlainText() == "" and window.draft_id != kept
    window.open_draft(kept)
    assert window.tabs.transcript.toPlainText() == SAID + "And one more line.\n" and window.meeting_on


@pytest.fixture
def browse(ctx):
    from docrepo.ui.browse_window import BrowseWindow

    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    w.hide()
    capture.deleteLater()
    w.deleteLater()


def test_add_summary_and_add_transcript_on_a_meetings_page(browse, ctx, monkeypatch):
    """Decision 798: on the meeting's page, each a box to paste into; a second transcript is transcript-2.md."""
    from PySide6.QtCore import QUrl

    from docrepo.ui import meeting_add

    meet = next(t.id for t in Model(ctx.conn).open_meetings())
    browse.go_task(meet)
    group = browse.task_pane.header.groups["summary"]
    assert group.present and "Add summary…" in group.text()
    answers = iter(["From the call's summary, made up.", "First recording, made up.", "Second recording, made up.", None])
    monkeypatch.setattr(meeting_add, "ASK", lambda parent, title, hint, text: next(answers))
    browse.on_link(QUrl(f"addsummary:{meet}"))
    browse.on_link(QUrl(f"addtranscript:{meet}"))
    browse.on_link(QUrl(f"addtranscript:{meet}"))
    browse.on_link(QUrl(f"addsummary:{meet}"))  # cancelled: nothing changes
    m = Model(ctx.conn)
    assert [s for _, s in transcripts.summaries(m, meet)] == ["From the call's summary, made up."]
    assert [d.name for d in transcripts.meeting_transcripts(m, meet)] == ["transcript.md", "transcript-2.md"]
    browse.go_task(meet)
    text = browse.task_pane.header.groups["summary"].text()
    assert "From the call's summary, made up." in text and "transcript-2.md" in text and "Edit summary…" in text
