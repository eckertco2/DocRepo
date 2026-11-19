"""Glossaries (release 5.171; the design workspace's ``docs/mods/glossaries-plan.md``, decisions 802 to 806).

A **glossary** is a table the owner imports whole from a sheet: an equipment list, an instrument list, a list of acronyms,
anything in rows. Each has a name and its own columns, every one kept as the sheet has it, and optionally a **tag column**,
whose cells are tags. They're kept apart from the **tag list** (the tagged labels DocRepo knows by name, ``tagged``), for
three reasons: a tag's key is unique across the one tag list, so two sheets holding the same number would collide; a row
that isn't shaped like a tag (a production line, an acronym) can't be a tagged label; and the tag list is read with every
``Model``, so wider rows there would slow the read every change makes.

They're kept in docs.db (decision 803, schema 31): ``glossaries`` (a name, its columns as a JSON list, the tag column, the
file it came from, when) and ``glossary_rows`` (a row's cells as a JSON list in the columns' order, and ``folded``, its
text folded for matching). Backups copy docs.db whole, ``dump`` copies every table, and ``rebuild`` leaves them be.
``Model`` never reads them: only this module does, when a glossary's view, page or lookup asks.

Nothing here touches Qt or the files; ``glossary_import`` reads a sheet, ``pages`` writes each glossary's page.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from docrepo import tagged
from docrepo.db import transaction

log = logging.getLogger(__name__)

#: The most rows the view draws of a glossary (decision 804), as the Tagged labels view draws at most 2,000.
SHOWN = 2000
#: The longest a glossary's name may be.
NAME_MAX = 80
#: What separates a row's cells in its folded text, so a word is never matched across two cells.
_SEP = " | "


class GlossaryError(Exception):
    """A change to a glossary that can't be made, with the reason in words."""


@dataclass(frozen=True)
class Glossary:
    """A glossary: its ID, name, columns (in the sheet's order), tag column (an index into them, or None), the file it came
    from (its name, as words), when it was imported (ISO), and how many rows it has."""

    id: int
    name: str
    columns: tuple[str, ...]
    tag_column: int | None
    source: str
    imported: str
    rows: int = 0

    @property
    def tag_name(self) -> str:
        """The tag column's name, or ""."""
        return self.columns[self.tag_column] if self.tag_column is not None and self.tag_column < len(self.columns) else ""


def fold(text: str) -> str:
    """Text folded for matching: case and accents aside, spacing made single."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def folded_row(cells: Sequence[str]) -> str:
    """A row's folded text: each cell folded, separated so no word spans two cells."""
    return _SEP.join(fold(c) for c in cells)


def tidy_name(name: str) -> str:
    return " ".join(str(name).split())


def name_problem(conn: sqlite3.Connection, name: str, glossary_id: int | None = None) -> str:
    """Why a glossary can't have this name, or "": it needs one, of at most NAME_MAX characters, that no other glossary has
    (case aside)."""
    name = tidy_name(name)
    if not name:
        return "A glossary needs a name."
    if len(name) > NAME_MAX:
        return f"A glossary's name is at most {NAME_MAX} characters."
    other = conn.execute("SELECT id FROM glossaries WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if other is not None and int(other["id"]) != glossary_id:
        return f"There's a glossary called {name} already. Give this one its own name."
    return ""


def _glossary(r: sqlite3.Row, rows: int = 0) -> Glossary:
    return Glossary(int(r["id"]), r["name"], tuple(json.loads(r["columns"])), r["tag_column"], r["source"], r["imported"], rows)


def all_glossaries(conn: sqlite3.Connection) -> list[Glossary]:
    """Every glossary, by name, with its count of rows."""
    # Rows are kept at places 0 to n - 1, so the last place says how many, read from the key alone (Contents.md asks often).
    counts = {int(r["id"]): int(r[1]) + 1 for r in conn.execute(
        "SELECT g.id, (SELECT max(pos) FROM glossary_rows WHERE glossary = g.id) FROM glossaries g") if r[1] is not None}
    return sorted((_glossary(r, counts.get(int(r["id"]), 0)) for r in conn.execute("SELECT * FROM glossaries")),
                  key=lambda g: g.name.casefold())


def summaries(conn: sqlite3.Connection | None) -> list[Glossary]:
    """Every glossary, for Contents.md's line (decision 806); none when docs.db can't say (no connection, or a database
    from before schema 31)."""
    if conn is None:
        return []
    try:
        return all_glossaries(conn)
    except sqlite3.Error:
        return []


def get(conn: sqlite3.Connection, glossary_id: int) -> Glossary | None:
    r = conn.execute("SELECT * FROM glossaries WHERE id = ?", (glossary_id,)).fetchone()
    if r is None:
        return None
    n = conn.execute("SELECT count(*) FROM glossary_rows WHERE glossary = ?", (glossary_id,)).fetchone()[0]
    return _glossary(r, int(n))


def words_of(find: str) -> list[str]:
    """What's typed in a glossary's box, as folded words: a row matches when every one is somewhere in it."""
    return [w for w in fold(find).split() if w]


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def rows_of(conn: sqlite3.Connection, glossary_id: int, find: str = "", limit: int | None = SHOWN) -> tuple[list[list[str]], int]:
    """A glossary's rows in the sheet's order, narrowed to those holding every word of ``find`` in any column (folded), at
    most ``limit``; and how many match in all."""
    words = words_of(find)
    where = "glossary = ?" + "".join(" AND folded LIKE ? ESCAPE '\\'" for _ in words)
    params: list[object] = [glossary_id, *(_like(w) for w in words)]
    total = int(conn.execute(f"SELECT count(*) FROM glossary_rows WHERE {where}", params).fetchone()[0])  # noqa: S608 - fixed text; values are parameters
    cap = f" LIMIT {int(limit)}" if limit is not None else ""
    rows = [json.loads(r[0]) for r in conn.execute(f"SELECT cells FROM glossary_rows WHERE {where} ORDER BY pos{cap}", params)]  # noqa: S608 - fixed text; values are parameters
    return rows, total


def _rows_params(glossary_id: int, rows: Iterable[Sequence[str]]) -> list[tuple[int, int, str, str]]:
    return [(glossary_id, pos, json.dumps(list(cells), ensure_ascii=False), folded_row(cells)) for pos, cells in enumerate(rows)]


def create(conn: sqlite3.Connection, name: str, columns: Sequence[str], tag_column: int | None, rows: Sequence[Sequence[str]],
           source: str, at: datetime) -> int:
    """A new glossary with its rows (decision 804's Import). Raises GlossaryError for a name that can't be used."""
    why = name_problem(conn, name)
    if why:
        raise GlossaryError(why)
    with transaction(conn):
        cur = conn.execute("INSERT INTO glossaries (name, columns, tag_column, source, imported) VALUES (?, ?, ?, ?, ?)",
                           (tidy_name(name), json.dumps(list(columns), ensure_ascii=False), tag_column, source,
                            at.isoformat(timespec="seconds")))
        gid = int(cur.lastrowid)
        conn.executemany("INSERT INTO glossary_rows (glossary, pos, cells, folded) VALUES (?, ?, ?, ?)", _rows_params(gid, rows))
    log.info("glossary %d imported: %d columns, %d rows", gid, len(columns), len(rows))
    return gid


def replace_rows(conn: sqlite3.Connection, glossary_id: int, columns: Sequence[str], tag_column: int | None,
                 rows: Sequence[Sequence[str]], source: str, at: datetime) -> None:
    """Import again (decision 804): the glossary's columns and rows become the new file's, its name kept."""
    with transaction(conn):
        if conn.execute("SELECT 1 FROM glossaries WHERE id = ?", (glossary_id,)).fetchone() is None:
            raise GlossaryError("That glossary isn't there any more.")
        conn.execute("UPDATE glossaries SET columns = ?, tag_column = ?, source = ?, imported = ? WHERE id = ?",
                     (json.dumps(list(columns), ensure_ascii=False), tag_column, source, at.isoformat(timespec="seconds"), glossary_id))
        conn.execute("DELETE FROM glossary_rows WHERE glossary = ?", (glossary_id,))
        conn.executemany("INSERT INTO glossary_rows (glossary, pos, cells, folded) VALUES (?, ?, ?, ?)", _rows_params(glossary_id, rows))
    log.info("glossary %d imported again: %d columns, %d rows", glossary_id, len(columns), len(rows))


def rename(conn: sqlite3.Connection, glossary_id: int, name: str) -> str:
    """Rename a glossary. Returns the name as kept; raises GlossaryError for one that can't be used."""
    why = name_problem(conn, name, glossary_id)
    if why:
        raise GlossaryError(why)
    with transaction(conn):
        conn.execute("UPDATE glossaries SET name = ? WHERE id = ?", (tidy_name(name), glossary_id))
    log.info("glossary %d renamed", glossary_id)
    return tidy_name(name)


def remove(conn: sqlite3.Connection, glossary_id: int) -> int:
    """Remove a glossary and its rows (decision 804, after the owner's confirm). Returns how many rows went. ``dump`` and
    the backups hold the old ones."""
    with transaction(conn):
        n = int(conn.execute("SELECT count(*) FROM glossary_rows WHERE glossary = ?", (glossary_id,)).fetchone()[0])
        conn.execute("DELETE FROM glossary_rows WHERE glossary = ?", (glossary_id,))
        conn.execute("DELETE FROM glossaries WHERE id = ?", (glossary_id,))
    log.info("glossary %d removed with its %d rows", glossary_id, n)
    return n


# ---- Import again's compare (decision 804) ----
def row_keys(rows: Sequence[Sequence[str]], tag_column: int | None) -> list[str]:
    """Each row's key for comparing two imports: its tag's key when there's a tag column, else its first cell folded; a
    second row with the same key is told apart by its place among them ("P204A#2")."""
    out, seen = [], {}
    for cells in rows:
        cell = cells[tag_column] if tag_column is not None and tag_column < len(cells) else (cells[0] if cells else "")
        base = (tagged.key_of(cell) or fold(cell)) if tag_column is not None else fold(cell)
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}#{seen[base]}")
    return out


@dataclass(frozen=True)
class Changes:
    """What Import again would do, by row: how many are added, gone and changed, and how many stay as they were."""

    added: int
    gone: int
    changed: int
    same: int

    def words(self) -> str:
        return f"{self.added:,} added · {self.gone:,} gone · {self.changed:,} changed · {self.same:,} as they were"


def compare(old_columns: Sequence[str], old_rows: Sequence[Sequence[str]], old_tag: int | None,
            new_columns: Sequence[str], new_rows: Sequence[Sequence[str]], new_tag: int | None) -> Changes:
    """Import again's counts: rows matched by their key (``row_keys``), a row changed when any of its cells under the same
    column name differs, or a column is added or gone."""
    def by_name(columns: Sequence[str], cells: Sequence[str]) -> dict[str, str]:
        return {c: (cells[i] if i < len(cells) else "") for i, c in enumerate(columns)}

    old = dict(zip(row_keys(old_rows, old_tag), old_rows))
    new = dict(zip(row_keys(new_rows, new_tag), new_rows))
    changed = sum(1 for k in new.keys() & old.keys() if by_name(new_columns, new[k]) != by_name(old_columns, old[k]))
    both = len(new.keys() & old.keys())
    return Changes(len(new.keys() - old.keys()), len(old.keys() - new.keys()), changed, both - changed)


# ---- a tagged label's rows (decision 805) ----
_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class TagRow:
    """A glossary's row whose tag is a tagged label's: the glossary, and the row's cells."""

    glossary: Glossary
    cells: tuple[str, ...]


def rows_for_tag(conn: sqlite3.Connection, key: str) -> list[TagRow]:
    """The rows of every glossary with a tag column whose tag has this key (``tagged.key_of``), by glossary name: a
    glossary row and a tagged label are the same thing then (decision 805). Narrowed in SQL by the key's longest run of
    digits, which no way of writing the tag splits, then matched exactly."""
    runs = sorted(_DIGITS.findall(key), key=len, reverse=True)
    out: list[TagRow] = []
    for g in all_glossaries(conn):
        if g.tag_column is None:
            continue
        sql, params = "SELECT cells FROM glossary_rows WHERE glossary = ?", [g.id]
        if runs:
            sql += " AND folded LIKE ? ESCAPE '\\'"
            params.append(_like(runs[0]))
        for r in conn.execute(sql + " ORDER BY pos", params):
            cells = json.loads(r[0])
            if g.tag_column < len(cells) and tagged.key_of(cells[g.tag_column]) == key:
                out.append(TagRow(g, tuple(cells)))
    return out


# ---- the lookup (release 5.172, decisions 807 to 809) ----
#: The most rows the lookup lists (decision 807).
LOOKUP_SHOWN = 50
#: What a typed word with a digit in it may leave out to match a tag: "p204a" finds P-204A, "fv 3001" finds FV-3001. SQL's
#: ``replace`` and ``squeeze`` leave out the same marks.
_SQUEEZED = ("-", ".", "/", "_", " ")
_SQUEEZE = re.compile(r"[-./_ ]")


def _squeeze_sql(column: str) -> str:
    for mark in _SQUEEZED:
        column = f"replace({column}, '{mark}', '')"
    return column


_SQUEEZE_SQL = _squeeze_sql("folded")


def squeeze(text: str) -> str:
    """Folded text without the marks a tag is written with or without (``_SQUEEZED``)."""
    return _SQUEEZE.sub("", text)


@dataclass(frozen=True)
class Found:
    """A row the lookup lists: its place in the sheet and its cells."""

    pos: int
    cells: tuple[str, ...]


def _match(glossary_id: int, words: Sequence[str]) -> tuple[str, list[object]]:
    """The WHERE for rows holding every word in some cell. A word with a digit also matches the row's text with its tag marks
    left out (``squeeze``), so it's found however the tag was typed."""
    esc = "ESCAPE '\\'"
    where, params = "glossary = ?", [glossary_id]
    for w in words:
        if _DIGITS.search(w):
            # As typed, or with the tag's marks left out of both: "p204" finds P-204A, and "p-204" does too.
            where += f" AND (folded LIKE ? {esc} OR {_SQUEEZE_SQL} LIKE ? {esc})"
            params += [_like(w), _like(squeeze(w))]
        else:
            where += f" AND folded LIKE ? {esc}"
            params.append(_like(w))
    return where, params


def lookup(conn: sqlite3.Connection, g: Glossary, typed: str, limit: int = LOOKUP_SHOWN) -> tuple[list[Found], int]:
    """The rows of ``g`` holding every word typed, in any column, case and accents aside (decision 807), at most ``limit``;
    and how many match in all. Nothing typed lists the first rows in the sheet's order.

    The order: the row whose tag (its first cell, with no tag column) is what's typed; then those whose tag starts with it;
    then those with a cell starting with the first word; then the rest; each in the sheet's order. Only each match's place
    and folded text are read to order them, and only the rows listed are read whole (decision 809's budget)."""
    words = words_of(typed)
    if not words:
        rows = conn.execute("SELECT pos, cells FROM glossary_rows WHERE glossary = ? ORDER BY pos LIMIT ?", (g.id, limit))
        found = [Found(int(r[0]), tuple(json.loads(r[1]))) for r in rows]
        total = int(conn.execute("SELECT count(*) FROM glossary_rows WHERE glossary = ?", (g.id,)).fetchone()[0])
        return found, total
    where, params = _match(g.id, words)
    hits = conn.execute(f"SELECT pos, folded FROM glossary_rows WHERE {where}", params).fetchall()  # noqa: S608 - fixed text; values are parameters
    whole = " ".join(words)
    key = squeeze(whole) if _DIGITS.search(whole) else ""
    tag = g.tag_column if g.tag_column is not None else 0

    def rank(folded: str) -> int:
        cells = folded.split(_SEP)
        first = cells[tag] if tag < len(cells) else ""
        if first == whole or (key and squeeze(first) == key):
            return 0
        if first.startswith(whole) or (key and squeeze(first).startswith(key)):
            return 1
        return 2 if any(c.startswith(words[0]) for c in cells) else 3

    places = [int(p) for p, _f in sorted(((int(r[0]), r[1]) for r in hits), key=lambda r: (rank(r[1]), r[0]))[:limit]]
    if not places:
        return [], 0
    marks = ",".join("?" * len(places))
    cells = {int(r[0]): tuple(json.loads(r[1])) for r in conn.execute(
        f"SELECT pos, cells FROM glossary_rows WHERE glossary = ? AND pos IN ({marks})", [g.id, *places])}  # noqa: S608 - fixed text; values are parameters
    return [Found(p, cells[p]) for p in places if p in cells], len(hits)


def tag_of(g: Glossary, cells: Sequence[str]) -> str:
    """What Enter copies (decision 807): the row's tag, or its first cell when the glossary has no tag column."""
    i = g.tag_column if g.tag_column is not None else 0
    return cells[i] if i < len(cells) else ""


def row_text(cells: Sequence[str]) -> str:
    """What Ctrl+C copies (decision 807): the row's cells, tab-separated, as a sheet takes them."""
    return "\t".join(" ".join(c.split()) for c in cells)


def shown_cells(g: Glossary, cells: Sequence[str]) -> list[tuple[str, bool]]:
    """A row's cells as the lookup draws them (decision 807): the tag column's first, marked True to be drawn bold, then
    the others in the sheet's order; empty cells left out."""
    cells = [" ".join(c.split()) for c in cells]
    tag = g.tag_column if g.tag_column is not None and g.tag_column < len(cells) else None
    out = [(cells[tag], True)] if tag is not None and cells[tag] else []
    return out + [(c, False) for i, c in enumerate(cells) if i != tag and c]


def remember(recent: Sequence[str], glossary_id: int, keep: int = 10) -> list[str]:
    """The glossaries last used, by ID as words (``Settings.glossary_recent``), ``glossary_id`` first."""
    key = str(glossary_id)
    return [key, *(k for k in recent if k != key)][:keep]


def by_recent(listed: Sequence[Glossary], recent: Sequence[str]) -> list[Glossary]:
    """The glossaries for the lookup's first list (decision 807): the last used first, then the rest by name."""
    place = {k: n for n, k in enumerate(recent)}
    return sorted(listed, key=lambda g: (place.get(str(g.id), len(place)), g.name.casefold()))


# ---- how often a row's tagged label is mentioned (decision 807) ----
def task_hits(model) -> dict[int, int]:
    """How many tasks' own fields mention each tagged label, in one pass over the tasks, as ``tagged.uses_of`` counts them.
    The lookup reads it once while its Model is the same, so typing never runs it again."""
    from collections import Counter

    f = model.tagged.finder()
    out: Counter[int] = Counter()
    for t in model.tasks.values():
        if not t.discarded:
            for label in {h.label for h in f.find(tagged.task_text(t, model))}:
                out[label] += 1
    return dict(out)


def places_of(model, label, hits: dict[int, int]) -> int:
    """How many places mention ``label`` (a ``tagged.Label``): its page's count (``tagged.uses_of``), for one row shown,
    with the tasks' part from ``task_hits``."""
    tg = model.tagged
    n, seen = 0, set()
    for m in tg.by_label.get(label.id, []):
        if tagged.live(model, m.kind, m.id) and tg.choices.get((m.kind, m.id), {}).get(label.key) != "removed":
            n += 1
            seen.add((m.kind, m.id))
    for (kind, item_id), own in tg.choices.items():
        if own.get(label.key) == "added" and (kind, item_id) not in seen and tagged.live(model, kind, item_id):
            n += 1
    return n + hits.get(label.id, 0)
