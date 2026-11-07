"""Tagged labels (release 5.79; the tagged labels plan, items 102 to 105, decisions 365 to 381): plant tags, such as
V-110 or FIC-2210, found in everything DocRepo reads as text.

- **The glossary** (``tagged_labels``, ``tagged_aliases``): each tagged label with its description and aliases, imported
  from Excel or CSV (``docrepo.tagged_import``), edited in the browse tool, or added by hand. A label is known by its
  **key**, its letters and digits in capitals, so V-110 and V110 are one label.
- **Matching with no setup** (decision 368): a label, or a tag-shaped alias (one with a digit and no space), is found
  however its parts are joined: a hyphen, an en dash, an underscore, nothing, or a space between capitals. So V-110 is
  found as V110, v-110 and V 110, and "page 101" isn't P-101. A label with fewer than four letters and digits (E-12) must
  be in capitals with no space. Any other alias ("feed drum", "CT fan 1") is found as whole words, in any case
  (decision 369). P-204A is its own label, and "P-204A/B" mentions P-204A and P-204B (decision 370).
- **What's read** (decision 366): the text the search index keeps for each capture, document and notes page
  (``search_text``), without its ID line, and without a capture's title or a page's task title when the rest has it;
  and a task's own fields (title, description, current status, deadline description, key dates' descriptions), read
  from the model as they are.
- **Kept current** (decision 377): each save indexes the item here too (``index``), keeping its tag-like words
  (``tagged_words``) and what they mention (``tagged_mentions``). A change to the glossary matches every item's kept words
  again (``rematch``) without reading any text, apart from word aliases, which are looked for in ``search_text``.
  Both tables are caches, rebuilt with the search index (``rebuild``).
- **The owner's own changes** (decision 376, ``tagged_choices``): a label removed from a capture or document, or added by
  hand, applied when the mentions are read, so reading the text again never undoes them.

Nothing here touches Qt. Pure functions (``Finder``, ``words_of``) are tested on their own.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from docrepo.db import get_state, set_state, transaction

if TYPE_CHECKING:
    from docrepo.model import Model, Task

log = logging.getLogger(__name__)

#: The marks a tag's parts may be joined by: a hyphen, an en dash, an underscore, and a space between capitals.
MARKS = "-–_ "
#: A label with fewer letters and digits than this must be in capitals with no space (E-12, but not e12 or E 12).
SHORT = 4
#: The most parts (runs of letters or digits) a label is matched across: "22-PT-101A" has four.
MAX_PARTS = 4
#: The kinds of item that hold text, as the search index names them.
KINDS = ("capture", "document", "page")
VERSION_KEY = "tagged_glossary"  # app_state: a new token each time the glossary changes, so a kept Finder knows it's out of date
WORDS_KEY = "tagged_words_built"  # app_state: every item's words have been kept (after the first rebuild)

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_PAIR = re.compile(r"/([A-Z])(?![A-Za-z0-9])")
_LETTER, _DIGIT = re.compile(r"[A-Za-z]"), re.compile(r"[0-9]")


def key_of(text: str) -> str:
    """A label's key: its letters and digits, in capitals."""
    return re.sub(r"[^0-9A-Za-z]", "", text).upper()


def tag_like(text: str) -> bool:
    """A name matched by its letters and digits: one with a digit and no space (V-110, D-10). Others are matched as words."""
    return bool(_DIGIT.search(text)) and not re.search(r"\s", text.strip())


def spellings(label: str) -> list[str]:
    """Ways a label is found, to show on its page: joined by hyphens, by nothing, and (in capitals) by spaces."""
    parts = _TOKEN.findall(label)
    if len(parts) < 2:
        return [label]
    up = [p.upper() for p in parts]
    return list(dict.fromkeys(["-".join(up), "".join(up), " ".join(up)] if len("".join(up)) >= SHORT else ["-".join(up), "".join(up)]))


def split_aliases(text: str) -> list[str]:
    """Aliases as typed or imported: separated by ``;``, ``,`` or a new line."""
    return [a.strip() for a in re.split(r"[;,\n]", text or "") if a.strip()]


def only_digits(text: str) -> bool:
    """An alias that's only digits (and marks) would match every such number, so it's refused."""
    return bool(re.fullmatch(r"[0-9\s\-–_./]+", text.strip()))


# ---- the glossary, as read ----
@dataclass(frozen=True)
class Label:
    id: int
    label: str
    key: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    status: str = "glossary"
    came: str = "import"
    pattern: str | None = None
    source: str | None = None
    added: str = ""


@dataclass(frozen=True)
class Hit:
    """One place a label is mentioned: where in the text, as written, and how it was found (label, alias, word or pair)."""

    start: int
    end: int
    written: str
    label: int
    how: str


@dataclass
class Mention:
    """What one item says about one label: how it was found, how often, and each spelling with its count."""

    kind: str
    id: str
    label: int
    how: str
    n: int
    written: dict[str, int] = field(default_factory=dict)


# ---- matching ----
def _spaced_ok(a: str, b: str) -> bool:
    """A space joins two parts only between capitals (and digits), so "page 101" isn't P-101."""
    return a == a.upper() and b == b.upper()


class Finder:
    """Finds a glossary's labels in text. Built once per version of the glossary."""

    def __init__(self, labels: Iterable[Label]) -> None:
        self.keys: dict[str, tuple[int, str]] = {}  # key -> (label id, how)
        phrases: dict[str, tuple[int, str]] = {}  # a word alias in lower case, its words one space apart -> (label id, how)
        for lb in labels:
            for name, how in ((lb.label, "label"), *((a, "alias") for a in lb.aliases)):
                if tag_like(name):
                    self.keys.setdefault(key_of(name), (lb.id, how))
                elif name.strip():
                    phrases.setdefault(" ".join(name.lower().split()), (lb.id, "label" if how == "label" else "word"))
        self.phrases = phrases
        self.words_re: re.Pattern[str] | None = None
        if phrases:
            alts = sorted(phrases, key=len, reverse=True)  # the longest first, so "ct fan 1" wins over "ct fan"
            body = "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in alts)
            self.words_re = re.compile(rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])", re.IGNORECASE)

    def __bool__(self) -> bool:
        return bool(self.keys or self.phrases)

    def find_tags(self, text: str) -> list[Hit]:
        """Labels and tag-shaped aliases: runs of letters and digits joined by one mark each, the longest match first."""
        hits: list[Hit] = []
        if not self.keys:
            return hits
        toks = list(_TOKEN.finditer(text))
        i = 0
        while i < len(toks):
            best: tuple[int, int, int, str] | None = None  # (last token, label, end, how)
            joined = ""
            for j in range(i, min(i + MAX_PARTS, len(toks))):
                if j > i:
                    gap = text[toks[j - 1].end():toks[j].start()]
                    if len(gap) != 1 or gap not in MARKS or (gap == " " and not _spaced_ok(toks[j - 1].group(), toks[j].group())):
                        break
                joined += toks[j].group()
                found = self.keys.get(joined.upper())
                if not found:
                    continue
                written = text[toks[i].start():toks[j].end()]
                if len(joined) < SHORT and (written != written.upper() or " " in written):
                    continue  # a short tag: capitals, no space
                best = (j, found[0], toks[j].end(), found[1])
            if best is None:
                i += 1
                continue
            j, label, end, how = best
            hits.append(Hit(toks[i].start(), end, text[toks[i].start():end], label, how))
            pair = _PAIR.match(text, end)  # P-204A/B: the same tag with that letter (decision 370)
            if pair:
                k = key_of(text[toks[i].start():end])
                if k[-1:].isalpha():
                    other = self.keys.get(k[:-1] + pair.group(1))
                    if other:
                        hits.append(Hit(pair.start(), pair.end(), pair.group(), other[0], "pair"))
            i = j + 1
        return hits

    def find_words(self, text: str) -> list[Hit]:
        """Word aliases, and labels with no digit, as whole words in any case."""
        if self.words_re is None:
            return []
        out = []
        for m in self.words_re.finditer(text):
            label, how = self.phrases[" ".join(m.group().lower().split())]
            out.append(Hit(m.start(), m.end(), m.group(), label, how))
        return out

    def find(self, text: str) -> list[Hit]:
        """Every mention in ``text``, in order."""
        tags = self.find_tags(text)
        words = [h for h in self.find_words(text) if not any(h.start < t.end and t.start < h.end for t in tags)]
        return sorted([*tags, *words], key=lambda h: h.start)


def words_of(text: str) -> Counter[str]:
    """The text's tag-like words as written: runs of letters and digits joined by one mark each (a space only between
    capitals), with a letter and a digit, and a pair's "/B" kept on (decision 377). Every tag a glossary could match lies
    inside one of these, so they're all a glossary change needs."""
    out: Counter[str] = Counter()
    toks = list(_TOKEN.finditer(text))
    i = 0
    while i < len(toks):
        j = i
        while j + 1 < len(toks):
            gap = text[toks[j].end():toks[j + 1].start()]
            if len(gap) != 1 or gap not in MARKS or (gap == " " and not _spaced_ok(toks[j].group(), toks[j + 1].group())):
                break
            j += 1
        end = toks[j].end()
        pair = _PAIR.match(text, end)
        if pair:
            end = pair.end()
        run = text[toks[i].start():end]
        if _LETTER.search(run) and _DIGIT.search(run):
            out[run] += 1
        i = j + 1
        if pair:  # the pair's letter is part of this run
            while i < len(toks) and toks[i].start() < end:
                i += 1
    return out


def text_of_body(kind: str, body: str) -> str:
    """What's read of a capture's or document's search index body: without its ID line, and for a capture without its
    title when the rest has it (it's usually the content's first line)."""
    rest = body.split("\n")[1:]
    if kind == "capture" and rest:
        title, others = rest[0], "\n".join(rest[1:])
        if title.rstrip("…").strip() and title.rstrip("…").strip() in others:
            return others
    return "\n".join(rest)


def page_text(page: str) -> str:
    """What's read of a notes page: what was typed on it, without the captures' blocks (from a caption to the next caption
    or heading), which are read as their captures, so a capture's words count once."""
    from docrepo import markup, notes_page

    out, in_block = [], False
    for x in notes_page.lines_of(page):
        if x.kind == "caption":
            in_block = True
            continue
        if x.kind == "heading":
            in_block = False
        if in_block:
            continue
        if x.kind == "row":
            if not notes_page.is_separator(x.text):
                out.append(" ".join(markup.to_plain(c) for c in notes_page.cells_of(x.text)))
        else:
            out.append(markup.to_plain(x.text) if x.kind == "text" else x.text)
    return "\n".join(out)


def item_texts(conn: sqlite3.Connection) -> Iterable[tuple[str, str, str]]:
    """Every capture's, document's and notes page's text, as read here: (kind, id, text)."""
    for r in conn.execute("SELECT kind, id, body FROM search_text WHERE kind != 'page'"):
        yield r["kind"], r["id"], text_of_body(r["kind"], r["body"])
    for r in conn.execute("SELECT task, body FROM task_pages"):
        yield "page", r["task"], page_text(r["body"])


def task_text(t: Task, model: Model) -> str:
    """A task's own fields, as read for its tagged labels."""
    dates = [kd.description for kd in model.key_dates_of(t.id) if kd.description]
    return "\n".join(x for x in (t.title, t.description, t.current_status, t.deadline_desc or "", *dates) if x)


def mentions_in(finder: Finder, kind: str, item_id: str, words: Mapping[str, int], text: str | None) -> dict[int, Mention]:
    """What one item mentions, from its kept words (and its text, for word aliases)."""
    out: dict[int, Mention] = {}

    def add(h: Hit, n: int) -> None:
        m = out.get(h.label)
        if m is None:
            m = out[h.label] = Mention(kind, item_id, h.label, h.how, 0)
        m.n += n
        m.written[h.written] = m.written.get(h.written, 0) + n

    for run, n in words.items():
        for h in finder.find_tags(run):
            add(h, n)
    if text and finder.words_re is not None:
        for h in finder.find_words(text):
            add(h, 1)
    return out


# ---- the glossary in docs.db ----
def read_labels(conn: sqlite3.Connection) -> list[Label]:
    aliases: dict[int, list[str]] = {}
    for r in conn.execute("SELECT label, alias FROM tagged_aliases ORDER BY label, pos"):
        aliases.setdefault(r["label"], []).append(r["alias"])
    return [Label(r["id"], r["label"], r["key"], r["description"], tuple(aliases.get(r["id"], ())), r["status"], r["came"], r["pattern"],
                  r["source"], r["added"])
            for r in conn.execute("SELECT * FROM tagged_labels ORDER BY id")]


class _Kept:
    """One version of the glossary, read once: its labels, and its Finder when it's first needed. A save builds the Model
    several times, and 20,000 labels took 0.1 s to read each time."""

    def __init__(self, labels: list[Label]) -> None:
        self.labels = labels
        self._finder: Finder | None = None

    def finder(self) -> Finder:
        if self._finder is None:
            self._finder = Finder(self.labels)
        return self._finder


_kept: dict[str, _Kept] = {}


def _glossary(conn: sqlite3.Connection) -> _Kept:
    """The glossary as it is: kept by its version's token, which every change to it makes new (``glossary_changed``)."""
    token = get_state(conn, VERSION_KEY)
    if token is None:
        return _Kept(read_labels(conn))
    kept = _kept.get(token)
    if kept is None:
        if len(_kept) > 4:
            _kept.clear()
        kept = _kept[token] = _Kept(read_labels(conn))
    return kept


def finder(conn: sqlite3.Connection) -> Finder:
    """The Finder for the glossary as it is, kept until the glossary changes."""
    return _glossary(conn).finder()


def glossary_changed(conn: sqlite3.Connection) -> None:
    set_state(conn, VERSION_KEY, uuid.uuid4().hex)


# ---- keeping it current ----
def _store(conn: sqlite3.Connection, kind: str, item_id: str, words: Counter[str], found: Mapping[int, Mention]) -> None:
    conn.execute("DELETE FROM tagged_words WHERE kind = ? AND id = ?", (kind, item_id))
    conn.executemany("INSERT INTO tagged_words (kind, id, word, n) VALUES (?, ?, ?, ?)", [(kind, item_id, w, n) for w, n in words.items()])
    conn.execute("DELETE FROM tagged_mentions WHERE kind = ? AND id = ?", (kind, item_id))
    _insert_mentions(conn, found.values())


def _insert_mentions(conn: sqlite3.Connection, ms: Iterable[Mention]) -> None:
    conn.executemany("INSERT INTO tagged_mentions (kind, id, label, how, n, written) VALUES (?, ?, ?, ?, ?, ?)",
                     [(m.kind, m.id, m.label, m.how, m.n, json.dumps(m.written, ensure_ascii=False)) for m in ms])


def index(conn: sqlite3.Connection, kind: str, item_id: str, text: str) -> None:
    """Keep one item's words and mentions, from its text (``text_of_body``, ``page_text``). Called inside the search
    index's transaction."""
    words = words_of(text)
    f = finder(conn)
    _store(conn, kind, item_id, words, mentions_in(f, kind, item_id, words, text) if f else {})


def rebuild(conn: sqlite3.Connection) -> int:
    """Read every item's words again from the search index, and match them. Returns the number of items with a mention."""
    f = finder(conn)
    with transaction(conn):
        conn.execute("DELETE FROM tagged_words")
        conn.execute("DELETE FROM tagged_mentions")
        found: list[Mention] = []
        rows: list[tuple[str, str, str, int]] = []
        for kind, item_id, text in list(item_texts(conn)):
            words = words_of(text)
            rows += [(kind, item_id, w, n) for w, n in words.items()]
            if f:
                found += mentions_in(f, kind, item_id, words, text).values()
        conn.executemany("INSERT INTO tagged_words (kind, id, word, n) VALUES (?, ?, ?, ?)", rows)
        _insert_mentions(conn, found)
        conn.execute("INSERT INTO app_state (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = '1'", (WORDS_KEY,))
    items = len({(m.kind, m.id) for m in found})
    log.info("tagged labels rebuilt: %d words kept, %d items with a mention", len(rows), items)
    return items


def rematch(conn: sqlite3.Connection) -> int:
    """Match every item again after the glossary changed: its kept words, and its text for word aliases. Words not kept
    yet (a data root from before release 5.79) are read first, from the search index. Returns the items with a mention."""
    if get_state(conn, WORDS_KEY) != "1":
        return rebuild(conn)
    f = finder(conn)
    words: dict[tuple[str, str], dict[str, int]] = {}
    for r in conn.execute("SELECT kind, id, word, n FROM tagged_words"):
        words.setdefault((r["kind"], r["id"]), {})[r["word"]] = r["n"]
    found: dict[tuple[str, str], dict[int, Mention]] = {}
    if f:
        for (kind, item_id), ws in words.items():
            got = mentions_in(f, kind, item_id, ws, None)
            if got:
                found[(kind, item_id)] = got
        if f.words_re is not None:
            for kind, item_id, text in item_texts(conn):
                for h in f.find_words(text):
                    ms = found.setdefault((kind, item_id), {})
                    m = ms.get(h.label) or ms.setdefault(h.label, Mention(kind, item_id, h.label, h.how, 0))
                    m.n += 1
                    m.written[h.written] = m.written.get(h.written, 0) + 1
    with transaction(conn):
        conn.execute("DELETE FROM tagged_mentions")
        _insert_mentions(conn, (m for ms in found.values() for m in ms.values()))
    return len(found)


# ---- changing the glossary ----
class TaggedError(ValueError):
    """A change to the glossary that can't be made, with the reason in words."""


def check_aliases(labels: Iterable[Label], label_id: int | None, aliases: Iterable[str]) -> list[str]:
    """Why any of these aliases can't be used for this label: only digits, or another label's name or alias."""
    taken: dict[str, str] = {}
    for lb in labels:
        if lb.id == label_id:
            continue
        for name in (lb.label, *lb.aliases):
            taken.setdefault(key_of(name) if tag_like(name) else " ".join(name.lower().split()), lb.label)
    problems = []
    for a in aliases:
        if only_digits(a):
            problems.append(f'"{a}" is only digits, so it would match every such number.')
            continue
        other = taken.get(key_of(a) if tag_like(a) else " ".join(a.lower().split()))
        if other:
            problems.append(f'"{a}" is {other}\'s already.')
    return problems


def add_label(conn: sqlite3.Connection, label: str, at: datetime, description: str = "", aliases: Iterable[str] = (),
              came: str = "hand", source: str | None = None) -> int:
    """Add a label to the glossary. Raises TaggedError for one that's there already, or has no letter or digit."""
    label = label.strip()
    k = key_of(label)
    if not k:
        raise TaggedError("A tagged label needs a letter or a digit.")
    have = conn.execute("SELECT label FROM tagged_labels WHERE key = ?", (k,)).fetchone()
    if have:
        raise TaggedError(f"{have['label']} is in the glossary already" + ("." if have["label"] == label else f", and {label} is it written another way."))
    aliases = list(aliases)
    problems = check_aliases(read_labels(conn), None, aliases)
    if problems:
        raise TaggedError(" ".join(problems))
    with transaction(conn):
        cur = conn.execute("INSERT INTO tagged_labels (label, key, description, came, source, added) VALUES (?, ?, ?, ?, ?, ?)",
                           (label, k, description.strip(), came, source, at.isoformat(timespec="seconds")))
        new_id = int(cur.lastrowid)
        conn.executemany("INSERT INTO tagged_aliases (label, alias, pos) VALUES (?, ?, ?)", [(new_id, a, i) for i, a in enumerate(aliases)])
        glossary_changed(conn)
    rematch(conn)
    return new_id


def edit_label(conn: sqlite3.Connection, label_id: int, description: str, aliases: Iterable[str]) -> None:
    """Change a label's description and aliases (the label page's Edit), and match everything again."""
    aliases = list(dict.fromkeys(a.strip() for a in aliases if a.strip()))
    labels = read_labels(conn)
    problems = check_aliases(labels, label_id, aliases)
    if problems:
        raise TaggedError(" ".join(problems))
    with transaction(conn):
        conn.execute("UPDATE tagged_labels SET description = ? WHERE id = ?", (description.strip(), label_id))
        conn.execute("DELETE FROM tagged_aliases WHERE label = ?", (label_id,))
        conn.executemany("INSERT INTO tagged_aliases (label, alias, pos) VALUES (?, ?, ?)", [(label_id, a, i) for i, a in enumerate(aliases)])
        glossary_changed(conn)
    rematch(conn)


def choose(conn: sqlite3.Connection, kind: str, item_id: str, key: str, choice: str | None, at: datetime) -> None:
    """The owner's own change on a capture or document (decision 376): ``removed``, ``added``, or None to undo either."""
    with transaction(conn):
        if choice is None:
            conn.execute("DELETE FROM tagged_choices WHERE kind = ? AND id = ? AND key = ?", (kind, item_id, key))
        else:
            conn.execute("INSERT INTO tagged_choices (kind, id, key, choice, at) VALUES (?, ?, ?, ?, ?) "
                         "ON CONFLICT(kind, id, key) DO UPDATE SET choice = excluded.choice, at = excluded.at",
                         (kind, item_id, key, choice, at.isoformat(timespec="seconds")))


# ---- what the browse tool reads: loaded once with the Model ----
@dataclass
class Tagged:
    """The glossary, every item's mentions and the owner's own changes, as of one read of docs.db."""

    labels: dict[int, Label] = field(default_factory=dict)
    mentions: list[Mention] = field(default_factory=list)
    choices: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)  # (kind, id) -> key -> choice
    _kept: _Kept | None = None

    def __post_init__(self) -> None:
        self.by_key = {lb.key: lb for lb in self.labels.values()}
        self.by_item: dict[tuple[str, str], list[Mention]] = {}
        self.by_label: dict[int, list[Mention]] = {}
        for m in self.mentions:
            self.by_item.setdefault((m.kind, m.id), []).append(m)
            self.by_label.setdefault(m.label, []).append(m)

    def __bool__(self) -> bool:
        return bool(self.labels)

    def finder(self) -> Finder:
        if self._kept is None:
            self._kept = _Kept(list(self.labels.values()))
        return self._kept.finder()

    def sorted_labels(self) -> list[Label]:
        return sorted(self.labels.values(), key=lambda lb: natural(lb.label))

    def item(self, kind: str, item_id: str) -> list[tuple[Label, Mention | None]]:
        """An item's tagged labels after the owner's own changes, each with what was found (None for one added by hand)."""
        own = self.choices.get((kind, item_id), {})
        out = [(self.labels[m.label], m) for m in self.by_item.get((kind, item_id), []) if m.label in self.labels
               and own.get(self.labels[m.label].key) != "removed"]
        have = {lb.key for lb, _ in out}
        out += [(self.by_key[k], None) for k, c in own.items() if c == "added" and k in self.by_key and k not in have]
        return sorted(out, key=lambda x: (-(x[1].n if x[1] else 0), natural(x[0].label)))

    def removed(self, kind: str, item_id: str) -> list[Label]:
        own = self.choices.get((kind, item_id), {})
        return [self.by_key[k] for k, c in own.items() if c == "removed" and k in self.by_key]


def load(conn: sqlite3.Connection) -> Tagged:
    kept = _glossary(conn)
    labels = {lb.id: lb for lb in kept.labels}
    if not labels:
        return Tagged()
    mentions = [Mention(r["kind"], r["id"], r["label"], r["how"], r["n"], json.loads(r["written"]))
                for r in conn.execute("SELECT * FROM tagged_mentions ORDER BY kind, id")]
    choices: dict[tuple[str, str], dict[str, str]] = {}
    for r in conn.execute("SELECT kind, id, key, choice FROM tagged_choices"):
        choices.setdefault((r["kind"], r["id"]), {})[r["key"]] = r["choice"]
    return Tagged(labels, mentions, choices, kept)


def natural(text: str) -> list:
    """Sort key: V-9 before V-10."""
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", text)]


# ---- what a task, a label and an item show (the browse tool, Task.md, the Task view) ----
@dataclass(frozen=True)
class Use:
    """One item that mentions a label, for its page: a capture, a document, a notes page (its task's ID) or a task's own
    fields (kind "task"), with how often and as written."""

    kind: str
    id: str
    n: int
    written: Mapping[str, int]
    how: str


def item_kind(kind: str) -> str:
    """The kind tagged_choices and the browse tool use for an item: a document is "document" here, "doc" in a link."""
    return "document" if kind == "doc" else kind


def live(model: Model, kind: str, item_id: str) -> bool:
    """An item that's still shown: not a discarded capture or task, and not a document only discarded captures brought."""
    if kind == "capture":
        c = model.captures.get(item_id)
        return c is not None and not c.discarded
    if kind == "document":
        return item_id in model.documents and not model.only_in_discarded(item_id)
    t = model.tasks.get(item_id)
    return t is not None and not t.discarded


def uses_of(model: Model, label: Label) -> list[Use]:
    """Everything that mentions a label: its kept mentions, after the owner's own changes, and the tasks whose own fields do."""
    tg = model.tagged
    out: list[Use] = []
    for m in tg.by_label.get(label.id, []):
        if live(model, m.kind, m.id) and tg.choices.get((m.kind, m.id), {}).get(label.key) != "removed":
            out.append(Use(m.kind, m.id, m.n, m.written, m.how))
    for (kind, item_id), own in tg.choices.items():
        if own.get(label.key) == "added" and not any(u.kind == kind and u.id == item_id for u in out) and live(model, kind, item_id):
            out.append(Use(kind, item_id, 0, {}, "hand"))
    f = tg.finder()
    for t in model.tasks.values():
        if t.discarded:
            continue
        hits = [h for h in f.find(task_text(t, model)) if h.label == label.id]
        if hits:
            out.append(Use("task", t.id, len(hits), dict(Counter(h.written for h in hits)), hits[0].how))
    return out


def task_tags(model: Model, task_id: str) -> list[tuple[Label, int]]:
    """A task's tagged labels (decision 367): from its own fields, its notes page, its captures and their documents, and
    the documents it holds, each item counted once. Each label with how often it's mentioned, the most first."""
    tg = model.tagged
    if not tg:
        return []
    counts: Counter[int] = Counter()
    for h in tg.finder().find(task_text(model.task(task_id), model)):
        counts[h.label] += 1
    seen: set[tuple[str, str]] = set()

    def add(kind: str, item_id: str) -> None:
        if (kind, item_id) in seen:
            return
        seen.add((kind, item_id))
        for lb, m in tg.item(kind, item_id):
            counts[lb.id] += m.n if m else 1

    add("page", task_id)
    for c in model.notes_of(task_id):
        add("capture", c.id)
        for d in c.document_ids:
            add("document", d)
    for d in model.documents:
        if task_id in model.document_holders(d):
            add("document", d)
    return sorted(((tg.labels[i], n) for i, n in counts.items() if i in tg.labels), key=lambda x: (-x[1], natural(x[0].label)))


def counts(model: Model) -> dict[int, int]:
    """How many items mention each label (the Tagged labels view's Items column), in one pass over the mentions and the
    tasks, as ``uses_of`` counts them one label at a time."""
    tg = model.tagged
    out: Counter[int] = Counter()
    dead_docs = {m.id for m in tg.mentions if m.kind == "document" and not live(model, "document", m.id)}
    alive = lambda kind, item_id: item_id not in dead_docs if kind == "document" else live(model, kind, item_id)  # noqa: E731
    have: set[tuple[str, str, int]] = set()
    for m in tg.mentions:
        lb = tg.labels.get(m.label)
        if lb and alive(m.kind, m.id) and tg.choices.get((m.kind, m.id), {}).get(lb.key) != "removed":
            out[m.label] += 1
            have.add((m.kind, m.id, m.label))
    for (kind, item_id), own in tg.choices.items():
        for k, c in own.items():
            lb = tg.by_key.get(k)
            if c == "added" and lb and (kind, item_id, lb.id) not in have and alive(kind, item_id):
                out[lb.id] += 1
    f = tg.finder()
    for t in model.tasks.values():
        if not t.discarded:
            for label in {h.label for h in f.find(task_text(t, model))}:
                out[label] += 1
    return dict(out)


def label_named(tagged: Tagged, text: str) -> Label | None:
    """The one label ``text`` names, however it's typed: by its key, a tag-shaped alias's, or a word alias whole."""
    k, words = key_of(text), " ".join(text.lower().split())
    for lb in tagged.labels.values():
        if (k and lb.key == k) or any((key_of(a) == k) if tag_like(a) else (" ".join(a.lower().split()) == words) for a in lb.aliases):
            return lb
    return None


def find_labels(tagged: Tagged, query: str) -> list[Label]:
    """The labels a search names (decision 378): by their key or an alias's, however typed ("v110" finds V-110), or
    by its start when it has a digit and three characters or more ("P-204" finds P-204A and P-204B), or by a word alias
    typed whole."""
    k = key_of(query)
    out: list[Label] = []
    if len(k) >= 2 and _DIGIT.search(k):
        for lb in tagged.sorted_labels():
            if lb.key == k or any(tag_like(a) and key_of(a) == k for a in lb.aliases):
                out.insert(0, lb)
            elif len(k) >= 3 and lb.key.startswith(k):
                out.append(lb)
    else:
        words = " ".join(query.lower().split())
        if len(words) > 3:
            out = [lb for lb in tagged.sorted_labels() if any(not tag_like(a) and " ".join(a.lower().split()) == words for a in lb.aliases)
                   or (not tag_like(lb.label) and " ".join(lb.label.lower().split()) == words)]
    return list(dict.fromkeys(out))
