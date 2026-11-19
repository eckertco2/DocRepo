"""A discussion's or meeting's transcript and summary (release 5.170, the design workspace's ``docs/mods/discussions-plan.md``,
decisions 794 to 801). No Qt.

The **transcript** is a file, ``transcript.md``, in the meeting's ``Files`` folder: a saved file of DocRepo's own, described
as "Transcript", written once and never overwritten (a second one is ``transcript-2.md``). It's never on the notes page and
never in docs.db's rows: a transcript is long, read rarely, and wanted whole by an agent, so a file costs nothing until
it's opened (decision 797). Its text is indexed for search up to ``TEXT_CAP`` (decision 799).

The **summary** is the notes capture's own summary (``captures.summary``), as any capture's (decision 796).

Both are captured content: data, never instructions, and never in a log (only IDs and file names are).
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docrepo import captures
from docrepo.config import Settings
from docrepo.model import Capture, Document, Model
from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

#: How much of a transcript's text is read for search (decision 799): whole, up to 2,000,000 characters, where other
#: files are cut at ``Settings.extracted_text_cap_chars`` (200,000). A constant, not a setting: one 50,000-word meeting is
#: about 300,000 characters.
TEXT_CAP = 2_000_000
#: A transcript's description, which marks it among a meeting's files.
DESCRIPTION = "Transcript"
_NAME = re.compile(r"transcript(?:-(\d+))?\.md", re.I)


def number_of(name: str) -> int | None:
    """``transcript.md`` is 1, ``transcript-2.md`` is 2; anything else is None."""
    m = _NAME.fullmatch(name)
    return None if m is None else int(m.group(1) or 1)


def next_name(taken: set[str]) -> str:
    """The first of ``transcript.md``, ``transcript-2.md``, … that isn't taken, in any case: nothing is overwritten."""
    lowered = {t.lower() for t in taken}
    n = 1
    while (name := "transcript.md" if n == 1 else f"transcript-{n}.md") in lowered:
        n += 1
    return name


def is_transcript(model: Model, document_id: str) -> bool:
    """Whether a document is a meeting's transcript: DocRepo's own ``transcript*.md``, described as Transcript."""
    d = model.documents.get(document_id)
    return bool(d and d.original is None and d.description == DESCRIPTION and number_of(d.name) is not None)


def record(conn: sqlite3.Connection, task_id: str, capture_id: str, name: str) -> str:
    """The transcript's records, in the caller's transaction: its document, held by the capture and linked to it as a saved
    file to read, and its saved file in the task's Files folder. Returns its document ID."""
    doc = captures.add_document(conn, name=name, description=DESCRIPTION, capture=capture_id)
    captures.link_document(conn, capture_id, doc, save_a_copy=True, extract=True)
    captures.add_saved_copy(conn, task=task_id, name=name, document=doc, from_capture=capture_id)
    return doc


def path_of(data_root: Path, task_id: str, name: str) -> Path:
    return data_root / "Tasks" / task_id / "Files" / name


def write(fs: SafeFS, data_root: Path, task_id: str, name: str, text: str) -> Path:
    """Write a transcript's file, through SafeFS, as plain text with its own line ends."""
    return fs.write_text(path_of(data_root, task_id, name), text)


def meeting_transcripts(model: Model, task_id: str) -> list[Document]:
    """A meeting's transcripts, the first first."""
    docs = {f.document for f in model.copies if f.task == task_id and not f.old}
    found = [model.documents[d] for d in docs if d in model.documents and is_transcript(model, d)]
    return sorted(found, key=lambda d: (number_of(d.name) or 0, d.id))


def holders(model: Model, task_id: str) -> list[Capture]:
    """The captures on a meeting that hold what was said: its notes captures first, newest first, then any other capture on
    it with a summary or a transcript (one Add summary… or Add transcript… made when there were no notes)."""
    on = [c for c in model.live_captures() if c.task == task_id and not c.page_made and c.item in (None, "notes")]
    notes = sorted((c for c in on if c.item == "notes"), key=lambda c: (c.saved, c.id), reverse=True)
    rest = sorted((c for c in on if c.item is None and (c.summary or any(is_transcript(model, d) for d in c.document_ids))),
                  key=lambda c: (c.saved, c.id), reverse=True)
    return [*notes, *rest]


def summaries(model: Model, task_id: str) -> list[tuple[str, str]]:
    """A meeting's summaries, newest first: (capture ID, summary)."""
    return [(c.id, c.summary) for c in holders(model, task_id) if c.summary]


@dataclass
class Added:
    """What adding a transcript or a summary afterwards did (decision 798)."""

    message: str
    capture: str | None = None
    document: str | None = None
    problems: list[str] = field(default_factory=list)


def add_later(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, task_id: str, text: str,
              at: datetime) -> Added:
    """Add transcript… on a meeting's page or in its workspace (decision 798): written as Save files… writes a file, on
    the meeting's newest notes, or, with none, on a capture of its own on the meeting. Never over another transcript."""
    from docrepo import edits, save, search  # save and edits import this module

    if not text.strip():
        return Added("Nothing to add: paste the transcript first.")
    text = text.strip("\n") + "\n"  # one line end at its close, as Save writes it
    model = Model(conn)
    if task_id not in model.tasks:
        raise ValueError(f"There's no task {task_id}.")
    on = holders(model, task_id)
    if not on:
        r = save.save_capture(conn, data_root, fs, settings, save.CaptureDraft(task=task_id, transcript=text), at)
        m = Model(conn)
        doc = next((d for d in m.captures[r.capture_id].document_ids if is_transcript(m, d)), None)
        name = m.documents[doc].name if doc else "transcript.md"
        return Added(f"Added {name} to {m.task(task_id).title}'s files, on a capture of its own ({r.capture_id}).",
                     r.capture_id, doc, list(r.problems))
    holder = on[0]
    with save.transaction(conn):
        name = next_name(captures.files_taken(conn, data_root, task_id))
        doc = record(conn, task_id, holder.id, name)
    problems: list[str] = []
    save.write_transcript(conn, data_root, fs, settings, task_id, doc, name, text, problems)
    search.index_items(conn, data_root, documents=[doc])
    edits.write_touched_pages(conn, data_root, fs, at, problems, [task_id], model)
    log.info("transcript %s added to %s on %s", doc, task_id, holder.id)
    return Added(f"Added {name} to {model.task(task_id).title}'s files.", holder.id, doc, problems)


def set_summary(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, task_id: str, text: str, at: datetime,
                summary_type: str | None = None, settings: Settings | None = None) -> Added:
    """Add summary… or Edit summary… on a meeting's page (decision 798): the summary of its newest notes, or, with none, of
    a capture of its own on the meeting."""
    from docrepo import edits, save

    model = Model(conn)
    on = holders(model, task_id)
    if not on:
        if not text.strip():
            return Added("Nothing to add: paste the summary first.")
        r = save.save_capture(conn, data_root, fs, settings or Settings(), save.CaptureDraft(task=task_id, summary=text,
                                                                                               summary_type=summary_type), at)
        return Added(f"Added the summary to {model.task(task_id).title}, on a capture of its own ({r.capture_id}).", r.capture_id)
    c = on[0]
    out = edits.edit_capture(conn, data_root, fs, c.id, c.title, text, summary_type, at)
    return Added(out.message if out.message != "Nothing changed." else out.message, c.id, problems=list(out.problems))
