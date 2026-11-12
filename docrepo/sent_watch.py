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

This module holds what doesn't need Outlook, so it's tested here: which T-mails wait, the match, and the save.
``docrepo.outlook`` reads Sent Items and copies the email; ``docrepo.app`` runs the watch and the sweep.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from docrepo import conversations
from docrepo.db import transaction
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


def _opened_at(t: TMail) -> datetime | None:
    try:
        return datetime.fromisoformat(t.opened)
    except ValueError:
        return None


def waiting(model: Model, now: datetime) -> list[TMail]:
    """The T-mails still looked for in Sent Items: not captured yet, opened in the last 14 days (decision 45), with an
    index that has a key, on a task that's still there. Oldest first."""
    since = now - timedelta(days=conversations.WAIT_DAYS)
    out = []
    for t in model.t_mails:
        at = _opened_at(t)
        task = model.tasks.get(t.task)
        if t.capture or at is None or at < since or not conversations.key(t.conversation_index) or task is None or task.discarded:
            continue
        out.append(t)
    return sorted(out, key=lambda t: (t.opened, t.id))


def any_waiting(conn: sqlite3.Connection, now: datetime) -> bool:
    """Whether a T-mail could still be waiting, read from ``t_mails`` alone: one not captured, with an index, opened in the
    last 14 days. The app's tick asks this every minute, so on the days with none it builds no model."""
    since = (now - timedelta(days=conversations.WAIT_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute("SELECT 1 FROM t_mails WHERE capture IS NULL AND conversation_index IS NOT NULL AND opened >= ? LIMIT 1",
                       (since,)).fetchone()
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
        self.pending: list = []  # SentCopy objects the event handed on, not yet looked at
        self.last_sweep: datetime | None = None
        self.last_found = 0  # captures the last sweep made
        self.last_problem = ""

    # ---- joining Outlook ----
    def waits(self) -> list[TMail]:
        return waiting(Model(self.conn), self.now())

    def watching(self) -> bool:
        return self.watch is not None

    def _drop(self, why: str) -> None:
        """Outlook went away (closed, or restarted): the next tick joins it again, and sweeps."""
        if self.watch is not None:
            log.info("T-mail watch: stopped (%s)", why)
        self.app, self.watch, self.last_problem = None, None, why

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
        """Look at the emails the event handed on."""
        copies, self.pending = self.pending, []
        if not copies:
            return
        waits = self.waits()
        for copy in copies:
            t = match(waits, copy.index)
            if t is not None:
                self._capture(t, copy)

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
        log.info("T-mail sweep: %d waiting, %d sent email(s) looked at, %d captured", len(waits), len(copies), self.last_found)
        return self.last_found

    def tick(self) -> None:
        """Every minute from the app: join Outlook when a T-mail waits, and sweep every 5 minutes while one does. The model
        is built only when ``t_mails`` has one that could be waiting."""
        if not any_waiting(self.conn, self.now()) or not self.waits():
            return
        if not self.ensure():
            return
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
        lines = ages(Model(self.conn), self.now()) or ["No T-mail is waiting to be sent."]
        lines.append("Watching Sent Items: " + ("yes" if self.watching() else "no" + (f" ({self.last_problem})" if self.last_problem else "")))
        lines.append("Last sweep: " + (f"{self.last_sweep:%Y-%m-%d %H:%M}, {self.last_found} captured" if self.last_sweep else "none yet"))
        return lines


def ages(model: Model, now: datetime) -> list[str]:
    """The waiting T-mails for the troubleshooting report, as IDs and ages, never content."""
    out = []
    for t in waiting(model, now):
        at = _opened_at(t)
        hours = (now - at).total_seconds() / 3600 if at else 0
        age = f"{hours:.0f} hour{'s' if round(hours) != 1 else ''}" if hours < 48 else f"{hours / 24:.0f} days"
        out.append(f"T-mail {t.id} ({t.kind}, on {t.task}), opened {age} ago, its index {conversations.layout(t.conversation_index)}")
    return out
