"""A task's notes page (release 5.25; the notes page plan in the design workspace, decisions 95 to 120).

Each task has one page, where its notes are read, written and edited. It's kept in docs.db (``task_pages``) as markup,
one line a block, and printed into Task.md. Its lines are DocRepo's markup (``docrepo.markup``: text with its marks, and
list items) and three more kinds:

- a heading: ``# ``, ``## `` or ``### `` and its text, at levels 1 to 3 (decision 118). Any text will do; one that
  reads as a date ("Thu 8 Oct 2026") is a day heading, which new captures can go under (decision 119);
- a caption: a line that's one link to a capture, ``[Thu 8 Oct 2026 · 10:42 am · Note](capture:C000101)``. It starts
  the capture's block and dates it (decisions 109 and 120);
- a file line: a line that's one link to a document, ``[File: Pump spec.docx, the vendor's datasheet](document:D000012)``
  (decision 96).
- since release 5.143 (the notes consolidation plan's decisions 613 and 614): a **pointer line**, one link to where lines
  of the page went, ``[Fill media order · 2 lines moved there](moved:T000023/M20261113091500)``, and on that page their
  **lead line**, ``[Moved from the notes of Cooling tower kickoff · Tue 3 Nov](from:T000021/M20261113091500)``, the two
  paired by the move's key; a meeting's ``#task`` section points to its item's capture, ``(moved:T000022/C000033)``;
- since release 5.27 (decisions 124 to 128): a **picture**, a list item that's one picture of a document,
  ``- ![Picture 2026-10-27 1042.png](document:D000031)``, and an **attachment**, a list item that's one link to a
  document, ``- [File: Pump curve.pdf](document:D000032)``, each with its description as the list item under it; and a
  **table**, Markdown's rows (``| Part | Qty |``, ``|---|---|``), one line of text a cell, a cell's ``|`` escaped.

A line of text that would read as one of them starts with a backslash (``\\#``, ``\\[``, ``\\|``). A link's text
escapes ``]`` and ``\\`` with a backslash.

Captures add their blocks when they're saved or filed (``add_capture``), each at the end of the page, or under the
heading for its day when the task uses day headings, in date order (decisions 97, 113 and 119). Discarding a capture
takes its block off again if it hasn't been edited there (decision 106). The owner's edits come from the browse tool
(``put``). Each change keeps the page as it stood at the end of that day (``task_page_versions``, decision 103).
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from docrepo import items, markup
from docrepo.dates import long_date, stamp, to_date
from docrepo.db import transaction
from docrepo.model import Capture, Model
from docrepo.text import is_file_line

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAY = re.compile(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})")
HEADING = re.compile(r"^(#{1,3}) (.*)$")
LINK = re.compile(r"^\[((?:[^\]\\]|\\.)*)\]\((capture|document|task|moved|from):([A-Z]\d+(?:/[A-Z][0-9-]+)?)\)$")
_LINK_KINDS = {"capture": "caption", "document": "file", "task": "task", "moved": "pointer", "from": "lead"}
#: A pointer's or a lead line's ref: the task, then the move's key ("M" and when, or a meeting item's capture).
_PAIR = re.compile(r"^(T\d+)/([A-Z][0-9-]+)$")
#: A picture or an attachment on the page (release 5.27): a list item that's one picture of, or link to, a document.
ITEM = re.compile(r"^((?:  )*)- (!?)\[((?:[^\]\\]|\\.)*)\]\(document:(D\d+)\)$")
#: The kinds of file a page shows as a picture.
PICTURES = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
_UNESCAPE = re.compile(r"\\([\]\\])")
#: A line that's only stored # tasks (release 5.32): ``#[Installation](T000008)``, with a colon or a full stop at most.
_OWN_HEADING = re.compile(r"(?:#\[[^\]\n]+\]\(T\d+\)[\s:.]*)+")
_TASK_REF = re.compile(r"\]\((T\d+)\)")


@dataclass(frozen=True)
class Line:
    """One line of a page, read: a "heading", a "caption", a "file" line, a "task" line (one link to a task made from
    the notes, release 5.83), a "pointer" or a "lead" line (release 5.143), a "picture", an "attachment", a table's "row"
    or a line of "text"."""

    kind: str
    text: str        # a heading's or a link's text, in words; a text line's markup; a row as it's kept
    level: int = 0   # a heading's level, 1 to 3; a picture's or attachment's list level, from 1
    ref: str = ""    # a caption's capture, a task line's task, or a file line's, picture's or attachment's document


# ---- reading and writing lines ----
def read_line(line: str) -> Line:
    m = HEADING.match(line)
    if m:
        return Line("heading", m.group(2), len(m.group(1)))
    m = LINK.match(line)
    if m:
        return Line(_LINK_KINDS[m.group(2)], _UNESCAPE.sub(r"\1", m.group(1)), ref=m.group(3))
    m = ITEM.match(line)
    if m:
        return Line("picture" if m.group(2) else "attachment", _UNESCAPE.sub(r"\1", m.group(3)), len(m.group(1)) // 2 + 1, m.group(4))
    if line.startswith("|"):
        return Line("row", line)
    if line.startswith(("\\#", "\\[", "\\|")):
        line = line[1:]
    return Line("text", line)


def lines_of(page: str) -> list[Line]:
    return [read_line(line) for line in page.split("\n")] if page else []


def heading_line(text: str, level: int) -> str:
    return f"{'#' * max(1, min(level, 3))} {text}"


def _link_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("]", "\\]").replace("\n", " ")


def caption_line(text: str, capture_id: str) -> str:
    return f"[{_link_text(text)}](capture:{capture_id})"


def task_line(text: str, task_id: str) -> str:
    """A task made from the notes, as one line on the page they came from (release 5.83, the task pane review's R4b)."""
    return f"[{_link_text(text)}](task:{task_id})"


def task_line_text(model: Model, task_id: str, today: date) -> str:
    """"Task: Rigging plan · Mike Ortiz · due Wed 14 Oct": the task's title, its first lead or assignee, and its due date."""
    t = model.tasks.get(task_id)
    if t is None:
        return f"Task: {task_id}"
    who = next((model.person_name(p) for p in [*t.leads, *t.assignees]), "")
    parts = [f"Task: {t.title}", *([who] if who else []), *([f"due {long_date(to_date(t.due), today)}"] if t.due else [])]
    return " · ".join(parts)


def task_lines(lines: list[str], made: list[tuple[str, list[str]]], model: Model, today: date) -> list[str]:
    """``lines`` with each task made from them (``made``: the task and its item's own page lines) as one task line in
    the item's place, its parameters kept in the item's capture (R4b): a meeting's page lists its follow-ups, not their
    text. An item whose lines aren't found as written is left as it is."""
    out = list(lines)
    for task_id, item in made:
        item = _trim_end(list(item))
        while item and not item[0].strip():
            item = item[1:]
        n = len(item)
        if not n:
            continue
        for i in range(len(out) - n + 1):
            if out[i:i + n] == item:
                out[i:i + n] = [task_line(task_line_text(model, task_id, today), task_id)]
                break
    return out


def pointer_line(text: str, task_id: str, key: str) -> str:
    """Where lines of the page went (release 5.143, decision 613): "Fill media order · 2 lines moved there", one link to
    the task they're on now and the move's key. A meeting's ``#task`` section points the same way (decision 614), its
    key the item's capture."""
    return f"[{_link_text(text)}](moved:{task_id}/{key})"


def lead_line(text: str, task_id: str, key: str) -> str:
    """The line before lines moved onto a page (decision 613): "Moved from the notes of Cooling tower kickoff · Tue 3
    Nov", one link to the page they came from and the move's key."""
    return f"[{_link_text(text)}](from:{task_id}/{key})"


def pair_of(ref: str) -> tuple[str, str] | None:
    """A pointer's or a lead line's (task, key)."""
    m = _PAIR.match(ref)
    return (m.group(1), m.group(2)) if m else None


def moved_block(page: str, key: str) -> tuple[int, int] | None:
    """The lines a move put on a page: its lead line, and the lines after it to the next day heading, caption, lead line
    or pointer line; as (first, end). None when it isn't there."""
    lines = lines_of(page)
    start = next((i for i, x in enumerate(lines) if x.kind == "lead" and (pair_of(x.ref) or ("", ""))[1] == key), None)
    if start is None:
        return None
    end = start + 1
    while end < len(lines) and not (lines[end].kind in ("caption", "lead", "pointer") or (lines[end].kind == "heading" and day_of(lines[end].text))):
        end += 1
    while end > start + 1 and lines[end - 1].kind == "text" and not lines[end - 1].text.strip():
        end -= 1
    return start, end


def pointer_index(page: str, key: str) -> int | None:
    """Where a page's pointer line with this key is."""
    return next((i for i, x in enumerate(lines_of(page)) if x.kind == "pointer" and (pair_of(x.ref) or ("", ""))[1] == key), None)


def section_pointers(lines: list[str], named: list[tuple[str, str, str, list[str]]], model: Model) -> list[str]:
    """Decision 614 (release 5.143): in a meeting's notes, each note, update or decision a ``#task`` made (``named``: its
    capture, its task, its kind and its own page lines) is one pointer line on the meeting's page in its lines' place,
    with the ``#task`` heading line just above it when that names the same task; its words are on the task's page, under
    its caption. Release 5.8 copied them onto both pages. Lines not found as written are left as they are."""
    out = list(lines)
    for capture_id, task_id, kind, item in named:
        item = _trim_end(list(item))
        while item and not item[0].strip():
            item = item[1:]
        n = len(item)
        if not n:
            continue
        title = model.tasks[task_id].title if task_id in model.tasks else task_id
        for i in range(len(out) - n + 1):
            if out[i:i + n] == item:
                first = i - 1 if i > 0 and _plain_words(out[i - 1]) == _plain_words(f"#{title}") else i
                count = sum(1 for x in item if x.strip())
                words = {"decision": "a decision there", "update": "an update there"}.get(kind) or f"{count} line{'s' if count != 1 else ''} there"
                out[first:i + n] = [pointer_line(f"{title} · {words}", task_id, capture_id)]
                break
    return out


def file_line(text: str, document_id: str) -> str:
    return f"[{_link_text(text)}](document:{document_id})"


def item_line(kind: str, text: str, document_id: str, level: int = 1) -> str:
    """A picture's or an attachment's line (release 5.27)."""
    return f"{'  ' * max(0, level - 1)}- {'!' if kind == 'picture' else ''}[{_link_text(text)}](document:{document_id})"


def text_line(line: str) -> str:
    """A line of markup as a page keeps it: one that would read as a heading, a link, a picture or a table's row starts
    with a backslash."""
    return ("\\" + line if HEADING.match(line) or LINK.match(line) or ITEM.match(line) or line.startswith(("\\#", "\\[", "|", "\\|"))
            else line)


# ---- tables (release 5.27, decision 128) ----
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_SEPARATOR = re.compile(r"^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?$")


def is_separator(row: str) -> bool:
    return bool(_SEPARATOR.match(row.strip()))


def cells_of(row: str) -> list[str]:
    """A table row's cells, as markup, a ``\\|`` back to ``|``."""
    inner = row.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(inner)]


def row_line(cells: list[str]) -> str:
    """A table row from its cells' markup, each ``|`` escaped, so the row reads back as the same cells."""
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def separator_line(columns: int) -> str:
    return "|" + "|".join(["---"] * columns) + "|"


def write(lines: list[Line]) -> str:
    out = []
    for x in lines:
        if x.kind == "heading":
            out.append(heading_line(x.text, x.level))
        elif x.kind == "caption":
            out.append(caption_line(x.text, x.ref))
        elif x.kind == "file":
            out.append(file_line(x.text, x.ref))
        elif x.kind in ("pointer", "lead"):
            out.append(f"[{_link_text(x.text)}]({'moved' if x.kind == 'pointer' else 'from'}:{x.ref})")
        elif x.kind in ("picture", "attachment"):
            out.append(item_line(x.kind, x.text, x.ref, x.level))
        elif x.kind == "row":
            out.append(x.text)
        else:
            out.append(text_line(x.text))
    return "\n".join(out)


# ---- days and captions ----
def day_title(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def day_of(text: str) -> date | None:
    """The date a heading's text reads as ("Thu 8 Oct 2026"), if it's a day heading."""
    m = DAY.fullmatch(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(4)), MONTHS.index(m.group(3)) + 1, int(m.group(2)))
    except ValueError:
        return None


def clock(t: datetime) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def caption_label(stories, c: Capture, task_id: str) -> str:
    """What a capture is, on its caption: "Note", "New task", "Update: Due date moved to Fri 23 Oct.", "Email from Tom
    Becker: Re: impeller delivery", "Decision from the notes of Weekly meeting 22 Oct", "Meeting notes"."""
    item = stories.note_item(c, task_id)
    kind, _, did = item.lead.partition(" · ")
    if c.item == "notes":
        return "Meeting notes"
    if c.from_notes:
        what = "New task" if c.item == "task" else kind
        return f"{what} from the notes of {item.from_title}" if item.from_title else what
    if c.created_task == task_id:
        return "New task"
    if kind == "Update":
        did = did.removeprefix("Update: ").replace("New current status.", "").strip()
        return f"Update: {did}" if did else "Update"
    if kind.startswith("Email"):
        about = "; ".join(e.description for e in c.emails if e.description)  # round 7's item 93
        label = f"{kind}: {c.title}" if c.title else kind
        return f"{label} – {about}" if about else label
    return kind


def caption_text(c: Capture, label: str) -> str:
    saved = datetime.fromisoformat(c.saved)
    return f"{day_title(saved.date())} · {clock(saved)} · {label}"


def own_heading(line: str, task_id: str) -> bool:
    """Whether a line of a capture's stored text is a # heading naming only ``task_id``. On that task's own page it says
    nothing, so it's left out (the knowledge base's decision 28, release 5.32); capture.md keeps it."""
    words = markup.to_plain(line).strip()
    return bool(_OWN_HEADING.fullmatch(words)) and set(_TASK_REF.findall(words)) == {task_id}


def capture_markup(c: Capture, content: str | None, title: str = "", own: str | None = None) -> list[str]:
    """A capture's note text as page lines (``note_markup``)."""
    return note_markup(content, c.formatted, title, own)


def note_markup(content: str | None, formatted: bool, title: str = "", own: str | None = None) -> list[str]:
    """Note text, as a capture or the capture window keeps it, as page lines: its names as written (``@Tom Becker``),
    its file and link lines left out (they're file lines on the page), and empty lines at its ends dropped. A new task's
    text that's only its title isn't repeated (decision 115). Its headings are the page's headings, at the level they
    were typed (release 5.28, the mods log round 4's decision 132). On ``own``'s page, a # heading naming only that task
    is left out (release 5.32)."""
    if not content:
        return []
    if own:
        content = "\n".join(line for line in content.split("\n") if not own_heading(line, own))
    content = items.unstore(content)
    text = content if formatted else markup.escape(content)
    lines = [line for line in text.split("\n") if not is_file_line(markup.to_plain(line).strip())]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if title and len(lines) == 1 and re.sub(r"\.\Z", "", markup.to_plain(lines[0]).strip()) == title.strip():
        return []
    return [heading_line(h[1], h[0]) if (h := markup.heading_of(line)) else text_line(markup.text_of(line)) for line in lines]


def _plain_words(line: str) -> str:
    return " ".join(markup.to_plain(line).split()).rstrip(".").casefold()


def captionless(c: Capture, label: str, text: list[str], model: Model) -> bool:
    """Whether a capture's block has no caption (release 5.83, the task pane review's R4): one that was made on the page,
    or one with no words of its own beyond its files, whose caption would only say "File" (or "Note", or "Update"
    with nothing changed), which its day heading and file lines say already. A caption that names an email, a change
    or where an item came from stays."""
    if c.page_made:
        return True
    return not text and bool(c.document_ids) and label in ("File", "Note", "Update")


def has_caption(lines: list[str]) -> bool:
    return any(read_line(x).kind == "caption" for x in lines)


def _same_line(line: str) -> str:
    """A line's words, to find an item's line in its notes: its names as written, without marks, spaces run together."""
    return " ".join(markup.to_plain(items.unstore(line)).split())


def sub_bullet_tree(model: Model, stories, c: Capture, task_id: str, content: str | None) -> tuple[str, bool] | None:
    """Decision 446 (release 5.120): a task made from a sub-bullet in the notes (``c``, the item's capture, on the page of
    ``task_id``, the task it made) has the whole bullet tree its top bullet heads as its notes: the tree as the notes
    have it, and whether that's markup. None for any other capture, or when its first line isn't found as a sub-bullet in
    its notes. The item's capture.md keeps its own lines, so the notes' page still finds them for its task line (R4b)."""
    if not (c.from_notes and c.item == "task" and c.created_task == task_id and content):
        return None
    notes = model.captures.get(c.from_notes)
    first = next((x for x in content.split("\n") if x.strip()), "")
    text = typed_content(notes, stories.content_of(notes.id)) if notes is not None else None
    if not text or items.list_level(first) < 1:
        return None
    lines, key = text.split("\n"), _same_line(first)
    for i, line in enumerate(lines):
        if items.list_level(line) >= 1 and _same_line(line) == key:
            span = items.bullet_tree(lines, i)
            return ("\n".join(lines[span[0]:span[1]]), notes.formatted) if span else None
    return None


def block(model: Model, stories, c: Capture, task_id: str, content: str | None) -> list[str]:
    """A capture's block on a task's page (decisions 96, 114, 115, 120): its caption, its note text in full, and a file
    line for each of its files. ``content`` is its typed text: an email's own text stays with the email. Since release
    5.83 (the task pane review's R4 and R4b): text that only repeats a file's description isn't written, a block with no
    words of its own beyond its files has no caption, and a task made from the notes is one task line where its
    lines were. Since release 5.120 (decision 446), a task made from a sub-bullet in the capture window's notes has its
    whole bullet tree as its block's text on its own page (``sub_bullet_tree``)."""
    tree = sub_bullet_tree(model, stories, c, task_id, content)
    text = (note_markup(tree[0], tree[1], "", task_id) if tree else
            capture_markup(c, content, c.title if c.created_task == task_id else "", task_id))
    docs = [model.documents[d] for d in c.document_ids if d in model.documents]
    descriptions = {_plain_words(d.description) for d in docs if d.description and not made_up(d.description, d.name)}
    words = [w for x in text if (w := _plain_words(x))]
    if words and all(w in descriptions for w in words):
        text = []
    made = [(x.created_task, note_markup(stories.content_of(x.id), x.formatted, "", task_id))
            for x in model.captures.values() if x.from_notes == c.id and x.item == "task" and x.created_task]
    if made:
        text = task_lines(text, made, model, stories.today)
    if c.item == "notes":  # a meeting's #task sections point to their tasks' pages (release 5.143, decision 614)
        named = [(x.id, x.task, x.item, note_markup(stories.content_of(x.id), x.formatted, "", task_id))
                 for x in sorted(model.captures.values(), key=lambda x: x.id)
                 if x.from_notes == c.id and x.item in ("note", "update", "decision") and x.task and x.task != task_id and not x.discarded]
        if named:
            text = section_pointers(text, named, model)
    label = caption_label(stories, c, task_id)
    out = [] if captionless(c, label, text, model) else [caption_line(caption_text(c, label), c.id)]
    out += text
    for d in c.document_ids:
        doc = model.documents.get(d)
        if doc is None:
            continue
        if c.page_made or is_picture(c, doc.name):
            # A picture (or a file put on the page) as a list item, its description under it (decisions 124 to 126);
            # a description DocRepo made up shows as an empty line, to be written.
            kind = "picture" if doc.name.lower().endswith(PICTURES) else "attachment"
            out.append(item_line(kind, doc.name if kind == "picture" else f"File: {doc.name}", d))
            out.append("  - " + ("" if made_up(doc.description, doc.name) else markup.escape_inline(" ".join((doc.description or "").split()))))
        else:
            out.append(file_line(f"File: {doc.name}" + (f", {doc.description}" if doc.description else ""), d))
    return out


def is_picture(c: Capture, name: str) -> bool:
    """A capture's file the page shows as a picture: one of PICTURES, but not an email's (its pictures are mostly
    signatures and logos, so they stay file lines)."""
    return c.source != "outlook_email" and name.lower().endswith(PICTURES)


def made_up(description: str | None, name: str) -> bool:
    """Whether a description is one DocRepo made up (release 5.5's default), not the owner's words."""
    d = (description or "").strip()
    return not d or d == name or any(f" – {how} {kind} – {name}" in d for how in ("Attached", "Pasted")
                                     for kind in ("picture", "document", "link"))


def descriptions(page: str) -> dict[str, str]:
    """The descriptions a page gives its pictures and attachments: the list item under each, as words (release 5.27,
    decision 125). An empty one gives "", for the description DocRepo makes up."""
    lines, out = lines_of(page), {}
    for i, x in enumerate(lines):
        if x.kind in ("picture", "attachment") and x.ref not in out:
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            m = markup.LIST_LINE.match(nxt.text) if nxt is not None and nxt.kind == "text" else None
            if m and len(m.group(1)) // 2 + 1 == x.level + 1:
                out[x.ref] = " ".join(markup.to_plain(nxt.text[m.end():]).split())
            else:
                out[x.ref] = ""
    return out


def document_ids(page: str) -> set[str]:
    """The documents a page shows: its pictures, attachments and file lines."""
    return {x.ref for x in lines_of(page) if x.kind in ("picture", "attachment", "file")}


def typed_content(c: Capture, content: str | None) -> str | None:
    """The capture's own typed text, from its content text: an email's text is the email's, so an email capture has none."""
    return None if c.source == "outlook_email" else content


# ---- placing blocks ----
def _trim_end(raw: list[str]) -> list[str]:
    while raw and not raw[-1].strip():
        raw = raw[:-1]
    return raw


def add_block(page: str, new: list[str], day: date, day_headings: bool) -> str:
    """The page with a block added: at the end, or, with day headings, at the end of its day's lines, or under a new
    heading for its day put in date order among the day headings (decisions 97, 113 and 119). A day's lines run to the
    next day heading, whatever headings of the owner's or the captures' own come between (release 5.28, decision 132)."""
    raw = page.split("\n") if page else []
    if not day_headings:
        return "\n".join(_trim_end(raw) + new)
    lines = [read_line(x) for x in raw]
    days = [(i, d) for i, x in enumerate(lines) if x.kind == "heading" and (d := day_of(x.text))]
    same = next((i for i, d in days if d == day), None)
    if same is not None:
        end = next((i for i, _ in days if i > same), len(raw))
        while end > same + 1 and not raw[end - 1].strip():
            end -= 1
        return "\n".join(raw[:end] + new + raw[end:])
    later = next((i for i, d in days if d > day), None)
    head = [heading_line(day_title(day), 1)]
    if later is None:
        return "\n".join(_trim_end(raw) + head + new)
    return "\n".join(raw[:later] + head + new + raw[later:])


def _same_words(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


@dataclass(frozen=True)
class Landing:
    """Where one of a note's headings went (release 5.94): under the page's last heading, which has its words ("under"),
    or at the page's end under its own heading ("end"), with whether a heading with its words is higher up."""

    words: str
    how: str
    higher_up: bool = False


def place_note(page: str, note: list[str], day: date) -> tuple[str, list[str]]:
    """The page with a note from the capture window on it, which is no capture: ``place_note_where`` without the
    landings. Returns the page and the headings the note went under, in order, for Save's message."""
    out, under, _ = place_note_where(page, note, day)
    return out, under


def place_note_where(page: str, note: list[str], day: date) -> tuple[str, list[str], list[Landing]]:
    """The page with a note from the capture window on it, which is no capture (release 5.69, the notes workspace plan's
    decision 345, with release 5.94's simpler rule, the review of 2026-11-06, F13, taken 2026-11-06). New text goes at
    the end of the page. Each of the note's headings goes under the page's heading with the same words (case and spacing
    aside) only when that heading is the page's last heading; otherwise it goes at the page's end under its own heading,
    at the level it was typed, even when a heading with its words is higher up (the footer says so). The note's lines
    under none of its headings go under the day's heading, at the end of the day's lines, as a capture's block does
    (``add_block``), which is the page's end unless a later day follows. Returns the page, the headings the note went
    under, in order, for Save's message, and where each of its headings went, for the capture window's sentence."""
    loose: list[str] = []
    sections: list[tuple[int, str, list[str]]] = []  # each of the note's headings: its level, its words, its lines
    for x in note:
        line = read_line(x)
        if line.kind == "heading":
            sections.append((line.level, line.text, []))
        elif sections:
            sections[-1][2].append(x)
        else:
            loose.append(x)

    def trimmed(lines: list[str]) -> list[str]:
        lines = _trim_end(lines)
        while lines and not lines[0].strip():
            lines = lines[1:]
        return lines

    out, under, landed = page, [], []
    loose = trimmed(loose)
    if loose:
        out = add_block(out, loose, day, True)
        under.append(day_title(day))
    for level, words, lines in sections:
        lines = trimmed(lines)
        raw = out.split("\n") if out else []
        read = [read_line(x) for x in raw]
        heads = [i for i, x in enumerate(read) if x.kind == "heading"]
        last = heads[-1] if heads else None
        if last is not None and _same_words(read[last].text, words):  # the page's last heading: under it, at the page's end
            end = len(raw)
            while end > last + 1 and not raw[end - 1].strip():
                end -= 1
            out = "\n".join(raw[:end] + lines + raw[end:])
            under.append(read[last].text)
            landed.append(Landing(read[last].text, "under"))
            continue
        higher = any(_same_words(read[i].text, words) for i in heads)
        out = "\n".join(_trim_end(raw) + [heading_line(words, level)] + lines)
        under.append(words)
        landed.append(Landing(words, "end", higher))
    return out, list(dict.fromkeys(under)), landed


def _file_run(lines: list[Line], start: int, refs: set[str]) -> int:
    """The end of a run of file, picture and attachment lines of ``refs`` from ``start``, each with its description
    list item under it."""
    end = start
    while end < len(lines):
        x = lines[end]
        if x.kind in ("file", "picture", "attachment") and x.ref in refs:
            end += 1
            if end < len(lines) and lines[end].kind == "text" and markup.LIST_LINE.match(lines[end].text) and x.kind != "file":
                end += 1  # a picture's or attachment's description
            continue
        break
    return end


def find_block(page: str, capture_id: str, refs: Sequence[str] = ()) -> tuple[int, int] | None:
    """Where a capture's block is: from its caption to the next caption or heading, or, for a capture with no caption
    (release 5.83), its run of file lines for ``refs``, its documents."""
    lines = lines_of(page)
    start = next((i for i, x in enumerate(lines) if x.kind == "caption" and x.ref == capture_id), None)
    if start is None:
        wanted = set(refs)
        start = next((i for i, x in enumerate(lines) if x.kind in ("file", "picture", "attachment") and x.ref in wanted), None)
        return (start, _file_run(lines, start, wanted)) if start is not None else None
    end = start + 1
    while end < len(lines) and lines[end].kind not in ("caption", "heading"):
        end += 1
    return start, end


def remove_block(page: str, capture_id: str, as_added: list[str], force: bool = False, refs: Sequence[str] = ()) -> tuple[str, str]:
    """The page without a capture's block, and what happened: "removed", "edited" (left on the page, as the owner
    changed it there, unless ``force``) or "absent" (decision 106). A day heading left with nothing under it goes too."""
    span = find_block(page, capture_id, refs)
    if span is None:
        return page, "absent"
    raw = page.split("\n")
    start, end = span
    here = _trim_end(raw[start:end])
    if not force and here != _trim_end(list(as_added)):
        return page, "edited"
    out = raw[:start] + raw[end:]
    if start > 0:
        prev = read_line(out[start - 1])
        nxt = read_line(out[start]) if start < len(out) else None
        if prev.kind == "heading" and day_of(prev.text) and (nxt is None or (nxt.kind == "heading" and nxt.level <= prev.level)):
            out = out[:start - 1] + out[start:]
    return "\n".join(out), "removed"


def merge(base: str, ours: str, theirs: str, day_headings: bool) -> str:
    """Two writers (the plan's "Two writers at once"): the owner's unsaved page (``ours``) with what changed in docs.db
    since it was loaded (``base`` to ``theirs``). A capture's block added there is added here, in its place; one taken
    off there (a discard) comes off here too, unless the owner has changed it."""
    known = set(capture_ids(base))
    ours_ids = set(capture_ids(ours))
    out = ours
    raw = theirs.split("\n")
    covered: set[int] = set()
    for cid in capture_ids(theirs):
        start, end = find_block(theirs, cid)
        covered.update(range(start, end))
        if cid in known or cid in ours_ids:
            continue
        when = day_of(read_line(raw[start]).text.split(" · ")[0]) or date.today()
        out = add_block(out, _trim_end(raw[start:end]), when, day_headings)
    # A block with no caption (release 5.83): its file lines, new there, come in under the day they sit under there.
    new_docs = document_ids(theirs) - document_ids(base) - document_ids(ours)
    lines = lines_of(theirs)
    i, day = 0, date.today()
    while i < len(lines):
        x = lines[i]
        if x.kind == "heading" and (d := day_of(x.text)):
            day = d
        if i not in covered and x.kind in ("file", "picture", "attachment") and x.ref in new_docs:
            end = _file_run(lines, i, new_docs)
            out = add_block(out, _trim_end(raw[i:end]), day, day_headings)
            i = end
            continue
        i += 1
    base_raw = base.split("\n")
    for cid in known - set(capture_ids(theirs)):
        span = find_block(base, cid)
        if span:
            out = remove_block(out, cid, base_raw[span[0]:span[1]])[0]
    return out


def on_page(model: Model, task_id: str, page: str, stories=None) -> set[str]:
    """The captures whose blocks are on a task's page: those with a caption there, those made on the page (release
    5.27) whose picture or attachment is there, and, given ``stories`` to read their text, those whose block has no
    caption (release 5.83) and whose file lines are there."""
    docs = document_ids(page)
    captions = set(capture_ids(page))
    made = set()
    for c in model.notes_of(task_id):
        if c.id in captions or not set(c.document_ids) & docs:
            continue
        if c.page_made:
            made.add(c.id)
        elif stories is not None:
            if not has_caption(block(model, stories, c, task_id, typed_content(c, stories.content_of(c.id)))):
                made.add(c.id)
        elif set(c.document_ids) <= docs:  # without its text to read (Task.md): every file line there, and no caption
            made.add(c.id)
    return captions | made


def capture_ids(page: str) -> list[str]:
    return [x.ref for x in lines_of(page) if x.kind == "caption"]


def words(page: str) -> str:
    """The page in words, for search: headings, captions and file lines as their text, and markup without its marks.
    Pointer and lead lines (release 5.143) aren't words of the page: they say where its lines went, or came from, so the
    moved words are found once, on their page."""
    out = []
    for x in lines_of(page):
        if x.kind in ("pointer", "lead"):
            continue
        if x.kind == "row":
            if not is_separator(x.text):
                out.append(" ".join(markup.to_plain(c) for c in cells_of(x.text)))
        else:
            out.append(markup.to_plain(x.text) if x.kind == "text" else x.text)
    return "\n".join(out)


def task_md(page: str, capture_link: Callable[[str], str | None], document_link: Callable[[str], str | None] = lambda _: None,
            task_link: Callable[[str], str | None] = lambda _: None) -> list[str]:
    """The page as Task.md prints it, under "## Notes": headings two levels down, captions as links to the capture's
    capture.md, task lines as links to the task's Task.md (``task_link``), pictures as pictures and attachments as
    links to their files (``document_link``), and the rest as it's kept (its markup, and a table's rows, read as
    Markdown)."""
    out = []
    for x in lines_of(page):
        if x.kind == "heading":
            out.append(f"{'#' * (x.level + 2)} {x.text}")
        elif x.kind == "caption":
            target = capture_link(x.ref)
            text = markup.escape_inline(x.text).replace("[", "\\[").replace("]", "\\]")
            out.append(f"_[{text}]({target})_" if target else f"_{text}_")
        elif x.kind == "task":
            target = task_link(x.ref)
            text = markup.escape_inline(x.text).replace("[", "\\[").replace("]", "\\]")
            out.append(f"- [{text}]({target})" if target else f"- {text}")
        elif x.kind in ("pointer", "lead"):  # release 5.143: a link to the page the lines went to, or came from
            pair = pair_of(x.ref)
            target = task_link(pair[0]) if pair else None
            text = markup.escape_inline(x.text).replace("[", "\\[").replace("]", "\\]")
            arrow = "↪ " if x.kind == "pointer" else ""
            out.append((f"{arrow}[{text}]({target})" if target else f"{arrow}{text}") if x.kind == "pointer"
                       else (f"_[{text}]({target})_" if target else f"_{text}_"))
        elif x.kind == "file":
            out.append(f"- {markup.escape_inline(x.text)}")
        elif x.kind in ("picture", "attachment"):
            target, text = document_link(x.ref), x.text.replace("[", "\\[").replace("]", "\\]")
            indent = "  " * (x.level - 1)
            if target:
                out.append(f"{indent}- {'!' if x.kind == 'picture' else ''}[{text}]({target})")
            else:
                out.append(f"{indent}- {text}")
        elif x.kind == "row":
            out.append(x.text)
        else:
            out.append(text_line(x.text))
    while out and not out[-1].strip():
        out.pop()
    # Markdown runs lines of text together; each line of the page is its own paragraph or list item.
    spaced: list[str] = []
    for line in out:
        together = (markup.LIST_LINE.match(line) and markup.LIST_LINE.match(spaced[-1] if spaced else "")) or (
            line.startswith("|") and spaced and spaced[-1].startswith("|"))
        if spaced and line and spaced[-1] and not together:
            spaced.append("")
        spaced.append(line)
    # The Checklist summary (release 5.26, decision 121): every checklist line on the page, open ones first.
    items = checklist(page)
    if items:
        done = sum(1 for x in items if x.done)
        summary = [f"**Checklist** · {done} of {len(items)} done", ""]
        summary += [f"- [{'x' if x.done else ' '}] {x.text}" for x in sorted(items, key=lambda x: x.done)]
        spaced = summary + ([""] + spaced if spaced else [])
    return spaced


@dataclass(frozen=True)
class CheckLine:
    """A checklist line on a page (release 5.26): where it is, whether it's ticked, its words as markup, its level, and
    the heading it sits under ("" for none)."""

    index: int
    done: bool
    text: str
    level: int
    heading: str


def checklist(page: str) -> list[CheckLine]:
    """Every checklist line on the page, in page order: what the Checklist summary lists (decision 121)."""
    out, heading = [], ""
    for i, x in enumerate(lines_of(page)):
        if x.kind == "heading":
            heading = x.text
        elif x.kind == "text" and (done := markup.check_of(x.text)) is not None:
            m = markup.LIST_LINE.match(x.text)
            c = markup.CHECK.match(x.text, m.end())
            out.append(CheckLine(i, done, x.text[c.end():], len(m.group(1)) // 2 + 1, heading))
    return out


# ---- docs.db ----
def get(conn: sqlite3.Connection, task_id: str) -> str:
    row = conn.execute("SELECT body FROM task_pages WHERE task = ?", (task_id,)).fetchone()
    return row["body"] if row else ""


def put(conn: sqlite3.Connection, task_id: str, body: str, at: datetime, by_owner: bool = False) -> bool:
    """Keep the page, and the day's version of it (decision 103). Says whether it changed."""
    with transaction(conn):
        if get(conn, task_id) == body and conn.execute("SELECT 1 FROM task_pages WHERE task = ?", (task_id,)).fetchone():
            return False
        conn.execute("INSERT INTO task_pages (task, body, updated) VALUES (?, ?, ?) "
                     "ON CONFLICT(task) DO UPDATE SET body = excluded.body, updated = excluded.updated", (task_id, body, stamp(at)))
        conn.execute("INSERT INTO task_page_versions (task, day, body, by_owner, at) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT(task, day) DO UPDATE SET body = excluded.body, by_owner = max(by_owner, excluded.by_owner), "
                     "at = CASE WHEN excluded.by_owner THEN excluded.at ELSE at END",
                     (task_id, at.date().isoformat(), body, int(by_owner), stamp(at)))
    return True


def versions(conn: sqlite3.Connection, task_id: str) -> list[tuple[str, bool]]:
    """The days the page was kept as it stood at their end, newest first, and whether the owner edited it that day."""
    return [(r["day"], bool(r["by_owner"])) for r in conn.execute(
        "SELECT day, by_owner FROM task_page_versions WHERE task = ? ORDER BY day DESC", (task_id,))]


def version(conn: sqlite3.Connection, task_id: str, day: str) -> str | None:
    row = conn.execute("SELECT body FROM task_page_versions WHERE task = ? AND day = ?", (task_id, day)).fetchone()
    return row["body"] if row else None


def add_capture(conn: sqlite3.Connection, model: Model, stories, capture_id: str, at: datetime, typed: str | None = None,
                tasks: list[str] | None = None) -> list[str]:
    """Add a capture's block to the page of each task it belongs to (or ``tasks``), unless it's there already. ``typed``
    is its typed text when it's known (at saving); else its content text is read. Returns the tasks whose pages changed."""
    c = model.captures[capture_id]
    if c.discarded:
        return []
    content = typed if typed is not None else typed_content(c, stories.content_of(c.id))
    changed = []
    for task_id in tasks if tasks is not None else model.capture_tasks(c):
        t = model.tasks.get(task_id)
        if t is None or t.discarded:
            continue
        page = get(conn, task_id)
        lines = block(model, stories, c, task_id, content)
        if capture_id in capture_ids(page) or (not has_caption(lines) and set(c.document_ids) & document_ids(page)):
            continue
        new = add_block(page, lines, datetime.fromisoformat(c.saved).date(), model.uses_day_headings(task_id))
        if put(conn, task_id, new, at):
            changed.append(task_id)
    return changed


def remove_capture(conn: sqlite3.Connection, model: Model, stories, capture_id: str, at: datetime,
                   force: bool = False) -> dict[str, str]:
    """Take a capture's block off each of its tasks' pages, as it was added (decision 106). Returns what happened on
    each page: "removed", "edited" (left, as the owner changed it there, unless ``force``) or "absent"."""
    c = model.captures[capture_id]
    content = typed_content(c, stories.content_of(c.id))
    out = {}
    for task_id in model.capture_tasks(c):
        if task_id not in model.tasks:
            continue
        page = get(conn, task_id)
        new, what = remove_block(page, capture_id, block(model, stories, c, task_id, content), force, c.document_ids)
        if what == "removed":
            put(conn, task_id, new, at)
        out[task_id] = what
    return out


def edited_blocks(model: Model, stories, capture_id: str) -> list[str]:
    """The tasks whose page has the capture's block as the owner changed it: discarding asks about those (106)."""
    c = model.captures[capture_id]
    content = typed_content(c, stories.content_of(c.id))
    out = []
    for task_id in model.capture_tasks(c):
        page = model.pages.get(task_id, "")
        if remove_block(page, capture_id, block(model, stories, c, task_id, content), refs=c.document_ids)[1] == "edited":
            out.append(task_id)
    return out


def build(model: Model, stories, task_id: str) -> str:
    """A task's first page, from its raw text log, oldest first (decision 107)."""
    page = ""
    day_headings = model.uses_day_headings(task_id)
    for c in sorted(model.notes_of(task_id), key=lambda k: k.saved):
        content = typed_content(c, stories.content_of(c.id))
        page = add_block(page, block(model, stories, c, task_id, content), datetime.fromisoformat(c.saved).date(), day_headings)
    return page


#: In app_state once every task's first page is built (decision 107), the first time release 5.25 runs.
BUILT = "notes_pages_built"


def build_all(conn: sqlite3.Connection, model: Model, stories, at: datetime) -> int:
    """Every task without a page gets its first one (decision 107), in one transaction. Returns how many."""
    made = 0
    with transaction(conn):
        for task_id, t in model.tasks.items():
            if t.discarded or task_id in model.pages:
                continue
            page = build(model, stories, task_id)
            conn.execute("INSERT INTO task_pages (task, body, updated) VALUES (?, ?, ?)", (task_id, page, stamp(at)))
            made += 1
        conn.execute("INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (BUILT, stamp(at)))
    return made


def needs_build(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM app_state WHERE key = ?", (BUILT,)).fetchone() is None
