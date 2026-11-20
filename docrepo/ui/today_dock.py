"""The Today side panel docked at its edge (release 5.178, the design workspace's ``docs/mods/today-docked-plan.md``,
decisions 833 to 835): the panel's half of it, beside ``docrepo/appbar.py``, which talks to Windows.

**Dock at this edge**, a ticked line on the panel's top-line menu (kept in ``app_state`` as ``today_panel_docked``, off to
start), registers the panel as an app bar on its side of its screen, for its width at rest and the screen's full height:
maximised and snapped windows stop at it, and the panel fills the strip. Under the pointer it still widens over the other
windows; the strip stays the width at rest. The grip's drag, a drag to the other side and Move to next screen move the
strip; closing the panel, unticking the line and quitting give it back (and ``atexit``, should Python end another way).
While another program is full screen the panel hides and the strip stays, as Windows lets a full-screen window cover an
app bar. A refusal at any step floats the panel, unticks the line and says so. Not on Windows, or offscreen, docking does
nothing and the line is greyed.

Every Windows call goes through one ``api`` object (``appbar.WindowsApi``); ``API``, here, is the stand-in tests put in its
place. Nothing here ever docks on this computer: the tests run offscreen, with the stand-in.
"""
from __future__ import annotations

import atexit
import contextlib
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

from docrepo import appbar, db
from docrepo.panel_rules import Rect, dock_rect
from docrepo.ui import look

if TYPE_CHECKING:
    from docrepo.ui.today_panel import TodayPanel

log = logging.getLogger(__name__)

#: Whether the owner ticked Dock at this edge (decision 833), in ``app_state``.
DOCKED_KEY = "today_panel_docked"
LINE = "Dock at this edge"
REFUSED = "Couldn't dock here, so it's floating."
#: The stand-in for Windows that tests put here. None: Windows' own, where there is one (``appbar.system_api``).
API: appbar.Api | None = None


def api() -> appbar.Api | None:
    """What talks to Windows, or None where docking does nothing (decision 835)."""
    return API if API is not None else appbar.system_api(QGuiApplication.platformName())


class Dock:
    """One panel's strip: whether it's wanted, the app bar, and the strip Windows gave (in Windows' pixels)."""

    def __init__(self, panel: TodayPanel) -> None:
        self.panel = panel
        self.bar: appbar.AppBar | None = None
        self.strip: appbar.Box | None = None
        self._atexit = False

    # ---- the owner's tick ----
    def wanted(self) -> bool:
        return db.get_state(self.panel.ctx.conn, DOCKED_KEY) == "1"

    def can(self) -> bool:
        """Whether the line can be ticked: on Windows' own desktop only."""
        return api() is not None

    def set_wanted(self, on: bool) -> None:
        """The line ticked or unticked: docked at once, or the strip given back, and the panel placed again."""
        self.panel.ctx.keep_state(DOCKED_KEY, "1" if on else "0")
        if on:
            self.dock()
        else:
            self.undock()
        self.panel.place_window(animate=False)

    # ---- Windows ----
    def dock(self) -> bool:
        """Ask Windows for the strip at the panel's side of its screen, its width at rest: registered once, moved after.
        True when it's docked; a refusal floats the panel, unticks the line and says so (decision 835)."""
        if not self.wanted() or not self.panel.user_open:
            return False
        talk = api()
        if talk is None:
            return False
        screen = self.panel._screen()
        ratio = screen.devicePixelRatio()
        g = screen.geometry()
        native = Rect(g.x(), g.y(), round(g.width() * ratio), round(g.height() * ratio))
        r = dock_rect(native, self.panel.place_.side, round(self.panel.rest_width() * ratio))
        if self.bar is None:
            self.bar = appbar.AppBar(int(self.panel.winId()), talk)
            if not self._atexit:
                atexit.register(self.undock)  # should Python end without aboutToQuit (decision 835)
                self._atexit = True
        got = self.bar.dock(appbar.Box(r.x, r.y, r.right, r.bottom), self.panel.place_.side)
        if got is None:
            self.strip = None
            self.panel.ctx.keep_state(DOCKED_KEY, "0")
            self.panel.tell_state(REFUSED, None)
            log.info("Today panel: docking refused; floating")
            return False
        self.strip = got
        look.square(self.panel, True)  # square against the screen's edge (release 5.187)
        return True

    def undock(self) -> None:
        """Give the strip back; nothing when there's none."""
        if self.bar is not None:
            self.bar.undock()
            with contextlib.suppress(RuntimeError):  # at exit the panel may be gone already
                look.square(self.panel, False)
        self.strip = None

    def rect(self) -> QRect | None:
        """The strip in Qt's pixels, for the panel's place: Qt keeps a screen's top left and scales its size."""
        if self.strip is None:
            return None
        screen = self.panel._screen()
        g, ratio = screen.geometry(), screen.devicePixelRatio()
        s = self.strip

        def back(value: int, origin: int) -> int:
            return origin + round((value - origin) / ratio)

        left, top = back(s.left, g.x()), back(s.top, g.y())
        return QRect(left, top, back(s.right, g.x()) - left, back(s.bottom, g.y()) - top)

    def moved(self) -> None:
        """The panel's place or width at rest changed: the strip moves with it."""
        if self.strip is not None or (self.wanted() and self.panel.user_open):
            self.dock()
