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
    backup_dir: str | None = None
    doc_check_minutes: int = 60
    extracted_text_cap_chars: int = 200_000
    prompt_warn_chars: int = 60_000
    capacity_horizon_years: int = 5
    workdays: list[str] = field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])

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
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, fs: SafeFS, data_root: Path) -> Path:
        return fs.write_text(data_root / SETTINGS_FILE, json.dumps(asdict(self), indent=2) + "\n")


def make_safe_fs(data_root: Path, settings: Settings) -> SafeFS:
    """The SafeFS for normal use: the data root, the backup folder if one is set, and DocRepo's own folder."""
    roots: list[Path] = [data_root, app_dir()]
    if settings.backup_dir:
        roots.append(Path(settings.backup_dir))
    return SafeFS(roots)


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
