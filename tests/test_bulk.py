"""Changing several tasks at once: Edit selected (mods log round 1, M0009) and a label's matching tasks (M0014)."""
from __future__ import annotations

from datetime import datetime

from docrepo import bulk, edits, people
from docrepo.config import Settings
from docrepo.model import Model

AT = datetime(2026, 10, 8, 15, 20)
SETTINGS = Settings(me="P001")
VIA = "Browse tool"


def logged(conn, task_id: str) -> list[tuple[str, str | None, str | None]]:
    return [(e.field, e.from_value, e.to_value) for e in Model(conn).status if e.task == task_id and e.at == "2026-10-08 15:20:00"]


def test_the_preview_changes_nothing_and_apply_does_what_it_showed(sample_conn):
    conn = sample_conn
    edit = bulk.BulkEdit(add_labels=["Safety", "Lifting"], fields={"state": "In progress", "due": "2026-10-23"}, assignees=("add", ["P003"]))
    before = conn.execute("SELECT count(*) FROM status_log").fetchone()[0]
    shown = bulk.preview(conn, SETTINGS, ["T000012", "T000016"], edit, AT, VIA)
    assert conn.execute("SELECT count(*) FROM status_log").fetchone()[0] == before
    assert not any(lb.name == "Lifting" for lb in Model(conn).labels)  # the new label was rolled back too
    assert [o.task for o in shown] == ["T000012", "T000016"] and not any(o.problem for o in shown)
    assert [c.field for c in shown[0].changes] == ["Due", "Assignees", "Labels"]  # T000012 is already In progress
    assert [c.field for c in shown[1].changes] == ["State", "Due", "Assignees", "Labels"]
    assert bulk.summary(shown) == "2 tasks change, 7 changes in their status logs."
    done = bulk.run(conn, SETTINGS, ["T000012", "T000016"], edit, AT, VIA)
    assert [(o.task, o.changes) for o in done] == [(o.task, o.changes) for o in shown]
    m = Model(conn)
    assert m.task("T000012").assignees == ["P004", "P003"] and m.task("T000016").labels == ["Safety", "Lifting"]
    assert ("Assignees", "Mike Ortiz", "Mike Ortiz, Tom Becker") in logged(conn, "T000012")
    assert bulk.summary(done, done=True) == "Changed 2 tasks: 7 changes in their status logs."


def test_people_replaced_labels_removed_and_dates_cleared(sample_conn):
    conn = sample_conn
    edit = bulk.BulkEdit(remove_labels=["safety"], leads=("set", ["P002"]), fields={"deadline": None})
    out = bulk.run(conn, SETTINGS, ["T000019"], edit, AT, VIA)
    t = Model(conn).task("T000019")
    assert (t.labels, t.leads, t.deadline) == ([], ["P002"], None)
    assert logged(conn, "T000019") == [("Deadline", "2026-10-19", None), ("Lead", "Me", "Priya Shah"), ("Labels", "Safety", None)]
    assert bulk.summary(out) == "1 task changes, 3 changes in its status log."
    nothing = bulk.run(conn, SETTINGS, ["T000019"], bulk.BulkEdit(remove_labels=["Line 1"]), AT, VIA)  # inherited, not its own
    assert nothing[0].changes == [] and bulk.summary(nothing, done=True) == "Nothing changed."


def test_moving_several_tasks_skips_one_that_would_go_under_itself(sample_conn):
    conn = sample_conn
    out = bulk.run(conn, SETTINGS, ["T000012", "T000008", "T000016"], bulk.BulkEdit(parent="T000012"), AT, VIA)
    assert [o.problem for o in out] == ["That would put the task under itself.", "That would put the task under itself.", None]
    m = Model(conn)
    assert m.parents_of("T000016") == ["T000012"] and m.parents_of("T000008") == ["T000001"]
    assert logged(conn, "T000016") == [("Parents", None, "Rigging plan")]
    assert bulk.summary(out, done=True) == "Changed 1 task: 1 change in its status log. 2 were left as they were."
    also = bulk.run(conn, SETTINGS, ["T000015"], bulk.BulkEdit(parent="T000009", parent_how="also"), AT, VIA)
    assert Model(conn).parents_of("T000015") == ["T000003", "T000008", "T000009"] and len(also[0].changes) == 1
    moved = bulk.run(conn, SETTINGS, ["T000015"], bulk.BulkEdit(parent="T000009"), AT, VIA)
    assert Model(conn).parents_of("T000015") == ["T000009"]
    assert moved[0].changes[0].from_value == "Q4 cost reduction; Installation; Vendor drawing package"


def test_bulk_edit_writes_the_pages(sample_root):
    conn, root, fs = sample_root
    out = edits.bulk_edit(conn, root, fs, SETTINGS, ["T000016", "T000017"], bulk.BulkEdit(fields={"reminder": "2026-10-12"}), AT)
    assert out.message == "Changed 2 tasks: 2 changes in their status logs." and not out.problems
    assert "Reminder: None → 2026-10-12 · Browse tool" in (root / "Tasks" / "T000017" / "Task.md").read_text(encoding="utf-8")


def test_a_labels_matching_tasks(sample_conn):
    conn = sample_conn
    people.add_label(conn, "Lifting", ["crane", "rigging"])
    m = Model(conn)
    matches = {x.task: x for x in bulk.label_matches(m, "lifting")}
    rigging = matches["T000012"]
    assert [f.field for f in rigging.found] == ["Title", "Description"]
    title = rigging.found[0]
    assert title.text[title.start:title.end] == "Rigging"
    desc = rigging.found[1]
    assert desc.text[desc.start:desc.end].lower() in ("crane", "rigging") and desc.text.startswith(("Mike", "…"))
    assert all(m.task(x).state in ("Not started", "In progress") for x in matches)
    bulk.run(conn, SETTINGS, ["T000012"], bulk.BulkEdit(add_labels=["Lifting"]), AT, VIA)
    assert "T000012" not in {x.task for x in bulk.label_matches(Model(conn), "Lifting")}  # it has it now
    assert bulk.keyword_pattern("pump").search("Two pumps failed") and not bulk.keyword_pattern("pump").search("pumpkin")
    assert bulk.label_matches(m, "No such label") == []


def test_plant_event_ticked_or_unticked_for_several(sample_conn):
    """Release 5.9 (M0028): Edit selected ticks or unticks Plant event; a task that already has it isn't changed."""
    conn = sample_conn
    done = bulk.run(conn, SETTINGS, ["T000012", "T000016"], bulk.BulkEdit(fields={"plant_event": True}), AT, VIA)
    assert bulk.summary(done, done=True) == "Changed 2 tasks: 2 changes in their status logs."
    assert ("Plant event", "No", "Yes") in logged(conn, "T000012")
    again = bulk.preview(conn, SETTINGS, ["T000012"], bulk.BulkEdit(fields={"plant_event": True}), AT, VIA)
    assert not again[0].changes
    bulk.run(conn, SETTINGS, ["T000016"], bulk.BulkEdit(fields={"plant_event": False}), AT, VIA)
    assert [t.id for t in Model(conn).plant_events()] == ["T000012"]
