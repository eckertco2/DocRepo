"""Formatted content text (mods log round 2, M0045, release 5.7).

A formatted capture's content text is kept in its capture.md as a small, readable piece of Markdown, one block per line:

- ``**bold**``, ``*italic*``, ``~~strikethrough~~``, ``<u>underline</u>`` and ``<mark class="yellow">highlight</mark>``
  (yellow, green or pink);
- a list item: two spaces per level, then ``- `` or a number and ``. ``;
- a checklist line (release 5.26, decision 86): a list item whose text starts with a box, ``- [ ] `` or ``- [x] ``;
- a heading (release 5.28, mods log round 4): ``# ``, ``## `` or ``### `` and its words, at levels 1 to 3, as on a
  task's notes page. Its words are kept as typed, without marks;
- any other line is a line of text, and an empty line stays empty.

A backslash keeps a character as itself: ``\\*``, ``\\~``, ``\\<``, and ``\\-`` or ``1\\.`` at a line's start, so a line of
text that starts like a list item stays text; a line of text that would read as a heading starts with a backslash
(``\\# Pump 3``). A backslash before anything else is just a backslash, so paths read as they are. Whatever reads content
text for its words (Parse and populate, titles, search) reads ``to_plain``, which gives a heading's words alone; pages
and the editor show ``to_html``. A capture with no formatting is kept as plain text, as before, and capture.md says which
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
#: A heading (release 5.28): its level's hashes, a space and its words, as the notes page keeps one.
HEADING = re.compile(r"^(#{1,3}) (.*)$")
#: How much larger than the text each heading level is shown, on the pages (Qt's steps of font size).
HEADING_SIZES = {1: "large", 2: "medium", 3: "medium"}
#: A line that a backslash keeps from reading as a heading, or that needs one: any backslashes, then a heading's start.
_HEADING_LIKE = re.compile(r"^\\*#{1,3} ")
_ESCAPED_HEADING = re.compile(r"^\\+#{1,3} ")
#: A checklist line's box, at the start of a list item's text: "[ ] " or "[x] " (release 5.26).
CHECK = re.compile(r"\[([ xX])\] ")
#: Ticked lines' words are grey (decision 91).
TICKED_GREY = "#5a6571"
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


def escape_heading(line: str) -> str:
    """A line of text, already markup, that would read as a heading (release 5.28): a backslash before it, so it stays
    text. One that already starts with a backslash before a heading's start gets another, so it reads back as it was."""
    return "\\" + line if _HEADING_LIKE.match(line) else line


def heading_line(words: str, level: int) -> str:
    """A heading's line, from its words: they're kept as typed, on one line."""
    return f"{'#' * max(1, min(level, 3))} {' '.join(words.split())}"


def heading_of(line: str) -> tuple[int, str] | None:
    """A heading line's level and words, or None for any other line."""
    m = HEADING.match(line)
    return (len(m.group(1)), m.group(2)) if m else None


def text_of(line: str) -> str:
    """A line of text's markup, without the backslash that keeps it from reading as a heading."""
    return line[1:] if _ESCAPED_HEADING.match(line) else line


def escape(text: str) -> str:
    """Plain text as markup that reads as the same text."""
    return "\n".join(escape_heading(escape_line_start(escape_inline(line))) for line in text.split("\n"))


def from_list_lines(text: str) -> str:
    """Plain text whose "- item" and "1. item" lines (indented two spaces a level) are list items, as markup with real
    lists: what pasting a Word or Outlook list gives (``paste.html_to_text``)."""
    out = []
    for line in text.split("\n"):
        m = LIST_LINE.match(line)
        out.append(line[:m.end()] + escape_inline(line[m.end():]) if m else escape_heading(escape_line_start(escape_inline(line))))
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


def replace_spans(text: str, spans: list[tuple[int, int, str]]) -> str:
    """A line's text (after any list marker) with spans of its words replaced, each (start, end, new words) in its plain
    text; the new words take the marks of the first character they replace (release 5.8: names kept with their IDs)."""
    chars = [(ch, marks, colour) for part, marks, colour in _segments(text) for ch in part]
    pieces: list[tuple[str, frozenset[str], str | None]] = []
    i = 0
    for start, end, new in sorted(spans):
        pieces.extend(chars[i:start])
        if start < len(chars):
            pieces.append((new, chars[start][1], chars[start][2]))
        i = end
    pieces.extend(chars[i:])
    merged: list[tuple[str, frozenset[str], str | None]] = []
    for t, marks, colour in pieces:
        if merged and merged[-1][1] == marks and merged[-1][2] == colour:
            merged[-1] = (merged[-1][0] + t, marks, colour)
        else:
            merged.append((t, marks, colour))
    return marks_text([(escape_inline(t), marks, colour) for t, marks, colour in merged])


def to_plain(markup: str) -> str:
    """The plain text: marks dropped, escapes undone. A list item keeps its marker and indent ("  - item"); a heading is
    its words alone."""
    lines = []
    for line in markup.split("\n"):
        h = heading_of(line)
        if h:
            lines.append(h[1])
            continue
        line = text_of(line)
        m = LIST_LINE.match(line)
        head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
        lines.append(head + "".join(t for t, _, _ in _segments(rest)))
    return "\n".join(lines)


def check_of(line: str) -> bool | None:
    """A line's box: True ticked, False not, None for a line that isn't a checklist line."""
    m = LIST_LINE.match(line)
    if not m or m.group(3):
        return None
    c = CHECK.match(line, m.end())
    return None if not c else c.group(1) in "xX"


def is_formatted(markup: str) -> bool:
    """Whether the markup has any list, heading or mark, so it needs keeping as markup rather than as plain text."""
    return any(LIST_LINE.match(line) or HEADING.match(line) or any(marks for _, marks, _ in _segments(text_of(line)))
               for line in markup.split("\n"))


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
        h = heading_of(line)
        if h:  # a heading (release 5.28): Qt's heading, a little larger than the text rather than its default sizes
            close_to(0)
            level, words = h
            out.append(f'<h{level} style="margin-top:{8 if level == 1 else 6}px; margin-bottom:2px; font-size:{HEADING_SIZES[level]}; '
                       f'font-weight:600; white-space:pre-wrap">{html.escape(words, quote=False) or "<br>"}</h{level}>')
            continue
        line = text_of(line)
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
        rest, check = line[m.end():], None if m.group(3) else CHECK.match(line, m.end())
        if check:  # a checklist line: Qt's list item with a box (release 5.26)
            done = check.group(1) in "xX"
            rest = line[check.end():]
            out.append(f'<li class="{"checked" if done else "unchecked"}" style="white-space:pre-wrap'
                       f'{"; color:" + TICKED_GREY if done else ""}">{inline_html(rest)}')
        else:
            out.append(f'<li style="white-space:pre-wrap">{inline_html(rest)}')
        stack[-1][1] = True
    close_to(0)
    return "".join(out)


def to_line_html(markup: str) -> str:
    """The markup as lines of HTML joined by ``<br>``, for text shown inside a paragraph (the raw text log): list items
    as indented bullets and numbers, and headings in bold."""
    out = []
    for line in markup.split("\n"):
        h = heading_of(line)
        if h:
            out.append(f"<b>{html.escape(h[1], quote=False)}</b>")
            continue
        line = text_of(line)
        m = LIST_LINE.match(line)
        if m:
            marker, rest = f"{m.group(3)}." if m.group(3) else "•", line[m.end():]
            check = None if m.group(3) else CHECK.match(line, m.end())
            if check:
                marker, rest = ("☑" if check.group(1) in "xX" else "☐"), line[check.end():]
            out.append("&nbsp;" * (4 * (len(m.group(1)) // 2) + 1) + f"{marker}&nbsp;{inline_html(rest)}")
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
