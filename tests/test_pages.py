"""The generated files against the mockup's examples.md: Task.md, Contents.md and capture.md."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from conftest import example_block

from docrepo import tasks
from docrepo.captures import capture_md
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.pages import Pages, rel_link, write_pages
from docrepo.sample import SAMPLE_AS_OF, read_sample

TODAY = SAMPLE_AS_OF.date()


@pytest.mark.parametrize("task_id", ["T000008", "T000010", "T000015"])
def test_task_page(sample_conn, task_id):
    model = Model(sample_conn)
    page = Pages(model, TODAY, SAMPLE_AS_OF).task_page(model.task(task_id))
    assert page == example_block(f"Tasks/{task_id}/Task.md")


def test_contents_page(sample_conn):
    assert Pages(Model(sample_conn), TODAY, SAMPLE_AS_OF).contents_page() == example_block("Contents.md")


@pytest.mark.parametrize("capture_id", ["C000020", "C000017", "C000014", "C000024", "C000003", "C000021"])
def test_capture_md(sample_conn, capture_id):
    content = {c["id"]: c["content"] for c in read_sample()["captures"]}[capture_id]
    assert capture_md(Model(sample_conn), capture_id, content) == example_block(f"Captures/{_folder(capture_id)}/capture.md")


def _folder(capture_id: str) -> str:
    saved = {c["id"]: c["at"] for c in read_sample()["captures"]}[capture_id]
    return f"{saved[:4]}/{saved[5:7]}/{capture_id}"


def test_capture_md_after_filing(sample_conn):
    sample_conn.execute("UPDATE captures SET filed_to = 'T000003', filed = '2026-10-08 14:05:00' WHERE id = 'C000021'")
    content = {c["id"]: c["content"] for c in read_sample()["captures"]}["C000021"]
    assert capture_md(Model(sample_conn), "C000021", content) == example_block("Captures/2026/10/C000021/capture.md, after filing")


def test_a_filed_capture_leaves_the_unfiled_list(sample_conn):
    sample_conn.execute("UPDATE captures SET filed_to = 'T000003', filed = '2026-10-08 14:05:00' WHERE id = 'C000021'")
    model = Model(sample_conn)
    assert [c.id for c in model.unfiled_captures()] == ["C000022", "C000023"]
    assert "C000021" in [e.capture.id for e in model.raw_log_of("T000003") if e.capture]


def test_relative_links():
    assert rel_link(["Tasks", "T000008"], ["Tasks", "T000001", "Task.md"]) == "../T000001/Task.md"
    assert rel_link(["Tasks", "T000008"], ["Captures", "2026", "10", "C000013", "capture.md"]) == "../../Captures/2026/10/C000013/capture.md"
    assert rel_link([], ["Tasks", "T000001", "Task.md"]) == "Tasks/T000001/Task.md"
    assert rel_link(["Tasks", "T1"], ["Tasks", "T1", "Files", "a (b).pdf"]) == "Files/a%20%28b%29.pdf"


def test_write_pages_skips_pages_whose_only_change_is_the_date(sample_conn, data_root, fs):
    model = Model(sample_conn)
    assert write_pages(model, data_root, fs, TODAY, SAMPLE_AS_OF) == len(model.tasks) + 1
    assert (data_root / "Tasks" / "T000008" / "Task.md").read_text(encoding="utf-8") == example_block("Tasks/T000008/Task.md")
    assert write_pages(model, data_root, fs, TODAY, datetime(2026, 10, 8, 9, 0)) == 0
    tasks.update_task(sample_conn, Settings(), "T000012", at=datetime(2026, 10, 8, 9, 5), via="Browse tool", current_status="Sling drawing done.")
    written = write_pages(Model(sample_conn), data_root, fs, TODAY, datetime(2026, 10, 8, 9, 5))
    assert written == 1  # T000012's page; its parent's subtasks table and Contents.md don't show the status
    assert "Sling drawing done." in (data_root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")


def test_titles_with_brackets_and_pipes_stay_readable(sample_conn):
    sample_conn.execute("UPDATE tasks SET title = 'Check [A|B] guards' WHERE id = 'T000012'")
    page = Pages(Model(sample_conn), TODAY, SAMPLE_AS_OF).task_page(Model(sample_conn).task("T000008"))
    assert "| T000012 | [Check \\[A\\|B\\] guards](../T000012/Task.md) |" in page


def test_days_until_due_on_the_page_follows_today(sample_conn):
    model = Model(sample_conn)
    page = Pages(model, date(2026, 11, 2), SAMPLE_AS_OF).task_page(model.task("T000008"))
    assert "| Due | 2026-10-30 (3 d overdue) |" in page
