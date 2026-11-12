"""Shared test fixtures. Every test runs away from the real %LOCALAPPDATA%, data root and OneDrive.

``tests/fixtures`` holds the browse tool mockup's ``examples.md`` and ``test-vectors.md``:
the expected results for the made-up sample data in ``docrepo/sample``.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from docrepo import db
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TESTS = Path(__file__).resolve().parent
#: Each run's temporary folders go in a folder of its own here (release 5.88), so two runs at once don't clear each other's.
TEMP_ROOT = TESTS.parent / ".pytest_tmp"
#: The imports that mark a test module as one that uses Qt.
GUI_IMPORTS = ("docrepo.ui", "PySide6")


def is_gui_module(path: Path) -> bool:
    """True when a test module uses Qt: it imports docrepo.ui or PySide6 (anywhere in it, read from its syntax tree, so
    a sample in a string doesn't count), or sets QT_QPA_PLATFORM."""
    import ast

    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return False
    if "QT_QPA_PLATFORM" in text:
        return True
    for node in ast.walk(tree):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names] if isinstance(node, ast.ImportFrom)
                 else [])
        if any(n == g or n.startswith(g + ".") for n in names for g in GUI_IMPORTS):
            return True
    return False


def _without_gui(config: pytest.Config) -> bool:
    """True when the run asks for no Qt tests (``-m "not gui"``), so their modules needn't even be imported."""
    return " ".join((config.option.markexpr or "").split()) == "not gui"


def pytest_configure(config: pytest.Config) -> None:
    """A temporary folder per run, ``.pytest_tmp\\run-<process id>``, unless ``--basetemp`` names one. Runs' folders
    older than a day are cleared, as pytest's own numbered folders are."""
    if config.option.basetemp:
        return
    import os
    import shutil
    import time

    TEMP_ROOT.mkdir(exist_ok=True)
    for old in TEMP_ROOT.glob("run-*"):
        try:
            if time.time() - old.stat().st_mtime > 86400:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    config.option.basetemp = str(TEMP_ROOT / f"run-{os.getpid()}")


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """With ``-m "not gui"``, a module that uses Qt isn't collected, so Qt is never imported and the run is quick."""
    if collection_path.suffix == ".py" and collection_path.name.startswith("test_") and _without_gui(config):
        return True if is_gui_module(collection_path) else None
    return None


def asks_for_scale(markexpr: str, args: list[str]) -> bool:
    """True when a run asks for the scale tests (release 5.126, decision 471): its ``-m`` names ``scale``, or it names
    ``test_scale.py``. They take minutes, so the default and the fast runs leave them out."""
    return bool(re.search(r"\bscale\b", markexpr or "")) or any("test_scale" in str(a) for a in args)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark each test in a module that uses Qt as ``gui``, and leave out the ``scale`` tests unless the run asks for them."""
    seen: dict[Path, bool] = {}
    for item in items:
        path = Path(str(item.fspath))
        if path not in seen:
            seen[path] = is_gui_module(path)
        if seen[path]:
            item.add_marker(pytest.mark.gui)
    if not asks_for_scale(config.option.markexpr, config.args):
        dropped = [item for item in items if item.get_closest_marker("scale")]
        if dropped:
            config.hook.pytest_deselected(items=dropped)
            items[:] = [item for item in items if not item.get_closest_marker("scale")]


def example_block(name: str) -> str:
    """One file's text from examples.md, such as "Tasks/T000008/Task.md", as DocRepo writes it (ending in a newline)."""
    text = (FIXTURES / "examples.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(name)}\n\n[^\n]*\n\n```\w+\n(.*?)\n```", text, re.S | re.M)
    assert m, f"no example called {name}"
    return m.group(1) + "\n"


def vector_lines(first_heading: str, end_heading: str) -> list[str]:
    """The headings, table rows and bullet lines of test-vectors.md from one heading up to another."""
    text = (FIXTURES / "test-vectors.md").read_text(encoding="utf-8")
    part = text[text.index(f"## {first_heading}"):text.index(f"## {end_heading}")]
    return table_lines(part)


def table_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith(("|", "- ", "## "))]


@pytest.fixture
def sample_conn() -> Iterator[sqlite3.Connection]:
    """An in-memory docs.db holding the sample data."""
    conn = db.connect_memory()
    load_sample(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    for name in ("DOCREPO_DATA_ROOT", "OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def close_log_file():
    """Detach DocRepo's log file after each test, so it doesn't stay open."""
    yield
    root = logging.getLogger()
    for handler in [h for h in root.handlers if h.get_name() == "docrepo-file"]:
        root.removeHandler(handler)
        handler.close()


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "DocRepoData"
    root.mkdir()
    return root


@pytest.fixture
def fs(data_root: Path) -> SafeFS:
    return SafeFS([data_root])


@pytest.fixture
def sample_root(data_root: Path, fs: SafeFS) -> Iterator[tuple[sqlite3.Connection, Path, SafeFS]]:
    """A data root holding the sample data with its files (capture.md, extracted.txt), its calendar and its search index."""
    from datetime import date

    from docrepo import capacity, prompts, search
    from docrepo.config import Settings
    from docrepo.sample import write_sample_files

    conn = db.connect(fs, data_root)
    load_sample(conn)
    write_sample_files(conn, data_root, fs)
    capacity.rebuild_all(conn, date(2026, 10, 8), Settings(me="P001"))
    prompts.write_defaults(fs, data_root)
    search.rebuild(conn, data_root)
    yield conn, data_root, fs
    conn.close()
