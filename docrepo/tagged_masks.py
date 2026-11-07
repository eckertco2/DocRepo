"""Tag patterns (release 5.80; the tagged labels plan, item 106, decisions 372 and 375): a **mask**, such as
``XX[X]-####``, names one of the plant's tagging conventions, and DocRepo turns it into a regular expression of its own.
The owner never writes a regular expression.

| In a mask | Means |
|---|---|
| ``X`` | a capital letter |
| ``#`` | a digit |
| ``*`` | a capital letter or a digit |
| ``[ ]`` | what's inside is optional: ``XX[X]-###[#]`` is 2 or 3 letters, then 3 or 4 digits |
| ``' '`` | what's inside is itself: ``'XV'-####`` starts with XV, since X alone is any letter |
| a hyphen, underscore or space | where a new label's spelling has that mark |
| any other letter, a digit, ``/`` or ``.`` | itself: ``V-###``, ``##-XX-###``, ``TK-##/#`` |

- **Marks are never required in the text.** ``XXX###`` finds FIC221, FIC-221 and FIC_221, and spells each as the mask
  does, FIC221. Wherever letters meet digits a hyphen, an en dash or an underscore may stand in the text, or not. A space
  stands only where the mask has one, or anywhere with the pattern's **Allow a space** ticked (off by default, since
  "API 610" and "for 100" are where false tags come from).
- **A mask is read in capitals:** ``x`` is ``X``, and ``v-###`` is ``V-###``. The text's letters must be capitals.
- **Safe:** the expression has no repetition, only optional parts, at most ``MAX_OPTIONAL`` of them, in a mask of at most
  ``MAX_LENGTH`` characters, so trying it at one place in a text takes a bounded number of steps. It's tried only where a
  run of letters and digits starts. No mask can hang a save on a big document (``tests/test_tagged_patterns.py`` times
  the worst one).
- **Never a tag** (decision 375): whole tags (ABC123) or starts with ``*`` (``API*``) that no pattern makes a tagged label,
  compared by their letters and digits.

Nothing here touches Qt or docs.db.
"""
from __future__ import annotations

import logging
import re
import string
from collections.abc import Iterable
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: The marks between a tag's parts: a hyphen, an en dash, an underscore and a space.
MARKS = "-–_ "
#: Other punctuation a mask may hold as itself.
JOINERS = "/."
#: The longest mask, in characters.
MAX_LENGTH = 32
#: The most optional parts ``[ ]`` a mask may have: each doubles the ways a place in the text can be tried.
MAX_OPTIONAL = 4
#: Made-up masks to start from, with what each means (Settings offers them; DocRepo ships no patterns).
EXAMPLES = (
    ("XXX###", "3 letters, then 3 digits"),
    ("X[X]-###[X]", "1 or 2 letters, 3 digits, maybe a letter, such as P-204A"),
    ("XX[X][X]-####", "2 to 4 letters, then 4 digits, such as FIC-2210"),
    ("'XV'-####", "starts with XV, since X alone is any letter"),
    ("##-XX-###", "a unit number first, such as 22-PT-101"),
)

_STRIP = re.compile(r"[-–_ ]")


class MaskError(ValueError):
    """A mask that can't be used, with the reason in words."""


def _key(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", text).upper()


# ---- a pattern, as Settings keeps it ----
@dataclass(frozen=True)
class Pattern:
    """A tag pattern: its name ("Instrument tag"), its mask, and whether a space may stand between any of its parts."""

    name: str
    mask: str
    space: bool = False

    def as_setting(self) -> dict:
        return {"name": self.name, "mask": self.mask, "space": self.space}


def patterns_of(value: object) -> list[Pattern]:
    """The patterns in settings.json's ``tagged_patterns``: each with a mask, named by its mask when it has no name.
    Anything else is left out, with a line in the log."""
    out = []
    for x in value if isinstance(value, list) else []:
        if not isinstance(x, dict) or not isinstance(x.get("mask"), str) or not x["mask"].strip():
            log.warning("Ignoring a tag pattern in settings.json with no mask")
            continue
        name = x.get("name") if isinstance(x.get("name"), str) else ""
        out.append(Pattern(name.strip() or x["mask"].strip(), x["mask"].strip(), bool(x.get("space", False))))
    return out


# ---- reading a mask ----
@dataclass(frozen=True)
class _El:
    kind: str  # "a" a letter, "d" a digit, "x" either, "p" other punctuation
    regex: str
    sample: str = ""  # what an example shows for a literal; "" for X, # and *


@dataclass(frozen=True)
class _Mark:
    ch: str


@dataclass(frozen=True)
class _Opt:
    items: tuple


_LETTER, _DIGIT, _EITHER = _El("a", "[A-Z]"), _El("d", "[0-9]"), _El("x", "[A-Z0-9]")
_ALLOWED = "X, #, *, [ ], quotes, letters, digits, a hyphen, an underscore, a space, a / or a dot"


def _literal(ch: str) -> _El:
    if len(ch) == 1 and ch in string.digits:
        return _El("d", ch, ch)
    if len(ch) == 1 and ch in string.ascii_uppercase:
        return _El("a", ch, ch)
    if ch in JOINERS:
        return _El("p", re.escape(ch), ch)
    raise MaskError(f"A mask can't hold “{ch}”. It can hold {_ALLOWED}.")


def parse(mask: str) -> list:
    """A mask's parts: letters, digits and either (``_El``), marks (``_Mark``) and optional parts (``_Opt``). Raises
    MaskError, saying what's wrong, for one that can't be used."""
    text = mask.strip()
    if not text:
        raise MaskError("Type a mask, such as XX-####.")
    if len(text) > MAX_LENGTH:
        raise MaskError(f"A mask can be at most {MAX_LENGTH} characters long.")
    out: list = []
    cur: list = out
    opt: list | None = None
    i = 0
    while i < len(text):
        c = text[i]
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise MaskError("A quote ' isn't closed.")
            if j == i + 1:
                raise MaskError("There's nothing between the quotes.")
            for ch in text[i + 1:j].upper():
                cur.append(_Mark("-" if ch == "–" else ch) if ch in MARKS else _literal(ch))
            i = j + 1
            continue
        if c == "[":
            if opt is not None:
                raise MaskError("Brackets can't go inside brackets.")
            opt = cur = []
        elif c == "]":
            if opt is None:
                raise MaskError("A ] has no [ before it.")
            if not opt:
                raise MaskError("The brackets are empty.")
            out.append(_Opt(tuple(opt)))
            opt, cur = None, out
        elif c in MARKS:
            cur.append(_Mark("-" if c == "–" else c))
        elif c.upper() == "X":
            cur.append(_LETTER)
        elif c == "#":
            cur.append(_DIGIT)
        elif c == "*":
            cur.append(_EITHER)
        else:
            cur.append(_literal(c.upper()))
        i += 1
    if opt is not None:
        raise MaskError("A [ isn't closed.")
    if sum(isinstance(x, _Opt) for x in out) > MAX_OPTIONAL:
        raise MaskError(f"A mask can have at most {MAX_OPTIONAL} optional parts in brackets.")
    if isinstance(out[0], _Mark) or isinstance(out[-1], _Mark):
        raise MaskError("A mask can't start or end with a hyphen, an underscore or a space.")
    if any(isinstance(a, _Mark) and isinstance(b, _Mark) for a, b in zip(out, out[1:])):
        raise MaskError("Two marks in a row: one hyphen, underscore or space between parts is enough.")
    kinds = {x.kind for x in out if isinstance(x, _El)}
    if "d" not in kinds:
        raise MaskError("A mask needs a digit (#) outside brackets, or it would match ordinary words.")
    if "a" not in kinds:
        raise MaskError("A mask needs a letter (X) outside brackets, or it would match ordinary numbers.")
    return out


# ---- the mask as a regular expression ----
@dataclass(frozen=True)
class Compiled:
    """A mask's regular expression, with a group for each part between its own marks, and those marks in order."""

    regex: re.Pattern[str]
    marks: tuple[str, ...]


def compile_mask(mask: str, space: bool = False) -> Compiled:
    """The mask as a regular expression of DocRepo's own: no repetition but optional parts, so nothing can hang. Each
    part between the mask's own marks is a group, so a new label is spelled with the mask's marks (``spell``). Wherever
    letters meet digits a mark may stand in the text or not (decision 372)."""
    items = parse(mask)
    mk = "[-–_ ]" if space else "[-–_]"
    segs: list[list[str]] = [[]]
    joints: list[str] = []
    marks: list[str] = []
    prev: set[str] = set()

    def put(arr: list[str], e: _El) -> None:
        nonlocal prev
        if e.kind in "ad" and any(k in "ad" and k != e.kind for k in prev):
            arr.append(mk + "?")  # a letter meets a digit: a mark may stand between them
        arr.append(e.regex)
        prev = {e.kind}

    for it in items:
        if isinstance(it, _Mark):
            segs.append([])
            marks.append(it.ch)
            joints.append("[-–_ ]?" if it.ch == " " else mk + "?")  # a space in the mask may stand in the text
            prev = set()
        elif isinstance(it, _El):
            put(segs[-1], it)
        else:
            before, inner = prev, []
            for x in it.items:
                if isinstance(x, _Mark):
                    inner.append(mk + "?")
                    prev = set()
                else:
                    put(inner, x)
            segs[-1].append(f"(?:{''.join(inner)})?")
            prev = before | prev  # the part may be missing, so what follows may meet either
    body = f"({''.join(segs[0])})" + "".join(j + f"({''.join(s)})" for j, s in zip(joints, segs[1:]))
    return Compiled(re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"), tuple(marks))


def spell(m: re.Match[str], c: Compiled) -> str:
    """A match spelled as its mask is: each part's letters and digits, joined by the mask's own marks."""
    out = ""
    for k, seg in enumerate(m.groups()):
        s = _STRIP.sub("", seg or "")
        if s:
            out += (c.marks[k - 1] if out and k else "") + s
    return out


def examples(mask: str) -> str:
    """A made-up tag the mask allows, the shortest and the longest, so its meaning shows as it's typed: "FT-2041 to
    FTIC-2041". Raises MaskError for a mask that can't be used."""
    items = parse(mask)

    def make(full: bool) -> str:
        letters, digits, out = iter("FTIC" * 8), iter("2041" * 8), []

        def one(x) -> None:
            if isinstance(x, _Mark):
                out.append(x.ch)
            elif x.sample:
                out.append(x.sample)
            else:
                out.append(next(letters) if x.kind == "a" else next(digits) if x.kind == "d" else "A")
        for x in items:
            if isinstance(x, _Opt):
                if full:
                    for y in x.items:
                        one(y)
            else:
                one(x)
        return "".join(out).strip()
    a, b = make(False), make(True)
    return a if a == b else f"{a} to {b}"


# ---- Never a tag (decision 375) ----
def never_problem(entry: str) -> str | None:
    """Why an entry can't go on Never a tag, or None."""
    e = entry.strip()
    if not _key(e.rstrip("*")):
        return f"“{e}” needs a letter or a digit" + (" before the *." if e.endswith("*") else ".")
    if "*" in e.rstrip("*") or e.count("*") > 1:
        return f"“{e}”: a * goes only at the end, for a start such as API*."
    return None


def never_of(entries: Iterable[str]) -> list[str]:
    """Never a tag as it's kept: each entry trimmed, in capitals, once, in the order given. Entries that can't be used are
    left out (Settings says why before saving)."""
    out: list[str] = []
    for e in entries:
        e = str(e).strip().upper()
        if e and never_problem(e) is None and e not in out:
            out.append(e)
    return out


class Never:
    """Never a tag, for matching: whole tags, and starts, by their letters and digits."""

    def __init__(self, entries: Iterable[str] = ()) -> None:
        entries = never_of(entries)
        self.whole = {_key(e) for e in entries if not e.endswith("*")}
        self.starts = tuple(_key(e[:-1]) for e in entries if e.endswith("*"))

    def __contains__(self, label: str) -> bool:
        k = _key(label)
        return k in self.whole or any(k.startswith(s) for s in self.starts)

    def __bool__(self) -> bool:
        return bool(self.whole or self.starts)
