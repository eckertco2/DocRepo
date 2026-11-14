"""The timing budgets at scale (release 5.126, the cold-eyes plan's decisions 469 to 473): three years of a lead engineer's
made-up work (``docrepo.sample_scale``), and each everyday operation timed on it against its budget (``docrepo.timings``).

They take minutes, so they never run in the default or the fast run (decision 471): run them before each train with
``.venv\\Scripts\\python.exe -m pytest -m scale``. The data root is built once by ``load-sample --years 3`` and kept in
``.pytest_tmp\\scale-v<generator version>-s<schema version>-3y``, so only the first run, or the first after the generator
or the schema changes, builds it. (Before the train of 2026-11-13 the name had no schema, so a root built at schema 25 was
kept at 28, and `timings` refused it: every budget erred.)
The last run's times are kept beside it as ``last-timings.md``.

A missed budget fails with its time. A budget missed on the day it's built is recorded in ``MISSED`` (decision 473): its
test is expected to fail, with the time it took, and its fix is a release of its own.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from docrepo import cli, db, sample_scale, timings
from docrepo.config import Settings
from docrepo.sample import SAMPLE_AS_OF

from conftest import TEMP_ROOT

pytestmark = pytest.mark.scale

YEARS = 3
#: Decision 473: the budgets missed on 2026-11-11, when they were first measured, with the time each took then. Each one's
#: fix is a release of its own; the release that fixes one takes it off this list.
MISSED: dict[str, str] = {
    "model": "1.6 s on 2026-11-11: tagged.load reads the JSON of each of 132,000 mentions",
    "counts": "17.2 s on 2026-11-11: Model.only_in_discarded looks through every capture for each of 7,500 documents",
    "search": "314 ms on 2026-11-11: LIKE over 91 MB of documents' text (row 8, ranked search, is its fix)",
    "page": "4.4 s on 2026-11-11: Stories.note_item looks through all 90,000 status-log rows for each capture on the page",
    "save": "7.6 s on 2026-11-11: save_capture reads the model about five times",
    "tree": "1.5 s on 2026-11-11: the model read again (see model)",
    "daily": "17.1 s on 2026-11-11: tagged.task_tags per page (8 s), capacity.rebuild_task reading every task for each (4.4 s), "
             "Model.tied_to per task (2.5 s)",
}


def built_root(years: int = YEARS) -> Path:
    """The scale data root, built once per generator version and schema version and kept in .pytest_tmp. Two runs at once
    each build their own and the second keeps the first's."""
    folder = TEMP_ROOT / f"scale-v{sample_scale.VERSION}-s{db.SCHEMA_VERSION}-{years}y"
    root = folder / "DocRepoData"
    if (folder / "built.txt").exists():
        return root
    building = TEMP_ROOT / f"scale-building-{os.getpid()}"
    shutil.rmtree(building, ignore_errors=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOCALAPPDATA", str(building / "localappdata"))
        for args in (["init"], ["load-sample", "--years", str(years)]):
            assert cli.main(["--data-root", str(building / "DocRepoData"), *args]) == 0
    (building / "built.txt").write_text(f"load-sample --years {years}, generator version {sample_scale.VERSION}\n", encoding="utf-8")
    _close_log_file()  # Windows won't move a folder with DocRepo's log open in it
    try:
        building.rename(folder)
    except OSError:  # another run built it first
        shutil.rmtree(building, ignore_errors=True)
    assert (folder / "built.txt").exists(), f"the scale data root wasn't kept in {folder}"
    return root


def _close_log_file() -> None:
    """Detach DocRepo's log file, as conftest's close_log_file does after each test."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if h.get_name() == "docrepo-file"]:
        root.removeHandler(handler)
        handler.close()


@pytest.fixture(scope="module")
def scale_root() -> Path:
    return built_root()


@pytest.fixture(scope="module")
def timed(scale_root: Path) -> dict[str, timings.Timing]:
    """Every budget's time on the scale data root, measured once for the module, and kept as last-timings.md."""
    db_file = db.db_path(scale_root)
    before = (db_file.stat().st_mtime_ns, db_file.stat().st_size)
    found = timings.measure(scale_root, Settings.load(scale_root), SAMPLE_AS_OF)
    assert (db_file.stat().st_mtime_ns, db_file.stat().st_size) == before, "timing changed docs.db"
    text = timings.report(scale_root, found, SAMPLE_AS_OF, timings.counts(scale_root))
    (scale_root.parent / "last-timings.md").write_text(text, encoding="utf-8")
    print(text)
    return {x.key: x for x in found}


def test_the_data_root_holds_three_years_of_work(scale_root: Path):
    """Decision 469's sizes, three times over, on top of the sample's own."""
    conn = sqlite3.connect(db.db_path(scale_root))
    try:
        def n(table: str) -> int:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 - the tests' own table names

        want = sample_scale.totals(YEARS)
        assert n("tasks") >= want["tasks"]
        assert n("captures") >= want["captures"]
        assert n("capture_emails") >= want["emails"]
        assert n("documents") >= want["documents"]
        assert n("status_log") >= want["status_log"]
        assert n("agenda_items") >= want["agenda"]
        assert n("tagged_labels") >= want["tagged"]
        assert n("people") >= want["people"]
        assert n("tagged_mentions") > 0
        text = conn.execute("SELECT avg(length(body)) FROM search_text WHERE kind = 'document'").fetchone()[0]
        assert 10_000 < text < 14_000
    finally:
        conn.close()


def _budget_params() -> list:
    return [pytest.param(b.key, id=b.key, marks=[pytest.mark.xfail(reason=MISSED[b.key], strict=False)] if b.key in MISSED else [])
            for b in timings.BUDGETS]


@pytest.mark.parametrize("key", _budget_params())
def test_budget(timed: dict[str, timings.Timing], key: str):
    """Decision 470: each operation within its budget on this computer. The message gives the time it took."""
    x = timed[key]
    assert x.within, f"{x.budget.name} took {timings.duration(x.seconds)}, over its budget of {timings.duration(x.budget.seconds)} ({x.note})"
