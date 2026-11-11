"""The emails filed in DocRepo, as conversations (release 5.122: the task page's Email conversations and a conversation's
page; the design workspace's ``docs/mods/email-section-plan.md``, decisions 455 to 463).

**What makes a conversation** (decision 457). Emails with the same conversation key (the GUID in their conversation
index, ``docrepo.conversations``, the knowledge base's stage K8) are one conversation. An email whose In-Reply-To or
References names a captured email's Message-ID joins that email's conversation, so a reply whose subject was changed,
which Exchange gives a new conversation index, stays with what it answers; that's the glossary's thread, one or more
conversations, which the owner sees as one. Never the subject (KB decision 35). An email with neither stands alone.
It's worked out once per model over every live capture, so a conversation is the same on every task that holds an
email of it. The same email captured twice (by its Message-ID, else its sender, subject and sent time) is listed once.

**An email's own words** (decision 462). DocRepo keeps an email's text in its capture's content text, after header
lines it writes itself (``EmailItem.text``: From, Sent, To, Subject). ``email_text`` finds that part again; ``own_words``
splits it where the quoted history starts. Only read: ``capture.md`` is never changed.

Nothing here touches Qt or Outlook, so it's tested in the fast run.
"""
from __future__ import annotations

import re
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field

from docrepo.captures import plain
from docrepo.conversations import message_ids
from docrepo.model import Capture, Model

#: How many conversations the task page's section lists before "Show all" (decision 456).
SHOWN = 5
#: How many characters of the newest email's own words a row shows.
SNIPPET = 70

_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|aw|wg|tr|sv|vs|antw)\s*(?:\[\d+\])?\s*[:：]\s*)+", re.IGNORECASE)


def clean_subject(subject: str) -> str:
    """A subject without its RE:, FW: and the like, in English and the usual other languages: "RE: FW: Seal delivery" is
    "Seal delivery"."""
    return " ".join(_PREFIX.sub("", subject or "").split())


@dataclass
class Email:
    """One captured email, as a conversation lists it: its capture and place in it, the live tasks its capture is on (none
    for an unfiled one), and what DocRepo keeps of it. ``pos`` is -1 for an email capture with no email rows (decision 463).
    ``also`` holds the other captures of the same email, as (capture, pos)."""

    capture: str
    pos: int
    tasks: list[str]
    subject: str
    sender: str
    sent: str
    saved: str
    file: str | None = None
    description: str = ""
    key: str = ""
    message_id: str = ""
    in_reply_to: str = ""
    refs: str = ""
    entry_id: str = ""
    store_id: str = ""
    also: list[tuple[str, int]] = field(default_factory=list)

    @property
    def at(self) -> str:
        """When it was sent ("YYYY-MM-DD HH:MM"), else when its capture was saved."""
        return self.sent or self.saved[:16]

    @property
    def ref(self) -> str:
        """Its capture and position, as the conversation's page names it in links: "C000012:0"."""
        return f"{self.capture}:{self.pos}"

    @property
    def can_open(self) -> bool:
        """Whether Open in Outlook can find it: by its place, or its saved .msg (decision 460)."""
        return bool(self.entry_id or self.file)


@dataclass
class Conversation:
    """One conversation (decision 457): its emails, the oldest first. ``id`` is its first keyed email's key, else its first
    email's capture and position ("C000012.0"), for links."""

    id: str
    emails: list[Email]

    @property
    def subject(self) -> str:
        """Its first email's subject, without RE: and FW:."""
        return next((s for s in (clean_subject(e.subject) for e in self.emails) if s), "(no subject)")

    @property
    def newest(self) -> Email:
        return self.emails[-1]

    @property
    def keys(self) -> set[str]:
        return {e.key for e in self.emails if e.key}

    def tasks(self) -> list[str]:
        """The tasks its emails are on, in the order its emails came."""
        return list(dict.fromkeys(t for e in self.emails for t in e.tasks))

    def senders(self) -> list[str]:
        """Who wrote its emails, each once, by first appearance."""
        return list(dict.fromkeys(e.sender for e in self.emails if e.sender))

    def names(self, ids: set[str]) -> bool:
        """Whether a link's conversation ID names this conversation: its own, one of its keys, or one of its emails, so a
        page stays open when a new capture joins two conversations."""
        return ids & ({self.id} | self.keys | {f"{e.capture}.{e.pos}" for e in self.emails}) != set()


# ---- the conversations ----
def _emails_of(model: Model, c: Capture) -> list[Email]:
    tasks = [t for t in model.capture_tasks(c) if t in model.tasks and not model.tasks[t].discarded]
    if c.emails:
        return [Email(c.id, e.pos, tasks, e.subject or "", e.sender or "", e.sent or "", c.saved, e.file, e.description or "",
                      e.conversation, e.message_id, e.in_reply_to, e.refs, e.entry_id, e.store_id) for e in c.emails]
    if c.source == "outlook_email":  # captured before release 5.74 and never backfilled (decision 463)
        return [Email(c.id, -1, tasks, c.title, "", "", c.saved)]
    return []


def _same(e: Email) -> tuple[str, ...] | None:
    """What says two captured emails are one: the Message-ID, else the sender, subject and sent time."""
    first = message_ids(e.message_id)[:1]
    if first:
        return ("id", first[0])
    return ("ss", e.sender, e.subject, e.sent) if e.sent else None


def build(model: Model) -> list[Conversation]:
    """Every conversation of the model's live captures, newest first (by its newest email)."""
    emails: list[Email] = []
    seen: dict[tuple[str, ...], Email] = {}
    for c in sorted(model.live_captures(), key=lambda c: (c.saved, c.id)):
        for e in _emails_of(model, c):
            same = _same(e)
            if same is not None and same in seen:
                kept = seen[same]
                kept.also.append((e.capture, e.pos))
                kept.tasks.extend(t for t in e.tasks if t not in kept.tasks)
                continue
            if same is not None:
                seen[same] = e
            emails.append(e)
    parent = list(range(len(emails)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a: int, b: int) -> None:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_key: dict[str, int] = {}
    by_id: dict[str, int] = {}
    for i, e in enumerate(emails):
        if e.key:
            if e.key in by_key:
                join(i, by_key[e.key])
            else:
                by_key[e.key] = i
        for mid in message_ids(e.message_id)[:1]:
            by_id.setdefault(mid, i)
    for i, e in enumerate(emails):
        for mid in (*message_ids(e.in_reply_to), *message_ids(e.refs)):
            j = by_id.get(mid)
            if j is not None:
                join(i, j)
    groups: dict[int, list[Email]] = {}
    for i, e in enumerate(emails):
        groups.setdefault(root(i), []).append(e)
    out = []
    for members in groups.values():
        members.sort(key=lambda e: (e.at, e.saved, e.capture, e.pos))
        keyed = next((e.key for e in members if e.key), "")
        out.append(Conversation(keyed or f"{members[0].capture}.{members[0].pos}", members))
    out.sort(key=lambda cv: (cv.newest.at, cv.newest.capture), reverse=True)
    return out


_BUILT: "weakref.WeakKeyDictionary[Model, list[Conversation]]" = weakref.WeakKeyDictionary()


def all_of(model: Model) -> list[Conversation]:
    """Every conversation, newest first; worked out once per model."""
    found = _BUILT.get(model)
    if found is None:
        found = build(model)
        _BUILT[model] = found
    return found


def for_tasks(model: Model, task_ids: list[str]) -> list[Conversation]:
    """The conversations with an email on any of these tasks, newest first (decision 456)."""
    wanted = {t for t in task_ids if t in model.tasks and not model.tasks[t].discarded}
    return [cv for cv in all_of(model) if any(t in wanted for e in cv.emails for t in e.tasks)]


def find(model: Model, conversation_id: str) -> Conversation | None:
    """The conversation a link names (``Conversation.names``)."""
    ids = {conversation_id}
    return next((cv for cv in all_of(model) if cv.names(ids)), None)


def task_in(cv: Conversation, task_ids: list[str]) -> str | None:
    """The task a conversation's row names on a page over these tasks: the task of its newest email on one of them."""
    wanted = set(task_ids)
    for e in reversed(cv.emails):
        for t in e.tasks:
            if t in wanted:
                return t
    return None


# ---- an email's own words (decision 462) ----
_QUOTED = re.compile(
    r"^(?:"
    r"-{2,}\s*Original Message\s*-{2,}"  # Outlook's plain-text reply
    r"|_{10,}\s*$"  # Outlook's rule above the quoted email's header
    r"|From:[^\n]*\n(?:[^\n]*\n){0,3}?(?:Sent|Date):"  # a quoted email's header block
    r"|On\b[^\n]{0,200}(?:\n[^\n]{0,200})?\bwrote:\s*$"  # "On Mon, 9 Nov 2026, Dana Ortiz wrote:"
    r"|>[^\n]*\n>"  # lines quoted with >
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def own_words(text: str) -> tuple[str, str]:
    """An email's text split where its quoted history starts: (its own words, the quoted emails). An email that's all
    quote (a forward with nothing added) keeps it all as its own words."""
    body = (text or "").replace("\r\n", "\n").strip()
    m = _QUOTED.search(body)
    if m is None:
        return body, ""
    own, quoted = body[:m.start()].rstrip(), body[m.start():].strip()
    return (own, quoted) if own else (body, "")


def _header(sender: str, sent: str, subject: str, loose: bool = False) -> re.Pattern[str]:
    """The header lines DocRepo wrote above an email's body in its capture's content text (``EmailItem.text``)."""
    when = r"(?:Sent: [^\n]*\n)?" if loose or not sent else f"Sent: {re.escape(sent)}\n"
    return re.compile(f"^From: {re.escape(sender)}\n{when}(?:To: ([^\n]*)\n)?Subject: {re.escape(subject)}[ \t]*\n", re.MULTILINE)


@dataclass(frozen=True)
class Text:
    """A captured email's part of its capture's content text: its To line, its words, and what the owner wrote in the
    capture above its emails (``note``, given with the capture's first email only)."""

    to: str = ""
    words: str = ""
    note: str = ""
    found: bool = False


def email_text(model: Model, email: Email, content: str | None) -> Text:
    """Find one email's text in its capture's content text (as kept: ``content``). A capture holding one email whose header
    isn't found (edited, or captured before its header lines) gives its whole text, less any header lines."""
    c = model.captures.get(email.capture)
    words = plain(c, content) if c is not None else content
    if not words:
        return Text()
    words = words.replace("\r\n", "\n")
    if c is None or email.pos < 0 or not c.emails:
        return Text(words=_without_head(words), found=True)
    starts: list[tuple[int, int, str]] = []
    at = 0
    for e in c.emails:
        m = (_header(e.sender, e.sent, e.subject).search(words, at) or _header(e.sender, e.sent, e.subject, loose=True).search(words, at))
        if m is None:
            starts.append((-1, -1, ""))
            continue
        starts.append((m.start(), m.end(), m.group(1) or ""))
        at = m.end()
    index = next((i for i, e in enumerate(c.emails) if e.pos == email.pos), -1)
    if index < 0 or starts[index][0] < 0:
        return Text(words=_without_head(words), found=False) if len(c.emails) == 1 else Text()
    begin, end, to = starts[index]
    after = [s for s, _e, _t in starts[index + 1:] if s >= 0]
    body = words[end:after[0]] if after else words[end:]
    first_found = next((s for s, _e, _t in starts if s >= 0), -1)
    note = words[:first_found].strip() if index == next((i for i, s in enumerate(starts) if s[0] >= 0), -1) else ""
    return Text(to=to.strip(), words=body.strip(), note=note, found=True)


_HEAD = re.compile(r"^(?:(?:From|To|Cc|Sent|Date|Subject):[^\n]*\n)+\s*")


def _without_head(text: str) -> str:
    """A text without the header lines at its start."""
    return _HEAD.sub("", text.strip() + "\n", count=1).strip()


_GREETING = re.compile(r"^(?:hi|hello|hey|dear|morning|good (?:morning|afternoon|evening))\b[^\n]{0,30}$|^[^\n]{1,30},$", re.IGNORECASE)


def snippet(words: str, limit: int = SNIPPET) -> str:
    """The first words of an email's own words for a row: without a greeting line, on one line, cut at ``limit``."""
    lines = [ln.strip() for ln in (words or "").split("\n") if ln.strip()]
    if len(lines) > 1 and _GREETING.match(lines[0]):
        lines = lines[1:]
    text = " ".join(" ".join(lines).split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def newest_words(model: Model, cv: Conversation, content_of: Callable[[str], str]) -> str:
    """The newest email's own words, for its conversation's row."""
    for e in reversed(cv.emails):
        text = email_text(model, e, content_of(e.capture))
        own = own_words(text.words)[0]
        if own:
            return own
    return ""


def who(names: list[str], me: str | None, most: int = 3) -> str:
    """The people of a conversation in words: "Dana Ortiz, Tom Becker and you", the owner (``me``, a name) as "you", and
    "and 2 more" after ``most``."""
    mine = (me or "").strip().lower()
    shown = ["you" if mine and n.strip().lower() == mine else n for n in names]
    shown = list(dict.fromkeys(shown))
    if not shown:
        return "an unknown sender"
    if len(shown) > most:
        return ", ".join(shown[:most]) + f" and {len(shown) - most} more"
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def to_words(to: str, me: str | None) -> str:
    """An email's To line for its page: its names split at ";" and joined with commas, the owner as "you"."""
    mine = (me or "").strip().lower()
    names = [n.strip() for n in re.split(r"[;]", to or "") if n.strip()]
    return ", ".join("you" if mine and n.lower() == mine else n for n in names)
