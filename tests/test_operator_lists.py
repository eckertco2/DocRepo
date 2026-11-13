"""The ``**label,`` and ``**agenda,`` lists (release 5.144, decisions 620 to 625, the owner's ask of 2026-11-13): the words
typed after either operator open the @ and # list, of the labels or the agendas it takes, as @ and # do. Everything
here runs without Qt; ``test_operator_lists_ui.py`` has the list in the capture window."""
from __future__ import annotations

from datetime import date

import pytest

from docrepo import items, people
from docrepo.config import Settings
from docrepo.model import TODAY, Model
from docrepo.parse import ParsePerson
from docrepo.save import item_names

DAY = date(2026, 10, 8)
TOM, PRIYA, MEETING, RIGGING = "P003", "P002", "T000010", "T000012"


@pytest.fixture
def names(sample_conn):
    return item_names(Model(sample_conn), Settings(me="P001"))


def typed(text: str, names: items.Names) -> items.Typing | None:
    return items.typing(text, names)


def listed(text: str, names: items.Names) -> list[tuple[str, str]]:
    """The list's rows for ``text``, each (its name, its grey part)."""
    t = typed(text, names)
    return [(o.label, o.sub) for o in items.options(t, names)] if t else []


def picked(text: str, names: items.Names, row: int = 0) -> str:
    """The line once the list's row ``row`` is picked."""
    t = typed(text, names)
    return text[:t.start] + items.inserted(t, items.options(t, names)[row])


# ---- **label, ----
def test_the_comma_opens_the_label_list_with_every_label(names):
    t = typed("- @Mike book the crane **label, ", names)
    assert (t.sigil, t.of, t.q, t.lead) == ("", "labels", "", "")
    assert [name for name, _ in listed("**label, ", names)] == ["Line 1", "Line 2", "Strategic Plan", "Safety", "Profitability"]


def test_the_list_opens_on_the_comma_and_a_pick_puts_the_space_in(names):
    t = typed("**label,", names)
    assert (t.q, t.lead) == ("", " ")
    assert picked("**label,", names, 3) == "**label, Safety "


def test_typing_narrows_it_and_offers_a_new_label(names):
    assert listed("**label, li", names) == [("Line 1", ""), ("Line 2", ""), ("Create label “li”", "Made when you save")]
    assert listed("**labels, saf", names) == [("Safety", "guard, rail, walkthrough, LOTO"), ("Create label “saf”", "Made when you save")]
    assert listed("**Label, plan strat", names)[0] == ("Strategic Plan", "strategic")  # words in any order, as @ and #


def test_a_whole_label_has_no_new_label_row(names):
    assert listed("**label, safety", names) == [("Safety", "guard, rail, walkthrough, LOTO")]


def test_a_name_that_isnt_a_label_is_one_row_that_makes_it(names):
    t = typed("**label, Fire safety", names)
    [o] = items.options(t, names)
    assert (o.label, o.add, o.value) == ("Create label “Fire safety”", True, "Fire safety")
    assert picked("**label, Fire safety", names) == "**label, Fire safety "


def test_a_space_after_a_whole_label_closes_it(names):
    assert listed("**label, Safety ", names) == []  # round 7's decision 326, as after @Tom Becker


def test_after_a_comma_or_and_the_next_label_is_listed(names):
    t = typed("**label, Safety, li", names)
    assert (t.q, t.start) == ("li", len("**label, Safety, "))
    assert picked("**label, Safety and pro", names) == "**label, Safety and Profitability "
    assert [name for name, _ in listed("**label, Safety and ", names)][:2] == ["Line 1", "Line 2"]


def test_a_sublabel_shows_under_its_parent_and_the_parent_isnt_offered(sample_conn):
    people.add_label(sample_conn, "Production line")
    people.add_label(sample_conn, "Line 3", parent="Production line")
    names = item_names(Model(sample_conn), Settings(me="P001"))
    rows = listed("**label, ", names)
    assert ("Production line › Line 3", "") in rows and not any(name == "Production line" for name, _ in rows)
    assert listed("**label, prod", names)[0] == ("Production line › Line 3", "")  # the parent's name finds it
    assert picked("**label, prod", names) == "**label, Line 3 "


def test_no_list_once_the_sentence_has_ended_or_another_operator_has_started(names):
    assert typed("**label, Safety. Then", names) is None
    assert typed("**label, Safety.", names) is None
    assert typed("**label, Safety **due, 5", names) is None
    assert typed("**label, Safety\n", names) is None


def test_other_parameters_have_no_list_of_their_own(names):
    assert typed("**due, to", names) is None and typed("**lead, To", names) is None
    assert typed("**lead, @To", names).sigil == "@"  # their @ and # lists, as before


def test_without_names_typing_is_as_it_was(names):
    assert items.typing("**label, Saf") is None
    assert items.typing("**agenda, @to").sigil == "@"


# ---- **agenda, ----
def test_the_comma_opens_today_the_meetings_and_people(names):
    assert listed("- @Mike book the crane **agenda, ", names) == [
        ("Today", "Your own agenda"), ("Business team meeting", "Meeting"), ("Priya Shah", "Person · Priya · PS"),
        ("Tom Becker", "Person · Tom · Thomas"), ("Mike Ortiz", "Person · Mike · Michael"), ("Tyler Nguyen", "Person · Tyler · Tyler N."),
        ("Todd", "Person")]
    assert typed("**agendas, ", names).of == "agendas"


def test_you_arent_on_it(names):
    assert not any(name == "Me" for name, _ in listed("**agenda, ", names) + listed("**agenda, me", names))


def test_typing_finds_today_people_and_open_tasks(names):
    rows = [name for name, _ in listed("**agenda, to", names)]
    assert rows[:3] == ["Today", "Tom Becker", "Todd"]
    assert [name for name, _ in listed("**agenda, rigging", names)] == ["Rigging plan"]
    assert ("Business team meeting", "Meeting") in listed("**agenda, bus", names)


def test_a_name_on_no_list_finds_nothing(names):
    assert listed("**agenda, Zed", names) == []  # as the # list: an agenda is never a new person


def test_a_pick_puts_in_what_the_at_and_hash_lists_would(names):
    assert picked("**agenda, tom", names) == "**agenda, @Tom Becker "
    assert picked("**agenda, @Tom Becker and bus", names) == "**agenda, @Tom Becker and #Business team meeting "
    assert picked("**agenda, tod", names) == "**agenda, Today "
    t = typed("**agenda, rigg", names)
    [o] = items.options(t, names)
    assert (items.remembered(t, o), o.ref) == ("#rigging plan", RIGGING)
    t = typed("**agenda, pri", names)
    assert items.remembered(t, items.options(t, names)[0]) == "@priya shah"
    assert items.remembered(typed("**agenda, tod", names), items.Option("Today", "Today")) is None


def test_a_picked_line_reads_as_the_agendas_picked(names):
    line = picked("- @Mike book the crane **agenda, @Tom Becker and bus", names)
    r = items.read(line.strip(), names, DAY, home=True)
    assert [it.value.changes for it in r.items if it.op and it.op.task_field == "agenda"] == [{"agenda": [TOM, MEETING]}]


def test_an_at_or_hash_word_keeps_its_own_list(names):
    assert typed("**agenda, @to", names).sigil == "@"
    assert typed("**agenda, Today and #rigg", names).sigil == "#"
    assert typed("**agenda, @Tom Becker ", names).sigil == "@"  # right after a pick: the capture window hides it


def test_an_at_word_run_on_past_an_and_gives_way_to_the_next_name(names):
    t = typed("**agenda, @Tom Becker and pri", names)
    assert (t.of, t.q) == ("agendas", "pri") and listed("**agenda, @Tom Becker and pri", names)[0][0] == "Priya Shah"


# ---- names that hold "and" or a comma (decision 623) ----
@pytest.fixture
def ands():
    return items.Names([ParsePerson(TOM, "Tom Becker", ("Tom",)), ParsePerson("P001", "Me", me=True)],
                       [items.RefTask("T000001", "Rigging and lifting"), items.RefTask("T000002", "Rigging plan")],
                       labels=["Health and safety", "Safety", "Line 1"])


def test_a_whole_name_holding_and_is_listed_whole(ands):
    t = typed("**label, Health and s", ands)
    assert (t.q, t.start) == ("Health and s", len("**label, "))
    assert [o.label for o in items.options(t, ands)][0] == "Health and safety"
    assert picked("**agenda, Rigging and l", ands) == "**agenda, #Rigging and lifting "
    assert typed("**label, Safety and l", ands).q == "l"  # nothing starts "Safety and l": the next name


def test_labels_holding_and_read_as_one(ands):
    r = items.read("Fix the rail **label, Health and safety, Safety and Fire", ands, DAY, new_task=True)
    [it] = [it for it in r.items if it.op and it.op.task_field == "labels"]
    assert it.value.changes == {"labels": ["Health and safety", "Safety", "Fire"]}
    assert it.title == "Health and safety, Safety, Fire (new)"


def test_an_agenda_holding_and_after_another_reads_as_two(ands):
    r = items.read("Fix the rail **agenda, @Tom and #Rigging and lifting", ands, DAY, new_task=True)
    [it] = [it for it in r.items if it.op and it.op.task_field == "agenda"]
    assert it.value.changes == {"agenda": [TOM, "T000001"]} and not it.problem


def test_the_runs_take_the_longest_name_first():
    known = {"a and b": 1, "a": 2, "c": 3}.get
    assert items._runs("a and b and c, d", lambda w: known(w.lower())) == [("a and b", 1), ("c", 3), ("d", None)]
    assert items._runs(" , a,, c ", lambda w: known(w.lower())) == [("a", 2), ("c", 3)]
    assert items._runs("", known) == []


def test_today_still_reads(names):
    r = items.read("Fix the rail **agenda, today", names, DAY, new_task=True)
    [it] = [it for it in r.items if it.op and it.op.task_field == "agenda"]
    assert it.value.changes == {"agenda": [TODAY]}
