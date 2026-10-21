"""Discarding tasks and captures made by mistake (mods log round 1, M0021): hidden, never deleted, and brought back as they were."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import captures, edits, search, tasks, views
from docrepo.config import Settings
from docrepo.lists import LISTS, list_tasks
from docrepo.model import Model
from docrepo.ui.task_picker import recent_tasks

AT = datetime(2026, 10, 8, 15, 20)
TODAY = date(2026, 10, 8)
SETTINGS = Settings(me="P001")


def tree_ids(m: Model) -> set[str]:
    return {n.id for n in views.walk(views.task_tree(m, views.TreeFilter(parked=True, closed=True)))}


def test_a_discarded_task_is_hidden_and_comes_back_as_it_was(sample_root):
    conn, root, fs = sample_root
    tasks.update_task(conn, SETTINGS, "T000016", at=AT, via="Browse tool", assignee_hours=6, due="2026-10-16")
    calendar = conn.execute("SELECT count(*) FROM work_calendar WHERE task = 'T000016'").fetchone()[0]
    assert calendar
    mine = next(x for x in LISTS if x.id == "mine")
    assert "T000016" in {t.id for t in list_tasks(Model(conn), mine, TODAY, "P001")}
    out = edits.discard_task(conn, root, fs, SETTINGS, "T000016", "  Typed twice  ", AT)
    assert out.message == "Discarded Holiday coverage schedule. It's off 1 agenda. It's in the Discarded view, where Bring back restores it."
    m = Model(conn)
    t = m.task("T000016")
    assert (t.discarded, t.discard_reason, t.state) == ("2026-10-08 15:20:00", "Typed twice", "Not started")
    assert "T000016" not in tree_ids(m) and "T000016" not in {x.id for x in list_tasks(m, mine, TODAY, "P001")}
    assert [r.kind for r in search.search(conn, m, "holiday coverage")] == ["capture"]  # the capture that made it stays
    assert conn.execute("SELECT count(*) FROM work_calendar WHERE task = 'T000016'").fetchone()[0] == 0
    assert views.view_counts(m, TODAY, "P001")["discarded"] == 1
    assert [(r.kind, r.id, r.reason) for r in views.discarded_rows(m, TODAY)] == [("task", "T000016", "Typed twice")]
    last = [e for e in m.status if e.task == "T000016"][-1]
    assert (last.at, last.field, last.from_value, last.to_value, last.via) == ("2026-10-08 15:20:00", "Discarded", None, "Typed twice", "Browse tool")
    assert m.agendas_on("T000016") == []  # taken off the agenda it was on, as Removed
    assert "| Discarded | 2026-10-08: Typed twice |" in (root / "Tasks" / "T000016" / "Task.md").read_text(encoding="utf-8")
    from docrepo.stories import Stories

    assert Stories(m, TODAY, lambda _: "").field_sentence(last) == "Discarded: Typed twice."
    with pytest.raises(tasks.TaskError, match="already discarded"):
        tasks.set_discarded(conn, SETTINGS, "T000016", "again", at=AT, via="Browse tool")

    assert edits.bring_back_task(conn, root, fs, SETTINGS, "T000016", AT).message == "Brought back Holiday coverage schedule."
    m = Model(conn)
    assert m.task("T000016").discarded is None and "T000016" in tree_ids(m)
    assert conn.execute("SELECT count(*) FROM work_calendar WHERE task = 'T000016'").fetchone()[0] == calendar
    assert Stories(m, TODAY, lambda _: "").field_sentence([e for e in m.status if e.task == "T000016"][-1]) == "Brought back."


def test_what_stops_a_task_being_discarded(sample_root):
    conn, root, fs = sample_root
    with pytest.raises(edits.EditError, match="has subtasks"):
        edits.discard_task(conn, root, fs, SETTINGS, "T000008", "", AT)
    with pytest.raises(edits.EditError, match="agenda has open items"):
        edits.discard_task(conn, root, fs, SETTINGS, "T000010", "", AT)
    on = [a.target for a in Model(conn).agendas_on("T000015")]
    assert on
    out = edits.discard_task(conn, root, fs, SETTINGS, "T000015", "", AT)
    assert "It's off 1 agenda." in out.message
    m = Model(conn)
    assert not m.agendas_on("T000015") and m.task("T000015").discard_reason == edits.DISCARD_REASON
    child = tasks.create_task(conn, SETTINGS, title="A subtask made by mistake", at=AT, created_by="Browse tool", parents=["T000016"])
    edits.discard_task(conn, root, fs, SETTINGS, child, "", AT)
    edits.discard_task(conn, root, fs, SETTINGS, "T000016", "", AT)  # its only subtask is discarded already
    with pytest.raises(edits.EditError, match="Bring Holiday coverage schedule back first"):
        edits.bring_back_task(conn, root, fs, SETTINGS, child, AT)


def test_a_discarded_capture_leaves_the_logs_but_keeps_its_folder(sample_root):
    conn, root, fs = sample_root
    m = Model(conn)
    c = m.captures["C000013"]
    task_id = m.capture_tasks(c)[0]
    md = captures.capture_md_path(root, c)
    before = md.read_text(encoding="utf-8")
    assert c in m.notes_of(task_id) and search.search(conn, m, "crane booking")
    out = edits.discard_capture(conn, root, fs, "C000013", "Saved twice", AT)
    assert out.message.startswith("Discarded C000013. Its folder stays")
    m = Model(conn)
    assert m.captures["C000013"] not in m.notes_of(task_id) and not search.search(conn, m, "crane booking")
    assert not any(e.capture and e.capture.id == "C000013" for e in m.raw_log_of(task_id))
    assert md.read_text(encoding="utf-8") == before  # capture.md isn't touched
    assert [(r.kind, r.id) for r in views.discarded_rows(m, TODAY)] == [("capture", "C000013")]
    edits.discard_capture(conn, root, fs, "C000022", "", AT)  # an unfiled one leaves the Unfiled view
    m = Model(conn)
    assert "C000022" not in {x.id for x in m.unfiled_captures()} and not m.is_unfiled(m.captures["C000022"])
    assert all(c.id not in ("C000013", "C000022") for c in m.live_captures())
    assert task_id not in recent_tasks(m) or any(task_id in m.capture_tasks(x) for x in m.live_captures())
    with pytest.raises(edits.EditError, match="already discarded"):
        edits.discard_capture(conn, root, fs, "C000013", "", AT)
    assert edits.bring_back_capture(conn, root, fs, "C000013", AT).message == "Brought back C000013."
    m = Model(conn)
    assert m.captures["C000013"] in m.notes_of(task_id) and m.captures["C000013"].discard_reason is None
