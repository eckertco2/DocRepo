"""The workspace's made-up work (release 5.152): the notes consolidation's project (``notes_example``) with a second parent
for one task, dates, key dates, a link on a page and a wait, saved through DocRepo's own calls. For the workspace's tests.
Every name and line here is made up."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from docrepo import edits, progress, tasks
from docrepo.model import Model
from docrepo.save import CaptureDraft, NewTaskFields, save_capture
from notes_example import SETTINGS, build

AT = datetime(2026, 11, 12, 9, 0)  # a Thursday
MIKE = "P004"


@dataclass
class Work:
    project: str
    crane: str
    rig: str
    survey: str
    kickoff: str
    weekly: str
    outage: str


def make(conn, root, fs) -> Work:
    """Cooling tower 2 rebuild with its meetings and follow-ups; Rig the east cell first also under Spring outage 2027; Due
    days, key dates (a plant activity on the project), a link in Crane for the fan lift's notes, and a wait on it."""
    ex = build(conn, root, fs)
    outage = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Spring outage 2027", types={"new_task"},
                                                                  new_task=NewTaskFields(title="Spring outage 2027")), AT).created_task
    tasks.add_parent(conn, ex.rig, outage, at=AT, via="test")
    tasks.update_task(conn, SETTINGS, ex.project, at=AT, via="test", due="2027-03-26", current_status="Survey booked for 17 Nov.")
    tasks.update_task(conn, SETTINGS, ex.crane, at=AT, via="test", due="2026-11-27", reminder="2026-11-30")
    tasks.set_key_dates(conn, ex.crane, [tasks.KeyDateRow("2026-11-24", "2026-11-26", "Crane on site")], at=AT, via="test")
    tasks.set_key_dates(conn, ex.project, [tasks.KeyDateRow("2027-03-08", "2027-03-26", "Spring outage", plant=True)], at=AT, via="test")
    page = Model(conn).pages.get(ex.crane, "")
    edits.save_page(conn, root, fs, ex.crane, page + "\n## Booking\nCrane vendor's booking page: https://crane.example.com/booking", AT)
    progress.log_progress(conn, root, fs, SETTINGS, task_id=ex.crane, line="Asked Mike for the crane vendor's quote", on=[MIKE],
                          follow_up=date(2026, 11, 17), at=AT)
    return Work(ex.project, ex.crane, ex.rig, ex.survey, ex.kickoff, ex.weekly, outage)
