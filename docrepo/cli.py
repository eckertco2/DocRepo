"""DocRepo's command line: ``python -m docrepo [--data-root PATH] COMMAND``."""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from docrepo import __version__
from docrepo.config import (
    SETTINGS_FILE,
    Settings,
    SettingsError,
    data_root_problem,
    init_data_root,
    location_file,
    make_safe_fs,
    resolve_data_root,
    save_location,
)
from docrepo.log_setup import setup_logging
from docrepo.safe_fs import WriteRefused

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docrepo", description="Capture and organize work notes, tasks and documents.")
    parser.add_argument("--version", action="version", version=f"DocRepo {__version__}")
    parser.add_argument("--data-root", metavar="PATH", help="use this data root instead of the recorded one (for development and testing)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.add_parser("where", help="show which data root DocRepo uses, and why")
    set_root = commands.add_parser("set-data-root", help="record where your data root is")
    set_root.add_argument("path")
    commands.add_parser("init", help="create the data root's folders and default settings")
    try_write = commands.add_parser("try-write", help="check whether DocRepo may write a test file at PATH")
    try_write.add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (WriteRefused, SettingsError) as e:
        print(e, file=sys.stderr)
        return 1


def _data_root(args: argparse.Namespace) -> Path | None:
    choice = resolve_data_root(args.data_root)
    if choice.path is None:
        print("No data root is set yet. Set one with: python -m docrepo set-data-root PATH", file=sys.stderr)
    return choice.path


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
    setup_logging(make_safe_fs(root, Settings.load(root)), root)
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


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "where": cmd_where,
    "set-data-root": cmd_set_data_root,
    "init": cmd_init,
    "try-write": cmd_try_write,
}
