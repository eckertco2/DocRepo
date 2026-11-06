"""Check the data root (release 5.89, the review of 2026-11-06, F3): what docs.db says is there, and isn't.

``check`` lists, as Markdown:

- captures whose ``capture.md`` is missing or can't be read. The content text is kept nowhere else, so each line names
  the finished draft in ``System\\Drafts\\Done`` that may still hold it, when one was last changed shortly before the
  capture was saved;
- documents whose text was read (``text_status`` ok) with no ``extracted.txt``;
- saved copies whose file isn't in their task's ``Files`` folder;
- captures and documents missing from the search index, or whose entry differs from what it would be now;
- SQLite's ``PRAGMA quick_check``.

It only reads, and repairs nothing: each line says what the owner can do. The command and Settings' "Check the data
root" write the list to ``System\\check-<date>.md`` through SafeFS.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from docrepo import captures, drafts, search
from docrepo.model import Model
from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

#: A finished draft last changed this long before a capture's save, or less, may be the capture's own.
DRAFT_WINDOW = timedelta(minutes=30)


@dataclass
class Finding:
    """One thing that isn't as docs.db says: what's wrong, and what the owner can do."""

    what: str
    todo: str


@dataclass
class CheckResult:
    at: datetime
    database: str = ""
    sections: dict[str, list[Finding]] = field(default_factory=dict)
    counted: dict[str, int] = field(default_factory=dict)

    @property
    def problems(self) -> int:
        return sum(len(v) for v in self.sections.values()) + (self.database != "ok")

    def markdown(self) -> str:
        out = [f"# Data root check, {self.at:%Y-%m-%d %H:%M}", ""]
        checked = ", ".join(f"{n} {what}" for what, n in self.counted.items())
        out += [f"Checked {checked}." if checked else "", ""]
        out += ["## The database", "", f"- SQLite's quick check: {self.database}" + ("" if self.database == "ok" else
                ". Restore docs.db from the backup folder: its backup-log.md says how."), ""]
        for title, found in self.sections.items():
            out += [f"## {title}", ""]
            out += [f"- {f.what} {f.todo}".rstrip() for f in found] or ["- None."]
            out.append("")
        out.append("Nothing was changed. " + ("Nothing needs doing." if not self.problems else
                                               f"{self.problems} thing{'s' if self.problems != 1 else ''} to look at."))
        return "\n".join(out) + "\n"


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("T", " ")[:19])
    except ValueError:
        return None


def _done_drafts(data_root: Path) -> list[tuple[str, datetime]]:
    """The finished drafts in ``System\\Drafts\\Done``, each with when it last changed."""
    base = data_root / drafts.DONE_DIR
    try:
        names = [p.name for p in base.iterdir() if p.is_dir()]
    except OSError:
        return []
    out = []
    for name in names:
        try:
            import json

            data = json.loads((base / name / drafts.DRAFT_JSON).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        when = _parse(str(data.get("saved") or "")) if isinstance(data, dict) else None
        if when:
            out.append((name, when))
    return out


def _draft_for(saved: str, done: list[tuple[str, datetime]]) -> str | None:
    """The finished draft last changed closest before ``saved``, within ``DRAFT_WINDOW``, or None."""
    at = _parse(saved)
    if at is None:
        return None
    near = [(at - when, name) for name, when in done if timedelta(minutes=-2) <= at - when <= DRAFT_WINDOW]
    return min(near)[1] if near else None


def run_check(conn: sqlite3.Connection, data_root: Path, at: datetime) -> CheckResult:
    """Check the data root against docs.db. Reads only."""
    model = Model(conn)
    result = CheckResult(at)
    try:
        result.database = conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as e:
        result.database = f"it couldn't run ({e})"

    lost, unreadable = [], []
    done = _done_drafts(data_root)
    for c in model.captures.values():
        path = captures.capture_md_path(data_root, c)
        try:
            path.read_text(encoding="utf-8")
            continue
        except FileNotFoundError:
            target = lost
        except (OSError, UnicodeDecodeError):
            target = unreadable
        rel = path.relative_to(data_root)
        draft = _draft_for(c.saved, done)
        hint = (f"Its words may be in the draft `{drafts.DONE_DIR / draft}`: open its draft.json, and copy them onto the capture's task's notes page."
                if draft else "No finished draft matches its time; its words may be on its task's notes page, or in the backup folder's Files.")
        what = "is missing" if target is lost else "can't be read"
        target.append(Finding(f'{c.id} ({c.saved[:16]}, "{c.title}"): `{rel}` {what}.', hint))
    result.sections["Captures with no capture.md"] = lost + unreadable

    texts = []
    for d in model.documents.values():
        if getattr(d, "text_status", None) == "ok" and not (data_root / "Documents" / d.id / "extracted.txt").exists():
            texts.append(Finding(f"{d.id} ({d.name}): its text was read, and `Documents\\{d.id}\\extracted.txt` isn't there.",
                                 "Add the file to a capture again to read its text, or leave it: only search misses it."))
    result.sections["Documents with no extracted text"] = texts

    copies = []
    for f in model.copies:
        path = data_root / "Tasks" / f.task / "Files" / ("_old versions" if f.old else "") / f.name
        if not path.exists():
            copies.append(Finding(f'{f.task}\'s saved copy "{f.name}" isn\'t at `{path.relative_to(data_root)}`.',
                                  "Copy it back from the backup folder's Files, or from its original."))
    result.sections["Saved copies that aren't there"] = copies

    indexed = {(r["kind"], r["id"]): r["body"] for r in conn.execute("SELECT kind, id, body FROM search_text")}
    stale = []
    for c in model.captures.values():
        body = indexed.get(("capture", c.id))
        if body is None or body != search.capture_body(model, data_root, c.id):
            stale.append(Finding(f"{c.id}: {'not in the search index' if body is None else 'its search entry is out of date'}.",
                                 "Rebuild pages, calendar and search (Settings, or the rebuild command) brings it up to date."))
    for d in model.documents.values():
        body = indexed.get(("document", d.id))
        if body is None or body != search.document_body(model, data_root, d.id):
            stale.append(Finding(f"{d.id}: {'not in the search index' if body is None else 'its search entry is out of date'}.",
                                 "Rebuild pages, calendar and search brings it up to date."))
    result.sections["The search index"] = stale
    result.counted = {"captures": len(model.captures), "documents": len(model.documents), "saved copies": len(model.copies)}
    log.info("check: %d problems, quick check %s", result.problems, result.database)
    return result


def write_report(fs: SafeFS, data_root: Path, result: CheckResult) -> Path:
    """The check's list, as ``System\\check-<date>.md`` in the data root. A second check on one day replaces the first."""
    return fs.write_text(data_root / "System" / f"check-{result.at:%Y-%m-%d}.md", result.markdown())
