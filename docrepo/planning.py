"""Quick edit's rules (mods log round 4, M0067, item 55, decisions 138, 139, 143 and 145; release 5.30).

Quick edit is a small window, opened by double-clicking a task on the timeline, with a one-line box and the fields that
plan a task: Start, Due, Deadline and its description, Repeats, the lead and the assignees with their hours, and Plant
event. What's typed in the box is read by Parse and populate as you type, with the task's own dates known, so "3 hours
a week" becomes a total over its Start to Due. What it reads fills the fields, tinted, each with a chip that unticks it;
what's typed in the box itself is never kept. Saving is an edit, as Edit task's is (``edits.edit_task``): status log
lines as "Browse tool", no capture.

Decision 143: hours that name no role ("3 hours a week") go to the assignees when there are any, as planning mostly sizes
the work rather than the lead's time. Hours that name one ("lead hours 4", "4 hours as lead") stay where they say.

The window (``docrepo/ui/quick_edit.py``) only draws what this module works out.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from docrepo import timeline
from docrepo.model import Model, Task
from docrepo.parse import EVENT_WORDS, ROLE_HOURS_RE, Known, ParsePerson, Who, parse_capture, work_weeks

#: The fields Quick edit has, in the order its chips are listed.
KEYS = ("start", "due", "deadline", "deadline_desc", "recurrence", "leads", "assignees", "lead_hours", "assignee_hours", "plant_event")
#: A field's name, as a chip, the window and its messages say it.
NAMES = {"start": "Start", "due": "Due", "deadline": "Deadline", "deadline_desc": "Deadline description", "recurrence": "Repeats",
         "leads": "Lead", "assignees": "Assignee", "lead_hours": "Lead hours", "assignee_hours": "Assignee hours",
         "plant_event": "Plant event"}
#: Words in an hours phrase's clause that name the lead's hours outright, as Parse and populate's clause rule reads them.
LEAD_NAMED = re.compile(r"\bfor\s+(?:the\s+)?lead\b|\blead(?:['’]s)?\s+(?:hours|time|load|effort)\b|\bas\s+(?:the\s+)?lead\b", re.I)
#: How Parse and populate explains a rate made a total over a span of dates: "3 h a week for 6 weeks, 12 Oct to 20 Nov".
RATE_CALC = re.compile(r"^[\d.]+ h a \w+ for [\d.]+ weeks?, .+ to .+$")


@dataclass
class Values:
    """Quick edit's fields. Dates are YYYY-MM-DD (or what was typed, until it's a date), empty for none; people are IDs."""

    start: str = ""
    due: str = ""
    deadline: str = ""
    deadline_desc: str = ""
    recurrence: str = ""
    leads: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    lead_hours: float | None = None
    assignee_hours: float | None = None
    plant_event: bool = False

    def copy(self) -> Values:
        return replace(self, leads=list(self.leads), assignees=list(self.assignees))


def values_of(t: Task) -> Values:
    """A task's fields as Quick edit shows them. A Start that isn't set stays empty (the task starts the day it was made)."""
    return Values(t.start or "", t.due or "", t.deadline or "", t.deadline_desc or "", t.recurrence or "", list(t.leads),
                  list(t.assignees), t.lead_hours, t.assignee_hours, bool(t.plant_event))


@dataclass(frozen=True)
class Chip:
    """One thing the box read, with the phrase it came from. ``why`` says why it didn't fill its field; ``off`` that it
    was unticked (or its field changed by hand), so the field keeps its own value."""

    key: str
    field: str
    value: str
    source: str
    calc: str = ""
    why: str = ""
    off: bool = False

    def text(self) -> str:
        return f"{self.field}: {self.value}"

    def tip(self) -> str:
        parts = [f'From "{self.source}"' + (f": {self.calc}" if self.calc else "")]
        if self.why:
            parts.append(self.why)
        elif self.off:
            parts.append("Not filled. Click to fill it again.")
        else:
            parts.append("Click to leave this field as it was.")
        return ". ".join(parts)


@dataclass
class Reading:
    """What the box read: each field's value (``fills``, only the fields it read) and the chips that say so."""

    fills: dict[str, Any] = field(default_factory=dict)
    chips: list[Chip] = field(default_factory=list)


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _names_lead(text: str, source: str) -> bool:
    """Whether an hours phrase, or the clause it's in, names the lead's hours outright ("lead hours 4", "4 h as lead")."""
    m = ROLE_HOURS_RE.search(source)
    if m and m.group(1).lower() == "lead":
        return True
    at = text.lower().find(source.lower())
    if at < 0:
        return bool(LEAD_NAMED.search(source))
    a = max(text.rfind(c, 0, at) for c in ".;!?\n") + 1
    ends = [i for i in (text.find(c, at + len(source)) for c in ".;!?\n") if i >= 0]
    return bool(LEAD_NAMED.search(text[a:min(ends) if ends else len(text)]))


def read(text: str, base: Values, task: Task, people: Sequence[ParsePerson], today: date,
         events: Sequence[str] = EVENT_WORDS, off: frozenset[str] | set[str] = frozenset()) -> Reading:
    """Read the box with Parse and populate. ``base`` is what the fields hold without the box: its dates are the known
    ones a rate of hours is turned into a total over (an empty Start is the day the task was made). ``off`` are the
    fields the box doesn't fill any more; their chips still show, unticked."""
    out = Reading()
    if not text.strip():
        return out
    start = _day(base.start) or _day((task.created or "")[:10])
    known = Known(start, _day(base.due), _day(base.deadline), base.recurrence)
    r = parse_capture(text, "new_task", today, people, [], events, known)
    # A name not on the people list is left out of the fields; its own chip says why, below.
    found = [f for f in r.found if f.key in KEYS and not (f.key in ("leads", "assignees") and f.value.endswith("(new)"))]
    fills: dict[str, Any] = {}
    for key in ("start", "due", "deadline"):
        if getattr(r, key):
            fills[key] = _iso(getattr(r, key))
    if r.deadline_desc:
        fills["deadline_desc"] = r.deadline_desc
    if r.recurrence:
        fills["recurrence"] = r.recurrence
    for key in ("leads", "assignees"):
        known_ids = [w.id for w in getattr(r, key) if w.id]
        if known_ids:
            fills[key] = known_ids
    for key in ("lead_hours", "assignee_hours"):
        if getattr(r, key):
            fills[key] = float(getattr(r, key))
    if r.plant_event:
        fills["plant_event"] = True
    # A rate is a total over the dates the fields will hold: with a date the box read unticked, over the field's own.
    if off & {"start", "due", "deadline"}:
        dates = {k: getattr(base, k) if k in off else fills.get(k) or getattr(base, k) for k in ("start", "due", "deadline")}
        again = Known(_day(dates["start"]) or start, _day(dates["due"]), _day(dates["deadline"]), fills.get("recurrence", base.recurrence))
        for i, f in enumerate(found):
            if f.key in ("lead_hours", "assignee_hours") and f.key in fills and RATE_CALC.match(f.calc):
                rr = parse_capture(f.source, "new_task", today, [], [], events, again)
                hours = next((x for x in rr.found if x.key in ("lead_hours", "assignee_hours")), None)
                if hours is not None and not hours.why:
                    fills[f.key] = float(rr.lead_hours or rr.assignee_hours)
                    found[i] = replace(f, value=hours.value, calc=hours.calc)
    # Decision 143: hours that name no role go to the assignees, when there are any and their own hours weren't read.
    assignees = fills.get("assignees") if "assignees" not in off else None
    if "lead_hours" in fills and "assignee_hours" not in fills and (assignees or base.assignees):
        source = next((f for f in found if f.key == "lead_hours"), None)
        if source is not None and not _names_lead(text, source.source):
            fills["assignee_hours"] = fills.pop("lead_hours")
            found = [replace(f, key="assignee_hours", field=NAMES["assignee_hours"],
                             calc=(f.calc + "; " if f.calc else "") + "each assignee's, as no role was named") if f is source else f
                     for f in found]
    chips: list[Chip] = []
    for f in found:
        chip = Chip(f.key, f.field, f.value, f.source, f.calc, f.why, f.key in off and not f.why)
        same = next((i for i, c in enumerate(chips) if c.key == f.key and not c.why and not f.why), None)
        if same is not None and f.key in ("leads", "assignees"):  # one chip for each role, its people listed
            c = chips[same]
            chips[same] = replace(c, field=NAMES["assignees"] + "s" if f.key == "assignees" else c.field,
                                  value=f"{c.value}, {f.value}", source=f"{c.source}; {f.source}")
        else:
            chips.append(chip)
    # A name that isn't on the people list can't be added here: its chip says so.
    for key in ("leads", "assignees"):
        for w in getattr(r, key):
            if w.is_new:
                chips.append(Chip(key, NAMES[key], w.name, w.name, why="Not on the people list. Add them in Edit task, or "
                                  "to the people list first"))
    out.fills = {k: v for k, v in fills.items() if k not in off}
    out.chips = sorted(chips, key=lambda c: KEYS.index(c.key))
    return out


def shown(base: Values, reading: Reading) -> Values:
    """The fields as the window shows them: the box's values over the base."""
    v = base.copy()
    for key, value in reading.fills.items():
        setattr(v, key, list(value) if isinstance(value, list) else value)
    return v


def total_hours(v: Values) -> float:
    """The task's whole work, as Capacity counts it: the lead hours for each lead, the assignee hours for each assignee."""
    return (v.lead_hours or 0) * len(v.leads) + (v.assignee_hours or 0) * len(v.assignees)


def hours_text(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}".rstrip("0").rstrip(".")


def total_text(v: Values, task: Task) -> str:
    """The line under the people: the total, and about how much a week over the task's workdays (a routine task's are
    for each time it comes round)."""
    total = total_hours(v)
    if not total:
        return "No hours yet: its bar on the timeline stays blank."
    if v.recurrence:
        return f"{hours_text(total)} h each time"
    start, end = _day(v.start) or _day((task.created or "")[:10]), _day(v.due) or _day(v.deadline)
    if start and end and end >= start:
        return f"{hours_text(total)} h in all · about {hours_text(round(total / work_weeks(start, end), 1))} h a week"
    return f"{hours_text(total)} h in all"


def during(model: Model, v: Values, today: date, task_id: str) -> str:
    """The line naming the plant events the dates fall in (release 5.9), the task's own left out."""
    return timeline.during_text(model, [("Start", v.start or None), ("Due", v.due or None), ("Deadline", v.deadline or None)], today, task_id)


def problem(v: Values) -> str | None:
    """What stops a save, if anything: a date that isn't one, or Due before Start."""
    for key in ("start", "due", "deadline"):
        if getattr(v, key) and _day(getattr(v, key)) is None:
            return f"{NAMES[key]} isn't a date. Use YYYY-MM-DD."
    if v.start and v.due and v.due < v.start:
        return "Due is before Start."
    for key in ("lead_hours", "assignee_hours"):
        x = getattr(v, key)
        if x is not None and x < 0:
            return f"{NAMES[key]} can't be less than nothing."
    return None


def edit_values(v: Values) -> dict[str, Any]:
    """The fields as ``edits.edit_task`` takes them."""
    return {"start": v.start or None, "due": v.due or None, "deadline": v.deadline or None, "deadline_desc": v.deadline_desc,
            "recurrence": v.recurrence or None, "leads": [Who(p) for p in v.leads], "assignees": [Who(p) for p in v.assignees],
            "lead_hours": v.lead_hours, "assignee_hours": v.assignee_hours, "plant_event": v.plant_event}
