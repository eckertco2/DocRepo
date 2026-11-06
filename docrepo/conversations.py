"""Outlook conversations, and the task each one follows (the knowledge base's stage K8, release 5.101, KB decisions 32 to 34).

Every email Outlook sends carries a conversation index (the ``Thread-Index`` header, ``PR_CONVERSATION_INDEX``), which a
reply keeps and adds to. MS-OXOMSG 2.2.1.3 gives its shape: a 22-byte header (a reserved byte that is 0x01, the time in
5 bytes, then the conversation's GUID in 16 bytes), then one 5-byte response level for each reply or forward. The GUID is
the conversation's **key**: the same in every email of the conversation, whatever its subject. Outlook's own
ConversationID is that GUID only when the email's conversation index tracking flag is set; otherwise it's an MD5 hash of
the subject (MS-OXOMSG 2.2.1.2), so DocRepo keys on the index and never on the ID, and never on the subject.

A conversation **follows the task it was last filed to** (KB decision 32): the newest live capture with an email of that
conversation and a task, or a T-mail opened from a task (K8's release B), whichever is later. A discarded task is
skipped, and the filing before it counts. The capture window fills its task picker from it (``pick``), shown as "from
conversation", for the owner to keep or change; a task picked by hand, then one ``#`` task, win over it (decision 33).

``backfill`` gives the emails captured before this release their identifiers, read from each saved .msg without Outlook
(KB decision 27): the ``email-ids`` command. It never changes a .msg file.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from docrepo.db import transaction

if TYPE_CHECKING:
    from docrepo.model import Model
    from docrepo.save import EmailItem

log = logging.getLogger(__name__)

HEADER = 22  # the conversation index's header: 0x01, the time in 5 bytes, the GUID in 16
LEVEL = 5  # each reply or forward adds a response level of 5 bytes
RESERVED = 0x01
GUID = slice(6, 22)
#: How long a T-mail is looked for in Sent Items after it's opened (KB decision 45, K8's release C).
WAIT_DAYS = 14

_HEX = re.compile(r"[0-9A-Fa-f]*\Z")


def clean_hex(value: object) -> str:
    """An index or ID as DocRepo keeps it: uppercase hex, from bytes or from Outlook's hex string. "" for nothing, or for
    text that isn't hex."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex().upper()
    if isinstance(value, str):
        text = "".join(value.split())
        return text.upper() if text and len(text) % 2 == 0 and _HEX.match(text) else ""
    return ""


def _bytes(index: str) -> bytes:
    try:
        return bytes.fromhex(index)
    except ValueError:
        return b""


def well_formed(index: str) -> bool:
    """Whether an index (as hex) has MS-OXOMSG's shape: at least the 22-byte header, 22 plus a multiple of 5 in all, and
    0x01 first."""
    raw = _bytes(clean_hex(index))
    return len(raw) >= HEADER and (len(raw) - HEADER) % LEVEL == 0 and raw[0] == RESERVED


def key(index: object) -> str:
    """The conversation's key: the GUID in the index's header, as 32 hex characters. "" when the index has no key."""
    hexed = clean_hex(index)
    return _bytes(hexed)[GUID].hex().upper() if well_formed(hexed) else ""


def replies(index: object) -> int:
    """How many replies and forwards deep the email is in its conversation: 0 for the first email; -1 for no key."""
    hexed = clean_hex(index)
    return (len(_bytes(hexed)) - HEADER) // LEVEL if well_formed(hexed) else -1


def layout(index: object) -> str:
    """The index's layout in words, for the troubleshooting report: never its value."""
    raw = _bytes(clean_hex(index))
    if not raw:
        return "none"
    if well_formed(clean_hex(index)):
        depth = (len(raw) - HEADER) // LEVEL
        return f"MS-OXOMSG's layout, {len(raw)} bytes: the header and {depth} repl{'y' if depth == 1 else 'ies'}"
    return f"another layout: {len(raw)} bytes, first byte 0x{raw[0]:02X}, so no key"


def within(child: object, parent: object) -> bool:
    """Whether ``child`` is a reply (or a reply's reply) in ``parent``'s conversation, by its index starting with the
    parent's whole index and going on."""
    c, p = clean_hex(child), clean_hex(parent)
    return bool(key(c)) and len(c) > len(p) and c.startswith(p) and key(c) == key(p)


# ---- which task a conversation follows ----
@dataclass(frozen=True)
class Filing:
    """One time a conversation was filed to a task: by a capture (``capture``) or by a T-mail opened from it."""

    task: str
    at: str  # a stored time, "YYYY-MM-DD HH:MM:SS"
    capture: str | None = None
    t_mail: int | None = None


@dataclass(frozen=True)
class Pick:
    """What the capture window's task picker takes from a capture's emails: one task, or nothing with the tasks that
    disagree (``mixed``)."""

    task: str | None = None
    closed: bool = False
    filing: Filing | None = None
    mixed: tuple[str, ...] = ()


_FILINGS: "weakref.WeakKeyDictionary[Model, dict[str, list[Filing]]]" = weakref.WeakKeyDictionary()


def filings(model: Model) -> dict[str, list[Filing]]:
    """Each conversation's filings, oldest first: every live capture with a task and an email of it, and every T-mail.
    Worked out once per model."""
    cached = _FILINGS.get(model)
    if cached is not None:
        return cached
    out: dict[str, list[Filing]] = {}
    for c in model.captures.values():
        task = c.task or c.filed_to
        if c.discarded or not task:
            continue
        at = max(c.saved, c.filed or "")
        for e in c.emails:
            if e.conversation:
                out.setdefault(e.conversation, []).append(Filing(task, at, capture=c.id))
    for t in model.t_mails:
        if t.conversation:
            out.setdefault(t.conversation, []).append(Filing(t.task, t.opened, t_mail=t.id))
    for found in out.values():
        found.sort(key=lambda f: (f.at, f.capture or "", f.t_mail or 0))
    _FILINGS[model] = out
    return out


def task_for(model: Model, conversation: str) -> Filing | None:
    """The filing a conversation follows: its latest to a task that's still there (decision 32)."""
    for f in reversed(filings(model).get(conversation, [])):
        t = model.tasks.get(f.task)
        if t is not None and not t.discarded:
            return f
    return None


def pick(model: Model, conversations: list[str]) -> Pick:
    """The task a capture's emails' conversations follow: their one task, or none with the tasks named when they follow
    different tasks (decision 33)."""
    found: dict[str, Filing] = {}
    for conversation in dict.fromkeys(c for c in conversations if c):
        f = task_for(model, conversation)
        if f is not None and (f.task not in found or f.at > found[f.task].at):
            found[f.task] = f
    if len(found) == 1:
        task, f = next(iter(found.items()))
        return Pick(task, model.tasks[task].state == "Closed", f)
    return Pick(mixed=tuple(sorted(found))) if found else Pick()


def note(model: Model, p: Pick) -> str:
    """The picker's tooltip for a task from the conversation: where the link came from."""
    if p.task is None or p.filing is None:
        return ""
    t, f = model.tasks[p.task], p.filing
    day = f.at[:10]
    if f.capture:
        return f"An email in this conversation was filed to {t.title} on {day} ({f.capture}). Pick another task to change it."
    return f"This conversation started with a T-mail from {t.title} on {day}. Pick another task to change it."


def email_keys(emails: list[EmailItem]) -> list[str]:
    """The conversations of a capture's emails, in order, with no key left out."""
    return [k for k in (key(e.conversation_index) for e in emails) if k]


# ---- the backfill: email-ids ----
_MSG_NAME = re.compile(r"email(?: (\d+))?\.msg\Z", re.IGNORECASE)

IDENTIFIERS = ("conversation", "conversation_index", "conversation_id", "conversation_topic", "conversation_tracking",
               "message_id", "in_reply_to", "refs")


@dataclass
class Backfill:
    """What ``email-ids`` found and did, as counts."""

    captures: int = 0
    filled: int = 0  # rows given their identifiers
    made: int = 0  # rows made for captures from before release 5.74, which had none
    keyed: int = 0  # of those, how many have a conversation key
    missing: int = 0  # .msg files named in docs.db and not in the capture's folder
    unreadable: list[str] = field(default_factory=list)  # capture IDs whose .msg couldn't be read

    def lines(self, dry_run: bool) -> list[str]:
        verb = "Would give" if dry_run else "Gave"
        return [
            f"Looked at {self.captures} capture{'s' if self.captures != 1 else ''} with saved emails.",
            f"{verb} {self.filled} email row{'s' if self.filled != 1 else ''} their Outlook identifiers, and "
            f"{'would make' if dry_run else 'made'} {self.made} row{'s' if self.made != 1 else ''} for emails captured before release 5.74.",
            f"{self.keyed} of them have a conversation key, so their conversations now follow their captures' tasks."
            if not dry_run else f"{self.keyed} of them have a conversation key.",
            *([f"{self.missing} .msg file{'s are' if self.missing != 1 else ' is'} named in docs.db but not in its capture's folder."]
              if self.missing else []),
            *([f"Couldn't read the .msg of {', '.join(self.unreadable[:10])}{' and more' if len(self.unreadable) > 10 else ''}."]
              if self.unreadable else []),
            "No .msg file was changed." if not dry_run else "Nothing was recorded (--dry-run).",
        ]


def identifier_values(email: EmailItem) -> dict[str, object]:
    """An email's identifiers as ``capture_emails`` keeps them (None for one it hasn't)."""
    tracking = email.conversation_tracking
    return {
        "conversation": key(email.conversation_index) or None,
        "conversation_index": clean_hex(email.conversation_index) or None,
        "conversation_id": clean_hex(email.conversation_id) or None,
        "conversation_topic": email.conversation_topic or None,
        "conversation_tracking": None if tracking is None else int(bool(tracking)),
        "message_id": email.message_id or None,
        "in_reply_to": email.in_reply_to or None,
        "refs": email.refs or None,
    }


def saved_msg_files(folder: Path) -> list[Path]:
    """A capture's saved emails, in their order: email.msg, then email 2.msg, email 3.msg and so on."""
    try:
        names = [p for p in folder.iterdir() if p.is_file() and _MSG_NAME.match(p.name)]
    except OSError:
        return []
    return sorted(names, key=lambda p: int(_MSG_NAME.match(p.name).group(1) or 1))  # type: ignore[union-attr]


def backfill(conn: sqlite3.Connection, data_root: Path, dry_run: bool = False) -> Backfill:
    """Read the Outlook identifiers of every saved email that has none from its .msg file, and record them; make the rows
    of emails captured before release 5.74. Only reads .msg files, never writes one (KB decisions 27 and 34)."""
    from docrepo import msg
    from docrepo.captures import capture_folder

    out = Backfill()
    rows = conn.execute("SELECT id, saved, source FROM captures ORDER BY id").fetchall()
    for c in rows:
        held = conn.execute("SELECT pos, file, conversation_index, message_id FROM capture_emails WHERE capture = ? ORDER BY pos",
                            (c["id"],)).fetchall()
        folder = capture_folder(data_root, c["id"], c["saved"])
        if held:
            todo = [(r["pos"], r["file"]) for r in held if r["file"] and not r["conversation_index"] and not r["message_id"]]
            files = [(pos, folder / name) for pos, name in todo]
        elif c["source"] == "outlook_email":
            files = [(pos, path) for pos, path in enumerate(saved_msg_files(folder))]
        else:
            continue
        if not files and not held:
            continue
        out.captures += 1
        updates: list[tuple[int, str, object, bool]] = []
        for pos, path in files:
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                out.missing += 1
                continue
            except OSError:
                out.unreadable.append(c["id"])
                continue
            try:
                email = msg.read(data)
            except msg.MsgError:
                out.unreadable.append(c["id"])
                continue
            updates.append((pos, path.name, email, bool(held)))
        if not updates:
            continue
        for _pos, _name, email, _had in updates:
            out.keyed += bool(key(email.conversation_index))
        out.filled += sum(had for *_, had in updates)
        out.made += sum(not had for *_, had in updates)
        if dry_run:
            continue
        with transaction(conn):
            for pos, name, email, had in updates:
                values = identifier_values(email)
                if had:
                    conn.execute(f"UPDATE capture_emails SET {', '.join(f'{k} = ?' for k in IDENTIFIERS)} WHERE capture = ? AND pos = ?",  # noqa: S608 - a column or table name of DocRepo's own; values are parameters
                                 (*values.values(), c["id"], pos))
                else:
                    conn.execute(f"INSERT INTO capture_emails (capture, pos, file, subject, sender, sent, description, {', '.join(IDENTIFIERS)}) "  # noqa: S608 - a column or table name of DocRepo's own; values are parameters
                                 f"VALUES (?, ?, ?, ?, ?, ?, NULL, {', '.join('?' for _ in IDENTIFIERS)})",
                                 (c["id"], pos, name, email.subject, email.sender, email.sent, *values.values()))
    log.info("email-ids%s: %d captures, %d rows filled, %d made, %d keyed", " (dry run)" if dry_run else "", out.captures, out.filled,
             out.made, out.keyed)
    return out
