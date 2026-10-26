"""Outlook emails, from classic Outlook through COM (pywin32). Phase 3b: it can only be tested where Outlook runs.

DocRepo reads the emails selected in Outlook (the ones being dragged, or Add
selected Outlook email) and .msg files dropped from File Explorer. It reads
their subject, sender, recipients, time, plain-text and HTML bodies and attachments, and,
when the capture is saved, writes the email as email.msg and its attachments
into the capture's folder. It never sends, moves or changes an email.

Each field is read on its own, so a field Outlook refuses (its security guard
can refuse the sender, the recipients or the body) leaves only that field out.
Every problem is logged and kept for the troubleshooting report
(``docrepo/diagnose.py``) as a step and an error code, never as email content.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docrepo.save import Attachment, EmailItem

log = logging.getLogger(__name__)

OL_MAIL = 43  # olMail: a mail item, not a meeting request or a report
OL_MSG = 3  # olMSG: SaveAs as an Outlook .msg file
OL_BY_VALUE = 1  # an attached file, not a link or an embedded item
PR_ATTACHMENT_HIDDEN = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"
PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"  # how the HTML body shows a picture (cid:)
OUTLOOK_WINDOW_CLASS = "rctrl_renwnd32"  # the class of Outlook's main window

#: The well-known COM error codes, in words, for messages and the troubleshooting report.
HRESULTS = {
    0x80004004: "operation aborted (often Outlook's security guard refusing access)",
    0x80004005: "unspecified failure",
    0x800401E3: "Outlook isn't registered as running (GetActiveObject can't see it)",
    0x800401F3: "classic Outlook isn't installed (no Outlook.Application)",
    0x80080005: "server execution failed (often DocRepo and Outlook running at different privilege levels)",
    0x80010001: "call rejected by Outlook (it was busy, such as with a dialog open)",
    0x8001010A: "Outlook is busy (a dialog or prompt is open)",
    0x80070005: "access denied",
    0x80020009: "Outlook raised an error",
    0x800706BA: "Outlook isn't reachable (the RPC server is unavailable)",
    0x80040154: "Outlook's COM class isn't registered",
}


class OutlookError(Exception):
    """Outlook isn't there, or didn't give DocRepo the email. ``step`` and ``detail`` are for the troubleshooting report."""

    def __init__(self, message: str, step: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.step = step
        self.detail = detail


@dataclass(frozen=True)
class Problem:
    """One thing Outlook refused or failed at, as the troubleshooting report shows it."""

    at: str
    step: str
    detail: str


#: This session's Outlook problems, newest last, for the troubleshooting report.
PROBLEMS: deque[Problem] = deque(maxlen=20)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def describe(error: BaseException) -> str:
    """An exception in words safe to share: its kind, its COM error code and Outlook's own message, with any email
    address taken out. Never the email's content."""
    args = getattr(error, "args", ())
    code = args[0] if args and isinstance(args[0], int) else None
    parts = [type(error).__name__]
    if code is not None:
        code &= 0xFFFFFFFF
        parts.append(f"0x{code:08X}" + (f" ({HRESULTS[code]})" if code in HRESULTS else ""))
    # pywintypes.com_error: (hresult, text, excepinfo, argerror); excepinfo's third item is the source's own description.
    if len(args) >= 3 and isinstance(args[2], tuple) and len(args[2]) >= 3:
        inner = args[2]
        scode = inner[5] if len(inner) > 5 and isinstance(inner[5], int) else None
        if inner[2]:
            parts.append(f"Outlook says: {str(inner[2]).strip()[:200]}")
        if scode is not None and (scode & 0xFFFFFFFF) != code:
            s = scode & 0xFFFFFFFF
            parts.append(f"inner code 0x{s:08X}" + (f" ({HRESULTS[s]})" if s in HRESULTS else ""))
    elif len(args) >= 2 and isinstance(args[1], str):
        parts.append(args[1][:200])
    elif code is None and str(error):
        parts.append(str(error)[:200])
    return _EMAIL.sub("<email address>", parts[0] + (": " + "; ".join(parts[1:]) if parts[1:] else ""))


def record_problem(step: str, error: BaseException) -> str:
    """Log a problem and keep it for the troubleshooting report. Returns its description."""
    detail = describe(error)
    PROBLEMS.append(Problem(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), step, detail))
    log.warning("Outlook: %s failed: %s", step, detail)
    return detail


def outlook_window_open() -> bool:
    """Whether Outlook's main window is open, found by its window class without asking Outlook anything."""
    if os.name != "nt":
        return False
    return bool(ctypes.windll.user32.FindWindowW(OUTLOOK_WINDOW_CLASS, None))


def connect() -> tuple[object, str]:
    """The running Outlook, and how it was found. GetActiveObject first; Office registers itself late, so when that
    fails but Outlook's window is open, Dispatch joins the running Outlook (it never starts one: the window check
    comes first)."""
    try:
        import pythoncom  # noqa: F401 - pywin32's COM support; importing it starts COM on this thread
        import win32com.client
    except ImportError as e:
        raise OutlookError("pywin32 isn't installed, so DocRepo can't talk to Outlook.", "loading pywin32", describe(e)) from e
    try:
        return win32com.client.GetActiveObject("Outlook.Application"), "GetActiveObject"
    except Exception as e:  # noqa: BLE001 - COM raises its own errors
        first = record_problem("finding Outlook (GetActiveObject)", e)
    if not outlook_window_open():
        raise OutlookError("Outlook isn't open. Open classic Outlook, select the email, and try again.", "finding Outlook", first)
    try:
        return win32com.client.Dispatch("Outlook.Application"), "Dispatch"
    except Exception as e:  # noqa: BLE001
        detail = record_problem("joining Outlook (Dispatch)", e)
        raise OutlookError(f"DocRepo couldn't reach Outlook ({detail}). Settings → Troubleshooting report collects the details.",
                           "joining Outlook", detail) from e


def _when(value: object) -> str:
    try:
        return datetime(value.year, value.month, value.day, value.hour, value.minute).strftime("%Y-%m-%d %H:%M")  # type: ignore[attr-defined]
    except (AttributeError, ValueError, TypeError):
        return ""


def is_hidden(attachment: object) -> bool:
    """Whether Outlook hides the attachment from the email's list of attachments, as it does pictures in the body."""
    try:
        return bool(attachment.PropertyAccessor.GetProperty(PR_ATTACHMENT_HIDDEN))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - the property is often simply missing
        return False


def attachment_content_id(attachment: object) -> str:
    """The attachment's content ID, which a picture in the HTML body points to as cid:<ID>; "" when it has none."""
    try:
        value = attachment.PropertyAccessor.GetProperty(PR_ATTACH_CONTENT_ID)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - the property is missing on ordinary attachments
        return ""
    return value.strip() if isinstance(value, str) else ""


def attachment_size(attachment: object) -> int:
    try:
        return int(attachment.Size)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0


def read_field(item: object, name: str, refused: list[str]) -> object:
    """One property of an Outlook item, or None when Outlook refuses it; ``refused`` gains the field's name."""
    try:
        return getattr(item, name)
    except Exception as e:  # noqa: BLE001 - COM raises its own errors, and the security guard refuses with them
        record_problem(f"reading the email's {name}", e)
        refused.append(name)
        return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def email_from_item(item: object) -> EmailItem:
    """An Outlook mail item as DocRepo's EmailItem. Saving it later calls Outlook's SaveAs and SaveAsFile.
    A field Outlook refuses is left empty and named in ``refused``.

    Every attached file is read with its size, content ID and hidden flag, and the HTML body too, so email layer 0
    (``docrepo/layer0.py``) can tell attachments from pictures in the body and find the body's links. Embedded items,
    such as an attached email, are left out."""
    i = item  # the COM object; attributes are Outlook's
    refused: list[str] = []
    attachments = []
    found = read_field(i, "Attachments", refused)
    try:
        for n in range(1, (found.Count if found is not None else 0) + 1):  # type: ignore[attr-defined]
            a = found.Item(n)  # type: ignore[attr-defined]
            if a.Type == OL_BY_VALUE:
                attachments.append(Attachment(a.FileName, lambda path, a=a: a.SaveAsFile(str(path)), size=attachment_size(a),
                                              content_id=attachment_content_id(a), hidden=is_hidden(a)))
    except Exception as e:  # noqa: BLE001
        record_problem("reading the email's attachments", e)
        refused.append("Attachments")
    sent = read_field(i, "SentOn", [])  # a received email's SentOn; a draft has only ReceivedTime or neither
    body = read_field(i, "Body", refused)
    html = read_field(i, "HTMLBody", refused)
    return EmailItem(
        subject=_text(read_field(i, "Subject", refused)) or "(no subject)",
        sender=_text(read_field(i, "SenderName", refused)),
        sent=_when(sent) or _when(read_field(i, "ReceivedTime", [])),
        to=_text(read_field(i, "To", refused)),
        body=body.replace("\r\n", "\n").strip() if isinstance(body, str) else "",
        attachments=attachments,
        save_msg=lambda path: i.SaveAs(str(path), OL_MSG),  # type: ignore[attr-defined]
        refused=tuple(refused),
        html=html if isinstance(html, str) else "",
    )


def selected_emails() -> list[EmailItem]:
    """The emails selected in Outlook's main window. Other kinds of item (meetings, tasks) are left out."""
    outlook, _how = connect()
    step = "opening Outlook's main window (ActiveExplorer)"
    try:
        explorer = outlook.ActiveExplorer()  # type: ignore[attr-defined]
        if explorer is None:
            raise OutlookError("Outlook's main window isn't open. Open it, select the email, and try again.", step, "no explorer")
        step = "reading Outlook's selection"
        selection = explorer.Selection
        step = "reading the selected items"
        items = [selection.Item(n) for n in range(1, selection.Count + 1)]
        step = "reading the selected items' kinds"
        mails = [item for item in items if getattr(item, "Class", None) == OL_MAIL]
    except OutlookError:
        raise
    except Exception as e:  # noqa: BLE001
        detail = record_problem(step, e)
        raise OutlookError(f"Outlook didn't say which email is selected ({detail}). Click the email in Outlook and try again; "
                           "if it keeps failing, Settings → Troubleshooting report collects the details.", step, detail) from e
    if not mails:
        raise OutlookError("No email is selected in Outlook." if not items else "The selected item in Outlook isn't an email.",
                           "reading Outlook's selection", f"{len(items)} selected, none an email")
    emails = []
    for item in mails:
        try:
            emails.append(email_from_item(item))
        except Exception as e:  # noqa: BLE001 - anything not caught field by field
            detail = record_problem("reading the email", e)
            raise OutlookError(f"Outlook didn't give DocRepo the email ({detail}).", "reading the email", detail) from e
    log.info("Outlook: read %d selected email(s)%s", len(emails),
             "; refused " + ", ".join(sorted({f for e in emails for f in e.refused})) if any(e.refused for e in emails) else "")
    return emails


def open_msg_file(path: Path) -> EmailItem:
    """A .msg file dropped from File Explorer, read through Outlook."""
    outlook, _how = connect()
    try:
        item = outlook.Session.OpenSharedItem(str(path))  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        detail = record_problem("opening a .msg file (OpenSharedItem)", e)
        raise OutlookError(f"Outlook couldn't open {path.name} ({detail}).", "opening a .msg file", detail) from e
    try:
        return email_from_item(item)
    except Exception as e:  # noqa: BLE001
        detail = record_problem("reading a .msg file", e)
        raise OutlookError(f"Outlook didn't give DocRepo {path.name} ({detail}).", "reading a .msg file", detail) from e


def is_outlook_drop(formats: list[str]) -> bool:
    """True for what Outlook puts on a drag (its own RenPrivate formats): the email isn't a file yet, so it's read from
    Outlook's selection. FileGroupDescriptorW alone doesn't count: File Explorer puts it on every file it drags."""
    return any("RenPrivate" in f for f in formats)


#: An email's fields in words, for the line the capture window shows when Outlook holds them back.
FIELD_WORDS = {"Body": "text", "HTMLBody": "text", "SenderName": "sender", "To": "recipients", "Subject": "subject",
               "Attachments": "attachments"}


def refused_note(emails: list[EmailItem]) -> str:
    """A line for the capture window when Outlook held back some fields, or "": what's missing, why it usually is, and
    the way round it today (mods log round 3, M0063)."""
    fields = {f for e in emails for f in e.refused}
    if not fields:
        return ""
    words = list(dict.fromkeys(FIELD_WORDS.get(f, f) for f in sorted(fields, key=lambda f: list(FIELD_WORDS).index(f) if f in FIELD_WORDS else 99)))
    what = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    text_too = "text" in words
    return (f"Outlook didn't let DocRepo read the email's {what}, so {'it is' if len(words) == 1 else 'they are'} left out; the rest is kept. "
            "Outlook's security guard does this when it doesn't trust programs that ask. If Outlook asks whether to allow access, choose Allow. "
            + ("Otherwise, copy the email's text in Outlook (Ctrl+A, then Ctrl+C) and paste it into the content text. " if text_too else "")
            + "Settings → Troubleshooting report shows Outlook's security settings.")
