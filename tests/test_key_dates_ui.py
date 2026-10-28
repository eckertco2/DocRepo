"""Key dates in the browse tool (release 5.31, the key dates plan, items 57, 59 and 61): Edit task's and Quick edit's rows,
the task page's block with its Done tick and Make it a subtask, and their rows on the Overdue list and Today."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import edits, tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import Pages, PageState  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.tasks import KeyDateRow  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_edit import QuickEdit  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE  # noqa: E402
from docrepo.views import view_counts  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)  # a Thursday
SETTINGS = Settings(me="P001")
TRIAL = [KeyDateRow("2026-10-01", None, "Trial planning period"),
         KeyDateRow(None, "2026-10-06", "Order the seals"),
         KeyDateRow(None, "2026-10-12", "Target for trial preparations", deadline=True),
         KeyDateRow("2026-12-01", "2026-12-05", "Trial execution window", plant=True)]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    QApplication.processEvents()
    capture.deleteLater()
    w.deleteLater()


def put(ctx, task_id: str = "T000008", rows=TRIAL) -> None:
    tasks.set_key_dates(ctx.conn, task_id, rows, at=NOW, via="Browse tool")


def key_rows(browse) -> list:
    """The tree's key date rows: those with the Key date chip."""
    return [it for it in browse.tree.items() if "Key date" in (it.data(1, HTML_ROLE) or "")]


# ---- Edit task (item 57) ----
def test_edit_task_adds_changes_orders_and_refuses_key_dates(browse, ctx):
    put(ctx, rows=TRIAL[:1])
    dialog = TaskEditDialog(browse, Model(ctx.conn), "T000008", browse._label_options, browse._people_options)
    editor = dialog.key_dates
    assert [line.desc.text() for line in editor.lines] == ["Trial planning period"] and not editor.empty.isVisibleTo(dialog)
    line = editor.add_row()
    line.desc.setText("Trial execution window")
    assert dialog.problem() == "Key date 2 needs a start, an end or both."
    line.start.set_value("2026-12-05")
    line.end.set_value("2026-12-01")
    assert dialog.problem() == "Key date 2 ends before it starts."
    line.end.line.setText("5 Decembre")
    assert dialog.problem() == "Key date 2's end isn't a date. Use YYYY-MM-DD."
    line.start.set_value("2026-12-01")
    line.end.set_value("2026-12-05")
    line.plant.setChecked(True)
    assert dialog.problem() is None
    editor.add_row()  # a new line left empty isn't saved
    editor._move(line, -1)  # the window first
    rows = dialog.values()["key_dates"]
    assert [(r.description, r.start, r.end, r.plant, r.id is None) for r in rows] == [
        ("Trial execution window", "2026-12-01", "2026-12-05", True, True), ("Trial planning period", "2026-10-01", None, False, False)]
    out = edits.edit_task(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, "T000008", NOW, **dialog.values())
    assert "change" in out.message
    assert [(kd.description, kd.pos) for kd in Model(ctx.conn).key_dates_of("T000008")] == [("Trial execution window", 0), ("Trial planning period", 1)]
    # Done and remove, in a fresh form; Edit selected isn't changed.
    dialog = TaskEditDialog(browse, Model(ctx.conn), "T000008", browse._label_options, browse._people_options)
    dialog.key_dates.lines[0].done.setChecked(True)
    dialog.key_dates._remove(dialog.key_dates.lines[1])
    edits.edit_task(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, "T000008", NOW, **dialog.values())
    kds = Model(ctx.conn).key_dates_of("T000008")
    assert [(kd.description, kd.done) for kd in kds] == [("Trial execution window", "2026-10-08")]


# ---- Quick edit (item 57) ----
def test_quick_edit_has_the_same_rows(ctx):
    put(ctx, rows=TRIAL[:1])
    qe = QuickEdit(ctx, "T000008")
    assert [line.desc.text() for line in qe.key_dates.lines] == ["Trial planning period"] and qe.key_dates.compact
    line = qe.key_dates.add_row()
    line.desc.setText("Crane booked")
    qe._key_dates_edited()
    qe.save()
    assert qe.message.text() == "Key date 2 needs a start, an end or both."
    line.end.set_value("2026-10-12")
    line.deadline.setChecked(True)
    qe._key_dates_edited()
    assert qe.changed()
    qe.save()
    kds = Model(ctx.conn).key_dates_of("T000008")
    assert [(kd.description, kd.end, kd.deadline) for kd in kds] == [("Trial planning period", None, False), ("Crane booked", "2026-10-12", True)]
    assert qe.width() == 352  # kept to the window's width


# ---- the task page (items 57 and 61) ----
def test_the_task_page_block_ticks_done_and_makes_a_subtask(browse, ctx):
    put(ctx)
    page = Pages(Model(ctx.conn), NOW.date(), lambda c: "", "P001", ctx.conn).task_page("T000008", PageState())
    assert "Key dates" in page and "Trial execution window" in page and "⚑ plant activity" in page and "Make\u00a0it\u00a0a\u00a0subtask" in page
    assert "by Mon 12 Oct" in page and "deadline" in page
    kds = Model(ctx.conn).key_dates_of("T000008")
    browse.on_link(QUrl(f"kd:done:{kds[2].id}"))
    assert Model(ctx.conn).key_dates_of("T000008")[2].done == "2026-10-08"
    page = Pages(Model(ctx.conn), NOW.date(), lambda c: "", "P001", ctx.conn).task_page("T000008", PageState())
    assert f"kd:undone:{kds[2].id}" in page and "done Thu 8 Oct" in page and "3 open" in page
    browse.on_link(QUrl(f"kd:undone:{kds[2].id}"))
    assert Model(ctx.conn).key_dates_of("T000008")[2].done is None
    browse.on_link(QUrl(f"kd:subtask:{kds[3].id}"))
    m = Model(ctx.conn)
    child = next(t for t in m.tasks.values() if t.title == "Trial execution window")
    assert m.parents_of(child.id) == ["T000008"] and child.plant_event and len(m.key_dates_of("T000008")) == 3


# ---- the Overdue and next 7 days list and Today (item 59, decisions 148 and 150) ----
def test_the_overdue_list_has_a_row_for_each_key_date_with_done(browse, ctx):
    before = view_counts(Model(ctx.conn), NOW.date(), "P001")["due"]
    put(ctx)
    assert view_counts(Model(ctx.conn), NOW.date(), "P001")["due"] == before + 2  # the overdue one and the one due in 4 days
    browse.refresh(render=False)  # written straight to docs.db, so the window reads it again
    browse.set_view("due")
    rows = key_rows(browse)
    assert [it.data(0, KEY_ROLE) for it in rows] == [("task", "T000008")] * 2
    assert "Order the seals, was due Tue 6 Oct" in rows[0].data(0, HTML_ROLE) and "#b0261e" in rows[0].data(2, HTML_ROLE)
    assert "Target for trial preparations, by Mon 12 Oct" in rows[1].data(0, HTML_ROLE)
    browse.tree.itemWidget(rows[0], 3).findChild(QPushButton).click()  # Done
    assert Model(ctx.conn).key_dates_of("T000008")[1].done == "2026-10-08"
    assert len(key_rows(browse)) == 1


def test_today_has_them_among_its_due_tasks_and_mine_only_filters_them(browse, ctx):
    put(ctx)
    put(ctx, "T000009", [KeyDateRow(None, "2026-10-09", "Vendor drawings back")])
    assert "P001" not in Model(ctx.conn).task("T000009").leads + Model(ctx.conn).task("T000009").assignees
    browse.refresh(render=False)
    browse.set_view("today")
    words = [it.data(0, HTML_ROLE) for it in key_rows(browse)]
    assert len(words) == 3 and "Vendor drawings back" in " ".join(words)
    browse.set_today_mine(True)
    assert len(key_rows(browse)) == 2
    browse.set_today_mine(False)
    first = key_rows(browse)[0]
    browse.tree.itemWidget(first, 3).findChild(QPushButton).click()
    assert len(key_rows(browse)) == 2
