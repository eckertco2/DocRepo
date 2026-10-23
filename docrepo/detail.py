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

from docrepo import capacity, markup
from docrepo.dates import days_text, long_date, monday_of, short, to_date
from docrepo.links import NO_TEXT, is_link
from docrepo.model import TODAY, TYPE_NAMES, Capture, Model, Task, is_person
from docrepo.pages import num
from docrepo.schedule import due_of, is_open, start_of
from docrepo.stories import Event, RawItem, Stories, clip
from docrepo.views import CapacityRow, label_tasks, markers, rem_text

CSS = """
body { font-family: 'Segoe UI'; font-size: 10pt; color: #1a1f25; }
a { color: #1d5e98; text-decoration: none; }
h2 { font-size: 15pt; font-weight: 600; margin-top: 2px; margin-bottom: 4px; }
.crumbs { color: #5a6571; font-size: 9pt; margin: 0; }
.sub { color: #5a6571; font-size: 9pt; }
.faint { color: #87919c; }
.k { color: #5a6571; padding-right: 12px; }
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
.chs { color: #87919c; font-size: 9pt; font-weight: 600; }
.ch { background-color: #f4f6f8; }
.st-ns { color: #5a6571; background-color: #eef1f4; }
.st-ip { color: #1d5e98; background-color: #dbe8f5; }
.st-pk { color: #585a70; background-color: #eae8f2; }
.st-cl { color: #87919c; background-color: #e9edf1; }
.urgent { color: #b0261e; background-color: #fbe3e1; font-weight: 600; }
.routine { color: #1a1f25; background-color: #e9edf1; }
.multi { color: #1d5e98; background-color: #e4eefa; }
.lbl { color: #1a1f25; background-color: #e9edf1; }
.inh { color: #5a6571; font-style: italic; }
.new { color: #875700; background-color: #fcefcf; }
.u1 { background-color: #e2f2e6; }
.u2 { background-color: #fcefcf; }
.u3 { background-color: #fbe3e1; }
"""

STATE_CLASS = {"Not started": "st-ns", "In progress": "st-ip", "Parked": "st-pk", "Closed": "st-cl"}
TABS = (("notes", "Raw text log"), ("summaries", "Summaries"), ("log", "Status log"), ("files", "Files"), ("subtasks", "Subtasks"))
SCOPES = (("self", "This task"), ("ancestors", "With ancestors"), ("descendants", "With subtasks"), ("family", "Family"))
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


def link(href: str, text: str, title: str = "") -> str:
    tip = f' title="{esc(title)}"' if title else ""
    return f'<a href="{esc(href)}"{tip}>{esc(text)}</a>'


def label_href(name: str) -> str:
    return "label:" + quote(name, safe="")


def none_text(text: str = "None") -> str:
    return f'<span class="sub">{esc(text)}</span>'


def fields_table(rows: list[tuple[str, str]]) -> str:
    cells = "".join(f'<tr><td class="k" width="118" valign="top">{esc(k)}</td><td valign="top">{v}</td></tr>' for k, v in rows)
    return f'<table cellspacing="0" cellpadding="3">{cells}</table>'


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

    def task_link(self, task_id: str) -> str:
        return link(f"task:{task_id}", self.m.task(task_id).title) if task_id in self.m.tasks else esc(task_id)

    def capture_link(self, capture_id: str, text: str | None = None) -> str:
        return link(f"capture:{capture_id}", text or capture_id, f"Open capture {capture_id}")

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

    def markers_html(self, t: Task) -> str:
        return "".join(" " + chip(text, cls) for text, cls in markers(self.m, t))

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

    # ---- the task page ----
    def has_agenda(self, t: Task) -> bool:
        return bool(self.m.open_items_for(t.id)) or (t.meeting and is_open(t))

    def task_page(self, task_id: str, state: PageState) -> str:
        m, t = self.m, self.m.task(task_id)
        crumbs = "".join(
            f'<p class="crumbs">{" › ".join(self.task_link(x) for x in chain[:-1])} ›</p>' if len(chain) > 1 else '<p class="crumbs">Top-level task</p>'
            for chain in m.chains_of(task_id))
        labels = "".join(f' <a href="{esc(label_href(name))}" title="{"Inherited from a parent" if inherited else "Set on this task"}">'
                         f'{chip(name, "inh" if inherited else "lbl")}</a>' for name, inherited in m.labels_of(task_id))
        chips = state_chip(t.state) + self.markers_html(t) + (" " + chip("Meeting", "routine") if t.meeting else "") + labels + f' &nbsp;<span class="sub">{t.id}</span>'
        routine = bool(t.recurrence)
        rows = [
            ("Description", multiline(t.description) if t.description else none_text("None")),
            ("Current status", multiline(t.current_status) if t.current_status else none_text("None yet")),
            ("Lead", self.roles(t.leads, t.lead_hours, routine)),
            ("Assignees", self.roles(t.assignees, t.assignee_hours, routine)),
            ("Start", esc(long_date(start_of(t), self.today)) + ("" if t.start else ' <span class="sub">date entered</span>')),
            ("Due", f'{esc(self.long(t.due))} <span class="sub">{days_text(to_date(t.due), self.today)}</span>' if t.due
             # With no Due, the deadline shows in its place, marked (mods log round 1, M0003); nothing changes in docs.db.
             else f'{esc(self.long(t.deadline))} <span class="sub">(deadline) {days_text(to_date(t.deadline), self.today)}</span>'
             if t.deadline and not routine else none_text()),
            ("Deadline", f'{esc(self.long(t.deadline))}{", " + esc(t.deadline_desc) if t.deadline_desc else ""} '
                         f'<span class="sub">{days_text(to_date(t.deadline), self.today)}</span>' if t.deadline else none_text()),
            ("Reminder", f'{esc(self.long(t.reminder))} <span class="sub">{rem_text(to_date(t.reminder), self.today)}</span>' if t.reminder else none_text()),
        ]
        if t.recurrence:
            nxt = due_of(t, self.today)
            rows.append(("Recurrence", f"{esc(t.recurrence)}, {'until ' + esc(self.long(t.repeat_until)) if t.repeat_until else 'no end date'}."
                         + (f" Next: {esc(long_date(nxt.date, self.today))}" if nxt else "")))
        on = m.agendas_on(task_id)
        if on:
            rows.append(("On agendas", "<br>".join(f'{self.target_link(a.target)} <span class="sub">since {self.day(a.added)}</span>' for a in on)))
        if t.closed:
            rows.append(("Closed", esc(self.long(t.closed))))
        rows.append(("Created", f"{esc(self.long(t.created))} from {self.ref_link(t.created_by)}"))
        if t.discarded:  # mods log round 1, M0021
            crumbs += self.discarded_box(t.discarded, t.discard_reason, "the task tree, the lists, the pickers, search and the capacity calendar")
        return (f"{crumbs}<h2>{esc(t.title)}</h2><p>{chips}</p>{fields_table(rows)}{self.agenda_block(task_id)}"
                f"{self.tab_bar(state)}{self.tab_body(t, state)}")

    def tab_bar(self, state: PageState) -> str:
        cells = "".join(f'<td class="tabon">&nbsp;{esc(label)}&nbsp;</td>' if key == state.tab
                        else f'<td>&nbsp;{link(f"tab:{key}", label)}&nbsp;</td>' for key, label in TABS)
        scope = ""
        if state.tab != "subtasks":
            scope = "Scope: " + " · ".join(f"<b>{esc(label)}</b>" if key == state.scope else link(f"scope:{key}", label) for key, label in SCOPES)
        return (f'<p></p><table cellspacing="0" cellpadding="5"><tr>{cells}</tr></table>'
                f'<p class="sub">{scope}</p>' if scope else f'<p></p><table cellspacing="0" cellpadding="5"><tr>{cells}</tr></table>')

    def tab_body(self, t: Task, state: PageState) -> str:
        ids = self.m.scope_ids(t.id, state.scope)
        if state.tab in ("notes", "log"):
            return self.story_tab(t, state, ids)
        if state.tab == "summaries":
            sums = sorted((s for tid in ids for s in self.m.summaries_of(tid)), key=lambda s: s.at, reverse=True)
            if not sums:
                return '<p class="note">No summaries yet. Use Copy prompt, then paste the answer into a capture\'s Summary.</p>'
            rows = []
            for s in sums:
                src = link(f"doc:{s.via}", s.type or "Summary") if s.via in self.m.documents else self.capture_link(s.via, s.type or "Summary")
                rows.append(f'<tr><td class="day" valign="top" width="60">{self.day(s.at)}</td><td>{src}{self.from_chip(s.task, t.id)}'
                            f"<br>{multiline(s.text)}</td></tr>")
            return f'<table cellspacing="0" cellpadding="4">{"".join(rows)}</table>'
        if state.tab == "files":
            seen, rows = set(), []
            for tid in ids:
                for f in self.m.files_of(tid):
                    key = (f.kind, f.name, f.task)
                    if key in seen:
                        continue
                    seen.add(key)
                    d = self.m.documents.get(f.document)
                    name = (f'{link(f"doc:{f.document}", f.name, d.original if d else "")} · {link(f"copylink:{f.document}", "Copy link")}'
                            if f.kind == "Link" else link(self.show_key(f), f.name, "Show it in File Explorer"))
                    rows.append(f'<tr><td>{name} <span class="sub">{esc(f.kind)}</span>'
                                f'{self.from_chip(f.task, t.id)}{"<br><span class=sub>" + esc(d.description) + "</span>" if d and d.description else ""}</td></tr>')
            return f'<table cellspacing="0" cellpadding="4">{"".join(rows)}</table>' if rows else '<p class="note">No files yet.</p>'
        kids = self.m.children_of(t.id)
        if not kids:
            return '<p class="note">No subtasks.</p>'
        rows = [f"<tr><td>{state_chip(self.m.task(k).state)} {self.task_link(k)}{self.markers_html(self.m.task(k))}</td></tr>" for k in kids]
        return f'<table cellspacing="0" cellpadding="4">{"".join(rows)}</table>'

    def show_key(self, f) -> str:
        if f.kind in ("Saved copy", "Old version"):
            copy = next((c for c in self.m.copies if c.task == f.task and c.name == f.name), None)
            return f"show:copy:{copy.id}" if copy else f"doc:{f.document}"
        return f"show:doc:{f.document}"

    # ---- stories ----
    def story_tab(self, t: Task, state: PageState, ids: list[str]) -> str:
        kind = state.tab
        anc = [x for x in dict.fromkeys(y for chain in self.m.chains_of(t.id) for y in chain[:-1]) if x in ids]
        subs = [(x, d) for x, d in self.stories.subtask_tree(t.id) if x in ids]
        order = "Order: " + " · ".join(f"<b>{label}</b>" if state.order == key else link(f"order:{key}", label)
                                       for key, label in (("old", "Oldest first"), ("new", "Newest first")))
        if anc or subs:
            order += f' &nbsp; {link("chapall:open", "Open all chapters")} · {link("chapall:close", "Close all")}'
        out = [f'<p class="sub">{order}</p>']
        if anc:
            out.append('<p class="chs">PARENT TASKS</p>' + "".join(self.chapter(x, 0, kind, state) for x in anc))
        if anc or subs:
            out.append('<p class="chs">THIS TASK</p>')
        out.append(self.story_body(t.id, kind, state))
        if subs:
            out.append(f'<p class="chs">SUBTASKS ({len(subs)})</p>' + "".join(self.chapter(x, d, kind, state) for x, d in subs))
        return "".join(out)

    def story_body(self, task_id: str, kind: str, state: PageState) -> str:
        if kind == "log":
            return self.story_list(self.stories.story(task_id), lambda e: self.log_item(e), state)
        items = self.stories.raw_items(task_id)
        if not items:
            return '<p class="note">Nothing in the raw text log yet.</p>'
        return self.story_list(items, lambda r: self.raw_item(r, state), state)

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
                rows.append(f'<tr><td colspan="2" class="month">{MONTH_NAMES[int(d[5:7]) - 1].upper()} {d[:4]}</td></tr>')
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

    def raw_item(self, r: RawItem, state: PageState) -> str:
        key = r.capture or f"V{r.document}{r.at}"
        title = self.capture_link(r.capture, r.title) if r.capture else link(f"doc:{r.document}", r.title)
        out = f'<p><span class="lead">{esc(r.lead)}</span><br><b>{title}</b>'

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
        for a in self.m.agenda:
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
        rows = [("Aliases", esc(", ".join(p.aliases)) or none_text()), ("Hours a week", num(p.hours) if p.hours is not None else none_text("Not set")),
                ("Status", esc(p.status)), ("Scheduled", f"{this_week:.1f} h this week, {next_week:.1f} h next week"),
                ("Leads", ", ".join(self.task_link(x) for x in leads) or "None"), ("Assigned", ", ".join(self.task_link(x) for x in assigned) or "None")]
        added = f'<p class="note">{esc(p.added_note)}</p>' if p.added_note else ""
        return f'<p class="crumbs">Person {p.id}</p><h2>{esc(p.name)}{chips}</h2>{added}{fields_table(rows)}{self.agenda_block(person_id)}'

    def label_page(self, name: str) -> str:
        label = next(lb for lb in self.m.labels if lb.name == name)
        tasks = label_tasks(self.m, name)
        rows = [("Keywords", esc(", ".join(label.keywords)) or none_text()), ("Status", esc(label.status)),
                ("Tasks", "<br>".join(self.task_link(t) + (' <span class="sub">inherited</span>' if inh else "") for t, inh in tasks) or none_text())]
        return f'<p class="crumbs">Label</p><h2>{esc(label.name)}</h2>{fields_table(rows)}'

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
