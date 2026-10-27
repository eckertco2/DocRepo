"""The generated pages: each task's ``Tasks\\<id>\\Task.md`` and the data root's ``Contents.md``.

They're one-way printouts of docs.db for reading outside DocRepo, in VS Code's
Markdown preview or from a restored backup. DocRepo never reads them back. Links
are relative, so they work wherever the data root is. The formats are those in
the mockup's ``examples.md``, with each task's notes page (release 5.25) printed under Notes, and its raw text log
listed as Captures.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from docrepo.dates import day_diff, days_text, minutes, to_date
from docrepo.model import PRIORITY_NAMES, TODAY, TYPE_NAMES, Capture, FileEntry, Model, StatusEntry, Task, is_person
from docrepo.safe_fs import SafeFS
from docrepo.schedule import due_of, is_open, start_of

CONTENTS_FILE = "Contents.md"
TASK_FILE = "Task.md"
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


def _value(value: str | None) -> str:
    return "None" if value is None or value == "" else value


class Pages:
    """Builds the page texts from a Model, as of ``today``."""

    def __init__(self, model: Model, today: date, generated_at: datetime) -> None:
        self.m = model
        self.today = today
        self.generated = generated_at.strftime("%Y-%m-%d %H:%M")

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

    def _names(self, person_ids: list[str], hours: float | None = None) -> str:
        """Names, each with the role's hours when they're set: "Tom Becker (60 h), Mike Ortiz (60 h)"."""
        text = ", ".join(self.m.person_name(p) + (f" ({num(hours)} h)" if hours else "") for p in person_ids)
        return text or "None"

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
        rows += [
            ("Parents", ", ".join(link(p) for p in self.m.parents_of(t.id)) or "None (top-level task)"),
            ("Labels", ", ".join(name + (" (inherited)" if inherited else "") for name, inherited in self.m.labels_of(t.id)) or "None"),
            ("Lead", self._names(t.leads, t.lead_hours)),
            ("Assignees", self._names(t.assignees, t.assignee_hours)),
            ("Start", start_of(t).isoformat()),
            ("Due", f"{t.due} ({days_text(to_date(t.due), self.today)})" if t.due else "None"),
            ("Deadline", (f"{t.deadline}, {t.deadline_desc}" if t.deadline_desc else t.deadline) if t.deadline else "None"),
        ]
        if t.reminder:
            rows.append(("Reminder", t.reminder))
        rows += list(t.references.items())  # its reference fields (release 5.9, M0034)
        on = self.m.agendas_on(t.id)
        if on:
            rows.append(("On agendas", ", ".join(self._target(here, a.target) for a in on)))
        out += ["| Field | Value |", "|---|---|", *[f"| {a} | {_cell(b)} |" for a, b in rows], ""]
        out += ["## Description", "", t.description or "_None._", "", "## Current status", "", t.current_status or "_No status yet._", ""]
        # The notes page (release 5.25): its headings two levels down, each caption a link to its capture.
        from docrepo import notes_page

        page = self.m.pages.get(t.id, "")

        def capture_link(capture_id: str) -> str | None:
            c = self.m.captures.get(capture_id)
            return rel_link(here, [*capture_dir(c), "capture.md"]) if c else None

        def document_link(document_id: str) -> str | None:
            """A picture's or attachment's file, when it's DocRepo's: in the task's Files folder (pasted there) or in its
            capture's attachments folder."""
            d = self.m.documents.get(document_id)
            if d is None:
                return None
            if d.capture and d.capture in self.m.captures:
                return rel_link(here, [*capture_dir(self.m.captures[d.capture]), "attachments", d.name])
            parts = Path(d.original or "").parts
            if len(parts) >= 3 and parts[-2] == "Files" and parts[-3] == t.id:
                return rel_link(here, [*here, "Files", d.name])
            return None

        out += ["## Notes", "", *(notes_page.task_md(page, capture_link, document_link) or ["_No notes yet._"]), ""]
        on_page = notes_page.on_page(self.m, t.id, page)
        kids = self.m.children_of(t.id)
        if kids:
            out += ["## Subtasks", "", "| ID | Title | State | Assignees | Due |", "|---|---|---|---|---|"]
            for k in kids:
                c = self.m.task(k)
                out.append(f"| {c.id} | {_cell(link(k))} | {c.state} | {_cell(self._names(c.assignees))} | {c.due or ''} |")
            out.append("")
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
        out += ["## Files", "", *([self._file_line(here, f) for f in self.m.files_of(t.id)] or ["_None._"]), ""]
        return "\n".join(out)

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
        if f.kind in ("Saved copy", "Old version"):
            path = ["Files", "_old versions", f.name] if f.kind == "Old version" else ["Files", f.name]
            return f"- {f.kind}: [{_text(f.name)}]({rel_link(here, [*here, *path])}) · {d.id}"
        if f.kind == "Tracked original":
            return f"- Tracked original: `{d.original}` · {d.id} · {text_link}"
        if f.kind == "Link":  # as code, not a Markdown link: DocRepo's pages never open a link (round 1 plan, decision 5)
            return f"- Link: {_text(f.name)} · `{d.original}` · {d.id}"
        capture = self.m.captures[d.capture]
        return f"- Email attachment: [{_text(f.name)}]({rel_link(here, [*capture_dir(capture), 'attachments', f.name])}) · {d.id} · {text_link}"

    # ---- Contents.md ----
    def contents_page(self) -> str:
        m = self.m

        def link(task_id: str) -> str:
            return self._task_link([], task_id)

        out = ["# DocRepo contents", "",
               f"{_GENERATED}{self.generated}. Don't edit: DocRepo rewrites this page. In VS Code, press Ctrl+Shift+V to preview it and follow the links.",
               "", "## Open tasks", ""]

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


def write_task_page(model: Model, data_root: Path, fs: SafeFS, task_id: str, today: date, generated_at: datetime) -> bool:
    """Write one task's Task.md, as an edit of its notes page does (release 5.25). Says whether it was written."""
    return _write(fs, data_root.joinpath(*task_dir(task_id), TASK_FILE), Pages(model, today, generated_at).task_page(model.task(task_id)))


def write_pages(
    model: Model, data_root: Path, fs: SafeFS, today: date, generated_at: datetime, task_ids: Iterable[str] | None = None
) -> int:
    """Write Task.md for every task (or only ``task_ids``) and Contents.md. Returns how many files were written."""
    pages = Pages(model, today, generated_at)
    ids = list(model.tasks) if task_ids is None else [i for i in task_ids if i in model.tasks]
    written = 0
    for task_id in ids:
        written += _write(fs, data_root.joinpath(*task_dir(task_id), TASK_FILE), pages.task_page(model.task(task_id)))
    written += _write(fs, data_root / CONTENTS_FILE, pages.contents_page())
    return written
