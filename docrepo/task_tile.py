"""The task tile (release 5.138, the task tile plan's decisions 563 to 579): the one line a task is drawn as wherever tasks
are listed, worked out here without Qt, so the fast run tests it, as ``file_rows.py`` holds the file rows' recipe.

A tile, left to right:
- depth ticks, in a flat list only (decision 570);
- the state circle, which opens the state menu (564);
- the title, cut to fit (565);
- Urgent's flag and the two-parents mark (569, 570);
- the view's own quiet context;
- three marks in fixed slots (566, 567);
- the days to the nearer of Due and Deadline (568).

The browse window paints it (``ui/tree_view.py``). The Today side panel and the Priorities board draw it as widgets
(``ui/task_tile.py``). Pages write it as HTML (``html`` here).
"""
from __future__ import annotations

import re
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from html import escape

from docrepo import waits as wait_records
from docrepo.dates import day_diff, days_words, long_date, to_date
from docrepo.model import TODAY, Model, Task
from docrepo.schedule import due_of

# ---- the title (decision 565) ----
ELLIPSIS = "…"
#: A cut keeps at least this many words, or it isn't offered.
MIN_WORDS = 2
#: A full stop after one of these ends an abbreviation, not a sentence: "Review rev. B of the drawings".
ABBREVIATIONS = frozenset({"rev", "no", "nos", "vs", "approx", "incl", "e.g", "i.e", "etc", "fig", "ref", "dept", "min", "max", "st",
                           "mr", "mrs", "ms", "dr", "qty", "ca", "cf", "al", "ea", "pt", "pp", "vol", "ver"})
#: A sentence ends at ".", "?" or "!" with a space after it, so "2.5 m" and "v1.2" never end one.
_SENTENCE_END = re.compile(r"[.!?](?=\s+\S)")
_CLAUSE_END = re.compile(r"[,;](?=\s)")
#: On a page, where the tile can't be measured, a title longer than this is cut the same way (decision 577).
PAGE_TITLE_CHARS = 60


def _words(text: str) -> int:
    return len(text.split())


def title_cuts(title: str) -> list[str]:
    """Where a title too long for its tile may be cut, longest first: its first sentence, then up to its first comma or
    semicolon within that sentence. Each keeps at least ``MIN_WORDS`` words; the "…" isn't added here."""
    title = " ".join(title.split())
    sentence = ""
    for m in _SENTENCE_END.finditer(title):
        head = title[:m.start()]
        last = head.rsplit(" ", 1)[-1]
        if title[m.start()] == "." and (last.lower() in ABBREVIATIONS or re.fullmatch(r"[A-Za-z]", last)):
            continue  # "rev. B", "No. 4", "J. Smith"
        if _words(head) >= MIN_WORDS:
            sentence = head.rstrip()
        break
    cuts = [sentence] if sentence else []
    scope = sentence or title
    m = _CLAUSE_END.search(scope)
    if m:
        clause = scope[:m.start()].rstrip()
        if _words(clause) >= MIN_WORDS and clause not in cuts:
            cuts.append(clause)
    return cuts


def _elide(text: str, room: float, measure: Callable[[str], float]) -> str:
    """``text`` cut at the end with "…" to fit ``room``, by the characters that fit."""
    if measure(text) <= room:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid].rstrip() + ELLIPSIS) <= room:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ELLIPSIS if lo else ELLIPSIS


def fit_title(title: str, room: float, measure: Callable[[str], float], elide: Callable[[str, float], str] | None = None) -> str:
    """The title as a tile shows it in ``room``: whole when it fits; else its first sentence, then its first clause, with "…";
    else the shortest of those (or the whole title) cut at the edge. ``measure`` gives a text's width, and ``elide`` cuts one
    at the edge (Qt's own, in the painted tile); both are in the same units as ``room``."""
    title = " ".join(title.split())
    if measure(title) <= room:
        return title
    cuts = title_cuts(title)
    for cut in cuts:
        if measure(cut + ELLIPSIS) <= room:
            return cut + ELLIPSIS
    base = cuts[-1] if cuts else title
    return elide(base, room) if elide is not None else _elide(base, room, measure)


def page_title(title: str, chars: int = PAGE_TITLE_CHARS) -> str:
    """A title on a page's tile, cut by the same rule to ``chars`` characters."""
    return fit_title(title, chars, len)


# ---- the days (decision 568) ----
#: Within this many days, the number is in caution's colour: today, tomorrow and the day after.
SOON_DAYS = 2
#: Above this, the number says "99+", so the column keeps its width.
MAX_DAYS = 99
MINUS = "−"


@dataclass(frozen=True)
class Days:
    """The number at a tile's right end."""

    value: int
    #: "6", "0", "−3" or "99+".
    text: str
    #: "" (grey), "soon" (caution) or "over" (critical).
    kind: str
    #: The date counted is the Deadline: a ◆ before the number.
    deadline: bool
    #: Both dates in words: "Due Fri 9 Oct, tomorrow · Deadline Mon 19 Oct, in 11 days".
    tip: str


def days(task: Task, today: date) -> Days | None:
    """Days to the nearer of the task's Due and Deadline (a Deadline on the same day counts as the Deadline), or to a routine
    task's next occurrence. None with no date, or for a closed or discarded task. A parked task's number stays grey."""
    if task.state == "Closed" or getattr(task, "discarded", None):
        return None
    dates: list[tuple[date, str]] = []
    if task.recurrence:
        nxt = due_of(task, today)
        if nxt is not None:
            dates.append((nxt.date, nxt.label))
    else:
        if task.due:
            dates.append((to_date(task.due), "Due"))
        if task.deadline:
            dates.append((to_date(task.deadline), "Deadline"))
    if not dates:
        return None
    dates.sort(key=lambda x: (x[0], x[1] != "Deadline"))
    day, label = dates[0]
    tip = " · ".join(f"{lab} {long_date(d, today)}, {days_words(d, today)}" for d, lab in dates)
    return days_to(day, today, label, quiet=task.state == "Parked", tip=tip)


def days_to(day: date, today: date, label: str = "Due", *, quiet: bool = False, tip: str = "") -> Days:
    """The number for one date: a task's nearer one, or a key date's in the lists (so the column reads one way). ``quiet``
    keeps it grey, as a parked task's is."""
    n = day_diff(today, day)
    text = f"{MAX_DAYS}+" if n > MAX_DAYS else f"{MINUS}{-n}" if n < 0 else str(n)
    kind = "" if quiet else "over" if n < 0 else "soon" if n <= SOON_DAYS else ""
    return Days(n, text, kind, label == "Deadline", tip or f"{label} {long_date(day, today)}, {days_words(day, today)}")


# ---- the marks (decisions 566 and 567) ----
#: The three slots, in their order, with each one's icon: the sidebar's own for Today, Agendas and Waiting on others.
KINDS = ("today", "agenda", "wait")
ICONS = {"today": "sun", "agenda": "agenda", "wait": "waiting"}


@dataclass(frozen=True)
class Mark:
    kind: str
    icon: str
    #: The colour's token: "text2", or "caution" for a wait whose follow-up day has come.
    colour: str
    tip: str


@dataclass(frozen=True)
class TileWait:
    """What a tile's hourglass says of a task's open wait (release 5.139's ``docrepo.waits``, the email-progress plan's
    decisions 580 and 581): since when, a row's words ("waiting on Dana · Thu", or "no reply from Dana since Thu" once its
    follow-up day has come), its tooltip, and whether that day has come."""

    since: str
    words: str
    tip: str
    late: bool = False


@dataclass(frozen=True)
class Marks:
    """What the marks show, for every task at once, read from the model in memory."""

    today: frozenset[str]
    #: Each task's open agenda items' targets, by name: a meeting's title or a person's name.
    agendas: dict[str, tuple[str, ...]]
    waits: dict[str, TileWait]


_MARKS: "weakref.WeakKeyDictionary[Model, tuple[date, Marks]]" = weakref.WeakKeyDictionary()


def listed(names: Iterable[str]) -> str:
    """"A", "A and B", "A, B and C"."""
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}" if names else ""


def wait_of(m: Model, task_id: str, today: date) -> TileWait | None:
    """The wait a task's hourglass shows (decision 567): its open wait (release 5.139), or None. An Ask for an update starts
    one too (the email-progress plan's decision 593)."""
    w = wait_records.current(m, task_id)
    if w is None:
        return None
    late = w.late(today)
    tip = wait_records.tip(m, w, today)
    if late:  # "No reply from Dana since Thu." first, as the row's words say it
        said = wait_records.words(m, w, today)
        tip = f"{said[:1].upper()}{said[1:]}. {tip}"
    return TileWait(w.since, wait_records.words(m, w, today, row=True), tip, late)


def marks(m: Model, today: date) -> Marks:
    """Today's tasks, each task's agendas and its wait, once per model and day."""
    cached = _MARKS.get(m)
    if cached is not None and cached[0] == today:
        return cached[1]
    on_today: set[str] = set()
    agendas: dict[str, list[str]] = {}
    for a in m.agenda:
        if a.closed or not a.subject:
            continue
        if a.target == TODAY:
            on_today.add(a.subject)
        else:
            names = agendas.setdefault(a.subject, [])
            name = m.target_name(a.target)
            if name not in names:
                names.append(name)
    waits = {}
    for task_id in wait_records.open_waits(m):
        w = wait_of(m, task_id, today)
        if w is not None:
            waits[task_id] = w
    out = Marks(frozenset(on_today), {k: tuple(v) for k, v in agendas.items()}, waits)
    _MARKS[m] = (today, out)
    return out


def slots(task_id: str, marks_: Marks, hide: Iterable[str] = ()) -> tuple[Mark | None, ...]:
    """A tile's marks, a slot for each kind but those ``hide`` leaves out (a mark every row of a view would show): a ``Mark``
    where it's true, None where it isn't, so each kind keeps its place down a list."""
    out: list[Mark | None] = []
    for kind in KINDS:
        if kind in hide:
            continue
        mark = None
        if kind == "today" and task_id in marks_.today:
            mark = Mark(kind, ICONS[kind], "text2", "On Today")
        elif kind == "agenda" and task_id in marks_.agendas:
            mark = Mark(kind, ICONS[kind], "text2", f"On the agenda of {listed(marks_.agendas[task_id])}")
        elif kind == "wait" and task_id in marks_.waits:
            w = marks_.waits[task_id]
            mark = Mark(kind, ICONS[kind], "caution" if w.late else "text2", w.tip)
        out.append(mark)
    return tuple(out)


# ---- where a task sits (decision 570) ----
#: The most depth ticks a tile shows; deeper tasks show this many, and say how deep in the tooltip.
MAX_TICKS = 4


def depth(m: Model, task_id: str) -> int:
    """How many generations are above a task, up its first parent, as Today's project context counts them."""
    return len(m.chains_of(task_id)[0]) - 1


def depth_tip(m: Model, task_id: str) -> str:
    """"2 levels down: Reactor impeller upgrade › Installation", or "" for a top-level task."""
    chain = m.chains_of(task_id)[0][:-1]
    if not chain:
        return ""
    n = len(chain)
    return f"{n} level{'s' if n > 1 else ''} down: " + " › ".join(m.task(x).title for x in chain if x in m.tasks)


def parents_tip(m: Model, task_id: str, under: str | None = None) -> str:
    """The two-parents mark's tooltip, or "" for a task with one parent or none: "Under Installation and Q4 cost reduction",
    or "Also under Q4 cost reduction" where the tile sits under ``under``, one of them."""
    parents = [p for p in m.parents_of(task_id) if p in m.tasks]
    if len(parents) < 2:
        return ""
    if under in parents:
        return "Also under " + listed(m.task(p).title for p in parents if p != under)
    return "Under " + listed(m.task(p).title for p in parents)


# ---- a whole tile ----
@dataclass(frozen=True)
class Tile:
    """Everything a tile shows for one task. ``depth`` is -1 where the view shows depth by indentation, so no ticks."""

    task_id: str
    title: str
    state: str
    priority: str
    urgent: bool
    parents: str
    depth: int
    depth_tip: str
    marks: tuple[Mark | None, ...]
    days: Days | None
    closed: bool


def tile(m: Model, task_id: str, today: date, marks_: Marks | None = None, *, hide: Iterable[str] = (), flat: bool = False,
         under: str | None = None) -> Tile:
    """The tile for a task. ``flat`` lists show depth ticks; ``hide`` leaves out a mark kind every row of the view would show;
    ``under`` is the parent the tile sits under, for the two-parents mark's words."""
    t = m.task(task_id)
    marks_ = marks_ if marks_ is not None else marks(m, today)
    d = depth(m, task_id) if flat else -1
    return Tile(task_id, t.title, t.state, t.priority if t.priority and t.state != "Closed" else "", bool(t.urgent),
                parents_tip(m, task_id, under), d, depth_tip(m, task_id) if d > 0 else "", slots(task_id, marks_, hide),
                days(t, today), t.state == "Closed")


def tooltip(t: Tile, priority_names: dict[str, str] | None = None) -> str:
    """A tile's tooltip: its whole title, then what its marks and colours say in words."""
    lines = [t.title, t.state]
    if t.priority and priority_names:
        lines.append(f"Priority: {priority_names.get(t.priority, t.priority)}")
    if t.urgent:
        lines.append("Urgent")
    if t.parents:
        lines.append(t.parents)
    lines += [mk.tip for mk in t.marks if mk is not None]
    if t.days is not None:
        lines.append(t.days.tip)
    return "\n".join(lines)


# ---- on a page (decision 577) ----
STATE_KEYS = {"Not started": "ns", "In progress": "ip", "Parked": "pk", "Closed": "cl"}


def _img(src: str, size: int, tip: str) -> str:
    return f'<img src="{escape(src)}" width="{size}" height="{size}" style="vertical-align: middle" title="{escape(tip)}">'


def days_html(d: Days | None, align: str = "right", block: bool = True) -> str:
    """The days number as a list's cell writes it (a paragraph, aligned), or as words in a page's cell (``block`` False)."""
    if d is None:
        return ""
    cls = {"over": "over", "soon": "caution"}.get(d.kind, "rel")
    weight = ' style="font-weight:600"' if d.kind else ""
    mark = '<span style="font-size:7pt">◆</span>&nbsp;' if d.deadline else ""
    words = f'<span class="{cls}"{weight} title="{escape(d.tip)}">{mark}{escape(d.text)}</span>'
    return f'<p align="{align}" title="{escape(d.tip)}">{words}</p>' if block else words


def circle_html(t: Tile) -> str:
    """A page tile's circle: a ``state:`` link that opens the state menu (decision 564)."""
    key = STATE_KEYS.get(t.state, "ns")
    return f'<a href="state:{escape(t.task_id)}" title="{escape(t.state)}. Click to change the state.">{_img(f"mark:{key}", 14, t.state)}</a>'


def title_html(t: Tile, link: Callable[[str, str], str]) -> str:
    """A page tile's title: a link to its page, cut by ``page_title`` with the whole in its tooltip, struck when closed."""
    title = page_title(t.title)
    words = link(f"task:{t.task_id}", title)
    if title != t.title:
        words = f'<span title="{escape(t.title)}">{words}</span>'
    return f"<s>{words}</s>" if t.closed else words


def extras_html(t: Tile) -> str:
    """Urgent's flag and the two-parents mark, after a page tile's title (decisions 569 and 570)."""
    return (" " + _img("tm:urgent", 13, "Urgent") if t.urgent else "") + (" " + _img("tm:parents", 13, t.parents) if t.parents else "")


def marks_html(t: Tile) -> str:
    """A page tile's marks, an empty slot where one isn't true (decision 566)."""
    return "".join(_img(f"tm:{mk.icon}{'-late' if mk.colour == 'caution' else ''}", 14, mk.tip) if mk is not None else
                   '<img src="tm:blank" width="14" height="14">' for mk in t.marks)


def html(t: Tile, link: Callable[[str, str], str], context: str = "") -> str:
    """A tile as a page's table row: its circle (a ``state:`` link that opens the state menu), its title (cut by
    ``page_title``, the whole in its tooltip), its flag and two-parents mark, ``context`` (HTML already), its marks and its
    days. ``link(href, text)`` writes a link as the page does; a right-click on the title or the circle is the tile's menu."""
    return (f'<tr><td class="tile" width="20" valign="middle">{circle_html(t)}</td>'
            f'<td class="tile" valign="middle">{title_html(t, link)}{extras_html(t)}{(" " + context) if context else ""}</td>'
            f'<td class="tile" align="right" valign="middle" width="{18 * len(t.marks) + 4}">{marks_html(t)}</td>'
            f'<td class="tile" align="right" valign="middle" width="34">{days_html(t.days, block=False)}</td></tr>')


#: A page's table of tiles: the cells meet, and each row's white underline sets it apart (decision 571).
TABLE = '<table width="100%" cellspacing="0" cellpadding="4" style="border-collapse: collapse">'
