"""Made-up Outlook .msg files for the tests (release 5.33), laid out as MS-OXMSG says: a stream per variable-length
property, a properties stream for the fixed-size ones, and a storage per attachment. Classic Outlook isn't installed
on the personal computer, so these stand in for the emails it hands over in a drag."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pythoncom
from win32com import storagecon as sc

from docrepo import msg

_NEW = sc.STGM_READWRITE | sc.STGM_SHARE_EXCLUSIVE | sc.STGM_CREATE


@dataclass
class FakeAttachment:
    name: str
    data: bytes
    content_id: str = ""
    hidden: bool = False
    method: int = msg.ATTACH_BY_VALUE


@dataclass
class FakeEmail:
    subject: str = "Crane booking"
    sender: str = "Ann Example"
    to: str = "Owner Example; Sam Example"
    body: str = "The crane is booked for Tuesday.\r\nThe lift plan is at https://example.com/lift-plan."
    html: str | None = None
    sent: datetime = datetime(2026, 10, 7, 9, 15, tzinfo=timezone.utc)
    attachments: list[FakeAttachment] = field(default_factory=list)


def _filetime(moment: datetime) -> int:
    return int((moment - datetime(1601, 1, 1, tzinfo=timezone.utc)).total_seconds() * 10_000_000)


def _write(storage, pid: int, ptype: int, value: bytes) -> None:
    s = storage.CreateStream(f"__substg1.0_{pid:04X}{ptype:04X}", _NEW, 0, 0)
    s.Write(value)


def _properties(storage, header: int, fixed: list[tuple[int, int, bytes]]) -> None:
    table = b"\0" * header + b"".join(struct.pack("<II", (pid << 16) | ptype, 6) + value.ljust(8, b"\0") for pid, ptype, value in fixed)
    s = storage.CreateStream(msg.PROPERTIES, _NEW, 0, 0)
    s.Write(table)


def build(email: FakeEmail) -> bytes:
    """The email as a .msg's bytes."""
    lock = pythoncom.CreateILockBytesOnHGlobal(None, True)
    root = pythoncom.StgCreateDocfileOnILockBytes(lock, _NEW, 0)
    for pid, text in ((msg.SUBJECT, email.subject), (msg.SENDER_NAME, email.sender), (msg.DISPLAY_TO, email.to), (msg.BODY, email.body)):
        _write(root, pid, msg.PT_UNICODE, (text + "\0").encode("utf-16-le"))
    fixed = [(msg.CLIENT_SUBMIT_TIME, msg.PT_SYSTIME, struct.pack("<q", _filetime(email.sent)))]
    if email.html is not None:
        _write(root, msg.HTML, msg.PT_BINARY, email.html.encode("utf-8"))
        fixed.append((msg.INTERNET_CPID, msg.PT_LONG, struct.pack("<i", 65001)))
    _properties(root, msg.TOP_HEADER, fixed)
    for n, a in enumerate(email.attachments):
        sub = root.CreateStorage(f"{msg.ATTACHMENT}{n:08X}", _NEW, 0, 0)
        _write(sub, msg.ATTACH_LONG_FILENAME, msg.PT_UNICODE, (a.name + "\0").encode("utf-16-le"))
        if a.method == msg.ATTACH_BY_VALUE:
            _write(sub, msg.ATTACH_DATA, msg.PT_BINARY, a.data)
        if a.content_id:
            _write(sub, msg.ATTACH_CONTENT_ID, msg.PT_UNICODE, (a.content_id + "\0").encode("utf-16-le"))
        _properties(sub, msg.ATTACH_HEADER, [(msg.ATTACH_METHOD, msg.PT_LONG, struct.pack("<i", a.method)),
                                             (msg.ATTACHMENT_HIDDEN, msg.PT_BOOLEAN, struct.pack("<H", int(a.hidden)))])
        sub.Commit(0)
        del sub
    root.Commit(0)
    del root
    return lock.ReadAt(0, lock.Stat(0)[2])
