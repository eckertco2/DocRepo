"""Decisions across projects (release 5.124; the design workspace's ``docs/mods/cold-eyes-plan.md``, section 3, decisions
475 to 480): what counts, a decision's words and where it was decided, ``type:decision`` in Search everything, the task
page's Decisions section, the register's Copy and Task.md's Decisions table. Every decision here is made up."""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from docrepo import decisions, edits, search
from docrepo.captures import read_content
from docrepo.config import Settings
from docrepo.detail import PageState, Pages
from docrepo.model import Capture, Model
from docrepo.pages import pages_touched, write_pages
from docrepo.save import CaptureDraft, save_capture

SETTINGS = Settings(me="P001")
TODAY = date(2026, 10, 9)
REACTOR, VERIFY, INSTALLATION, BUSINESS, RIGGING = "T000001", "T000002", "T000008", "T000010", "T000012"
NOTES = """#Reactor impeller upgrade
Impeller is on site.
- **decision, we go with the 50 t crane. It's cheaper than two lifts.
  - Tom checks the ground bearing
#Rigging plan **decision, lift on the 20th."""


@pytest.fixture
def env(sample_root):
    conn, root, fs = sample_root

    def save(content: str, task: str, at: datetime, **more) -> object:
        r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=content, task=task, **more), at)
        assert r.made.get("decision"), r  # a note on a task's page made of items is no capture of its own (release 5.69)
        return r

    def model() -> Model:
        return Model(conn)

    def pages() -> Pages:
        m = Model(conn)
        return Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)

    return conn, root, fs, save, model, pages


@pytest.fixture
def meeting(env):
    """The Business team meeting's notes of 8 Oct: a decision on Reactor impeller upgrade, one on Rigging plan under it."""
    r = env[3](NOTES, BUSINESS, datetime(2026, 10, 8, 14, 10), meeting=True)
    return r


def content_of(env):
    root, m = env[1], env[4]()
    return lambda cid: read_content(root, m.captures[cid])


def text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("&#x27;", "'").split())


# ================= what counts, and its words (decisions 475 and 478) =================
def test_a_decision_is_a_live_capture_saved_as_a_decision_item(env, meeting):
    m = env[4]()
    made = [m.captures[c] for c in meeting.items]
    assert [c.item for c in made] == ["note", "decision", "decision"]
    assert [decisions.is_decision(c) for c in made] == [False, True, True]
    assert not decisions.is_decision(m.captures[meeting.capture_id])  # the notes themselves aren't one


def test_its_words_are_its_first_line_and_the_rest_its_tooltip(env, meeting):
    found = decisions.every(env[4](), content_of(env))
    crane, lift = found
    assert crane.words == "We go with the 50 t crane. It's cheaper than two lifts."  # its whole line (decision 203), not only its title
    assert crane.more == "We go with the 50 t crane. It's cheaper than two lifts.\n  - Tom checks the ground bearing"  # a person by name
    assert (lift.words, lift.more) == ("Lift on the 20th.", "")  # the # task taken out: its Task column says which
    assert decisions.every(env[4]())[0].words == "We go with the 50 t crane"  # without its text to read, its title


@pytest.mark.parametrize(("content", "formatted", "words"), [
    ("**decision, we keep the spare seal.", False, "We keep the spare seal."),
    ("  - **Decision, we keep the spare seal.", False, "We keep the spare seal."),
    ("#[Rigging plan](T000012) **decision, @L.[Tom Becker](P003) signs the lift plan.", False, "Tom Becker signs the lift plan."),
    ("- \\*\\*decision, we **keep** the spare seal.", True, "We keep the spare seal."),
    ("**decision,", False, "Spare seal"),  # nothing of its own: its title
    (None, False, "Spare seal"),
])
def test_words_of(content, formatted, words):
    c = Capture("C000099", "2026-10-08 14:10:00", "typed", "T000012", ["note"], None, None, None, "Spare seal", None, None, None,
                formatted=formatted, item="decision")
    assert decisions.words_of(c, content)[0] == words


def test_where_it_was_decided(env, meeting):
    save = env[3]
    save("**decision, we order the long-lead bearings now.", RIGGING, datetime(2026, 10, 9, 10, 0), meeting=True, meeting_name="Vendor call")
    save("**decision, we keep the old guard design.", INSTALLATION, datetime(2026, 10, 9, 11, 0))
    m = env[4]()
    found = decisions.every(m)
    assert [(d.meeting_name, d.where(TODAY)) for d in found] == [
        ("", ""),  # typed in a capture, not a meeting's notes
        ("Vendor call", "Vendor call, 9 Oct"),  # a new meeting: its name, and its day
        ("Business team meeting", "Business team meeting, 8 Oct"),  # a regular meeting's name without its day
        ("Business team meeting", "Business team meeting, 8 Oct")]
    assert m.task(found[1].meeting).title == "Vendor call" and m.task(found[2].meeting).title == "Business team meeting 8 Oct"
    assert decisions.every(m)[2].where(date(2027, 1, 4)) == "Business team meeting, 8 Oct 2026"  # another year says it


def test_a_task_lists_its_own_and_its_subtasks_decisions_newest_first(env, meeting):
    save = env[3]
    save("**decision, we keep the old guard design.", INSTALLATION, datetime(2026, 10, 9, 11, 0))
    m = env[4]()
    found = decisions.of_tasks(m, m.scope_ids(REACTOR, "descendants"))
    assert [(d.words, d.task) for d in found] == [
        ("We keep the old guard design", INSTALLATION), ("We go with the 50 t crane", REACTOR), ("Lift on the 20th", RIGGING)]  # one save's in order
    assert [d.task for d in decisions.of_tasks(m, [RIGGING])] == [RIGGING]
    assert decisions.of_tasks(m, [VERIFY]) == []


def test_discarded_decisions_and_tasks_are_left_out(env, meeting):
    conn, root, fs = env[:3]
    m = env[4]()
    crane = next(d.capture for d in decisions.every(m) if d.task == REACTOR)
    edits.discard_capture(conn, root, fs, crane, "typed twice", datetime(2026, 10, 9, 9, 0))
    edits.discard_task(conn, root, fs, SETTINGS, RIGGING, "not needed", datetime(2026, 10, 9, 9, 5))
    m = env[4]()
    assert decisions.every(m) == [] and decisions.of_tasks(m, m.scope_ids(REACTOR, "descendants")) == []


# ================= type:decision in Search everything (decision 476) =================
def found(conn, m, query: str) -> list[tuple[str, str]]:
    return [(r.group, r.title) for r in search.search(conn, m, query, TODAY)]


def test_type_decision_lists_every_decision_newest_first(env, meeting):
    conn, save, m = env[0], env[3], env[4]()
    assert found(conn, m, "type:decision") == [("Decision", "We go with the 50 t crane"), ("Decision", "Lift on the 20th")]
    assert found(conn, m, "type:decisions") == found(conn, m, "type:decision")  # the plural too
    assert found(conn, m, "type:decision crane") == [("Decision", "We go with the 50 t crane")]
    save("**decision, we keep the old guard design.", INSTALLATION, datetime(2026, 10, 9, 11, 0))
    m = env[4]()
    assert found(conn, m, "type:decision")[0] == ("Decision", "We keep the old guard design")
    assert ("Capture", "We go with the 50 t crane") in found(conn, m, "crane")  # without the filter, with the captures


def test_type_decision_with_the_other_filters(env, meeting):
    conn, save = env[0], env[3]
    save("**decision, we keep the old guard design.", INSTALLATION, datetime(2026, 10, 1, 11, 0))
    m = env[4]()
    assert found(conn, m, "type:decision #rigging") == [("Decision", "Lift on the 20th")]
    assert found(conn, m, "type:decision in:installation") == [("Decision", "Lift on the 20th"), ("Decision", "We keep the old guard design")]
    assert found(conn, m, "type:decision after:5 oct") == [("Decision", "We go with the 50 t crane"), ("Decision", "Lift on the 20th")]
    assert found(conn, m, "type:decision before:5 oct") == [("Decision", "We keep the old guard design")]
    assert found(conn, m, "type:decision from:tom") == []  # a decision has no sender
    scope, rest = search.read("type:decision #Rigging plan lift", m, TODAY)
    assert (scope.name, scope.decisions, rest) == ("Decisions in Rigging plan", True, "lift")
    assert not search.read("type:decision type:note", m, TODAY)[0].decisions  # every note: a decision is one too
    assert "decision" in search.HINTS["type"]


def test_type_decision_lists_up_to_200(env, monkeypatch):
    conn, root, fs, save = env[:4]
    for n in range(3):
        save(f"**decision, option {n}.", RIGGING, datetime(2026, 10, 1 + n, 9, 0))
    monkeypatch.setattr(search, "SCOPED_LIMIT", 2)
    assert found(conn, env[4](), "type:decision") == [("Decision", "Option 2"), ("Decision", "Option 1")]
    assert decisions.LIMIT == 200


# ================= the task page's section (decisions 477 and 478) =================
def test_the_section_lists_the_decisions_with_copy(env, meeting):
    parts = env[5]().task_parts(REACTOR, PageState())
    assert parts["decisions_short"] == "2" and 'href="copydecisions:T000001"' in parts["decisions_summary"] and "Copy" in parts["decisions_summary"]
    rows = parts["decisions"]
    assert rows.count('src="lk:decision"') == 2 and 'href="capture:' in rows and f'href="task:{RIGGING}"' in rows
    assert text(rows) == ("We go with the 50 t crane. It's cheaper than two lifts. in Business team meeting, 8 Oct 8 Oct "
                          "Lift on the 20th. ↗ Rigging plan in Business team meeting, 8 Oct 8 Oct")
    assert "Tom checks the ground bearing" in rows  # in its tooltip
    assert list(parts).index("decisions") < list(parts).index("emails")  # after Subtasks, before Email conversations
    assert "decisions" not in env[5]().task_parts(VERIFY, PageState())  # none: no section


def test_a_decision_on_the_meeting_itself_names_it_once(env):
    env[3]("**decision, we order the long-lead bearings now.", RIGGING, datetime(2026, 10, 8, 10, 0), meeting=True, meeting_name="Vendor call")
    rows = env[5]().task_parts(INSTALLATION, PageState())["decisions"]
    assert text(rows) == "We order the long-lead bearings now. in Vendor call, 8 Oct 8 Oct"  # no chip: the line says it


def test_the_section_shows_five_then_all(env):
    save = env[3]
    for n in range(6):
        save(f"**decision, option {n}.", INSTALLATION, datetime(2026, 10, 1 + n, 9, 0))
    few = env[5]().task_parts(INSTALLATION, PageState())["decisions"]
    assert few.count('src="lk:decision"') == 5 and 'href="fold:decisions"' in few and "Show all 6 decisions" in text(few)
    assert text(few).startswith("Option 5.")  # newest first
    every = env[5]().task_parts(INSTALLATION, PageState(decisions=True))["decisions"]
    assert every.count('src="lk:decision"') == 6 and "Show fewer" in text(every)


# ================= the register (decision 479) =================
def test_the_register_as_a_table(env, meeting):
    table = env[5]().decision_register(REACTOR)
    assert table == [("2026-10-08", "We go with the 50 t crane. It's cheaper than two lifts.", "Reactor impeller upgrade", "Business team meeting, 8 Oct"),
                     ("2026-10-08", "Lift on the 20th.", "Rigging plan", "Business team meeting, 8 Oct")]
    md = decisions.markdown([*table, ("2026-10-09", "A | B\nsplit", "Rigging plan", "")])
    assert md.splitlines()[:2] == ["| Date | Decision | Task | Where |", "|---|---|---|---|"]
    assert md.splitlines()[2] == "| 2026-10-08 | We go with the 50 t crane. It's cheaper than two lifts. | Reactor impeller upgrade | Business team meeting, 8 Oct |"
    assert md.splitlines()[4] == "| 2026-10-09 | A \\| B split | Rigging plan |  |"  # a pipe kept, a line break a space
    html = decisions.html(table)
    assert html.startswith("<table") and html.count("<tr>") == 3 and "<th" in html and "It&#x27;s cheaper" in html
    assert env[5]().decision_register(REACTOR, "self") == table[:1]  # the page's scope


# ================= Task.md (decision 479) =================
def test_task_md_has_the_register(env, meeting):
    root = env[1]
    write_pages(env[4](), root, env[2], TODAY, datetime(2026, 10, 9, 9, 0))
    md =(root / "Tasks" / REACTOR / "Task.md").read_text(encoding="utf-8")
    at = md.index("## Decisions")
    assert md.index("## Subtasks") < at < md.index("## Status log")
    lines = md[at:].splitlines()
    assert lines[2:4] == ["| Date | Decision | Task | Where |", "|---|---|---|---|"]
    assert re.fullmatch(r"\| 2026-10-08 \| \[We go with the 50 t crane\. It's cheaper than two lifts\.\]\(\.\./\.\./Captures/2026/10/C\d+/capture\.md\) "
                        r"\| \[Reactor impeller upgrade\]\(Task\.md\) \| Business team meeting, 8 Oct \|", lines[4])
    assert "[Rigging plan](../T000012/Task.md)" in lines[5]
    rigging = (root / "Tasks" / RIGGING / "Task.md").read_text(encoding="utf-8")
    assert "Lift on the 20th." in rigging and "50 t crane" not in rigging  # its own only
    assert "## Decisions" not in (root / "Tasks" / VERIFY / "Task.md").read_text(encoding="utf-8")


def test_renaming_a_meeting_rewrites_the_registers_that_name_it(env, meeting):
    m = env[4]()
    assert {REACTOR, RIGGING, INSTALLATION} <= pages_touched(m, [meeting.meeting])
