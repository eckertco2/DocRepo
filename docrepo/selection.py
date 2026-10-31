"""The window you were in, and what's selected in it (releases 5.41 and 5.42; ``docs/ui-design/wheel-design.md``, section 5).

``snapshot`` is taken at the hotkey: the foreground window, its top-level owner, class, process and program, and for File
Explorer its front tab. Windows answers all of it without asking the other program, so the wheel is never slowed and
nothing is read from Outlook or Explorer unless the Capture wheel's "Email or file" is picked. No keystrokes are ever sent
to the other program, and no keyboard hook is used.

``read`` decides what to read from a snapshot; its COM calls are passed in, so the tests use fakes.
"""
from __future__ import annotations

import ctypes
import logging
import os
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

EXPLORER_CLASSES = ("CabinetWClass", "ExploreWClass")
DESKTOP_CLASSES = ("Progman", "WorkerW")
OUTLOOK_MAIN = "rctrl_renwnd32"  # both Outlook's main window and an email open on its own
#: Not windows you were "in", for placing a wheel.
NOT_A_WINDOW = (*DESKTOP_CLASSES, "Shell_TrayWnd", "Shell_SecondaryTrayWnd")


@dataclass(frozen=True)
class Snapshot:
    """What's known about the window you were in, without asking it anything."""

    hwnd: int = 0
    top: int = 0
    window_class: str = ""
    pid: int = 0
    program: str = ""  # the executable's name, lower case
    tab: int = 0  # File Explorer's front tab (its ShellTabWindowClass child), on Windows 11

    @property
    def kind(self) -> str:
        """"explorer", "desktop", "outlook" or "" for anything else."""
        if self.window_class in EXPLORER_CLASSES:
            return "explorer"
        if self.window_class in DESKTOP_CLASSES:
            return "desktop"
        if self.window_class == OUTLOOK_MAIN and self.program == "outlook.exe":
            return "outlook"
        return ""


def foreground() -> int:
    """The foreground window. One fast call, and it has to come before the wheel takes the foreground."""
    return int(ctypes.windll.user32.GetForegroundWindow() or 0) if os.name == "nt" else 0


def message_age_ms() -> int:
    """How long the message being handled waited in the queue, in ms (Windows' tick is about 15 ms)."""
    if os.name != "nt":
        return 0
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    age = (kernel32.GetTickCount() - user32.GetMessageTime()) & 0x7FFFFFFF
    return age if age < 5000 else 0


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(wintypes.HWND(hwnd), buffer, 256)
    return buffer.value


def _program(pid: int) -> str:
    """The program's file name, from its process (PROCESS_QUERY_LIMITED_INFORMATION is enough)."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(wintypes.HANDLE(handle), 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.lower()
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(handle))
    return ""


def _front_tab(top: int) -> int:
    """File Explorer's front tab on Windows 11: the first visible ShellTabWindowClass child of the window. FindWindowEx goes
    through a window's children top first, so the first visible one is the tab in front."""
    user32 = ctypes.windll.user32
    user32.FindWindowExW.restype = wintypes.HWND
    child = None
    while True:
        child = user32.FindWindowExW(wintypes.HWND(top), child, "ShellTabWindowClass", None)
        if not child:
            return 0
        if user32.IsWindowVisible(child):
            return int(child)


def snapshot(hwnd: int) -> Snapshot:
    """What's known about ``hwnd``. Windows answers without asking the program."""
    if os.name != "nt" or not hwnd:
        return Snapshot(hwnd)
    user32 = ctypes.windll.user32
    user32.GetAncestor.restype = wintypes.HWND
    top = int(user32.GetAncestor(wintypes.HWND(hwnd), 2) or hwnd)  # GA_ROOT
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(top), ctypes.byref(pid))
    window_class = _class_name(top)
    return Snapshot(hwnd, top, window_class, pid.value, _program(pid.value), _front_tab(top) if window_class in EXPLORER_CLASSES else 0)


def still_there(snap: Snapshot) -> bool:
    """Whether the window still exists, in the same process: a closed window's handle can be used again by another."""
    if os.name != "nt" or not snap.top:
        return False
    user32 = ctypes.windll.user32
    if not user32.IsWindow(wintypes.HWND(snap.top)):
        return False
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(snap.top), ctypes.byref(pid))
    return pid.value == snap.pid


def monitor_of(hwnd: int) -> tuple[int, int] | None:
    """The top left of the monitor holding ``hwnd``, in Windows' pixels; None when there's no window you were in (the
    desktop or the taskbar), or none at all."""
    if os.name != "nt" or not hwnd or _class_name(hwnd) in NOT_A_WINDOW:
        return None

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), 0)  # MONITOR_DEFAULTTONULL
    if not monitor:
        return None
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    if not user32.GetMonitorInfoW(wintypes.HANDLE(monitor), ctypes.byref(info)):
        return None
    return info.rcMonitor.left, info.rcMonitor.top


def bring_forward(hwnd: int) -> None:
    """Give the keyboard back to a window, if it's still there. DocRepo is in front, so Windows allows it."""
    if os.name == "nt" and hwnd and ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)):
        ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))


# ---- reading what's selected (release 5.42) ----
@dataclass
class Selected:
    """What a read found: ``paths`` for files, ``source`` "outlook" for the email to read, and ``note`` when there's
    nothing to add or something was left out, in words."""

    paths: list[str] = field(default_factory=list)
    source: str = ""
    note: str = ""


def explorer_window_for(windows, snap: Snapshot, tab_of: Callable[[object], int] | None = None):
    """From ``Shell.Application.Windows()``, the entry for the snapshot's window: its front tab on Windows 11, whose entries
    all share the same HWND, so the tab's own window from IShellBrowser tells them apart."""
    tab_of = tab_of or _tab_of
    same = []
    for w in windows:
        try:
            if int(w.HWND) == snap.top:
                same.append(w)
        except Exception:  # noqa: BLE001 - a window closing as we look
            continue
    if len(same) <= 1 or not snap.tab:
        return same[0] if same else None
    return next((w for w in same if tab_of(w) == snap.tab), same[0])


def _tab_of(window) -> int:
    """A Shell window's tab: the window of its top-level browser. 0 if it can't say."""
    try:
        import pythoncom  # noqa: PLC0415 - only where Windows has it
        from win32com.shell import shell  # noqa: PLC0415

        provider = window._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
        return int(provider.QueryService(shell.SID_STopLevelBrowser, pythoncom.IID_IOleWindow).GetWindow())
    except Exception:  # noqa: BLE001 - fall back on the first entry for the window
        return 0


def items_to_paths(items) -> tuple[list[str], list[str]]:
    """From ``SelectedItems()``, the paths of items on disk, and what was left out and why, in words."""
    paths, left = [], []
    for item in items:
        try:
            name, path = str(item.Name), str(item.Path)
            on_disk = bool(item.IsFileSystem)
        except Exception:  # noqa: BLE001 - an item that's gone as we read it
            continue
        if on_disk and path:
            paths.append(path)
        else:
            left.append(name)
    return paths, left


def read_explorer(shell, snap: Snapshot, tab_of: Callable[[object], int] | None = None) -> Selected:
    """File Explorer's selected files, or the desktop's. ``shell`` is ``Shell.Application``."""
    if snap.kind == "desktop":
        window = shell.Windows().FindWindowSW(0, 0, 8, 0, 1)  # SWC_DESKTOP, SWFO_NEEDDISPATCH
    else:
        window = explorer_window_for(shell.Windows(), snap, tab_of)
    if window is None:
        return Selected(note="DocRepo couldn't find that File Explorer window. Drop files here instead.")
    items = window.Document.SelectedItems()
    paths, left = items_to_paths(items)
    where = "on the desktop" if snap.kind == "desktop" else "in File Explorer"
    if not paths and not left:
        return Selected(note=f"Nothing is selected {where}. Drop files here, or add this folder as a link.")
    note = f"{', '.join(left)} {'is' if len(left) == 1 else 'are'}n't files, so {'it was' if len(left) == 1 else 'they were'} left out." if left else ""
    return Selected(paths=paths, note=note)


def plan(snap: Snapshot | None) -> str:
    """What the pick reads: "explorer", "outlook", or "" for nothing."""
    if snap is None or not snap.top or not still_there(snap):
        return ""
    return {"explorer": "explorer", "desktop": "explorer", "outlook": "outlook"}.get(snap.kind, "")


def read_selected(snap: Snapshot) -> Selected:
    """Read File Explorer's selection through the Shell's COM objects, on whichever thread calls it. Never raises."""
    try:
        import pythoncom  # noqa: PLC0415
        import win32com.client  # noqa: PLC0415
    except ImportError:
        return Selected(note="DocRepo can't read File Explorer here. Drop files here instead.")
    pythoncom.CoInitialize()
    try:
        return read_explorer(win32com.client.Dispatch("Shell.Application"), snap)
    except Exception as e:  # noqa: BLE001 - whatever the Shell raises: a line in the window, and in the log
        log.warning("File Explorer's selection couldn't be read: %s", type(e).__name__)
        return Selected(note="File Explorer didn't say what's selected. Drop files here instead.")
    finally:
        pythoncom.CoUninitialize()
