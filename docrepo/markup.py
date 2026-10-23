"""Formatted content text (mods log round 2, M0045, release 5.7).

A formatted capture's content text is kept in its capture.md as a small, readable piece of Markdown, one block per line:

- ``**bold**``, ``*italic*``, ``~~strikethrough~~``, ``<u>underline</u>`` and ``<mark class="yellow">highlight</mark>``
  (yellow, green or pink);
- a list item: two spaces per level, then ``- `` or a number and ``. ``;
- any other line is a line of text, and an empty line stays empty.

A backslash keeps a character as itself: ``\\*``, ``\\~``, ``\\<``, and ``\\-`` or ``1\\.`` at a line's start, so a line of
text that starts like a list item stays text. A backslash before anything else is just a backslash, so paths read as
they are. Whatever reads content text for its words (Parse and populate, titles, search) reads ``to_plain``; pages and
the editor show ``to_html``. A capture with no formatting is kept as plain text, as before, and capture.md says which
(``content_format``).
"""
from __future__ import annotations

import html
import re

#: The highlight colours, by name, as pages and the editor show them.
HIGHLIGHTS = {"yellow": "#fff1a8", "green": "#cdeccd", "pink": "#f8d0e3"}
#: After a backslash, these stand for themselves.
ESCAPABLE = frozenset("\\*~<-.")
LIST_LINE = re.compile(r"^((?:  )*)(- |(\d+)\. )")
_LIKE_LIST = re.compile(r"^(\s*)(-|\d+\.)(?=\s|\Z)")
_TAG = re.compile(r'<u>|</u>|<mark(?: class="(\w+)")?>|</mark>')
#: The marks, in the order they're written and nested.
MARKS = ("b", "i", "s", "u", "mark")
_PAIRS = {"b": "**", "i": "*", "s": "~~"}


# ---- writing ----
def escape_inline(text: str) -> str:
    """Text as markup that reads as the same text, within a line."""
    out = []
    for i, ch in enumerate(text):
        if ch in "*~<":
            out.append("\\" + ch)
        elif ch == "\\":
            nxt = text[i + 1] if i + 1 < len(text) else ""
            out.append("\\\\" if nxt in ESCAPABLE or not nxt else "\\")
        else:
            out.append(ch)
    return "".join(out)


def escape_line_start(line: str) -> str:
    """A line of text, already escaped within, that would read as a list item: its marker escaped, so it stays text."""
    m = _LIKE_LIST.match(line)
    if not m:
        return line
    marker = m.group(2)
    return m.group(1) + ("\\-" if marker == "-" else marker[:-1] + "\\.") + line[m.end():]


def escape(text: str) -> str:
    """Plain text as markup that reads as the same text."""
    return "\n".join(escape_line_start(escape_inline(line)) for line in text.split("\n"))


def from_list_lines(text: str) -> str:
    """Plain text whose "- item" and "1. item" lines (indented two spaces a level) are list items, as markup with real
    lists: what pasting a Word or Outlook list gives (``paste.html_to_text``)."""
    out = []
    for line in text.split("\n"):
        m = LIST_LINE.match(line)
        out.append(line[:m.end()] + escape_inline(line[m.end():]) if m else escape_line_start(escape_inline(line)))
    return "\n".join(out)


def marks_text(segments: list[tuple[str, frozenset[str], str | None]]) -> str:
    """One line's text from (text, marks, highlight colour) segments, already escaped. Each change writes only the marks
    that change: a mark is a switch, on then off, so a run of stars never reads back as other marks ("****" would read as
    bold twice, where "close italic, close bold, open italic" meant something else)."""
    out: list[str] = []
    now: set[str] = set()
    colour_now: str | None = None
    for text, marks, colour in [*segments, ("", frozenset(), None)]:
        recolour = "mark" in marks and "mark" in now and colour != colour_now
        for k in reversed(MARKS):  # closing innermost first, then opening outermost first, keeps them nested
            if k in now and (k not in marks or (k == "mark" and recolour)):
                out.append(_close(k))
        for k in MARKS:
            if k in marks and (k not in now or (k == "mark" and recolour)):
                out.append(_open(k, colour))
        now, colour_now = set(marks), colour
        out.append(text)
    return "".join(out)


def _open(mark: str, colour: str | None) -> str:
    return _PAIRS.get(mark) or ("<u>" if mark == "u" else f'<mark class="{colour or "yellow"}">')


def _close(mark: str) -> str:
    return _PAIRS.get(mark) or ("</u>" if mark == "u" else "</mark>")


# ---- reading ----
def _segments(text: str) -> list[tuple[str, frozenset[str], str | None]]:
    """A line's text (after any list marker) as (text, marks, highlight colour) segments."""
    out: list[tuple[str, frozenset[str], str | None]] = []
    marks: set[str] = set()
    colour: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(("".join(buf), frozenset(marks), colour))
            buf.clear()

    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in ESCAPABLE:
            buf.append(text[i + 1])
            i += 2
            continue
        token = "**" if text.startswith("**", i) else "~~" if text.startswith("~~", i) else "*" if ch == "*" else None
        if token:
            flush()
            marks ^= {{"**": "b", "~~": "s", "*": "i"}[token]}
            i += len(token)
            continue
        if ch == "<":
            m = _TAG.match(text, i)
            if m:
                flush()
                tag = m.group(0)
                if tag == "<u>":
                    marks.add("u")
                elif tag == "</u>":
                    marks.discard("u")
                elif tag == "</mark>":
                    marks.discard("mark")
                    colour = None
                else:
                    marks.add("mark")
                    colour = m.group(1) if m.group(1) in HIGHLIGHTS else "yellow"
                i = m.end()
                continue
        buf.append(ch)
        i += 1
    flush()
    return out


def to_plain(markup: str) -> str:
    """The plain text: marks dropped, escapes undone. A list item keeps its marker and indent ("  - item")."""
    lines = []
    for line in markup.split("\n"):
        m = LIST_LINE.match(line)
        head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
        lines.append(head + "".join(t for t, _, _ in _segments(rest)))
    return "\n".join(lines)


def is_formatted(markup: str) -> bool:
    """Whether the markup has any list or mark, so it needs keeping as markup rather than as plain text."""
    return any(LIST_LINE.match(line) or any(marks for _, marks, _ in _segments(line)) for line in markup.split("\n"))


def inline_html(text: str) -> str:
    """One line's text as HTML: its marks as tags, the rest escaped."""
    out = []
    for part, marks, colour in _segments(text):
        piece = html.escape(part, quote=False)
        for k in reversed(MARKS):
            if k in marks:
                tag = {"b": "b", "i": "i", "s": "s", "u": "u"}.get(k)
                piece = (f"<{tag}>{piece}</{tag}>" if tag else
                         f'<span style="background-color:{HIGHLIGHTS.get(colour or "yellow", HIGHLIGHTS["yellow"])}">{piece}</span>')
        out.append(piece)
    return "".join(out)


def to_html(markup: str) -> str:
    """The markup as HTML, for the editor and the pages: a paragraph per line, and lists nested by level."""
    out: list[str] = []
    stack: list[list] = []  # open lists: [kind, li_open]

    def close_to(depth: int) -> None:
        while len(stack) > depth:
            kind, li_open = stack.pop()
            out.append(("</li>" if li_open else "") + f"</{kind}>")

    for line in markup.split("\n"):
        m = LIST_LINE.match(line)
        if not m:
            close_to(0)
            out.append(f'<p style="margin:0; white-space:pre-wrap">{inline_html(line) or "<br>"}</p>')
            continue
        level, kind = len(m.group(1)) // 2, "ol" if m.group(3) else "ul"
        close_to(level + 1)
        if len(stack) == level + 1 and stack[-1][0] != kind:
            close_to(level)
        if len(stack) == level + 1 and stack[-1][1]:
            out.append("</li>")
            stack[-1][1] = False
        while len(stack) < level + 1:
            out.append(f'<{kind} style="margin-top:0; margin-bottom:0">')
            stack.append([kind, False])
        out.append(f'<li style="white-space:pre-wrap">{inline_html(line[m.end():])}')
        stack[-1][1] = True
    close_to(0)
    return "".join(out)


def to_line_html(markup: str) -> str:
    """The markup as lines of HTML joined by ``<br>``, for text shown inside a paragraph (the raw text log): list items
    as indented bullets and numbers."""
    out = []
    for line in markup.split("\n"):
        m = LIST_LINE.match(line)
        if m:
            marker = f"{m.group(3)}." if m.group(3) else "•"
            out.append("&nbsp;" * (4 * (len(m.group(1)) // 2) + 1) + f"{marker}&nbsp;{inline_html(line[m.end():])}")
        else:
            out.append(inline_html(line))
    return "<br>".join(out)


def clip(markup: str, limit: int) -> str:
    """The first lines of the markup whose plain text comes to about ``limit`` characters, at least one line."""
    kept, size = [], 0
    for line in markup.split("\n"):
        if kept and size + len(to_plain(line)) > limit:
            break
        kept.append(line)
        size += len(to_plain(line)) + 1
    return "\n".join(kept)


def without_title_line(markup: str, title: str) -> str:
    """The markup without its first line when that line is just the capture's title (its first sentence), so the raw
    text log doesn't show it twice."""
    first, _, rest = markup.partition("\n")
    plain = re.sub(r"\.\Z", "", re.sub(r"\s+", " ", to_plain(first)).strip())
    return rest.lstrip("\n") if plain and plain == title.strip() else markup
