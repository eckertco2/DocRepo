"""Quick input (release 5.38, round 5's item 67, decisions 200 to 209): the ** names read as the mockup's test vectors say,
what Save does with them, and their cards in the capture window."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from conftest import FIXTURES  # noqa: E402
from docrepo import captures, db, items  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.parse import ParsePerson  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import CaptureDraft, NewTaskFields, add_quick_task, save_capture  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from test_parse_vectors import split_row  # noqa: E402

TODAY = date(2026, 10, 8)
AT = datetime(2026, 10, 8, 9, 30)
#: Made up, as in the test vectors: the real names are only ever typed into Settings.
FIELDS = ["Work order #", "Permit no."]
SETTINGS = Settings(me="P001", reference_fields=FIELDS)


def _rows(title: str) -> list[list[str]]:
    text = (FIXTURES / "test-vectors.md").read_text(encoding="utf-8")
    part = text[text.index("## Quick input"):text.index("## Parse and populate")]
    part = part[part.index(f"### {title}"):]
    part = part[:part.find("\n### ", 4)] if "\n### " in part[4:] else part
    return [split_row(line) for line in part.split("\n")[2:] if line.startswith("| ") and not line.startswith(("|---", "| Line |", "| Task |"))]


PICKED, ON_TASK, NEW_TASK = _rows("With a task picked"), _rows("On an existing task"), _rows("With New task ticked")


@pytest.fixture(scope="module")
def model():
    conn = db.connect_memory()
    load_sample(conn)
    yield Model(conn)
    conn.close()


def names_of(model, fields=FIELDS) -> items.Names:
    people = [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == "P001") for p in model.people.values()]
    return items.names_of(model, people, None, fields)


def reads(r: items.Reading, names: items.Names, new_task: bool = False) -> str:
    own = items.self_fields(r, names) if new_task else None
    said = [f'Its own line "{own.text}"' + (" Plant event" if own.plant_event else "")] if own and own.any else []
    return " / ".join([*said, *(items.item_text(it, names) for it in r.items)]) or "Stays in the notes."


# ---- the mockup's test vectors ----
def test_the_vectors_were_read():
    assert len(PICKED) > 90 and len(ON_TASK) > 10 and len(NEW_TASK) > 4


@pytest.mark.parametrize("line, expected", PICKED, ids=[r[0][:50] for r in PICKED])
def test_a_line_with_a_task_picked_reads_as_the_mockup_does(model, line, expected):
    names = names_of(model)
    assert reads(items.read(line, names, TODAY, home=True), names) == expected


@pytest.mark.parametrize("task, line, expected", ON_TASK, ids=[r[1][:50] for r in ON_TASK])
def test_a_line_on_an_existing_task_reads_as_the_mockup_does(model, task, line, expected):
    names = names_of(model)
    assert reads(items.read(line, names, TODAY, home=True, own=task), names) == expected


@pytest.mark.parametrize("line, expected", NEW_TASK, ids=[r[0][:50] for r in NEW_TASK])
def test_a_line_with_new_task_ticked_reads_as_the_mockup_does(model, line, expected):
    names = names_of(model)
    assert reads(items.read(line, names, TODAY, home=True, new_task=True), names, True) == expected


# ---- reading ----
def test_your_example_is_one_window_in_2027(model):
    it = items.read("**key date, trial window from November 1st to November 5th, 2027.", names_of(model), TODAY, home=True).items[0]
    assert (it.key_date.start, it.key_date.end, it.key_date.description) == ("2027-11-01", "2027-11-05", "Trial window")


def test_a_sentence_ends_at_its_period_and_the_rest_stays(model):
    names = names_of(model)
    text = "Trial run next month. **due, Nov. 5. Walkdown first."
    toks = items.scan(text, names)
    assert [(x.kind, x.sentence, text[x.start:x.until]) for x in toks] == [("param", "Nov. 5", "**due, Nov. 5.")]
    assert items.clean(text, toks, names) == "Trial run next month. Walkdown first."
    r = items.read(text, names, TODAY, home=True)
    assert [it.kind for it in r.items] == ["param"] and items.parse_text(r, names) == "Trial run next month. Walkdown first."


def test_a_line_of_parameters_is_left_out_of_parse_and_populate_and_of_the_title(model):
    names = names_of(model)
    r = items.read("Line 2 trial\n**due, 5 Nov.\n**lead, Tom.", names, TODAY, home=True, new_task=True)
    assert items.parse_text(r, names) == "Line 2 trial"
    assert items.without_params("**due, 5 Nov.\nLine 2 trial **lead, Tom.", names) == "Line 2 trial"
    assert items.words("**reminder, 5 Nov.", names) == "Reminder, 5 Nov."  # a capture of nothing else is still called something


def test_an_at_or_a_hash_in_a_sentence_is_its_own(model):
    names = names_of(model)
    r = items.read("**key date, review with @Tom by Nov 25, #Rigging plan.", names, TODAY, home=True)
    assert [(it.kind, it.key_date.description, [w.ref for w in it.where]) for it in r.items] == [("date", "Review with Tom", ["T000012"])]  # no task for Tom
    assert items.named_tasks(r) == ["T000012"]  # it still fills the task picker, as a # does
    assert items.store("**lead, @Tom. **key date, by Nov 25 #Rigging plan.", names) == (
        "**lead, @[Tom Becker](P003). **key date, by Nov 25 #[Rigging plan](T000012).")  # kept with their IDs, as ever
    # A parent's sentence is all value: its # isn't a link to another task, and fills nothing.
    r = items.read("**parent, #Rigging plan.", names, TODAY, home=True)
    assert r.items[0].value.changes == {"parents": ["T000012"]} and [w.kind for w in r.items[0].where] == ["home"] and items.named_tasks(r) == []


def test_a_checklist_line_reads_no_parameters(model):
    names = names_of(model)
    assert items.read("- [ ] Book it **due, 5 Nov.", names, TODAY, home=True).items == []


def test_a_reference_field_comes_only_from_settings(model):
    with_it, without = names_of(model), names_of(model, [])
    assert items.read("**work order, 48213.", with_it, TODAY, home=True).items[0].value.changes == {"references": {"Work order #": "48213"}}
    assert items.read("**work order, 48213.", without, TODAY, home=True).items[0].problem == "No field called work order"


def test_adding_a_parameter_is_one_entry(model, monkeypatch, sample_root):
    """Thread A's new parameters: an entry in the table, and nothing else."""
    op = items.Operator(("kickoff",), label="Kickoff", task_field="start", read=items._read_date)
    monkeypatch.setitem(items._BY_NAME, "kickoff", op)
    names = names_of(model)
    it = items.read("**kickoff, 5 Nov.", names, TODAY, home=True).items[0]
    assert (it.label, it.value.shown, it.on) == ("Kickoff", "2026-11-05", True)
    conn, root, fs = sample_root
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Plan.\n**kickoff, 5 Nov.", types={"new_task"}, new_task=NewTaskFields(title="New one")), AT)
    assert Model(conn).tasks[r.created_task].start == "2026-11-05"


# ---- Save ----
def save(sample_root, draft: CaptureDraft):
    conn, root, fs = sample_root
    return save_capture(conn, root, fs, SETTINGS, draft, AT), Model(conn)


def test_an_empty_field_fills_and_a_filled_one_stays(sample_root):
    """Decision 200: T000012 is due 14 Oct, with no reminder."""
    r, m = save(sample_root, CaptureDraft(content="Walkdown.\n**due, 5 Nov.\n**reminder, 5 Nov.\n**work order, #48213.", task="T000012"))
    t = m.tasks["T000012"]
    assert (t.due, t.reminder, t.references) == ("2026-10-14", "2026-11-05", {"Work order #": "48213"})
    assert r.made == {"param": 2} and "Made 2 fields from its items." in r.message and "1 line wasn't used: it stays in the notes." in r.message
    log = sample_root[0].execute("SELECT field, via FROM status_log WHERE task = 'T000012' AND via = ?", (r.capture_id,)).fetchall()
    assert sorted(x["field"] for x in log) == ["Reminder", "Work order #"]
    assert "**due, 5 Nov." in captures.read_content(sample_root[1], m.captures[r.capture_id])  # the notes keep the lines
    assert not any(c.from_notes == r.capture_id for c in m.captures.values())  # no capture of their own


def test_lists_add(sample_root):
    content = "Notes.\n**assignee, Tom and Kim Lee.\n**label, safety, Line 9.\n**parent, Reactor impeller upgrade.\n**key date, by Nov 25 prep."
    r, m = save(sample_root, CaptureDraft(content=content, task="T000012"))
    t = m.tasks["T000012"]
    assert t.assignees[0] == "P004" and "P003" in t.assignees and len(t.assignees) == 3 and r.added_people == ["Kim Lee"]
    assert t.labels == ["Safety", "Line 9"]
    assert {p for chain in m.chains_of("T000012") for p in chain} >= {"T000001"}
    assert [kd.description for kd in m.key_dates_of("T000012")] == ["Prep"]
    assert r.made == {"date": 1, "param": 3}


def test_a_new_task_takes_its_lines_even_over_the_form(sample_root):
    content = "Line 2 trial\n**due, 5 Nov.\n**lead, Tom.\n**hours, 12.\n**priority, high.\n**urgent, yes.\n**state, parked.\n**deadline, 19 Nov, the external audit."
    r, m = save(sample_root, CaptureDraft(content=content, types={"new_task"}, new_task=NewTaskFields(due="2026-10-30")))
    t = m.tasks[r.created_task]
    assert (t.title, t.description, t.due) == ("Line 2 trial", "Line 2 trial", "2026-11-05")
    assert (t.leads, t.assignee_hours, t.priority, t.urgent, t.state) == (["P003"], 12.0, "high", True, "Parked")
    assert (t.deadline, t.deadline_desc) == ("2026-11-19", "The external audit")


def test_a_new_task_s_title_skips_a_line_of_parameters(sample_root):
    r, m = save(sample_root, CaptureDraft(content="**due, 5 Nov.\nLine 2 trial", types={"new_task"}))
    t = m.tasks[r.created_task]
    assert (t.title, t.description, t.due) == ("Line 2 trial", "Line 2 trial", "2026-11-05")


def test_a_task_item_takes_the_line_on_it(sample_root):
    r, m = save(sample_root, CaptureDraft(content="- @Tom check the pump. **due, 5 Nov.\n  - **hours, 3.", task="T000008"))
    made = next(c.created_task for c in m.captures.values() if c.from_notes == r.capture_id)
    assert (m.tasks[made].title, m.tasks[made].due, m.tasks[made].assignee_hours) == ("Check the pump", "2026-11-05", 3.0)
    assert m.tasks["T000008"].due == "2026-10-30" and m.tasks["T000008"].assignee_hours == 60


def test_the_kinds_moved(sample_root):
    r, m = save(sample_root, CaptureDraft(content="**closed, #Rigging plan sling drawing approved. Will recheck Friday.\n**decision, we go with option B. It's cheaper.",
                                          task="T000008"))
    assert m.tasks["T000012"].state == "Closed" and m.tasks["T000012"].current_status == "Sling drawing approved. Will recheck Friday."
    decision = next(c for c in m.captures.values() if c.from_notes == r.capture_id and c.item == "decision")
    assert "It's cheaper." in captures.read_content(sample_root[1], decision)  # decision 203: its whole line
    assert r.made == {"update": 1, "decision": 1}


def test_what_can_t_be_read_stays_in_the_notes(sample_root):
    content = "**vendor, Norvane.\n**Closed. Mike confirmed.\n**date Dec 1 to 5 trial window\n**due, sometime soon."
    r, m = save(sample_root, CaptureDraft(content=content, task="T000012"))
    t = m.tasks["T000012"]
    assert (t.state, t.due, m.key_dates_of("T000012")) == ("In progress", "2026-10-14", [])
    assert r.made == {} and "4 lines weren't used: they stay in the notes." in r.message
    assert content in captures.read_content(sample_root[1], m.captures[r.capture_id])


def test_a_value_the_task_can_t_take_changes_nothing(sample_root):
    r, m = save(sample_root, CaptureDraft(content="Notes.\n**repeat until, 1 Mar 2027.\n**parent, Rigging plan.", task="T000012"))
    assert m.tasks["T000012"].repeat_until is None and r.made == {}  # no recurrence to end, and it can't go under itself
    assert "2 lines weren't used" in r.message


def test_a_quick_task_reads_its_parameters(sample_root):
    conn, root, fs = sample_root
    r = add_quick_task(conn, root, fs, SETTINGS, "Call the vendor about seals **due, 5 Nov.", AT)
    t = Model(conn).tasks[r.created_task]
    assert t.title == "Call the vendor about seals" and t.due == "2026-11-05"


def test_a_capture_of_a_parameter_alone_is_still_called_something(sample_root):
    r, m = save(sample_root, CaptureDraft(content="**reminder, 5 Nov.", task="T000012"))
    assert m.captures[r.capture_id].title == "Reminder, 5 Nov"


def test_saved_captures_are_not_read_again(sample_root):
    """Decision 206: an old **date stays as written. Nothing rereads a saved capture's operators."""
    conn, root, fs = sample_root
    r, m = save(sample_root, CaptureDraft(content="Notes.\n**date Dec 1 to 5 Trial window", task="T000012"))
    before = captures.read_content(root, m.captures[r.capture_id])
    save(sample_root, CaptureDraft(content="Another.", task="T000012"))
    assert captures.read_content(root, Model(conn).captures[r.capture_id]) == before
    assert Model(conn).key_dates_of("T000012") == []


# ---- the capture window's cards ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, notify=lambda t, m: None, now=lambda: AT)
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()


def test_the_cards_show_what_was_read(window):
    window.set_task("T000012")
    window.content.setPlainText("**reminder, 5 Nov.\n**due, 6 Nov.\n**vendor, Norvane.\n**work order, 48213.\n**key date, trial window from 1 Nov to 5 Nov 2027.")
    window.read_items()
    cards = window.item_cards.cards
    assert [c.tick.text() for c in cards] == ["Reminder", "Due", "**vendor", "Work order #", "Key date"]
    assert [c.tick.isChecked() for c in cards] == [True, False, False, True, True]
    assert cards[0].title.text() == "Thu 5 Nov" and cards[0].title.isReadOnly()
    assert not cards[4].title.isReadOnly() and cards[4].title.text() == "Trial window"  # a key date's description is yours to change
    said = " ".join(x.text() for x in cards[1].findChildren(QLabel))
    assert "Due is already Wed 14 Oct: change it with Update or Edit task" in said
    kinds = items.line_kinds(window.reading)
    assert (kinds[0], kinds[1], kinds[4]) == ("param", "off", "date")


def test_save_uses_the_window_s_cards(window, sample_root):
    conn = sample_root[0]
    window.set_task("T000012")
    window.content.setPlainText("Walkdown.\n**reminder, 5 Nov.")
    window.read_items()
    draft = window.draft()
    r = save_capture(conn, sample_root[1], sample_root[2], SETTINGS, draft, AT)
    assert Model(conn).tasks["T000012"].reminder == "2026-11-05" and r.made == {"param": 1}
