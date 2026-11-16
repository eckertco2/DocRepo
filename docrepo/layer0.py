"""Email layer 0 (mods log round 1, M0005, M0024): an Outlook email's parts, each a row of its own in the capture window.

Adding an email finds its attachments, the links in its body and the pictures in its body. Each becomes a row with
its own description and a Keep tick box. Email addresses (mailto:) are left out, Outlook's Safe Links are turned
back into the real address, and repeated links are dropped. A picture is an attachment the body shows (an image
whose address is cid: and the attachment's content ID). Outlook marks most of those hidden, so hidden doesn't mean
a signature: a hidden attachment the body doesn't show is left out, as before layer 0, and pictures under
SMALL_BYTES start unticked, as probable logos and signature pictures. What layer 0 kept and left out becomes a
line in the capture's capture.md (``email_layer_0``), for later layers to build on.

**Always keep and Never keep** (release 5.146, the design workspace's ``docs/mods/email-link-filter-plan.md``, decisions
635 to 640). Settings' two lists of sites (``LinkRules``, from ``links_keep``, ``links_drop`` and ``other_links``) sort
the links on their real address, after Safe Links: a link on Never keep gets no row and is counted as a blocked link; one
on Always keep gets its row, ticked; one on neither is kept, shown unticked or left out (counted as an other link), as
Other links says. An entry is a domain, which covers its subdomains, or a domain and the start of a path; the longer
entry wins when both lists match, and a tie goes to Never keep (``rule_for``). Never keep starts with the links a meeting
invitation carries (``DEFAULT_DROP``). Only an email's links are sorted: a link the owner adds never is.

The email's HTML is read with the standard library's parser, as data: nothing in it is run, opened or fetched.
Nothing here talks to Outlook, so it's tested with made-up emails.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from docrepo.links import is_link, link_name

if TYPE_CHECKING:
    from docrepo.config import Settings
    from docrepo.save import Attachment, EmailItem

#: Pictures smaller than this start unticked: logos and signature pictures are usually a few KB.
SMALL_BYTES = 10 * 1024
_SAFE_LINKS = re.compile(r"(?:^|\.)safelinks\.protection\.outlook\.com$", re.IGNORECASE)
_TEXT_LINK = re.compile(r"(?:https?://|mailto:)[^\s<>\"]+", re.IGNORECASE)
KINDS = ("attachment", "link", "picture")

#: Never keep's start (decision 639): the links a meeting invitation carries. Always keep starts empty: the company's own
#: sites can't be named in the public code.
DEFAULT_DROP = ("zoom.us", "teams.microsoft.com/l/meetup-join", "teams.microsoft.com/meet", "teams.microsoft.com/meetingOptions",
                "teams.live.com/meet", "dialin.teams.microsoft.com", "aka.ms/JoinTeamsMeeting", "meet.google.com", "webex.com",
                "gotomeeting.com")
#: Other links (decision 637): what a link on neither list gets. Keep them is the default, so nothing changes until it's set.
OTHER_LINKS = {"keep": "Keep them", "untick": "Show them unticked", "leave": "Leave them out"}
#: A list entry's domain: labels of letters, digits and hyphens, with a dot at least, ending in a name (not a number).
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class Part:
    """One part of an email: an attachment, a link in its body, or a picture in its body."""

    kind: str  # attachment, link or picture
    name: str
    attachment: Attachment | None = None  # an attachment's or picture's file, saved with the capture
    url: str = ""  # a link's address
    size: int = 0  # an attachment's or picture's size in bytes, as Outlook gives it
    keep: bool = True  # whether its row starts ticked
    safe: bool = False  # a link turned back from Outlook's Safe Links
    small: bool = False  # a picture under SMALL_BYTES
    pasted: bool = False  # a picture pasted into the capture window (release 5.27, decision 129), not an email's
    rule: str = ""  # a link's list (release 5.146): "keep" on Always keep, "other" on neither, "" when no lists were given


@dataclass(frozen=True)
class Found:
    """What layer 0 found in an email: its parts, and how many things it left out."""

    parts: tuple[Part, ...]
    addresses: int = 0  # mailto: links
    repeats: int = 0  # links already found
    other: int = 0  # links that aren't web addresses, such as tel: or a place within the email
    hidden: int = 0  # hidden attachments the body doesn't show
    blocked: int = 0  # links on Never keep (release 5.146)
    left: int = 0  # links on neither list, with Other links at Leave them out: counted with ``other`` on the line


# ---- Always keep and Never keep (release 5.146, decisions 635 to 640) ----
def tidy_entry(text: str) -> str:
    """A list entry as it's kept: ``http://`` or ``https://``, a leading ``www.`` (or ``*.``) and a lone ``/`` at the end
    taken off, and its domain in lower case. Its path keeps its case; matching ignores case."""
    t = text.strip()
    t = re.sub(r"^https?://", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(?:\*\.|www\.)", "", t, flags=re.IGNORECASE)
    host, slash, path = t.partition("/")
    return host.lower() + (slash + path if path.strip("/") else "")


def entry_problem(text: str) -> str:
    """Why a list entry can't be used, or "" when it can: a domain (``zoom.us``), or a domain and the start of a path
    (``teams.microsoft.com/l/meetup-join``), with no spaces."""
    host, _, path = tidy_entry(text).partition("/")
    if not _DOMAIN.match(host):
        return "it isn't a domain"
    if any(ch.isspace() for ch in path):
        return "it has a space in it"
    return ""


def tidy_list(lines: Iterable[str]) -> list[str]:
    """A list's entries as they're kept: each tidied, blank lines and repeats (in any case) left out, in order."""
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        t = tidy_entry(line)
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def list_problem(lines: Iterable[str]) -> tuple[int, str, str] | None:
    """The first line of a list that can't be used, as (its line number, from 1; the line; why), or None."""
    for n, line in enumerate(lines, 1):
        if line.strip():
            why = entry_problem(line)
            if why:
                return n, line.strip(), why
    return None


@lru_cache(maxsize=512)
def _entry(text: str) -> tuple[str, str] | None:
    """A list entry as it's matched: its domain, and its path's start in lower case. None for one that can't be used."""
    if entry_problem(text):
        return None
    host, slash, path = tidy_entry(text).partition("/")
    return host, (slash + path).lower()


@dataclass(frozen=True)
class LinkRules:
    """Settings' Always keep, Never keep and Other links (decisions 635 to 637), for layer 0. With no lists and Keep them,
    as ``LinkRules()``, every web link is kept, as before release 5.146."""

    keep: tuple[str, ...] = ()
    drop: tuple[str, ...] = ()
    other: str = "keep"

    @classmethod
    def of(cls, settings: Settings) -> LinkRules:
        return cls(tuple(settings.links_keep), tuple(settings.links_drop), settings.other_links)


def domain_of(url: str) -> str:
    """A link's domain as the row's menu names it (decision 638): its host, after Safe Links, without ``www.``."""
    host = urlsplit(unwrap(url)[0]).hostname or ""
    return host[4:] if host.startswith("www.") else host


def put_on(keep: list[str], drop: list[str], domain: str, which: str) -> tuple[list[str], list[str]]:
    """Always keep and Never keep with ``domain`` put on one ("keep" or "drop") from a row's menu (decision 638): at the
    end, if it isn't there yet, and taken off the other, so the two lists never name the same entry."""
    domain = tidy_entry(domain)
    on, off = (list(keep), list(drop)) if which == "keep" else (list(drop), list(keep))
    off = [x for x in off if x.lower() != domain.lower()]
    if domain.lower() not in {x.lower() for x in on}:
        on.append(domain)
    return (on, off) if which == "keep" else (off, on)


def _longest(host: str, rest: str, entries: tuple[str, ...]) -> int:
    """The length of the longest entry that matches a link, or 0: an entry matches when its domain is the link's host or
    a domain the host is under, and its path, if it has one, starts what follows the host."""
    best = 0
    for text in entries:
        e = _entry(text)
        if e is None:
            continue
        domain, path = e
        if (host == domain or host.endswith("." + domain)) and rest.startswith(path):
            best = max(best, len(domain) + len(path))
    return best


def _rule(url: str, rules: LinkRules) -> str:
    """``rule_for`` on an address already unwrapped."""
    url = url.strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    rest = url.split("://", 1)[-1][len(parts.netloc):].lower()
    keep, drop = _longest(host, rest, rules.keep), _longest(host, rest, rules.drop)
    if drop and drop >= keep:
        return "drop"  # the longer entry wins, and a tie goes to Never keep (decision 636)
    return "keep" if keep else ""


def rule_for(url: str, rules: LinkRules) -> str:
    """Which list a link is on, by its real address (Safe Links unwrapped first): "drop" for Never keep, "keep" for Always
    keep, "" for neither. When both match, the longer entry wins; an exact tie goes to Never keep (decision 636)."""
    return _rule(unwrap(url)[0], rules)


class _BodyReader(HTMLParser):
    """Collects each link's address and each cid: picture from an email's HTML body."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.cids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): (v or "").strip() for k, v in attrs}
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        elif tag == "img" and values.get("src", "").lower().startswith("cid:"):
            self.cids.append(content_id(values["src"][4:]))


def content_id(value: str) -> str:
    """A content ID as compared: without angle brackets, in lower case."""
    return value.strip().strip("<>").strip().lower()


def read_body(html: str) -> tuple[list[str], list[str]]:
    """The addresses of the links in an HTML body, in order, and the content IDs of its cid: pictures."""
    reader = _BodyReader()
    try:
        reader.feed(html or "")
        reader.close()
    except Exception:  # noqa: BLE001, S110 - a broken body gives what was read before the break
        pass
    return reader.hrefs, reader.cids


def unwrap(href: str) -> tuple[str, bool]:
    """A link's real address, and whether it was wrapped in Outlook's Safe Links (``…safelinks…/?url=<address>``)."""
    parts = urlsplit(href.strip())
    if parts.hostname and _SAFE_LINKS.search(parts.hostname):
        real = parse_qs(parts.query).get("url")
        if real and real[0].strip():
            return real[0].strip(), True
    return href.strip(), False


def read_text(body: str) -> list[str]:
    """The addresses in a plain-text body, in order: Outlook writes a link out there as "text <https://…>". Punctuation
    ending a sentence after an address isn't part of it."""
    return [m.rstrip(".,;:!?)]'") for m in _TEXT_LINK.findall(body or "")]


def find(email: EmailItem, rules: LinkRules | None = None) -> Found:
    """The email's parts, attachments first, then the links in its body, then the pictures in its body. With no HTML
    body, as a .msg can have (release 5.33, the knowledge base's decision 23), the links come from the plain text, and
    the pictures are the hidden attachments with a content ID. ``rules`` sort the links (release 5.146): every caller that
    reads an email passes Settings' (decision 640); with none, every web link is kept."""
    if email.html:
        hrefs, cids = read_body(email.html)
    else:
        hrefs, cids = read_text(email.body), [content_id(a.content_id) for a in email.attachments if a.hidden and a.content_id]
    shown = set(cids)
    attachments: list[Part] = []
    pictures: list[Part] = []
    hidden = 0
    for a in email.attachments:
        if a.content_id and content_id(a.content_id) in shown:
            small = 0 < a.size < SMALL_BYTES
            pictures.append(Part("picture", a.name, a, size=a.size, keep=not small, small=small))
        elif a.hidden:
            hidden += 1
        else:
            attachments.append(Part("attachment", a.name, a, size=a.size))
    links: list[Part] = []
    seen: set[str] = set()
    addresses = repeats = other = blocked = left = 0
    for href in hrefs:
        url, safe = unwrap(href)
        if href.lower().startswith("mailto:"):
            addresses += 1
        elif not is_link(url):
            other += 1
        elif url in seen:
            repeats += 1
        else:
            seen.add(url)
            rule = _rule(url, rules) if rules is not None else ""
            if rule == "drop":
                blocked += 1
            elif rule == "keep":
                links.append(Part("link", link_name(url), url=url, safe=safe, rule="keep"))
            elif rules is None:
                links.append(Part("link", link_name(url), url=url, safe=safe))
            elif rules.other == "leave":
                left += 1
            else:
                links.append(Part("link", link_name(url), url=url, safe=safe, keep=rules.other != "untick", rule="other"))
    return Found(tuple(attachments + links + pictures), addresses, repeats, other, hidden, blocked, left)


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def line(found: Found, kept: list[str], unticked: int) -> str:
    """The email layer 0 line: what was kept (``kept`` holds each kept part's kind) and what was left out, such as
    "2 attachments, 2 links and 1 picture kept. Left out: 1 email address, 1 repeated link and 1 unticked row.". Links on
    Never keep are blocked links; links Other links leaves out are other links, as links that aren't web addresses are
    (release 5.146, decisions 636 and 637)."""
    n = Counter(kept)
    got = _and_list([_count(n[k], k) for k in KINDS if n[k]])
    others = found.other + found.left
    out = _and_list([x for x in (
        found.addresses and _count(found.addresses, "email address", "email addresses"),
        found.repeats and _count(found.repeats, "repeated link"),
        found.blocked and _count(found.blocked, "blocked link"),
        others and _count(others, "other link"),
        found.hidden and _count(found.hidden, "hidden attachment"),
        unticked and _count(unticked, "unticked row"),
    ) if x])
    return f"{got + ' kept' if got else 'Nothing kept'}.{' Left out: ' + out + '.' if out else ''}"


def size_text(size: int) -> str:
    """A size as the capture window shows it: "412 KB", or "2.4 MB" from a megabyte up."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"
