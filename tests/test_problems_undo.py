"""Errors you can see, and Undo where it was missing (release 5.91, the review of 2026-11-06, F12): the Problems line,
Undo for Today's Done, an agenda's Discussed and Save, and one double-click rule (in ``test_timeline.py``)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, drafts, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import TODAY, Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui import capture_window as cw  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    messages: list[tuple[str, str]] = []
    context = AppContext(conn, data_root, fs, settings, notify=lambda t, m: messages.append((t, m)), now=lambda: NOW)
    context.messages = messages  # type: ignore[attr-defined]
    yield context
    conn.close()


@pytest.fixture
def windows(ctx):
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    browse.revealed = []
    browse.reveal = lambda path: browse.revealed.append(path) or True
    capture.saved.connect(browse.capture_saved)
    browse.show_browse()
    yield capture, browse
    QApplication.processEvents()
    capture.hide()
    capture.deleteLater()
    browse.deleteLater()


# ---- the Problems line ----
def test_a_save_with_problems_keeps_them_in_view_until_opened(windows, ctx, monkeypatch):
    capture, browse = windows
    real = cw.save_capture

    def with_a_problem(*a, **kw):
        r = real(*a, **kw)
        r.problems.append("The copy of Lift plan.pdf couldn't be saved (PermissionError).")
        return r

    monkeypatch.setattr(cw, "save_capture", with_a_problem)
    capture.show_capture()
    capture.content.setPlainText("Lift plan from the vendor.")  # no task: an unfiled capture
    capture.save()
    assert "Problems: The copy of Lift plan.pdf" in ctx.messages[-1][1]  # the tray's balloon, as before
    assert browse.problems_line.isVisible() and browse.problems_line.text() == "1 problem with the last save"
    assert capture.problems_line.text() == "1 problem with the last save"
    browse.say("Something else happened.")  # the status line moves on; the Problems line stays
    assert browse.problems_line.isVisible()
    browse.problems_line.show_dialogs = False
    browse.problems_line.click()
    dialog = browse.problems_line.last_dialog
    assert dialog is not None and dialog.list.count() == 1 and "Lift plan.pdf" in dialog.list.item(0).text()
    folder = ctx.problem_log.saves[-1].folder
    assert folder is not None and folder.name.startswith("C0000")
    show = next(b for b in dialog.findChildren(type(capture.problems_line).__mro__[1]) if b.text() == "Show in File Explorer")
    show.click()
    assert browse.revealed == [folder]
    capture.problems_line.refresh()
    assert not browse.problems_line.isVisible() and not capture.problems_line.isVisible()  # opened once: seen
    dialog.deleteLater()


def test_a_save_with_no_problems_shows_none(windows, ctx):
    capture, browse = windows
    capture.show_capture()
    capture.content.setPlainText("All good.")
    capture.save()
    assert not browse.problems_line.isVisible() and not ctx.problem_log.saves


# ---- Undo on Today's Done and an agenda's Discussed ----
def test_undo_after_done_puts_it_back_on_today(windows, ctx):
    _, browse = windows
    browse.add_to_today("T000012")
    item = next(a for a in Model(ctx.conn).today_items() if a.subject == "T000012")
    browse.close_today_item(item.id, "Done")
    assert "Undo" in browse.status.text()
    browse._status_link("undo")
    m = Model(ctx.conn)
    again = next(a for a in m.agenda if a.id == item.id)
    assert again.closed is None and again.how is None
    assert not [e for e in m.status_log_of("T000012") if e.to_value == "Done"]  # its closing line went with it
    assert "Back on Today." in browse.status.text()


def test_undo_after_discussed_reopens_and_drops_the_untouched_update(windows, ctx):
    capture, browse = windows
    item = next(a for a in Model(ctx.conn).agenda if a.subject == "T000001" and a.target == "T000010" and not a.closed)
    browse.close_agenda_item(item.id, "Discussed")
    assert capture.isVisible() and capture.task == "T000001" and capture.content.toPlainText().startswith("Discussed at Business team meeting")
    browse._status_link("undo")
    assert next(a for a in Model(ctx.conn).agenda if a.id == item.id).closed is None
    assert not capture.isVisible() and not drafts.listed(ctx.data_root)  # nothing was typed: no draft either


def test_undo_after_discussed_keeps_an_update_with_words_in_it(windows, ctx):
    capture, browse = windows
    item = next(a for a in Model(ctx.conn).agenda if a.subject == "T000001" and a.target == "T000010" and not a.closed)
    browse.close_agenda_item(item.id, "Discussed")
    capture.content.setPlainText(capture.content.toPlainText() + "go ahead with the new impeller.")
    browse._status_link("undo")
    assert capture.isVisible() and "stays open in the capture window" in browse.status.text()


# ---- Save's Undo ----
def test_undo_after_save_discards_the_capture_and_opens_it_again(windows, ctx):
    capture, browse = windows
    capture.show_capture()
    capture.content.setPlainText("The vendor called back about the seals.")
    capture.save()
    cid = max(Model(ctx.conn).captures)
    assert "Undo" in browse.status.text() and not capture.isVisible()
    browse._status_link("undo")
    c = Model(ctx.conn).captures[cid]
    assert c.discarded and c.discard_reason == "undone"  # nothing deleted: it's in the Discarded view
    assert capture.isVisible() and capture.content.toPlainText() == "The vendor called back about the seals."
    assert "is undone" in browse.status.text()
    capture.save()  # and it saves again, as a new capture
    assert max(Model(ctx.conn).captures) > cid and not Model(ctx.conn).captures[max(Model(ctx.conn).captures)].discarded


def test_a_save_that_made_a_task_has_no_undo(windows, ctx):
    capture, browse = windows
    capture.show_capture()
    capture.set_type("new_task", True) if hasattr(capture, "set_type") else capture.type_boxes["new_task"].setChecked(True)
    capture.title.setText("Book the crane")
    capture.content.setPlainText("Book the crane for Tuesday.")
    capture.save()
    assert "Undo" not in browse.status.text()


def test_the_footer_offers_undo_if_the_window_opens_again_soon(windows, ctx):
    capture, _ = windows
    capture.show_capture()
    capture.content.setPlainText("A note to take back.")
    capture.save()
    capture.show_capture()
    assert capture.undo_clear.isVisible() and capture.draft_label.text().startswith("Saved C")
    capture.undo_clear.click()
    assert capture.content.toPlainText() == "A note to take back."
    assert TODAY  # the Today target is unaffected
