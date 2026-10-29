"""A large made-up project for trying the Task view at scale (release 5.34): **Line 2 debottleneck**, with 16 subtasks,
about 500 files, 80 emails and 300 notes and updates, added to the sample data by ``load-sample --large`` and used by
the Task view's timing tests. It's the browse tool mockup's ``tvSeed``, made from a seeded random generator, so it's the
same every time. Every name, company and address in it is made up.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

TITLE = "Line 2 debottleneck"
ROOT = "\\\\fileserver\\eng\\Line 2\\Debottleneck\\"
POOL = (
    "Tie-in T-14 is on the 8-inch discharge header.", "Hydrotest at 1.5 times the design pressure.", "Cable tray runs along the east pipe rack.",
    "Anchor bolts M24, grade 8.8, cast in.", "Seal flush plan 53B with a bladder accumulator.", "The VFD is rated 250 kW at 690 V.",
    "Hot work permit needed inside the dike.", "Duty point 410 m3/h at 62 m head.", "NPSH available 6.1 m at the low tank level.",
    "Isolation by double block and bleed.", "Scaffold access on the north side only.", "Lead time 14 weeks from the purchase order.",
    "Spool S-07 to be prefabricated off site.", "Vibration limits to ISO 10816-3 zone B.", "Motor frame 355, 4-pole, IE4.",
    "Concrete C32/40 with 50 mm cover.", "Instrument air tie-in at the existing manifold.", "Control narrative updated for the new pump.",
    "Startup on recycle before forward flow.", "Lifting plan for the 6 t pump skid.", "Base plate grouted with epoxy grout.",
    "Line 2 heat exchanger E-205 has spare capacity.", "Fouling factor 0.0003 m2K/W assumed.", "Relief valve PSV-212 resized for the new rate.",
)
NOTES = (
    "Called {who} about {doc}; they'll come back by Friday.", "Walked the pump bay with {who}. Access is tight on the north side.",
    "{who} says {doc} needs another look before it's issued.", "Agreed with {who} to hold the tie-in until the scaffold is up.",
    "Asked {who} for the latest {doc}.", "Reviewed {doc} with {who}: three comments, sent back.", "{who} raised the lead time on the motor; 14 weeks is tight.",
    "Checked {doc} against the turnaround window. It fits if the spools are made off site.",
    "Note from the morning meeting: {who} wants a single point of contact for the vendor.",
    "{doc} is the one to use; the earlier revisions are superseded.", "Seal flush plan to be confirmed with {who}.",
    "{who} found a clash between the cable tray and the new spool.",
)
SENDERS = {"P002": "Priya Shah <priya.shah@example.com>", "P003": "Tom Becker <tom.becker@example.com>", "P004": "Mike Ortiz <mike.ortiz@example.com>",
           "P005": "Tyler Nguyen <tyler.nguyen@example.com>", "v1": "Norvane Pumps (vendor) <sales@norvane.example.com>",
           "v2": "Aldren Engineering (vendor) <bids@aldren.example.com>"}
FIRST = {"P002": "Priya", "P003": "Tom", "P004": "Mike", "P005": "Tyler"}

# Each subtask: its folder, when its work ran, its people, and its file families: (name, extension, revisions ("rev",
# "v", "date", "n" or ""), how many, the description, how they came ("path", "email" or "link"), words their text holds).
SUBTASKS: list[dict[str, Any]] = [
    {"title": "Scope and FEED", "state": "In progress", "folder": "01 Scope", "from": "2026-06-01", "to": "2026-10-07", "leads": ["P001"], "assignees": ["P002"],
     "due": "2026-10-30", "desc": "Front-end engineering: scope, basis of design and the FEED package.", "status": "FEED review moved to Thu 22 Oct.",
     "fam": [("Scope of work", "docx", "v", 3, "The project's scope: target rate, battery limits and what's left out.", "path", ["Target rate 410 m3/h, up from 340 m3/h."]),
             ("Basis of design", "docx", "rev", 3, "Design basis: rates, utilities, codes and assumptions.", "path", []),
             ("Heat and material balance", "xlsx", "rev", 4, "Stream table at the new 410 m3/h rate.", "email", []),
             ("FEED review minutes", "docx", "date", 18, "Minutes of the weekly FEED review.", "path", []),
             ("PFD 2-001", "pdf", "rev", 4, "Process flow diagram of Line 2 after the debottleneck.", "email", []),
             ("Debottleneck study", "pdf", "", 1, "The study that found the transfer pump and E-205 as the bottlenecks.", "path",
              ["Bottleneck 1: the transfer pump P-201.", "Bottleneck 2: exchanger E-205."]),
             ("Kickoff deck", "pptx", "", 1, "Slides from the project kickoff on 3 June.", "path", []),
             ("Line 2 master schedule", "xlsx", "rev", 6, "The project's master schedule, milestone by milestone.", "path", []),
             ("Line 2 team site", "link", "", 1, "The project's SharePoint site.", "link", [])],
     "sub": [{"title": "FEED review package", "state": "In progress", "folder": "01 Scope\\FEED package", "from": "2026-08-20", "to": "2026-10-06",
              "assignees": ["P002", "P003"], "due": "2026-10-22", "desc": "Everything the FEED review on 22 Oct needs.",
              "fam": [("FEED package index", "xlsx", "rev", 3, "The list of FEED deliverables and their status.", "path", []),
                      ("Equipment list", "xlsx", "rev", 4, "Every item of equipment, new and changed.", "email", []),
                      ("Line list", "xlsx", "rev", 3, "New and changed lines with their specs.", "email", []),
                      ("Cost estimate class 3", "xlsx", "rev", 2, "The class 3 estimate for the capital request.", "path", ["Total installed cost 4.2 M, +20% / -15%."]),
                      ("FEED review presentation", "pptx", "v", 2, "Slides for the FEED review.", "path", [])]}]},
    {"title": "Vendor selection", "state": "In progress", "folder": "02 Vendors", "from": "2026-07-01", "to": "2026-10-07", "leads": ["P001"], "assignees": ["P005"],
     "due": "2026-10-23", "desc": "Pick the pump and motor package vendor.", "status": "Shortlist of two agreed with procurement.",
     "fam": [("Pump curve", "pdf", "rev", 2, "The vendor's pump curve at the new duty point.", "email",
              ["Duty point 410 m3/h at 62 m head.", "NPSH required 4.2 m.", "Efficiency 81% at the duty point."]),
             ("Bid tab", "xlsx", "rev", 3, "Bids side by side: price, lead time and exceptions.", "path", []),
             ("Vendor comparison", "xlsx", "v", 2, "Technical comparison of the two shortlisted vendors.", "path", []),
             ("Technical bid Norvane", "pdf", "", 1, "Norvane's technical bid.", "email", []),
             ("Technical bid Aldren", "pdf", "", 1, "Aldren's technical bid.", "email", []),
             ("Commercial bid Norvane", "pdf", "", 1, "Norvane's price and terms.", "email", []),
             ("Commercial bid Aldren", "pdf", "", 1, "Aldren's price and terms.", "email", []),
             ("Bid clarifications", "docx", "rev", 3, "Questions to the bidders and their answers.", "email", []),
             ("Pump datasheet", "pdf", "rev", 3, "The pump datasheet for the enquiry.", "path", ["Seal flush plan 53B.", "API 610 OH2."]),
             ("Request for quotation", "docx", "v", 2, "The enquiry sent to four vendors.", "path", []),
             ("Vendor visit photo", "jpg", "n", 26, "Photos from the visit to Norvane's test bay.", "path", [])]},
    {"title": "Pump and motor package", "state": "Not started", "folder": "03 Pump", "from": "2026-08-15", "to": "2026-10-06", "leads": ["P002"], "assignees": ["P004"],
     "due": "2026-12-04", "desc": "Detailed design of the new transfer pump P-201B and its motor.",
     "fam": [("GA drawing P-201B", "pdf", "rev", 4, "General arrangement of the new pump skid.", "email", []),
             ("Seal drawing", "pdf", "rev", 2, "Mechanical seal and its flush plan.", "email", ["Seal flush plan 53B with a bladder accumulator."]),
             ("Pump foundation loads", "xlsx", "", 1, "Static and dynamic loads for the civil design.", "email", []),
             ("Lifting plan", "docx", "v", 2, "How the 6 t skid gets lifted in.", "path", []),
             ("Pump inspection and test plan", "docx", "rev", 2, "Witness and hold points at the vendor's works.", "path", [])],
     "sub": [{"title": "Motor and VFD", "state": "Not started", "folder": "03 Pump\\Motor", "from": "2026-09-01", "to": "2026-10-05", "assignees": ["P004"],
              "due": "2026-12-04", "desc": "The 250 kW motor and its drive.",
              "fam": [("Motor datasheet", "pdf", "rev", 2, "The 250 kW, 4-pole IE4 motor.", "email", []),
                      ("VFD datasheet", "pdf", "rev", 2, "The drive: 250 kW, 690 V.", "email", []),
                      ("Harmonics study", "pdf", "", 1, "Harmonics with the new drive on the 690 V board.", "path", [])]}]},
    {"title": "Piping tie-ins", "state": "In progress", "folder": "04 Piping", "from": "2026-07-15", "to": "2026-10-07", "leads": ["P003"], "assignees": ["P004"],
     "due": "2026-10-30", "desc": "The tie-ins the turnaround has to make, and their spools.", "status": "Tie-in list at rev 4; two spools still to be detailed.",
     "fam": [("Tie-in list", "xlsx", "rev", 4, "Every tie-in, its size, its isolation and its window.", "path", ["Tie-in T-14 is on the 8-inch discharge header."]),
             ("Isometric", "pdf", "n", 60, "A spool isometric for fabrication.", "path", []),
             ("Tie-in sketch", "pdf", "n", 24, "A sketch of a tie-in from the site walk.", "email", []),
             ("Hydrotest procedure", "docx", "rev", 2, "How the new spools are pressure tested.", "path", []),
             ("Piping stress report", "pdf", "rev", 2, "Stress analysis of the new discharge line.", "email", []),
             ("Site walk photo", "jpg", "n", 40, "A photo from the tie-in site walk.", "path", [])]},
    {"title": "Electrical and controls", "state": "Not started", "folder": "05 Electrical", "from": "2026-08-01", "to": "2026-10-02", "leads": ["P002"],
     "due": "2026-11-27", "desc": "Power, cabling, instruments and the control changes.",
     "fam": [("Single line diagram", "pdf", "rev", 3, "The 690 V board with the new feeder.", "email", []),
             ("Cable schedule", "xlsx", "rev", 3, "Every new cable, its route and size.", "path", []),
             ("Instrument index", "xlsx", "rev", 3, "New and changed instruments.", "path", []),
             ("Control narrative", "docx", "rev", 2, "How the new pump is controlled.", "path", ["Control narrative updated for the new pump."]),
             ("Loop drawing", "pdf", "n", 40, "An instrument loop drawing.", "email", []),
             ("Cable tray layout", "pdf", "rev", 2, "Tray routes on the east pipe rack.", "email", [])]},
    {"title": "Civil and foundations", "state": "Not started", "folder": "06 Civil", "from": "2026-08-10", "to": "2026-10-01", "assignees": ["P004"],
     "due": "2026-11-13", "desc": "The new pump plinth and pipe supports.",
     "fam": [("Foundation drawing F-203", "pdf", "rev", 3, "The new pump plinth.", "email", ["Anchor bolts M24, grade 8.8, cast in."]),
             ("Geotechnical report", "pdf", "", 1, "Soil report from the 2019 survey.", "path", []),
             ("Pipe support drawing", "pdf", "n", 22, "A new pipe support.", "email", []),
             ("Concrete pour plan", "docx", "", 1, "Pour sequence and curing for the plinth.", "path", [])]},
    {"title": "Permits and approvals", "state": "In progress", "folder": "07 Permits", "from": "2026-07-01", "to": "2026-10-06", "leads": ["P001"],
     "due": "2026-10-16", "desc": "The air permit change and the capital approval.", "status": "Air permit submitted; waiting on the regulator.",
     "fam": [("Air permit application", "pdf", "v", 2, "The change to the site's air permit.", "path", []),
             ("Capital request", "docx", "v", 3, "The capital request for the board.", "path", []),
             ("Approval email", "pdf", "", 1, "The board's approval, saved as PDF.", "email", []),
             ("Regulator correspondence", "pdf", "n", 9, "A letter to or from the regulator.", "email", [])]},
    {"title": "HAZOP and safety review", "state": "Closed", "closed": "2026-09-25", "folder": "08 HAZOP", "from": "2026-08-20", "to": "2026-09-25", "leads": ["P002"],
     "due": "2026-09-25", "desc": "The HAZOP of the new pump and tie-ins.", "status": "HAZOP done; 23 actions, all assigned.",
     "fam": [("HAZOP report", "pdf", "", 1, "The HAZOP report.", "path", []),
             ("HAZOP actions register", "xlsx", "rev", 3, "The 23 actions and who owns them.", "path", []),
             ("HAZOP worksheets", "pdf", "", 1, "Node by node worksheets.", "path", []),
             ("Safety review slides", "pptx", "", 1, "Slides for the safety committee.", "path", [])]},
    {"title": "Budget and capital request", "state": "Closed", "closed": "2026-08-28", "folder": "09 Budget", "from": "2026-06-15", "to": "2026-08-28", "leads": ["P001"],
     "due": "2026-08-28", "desc": "The budget for the capital request.", "status": "Approved by the board on 28 Aug.",
     "fam": [("Budget estimate", "xlsx", "rev", 4, "The project budget by area.", "path", []),
             ("Cash flow forecast", "xlsx", "v", 2, "Spend by month.", "path", []),
             ("Board paper", "docx", "v", 2, "The paper for the board's approval.", "path", [])]},
    {"title": "Turnaround window planning", "state": "In progress", "folder": "10 Turnaround", "from": "2026-08-01", "to": "2026-10-07", "leads": ["P003"],
     "assignees": ["P004"], "due": "2026-11-06", "desc": "Fitting the tie-ins into the fall turnaround.", "status": "Tie-ins planned into the fall turnaround, 19 to 30 Oct.",
     "fam": [("Turnaround schedule", "xlsx", "rev", 5, "Line 2's part of the turnaround schedule.", "path", []),
             ("Work pack", "pdf", "n", 26, "A work pack for the turnaround crew.", "path", []),
             ("Scaffold request", "xlsx", "", 1, "Scaffolds the tie-ins need.", "email", []),
             ("Crane plan", "pdf", "", 1, "The 80 t crane's set-up for the skid lift.", "email", [])]},
    {"title": "Commissioning plan", "state": "Not started", "folder": "11 Commissioning", "from": "2026-09-10", "to": "2026-10-05", "assignees": ["P003"],
     "due": "2026-12-11", "desc": "How the new pump is started and handed over.",
     "fam": [("Commissioning plan", "docx", "v", 2, "Steps from mechanical completion to handover.", "path", ["Startup on recycle before forward flow."]),
             ("Commissioning checklist", "xlsx", "", 1, "The checks before startup.", "path", []),
             ("Performance test procedure", "docx", "", 1, "How the new rate is proven.", "path", [])]},
    {"title": "Operator training", "state": "Not started", "folder": "12 Training", "from": "2026-09-15", "to": "2026-10-06", "assignees": ["P003"],
     "due": "2026-12-11", "desc": "Training the operators on the new pump.",
     "fam": [("Training matrix", "xlsx", "", 1, "Who needs which module.", "path", []),
             ("Operator training slides", "pptx", "v", 2, "The new pump and its controls, for operators.", "path", [])]},
    {"title": "Spares and stores", "state": "Not started", "folder": "13 Spares", "from": "2026-09-01", "to": "2026-10-03", "assignees": ["P005"],
     "due": "2026-12-18", "desc": "Commissioning and two-year spares.",
     "fam": [("Spares list", "xlsx", "rev", 2, "Commissioning and two-year spares.", "email", []),
             ("Spare seal quote", "pdf", "", 1, "A quote for a spare mechanical seal.", "email", [])]},
    {"title": "Site survey", "state": "Closed", "closed": "2026-07-17", "folder": "14 Survey", "from": "2026-06-20", "to": "2026-07-17", "assignees": ["P004"],
     "due": "2026-07-17", "desc": "Survey of the Line 2 pump bay before design.", "status": "Survey done; photos and the point cloud are on the share.",
     "fam": [("Survey photo", "jpg", "n", 100, "A photo from the pump bay survey.", "path", []),
             ("Laser scan index", "xlsx", "", 1, "Where each scan was taken.", "path", []),
             ("Survey report", "pdf", "", 1, "What the survey found.", "path", []),
             ("Point cloud viewer", "link", "", 1, "The laser scan, in the scan viewer.", "link", [])]},
]
#: The files the large project pins, and those it has opened lately: (name, when, action), for release 5.35's tables.
PINNED = ("Scope of work v3.docx", "Line 2 master schedule rev F.xlsx", "Pump curve rev C.pdf", "Line 2 team site")
OPENED = (("Pump curve rev C.pdf", "2026-10-08 08:10:00", "open"), ("Tie-in list rev D.xlsx", "2026-10-07 14:22:00", "open"),
          ("Line 2 master schedule rev F.xlsx", "2026-10-07 09:03:00", "open"), ("Bid tab rev C.xlsx", "2026-10-06 11:40:00", "copy_path"),
          ("Scope of work v3.docx", "2026-10-05 10:15:00", "open"), ("Turnaround schedule rev E.xlsx", "2026-10-02 15:30:00", "show"),
          ("Control narrative rev B.docx", "2026-09-30 13:05:00", "open"))
#: A file moved since it was added, for the Task view's missing-file message.
MOVED = "Tie-in list rev B.xlsx"


def _last(ids: list[str], prefix: str) -> int:
    return max(int(x[len(prefix):]) for x in ids if x.startswith(prefix))


def add_large_project(data: dict[str, Any]) -> dict[str, Any]:
    """The sample data with the large project added: new tasks, captures, documents and saved copies, with IDs after
    the sample's own. The sample's own records are left as they are."""
    rnd = random.Random(20261029)
    t_n = _last([t["id"] for t in data["tasks"]], "T")
    c_n = _last([c["id"] for c in data["captures"]], "C")
    d_n = _last([d["id"] for d in data["documents"]], "D")
    tasks, links, caps, docs, copies = data["tasks"], data["links"], data["captures"], data["documents"], data["copies"]

    def new_id(kind: str) -> str:
        nonlocal t_n, c_n, d_n
        if kind == "T":
            t_n += 1
            return f"T{t_n:06d}"
        if kind == "C":
            c_n += 1
            return f"C{c_n:06d}"
        d_n += 1
        return f"D{d_n:06d}"

    def day_of(text: str) -> date:
        return date.fromisoformat(text)

    def workday(d: date) -> date:
        return d + timedelta(days=(7 - d.weekday()) % 7 if d.weekday() >= 5 else 0)

    def at(d: date) -> str:
        return f"{d.isoformat()} {7 + rnd.randrange(10):02d}:{rnd.randrange(60):02d}"

    def text_for(base: str, rev: str, extra: list[str]) -> str:
        return "\n".join([base.upper(), *([f"Revision {rev}"] if rev else []), "Line 2 debottleneck", "", *extra, *(rnd.choice(POOL) for _ in range(4))])

    def add_task(fields: dict[str, Any], parent: str | None) -> str:
        tid = new_id("T")
        tasks.append({"id": tid, "created": fields.get("from", "2026-06-01"), "by": "Excel import", "state": "Not started", **fields})
        if parent:
            links.append([tid, parent])
        return tid

    project = add_task({"title": TITLE, "state": "In progress", "labels": ["Line 2", "Strategic Plan"], "leads": ["P001"], "leadH": 120,
                        "assignees": ["P003", "P004", "P002"], "asgH": 80, "start": "2026-06-01", "due": "2026-12-18", "from": "2026-06-01",
                        "desc": "Raise Line 2's rate from 340 to 410 m3/h by replacing the transfer pump and tying it in during the fall turnaround.",
                        "status": "Vendor shortlist agreed with procurement. FEED review moved to Thu 22 Oct."}, None)

    def seed(sub: dict[str, Any], parent: str) -> None:
        tid = add_task({k: sub[k] for k in ("title", "state", "closed", "leads", "assignees", "due", "desc", "status") if k in sub}
                       | {"start": sub["from"], "from": sub["from"]}, parent)
        start, end = day_of(sub["from"]), day_of(sub["to"])
        span = (end - start).days
        pending: list[tuple[dict[str, Any], date]] = []
        names: list[str] = []
        for base, ext, revs, count, desc, how, words in sub["fam"]:
            for i in range(count):
                d = workday(start + timedelta(days=rnd.randrange(span + 1)) if count == 1 else start + timedelta(days=int(span * (i + 0.5 + rnd.random() * 0.4) / count)))
                rev = chr(65 + i) if revs == "rev" else str(i + 1) if revs == "v" else d.isoformat() if revs == "date" else str(1000 + i * 3 + rnd.randrange(3)) if revs == "n" else ""
                suffix = {"rev": f" rev {rev}", "v": f" v{rev}", "date": f" {rev}", "n": f" {rev}"}.get(revs, "")
                name = base if how == "link" else f"{base}{suffix}.{ext}"
                doc: dict[str, Any] = {"name": name, "desc": desc, "status": "Current", "checked": "2026-10-08 07:58",
                                       "text": "" if ext in ("jpg", "link") else text_for(base, rev if revs in ("rev", "v") else "", words)}
                if how == "link":
                    doc["original"] = f"https://sharepoint.example.com/sites/line2/{base.replace(' ', '')}"
                elif how == "path":
                    doc["original"] = ROOT + sub["folder"] + "\\" + name
                if how == "email":
                    pending.append((doc, d))
                    continue
                doc["id"] = new_id("D")
                docs.append(doc)
                names.append(name)
                if ext == "jpg" and caps and caps[-1].get("task") == tid and caps[-1]["kind"] == "path" and caps[-1].get("photos") and len(caps[-1]["docs"]) < 12:
                    caps[-1]["docs"].append(doc["id"])
                    caps[-1]["content"] += "\n" + doc["original"]
                    continue
                cid = new_id("C")
                content = f"Photos: {desc[:-1].replace('A photo', 'photos')}.\n{doc['original']}" if ext == "jpg" else (
                    f"{desc}\n{doc['original']}" if how == "link" or rnd.random() < 0.5 else doc["original"])
                cap: dict[str, Any] = {"id": cid, "at": at(d), "kind": "typed" if how == "link" else "path", "task": tid, "types": ["note"], "docs": [doc["id"]],
                                       "content": content}
                if ext == "jpg":
                    cap["photos"] = True
                if how == "path" and ext != "jpg" and rnd.random() < 0.18:
                    cap["copies"] = [doc["id"]]
                    copies.append({"task": tid, "name": f"{d.isoformat()} {name}", "doc": doc["id"], "from": cid})
                caps.append(cap)
        # The emails: one to three attachments each, from a person or a vendor.
        while pending:
            n = 1 + rnd.randrange(3)
            batch, pending = pending[:n], pending[n:]
            d = batch[-1][1]
            sender = rnd.choice(["P002", "P003", "P004", "P005", "v1", "v2"])
            cid = new_id("C")
            subject = ("Re: " if rnd.random() < 0.5 else "") + batch[0][0]["name"].rsplit(".", 1)[0] + (f" and {len(batch) - 1} more" if len(batch) > 1 else "")
            ids = []
            for doc, _ in batch:
                doc["id"], doc["capture"] = new_id("D"), cid
                doc.pop("original", None)
                docs.append(doc)
                ids.append(doc["id"])
                names.append(doc["name"])
            body = f"Please find {'the files' if len(batch) > 1 else 'it'} attached. {rnd.choice(POOL)} {rnd.choice(POOL)} Let me know if you need anything else."
            caps.append({"id": cid, "at": at(d), "kind": "email", "task": tid, "types": ["note"], "docs": ids, "attachments": [x[0]["name"] for x in batch],
                         "content": f"From: {SENDERS[sender]}\nSubject: {subject}\n\n{body}"})
        # Notes and updates: about one a week through its window.
        for i in range(max(3, round(span / 6))):
            d = workday(start + timedelta(days=int(span * (i + rnd.random()) / max(3, round(span / 6)))))
            who = FIRST[rnd.choice(["P002", "P003", "P004", "P005"])]
            doc_name = rnd.choice(names).rsplit(".", 1)[0] if names else "the drawings"
            text = rnd.choice(NOTES).replace("{who}", who).replace("{doc}", doc_name)
            text = text[0].upper() + text[1:]
            update = rnd.random() < 0.35
            cap = {"id": new_id("C"), "at": at(d), "kind": "typed", "task": tid, "types": ["update" if update else "note"], "content": text}
            if update and rnd.random() < 0.5:
                cap["changes"] = [["Current status", "None", text]]
            caps.append(cap)
        if sub.get("status"):
            caps.append({"id": new_id("C"), "at": at(workday(end)), "kind": "typed", "task": tid, "types": ["update"], "content": sub["status"],
                         "changes": [["Current status", "None", sub["status"]]]})
        if sub.get("closed"):
            caps.append({"id": new_id("C"), "at": at(day_of(sub["closed"])), "kind": "typed", "task": tid, "types": ["update"],
                         "content": f"Closed. {sub.get('status', '')}".strip(), "changes": [["State", "In progress", "Closed"]]})
        for child in sub.get("sub", []):
            seed(child, tid)

    for sub in SUBTASKS:
        seed(sub, project)
    for when, content, changes in (
            ("2026-06-03 09:12", "Kickoff held with Priya, Tom and Mike. Target 410 m3/h, tie-ins in the fall turnaround.", None),
            ("2026-08-28 15:40", "Capital approved by the board.", [["Current status", "None", "Capital approved; FEED under way."]]),
            ("2026-10-05 08:55", "Vendor shortlist agreed with procurement. FEED review moved to Thu 22 Oct.",
             [["Current status", "Capital approved; FEED under way.", "Vendor shortlist agreed with procurement. FEED review moved to Thu 22 Oct."]])):
        cap = {"id": new_id("C"), "at": when, "kind": "typed", "task": project, "types": ["update" if changes else "note"], "content": content}
        if changes:
            cap["changes"] = changes
        caps.append(cap)
    vendors = next(t["id"] for t in tasks if t["title"] == "Vendor selection")
    cid, did = new_id("C"), new_id("D")
    docs.append({"id": did, "name": "Pump curve rev C.pdf", "desc": "The vendor's revised curve at the new duty point.", "capture": cid, "status": "Current",
                 "checked": "2026-10-08 07:58", "text": "NORVANE PUMPS\nPump curve, rev C\nP-201B transfer pump\n\nDuty point 410 m3/h at 62 m head\n"
                 "NPSH required 4.2 m at the duty point\nEfficiency 81% at the duty point\nImpeller 385 mm, trimmed from 405 mm\nSeal flush plan 53B"})
    caps.append({"id": cid, "at": "2026-10-07 17:48", "kind": "email", "task": vendors, "types": ["note"], "docs": [did], "attachments": ["Pump curve rev C.pdf"],
                 "content": "From: Tom Becker <tom.becker@example.com>\nSubject: Re: pump curve rev C\n\nRev C attached. The impeller is trimmed to 385 mm, "
                            "which moves the duty point onto the curve's sweet spot. NPSH is fine at the low tank level."})
    for cap in caps:
        cap.pop("photos", None)
    return data


def project_id(conn) -> str | None:
    """The large project's task ID in a database, or None when it isn't there."""
    row = conn.execute("SELECT id FROM tasks WHERE title = ?", (TITLE,)).fetchone()
    return row["id"] if row else None


def add_pins_and_uses(conn) -> None:
    """The large project's pinned files, and the files it opened lately (release 5.35's tables), for its Overview."""
    from datetime import datetime

    from docrepo import pins

    pid = project_id(conn)
    if pid is None:
        return

    def doc(name: str) -> str | None:
        row = conn.execute("SELECT id FROM documents WHERE name = ? ORDER BY id DESC", (name,)).fetchone()
        return row["id"] if row else None

    for name in PINNED:
        d = doc(name)
        if d:
            pins.set_pinned(conn, pid, d, True)
    for name, at, action in OPENED:
        d = doc(name)
        if d:
            pins.record_use(conn, d, pid, action, datetime.fromisoformat(at))
