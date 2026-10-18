"""The status log and raw text log as stories, checked against the browse tool mockup.

``tests/fixtures/stories.json`` is the mockup's ``exportStories``: what its ``storyOf`` and ``noteLead`` give
for every sample task, with times cut to the minute.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from docrepo.captures import read_content
from docrepo.model import Model, StatusEntry
from docrepo.stories import Stories, state_words
from conftest import FIXTURES

TODAY = date(2026, 10, 8)
EXPECTED = json.loads((FIXTURES / "stories.json").read_text(encoding="utf-8"))


@pytest.fixture
def stories(sample_root):
    conn, root, _ = sample_root
    m = Model(conn)
    return Stories(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "Me")


def as_mockup(e) -> dict:
    d = {"at": e.at[:16], "kind": e.kind}
    if e.kind == "created":
        d.update(state=e.state, parents=e.parents, how=e.how, text=e.text, status=e.status, facts=e.facts)
    elif e.kind == "update":
        d.update(state=e.state, stateWords=e.state_words, main=e.main, facts=e.facts, via=e.via)
    else:
        d.update(task=e.task, verb=e.verb, note=e.note, text=e.text)
    return d


@pytest.mark.parametrize("task_id", sorted(EXPECTED))
def test_each_story_matches_the_mockup(stories, task_id):
    assert [as_mockup(e) for e in stories.story(task_id)] == EXPECTED[task_id]["story"]


@pytest.mark.parametrize("task_id", sorted(EXPECTED))
def test_each_raw_text_log_matches_the_mockup(stories, task_id):
    got = [{"at": r.at[:16], "lead": r.lead, "title": r.title, "text": r.text} for r in stories.raw_items(task_id)]
    assert got == EXPECTED[task_id]["raw"]


def test_every_sample_task_is_covered(stories):
    assert set(EXPECTED) == set(stories.m.tasks)


def test_state_words():
    assert [state_words("Not started", "In progress"), state_words("Parked", "In progress"), state_words("Closed", "In progress"),
            state_words("In progress", "Parked"), state_words("Closed", "Not started"), state_words("In progress", "Not started")] == [
        "Work started", "Picked back up", "Reopened", "Parked", "Reopened", "Set back to Not started"]


def entry(field: str, before: str | None, after: str | None, target: str | None = None) -> StatusEntry:
    return StatusEntry("T000008", "2026-10-08 10:00:00", field, before, after, "Browse tool", target)


@pytest.mark.parametrize(("field", "before", "after", "said"), [
    ("Due", None, "2026-10-23", "Due date set for Fri 23 Oct."),
    ("Due", "2026-10-16", "2026-10-23", "Due date moved to Fri 23 Oct."),
    ("Deadline", "2026-10-30", None, "Deadline cleared."),
    ("Reminder", None, "2026-10-12", "Reminder set for Mon 12 Oct."),
    ("Lead", "Priya Shah", "Priya Shah, Me", "I now lead."),
    ("Assignees", "Tom Becker", "Mike Ortiz", "Mike Ortiz was assigned. Tom Becker was unassigned."),
    ("Assignee hours", None, "6", "Assignee hours set to 6 h."),
    ("Urgent", "No", "Yes", "Marked urgent."),
    ("Recurrence", None, "Weekly", "Now repeats weekly."),
    ("Repeat until", None, "2027-03-31", "Repeats until Wed 31 Mar 2027."),
    ("Parents", "Installation", "Installation; Q4 cost reduction", "Also put under Q4 cost reduction."),
    ("Title", "Rigging", "Rigging plan", "Renamed “Rigging plan”."),
    ("Description", "Old", "New", "Description edited."),
    ("Labels", "Safety", "Safety, Line 1", "Label Line 1 added."),
    ("Inherit parent labels", "Yes", "No", "No longer inherits its parents' labels."),
])
def test_field_sentences(stories, field, before, after, said):
    assert stories.field_sentence(entry(field, before, after)) == said


def test_agenda_sentences_for_a_person_and_a_meeting(stories):
    assert stories.field_sentence(entry("Agenda", None, "Tom Becker", "P003")) == "Added to Tom Becker's agenda."
    assert stories.field_sentence(entry("Agenda", "Tom Becker", "Discussed", "P003")) == "Discussed with Tom Becker."
    assert stories.field_sentence(entry("Agenda", "Business team meeting", "Removed", "T000010")) == "Taken off the agenda of Business team meeting."


def test_the_owner_is_told_as_i_by_name(sample_root):
    conn, root, _ = sample_root
    m = Model(conn)
    s = Stories(m, TODAY, lambda cid: "", "Alex Morgan")
    assert s.field_sentence(entry("Assignees", None, "Alex Morgan")) == "I was assigned."


def test_subtask_tree_lists_each_subtask_once_with_its_depth(stories):
    assert stories.subtask_tree("T000001") == [("T000007", 0), ("T000008", 0), ("T000012", 1), ("T000015", 1), ("T000019", 1),
                                               ("T000009", 0), ("T000011", 0)]
