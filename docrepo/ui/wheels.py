"""The wheels as a whole (releases 5.41 to 5.43; ``docs/ui-design/wheel-design.md``): the config and its reload, opening a
wheel on its hotkey, running what's picked, the usage log, and the windows the wheels open. Held by the app."""
from __future__ import annotations

import csv
import io
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QFileSystemWatcher, QObject, QPointF, QTimer
from PySide6.QtGui import QCursor, QGuiApplication

from docrepo import hotkey, selection, wheels_config
from docrepo.ui.palette import Command
from docrepo.ui.wheel_commands import REGISTRY, SPECS, icon_names
from docrepo.ui.wheel_window import Pick, WheelWindow
from docrepo.wheel import DIRECTIONS
from docrepo.wheels_config import ConfigError, Wheel, WheelsConfig

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

log = logging.getLogger(__name__)

USAGE_LOG = Path("System") / "logs" / "wheel-usage.csv"
USAGE_HEADER = "time,wheel,direction,command,how,drawn,appear_ms,pick_ms\r\n"
RELOAD_WAIT_MS = 200
WORDS = {"N": "up", "NE": "up and right", "E": "right", "SE": "down and right", "S": "down", "SW": "down and left", "W": "left", "NW": "up and left"}


def usage_line(when: str, pick: Pick, appear_ms: int) -> str:
    """One row of the usage log: no content, only which slot was picked and how quickly, to reorganize from real data."""
    out = io.StringIO()
    csv.writer(out).writerow([when, pick.wheel.id, pick.direction, pick.slot.command, pick.how, int(pick.drawn), appear_ms, pick.pick_ms])
    return out.getvalue()


class Wheels(QObject):
    def __init__(self, app: CaptureApp) -> None:
        super().__init__(app)
        self.app = app
        self.ctx = app.ctx
        self.config: WheelsConfig = wheels_config.parse(wheels_config.DEFAULT_TEXT, SPECS, icon_names())
        self.window = WheelWindow(self._picked, self._cancelled, self._palette)
        self.snapshot: selection.Snapshot | None = None
        self.appear_ms = 0
        self.problem = ""  # what's wrong with the file now, for the tray's Reload wheels to say again
        self.started = False  # until the app's tray is showing, a notification would go nowhere
        self._task_search = None
        self._file_search = None
        self._reload_timer = QTimer(self, singleShot=True, interval=RELOAD_WAIT_MS, timeout=self._file_changed)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(lambda _p: self._reload_timer.start())
        self._watcher.directoryChanged.connect(lambda _p: self._reload_timer.start())
        try:
            wheels_config.write_defaults(self.ctx.fs, self.ctx.data_root, SPECS, icon_names())
        except OSError as e:
            log.warning("the wheels' config couldn't be written: %s", type(e).__name__)
        self._watch()
        self.reload(quiet=True)
        self.started = True

    # ---- the config ----
    @property
    def path(self) -> Path:
        return self.ctx.data_root / wheels_config.CONFIG_FILE

    def _watch(self) -> None:
        """The file and its folder: editors that save by replacing a file drop a plain watch."""
        for p in (self.path, self.path.parent):
            if p.exists() and str(p) not in (*self._watcher.files(), *self._watcher.directories()):
                self._watcher.addPath(str(p))

    def _file_changed(self) -> None:
        """The config's folder changed, which may be another file in it: nothing is said unless something's new."""
        self.reload(quiet=True)

    def say_problem(self) -> None:
        """What's wrong with the file, in a notification."""
        if self.problem:
            self.ctx.notify("Wheels config", f"{self.problem} The last good wheels stay in use.")

    def reload(self, quiet: bool = False) -> bool:
        """Read the file again. A problem names the field, and the last good wheels stay in use. True if it was used.
        ``quiet`` doesn't repeat a problem already told, or say that nothing changed."""
        self._watch()
        before = [(w.id, w.name) for w in self.config.wheels]
        try:
            config = wheels_config.load(self.ctx.data_root, SPECS, icon_names())
        except ConfigError as e:
            told = str(e) == self.problem
            self.problem = str(e)
            if not told:
                log.warning("wheels config: %s", e)
            if self.started and (not quiet or not told):
                self.say_problem()
            return False
        was_broken, self.problem = bool(self.problem), ""
        same = config == self.config
        self.config = config
        if not same:
            log.info("wheels config loaded: %s", ", ".join(w.id for w in config.wheels))
        if [(w.id, w.name) for w in config.wheels] != before and self.started:
            self.app.wheels_changed()
        if self.started and (not quiet or not same or was_broken):
            self.ctx.notify("Wheels config", "Your wheels are reloaded.")
        return True

    def open_config(self) -> None:
        """Open wheels config, from the tray or the panel: in its own program, or shown in File Explorer."""
        from docrepo.opener import start_own_file
        from docrepo.ui.explorer import show_in_explorer

        problem = start_own_file(self.path)
        if problem:
            log.info("the wheels' config opened in File Explorer instead: %s", problem)
            show_in_explorer(self.path)

    # ---- hotkeys ----
    def hotkeys(self) -> list[tuple[int, str, str, Callable[[], None]]]:
        """For each wheel with keys set: (its Windows ID, its keys, its label, what the hotkey does). An ID is the wheel's
        place in the file, after DocRepo's other hotkeys."""
        out = []
        for n, w in enumerate(self.config.wheels):
            keys = (self.ctx.settings.wheel_hotkeys.get(w.id) or "").strip()
            if keys:
                out.append((hotkey.WHEEL_ID_BASE + n, keys, f"the {w.name} wheel", lambda w=w, keys=keys: self.open(w.id, keys)))
        return out

    # ---- opening ----
    def _screen_for(self, hwnd: int):
        """The monitor holding the window you were in (decision 171), or the cursor's if there's none."""
        screens = QGuiApplication.screens()
        place = selection.monitor_of(hwnd)
        if place is not None:
            for s in screens:
                g = s.geometry()
                if (g.x(), g.y()) == place:
                    return s
        return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    def open(self, wheel_id: str, keys: str | None = None) -> None:
        """A wheel's hotkey: open it, or, pressed again, cancel it. Another wheel's hotkey changes to that wheel."""
        started = time.perf_counter()
        queued = selection.message_age_ms() if keys else 0  # the hotkey's own wait in the queue
        wheel = self.config.wheel(wheel_id)
        if wheel is None:
            return
        if self.window.is_open() and self.window.wheel is not None and self.window.wheel.id == wheel_id:
            self.window.cancel(True)
            return
        hwnd = selection.foreground() if not self.window.is_open() else (self.snapshot.hwnd if self.snapshot else 0)
        screen = self._screen_for(hwnd)
        area = screen.availableGeometry()
        held: Callable[[], bool] | None = None
        if keys:
            modifiers, vk = hotkey.parse_hotkey(keys)
            held = lambda: hotkey.is_held(modifiers, vk)  # noqa: E731
        self.window.open_wheel(wheel, self.config.timing, QPointF(area.center()), held)
        self.snapshot = selection.snapshot(hwnd)
        self.appear_ms = queued + int((time.perf_counter() - started) * 1000)
        log.info("wheel %s in front after %d ms", wheel.id, self.appear_ms)

    def open_from_palette(self, wheel_id: str) -> None:
        self.open(wheel_id)

    def _picked(self, pick: Pick) -> None:
        registered = REGISTRY.get(pick.slot.command)
        if registered is None:
            return
        try:
            self.ctx.fs.append_text(self._usage_path(), usage_line(self.ctx.now().isoformat(timespec="seconds"), pick, self.appear_ms))
        except OSError as e:
            log.warning("the wheel's usage log wasn't written: %s", type(e).__name__)
        log.info("wheel %s: %s, %s, in %d ms", pick.wheel.id, pick.direction, pick.slot.command, pick.pick_ms)
        self.run(pick.slot.command, pick.slot.args)
        if registered.gives_back:
            self.give_back()

    def _usage_path(self) -> Path:
        path = self.ctx.data_root / USAGE_LOG
        if not path.exists():
            self.ctx.fs.append_text(path, USAGE_HEADER)
        return path

    def run(self, command: str, args) -> None:
        """Run a command. A failure says so in a notification and the log, and never stops the app."""
        try:
            REGISTRY[command].run(self.app, args)
        except Exception as e:  # noqa: BLE001 - shown, not raised: under pythonw an error nothing caught would vanish
            log.exception("the wheel's command %s failed", command)
            self.ctx.notify("Wheel", f"That didn't work ({type(e).__name__}). The log has the details.")

    def _cancelled(self, give_back: bool) -> None:
        if give_back:
            self.give_back()

    def give_back(self) -> None:
        """The keyboard goes back to the window you were in. DocRepo is in front, so Windows allows it."""
        if self.snapshot is not None:
            selection.bring_forward(self.snapshot.hwnd)

    def _palette(self, wheel: Wheel) -> None:
        """Ctrl+K: the way out for what doesn't fit. The capture window's palette from the Capture wheel, otherwise the
        browse tool's."""
        if wheel.id == "capture":
            self.app.window.show_capture()
            self.app.window.open_palette()
        else:
            self.app.show_browse()
            self.app.browse.open_palette()

    # ---- the palette's rows ----
    def palette_commands(self) -> list[Command]:
        """Every slot, with its wheel and direction ("Capture wheel, up"), and each wheel itself."""
        out = [Command("Wheel", f"Open the {w.name} wheel", lambda w=w: self.open_from_palette(w.id), self.ctx.settings.wheel_hotkeys.get(w.id, "")) for w in self.config.wheels]
        for w in self.config.wheels:
            for d in DIRECTIONS:
                slot = w.slots.get(d)
                if slot is not None and not slot.held:
                    out.append(Command(f"{w.name} wheel, {WORDS[d]}", slot.label, lambda s=slot: self._run_from_palette(s)))
        return out

    def _run_from_palette(self, slot) -> None:
        """From the palette, the window you were in is DocRepo's own: there's no selection to read."""
        self.snapshot = None
        self.run(slot.command, slot.args)

    # ---- what the commands open ----
    def capture_selection(self) -> None:
        self.app.window.capture_selection(self.snapshot)

    def task_search(self, then: str = "page") -> None:
        from docrepo.ui.task_search import TaskSearch

        if self._task_search is None:
            self._task_search = TaskSearch(self.app)
        self._task_search.open_it(then, self._screen_for(self.snapshot.hwnd if self.snapshot else 0))

    def file_search(self) -> None:
        from docrepo.ui.file_search import FileSearch

        if self._file_search is None:
            self._file_search = FileSearch(self.app)
        self._file_search.open_it(self._screen_for(self.snapshot.hwnd if self.snapshot else 0))

    def today_panel(self, do: str = "toggle") -> None:
        self.app.today_panel_action(do)
