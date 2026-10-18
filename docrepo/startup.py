"""The Startup shortcut, so DocRepo starts when the owner signs in.

DocRepo writes only in its three places, and the owner's Startup folder isn't
one of them. So DocRepo makes the shortcut, ``DocRepo.lnk``, in
``%LOCALAPPDATA%\\DocRepo\\``, and the owner drags it into their Startup folder;
the Settings view opens both folders in File Explorer. DocRepo only reads the
Startup folder, to say whether the shortcut is there.

The shortcut runs ``pythonw.exe -m docrepo app`` from DocRepo's folder, so no
console window opens. It names no data root: DocRepo finds that in
``location.json``, as always. No admin rights, services, scheduled tasks or
registry changes are involved.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from docrepo.config import CODE_DIR, app_dir
from docrepo.safe_fs import SafeFS

SHORTCUT = "DocRepo.lnk"
_CSIDL_STARTUP = 0x0007


class StartupError(Exception):
    """The shortcut can't be made here."""


@dataclass(frozen=True)
class Shortcut:
    target: str
    arguments: str
    folder: str


def startup_folder() -> Path | None:
    """The owner's Startup folder, as Windows knows it (it may be redirected), or None if there isn't one."""
    if os.name != "nt":
        return None
    buffer = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, _CSIDL_STARTUP, None, 0, buffer) != 0:
        return None
    return Path(buffer.value)


def shortcut_path() -> Path:
    """Where DocRepo makes the shortcut: its own folder in %LOCALAPPDATA%."""
    return app_dir() / SHORTCUT


def wanted() -> Shortcut:
    """What the shortcut should run: this copy of DocRepo, with pythonw, from its own folder."""
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    return Shortcut(str(pythonw if pythonw.exists() else python), "-m docrepo app", str(CODE_DIR))


def _shell():
    try:
        import win32com.client  # pywin32, one of DocRepo's packages
    except ImportError as e:
        raise StartupError("Windows' shortcut support (pywin32) isn't installed.") from e
    return win32com.client.Dispatch("WScript.Shell")


def make_shortcut(fs: SafeFS) -> Path:
    """Make (or make again) DocRepo.lnk in DocRepo's own folder. Windows' shell writes it, to a path the guard has checked."""
    if os.name != "nt":
        raise StartupError("The Startup shortcut is for Windows.")
    path = fs.checked_path(shortcut_path())
    fs.makedirs(path.parent)
    want = wanted()
    link = _shell().CreateShortcut(str(path))
    link.TargetPath = want.target
    link.Arguments = want.arguments
    link.WorkingDirectory = want.folder
    link.Description = "Start DocRepo: the tray icon, the capture window's hotkey and the browse tool"
    link.Save()
    return path


def read_shortcut(path: Path) -> Shortcut:
    link = _shell().CreateShortcut(str(path))
    return Shortcut(link.TargetPath, link.Arguments, link.WorkingDirectory)


def status() -> str:
    """Whether DocRepo starts when the owner signs in, in a sentence for the Settings view."""
    folder = startup_folder()
    if folder is None:
        return "Windows has no Startup folder for you, so DocRepo can't start when you sign in."
    installed = folder / SHORTCUT
    if not installed.exists():
        return "DocRepo doesn't start when you sign in yet."
    try:
        found = read_shortcut(installed)
    except Exception:  # noqa: BLE001 - a shortcut Windows can't read is reported, not fatal
        return f"There's a {SHORTCUT} in your Startup folder, but it can't be read. Make the shortcut again and replace it."
    want = wanted()
    if os.path.normcase(found.target) != os.path.normcase(want.target) or os.path.normcase(found.folder) != os.path.normcase(want.folder):
        return (f"The {SHORTCUT} in your Startup folder starts DocRepo from another folder ({found.folder}). "
                "Make the shortcut again and replace it.")
    return "DocRepo starts when you sign in."
