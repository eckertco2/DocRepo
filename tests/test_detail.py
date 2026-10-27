"""The browse tool's pages, as the HTML its detail pane shows."""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from docrepo import people, prompts, search, tasks
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
    """The visual overhaul's O9 (release 5.21, decisions 64 to 69): the task's story, top to bottom."""
    html = pages.task_page("T000008", PageState())
    words = text(html)
    assert words.startswith("Reactor impeller upgrade › Installation In progress Line 1 Strategic Plan Install and align")
    order = ["Current status Mon 5 Oct · 3 days ago Procedure rev 2 approved. Waiting on the rigging plan.",
             "When Due Fri 30 Oct in 22 days Deadline too · Turnaround ends Starts Mon 19 Oct in 11 days",
             "Who Lead Me 8 h Assignees Tom Becker 60 h Mike Ortiz 60 h", "Subtasks 3 of 3 open New subtask Rigging plan 14 Oct · 6 d",
             "▸ Details T000008 · Created Tue 22 Sep from C000005", "Captures 6 Status log 14 Summaries 1 Files 3 With subtasks ▾ ⇅ Oldest first",
             "This task September 2026", "Subtasks · 3"]
    at = [words.find(part) for part in order]
    assert -1 not in at and at == sorted(at), dict(zip(order, at))
    for gone in ("Reminder", "—", "Subtasks Summaries", "SUBTASKS", "Scope:", "Order:", "Top-level task"):  # empty fields, the old tab and lines
        assert gone not in words, gone
    assert {"task:T000001", "person:P003", "label:Line%201", "fold:details", "menu:scope", "menu:order", "new:T000008", "tab:log",
            "chap:T000012"} <= set(links(html))
    assert 'src="avatar:me"' in html and 'src="avatar:TB"' in html and 'src="mark:ip"' in html and 'src="progress:0:3"' in html
    opened = pages.task_page("T000008", PageState(details=True))
    assert "ID T000008 Created Tue 22 Sep from C000005 Folder Tasks\\T000008" in text(opened) and "folder:T000008" in opened  # Start's in When


def test_the_page_shows_only_what_says_something(pages):
    """Decision 65: a deadline with no Due takes Due's place (M0003); a task with neither says No due date; a passed reminder
    is "ago"; a routine meeting counts to its next one, with hours per occurrence and its agenda before Details."""
    words = text(pages.task_page("T000002", PageState()))
    assert "When Deadline Sat 31 Oct in 23 days Verification walkthrough Who" in words and "No due date" not in words
    assert "Current status Tue 1 Sep · 5 weeks ago" in words  # the Excel import's status: as old as the task
    words = text(pages.task_page("T000016", PageState()))
    assert "When Due No due date Reminder Wed 7 Oct yesterday Agenda Business team meeting Tue 13 Oct" in words
    assert "No status yet. Add one" in words and "update:T000016" in pages.task_page("T000016", PageState())
    words = text(pages.task_page("T000010", PageState()))
    assert "When Next meeting Tue 13 Oct in 5 days Who Lead Priya Shah 1.5 h per occurrence" in words
    assert words.index("Agenda 4 open Open agenda") < words.index("Details")
    assert "↻ Weekly Meeting" in words


def test_subtasks_closed_ones_and_the_description(pages, sample_root):
    """Decisions 66 and 67: the closed subtasks behind Show closed; a long description folds to its first 180 characters."""
    words = text(pages.task_page("T000001", PageState()))
    assert "Subtasks 3 of 4 open" in words and "Show 1 closed" in words and "Order spare mechanical seal" not in words.split("Details")[0]
    shown = text(pages.task_page("T000001", PageState(closed=True)))
    assert "Order spare mechanical seal" in shown.split("Details")[0] and "Hide closed" in shown
    conn, root, _ = sample_root
    tasks.update_task(conn, Settings(me="P001"), "T000017", at=datetime(2026, 10, 8, 9, 0), via="Browse tool",
                      description="Rails need to be painted red. " + "The rails by the stairs and the platform need it first. " * 4 + "Todd's on it.")
    m = Model(conn)
    p = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)
    folded = p.task_page("T000017", PageState())
    assert "fold:desc" in folded and "Todd's on it" not in text(folded) and "…" in text(folded)
    assert "Todd's on it. Less" in text(p.task_page("T000017", PageState(desc=True)))


def test_the_wide_page_has_its_facts_on_the_right(pages):
    """Decision 69: from 760 px, When, Who and Details move into a rail, with Details open; narrow, When and Who stack."""
    main, rail = pages.task_page("T000008", PageState(), 900).split('class="rule"', 1)
    assert "Current status" in main and "Subtasks" in main and "Captures" in main and "When" not in text(main)
    # The browse tool draws it in two parts, the notes page's editor between them (release 5.25).
    top, bottom = pages.task_page("T000008", PageState(), 900, "top"), pages.task_page("T000008", PageState(), 900, "bottom")
    assert "Captures" not in text(top) and "Folder" in text(top) and text(bottom).startswith("Captures 6 Status log")
    assert all(x in text(rail) for x in ("When Due Fri 30 Oct", "Who Lead", "Details ID T000008", "Folder"))
    assert '<td width="50%"' in pages.task_page("T000008", PageState(), 600)
    assert '<td width="50%"' not in pages.task_page("T000008", PageState(), 500)


def test_tabs_scopes_and_chapters(pages):
    log = text(pages.task_page("T000008", PageState(tab="log")))
    assert "Work started" in log and "↳ New subtask: Rigging plan · Mike Ortiz, due 14 Oct" in log
    closed = text(pages.task_page("T000008", PageState(tab="log", scope="self")))
    assert "Subtasks ·" not in closed and "This task ▾" in closed  # the scope's name is its menu's
    assert log.count("Status log") == closed.count("Status log") and log.split("Status log ")[1][:2] != closed.split("Status log ")[1][:2]
    opened = text(pages.task_page("T000008", PageState(tab="log", chapters={"T000012"})))
    assert "Rigging plan In progress Lift study done" in opened and "Mike to write the rigging plan" in opened
    files = pages.task_page("T000001", PageState(tab="files"))
    assert "show:copy:" in files and "Impeller datasheet rev B.pdf" in text(files) and "⇅" not in text(files)
    old = text(pages.task_page("T000008", PageState(tab="subtasks")))  # a page left on the old Subtasks tab shows the raw text log
    assert "This task September 2026 Tue 22 Sep File · Started this task" in old
    sums = text(pages.task_page("T000001", PageState(tab="summaries")))
    assert sums.count("↗") >= 1  # entries from subtasks name the task they come from


def test_dates_in_words():
    from docrepo.dates import ago, days_words

    assert [days_words(date(2026, 10, d), TODAY) for d in (5, 7, 8, 9, 30)] == ["3 days overdue", "1 day overdue", "today", "tomorrow", "in 22 days"]
    assert [ago(date(2026, m, d), TODAY) for m, d in ((10, 8), (10, 7), (10, 5), (9, 1), (6, 1))] == [
        "today", "yesterday", "3 days ago", "5 weeks ago", "4 months ago"]


def test_newest_first_and_long_entries(pages, sample_root):
    conn, root, fs = sample_root
    long_text = "First sentence of a long note. " + "More words go here to make it long. " * 15
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=long_text, task="T000012"), datetime(2026, 10, 8, 15, 0))
    m = Model(conn)
    p = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)
    # Captures (release 5.25, decision 104): the text is the notes page's to show; each entry links to its block there.
    page = p.task_page("T000012", PageState(scope="self"))
    assert "goto:T000012:C000026" in page and "More words go here" not in page
    conn.execute("UPDATE task_pages SET body = '' WHERE task = 'T000012'")
    off = Pages(Model(conn), TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn).task_page("T000012", PageState(scope="self"))
    assert "Not on the notes page" in text(off) and "readd:T000012:C000026" in off
    newest = text(p.task_page("T000012", PageState(scope="self", order="new"))).split("Newest first", 1)[1]
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


def test_release_59_fields_on_the_pages(sample_root):
    """Release 5.9: a person's email, group and role; a task's Plant event and reference fields; a parent label's page."""
    conn, root, _ = sample_root
    tasks.update_task(conn, Settings(me="P001"), "T000012", at=datetime(2026, 10, 8, 9, 0), via="Browse tool", plant_event=True,
                      references={"Work order #": "48213"})
    people.add_label(conn, "Production line")
    people.update_label(conn, "Line 1", parent="Production line")
    m = Model(conn)
    pages = Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)
    assert "Email tom.becker@example.com Group Maintenance Role Planner" in text(pages.person_page("P003"))
    task = text(pages.task_page("T000012", PageState()))
    assert "In progress Plant event" in task and "Work order # 48213" in task
    parent = text(pages.label_page("Production line"))
    assert "Labels under it Line 1" in parent and "a heading: tasks get one of its labels, not it" in parent
    assert text(pages.label_page("Line 1")).startswith("Label › Production line Line 1 Under Production line")
