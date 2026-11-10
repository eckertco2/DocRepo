"""Bringing a window to the front, restored if it was minimized (release 5.106, decision 405).

A hotkey, a wheel's slice or a link brings a window forward with ``show()``, ``raise_()`` and ``activateWindow()``. None
of the three restores a minimized window: Qt's ``show()`` keeps a minimized or maximized state as it is, on purpose. So a
hotkey for a window that had been minimized only flashed its button on the taskbar. ``bring_to_front`` takes the
minimized state off first; a window that was maximized before it was minimized comes back maximized.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


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
