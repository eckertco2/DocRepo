"""The Task view's records (release 5.34; the design workspace's task overview design, decisions 156 to 167): everything
a task and the tasks under it hold, as one list of records the Task view shows, groups and searches.

A record is a file (a document, once, from the first capture that brought it), an email, a note or update (a capture,
as it reads on the notes page now), text typed straight onto a notes page (a record per heading section), or a
subtask. Each keeps its words lower-cased and without accents for ``docrepo.finder``. A file's extracted text isn't
here: it's the search's second tier, read separately (``file_texts``).

Nothing here touches a file on a drive: the type comes from a file's name, so drawing the window never waits on the LAN.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from docrepo import markup, notes_page
from docrepo.captures import capture_folder
from docrepo.links import is_link
from docrepo.model import Capture, Model

#: A file's type, by its extension. Anything else is "other"; a link is "link".
TYPES = {
    "doc": ("docx", "doc", "docm", "rtf", "odt", "txt", "md"),
    "sheet": ("xlsx", "xls", "xlsm", "xlsb", "csv", "ods"),
    "slides": ("pptx", "ppt", "pptm", "odp"),
    "pdf": ("pdf",),
    "picture": ("png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"),
    "mail": ("msg", "eml"),
    "drawing": ("vsdx", "vsd", "dwg", "dxf"),
}
_EXT = {ext: kind for kind, exts in TYPES.items() for ext in exts}
TYPE_NAMES = {"doc": "Word", "sheet": "Excel", "slides": "PowerPoint", "pdf": "PDF", "picture": "Picture", "mail": "Email",
              "drawing": "Drawing", "link": "Link", "other": "Other"}
TYPE_ORDER = ("doc", "sheet", "slides", "pdf", "drawing", "picture", "mail", "link", "other")
#: Where a file came from, in the order Group by Source lists them.
SOURCES = ("Tracked original", "Email attachment", "Saved copy", "Link", "Pasted on the notes page")
SOURCE_NAMES = {"Tracked original": "Tracked originals", "Email attachment": "Email attachments", "Saved copy": "Saved copies",
                "Link": "Links", "Pasted on the notes page": "Pasted on the notes page"}
#: The kinds, in the order the Task view lists them, and their names.
KINDS = ("file", "email", "note", "task")
KIND_NAMES = {"all": "All", "file": "Files", "email": "Emails", "note": "Notes and updates", "task": "Subtasks"}

_FROM = re.compile(r"^From:\s*(.+?)\s*$", re.M)
_ADDRESS = re.compile(r"\s*<[^>]*>\s*$")
_HEAD = re.compile(r"^(?:(?:From|To|Cc|Sent|Date|Subject):.*\n)+\s*")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def fold(text: str | None) -> str:
    """Lower case without accents, keeping one character for each one in, so a match's place is its place in the text."""
    out = []
    for ch in (text or "").lower():
        base = unicodedata.normalize("NFD", ch)
        out.append(base[0] if base and len(base) > 1 and unicodedata.combining(base[1]) else ch)
    return "".join(out)


def words_of(folded: str) -> list[str]:
    return [w for w in re.split(r"[^0-9a-z]+", folded) if w]


def file_type(name: str, original: str | None = None) -> str:
    if is_link(original):
        return "link"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _EXT.get(ext, "other")


_PATH_LINE = re.compile(r'^\s*"?(?:\\\\|[A-Za-z]:\\|https?://)\S')


def without_paths(text: str) -> str:
    """A capture's text without its file path and link lines, which are its files."""
    return "\n".join(line for line in text.split("\n") if not _PATH_LINE.match(line)).strip()


def sender_of(text: str) -> str:
    """An email's sender, from its capture's From line, without the address."""
    m = _FROM.search(text or "")
    return _ADDRESS.sub("", m.group(1)).strip().strip('"') if m else ""


@dataclass
class Record:
    """One thing the Task view lists."""

    kind: str                # file, email, note or task
    id: str                  # a document's, capture's or task's ID; a notes page section's "T000001#2"
    task: str                # the task it belongs to
    at: str                  # when it came: YYYY-MM-DD HH:MM:SS
    title: str
    desc: str = ""           # the second line: a file's description, an email's sender and attachments, a subtask's facts
    text: str = ""           # searched on every keystroke: a note's, an email's, a page section's or a subtask's words
    type: str = ""           # a file's type (TYPES), or the kind's mark: mail, note, update, page, task
    source: str = ""         # a file's source (SOURCES)
    came: str = ""           # where a file came from, in words: "Email from Tom Becker", "a Note"
    sender: str = ""         # an email's sender, or the sender of the email a file came with
    capture: str = ""        # the capture that brought it, or that it is
    path: str = ""           # a file's original or where DocRepo keeps it; a link's address
    copy: str = ""           # a saved copy of it, when there is one
    state: str = ""          # a subtask's state
    attachments: list[str] = field(default_factory=list)
    # Its words for matching (docrepo.finder): lower-cased and without accents.
    n_title: str = ""
    n_desc: str = ""
    n_src: str = ""
    n_text: str = ""
    words: list[str] = field(default_factory=list)

    @property
    def day(self) -> str:
        return self.at[:10]

    def fold(self, extra: str = "") -> None:
        self.n_title, self.n_desc, self.n_text = fold(self.title), fold(self.desc), fold(self.text)
        self.n_src = fold(" ".join(x for x in (self.came, self.sender, extra) if x))
        self.words = words_of(self.n_title)


# ---- reading what's there ----
def family(model: Model, task_id: str) -> list[str]:
    """The task and every task under it, in tree order, without discarded ones."""
    return [x for x in [task_id, *model.descendants_of(task_id)] if x in model.tasks and not model.tasks[x].discarded]


def capture_texts(conn: sqlite3.Connection, capture_ids: Iterable[str]) -> dict[str, str]:
    """Each capture's text as the search index keeps it, without its ID and title lines."""
    ids = list(capture_ids)
    out: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        rows = conn.execute(f"SELECT id, body FROM search_text WHERE kind = 'capture' AND id IN ({','.join('?' * len(chunk))})", chunk)
        for r in rows:
            body = r["body"]
            out[r["id"]] = body.split("\n", 2)[2] if body.count("\n") >= 2 else ""
    return out


def file_texts(conn: sqlite3.Connection, model: Model, document_ids: Iterable[str]) -> dict[str, str]:
    """Each document's extracted text, as written, from the search index: the search's second tier and the preview
    (release 5.35). The index keeps the ID, name, description and original first; they're taken off."""
    ids = list(document_ids)
    out: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in conn.execute(f"SELECT id, body FROM search_text WHERE kind = 'document' AND id IN ({','.join('?' * len(chunk))})", chunk):
            d = model.documents.get(r["id"])
            head = "\n".join(x for x in (d.id, d.name, d.description or "", d.original or "") if x) if d else ""
            body = r["body"]
            out[r["id"]] = body[len(head):].lstrip("\n") if head and body.startswith(head) else body
    return out


def page_texts(page: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """A notes page as text: each capture's block (its caption to the next caption or heading) as it reads now, and the
    text typed straight on the page, as (heading, text) for each heading's section that has some."""
    blocks: dict[str, list[str]] = {}
    sections: list[tuple[str, list[str]]] = [("", [])]
    current: list[str] | None = None
    for line in notes_page.lines_of(page):
        if line.kind == "heading":
            sections.append((line.text, []))
            current = None
        elif line.kind == "caption":
            current = blocks.setdefault(line.ref, [])
        elif line.kind in ("file", "picture", "attachment"):
            continue  # the files are records of their own
        else:
            if line.kind == "row":
                words = "" if notes_page.is_separator(line.text) else " ".join(markup.to_plain(x) for x in notes_page.cells_of(line.text))
            else:
                words = markup.to_plain(line.text) if line.kind == "text" else line.text
            words = words.strip()
            if not words:
                continue
            (current if current is not None else sections[-1][1]).append(words)
    return ({cid: "\n".join(lines) for cid, lines in blocks.items()},
            [(heading, "\n".join(lines)) for heading, lines in sections if lines])


def _changes(model: Model) -> dict[str, list[str]]:
    """Each capture's field changes, in words, for searching an update by what it changed."""
    out: dict[str, list[str]] = {}
    for e in model.status:
        if e.via and e.via.startswith("C"):
            out.setdefault(e.via, []).append(f"{e.field} {e.to_value or ''}".strip())
    return out


def build(model: Model, data_root: Path, task_id: str, texts: dict[str, str]) -> list[Record]:
    """Every record of the task and the tasks under it. ``texts`` is each capture's indexed text (``capture_texts``)."""
    fam = family(model, task_id)
    in_fam = set(fam)
    caps: list[tuple[Capture, str]] = []
    for c in sorted(model.live_captures(), key=lambda c: (c.saved, c.id)):
        mine = [t for t in model.capture_tasks(c) if t in in_fam]
        if mine:
            caps.append((c, mine[0]))
    changes = _changes(model)
    on_pages = {t: page_texts(model.pages.get(t, "")) for t in fam}
    copies = {f.document: f for f in model.copies if not f.old and f.task in in_fam}
    out: list[Record] = []
    seen: set[str] = set()
    for c, tid in caps:
        text = texts.get(c.id, "")
        if c.source == "outlook_email":
            sender = sender_of(text)
            n = len(c.document_ids)
            r = Record("email", c.id, tid, c.saved, c.title, f"From {sender or 'an unknown sender'}" + (f" · {n} attachment{'s' * (n != 1)}" if n else ""),
                       _HEAD.sub("", text, count=1), "mail", sender=sender, capture=c.id, attachments=list(c.document_ids))
            r.fold(" ".join(model.documents[d].name for d in c.document_ids if d in model.documents))
            out.append(r)
        else:
            body = on_pages[tid][0].get(c.id) if tid in on_pages else None
            body = without_paths(body if body is not None else text)
            said = changes.get(c.id, [])
            if body.strip() or said or not c.document_ids:
                kind = "update" if c.has("update") else "note"
                r = Record("note", c.id, tid, c.saved, c.title, "", "\n".join(x for x in (body, *said) if x), kind, capture=c.id)
                r.fold()
                out.append(r)
        for doc_id in c.document_ids:
            if doc_id in seen or doc_id not in model.documents:
                continue
            seen.add(doc_id)
            out.append(_file(model, data_root, c, tid, doc_id, copies, text))
    # Saved copies of documents no capture in the family brought.
    for doc_id, f in copies.items():
        if doc_id not in seen and doc_id in model.documents:
            seen.add(doc_id)
            c = model.captures.get(f.from_capture or "")
            at = c.saved if c else model.tasks[f.task].created
            d = model.documents[doc_id]
            r = Record("file", doc_id, f.task, at, d.name, d.description or "", "", file_type(d.name, d.original), "Saved copy", "a saved copy",
                       capture=f.from_capture or "", path=str(data_root / "Tasks" / f.task / "Files" / f.name),
                       copy=str(data_root / "Tasks" / f.task / "Files" / f.name))
            r.fold(model.tasks[f.task].title)
            out.append(r)
    # Text typed straight on a notes page, a record for each heading's section.
    for tid in fam:
        for n, (heading, text) in enumerate(on_pages[tid][1]):
            t = model.tasks[tid]
            r = Record("note", f"{tid}#{n}", tid, t.created, heading or f"Notes page of {t.title}", "On the notes page", text, "page")
            r.fold()
            out.append(r)
    for tid in fam[1:]:
        t = model.tasks[tid]
        people = ", ".join(model.person_name(p) for p in dict.fromkeys([*t.leads, *t.assignees]))
        facts = " · ".join(x for x in (t.state, f"due {t.due}" if t.due else "", people) if x)
        parent = next((p for p in model.parents_of(tid) if p in in_fam), task_id)
        r = Record("task", tid, parent, t.created, t.title, facts, "\n".join(x for x in (t.description, t.current_status) if x), "task", state=t.state)
        r.fold(" ".join(model.person_name(p) for p in [*t.leads, *t.assignees]))
        out.append(r)
    return out


def _file(model: Model, data_root: Path, c: Capture, tid: str, doc_id: str, copies: dict, text: str) -> Record:
    d = model.documents[doc_id]
    kind = file_type(d.name, d.original)
    copy = copies.get(doc_id)
    copy_path = str(data_root / "Tasks" / copy.task / "Files" / copy.name) if copy else ""
    if kind == "link":
        source, path = "Link", d.original or ""
    elif d.original:
        source, path = ("Pasted on the notes page" if c.page_made and kind == "picture" else "Tracked original"), d.original
    else:
        source = "Email attachment"
        path = str(capture_folder(data_root, c.id, c.saved) / "attachments" / d.name)
    sender = sender_of(text) if c.source == "outlook_email" else ""
    if c.source == "outlook_email":
        came = f"Email from {sender or 'an unknown sender'}"
    elif c.page_made:
        came = "the notes page"
    else:
        came = "an Update" if c.has("update") else "a Note"
    r = Record("file", doc_id, tid, c.saved, d.name, d.description or "", "", kind, source, came, sender, c.id, path, copy_path)
    # Its subtask and the folders it's in are found too: people look for a file where they put it.
    r.fold(f"{model.tasks[tid].title} {folders_of(path) if source == 'Tracked original' else ''}")
    return r


def folders_of(path: str) -> str:
    """A path's folder names, without the server and share: "\\\\server\\eng\\Line 2\\Piping\\x.pdf" is "Line 2 Piping"."""
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if path.startswith("\\\\"):
        parts = parts[2:]
    elif parts and parts[0].endswith(":"):
        parts = parts[1:]
    return " ".join(parts[:-1])


# ---- choosing, grouping and sorting ----
def in_scope(model: Model, r: Record, scope: str, root: str) -> bool:
    """Whether a record is in the outline's scope: the whole task (``root``), or one subtask's branch."""
    if scope == root:
        return True
    branch = {scope, *model.descendants_of(scope)}
    return (r.id if r.kind == "task" else r.task) in branch


def counts(records: Iterable[Record]) -> dict[str, int]:
    """How many of each kind, and all of them."""
    out = dict.fromkeys(("all", *KINDS), 0)
    for r in records:
        out[r.kind] += 1
        out["all"] += 1
    return out


def date_group(at: str, today: date) -> tuple[float, str]:
    """A date's group, as File Explorer and Outlook name them: Today, Yesterday, Earlier this week, Last week, then months."""
    day = date.fromisoformat(at[:10])
    n = (today - day).days
    monday = today.toordinal() - today.weekday()
    if n <= 0:
        return 0, "Today"
    if n == 1:
        return 1, "Yesterday"
    if day.toordinal() >= monday:
        return 2, "Earlier this week"
    if day.toordinal() >= monday - 7:
        return 3, "Last week"
    months = (today.year - day.year) * 12 + today.month - day.month
    return 10 + months, f"{MONTHS[day.month - 1]} {day.year}"


def group(model: Model, records: list[Record], how: str, today: date, root: str) -> list[tuple[str, list[Record]]]:
    """The records under their headings: by "date" added, "task" (subtask, in tree order), "type", "source" or "none"."""
    if how == "none":
        return [("", records)]
    order = family(model, root)
    keyed: dict[str, tuple[float, list[Record]]] = {}
    for r in records:
        if how == "task":
            owner = r.id if r.kind == "task" else r.task
            k, label = (order.index(owner) if owner in order else len(order)), ("The task itself" if owner == root else path_of(model, owner, root))
        elif how == "type":
            k, label = TYPE_ORDER.index(r.type) if r.type in TYPE_ORDER else len(TYPE_ORDER), TYPE_NAMES.get(r.type, "Other")
        elif how == "source":
            k, label = (SOURCES.index(r.source) if r.source in SOURCES else len(SOURCES)), SOURCE_NAMES.get(r.source, "Other")
        else:
            k, label = date_group(r.at, today)
        keyed.setdefault(label, (k, []))[1].append(r)
    return [(label, rs) for label, (k, rs) in sorted(keyed.items(), key=lambda x: x[1][0])]


def path_of(model: Model, task_id: str, root: str) -> str:
    """A subtask's path under the root: "Pump and motor package › Motor and VFD"."""
    chain = next((c for c in model.chains_of(task_id) if root in c), [task_id])
    return " › ".join(model.task(x).title for x in chain[chain.index(root) + 1:]) if root in chain else model.task(task_id).title


def sort(records: list[Record], how: str, last_use: dict[str, str] | None = None) -> list[Record]:
    """Newest first ("new", the default), "old", "name", "used" (last opened from DocRepo, then newest) or "type"."""
    if how == "old":
        return sorted(records, key=lambda r: (r.at, r.id))
    if how == "name":
        return sorted(records, key=lambda r: (r.title.lower(), r.at))
    if how == "used":
        used = last_use or {}
        return sorted(records, key=lambda r: (used.get(r.id, ""), r.at), reverse=True)
    if how == "type":
        return sorted(records, key=lambda r: (TYPE_ORDER.index(r.type) if r.type in TYPE_ORDER else 99, r.title.lower()))
    return sorted(records, key=lambda r: (r.at, r.id), reverse=True)


# ---- Overview ----
@dataclass
class Recent:
    record: Record
    at: str
    why: str  # "opened today", "added yesterday"


USE_WORDS = {"open": "opened", "show": "shown", "copy_path": "path copied", "copy_link": "link copied"}


def ago(at: str, today: date) -> str:
    day = date.fromisoformat(at[:10])
    n = (today - day).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    if n < 7:
        return f"{n} days ago"
    return f"on {day.day} {MONTHS[day.month - 1][:3]}"


def recent(records: list[Record], uses: list[tuple[str, str, str]], today: date, limit: int = 8) -> list[Recent]:
    """Overview's Recent: the files opened, shown or copied from DocRepo lately (``uses``: document, when, action, newest
    first), mixed with those added lately, newest first, each once."""
    files = {r.id: r for r in records if r.kind == "file"}
    out: list[Recent] = []
    seen: set[str] = set()
    for doc_id, at, action in uses:
        if doc_id in files and doc_id not in seen:
            seen.add(doc_id)
            out.append(Recent(files[doc_id], at, f"{USE_WORDS.get(action, 'opened')} {ago(at, today)}"))
    for r in sort(list(files.values()), "new")[:limit]:
        if r.id not in seen:
            seen.add(r.id)
            out.append(Recent(r, r.at, f"added {ago(r.at, today)}"))
    return sorted(out, key=lambda x: x.at, reverse=True)[:limit]


def latest(records: list[Record], limit: int = 4) -> list[Record]:
    """Overview's Latest updates: the newest notes, updates and emails."""
    return sort([r for r in records if r.kind in ("note", "email") and r.type != "page"], "new")[:limit]
