"""Reading a capture's content text: its sentences and the title it's listed under.

Ported from the mockup's ``model.js`` (``plainText``, ``sentencesOf``, ``firstSentence``
and ``capTitle``). Parse and populate (phase 3) builds on the same sentence rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: An email's header lines at the start of the content text.
MAIL_HEAD = re.compile(r"^(?:(?:From|To|Cc|Sent|Date|Subject):.*\n)+\s*")
_PATH_LINE = re.compile(r"^(\\\\|[A-Za-z]:\\)\S")
# A full stop after these never ends a sentence: "approx.", "e.g.", "Dr.".
_ABBREV = re.compile(r"(?:^|[\s(])(?:approx|appr|e\.g|i\.e|vs|dr|mr|mrs|ms|prof|jr|sr|incl|ca)\Z", re.IGNORECASE)
# A full stop after these doesn't end one when a digit or a lowercase word follows: "Oct. 19", "No. 3", "Tyler N. about".
_ABBREV_BEFORE_LOWER = re.compile(
    r"(?:^|[\s(])(?:[A-Z]|etc|no|nos|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|mon|tue|tues|wed|thu|thur|thurs"
    r"|fri|sat|sun|in|ft|fig|ref|rev|qty|est)\Z",
    re.IGNORECASE,
)
_ENDS = re.compile(r"[.!?]+(?=\s)|\n")


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


def is_path_line(line: str) -> bool:
    """True for a line that is a file path, such as ``C:\\Docs\\a.pdf`` or ``\\\\server\\share\\a.pdf``."""
    return bool(_PATH_LINE.match(line.strip()))


def plain_text(content: str) -> str:
    """The content text without an email's header lines or file path lines."""
    lines = MAIL_HEAD.sub("", content, count=1).split("\n")
    return "\n".join(line for line in lines if not is_path_line(line)).strip()


def sentences(text: str) -> list[Sentence]:
    """Sentences end at . ! ? before a space, or at a line break, except after an abbreviation."""
    out: list[Sentence] = []

    def push(a: int, b: int) -> None:
        raw = text[a:b]
        trimmed = raw.strip()
        if trimmed:
            start = a + raw.index(trimmed)
            out.append(Sentence(trimmed, start, start + len(trimmed)))

    begin = 0
    for m in _ENDS.finditer(text):
        if m.group() == ".":
            word = text[begin:m.start()]
            following = re.match(r"\s*(\S)", text[m.start() + 1:])
            if _ABBREV.search(word) or (
                _ABBREV_BEFORE_LOWER.search(word) and following and re.match(r"[\da-z]", following.group(1))
            ):
                continue
        push(begin, m.end())
        begin = m.end()
    push(begin, len(text))
    return out


def first_sentence(text: str, limit: int = 100) -> str:
    """The first sentence, without its closing full stop, cut at a word and ended with … beyond ``limit`` characters."""
    found = sentences(text.strip())
    first = re.sub(r"\s+", " ", found[0].text if found else "").strip()
    first = re.sub(r"\.\Z", "", first)
    if len(first) > limit:
        first = re.sub(r"\s+\S*\Z", "", first[:limit]) + "…"
    return first


def capture_title(source: str, content: str, first_document: str | None, capture_id: str) -> str:
    """How a capture is listed: an email's subject, else its first sentence, else its first file's name."""
    if source == "outlook_email":
        subject = re.search(r"^Subject:\s*(.+)$", content, re.MULTILINE)
        if subject:
            return subject.group(1).strip()
    return first_sentence(plain_text(content)) or first_document or capture_id
