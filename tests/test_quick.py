"""Quick tasks (mods log round 2, M0039, M0040): one-line tasks on Today, under the built-in Quick tasks until filed."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import agenda, capacity, db, edits, quick, timeline
from docrepo.config import Settings
from docrepo.model import TODAY, Model
from docrepo.save import CaptureDraft, NewTaskFields, SaveError, add_quick_task, note_to_task, save_capture

AT = datetime(2026, 10, 8, 9, 30)  # a Thursday
SETTINGS = Settings(me="P001")


@pytest.fixture
def env(data_root, fs):
    from docrepo.sample import load_sample

    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def test_a_quick_task_from_todays_box(env):
    conn, root, fs = env
    assert quick.parent_id(conn) is None  # made the first time it's needed
    r = add_quick_task(conn, root, fs, SETTINGS, "Call the vendor about seals by Fri", AT)
    m = Model(conn)
    t, parent = m.task(r.created_task), quick.parent_id(conn)
    assert (t.title, t.due, m.parents_of(t.id)) == ("Call the vendor about seals", "2026-10-09", [parent])
    assert (m.task(parent).title, m.task(parent).state, quick.is_parent(m.task(parent)), m.parents_of(parent)) == ("Quick tasks", "In progress", True, [])
    assert parent < t.id  # Quick tasks is made first
    assert [a.subject for a in m.today_items()] == [t.id]
    assert r.message == f"Saved {r.capture_id}. Created {t.id}, Call the vendor about seals, under Quick tasks. On Today."
    # The next one reuses it, and a name not on the people list isn't added from a one-liner.
    r2 = add_quick_task(conn, root, fs, SETTINGS, "Ask Tom and Zed about the coupling", AT)
    m = Model(conn)
    assert m.parents_of(r2.created_task) == [parent] and "Zed" not in {p.name for p in m.people.values()}
    with pytest.raises(SaveError):
        add_quick_task(conn, root, fs, SETTINGS, "  ", AT)


def test_a_new_task_on_today_with_no_task_picked_is_a_quick_task(env):
    conn, root, fs = env
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(types={"new_task"}, new_task=NewTaskFields(title="Order seal kits"), agenda=[TODAY]), AT)
    m = Model(conn)
    assert m.parents_of(r.created_task) == [quick.parent_id(conn)] and r.message.endswith("under Quick tasks. On Today.")
    # Without Today, or with a task picked, nothing changes.
    plain = save_capture(conn, root, fs, SETTINGS, CaptureDraft(types={"new_task"}, new_task=NewTaskFields(title="A new project")), AT)
    under = save_capture(conn, root, fs, SETTINGS, CaptureDraft(task="T000008", types={"new_task"}, new_task=NewTaskFields(title="Torque the bolts"),
                                                                agenda=[TODAY]), AT)
    m = Model(conn)
    assert (m.parents_of(plain.created_task), m.parents_of(under.created_task)) == ([], ["T000008"])


def test_make_it_a_task_and_editing_a_note_on_today(env):
    conn, root, fs = env
    item = agenda.add_item(conn, subject=None, target=TODAY, note="Call the crane company back", added="2026-10-06 08:20:00", added_by="Browse tool")
    edits.edit_today_note(conn, root, fs, item, "Call the crane company back about the lift", AT)
    assert next(a for a in Model(conn).agenda if a.id == item).note == "Call the crane company back about the lift"
    r = note_to_task(conn, root, fs, SETTINGS, item, AT)
    m = Model(conn)
    a = next(x for x in m.agenda if x.id == item)
    assert (a.subject, a.note, a.added) == (r.created_task, "", "2026-10-06 08:20:00")  # in the note's place, still since Tuesday
    assert [x.subject for x in m.today_items()] == [r.created_task] and m.parents_of(r.created_task) == [quick.parent_id(conn)]
    assert m.task(r.created_task).title == "Call the crane company back about the lift"
    with pytest.raises(SaveError):
        note_to_task(conn, root, fs, SETTINGS, item, AT)  # it's a task's item now
    with pytest.raises(agenda.AgendaError):
        edits.edit_today_note(conn, root, fs, item, "Something else", AT)


def test_filing_a_quick_task_with_edit_task(env):
    conn, root, fs = env
    r = add_quick_task(conn, root, fs, SETTINGS, "Check the guard drawings", AT)
    out = edits.edit_task(conn, root, fs, SETTINGS, r.created_task, AT, parents=["T000008"])
    m = Model(conn)
    assert m.parents_of(r.created_task) == ["T000008"] and out.message == "1 change in the status log."
    entry = next(e for e in m.status_log_of(r.created_task) if e.field == "Parents")
    assert (entry.field, entry.from_value, entry.to_value, entry.via) == ("Parents", "Quick tasks", "Installation", "Browse tool")
    assert edits.edit_task(conn, root, fs, SETTINGS, r.created_task, AT, parents=["T000008"]).message == "Nothing changed."


def test_quick_tasks_itself_stays_off_the_timeline(env):
    conn, root, fs = env
    add_quick_task(conn, root, fs, SETTINGS, "Sort the spare parts", AT)
    m = Model(conn)
    tl = timeline.build(m, AT.date(), date(2026, 10, 5), 9)
    assert quick.parent_id(conn) not in tl.undated
