"""How a file is listed (release 5.114, the file rows review's decisions 427 to 434).

One recipe wherever a file or a search result is a row: its type's mark in its type's colour, its name, one quiet line
(where it is, then the words that matched or its description), one short date at the row's end, a chip only for
something wrong, and marks only on what matched. What a row used to repeat on every line (where it came from, "Saved
copy", "Current", the day it was checked, a path, an email's headers) is in its preview or its tooltip instead.

No Qt here, so it's tested in the fast run; the lists and pages draw it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from docrepo.model import Model
from docrepo.overview import TYPE_NAMES

#: The types with a colour of their own; the rest are drawn in ``type_other``'s.
_COLOURED = frozenset({"doc", "sheet", "slides", "pdf", "picture", "mail", "drawing", "link"})
#: Search's groups as their headings say them, plural, with how many follow (decision 430).
GROUP_NAMES = {"Tagged label": "Tagged labels", "Task": "Tasks", "Notes": "Notes pages", "Capture": "Captures", "Decision": "Decisions", "Document": "Documents",
               "Saved copy": "Saved copies", "Person": "People", "Label": "Labels"}
#: A saved copy's name starts with the day it was saved (decision 429 shows the day at the row's end instead).
_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2}) (.+)$")


def type_icon(kind: str) -> str:
    """A file type's icon: ``type-pdf``, ``folder``, and ``type-other`` for a type with none of its own."""
    return "folder" if kind == "folder" else f"type-{kind if kind in _COLOURED else 'other'}"


def type_colour(kind: str) -> str:
    """A file type's colour token (decision 427): every list draws a type in the same colour."""
    return f"type_{kind}" if kind in _COLOURED else "type_other"


def type_name(kind: str) -> str:
    """A file type in words, for a tooltip: "PDF", "Excel"."""
    return TYPE_NAMES.get(kind, "Other")


@dataclass
class DocPlace:
    """Where a document is: the tasks it's on, in the order they took it, and when it first came in."""

    tasks: list[str] = field(default_factory=list)
    added: str = ""


def doc_places(m: Model) -> dict[str, DocPlace]:
    """Every document's place, read once for a whole list: the tasks of the captures that brought it, then those it's saved
    on. A discarded capture brings nothing."""
    out: dict[str, DocPlace] = {}
    for c in sorted(m.captures.values(), key=lambda c: c.saved):
        if c.discarded:
            continue
        for d in c.document_ids:
            place = out.setdefault(d, DocPlace(added=c.saved))
            if c.task and c.task in m.tasks and c.task not in place.tasks:
                place.tasks.append(c.task)
    for f in m.copies:
        place = out.setdefault(f.document, DocPlace())
        if f.task in m.tasks and f.task not in place.tasks:
            place.tasks.append(f.task)
    return out


def place_words(m: Model, place: DocPlace | None) -> str:
    """Where a document is, in a few words: its task, "and 2 more" when it's on others, or "Not filed yet"."""
    tasks = [t for t in (place.tasks if place else []) if not m.task(t).discarded]
    if not tasks:
        return "Not filed yet"
    return m.task(tasks[0]).title + (f" and {len(tasks) - 1} more" if len(tasks) > 1 else "")


def dated_name(name: str) -> tuple[str, str]:
    """A saved copy's name split into the day it starts with and the rest: ("2026-08-03", "Tie-in list.xlsx"). A name that
    doesn't start with a day comes back whole, with no day."""
    m = _DATED.match(name)
    return (m.group(1), m.group(2)) if m else ("", name)


def without_title(snippet: str, title: str) -> str:
    """A result's matched words without its own title, which its first line says already (decision 430): a capture's text
    often starts with its subject or its first sentence, and an email's with its sender then its subject. The title is
    taken out only at the start, or after a "·"."""
    if not snippet or len(title) < 4:
        return snippet
    lead = "…" if snippet.startswith("…") else ""
    body = snippet[len(lead):]
    cut = re.sub(rf"(^|· ){re.escape(title)}\s*[.,;:]?\s*(?:·\s*)?", r"\1", body, count=1, flags=re.IGNORECASE).strip(" ·")
    if cut == body:
        return snippet
    return ("" if body.lower().startswith(title.lower()) else lead) + cut


def folder_of(path: str) -> str:
    """The folder a file is in, for its preview (decision 432): its name is the preview's title already. A link, or a path
    with no folder, comes back whole."""
    if not path or "://" in path:
        return path
    head, sep, _ = path.rstrip("\\/").rpartition("\\" if "\\" in path else "/")
    return head + sep if head else path
