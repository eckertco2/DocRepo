"""Formatted captures (mods log round 2, M0045, release 5.7): saved as markup, read everywhere else as their words."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import capacity, captures, db, edits, search
from docrepo.config import Settings
from docrepo.detail import Pages, PageState
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, EmailItem, FileRow, save_capture

AT = datetime(2026, 10, 16, 9, 30)
SETTINGS = Settings(me="P001")
NOTES = ("Coupling guard walkdown\n- **guard** fitted, <mark class=\"green\">signed off</mark>\n  - bolts at *62 Nm*\n"
         "- rails painted\n1. Book the alignment\n\\- dash, not a list")


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def save(env, draft: CaptureDraft):
    conn, root, fs = env
    return save_capture(conn, root, fs, SETTINGS, draft, AT)


def pages(conn, root) -> Pages:
    model = Model(conn)
    return Pages(model, AT.date(), lambda cid: captures.read_content(root, model.captures[cid]) or "", "P001", conn)


def test_a_formatted_note_keeps_its_markup(env):
    conn, root, _ = env
    r = save(env, CaptureDraft(content=NOTES, formatted=True, task="T000008", types={"note"}))
    c = Model(conn).captures[r.capture_id]
    assert c.formatted and c.title == "Coupling guard walkdown"
    text = captures.capture_md_path(root, c).read_text(encoding="utf-8")
    assert 'content_format: "markdown"\n' in text and text.endswith(f"---\n\n{NOTES}\n")
    assert captures.read_content(root, c) == NOTES
    assert captures.plain(c, NOTES).startswith("Coupling guard walkdown\n- guard fitted, signed off\n  - bolts at 62 Nm\n")
    # Search reads its words, not its marks.
    assert any(x.id == r.capture_id for x in search.search(conn, Model(conn), "guard fitted signed"))
    assert not any(x.id == r.capture_id for x in search.search(conn, Model(conn), "mark class"))
    # Its notes page holds it with its formatting and lists, line for line (release 5.25); the Captures tab lists it.
    from docrepo import notes_page

    body = notes_page.get(conn, "T000008").split("\n")
    assert all(line in body for line in NOTES.split("\n") if line.strip())
    assert f"goto:T000008:{r.capture_id}" in pages(conn, root).task_page("T000008", PageState())
    page = pages(conn, root).capture_page(r.capture_id, NOTES)
    assert "<ul" in page and "<ol" in page and "<b>guard</b>" in page


def test_plain_text_stays_plain(env):
    conn, root, _ = env
    r = save(env, CaptureDraft(content="Rate *2* and 3*4.", task="T000008", types={"note"}))
    c = Model(conn).captures[r.capture_id]
    text = captures.capture_md_path(root, c).read_text(encoding="utf-8")
    assert not c.formatted and "content_format" not in text and text.endswith("\n\nRate *2* and 3*4.\n")


def test_a_new_task_from_formatted_text_takes_its_words(env):
    conn, root, _ = env
    r = save(env, CaptureDraft(content="**Replace** the seal kit by Friday\n- two spares", formatted=True, task="T000008", types={"new_task"}))
    t = Model(conn).task(r.created_task)
    # Parse and populate reads the words: "by Friday" is its due date, not part of its title. Its description is the first
    # line, and the whole text, formatted, is on its notes page (release 5.25, decision 115).
    assert t.title == "Replace the seal kit" and t.description == "Replace the seal kit by Friday"
    from docrepo import notes_page

    assert notes_page.get(conn, t.id).endswith("\n**Replace** the seal kit by Friday\n- two spares")


def test_an_email_in_a_formatted_capture_reads_as_itself(env):
    conn, root, _ = env
    email = EmailItem("Seal kit *urgent*", "Dana <dana@example.com>", "2026-10-15 08:00", "", "Body with ~~tildes~~ and - dashes\n- a list?")
    r = save(env, CaptureDraft(content="**Forwarding** this", formatted=True, files=[FileRow("Seal kit", email=email)], task="T000008",
                               types={"note"}))
    c = Model(conn).captures[r.capture_id]
    kept = captures.read_content(root, c)
    assert captures.plain(c, kept) == "Forwarding this\n\n" + email.text()  # the email's text comes back exactly
    assert c.title == "Seal kit *urgent*"
