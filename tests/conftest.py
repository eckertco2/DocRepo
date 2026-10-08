"""Shared test fixtures. Every test runs away from the real %LOCALAPPDATA%, data root and OneDrive."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from docrepo.safe_fs import SafeFS


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
