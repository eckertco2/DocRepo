"""The app: runs in the background with a tray icon, opens the capture window on the hotkey, and the browse tool.

Run it with ``pythonw -m docrepo app`` (no console window) or ``python -m docrepo app``;
``browse`` instead of ``app`` opens the browse tool as it starts. Only one copy
runs per data root; starting it again shows the open copy's window. At its first
start each day it rebuilds the capacity calendar and the generated pages, so
routine tasks roll forward. Reminders show as Windows notifications.
"""
from __future__ import annotations

import ctypes
import dataclasses
import logging
import os
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from datetime import datetime, time
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QObject, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QSystemTrayIcon

from docrepo import backup, capacity, db, diagnose, hotkey, people, prompts, search
from docrepo.config import Settings
from docrepo.dates import long_date
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.safe_fs import SafeFS
from docrepo.schedule import due_of, is_open
from docrepo.ui.browse_window import BrowseWindow
from docrepo.ui.capture_window import CaptureWindow
from docrepo.ui.context import AppContext
from docrepo.ui.style import use_light_theme

log = logging.getLogger(__name__)

LOCK_FILE = Path("System") / "capture-app.lock"
WINDOW_TITLE = "DocRepo Capture"
SHOW_MESSAGE = "DocRepo.ShowCapture"
SHOW_BROWSE_MESSAGE = "DocRepo.ShowBrowse"
HOTKEY_ID = hotkey.HOTKEY_IDS["hotkey"]
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


def show_message_id(name: str = SHOW_MESSAGE) -> int:
    return ctypes.windll.user32.RegisterWindowMessageW(name) if os.name == "nt" else 0


def wake_running_copy(browse: bool = False) -> bool:
    """Ask the copy that's already running to show its capture window, or its browse tool. True if one was found."""
    if os.name != "nt":
        return False
    hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    ctypes.windll.user32.PostMessageW(hwnd, show_message_id(SHOW_BROWSE_MESSAGE if browse else SHOW_MESSAGE), 0, 0)
    return True


class _MessageFilter(QAbstractNativeEventFilter):
    """Hears the hotkey (WM_HOTKEY) and a second copy's request to show the window."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__()
        self.app = app
        self.show_id = show_message_id()
        self.browse_id = show_message_id(SHOW_BROWSE_MESSAGE)

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt's name
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == hotkey.WM_HOTKEY and msg.wParam in self.app.hotkey_actions:
            self.app.hotkey_actions[msg.wParam]()
            return True, 0
        if self.show_id and msg.message == self.show_id:
            self.app.window.show_capture()
            return True, 0
        if self.browse_id and msg.message == self.browse_id:
            self.app.show_browse()
            return True, 0
        return False, 0


class CaptureApp(QObject):
    #: A backup finished on its own thread: its BackupResult, or the exception that stopped it.
    backup_finished = Signal(object)

    def __init__(self, qt: QApplication, ctx: AppContext) -> None:
        super().__init__()
        self.qt = qt
        self.ctx = ctx
        self.paused = False
        self.reminder_task: str | None = None
        self.reminder_many = False
        self.tray = QSystemTrayIcon(make_icon(), qt)
        self.tray.setToolTip("DocRepo")
        ctx.notify = self.notify
        ctx.settings_changed = self.settings_changed
        ctx.start_backup = self.start_backup
        self._backup_thread: threading.Thread | None = None
        self.backup_finished.connect(self._backup_done)
        self.window = CaptureWindow(ctx)
        self.hwnd = int(self.window.winId())
        self.browse = BrowseWindow(ctx, self.window)
        menu = QMenu()
        menu.addAction("New capture", lambda: self.window.show_capture())
        menu.addAction("Open browse tool", lambda: self.show_browse())
        menu.addAction("Mods log", lambda: self.window.show_capture(mods=True))
        self.pause_action = QAction("Pause hotkeys", menu)
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
        self.registered: list[int] = []
        #: What each hotkey's Windows ID does (hotkey.HOTKEYS).
        self.hotkey_actions: dict[int, Callable[[], None]] = {
            hotkey.HOTKEY_IDS["hotkey"]: self.toggle_window,
            hotkey.HOTKEY_IDS["browse_hotkey"]: lambda: self.show_browse(),
            hotkey.HOTKEY_IDS["note_hotkey"]: lambda: self.window.open_with_hotkey("note"),
            hotkey.HOTKEY_IDS["new_task_hotkey"]: lambda: self.window.open_with_hotkey("new_task"),
            hotkey.HOTKEY_IDS["update_hotkey"]: lambda: self.window.open_with_hotkey("update"),
            hotkey.HOTKEY_IDS["agenda_hotkey"]: lambda: self.window.open_with_hotkey("agenda"),
        }
        self.register_hotkey()
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ---- the hotkeys ----
    def register_hotkey(self) -> None:
        """Register the capture window's hotkey and each of the others that's set (hotkey.HOTKEYS)."""
        taken = []
        for setting, label in hotkey.HOTKEYS:
            keys = getattr(self.ctx.settings, setting)
            if not keys:
                continue
            hotkey_id = hotkey.HOTKEY_IDS[setting]
            try:
                ok = hotkey.register(self.hwnd, hotkey_id, keys)
            except ValueError as e:
                self.notify("Hotkey", f"{keys} isn't a hotkey DocRepo can use: {e} Choose another in Settings.")
                continue
            if ok:
                self.registered.append(hotkey_id)
                log.info("hotkey %s registered (%s)", keys, setting)
            else:
                log.warning("hotkey %s (%s) is taken by another program", keys, setting)
                taken.append(f"{keys} ({label.lower()})")
        if taken:
            self.notify("Hotkey taken", f"Another program uses {', '.join(taken)}. Choose another in Settings, or for the capture window "
                        "with: python -m docrepo set-hotkey \"Ctrl+Alt+Space\". The tray icon still opens the capture window.")

    def unregister_hotkeys(self) -> None:
        for hotkey_id in self.registered:
            hotkey.unregister(self.hwnd, hotkey_id)
        self.registered = []

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            self.unregister_hotkeys()
        else:
            self.register_hotkey()
        self.pause_action.setText("Resume hotkeys" if self.paused else "Pause hotkeys")
        self.window.hotkey_label.setText("Hotkeys paused" if self.paused else self.ctx.settings.hotkey)
        self.notify("Hotkey", "Hotkeys paused. They do nothing until you resume them." if self.paused else "Hotkeys resumed.")

    def show_browse(self, view: str | None = None, task: str | None = None) -> None:
        self.browse.show_browse(view, task)

    def settings_changed(self, keys: list[str]) -> None:
        """Apply what the Settings view changed: a new hotkey works at once."""
        if any(k in hotkey.HOTKEY_IDS for k in keys):
            self.unregister_hotkeys()
            self.paused = False
            self.pause_action.setText("Pause hotkeys")
            self.register_hotkey()
            self.window.hotkey_label.setText(self.ctx.settings.hotkey)

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
        """Clicking a reminder opens the browse tool's Reminders list, on that task when there's one."""
        if self.reminder_task or self.reminder_many:
            self.show_browse("reminders", self.reminder_task)
        self.reminder_task, self.reminder_many = None, False

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
            self.reminder_many = len(due) > 1
            self.notify("Reminder" if len(due) == 1 else f"{len(due)} reminders", "\n".join(lines))
        else:
            self.reminder_task, self.reminder_many = None, True
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
        if search.needs_rebuild(self.ctx.conn):
            search.rebuild(self.ctx.conn, self.ctx.data_root)
        db.set_state(self.ctx.conn, "daily", now.date().isoformat())
        log.info("daily start: %d calendar rows, %d pages written", rows, pages)
        if backup.is_due(self.ctx.conn, self.ctx.settings, now):
            self.start_backup()
        return True

    # ---- backups ----
    def start_backup(self) -> bool:
        """Start a backup on its own thread, so the windows stay quick. A notification says when it's done."""
        if self._backup_thread is not None and self._backup_thread.is_alive():
            self.notify("Backup", "A backup is already running.")
            return False
        root, settings, now = self.ctx.data_root, dataclasses.replace(self.ctx.settings), self.ctx.now()

        def work() -> None:
            try:
                result: object = backup.run_backup(root, settings, now)
            except Exception as e:  # noqa: BLE001 - reported in the notification and the log
                result = e
            self.backup_finished.emit(result)

        self._backup_thread = threading.Thread(target=work, name="DocRepo backup", daemon=True)
        self._backup_thread.start()
        log.info("backup started")
        return True

    def _backup_done(self, result: object) -> None:
        if isinstance(result, backup.BackupResult):
            backup.record(self.ctx.conn, result)
            self.notify("Backup", result.message())
        else:
            log.warning("backup failed: %s", result)
            self.notify("Backup", f"The backup couldn't be made. {result}")
        self.browse.settings_view.show_backup_status()

    def tick(self) -> None:
        """Every minute: the daily work after midnight, and reminders once it's past reminder_time."""
        try:
            self.daily()
            if self.ctx.now().time() >= _reminder_time(self.ctx.settings):
                self.show_reminders()
        except Exception:  # noqa: BLE001 - a background check must never stop the app
            log.exception("background check failed")

    def quit(self) -> None:
        self.unregister_hotkeys()
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


def run(data_root: Path, settings: Settings, fs: SafeFS, browse: bool = False) -> int:
    """Start the app, with the browse tool open if ``browse``. Returns the exit code."""
    qt = QApplication.instance() or QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    qt.setApplicationName("DocRepo")
    qt.setFont(QFont("Segoe UI", 9))
    use_light_theme(qt)  # DocRepo's windows are light; Windows' dark mode would mix dark controls into them
    lock = QLockFile(str(fs.checked_path(data_root / LOCK_FILE)))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        if wake_running_copy(browse):
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
    diagnose.install_excepthook(app.notify)  # under pythonw an error nothing caught would otherwise vanish
    app.daily()
    if search.needs_rebuild(conn):
        search.rebuild(conn, data_root)
    if browse:
        app.show_browse()
    app.show_reminders()
    log.info("capture app started")
    code = qt.exec()
    conn.close()
    lock.unlock()
    log.info("capture app stopped")
    return code
