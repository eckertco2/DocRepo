"""Meeting notes and items (mods log round 2, M0048 phase 2, M0049, M0052; release 5.8): what Save makes, and the pages."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import capacity, captures, db, edits
from docrepo.config import Settings
from docrepo.detail import Pages, PageState
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, NewTaskFields, SaveError, meeting_case, meeting_name, save_capture

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
NOTES = """Agenda: Ask whether the December shutdown dates are confirmed.
Yes, 14 to 18 Dec.

#Reactor impeller upgrade
Impeller is on site.
- @Tom get the alignment report by Friday, 2 hours
  - include the shaft runout
- **decision, we go with the 50 t crane.

#Q4 overtime budget
- **u, waiting on the vendor quote
- @Sam to book the scaffolding

**closed, #Rigging plan sling drawing approved"""


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


def capture_md(env, capture_id: str) -> str:
    conn, root, _ = env
    return captures.capture_md_path(root, Model(conn).captures[capture_id]).read_text(encoding="utf-8")


def test_the_meeting_each_task_decides(env):
    m = Model(env[0])
    assert (meeting_case(m, "T000010"), meeting_name(m, "T000010", AT.date())) == ("regular", "Business team meeting 8 Oct")
    assert meeting_case(m, "T000008") == "new" and meeting_name(m, "T000008", AT.date()) == ""
    assert meeting_case(m, None) == "new"


def test_notes_of_a_regular_meeting(env):
    conn, root, _ = env
    r = save(env, CaptureDraft(content=NOTES, task="T000010", meeting=True))
    m = Model(conn)
    meeting = m.task(r.meeting)
    assert (meeting.title, meeting.meeting, meeting.state, meeting.due, m.parents_of(meeting.id)) == (
        "Business team meeting 8 Oct", True, "In progress", "2026-10-08", ["T000010"])
    notes = m.captures[r.capture_id]
    assert (notes.task, notes.types, notes.title, notes.item, notes.meeting) == (meeting.id, ["note"], "Notes of Business team meeting 8 Oct", "notes", meeting.id)
    made = [m.captures[c] for c in r.items]
    assert [(c.item, c.task, c.title) for c in made] == [
        ("note", "T000001", "Impeller is on site"), ("task", meeting.id, "Get the alignment report"),
        ("decision", "T000001", "We go with the 50 t crane"), ("update", "T000015", "Waiting on the vendor quote"),
        ("task", meeting.id, "Book the scaffolding"), ("update", "T000012", "Sling drawing approved")]
    report = m.task(made[1].created_task)
    assert m.parents_of(report.id) == [meeting.id, "T000001"] and report.assignees == ["P003"] and report.due == "2026-10-09"
    assert report.leads == [] and report.assignee_hours == 2  # no lead without @L.
    sam = next(p for p in m.people.values() if p.name == "Sam")
    assert m.task(made[4].created_task).assignees == [sam.id] and r.added_people == ["Sam"]
    rigging = m.task("T000012")
    assert (rigging.state, rigging.current_status) == ("Closed", "Sling drawing approved")
    assert [e.via for e in m.status if e.task == "T000012" and e.field == "State"][-1] == made[5].id
    # The agenda items the notes worked through close as Discussed; the rest stay open.
    open_now = {a.subject for a in m.open_items_for("T000010")}
    assert "T000001" not in open_now and "T000015" not in open_now and "T000016" in open_now and None in open_now
    assert r.discussed == 2 and r.made == {"task": 2, "note": 1, "update": 2, "decision": 1}
    assert r.message.startswith("Saved C000026. Made the meeting Business team meeting 8 Oct, under Business team meeting.")
    assert "Made 2 tasks, 1 note, 2 updates and 1 decision from its items. 2 agenda items closed as Discussed. Added Sam to people." in r.message
    # capture.md: the notes keep each @ and # with its ID, a person added by this save too, and list the items.
    text = capture_md(env, r.capture_id)
    assert f'meeting: "{meeting.id}"' in text and '"items": ' not in text and "items: [" in text and 'item: "notes"' in text
    assert "#[Reactor impeller upgrade](T000001)" in text and f"@[Sam]({sam.id}) to book" in text and "#[Rigging plan](T000012)" in text
    item_md = capture_md(env, made[1].id)
    assert 'from_notes: "C000026"' in item_md and 'item: "task"' in item_md
    assert item_md.endswith("- @[Tom Becker](P003) get the alignment report by Friday, 2 hours\n  - include the shaft runout\n")


def test_ticks_and_cards_change_what_save_makes(env):
    conn, _, _ = env
    ov = {"1": {"title": "Get the vendor's report", "due": "2026-10-16"}, "4": {"off": True}}
    open_items = {a.subject: a.id for a in Model(conn).open_items_for("T000010")}
    r = save(env, CaptureDraft(content=NOTES, task="T000010", meeting=True, meeting_name="Business team meeting, the 8th",
                               item_overrides=ov, agenda_ticks={open_items["T000015"]: False, open_items["T000016"]: True}))
    m = Model(conn)
    assert m.task(r.meeting).title == "Business team meeting, the 8th"
    report = m.task(m.captures[r.items[1]].created_task)
    assert (report.title, report.due) == ("Get the vendor's report", "2026-10-16")
    assert not any(c.title == "Book the scaffolding" for c in m.captures.values()) and r.added_people == []
    still_open = {a.subject for a in m.open_items_for("T000010")}
    assert "T000015" in still_open and "T000016" not in still_open and "T000001" not in still_open


def test_a_new_meeting_needs_a_name(env):
    with pytest.raises(SaveError, match="Name the meeting first") as e:
        save(env, CaptureDraft(content="Pump vendor call.", meeting=True))
    assert e.value.focus == "meeting"
    r = save(env, CaptureDraft(content="Pump vendor call.\n@Tom send the seal drawings #Vendor drawing package", meeting=True,
                               meeting_name="Pump vendor call"))
    m = Model(env[0])
    assert m.parents_of(r.meeting) == [] and m.task(r.meeting).meeting
    send = m.task(m.captures[r.items[0]].created_task)
    assert m.parents_of(send.id) == [r.meeting, "T000009"]


def test_items_in_an_ordinary_capture(env):
    conn, _, _ = env
    r = save(env, CaptureDraft(content="Markups finished.\n**closed, drawings sent to Mike for sign-off.", task="T000018", types={"note"}))
    m = Model(conn)
    assert m.task("T000018").state == "Closed" and m.task("T000018").current_status == "Drawings sent to Mike for sign-off."
    assert m.captures[r.capture_id].title == "Markups finished" and r.meeting is None
    # A new task: its first line's @ and # fill its own fields, and the lines under it go under it.
    r = save(env, CaptureDraft(content="@Tom check the coupling alignment #Rigging plan\n- @Mike paint the guard rails by Friday",
                               task="T000001", types={"new_task"}, new_task=NewTaskFields()))
    m = Model(conn)
    new = m.task(r.created_task)
    assert (new.title, new.assignees, m.parents_of(new.id)) == ("Check the coupling alignment", ["P003"], ["T000001", "T000012"])
    paint = m.task(m.captures[r.items[0]].created_task)
    assert (paint.title, paint.assignees, m.parents_of(paint.id)) == ("Paint the guard rails", ["P004"], [new.id])
    # A task with nowhere else to go: under Quick tasks.
    r = save(env, CaptureDraft(content="@Tom pick up the seals", types={"note"}))
    m = Model(conn)
    quick = m.task(m.captures[r.items[0]].created_task)
    assert m.task(m.parents_of(quick.id)[0]).title == "Quick tasks" and m.is_unfiled(m.captures[r.capture_id])


def test_the_pages_show_the_items(env):
    conn, root, _ = env
    r = save(env, CaptureDraft(content=NOTES, task="T000010", meeting=True))
    m = Model(conn)
    pages = Pages(m, AT.date(), lambda cid: captures.read_content(root, m.captures[cid]) or "", "P001", conn)
    log = pages.task_page("T000001", PageState())
    assert "Decision</span>" in log and "· from the notes of</span>" in log and "Business team meeting 8 Oct</a>" in log
    assert "We go with the 50 t crane" in log and "**decision" not in log  # a one-line item shows only its title
    notes_page = pages.capture_page(r.capture_id, captures.read_content(root, m.captures[r.capture_id]))
    assert "Made the meeting" in notes_page and "Made 6 items" in notes_page and "Discussed Reactor impeller upgrade" in notes_page
    assert "#Reactor impeller upgrade" in notes_page and "](T000001)" not in notes_page  # names, not IDs
    item_page = pages.capture_page(r.items[0], captures.read_content(root, m.captures[r.items[0]]))
    assert "An item from the notes in" in item_page
