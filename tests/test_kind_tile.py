"""The kind on the tile (release 5.168, the design workspace's docs/mods/collections-and-kinds-plan.md, decision 786): one
recipe, ``task_tile.kind_mark``, for a parent's branches and a routine task's loop; a single task as quiet as it was; the
"↻ Weekly" chip's rhythm in the loop's words. Made-up sample data, no Qt."""
from __future__ import annotations

from datetime import date, datetime

from docrepo import kinds, task_tile, tasks, views
from docrepo.config import Settings
from docrepo.model import Model

TODAY = date(2026, 10, 8)
AT = datetime(2026, 10, 8, 9, 0)


def tile(conn, task_id: str) -> task_tile.Tile:
    m = Model(conn)
    return task_tile.tile(m, task_id, TODAY, task_tile.marks(m, TODAY))


def test_each_kind_has_its_mark_or_none(sample_conn):
    c = tasks.create_task(sample_conn, Settings(), title="Job aids", at=AT, created_by="test", collection=True)
    got = {x: (tile(sample_conn, x).kind, task_tile.kind_mark(tile(sample_conn, x))) for x in ("T000001", "T000006", "T000016", c)}
    assert got["T000001"][0] == kinds.PARENT and got["T000001"][1][0] == "kind-parent"
    assert got["T000006"][0] == kinds.ROUTINE and got["T000006"][1] == ("kind-routine", "Routine task: Monthly")
    assert got["T000016"] == (kinds.SINGLE, None) and got[c] == (kinds.COLLECTION, None)


def test_the_marks_words(sample_conn):
    m = Model(sample_conn)
    assert task_tile.kind_tip(m, m.task("T000001"), kinds.PARENT).startswith("Parent task: ")
    occ = tasks.create_task(sample_conn, Settings(), title="Business team meeting 13 Oct", at=AT, created_by="test", parents=["T000010"],
                            meeting=True, start="2026-10-13")
    t = tile(sample_conn, occ)
    assert t.kind == kinds.ROUTINE and t.kind_tip == "Routine task: an occurrence of Business team meeting"
    assert "Routine task: Monthly" in task_tile.tooltip(tile(sample_conn, "T000006"))
    assert "Routine" not in task_tile.tooltip(tile(sample_conn, "T000016"))


def test_a_page_tile_draws_the_same_mark(sample_conn):
    link = lambda href, text: f'<a href="{href}">{text}</a>'  # noqa: E731
    assert 'src="tm:kind-parent"' in task_tile.html(tile(sample_conn, "T000001"), link)
    assert 'src="tm:kind-routine"' in task_tile.html(tile(sample_conn, "T000006"), link)
    assert "tm:kind" not in task_tile.html(tile(sample_conn, "T000016"), link)


def test_the_chip_gives_way_where_the_mark_is(sample_conn):
    m = Model(sample_conn)
    assert ("↻ Monthly", "routine") in views.markers(m, m.task("T000006"))  # the Classic look keeps it
    assert ("↻ Monthly", "routine") not in views.markers(m, m.task("T000006"), routine=False)
