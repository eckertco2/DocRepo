"""The mods log: changes the owner wants made to DocRepo itself, noted with the ? button in the capture window.

It's a plain Markdown file, ``Mods\\mods-log.md``, kept out of docs.db on purpose:
it still works when something else is broken, and it never mixes with work data,
so it can leave the computer on its own (by hand, with Copy open or Copy all). Entries are
M0001, M0002 and so on, oldest first. An entry can be edited (mods log round 2,
M0047); its heading then ends with the day, "· edited YYYY-MM-DD", so a copy of
the log shows it changed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from docrepo.safe_fs import SafeFS

MODS_FILE = Path("Mods") / "mods-log.md"
AREAS = ("General", "Capture window", "Task picker", "Parse and populate", "Copy prompt", "Browse tool", "Capacity", "Documents")
TITLE = "# DocRepo mods log"
INTRO = ("Changes I want in DocRepo, noted with the ? button in the capture window, oldest first. "
         "Notes about the tool only: no names, captured content or work details.")
_HEADING = re.compile(r"^## (M\d{4}) · (\d{4}-\d\d-\d\d \d\d:\d\d) · (.+?) · (?:open|done (\d{4}-\d\d-\d\d))"
                      r"(?: · edited (\d{4}-\d\d-\d\d))?$")


@dataclass
class ModEntry:
    id: str
    at: str  # YYYY-MM-DD HH:MM
    area: str
    text: str
    done: str | None = None  # the day it was marked done
    edited: str | None = None  # the day it was last edited


def read_log(data_root: Path) -> list[ModEntry]:
    """The entries in the mods log, oldest first. A missing file is an empty log."""
    path = data_root / MODS_FILE
    if not path.exists():
        return []
    entries: list[ModEntry] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        m = _HEADING.match(line)
        if m:
            entries.append(ModEntry(m.group(1), m.group(2), m.group(3), "", m.group(4), m.group(5)))
        elif entries:
            entries[-1].text += line + "\n"
    for e in entries:
        e.text = e.text.strip()
    return entries


def render(entries: list[ModEntry]) -> str:
    """The mods log's text."""
    lines = [TITLE, "", INTRO, ""]
    for e in entries:
        edited = f" · edited {e.edited}" if e.edited else ""
        lines += [f"## {e.id} · {e.at} · {e.area} · {'done ' + e.done if e.done else 'open'}{edited}", "", e.text, ""]
    return "\n".join(lines)


def add_entry(fs: SafeFS, data_root: Path, area: str, text: str, at: datetime) -> ModEntry:
    """Add an entry to the end of the log. Returns it, with its new ID."""
    text = text.strip()
    if not text:
        raise ValueError("Type the change you want first.")
    if area not in AREAS:
        raise ValueError(f"Unknown area {area!r}.")
    entries = read_log(data_root)
    number = max((int(e.id[1:]) for e in entries), default=0) + 1
    entry = ModEntry(f"M{number:04d}", at.strftime("%Y-%m-%d %H:%M"), area, text)
    fs.write_text(data_root / MODS_FILE, render([*entries, entry]))
    return entry


def _find(entries: list[ModEntry], mod_id: str) -> ModEntry:
    entry = next((e for e in entries if e.id == mod_id), None)
    if entry is None:
        raise ValueError(f"There's no mods log entry {mod_id}.")
    return entry


def mark_done(fs: SafeFS, data_root: Path, mod_id: str, day: date) -> None:
    """Mark an entry done, with the day."""
    entries = read_log(data_root)
    _find(entries, mod_id).done = day.isoformat()
    fs.write_text(data_root / MODS_FILE, render(entries))


def edit_entry(fs: SafeFS, data_root: Path, mod_id: str, area: str, text: str, day: date) -> ModEntry:
    """Replace an entry's note and area (mods log round 2, M0047), keeping its ID and time, and note the day it was
    edited. Returns it. Nothing changes when the note and area are as they were."""
    text = text.strip()
    if not text:
        raise ValueError("Type the change you want first.")
    if area not in AREAS:
        raise ValueError(f"Unknown area {area!r}.")
    entries = read_log(data_root)
    entry = _find(entries, mod_id)
    if (entry.text, entry.area) != (text, area):
        entry.text, entry.area, entry.edited = text, area, day.isoformat()
        fs.write_text(data_root / MODS_FILE, render(entries))
    return entry


def log_text(data_root: Path, open_only: bool = False) -> str:
    """The log as Markdown: the whole of it, for Copy all, or only the entries not marked done, for Copy open (mods log
    round 4, M0066). Either way under the log's title and intro, each entry's heading as the file has it."""
    entries = read_log(data_root)
    return render([e for e in entries if not e.done] if open_only else entries)
