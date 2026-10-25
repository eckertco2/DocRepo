"""Parse and populate against the mockup's test vectors: every capture and date phrase in test-vectors.md,
read with today = Thursday 2026-10-08 and the sample people and labels."""
from __future__ import annotations

import re
from datetime import date

import pytest
from conftest import FIXTURES

from docrepo.parse import ParseLabel, ParsePerson, ParseResult, find_dates, parse_capture
from docrepo.sample import read_sample

TODAY = date(2026, 10, 8)
SAMPLE = read_sample()
# The vectors leave Todd off the people list, so he's found as a new person.
PEOPLE = [ParsePerson(p["id"], p["name"], tuple(p["aliases"]), p["status"], bool(p.get("me"))) for p in SAMPLE["people"] if p["id"] != "P006"]
NAMES = {p["id"]: p["name"] for p in SAMPLE["people"]}
LABELS = [ParseLabel(label["name"], tuple(label["keywords"])) for label in SAMPLE["labels"]]


def split_row(line: str) -> list[str]:
    """A Markdown table row's cells, with \\|, \\n and \\\\ unescaped."""
    cells, cell, i = [], "", 1
    body = line.strip()
    while i < len(body) - 1:
        ch = body[i]
        if ch == "\\" and body[i + 1] in "\\|n":
            cell += {"\\": "\\", "|": "|", "n": "\n"}[body[i + 1]]
            i += 2
            continue
        if ch == "|":
            cells.append(cell.strip())
            cell = ""
        else:
            cell += ch
        i += 1
    cells.append(cell.strip())
    return cells


def section_rows(start: str, end: str | None) -> list[list[str]]:
    text = (FIXTURES / "test-vectors.md").read_text(encoding="utf-8")
    part = text[text.index(start):text.index(end) if end else len(text)]
    rows = [split_row(line) for line in part.split("\n") if line.startswith("| ") and not line.startswith(("|---", "| Capture type", "| Phrase"))]
    return rows


def show(r: ParseResult) -> str:
    """What the vectors list for a parse, in the mockup's words."""
    def who(ws):
        return ", ".join(NAMES[w.id] if w.id else f"{w.name} (new person)" for w in ws)

    parts = [
        r.title and f'Title "{r.title}"', r.state and f"State {r.state}", r.status and f'Current status "{r.status}"',
        r.due and f"Due {r.due}", r.deadline and f"Deadline {r.deadline}",
        r.deadline_desc and f'Deadline description "{r.deadline_desc}"', r.reminder and f"Reminder {r.reminder}",
        r.start and f"Start {r.start}", r.recurrence and f"Recurrence {r.recurrence}", r.urgent and "Urgent", r.plant_event and "Plant event",
        r.labels and f"Labels [{', '.join(r.labels)}]", r.leads and f"Lead [{who(r.leads)}]",
        r.assignees and f"Assignees [{who(r.assignees)}]", r.lead_hours and f"Lead hours {r.lead_hours}",
        r.assignee_hours and f"Assignee hours {r.assignee_hours}", ". ".join(f"{k} {v}" for k, v in r.refs.items()),
        *[re.sub(r"\.\Z", "", f.why) for f in r.found if f.why],
    ]
    parts = [p for p in parts if p]
    return ". ".join(parts) + "." if parts else "Nothing."


CAPTURE_ROWS = section_rows("## Parse and populate", "### Reference fields")
#: Release 5.9's reference fields, read with two made-up field names.
REF_ROWS = section_rows("### Reference fields", "### Date phrases")
REFS = ("Work order #", "Permit no.")
DATE_ROWS = section_rows("### Date phrases", None)


def test_the_vectors_were_read():
    assert len(CAPTURE_ROWS) > 140 and len(REF_ROWS) > 5 and len(DATE_ROWS) > 90


@pytest.mark.parametrize("kind, content, expected", CAPTURE_ROWS, ids=[row[1][:60] for row in CAPTURE_ROWS])
def test_parse_and_populate(kind, content, expected):
    capture_type = "new_task" if kind == "New task" else "update"
    assert show(parse_capture(content, capture_type, TODAY, PEOPLE, LABELS)) == expected


@pytest.mark.parametrize("kind, content, expected", REF_ROWS, ids=[row[1][:60] for row in REF_ROWS])
def test_reference_fields(kind, content, expected):
    capture_type = "new_task" if kind == "New task" else "update"
    assert show(parse_capture(content, capture_type, TODAY, PEOPLE, LABELS, refs=REFS)) == expected


@pytest.mark.parametrize("phrase, expected", DATE_ROWS, ids=[row[0] for row in DATE_ROWS])
def test_date_phrases(phrase, expected):
    hits = find_dates(phrase, TODAY)
    got = "not a date" if not hits else f"{hits[0].date}, Start {hits[0].from_}" if hits[0].from_ else str(hits[0].date)
    assert got == expected
