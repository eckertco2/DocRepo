"""Release 5.158, Recent captures, offscreen (the design workspace's ``docs/mods/recent-captures-plan.md``, decisions 722 to
727): the Capture wheel's NE and the palettes, the popup's rows and keys, Enter on a capture whose block is on a notes page
(a note, an email's capture and meeting notes), and on one that's on none. Every name here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import types  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import hotkey  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import CaptureDraft, save_capture  # noqa: E402
from docrepo.ui import recent_captures as rc  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.palette import RECENT_CAPTURES  # noqa: E402
from docrepo.ui.wheel_commands import REGISTRY  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
NOTES = """Impeller is on site.
- @Tom get the alignment report by Friday
- **decision, we go with the 50 t crane."""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    SETTINGS.save(fs, root)
    return AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)


@pytest.fixture
def host(ctx):
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    browse.said = []
    real_say = browse.say
    browse.say = lambda text, error=False: (browse.said.append(text), real_say(text, error))
    given_back: list[bool] = []
    app = types.SimpleNamespace(ctx=ctx, browse=browse, show_browse=browse.show_browse,
                                wheels=types.SimpleNamespace(give_back=lambda: given_back.append(True)))
    h = rc.RecentCaptures(app)
    h.given_back = given_back
    yield h
    # Everything it opened goes, so no window or popup of ours holds the focus in a later test.
    QApplication.processEvents()
    for shown in (h.popup, h, browse, capture):
        shown.hide()
    for widget in (h, browse, capture):
        widget.deleteLater()
    QApplication.processEvents()


def open_it(h: rc.RecentCaptures) -> rc.RecentPopup:
    h.open_it(QApplication.primaryScreen())
    return h.popup


def press(widget, key, text: str = "") -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))


def caret_capture(browse: BrowseWindow) -> str | None:
    """The capture whose block the caret is on: its caption, or the line its tucked caption's mark is beside."""
    notes = browse.task_pane.notes
    b = notes.textCursor().block()
    caption = notes.mark_of(b) or b
    ref = notes.ref_of(caption)
    return ref[1] if ref and ref[0] == "capture" else None


# ---- the wheel and the palettes (decision 723) ----
def test_the_capture_wheel_s_ne_opens_it_and_the_palettes_have_it(qapp, ctx, monkeypatch):
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    app = CaptureApp(qapp, ctx)
    try:
        slot = app.wheels.config.wheel("capture").slots["NE"]
        assert (slot.label, slot.icon, slot.command) == ("Recent captures", "activity", "capture.recent")
        REGISTRY["capture.recent"].run(app, {})
        h = app.wheels._recent_captures
        assert h is not None and h.popup.isVisible() and h.popup.search.text() == ""
        assert [r.id for r in h.popup.rows()][:3] == ["C000025", "C000024", "C000023"]
        h.popup.close()
        for window in (app.browse, app.window):
            names = [c.name for c in window.palette_commands()]
            assert RECENT_CAPTURES in names, window
            assert "Recent captures" in names  # the slot's row too, "Capture wheel, up and right"
        app.wheels.snapshot = object()
        next(c for c in app.browse.palette_commands() if c.name == RECENT_CAPTURES).run()
        assert app.wheels.snapshot is None and h.popup.isVisible()  # from Ctrl+K, Esc gives the keyboard to no other program
        h.popup.close()
    finally:  # the app's minute timer would go on ticking into later tests
        app.timer.stop()
        for window in (app.wheels.window, app.window, app.browse, app.tray):
            window.hide()
        qapp.removeNativeEventFilter(app.filter)


# ---- the popup (decision 724) ----
def test_the_rows_newest_first_with_their_kinds_and_where(host):
    popup = open_it(host)
    rows = popup.rows()
    assert len(rows) == 10 and rows[0].id == "C000025" and popup.list.currentRow() == 0
    assert [(r.kind, r.where, r.when) for r in rows[:5]] == [
        ("update", "Draft monitoring plan", "13:52"), ("note", "On an agenda", "13:40"), ("note", "Unfiled", "13:15"),
        ("note", "Unfiled", "11:30"), ("email", "Unfiled", "10:05")]
    assert popup.note.text() == rc.HINT
    item = popup.list.item(0)
    assert "Draft monitoring plan" in item.toolTip() and "C000025" in item.toolTip()


def test_typing_narrows_it_and_esc_closes_it(host):
    popup = open_it(host)
    popup.search.setText("impeller")
    assert [r.id for r in popup.rows()] == ["C000014", "C000012", "C000010", "C000008", "C000005", "C000003", "C000002"]
    popup.search.setText("zeppelin")
    assert popup.rows() == [] and popup.list.count() == 1 and "zeppelin" in popup.list.item(0).data(Qt.ItemDataRole.UserRole).label
    press(popup.search, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not popup.isVisible() and host.given_back == [True]  # nothing picked: the keyboard goes back


def test_down_moves_and_wraps_as_the_hash_list_does(host):
    popup = open_it(host)
    press(popup.search, Qt.Key.Key_Down)
    assert popup.list.currentRow() == 1
    press(popup.search, Qt.Key.Key_Up)
    press(popup.search, Qt.Key.Key_Up)
    assert popup.list.currentRow() == 9  # round from the start to the end


# ---- Enter (decisions 725 and 726) ----
def test_enter_opens_the_block_on_its_notes_page(host):
    browse = host.app.browse
    popup = open_it(host)
    popup.search.setText("crane booking")
    assert [r.id for r in popup.rows()] == ["C000013"]
    press(popup.search, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert not popup.isVisible() and host.given_back == []
    assert browse.sel == ("task", "T000008") and browse.task_pane.task_id == "T000008"
    assert caret_capture(browse) == "C000013"


def test_tab_opens_an_email_s_capture_on_its_task_s_page(host):
    browse = host.app.browse
    popup = open_it(host)
    popup.search.setText("datasheet")
    press(popup.search, Qt.Key.Key_Tab)
    QApplication.processEvents()
    assert browse.sel == ("task", "T000001") and caret_capture(browse) == "C000003"


def test_meeting_notes_open_on_the_meeting_s_page(host, ctx):
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, CaptureDraft(content=NOTES, task="T000010", meeting=True), NOW)
    browse = host.app.browse
    browse.refresh()
    popup = open_it(host)
    first = popup.rows()[0]
    assert (first.id, first.kind) == (r.capture_id, "meeting") and not set(r.items) & {x.id for x in popup.rows()}
    press(popup.search, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert browse.sel == ("task", r.meeting) and caret_capture(browse) == r.capture_id


def test_an_unfiled_capture_opens_its_own_page_saying_why(host):
    browse = host.app.browse
    popup = open_it(host)
    popup.search.setText("steam trap")
    press(popup.search, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert browse.sel == ("capture", "C000021") and browse.view == "unfiled"
    assert browse.said[-1] == "C000021 isn't on a notes page, so its capture page is open instead."
    assert browse.status.text() == browse.said[-1]


def test_a_block_taken_off_its_page_opens_its_capture_page(host, ctx):
    page = Model(ctx.conn).pages["T000008"]
    caption = next(line for line in page.split("\n") if line.endswith("(capture:C000013)"))
    ctx.conn.execute("UPDATE task_pages SET body = ? WHERE task = 'T000008'", (page.replace(caption + "\n", "").replace(
        "Bring up the 20 Oct crane booking at the next business team meeting.", ""),))
    ctx.conn.commit()
    browse = host.app.browse
    browse.refresh()
    popup = open_it(host)
    popup.search.setText("crane booking")
    assert [(r.id, r.where) for r in popup.rows()] == [("C000013", "Not on a notes page")]
    press(popup.search, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert browse.sel == ("capture", "C000013") and browse.said[-1].startswith("C000013 isn't on a notes page")


def test_a_click_opens_a_row(host):
    browse = host.app.browse
    popup = open_it(host)
    popup.search.setText("rigging plan")
    item = popup.list.item(0)
    assert item.data(Qt.ItemDataRole.UserRole).ref == "C000012"
    popup.list.itemClicked.emit(item)
    QApplication.processEvents()
    assert browse.sel == ("task", "T000012") and caret_capture(browse) == "C000012"
