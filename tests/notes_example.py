"""A made-up project with two meetings whose notes make follow-ups (release 5.140, the design workspace's notes
consolidation research of 2026-11-12, section 1.1), saved through DocRepo's own save on the sample data root, for the
tests of All notes and the Meetings section. Every name and line here is made up."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from docrepo.config import Settings
from docrepo.model import Model
from docrepo.save import CaptureDraft, NewTaskFields, save_capture

SETTINGS = Settings(me="P001")
KICKOFF_NOTES = """Attendees: Priya, Tom, Mike.
Fan deck is worse than the survey said; two panels cracked at the east cell.
- Structural survey of the fan deck @Priya **due, 20 Nov
  - get the 2019 drawings from the archive
  - check the cracked panels at the east cell
- Fill media order @Tyler
  - quotes from two vendors
- Crane for the fan lift @Tom
Shutdown window: Tom thinks the March outage is too tight for the fill media.
Vendor says fill lead time is 10 to 12 weeks, so the order has to go by 1 Dec."""
WEEKLY_NOTES = """Fill media: Tyler has both quotes; vendor B is two weeks faster. Go with B.
- Fan blade inspection @Mike **due, 4 Dec
#Structural survey of the fan deck
- drawings found; survey booked for 17 Nov
#Crane for the fan lift
- **decision, use the 90 t crane; the 50 t can't reach the east cell.
- rig the east cell first @Mike"""


@dataclass
class Example:
    project: str
    kickoff: str
    weekly: str
    survey: str
    fill: str
    crane: str
    blades: str
    rig: str
    kickoff_notes: str
    weekly_notes: str


def build(conn, data_root, fs) -> Example:
    """The project (Mon 2 Nov), the kickoff's notes (Tue 3 Nov), the weekly's (Tue 10 Nov) and a note typed on the survey
    (Wed 11 Nov)."""
    def save(draft: CaptureDraft, at: datetime):
        return save_capture(conn, data_root, fs, SETTINGS, draft, at)

    project = save(CaptureDraft(content="Cooling tower 2 rebuild", types={"new_task"}, new_task=NewTaskFields(title="Cooling tower 2 rebuild")),
                   datetime(2026, 11, 2, 8, 0)).created_task
    kickoff = save(CaptureDraft(content=KICKOFF_NOTES, task=project, meeting=True, meeting_name="Cooling tower kickoff"), datetime(2026, 11, 3, 10, 0))
    m = Model(conn)
    made = {m.tasks[m.captures[c].created_task].title: m.captures[c].created_task for c in kickoff.items}
    survey, fill, crane = made["Structural survey of the fan deck"], made["Fill media order"], made["Crane for the fan lift"]
    refs = {"#structural survey of the fan deck": survey, "#crane for the fan lift": crane}
    weekly = save(CaptureDraft(content=WEEKLY_NOTES, task=project, meeting=True, meeting_name="Cooling tower weekly 10 Nov", refs=refs),
                  datetime(2026, 11, 10, 10, 0))
    m = Model(conn)
    later = {m.tasks[t].title: t for c in weekly.items if (t := m.captures[c].created_task)}
    save(CaptureDraft(content="Priya: the archive drawings are the 2019 issue, rev C.", task=survey), datetime(2026, 11, 11, 9, 0))
    return Example(project, kickoff.meeting, weekly.meeting, survey, fill, crane, later["Fan blade inspection"], later["Rig the east cell first"],
                   kickoff.capture_id, weekly.capture_id)
