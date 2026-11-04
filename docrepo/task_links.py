"""A task's links in one place (release 5.67, round 6's items 88 and 90, decisions 316, 317 and 320).

What counts (decision 317): the task's reference fields that have a link address in Settings, its link and folder
documents (from its captures, Add link, and email layer 0's kept links), and the web addresses in its notes page's
words, each once. A subtask's are on its own page, and in the Task view, which covers subtasks.

The order, as mocked and approved: reference fields first, then the task's pinned links, then the newest. The task
page shows the first ``SHOWN``, then a button to the Task view, whose Link type lists the link documents.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from docrepo import notes_page
from docrepo.links import ADDRESS, is_folder, is_link, read_address, reference_link
from docrepo.model import Model
from docrepo.text import is_file_line

#: The Links group's rows on the task page before its button to the Task view (decision 316).
SHOWN = 5


@dataclass(frozen=True)
class TaskLink:
    """One of a task's links: ``kind`` is "reference" (a reference field's link), "link" or "folder" (a document), or
    "text" (an address in its notes page's words)."""

    kind: str
    name: str
    address: str
    document: str | None = None
    at: str = ""
    pinned: bool = False

    @property
    def where(self) -> str:
        """What the row says after the name: the host, "In a note" and the host, or Folder."""
        if self.kind == "folder":
            return "Folder"
        host = urlsplit(self.address).hostname or ""
        return f"In a note · {host}" if self.kind == "text" else host

    @property
    def opens(self) -> str:
        """Where it opens, for its tooltip: before the click, the whole address (decision 314)."""
        return f"Opens in File Explorer: {self.address}" if self.kind == "folder" else f"Opens in your browser: {self.address}"


def _name_of(address: str) -> str:
    """An address found in a note's words has no name: its path's last part ("Torque.aspx"), or else its host."""
    parts = urlsplit(address)
    last = unquote(parts.path.rstrip("/").rpartition("/")[2])
    return last or parts.hostname or address


def addresses_in(page: str) -> list[str]:
    """The web addresses in a notes page's words: not its file lines, which are documents, nor a link on a line of its
    own, which is one too. Each tidied as ``links.read_address`` tidies a link."""
    out: list[str] = []
    for line in notes_page.lines_of(page):
        if line.kind not in ("text", "row") or is_file_line(line.text.strip()):
            continue
        for raw in ADDRESS.findall(line.text):
            a = read_address(raw, one=False)
            if a.kind == "link" and a.value not in out:
                out.append(a.value)
    return out


def links_of(model: Model, task_id: str, reference_links: Mapping[str, str] | None = None) -> list[TaskLink]:
    """The task's links, in the Links group's order. ``reference_links``: Settings' link address for each reference field."""
    t = model.task(task_id)
    out: list[TaskLink] = []
    seen: set[str] = set()

    def add(x: TaskLink) -> None:
        if x.address not in seen:
            seen.add(x.address)
            out.append(x)

    for name, value in t.references.items():
        address = reference_link((reference_links or {}).get(name), value)
        if address:
            add(TaskLink("reference", f"{name} {value}", address))
    pinned = set(model.pins.get(task_id, []))
    found: list[TaskLink] = []
    for c in model.notes_of(task_id):
        for doc_id in c.document_ids:
            d = model.documents.get(doc_id)
            if d is None or not d.original:
                continue
            if is_link(d.original):
                found.append(TaskLink("link", d.name, d.original.strip(), doc_id, c.saved, doc_id in pinned))
            elif is_folder(d.original):
                found.append(TaskLink("folder", d.name, d.original, doc_id, c.saved, doc_id in pinned))
    found.sort(key=lambda x: x.at, reverse=True)
    found.sort(key=lambda x: not x.pinned)  # stable: the pinned first, each part newest first
    for x in found:
        add(x)
    for address in addresses_in(model.pages.get(task_id, "")):
        add(TaskLink("text", _name_of(address), address))
    return out


def all_documents(links: list[TaskLink]) -> bool:
    """Whether every link is a document, so the Task view's Link type lists them all (decision 323)."""
    return all(x.document for x in links)
