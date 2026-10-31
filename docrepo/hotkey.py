"""The global hotkey, through Windows' own RegisterHotKey.

Windows tells DocRepo only when its own key combination is pressed. Nothing here
watches the keyboard, so security software has nothing to flag as a keylogger.
"""
from __future__ import annotations

import ctypes
import os
import re

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E, "home": 0x24,
        "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "pause": 0x13, "backquote": 0xC0, "`": 0xC0, "-": 0xBD, "=": 0xBB, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE,
        "/": 0xBF, "\\": 0xDC, "[": 0xDB, "]": 0xDD}


#: Each hotkey: its setting in settings.json and what it does. Only the first has a default; the others (mods log round 1:
#: M0002, M0010, M0020; round 2: M0039; round 3: M0053) are off until set. A hotkey's Windows ID is its place here, from 1.
HOTKEYS: tuple[tuple[str, str], ...] = (
    ("hotkey", "Open the capture window"),
    ("browse_hotkey", "Open the browse tool"),
    ("note_hotkey", "A note"),
    ("new_task_hotkey", "A new task"),
    ("update_hotkey", "An update"),
    ("agenda_hotkey", "Add to agenda"),
    ("today_hotkey", "A quick task on Today"),
    ("pin_hotkey", "Pin the capture window, or bring it back"),
    ("outlook_hotkey", "Add the email selected in Outlook"),
    ("today_panel_hotkey", "Open or close the Today side panel"),  # release 5.43: decision 216, no keys until set
)
HOTKEY_IDS = {setting: n for n, (setting, _label) in enumerate(HOTKEYS, 1)}
#: The wheels' hotkeys (release 5.41, decisions 173 and 216): a wheel's ID is this plus its place in Config/wheels.jsonc.
WHEEL_ID_BASE = 100
#: The keys Settings offers for the others (mods log round 2, M0036): Ctrl+Shift and the topic's letter, as the owner chose.
#: While DocRepo runs, a global hotkey is taken from every other program, such as Outlook's Ctrl+Shift+N for a new note.
SUGGESTED = {"browse_hotkey": "Ctrl+Shift+B", "note_hotkey": "Ctrl+Shift+N", "new_task_hotkey": "Ctrl+Shift+T", "update_hotkey": "Ctrl+Shift+U",
             "agenda_hotkey": "Ctrl+Shift+A", "today_hotkey": "Ctrl+Shift+D",
             # Release 5.33.1: E for email. While DocRepo runs it takes Outlook's own Ctrl+Shift+E (a new folder).
             "outlook_hotkey": "Ctrl+Shift+E"}


def parse_hotkey(text: str) -> tuple[int, int]:
    """(modifiers, virtual key) for a hotkey such as "Ctrl+Shift+Space". It needs Ctrl, Alt or Win, and one key."""
    parts = [p.strip() for p in re.split(r"\s*\+\s*", text.strip()) if p.strip()]
    if not parts:
        raise ValueError("The hotkey is empty.")
    *mods, key = parts
    modifiers = 0
    for m in mods:
        if m.lower() not in MODIFIERS:
            raise ValueError(f"{m!r} isn't a modifier. Use Ctrl, Alt, Shift and Win.")
        modifiers |= MODIFIERS[m.lower()]
    if not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise ValueError("A hotkey needs Ctrl, Alt or Win, so it doesn't get in the way of typing.")
    k = key.lower()
    if k in KEYS:
        vk = KEYS[k]
    elif re.fullmatch(r"[a-z0-9]", k):
        vk = ord(k.upper())
    elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", k):
        vk = 0x70 + int(k[1:]) - 1
    else:
        raise ValueError(f"{key!r} isn't a key DocRepo knows. Use a letter, a digit, F1 to F24, Space and so on.")
    return modifiers, vk


def register(hwnd: int, hotkey_id: int, text: str) -> bool:
    """Ask Windows to send WM_HOTKEY to ``hwnd`` for this hotkey. False if another program already has it."""
    if os.name != "nt":
        return False
    modifiers, vk = parse_hotkey(text)
    return bool(ctypes.windll.user32.RegisterHotKey(ctypes.c_void_p(hwnd), hotkey_id, modifiers | MOD_NOREPEAT, vk))


def unregister(hwnd: int, hotkey_id: int) -> None:
    if os.name == "nt":
        ctypes.windll.user32.UnregisterHotKey(ctypes.c_void_p(hwnd), hotkey_id)


def is_held(modifiers: int, vk: int) -> bool:
    """Whether a hotkey's own keys are all down: read for a wheel's tap or hold, only while it's open, and for no other key."""
    if os.name != "nt":
        return False
    state = ctypes.windll.user32.GetAsyncKeyState

    def down(*keys: int) -> bool:
        return any(state(k) & 0x8000 for k in keys)

    return (down(vk) and (not modifiers & MOD_CONTROL or down(0x11)) and (not modifiers & MOD_SHIFT or down(0x10))
            and (not modifiers & MOD_ALT or down(0x12)) and (not modifiers & MOD_WIN or down(0x5B, 0x5C)))
