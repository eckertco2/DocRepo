"""The ** syntax, discoverable and loud when it fails (release 5.92, the review of 2026-11-06, F6): the ** list, the Unread
line card, the new person's card, the examples, and the README's table made from ``items.OPERATORS``."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from docrepo import items, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.save import CaptureDraft, item_names, save_capture

TODAY = date(2026, 10, 8)
README = Path(__file__).resolve().parent.parent / "README.md"


@pytest.fixture
def names(sample_conn):
    return item_names(Model(sample_conn), Settings(me="P001", reference_fields=["Change record"]))


def read(text: str, names: items.Names, own: str | None = "T000008", **kw) -> items.Reading:
    return items.read(text, names, TODAY, home=True, own=own, **kw)


# ---- the ** list ----
def test_typing_two_stars_opens_the_list(names):
    assert items.typing("**") == items.Typing("**", "", 0)
    assert items.typing("Crane note **du") == items.Typing("**", "du", 11)
    assert items.typing("x **due,") is None  # the comma's typed: the list goes
    assert items.typing("**due, 5 Nov") is None


def test_the_list_has_every_name_kinds_first(names):
    every = items.star_options("", names)
    kinds = [op for op in items.OPERATORS if op.item and not op.gone]
    fields = [op for op in items.OPERATORS if not op.item and not op.gone]
    assert len(every) == len(kinds) + len(fields) + 1  # and the reference field from Settings
    assert [o.label for o in every[:len(kinds)]] == [f"**{items.star_name(op)}," for op in kinds]
    assert every[-1].label == "**change record," and every[-1].sub == "Field: **change record, 4471"
    due = next(o for o in every if o.label == "**due,")
    assert due.value == "due," and due.sub == "Field: **due, 5 Nov"  # choosing it puts in "**due, "
    assert not any("date," == o.value for o in every)  # a name that's gone isn't offered


def test_what_is_typed_narrows_it(names):
    assert [o.label for o in items.star_options("du", names)] == ["**due,", "**duration,"]
    assert [o.label for o in items.star_options("done", names)] == ["**closed,"]  # by any of its names


def test_every_example_reads_with_no_problem(sample_conn):
    s = Settings(me="P001")
    mike = next(p.id for p in Model(sample_conn).people.values() if p.name == "Mike Ortiz")  # involvement is a share of someone on it
    empty = tasks.create_task(sample_conn, s, title="Empty task", at=datetime(2026, 10, 8, 9, 0), created_by="test", assignees=[mike])
    names = item_names(Model(sample_conn), s)
    for name, example in items.STAR_EXAMPLES.items():
        # A task always has a title (and a filled field stays, decision 200), so these two fill a new task's: under its first line.
        r = (items.read(f"Book the crane\n{example}", names, TODAY, home=True, new_task=True) if name in ("title", "description")
             else read(example, names, own=empty))
        assert r.items and not r.unread, name
        assert [it.problem for it in r.items] == [""] * len(r.items), (name, [it.problem for it in r.items])
    assert set(items.STAR_EXAMPLES) == {items.star_name(op) for op in items.OPERATORS if not op.gone}


# ---- the Unread line card ----
@pytest.mark.parametrize("line", ["**Tom to book the crane", "Then **check the slings", "(**ask about the hire rate"])
def test_a_star_line_that_reads_as_nothing_is_unread(names, line):
    r = read(line, names)
    assert r.unread == [(0, line)] and not r.items


@pytest.mark.parametrize("line", ["Some **bold** words", "**closed, The seals are fitted", "**due, 5 Nov", "a*b**c", "** nothing after"])
def test_a_star_line_that_reads_or_is_bold_isnt(names, line):
    assert read(line, names).unread == []


def test_a_name_that_isnt_a_field_has_its_own_card_still(names):
    r = read("**colour, red", names)
    assert r.unread == [] and r.items[0].problem == "No field called colour"


# ---- a new person from @ ----
def test_a_new_name_is_a_ticked_card(names):
    r = read("@Zed to book the crane", names)
    assert r.new_people == [("Zed", True)] and [x.name for x in r.items[0].assignees] == ["Zed"]
    off = read("@Zed to book the crane", names, overrides={items.PEOPLE_KEY: {"zed": False}})
    assert off.new_people == [("Zed", False)] and off.items[0].assignees == [] and off.items[0].kind == "task"
    assert read("@Tom to book the crane", names).new_people == []  # Tom is on the people list


def test_unticked_saving_makes_no_person(sample_root):
    conn, root, fs = sample_root
    s = Settings(me="P001")
    people = conn.execute("SELECT count(*) FROM people").fetchone()[0]
    r = save_capture(conn, root, fs, s, CaptureDraft(content="Crane plan.\n@Zed to book the crane", task="T000008", types={"note"}, files=[],
                                                      item_overrides={items.PEOPLE_KEY: {"zed": False}}), datetime(2026, 10, 8, 9, 0))
    assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == people and r.added_people == []
    made = Model(conn).captures[r.items[0]].created_task
    assert Model(conn).task(made).assignees == []  # a task for no one yet
    r2 = save_capture(conn, root, fs, s, CaptureDraft(content="Crane plan.\n@Zed to book the crane", task="T000008", types={"note"}, files=[]),
                      datetime(2026, 10, 8, 9, 5))
    assert r2.added_people == ["Zed"]  # ticked, as it starts: added, as before


# ---- the README's table ----
def test_the_readme_table_is_the_operators():
    text = README.read_text(encoding="utf-8")
    assert items.readme_table() in text, "README.md's table of ** names isn't items.readme_table(): paste it in again"
    for old in ("**Closed.", "**Decision.", "**event."):  # the period form, which _star now refuses
        assert old not in text, old
