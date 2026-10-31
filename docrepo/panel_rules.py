"""The Today side panel's rules (release 5.43; ``docs/ui-design/wheel-design.md``, section 7): hovering, where it snaps, finding
its monitor again, and whether something full screen covers it. No Qt, so the tests feed them directly."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

#: Whether the panel is open, in docs.db's app_state: remembered across restarts.
OPEN_KEY = "today_panel_open"
#: How far the pointer may drift, in pixels, and still count as resting on the panel: one crossing on its way past does nothing.
STILL_PX = 6


@dataclass(frozen=True)
class Rect:
    """A rectangle, as (x, y, width, height)."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


class Hover:
    """Decision 219: widens after the pointer has rested on it for ``hover_ms``; contracts ``contract_ms`` after the pointer
    leaves, and never while the pointer is on it or something holds it open (a box with the cursor, a menu, a task's detail)."""

    def __init__(self, hover_ms: int = 400, contract_ms: int = 1500, enabled: bool = True) -> None:
        self.hover_ms, self.contract_ms, self.enabled = hover_ms, contract_ms, enabled
        self.wide = False
        self.inside = False
        self.rest_since = 0
        self.left_at = 0
        self.dismissed = False  # Esc contracted it with the pointer still on it: it stays narrow until the pointer comes back
        self._at = (0, 0)

    def pointer_in(self, t: int, at: tuple[int, int] = (0, 0)) -> None:
        self.inside = True
        self.rest_since = t
        self.dismissed = False
        self._at = at

    def pointer_moved(self, t: int, at: tuple[int, int]) -> None:
        """Moving more than a little starts the rest again, so a pass across it doesn't widen it."""
        if abs(at[0] - self._at[0]) + abs(at[1] - self._at[1]) > STILL_PX:
            self.rest_since = t
            self._at = at

    def pointer_out(self, t: int) -> None:
        self.inside = False
        self.left_at = t

    def open_wide(self) -> None:
        """A click on the top line, or the hotkey: wide at once, hover or no hover."""
        self.wide = True

    def contract(self) -> None:
        """Esc: narrow now, and it doesn't widen again under a pointer that hasn't moved off it."""
        self.wide = False
        self.dismissed = self.inside

    def tick(self, t: int, holding: bool = False, hover_ms: int | None = None) -> bool:
        """Whether it's wide now. ``hover_ms`` overrides the wait, for an edge between two monitors."""
        if not self.wide and self.enabled and self.inside and not self.dismissed and t - self.rest_since >= (hover_ms if hover_ms is not None else self.hover_ms):
            self.wide = True
        elif self.wide and not self.inside and not holding and t - self.left_at >= self.contract_ms:
            self.wide = False
        return self.wide

    def waiting(self, holding: bool = False) -> bool:
        """Whether a timer is still needed: something may change on its own."""
        return (not self.wide and self.enabled and self.inside and not self.dismissed) or (self.wide and not self.inside and not holding)


def snap_side(centre_x: int, monitor: Rect) -> str:
    """Decision 222: on release, the nearer side edge of the monitor it's on."""
    return "left" if centre_x < monitor.x + monitor.w / 2 else "right"


def edge_x(side: str, monitor: Rect, width: int) -> int:
    return monitor.x if side == "left" else monitor.right - width


def is_inner_edge(side: str, monitor: Rect, monitors: Sequence[Rect]) -> bool:
    """Whether the side it's on meets another monitor, where a pointer crossing screens would pass over it."""
    x = monitor.x if side == "left" else monitor.right
    for other in monitors:
        if other == monitor:
            continue
        touching = other.right == x if side == "left" else other.x == x
        if touching and other.y < monitor.bottom and monitor.y < other.bottom:
            return True
    return False


def next_monitor(current: int, count: int) -> int:
    return (current + 1) % count if count else 0


@dataclass(frozen=True)
class Monitor:
    """What's remembered of a monitor: a name alone isn't unique, so its serial number and size too."""

    name: str = ""
    serial: str = ""
    w: int = 0
    h: int = 0


@dataclass(frozen=True)
class Place:
    """Where the panel lives, kept in docs.db's app_state."""

    side: str = "left"
    top: int = 0
    monitor: Monitor = Monitor()

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: object) -> Place:
        if not isinstance(data, dict):
            return cls()
        monitor = data.get("monitor")
        monitor = monitor if isinstance(monitor, dict) else {}
        side = data.get("side") if data.get("side") in ("left", "right") else "left"
        top = data.get("top") if isinstance(data.get("top"), int) else 0
        return cls(side, max(0, top), Monitor(str(monitor.get("name", "")), str(monitor.get("serial", "")), int(monitor.get("w") or 0), int(monitor.get("h") or 0)))


def find_monitor(saved: Monitor, monitors: Sequence[Monitor]) -> int | None:
    """Which of ``monitors`` is the one saved, best match first: all three things, then its serial number, then its name and
    size. None if it's gone, and the panel goes to the main monitor until it's back."""
    if not saved.name and not saved.serial:
        return None
    for test in (lambda m: m == saved,
                 lambda m: bool(saved.serial) and m.serial == saved.serial,
                 lambda m: m.name == saved.name and (m.w, m.h) == (saved.w, saved.h)):
        for i, m in enumerate(monitors):
            if test(m):
                return i
    return None


def covers(front: Rect, monitor: Rect) -> bool:
    """Decision 223: whether a window fills the monitor. A maximized window stops short of the taskbar, so it doesn't."""
    return front.x <= monitor.x and front.y <= monitor.y and front.right >= monitor.right and front.bottom >= monitor.bottom
