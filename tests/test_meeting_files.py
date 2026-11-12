"""Files on meeting notes (release 5.135, decision 547): Save keeps a meeting's files, folders, links, emails and pasted
pictures on its notes capture, as it keeps a note's, and Save a copy puts a file in the meeting's own Files folder. Run
without Qt; the window's side is in ``test_meeting_window.py``."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from docrepo import capacity, captures, db, msg
from docrepo.config import Settings
from docrepo.layer0 import Part
from docrepo.model import Model
from docrepo.save import Attachment, CaptureDraft, FileRow, email_rows, save_capture
from msg_builder import FakeAttachment, FakeEmail, build

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
PNG = b"\x89PNG\r\n\x1a\n made-up picture"


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    from docrepo.sample import load_sample

    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def save(env, draft: CaptureDraft):
    conn, root, fs = env
    return save_capture(conn, root, fs, SETTINGS, draft, AT)


def a_file(tmp_path: Path, name: str = "Pump curve.txt") -> Path:
    path = tmp_path / name
    path.write_text("Design point 38 kW", encoding="utf-8")
    return path


def a_picture(fs, name: str = "Picture 2026-10-08 1410.png") -> FileRow:
    """A picture pasted in the notes, as the window hands it to Save."""
    attachment = Attachment(name, save=lambda target: fs.write_picture(target, PNG), size=len(PNG))
    return FileRow(name, None, part=Part("picture", name, attachment=attachment, size=len(PNG), pasted=True))


def folder_of(env, capture_id: str) -> Path:
    conn, root, _ = env
    c = Model(conn).captures[capture_id]
    return captures.capture_folder(root, c.id, c.saved)


def test_this_times_meeting_keeps_the_notes_files(env, tmp_path):
    """A regular meeting's notes: each kind of file goes on the notes capture, on this time's meeting, and a saved copy
    in that meeting's Files folder, not the regular meeting's."""
    conn, root, fs = env
    report = a_file(tmp_path)
    drawings = tmp_path / "Drawings"
    drawings.mkdir()
    email = msg.read(build(FakeEmail(body="The crane is booked for Tuesday.", attachments=[FakeAttachment("Lift plan.txt", b"Lift plan, made up")])))
    files = [FileRow("Pump curve.txt", str(report), save_a_copy=True), FileRow("Drawings", f"{drawings}\\"),
             FileRow("Crane booking", "https://example.com/crane-booking"), a_picture(fs), *email_rows(email)]
    r = save(env, CaptureDraft(content="Impeller is on site.", task="T000010", meeting=True, files=files))
    m = Model(conn)
    meeting, notes = m.task(r.meeting), m.captures[r.capture_id]
    assert meeting.title == "Business team meeting 8 Oct" and m.parents_of(meeting.id) == ["T000010"]
    assert (notes.task, notes.item, notes.meeting, notes.title) == (meeting.id, "notes", meeting.id, "Notes of Business team meeting 8 Oct")
    docs = {m.documents[d.document].name: (m.documents[d.document].description, d.save_a_copy) for d in notes.documents}
    assert docs == {
        "Pump curve.txt": ("Business team meeting 8 Oct – Attached document – Pump curve.txt", True),
        "Drawings": ("Business team meeting 8 Oct – Attached folder – Drawings", False),
        "Crane booking": ("Business team meeting 8 Oct – Attached link – Crane booking", False),
        "Picture 2026-10-08 1410.png": ("Business team meeting 8 Oct – Pasted picture – Picture 2026-10-08 1410.png", False),
        "Lift plan.txt": ("Business team meeting 8 Oct – Attached document – Lift plan.txt", False),
    }
    assert [e.subject for e in notes.emails] == ["Crane booking"]
    folder = folder_of(env, r.capture_id)
    assert (folder / "email.msg").exists()
    assert (folder / "attachments" / "Picture 2026-10-08 1410.png").read_bytes() == PNG
    assert (folder / "attachments" / "Lift plan.txt").read_bytes() == b"Lift plan, made up"
    # Save a copy goes to the meeting the notes made.
    assert (root / "Tasks" / meeting.id / "Files" / "2026-10-08 Pump curve.txt").exists()
    assert not (root / "Tasks" / "T000010" / "Files" / "2026-10-08 Pump curve.txt").exists()
    assert [(c.task, c.name) for c in m.copies if c.from_capture == r.capture_id] == [(meeting.id, "2026-10-08 Pump curve.txt")]
    # The original stays where it is.
    assert report.read_text(encoding="utf-8") == "Design point 38 kW"


def test_a_new_meeting_and_then_its_notes_again_keep_their_files(env, tmp_path):
    """A new meeting under a task gets the files; notes taken on it again later (a one-off meeting, used as it is) keep
    theirs on it too, with its copies in its own Files folder."""
    conn, root, _ = env
    report, sketch = a_file(tmp_path), a_file(tmp_path, "Seal sketch.txt")
    first = save(env, CaptureDraft(content="Pump vendor call.", task="T000008", meeting=True, meeting_name="Pump vendor call",
                                   files=[FileRow("Pump curve.txt", str(report), save_a_copy=True)]))
    m = Model(conn)
    call = m.task(first.meeting)
    assert m.parents_of(call.id) == ["T000008"] and m.captures[first.capture_id].task == call.id
    assert (root / "Tasks" / call.id / "Files" / "2026-10-08 Pump curve.txt").exists()
    again = save(env, CaptureDraft(content="Second call: seals agreed.", task=call.id, meeting=True,
                                   files=[FileRow("Seal sketch.txt", str(sketch), save_a_copy=True)]))
    m = Model(conn)
    assert again.meeting == call.id and m.captures[again.capture_id].task == call.id  # no new meeting this time
    (doc,) = m.captures[again.capture_id].documents
    assert m.documents[doc.document].description == "Pump vendor call – Attached document – Seal sketch.txt"
    assert (root / "Tasks" / call.id / "Files" / "2026-10-08 Seal sketch.txt").exists()


def test_a_top_level_meeting_keeps_its_files(env, tmp_path):
    conn, root, _ = env
    report = a_file(tmp_path)
    r = save(env, CaptureDraft(content="Walkdown with the crane crew.", meeting=True, meeting_name="Walkdown",
                               files=[FileRow("Pump curve.txt", str(report), save_a_copy=True)]))
    m = Model(conn)
    assert m.parents_of(r.meeting) == [] and m.captures[r.capture_id].task == r.meeting
    assert (root / "Tasks" / r.meeting / "Files" / "2026-10-08 Pump curve.txt").exists()


def test_meeting_notes_of_files_alone_are_kept(env, tmp_path):
    """No words, only a file: the notes are still a capture on the meeting, as a note of a file alone is."""
    conn, _, fs = env
    r = save(env, CaptureDraft(content="", task="T000010", meeting=True, files=[a_picture(fs)]))
    m = Model(conn)
    notes = m.captures[r.capture_id]
    assert notes.task == r.meeting and notes.item == "notes" and len(notes.documents) == 1
    assert (folder_of(env, r.capture_id) / "attachments" / "Picture 2026-10-08 1410.png").read_bytes() == PNG


def test_the_notes_files_are_on_the_meetings_page(env, tmp_path):
    conn, _, _ = env
    report = a_file(tmp_path)
    r = save(env, CaptureDraft(content="Impeller is on site.", task="T000010", meeting=True,
                               files=[FileRow("Pump curve.txt", str(report))]))
    m = Model(conn)
    on_page = {d.document for c in m.captures.values() if r.meeting in m.capture_tasks(c) for d in c.documents}
    assert {m.documents[d].name for d in on_page} == {"Pump curve.txt"}
