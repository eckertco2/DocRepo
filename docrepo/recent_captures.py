"""Recent captures (release 5.158, the design workspace's ``docs/mods/recent-captures-plan.md``, decisions 722 to 727): the
last captures saved, newest first, each with the notes page it opens on, for the Capture wheel's popup
(``docrepo/ui/recent_captures.py``).

A saved capture is never opened again in the capture window (decision 722). Its words are worked on where they already live,
its block on a notes page, so nothing its save did runs again and its ``capture.md`` stays as it was written. The list is
only a way there: it reads the records and changes nothing.

- **What it lists** (decision 724): the last ``LIMIT`` captures saved, newest first, of every capture type: notes, meeting
  notes, an email's capture, a T-mail's sent copy, a new task's or an update's. A discarded capture is left out, and so is a
  capture that's part of another (``listed``): an item made from a capture's notes, which its notes capture stands for, and
  a picture or file made on a notes page, which is on the page already. Typing narrows it by title, across every capture,
  still newest first and still at most ``LIMIT``.
- **Where it opens** (decisions 725 and 726, ``page_of``): the notes page holding its block, found as Edit capture finds it;
  with none, its own capture page.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from docrepo import items, notes_page
from docrepo.dates import to_date
from docrepo.model import Capture, Model
from docrepo.views import since_text

#: How many rows the list shows, before and after typing (decision 724).
LIMIT = 10
#: What each kind of capture is called on its row, and in its tooltip.
KIND_WORDS = {"meeting": "Meeting notes", "t_mail": "T-mail sent", "email": "Email", "new_task": "New task", "update": "Update",
              "note": "Note"}
#: A row's grey words when its capture is on no notes page: unfiled; a note put on an agenda with no task; or filed, with its
#: block taken off the page.
UNFILED, ON_AGENDA, OFF_PAGE = "Unfiled", "On an agenda", "Not on a notes page"


@dataclass(frozen=True)
class RecentRow:
    """One row: the capture, its title, its kind (a key of ``KIND_WORDS``), the task whose notes page holds its block (None
    when no page does), the words saying where it opens (that task's title, or ``UNFILED``, ``ON_AGENDA`` or ``OFF_PAGE``)
    and when it was saved, as the browse tool's rows say it."""

    id: str
    title: str
    kind: str
    page: str | None
    where: str
    when: str

    @property
    def kind_words(self) -> str:
        return KIND_WORDS[self.kind]


def listed(c: Capture) -> bool:
    """Whether a capture may be listed: not discarded, and not a part of another capture. An item made from a capture's notes
    (``from_notes``, release 5.8) is one of its notes' lines, so the notes capture is listed for it; a meeting's ten
    follow-ups would otherwise fill the list. A picture pasted or a file dropped on a notes page (``page_made``, release
    5.27) is on that page already."""
    return not c.discarded and not c.from_notes and not c.page_made


def sent_copies(m: Model) -> set[str]:
    """The captures that are a T-mail's sent copy (release 5.123)."""
    return {t.capture for t in m.t_mails if t.capture}


def kind_of(c: Capture, t_mail_copies: Iterable[str] = ()) -> str:
    """What a capture is, for its row's icon and words: meeting notes first, then a T-mail's sent copy, an email's capture,
    a new task's, an update's, and otherwise a note."""
    if c.item == "notes":
        return "meeting"
    if c.id in t_mail_copies:
        return "t_mail"
    if c.source == "outlook_email" or c.emails:
        return "email"
    if c.created_task or c.has("new_task"):
        return "new_task"
    if c.has("update"):
        return "update"
    return "note"


def page_of(m: Model, c: Capture) -> str | None:
    """The task whose notes page holds the capture's block (decision 725): the first of its tasks, in ``capture_tasks``
    order (the task it was filed on first), whose page has its caption, as Edit capture finds it. A meeting's notes are on
    the meeting's page, where their block is. A block with no caption (release 5.83), only its file lines, is found by those:
    the first page holding every one of them. None when no page holds it: an unfiled capture, or one whose block was taken
    off its page (decision 726)."""
    tasks = [t for t in m.capture_tasks(c) if t in m.tasks]
    pages = {t: m.pages.get(t, "") for t in tasks}
    for t in tasks:
        if c.id in notes_page.capture_ids(pages[t]):
            return t
    docs = set(c.document_ids)
    if docs:
        for t in tasks:
            if docs <= notes_page.document_ids(pages[t]):
                return t
    return None


def when_text(saved: str, today: date) -> str:
    """When a capture was saved, in the browse tool's short form (decision 724): the time today ("9:40"), the weekday within
    the past six days ("Mon"), else the date ("12 Nov", with its year when it isn't this year's)."""
    if to_date(saved) == today:
        return f"{int(saved[11:13])}:{saved[14:16]}"
    return since_text(saved, today)


def newest_first(m: Model) -> list[Capture]:
    """Every capture that may be listed, the newest saved first; captures saved in the same second, the last made first."""
    return sorted((c for c in m.captures.values() if listed(c)), key=lambda c: (c.saved, c.id), reverse=True)


def title_of(c: Capture, kind: str) -> str:
    """The row's title: the capture's, or its kind's words and ID when it has none."""
    return c.title.strip() or f"{KIND_WORDS[kind]} {c.id}"


def row_of(m: Model, c: Capture, today: date, t_mail_copies: Iterable[str] = ()) -> RecentRow:
    kind = kind_of(c, t_mail_copies)
    page = page_of(m, c)
    if page is not None:
        where = m.task(page).title
    elif m.is_unfiled(c):
        where = UNFILED
    elif not m.capture_tasks(c):  # a note on an agenda, with no task (release 5.6)
        where = ON_AGENDA
    else:
        where = OFF_PAGE
    return RecentRow(c.id, title_of(c, kind), kind, page, where, when_text(c.saved, today))


def recent_rows(m: Model, today: date, query: str = "", limit: int = LIMIT) -> list[RecentRow]:
    """The rows for what's typed (decision 724): with nothing typed, the last ``limit`` captures saved, newest first; typed
    words narrow them by title across every capture, as the `#` list matches a task's name (each word starts a word of the
    title, or the capture's ID), still newest first and still at most ``limit``."""
    copies = sent_copies(m)
    captures = newest_first(m)
    typed = query.strip()
    if typed:
        found = set(items.task_matches(typed, [(c.id, title_of(c, kind_of(c, copies))) for c in captures], lambda _: ()))
        captures = [c for c in captures if c.id in found]
    return [row_of(m, c, today, copies) for c in captures[:limit]]
