"""What-ifs on the Timeline page (release 5.64; decisions 226 to 228, 290 and 292): Take off, the drags, a whole parent, the
strip, the list, Undo and Review and apply, with no task changing until then. Driven offscreen."""
from __future__ import annotations

import json
import os
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from docrepo import capacity, db, load, tasks, whatif  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, Tie, load_tasks  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TODAY = NOW.date()
SETTINGS = Settings(me="P001")
WHO = "P004"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse()
    w.set_view("timeline")
    w.resize(1500, 950)
    QApplication.processEvents()
    yield w
    capture.deleteLater()
    w.deleteLater()


def make(browse, title: str, **values) -> str:
    values.setdefault("assignees", [WHO])
    values.setdefault("assignee_hours", 40)
    t = tasks.create_task(browse.ctx.conn, SETTINGS, title=title, at=NOW, created_by="Test", **values)
    return t


def trial(browse) -> tuple[str, str, str]:
    """A trial with two steps, the second tied to follow the first, shown open on the page."""
    top = make(browse, "Trial 7", assignees=[], assignee_hours=None)
    a = make(browse, "Set up the line", parents=[top], start="2026-10-19", due="2026-10-23")
    b = make(browse, "Run the trial", parents=[top], start="2026-10-26", due="2026-10-30")
    tasks.update_task(browse.ctx.conn, SETTINGS, b, at=NOW, via="Test", ties={"start": Tie(a, amount=1)})
    shown(browse)
    browse.timeline.set_open(top, True)
    return top, a, b


def shown(browse) -> None:
    browse.refresh()
    browse.set_view("timeline")
    QApplication.processEvents()


def real(browse, task_id: str):
    return load_tasks(browse.ctx.conn, [task_id])[task_id]


def hours_in(view, week: str) -> float:
    return load.week_hours(view.cells, WHO, date.fromisoformat(week))


def mouse(widget, kind: QEvent.Type, at: QPointF, buttons) -> None:
    QApplication.sendEvent(widget, QMouseEvent(kind, at, widget.mapToGlobal(at), Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))


def drag(widget, a: QPointF, b: QPointF) -> None:
    mouse(widget, QEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton)
    for i in range(1, 6):
        mouse(widget, QEvent.Type.MouseMove, a + (b - a) * (i / 5), Qt.MouseButton.LeftButton)
    mouse(widget, QEvent.Type.MouseButtonRelease, b, Qt.MouseButton.NoButton)
    QApplication.processEvents()


def row_top(view, task_id: str) -> int:
    top = view.chart.top_of(task_id)
    assert top is not None, task_id
    return top


def kept(browse) -> list:
    return json.loads(db.get_state(browse.ctx.conn, whatif.KEY) or "[]")


# ---- Take off (decision 227) ----
def test_take_off_starts_a_what_if_and_changes_no_task(browse):
    top, a, b = trial(browse)
    view = browse.timeline
    before = hours_in(view, "2026-10-19")
    view._pick(top)
    assert view.off_button.isVisible() and view.off_button.text() == "Remove"
    assert not view.whatif_strip.isVisible() and not view.whatif_button.isChecked()
    view.off_button.click()
    QApplication.processEvents()
    assert view.whatif_strip.isVisible() and view.whatif_button.isChecked() and view.whatif_name.text() == "What-if 1"
    assert "Trial 7 and 2 subtasks under it taken off, in a new what-if" in browse.status.text()
    assert real(browse, a).state == "Not started" and real(browse, b).state == "Not started"
    assert hours_in(view, "2026-10-19") == pytest.approx(before - 40)
    assert {a, b, top} <= view.chart.off and view.chart.top_of(a) is not None  # still rows, to put back
    assert view.off_button.text() == "Add back" and not view.quick_button.isVisible() and not view.update_button.isVisible()
    assert [w["name"] for w in kept(browse)] == ["What-if 1"]
    view.off_button.click()
    QApplication.processEvents()
    assert not view.chart.off and hours_in(view, "2026-10-19") == pytest.approx(before)


def test_the_sentence_and_team_chart_say_the_real_plan_beside_it(browse):
    big = make(browse, "Big job", start="2026-10-12", due="2026-10-16")
    capacity.rebuild_task(browse.ctx.conn, big, TODAY, SETTINGS)
    shown(browse)
    view = browse.timeline
    view.take_off(big)
    QApplication.processEvents()
    assert "on the real plan" in view.cap_say.text()
    assert view.cap_team.data.was is not None
    b = next(x for x in view.cap_team.data.buckets if x.holds(date(2026, 10, 12)))
    assert "On the real plan:" in view.cap_team.tip(b)


def test_the_spotlights_card_takes_a_task_off(browse):
    top, a, b = trial(browse)
    view = browse.timeline
    rows = view.cap_rows
    bucket = next(x for x in rows.data.buckets if x.holds(date(2026, 10, 19)))
    QTest.mouseClick(rows, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rows.cell_rect(rows.line_of(WHO), bucket).center().toPoint())
    QApplication.processEvents()
    links = [x for x in view.cap_card.findChildren(QLabel) if "off:" in x.text() and x.isVisibleTo(view.cap_card)]
    assert any(f'off:{a}"' in x.text() for x in links)
    view._card_link(f"off:{a}")
    QApplication.processEvents()
    assert view.cur is not None and a in view.chart.off and real(browse, a).state == "Not started"


# ---- the drags (decisions 227 and 290) ----
def test_a_bar_drags_in_a_what_if_without_plan_mode_and_leaves_an_outline(browse):
    top, a, b = trial(browse)
    view = browse.timeline
    view._new_whatif("Later")
    QApplication.processEvents()
    assert not view.plan and not view.plan_button.isVisible() and view.chart.plan
    bar = view.chart.bar_rect(next(r for r in view.chart.rows if r.task == a), row_top(view, a))
    week = view.scale.px_per_day(view.chart) * 7
    drag(view.chart, bar.center(), bar.center() + QPointF(week, 0))
    assert real(browse, a).start == "2026-10-19"  # nothing changed
    m = view.model
    assert m.task(a).start == "2026-10-26" and m.task(b).start == "2026-11-02"  # what's tied to it moves with it
    assert view.chart.was[a] == (date(2026, 10, 19), date(2026, 10, 23)) and b in view.chart.was
    assert "in this what-if. Your tasks haven't changed." in browse.status.text()
    view.undo_whatif()
    assert view.model.task(a).start == "2026-10-19" and not view.showing().actions


def test_a_whole_parent_drags_in_whole_weeks_with_everything_under_it(browse):
    top, a, b = trial(browse)
    view = browse.timeline
    view.set_open(top, False)
    view._new_whatif("Later")
    QApplication.processEvents()
    r = next(x for x in view.chart.rows if x.task == top)
    span = view.chart.span_rect(r, row_top(view, top))
    assert span is not None and view.chart._hit(span.center().x(), span.center().y())[1] == "parent"
    day = view.scale.px_per_day(view.chart)
    drag(view.chart, span.center(), span.center() + QPointF(day * 16, 0))  # two weeks and a bit: whole weeks only
    m = view.model
    assert (m.task(a).start, m.task(b).start, m.task(b).due) == ("2026-11-02", "2026-11-09", "2026-11-13")
    assert real(browse, a).start == "2026-10-19"
    assert view.showing().actions[0].kind == "parent" and view.showing().actions[0].weeks == 2


def test_neither_edit_nor_quick_edit_opens_in_a_what_if(browse):
    top, a, b = trial(browse)
    view = browse.timeline
    asked = []
    view.quick_edit.connect(lambda *x: asked.append(x))
    view.edit_task.connect(lambda *x: asked.append(x))
    view._new_whatif("x")
    QApplication.processEvents()
    bar = view.chart.bar_rect(next(r for r in view.chart.rows if r.task == a), row_top(view, a))
    QTest.mouseDClick(view.chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, bar.center().toPoint())
    QApplication.processEvents()
    assert not asked and "Edit task changes the task itself, so it isn't offered in a what-if" in browse.status.text()
    QTest.keyClick(view.chart, Qt.Key.Key_Q)
    QApplication.processEvents()
    assert not asked and "Quick edit changes the task itself" in browse.status.text()


def test_p_and_ctrl_z_work_on_the_what_if(browse):
    t = make(browse, "Big job", start="2026-10-12", due="2026-10-16")
    shown(browse)
    view = browse.timeline
    view.take_off(t)
    QApplication.processEvents()
    QTest.keyClick(view, Qt.Key.Key_P)
    assert not view.plan and "bars always drag" in browse.status.text()
    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not view.showing().actions and real(browse, t).state == "Not started"


# ---- the list (decision 228) ----
def test_what_ifs_are_named_flipped_between_and_kept(browse):
    t = make(browse, "Big job", start="2026-10-12", due="2026-10-16")
    shown(browse)
    view = browse.timeline
    view._open_whatifs()
    view.whatif_new.setText("Drop the big job")
    QTest.keyClick(view.whatif_new, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert view.showing().name == "Drop the big job"
    view.take_off(t)
    view.show_whatif(None)
    QApplication.processEvents()
    assert not view.whatif_strip.isVisible() and not view.chart.off and view.plan_button.isVisible()
    view.show_whatif(view.whatifs[0].id)
    assert t in view.chart.off
    view.whatif_name.setText("No big job")
    view.whatif_name.editingFinished.emit()
    assert kept(browse)[0]["name"] == "No big job"
    # DocRepo starts on the real plan, with the what-ifs still there.
    again = BrowseWindow(browse.ctx, browse.capture)
    assert again.timeline.cur is None and [w.name for w in again.timeline.whatifs] == ["No big job"]
    again.deleteLater()


def test_deleting_a_what_if_with_changes_asks_first(browse):
    t = make(browse, "Big job", start="2026-10-12", due="2026-10-16")
    shown(browse)
    view = browse.timeline
    view.take_off(t)
    asked = []
    view.confirm = lambda title, words: asked.append((title, words)) or False
    view._delete_whatif(view.cur)
    assert asked == [("Delete What-if 1", "Its 1 change go with it. Your tasks never changed.")] and view.whatifs
    view.confirm = lambda title, words: True
    view._delete_whatif(view.cur)
    assert not view.whatifs and view.cur is None and kept(browse) == []


# ---- Review and apply (decision 226) ----
def test_review_and_apply_makes_the_ticked_changes_and_the_what_if_goes(browse):
    top, a, b = trial(browse)
    other = make(browse, "Big job", start="2026-10-12", due="2026-10-16")
    shown(browse)
    view = browse.timeline
    view.take_off(other)
    view._dropped(a, date(2026, 10, 26), date(2026, 10, 30), "move")
    picked = {}

    def answer(dialog) -> bool:
        picked["titles"] = [e.title for e in dialog.entries]
        dialog.ticks["0"].setChecked(False)  # leave the big job on
        picked["button"] = dialog.commit_button.text()
        return True

    browse.run_dialog = answer
    view.review()
    QApplication.processEvents()
    assert picked == {"titles": ["Big job", "Set up the line"], "button": "Apply 1 change"}
    assert real(browse, a).start == "2026-10-26" and real(browse, b).start == "2026-11-02" and real(browse, other).state == "Not started"
    assert not view.whatifs and view.cur is None and not view.whatif_strip.isVisible() and kept(browse) == []
    assert "Applied 1 change from What-if 1" in browse.status.text()
    via = [r["via"] for r in browse.ctx.conn.execute("SELECT via FROM status_log WHERE task = ? AND field = 'Start' ORDER BY id", (a,))]
    assert via[-1] == "What-if: What-if 1"


def test_a_change_out_of_date_is_said_and_left_out(browse):
    t = make(browse, "Big job", start="2026-10-12", due="2026-10-16")
    shown(browse)
    view = browse.timeline
    view._new_whatif("x")
    view._dropped(t, date(2026, 10, 19), date(2026, 10, 23), "move")
    tasks.update_task(browse.ctx.conn, SETTINGS, t, at=NOW, via="Test", due="2026-10-20")
    shown(browse)
    assert "1 out of date" in view.whatif_facts.text()
    seen = {}

    def answer(dialog) -> bool:
        tick = dialog.ticks["0"]
        seen["tick"] = (tick.isChecked(), tick.isEnabled())
        seen["lines"] = dialog._lines["0"].text()
        return False

    browse.run_dialog = answer
    view.review()
    assert seen["tick"] == (False, False) and "Big job has changed since, so this is left out." in seen["lines"]
    assert view.whatifs  # kept as a what-if


def test_the_classic_look_has_no_what_ifs(qapp, sample_root):
    from docrepo.ui.look import configure

    conn, root, fs = sample_root
    configure("classic", False)
    try:
        ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
        capture = CaptureWindow(ctx)
        w = BrowseWindow(ctx, capture)
        w.set_view("timeline")
        assert not hasattr(w.timeline, "whatif_button") and w.timeline.cur is None
        capture.deleteLater()
        w.deleteLater()
    finally:
        configure("new", False)


def test_a_picture_is_worked_out_once_for_each_change(browse, monkeypatch):
    t = make(browse, "Big job", start="2026-10-12", due="2026-10-16")
    shown(browse)
    view = browse.timeline
    view.take_off(t)
    calls = []
    real_picture = whatif.picture
    monkeypatch.setattr(whatif, "picture", lambda *a, **k: calls.append(1) or real_picture(*a, **k))
    view._pick(t)
    view.set_open(t, False)
    view.shift(1)
    assert calls == []
    view._dropped(t, date(2026, 10, 19), date(2026, 10, 23), "move")
    assert calls == [1]
    assert Model(browse.ctx.conn).task(t).start == "2026-10-12"
