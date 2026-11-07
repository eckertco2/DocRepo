"""The dump (release 5.102, the review of 2026-11-06's smaller items): every table of docs.db as JSON, one file each, in
``System\\export\\<date>\\`` in the data root.

Much of what DocRepo knows lives only in SQLite: templates and their ties, task ties, pins, document uses, notes page
versions, label keywords and parents, reference fields. The dump gives all of it a plain-file way out, for reading in
another program or by an LLM. Each ``<table>.json`` holds the table's name, its columns and its rows, each row an
object of column and value; ``_dump.json`` says which DocRepo made the dump, when, at which schema version, and how many
rows each table had.

It reads docs.db through a read-only connection, in one transaction, so the tables agree with each other; it changes
nothing in the database, and writes only through SafeFS. A second dump on one day replaces the first's files. The
backup doesn't copy ``System`` (only its drafts), so the dump isn't backed up: it's made again from docs.db, which is.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docrepo import __version__, db
from docrepo.dates import stamp
from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

#: Where dumps go in the data root: a folder per day below it.
EXPORT_DIR = Path("System") / "export"
#: The dump's own record of itself, beside the tables' files (no table's name starts with an underscore).
INDEX_FILE = "_dump.json"


@dataclass
class DumpResult:
    """What a dump wrote: its folder, and each table with its number of rows, in name order."""

    folder: Path
    tables: dict[str, int] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        """The rows dumped, in all the tables."""
        return sum(self.tables.values())


def dump_folder(data_root: Path, at: datetime) -> Path:
    """The folder a dump made at ``at`` writes: ``System\\export\\<YYYY-MM-DD>`` in the data root."""
    return data_root / EXPORT_DIR / f"{at:%Y-%m-%d}"


def _quoted(name: str) -> str:
    """A table's name as an SQL identifier, in double quotes."""
    return '"' + name.replace('"', '""') + '"'


def _value(value: object) -> object:
    """A value as JSON holds it. SQLite's numbers, text and NULL go as they are; bytes, which DocRepo doesn't store,
    would go as hex."""
    return {"hex": value.hex()} if isinstance(value, bytes) else value


def table_names(conn: sqlite3.Connection) -> list[str]:
    """docs.db's tables, in name order, without SQLite's own."""
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' "
                                       "ORDER BY name")]


def read_tables(conn: sqlite3.Connection) -> dict[str, dict]:
    """Every table's columns and rows, read in one transaction so they agree with each other."""
    out: dict[str, dict] = {}
    conn.execute("BEGIN")
    try:
        names = table_names(conn)
        for name in names:
            db.check_names(name, names)  # a name sqlite_master gives, in quotes
            cur = conn.execute(f"SELECT * FROM {_quoted(name)}")  # noqa: S608 - a table name docs.db itself lists, quoted; no values
            columns = [d[0] for d in cur.description]
            out[name] = {"table": name, "columns": columns, "rows": [dict(zip(columns, map(_value, r), strict=True)) for r in cur]}
    finally:
        conn.execute("COMMIT")
    return out


def dump(data_root: Path, fs: SafeFS, at: datetime) -> DumpResult:
    """Write every table of the data root's docs.db as JSON into ``dump_folder``. Raises ``sqlite3.Error`` when docs.db
    can't be read, and writes nothing then."""
    conn = db.connect_read_only(data_root)
    conn.isolation_level = None  # the one transaction is read_tables' own
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = read_tables(conn)
    finally:
        conn.close()
    result = DumpResult(dump_folder(data_root, at))
    for name, data in tables.items():
        fs.write_text(result.folder / f"{name}.json", json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        result.tables[name] = len(data["rows"])
    index = {"made_by": f"DocRepo {__version__}", "made": stamp(at), "schema_version": version, "tables": result.tables}
    fs.write_text(result.folder / INDEX_FILE, json.dumps(index, ensure_ascii=False, indent=1) + "\n")
    log.info("dump: %d tables, %d rows, to %s", len(result.tables), result.rows, result.folder)
    return result
