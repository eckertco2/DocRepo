"""The navigation wheels' direction resolver, and tap or hold (release 5.41, decisions 168 to 170): no Qt, fed timed sequences."""
from __future__ import annotations

import pytest

from docrepo.wheel import DIGITS, DIRECTIONS, NUMPAD, Resolver, Session, direction


@pytest.mark.parametrize(("held", "expected"), [
    ({"U"}, "N"), ({"R"}, "E"), ({"D"}, "S"), ({"L"}, "W"),
    ({"U", "R"}, "NE"), ({"D", "R"}, "SE"), ({"D", "L"}, "SW"), ({"U", "L"}, "NW"),
    ({"U", "D"}, None), ({"L", "R"}, None), ({"U", "R", "D"}, None), ({"U", "R", "D", "L"}, None), (set(), None),
])
def test_what_a_set_of_arrows_points_at(held, expected):
    assert direction(held) == expected


def feed(events: list[tuple[str, str, int]], grace: int = 80) -> list:
    """Feed "down" and "up" events, and collect what each answered."""
    r = Resolver(grace)
    return [(r.down if kind == "down" else r.up)(key, t) for kind, key, t in events]


def test_the_briefs_diagonal_commits_ne():
    """Up down at 0, Right down at 30, Up up at 120, Right up at 140: Right comes up inside the grace."""
    steps = feed([("down", "U", 0), ("down", "R", 30), ("up", "U", 120), ("up", "R", 140)])
    assert [s.lit for s in steps[:3]] == ["N", "NE", "NE"]
    assert steps[-1].commit == "NE" and steps[-1].lit is None


def test_one_arrow_commits_its_direction():
    assert feed([("down", "U", 0), ("up", "U", 50)])[-1].commit == "N"


def test_opposites_select_nothing():
    steps = feed([("down", "U", 0), ("down", "D", 20), ("up", "U", 60), ("up", "D", 70)])
    assert steps[1].lit is None
    assert steps[-1].commit is None and steps[-1].released


def test_holding_one_key_past_the_grace_re_aims_at_it():
    """Up down, Right down, Up up, and Right held for 200 ms more, then up: E. That's how to correct a chord."""
    r = Resolver(80)
    r.down("U", 0)
    r.down("R", 30)
    step = r.up("U", 100)
    assert step.lit == "NE" and step.wait == 80
    assert r.tick(179).lit == "NE"
    assert r.tick(180).lit == "E"
    assert r.up("R", 300).commit == "E"


def test_the_grace_is_also_noticed_by_the_next_key():
    """No tick came, but the release itself is past the grace, so what's still held is the choice."""
    r = Resolver(80)
    r.down("U", 0)
    r.down("R", 30)
    r.up("U", 100)
    assert r.up("R", 300).commit == "E"


def test_a_new_arrow_during_the_grace_aims_again():
    r = Resolver(80)
    r.down("U", 0)
    r.down("R", 10)
    r.up("U", 20)
    assert r.down("D", 40).lit == "SE"
    assert r.up("R", 60).lit == "SE"
    assert r.up("D", 70).commit == "SE"


def test_lit_follows_with_no_release():
    r = Resolver()
    assert r.down("U", 0).lit == "N"
    assert r.down("R", 30).lit == "NE"


def test_auto_repeat_changes_nothing():
    r = Resolver()
    r.down("U", 0)
    r.down("R", 10)
    r.up("R", 20)  # the grace is running
    r.down("U", 25)  # a repeat of the key held: the grace isn't restarted
    assert r.tick(100).lit == "N"


def test_an_up_for_a_key_never_seen_is_ignored():
    """The hotkey's own arrow, say: pressed before the wheel opened."""
    r = Resolver()
    step = r.up("U", 10)
    assert step.commit is None and not step.released


def test_three_keys_then_one_left():
    r = Resolver(80)
    r.down("U", 0)
    r.down("R", 1)
    assert r.down("D", 2).lit is None
    r.up("D", 10)
    assert r.tick(200).lit == "NE"


def test_numpad_is_spatial_and_every_direction_has_a_digit():
    assert NUMPAD[8] == "N" and NUMPAD[9] == "NE" and NUMPAD[1] == "SW" and 5 not in NUMPAD
    assert set(DIGITS) == set(DIRECTIONS)


# ---- tap or hold (decision 168) ----
def test_a_tap_leaves_the_wheel_open():
    s = Session(0, tap_ms=200)
    assert s.hotkey_up(120) == "stay"
    assert s.tapped


def test_holding_past_the_tap_time_and_letting_go_with_nothing_down_cancels():
    s = Session(0, tap_ms=200)
    assert s.hotkey_up(500) == "cancel"
    assert not s.tapped


def test_rolling_off_the_hotkey_with_an_arrow_down_leaves_the_pick_to_that_arrow():
    """A hand rolling off the hotkey can't fire a half-made diagonal."""
    s = Session(0, tap_ms=200)
    s.arrow_down("U", 300)
    assert s.hotkey_up(400) == "wait"
    assert s.arrow_down("R", 420).lit == "NE"
    s.arrow_up("U", 500)
    assert s.arrow_up("R", 520).commit == "NE"


def test_a_hold_that_ends_on_opposites_is_over():
    s = Session(0, tap_ms=200)
    s.arrow_down("U", 300)
    s.arrow_down("D", 310)
    assert s.hotkey_up(400) == "wait"
    s.arrow_up("U", 410)
    step = s.arrow_up("D", 420)
    assert step.commit is None and step.released and s.ended_with_nothing()


def test_a_tapped_wheel_stays_open_after_opposites():
    s = Session(0, tap_ms=200)
    s.hotkey_up(50)
    s.arrow_down("U", 300)
    s.arrow_down("D", 310)
    s.arrow_up("U", 320)
    assert s.arrow_up("D", 330).released
    assert not s.ended_with_nothing()


def test_a_quick_press_of_hotkey_and_arrow_together_is_still_a_tap():
    s = Session(0, tap_ms=200)
    s.arrow_down("U", 20)
    assert s.hotkey_up(100) == "wait"
    assert s.tapped and not s.let_go


def test_only_the_first_hotkey_up_counts():
    s = Session(0)
    assert s.hotkey_up(50) == "stay"
    assert s.hotkey_up(900) == "stay"
