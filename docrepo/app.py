"""The capture app: runs in the background with a tray icon, and opens the capture window on the hotkey.

Run it with ``pythonw -m docrepo app`` (no console window) or ``python -m docrepo app``.
Only one copy runs per data root; starting it again shows the open copy's window.
At its first start each day it rebuilds the capacity calendar and the generated
pages, so routine tasks roll forward. Reminders show as Windows notifications.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from datetime import datetime, time
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QObject, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QSystemTrayIcon

from docrepo import capacity, db, hotkey, people, prompts
from docrepo.config import Settings
from docrepo.dates import long_date
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.safe_fs import SafeFS
from docrepo.schedule import due_of, is_open
from docrepo.ui.capture_window import CaptureWindow
from docrepo.ui.context import AppContext

log = logging.getLogger(__name__)

LOCK_FILE = Path("System") / "capture-app.lock"
WINDOW_TITLE = "DocRepo Capture"
SHOW_MESSAGE = "DocRepo.ShowCapture"
HOTKEY_ID = 1
MAX_SINGLE_REMINDERS = 3


def make_icon() -> QIcon:
    """DocRepo's tray icon, drawn here so no image file is needed: a blue square with a white D."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#1d5e98"))
    painter.setPen(QColor("#1d5e98"))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), 0x84, "D")  # centred
    painter.end()
    return QIcon(pixmap)


def show_message_id() -> int:
    return ctypes.windll.user32.RegisterWindowMessageW(SHOW_MESSAGE) if os.name == "nt" else 0


def wake_running_copy() -> bool:
    """Ask the copy that's already running to show its capture window. True if one was found."""
    if os.name != "nt":
        return False
    hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    ctypes.windll.user32.PostMessageW(hwnd, show_message_id(), 0, 0)
    return True


class _MessageFilter(QAbstractNativeEventFilter):
    """Hears the hotkey (WM_HOTKEY) and a second copy's request to show the window."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__()
        self.app = app
        self.show_id = show_message_id()

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt's name
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == hotkey.WM_HOTKEY and msg.wParam == HOTKEY_ID:
            self.app.toggle_window()
            return True, 0
        if self.show_id and msg.message == self.show_id:
            self.app.window.show_capture()
            return True, 0
        return False, 0


class CaptureApp(QObject):
    def __init__(self, qt: QApplication, ctx: AppContext) -> None:
        super().__init__()
        self.qt = qt
        self.ctx = ctx
        self.paused = False
        self.reminder_task: str | None = None
        self.tray = QSystemTrayIcon(make_icon(), qt)
        self.tray.setToolTip("DocRepo")
        ctx.notify = self.notify
        self.window = CaptureWindow(ctx)
        self.hwnd = int(self.window.winId())
        menu = QMenu()
        menu.addAction("New capture", lambda: self.window.show_capture())
        menu.addAction("Mods log", lambda: self.window.show_capture(mods=True))
        self.pause_action = QAction("Pause hotkey", menu)
        self.pause_action.triggered.connect(self.toggle_pause)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.messageClicked.connect(self._message_clicked)
        self.tray.show()
        self.filter = _MessageFilter(self)
        qt.installNativeEventFilter(self.filter)
        self.register_hotkey()
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ---- the hotkey ----
    def register_hotkey(self) -> None:
        keys = self.ctx.settings.hotkey
        try:
            ok = hotkey.register(self.hwnd, HOTKEY_ID, keys)
        except ValueError as e:
            self.notify("Hotkey", f"{keys} isn't a hotkey DocRepo can use: {e} Set another with: python -m docrepo set-hotkey KEYS")
            return
        if not ok:
            log.warning("hotkey %s is taken by another program", keys)
            self.notify("Hotkey taken", f"Another program uses {keys}. Choose another with: python -m docrepo set-hotkey \"Ctrl+Alt+Space\", "
                        "then start DocRepo again. The tray icon still opens the capture window.")
        else:
            log.info("hotkey %s registered", keys)

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            hotkey.unregister(self.hwnd, HOTKEY_ID)
        else:
            self.register_hotkey()
        self.pause_action.setText("Resume hotkey" if self.paused else "Pause hotkey")
        self.window.hotkey_label.setText("Hotkey paused" if self.paused else self.ctx.settings.hotkey)
        self.notify("Hotkey", f"Hotkey paused. {self.ctx.settings.hotkey} does nothing until you resume it." if self.paused else "Hotkey resumed.")

    def toggle_window(self) -> None:
        if self.window.isVisible() and self.window.isActiveWindow():
            self.window.hide()
        else:
            self.window.show_capture()

    def _tray_clicked(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.window.show_capture()

    # ---- notifications and reminders ----
    def notify(self, title: str, text: str) -> None:
        self.tray.showMessage(title, text, make_icon(), 6000)

    def _message_clicked(self) -> None:
        if self.reminder_task:
            self.window.show_capture(task=self.reminder_task, mode="update")
            self.reminder_task = None

    def show_reminders(self) -> int:
        """Show each open task's reminder that's due and hasn't been shown yet. Returns how many were shown."""
        conn, now = self.ctx.conn, self.ctx.now()
        today = now.date()
        model = Model(conn)
        shown = {(r["task"], r["reminder"]) for r in conn.execute("SELECT task, reminder FROM reminders_shown")}
        due = [t for t in model.tasks.values() if is_open(t) and t.reminder and t.reminder <= today.isoformat() and (t.id, t.reminder) not in shown]
        if not due:
            return 0
        if len(due) <= MAX_SINGLE_REMINDERS:
            lines = []
            for t in due:
                who = ", ".join(model.person_name(p) for p in t.assignees)
                d = due_of(t, today)
                lines.append(" · ".join(x for x in (t.title, who, f"{d.label.lower()} {long_date(d.date, today)}" if d else "") if x))
            self.reminder_task = due[0].id if len(due) == 1 else None
            self.notify("Reminder" if len(due) == 1 else f"{len(due)} reminders", "\n".join(lines))
        else:
            self.reminder_task = None
            self.notify(f"{len(due)} reminders today", ", ".join(t.title for t in due[:6]) + ("…" if len(due) > 6 else ""))
        with db.transaction(conn):
            conn.executemany("INSERT OR IGNORE INTO reminders_shown (task, reminder, shown) VALUES (?, ?, ?)",
                             [(t.id, t.reminder, now.strftime("%Y-%m-%d %H:%M:%S")) for t in due])
        log.info("reminders: shown for %s", ", ".join(t.id for t in due))
        return len(due)

    # ---- the daily work ----
    def daily(self) -> bool:
        """At the first start each day: rebuild the capacity calendar and the generated pages. True if it ran."""
        now = self.ctx.now()
        if db.get_state(self.ctx.conn, "daily") == now.date().isoformat():
            return False
        rows = capacity.rebuild_all(self.ctx.conn, now.date(), self.ctx.settings)
        pages = write_pages(Model(self.ctx.conn), self.ctx.data_root, self.ctx.fs, now.date(), now)
        db.set_state(self.ctx.conn, "daily", now.date().isoformat())
        log.info("daily start: %d calendar rows, %d pages written", rows, pages)
        return True

    def tick(self) -> None:
        """Every minute: the daily work after midnight, and reminders once it's past reminder_time."""
        try:
            self.daily()
            if self.ctx.now().time() >= _reminder_time(self.ctx.settings):
                self.show_reminders()
        except Exception:  # noqa: BLE001 - a background check must never stop the app
            log.exception("background check failed")

    def quit(self) -> None:
        hotkey.unregister(self.hwnd, HOTKEY_ID)
        self.tray.hide()
        self.qt.quit()


def _reminder_time(settings: Settings) -> time:
    try:
        return time.fromisoformat(settings.reminder_time)
    except ValueError:
        return time(8, 0)


def ask_who_i_am(ctx: AppContext) -> None:
    """The first time, ask for the owner's name and add them to the people list as me."""
    if ctx.settings.me:
        return
    name, ok = QInputDialog.getText(None, "DocRepo", "What's your name? DocRepo adds you to the people list as “me”,\n"
                                                     "so “I” and “me” in a capture mean you.")
    name = name.strip()
    if not ok or not name:
        return
    row = ctx.conn.execute("SELECT id FROM people WHERE lower(name) = lower(?)", (name,)).fetchone()
    ctx.settings.me = row["id"] if row else people.add_person(ctx.conn, name)
    ctx.settings.save(ctx.fs, ctx.data_root)
    log.info("first run: me is %s", ctx.settings.me)


def run(data_root: Path, settings: Settings, fs: SafeFS) -> int:
    """Start the capture app. Returns the exit code."""
    qt = QApplication.instance() or QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    qt.setApplicationName("DocRepo")
    qt.setFont(QFont("Segoe UI", 9))
    lock = QLockFile(str(fs.checked_path(data_root / LOCK_FILE)))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        if wake_running_copy():
            return 0
        print("DocRepo is already running, or its lock file is stuck:", data_root / LOCK_FILE, file=sys.stderr)
        return 1
    conn = db.connect(fs, data_root)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("no system tray; the capture window opens with the hotkey only")
    ask_who_i_am(ctx)
    app = CaptureApp(qt, ctx)
    app.daily()
    app.show_reminders()
    log.info("capture app started")
    code = qt.exec()
    conn.close()
    lock.unlock()
    log.info("capture app stopped")
    return code
