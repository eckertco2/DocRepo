"""Email layer 0 (mods log round 1, M0005, M0024): an Outlook email's parts, each a row of its own in the capture window.

Adding an email finds its attachments, the links in its body and the pictures in its body. Each becomes a row with
its own description and a Keep tick box. Email addresses (mailto:) are left out, Outlook's Safe Links are turned
back into the real address, and repeated links are dropped. A picture is an attachment the body shows (an image
whose address is cid: and the attachment's content ID). Outlook marks most of those hidden, so hidden doesn't mean
a signature: a hidden attachment the body doesn't show is left out, as before layer 0, and pictures under
SMALL_BYTES start unticked, as probable logos and signature pictures. What layer 0 kept and left out becomes a
line in the capture's capture.md (``email_layer_0``), for later layers to build on.

The email's HTML is read with the standard library's parser, as data: nothing in it is run, opened or fetched.
Nothing here talks to Outlook, so it's tested with made-up emails.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from docrepo.links import is_link, link_name

if TYPE_CHECKING:
    from docrepo.save import Attachment, EmailItem

#: Pictures smaller than this start unticked: logos and signature pictures are usually a few KB.
SMALL_BYTES = 10 * 1024
_SAFE_LINKS = re.compile(r"(?:^|\.)safelinks\.protection\.outlook\.com$", re.IGNORECASE)
KINDS = ("attachment", "link", "picture")


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


@dataclass(frozen=True)
class Found:
    """What layer 0 found in an email: its parts, and how many things it left out."""

    parts: tuple[Part, ...]
    addresses: int = 0  # mailto: links
    repeats: int = 0  # links already found
    other: int = 0  # links that aren't web addresses, such as tel: or a place within the email
    hidden: int = 0  # hidden attachments the body doesn't show


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
    except Exception:  # noqa: BLE001 - a broken body gives what was read before the break
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


def find(email: EmailItem) -> Found:
    """The email's parts, attachments first, then the links in its body, then the pictures in its body."""
    hrefs, cids = read_body(email.html)
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
    addresses = repeats = other = 0
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
            links.append(Part("link", link_name(url), url=url, safe=safe))
    return Found(tuple(attachments + links + pictures), addresses, repeats, other, hidden)


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def line(found: Found, kept: list[str], unticked: int) -> str:
    """The email layer 0 line: what was kept (``kept`` holds each kept part's kind) and what was left out, such as
    "2 attachments, 2 links and 1 picture kept. Left out: 1 email address, 1 repeated link and 1 unticked row."."""
    n = Counter(kept)
    got = _and_list([_count(n[k], k) for k in KINDS if n[k]])
    out = _and_list([x for x in (
        found.addresses and _count(found.addresses, "email address", "email addresses"),
        found.repeats and _count(found.repeats, "repeated link"),
        found.other and _count(found.other, "other link"),
        found.hidden and _count(found.hidden, "hidden attachment"),
        unticked and _count(unticked, "unticked row"),
    ) if x])
    return f"{got + ' kept' if got else 'Nothing kept'}.{' Left out: ' + out + '.' if out else ''}"


def size_text(size: int) -> str:
    """A size as the capture window shows it: "412 KB", or "2.4 MB" from a megabyte up."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"
