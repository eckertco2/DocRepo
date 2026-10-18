"""Backups: copies of docs.db and a mirror of the data root's files, in the backup folder.

A backup runs every ``backup_every_days`` (7 by default) at the app's first
start of the day, or when the owner asks (Back up now, or the ``backup``
command). In the backup folder:

- ``Database\\docs-1.db`` to ``docs-<backup_keep>.db``: copies of docs.db, made
  with SQLite's backup API, so they're whole even while DocRepo is writing.
  Each backup overwrites the oldest copy (or fills an empty slot).
- ``Files\\``: the data root's files as they are there (captures, saved copies,
  extracted text, the pages, the settings and the mods log). New and changed
  files are copied; nothing is ever removed, since DocRepo never deletes.
- ``backup-log.md``: one line per backup, and how to restore from it.

The data root's ``System`` folder (docs.db itself, the lock and the logs) isn't
mirrored. Backups write only in the backup folder, through a SafeFS that
allows nothing else, and never inside the data root.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from docrepo import db
from docrepo.config import Settings
from docrepo.dates import stamp
from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

DB_DIR = "Database"
FILES_DIR = "Files"
LOG_FILE = "backup-log.md"
STATE_KEY = "backup"
#: Top-level folders of the data root that aren't mirrored: docs.db is copied whole instead, and the rest is the app's own.
SKIP_DIRS = ("System",)
LOG_HEAD = """# DocRepo backups

Each line is one backup. `Database` holds the last copies of docs.db; the line says which one each backup wrote.
`Files` mirrors the data root's files. Nothing in it is ever removed.

To restore: quit DocRepo, make a new empty folder for the data root, copy everything in `Files` into it, make a
`System` folder there, copy the newest `Database\\docs-N.db` into it as `docs.db`, then run
`python -m docrepo set-data-root <the new folder>` and `python -m docrepo rebuild`.

"""


class BackupError(Exception):
    """A backup can't be made at all: no backup folder, or one inside the data root."""


@dataclass
class BackupResult:
    at: str
    folder: Path
    database: str = ""  # the database copy it wrote, such as docs-3.db
    copied: int = 0
    checked: int = 0
    problems: list[str] = field(default_factory=list)

    def message(self) -> str:
        text = (f"Backed up the database ({self.database}) and {self.copied} new or changed file{'s' if self.copied != 1 else ''} "
                f"of {self.checked}, in {self.folder}.")
        if self.problems:
            text += f" {len(self.problems)} problem{'s' if len(self.problems) > 1 else ''}: " + " ".join(self.problems[:3])
            text += " See backup-log.md." if len(self.problems) > 3 else ""
        return text


def _inside(path: Path, folder: Path) -> bool:
    p = os.path.normcase(os.path.realpath(path))
    f = os.path.normcase(os.path.realpath(folder)).rstrip("\\/")
    return p == f or p.startswith(f + os.sep)


def backup_folder(settings: Settings, data_root: Path) -> Path:
    """The backup folder, checked. Raises BackupError if there isn't a usable one."""
    if not settings.backup_dir:
        raise BackupError("No backup folder is set. Choose one in the browse tool's Settings.")
    folder = Path(settings.backup_dir)
    if not folder.is_absolute():
        raise BackupError(f"The backup folder {folder} isn't a full path.")
    if _inside(folder, data_root) or _inside(data_root, folder):
        raise BackupError("The backup folder can't be inside the data root, or hold it. Choose another in Settings.")
    return folder


def last_backup(conn: sqlite3.Connection) -> str | None:
    """When the last backup was made, as a stored time, or None."""
    return db.get_state(conn, STATE_KEY)


def is_due(conn: sqlite3.Connection, settings: Settings, now: datetime) -> bool:
    """True when a backup folder is set and the last backup is ``backup_every_days`` old or more."""
    if not settings.backup_dir:
        return False
    last = last_backup(conn)
    return last is None or (now.date() - datetime.fromisoformat(last).date()).days >= max(1, settings.backup_every_days)


def _slot(folder: Path, keep: int) -> Path:
    """The database copy to write: the first empty slot, else the oldest."""
    slots = [folder / DB_DIR / f"docs-{i}.db" for i in range(1, max(1, keep) + 1)]
    empty = [s for s in slots if not s.exists()]
    return empty[0] if empty else min(slots, key=lambda s: s.stat().st_mtime)


def run_backup(data_root: Path, settings: Settings, at: datetime) -> BackupResult:
    """Make a backup now. It opens docs.db on its own, so it can run on another thread than the app's."""
    folder = backup_folder(settings, data_root)
    fs = SafeFS([folder], replace_roots=[folder])  # this backup can write nowhere else
    result = BackupResult(stamp(at), folder)
    try:
        fs.makedirs(folder / DB_DIR)
    except OSError as e:
        raise BackupError(f"The backup folder {folder} can't be used ({type(e).__name__}). Is its drive there?") from e
    slot = _slot(folder, settings.backup_keep)
    tmp = fs.checked_path(slot.with_name(f".{slot.name}.tmp"))
    try:
        source = sqlite3.connect(f"file:{quote(db.db_path(data_root).as_posix(), safe='/:')}?mode=ro", uri=True)
        source.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as e:
        raise BackupError(f"docs.db can't be read, so nothing was backed up ({e}).") from e
    try:
        target = sqlite3.connect(tmp)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    fs.replace(tmp, slot)
    result.database = slot.name
    for here, dirs, files in os.walk(data_root):
        rel = Path(here).relative_to(data_root)
        if rel == Path("."):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.startswith(".") and name.endswith(".tmp"):
                continue  # a write that was under way
            src = Path(here) / name
            dst = folder / FILES_DIR / rel / name
            result.checked += 1
            try:
                st = src.stat()
                if dst.exists():
                    dt = dst.stat()
                    if dt.st_size == st.st_size and int(dt.st_mtime) == int(st.st_mtime):
                        continue
                fs.replace_file(src, dst)
                result.copied += 1
            except OSError as e:
                result.problems.append(f"{rel / name} wasn't copied ({type(e).__name__}).")
    _write_log(fs, folder, result)
    log.info("backup: %s, %d of %d files copied, %d problems", result.database, result.copied, result.checked, len(result.problems))
    return result


def _write_log(fs: SafeFS, folder: Path, result: BackupResult) -> None:
    path = folder / LOG_FILE
    try:
        old = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        old = LOG_HEAD
    line = (f"- {result.at[:16]} · database copy {result.database} · {result.copied} of {result.checked} files copied"
            + (f" · problems: {' '.join(result.problems)}" if result.problems else ""))
    fs.write_text(path, old.rstrip("\n") + "\n" + line + "\n")


def record(conn: sqlite3.Connection, result: BackupResult) -> None:
    """Note in docs.db that a backup was made, so the next one waits ``backup_every_days``."""
    db.set_state(conn, STATE_KEY, result.at)
