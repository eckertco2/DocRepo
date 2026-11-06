"""The tagged labels' glossary from Excel or CSV, and back out as CSV (release 5.79; the tagged labels plan, item 103,
decision 371).

- **Reading:** an ``.xlsx`` is opened read-only, as the project list's import does (``excel_import.read_sheet``), and a
  ``.csv`` is read as UTF-8 (or Windows' own encoding when it isn't), with its separator worked out (a comma, a
  semicolon or a tab). Neither is ever changed. Up to MAX_ROWS rows.
- **Columns:** each column fills the tagged label, its description or its aliases, or is left out, guessed from its
  header ("Tag No.", "Service", "Other names") and changed in the form.
- **The preview** says what Import would do, and nothing is written until then. Importing again merges: new labels are
  added, aliases added to the ones there, and a description that differs replaces DocRepo's unless DocRepo's is kept.
  Nothing is removed. Two rows that are one tag written two ways (V-110 and V110) become one label, the other spelling
  its alias. A row that's another label's alias becomes a label of its own, and that label loses the alias: the list
  wins. An alias that's only digits, or that two labels share, is refused, and the preview names it.
- **Export** writes the glossary as a CSV with the same three columns in ``Exports`` in the data root, as tree files'
  Export does, since DocRepo writes nowhere else.

The log records counts, never the file's contents.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docrepo import tagged
from docrepo.db import transaction
from docrepo.excel_import import WorkbookError, guess_header_row, read_sheet, sheet_names, text_of
from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

MAX_ROWS = 100_000
EXPORTS = "Exports"
EXPORT_NAME = "Tagged labels"
#: What a column can fill, in the order the form lists them.
FIELDS = (("label", "Tagged label"), ("description", "Description"), ("aliases", "Aliases"), ("skip", "Leave out"))
FIELD_NAMES = dict(FIELDS)
#: Header words that suggest a field, tried in order. Aliases and descriptions first, so "Tagged label description" isn't
#: taken for the label.
_GUESSES = (
    ("aliases", ("alias", "aliases", "other name", "other names", "also known as", "aka", "tagged label aliases")),
    ("description", ("description", "desc", "service", "duty", "tagged label description")),
    ("label", ("tag", "tag no", "tag number", "tagged label", "label", "equipment", "equipment number", "instrument", "item")),
)


def is_csv(path: Path) -> bool:
    return path.suffix.lower() in (".csv", ".txt")


def workbook_sheets(path: Path) -> list[str]:
    """An .xlsx's sheets; a CSV has none to pick."""
    return [] if is_csv(path) else sheet_names(path)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_rows(path: Path, sheet: str | None = None) -> list[list[str]]:
    """The file's rows as text, without trailing empty cells, at most MAX_ROWS (and a few for the header)."""
    if is_csv(path):
        try:
            text = _decode(path.read_bytes())
        except OSError as e:
            raise WorkbookError(f"{path.name} can't be read ({type(e).__name__}).") from e
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = []
        for row in csv.reader(io.StringIO(text), dialect):
            rows.append([c.strip() for c in row])
            if len(rows) >= MAX_ROWS + 30:
                break
    else:
        if not sheet:
            sheets = sheet_names(path)
            sheet = sheets[0] if sheets else ""
        rows = [[text_of(v) for v in row] for row in read_sheet(path, sheet, MAX_ROWS + 30)]
    for row in rows:
        while row and not row[-1]:
            row.pop()
    while rows and not rows[-1]:
        rows.pop()
    return rows


def guess_header(rows: list[list[str]]) -> int:
    """The header row (0 is the first)."""
    return guess_header_row([[c or None for c in r] for r in rows])


def guess_field(header: str) -> str:
    words = " " + " ".join(re.sub(r"[^a-z0-9]+", " ", header.lower()).split()) + " "
    for f, names in _GUESSES:
        if any(f" {n} " in words for n in names):
            return f
    return "skip"


def propose(rows: list[list[str]], header_row: int) -> list[str]:
    """Each column's field, guessed from its header. One column fills the label: the first guessed, or else the first."""
    header = rows[header_row] if header_row < len(rows) else []
    fields = [guess_field(h) for h in header]
    for f in ("label", "description"):
        firsts = [i for i, x in enumerate(fields) if x == f]
        for i in firsts[1:]:
            fields[i] = "skip"
    if "label" not in fields and fields:
        fields[0] = "label"
    return fields


@dataclass
class Plan:
    header_row: int
    fields: list[str]
    keep_descriptions: bool = False  # keep DocRepo's description where the file's differs


@dataclass
class Draft:
    """One label as Import would leave it."""

    label: str
    description: str
    aliases: list[str]
    id: int | None = None  # None: a new label
    changed: bool = False


@dataclass
class Preview:
    added: list[str] = field(default_factory=list)
    changed: list[tuple[str, str, str]] = field(default_factory=list)  # (label, DocRepo's description, the file's)
    aliases_added: list[tuple[str, str]] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    unchanged: int = 0
    empty: int = 0
    cut: bool = False  # more rows than MAX_ROWS
    kept_descriptions: bool = False  # the plan kept DocRepo's descriptions
    drafts: dict[str, Draft] = field(default_factory=dict)
    error: str = ""

    def summary(self) -> str:
        s = lambda n, one, many: f"{n} {one if n == 1 else many}"  # noqa: E731
        return (f"{s(len(self.added), 'to add', 'to add')} · {s(len(self.changed), 'description differs', 'descriptions differ')} · "
                f"{s(len(self.aliases_added), 'alias added', 'aliases added')} · {self.unchanged} unchanged · {len(self.merged)} merged · "
                f"{len(self.refused)} refused" + (f" · {s(self.empty, 'empty row skipped', 'empty rows skipped')}" if self.empty else ""))


def _alias_key(a: str) -> str:
    return tagged.key_of(a) if tagged.tag_like(a) else " ".join(a.lower().split())


def preview(conn: sqlite3.Connection, rows: list[list[str]], plan: Plan) -> Preview:
    """What Import would do with these rows, against the glossary as it is. Nothing is written."""
    out = Preview(kept_descriptions=plan.keep_descriptions)
    if "label" not in plan.fields:
        out.error = "Pick the column that holds the tagged label."
        return out
    col = {f: plan.fields.index(f) for f in ("label", "description", "aliases") if f in plan.fields}
    cell = lambda r, f: (r[col[f]] if f in col and col[f] < len(r) else "").strip()  # noqa: E731
    body = rows[plan.header_row + 1:]
    if len(body) > MAX_ROWS:
        body, out.cut = body[:MAX_ROWS], True
    drafts = {lb.key: Draft(lb.label, lb.description, list(lb.aliases), lb.id) for lb in tagged.read_labels(conn)}
    # Who has each alias, from the glossary and the file, so one two labels share is refused.
    owners: dict[str, set[str]] = {}
    for k, d in drafts.items():
        for a in d.aliases:
            owners.setdefault(_alias_key(a), set()).add(k)
    spelling: dict[str, str] = {k: d.label for k, d in drafts.items()}
    for r in body:
        label = cell(r, "label")
        if label and tagged.key_of(label):
            spelling.setdefault(tagged.key_of(label), label)
            for a in tagged.split_aliases(cell(r, "aliases")):
                owners.setdefault(_alias_key(a), set()).add(tagged.key_of(label))
    told: set[str] = set()
    first: dict[str, str] = {}  # key -> the spelling this file used first
    for r in body:
        label = cell(r, "label")
        k = tagged.key_of(label)
        if not k:
            out.empty += 1
            continue
        if k in first and first[k] != label:
            d = drafts[k]
            if label not in d.aliases:
                d.aliases.append(label)
                d.changed = True
            out.merged.append(f"{label} is {first[k]} written another way: kept as its alias")
            continue
        first.setdefault(k, label)
        desc, aliases = cell(r, "description"), tagged.split_aliases(cell(r, "aliases"))
        d = drafts.get(k)
        fresh = d is None
        if fresh:
            d = drafts[k] = Draft(label, desc, [], changed=True)
            out.added.append(label)
            # The list wins over an alias given in DocRepo: a row that's another label's alias becomes a label of its own.
            for ok in owners.get(k, set()) - {k}:
                other = drafts.get(ok)
                if other and any(tagged.tag_like(a) and tagged.key_of(a) == k for a in other.aliases):
                    other.aliases = [a for a in other.aliases if not (tagged.tag_like(a) and tagged.key_of(a) == k)]
                    other.changed = True
                    out.merged.append(f"{label} was an alias of {other.label}: it's a label of its own now, and {other.label} loses the alias")
        elif desc and desc != d.description:
            out.changed.append((d.label, d.description, desc))
            if not plan.keep_descriptions:
                d.description, d.changed = desc, True
        had = len(out.aliases_added)
        for a in aliases:
            ak = _alias_key(a)
            if tagged.only_digits(a):
                out.refused.append(f"{label}'s alias \"{a}\": only digits, so it would match every such number")
            elif tagged.tag_like(a) and tagged.key_of(a) == k:
                continue  # its own label written another way
            elif len(owners.get(ak, ())) > 1:
                if ak not in told:
                    told.add(ak)
                    out.refused.append(f"The alias \"{a}\": {' and '.join(sorted(spelling.get(x, x) for x in owners[ak]))} both have it")
            elif tagged.tag_like(a) and tagged.key_of(a) in spelling and tagged.key_of(a) != k:
                out.refused.append(f"{label}'s alias \"{a}\": it's the label {spelling[tagged.key_of(a)]}")
            elif not any(_alias_key(x) == ak for x in d.aliases):
                d.aliases.append(a)
                d.changed = True
                if not fresh:
                    out.aliases_added.append((d.label, a))
        if not fresh and not d.changed and len(out.aliases_added) == had and not (out.changed and out.changed[-1][0] == d.label):
            out.unchanged += 1
    out.drafts = drafts
    return out


def run_import(conn: sqlite3.Connection, found: Preview, source: str, at: datetime) -> str:
    """Make the glossary what the preview showed, then match everything again. Returns what to say."""
    stamp = at.isoformat(timespec="seconds")
    with transaction(conn):
        for k, d in found.drafts.items():
            if not d.changed:
                continue
            if d.id is None:
                cur = conn.execute("INSERT INTO tagged_labels (label, key, description, came, source, added) VALUES (?, ?, ?, 'import', ?, ?)",
                                   (d.label, k, d.description, source, stamp))
                d.id = int(cur.lastrowid)
            else:
                conn.execute("UPDATE tagged_labels SET description = ? WHERE id = ?", (d.description, d.id))
                conn.execute("DELETE FROM tagged_aliases WHERE label = ?", (d.id,))
            conn.executemany("INSERT INTO tagged_aliases (label, alias, pos) VALUES (?, ?, ?)", [(d.id, a, i) for i, a in enumerate(d.aliases)])
        tagged.glossary_changed(conn)
    items = tagged.rematch(conn)
    log.info("tagged labels imported: %d added, %d descriptions differ, %d aliases added, %d merged, %d refused; %d items mention one",
             len(found.added), len(found.changed), len(found.aliases_added), len(found.merged), len(found.refused), items)
    kept = " (DocRepo's kept)" if found.changed and found.kept_descriptions else ""
    return (f"Imported {source}: {len(found.added)} added, {len(found.changed)} description{'s' if len(found.changed) != 1 else ''} differed{kept}, "
            f"{len(found.aliases_added)} alias{'es' if len(found.aliases_added) != 1 else ''} added. {items} item{'s' if items != 1 else ''} mention a tagged label.")


# ---- export ----
def export_csv(conn: sqlite3.Connection) -> str:
    """The glossary as CSV: Tagged label, Tagged label description, Tagged label aliases (separated by "; ")."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Tagged label", "Tagged label description", "Tagged label aliases"])
    for lb in sorted(tagged.read_labels(conn), key=lambda x: tagged.natural(x.label)):
        if lb.status == "glossary":
            w.writerow([lb.label, lb.description, "; ".join(lb.aliases)])
    return buf.getvalue()


def save_export(fs: SafeFS, data_root: Path, text: str, at: datetime) -> Path:
    """Write the export to ``Exports`` in the data root, under its date and name, never over an earlier one. With a BOM,
    so Excel reads its accents."""
    base, n = f"{at:%Y-%m-%d %H%M} {EXPORT_NAME}", 2
    path = data_root / EXPORTS / f"{base}.csv"
    while path.exists():
        path, n = data_root / EXPORTS / f"{base} ({n}).csv", n + 1
    written = fs.write_text(path, "﻿" + text)
    log.info("tagged labels exported: %d rows", text.count("\n") - 1)
    return written
