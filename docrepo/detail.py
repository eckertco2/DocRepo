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

import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import quote

from docrepo import ask_update, capacity, decisions, email_conversations, items, markup, notes_page, repeats, tagged, task_tile, ties
from docrepo.dates import ago, days_words, long_date, monday_of, short, to_date
from docrepo.file_rows import dated_name, type_name
from docrepo.markup import esc
from docrepo.links import FOLDER_TEXT, NO_TEXT, is_folder, is_link, reference_link
from docrepo.model import PRIORITY_NAMES, TODAY, TYPE_NAMES, Capture, Model, Task, is_person
from docrepo.overview import file_type, sender_of
from docrepo.pages import num
from docrepo.schedule import due_of, held_on, is_open, start_of
from docrepo.stories import Event, RawItem, Stories, clip
from docrepo.task_links import SHOWN, all_documents, links_of
from docrepo.views import CapacityRow, label_tasks, markers

CSS = """
body { font-family: 'Segoe UI'; font-size: 10pt; color: #1a1f25; }
a { color: #1d5e98; text-decoration: none; }
h2 { font-size: 15pt; font-weight: 600; margin-top: 2px; margin-bottom: 4px; }
.crumbs { color: #5a6571; font-size: 9pt; margin: 0; }
.sub { color: #5a6571; font-size: 9pt; font-weight: 400; }
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
.caution { color: #875700; }
.critical { color: #b0261e; }
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
.tg { font-family: 'Cascadia Mono', 'Consolas'; color: #1a1f25; background-color: #f4f6f8; }
.tgn { font-family: 'Cascadia Mono', 'Consolas'; color: #875700; background-color: #fcefcf; }
.tgw { color: #875700; font-size: 8pt; }
.anchor { color: #1d5e98; background-color: #dbe8f5; }
.inh { color: #5a6571; font-style: italic; }
.new { color: #875700; background-color: #fcefcf; }
.u1 { background-color: #e2f2e6; }
.u2 { background-color: #fcefcf; }
.u3 { background-color: #fbe3e1; }
.sec { font-weight: 600; margin-top: 16px; margin-bottom: 4px; }
.secx { font-weight: 400; }
.factline { margin-top: 6px; margin-bottom: 0px; }
.ttl { font-weight: 600; }
.dt { color: #5a6571; font-size: 9pt; padding-right: 12px; }
.rel { color: #5a6571; font-size: 9pt; font-weight: 400; }
.over { color: #b0261e; }
.tile { background-color: #f4f6f8; border-bottom: 2px solid #ffffff; }
.stat { background-color: #f4f6f8; }
.sk { color: #5a6571; font-size: 9pt; }
.desc { color: #5a6571; margin-top: 4px; }
.lbli { color: #5a6571; }
.rule { background-color: #d6dce3; }
.tl { color: #1a1f25; }
.tq { color: #5a6571; }
.mark { background-color: #fff4ce; font-weight: 600; }
.line { margin: 0; }
.hitline { margin: 0; background-color: #fff4ce; }
.gap { margin: 0; color: #5a6571; }
.gk { color: #5a6571; padding-right: 10px; }
.relb { color: #5a6571; font-weight: 400; }
.grid { margin-top: 10px; }
"""

STATE_CLASS = {"Not started": "st-ns", "In progress": "st-ip", "Parked": "st-pk", "Closed": "st-cl"}
#: The task page's history (release 5.21): its tabs, and the names of its scopes. Subtasks is a section of its own now.
#: The history's tabs. The raw text log is Captures since the notes page (release 5.25, decision 104).
TABS = (("notes", "Captures"), ("log", "Status log"), ("summaries", "Summaries"), ("files", "Files"))
#: The History group's tabs since release 5.84 (the task pane review's R6): the status log is behind the status, the files are
#: a group of their own.
HISTORY_TABS = (("notes", "Captures"), ("summaries", "Summaries"))
#: The most files the Files group lists before pointing at Find files (release 5.84, decision P10).
FILES_SHOWN = 8
#: Find files' link in the Files group (release 5.98, the consolidation plan's decision 389: the Task view, renamed).
FIND_FILES_TIP = "Find files (O): a window of its own for searching, previewing and opening its files, emails and notes"
#: The Email conversations section's command (release 5.122, decision 455): New T-mail, as on the task page's bar.
NEW_T_MAIL_TIP = ("A new email in Outlook, empty, tagged so its replies come back to this task when you capture them. "
                  "You write and send it; DocRepo never sends email.")
CONVERSATION_TIP = "Open the conversation: every email of it DocRepo holds, oldest first"
#: The Decisions section's command (release 5.124, decision 479): the decision register, on the clipboard.
COPY_DECISIONS_TIP = ("Copy the decision register: a table of each decision's date, its words, its task and the meeting it came "
                      "from, for an email or a document")
#: The line between a conversation's emails: a block one pixel high in the rule's grey (Qt draws an <hr> dark).
RULE = '<p class="rule" style="font-size: 1px; margin-top: 16px; margin-bottom: 0px">&nbsp;</p>'
SCOPE_NAMES = {"self": "This task", "ancestors": "With parent tasks", "descendants": "With subtasks", "family": "Whole family"}
SOURCE_NAMES = {"typed": "Typed", "outlook_email": "Email", "file_path": "File path"}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
#: A raw text log entry longer than this folds, with Show all.
FOLD_CHARS = 360


def multiline(text: str) -> str:
    """Text as HTML, its line breaks kept as ``<br>``."""
    return esc(text).replace("\n", "<br>")


#: The arrows on a page: the icons' chevrons, which ``PageView`` draws, in place of typed glyphs (release 5.59).
CHEVRON_RIGHT = '<img src="chev:right" width="14" height="14">'
CHEVRON_DOWN = '<img src="chev:down" width="14" height="14">'


def fold_link(href: str, text: str, is_open: bool) -> str:
    """A heading that folds: its chevron, then its words in the text colour, as it isn't a link to anywhere."""
    return f'<a href="{esc(href)}">{CHEVRON_DOWN if is_open else CHEVRON_RIGHT} <span class="foldword">{esc(text)}</span></a>'


def chip(text: str, cls: str) -> str:
    """Words in a chip: a small tinted label of class ``cls``."""
    return f'<span class="{cls}">&nbsp;{esc(text)}&nbsp;</span>'


def row_state(state: str) -> str:
    """A task's state in a list's row (the review's decision V6): In progress in words, Not started and Closed quieter, and a chip
    only for Parked, so a chip says something needs a look."""
    if state == "Parked":
        return state_chip(state)
    return esc(state) if state == "In progress" else f'<span class="faint">{esc(state)}</span>'


def state_chip(state: str, text: str | None = None) -> str:
    """A task's state as its coloured chip, with ``text`` in place of the state's name when given."""
    return chip(text or state, STATE_CLASS.get(state, "st-ns"))


def link(href: str, text: str, title: str = "", quiet: str = "") -> str:
    """A link. ``quiet`` ("tl" for primary text, "tq" for secondary) colours it as text, for a title that's a link
    (release 5.21): blue stays for what reads as an action or a reference."""
    tip = f' title="{esc(title)}"' if title else ""
    words = f'<span class="{quiet}">{esc(text)}</span>' if quiet else esc(text)
    return f'<a href="{esc(href)}"{tip}>{words}</a>'


def label_href(name: str) -> str:
    """The link that opens a label's page."""
    return "label:" + quote(name, safe="")


def none_text(text: str = "None") -> str:
    """A grey placeholder for a field with nothing in it."""
    return f'<span class="sub">{esc(text)}</span>'


def fields_table(rows: list[tuple[str, str]]) -> str:
    """Rows of a name and its value, as a two-column table; the values are HTML already."""
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
    """A section's heading in Body Strong, with ``extra`` (a count, a link) after it, in the regular weight (release
    5.83, the task pane review's R10: the page keeps to the playbook's two weights)."""
    return f'<p class="sec">{esc(title)}<span class="secx">{extra}</span></p>'


def fact_rows(rows: list[tuple[str, str]]) -> str:
    """Facts as a short grey label beside its value, the values on one left edge."""
    cells = "".join(f'<tr><td class="dt" valign="top">{esc(k)}</td><td valign="top">{v}</td></tr>' for k, v in rows)
    return f'<table cellspacing="0" cellpadding="3">{cells}</table>'


def group(title: str, rows: list[tuple[str, str]]) -> str:
    """A titled section of fact rows, or nothing when there are no rows."""
    return section(title) + fact_rows(rows) if rows else ""


_SECTION = re.compile(r'^<p class="sec">(?:<a [^>]*>.*?</a> &nbsp;)?[^<]*<span class="secx">(.*?)</span></p>(.*)$', re.S)


#: How wide the facts grid gets on a wide pane (release 5.113).
GRID_MAX = 760


def grid_column(rows: list[tuple[str, str]]) -> str:
    """Rows of the facts grid (release 5.113): a grey name beside its value, both at the Body size, the names' column a
    fixed width, so values line up down the grid; the first column's words on the page's left edge."""
    cells = "".join(f'<tr><td class="gk" valign="top" style="padding: 3px 14px 3px 0px; white-space: nowrap">{esc(k)}</td>'
                    f'<td valign="top" style="padding: 3px 12px 3px 0px">{v}</td></tr>' for k, v in rows)
    return f'<table cellspacing="0" cellpadding="0">{cells}</table>'


def section_head(count: str, action: str = "", raw: bool = False) -> str:
    """An open section's summary beside its title (release 5.113, decision 423): its count in the secondary colour, then
    its one command at the right. ``count`` is HTML already when ``raw``."""
    words = count if raw else esc(count)
    left = f'<span class="rel">{words}</span>' if words else ""
    right = f'<td align="right" class="rel">{action}</td>' if action else ""
    return f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td valign="middle">{left}</td>{right}</tr></table>'


def split_section(html: str) -> tuple[str, str]:
    """A section's heading split from its body (release 5.84): what followed its title (a count, a link), and the rest,
    for the pane to show the section as an expander with the title on its button."""
    m = _SECTION.match(html)
    return (m.group(1).strip(), m.group(2)) if m else ("", html)


def initials(name: str) -> str:
    """``Tom Becker`` is TB, ``Todd`` is T."""
    words = [w for w in name.split() if w[:1].isalpha()] or [name or "?"]
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def box(inner: str, cls: str = "box") -> str:
    """HTML inside a full-width box of class ``cls``."""
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
    conversations: bool = False  # every email conversation shown, not only the newest few (release 5.122)
    decisions: bool = False  # every decision shown, not only the newest few (release 5.124)


class Pages:
    """Builds the pages for one Model, as of ``today``. ``content_of`` reads a capture's content text. ``hints`` adds the sentences
    that say how a page works, which show only with Show hints on (decision 7, release 5.59)."""

    def __init__(self, model: Model, today: date, content_of: Callable[[str], str], me: str | None = None,
                 conn: sqlite3.Connection | None = None, hints: bool = True, reference_links: Mapping[str, str] | None = None) -> None:
        self.m = model
        #: Settings' link address for each reference field (release 5.67, round 6's decision 320).
        self.reference_links = dict(reference_links or {})
        self.hints = hints
        self.today = today
        self.content_of = content_of
        self.me = me
        self.conn = conn
        self.stories = Stories(model, today, content_of, model.person_name(me) if me and me in model.people else None)

    # ---- small pieces ----
    def day(self, at: str) -> str:
        """A stored time's day, short, as the lists show one ("13 Oct")."""
        return short(to_date(at), self.today)

    def long(self, value: str) -> str:
        """A stored date with its weekday, as the pages write one ("Tue 13 Oct")."""
        return long_date(to_date(value), self.today)

    def task_link(self, task_id: str, quiet: str = "") -> str:
        """A link to a task's page, by its title; its ID alone when there's no such task."""
        return link(f"task:{task_id}", self.m.task(task_id).title, quiet=quiet) if task_id in self.m.tasks else esc(task_id)

    def capture_link(self, capture_id: str, text: str | None = None, quiet: str = "") -> str:
        """A link that opens a capture, with ``text`` or its ID as its words."""
        return link(f"capture:{capture_id}", text or capture_id, f"Open capture {capture_id}", quiet)

    def target_link(self, target: str) -> str:
        """A link to an agenda target: Today, a person or a task."""
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
        """Leads or assignees as links to their pages, each with their hours; per occurrence for a routine task."""
        if not person_ids:
            return none_text()
        per = ' <span class="sub">per occurrence</span>' if routine and hours else ""
        return ", ".join(link(f"person:{p}", self.m.person_name(p)) + (f' <span class="sub">{num(hours)} h</span>' if hours else "")
                         for p in person_ids) + per

    def markers_html(self, t: Task, critical: bool = True) -> str:
        """A task's markers (Critical, Urgent, routine, more than one parent) as chips, after a space each."""
        return "".join(" " + chip(text, cls) for text, cls in markers(self.m, t, critical))

    def priority_chip(self, t: Task) -> str:
        """The task page shows every bucket (release 5.23, decision 77); rows show only Critical."""
        return f" {chip(PRIORITY_NAMES[t.priority], 'pri-' + t.priority)}" if t.priority in PRIORITY_NAMES else ""

    def agenda_block(self, target: str) -> str:
        """A target's open agenda items, with a link to the agenda; empty when it has none."""
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
        """True when a task has open agenda items, or is an open meeting."""
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
        links = self.links_group(t)  # release 5.67, decision 316: after When and Who, in the rail on a wide page
        if width >= WIDE_PAGE:
            main = head + self.status_block(t) + self.agenda_section(t) + self.subtask_section(t, state) + (self.history(t, state) if history else "")
            return (f'<table width="{min(width, PAGE_MAX)}" cellspacing="0" cellpadding="0"><tr><td valign="top">{main}</td>'
                    f'<td width="24"></td><td width="1" class="rule"></td><td width="20"></td>'
                    f'<td width="{RAIL}" valign="top">{when}{who}{links}{self.details(t, state, rail=True)}</td></tr></table>')
        facts = (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top: 8px"><tr><td width="50%" valign="top">{when}</td>'
                 f'<td width="50%" valign="top">{who}</td></tr></table>' if width >= SIDE_BY_SIDE else when + who)
        return (head + self.status_block(t) + facts + links + self.agenda_section(t) + self.subtask_section(t, state) + self.details(t, state)
                + (self.history(t, state) if history else ""))

    # ---- the page in parts (release 5.84, the task pane review's T2: R1, R2, R6 and decisions P1, P4, P10; release 5.113's
    # facts grid took the fact line's and the When and who group's place, the task panel plan's decision 422) ----
    def task_parts(self, task_id: str, state: PageState, width: int = 600) -> dict[str, str]:
        """The page as the browse window draws it since release 5.84: the header (the path, title and description, and
        since release 5.113 the facts grid in place of the chips and the fact line), the status card's pieces with the
        status log behind it, and each section's summary (its count, and its command at the right), its few words for
        when it's closed (``<key>_short``) and its body; then the history's. Since release 5.113 there's no rail on a
        wide pane: the grid holds what it held, and the sections are the same at any width (the task panel plan's decision
        424). Everything here is also in ``task_page``, which draws the page as one, for reading."""
        t = self.m.task(task_id)
        out: dict[str, str] = {}
        out["head"] = (self.discarded_box(t.discarded, t.discard_reason, "the task tree, the lists, the pickers, search and the capacity calendar")
                       if t.discarded else "") + self.page_head(t, state, grid=self.facts_grid(t, width))
        out["title"] = t.title  # the sticky title line's words (release 5.86)
        out["status_name"], out["status_when"], out["status_age"], out["status_body"] = self.status_parts(t)
        out["status_asked"], out["status_asked_tip"] = self.asked_parts(t)
        log = self.stories.story(task_id)
        out["status_log"] = self.story_list(log, lambda e: self.log_item(e), state) if log else '<p class="note">No changes yet.</p>'
        out["status_log_summary"] = f"{len(log)} change{'s' if len(log) != 1 else ''}"
        kd = self.key_dates_block(t)
        if kd:
            kds = self.m.key_dates_of(t.id)
            open_n = sum(1 for x in kds if not x.done)
            out["key_dates_short"] = f"{open_n} open" if open_n != len(kds) else str(len(kds))
            out["key_dates_summary"], out["key_dates"] = section_head(out["key_dates_short"]), split_section(kd)[1]
        agenda = self.agenda_section(t)
        if agenda:
            n_open = len(self.m.open_items_for(t.id))
            out["agenda_short"] = f"{n_open} open"
            out["agenda_summary"] = section_head(out["agenda_short"], link(f"agenda:{t.id}", "Open agenda"))
            out["agenda"] = split_section(agenda)[1]
        subtasks = self.subtask_section(t, state)
        if subtasks:
            kids = [self.m.task(k) for k in self.m.children_of(t.id)]
            closed = sum(1 for k in kids if k.state == "Closed")
            out["subtasks_short"] = f"{sum(is_open(k) for k in kids)} of {len(kids)} open"
            bar = f'<img src="progress:{closed}:{len(kids)}" width="{PROGRESS_WIDTH}" height="4" title="{closed} of {len(kids)} closed">'
            out["subtasks_summary"] = section_head(f'{esc(out["subtasks_short"])} &nbsp;{bar}',
                                                   link(f"new:{t.id}", "New task under this one", "A new task under this one (T)"), raw=True)
            out["subtasks"] = split_section(subtasks)[1]
        ids = self.m.scope_ids(t.id, state.scope)
        # Decisions (release 5.124, decisions 477 to 479): the task's and its subtasks' decisions, newest first, after
        # Subtasks and before Email conversations, with Copy at the right; the section isn't there when they have none.
        found = decisions.of_tasks(self.m, ids)  # their words are read for the rows shown (decision_rows)
        if found:
            out["decisions_short"] = str(len(found))
            out["decisions_summary"] = section_head(out["decisions_short"], link(f"copydecisions:{t.id}", "Copy", COPY_DECISIONS_TIP))
            out["decisions"] = self.decision_rows(t, found, state)
        # Email conversations (release 5.122, decisions 455 and 456): the task's and its subtasks' emails, a row per
        # conversation; the section isn't there when they have none.
        convs = email_conversations.for_tasks(self.m, ids)
        if convs:
            n = sum(len(cv.emails) for cv in convs)
            out["emails_short"] = f"{len(convs)} · {n} email{'s' if n != 1 else ''}"
            out["emails_summary"] = section_head(out["emails_short"], link(f"tmail:{t.id}", "New T-mail", NEW_T_MAIL_TIP))
            out["emails"] = self.conversation_rows(t, convs, ids, state)
        links = self.links_group(t)
        if links:
            out["links_short"] = str(len(links_of(self.m, t.id, self.reference_links)))
            out["links_summary"], out["links"] = section_head(out["links_short"]), split_section(links)[1]
        files = self.files_in(ids)
        # Find files opens from here (release 5.98, the consolidation plan's decision 389), and with O; so the group shows
        # with no files too, as the mock has it, and Find files always has a way in by the mouse.
        out["files"] = self.files_body(t, files, FILES_SHOWN, intro=False)
        out["files_short"] = str(len(files)) if files else "none yet"
        out["files_summary"] = section_head(out["files_short"], link(f"taskview:{t.id}", "Find files", FIND_FILES_TIP))
        out["details"] = grid_column(self.details_rows(t))
        out["details_short"] = " · ".join(f"{k} {v}" for k, v in t.references.items())
        out["details_summary"] = section_head(out["details_short"])
        out["history"] = self.history(t, state, HISTORY_TABS)
        n = self.history_counts(ids)["notes"]
        out["history_short"] = f"{n} capture{'s' if n != 1 else ''}"
        out["history_summary"] = section_head(out["history_short"])
        return out

    def facts_grid(self, t: Task, width: int = 600) -> str:
        """The task's facts as one grid under its title (release 5.113, the task panel plan's decision 422): its state
        with its flags, then its dates (When's rows) on the left; its people (Who's rows) and its labels on the right; each
        a grey name beside its value, all at the Body size. From SIDE_BY_SIDE wide the two sit side by side, below it one
        under the other. It takes the place of the chips, the fact line and the When and who group."""
        left = [("Status", self.status_value(t)), *self.when_rows(t)]
        right = list(self.who_rows(t))
        labels = self.labels_value(t)
        if labels:
            right.append(("Labels", labels))

        column = grid_column
        if width >= SIDE_BY_SIDE:
            wide = f'width="{GRID_MAX}"' if width >= WIDE_PAGE else 'width="100%"'
            html = (f'<table {wide} cellspacing="0" cellpadding="0" class="grid"><tr><td width="50%" valign="top">{column(left)}</td>'
                    f'<td width="50%" valign="top">{column(right)}</td></tr></table>')
        else:
            html = f'<table width="100%" cellspacing="0" cellpadding="0" class="grid"><tr><td>{column(left + right)}</td></tr></table>'
        # One size on the grid: the grey words (how far off a date is, "No due date") are Body size here, not Caption (R10).
        return html.replace('class="rel"', 'class="relb"').replace('class="sub"', 'class="relb"')

    def status_value(self, t: Task) -> str:
        """The grid's Status: the state's mark and name, which open the state menu (a discarded task's are only words),
        then its priority, flags and kind as chips, as a chip says something needs a look (the visual review's V6)."""
        if t.discarded:
            state = f"{self.mark(t)} {esc(t.state)}"
        else:
            state = (f'<a href="state:{t.id}" title="{esc(t.state)}. Click to change the state." style="text-decoration: none">'
                     f'{self.mark(t)} <span class="tl">{esc(t.state)}</span>{CHEVRON_DOWN}</a>')
        # A meeting's dates already say it's one ("Next meeting", "Meeting"), so its chip would say it twice.
        said = t.meeting and any("eeting" in k for k, _ in self.when_rows(t))
        flags = (self.priority_chip(t) + self.markers_html(t, critical=False) + (" " + chip("Meeting", "routine") if t.meeting and not said else "")
                 + (" " + chip("Plant event", "new") if t.plant_event else ""))
        return state + (f" &nbsp;{flags.strip()}" if flags.strip() else "")

    def labels_value(self, t: Task) -> str:
        """The grid's Labels: each label's name, which opens its page; an inherited one in the secondary colour."""
        return ", ".join(link(label_href(name), name, "Inherited from a parent task" if inherited else "Set on this task", "tq" if inherited else "tl")
                         for name, inherited in self.m.labels_of(t.id))

    def page_head(self, t: Task, state: PageState, fact: str = "", grid: str | None = None) -> str:
        """The path (none for a top-level task), the title, the state, flags and labels, ``fact`` (the fact line, release
        5.84) and the description in two lines. With ``grid`` (the facts grid, release 5.113) the description follows the
        title and the grid takes the place of the chips and the fact line."""
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
        tags = (self.state_button(t) + self.priority_chip(t) + self.markers_html(t, critical=False) + (" " + chip("Meeting", "routine") if t.meeting else "")
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
        if grid is not None:
            return f'{crumbs}<h2 title="{t.id}">{esc(t.title)}</h2>{desc}{made}{grid}'
        return f'{crumbs}<h2 title="{t.id}">{esc(t.title)}</h2><p class="tags">{tags}</p>{fact}{desc}{made}'

    def state_button(self, t: Task) -> str:
        """The task's state under its title: a link that opens the state menu, with its chevron, as a page has no hover to show
        it on (release 5.76, round 7's decision 361). A discarded task's is only its chip."""
        if t.discarded:
            return state_chip(t.state)
        return (f'<a href="state:{t.id}" title="{esc(t.state)}. Click to change the state." style="text-decoration: none">'
                f'{state_chip(t.state)}{CHEVRON_DOWN}</a>')

    def status_since(self, t: Task) -> str | None:
        """When the current status last changed: its latest status log entry, or the day the task was made, for a status
        that came with it (the Excel import's)."""
        changes = [e.at for e in self.m.status if e.task == t.id and e.field == "Current status"]
        return max(changes)[:10] if changes else t.created[:10] if t.current_status else None

    def status_parts(self, t: Task) -> tuple[str, str, str, str]:
        """The status card's pieces (release 5.84): its name, the date its text last changed, how long ago that was (the
        date's tooltip, release 5.83's R7) and its body."""
        name = "Final status" if t.state == "Closed" else "Current status"
        since = self.status_since(t)
        when = self.long(since) if t.current_status and since else ""
        age = ago(to_date(since), self.today) if when else ""
        body = (multiline(t.current_status) if t.current_status
                else f'<span class="sub">No status yet.</span> {link(f"update:{t.id}", "Add one", "Update this task")}')
        return name, when, age, body

    def asked_parts(self, t: Task) -> tuple[str, str]:
        """The status card's "asked Mon" and its tooltip (release 5.125, the cold-eyes plan's decision 485), while an Ask for
        an update waits for a capture on the task; two empty strings otherwise."""
        opened = ask_update.asked(self.m, t.id)
        return (ask_update.asked_words(opened, self.today), ask_update.asked_tip(opened, self.today)) if opened else ("", "")

    def status_block(self, t: Task) -> str:
        """The page's one tinted block: where the task stands, the date that was written, and "asked Mon" while an Ask for
        an update waits (release 5.125)."""
        name, date, age, body = self.status_parts(t)
        asked, asked_tip = self.asked_parts(t)
        when = f'<td align="right" class="rel" title="The current status last changed {age}">{esc(date)}</td>' if date else ""
        if asked:
            when += f'<td align="right" class="rel" width="1" title="{esc(asked_tip)}">&nbsp;·&nbsp;{esc(asked)}</td>'
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
            marks = (' <span class="caution">⚑ plant activity</span>' if kd.plant else "") + \
                    (' <span class="critical">◆</span> <span class="rel">deadline</span>' if kd.deadline else "")
            # Kept on one line (no-break spaces), so a narrow column doesn't split it.
            sub = link(f"kd:subtask:{kd.id}", "Make it a subtask".replace(" ", "\u00a0"), "A subtask of this task with these dates, in its place", quiet="tq")
            text = f"{when}<br>{what}{marks}"
            if done:
                text = f'<span class="faint"><s>{key_dates.when_text(kd, today)}</s><br>{esc(kd.description or "Key date")}</span>' \
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
        elif held_on(t):  # a meeting's day, with no Due to count down to (release 5.82)
            rows.append(("Meeting", esc(long_date(held_on(t), today))))
        elif t.state != "Closed" and not t.recurrence and not t.deadline:
            rows.append(("Due", '<span class="sub">No due date</span>'))
        if t.deadline and t.deadline != t.due:
            rows.append(("Deadline", dated(t.deadline, note(t.deadline_desc) if t.deadline_desc else "")))
        if open_ and t.start and to_date(t.start) > today and not held_on(t):
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
        if open_ and t.reminder_repeat:  # release 5.117, decision 416
            until = f", until {long_date(to_date(t.reminder_until), today)}" if t.reminder_until else ""
            rows.append(("Repeats", f'{esc(repeats.describe(t.reminder_repeat))}<span class="rel">{esc(until)}</span>'))
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
        """A task's state as its small mark, with the state's name as its tooltip."""
        return f'<img src="mark:{MARKS.get(t.state, "ns")}" width="14" height="14" style="vertical-align: middle" title="{esc(t.state)}">'

    def agenda_section(self, t: Task) -> str:
        """A meeting's (or any agenda target's) open agenda items: for a meeting, they're what's next."""
        items = self.m.open_items_for(t.id)
        if not items:
            return ""
        rows = []
        marks = task_tile.marks(self.m, self.today)
        for a in items:
            note = f'<span class="sub">{esc(clip(a.note, 90))}</span>' if a.subject and a.note else ""
            added = f'<span class="rel">added {esc(self.day(a.added))}</span>'
            if a.subject and a.subject in self.m.tasks:  # a task tile (release 5.138, decision 577); every row is on this agenda
                tile = task_tile.tile(self.m, a.subject, self.today, marks, hide=("agenda",))
                rows.append(task_tile.html(tile, lambda href, text: link(href, text, quiet="tl"), " · ".join(x for x in (note, added) if x)))
            else:
                rows.append(f'<tr><td class="tile" width="20"></td><td class="tile">{esc(a.note)} {added}</td><td class="tile"></td>'
                            f'<td class="tile"></td></tr>')
        return (section("Agenda", f' <span class="rel">{len(items)} open</span> &nbsp;{link(f"agenda:{t.id}", "Open agenda")}')
                + f'{task_tile.TABLE}{"".join(rows)}</table>')

    def subtask_section(self, t: Task, state: PageState) -> str:
        """How far along the subtasks are, the ones still to do, and the closed ones behind Show closed."""
        kids = [self.m.task(k) for k in self.m.children_of(t.id)]
        if not kids:
            return ""
        closed = [k for k in kids if k.state == "Closed"]
        shown = [k for k in kids if k.state != "Closed"] + (closed if state.closed else [])
        rows = []
        marks = task_tile.marks(self.m, self.today)
        for k in shown:
            # A task tile (release 5.138, the task tile plan's decision 577): the circle opens the state menu, the title is cut
            # to fit, then the flag, the two-parents mark, who it's with, the marks and the days. Before 5.138 the date itself.
            who = ([*k.leads, *k.assignees] or [None])[0]
            tile = task_tile.tile(self.m, k.id, self.today, marks, under=t.id)
            rows.append(task_tile.html(tile, lambda href, text: link(href, text, quiet="tl"), self.avatar(who) if who else ""))
        count = f'{sum(is_open(k) for k in kids)} of {len(kids)} open'
        bar = f' <img src="progress:{len(closed)}:{len(kids)}" width="{PROGRESS_WIDTH}" height="4" title="{len(closed)} of {len(kids)} closed">'
        toggle = (f'<p class="more">{link("fold:closed", "Hide closed" if state.closed else f"Show {len(closed)} closed")}</p>' if closed else "")
        return (section("Subtasks", f' <span class="rel">{count}</span>{bar} &nbsp;{link(f"new:{t.id}", "New task under this one", "A new task under this one (T)")}')
                + f'{task_tile.TABLE}{"".join(rows)}</table>{toggle}')

    def reference_value(self, name: str, value: str) -> str:
        """A reference field's value in Details: a link to its page when Settings gives the field a link address (release
        5.67, decision 320), with Copy (the value) and Copy link; with no link address, Copy and Add a link (to Settings)."""
        copy = link("copyref:" + quote(name, safe=""), "Copy", f"Copy {name} {value}")
        address = reference_link(self.reference_links.get(name), value)
        if not address:
            return f'{esc(value)} &nbsp;{copy} &nbsp;{link("settings:reference", "Add a link", f"Give {name} a link address in Settings", "tq")}'
        return (f'{link("openurl:" + quote(address, safe=""), value, f"Opens in your browser: {address}")} &nbsp;{copy}'
                f' &nbsp;{link("copyaddr:" + quote(address, safe=""), "Copy link")}')

    def links_group(self, t: Task) -> str:
        """The task's links in one place (release 5.67, round 6's decision 316): its reference fields' links, then its
        pinned links, then the newest, SHOWN at most; each name opens it (a folder in File Explorer), with its host and
        Copy. With more, a link to Find files' Link type, named for what it lists (decision 323)."""
        xs = links_of(self.m, t.id, self.reference_links)
        if not xs:
            return ""
        marks = {"reference": "ref", "link": "link", "folder": "folder", "text": "note"}
        rows = []
        for x in xs[:SHOWN]:
            href = f"opendoc:{x.document}" if x.document else "openurl:" + quote(x.address, safe="")
            pin = ' <img src="lk:pin" width="12" height="12" title="Pinned on this task">' if x.pinned else ""
            copy = link("copyaddr:" + quote(x.address, safe=""), "Copy path" if x.kind == "folder" else "Copy", f"Copy {x.address}", "tq")
            rows.append(f'<tr><td valign="top" width="18"><img src="lk:{marks[x.kind]}" width="14" height="14"></td>'
                        f'<td valign="top">{link(href, x.name, x.opens)}{pin} <span class="sub">{esc(x.where)}</span> &nbsp;{copy}</td></tr>')
        more = ""
        if len(xs) > SHOWN:
            words = f"All {len(xs)} links" if all_documents(xs) else "Show link files in Find files"
            more = f'<p>{link(f"taskviewlinks:{t.id}", words, "Find files, showing only links")}</p>'
        return section("Links", f' <span class="sub">{len(xs)}</span>') + f'<table cellspacing="0" cellpadding="2">{"".join(rows)}</table>' + more

    def details_rows(self, t: Task) -> list[tuple[str, str]]:
        """The record's rows: the ID, when and from what the task was made, a passed start, the recurrence, every parent
        when there are several, each reference field, and the folder."""
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
        for name, value in t.references.items():  # reference fields (release 5.9, M0034), with their links (release 5.67)
            rows.append((name, self.reference_value(name, value)))
        if m.tagged:  # release 5.79, decision 367: from its fields, notes page, captures and documents
            tags = tagged.task_tags(m, t.id)
            rows.append(("Tagged labels", "&nbsp; ".join(self.tagged_chip(lb, n) for lb, n in tags) if tags
                         else none_text("None found in its fields, notes, captures or documents")))
        rows.append(("Folder", link(f"folder:{t.id}", f"Tasks\\{t.id}", "Open it in File Explorer")))
        return rows

    def details(self, t: Task, state: PageState, rail: bool = False) -> str:
        """The record: folded to one line that still shows the ID, the reference fields and when the task was made. In the
        wide page's rail there's room, so it's open."""
        rows = self.details_rows(t)
        if rail:
            return group("Details", rows)
        if not state.details:
            made = f"Created {self.long(t.created)}" + (f" from {t.created_by}" if t.created_by else "")
            line = " · ".join([t.id, *(f"{k} {v}" for k, v in t.references.items()), made])
            return f'<p class="sec">{fold_link("fold:details", "Details", False)} &nbsp;<span class="rel">{esc(line)}</span></p>'
        return f'<p class="sec">{fold_link("fold:details", "Details", True)}</p>{fact_rows(rows)}'

    def history_counts(self, ids: list[str]) -> dict[str, int]:
        """How many raw text log entries, status log entries, summaries and files these tasks have, for the tabs."""
        raw = {r.capture or f"V{r.document}{r.at}" for x in ids for r in self.stories.raw_items(x)}
        return {"notes": len(raw), "log": sum(len(self.stories.story(x)) for x in ids),
                "summaries": sum(len(self.m.summaries_of(x)) for x in ids), "files": len(self.files_in(ids))}

    def history(self, t: Task, state: PageState, tabs: tuple = TABS) -> str:
        """The tabs with their counts for the scope, and the scope and order as two menus on the same line. ``tabs`` is
        HISTORY_TABS on the pane since release 5.84; a tab that isn't there shows the captures."""
        tab = "notes" if state.tab == "subtasks" or state.tab not in {k for k, _ in tabs} else state.tab
        ids = self.m.scope_ids(t.id, state.scope)
        counts = self.history_counts(ids)
        cells = "".join(f'<td class="tabon">{esc(label)} <span class="rel">{counts[key]}</span></td>' if key == tab
                        else f'<td><a href="tab:{key}"><span class="tab">{esc(label)}</span></a> <span class="rel">{counts[key]}</span></td>'
                        for key, label in tabs)
        controls = f'<a href="menu:scope" title="Which tasks\' entries to show">{esc(SCOPE_NAMES[state.scope])} {CHEVRON_DOWN}</a>'
        if tab in ("notes", "log"):
            controls += " &nbsp; " + link("menu:order", f"⇅ {'Newest' if state.order == 'new' else 'Oldest'} first", "Oldest or newest first")
        # The tabs have a table of their own: the selected one's underline would make a full-width table a pixel too wide.
        strip = (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top: 16px; margin-bottom: 4px"><tr>'
                 f'<td><table cellspacing="0" cellpadding="5"><tr>{cells}</tr></table></td>'
                 f'<td align="right" valign="middle" class="rel">{controls}</td></tr></table>')
        return strip + self.tab_body(t, state, tab, ids)

    def files_in(self, ids: list[str]) -> list:
        """These tasks' files, each once, in the tasks' order."""
        seen, out = set(), []
        for tid in ids:
            for f in self.m.files_of(tid):
                if (f.kind, f.name, f.task) not in seen:
                    seen.add((f.kind, f.name, f.task))
                    out.append(f)
        return out

    def tab_body(self, t: Task, state: PageState, tab: str, ids: list[str]) -> str:
        """The body of the task page's history tab ``tab`` over these tasks."""
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
        return self.files_body(t, self.files_in(ids))

    def files_body(self, t: Task, files: list, limit: int | None = None, intro: bool = True) -> str:
        """The files as rows, each opening in File Explorer (a link in the browser, a folder in File Explorer), with Find
        files for searching, previewing and opening them (decision 166; the Task view until release 5.98, decision 389).
        ``limit`` shows the first so many, with the rest's count (the Files group, release 5.84). Without ``intro`` (the
        Files section since release 5.113, whose head has Find files at its right) the line about Find files is left out,
        and only "Show all n in Find files" follows the rows, when some aren't shown."""
        # Release 5.114 (the file rows review's decision 429): each file as a row of a list, not a run of blue links: its type's
        # mark, its name in the text's colour, the subtask it's on, its description under it, and the day it came in at the
        # end. Where it came from ("Saved copy", "Email attachment") is its tooltip; only an old version says so.
        came = {(c.task, d): c.saved for tid in dict.fromkeys(f.task for f in files) for c in self.m.notes_of(tid) for d in c.document_ids}
        # Each file once: a saved copy stands for its original on the same task (both are one document), so the list doesn't
        # show every name twice; an old version is a file of its own.
        listed, seen = [], set()
        for f in files:
            key = (f.kind, f.name, f.task) if f.kind == "Old version" else (f.document, f.task)
            if key not in seen:
                seen.add(key)
                listed.append(f)
        names = Counter(dated_name(f.name)[1] if f.kind in ("Saved copy", "Old version") else f.name for f in listed)
        rows = []
        for f in listed[:limit]:
            d = self.m.documents.get(f.document)
            original = d.original if d and d.original else ""
            kind = file_type(f.name, original)
            day, shown = dated_name(f.name) if f.kind in ("Saved copy", "Old version") else ("", f.name)
            day = day or came.get((f.task, f.document), "")[:10]
            if f.kind == "Link":  # it opens in the browser, on a click (release 5.67, decision 315)
                name = (f'{link(f"opendoc:{f.document}", shown, "Opens in your browser: " + original, "tl")} &nbsp;'
                        f'{link(f"copylink:{f.document}", "Copy link", "", "tq")} &nbsp;{link(f"doc:{f.document}", "Details", "", "tq")}')
            elif f.kind == "Folder":  # release 5.66: it opens in File Explorer
                name = (f'{link(f"opendoc:{f.document}", shown, "Opens in File Explorer: " + original, "tl")} &nbsp;'
                        f'{link("copyaddr:" + quote(original, safe=""), "Copy path", "", "tq")}')
            else:
                name = link(self.show_key(f), shown, f"{type_name(kind)} · {f.kind}. Click to show it in File Explorer.", "tl")
            # Only an old version says what it is, and a name two files share.
            old = f' <span class="sub">{esc(f.kind.lower())}</span>' if f.kind == "Old version" or names[shown] > 1 else ""
            desc = f'<br><span class="sub">{esc(d.description)}</span>' if d and d.description else ""
            when = esc(short(to_date(day), self.today)) if day else ""
            rows.append(f'<tr><td valign="top" width="22"><img src="ft:{kind}" width="16" height="16"></td>'
                        f'<td valign="top">{name}{old}{self.from_chip(f.task, t.id)}{desc}</td>'
                        f'<td valign="top" align="right" class="rel" width="64">{when}</td></tr>')
        if not rows:
            return '<p class="note">No files yet.</p>'
        # Decision 166: Find files is where a task's files are searched, previewed and opened; its link follows the list.
        left = len(listed) - len(rows)
        table = f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
        if left > 0:
            more = (f'<p style="margin-top: 4px">{link(f"taskview:{t.id}", f"Show all {len(files)} in Find files", FIND_FILES_TIP)} '
                    f'<span class="sub">(O)</span></p>')
        elif intro:
            more = f'<p style="margin-top: 4px">{link(f"taskview:{t.id}", "Find files", FIND_FILES_TIP)} <span class="sub">to search, preview and open them (O)</span></p>'
        else:
            more = ""
        return table + more

    # ---- decisions (release 5.124, the cold-eyes plan's decisions 477 to 479) ----
    def decision_rows(self, t: Task, found: list[decisions.Decision], state: PageState) -> str:
        """The Decisions section's body (decision 478): a row per decision, the newest first, as a conversation's row is
        drawn: the decision's mark, its words (its first line, all of them in the tooltip) in the text's colour, the subtask
        it's on (unless that's the meeting, which the next line names), a grey line naming the meeting it came from, and its
        day at the end. The words open its capture. The first ``SHOWN``, then Show all (decision 477); only the rows shown
        have their words read."""
        shown = found if state.decisions else found[:decisions.SHOWN]
        rows = []
        for d in (decisions.worded(self.m, x, self.content_of) for x in shown):
            tip = f"{d.more or d.words}\n\nClick to open its capture."
            words = link(f"capture:{d.capture}", d.words, tip, "tl")
            where = d.where(self.today)
            line = (f'<br><span class="sub">in {link(f"task:{d.meeting}", where, "Open the meeting", "tq")}</span>'
                    if where and d.meeting in self.m.tasks else f'<br><span class="sub">in {esc(where)}</span>' if where else "")
            chip = "" if d.task == d.meeting else self.from_chip(d.task, t.id)  # on the meeting itself: its line names it
            rows.append(f'<tr><td valign="top" width="22"><img src="lk:decision" width="14" height="14"></td>'
                        f'<td valign="top">{words}{chip}{line}</td>'
                        f'<td valign="top" align="right" class="rel" width="64">{esc(self.day(d.saved))}</td></tr>')
        table = f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
        if len(found) > decisions.SHOWN:
            words = "Show fewer" if state.decisions else f"Show all {len(found)} decisions"
            table += f'<p style="margin-top: 4px">{link("fold:decisions", words)}</p>'
        return table

    def decision_register(self, task_id: str, scope: str = "descendants") -> list[tuple[str, str, str, str]]:
        """The decision register the Decisions section's Copy puts on the clipboard (decision 479): every decision on the
        task and the tasks under it (the page's scope), newest first, as Date, Decision, Task and Where."""
        return decisions.rows(self.m, decisions.of_tasks(self.m, self.m.scope_ids(task_id, scope), self.content_of), self.today)

    # ---- email conversations (release 5.122, the email section plan's decisions 455 to 463) ----
    def me_name(self) -> str | None:
        """The owner's name, which a conversation says as "you"."""
        return self.m.person_name(self.me) if self.me and self.me in self.m.people else None

    def senders(self, cv: email_conversations.Conversation) -> list[str]:
        """Who wrote a conversation's emails; for an email kept without its rows (decision 463), from its From line."""
        return list(dict.fromkeys(x for x in (self.sender(e) for e in cv.emails) if x))

    def sender(self, e: email_conversations.Email) -> str:
        return e.sender or (sender_of(self.content_of(e.capture)) if e.pos < 0 else "")

    def conversation_rows(self, t: Task, convs: list, ids: list[str], state: PageState) -> str:
        """The Email conversations section's body (decision 458): a row per conversation, the newest first, as a file's row
        is drawn (release 5.114): the mail mark, its subject in the text's colour with its count of emails in grey and the
        subtask it's on, a grey line of who's written and the newest email's first words, and its newest day at the end.
        The subject opens the conversation's page. The first ``SHOWN``, then Show all (decision 456)."""
        ec = email_conversations
        me = self.me_name()
        shown = convs if state.conversations else convs[:ec.SHOWN]
        rows = []
        for cv in shown:
            n = len(cv.emails)
            subject = link(f"conv:{t.id}/{cv.id}", cv.subject, CONVERSATION_TIP, "tl")
            count = f' <span class="rel">&nbsp;{n}</span>' if n > 1 else ""
            where = ec.task_in(cv, ids)
            words = ec.snippet(ec.newest_words(self.m, cv, self.content_of))
            line = esc(ec.who(self.senders(cv), me)) + (f" · {esc(words)}" if words else "")
            rows.append(f'<tr><td valign="top" width="22"><img src="ft:mail" width="16" height="16"></td>'
                        f'<td valign="top">{subject}{count}{self.from_chip(where or "", t.id)}<br><span class="sub">{line}</span></td>'
                        f'<td valign="top" align="right" class="rel" width="64">{esc(short(to_date(cv.newest.at), self.today))}</td></tr>')
        table = f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
        if len(convs) > ec.SHOWN:
            words = "Show fewer" if state.conversations else f"Show all {len(convs)} conversations"
            table += f'<p style="margin-top: 4px">{link("fold:conversations", words)}</p>'
        return table

    def conversation_page(self, task_id: str, conversation_id: str, state: PageState) -> str:
        """A conversation's page (decision 459), opened from a task's Email conversations: back to the task, the subject, a
        line of facts, then every email of it DocRepo holds, oldest first, each with its sender, when, To, its own words
        (the quoted emails folded, decision 462), its capture's files, and Open in Outlook, Reply all and Open capture."""
        ec = email_conversations
        cv = ec.find(self.m, conversation_id)
        back = (f'<p class="crumbs">{link(f"task:{task_id}", "‹ " + self.m.task(task_id).title, "Back to the task")}</p>'
                if task_id in self.m.tasks else "")
        if cv is None:
            return back + '<p class="note">This conversation isn\'t here any more: the captures of its emails were discarded.</p>'
        me = self.me_name()
        n = len(cv.emails)
        first, last = cv.emails[0].at, cv.newest.at
        span = self.day(first) if first[:10] == last[:10] else f"{self.day(first)} to {self.day(last)}"
        tasks = cv.tasks()
        on = "on " + ", ".join(self.task_link(x) for x in tasks) if tasks else '<span class="faint">not filed to a task</span>'
        head = (back + f"<h2>{esc(cv.subject)}</h2>"
                + f'<p class="facts">{esc(ec.who(self.senders(cv), me, most=6))} · {n} email{"s" if n != 1 else ""} · {esc(span)} · {on}</p>')
        blocks, filed = [], set()
        for i, e in enumerate(cv.emails):
            text = ec.email_text(self.m, e, self.content_of(e.capture))
            own, quoted = ec.own_words(text.words)
            sender = ec.who([self.sender(e)], me) if self.sender(e) else "An unknown sender"
            when = f"{self.long(e.at)} {e.at[11:16]}".strip()
            to = f'<span class="sub"> &nbsp;to {esc(clip(ec.to_words(text.to, me), 120))}</span>' if text.to else ""
            newest = f" &nbsp;{chip('Newest', 'st-ip')}" if i == n - 1 and n > 1 else ""
            # An email whose subject was changed says its own (a reply joined by In-Reply-To, decision 457).
            own_subject = (f'<br><span class="sub">Subject: {esc(e.subject)}</span>'
                           if e.subject and ec.clean_subject(e.subject) != cv.subject else "")
            parts = [f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top: {4 if i == 0 else 16}px"><tr>'
                     f'<td valign="top"><span class="ttl">{esc(sender[:1].upper() + sender[1:])}</span>{to}{newest}{own_subject}</td>'
                     f'<td valign="top" align="right" class="rel" style="white-space: nowrap">{esc(when)}</td></tr></table>']
            if own:
                parts.append(f'<p style="margin-top: 6px; margin-bottom: 0px">{multiline(own)}</p>')
            else:
                parts.append('<p class="note" style="margin-top: 6px">DocRepo has none of its words here; its capture\'s page has what was kept.</p>')
            if quoted:
                key = f"q:{e.ref}"
                if key in state.expanded:
                    parts.append(f'<p class="sub" style="margin-top: 6px">{multiline(quoted)}</p>'
                                 f'<p class="sub">{link("more:" + key, "Hide the quoted emails")}</p>')
                else:
                    parts.append(f'<p class="sub" style="margin-top: 4px">{link("more:" + key, "Show the quoted emails", "What it quotes of the emails before it")}</p>')
            if text.note:
                parts.append(f'<p class="sub" style="margin-top: 6px">Your words with it: {multiline(clip(text.note, 400))}</p>')
            if e.capture not in filed:  # a capture's files, under the first of its emails here (decision 461)
                filed.add(e.capture)
                parts.append(self._capture_files(e.capture))
            acts = []
            if e.can_open:
                acts.append(link(f"outlook:{e.ref}", "Open in Outlook", "The email itself in Outlook: from its place there, else its saved .msg"))
                acts.append(link(f"replyall:{e.ref}", "Reply all", "Reply all in Outlook, as a T-mail: its replies come back to its task"))
            acts.append(self.capture_link(e.capture, "Open capture"))
            where = (self.from_chip(e.tasks[0], task_id) if task_id not in e.tasks else "") if e.tasks else ' <span class="faint">not filed</span>'
            also = f' <span class="faint">· also in {esc(", ".join(c for c, _p in e.also))}</span>' if e.also else ""
            parts.append(f'<p class="sub" style="margin-top: 6px">{" &nbsp;·&nbsp; ".join(acts)}{where}{also}</p>')
            blocks.append("".join(parts))
        return head + RULE.join(blocks)

    def _capture_files(self, capture_id: str) -> str:
        """A capture's files under its email on a conversation's page: its attachments, and the links and pictures email
        layer 0 kept, each a row with its type's mark (decision 461)."""
        c = self.m.captures[capture_id]
        rows = []
        for doc_id in c.document_ids:
            d = self.m.documents.get(doc_id)
            if d is None:
                continue
            kind = file_type(d.name, d.original)
            if is_link(d.original) or is_folder(d.original):
                name = link(f"opendoc:{d.id}", d.name, ("Opens in your browser: " if is_link(d.original) else "Opens in File Explorer: ") + (d.original or ""), "tl")
            else:
                name = link(f"show:doc:{d.id}", d.name, f"{type_name(kind)} · Email attachment. Click to show it in File Explorer.", "tl")
            desc = f' <span class="sub">{esc(d.description)}</span>' if d.description else ""
            rows.append(f'<tr><td valign="top" width="22"><img src="ft:{kind}" width="16" height="16"></td><td valign="top">{name}{desc}</td></tr>')
        return f'<table cellspacing="0" cellpadding="2" style="margin-top: 6px">{"".join(rows)}</table>' if rows else ""

    def show_key(self, f) -> str:
        """The address that shows a file in File Explorer: a saved copy's, else its document's."""
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
        """A task's status log or raw text log as a list, with the page's folding and order."""
        if kind == "log":
            return self.story_list(self.stories.story(task_id), lambda e: self.log_item(e), state)
        items = self.stories.raw_items(task_id)
        if not items:
            return '<p class="note">Nothing has come in yet.</p>'
        on_page = notes_page.on_page(self.m, task_id, self.m.pages.get(task_id, ""), self.stories)
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
        """One status log entry as a line, with a link to the capture that made it."""
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
        out = f'<p><span class="lead">{esc(r.lead)}</span>{notes}<br><span class="ttl">{title}</span>'
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
        caret = "" if empty else f'<a href="chap:{esc(task_id)}">{CHEVRON_DOWN if is_open_ else CHEVRON_RIGHT}</a>'
        head = (f'<tr><td class="ch" width="{18 + 16 * depth}" align="right">{caret}</td><td class="ch"><span class="ttl">{esc(k.title)}</span> {state_chip(k.state)} '
                f'<span class="sub">{esc(clip(summary, 90))}{" · " + self.day(dates[-1]) if dates else ""}</span>'
                f' &nbsp;<a href="task:{esc(task_id)}" title="Open {esc(k.title)}"><span class="sub">Open ↗</span></a></td></tr>')
        body = f'<tr><td></td><td>{self.story_body(task_id, kind, state)}</td></tr>' if is_open_ and not empty else ""
        return f'<table width="100%" cellspacing="0" cellpadding="3">{head}{body}</table>'

    # ---- the capture page ----
    def what_save_did(self, c: Capture) -> str:
        """What saving a capture made and changed, in words with links."""
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
        """A capture's page: its facts, what its save did, its files and its content text (``content``, read from capture.md)."""
        c = self.m.captures[capture_id]
        rows = [("Saved", esc(f"{self.long(c.saved)} {c.saved[11:16]}")), ("Source", esc(SOURCE_NAMES.get(c.source, c.source))),
                ("Capture types", esc(", ".join(TYPE_NAMES[k] for k in c.types) or "None")), ("What Save did", self.what_save_did(c))]
        if c.filed:
            rows.append(("Filed", esc(f"{self.long(c.filed)} {c.filed[11:16]}")))
        changes = [e for e in self.m.status if e.via == c.id]
        if changes:
            rows.append(("Changes", "<br>".join(esc(f"{e.field}: {e.from_value or 'None'} → {e.to_value or 'None'}") for e in changes)))
        if c.emails:  # each email, its .msg file and what it's about (round 7's item 93, release 5.74)
            # Reply all beside each email DocRepo can find (release 5.105, the knowledge base's stage K8, release B).
            tip = "Reply all in Outlook, as a T-mail: its replies come back to its task"
            reply = {e.pos: f' &nbsp;{link(f"replyall:{c.id}:{e.pos}", "Reply all", tip)}' for e in c.emails
                     if (e.entry_id or e.file) and not c.discarded}
            rows.append(("Emails", "<br>".join(
                f'{esc(e.subject or "(no subject)")} <span class="sub">{esc(e.file or "not saved as a file")}</span>{reply.get(e.pos, "")}'
                + (f"<br>{esc(e.description)}" if e.description else "") for e in c.emails)))
        if c.email_layer_0:
            rows.append(("Email layer 0", esc(c.email_layer_0)))
        if c.documents:
            files = []
            for cd in c.documents:
                d = self.m.documents[cd.document]
                choices = (" · Link" if is_link(d.original) else " · Folder" if is_folder(d.original) else "") + (" · Save a copy" if cd.save_a_copy else "") + (
                    " · Extract information" if cd.extract else "")
                files.append(f'{link(f"doc:{d.id}", d.name)} <span class="sub">{d.id}{choices}</span>'
                             + (f'<br><span class="sub">{esc(d.description)}</span>' if d.description else ""))
            rows.append(("Files", "<br>".join(files)))
        if c.summary:
            rows.append(("Summary", f'{multiline(c.summary)} <span class="sub">{esc(c.summary_type or "")}</span>'))
        if self.m.tagged:  # release 5.79, decision 367: once there's a glossary
            rows.append(("Tagged labels", self.tagged_row("capture", c.id)))
        if c.edited:
            kept = f' <span class="sub">{old_versions} earlier version{"s" if old_versions != 1 else ""} kept</span>' if old_versions else ""
            rows.append(("Edited", esc(f"{self.long(c.edited)} {c.edited[11:16]}") + kept))
        unfiled = ""
        if c.discarded:
            unfiled = self.discarded_box(c.discarded, c.discard_reason, "its tasks' logs, the Unfiled view and search. Its folder stays")
        if self.m.is_unfiled(c):
            unfiled = (box("<b>Unfiled.</b> Pick a task and File to task, or Make it a task, with the buttons above. Filing links it to the task "
                           "and sets the task in its capture.md; the folder stays where it is.", "info") if self.hints
                       else f'<p>{chip("Unfiled", "st-ns")}</p>')
        content = items.unstore(content) if content else content  # each @ and # by its name (release 5.8)
        shown = markup.to_html(content) if content and c.formatted else f'<span class="text">{multiline(content or "")}</span>'
        text = (box(f'<span class="sub">Content text</span><br>{shown}') if content
                else box('<span class="sub">Content text</span><br><span class="sub">None</span>') if content == ""
                else box("This capture's capture.md couldn't be read, so its content text can't be shown.", "warn"))
        return f'<p class="crumbs">Capture {c.id}</p><h2>{esc(c.title)}</h2>{unfiled}{fields_table(rows)}<p></p>{text}'

    # ---- documents, people and labels ----
    def document_page(self, document_id: str) -> str:
        """A document's page: its facts, the tasks it's on, its saved copies and its versions."""
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
                    ("Tasks", ", ".join(self.task_link(x) for x in tasks) or none_text("Not filed yet")), *self.tagged_rows("document", d.id)]
            return (f'<p class="crumbs">Link {d.id}</p><h2>{esc(d.name)}</h2>{fields_table(rows)}'
                    '<p class="note">Open link hands it to your default browser, only when you click it (release 5.67). Copy link puts the address on the clipboard. DocRepo never fetches it.</p>')
        if is_folder(d.original):
            # A folder (release 5.66, round 6's decision 318): kept by where it is, with no text, checks or saved copies.
            rows = [("File description", esc(d.description) if d.description else none_text("None yet")), ("ID", d.id),
                    ("Folder", f"<span>{esc(d.original)}</span>"), ("Text", esc(f"No text: {FOLDER_TEXT}")),
                    ("Tasks", ", ".join(self.task_link(x) for x in tasks) or none_text("Not filed yet")), *self.tagged_rows("document", d.id)]
            return (f'<p class="crumbs">Folder {d.id}</p><h2>{esc(d.name)}</h2>{fields_table(rows)}'
                    '<p class="note">Show in File Explorer opens the folder.</p>')
        rows = [("File description", esc(d.description) if d.description else none_text("None yet")), ("ID", d.id),
                ("Original", f"<span>{esc(d.original)}</span>" if d.original else f"Email attachment in {self.capture_link(d.capture)}" if d.capture else none_text()),
                ("Status", esc(d.status)), ("Text", esc(text.get(d.text_status or "", "Not read yet"))),
                ("Last checked", esc(d.checked[:16]) if d.checked else none_text("Not yet")),
                ("Versions", ", ".join(esc(self.long(v.at)) for v in versions) + f' <span class="sub">{len(versions)} change{"s" if len(versions) > 1 else ""} '
                             f'in the raw text log of its tasks</span>' if versions else none_text("No changes found yet")),
                ("Tasks", ", ".join(self.task_link(x) for x in tasks) or none_text("Not filed yet")),
                ("Saved copies", "<br>".join(link(f"show:copy:{f.id}", f"Tasks\\{f.task}\\Files\\{'_old versions' + chr(92) if f.old else ''}{f.name}")
                                             for f in copies) or none_text())]
        rows += self.tagged_rows("document", d.id)
        return f'<p class="crumbs">Document {d.id}</p><h2>{esc(d.name)}</h2>{fields_table(rows)}'

    # ---- tagged labels (release 5.79, the tagged labels plan, decisions 367, 376 and 379) ----
    def tagged_chip(self, lb: tagged.Label, n: int = 0, item: str = "") -> str:
        """A tagged label as a small plate in the mono font, so it doesn't read as a task's label. It opens the label's
        page; ``item`` ("capture:C000123") adds × to remove it from that item. A suggested one, new from a pattern (release
        5.80, decision 374), is marked new, with the pattern's name on hover."""
        if lb.status == "suggested":
            tip = f"New: found by the {lb.pattern or ''} pattern, and not in the glossary yet"
            out = (f'<a href="tagged:{quote(lb.key, safe="")}" title="{esc(tip)}"><span class="tgn">&nbsp;{esc(lb.label)}&nbsp;</span></a>'
                   '<span class="tgw">&nbsp;new</span>')
        else:
            out = f'<a href="tagged:{quote(lb.key, safe="")}" title="{esc(lb.description or "A tagged label")}"><span class="tg">&nbsp;{esc(lb.label)}&nbsp;</span></a>'
        if n > 1:
            out += f'<span class="tq">&nbsp;{n}</span>'
        if item:
            what = "capture" if item.startswith("capture:") else "document"
            out += "&nbsp;" + link(f"taggedrm:{item}:{quote(lb.key, safe='')}", "×", f"Remove {lb.label} from this {what}. It stays removed.", "tq")
        return out

    def tagged_row(self, kind: str, item_id: str) -> str:
        """A capture's or document's tagged labels, each with × (decision 376), then Add, and any removed by the owner."""
        tg = self.m.tagged
        chips = [self.tagged_chip(lb, m.n if m else 0, f"{kind}:{item_id}") for lb, m in tg.item(kind, item_id)]
        add = link(f"taggedadd:{kind}:{item_id}", "Add", "Add a tagged label by hand, from the glossary", "tq")
        removed = tg.removed(kind, item_id)
        back = ('<br><span class="sub">Removed by you: ' + ", ".join(
            link(f"taggedback:{kind}:{item_id}:{quote(lb.key, safe='')}", lb.label, "Add it back") for lb in removed) + "</span>") if removed else ""
        return ("&nbsp;&nbsp;".join(chips) if chips else none_text("None found")) + f" &nbsp;{add}{back}"

    def tagged_rows(self, kind: str, item_id: str) -> list[tuple[str, str]]:
        """The Tagged labels row for an item, when there's a glossary; else none."""
        return [("Tagged labels", self.tagged_row(kind, item_id))] if self.m.tagged else []

    def _use_text(self, u: tagged.Use) -> str:
        if u.kind == "task":
            return tagged.task_text(self.m.task(u.id), self.m)
        if u.kind == "page":
            return tagged.page_text(self.m.pages.get(u.id, ""))
        if self.conn is None:
            return ""
        row = self.conn.execute("SELECT body FROM search_text WHERE kind = ? AND id = ?", (u.kind, u.id)).fetchone()
        return tagged.text_of_body(u.kind, row["body"]) if row else ""

    def _use_snippet(self, u: tagged.Use, lb: tagged.Label) -> str:
        """The words around the first mention, with the mention in bold."""
        text = self._use_text(u)
        hit = next((h for h in self.m.tagged.finder().find(text) if h.label == lb.id), None)
        if hit is None:
            return '<span class="sub">Added by you</span>' if u.how == "hand" else ""
        a, b = max(0, hit.start - 60), min(len(text), hit.end + 80)

        def one(part: str) -> str:
            return esc(" ".join(part.split()))

        return (f'<span class="sub">{"…" if a else ""}{one(text[a:hit.start])} </span><b>{one(text[hit.start:hit.end])}</b>'
                f'<span class="sub"> {one(text[hit.end:b])}{"…" if b < len(text) else ""}</span>')

    def _use_line(self, u: tagged.Use) -> tuple[str, str, list[str]]:
        """A use's link and grey words, its date to sort by, and the tasks it belongs to."""
        m = self.m
        if u.kind == "capture":
            c = m.captures[u.id]
            kind = "Email" if c.source == "email" else "Capture"
            return (f'{self.capture_link(c.id, c.title)} <span class="sub">{c.id} · {kind} · {esc(self.day(c.saved))}</span>', c.saved,
                    m.capture_tasks(c))
        if u.kind == "document":
            d = m.documents[u.id]
            when = min((c.saved for c in m.captures.values() if u.id in c.document_ids), default="")
            return f'{link(f"doc:{d.id}", d.name)} <span class="sub">{d.id} · Document</span>', when, m.document_holders(d.id)
        t = m.task(u.id)
        if u.kind == "page":
            return f'{link(f"task:{t.id}", f"Notes of {t.title}")} <span class="sub">{t.id} · its notes page</span>', "", [t.id]
        return f'{self.task_link(t.id)} <span class="sub">{t.id} · the task&#8217;s own fields</span>', t.created or "", [t.id]

    def tagged_page(self, key: str) -> str:
        """A tagged label's page (decision 379): its description and aliases, how it's found, how it's written, and every
        item that mentions it, newest first, under each top-level task, with the words around it."""
        m, lb = self.m, self.m.tagged.by_key[key]
        uses = tagged.uses_of(m, lb)
        written: dict[str, int] = {}
        for u in uses:
            for w, n in u.written.items():
                written[w] = written.get(w, 0) + n
        source = f" from {esc(lb.source)}" if lb.source else ""
        suggested = lb.status == "suggested"
        came = {"import": f"Imported{source}", "hand": "Added by hand",
                "pattern": f"Found by the {esc(lb.pattern or '')} pattern" + ("" if suggested else ", then added to the glossary")}.get(lb.came, "")
        found = (f"New: found by the <b>{esc(lb.pattern or '')}</b> pattern, spelled as its mask is, and not in the glossary"
                 if suggested else "In the glossary: " + (f"however its parts are joined ({esc(', '.join(tagged.spellings(lb.label)))})"
                                                          if len(tagged.spellings(lb.label)) > 1 else "as it's written")
                 + (", and by its aliases" if lb.aliases else ""))
        rows = [*([] if suggested else [("Description", esc(lb.description) or none_text("None")),
                                        ("Aliases", esc("; ".join(lb.aliases)) or none_text("None"))]),
                ("How it's found", found),
                ("Written as", ", ".join(f'<span class="tg">&nbsp;{esc(w)}&nbsp;</span> <span class="tq">{n}</span>'
                                          for w, n in sorted(written.items(), key=lambda x: -x[1])) or none_text("Not found anywhere yet")),
                ("Mentioned in", f"{len(uses)} item{'s' if len(uses) != 1 else ''}"),
                ("Added", f"{esc(self.long(lb.added))} · {came}" if lb.added else came)]
        groups: dict[str | None, list[tuple[str, str]]] = {}
        for u in uses:
            line, when, tasks = self._use_line(u)
            tops = list(dict.fromkeys(m.chains_of(x)[0][0] for x in tasks if x in m.tasks)) or [None]
            entry = (when, f'<p class="line">{line}<br>{self._use_snippet(u, lb)}</p>')
            for top in tops:
                groups.setdefault(top, []).append(entry)
        order = sorted(groups, key=lambda g: (g is None, -len(groups[g]), m.task(g).title if g else ""))
        body = "".join(f'<p class="sec">{self.task_link(g) if g else "Not filed yet"} <span class="sub">{len(groups[g])}</span></p>'
                       + "".join(e for _, e in sorted(groups[g], key=lambda x: x[0], reverse=True)) for g in order)
        crumbs = "Tagged label" if lb.status == "glossary" else "Tagged label · suggested"
        what = ('<p class="note">Suggested (decision 374): it&#8217;s on what mentions it already, marked new. <b>Add to glossary</b> '
                'makes it an ordinary tagged label, with a description. <b>Same as…</b> makes it an alias of another label and moves '
                'its mentions there. <b>Not a tag</b> removes it everywhere and puts it on Never a tag, so no pattern suggests it '
                'again.</p>') if suggested else ""
        plate = f'<span class="tgn">&nbsp;{esc(lb.label)}&nbsp;</span><span class="tgw">&nbsp;new</span>' if suggested else \
            f'<span class="tg">&nbsp;{esc(lb.label)}&nbsp;</span>'
        return (f'<p class="crumbs">{crumbs}</p><h2>{plate}</h2>{fields_table(rows)}{what}'
                + (body if uses else '<p class="note">Nothing mentions it yet.</p>'))

    def scheduled(self, person_id: str) -> tuple[float, float]:
        """A person's scheduled hours this week and next."""
        if self.conn is None:
            return 0.0, 0.0
        weeks = [monday_of(self.today), monday_of(self.today) + timedelta(weeks=1)]
        cells = capacity.week_cells(self.conn, weeks)
        return capacity.week_total(cells, person_id, weeks[0]), capacity.week_total(cells, person_id, weeks[1])

    def person_page(self, person_id: str) -> str:
        """A person's page: their open tasks as lead and assignee, their hours this week and next, and their agenda."""
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
        tags = f'<p class="tags">{chips.strip()}</p>' if chips else ""  # under the name, at the chips' own size
        summary = link(f"summary:person:{p.id}", "Quick summary", "Their agenda, the tasks you share and what's changed (release 5.131)")
        return f'<p class="crumbs">Person {p.id} &nbsp;{summary}</p><h2>{esc(p.name)}</h2>{tags}{added}{fields_table(rows)}{self.agenda_block(person_id)}'

    def label_page(self, name: str) -> str:
        """A label's page: its tasks, or its sublabels' tasks under each sublabel."""
        label = next(lb for lb in self.m.labels if lb.name == name)
        subs = self.m.sublabels(name, active=False)
        # Nested labels (release 5.9, M0051): a parent label lists its sublabels' tasks, under each sublabel.
        if subs:
            rows = [("Keywords", esc(", ".join(label.keywords)) or none_text()), ("Status", esc(label.status)),
                    ("Labels under it", ", ".join(link(label_href(s), s) for s in subs))]
            for s in subs:
                tasks = label_tasks(self.m, s)
                rows.append((s, "<br>".join(self.task_link(t) + (' <span class="sub">inherited</span>' if inh else "") for t, inh in tasks) or none_text()))
            return (f'<p class="crumbs">Label &nbsp;{self.summary_link(name)}</p><h2>{esc(label.name)}</h2>{fields_table(rows)}'
                    '<p class="note">A label with labels under it is a heading: tasks get one of its labels, not it.</p>')
        tasks = label_tasks(self.m, name)
        parent = self.m.parent_label(name)
        rows = [*([("Under", link(label_href(parent), parent))] if parent else []),
                ("Keywords", esc(", ".join(label.keywords)) or none_text()), ("Status", esc(label.status)),
                ("Tasks", "<br>".join(self.task_link(t) + (' <span class="sub">inherited</span>' if inh else "") for t, inh in tasks) or none_text())]
        return (f'<p class="crumbs">{"Label › " + esc(parent) if parent else "Label"} &nbsp;{self.summary_link(name)}</p>'
                f'<h2>{esc(label.name)}</h2>{fields_table(rows)}')

    def summary_link(self, label_name: str) -> str:
        """A label's Quick summary (release 5.131): where its open tasks stand, what needs attention and what's changed."""
        return link("summary:label:" + quote(label_name, safe=""), "Quick summary", "Where its open tasks stand, what needs attention, what's changed")

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
            out = '<p class="note">Click a cell to see which tasks fill it.</p>' if self.hints else ""
        links = lambda ids: ", ".join(self.task_link(x) for x in ids) or "None"  # noqa: E731
        return (out + f'<p class="note"><b>Unestimated</b> (people, no hours): {links(unestimated)}</p>'
                f'<p class="note"><b>Unscheduled</b> (hours, no dates): {links(unscheduled)}</p>')
