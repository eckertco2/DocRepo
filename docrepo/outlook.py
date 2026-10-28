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

from docrepo.save import Attachment, EmailItem

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
    )


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
        except Exception:  # noqa: BLE001 - never saved, so nothing is left behind either way
            pass
    email = msg.read(scratch.read_bytes())
    email.entry_id, email.store_id = where_kept(item)
    return email


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
def selected_places() -> list[tuple[str, str, str]]:
    """The EntryID, StoreID and subject of each email selected in Outlook, which are the emails being dragged. None of
    these is covered by the security guard. Raises OutlookError."""
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
        out.append((entry_id, store_id, _text(read_field(item, "Subject", []))))
    return out


def match_places(emails: Sequence[EmailItem], places: Sequence[tuple[str, str, str]]) -> int:
    """Give each dragged email the place in Outlook of the selected email with the same subject, in order; failing that,
    when as many are selected as were dragged, the one in the same position. Returns how many were placed."""
    left = [p for p in places if p[0]]
    placed = 0
    for n, email in enumerate(emails):
        match = next((p for p in left if p[2].strip().casefold() == email.subject.strip().casefold()), None)
        if match is None and len(places) == len(emails) and places[n][0] and places[n] in left:
            match = places[n]
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
    unplaced = sum(not e.entry_id for e, _ in filed)
    problems = [f"{unplaced} email{'s' if unplaced != 1 else ''} couldn't be marked in Outlook: DocRepo didn't find "
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
