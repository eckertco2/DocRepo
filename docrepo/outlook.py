"""Outlook emails, from classic Outlook through COM (pywin32). Phase 3b: it can only be tested where Outlook runs.

DocRepo reads the emails selected in Outlook (the ones being dragged, or Add
selected Outlook email) and .msg files dropped from File Explorer. It reads
their subject, sender, recipients, time, plain-text body and attachments, and,
when the capture is saved, writes the email as email.msg and its attachments
into the capture's folder. It never sends, moves or changes an email.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from docrepo.save import Attachment, EmailItem

log = logging.getLogger(__name__)

OL_MAIL = 43  # olMail: a mail item, not a meeting request or a report
OL_MSG = 3  # olMSG: SaveAs as an Outlook .msg file
OL_BY_VALUE = 1  # an attached file, not a link or an embedded item
PR_ATTACHMENT_HIDDEN = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"


class OutlookError(Exception):
    """Outlook isn't there, or didn't give DocRepo the email."""


def _outlook():
    try:
        import win32com.client
    except ImportError as e:
        raise OutlookError("pywin32 isn't installed, so DocRepo can't talk to Outlook.") from e
    try:
        return win32com.client.GetActiveObject("Outlook.Application")
    except Exception as e:  # noqa: BLE001 - COM raises its own errors
        raise OutlookError("Outlook isn't open. Open classic Outlook, select the email, and try again.") from e


def _when(value: object) -> str:
    try:
        return datetime(value.year, value.month, value.day, value.hour, value.minute).strftime("%Y-%m-%d %H:%M")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        return ""


def _hidden(attachment: object) -> bool:
    """Pictures in a signature come as hidden attachments; they're left out."""
    try:
        return bool(attachment.PropertyAccessor.GetProperty(PR_ATTACHMENT_HIDDEN))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - the property is often simply missing
        return False


def email_from_item(item: object) -> EmailItem:
    """An Outlook mail item as DocRepo's EmailItem. Saving it later calls Outlook's SaveAs and SaveAsFile."""
    i = item  # the COM object; attributes are Outlook's
    attachments = []
    for n in range(1, i.Attachments.Count + 1):  # type: ignore[attr-defined]
        a = i.Attachments.Item(n)  # type: ignore[attr-defined]
        if a.Type == OL_BY_VALUE and not _hidden(a):
            attachments.append(Attachment(a.FileName, lambda path, a=a: a.SaveAsFile(str(path))))
    return EmailItem(
        subject=(i.Subject or "(no subject)").strip(),  # type: ignore[attr-defined]
        sender=(i.SenderName or "").strip(),  # type: ignore[attr-defined]
        sent=_when(getattr(i, "SentOn", None) or getattr(i, "ReceivedTime", None)),
        to=(i.To or "").strip(),  # type: ignore[attr-defined]
        body=(i.Body or "").replace("\r\n", "\n").strip(),  # type: ignore[attr-defined]
        attachments=attachments,
        save_msg=lambda path: i.SaveAs(str(path), OL_MSG),  # type: ignore[attr-defined]
    )


def selected_emails() -> list[EmailItem]:
    """The emails selected in Outlook's main window. Other kinds of item (meetings, tasks) are left out."""
    outlook = _outlook()
    try:
        selection = outlook.ActiveExplorer().Selection
        items = [selection.Item(n) for n in range(1, selection.Count + 1)]
    except Exception as e:  # noqa: BLE001
        raise OutlookError("Outlook didn't say which email is selected. Click the email in Outlook, then try again.") from e
    emails = [email_from_item(item) for item in items if getattr(item, "Class", None) == OL_MAIL]
    if not emails:
        raise OutlookError("No email is selected in Outlook.")
    log.info("Outlook: read %d selected email(s)", len(emails))
    return emails


def open_msg_file(path: Path) -> EmailItem:
    """A .msg file dropped from File Explorer, read through Outlook."""
    outlook = _outlook()
    try:
        return email_from_item(outlook.Session.OpenSharedItem(str(path)))
    except Exception as e:  # noqa: BLE001
        raise OutlookError(f"Outlook couldn't open {path.name}.") from e


def is_outlook_drop(formats: list[str]) -> bool:
    """True for what Outlook puts on a drag (its own RenPrivate formats): the email isn't a file yet, so it's read from
    Outlook's selection. FileGroupDescriptorW alone doesn't count: File Explorer puts it on every file it drags."""
    return any("RenPrivate" in f for f in formats)
