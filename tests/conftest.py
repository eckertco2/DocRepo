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
