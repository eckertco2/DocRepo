"""The scale generator and the ``timings`` command (release 5.126, the cold-eyes plan's decisions 469 to 474), small and
quick: the generator's shape, that it's the same for one seed and made up, and that timing changes nothing and says
nothing of the content. The budgets themselves are timed at three years in ``test_scale.py``, run with ``-m scale``."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from conftest import asks_for_scale

from docrepo import cli, db, sample_scale, timings
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.safe_fs import WriteRefused
from docrepo.sample import SAMPLE_AS_OF, load_sample, read_sample
from docrepo.sample_scale import add_scale_extras, add_years, totals

SMALL = 0.02  # a fiftieth of decision 469's sizes


@pytest.fixture(scope="module")
def small() -> dict:
    return add_years(read_sample(), 1, scale=SMALL)


def test_the_sizes_are_decision_469s():
    assert totals(3) == {"projects": 60, "tasks": 1500, "captures": 15000, "emails": 4500, "documents": 7500, "text": 12000,
                         "status_log": 90000, "agenda": 450, "tagged": 4500, "people": 75}


def test_one_seed_gives_the_same_data_every_time(small: dict):
    again = add_years(read_sample(), 1, scale=SMALL)
    assert json.dumps(again, sort_keys=True) == json.dumps(small, sort_keys=True)
    other = add_years(read_sample(), 1, seed=7, scale=SMALL)
    assert json.dumps(other, sort_keys=True) != json.dumps(small, sort_keys=True)


def test_it_adds_to_the_sample_with_ids_after_its_own(small: dict):
    base = read_sample()
    for kind, key in (("tasks", "T"), ("captures", "C"), ("documents", "D")):
        assert [x["id"] for x in small[kind][:len(base[kind])]] == [x["id"] for x in base[kind]]
        new = [x["id"] for x in small[kind][len(base[kind]):]]
        assert new and min(new) > max(x["id"] for x in base[kind]) and len(set(new)) == len(new)
        assert all(re.fullmatch(rf"{key}\d{{6}}", i) for i in new)
    assert {p["id"] for p in base["people"]} < {p["id"] for p in small["people"]}


def test_the_years_end_on_the_samples_date(small: dict):
    base = {c["id"] for c in read_sample()["captures"]}
    days = sorted(c["at"][:10] for c in small["captures"] if c["id"] not in base)
    assert days[-1] <= SAMPLE_AS_OF.date().isoformat()
    assert days[0] >= small["scale"]["first"] >= "2025-10-01"


def test_its_content_is_made_up(small: dict):
    """Decision 474: example.com addresses, the made-up file server, and names from its own lists."""
    base = {p["id"] for p in read_sample()["people"]}
    for p in small["people"]:
        if p["id"] not in base:
            first, last = p["name"].split()
            assert first in sample_scale.FIRST and last in sample_scale.LAST
            assert p["email"].endswith("@example.com")
    text = "\n".join(c["content"] for c in small["captures"])
    assert set(re.findall(r"@([\w.]+)>", text)) <= {"example.com", *(f"{d}.example.com" for _, d in sample_scale.VENDORS)}
    for d in small["documents"]:
        assert "original" not in d or d["original"].startswith(("\\\\fileserver\\", "https://", "C:\\"))


def test_one_task_has_300_notes():
    data = add_years(read_sample(), 3, scale=0.2)
    busiest = data["scale"]["busiest"]
    assert sum(1 for c in data["captures"] if c.get("task") == busiest) >= sample_scale.BUSIEST_NOTES


def test_it_loads_with_its_emails_and_glossary(small: dict):
    conn = db.connect_memory()
    load_sample(conn, small)
    add_scale_extras(conn, small)
    m = Model(conn)
    emails = [c for c in m.captures.values() if c.source == "outlook_email" and c.emails]
    assert len(emails) == len(small["scale"]["emails"]) >= totals(1, SMALL)["emails"]
    assert all(e.file is None and e.conversation for c in emails for e in c.emails)
    assert conn.execute("SELECT count(*) FROM tagged_labels").fetchone()[0] == len(small["scale"]["glossary"])
    assert m.pages[small["scale"]["busiest"]]  # the notes pages are built from the captures, as the sample's are
    assert len(m.status) >= totals(1, SMALL)["status_log"]
    conn.close()


def test_load_sample_takes_years_from_1_to_10(capsys):
    for bad in ("0", "11", "two", "-1"):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["load-sample", "--years", bad])
    assert cli.build_parser().parse_args(["load-sample", "--years", "3"]).years == 3


def _files(root: Path) -> dict[str, int]:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file() and "Logs" not in p.parts}


def test_timing_changes_nothing_and_times_every_budget(sample_root):
    conn, root, _fs = sample_root
    conn.close()
    before = _files(root)
    found = timings.measure(root, Settings(me="P001"), SAMPLE_AS_OF, runs=1)
    assert [x.key for x in found] == [b.key for b in timings.BUDGETS]
    assert all(x.seconds >= 0 for x in found)
    assert _files(root) == before


def test_the_output_has_counts_and_times_and_no_content(sample_root):
    """Decision 472: never a title, a name or a word of content."""
    conn, root, _fs = sample_root
    m = Model(conn)
    conn.close()
    text = timings.report(root, timings.measure(root, Settings(me="P001"), SAMPLE_AS_OF, runs=1), SAMPLE_AS_OF, timings.counts(root))
    assert "| Loading the model |" in text and "| Tasks | 17 |" in text
    secrets = [t.title for t in m.tasks.values()] + [p.name for p in m.people.values() if p.name != "Me"]
    secrets += [c.title for c in m.captures.values()] + [d.name for d in m.documents.values()]
    secrets += [lb.name for lb in m.labels]
    for word in secrets:
        assert word not in text, word
    assert timings.DEFAULT_WORDS not in text


def test_the_counting_fs_writes_nothing_and_refuses_what_safe_fs_would(tmp_path: Path):
    fs = timings.CountingFS([tmp_path])
    fs.write_text(tmp_path / "a" / "page.md", "words")
    fs.makedirs(tmp_path / "b")
    assert fs.writes == 1 and list(tmp_path.iterdir()) == []
    with pytest.raises(WriteRefused):
        fs.write_text(tmp_path.parent / "outside.md", "words")


def test_the_command_prints_and_keeps_its_output(tmp_path: Path, capsys):
    root = tmp_path / "Root"
    assert cli.main(["--data-root", str(root), "init"]) == 0
    assert cli.main(["--data-root", str(root), "load-sample"]) == 0
    capsys.readouterr()
    code = cli.main(["--data-root", str(root), "timings", "--as-of", "2026-10-08"])
    out = capsys.readouterr().out
    assert code in (0, 2)
    assert "| The daily work |" in out and "Kept as System" in out
    kept = list((root / "System" / "diagnostics").glob("timings *.md"))
    assert len(kept) == 1 and "| rebuild |" in kept[0].read_text(encoding="utf-8")


def test_the_command_says_when_docs_db_is_at_another_schema(tmp_path: Path, capsys):
    root = tmp_path / "Root"
    assert cli.main(["--data-root", str(root), "init"]) == 0
    conn = sqlite3.connect(db.db_path(root))  # docs.db made older by hand
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION - 1}")
    conn.close()
    assert cli.main(["--data-root", str(root), "timings"]) == 1
    assert "Start DocRepo once" in capsys.readouterr().err


def test_the_scale_tests_run_only_when_asked_for():
    assert not asks_for_scale("", ["tests"])
    assert not asks_for_scale("not gui", [])
    assert asks_for_scale("scale", [])
    assert asks_for_scale("not gui and scale", [])
    assert asks_for_scale("", ["tests/test_scale.py::test_budget"])
    assert not asks_for_scale("not gui", ["tests/test_timings.py"])


def test_a_timing_reads_as_the_budgets_do():
    assert timings.duration(0.2124) == "212 ms"
    assert timings.duration(1.44) == "1.4 s"
    x = timings.Timing("model", 0.5)
    assert timings.verdict(x) == "Within twice" and not x.within
    assert timings.verdict(timings.Timing("model", 0.7)) == "Over"
    assert timings.verdict(timings.Timing("rebuild", 100.0)) == "Within"


def test_now_is_what_the_report_says(sample_root):
    conn, root, _fs = sample_root
    conn.close()
    when = datetime(2026, 11, 11, 9, 30)
    assert timings.report(root, [], when, []).startswith("# DocRepo timings, 2026-11-11 09:30")
