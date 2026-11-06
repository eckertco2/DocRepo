"""What's used (release 5.96, the review of 2026-11-06, F15): the ``usage`` command reads the wheels' usage log and the
Activity view's lines, and says how often each command and each kind of thing was used in the last 7 and 30 days, so the
owner can see what's used before the next thing is built. It reads only, and writes nothing.

The usage log is ``System\\logs\\wheel-usage.csv`` (release 5.41): a row per slot picked, with no content. The Activity
view's lines are worked out from docs.db, as the view does (``activity.Activity``): each thing made, changed or noted,
by its chip (New task, Update, Note and the rest).
"""
from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from docrepo.activity import Activity
from docrepo.model import Model

#: The wheels' usage log, in the data root (``ui.wheels.USAGE_LOG``, named here so this needs no Qt).
USAGE_LOG = Path("System") / "logs" / "wheel-usage.csv"
SPANS = (7, 30)


def wheel_counts(data_root: Path, today: date) -> dict[str, list[int]]:
    """Each wheel command picked, with how many times in each of ``SPANS`` days up to ``today``."""
    out: dict[str, list[int]] = {}
    try:
        with (data_root / USAGE_LOG).open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        return out
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("time") or "")[:10])
        except ValueError:
            continue
        command = str(row.get("command") or "").strip() or "(none)"
        counts = out.setdefault(command, [0] * len(SPANS))
        for i, n in enumerate(SPANS):
            if today - timedelta(days=n - 1) <= day <= today:
                counts[i] += 1
    return out


def activity_counts(conn: sqlite3.Connection, today: date) -> dict[str, list[int]]:
    """Each kind of Activity line (its chip), with how many in each of ``SPANS`` days up to ``today``."""
    lines = Activity(Model(conn), today).lines(today - timedelta(days=max(SPANS) - 1), today)
    out: dict[str, list[int]] = {}
    for n_i, n in enumerate(SPANS):
        start = today - timedelta(days=n - 1)
        for kind, k in Counter(x.chip for x in lines if start <= x.day <= today).items():
            out.setdefault(kind, [0] * len(SPANS))[n_i] = k
    return out


def report(conn: sqlite3.Connection, data_root: Path, today: date) -> str:
    """The usage summary as Markdown: the wheels' commands, then the Activity view's kinds, the most used first."""
    def table(title: str, counts: dict[str, list[int]], empty: str) -> list[str]:
        out = [f"## {title}", ""]
        if not counts:
            return out + [empty, ""]
        out += ["| | Last 7 days | Last 30 days |", "|---|---:|---:|"]
        for name, (week, month) in sorted(counts.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0])):
            out.append(f"| {name} | {week} | {month} |")
        return out + [""]

    out = [f"# What's used, as of {today.isoformat()}", "",
           "Counts from the wheels' usage log and the Activity view, for the last 7 and 30 days. Nothing here was changed.", ""]
    out += table("The wheels' commands", wheel_counts(data_root, today), "No wheel was used in the last 30 days, or none is set up.")
    out += table("What was done (the Activity view)", activity_counts(conn, today), "Nothing in the last 30 days.")
    return "\n".join(out)
