"""The browse tool's Settings view: the paths and other settings in settings.json, and where the data root is.

Nothing here is a path in the code: the owner enters the data root and the
backup folder here, and they're kept in location.json and settings.json.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from docrepo import capacity, db, hotkey, prompts, search
from docrepo.config import Settings, data_root_problem, init_data_root, make_safe_fs, resolve_data_root, save_location
from docrepo.dates import WEEKDAYS
from docrepo.model import Model
from docrepo.pages import write_pages
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
        hotkey.parse_hotkey(keys)
    except ValueError as e:
        raise SettingsProblem(f"The hotkey {keys or '(empty)'} can't be used: {e}") from e
    out["hotkey"] = keys
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


class SettingsView(QWidget):
    """The form. ``message`` shows a line in the browse tool's status line."""

    def __init__(self, ctx: AppContext, message: Callable[[str], None], confirm: Callable[[str, str], bool]) -> None:
        super().__init__()
        self.ctx = ctx
        self.message = message
        self.confirm = confirm
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

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.me = QComboBox()
        self.hotkey = QLineEdit()
        self.hotkey.setPlaceholderText("Such as Ctrl+Shift+Space")
        self.backup = QLineEdit()
        self.backup.setPlaceholderText("Not set. Backups start in a later version")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_backup)
        backup_row = QHBoxLayout()
        backup_row.addWidget(self.backup, 1)
        backup_row.addWidget(browse)
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
                ("Backup folder", backup_row, "Where daily backups go (a later version). Outside the data root."),
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
        self.backup.setText(s.backup_dir or "")
        self.reminder.setTime(QTime.fromString(s.reminder_time, "HH:mm") if QTime.fromString(s.reminder_time, "HH:mm").isValid() else QTime(8, 0))
        for d, box in self.workdays.items():
            box.setChecked(d in s.workdays)
        self.horizon.setValue(s.capacity_horizon_years)
        self.events.setText(", ".join(s.event_words))
        self.cap.setValue(s.extracted_text_cap_chars)
        self.warn.setValue(s.prompt_warn_chars)
        self.check.setValue(s.doc_check_minutes)
        self.error.hide()

    def values(self) -> dict[str, Any]:
        return {
            "me": self.me.currentData(), "hotkey": self.hotkey.text(), "backup_dir": self.backup.text(),
            "reminder_time": self.reminder.time().toString("HH:mm"), "workdays": [d for d, box in self.workdays.items() if box.isChecked()],
            "capacity_horizon_years": self.horizon.value(), "event_words": [w for w in self.events.text().split(",")],
            "extracted_text_cap_chars": self.cap.value(), "prompt_warn_chars": self.warn.value(), "doc_check_minutes": self.check.value(),
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
            later = " The hotkey works from now on." if "hotkey" in changed else ""
            self.message(f"Saved {len(changed)} setting{'s' if len(changed) > 1 else ''} to settings.json.{later}")
        return changed

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
