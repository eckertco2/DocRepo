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
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import __version__, backup, capacity, db, diagnose, hotkey, outlook, prompts, search, startup, tagged, wheels_config
from docrepo import tagged_masks as masks
from docrepo.config import REVIEW_DAYS, Settings, data_root_problem, init_data_root, make_safe_fs, resolve_data_root, save_location
from docrepo.dates import WEEKDAYS, long_date, stamp
from docrepo.links import check_link_template
from docrepo.markup import esc
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.safe_fs import WriteRefused
from docrepo.ui.tokens import C
from docrepo.ui.context import AppContext
from docrepo.ui.icons import icon, set_fold
from docrepo.ui.look import LOOK, Help, set_hints
from docrepo.ui.wheel_commands import SPECS, icon_names

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
    if "wheel_hotkeys" in out:  # the wheels' hotkeys (release 5.41): off when empty too
        wheels = {}
        for wheel_id, keys in out["wheel_hotkeys"].items():
            keys = (keys or "").strip()
            if not keys:
                continue
            try:
                combo = hotkey.parse_hotkey(keys)
            except ValueError as e:
                raise SettingsProblem(f"The hotkey for the {wheel_id} wheel, {keys}, can't be used: {e}") from e
            if combo in taken:
                raise SettingsProblem(f"{keys} is already the hotkey for {taken[combo]}. Give each hotkey its own keys.")
            taken[combo] = f"the {wheel_id} wheel"
            wheels[wheel_id] = keys
        out["wheel_hotkeys"] = wheels
    backup = (out.get("backup_dir") or "").strip()
    if backup:
        path = Path(backup)
        if not path.is_absolute():
            raise SettingsProblem("The backup folder needs a full path, starting with a drive letter or \\\\server\\share.")
        if _inside(path, ctx.data_root):
            raise SettingsProblem("The backup folder can't be inside the data root. Pick a folder outside it, such as on another drive.")
    out["backup_dir"] = backup or None
    copilot = (out.get("copilot_folder") or "").strip()
    if copilot:
        path = Path(copilot)
        if not path.is_absolute():
            raise SettingsProblem("Copilot's folder needs a full path, starting with a drive letter or \\\\server\\share.")
        if _inside(path, ctx.data_root):
            raise SettingsProblem("Copilot's folder can't be inside the data root. DocRepo only reads it, and Copilot writes nothing there.")
    out["copilot_folder"] = copilot or None
    if not out.get("workdays"):
        raise SettingsProblem("Pick at least one workday, or the capacity calendar has no days to spread hours over.")
    out["event_words"] = [w.strip().lower() for w in out.get("event_words", []) if w.strip()]
    names = [w.strip() for w in out.get("reference_fields", []) if w.strip()]
    if len({n.lower() for n in names}) < len(names):
        raise SettingsProblem("Give each reference field its own name.")
    out["reference_fields"] = names
    links = {k.strip(): v.strip() for k, v in (out.get("reference_links") or {}).items() if k.strip() in names and v.strip()}
    for name, template in links.items():  # release 5.67, decision 320
        why = check_link_template(template)
        if why:
            raise SettingsProblem(f"{name}'s link address needs to be one that {why}, such as https://example.com/record/{{}}.")
    out["reference_links"] = links
    if "review_day" in out and out["review_day"] not in REVIEW_DAYS:  # release 5.128
        raise SettingsProblem("The review day is a day of the week.")
    if "review_weeks" in out and out["review_weeks"] not in (1, 2, 4):
        raise SettingsProblem("Projects come up every 1, 2 or 4 weeks.")
    if "quiet_days" in out and not (isinstance(out["quiet_days"], int) and 1 <= out["quiet_days"] <= 365):
        raise SettingsProblem("Gone quiet is after 1 to 365 days.")
    if out.get("look", "new") not in ("new", "classic"):
        raise SettingsProblem("The look is the new one or the Classic one.")
    if out.get("me") and out["me"] not in Model(ctx.conn).people:
        raise SettingsProblem(f"There's no person {out['me']}.")
    if "tagged_patterns" in out or "tagged_never" in out:  # release 5.80
        out.update(check_tagged(out.get("tagged_patterns", ctx.settings.tagged_patterns), out.get("tagged_never", ctx.settings.tagged_never)))
    return out


def check_tagged(patterns: list[dict], never: list[str]) -> dict[str, Any]:
    """The tag patterns and Never a tag (release 5.80, decisions 372 and 375), checked and tidied: each pattern with a mask
    DocRepo can use and a name of its own (its mask when none is typed), and each Never a tag entry a tag or a start with
    *. Raises SettingsProblem naming the first that's wrong."""
    kept = []
    for n, p in enumerate(patterns, 1):
        name, mask = str(p.get("name") or "").strip(), str(p.get("mask") or "").strip()
        if not name and not mask:
            continue
        try:
            masks.parse(mask)
        except masks.MaskError as e:
            raise SettingsProblem(f"{name or f'Tag pattern {n}'}'s mask can't be used: {e}") from e
        kept.append({"name": name or mask, "mask": mask, "space": bool(p.get("space"))})
    names = [p["name"].lower() for p in kept]
    if len(set(names)) < len(names):
        raise SettingsProblem("Give each tag pattern its own name: it's what a new tagged label says it was found by.")
    for entry in never:
        why = masks.never_problem(entry)
        if why:
            raise SettingsProblem(f"Never a tag: {why}")
    return {"tagged_patterns": kept, "tagged_never": masks.never_of(never)}


def apply_tagged(ctx: AppContext) -> None:
    """The tag patterns or Never a tag changed in settings.json: docs.db's copy is made the same, everything is matched
    again from the kept words (decision 377), and Task.md's Tagged labels rows are written again."""
    tagged.use_settings(ctx.conn, ctx.settings)
    now = ctx.now()
    write_pages(Model(ctx.conn), ctx.data_root, ctx.fs, now.date(), now)


def save_never(ctx: AppContext, entries: list[str]) -> None:
    """Never a tag as given (Not a tag on a suggested label, and its Undo, release 5.80), saved to settings.json and used."""
    ctx.settings.tagged_never = masks.never_of(entries)
    ctx.settings.save(ctx.fs, ctx.data_root)
    apply_tagged(ctx)
    log.info("settings changed: tagged_never")
    ctx.settings_changed(["tagged_never"])


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
    if "tagged_patterns" in changed or "tagged_never" in changed:  # release 5.80
        apply_tagged(ctx)
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
    """Rebuild the capacity calendar, every generated page and the search index, and say how many of each."""
    now = ctx.now()
    rows = capacity.rebuild_all(ctx.conn, now.date(), ctx.settings)
    pages = write_pages(Model(ctx.conn), ctx.data_root, ctx.fs, now.date(), now)
    items = search.rebuild(ctx.conn, ctx.data_root)
    return f"Rebuilt the capacity calendar ({rows} rows), {pages} changed pages and the search index ({items} items)."


class ReportDialog(QDialog):
    """The troubleshooting report, or the data root's check (release 5.89), to read through and copy."""

    def __init__(self, parent: QWidget, text: str, path: Path | None, reveal: Callable[[Path], bool], title: str = "Troubleshooting report",
                 intro_text: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        intro = QLabel(intro_text if intro_text is not None else
                       "Read it through before you send it on: it should hold no email text, names or company details. "
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


def _row(*widgets: QWidget) -> QWidget:
    """Controls side by side, 8 px apart, as one cell of a settings card."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for w in widgets:
        lay.addWidget(w)
    return box


class ReferenceFields(QWidget):
    """Settings' reference fields (release 5.9) with their link addresses (release 5.67, round 6's decision 320): a row for
    each, its name and link address side by side, then what a value of 1234 would link to, worked out as it's typed."""

    SAMPLE = "1234"

    def __init__(self) -> None:
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 12)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        for col, words in enumerate(("Field", "Link address", f"A value of {self.SAMPLE} links to")):
            self.grid.addWidget(QLabel(words, objectName="hint"), 0, col)
        self.grid.setColumnStretch(1, 2)
        self.grid.setColumnStretch(2, 2)
        self.rows: list[tuple[QLineEdit, QLineEdit, QLabel, QToolButton]] = []
        self.add_button = QPushButton("Add a field")
        self.add_button.clicked.connect(lambda: self.add_row("", "", focus=True))
        self.grid.addWidget(self.add_button, 999, 0, Qt.AlignmentFlag.AlignLeft)

    def set(self, names: list[str], links: dict[str, str]) -> None:
        """Show these reference fields and their link addresses, a row each, in place of the rows there."""
        for row in self.rows:
            for w in row:
                w.deleteLater()
        self.rows = []
        for name in names:
            self.add_row(name, links.get(name, ""))

    def add_row(self, name: str, link: str, focus: bool = False) -> None:
        """Add a row for a reference field: its name, its link address and the link it makes."""
        n = len(self.rows) + 1
        name_box, link_box = QLineEdit(name), QLineEdit(link)
        name_box.setPlaceholderText("Such as Change #")
        name_box.setAccessibleName(f"Reference field {n}'s name")
        link_box.setPlaceholderText("None: its value is only copied")
        link_box.setAccessibleName(f"Reference field {n}'s link address, with {{}} where its value goes")
        link_box.setToolTip("Where the field's value goes, such as https://example.com/record/{}. With no {}, the value goes at the end.\n"
                            "With no http:// or https://, http:// goes in front, as your browser does: intranet/record? works.")
        made = QLabel(objectName="hint")
        made.setWordWrap(True)
        remove = QToolButton(text="×")
        remove.setAccessibleName(f"Remove reference field {n}")
        remove.setToolTip("Remove this field. A task's value stays, and still shows.")
        row = (name_box, link_box, made, remove)
        remove.clicked.connect(lambda: self.remove_row(row))
        link_box.textChanged.connect(lambda: self.show_made(row))
        self.rows.append(row)
        for col, w in enumerate(row):
            self.grid.addWidget(w, len(self.rows), col)
        self.show_made(row)
        if focus:
            name_box.setFocus()

    def remove_row(self, row) -> None:
        """Take a reference field's row away."""
        self.rows.remove(row)
        for w in row:
            w.deleteLater()

    def show_made(self, row) -> None:
        """Under a row, the link its address makes from an example value, or what's wrong with the address."""
        from docrepo.links import check_link_template, reference_link

        template, made = row[1].text().strip(), row[2]
        why = check_link_template(template)
        made.setText("No link: Copy only" if not template else f"Needs an address that {why}" if why else reference_link(template, self.SAMPLE))

    def names(self) -> list[str]:
        """The reference fields' names, as typed, in order."""
        return [r[0].text() for r in self.rows]

    def links(self) -> dict[str, str]:
        """Each named reference field's link address, for those that have one."""
        return {r[0].text().strip(): r[1].text().strip() for r in self.rows if r[0].text().strip() and r[1].text().strip()}


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
        scroll = self.scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        # The visual overhaul's O6: Windows' settings cards, at most 1000 px wide. Each row has its name and a line on what it
        # does on the left, and its control on the right, as wide as what goes in it.
        page = QWidget()
        page.setMaximumWidth(1000)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 16, 24, 24)
        lay.setSpacing(8)
        holder = QHBoxLayout(body)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(page, 1)
        holder.addStretch(0)
        lay.addWidget(QLabel("Settings", objectName="paneTitle"))
        lay.addWidget(Help("Kept in Config\\settings.json in the data root. The data root's own location is kept in "
                           "%LOCALAPPDATA%\\DocRepo\\location.json."))

        # ---- the data root and start-up ----
        self._build_data_root(lay, open_import)
        # ---- the look (decisions 7 and 15) ----
        self._build_look(lay)
        # ---- hotkeys ----
        self._build_hotkeys(lay)
        # ---- backups ----
        self._build_backups(lay)
        # ---- calendar and reminders ----
        self._build_calendar(lay)
        # ---- the weekly review (release 5.128) ----
        self._build_review(lay)
        # ---- Parse and populate ----
        self._build_parse(lay)
        # ---- tagged labels' patterns, Never a tag and the tester (release 5.80) ----
        self._build_tagged(lay)
        # ---- files and prompts ----
        self._build_files(lay)
        # ---- Outlook (release 5.33) ----
        self._build_outlook(lay)
        # ---- the troubleshooting report, to bring to the personal computer ----
        self._build_troubleshooting(lay)

    def _build_data_root(self, lay, open_import) -> None:
        """The data root and start-up (part of ``__init__``, release 5.95)."""
        self.where = QLabel()
        self.where.setWordWrap(True)
        self.where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        change = QPushButton("Change data root…")
        change.clicked.connect(self.change_data_root)
        rebuild = QPushButton("Rebuild pages, calendar and search")
        rebuild.setToolTip("Rebuilds the capacity calendar, every Task.md and Contents.md, and the search index from docs.db and the files")
        rebuild.clicked.connect(lambda: self.message(rebuild_everything(self.ctx)))
        self.startup_status = QLabel()
        self.startup_status.setWordWrap(True)
        make = QPushButton("Make the Startup shortcut")
        make.setToolTip("Makes DocRepo.lnk and opens your Startup folder next to it, for you to drag it in")
        make.clicked.connect(self.make_shortcut)
        imp = QPushButton("Import projects from Excel…")
        imp.setToolTip("A one-time import of your project list: each row becomes a top-level task")
        imp.clicked.connect(lambda: open_import())
        self._card(lay, "Data root and start-up", [
            (self.where, "", _row(change, rebuild)),
            (self.startup_status, "", _row(make)),
            ("Import your project list", "A one-time import: each row of the Excel workbook becomes a top-level task.", _row(imp)),
        ])

    def _build_look(self, lay) -> None:
        """The look (decisions 7 and 15) (part of ``__init__``, release 5.95)."""
        self.look = QComboBox()
        self.look.addItem("New look", "new")
        self.look.addItem("Classic look (release 5.9)", "classic")
        self.look.setFixedWidth(240)
        self.hints = QCheckBox("Show hints")
        self.hints.setToolTip("Help text, the ⓘ buttons and key badges, in every window, at once")
        self.hints.toggled.connect(self._hints_toggled)
        self._card(lay, "Look", [
            ("Look", "The new look, or release 5.9's while you get used to it. It changes when DocRepo next starts.", self.look),
            ("Hints", "Help text under fields, the ⓘ buttons and the keys beside controls. Hold Alt to see the letter keys, or Ctrl "
                      "for the Ctrl shortcuts, at any time.", self.hints),
            ("Version", "The release of DocRepo running now. CHANGELOG.md, beside the code, says what each brought.",
             QLabel(f"DocRepo {__version__}", objectName="version")),  # release 5.87, the review's F9
        ])

    def _build_hotkeys(self, lay) -> None:
        """Hotkeys (part of ``__init__``, release 5.95)."""
        self.me = QComboBox()
        self.me.setFixedWidth(240)
        self.hotkey = QLineEdit()
        self.hotkey.setPlaceholderText("Such as Ctrl+Shift+Space")
        self.hotkey.setFixedWidth(240)
        more = QWidget()
        more_form = QFormLayout(more)
        more_form.setContentsMargins(0, 0, 0, 0)
        more_form.setHorizontalSpacing(12)
        more_form.setVerticalSpacing(8)
        more_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        more_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.more_hotkeys: dict[str, QLineEdit] = {}
        for setting, label in hotkey.HOTKEYS[1:]:
            box = QLineEdit()
            box.setPlaceholderText("Off, such as Ctrl+Shift+4" if setting == "today_panel_hotkey" else "Off")
            box.setFixedWidth(200)
            self.more_hotkeys[setting] = box
            more_form.addRow(label, box)
        # A box per wheel in Config\wheels.jsonc (release 5.41, decision 216), filled by load(), so a new wheel gets its box.
        self.wheel_rows = QWidget()
        self.wheel_form = QFormLayout(self.wheel_rows)
        self.wheel_form.setContentsMargins(0, 0, 0, 0)
        self.wheel_form.setHorizontalSpacing(12)
        self.wheel_form.setVerticalSpacing(8)
        self.wheel_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.wheel_hotkeys: dict[str, QLineEdit] = {}
        more_form.addRow(self.wheel_rows)
        suggest = QPushButton("Use the suggested keys")
        suggest.setToolTip("Fills each empty box with Ctrl+Shift and its letter: " + ", ".join(hotkey.SUGGESTED.values()))
        suggest.clicked.connect(self.suggest_hotkeys)
        more_form.addRow("", suggest)
        more.hide()
        more_fold = QPushButton("Show", objectName="moreLink")  # release 5.61: each hotkey a row of its own, under a fold
        more_fold.setIcon(icon("chevron-right"))
        more_fold.clicked.connect(lambda: (more.setVisible(more.isHidden()), set_fold(more_fold, "Hide" if not more.isHidden() else "Show", not more.isHidden())))
        self._card(lay, "You and your hotkeys", [
            ("Me", "Who “I” and “me” are in captures.", self.me),
            ("Hotkey", "Opens the capture window. It needs Ctrl, Alt or Win.", self.hotkey),
            ("More hotkeys", "Each is off until you set it; Use the suggested keys fills the empty ones with Ctrl+Shift and the topic's "
                             "letter. While DocRepo runs, a hotkey is taken from other programs, such as Outlook's Ctrl+Shift+N. Pause "
                             "hotkeys in the tray menu pauses them all.", more_fold),
            (None, None, more),
        ])

    def _build_backups(self, lay) -> None:
        """Backups (part of ``__init__``, release 5.95)."""
        self.backup = QLineEdit()
        self.backup.setPlaceholderText("Not set: no backups are made")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_backup)
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
        folder = QWidget()
        fl = QHBoxLayout(folder)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)
        fl.addWidget(self.backup, 1)
        fl.addWidget(browse)
        folder.setMinimumWidth(380)
        self._card(lay, "Backups", [
            ("Backup folder", "Where backups go: a copy of docs.db and a mirror of the data root's files. Outside the data root.", folder),
            ("How often", "At DocRepo's first start of the day, and how many copies of docs.db it keeps.",
             _row(self.backup_days, QLabel("keeping"), self.backup_keep)),
            (self.backup_status, "", _row(now)),
        ])

    def _build_calendar(self, lay) -> None:
        """Calendar and reminders (part of ``__init__``, release 5.95)."""
        self.reminder = QTimeEdit()
        self.reminder.setDisplayFormat("HH:mm")
        self.reminder.setFixedWidth(96)
        self.workdays = {d: QCheckBox(d) for d in WEEKDAYS}
        self.horizon = QSpinBox()
        self.horizon.setRange(1, 10)
        self.horizon.setSuffix(" years")
        self.horizon.setFixedWidth(120)
        self._card(lay, "Calendar and reminders", [
            ("Reminders at", "Each day's reminders show as notifications from this time.", self.reminder),
            ("Workdays", "The capacity calendar spreads hours over these days.", _row(*self.workdays.values())),
            ("Capacity horizon", "How far ahead routine tasks fill the capacity calendar.", self.horizon),
        ])

    def _build_review(self, lay) -> None:
        """The weekly review (release 5.128, the cold-eyes plan's decisions 499, 500 and 502): its day, how often a project
        comes up, and when a task has gone quiet, which the quick summary's grey "quiet" uses too."""
        self.review_day = QComboBox()
        self.review_day.setAccessibleName("Review day")
        for day, name in zip(WEEKDAYS, ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"), strict=True):
            self.review_day.addItem(name, day)
        self.review_day.setFixedWidth(160)
        self.review_weeks = QComboBox()
        self.review_weeks.setAccessibleName("Projects come up for review")
        for weeks, words in ((1, "Every week"), (2, "Every 2 weeks"), (4, "Every 4 weeks")):
            self.review_weeks.addItem(words, weeks)
        self.review_weeks.setFixedWidth(160)
        self.quiet_days = QSpinBox()
        self.quiet_days.setRange(1, 365)
        self.quiet_days.setSuffix(" days")
        self.quiet_days.setAccessibleName("Gone quiet after")
        self.quiet_days.setFixedWidth(120)
        self._card(lay, "Weekly review", [
            ("Review day", "That day, Today's first line is Weekly review, until you finish one.", self.review_day),
            ("Projects come up", "How often an open top-level task comes up in Review's Projects step. A task can have its own "
                                 "interval, or never, in Edit task's More options.", self.review_weeks),
            ("Gone quiet after", "A task nothing has touched for this long (a capture, a change, an edit of its notes, on it or "
                                 "under it) is in Review's Gone quiet step, and grey in the quick summary.", self.quiet_days),
        ])

    def _build_parse(self, lay) -> None:
        """Parse and populate (part of ``__init__``, release 5.95)."""
        self.events = QLineEdit()
        self.events.setPlaceholderText("Comma-separated")
        self.events.setMinimumWidth(380)
        self.references = ReferenceFields()  # release 5.9, mods log round 2, M0034; link addresses since release 5.67
        self._card(lay, "Parse and populate", [
            ("Event words", "Words Parse and populate reads as events, for deadlines.", self.events),
            ("Reference fields", "Fields every task gets, such as a change record's number. Each shows on the task's page with Copy, is "
                                 "found by search, and Parse and populate reads its name followed by a number. With a link address, "
                                 "its value is also a link to its page: the value goes where {} is, or at the end. The address stays on "
                                 "this computer.", self.references.add_button),
            (None, "", self.references),
        ])

    def _build_tagged(self, lay) -> None:
        """Tagged labels: the tag patterns, Never a tag, the tester and Try on everything (release 5.80, the tagged labels
        plan's items 106 and 107), a form of its own (``ui/tagged_settings.py``)."""
        from docrepo.ui.tagged_settings import TaggedSettings

        self.tagged = TaggedSettings(lambda: tagged.read_labels(self.ctx.conn),
                                     lambda patterns, never: tagged.try_everything(self.ctx.conn, Model(self.ctx.conn), patterns, never))
        self.tagged_card = self._card(lay, "Tagged labels", [(None, None, self.tagged)])

    def show_tagged(self) -> None:
        """Scroll to the Tagged labels section (the Tagged labels view's Patterns…)."""
        self.scroll.ensureWidgetVisible(self.tagged_card, 0, 0)
        self.scroll.verticalScrollBar().setValue(self.tagged_card.y())

    def _build_files(self, lay) -> None:
        """Files and prompts (part of ``__init__``, release 5.95)."""
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
        for w in (self.cap, self.warn, self.check):
            w.setFixedWidth(180)
        self.copilot = QLineEdit()
        self.copilot.setPlaceholderText("Not set")
        self.copilot.setAccessibleName("Copilot's folder")
        pick_copilot = QPushButton("Browse…")
        pick_copilot.clicked.connect(self._pick_copilot)
        copilot_row = QWidget()
        cl = QHBoxLayout(copilot_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addWidget(self.copilot, 1)
        cl.addWidget(pick_copilot)
        copilot_row.setMinimumWidth(380)
        self._card(lay, "Files and prompts", [
            ("Extracted text", "The most text kept from each file.", self.cap),
            ("Copy prompt warns", "Copy prompt warns when a prompt is longer than this.", self.warn),
            ("Document checks", "How often tracked documents are checked for changes (a later version).", self.check),
            ("Copilot's folder", "Where Copilot leaves tree files and edit files for the Import window to offer. DocRepo only reads it. Outside the data root.", copilot_row),
        ])

    def _build_outlook(self, lay) -> None:
        """Outlook (release 5.33) (part of ``__init__``, release 5.95)."""
        self.categories = QCheckBox("Mark filed emails in Outlook with their task's name")
        self.categories.setToolTip("Each email a capture files on a task gets the task's name as a category in Outlook")
        self.colour = QComboBox()
        for name in outlook.COLOURS:
            self.colour.addItem("None: leave Outlook's list alone" if name == "None" else name, name)
        self.colour.setFixedWidth(240)
        self._card(lay, "Outlook", [
            ("Categories", "When a capture with an Outlook email is saved on a task, DocRepo adds the task's name to the email in "
                           "Outlook as a category, so Outlook's search finds it (category:\"Pump trial\"). Nothing else on the email "
                           "changes, and nobody on the email sees it.", self.categories),
            ("Category colour", "A new category goes on Outlook's list of categories in this colour, so it shows on the email. One "
                                "already on the list keeps its own colour.", self.colour),
        ])

    def _build_troubleshooting(self, lay) -> None:
        """The troubleshooting report, to bring to the personal computer (part of ``__init__``, release 5.95)."""
        self.try_category = QCheckBox("Also try a test category on the selected email")
        self.try_category.setToolTip("Adds the category DocRepo test to the email selected in Outlook, then puts its categories back")
        # The T-mail try-outs (the knowledge base's checks C1, C3 and C4, release 5.101)
        self.try_t_mail = QCheckBox("Also try a new email and a reply")
        self.try_t_mail.setToolTip("Makes a new email, and a reply to the selected email and to your newest saved one, reads each one's "
                                   "conversation index, and closes it without saving. Nothing is shown, saved or sent")
        report = QPushButton("Troubleshooting report…")
        report.setToolTip("Saved in System\\diagnostics in the data root, and shown here to copy")
        report.clicked.connect(self.troubleshooting_report)
        check = QPushButton("Check the data root")
        check.setToolTip("Lists what docs.db says is there and isn't, and checks the database. It changes nothing.")
        check.clicked.connect(self.check_data_root)
        self._card(lay, "Troubleshooting", [
            ("Troubleshooting report", "DocRepo's versions, a check of reading the email selected in Outlook, recent drags and recent "
                                       "problems. It leaves out email text, names and addresses. Select an email in Outlook first.",
             _row(report, self.try_category, self.try_t_mail)),
            ("Check the data root", "Captures whose capture.md is missing, documents and saved copies whose files aren't there, the "
                                    "search index, and SQLite's own check of docs.db. Nothing is changed: each line says what you can do.",
             _row(check)),
        ])

        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addSpacing(8)
        lay.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        save = QPushButton("Save settings", objectName="primary" if LOOK.classic else "")
        save.clicked.connect(self.save)
        undo = QPushButton("Undo changes")
        undo.clicked.connect(self.load)
        buttons.addWidget(save)
        buttons.addWidget(undo)
        buttons.addStretch()
        lay.addLayout(buttons)
        lay.addStretch()

    def _card(self, lay: QVBoxLayout, title: str, rows: list) -> QWidget:
        """A group of settings: its heading, then a card with a row for each: its name and what it does, then its control."""
        lay.addSpacing(16)
        lay.addWidget(QLabel(title, objectName="heading"))
        card = QWidget(objectName="settingsCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 4, 16, 4)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)
        for i, (name, what, control) in enumerate(rows):
            if name is None:  # all the row's width, under the row above
                grid.addWidget(control, 2 * i, 0, 1, 2)
                continue
            left = QWidget()
            ll = QVBoxLayout(left)
            ll.setContentsMargins(0, 12, 0, 12)
            ll.setSpacing(2)
            ll.addWidget(QLabel(name) if isinstance(name, str) else name)
            if what:
                note = QLabel(what, objectName="hint")
                note.setWordWrap(True)
                ll.addWidget(note)
            grid.addWidget(left, 2 * i, 0)
            grid.addWidget(control, 2 * i, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if i < len(rows) - 1 and rows[i + 1][0] is not None:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setObjectName("divider")
                grid.addWidget(line, 2 * i + 1, 0, 1, 2)
        lay.addWidget(card)
        return card

    def _hints_toggled(self, on: bool) -> None:
        """Show hints applies at once, in every window (decision 7); Save settings keeps it."""
        set_hints(on)

    def suggest_hotkeys(self) -> None:
        """Use the suggested keys (mods log round 2, M0036): each empty hotkey box gets Ctrl+Shift and its letter. Nothing is
        saved until Save settings."""
        filled = [setting for setting, box in self.more_hotkeys.items() if not box.text().strip() and setting in hotkey.SUGGESTED]
        for setting in filled:
            self.more_hotkeys[setting].setText(hotkey.SUGGESTED[setting])
        self.message(f"Filled {len(filled)} hotkey{'s' if len(filled) != 1 else ''}. Save settings to use them." if filled
                     else "Every hotkey box already has keys.")

    def _load_wheel_hotkeys(self) -> None:
        """A box per wheel, from the config file: its hotkey, or none until you set one (decision 216)."""
        rows = wheels_config.hotkey_rows(self.ctx.data_root, SPECS, icon_names())
        if [w for w, _ in rows] != list(self.wheel_hotkeys):
            while self.wheel_form.rowCount():
                self.wheel_form.removeRow(0)
            self.wheel_hotkeys = {}
            for n, (wheel_id, name) in enumerate(rows, 1):
                box = QLineEdit()
                box.setPlaceholderText(f"Off, such as Ctrl+Shift+{n}" if n < 10 else "Off")
                box.setFixedWidth(200)
                self.wheel_hotkeys[wheel_id] = box
                self.wheel_form.addRow(f"The {name} wheel", box)
        for wheel_id, box in self.wheel_hotkeys.items():
            box.setText(self.ctx.settings.wheel_hotkeys.get(wheel_id, ""))

    # ---- filling and reading the form ----
    def load(self) -> None:
        """Show the saved settings and the data root's facts."""
        s, m = self.ctx.settings, Model(self.ctx.conn)
        choice = resolve_data_root(None)
        override = "" if choice.path and choice.path.resolve() == self.ctx.data_root.resolve() else (
            f" <span style='color:{C.caution}'>DocRepo was started with another data root (the command line or DOCREPO_DATA_ROOT), so the recorded "
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
        self._load_wheel_hotkeys()
        self.backup.setText(s.backup_dir or "")
        self.copilot.setText(s.copilot_folder or "")
        self.reminder.setTime(QTime.fromString(s.reminder_time, "HH:mm") if QTime.fromString(s.reminder_time, "HH:mm").isValid() else QTime(8, 0))
        for d, box in self.workdays.items():
            box.setChecked(d in s.workdays)
        self.horizon.setValue(s.capacity_horizon_years)
        self.review_day.setCurrentIndex(max(0, self.review_day.findData(s.review_day)))
        self.review_weeks.setCurrentIndex(max(0, self.review_weeks.findData(s.review_weeks)))
        self.quiet_days.setValue(s.quiet_days)
        self.events.setText(", ".join(s.event_words))
        self.references.set(s.reference_fields, s.reference_links)
        self.tagged.set(s.tagged_patterns, s.tagged_never)
        self.cap.setValue(s.extracted_text_cap_chars)
        self.warn.setValue(s.prompt_warn_chars)
        self.check.setValue(s.doc_check_minutes)
        self.backup_days.setValue(s.backup_every_days)
        self.backup_keep.setValue(s.backup_keep)
        self.look.setCurrentIndex(max(0, self.look.findData(s.look)))
        self.hints.blockSignals(True)
        self.hints.setChecked(s.show_hints)
        self.hints.blockSignals(False)
        self.categories.setChecked(s.outlook_categories)
        self.colour.setCurrentIndex(max(0, self.colour.findData(s.outlook_category_colour)))
        self.startup_status.setText(f"<b>Start when you sign in:</b> {startup.status()}")
        self.show_backup_status()
        self.error.hide()

    def values(self) -> dict[str, Any]:
        """The settings as the view shows them, by field, ready to check and save."""
        return {
            "me": self.me.currentData(), "hotkey": self.hotkey.text(), **{k: box.text() for k, box in self.more_hotkeys.items()},
            "wheel_hotkeys": {**self.ctx.settings.wheel_hotkeys, **{k: box.text() for k, box in self.wheel_hotkeys.items()}},
            "backup_dir": self.backup.text(),
            "copilot_folder": self.copilot.text(),
            "reminder_time": self.reminder.time().toString("HH:mm"), "workdays": [d for d, box in self.workdays.items() if box.isChecked()],
            "capacity_horizon_years": self.horizon.value(), "event_words": [w for w in self.events.text().split(",")],
            "review_day": self.review_day.currentData(), "review_weeks": self.review_weeks.currentData(), "quiet_days": self.quiet_days.value(),
            "reference_fields": self.references.names(), "reference_links": self.references.links(),
            "tagged_patterns": self.tagged.patterns(), "tagged_never": self.tagged.never(),
            "extracted_text_cap_chars": self.cap.value(), "prompt_warn_chars": self.warn.value(), "doc_check_minutes": self.check.value(),
            "backup_every_days": self.backup_days.value(), "backup_keep": self.backup_keep.value(),
            "look": self.look.currentData(), "show_hints": self.hints.isChecked(), "outlook_categories": self.categories.isChecked(),
            "outlook_category_colour": self.colour.currentData(),
        }

    def save(self) -> list[str]:
        """Save what changed, and say so. Returns the fields that changed: none when nothing did or a value is refused."""
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
            n = sum(1 for k in changed if k in hotkey.HOTKEY_IDS or k == "wheel_hotkeys")
            later = f" The hotkey{'s work' if n > 1 else ' works'} from now on." if n else ""
            later += " The look changes the next time DocRepo starts." if "look" in changed else ""
            if "tagged_patterns" in changed or "tagged_never" in changed:  # release 5.80
                fresh = sum(1 for lb in tagged.read_labels(self.ctx.conn) if lb.status == "suggested")
                later += (f" Everything is matched again: {fresh:,} new tagged label{'s are' if fresh != 1 else ' is'} on what mentions "
                          f"{'them' if fresh != 1 else 'it'}, marked new, under Suggested in Tagged labels.")
            self.message(f"Saved {len(changed)} setting{'s' if len(changed) > 1 else ''} to settings.json.{later}")
        return changed

    # ---- backups ----
    def show_backup_status(self) -> None:
        """The backup card's line: off, when the last backup was, or what went wrong."""
        s = self.ctx.settings
        if not s.backup_dir:
            self.backup_status.setText("<b>Backups:</b> off. Choose a backup folder and save, to turn them on.")
            return
        last = backup.last_backup(self.ctx.conn)
        trouble = backup.last_problem(self.ctx.conn)  # release 5.89: a copy that failed its check, or a backup that wasn't made
        problem = (f'<br><span style="color:{C.critical}"><b>The last try, on {esc(long_date(datetime.fromisoformat(trouble[0]).date(), self.ctx.now().date()))}'
                   f" at {esc(trouble[0][11:16])}:</b> {esc(trouble[1])}</span>") if trouble else ""
        if not last:
            self.backup_status.setText("<b>Backups:</b> none yet. The first is made at DocRepo's next start, or with Back up now." + problem)
            return
        when = datetime.fromisoformat(last)
        left = s.backup_every_days - (self.ctx.now().date() - when.date()).days
        nxt = "at DocRepo's next start" if left <= 0 else "tomorrow" if left == 1 else f"in {left} days"
        self.backup_status.setText(f"<b>Backups:</b> the last was on {long_date(when.date(), self.ctx.now().date())} at "
                                   f"{last[11:16]}. The next is due {nxt}. Each one is listed in backup-log.md in the backup folder." + problem)

    def backup_now(self) -> None:
        """Start a backup now, once the backup folder shown is the one saved."""
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
            backup.record_failure(self.ctx.conn, stamp(self.ctx.now()), f"The backup couldn't be made. {e}")
            self.show_backup_status()
            self.message(str(e))
            return
        backup.record(self.ctx.conn, result)
        self.show_backup_status()
        self.message(result.message())

    # ---- the Startup shortcut ----
    def make_shortcut(self) -> None:
        """Make the Startup shortcut, and say where it is and where to move it."""
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
            trying, colour = self.try_category.isChecked(), self.ctx.settings.outlook_category_colour
            t_mail = self.try_t_mail.isChecked()
            scratch = outlook.copy_path(self.ctx.fs, self.ctx.data_root)
            reply_to = diagnose.newest_saved_email(self.ctx.data_root) if t_mail else None
            text = diagnose.build_report(self.ctx.data_root, now, list(diagnose.DRAGS), drops=list(diagnose.DROPS),
                                         check_outlook=lambda: diagnose.outlook_check(try_category=trying, scratch=scratch, colour=colour,
                                                                                      try_t_mail=t_mail, reply_to=reply_to))
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

    def check_data_root(self, show: bool = True) -> ReportDialog:
        """Check the data root against docs.db (release 5.89), keep the list as System\\check-<date>.md, and show it."""
        from docrepo.check import run_check, write_report

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = run_check(self.ctx.conn, self.ctx.data_root, self.ctx.now())
            try:
                path: Path | None = write_report(self.ctx.fs, self.ctx.data_root, result)
            except (OSError, WriteRefused) as e:
                log.warning("data root check not saved: %s", e)
                path = None
        finally:
            QGuiApplication.restoreOverrideCursor()
        found = (f"{result.problems} thing{'s' if result.problems != 1 else ''} to look at." if result.problems else "Nothing needs doing.")
        self.message(f"Checked the data root: {found}")
        kept = f"It's kept as {path.name} in System." if path else "It couldn't be saved, so copy it from here."
        dialog = ReportDialog(self, result.markdown(), path, self.reveal, "Data root check", f"{found} Nothing was changed. {kept}")
        if show:
            dialog.exec()
        return dialog

    def _pick_copilot(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Copilot's folder", self.copilot.text())
        if folder:
            self.copilot.setText(str(Path(folder)))

    def _pick_backup(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Backup folder", self.backup.text())
        if folder:
            self.backup.setText(str(Path(folder)))

    def change_data_root(self) -> None:
        """Choose another folder as the data root, set it up if it's new, and record it for DocRepo's next start."""
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
