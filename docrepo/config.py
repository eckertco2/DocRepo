"""Where DocRepo's data lives, and its settings.

The data root's location is the one setting that can't live inside the data
root, so it's kept in ``%LOCALAPPDATA%\\DocRepo\\location.json``. Everything else
is in ``<data root>\\Config\\settings.json``. No path is ever written into the code.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

ENV_DATA_ROOT = "DOCREPO_DATA_ROOT"
LOCATION_FILE = "location.json"
SETTINGS_FILE = Path("Config") / "settings.json"
CODE_DIR = Path(__file__).resolve().parent.parent

#: The folders every data root has. Others (a task's Files folder, for example) appear only when needed.
DATA_ROOT_FOLDERS = ("Captures", "Tasks", "Documents", "Mods", "Config/prompts", "System/logs")


class SettingsError(Exception):
    """settings.json exists but can't be read. It's never overwritten silently."""


def app_dir() -> Path:
    """DocRepo's own folder for this Windows user: %LOCALAPPDATA%\\DocRepo."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "DocRepo"


def location_file() -> Path:
    return app_dir() / LOCATION_FILE


@dataclass(frozen=True)
class DataRootChoice:
    """The data root DocRepo will use, and where that choice came from."""

    path: Path | None
    source: str


def read_location() -> Path | None:
    """The data root recorded in location.json, or None if there isn't a usable one."""
    file = location_file()
    if not file.exists():
        return None
    try:
        value = json.loads(file.read_text(encoding="utf-8")).get("data_root")
    except (OSError, ValueError, AttributeError) as e:
        log.warning("Can't read %s: %s", file, e)
        return None
    return Path(value) if isinstance(value, str) and value else None


def save_location(data_root: Path) -> Path:
    """Record where the data root is, in location.json."""
    fs = SafeFS([app_dir()])
    text = json.dumps({"data_root": str(data_root)}, indent=2) + "\n"
    return fs.write_text(location_file(), text)


def resolve_data_root(cli_value: str | None = None) -> DataRootChoice:
    """Pick the data root: the command line first, then the environment, then location.json."""
    if cli_value:
        return DataRootChoice(Path(os.path.abspath(cli_value)), "the command line")
    env_value = os.environ.get(ENV_DATA_ROOT)
    if env_value:
        return DataRootChoice(Path(os.path.abspath(env_value)), f"the {ENV_DATA_ROOT} environment variable")
    recorded = read_location()
    if recorded:
        return DataRootChoice(recorded, str(location_file()))
    return DataRootChoice(None, "not set")


def onedrive_folders() -> list[Path]:
    """The OneDrive folders Windows knows about for this user."""
    names = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
    return [Path(os.environ[n]) for n in names if os.environ.get(n)]


def _inside(path: Path, folder: Path) -> bool:
    p = os.path.normcase(os.path.abspath(path))
    f = os.path.normcase(os.path.abspath(folder)).rstrip("\\/")
    return p == f or p.startswith(f + os.sep)


def data_root_problem(path: Path, *, allow_code_dir: bool = False) -> str | None:
    """Why ``path`` can't be the data root, or None if it can.

    ``allow_code_dir`` lets development data (``dev_data``) live in the code folder.
    """
    if not path.is_absolute():
        return "use a full path, starting with a drive letter"
    for folder in onedrive_folders():
        if _inside(path, folder):
            return f"it's inside OneDrive ({folder}). Keep the data root on the local drive, outside OneDrive"
    if not allow_code_dir and _inside(path, CODE_DIR):
        return "it's inside DocRepo's code folder. Keep it outside, so updates never touch your data"
    return None


@dataclass
class Settings:
    """The contents of Config/settings.json."""

    schema_version: int = 1
    me: str | None = None
    hotkey: str = "Ctrl+Shift+Space"
    # More hotkeys (mods log round 1), each off until set: the browse tool, each capture type, and Add to agenda; and a
    # quick task on Today (round 2, M0039); and Pin (round 3, M0053), which Use the suggested keys leaves alone.
    browse_hotkey: str = ""
    note_hotkey: str = ""
    new_task_hotkey: str = ""
    update_hotkey: str = ""
    agenda_hotkey: str = ""
    today_hotkey: str = ""
    pin_hotkey: str = ""
    #: Adds the email selected in Outlook to the capture, on the pinned window, from Outlook itself (release 5.33.1).
    outlook_hotkey: str = ""
    #: The navigation wheels' hotkeys, keyed by wheel ID (release 5.41, decision 216): none until set, like the others.
    wheel_hotkeys: dict[str, str] = field(default_factory=dict)
    #: Opens or closes the Today side panel (release 5.43).
    today_panel_hotkey: str = ""
    backup_dir: str | None = None
    backup_every_days: int = 7
    backup_keep: int = 8
    doc_check_minutes: int = 60
    reminder_time: str = "08:00"
    extracted_text_cap_chars: int = 200_000
    prompt_warn_chars: int = 60_000
    capacity_horizon_years: int = 5
    workdays: list[str] = field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])
    event_words: list[str] = field(default_factory=lambda: ["turnaround", "shutdown", "audit", "inspection", "outage", "walkthrough"])
    #: Reference fields every task has (mods log round 2, M0034, release 5.9), such as a change record's number. Named
    #: here, never in the code, so DocRepo names no company system.
    reference_fields: list[str] = field(default_factory=list)
    #: Each reference field's link address, by its name (release 5.67, round 6's decision 320): the field's value goes
    #: where ``{}`` is, or at the end, and becomes a link to its page. Typed on the owner's computer, never in the code.
    reference_links: dict[str, str] = field(default_factory=dict)
    #: The visual overhaul (releases 5.10 to 5.16): "new", or "classic" for release 5.9's look (decision 15); and Show
    #: hints, which brings back the help text, ⓘ buttons and key badges (decision 7). Both take effect when DocRepo starts.
    look: str = "new"
    show_hints: bool = False
    #: Mark filed emails in Outlook (release 5.33, the knowledge base's decisions 24 to 26): each email a capture files on
    #: a task gets the task's name as a category in Outlook. Off until the owner turns it on, since it changes the email.
    outlook_categories: bool = False
    #: The colour a category gets on Outlook's list of categories when DocRepo puts it there (release 5.33.1, decision 26 as
    #: the owner changed it): one of ``outlook.COLOURS``; "None" leaves the list alone, so the category shows uncoloured.
    outlook_category_colour: str = "Teal"
    #: Where Copilot leaves files for DocRepo to read (release 5.56, the tree files plan's item 84). DocRepo only reads it, and it's outside the data root.
    copilot_folder: str | None = None
    #: Tag patterns (release 5.80, the tagged labels plan's item 106, decision 372): each a name, a mask (``tagged_masks``)
    #: and whether a space may stand between its parts, as {"name": ..., "mask": ..., "space": false}. They're the plant's
    #: own conventions, so DocRepo ships none. docs.db keeps a copy for matching (``tagged.use_settings``).
    tagged_patterns: list[dict] = field(default_factory=list)
    #: Never a tag (decision 375): whole tags (ABC123) or starts with * (API*) that no pattern makes a tagged label.
    tagged_never: list[str] = field(default_factory=list)
    #: The quick summary (release 5.131, the quick summary plan's decisions 524 and 534): a task nothing has touched for this
    #: many days is quiet (the weekly review's setting too, when it comes); and the subjects pinned to the box's list, and the
    #: recent ones, as "person:P004", "agenda:T000010" or "label:Safety".
    quiet_days: int = 21
    summary_pins: list[str] = field(default_factory=list)
    summary_recent: list[str] = field(default_factory=list)
    #: Today's meetings from the Outlook calendar (release 5.127, the cold-eyes plan's decision 494): Today's first group, and
    #: the side panel's first line. On by default; off, DocRepo doesn't read the calendar at all.
    today_meetings: bool = True

    @classmethod
    def load(cls, data_root: Path) -> Settings:
        """Read settings.json. A missing file gives the defaults; an unreadable one raises SettingsError."""
        file = data_root / SETTINGS_FILE
        if not file.exists():
            return cls()
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SettingsError(f"Can't read {file}: {e}") from e
        if not isinstance(data, dict):
            raise SettingsError(f"{file} doesn't hold a JSON object.")
        known = {f.name for f in fields(cls)}
        for key in sorted(set(data) - known):
            log.warning("Ignoring unknown setting %r in %s", key, file)
        links = data.get("reference_links")
        if links is not None and not (isinstance(links, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in links.items())):
            log.warning("Ignoring reference_links in %s: it isn't names and addresses", file)
            data = {k: v for k, v in data.items() if k != "reference_links"}
        # The tagged labels' patterns and Never a tag (release 5.80): a list of patterns with masks, and a list of words.
        patterns = data.get("tagged_patterns")
        if patterns is not None:
            from docrepo.tagged_masks import patterns_of

            if not isinstance(patterns, list):
                log.warning("Ignoring tagged_patterns in %s: it isn't a list", file)
            data["tagged_patterns"] = [p.as_setting() for p in patterns_of(patterns)]
        never = data.get("tagged_never")
        if never is not None:
            if not (isinstance(never, list) and all(isinstance(x, str) for x in never)):
                log.warning("Ignoring tagged_never in %s: it isn't a list of words", file)
                never = []
            data["tagged_never"] = never
        # The quick summary's pins and recents (release 5.131): lists of words; anything else is left out.
        for key in ("summary_pins", "summary_recent"):
            value = data.get(key)
            if value is not None and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
                log.warning("Ignoring %s in %s: it isn't a list of words", key, file)
                del data[key]
        quiet = data.get("quiet_days")
        if quiet is not None and not (isinstance(quiet, int) and not isinstance(quiet, bool) and 1 <= quiet <= 365):
            log.warning("Ignoring quiet_days in %s: it isn't a number of days from 1 to 365", file)
            del data["quiet_days"]
        return cls(**{k: v for k, v in data.items() if k in known})

    def reference_link(self, name: str, value: str | None) -> str:
        """A reference field's value as a link to its page, from the field's link address (release 5.67), or "" for a field
        with no link address, or no value."""
        from docrepo.links import reference_link

        return reference_link(self.reference_links.get(name), value)

    def save(self, fs: SafeFS, data_root: Path) -> Path:
        data = asdict(self)
        for key in ("wheel_hotkeys", "today_panel_hotkey", "copilot_folder", "reference_links", "tagged_patterns", "tagged_never",
                    "summary_pins", "summary_recent"):  # written once they're set, as they're optional (releases 5.41, 5.56, 5.67, 5.80 and 5.131)
            if not data[key]:
                del data[key]
        if data["quiet_days"] == 21:  # release 5.131: written once it's changed from its default, as the optional ones are
            del data["quiet_days"]
        if data["today_meetings"]:  # release 5.127: on by default, so written only once it's turned off
            del data["today_meetings"]
        return fs.write_text(data_root / SETTINGS_FILE, json.dumps(data, indent=2) + "\n")


def make_safe_fs(data_root: Path, settings: Settings) -> SafeFS:
    """The SafeFS for normal use: the data root, the backup folder if one is set, and DocRepo's own folder."""
    roots: list[Path] = [data_root, app_dir()]
    if settings.backup_dir:
        roots.append(Path(settings.backup_dir))
    # Backups may replace their own copies, but never in the data root, even if settings.json says the backup folder is there.
    backup = Path(settings.backup_dir) if settings.backup_dir else None
    usable = backup is not None and not _inside(backup, data_root) and not _inside(data_root, backup)
    return SafeFS(roots, replace_roots=[backup] if usable else [])


def init_data_root(data_root: Path) -> list[Path]:
    """Create the data root's standard folders and default settings. Returns what was created."""
    settings = Settings.load(data_root)
    fs = make_safe_fs(data_root, settings)
    created = []
    for name in DATA_ROOT_FOLDERS:
        folder = data_root / name
        if not folder.exists():
            created.append(fs.makedirs(folder))
    if not (data_root / SETTINGS_FILE).exists():
        created.append(settings.save(fs, data_root))
    return created
