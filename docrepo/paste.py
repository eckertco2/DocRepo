"""Pasting into the content text: lists from OneNote, Word and Outlook keep their bullets (mods log round 1, M0022).

The content text box is plain text. A list copied from OneNote has its bullets
only in the clipboard's HTML; its plain text has none. So when the HTML holds a
list, it's turned into plain text here: each item a "- item" line (numbered
items keep "1." and so on), indented two spaces a level. Word and Outlook mark
their list paragraphs with ``mso-list`` and put the bullet in a hidden span,
which is read the same way. Bullet characters at the start of plain-text lines
("•", "·", "▪" and so on) become "- " too.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

BLOCKS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote", "pre", "dt", "dd", "section", "article"}
SKIP = {"style", "script", "head", "title", "xml"}
_SPACES = re.compile(r"[ \t\r\n ]+")
_MARKER = re.compile(r"\(?[0-9A-Za-z]{1,3}[.)]")  # "1.", "a)", "(iv)": a numbered item's own number


def has_list(html: str) -> bool:
    """Whether clipboard HTML holds a list: HTML list items, or Word's and Outlook's list paragraphs."""
    return bool(re.search(r"<li[\s>]|mso-list\s*:", html, re.I))


class _ListText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.cur: list[str] = []
        self.prefix = ""
        self.lists: list[list] = []  # [tag, count] for each open <ul> or <ol>
        self.skip = 0
        self.marker: list[str] | None = None  # Word's hidden bullet text, inside <![if !supportLists]>
        self.indent = ""
        self.empty_block = False

    def flush(self) -> None:
        text = _SPACES.sub(" ", "".join(self.cur)).strip()
        if text:
            self.lines.append(self.prefix + text)
        elif self.empty_block:
            self.lines.append("")  # an empty paragraph is a blank line
        self.cur, self.prefix, self.empty_block = [], "", False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP:
            self.skip += 1
            return
        if tag in ("ul", "ol"):
            self.flush()
            start = dict(attrs).get("start") or "1"
            self.lists.append([tag, int(start) - 1 if start.isdigit() else 0])
        elif tag == "li":
            self.flush()
            kind = self.lists[-1] if self.lists else ["ul", 0]
            if kind[0] == "ol":
                kind[1] += 1
            self.prefix = "  " * max(len(self.lists) - 1, 0) + (f"{kind[1]}. " if kind[0] == "ol" else "- ")
        elif tag in ("p", "div"):
            self.flush()
            level = re.search(r"mso-list\s*:\s*\S+\s+level(\d+)", dict(attrs).get("style") or "", re.I)
            self.indent = "  " * (int(level.group(1)) - 1) if level else ""
            self.prefix = self.indent + "- " if level else ""
            self.empty_block = not level
        elif tag in BLOCKS:
            self.flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip = max(self.skip - 1, 0)
        elif tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
        elif tag == "li" or tag in BLOCKS:
            self.flush()

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.marker is not None:
            self.marker.append(data)
        else:
            self.cur.append(data)

    def _list_marker(self, text: str) -> None:
        d = text.strip().lower()
        if d.startswith("[if !supportlists]") or d.startswith("if !supportlists"):
            self.marker = []
        elif d in ("[endif]", "endif") and self.marker is not None:
            mark = _SPACES.sub("", "".join(self.marker))
            if _MARKER.fullmatch(mark):
                self.prefix = self.indent + mark + " "
            self.marker = None

    def handle_comment(self, data: str) -> None:  # <!--[if !supportLists]-->
        self._list_marker(data)

    def unknown_decl(self, data: str) -> None:  # <![if !supportLists]>
        self._list_marker(data)


def html_to_text(html: str) -> str:
    """Clipboard HTML as plain text, with each list item on its own "- " or "1. " line."""
    parser = _ListText()
    parser.feed(html)
    parser.close()
    parser.flush()
    text = "\n".join(parser.lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


_BULLET_LINE = re.compile(r"^([ \t]*)(?:[•·▪◦‣§●○■□➢➤✓]|o(?=\t))[ \t ]+", re.M)


def bullets_to_dashes(text: str) -> str:
    """Plain text with bullet characters starting its lines ("•\\tItem") as "- Item", two spaces for each tab before it."""
    return _BULLET_LINE.sub(lambda m: m.group(1).replace("\t", "  ") + "- ", text)
