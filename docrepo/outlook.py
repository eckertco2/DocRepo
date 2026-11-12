"""Outlook emails, from classic Outlook through COM (pywin32). Phase 3b: it can only be tested where Outlook runs.

DocRepo reads the email selected in Outlook (Add selected Outlook email, its
hotkey, and a drag that DocRepo's own drop target couldn't take). Since release
5.33.1 it copies the email whole first (``copy_whole``): attached to a new email
that's never saved or sent, and that attachment saved as a .msg file, which
Outlook's security guard allows, as it allows any attachment's. The .msg is read
without Outlook (``docrepo/msg.py``), as a dragged email or a dropped .msg file
is (release 5.33). Only when that fails is the email read field by field, as
before, which the guard can refuse; then, when the capture is saved, Outlook's
SaveAs writes its .msg file (email.msg, then email 2.msg and so on) and its
attachments into the capture's folder.

It never sends, moves or deletes an email. With Settings' "Mark filed emails in
Outlook" on (release 5.33, the knowledge base's decisions 24 to 26), it adds the
task's name to each email it files as a category (``mark_filed``), and changes
nothing else on it. Since release 5.33.1 (decision 26 as the owner changed it),
it also adds that category to Outlook's list of categories, in the colour chosen
in Settings, when it isn't there yet, so it shows; a category already on the
list keeps its colour, and the colour None leaves the list alone.

On the owner's click (the knowledge base's stage K8, release B, as release
5.105) it makes a T-mail: a new email (``new_t_mail``), or a Reply all to an
email the owner filed (``reply_all``), and opens it for the owner to write and
send. A new email Outlook gives no conversation index is saved to Drafts first,
as Outlook's AutoSave would, and if it still has none, DocRepo gives it one in
MS-OXOMSG's shape (KB decision 39). It never sends one. Since release 5.125
Ask for an update (``ask_t_mail``) makes a new T-mail with its To, Subject and
words filled in: it writes those fields, shows the email so Outlook adds the
owner's signature, puts the words before it, and still never sends it.

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from docrepo.layer0 import Part
from docrepo.save import Attachment, EmailItem, FileRow

if TYPE_CHECKING:
    from docrepo.model import Model
    from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

OL_MAIL = 43  # olMail: a mail item, not a meeting request or a report
OL_MAIL_ITEM, OL_EMBEDDED_ITEM, OL_DISCARD = 0, 5, 1  # CreateItem's olMailItem, an attached Outlook item, Close without saving
OL_MSG = 3  # olMSG: SaveAs as an Outlook .msg file
OL_BY_VALUE = 1  # an attached file, not a link or an embedded item
PR_ATTACHMENT_HIDDEN = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"
PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"  # how the HTML body shows a picture (cid:)
#: An email's Message-ID, In-Reply-To and References, its transport headers, and its conversation index tracking flag,
#: through PropertyAccessor (the knowledge base's stage K8, release 5.101).
PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
PR_IN_REPLY_TO_ID = "http://schemas.microsoft.com/mapi/proptag/0x1042001F"
PR_INTERNET_REFERENCES = "http://schemas.microsoft.com/mapi/proptag/0x1039001F"
PR_TRANSPORT_MESSAGE_HEADERS = "http://schemas.microsoft.com/mapi/proptag/0x007D001F"
PR_CONVERSATION_INDEX_TRACKING = "http://schemas.microsoft.com/mapi/proptag/0x3016000B"
PR_CONVERSATION_INDEX = "http://schemas.microsoft.com/mapi/proptag/0x00710102"  # binary: written only on a new T-mail with none
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
    entry_id, store_id = where_kept(i)
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
        entry_id=entry_id,
        store_id=store_id,
        **item_identifiers(i)[0],
    )


def _prop(item: object, tag: str) -> object:
    return item.PropertyAccessor.GetProperty(tag)  # type: ignore[attr-defined]


def item_identifiers(item: object) -> tuple[dict[str, object], dict[str, str]]:
    """An Outlook item's identifiers, as ``EmailItem`` holds them (release 5.101), and how each was got, for the
    troubleshooting report: "field", "PropertyAccessor", "transport headers", or "refused" or "none". Each is read on its
    own, and a refusal leaves only that one out; the guard doesn't cover the conversation's fields."""
    from docrepo import conversations, msg

    out: dict[str, object] = {}
    how: dict[str, str] = {}
    for name, field_name in (("conversation_index", "ConversationIndex"), ("conversation_id", "ConversationID"),
                             ("conversation_topic", "ConversationTopic")):
        try:
            value = getattr(item, field_name)
        except AttributeError:  # an item that has no such field: nothing to say
            out[name], how[name] = "", "none"
            continue
        except Exception as e:  # noqa: BLE001 - COM raises its own errors
            record_problem(f"reading the email's {field_name}", e)
            out[name], how[name] = "", "refused"
            continue
        text = value.strip() if isinstance(value, str) else ""
        out[name] = conversations.clean_hex(text) if name != "conversation_topic" else text
        how[name] = "field" if out[name] else "none"
    try:
        out["conversation_tracking"] = bool(_prop(item, PR_CONVERSATION_INDEX_TRACKING))
        how["conversation_tracking"] = "PropertyAccessor"
    except Exception:  # noqa: BLE001 - often simply not set
        out["conversation_tracking"], how["conversation_tracking"] = None, "none"
    headers: tuple[str, str, str] | None = None
    for n, (name, tag) in enumerate((("message_id", PR_INTERNET_MESSAGE_ID), ("in_reply_to", PR_IN_REPLY_TO_ID),
                                     ("refs", PR_INTERNET_REFERENCES))):
        try:
            value = _prop(item, tag)
            text = " ".join(value.split()) if isinstance(value, str) else ""
        except Exception:  # noqa: BLE001 - missing on many emails, or refused
            text = ""
        if text:
            out[name], how[name] = text, "PropertyAccessor"
            continue
        if headers is None:
            try:
                raw = _prop(item, PR_TRANSPORT_MESSAGE_HEADERS)
                headers = msg.header_ids(raw if isinstance(raw, str) else "")
            except Exception:  # noqa: BLE001 - a sent or draft email has no transport headers
                headers = ("", "", "")
        out[name] = headers[n]
        how[name] = "transport headers" if headers[n] else "none"
    return out, how


def where_kept(item: object) -> tuple[str, str]:
    """Where Outlook keeps an item: its EntryID and its folder's StoreID ("" for one Outlook won't give). The security
    guard doesn't cover them (release 5.33)."""
    out = []
    for read in (lambda: item.EntryID, lambda: item.Parent.StoreID):  # type: ignore[attr-defined]
        try:
            value = read()
        except Exception:  # noqa: BLE001
            value = ""
        out.append(value if isinstance(value, str) else "")
    return out[0], out[1]


#: DocRepo's one file for the email Outlook copies whole for Add selected Outlook email (release 5.33.1), in the data
#: root's System folder. Outlook replaces it each time.
COPY_FILE = Path("System") / "outlook-email.msg"


def copy_path(fs: SafeFS, data_root: Path) -> Path | None:
    """Where Outlook writes the email it copies whole, checked as inside the data root; None if it can't be."""
    try:
        target = fs.checked_path(data_root / COPY_FILE)
        fs.makedirs(target.parent)
        return target
    except OSError:
        return None


def copy_whole(app: object, item: object, scratch: Path) -> EmailItem:
    """The email, whole, as Outlook's own .msg copy (release 5.33.1): attached to a new email that's never saved or sent,
    and that attachment saved at ``scratch`` (Attachment.SaveAsFile, which the guard allows), then read without Outlook.
    The new email is closed without saving. ``scratch`` is DocRepo's one file for this, which Outlook replaces each time."""
    from docrepo import msg

    draft = app.CreateItem(OL_MAIL_ITEM)  # type: ignore[attr-defined]
    try:
        draft.Attachments.Add(item, OL_EMBEDDED_ITEM).SaveAsFile(str(scratch))
    finally:
        try:
            draft.Close(OL_DISCARD)
        except Exception:  # noqa: BLE001, S110 - never saved, so nothing is left behind either way
            pass
    email = msg.read(scratch.read_bytes())
    email.entry_id, email.store_id = where_kept(item)
    return email


# ---- T-mails (the knowledge base's stage K8, release B, as release 5.105) ----
@dataclass(frozen=True)
class Opened:
    """A T-mail Outlook opened: its whole conversation index as hex ("" when Outlook gave none), and how DocRepo got it.
    A new email's: "made" (Outlook gave one at once), "saved" (once saved to Drafts) or "written" (DocRepo gave it one,
    KB decision 39). A reply's route to the original: "place" (where Outlook keeps it) or "msg" (its saved .msg)."""

    index: str
    how: str


def index_of(item: object) -> str:
    """An item's conversation index as hex: its ConversationIndex field, else the property itself. "" for none."""
    from docrepo import conversations

    try:
        found = conversations.clean_hex(getattr(item, "ConversationIndex", ""))
    except Exception:  # noqa: BLE001 - COM raises its own errors
        found = ""
    if conversations.key(found):
        return found
    try:
        return conversations.clean_hex(_prop(item, PR_CONVERSATION_INDEX))
    except Exception:  # noqa: BLE001 - not there yet
        return found


def _close_unsaved(item: object) -> None:
    try:
        item.Close(OL_DISCARD)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001, S110 - never saved, so nothing is left behind either way
        pass


def give_index(item: object, now: datetime) -> str:
    """Write a new conversation's index on an email that has none (KB decision 39), with the conversation index tracking
    flag on so Outlook's ConversationID is the same GUID, and read it back. Returns the index the email now has."""
    from docrepo import conversations

    written = conversations.new_index(now)
    accessor = item.PropertyAccessor  # type: ignore[attr-defined]
    accessor.SetProperty(PR_CONVERSATION_INDEX, accessor.StringToBinary(written))
    try:
        accessor.SetProperty(PR_CONVERSATION_INDEX_TRACKING, True)
    except Exception as e:  # noqa: BLE001 - the index is what counts; the flag only makes Outlook's ID agree with it
        record_problem("setting the new email's conversation index tracking flag", e)
    back = index_of(item)
    return back if conversations.key(back) else written


def new_t_mail(now: datetime) -> Opened:
    """Make a new email and open it for the owner (New T-mail, KB decisions 35, 36 and 39): empty, no subject and no To,
    tagged only by its conversation index. Outlook gives a new email none when it's made (check C1), so DocRepo saves it
    to Drafts, as AutoSave would, and reads it then; if it still has none, DocRepo writes one. Never sent."""
    from docrepo import conversations

    app, _how = connect()
    try:
        item = app.CreateItem(OL_MAIL_ITEM)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        detail = record_problem("making a new email (CreateItem)", e)
        raise OutlookError(f"Outlook didn't make a new email ({detail}).", "making a new email", detail) from e
    index, how = index_of(item), "made"
    if not conversations.key(index):
        try:
            item.Save()
            index, how = index_of(item), "saved"
        except Exception as e:  # noqa: BLE001 - then DocRepo gives it one
            record_problem("saving the new email to Drafts", e)
    if not conversations.key(index):
        try:
            index, how = give_index(item, now), "written"
        except Exception as e:  # noqa: BLE001 - it's still opened, untagged, and the owner is told
            record_problem("giving the new email a conversation index", e)
            index, how = "", "none"
    try:
        item.Display()
    except Exception as e:  # noqa: BLE001
        detail = record_problem("opening the new email (Display)", e)
        if how != "saved":
            _close_unsaved(item)
        raise OutlookError(f"Outlook didn't open the new email ({detail}).", "opening the new email", detail) from e
    log.info("Outlook: opened a new T-mail, its conversation index %s", how)
    return Opened(index if conversations.key(index) else "", how)


# ---- Ask for an update (release 5.125, the cold-eyes plan's decisions 481 to 487) ----
OL_FORMAT_PLAIN = 1  # olFormatPlain: a plain-text email
_WORD_SECTION = re.compile(r"<div\b[^>]*\bclass=\"?WordSection1\"?[^>]*>", re.IGNORECASE)
_BODY_TAG = re.compile(r"<body\b[^>]*>", re.IGNORECASE)


@dataclass(frozen=True)
class AskOpened:
    """An ask Outlook opened: the T-mail (its conversation index and how it was had), whether To was filled, and how the
    words went in before the signature: "editor" (through Word, the email's editor), "html", "text", or "" when they
    couldn't be, for the owner to paste."""

    opened: Opened
    to_filled: bool
    words: str


def words_first_html(html: str, words: str) -> str:
    """An HTML body with the words put first, a paragraph a line in Outlook's own paragraph style, before what was there
    (the signature): just inside Word's section when there is one, else just inside the body."""
    from html import escape

    paras = "".join(f"<p class=MsoNormal>{escape(line) if line else '&nbsp;'}</p>" for line in words.split("\n"))
    at = _WORD_SECTION.search(html) or _BODY_TAG.search(html)
    return html[:at.end()] + paras + html[at.end():] if at else paras + html


def put_words_first(item: object, words: str) -> str:
    """Put the words before what Outlook wrote in a new email it's showing, its signature (decision 483): through Word,
    the email's editor, at the very start; else into the HTML body, or the text of a plain-text email. Returns how, or ""
    when nothing worked; each failure is kept for the troubleshooting report. Either way the email is only changed, never
    sent."""
    try:
        doc = item.GetInspector.WordEditor  # type: ignore[attr-defined]
        doc.Range(0, 0).InsertBefore(words.replace("\n", "\r") + "\r")
        return "editor"
    except Exception as e:  # noqa: BLE001 - COM raises its own errors; the body is next
        record_problem("putting the words in through the editor (WordEditor)", e)
    try:
        if item.BodyFormat == OL_FORMAT_PLAIN:  # type: ignore[attr-defined]
            item.Body = words.replace("\n", "\r\n") + "\r\n" + (item.Body or "")  # type: ignore[attr-defined]
            return "text"
        item.HTMLBody = words_first_html(item.HTMLBody or "", words)  # type: ignore[attr-defined]
        return "html"
    except Exception as e:  # noqa: BLE001 - the email stays open, for the owner to paste the words
        record_problem("putting the words in the body (HTMLBody)", e)
    return ""


def ask_t_mail(now: datetime, to: Sequence[str], subject: str, words: str) -> AskOpened:
    """Ask for an update: a new email with To, Subject and the words filled in, opened for the owner to change and send
    (decisions 482 to 486). Outlook writes the owner's signature when it shows a new email, so DocRepo shows it first and
    then puts the words before what Outlook wrote. Then it's tagged by its conversation as New T-mail's is: the index
    Outlook gives, else the one it has once saved to Drafts, else one DocRepo writes (KB decision 39). Filling To,
    Subject and the body only writes fields; DocRepo reads no address and never sends one."""
    from docrepo import conversations

    app, _how = connect()
    try:
        item = app.CreateItem(OL_MAIL_ITEM)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        detail = record_problem("making a new email (CreateItem)", e)
        raise OutlookError(f"Outlook didn't make a new email ({detail}).", "making a new email", detail) from e
    to_filled = False
    try:
        item.Subject = subject
        if to:
            item.To = "; ".join(to)
            to_filled = True
    except Exception as e:  # noqa: BLE001 - the owner fills what's missing
        record_problem("filling the new email's To and Subject", e)
    try:
        item.Display()
    except Exception as e:  # noqa: BLE001
        detail = record_problem("opening the new email (Display)", e)
        _close_unsaved(item)
        raise OutlookError(f"Outlook didn't open the new email ({detail}).", "opening the new email", detail) from e
    placed = put_words_first(item, words)
    index, how = index_of(item), "made"
    if not conversations.key(index):
        try:
            item.Save()
            index, how = index_of(item), "saved"
        except Exception as e:  # noqa: BLE001 - then DocRepo gives it one
            record_problem("saving the new email to Drafts", e)
    if not conversations.key(index):
        try:
            index, how = give_index(item, now), "written"
        except Exception as e:  # noqa: BLE001 - it's still open, untagged, and the owner is told
            record_problem("giving the new email a conversation index", e)
            index, how = "", "none"
    log.info("Outlook: opened an Ask for an update, To %s, the words %s, its conversation index %s",
             "filled" if to_filled else "empty", f"in by the {placed}" if placed else "not in", how)
    return AskOpened(Opened(index if conversations.key(index) else "", how), to_filled, placed)


def reply_all(entry_id: str, store_id: str, saved: Path | None) -> Opened:
    """Reply all to a captured email and open the reply for the owner (KB decisions 37 and 38): found by its place in
    Outlook (EntryID and StoreID, kept since release 5.93), else from its saved .msg, which Outlook opens without changing
    it (C4 showed the reply keeps the conversation that way). The reply is Outlook's own, in the same conversation. Never
    sent."""
    app, _how = connect()
    session = app.Session  # type: ignore[attr-defined]
    original, route = None, ""
    if entry_id:
        try:
            original = session.GetItemFromID(entry_id, store_id) if store_id else session.GetItemFromID(entry_id)
            route = "place"
        except Exception as e:  # noqa: BLE001 - moved to another mailbox or deleted: the .msg route is next
            record_problem("finding the email in Outlook (GetItemFromID)", e)
    if original is None and saved is not None and saved.is_file():
        try:
            original, route = session.OpenSharedItem(str(saved)), "msg"
        except Exception as e:  # noqa: BLE001
            detail = record_problem("opening the saved email (OpenSharedItem)", e)
            raise OutlookError(f"Outlook couldn't open the saved email ({detail}).", "opening the saved email", detail) from e
    if original is None:
        raise OutlookError("DocRepo couldn't find the email in Outlook, and its saved .msg isn't there.", "finding the email", "no place, no .msg")
    reply = None
    try:
        reply = original.ReplyAll()  # type: ignore[attr-defined]
        index = index_of(reply)
        reply.Display()
    except Exception as e:  # noqa: BLE001
        if reply is not None:
            _close_unsaved(reply)
        detail = record_problem("making the reply (ReplyAll)", e)
        raise OutlookError(f"Outlook didn't make the reply ({detail}).", "making the reply", detail) from e
    finally:
        if route == "msg":
            _close_unsaved(original)  # the saved .msg, opened only to reply to it: closed without saving, so it's unchanged
    log.info("Outlook: opened a Reply all T-mail, the original found by its %s", "place in Outlook" if route == "place" else "saved .msg")
    return Opened(index, route)


def show_email(entry_id: str, store_id: str) -> bool:
    """Open a captured email in Outlook, in its own window, found by its place (EntryID and StoreID, kept since release
    5.93): a conversation page's Open in Outlook (release 5.122, the email section plan's decision 460). It only shows the
    email; nothing in it changes. False when Outlook can't find it there (moved to another mailbox, deleted, or captured
    before its place was kept), for the caller to open its saved .msg instead."""
    if not entry_id:
        return False
    app, _how = connect()
    session = app.Session  # type: ignore[attr-defined]
    try:
        item = session.GetItemFromID(entry_id, store_id) if store_id else session.GetItemFromID(entry_id)
    except Exception as e:  # noqa: BLE001 - COM raises its own errors; the .msg is next
        record_problem("finding the email in Outlook (GetItemFromID)", e)
        return False
    try:
        item.Display()  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        detail = record_problem("showing the email (Display)", e)
        raise OutlookError(f"Outlook found the email but didn't show it ({detail}).", "showing the email", detail) from e
    log.info("Outlook: showed a captured email, found by its place")
    return True


def selected_emails(scratch: Path | None = None) -> list[EmailItem]:
    """The emails selected in Outlook's main window. Other kinds of item (meetings, tasks) are left out. With ``scratch``
    (a path in the data root), each is copied whole first (``copy_whole``); one that can't be is read field by field."""
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
        mails = _conversation_mails(selection)  # a conversation's header selected, rather than an email
    if not mails:
        raise OutlookError("No email is selected in Outlook." if not items else "The selected item in Outlook isn't an email.",
                           "reading Outlook's selection", f"{len(items)} selected, none an email")
    emails = []
    for item in mails:
        if scratch is not None:
            try:
                emails.append(copy_whole(outlook, item, scratch))
                continue
            except Exception as e:  # noqa: BLE001 - the guard, or a damaged copy: read it field by field instead
                record_problem("copying the email whole (attached to a new email, never saved)", e)
        try:
            emails.append(email_from_item(item))
        except Exception as e:  # noqa: BLE001 - anything not caught field by field
            detail = record_problem("reading the email", e)
            raise OutlookError(f"Outlook didn't give DocRepo the email ({detail}).", "reading the email", detail) from e
    log.info("Outlook: read %d selected email(s)%s", len(emails),
             "; refused " + ", ".join(sorted({f for e in emails for f in e.refused})) if any(e.refused for e in emails) else "")
    return emails


OL_INSPECTOR = 35  # olInspector: an email open in its own window
OL_CONVERSATION_HEADERS = 1  # olConversationHeaders: what Selection.GetSelection is asked for


def _conversation_mails(selection: object) -> list[object]:
    """The newest email of each conversation whose header is selected (release 5.42). None when there's none, or an older
    Outlook that can't say."""
    mails = []
    try:
        headers = selection.GetSelection(OL_CONVERSATION_HEADERS)  # type: ignore[attr-defined]
        for n in range(1, headers.Count + 1):
            items = headers.Item(n).GetItems()
            found = [items.Item(i) for i in range(1, items.Count + 1)]
            found = [item for item in found if getattr(item, "Class", None) == OL_MAIL]
            if found:
                mails.append(max(found, key=lambda item: str(getattr(item, "ReceivedTime", ""))))
    except Exception as e:  # noqa: BLE001 - the selection has no conversation headers to give
        log.info("Outlook: no conversation headers: %s", type(e).__name__)
    return mails


def front_emails(scratch: Path | None = None) -> list[EmailItem]:
    """The Capture wheel's "Email or file" (release 5.42): the email open in Outlook's window in front, or else what's
    selected in its main window."""
    outlook, _how = connect()
    try:
        window = outlook.ActiveWindow()  # type: ignore[attr-defined]
        item = window.CurrentItem if getattr(window, "Class", None) == OL_INSPECTOR else None
    except Exception as e:  # noqa: BLE001 - then read the main window's selection
        record_problem("asking Outlook which window is in front", e)
        item = None
    if item is None or getattr(item, "Class", None) != OL_MAIL:
        return selected_emails(scratch)
    if scratch is not None:
        try:
            return [copy_whole(outlook, item, scratch)]
        except Exception as e:  # noqa: BLE001 - the guard, or a damaged copy: read it field by field instead
            record_problem("copying the open email whole", e)
    return [email_from_item(item)]


def selected_attachment_row() -> FileRow | None:
    """The attachment selected in Outlook's reading pane, as a file row of its own (release 5.42): it arrives alone, as a
    dropped file does. None when no attachment is selected, or the window in front isn't the main one."""
    outlook, _how = connect()
    window = outlook.ActiveWindow()  # type: ignore[attr-defined]
    if getattr(window, "Class", None) == OL_INSPECTOR:
        return None
    selected = window.AttachmentSelection
    if not selected.Count:
        return None
    a = selected.Item(1)
    name = str(a.FileName)
    attachment = Attachment(name, lambda path, a=a: a.SaveAsFile(str(path)), size=attachment_size(a))
    return FileRow(name, None, part=Part("attachment", name, attachment=attachment, size=attachment.size))


def open_msg_file(path: Path) -> EmailItem:
    """A .msg file dropped from File Explorer, read through Outlook: only when DocRepo's own reader (``docrepo/msg.py``)
    can't read it."""
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


# ---- where a dragged email is in Outlook, and its category (release 5.33) ----
def selected_places() -> list[tuple[str, str, str, str]]:
    """The EntryID, StoreID, subject and sent time (to the minute) of each email selected in Outlook, which are the emails
    being dragged. None of these is covered by the security guard. Raises OutlookError."""
    app, _how = connect()
    try:
        selection = app.ActiveExplorer().Selection  # type: ignore[attr-defined]
        items = [selection.Item(n) for n in range(1, selection.Count + 1)]
    except Exception as e:  # noqa: BLE001
        detail = record_problem("reading Outlook's selection, for where the dragged emails are", e)
        raise OutlookError(f"Outlook didn't say which emails are selected ({detail}).", "reading Outlook's selection", detail) from e
    out = []
    for item in items:
        if getattr(item, "Class", None) != OL_MAIL:
            continue
        entry_id, store_id = where_kept(item)
        out.append((entry_id, store_id, _text(read_field(item, "Subject", [])), _when(read_field(item, "SentOn", []))))
    return out


def match_places(emails: Sequence[EmailItem], places: Sequence[tuple[str, ...]]) -> int:
    """Give each dragged email its place in Outlook (release 5.93, the review's F14): the EntryID its own .msg carries,
    when it has one; else the selected email with the same subject and sent minute; else the one selected email with that
    subject, but never by subject when two selected share it (a reply chain), which is skipped and noted on the email for
    Save to say; else, with one email dragged and one selected, that one. Returns how many were placed. A place is
    (EntryID, StoreID, subject, sent minute), the sent minute "" when Outlook didn't give it."""
    left = [p for p in places if p[0]]
    placed = 0

    def same(a: str, b: str) -> bool:
        return a.strip().casefold() == b.strip().casefold()

    for email in emails:
        if email.entry_id:  # its .msg said where it is
            placed += 1
            continue
        sent = (email.sent or "")[:16]
        named = [p for p in left if same(p[2], email.subject)]
        timed = [p for p in named if sent and len(p) > 3 and p[3] == sent]
        match = timed[0] if len(timed) == 1 else None
        if match is None and len(named) == 1 and not timed:
            match = named[0]
        if match is None and len(named) > 1:
            email.place_note = (f"{len(named)} emails selected in Outlook have its subject, so DocRepo couldn't tell which it was, "
                                "and didn't guess")
            continue
        if match is None and not named and len(places) == len(emails) == 1 and left:
            match = left[0]
        if match is not None:
            left.remove(match)
            email.entry_id, email.store_id = match[0], match[1]
            placed += 1
    return placed


def list_separator() -> str:
    """The list separator Windows is set to, which Outlook puts between an email's categories: "," in most places."""
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(8)
        if ctypes.windll.kernel32.GetLocaleInfoW(0x0400, 0x0C, buffer, 8):  # LOCALE_USER_DEFAULT, LOCALE_SLIST
            return buffer.value.strip() or ","
    return ","


def with_category(categories: str, name: str, separator: str | None = None) -> str:
    """An email's categories with ``name`` added at the end, unless it's there already (in any case)."""
    sep = separator or list_separator()
    have = [c.strip() for c in (categories or "").split(sep) if c.strip()]
    if name.casefold() not in {c.casefold() for c in have}:
        have.append(name)
    return f"{sep} ".join(have)


def category_name(model: Model, task_id: str) -> str:
    """The category an email filed on a task gets (decision 25): the task's name, with its top-level task's name in
    brackets when another open task has the same name ("Procurement (Pump trial)"). Commas and semicolons separate
    categories in Outlook, so they become spaces."""
    t = model.task(task_id)

    def clean(text: str) -> str:
        return " ".join(re.sub(r"[,;]", " ", text).split())

    name = clean(t.title)
    same = [x for x in model.tasks.values() if x.id != t.id and not x.discarded and x.state != "Closed" and clean(x.title).casefold() == name.casefold()]
    if same:
        top = t
        while model.parents_of(top.id):
            top = model.task(model.parents_of(top.id)[0])
        name = f"{name} ({clean(top.title) if top.id != t.id else t.id})"
    return name[:255]


#: Outlook's category colours (OlCategoryColor), in its own order: a colour's number is its place here. "None" leaves
#: Outlook's list of categories alone, as release 5.33 did.
COLOURS = ("None", "Red", "Orange", "Peach", "Yellow", "Green", "Teal", "Olive", "Blue", "Purple", "Maroon", "Steel", "Dark steel",
           "Gray", "Dark gray", "Black", "Dark red", "Dark orange", "Dark peach", "Dark yellow", "Dark green", "Dark teal",
           "Dark olive", "Dark blue", "Dark purple", "Dark maroon")


def colour_number(name: str) -> int:
    """A colour's number in Outlook (olCategoryColorTeal is 6), or 0 for None or a name it doesn't know."""
    return COLOURS.index(name) if name in COLOURS else 0


def listed(session: object, name: str, colour: str) -> str:
    """Put the category on Outlook's list, in ``colour``, when it isn't there yet, so it shows in that colour; one already
    there keeps its own (release 5.33.1). Returns a problem in words, or ""."""
    number = colour_number(colour)
    if not number:
        return ""
    try:
        categories = session.Categories  # type: ignore[attr-defined]
        if name.casefold() not in {categories.Item(n).Name.casefold() for n in range(1, categories.Count + 1)}:
            categories.Add(name, number)
        return ""
    except Exception as e:  # noqa: BLE001
        return f"The category {name} wasn't added to Outlook's list of categories ({record_problem('adding a category to Outlook’s list', e)})."


def mark_filed(filed: Sequence[tuple[EmailItem, str]], model: Model, colour: str = "None") -> tuple[int, list[str]]:
    """Add each filed email's task name to it in Outlook as a category, and save it (decisions 24 to 26). Nothing else
    on the email changes. The category goes on Outlook's list in ``colour`` when it isn't there yet (release 5.33.1).
    Returns how many were marked, and a problem for each that wasn't, in words safe for the notification."""
    if not filed:
        return 0, []
    noted = [e for e, _ in filed if not e.entry_id and e.place_note]
    unplaced = sum(not e.entry_id and not e.place_note for e, _ in filed)
    problems = [f"An email ({e.subject[:60]}) couldn't be marked in Outlook: {e.place_note}." for e in noted]
    problems += [f"{unplaced} email{'s' if unplaced != 1 else ''} couldn't be marked in Outlook: DocRepo didn't find "
                 f"{'them' if unplaced != 1 else 'it'} there."] if unplaced else []
    todo = [(e, task) for e, task in filed if e.entry_id]
    if not todo:
        return 0, problems
    try:
        app, _how = connect()
        session = app.Session  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        return 0, problems + [f"Emails weren't marked in Outlook ({e if isinstance(e, OutlookError) else record_problem('marking emails', e)})."]
    marked = 0
    separator = list_separator()
    for name in dict.fromkeys(category_name(model, task) for _, task in todo):
        if trouble := listed(session, name, colour):
            problems.append(trouble)
    for email, task in todo:
        try:
            item = session.GetItemFromID(email.entry_id, email.store_id) if email.store_id else session.GetItemFromID(email.entry_id)
            now = item.Categories or ""
            new = with_category(now, category_name(model, task), separator)
            if new != now:
                item.Categories = new
                item.Save()
            marked += 1
        except Exception as e:  # noqa: BLE001 - moved to another mailbox, deleted, or refused
            problems.append(f"An email wasn't marked in Outlook ({record_problem('marking an email with its task', e)}).")
    log.info("Outlook: marked %d of %d filed emails with their task's name", marked, len(filed))
    return marked, problems


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
