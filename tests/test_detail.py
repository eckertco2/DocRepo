"""The browse tool's pages, as the HTML its detail pane shows."""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from docrepo import prompts, search
from docrepo.captures import read_content
from docrepo.config import Settings
from docrepo.detail import PageState, Pages
from docrepo.model import Model
from docrepo.save import CaptureDraft, save_capture

TODAY = date(2026, 10, 8)


@pytest.fixture
def pages(sample_root):
    conn, root, _ = sample_root
    m = Model(conn)
    return Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)


def text(html: str) -> str:
    """The page's words, without tags, on one line."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("&#x27;", "'").split())


def links(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


def test_a_task_page(pages):
    html = pages.task_page("T000008", PageState())
    words = text(html)
    assert words.startswith("Reactor impeller upgrade › Installation In progress")
    for part in ("Lead Me 8 h", "Assignees Tom Becker 60 h , Mike Ortiz 60 h", "Due Fri 30 Oct in 22 d", "Deadline Fri 30 Oct, Turnaround ends in 22 d",
                 "Created Tue 22 Sep from C000005", "Raw text log Summaries Status log Files Subtasks",
                 "Scope: This task · With ancestors · With subtasks · Family", "SUBTASKS (3)"):
        assert part in words, part
    assert {"task:T000001", "person:P003", "capture:C000005", "tab:log", "scope:family", "chap:T000012", "label:Line%201"} <= set(links(html))


def test_tabs_scopes_and_chapters(pages):
    log = text(pages.task_page("T000008", PageState(tab="log")))
    assert "Work started" in log and "↳ New subtask: Rigging plan · Mike Ortiz, due 14 Oct" in log
    closed = text(pages.task_page("T000008", PageState(tab="log", scope="self")))
    assert "SUBTASKS" not in closed and "Open all chapters" not in closed
    opened = text(pages.task_page("T000008", PageState(tab="log", chapters={"T000012"})))
    assert "Rigging plan In progress Lift study done" in opened and "Mike to write the rigging plan" in opened
    files = pages.task_page("T000001", PageState(tab="files"))
    assert "show:copy:" in files and "Impeller datasheet rev B.pdf" in text(files)
    subs = text(pages.task_page("T000008", PageState(tab="subtasks")))
    assert "In progress Rigging plan" in subs and "Not started Book the alignment contractor Urgent" in subs
    sums = text(pages.task_page("T000001", PageState(tab="summaries")))
    assert sums.count("↗") >= 1  # entries from subtasks name the task they come from


def test_newest_first_and_long_entries(pages, sample_root):
    conn, root, fs = sample_root
    long_text = "First sentence of a long note. " + "More words go here to make it long. " * 15
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=long_text, task="T000012"), datetime(2026, 10, 8, 15, 0))
    m = Model(conn)
    p = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)
    folded = p.task_page("T000012", PageState(scope="self"))
    assert "more:C000026" in folded and "Show all" in folded
    shown = p.task_page("T000012", PageState(scope="self", expanded={"C000026"}))
    assert "Show less" in shown
    newest = text(p.task_page("T000012", PageState(scope="self", order="new"))).split("Order:", 1)[1]
    assert newest.index("First sentence of a long note") < newest.index("Mike to write the rigging plan")


def test_captured_content_is_shown_as_text_never_as_markup(sample_root):
    conn, root, fs = sample_root
    r = save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content='<a href="task:T000001">click</a> <b>bold</b>'),
                     datetime(2026, 10, 8, 15, 0))
    m = Model(conn)
    html = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "").capture_page(r.capture_id, read_content(root, m.captures[r.capture_id]))
    assert "&lt;a href=&quot;task:T000001&quot;&gt;click&lt;/a&gt;" in html and "<b>bold</b>" not in html


def test_an_unfiled_capture_page(pages, sample_root):
    conn, root, _ = sample_root
    html = pages.capture_page("C000021", read_content(root, Model(conn).captures["C000021"]))
    words = text(html)
    assert words.startswith("Capture C000021 Steam trap survey quote Unfiled.")
    assert "What Save did Kept as an unfiled capture, to file later" in words and "Source Email" in words
    assert "Quote 4471.pdf D000003" in words and "CONTENT TEXT From:" in words


def test_a_filed_capture_page_says_what_save_did(pages, sample_root):
    conn, root, _ = sample_root
    words = text(pages.capture_page("C000017", read_content(root, Model(conn).captures["C000017"])))
    assert "What Save did Updated Vendor drawing package" in words and "Changes Due: 2026-10-16 → 2026-10-23" in words
    unreadable = text(pages.capture_page("C000017", None))
    assert "couldn't be read" in unreadable


def test_document_person_and_label_pages(pages):
    doc = text(pages.document_page("D000002"))
    assert "Installation procedure.docx" in doc and "Tasks Installation" in doc and "1 change in the raw text log of its tasks" in doc
    person = text(pages.person_page("P003"))
    assert "Tom Becker" in person and "Aliases Tom, Thomas" in person and "h this week" in person and "Agenda: 1 open item" in person
    me = text(pages.person_page("P001"))
    assert me.startswith("Person P001 Me me")
    label = text(pages.label_page("Safety"))
    assert "Keywords" in label and "Rails need to be painted red inherited" in label


def test_capacity_detail(pages, sample_root):
    from docrepo import views

    conn, _, _ = sample_root
    weeks = views.capacity_weeks(TODAY)
    rows = views.capacity_grid(conn, pages.m, weeks)
    html = pages.capacity_detail(rows, weeks, ("P004", 2), ["T000017"], ["T000016"])
    words = text(html)
    assert words.startswith("Mike Ortiz, week of Mon 19 Oct Installation")
    assert "Unestimated (people, no hours): Rails need to be painted red" in words


def test_copy_prompt_sends_content_text_and_file_text(sample_root):
    conn, root, _ = sample_root
    m = Model(conn)
    general = prompts.DEFAULTS[0]
    blocks = prompts.task_blocks(general, m, "T000009", content_of=lambda cid: read_content(root, m.captures[cid]) or "")
    assert blocks == [("Latest raw text log entry (C000017)", "Vendor drawings came in late, so the package is now due Oct 23.")]
    report = prompts.DEFAULTS[2]
    blocks = prompts.task_blocks(report, m, "T000008", content_of=lambda cid: "", file_text_of=lambda d: search.extracted_text(root, d))
    assert any(label == "Text of Installation procedure.docx" and "7. Alignment" in body for label, body in blocks)
    every = prompts.SummaryType("all.md", "All", ("raw_text_all",), "self", "Summarize.")
    labels = [label for label, _ in prompts.task_blocks(every, m, "T000008", content_of=lambda cid: "x")]
    assert labels[0].startswith("Raw text log, Installation, 2026-09-22 10:31") and any("Installation procedure.docx changed" in x for x in labels)
