"""Bringing a window to the front, restored if it was minimized (release 5.106, decision 405).

A hotkey, a wheel's slice or a link brings a window forward with ``show()``, ``raise_()`` and ``activateWindow()``. None
of the three restores a minimized window: Qt's ``show()`` keeps a minimized or maximized state as it is, on purpose. So a
hotkey for a window that had been minimized only flashed its button on the taskbar. ``bring_to_front`` takes the
minimized state off first; a window that was maximized before it was minimized comes back maximized.

Windows may still refuse the foreground to a program that didn't have it, and only flash its taskbar button, as when
the Today side panel, which never takes the keyboard, opens the workspace (release 5.165, decision 771). So when the
window isn't in front after ``activateWindow``, ``bring_to_front`` attaches to the foreground window's input thread, sets
the foreground and detaches again (``AttachThreadInput`` and ``SetForegroundWindow``, through ``ctypes``, as
``hotkey.py`` and ``selection.py`` call Windows). Only on Windows' own platform, never offscreen, and a refusal is
logged, never raised.
"""
from __future__ import annotations

import ctypes
import logging
import os
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

#: The fallback that takes the foreground when Windows refused it, given the window's handle. Tests replace it.
FOREGROUND: Callable[[int], bool] | None = None


def restored_state(state: Qt.WindowState) -> Qt.WindowState:
    """A window's state without Minimized, and active; Maximized and Full screen stay as they were."""
    return (state & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive


def bring_to_front(window: QWidget) -> None:
    """Show ``window``, restored if it was minimized, in front, with the keyboard."""
    if window.windowState() & Qt.WindowState.WindowMinimized:
        window.setWindowState(restored_state(window.windowState()))
    window.show()
    window.raise_()
    window.activateWindow()
    take_foreground(window)


def take_foreground(window: QWidget) -> bool:
    """When Windows left another program in front, take the foreground for ``window`` (decision 771). True when it's in
    front, or nothing needed doing; False when Windows refused, which is logged."""
    starter = FOREGROUND if FOREGROUND is not None else (_attach_and_set if _on_windows() else None)
    if starter is None:
        return True
    try:
        return bool(starter(int(window.winId())))
    except Exception as e:  # noqa: BLE001 - Windows can refuse in many ways; the window is shown either way
        log.warning("couldn't bring a window to the front: %s", type(e).__name__)
        return False


def _on_windows() -> bool:
    return os.name == "nt" and QGuiApplication.platformName() == "windows"


def _attach_and_set(hwnd: int) -> bool:
    """Windows' own way past its foreground lock: share the foreground window's input for a moment, set the foreground,
    and let go. Nothing changes when the window is in front already."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    front = int(user32.GetForegroundWindow() or 0)
    if not hwnd or front == hwnd:
        return True
    theirs = int(user32.GetWindowThreadProcessId(ctypes.c_void_p(front), None) or 0) if front else 0
    mine = int(kernel32.GetCurrentThreadId())
    attached = bool(theirs and theirs != mine and user32.AttachThreadInput(theirs, mine, True))
    try:
        user32.BringWindowToTop(ctypes.c_void_p(hwnd))
        done = bool(user32.SetForegroundWindow(ctypes.c_void_p(hwnd)))
    finally:
        if attached:
            user32.AttachThreadInput(theirs, mine, False)
    if not done:
        log.info("Windows kept another program in front")
    return done
