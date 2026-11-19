"""Topic headings and the heading list (release 5.156; the design workspace's ``docs/mods/notes-topics-plan.md``,
decisions 704 to 708, the owner's voice memo of 2026-11-16).

A **topic heading** is a heading of the owner's on a notes page or in a capture, at level 1, 2 or 3 (release 5.28's
``# ``, ``## `` and ``### ``), that isn't a day heading. It isn't the glossary's **Heading**, a line of ``#`` tasks.

**Its reach** (decision 708): a topic heading covers the lines after it up to the next heading at its level or above,
and never past its block: the next caption, lead line or day heading. Its **path** is the topic headings in force over
it, its own words last ("Vendor › Lead time"); a level missing from a path is left out of it. A **topic** is a path on a
task's pages, its words matched case and spacing aside.

**The heading list** (decisions 705 and 707): typing in a topic heading lists the topic headings already used at its
level, from the pages of a task and every task under it, then, after an "Elsewhere in …" row, from the rest of its
top-level task's tree. Headings with the same words under the same heading are one row, spelled as most recently typed,
each saying what it's under, how often it's been used and when last. The headings typed in the same box count with the
task's own; the line being typed doesn't. Since release 5.169 (``docrepo.stock_headings``, decision 789) a "Stock
headings" group comes last: the owner's stock headings at that level the page doesn't have yet, each with what belongs
under it, on every task, and in the capture window before a task is picked.

**All notes grouped** (release 5.157, decisions 709 to 717): All notes read By meeting or By topic, task first. A
**band** for the task and for each live task under it, in tree order, meetings not among them; a meeting's page goes in
its home task's band (decision 610). By meeting lists each band's **occasions** oldest first: a meeting (from a block of
its notes, an item made from them, lines moved from its page, or anything on its page) or a day's other entries
("Notes", "Email"). By topic lists each band's topics in the order first used, each topic's **runs** (lines of one
block under it) oldest first, then the lines under no topic heading. Both read every day (decision 714).

Nothing here touches Qt; ``docrepo.ui.heading_list`` shows the list, and ``detail.Pages.grouped_notes`` draws the groupings.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from functools import lru_cache

from docrepo import markup, meeting_rows, notes_page
from docrepo.all_notes import Block, blocks_of
from docrepo.model import Model
from docrepo.stock_headings import StockHeading

#: The words a typed word is matched against the start of: a heading's words split at spaces and punctuation.
_WORD_BREAK = re.compile(r"[\s,.;:/()\[\]\-–—›&+]+")
#: A caption's leading date ("Thu 8 Oct 2026 · 10:42 am · Note"), the day a page with no day headings dates its block by.
_CAPTION_DAY = re.compile(r"^((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} \w{3} \d{4})")


@dataclass(frozen=True)
class Heading:
    """A topic heading: its level (1 to 3), its words, its path (the topic headings in force over it, its own words last),
    the day it's dated by (its day heading's, else its caption's; None when the page says none), the page it's on (a
    task's ID; "" for the box being typed in), and ``n``, its place among the page's heading lines (day headings counted),
    which a box uses to leave out the line being typed."""

    level: int
    words: str
    path: tuple[str, ...]
    day: date | None
    page: str = ""
    n: int = -1

    @property
    def under(self) -> str:
        """The topic heading it's under, in words ("" for none)."""
        return self.path[-2] if len(self.path) > 1 else ""


@dataclass(frozen=True)
class Row:
    """A row of the heading list: the words (as most recently typed), the level, the topic heading it's under, how many
    times it's been used, the day it was last used, and whether it's from the task and what's under it (``here``) or
    elsewhere in its top-level task."""

    words: str
    level: int
    under: str
    times: int
    last: date | None
    here: bool
    #: What belongs under it, when its words are a stock heading's at its level (release 5.169, decision 789); "" otherwise.
    about: str = ""
    #: Whether it's a stock heading the page doesn't have yet (decision 789): never used, so ``times`` is 0.
    stock: bool = False


@dataclass(frozen=True)
class Listing:
    """What the heading list shows: the task's rows, then the rest of its project's under ``elsewhere`` (the top-level
    task's title, for the "Elsewhere in …" row; "" when the task is top-level), then the stock headings it doesn't have
    (release 5.169, decision 789)."""

    here: list[Row]
    others: list[Row]
    elsewhere: str = ""
    stock: list[Row] = field(default_factory=list)

    def rows(self) -> list[Row]:
        return self.here + self.others + self.stock


def same(words: str) -> str:
    """Words as a heading is matched by: case and spacing aside (as release 5.94's note placing matches them)."""
    return " ".join(words.split()).casefold()


def heading_words(text: str) -> str:
    """A heading line's words in plain text: its marks dropped."""
    return " ".join(markup.to_plain(text).split())


def sections(page: str, page_id: str = "") -> list[Heading]:
    """The topic headings on a page (or in a capture's markup), in order, each with its path and day (decision 708). Day
    headings, captions and lead lines end every topic heading's reach; a day heading or a caption with a date dates what
    follows. Read once per page's words: the list asks again at every key typed."""
    return list(_sections(page, page_id))


@lru_cache(maxsize=1024)
def _sections(page: str, page_id: str) -> tuple[Heading, ...]:
    out: list[Heading] = []
    path: list[tuple[int, str]] = []
    day: date | None = None
    n = -1
    for x in notes_page.lines_of(page):
        if x.kind == "heading":
            n += 1
            d = notes_page.day_of(x.text)
            if d is not None:
                day, path = d, []
                continue
            words = heading_words(x.text)
            if not words:
                continue
            path = [p for p in path if p[0] < x.level] + [(x.level, words)]
            out.append(Heading(x.level, words, tuple(w for _lv, w in path), day, page_id, n))
            continue
        if x.kind in ("caption", "lead"):
            path = []
            if x.kind == "caption" and (m := _CAPTION_DAY.match(x.text)):
                day = notes_page.day_of(m.group(1)) or day
    return tuple(out)


def in_force(headings: list[Heading], level: int) -> str:
    """The topic heading a new heading at ``level`` would be under, from the headings above it in its block, the last
    first: the nearest one at a lower level. "" for level 1, or with none."""
    for h in reversed(headings):
        if h.level < level:
            return h.words
    return ""


def matches(words: str, typed: str) -> bool:
    """Whether a heading's words match what's typed: each typed word the start of one of its words, in any order (as the
    ``#`` list matches, release 5.74)."""
    have = [w for w in _WORD_BREAK.split(words.casefold()) if w]
    return all(any(w.startswith(t) for w in have) for t in _WORD_BREAK.split(typed.casefold()) if t)


def scope(model: Model, task_id: str) -> tuple[list[str], list[str], str]:
    """The pages a task's heading list reads (decision 705): the task and every live task under it; then the rest of its
    top-level task's tree (by its first chain of parents); and that top-level task's title ("" when the task is one)."""
    live = lambda x: x in model.tasks and not model.tasks[x].discarded  # noqa: E731 - a one-line test
    here = [x for x in model.scope_ids(task_id, "descendants") if live(x)]
    top = model.chains_of(task_id)[0][0] if task_id in model.tasks else task_id
    if top == task_id:
        return here, [], ""
    seen = set(here)
    others = [x for x in model.scope_ids(top, "descendants") if live(x) and x not in seen]
    return here, others, model.task(top).title


def _rows(headings: list[Heading], level: int, here: bool) -> dict[tuple[str, str], Row]:
    out: dict[tuple[str, str], Row] = {}
    for h in headings:
        if h.level != level:
            continue
        key = (same(h.under), same(h.words))
        r = out.get(key)
        if r is None:
            out[key] = Row(h.words, level, h.under, 1, h.day, here)
            continue
        newer = h.day is not None and (r.last is None or h.day >= r.last)
        out[key] = Row(h.words if newer else r.words, level, h.under if newer else r.under, r.times + 1,
                       h.day if newer else r.last, here)
    return out


def _order(rows: list[Row], typed: str, under: str) -> list[Row]:
    """Decision 707: words starting with what's typed first, then those under the heading in force (705), then the most
    recently used, then by their words."""
    t, u = same(typed), same(under)
    return sorted(rows, key=lambda r: (bool(t) and not same(r.words).startswith(t), bool(u) and same(r.under) != u,
                                       -(r.last.toordinal() if r.last else 0), same(r.words)))


def options(model: Model, task_id: str | None, level: int, typed: str = "", under: str = "",
            own: list[Heading] | None = None, own_page: str | None = None, stock: Sequence[StockHeading] = ()) -> Listing:
    """The heading list for a topic heading at ``level`` being typed for ``task_id`` (decisions 705 and 707): the rows
    whose words match ``typed``, in order. ``under`` is the topic heading in force over the line (``in_force``); ``own``
    the headings typed in the same box, the line being typed left out, counted with the task's own; with ``own_page``,
    that task's page is read from ``own`` rather than from docs.db (the notes page being edited, which saves as it goes).

    ``stock`` (release 5.169, decision 789): the stock headings, of which those at ``level`` that aren't already a row (on
    the task's pages, its project's or the box) come last; a row whose words are a stock heading's says what belongs under
    it (``Row.about``). With no task there are only those, less any already in the box."""
    if level not in (1, 2, 3):
        return Listing([], [])
    about = {h.key: h.description for h in stock}
    if not task_id or task_id not in model.tasks:
        here: dict[tuple[str, str], Row] = {}
        others: dict[tuple[str, str], Row] = {}
        top = ""
        have = {same(h.words) for h in own or [] if h.level == level}
    else:
        here_ids, other_ids, top = scope(model, task_id)
        mine = [h for x in here_ids if x != own_page for h in sections(model.pages.get(x, ""), x)] + list(own or [])
        theirs = [h for x in other_ids if x != own_page for h in sections(model.pages.get(x, ""), x)]
        here = _rows(mine, level, True)
        others = {k: r for k, r in _rows(theirs, level, False).items() if k not in here}
        have = {k[1] for k in here} | {k[1] for k in others}
    tell = lambda r: replace(r, about=about.get((level, same(r.words)), ""))  # noqa: E731 - a one-line mapping
    fresh = [Row(h.name, level, "", 0, None, False, h.description, True) for h in stock
             if h.level == level and same(h.name) not in have]
    pick = lambda rows: _order([tell(r) for r in rows if not typed.strip() or matches(r.words, typed)], typed, under)  # noqa: E731
    theirs_shown = pick(list(others.values()))
    t = same(typed)
    stock_shown = sorted([r for r in fresh if not typed.strip() or matches(r.words, typed)],
                         key=lambda r: bool(t) and not same(r.words).startswith(t))  # the starts first, else Settings' order
    return Listing(pick(list(here.values())), theirs_shown, top if theirs_shown else "", stock_shown)


def short_day(d: date, today: date) -> str:
    """A day as the list says it: "Tue 10 Nov", with its year when it isn't this year's."""
    words = notes_page.day_title(d)
    return words if d.year != today.year else words.rsplit(" ", 1)[0]


def sub_text(r: Row, today: date) -> str:
    """A row's grey words: what it's under, how often it's been used, and when last ("under Vendor · 3 times · last
    Tue 10 Nov"; "once · Thu 5 Nov"); for a stock heading the page doesn't have yet, what belongs under it (decision 789)."""
    if r.stock:
        return r.about
    times = "once" if r.times == 1 else "twice" if r.times == 2 else f"{r.times} times"
    when = (("last " if r.times > 1 else "") + short_day(r.last, today)) if r.last else ""
    return " · ".join(x for x in (f"under {r.under}" if r.under else "", times, when) if x)


# ---- All notes grouped (release 5.157, decisions 709 to 717) ----

#: All notes' groupings (decision 709), as the Group strip names them, By day first (release 5.140's, as it was).
GROUPS = {"day": "By day", "meeting": "By meeting", "topic": "By topic"}
#: What a day's entries that aren't a meeting's are called (decision 710): an email's, and the rest's.
NOTES, EMAIL = "Notes", "Email"
#: What By topic calls the lines under no topic heading (decision 711).
LOOSE = "Not under a topic heading"


@dataclass(frozen=True)
class Occasion:
    """Where a block came from (decision 710): a meeting (``meeting`` its task, ``label`` its title), or a day's other
    entries (``label`` "Notes" or "Email"); and the day."""

    label: str
    day: date
    meeting: str = ""


@dataclass
class Run:
    """Lines of one block under one topic, or under none (decision 711): the block, its occasion and the lines, the
    topic's headings left out. An email's block is a run with no lines: it reads as one line."""

    block: Block
    occasion: Occasion
    lines: list[notes_page.Line] = field(default_factory=list)


@dataclass
class Topic:
    """A topic in a band (decisions 708 and 711): its path as matched (``key``), its words as most recently typed
    (``path``), and its runs, oldest first."""

    key: tuple[str, ...]
    path: tuple[str, ...]
    runs: list[Run] = field(default_factory=list)

    @property
    def words(self) -> str:
        return self.path[-1]


@dataclass
class Band:
    """A task's band (decisions 710 and 711): the task; the tasks between the All notes' task and it (``above``, that
    task first; none for that task itself); By meeting's occasions, each with its blocks, oldest first; By topic's topics
    in the order first used, and its runs under no topic heading (``loose``)."""

    task: str
    above: list[str]
    occasions: list[tuple[Occasion, list[Block]]] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    loose: list[Run] = field(default_factory=list)

    def ordered(self) -> list[tuple[Topic, int]]:
        """Its topics as they read, each with its level: each top topic in the order first used, then the topics under it,
        each under its own (a level 2 topic under its level 1, a level 3 under its level 2)."""
        known = {t.key for t in self.topics}
        kids: dict[tuple[str, ...], list[Topic]] = {}
        tops: list[Topic] = []
        for t in self.topics:
            if len(t.key) > 1 and t.key[:-1] in known:
                kids.setdefault(t.key[:-1], []).append(t)
            else:
                tops.append(t)
        out: list[tuple[Topic, int]] = []

        def walk(t: Topic, level: int) -> None:
            out.append((t, level))
            for k in kids.get(t.key, []):
                walk(k, level + 1)
        for t in tops:
            walk(t, 1)
        return out

    def runs_in(self, topic: Topic) -> int:
        """How many runs a topic has, with the topics under it (the outline's count, decision 713)."""
        n = len(topic.key)
        return sum(len(t.runs) for t in self.topics if t.key[:n] == topic.key)


@dataclass
class Grouped:
    """A task's All notes grouped (``group``, "meeting" or "topic"): its bands with something to show, in tree order."""

    task: str
    group: str
    bands: list[Band]


def band_tasks(model: Model, task_id: str) -> tuple[list[str], list[str]]:
    """The tasks All notes reads (the task and every live task under it, in tree order), and those that have a band
    (decision 710): the task itself, and the rest that aren't meetings."""
    scope = [x for x in model.scope_ids(task_id, "descendants") if x in model.tasks and not model.tasks[x].discarded]
    return scope, [x for x in scope if x == task_id or not model.tasks[x].meeting]


def home_band(model: Model, page: str, bands: set[str], scope: set[str], task_id: str) -> str:
    """The band a page's blocks go in: its own, or for a meeting's page the nearest band above it (its home task, decision
    610), up its parents within All notes; else the All notes' task."""
    here, seen = page, {page}
    while here not in bands:
        up = next((p for p in model.parents_of(here) if p in scope and p not in seen), None)
        if up is None:
            return task_id
        here = up
        seen.add(here)
    return here


def above(model: Model, task_id: str, band: str) -> list[str]:
    """The tasks from the All notes' task down to a band's parent, by the band's first chain through it."""
    if band == task_id:
        return []
    for chain in model.chains_of(band):
        if task_id in chain:
            return chain[chain.index(task_id):-1]
    return [task_id]


def is_email(model: Model, b: Block) -> bool:
    """Whether a block is an email's, which All notes reads as one line (decision 606)."""
    c = model.captures.get(b.capture or "")
    return c is not None and c.source == "outlook_email"


def occasion_of(model: Model, b: Block) -> Occasion:
    """A block's occasion (decision 710): the meeting whose notes it is, whose notes made it (``from_notes``), whose page
    its lines were moved from, or whose page it's on; else the day's emails or other notes."""
    c = model.captures.get(b.capture or "")
    meeting = None
    if c is not None:
        meeting = meeting_rows.meeting_of(model, c.id if c.item == "notes" else c.from_notes)
    for x in (b.came_from, b.page):
        if meeting is None and x in model.tasks and model.tasks[x].meeting and not model.tasks[x].discarded:
            meeting = x
    if meeting:
        return Occasion(model.task(meeting).title, b.day, meeting)
    return Occasion(EMAIL if is_email(model, b) else NOTES, b.day)


def band_blocks(model: Model, task_id: str) -> list[tuple[str, list[Block]]]:
    """Each band's blocks, oldest first, every day of them (decision 714): its own page's and its meetings' pages', each
    block with lines. A block an item made from notes, and lines moved from a page, stay in their own page's band: the
    task line or pointer line where they came from stays one line (decision 710)."""
    scope, bands = band_tasks(model, task_id)
    rank = {x: i for i, x in enumerate(scope)}
    band_set, scope_set = set(bands), set(scope)
    out: dict[str, list[Block]] = {x: [] for x in bands}
    for x in scope:
        out[home_band(model, x, band_set, scope_set, task_id)] += [b for b in blocks_of(model, x) if b.lines]
    for blocks in out.values():
        blocks.sort(key=lambda b: (b.day, b.at, rank[b.page], b.order))
    return [(x, out[x]) for x in bands]


def occasions(model: Model, task_id: str) -> Grouped:
    """All notes By meeting (decision 710): a band per task with something to show, each with its occasions oldest first,
    each occasion's blocks in the order they came in."""
    out: list[Band] = []
    for task, blocks in band_blocks(model, task_id):
        found: dict[Occasion, list[Block]] = {}
        for b in blocks:
            found.setdefault(occasion_of(model, b), []).append(b)
        if found:
            out.append(Band(task, above(model, task_id, task), occasions=list(found.items())))
    return Grouped(task_id, "meeting", out)


def by_topic(model: Model, task_id: str) -> Grouped:
    """All notes By topic (decisions 708 and 711): a band per task with something to show, each with its topics in the
    order first used and their runs oldest first, then its lines under no topic heading. A topic is a path, its words
    matched case and spacing aside, read by 708's reach: a topic heading covers what follows it in its block up to the
    next heading at its level or above."""
    out: list[Band] = []
    for task, blocks in band_blocks(model, task_id):
        band = Band(task, above(model, task_id, task))
        index: dict[tuple[str, ...], Topic] = {}
        for b in blocks:
            o = occasion_of(model, b)
            if is_email(model, b):
                band.loose.append(Run(b, o))
                continue
            path: list[tuple[int, str]] = []
            run: Run | None = None
            for x in b.lines:
                if x.kind == "heading":
                    words = heading_words(x.text)
                    if not words or notes_page.day_of(x.text):
                        continue
                    path = [p for p in path if p[0] < x.level] + [(x.level, words)]
                    key = tuple(same(w) for _lv, w in path)
                    if key not in index:
                        index[key] = Topic(key, tuple(w for _lv, w in path))
                        band.topics.append(index[key])
                    else:  # spelled as most recently typed, as the heading list spells it (705)
                        index[key].path = tuple(w for _lv, w in path)
                    run = None
                    continue
                if run is None:
                    if x.kind == "text" and not x.text.strip():
                        continue
                    run = Run(b, o)
                    key = tuple(same(w) for _lv, w in path)
                    (index[key].runs if key else band.loose).append(run)
                run.lines.append(x)
        for r in [r for t in band.topics for r in t.runs] + band.loose:
            while r.lines and r.lines[-1].kind == "text" and not r.lines[-1].text.strip():
                r.lines.pop()
        if band.topics or band.loose:
            out.append(band)
    return Grouped(task_id, "topic", out)


def grouped(model: Model, task_id: str, group: str) -> Grouped:
    """All notes By meeting or By topic."""
    return by_topic(model, task_id) if group == "topic" else occasions(model, task_id)


# ---- their places, for the HTML's anchors and the outline (decision 713) ----
def band_anchor(task: str) -> str:
    return f"band:{task}"


def occasion_anchor(task: str, n: int) -> str:
    return f"occ:{task}:{n}"


def topic_anchor(task: str, n: int) -> str:
    return f"topic:{task}:{n}"


def loose_anchor(task: str) -> str:
    return f"loose:{task}"


@dataclass(frozen=True)
class Entry:
    """A row of the outline (decision 713): where it goes (("band", task), whose click folds the band, or ("anchor",
    name)), its level, its words, how many runs (a topic's; None for none), and whether it reads in grey."""

    target: tuple[str, str]
    level: int
    words: str
    count: int | None = None
    quiet: bool = False


def runs_words(n: int) -> str:
    return f"{n} run{'s' if n != 1 else ''}"


def occasion_words(o: Occasion, today: date) -> str:
    """An occasion as a line says it: "Cooling tower weekly 10 Nov · Tue 10 Nov", "Notes · Thu 5 Nov"."""
    return f"{o.label} · {short_day(o.day, today)}"


def outline(model: Model, g: Grouped, today: date, folded: set[str] | frozenset[str] = frozenset()) -> list[Entry]:
    """The outline of a grouping (decision 713): each band's task, then (unless its band is folded) its occasions, or its
    topics indented by level with how many runs each has, and its lines under no topic heading."""
    out: list[Entry] = []
    for band in g.bands:
        out.append(Entry(("band", band.task), 1, model.task(band.task).title))
        if band.task in folded:
            continue
        if g.group == "meeting":
            for n, (o, _blocks) in enumerate(band.occasions):
                out.append(Entry(("anchor", occasion_anchor(band.task, n)), 2, o.label if o.meeting else occasion_words(o, today),
                                 quiet=not o.meeting))
            continue
        for n, (t, level) in enumerate(band.ordered()):
            out.append(Entry(("anchor", topic_anchor(band.task, n)), level + 1, t.words, band.runs_in(t)))
        if band.loose:
            out.append(Entry(("anchor", loose_anchor(band.task)), 2, LOOSE, len(band.loose), quiet=True))
    return out
