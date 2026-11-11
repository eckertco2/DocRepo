"""The browse tool's Today view since release 5.115 (the design workspace's ``docs/mods/today-reminders-plan.md``): drops
on a task's row (decision 419), Done opening an Update, and Back on Today (decisions 420 and 421). Driven offscreen over the
sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import capacity, db, edits, hotkey, prompts  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import ACTIONS_ROLE, KEY_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


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
    a = CaptureApp(qapp, ctx)
    yield a
    for w in (a.wheels.window, a.window, a.browse):
        w.hide()
    a.tray.hide()
    qapp.removeNativeEventFilter(a.filter)
    conn.close()


def _today(app, *tasks, note=""):
    for t in tasks:
        edits.add_to_today(app.ctx.conn, app.ctx.data_root, app.ctx.fs, t, "", NOW)
    if note:
        edits.add_to_today(app.ctx.conn, app.ctx.data_root, app.ctx.fs, None, note, NOW)
    app.show_browse("today")
    app.browse.refresh()
    return app.browse


def _row(tree, key):
    found = []

    def walk(item):
        if item.data(0, KEY_ROLE) == key:
            found.append(item)
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return found[0]


def _file(tmp_path, name="Seal drawing.txt"):
    folder = tmp_path / "Inbox"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text("Made up for the test", encoding="utf-8")
    return path


def _drop(tree, mime, at: QPoint):
    """A drag coming over the tree's rows, moved to ``at`` (viewport coordinates) and dropped there."""
    copy, buttons, keys = Qt.DropAction.CopyAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    view = tree.viewport()
    enter = QDragEnterEvent(at, copy, mime, buttons, keys)
    QApplication.sendEvent(view, enter)
    move = QDragMoveEvent(at, copy, mime, buttons, keys)
    QApplication.sendEvent(view, move)
    drop = QDropEvent(QPointF(at), copy, mime, buttons, keys)
    QApplication.sendEvent(view, drop)
    QApplication.processEvents()
    return enter, move, drop


def _mime(path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def test_a_file_dropped_on_a_task_row_opens_an_update_with_it(app, tmp_path):
    browse = _today(app, "T000008")
    item = _row(browse.tree, ("task", "T000008"))
    path = _file(tmp_path)
    enter, move, drop = _drop(browse.tree, _mime(path), browse.tree.visualItemRect(item).center())
    assert enter.isAccepted() and move.isAccepted() and drop.isAccepted()
    w = app.window
    assert w.isVisible() and w.task == "T000008" and w.types == {"update"}
    assert [e.row.path for e in w.files] == [str(path)]


def test_a_drop_on_a_heading_or_a_note_is_refused(app, tmp_path):
    browse = _today(app, "T000008", note="Sign the overtime sheets")
    mime = _mime(_file(tmp_path))
    heading = browse.tree.topLevelItem(0)
    assert heading.data(0, KEY_ROLE) is None
    _enter, move, drop = _drop(browse.tree, mime, browse.tree.visualItemRect(heading).center())
    assert not move.isAccepted() and not drop.isAccepted()
    note = next(_row(browse.tree, k) for k in [browse.tree.topLevelItem(0).child(i).data(0, KEY_ROLE)
                                               for i in range(browse.tree.topLevelItem(0).childCount())] if not (isinstance(k, tuple) and k[0] == "task"))
    _enter, move, drop = _drop(browse.tree, mime, browse.tree.visualItemRect(note).center())
    assert not move.isAccepted() and not drop.isAccepted()
    assert not app.window.isVisible()


def test_a_link_dropped_on_a_due_row(app):
    browse = _today(app)
    due = next(browse.tree.topLevelItem(i) for i in range(browse.tree.topLevelItemCount())
               if "Due in the next 7 days" in (browse.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1) or ""))
    row = due.child(0)
    key = row.data(0, KEY_ROLE)
    assert isinstance(key, tuple) and key[0] == "task"
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/seal-specs")])
    _drop(browse.tree, mime, browse.tree.visualItemRect(row).center())
    assert app.window.task == key[1] and any("example.com/seal-specs" in (e.row.path or "") for e in app.window.files)


def test_other_views_take_no_file_drops(app, tmp_path):
    browse = _today(app, "T000008")
    browse.set_view("tasks")
    item = _row(browse.tree, ("task", "T000008"))
    _enter, move, drop = _drop(browse.tree, _mime(_file(tmp_path)), browse.tree.visualItemRect(item).center())
    assert not drop.isAccepted() and not app.window.isVisible()


def test_done_opens_an_update_and_undo_takes_it_away(app):
    browse = _today(app, "T000008")
    item = next(a for a in Model(app.ctx.conn).today_items() if a.subject == "T000008")
    browse.close_today_item(item.id, "Done")
    w = app.window
    assert w.isVisible() and w.task == "T000008" and w.types == {"update"} and w.content.value()[0].startswith("Done today")
    browse._status_link("undo")
    assert any(a.id == item.id for a in Model(app.ctx.conn).today_items()) and not w.isVisible()


def test_put_back_on_done_today(app):
    browse = _today(app, "T000008")
    item = next(a for a in Model(app.ctx.conn).today_items() if a.subject == "T000008")
    edits.close_today_item(app.ctx.conn, app.ctx.data_root, app.ctx.fs, item.id, "Done", NOW)
    browse.refresh()
    done = next(browse.tree.topLevelItem(i) for i in range(browse.tree.topLevelItemCount())
                if "Done today" in (browse.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1) or ""))
    actions = done.child(0).data(0, ACTIONS_ROLE).actions
    put_back = next(a for a in actions if a[0] == "Back on Today")
    put_back[1]()
    assert any(a.id == item.id for a in Model(app.ctx.conn).today_items())


def test_edit_task_sets_a_repeating_reminder(app):
    """Release 5.117, decision 416: Edit task's Reminder repeats, beside Reminder, and Reminder until with it."""
    from docrepo.ui.task_forms import TaskEditDialog

    browse = app.browse
    dialog = TaskEditDialog(browse, browse.model(), "T000012", browse._label_options, browse._people_options, today=NOW.date())
    field = dialog.reminder_repeat
    assert field.value() is None and dialog.reminder_until_field.isHidden()
    field.kind.setCurrentIndex(1)  # Every week on
    assert dialog.problem() == "Tick a weekday for Every week on, or pick Doesn't repeat." and not dialog.reminder_until_field.isHidden()
    field.weekdays[0].setChecked(True)
    field.weekdays[3].setChecked(True)
    assert field.value() == "week:mon,thu" and dialog.problem() is None
    assert dialog.reminder.value() == "2026-10-08"  # the rule's first time from today, a Thursday, shown in the form
    field.kind.setCurrentIndex(3)
    field.workday.setCurrentIndex(field.workday.findData("last"))
    assert field.value() == "workday:last" and dialog.reminder.value() == "2026-10-30"  # October's last workday
    field.set_value("days:5")
    assert field.kind.currentData() == "days" and field.every.value() == 5
    dialog.reminder_until.set_value("2027-01-31")
    edits.edit_task(app.ctx.conn, app.ctx.data_root, app.ctx.fs, app.ctx.settings, "T000012", NOW, **dialog.values())
    t = Model(app.ctx.conn).task("T000012")
    assert (t.reminder_repeat, t.reminder_until, t.reminder) == ("days:5", "2027-01-31", "2026-10-08")
    again = TaskEditDialog(browse, browse.model(), "T000012", browse._label_options, browse._people_options)
    assert again.reminder_repeat.value() == "days:5" and again.reminder_until.value() == "2027-01-31"
