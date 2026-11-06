"""The capture window's task picker filled from an email's conversation (the knowledge base's stage K8, release 5.101,
KB decisions 32 and 33): "from conversation", a hand pick and one # task winning over it, emails of different tasks
filling nothing, an email taken off emptying it again, a draft keeping it, and the pinned window saying where it came
from. Every email here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, msg, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import CaptureDraft, email_rows, save_capture  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from msg_builder import FakeEmail, build  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
INSTALLATION, RIGGING, REACTOR = "T000008", "T000012", "T000001"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")
OTHER = bytes.fromhex("11111111222222223333333344444444")


def index(guid: bytes = GUID, replies: int = 0) -> bytes:
    return b"\x01" + bytes.fromhex("D9A1B2C3D4") + guid + b"".join(bytes([0x80, 0, 0, 0, n]) for n in range(1, replies + 1))


def email(subject: str = "Re: crane booking", guid: bytes = GUID, replies: int = 1, message_id: str = "<r1@example.com>"):
    return msg.read(build(FakeEmail(subject=subject, conversation_index=index(guid, replies), message_id=message_id)))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    prompts.write_defaults(fs, data_root)
    messages: list[tuple[str, str]] = []
    ctx = AppContext(conn, data_root, fs, SETTINGS, notify=lambda t, m: messages.append((t, m)), now=lambda: AT)
    # The conversation's first email, filed to Rigging plan earlier.
    first = msg.read(build(FakeEmail(conversation_index=index(), message_id="<a1@example.com>")))
    r = save_capture(conn, data_root, fs, SETTINGS, CaptureDraft(content="", task=RIGGING, files=email_rows(first)[:1]), datetime(2026, 10, 7, 9, 30))
    assert r.capture_id
    w = CaptureWindow(ctx)
    w.messages = messages  # type: ignore[attr-defined]
    w.filed_from = r.capture_id  # type: ignore[attr-defined]
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    if w.pin_window is not None:
        w.pin_window.hide()
        w.pin_window.deleteLater()
    w.deleteLater()
    conn.close()


def own_entry(window, e):
    return next(f for f in window.files if f.row.email is e)


def test_a_reply_fills_the_picker_from_its_conversation(window):
    window._add_email(email())
    assert window.task == RIGGING and window.task_conv and not window.task_auto
    assert window.task_button.text().endswith("Rigging plan  (from conversation)")
    assert f"filed to Rigging plan on 2026-10-07 ({window.filed_from})" in window.task_button.toolTip()
    window.save()
    saved = Model(window.ctx.conn)
    newest = max(saved.captures.values(), key=lambda c: c.id)
    assert newest.task == RIGGING and newest.emails[0].message_id == "<r1@example.com>"


def test_taking_the_email_off_empties_the_picker(window):
    e = email()
    window._add_email(e)
    assert window.task == RIGGING
    window._remove_file(own_entry(window, e))
    assert window.task is None and not window.task_conv and window.task_button.text() == "None: keep it unfiled"


def test_a_hand_pick_wins_and_stays(window):
    window.set_task(REACTOR)
    window._add_email(email())
    assert window.task == REACTOR and not window.task_conv


def test_one_hash_task_wins_over_the_conversation_and_gives_it_back(window):
    window._add_email(email())
    assert window.task == RIGGING and window.task_conv
    window.content.setPlainText("#Installation\nCrane booked for Tuesday.")
    window.read_items()
    assert window.task == INSTALLATION and window.task_auto and not window.task_conv
    window.content.setPlainText("Crane booked for Tuesday.")  # the # gone: the conversation's task again
    window.read_items()
    assert window.task == RIGGING and window.task_conv


def test_emails_of_conversations_on_different_tasks_fill_nothing(window):
    other = msg.read(build(FakeEmail(subject="Reactor inspection", conversation_index=index(OTHER), message_id="<x1@example.com>")))
    conn, root, fs = window.ctx.conn, window.ctx.data_root, window.ctx.fs
    save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="", task=REACTOR, files=email_rows(other)[:1]), datetime(2026, 10, 7, 10, 0))
    window._add_email(email())
    window._add_email(email("Re: reactor inspection", OTHER, message_id="<x2@example.com>"))
    assert window.task is None and not window.task_conv
    assert window.task_button.text().startswith("None: these emails belong to ") and "pick the task" in window.task_button.text()


def test_an_email_of_a_new_conversation_leaves_the_picker_alone(window):
    window._add_email(email("New subject", OTHER, replies=0, message_id="<n1@example.com>"))
    assert window.task is None and not window.task_conv


def test_a_draft_keeps_the_conversations_task(window):
    window._add_email(email())
    data = window._draft_data()
    assert data["task_conv"] is True and data["task"] == RIGGING


def test_the_pinned_window_says_where_the_task_came_from(window):
    window.pin()
    window._add_email(email())
    window.pin_window.sync()
    assert window.pin_window.task_button.text() == "Rigging plan"
    assert "filed to Rigging plan" in window.pin_window.task_button.toolTip()
