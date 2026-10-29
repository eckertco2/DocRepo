"""Pins and uses (release 5.35, decisions 159 and 160) and what Open may do (decision 158)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from docrepo import opener, pins
from docrepo.overview import Record


# ---- pins and uses ----
def test_pins_keep_their_order_and_move(sample_conn):
    conn = sample_conn
    assert pins.set_pinned(conn, "T000001", "D000001", True)
    assert pins.set_pinned(conn, "T000001", "D000002", True)
    assert not pins.set_pinned(conn, "T000001", "D000002", True)  # already pinned
    assert pins.pins_of(conn, "T000001") == ["D000001", "D000002"]
    assert pins.move_pin(conn, "T000001", "D000002", -1)
    assert pins.pins_of(conn, "T000001") == ["D000002", "D000001"]
    assert not pins.move_pin(conn, "T000001", "D000002", -1)  # first already
    assert pins.set_pinned(conn, "T000001", "D000002", False)
    assert pins.pins_of(conn, "T000001") == ["D000001"]
    assert pins.pins_of(conn, "T000008") == []  # pins are per task
    assert conn.execute("SELECT count(*) FROM status_log WHERE field LIKE '%pin%'").fetchone()[0] == 0  # not in the status log


def test_uses_are_kept_newest_first(sample_conn):
    conn = sample_conn
    pins.record_use(conn, "D000001", "T000001", "open", datetime(2026, 10, 7, 9, 0))
    pins.record_use(conn, "D000002", None, "show", datetime(2026, 10, 8, 9, 0))
    pins.record_use(conn, "D000001", "T000001", "copy_path", datetime(2026, 10, 8, 10, 0))
    assert pins.uses_of(conn, ["D000001", "D000002"]) == [("D000001", "2026-10-08 10:00:00", "copy_path"), ("D000002", "2026-10-08 09:00:00", "show"),
                                                           ("D000001", "2026-10-07 09:00:00", "open")]
    assert pins.last_uses(conn) == {"D000001": "2026-10-08 10:00:00", "D000002": "2026-10-08 09:00:00"}
    with pytest.raises(ValueError):
        pins.record_use(conn, "D000001", None, "delete", datetime(2026, 10, 8))


def test_the_model_and_task_md_carry_the_pins(sample_conn):
    from docrepo.model import Model

    pins.set_pinned(sample_conn, "T000008", "D000002", True)
    assert Model(sample_conn).pins == {"T000008": ["D000002"]}


# ---- what Open may do ----
def record(**fields) -> Record:
    base = {"kind": "file", "id": "D000009", "task": "T000001", "at": "2026-10-01 09:00:00", "title": "x"}
    return Record(**{**base, **fields})


def test_open_plans_by_what_a_file_is():
    assert opener.plan(record(type="doc", source="Tracked original", path="\\\\server\\eng\\Scope.docx")) == opener.Plan("open", "\\\\server\\eng\\Scope.docx")
    attachment = opener.plan(record(type="pdf", source="Email attachment", path="C:\\data\\Captures\\x\\attachments\\Curve.pdf"))
    assert attachment.action == "show" and "not opened" in attachment.reason
    saved = opener.plan(record(type="pdf", source="Email attachment", path="C:\\a\\Curve.pdf", copy="C:\\data\\Tasks\\T1\\Files\\Curve.pdf"))
    assert saved == opener.Plan("open", "C:\\data\\Tasks\\T1\\Files\\Curve.pdf")  # saved to the repo, so it opens
    link = opener.plan(record(type="link", source="Link", path="https://example.sharepoint.com/sites/x"))
    assert link.action == "copy_link"
    macro = opener.plan(record(type="sheet", source="Tracked original", path="\\\\server\\eng\\Tool.xlsm"))
    assert macro.action == "show" and ".xlsm" in macro.reason
    program = opener.plan(record(type="other", source="Tracked original", path="\\\\server\\eng\\setup.exe"))
    assert program.action == "show"
    email = record(kind="email", type="mail", capture="C000003")
    assert opener.plan(email, lambda r: "C:\\data\\Captures\\C000003\\email.msg") == opener.Plan("open", "C:\\data\\Captures\\C000003\\email.msg")
    assert opener.plan(email).action == "capture"


@pytest.mark.parametrize("name", ["a.docm", "b.xlsm", "c.pptm", "d.exe", "e.bat", "f.cmd", "g.ps1", "h.js", "i.vbs", "j.lnk", "k.msi", "l.hta", "m.url"])
def test_never_opens_programs_scripts_shortcuts_or_macros(name):
    started = []
    assert not opener.openable(name)
    assert opener.start(name, started.append, lambda p: True) and started == []


def test_start_says_what_went_wrong():
    started = []
    assert opener.start("\\\\server\\eng\\Scope.docx", started.append, lambda p: True) is None and started == ["\\\\server\\eng\\Scope.docx"]
    assert opener.start("\\\\server\\eng\\Scope.docx", started.append, lambda p: False) == "Scope.docx isn't at \\\\server\\eng any more."

    def refuse(_path: str) -> None:
        raise PermissionError

    assert opener.start("C:\\x\\Scope.docx", refuse, lambda p: True) == "Scope.docx couldn't be opened (PermissionError)."


def test_copy_path_quotes_paths_with_spaces():
    assert opener.copy_text(["C:\\a\\b.pdf", "\\\\server\\eng\\Line 2\\c.pdf"]) == 'C:\\a\\b.pdf\n"\\\\server\\eng\\Line 2\\c.pdf"'
    assert Path  # noqa: B018
