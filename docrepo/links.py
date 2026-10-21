"""Links as files (mods log round 1, M0001): a web or SharePoint link kept as a document.

A link on a line of its own in the content text, or added with Add link…, gets a
file row like a file path, and is kept as a document whose original is the link.
DocRepo only keeps the address: it never fetches a link (the app makes no network
connections), so a link has no extracted text, and it never opens one in the
browser. The browse tool's Copy link puts it on the clipboard.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

#: A line that is only a web link: http or https, with no spaces.
LINK_LINE = re.compile(r"^https?://[^\s<>\"]+$", re.IGNORECASE)
_FILE_NAME = re.compile(r"^[^/\\]+\.[A-Za-z0-9]{1,5}$")
NAME_CHARS = 100
#: Why a link has no text, as the document page shows it.
NO_TEXT = "it's a link, and DocRepo never opens or fetches links"


def is_link(original: str | None) -> bool:
    """True for a document's original, or a line of text, that is a web link rather than a file path."""
    return bool(original and LINK_LINE.match(original.strip()))


def link_name(url: str) -> str:
    """How a link is listed: the file it points to when its address names one ("Pump spec.docx", from SharePoint's
    ``file=`` or else the path's last part), else its host ("example.sharepoint.com")."""
    parts = urlsplit(url.strip())
    candidates = [*parse_qs(parts.query).get("file", []), unquote(parts.path.rstrip("/").rpartition("/")[2])]
    name = next((c.strip() for c in candidates if _FILE_NAME.match(c.strip())), "") or parts.hostname or url.strip()
    return name if len(name) <= NAME_CHARS else name[: NAME_CHARS - 1].rstrip() + "…"
