"""Open (release 5.35; the task overview design's decision 158): what DocRepo may do when the owner opens a file from
the Task view.

- A **tracked original** or a **saved copy** opens in its own program, through Windows' "open", but only when its type
  is on the allow-list of documents below: never a macro-enabled file, a program, a script or a shortcut.
- An **email attachment** isn't opened, keeping the hard rule against launching attachments: it's shown in File
  Explorer, where Windows' own protections apply. One saved to the repo opens as its saved copy.
- An **email** (its ``.msg``, kept in its capture's folder) opens in Outlook, which shows it read-only.
- A **link** opens in the default browser, only on the owner's click (release 5.67, round 6's decision 314; until then
  it was only copied): ``start_link`` hands an http or https address to Windows' "open", as clicking a link in
  Outlook does. DocRepo never fetches it: the browser makes the connection, not DocRepo. Copy link stays beside it.
- A **folder** (release 5.66) opens in File Explorer, which is what showing it does.
- **File Explorer** (release 5.87, the review's F7) is started here too, and only here: ``show_in_explorer`` with a
  file selected, ``open_folder`` on a folder. Its arguments go as a list, never as one string, and never through a
  shell.

Starting the program is the caller's (``start``): the window runs it on a worker thread, so a slow LAN drive never
freezes it, and says so if the file isn't there.
"""
from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from docrepo.links import read_address
from docrepo.overview import Record

log = logging.getLogger(__name__)

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
        return Plan("open_link", r.path)
    if r.type == "folder":  # a folder (release 5.66) opens in File Explorer, which is what showing it does
        return Plan("show", r.path)
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


def start_link(address: str, starter: Callable[[str], None] | None = None) -> str | None:
    """Open a web link in the default browser (release 5.67, round 6's decision 314), on the owner's click only: Windows'
    "open" hands the address to the browser, as clicking a link in Outlook does, and the browser makes the connection.
    Only an http or https address that ``links.read_address`` keeps, with a host and no name or password in it. Returns
    None when it was handed over, else what went wrong, in words."""
    a = read_address(address or "", one=False)
    if a.kind != "link":
        return "DocRepo opens only web links (http or https)."
    parts = urlsplit(a.value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return "DocRepo opens only web links (http or https)."
    if parts.username or parts.password:
        return "That link has a name or password in it, so DocRepo won't open it. Copy it instead."
    try:
        (starter or os.startfile)(a.value)  # noqa: S606 - Windows' "open", for a checked web link only, on a click
    except OSError as e:
        return f"Windows couldn't hand the link to your browser ({type(e).__name__})."
    return None


def _start_explorer(args: Sequence[str]) -> None:
    """Start File Explorer with these arguments, as a list: no shell, and nothing but Explorer."""
    subprocess.Popen(["explorer", *args])  # noqa: S603, S607 - Explorer only, its arguments as a list, no shell


def open_folder(folder: Path, launcher: Callable[[Sequence[str]], None] | None = None) -> bool:
    """Open File Explorer on a folder. Only a full path: never a link, which Explorer would open in the browser."""
    target = Path(folder)
    if os.name != "nt" and launcher is None:
        return False
    if not target.is_absolute() or not target.is_dir():
        return False
    try:
        (launcher or _start_explorer)([str(target)])
    except OSError as e:
        log.warning("couldn't start File Explorer: %s", type(e).__name__)
        return False
    return True


def show_in_explorer(path: Path, launcher: Callable[[Sequence[str]], None] | None = None) -> bool:
    """Open File Explorer with ``path`` selected, or on the folder itself, or on the nearest folder above it that's there.
    Returns False when nothing was shown. DocRepo never opens or runs the file itself.

    ``/select,`` and the path are two arguments, which Python quotes as Windows expects (``explorer /select, "C:\\Docs\\Lift plan.pdf"``);
    a Windows path can't hold a quote."""
    target = Path(path)
    if os.name != "nt" and launcher is None:
        return False
    if not target.is_absolute():  # only a full path: never a link, which Explorer would open in the browser
        return False
    start = launcher or _start_explorer
    try:
        if target.is_dir():
            start([str(target)])
            return True
        if target.exists():
            start(["/select,", str(target)])
            return True
        folder = next((p for p in target.parents if p.is_dir()), None)
        if folder is not None:
            start([str(folder)])
    except OSError as e:
        log.warning("couldn't start File Explorer: %s", type(e).__name__)
    return False
