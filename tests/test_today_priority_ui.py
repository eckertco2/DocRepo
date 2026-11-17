"""Today in priority order (release 5.154, the design workspace's ``docs/mods/today-priority-plan.md``, decisions 688 to
694), driven offscreen over the sample data: the band headings in the view and the widened panel, a drop line only within
a band, the bins a task's drag opens and a drop on one, none for a note, and the width widened dragged, kept and reset."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import capacity, db, edits, hotkey, panel_rules, priorities, prompts  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import today_bins, today_panel  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, MOVE_ROLE  # noqa: E402

from test_today_order_ui import OwnDrop, OwnMove, drag_to, panel_row, rows_in_order, row_drop, row_mime, show_today, today_row, wide  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
MONDAY = datetime(2026, 10, 5, 9, 0)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app(qapp, data_root, fs, monkeypatch):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, now=lambda: NOW)
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    monkeypatch.setattr(today_panel, "_full_screen_candidates", lambda own: [])
    a = CaptureApp(qapp, ctx)
    yield a
    if a.panel is not None:
        a.panel.close_panel()
        a.panel.deleteLater()
    for w in (a.wheels.window, a.window, a.browse):
        w.hide()
    a.tray.hide()
    qapp.removeNativeEventFilter(a.filter)
    conn.close()


@pytest.fixture
def panel(app):
    app.today_panel_action("open")
    panel = app.panel
    panel._check_full_screen()
    assert panel.isVisible()
    return panel


def put(app) -> dict[str, int]:
    """Four made-up items: Rigging plan ranked High, the alignment contractor not ranked and carried from Monday, a note, and
    the guard drawings Medium. Their numbers by name."""
    c = app.ctx
    priorities.place(c.conn, "T000012", "high", None, at=NOW, via=priorities.VIA)
    priorities.place(c.conn, "T000018", "medium", None, at=NOW, via=priorities.VIA)
    plain = edits.add_to_today(c.conn, c.data_root, c.fs, "T000019", "", MONDAY)
    edits.add_to_today(c.conn, c.data_root, c.fs, None, "Sign the overtime sheets", NOW)
    edits.add_to_today(c.conn, c.data_root, c.fs, "T000012", "", NOW)
    edits.add_to_today(c.conn, c.data_root, c.fs, "T000018", "", NOW)
    app.browse.refresh(render=False)
    if app.panel is not None:
        app.panel.refresh()
    del plain
    m = Model(c.conn)
    by = {a.subject or "note": a.id for a in m.today_items()}
    return {"high": by["T000012"], "medium": by["T000018"], "plain": by["T000019"], "note": by["note"]}


def order(app, mine: dict[str, int]) -> list[str]:
    names = {v: k for k, v in mine.items()}
    return [names[a.id] for a in Model(app.ctx.conn).today_items() if a.id in names]


# ---- the Today view ----
def test_the_view_shows_todays_bands_under_today(app):
    i = put(app)
    browse = show_today(app)
    tree = browse.tree
    heads = [tree.topLevelItem(n) for n in range(tree.topLevelItemCount())]
    today = next(h for h in heads if h.data(0, HTML_ROLE) == "<b>Today</b>")
    kids = [today.child(n) for n in range(today.childCount())]
    words = [str(k.data(0, HTML_ROLE)) for k in kids if k.data(0, MOVE_ROLE) is None]
    assert [w.split(">")[1].split("<")[0] for w in words] == ["High", "Medium", "Not ranked"]  # decision 688
    assert rows_in_order(tree)[-4:] == [i["high"], i["medium"], i["plain"], i["note"]]
    assert order(app, i) == ["high", "medium", "plain", "note"]


def test_a_drag_in_the_view_lands_only_in_its_band(app):
    i = put(app)
    browse = show_today(app)
    row_drop(browse, i["note"], i["high"], "before")  # Not ranked onto High: refused (decision 689)
    assert order(app, i) == ["high", "medium", "plain", "note"]
    row_drop(browse, i["note"], i["plain"], "before")
    assert order(app, i) == ["high", "medium", "note", "plain"]


def bin_point(bins: today_bins.Bins, band: str) -> QPoint:
    rect = dict(bins.rects())[band]
    return bins.mapTo(bins.parentWidget(), rect.center())


def test_a_tasks_drag_opens_the_bins_and_a_drop_sets_its_priority(app):
    i = put(app)
    browse = show_today(app)
    tree = browse.tree
    assert browse._today_bins_for(("today", i["note"])) is None  # a note's drag opens none (decision 692)
    own, counts = browse._today_bins_for(("today", i["plain"]))
    assert own == "" and counts == {"critical": 0, "high": 1, "medium": 1, "": 2, "parking": 0}
    tree.setCurrentItem(today_row(tree, i["plain"]))
    tree._bins.open_for(own, counts, tree.viewport().rect())
    assert tree._bins.isVisible() and tree._bins.width() == today_bins.VIEW_WIDTH
    at = bin_point(tree._bins, own)  # its own bin takes nothing
    move = OwnMove(tree, at, Qt.DropAction.MoveAction, QMimeData(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tree.dragMoveEvent(move)
    assert not move.isAccepted() and tree._bins.hot is None
    at = bin_point(tree._bins, "critical")
    move = OwnMove(tree, at, Qt.DropAction.MoveAction, QMimeData(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tree.dragMoveEvent(move)
    assert move.isAccepted() and tree._bins.hot == "critical"
    drop = OwnDrop(tree, QPointF(at), Qt.DropAction.MoveAction, QMimeData(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tree.dropEvent(drop)
    assert drop.dropAction() == Qt.DropAction.IgnoreAction  # Qt moves no row: the records change
    tree._bins.close_bins()
    QApplication.processEvents()
    m = Model(app.ctx.conn)
    assert m.task("T000019").priority == "critical" and order(app, i)[0] == "plain"  # decision 691
    assert "Book the alignment contractor: Critical." in browse.status.text()
    assert tree.currentItem() is today_row(browse.tree, i["plain"])


def test_other_views_have_no_bins(app):
    put(app)
    browse = show_today(app)
    assert browse.tree._bin_hooks is not None
    app.show_browse("tasks")
    browse.refresh()
    QApplication.processEvents()
    assert browse.tree._bin_hooks is None


# ---- the Today side panel, widened ----
def test_the_widened_panel_names_its_bands(app, panel):
    put(app)
    panel.hover.contract()
    panel.refresh()
    bands = [w for w in panel.extras if w.objectName() == "tpBand"]
    assert [b.text().split("  ")[0] for b in bands] == ["HIGH", "MEDIUM", "NOT RANKED"] and not any(b.isVisibleTo(panel) for b in bands)
    wide(panel)
    bands = [w for w in panel.extras if w.objectName() == "tpBand"]
    assert all(b.isVisibleTo(panel) for b in bands)
    i = {r.task_id or "note": r for r in panel.rows}
    assert [r.band for r in panel.rows] == ["high", "medium", "", ""] and i["T000019"].band == ""


def test_the_panels_line_shows_only_within_its_band(app, panel, monkeypatch):
    i = put(app)
    wide(panel)
    seen: list = []
    monkeypatch.setattr(panel, "run_drag", drag_to(panel, panel_row(panel, i["high"]), "before", seen))
    panel.start_row_drag(panel_row(panel, i["note"]))
    assert seen[0][1] is False and order(app, i) == ["high", "medium", "plain", "note"]
    seen.clear()
    monkeypatch.setattr(panel, "run_drag", drag_to(panel, panel_row(panel, i["plain"]), "before", seen))
    panel.start_row_drag(panel_row(panel, i["note"]))
    assert seen[0][1] is True and order(app, i) == ["high", "medium", "note", "plain"]
    lines = {name: tip for name, _do, tip in panel._move_lines(panel_row(panel, i["plain"]))}
    assert set(lines) == {"Move to top"} and "in Not ranked" in lines["Move to top"]


def drop_on_bin(panel, band: str, seen: list):
    """Stands in for the drag's run: the row's own drag over the panel's bins, onto ``band``'s, then dropped."""
    def run(drag):
        mime = drag.mimeData()
        bins = panel.bins
        seen.append((bins.isVisible(), bins.own, dict(bins.counts)))
        at = bin_point(bins, band)
        move, buttons, keys = Qt.DropAction.MoveAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        QApplication.sendEvent(panel, QDragEnterEvent(at, move, mime, buttons, keys))
        over = QDragMoveEvent(at, move, mime, buttons, keys)
        QApplication.sendEvent(panel, over)
        seen.append((over.isAccepted(), bins.hot, panel.row_line.isVisible()))
        QApplication.sendEvent(panel, QDropEvent(QPointF(at), move, mime, buttons, keys))
    return run


def test_a_tasks_drag_in_the_panel_opens_the_bins_and_a_drop_sets_its_priority(app, panel, monkeypatch):
    i = put(app)
    wide(panel)
    seen: list = []
    monkeypatch.setattr(panel, "run_drag", drop_on_bin(panel, "high", seen))
    panel.start_row_drag(panel_row(panel, i["plain"]))
    (shown, own, counts), (accepted, hot, line) = seen
    assert shown and own == "" and counts["high"] == 1 and counts[""] == 2  # decision 690
    assert accepted and hot == "high" and not line
    assert not panel.bins.isVisible()  # closed once the drag is over
    assert Model(app.ctx.conn).task("T000019").priority == "high" and order(app, i) == ["high", "plain", "medium", "note"]
    assert panel.note_label.text() == "Book the alignment contractor: High. Its status log says so."
    assert panel.rows[panel.cursor].item_id == i["plain"]


def test_a_notes_drag_in_the_panel_opens_no_bins(app, panel, monkeypatch):
    i = put(app)
    wide(panel)
    seen: list = []
    monkeypatch.setattr(panel, "run_drag", lambda drag: seen.append(panel.bins is not None and panel.bins.isVisible()))
    panel.start_row_drag(panel_row(panel, i["note"]))
    assert seen == [False]


def test_a_file_over_the_panel_still_isnt_a_bin(app, panel):
    put(app)
    wide(panel)
    assert panel.bins is None or not panel.bins.isVisible()
    mime = row_mime(999)  # a row's format, but no row of the panel's is being dragged
    at = QPoint(20, 120)
    over = QDragMoveEvent(at, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel, over)
    assert not over.isAccepted()


# ---- a faster drop (release 5.159, the design workspace's docs/mods/bin-drop-speed-plan.md, decision 730) ----
def counted(monkeypatch, owner, names: tuple[str, ...], calls: list[str]) -> None:
    """Each of ``owner``'s methods ``names`` noted in ``calls`` when it's called, and run as it was."""
    for name in names:
        was = getattr(owner, name)
        monkeypatch.setattr(owner, name, lambda *a, _was=was, _name=name, **k: (calls.append(_name), _was(*a, **k))[1])


def model_loads(monkeypatch) -> list[int]:
    """Each Model read from docs.db from now on."""
    import docrepo.model as model_module

    loads: list[int] = []
    init = model_module.Model.__init__
    monkeypatch.setattr(model_module.Model, "__init__", lambda self, conn: (loads.append(1), init(self, conn))[1])
    return loads


def test_a_drop_draws_the_panel_once_and_reads_docs_db_once(app, panel, monkeypatch):
    """With the browse tool hidden: the panel drawn once, the browse tool not drawn till it's shown, and the one Model the
    drop read after its change kept for both, so no window reads every table again."""
    i = put(app)
    wide(panel)
    app.browse.hide()
    calls: list[str] = []
    counted(monkeypatch, panel, ("refresh",), calls)
    counted(monkeypatch, app.browse, ("render_nav", "render_list", "render_detail"), calls)
    loads = model_loads(monkeypatch)
    monkeypatch.setattr(panel, "run_drag", drop_on_bin(panel, "high", []))
    panel.start_row_drag(panel_row(panel, i["plain"]))
    assert calls == ["refresh"] and len(loads) == 1 and app.browse.dirty
    assert order(app, i) == ["high", "plain", "medium", "note"]  # the end of High, as before (decision 691)
    assert panel.note_label.text() == "Book the alignment contractor: High. Its status log says so."
    assert panel.rows[panel.cursor].item_id == i["plain"]  # the keyboard still on it
    assert [r.item_id for r in panel.rows] == [i["high"], i["plain"], i["medium"], i["note"]]
    assert "Book the alignment contractor: High." in app.browse.status.text()
    browse = show_today(app)  # drawn once it's shown, with the drop in it
    assert rows_in_order(browse.tree)[-4:] == [i["high"], i["plain"], i["medium"], i["note"]] and not browse.dirty


def test_a_drop_with_the_browse_tool_showing_draws_its_list_and_page_not_its_counts(app, panel, monkeypatch):
    """No view's count follows a priority, so the views pane, whose counts take longest, isn't drawn again."""
    i = put(app)
    wide(panel)
    browse = show_today(app)
    calls: list[str] = []
    counted(monkeypatch, panel, ("refresh",), calls)
    counted(monkeypatch, browse, ("render_nav", "render_list", "render_detail"), calls)
    monkeypatch.setattr(panel, "run_drag", drop_on_bin(panel, "critical", []))
    panel.start_row_drag(panel_row(panel, i["plain"]))
    assert calls == ["render_list", "render_detail", "refresh"]
    assert rows_in_order(browse.tree)[-4:] == [i["plain"], i["high"], i["medium"], i["note"]]
    assert [r.item_id for r in panel.rows] == [i["plain"], i["high"], i["medium"], i["note"]]


def test_a_move_in_a_band_draws_the_panel_once(app, panel, monkeypatch):
    i = put(app)
    wide(panel)
    calls: list[str] = []
    counted(monkeypatch, panel, ("refresh",), calls)
    monkeypatch.setattr(panel, "run_drag", drag_to(panel, panel_row(panel, i["plain"]), "before", []))
    panel.start_row_drag(panel_row(panel, i["note"]))
    assert calls == ["refresh"] and order(app, i) == ["high", "medium", "note", "plain"]


def test_a_board_move_reads_docs_db_once_and_leaves_the_counts(app, panel, monkeypatch):
    put(app)
    app.show_browse("priorities")
    browse = app.browse
    browse.refresh()
    QApplication.processEvents()
    calls: list[str] = []
    counted(monkeypatch, browse, ("render_nav", "render_list", "render_detail"), calls)
    loads = model_loads(monkeypatch)
    browse.move_priority("T000019", "critical", None)
    assert calls == ["render_list", "render_detail"] and len(loads) == 1
    assert Model(app.ctx.conn).task("T000019").priority == "critical" and browse.sel == ("task", "T000019")
    assert "Book the alignment contractor: Critical. Its status log says so." in browse.status.text()
    assert "T000019" in next(col.ids for col in browse.priorities.columns if col.key == "critical")  # the board drawn again


def test_a_model_is_kept_only_while_docs_db_is_as_it_read_it(app):
    """``AppContext.keep``: a Model read before a later write, or inside a transaction, isn't kept."""
    c = app.ctx
    edits.add_to_today(c.conn, c.data_root, c.fs, "T000019", "", NOW)
    fresh = Model(c.conn)
    assert c.keep(fresh) and c.model() is fresh
    stale = Model(c.conn)
    priorities.place(c.conn, "T000012", "high", None, at=NOW, via=priorities.VIA)
    assert not c.keep(stale) and c.model() is not stale and c.model().task("T000012").priority == "high"
    c.conn.execute("BEGIN")
    try:
        inside = Model(c.conn)
        assert inside.read_at is None and not c.keep(inside)
    finally:
        c.conn.execute("ROLLBACK")
    assert not c.keep(None)
    other = db.connect_memory()  # another connection's Model, however its counts fall
    try:
        load_sample(other)
        assert not c.keep(Model(other))
    finally:
        other.close()


# ---- the width widened (decision 694) ----
def test_the_grip_drags_the_width_widened_and_its_kept(app, panel):
    put(app)
    wide(panel)
    panel._update_state()
    assert panel.grip.isVisibleTo(panel) and "widens to" in panel.grip.toolTip()
    side = panel.place_.side
    dx = 100 if side == "left" else -100
    panel.size_edge(panel.wide_width(), dx)
    assert panel.target_width() == 420 and panel.geometry().width() == 420
    panel.keep_edge()
    assert db.get_state(app.ctx.conn, panel_rules.WIDE_WIDTH_KEY) == "420"
    assert db.get_state(app.ctx.conn, panel_rules.REST_WIDTH_KEY) in (None, "")  # the width at rest untouched
    again = today_panel.TodayPanel(app.ctx, app.browse, app.wheels)  # as after a restart
    try:
        assert again.wide_width() == 420
    finally:
        again.drop_cover.release()
        again.deleteLater()
    panel.hover.contract()
    panel._update_state()
    assert panel.target_width() == 180  # at rest as before
    panel.reset_wide()
    assert panel.wide_width() == 320 and not db.get_state(app.ctx.conn, panel_rules.WIDE_WIDTH_KEY)


def test_a_task_page_in_the_panel_is_at_least_as_wide(app, panel):
    i = put(app)
    panel._wide = "500"
    panel.open_detail(i["high"])
    assert panel.target_width() == 500
    panel._wide = None
    assert panel.target_width() == 420  # the config's detail_width when that's wider


def test_the_width_at_rest_stays_under_the_width_widened(app, panel):
    panel._wide = "300"
    panel.size_rest(180, 5000 if panel.place_.side == "left" else -5000)
    assert panel.rest_width() == 300


def test_the_grip_dragged_while_widened_keeps_it_wide(app, panel):
    clock = [0]
    panel.clock = lambda: clock[0]
    put(app)
    wide(panel)
    panel.on_grip(True)  # widened, the pointer on the grip is on the panel
    panel.grip._from = 0  # a drag of the grip under way
    panel.hover.pointer_out(clock[0])
    clock[0] = 10_000
    panel._hover_tick()
    assert panel.hover.wide
    panel.grip._from = None
