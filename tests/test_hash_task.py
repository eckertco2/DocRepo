"""# choosing the task (the knowledge base's phase 0, decisions 28 to 30; release 5.32): one # task fills the task
picker, several split a note into a capture per task, and a note on the capture's own task makes no item."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import agenda, capacity, captures, db, items, notes_page, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import TODAY, Model  # noqa: E402
from docrepo.parse import ParsePerson  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import CaptureDraft, EmailItem, FileRow, email_rows, save_capture  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
INSTALLATION, RIGGING, REACTOR = "T000008", "T000012", "T000001"
NOTE = """Call from the vendor this morning.

#Installation
Crane booked for Tuesday.
- @Tom check the rigging

#Rigging plan
Sling drawing approved."""


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


def names_of(conn) -> items.Names:
    m = Model(conn)
    return items.names_of(m, [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == "P001") for p in m.people.values()])


def capture_md(env, capture_id: str) -> str:
    conn, root, _ = env
    return captures.capture_md_path(root, Model(conn).captures[capture_id]).read_text(encoding="utf-8")


def email(subject: str) -> EmailItem:
    return EmailItem(subject=subject, sender="Ann Example", sent="2026-10-07 09:15", to="Owner", body="Made-up text.")


# ---- reading ----
def test_the_tasks_a_note_names_and_its_sections(env):
    names = names_of(env[0])
    text = NOTE + "\n\nSeal kit arrived #Reactor impeller upgrade\n#Installation\nGuard rails fitted."
    r = items.read(text, names, AT.date())
    assert items.named_tasks(r) == [INSTALLATION, RIGGING, REACTOR]
    secs, rest = items.sections(r)
    # Each heading's lines run to the next heading, so "Seal kit arrived" is under Rigging plan's; Installation's two
    # parts are one section.
    assert [(s.task, s.lines) for s in secs] == [(INSTALLATION, [2, 3, 4, 5, 10, 11]), (RIGGING, [6, 7, 8, 9])]
    assert rest == [0, 1]
    assert items.section_at(r, 3) == INSTALLATION and items.section_at(r, 0) is None
    # Before any heading, a note whose line names a # task is that task's section, with the list items under it.
    r = items.read("- Seal kit arrived #Reactor impeller upgrade\n  - the gasket too\nGeneral remark.", names, AT.date())
    assert [(s.task, s.lines) for s in items.sections(r)[0]] == [(REACTOR, [0, 1])] and items.sections(r)[1] == [2]


def test_a_note_on_the_captures_own_task_makes_no_item(env):
    names = names_of(env[0])
    text = "#Installation\nCrane booked for Tuesday.\n- @Tom check the rigging\n\n#Installation #Rigging plan\nSling drawing approved."
    r = items.read(text, names, AT.date(), home=True, own=INSTALLATION)
    # The heading on Installation is the capture's own note; the one naming Rigging plan too is a note on it alone.
    assert [(it.kind, [w.ref for w in it.where]) for it in r.items] == [("task", [None, INSTALLATION]), ("note", [RIGGING])]
    r = items.read(text, names, AT.date(), home=True)  # without its own task, as before release 5.32
    assert [it.kind for it in r.items] == ["note", "task", "note"]


def test_saving_a_note_on_its_own_task(env):
    conn = env[0]
    r = save(env, CaptureDraft(content="#Installation\nCrane booked for Tuesday.", task=INSTALLATION))
    assert r.items == [] and r.message == f"Saved {r.capture_id}. Added to the raw text log of Installation."
    assert "#[Installation](T000008)\nCrane booked for Tuesday." in capture_md(env, r.capture_id)  # capture.md keeps it
    page = notes_page.get(conn, INSTALLATION)
    block = page[page.index(f"(capture:{r.capture_id})"):]
    assert "Crane booked for Tuesday." in block and "#Installation" not in block and "Installation](T" not in block  # the heading is left out
    assert notes_page.own_heading("#[Installation](T000008):", INSTALLATION)
    assert not notes_page.own_heading("#[Installation](T000008) #[Rigging plan](T000012)", INSTALLATION)
    assert not notes_page.own_heading("#[Installation](T000008) crane", INSTALLATION)


# ---- saving a split note ----
def test_a_note_naming_several_tasks_is_split(env, tmp_path):
    conn = env[0]
    a, b, c = (tmp_path / n for n in ("crane.txt", "sling.txt", "notes.txt"))
    for f in (a, b, c):
        f.write_text("made-up file", encoding="utf-8")
    mail = email("Crane booking")
    mail_rows = email_rows(mail)
    mail_rows[0].section = INSTALLATION  # its parts (none here) would go with it
    files = [FileRow(a.name, str(a), section=INSTALLATION), FileRow(b.name, str(b), section=RIGGING), FileRow(c.name, str(c)), *mail_rows]
    r = save(env, CaptureDraft(content=NOTE, files=files, agenda=[TODAY]))
    m = Model(conn)
    ids = [p.capture_id for p in r.parts]
    assert [m.captures[x].task for x in ids] == [INSTALLATION, RIGGING, None]
    assert r.capture_id == ids[0] and r.picked_task == INSTALLATION
    assert r.message == (f"Saved 3 captures, one per #task: {ids[0]}, a note on Installation with 1 email and 1 file; {ids[1]}, a note on "
                         f"Rigging plan with 1 file; {ids[2]}, an unfiled note with 1 file. Each is on Today. Made 1 task from their items.")
    assert [m.documents[d].name for d in m.captures[ids[0]].document_ids] == ["crane.txt"]
    assert m.captures[ids[0]].source == "outlook_email" and m.captures[ids[0]].title == "Crane booking"
    assert [m.documents[d].name for d in m.captures[ids[2]].document_ids] == ["notes.txt"]
    # Each capture keeps its own lines; the task item under Installation's heading is made from Installation's capture.
    assert "Crane booked for Tuesday." in capture_md(env, ids[0]) and "Sling drawing" not in capture_md(env, ids[0])
    assert "Sling drawing approved." in capture_md(env, ids[1])
    assert "Call from the vendor this morning." in capture_md(env, ids[2]) and "#" not in capture_md(env, ids[2]).split("---")[-1]
    made = m.captures[r.items[0]]
    assert made.from_notes == ids[0] and m.parents_of(made.created_task) == [INSTALLATION]
    # No note item on a part's own task: each page gets its capture's block once.
    page = notes_page.get(conn, RIGGING)
    assert page.count("Sling drawing approved.") == 1
    # Add to agenda puts each part on Today: a task's part as its task, the unfiled one as a note.
    today = [a for a in Model(conn).agenda if a.target == TODAY and a.added_by in ids]
    assert sorted((a.subject or "", a.added_by) for a in today) == sorted([(INSTALLATION, ids[0]), (RIGGING, ids[1]), ("", ids[2])])


def test_what_isnt_split(env):
    conn = env[0]
    names = names_of(conn)
    text = "#Installation\nCrane booked.\n\n#Rigging plan\nSling approved."
    # A task picked: one capture, with the other # task's lines a note item on it, as before.
    r = save(env, CaptureDraft(content=text, task=INSTALLATION))
    assert not r.parts and Model(conn).captures[r.capture_id].task == INSTALLATION and r.made == {"note": 1}
    # A new task: its own line's # tasks are its parents; the rest are items.
    r = save(env, CaptureDraft(content="Order seals\n" + text, types={"new_task"}))
    assert not r.parts and r.created_task
    # One # task, or none: no split (the capture window picks the one task).
    r = save(env, CaptureDraft(content="Crane booked #Installation"))
    assert not r.parts and Model(conn).captures[r.capture_id].task is None
    assert items.named_tasks(items.read(text, names, date(2026, 10, 8))) == [INSTALLATION, RIGGING]


def test_a_split_drops_empty_sections_and_keeps_unticked_items(env):
    conn = env[0]
    text = "#Reactor impeller upgrade\n#Installation\n- @Tom check the rigging\n- @Sam book the scaffolding\n\n#Rigging plan\nSling approved."
    names = names_of(conn)
    whole = items.read(text, names, AT.date())
    sam = next(it for it in whole.items if "scaffolding" in it.text)
    r = save(env, CaptureDraft(content=text, item_overrides={sam.key: {"off": True}}))
    m = Model(conn)
    # Reactor impeller upgrade's heading has nothing under it, so it makes no capture; nothing is under no # task either.
    assert [m.captures[p.capture_id].task for p in r.parts] == [INSTALLATION, RIGGING]
    assert r.made == {"task": 1}  # Sam's card was unticked in the window, and stays so in Installation's capture
    assert [m.tasks[m.captures[x].created_task].title for x in r.items] == ["Check the rigging"]


def test_parts_of_one_task_are_joined(env):
    r = save(env, CaptureDraft(content="#Installation\nCrane booked.\n#Rigging plan\nSling approved.\n#Installation\nGuard rails fitted."))
    first = capture_md(env, r.parts[0].capture_id)
    assert "Crane booked.\n\n#[Installation](T000008)\nGuard rails fitted." in first and len(r.parts) == 2


# ---- the capture window ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    prompts.write_defaults(fs, data_root)
    messages: list[tuple[str, str]] = []
    ctx = AppContext(conn, data_root, fs, SETTINGS, notify=lambda t, m: messages.append((t, m)), now=lambda: AT)
    w = CaptureWindow(ctx)
    w.messages = messages  # type: ignore[attr-defined]
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    if w.pin_window is not None:
        w.pin_window.hide()
        w.pin_window.deleteLater()
    w.deleteLater()
    conn.close()


def type_text(window, text: str) -> None:
    window.content.setPlainText(text)
    window.read_items()


def cursor_to(window, line: int) -> None:
    c = window.content.textCursor()
    c.movePosition(QTextCursor.MoveOperation.Start)
    c.movePosition(QTextCursor.MoveOperation.NextBlock, n=line)
    window.content.setTextCursor(c)


def test_one_hash_task_fills_the_task_picker(window):
    type_text(window, "#Installation\nCrane booked for Tuesday.")
    assert window.task == INSTALLATION and window.task_auto
    assert window.task_button.text().endswith("Installation  (from #)")
    assert "adds this to the raw text log of <b>Installation</b>" in window.does.text()
    assert window.item_cards.cards == []  # the heading's lines are the capture's own note, not an item
    type_text(window, "#Rigging plan\nSling approved.")  # the # changed: the picker follows
    assert window.task == RIGGING
    type_text(window, "#Installation\nCrane booked.\n#Rigging plan\nSling approved.")  # a second # task: no task, a split
    assert window.task is None and window.task_button.text() == "None: a capture per #task"
    assert window.does.text() == "Save makes 2 captures, one per #task: a note on <b>Installation</b> and a note on <b>Rigging plan</b>."
    type_text(window, "Crane booked.")  # the # gone: no task
    assert window.task is None and not window.task_auto
    window.save()
    assert window.messages[-1][1].endswith("Kept as an unfiled capture, listed under Unfiled.")


def test_a_hand_pick_isnt_changed_by_the_text(window):
    window.set_task(REACTOR)
    type_text(window, "#Installation\nCrane booked.")
    assert window.task == REACTOR and not window.task_auto
    window.reset_draft()
    type_text(window, "#Installation\nCrane booked.")
    assert window.task == INSTALLATION
    window._picked(None)  # None, picked by hand: it stays unfiled, with a note item on Installation
    type_text(window, "#Installation\nCrane booked again.")
    assert window.task is None and [it.kind for it in window.reading.items] == ["note"]


def test_update_follows_the_hash_task(window):
    type_text(window, "#Installation\n**u Crane booked.")
    window.set_type("update", True)
    assert window.types == {"update"} and window.task == INSTALLATION
    type_text(window, "**u Crane booked.")  # the # gone: no task, and Update stays checked until it comes back
    assert window.task is None and "update" in window.types
    type_text(window, "#Installation\n**u Crane booked.")
    assert window.task == INSTALLATION and "updates <b>Installation</b>" in window.does.text()


def test_files_go_with_the_section_the_cursor_is_in(window, tmp_path):
    a, b = tmp_path / "crane.txt", tmp_path / "sling.txt"
    for f in (a, b):
        f.write_text("made-up file", encoding="utf-8")
    type_text(window, "#Installation\nCrane booked.\n\n#Rigging plan\nSling approved.")
    cursor_to(window, 1)
    window.add_paths([str(a)])
    cursor_to(window, 4)
    window.add_paths([str(b)])
    assert [e.row.section for e in window.files] == [INSTALLATION, RIGGING]
    assert [e.goes.text() for e in window.files] == ["→ Installation", "→ Rigging plan"] and not window.files[0].goes.isHidden()
    assert window.does.text().startswith("Save makes 2 captures, one per #task: a note on <b>Installation</b> with 1 file and a note on "
                                         "<b>Rigging plan</b> with 1 file.")
    window._set_goes(window.files[1], None)  # moved by hand to the unfiled capture
    assert window.files[1].goes.text() == "→ Unfiled" and "an unfiled note with 1 file" in window.does.text()
    window._set_goes(window.files[1], RIGGING)
    window.save()
    m = window.ctx.model()
    caps = sorted((c for c in m.captures.values() if c.document_ids and c.saved.startswith("2026-10-08")), key=lambda c: c.id)
    assert [(c.task, [m.documents[d].name for d in c.document_ids]) for c in caps[-2:]] == [(INSTALLATION, ["crane.txt"]), (RIGGING, ["sling.txt"])]


def test_the_pinned_window_shows_the_hash_task_and_the_split(window, tmp_path):
    a = tmp_path / "crane.txt"
    a.write_text("made-up file", encoding="utf-8")
    window.pin()
    pin = window.pin_window
    window.content.setPlainText("#Installation")
    window.read_items()
    assert pin.task_button.text() == "#Installation"
    pin.text.moveCursor(QTextCursor.MoveOperation.End)
    window.add_paths([str(a)])
    window.content.setPlainText("#Installation\n#Rigging plan\nSling approved.")
    window.read_items()
    assert pin.task_button.text() == "Split by #task"
    assert pin.status.text() == "Installation: 1 file"


def test_the_hash_list_on_the_pinned_window(window):
    """The @ and # list follows the pinned window's own text box, in a window of its own, and Esc closes it first."""
    window.pin()
    pin = window.pin_window
    pin.activateWindow()
    pin.text.setFocus()
    QApplication.processEvents()
    pin.text.insertPlainText("#inst")
    assert pin.ref_popup.isVisible() and pin.ref_popup.item(0).text().startswith("Installation")
    assert not window.ref_popup.isVisible()  # the full window's list stays hidden with it
    assert pin.text.list_keys(Qt.Key.Key_Return)  # Enter picks
    assert pin.text.toPlainText() == "#Installation " and not pin.ref_popup.isVisible()
    window.read_items()
    assert window.task == INSTALLATION and pin.task_button.text() == "#Installation"
    pin.text.insertPlainText("@ty")
    assert pin.ref_popup.isVisible()
    pin._escape()  # Esc closes the list, and the pinned window stays
    assert not pin.ref_popup.isVisible() and pin.isVisible()
    pin._escape()
    assert not pin.isVisible()
