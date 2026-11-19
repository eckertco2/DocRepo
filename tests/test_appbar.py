"""Today docked at a screen edge (release 5.178, the design workspace's ``docs/mods/today-docked-plan.md``, decisions 833
to 837), without Qt and without Windows: every call goes to a stand-in that records it and answers as told. Nothing here
registers anything with Windows."""
from __future__ import annotations

import pytest

from docrepo import appbar
from docrepo.appbar import ABM_NEW, ABM_QUERYPOS, ABM_REMOVE, ABM_SETPOS, AppBar, Box
from docrepo.panel_rules import Rect, dock_rect


class StandIn:
    """Windows, as the tests tell it to answer: a 1920 x 1080 screen with a 40 px taskbar at the bottom."""

    def __init__(self, refuse: int | None = None, narrower: bool = False):
        self.calls: list[tuple[int, Box]] = []
        self.refuse, self.narrower = refuse, narrower
        self.reserved: Box | None = None

    def message(self, msg, hwnd, edge, box):
        self.calls.append((msg, box))
        if msg == self.refuse:
            return 0, box
        if msg == ABM_QUERYPOS:
            return 1, Box(box.left, box.top, box.right, min(box.bottom, 1040))  # clear of the taskbar
        if msg == ABM_SETPOS:
            got = Box(box.left, box.top, box.right - 20, box.bottom) if self.narrower else box
            self.reserved = got
            return 1, got
        if msg == ABM_REMOVE:
            self.reserved = None
        return 1, box

    def work_area(self):
        r = self.reserved
        left = r.right if r and r.left == 0 else 0
        right = r.left if r and r.left > 0 else 1920
        return Box(left, 0, right, 1040)


def test_the_strip_for_each_side_and_a_second_screen():
    main, second = Rect(0, 0, 1920, 1080), Rect(1920, 0, 2560, 1440)
    assert dock_rect(main, "left", 180) == Rect(0, 0, 180, 1080)
    assert dock_rect(main, "right", 180) == Rect(1740, 0, 180, 1080)
    assert dock_rect(second, "right", 240) == Rect(4240, 0, 240, 1440) and dock_rect(second, "left", 240) == Rect(1920, 0, 240, 1440)


def test_dock_move_and_undock_in_their_order():
    api = StandIn()
    bar = AppBar(42, api)
    got = bar.dock(Box(1740, 0, 1920, 1080), "right")
    assert got == Box(1740, 0, 1920, 1040) and bar.registered  # clear of the taskbar, as Windows said
    assert [m for m, _ in api.calls] == [ABM_NEW, ABM_QUERYPOS, ABM_SETPOS]
    api.calls.clear()
    assert bar.move(Box(0, 0, 220, 1080), "left") == Box(0, 0, 220, 1040)
    assert [m for m, _ in api.calls] == [ABM_QUERYPOS, ABM_SETPOS]  # registered once
    assert bar.undock() and [m for m, _ in api.calls][-1] == ABM_REMOVE and not bar.registered
    assert not bar.undock() and [m for m, _ in api.calls].count(ABM_REMOVE) == 1  # twice does nothing


@pytest.mark.parametrize("step", [ABM_NEW, ABM_QUERYPOS, ABM_SETPOS])
def test_a_refusal_at_any_step_answers_none_and_leaves_nothing_registered(step):
    api = StandIn(refuse=step)
    bar = AppBar(42, api)
    assert bar.dock(Box(1740, 0, 1920, 1080), "right") is None and not bar.registered
    assert api.reserved is None
    assert ([m for m, _ in api.calls].count(ABM_REMOVE) == 1) == (step != ABM_NEW)  # given back once it was registered


def test_a_strip_narrower_than_asked_is_a_refusal():
    api = StandIn(narrower=True)
    bar = AppBar(42, api)
    assert bar.dock(Box(1740, 0, 1920, 1080), "right") is None and not bar.registered and api.reserved is None


def test_the_try_outs_report_against_the_stand_in():
    api = StandIn()
    waited: list[float] = []
    closed: list[bool] = []
    text = appbar.try_out(api, lambda box: appbar.Strip(7, lambda: closed.append(True)), waited.append, seconds=30)
    assert "Working area before: 0,0 to 1920,1040" in text and "Working area during: 0,0 to 1680,1040" in text
    assert "Working area after: 0,0 to 1920,1040 (1920 x 1040) (as before)" in text
    assert "ABM_SETPOS: answered 1, strip 1680,0 to 1920,1040" in text and "ABM_REMOVE: answered 1" in text
    assert waited == [30] and closed == [True] and api.reserved is None
    left = StandIn()
    text = appbar.try_out(left, lambda box: appbar.Strip(7, lambda: None), lambda s: None, side="left", width=200, leave=True)
    assert left.reserved == Box(0, 0, 200, 1040) and "--leave" in text and "ABM_REMOVE" not in text
    assert appbar.check(left) == "# appbar-try --check\n\n- Working area now: 200,0 to 1920,1040 (1720 x 1040)\n"


def test_no_windows_offscreen():
    """Offscreen, as the tests and the pictures run, docking does nothing (decision 835). Making the object calls nothing."""
    assert appbar.system_api("offscreen") is None
