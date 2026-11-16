"""``**today`` (release 5.147, decisions 641 and 642, the owner's ask of 2026-11-13): ``**agenda, today`` in one word, with
no comma and no sentence, wherever ``**agenda,`` works: a task item's line, a sub-bullet task, a ``#task`` line, the New
task's own first line, or a plain line under a task. The rest is ``**agenda,``'s (release 5.133)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import agenda, edits, items
from docrepo.config import Settings
from docrepo.model import TODAY, Model
from docrepo.save import CaptureDraft, item_names, save_capture

DAY = date(2026, 10, 8)
TOM = "P003"
INSTALLATION, RIGGING, MEETING = "T000008", "T000012", "T000010"


@pytest.fixture
def names(sample_conn):
    return item_names(Model(sample_conn), Settings(me="P001"))


def agendas(text: str, names: items.Names, **kw) -> list[items.Item]:
    """The agenda cards a text makes, **agenda,'s and **today's."""
    kw.setdefault("home", True)
    return [it for it in items.read(text, names, DAY, **kw).items if it.op and it.op.task_field == "agenda"]


def where(it: items.Item) -> list[tuple[str, str | None]]:
    return [(w.kind, w.ref) for w in it.where]


def on_today(it: items.Item) -> bool:
    return it.value is not None and it.value.changes == {"agenda": [TODAY]} and it.title == "Today" and it.label == "Agenda"


# ---- reading: each place **agenda, works ----
def test_the_new_tasks_own_line(names):
    [it] = agendas("Review the lift plan **today", names, new_task=True)
    assert on_today(it) and where(it) == [("home", None)] and it.note == "" and not it.problem and it.on
    assert items.without_params("Review the lift plan **today", names) == "Review the lift plan"
    r = items.read("Review the lift plan **today", names, DAY, home=True, new_task=True)
    assert items.parse_text(r, names) == "Review the lift plan"  # Parse and populate doesn't read it as a date


def test_a_line_under_the_new_task_puts_the_new_task_with_its_words(names):
    [it] = agendas("Review the lift plan\n- ask about the hire rate **today", names, new_task=True)
    assert on_today(it) and where(it) == [("home", None)] and it.note == "Ask about the hire rate"


def test_an_at_task_item(names):
    r = items.read("- @Mike book the crane **today", names, DAY, home=True, own=INSTALLATION)
    task, it = r.items
    assert task.kind == "task" and task.title == "Book the crane" and not r.unread
    assert on_today(it) and where(it) == [("item", task.key)] and it.note == "" and not it.problem


def test_a_sub_bullet_task_and_a_plain_sub_bullet(names):
    text = "- @Mike book the crane\n  - @Tyler order the shackles **today\n  - ask about the hire rate **today"
    crane, shackles, on_shackles, on_crane = items.read(text, names, DAY, home=True, own=INSTALLATION).items
    assert shackles.kind == "task" and shackles.title == "Order the shackles"
    assert on_today(on_shackles) and where(on_shackles) == [("item", shackles.key)] and on_shackles.note == ""
    assert on_today(on_crane) and where(on_crane) == [("item", crane.key)] and on_crane.note == "Ask about the hire rate"


@pytest.mark.parametrize("line", ["#Rigging plan **today", "#Rigging plan **today.", "#Rigging plan **today,", "#Rigging plan **Today."])
def test_a_hash_task_line(names, line):
    [it] = agendas(line, names, own=INSTALLATION)
    assert on_today(it) and where(it) == [("task", RIGGING)] and it.note == "" and not it.problem


def test_a_hash_task_lines_other_words_are_the_note(names):
    [it] = agendas("#Rigging plan check the slings **today.", names, own=INSTALLATION)
    assert where(it) == [("task", RIGGING)] and it.note == "Check the slings"


def test_a_plain_line_puts_the_captures_task_saying_why(names):
    [it] = agendas("Ask about the hire rate **today", names, own=INSTALLATION)
    assert on_today(it) and where(it) == [("home", None)] and it.note == "Ask about the hire rate"
    [mid] = agendas("Ask about the hire rate **today. Then call him.", names, own=INSTALLATION)
    assert mid.note == "Ask about the hire rate. Then call him."  # a full stop with more after it is the line's


def test_its_full_stop_at_the_lines_end_is_its_own(names):
    task, it = items.read("- @Mike book the crane **today.", names, DAY, home=True, own=INSTALLATION).items
    assert task.title == "Book the crane" and on_today(it)
    [before_star] = agendas("Ask about the hire rate **today. **agenda, Tom.", names, own=INSTALLATION)[:1]
    assert before_star.note == "Ask about the hire rate"


def test_a_line_under_a_heading_puts_the_headings_task(names):
    [it] = agendas("#Rigging plan\nAsk about the hire rate **today", names, own=INSTALLATION)
    assert where(it) == [("task", RIGGING)] and it.note == "Ask about the hire rate"


def test_with_no_task_the_words_go_on_alone_and_with_none_it_stays_in_the_notes(names):
    [it] = agendas("Ask about the crane hire **today", names, home=False)
    assert on_today(it) and it.where == [] and it.note == "Ask about the crane hire" and not it.problem and it.on
    [bare] = agendas("**today", names, home=False)
    assert bare.problem == "No task to put it on: it stays in the notes" and not bare.on


# ---- reading: its comma, the words after it, and what isn't it ----
def test_its_comma_reads_the_same(names):
    plain = items.read("- @Mike book the crane **today", names, DAY, home=True, own=INSTALLATION).items
    comma = items.read("- @Mike book the crane **today,", names, DAY, home=True, own=INSTALLATION).items
    assert [(it.kind, it.title, it.where, it.note, it.problem) for it in plain] == [(it.kind, it.title, it.where, it.note, it.problem) for it in comma]


@pytest.mark.parametrize("line", ["- @Mike book the crane **today, before lunch", "- @Mike book the crane **today before lunch",
                                  "- @Mike book the crane **today and ask Tom, Priya and Sam"])
def test_the_words_after_it_stay_the_lines(names, line):
    r = items.read(line, names, DAY, home=True, own=INSTALLATION)
    task, it = r.items
    assert task.kind == "task" and task.title.startswith("Book the crane") and "today" not in task.text.lower()
    assert on_today(it) and not it.problem and where(it) == [("item", task.key)] and not r.unread


@pytest.mark.parametrize("line", ["Make the **todays list", "Some **today** words"])
def test_part_of_a_word_or_bold_isnt_it(names, line):
    assert agendas(line, names, own=INSTALLATION) == []


def test_with_agenda_tom_on_the_same_line_it_goes_on_both(names):
    for line in ("- @Mike book the crane **agenda, Tom **today", "- @Mike book the crane **today **agenda, Tom."):
        task, *cards = items.read(line, names, DAY, home=True, own=INSTALLATION).items
        assert task.title == "Book the crane", line
        assert sorted(it.value.changes["agenda"][0] for it in cards) == sorted([TOM, TODAY]), line
        assert all(where(it) == [("item", task.key)] and not it.problem for it in cards), line


def test_the_capture_title_has_it(names):
    assert items.words("**today", names) == "Today"  # a line of parameters only still names the capture


# ---- the ** list and the Syntax tab ----
def test_the_list_offers_it_with_no_comma(names):
    [today] = [o for o in items.star_options("tod", names) if o.label == "**today"]
    assert today.value == "today" and today.sub == "Field: @Mike book the crane **today"
    assert "**today" in [o.label for o in items.star_options("", names)]
    typing = items.typing("Crane note **tod")
    assert items.inserted(typing, today) == "**today "  # a pick puts in no comma
    assert items.typing("Crane note **today ") is None  # and the list goes
    assert items.typing("Crane note **today, ", names) is None  # it has no list of names after it


def test_the_syntax_tab_has_it(names):
    row = next(r for r in items.syntax_rows() if r[0] == "**today")
    assert row == ("**today", "", "Puts the task on Today, with no comma or sentence", "@Mike book the crane **today")
    assert "| `**today` |" in items.readme_table()


# ---- saving ----
def save(sample_root, content: str, task: str | None = INSTALLATION, types: set[str] | None = None, minute: int = 0):
    conn, root, fs = sample_root
    return save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=content, task=task, types=types or {"note"}, files=[]),
                        datetime(2026, 10, 8, 9, minute))


def today(conn) -> list[tuple[str | None, str]]:
    return [(a.subject, a.note) for a in Model(conn).today_items()]


def test_saving_a_new_task_puts_it_on_today(sample_root):
    conn = sample_root[0]
    r = save(sample_root, "Review the lift plan **today", types={"new_task"})
    assert Model(conn).task(r.created_task).title == "Review the lift plan"
    assert (r.created_task, "") in today(conn)
    assert r.made.get("agenda") == 1 and "1 agenda item" in r.message


def test_saving_task_items_and_a_plain_sub_bullet(sample_root):
    conn = sample_root[0]
    r = save(sample_root, "Crane plan.\n- @Mike book the crane **today\n  - ask about the hire rate **today")
    crane = Model(conn).captures[r.items[0]].created_task
    assert Model(conn).task(crane).title == "Book the crane" and INSTALLATION in Model(conn).parents_of(crane)
    assert [s for s, _ in today(conn)].count(crane) == 1  # the second line found it there already
    assert r.unused == 0


def test_saving_a_sub_bullet_task_puts_both_on_today(sample_root):
    conn = sample_root[0]
    r = save(sample_root, "Crane plan.\n- @Mike book the crane **today\n  - @Tyler order the shackles **today")
    m = Model(conn)
    crane, shackles = (m.captures[c].created_task for c in r.items[:2])
    assert m.task(shackles).title == "Order the shackles" and crane in m.parents_of(shackles)
    assert {crane, shackles} <= {s for s, _ in today(conn)}
    assert r.made.get("task") == 2 and r.made.get("agenda") == 2 and "2 tasks and 2 agenda items" in r.message


def test_saving_a_hash_task_line_and_a_plain_line(sample_root):
    conn = sample_root[0]
    save(sample_root, "#Rigging plan check the slings **today.\nAsk about the crane hire **today")
    assert (RIGGING, "Check the slings") in today(conn) and (INSTALLATION, "Ask about the crane hire") in today(conn)


def test_with_no_task_the_note_goes_on_alone(sample_root):
    conn = sample_root[0]
    save(sample_root, "Ask about the crane hire **today", task=None)
    assert (None, "Ask about the crane hire") in today(conn)


def test_a_task_already_on_today_isnt_added_twice(sample_root):
    conn = sample_root[0]
    save(sample_root, "#Rigging plan **today")
    r = save(sample_root, "#Rigging plan **today", minute=5)
    assert [s for s, _ in today(conn)].count(RIGGING) == 1 and r.unused == 0 and not r.made.get("agenda")


def test_it_goes_at_the_bottom_of_today_in_the_owners_order(sample_root):
    conn, root, fs = sample_root
    at = datetime(2026, 10, 8, 8, 0)
    for t in ("T000002", "T000001"):
        edits.add_to_today(conn, root, fs, t, "", at)
    first, second = (a.id for a in Model(conn).today_items())
    agenda.move_item(conn, second, 0)  # the owner's order (release 5.148)
    save(sample_root, "#Rigging plan **today")
    assert [a.subject for a in Model(conn).today_items()] == ["T000001", "T000002", RIGGING]  # a new item at the bottom (decision 645)


def test_saving_with_agenda_tom_puts_it_on_both(sample_root):
    conn = sample_root[0]
    r = save(sample_root, "Crane plan.\n- @Mike book the crane **agenda, Tom **today")
    crane = Model(conn).captures[r.items[0]].created_task
    assert (crane, "") in today(conn) and (crane, "") in [(a.subject, a.note) for a in Model(conn).open_items_for(TOM)]
    assert r.made.get("agenda") == 2
