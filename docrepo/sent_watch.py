"""T-mails captured when they're sent (the knowledge base's stage K8, release C, as release 5.123; KB decisions 42 to 45).

A T-mail (``docrepo.conversations``, ``docrepo.ui.t_mails``) is an email DocRepo opened in Outlook from a task, new or
a Reply all, kept in ``t_mails`` with its whole conversation index. When the owner sends it, Outlook keeps a copy in
Sent Items with that same index, and DocRepo saves that copy as a capture on the T-mail's task, with no window
(decision 44): a Note holding the email, as a dragged email makes, with its .msg, its attachments and its text.

DocRepo sees the copy arrive through Outlook's ``ItemAdd`` event on Sent Items (decision 43), and a sweep is the
backstop: at start-up, when the watch is joined to Outlook again, and every 5 minutes while a T-mail waits. A T-mail
is waited for 14 days from when it was opened (decision 45). Only an email whose **whole** conversation index is a
waiting T-mail's is opened; every other email in Sent Items is left alone. Each T-mail is captured once: its row then
names its capture, however often the event and the sweep see it.

**A new T-mail known by its draft** (release 5.141, the design workspace's ``docs/mods/email-progress-plan.md``,
decision 582). Where Outlook's security guard refuses DocRepo's conversation index (``PropertyAccessor``), a new email
has no index until it's sent, so nothing could match it. Such a T-mail is kept with its draft's place in Outlook
(``app_state``, ``t_mail_draft:<id>``, until a schema change moves it into ``t_mails``) and known when it's sent:
- the send is seen by Outlook's ``ItemSend`` event, which names the draft by its EntryID before it moves, with its final
  subject (and its index, should it have one by then); or, as the backstop, by the draft leaving Drafts, looked at every
  minute while it waits (``outlook.draft_state``: only its subject and index are read);
- its sent copy is then the email in Sent Items with a **new conversation's** index (22 bytes: no reply in it), that
  subject, sent between when the T-mail was opened and 30 minutes after the send was seen. Two such emails, or one that
  two T-mails could claim, are all left alone, and the report says so. Its index is then the T-mail's (``learn_index``),
  so its replies find the task, and it's saved like any T-mail's copy. Nothing is ever written on the email.

This module holds what doesn't need Outlook, so it's tested here: which T-mails wait, the match, and the save.
``docrepo.outlook`` reads Sent Items and copies the email; ``docrepo.app`` runs the watch and the sweep.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from docrepo import conversations
from docrepo.db import set_state, transaction
from docrepo.model import Model
from docrepo.save import CaptureDraft, EmailItem, SaveResult, email_rows, save_capture

if TYPE_CHECKING:
    from docrepo.config import Settings
    from docrepo.model import TMail
    from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

#: How often the sweep runs while a T-mail waits (decision 43).
SWEEP_MINUTES = 5
#: The most emails in Sent Items one sweep looks at, newest first, so a full Sent Items can't hold DocRepo up.
SWEEP_LIMIT = 400
#: A new T-mail's sent copy is looked for this long after its send was seen (release 5.141): the owner's own delay rule
#: holds an email in the Outbox a minute, and Outlook may be slow to file it.
SENT_WITHIN = timedelta(minutes=30)
#: A new conversation's index: its 22-byte header and no reply (MS-OXOMSG 2.2.1.3), as hex.
NEW_INDEX_HEX = 44
DRAFT_KEY = "t_mail_draft:"


# ---- a new T-mail's draft (release 5.141) ----
@dataclass(frozen=True)
class Draft:
    """Where a new T-mail Outlook wouldn't let DocRepo tag was kept as a draft, its subject when last seen, and when its
    send was seen ("" while it's still a draft), and how: "send" (``ItemSend``) or "draft" (gone from Drafts)."""

    entry_id: str
    store_id: str
    subject: str = ""
    gone: str = ""
    how: str = ""


def keep_draft(conn: sqlite3.Connection, t_mail: int, entry_id: str, store_id: str) -> None:
    """Keep a new T-mail's draft place, so it's known when it's sent."""
    _save(conn, t_mail, Draft(entry_id, store_id))


def _save(conn: sqlite3.Connection, t_mail: int, d: Draft) -> None:
    set_state(conn, f"{DRAFT_KEY}{t_mail}", json.dumps({"entry": d.entry_id, "store": d.store_id, "subject": d.subject,
                                                         "gone": d.gone, "how": d.how}))


def drop_draft(conn: sqlite3.Connection, t_mail: int) -> None:
    """Forget a new T-mail's draft: it has its index now, or it no longer waits."""
    with transaction(conn):
        conn.execute("DELETE FROM app_state WHERE key = ?", (f"{DRAFT_KEY}{t_mail}",))


def drafts(conn: sqlite3.Connection) -> dict[int, Draft]:
    """Every new T-mail's draft still kept, by T-mail ID."""
    out: dict[int, Draft] = {}
    for row in conn.execute("SELECT key, value FROM app_state WHERE substr(key, 1, ?) = ?", (len(DRAFT_KEY), DRAFT_KEY)):
        try:
            t_mail, v = int(row["key"][len(DRAFT_KEY):]), json.loads(row["value"])
            out[t_mail] = Draft(str(v.get("entry") or ""), str(v.get("store") or ""), str(v.get("subject") or ""),
                                str(v.get("gone") or ""), str(v.get("how") or ""))
        except (ValueError, TypeError, AttributeError):
            continue
    return out


def new_conversation(index: object) -> bool:
    """Whether an index starts a conversation: a key, and no reply in it (a new email's, not a reply's or a forward's)."""
    hexed = conversations.clean_hex(index)
    return bool(conversations.key(hexed)) and len(hexed) == NEW_INDEX_HEX


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%d %H:%M:%S")


def _opened_at(t: TMail) -> datetime | None:
    try:
        return datetime.fromisoformat(t.opened)
    except ValueError:
        return None


def waiting(model: Model, now: datetime, kept: Mapping[int, Draft] | None = None) -> list[TMail]:
    """The T-mails still looked for in Sent Items: not captured yet, opened in the last 14 days (decision 45), with an
    index that has a key, or (release 5.141) with no index but a draft kept in ``kept``, on a task that's still there.
    Oldest first."""
    since = now - timedelta(days=conversations.WAIT_DAYS)
    kept = kept or {}
    out = []
    for t in model.t_mails:
        at = _opened_at(t)
        task = model.tasks.get(t.task)
        known = conversations.key(t.conversation_index) or t.id in kept
        if t.capture or at is None or at < since or not known or task is None or task.discarded:
            continue
        out.append(t)
    return sorted(out, key=lambda t: (t.opened, t.id))


def any_waiting(conn: sqlite3.Connection, now: datetime) -> bool:
    """Whether a T-mail could still be waiting, read from ``t_mails`` alone: one not captured, opened in the last 14 days,
    with an index, or (release 5.141) with its draft kept. The app's tick asks this every minute, so on the days with none
    it builds no model."""
    since = (now - timedelta(days=conversations.WAIT_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute("SELECT 1 FROM t_mails t WHERE t.capture IS NULL AND t.opened >= ? AND (t.conversation_index IS NOT NULL OR "
                       "EXISTS (SELECT 1 FROM app_state a WHERE a.key = ? || t.id)) LIMIT 1", (since, DRAFT_KEY)).fetchone()
    return row is not None


def oldest(waits: list[TMail]) -> datetime | None:
    """When the oldest waiting T-mail was opened: the sweep looks at the emails sent since then."""
    times = [x for x in (_opened_at(t) for t in waits) if x is not None]
    return min(times) if times else None


def match(waits: list[TMail], index: object) -> TMail | None:
    """The waiting T-mail whose whole conversation index is this email's, or None. A reply in the same conversation
    has a longer index, and an email of another conversation another key, so neither matches."""
    hexed = conversations.clean_hex(index)
    if not conversations.key(hexed):
        return None
    return next((t for t in waits if conversations.clean_hex(t.conversation_index) == hexed), None)


def _same_subject(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def match_drafts(waits: list[TMail], kept: Mapping[int, Draft], copies: list) -> tuple[list[tuple[TMail, object]], list[int]]:
    """New T-mails known by their draft (release 5.141), paired with their sent copies: for each whose send was seen
    and whose subject is known, the one email among ``copies`` with a new conversation's index, that subject, sent
    from when its send was seen (from when it was opened, when only its draft leaving Drafts was seen) to 30 minutes
    after. Returns the pairs, and the T-mails left alone
    because two emails would do, or because another T-mail could claim the same email."""
    claims: dict[int, list] = {}
    for t in waits:
        d = kept.get(t.id)
        opened = _opened_at(t)
        if d is None or conversations.key(t.conversation_index) or not d.gone or not d.subject.strip() or opened is None:
            continue
        try:
            gone = datetime.fromisoformat(d.gone)
        except ValueError:
            continue
        # Seen by the send, it was sent then (Outlook's clock and DocRepo's may differ a little); seen by the draft leaving
        # Drafts, it was sent some time after it was opened.
        since = gone - timedelta(minutes=5) if d.how == "send" else opened - timedelta(minutes=5)
        claims[t.id] = [c for c in copies if new_conversation(c.index) and _same_subject(c.subject, d.subject) and c.sent is not None
                        and since <= c.sent <= gone + SENT_WITHIN]
    by_entry: dict[str, int] = {}
    for found in claims.values():
        for c in found:
            by_entry[c.entry_id] = by_entry.get(c.entry_id, 0) + 1
    pairs, unsure = [], []
    for t in waits:
        found = claims.get(t.id)
        if not found:
            continue
        if len(found) == 1 and by_entry[found[0].entry_id] == 1:
            pairs.append((t, found[0]))
        else:
            unsure.append(t.id)
    return pairs, unsure


def still_waiting(conn: sqlite3.Connection, t_mail_id: int) -> bool:
    """Whether the T-mail hasn't been captured yet, read again from docs.db, so the event and the sweep never both save it."""
    row = conn.execute("SELECT capture FROM t_mails WHERE id = ?", (t_mail_id,)).fetchone()
    return row is not None and not row["capture"]


@dataclass(frozen=True)
class Captured:
    """A T-mail saved as a capture: its capture, task and subject, for the notification."""

    t_mail: int
    capture: str
    task: str
    subject: str
    result: SaveResult


def save_sent(conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, t: TMail, email: EmailItem,
              at: datetime) -> Captured | None:
    """Save a T-mail's sent copy as a Note on its task (decision 44), as a dragged email is saved, and note the capture
    on its ``t_mails`` row. None when it was captured already."""
    if not still_waiting(conn, t.id):
        return None
    draft = CaptureDraft(task=t.task, types={"note"}, files=email_rows(email))
    result = save_capture(conn, data_root, fs, settings, draft, at)
    if result.capture_id is None:
        return None
    with transaction(conn):
        conn.execute("UPDATE t_mails SET capture = ? WHERE id = ? AND capture IS NULL", (result.capture_id, t.id))
    log.info("T-mail %s captured when sent, as %s on %s", t.id, result.capture_id, t.task)
    return Captured(t.id, result.capture_id, t.task, email.subject, result)


def notice(model: Model, c: Captured) -> str:
    """The notification's words (decision 44): "Captured your T-mail “Seal delivery” on Pump trial (C000412)"."""
    title = model.tasks[c.task].title if c.task in model.tasks else c.task
    subject = (c.subject or "(no subject)").strip()
    if len(subject) > 60:
        subject = subject[:57] + "…"
    return f"Captured your T-mail “{subject}” on {title} ({c.capture}). Click to open it; Discard is on its page."


class Watcher:
    """The watch on Sent Items and the sweep, for the app (decision 43). It joins Outlook only while a T-mail waits, and
    only when Outlook's window is open, so it never starts Outlook. ``schedule`` runs work after an Outlook event has
    returned (the app's ``QTimer.singleShot``); ``told`` gets each capture made, for the notification. ``out`` is the
    Outlook module, a fake in the tests."""

    def __init__(self, conn: sqlite3.Connection, data_root: Path, fs: SafeFS, settings: Settings, now, told, schedule, out=None) -> None:
        if out is None:
            from docrepo import outlook as out
        self.conn, self.data_root, self.fs, self.settings = conn, data_root, fs, settings
        self.now, self.told, self.schedule, self.out = now, told, schedule, out
        self.app: object | None = None  # the Outlook joined
        self.watch: object | None = None  # the ItemAdd watch, kept so its events keep coming
        self.send_watch: object | None = None  # the ItemSend watch (release 5.141), kept the same way
        self.pending: list = []  # SentCopy objects the event handed on, not yet looked at
        self.sends: list = []  # SendSeen objects ItemSend handed on, not yet looked at (release 5.141)
        self.unsure: list[int] = []  # new T-mails the last sweep left alone: two emails would do
        self.last_sweep: datetime | None = None
        self.last_found = 0  # captures the last sweep made
        self.last_problem = ""

    # ---- joining Outlook ----
    def waits(self) -> list[TMail]:
        return waiting(Model(self.conn), self.now(), drafts(self.conn))

    def watching(self) -> bool:
        return self.watch is not None

    def _drop(self, why: str) -> None:
        """Outlook went away (closed, or restarted): the next tick joins it again, and sweeps."""
        if self.watch is not None:
            log.info("T-mail watch: stopped (%s)", why)
        self.app, self.watch, self.send_watch, self.last_problem = None, None, None, why

    def ensure(self) -> bool:
        """Join Outlook and watch Sent Items, when a T-mail waits and Outlook is open; sweep on joining (decision 43).
        True while watching."""
        if self.watch is not None:
            return True
        if not self.waits() or not self.out.outlook_window_open():
            return False
        try:
            self.app, _how = self.out.connect()
            self.watch = self.out.watch_sent(self.app, self._heard)
        except Exception as e:  # noqa: BLE001 - Outlook, pywin32 or COM; tried again on the next tick
            self._drop(self.out.record_problem("watching Sent Items for T-mails (ItemAdd)", e))
            return False
        log.info("T-mail watch: watching Sent Items")
        try:
            self.send_watch = self.out.watch_send(self.app, self._heard_send)  # release 5.141; the draft watch is the backstop
        except Exception as e:  # noqa: BLE001 - Outlook, pywin32 or COM: drafts are still looked at every minute
            self.send_watch = None
            self.out.record_problem("watching Outlook's sends for T-mails (ItemSend)", e)
        self.watch_drafts()
        self.sweep()
        return self.watch is not None

    def started(self) -> None:
        """A T-mail was just opened: watch for it now, rather than at the next tick."""
        self.ensure()

    # ---- the event ----
    def _heard(self, copy) -> None:
        """Inside Outlook's event: only note it, and look after the event has returned."""
        self.pending.append(copy)
        self.schedule(self.look)

    def look(self) -> None:
        """Look at the emails the event handed on. One that matches no T-mail by its index, while a new T-mail known
        by its draft has been sent, brings the sweep, which sees every candidate before it takes one (release 5.141)."""
        copies, self.pending = self.pending, []
        if not copies:
            return
        waits = self.waits()
        kept = drafts(self.conn)
        sweep = False
        for copy in copies:
            t = match(waits, copy.index)
            if t is not None:
                self._capture(t, copy)
            elif new_conversation(copy.index) and any(kept[w.id].gone for w in waits if w.id in kept):
                sweep = True
        if sweep:
            self.sweep()

    # ---- a new T-mail's send (release 5.141) ----
    def _heard_send(self, seen) -> None:
        """Inside Outlook's ItemSend: only note it, and look after the event has returned."""
        self.sends.append(seen)
        self.schedule(self.look_sends)

    def look_sends(self) -> None:
        """A new T-mail's draft being sent: its final subject and the time, and its index if it has one by now."""
        seen, self.sends = self.sends, []
        if not seen:
            return
        kept = drafts(self.conn)
        for s in seen:
            for t_mail, d in kept.items():
                if s.entry_id and s.entry_id == d.entry_id and not d.gone:
                    self._sent(t_mail, d, s.subject or d.subject, s.index, "send")

    def _sent(self, t_mail: int, d: Draft, subject: str, index: str, how: str) -> None:
        if conversations.learn_index(self.conn, t_mail, index):
            drop_draft(self.conn, t_mail)  # an ordinary T-mail now, matched by its index
            return
        _save(self.conn, t_mail, replace(d, subject=subject, gone=_stamp(self.now()), how=how))
        log.info("T-mail %s: its draft was sent (seen by %s)", t_mail, "the send" if how == "send" else "its draft leaving Drafts")

    def watch_drafts(self) -> None:
        """Every minute: each new T-mail's draft still in Drafts is looked at again, for its subject, an index Outlook
        may have given it, and whether it's gone. Drafts of T-mails no longer waiting are forgotten."""
        kept = drafts(self.conn)
        if not kept:
            return
        waits = {t.id for t in self.waits()}
        for t_mail, d in kept.items():
            if t_mail not in waits:
                drop_draft(self.conn, t_mail)
                continue
            if d.gone or self.app is None:
                continue
            try:
                state = self.out.draft_state(self.app, d.entry_id, d.store_id)
            except Exception as e:  # noqa: BLE001 - Outlook busy or gone: the next tick tries again
                self._drop(self.out.record_problem("looking at a new T-mail's draft", e))
                return
            if state.gone:
                self._sent(t_mail, d, state.subject or d.subject, state.index, "draft")
            elif conversations.learn_index(self.conn, t_mail, state.index):
                drop_draft(self.conn, t_mail)
            elif state.subject and state.subject != d.subject:
                _save(self.conn, t_mail, replace(d, subject=state.subject))

    # ---- the sweep ----
    def sweep(self) -> int:
        """Look through Sent Items for the waiting T-mails, among the emails sent since the oldest was opened. Returns how
        many were captured."""
        waits = self.waits()
        since = oldest(waits)
        self.last_sweep = self.now()
        self.last_found = 0
        if since is None or self.app is None:
            return 0
        try:
            copies = self.out.sent_since(self.out.sent_items(self.app), since, SWEEP_LIMIT)
        except Exception as e:  # noqa: BLE001
            self._drop(self.out.record_problem("looking through Sent Items for T-mails", e))
            return 0
        for copy in copies:
            t = match(waits, copy.index)
            if t is not None and self._capture(t, copy):
                self.last_found += 1
        pairs, self.unsure = match_drafts(self.waits(), drafts(self.conn), copies)
        for t, copy in pairs:
            if conversations.learn_index(self.conn, t.id, copy.index) and self._capture(t, copy):
                drop_draft(self.conn, t.id)
                self.last_found += 1
        log.info("T-mail sweep: %d waiting, %d sent email(s) looked at, %d captured", len(waits), len(copies), self.last_found)
        return self.last_found

    def tick(self) -> None:
        """Every minute from the app: join Outlook when a T-mail waits, and sweep every 5 minutes while one does. The model
        is built only when ``t_mails`` has one that could be waiting."""
        if not any_waiting(self.conn, self.now()) or not self.waits():
            return
        joined = self.watch is not None
        if not self.ensure():
            return
        if joined:  # joining just now looked at the drafts already (release 5.141)
            self.watch_drafts()
        if self.last_sweep is None or self.now() - self.last_sweep >= timedelta(minutes=SWEEP_MINUTES):
            self.sweep()

    # ---- the capture ----
    def _capture(self, t: TMail, copy) -> bool:
        if not still_waiting(self.conn, t.id) or self.app is None:
            return False
        try:
            email = self.out.copy_sent(self.app, copy, self.out.copy_path(self.fs, self.data_root))
        except Exception as e:  # noqa: BLE001 - OutlookError, or COM: the next sweep tries again
            self.last_problem = str(e)
            log.warning("T-mail %s: its sent copy couldn't be read: %s", t.id, e)
            return False
        try:
            captured = save_sent(self.conn, self.data_root, self.fs, self.settings, t, email, self.now())
        except Exception as e:  # noqa: BLE001 - a save that fails is said, and tried again on the next sweep
            self.last_problem = f"saving T-mail {t.id}: {type(e).__name__}"
            log.exception("T-mail %s: its capture couldn't be saved", t.id)
            return False
        if captured is None:
            return False
        if self.settings.outlook_categories and captured.result.filed_emails:  # "Mark filed emails in Outlook" (release 5.33)
            try:
                self.out.mark_filed(captured.result.filed_emails, Model(self.conn), self.settings.outlook_category_colour)
            except Exception as e:  # noqa: BLE001 - the capture is saved; only the category is missing
                self.out.record_problem("marking the sent T-mail with its task's category", e)
        self.told(captured)
        return True

    def report(self) -> list[str]:
        """The troubleshooting report's lines: the waiting T-mails, the watch, and the last sweep."""
        lines = ages(Model(self.conn), self.now(), drafts(self.conn), self.unsure) or ["No T-mail is waiting to be sent."]
        lines.append("Watching Sent Items: " + ("yes" if self.watching() else "no" + (f" ({self.last_problem})" if self.last_problem else "")))
        lines.append("Watching Outlook's sends, for a new T-mail known by its draft: " + ("yes" if self.send_watch is not None else "no"))
        lines.append("Last sweep: " + (f"{self.last_sweep:%Y-%m-%d %H:%M}, {self.last_found} captured" if self.last_sweep else "none yet"))
        return lines


def ages(model: Model, now: datetime, kept: Mapping[int, Draft] | None = None, unsure: list[int] | None = None) -> list[str]:
    """The waiting T-mails for the troubleshooting report, as IDs and ages, and how each will be known: by its index, or
    (release 5.141) by its draft, still one or sent (seen by the send, or by the draft leaving Drafts). Never content."""
    kept = kept or {}
    out = []
    for t in waiting(model, now, kept):
        at = _opened_at(t)
        hours = (now - at).total_seconds() / 3600 if at else 0
        age = f"{hours:.0f} hour{'s' if round(hours) != 1 else ''}" if hours < 48 else f"{hours / 24:.0f} days"
        d = kept.get(t.id)
        if conversations.key(t.conversation_index) or d is None:
            known = f"its index {conversations.layout(t.conversation_index)}"
        elif not d.gone:
            known = "known by its draft, still in Drafts"
        else:
            seen = "the send" if d.how == "send" else "its draft leaving Drafts"
            known = f"known by its draft, sent at {d.gone[11:16]} (seen by {seen})"
            if t.id in (unsure or []):
                known += "; two sent emails would do, so it's left alone"
        out.append(f"T-mail {t.id} ({t.kind}, on {t.task}), opened {age} ago, {known}")
    return out
