"""File search's records (release 5.42, decision 214): each file and saved email of every task, built with the Task view's
own functions (``docrepo/overview.py``), and each file once. No Qt. Searching them is ``docrepo/finder.py``'s.

Nothing here is vector-based; that's the knowledge base's, later.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from docrepo import overview
from docrepo.model import Model
from docrepo.overview import Record


def records(conn: sqlite3.Connection, model: Model, data_root: Path) -> list[Record]:
    """Every task's files and emails, newest first. A file on several tasks is one row, on the first task that has it."""
    texts = overview.capture_texts(conn, [c.id for c in model.live_captures()])
    seen: set[tuple[str, str]] = set()
    out: list[Record] = []
    for top in model.top_level():
        if top.discarded:
            continue
        for r in overview.build(model, data_root, top.id, texts):
            key = (r.kind, r.id)
            if r.kind in ("file", "email") and key not in seen:
                seen.add(key)
                out.append(r)
    out.sort(key=lambda r: r.at, reverse=True)
    return out


def task_title(model: Model, r: Record) -> str:
    """Which task a row is on, as each row says."""
    t = model.tasks.get(r.task)
    return t.title if t else ""
