"""Save or link in the windows (release 5.145, the save or link plan's decisions 627 to 633), driven offscreen over the
sample data: the two drop zones on the capture window, the pinned window and Find files, which zone a drop lands in, a
folder on Save, a web link, and each row's Saved · Linked switch. The examples are made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from docrepo.config import Settings  # noqa: E402
from docrepo.layer0 import Part  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import Attachment, FileRow  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.save_link import LINK, SAVE, zone_at  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
INSTALLATION = "T000008"
ACTIONS = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    messages: list[tuple[str, str]] = []
    context = AppContext(conn, root, fs, Settings(me="P001"), notify=lambda t, m: messages.append((t, m)), now=lambda: NOW)
    context.messages = messages  # type: ignore[attr-defined]
    return context


@pytest.fixture
def window(ctx):
    w = CaptureWindow(ctx)
    w.resize(900, 700)
    w.show_capture(task=INSTALLATION)
    yield w
    w.hide()
    if w.pin_window is not None:
        w.pin_window.hide()
        w.pin_window.deleteLater()
    w.deleteLater()


def mime_of(*paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def drag_in(widget, mime: QMimeData, at: QPoint | None = None) -> QDragEnterEvent:
    enter = QDragEnterEvent(at or widget.rect().center(), ACTIONS, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, enter)
    return enter


def move_over(widget, mime: QMimeData, at: QPoint) -> None:
    """The pointer moving over the zones: Qt first hands the drag to the widget now under it, with a drag-enter, as
    QWidgetWindow does when the drag crosses onto another widget, then moves it there."""
    QApplication.sendEvent(widget, QDragEnterEvent(at, ACTIONS, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(widget, QDragMoveEvent(at, ACTIONS, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def drop_on(widget, mime: QMimeData, at: QPoint) -> QDropEvent:
    drop = QDropEvent(QPointF(at), ACTIONS, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, drop)
    return drop


def left(widget) -> QPoint:
    return QPoint(widget.width() // 4, widget.height() // 2)


def right(widget) -> QPoint:
    return QPoint(widget.width() * 3 // 4, widget.height() // 2)


def a_file(tmp_path, name: str = "Pump curve.txt", text: str = "Design point 38 kW"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---- the zones (decisions 627 and 628) ----
def test_the_left_half_saves_and_the_right_half_links():
    assert (zone_at(800, 10), zone_at(800, 399), zone_at(800, 400), zone_at(800, 790)) == (SAVE, SAVE, LINK, LINK)


def test_files_dragged_over_the_window_meet_two_zones(window, tmp_path):
    report = a_file(tmp_path)
    mime = mime_of(report)
    assert drag_in(window.content.viewport(), mime).isAccepted()  # over the content text too: the zones cover it
    zones = window.zones
    assert zones.isVisible() and zones.geometry() == window.rect() and not zones.folders
    assert [zones.titles[k].text() for k in (SAVE, LINK)] == ["Save in DocRepo", "Link"]
    assert zones.lines[SAVE].text() == "A file of its own, in the task's Files folder"
    assert zones.lines[LINK].text() == "DocRepo notes where it is and reads it there"
    assert zones.lit == ""  # neither lit until the pointer is over one
    move_over(zones, mime, left(zones))
    assert zones.lit == SAVE and zones.zones[SAVE].property("lit") and not zones.zones[LINK].property("lit")
    QApplication.sendEvent(zones, QDragMoveEvent(right(zones), ACTIONS, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert zones.lit == LINK
    drop = drop_on(zones, mime, left(zones))
    assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction and not zones.isVisible()
    [entry] = window.files
    assert entry.row.name == "Pump curve.txt" and entry.switch.saved() and not entry.switch.fixed


def test_a_file_dropped_on_link_is_linked_and_the_zones_go_when_the_drag_leaves(window, tmp_path):
    mime = mime_of(a_file(tmp_path))
    drag_in(window, mime)
    QApplication.sendEvent(window.zones, QDragEnterEvent(right(window.zones), ACTIONS, mime, Qt.MouseButton.LeftButton,
                                                         Qt.KeyboardModifier.NoModifier))
    from PySide6.QtGui import QDragLeaveEvent

    QApplication.sendEvent(window.zones, QDragLeaveEvent())
    assert not window.zones.isVisible() and not window.files  # left without a drop: nothing added
    drag_in(window, mime)
    move_over(window.zones, mime, right(window.zones))
    drop_on(window.zones, mime, right(window.zones))
    [entry] = window.files
    assert not entry.switch.saved()
    window.save()
    m = Model(window.ctx.conn)
    c = max(m.captures.values(), key=lambda x: x.id)
    assert [d.save_a_copy for d in c.documents] == [False] and not any(f.from_capture == c.id for f in m.copies)


def test_a_drop_the_zones_dont_take_goes_by_the_half_it_lands_in(window, tmp_path):
    """Should a drop reach the window itself, it goes as the zones would have taken it."""
    one, two = a_file(tmp_path, "One.txt"), a_file(tmp_path, "Two.txt")
    drag_in(window, mime_of(one))
    drop_on(window, mime_of(one), left(window))
    assert not window.zones.isVisible()
    drag_in(window, mime_of(two))
    drop_on(window, mime_of(two), right(window))
    assert [(e.row.name, e.switch.saved()) for e in window.files] == [("One.txt", True), ("Two.txt", False)]


def test_a_folder_dropped_on_save_is_linked_and_the_window_says_so(window, tmp_path):
    drawings = tmp_path / "Drawings"
    drawings.mkdir()
    mime = mime_of(drawings)
    drag_in(window, mime)
    zones = window.zones
    assert zones.folders and zones.zones[SAVE].property("off") and zones.lines[SAVE].text() == "A folder isn't copied: it's linked"
    move_over(zones, mime, left(zones))
    drop_on(zones, mime, left(zones))
    [entry] = window.files
    assert entry.switch.fixed and not entry.switch.saved()
    assert entry.note.text().startswith("Dropped on Save: a folder isn't copied, so it's linked.")
    # Files and folders together: both zones, each kept as its zone allows.
    window.reset_draft()
    report = a_file(tmp_path)
    both = mime_of(report, drawings)
    drag_in(window, both)
    assert not zones.folders and not zones.zones[SAVE].property("off")
    move_over(zones, both, left(zones))
    drop_on(zones, both, left(zones))
    assert [(e.row.name, e.switch.saved()) for e in window.files] == [("Pump curve.txt", True), ("Drawings", False)]


def test_a_web_link_gets_no_zones(window):
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/sites/eng/Pump%20spec.docx")])
    drag_in(window, mime)
    assert not window.zones.isVisible()
    drop_on(window, mime, left(window))  # a link, wherever it lands
    [entry] = window.files
    assert entry.row.path == "https://example.com/sites/eng/Pump%20spec.docx" and entry.switch.fixed and not entry.switch.saved()


# ---- the switch (decision 630) ----
def test_each_row_says_saved_or_linked(window, tmp_path, monkeypatch):
    report, sketch = a_file(tmp_path), a_file(tmp_path, "Seal sketch.txt", "Made-up sketch")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(report)], ""))
    actions = {a.text(): a for a in window.attach_button.menu().actions()}
    assert list(actions)[:3] == ["Save files…", "Link files…", "A link…"]
    actions["Save files…"].trigger()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(sketch)], ""))
    actions["Link files…"].trigger()
    window.content.setPlainText(f"From the site.\n{tmp_path / 'Seal sketch.txt'}")  # the same file typed: no second row
    attachment = Attachment("Lift plan.txt", data=b"Lift plan, made up")
    window._add_file(FileRow("Lift plan.txt", part=Part("attachment", "Lift plan.txt", attachment, size=18)), "dropped")
    picture = Attachment("Picture.png", data=b"\x89PNG", size=4)
    window._add_file(FileRow("Picture.png", part=Part("picture", "Picture.png", picture, size=4, pasted=True)), "pasted")
    rows = {e.row.name: e for e in window.files}
    assert rows["Pump curve.txt"].switch.saved() and not rows["Seal sketch.txt"].switch.saved()
    assert rows["Lift plan.txt"].switch.fixed and rows["Lift plan.txt"].switch.saved()  # an attachment: always saved
    assert rows["Picture.png"].switch is None  # a picture stays with the capture
    rows["Seal sketch.txt"].switch.buttons[True].click()  # a click changes it until Save
    assert rows["Seal sketch.txt"].switch.saved()
    rows["Lift plan.txt"].switch.buttons[False].click()  # a fixed one doesn't
    assert rows["Lift plan.txt"].switch.saved()
    assert window.files_line.text() == "Saved files go in Installation's Files folder." and window.files_line.isVisible()
    window.set_task(None)
    window.refresh()
    assert window.files_line.text() == "Saved files stay in the capture's own folder until it's filed, then go in its task's Files folder."


def test_a_path_on_a_line_of_its_own_is_linked(window, tmp_path):
    report = a_file(tmp_path)
    window.content.setPlainText(f"See the curve.\n{report}\n")
    window._sync_paths()
    [entry] = window.files
    assert entry.src == "pasted" and not entry.switch.saved() and not entry.switch.fixed


def test_use_the_first_files_choices_carries_the_switch(window, tmp_path):
    one, two, drawings = a_file(tmp_path, "One.txt"), a_file(tmp_path, "Two.txt"), tmp_path / "Drawings"
    drawings.mkdir()
    window.add_paths([str(one)], saved=True)
    window.add_paths([str(two), str(drawings)])
    window.same_all.setChecked(True)
    rows = window._file_rows()
    assert [(r.name, r.save_a_copy) for r in rows] == [("One.txt", True), ("Two.txt", True), ("Drawings", False)]
    assert window.files[1].switch.saved() and not window.files[1].switch.isEnabled()


def test_a_draft_keeps_each_rows_switch(window, ctx, tmp_path):
    one, two = a_file(tmp_path, "One.txt"), a_file(tmp_path, "Two.txt")
    window.add_paths([str(one)], saved=True)
    window.add_paths([str(two)])
    window.content.setPlainText("Kept for later.")
    window.hide()  # to Drafts
    window.show_capture()
    from docrepo import drafts

    (kept,) = drafts.listed(ctx.data_root)
    window.open_draft(kept.id)
    assert [(e.row.name, e.switch.saved()) for e in window.files] == [("One.txt", True), ("Two.txt", False)]


# ---- the pinned window (decision 627) ----
def test_the_pinned_windows_drop_zone_splits_the_same_way(window, tmp_path):
    window.pin()
    pin = window.pin_window
    report = a_file(tmp_path)
    mime = mime_of(report)
    drag_in(pin, mime)
    zones = pin.zones
    assert zones.isVisible() and zones.y() == 32 and zones.height() == pin.height() - 32  # below the top line
    move_over(zones, mime, left(zones))
    assert zones.lit == SAVE
    drop_on(zones, mime, left(zones))
    assert not zones.isVisible() and [(e.row.name, e.switch.saved()) for e in window.files] == [("Pump curve.txt", True)]
    drawings = tmp_path / "Drawings"
    drawings.mkdir()
    drag_in(pin, mime_of(drawings))
    move_over(zones, mime_of(drawings), left(zones))
    drop_on(zones, mime_of(drawings), left(zones))
    assert "a folder isn't copied, so it's linked" in pin.message.toolTip()
    window.save()
    assert (window.ctx.data_root / "Tasks" / INSTALLATION / "Files" / "2026-10-08 Pump curve.txt").exists()


# ---- Find files (decision 633) ----
def test_find_files_takes_the_zones(ctx, tmp_path):
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    browse.show_browse()
    try:
        browse.open_task_view(INSTALLATION)
        view = browse.task_views[INSTALLATION]
        view.resize(1000, 700)
        report = a_file(tmp_path)
        mime = mime_of(report)
        drag_in(view, mime)
        assert view.zones.isVisible()
        move_over(view.zones, mime, left(view.zones))
        drop_on(view.zones, mime, left(view.zones))
        assert capture.isVisible() and capture.task == INSTALLATION
        assert [(e.row.name, e.switch.saved()) for e in capture.files] == [("Pump curve.txt", True)]
        capture.reset_draft()
        drag_in(view, mime)
        move_over(view.zones, mime, right(view.zones))
        drop_on(view.zones, mime, right(view.zones))
        assert [(e.row.name, e.switch.saved()) for e in capture.files] == [("Pump curve.txt", False)]
        view.close()
    finally:
        capture.hide()
        capture.deleteLater()
        browse.deleteLater()
