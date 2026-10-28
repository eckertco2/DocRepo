"""DocRepo's command line: ``python -m docrepo [--data-root PATH] COMMAND``."""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from docrepo import __version__, backup, capacity, db, diagnose, hotkey, prompts, search
from docrepo.config import (
    SETTINGS_FILE,
    Settings,
    SettingsError,
    app_dir,
    data_root_problem,
    init_data_root,
    location_file,
    make_safe_fs,
    resolve_data_root,
    save_location,
)
from docrepo.dates import monday_of
from docrepo.log_setup import setup_logging
from docrepo.model import Model
from docrepo.pages import write_pages
from docrepo.report import build_report
from docrepo.safe_fs import SafeFS, WriteRefused
from docrepo.sample import SAMPLE_AS_OF, SampleError, load_sample, write_sample_files

log = logging.getLogger(__name__)

#: How many weeks the report's capacity table shows.
REPORT_WEEKS = 9


def as_of(value: str) -> datetime:
    """``YYYY-MM-DD`` or ``YYYY-MM-DD HH:MM``, for --as-of."""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M") if " " in value.strip() else datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} isn't YYYY-MM-DD or YYYY-MM-DD HH:MM") from None


def a_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} isn't YYYY-MM-DD") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docrepo", description="Capture and organize work notes, tasks and documents.")
    parser.add_argument("--version", action="version", version=f"DocRepo {__version__}")
    parser.add_argument("--data-root", metavar="PATH", help="use this data root instead of the recorded one (for development and testing)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.add_parser("where", help="show which data root DocRepo uses, and why")
    set_root = commands.add_parser("set-data-root", help="record where your data root is")
    set_root.add_argument("path")
    commands.add_parser("init", help="create the data root's folders, default settings and database")
    try_write = commands.add_parser("try-write", help="check whether DocRepo may write a test file at PATH")
    try_write.add_argument("path")
    as_of_help = "work as if it were this date (and time), YYYY-MM-DD or \"YYYY-MM-DD HH:MM\", for testing"
    sample = commands.add_parser("load-sample", help="fill a new, empty data root with the made-up sample data, for trying DocRepo")
    sample.add_argument("--as-of", type=as_of, metavar="WHEN", help=f"{as_of_help} (default: the sample's own date, 2026-10-08 07:58)")
    rebuild = commands.add_parser("rebuild", help="rebuild the capacity calendar, every generated page and the search index")
    rebuild.add_argument("--as-of", type=as_of, metavar="WHEN", help=as_of_help)
    report = commands.add_parser("report", help="print capacity, days until due, lists, labels, raw text logs and agendas")
    report.add_argument("--as-of", type=as_of, metavar="WHEN", help=as_of_help)
    report.add_argument("--week", type=a_date, metavar="DATE", help="break this week's hours down by task (default: this week)")
    commands.add_parser("app", help="start the capture app: the tray icon, the hotkey and the capture window (use pythonw for no console)")
    commands.add_parser("browse", help="open the browse tool, starting the app if it isn't running (use pythonw for no console)")
    commands.add_parser("backup", help="back up docs.db and the data root's files to the backup folder now")
    commands.add_parser("make-shortcut", help="make DocRepo.lnk, to move into your Startup folder so DocRepo starts when you sign in")
    set_hotkey = commands.add_parser("set-hotkey", help="choose the capture window's hotkey, such as \"Ctrl+Alt+Space\"")
    set_hotkey.add_argument("keys")
    check = commands.add_parser("outlook-check", aliases=["troubleshoot"],
                                help="check each step of reading the email selected in Outlook, and save a troubleshooting report to bring to the personal computer")
    check.add_argument("--try-category", action="store_true",
                       help="also add the category DocRepo test to the selected email, then put its categories back (release 5.33)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (WriteRefused, SettingsError, db.DatabaseError, SampleError, sqlite3.Error) as e:
        print(e, file=sys.stderr)
        return 1


def _data_root(args: argparse.Namespace) -> Path | None:
    choice = resolve_data_root(args.data_root)
    if choice.path is None:
        print("No data root is set yet. Set one with: python -m docrepo set-data-root PATH", file=sys.stderr)
    return choice.path


def _open(args: argparse.Namespace) -> tuple[Path, Settings, SafeFS, sqlite3.Connection] | None:
    """The data root, its settings, a SafeFS and docs.db, with logging started. None if it isn't set up yet."""
    root = _data_root(args)
    if root is None:
        return None
    if not (root / SETTINGS_FILE).exists():
        print(f"{root} isn't set up yet. Run: python -m docrepo init", file=sys.stderr)
        return None
    settings = Settings.load(root)
    fs = make_safe_fs(root, settings)
    setup_logging(fs, root)
    return root, settings, fs, db.connect(fs, root)


def cmd_where(args: argparse.Namespace) -> int:
    choice = resolve_data_root(args.data_root)
    print(f"Location file: {location_file()}")
    if choice.path is None:
        print("Data root: not set yet. Set one with: python -m docrepo set-data-root PATH")
        return 1
    print(f"Data root: {choice.path}")
    print(f"Chosen by: {choice.source}")
    problem = data_root_problem(choice.path, allow_code_dir=True)
    if problem:
        print(f"Warning: {problem}.")
    ready = (choice.path / SETTINGS_FILE).exists()
    print("Status: ready" if ready else "Status: not set up yet. Run: python -m docrepo init")
    return 0


def cmd_set_data_root(args: argparse.Namespace) -> int:
    path = Path(args.path)
    problem = data_root_problem(path)
    if problem:
        print(f"Can't use {path} as the data root: {problem}.", file=sys.stderr)
        return 1
    file = save_location(path)
    print(f"Data root set to {path}. Recorded in {file}.")
    if not (path / SETTINGS_FILE).exists():
        print("Next, create it with: python -m docrepo init")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = _data_root(args)
    if root is None:
        return 1
    problem = data_root_problem(root, allow_code_dir=True)
    if problem:
        print(f"Can't use {root} as the data root: {problem}.", file=sys.stderr)
        return 1
    created = init_data_root(root)
    fs = make_safe_fs(root, Settings.load(root))
    setup_logging(fs, root)
    created += prompts.write_defaults(fs, root)
    if not db.db_path(root).exists():
        created.append(db.db_path(root))
    db.connect(fs, root).close()
    log.info("init: data root ready, %d folders or files created", len(created))
    print(f"Data root ready: {root}")
    for item in created:
        print(f"  created {item}")
    return 0


def cmd_try_write(args: argparse.Namespace) -> int:
    root = _data_root(args)
    if root is None:
        return 1
    fs = make_safe_fs(root, Settings.load(root))
    if (root / SETTINGS_FILE).exists():
        setup_logging(fs, root)
    target = Path(args.path)
    try:
        fs.write_text(target, "DocRepo write test.\n")
    except WriteRefused as e:
        print(f"Refused. {e}")
        return 1
    print(f"Allowed. Wrote {target}")
    return 0


def _rebuild(conn: sqlite3.Connection, root: Path, settings: Settings, fs: SafeFS, when: datetime) -> tuple[int, int]:
    rows = capacity.rebuild_all(conn, when.date(), settings)
    pages = write_pages(Model(conn), root, fs, when.date(), when)
    search.rebuild(conn, root)
    return rows, pages


def cmd_load_sample(args: argparse.Namespace) -> int:
    opened = _open(args)
    if opened is None:
        return 1
    root, settings, fs, conn = opened
    with closing(conn):
        when = args.as_of or SAMPLE_AS_OF
        load_sample(conn)
        if settings.me is None:
            settings.me = "P001"
            settings.save(fs, root)
        files = write_sample_files(conn, root, fs)
        rows, pages = _rebuild(conn, root, settings, fs, when)
    log.info("load-sample: sample data loaded as of %s, %d files, %d calendar rows, %d pages", when, files, rows, pages)
    print(f"Loaded the sample data into {root}, as of {when:%Y-%m-%d %H:%M}.")
    print(f"  {files} capture.md and extracted.txt files, {rows} capacity calendar rows, {pages} generated pages.")
    print("  The sample's emails, attachments and saved copies aren't made, so links to them don't open.")
    return 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    opened = _open(args)
    if opened is None:
        return 1
    root, settings, fs, conn = opened
    with closing(conn):
        when = args.as_of or datetime.now().replace(second=0, microsecond=0)
        rows, pages = _rebuild(conn, root, settings, fs, when)
    log.info("rebuild: %d calendar rows, %d pages written, as of %s", rows, pages, when)
    print(f"Rebuilt the capacity calendar ({rows} rows), wrote {pages} changed pages and rebuilt the search index, "
          f"as of {when:%Y-%m-%d %H:%M}.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    opened = _open(args)
    if opened is None:
        return 1
    _root, settings, _fs, conn = opened
    with closing(conn):
        today = (args.as_of or datetime.now()).date()
        first = monday_of(today)
        weeks = [first + timedelta(weeks=i) for i in range(REPORT_WEEKS)]
        text = build_report(conn, Model(conn), today, settings, weeks, monday_of(args.week) if args.week else first)
    _utf8_stdout()  # report > report.md is UTF-8
    print(text)
    return 0


def _utf8_stdout() -> None:
    """Saved to a file, output is UTF-8. A console that can't show "→" gets "?" rather than an error."""
    if hasattr(sys.stdout, "reconfigure"):
        if sys.stdout.isatty():
            sys.stdout.reconfigure(errors="replace")
        else:
            sys.stdout.reconfigure(encoding="utf-8")


def cmd_outlook_check(args: argparse.Namespace) -> int:
    opened = _open(args)
    if opened is None:
        return 1
    root, _settings, fs, conn = opened
    conn.close()
    now = datetime.now()
    trying = bool(getattr(args, "try_category", False))
    text = diagnose.build_report(root, now, drags=None, check_outlook=lambda: diagnose.outlook_check(try_category=trying))
    path = diagnose.save_report(fs, root, text, now)
    _utf8_stdout()
    print(text)
    print(f"Saved as {path.relative_to(root)} in the data root. Bring it, or the text above, to the personal computer.")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    opened = _open(args)
    if opened is None:
        return 1
    root, settings, _fs, conn = opened
    with closing(conn):
        try:
            result = backup.run_backup(root, settings, datetime.now())
        except backup.BackupError as e:
            print(e, file=sys.stderr)
            return 1
        backup.record(conn, result)
    print(result.message())
    for problem in result.problems:
        print(f"  {problem}")
    return 0


def cmd_make_shortcut(args: argparse.Namespace) -> int:
    from docrepo import startup

    try:
        path = startup.make_shortcut(SafeFS([app_dir()]))
    except (startup.StartupError, OSError) as e:
        print(f"The shortcut couldn't be made: {e}", file=sys.stderr)
        return 1
    print(f"Made {path}.")
    folder = startup.startup_folder()
    if folder is not None:
        print(f"To start DocRepo when you sign in, move it into your Startup folder: {folder}")
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    return cmd_app(args, browse=True)


def cmd_app(args: argparse.Namespace, browse: bool = False) -> int:
    root = _data_root(args)
    if root is None:
        return 1
    if not (root / SETTINGS_FILE).exists():
        print(f"{root} isn't set up yet. Run: python -m docrepo init", file=sys.stderr)
        return 1
    settings = Settings.load(root)
    fs = make_safe_fs(root, settings)
    setup_logging(fs, root)
    from docrepo.app import run  # PySide6 loads only for the app

    return run(root, settings, fs, browse)


def cmd_set_hotkey(args: argparse.Namespace) -> int:
    root = _data_root(args)
    if root is None:
        return 1
    try:
        hotkey.parse_hotkey(args.keys)
    except ValueError as e:
        print(f"Can't use {args.keys}: {e}", file=sys.stderr)
        return 1
    settings = Settings.load(root)
    fs = make_safe_fs(root, settings)
    settings.hotkey = args.keys.strip()
    settings.save(fs, root)
    print(f"The hotkey is now {settings.hotkey}. Quit DocRepo from its tray icon and start it again to use it.")
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "app": cmd_app,
    "browse": cmd_browse,
    "backup": cmd_backup,
    "make-shortcut": cmd_make_shortcut,
    "set-hotkey": cmd_set_hotkey,
    "where": cmd_where,
    "set-data-root": cmd_set_data_root,
    "init": cmd_init,
    "try-write": cmd_try_write,
    "load-sample": cmd_load_sample,
    "rebuild": cmd_rebuild,
    "report": cmd_report,
    "outlook-check": cmd_outlook_check,
    "troubleshoot": cmd_outlook_check,
}
