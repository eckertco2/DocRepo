"""The task model against the mockup's test vectors: capacity, days until due, lists, labels and parent chains,
raw text logs and agendas, all computed from the sample data as of Thursday 2026-10-08."""
from __future__ import annotations

from datetime import date, timedelta

from conftest import table_lines, vector_lines

from docrepo import capacity
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.report import build_report, fixed2

TODAY = date(2026, 10, 8)
WEEKS = [date(2026, 10, 5) + timedelta(weeks=i) for i in range(9)]


def report(conn) -> list[str]:
    capacity.rebuild_all(conn, TODAY, Settings(me="P001"))
    text = build_report(conn, Model(conn), TODAY, Settings(me="P001"), WEEKS, date(2026, 10, 19))
    return table_lines(text)


def section(lines: list[str], heading: str) -> list[str]:
    start = lines.index(f"## {heading}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def test_capacity_per_person_and_week(sample_conn):
    expected = vector_lines("Capacity: scheduled hours per person and week", "Capacity: week of 19 Oct, by task")
    assert section(report(sample_conn), "Capacity: scheduled hours per person and week") == expected


def test_capacity_by_task(sample_conn):
    expected = vector_lines("Capacity: week of 19 Oct, by task", "Days until due")
    assert section(report(sample_conn), "Capacity: week of 19 Oct, by task") == expected


def test_days_until_due(sample_conn):
    assert section(report(sample_conn), "Days until due") == vector_lines("Days until due", "Lists")


def test_lists(sample_conn):
    assert section(report(sample_conn), "Lists") == vector_lines("Lists", "Labels and parent chains")


def test_labels_and_parent_chains(sample_conn):
    expected = vector_lines("Labels and parent chains", "Raw text log")
    assert section(report(sample_conn), "Labels and parent chains") == expected


def test_raw_text_logs(sample_conn):
    assert section(report(sample_conn), "Raw text log") == vector_lines("Raw text log", "Agendas")


def test_agendas(sample_conn):
    assert section(report(sample_conn), "Agendas") == vector_lines("Agendas", "Paths")


def test_the_whole_report_matches(sample_conn):
    assert report(sample_conn) == vector_lines("Capacity: scheduled hours per person and week", "Paths")


def test_two_decimals_round_halves_up():
    assert fixed2(0.125) == "0.13"
    assert fixed2(2.0) == "2.00"
    assert fixed2(10.466666) == "10.47"
