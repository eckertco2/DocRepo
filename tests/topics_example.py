"""The cooling tower project (``notes_example``) with topic headings on its pages, for release 5.157's tests of All notes
By meeting and By topic, and its pictures (the design workspace's notes topics plan, decisions 709 to 717): the kickoff's
and the weekly's notes under Schedule, Safety and Budget, lines moved from the weekly onto Fill media order under Vendor
and Delivery, Fill media order's own "Vendors" (drift typed before the heading list), and the survey's findings with a
run of five files. Written to docs.db as the owner's edits would be. Every name and line here is made up."""
from __future__ import annotations

from datetime import datetime

from docrepo import notes_page

#: The move of the weekly's fill media lines onto Fill media order, keyed as Move to task keys one (release 5.143).
KEY = "M20261110100500"
#: Made-up files: the survey's run of five (two pictures, three attachments), and the project's scope of work.
FILES = (("D000901", "Deck plank 4.png", "Plank 4 split along the grain"),
         ("D000902", "Beam 3 bearing.png", "Section loss at the bearing plate"),
         ("D000903", "Survey report draft.docx", "Draft report, for comment by Fri 20 Nov"),
         ("D000904", "Deck plan rev C.pdf", "The fan deck's plank layout, marked up"),
         ("D000905", "Fan deck photos.zip", "Every photo from the walk-down"),
         ("D000906", "Scope of work rev A.docx", "Maintenance planning's scope for the rebuild"))


def _caption(page: str) -> str:
    return next(x for x in page.split("\n") if notes_page.read_line(x).kind == "caption")


def file_lines(files) -> list[str]:
    """Pictures and attachments as a page holds them: each its line, then its description as the list item under it."""
    out = []
    for doc_id, name, description in files:
        picture = name.endswith(".png")
        out += [notes_page.item_line("picture" if picture else "attachment", name if picture else f"File: {name}", doc_id), f"  - {description}"]
    return out


def pages_of(conn, ex) -> dict[str, str]:
    """The project's pages with their topic headings, from the pages the example's saves wrote."""
    page = {t: notes_page.get(conn, t) for t in (ex.project, ex.kickoff, ex.weekly, ex.fill, ex.survey)}
    lines = {t: body.split("\n") for t, body in page.items()}
    tasks = [x for x in lines[ex.kickoff] if notes_page.read_line(x).kind == "task"]
    weekly = [x for x in lines[ex.weekly][3:] if notes_page.read_line(x).kind in ("task", "pointer")]
    body = {
        ex.project: [*lines[ex.project], "Rebuild of cooling tower 2: fill, fan deck and drift eliminators, in the spring outage.",
                     notes_page.file_line(f"File: {FILES[5][1]}, {FILES[5][2]}", FILES[5][0])],
        ex.kickoff: ["# Tue 3 Nov 2026", _caption(page[ex.kickoff]), "Attendees: Priya, Tom, Mike.",
                     "Fan deck is worse than the survey said; two panels cracked at the east cell.", *tasks,
                     "# Schedule", "## Outage window", "Tower 2 offline 9 to 20 Mar, from 6 am on the 9th.",
                     "# Safety", "Confined space entry for the basin: a standby person each shift.",
                     "# Budget", "Approved at 410 k with 10 % contingency."],
        ex.weekly: ["# Tue 10 Nov 2026", _caption(page[ex.weekly]), *weekly,
                    notes_page.pointer_line("Fill media order · 5 lines moved there", ex.fill, KEY),
                    "# Schedule", "## Tie-in", "Tie in the new basin heater on the outage's last day.",
                    "# Safety", "## Permits", "Hot work permit for the fan deck brackets."],
        ex.fill: [*lines[ex.fill], "# Vendors", "Ask Tyler for quotes from two vendors.",
                  "# Tue 10 Nov 2026", notes_page.lead_line("Moved from the notes of Cooling tower weekly 10 Nov · Tue 10 Nov", ex.weekly, KEY),
                  "# Vendor", "## Quotes", "Vendor B 18 % under vendor A.", "## Lead time", "12 weeks from the order.",
                  "# Delivery", "Order by 1 Dec to land on site 23 Feb.",
                  "# Thu 12 Nov 2026", "# vendor ", "## Quotes", "Vendor B holds its price to 30 Nov.",
                  "## Lead time", "Vendor B can do 10 weeks for a 5 % premium."],
        ex.survey: [*lines[ex.survey], "# Findings", "Six planks to replace; beam 3 corroded at its bearing.", *file_lines(FILES[:5]),
                    "# Access", "## Scaffold", "Scaffold for beam 3 booked for 9 Mar."],
    }
    return {t: "\n".join(x) for t, x in body.items()}


def give_topics(conn, ex, now: datetime = datetime(2026, 11, 17, 9, 0)) -> dict[str, str]:
    """Write the made-up files and the pages with topic headings to docs.db; the pages, by task."""
    held_by = _caption(notes_page.get(conn, ex.survey)).split("(capture:")[1].rstrip(")")
    for doc_id, name, description in FILES:
        conn.execute("INSERT INTO documents (id, name, description, capture) VALUES (?, ?, ?, ?)", (doc_id, name, description, held_by))
    body = pages_of(conn, ex)
    for task_id, text in body.items():
        notes_page.put(conn, task_id, text, now)
    conn.commit()
    return body
