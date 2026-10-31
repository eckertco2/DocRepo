"""The navigation wheels' direction resolver (release 5.41; ``docs/ui-design/wheel-design.md``, decisions 168 to 170).

Pure Python, with no Qt and no clock of its own: it's fed timed key events and answers with what's lit and what's
committed, so the tests feed it sequences. ``Resolver`` turns arrows into a direction; ``Session`` adds the hotkey (tap or
hold), which is everything the wheel's window needs to decide.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Every direction a slot can have, clockwise from the top.
DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
CARDINALS = ("N", "E", "S", "W")
DIAGONALS = ("NE", "SE", "SW", "NW")
#: Numpad digits, spatially; 5 cancels, and doesn't appear here.
NUMPAD = {8: "N", 9: "NE", 6: "E", 3: "SE", 2: "S", 1: "SW", 4: "W", 7: "NW"}
#: The arrow key each cardinal direction is, as words for the wheel's own labels.
ARROWS = {"N": "↑", "NE": "↑→", "E": "→", "SE": "↓→", "S": "↓", "SW": "↓←", "W": "←", "NW": "↑←"}
#: The numpad digit each direction is.
DIGITS = {direction: digit for digit, direction in NUMPAD.items()}
#: Each cardinal arrow, by the letter the resolver calls it.
KEY_DIRECTION = {"U": "N", "R": "E", "D": "S", "L": "W"}


def direction(held: set[str] | frozenset[str]) -> str | None:
    """The direction a set of held arrows ("U", "R", "D", "L") points: one for a cardinal, two at right angles for a
    diagonal. Opposites, or three or more, point nowhere (a fighting game's SOCD neutral)."""
    if len(held) == 1:
        return KEY_DIRECTION[next(iter(held))]
    if len(held) != 2:
        return None
    vertical = "N" if "U" in held else "S" if "D" in held else ""
    horizontal = "E" if "R" in held else "W" if "L" in held else ""
    return vertical + horizontal if vertical and horizontal else None


@dataclass(frozen=True)
class Step:
    """What a key event did: what's ``lit`` now, what's committed (None if nothing is), and how many ms from now the
    grace ends (None if it isn't running), for the caller to ``tick`` then."""

    lit: str | None
    commit: str | None = None
    wait: int | None = None
    #: All the arrows are up, with nothing to commit: opposites, or a press that's been cancelled out.
    released: bool = False


class Resolver:
    """Arrows to a direction (decision 169). It lights what's held as it changes, commits when all the arrows are up, and
    gives a diagonal's second key ``grace_ms`` to come up: holding one key past that re-aims at what's still held, which
    is how to correct a chord. A key's auto-repeat is ignored."""

    def __init__(self, grace_ms: int = 80) -> None:
        self.grace_ms = grace_ms
        self.held: set[str] = set()
        self.lit: str | None = None
        self._until: int | None = None

    def _advance(self, t: int) -> None:
        if self._until is not None and t >= self._until and self.held:
            self._until = None
            self.lit = direction(self.held)

    def down(self, key: str, t: int) -> Step:
        self._advance(t)
        if key not in self.held:  # a repeat changes nothing
            self.held.add(key)
            self._until = None
            self.lit = direction(self.held)
        return Step(self.lit)

    def up(self, key: str, t: int) -> Step:
        self._advance(t)
        if key not in self.held:
            return Step(self.lit)
        self.held.discard(key)
        if not self.held:
            commit, self.lit, self._until = self.lit, None, None
            return Step(None, commit=commit, released=commit is None)
        if self._until is None:
            self._until = t + self.grace_ms
        return Step(self.lit, wait=self._until - t)

    def tick(self, t: int) -> Step:
        """The grace may have run out."""
        self._advance(t)
        return Step(self.lit)

    def reset(self) -> None:
        self.held.clear()
        self.lit = None
        self._until = None


class Session:
    """One opening of a wheel (decision 168): tap or hold. If the hotkey comes up within ``tap_ms`` with no arrow pressed,
    the wheel stays open until a pick or a cancel. If it's held longer, the wheel lasts only while it's held: letting go
    with nothing down cancels, and letting go with an arrow still down leaves the pick to that arrow's coming up, so a hand
    rolling off the hotkey can't fire a half-made diagonal."""

    def __init__(self, t0: int, tap_ms: int = 200, grace_ms: int = 80) -> None:
        self.t0 = t0
        self.tap_ms = tap_ms
        self.resolver = Resolver(grace_ms)
        self.hotkey_down = True
        self.tapped = False  # the hotkey came up as a tap: the wheel stays until a pick or a cancel
        self.let_go = False  # the hotkey came up after a hold, with an arrow still down

    @property
    def lit(self) -> str | None:
        return self.resolver.lit

    def hotkey_up(self, t: int) -> str:
        """The hotkey came up: "stay", "wait" for the arrows still down, or "cancel"."""
        if not self.hotkey_down:
            return "stay"
        self.hotkey_down = False
        quick = t - self.t0 < self.tap_ms
        self.tapped = quick
        if self.resolver.held:
            self.let_go = not quick
            return "wait"
        return "stay" if quick else "cancel"

    def arrow_down(self, key: str, t: int) -> Step:
        return self.resolver.down(key, t)

    def arrow_up(self, key: str, t: int) -> Step:
        return self.resolver.up(key, t)

    def tick(self, t: int) -> Step:
        return self.resolver.tick(t)

    def ended_with_nothing(self) -> bool:
        """After the arrows all came up with nothing to run: true if a hold has already ended, so the wheel should cancel."""
        return self.let_go and not self.resolver.held
