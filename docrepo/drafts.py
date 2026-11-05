"""Drafts (release 5.77, round 7's item 94, decisions 333 to 338): captures closed before they were saved.

Every capture window opens empty. Closing one that holds something unsaved files it here, without asking, and the
capture window's Drafts button (or the tray's Drafts…) opens it again. Each draft is a folder in ``System\\Drafts`` in
the data root, named by when it was first kept:

- ``draft.json``: the form, as the capture window keeps it every 30 seconds, with a row for each file;
- the files a program handed over, written exactly as handed over (``SafeFS.write_copy``): an Outlook email's ``.msg``
  under ``emails``, a file dragged from an email or a zip folder under ``files``; and a pasted picture as its PNG
  (``SafeFS.write_picture``). Paths and links stay as text in ``draft.json``.

So a restart keeps a draft whole. A draft that's saved as a capture, or discarded, moves to ``System\\Drafts\\Done``:
DocRepo deletes nothing, and the owner can empty that folder by hand. Drafts never expire.

The draft files of releases 5.8 and 5.41, ``System\\capture-draft.json`` and ``System\\capture-draft-aside.json``, move
in as drafts of their own on the first start (``move_old_drafts``). Their form is the one ``draft.json`` keeps, without
the files.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

DRAFTS_DIR = Path("System") / "Drafts"
DONE_DIR = DRAFTS_DIR / "Done"
DRAFT_JSON = "draft.json"
#: The one draft file of release 5.8, and the draft set aside of release 5.41 (decision 215).
OLD_FILES = (Path("System") / "capture-draft.json", Path("System") / "capture-draft-aside.json")
#: draft.json's form: 1 is release 5.77's. A file without it is an old draft file, moved in.
FORMAT = 1


@dataclass(frozen=True)
class Draft:
    """A draft in the Drafts list: its folder's name, what it holds, and when it last changed."""

    id: str
    data: dict[str, Any]

    @property
    def changed(self) -> str:
        return str(self.data.get("saved") or "")

    def words(self, width: int = 60) -> str:
        """What the list shows first: its first line with words, else its title, its first file's name, or Meeting notes."""
        content = str(self.data.get("content") or "")
        line = next((x.strip() for x in content.split("\n") if x.strip()), "")
        if line:
            from docrepo.markup import text_of  # its marks off, when it's formatted

            line = text_of(line).strip() if self.data.get("formatted") else line
        files = [f.get("name") for f in self.data.get("files") or [] if isinstance(f, dict) and f.get("kind") != "part"]
        words = (line or str(self.data.get("title") or "").strip() or next((str(n) for n in files if n), "")
                 or next((str(n) for n in self.data.get("file_names") or [] if n), "")
                 or ("Meeting notes" if self.data.get("meeting") else "Empty"))
        return words if len(words) <= width else words[:width - 1] + "…"

    def file_count(self) -> int:
        """Its files: an email counts once, with its parts; an old draft counts the files a restart lost."""
        rows = [f for f in self.data.get("files") or [] if isinstance(f, dict) and f.get("kind") != "part"]
        return len(rows) or len(self.data.get("file_names") or [])

    def when(self, today: date) -> str:
        """When it last changed: its time today, else its day ("Mon 2 Nov")."""
        try:
            at = datetime.fromisoformat(self.changed)
        except ValueError:
            return ""
        return f"{at:%H:%M}" if at.date() == today else f"{at:%a} {at.day} {at:%b}"


def folder(data_root: Path, draft_id: str) -> Path:
    return data_root / DRAFTS_DIR / draft_id


def new_id(data_root: Path, now: datetime) -> str:
    """A new draft's folder name: when it was first kept, "2026-11-05 104233", with " (2)" and so on when it's taken,
    in Drafts or in Done."""
    base = f"{now:%Y-%m-%d %H%M%S}"
    name, n = base, 2
    while (data_root / DRAFTS_DIR / name).exists() or (data_root / DONE_DIR / name).exists():
        name, n = f"{base} ({n})", n + 1
    return name


def read(data_root: Path, draft_id: str) -> dict[str, Any] | None:
    """A draft's draft.json, or None when it can't be read or holds nothing."""
    try:
        data = json.loads((folder(data_root, draft_id) / DRAFT_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and holds_anything(data) else None


def holds_anything(data: dict[str, Any]) -> bool:
    """Whether a kept draft holds words, a title, files, meeting notes or Make it a task."""
    return bool(str(data.get("content") or "").strip() or str(data.get("title") or "").strip() or data.get("files")
                or data.get("file_names") or data.get("meeting") or data.get("from_capture"))


def listed(data_root: Path, but: str | None = None) -> list[Draft]:
    """The drafts, the most recently changed first: every folder in Drafts with a draft.json that holds something, but
    ``but`` (the one open in the capture window) and Done."""
    base = data_root / DRAFTS_DIR
    try:
        names = [p.name for p in base.iterdir() if p.is_dir() and p.name != DONE_DIR.name and p.name != but]
    except OSError:
        return []
    out = [Draft(n, d) for n in names if (d := read(data_root, n)) is not None]
    return sorted(out, key=lambda d: (d.changed, d.id), reverse=True)


def write(fs: SafeFS, data_root: Path, draft_id: str, data: dict[str, Any]) -> Path:
    """Write a draft's draft.json, making its folder if it's new."""
    return fs.write_text(folder(data_root, draft_id) / DRAFT_JSON, json.dumps({**data, "draft": FORMAT}, ensure_ascii=False, indent=1))


def file_path(data_root: Path, draft_id: str, stored: str) -> Path | None:
    """Where one of a draft's files is, from its row's ``stored`` name, or None when the name would leave the folder."""
    base = folder(data_root, draft_id).resolve()
    path = (base / stored).resolve()
    return path if path.is_relative_to(base) and path != base else None


def file_bytes(data_root: Path, draft_id: str, stored: str) -> bytes | None:
    path = file_path(data_root, draft_id, stored)
    try:
        return path.read_bytes() if path else None
    except OSError:
        return None


def finish(fs: SafeFS, data_root: Path, draft_id: str) -> str | None:
    """A draft saved as a capture, or discarded: its folder moves to Done, under a name of its own there. Returns that
    name, for Undo, or None when there was no folder."""
    source = folder(data_root, draft_id)
    if not source.exists():
        return None
    name, n = draft_id, 2
    while (data_root / DONE_DIR / name).exists():
        name, n = f"{draft_id} ({n})", n + 1
    fs.move(source, data_root / DONE_DIR / name)
    log.info("draft %s moved to Done", draft_id)
    return name


def bring_back(fs: SafeFS, data_root: Path, done_name: str, draft_id: str) -> None:
    """Undo a discard: the folder moves back from Done."""
    fs.move(data_root / DONE_DIR / done_name, folder(data_root, draft_id))
    log.info("draft %s brought back from Done", draft_id)


def move_old_drafts(fs: SafeFS, data_root: Path, now: datetime) -> list[str]:
    """On the first start of release 5.77: each old draft file that holds something moves into a folder of its own in
    Drafts, as its draft.json (decision 337). An empty one ("{}", as releases 5.8 and 5.41 left them) stays."""
    moved = []
    for old in OLD_FILES:
        path = data_root / old
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not holds_anything(data):
            continue
        draft_id = new_id(data_root, _when(data.get("saved"), now))
        try:
            fs.move(path, folder(data_root, draft_id) / DRAFT_JSON)
        except OSError as e:
            log.warning("an old draft file wasn't moved into Drafts: %s", type(e).__name__)
            continue
        moved.append(draft_id)
        log.info("an old draft file moved into Drafts as %s", draft_id)
    return moved


def _when(saved: Any, now: datetime) -> datetime:
    try:
        return datetime.fromisoformat(str(saved))
    except ValueError:
        return now
