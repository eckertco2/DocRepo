"""The troubleshooting report (mods log round 1): it tells what failed without carrying captured content."""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

from docrepo import diagnose, outlook
from docrepo.cli import main
from docrepo.diagnose import DragNote, Step
from docrepo.log_setup import setup_logging

NOW = datetime(2026, 10, 19, 15, 40)


@pytest.fixture(autouse=True)
def fresh():
    outlook.PROBLEMS.clear()
    diagnose.UNCAUGHT.clear()
    yield
    outlook.PROBLEMS.clear()
    diagnose.UNCAUGHT.clear()


def fake_check():
    return [Step("Find Outlook (GetActiveObject)", True, "ok"),
            Step("Read the email's Body", False, "com_error: 0x80004004 (operation aborted)")], "16.0.1"


def test_the_report_names_steps_drags_and_problems(data_root):
    outlook.PROBLEMS.append(outlook.Problem("2026-10-19 15:30:00", "reading the email's To", "com_error: 0x80004004"))
    drags = [DragNote("2026-10-19 15:31:00", "drop", ('application/x-qt-windows-mime;value="RenPrivateMessages"', "text/plain"), 0, 0, "outlook")]
    text = diagnose.build_report(data_root, NOW, drags, check_outlook=fake_check)
    assert text.startswith("# DocRepo troubleshooting report\n\nMade 2026-10-19 15:40.")
    assert "| Find Outlook (GetActiveObject) | ok: ok |" in text
    assert "| Read the email's Body | FAILED: com_error: 0x80004004 (operation aborted) |" in text
    assert "| 2026-10-19 15:31:00 | drop | outlook | 0 (0) | RenPrivateMessages (Windows), text/plain |" in text
    assert "- 2026-10-19 15:30:00 · reading the email's To: com_error: 0x80004004" in text


def test_the_report_says_when_there_were_no_drags(data_root):
    assert "None yet since DocRepo started." in diagnose.build_report(data_root, NOW, [], check_outlook=fake_check)
    assert "Not available from the command line." in diagnose.build_report(data_root, NOW, None, check_outlook=fake_check)


def test_the_report_carries_log_warnings_but_not_paths_or_addresses(data_root, fs):
    import logging

    setup_logging(fs, data_root)
    logging.getLogger("docrepo.test").info("an everyday line")
    logging.getLogger("docrepo.test").warning("couldn't copy %s for tom@example.com", data_root / "Tasks" / "T000001" / "a.txt")
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("docrepo.test").exception("save failed")
    for h in logging.getLogger().handlers:
        h.flush()
    text = diagnose.build_report(data_root, datetime.now(), [], check_outlook=fake_check)
    assert "an everyday line" not in text
    assert "couldn't copy <data root>" in text and "<email address>" in text and "example.com" not in text
    assert "ERROR" in text and "ValueError: boom" in text
    assert str(data_root) not in text and os.path.expanduser("~") not in text


def test_scrub_shortens_servers_and_the_users_folder():
    home = os.path.expanduser("~")
    text = diagnose.scrub(f"{home}\\Documents\\a.txt and \\\\fileserver01\\projects\\b.pdf", None)
    assert text == "%USERPROFILE%\\Documents\\a.txt and \\\\<server>\\<share>\\b.pdf"


def test_save_report_never_overwrites(data_root, fs):
    first = diagnose.save_report(fs, data_root, "one", NOW)
    second = diagnose.save_report(fs, data_root, "two", NOW)
    assert (first.name, second.name) == ("troubleshooting 2026-10-19 1540.md", "troubleshooting 2026-10-19 1540 (2).md")
    assert first.read_text(encoding="utf-8") == "one" and first.parent == data_root / "System" / "diagnostics"


def test_uncaught_errors_are_logged_kept_and_told_once(monkeypatch):
    told = []
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # put back after the test
    diagnose.install_excepthook(lambda title, text: told.append(title))
    for _ in range(2):
        try:
            raise TypeError("nope")
        except TypeError:
            sys.excepthook(*sys.exc_info())
    assert len(diagnose.UNCAUGHT) == 2 and diagnose.UNCAUGHT[0][1].startswith("TypeError in test_diagnose.py, line")
    assert told == ["DocRepo hit a problem"]


def test_outlook_check_on_the_command_line(tmp_path, capsys, monkeypatch):
    root = tmp_path / "Data"
    assert main(["--data-root", str(root), "init"]) == 0
    monkeypatch.setattr(diagnose, "outlook_check", fake_check)
    assert main(["--data-root", str(root), "troubleshoot"]) == 0
    out = capsys.readouterr().out
    assert "## Outlook check" in out and "Saved as System\\diagnostics\\troubleshooting " in out
    assert len(list((root / "System" / "diagnostics").glob("troubleshooting *.md"))) == 1


def test_the_real_check_runs_without_outlook():
    """On this computer there's no classic Outlook: the check says so, step by step, and never starts it."""
    steps, version = diagnose.outlook_check()
    assert steps[0].name == "Load pywin32" and steps[0].ok
    if not outlook.outlook_window_open():
        assert version == "" and not any(s.name == "Join Outlook (Dispatch)" for s in steps)
