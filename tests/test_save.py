"""Saving captures: notes, new tasks, updates, unfiled captures, agendas, files and Outlook emails."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from docrepo import capacity, db
from docrepo.config import Settings
from docrepo.log_setup import setup_logging
from docrepo.model import Model
from docrepo.parse import Who
from docrepo.sample import load_sample
from docrepo.save import Attachment, CaptureDraft, EmailItem, FileRow, NewTaskFields, SaveError, copy_name, email_rows, save_capture

AT = datetime(2026, 10, 16, 9, 30)
SETTINGS = Settings(me="P001")


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def save(env, draft: CaptureDraft):
    conn, root, fs = env
    return save_capture(conn, root, fs, SETTINGS, draft, AT)


def capture_md(root: Path, capture_id: str) -> str:
    return (root / "Captures" / "2026" / "10" / capture_id / "capture.md").read_text(encoding="utf-8")


def test_a_note_on_a_task(env):
    r = save(env, CaptureDraft(content="Crane inspection passed. Certificate is on file.", task="T000008", types={"note"}))
    conn, root, _ = env
    assert r.capture_id == "C000026"
    assert r.message == "Saved C000026. Added to the raw text log of Installation."
    assert [e.capture.id for e in Model(conn).raw_log_of("T000008") if e.capture][-1] == "C000026"
    text = capture_md(root, "C000026")
    assert text.startswith('---\nid: "C000026"\nsaved: "2026-10-16T09:30:00"\nsource: "typed"\ntask: "T000008"\ncapture_types: ["note"]\n')
    assert text.endswith("---\n\nCrane inspection passed. Certificate is on file.\n")
    assert "C000026" in (root / "Tasks" / "T000008" / "Task.md").read_text(encoding="utf-8")


def test_a_new_subtask_with_new_people_and_labels(env):
    fields = NewTaskFields(title="Hydrotest the new seal", labels=["Safety", "Pressure"], leads=[Who("P003")],
                           assignees=[Who(name="Marcus")], due="2026-10-23", assignee_hours=6)
    r = save(env, CaptureDraft(content="Hydrotest to 1.5 times design pressure.", task="T000008", types={"new_task"}, new_task=fields))
    conn, root, _ = env
    model = Model(conn)
    new = model.task(r.created_task)
    assert (new.title, new.description, model.parents_of(new.id)) == ("Hydrotest the new seal", "Hydrotest to 1.5 times design pressure.", ["T000008"])
    assert new.created_by == r.capture_id and new.labels == ["Safety", "Pressure"]
    marcus = next(p for p in model.people.values() if p.name == "Marcus")
    assert new.assignees == [marcus.id] and marcus.added_note.startswith("Added on 2026-10-16 from C000026")
    assert next(lb for lb in model.labels if lb.name == "Pressure").keywords == ["Pressure"]
    assert r.message == f"Saved C000026. Created {new.id}, Hydrotest the new seal, under Installation. Added Marcus to people."
    assert conn.execute("SELECT count(*) FROM work_calendar WHERE task = ?", (new.id,)).fetchone()[0] == 6  # 16 to 23 Oct, workdays
    assert "created_task" in capture_md(root, "C000026")


def test_a_new_task_takes_its_title_from_the_content_text(env):
    content = "Remind Tyler tomorrow that he needs to book the alignment contractor. Urgent: hard deadline is the turnaround on Oct 19."
    r = save(env, CaptureDraft(content=content, types={"new_task"}))
    new = Model(env[0]).task(r.created_task)
    assert new.title == "Book the alignment contractor" and new.description == content
    assert "The title came from the content text." in r.message and "under" not in r.message


def test_an_update_logs_its_changes_under_the_capture(env):
    r = save(env, CaptureDraft(content="Vendor drawings came in late.", task="T000009", types={"update"},
                               update={"due": "2026-10-30", "current_status": "Drawings late."}))
    conn = env[0]
    log = [e for e in Model(conn).status_log_of("T000009") if e.via == r.capture_id]
    assert [(e.field, e.from_value, e.to_value) for e in log] == [("Current status", "Drawings came in late; review moved to 23 Oct.", "Drawings late."),
                                                                  ("Due", "2026-10-23", "2026-10-30")]
    assert r.message == "Saved C000026. 2 changes in the status log of Vendor drawing package."
    assert '"changes": ' not in capture_md(env[1], r.capture_id) and 'changes: [{"field":"Current status"' in capture_md(env[1], r.capture_id)


def test_a_change_with_no_text_keeps_no_capture(env):
    r = save(env, CaptureDraft(task="T000012", types={"update"}, update={"state": "Closed"}))
    assert r.capture_id is None and r.message == "1 change in the status log of Rigging plan."
    entry = Model(env[0]).status_log_of("T000012")[-1]
    assert (entry.field, entry.to_value, entry.via) == ("State", "Closed", "Capture window")


def test_nothing_to_save(env):
    with pytest.raises(SaveError, match="nothing to save"):
        save(env, CaptureDraft(task="T000012", types={"update"}, update={"state": "In progress"}))
    with pytest.raises(SaveError, match="nothing to save"):
        save(env, CaptureDraft(types={"note"}, content="  "))
    with pytest.raises(SaveError, match="Pick a task") as e:
        save(env, CaptureDraft(types={"update"}, content="Done."))
    assert e.value.focus == "task"
    with pytest.raises(SaveError, match="title or some content"):
        save(env, CaptureDraft(types={"new_task"}))


def test_an_unfiled_capture_and_a_note_on_an_agenda(env):
    r = save(env, CaptureDraft(content="Check the spare impeller stock.", types={"note"}))
    assert r.message == "Saved C000026. Kept as an unfiled capture, listed under Unfiled."
    r2 = save(env, CaptureDraft(content="Ask about the holiday rota.", types={"note"}, agenda=["T000010"]))
    model = Model(env[0])
    assert [c.id for c in model.unfiled_captures()][-1] == "C000026"
    item = model.agenda[-1]
    assert (item.subject, item.target, item.note, item.added_by) == (None, "T000010", "Ask about the holiday rota.", r2.capture_id)
    assert r2.message == "Saved C000027. On the agenda of Business team meeting."


def test_an_update_put_on_an_agenda(env):
    r = save(env, CaptureDraft(content="Discuss the crane booking.", task="T000012", types={"update"}, agenda=["T000010", "P003"]))
    items = [a for a in Model(env[0]).agenda if a.added_by == r.capture_id]
    assert [(a.subject, a.target) for a in items] == [("T000012", "T000010"), ("T000012", "P003")]
    assert r.message.endswith("On the agenda of Business team meeting and Tom Becker.")


def test_files_are_recorded_copied_and_their_text_saved(env, tmp_path):
    conn, root, _ = env
    original = tmp_path / "share" / "Pump curve.txt"
    original.parent.mkdir()
    original.write_text("Design point 38 kW", encoding="utf-8")
    row = FileRow("Pump curve.txt", str(original), "Pump curve at 62 rpm.", save_a_copy=True, extract=True)
    r = save(env, CaptureDraft(content="", task="T000008", types={"note"}, files=[row]))
    model = Model(conn)
    doc = model.documents["D000005"]
    assert (doc.original, doc.description, doc.text_status, doc.text_chars) == (str(original), "Pump curve at 62 rpm.", "ok", 18)
    assert (root / "Documents" / "D000005" / "extracted.txt").read_text(encoding="utf-8") == "Design point 38 kW"
    assert (root / "Tasks" / "T000008" / "Files" / "2026-10-16 Pump curve.txt").read_text(encoding="utf-8") == "Design point 38 kW"
    capture = model.captures[r.capture_id]
    assert (capture.source, capture.title, capture.documents[0].save_a_copy) == ("file_path", "Pump curve.txt", True)
    assert original.read_text(encoding="utf-8") == "Design point 38 kW"  # the original is only read
    # The same file again reuses its document, and the second copy gets its own name.
    save(env, CaptureDraft(task="T000008", types={"note"}, files=[FileRow("Pump curve.txt", str(original).upper(), "Rev B.", save_a_copy=True)]))
    assert "D000006" not in Model(conn).documents
    assert (root / "Tasks" / "T000008" / "Files" / "2026-10-16 Pump curve (2).txt").exists()


def test_each_file_needs_a_description(env, tmp_path):
    rows = [FileRow("a.txt", str(tmp_path / "a.txt"), "First"), FileRow("b.txt", str(tmp_path / "b.txt"), " ")]
    with pytest.raises(SaveError) as e:
        save(env, CaptureDraft(task="T000008", types={"note"}, files=rows))
    assert e.value.focus == "file:1"
    assert env[0].execute("SELECT count(*) FROM captures").fetchone()[0] == 24


def test_a_missing_file_still_saves_the_capture(env, tmp_path):
    r = save(env, CaptureDraft(task="T000008", types={"note"}, files=[FileRow("gone.pdf", str(tmp_path / "gone.pdf"), "Old report.")]))
    assert r.capture_id and any("gone.pdf couldn't be opened" in p for p in r.problems)
    assert Model(env[0]).documents["D000005"].text_status == "error"


def test_an_outlook_email_and_its_attachments(env):
    def write(data: bytes):
        return lambda path: Path(path).write_bytes(data)

    email = EmailItem(subject="Revised coupling guard delivery", sender="Norvane Pumps (vendor)", sent="2026-10-15 16:02", to="Me",
                      body="The guard now ships on 14 Oct.", attachments=[Attachment("Guard drawing rev C.txt", write(b"Mounting holes: four M12"))],
                      save_msg=write(b"MSG"))
    rows = email_rows(email)  # the email's own row, then a row for its attachment (email layer 0)
    assert [(r.name, r.email is email, r.part and r.part.kind) for r in rows] == [
        ("Revised coupling guard delivery", True, None), ("Guard drawing rev C.txt", False, "attachment")]
    rows[1].description = "Guard delivery news."
    r = save(env, CaptureDraft(task="T000008", types={"note"}, files=rows))
    conn, root, _ = env
    folder = root / "Captures" / "2026" / "10" / r.capture_id
    assert (folder / "email.msg").read_bytes() == b"MSG"
    assert (folder / "attachments" / "Guard drawing rev C.txt").exists()
    model = Model(conn)
    capture = model.captures[r.capture_id]
    assert (capture.source, capture.title, capture.attachments) == ("outlook_email", "Revised coupling guard delivery", ["Guard drawing rev C.txt"])
    assert capture.email_layer_0 == "1 attachment kept."
    doc = model.documents[capture.documents[0].document]
    assert (doc.capture, doc.original, doc.description, doc.text_status) == (r.capture_id, None, "Guard delivery news.", "ok")
    text = capture_md(root, r.capture_id)
    assert "From: Norvane Pumps (vendor)\nSent: 2026-10-15 16:02\nTo: Me\nSubject: Revised coupling guard delivery\n\nThe guard now ships on 14 Oct." in text
    assert '\nemail_layer_0: "1 attachment kept."\nsummary_type: null\n' in text


def test_an_email_with_no_attachments_is_still_saved_as_email_msg(env):
    email = EmailItem("Crane booked", "Priya Shah", "2026-10-15 16:02", "Me", "Booked for 20 Oct.", save_msg=lambda path: Path(path).write_bytes(b"MSG"))
    r = save(env, CaptureDraft(task="T000008", types={"note"}, files=email_rows(email)))
    assert (env[1] / "Captures" / "2026" / "10" / r.capture_id / "email.msg").read_bytes() == b"MSG"
    assert Model(env[0]).captures[r.capture_id].email_layer_0 == "Nothing kept."


def test_the_log_holds_ids_not_content(env):
    conn, root, fs = env
    setup_logging(fs, root)
    save(env, CaptureDraft(content="Secret pricing details for the turnaround.", task="T000008", types={"note"}))
    log_text = (root / "System" / "logs" / "docrepo.log").read_text(encoding="utf-8")
    assert "capture C000026 saved: raw text log of T000008" in log_text and "Secret pricing" not in log_text


def test_copy_names():
    assert copy_name("2026-10-16", "Pump curve.pdf", set()) == "2026-10-16 Pump curve.pdf"
    assert copy_name("2026-10-16", 'Bad: "name"?.pdf', set()) == "2026-10-16 Bad name.pdf"
    assert copy_name("2026-10-16", "a.pdf", {"2026-10-16 a.pdf"}) == "2026-10-16 a (2).pdf"
    long = copy_name("2026-10-16", "x" * 200 + ".docx", set())
    assert len(long) == 100 and long.endswith(".docx")
