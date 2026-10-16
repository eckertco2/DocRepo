"""Pulling the plain text out of a file, for search and for the differences in document versions.

Files are only ever opened to read. The text is cut at ``extracted_text_cap_chars``
(settings.json). A file DocRepo can't read is still recorded; its status says why.
This isn't Extract, the later processing into the knowledge base.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

log = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".ini"}
#: What each kind of file is read with, for the help text and SPEC.
READERS = {".pdf": "pypdf", ".docx": "python-docx", ".pptx": "python-pptx", ".xlsx": "openpyxl", ".xlsm": "openpyxl", ".eml": "email"}


@dataclass(frozen=True)
class Extracted:
    """A file's text and how it went: ok, partial (cut at the limit), none (no text found or not a kind DocRepo reads) or error."""

    text: str
    status: str
    note: str = ""


@dataclass(frozen=True)
class FileInfo:
    size: int
    modified: str
    sha256: str


def file_info(path: Path) -> FileInfo:
    """A file's size, modified time and SHA-256, for noticing later that it changed."""
    stat = path.stat()
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return FileInfo(stat.st_size, datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), digest.hexdigest())


def decode(data: bytes) -> str:
    """Text from bytes: UTF-8 (with or without a BOM), UTF-16 with a BOM, or else Windows-1252."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def _docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts).strip()


def _pptx(path: Path) -> str:
    from pptx import Presentation

    parts = []
    for number, slide in enumerate(Presentation(str(path)).slides, 1):
        parts.append(f"Slide {number}")
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"Notes: {notes}")
    return "\n".join(p for p in parts if p).strip()


def _xlsx(path: Path, cap: int) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    size = 0
    try:
        for sheet in workbook.worksheets:
            parts.append(f"Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = ["" if v is None else str(v) for v in row]
                if any(values):
                    line = " | ".join(values).rstrip(" |")
                    parts.append(line)
                    size += len(line) + 1
                if size > cap:  # big sheets stop early; the text is cut at the cap anyway
                    return "\n".join(parts)
    finally:
        workbook.close()
    return "\n".join(parts).strip()


def _eml(path: Path) -> str:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    head = [f"{k}: {message[k]}" for k in ("From", "To", "Date", "Subject") if message[k]]
    body = message.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    return "\n".join(head) + "\n\n" + text.strip()


def extract_text(path: Path, cap: int) -> Extracted:
    """The plain text of a file, read-only. Never raises: a failure comes back with status "error"."""
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_SUFFIXES:
            text = decode(path.read_bytes())
        elif suffix == ".pdf":
            text = _pdf(path)
        elif suffix == ".docx":
            text = _docx(path)
        elif suffix == ".pptx":
            text = _pptx(path)
        elif suffix in (".xlsx", ".xlsm"):
            text = _xlsx(path, cap)
        elif suffix == ".eml":
            text = _eml(path)
        else:
            return Extracted("", "none", f"DocRepo doesn't read {suffix or 'extensionless'} files")
    except Exception as e:  # noqa: BLE001 - a bad file must never stop a save
        log.warning("Couldn't read the text of %s: %s", path.name, type(e).__name__)
        return Extracted("", "error", f"couldn't read it ({type(e).__name__})")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        note = "no text found; it may be a scanned document" if suffix == ".pdf" else "no text found"
        return Extracted("", "none", note)
    if len(text) > cap:
        return Extracted(text[:cap], "partial", f"cut at {cap} characters")
    return Extracted(text, "ok")


def to_unc(path: str) -> str:
    """A path on a mapped network drive (H:\\x) as its network path (\\\\server\\share\\x), so it survives drive-letter changes.

    Asks Windows which share the letter is mapped to; nothing is sent over the network.
    """
    drive = os.path.splitdrive(path)[0]
    if os.name != "nt" or len(drive) != 2 or drive[1] != ":":
        return path
    import ctypes
    from ctypes import wintypes

    if ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\") != 4:  # DRIVE_REMOTE
        return path
    buffer = ctypes.create_unicode_buffer(1024)
    length = wintypes.DWORD(len(buffer))
    if ctypes.windll.mpr.WNetGetConnectionW(drive, buffer, ctypes.byref(length)) != 0:
        return path
    return buffer.value.rstrip("\\") + path[2:]
