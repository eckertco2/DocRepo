"""Undo after a move from the Edit menu (release 5.118; the design workspace's ``docs/mods/undo-moves-plan.md``, decisions
435 to 439), without Qt: a task back under exactly the parents it had, in its old place, with the status log keeping both
changes, and the moves' own words."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import edits, quick, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.save import add_quick_task

AT = datetime(2026, 10, 8, 15, 20)
LATER = datetime(2026, 10, 8, 15, 21)
SETTINGS = Settings(me="P001")


def parents_log(conn, task_id: str) -> list[tuple[str | None, str | None, str]]:
    return [(e.from_value, e.to_value, e.via) for e in Model(conn).status_log_of(task_id) if getattr(e, "field", None) == "Parents"]


def test_undo_puts_a_moved_task_back_in_its_old_place(sample_root):
    """Installation is the second of Reactor impeller upgrade's four subtasks: Undo puts it back second, not last."""
    conn, root, fs = sample_root
    siblings = Model(conn).children_of("T000001")
    assert siblings.index("T000008") == 1 and len(siblings) == 4
    had = tasks.parent_links(conn, "T000008")
    out = edits.move_task(conn, root, fs, "T000008", "T000001", "T000002", AT)
    assert out.message == "Installation moved from under Reactor impeller upgrade to Verification walkthrough readiness."
    left = tasks.parent_links(conn, "T000008")
    assert Model(conn).children_of("T000001") == [s for s in siblings if s != "T000008"]

    back = edits.undo_move(conn, root, fs, "T000008", had, left, LATER)
    assert back.message == "Set back: Installation is under Reactor impeller upgrade again. The status log keeps both changes."
    m = Model(conn)
    assert m.parents_of("T000008") == ["T000001"] and m.children_of("T000001") == siblings
    assert "T000008" not in m.children_of("T000002")
    assert tasks.parent_links(conn, "T000008") == had  # the very link, with its own number
    assert parents_log(conn, "T000008") == [  # both changes, as Browse tool (decision 438)
        ("Reactor impeller upgrade", "Verification walkthrough readiness", "Browse tool"),
        ("Verification walkthrough readiness", "Reactor impeller upgrade", "Browse tool")]


def test_undo_keeps_the_order_of_several_parents_and_its_place_under_each(sample_root):
    """Q4 overtime budget is under Q4 cost reduction first, then Installation, the second of Installation's three."""
    conn, root, fs = sample_root
    m = Model(conn)
    assert m.parents_of("T000015") == ["T000003", "T000008"]
    under_installation = m.children_of("T000008")
    had = tasks.parent_links(conn, "T000015")
    edits.move_task(conn, root, fs, "T000015", "T000003", "T000002", AT)
    assert Model(conn).parents_of("T000015") == ["T000008", "T000002"]  # the order changed: the new link is the newest
    edits.undo_move(conn, root, fs, "T000015", had, tasks.parent_links(conn, "T000015"), LATER)
    m = Model(conn)
    assert m.parents_of("T000015") == ["T000003", "T000008"] and m.children_of("T000008") == under_installation


def test_undo_after_each_kind_of_move(sample_root):
    """Also put under…, Remove from under… one of several and from the only one, and a top-level task's Put under…: each
    set back to exactly what it was."""
    conn, root, fs = sample_root
    for task_id, old, new in (("T000012", None, "T000002"), ("T000015", "T000008", None), ("T000012", "T000008", None),
                              ("T000002", None, "T000001")):
        before = Model(conn)
        had, kids = tasks.parent_links(conn, task_id), {p: before.children_of(p) for p in ("T000001", "T000002", "T000003", "T000008")}
        edits.move_task(conn, root, fs, task_id, old, new, AT)
        out = edits.undo_move(conn, root, fs, task_id, had, tasks.parent_links(conn, task_id), LATER)
        after = Model(conn)
        assert tasks.parent_links(conn, task_id) == had and {p: after.children_of(p) for p in kids} == kids
        assert ("a top-level task again" in out.message) == (not had)


def test_a_quick_tasks_put_under_undone_puts_it_back_under_quick_tasks(sample_root):
    conn, root, fs = sample_root
    r = add_quick_task(conn, root, fs, SETTINGS, "Call the vendor about seals", AT)
    q = quick.parent_id(conn)
    had = tasks.parent_links(conn, r.created_task)
    out = edits.move_task(conn, root, fs, r.created_task, q, "T000008", AT)
    assert out.message == "Call the vendor about seals is under Installation now, out of Quick tasks."
    edits.undo_move(conn, root, fs, r.created_task, had, tasks.parent_links(conn, r.created_task), LATER)
    m = Model(conn)
    assert m.parents_of(r.created_task) == [q] and [a.subject for a in m.today_items()] == [r.created_task]


def test_a_number_taken_since_puts_the_task_last_and_keeps_its_parents_order(sample_root):
    """Only the newest link's number can be taken again (SQLite gives a new row the highest number plus one): then the task
    goes back last among that parent's subtasks, and its parents stay in their order (decision 436)."""
    conn, root, fs = sample_root
    newest, child = conn.execute("SELECT id, child FROM task_parents ORDER BY id DESC LIMIT 1").fetchone()
    had = tasks.parent_links(conn, child)
    parent = dict((n, p) for n, p in had)[newest]
    edits.move_task(conn, root, fs, child, parent, None, AT)
    left = tasks.parent_links(conn, child)
    tasks.add_parent(conn, "T000011", "T000002", at=AT, via="Browse tool")  # another task's link takes the number
    assert conn.execute("SELECT child FROM task_parents WHERE id = ?", (newest,)).fetchone()["child"] == "T000011"
    edits.undo_move(conn, root, fs, child, had, left, LATER)
    m = Model(conn)
    assert m.parents_of(child) == [p for _, p in had] and m.children_of(parent)[-1] == child
    assert m.parents_of("T000011") == ["T000001", "T000002"]  # the other task's link is left as it is


def test_undo_says_why_it_cant_and_changes_nothing(sample_root):
    conn, root, fs = sample_root
    had = tasks.parent_links(conn, "T000012")
    edits.move_task(conn, root, fs, "T000012", "T000008", "T000002", AT)
    left = tasks.parent_links(conn, "T000012")

    edits.move_task(conn, root, fs, "T000012", "T000002", "T000003", AT)  # moved again since: its parents aren't as Undo found them
    with pytest.raises(tasks.TaskError, match="changed since"):
        edits.undo_move(conn, root, fs, "T000012", had, left, LATER)
    assert Model(conn).parents_of("T000012") == ["T000003"]

    had = tasks.parent_links(conn, "T000008")
    edits.move_task(conn, root, fs, "T000008", "T000001", "T000002", AT)
    left = tasks.parent_links(conn, "T000008")
    edits.move_task(conn, root, fs, "T000001", None, "T000019", AT)  # its old parent is under one of its subtasks by now
    n = len(parents_log(conn, "T000008"))
    with pytest.raises(tasks.TaskError, match="can't go back under it"):
        edits.undo_move(conn, root, fs, "T000008", had, left, LATER)
    assert Model(conn).parents_of("T000008") == ["T000002"] and len(parents_log(conn, "T000008")) == n


def test_restoring_what_it_already_has_changes_nothing(sample_root):
    conn, _, _ = sample_root
    links, logged = tasks.parent_links(conn, "T000015"), parents_log(conn, "T000015")
    assert tasks.restore_parents(conn, "T000015", links, expect=links, at=AT, via="Browse tool") is None
    assert parents_log(conn, "T000015") == logged


def test_undo_writes_the_pages_again(sample_root):
    conn, root, fs = sample_root
    had = tasks.parent_links(conn, "T000012")
    edits.move_task(conn, root, fs, "T000012", "T000008", "T000002", AT)
    edits.undo_move(conn, root, fs, "T000012", had, tasks.parent_links(conn, "T000012"), LATER)
    contents = next(root.rglob("Contents.md")).read_text(encoding="utf-8")
    assert "Rigging plan" in contents
