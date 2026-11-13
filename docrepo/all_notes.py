"""All notes (release 5.140; the design workspace's ``docs/mods/notes-consolidation-plan.md``, decisions 602 to 606 and
609, the owner's voice memo of 2026-11-12): a task's notes page and the page of every task under it, read as one page.

**What's in it** (decision 602): the task and every live task under it, at any depth (the With subtasks scope), each
page cut into its blocks: a caption and the lines under it, or lines a day heading heads with no caption. It's read
only: every word stays on its own page, where it's written (decision 605).

**The order** (decision 603): by day, oldest first, as a page is, and within a day by the time each block came in; a
block with no caption of its own (typed on the page) keeps its place after the block before it on its page.

**A meeting reads as it was said** (decision 604). A meeting's notes block (its caption's capture is the meeting's
notes, ``item == "notes"``) holds a task line for each follow-up it made (R4b, release 5.83); here each task line opens
into the block the follow-up's own page holds from those notes, its bullet tree (5.120), wherever that page is. So a
block that came from notes whose block is in view (an item's: a follow-up, a note, an update or a decision, by its
``from_notes``) isn't shown again on its own: the follow-up's is in its task line's place, and a note's, update's or
decision's words are in the meeting's own lines already (release 5.8 copies a ``#task`` section, decision 105), which
the page marks "also on its page".

**Speed** (decision 609): only the pages the model already holds are read, never the captures' files, and only the
last ``WEEKS`` weeks of days are shown until more are asked for.

Nothing here touches Qt; ``detail.Pages.all_notes`` draws it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from docrepo import notes_page
from docrepo.dates import to_date
from docrepo.model import Model

#: How many weeks of days All notes shows at first, and each Show earlier adds (decision 609).
WEEKS = 8
#: The kinds of item a meeting's notes make, whose blocks show in the meeting's place.
ITEMS = ("task", "note", "update", "decision")


@dataclass
class Block:
    """One block of a page: the page it's on, the day heading it's under, when it came in (``at``, "HH:MM", for the
    order within a day), its place on its page, the capture its caption names (None for lines typed on the page), the
    caption's words after the day and time (``label``) and its time ("10:00 am"), and its lines."""

    page: str
    day: date
    at: str
    order: int
    capture: str | None = None
    label: str = ""
    time: str = ""
    lines: list[notes_page.Line] = field(default_factory=list)


@dataclass
class AllNotes:
    """A task's All notes: its days, each with its blocks in order; the pages with something in it, the task's first and
    the rest in the tree's order; the first day shown; whether there are earlier days; and the page it's narrowed to."""

    task: str
    days: list[tuple[date, list[Block]]]
    pages: list[str]
    since: date | None = None
    earlier: bool = False
    only: str = ""

    def blocks(self) -> list[Block]:
        return [b for _d, bs in self.days for b in bs]


def blocks_of(model: Model, task_id: str) -> list[Block]:
    """A task's page cut into blocks (decision 603). Lines before the page's first day heading are under the day the
    task was made."""
    t = model.tasks.get(task_id)
    if t is None:
        return []
    day = to_date((t.created or "")[:10]) or date.min
    out: list[Block] = []
    cur: Block | None = None
    for x in notes_page.lines_of(model.pages.get(task_id, "")):
        if x.kind == "heading" and (d := notes_page.day_of(x.text)):
            day, cur = d, None
            continue
        if x.kind == "caption":
            parts = x.text.split(" · ", 2)
            cur = Block(task_id, day, "", len(out), x.ref, parts[2] if len(parts) == 3 else x.text, parts[1] if len(parts) == 3 else "")
            out.append(cur)
            continue
        if cur is None:
            if x.kind == "text" and not x.text.strip():
                continue
            cur = Block(task_id, day, "", len(out))
            out.append(cur)
        cur.lines.append(x)
    kept: list[Block] = []
    for b in out:
        while b.lines and b.lines[-1].kind == "text" and not b.lines[-1].text.strip():
            b.lines.pop()
        if not b.lines and b.capture is None:
            continue
        c = model.captures.get(b.capture or "")
        before = kept[-1].at if kept and kept[-1].day == b.day else "00:00"
        b.at = c.saved[11:16] if c is not None and c.saved[:10] == b.day.isoformat() else before
        kept.append(b)
    return kept


def notes_in_view(model: Model, blocks: list[Block]) -> set[str]:
    """The meetings' notes captures whose blocks are among these."""
    return {b.capture for b in blocks if b.capture and (c := model.captures.get(b.capture)) is not None and c.item == "notes"}


def shown_in_meeting(model: Model, b: Block, notes: set[str]) -> bool:
    """Whether a block is an item's from notes in view, so it shows in the meeting's place instead (decision 604)."""
    c = model.captures.get(b.capture or "")
    return c is not None and c.item in ITEMS and c.from_notes in notes


def compose(model: Model, task_id: str, weeks: int | None = WEEKS, only: str = "") -> AllNotes:
    """A task's All notes: its pages' blocks by day, the last ``weeks`` weeks of days (all of them with None), narrowed
    to one page with ``only`` (the outline's Pages, decision 603)."""
    scope = [x for x in model.scope_ids(task_id, "descendants") if x in model.tasks and not model.tasks[x].discarded]
    rank = {x: i for i, x in enumerate(scope)}
    blocks = [b for x in scope for b in blocks_of(model, x)]
    notes = notes_in_view(model, blocks)
    kept = [b for b in blocks if b.lines and not shown_in_meeting(model, b, notes)]  # a caption alone says nothing here
    pages = sorted({b.page for b in kept}, key=lambda x: rank[x])
    only = only if only in pages else ""
    shown = [b for b in kept if not only or b.page == only]
    shown.sort(key=lambda b: (b.day, b.at, rank[b.page], b.order))
    since, earlier = None, False
    if weeks is not None and shown:
        since = shown[-1].day - timedelta(days=7 * weeks)
        earlier = any(b.day < since for b in shown)
        shown = [b for b in shown if b.day >= since]
    days: list[tuple[date, list[Block]]] = []
    for b in shown:
        if days and days[-1][0] == b.day:
            days[-1][1].append(b)
        else:
            days.append((b.day, [b]))
    return AllNotes(task_id, days, pages, since if earlier else None, earlier, only)


def follow_up_block(model: Model, notes_id: str, task_ref: str, cache: dict[str, list[Block]] | None = None) -> Block | None:
    """The block a follow-up's page holds from the notes that made it: what its task line opens into (decision 604)."""
    item = next((c.id for c in model.captures.values()
                 if c.from_notes == notes_id and c.item == "task" and c.created_task == task_ref and not c.discarded), None)
    if item is None:
        return None
    cache = {} if cache is None else cache
    if task_ref not in cache:
        cache[task_ref] = blocks_of(model, task_ref)
    return next((b for b in cache[task_ref] if b.capture == item), None)


def copied_to(model: Model, notes_id: str) -> dict[str, str]:
    """The tasks a meeting's notes put notes, updates or decisions on, by their ``#`` heading's words in lowercase
    ("#structural survey of the fan deck"): the lines release 5.8 copies, marked "also on its page" (decision 604)."""
    out: dict[str, str] = {}
    for c in model.captures.values():
        if c.from_notes == notes_id and c.item in ("note", "update", "decision") and not c.discarded and c.task in model.tasks:
            out[f"#{model.tasks[c.task].title}".casefold()] = c.task
    return out


def has_more(model: Model, task_id: str) -> bool:
    """Whether All notes would show more than the page itself: a task under it, or a task line on its page (decision 602)."""
    if any(x in model.tasks and not model.tasks[x].discarded for x in model.descendants_of(task_id)):
        return True
    return any(x.kind == "task" for x in notes_page.lines_of(model.pages.get(task_id, "")))
