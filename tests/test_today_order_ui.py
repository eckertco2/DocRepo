"""Today in the owner's order (release 5.148, the design workspace's ``docs/mods/today-order-plan.md``, decisions 643 to 648),
driven offscreen over the sample data: a row dragged in the Today view and in the widened side panel, the line where it
lands, Alt+Up and Alt+Down, Move to top and Move to bottom, and a file still dropped on a task's row."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import capacity, db, edits, hotkey, prompts  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import today_panel  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import ACTIONS_ROLE, HTML_ROLE, KEY_ROLE, LINE_ROLE, MOVE_ROLE  # noqa: E402

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


def put(app) -> list[int]:
    """Three made-up items: a task carried over from Monday, then a note and a task added today. Their numbers, in order."""
    c = app.ctx
    edits.add_to_today(c.conn, c.data_root, c.fs, "T000012", "", MONDAY)
    edits.add_to_today(c.conn, c.data_root, c.fs, None, "Sign the overtime sheets", NOW)
    edits.add_to_today(c.conn, c.data_root, c.fs, "T000008", "", NOW)
    app.browse.refresh(render=False)
    if app.panel is not None:
        app.panel.refresh()
    return [a.id for a in Model(c.conn).today_items()][-3:]


def order(app, mine: list[int]) -> list[int]:
    """Today's order of these items (anything else on Today left out)."""
    return [a.id for a in Model(app.ctx.conn).today_items() if a.id in mine]


def show_today(app):
    app.show_browse("today")
    app.browse.refresh()
    QApplication.processEvents()
    return app.browse


def today_row(tree, item_id: int):
    return next(r for r in tree.items() if r.data(0, MOVE_ROLE) == ("today", item_id))


def rows_in_order(tree) -> list[int]:
    return [r.data(0, MOVE_ROLE)[1] for r in tree.items() if r.data(0, MOVE_ROLE) is not None]


class OwnDrop(QDropEvent):
    """A drop whose drag began in ``source``, as a row's own drag does: Qt's events made by hand have no source."""

    def __init__(self, source, *args):
        super().__init__(*args)
        self._source = source

    def source(self):  # noqa: D102 - Qt's
        return self._source


class OwnMove(QDragMoveEvent):
    def __init__(self, source, *args):
        super().__init__(*args)
        self._source = source

    def source(self):  # noqa: D102 - Qt's
        return self._source


def edge(tree, item, where: str) -> QPoint:
    rect = tree.visualItemRect(item)
    y = {"before": rect.top() + 1, "after": rect.bottom() - 1, "upper": rect.center().y() - 2, "lower": rect.center().y() + 2}[where]
    return QPoint(rect.left() + 60, y)


def row_drop(browse, item_id: int, onto: int, where: str) -> OwnDrop:
    """A Today row picked and dragged within the view, dropped at a part of another row, and the tick that runs the move."""
    tree = browse.tree
    tree.setCurrentItem(today_row(tree, item_id))
    event = OwnDrop(tree, QPointF(edge(tree, today_row(tree, onto), where)), Qt.DropAction.MoveAction, QMimeData(),
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tree.dropEvent(event)
    QApplication.processEvents()
    return event


# ---- the Today view ----
def test_today_is_one_list_and_a_carried_row_keeps_its_since(app):
    carried, note, task = put(app)
    browse = show_today(app)
    heads = [browse.tree.topLevelItem(i) for i in range(browse.tree.topLevelItemCount())]
    words = [str(h.data(0, HTML_ROLE)) for h in heads]
    assert "<b>Today</b>" in words and not any("Carried over" in w or "Added today" in w for w in words)  # decision 644
    today = heads[words.index("<b>Today</b>")]
    moved = [today.child(i).data(0, MOVE_ROLE) for i in range(today.childCount())]
    assert [m for m in moved if m is not None][-3:] == [("today", carried), ("today", note), ("today", task)]  # heads aside (5.189)
    assert "since Mon" in today_row(browse.tree, carried).data(0, LINE_ROLE).html()


def test_a_row_dragged_in_the_view_lands_where_dropped_and_stays_selected(app):
    carried, note, task = put(app)
    browse = show_today(app)
    event = row_drop(browse, task, carried, "before")
    assert event.isAccepted() and order(app, [carried, note, task]) == [task, carried, note]  # decision 644: above Monday's
    assert rows_in_order(browse.tree)[-3:] == [task, carried, note]
    assert browse.tree.currentItem() is today_row(browse.tree, task)
    row_drop(browse, task, note, "lower")  # the middle of a row lands by its halves: Qt's line is between rows
    assert order(app, [carried, note, task]) == [carried, note, task]


def test_only_todays_rows_drag_and_nothing_lands_in_a_row(app):
    carried, note, task = put(app)
    browse = show_today(app)
    tree = browse.tree
    for item_id in (carried, note, task):
        flags = today_row(tree, item_id).flags()
        assert flags & Qt.ItemFlag.ItemIsDragEnabled and not flags & Qt.ItemFlag.ItemIsDropEnabled
    others = [r for r in tree.items() if r.data(0, MOVE_ROLE) is None]
    assert others and not any(r.flags() & Qt.ItemFlag.ItemIsDragEnabled for r in others)  # headings, Due, Done today
    tree.setCurrentItem(today_row(tree, task))
    heading = next(r for r in others if r.data(0, HTML_ROLE) == "<b>Today</b>")

    def hover(item, where) -> bool:
        event = OwnMove(tree, edge(tree, item, where), Qt.DropAction.MoveAction, QMimeData(), Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
        tree.dragMoveEvent(event)
        assert tree.showDropIndicator() == event.isAccepted()  # Qt's line only where a row can land
        return event.isAccepted()
    assert hover(today_row(tree, carried), "upper") and hover(today_row(tree, note), "after")
    assert not hover(heading, "upper") and not hover(today_row(tree, task), "upper")  # a heading, or onto itself
    for r in others:  # Due in the next 7 days, Done today and the rest take no Today row
        if r is not heading and r.data(0, KEY_ROLE) is not None:
            assert not hover(r, "before") and not hover(r, "upper")


def test_alt_up_and_alt_down_in_the_view(app):
    carried, note, task = put(app)
    browse = show_today(app)
    tree = browse.tree
    tree.setCurrentItem(today_row(tree, task))
    alt = Qt.KeyboardModifier.AltModifier
    QApplication.sendEvent(tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, alt))
    QApplication.processEvents()
    assert order(app, [carried, note, task]) == [carried, task, note]
    assert tree.currentItem() is today_row(tree, task)  # it stays selected, so Alt+Up can go on
    QApplication.sendEvent(tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, alt))
    assert order(app, [carried, note, task]) == [task, carried, note]
    tree.setCurrentItem(today_row(tree, note))  # a note moves too, by its item
    QApplication.sendEvent(tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, alt))
    assert order(app, [carried, note, task]) == [task, note, carried] and tree.currentItem() is today_row(tree, note)
    QApplication.sendEvent(tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, alt))
    assert order(app, [carried, note, task]) == [task, carried, note]


def test_move_to_top_and_bottom_on_the_right_click_menu(app):
    carried, note, task = put(app)
    browse = show_today(app)
    tree = browse.tree

    def lines(item_id) -> dict:
        menu = tree.row_menu(today_row(tree, item_id))
        found = {a.text(): a for a in menu.actions() if a.text().startswith("Move to")}
        return found
    first = rows_in_order(tree)[0]
    assert "Move to top" not in lines(first) and set(lines(note)) == {"Move to top", "Move to bottom"}
    assert "Move to bottom" not in lines(task) and "Move to top" in lines(task)  # a task's tile menu has them too
    lines(task)["Move to top"].trigger()
    QApplication.processEvents()
    assert rows_in_order(tree)[0] == task
    lines(task)["Move to bottom"].trigger()
    assert rows_in_order(tree)[-1] == task and order(app, [carried, note, task]) == [carried, note, task]
    assert all(label not in ("Move to top", "Move to bottom") for label, _, _ in today_row(tree, task).data(0, ACTIONS_ROLE).actions)  # no button


def _files(tmp_path) -> QMimeData:
    folder = tmp_path / "Inbox"
    folder.mkdir(exist_ok=True)
    path = folder / "Seal drawing.txt"
    path.write_text("Made up for the test", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def test_a_file_dropped_on_a_row_still_opens_an_update(app, tmp_path):
    carried, note, task = put(app)
    browse = show_today(app)
    tree = browse.tree
    at = tree.visualItemRect(today_row(tree, task)).center()
    copy, buttons, keys = Qt.DropAction.CopyAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    mime = _files(tmp_path)
    view = tree.viewport()
    enter = QDragEnterEvent(at, copy, mime, buttons, keys)
    QApplication.sendEvent(view, enter)
    move = QDragMoveEvent(at, copy, mime, buttons, keys)
    QApplication.sendEvent(view, move)
    drop = QDropEvent(QPointF(at), copy, mime, buttons, keys)
    QApplication.sendEvent(view, drop)
    QApplication.processEvents()
    assert enter.isAccepted() and move.isAccepted() and drop.isAccepted()  # decision 648: told apart by what's dragged
    w = app.window
    assert w.isVisible() and w.task == "T000008" and w.types == {"update"}
    assert order(app, [carried, note, task]) == [carried, note, task]


def test_a_row_dragged_onto_a_task_moves_it_and_opens_nothing(app):
    carried, note, task = put(app)
    browse = show_today(app)
    row_drop(browse, carried, task, "lower")
    assert order(app, [carried, note, task]) == [note, task, carried] and not app.window.isVisible()


# ---- the Today side panel, widened ----
@pytest.fixture
def panel(app):
    app.today_panel_action("open")
    panel = app.panel
    panel._check_full_screen()
    assert panel.isVisible()
    return panel


def wide(panel):
    panel.hover.open_wide()
    panel.refresh()
    QApplication.processEvents()


def panel_row(panel, item_id):
    return next(r for r in panel.rows if r.item_id == item_id)


def row_mime(item_id: int) -> QMimeData:
    mime = QMimeData()
    mime.setData(today_panel.ROW_MIME, QByteArray(str(item_id).encode("ascii")))
    return mime


def drag_to(panel, onto, where: str, seen: list):
    """Stands in for the drag's run: the row's own drag over the panel, to the top or bottom of ``onto``, then dropped."""
    def run(drag):
        mime = drag.mimeData()
        box = onto.geometry()
        y = box.top() + 2 if where == "before" else box.bottom() - 2
        at = panel.list_widget.mapTo(panel, QPoint(box.center().x(), y))
        move, buttons, keys = Qt.DropAction.MoveAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        enter = QDragEnterEvent(at, move, mime, buttons, keys)
        QApplication.sendEvent(panel, enter)
        over = QDragMoveEvent(at, move, mime, buttons, keys)
        QApplication.sendEvent(panel, over)
        seen.append((enter.isAccepted(), over.isAccepted(), panel.row_line.isVisible(), panel.row_line.geometry()))
        QApplication.sendEvent(panel, QDropEvent(QPointF(at), move, mime, buttons, keys))
    return run


def test_a_row_dragged_in_the_widened_panel(app, panel, monkeypatch):
    carried, note, task = put(app)
    wide(panel)
    assert panel.can_drag_rows()
    seen: list = []
    monkeypatch.setattr(panel, "run_drag", drag_to(panel, panel_row(panel, carried), "before", seen))
    panel.start_row_drag(panel_row(panel, task))
    (entered, over, line, box), = seen
    assert entered and over and line  # the line where it will land (decision 643)
    assert box.bottom() < panel_row(panel, note).geometry().top() + 4 or box.height() == 2
    assert order(app, [carried, note, task]) == [task, carried, note]
    assert [r.item_id for r in panel.rows][-3:] == [task, carried, note] and not panel.row_line.isVisible()
    browse = show_today(app)  # the same order in the view (decision 643)
    assert rows_in_order(browse.tree)[-3:] == [task, carried, note]


def test_a_row_drag_only_while_widened_and_off_itself(app, panel, monkeypatch):
    carried, note, task = put(app)
    panel.hover.contract()
    panel.refresh()
    started = []
    real = panel.start_row_drag
    monkeypatch.setattr(panel, "start_row_drag", lambda row: started.append(row.item_id))
    row = panel_row(panel, task)

    def press_and_move():
        centre = row.rect().center()
        g = row.mapToGlobal(centre)
        QApplication.sendEvent(row, QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(centre), QPointF(g), Qt.MouseButton.LeftButton,
                                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        far = centre + QPoint(0, 30)
        QApplication.sendEvent(row, QMouseEvent(QEvent.Type.MouseMove, QPointF(far), QPointF(row.mapToGlobal(far)), Qt.MouseButton.NoButton,
                                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    press_and_move()
    assert not panel.hover.wide and started == []  # at rest a click opens the detail, as before
    wide(panel)
    row = panel_row(panel, task)
    press_and_move()
    assert started == [task]
    seen: list = []
    monkeypatch.setattr(panel, "run_drag", drag_to(panel, panel_row(panel, task), "before", seen))
    real(panel_row(panel, task))
    assert seen[0][1] is False and order(app, [carried, note, task]) == [carried, note, task]  # onto itself: nothing


def test_a_file_dragged_over_the_panel_isnt_a_row_move(app, panel, tmp_path):
    carried, note, task = put(app)
    wide(panel)
    panel._moving = carried  # even during a row's drag, a file is a file (decision 648)
    try:
        assert panel._row_drag(QDragMoveEvent(QPoint(5, 5), Qt.DropAction.CopyAction, _files(tmp_path), Qt.MouseButton.LeftButton,
                                              Qt.KeyboardModifier.NoModifier)) is None
    finally:
        panel._moving = None
    assert panel._row_drag(QDragMoveEvent(QPoint(5, 5), Qt.DropAction.MoveAction, row_mime(carried), Qt.MouseButton.LeftButton,
                                          Qt.KeyboardModifier.NoModifier)) is None  # no row of its own being dragged


def test_alt_up_and_alt_down_in_the_panel(app, panel):
    carried, note, task = put(app)
    panel.take_keyboard()
    panel._move_cursor([r.item_id for r in panel.rows].index(task))
    alt = Qt.KeyboardModifier.AltModifier
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, alt))
    assert order(app, [carried, note, task]) == [carried, task, note] and panel.rows[panel.cursor].item_id == task
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, alt))
    assert order(app, [carried, note, task]) == [carried, note, task] and panel.rows[panel.cursor].item_id == task
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    assert panel.rows[panel.cursor].item_id == note and order(app, [carried, note, task]) == [carried, note, task]  # Up still moves the cursor


def test_move_to_top_and_bottom_on_the_panels_menus(app, panel, monkeypatch):
    carried, note, task = put(app)
    wide(panel)
    shown = []
    monkeypatch.setattr(panel, "run_menu", lambda menu, at: shown.append({a.text().split("\t")[0]: a for a in menu.actions()}))
    panel.row_menu(panel_row(panel, note), QPoint(0, 0))  # a note has a menu now: Today's own lines
    assert {"Done for today", "Remove from Today", "Move to top", "Move to bottom"} <= set(shown[-1])
    first = panel.rows[0]
    panel.row_menu(first, QPoint(0, 0))
    assert "Move to top" not in shown[-1] and "Move to bottom" in shown[-1]
    panel.row_menu(panel_row(panel, task), QPoint(0, 0))
    assert "Move to top" in shown[-1] and "Move to bottom" not in shown[-1] and "Work on it" in shown[-1]  # the tile's menu
    shown[-1]["Move to top"].trigger()
    assert panel.rows[0].item_id == task and Model(app.ctx.conn).today_items()[0].id == task
