"""The browse tool's pages: a task, a capture, a document, a person or a label, as HTML for its detail pane.

The pane is a QTextBrowser, so the HTML keeps to what Qt's rich text shows:
tables, coloured spans and links. Every link is handled by the browse tool
itself; none leaves DocRepo. A link's address says what it does:

- ``task:T000008``, ``capture:C000001``, ``doc:D000001``, ``person:P001``, ``label:Safety`` open an item;
- ``tab:notes``, ``scope:family``, ``order:new``, ``chap:T000009``, ``chapall:open``, ``more:C000012`` and
  ``orig:C000012`` change what the task page shows;
- ``agenda:T000010`` opens an agenda, ``show:copy:3`` (or ``show:doc:``, ``show:capture:``) shows a file in File Explorer,
  and ``copylink:D000001`` copies a link document's address (a link is only ever copied, never opened).

Nothing here touches Qt, so the pages are tested as text. Ported from the mockup's ``detail.js``.
"""
from __future__ import annotations

import html
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import quote

from docrepo import capacity, items, markup, notes_page, ties
from docrepo.dates import ago, days_words, long_date, monday_of, short, to_date
from docrepo.links import NO_TEXT, is_link
from docrepo.model import PRIORITY_NAMES, TODAY, TYPE_NAMES, Capture, Model, Task, is_person
from docrepo.pages import num
from docrepo.schedule import due_of, is_open, start_of
from docrepo.stories import Event, RawItem, Stories, clip
from docrepo.views import CapacityRow, due_cell, label_tasks, markers, rem_text

CSS = """
body { font-family: 'Segoe UI'; font-size: 10pt; color: #1a1f25; }
a { color: #1d5e98; text-decoration: none; }
h2 { font-size: 15pt; font-weight: 600; margin-top: 2px; margin-bottom: 4px; }
.crumbs { color: #5a6571; font-size: 9pt; margin: 0; }
.sub { color: #5a6571; font-size: 9pt; }
.faint { color: #87919c; }
.k { color: #5a6571; padding-right: 12px; }
.fk { color: #5a6571; font-size: 9pt; }
.note { color: #5a6571; font-size: 9pt; }
.box { background-color: #f4f6f8; }
.info { background-color: #dbe8f5; }
.warn { background-color: #fcefcf; }
.tab { color: #1d5e98; }
.tabon { background-color: #dbe8f5; font-weight: 600; }
.day { color: #5a6571; font-size: 9pt; }
.month { color: #87919c; font-size: 9pt; font-weight: 600; }
.lead { color: #5a6571; font-size: 9pt; }
.facts { color: #5a6571; font-size: 9pt; }
.text { white-space: pre-wrap; }
.chs { color: #1a1f25; font-weight: 600; margin-top: 12px; }
.ch { background-color: #f4f6f8; }
.st-ns { color: #5a6571; background-color: #eef1f4; }
.st-ip { color: #1d5e98; background-color: #dbe8f5; }
.st-pk { color: #585a70; background-color: #eae8f2; }
.st-cl { color: #87919c; background-color: #e9edf1; }
.urgent { color: #b0261e; background-color: #fbe3e1; font-weight: 600; }
.pri-critical { color: #ffffff; background-color: #b0261e; font-weight: 600; }
.pri-high { color: #875700; background-color: #fcefcf; font-weight: 600; }
.pri-medium { color: #1d5e98; background-color: #dbe8f5; }
.pri-parking { color: #5a6571; background-color: #e9edf1; }
.routine { color: #1a1f25; background-color: #e9edf1; }
.multi { color: #1d5e98; background-color: #e4eefa; }
.lbl { color: #1a1f25; background-color: #e9edf1; }
.inh { color: #5a6571; font-style: italic; }
.new { color: #875700; background-color: #fcefcf; }
.u1 { background-color: #e2f2e6; }
.u2 { background-color: #fcefcf; }
.u3 { background-color: #fbe3e1; }
.sec { font-weight: 600; margin-top: 16px; margin-bottom: 4px; }
.dt { color: #5a6571; font-size: 9pt; padding-right: 12px; }
.rel { color: #5a6571; font-size: 9pt; }
.over { color: #b0261e; font-weight: 600; }
.stat { background-color: #f4f6f8; }
.sk { color: #5a6571; font-size: 9pt; font-weight: 600; }
.desc { color: #5a6571; margin-top: 4px; }
.lbli { color: #5a6571; }
.rule { background-color: #d6dce3; }
.tl { color: #1a1f25; }
.tq { color: #5a6571; }
.mark { background-color: #fff4ce; font-weight: 600; }
.line { margin: 0; }
.hitline { margin: 0; background-color: #fff4ce; }
.gap { margin: 0; color: #5a6571; }
"""

STATE_CLASS = {"Not started": "st-ns", "In progress": "st-ip", "Parked": "st-pk", "Closed": "st-cl"}
#: The task page's history (release 5.21): its tabs, and the names of its scopes. Subtasks is a section of its own now.
#: The history's tabs. The raw text log is Captures since the notes page (release 5.25, decision 104).
TABS = (("notes", "Captures"), ("log", "Status log"), ("summaries", "Summaries"), ("files", "Files"))
SCOPE_NAMES = {"self": "This task", "ancestors": "With parent tasks", "descendants": "With subtasks", "family": "Whole family"}
SOURCE_NAMES = {"typed": "Typed", "outlook_email": "Email", "file_path": "File path"}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
#: A raw text log entry longer than this folds, with Show all.
FOLD_CHARS = 360


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def multiline(text: str) -> str:
    return esc(text).replace("\n", "<br>")


def chip(text: str, cls: str) -> str:
    return f'<span class="{cls}">&nbsp;{esc(text)}&nbsp;</span>'


def state_chip(state: str, text: str | None = None) -> str:
    return chip(text or state, STATE_CLASS.get(state, "st-ns"))


def link(href: str, text: str, title: str = "", quiet: str = "") -> str:
    """A link. ``quiet`` ("tl" for primary text, "tq" for secondary) colours it as text, for a title that's a link
    (release 5.21): blue stays for what reads as an action or a reference."""
    tip = f' title="{esc(title)}"' if title else ""
    words = f'<span class="{quiet}">{esc(text)}</span>' if quiet else esc(text)
    return f'<a href="{esc(href)}"{tip}>{words}</a>'


def label_href(name: str) -> str:
    return "label:" + quote(name, safe="")


def none_text(text: str = "None") -> str:
    return f'<span class="sub">{esc(text)}</span>'


def fields_table(rows: list[tuple[str, str]]) -> str:
    cells = "".join(f'<tr><td class="k" width="118" valign="top">{esc(k)}</td><td valign="top">{v}</td></tr>' for k, v in rows)
    return f'<table cellspacing="0" cellpadding="3">{cells}</table>'


#: The task page (the visual overhaul's O9, release 5.21): two columns from WIDE_PAGE wide, with the facts in a rail RAIL
#: wide; no wider than PAGE_MAX, so lines stay readable; When and Who side by side from SIDE_BY_SIDE.
WIDE_PAGE = 760
RAIL = 260
PAGE_MAX = 1040
SIDE_BY_SIDE = 540
#: A description longer than this folds, with More (decision 67).
DESC_CHARS = 180
PROGRESS_WIDTH = 72
MARKS = {"Not started": "ns", "In progress": "ip", "Parked": "pk", "Closed": "cl"}


def section(title: str, extra: str = "") -> str:
    """A section's heading in Body Strong, with ``extra`` (a count, a link) after it."""
    return f'<p class="sec">{esc(title)}{extra}</p>'


def fact_rows(rows: list[tuple[str, str]]) -> str:
    """Facts as a short grey label beside its value, the values on one left edge."""
    cells = "".join(f'<tr><td class="dt" valign="top">{esc(k)}</td><td valign="top">{v}</td></tr>' for k, v in rows)
    return f'<table cellspacing="0" cellpadding="3">{cells}</table>'


def group(title: str, rows: list[tuple[str, str]]) -> str:
    return section(title) + fact_rows(rows) if rows else ""


def initials(name: str) -> str:
    """``Tom Becker`` is TB, ``Todd`` is T."""
    words = [w for w in name.split() if w[:1].isalpha()] or [name or "?"]
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def box(inner: str, cls: str = "box") -> str:
    return f'<table width="100%" cellspacing="0" cellpadding="7"><tr><td class="{cls}">{inner}</td></tr></table>'


@dataclass
class PageState:
    """What a task page shows: its tab, scope and order, and which chapters and entries are open."""

    tab: str = "notes"
    scope: str = "descendants"
    order: str = "old"
    chapters: set[str] = field(default_factory=set)
    expanded: set[str] = field(default_factory=set)  # long raw text log entries shown in full
    originals: set[str] = field(default_factory=set)  # entries with a summary showing their original text too
    details: bool = False  # Details open (release 5.21)
    desc: bool = False  # the whole description
    closed: bool = False  # the closed subtasks shown


class Pages:
    """Builds the pages for one Model, as of ``today``. ``content_of`` reads a capture's content text."""

    def __init__(self, model: Model, today: date, content_of: Callable[[str], str], me: str | None = None,
                 conn: sqlite3.Connection | None = None) -> None:
        self.m = model
        self.today = today
        self.content_of = content_of
        self.me = me
        self.conn = conn
        self.stories = Stories(model, today, content_of, model.person_name(me) if me and me in model.people else None)

    # ---- small pieces ----
    def day(self, at: str) -> str:
        return short(to_date(at), self.today)

    def long(self, value: str) -> str:
        return long_date(to_date(value), self.today)

    def task_link(self, task_id: str, quiet: str = "") -> str:
        return link(f"task:{task_id}", self.m.task(task_id).title, quiet=quiet) if task_id in self.m.tasks else esc(task_id)

    def capture_link(self, capture_id: str, text: str | None = None, quiet: str = "") -> str:
        return link(f"capture:{capture_id}", text or capture_id, f"Open capture {capture_id}", quiet)

    def target_link(self, target: str) -> str:
        if target == TODAY:
            return link(f"agenda:{TODAY}", "Today")
        return link(f"person:{target}", self.m.person_name(target)) if is_person(target) else self.task_link(target)

    def ref_link(self, via: str | None) -> str:
        """A link to where a change came from: a capture, or plain text such as "Browse tool"."""
        if via and via in self.m.captures:
            return self.capture_link(via)
        return esc(via or "")

    def from_chip(self, task_id: str, here: str) -> str:
        """A small link naming another task in the scope that an entry comes from."""
        if not task_id or task_id == here:
            return ""
        title = self.m.task(task_id).title
        return f' <a href="task:{esc(task_id)}" title="From {esc(title)}. Click to open it."><span class="sub">↗ {esc(clip(title, 40))}</span></a>'

    def roles(self, person_ids: list[str], hours: float | None, routine: bool) -> str:
        if not person_ids:
            return none_text()
        per = ' <span class="sub">per occurrence</span>' if routine and hours else ""
        return ", ".join(link(f"person:{p}", self.m.person_name(p)) + (f' <span class="sub">{num(hours)} h</span>' if hours else "")
                         for p in person_ids) + per

    def markers_html(self, t: Task, critical: bool = True) -> str:
        return "".join(" " + chip(text, cls) for text, cls in markers(self.m, t, critical))

    def priority_chip(self, t: Task) -> str:
        """The task page shows every bucket (release 5.23, decision 77); rows show only Critical."""
        return f" {chip(PRIORITY_NAMES[t.priority], 'pri-' + t.priority)}" if t.priority in PRIORITY_NAMES else ""

    def agenda_block(self, target: str) -> str:
        items = self.m.open_items_for(target)
        if not items:
            return ""
        lines = [f'<b>Agenda: {len(items)} open item{"s" if len(items) > 1 else ""}</b> &nbsp; {link(f"agenda:{target}", "Open agenda")}']
        for a in items:
            note = f' <span class="sub">{esc(clip(a.note, 90))}</span>' if a.subject and a.note else ""
            lines.append((self.task_link(a.subject) if a.subject else esc(a.note)) + note)
        return box("<br>".join(lines))

    def discarded_box(self, at: str, reason: str | None, hidden_from: str) -> str:
        """The note on a discarded task's or capture's page (mods log round 1, M0021)."""
        why = f": {esc(reason.rstrip('.'))}" if reason else ""
        return box(f"<b>Discarded</b> {esc(self.long(at[:10]))}{why}. It's hidden from {esc(hidden_from)}. Nothing is deleted: Bring back "
                   "restores it as it was.", "warn")

    # ---- the task page (the visual overhaul's O9, release 5.21, decisions 64 to 69) ----
    def has_agenda(self, t: Task) -> bool:
        return bool(self.m.open_items_for(t.id)) or (t.meeting and is_open(t))

    def task_page(self, task_id: str, state: PageState, width: int = 600, part: str = "all") -> str:
        """The task's story, top to bottom: where it sits and what it is, its current status, When and Who, a meeting's
        agenda, its subtasks, Details folded to one line, then its history. ``width`` is the page's: from WIDE_PAGE, When,
        Who and Details move into a rail on the right, and narrower than SIDE_BY_SIDE, When and Who stack.

        Since the notes page (release 5.25), the browse tool draws it in two ``part``s with the page's editor between
        them: "top", all but the history, and "bottom", the history. "all" is both, for anything that reads the page."""
        if part == "bottom":
            t = self.m.task(task_id)
            history = self.history(t, state)
            return (f'<table width="{min(width, PAGE_MAX)}" cellspacing="0" cellpadding="0"><tr><td>{history}</td></tr></table>'
                    if width >= WIDE_PAGE else history)
        if part == "top":
            return self._task_top(task_id, state, width, history=False)
        return self._task_top(task_id, state, width, history=True)

    def _task_top(self, task_id: str, state: PageState, width: int, history: bool) -> str:
        t = self.m.task(task_id)
        head = (self.discarded_box(t.discarded, t.discard_reason, "the task tree, the lists, the pickers, search and the capacity calendar")
                if t.discarded else "") + self.page_head(t, state)  # mods log round 1, M0021
        when, who = group("When", self.when_rows(t)) + self.key_dates_block(t), group("Who", self.who_rows(t))
        if width >= WIDE_PAGE:
            main = head + self.status_block(t) + self.agenda_section(t) + self.subtask_section(t, state) + (self.history(t, state) if history else "")
            return (f'<table width="{min(width, PAGE_MAX)}" cellspacing="0" cellpadding="0"><tr><td valign="top">{main}</td>'
                    f'<td width="24"></td><td width="1" class="rule"></td><td width="20"></td>'
                    f'<td width="{RAIL}" valign="top">{when}{who}{self.details(t, state, rail=True)}</td></tr></table>')
        facts = (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top: 8px"><tr><td width="50%" valign="top">{when}</td>'
                 f'<td width="50%" valign="top">{who}</td></tr></table>' if width >= SIDE_BY_SIDE else when + who)
        return (head + self.status_block(t) + facts + self.agenda_section(t) + self.subtask_section(t, state) + self.details(t, state)
                + (self.history(t, state) if history else ""))

    def page_head(self, t: Task, state: PageState) -> str:
        """The path (none for a top-level task), the title, the state, flags and labels, and the description in two lines."""
        m = self.m
        chains = [c for c in m.chains_of(t.id) if len(c) > 1]
        crumbs = ""
        if chains:
            more = ""
            if len(chains) > 1:
                others = "\n".join(" › ".join(m.task(x).title for x in c[:-1]) for c in chains[1:])
                more = f' &nbsp;<span class="rel" title="{esc(others)}">+{len(chains) - 1} more path{"s" if len(chains) > 2 else ""}</span>'
            crumbs = f'<p class="crumbs">{" › ".join(self.task_link(x, "tq") for x in chains[0][:-1])} ›{more}</p>'
        labels = "".join(f' <a href="{esc(label_href(name))}" title="{"Inherited from a parent task" if inherited else "Set on this task"}">'
                         f'{chip(name, "lbli" if inherited else "lbl")}</a>' for name, inherited in m.labels_of(t.id))
        tags = (state_chip(t.state) + self.priority_chip(t) + self.markers_html(t, critical=False) + (" " + chip("Meeting", "routine") if t.meeting else "")
                + (" " + chip("Plant event", "new") if t.plant_event else "") + labels)
        desc = ""
        if t.description:
            short_text = clip(t.description, DESC_CHARS)
            folded = short_text != t.description
            more = f' {link("fold:desc", "Less" if state.desc else "More")}' if folded else ""
            desc = f'<p class="desc">{multiline(t.description if state.desc or not folded else short_text)}{more}</p>'
        origin = m.origins.get(t.id)
        made = ""
        if origin:  # release 5.44: the template it came from
            gone = " (discarded)" if origin.discarded else ""
            made = f'<p class="rel">From template: {link(f"tplrow:{origin.row}", " › ".join(origin.path), "Open it in Templates")}{gone}</p>'
        return f'{crumbs}<h2 title="{t.id}">{esc(t.title)}</h2><p class="tags">{tags}</p>{desc}{made}'

    def status_since(self, t: Task) -> str | None:
        """When the current status last changed: its latest status log entry, or the day the task was made, for a status
        that came with it (the Excel import's)."""
        changes = [e.at for e in self.m.status if e.task == t.id and e.field == "Current status"]
        return max(changes)[:10] if changes else t.created[:10] if t.current_status else None

    def status_block(self, t: Task) -> str:
        """The page's one tinted block: where the task stands, and how long ago that was written."""
        name = "Final status" if t.state == "Closed" else "Current status"
        since = self.status_since(t)
        when = (f'<td align="right" class="rel" title="When the current status last changed">{esc(self.long(since))} · '
                f'{ago(to_date(since), self.today)}</td>' if t.current_status and since else "")
        body = (multiline(t.current_status) if t.current_status
                else f'<span class="sub">No status yet.</span> {link(f"update:{t.id}", "Add one", "Update this task")}')
        return (f'<table width="100%" cellspacing="0" cellpadding="12" style="margin-top: 12px"><tr><td class="stat">'
                f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td class="sk">{name}</td>{when}</tr></table>'
                f'<p class="stext">{body}</p></td></tr></table>')

    def days(self, day: date) -> str:
        """How far off a date is, in words, in critical red once it's passed."""
        text = esc(days_words(day, self.today))
        return f'<span class="over">{text}</span>' if day < self.today else text

    def key_dates_block(self, t: Task) -> str:
        """Its key dates (release 5.31, the key dates plan), under When: a line each, in its order, with its Done tick
        (decision 148), its dates (how far off while it's open), its description, ⚑ for a plant activity and a red ◆ for a
        deadline, done ones grey (decision 153), and Make it a subtask (item 61)."""
        from docrepo import key_dates

        kds = self.m.key_dates_of(t.id)
        if not kds:
            return ""
        today, lines = self.today, []
        for kd in kds:
            done = bool(kd.done)
            tick = link(f"kd:{'undone' if done else 'done'}:{kd.id}", "☑" if done else "☐",
                        "Not done after all" if done else "Mark it done: off Today and the Overdue list, logged")
            when = esc(key_dates.when_text(kd, today))
            _, last = key_dates.first_last(kd)
            if not done and is_open(t) and (kd.end or last >= today):
                when += f' <span class="rel">{self.days(last)}</span>'
            what = esc(kd.description) if kd.description else '<span class="sub">Key date</span>'
            marks = (' <span style="color:#875700">⚑ plant activity</span>' if kd.plant else "") + \
                    (' <span style="color:#b0261e">◆</span> <span class="rel">deadline</span>' if kd.deadline else "")
            # Kept on one line (no-break spaces), so a narrow column doesn't split it.
            sub = link(f"kd:subtask:{kd.id}", "Make it a subtask".replace(" ", "\u00a0"), "A subtask of this task with these dates, in its place", quiet="tq")
            text = f"{when}<br>{what}{marks}"
            if done:
                text = f'<span style="color:#87919c"><s>{key_dates.when_text(kd, today)}</s><br>{esc(kd.description or "Key date")}</span>' \
                       f' <span class="rel">done {esc(self.long(kd.done))}</span>'
            lines.append(f'<tr><td valign="top" width="18">{tick}</td><td valign="top">{text} <span class="rel">· {sub}</span></td></tr>')
        open_n = sum(1 for kd in kds if not kd.done)
        count = f' <span class="rel">{open_n} open</span>' if open_n != len(kds) else ""
        return section("Key dates", count) + f'<table cellspacing="0" cellpadding="3">{"".join(lines)}</table>'

    def when_rows(self, t: Task) -> list[tuple[str, str]]:
        """Only the dates that say something. Due is always there, so a missing one is still seen, unless a deadline takes
        its place (mods log round 1, M0003)."""
        today, rows, open_ = self.today, [], is_open(t)

        def dated(value: str | date, extra: str = "") -> str:
            d = to_date(value)
            return esc(long_date(d, today)) + (f' <span class="rel">{self.days(d)}</span>' if open_ else "") + extra

        def note(text: str) -> str:
            return f'<br><span class="rel">{esc(text)}</span>'

        if t.state == "Closed":
            rows.append(("Closed", esc(self.long(t.closed)) if t.closed else "Closed"))
        nxt = due_of(t, today) if t.recurrence and open_ else None
        if nxt:
            rows.append(("Next meeting" if t.meeting else "Next due", dated(nxt.date)))
        elif t.due:
            same = t.deadline == t.due
            rows.append(("Due", dated(t.due, note("Deadline too" + (f" · {t.deadline_desc}" if t.deadline_desc else "")) if same else "")))
        elif t.state != "Closed" and not t.recurrence and not t.deadline:
            rows.append(("Due", '<span class="sub">No due date</span>'))
        if t.deadline and t.deadline != t.due:
            rows.append(("Deadline", dated(t.deadline, note(t.deadline_desc) if t.deadline_desc else "")))
        if open_ and t.start and to_date(t.start) > today:
            rows.append(("Starts", dated(t.start)))
        if t.duration:  # release 5.46
            rows.append(("Duration", esc(f"{t.duration} day{'' if t.duration == 1 else 's'}, through weekends" if t.calendar_days
                                         else f"{t.duration} workday{'' if t.duration == 1 else 's'}")))
        for f, tie in t.ties.items():  # release 5.50: "3 workdays after Line 2 outage ends", linked
            source = self.m.tasks.get(tie.source)
            name = link(f"task:{tie.source}", source.title) if source else "a task"
            if tie.key_date is not None:
                name += esc(ties.name_in(self.m, tie)[len(source.title):]) if source else ""
            waits = "" if ties.ref_in(self.m, tie) else note("Waiting for that date")
            rows.append((f"{ties.FIELDS[f]} tied", ties.words(tie, name) + (' <span class="rel">discarded</span>' if source and source.discarded else "") + waits))
        tied = self.m.tied_to(t.id)
        if tied:
            mine = ties.tops(self.m.parents_of, t.id)

            def named(x: Task) -> str:
                top = next(iter(ties.tops(self.m.parents_of, x.id)))
                other = "" if ties.tops(self.m.parents_of, x.id) & mine or top == x.id else f' <span class="rel">{esc(self.m.task(top).title)}</span>'
                return link(f"task:{x.id}", x.title) + other
            rows.append(("Tied to this", ", ".join(named(x) for x in tied[:5]) + (f' <span class="rel">and {len(tied) - 5} more</span>' if len(tied) > 5 else "")))
        if open_ and t.reminder:
            r = to_date(t.reminder)
            rows.append(("Reminder", f'{esc(long_date(r, today))} <span class="rel">{ago(r, today) if r < today else days_words(r, today)}</span>'))
        on = self.m.agendas_on(t.id)
        if on:
            def when_met(target: str) -> str:
                meeting = target in self.m.tasks and self.m.task(target).meeting
                return f' <span class="rel">{esc(self.m.meeting_when(target, today))}</span>' if meeting else ""
            rows.append(("Agenda", "<br>".join(self.target_link(a.target) + when_met(a.target) for a in on)))
        return rows

    def avatar(self, person_id: str) -> str:
        """A person's initials in a circle, drawn by the browse window's page view; the owner gets a figure, as their name is
        Me, so "Me" isn't said twice."""
        name = self.m.person_name(person_id)
        key = "me" if person_id == self.me else initials(name)
        return f'<img src="avatar:{quote(key, safe="")}" width="20" height="20" style="vertical-align: middle" title="{esc(name)}">'

    def who_rows(self, t: Task) -> list[tuple[str, str]]:
        """Faces first, then names and hours."""
        per = " per occurrence" if t.recurrence else ""

        def people(ids: list[str], hours: float | None, role: str) -> str:
            # Release 5.46: hours a day show beside the total worked out from them, or ask for a length, as hours a week do since
            # release 5.49. Release 5.47: each person's own hours, by their Involvement, which says so.
            stated_rate = t.rate_of(role)
            rate = f"{num(stated_rate[0])} h a {stated_rate[1]}" if stated_rate else ""

            def text(p: str) -> str:
                share = t.share(role, p)
                tail = f"{share}%" if share != 100 else rate
                if hours:
                    return f"{num(round(hours * share / 100, 2))} h{per}" + (f" · {tail}" if tail else "")
                if rate:
                    return f"{rate}, needs a length"
                return tail

            return "<br>".join(f'{self.avatar(p)} {link(f"person:{p}", self.m.person_name(p))}' + (f' <span class="rel">{esc(text(p))}</span>' if text(p) else "")
                               for p in ids)

        rows = []
        if t.leads:
            rows.append(("Leads" if len(t.leads) > 1 else "Lead", people(t.leads, t.lead_hours, "lead")))
        if t.assignees:
            rows.append(("Assignees" if len(t.assignees) > 1 else "Assignee", people(t.assignees, t.assignee_hours, "assignee")))
        return rows or [("People", '<span class="sub">No one yet</span>')]

    def mark(self, t: Task) -> str:
        return f'<img src="mark:{MARKS.get(t.state, "ns")}" width="14" height="14" style="vertical-align: middle" title="{esc(t.state)}">'

    def agenda_section(self, t: Task) -> str:
        """A meeting's (or any agenda target's) open agenda items: for a meeting, they're what's next."""
        items = self.m.open_items_for(t.id)
        if not items:
            return ""
        rows = []
        for a in items:
            what = (f'{self.mark(self.m.task(a.subject))} {self.task_link(a.subject, "tl")}' if a.subject else esc(a.note))
            note = f' <span class="sub">{esc(clip(a.note, 90))}</span>' if a.subject and a.note else ""
            rows.append(f'<tr><td>{what}{note}</td><td align="right" class="rel" width="60">{esc(self.day(a.added))}</td></tr>')
        return (section("Agenda", f' <span class="rel">{len(items)} open</span> &nbsp;{link(f"agenda:{t.id}", "Open agenda")}')
                + f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(rows)}</table>')

    def subtask_section(self, t: Task, state: PageState) -> str:
        """How far along the subtasks are, the ones still to do, and the closed ones behind Show closed."""
        kids = [self.m.task(k) for k in self.m.children_of(t.id)]
        if not kids:
            return ""
        closed = [k for k in kids if k.state == "Closed"]
        shown = [k for k in kids if k.state != "Closed"] + (closed if state.closed else [])
        rows = []
        for k in shown:
            cell = due_cell(k, self.today)
            due = (f'<span class="over">{esc(cell.text)}</span>' if cell.cls == "over" else esc(cell.text)) if cell else ""
            who = ([*k.leads, *k.assignees] or [None])[0]
            rows.append(f'<tr><td width="18">{self.mark(k)}</td><td>{self.task_link(k.id, "tl")}{self.markers_html(k)}</td>'
                        f'<td align="right" class="rel" title="{esc(cell.tip) if cell else "No due date"}">{due}</td>'
                        f'<td width="24" align="right">{self.avatar(who) if who else ""}</td></tr>')
        count = f'{sum(is_open(k) for k in kids)} of {len(kids)} open'
        bar = f' <img src="progress:{len(closed)}:{len(kids)}" width="{PROGRESS_WIDTH}" height="4" title="{len(closed)} of {len(kids)} closed">'
        toggle = (f'<p class="more">{link("fold:closed", "Hide closed" if state.closed else f"Show {len(closed)} closed")}</p>' if closed else "")
        return (section("Subtasks", f' <span class="rel">{count}</span>{bar} &nbsp;{link(f"new:{t.id}", "New subtask", "A new task under this one (T)")}')
                + f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(rows)}</table>{toggle}')

    def details(self, t: Task, state: PageState, rail: bool = False) -> str:
        """The record: folded to one line that still shows the ID, the reference fields and when the task was made. In the
        wide page's rail there's room, so it's open."""
        m = self.m
        rows = [("ID", t.id), ("Created", f"{esc(self.long(t.created))} from {self.ref_link(t.created_by)}")]
        start = start_of(t)
        if not (t.start and start > self.today):  # a start still to come is in When
            rows.append(("Start", esc(long_date(start, self.today)) + ("" if t.start else ' <span class="rel">the day it was entered</span>')))
        if t.recurrence:
            rows.append(("Repeats", f"{esc(t.recurrence)}, {'until ' + esc(self.long(t.repeat_until)) if t.repeat_until else 'with no end date'}"))
        chains = [c for c in m.chains_of(t.id) if len(c) > 1]
        if len(chains) > 1:
            rows.append(("Parents", "<br>".join(" › ".join(self.task_link(x) for x in c[:-1]) for c in chains)))
        for name, value in t.references.items():  # reference fields (release 5.9, M0034)
            rows.append((name, f'{esc(value)} &nbsp;{link("copyref:" + quote(name, safe=""), "Copy")}'))
        rows.append(("Folder", link(f"folder:{t.id}", f"Tasks\\{t.id}", "Open it in File Explorer")))
        if rail:
            return group("Details", rows)
        if not state.details:
            made = f"Created {self.long(t.created)}" + (f" from {t.created_by}" if t.created_by else "")
            line = " · ".join([t.id, *(f"{k} {v}" for k, v in t.references.items()), made])
            return f'<p class="sec">{link("fold:details", "▸ Details")} &nbsp;<span class="rel">{esc(line)}</span></p>'
        return f'<p class="sec">{link("fold:details", "▾ Details")}</p>{fact_rows(rows)}'

    def history(self, t: Task, state: PageState) -> str:
        """The tabs with their counts for the scope, and the scope and order as two menus on the same line."""
        tab = "notes" if state.tab == "subtasks" else state.tab  # Subtasks is a section of its own now
        ids = self.m.scope_ids(t.id, state.scope)
        raw = {r.capture or f"V{r.document}{r.at}" for x in ids for r in self.stories.raw_items(x)}
        counts = {"notes": len(raw), "log": sum(len(self.stories.story(x)) for x in ids),
                  "summaries": sum(len(self.m.summaries_of(x)) for x in ids), "files": len(self.files_in(ids))}
        cells = "".join(f'<td class="tabon">{esc(label)} <span class="rel">{counts[key]}</span></td>' if key == tab
                        else f'<td><a href="tab:{key}"><span class="tab">{esc(label)}</span></a> <span class="rel">{counts[key]}</span></td>'
                        for key, label in TABS)
        controls = link("menu:scope", f"{SCOPE_NAMES[state.scope]} ▾", "Which tasks' entries to show")
        if tab in ("notes", "log"):
            controls += " &nbsp; " + link("menu:order", f"⇅ {'Newest' if state.order == 'new' else 'Oldest'} first", "Oldest or newest first")
        # The tabs have a table of their own: the selected one's underline would make a full-width table a pixel too wide.
        strip = (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top: 16px; margin-bottom: 4px"><tr>'
                 f'<td><table cellspacing="0" cellpadding="5"><tr>{cells}</tr></table></td>'
                 f'<td align="right" valign="middle" class="rel">{controls}</td></tr></table>')
        return strip + self.tab_body(t, state, tab, ids)

    def files_in(self, ids: list[str]) -> list:
        seen, out = set(), []
        for tid in ids:
            for f in self.m.files_of(tid):
                if (f.kind, f.name, f.task) not in seen:
                    seen.add((f.kind, f.name, f.task))
                    out.append(f)
        return out

    def tab_body(self, t: Task, state: PageState, tab: str, ids: list[str]) -> str:
        if tab in ("notes", "log"):
            return self.story_tab(t, state, ids, tab)
        if tab == "summaries":
            sums = sorted((s for tid in ids for s in self.m.summaries_of(tid)), key=lambda s: s.at, reverse=True)
            if not sums:
                return '<p class="note">No summaries yet. Use Copy prompt, then paste the answer into a capture\'s Summary.</p>'
            rows = []
            for s in sums:
                src = link(f"doc:{s.via}", s.type or "Summary") if s.via in self.m.documents else self.capture_link(s.via, s.type or "Summary")
                rows.append(f'<tr><td class="day" valign="top" width="60">{self.day(s.at)}</td><td>{src}{self.from_chip(s.task, t.id)}'
                            f"<br>{multiline(s.text)}</td></tr>")
            return f'<table cellspacing="0" cellpadding="4">{"".join(rows)}</table>'
        rows = []
        for f in self.files_in(ids):
            d = self.m.documents.get(f.document)
            name = (f'{link(f"doc:{f.document}", f.name, d.original if d else "")} · {link(f"copylink:{f.document}", "Copy link")}'
                    if f.kind == "Link" else link(self.show_key(f), f.name, "Show it in File Explorer"))
            rows.append(f'<tr><td>{name} <span class="sub">{esc(f.kind)}</span>'
                        f'{self.from_chip(f.task, t.id)}{"<br><span class=sub>" + esc(d.description) + "</span>" if d and d.description else ""}</td></tr>')
        # Decision 166: the Task view is where a task's files are searched, previewed and opened.
        more = f'<p>{link(f"taskview:{t.id}", "Open in Task view")} <span class="sub">to search, preview and open its files (O)</span></p>'
        return more + (f'<table cellspacing="0" cellpadding="4">{"".join(rows)}</table>' if rows else '<p class="note">No files yet.</p>')

    def show_key(self, f) -> str:
        if f.kind in ("Saved copy", "Old version"):
            copy = next((c for c in self.m.copies if c.task == f.task and c.name == f.name), None)
            return f"show:copy:{copy.id}" if copy else f"doc:{f.document}"
        return f"show:doc:{f.document}"

    # ---- stories ----
    def story_tab(self, t: Task, state: PageState, ids: list[str], kind: str) -> str:
        """This task's story, with its parents' and subtasks' as chapters under sentence-case headings. The order and the
        chapters' Open all and Close all are in the history's menus."""
        anc = [x for x in dict.fromkeys(y for chain in self.m.chains_of(t.id) for y in chain[:-1]) if x in ids]
        subs = [(x, d) for x, d in self.stories.subtask_tree(t.id) if x in ids]
        out = []
        if anc:
            out.append('<p class="chs">Parent tasks</p>' + "".join(self.chapter(x, 0, kind, state) for x in anc))
        if anc or subs:
            out.append('<p class="chs">This task</p>')
        out.append(self.story_body(t.id, kind, state))
        if subs:
            out.append(f'<p class="chs">Subtasks · {len(subs)}</p>' + "".join(self.chapter(x, d, kind, state) for x, d in subs))
        return "".join(out)

    def story_body(self, task_id: str, kind: str, state: PageState) -> str:
        if kind == "log":
            return self.story_list(self.stories.story(task_id), lambda e: self.log_item(e), state)
        items = self.stories.raw_items(task_id)
        if not items:
            return '<p class="note">Nothing has come in yet.</p>'
        on_page = notes_page.on_page(self.m, task_id, self.m.pages.get(task_id, ""))
        return self.story_list(items, lambda r: self.raw_item(r, state, task_id, on_page), state)

    def story_list(self, items: list, render: Callable, state: PageState) -> str:
        """Entries grouped by day, with a heading for each month when they span more than one."""
        xs = list(reversed(items)) if state.order == "new" else items
        days: list[tuple[str, list]] = []
        for x in xs:
            d = x.at[:10]
            if days and days[-1][0] == d:
                days[-1][1].append(x)
            else:
                days.append((d, [x]))
        spans = len({d[:7] for d, _ in days}) > 1
        rows, prev = [], ""
        for d, entries in days:
            if spans and d[:7] != prev:
                rows.append(f'<tr><td colspan="2" class="month">{MONTH_NAMES[int(d[5:7]) - 1]} {d[:4]}</td></tr>')
            prev = d[:7]
            rows.append(f'<tr><td class="day" valign="top" width="78">{esc(self.long(d))}</td>'
                        f'<td valign="top">{"".join(render(e) for e in entries)}</td></tr>')
        return f'<table width="100%" cellspacing="0" cellpadding="4">{"".join(rows)}</table>'

    def log_item(self, e: Event) -> str:
        src = f' <a href="capture:{esc(e.via)}" title="Open the capture, {esc(e.via)}"><span class="sub">note</span></a>' if e.via in self.m.captures else ""
        if e.kind == "sub":
            what = self.task_link(e.task) if e.task else esc(e.text)
            return f'<p>↳ {esc(e.verb)}: {what}{f" <span class=sub>· {esc(e.note)}</span>" if e.note else ""}</p>'
        if e.kind == "created":
            head = {"import": "Imported from the Excel tracker", "unfiled": "Made into a task from an unfiled capture", "new": "Created"}[e.how]
            where = f" under {' and '.join(self.task_link(p) for p in e.parents)}" if e.parents else "" if e.how == "import" else " as a top-level task"
            out = f"<p>{state_chip(e.state)} {head}{where}.{src}"
            if e.text:
                out += f"<br>{multiline(e.text)}"
            if e.status:
                out += f'<br><span class="sub">Status:</span> {multiline(e.status)}'
            if e.facts:
                out += f'<br><span class="facts">{" · ".join(esc(x) for x in e.facts)}</span>'
            return out + "</p>"
        facts = " ".join(e.facts)
        main = e.main or facts or ("" if e.state_words else "Updated, with no field changes.")
        rest = facts if e.main else ""
        out = f"<p>{state_chip(e.state, e.state_words) + ' ' if e.state_words else ''}{multiline(main)}{'' if rest else src}"
        if rest:
            out += f'<br><span class="facts">{esc(rest)}</span>{src}'
        return out + "</p>"

    def raw_item(self, r: RawItem, state: PageState, task_id: str = "", on_page: set[str] | None = None) -> str:
        """An entry on the Captures tab. A capture (release 5.25, decision 104) says whether its block is on the task's
        notes page, linking to it there, or offers to add it again (decision 109): its text is the page's to show. A
        document version still shows what changed."""
        key = r.capture or f"V{r.document}{r.at}"
        title = self.capture_link(r.capture, r.title, "tl") if r.capture else link(f"doc:{r.document}", r.title, quiet="tl")
        # An item (release 5.8) says whose notes it came from.
        notes = f' <span class="lead">· from the notes of</span> {self.capture_link(r.from_notes, r.from_title)}' if r.from_notes else ""
        out = f'<p><span class="lead">{esc(r.lead)}</span>{notes}<br><b>{title}</b>'
        if r.capture and on_page is not None:
            if r.capture in on_page:
                out += f'<br>{link(f"goto:{task_id}:{r.capture}", "On the notes page", "Show its block on the notes page")}'
            else:
                out += (f'<br><span class="sub">Not on the notes page</span> · '
                        f'{link(f"readd:{task_id}:{r.capture}", "Add it again", "Put its block back on the notes page, as it was added")}')
            if r.documents:
                out += '<br><span class="facts">Files: ' + ", ".join(link(f"doc:{d}", name, desc) for d, name, desc in r.documents) + "</span>"
            return out + "</p>"

        def shown(text: str) -> str:
            return markup.to_line_html(text) if r.formatted else multiline(text)

        if r.summary:
            out += f'<br><span class="lead">Summary · {esc(r.summary_type or "")}</span><br>{multiline(r.summary)}'
            if r.text:
                if key in state.originals:
                    out += f'<br>{link(f"orig:{key}", "Hide " + r.original_label.lower())}<br><span class="sub">{shown(r.text)}</span>'
                else:
                    out += f'<br>{link(f"orig:{key}", "Show " + r.original_label.lower())}'
        elif r.text:
            # A formatted capture's text is markup (mods log round 2, M0045): shown with its formatting, folded at a line.
            short_text = markup.clip(r.text, FOLD_CHARS) if r.formatted else clip(r.text, FOLD_CHARS)
            if short_text != r.text and key not in state.expanded:
                out += f'<br>{shown(short_text)} {link(f"more:{key}", "Show all")}'
            else:
                out += f"<br>{shown(r.text)}" + (f' {link(f"more:{key}", "Show less")}' if short_text != r.text else "")
        if r.documents:
            out += '<br><span class="facts">Files: ' + ", ".join(link(f"doc:{d}", name, desc) for d, name, desc in r.documents) + "</span>"
        return out + "</p>"

    def chapter(self, task_id: str, depth: int, kind: str, state: PageState) -> str:
        """Another task's story, behind a header with its state, latest status (or entry count) and latest date."""
        k = self.m.task(task_id)
        is_open_ = task_id in state.chapters
        notes = self.m.raw_log_of(task_id)
        empty = kind == "notes" and not notes
        dates = sorted(e.at for e in (self.stories.story(task_id) if kind == "log" else notes))
        summary = (k.current_status or "No status yet") if kind == "log" else "No entries" if empty else f"{len(notes)} entr{'ies' if len(notes) > 1 else 'y'}"
        caret = "" if empty else link(f"chap:{task_id}", "▼" if is_open_ else "▶")
        head = (f'<tr><td class="ch" width="{18 + 16 * depth}" align="right">{caret}</td><td class="ch"><b>{esc(k.title)}</b> {state_chip(k.state)} '
                f'<span class="sub">{esc(clip(summary, 90))}{" · " + self.day(dates[-1]) if dates else ""}</span>'
                f' &nbsp;<a href="task:{esc(task_id)}" title="Open {esc(k.title)}"><span class="sub">Open ↗</span></a></td></tr>')
        body = f'<tr><td></td><td>{self.story_body(task_id, kind, state)}</td></tr>' if is_open_ and not empty else ""
        return f'<table width="100%" cellspacing="0" cellpadding="3">{head}{body}</table>'

    # ---- the capture page ----
    def what_save_did(self, c: Capture) -> str:
        out = []
        if c.created_task:
            out.append(f"Created {self.task_link(c.created_task)}" + (f" under {self.task_link(c.task)}" if c.task else " as a top-level task"))
        if c.has("update") and c.task:
            out.append(f"Updated {self.task_link(c.task)}")
        if c.has("note") and c.task and not c.created_task:
            out.append(f"Added to the raw text log of {self.task_link(c.task)}")
        if c.filed_to:
            out.append(f"Filed to {self.task_link(c.filed_to)}")
        # Meeting notes and items (release 5.8).
        if c.meeting:
            out.insert(0, f"Made the meeting {self.task_link(c.meeting)}")
        if c.from_notes:
            out.append(f"An item from the notes in {self.capture_link(c.from_notes)}")
        made = [x for x in self.m.captures.values() if x.from_notes == c.id]
        if made:
            def what(x: Capture) -> str:
                return (f"task {self.task_link(x.created_task)}" if x.created_task else
                        f"{'decision on' if x.item == 'decision' else 'update to' if x.item == 'update' else 'note on'} {self.task_link(x.task)}" if x.task else esc(x.title))
            out.append(f"Made {len(made)} item{'s' if len(made) > 1 else ''}: " + ", ".join(f'{self.capture_link(x.id)} <span class="sub">{what(x)}</span>' for x in made))
        for a in self.m.agenda:
            if a.closed_by == c.id and a.added_by != c.id:
                out.append(f"Discussed {esc(self.m.task(a.subject).title) if a.subject else 'a note'} from the agenda of {self.target_link(a.target)}")
            if a.added_by == c.id:
                what = esc(self.m.task(a.subject).title) if a.subject else "a note"
                closed = f' <span class="sub">{esc((a.how or "").lower())} {self.day(a.closed)}</span>' if a.closed else ""
                out.append(f"Put {what} on {'' if a.target == TODAY else 'the agenda of '}{self.target_link(a.target)}{closed}")
        if not out:
            out.append("Kept as an unfiled capture, to file later" if self.m.is_unfiled(c) else "Nothing else")
        return "<br>".join(out)

    def capture_page(self, capture_id: str, content: str | None, old_versions: int = 0) -> str:
        c = self.m.captures[capture_id]
        rows = [("Saved", esc(f"{self.long(c.saved)} {c.saved[11:16]}")), ("Source", esc(SOURCE_NAMES.get(c.source, c.source))),
                ("Capture types", esc(", ".join(TYPE_NAMES[k] for k in c.types) or "None")), ("What Save did", self.what_save_did(c))]
        if c.filed:
            rows.append(("Filed", esc(f"{self.long(c.filed)} {c.filed[11:16]}")))
        changes = [e for e in self.m.status if e.via == c.id]
        if changes:
            rows.append(("Changes", "<br>".join(esc(f"{e.field}: {e.from_value or 'None'} → {e.to_value or 'None'}") for e in changes)))
        if c.email_layer_0:
            rows.append(("Email layer 0", esc(c.email_layer_0)))
        if c.documents:
            files = []
            for cd in c.documents:
                d = self.m.documents[cd.document]
                choices = (" · Link" if is_link(d.original) else "") + (" · Save a copy" if cd.save_a_copy else "") + (
                    " · Extract information" if cd.extract else "")
                files.append(f'{link(f"doc:{d.id}", d.name)} <span class="sub">{d.id}{choices}</span>'
                             + (f'<br><span class="sub">{esc(d.description)}</span>' if d.description else ""))
            rows.append(("Files", "<br>".join(files)))
        if c.summary:
            rows.append(("Summary", f'{multiline(c.summary)} <span class="sub">{esc(c.summary_type or "")}</span>'))
        if c.edited:
            kept = f' <span class="sub">{old_versions} earlier version{"s" if old_versions != 1 else ""} kept</span>' if old_versions else ""
            rows.append(("Edited", esc(f"{self.long(c.edited)} {c.edited[11:16]}") + kept))
        unfiled = ""
        if c.discarded:
            unfiled = self.discarded_box(c.discarded, c.discard_reason, "its tasks' logs, the Unfiled view and search. Its folder stays")
        if self.m.is_unfiled(c):
            unfiled = box("<b>Unfiled.</b> Pick a task and File to task, or Make it a task, with the buttons above. Filing links it to the task "
                          "and sets the task in its capture.md; the folder stays where it is.", "info")
        content = items.unstore(content) if content else content  # each @ and # by its name (release 5.8)
        shown = markup.to_html(content) if content and c.formatted else f'<span class="text">{multiline(content or "")}</span>'
        text = (box(f'<span class="sub">CONTENT TEXT</span><br>{shown}') if content
                else box('<span class="sub">CONTENT TEXT</span><br><span class="sub">None</span>') if content == ""
                else box("This capture's capture.md couldn't be read, so its content text can't be shown.", "warn"))
        return f'<p class="crumbs">Capture {c.id}</p><h2>{esc(c.title)}</h2>{unfiled}{fields_table(rows)}<p></p>{text}'

    # ---- documents, people and labels ----
    def document_page(self, document_id: str) -> str:
        m, d = self.m, self.m.documents[document_id]
        tasks = m.document_holders(document_id)
        copies = [f for f in m.copies if f.document == document_id]
        versions = [v for v in m.versions if v.document == document_id]
        text = {"ok": f"Extracted, {d.text_chars or 0:,} characters", "partial": f"Cut at {d.text_chars or 0:,} characters",
                "none": f"No text{': ' + d.text_note if d.text_note else ''}", "error": f"Couldn't be read{': ' + d.text_note if d.text_note else ''}"}
        if is_link(d.original):
            # A link (mods log round 1, M0001): only its address is kept, so it has no text, checks or saved copies.
            rows = [("File description", esc(d.description) if d.description else none_text("None yet")), ("ID", d.id),
                    ("Link", f"<span>{esc(d.original)}</span>"), ("Text", esc(f"No text: {NO_TEXT}")),
                    ("Tasks", ", ".join(self.task_link(x) for x in tasks) or none_text("Not filed yet"))]
            return (f'<p class="crumbs">Link {d.id}</p><h2>{esc(d.name)}</h2>{fields_table(rows)}'
                    '<p class="note">Copy link puts the address on the clipboard, to paste into your browser. DocRepo never opens it.</p>')
        rows = [("File description", esc(d.description) if d.description else none_text("None yet")), ("ID", d.id),
                ("Original", f"<span>{esc(d.original)}</span>" if d.original else f"Email attachment in {self.capture_link(d.capture)}" if d.capture else none_text()),
                ("Status", esc(d.status)), ("Text", esc(text.get(d.text_status or "", "Not read yet"))),
                ("Last checked", esc(d.checked[:16]) if d.checked else none_text("Not yet")),
                ("Versions", ", ".join(esc(self.long(v.at)) for v in versions) + f' <span class="sub">{len(versions)} change{"s" if len(versions) > 1 else ""} '
                             f'in the raw text log of its tasks</span>' if versions else none_text("No changes found yet")),
                ("Tasks", ", ".join(self.task_link(x) for x in tasks) or none_text("Not filed yet")),
                ("Saved copies", "<br>".join(link(f"show:copy:{f.id}", f"Tasks\\{f.task}\\Files\\{'_old versions' + chr(92) if f.old else ''}{f.name}")
                                             for f in copies) or none_text())]
        return f'<p class="crumbs">Document {d.id}</p><h2>{esc(d.name)}</h2>{fields_table(rows)}'

    def scheduled(self, person_id: str) -> tuple[float, float]:
        """A person's scheduled hours this week and next."""
        if self.conn is None:
            return 0.0, 0.0
        weeks = [monday_of(self.today), monday_of(self.today) + timedelta(weeks=1)]
        cells = capacity.week_cells(self.conn, weeks)
        return capacity.week_total(cells, person_id, weeks[0]), capacity.week_total(cells, person_id, weeks[1])

    def person_page(self, person_id: str) -> str:
        m, p = self.m, self.m.people[person_id]
        leads = [t.id for t in m.tasks.values() if is_open(t) and person_id in t.leads]
        assigned = [t.id for t in m.tasks.values() if is_open(t) and person_id in t.assignees]
        this_week, next_week = self.scheduled(person_id)
        chips = (" " + chip("me", "st-ip") if person_id == self.me else "") + (" " + chip("retired", "st-cl") if p.status == "retired" else "")
        rows = [("Aliases", esc(", ".join(p.aliases)) or none_text()),
                # Release 5.9 (mods log round 2, M0031, M0033, M0038): DocRepo only keeps the address; Copy email copies it.
                ("Email", esc(p.email) if p.email else none_text("None")), ("Group", esc(p.group) if p.group else none_text("None")),
                ("Role", esc(p.role) if p.role else none_text("None")),
                ("Hours a week", num(p.hours) if p.hours is not None else none_text("Not set")),
                ("Status", esc(p.status)), ("Scheduled", f"{this_week:.1f} h this week, {next_week:.1f} h next week"),
                ("Leads", ", ".join(self.task_link(x) for x in leads) or "None"), ("Assigned", ", ".join(self.task_link(x) for x in assigned) or "None")]
        added = f'<p class="note">{esc(p.added_note)}</p>' if p.added_note else ""
        return f'<p class="crumbs">Person {p.id}</p><h2>{esc(p.name)}{chips}</h2>{added}{fields_table(rows)}{self.agenda_block(person_id)}'

    def label_page(self, name: str) -> str:
        label = next(lb for lb in self.m.labels if lb.name == name)
        subs = self.m.sublabels(name, active=False)
        # Nested labels (release 5.9, M0051): a parent label lists its sublabels' tasks, under each sublabel.
        if subs:
            rows = [("Keywords", esc(", ".join(label.keywords)) or none_text()), ("Status", esc(label.status)),
                    ("Labels under it", ", ".join(link(label_href(s), s) for s in subs))]
            for s in subs:
                tasks = label_tasks(self.m, s)
                rows.append((s, "<br>".join(self.task_link(t) + (' <span class="sub">inherited</span>' if inh else "") for t, inh in tasks) or none_text()))
            return (f'<p class="crumbs">Label</p><h2>{esc(label.name)}</h2>{fields_table(rows)}'
                    '<p class="note">A label with labels under it is a heading: tasks get one of its labels, not it.</p>')
        tasks = label_tasks(self.m, name)
        parent = self.m.parent_label(name)
        rows = [*([("Under", link(label_href(parent), parent))] if parent else []),
                ("Keywords", esc(", ".join(label.keywords)) or none_text()), ("Status", esc(label.status)),
                ("Tasks", "<br>".join(self.task_link(t) + (' <span class="sub">inherited</span>' if inh else "") for t, inh in tasks) or none_text())]
        return f'<p class="crumbs">{"Label › " + esc(parent) if parent else "Label"}</p><h2>{esc(label.name)}</h2>{fields_table(rows)}'

    # ---- capacity ----
    def capacity_detail(self, rows: list[CapacityRow], weeks: list[date], cell: tuple[str, int] | None, unestimated: list[str],
                        unscheduled: list[str]) -> str:
        """Under the capacity grid: the tasks in the picked cell, then the tasks the calendar can't place."""
        if cell:
            person, i = cell
            row = next(r for r in rows if r.person == person)
            c = row.cells[i]
            lines = [f"{self.task_link(t)} <span class=sub>{h:.1f} h</span>" for t, h in c.tasks] or ['<span class="sub">No scheduled hours.</span>']
            out = box(f"<b>{esc(row.name)}, week of {esc(long_date(weeks[i], self.today))}</b><br>" + "<br>".join(lines))
        else:
            out = '<p class="note">Click a cell to see which tasks fill it.</p>'
        links = lambda ids: ", ".join(self.task_link(x) for x in ids) or "None"  # noqa: E731
        return (out + f'<p class="note"><b>Unestimated</b> (people, no hours): {links(unestimated)}</p>'
                f'<p class="note"><b>Unscheduled</b> (hours, no dates): {links(unscheduled)}</p>')
