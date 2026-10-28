"""Outlook .msg files, read without Outlook (the knowledge base's phase 0, decisions 22 and 23; release 5.33).

A .msg file is a compound file (Microsoft's MS-OXMSG): each of the email's properties is a stream named for its tag
(``__substg1.0_0037001F`` is the subject, in UTF-16), the fixed-size ones (times, flags, numbers) sit in the
``__properties_version1.0`` stream, and each attachment is a storage of its own (``__attach_version1.0_#00000000``).
DocRepo reads them with pywin32's structured storage calls, from the bytes Outlook hands over in a drag
(``docrepo/ui/drop_target.py``) or from a .msg file dropped from File Explorer. Outlook isn't asked, so its security
guard never refuses anything, and nothing is opened, run or written here: the bytes are read in memory, as data.

What's read: the subject, sender, recipients, the time it was sent, the plain text and the HTML body (when the file has
one), and each attached file with its name, size, content ID and whether Outlook hides it, for email layer 0. An
attached email or object is left out, as Outlook's own route leaves it out. A field the file lacks is left empty.
"""
from __future__ import annotations

import codecs
import logging
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from docrepo.save import Attachment, EmailItem

log = logging.getLogger(__name__)

#: The first bytes of every compound file, a .msg among them.
SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
PROPERTIES = "__properties_version1.0"
ATTACHMENT = "__attach_version1.0_#"
_STREAM = re.compile(r"__substg1\.0_([0-9A-Fa-f]{4})([0-9A-Fa-f]{4})\Z")

# Property IDs (MS-OXPROPS) and types.
SUBJECT, SENDER_NAME, SENT_REPRESENTING_NAME, DISPLAY_TO = 0x0037, 0x0C1A, 0x0042, 0x0E04
CLIENT_SUBMIT_TIME, MESSAGE_DELIVERY_TIME, CREATION_TIME = 0x0039, 0x0E06, 0x3007
BODY, HTML, INTERNET_CPID, MESSAGE_CODEPAGE = 0x1000, 0x1013, 0x3FDE, 0x3FFD
ATTACH_DATA, ATTACH_LONG_FILENAME, ATTACH_FILENAME, DISPLAY_NAME = 0x3701, 0x3707, 0x3704, 0x3001
ATTACH_METHOD, ATTACH_SIZE, ATTACH_CONTENT_ID, ATTACHMENT_HIDDEN = 0x3705, 0x0E20, 0x3712, 0x7FFE
PT_LONG, PT_BOOLEAN, PT_I8, PT_STRING8, PT_UNICODE, PT_SYSTIME, PT_BINARY = 0x0003, 0x000B, 0x0014, 0x001E, 0x001F, 0x0040, 0x0102
ATTACH_BY_VALUE = 1
#: The fixed-size properties stream's header: 32 bytes for the email itself, 8 for an attachment.
TOP_HEADER, ATTACH_HEADER = 32, 8


class MsgError(Exception):
    """The bytes aren't a .msg DocRepo can read."""


def is_msg(data: bytes) -> bool:
    """Whether the bytes are a compound file, as a .msg is."""
    return data[:8] == SIGNATURE


@dataclass
class _Props:
    """One storage's properties: variable-length ones by ID, as text or bytes, and fixed-size ones by ID."""

    streams: dict[int, str | bytes]
    fixed: dict[int, int]


def _modes():
    from win32com import storagecon as sc
    return sc.STGM_READ | sc.STGM_SHARE_EXCLUSIVE, sc.STGTY_STREAM, sc.STGTY_STORAGE


def _open(data: bytes):
    """The bytes as a storage, in memory."""
    import pythoncom
    read, _, _ = _modes()
    lock = pythoncom.CreateILockBytesOnHGlobal(None, True)
    lock.WriteAt(0, data)
    return pythoncom.StgOpenStorageOnILockBytes(lock, None, read)


def _stream(storage, name: str) -> bytes:
    read, _, _ = _modes()
    s = storage.OpenStream(name, None, read, 0)
    size = s.Stat()[2]
    out = b""
    while len(out) < size:
        chunk = s.Read(min(1 << 20, size - len(out)))
        if not chunk:
            break
        out += chunk
    return out


def _text(raw: bytes, kind: int, codepage: int | None) -> str:
    if kind == PT_UNICODE:
        return raw.decode("utf-16-le", errors="replace").split("\0", 1)[0]
    return raw.decode(_codec(codepage) or "cp1252", errors="replace").split("\0", 1)[0]


def _codec(codepage: int | None) -> str | None:
    """A Windows code page as a Python codec name, or None for one Python doesn't know."""
    if not codepage:
        return None
    name = "utf-8" if codepage == 65001 else f"cp{codepage}"
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def _props(storage, header: int) -> _Props:
    """A storage's properties. Strings are text; binary stays bytes; fixed-size values are numbers."""
    _, is_stream, _ = _modes()
    raw: dict[int, tuple[int, bytes]] = {}
    fixed: dict[int, int] = {}
    for element in storage.EnumElements(0, None, 0):
        name, kind = element[0], element[1]
        if kind != is_stream:
            continue
        if name == PROPERTIES:
            table = _stream(storage, name)
            for at in range(header, len(table) - 15, 16):
                tag, _flags, value = struct.unpack_from("<II8s", table, at)
                pid, ptype = tag >> 16, tag & 0xFFFF
                if ptype == PT_LONG:
                    fixed[pid] = struct.unpack_from("<i", value)[0]
                elif ptype == PT_BOOLEAN:
                    fixed[pid] = int(struct.unpack_from("<H", value)[0] != 0)
                elif ptype in (PT_I8, PT_SYSTIME):
                    fixed[pid] = struct.unpack_from("<q", value)[0]
            continue
        m = _STREAM.match(name)
        if m:
            pid, ptype = int(m.group(1), 16), int(m.group(2), 16)
            if ptype in (PT_UNICODE, PT_STRING8, PT_BINARY):
                raw[pid] = (ptype, _stream(storage, name))
    codepage = fixed.get(MESSAGE_CODEPAGE)
    streams = {pid: _text(data, ptype, codepage) if ptype != PT_BINARY else data for pid, (ptype, data) in raw.items()}
    return _Props(streams, fixed)


def when(filetime: int | None) -> str:
    """A Windows FILETIME (100-nanosecond steps since 1601, in UTC) as this computer's local time, as DocRepo writes
    an email's time ("2026-10-07 09:15"), or "" for none."""
    if not filetime or filetime <= 0:
        return ""
    try:
        moment = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=filetime // 10)
        return moment.astimezone().strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def _html(props: _Props) -> str:
    value = props.streams.get(HTML)
    if isinstance(value, str):
        return value
    if not value:
        return ""
    for name in (_codec(props.fixed.get(INTERNET_CPID)), "utf-8"):
        if name:
            try:
                return value.decode(name)
            except UnicodeDecodeError:
                continue
    return value.decode("cp1252", errors="replace")


def _string(props: _Props, *pids: int) -> str:
    for pid in pids:
        value = props.streams.get(pid)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _attachments(storage) -> list[Attachment]:
    """The email's attached files, each with its bytes. An attached email or object (no binary data) is left out."""
    read, _, is_storage = _modes()
    out = []
    names = sorted(e[0] for e in storage.EnumElements(0, None, 0) if e[1] == is_storage and e[0].startswith(ATTACHMENT))
    for name in names:
        try:
            props = _props(storage.OpenStorage(name, None, read, None, 0), ATTACH_HEADER)
        except Exception as e:  # noqa: BLE001 - one unreadable attachment leaves the others
            log.warning("a .msg attachment couldn't be read: %s", type(e).__name__)
            continue
        data = props.streams.get(ATTACH_DATA)
        method = props.fixed.get(ATTACH_METHOD, ATTACH_BY_VALUE)
        if not isinstance(data, bytes) or method != ATTACH_BY_VALUE:
            continue
        filename = _string(props, ATTACH_LONG_FILENAME, ATTACH_FILENAME, DISPLAY_NAME) or f"attachment {len(out) + 1}"
        out.append(Attachment(filename, size=len(data), content_id=_string(props, ATTACH_CONTENT_ID),
                              hidden=bool(props.fixed.get(ATTACHMENT_HIDDEN)), data=data))
    return out


def read(data: bytes) -> EmailItem:
    """A .msg's bytes as DocRepo's EmailItem, keeping the bytes to save as the capture's .msg file. Raises MsgError."""
    if not is_msg(data):
        raise MsgError("It isn't an Outlook .msg file.")
    try:
        storage = _open(data)
        props = _props(storage, TOP_HEADER)
        attachments = _attachments(storage)
    except Exception as e:  # noqa: BLE001 - pywin32 raises its own errors for a damaged file
        raise MsgError(f"The .msg file couldn't be read ({type(e).__name__}).") from e
    body = _string(props, BODY)
    return EmailItem(
        subject=_string(props, SUBJECT) or "(no subject)",
        sender=_string(props, SENDER_NAME, SENT_REPRESENTING_NAME),
        sent=when(props.fixed.get(CLIENT_SUBMIT_TIME) or props.fixed.get(MESSAGE_DELIVERY_TIME) or props.fixed.get(CREATION_TIME)),
        to=_string(props, DISPLAY_TO),
        body=body.replace("\r\n", "\n").strip(),
        attachments=attachments,
        html=_html(props),
        msg_bytes=data,
    )
