"""Open (release 5.35; the task overview design's decision 158): what DocRepo may do when the owner opens a file from
the Task view.

- A **tracked original** or a **saved copy** opens in its own program, through Windows' "open", but only when its type
  is on the allow-list of documents below: never a macro-enabled file, a program, a script or a shortcut.
- An **email attachment** isn't opened, keeping the hard rule against launching attachments: it's shown in File
  Explorer, where Windows' own protections apply. One saved to the repo opens as its saved copy.
- An **email** (its ``.msg``, kept in its capture's folder) opens in Outlook, which shows it read-only.
- A **link** is copied, never opened or fetched (release 5.4).

Starting the program is the caller's (``start``): the window runs it on a worker thread, so a slow LAN drive never
freezes it, and says so if the file isn't there.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from docrepo.overview import Record

#: The document types Open may start: Word, Excel, PowerPoint, PDF, Visio, text, CSV, OpenDocument, pictures and emails.
OPENABLE = frozenset({
    ".docx", ".doc", ".rtf", ".odt", ".txt", ".md",
    ".xlsx", ".xls", ".xlsb", ".csv", ".ods",
    ".pptx", ".ppt", ".odp",
    ".pdf", ".vsdx", ".vsd",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
    ".msg",
})


@dataclass(frozen=True)
class Plan:
    """What Open does with a record: "open" a path, "show" it in File Explorer, or "copy_link"; and why, in words, when
    it isn't opened."""

    action: str
    path: str
    reason: str = ""


def openable(path: str) -> bool:
    return Path(path).suffix.lower() in OPENABLE


def plan(r: Record, email_file: Callable[[Record], str] = lambda r: "") -> Plan:
    """What Open does with a record (a file or an email)."""
    if r.kind == "email":
        msg = email_file(r)
        return Plan("open", msg) if msg else Plan("capture", r.capture, "Its .msg file isn't in its capture's folder, so its capture opens.")
    if r.type == "link":
        return Plan("copy_link", r.path, "DocRepo never opens links: it copies them, for your browser.")
    if r.source == "Email attachment":
        if r.copy and openable(r.copy):
            return Plan("open", r.copy)
        return Plan("show", r.path, "Email attachments are shown in File Explorer, not opened from DocRepo. Save it to the repo to open it here.")
    path = r.path or r.copy
    if not openable(path):
        ext = Path(path).suffix.lower() or "no extension"
        return Plan("show", path, f"DocRepo opens documents only, and a {ext} file isn't one, so it's shown in File Explorer.")
    return Plan("open", path)


def start_own_file(path: Path, starter: Callable[[str], None] | None = None) -> str | None:
    """Open wheels config (release 5.41): DocRepo's own settings file for the wheels, ``Config\\wheels.jsonc`` in the data
    root, in the program Windows has for it. Only that file: returns what went wrong, in words, or None when it started."""
    if path.name != "wheels.jsonc" or path.parent.name != "Config":
        return f"{path.name} isn't the wheels' config."
    try:
        (starter or os.startfile)(str(path))  # noqa: S606 - Windows' "open", for this one file of DocRepo's own
    except OSError as e:
        return f"Windows has no program for it ({type(e).__name__})."
    return None


def start(path: str, starter: Callable[[str], None] | None = None, exists: Callable[[Path], bool] = Path.exists) -> str | None:
    """Start a file in its own program. Returns None when it started, else what went wrong, in words. Run it off the UI
    thread: on a LAN drive, finding the file can take seconds."""
    target = Path(path)
    if not openable(path):
        return f"{target.name} isn't a document DocRepo opens."
    try:
        if not exists(target):
            return f"{target.name} isn't at {folder_of(path)} any more."
        (starter or os.startfile)(str(target))  # noqa: S606 - Windows' "open", for documents on the allow-list only
    except OSError as e:
        return f"{target.name} couldn't be opened ({type(e).__name__})."
    return None


def folder_of(path: str) -> str:
    """The folder a file is in, as words say it: without a share root's trailing backslash."""
    return str(Path(path).parent).rstrip("\\/")


def copy_text(paths: list[str]) -> str:
    """Paths for the clipboard, one a line, each quoted when it has a space (as File Explorer's Copy as path does)."""
    return "\n".join(f'"{p}"' if " " in p else p for p in paths)
