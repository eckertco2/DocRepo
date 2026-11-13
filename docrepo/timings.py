"""How long DocRepo's everyday work takes on a data root, against its budgets (release 5.126, the cold-eyes plan's decisions
470 to 473). ``python -m docrepo timings`` runs it on any data root; ``tests/test_scale.py`` runs it on three years of made-up
work (``sample_scale``). Not to be confused with ``timing.py``, a template's ties.

It reads and changes nothing. What only reads (the model, the view counts, search, a task page, the task tree and the
Timeline) is timed on docs.db opened read-only. What writes (saving a capture, the daily work and ``rebuild``) is timed on
a copy of docs.db in memory, with a stand-in for SafeFS that counts the files it would write and writes none, so a page is
still read from the data root to see whether it changed. What it prints, and keeps in ``System\\diagnostics``, is counts and
times only (decision 472): never a title, a name or a word of content.

Each budget is the data's part of the work, without Qt's drawing: the rows, the page's HTML and the chart's bars that the
browse tool then shows. The budgets are this computer's (decision 470); the corporate computer is taken as twice as slow.
"""
from __future__ import annotations

import logging
import os
import platform
import sqlite3
import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docrepo import __version__, db
from docrepo.config import Settings
from docrepo.safe_fs import PathLike, SafeFS

log = logging.getLogger(__name__)

#: Where the output is kept, as the troubleshooting report's is.
REPORT_DIR = Path("System") / "diagnostics"
#: The words Search everything is timed with: plant words that most engineers' text holds.
DEFAULT_WORDS = "pump seal drawing"
#: The note saved on the busiest task, in the copy in memory only. Made up.
NOTE = "Timings check: a made-up note on the pump seal, saved to a copy of docs.db in memory and never kept."


@dataclass(frozen=True)
class Budget:
    key: str
    name: str
    seconds: float


#: Decision 470's budgets, on the personal computer.
BUDGETS = (
    Budget("model", "Loading the model", 0.3),
    Budget("counts", "The view counts", 0.3),
    Budget("search", "Search everything, three words", 0.3),
    Budget("page", "A task page with 300 notes", 0.3),
    # Release 5.140 (the notes consolidation plan's decision 609): the task page's budget, for its All notes and Meetings.
    Budget("allnotes", "All notes and Meetings on the busiest project", 0.3),
    Budget("save", "Saving a capture on a task", 0.5),
    Budget("tree", "Refreshing the task tree", 0.5),
    Budget("timeline", "The Timeline over 12 months", 1.0),
    Budget("daily", "The daily work", 10.0),
    Budget("rebuild", "rebuild", 120.0),
)
BUDGET = {b.key: b for b in BUDGETS}


@dataclass
class Timing:
    """One operation's time, in seconds, the median of ``runs``. ``note`` says how much it handled, in numbers only."""

    key: str
    seconds: float
    runs: int = 1
    note: str = ""

    @property
    def budget(self) -> Budget:
        return BUDGET[self.key]

    @property
    def within(self) -> bool:
        return self.seconds <= self.budget.seconds


class CountingFS(SafeFS):
    """SafeFS's checks with none of its writes: each write is checked and counted, then dropped. For timing what writes,
    against a copy of docs.db in memory, without changing the data root."""

    def __init__(self, roots: list[PathLike]) -> None:
        super().__init__(roots)
        self.writes = 0

    def _count(self, path: PathLike) -> Path:
        self.writes += 1
        return self.checked_path(path)

    def makedirs(self, path: PathLike) -> Path:
        return self.checked_path(path)

    def write_text(self, path: PathLike, text: str) -> Path:
        return self._count(path)

    def append_text(self, path: PathLike, text: str) -> Path:
        return self._count(path)

    def write_picture(self, path: PathLike, data: bytes) -> Path:
        return self._count(path)

    def write_copy(self, path: PathLike, data: bytes) -> Path:
        return self._count(path)

    def copy_file(self, src: PathLike, dst: PathLike) -> Path:
        return self._count(dst)

    def replace_file(self, src: PathLike, dst: PathLike) -> Path:
        return self._count(dst)

    def replace(self, src: PathLike, dst: PathLike) -> Path:
        return self._count(dst)

    def move(self, src: PathLike, dst: PathLike) -> Path:
        return self._count(dst)


class TimingsError(Exception):
    """The data root can't be timed: no docs.db, or one at another schema version."""


def open_read_only(data_root: Path) -> sqlite3.Connection:
    """docs.db, read-only, with rows by name as DocRepo reads them. TimingsError when it's missing or at another schema."""
    if not db.db_path(data_root).exists():
        raise TimingsError(f"{data_root} has no docs.db to time. Run: python -m docrepo init")
    conn = db.connect_read_only(data_root)
    conn.row_factory = sqlite3.Row
    version = db.schema_version(conn)
    if version != db.SCHEMA_VERSION:
        conn.close()
        raise TimingsError(f"docs.db is at schema {version} and this DocRepo reads schema {db.SCHEMA_VERSION}. "
                           "Start DocRepo once, so it brings docs.db up to date, then time it.")
    return conn


def copy_in_memory(conn: sqlite3.Connection) -> sqlite3.Connection:
    """A copy of a docs.db in memory, which what writes is timed on."""
    mem = sqlite3.connect(":memory:", isolation_level=None)
    conn.backup(mem)
    mem.row_factory = sqlite3.Row
    mem.execute("PRAGMA foreign_keys = ON")
    return mem


def busiest_task(model) -> tuple[str | None, int]:
    """The task with the most captures, and how many: the task page that's timed."""
    counts = Counter(c.task for c in model.captures.values() if c.task and c.task in model.tasks)
    if not counts:
        return None, 0
    task, n = counts.most_common(1)[0]
    return task, n


def busiest_project(model) -> tuple[str | None, int]:
    """The top-level task with the most live tasks under it, and how many: the All notes that's timed (release 5.140)."""
    best, most = None, -1
    for t in model.tasks.values():
        if t.discarded or model.parents_of(t.id):
            continue
        n = sum(1 for x in model.descendants_of(t.id) if x in model.tasks and not model.tasks[x].discarded)
        if n > most:
            best, most = t.id, n
    return best, max(most, 0)


def _clock(work: Callable[[], object], runs: int) -> tuple[float, object]:
    """The median time of ``runs`` runs of ``work``, and what the last returned."""
    times, out = [], None
    for _ in range(runs):
        start = time.perf_counter()
        out = work()
        times.append(time.perf_counter() - start)
    return statistics.median(times), out


def measure(data_root: Path, settings: Settings, now: datetime, words: str = DEFAULT_WORDS, runs: int = 3,
            keys: tuple[str, ...] | None = None) -> list[Timing]:
    """Time each budget's operation on a data root, ``runs`` times for the quick ones (the median counts) and once for the
    daily work and ``rebuild``. ``keys`` times only those. The data root and its docs.db are left as they were."""
    from docrepo import capacity, meeting_rows, notes_page, search, timeline
    from docrepo.captures import read_content
    from docrepo.detail import PageState, Pages
    from docrepo.model import Model
    from docrepo.pages import write_pages
    from docrepo.save import CaptureDraft, save_capture
    from docrepo.views import TreeFilter, due_cell, markers, sort_tree, task_tree, view_counts, walk

    data_root = Path(os.path.abspath(data_root))  # SafeFS takes a full path
    wanted = set(keys or BUDGET)
    today = now.date()
    out: list[Timing] = []
    logging.disable(logging.INFO)  # a save's and a rebuild's lines would say what wasn't kept, and cost time of their own
    conn = open_read_only(data_root)
    try:
        model_time, m = _clock(lambda: Model(conn), runs)
        if "model" in wanted:
            out.append(Timing("model", model_time, runs, f"{len(m.tasks):,} tasks, {len(m.captures):,} captures"))
        if "counts" in wanted:
            t, counts = _clock(lambda: view_counts(m, today, settings.me), runs)
            out.append(Timing("counts", t, runs, f"{len(counts)} views"))
        if "search" in wanted:
            t, results = _clock(lambda: search.search(conn, m, words, today), runs)
            out.append(Timing("search", t, runs, f"{len(results):,} results"))
        busiest, notes = busiest_task(m)
        if "page" in wanted and busiest:
            def page() -> int:
                pages = Pages(m, today, lambda cid: read_content(data_root, m.captures[cid]) or "" if cid in m.captures else "",
                              settings.me, conn, hints=False, reference_links=settings.reference_links)
                html = pages.task_page(busiest, PageState())
                return len(html) + len(notes_page.lines_of(m.pages.get(busiest, "")))
            t, _ = _clock(page, runs)
            out.append(Timing("page", t, runs, f"its task has {notes:,} captures"))
        project, under = busiest_project(m)
        if "allnotes" in wanted and project:
            def all_notes() -> int:
                pages = Pages(m, today, lambda cid: read_content(data_root, m.captures[cid]) or "" if cid in m.captures else "",
                              settings.me, conn, hints=False, reference_links=settings.reference_links)
                html, _an = pages.all_notes(project, PageState())
                rows = meeting_rows.rows(m, project)
                return len(html) + len(pages.meeting_rows_html(m.task(project), rows, PageState()) if rows else "")
            t, _ = _clock(all_notes, runs)
            out.append(Timing("allnotes", t, runs, f"{under:,} tasks under it"))
        if "tree" in wanted:
            def tree() -> int:
                mm = Model(conn)
                nodes = sort_tree(mm, task_tree(mm, TreeFilter()), "default", today)
                shown = 0
                for node in walk(nodes):
                    t = mm.task(node.id)
                    markers(mm, t)
                    due_cell(t, today)
                    shown += 1
                return shown
            t, rows = _clock(tree, runs)
            out.append(Timing("tree", t, runs, f"{rows:,} rows, the model read again"))
        if "timeline" in wanted:
            t, chart = _clock(lambda: timeline.build(m, today, timeline.default_start(today), 52), runs)
            out.append(Timing("timeline", t, runs, f"{len(chart.rows):,} rows"))

        if wanted & {"save", "daily", "rebuild"}:
            mem = copy_in_memory(conn)
            fs = CountingFS([data_root])
            try:
                if "save" in wanted and busiest:
                    def save() -> object:
                        return save_capture(mem, data_root, fs, settings, CaptureDraft(content=NOTE, task=busiest), now)
                    t, _ = _clock(save, runs)
                    out.append(Timing("save", t, runs, "a note, on the task with the most captures"))
                if "daily" in wanted:
                    def daily() -> int:
                        capacity.rebuild_all(mem, today, settings)
                        written = write_pages(Model(mem), data_root, fs, today, now)
                        if search.needs_rebuild(mem):
                            search.rebuild(mem, data_root)
                        return written
                    fs.writes = 0
                    t, written = _clock(daily, 1)
                    out.append(Timing("daily", t, 1, f"{written:,} pages would be written"))
                if "rebuild" in wanted:
                    from docrepo.cli import _rebuild

                    fs.writes = 0
                    t, (rows, pages) = _clock(lambda: _rebuild(mem, data_root, settings, fs, now), 1)
                    out.append(Timing("rebuild", t, 1, f"{rows:,} calendar rows, {pages:,} pages would be written"))
            finally:
                mem.close()
    finally:
        conn.close()
        logging.disable(logging.NOTSET)
    order = [b.key for b in BUDGETS]
    out.sort(key=lambda x: order.index(x.key))
    log.info("timings: %s", ", ".join(f"{x.key} {x.seconds * 1000:.0f} ms" for x in out))
    return out


def counts(data_root: Path) -> list[tuple[str, str]]:
    """How much the data root holds, in numbers only."""
    conn = open_read_only(data_root)
    try:
        def n(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]

        rows = [
            ("Tasks", n("SELECT count(*) FROM tasks")),
            ("Top-level tasks", n("SELECT count(*) FROM tasks WHERE id NOT IN (SELECT child FROM task_parents)")),
            ("Open tasks", n("SELECT count(*) FROM tasks WHERE state IN ('Not started', 'In progress')")),
            ("Captures", n("SELECT count(*) FROM captures")),
            ("Emails in captures", n("SELECT count(*) FROM capture_emails")),
            ("Documents", n("SELECT count(*) FROM documents")),
            ("Status-log rows", n("SELECT count(*) FROM status_log")),
            ("Agenda items", n("SELECT count(*) FROM agenda_items")),
            ("Tagged labels", n("SELECT count(*) FROM tagged_labels")),
            ("Tagged label mentions", n("SELECT count(*) FROM tagged_mentions")),
            ("People", n("SELECT count(*) FROM people")),
            ("Notes pages", n("SELECT count(*) FROM task_pages")),
            ("Items in the search index", n("SELECT count(*) FROM search_text")),
        ]
        text = n("SELECT coalesce(sum(length(CAST(body AS BLOB))), 0) FROM search_text WHERE kind = 'document'")
    finally:
        conn.close()
    out = [(name, f"{value:,}") for name, value in rows]
    out.append(("Documents' text in the search index", megabytes(text)))
    out.append(("docs.db", megabytes(os.path.getsize(db.db_path(data_root)))))
    return out


def megabytes(size: int) -> str:
    return f"{size / 1_000_000:,.1f} MB"


def duration(seconds: float) -> str:
    """A time as the budgets give one: "212 ms", "1.4 s"."""
    return f"{seconds * 1000:,.0f} ms" if seconds < 1 else f"{seconds:,.1f} s"


def verdict(x: Timing) -> str:
    """Within the budget, within twice it (the corporate computer's), or over both."""
    if x.within:
        return "Within"
    return "Within twice" if x.seconds <= 2 * x.budget.seconds else "Over"


def report(data_root: Path, timings: list[Timing], now: datetime, data_counts: list[tuple[str, str]]) -> str:
    """The output, as Markdown: what was timed with, how much the data root holds, and each time against its budget."""
    lines = [
        f"# DocRepo timings, {now:%Y-%m-%d %H:%M}",
        "",
        f"DocRepo {__version__}, schema {db.SCHEMA_VERSION}, Python {platform.python_version()}, SQLite {sqlite3.sqlite_version}, "
        f"{platform.system()} {platform.release()}, {os.cpu_count()} processors.",
        "Counts and times only: no titles, names or words of content. docs.db was read, and copied into memory to time what "
        "writes; nothing in the data root was changed.",
        "",
        "## What the data root holds",
        "",
        "| What | How many |",
        "|---|---|",
        *(f"| {name} | {value} |" for name, value in data_counts),
        "",
        "## Times",
        "",
        "The budgets are the personal computer's; the corporate computer is taken as twice as slow, so its budget is the "
        "second column. A quick operation's time is the median of its runs.",
        "",
        "| Operation | Time | Budget | Twice the budget | | Runs | What it handled |",
        "|---|---|---|---|---|---|---|",
        *(f"| {x.budget.name} | {duration(x.seconds)} | {duration(x.budget.seconds)} | {duration(2 * x.budget.seconds)} | "
          f"{verdict(x)} | {x.runs} | {x.note} |" for x in timings),
        "",
    ]
    return "\n".join(lines)


def save_report(fs: SafeFS, data_root: Path, text: str, now: datetime) -> Path:
    """Keep the output as System\\diagnostics\\timings YYYY-MM-DD HHMM.md, never over an earlier one."""
    folder = data_root / REPORT_DIR
    name = f"timings {now:%Y-%m-%d %H%M}"
    path, n = folder / f"{name}.md", 2
    while path.exists():
        path, n = folder / f"{name} ({n}).md", n + 1
    return fs.write_text(path, text)
