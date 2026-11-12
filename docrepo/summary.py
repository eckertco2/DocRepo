"""The quick summary (release 5.131; the design workspace's ``docs/mods/quick-summary-plan.md``, decisions 517 to 539): one
person, agenda or label as a briefing, for a glance while someone's standing there.

Every subject has one shape (decision 521): a headline of counts, with only what's wrong in colour (decision 522), a line of
facts, then its sections in order, each left out when it has nothing:

- **a person:** Agenda; Waiting on <first name>; <first name>'s waiting on you; <first name>'s other work, folded (decision
  525); Email conversations; What's changed since you last talked;
- **an agenda** (a meeting, or any task with open items on its agenda): Agenda; Discussed lately, folded; Email
  conversations; What's changed since it was last discussed;
- **a label** (a parent label takes its sublabels in): Where they stand (decision 532); Needs attention; Other open tasks,
  folded; Email conversations; What's changed in the last 30 days;
- **a tagged label** (decision 561): a label's shape, over the tasks whose own fields, notes, captures or documents mention it;
- **several together** (decisions 555 to 560): each chosen person's and agenda's agenda; the tasks that match, with either
  of several of one kind and every kind chosen (Mike or Tom, with Vulnerabilities); then emails and what's changed.

Every list of tasks is in the **attention order** (decision 523): late first, then urgent or Critical, then by date, the
soonest first, with no date last; a list shows ``SHOWN`` rows, then "n more". A task is **quiet** (decision 524) when nothing
has touched it (a capture, a status change, an edit of its notes) for ``Settings.quiet_days`` days; quiet is grey, never red.
An agenda's items come with late or urgent tasks first, then the oldest first (decision 529), and each row leads with the
owner's note, the question to ask.

Nothing here touches Qt, so the summary is tested as words and HTML in the fast run; ``docrepo/ui/quick_summary.py`` shows
it. DocRepo runs no model: every line here is counted or quoted from docs.db.
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import quote, unquote

from docrepo import capacity, email_conversations, tagged
from docrepo.activity import Activity, Line
from docrepo.dates import long_date, monday_of, short, to_date
from docrepo.detail import chip, esc, initials, link
from docrepo.model import PRIORITY_NAMES, TODAY, AgendaItem, Model, Person, Task, is_person
from docrepo.schedule import DueDate, due_of, is_open
from docrepo.stories import clip
from docrepo.text import first_sentence
from docrepo.views import due_cell, last_updated, project_text

PERSON, AGENDA, LABEL, TAG, MANY = "person", "agenda", "label", "tag", "many"
KIND_WORDS = {PERSON: "Person", AGENDA: "Agenda", LABEL: "Label", TAG: "Tagged label", MANY: "Together"}
#: The plural each kind is counted in, on a combination's kind line (decision 562).
KIND_PLURALS = {PERSON: ("person", "people"), AGENDA: ("agenda", "agendas"), LABEL: ("label", "labels"), TAG: ("tag", "tags")}
#: How a combination's subjects are joined, in its name and its key (decision 562).
JOIN = " + "
#: The most tagged labels the box lists for what's typed.
TAGS_LISTED = 8
#: Rows a list shows before "n more" (decision 523).
SHOWN = 5
#: Email conversations shown, and with Show more (decision 530).
EMAILS_SHOWN, EMAILS_MORE = 5, 10
#: What's changed: at most this many tasks, each with its newest change (decision 531).
CHANGED_TASKS = 5
#: Due within this many days is amber (decision 522).
SOON_DAYS = 2
#: What's changed for a person or an agenda never discussed, and for a label (decision 531).
FIRST_WINDOW_DAYS, LABEL_WINDOW_DAYS = 14, 30
#: Discussed lately: an agenda's items discussed in the last week.
DISCUSSED_DAYS = 7
#: A label's trend: its open count at the end of each of the last eight weeks (decision 532).
TREND_WEEKS = 8
#: The box's list with nothing typed (decision 519): pinned, then recent, numbered 1 to 9.
START_MAX = 9
#: How many recent subjects Settings keeps.
RECENT_KEEP = 12
#: Who closes and adds agenda items from the window, in the status log and the agenda (decisions 526 and 527).
VIA = "Quick summary"
#: The priorities whose mark a row has at its left edge (release 5.81), drawn by the page view as ``edge:<priority>``.
EDGE = ("critical", "high", "medium", "parking")
BUCKETS = ("critical", "high", "medium", "parking", "none")
BUCKET_NAMES = {**PRIORITY_NAMES, "none": "No priority"}
#: The bars' width in pixels for the label's largest group (decision 532).
BAR_WIDTH = 300


# ---- subjects ----
@dataclass(frozen=True)
class Subject:
    """What a summary is of: a person (``ref`` their ID), an agenda (its task's ID) or a label (its name)."""

    kind: str
    ref: str
    name: str
    #: Several together (decision 555): the subjects, in the order they were picked; ``kind`` is MANY.
    parts: tuple[Subject, ...] = ()

    @property
    def key(self) -> str:
        """How Settings keeps it, in pins and recents: "person:P004", "agenda:T000010", "label:Safety", "tag:P204B", or a
        combination's keys joined: "person:P004 + label:Vulnerabilities" (decision 562)."""
        return JOIN.join(p.key for p in self.parts) if self.parts else f"{self.kind}:{self.ref}"

    def each(self) -> tuple[Subject, ...]:
        """The subjects it's made of: its parts, or itself."""
        return self.parts or (self,)


def combine(subjects: Iterable[Subject]) -> Subject | None:
    """Several subjects as one (decision 555), each once, in the order given: None for none, the one for one."""
    seen: dict[str, Subject] = {}
    for x in subjects:
        for p in x.each():
            seen.setdefault(p.key, p)
    parts = tuple(seen.values())
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return Subject(MANY, JOIN.join(p.key for p in parts), JOIN.join(p.name for p in parts), parts)


def subject_of(m: Model, key: str, me: str | None = None) -> Subject | None:
    """The subject a key names, or None when it's gone (a person retired, a label renamed, a task closed or discarded). A
    combination's key gives the parts still there, combined."""
    if JOIN in key:
        return combine(x for x in (subject_of(m, k, me) for k in key.split(JOIN)) if x)
    kind, _, ref = key.partition(":")
    if kind == PERSON and ref in m.people and m.people[ref].status == "active" and ref != me:
        return Subject(PERSON, ref, m.people[ref].name)
    if kind == AGENDA and ref in m.tasks and is_agenda(m, ref):
        return Subject(AGENDA, ref, m.task(ref).title)
    if kind == LABEL and m.label(ref) is not None and m.label(ref).status == "active":
        return Subject(LABEL, ref, ref)
    if kind == TAG and ref in m.tagged.by_key:
        return Subject(TAG, ref, m.tagged.by_key[ref].label)
    return None


def is_agenda(m: Model, task_id: str) -> bool:
    """A task that's an agenda: an open meeting, or any live task with open items on its agenda (decision 520)."""
    t = m.tasks.get(task_id)
    if t is None or t.discarded:
        return False
    return (t.meeting and is_open(t)) or bool(m.open_items_for(task_id))


def subjects(m: Model, me: str | None) -> list[Subject]:
    """Everything the box finds: the active people but the owner, the agendas (open meetings first, then any task with open
    items), and the active labels, each in its own order. Today has a view of its own (decision 520)."""
    people = [Subject(PERSON, p.id, p.name) for p in m.active_people() if p.id != me]
    agendas = [Subject(AGENDA, x, m.task(x).title) for x in m.agenda_targets() if not is_person(x) and x != TODAY and is_agenda(m, x)]
    labels = [Subject(LABEL, lb.name, lb.name) for lb in m.active_labels()]
    return people + agendas + labels


def matches(m: Model, subs: list[Subject], query: str) -> list[Subject]:
    """The subjects for what's typed (decision 519): each word starting a word of a name or a person's alias, in any
    order, the names that start with what's typed first. A leading @ keeps to people, as it does in the capture window.
    Tagged labels come last, found as Search everything finds them (``tagged.find_labels``: "p204" finds P-204B), at most
    ``TAGS_LISTED`` (decision 561)."""
    q = query.strip()
    people_only = q.startswith("@")
    words = q.lstrip("@").lower().split()
    tags = [] if people_only or not words else [Subject(TAG, lb.key, lb.label) for lb in tagged.find_labels(m.tagged, q)][:TAGS_LISTED]
    if not words:
        return [s for s in subs if s.kind == PERSON] if people_only else []

    def names(s: Subject) -> list[str]:
        return [s.name.lower(), *(a.lower() for a in (m.people[s.ref].aliases if s.kind == PERSON else ()))]

    def hit(s: Subject) -> bool:
        parts = [part for n in names(s) for part in n.split()]
        return all(any(part.startswith(w) for part in parts) for w in words)

    found = [s for s in subs if (not people_only or s.kind == PERSON) and hit(s)]
    return sorted(found, key=lambda s: (not any(n.startswith(words[0]) for n in names(s)),)) + tags


# ---- what's in a summary ----
@dataclass
class Chip:
    """One of the headline's counts. ``kind`` colours it: "raise" in the accent, "late" in red, "soon" in amber, "calm"
    for "nothing to raise", "" grey (decision 522)."""

    html: str
    kind: str = ""

    @property
    def text(self) -> str:
        return re.sub(r"<[^>]+>", "", self.html).replace("&amp;", "&")


@dataclass
class AgendaRow:
    """An agenda item as the window draws it (decision 529): the owner's note first (the question), then what it's about.
    ``when`` and ``when_class`` are its task's date, as a list row shows it."""

    item: int
    task: str | None
    question: str
    about: str
    when: str = ""
    when_class: str = ""
    urgent: bool = False
    tip: str = ""
    discussed: bool = False
    #: The agenda it's on: a person's ID or a task's (several agendas show together, decision 557).
    target: str = ""


@dataclass
class Section:
    """A section of the window, in the task page's shape (release 5.113): its title, a count, a few grey words, its one
    command at the right as (link, words), and its body as HTML. The agenda's rows are drawn by the window, so they come as
    ``agenda``, with ``add_to`` the target the add box adds to (decision 527)."""

    key: str
    title: str
    count: str = ""
    extra: str = ""
    action: tuple[str, str] | None = None
    body: str = ""
    folded: bool = False
    agenda: list[AgendaRow] | None = None
    add_to: str | None = None

    def text(self) -> str:
        """The section in words, as the tests read it."""
        rows = " ".join(f"{a.question} {a.about} {a.when}" for a in self.agenda or ())
        return " ".join(x for x in (self.title, self.count, self.extra, rows, words_of(self.body)) if x)


@dataclass
class Summary:
    """A subject's summary: its name and what it is, its facts as (name, value), the headline, the sections in order, and
    what Copy puts on the clipboard (decision 533)."""

    subject: Subject
    kind_line: str
    face: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    chips: list[Chip] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    markdown: str = ""
    html: str = ""

    def section(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    def text(self) -> str:
        """The whole summary in words: what the tests read."""
        facts = " ".join(f"{k} {v}" for k, v in self.facts)
        return " ".join([self.subject.name, self.kind_line, facts, " ".join(c.text for c in self.chips), *(s.text() for s in self.sections)])


def bar_width(counts: dict[str, int], biggest: int) -> int:
    """A Where they stand bar's width: ``BAR_WIDTH`` for the largest group, the rest in proportion, 12 at least."""
    return max(12, round(BAR_WIDTH * sum(counts.values()) / max(1, biggest)))


def words_of(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#x27;", "'"), ("&#39;", "'")):
        text = text.replace(a, b)
    return " ".join(text.split())


# ---- dates and the attention order ----
def task_date(m: Model, t: Task, today: date) -> DueDate | None:
    """A task's date for the lists (decision 523): Due, else Deadline (a routine task's next occurrence), else its next key
    date not done."""
    d = due_of(t, today)
    if d is not None:
        return d
    days = [to_date(k.end or k.start) for k in m.key_dates_of(t.id) if not k.done and (k.end or k.start)]
    return DueDate(min(days), "Key date") if days else None


def is_late(m: Model, t: Task, today: date) -> bool:
    d = task_date(m, t, today)
    return d is not None and d.date < today


def is_soon(m: Model, t: Task, today: date) -> bool:
    d = task_date(m, t, today)
    return d is not None and 0 <= (d.date - today).days <= SOON_DAYS


def attention(m: Model, ids: Iterable[str], today: date) -> list[Task]:
    """The attention order (decision 523): late first, then urgent or Critical, then by date, the soonest first, no date last."""
    def key(t: Task) -> tuple:
        d = task_date(m, t, today)
        late = d is not None and d.date < today
        lifted = t.urgent or t.priority == "critical"
        return (0 if late else 1 if lifted else 2, d.date if d else date.max, t.title.lower())

    return sorted((m.task(i) for i in dict.fromkeys(ids)), key=key)


def touched(m: Model) -> dict[str, date]:
    """When each task was last touched: its newest capture or status log entry (``views.last_updated``), or edit of its
    notes page by the owner, else when it was made."""
    out = {k: to_date(v[:10]) for k, v in last_updated(m).items() if v}
    for task_id, day, _at in m.page_edits:
        d = to_date(day[:10])
        if task_id in out and d > out[task_id]:
            out[task_id] = d
    return out


def worklike(t: Task) -> bool:
    """A task the lists show: live, open (Not started or In progress), and not a meeting, which is an agenda, not work."""
    return is_open(t) and not t.meeting


def status_of(m: Model, t: Task) -> tuple[str, date | None]:
    """The first sentence of a task's current status, and when it was set (decision 532)."""
    words = first_sentence(t.current_status or "", 110)
    if not words:
        return "", None
    at = [e.at for e in m.status_log_of(t.id) if e.field == "Current status"]
    return words, (to_date(max(at)[:10]) if at else None)


def ago_short(day: date, today: date) -> str:
    n = (today - day).days
    return "today" if n <= 0 else f"{n} d"


# ---- the summary ----
class Builder:
    """Makes the summaries for one Model, as of ``today``. ``conn`` reads the search index for an email's To line and the
    capacity calendar for a person's week; ``me`` is the owner's person ID."""

    def __init__(self, m: Model, today: date, me: str | None, conn: sqlite3.Connection | None = None, quiet_days: int = 21) -> None:
        self.m, self.today, self.me, self.conn = m, today, me, conn
        self.quiet_days = quiet_days
        self._touched: dict[str, date] | None = None
        self._activity: Activity | None = None
        self._labels: dict[str, set[str]] | None = None
        self._tags: dict[str, list[str]] = {}

    # ---- shared pieces ----
    def first(self, person_id: str) -> str:
        name = self.m.person_name(person_id)
        return name.split()[0] if name.split() else name

    def quiet(self, t: Task) -> int:
        """Days since the task was last touched, when that's ``quiet_days`` or more; else 0 (decision 524)."""
        if self._touched is None:
            self._touched = touched(self.m)
        day = self._touched.get(t.id)
        n = (self.today - day).days if day else 0
        return n if n >= self.quiet_days else 0

    def mark(self, t: Task) -> str:
        key = {"Not started": "ns", "In progress": "ip", "Parked": "pk", "Closed": "cl"}.get(t.state, "ns")
        return f'<img src="mark:{key}" width="14" height="14" title="{esc(t.state)}">'

    def when(self, t: Task) -> tuple[str, str, str]:
        """A task's date as a row shows it, its colour's class (decision 522) and its tooltip."""
        cell = due_cell(t, self.today, task_date(self.m, t, self.today))
        if cell is None:
            return "No date", "faint", "No date"
        return cell.text, {"over": "over", "soon": "caution"}.get(cell.cls, "rel"), cell.tip

    def task_row(self, t: Task, with_status: bool = True, people: Iterable[str] = ()) -> str:
        """A task's row (decision 523): its priority as the left edge, its state's mark, its title (a link to its page) with its
        project in grey, Urgent and quiet, the first sentence of its status and how old that is, and its date at the right."""
        edge_cell = (f'<td width="3" valign="top"><img src="edge:{t.priority}" width="3" height="18"></td>' if t.priority in EDGE
                     else '<td width="3"></td>')
        project = project_text(self.m, t.id)
        quiet = self.quiet(t)
        chips = (f" {chip('Urgent', 'urgent')}" if t.urgent else "") + \
            (f' <span title="Nothing has touched it for {quiet} days">{chip(f"quiet {quiet} d", "routine")}</span>' if quiet else "")
        status = ""
        if with_status:
            words, at = status_of(self.m, t)
            if words:
                status = f'<br><span class="sub">“{esc(words)}”{f" · {ago_short(at, self.today)}" if at else ""}</span>'
        when, cls, tip = self.when(t)
        title = f'{PRIORITY_NAMES.get(t.priority or "", "No")} priority'
        on = [self.first(p) for p in people if p in (*t.leads, *t.assignees)]
        if on:  # several people chosen (decision 558): which of them it's with
            project = " · ".join(x for x in (project, ", ".join(on)) if x)
        return (f'<tr>{edge_cell}<td width="6"></td><td width="20" valign="top">{self.mark(t)}</td>'
                f'<td valign="top" title="{esc(title)}">{link(f"task:{t.id}", t.title, quiet="tl")}'
                f'{f" &nbsp;<span class=sub>{esc(project)}</span>" if project else ""}{chips}{status}</td>'
                f'<td align="right" valign="top" class="{cls}" title="{esc(tip)}" style="white-space: nowrap">{esc(when)}</td></tr>')

    def task_list(self, key: str, ids: Iterable[str], more: set[str], with_status: bool = True, people: Iterable[str] = ()) -> str:
        """Rows in the attention order: ``SHOWN``, then "n more", which shows the rest in place."""
        ts = attention(self.m, ids, self.today)
        shown = ts if key in more or len(ts) <= SHOWN else ts[:SHOWN]
        people = list(people)
        rows = "".join(self.task_row(t, with_status, people) for t in shown)
        table = f'<table width="100%" cellspacing="0" cellpadding="3">{rows}</table>'
        if len(shown) < len(ts):
            table += f'<p style="margin-top: 2px; margin-left: 30px">{link(f"more:{key}", f"{len(ts) - len(shown)} more")}</p>'
        return table

    def counts_words(self, ids: list[str]) -> str:
        """A folded list's few words: "1 late · 3 due this week" (decision 525)."""
        ts = [self.m.task(i) for i in ids]
        late = sum(is_late(self.m, t, self.today) for t in ts)
        week_end = monday_of(self.today) + timedelta(days=6)
        week = sum(1 for t in ts if (d := task_date(self.m, t, self.today)) and self.today <= d.date <= week_end)
        parts = [f"{late} late"] * bool(late) + [f"{week} due this week"] * bool(week)
        return " · ".join(parts) or "none due this week"

    # ---- an agenda's items ----
    def agenda_rows(self, target: str) -> list[AgendaRow]:
        """The open items, late or urgent tasks first, then the oldest first (decision 529)."""
        m = self.m

        def hot(a: AgendaItem) -> bool:
            t = m.tasks.get(a.subject) if a.subject else None
            return bool(t) and (t.urgent or is_late(m, t, self.today))

        items = sorted(m.open_items_for(target), key=lambda a: (not hot(a), a.added, a.id))
        out = []
        for a in items:
            t = m.tasks.get(a.subject) if a.subject else None
            if t is None:
                out.append(AgendaRow(a.id, None, a.note, f"A note · waiting {ago_short(to_date(a.added[:10]), self.today)}",
                                     tip=f"Added {long_date(to_date(a.added[:10]), self.today)}", target=target))
                continue
            words, _at = status_of(m, t)
            about = t.title + (f" · “{words}”" if words else "")
            when, cls, tip = self.when(t)
            path = project_text(m, t.id)
            out.append(AgendaRow(a.id, t.id, a.note or t.title, about if a.note else (f"“{words}”" if words else path or ""),
                                 "" if when == "No date" else when, cls, t.urgent,
                                 "\n".join(x for x in (path, tip, f"Added {long_date(to_date(a.added[:10]), self.today)}") if x), target=target))
        return out

    def last_discussed(self, target: str) -> AgendaItem | None:
        """The item on this agenda discussed last: when you last talked, or last visited (decision 531)."""
        done = [a for a in self.m.agenda if a.target == target and a.how == "Discussed" and a.closed]
        return max(done, key=lambda a: a.closed or "") if done else None

    def agenda_section(self, target: str, owner_words: str) -> Section:
        rows = self.agenda_rows(target)
        return Section("agenda", "Agenda", str(len(rows)), "" if rows else f"Nothing on {owner_words} yet", agenda=rows, add_to=target)

    # ---- email conversations (decision 530) ----
    def _me_names(self) -> set[str]:
        p = self.m.people.get(self.me or "")
        return {x.lower() for x in ((p.name, *(p.aliases or ()), p.email or "") if p else ()) if x}

    def is_mine(self, sender: str) -> bool:
        s = (sender or "").strip().lower()
        return bool(s) and any(s == n or (("@" in n) and n in s) for n in self._me_names())

    def _to_lines(self, p: Person) -> set[str]:
        """The captures whose emails' To or Cc lines name this person, from the search index's text."""
        if self.conn is None:
            return set()
        words = [w for w in dict.fromkeys([p.name, *(a for a in p.aliases if len(a) >= 3), p.email or ""]) if w.strip()]
        if not words:
            return set()
        with_emails = {c.id for c in self.m.live_captures() if c.emails}
        like = " OR ".join("body LIKE ? ESCAPE '\\'" for _ in words)
        params = [f"%{w.replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%" for w in words]
        found: set[str] = set()
        pattern = re.compile("|".join(rf"(?<!\w){re.escape(w)}(?!\w)" for w in words), re.IGNORECASE)
        for row in self.conn.execute(f"SELECT id, body FROM search_text WHERE kind = 'capture' AND ({like})", params):  # noqa: S608 - only placeholders are added
            if row[0] not in with_emails:
                continue
            for line in row[1].splitlines():
                if re.match(r"\s*(To|Cc):", line, re.IGNORECASE) and pattern.search(line):
                    found.add(row[0])
                    break
        return found

    def person_conversations(self, p: Person) -> list[email_conversations.Conversation]:
        """Conversations with an email from or to the person: their name, an alias or their address as the sender, or their
        name in an email's To or Cc line."""
        names = {x.lower() for x in (p.name, *(a for a in p.aliases if len(a) >= 3)) if x}
        address = (p.email or "").lower()

        def from_them(sender: str) -> bool:
            s = (sender or "").strip().lower()
            return bool(s) and (s in names or bool(address and address in s))

        to_them = self._to_lines(p)
        return [cv for cv in email_conversations.all_of(self.m) if any(from_them(e.sender) or e.capture in to_them for e in cv.emails)]

    def emails_section(self, convs: list, more: set[str]) -> Section | None:
        if not convs:
            return None
        shown = convs[:EMAILS_MORE if "emails" in more else EMAILS_SHOWN]
        rows = []
        for cv in shown:
            newest = cv.newest
            task = next((t for t in reversed(cv.tasks()) if t in self.m.tasks), None)
            href = f"conv:{task}/{cv.id}" if task else f"capture:{newest.capture}"
            subject = link(href, cv.subject, email_conversations_tip(), "tl")
            sender = newest.sender or ""
            mine = self.is_mine(sender)
            turn = f" {chip('your turn', 'multi')}" if sender and not mine else ""
            who = "You" if mine else sender or "Someone"
            where = f"↗ {esc(self.m.task(task).title)}" if task else "Unfiled"
            n = len(cv.emails)
            rows.append(f'<tr><td valign="top" width="22"><img src="ft:mail" width="16" height="16"></td>'
                        f'<td valign="top">{subject}{turn}<br><span class="sub">{where} · {esc(who)} wrote last · {n} email{"s" * (n != 1)}</span></td>'
                        f'<td valign="top" align="right" class="rel" width="70">{esc(self.day_words(to_date(newest.at[:10])))}</td></tr>')
        body = f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
        if len(convs) > EMAILS_SHOWN and "emails" not in more:
            body += f'<p style="margin-top: 2px; margin-left: 30px">{link("more:emails", f"Show {min(EMAILS_MORE, len(convs))}")}</p>'
        return Section("emails", "Email conversations", str(len(convs)), body=body)

    def day_words(self, day: date) -> str:
        """A past day as the rows say it: Today, Yesterday, the weekday within the week, else "9 Nov"."""
        n = (self.today - day).days
        if n <= 0:
            return "Today"
        if n == 1:
            return "Yesterday"
        if n < 7:
            return long_date(day, self.today).split()[0]
        return short(day, self.today)

    # ---- what's changed (decision 531) ----
    def activity(self) -> Activity:
        if self._activity is None:
            self._activity = Activity(self.m, self.today)
        return self._activity

    def changed_section(self, task_ids: set[str], since: date, why: str, activity_href: str, targets: set[str] = frozenset()) -> Section | None:
        """Counts of what happened since ``since`` on these tasks (and on these agendas), then up to ``CHANGED_TASKS`` tasks,
        each with its newest change, the newest first. None when nothing changed."""
        lines = [x for x in self.activity().lines(since, self.today) if (x.about in task_ids) or (x.key.startswith("a:") and self._on_target(x, targets))]
        if not lines:
            return None
        counts: dict[str, int] = {}
        for x in lines:
            word = self.kind_word(x)
            counts[word] = counts.get(word, 0) + 1
        order = ("closed", "new", "updates", "notes", "emails", "changes", "documents", "agenda items")
        digest = " ".join(f'<span class="stat">&nbsp;<b>{n}</b> {esc(w if n != 1 else SINGULAR.get(w, w))}&nbsp;</span>&nbsp;'
                          for w, n in sorted(counts.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99))
        newest: dict[str, Line] = {}
        for x in sorted(lines, key=lambda x: x.at):
            if x.about:
                newest[x.about] = x
        rows = []
        for x in sorted(newest.values(), key=lambda x: x.at, reverse=True)[:CHANGED_TASKS]:
            title = self.m.task(x.about).title if x.about in self.m.tasks else ""
            rows.append(f'<tr><td>{link(f"task:{x.about}", title, quiet="tl")} <span class="sub">· {esc(clip(self.change_words(x), max(24, 96 - len(title))))}</span></td>'
                        f'<td align="right" class="rel" width="70">{esc(self.day_words(x.day))}</td></tr>')
        body = f'<p style="margin: 0 0 4px 0">{digest}</p><table width="100%" cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
        return Section("changed", "What's changed", "", why, (activity_href, "Show in Activity"), body)

    def _on_target(self, x: Line, targets: set[str]) -> bool:
        try:
            item = int(x.key.split(":")[1])
        except (IndexError, ValueError):
            return False
        return any(a.id == item and a.target in targets for a in self.m.agenda)

    def kind_word(self, x: Line) -> str:
        kind = x.kinds[0] if x.kinds else "change"
        if kind == "change" and x.chip == "State" and x.key.startswith("e:"):
            e = self.m.status[int(x.key[2:])]
            return "closed" if e.to_value == "Closed" else "changes"
        return {"task": "new", "update": "updates", "note": "notes", "email": "emails", "change": "changes", "doc": "documents",
                "agenda": "agenda items"}.get(kind, "changes")

    def change_words(self, x: Line) -> str:
        """A line in a few words: "status: Waiting for the quote", "closed", "new", "email: Crane booking"."""
        if self.kind_word(x) == "closed":
            return "closed"
        if x.chip in ("New task", "New task under this one"):
            return "new"
        if x.chip == "State":
            return x.text.rstrip(".").lower()
        return f"{x.chip.lower()}: {x.text.rstrip('.')}"

    # ---- the three kinds ----
    def build(self, s: Subject, more: Iterable[str] = ()) -> Summary:
        more = set(more)
        if s.kind == PERSON:
            out = self.person(s, more)
        elif s.kind == AGENDA:
            out = self.agenda(s, more)
        elif s.kind == MANY:
            out = self.many(s, more)
        elif s.kind == TAG:
            out = self.tag(s, more)
        else:
            out = self.label(s, more)
        out.markdown, out.html = copy_text(self, out)
        return out

    def person_lists(self, pid: str) -> tuple[list[str], list[str], list[str]]:
        """A person's open tasks by who acts (decision 525): waiting on them (you lead and they're assigned, or you share a
        role), waiting on you (they lead and you're assigned), and their other work (without you). With no owner set, all
        of it is their other work."""
        waiting_on, waiting_you, other = [], [], []
        me = self.me
        for t in self.m.tasks.values():
            if not worklike(t) or pid not in (*t.leads, *t.assignees):
                continue
            if not me or me not in (*t.leads, *t.assignees):
                other.append(t.id)
            elif pid in t.leads and me in t.assignees and me not in t.leads:
                waiting_you.append(t.id)
            else:
                waiting_on.append(t.id)
        return waiting_on, waiting_you, other

    def person(self, s: Subject, more: set[str]) -> Summary:
        m, today, p = self.m, self.today, self.m.people[s.ref]
        first = self.first(p.id)
        agenda = self.agenda_section(p.id, f"{first}'s agenda")
        on_agenda = {a.task for a in agenda.agenda or () if a.task}
        waiting_on, waiting_you, other = self.person_lists(p.id)
        waiting_on = [x for x in waiting_on if x not in on_agenda]
        waiting_you = [x for x in waiting_you if x not in on_agenda]
        other = [x for x in other if x not in on_agenda]
        shared = [m.task(x) for x in (*on_agenda, *waiting_on, *waiting_you) if worklike(m.task(x))]
        last = self.last_discussed(p.id)
        last_day = to_date(last.closed[:10]) if last and last.closed else None
        upcoming = sorted(d.date for t in shared if (d := task_date(m, t, today)) and d.date >= today)
        facts = [("Last talked", f"{long_date(last_day, today)} · {ago_short(last_day, today)}" if last_day else "Not on record"),
                 ("Next", long_date(upcoming[0], today) if upcoming else "Nothing dated")]
        week = self.week_hours(p)
        if week:
            facts.append(("This week", week))
        late = sum(is_late(m, t, today) for t in shared)
        soon = sum(is_soon(m, t, today) for t in shared)
        n = len(agenda.agenda or ())
        chips = [Chip(f"<b>{n}</b> to raise", "raise") if n else Chip(f"Nothing to raise with {esc(first)}", "calm")]
        chips += [Chip(f"<b>{late}</b> late", "late")] * bool(late) + [Chip(f"<b>{soon}</b> due in {SOON_DAYS} days", "soon")] * bool(soon)
        if self.me:  # counts, grey; a list with nothing in it says nothing (decision 522)
            chips += [Chip(f"<b>{len(waiting_on)}</b> waiting on {esc(first)}")] * bool(waiting_on) + [Chip(f"<b>{len(waiting_you)}</b> waiting on you")] * bool(waiting_you)
        sections = [agenda]
        if waiting_on:
            sections.append(Section("waiting_on", f"Waiting on {first}", str(len(waiting_on)), "you lead, they're on it",
                                    body=self.task_list("waiting_on", waiting_on, more)))
        if waiting_you:
            sections.append(Section("waiting_you", f"{first}'s waiting on you", str(len(waiting_you)), "they lead, you're on it",
                                    body=self.task_list("waiting_you", waiting_you, more)))
        if other:
            sections.append(Section("other", f"{first}'s other work" if self.me else f"{first}'s tasks", str(len(other)), self.counts_words(other),
                                    body=self.task_list("other", other, more, with_status=False), folded=bool(self.me)))
        emails = self.emails_section(self.person_conversations(p), more)
        if emails:
            sections.append(emails)
        since = last_day if last_day and (today - last_day).days <= 60 else today - timedelta(days=FIRST_WINDOW_DAYS)
        why = f"since {long_date(since, today)}, when you last talked" if since == last_day else f"in the last {FIRST_WINDOW_DAYS} days"
        involved = {t.id for t in m.tasks.values() if p.id in (*t.leads, *t.assignees) and not t.discarded and not t.meeting}
        changed = self.changed_section(involved, since, why, activity_href(s, since), {p.id})
        if changed:
            sections.append(changed)
        kind = " · ".join(x for x in (KIND_WORDS[PERSON], p.role or "", p.group or "") if x)
        return Summary(s, kind, initials(p.name), facts, chips, sections)

    def week_hours(self, p: Person) -> str:
        """Their scheduled hours this week against their hours a week, from the capacity calendar: "38 of 40 h"."""
        if self.conn is None or not p.hours:
            return ""
        week = monday_of(self.today)
        try:
            hours = capacity.week_total(capacity.week_cells(self.conn, [week]), p.id, week)
        except sqlite3.Error:
            return ""
        return f"{hours:.0f} of {p.hours:g} h"

    def agenda(self, s: Subject, more: set[str]) -> Summary:
        m, today, t = self.m, self.today, self.m.task(s.ref)
        agenda = self.agenda_section(t.id, "this agenda")
        rows = agenda.agenda or []
        last = self.last_discussed(t.id)
        last_day = to_date(last.closed[:10]) if last and last.closed else None
        facts = [("Last discussed", f"{long_date(last_day, today)} · {last.closed[11:16]}" if last_day and last.closed and last_day == today
                  else long_date(last_day, today) if last_day else "Not on record")]
        when = m.meeting_when(t.id, today)
        if when and when != "no date set":
            facts.append(("Next", when))
        tasks = [m.task(a.task) for a in rows if a.task]
        late = sum(is_late(m, x, today) for x in tasks)
        urgent = sum(x.urgent for x in tasks)
        oldest = max(((today - to_date(a.added[:10])).days for a in m.open_items_for(t.id)), default=0)
        chips = [Chip(f"<b>{len(rows)}</b> to raise", "raise") if rows else Chip("Nothing to raise", "calm")]
        chips += [Chip(f"<b>{late}</b> late", "late")] * bool(late) + [Chip(f"<b>{urgent}</b> urgent", "late")] * bool(urgent)
        if rows:
            chips.append(Chip(f"oldest <b>{oldest} d</b>"))
        sections = [agenda]
        week_ago = (today - timedelta(days=DISCUSSED_DAYS)).isoformat()
        done = sorted((a for a in m.agenda if a.target == t.id and a.how == "Discussed" and (a.closed or "")[:10] >= week_ago),
                      key=lambda a: a.closed or "", reverse=True)
        if done:
            body = "".join(
                f'<tr><td width="20" valign="top"><img src="mark:cl" width="14" height="14"></td><td valign="top">'
                f'{esc(a.note) if a.note else link(f"task:{a.subject}", m.task(a.subject).title, quiet="tl")}'
                f'{f" &nbsp;<span class=sub>{esc(m.task(a.subject).title)}</span>" if a.note and a.subject else ""}</td>'
                f'<td align="right" class="rel" width="90">{esc(self.day_words(to_date(a.closed[:10])))}{(" " + a.closed[11:16]) if a.closed and to_date(a.closed[:10]) == today else ""}</td></tr>'
                for a in done)
            sections.append(Section("discussed", "Discussed lately", str(len(done)), f"the last {DISCUSSED_DAYS} days",
                                    body=f'<table width="100%" cellspacing="0" cellpadding="3">{body}</table>', folded=True))
        on = {a.subject for a in m.agenda if a.target == t.id and a.subject} | {t.id}
        emails = self.emails_section(email_conversations.for_tasks(m, sorted(on)), more)
        if emails:
            sections.append(emails)
        since = last_day or today - timedelta(days=FIRST_WINDOW_DAYS)
        why = f"since {long_date(since, today)}, when it was last discussed" if last_day else f"in the last {FIRST_WINDOW_DAYS} days"
        open_on = {a.subject for a in m.open_items_for(t.id) if a.subject} | {t.id}
        changed = self.changed_section(open_on, since, why, activity_href(s, since), {t.id})
        if changed:
            sections.append(changed)
        kind = " · ".join(x for x in (KIND_WORDS[AGENDA], "Meeting" if t.meeting else "on a task", f"↻ {t.recurrence}" if t.recurrence else "") if x)
        return Summary(s, kind, "agenda", facts, chips, sections)

    def label_names(self, name: str) -> list[str]:
        """A label and, for a parent label, its sublabels (decision 520)."""
        return [name, *self.m.sublabels(name, active=False)]

    def label_task_ids(self, name: str) -> list[str]:
        """Every live task with the label or one of its sublabels, open or not, own or inherited (``views.label_tasks``'s
        answer, from each task's labels worked out once per builder, as the box asks for every label)."""
        if self._labels is None:
            self._labels = {t.id: {n for n, _inh in self.m.labels_of(t.id)} for t in self.m.tasks.values() if not t.discarded}
        names = set(self.label_names(name))
        return [x for x, have in self._labels.items() if have & names and not self.m.task(x).meeting]

    def tag_task_ids(self, key: str) -> list[str]:
        """Every live task a tagged label is on (decision 561): its own fields or notes page mention it, or a capture or a
        document of it does (``tagged.uses_of``, the label's page's list), worked out once per tag."""
        if key in self._tags:
            return self._tags[key]
        m, found = self.m, {}
        lb = m.tagged.by_key.get(key)
        for u in tagged.uses_of(m, lb) if lb is not None else ():
            if u.kind in ("task", "page"):
                ids = [u.id]
            elif u.kind == "capture":
                c = m.captures.get(u.id)
                ids = m.capture_tasks(c) if c is not None else []
            elif u.kind == "document":
                ids = m.document_holders(u.id)
            else:
                ids = []
            for x in ids:
                if x in m.tasks and not m.task(x).discarded and not m.task(x).meeting:
                    found[x] = None
        self._tags[key] = list(found)
        return self._tags[key]

    def tag(self, s: Subject, more: set[str]) -> Summary:
        lb = self.m.tagged.by_key[s.ref]
        kind = " · ".join(x for x in (KIND_WORDS[TAG], lb.description) if x)
        return self.label(s, more, self.tag_task_ids(s.ref), kind, "tag")

    def label(self, s: Subject, more: set[str], every: list[str] | None = None, kind: str = "", face: str = "label") -> Summary:
        m, today = self.m, self.today
        every = self.label_task_ids(s.ref) if every is None else every
        open_ids = [x for x in every if worklike(m.task(x))]
        ts = [m.task(x) for x in open_ids]
        subs = m.sublabels(s.ref, active=False) if s.kind == LABEL else []
        month = today - timedelta(days=LABEL_WINDOW_DAYS)
        opened = sum(1 for x in every if (m.task(x).created or "")[:10] >= month.isoformat())
        closed = sum(1 for x in every if m.task(x).state == "Closed" and (m.task(x).closed or "")[:10] >= month.isoformat())
        oldest = min(ts, key=lambda t: t.created or "9999", default=None)
        oldest_days = (today - to_date(oldest.created[:10])).days if oldest and oldest.created else 0
        groups = {self.group_of(t, subs) for t in ts}
        crit = sum(t.priority == "critical" for t in ts)
        late = sum(is_late(m, t, today) for t in ts)
        quiet = sum(bool(self.quiet(t)) for t in ts)
        where = "projects" if not subs else "labels"
        chips = [Chip(f"<b>{len(ts)}</b> open in <b>{len(groups)}</b> {where if len(groups) != 1 else where[:-1]}")] if ts else [Chip("Nothing open", "calm")]
        chips += [Chip(f"<b>{crit}</b> Critical")] * bool(crit) + [Chip(f"<b>{late}</b> late", "late")] * bool(late) + [Chip(f"<b>{quiet}</b> quiet")] * bool(quiet)
        facts = [(f"Last {LABEL_WINDOW_DAYS} days", f"opened {opened} · closed {closed}")]
        if oldest:
            facts.append(("Oldest open", f"{oldest_days} d"))
        sections: list[Section] = []
        if ts:
            sections.append(self.where_section(ts, subs, oldest, oldest_days, every))
            need = [t.id for t in ts if t.priority in ("critical", "high") or t.urgent or is_late(m, t, today)]
            rest = [x for x in open_ids if x not in need]
            if need:
                sections.append(Section("need", "Needs attention", str(len(need)), "Critical, High, urgent or late", body=self.task_list("need", need, more)))
            if rest:
                sections.append(Section("rest", "Other open tasks", str(len(rest)), self.counts_words(rest),
                                        body=self.task_list("rest", rest, more, with_status=False), folded=bool(need)))
        emails = self.emails_section(email_conversations.for_tasks(m, every), more)
        if emails:
            sections.append(emails)
        changed = self.changed_section(set(every), month, f"since {long_date(month, today)}", activity_href(s, month))
        if changed:
            sections.append(changed)
        if not kind:
            parent = m.parent_label(s.ref)
            kind = " · ".join(x for x in (KIND_WORDS[LABEL], f"under {parent}" if parent else "", f"{len(subs)} labels under it" if subs else "") if x)
        return Summary(s, kind, face, facts, chips, sections)

    def chosen_tasks(self, s: Subject) -> list[str] | None:
        """The live tasks (not meetings) a combination's people, labels and tags choose, open or not (decision 556): with
        either of several of one kind, and every kind chosen. None when it has none of them, only agendas."""
        people = {p.ref for p in s.each() if p.kind == PERSON}
        labels = [p.ref for p in s.each() if p.kind == LABEL]
        tags = [p.ref for p in s.each() if p.kind == TAG]
        if not (people or labels or tags):
            return None
        with_label = set().union(*(self.label_task_ids(x) for x in labels)) if labels else None
        with_tag = set().union(*(self.tag_task_ids(x) for x in tags)) if tags else None
        out = []
        for t in self.m.tasks.values():
            if t.discarded or t.meeting:
                continue
            if people and not people & {*t.leads, *t.assignees}:
                continue
            if (with_label is not None and t.id not in with_label) or (with_tag is not None and t.id not in with_tag):
                continue
            out.append(t.id)
        return out

    def many(self, s: Subject, more: set[str]) -> Summary:
        """Several together (decisions 555 to 560): each chosen person's and agenda's agenda; the chosen tasks, by who acts
        for one person, else as a label's; emails and what's changed over them."""
        m, today = self.m, self.today
        parts = s.each()
        people = [p for p in parts if p.kind == PERSON]
        agendas = [p for p in parts if p.kind == AGENDA]
        filters = [p for p in parts if p.kind in (LABEL, TAG)]
        sections: list[Section] = []
        for p in (*people, *agendas):  # decision 557: every agenda, as it is
            words = f"{self.first(p.ref)}'s agenda" if p.kind == PERSON else f"{p.name}'s agenda"
            sec = self.agenda_section(p.ref, words)
            sec.key, sec.title = f"agenda:{p.ref}", words[0].upper() + words[1:] if p.kind == PERSON else p.name
            sections.append(sec)
        rows = [a for sec in sections for a in sec.agenda or ()]
        on_agendas = {a.task for a in rows if a.task}
        every = self.chosen_tasks(s)
        open_ids = [x for x in every or () if worklike(m.task(x))]
        listed = [x for x in open_ids if x not in on_agendas]
        names = [p.ref for p in people]
        facts: list[tuple[str, str]] = []
        lists: list[Section] = []
        if len(people) == 1 and self.me:  # decision 558: one person's lists, by who acts, narrowed
            first = self.first(people[0].ref)
            on, you, other = self.person_lists(people[0].ref)
            keep = set(listed)
            on, you, other = [x for x in on if x in keep], [x for x in you if x in keep], [x for x in other if x in keep]
            if on:
                lists.append(Section("waiting_on", f"Waiting on {first}", str(len(on)), "you lead, they're on it", body=self.task_list("waiting_on", on, more)))
            if you:
                lists.append(Section("waiting_you", f"{first}'s waiting on you", str(len(you)), "they lead, you're on it",
                                     body=self.task_list("waiting_you", you, more)))
            if other:
                lists.append(Section("other", f"{first}'s other work", str(len(other)), self.counts_words(other),
                                     body=self.task_list("other", other, more, with_status=False), folded=True))
        elif listed:
            ts = [m.task(x) for x in open_ids]
            if filters:
                oldest = min(ts, key=lambda t: t.created or "9999", default=None)
                days = (today - to_date(oldest.created[:10])).days if oldest and oldest.created else 0
                lists.append(self.where_section(ts, [], oldest, days, every or []))
            need = [x for x in listed if (t := m.task(x)).priority in ("critical", "high") or t.urgent or is_late(m, t, today)]
            rest = [x for x in listed if x not in need]
            if need:
                lists.append(Section("need", "Needs attention", str(len(need)), "Critical, High, urgent or late", body=self.task_list("need", need, more, people=names)))
            if rest:
                lists.append(Section("rest", "Other open tasks", str(len(rest)), self.counts_words(rest),
                                     body=self.task_list("rest", rest, more, with_status=False, people=names), folded=bool(need)))
        sections += lists
        # Emails (decision 559): on the chosen tasks with a label or tag; else from or to the chosen people; else on the agendas.
        if filters:
            convs = email_conversations.for_tasks(m, every or [])
        elif people:
            seen: dict[str, None] = {}
            for p in people:
                for cv in self.person_conversations(m.people[p.ref]):
                    seen.setdefault(cv.id, None)
            convs = [cv for cv in email_conversations.all_of(m) if cv.id in seen]
        else:
            on = sorted({a.subject for p in agendas for a in m.agenda if a.target == p.ref and a.subject} | {p.ref for p in agendas})
            convs = email_conversations.for_tasks(m, on)
        emails = self.emails_section(convs, more)
        if emails:
            sections.append(emails)
        # What's changed (decision 560): since the earliest last talk among them, else 30 days with a label or tag, else 14.
        talks = [to_date(a.closed[:10]) for p in (*people, *agendas) if (a := self.last_discussed(p.ref)) and a.closed]
        talks = [d for d in talks if (today - d).days <= 60]
        since = min(talks) if talks else today - timedelta(days=LABEL_WINDOW_DAYS if filters else FIRST_WINDOW_DAYS)
        why = (f"since {long_date(since, today)}, when you last talked" if len(talks) == 1 else
               f"since {long_date(since, today)}, the earliest of your last talks" if talks else f"since {long_date(since, today)}")
        involved = set(every or []) | on_agendas | {p.ref for p in agendas}
        changed = self.changed_section(involved, since, why, activity_href(s.each()[0], since), {p.ref for p in (*people, *agendas)})
        if changed:
            sections.append(changed)
        # The header (decision 562).
        if len(people) == 1:
            last = self.last_discussed(people[0].ref)
            day = to_date(last.closed[:10]) if last and last.closed else None
            facts.append(("Last talked", f"{long_date(day, today)} · {ago_short(day, today)}" if day else "Not on record"))
        if filters and every is not None:
            month = (today - timedelta(days=LABEL_WINDOW_DAYS)).isoformat()
            opened = sum(1 for x in every if (m.task(x).created or "")[:10] >= month)
            shut = sum(1 for x in every if m.task(x).state == "Closed" and (m.task(x).closed or "")[:10] >= month)
            facts.append((f"Last {LABEL_WINDOW_DAYS} days", f"opened {opened} · closed {shut}"))
        hot = [m.task(x) for x in {*open_ids, *on_agendas} if x in m.tasks and worklike(m.task(x))]
        late = sum(is_late(m, t, today) for t in hot)
        soon = sum(is_soon(m, t, today) for t in hot)
        crit = sum(m.task(x).priority == "critical" for x in open_ids)
        quiet = sum(bool(self.quiet(m.task(x))) for x in open_ids)
        chips = [Chip(f"<b>{len(rows)}</b> to raise", "raise")] if rows else ([Chip("Nothing to raise", "calm")] if people or agendas else [])
        chips += [Chip(f"<b>{late}</b> late", "late")] * bool(late) + [Chip(f"<b>{soon}</b> due in {SOON_DAYS} days", "soon")] * bool(soon)
        if every is not None and not open_ids:
            chips.append(Chip("Nothing open matches all of them", "calm"))
        elif every is not None:
            chips += [Chip(f"<b>{len(open_ids)}</b> open")] + [Chip(f"<b>{crit}</b> Critical")] * bool(crit) + [Chip(f"<b>{quiet}</b> quiet")] * bool(quiet)
        counts = []
        for k in (PERSON, AGENDA, LABEL, TAG):
            n = sum(p.kind == k for p in parts)
            if n:
                counts.append(f"{n} {KIND_PLURALS[k][n != 1]}")
        kind = " · ".join([KIND_WORDS[MANY], *counts])
        return Summary(s, kind, "many", facts, chips, sections)

    def group_of(self, t: Task, subs: list[str]) -> str:
        """Where a label's task sits, for Where they stand: its top-level task, or for a parent label its sublabel."""
        if subs:
            own = [n for n, _inh in self.m.labels_of(t.id) if n in subs]
            return own[0] if own else "Itself"
        return self.m.task(self.m.chains_of(t.id)[0][0]).title

    def where_section(self, ts: list[Task], subs: list[str], oldest: Task | None, oldest_days: int, every: list[str]) -> Section:
        """A bar per group, split by priority, the largest first; under it the open count's last eight weeks and the oldest
        open task (decision 532)."""
        groups: dict[str, dict[str, int]] = {}
        for t in ts:
            g = groups.setdefault(self.group_of(t, subs), dict.fromkeys(BUCKETS, 0))
            g[t.priority or "none"] += 1
        rows = sorted(groups.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower()))
        biggest = max(sum(c.values()) for _g, c in rows)
        used = [b for b in BUCKETS if any(c[b] for _g, c in rows)]
        legend = " &nbsp; ".join(f'<img src="swatch:{b}" width="10" height="10"> {esc(BUCKET_NAMES[b])}' for b in used)
        bars = "".join(
            f'<tr><td width="190" valign="middle" title="{esc(g)}">{esc(clip(g, 34))}</td>'
            f'<td valign="middle"><img src="stack:{",".join(str(c[b]) for b in BUCKETS)}:{bar_width(c, biggest)}" width="{bar_width(c, biggest)}" height="12"'
            f' title="{esc(", ".join(f"{BUCKET_NAMES[b]} {c[b]}" for b in BUCKETS if c[b]))}"></td>'
            f'<td align="right" width="30" valign="middle">{sum(c.values())}</td></tr>'
            for g, c in rows)
        trend = self.trend(every)
        spark = (f'<img src="spark:{",".join(str(n) for n in trend)}" width="120" height="26" title="Open at the end of each of the last '
                 f'{TREND_WEEKS} weeks: {", ".join(str(n) for n in trend)}"> &nbsp;<span class="sub">open, {TREND_WEEKS} weeks: '
                 f'<b>{trend[0]}</b> to <b>{trend[-1]}</b></span>')
        old = f' &nbsp; &nbsp;<span class="sub">Oldest: {link(f"task:{oldest.id}", oldest.title, quiet="tq")}, <b>{oldest_days} d</b></span>' if oldest else ""
        body = (f'<p class="sub" style="margin: 0 0 6px 0">{legend}</p><table cellspacing="0" cellpadding="3">{bars}</table>'
                f'<p style="margin-top: 8px">{spark}{old}</p>')
        return Section("where", "Where they stand", "", f"by {'label' if subs else 'project'}, split by priority", body=body)

    def trend(self, every: list[str]) -> list[int]:
        """How many of these tasks were open at the end of each of the last ``TREND_WEEKS`` weeks, the oldest first: made by
        then and not closed by then. Parked ones count as open here, as they're still to be done."""
        out = []
        for k in range(TREND_WEEKS - 1, -1, -1):
            end = (self.today - timedelta(days=7 * k)).isoformat()
            n = 0
            for x in every:
                t = self.m.task(x)
                made = (t.created or "")[:10] <= end
                shut = t.state == "Closed" and (t.closed or "")[:10] <= end
                n += bool(made and not shut)
            out.append(n)
        return out

    # ---- the box ----
    def count_line(self, s: Subject) -> str:
        """What the box's row says beside a subject (decision 519): "3 to raise · 8 with you", "5 to raise", "14 open · 3 Critical"."""
        m = self.m
        if s.kind == MANY:
            every = self.chosen_tasks(s)
            raise_n = sum(len(m.open_items_for(p.ref)) for p in s.each() if p.kind in (PERSON, AGENDA))
            parts = [f"{raise_n} to raise"] * bool(raise_n) + ([f"{sum(worklike(m.task(x)) for x in every)} open"] if every is not None else [])
            return " · ".join(parts) or "Nothing to raise"
        if s.kind in (LABEL, TAG):
            ts = [m.task(x) for x in (self.label_task_ids(s.ref) if s.kind == LABEL else self.tag_task_ids(s.ref)) if worklike(m.task(x))]
            crit = sum(t.priority == "critical" for t in ts)
            return f"{len(ts)} open" + (f" · {crit} Critical" if crit else "")
        raise_n = len(m.open_items_for(s.ref))
        if s.kind == AGENDA:
            return f"{raise_n} to raise" if raise_n else "Nothing to raise"
        waiting_on, waiting_you, other = self.person_lists(s.ref)
        with_you = len(waiting_on) + len(waiting_you)
        parts = [f"{raise_n} to raise"] * bool(raise_n) + ([f"{with_you} with you" if with_you else "none with you"] if self.me else [f"{len(other)} open"])
        return " · ".join(parts)


SINGULAR = {"updates": "update", "notes": "note", "emails": "email", "changes": "change", "documents": "document", "agenda items": "agenda item"}


def email_conversations_tip() -> str:
    return "Open the conversation: every email of it DocRepo holds, oldest first"


# ---- Copy (decision 533) ----
def copy_text(b: Builder, s: Summary) -> tuple[str, str]:
    """What Copy puts on the clipboard, as Markdown and as HTML (rich text): an agenda as tick-box lines in the window's order,
    then a person's tasks that need a word; a label as a short note for a manager."""
    m, today = b.m, b.today
    md: list[str] = []
    html: list[str] = []
    subject = s.subject
    if subject.kind == MANY:
        for sec in s.sections:
            if sec.agenda is None:
                continue
            md.extend([f"## {sec.title}: to raise", ""])
            html.append(f"<p><b>{esc(sec.title)}: to raise</b></p>")
            items = []
            for a in sec.agenda:
                tail = f" ({m.task(a.task).title}{', ' + a.when if a.when else ''})" if a.task and a.question != m.task(a.task).title else ""
                md.append(f"- [ ] {a.question}{tail}")
                items.append(f"<li>☐ {esc(a.question)}{esc(tail)}</li>")
            if not items:
                md.append("Nothing to raise.")
            md.append("")
            html.append(f"<ul>{''.join(items)}</ul>" if items else "<p>Nothing to raise.</p>")
        every = b.chosen_tasks(subject)
        if every is not None:
            hot = [t for t in attention(m, [x for x in every if worklike(m.task(x))], today)
                   if is_late(m, t, today) or is_soon(m, t, today) or t.urgent or t.priority in ("critical", "high")]
            md.extend([f"### {subject.name}: needs a word", ""] if hot else [f"{subject.name}: nothing open needs a word."])
            items = []
            for t in hot[:SHOWN * 2]:
                when, _cls, _tip = b.when(t)
                words, _at = status_of(m, t)
                line = f"{t.title} ({when}{', urgent' if t.urgent else ''})" + (f": {words}." if words else "")
                md.append(f"- {line}")
                items.append(f"<li>{esc(line)}</li>")
            html.append(f"<p><b>{esc(subject.name)}: needs a word</b></p><ul>{''.join(items)}</ul>" if items else f"<p>{esc(subject.name)}: nothing open needs a word.</p>")
    elif subject.kind in (PERSON, AGENDA):
        agenda = s.section("agenda")
        rows = agenda.agenda if agenda and agenda.agenda else []
        md.append(f"## {subject.name}: to raise")
        html.append(f"<p><b>{esc(subject.name)}: to raise</b></p>")
        if rows:
            md.append("")
            items = []
            for a in rows:
                tail = f" ({m.task(a.task).title}{', ' + a.when if a.when else ''})" if a.task and a.question != m.task(a.task).title else \
                    (f" ({a.when})" if a.when else "")
                md.append(f"- [ ] {a.question}{tail}")
                items.append(f"<li>☐ {esc(a.question)}{esc(tail)}</li>")
            html.append(f"<ul>{''.join(items)}</ul>")
        else:
            md.extend(["", "Nothing to raise."])
            html.append("<p>Nothing to raise.</p>")
        if subject.kind == PERSON:
            waiting_on, waiting_you, _other = b.person_lists(subject.ref)
            on_agenda = {a.task for a in rows if a.task}
            hot = [t for t in attention(m, [x for x in (*waiting_on, *waiting_you) if x not in on_agenda], today)
                   if is_late(m, t, today) or is_soon(m, t, today) or t.urgent or t.priority == "critical"]
            if hot:
                md.extend(["", "### Needs a word", ""])
                items = []
                for t in hot:
                    when, _cls, _tip = b.when(t)
                    line = f"{t.title}: {when}" + (", urgent" if t.urgent else "")
                    md.append(f"- {line}")
                    items.append(f"<li>{esc(line)}</li>")
                html.append(f"<p><b>Needs a word</b></p><ul>{''.join(items)}</ul>")
    else:
        every = b.label_task_ids(subject.ref) if subject.kind == LABEL else b.tag_task_ids(subject.ref)
        ts = [m.task(x) for x in every if worklike(m.task(x))]
        subs = m.sublabels(subject.ref, active=False) if subject.kind == LABEL else []
        groups: dict[str, int] = {}
        for t in ts:
            g = b.group_of(t, subs)
            groups[g] = groups.get(g, 0) + 1
        crit = sum(t.priority == "critical" for t in ts)
        top = max(groups.items(), key=lambda kv: (kv[1], kv[0]), default=None)
        sentence = (f"{subject.name}: {len(ts)} open in {len(groups)} {'labels' if subs else 'projects'}"
                    + (f", {crit} Critical" if crit else "") + "." + (f" Most are in {top[0]} ({top[1]})." if top and len(groups) > 1 else ""))
        md.append(sentence)
        html.append(f"<p>{esc(sentence)}</p>")
        focus = [t for t in attention(m, [t.id for t in ts], today) if t.priority in ("critical", "high") or t.urgent or is_late(m, t, today)]
        if focus:
            md.extend(["", "Focus:", ""])
            items = []
            for t in focus[:SHOWN]:
                words, _at = status_of(m, t)
                bits = [PRIORITY_NAMES.get(t.priority or "", "")] + (["late"] if is_late(m, t, today) else []) + (["urgent"] if t.urgent else [])
                line = f"{t.title} ({', '.join(x for x in bits if x)})" + (f": {words}." if words else ".")
                md.append(f"- {line}")
                items.append(f"<li>{esc(line)}</li>")
            html.append(f"<p>Focus:</p><ul>{''.join(items)}</ul>")
    return "\n".join(md) + "\n", "".join(html)


# ---- pins and recents (decision 534) ----
def start_list(m: Model, me: str | None, pins: list[str], recent: list[str]) -> tuple[list[Subject], list[Subject]]:
    """The box's list with nothing typed: the pinned subjects, then the recent ones, ``START_MAX`` in all, each once, those
    that are gone left out."""
    pinned = [x for x in (subject_of(m, k, me) for k in dict.fromkeys(pins)) if x]
    keys = {x.key for x in pinned}
    recents = [x for x in (subject_of(m, k, me) for k in dict.fromkeys(recent) if k not in keys) if x]
    room = max(0, START_MAX - len(pinned))
    return pinned[:START_MAX], recents[:room]


def remember(recent: list[str], key: str) -> list[str]:
    """Recent subjects with ``key`` first, ``RECENT_KEEP`` at most."""
    return [key, *(k for k in recent if k != key)][:RECENT_KEEP]


def activity_href(s: Subject, since: date) -> str:
    """The link Show in Activity follows (decision 531): the subject and the day its window starts."""
    return f"activity:{s.kind}:{quote(s.ref, safe='')}:{since.isoformat()}"


def activity_window(href: str) -> tuple[str, str, date] | None:
    """What a Show in Activity link names: (the subject's kind, its ref, the window's first day)."""
    parts = href.split(":")
    if len(parts) != 4 or parts[0] != "activity" or parts[1] not in (PERSON, AGENDA, LABEL, TAG):
        return None
    try:
        return parts[1], unquote(parts[2]), date.fromisoformat(parts[3])
    except ValueError:
        return None


def summary_href(s: Subject) -> str:
    """The link that opens a subject's quick summary, from a page in the browse tool."""
    return f"summary:{s.kind}:{quote(s.ref, safe='')}"
