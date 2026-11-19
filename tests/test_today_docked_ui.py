"""Today docked at a screen edge (release 5.178, the design workspace's ``docs/mods/today-docked-plan.md``, decisions 833 to
835), driven offscreen with the stand-in for Windows in ``today_dock.API``: nothing is registered with Windows, and no
window is shown on the desktop. The tick docks and fills the height; unticking, closing and quitting each give the strip
back once; a refusal floats, unticks and says so; the grip and a move to the other side move the strip; widening doesn't."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.appbar import ABM_NEW, ABM_QUERYPOS, ABM_REMOVE, ABM_SETPOS  # noqa: E402
from docrepo.ui import today_dock  # noqa: E402

import test_today_priority_ui as shared  # noqa: E402
from test_appbar import StandIn  # noqa: E402

qapp, app, panel = shared.qapp, shared.app, shared.panel  # the fixtures, shared


@pytest.fixture
def windows(monkeypatch):
    api = StandIn()
    monkeypatch.setattr(today_dock, "API", api)
    return api


def calls(api) -> list[int]:
    return [m for m, _ in api.calls]


def test_offscreen_the_line_is_greyed_and_nothing_docks(app, panel):
    line = next(a for a in panel.top_menu().actions() if a.text() == today_dock.LINE)
    assert line.isCheckable() and not line.isChecked() and not line.isEnabled()  # no stand-in: Windows can't be asked
    assert not panel.dock.dock() and panel.dock.strip is None


def test_the_tick_docks_and_fills_the_height(app, panel, windows):
    line = next(a for a in panel.top_menu().actions() if a.text() == today_dock.LINE)
    assert line.isEnabled() and not line.isChecked()
    line.trigger()
    assert calls(windows) == [ABM_NEW, ABM_QUERYPOS, ABM_SETPOS] and db.get_state(app.ctx.conn, today_dock.DOCKED_KEY) == "1"
    strip = panel.dock.rect()
    assert strip is not None and panel.geometry().height() == strip.height() and panel.geometry().y() == strip.y()
    assert strip.width() == panel.rest_width()
    assert next(a for a in panel.top_menu().actions() if a.text() == today_dock.LINE).isChecked()
    # Widened under the pointer, it lies over the other windows: the strip stays.
    windows.calls.clear()
    panel.hover.open_wide()
    panel.place_window(animate=False)
    assert windows.calls == [] and panel.width() > strip.width() and panel.dock.rect() == strip


def test_unticking_closing_and_quitting_each_give_it_back_once(app, panel, windows):
    panel.dock.set_wanted(True)
    panel.dock.set_wanted(False)
    assert calls(windows).count(ABM_REMOVE) == 1 and panel.dock.strip is None and db.get_state(app.ctx.conn, today_dock.DOCKED_KEY) == "0"
    panel.dock.set_wanted(True)
    panel.close_panel()
    assert calls(windows).count(ABM_REMOVE) == 2 and db.get_state(app.ctx.conn, today_dock.DOCKED_KEY) == "1"  # the tick stays
    panel.open_panel()  # docked again, as ticked
    assert panel.dock.strip is not None
    app.give_back_strip()  # as aboutToQuit does
    app.give_back_strip()
    assert calls(windows).count(ABM_REMOVE) == 3 and panel.dock.strip is None


def test_a_refusal_floats_unticks_and_says_so(app, panel, monkeypatch):
    monkeypatch.setattr(today_dock, "API", StandIn(refuse=ABM_SETPOS))
    panel.dock.set_wanted(True)
    assert panel.dock.strip is None and db.get_state(app.ctx.conn, today_dock.DOCKED_KEY) == "0"
    assert panel.note_label.text() == "Couldn't dock here, so it's floating." and not panel.note_row.isHidden()
    assert not next(a for a in panel.top_menu().actions() if a.text() == today_dock.LINE).isChecked()


def test_the_grip_and_a_move_to_the_other_side_move_the_strip(app, panel, windows):
    panel.dock.set_wanted(True)
    first = panel.dock.strip
    windows.calls.clear()
    panel._rest = str(panel.rest_width() + 40)  # the grip dragged wider, then let go
    panel.keep_rest()
    assert calls(windows) == [ABM_QUERYPOS, ABM_SETPOS] and panel.dock.strip.width == first.width + 40
    windows.calls.clear()
    other = "right" if panel.place_.side == "left" else "left"
    area = panel._screen().geometry()
    panel.dropped(area.topRight() if other == "right" else area.topLeft())
    assert panel.place_.side == other and calls(windows) == [ABM_QUERYPOS, ABM_SETPOS]
    s = panel.dock.strip
    assert (s.left == area.x()) if other == "left" else (s.right == area.x() + area.width())
