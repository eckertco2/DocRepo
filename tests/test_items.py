"""Items from operators (mods log round 2, M0048 phase 2, M0049, M0052; release 5.8): reading @, #, ** and the blocks."""
from __future__ import annotations

from datetime import date

import pytest

from docrepo import db, items, markup
from docrepo.model import Model
from docrepo.parse import ParsePerson
from docrepo.sample import load_sample

TODAY = date(2026, 10, 8)
NOTES = """Agenda: Ask whether the December shutdown dates are confirmed.
Yes, 14 to 18 Dec.

#Reactor impeller upgrade
Impeller is on site, alignment booked.
- @Tom get the vendor's alignment report by Friday, 2 hours
  - include the shaft runout
- @L.Priya @Mike review the lift study next week
- **decision, we go with the 50 t crane.

#Q4 overtime budget
- **closed, #Rigging plan sling drawing approved
- **u, waiting on the vendor quote
- Ask @Tom about the seal kit, and email tom@example.com
- Pump #3 is noisy again
- @__ check the coupling guard bolts
- @Sam to book the scaffolding"""


@pytest.fixture(scope="module")
def model():
    conn = db.connect_memory()
    load_sample(conn)
    yield Model(conn)
    conn.close()


def names_of(model, prefer=None) -> items.Names:
    people = [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == "P001") for p in model.people.values()]
    return items.names_of(model, people, prefer)


def test_reading_operators(model):
    names = names_of(model)
    toks = items.scan("@Tom and @L.Priya Shah, @__, @Sam, tom@example.com #Rigging plan #T000008 Pump #3 ** t **t, **closed, **u, **n, **decision,", names)
    assert [(x.kind, x.id, x.name, x.lead, x.none) for x in toks if x.kind == "person"] == [
        ("person", "P003", "Tom Becker", False, False), ("person", "P002", "Priya Shah", True, False),
        ("person", None, "", False, True), ("person", None, "Sam", False, False)]
    assert [x.id for x in toks if x.kind == "task"] == ["T000012", "T000008"]  # "Pump #3" stays text
    assert [(x.item_type, x.state) for x in toks if x.kind == "type"] == [("task", ""), ("update", "Closed"), ("update", ""), ("note", ""), ("decision", "")]
    stored = items.scan("@[Tom Becker](P003) and @L.[Thomas](P003) on #[Old title](T000012)", names)
    assert [(x.kind, x.id, x.lead) for x in stored] == [("person", "P003", False), ("person", "P003", True), ("task", "T000012", False)]


@pytest.mark.parametrize("line, title", [
    ("Crane walkdown done with @Mike.", "Crane walkdown done with Mike."),
    ("@Tom and @Mike check the guards", "Check the guards"),
    ("Get the quote @Tom", "Get the quote"),
    ("Ask @Tom about the seal", "Ask Tom about the seal"),
    ("@Sam to book the scaffolding", "Book the scaffolding"),
    ("Book scaffolding for @Tom", "Book scaffolding for Tom"),
    ("**closed, #Rigging plan sling drawing approved", "Sling drawing approved"),
    ("@L.Priya review it by Friday @Mike", "Review it by Friday"),
    ("Pump #3 noisy, see #T000012", "Pump #3 noisy, see Rigging plan"),
])
def test_a_line_without_its_operators(model, line, title):
    names = names_of(model)
    assert items.clean(line, items.scan(line, names), names) == title


def test_the_meeting_notes_items(model):
    r = items.read(NOTES, names_of(model), TODAY, home=True)
    got = [(it.kind, it.title, it.state, [x.name for x in it.assignees], [x.name for x in it.leads], it.none,
            [(w.kind, w.ref) for w in it.where]) for it in r.items]
    assert got == [
        ("note", "Impeller is on site, alignment booked", "", [], [], False, [("task", "T000001")]),
        ("task", "Get the vendor's alignment report", "", ["Tom Becker"], [], False, [("home", None), ("task", "T000001")]),
        ("task", "Review the lift study", "", ["Mike Ortiz"], ["Priya Shah"], False, [("home", None), ("task", "T000001")]),
        ("decision", "We go with the 50 t crane", "", [], [], False, [("task", "T000001")]),
        ("update", "Sling drawing approved", "Closed", [], [], False, [("task", "T000012")]),
        ("update", "Waiting on the vendor quote", "", [], [], False, [("task", "T000015")]),
        ("task", "Ask Tom about the seal kit, and email tom@example.com", "", ["Tom Becker"], [], False, [("home", None), ("task", "T000015")]),
        ("note", "Pump #3 is noisy again", "", [], [], False, [("task", "T000015")]),
        ("task", "Check the coupling guard bolts", "", [], [], True, [("home", None), ("task", "T000015")]),
        ("task", "Book the scaffolding", "", ["Sam"], [], False, [("home", None), ("task", "T000015")]),
    ]
    alignment = r.items[1]
    assert alignment.due == "2026-10-09" and alignment.assignee_hours == "2" and alignment.text.endswith("\n- include the shaft runout")
    assert [h.tasks for h in r.headings] == [["T000001"], ["T000015"]]
    assert items.discussed(r, "T000001") and items.discussed(r, "T000015") and not items.discussed(r, "T000016")
    kinds = items.line_kinds(r)
    assert kinds[3] == "heading" and kinds[5] == "task" and kinds[6] == "task" and 0 not in kinds  # the first lines stay in the notes


def test_blocks_headings_and_where_items_go(model):
    names = names_of(model)
    text = "#Installation\nCrane booked.\n\nRigging is late.\n- @Tom draw the slings\n  - @Mike check them\n  - **n, old slings scrapped.\n#Rigging plan\n"
    r = items.read(text, names, TODAY)
    note, tom, mike, scrapped = r.items
    assert note.kind == "note" and note.heading and note.text == "Crane booked.\nRigging is late."  # one note for the heading, past a blank line
    assert [(w.kind, w.ref) for w in tom.where] == [("task", "T000008")]  # nothing picked: only its # task
    assert mike.parent_item == tom.key and [(w.kind, w.ref) for w in mike.where] == [("item", tom.key), ("task", "T000008")]
    assert scrapped.kind == "note" and [(w.kind, w.ref) for w in scrapped.where] == [("task", "T000008")]
    loose = items.read("@Tom pick up the seals\n**u, waiting on the vendor\n**n, a note on nothing", names, TODAY)
    assert [(w.kind,) for w in loose.items[0].where] == [("quick",)]  # a task with nowhere else goes under Quick tasks
    assert not loose.items[1].on and loose.items[1].problem == "Needs a #task to update"
    assert not loose.items[2].on and "stays in the notes" in loose.items[2].problem


def test_a_new_tasks_own_first_line(model):
    names = names_of(model)
    text = "@Tom check the coupling alignment #Rigging plan\n- @Mike paint the guard rails by Friday\n- **n, the old coupling goes back to stores."
    r = items.read(text, names, TODAY, home=True, new_task=True)
    own = items.self_fields(r, names)
    assert [x.id for x in own.assignees] == ["P003"] and own.tasks == ["T000012"] and own.text == "Check the coupling alignment"
    # The other items go under the new task (list items after a line of text aren't nested under it).
    assert [(it.kind, it.title, [(w.kind, w.ref) for w in it.where]) for it in r.items] == [
        ("task", "Paint the guard rails", [("home", None)]), ("note", "The old coupling goes back to stores", [("home", None)])]
    assert items.parse_text(r, names) == "Check the coupling alignment"  # Parse and populate reads only the rest


def test_a_cards_changes_stay(model):
    names = names_of(model)
    ov = {"0": {"title": "Get the vendor report", "due": "2026-10-23"}, "1": {"off": True}}
    r = items.read("- @Tom get the report by Friday\n- @Mike paint the rails", names, TODAY, home=True, overrides=ov)
    assert (r.items[0].title, r.items[0].due, r.items[0].changed, r.items[1].on) == ("Get the vendor report", "2026-10-23", True, False)
    edited = items.read("- @Tom get the full report by Friday\n- @Mike paint the rails red", names, TODAY, home=True, overrides=ov)
    assert edited.items[0].title == "Get the vendor report" and not edited.items[1].on  # still, after the lines changed


def test_the_lists_while_typing(model):
    names = names_of(model)
    t = items.typing("- @ty")
    assert (t.sigil, t.q, t.start) == ("@", "ty", 2)
    assert [(o.value, o.ref, o.add) for o in items.options(t, names)] == [("Tyler Nguyen", "P005", False), ("ty", None, True)]
    assert [o.ref for o in items.options(items.typing("see #rigging pl"), names)] == ["T000012"]
    assert [o.value for o in items.options(items.typing("@"), names)][-1] == "__"
    assert items.typing("mail tom@exa") is None and items.options(items.typing("@Tom get the report"), names) == []


def test_capture_md_keeps_ids(model):
    names = names_of(model)
    stored = items.store("- @Tom and @L.Priya check #Rigging plan\nPump #3 @Sam", names)
    assert stored == "- @[Tom Becker](P003) and @L.[Priya Shah](P002) check #[Rigging plan](T000012)\nPump #3 @Sam"
    assert items.unstore(stored) == "- @Tom Becker and @L.Priya Shah check #Rigging plan\nPump #3 @Sam"
    assert items.refs_of(stored) == {"@tom becker": "P003", "@priya shah": "P002", "#rigging plan": "T000012"}
    # Formatted text keeps its marks around each name.
    rich = items.store('- **@Tom** check #Rigging plan <mark class="green">now</mark>', names, formatted=True)
    assert rich == '- **@[Tom Becker](P003)** check #[Rigging plan](T000012) <mark class="green">now</mark>'
    assert markup.to_plain(rich) == "- @[Tom Becker](P003) check #[Rigging plan](T000012) now"
    # A name kept with its ID stays linked after a rename: the capture's own IDs come first.
    renamed = items.Names([ParsePerson("P003", "Thomas Becker", ("Tom",))], [items.RefTask("T000012", "Rigging plan")], items.refs_of(stored))
    assert items.store("@Tom Becker has it", renamed) == "@[Thomas Becker](P003) has it"
    assert items.words("- @Tom to send it, see #Rigging plan", names) == "- Send it, see Rigging plan"


def test_an_event_line_is_a_plant_event(model):
    """Release 5.9 (decision 22): **event, makes a task with Plant event ticked. The end date the event's own name
    made a Deadline is its Due, so it runs from its Start to its Due."""
    r = items.read("**event, Spring outage, 3 to 14 Nov\n**Event, Fall turnaround from 2 Nov to 6 Nov @Tom\n**events are fun",
                   names_of(model), TODAY)
    assert [(it.kind, it.plant_event, it.title, it.start, it.due, it.deadline) for it in r.items] == [
        ("task", True, "Spring outage", "2026-11-03", "2026-11-14", None), ("task", True, "Fall turnaround", "2026-11-02", "2026-11-06", None)]
    assert [x.id for x in r.items[1].assignees] == ["P003"]
    assert not items.read("@Tom book the outage crane by 14 Nov", names_of(model), TODAY).items[0].plant_event  # no reading of event words


def test_the_words_plant_event_make_a_plant_event(model):
    """Mods log round 3 (M0059, decision 58): a task item that says "plant event" or "major event" is one, and **event,
    on a new task's own line ticks the new task's own Plant event."""
    r = items.read("Walkdown done.\n- @Tom plan the line 2 rebuild, a major event, 9 to 20 Nov", names_of(model), TODAY)
    assert [(it.plant_event, it.start, it.due) for it in r.items] == [(True, "2026-11-09", "2026-11-20")]
    r = items.read("**event, Spring outage, 3 to 14 Nov\nScope agreed.", names_of(model), TODAY, new_task=True)
    own = items.self_fields(r, names_of(model))
    assert own.plant_event and r.items == []
    assert not items.self_fields(items.read("Spring outage, 3 to 14 Nov", names_of(model), TODAY, new_task=True), names_of(model)).plant_event


# ---- sub-bullets (release 5.120, the owner's voice memo of 2026-11-11, decisions 444 to 446) ----
def test_a_bullets_sub_bullets_are_its_lines(model):
    """Decision 444, as it's been since release 5.8: a bullet's sub-bullets with no operator of their own are its task's,
    its update's or its note's lines, and a task in a sub-bullet under a task's bullet goes under that task only."""
    names = names_of(model)
    r = items.read("- @Tom order seals\n  - ask about lead time\n    - two quotes\n  - @Mike book the crane\n    - 50 t", names, TODAY, home=True)
    seals, crane = r.items
    assert seals.text == "Order seals\n- ask about lead time\n  - two quotes" and [(w.kind,) for w in seals.where] == [("home",)]
    assert crane.text == "Book the crane\n- 50 t" and [(w.kind, w.ref) for w in crane.where] == [("item", seals.key)]
    update = items.read("- #Rigging plan **in progress, crane booked\n  - slings checked", names, TODAY).items[0]
    assert update.kind == "update" and update.text == "Crane booked\n- slings checked"


def test_a_task_in_a_sub_bullet_goes_under_its_parent_bullets_task(model):
    """Decision 445: under the # task its parent bullet names, in the capture's task's place; a # of its own, or a top
    bullet, is as before."""
    names = names_of(model)
    text = "- #Rigging plan\n  - crane is booked\n  - @Tom check the slings\n  - @Mike order shackles #Installation"
    note, tom, mike = items.read(text, names, TODAY, home=True, own="T000010").items
    assert note.kind == "note" and [(w.kind, w.ref) for w in note.where] == [("task", "T000012")]
    assert [(w.kind, w.ref) for w in tom.where] == [("task", "T000012")]  # not under the capture's task too
    assert [(w.kind, w.ref) for w in mike.where] == [("home", None), ("task", "T000008")]
    top = items.read("- @Tom check the slings #Rigging plan", names, TODAY, home=True).items[0]
    assert [(w.kind, w.ref) for w in top.where] == [("home", None), ("task", "T000012")]
    update = "- #Rigging plan **in progress, crane booked\n  - @Tom check the slings"
    assert [(w.kind, w.ref) for w in items.read(update, names, TODAY, home=True).items[1].where] == [("task", "T000012")]
    meeting = "#Rigging plan\n- crane is booked\n  - @Tom check the slings\n- @Mike order shackles"
    tom, mike = [x for x in items.read(meeting, names, TODAY, home=True).items if x.kind == "task"]
    assert [(w.kind, w.ref) for w in tom.where] == [("task", "T000012")]  # a sub-bullet, under the heading's task
    assert [(w.kind, w.ref) for w in mike.where] == [("home", None), ("task", "T000012")]  # a top bullet under a heading, as before


def test_the_bullet_tree_of_a_sub_bullet():
    """Decision 446: from its top bullet to the last line under it."""
    lines = ["Intro", "- top", "  - a", "    - b", "\t- c", "- next", "", "  - stray", "  - its sibling", "Text"]
    assert items.bullet_tree(lines, 3) == (1, 5) and items.bullet_tree(lines, 4) == (1, 5)
    assert items.bullet_tree(lines, 1) is None and items.bullet_tree(lines, 0) is None  # a top bullet, and a line of text
    assert items.bullet_tree(lines, 8) == (7, 9)  # no top bullet: from the first of its run
    assert [items.list_level(x) for x in lines[:5]] == [-1, 0, 1, 2, 1]
