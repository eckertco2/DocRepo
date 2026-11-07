"""Tagged labels (release 5.79; the tagged labels plan, items 102 to 105, decisions 365 to 381): plant tags, such as
V-110 or FIC-2210, found in everything DocRepo reads as text.

- **The glossary** (``tagged_labels``, ``tagged_aliases``): each tagged label with its description and aliases, imported
  from Excel or CSV (``docrepo.tagged_import``), edited in the browse tool, or added by hand. A label is known by its
  **key**, its letters and digits in capitals, so V-110 and V110 are one label.
- **Matching with no setup** (decision 368): a label, or a tag-shaped alias (one with a digit and no space), is found
  however its parts are joined: a hyphen, an en dash, an underscore, nothing, or a space between capitals. So V-110 is
  found as V110, v-110 and V 110, and "page 101" isn't P-101. A label with fewer than four letters and digits (E-12) must
  be in capitals with no space. Any other alias ("feed drum", "CT fan 1") is found as whole words, in any case
  (decision 369). P-204A is its own label, and "P-204A/B" mentions P-204A and P-204B (decision 370), "P-204A/B/C" all three.
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
- **Tag patterns** (release 5.80, items 106 and 107, decisions 372 to 375 and 377): masks (``docrepo.tagged_masks``) find
  tags that aren't in the glossary. A match with no glossary label becomes a tagged label at once, a **suggested** row in
  ``tagged_labels`` (status ``suggested``, how it came ``pattern``, the pattern's name), marked new where it shows, until
  the owner adds it to the glossary (``accept``), makes it another label's alias (``same_as``) or puts it on Never a tag.
  A glossary label is always found first; Never a tag applies to patterns only. "P-204A/B" a pattern finds is both tags,
  as for a glossary label, when the mask allows the other letter where the first was. The patterns and Never a tag are the
  owner's, in the data root's ``Config\\settings.json``; docs.db keeps a copy in ``app_state`` (``set_patterns``), made
  again from settings.json at each start (``use_settings``), so a save matches without reading the settings. A pattern
  change matches the kept words again, as a glossary change does. A suggested label nothing mentions any more is
  dropped when everything is matched again.

Nothing here touches Qt. Pure functions (``Finder``, ``words_of``) are tested on their own.
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING

from docrepo import tagged_masks as masks
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
#: The most kept words a Finder remembers the hits of (``Finder.in_run``) before it starts again.
RUNS_KEPT = 200_000
#: The kinds of item that hold text, as the search index names them.
KINDS = ("capture", "document", "page")
VERSION_KEY = "tagged_glossary"  # app_state: a new token each time the glossary or the patterns change, so a kept Finder knows
WORDS_KEY = "tagged_words_built"  # app_state: every item's words have been kept, in the form WORDS_FORM
#: The form of the kept words: "1" (release 5.79), "2" with runs joined across a / or a dot too (release 5.80), so a mask
#: such as TK-##/# is found in them. Kept words in an older form are read again from the search index at the next match.
WORDS_FORM = "2"
PATTERNS_KEY = "tagged_patterns"  # app_state: docs.db's copy of the patterns and Never a tag in settings.json (release 5.80)

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_PAIR = re.compile(r"/([A-Z])(?![A-Za-z0-9])")
#: What joins two runs of letters and digits into one kept word besides the marks: a / or a dot (release 5.80).
_JOINS = masks.JOINERS
_LETTER, _DIGIT = re.compile(r"[A-Za-z]"), re.compile(r"[0-9]")


def _pairs(text: str, end: int) -> Iterator[re.Match[str]]:
    """The letters after a tag that ends at ``end``, each after a slash: "/B" in P-204A/B, "/B" and "/C" in P-204A/B/C."""
    while (pair := _PAIR.match(text, end)) is not None:
        yield pair
        end = pair.end()


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
    """One place a label is mentioned: where in the text, as written, and how it was found (label, alias, word or pair;
    since release 5.80 "new" for a label a pattern found that isn't in the glossary, and "never" for one on Never a tag).
    A pattern's hit has its key, the pattern's name and the label as the mask spells it; ``label`` is 0 for a new one
    with no row in docs.db yet."""

    start: int
    end: int
    written: str
    label: int
    how: str
    key: str = ""
    pattern: str = ""
    spelled: str = ""


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
    """Finds a glossary's labels in text, and what its tag patterns find (release 5.80). Built once per version of the
    glossary and the patterns. Only glossary labels are matched however they're written; a suggested label is found
    only by a pattern."""

    def __init__(self, labels: Iterable[Label], patterns: Iterable[masks.Pattern] = (), never: Iterable[str] = ()) -> None:
        self.keys: dict[str, tuple[int, str]] = {}  # key -> (label id, how)
        phrases: dict[str, tuple[int, str]] = {}  # a word alias in lower case, its words one space apart -> (label id, how)
        self.named: dict[str, tuple[int, str]] = {}  # every glossary name's key -> (label id, how), for what a pattern spells
        self.suggested: dict[str, int] = {}  # a suggested label's key -> its id
        for lb in labels:
            if lb.status != "glossary":
                self.suggested.setdefault(lb.key, lb.id)
                continue
            for name, how in ((lb.label, "label"), *((a, "alias") for a in lb.aliases)):
                if tag_like(name):
                    self.keys.setdefault(key_of(name), (lb.id, how))
                elif name.strip():
                    phrases.setdefault(" ".join(name.lower().split()), (lb.id, "label" if how == "label" else "word"))
                if key_of(name):
                    self.named.setdefault(key_of(name), (lb.id, how))
        self.masks: list[tuple[masks.Pattern, masks.Compiled]] = []
        for p in patterns:
            try:
                self.masks.append((p, masks.compile_mask(p.mask, p.space)))
            except masks.MaskError as e:  # settings.json changed by hand: the other patterns still work
                log.warning("tag pattern %r left out: %s", p.name, e)
        self.never = masks.Never(never)
        self._runs: dict[str, list[Hit]] = {}  # in_run's: what each kept word met mentions
        self.phrases = phrases
        self.words_re: re.Pattern[str] | None = None
        if phrases:
            alts = sorted(phrases, key=len, reverse=True)  # the longest first, so "ct fan 1" wins over "ct fan"
            body = "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in alts)
            self.words_re = re.compile(rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])", re.IGNORECASE)

    def __bool__(self) -> bool:
        return bool(self.keys or self.phrases or self.masks)

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
            k = key_of(text[toks[i].start():end])
            for pair in _pairs(text, end) if k[-1:].isalpha() else ():  # P-204A/B/C: the same tag with each letter (decision 370)
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

    def find_patterns(self, text: str, taken: Iterable[Hit] = ()) -> list[Hit]:
        """What the patterns find where nothing in ``taken`` is, each pattern in turn (release 5.80, decisions 372, 374 and
        375). Each match is spelled as its mask is. A glossary label with that key is that label (how "label" or "alias":
        a glossary label is always found); else one on Never a tag is "never"; else it's "new", with its suggested label's
        row, or label 0 for one with no row yet. "P-204A/B" is P-204A and P-204B, as it is for a glossary label (decision
        370), when the mask allows the other letter too: its hit is the "/B", how "pair" if it's a glossary label."""
        out: list[Hit] = []
        if not self.masks:
            return out
        spans = [(h.start, h.end) for h in taken]
        for p, c in self.masks:
            for m in c.regex.finditer(text):
                s, e = m.span()
                if any(s < b and a < e for a, b in spans):
                    continue
                spans.append((s, e))
                spelled = masks.spell(m, c)
                out.append(self._pattern_hit(s, e, m.group(), spelled, p.name))
                for pair in _pairs(text, e) if spelled[-1:].isalpha() else ():
                    other = spelled[:-1] + pair.group(1)
                    if c.regex.fullmatch(other) and not any(pair.start() < b and a < pair.end() for a, b in spans):
                        spans.append(pair.span())
                        h = self._pattern_hit(pair.start(), pair.end(), pair.group(), other, p.name)
                        out.append(replace(h, how="pair") if h.how in ("label", "alias") else h)
        return out

    def _pattern_hit(self, s: int, e: int, written: str, spelled: str, pattern: str) -> Hit:
        """What a pattern's match is: a glossary label with its key, one on Never a tag, or a new one."""
        k = key_of(spelled)
        g = self.named.get(k)
        if g:
            return Hit(s, e, written, g[0], "label" if g[1] == "label" else "alias", k, pattern, spelled)
        if spelled in self.never:
            return Hit(s, e, written, 0, "never", k, pattern, spelled)
        return Hit(s, e, written, self.suggested.get(k, 0), "new", k, pattern, spelled)

    def in_run(self, run: str) -> list[Hit]:
        """What one kept word mentions (``words_of``): the glossary's tags, then what the patterns find, without what's on
        Never a tag. Kept for each word met, as the same tags recur across a data root's items."""
        hits = self._runs.get(run)
        if hits is None:
            if len(self._runs) > RUNS_KEPT:
                self._runs.clear()
            tags = self.find_tags(run)
            hits = self._runs[run] = [*tags, *(h for h in self.find_patterns(run, tags) if h.how != "never")]
        return hits

    def find_all(self, text: str) -> list[Hit]:
        """Every mention in ``text``, in order, with what the patterns find that has no row yet, and what's on Never a
        tag: Settings' tester shows them all (decision 373)."""
        tags = self.find_tags(text)
        words = [h for h in self.find_words(text) if not any(h.start < t.end and t.start < h.end for t in tags)]
        return sorted([*tags, *words, *self.find_patterns(text, [*tags, *words])], key=lambda h: h.start)

    def find(self, text: str) -> list[Hit]:
        """Every mention in ``text``, in order: the glossary's, and the suggested labels the patterns find."""
        return [h for h in self.find_all(text) if h.label and h.how != "never"]


def words_of(text: str) -> Counter[str]:
    """The text's tag-like words as written: runs of letters and digits joined by one mark each (a space only between
    capitals), or by a / or a dot (release 5.80, so a pair's "/B" and a mask's own / are kept on), with a letter and a
    digit (decision 377). Every tag a glossary or a pattern could match lies inside one of these, so they're all a change
    to either needs."""
    out: Counter[str] = Counter()
    toks = list(_TOKEN.finditer(text))
    i = 0
    while i < len(toks):
        j = i
        while j + 1 < len(toks):
            gap = text[toks[j].end():toks[j + 1].start()]
            if len(gap) != 1 or gap not in MARKS + _JOINS or (gap == " " and not _spaced_ok(toks[j].group(), toks[j + 1].group())):
                break
            j += 1
        run = text[toks[i].start():toks[j].end()]
        if _LETTER.search(run) and _DIGIT.search(run):
            out[run] += 1
        i = j + 1
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


def task_texts(conn: sqlite3.Connection, task_id: str | None = None) -> Iterable[tuple[str, str]]:
    """Each task's own fields as ``task_text`` reads them, from docs.db without the Model (release 5.80): (task ID, text),
    for every task or one. Discarded tasks are left out."""
    dates: dict[str, list[str]] = {}
    for r in conn.execute("SELECT task, description FROM task_dates WHERE description != '' AND (? IS NULL OR task = ?) ORDER BY task, pos, id",
                          (task_id, task_id)):
        dates.setdefault(r["task"], []).append(r["description"])
    for r in conn.execute("SELECT id, title, description, current_status, deadline_desc FROM tasks WHERE discarded IS NULL "
                          "AND (? IS NULL OR id = ?) ORDER BY id", (task_id, task_id)):
        yield r["id"], "\n".join(x for x in (r["title"], r["description"], r["current_status"], r["deadline_desc"] or "",
                                             *dates.get(r["id"], ())) if x)


def mentions_in(finder: Finder, kind: str, item_id: str, words: Mapping[str, int], text: str | None,
                new: Callable[[Hit], int] | None = None) -> dict[int, Mention]:
    """What one item mentions, from its kept words (and its text, for word aliases). What the patterns find in the words
    is a glossary label or a new one (release 5.80): ``new`` gives a new one's row, making it if there's none; without
    it, only a new one with a row counts."""
    out: dict[int, Mention] = {}

    def add(h: Hit, n: int) -> None:
        m = out.get(h.label)
        if m is None:
            m = out[h.label] = Mention(kind, item_id, h.label, h.how, 0)
        m.n += n
        m.written[h.written] = m.written.get(h.written, 0) + n

    for run, n in words.items():
        for h in finder.in_run(run):
            if h.how != "new":
                add(h, n)
                continue
            label = new(h) if new is not None else h.label
            if label:
                add(replace(h, label=label) if label != h.label else h, n)
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


def patterns_state(conn: sqlite3.Connection) -> tuple[list[masks.Pattern], list[str]]:
    """docs.db's copy of the tag patterns and Never a tag (release 5.80), as ``set_patterns`` kept them."""
    raw = get_state(conn, PATTERNS_KEY)
    if not raw:
        return [], []
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("docs.db's copy of the tag patterns can't be read; it's made again from settings.json at the next start")
        return [], []
    never = data.get("never") if isinstance(data, dict) else None
    return masks.patterns_of(data.get("patterns") if isinstance(data, dict) else None), masks.never_of(never if isinstance(never, list) else [])


class _Kept:
    """One version of the glossary and the patterns, read once: its labels, and its Finder when it's first needed. A
    save builds the Model several times, and 20,000 labels took 0.1 s to read each time."""

    def __init__(self, labels: list[Label], patterns: list[masks.Pattern] = (), never: list[str] = ()) -> None:
        self.labels = labels
        self.patterns, self.never = list(patterns), list(never)
        self._finder: Finder | None = None

    def finder(self) -> Finder:
        if self._finder is None:
            self._finder = Finder(self.labels, self.patterns, self.never)
        return self._finder


_kept: dict[str, _Kept] = {}


def _glossary(conn: sqlite3.Connection) -> _Kept:
    """The glossary and patterns as they are: kept by their version's token, which every change to either makes new
    (``glossary_changed``)."""
    token = get_state(conn, VERSION_KEY)
    if token is None:
        return _Kept(read_labels(conn), *patterns_state(conn))
    kept = _kept.get(token)
    if kept is None:
        if len(_kept) > 4:
            _kept.clear()
        kept = _kept[token] = _Kept(read_labels(conn), *patterns_state(conn))
    return kept


def finder(conn: sqlite3.Connection) -> Finder:
    """The Finder for the glossary and patterns as they are, kept until either changes."""
    return _glossary(conn).finder()


def glossary_changed(conn: sqlite3.Connection) -> None:
    set_state(conn, VERSION_KEY, uuid.uuid4().hex)


class _Suggest:
    """Gives a new tagged label a pattern found its row (decision 374): a suggested one, made the first time its key is
    met, with the pattern's name. Remembers which pattern found each, and whether it made any."""

    def __init__(self, conn: sqlite3.Connection, at: datetime | None = None) -> None:
        self.conn = conn
        self.at = (at or datetime.now()).isoformat(timespec="seconds")
        self.ids: dict[str, int] = {}
        self.found_by: dict[int, str] = {}  # label -> the pattern that found it first in this pass
        self.made = 0

    def __call__(self, h: Hit) -> int:
        i = h.label or self.ids.get(h.key)
        if not i:
            row = self.conn.execute("SELECT id FROM tagged_labels WHERE key = ?", (h.key,)).fetchone()
            if row is not None:
                i = row["id"]
            else:
                cur = self.conn.execute("INSERT INTO tagged_labels (label, key, status, came, pattern, added) VALUES (?, ?, 'suggested', 'pattern', ?, ?)",
                                        (h.spelled, h.key, h.pattern, self.at))
                i = int(cur.lastrowid)
                self.made += 1
            self.ids[h.key] = i
        self.found_by.setdefault(i, h.pattern)
        return i


# ---- keeping it current ----
def _store(conn: sqlite3.Connection, kind: str, item_id: str, words: Counter[str], found: Mapping[int, Mention]) -> None:
    conn.execute("DELETE FROM tagged_words WHERE kind = ? AND id = ?", (kind, item_id))
    conn.executemany("INSERT INTO tagged_words (kind, id, word, n) VALUES (?, ?, ?, ?)", [(kind, item_id, w, n) for w, n in words.items()])
    conn.execute("DELETE FROM tagged_mentions WHERE kind = ? AND id = ?", (kind, item_id))
    _insert_mentions(conn, found.values())


def _insert_mentions(conn: sqlite3.Connection, ms: Iterable[Mention]) -> None:
    conn.executemany("INSERT INTO tagged_mentions (kind, id, label, how, n, written) VALUES (?, ?, ?, ?, ?, ?)",
                     [(m.kind, m.id, m.label, m.how, m.n, json.dumps(m.written, ensure_ascii=False)) for m in ms])


_batches: dict[int, tuple[Finder, _Suggest]] = {}  # id(conn) -> the Finder and the new rows of the items indexed together


@contextlib.contextmanager
def batch(conn: sqlite3.Connection) -> Iterator[None]:
    """Index several items together (the search index's calls, release 5.80): one Finder for them all, and the glossary's
    version changed once at the end if a pattern gave any new label its row, rather than after each item, which would
    read the glossary again for the next. Inside a transaction, so a rollback takes the new rows with it."""
    if id(conn) in _batches:
        yield
        return
    with transaction(conn):
        _batches[id(conn)] = (finder(conn), _Suggest(conn))
        try:
            yield
            made = _batches[id(conn)][1].made
        finally:
            del _batches[id(conn)]
        if made:
            glossary_changed(conn)


def index(conn: sqlite3.Connection, kind: str, item_id: str, text: str) -> None:
    """Keep one item's words and mentions, from its text (``text_of_body``, ``page_text``). Called inside the search
    index's transaction. A new tagged label a pattern finds gets its row at once (decision 374)."""
    words = words_of(text)
    with batch(conn):
        f, new = _batches[id(conn)]
        _store(conn, kind, item_id, words, mentions_in(f, kind, item_id, words, text, new) if f else {})


def index_task(conn: sqlite3.Connection, task_id: str) -> None:
    """A task's own fields were written (release 5.80): a new tagged label a pattern finds in them gets its row at once,
    as one in a capture does. They're read as they are wherever they show, so nothing else is kept."""
    f = finder(conn)
    if not f.masks:
        return
    text = next((x for _, x in task_texts(conn, task_id)), "")
    with transaction(conn):
        new = _Suggest(conn)
        for h in f.find_all(text):
            if h.how == "new":
                new(h)
        if new.made:
            glossary_changed(conn)


def _task_suggestions(conn: sqlite3.Connection, f: Finder, new: _Suggest) -> set[int]:
    """The suggested labels the tasks' own fields mention, given their rows."""
    used: set[int] = set()
    if f.masks:
        for _, text in task_texts(conn):
            used |= {new(h) for h in f.find_all(text) if h.how == "new"}
    return used


def _tidy(conn: sqlite3.Connection, used: set[int], new: _Suggest) -> bool:
    """After everything is matched again: drop the suggested labels nothing mentions now (nor the owner added by hand),
    and give the rest the name of the pattern that found them, which may have been renamed. True if anything changed."""
    added = {r["key"] for r in conn.execute("SELECT DISTINCT key FROM tagged_choices WHERE choice = 'added'")}
    gone, renamed = [], []
    for r in conn.execute("SELECT id, key, pattern FROM tagged_labels WHERE status = 'suggested'").fetchall():
        if r["id"] not in used and r["key"] not in added:
            gone.append((r["id"],))
        elif r["id"] in new.found_by and new.found_by[r["id"]] != r["pattern"]:
            renamed.append((new.found_by[r["id"]], r["id"]))
    conn.executemany("DELETE FROM tagged_aliases WHERE label = ?", gone)
    conn.executemany("DELETE FROM tagged_mentions WHERE label = ?", gone)
    conn.executemany("DELETE FROM tagged_labels WHERE id = ?", gone)
    conn.executemany("UPDATE tagged_labels SET pattern = ? WHERE id = ?", renamed)
    return bool(gone or renamed or new.made)


def rebuild(conn: sqlite3.Connection) -> int:
    """Read every item's words again from the search index, and match them. Returns the number of items with a mention."""
    f = finder(conn)
    with transaction(conn):
        conn.execute("DELETE FROM tagged_words")
        conn.execute("DELETE FROM tagged_mentions")
        new = _Suggest(conn)
        found: list[Mention] = []
        rows: list[tuple[str, str, str, int]] = []
        for kind, item_id, text in list(item_texts(conn)):
            words = words_of(text)
            rows += [(kind, item_id, w, n) for w, n in words.items()]
            if f:
                found += mentions_in(f, kind, item_id, words, text, new).values()
        conn.executemany("INSERT INTO tagged_words (kind, id, word, n) VALUES (?, ?, ?, ?)", rows)
        _insert_mentions(conn, found)
        used = {m.label for m in found} | _task_suggestions(conn, f, new)
        if _tidy(conn, used, new):
            glossary_changed(conn)
        conn.execute("INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (WORDS_KEY, WORDS_FORM))
    items = len({(m.kind, m.id) for m in found})
    log.info("tagged labels rebuilt: %d words kept, %d items with a mention", len(rows), items)
    return items


def rematch(conn: sqlite3.Connection) -> int:
    """Match every item again after the glossary or the patterns changed: its kept words, and its text for word aliases
    (decision 377). Words not kept yet, or kept in an older form (a data root from before release 5.79 or 5.80), are read
    first, from the search index. Returns the items with a mention."""
    if get_state(conn, WORDS_KEY) != WORDS_FORM:
        return rebuild(conn)
    f = finder(conn)
    words: dict[tuple[str, str], dict[str, int]] = {}
    for r in conn.execute("SELECT kind, id, word, n FROM tagged_words"):
        words.setdefault((r["kind"], r["id"]), {})[r["word"]] = r["n"]
    with transaction(conn):
        new = _Suggest(conn)
        found: dict[tuple[str, str], dict[int, Mention]] = {}
        if f:
            for (kind, item_id), ws in words.items():
                got = mentions_in(f, kind, item_id, ws, None, new)
                if got:
                    found[(kind, item_id)] = got
            if f.words_re is not None:
                for kind, item_id, text in item_texts(conn):
                    for h in f.find_words(text):
                        ms = found.setdefault((kind, item_id), {})
                        m = ms.get(h.label) or ms.setdefault(h.label, Mention(kind, item_id, h.label, h.how, 0))
                        m.n += 1
                        m.written[h.written] = m.written.get(h.written, 0) + 1
        conn.execute("DELETE FROM tagged_mentions")
        _insert_mentions(conn, (m for ms in found.values() for m in ms.values()))
        used = {label for ms in found.values() for label in ms} | _task_suggestions(conn, f, new)
        if _tidy(conn, used, new):
            glossary_changed(conn)
    return len(found)


# ---- the patterns (release 5.80) ----
def set_patterns(conn: sqlite3.Connection, patterns: Iterable[masks.Pattern], never: Iterable[str], match: bool = True) -> int | None:
    """Keep docs.db's copy of the tag patterns and Never a tag, and match everything again from the kept words (decision
    377). Returns the items with a mention, or None when they're as kept already. ``match`` False leaves the matching to
    a rebuild that follows."""
    value = json.dumps({"patterns": [p.as_setting() for p in patterns], "never": masks.never_of(never)}, ensure_ascii=False, sort_keys=True)
    empty = json.dumps({"patterns": [], "never": []}, sort_keys=True)
    if (get_state(conn, PATTERNS_KEY) or empty) == value:
        return None
    with transaction(conn):
        set_state(conn, PATTERNS_KEY, value)
        glossary_changed(conn)
    log.info("tag patterns set: %d patterns, %d on Never a tag", value.count('"mask"'), len(masks.never_of(never)))
    return rematch(conn) if match else None


def use_settings(conn: sqlite3.Connection, settings, match: bool = True) -> int | None:
    """Make docs.db's copy of the patterns and Never a tag what settings.json says (at each start, and after Settings
    saves them), matching everything again if they changed."""
    return set_patterns(conn, masks.patterns_of(settings.tagged_patterns), settings.tagged_never, match)


# ---- changing the glossary ----
class TaggedError(ValueError):
    """A change to the glossary that can't be made, with the reason in words."""


def check_aliases(labels: Iterable[Label], label_id: int | None, aliases: Iterable[str]) -> list[str]:
    """Why any of these aliases can't be used for this label: only digits, or another glossary label's name or alias. A
    suggested label's name is free: Same as… makes it an alias."""
    taken: dict[str, str] = {}
    for lb in labels:
        if lb.id == label_id or lb.status != "glossary":
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
    """Add a label to the glossary. Raises TaggedError for one that's there already, or has no letter or digit. One that's
    suggested (release 5.80) is added to the glossary as it's typed here, as Add to glossary does."""
    label = label.strip()
    k = key_of(label)
    if not k:
        raise TaggedError("A tagged label needs a letter or a digit.")
    have = conn.execute("SELECT id, label, status FROM tagged_labels WHERE key = ?", (k,)).fetchone()
    if have and have["status"] == "suggested":
        accept(conn, k, description, aliases, label)
        return int(have["id"])
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


def _suggested_row(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tagged_labels WHERE key = ? AND status = 'suggested'", (key,)).fetchone()
    if row is None:
        raise TaggedError("It isn't a suggested tagged label any more: the glossary or the patterns changed.")
    return row


def accept(conn: sqlite3.Connection, key: str, description: str = "", aliases: Iterable[str] = (), label: str | None = None) -> None:
    """Add to glossary (release 5.80, item 107): a suggested label becomes an ordinary one, with a description and any
    aliases, keeping how it came and its pattern's name; then it's found however it's written, and everything is matched
    again. ``label`` respells it, as typed by the owner."""
    row = _suggested_row(conn, key)
    aliases = list(dict.fromkeys(a.strip() for a in aliases if a.strip()))
    problems = check_aliases(read_labels(conn), row["id"], aliases)
    if problems:
        raise TaggedError(" ".join(problems))
    with transaction(conn):
        conn.execute("UPDATE tagged_labels SET status = 'glossary', description = ?, label = ? WHERE id = ?",
                     (description.strip(), (label or "").strip() or row["label"], row["id"]))
        conn.execute("DELETE FROM tagged_aliases WHERE label = ?", (row["id"],))
        conn.executemany("INSERT INTO tagged_aliases (label, alias, pos) VALUES (?, ?, ?)", [(row["id"], a, i) for i, a in enumerate(aliases)])
        glossary_changed(conn)
    rematch(conn)


def same_as(conn: sqlite3.Connection, key: str, label_id: int) -> Label:
    """Same as… (release 5.80, item 107): a suggested label becomes an alias of a glossary label, and its mentions, and
    the owner's own changes on it, move there. Returns the label it's an alias of now."""
    row = _suggested_row(conn, key)
    target = next((lb for lb in read_labels(conn) if lb.id == label_id and lb.status == "glossary"), None)
    if target is None:
        raise TaggedError("Pick a tagged label from the glossary.")
    problems = check_aliases(read_labels(conn), target.id, [row["label"]])
    if problems:
        raise TaggedError(" ".join(problems))
    with transaction(conn):
        conn.execute("INSERT OR IGNORE INTO tagged_aliases (label, alias, pos) VALUES (?, ?, ?)", (target.id, row["label"], len(target.aliases)))
        conn.execute("INSERT OR IGNORE INTO tagged_choices (kind, id, key, choice, at) SELECT kind, id, ?, choice, at FROM tagged_choices WHERE key = ?",
                     (target.key, key))
        conn.execute("DELETE FROM tagged_choices WHERE key = ?", (key,))
        conn.execute("DELETE FROM tagged_mentions WHERE label = ?", (row["id"],))
        conn.execute("DELETE FROM tagged_labels WHERE id = ?", (row["id"],))
        glossary_changed(conn)
    rematch(conn)
    return target


def forget(conn: sqlite3.Connection, key: str) -> None:
    """Not a tag (release 5.80, decision 375), in docs.db: the owner's own changes on it go. The caller puts it on Never a
    tag, in settings.json, whose matching again removes it everywhere."""
    with transaction(conn):
        conn.execute("DELETE FROM tagged_choices WHERE key = ?", (key,))


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

    def glossary(self) -> list[Label]:
        """The glossary's labels, sorted, without the suggested ones (release 5.80)."""
        return [lb for lb in self.sorted_labels() if lb.status == "glossary"]

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


# ---- Suggested, the tester and Try on everything (release 5.80, decisions 373 and 374) ----
@dataclass(frozen=True)
class Suggestion:
    """A new tagged label waiting in the Tagged labels view's Suggested list: how many items mention it, and where it's
    seen, as top-level tasks, the most first, and how many items are on no task."""

    label: Label
    items: int
    places: tuple[str, ...]
    unfiled: int


def _tasks_of(model: Model, kind: str, item_id: str) -> list[str]:
    if kind == "capture":
        return model.capture_tasks(model.captures[item_id])
    if kind == "document":
        return model.document_holders(item_id)
    return [item_id]


def suggestions(model: Model) -> list[Suggestion]:
    """The suggested labels something mentions, the most mentioned first (decision 374), each with where it's seen."""
    tg = model.tagged
    wanted = {lb.id for lb in tg.labels.values() if lb.status == "suggested"}
    if not wanted:
        return []
    n = counts(model)
    places: dict[int, Counter[str]] = {i: Counter() for i in wanted}
    unfiled: Counter[int] = Counter()

    def seen(label: int, tasks: list[str]) -> None:
        tops = {model.chains_of(t)[0][0] for t in tasks if t in model.tasks}
        places[label].update(tops)
        if not tops:
            unfiled[label] += 1

    for m in tg.mentions:
        if m.label in wanted and live(model, m.kind, m.id) and tg.choices.get((m.kind, m.id), {}).get(tg.labels[m.label].key) != "removed":
            seen(m.label, _tasks_of(model, m.kind, m.id))
    f = tg.finder()
    for t in model.tasks.values():
        if not t.discarded:
            for label in {h.label for h in f.find(task_text(t, model))} & wanted:
                seen(label, [t.id])
    out = [Suggestion(tg.labels[i], n.get(i, 0), tuple(t for t, _ in places[i].most_common()), unfiled[i]) for i in wanted if n.get(i)]
    return sorted(out, key=lambda s: (-s.items, natural(s.label.label)))


def tester(labels: Iterable[Label], patterns: Iterable[masks.Pattern], never: Iterable[str], text: str) -> list[Hit]:
    """Settings' tester (decision 373): what the glossary and these patterns, as they stand in the form, find in text
    pasted there, each with how: a glossary label, an alias, a word alias, a pair, new from a named pattern, or on Never
    a tag. Nothing is kept."""
    return Finder(labels, patterns, never).find_all(text)


@dataclass
class Tried:
    """One new tagged label Try on everything would make: as the mask spells it, the pattern that found it, how many
    items mention it, and how it's written there."""

    label: str
    key: str
    pattern: str
    items: int = 0
    written: list[str] = field(default_factory=list)


def try_everything(conn: sqlite3.Connection, model: Model, patterns: Iterable[masks.Pattern], never: Iterable[str]) -> tuple[list[Tried], int]:
    """Try on everything (decision 373): run these patterns, before they're saved, over every capture, document, notes page
    and task DocRepo holds, from the kept words, so nothing is read again. Returns the new tagged labels they'd make (not
    in the glossary), the most frequent first, and how many items mention one. Nothing is changed."""
    f = Finder(read_labels(conn), patterns, never)
    if not f.masks:
        return [], 0
    if get_state(conn, WORDS_KEY) == WORDS_FORM:
        words: dict[tuple[str, str], dict[str, int]] = {}
        for r in conn.execute("SELECT kind, id, word, n FROM tagged_words"):
            words.setdefault((r["kind"], r["id"]), {})[r["word"]] = r["n"]
        runs = words.items()
    else:  # kept in an older form: read from the search index, without keeping them
        runs = (((kind, item_id), words_of(text)) for kind, item_id, text in item_texts(conn))
    out: dict[str, Tried] = {}
    items = 0

    def note(hits: Iterable[Hit]) -> int:
        """Count one item's new labels, each once. Returns how many it has."""
        keys: set[str] = set()
        for h in hits:
            if h.how == "new":
                t = out.get(h.key) or out.setdefault(h.key, Tried(h.spelled, h.key, h.pattern))
                if h.written not in t.written:
                    t.written.append(h.written)
                keys.add(h.key)
        for k in keys:
            out[k].items += 1
        return len(keys)

    for (kind, item_id), ws in runs:
        if not live(model, kind, item_id):  # a discarded capture or task, or a document only discarded captures brought
            continue
        items += bool(note(h for run in ws for h in f.in_run(run)))
    for _, text in task_texts(conn):
        items += bool(note(f.find_all(text)))
    return sorted(out.values(), key=lambda t: (-t.items, natural(t.label))), items
