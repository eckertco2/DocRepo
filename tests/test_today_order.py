"""Today in the owner's order (release 5.148, the design workspace's ``docs/mods/today-order-plan.md``, decisions 643 to 648),
without Qt: one list, a place for each open item once the first move is made, new items and Back on Today at the bottom,
Done leaving the rest as they were, Move to top and bottom, up and down, and an upgraded v28 data root."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from docrepo import agenda, db, edits, views
from docrepo.config import Settings
from docrepo.model import TODAY, Model
from docrepo.safe_fs import SafeFS

from test_migrations import unzip_root

AT = datetime(2026, 10, 8, 15, 20)
SETTINGS = Settings(me="P001")


def ids(conn: sqlite3.Connection) -> list[int]:
    return [a.id for a in Model(conn).today_items()]


def places(conn: sqlite3.Connection) -> dict[int, int | None]:
    return {r["id"]: r["pos"] for r in conn.execute("SELECT id, pos FROM agenda_items WHERE target = ? AND closed IS NULL", (TODAY,))}


def add(conn, subject=None, note="", added="2026-10-08 09:00:00") -> int:
    return agenda.add_item(conn, subject=subject, target=TODAY, note=note, added=added, added_by="Browse tool")


@pytest.fixture
def today(sample_conn):
    """Three made-up items: one carried over from Monday, then a note and a task added this morning."""
    conn = sample_conn
    carried = add(conn, "T000019", added="2026-10-05 08:05:00")
    note = add(conn, note="Sign the overtime sheets", added="2026-10-08 07:50:00")
    task = add(conn, "T000012", added="2026-10-08 08:30:00")
    return conn, carried, note, task


def test_until_the_first_move_carried_items_come_first_then_todays(today):
    conn, carried, note, task = today
    assert ids(conn) == [carried, note, task] and set(places(conn).values()) == {None}
    assert views.today_groups(Model(conn), AT.date()) == [("Today", Model(conn).today_items())]  # one list (decision 644)
    assert views.today_groups(Model(db.connect_memory()), AT.date()) == []


def test_the_first_drag_places_every_open_item(today):
    conn, carried, note, task = today
    agenda.close_item(conn, add(conn, "T000016"), how="Done", closed="2026-10-08 10:00:00", closed_by="Today")
    agenda.move_beside(conn, task, carried, "before")  # added this morning, above Monday's (decision 644)
    assert ids(conn) == [task, carried, note]
    assert places(conn) == {task: 1, carried: 2, note: 3}  # every open item has its place, the closed one none
    assert conn.execute("SELECT pos FROM agenda_items WHERE subject = 'T000016'").fetchone()[0] is None


def test_a_drag_lands_before_or_after_another_item(today):
    conn, carried, note, task = today
    assert agenda.move_beside(conn, carried, task, "after") == [note, task, carried]
    assert agenda.move_beside(conn, carried, note, "before") == [carried, note, task]
    assert agenda.move_beside(conn, note, note, "after") == [carried, note, task]  # on itself: nothing moves
    assert agenda.can_move_beside(conn, carried, task) and not agenda.can_move_beside(conn, carried, carried)


def test_a_drag_only_moves_beside_an_open_item_of_the_same_list(today):
    conn, carried, note, task = today
    meeting = next(a.id for a in Model(conn).open_items_for("T000010"))
    with pytest.raises(agenda.AgendaError, match="beside another open item"):
        agenda.move_beside(conn, carried, meeting, "before")
    with pytest.raises(agenda.AgendaError, match="before or after"):
        agenda.move_beside(conn, carried, task, "in")
    agenda.close_item(conn, task, how="Done", closed="2026-10-08 10:00:00", closed_by="Today")
    with pytest.raises(agenda.AgendaError, match="beside another open item"):
        agenda.move_beside(conn, carried, task, "after")
    assert not agenda.can_move_beside(conn, carried, task) and not agenda.can_move_beside(conn, carried, meeting)
    assert ids(conn) == [carried, note] and set(places(conn).values()) == {None}  # refused moves place nothing


def test_place_items_needs_the_whole_list_as_it_is(today):
    conn, carried, note, task = today
    with pytest.raises(agenda.AgendaError, match="changed since it was shown"):
        agenda.place_items(conn, [task, carried])
    with pytest.raises(agenda.AgendaError, match="changed since it was shown"):
        agenda.place_items(conn, [task, carried, note, note])
    agenda.place_items(conn, [note, task, carried])
    assert ids(conn) == [note, task, carried]


def test_a_new_item_goes_at_the_bottom(today):
    conn, carried, note, task = today
    first = add(conn, "T000002", added="2026-10-08 11:00:00")
    assert ids(conn)[-1] == first and places(conn)[first] is None  # before any move: last, as the newest
    agenda.move_item(conn, first, 0)
    later = add(conn, "T000001", added="2026-10-08 12:00:00")
    assert ids(conn) == [first, carried, note, task, later] and places(conn)[later] == 5  # after the last (decision 645)


def test_a_reminder_and_the_box_add_at_the_bottom_too(sample_root):
    conn, root, fs = sample_root
    edits.add_to_today(conn, root, fs, "T000012", "", AT)
    edits.add_to_today(conn, root, fs, None, "Call the crane company back", AT)
    first, second = ids(conn)
    edits.move_today_item(conn, root, fs, second, AT, to="top")
    edits.reminders_to_today(conn, root, fs, SETTINGS, AT)  # the sample's two reminders have come (decision 415)
    m = Model(conn)
    assert [a.id for a in m.today_items()][:2] == [second, first]
    assert [a.subject for a in m.today_items()][2:] == ["T000016", "T000018"]


def test_done_leaves_and_the_rest_keep_their_order(today):
    conn, carried, note, task = today
    agenda.move_item(conn, task, 0)
    agenda.close_item(conn, carried, how="Done", closed="2026-10-08 10:00:00", closed_by="Today")
    assert ids(conn) == [task, note]
    agenda.close_item(conn, task, how="Removed", closed="2026-10-08 10:05:00", closed_by="Today")
    assert ids(conn) == [note]


def test_undo_puts_an_item_back_in_its_place(sample_root):
    conn, root, fs = sample_root
    for t in ("T000012", "T000002", "T000001"):
        edits.add_to_today(conn, root, fs, t, "", AT)
    a, b, c = ids(conn)
    edits.move_today_item(conn, root, fs, c, AT, to="top")
    edits.close_today_item(conn, root, fs, a, "Done", AT)
    assert ids(conn) == [c, b]
    edits.reopen_agenda_item(conn, root, fs, a, AT)  # Undo, for ten seconds (release 5.91): back as it was
    assert ids(conn) == [c, a, b]


def test_back_on_today_goes_at_the_bottom(sample_root):
    conn, root, fs = sample_root
    for t in ("T000012", "T000002", "T000001"):
        edits.add_to_today(conn, root, fs, t, "", AT)
    a, b, c = ids(conn)
    edits.close_today_item(conn, root, fs, a, "Done", AT)
    out = edits.back_on_today(conn, root, fs, a, AT)  # Done today's row (decision 420), never moved yet
    assert out.message == "Back on Today, at the bottom." and ids(conn) == [b, c, a]
    assert places(conn) == {b: 1, c: 2, a: 3}  # to put it last, the list took its places
    edits.close_today_item(conn, root, fs, b, "Done", AT)
    edits.back_on_today(conn, root, fs, b, AT)
    assert ids(conn) == [c, a, b]


def test_move_to_top_and_bottom_up_and_down(sample_root):
    conn, root, fs = sample_root
    for t in ("T000012", "T000002", "T000001"):
        edits.add_to_today(conn, root, fs, t, "", AT)
    a, b, c = ids(conn)
    assert edits.move_today_item(conn, root, fs, c, AT, to="top").message == f"{Model(conn).task('T000001').title}: moved to the top."
    assert ids(conn) == [c, a, b]
    assert edits.move_today_item(conn, root, fs, c, AT, to="bottom").message.endswith(": moved to the bottom.")
    assert ids(conn) == [a, b, c]
    edits.move_today_item(conn, root, fs, b, AT, to="up")
    assert ids(conn) == [b, a, c]
    edits.move_today_item(conn, root, fs, b, AT, to="down")
    assert ids(conn) == [a, b, c]
    assert edits.move_today_item(conn, root, fs, a, AT, to="up").message == ""  # at the top already: nothing to do
    assert edits.move_today_item(conn, root, fs, c, AT, to="down").message == "" and ids(conn) == [a, b, c]
    assert edits.move_today_item(conn, root, fs, b, AT, beside=(a, "after")).message == ""  # dropped where it was
    with pytest.raises(edits.EditError, match="top, the bottom, up or down"):
        edits.move_today_item(conn, root, fs, a, AT, to="sideways")


def test_a_note_moves_too_and_keeps_its_place_as_a_task(sample_root):
    conn, root, fs = sample_root
    from docrepo.save import note_to_task

    edits.add_to_today(conn, root, fs, "T000012", "", AT)
    edits.add_to_today(conn, root, fs, None, "Call the crane company back", AT)
    task, note = ids(conn)
    assert edits.move_today_item(conn, root, fs, note, AT, to="top").message == "The note: moved to the top."
    note_to_task(conn, root, fs, SETTINGS, note, AT)  # Make it a task: the same item, in its place
    assert ids(conn) == [note, task] and Model(conn).today_items()[0].subject is not None


def test_a_move_goes_in_no_status_log_and_contents_follows_the_order(sample_root):
    conn, root, fs = sample_root
    edits.add_to_today(conn, root, fs, "T000012", "", AT)
    edits.add_to_today(conn, root, fs, None, "Call the crane company back", AT)
    task, note = ids(conn)
    logged = conn.execute("SELECT count(*) FROM status_log").fetchone()[0]
    before = Model(conn).status_log_of("T000012")
    edits.move_today_item(conn, root, fs, task, AT, beside=(note, "after"))
    assert conn.execute("SELECT count(*) FROM status_log").fetchone()[0] == logged and Model(conn).status_log_of("T000012") == before
    contents = (root / "Contents.md").read_text(encoding="utf-8")
    assert "### Today\n\n- Call the crane company back\n- [Rigging plan](Tasks/T000012/Task.md)\n" in contents  # decision 647


def test_a_move_of_an_item_gone_from_today_says_so(sample_root):
    conn, root, fs = sample_root
    edits.add_to_today(conn, root, fs, "T000012", "", AT)
    (item,) = ids(conn)
    edits.close_today_item(conn, root, fs, item, "Done", AT)
    with pytest.raises(edits.EditError, match="isn't on Today any more"):
        edits.move_today_item(conn, root, fs, item, AT, to="top")
    with pytest.raises(agenda.AgendaError, match="closed"):
        agenda.move_item(conn, item, 0)


def test_other_agendas_keep_no_places(today):
    conn, carried, note, task = today
    agenda.move_item(conn, task, 0)
    item = agenda.add_item(conn, subject="T000002", target="T000010", note="", added="2026-10-08 12:00:00", added_by="Agenda view")
    assert conn.execute("SELECT pos FROM agenda_items WHERE id = ?", (item,)).fetchone()[0] is None
    assert [a.id for a in Model(conn).open_items_for("T000010")][-1] == item


def test_an_upgraded_v28_root_keeps_today_as_it_was(tmp_path):
    """The v28 fixture, made by 5.142's own code, has Today's items from Wednesday and Thursday: no places after the upgrade,
    the same order as before, and the first move places them all."""
    root = unzip_root("v28", tmp_path)
    conn = db.connect(SafeFS([root]), root)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        m = Model(conn)
        items = m.today_items()
        assert [(a.subject, a.note) for a in items] == [("T000012", ""), (None, "Sign the overtime sheets"), ("T000008", "")]
        assert all(a.pos is None for a in m.agenda)
        carried, note, task = (a.id for a in items)
        agenda.move_beside(conn, task, carried, "before")
        assert ids(conn) == [task, carried, note] and places(conn) == {task: 1, carried: 2, note: 3}
    finally:
        conn.close()
