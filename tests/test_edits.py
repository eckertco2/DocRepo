"""Changes made in the browse tool: filing and fixing captures, Make it a task, reminders, agenda items and task edits."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from docrepo import captures, edits, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.pages import Pages
from docrepo.save import CaptureDraft, NewTaskFields, save_capture

AT = datetime(2026, 10, 8, 15, 20)
SETTINGS = Settings(me="P001")


def front(text: str) -> dict:
    head = text.split("\n---\n", 1)[0].removeprefix("---\n")
    return {k: json.loads(v) for k, v in (line.split(": ", 1) for line in head.split("\n"))}


def capture_md(root, conn, capture_id: str) -> str:
    return captures.capture_md_path(root, Model(conn).captures[capture_id]).read_text(encoding="utf-8")


def test_reading_content_back_from_capture_md(sample_root):
    conn, root, _ = sample_root
    m = Model(conn)
    assert captures.read_content(root, m.captures["C000001"]).startswith("Kickoff with Tom and Priya.")
    with_summary = next(c for c in m.captures.values() if c.summary)
    text = captures.read_content(root, with_summary)
    assert "## Summary" not in text and text == text.strip()
    assert captures.split_capture_md('---\nid: "C1"\n---\n\nLine one\n\nLine two\n\n## Summary\n\nShort.\n', "Short.") == "Line one\n\nLine two"


def test_filing_an_unfiled_capture(sample_root):
    conn, root, fs = sample_root
    before = captures.read_content(root, Model(conn).captures["C000022"])
    out = edits.file_capture(conn, root, fs, "C000022", "T000018", AT)
    m = Model(conn)
    c = m.captures["C000022"]
    assert out.message == "Filed C000022 to Update area 3 guard drawings." and not out.problems
    assert (c.filed_to, c.filed) == ("T000018", "2026-10-08 15:20:00") and not m.is_unfiled(c)
    text = capture_md(root, conn, "C000022")
    assert front(text)["task"] == "T000018" and front(text)["filed"] == "2026-10-08T15:20:00"
    assert captures.read_content(root, c) == before  # the content text is kept as it was
    assert "C000022" in (root / "Tasks" / "T000018" / "Task.md").read_text(encoding="utf-8")
    with pytest.raises(edits.EditError, match="already filed"):
        edits.file_capture(conn, root, fs, "C000022", "T000017", AT)


def test_filing_makes_the_saved_copies_that_waited_for_it(sample_root, tmp_path):
    conn, root, fs = sample_root
    original = tmp_path / "Pump curve.pdf"
    original.write_bytes(b"%PDF-1.4 a made-up pump curve")
    from docrepo.save import FileRow

    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Pump curve from the vendor.", files=[
        FileRow("Pump curve.pdf", str(original), "The vendor's pump curve", save_a_copy=True)]), AT)
    assert Model(conn).is_unfiled(Model(conn).captures[r.capture_id])
    out = edits.file_capture(conn, root, fs, r.capture_id, "T000008", AT)
    assert "1 saved copy made" in out.message
    copy = root / "Tasks" / "T000008" / "Files" / "2026-10-08 Pump curve.pdf"
    assert copy.read_bytes() == original.read_bytes()
    assert [f.name for f in Model(conn).copies if f.from_capture == r.capture_id] == ["2026-10-08 Pump curve.pdf"]


def test_fixing_a_capture_keeps_the_previous_version(sample_root):
    conn, root, fs = sample_root
    old_text = capture_md(root, conn, "C000017")
    out = edits.edit_capture(conn, root, fs, "C000017", "Vendor drawings came in late. The package is now due 23 Oct.", "", None, AT)
    assert out.message == "Saved C000017. The previous version is in its _old versions folder."
    kept = captures.capture_folder(root, "C000017", Model(conn).captures["C000017"].saved) / "_old versions" / "capture 2026-10-08 1520.md"
    assert kept.read_text(encoding="utf-8") == old_text
    c = Model(conn).captures["C000017"]
    assert c.edited == "2026-10-08 15:20:00" and c.title == "Vendor drawings came in late"
    text = capture_md(root, conn, "C000017")
    assert front(text)["edited"] == "2026-10-08T15:20:00" and text.endswith("\n\nVendor drawings came in late. The package is now due 23 Oct.\n")
    again = edits.edit_capture(conn, root, fs, "C000017", "Second fix.", "A summary.", "General summary", AT)
    assert "Saved" in again.message and (kept.parent / "capture 2026-10-08 1520 (2).md").exists()
    c = Model(conn).captures["C000017"]
    assert (c.summary, c.summary_type) == ("A summary.", "General summary")
    assert capture_md(root, conn, "C000017").endswith("Second fix.\n\n## Summary\n\nA summary.\n")


def test_a_fix_needs_a_change_and_some_text(sample_root):
    conn, root, fs = sample_root
    content = captures.read_content(root, Model(conn).captures["C000017"])
    assert edits.edit_capture(conn, root, fs, "C000017", content, "", None, AT).message == "Nothing changed."
    with pytest.raises(edits.EditError, match="can't be empty"):
        edits.edit_capture(conn, root, fs, "C000017", "  ", "", None, AT)


def test_make_it_a_task_files_the_capture_to_the_new_task(sample_root):
    conn, root, fs = sample_root
    before = capture_md(root, conn, "C000022")
    count = len(Model(conn).captures)
    content = captures.read_content(root, Model(conn).captures["C000022"])
    draft = CaptureDraft(content=content + "\nEdited in the window.", task="T000002", types={"new_task"}, from_capture="C000022",
                         new_task=NewTaskFields(title="Guard drawings: lockout points"))
    r = save_capture(conn, root, fs, SETTINGS, draft, AT)
    m = Model(conn)
    new = m.task(r.created_task)
    assert r.capture_id is None and r.filed_capture == "C000022"
    assert r.message == f"Created {new.id}, Guard drawings: lockout points, under Verification walkthrough readiness, and filed C000022 to it."
    assert new.created_by == "C000022" and m.parents_of(new.id) == ["T000002"] and new.description.endswith("Edited in the window.")
    c = m.captures["C000022"]
    assert c.filed_to == new.id and len(m.captures) == count  # no new capture
    after = capture_md(root, conn, "C000022")
    assert front(after)["task"] == new.id and after.split("\n---\n", 1)[1] == before.split("\n---\n", 1)[1]  # its own text, unchanged
    from docrepo.captures import read_content
    from docrepo.stories import Stories

    story = Stories(m, AT.date(), lambda cid: read_content(root, m.captures[cid]) or "").story(new.id)
    assert story[0].how == "unfiled"


def test_clearing_a_reminder_goes_into_the_status_log(sample_root):
    conn, root, fs = sample_root
    out = edits.clear_reminder(conn, root, fs, SETTINGS, "T000018", AT)
    assert out.message == "Update area 3 guard drawings: reminder cleared. The change is in its status log."
    m = Model(conn)
    assert m.task("T000018").reminder is None
    assert [(e.field, e.to_value, e.via) for e in m.status_log_of("T000018")][-1] == ("Reminder", None, "Reminders list")


def test_closing_an_agenda_item(sample_root):
    conn, root, fs = sample_root
    item = next(a for a in Model(conn).open_items_for("T000010") if a.subject == "T000015")
    out = edits.close_agenda_item(conn, root, fs, item.id, "Removed", AT)
    assert out.message == "Q4 overtime budget: removed. It's off the Business team meeting agenda, and its status log says so."
    m = Model(conn)
    assert item.id not in [a.id for a in m.open_items_for("T000010")]
    assert m.status_log_of("T000015")[-1].to_value == "Removed" and m.task("T000015").state == "Not started"


def test_renaming_a_task_and_its_description(sample_root):
    conn, root, fs = sample_root
    out = edits.change_task(conn, root, fs, SETTINGS, "T000012", AT, title="Rigging plan for the impeller lift", description="Line one.\nLine two.")
    assert out.message == "2 changes in the status log."
    m = Model(conn)
    assert (m.task("T000012").title, m.task("T000012").description) == ("Rigging plan for the impeller lift", "Line one.\nLine two.")
    page = (root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")
    assert "· Description: Mike to write the rigging plan for the impeller lift. Crane booked for 20 Oct. Due 14 Oct. → Line one. Line two. · Browse tool" in page
    with pytest.raises(tasks.TaskError):
        edits.change_task(conn, root, fs, SETTINGS, "T000012", AT, title="  ")


def test_labels_and_inheriting(sample_root):
    conn, root, fs = sample_root
    edits.change_task(conn, root, fs, SETTINGS, "T000012", AT, labels=["Safety"], inherit_labels=False)
    m = Model(conn)
    assert m.labels_of("T000012") == [("Safety", False)]
    assert [(e.field, e.to_value) for e in m.status_log_of("T000012")][-2:] == [("Labels", "Safety"), ("Inherit parent labels", "No")]


def test_moving_a_task_in_the_tree(sample_root):
    conn, root, fs = sample_root
    out = edits.move_task(conn, root, fs, "T000012", "T000008", "T000001", AT)
    assert out.message == "Rigging plan is now under Reactor impeller upgrade."
    m = Model(conn)
    assert m.parents_of("T000012") == ["T000001"]
    assert m.status_log_of("T000012")[-1].from_value == "Installation"
    edits.move_task(conn, root, fs, "T000012", None, "T000008", AT)  # also under
    assert Model(conn).parents_of("T000012") == ["T000001", "T000008"]
    edits.move_task(conn, root, fs, "T000012", "T000001", None, AT)  # take out from under one
    assert Model(conn).parents_of("T000012") == ["T000008"]
    with pytest.raises(tasks.TaskError, match="under itself"):
        edits.move_task(conn, root, fs, "T000008", "T000001", "T000012", AT)
    out = edits.move_task(conn, root, fs, "T000012", "T000008", None, AT)
    assert Model(conn).parents_of("T000012") == [] and "top-level task" in out.message


def test_task_md_keeps_a_long_value_on_one_line(sample_root):
    conn, root, fs = sample_root
    tasks.update_task(conn, SETTINGS, "T000012", at=AT, via="Browse tool", current_status="First line.\nSecond line.")
    page = Pages(Model(conn), AT.date(), AT).task_page(Model(conn).task("T000012"))
    assert "→ First line. Second line. · Browse tool" in page
