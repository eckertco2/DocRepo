"""Years of a lead engineer's made-up work, for timing DocRepo at scale (release 5.126, the cold-eyes plan's decisions 469
to 474). ``load-sample --years 3`` adds them to the sample data; ``tests/test_scale.py`` builds that data root once and
times DocRepo on it, and the ``timings`` command times the same operations on any data root.

Each year has (decision 469) 20 projects and 500 tasks in all, 5,000 captures (1,500 of them emails, kept as
``capture_emails`` rows with their content text and no ``.msg`` file), 2,500 documents with about 12 KB of extracted text
each, 30,000 status-log rows, 150 agenda items, 1,500 tagged labels in the glossary, which the text mentions, and 25
people. The captures are notes, updates (some changing a task's Current status) and meeting notes, emails with their
attachments, and files added by their path. One task has 300 notes on its page, for the task page's budget. The years
end on the sample's own date, 2026-10-08, so its open tasks are the latest year's.

It's written the way ``sample_large.py`` is: a seeded random generator, so one seed gives the same data every time.
Every name, tag, place and address in it is made up (decision 474): plant words, invented people and vendors, the
example.com domain and a made-up file server.
"""
from __future__ import annotations

import random
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from docrepo.sample import SAMPLE_AS_OF
from docrepo.sample_large import _last

#: The generator's version. Change it whenever what it makes changes: the scale tests keep the data root they build by it.
VERSION = 1
#: The seed ``load-sample --years`` uses.
SEED = 20261111
#: The busiest task's notes, for the budget of a task page with 300 notes (decision 470).
BUSIEST_NOTES = 300
#: Where the made-up documents are, on a made-up file server.
SHARE = "\\\\fileserver\\eng\\"


@dataclass(frozen=True)
class Sizes:
    """How much one year holds (decision 469). ``text`` is the extracted text of a document, in bytes, on average."""

    projects: int = 20
    tasks: int = 500
    captures: int = 5000
    emails: int = 1500
    documents: int = 2500
    text: int = 12_000
    status_log: int = 30_000
    agenda: int = 150
    tagged: int = 1500
    people: int = 25


PER_YEAR = Sizes()

FIRST = ("Aiden", "Bea", "Carlos", "Dana", "Elif", "Farid", "Greta", "Hugo", "Ines", "Jonas", "Kara", "Liam", "Mara", "Nils",
         "Olga", "Pavel", "Quinn", "Rosa", "Sven", "Tara", "Umar", "Vera", "Wes", "Xenia", "Yusuf", "Zoe", "Arne", "Bruno",
         "Celia", "Dmitri", "Edda", "Felix", "Gwen", "Hana", "Ivo", "Jada", "Kofi", "Lena", "Milo", "Noor")
LAST = ("Aldana", "Brandt", "Castell", "Dorsey", "Eklund", "Falk", "Gurney", "Holm", "Ibarra", "Jessup", "Kovac", "Lund",
        "Marek", "Novak", "Okafor", "Pell", "Quist", "Rourke", "Sato", "Thorne", "Ueda", "Varga", "Wendt", "Yilmaz", "Zeller",
        "Abbot", "Bergen", "Corwin", "Dahl", "Ellery")
GROUPS = (("Engineering", "Process engineer"), ("Engineering", "Mechanical engineer"), ("Engineering", "Electrical engineer"),
          ("Engineering", "Instrument engineer"), ("Operations", "Shift supervisor"), ("Operations", "Area operator"),
          ("Maintenance", "Maintenance planner"), ("Maintenance", "Reliability engineer"), ("Projects", "Project controls"),
          ("Procurement", "Buyer"), ("EHS", "Safety advisor"), ("Construction", "Site supervisor"))
VENDORS = (("Norvane Pumps", "norvane"), ("Aldren Engineering", "aldren"), ("Kestrel Valves", "kestrel"),
           ("Brightwater Controls", "brightwater"), ("Halvard Fabrication", "halvard"), ("Tamsin Instruments", "tamsin"),
           ("Corrin Electrical", "corrin"), ("Westmark Scaffolding", "westmark"))
AREAS = ("Line 1", "Line 2", "Line 3", "Unit 4", "Tank farm", "Utilities", "Boiler house")
#: The labels the sample doesn't have already, with their keywords.
NEW_LABELS = (("Line 3", ["line 3"]), ("Unit 4", ["unit 4"]), ("Tank farm", ["tank farm"]), ("Utilities", ["utilities"]),
              ("Boiler house", ["boiler house"]))
THEMES = ("Strategic Plan", "Safety", "Profitability")
SCOPES = ("pump replacement", "debottleneck", "control system upgrade", "relief study", "cooling water upgrade",
          "exchanger retube", "tank inspection", "compressor overhaul", "flare tie-in", "instrument air upgrade",
          "energy savings", "loading arm replacement", "fire water upgrade", "MCC replacement", "piping renewal",
          "dryer upgrade", "safety system upgrade", "feed pump upgrade", "effluent upgrade", "nitrogen supply")
PHASES = ("Scope and basis of design", "Budget and capital request", "Permits and approvals", "Vendor selection",
          "Detailed design", "HAZOP and safety review", "Procurement", "Construction and tie-ins", "Commissioning",
          "Operator training", "Handover")
DELIVERABLES = ("Datasheet for {tag}", "Drawing review for {tag}", "Calculation for {tag}", "Vendor clarifications",
                "Isometrics", "Cable schedule", "Punch list", "Loop checks", "Inspection of {tag}", "Spares list",
                "Procedure for {tag}", "Risk assessment", "Lifting plan", "Test plan for {tag}", "Line list", "Work pack")
#: The tags' kinds: their letters and what they are.
TAG_KINDS = (("P", "Pump"), ("V", "Vessel"), ("E", "Heat exchanger"), ("TK", "Tank"), ("K", "Compressor"),
             ("FT", "Flow transmitter"), ("PT", "Pressure transmitter"), ("TT", "Temperature transmitter"),
             ("LT", "Level transmitter"), ("PSV", "Relief valve"), ("XV", "Shutdown valve"), ("FCV", "Flow control valve"),
             ("M", "Motor"), ("F", "Filter"))
#: Sentences for documents and emails. ``{tag}`` is one of the project's tags.
POOL = ("The {tag} pump seal leaks at the gland after the restart.", "Hydrotest {tag} at 1.5 times the design pressure.",
        "Cable tray runs along the east pipe rack past {tag}.", "Anchor bolts for {tag} are M24, grade 8.8, cast in.",
        "Seal flush plan 53B on {tag} with a bladder accumulator.", "The drive for {tag} is rated 250 kW at 690 V.",
        "Hot work permit needed inside the dike near {tag}.", "Duty point for {tag} is 410 m3/h at 62 m head.",
        "NPSH available at {tag} is 6.1 m at the low tank level.", "Isolate {tag} by double block and bleed.",
        "Scaffold access to {tag} on the north side only.", "Lead time for {tag} is 14 weeks from the purchase order.",
        "Spool for {tag} to be prefabricated off site.", "Vibration on {tag} within ISO 10816-3 zone B.",
        "The drawing for {tag} shows the nozzle loads at revision C.", "Concrete for the {tag} plinth is C32/40 with 50 mm cover.",
        "Instrument air for {tag} ties in at the existing manifold.", "Control narrative updated for {tag}.",
        "Start {tag} on recycle before forward flow.", "Lifting plan for the {tag} skid, 6 t.", "Base plate of {tag} grouted with epoxy.",
        "Fouling factor 0.0003 m2K/W assumed for {tag}.", "Relief valve on {tag} resized for the new rate.",
        "Pressure drop across {tag} is 0.4 bar at the design flow.", "The level switch on {tag} trips at 85 percent.",
        "Corrosion allowance for {tag} is 3 mm.", "Insulation on {tag} is mineral wool, 50 mm.", "Paint system for {tag} per spec 2.",
        "The pump curve for {tag} was revised by the vendor.", "Torque the flange bolts on {tag} in four passes.",
        "Loop check on {tag} passed with the operator present.", "The datasheet for {tag} needs the motor frame size.")
NOTES = ("Called {who} about {tag}; they'll come back by Friday.", "Walked the area with {who}. Access to {tag} is tight.",
         "{who} says the drawing for {tag} needs another look before it's issued.", "Agreed with {who} to hold {tag} until the scaffold is up.",
         "Asked {who} for the latest datasheet for {tag}.", "Reviewed the procedure with {who}: three comments, sent back.",
         "{who} raised the lead time on {tag}; it's tight.", "Checked {tag} against the shutdown window. It fits.",
         "{who} wants one point of contact for the vendor.", "{who} found a clash between the cable tray and {tag}.",
         "The seal on {tag} is to be confirmed with {who}.", "Spoke to {who}: the pump for {tag} ships next week.")
STATUSES = ("Waiting on the vendor's drawings.", "Design review done; comments sent back.", "On track for the shutdown window.",
            "Quote received; checking it against the budget.", "Behind by a week: the datasheet is late.",
            "Ready for the safety review.", "Construction started on site.", "Punch list down to a few items.",
            "Handed over to operations.", "Waiting on the permit.", "Procurement placed the order.", "Commissioning next week.")
SUBJECTS = ("{tag} datasheet comments", "Quote for {tag}", "Shutdown window for {tag}", "{tag} drawing at revision C",
            "Inspection report for {tag}", "{task} update", "Questions on {tag}", "{tag} lead time", "Meeting about {task}")
DOC_KINDS = (("Datasheet {tag}", "pdf"), ("GA drawing {tag}", "pdf"), ("Isometric {n}", "pdf"), ("Cable schedule", "xlsx"),
             ("Basis of design", "docx"), ("HAZOP report", "pdf"), ("Meeting minutes {n}", "docx"), ("Inspection report {tag}", "pdf"),
             ("Vendor quote {n}", "pdf"), ("Calculation {tag}", "xlsx"), ("Procedure {n}", "docx"), ("Line list", "xlsx"),
             ("Instrument index", "xlsx"), ("Control narrative", "docx"), ("Review slides", "pptx"), ("Test report {tag}", "pdf"))
EDIT_FIELDS = (("Current status", 40), ("Due", 20), ("Start", 10), ("Reminder", 10), ("Priority", 8), ("State", 7), ("Assignees", 5))


def totals(years: float, scale: float = 1.0) -> dict[str, int]:
    """Decision 469's sizes for ``years`` years, times ``scale`` (the tests try the generator small), each at least 1."""
    return {k: max(1, round(v * years * (scale if k != "text" else 1))) if k != "text" else v for k, v in asdict(PER_YEAR).items()}


def _workdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def add_years(data: dict[str, Any], years: float = 3, seed: int = SEED, scale: float = 1.0) -> dict[str, Any]:
    """The sample data with ``years`` years of made-up work added, ending on the sample's own date, with IDs after the
    sample's. The sample's own records are left as they are. What ``load_sample`` doesn't load (the emails' rows, the
    tagged labels' glossary and the busiest task) is kept in ``data["scale"]`` for ``add_scale_extras``."""
    rnd = random.Random(seed)  # noqa: S311 - made-up sample data, the same each time
    n = totals(years, scale)
    end = SAMPLE_AS_OF.date()
    first = end - timedelta(days=round(365 * years) - 1)
    ids = {"T": _last([t["id"] for t in data["tasks"]], "T"), "C": _last([c["id"] for c in data["captures"]], "C"),
           "D": _last([d["id"] for d in data["documents"]], "D"), "P": _last([p["id"] for p in data["people"]], "P")}

    def new_id(kind: str) -> str:
        ids[kind] += 1
        return f"{kind}{ids[kind]:03d}" if kind == "P" else f"{kind}{ids[kind]:06d}"

    def stamp(d: date) -> str:
        return f"{d.isoformat()} {7 + rnd.randrange(11):02d}:{rnd.randrange(60):02d}"

    # ---- people ----
    taken = {p["name"] for p in data["people"]}
    staff: list[str] = []
    while len(staff) < n["people"]:
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        if name in taken:
            continue
        taken.add(name)
        pid = new_id("P")
        group, role = rnd.choice(GROUPS)
        data["people"].append({"id": pid, "name": name, "aliases": [], "hours": 40, "status": "active",
                               "email": f"{name.lower().replace(' ', '.')}@example.com", "group": group, "role": role})
        staff.append(pid)
    names = {p["id"]: p["name"] for p in data["people"]}
    have = {lb["name"] for lb in data["labels"]}
    data["labels"].extend({"name": name, "keywords": words} for name, words in NEW_LABELS if name not in have)

    # ---- tagged labels: each project's own tags ----
    used_keys: set[str] = set()
    glossary: list[tuple[str, str]] = []

    def make_tags(area: str, count: int) -> list[str]:
        out = []
        digit = AREAS.index(area) + 1
        while len(out) < count:
            letters, kind = rnd.choice(TAG_KINDS)
            tag = f"{letters}-{digit}{rnd.randrange(1000):03d}{rnd.choice(('', '', '', 'A', 'B'))}"
            key = tag.replace("-", "")
            if key in used_keys:
                continue
            used_keys.add(key)
            out.append(tag)
            glossary.append((tag, f"{kind}, {area}"))
        return out

    # ---- tasks: projects, their phases and the phases' deliverables ----
    tasks: list[dict[str, Any]] = []
    windows: dict[str, tuple[date, date, int]] = {}  # task -> (start, end, depth)
    project_of: dict[str, str] = {}
    info: dict[str, dict[str, Any]] = {}  # project -> its area, tags, team and folder
    per = max(1, n["tasks"] // n["projects"])
    n_sub = (per - 1) // 4
    n_child = (per - 1 - n_sub) // n_sub if n_sub else 0
    titles: set[str] = set()
    span = (end - first).days
    current_status: dict[str, str] = {}

    def add_task(fields: dict[str, Any], parent: str | None, start: date, stop: date, depth: int, project: str | None) -> str:
        tid = new_id("T")
        state = ("Closed" if stop < end - timedelta(days=10) else "Not started" if start > end else "In progress")
        if state == "Closed" and rnd.random() < 0.04:
            state = "Parked"
        elif state == "In progress" and depth == 2 and rnd.random() < 0.15:
            state = "Not started"
        t = {"id": tid, "state": state, "created": (start - timedelta(days=rnd.randrange(1, 15))).isoformat(), "by": "Capture window",
             "start": start.isoformat(), "due": stop.isoformat(), **fields}
        if state == "Closed":
            t["closed"] = min(stop, end).isoformat()
        if state in ("In progress", "Parked"):
            t["status"] = current_status.setdefault(tid, rnd.choice(STATUSES))
        tasks.append(t)
        if parent:
            data["links"].append([tid, parent])
        windows[tid] = (start, stop, depth)
        project_of[tid] = project or tid
        return tid

    for p in range(n["projects"]):
        start = first + timedelta(days=round(span * p / n["projects"]) + rnd.randrange(-10, 11))
        start = max(first, start)
        stop = start + timedelta(days=90 + rnd.randrange(180))
        area = rnd.choice(AREAS)
        title = f"{area} {rnd.choice(SCOPES)} {start.year}"
        while title in titles:
            title += " phase 2"
        titles.add(title)
        team = rnd.sample(staff, min(len(staff), 3 + rnd.randrange(4)))
        tags = make_tags(area, max(1, n["tagged"] // n["projects"]))
        lead = "P001" if rnd.random() < 0.8 else team[0]
        project = add_task({"title": title, "labels": [area, rnd.choice(THEMES)], "leads": [lead], "leadH": 40 + rnd.randrange(120),
                            "assignees": team[:2], "asgH": 40 + rnd.randrange(160),
                            "desc": f"The {title.rsplit(' ', 1)[0].lower()} on {area}: scope, design, the shutdown work and the handover."},
                           None, start, stop, 0, None)
        info[project] = {"area": area, "tags": tags, "team": team, "title": title,
                         "pool": [s.replace("{tag}", rnd.choice(tags)) for s in POOL for _ in range(4)]}
        phases = sorted(rnd.sample(range(len(PHASES)), min(n_sub, len(PHASES))))
        days = (stop - start).days
        for i, ph in enumerate(phases):
            s = start + timedelta(days=days * i // max(1, len(phases)) - rnd.randrange(0, 10))
            e = s + timedelta(days=max(14, days // max(1, len(phases)) + rnd.randrange(0, 30)))
            s = max(s, start)
            sub = add_task({"title": PHASES[ph], "leads": [rnd.choice(team)], "leadH": 10 + rnd.randrange(50),
                            "assignees": rnd.sample(team, min(2, len(team))), "asgH": 20 + rnd.randrange(100),
                            "desc": f"{PHASES[ph]} for the {title.lower()}."}, project, s, e, 1, project)
            for _ in range(n_child):
                cs = s + timedelta(days=rnd.randrange(max(1, (e - s).days)))
                ce = cs + timedelta(days=5 + rnd.randrange(40))
                fields: dict[str, Any] = {"title": rnd.choice(DELIVERABLES).replace("{tag}", rnd.choice(tags)),
                                          "assignees": [rnd.choice(team)], "desc": "A deliverable of this phase."}
                if rnd.random() < 0.5:
                    fields["asgH"] = 8 + rnd.randrange(32)
                add_task(fields, sub, cs, ce, 2, project)
    data["tasks"].extend(tasks)
    title_of = {t["id"]: t["title"] for t in tasks}

    # The busiest task: a deliverable open on the last day, whose page gets BUSIEST_NOTES notes.
    open_leaves = [t["id"] for t in tasks if windows[t["id"]][2] == 2 and t["state"] == "In progress"] or [t["id"] for t in tasks]
    busiest = open_leaves[0]
    b0, b1, _ = windows[busiest]
    windows[busiest] = (min(b0, end - timedelta(days=200)), max(b1, end), 2)

    # ---- which tasks are open on a day ----
    days = _workdays(first, end)
    active_cache: dict[date, tuple[list[str], list[str], list[str]]] = {}

    def active(d: date) -> tuple[list[str], list[str], list[str]]:
        if d not in active_cache:
            by_depth: tuple[list[str], list[str], list[str]] = ([], [], [])
            for tid, (s, e, depth) in windows.items():
                if s <= d <= e:
                    by_depth[depth].append(tid)
            active_cache[d] = by_depth
        return active_cache[d]

    def task_on(d: date) -> str:
        projects, subs, leaves = active(d)
        roll = rnd.random()
        for group, cut in ((leaves, 0.6), (subs, 0.9), (projects, 1.0)):
            if group and roll < cut:
                return rnd.choice(group)
        return rnd.choice(leaves or subs or projects or list(windows))

    def sentences(project: str, k: int) -> str:
        return " ".join(rnd.choices(info[project]["pool"], k=k))

    def who(project: str) -> str:
        return names[rnd.choice(info[project]["team"])].split()[0]

    # ---- documents' text: about n["text"] bytes each, in paragraphs, mentioning a few of the project's tags ----
    def doc_text(name: str, project: str) -> str:
        want = int(n["text"] * (0.3 + rnd.random() * 1.4))
        tags = info[project]["tags"]
        mine = rnd.sample(tags, min(len(tags), 2 + rnd.randrange(19)))  # a datasheet names a few tags, a line list many
        parts = [name.rsplit(".", 1)[0].upper(), info[project]["title"], ""]
        size = sum(len(x) + 1 for x in parts)
        while size < want:
            para = " ".join(s.replace("{tag}", rnd.choice(mine)) for s in rnd.choices(POOL, k=6))
            parts.append(para)
            size += len(para) + 1
        return "\n".join(parts)

    folder_n = {"pdf": "Drawings", "xlsx": "Calculations", "docx": "Documents", "pptx": "Presentations"}

    def new_doc(project: str, d: date) -> dict[str, Any]:
        base, ext = rnd.choice(DOC_KINDS)
        name = base.replace("{tag}", rnd.choice(info[project]["tags"])).replace("{n}", str(1000 + rnd.randrange(9000)))
        name = f"{name} rev {chr(65 + rnd.randrange(6))}.{ext}"
        return {"id": new_id("D"), "name": name, "desc": None, "status": "Current", "checked": f"{d.isoformat()} 18:00",
                "text": doc_text(name, project), "_folder": folder_n[ext]}

    # ---- the captures, in the order they were saved ----
    d_email = n["documents"] * 3 // 10
    path_sizes: list[int] = []
    left = n["documents"] - d_email
    while left > 0:
        k = min(left, 1 + rnd.randrange(3))
        path_sizes.append(k)
        left -= k
    att_sizes: list[int] = []
    left = d_email
    while left > 0 and len(att_sizes) < n["emails"]:
        k = min(left, 1 + rnd.randrange(2))
        att_sizes.append(k)
        left -= k
    typed = max(0, n["captures"] - n["emails"] - len(path_sizes) - BUSIEST_NOTES)
    with_attachments = set(rnd.sample(range(n["emails"]), len(att_sizes)))
    att_iter = iter(att_sizes)
    slots: list[tuple[str, str, Any]] = []  # (when, kind, how many files or the busiest task)
    for i in range(n["emails"]):
        slots.append((stamp(rnd.choice(days)), "email", next(att_iter) if i in with_attachments else 0))
    slots += [(stamp(rnd.choice(days)), "path", k) for k in path_sizes]
    slots += [(stamp(rnd.choice(days)), "typed", None) for _ in range(typed)]
    busy_days = [d for d in days if windows[busiest][0] <= d]
    slots += [(stamp(rnd.choice(busy_days)), "typed", busiest) for _ in range(min(BUSIEST_NOTES, n["captures"]))]
    slots.sort(key=lambda s: s[0])

    caps, docs, copies = data["captures"], data["documents"], data["copies"]
    emails: list[tuple[str, str, str, str, str]] = []  # (capture, subject, sender, sent, conversation)
    threads: dict[str, tuple[str, str]] = {}  # task -> (its latest conversation, its subject)
    status_rows = 0
    for when, kind, extra in slots:
        d = date.fromisoformat(when[:10])
        tid = extra if kind == "typed" and extra else task_on(d)
        project = project_of[tid]
        tag = rnd.choice(info[project]["tags"])
        cid = new_id("C")
        if kind == "email":
            sender_id = rnd.choice(info[project]["team"])
            vendor = rnd.random() < 0.3
            if vendor:
                vname, domain = rnd.choice(VENDORS)
                sender = f"{vname} <sales@{domain}.example.com>"
            else:
                sender = f"{names[sender_id]} <{names[sender_id].lower().replace(' ', '.')}@example.com>"
            if tid in threads and rnd.random() < 0.6:
                conversation, base = threads[tid]
                subject = f"Re: {base}"
            else:
                conversation = f"{rnd.getrandbits(128):032X}"
                base = rnd.choice(SUBJECTS).replace("{tag}", tag).replace("{task}", title_of[tid])
                subject = base
                threads[tid] = (conversation, base)
            atts = [new_doc(project, d) for _ in range(extra)]
            for doc in atts:
                doc["capture"] = cid
                doc.pop("_folder")
                docs.append(doc)
            body = sentences(project, 3 + rnd.randrange(6))
            caps.append({"id": cid, "at": when, "kind": "email", "task": tid, "types": ["note"], "docs": [x["id"] for x in atts],
                         "attachments": [x["name"] for x in atts], "content": f"From: {sender}\nSubject: {subject}\n\n{body}"})
            emails.append((cid, subject, sender, f"{when}:00", conversation))
        elif kind == "path":
            files = [new_doc(project, d) for _ in range(extra)]
            lines = []
            for doc in files:
                doc["original"] = f"{SHARE}{info[project]['area']}\\{info[project]['title']}\\{doc.pop('_folder')}\\{doc['name']}"
                docs.append(doc)
                lines.append(doc["original"])
            if rnd.random() < 0.5:
                lines.insert(0, rnd.choice(NOTES).replace("{who}", who(project)).replace("{tag}", tag))
            cap = {"id": cid, "at": when, "kind": "path", "task": tid, "types": ["note"], "docs": [x["id"] for x in files],
                   "content": "\n".join(lines)}
            if rnd.random() < 0.05:
                cap["copies"] = [files[0]["id"]]
                copies.append({"task": tid, "name": f"{d.isoformat()} {files[0]['name']}", "doc": files[0]["id"], "from": cid})
            caps.append(cap)
        else:
            roll = rnd.random()
            text = " ".join(rnd.choice(NOTES).replace("{who}", who(project)).replace("{tag}", rnd.choice(info[project]["tags"]))
                            for _ in range(1 + rnd.randrange(4)))
            cap = {"id": cid, "at": when, "kind": "typed", "task": tid, "types": ["note"], "content": text}
            if extra is None and roll < 0.1:  # meeting notes, on the project
                cap["task"] = project
                bullets = "\n".join(f"- {rnd.choice(NOTES).replace('{who}', who(project)).replace('{tag}', rnd.choice(info[project]['tags']))}"
                                    for _ in range(3 + rnd.randrange(5)))
                cap["content"] = f"Meeting notes, {info[project]['title']} weekly\n{bullets}"
            elif extra is None and roll < 0.4:
                cap["types"] = ["update"]
                if rnd.random() < 0.5:
                    new = rnd.choice(STATUSES)
                    cap["changes"] = [["Current status", current_status.get(tid, "None"), new]]
                    current_status[tid] = new
                    status_rows += 1
            caps.append(cap)

    # ---- the status log: the rest of decision 469's rows, made in the browse tool ----
    edits = data["edits"]
    fields = [f for f, w in EDIT_FIELDS for _ in range(w)]
    task_ids = list(windows)
    for _ in range(max(0, n["status_log"] - status_rows)):
        tid = rnd.choice(task_ids)
        s, e, _depth = windows[tid]
        day = s + timedelta(days=rnd.randrange(max(1, (min(e, end) - s).days + 1)))
        field = rnd.choice(fields)
        if field == "Current status":
            old, new = current_status.get(tid, "None"), rnd.choice(STATUSES)
            current_status[tid] = new
        elif field in ("Due", "Start", "Reminder"):
            old, new = day.isoformat(), (day + timedelta(days=rnd.randrange(1, 30))).isoformat()
        elif field == "Priority":
            old, new = rnd.choice(("None", "Low", "Medium")), rnd.choice(("High", "Medium", "Low"))
        elif field == "State":
            old, new = "Not started", "In progress"
        else:
            old, new = "None", names[rnd.choice(staff)]
        edits.append({"task": tid, "at": stamp(day), "field": field, "from": old, "to": new,
                      "via": rnd.choice(("Browse tool", "Quick edit", "Timeline"))})

    # ---- agenda items: a task to bring up with someone, most of them discussed since ----
    for _ in range(n["agenda"]):
        tid = rnd.choice(task_ids)
        s, e, _depth = windows[tid]
        day = min(end, s + timedelta(days=rnd.randrange(max(1, (e - s).days + 1))))
        item = {"subject": tid, "target": rnd.choice(info[project_of[tid]]["team"]), "at": stamp(day), "by": "Browse tool",
                "note": rnd.choice(NOTES).replace("{who}", "them").replace("{tag}", rnd.choice(info[project_of[tid]]["tags"]))}
        if day < end - timedelta(days=7) and rnd.random() < 0.85:
            item.update({"closed": stamp(day + timedelta(days=rnd.randrange(1, 7))), "how": "Discussed", "closedBy": "Agenda view"})
        data["agenda"].append(item)

    data["scale"] = {"emails": emails, "glossary": glossary, "busiest": busiest, "years": years, "first": first.isoformat(),
                     "end": end.isoformat()}
    return data


def add_scale_extras(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """What ``load_sample`` doesn't load: each email's row (no ``.msg`` file), with its conversation, and the tagged labels'
    glossary, whose mentions the search index's rebuild finds in the text."""
    from docrepo.db import transaction

    extra = data.get("scale")
    if not extra:
        return
    added = datetime.fromisoformat(extra["first"]).strftime("%Y-%m-%d 08:00:00")
    with transaction(conn):
        conn.executemany(
            "INSERT INTO capture_emails (capture, pos, file, subject, sender, sent, description, conversation, message_id)"
            " VALUES (?, 0, NULL, ?, ?, ?, NULL, ?, ?)",
            [(cid, subject, sender, sent, conversation, f"<{cid.lower()}.{conversation[:12].lower()}@mail.example.com>")
             for cid, subject, sender, sent, conversation in extra["emails"]])
        conn.executemany("INSERT INTO tagged_labels (label, key, description, status, came, added) VALUES (?, ?, ?, 'glossary', 'import', ?)",
                         [(tag, tag.replace("-", "").upper(), description, added) for tag, description in extra["glossary"]])
