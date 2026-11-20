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

from docrepo.layer0 import DEFAULT_DROP, OTHER_LINKS, entry_problem, tidy_list
from docrepo.safe_fs import SafeFS

#: Open a task in (release 5.174, decision 815): each choice and its words in Settings.
OPEN_TASKS_IN = {"workspace": "Its workspace", "page": "Its page"}

log = logging.getLogger(__name__)

ENV_DATA_ROOT = "DOCREPO_DATA_ROOT"
LOCATION_FILE = "location.json"
SETTINGS_FILE = Path("Config") / "settings.json"
CODE_DIR = Path(__file__).resolve().parent.parent

#: The days the weekly review may fall on (release 5.128, decision 502), as ``dates.WEEKDAYS`` names them.
REVIEW_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

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
    #: Log progress (release 5.139, the design workspace's docs/mods/email-progress-plan.md, decision 583): off until set.
    progress_hotkey: str = ""
    #: The glossary lookup (release 5.172, the design workspace's docs/mods/glossaries-plan.md, decision 808): off until set.
    lookup_hotkey: str = ""
    #: Back to the task you're working on (release 5.177, the design workspace's docs/mods/current-task-plan.md, decision 829):
    #: off until set.
    current_hotkey: str = ""
    #: Whether Log progress's Enter sends the draft in its own window (decision 590 A); off, Enter logs and brings the draft
    #: back to the front for the owner to send (590 B).
    progress_sends: bool = True
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
    #: The look: "new" (the visual overhaul, releases 5.10 to 5.16), the one there is since release 5.179 retired release
    #: 5.9's (the redesign's decision 840). Kept in settings.json as it was; a saved "classic" is read as "new". And Show
    #: hints, which brings back the help text, ⓘ buttons and key badges (decision 7). It takes effect when DocRepo starts.
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
    #: The glossaries the lookup opened last, by ID, the latest first (release 5.172, decision 807).
    glossary_recent: list[str] = field(default_factory=list)
    #: Saved sets (release 5.149, the design workspace's docs/mods/summary-sets-plan.md, decisions 649 and 650): a pinned
    #: combination's name, by its key in ``summary_pins`` ("person:P003 + agenda:T000010": "Morning meeting").
    summary_names: dict[str, str] = field(default_factory=dict)
    #: Today's meetings from the Outlook calendar (release 5.127, the cold-eyes plan's decision 494): Today's first group, and
    #: the side panel's first line. On by default; off, DocRepo doesn't read the calendar at all.
    today_meetings: bool = True
    #: The weekly review (release 5.128, the cold-eyes plan's decisions 499 and 502): the day Today offers it, as "Fri", and
    #: how many weeks apart an open top-level task with no interval of its own comes up for review (1, 2 or 4). ``quiet_days``
    #: is its Gone quiet too (decision 500).
    review_day: str = "Fri"
    review_weeks: int = 1
    #: The email link filter (release 5.146, the design workspace's docs/mods/email-link-filter-plan.md, decisions 635 to
    #: 639): the sites whose links email layer 0 always keeps and never keeps, one entry each (a domain, or a domain and the
    #: start of a path), and what a link on neither list gets ("keep", "untick" or "leave"). Never keep starts with meeting
    #: links; Always keep starts empty, as the company's own sites can't be named here. Each is written once it's changed.
    links_keep: list[str] = field(default_factory=list)
    links_drop: list[str] = field(default_factory=lambda: list(DEFAULT_DROP))
    other_links: str = "keep"
    #: Stock headings (release 5.169, the design workspace's docs/mods/stock-headings-plan.md, decisions 788 to 791): topic
    #: headings for every task's notes, each {"name": ..., "level": 1 to 3, "description": what belongs under it}. Four
    #: ship (``stock_headings.DEFAULTS``); the list is written once it differs from them, so an emptied list stays empty.
    stock_headings: list[dict] = field(default_factory=lambda: _stock_defaults())
    #: Open a task in (release 5.174, the design workspace's docs/mods/today-workspace-carry-plan.md, decision 815): "workspace"
    #: or "page". What opening a task from a list, a tile, Task search, the quick summary or File search does; the other one
    #: is the tile menu's second line, and Shift. A link inside a page always goes to the task's page. Written once it's changed.
    open_tasks_in: str = "workspace"

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
        if "look" in data:  # release 5.179: one look, whatever was saved, written back as it when the settings are saved next
            data["look"] = "new"
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
        for key in ("summary_pins", "summary_recent", "glossary_recent"):  # and the glossary lookup's (release 5.172)
            value = data.get(key)
            if value is not None and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
                log.warning("Ignoring %s in %s: it isn't a list of words", key, file)
                del data[key]
        # Saved sets' names (release 5.149): each a name for a pinned combination; one for anything else is left out.
        names = data.get("summary_names")
        if names is not None:
            if not (isinstance(names, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in names.items())):
                log.warning("Ignoring summary_names in %s: it isn't keys and names", file)
                names = {}
            pins = set(data.get("summary_pins") or ())
            kept = {k: " ".join(v.split()) for k, v in names.items() if k in pins and " + " in k and v.strip()}
            if len(kept) < len(names):
                log.warning("Leaving %d names out of summary_names in %s: they aren't pinned combinations", len(names) - len(kept), file)
            data["summary_names"] = kept
        quiet = data.get("quiet_days")
        if quiet is not None and not (isinstance(quiet, int) and not isinstance(quiet, bool) and 1 <= quiet <= 365):
            log.warning("Ignoring quiet_days in %s: it isn't a number of days from 1 to 365", file)
            del data["quiet_days"]
        if "review_day" in data and data["review_day"] not in REVIEW_DAYS:  # release 5.128
            log.warning("Ignoring review_day in %s: it isn't one of %s", file, ", ".join(REVIEW_DAYS))
            del data["review_day"]
        if "review_weeks" in data and (isinstance(data["review_weeks"], bool) or data["review_weeks"] not in (1, 2, 4)):
            log.warning("Ignoring review_weeks in %s: it isn't 1, 2 or 4", file)
            del data["review_weeks"]
        for key in ("links_keep", "links_drop"):  # release 5.146: lists of sites; a line that isn't one is left out
            value = data.get(key)
            if value is None:
                continue
            if not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
                log.warning("Ignoring %s in %s: it isn't a list of sites", key, file)
                del data[key]
                continue
            bad = [x for x in value if x.strip() and entry_problem(x)]
            if bad:
                log.warning("Leaving %d entries out of %s in %s: they aren't sites", len(bad), key, file)
            data[key] = tidy_list(x for x in value if not entry_problem(x))
        stock = data.get("stock_headings")  # release 5.169: a list of stock headings; one that can't be used is left out
        if stock is not None:
            from docrepo.stock_headings import stock_of

            if not isinstance(stock, list):
                log.warning("Ignoring stock_headings in %s: it isn't a list", file)
                del data["stock_headings"]
            else:
                data["stock_headings"] = [h.as_setting() for h in stock_of(stock)]
        if "open_tasks_in" in data and data["open_tasks_in"] not in OPEN_TASKS_IN:  # release 5.174
            log.warning("Ignoring open_tasks_in in %s: it isn't one of %s", file, ", ".join(OPEN_TASKS_IN))
            del data["open_tasks_in"]
        if "other_links" in data and data["other_links"] not in OTHER_LINKS:
            log.warning("Ignoring other_links in %s: it isn't one of %s", file, ", ".join(OTHER_LINKS))
            del data["other_links"]
        return cls(**{k: v for k, v in data.items() if k in known})

    def stock(self) -> list:
        """The stock headings (release 5.169) as ``stock_headings.StockHeading``."""
        from docrepo.stock_headings import stock_of

        return stock_of(self.stock_headings)

    def reference_link(self, name: str, value: str | None) -> str:
        """A reference field's value as a link to its page, from the field's link address (release 5.67), or "" for a field
        with no link address, or no value."""
        from docrepo.links import reference_link

        return reference_link(self.reference_links.get(name), value)

    def save(self, fs: SafeFS, data_root: Path) -> Path:
        data = asdict(self)
        for key in ("wheel_hotkeys", "today_panel_hotkey", "copilot_folder", "reference_links", "tagged_patterns", "tagged_never",
                    "summary_pins", "summary_recent", "summary_names", "progress_hotkey", "lookup_hotkey", "glossary_recent", "current_hotkey"):  # written once they're set, as they're optional (releases 5.41, 5.56, 5.67, 5.80, 5.131, 5.139, 5.149, 5.172 and 5.177)
            if not data[key]:
                del data[key]
        if data["progress_sends"]:  # release 5.139: written once it's turned off
            del data["progress_sends"]
        if data["quiet_days"] == 21:  # release 5.131: written once it's changed from its default, as the optional ones are
            del data["quiet_days"]
        if data["today_meetings"]:  # release 5.127: on by default, so written only once it's turned off
            del data["today_meetings"]
        for key, default in (("review_day", "Fri"), ("review_weeks", 1)):  # release 5.128: the same
            if data[key] == default:
                del data[key]
        # Release 5.146 (decision 639): the link lists and Other links, written once they differ from their start, so an
        # existing data root gets Never keep's start too, and a list emptied on purpose stays empty.
        for key, default in (("links_keep", []), ("links_drop", list(DEFAULT_DROP)), ("other_links", "keep"),
                             ("stock_headings", _stock_defaults()), ("open_tasks_in", "workspace")):  # 5.169 (decision 788) and 5.174: the same
            if data[key] == default:
                del data[key]
        return fs.write_text(data_root / SETTINGS_FILE, json.dumps(data, indent=2) + "\n")


def _stock_defaults() -> list[dict]:
    """The stock headings that ship (release 5.169), as settings.json holds them."""
    from docrepo.stock_headings import defaults

    return defaults()


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
