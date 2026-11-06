"""Only the touched pages, and the model's indexes (release 5.90, the review of 2026-11-06, F5).

The oracle: after each kind of change, written only to the pages ``pages_touched`` names, a full rebuild finds no page
left to write. So a page that depends on what changed was among the touched, whatever the change was."""
from __future__ import annotations

import os
import time
from datetime import datetime

import pytest

from docrepo import edits, tasks
from docrepo.config import Settings
from docrepo.model import TODAY, Capture, FileEntry, Model, RawEntry, StatusEntry, Version
from docrepo.pages import pages_touched, write_pages
from docrepo.save import CaptureDraft, save_capture

AT = datetime(2026, 10, 8, 9, 30)
SETTINGS = Settings(me="P001")
INSTALLATION, IMPELLER, RIGGING, MEETING, BUDGET = "T000008", "T000001", "T000012", "T000010", "T000015"


@pytest.fixture
def root(sample_root):
    conn, data_root, fs = sample_root
    write_pages(Model(conn), data_root, fs, AT.date(), AT)
    return conn, data_root, fs


def left_to_write(conn, data_root, fs) -> int:
    """What a full rebuild still writes: 0 when the touched pages were all the pages that changed."""
    return write_pages(Model(conn), data_root, fs, AT.date(), AT)


def save(env, **kw):
    conn, data_root, fs = env
    return save_capture(conn, data_root, fs, SETTINGS, CaptureDraft(**kw), AT)


CHANGES = {
    "a note on a task": lambda env: save(env, content="Crane booked for Tuesday.", task=INSTALLATION, types={"note"}, files=[]),
    "a new subtask": lambda env: save(env, content="Check the coupling bolts", task=INSTALLATION, types={"new_task"}, files=[]),
    "an update closing a task": lambda env: save(env, content="Rigging plan signed off. **state, closed", task=RIGGING, types={"update"}, files=[]),
    "a note with an item for another task": lambda env: save(env, content="Walkthrough notes.\n**task, Book scaffolding", task=IMPELLER,
                                                            types={"note"}, files=[]),
    "a quick task on Today": lambda env: save(env, content="Call the crane vendor", types={"new_task"}, agenda=[TODAY], files=[]),
    "a note on a meeting's agenda": lambda env: save(env, content="Bring the lift plan", task=RIGGING, types={"note"}, agenda=[MEETING], files=[]),
    "renaming a parent": lambda env: edits.edit_task(env[0], env[1], env[2], SETTINGS, INSTALLATION, AT, title="Impeller installation"),
    "moving a task to another parent": lambda env: edits.edit_task(env[0], env[1], env[2], SETTINGS, RIGGING, AT, parents=["T000009"]),
    "a label on a parent": lambda env: edits.change_task(env[0], env[1], env[2], SETTINGS, IMPELLER, AT, labels=["Safety"]),
    "states from a row": lambda env: edits.set_states(env[0], env[1], env[2], SETTINGS, {"T000019": "In progress", "T000007": "Parked"}, AT),
    "an agenda item closed": lambda env: edits.close_agenda_item(env[0], env[1], env[2], 2, "Discussed", AT),
    "a task put on Today": lambda env: edits.add_to_today(env[0], env[1], env[2], RIGGING, "", AT),
    "a reminder cleared": lambda env: edits.clear_reminder(env[0], env[1], env[2], SETTINGS, INSTALLATION, AT),
    "an unfiled capture filed": lambda env: edits.file_capture(env[0], env[1], env[2], "C000021", RIGGING, AT),
    "a capture's title fixed": lambda env: edits.edit_capture(env[0], env[1], env[2], "C000001", "Impeller datasheet, rev B", "", None, AT),
}


@pytest.mark.parametrize("name", list(CHANGES))
def test_the_touched_pages_are_every_page_that_changed(root, name):
    CHANGES[name](root)
    assert left_to_write(*root) == 0, f"{name}: a page it changed wasn't written"


def test_a_move_along_ties_rewrites_whats_tied(root):
    conn, data_root, fs = root
    tasks.update_task(conn, SETTINGS, "T000019", at=AT, via="test", ties={"start": tasks.Tie(RIGGING, amount=2)})
    tasks.update_task(conn, SETTINGS, "T000007", at=AT, via="test", ties={"start": tasks.Tie("T000019", amount=1)})
    write_pages(Model(conn), data_root, fs, AT.date(), AT)
    edits.edit_task(conn, data_root, fs, SETTINGS, RIGGING, AT, due="2026-10-30")  # the Rigging plan's end moves two tasks
    assert left_to_write(conn, data_root, fs) == 0
    assert {"T000019", "T000007", RIGGING, INSTALLATION} <= pages_touched(Model(conn), [RIGGING])


def test_a_save_on_200_tasks_rewrites_only_its_pages(root):
    conn, data_root, fs = root
    for n in range(200):  # a project with 200 tasks under it
        tasks.create_task(conn, SETTINGS, title=f"Punch item {n}", at=AT, created_by="test", parents=["T000004"])
    write_pages(Model(conn), data_root, fs, AT.date(), AT)
    pages = {p: p.stat().st_mtime_ns for p in (data_root / "Tasks").glob("*/Task.md")}
    assert len(pages) >= 217
    time.sleep(0.02)
    save(root, content="Crane booked for Tuesday.", task=RIGGING, types={"note"}, files=[])
    changed = sorted(p.parent.name for p, ns in pages.items() if p.stat().st_mtime_ns != ns)
    assert changed == [RIGGING]  # its ancestors' pages show nothing of a note on it, so they stay as they were
    assert left_to_write(conn, data_root, fs) == 0


def test_a_page_is_the_same_built_alone_or_with_all(root):
    conn, data_root, fs = root
    save(root, content="Seals arrived.", task=INSTALLATION, types={"note"}, files=[])
    alone = (data_root / "Tasks" / INSTALLATION / "Task.md").read_bytes()
    os.utime(data_root / "Tasks" / INSTALLATION / "Task.md", (1, 1))
    (data_root / "Tasks" / INSTALLATION / "Task.md").write_text("old", encoding="utf-8")
    write_pages(Model(conn), data_root, fs, AT.date(), AT)
    assert (data_root / "Tasks" / INSTALLATION / "Task.md").read_bytes() == alone


# ---- the indexes, against the scans they replace (kept here as the oracle for one release) ----
def old_notes_of(m: Model, task_id: str) -> list[Capture]:
    return [c for c in m.live_captures() if task_id in m.capture_tasks(c)]


def old_versions_of(m: Model, task_id: str) -> list[Version]:
    return [v for v in m.versions if task_id in m.document_holders(v.document)]


def old_files_of(m: Model, task_id: str) -> list[FileEntry]:
    from docrepo.links import is_folder, is_link

    out = [FileEntry("Old version" if f.old else "Saved copy", f.name, f.document, task_id) for f in m.copies if f.task == task_id]
    for doc_id in dict.fromkeys(d for c in old_notes_of(m, task_id) for d in c.document_ids):
        d = m.documents[doc_id]
        kind = "Link" if is_link(d.original) else "Folder" if is_folder(d.original) else "Tracked original" if d.original else "Email attachment"
        out.append(FileEntry(kind, d.name, doc_id, task_id))
    return out


def old_status_log_of(m: Model, task_id: str) -> list[StatusEntry]:
    out = [e for e in m.status if e.task == task_id]
    for a in m.agenda:
        if a.subject != task_id:
            continue
        name = m.target_name(a.target)
        out.append(StatusEntry(task_id, a.added, "Agenda", None, name, a.added_by, a.target))
        if a.closed:
            out.append(StatusEntry(task_id, a.closed, "Agenda", name, a.how, a.closed_by or "", a.target))
    return out


def test_the_indexes_give_what_the_scans_gave(root):
    conn, data_root, fs = root
    save(root, content="Walkthrough notes.\n**task, Book scaffolding", task=IMPELLER, types={"note"}, files=[])
    edits.add_to_today(conn, data_root, fs, RIGGING, "", AT)
    conn.execute("UPDATE captures SET discarded = '2026-10-08 09:00', discard_reason = 'test' WHERE id = 'C000002'")
    m = Model(conn)
    for t in m.tasks:
        assert m.notes_of(t) == old_notes_of(m, t), t
        assert m.versions_of(t) == old_versions_of(m, t), t
        assert m.files_of(t) == old_files_of(m, t), t
        assert m.status_log_of(t) == old_status_log_of(m, t), t
        assert m.raw_log_of(t) == sorted([RawEntry(c.saved, capture=c) for c in old_notes_of(m, t)]
                                          + [RawEntry(v.at, version=v) for v in old_versions_of(m, t)], key=lambda e: e.at), t
    m.notes_of(INSTALLATION).clear()  # a caller's list is its own: the index is untouched
    assert m.notes_of(INSTALLATION) == old_notes_of(m, INSTALLATION)
