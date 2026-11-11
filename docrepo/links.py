"""Links as files (mods log round 1, M0001): a web or SharePoint link kept as a document.

A link on a line of its own in the content text, or added with Add link…, gets a
file row like a file path, and is kept as a document whose original is the link.
DocRepo only keeps the address: it never fetches a link (the app makes no network
connections), so a link has no extracted text, and it never opens one in the
browser. The browse tool's Copy link puts it on the clipboard.

Since release 5.66 (round 6's item 89) an address is read the same way wherever it
comes from (``read_address``): what came round it is taken off, ``www.`` gets
``https://``, a ``file:`` address is the path it names, and anything else says
why it isn't kept. A folder is kept too, as a document whose original ends in
``\\`` (decision 318): DocRepo keeps where it is and reads nothing in it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlsplit

#: A line that is only a web link: http or https, with no spaces.
LINK_LINE = re.compile(r"^https?://[^\s<>\"]+$", re.IGNORECASE)
#: A web address inside words, such as in a note (release 5.67): tidied with ``read_address`` before it's used.
ADDRESS = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_FILE_NAME = re.compile(r"^[^/\\]+\.[A-Za-z0-9]{1,5}$")
NAME_CHARS = 100
#: Why a link has no text, as the document page shows it.
NO_TEXT = "it's a link, and DocRepo never fetches links: it only opens one in your browser when you click it"
#: Why a folder has no text (release 5.66).
FOLDER_TEXT = "it's a folder: DocRepo keeps where it is, and reads nothing in it"
#: What DocRepo keeps, for the messages that say why something isn't kept.
KEEPS = "DocRepo keeps web links (http or https), files and folders"

_WEB = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]+):", re.IGNORECASE)  # two letters at least, so C: is a drive
_PATH = re.compile(r"^(?:\\\\[^\\\s]|[A-Za-z]:[\\/])")
_WRAPS = (('"', '"'), ("<", ">"), ("'", "'"), ("“", "”"))


def is_link(original: str | None) -> bool:
    """True for a document's original, or a line of text, that is a web link rather than a file path."""
    return bool(original and LINK_LINE.match(original.strip()))


def is_folder(original: str | None) -> bool:
    """True for a document's original that is a folder: a path ending in ``\\`` (release 5.66)."""
    return bool(original) and original.endswith("\\") and not is_link(original)


def keeps_no_text(original: str | None) -> bool:
    """A link or a folder: kept by where it is, with no text, no saved copy and nothing to extract."""
    return is_link(original) or is_folder(original)


def folder_original(path: str) -> str:
    """A folder's path as its document keeps it, with one ``\\`` at the end."""
    return path.rstrip("\\/") + "\\"


def link_name(url: str) -> str:
    """How a link is listed: the file it points to when its address names one ("Pump spec.docx", from SharePoint's
    ``file=`` or else the path's last part), else its host ("example.sharepoint.com")."""
    parts = urlsplit(url.strip())
    candidates = [*parse_qs(parts.query).get("file", []), unquote(parts.path.rstrip("/").rpartition("/")[2])]
    name = next((c.strip() for c in candidates if _FILE_NAME.match(c.strip())), "") or parts.hostname or url.strip()
    return name if len(name) <= NAME_CHARS else name[: NAME_CHARS - 1].rstrip() + "…"


def short_name(name: str) -> str:
    """A name a link was copied with, on one line and no longer than a link's own name may be."""
    name = " ".join((name or "").split())
    return name if len(name) <= NAME_CHARS else name[: NAME_CHARS - 1].rstrip() + "…"


def folder_name(original: str) -> str:
    """How a folder is listed: its own name, or the whole path for a drive or a share."""
    path = original.rstrip("\\")
    return path.rpartition("\\")[2] if path.count("\\") > (3 if path.startswith("\\\\") else 0) else path + "\\"


# ---- reading an address as typed, pasted or dropped (release 5.66) ----
@dataclass(frozen=True)
class Address:
    """What some text is as an address: ``kind`` "link" (a web link), "path" (a file or folder, not yet looked for), or
    "refused", with ``why`` in words."""

    kind: str
    value: str = ""
    why: str = ""


def _unwrap(text: str) -> str:
    """Quotes and angle brackets round an address taken off, as often as they're there."""
    t = text.strip()
    while len(t) > 1 and any(t.startswith(a) and t.endswith(b) for a, b in _WRAPS):
        t = t[1:-1].strip()
    return t


def _trim_end(url: str) -> str:
    """A full stop, comma, semicolon, colon, ! or ? after a web link taken off, and a closing bracket that has no opening
    one in the address: they belong to the sentence it was in."""
    while url:
        last = url[-1]
        if last in ".,;:!?'\"":
            url = url[:-1]
        elif last in ")]" and url.count({")": "(", "]": "["}[last]) < url.count(last):
            url = url[:-1]
        else:
            break
    return url


def file_url_path(url: str) -> str | None:
    """The path a ``file:`` address names: ``file:///C:/Docs/a%20b.pdf`` is ``C:\\Docs\\a b.pdf``, and
    ``file://server/share/a.pdf`` is ``\\\\server\\share\\a.pdf``. None when it names no drive or share."""
    parts = urlsplit(url.strip())
    path = unquote(parts.path)
    if parts.netloc and parts.netloc.lower() != "localhost":
        return "\\\\" + parts.netloc + path.replace("/", "\\")
    path = path.lstrip("/")
    return path.replace("/", "\\") if re.match(r"^[A-Za-z]:(?:/|$)", path) else None


def read_address(text: str, one: bool = True) -> Address:
    """What ``text`` is as an address. ``one``: it's a box for one address (the landing row, Add link), so an http or
    https address's spaces are its own and become %20; elsewhere a line with a space in it is words.

    OneNote's Copy link brings two lines, a web link and an ``onenote:`` one: the web link is taken (decision 321)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return Address("refused", why="There's no link or path to add.")
    if len(lines) > 1:
        webs = [_unwrap(line) for line in lines if _WEB.match(_unwrap(line))]
        if not webs:
            return Address("refused", why="That's more than one line. Add one link or path at a time.")
        lines = webs[:1]
    t = _unwrap(lines[0])
    if t.lower().startswith("www."):
        t = "https://" + t
    if re.match(r"^https?://", t, re.IGNORECASE):
        t = _trim_end(t)
        if one:
            t = re.sub(r"\s", "%20", t)
        if LINK_LINE.match(t) and urlsplit(t).hostname:
            return Address("link", t)
        return Address("refused", why="That link has a space or a character a link can't have. " + KEEPS + ".")
    if t.lower().startswith("file:"):
        path = file_url_path(t)
        return Address("path", path) if path else Address("refused", why="That file: address doesn't name a drive or a share.")
    if _PATH.match(t):
        return Address("path", t.replace("/", "\\") if re.match(r"^[A-Za-z]:/", t) else t)
    scheme = _SCHEME.match(t)
    if scheme:
        return Address("refused", why=f"That's a {scheme.group(1).lower()}: link. {KEEPS}.")
    return Address("refused", why="That isn't a link or a path: a link starts with http://, https:// or www., and a path with a "
                                  "drive (C:\\) or \\\\server.")


#: A link address typed with no http:// or https:// (release 5.134, decision 546): a server's name, with its port if it has
#: one, then a / or a ?, as "intranet/record?" or "records.example.com/view?id=" are typed in a browser's address bar.
_BARE_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*(?::\d+)?[/?]")


def full_template(template: str | None) -> str:
    """A reference field's link address with its http:// or https:// in front (release 5.134, decision 546). One typed
    without them is read as a browser's address bar reads it: a server's name and a / take http://
    ("intranet/record?" is http://intranet/record?), and www. takes https://, as Add link gives it. Anything else, such
    as a path or a mailto: address, is left as it was, for ``check_link_template`` to refuse."""
    t = (template or "").strip()
    if not t or re.match(r"^https?://", t, re.IGNORECASE):
        return t
    if t.lower().startswith("www."):
        return "https://" + t
    return "http://" + t if _BARE_HOST.match(t) else t


def reference_link(template: str | None, value: str | None) -> str:
    """A reference field's link (release 5.67, round 6's decision 320): its value put into the link address Settings
    gives the field, where ``{}`` is or at the end, encoded as an address needs. "" when either is empty, or what they
    make isn't a web link. Since release 5.134 an address typed with no http:// or https:// gets one (``full_template``)."""
    template, value = full_template(template), (value or "").strip()
    if not template or not value:
        return ""
    v = quote(value, safe="")
    made = template.replace("{}", v) if "{}" in template else template + v
    return made if LINK_LINE.match(made) and urlsplit(made).hostname else ""


def check_link_template(template: str) -> str:
    """Why a reference field's link address can't be used, in words, or "" when it can: it must be an http or https
    address, or a server's name and a / that takes http:// (release 5.134), with ``{}`` where the value goes or the value
    going at its end."""
    t = full_template(template)
    if not t:
        return ""
    if not re.match(r"^https?://", t, re.IGNORECASE):
        return "starts with http://, https:// or a server's name and a /"
    if t.count("{}") > 1:
        return "has {} once at most"
    if not reference_link(t, "1234"):
        return "is a web address with no spaces"
    return ""


def link_of_line(line: str) -> str | None:
    """The web link a line of the content text is, tidied, or None: a link on a line of its own, with or without angle
    brackets round it or a full stop after it, or one starting www. A line with a space in it is words."""
    t = _unwrap(line)
    if not _WEB.match(t):
        return None
    a = read_address(t, one=False)
    return a.value if a.kind == "link" else None
