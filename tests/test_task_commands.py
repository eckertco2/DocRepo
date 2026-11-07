"""One Edit and one Add to (release 5.98, the consolidation plan's decision 392), and a quick task's Put under… (release
5.99, decision 394): what the menus hold, worked out once for the task page, the rows and Find files, as data."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import agenda, capacity, db, quick, tasks
from docrepo.config import Settings
from docrepo.model import TODAY, Model
from docrepo.save import add_quick_task
from docrepo.task_commands import add_to_entries, edit_entries, is_quick_task, put_under

AT = datetime(2026, 10, 8, 9, 30)
SETTINGS = Settings(me="P001")
DAY = date(2026, 10, 8)


@pytest.fixture
def env(data_root, fs):
    from docrepo.sample import load_sample

    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, DAY, SETTINGS)
    yield conn, data_root, fs
    conn.close()


def words(entries) -> list[str]:
    return ["—" if e.separator else e.label for e in entries]


#: The Edit menu's six, the same whatever the task (decision 392, the mock's, the owner's choice of 2026-11-07).
SIX = ["Edit task…", "—", "Move…", "Put under…", "Also put under…", "Remove from under…", "—", "Discard…"]


def by_label(entries, label: str):
    return next(e for e in entries if e.label == label)


def test_edit_for_a_subtask_is_the_six(sample_conn):
    m = Model(sample_conn)
    entries = edit_entries(m, "T000008")  # Installation, under Reactor impeller upgrade
    assert words(entries) == SIX
    assert entries[0].do == "edit" and entries[0].key == "E"
    assert [(e.do, e.args, e.enabled) for e in entries if not e.separator][1:] == [
        ("move", ("T000001",), True), ("", (), False), ("also", (), True), ("top", ("T000001",), True), ("discard", (), True)]
    assert by_label(entries, "Put under…").tip == "It's under Reactor impeller upgrade: Move… or Also put under… changes that."
    assert by_label(entries, "Remove from under…").tip == "From under Reactor impeller upgrade: it becomes a top-level task"


def test_edit_for_a_top_level_task_greys_what_needs_a_parent(sample_conn):
    entries = edit_entries(Model(sample_conn), "T000001")
    assert words(entries) == SIX
    assert by_label(entries, "Put under…").args == (None,) and by_label(entries, "Put under…").enabled
    for label, why in (("Move…", "A top-level task has no parent to move from: Put under… gives it one."),
                       ("Also put under…", "Put under… gives it its first parent."),
                       ("Remove from under…", "A top-level task isn't under anything.")):
        assert not by_label(entries, label).enabled and by_label(entries, label).tip == why


def test_edit_for_a_task_with_two_parents_lists_them(sample_conn):
    tasks.set_parents(sample_conn, "T000012", ["T000008", "T000009"], at=AT, via="Browse tool")
    m = Model(sample_conn)
    parents = m.parents_of("T000012")
    assert len(parents) == 2
    entries = edit_entries(m, "T000012")
    assert words(entries) == SIX
    names = [m.task(p).title for p in parents]
    assert [(e.label, e.do, e.args) for e in by_label(entries, "Move…").sub] == [(f"From under {n}…", "move", (p,)) for n, p in zip(names, parents)]
    assert [(e.label, e.do, e.args) for e in by_label(entries, "Remove from under…").sub] == [(f"From under {n}", "top", (p,)) for n, p in zip(names, parents)]


def test_add_to_has_today_the_meetings_and_anyone_else(sample_conn):
    m = Model(sample_conn)
    entries = add_to_entries(m, "T000008", DAY)
    assert entries[0].do == "today" and entries[0].key == "D" and entries[0].label.startswith("Today")
    meetings = [e for e in entries if e.do == "agenda"]
    assert meetings and all(e.args[0] in {t.id for t in m.open_meetings()} for e in meetings)
    assert entries[-1].label == "An agenda…" and entries[-1].do == "agenda_other" and entries[-1].key == "A"
    agenda.add_item(sample_conn, subject="T000008", target=TODAY, note="", added="2026-10-08 08:00:00", added_by="Browse tool")
    again = add_to_entries(Model(sample_conn), "T000008", DAY)
    assert again[0].do == "open_today" and again[0].label.startswith("On Today ✓")


def test_a_quick_task_puts_under_its_real_task(env):
    """Decision 394: a quick task leaves Quick tasks in one step, from the Edit menu or its row's own Put under…."""
    conn, root, fs = env
    r = add_quick_task(conn, root, fs, SETTINGS, "Call the vendor about seals", AT)
    m = Model(conn)
    q = quick.parent_id(conn)
    assert is_quick_task(m, r.created_task) and not is_quick_task(m, "T000008")
    entries = edit_entries(m, r.created_task)
    assert words(entries) == SIX
    assert not by_label(entries, "Move…").enabled and by_label(entries, "Move…").tip.startswith("A quick task has no real parent")
    assert not by_label(entries, "Also put under…").enabled
    assert (by_label(entries, "Remove from under…").do, by_label(entries, "Remove from under…").args) == ("top", (q,))
    put = put_under(m, r.created_task)
    assert put is not None and (put.label, put.do, put.args) == ("Put under…", "move", (q,)) and put == by_label(entries, "Put under…")
    assert put_under(m, "T000008") is None
