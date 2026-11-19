"""A glossary from Excel or CSV (release 5.171; the design workspace's ``docs/mods/glossaries-plan.md``, decisions 804 and 805).

- **Reading:** as the tag list's import reads a file (``tagged_import.read_rows``): an ``.xlsx`` opened read-only, a
  ``.csv`` as UTF-8 or Windows' own encoding, its separator worked out. Neither is ever changed. A sheet of more than
  ``MAX_ROWS`` rows below its header is refused rather than cut, so a glossary is never part of its sheet.
- **Columns:** every one is kept, named as its header (an empty header is "Column 3"; a second "Area" is "Area (2)"), as
  wide as the widest row. The header row is guessed (``tagged_import.guess_header``) and changed in the form.
- **The tag column** is optional: of the columns whose header says it holds tags ("Tag No.", "Equipment number"), the one
  whose cells are most often tag-shaped; with none, the column whose cells are most often tag-shaped, when at least half
  are (decision 676's rule, ``tagged_import.tag_share``); else none.
- **The preview** says what Import would keep, and for Import again what's added, gone and changed (``glossaries.compare``).
  Nothing is written until Import. A row with nothing in it is left out.

The log records counts, never the file's contents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docrepo import glossaries, tagged_import
from docrepo.excel_import import WorkbookError

MAX_ROWS = tagged_import.MAX_ROWS


def read_rows(path: Path, sheet: str | None = None) -> list[list[str]]:
    """The file's rows as text (``tagged_import.read_rows``): at most MAX_ROWS and a few for the header, which is enough to
    tell that a sheet is too long."""
    return tagged_import.read_rows(path, sheet)


def workbook_sheets(path: Path) -> list[str]:
    return tagged_import.workbook_sheets(path)


def guess_header(rows: list[list[str]]) -> int:
    return tagged_import.guess_header(rows)


def columns_of(rows: list[list[str]], header_row: int) -> list[str]:
    """The columns' names: the header's cells, as wide as the widest row below it; an empty one "Column n", and a name
    already used given its count ("Area (2)")."""
    header = rows[header_row] if header_row < len(rows) else []
    width = max([len(header), *(len(r) for r in rows[header_row + 1:])], default=0)
    out: list[str] = []
    for i in range(width):
        name = " ".join((header[i] if i < len(header) else "").split()) or f"Column {i + 1}"
        base, n = name, 2
        while name.casefold() in (x.casefold() for x in out):
            name, n = f"{base} ({n})", n + 1
        out.append(name)
    return out


def guess_tag_column(rows: list[list[str]], header_row: int) -> int | None:
    """The tag column (decision 804, by decision 676's rule): of the columns whose header says tags, the most tag-shaped;
    with none, the most tag-shaped column when at least half its cells are tags; else None."""
    width = len(columns_of(rows, header_row))
    header = rows[header_row] if header_row < len(rows) else []
    said = [i for i in range(width) if i < len(header) and tagged_import.guess_field(header[i]) == "label"]
    share = {i: tagged_import.tag_share(rows, header_row, i) for i in range(width)}
    if said:
        best = max(said, key=lambda i: (share[i], -i))
        return best if share[best] > 0 else None
    best = max(range(width), key=lambda i: (share[i], -i), default=None)
    return best if best is not None and share[best] >= 0.5 else None


def body_of(rows: list[list[str]], header_row: int, width: int) -> tuple[list[list[str]], int]:
    """The rows below the header, each as wide as the columns, trimmed; and how many empty rows were left out."""
    out, empty = [], 0
    for r in rows[header_row + 1:]:
        cells = [" ".join((r[i] if i < len(r) else "").split()) for i in range(width)]
        if not any(cells):
            empty += 1
            continue
        out.append(cells)
    return out, empty


@dataclass
class Preview:
    """What Import would keep: the name, the columns, the tag column, the rows, how many empty rows are left out, and for
    Import again (``against``) what changes; or ``error``, why nothing can be imported."""

    name: str
    columns: list[str]
    tag_column: int | None
    rows: list[list[str]] = field(default_factory=list)
    empty: int = 0
    changes: glossaries.Changes | None = None
    error: str = ""

    def summary(self) -> str:
        n = len(self.rows)
        tag = f", the tags in {self.columns[self.tag_column]}" if self.tag_column is not None else ", no tag column"
        out = f"{n:,} row{'s' if n != 1 else ''} in {len(self.columns)} column{'s' if len(self.columns) != 1 else ''}{tag}"
        if self.empty:
            out += f" · {self.empty:,} empty row{'s' if self.empty != 1 else ''} left out"
        if self.changes is not None:
            out += f" · {self.changes.words()}"
        return out


def preview(conn, rows: list[list[str]], header_row: int, name: str, tag_column: int | None,
            against: glossaries.Glossary | None = None) -> Preview:
    """What Import (or, with ``against``, Import again) would keep. Nothing is written."""
    columns = columns_of(rows, header_row)
    out = Preview(glossaries.tidy_name(name), columns, tag_column if tag_column is not None and tag_column < len(columns) else None)
    if not columns:
        out.error = "There's nothing in the header row. Pick the row that names the columns."
        return out
    body, out.empty = body_of(rows, header_row, len(columns))
    if len(body) > MAX_ROWS:
        out.error = f"The sheet has more than {MAX_ROWS:,} rows below its header. Split it into glossaries of {MAX_ROWS:,} rows or fewer."
        return out
    if not body:
        out.error = "There are no rows below the header row."
        return out
    out.rows = body
    if against is None:
        out.error = glossaries.name_problem(conn, name)
    else:
        old, _ = glossaries.rows_of(conn, against.id, limit=None)
        out.changes = glossaries.compare(against.columns, old, against.tag_column, columns, body, out.tag_column)
    return out


def tag_plan(preview_: Preview, description_column: int | None) -> tagged_import.Plan:
    """Add these to the tag list too (decision 805): the tag list's own import, run on the tag column (its tagged labels)
    and the column chosen as each tag's description, the rest left out."""
    fields = ["skip"] * len(preview_.columns)
    if preview_.tag_column is not None:
        fields[preview_.tag_column] = "label"
    if description_column is not None and description_column != preview_.tag_column and description_column < len(fields):
        fields[description_column] = "description"
    return tagged_import.Plan(0, fields)


def tag_rows(preview_: Preview) -> list[list[str]]:
    """The preview's rows with its columns as the header, as the tag list's import reads them."""
    return [list(preview_.columns), *preview_.rows]


def guess_description(preview_: Preview) -> int | None:
    """The column a tag's description comes from, guessed from the headers as the tag list's import guesses ("Description",
    "Service", "Equipment name"); else the first column after the tag column; else None."""
    for i, name in enumerate(preview_.columns):
        if i != preview_.tag_column and tagged_import.guess_field(name) == "description":
            return i
    others = [i for i in range(len(preview_.columns)) if i != preview_.tag_column]
    after = [i for i in others if preview_.tag_column is not None and i > preview_.tag_column]
    return (after or others or [None])[0]


__all__ = ["MAX_ROWS", "Preview", "WorkbookError", "body_of", "columns_of", "guess_description", "guess_header", "guess_tag_column",
           "preview", "read_rows", "tag_plan", "tag_rows", "workbook_sheets"]
