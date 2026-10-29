"""The Task view's search (release 5.34; the task overview design's section 6, decisions 161 and 162): reading what's
typed in its box, and finding the task's records that match, best first, fast enough for every keystroke.

- **Words:** every word must match somewhere, in any order and any case, ignoring accents. Quotes keep a phrase together,
  and a leading "-" leaves out what has a word. Words of one or two letters match only at the start of a word.
- **Where a word matched** sets its score: the start of the name, a word start in it, inside it, the description,
  where it came from (or its subtask), then, as the fallback, a slip in a name word (one letter missing, added, wrong
  or two swapped, keeping its first letter), then the text. Pins, use and age only break ties (``bonus``).
- **Typed filters** (``type:pdf``, ``in:vendor``, ``from:tom``, ``after:``, ``before:``, ``since:``, ``is:``) become
  filters, and leave the box, once a space follows them.
- **Two tiers:** the first searches what every record holds in memory, on every keystroke; the second searches files'
  extracted text, off the keystroke path (``find`` with ``texts``), and returns only the files only their text matched.

Nothing here knows about Qt; the window shows what this finds.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from docrepo.overview import Record, fold

#: What a typed ``type:`` value means, and the file extensions typed alone (".pdf").
TYPE_WORDS = {
    "word": "doc", "doc": "doc", "docx": "doc", "text": "doc", "txt": "doc", "excel": "sheet", "xlsx": "sheet", "xls": "sheet", "sheet": "sheet",
    "spreadsheet": "sheet", "csv": "sheet", "powerpoint": "slides", "pptx": "slides", "ppt": "slides", "slides": "slides", "pdf": "pdf",
    "picture": "picture", "pictures": "picture", "photo": "picture", "photos": "picture", "image": "picture", "jpg": "picture", "png": "picture",
    "email": "mail", "emails": "mail", "msg": "mail", "drawing": "drawing", "vsdx": "drawing", "dwg": "drawing", "link": "link", "links": "link",
}
OPERATORS = ("type", "in", "from", "after", "since", "before", "is")
HINTS = {
    "type": "Type a type and a space: pdf, word, excel, powerpoint, picture, email, drawing or link.",
    "in": "Type part of a subtask's name and a space.",
    "from": "Type part of a sender's name and a space, or attachment, original, copy or link.",
    "after": "Type a date and a space: 1 sep, sep, 2026-09-01, yesterday, last week or 30d.",
    "since": "Type a date and a space: 1 sep, sep, 2026-09-01, yesterday, last week or 30d.",
    "before": "Type a date and a space: 1 oct, oct, 2026-10-01 or last month.",
    "is": "Type pinned, missing, email, link, attachment or picture, and a space.",
}
#: ``from:`` values that name a file's source rather than a sender.
SOURCE_WORDS = {"attachment": "Email attachment", "attachments": "Email attachment", "original": "Tracked original", "originals": "Tracked original",
                "copy": "Saved copy", "copies": "Saved copy", "link": "Link", "links": "Link", "pasted": "Pasted on the notes page"}

# How much a word scores, by where it matched.
TITLE_START, WORD_START, IN_TITLE, IN_DESC, IN_SOURCE, SLIP, IN_TEXT, IN_FILE_TEXT = 12, 10, 7, 4, 3, 2.5, 2, 1

#: A typed filter, followed by a space. A date's value may be two words ("since:1 sep", "before:last month").
_OPERATOR = re.compile(r"(^|\s)(type|in|from|is):(?:\"([^\"]+)\"|(\S+))(?=\s)", re.I)
_DATE_OPERATOR = re.compile(r"(^|\s)(after|since|before):(?:\"([^\"]+)\"|(\d{1,2}\s+[a-z]{3,9}|[a-z]{3,9}\s+\d{1,2}(?!\d)|(?:last|this)\s+(?:week|month)|\S+))(?=\s)",
                            re.I)
_EXTENSION = re.compile(r"(^|\s)\.(docx|xlsx|pptx|pdf|jpg|png|csv|msg|vsdx|txt)(?=\s)", re.I)
_UNFINISHED = re.compile(r"(?:^|\s)(type|in|from|after|since|before|is):\S*$", re.I)
_TERM = re.compile(r"(-?)\"([^\"]+)\"?|(-?)(\S+)")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


@dataclass
class Filters:
    """The filters set from the buttons or typed: each shown as a chip."""

    types: set[str] = field(default_factory=set)       # file types (overview.TYPES' keys, "link")
    sources: set[str] = field(default_factory=set)     # overview.SOURCES
    senders: set[str] = field(default_factory=set)     # emails' senders
    since: date | None = None
    before: date | None = None
    pinned: bool = False
    missing: bool = False

    def count(self) -> int:
        return len(self.types) + len(self.sources) + len(self.senders) + (self.since is not None) + (self.before is not None) + self.pinned + self.missing

    def clear(self) -> None:
        self.types.clear(), self.sources.clear(), self.senders.clear()
        self.since = self.before = None
        self.pinned = self.missing = False

    def keep(self, r: Record, pinned: Callable[[str], bool] = lambda _: False, missing: Callable[[str], bool] = lambda _: False) -> bool:
        """Whether a record passes the filters. A file filter (type, source, pinned, missing) keeps only files; a sender
        keeps their emails and the files that came with them; the dates keep what came in that window."""
        if self.types and not (r.kind == "file" and r.type in self.types or r.kind == "email" and "mail" in self.types):
            return False
        if self.sources and not (r.kind == "file" and r.source in self.sources):
            return False
        if self.senders and r.sender not in self.senders:
            return False
        if self.since and r.day < self.since.isoformat():
            return False
        if self.before and r.day >= self.before.isoformat():
            return False
        if self.pinned and not (r.kind == "file" and pinned(r.id)):
            return False
        return not (self.missing and not (r.kind == "file" and missing(r.id)))


# ---- reading the box ----
@dataclass
class Typed:
    """What reading the box found: the text left to search, a subtask scope or kind it asked for, and a hint for an
    operator still being typed."""

    rest: str
    scope: str | None = None
    kind: str | None = None
    hint: str = ""
    changed: bool = False


def read_day(text: str, today: date) -> date | None:
    """A date typed for a filter, looking back from today: 2026-09-01, 1 sep, sep 1, sep, yesterday, last week, last month,
    this week, this month, 30d, 2w. A day that would be in the future means last year's."""
    s = text.strip().lower().replace(".", "")
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    if s == "today":
        return today
    if s == "yesterday":
        return today - timedelta(days=1)
    monday = today - timedelta(days=today.weekday())
    if s in ("this week", "thisweek"):
        return monday
    if s in ("last week", "lastweek"):
        return monday - timedelta(days=7)
    if s in ("this month", "thismonth"):
        return today.replace(day=1)
    if s in ("last month", "lastmonth"):
        return (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    m = re.fullmatch(r"(\d+)\s*(d|days?|w|weeks?)", s)
    if m:
        n = int(m.group(1)) * (7 if m.group(2).startswith("w") else 1)
        return today - timedelta(days=n)
    m = re.fullmatch(r"(\d{1,2})\s*([a-z]+)", s) or re.fullmatch(r"([a-z]+)\s*(\d{1,2})?", s)
    if not m:
        return None
    day_text, month_text = (m.group(1), m.group(2)) if m.group(1).isdigit() else (m.group(2) or "1", m.group(1))
    if month_text[:3] not in _MONTHS:
        return None
    month = _MONTHS.index(month_text[:3]) + 1
    try:
        found = date(today.year, month, int(day_text))
    except ValueError:
        return None
    return found.replace(year=today.year - 1) if found > today else found


def take_filters(text: str, filters: Filters, subtasks: list[tuple[str, str]], senders: Iterable[str], today: date) -> Typed:
    """Turn each complete typed filter (one a space follows) into a filter, and take it out of the box's text.
    ``subtasks`` are the (ID, title) pairs ``in:`` may name; ``senders`` the emails' senders ``from:`` may name."""
    out = Typed(text)
    senders = list(senders)

    def apply(m: re.Match) -> str:
        op, value = m.group(2).lower(), (m.group(3) or m.group(4)).strip()
        v = fold(value)
        done = False
        if op == "type" and v in TYPE_WORDS:
            filters.types.add(TYPE_WORDS[v])
            done = True
        elif op == "in":
            match = next((tid for tid, title in subtasks if v in fold(title)), None)
            if match:
                out.scope, done = match, True
        elif op == "from":
            if v in SOURCE_WORDS:
                filters.sources.add(SOURCE_WORDS[v])
                done = True
            else:
                who = next((s for s in senders if v in fold(s)), None)
                if who:
                    filters.senders.add(who)
                    done = True
        elif op in ("after", "since", "before"):
            day = read_day(value, today)
            if day:
                if op == "before":
                    filters.before = day
                else:
                    filters.since = day + timedelta(days=1) if op == "after" else day
                done = True
        elif op == "is":
            if v == "pinned":
                filters.pinned = done = True
            elif v == "missing":
                filters.missing = done = True
            elif v in ("email", "emails"):
                out.kind, done = "email", True
            elif v in ("attachment", "attachments"):
                filters.sources.add("Email attachment")
                done = True
            elif v in ("link", "links", "picture", "pictures"):
                filters.types.add(TYPE_WORDS[v])
                done = True
        if done:
            out.changed = True
            return m.group(1)
        return m.group(0)

    def extension(m: re.Match) -> str:
        filters.types.add(TYPE_WORDS[m.group(2).lower()])
        out.changed = True
        return m.group(1)

    rest = _EXTENSION.sub(extension, _OPERATOR.sub(apply, _DATE_OPERATOR.sub(apply, text)))
    out.rest = re.sub(r"\s{2,}", " ", rest).lstrip() if out.changed else rest
    unfinished = _UNFINISHED.search(out.rest)
    out.hint = HINTS[unfinished.group(1).lower()] if unfinished else ""
    return out


def terms(text: str) -> tuple[list[str], list[str]]:
    """The words to find and the words to leave out, folded. A quoted phrase is one word, spaces and all; an operator
    still being typed (``type:``) isn't searched for."""
    pos: list[str] = []
    neg: list[str] = []
    for m in _TERM.finditer(fold(text)):
        minus = m.group(1) or m.group(3)
        word = (m.group(2) or m.group(4) or "").strip()
        if not word or word == "-" or (not m.group(2) and re.fullmatch(r"(type|in|from|after|since|before|is):\S*", word)):
            continue
        (neg if minus else pos).append(word)
    return pos, neg


# ---- matching ----
def one_slip(a: str, b: str) -> bool:
    """Whether two words differ by one slip at most: a letter missing, added or wrong, or two letters swapped."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1:]


_STARTS: dict[str, re.Pattern] = {}


def _starts(word: str) -> re.Pattern:
    p = _STARTS.get(word)
    if p is None:
        p = _STARTS[word] = re.compile(r"(?:^|[^0-9a-z])" + re.escape(word))
    return p


def has_word(text: str, word: str) -> bool:
    """Whether folded text holds a word: anywhere for three letters or more, at a word's start for fewer."""
    return bool(_starts(word).search(text)) if len(word) < 3 else word in text


def match_word(r: Record, w: str, file_text: str | None = None) -> tuple[float, str | None, bool] | None:
    """Where a word matched a record, as (score, the name word a slip matched, whether it took the text), or None."""
    if r.n_title.startswith(w):
        return TITLE_START, None, False
    if " " not in w and any(x.startswith(w) for x in r.words):
        return WORD_START, None, False
    if len(w) >= 3 and w in r.n_title:
        return IN_TITLE, None, False
    if has_word(r.n_desc, w):
        return IN_DESC, None, False
    if has_word(r.n_src, w):
        return IN_SOURCE, None, False
    if len(w) >= 4 and " " not in w:
        slip = next((x for x in r.words if x[0] == w[0] and (one_slip(w, x[:len(w)]) or one_slip(w, x))), None)
        if slip:
            return SLIP, slip, False
    if r.kind != "file" and has_word(r.n_text, w):
        return IN_TEXT, None, True
    if file_text is not None and has_word(file_text, w):
        return IN_FILE_TEXT, None, True
    return None


@dataclass
class Hit:
    record: Record
    score: float
    slips: tuple[str, ...] = ()     # the name words matched with a slip, to highlight
    in_text: bool = False           # a word matched only in its text: show the text around it
    second: bool = False            # found by the second tier, in a file's extracted text


def _left_out(r: Record, neg: list[str]) -> bool:
    return any(has_word(t, w) for w in neg for t in (r.n_title, r.n_desc, r.n_src, r.n_text))


def find(records: Iterable[Record], words: list[str], neg: list[str] = (), keep: Callable[[Record], bool] | None = None,
         bonus: Callable[[Record], float] | None = None, texts: dict[str, str] | None = None) -> list[Hit]:
    """The records that match every word and none of ``neg``, best first (ties to the newer). With ``texts`` (each
    file's folded extracted text) it's the second tier: only the files that need their text to match."""
    out: list[Hit] = []
    for r in records:
        if keep is not None and not keep(r):
            continue
        if neg and _left_out(r, neg):
            continue
        file_text = texts.get(r.id, "") if texts is not None and r.kind == "file" else None
        if texts is not None and file_text is None:
            continue
        score, slips, in_text, needed_file_text = 0.0, [], False, False
        for w in words:
            m = match_word(r, w, file_text)
            if m is None:
                break
            score += m[0]
            if m[1]:
                slips.append(m[1])
            if m[2]:
                in_text = True
                needed_file_text = needed_file_text or file_text is not None and r.kind == "file"
        else:
            if texts is not None and not needed_file_text:
                continue  # the first tier has it already
            out.append(Hit(r, score + (bonus(r) if bonus else 0.0), tuple(slips), in_text, texts is not None))
    # Ties go to the newer, then to the later name (rev C before rev B when one email brought both), as the score's sort
    # keeps this order.
    out.sort(key=lambda h: (h.record.at, natural(h.record.title)), reverse=True)
    out.sort(key=lambda h: -h.score)
    return out


def natural(text: str) -> list:
    """A name's sort key with its numbers as numbers, so "v10" comes after "v9"."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.split(r"(\d+)", text.lower()) if part]


# ---- showing what matched ----
def highlights(text: str, words: list[str], slips: Iterable[str] = ()) -> list[tuple[int, int]]:
    """Where the words (and the slips' name words) are in a text, as (start, end) ranges, merged and in order."""
    folded = fold(text)
    spans: list[tuple[int, int]] = []
    for w in [*words, *slips]:
        if not w:
            continue
        if len(w) < 3:
            spans += [(m.end() - len(w), m.end()) for m in _starts(w).finditer(folded)]
        else:
            start = folded.find(w)
            while start >= 0:
                spans.append((start, start + len(w)))
                start = folded.find(w, start + len(w))
    merged: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def snippet(text: str, words: list[str], width: int = 100) -> str:
    """The text around the first word found, on one line."""
    spans = highlights(text, words)
    if not spans:
        return ""
    start = max(0, spans[0][0] - 20)  # the word near the start, so a narrow row still shows it
    part = " ".join(text[start:start + width].split())
    return ("…" if start else "") + part + ("…" if start + width < len(text) else "")


def matched_lines(text: str, words: list[str], context: int = 1, limit: int = 14) -> list[tuple[int, str, bool]]:
    """The lines a word is on, with ``context`` lines either side, as (line number, line, matched); a gap between runs
    is (-1, "…", False). At most ``limit`` lines."""
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if words and any(has_word(fold(line), w) for w in words)]
    shown = sorted({j for i in hits for j in range(i - context, i + context + 1) if 0 <= j < len(lines)})
    out: list[tuple[int, str, bool]] = []
    last = None
    for j in shown:
        if len(out) >= limit:
            break
        if last is not None and j > last + 1:
            out.append((-1, "…", False))
        out.append((j, lines[j], j in hits))
        last = j
    return out


def suggestion(words: list[str], records: list[Record], finds: Callable[[list[str]], bool]) -> str | None:
    """"Did you mean …": each word of four letters or more swapped for the nearest name word one slip away, offered only
    when the new words find something (``finds``)."""
    vocabulary = sorted({x for r in records for x in r.words if len(x) >= 4})
    changed, out = False, []
    for w in words:
        near = None if len(w) < 4 or " " in w or w in vocabulary else next(
            (x for x in vocabulary if x[0] == w[0] and (one_slip(w, x) or one_slip(w, x[:len(w)]))), None)
        out.append(near or w)
        changed = changed or near is not None
    return " ".join(out) if changed and finds(out) else None
