"""Quick edit (mods log round 4, M0067, item 55; release 5.30): its rules in ``docrepo.planning`` and its window."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from docrepo import planning, tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.parse import Who  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.quick_edit import QuickEdit  # noqa: E402

TODAY = date(2026, 10, 8)
NOW = datetime(2026, 10, 8, 14, 0)
SETTINGS = Settings(me="P001")
PLAN = "3 hours a week, Tom leads, Mike and Priya to help, due 20 Nov"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)


def _read(ctx, task_id: str, text: str, off=frozenset(), base: planning.Values | None = None) -> planning.Reading:
    m = ctx.model()
    t = m.task(task_id)
    return planning.read(text, base or planning.values_of(t), t, ctx.parse_people(m), TODAY, off=off)


# ---- the rules ----
def test_a_rate_becomes_a_total_over_the_task_s_start_to_due(ctx):
    # Draft monitoring plan runs Mon 12 Oct to Fri 23 Oct: two working weeks. Its assignee, Tom, gets the hours (143).
    r = _read(ctx, "T000011", "3 hours a week")
    assert r.fills == {"assignee_hours": 6.0}
    assert "3 h a week for 2 weeks" in r.chips[0].calc and r.chips[0].key == "assignee_hours"
    # A Due read from the box counts: 12 Oct to Fri 20 Nov is six working weeks.
    r = _read(ctx, "T000011", "3 hours a week, due 20 Nov")
    assert r.fills["due"] == "2026-11-20" and r.fills["assignee_hours"] == 18.0


def test_hours_that_name_no_role_go_to_the_assignees(ctx):
    r = _read(ctx, "T000011", PLAN)
    assert r.fills["leads"] == ["P003"] and r.fills["assignees"] == ["P004", "P002"]
    assert r.fills["assignee_hours"] == 18.0 and "lead_hours" not in r.fills
    assert [c.text() for c in r.chips] == ["Due: Fri 20 Nov", "Lead: Tom Becker", "Assignees: Mike Ortiz, Priya Shah", "Assignee hours: 18 h"]
    assert "as no role was named" in r.chips[-1].calc
    # Hours that name the lead stay the lead's.
    for text in ("lead hours 4, Mike to help", "4 hours as lead, Mike to help"):
        assert _read(ctx, "T000011", text).fills.get("lead_hours") == 4.0
    # With no assignees, read or already on the task, they stay where Parse and populate put them.
    assert _read(ctx, "T000002", "Tom leads, 5 hours").fills.get("lead_hours") == 5.0


def test_a_chip_unticked_leaves_its_field_as_it_was(ctx):
    m = ctx.model()
    base = planning.values_of(m.task("T000011"))
    r = _read(ctx, "T000011", PLAN, off={"due"})
    assert "due" not in r.fills and next(c for c in r.chips if c.key == "due").off
    shown = planning.shown(base, r)
    assert shown.due == "2026-10-23" and shown.assignees == ["P004", "P002"]
    # Unticked, the rate is worked over the task's own Due again.
    assert r.fills["assignee_hours"] == 6.0


def test_a_name_not_on_the_people_list_says_why(ctx):
    r = _read(ctx, "T000011", "@Sam to help")
    chip = next(c for c in r.chips if c.key == "assignees")
    assert chip.why.startswith("Not on the people list") and "assignees" not in r.fills


def test_the_total_and_about_a_week(ctx):
    t = ctx.model().task("T000011")
    v = planning.Values(start="2026-10-12", due="2026-11-20", leads=["P003"], assignees=["P004", "P002"], lead_hours=2, assignee_hours=18)
    assert planning.total_hours(v) == 38
    assert planning.total_text(v, t) == "38 h in all · about 6.3 h a week"
    assert planning.total_text(planning.Values(recurrence="Weekly", assignees=["P004"], assignee_hours=1.5), t) == "1.5 h each time"
    assert planning.total_text(planning.Values(), t).startswith("No hours yet")


def test_the_line_naming_a_plant_event(ctx):
    tasks.update_task(ctx.conn, SETTINGS, "T000008", at=NOW, via="Test", plant_event=True)  # Installation: 19 to 30 Oct
    m = ctx.model()
    v = planning.Values(start="2026-10-20", due="2026-11-20")
    assert planning.during(m, v, TODAY, "T000011").startswith("Start falls during Installation")
    assert planning.during(m, v, TODAY, "T000008") == ""  # a task's own event isn't counted


def test_problems_and_the_values_edit_task_takes():
    assert planning.problem(planning.Values(start="2026-10-20", due="2026-10-19")) == "Due is before Start."
    assert planning.problem(planning.Values(due="soon")) == "Due isn't a date. Use YYYY-MM-DD."
    assert planning.problem(planning.Values(start="2026-10-12", due="2026-10-12")) is None
    values = planning.edit_values(planning.Values(due="2026-11-20", leads=["P003"], assignee_hours=6.0, plant_event=True))
    assert values["start"] is None and values["due"] == "2026-11-20" and values["recurrence"] is None
    assert values["leads"] == [Who("P003")] and values["assignees"] == [] and values["assignee_hours"] == 6.0 and values["plant_event"]


# ---- the window ----
def _window(qapp, ctx, task_id: str = "T000011") -> QuickEdit:
    w = QuickEdit(ctx, task_id)
    w.show_near(QRect(100, 200, 120, 16))
    QApplication.processEvents()
    return w


def _chip(w: QuickEdit, start: str) -> QToolButton:
    return next(b for b in w.chips.findChildren(QToolButton) if b.isVisible() and b.text().startswith(start))


def test_typing_fills_the_fields_tinted_and_a_chip_unticks(qapp, ctx):
    w = _window(qapp, ctx)
    assert w.isVisible() and w.width() == 362 and w.box.hasFocus()
    QTest.keyClicks(w.box, PLAN)
    assert w.dates["due"].value() == "2026-11-20" and w.dates["due"].line.property("filled")
    assert w.hours["assignee_hours"].value() == 18.0 and w.hours["assignee_hours"].property("filled")
    assert w.rows["assignees"].ids == ["P004", "P002"] and w.rows["leads"].ids == ["P003"]
    assert w.total.text() == "38 h in all · about 6.3 h a week"  # the sample gives Draft monitoring plan's lead 2 h
    _chip(w, "Due:").click()
    QApplication.processEvents()
    assert w.dates["due"].value() == "2026-10-23" and not w.dates["due"].line.property("filled")
    assert _chip(w, "Due:").text().endswith("↺") and w.hours["assignee_hours"].value() == 6.0
    _chip(w, "Due:").click()
    QApplication.processEvents()
    assert w.dates["due"].value() == "2026-11-20"
    # A field changed by hand keeps its value, and the box no longer fills it.
    w.dates["due"].set_value("2026-11-27")
    w.dates["due"].edited.emit()
    QApplication.processEvents()
    assert w.values().due == "2026-11-27" and _chip(w, "Due:").text().endswith("↺")


def test_save_writes_and_logs_as_edit_task(qapp, ctx):
    w = _window(qapp, ctx)
    saved: list[str] = []
    w.saved.connect(saved.append)
    QTest.keyClicks(w.box, PLAN)
    w.plant_event.click()
    w.save()
    assert saved == ["T000011"] and not w.isVisible()
    t = Model(ctx.conn).task("T000011")
    assert (t.due, t.leads, t.assignees, t.assignee_hours, t.plant_event) == ("2026-11-20", ["P003"], ["P004", "P002"], 18.0, True)
    rows = ctx.conn.execute("SELECT field, via FROM status_log WHERE task = 'T000011' AND at = ?", ("2026-10-08 14:00:00",)).fetchall()
    assert {f for f, _ in rows} >= {"Due", "Assignees", "Assignee hours", "Plant event"} and {v for _, v in rows} == {"Browse tool"}


def test_esc_asks_once_and_due_before_start_is_refused(qapp, ctx):
    w = _window(qapp, ctx)
    w.escape()
    assert not w.isVisible()  # nothing changed: it just closes
    w = _window(qapp, ctx)
    w.dates["start"].set_value("2026-10-30")
    w.dates["start"].edited.emit()
    w.save()
    assert w.isVisible() and w.message.text() == "Due is before Start."
    assert Model(ctx.conn).task("T000011").start == "2026-10-12"
    w.escape()
    assert w.isVisible() and w.message.text() == "You've changed something. Esc again closes without saving."
    w.escape()
    assert not w.isVisible() and Model(ctx.conn).task("T000011").start == "2026-10-12"


def test_open_task_and_the_people_row(qapp, ctx):
    w = _window(qapp, ctx)
    asked: list[str] = []
    w.open_task.connect(asked.append)
    row = w.rows["leads"]
    names = [a.text() for a in row.add_menu.actions()]
    assert "Priya Shah" not in names and "Tom Becker" in names  # Priya is the lead already
    next(a for a in row.add_menu.actions() if a.text() == "Tom Becker").trigger()
    QApplication.processEvents()
    assert w.values().leads == ["P002", "P003"] and w.changed()
    w._open()
    assert asked == ["T000011"] and not w.isVisible()
