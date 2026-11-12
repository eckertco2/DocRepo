"""Decisions across projects (release 5.124; the design workspace's ``docs/mods/cold-eyes-plan.md``, section 3, decisions
475 to 480).

A decision is a live capture whose item is ``decision`` (decision 475): a ``**decision,`` line in the capture window makes
one, on its ``#`` task, else on the capture's task or meeting (release 5.8). Nothing new is stored. Decisions are found
three ways, all built from here:

- ``type:decision`` (or ``decisions``) in Search everything (``docrepo.search``, decision 476);
- the task page's Decisions section (``docrepo.detail``, decisions 477 and 478);
- the Decisions table in each Task.md (``docrepo.pages``, decision 479).

Each lists the decisions on a task and the tasks under it, newest first. As a table (Date, Decision, Task, Where) it's the
**decision register**: the section's Copy puts it on the clipboard, in rich text and Markdown, and Task.md prints it.

A ``**decision,`` typed straight onto a notes page makes no item, so it's no decision here; nor is there a sidebar view,
or one decision superseding another (decision 480).
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from html import escape

from docrepo import items, markup
from docrepo.dates import short, to_date
from docrepo.model import Capture, Model

#: How many rows the task page's section shows before Show all (decision 477).
SHOWN = 5
#: The most ``type:decision`` lists with no words (decision 476), as any filter does (``search.SCOPED_LIMIT``).
LIMIT = 200
#: The decision register's columns (decision 479).
COLUMNS = ("Date", "Decision", "Task", "Where")

_OPERATOR = re.compile(r"\*\*decision,\s*", re.I)
#: A ``#`` naming a task, as capture.md keeps one: the register's Task column says which task it's on.
_TASK_REF = re.compile(r"#\[[^\]\n]+\]\(T\d+\)[ \t]*")
#: An ``@`` naming a person, as capture.md keeps one: the person's name, without the @.
_PERSON_REF = re.compile(r"(?:@L\.|@)\[([^\]\n]+)\]\(P\d+\)", re.I)


@dataclass(frozen=True)
class Decision:
    """One decision, as the register lists it."""

    capture: str  # its capture's ID; a click opens it
    saved: str  # when it was saved: "2026-10-13 10:22:05"
    words: str  # its first line, without the operator (decision 478)
    more: str  # all its words, for the row's tooltip, when there's more than the first line
    task: str  # the task it's on: on a task page, the one in the page's tasks
    meeting: str | None = None  # the meeting whose notes it came from
    meeting_name: str = ""  # that meeting's name, without the day a regular meeting's name ends with
    meeting_day: str | None = None  # the meeting's day: its Start, else its Due, else the day of its notes

    @property
    def day(self) -> str:
        return self.saved[:10]

    def where(self, today: date) -> str:
        """Where it was decided: "Business team meeting, 13 Oct"; nothing when it didn't come from a meeting's notes."""
        if not self.meeting_name:
            return ""
        return f"{self.meeting_name}, {short(to_date(self.meeting_day), today)}" if self.meeting_day else self.meeting_name


def is_decision(c: Capture) -> bool:
    """A live capture saved as a decision item (decision 475)."""
    return c.item == "decision" and not c.discarded


def _live_tasks(model: Model, c: Capture) -> list[str]:
    return [t for t in model.capture_tasks(c) if t in model.tasks and not model.tasks[t].discarded]


def words_of(c: Capture, content: str | None) -> tuple[str, str]:
    """A decision's first line and all its words, from its content text as capture.md keeps it (its whole line, decision
    203): the list marker, the operator and the ``#`` tasks taken out, a person by their name. With no words of its own
    (a ``**decision,`` alone), or no content text to read, its title, which is its first sentence."""
    text = markup.to_plain(content) if content and c.formatted else content or ""
    text = items.unstore(_PERSON_REF.sub(lambda m: m.group(1), _TASK_REF.sub("", text)))
    lines = [x.rstrip() for x in text.split("\n") if x.strip()]
    first = " ".join(_OPERATOR.sub("", items.LIST_RE.sub("", lines[0], count=1) if lines else "").split())
    if not first:
        return c.title, c.title
    first = first[0].upper() + first[1:]
    whole = "\n".join([first, *lines[1:]])
    return first, whole


def _meeting_name(title: str, day: str | None) -> str:
    """A meeting's name without the day a regular meeting's name ends with ("Business team meeting 8 Oct", release 5.8),
    since the register says the day."""
    if day:
        d = to_date(day)
        end = " " + short(d, d)
        if title.endswith(end) and len(title) > len(end):
            return title[: -len(end)]
    return title


def meeting_of(model: Model, c: Capture) -> tuple[str | None, str, str | None]:
    """The meeting a capture came from, when it came from a meeting's notes: its task, its name and its day."""
    notes = model.captures.get(c.from_notes) if c.from_notes else None
    if notes is None or notes.item != "notes" or not notes.task or notes.task not in model.tasks:
        return None, "", None
    m = model.task(notes.task)
    day = m.start or m.due or notes.saved[:10]
    return m.id, _meeting_name(m.title, day), day


def decision(model: Model, c: Capture, task_id: str, content_of: Callable[[str], str | None] | None = None) -> Decision:
    """A decision capture as the register lists it, on ``task_id``. ``content_of`` reads a capture's content text; without
    it, its words are its title."""
    words, whole = words_of(c, content_of(c.id) if content_of else None)
    meeting, name, day = meeting_of(model, c)
    return Decision(c.id, c.saved, words, whole if whole != words else "", task_id, meeting, name, day)


def worded(model: Model, d: Decision, content_of: Callable[[str], str | None]) -> Decision:
    """A decision listed without its text read, with its words from its content text: a page reads only the rows it shows."""
    return decision(model, model.captures[d.capture], d.task, content_of)


def _newest_first(found: Iterable[Decision]) -> list[Decision]:
    """Newest first; those saved together (one meeting's notes) in the order they were typed, as search lists them."""
    return sorted(sorted(found, key=lambda d: d.capture), key=lambda d: d.saved, reverse=True)


def of_tasks(model: Model, task_ids: Iterable[str], content_of: Callable[[str], str | None] | None = None) -> list[Decision]:
    """The decisions on any of these tasks, newest first (decision 477), each named by the first of its tasks among them.
    A discarded task's are left out, as its other captures are."""
    order = {t: i for i, t in enumerate(dict.fromkeys(task_ids)) if t in model.tasks and not model.tasks[t].discarded}
    out = []
    for c in model.captures.values():
        if is_decision(c):
            here = sorted((t for t in _live_tasks(model, c) if t in order), key=order.__getitem__)
            if here:
                out.append(decision(model, c, here[0], content_of))
    return _newest_first(out)


def every(model: Model, content_of: Callable[[str], str | None] | None = None) -> list[Decision]:
    """Every decision on a live task, newest first."""
    out = []
    for c in model.captures.values():
        if is_decision(c):
            tasks = _live_tasks(model, c)
            if tasks:
                out.append(decision(model, c, tasks[0], content_of))
    return _newest_first(out)


# ---- the register (decision 479) ----
def rows(model: Model, found: Iterable[Decision], today: date) -> list[tuple[str, str, str, str]]:
    """The register's rows: the day (2026-10-13), the decision's first line, its task's title and where it was decided."""
    return [(d.day, d.words, model.task(d.task).title, d.where(today)) for d in found]


def _md_cell(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split())


def markdown(table: list[tuple[str, ...]]) -> str:
    """The register as a Markdown table."""
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(_md_cell(x) for x in row) + " |" for row in table]
    return "\n".join(lines) + "\n"


def html(table: list[tuple[str, ...]]) -> str:
    """The register as an HTML table, for pasting into an email or a document: a header row, thin borders, the dates kept
    on one line."""
    cell = 'style="border: 1px solid #c8cfd6; padding: 4px 8px; vertical-align: top; text-align: left"'
    head = "".join(f"<th {cell}>{escape(x)}</th>" for x in COLUMNS)
    body = "".join("<tr>" + "".join(f'<td {cell}{" nowrap" if i == 0 else ""}>{escape(x)}</td>' for i, x in enumerate(row)) + "</tr>"
                   for row in table)
    return (f'<table style="border-collapse: collapse; font-family: Segoe UI, sans-serif; font-size: 10pt">'
            f"<tr>{head}</tr>{body}</table>")
