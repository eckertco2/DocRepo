"""The Startup shortcut: made in DocRepo's own folder, for the owner to move into their Startup folder."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from docrepo import startup
from docrepo.cli import main
from docrepo.config import CODE_DIR, app_dir
from docrepo.safe_fs import SafeFS, WriteRefused

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows shortcuts")


def test_the_shortcut_runs_this_copy_of_docrepo_without_a_console():
    path = startup.make_shortcut(SafeFS([app_dir()]))
    assert path == app_dir() / "DocRepo.lnk" and path.exists()
    link = startup.read_shortcut(path)
    assert Path(link.target).name.lower() == "pythonw.exe" and link.arguments == "-m docrepo app"
    assert os.path.normcase(link.folder) == os.path.normcase(str(CODE_DIR))
    again = startup.make_shortcut(SafeFS([app_dir()]))  # making it again replaces DocRepo's own shortcut
    assert again == path


def test_it_is_made_only_where_docrepo_may_write(tmp_path):
    with pytest.raises(WriteRefused):
        startup.make_shortcut(SafeFS([tmp_path / "elsewhere"]))


def test_status_reads_the_startup_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(startup, "startup_folder", lambda: tmp_path)
    assert startup.status() == "DocRepo doesn't start when you sign in yet."
    made = startup.make_shortcut(SafeFS([app_dir()]))
    (tmp_path / "DocRepo.lnk").write_bytes(made.read_bytes())  # the owner drags it across
    assert startup.status() == "DocRepo starts when you sign in."
    monkeypatch.setattr(startup, "wanted", lambda: startup.Shortcut(r"C:\Other\pythonw.exe", "-m docrepo app", r"C:\Other"))
    assert "from another folder" in startup.status()
    monkeypatch.setattr(startup, "startup_folder", lambda: None)
    assert "no Startup folder" in startup.status()


def test_the_make_shortcut_command(capsys):
    assert main(["make-shortcut"]) == 0
    out = capsys.readouterr().out
    assert "DocRepo.lnk" in out and "Startup folder" in out
