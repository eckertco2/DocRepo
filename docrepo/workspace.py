"""The workspace (release 5.152; the design workspace's ``docs/mods/workspace-view-plan.md``, decisions 663 to 670, 678 to
687 and 698 to 702, from the owner's voice memo of 2026-11-13): the task page laid out for doing the work, with the chain
of tasks above it, its notes and theirs, and the resources of all of them.

- **The chain** (decisions 664 and 686): the project down to this task, a tile each. A task under two parents has a path
  per parent, the second "and under" the first, each task once; nothing is said of a parent's other subtasks.
- **What's gathered** (665, 680 and 700): the task picked in the chain (this task until another is picked), every live
  task under it at any depth, and every task above it. Picking a parent widens it to that parent's other subtasks; this
  task picked leaves them out, as they're other work.
- **The outline** (669 and 683): the pages from the project down to this task, then the pages of what's under it, each
  page's days and headings under its name, with Dates at its end. DocRepo runs no model, so the outline and each task's
  status are the summary.
- **Dates** (681, 698 and 699): every date of what's gathered, soonest first: Due, Deadline, a Reminder, a wait's
  follow-up, key dates (a plant activity as a plant event), and meetings with their next one. It adds no date kind, so
  it retires none (698): a day is typed in Quick edit's words and written through the calls the task page uses, each
  change in the status log.
- **The resources** (664, 679, 680 and 685): Links, Files, Email conversations, Meetings and Decisions of what's
  gathered, the picked task's own first, each saying whose, with the search box's filter over each row's name, its second
  line and whose it is. Read from what's gathered, so there's no new index.

No Qt here: ``docrepo.ui.workspace`` draws it, and the tests feed this directly.
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from docrepo import decisions, edits, email_conversations, later, markup, meeting_rows, notes_page, tasks, waits
from docrepo.config import Settings
from docrepo.dates import days_words, long_date, short, stamp, to_date
from docrepo.db import transaction
from docrepo.detail import CHEVRON_DOWN, CHEVRON_RIGHT, Pages, esc, link
from docrepo.file_rows import dated_name, type_name
from docrepo.model import Model
from docrepo.overview import file_type
from docrepo.parse import find_dates
from docrepo.safe_fs import SafeFS
from docrepo.schedule import due_of, held_on
from docrepo.task_links import links_of

#: The glossary's word, and what the status line and the bar say it is.
NAME = "Workspace"
#: The key that opens it, on a selected task (decision 663).
KEY = "W"


def _live(m: Model, ids: Collection[str]) -> list[str]:
    return [x for x in ids if x in m.tasks and not m.tasks[x].discarded]


def _unique(ids) -> list[str]:
    return list(dict.fromkeys(ids))


# ---- the chain (decisions 664 and 686) ----
@dataclass(frozen=True)
class Chain:
    """The tasks above a task, a path per parent from its project down, each task in the first path it's in, and the task."""

    paths: tuple[tuple[str, ...], ...]
    task: str

    @property
    def above(self) -> list[str]:
        """Every task above, in the chain's order: the first path from its project down, then the next."""
        return [x for p in self.paths for x in p]

    def caption(self, n: int) -> str:
        """The words over a path after the first ("and under"), and over the task under more than one ("under both")."""
        if n == 0 or len(self.paths) < 2:
            return ""
        if n < len(self.paths):
            return "and under"
        return "under both" if len(self.paths) == 2 else f"under all {len(self.paths)}"


def chain(m: Model, task_id: str) -> Chain:
    seen: set[str] = set()
    paths = []
    for c in m.chains_of(task_id):
        part = tuple(x for x in c[:-1] if x not in seen and x in m.tasks)
        seen.update(part)
        if part:
            paths.append(part)
    return Chain(tuple(paths), task_id)


def above(m: Model, task_id: str) -> list[str]:
    return chain(m, task_id).above


def under(m: Model, task_id: str) -> list[str]:
    """Every live task under a task, at any depth, in the tree's order."""
    return _live(m, m.descendants_of(task_id))


def gathered(m: Model, picked: str) -> list[str]:
    """What the resources and Dates gather (680 and 700): the task picked, everything under it and every task above it."""
    return _unique([*above(m, picked), picked, *under(m, picked)])


def resource_order(m: Model, picked: str) -> list[str]:
    """The tasks whose resources are listed, in their order: the picked task's own first (decision 664), then what's under
    it in the tree's order, then the tasks above it, the nearest first."""
    return _unique([picked, *under(m, picked), *reversed(above(m, picked))])


def subtasks(m: Model, task_id: str) -> list[str]:
    """A task's subtasks for the chain's column: the live ones directly under it, the open first, as Subtasks lists them."""
    kids = [m.task(x) for x in _live(m, m.children_of(task_id))]
    return [t.id for t in kids if t.state != "Closed"] + [t.id for t in kids if t.state == "Closed"]


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def scope_words(m: Model, here: str, picked: str) -> str:
    """The line under the resources' search box: whose they are. "Of this task, everything under it (4) and the 2 tasks
    above it."; with a parent picked, "Of Fan deck, everything under it (7) and the task above it."."""
    name = "this task" if picked == here else m.task(picked).title
    n_under, n_above = len(under(m, picked)), len(above(m, picked))
    parts = []
    if n_under:
        parts.append(f"everything under it ({n_under})")
    if n_above:
        parts.append("the task above it" if n_above == 1 else f"the {n_above} tasks above it")
    if not parts:
        return f"Of {name} only."
    if len(parts) == 1:
        return f"Of {name} and {parts[0]}."
    return f"Of {name}, {parts[0]} and {parts[1]}."


def gathered_words(m: Model, here: str) -> str:
    """The status line as it opens: "Gathered from 7 pages: this task, 4 under it and 2 above it."."""
    n_under, n_above = len(under(m, here)), len(above(m, here))
    parts = ["this task"] + ([f"{n_under} under it"] if n_under else []) + ([f"{n_above} above it"] if n_above else [])
    said = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Gathered from {_count(1 + n_under + n_above, 'page', 'pages')}: {said}."


# ---- the outline (decisions 669 and 683) ----
@dataclass(frozen=True)
class Entry:
    """One line of the outline: the page it's on ("" for Dates), its level (1 a page's name or Dates, 2 a day, 3 and on the
    owner's headings), whether it's a day, its words, and which of its page's headings it is (-1 for the page's name)."""

    page: str
    level: int
    day: bool
    text: str
    heading: int = -1


def headings(body: str) -> list[tuple[int, bool, str]]:
    """A page's headings in order, as Jump to lists them: (level, whether it's a day, words); a day is level 1."""
    out = []
    for line in body.split("\n"):
        mt = notes_page.HEADING.match(line)
        if mt:
            text = " ".join(markup.to_plain(mt.group(2)).split())
            out.append((len(mt.group(1)), notes_page.day_of(text) is not None, text or "(an empty heading)"))
    return out


def outline_pages(m: Model, here: str, also: str | None = None) -> list[str]:
    """The pages the outline names, in its order (683): the project down to this task, this task, then the tasks under it
    that have notes (and ``also``, the subtask being edited, whether it has or not), in the tree's order."""
    below = [x for x in under(m, here) if m.pages.get(x, "").strip() or x == also]
    return _unique([*above(m, here), here, *below])


def page_entries(m: Model, page: str) -> list[Entry]:
    """A page's lines of the outline: its name, then its days and headings a level under it."""
    out = [Entry(page, 1, False, m.task(page).title)]
    out += [Entry(page, level + 1, day, text, i) for i, (level, day, text) in enumerate(headings(m.pages.get(page, "")))]
    return out


def outline(m: Model, here: str, also: str | None = None) -> list[Entry]:
    """The whole outline, with Dates at its end."""
    out = [e for p in outline_pages(m, here, also) for e in page_entries(m, p)]
    return out + [Entry("", 1, False, "Dates")]


# ---- Dates (decisions 681, 698 and 699) ----
#: The order of a day's dates.
KINDS = ("Deadline", "Due", "Meeting", "Key date", "Plant event", "Follow-up", "Reminder")
#: How many earlier dates are folded behind Show earlier: every one before today.
DAY_HINT = "A day in words: tomorrow, fri, 24 nov, or +3 for three workdays. Enter keeps it, Esc leaves it."


@dataclass(frozen=True)
class DateRow:
    """A date in Dates: its day (a key date's first), its kind, the task it's on, its words, and what a change writes:
    "due", "deadline", "reminder" or "start" (the task's field), "key_date", "follow_up" (the wait's), or "" when it can't
    be changed here (a repeating meeting's next one)."""

    day: date
    kind: str
    task: str
    words: str
    field: str
    end: date | None = None
    key_date: int | None = None
    deadline: bool = False
    wait: int | None = None

    @property
    def key(self) -> str:
        return f"{self.task}:{self.field}:{self.key_date or ''}:{self.kind}"

    def when(self, today: date) -> str:
        """How far off it is: "today", "tomorrow", "in 2 days", "3 days ago"."""
        return days_words(self.day, today)


def _meetings_of(m: Model, ids: list[str]) -> list[str]:
    """The meetings that are a gathered task's own: gathered ones, and the meetings directly under a gathered task."""
    out = [x for x in ids if m.task(x).meeting]
    for x in ids:
        out += [k for k in _live(m, m.children_of(x)) if m.task(k).meeting]
    return _unique(out)


def dates(m: Model, picked: str, today: date) -> list[DateRow]:
    """Every date of what's gathered (680), soonest first, a day's in ``KINDS`` order. Closed tasks' dates are done with."""
    ids = gathered(m, picked)
    rows: list[DateRow] = []
    for tid in _meetings_of(m, ids):
        t = m.task(tid)
        if t.state == "Closed":
            continue
        d = due_of(t, today)
        day = d.date if d else held_on(t)
        if day is not None:
            fld = "" if t.recurrence else "due" if t.due else "start" if t.start else "deadline" if t.deadline else ""
            rows.append(DateRow(day, "Meeting", tid, t.title, fld))
    for tid in ids:
        t = m.task(tid)
        if t.state == "Closed" or t.meeting:
            continue
        if t.due:
            rows.append(DateRow(to_date(t.due), "Due", tid, t.title, "due"))
        if t.deadline and t.deadline != t.due:
            rows.append(DateRow(to_date(t.deadline), "Deadline", tid, t.deadline_desc or t.title, "deadline", deadline=True))
        w = waits.current(m, tid)
        if w is not None and w.follow_up:
            rows.append(DateRow(to_date(w.follow_up), "Follow-up", tid, f"Follow up with {waits.who(m, w)}", "follow_up", wait=w.id))
        if t.reminder and not (w is not None and w.follow_up == t.reminder):
            rows.append(DateRow(to_date(t.reminder), "Reminder", tid, t.title, "reminder"))
        for kd in m.key_dates_of(tid):
            if kd.done or not (kd.start or kd.end):
                continue
            first, last = to_date(kd.start or kd.end), to_date(kd.end or kd.start)
            rows.append(DateRow(first, "Plant event" if kd.plant else "Key date", tid, kd.description or "A key date", "key_date",
                                end=last if last != first else None, key_date=kd.id, deadline=kd.deadline))
    return sorted(rows, key=lambda r: (r.day, KINDS.index(r.kind), r.words.casefold()))


def split_dates(rows: list[DateRow], today: date) -> tuple[list[DateRow], list[DateRow]]:
    """The earlier dates, folded behind Show earlier, and today's and the ones to come."""
    return [r for r in rows if r.day < today], [r for r in rows if r.day >= today]


_WORKDAYS = re.compile(r"\+?\s*(\d{1,3})")


def read_day(text: str, today: date, workdays: Collection[int]) -> date | None:
    """A day typed in Quick edit's words (decision 681): "+3" or "3" is three workdays on, as Later's Other… reads a number;
    anything else is the first date Parse and populate reads in it ("tomorrow", "fri", "24 nov", "2026-11-24"). None when
    it's neither."""
    words = " ".join(text.split())
    if not words:
        return None
    mt = _WORKDAYS.fullmatch(words)
    if mt:
        n = int(mt.group(1))
        return later.workdays_after(today, n, workdays) if n > 0 else today
    hits = find_dates(words, today)
    return hits[0].date if hits else None


def day_text(day: date, today: date) -> str:
    """A day as the box shows it to change it: "mon 23 nov", with its year when it isn't this year's."""
    words = long_date(day, today)
    return words.lower()


def _shift(value: str | None, days: int) -> str | None:
    return (to_date(value) + timedelta(days=days)).isoformat() if value else None


def change_day(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, row: DateRow, day: date, at: datetime) -> edits.Outcome:
    """Change a date in Dates to ``day`` (decisions 681 and 698), through the calls the task page uses, each change logged:
    a task's field by ``edits.change_task``, a key date by ``edits.set_key_dates`` (one with a start and an end moves
    both), a wait's follow-up by ``set_follow_up``. Undo is the same call with the row at its new day and the old one."""
    if row.field in ("due", "deadline", "reminder", "start"):
        return edits.change_task(conn, data_root, fs, settings, row.task, at, **{row.field: day.isoformat()})
    if row.field == "key_date":
        rows = tasks.key_date_rows(conn, row.task)
        moved = (day - row.day).days
        hit = False
        for r in rows:
            if r.id == row.key_date:
                r.start, r.end, hit = _shift(r.start, moved), _shift(r.end, moved), True
        if not hit:
            raise edits.EditError("That key date isn't there any more.")
        return edits.set_key_dates(conn, data_root, fs, settings, row.task, rows, at)
    if row.field == "follow_up":
        return set_follow_up(conn, data_root, fs, settings, row.task, day, at)
    raise edits.EditError("A repeating meeting's next one moves with its series: change it in Edit task.")


#: The status log's field for a follow-up day changed in Dates.
FOLLOW_UP_FIELD = "Follow up"


def set_follow_up(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, day: date,
                  at: datetime) -> edits.Outcome:
    """A wait's follow-up moved to ``day`` (decision 681): logged, and the Reminder it set moved with it, as Log progress
    sets one (``waits.reminder_for``): the task's own earlier reminder stays, and a later one is kept for after."""
    before = Model(conn)
    w = waits.current(before, task_id)
    if w is None:
        raise edits.EditError(f"{before.task(task_id).title} isn't waiting any more.")
    new = day.isoformat()
    if w.follow_up == new:
        return edits.Outcome("Nothing changed.")
    t = before.task(task_id)
    own = w.reminder_before if w.follow_up and t.reminder == w.follow_up else t.reminder
    reminder = own if own and own <= new else new
    kept = own if own and own > new else None
    with transaction(conn):
        conn.execute("UPDATE waits SET follow_up = ?, reminder_before = ? WHERE id = ?", (new, kept, w.id))
        conn.execute("INSERT INTO status_log (task, at, field, from_value, to_value, via) VALUES (?, ?, ?, ?, ?, ?)",
                     (task_id, stamp(at), FOLLOW_UP_FIELD, w.follow_up, new, edits.BROWSE))
    if reminder != t.reminder:
        tasks.update_task(conn, settings, task_id, at=at, via=edits.BROWSE, reminder=reminder)
    out = edits.Outcome(f"Follow up with {waits.who(before, w)}: {long_date(day, at.date())}.")
    edits.write_touched_pages(conn, data_root, fs, at, out.problems, [task_id], before)
    return out


def key_date_done(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, row: DateRow, done: bool, at: datetime) -> edits.Outcome:
    """A key date's menu's Done (decision 681), as the task page's tick (decision 148)."""
    if row.key_date is None:
        raise edits.EditError("Only a key date is done this way.")
    return edits.set_key_date_done(conn, data_root, fs, row.key_date, done, at)


def take_off(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, row: DateRow, at: datetime) -> tuple[edits.Outcome, list[tasks.KeyDateRow]]:
    """A key date's menu's Take it off: the task's key dates without it. Returns the rows as they were, for Undo."""
    rows = tasks.key_date_rows(conn, row.task)
    kept = [r for r in rows if r.id != row.key_date]
    if len(kept) == len(rows):
        raise edits.EditError("That key date isn't there any more.")
    return edits.set_key_dates(conn, data_root, fs, settings, row.task, kept, at), rows


def put_back(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, rows: list[tasks.KeyDateRow],
             at: datetime) -> edits.Outcome:
    """Undo after Take it off: the key dates as they were (the one taken off comes back as a new one, in its place)."""
    alive = {r.id for r in tasks.key_date_rows(conn, task_id)}
    return edits.set_key_dates(conn, data_root, fs, settings, task_id,
                               [r if r.id in alive else replace(r, id=None) for r in rows], at)


def read_key_date(text: str, today: date, workdays: Collection[int]) -> tuple[date, str] | None:
    """Add a key date's words: a day in Quick edit's words and what it is, "24 nov Base plate drawing" or "+3 Datasheet".
    None when there's no day in it."""
    words = " ".join(text.split())
    head, _, rest = words.partition(" ")
    hits = find_dates(words, today)
    first = hits[0] if hits and words.casefold().startswith(hits[0].text.casefold()) else None
    if first is None and _WORKDAYS.fullmatch(head):
        day = read_day(head, today, workdays)
        return (day, rest) if day else None
    hit = first or (hits[0] if hits else None)
    if hit is None:
        return None
    i = words.casefold().find(hit.text.casefold())
    what = (words[:i] + words[i + len(hit.text):]) if i >= 0 else words
    return hit.date, " ".join(what.split()).strip(" ,:-")


def add_key_date(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, day: date, what: str,
                 at: datetime) -> edits.Outcome:
    """Add a key date (decision 681) to the task being edited, at the end of its own."""
    rows = tasks.key_date_rows(conn, task_id) + [tasks.KeyDateRow(day.isoformat(), None, what)]
    return edits.set_key_dates(conn, data_root, fs, settings, task_id, rows, at)


# ---- the quick entry bar (decisions 678, 701 and 702) ----
def note_page(body: str, line: str, day: date) -> str:
    """The page with a line of notes under the day's heading, starting that day when the page hasn't one (decision 701)."""
    return notes_page.add_block(body, [line], day, True)


def without_note(body: str, line: str, day: date) -> str:
    """Undo after Shift+Enter: the page without that line (its last copy under the day), and the day's heading too when the
    line made it and nothing else is under it."""
    raw = body.split("\n")
    head = notes_page.heading_line(notes_page.day_title(day), 1)
    for i in range(len(raw) - 1, -1, -1):
        if raw[i] == line:
            del raw[i]
            if i > 0 and raw[i - 1] == head and (i == len(raw) or notes_page.HEADING.match(raw[i] or "") and notes_page.day_of(raw[i])):
                del raw[i - 1]
            break
    while raw and not raw[-1].strip():
        raw.pop()
    return "\n".join(raw)


def today_item(m: Model, task_id: str):
    """The task's open item on Today, or None."""
    return next((a for a in m.today_items() if a.subject == task_id), None)


def done_today(m: Model, task_id: str, today: date) -> bool:
    """Whether the task was marked Done on Today today: neither Later… nor Add to Today shows then (702)."""
    return any(a.subject == task_id for a in m.done_on(today))


# ---- the resources (decisions 664, 679, 680 and 685) ----
#: The sections, in the column's order (685 puts Meetings between Email conversations and Decisions).
SECTIONS = (("links", "Links"), ("files", "Files"), ("emails", "Email conversations"), ("meetings", "Meetings"), ("decisions", "Decisions"))


@dataclass
class Row:
    """A resource's row: its section, the task it's on, its name and the line under it (both searched), its day, where a
    click goes, its mark (an ``img`` source), and markup after the name that isn't searched (a count, a pin)."""

    section: str
    task: str
    name: str
    second: str
    day: str
    href: str
    mark: str
    tip: str = ""
    after: str = ""
    whose: str = field(default="", compare=False)


def _links(pages: Pages, order: list[str]) -> list[Row]:
    marks = {"reference": "lk:ref", "link": "lk:link", "folder": "lk:folder", "text": "lk:note"}
    rows, seen = [], set()
    for tid in order:
        for x in links_of(pages.m, tid, pages.reference_links):
            if x.address in seen:
                continue
            seen.add(x.address)
            href = f"opendoc:{x.document}" if x.document else "openurl:" + quote(x.address, safe="")
            rows.append(Row("links", tid, x.name, x.where, "", href, marks[x.kind], x.opens))
    return rows


def _files(pages: Pages, order: list[str]) -> list[Row]:
    m = pages.m
    came = {(c.task, d): c.saved for tid in order for c in m.notes_of(tid) for d in c.document_ids}
    rows, seen = [], set()
    for f in pages.files_in(order):
        key = (f.kind, f.name, f.task) if f.kind == "Old version" else f.document or (f.kind, f.name)
        if key in seen:
            continue
        seen.add(key)
        d = m.documents.get(f.document)
        original = d.original if d and d.original else ""
        kind = file_type(f.name, original)
        day, shown = dated_name(f.name) if f.kind in ("Saved file", "Old version") else ("", f.name)
        day = day or came.get((f.task, f.document), "")[:10]
        href = f"opendoc:{f.document}" if f.kind in ("Link", "Folder") else pages.show_key(f)
        tip = f"{type_name(kind)} · {f.kind}. " + ("Click to open it." if f.kind in ("Link", "Folder") else "Click to show it in File Explorer.")
        rows.append(Row("files", f.task, shown, d.description if d and d.description else "", short(to_date(day), pages.today) if day else "",
                        href, f"ft:{kind}", tip, ' <span class="sub">old version</span>' if f.kind == "Old version" else ""))
    return rows


def _emails(pages: Pages, picked: str, order: list[str]) -> list[Row]:
    ec, m = email_conversations, pages.m
    me = pages.me_name()
    rows = []
    for cv in ec.for_tasks(m, order):
        words = ec.snippet(ec.newest_words(m, cv, pages.content_of))
        second = ec.who(pages.senders(cv), me) + (f" · {words}" if words else "")
        n = len(cv.emails)
        rows.append(Row("emails", ec.task_in(cv, order) or picked, cv.subject, second, short(to_date(cv.newest.at), pages.today),
                        f"conv:{picked}/{cv.id}", "ft:mail", "Open the conversation: its emails, the newest first",
                        f' <span class="rel">&nbsp;{n}</span>' if n > 1 else ""))
    return rows


def _meetings(pages: Pages, picked: str, order: list[str]) -> list[Row]:
    """The picked task's meetings (``meeting_rows``: under it, or whose notes did something on it or under it), and each
    task above's own: a meeting directly under it, or whose notes did something on that task itself, not its other work."""
    m = pages.m
    found: dict[str, tuple[meeting_rows.MeetingRow, str]] = {r.meeting: (r, picked) for r in meeting_rows.rows(m, picked)}
    for tid in order:
        if tid == picked or tid not in m.tasks:
            continue
        for r in meeting_rows.rows(m, tid):
            own = tid in m.parents_of(r.meeting) or any(getattr(x, "task", None) == tid for x in r.touches)
            if own and r.meeting not in found:
                found[r.meeting] = (r, tid)
    out = []
    for r, tid in sorted(found.values(), key=lambda x: x[0].day or "", reverse=True):
        said = meeting_rows.words(m, r, tid, pages.content_of)
        out.append(Row("meetings", tid, m.task(r.meeting).title, said, short(to_date(r.day), pages.today) if r.day else "",
                       f"wsmeet:{r.meeting}", "lk:meeting", "Read its notes here, read only"))
    return out


def _decisions(pages: Pages, order: list[str]) -> list[Row]:
    m = pages.m
    rows = []
    for d in (decisions.worded(m, x, pages.content_of) for x in decisions.of_tasks(m, order)):
        where = d.where(pages.today)
        rows.append(Row("decisions", d.task, d.words, f"in {where}" if where else "", short(to_date(d.day), pages.today),
                        f"capture:{d.capture}", "lk:decision", f"{d.more or d.words}\n\nClick to open its capture."))
    return rows


def resources(pages: Pages, picked: str) -> dict[str, list[Row]]:
    """Every resource of what's gathered (680), by section, each row's ``whose`` its task's title."""
    m = pages.m
    order = [x for x in resource_order(m, picked) if x in m.tasks]
    out = {"links": _links(pages, order), "files": _files(pages, order), "emails": _emails(pages, picked, order),
           "meetings": _meetings(pages, picked, order), "decisions": _decisions(pages, order)}
    for rows in out.values():
        for r in rows:
            r.whose = m.task(r.task).title if r.task in m.tasks else ""
    return out


def words_of(query: str) -> list[str]:
    return query.casefold().split()


def matches(row: Row, words: list[str]) -> bool:
    """Whether a row has every word of the search (679), in its name, its second line or whose it is."""
    hay = f"{row.name}\n{row.second}\n{row.whose}".casefold()
    return all(w in hay for w in words)


def filtered(found: dict[str, list[Row]], query: str) -> dict[str, list[Row]]:
    words = words_of(query)
    return {k: [r for r in rows if matches(r, words)] for k, rows in found.items()} if words else found


def marked(text: str, words: list[str]) -> str:
    """The words found marked in the text (679), as search marks them; the rest escaped."""
    if not words or not text:
        return esc(text)
    pattern = re.compile("|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)), re.IGNORECASE)
    out, at = [], 0
    for mt in pattern.finditer(text):
        out.append(esc(text[at:mt.start()]))
        out.append(f'<span class="mark">{esc(mt.group(0))}</span>')
        at = mt.end()
    out.append(esc(text[at:]))
    return "".join(out)


def whose_chip(m: Model, task_id: str, picked: str, words: list[str]) -> str:
    """Whose a row is, after its name (664): "↑ on Fan deck" for a task above, "↳ on Confirm the frame size" for one under,
    nothing for the picked task's own. A click picks that task in the chain."""
    if not task_id or task_id == picked or task_id not in m.tasks:
        return ""
    up = task_id in above(m, picked)
    title = m.task(task_id).title
    words_html = marked(title if len(title) <= 40 else title[:39] + "…", words)
    tip = f"On {title}, {'above' if up else 'under'} {m.task(picked).title}. Click to pick it in the chain."
    return f' <a href="wspick:{esc(task_id)}" title="{esc(tip)}" style="text-decoration: none"><span class="{"multi" if up else "lbli"}">&nbsp;{"↑" if up else "↳"} on {words_html}&nbsp;</span></a>'


def section_actions(picked: str) -> dict[str, str]:
    """Each section's command at its head's right: Find files, New T-mail, Meeting notes and Copy."""
    return {"files": link(f"taskview:{picked}", "Find files", "Search, preview and open the task's files (O)"),
            "emails": link(f"tmail:{picked}", "New T-mail", "A new email in Outlook, tagged for the task"),
            "meetings": link(f"meetingnotes:{picked}", "Meeting notes", "Take meeting notes for the task"),
            "decisions": link(f"copydecisions:{picked}", "Copy", "Copy the decision register")}


def resources_html(m: Model, found: dict[str, list[Row]], picked: str, query: str, folded: Collection[str]) -> str:
    """The resources column under its search box: a section each, with its count ("2 of 9" while searching, decision 679),
    its rows with the words found marked, and nothing for a section the search has emptied."""
    words = words_of(query)
    shown = filtered(found, query)
    actions = section_actions(picked)
    out = []
    for key, title in SECTIONS:
        rows, total = shown[key], len(found[key])
        if not rows and (words or key != "files"):
            continue
        count = f"{len(rows)} of {total}" if words else str(total)
        is_open = key not in folded
        chevron = f'<a href="wsfold:{key}" title="{"Fold" if is_open else "Unfold"} {title}">{CHEVRON_DOWN if is_open else CHEVRON_RIGHT}</a>'
        act = actions.get(key, "")
        out.append(f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top: 12px"><tr>'
                   f'<td width="18" valign="middle">{chevron}</td><td><b>{esc(title)}</b> <span class="rel">&nbsp;{count}</span></td>'
                   f'<td align="right" class="rel">{act}</td></tr></table>')
        if not is_open:
            continue
        if not rows:
            out.append('<p class="note">None yet.</p>')
            continue
        cells = []
        for r in rows:
            name = f'<a href="{esc(r.href)}" title="{esc(r.tip)}"><span class="tl">{marked(r.name, words)}</span></a>{r.after}'
            second = f'<br><span class="sub">{marked(r.second, words)}</span>' if r.second else ""
            chip = whose_chip(m, r.task, picked, words)
            cells.append(f'<tr><td valign="top" width="20"><img src="{esc(r.mark)}" width="14" height="14"></td>'
                         f'<td valign="top">{name}{second}{chip}</td>'
                         f'<td valign="top" align="right" class="rel" width="48">{esc(r.day)}</td></tr>')
        out.append(f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(cells)}</table>')
    if words and not any(shown.values()):
        out.append(f'<p class="note">Nothing here has "{esc(query.strip())}". Esc clears the search.</p>')
    return "".join(out)


# ---- reading a parent's or a meeting's notes in place (decisions 668 and 685) ----
EDIT_THERE_TIP = "Open its page at these lines, to edit them there; Alt+Left comes back to the workspace"


@dataclass(frozen=True)
class Place:
    """A place in notes read in place, for the outline: its anchor's name, its level (2 a day, 3 and on a heading), whether
    it's a day, and its words."""

    anchor: str
    level: int
    day: bool
    text: str


def read_html(pages: Pages, task_id: str, banner: str = "") -> tuple[str, list[Place]]:
    """A page's notes read in place, read only, as All notes shows them (668): each day with Edit there, a meeting's notes
    and a capture's block named, then its lines. Returns the HTML and its places, in order, for the outline."""
    from docrepo import all_notes

    m = pages.m
    an = all_notes.compose(m, task_id, None, task_id)
    out = [banner] if banner else []
    places: list[Place] = []
    for day, blocks in an.days:
        first = (blocks[0].capture or "") if blocks else ""
        edit = link(f"notesgo:{task_id}:{first}", "Edit there", EDIT_THERE_TIP)
        out.append(f'<p class="anday"><a name="day:{day.isoformat()}"><span class="anday">{esc(notes_page.day_title(day))}</span></a>'
                   f' &nbsp;<span class="rel">{edit}</span></p>')
        places.append(Place(f"day:{day.isoformat()}", 2, True, notes_page.day_title(day)))
        for b in blocks:
            c = m.captures.get(b.capture or "")
            if c is not None:
                if c.item == "notes":
                    meeting = meeting_rows.meeting_of(m, c.id)
                    name = (pages.page_chip(meeting, "") + " ") if meeting and meeting != task_id else ""
                    out.append(f'<p class="src">{name}Meeting notes</p>')
                elif b.label:
                    out.append(f'<p class="src">{esc(b.label)}{f" · {esc(b.time)}" if b.time else ""}</p>')
            for x in b.lines:
                if x.kind == "heading" and not notes_page.day_of(x.text):
                    anchor = f"heading:{len(places)}"
                    out.append(f'<a name="{anchor}"></a>')
                    text = " ".join(markup.to_plain(x.text).split()) or "(an empty heading)"
                    places.append(Place(anchor, 2 + max(1, getattr(x, "level", 2) - 1), False, text))
                out.append(pages.note_line_html(x, page=b.page))
    if not an.days:
        out.append('<p class="note">No notes on this page yet.</p>')
    return "".join(out), places


def banner_html(text: str, back: str = "Back to this task's notes", extra: str = "") -> str:
    """The line over notes read in place or a subtask edited: what it is, then its links."""
    links = (f" &nbsp;{extra}" if extra else "") + f' &nbsp;{link("wsback:", back, "Alt+Left")} <span class="faint">Alt+←</span>'
    return f'<table width="100%" cellspacing="0" cellpadding="8" style="margin-bottom: 6px"><tr><td class="info">{text}{links}</td></tr></table>'


def meeting_words(pages: Pages, meeting: str, task_id: str) -> str:
    """What a meeting's notes did on the task (685), release 5.140's words, or its day."""
    m = pages.m
    r = next((x for x in meeting_rows.rows(m, task_id) if x.meeting == meeting), None)
    if r is None:
        return ""
    return meeting_rows.words(m, r, task_id, pages.content_of)


def short_day(day: str | date, today: date) -> str:
    return short(to_date(day), today)


__all__ = ["Chain", "DateRow", "Entry", "KEY", "NAME", "Row", "SECTIONS", "above", "add_key_date", "chain", "change_day", "dates",
           "day_text", "done_today", "gathered", "gathered_words", "outline", "outline_pages", "page_entries", "read_day",
           "read_html", "read_key_date", "resource_order", "resources", "resources_html", "scope_words", "set_follow_up",
           "split_dates", "subtasks", "today_item", "under"]
