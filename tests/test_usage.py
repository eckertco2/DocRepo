"""What's used (release 5.96, the review of 2026-11-06, F15): the usage command's counts from the wheels' usage log and the
Activity view, over 7 and 30 days, and that it writes nothing."""
from __future__ import annotations

from datetime import date

from docrepo import usage
from docrepo.cli import main

TODAY = date(2026, 10, 8)
HEADER = "time,wheel,direction,command,how,drawn,appear_ms,pick_ms\r\n"


def write_log(root, rows: list[str]) -> None:
    path = root / usage.USAGE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "".join(r + "\r\n" for r in rows), encoding="utf-8")


def test_the_wheels_commands_are_counted_by_week_and_month(sample_root):
    conn, root, _ = sample_root
    write_log(root, ["2026-10-08 09:00,capture,N,capture.note,key,1,40,300",
                     "2026-10-03 09:00,capture,N,capture.note,key,1,40,300",
                     "2026-09-20 09:00,capture,E,today.panel,numpad,1,40,300",
                     "2026-08-01 09:00,capture,E,today.panel,numpad,1,40,300",  # too old for either
                     "not a time,capture,S,capture.task,key,1,40,300"])
    assert usage.wheel_counts(root, TODAY) == {"capture.note": [2, 2], "today.panel": [0, 1]}


def test_no_log_is_no_wheels(sample_root):
    assert usage.wheel_counts(sample_root[1], TODAY) == {}


def test_the_activity_view_is_counted_by_kind(sample_root):
    conn, _, _ = sample_root
    counts = usage.activity_counts(conn, TODAY)
    assert counts and all(month >= week for week, month in counts.values())
    report = usage.report(conn, sample_root[1], TODAY)
    assert report.startswith("# What's used, as of 2026-10-08") and "## What was done (the Activity view)" in report
    assert "No wheel was used in the last 30 days" in report


def test_the_command_prints_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    assert main(["--data-root", str(root), "load-sample"]) == 0
    write_log(root, ["2026-10-07 10:00,capture,N,capture.note,key,1,40,300"])
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file() and "logs" not in p.parts}
    capsys.readouterr()
    assert main(["--data-root", str(root), "usage", "--as-of", "2026-10-08"]) == 0
    out = capsys.readouterr().out
    assert "| capture.note | 1 | 1 |" in out
    after = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file() and "logs" not in p.parts}
    assert after == before  # only the log (docrepo.log) may change: nothing else is written
