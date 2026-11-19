"""The generated pages: each task's ``Tasks\\<id>\\Task.md`` and the data root's ``Contents.md``.

They're one-way printouts of docs.db for reading outside DocRepo, in VS Code's
Markdown preview or from a restored backup. DocRepo never reads them back. Links
are relative, so they work wherever the data root is. The formats are those in
the mockup's ``examples.md``, with each task's notes page (release 5.25) printed under Notes, and its raw text log
listed as Captures. Since release 5.124 a task's page has its decision register under Decisions (``docrepo.decisions``):
the decisions on it and the tasks under it, newest first, as a table of Date, Decision, Task and Where, each decision a
link to its capture.md, for agents and the handover pack. Since release 5.140 it lists its meetings under Meetings
(``docrepo.meeting_rows``): every meeting under it, or whose notes made, named or decided something on it or a task under
it, newest first, as a table of Date, Meeting and What it did here, so an agent finds where each task was talked about.

Since release 5.153 the glossary of tagged labels has a page too, ``Views\\Tagged labels.md`` (``tagged_page``; the design
workspace's ``docs/mods/tagged-labels-page-plan.md``, decisions 671 to 677): every tag DocRepo knows with its name and the
other ways it's written, so an agent that meets "P-204A" in a page can look up what it is. ``Contents.md`` points to it,
and a task page's Tagged labels row names each tag's equipment.

Since release 5.169 the stock headings have one, ``Views\\Stock headings.md`` (``write_stock_page``; the design
workspace's ``docs/mods/stock-headings-plan.md``, decision 792): each, its level and what belongs under it, so an agent
reading a task's notes knows what "Path forward" is meant to hold. ``Contents.md`` points to it.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from docrepo import decisions, meeting_rows, repeats, stock_headings, tagged, ties
from docrepo.dates import day_diff, days_text, minutes, to_date
from docrepo.links import reference_link
from docrepo.model import PRIORITY_NAMES, TODAY, TYPE_NAMES, Capture, FileEntry, Model, StatusEntry, Task, is_person
from docrepo.safe_fs import SafeFS
from docrepo.schedule import due_of, is_open, start_of
from docrepo.task_links import links_of

CONTENTS_FILE = "Contents.md"
TASK_FILE = "Task.md"
#: The tagged labels page (release 5.153, decision 671), in the folder the agent views will fill (K9a).
TAGGED_PAGE = ("Views", "Tagged labels.md")
#: The stock headings page (release 5.169, the stock headings plan's decision 792), beside it.
STOCK_PAGE = ("Views", "Stock headings.md")
_GENERATED = "> Generated from docs.db on "


def task_dir(task_id: str) -> list[str]:
    return ["Tasks", task_id]


def capture_dir(c: Capture) -> list[str]:
    return ["Captures", c.saved[:4], c.saved[5:7], c.id]


def rel_link(from_dir: list[str], to: list[str]) -> str:
    """A relative link from a folder to a file, each given as path parts from the data root, encoded as VS Code follows it."""
    i = 0
    while i < len(from_dir) and i < len(to) - 1 and from_dir[i] == to[i]:
        i += 1
    parts = [".."] * (len(from_dir) - i) + to[i:]
    return "/".join(quote(p, safe="!*'") for p in parts)


def num(value: float) -> str:
    """A number as people write it: 8, 1.5."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _text(value: str) -> str:
    """Link text with its brackets escaped."""
    return value.replace("[", "\\[").replace("]", "\\]")


def _cell(value: str) -> str:
    """A table cell with its pipes escaped."""
    return value.replace("|", "\\|")


def _one_line(value: str) -> str:
    """Text on one line: its line breaks and runs of spaces as one space."""
    return " ".join(value.split())


def _tag_words(lb: tagged.Label, n: int) -> str:
    """A tag in a task page's Tagged labels row (decision 675): "P-204A Reactor feed pump A (3)", its name after it."""
    name = _one_line(lb.description)
    return f"{lb.label} {name} ({n})" if name else f"{lb.label} ({n})"


def _value(value: str | None) -> str:
    return "None" if value is None or value == "" else value


class Pages:
    """Builds the page texts from a Model, as of ``today``."""

    def __init__(self, model: Model, today: date, generated_at: datetime, reference_links: Mapping[str, str] | None = None,
                 content_of: Callable[[str], str | None] | None = None, stock: Iterable[stock_headings.StockHeading] = ()) -> None:
        self.m = model
        self.today = today
        self.generated = generated_at.strftime("%Y-%m-%d %H:%M")
        #: Settings' link address for each reference field (release 5.67, round 6's decision 320).
        self.reference_links = dict(reference_links or {})
        #: Reads a capture's content text, for a decision's words (release 5.124); without it, a decision is its title.
        self.content_of = content_of
        #: Settings' stock headings (release 5.169), which Contents.md names, pointing to their page (decision 792).
        self.stock = list(stock)

    # ---- links ----
    def _task_link(self, from_dir: list[str], task_id: str) -> str:
        return f"[{_text(self.m.task(task_id).title)}]({rel_link(from_dir, [*task_dir(task_id), TASK_FILE])})"

    def _ref_link(self, from_dir: list[str], ref: str) -> str:
        """A link to what a log entry came from: a capture or a document. Anything else (Browse tool) is plain text."""
        if ref in self.m.captures:
            return f"[{ref}]({rel_link(from_dir, [*capture_dir(self.m.captures[ref]), 'capture.md'])})"
        if ref in self.m.documents:
            return f"[{ref}]({rel_link(from_dir, ['Documents', ref, 'extracted.txt'])})"
        return ref

    def _names(self, person_ids: list[str], hours: float | None = None, task: Task | None = None, role: str = "") -> str:
        """Names, each with the role's hours when they're set: "Tom Becker (60 h), Mike Ortiz (15 h, 25%)". Hours are each
        person's own, by their Involvement (release 5.47)."""
        def own(p: str) -> str:
            share = task.share(role, p) if task else 100
            parts = ([f"{num(round(hours * share / 100, 2))} h"] if hours else []) + ([f"{share}%"] if share != 100 else [])
            return f" ({', '.join(parts)})" if parts else ""

        return ", ".join(self.m.person_name(p) + own(p) for p in person_ids) or "None"

    # ---- Task.md ----
    def task_page(self, t: Task) -> str:
        here = task_dir(t.id)

        def link(task_id: str) -> str:
            return self._task_link(here, task_id)

        out = [f"# {t.title}", "", f"{_GENERATED}{self.generated}. Don't edit: DocRepo rewrites this page. Change the task in the browse tool.", ""]
        rows = [("ID", t.id), ("State", t.state + (f" ({t.closed})" if t.closed else ""))]
        if t.priority:  # release 5.23
            rows.append(("Priority", PRIORITY_NAMES.get(t.priority, t.priority)))
        if t.discarded:
            rows.append(("Discarded", f"{t.discarded[:10]}: {t.discard_reason}" if t.discard_reason else t.discarded[:10]))
        if t.urgent:
            rows.append(("Urgent", "Yes"))
        if t.meeting:
            rows.append(("Meeting", "Yes"))
        if t.plant_event:  # release 5.9, mods log round 2, M0028
            rows.append(("Plant event", "Yes"))
        if t.recurrence:
            rows.append(("Recurrence", t.recurrence + (f" until {t.repeat_until}" if t.repeat_until else ", no end date")))
        origin = self.m.origins.get(t.id)
        if origin:  # release 5.44: the template it came from
            rows.append(("From template", origin.words()))
        rows += [
            ("Parents", ", ".join(link(p) for p in self.m.parents_of(t.id)) or "None (top-level task)"),
            ("Labels", ", ".join(name + (" (inherited)" if inherited else "") for name, inherited in self.m.labels_of(t.id)) or "None"),
            ("Lead", self._names(t.leads, t.lead_hours, t, "lead")),
            ("Assignees", self._names(t.assignees, t.assignee_hours, t, "assignee")),
            ("Start", start_of(t).isoformat()),
            ("Due", f"{t.due} ({days_text(to_date(t.due), self.today)})" if t.due else "None"),
            ("Deadline", (f"{t.deadline}, {t.deadline_desc}" if t.deadline_desc else t.deadline) if t.deadline else "None"),
        ]
        if self.m.tagged:  # release 5.79 (decision 367): once there's a glossary, after Labels
            tags = tagged.task_tags(self.m, t.id)
            at = next(i for i, (k, _) in enumerate(rows) if k == "Labels") + 1
            rows.insert(at, ("Tagged labels", "; ".join(_tag_words(lb, n) for lb, n in tags) or "None found"))
        if t.duration:  # release 5.46
            rows.append(("Duration", f"{t.duration} day{'' if t.duration == 1 else 's'}, through weekends" if t.calendar_days else f"{t.duration} workday{'' if t.duration == 1 else 's'}"))
        for f, tie in t.ties.items():  # release 5.50
            rows.append((f"{ties.FIELDS[f]} tied", ties.words(tie, ties.name_in(self.m, tie))))
        tied = self.m.tied_to(t.id)
        if tied:
            rows.append(("Tied to this", ", ".join(link(x.id) for x in tied)))
        if t.reminder:
            rows.append(("Reminder", t.reminder))
        if t.reminder_repeat:  # release 5.117, decision 416
            rows.append(("Reminder repeats", repeats.describe(t.reminder_repeat) + (f", until {t.reminder_until}" if t.reminder_until else "")))
        if t.reviewed or t.review_every is not None:  # release 5.128 (the weekly review, decisions 498 and 499)
            every = {None: "", 0: "never reviewed", 1: "every week"}.get(t.review_every, f"every {t.review_every} weeks")
            rows.append(("Reviewed", ", ".join(x for x in (t.reviewed[:10] if t.reviewed else "", every) if x)))
        for name, value in t.references.items():  # its reference fields (release 5.9, M0034), as links when they have one (5.67)
            address = reference_link(self.reference_links.get(name), value)
            rows.append((name, f"[{_text(value)}]({address})" if address else value))
        on = self.m.agendas_on(t.id)
        if on:
            rows.append(("On agendas", ", ".join(self._target(here, a.target) for a in on)))
        out += ["| Field | Value |", "|---|---|", *[f"| {a} | {_cell(b)} |" for a, b in rows], ""]
        kds = self.m.key_dates_of(t.id)
        if kds:  # release 5.31: its key dates, in its order, with their ticks
            from docrepo.key_dates import when_text

            out += ["## Key dates", "", "| Dates | Description | Marks |", "|---|---|---|"]
            for kd in kds:
                marks = ", ".join(x for x, on in (("Plant activity", kd.plant), ("Deadline", kd.deadline), (f"Done {kd.done}", kd.done)) if on)
                out.append(f"| {_cell(when_text(kd, self.today))} | {_cell(kd.description) or '–'} | {_cell(marks) or '–'} |")
            out.append("")
        out += ["## Description", "", t.description or "_None._", "", "## Current status", "", t.current_status or "_No status yet._", ""]
        # The notes page (release 5.25): its headings two levels down, each caption a link to its capture.
        from docrepo import notes_page

        page = self.m.pages.get(t.id, "")

        def capture_link(capture_id: str) -> str | None:
            c = self.m.captures.get(capture_id)
            return rel_link(here, [*capture_dir(c), "capture.md"]) if c else None

        def document_link(document_id: str) -> str | None:
            """A picture's or attachment's file, when it's DocRepo's: its saved file in a Files folder (release 5.145,
            decision 629), in the task's Files folder (pasted there), or in its capture's attachments folder."""
            d = self.m.documents.get(document_id)
            if d is None:
                return None
            saved = self.m.saved_of(document_id)
            if saved:
                return rel_link(here, ["Tasks", saved[0].task, "Files", saved[0].name])
            if d.capture and d.capture in self.m.captures:
                return rel_link(here, [*capture_dir(self.m.captures[d.capture]), "attachments", d.name])
            parts = Path(d.original or "").parts
            if len(parts) >= 3 and parts[-2] == "Files" and parts[-3] == t.id:
                return rel_link(here, [*here, "Files", d.name])
            return None

        def task_link(task_id: str) -> str | None:
            """The path to a task's Task.md, which ``task_md`` makes a link of (a whole link here, from release 5.83 to
            5.142, printed task lines as a link inside a link)."""
            return rel_link(here, [*task_dir(task_id), TASK_FILE]) if task_id in self.m.tasks else None

        out += ["## Notes", "", *(notes_page.task_md(page, capture_link, document_link, task_link, t.id) or ["_No notes yet._"]), ""]
        on_page = notes_page.on_page(self.m, t.id, page)
        kids = self.m.children_of(t.id)
        if kids:
            out += ["## Subtasks", "", "| ID | Title | State | Assignees | Due |", "|---|---|---|---|---|"]
            for k in kids:
                c = self.m.task(k)
                out.append(f"| {c.id} | {_cell(link(k))} | {c.state} | {_cell(self._names(c.assignees))} | {c.due or ''} |")
            out.append("")
        out += self._meetings(here, t)
        out += self._decisions(here, t)
        items = self.m.open_items_for(t.id)
        if items or (t.meeting and is_open(t)):
            lines = [f"- {self._agenda_text(here, a.subject, a.note)} · added {a.added[:10]}" for a in items]
            out += ["## Agenda", "", *(lines or ["_No open agenda items._"]), ""]
        log = sorted(self.m.status_log_of(t.id), key=lambda e: e.at, reverse=True)
        out += ["## Status log", "", *([self._status_line(here, e) for e in log] or ["_No changes yet._"]), ""]
        summaries = list(reversed(self.m.summaries_of(t.id)))
        out += ["## Summary log", ""]
        out += [line for s in summaries for line in (f"### {minutes(s.at)} · {s.type} · {self._ref_link(here, s.via)}", "", s.text, "")] or ["_No summaries yet._", ""]
        raw = []
        for e in reversed(self.m.raw_log_of(t.id)):
            if e.capture:
                types = ", ".join(TYPE_NAMES[k] for k in e.capture.types) or "None"
                raw.append(f"- {minutes(e.at)} · {self._ref_link(here, e.capture.id)} · {types} · {e.capture.title}"
                           + ("" if e.capture.id in on_page else " · not on the notes page"))
            else:
                raw.append(f"- {minutes(e.at)} · {self._ref_link(here, e.version.document)} · Document version · {self.m.documents[e.version.document].name} changed")
        out += ["## Captures", "", *(raw or ["_None._"]), ""]
        # The Task view's pinned files (release 5.35, decision 160): its key documents, first under Files.
        pinned = [self.m.documents[d].name for d in self.m.pins.get(t.id, []) if d in self.m.documents]
        key_docs = [f"Key documents: {', '.join(pinned)}", ""] if pinned else []
        out += ["## Files", "", *key_docs, *([self._file_line(here, f) for f in self.m.files_of(t.id)] or ["_None._"]), ""]
        # Its links in one place (release 5.67, decision 316), each a Markdown link, when it has any.
        found = links_of(self.m, t.id, self.reference_links)
        if found:
            out += ["## Links", "", *[f"- [{_text(x.name)}]({_link_target(x.address) if x.kind == 'folder' else x.address})" for x in found], ""]
        return "\n".join(out)

    def _meetings(self, here: list[str], t: Task) -> list[str]:
        """The task page's Meetings section as a table (release 5.140, the notes consolidation plan's decision 608): each
        meeting a link to its Task.md, newest first, with what it did here. Nothing when there are none. The words stay on
        the pages they're on: All notes isn't printed, so every word is in one Task.md."""
        found = meeting_rows.rows(self.m, t.id)
        if not found:
            return []
        out = ["## Meetings", "", "| Date | Meeting | What it did here |", "|---|---|---|"]
        for r in found:
            out.append(f"| {r.day} | {_cell(self._task_link(here, r.meeting))} | {_cell(meeting_rows.words(self.m, r, t.id, self.content_of))} |")
        return [*out, ""]

    def _decisions(self, here: list[str], t: Task) -> list[str]:
        """The decision register (release 5.124, decision 479): the decisions on the task and the tasks under it, newest
        first, as the task page's Decisions section has them and its Copy puts them, each decision a link to its
        capture.md and each task to its Task.md. Nothing when there are none."""
        found = decisions.of_tasks(self.m, [t.id, *self.m.descendants_of(t.id)], self.content_of)
        if not found:
            return []
        out = ["## Decisions", "", "| " + " | ".join(decisions.COLUMNS) + " |", "|" + "---|" * len(decisions.COLUMNS)]
        for d in found:
            words = " ".join(d.words.split())
            c = self.m.captures[d.capture]
            decided = f"[{_text(words)}]({rel_link(here, [*capture_dir(c), 'capture.md'])})"
            out.append(f"| {d.day} | {_cell(decided)} | {_cell(self._task_link(here, d.task))} | {_cell(d.where(self.today))} |")
        return [*out, ""]

    def _target(self, here: list[str], target: str) -> str:
        if target == TODAY:
            return "Today"
        return self.m.person_name(target) if is_person(target) else self._task_link(here, target)

    def _agenda_text(self, here: list[str], subject: str | None, note: str) -> str:
        if not subject:
            return note
        return self._task_link(here, subject) + (f" · {note}" if note else "")

    def _status_line(self, here: list[str], e: StatusEntry) -> str:
        # A value with line breaks, such as an edited description, stays on the entry's one line.
        return (f"- {minutes(e.at)} · {e.field}: {' '.join(_value(e.from_value).split())} → {' '.join(_value(e.to_value).split())}"
                f" · {self._ref_link(here, e.via)}")

    def _file_line(self, here: list[str], f: FileEntry) -> str:
        d = self.m.documents[f.document]
        text_link = f"[text]({rel_link(here, ['Documents', d.id, 'extracted.txt'])})"
        if f.kind in ("Saved file", "Old version"):
            path = ["Files", "_old versions", f.name] if f.kind == "Old version" else ["Files", f.name]
            return f"- {f.kind}: [{_text(f.name)}]({rel_link(here, [*here, *path])}) · {d.id}"
        if f.kind == "Linked file":  # release 5.145, decision 631: read where it is
            return f"- Linked file: `{d.original}` · {d.id} · {text_link}"
        if f.kind == "Link":  # as code, not a Markdown link: DocRepo's pages never open a link (round 1 plan, decision 5)
            return f"- Link: {_text(f.name)} · `{d.original}` · {d.id}"
        if f.kind == "Folder":  # release 5.66: where it is, with no text
            return f"- Folder: `{d.original}` · {d.id}"
        capture = self.m.captures[d.capture]
        return f"- Email attachment: [{_text(f.name)}]({rel_link(here, [*capture_dir(capture), 'attachments', f.name])}) · {d.id} · {text_link}"

    # ---- Contents.md ----
    def contents_page(self) -> str:
        m = self.m

        def link(task_id: str) -> str:
            return self._task_link([], task_id)

        out = ["# DocRepo contents", "",
               f"{_GENERATED}{self.generated}. Don't edit: DocRepo rewrites this page. In VS Code, press Ctrl+Shift+V to preview it and follow the links.",
               ""]
        if m.tagged:  # release 5.153 (decision 674): where to look a tag up
            out += [f"Tagged labels: {tagged_counts(m.tagged)}. Look a tag up in [Views\\Tagged labels.md]({rel_link([], list(TAGGED_PAGE))}).", ""]
        if self.stock:  # release 5.169 (decision 792): what a task's stock headings are meant to hold
            names = [_text(h.name) for h in self.stock]
            listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
            out += [f"Stock headings: {listed}. What belongs under each is in [Views\\Stock headings.md]({rel_link([], list(STOCK_PAGE))}).", ""]
        out += ["## Open tasks", ""]

        def add(task_id: str, depth: int, via: str | None) -> None:
            t = m.task(task_id)
            bits = [t.id, t.state]
            if t.recurrence:
                bits.append(t.recurrence)
            if t.meeting:
                bits.append("meeting")
            due = due_of(t, self.today)
            if due:
                bits.append(f"{due.label.lower()} {due.date.isoformat()}")
            if t.urgent:
                bits.append("urgent")
            others = [p for p in m.parents_of(task_id) if p != via] if via else []
            also = f" · also under {', '.join(m.task(o).title for o in others)}" if others else ""
            out.append(f"{'  ' * depth}- {link(task_id)} · {' · '.join(bits)}{also}")
            for k in m.children_of(task_id):
                if is_open(m.task(k)):
                    add(k, depth + 1, task_id)

        for t in m.top_level():
            if is_open(t):
                add(t.id, 0, None)
        out += ["", "## Parked", "", *[f"- {link(t.id)} · {t.id}" for t in m.tasks.values() if t.state == "Parked" and not t.discarded]]
        recent = [t for t in m.tasks.values() if t.closed and not t.discarded and day_diff(to_date(t.closed), self.today) <= 30]
        out += ["", "## Closed in the last 30 days", "", *[f"- {link(t.id)} · {t.id} · closed {t.closed}" for t in recent]]
        out += ["", "## Agendas", ""]
        # Today (mods log round 1, M0016) comes first, with the day an item was added when it carried over.
        today_items = m.today_items()
        if today_items:
            out += ["### Today", "", *[f"- {self._agenda_text([], a.subject, a.note)}" + (f" · since {a.added[:10]}" if a.added[:10] < self.today.isoformat() else "")
                                      for a in today_items], ""]
        for target in m.agenda_targets():
            items = m.open_items_for(target)
            if not items:
                continue
            when = m.meeting_when(target, self.today)
            head = m.person_name(target) if is_person(target) else link(target)
            out += [f"### {head}" + (f" · next {when}" if when and when != "no date set" else ""), "",
                    *[f"- {self._agenda_text([], a.subject, a.note)}" for a in items], ""]
        unfiled = m.unfiled_captures()
        out += [f"## Unfiled ({len(unfiled)})", "",
                *[f"- [{c.id}]({rel_link([], [*capture_dir(c), 'capture.md'])}) · {minutes(c.saved)} · {c.title}" for c in unfiled]]
        out += ["", "## People", "", "| Name | Aliases | Hours per week |", "|---|---|---|",
                *[f"| {_cell(p.name)} | {_cell(', '.join(p.aliases))} | {num(p.hours) if p.hours is not None else 'Not set'} |" for p in m.active_people()]]
        out += ["", "## Labels", "", "| Label | Keywords |", "|---|---|",
                *[f"| {_cell(m.label_path(label.name))} | {_cell(', '.join(label.keywords))} |" for label in m.active_labels()], ""]  # a sublabel with its parent
        return "\n".join(out)


def _same_apart_from_date(old: str, new: str) -> bool:
    """True when two page texts differ at most in their "Generated from docs.db on" line."""
    def strip(text: str) -> list[str]:
        return [line for line in text.split("\n") if not line.startswith(_GENERATED)]

    return strip(old) == strip(new)


def _write(fs: SafeFS, path: Path, text: str) -> bool:
    """Write a page unless only its generated date would change. Returns True if it was written."""
    if path.exists():
        try:
            if _same_apart_from_date(path.read_text(encoding="utf-8"), text):
                return False
        except (OSError, UnicodeDecodeError):
            pass
    fs.write_text(path, text)
    return True


def _link_target(path: str) -> str:
    """A folder's path as a Markdown link's target: a file: address, so a Markdown preview opens it."""
    try:
        return Path(path.rstrip("\\") or path).as_uri()
    except ValueError:
        return path


def reference_links_of(data_root: Path) -> dict[str, str]:
    """Settings' link addresses for reference fields (release 5.67), for Task.md; none when settings.json can't be read."""
    from docrepo.config import Settings, SettingsError

    try:
        return Settings.load(data_root).reference_links
    except SettingsError:
        return {}


def write_task_page(model: Model, data_root: Path, fs: SafeFS, task_id: str, today: date, generated_at: datetime) -> bool:
    """Write one task's Task.md, as an edit of its notes page does (release 5.25). Says whether it was written."""
    pages = Pages(model, today, generated_at, reference_links_of(data_root), _reader(model, data_root))
    return _write(fs, data_root.joinpath(*task_dir(task_id), TASK_FILE), pages.task_page(model.task(task_id)))


def _reader(model: Model, data_root: Path) -> Callable[[str], str | None]:
    """Reads a capture's content text from its capture.md, each once, for the decisions' words (release 5.124)."""
    from docrepo.captures import read_content

    read: dict[str, str | None] = {}

    def content_of(capture_id: str) -> str | None:
        if capture_id not in read:
            c = model.captures.get(capture_id)
            read[capture_id] = read_content(data_root, c) if c else None
        return read[capture_id]

    return content_of


def pages_touched(m: Model, task_ids: Iterable[str]) -> set[str]:
    """The tasks whose Task.md can show something of these tasks (release 5.90, the review's F5), so a change to them
    rewrites only those pages:

    - the tasks themselves, and the tasks tied to them, and to those, since a move follows its ties;
    - each one's ancestors (a parent's Subtasks table, and the chains) and descendants (inherited labels, and Parents);
    - the tasks it's tied to (Tied to this), its agenda items' targets and subjects, open or closed, and the tasks
      whose notes page holds a task line for it (a task made from those notes);
    - for a meeting, the tasks of the decisions its notes made, and the tasks above them, whose registers name it (release
      5.124); since release 5.140, the tasks of every item its notes made, and the tasks above them, whose Meetings list it.

    Call it on the Model from before a change as well as after, since a move, an untie or a discard takes a link away."""
    seeds = {t for t in task_ids if t in m.tasks}
    tied_by: dict[str, set[str]] = {}
    for t in m.tasks.values():
        for tie in t.ties.values():
            tied_by.setdefault(tie.source, set()).add(t.id)
    frontier = list(seeds)
    while frontier:
        for x in tied_by.get(frontier.pop(), ()):
            if x not in seeds:
                seeds.add(x)
                frontier.append(x)
    out: set[str] = set()
    for t in seeds:
        out.add(t)
        out.update(m.ancestors_of(t))
        out.update(m.descendants_of(t))
        out.update(tie.source for tie in m.tasks[t].ties.values())
        out.update(tied_by.get(t, ()))
    for a in m.agenda:
        if a.subject in seeds and not is_person(a.target) and a.target != TODAY:
            out.add(a.target)
        if a.target in seeds and a.subject:
            out.add(a.subject)
    for c in m.captures.values():  # a task line on the notes page it was made from (release 5.83)
        if c.created_task in seeds and c.from_notes and c.from_notes in m.captures:
            out.update(m.capture_tasks(m.captures[c.from_notes]))
        # A decision's Where names the meeting whose notes it came from (release 5.124): its task's register, and those above;
        # and every item's task, and those above, list the meeting under Meetings (release 5.140, decision 608).
        if c.item in ("task", "note", "update", "decision") and c.from_notes in m.captures and m.captures[c.from_notes].task in seeds:
            for x in [*m.capture_tasks(c), *([c.created_task] if c.created_task else [])]:
                out.add(x)
                out.update(m.ancestors_of(x))
    return {t for t in out if t in m.tasks}


# ---- the tagged labels page (release 5.153) ----
def tagged_counts(tg: tagged.Tagged) -> str:
    """"1,234 in the glossary, 12 new": the glossary's labels, and the suggested ones when there are any."""
    n, new = len(tg.glossary()), len(tg.suggested())
    return f"{n:,} in the glossary" + (f", {new:,} new" if new else "")


def _tagged_table(labels: Iterable[tagged.Label], name: Callable[[tagged.Label], str]) -> list[str]:
    return ["| Tag | Name | Also found as |", "|---|---|---|",
            *[f"| {_cell(_one_line(lb.label))} | {_cell(name(lb))} | {_cell(', '.join(_one_line(x) for x in tagged.found_as(lb)))} |"
              for lb in labels]]


def _tagged_body(tg: tagged.Tagged) -> str:
    """The page below its header (decisions 671 and 672): the count, then the glossary under a heading for each tag's
    letters, then the suggested labels. No counts of mentions, so it changes only when the glossary or the suggestions do."""
    glossary, new = tg.glossary(), tg.suggested()
    out = [f"{tagged_counts(tg)}." if glossary or new else "The glossary is empty: import it in the browse tool's Tagged labels view.", ""]
    groups: dict[str, list[tagged.Label]] = {}
    for lb in glossary:
        groups.setdefault(tagged.letters_of(lb.label), []).append(lb)
    for head in sorted(groups, key=lambda h: (h == "Other", tagged.natural(h))):
        out += [f"## {head}", "", *_tagged_table(groups[head], lambda lb: _one_line(lb.description) or "(no name)"), ""]
    if new:
        out += ["## Found in the text, not in the glossary", "",
                "Tags a tag pattern found that the glossary doesn't have yet. They have no name until the owner adds them to the glossary.", "",
                *_tagged_table(new, lambda lb: "(new, no name yet)"), ""]
    return "\n".join(out)


def tagged_page(tg: tagged.Tagged, generated: str) -> str:
    """``Views\\Tagged labels.md`` (decisions 671, 672 and 677): what it is, that DocRepo writes it, and the glossary. Its
    body is worked out once per version of the glossary (``Tagged.once``), as 20,000 labels make a page of over 1 MB."""
    head = ["# Tagged labels", "",
            f"{_GENERATED}{generated}. Don't edit: DocRepo rewrites this page when the glossary changes. Change the glossary in the browse "
            "tool's Tagged labels view.", "",
            "The plant's tags DocRepo knows, from the owner's glossary of tagged labels: each tag, its name (the equipment or instrument "
            "it is), and the other ways it's written. Look a tag up here written any way: V-110, V110 and V 110 are one tag. "
            "The names are text from the owner's list, kept as data.", ""]
    return "\n".join(head) + "\n" + str(tg.once("page", lambda: _tagged_body(tg)))


#: The tagged labels page's body last written to each path in this run, so a save doesn't read a page of 1 MB again to
#: find it unchanged (release 5.153). It's the body's own object, worked out once per glossary version.
_tagged_written: dict[Path, object] = {}


def write_tagged_page(model: Model, data_root: Path, fs: SafeFS, generated_at: datetime) -> bool:
    """Write ``Views\\Tagged labels.md`` when its text changed (decision 673). With no glossary and no page yet there's
    none; a page left from a glossary since emptied says so, as DocRepo deletes nothing."""
    path = data_root.joinpath(*TAGGED_PAGE)
    tg = model.tagged
    if not tg and not path.exists():
        return False
    body = tg.once("page", lambda: _tagged_body(tg))
    if _tagged_written.get(path) is body and path.exists():
        return False
    wrote = _write(fs, path, tagged_page(tg, generated_at.strftime("%Y-%m-%d %H:%M")))
    _tagged_written[path] = body
    return wrote


def stock_of_root(data_root: Path) -> list[stock_headings.StockHeading]:
    """Settings' stock headings (release 5.169); the defaults when settings.json can't be read."""
    from docrepo.config import Settings, SettingsError

    try:
        return Settings.load(data_root).stock()
    except SettingsError:
        return list(stock_headings.DEFAULTS)


def write_stock_page(data_root: Path, fs: SafeFS, stock: Iterable[stock_headings.StockHeading]) -> bool:
    """Write ``Views\\Stock headings.md`` when its text changed (decision 792): it has no date, so it's written once per
    change of the setting, and once on a data root that hasn't got it."""
    return _write(fs, data_root.joinpath(*STOCK_PAGE), stock_headings.page(stock))


def write_pages(
    model: Model, data_root: Path, fs: SafeFS, today: date, generated_at: datetime, task_ids: Iterable[str] | None = None
) -> int:
    """Write Task.md for every task (or only ``task_ids``) and Contents.md. Returns how many files were written. Contents.md
    is one page listing every task: it's made each time, and written only when its text changed, as every page is. So are
    the agents' pages beside it: the tagged labels' (release 5.153) and the stock headings' (release 5.169)."""
    stock = stock_of_root(data_root)
    pages = Pages(model, today, generated_at, reference_links_of(data_root), _reader(model, data_root), stock)
    ids = list(model.tasks) if task_ids is None else [i for i in task_ids if i in model.tasks]
    if task_ids is None:  # release 5.160 (decision 734): every page's tagged labels, read in one pass rather than task by task
        model.tagged.read_all()
    written = 0
    for task_id in ids:
        written += _write(fs, data_root.joinpath(*task_dir(task_id), TASK_FILE), pages.task_page(model.task(task_id)))
    written += _write(fs, data_root / CONTENTS_FILE, pages.contents_page())
    written += write_tagged_page(model, data_root, fs, generated_at)
    written += write_stock_page(data_root, fs, stock)
    return written
