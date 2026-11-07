"""An email's description (release 5.74, round 7's item 93, decisions 331 and 332): a box on the email's own row, with the
cursor in it after a drop, attachments or not; kept per email in capture_emails (schema version 21), and shown in the Task
view, the capture's page, capture.md, search and the notes page's caption. Made-up emails over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, captures, db, overview, prompts, search  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import Pages  # noqa: E402
from docrepo.model import CaptureEmail, Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import CaptureDraft, EmailItem, email_rows, save_capture  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)
INSTALLATION = "T000008"
ABOUT = "Crane for the Tuesday lift"


def crane(**kw) -> EmailItem:
    values = {"subject": "Crane booking", "sender": "Ann Example", "sent": "2026-10-08 09:30", "to": "Me",
              "body": "The crane is booked for Tuesday.", "msg_bytes": b"MSG, made up"}
    return EmailItem(**{**values, **kw})


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), Settings(me="P001"))
    yield conn, data_root, fs
    conn.close()


def saved(env, *emails: tuple[EmailItem, str]) -> str:
    """Save a capture on Installation holding these emails, each with what's typed on its row."""
    conn, root, fs = env
    files = []
    for email, about in emails:
        rows = email_rows(email)
        rows[0].description = about
        files += rows
    r = save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(task=INSTALLATION, files=files), AT)
    assert r.problems == []
    return r.capture_id


# ---- kept with the email ----
def test_a_description_is_kept_with_its_email(env):
    conn, root, fs = env
    cid = saved(env, (crane(), f"  {ABOUT}  "), (crane(subject="Re: crane booking", msg_bytes=None), ""))
    c = Model(conn).captures[cid]
    assert c.emails == [CaptureEmail(0, "email.msg", "Crane booking", "Ann Example", "2026-10-08 09:30", ABOUT),
                        CaptureEmail(1, None, "Re: crane booking", "Ann Example", "2026-10-08 09:30", None)]  # nothing to save, no file
    front = captures.capture_md_path(root, c).read_text(encoding="utf-8").split("---")[1]
    line = next(x for x in front.splitlines() if x.startswith("emails: "))
    assert json.loads(line.removeprefix("emails: ")) == [
        {"file": "email.msg", "subject": "Crane booking", "sender": "Ann Example", "sent": "2026-10-08 09:30", "description": ABOUT},
        {"file": None, "subject": "Re: crane booking", "sender": "Ann Example", "sent": "2026-10-08 09:30", "description": None}]


def test_emails_captured_before_have_none(env):
    conn, root, fs = env
    m = Model(conn)
    assert m.captures["C000003"].source == "outlook_email" and m.captures["C000003"].emails == []
    assert '"emails"' not in captures.capture_md(m, "C000003", "") and "\nemails:" not in captures.capture_md(m, "C000003", "")
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 21  # 21 brought capture_emails; 22 (release 5.79) the tagged labels


# ---- where it shows ----
def test_where_it_shows(env):
    conn, root, fs = env
    cid = saved(env, (crane(), ABOUT))
    m = Model(conn)
    c = m.captures[cid]
    text = captures.read_content(root, c) or ""
    record = next(r for r in overview.build(m, root, INSTALLATION, {cid: text}) if r.id == cid)
    assert record.desc == f"From Ann Example · {ABOUT}"  # the Task view's email row
    assert ABOUT in search.capture_body(m, root, cid)
    assert ABOUT in Pages(m, AT.date(), lambda x: text, "P001", conn).capture_page(cid, text)
    assert f"Email from Ann Example: Crane booking – {ABOUT}" in m.pages[INSTALLATION]  # the notes page's caption


def test_no_description_shows_as_before(env):
    conn, root, fs = env
    cid = saved(env, (crane(), ""))
    m = Model(conn)
    text = captures.read_content(root, m.captures[cid]) or ""
    record = next(r for r in overview.build(m, root, INSTALLATION, {cid: text}) if r.id == cid)
    assert record.desc == "From Ann Example"
    assert "Email from Ann Example: Crane booking –" not in m.pages[INSTALLATION]


# ---- the capture window ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, env):
    conn, root, fs = env
    prompts.write_defaults(fs, root)
    w = CaptureWindow(AppContext(conn, root, fs, Settings(me="P001"), notify=lambda t, m: None, now=lambda: AT))
    w.resize(900, 700)
    w.show_capture(task=INSTALLATION)
    yield w
    QApplication.processEvents()
    w._items_timer.stop()
    w.hide()
    w.deleteLater()


def test_an_email_with_no_attachment_gets_the_cursor(window):
    """The owner's "usually": with no attachment there was no box, so the cursor went to the content text."""
    window._add_email(crane())
    (entry,) = window.files
    assert entry.desc is None and entry.email_desc is not None
    assert window.focusWidget() is entry.email_desc
    assert "What's this email about?" in entry.email_desc.placeholderText()
    entry.email_desc.setText(ABOUT)
    assert window._file_rows()[0].description == ABOUT


def test_two_emails_at_once_the_first_gets_the_cursor(window):
    window._read_emails(lambda: [crane(), crane(subject="Re: crane booking")], "a test")
    boxes = [e.email_desc for e in window.files if e.row.email]
    assert len(boxes) == 2 and window.focusWidget() is boxes[0]


def test_a_drop_brings_the_window_forward_and_the_button_doesnt_need_to(window, tmp_path, monkeypatch):
    came = []
    monkeypatch.setattr(window, "_come_forward", lambda: came.append(True))
    f = tmp_path / "Lift plan.txt"
    f.write_text("made up", encoding="utf-8")
    window.dropped("files", [str(f)])
    window.dropped("links", ["https://example.com/crane"])
    assert came == [True, True]
    window._read_emails(lambda: [crane()], "a test")  # the Outlook button: the window is already in front
    assert came == [True, True]
