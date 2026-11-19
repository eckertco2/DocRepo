"""The Today panel docked at a screen edge (release 5.178, the design workspace's ``docs/mods/today-docked-plan.md``,
decisions 833 to 839). No Qt.

Windows lets a window register as an **app bar** (``SHAppBarMessage`` in shell32): it reserves a strip of a screen, and
Windows keeps maximised and snapped windows out of it, as it does for the taskbar. It asks for no package and changes no
Windows setting. ``AppBar`` registers a window (``dock``), moves its strip (``move``) and gives it back (``undock``); every
Windows call goes through one ``api`` object, ``WindowsApi`` on Windows, which the tests replace with a stand-in that
records the calls and answers as told. Nothing here runs on this computer's desktop: the panel docks only on the owner's
tick, and never offscreen (``system_api``).

``try_out`` is ``python -m docrepo appbar-try`` (decision 836): a plain strip of its own, registered for a while and given
back (or, with ``leave``, not), with the screen's working area before, during and after, and each answer Windows gave. It's
for the corporate computer, where what Windows does with a strip left behind is found out.
"""
from __future__ import annotations

import ctypes
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

# SHAppBarMessage's messages, edges and notice (shellapi.h).
ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS = 0x0, 0x1, 0x2, 0x3
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3
ABN_POSCHANGED = 0x1
#: The message Windows sends the docked window, its notice in its wParam (WM_APP + 0x5DC, DocRepo's own).
CALLBACK_MESSAGE = 0x8000 + 0x5DC
SPI_GETWORKAREA = 0x0030
EDGES = {"left": ABE_LEFT, "right": ABE_RIGHT}
NAMES = {ABM_NEW: "ABM_NEW", ABM_REMOVE: "ABM_REMOVE", ABM_QUERYPOS: "ABM_QUERYPOS", ABM_SETPOS: "ABM_SETPOS"}


@dataclass(frozen=True)
class Box:
    """A rectangle as Windows gives one: left, top, right and bottom, in Windows' pixels."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def __str__(self) -> str:
        return f"{self.left},{self.top} to {self.right},{self.bottom} ({self.width} x {self.height})"


class Api(Protocol):
    """What touches Windows: one call of ``SHAppBarMessage``, and the main screen's working area."""

    def message(self, msg: int, hwnd: int, edge: int, box: Box) -> tuple[int, Box]: ...

    def work_area(self) -> Box: ...


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class APPBARDATA(ctypes.Structure):
    """shellapi.h's APPBARDATA."""

    _fields_ = [("cbSize", ctypes.c_uint32), ("hWnd", ctypes.c_void_p), ("uCallbackMessage", ctypes.c_uint32),
                ("uEdge", ctypes.c_uint32), ("rc", _RECT), ("lParam", ctypes.c_ssize_t)]


class WindowsApi:
    """The one object that calls Windows (shell32's ``SHAppBarMessage``, user32's ``SystemParametersInfoW``). Only made on
    Windows (``system_api``)."""

    def message(self, msg: int, hwnd: int, edge: int, box: Box) -> tuple[int, Box]:
        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        data.hWnd = ctypes.c_void_p(hwnd)
        data.uCallbackMessage = CALLBACK_MESSAGE
        data.uEdge = edge
        data.rc = _RECT(box.left, box.top, box.right, box.bottom)
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        shell32.SHAppBarMessage.restype = ctypes.c_size_t
        answer = int(shell32.SHAppBarMessage(ctypes.c_uint32(msg), ctypes.byref(data)))
        return answer, Box(data.rc.left, data.rc.top, data.rc.right, data.rc.bottom)

    def work_area(self) -> Box:
        r = _RECT()
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)  # type: ignore[attr-defined]
        return Box(r.left, r.top, r.right, r.bottom)


def system_api(platform: str = "") -> Api | None:
    """Windows' own, or None where docking does nothing (decision 835): not Windows, or Qt's offscreen platform, as the
    tests and the pictures run."""
    if os.name != "nt" or platform == "offscreen" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return None
    return WindowsApi()


@dataclass
class AppBar:
    """One window's strip (decisions 834 and 835). ``dock`` registers it and asks Windows for a strip at ``edge`` ("left" or
    "right") as wide as ``box``; ``move`` asks again; ``undock`` gives it back, once. A refusal at any step (an answer of 0,
    or a strip narrower than asked) gives back what was registered and answers None. ``said`` keeps each call and answer,
    in words, for the try-out's report."""

    hwnd: int
    api: Api
    registered: bool = False
    said: list[str] = field(default_factory=list)

    def _ask(self, msg: int, edge: int, box: Box) -> tuple[int, Box]:
        answer, got = self.api.message(msg, self.hwnd, edge, box)
        self.said.append(f"{NAMES.get(msg, msg)}: answered {answer}" + (f", strip {got}" if msg in (ABM_QUERYPOS, ABM_SETPOS) else ""))
        return answer, got

    def dock(self, box: Box, edge: str) -> Box | None:
        """Register (when it isn't yet), then ask for the strip and set it. The strip Windows gave, or None."""
        side = EDGES[edge]
        if not self.registered:
            answer, _ = self._ask(ABM_NEW, side, box)
            if not answer:
                log.info("app bar: Windows refused to register it")
                return None
            self.registered = True
        answer, asked = self._ask(ABM_QUERYPOS, side, box)
        if not answer:
            return self._refused("its place")
        # Windows moves the strip clear of the taskbar and other app bars: keep its own width from the edge it took.
        want = box.width
        asked = Box(asked.left, asked.top, asked.left + want, asked.bottom) if side == ABE_LEFT else Box(asked.right - want, asked.top, asked.right, asked.bottom)
        answer, got = self._ask(ABM_SETPOS, side, asked)
        if not answer or got.width < want:
            return self._refused("its width")
        return got

    def move(self, box: Box, edge: str) -> Box | None:
        """The strip moved or made wider or narrower: asked for again, the registration kept."""
        return self.dock(box, edge)

    def undock(self) -> bool:
        """Give the strip back. True when it was registered; a second call does nothing."""
        if not self.registered:
            return False
        self.registered = False
        self._ask(ABM_REMOVE, ABE_LEFT, Box(0, 0, 0, 0))
        return True

    def _refused(self, what: str) -> None:
        log.info("app bar: Windows refused %s; given back", what)
        self.undock()
        return None


# ---- the try-out (decision 836): python -m docrepo appbar-try ----
@dataclass
class Strip:
    """The try-out's own plain strip window: its handle, and how to close it."""

    hwnd: int
    close: Callable[[], None]


def try_out(api: Api, open_strip: Callable[[Box], Strip], wait: Callable[[float], None], *, side: str = "right", width: int = 240,
            seconds: float = 30, leave: bool = False) -> str:
    """Register a plain strip ``width`` px wide at ``side`` of the main screen, wait ``seconds``, give it back (or, with
    ``leave``, not), and report the working area before, during and after, and each answer Windows gave. Measurements
    only: no title, no name."""
    lines = ["# appbar-try", "", f"- Side: {side}, width {width} px, {seconds:g} s" + (", left registered (--leave)" if leave else "")]
    before = api.work_area()
    lines.append(f"- Working area before: {before}")
    whole = Box(before.left, before.top, before.right, before.bottom)
    want = Box(whole.left, whole.top, whole.left + width, whole.bottom) if side == "left" else Box(whole.right - width, whole.top, whole.right, whole.bottom)
    strip = open_strip(want)
    bar = AppBar(strip.hwnd, api)
    got = bar.dock(want, side)
    lines.append(f"- The strip: {got}" if got is not None else "- The strip: refused, given back")
    during = api.work_area()
    lines.append(f"- Working area during: {during}")
    if got is not None:
        wait(seconds)
    if not leave:
        bar.undock()
        strip.close()
        after = api.work_area()
        lines.append(f"- Working area after: {after}" + (" (as before)" if after == before else " (not as before)"))
    else:
        lines.append("- Left registered on purpose (--leave): run appbar-try --check to see whether Windows took it back.")
    lines += ["", "## What Windows answered", "", *(f"- {s}" for s in bar.said), ""]
    return "\n".join(lines)


def check(api: Api) -> str:
    """``appbar-try --check``: the working area now, to show whether a strip left behind was taken back."""
    return "\n".join(["# appbar-try --check", "", f"- Working area now: {api.work_area()}", ""])
