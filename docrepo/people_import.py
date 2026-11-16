"""Import people (release 5.151, the design workspace's ``docs/mods/people-import-plan.md``, decisions 658 to 662): a list of
people from a ``.csv`` or an ``.xlsx`` file, with a preview before anything changes.

- **Columns** (decision 658): the first row names them, found by name, case and spaces aside: **Name** (needed), **Email**,
  **Role**, **Group** and **Aliases** (split by semicolons). Other columns are left alone, and the window names them. An
  ``.xlsx`` with several sheets uses the first, or the one picked.
- **The preview** (decision 659): each row of the file is a line, **New**, **Update** (with what changes), **Same** or a
  **Problem** (no name, an email that isn't one, two rows for one person, a name or an email that matches two people),
  each New and Update ticked. Import adds and updates the ticked ones in one transaction.
- **Matching** (decision 660): by email first, case aside; else by name or alias, case and spaces aside. A row matching
  nobody is New. A retired person is matched too, and stays retired.
- **An update fills in** (decision 661): an empty email, role or group is filled in, a different one is a change, shown
  in the line, and both happen only when the line is ticked; aliases are added, never taken away. Nobody is removed or
  retired, no field is cleared, and a person's name isn't changed.
- **The file is data** (decision 662): cells are read as text only, an ``.xlsx`` with openpyxl in read-only mode with
  cached values (``excel_import.read_sheet``) and a ``.csv`` with the standard library, as UTF-8 or else Windows-1252.
  At most MAX_ROWS rows under the header and MAX_CELL characters a cell are read; nothing in a cell runs, and a cell
  that holds a formula's text (it starts with ``=``) is a Problem, never a value. The file isn't kept, and the log has
  counts only, never a name or an address.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docrepo import people
from docrepo.db import transaction
from docrepo.excel_import import WorkbookError, read_sheet, sheet_names, text_of
from docrepo.model import Model, Person

log = logging.getLogger(__name__)

MAX_ROWS = 5000
MAX_CELL = 200
#: A cell is cut to this many characters as it's read, so a huge one costs nothing; past MAX_CELL it's a Problem anyway.
_READ_CUT = MAX_CELL * 5
#: The columns read, by their header (case and spaces aside), in the order the window names them.
COLUMNS = (("name", "Name"), ("email", "Email"), ("role", "Role"), ("group", "Group"), ("aliases", "Aliases"))
COLUMN_NAMES = dict(COLUMNS)
SUFFIXES = (".csv", ".xlsx")
#: The file picker's filter.
FILE_FILTER = "People lists (*.csv *.xlsx)"
NEW, UPDATE, SAME, PROBLEM = "new", "update", "same", "problem"
KIND_WORDS = {NEW: "New", UPDATE: "Update", SAME: "Same", PROBLEM: "Problem"}
#: The words a change's field has in a line.
FIELD_WORDS = {"email": "Email", "role": "Role", "group": "Group"}
ADDED_NOTE = "Added on {day} by Import people. Hours aren't set yet."


# ---- reading the file ----
@dataclass
class Table:
    """The file's rows as text: the header first, then at most MAX_ROWS rows. ``cut``: the file had more."""

    rows: list[list[str]]
    cut: bool = False


def _check_suffix(path: Path) -> None:
    if path.suffix.lower() not in SUFFIXES:
        raise WorkbookError(f"{path.name} isn't a .csv or an .xlsx file. Save the list as one of those, and import that.")


def sheets(path: Path) -> list[str]:
    """An ``.xlsx``'s sheets, in order; a ``.csv`` has none to pick."""
    _check_suffix(path)
    return [] if path.suffix.lower() == ".csv" else sheet_names(path)


def read_file(path: Path, sheet: str | None = None) -> Table:
    """The file's rows as text (``sheet``, or the first, for an ``.xlsx``). Only read, never changed."""
    _check_suffix(path)
    if path.suffix.lower() == ".csv":
        return _read_csv(path)
    if not sheet:
        names = sheet_names(path)
        sheet = names[0] if names else ""
    rows = [[text_of(v)[:_READ_CUT] for v in row] for row in read_sheet(path, sheet, MAX_ROWS + 2)]
    return Table(rows[:MAX_ROWS + 1], len(rows) > MAX_ROWS + 1)


def _read_csv(path: Path) -> Table:
    """A CSV as UTF-8 (with or without its byte order mark), or else Windows-1252, which reads any byte."""
    try:
        return _csv_rows(path, "utf-8-sig", "strict")
    except UnicodeDecodeError:
        return _csv_rows(path, "cp1252", "replace")


def _csv_rows(path: Path, encoding: str, errors: str) -> Table:
    try:
        with open(path, encoding=encoding, errors=errors, newline="") as f:
            first = f.readline()
            # The separator is the header's: a comma, or a semicolon or a tab where those are more (Excel's own CSVs in
            # some countries use a semicolon).
            separator = max((",", ";", "\t"), key=first.count)
            f.seek(0)
            rows: list[list[str]] = []
            cut = False
            for row in csv.reader(f, delimiter=separator):
                if len(rows) > MAX_ROWS:  # the header and MAX_ROWS rows are in: is there more than blank rows after them?
                    if any(c.strip() for c in row):
                        cut = True
                        break
                    continue
                rows.append([c[:_READ_CUT] for c in row])
    except OSError as e:
        raise WorkbookError(f"{path.name} can't be opened. If it's open in another program, close it, or save a copy and import that.") from e
    except csv.Error as e:
        raise WorkbookError(f"{path.name} can't be read as a CSV file ({e}).") from e
    return Table(rows, cut)


# ---- the columns ----
def _key(text: str) -> str:
    """Text with case and spaces aside, for matching a header, a name or an alias."""
    return "".join(text.split()).casefold()


def _same(a: str, b: str) -> bool:
    """Whether two values are one, case and runs of spaces aside."""
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def find_columns(header: list[str]) -> tuple[dict[str, int], list[str]]:
    """The columns read, as {"name": its index, …}, and the headers of those left alone. A column named twice is read once,
    the first time; the second is left alone."""
    wanted = {_key(label): key for key, label in COLUMNS}
    found: dict[str, int] = {}
    left: list[str] = []
    for i, text in enumerate(header):
        key = wanted.get(_key(text))
        if key and key not in found:
            found[key] = i
        elif text.strip():
            left.append(" ".join(text.split()) + (" (a second one)" if key else ""))
    return found, left


# ---- the preview ----
@dataclass
class Change:
    """A field an update changes: filled in when it was empty (``before`` is ""), else from ``before`` to ``after``."""

    field: str
    before: str
    after: str

    @property
    def filled(self) -> bool:
        return not self.before

    def words(self) -> str:
        """ "Role: Planner → Lead planner", or "Email filled in: lena.fischer@example.com"."""
        name = FIELD_WORDS[self.field]
        return f"{name} filled in: {self.after}" if self.filled else f"{name}: {self.before} → {self.after}"


@dataclass
class Line:
    """One row of the file in the preview."""

    row: int  # its number in the file, the header being row 1
    name: str
    email: str = ""
    role: str = ""
    group: str = ""
    aliases: list[str] = field(default_factory=list)
    kind: str = NEW
    problem: str = ""
    person: str | None = None  # the matched person's ID
    person_name: str = ""  # their name in DocRepo
    by: str = ""  # "email" or "name": how they were matched
    retired: bool = False
    changes: list[Change] = field(default_factory=list)
    added_aliases: list[str] = field(default_factory=list)
    ticked: bool = False

    @property
    def can_tick(self) -> bool:
        return self.kind in (NEW, UPDATE)

    def kind_word(self) -> str:
        return KIND_WORDS[self.kind]

    def words(self) -> str:
        """What the line does, after its name: what a new person gets, what an update changes, or the problem."""
        if self.kind == PROBLEM:
            return self.problem
        bits: list[str] = []
        if self.person and not _same(self.person_name, self.name):
            bits.append(f"DocRepo's {self.person_name}, found by {self.by}")
        if self.kind == NEW:
            bits += [x for x in (self.email, self.role, self.group) if x]
            if self.aliases:
                bits.append("aliases " + ", ".join(self.aliases))
        elif self.kind == UPDATE:
            bits += [c.words() for c in self.changes]
            if self.added_aliases:
                bits.append("Aliases added: " + ", ".join(self.added_aliases))
        else:
            bits.append("Nothing to change")
        if self.retired:
            bits.append("stays retired")
        return " · ".join(bits)


@dataclass
class Preview:
    """What Import would do, line by line. Nothing is written until ``run_import``."""

    lines: list[Line]
    columns: dict[str, int]
    left_alone: list[str]
    cut: bool = False

    def count(self, kind: str) -> int:
        return sum(1 for x in self.lines if x.kind == kind)

    @property
    def ticked(self) -> list[Line]:
        return [x for x in self.lines if x.ticked and x.can_tick]

    def columns_words(self) -> str:
        """ "Read: Name, Email, Role. Left alone: Phone, Notes." """
        read = [label for key, label in COLUMNS if key in self.columns]
        return f"Read: {', '.join(read)}." + (f" Left alone: {', '.join(self.left_alone)}." if self.left_alone else "")

    def summary(self) -> str:
        """ "9 rows: 4 new, 2 updates, 1 the same, 2 problems." """
        n = len(self.lines)
        bits = [f"{self.count(NEW)} new", _plural(self.count(UPDATE), "update"), f"{self.count(SAME)} the same",
                _plural(self.count(PROBLEM), "problem")]
        return f"{_plural(n, 'row')}: " + ", ".join(bits) + "."


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class _Index:
    """The people list by email and by name or alias, each key to the people who have it; retired people too."""

    def __init__(self, model: Model) -> None:
        self.people = model.people
        self.by_email: dict[str, list[str]] = {}
        self.by_name: dict[str, list[str]] = {}
        self.groups: dict[str, str] = {}
        for p in model.people.values():
            if p.email:
                self.by_email.setdefault(p.email.casefold(), []).append(p.id)
            for n in (p.name, *p.aliases):
                ids = self.by_name.setdefault(_key(n), [])
                if p.id not in ids:
                    ids.append(p.id)
            if p.group:
                self.groups.setdefault(" ".join(p.group.split()).casefold(), p.group)

    def group(self, text: str) -> str:
        """A group as DocRepo already spells it, when it has it (case aside), so one group isn't made two."""
        return self.groups.get(" ".join(text.split()).casefold(), text) if text else ""


def _aliases(text: str, name: str) -> list[str]:
    """An Aliases cell's aliases, split by semicolons, each once, without the name itself."""
    out: list[str] = []
    seen = {_key(name)}
    for alias in text.split(";"):
        alias = " ".join(alias.split())
        if alias and _key(alias) not in seen:
            seen.add(_key(alias))
            out.append(alias)
    return out


def _read_line(number: int, cells: list[str], columns: dict[str, int], index: _Index) -> Line:
    """A row as a line: its values checked, then matched (decision 660) and compared (decision 661)."""
    raw = {key: (cells[i] if i < len(cells) else "") for key, i in columns.items()}
    values = {key: " ".join(text.split()) for key, text in raw.items()}
    line = Line(number, values.get("name", ""), values.get("email", ""), values.get("role", ""), index.group(values.get("group", "")))

    def problem(words: str) -> Line:
        line.kind, line.problem, line.ticked = PROBLEM, words, False
        return line

    for key, label in COLUMNS:
        text = values.get(key, "")
        if text.startswith("="):
            return problem(f"Its {label} is a formula (it starts with =), and a formula's text is never read.")
        if len(text) > MAX_CELL:
            return problem(f"Its {label} is longer than {MAX_CELL} characters.")
    if not line.name:
        return problem("It has no name.")
    if line.email and not people.is_email(line.email):
        return problem(f"“{line.email}” isn't an email address.")
    line.aliases = _aliases(values.get("aliases", ""), line.name)
    ids = index.by_email.get(line.email.casefold(), []) if line.email else []
    line.by = "email"
    if not ids:
        ids, line.by = index.by_name.get(_key(line.name), []), "name"
    if len(ids) > 1:
        who = ", ".join(index.people[i].name for i in ids[:-1]) + " and " + index.people[ids[-1]].name
        return problem(f"Its {line.by} matches {len(ids)} people: {who}.")
    if not ids:
        line.by, line.kind, line.ticked = "", NEW, True
        return line
    _compare(line, index.people[ids[0]])
    return line


def _compare(line: Line, p: Person) -> None:
    """A matched row against the person: what it fills in, what it changes, and the aliases it adds (decision 661)."""
    line.person, line.person_name, line.retired = p.id, p.name, p.status == "retired"
    for name, ours, theirs in (("email", p.email or "", line.email), ("role", p.role or "", line.role), ("group", p.group or "", line.group)):
        if not theirs or (ours and (ours.casefold() == theirs.casefold() if name == "email" else _same(ours, theirs))):
            continue  # nothing in the file, or what DocRepo has: never cleared
        line.changes.append(Change(name, ours, theirs))
    known = {_key(n) for n in (p.name, *p.aliases)}
    line.added_aliases = [a for a in line.aliases if _key(a) not in known]
    line.kind = UPDATE if (line.changes or line.added_aliases) else SAME
    line.ticked = line.kind == UPDATE


def _claims(line: Line) -> list[str]:
    """What makes two rows one person: the person matched, the email, and a new person's name."""
    keys = [f"person:{line.person}"] if line.person else [f"name:{_key(line.name)}"]
    return keys + ([f"email:{line.email.casefold()}"] if line.email else [])


def preview(model: Model, table: Table) -> Preview:
    """What Import would do with each row of ``table`` (decision 659). Nothing is written."""
    header = table.rows[0] if table.rows else []
    if not any(c.strip() for c in header):
        raise WorkbookError("The file's first row is empty. It should name the columns: Name, and Email, Role, Group and Aliases when it has them.")
    columns, left = find_columns(header)
    if "name" not in columns:
        raise WorkbookError("The first row has no Name column. It should name the columns: Name, and Email, Role, Group and Aliases when "
                            "it has them.")
    index = _Index(model)
    lines: list[Line] = []
    claimed: dict[str, int] = {}
    for offset, cells in enumerate(table.rows[1:]):
        if not any(c.strip() for c in cells):
            continue  # a blank row
        line = _read_line(offset + 2, cells, columns, index)
        if line.kind != PROBLEM:
            first = next((claimed[k] for k in _claims(line) if k in claimed), None)
            if first is not None:
                line.kind, line.problem, line.ticked = PROBLEM, f"Row {first} is for the same person.", False
            else:
                for k in _claims(line):
                    claimed[k] = line.row
        lines.append(line)
    return Preview(lines, columns, left, table.cut)


# ---- importing ----
def run_import(conn: sqlite3.Connection, found: Preview, at: datetime) -> str:
    """Add and update the ticked lines' people in one transaction (decisions 659 and 661). Returns the status line's
    words: "12 people added, 3 updated, 2 left out." The log has the counts only."""
    chosen = found.ticked
    added = updated = 0
    note = ADDED_NOTE.format(day=at.date().isoformat())
    with transaction(conn):
        for line in chosen:
            if line.kind == NEW:
                people.add_person(conn, line.name, aliases=line.aliases, email=line.email or None, group=line.group or None,
                                  role=line.role or None, added_note=note)
                added += 1
                continue
            details: dict[str, object] = {c.field: c.after for c in line.changes}
            if line.added_aliases:
                current = [str(r[0]) for r in conn.execute("SELECT alias FROM person_aliases WHERE person = ? ORDER BY pos", (line.person,))]
                known = {_key(a) for a in current}
                details["aliases"] = current + [a for a in line.added_aliases if _key(a) not in known]
            people.update_person(conn, str(line.person), **details)  # type: ignore[arg-type]
            updated += 1
    same = found.count(SAME)
    left = len(found.lines) - added - updated - same
    log.info("people import: %d added, %d updated, %d the same, %d left out", added, updated, same, left)
    return outcome_words(added, updated, same, left)


def outcome_words(added: int, updated: int, same: int, left: int) -> str:
    """ "12 people added, 3 updated, 2 left out.", with "4 already the same" when there are some."""
    words = f"{added} {'person' if added == 1 else 'people'} added, {updated} updated"
    if same:
        words += f", {same} already the same"
    if left:
        words += f", {left} left out"
    return words + "."
