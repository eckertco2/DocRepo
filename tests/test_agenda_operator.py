"""``**agenda,`` (release 5.133, decisions 540 to 545, the owner's ask of 2026-11-11): a task written in the capture
window's content text, the New task itself, a sub-bullet task or a ``#`` task goes on the agendas its line names, a
person's, a meeting's, another task's or Today, with the line's other words as the item's note."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import items
from docrepo.config import Settings
from docrepo.model import TODAY, Model
from docrepo.save import CaptureDraft, item_names, save_capture

DAY = date(2026, 10, 8)
AT = datetime(2026, 10, 8, 9, 0)
TOM, PRIYA = "P003", "P002"
INSTALLATION, RIGGING, MEETING, MONITORING = "T000008", "T000012", "T000010", "T000011"


@pytest.fixture
def names(sample_conn):
    return item_names(Model(sample_conn), Settings(me="P001"))


def agendas(text: str, names: items.Names, **kw) -> list[items.Item]:
    """The **agenda, cards a text makes."""
    kw.setdefault("home", True)
    return [it for it in items.read(text, names, DAY, **kw).items if it.op and it.op.task_field == "agenda"]


def where(it: items.Item) -> list[tuple[str, str | None]]:
    return [(w.kind, w.ref) for w in it.where]


# ---- reading ----
def test_the_new_tasks_own_line_puts_the_new_task_on_the_agenda(names):
    [it] = agendas("Review the lift plan **agenda, Tom.", names, new_task=True)
    assert it.value.changes == {"agenda": [TOM]} and it.title == "Tom Becker"
    assert where(it) == [("home", None)] and it.note == "" and not it.problem


def test_an_at_task_item_goes_on_the_agendas_named(names):
    r = items.read("- @Mike book the crane **agenda, @Tom and #Business team meeting", names, DAY, home=True, own=INSTALLATION)
    task, agenda = r.items
    assert task.kind == "task" and task.title == "Book the crane"
    assert agenda.value.changes == {"agenda": [TOM, MEETING]} and where(agenda) == [("item", task.key)] and agenda.note == ""


def test_a_sub_bullet_task_goes_on_it_and_a_plain_sub_bullet_puts_its_parent_task(names):
    text = "- @Mike book the crane\n  - @Tyler order the shackles **agenda, Priya\n  - ask about the hire rate **agenda, today"
    r = items.read(text, names, DAY, home=True, own=INSTALLATION)
    crane, shackles, on_shackles, on_crane = r.items
    assert shackles.kind == "task" and where(on_shackles) == [("item", shackles.key)] and on_shackles.note == ""
    assert on_shackles.value.changes == {"agenda": [PRIYA]}
    assert where(on_crane) == [("item", crane.key)] and on_crane.value.changes == {"agenda": [TODAY]}
    assert on_crane.note == "Ask about the hire rate" and on_crane.title == "Today"


def test_a_hash_task_line_puts_that_task_with_its_words_as_the_note(names):
    [it] = agendas("#Rigging plan check the slings **agenda, Tom.", names, own=INSTALLATION)
    assert where(it) == [("task", RIGGING)] and it.note == "Check the slings" and not it.problem


def test_a_plain_line_puts_the_captures_task_with_its_words(names):
    [it] = agendas("Ask about the crane hire **agenda, Tom.", names, own=INSTALLATION)
    assert where(it) == [("home", None)] and it.note == "Ask about the crane hire"


def test_with_no_task_the_words_go_on_alone_and_with_none_it_stays_in_the_notes(names):
    [it] = agendas("Ask about the crane hire **agenda, Tom.", names, home=False)
    assert it.where == [] and it.note == "Ask about the crane hire" and not it.problem and it.on
    [bare] = agendas("**agenda, Tom.", names, home=False)
    assert bare.problem == "No task to put it on: it stays in the notes" and not bare.on


@pytest.mark.parametrize(("sentence", "found"), [
    ("Business team meeting", [MEETING]),  # a bare name that's no person is a task's
    ("T000010", [MEETING]),
    ("tom", [TOM]),  # an alias, in any case
    ("Tom Becker, Priya and today", [TOM, PRIYA, TODAY]),
    ("Tom and Tom", [TOM]),
])
def test_what_it_names(names, sentence, found):
    [it] = agendas(f"**agenda, {sentence}", names, own=INSTALLATION)
    assert it.value.changes == {"agenda": found} and not it.problem


@pytest.mark.parametrize(("sentence", "problem"), [
    ("me", "Your own agenda is Today: write **agenda, today"),
    ("Zed", "No person, meeting or task called Zed"),
    ("@Business team meeting", "No person, meeting or task called Business team meeting"),  # an @ is a person
    ("#Tom", "No person, meeting or task called Tom"),  # a # is a task
    ("", "Nothing after the comma"),
])
def test_what_it_cant_take(names, sentence, problem):
    [it] = agendas(f"Crane note **agenda, {sentence}", names, own=INSTALLATION)
    assert it.problem == problem and not it.on


def test_a_task_cant_go_on_its_own_agenda(names):
    [it] = agendas("**agenda, #Installation", names, own=INSTALLATION)
    assert it.problem == "A task can't be on its own agenda" and not it.on
    [both] = agendas("**agenda, Tom and #Installation", names, own=INSTALLATION)
    assert not both.problem  # Tom's is fine: Save leaves out Installation's own


def test_the_list_and_the_syntax_tab_have_it(names):
    assert "**agenda," in [o.label for o in items.star_options("agen", names)]
    row = next(r for r in items.syntax_rows() if r[0] == "**agenda,")
    assert row[1] == "**agendas," and row[2].startswith("Puts the task on each agenda named")


def test_the_new_tasks_title_leaves_it_out(names):
    assert items.without_params("Review the lift plan **agenda, Tom.", names) == "Review the lift plan"


# ---- saving ----
def save(sample_root, content: str, task: str | None = INSTALLATION, types: set[str] | None = None, minute: int = 0):
    conn, root, fs = sample_root
    return save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=content, task=task, types=types or {"note"}, files=[]),
                        datetime(2026, 10, 8, 9, minute))


def open_items(conn, target: str) -> list[tuple[str | None, str]]:
    return [(a.subject, a.note) for a in Model(conn).open_items_for(target)]


def test_saving_a_new_task_puts_it_on_the_agenda(sample_root):
    conn = sample_root[0]
    r = save(sample_root, "Review the lift plan **agenda, Tom.", types={"new_task"})
    assert Model(conn).task(r.created_task).title == "Review the lift plan"
    assert (r.created_task, "") in open_items(conn, TOM)
    assert r.made.get("agenda") == 1 and "1 agenda item" in r.message


def test_saving_task_items_puts_each_on_its_agendas(sample_root):
    conn = sample_root[0]
    before = len(open_items(conn, MEETING))
    r = save(sample_root, "Crane plan.\n- @Mike book the crane **agenda, @Tom and #Business team meeting\n  - ask about the hire rate **agenda, today")
    crane = Model(conn).captures[r.items[0]].created_task
    assert Model(conn).task(crane).title == "Book the crane" and INSTALLATION in Model(conn).parents_of(crane)
    assert (crane, "") in open_items(conn, TOM) and (crane, "") in open_items(conn, MEETING)
    assert len(open_items(conn, MEETING)) == before + 1
    assert (crane, "Ask about the hire rate") in [(a.subject, a.note) for a in Model(conn).today_items()]
    assert r.made.get("agenda") == 3 and r.unused == 0


def test_saving_a_hash_task_line_and_a_plain_line(sample_root):
    conn = sample_root[0]
    save(sample_root, "#Rigging plan check the slings **agenda, Tom.\nAsk about the crane hire **agenda, Priya.")
    assert (RIGGING, "Check the slings") in open_items(conn, TOM)
    assert (INSTALLATION, "Ask about the crane hire") in open_items(conn, PRIYA)


def test_with_no_task_the_note_goes_on_alone(sample_root):
    conn = sample_root[0]
    save(sample_root, "Ask about the crane hire **agenda, Tom.", task=None)
    assert (None, "Ask about the crane hire") in open_items(conn, TOM)


def test_a_task_already_on_the_agenda_isnt_added_again_nor_one_on_its_own(sample_root):
    conn = sample_root[0]
    assert (MONITORING, ) == tuple(s for s, _ in open_items(conn, TOM) if s == MONITORING)  # the sample has it on Tom's already
    r = save(sample_root, "#Draft monitoring plan **agenda, Tom.")
    assert [s for s, _ in open_items(conn, TOM)].count(MONITORING) == 1 and r.unused == 0 and not r.made.get("agenda")
    r2 = save(sample_root, "**agenda, Priya and #Installation", minute=5)
    assert (INSTALLATION, "") in open_items(conn, PRIYA) and open_items(conn, INSTALLATION) == [] and r2.made.get("agenda") == 1


def test_the_targets_page_is_written(sample_root):
    conn, root, _ = sample_root
    # Monthly safety report touches nothing of these two, so only the agenda line can bring the target's page up to date.
    save(sample_root, "#Q4 cost reduction **agenda, #Verification walkthrough readiness.", task="T000006")
    assert ("T000003", "") in open_items(conn, "T000002")
    page = (root / "Tasks" / "T000002" / "Task.md").read_text(encoding="utf-8")
    assert "## Agenda" in page and "Q4 cost reduction" in page.split("## Agenda", 1)[1]
