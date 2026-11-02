"""Tree files (releases 5.53 to 5.56; the tree files plan, decisions 264 to 287): reading a file or a paste, the checks, Import, the prompts, Export,
edit files on templates and on task trees, the commands and Copilot's folder. The sample names are made up."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from docrepo import cli, db, notes_page, tasks, templates, tree_files as tf
from docrepo.config import Settings
from docrepo.model import Model, load_tasks
from docrepo.templates import Choice, Library
from docrepo.tree_files import Settled

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AT = datetime(2026, 11, 1, 9, 15)
LATER = datetime(2026, 11, 2, 10, 0)
SETTINGS = Settings(me="P001")
TALK = {
    "format": tf.TREE_FORMAT, "anchor": "prep",
    "rows": [
        {"key": "top", "title": "Coating qualification", "description": "From the change record to the review."},
        {"key": "change", "parent": "top", "title": "Change record", "quote": "nothing goes on the line until it's through"},
        {"key": "prep", "parent": "change", "title": "Prepare change record", "duration": 10, "assignees": ["Priya Shah"], "assignee_hours": 30, "quote": "about thirty hours",
         "assumed": ["'two weeks' read as 10 workdays"]},
        {"key": "ok", "parent": "change", "title": "Approval: change record", "duration": 5, "assignees": ["Tom Baker"],
         "start_tie": {"source": "prep", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}, "quote": "then Tom Baker signs it off"},
        {"key": "notice", "parent": "top", "title": "Tell the supplier", "description": "Give them the dates.", "assignees": ["Tyler Nguyen"],
         "start_tie": {"source": "change", "point": "end", "amount": 2, "unit": "workdays", "direction": "after"}, "quote": "two days after the change record's done"},
        {"key": "window", "parent": "top", "title": "Trial execution window", "duration": 5, "assignees": ["Priya Shah", "Mike Ortiz"], "assignee_per_day": 6, "plant_event": True,
         "labels": ["Safety", "Coatings"], "start_tie": {"source": "ok", "point": "end", "amount": 5, "unit": "workdays", "direction": "after"},
         "notes": "- [ ] Confirm operators are trained\n- [ ] Book the lab for samples", "quote": "the window runs five days after", "assumed": ["'five days' read as workdays"]},
        {"key": "review", "parent": "top", "title": "Management review", "meeting": True},
    ],
    "unplaced": ["Ask: who approves if Tom is away?"],
}


def checked(conn, data=None) -> tf.TreePlan:
    return tf.check_tree(json.loads(json.dumps(data or TALK)), Model(conn), "P001", tf.template_names(conn))


def texts(said) -> str:
    return " | ".join(x.text for x in said)


def imported(conn, data=None, settled=None) -> int:
    return tf.import_tree(conn, checked(conn, data), settled or Settled(), AT)


# ---- reading (decision 267) ----
def test_reads_a_plain_object():
    r = tf.read_text('{"format": "x"}')
    assert r.data == {"format": "x"} and not r.wrapped and not r.problem


def test_reads_a_paste_with_a_fence_and_a_sentence_around_it():
    r = tf.read_text('Here it is.\n\n```json\n{"format": "x", "rows": []}\n```\n\nI kept the hours as said.')
    assert r.data == {"format": "x", "rows": []} and r.wrapped
    assert r.text == '{"format": "x", "rows": []}'


def test_reads_a_paste_with_only_words_around_it():
    r = tf.read_text('Sure: {"a": {"b": 1}} Hope that helps.')
    assert r.data == {"a": {"b": 1}} and r.wrapped


@pytest.mark.parametrize(("text", "said"), [
    ("", "nothing here"),
    ("   ", "nothing here"),
    ("just some words", "no JSON object"),
    ('{"rows": [{"key": "a", ', "stops before the file ends"),
    ('{"a": 1,, "b": 2}', "isn't valid JSON"),
    ('{"a": NaN}', "isn't valid JSON"),
    ("[1, 2]", "no JSON object"),
])
def test_names_what_cant_be_read(text, said):
    assert said in tf.read_text(text).problem


def test_a_cut_off_file_makes_nothing(sample_conn):
    r = tf.read_text(json.dumps(TALK, indent=2)[:900])
    assert r.data is None and "cut off" in r.problem


def test_a_byte_order_mark_is_fine():
    assert tf.read_text('\ufeff{"a": 1}').data == {"a": 1}


# ---- the checks ----
def test_a_good_file_has_no_problems(sample_conn):
    p = checked(sample_conn)
    assert p.problems == []
    assert [k for k, _ in p.walk()] == ["top", "change", "prep", "ok", "notice", "window", "review"]
    assert p.tie_count() == 3 and p.assumed_count() == 2 and p.unplaced == TALK["unplaced"]
    assert p.to_type == ["review"]


@pytest.mark.parametrize(("change", "said"), [
    (lambda d: d["rows"].append({"key": "x", "title": "Another top"}), "one top row"),
    (lambda d: d["rows"].__setitem__(0, {"key": "top", "parent": "change", "title": "No top"}), "There's no top row"),
    (lambda d: d["rows"].append({"key": "prep", "parent": "top", "title": "Again"}), "used twice"),
    (lambda d: d["rows"].append({"key": "x", "parent": "nope", "title": "Lost"}), "isn't a row in this file"),
    (lambda d: d["rows"].append({"parent": "top", "title": "No key"}), "has no key"),
    (lambda d: d["rows"].append({"key": "x", "parent": "top"}), "has no title"),
    (lambda d: d["rows"].append({"key": "x", "parent": "top", "title": "T", "urgent": True}), '"urgent" isn\'t a field'),
    (lambda d: d["rows"].append({"key": "x", "parent": "top", "title": "T", "recurrence": "Weekly"}), '"recurrence" isn\'t a field'),
    (lambda d: d["rows"].append({"key": "x", "parent": "top", "title": "T", "start": "2027-01-01"}), '"start" isn\'t a field'),
    (lambda d: d["rows"].append({"key": "x", "parent": "top", "title": "T", "path": "C:/secret.docx"}), '"path" isn\'t a field'),
    (lambda d: d.update(priority="high"), '"priority" isn\'t a field'),
    (lambda d: d.update(unplaced="words"), '"unplaced" should be a list'),
    (lambda d: d.update(rows=[]), "There are no rows"),
    (lambda d: d.update(anchor="nope"), "The anchor"),
    (lambda d: d.update(anchor="ok"), "can't be tied as well"),
    (lambda d: d.update(anchor="change"), "can't be the anchor"),
    (lambda d: d["rows"][2].update(duration=2.5), "whole number of days"),
    (lambda d: d["rows"][2].update(duration=0), "whole number of days"),
    (lambda d: d["rows"][2].update(assignee_hours=-1), "0 or more"),
    (lambda d: d["rows"][2].update(assignee_hours=True), "number of hours"),
    (lambda d: d["rows"][2].update(assignee_per_day=6), "stated two ways"),
    (lambda d: d["rows"][2].update(involvement={"assignees": {"Priya Shah": 150}}), "from 0 to 100"),
    (lambda d: d["rows"][2].update(meeting="yes"), "true or false"),
    (lambda d: d["rows"][2].update(assignees="Priya Shah"), "a list of names"),
    (lambda d: d["rows"][2].update(description="x" * (tf.MAX_TEXT + 1)), "no more than"),
    (lambda d: d["rows"][3]["start_tie"].update(unit="days"), 'unit is "days"'),
    (lambda d: d["rows"][3]["start_tie"].update(direction="around"), "before or after"),
    (lambda d: d["rows"][3]["start_tie"].update(point="middle"), "start or end"),
    (lambda d: d["rows"][3]["start_tie"].update(amount=1.5), "whole number"),
    (lambda d: d["rows"][3]["start_tie"].update(source="nope"), "isn't a row in this file"),
    (lambda d: d["rows"][3]["start_tie"].update(source="ok"), "from the row itself"),
    (lambda d: d["rows"][3]["start_tie"].update(path="x"), 'has "path"'),
    (lambda d: d["rows"][2].update(start_tie={"source": "window", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}), "circle"),
    (lambda d: d.update(of="task T000001"), "export of a task tree"),
])
def test_a_problem_stops_it(sample_conn, change, said):
    data = json.loads(json.dumps(TALK))
    change(data)
    p = checked(sample_conn, data)
    assert said in texts(p.problems), texts(p.problems)
    with pytest.raises(tasks.TaskError):
        tf.import_tree(sample_conn, p, Settled(), AT)
    assert Library(sample_conn).live() == []


def test_a_row_under_itself_is_a_problem(sample_conn):
    data = {"format": tf.TREE_FORMAT, "rows": [{"key": "a", "title": "A"}, {"key": "b", "parent": "c", "title": "B"}, {"key": "c", "parent": "b", "title": "C"}]}
    assert "under itself" in texts(checked(sample_conn, data).problems)


def test_too_many_rows_is_a_problem(sample_conn):
    rows = [{"key": "top", "title": "Top"}, *({"key": f"r{i}", "parent": "top", "title": "R"} for i in range(tf.MAX_ROWS + 1))]
    assert "at most" in texts(checked(sample_conn, {"format": tf.TREE_FORMAT, "rows": rows}).problems)


def test_warnings_dont_stop_it(sample_conn):
    data = json.loads(json.dumps(TALK))
    data["rows"][1].pop("quote")
    data["rows"].append({"key": "long", "parent": "top", "title": "T" * 70, "quote": "q"})
    templates.new_template(sample_conn, "Coating qualification", AT)
    p = checked(sample_conn, data)
    words = texts(p.warnings)
    assert p.problems == []
    for said in ('"Tom Baker" isn\'t on the people list', 'The label "Coatings" doesn\'t exist yet', "Change record has no quote", "the title is long",
                 "already exists", "it would wait"):
        assert said in words, said


def test_a_tie_to_the_end_of_a_row_with_no_length_says_it_would_wait(sample_conn):
    tie = {"source": "a", "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}
    rows = [{"key": "top", "title": "T"}, {"key": "a", "parent": "top", "title": "No length", "quote": "q"}, {"key": "b", "parent": "top", "title": "Waits", "quote": "q", "start_tie": tie}]
    said = texts(checked(sample_conn, {"format": tf.TREE_FORMAT, "rows": rows}).warnings)
    assert "Waits: Start tie counts from the end of No length, which has no Duration" in said


@pytest.mark.parametrize("change", [lambda a: a.update(duration=3), lambda a: a.update(due_tie={"source": "c", "point": "end", "amount": 1, "unit": "workdays", "direction": "after"})])
def test_a_tie_to_the_end_of_a_row_with_an_end_doesnt_wait(sample_conn, change):
    a = {"key": "a", "parent": "top", "title": "A", "quote": "q"}
    change(a)
    tie = {"source": "a", "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}
    rows = [{"key": "top", "title": "T"}, {"key": "c", "parent": "top", "title": "C", "duration": 1, "quote": "q"}, a, {"key": "b", "parent": "top", "title": "B", "quote": "q", "start_tie": tie}]
    assert "no Duration" not in texts(checked(sample_conn, {"format": tf.TREE_FORMAT, "rows": rows}).warnings)


def test_a_tie_to_the_start_of_a_row_with_no_length_is_fine(sample_conn):
    tie = {"source": "a", "point": "start", "amount": 1, "unit": "workdays", "direction": "after"}
    rows = [{"key": "top", "title": "T"}, {"key": "a", "parent": "top", "title": "A", "quote": "q"}, {"key": "b", "parent": "top", "title": "B", "quote": "q", "start_tie": tie}]
    assert "no Duration" not in texts(checked(sample_conn, {"format": tf.TREE_FORMAT, "rows": rows}).warnings)


def test_a_tie_to_a_parent_is_judged_by_its_last_subtask(sample_conn):
    tie = {"source": "p", "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}
    rows = [{"key": "top", "title": "T"}, {"key": "p", "parent": "top", "title": "Parent", "quote": "q"}, {"key": "a", "parent": "p", "title": "Last one", "quote": "q"},
            {"key": "b", "parent": "top", "title": "B", "quote": "q", "start_tie": tie}]
    assert "the end of Last one, which has no Duration" in texts(checked(sample_conn, {"format": tf.TREE_FORMAT, "rows": rows}).warnings)


def test_a_null_is_a_field_left_out(sample_conn):
    data = json.loads(json.dumps(TALK))
    data["rows"][2].update(lead_hours=None, description=None, leads=None)
    data["rows"][6].update(duration=None, start_tie=None)
    assert checked(sample_conn, data).problems == []


def test_keys_may_be_numbers_and_an_llm_may_write_them_as_text(sample_conn):
    data = {"format": tf.TREE_FORMAT, "rows": [{"id": 1, "title": "Top"}, {"id": 2, "parent": "1", "title": "A", "quote": "q"},
                                                 {"id": 3, "parent": 1, "title": "B", "quote": "q", "start_tie": {"source": "2", "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}}]}
    p = checked(sample_conn, data)
    assert p.problems == []
    top = tf.import_tree(sample_conn, p, Settled(), AT)
    assert [x.title for x, _ in Library(sample_conn).walk(top)] == ["Top", "A", "B"]


# ---- names (decision 272) ----
def test_a_name_is_matched_by_name_or_alias_in_any_case(sample_conn):
    m = Model(sample_conn)
    assert tf.person_named(m, "P001", "priya shah").id == "P002"
    alias = next(x for p in m.active_people() for x in p.aliases)
    assert tf.person_named(m, "P001", alias.upper()) is not None
    assert tf.person_named(m, "P001", "me").id == "P001"
    assert tf.person_named(m, None, "me") is None or m.people["P001"].name == "Me"
    assert tf.person_named(m, "P001", "Nobody Here") is None


def test_a_garbled_name_is_offered_its_close_match(sample_conn):
    p = checked(sample_conn)
    assert [(n.name, n.near.name) for n in p.names] == [("Tom Baker", "Tom Becker")]


def test_a_name_left_blank_stays_in_the_description(sample_conn):
    top = imported(sample_conn)
    lib = Library(sample_conn)
    row = next(x for x, _ in lib.walk(top) if x.title == "Approval: change record")
    assert row.assignees == [] and "Named in the notes: Tom Baker." in row.description
    assert "Tom Baker" not in [p.name for p in Model(sample_conn).people.values()]


def test_a_name_can_be_settled_as_someone_on_the_list(sample_conn):
    top = imported(sample_conn, settled=Settled(names={"Tom Baker": "P003"}))
    lib = Library(sample_conn)
    row = next(x for x, _ in lib.walk(top) if x.title == "Approval: change record")
    assert row.assignees == ["P003"] and "Named in the notes" not in row.description


def test_a_name_can_be_added_as_a_new_person(sample_conn):
    added: list[str] = []
    top = tf.import_tree(sample_conn, checked(sample_conn), Settled(names={"Tom Baker": tf.NEW}), AT, added)
    m, lib = Model(sample_conn), Library(sample_conn)
    row = next(x for x, _ in lib.walk(top) if x.title == "Approval: change record")
    assert added == ["Tom Baker"] and m.person_name(row.assignees[0]) == "Tom Baker"


def test_a_label_not_there_is_left_out_unless_added(sample_conn):
    top = imported(sample_conn)
    window = next(x for x, _ in Library(sample_conn).walk(top) if x.title == "Trial execution window")
    assert window.labels == ["Safety"]
    assert not any(x.name == "Coatings" for x in Model(sample_conn).labels)
    top = imported(sample_conn, settled=Settled(labels={"Coatings": tf.NEW}))
    window = next(x for x, _ in Library(sample_conn).walk(top) if x.title == "Trial execution window")
    assert window.labels == ["Safety", "Coatings"]


# ---- ties (decisions 275, 276 and 284) ----
def test_a_tie_to_a_parent_counts_from_its_last_subtask_by_default(sample_conn):
    p = checked(sample_conn)
    assert [(t.key, t.field_name, t.source, t.options) for t in p.parent_ties] == [("notice", "start_tie", "change", ["ok", "prep"])]
    top = tf.import_tree(sample_conn, p, Settled(), AT)
    lib = Library(sample_conn)
    rows = {x.title: x for x, _ in lib.walk(top)}
    tie = rows["Tell the supplier"].ties["start"]
    assert tie.source == rows["Approval: change record"].id and (tie.point, tie.amount) == ("end", 2)
    assert rows["Tell the supplier"].description == "Give them the dates."


def test_a_tie_to_a_parent_can_count_from_another_subtask(sample_conn):
    top = imported(sample_conn, settled=Settled(ties={("notice", "start_tie"): "prep"}))
    rows = {x.title: x for x, _ in Library(sample_conn).walk(top)}
    assert rows["Tell the supplier"].ties["start"].source is None  # prep is the anchor


def test_a_tie_to_a_parent_can_be_left_untied_with_its_words_kept(sample_conn):
    top = imported(sample_conn, settled=Settled(ties={("notice", "start_tie"): ""}))
    rows = {x.title: x for x, _ in Library(sample_conn).walk(top)}
    assert rows["Tell the supplier"].ties == {}
    assert rows["Tell the supplier"].description == "Give them the dates. Start: 2 workdays after Change record ends."


def test_a_subtask_that_would_make_a_circle_isnt_offered(sample_conn):
    data = {"format": tf.TREE_FORMAT, "rows": [
        {"key": "top", "title": "Top"}, {"key": "p", "parent": "top", "title": "Parent", "quote": "q"},
        {"key": "a", "parent": "p", "title": "A", "quote": "q"},
        {"key": "b", "parent": "p", "title": "B", "quote": "q", "start_tie": {"source": "x", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}},
        {"key": "x", "parent": "top", "title": "X", "quote": "q", "start_tie": {"source": "p", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}}]}
    p = checked(sample_conn, data)
    assert p.problems == [] and p.parent_ties[0].options == ["a"]


def test_a_tie_to_a_parent_with_a_duration_or_a_tie_doesnt_wait(sample_conn):
    data = json.loads(json.dumps(TALK))
    data["rows"][1]["duration"] = 3
    assert checked(sample_conn, data).parent_ties == []


def test_two_settled_ties_in_a_circle_stop_the_import(sample_conn):
    data = {"format": tf.TREE_FORMAT, "rows": [
        {"key": "top", "title": "Top"}, {"key": "p1", "parent": "top", "title": "P1", "quote": "q"}, {"key": "p2", "parent": "top", "title": "P2", "quote": "q"},
        {"key": "a", "parent": "p1", "title": "A", "quote": "q", "start_tie": {"source": "p2", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}},
        {"key": "b", "parent": "p2", "title": "B", "quote": "q", "start_tie": {"source": "p1", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}}]}
    p = checked(sample_conn, data)
    assert p.problems == []
    with pytest.raises(tasks.TaskError, match="circle"):
        tf.import_tree(sample_conn, p, Settled(), AT)
    assert Library(sample_conn).live() == []


# ---- Import (decision 264) ----
def test_import_makes_a_template_and_no_tasks(sample_conn):
    before = len(Model(sample_conn).tasks)
    top = imported(sample_conn)
    lib = Library(sample_conn)
    assert len(Model(sample_conn).tasks) == before
    rows = {x.title: x for x, _ in lib.walk(top)}
    assert lib.name(rows["Coating qualification"].template) == "Coating qualification"
    assert lib.templates[rows["Coating qualification"].template].anchor == rows["Prepare change record"].id
    prep, window, ok = rows["Prepare change record"], rows["Trial execution window"], rows["Approval: change record"]
    assert prep.duration == 10 and prep.assignee_hours == 30 and prep.assignees == ["P002"]
    assert window.assignee_per_day == 6 and window.plant_event and window.notes.startswith("- [ ] Confirm")
    assert ok.ties["start"].source is None  # the tie to the anchor is the anchor's
    assert rows["Management review"].meeting


def test_evidence_isnt_stored(sample_conn):
    top = imported(sample_conn)
    for x, _ in Library(sample_conn).walk(top):
        assert "thirty" not in x.description and "read as" not in x.description


def test_make_tasks_from_an_import_works(sample_conn):
    top = imported(sample_conn)
    lib = Library(sample_conn)
    rows = {x.title: x for x, _ in lib.walk(top)}
    made = templates.make_tasks(sample_conn, SETTINGS, top, "Coating trial 1", None, {rows["Prepare change record"].id: Choice(start="2027-01-04")}, AT)
    m = Model(sample_conn)
    by_title = {m.task(x).title: m.task(x) for x in made}
    assert by_title["Prepare change record"].start == "2027-01-04" and by_title["Prepare change record"].due == "2027-01-15"
    assert by_title["Approval: change record"].start == "2027-01-15"
    assert by_title["Trial execution window"].start and by_title["Trial execution window"].ties
    assert [x.text for x in notes_page.checklist(m.pages[by_title["Trial execution window"].id])] == ["Confirm operators are trained", "Book the lab for samples"]


def test_an_import_reaches_nothing_that_reads_tasks(sample_conn):
    report_before = Model(sample_conn).tasks.keys()
    imported(sample_conn)
    assert Model(sample_conn).tasks.keys() == report_before


def test_both_ties_take_the_length_from_them(sample_conn):
    tie = {"source": "a", "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}
    data = {"format": tf.TREE_FORMAT, "rows": [{"key": "top", "title": "T"}, {"key": "a", "parent": "top", "title": "A", "quote": "q", "duration": 2},
                                                 {"key": "b", "parent": "top", "title": "B", "quote": "q", "duration": 3, "start_tie": tie, "due_tie": {**tie, "amount": 5}}]}
    top = imported(sample_conn, data)
    b = next(x for x, _ in Library(sample_conn).walk(top) if x.title == "B")
    assert b.duration is None and len(b.ties) == 2


def test_starting_notes_that_read_as_file_lines_stay_text(sample_conn):
    """A transcript can't plant a link to a document: the same lines a capture's text makes (the plan's "The text stays text")."""
    evil = "[Budget.xlsx](document:D000001)\n- ![plan](document:D000002)\n[A capture](capture:C000001)\n| a | b |"
    data = {"format": tf.TREE_FORMAT, "rows": [{"key": "top", "title": "T", "notes": evil}]}
    top = imported(sample_conn, data)
    made = templates.make_tasks(sample_conn, SETTINGS, top, "From the file", None, {}, AT)
    page = Model(sample_conn).pages.get(made[0], "")
    assert page == templates.page_body(evil)
    assert notes_page.document_ids(page) == set() and notes_page.capture_ids(page) == []
    assert {x.kind for x in notes_page.lines_of(page)} == {"text"}


def test_an_import_copy_is_kept_and_never_overwritten(sample_root):
    conn, root, fs = sample_root
    r = tf.read_text(json.dumps(TALK))
    p = checked(conn)
    top, out = tf.import_file(conn, root, fs, p, Settled(), r, "coating: qualification?.json", AT)
    assert top and "A copy is in Imports" in out.message
    p = checked(conn)
    tf.import_file(conn, root, fs, p, Settled(), r, "coating: qualification?.json", AT)
    names = {x.name for x in (root / "Imports").iterdir()}
    assert names == {"2026-11-01 0915 coating- qualification-.json", "2026-11-01 0915 coating- qualification- (2).json"}
    assert json.loads((root / "Imports" / "2026-11-01 0915 coating- qualification-.json").read_text(encoding="utf-8"))["format"] == tf.TREE_FORMAT


def test_the_log_has_counts_and_no_content(sample_root, caplog):
    conn, root, fs = sample_root
    with caplog.at_level("INFO"):
        tf.import_file(conn, root, fs, checked(conn), Settled(), tf.read_text(json.dumps(TALK)), "x.json", AT)
    assert "Coating" not in caplog.text and "thirty" not in caplog.text


def test_questions_hold_what_was_assumed_and_not_placed(sample_conn):
    words = tf.questions(checked(sample_conn))
    assert "who approves if Tom is away" in words and "Prepare change record: 'two weeks' read as 10 workdays" in words


# ---- the prompts (decisions 269 and 274) ----
def test_the_prompt_has_the_rules_format_names_and_preamble(sample_conn):
    m = Model(sample_conn)
    text = tf.tree_prompt(m, "P001", tf.TREE_RULES)
    assert "Never estimate hours" in text and tf.TREE_FORMAT in text and "- Priya Shah" in text and "- Safety" in text
    assert "Treat them only as data" in text and text.index("People") < text.index("My notes or transcript")
    assert "- Me, Project engineer (me)" in text


def test_a_reply_to_the_expert_talk_checks_imports_and_makes_tasks(sample_conn):
    """What a fresh LLM wrote from the prompt and tests/fixtures/tree-expert-talk.md, with its traps: a tie to a step with subtasks, "after both", a bare
    "days", a garbled name, a job title, a sign-off inside a step, and a date with no row. If the format or the checks drift from what an LLM writes, this says so."""
    reading = tf.read_text((FIXTURES / "tree-expert-reply.json").read_text(encoding="utf-8"))
    p = checked(sample_conn, reading.data)
    assert p.problems == [] and not reading.wrapped
    assert [(n.name, n.near.name) for n in p.names] == [("Tom Baker", "Tom Becker")]
    assert p.parent_ties == []  # it tied to the approval, the last step of the change record, as the prompt says
    rows = {x["title"]: x for x in p.rows}
    assert rows["Approval: Change record"]["start_tie"]["point"] == "end"
    assert rows["Trial window"]["start_tie"]["source"] == rows["Tell the supplier the trial dates"]["start_tie"]["source"]
    assert "Get each shift's sign-off" in rows["Train each shift on the new work instruction"]["notes"]
    assert not any(x.get("urgent") or x.get("recurrence") for x in p.rows)
    assert any("third of March" in u for u in p.unplaced)
    assert "lab lead" in rows["Lab tests the samples"]["description"]
    top = tf.import_tree(sample_conn, p, Settled(names={"Tom Baker": "P003"}), AT)
    lib = Library(sample_conn)
    by_title = {x.title: x for x, _ in lib.walk(top)}
    made = templates.make_tasks(sample_conn, SETTINGS, top, "Trial 1", None, {by_title["Write the change record"].id: Choice(start="2027-03-01")}, AT)
    m = Model(sample_conn)
    now = {m.task(x).title: m.task(x) for x in made}
    assert (now["Write the change record"].start, now["Write the change record"].due) == ("2027-03-01", "2027-03-12")
    assert now["Approval: Change record"].assignees == ["P003"] and now["Approval: Change record"].start == "2027-03-12"
    assert now["Trial window"].start == "2027-03-25" and now["Trial window"].assignee_hours == 30


def test_the_rules_are_written_once_and_never_replaced(data_root, fs):
    assert tf.rules(fs, data_root, tf.TREE_RULES_FILE, "The rules.") == "The rules."
    path = data_root / tf.TREE_RULES_FILE
    assert path.read_text(encoding="utf-8") == "The rules.\n"
    path.write_text("My own rules.\n", encoding="utf-8")
    assert tf.rules(fs, data_root, tf.TREE_RULES_FILE, "The rules.") == "My own rules."


def test_with_no_fs_the_rules_are_only_read(data_root):
    assert tf.rules(None, data_root, tf.TREE_RULES_FILE, "The rules.") == "The rules."
    assert not (data_root / tf.TREE_RULES_FILE).exists()


def test_the_prompt_example_passes_the_checks(sample_conn):
    data = json.loads(json.dumps(tf.TREE_EXAMPLE))
    data["rows"][1]["assignees"] = ["Priya Shah"]
    p = checked(sample_conn, data)
    assert p.problems == [] and p.anchor == "prep"


# ---- Export (decision 278), and a round trip ----
@pytest.fixture
def built(sample_conn):
    """A made-up template with all a row can hold, and a tree made from it."""
    conn = sample_conn
    top = templates.new_template(conn, "Product trial", AT, {"description": "A trial.", "labels": ["Safety"], "leads": ["P001"]})
    add = lambda parent, **v: templates.add_row(conn, SETTINGS, parent, {"title": "T", "inherit_labels": True, **v}, AT)[0]  # noqa: E731
    prep = add(top, title="Preparation", description="What has to be ready.")
    change = add(prep, title="Change record prep", assignees=["P002", "P003"], assignee_hours=30, involvement={("assignee", "P003"): 50}, duration=10)
    window = add(top, title="Trial execution window", assignees=["P002"], assignee_per_day=6, duration=5, plant_event=True, urgent=True, calendar_days=True, notes="- [ ] Book the room\n\nPlain words",
                 inherit_labels=False)
    report = add(top, title="Trial report", leads=["P001"], lead_per_week=3, meeting=True, labels=["Safety"], recurrence=None)
    routine = add(top, title="Weekly check", recurrence="Weekly", assignees=["P004"], assignee_hours=1)
    template = Library(conn).rows[top].template
    templates.apply_timing(conn, SETTINGS, template, window, {
        change: templates.RowTiming({"due": timing_tie(None, "start", 5, "weeks", "before")}, 10),
        report: templates.RowTiming({"start": timing_tie(window, "end", 2, "workdays", "after"), "due": timing_tie(window, "end", 9, "workdays", "after")}, None)}, AT)
    return conn, {"top": top, "prep": prep, "change": change, "window": window, "report": report, "routine": routine, "template": template}


def timing_tie(source, point, amount, unit, direction):
    from docrepo.timing import RowTie
    return RowTie(source, point, amount, unit, direction)


def row_shape(lib: Library, top: int) -> list[tuple]:
    """A template's rows as they read, with their ties by title."""
    titles = lib.titles(lib.rows[top].template)
    anchor = lib.templates[lib.rows[top].template].anchor
    out = []
    for x, depth in lib.walk(top):
        out.append((depth, x.title, x.description, x.lead_hours, x.assignee_hours, x.lead_per_day, x.assignee_per_day, x.lead_per_week, x.assignee_per_week, x.duration, x.calendar_days,
                    x.leads, x.assignees, x.labels, x.inherit_labels, x.meeting, x.plant_event, x.urgent, x.recurrence, x.notes, sorted(x.involvement.items()),
                    x.id == anchor, sorted((f, titles.get(timing_source(t, anchor)), t.point, t.amount, t.unit, t.direction) for f, t in x.ties.items())))
    return out


def timing_source(tie, anchor):
    return anchor if tie.source is None else tie.source


def test_export_then_import_gives_the_same_template(built):
    conn, r = built
    text = tf.export_text(tf.export_template(conn, r["template"], AT))
    reading = tf.read_text(text)
    plan = checked(conn, reading.data)
    assert plan.problems == [], texts(plan.problems)
    assert not any("has no quote" in x.text for x in plan.warnings)
    copy = tf.import_tree(conn, plan, Settled(), LATER)
    lib = Library(conn)
    assert row_shape(lib, copy) == row_shape(lib, r["top"])


def test_an_export_names_people_and_has_ids(built):
    conn, r = built
    data = tf.export_template(conn, r["template"], AT)
    assert data["of"] == f"template {r['template']}" and data["exported"] == "2026-11-01 09:15" and data["anchor"] == r["window"]
    rows = {x["id"]: x for x in data["rows"]}
    assert rows[r["change"]]["assignees"] == ["Priya Shah", "Tom Becker"] and rows[r["change"]]["involvement"] == {"assignees": {"Tom Becker": 50}}
    assert rows[r["window"]]["assignee_per_day"] == 6 and "assignee_hours" not in rows[r["window"]]
    assert rows[r["report"]]["lead_per_week"] == 3
    assert rows[r["change"]]["due_tie"] == {"source": r["window"], "point": "start", "amount": 5, "unit": "weeks", "direction": "before"}


def test_export_writes_to_exports_and_never_over_an_earlier_one(built, data_root, fs):
    conn, r = built
    data = tf.export_template(conn, r["template"], AT)
    a = tf.save_export(fs, data_root, data, "Product trial", AT)
    b = tf.save_export(fs, data_root, data, "Product trial", AT)
    assert a.parent == data_root / "Exports" and a != b and a.name == "2026-11-01 0915 Product trial.json"
    assert json.loads(a.read_text(encoding="utf-8")) == data


def test_a_task_export_has_what_a_task_has_and_leaves_out_whats_discarded(built):
    conn, r = built
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {r["window"]: Choice(start="2027-03-01")}, AT)
    tasks.set_discarded(conn, SETTINGS, made[-1], "Made by mistake", at=AT, via="Test")
    data = tf.export_task(conn, made[0], AT)
    assert data["of"] == f"task {made[0]}" and made[-1] not in [x["id"] for x in data["rows"]]
    rows = {x["title"]: x for x in data["rows"]}
    assert rows["Trial execution window"]["start"] == "2027-03-01" and rows["Trial execution window"]["state"] == "Not started"
    assert rows["Change record prep"]["due_tie"]["source"] in {x["id"] for x in data["rows"]}


def test_a_task_under_two_parents_appears_once_with_the_other_listed(sample_conn):
    a = tasks.create_task(sample_conn, SETTINGS, title="Project A", at=AT, created_by="Test")
    b = tasks.create_task(sample_conn, SETTINGS, title="Project B", at=AT, created_by="Test")
    shared = tasks.create_task(sample_conn, SETTINGS, title="Shared", at=AT, created_by="Test", parents=[a, b])
    data = tf.export_task(sample_conn, a, AT)
    assert [x["id"] for x in data["rows"]] == [a, shared] and data["rows"][1]["also_under"] == ["Project B"]


# ---- edit files on a template (decisions 279, 280 and 286) ----
def edit_of(data_of: str, *rows, **more) -> dict:
    return {"format": tf.EDIT_FORMAT, "of": data_of, "rows": list(rows), **more}


def trees_of(built, n: int = 2) -> list[str]:
    conn, r = built
    return [templates.make_tasks(conn, SETTINGS, r["top"], f"Trial {i}", None, {r["window"]: Choice(start="2027-03-01")}, AT)[0] for i in range(1, n + 1)]


def template_edit(built, *rows):
    conn, r = built
    return tf.plan_edit(conn, SETTINGS, edit_of(f"template {r['template']}", *rows), AT)


def apply_template(conn, root, fs, plan):
    return tf.apply_edit(conn, root, fs, SETTINGS, plan, tf.Reading(text="{}"), "edit.json", AT)


@pytest.fixture
def on_disk(data_root, fs):
    return data_root, fs


def test_an_edit_changes_only_whats_listed(built, on_disk):
    conn, r = built
    plan = template_edit(built, {"id": r["change"], "duration": 3, "quote": "only three days"})
    assert plan.problems == [] and [(c.kind, c.field_name, c.old, c.new) for c in plan.changes] == [("field", "duration", 10, 3)]
    before = {x.id: x for x, _ in Library(conn).walk(r["top"])}
    apply_template(conn, *on_disk, plan)
    after = {x.id: x for x, _ in Library(conn).walk(r["top"])}
    assert after[r["change"]].duration == 3
    assert after[r["change"]].assignees == before[r["change"]].assignees and after[r["change"]].assignee_hours == before[r["change"]].assignee_hours
    assert after[r["window"]] == before[r["window"]]


def test_a_whole_tree_sent_back_shows_no_changes(built):
    conn, r = built
    data = tf.export_template(conn, r["template"], AT)
    data["format"] = tf.EDIT_FORMAT
    plan = tf.plan_edit(conn, SETTINGS, data, AT)
    assert plan.problems == [], plan.problems
    assert plan.changes == [] and plan.unchanged == len(data["rows"])


def test_a_whole_tree_with_tidied_values_shows_no_changes(built):
    conn, r = built
    data = tf.export_template(conn, r["template"], AT)
    data["format"] = tf.EDIT_FORMAT
    for x in data["rows"]:
        x["id"] = str(x["id"])
        if x.get("assignees"):
            x["assignees"] = [n.upper() for n in reversed(x["assignees"])]
        x["description"] = (x.get("description") or "") + "  "
    plan = tf.plan_edit(conn, SETTINGS, data, AT)
    assert plan.problems == [] and plan.changes == []


def test_a_rewording_nobody_asked_for_starts_unticked(built):
    conn, r = built
    data = tf.export_template(conn, r["template"], AT)
    data["format"] = tf.EDIT_FORMAT
    rows = {x["id"]: x for x in data["rows"]}
    rows[r["prep"]]["description"] = "Reworded by the LLM."
    rows[r["change"]].update(duration=4, quote="make it four days")
    plan = tf.plan_edit(conn, SETTINGS, data, AT)
    by_field = {c.field_name: c for c in plan.changes}
    assert set(by_field) == {"description", "duration"}
    assert by_field["duration"].ticked and not by_field["description"].ticked


def test_a_removal_must_be_stated(built, on_disk):
    conn, r = built
    plan = template_edit(built, {"id": r["change"], "duration": 3, "quote": "q"})
    assert not any(c.kind == "remove" for c in plan.changes)
    apply_template(conn, *on_disk, plan)
    assert r["window"] in Library(conn).rows and r["report"] in Library(conn).rows


def test_a_row_can_be_taken_out_and_its_untouched_copies_discarded(built, on_disk):
    conn, r = built
    first, _ = trees_of(built)
    plan = template_edit(built, {"id": r["report"], "remove": True, "quote": "drop the report"})
    c = plan.changes[0]
    assert c.kind == "remove" and len(c.plan.copies) == 2 and all(x.can for x in c.plan.copies)
    kept = c.plan.copies[0].task
    c.off.add(kept)
    apply_template(conn, *on_disk, plan)
    assert r["report"] not in Library(conn).rows
    tasks_now = load_tasks(conn, [c.plan.copies[0].task, c.plan.copies[1].task])
    assert not tasks_now[kept].discarded and tasks_now[c.plan.copies[1].task].discarded


def test_a_new_row_reaches_the_trees_left_ticked(built, on_disk):
    conn, r = built
    first, second = trees_of(built)
    plan = template_edit(built, {"key": "brief", "parent": r["prep"], "title": "Brief the night shift", "duration": 1, "assignees": ["Tom Becker"], "quote": "add a briefing"})
    c = plan.changes[0]
    assert c.kind == "add" and {t.task for t in c.plan.trees} == {first, second}
    c.off.add(second)
    apply_template(conn, *on_disk, plan)
    lib = Library(conn)
    row = next(x for x, _ in lib.walk(r["top"]) if x.title == "Brief the night shift")
    assert row.duration == 1 and row.parent == r["prep"]
    assert {x.tree for x in lib.copies_of(row.id)} == {first}


def test_a_new_row_under_a_new_row(built, on_disk):
    conn, r = built
    plan = template_edit(built, {"key": "kid", "parent": "mum", "title": "Kid", "quote": "q"}, {"key": "mum", "parent": r["prep"], "title": "Mum", "quote": "q",
                                                                                                "start_tie": {"source": r["window"], "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}})
    assert plan.problems == [] and [c.title for c in plan.changes] == ["Mum", "Kid"]
    apply_template(conn, *on_disk, plan)
    rows = {x.title: x for x, _ in Library(conn).walk(r["top"])}
    assert rows["Kid"].parent == rows["Mum"].id and rows["Mum"].ties["start"].source is None


def test_a_new_row_under_an_unticked_new_row_says_so(built):
    conn, r = built
    plan = template_edit(built, {"key": "mum", "parent": r["prep"], "title": "Mum", "quote": "q"}, {"key": "kid", "parent": "mum", "title": "Kid", "quote": "q"})
    assert tf.waiting_on(plan) == ""
    plan.changes[0].ticked = False
    assert "Mum" in tf.waiting_on(plan)


def test_new_rows_waiting_on_each_other_are_a_problem(built):
    conn, r = built
    tie = lambda s: {"source": s, "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}  # noqa: E731
    plan = template_edit(built, {"key": "a", "parent": r["prep"], "title": "A", "start_tie": tie("b")}, {"key": "b", "parent": r["prep"], "title": "B", "start_tie": tie("a")})
    assert any("wait on each other" in x for x in plan.problems)


def test_a_field_reaches_the_tasks_following_and_one_can_be_left(built, on_disk):
    conn, r = built
    first, second = trees_of(built)
    plan = template_edit(built, {"id": r["change"], "assignee_hours": 10, "quote": "ten hours"})
    c = plan.changes[0]
    assert len(c.plan.items) == 2 and all(x.work_before != x.work_after for x in c.plan.items)
    left = next(x.task for x in c.plan.items if x.tree == "Trial 2")
    went = next(x.task for x in c.plan.items if x.tree == "Trial 1")
    c.off.add(left)
    apply_template(conn, *on_disk, plan)
    now = load_tasks(conn, [left, went])
    assert now[went].assignee_hours == 10 and now[left].assignee_hours == 30
    links = Library(conn).links
    assert "assignee_hours" in links[went] and "assignee_hours" not in links[left]


def test_nothing_changes_while_a_template_edit_is_reviewed(built):
    conn, r = built
    trees_of(built)
    before = (Library(conn).rows[r["change"]].assignee_hours, conn.execute("SELECT count(*) FROM status_log").fetchone()[0])
    template_edit(built, {"id": r["change"], "assignee_hours": 10, "quote": "q"}, {"id": r["report"], "remove": True, "quote": "q"}, {"key": "n", "parent": r["prep"], "title": "N", "quote": "q"})
    assert (Library(conn).rows[r["change"]].assignee_hours, conn.execute("SELECT count(*) FROM status_log").fetchone()[0]) == before


def test_hours_change_form(built, on_disk):
    conn, r = built
    plan = template_edit(built, {"id": r["change"], "assignee_per_day": 3, "quote": "three hours a day"})
    apply_template(conn, *on_disk, plan)
    row = Library(conn).rows[r["change"]]
    assert row.assignee_per_day == 3 and row.assignee_hours is None
    plan = template_edit(built, {"id": r["change"], "assignee_per_day": None, "assignee_hours": 12, "quote": "twelve hours"})
    assert plan.problems == []
    apply_template(conn, *on_disk, plan)
    row = Library(conn).rows[r["change"]]
    assert row.assignee_per_day is None and row.assignee_hours == 12


def test_null_clears_a_field(built, on_disk):
    conn, r = built
    plan = template_edit(built, {"id": r["change"], "duration": None, "description": None, "quote": "q"}, {"id": r["prep"], "description": None, "quote": "q"})
    apply_template(conn, *on_disk, plan)
    lib = Library(conn)
    assert lib.rows[r["change"]].duration is None and lib.rows[r["prep"]].description == ""


def test_a_tie_can_be_changed_and_cleared(built, on_disk):
    conn, r = built
    plan = template_edit(built, {"id": r["report"], "start_tie": {"source": r["window"], "point": "end", "amount": 4, "unit": "workdays", "direction": "after"}, "due_tie": None, "quote": "q"})
    assert plan.problems == [], plan.problems
    apply_template(conn, *on_disk, plan)
    row = Library(conn).rows[r["report"]]
    assert row.ties["start"].amount == 4 and "due" not in row.ties


@pytest.mark.parametrize(("change", "said"), [
    (lambda r: {"id": 99999, "duration": 3}, "IDs have to stay"),
    (lambda r: {"id": r["change"], "parent": r["window"]}, "moving a row stays in the app"),
    (lambda r: {"id": r["change"], "assignees": ["Nobody Here"]}, "isn't on the people list"),
    (lambda r: {"id": r["change"], "labels": ["Nothing"]}, "doesn't exist yet"),
    (lambda r: {"id": r["change"], "state": "Closed"}, "a template row has no State"),
    (lambda r: {"id": r["change"], "start": "2027-01-01"}, "a template row has no Start"),
    (lambda r: {"id": r["change"], "urgent": True}, "can't be changed by an edit file"),
    (lambda r: {"id": r["change"], "pathname": "x"}, "isn't a field"),
    (lambda r: {"id": r["change"], "duration": 1.5}, "whole number of days"),
    (lambda r: {"id": r["change"], "assignee_hours": 3, "assignee_per_day": 2}, "stated two ways"),
    (lambda r: {"id": r["top"], "remove": True}, "top row"),
    (lambda r: {"id": r["change"], "title": None}, "can't be cleared"),
    (lambda r: {"key": "x", "title": "No parent"}, "isn't in this tree"),
    (lambda r: {"parent": r["top"], "title": "No key"}, "needs a key"),
    (lambda r: {"key": "x", "parent": r["top"], "title": "T", "assignees": ["Nobody Here"]}, "isn't on the people list"),
    (lambda r: {"id": r["report"], "start_tie": {"source": 99999, "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}}, "isn't in this tree"),
    (lambda r: {"id": r["window"], "start_tie": {"source": r["report"], "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}}, "is the anchor"),
])
def test_an_edit_problem_stops_it(built, change, said):
    conn, r = built
    plan = template_edit(built, change(r))
    assert plan.problems and said in " ".join(plan.problems), plan.problems
    with pytest.raises(tasks.TaskError):
        tf.apply_edit(conn, None, None, SETTINGS, plan, tf.Reading(), "x", AT)


def test_an_edit_for_something_not_there_is_a_problem(sample_conn):
    for of in ("template 99", "task T999999", "nonsense", ""):
        assert "there's no such" in tf.plan_edit(sample_conn, SETTINGS, edit_of(of), AT).problems[0]


def test_an_edit_cant_change_the_anchor(built):
    conn, r = built
    plan = tf.plan_edit(conn, SETTINGS, edit_of(f"template {r['template']}", anchor=r["change"]), AT)
    assert "Timing" in plan.problems[0]


def test_an_edit_is_all_or_none(built, on_disk):
    """A change that fails when it's made undoes those before it."""
    conn, r = built
    plan = template_edit(built, {"id": r["change"], "duration": 3, "quote": "q"}, {"key": "kid", "parent": "mum", "title": "Kid", "quote": "q"}, {"key": "mum", "parent": r["prep"], "title": "Mum", "quote": "q"})
    next(c for c in plan.changes if c.title == "Mum").ticked = False
    with pytest.raises(tasks.TaskError):
        apply_template(conn, *on_disk, plan)
    assert Library(conn).rows[r["change"]].duration == 10


def test_two_changes_that_make_a_circle_undo_each_other(built, on_disk):
    conn, r = built
    tie = lambda s: {"source": s, "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}  # noqa: E731
    plan = template_edit(built, {"id": r["prep"], "duration": 2, "start_tie": tie(r["routine"]), "quote": "q"})
    assert any("repeats" in x for x in plan.problems)
    plan = template_edit(built, {"id": r["change"], "start_tie": tie(r["report"]), "quote": "q"}, {"id": r["report"], "start_tie": tie(r["change"]), "quote": "q"})
    assert plan.problems == [], plan.problems
    before = Library(conn).rows[r["change"]].ties
    with pytest.raises(tasks.TaskError, match="circle"):
        apply_template(conn, *on_disk, plan)
    assert Library(conn).rows[r["change"]].ties == before


def test_an_applied_edit_file_is_kept_in_imports(built, on_disk):
    conn, r = built
    root, _fs = on_disk
    plan = template_edit(built, {"id": r["change"], "duration": 3, "quote": "q"})
    out = tf.apply_edit(conn, root, _fs, SETTINGS, plan, tf.Reading(text='{"format": "docrepo-edit-1"}'), "edit.json", AT)
    assert "Applied 1 change." in out.message and len(list((root / "Imports").iterdir())) == 1


# ---- edit files on a task tree (decisions 280 and 287) ----
@pytest.fixture
def tree(built):
    conn, r = built
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {r["window"]: Choice(start="2027-03-01")}, AT)
    m = Model(conn)
    return conn, {m.task(x).title: x for x in made}, made[0]


def task_edit(conn, top, *rows, **more):
    return tf.plan_edit(conn, SETTINGS, edit_of(f"task {top}", *rows, **more), AT)


def test_a_task_edit_goes_through_update_task_and_is_logged(tree, on_disk):
    conn, ids, top = tree
    plan = task_edit(conn, top, {"id": ids["Preparation"], "title": "Getting ready", "description": "New words", "quote": "q"})
    assert plan.problems == [] and len(plan.changes) == 2
    apply_template(conn, *on_disk, plan)
    t = load_tasks(conn, [ids["Preparation"]])[ids["Preparation"]]
    assert t.title == "Getting ready" and t.description == "New words"
    assert {e.via for e in Model(conn).status_log_of(ids["Preparation"]) if e.at.startswith("2026-11-01 09:15") and e.field == "Title"} == {tf.VIA}


def test_a_linked_field_stops_following_and_the_review_says_so(tree, on_disk):
    conn, ids, top = tree
    win = ids["Trial execution window"]
    plan = task_edit(conn, top, {"id": win, "assignee_per_day": 2, "quote": "two hours a day"})
    c = plan.changes[0]
    assert c.linked
    apply_template(conn, *on_disk, plan)
    assert "assignee_hours" not in Library(conn).links.get(win, set())
    assert load_tasks(conn, [win])[win].assignee_per_day == 2


def test_a_moved_date_lists_what_moves_with_it(tree, on_disk):
    conn, ids, top = tree
    win = ids["Trial execution window"]
    plan = task_edit(conn, top, {"id": win, "start": "2027-03-08", "quote": "slips a week"})
    c = plan.changes[0]
    assert {x.title for x in c.moves} >= {"Trial report", "Change record prep"}
    before = load_tasks(conn, [ids["Trial report"]])[ids["Trial report"]].start
    apply_template(conn, *on_disk, plan)
    assert load_tasks(conn, [ids["Trial report"]])[ids["Trial report"]].start > before


def test_a_tied_date_keeps_its_tie_with_a_new_gap(tree, on_disk):
    conn, ids, top = tree
    report = ids["Trial report"]
    t = load_tasks(conn, [report])[report]
    plan = task_edit(conn, top, {"id": report, "start": "2027-03-15", "quote": "q"})
    assert plan.changes[0].tied
    apply_template(conn, *on_disk, plan)
    after = load_tasks(conn, [report])[report]
    assert after.start == "2027-03-15" and after.ties["start"].amount != t.ties["start"].amount


def test_a_task_this_file_closes_doesnt_move(tree, on_disk):
    """Whichever order its rows are in (decision 287)."""
    conn, ids, top = tree
    win, report = ids["Trial execution window"], ids["Trial report"]
    before = load_tasks(conn, [report])[report]
    plan = task_edit(conn, top, {"id": win, "start": "2027-03-08", "quote": "slips a week"}, {"id": report, "state": "Closed", "quote": "the report's done"})
    assert tf.closing_ids(plan) == {report}
    assert report in [x.task for x in plan.changes[0].moves]
    apply_template(conn, *on_disk, plan)
    after = load_tasks(conn, [report])[report]
    assert after.state == "Closed" and after.start == before.start and after.due == before.due


def test_a_task_can_be_discarded_with_a_reason_and_brought_back(tree, on_disk):
    conn, ids, top = tree
    report = ids["Trial report"]
    plan = task_edit(conn, top, {"id": report, "remove": True, "quote": "drop it"})
    apply_template(conn, *on_disk, plan)
    t = load_tasks(conn, [report])[report]
    assert t.discarded and t.discard_reason == tf.TAKEN_OUT
    tasks.set_discarded(conn, SETTINGS, report, None, at=LATER, via="Test")
    assert not load_tasks(conn, [report])[report].discarded


def test_a_parent_with_other_subtasks_cant_be_discarded(tree):
    conn, ids, top = tree
    plan = task_edit(conn, top, {"id": ids["Preparation"], "remove": True, "quote": "q"})
    c = plan.changes[0]
    assert c.blocked and "Change record prep" in c.blocked and not c.ticked


def test_a_parent_and_its_subtasks_can_go_together(tree, on_disk):
    conn, ids, top = tree
    plan = task_edit(conn, top, {"id": ids["Preparation"], "remove": True, "quote": "q"}, {"id": ids["Change record prep"], "remove": True, "quote": "q"})
    assert not any(c.blocked for c in plan.changes)
    apply_template(conn, *on_disk, plan)
    now = load_tasks(conn, [ids["Preparation"], ids["Change record prep"]])
    assert all(t.discarded for t in now.values())


def test_a_task_edit_can_add_a_subtask(tree, on_disk):
    conn, ids, top = tree
    plan = task_edit(conn, top, {"key": "n", "parent": ids["Preparation"], "title": "Check-in", "assignees": ["Priya Shah"], "assignee_hours": 2, "quote": "add a check-in"},
                     {"key": "k", "parent": "n", "title": "Under it", "quote": "q"})
    assert plan.problems == [], plan.problems
    apply_template(conn, *on_disk, plan)
    m = Model(conn)
    new = next(x for x in m.children_of(ids["Preparation"]) if m.task(x).title == "Check-in")
    assert m.task(new).assignees == ["P002"] and m.task(new).created_by == tf.VIA
    assert [m.task(x).title for x in m.children_of(new)] == ["Under it"]


@pytest.mark.parametrize(("change", "said"), [
    (lambda ids: {"id": ids["Trial report"], "notes": "x"}, "can't be changed by an edit file"),
    (lambda ids: {"id": ids["Trial report"], "meeting": False}, "can't be changed by an edit file"),
    (lambda ids: {"id": ids["Trial report"], "start_tie": None}, "can't be changed by an edit file"),
    (lambda ids: {"id": ids["Trial report"], "state": "Done"}, "a state is one of"),
    (lambda ids: {"id": ids["Trial report"], "due": "soon"}, "YYYY-MM-DD"),
    (lambda ids: {"id": "T999999", "duration": 3}, "IDs have to stay"),
    (lambda ids: {"id": ids["Trial report"], "parent": ids["Preparation"]}, "moving a row"),
    (lambda ids: {"key": "x", "parent": ids["Preparation"], "title": "T", "start_tie": {"source": ids["Preparation"], "point": "end", "amount": 1, "unit": "workdays", "direction": "after"}}, "can't be set"),
])
def test_a_task_edit_problem_stops_it(tree, change, said):
    conn, ids, top = tree
    plan = task_edit(conn, top, change(ids))
    assert plan.problems and said in " ".join(plan.problems), plan.problems


def test_a_whole_task_tree_sent_back_shows_no_changes(tree):
    conn, ids, top = tree
    data = tf.export_task(conn, top, AT)
    data["format"] = tf.EDIT_FORMAT
    plan = tf.plan_edit(conn, SETTINGS, data, AT)
    assert plan.problems == [], plan.problems
    assert plan.changes == []


def test_a_stale_file_says_so(tree):
    conn, ids, top = tree
    data = tf.export_task(conn, top, AT)
    tasks.update_task(conn, SETTINGS, ids["Preparation"], at=LATER, via="Test", description="Changed since")
    data = {"format": tf.EDIT_FORMAT, "of": data["of"], "exported": data["exported"], "rows": [{"id": ids["Preparation"], "title": "New", "quote": "q"}]}
    plan = tf.plan_edit(conn, SETTINGS, data, datetime(2026, 11, 3, 8, 0))
    assert "Exported 1 Nov; 1 task in this tree has changed since" in plan.stale
    assert plan.changes[0].old == "Preparation"


def test_old_values_are_read_from_the_database_not_the_file(tree):
    conn, ids, top = tree
    tasks.update_task(conn, SETTINGS, ids["Preparation"], at=LATER, via="Test", title="Renamed")
    plan = task_edit(conn, top, {"id": ids["Preparation"], "title": "New", "quote": "q"})
    assert plan.changes[0].old == "Renamed"


# ---- the commands, which only print ----
@pytest.fixture
def root_on_disk(tmp_path):
    root = tmp_path / "Root"
    assert cli.main(["--data-root", str(root), "init"]) == 0
    assert cli.main(["--data-root", str(root), "load-sample"]) == 0
    return root


def counts(root) -> tuple:
    conn = db.connect(*_fs_for(root))
    try:
        return tuple(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("tasks", "templates", "status_log", "people"))
    finally:
        conn.close()


def _fs_for(root):
    from docrepo.safe_fs import SafeFS
    return SafeFS([root]), root


def test_tree_check_prints_and_changes_nothing(root_on_disk, tmp_path, capsys):
    file = tmp_path / "talk.json"
    file.write_text(json.dumps(TALK), encoding="utf-8")
    before = counts(root_on_disk)
    assert cli.main(["--data-root", str(root_on_disk), "tree-check", str(file)]) == 0
    out = capsys.readouterr().out
    assert "A tree file: Coating qualification, 7 rows, 3 ties." in out and "Warning:" in out
    assert counts(root_on_disk) == before


def test_tree_check_fails_on_a_problem(root_on_disk, tmp_path, capsys):
    file = tmp_path / "bad.json"
    file.write_text('{"format": "docrepo-tree-1", "rows": [{"key": "a"}]}', encoding="utf-8")
    assert cli.main(["--data-root", str(root_on_disk), "tree-check", str(file)]) == 1
    assert "Problem: a has no title." in capsys.readouterr().out


def test_tree_check_names_an_unknown_format(root_on_disk, tmp_path, capsys):
    file = tmp_path / "other.json"
    file.write_text('{"format": "something-else"}', encoding="utf-8")
    assert cli.main(["--data-root", str(root_on_disk), "tree-check", str(file)]) == 1
    assert 'format is "something-else"' in capsys.readouterr().out


def test_tree_check_reads_an_edit_file(root_on_disk, tmp_path, capsys):
    file = tmp_path / "edit.json"
    file.write_text(json.dumps({"format": tf.EDIT_FORMAT, "of": "task T000001", "rows": [{"id": "T000001", "title": "New name", "quote": "q"}]}), encoding="utf-8")
    before = counts(root_on_disk)
    assert cli.main(["--data-root", str(root_on_disk), "tree-check", str(file)]) == 0
    assert "An edit file for" in capsys.readouterr().out
    assert counts(root_on_disk) == before


def test_tree_prompt_prints_and_writes_nothing(root_on_disk, capsys):
    assert cli.main(["--data-root", str(root_on_disk), "tree-prompt"]) == 0
    assert "Never estimate hours" in capsys.readouterr().out
    assert not (root_on_disk / tf.TREE_RULES_FILE).exists()


def test_tree_prompt_edit_holds_the_tree(root_on_disk, capsys):
    assert cli.main(["--data-root", str(root_on_disk), "tree-prompt", "--edit", "T000001"]) == 0
    out = capsys.readouterr().out
    assert "Keep every" in out and '"of": "task T000001"' in out


def test_tree_export_prints_a_task_as_json(root_on_disk, capsys):
    assert cli.main(["--data-root", str(root_on_disk), "tree-export", "T000001"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["of"] == "task T000001" and data["rows"][0]["id"] == "T000001"
    assert not (root_on_disk / tf.EXPORTS).exists()


def test_tree_export_of_nothing_says_so(root_on_disk, capsys):
    assert cli.main(["--data-root", str(root_on_disk), "tree-export", "T999999"]) == 1
    assert "no task" in capsys.readouterr().err


# ---- Copilot's folder (item 84) ----
def test_the_folder_offers_whats_not_imported_yet(data_root, fs, tmp_path):
    folder = tmp_path / "Copilot"
    folder.mkdir()
    text = json.dumps(TALK)
    (folder / "a.json").write_text(text, encoding="utf-8")
    (folder / "b.json").write_text('{"format": "docrepo-edit-1"}', encoding="utf-8")
    (folder / "notes.txt").write_text("not a tree", encoding="utf-8")
    assert [w.name for w in tf.waiting_files(str(folder), data_root)] == ["a.json", "b.json"]
    tf.save_record(fs, data_root, tf.IMPORTS, text, "a.json", AT)
    assert [w.name for w in tf.waiting_files(str(folder), data_root)] == ["b.json"]


def test_the_same_name_with_new_text_is_offered_again(data_root, fs, tmp_path):
    folder = tmp_path / "Copilot"
    folder.mkdir()
    (folder / "a.json").write_text('{"v": 1}', encoding="utf-8")
    tf.save_record(fs, data_root, tf.IMPORTS, '{"v": 1}', "a.json", AT)
    (folder / "a.json").write_text('{"v": 2}', encoding="utf-8")
    assert [w.name for w in tf.waiting_files(str(folder), data_root)] == ["a.json"]


def test_no_folder_or_a_missing_one_offers_nothing(data_root, tmp_path):
    assert tf.waiting_files(None, data_root) == [] and tf.waiting_files("", data_root) == []
    assert tf.waiting_files(str(tmp_path / "gone"), data_root) == []


def test_people_added_by_an_import_are_noted_as_such(sample_conn):
    tf.import_tree(sample_conn, checked(sample_conn), Settled(names={"Tom Baker": tf.NEW}), AT)
    p = next(x for x in Model(sample_conn).people.values() if x.name == "Tom Baker")
    assert "from a tree file" in (p.added_note or "")
