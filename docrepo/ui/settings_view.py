"""The browse tool's Settings view: the paths and other settings in settings.json, and where the data root is.

Nothing here is a path in the code: the owner enters the data root and the
backup folder here, and they're kept in location.json and settings.json.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from docrepo import backup, capacity, db, diagnose, hotkey, prompts, search, startup
from docrepo.config import Settings, data_root_problem, init_data_root, make_safe_fs, resolve_data_root, save_location
from docrepo.dates import WEEKDAYS, long_date
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.safe_fs import WriteRefused
from docrepo.ui.context import AppContext

log = logging.getLogger(__name__)

#: Settings whose change means the capacity calendar is built again.
CALENDAR_KEYS = ("workdays", "capacity_horizon_years")


class SettingsProblem(ValueError):
    """A setting that can't be saved as entered."""


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def check_values(ctx: AppContext, values: dict[str, Any]) -> dict[str, Any]:
    """The values, checked and tidied. Raises SettingsProblem naming the first one that's wrong."""
    out = dict(values)
    keys = out.get("hotkey", "").strip()
    try:
        taken = {hotkey.parse_hotkey(keys): "the capture window"}
    except ValueError as e:
        raise SettingsProblem(f"The hotkey {keys or '(empty)'} can't be used: {e}") from e
    out["hotkey"] = keys
    for setting, label in hotkey.HOTKEYS[1:]:  # the others are off when empty (mods log round 1)
        if setting not in out:
            continue
        keys = (out[setting] or "").strip()
        out[setting] = keys
        if not keys:
            continue
        try:
            combo = hotkey.parse_hotkey(keys)
        except ValueError as e:
            raise SettingsProblem(f"The hotkey for {label.lower()}, {keys}, can't be used: {e}") from e
        if combo in taken:
            raise SettingsProblem(f"{keys} is already the hotkey for {taken[combo]}. Give each hotkey its own keys.")
        taken[combo] = label.lower()
    backup = (out.get("backup_dir") or "").strip()
    if backup:
        path = Path(backup)
        if not path.is_absolute():
            raise SettingsProblem("The backup folder needs a full path, starting with a drive letter or \\\\server\\share.")
        if _inside(path, ctx.data_root):
            raise SettingsProblem("The backup folder can't be inside the data root. Pick a folder outside it, such as on another drive.")
    out["backup_dir"] = backup or None
    if not out.get("workdays"):
        raise SettingsProblem("Pick at least one workday, or the capacity calendar has no days to spread hours over.")
    out["event_words"] = [w.strip().lower() for w in out.get("event_words", []) if w.strip()]
    if out.get("me") and out["me"] not in Model(ctx.conn).people:
        raise SettingsProblem(f"There's no person {out['me']}.")
    return out


def update_settings(ctx: AppContext, values: dict[str, Any]) -> list[str]:
    """Save changed settings to settings.json, then do what each change needs. Returns the changed keys."""
    values = check_values(ctx, values)
    current = asdict(ctx.settings)
    changed = [k for k, v in values.items() if k in current and current[k] != v]
    if not changed:
        return []
    for k in changed:
        setattr(ctx.settings, k, values[k])
    ctx.settings.save(ctx.fs, ctx.data_root)
    if "backup_dir" in changed:
        ctx.fs = make_safe_fs(ctx.data_root, ctx.settings)
    if any(k in changed for k in CALENDAR_KEYS):
        now = ctx.now()
        capacity.rebuild_all(ctx.conn, now.date(), ctx.settings)
        write_pages(Model(ctx.conn), ctx.data_root, ctx.fs, now.date(), now)
    log.info("settings changed: %s", ", ".join(changed))
    ctx.settings_changed(changed)
    return changed


def set_up_data_root(path: Path) -> str:
    """Record a new data root in location.json, setting it up first if it's new. DocRepo uses it from its next start."""
    problem = data_root_problem(path)
    if problem:
        raise SettingsProblem(f"Can't use {path} as the data root: {problem}.")
    init_data_root(path)
    settings = Settings.load(path)
    fs = make_safe_fs(path, settings)
    prompts.write_defaults(fs, path)
    db.connect(fs, path).close()
    save_location(path)
    log.info("data root recorded for the next start")
    return f"DocRepo will use {path} from its next start. Quit it from the tray icon and start it again. Your data here isn't moved."


def rebuild_everything(ctx: AppContext) -> str:
    now = ctx.now()
    rows = capacity.rebuild_all(ctx.conn, now.date(), ctx.settings)
    pages = write_pages(Model(ctx.conn), ctx.data_root, ctx.fs, now.date(), now)
    items = search.rebuild(ctx.conn, ctx.data_root)
    return f"Rebuilt the capacity calendar ({rows} rows), {pages} changed pages and the search index ({items} items)."


class ReportDialog(QDialog):
    """The troubleshooting report, to read through and copy."""

    def __init__(self, parent: QWidget, text: str, path: Path | None, reveal: Callable[[Path], bool]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Troubleshooting report")
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        intro = QLabel("Read it through before you send it on: it should hold no email text, names or company details. "
                       + (f"It's saved as {path.name} in System\\diagnostics." if path else "It couldn't be saved, so copy it from here."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 9))
        lay.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        self.copy = QPushButton("Copy report")
        self.copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(text), self.copy.setText("Copied")))
        buttons.addWidget(self.copy)
        if path:
            show = QPushButton("Show in File Explorer")
            show.clicked.connect(lambda: reveal(path))
            buttons.addWidget(show)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        lay.addLayout(buttons)


class SettingsView(QWidget):
    """The form. ``message`` shows a line in the browse tool's status line."""

    def __init__(self, ctx: AppContext, message: Callable[[str], None], confirm: Callable[[str, str], bool],
                 reveal: Callable[[Path], bool] = lambda path: False, open_import: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self.ctx = ctx
        self.message = message
        self.confirm = confirm
        self.reveal = reveal
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(14, 10, 14, 14)
        head = QLabel("<b style='font-size:12pt'>Settings</b><br><span style='color:#5a6571'>Kept in Config\\settings.json in the data root. "
                      "The data root's own location is kept in %LOCALAPPDATA%\\DocRepo\\location.json.</span>")
        head.setWordWrap(True)
        lay.addWidget(head)

        self.where = QLabel()
        self.where.setWordWrap(True)
        change = QPushButton("Change data root…")
        change.clicked.connect(self.change_data_root)
        rebuild = QPushButton("Rebuild pages, calendar and search")
        rebuild.setToolTip("Rebuilds the capacity calendar, every Task.md and Contents.md, and the search index from docs.db and the files")
        rebuild.clicked.connect(lambda: self.message(rebuild_everything(self.ctx)))
        row = QHBoxLayout()
        row.addWidget(change)
        row.addWidget(rebuild)
        row.addStretch()
        lay.addWidget(self.where)
        lay.addLayout(row)

        # Starting when the owner signs in, and the one-time import of the project list
        self.startup_status = QLabel()
        self.startup_status.setWordWrap(True)
        make = QPushButton("Make the Startup shortcut")
        make.setToolTip("Makes DocRepo.lnk and opens your Startup folder next to it, for you to drag it in")
        make.clicked.connect(self.make_shortcut)
        imp = QPushButton("Import projects from Excel…")
        imp.setToolTip("A one-time import of your project list: each row becomes a top-level task")
        imp.clicked.connect(lambda: open_import())
        row = QHBoxLayout()
        row.addWidget(make)
        row.addWidget(imp)
        row.addStretch()
        lay.addWidget(self.startup_status)
        lay.addLayout(row)

        # The troubleshooting report, to bring to the personal computer
        trouble = QLabel("<b>Troubleshooting:</b> a report of DocRepo's versions, a step-by-step check of reading the email selected "
                         "in Outlook, recent drags onto the capture window and recent problems. It leaves out email text, names and "
                         "addresses, to bring to the personal computer. Select an email in Outlook first.")
        trouble.setWordWrap(True)
        report = QPushButton("Troubleshooting report…")
        report.setToolTip("Saved in System\\diagnostics in the data root, and shown here to copy")
        report.clicked.connect(self.troubleshooting_report)
        row = QHBoxLayout()
        row.addWidget(report)
        row.addStretch()
        lay.addWidget(trouble)
        lay.addLayout(row)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.me = QComboBox()
        self.hotkey = QLineEdit()
        self.hotkey.setPlaceholderText("Such as Ctrl+Shift+Space")
        more = QWidget()
        more_form = QFormLayout(more)
        more_form.setContentsMargins(0, 0, 0, 0)
        self.more_hotkeys: dict[str, QLineEdit] = {}
        for setting, label in hotkey.HOTKEYS[1:]:
            box = QLineEdit()
            box.setPlaceholderText("Off")
            self.more_hotkeys[setting] = box
            more_form.addRow(label, box)
        suggest = QPushButton("Use the suggested keys")
        suggest.setToolTip("Fills each empty box with Ctrl+Shift and its letter: " + ", ".join(hotkey.SUGGESTED.values()))
        suggest.clicked.connect(self.suggest_hotkeys)
        more_form.addRow("", suggest)
        self.backup = QLineEdit()
        self.backup.setPlaceholderText("Not set: no backups are made")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_backup)
        backup_row = QHBoxLayout()
        backup_row.addWidget(self.backup, 1)
        backup_row.addWidget(browse)
        self.backup_days = QSpinBox()
        self.backup_days.setRange(1, 90)
        self.backup_days.setPrefix("every ")
        self.backup_days.setSuffix(" days")
        self.backup_keep = QSpinBox()
        self.backup_keep.setRange(1, 60)
        self.backup_keep.setSuffix(" database copies")
        self.backup_status = QLabel()
        self.backup_status.setWordWrap(True)
        now = QPushButton("Back up now")
        now.clicked.connect(self.backup_now)
        backup_when = QHBoxLayout()
        for w in (self.backup_days, QLabel("keeping"), self.backup_keep, now):
            backup_when.addWidget(w)
        backup_when.addStretch()
        self.reminder = QTimeEdit()
        self.reminder.setDisplayFormat("HH:mm")
        self.workdays = {d: QCheckBox(d) for d in WEEKDAYS}
        days = QHBoxLayout()
        for box in self.workdays.values():
            days.addWidget(box)
        days.addStretch()
        self.horizon = QSpinBox()
        self.horizon.setRange(1, 10)
        self.horizon.setSuffix(" years")
        self.events = QLineEdit()
        self.events.setPlaceholderText("Comma-separated")
        self.cap = QSpinBox()
        self.cap.setRange(1_000, 5_000_000)
        self.cap.setSingleStep(10_000)
        self.cap.setSuffix(" characters")
        self.warn = QSpinBox()
        self.warn.setRange(1_000, 5_000_000)
        self.warn.setSingleStep(5_000)
        self.warn.setSuffix(" characters")
        self.check = QSpinBox()
        self.check.setRange(5, 24 * 60)
        self.check.setSuffix(" minutes")
        rows = [("Me", self.me, "Who “I” and “me” are in captures."), ("Hotkey", self.hotkey, "Opens the capture window. It needs Ctrl, Alt or Win."),
                ("More hotkeys", more, "Each is off until you set it, or Use the suggested keys fills the empty ones with Ctrl+Shift and the "
                                       "topic's letter (F1 lists them); then Save settings. While DocRepo runs, a hotkey is taken from other "
                                       "programs, such as Outlook's Ctrl+Shift+N for a new note. Update and Add to agenda use the task picked "
                                       "in the capture window, or open the task picker. Pause hotkeys in the tray menu pauses them all."),
                ("Backup folder", backup_row, "Where backups go: a copy of docs.db and a mirror of the data root's files. Outside the data root."),
                ("Backups", backup_when, "How often DocRepo backs up, at its first start of the day, and how many copies of docs.db it keeps."),
                ("Reminders at", self.reminder, "Each day's reminders show as notifications from this time."),
                ("Workdays", days, "The capacity calendar spreads hours over these days."),
                ("Capacity horizon", self.horizon, "How far ahead routine tasks fill the capacity calendar."),
                ("Event words", self.events, "Words Parse and populate reads as events, for deadlines."),
                ("Extracted text", self.cap, "The most text kept from each file."),
                ("Copy prompt warns", self.warn, "Copy prompt warns when a prompt is longer than this."),
                ("Document checks", self.check, "How often tracked documents are checked for changes (a later version).")]
        for label, widget, hint in rows:
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 4)
            bl.setSpacing(1)
            if isinstance(widget, QHBoxLayout):
                bl.addLayout(widget)
            else:
                bl.addWidget(widget)
            note = QLabel(hint)
            note.setStyleSheet("color:#5a6571; font-size:8.5pt")
            note.setWordWrap(True)
            bl.addWidget(note)
            form.addRow(label, box)
        lay.addLayout(form)
        lay.addWidget(self.backup_status)
        self.error = QLabel()
        self.error.setStyleSheet("background:#fbe3e1; color:#b0261e; padding:6px 10px")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)
        buttons = QHBoxLayout()
        save = QPushButton("Save settings")
        save.setStyleSheet("background:#1d5e98; color:white; padding:4px 14px")
        save.clicked.connect(self.save)
        undo = QPushButton("Undo changes")
        undo.clicked.connect(self.load)
        buttons.addWidget(save)
        buttons.addWidget(undo)
        buttons.addStretch()
        lay.addLayout(buttons)
        lay.addStretch()

    def suggest_hotkeys(self) -> None:
        """Use the suggested keys (mods log round 2, M0036): each empty hotkey box gets Ctrl+Shift and its letter. Nothing is
        saved until Save settings."""
        filled = [setting for setting, box in self.more_hotkeys.items() if not box.text().strip() and setting in hotkey.SUGGESTED]
        for setting in filled:
            self.more_hotkeys[setting].setText(hotkey.SUGGESTED[setting])
        self.message(f"Filled {len(filled)} hotkey{'s' if len(filled) != 1 else ''}. Save settings to use them." if filled
                     else "Every hotkey box already has keys.")

    # ---- filling and reading the form ----
    def load(self) -> None:
        s, m = self.ctx.settings, Model(self.ctx.conn)
        choice = resolve_data_root(None)
        override = "" if choice.path and choice.path.resolve() == self.ctx.data_root.resolve() else (
            " <span style='color:#875700'>DocRepo was started with another data root (the command line or DOCREPO_DATA_ROOT), so the recorded "
            f"one ({choice.path or 'none'}) isn't in use now.</span>")
        self.where.setText(f"<b>Data root:</b> {self.ctx.data_root}{override}")
        self.me.clear()
        self.me.addItem("Not set", None)
        for p in m.active_people():
            self.me.addItem(p.name, p.id)
        self.me.setCurrentIndex(max(0, self.me.findData(s.me)))
        self.hotkey.setText(s.hotkey)
        for setting, box in self.more_hotkeys.items():
            box.setText(getattr(s, setting))
        self.backup.setText(s.backup_dir or "")
        self.reminder.setTime(QTime.fromString(s.reminder_time, "HH:mm") if QTime.fromString(s.reminder_time, "HH:mm").isValid() else QTime(8, 0))
        for d, box in self.workdays.items():
            box.setChecked(d in s.workdays)
        self.horizon.setValue(s.capacity_horizon_years)
        self.events.setText(", ".join(s.event_words))
        self.cap.setValue(s.extracted_text_cap_chars)
        self.warn.setValue(s.prompt_warn_chars)
        self.check.setValue(s.doc_check_minutes)
        self.backup_days.setValue(s.backup_every_days)
        self.backup_keep.setValue(s.backup_keep)
        self.startup_status.setText(f"<b>Start when you sign in:</b> {startup.status()}")
        self.show_backup_status()
        self.error.hide()

    def values(self) -> dict[str, Any]:
        return {
            "me": self.me.currentData(), "hotkey": self.hotkey.text(), **{k: box.text() for k, box in self.more_hotkeys.items()},
            "backup_dir": self.backup.text(),
            "reminder_time": self.reminder.time().toString("HH:mm"), "workdays": [d for d, box in self.workdays.items() if box.isChecked()],
            "capacity_horizon_years": self.horizon.value(), "event_words": [w for w in self.events.text().split(",")],
            "extracted_text_cap_chars": self.cap.value(), "prompt_warn_chars": self.warn.value(), "doc_check_minutes": self.check.value(),
            "backup_every_days": self.backup_days.value(), "backup_keep": self.backup_keep.value(),
        }

    def save(self) -> list[str]:
        try:
            changed = update_settings(self.ctx, self.values())
        except SettingsProblem as e:
            self.error.setText(str(e))
            self.error.show()
            return []
        self.error.hide()
        self.load()
        if not changed:
            self.message("Nothing changed.")
        else:
            n = sum(1 for k in changed if k in hotkey.HOTKEY_IDS)
            later = f" The hotkey{'s work' if n > 1 else ' works'} from now on." if n else ""
            self.message(f"Saved {len(changed)} setting{'s' if len(changed) > 1 else ''} to settings.json.{later}")
        return changed

    # ---- backups ----
    def show_backup_status(self) -> None:
        s = self.ctx.settings
        if not s.backup_dir:
            self.backup_status.setText("<b>Backups:</b> off. Choose a backup folder and save, to turn them on.")
            return
        last = backup.last_backup(self.ctx.conn)
        if not last:
            self.backup_status.setText("<b>Backups:</b> none yet. The first is made at DocRepo's next start, or with Back up now.")
            return
        when = datetime.fromisoformat(last)
        left = s.backup_every_days - (self.ctx.now().date() - when.date()).days
        nxt = "at DocRepo's next start" if left <= 0 else "tomorrow" if left == 1 else f"in {left} days"
        self.backup_status.setText(f"<b>Backups:</b> the last was on {long_date(when.date(), self.ctx.now().date())} at "
                                   f"{last[11:16]}. The next is due {nxt}. Each one is listed in backup-log.md in the backup folder.")

    def backup_now(self) -> None:
        if (self.backup.text().strip() or None) != self.ctx.settings.backup_dir:
            self.message("Save the settings first, so the backup goes to the folder shown.")
            return
        if self.ctx.start_backup is not None:
            if self.ctx.start_backup():
                self.message("Backing up. A notification says when it's done.")
            return
        try:
            result = backup.run_backup(self.ctx.data_root, self.ctx.settings, self.ctx.now())
        except backup.BackupError as e:
            self.message(str(e))
            return
        backup.record(self.ctx.conn, result)
        self.show_backup_status()
        self.message(result.message())

    # ---- the Startup shortcut ----
    def make_shortcut(self) -> None:
        try:
            path = startup.make_shortcut(self.ctx.fs)
        except (startup.StartupError, OSError) as e:
            self.message(f"The shortcut couldn't be made: {e}")
            return
        folder = startup.startup_folder()
        self.reveal(path)
        if folder is not None:
            self.reveal(folder)
        self.message(f"Made {startup.SHORTCUT}. Drag it from the File Explorer window it's selected in into your Startup folder, "
                     "the other window. To stop DocRepo starting when you sign in, delete it from the Startup folder.")
        self.startup_status.setText(f"<b>Start when you sign in:</b> {startup.status()}")

    def troubleshooting_report(self) -> None:
        """Make the report (asking Outlook about the email selected there), save it and show it to copy."""
        now = self.ctx.now()
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = diagnose.build_report(self.ctx.data_root, now, list(diagnose.DRAGS))
            try:
                path: Path | None = diagnose.save_report(self.ctx.fs, self.ctx.data_root, text, now)
            except (OSError, WriteRefused) as e:
                log.warning("troubleshooting report not saved: %s", e)
                path = None
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.message(f"Saved the troubleshooting report as {path.name} in System\\diagnostics." if path
                     else "Made the troubleshooting report, but couldn't save it. Copy it from the window.")
        ReportDialog(self, text, path, self.reveal).exec()

    def _pick_backup(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Backup folder", self.backup.text())
        if folder:
            self.backup.setText(str(Path(folder)))

    def change_data_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Data root", str(self.ctx.data_root.parent))
        if not folder:
            return
        path = Path(folder)
        if path.resolve() == self.ctx.data_root.resolve():
            self.message("That's the data root DocRepo uses now.")
            return
        if not self.confirm("Change data root", f"Use {path} as the data root from DocRepo's next start? It's set up if it's new. "
                                                 "Nothing in the current data root moves or changes."):
            return
        try:
            self.message(set_up_data_root(path))
        except (SettingsProblem, OSError, db.DatabaseError) as e:
            self.error.setText(str(e))
            self.error.show()
