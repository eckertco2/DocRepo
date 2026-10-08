"""The only module that writes, copies or moves files, or creates folders.

Every path is first resolved to its real location, following ``..``, symlinks and
junctions. A write is refused unless that location lies inside one of the allowed
roots: the data root, the backup folder and DocRepo's own folder in
``%LOCALAPPDATA%``. Paths that Windows treats specially (device paths, alternate
data streams, reserved names such as NUL) are refused before they're resolved.

There is deliberately no delete function. Every refusal is logged.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import NoReturn

log = logging.getLogger(__name__)

#: The only kinds of file ``write_text`` produces.
TEXT_SUFFIXES = frozenset({".md", ".json", ".txt", ".log"})

_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_FORBIDDEN_CHARS = re.compile(r'[<>"|?*\x00-\x1f]')

PathLike = str | os.PathLike[str]


class WriteRefused(PermissionError):
    """A write would land outside DocRepo's folders, or would break one of its file rules."""


def path_problem(raw: str) -> str | None:
    """Return why ``raw`` can't be used as a write target, or None if its shape is fine.

    This checks only the text of the path. Whether it lands inside an allowed
    root is checked after resolving it.
    """
    if raw.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        return "device and namespace paths aren't allowed"
    drive, rest = os.path.splitdrive(raw)
    if not drive or not rest.startswith(("\\", "/")):
        return "it isn't a full path"
    if ":" in rest:
        return "alternate data streams aren't allowed"
    for part in re.split(r"[\\/]+", rest):
        if part in ("", ".", ".."):
            continue
        if part != part.rstrip(". "):
            return f"the name {part!r} ends with a dot or a space"
        if _FORBIDDEN_CHARS.search(part):
            return f"the name {part!r} contains a character Windows doesn't allow"
        if part.split(".")[0].strip().upper() in _RESERVED_NAMES:
            return f"{part!r} is a name Windows reserves for devices"
    return None


def _is_within(path: Path, root: Path) -> bool:
    """True if ``path`` is ``root`` or lies inside it. Both must already be resolved."""
    p = os.path.normcase(str(path))
    r = os.path.normcase(str(root)).rstrip("\\/")
    return p == r or p.startswith(r + os.sep)


class SafeFS:
    """Writes files, but only inside the allowed roots."""

    def __init__(self, roots: Iterable[PathLike]) -> None:
        self._roots: list[Path] = []
        for root in roots:
            raw = os.fspath(root)
            problem = path_problem(raw)
            if problem:
                raise ValueError(f"Can't use {raw} as an allowed folder: {problem}.")
            self._roots.append(Path(os.path.abspath(raw)))
        if not self._roots:
            raise ValueError("SafeFS needs at least one allowed folder.")

    @property
    def roots(self) -> tuple[Path, ...]:
        """The allowed roots, as given (not resolved)."""
        return tuple(self._roots)

    def checked_path(self, path: PathLike) -> Path:
        """Return the real, absolute location of ``path``, or raise WriteRefused.

        Use this before handing a path to code that writes on its own, such as
        SQLite, the logging module or Outlook's SaveAs.
        """
        raw = os.fspath(path)
        problem = path_problem(raw)
        if problem:
            self._refuse(raw, problem)
        real = Path(os.path.realpath(raw))
        roots = [Path(os.path.realpath(r)) for r in self._roots]
        if not any(_is_within(real, root) for root in roots):
            self._refuse(raw, "it's outside DocRepo's folders")
        return real

    def makedirs(self, path: PathLike) -> Path:
        """Create a folder, and any missing parents, inside the allowed roots."""
        target = self.checked_path(path)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def write_text(self, path: PathLike, text: str) -> Path:
        """Write a Markdown, JSON, text or log file atomically, as UTF-8.

        The text goes to a temporary file in the same folder first, which then
        replaces the target in one step, so a crash never leaves half a file.
        """
        target = self.checked_path(path)
        if target.suffix.lower() not in TEXT_SUFFIXES:
            self._refuse(os.fspath(path), f"DocRepo doesn't write {target.suffix or 'extensionless'} files")
        self.makedirs(target.parent)
        fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            os.replace(tmp, target)
        except BaseException:
            # Removes only the temporary file this call just created.
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        return target

    def copy_file(self, src: PathLike, dst: PathLike) -> Path:
        """Copy a file the owner asked to keep. The source is only read.

        Never overwrites: replacing a filed copy means moving the old one to
        ``_old versions`` first.
        """
        target = self.checked_path(dst)
        if target.exists():
            raise FileExistsError(f"{target} already exists.")
        self.makedirs(target.parent)
        shutil.copy2(os.fspath(src), target)
        return target

    def move(self, src: PathLike, dst: PathLike) -> Path:
        """Move a file or folder from one place inside the allowed roots to another."""
        source = self.checked_path(src)
        target = self.checked_path(dst)
        if target.exists():
            raise FileExistsError(f"{target} already exists.")
        self.makedirs(target.parent)
        shutil.move(source, target)
        return target

    def _refuse(self, path: str, reason: str) -> NoReturn:
        log.warning("Write refused (%s): %s", reason, path)
        raise WriteRefused(f"Refused to write {path}: {reason}.")
