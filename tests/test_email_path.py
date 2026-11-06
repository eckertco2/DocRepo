"""The email path (release 5.93, the review of 2026-11-06, F14): an email's place in Outlook matched safely, kept, and
marked when its capture is filed later; an email captured before said on its drop; and a cap on what a drag hands over.
Outlook is a fake here, as on every test of this computer; the corporate computer checks it by hand."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, captures, db, msg, outlook, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import CaptureDraft, EmailItem, FileRow, email_rows, save_capture  # noqa: E402
from docrepo.ui import drop_target  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.drop_target import DropRead, Dropped  # noqa: E402
from msg_builder import FakeEmail, build  # noqa: E402

AT = datetime(2026, 10, 8, 9, 0)
RIGGING = "T000012"


class FakeItem:
    def __init__(self) -> None:
        self.Categories, self.saved = "", 0

    def Save(self):  # noqa: N802 - Outlook's name
        self.saved += 1


class FakeSession:
    def __init__(self, items: dict) -> None:
        self.items, self.asked = items, []

    def GetItemFromID(self, entry_id, store_id=None):  # noqa: N802 - Outlook's name
        self.asked.append((entry_id, store_id))
        return self.items[entry_id]


class FakeApp:
    def __init__(self, session) -> None:
        self.Session = session


# ---- matching a dragged email to Outlook's selection ----
def test_a_reply_chain_matches_by_sent_time_never_by_subject_alone():
    first = EmailItem("Re: crane", "Ann", "2026-10-07 09:15", "", "")
    second = EmailItem("Re: crane", "Ann", "2026-10-07 11:40", "", "")
    places = [("E1", "S", "Re: crane", "2026-10-07 11:40"), ("E2", "S", "Re: crane", "2026-10-07 09:15")]
    assert outlook.match_places([first, second], places) == 2
    assert (first.entry_id, second.entry_id) == ("E2", "E1")
    lost = EmailItem("Re: crane", "Ann", "2026-10-06 08:00", "", "")  # neither selected one was sent then: no guess
    assert outlook.match_places([lost], places) == 0 and lost.entry_id == "" and "couldn't tell which" in lost.place_note


def test_a_subject_alone_matches_when_only_one_has_it():
    e = EmailItem("Sling drawing", "", "", "", "")
    assert outlook.match_places([e], [("E7", "S", "Sling drawing", "2026-10-07 10:00"), ("E8", "S", "Other", "")]) == 1 and e.entry_id == "E7"


def test_the_place_a_msg_carries_wins():
    e = msg.read(build(FakeEmail(entry_id=bytes.fromhex("00000000ABCD"))))
    assert e.entry_id == "00000000ABCD"
    assert outlook.match_places([e], [("E1", "S", "Crane booking", "")]) == 1 and e.entry_id == "00000000ABCD"


def test_an_unmatched_reply_is_said_when_marking():
    e = EmailItem("Re: crane", "", "", "", "", place_note="2 emails selected in Outlook have its subject, so DocRepo couldn't tell which it was, and didn't guess")
    count, problems = outlook.mark_filed([(e, RIGGING)], Model(sample()))
    assert count == 0 and problems == [f"An email (Re: crane) couldn't be marked in Outlook: {e.place_note}."]


def sample():
    conn = db.connect_memory()
    load_sample(conn)
    return conn


# ---- marking on filing ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001", outlook_categories=True)
    capacity.rebuild_all(conn, AT.date(), settings)
    prompts.write_defaults(fs, data_root)
    context = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: AT)
    yield context
    conn.close()


def unfiled_email_capture(ctx, entry_id: str = "E1") -> str:
    email = EmailItem("Crane booking", "Ann Example", "2026-10-07 09:15", "", "The crane is booked.", entry_id=entry_id, store_id="S1",
                      msg_bytes=build(FakeEmail()))
    r = save_capture(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, CaptureDraft(content="", files=email_rows(email)[:1]), AT)
    assert r.capture_id and not Model(ctx.conn).captures[r.capture_id].task
    return r.capture_id


def test_a_save_keeps_where_its_emails_are(ctx):
    cid = unfiled_email_capture(ctx)
    assert captures.email_places(ctx.conn, cid) == [("E1", "S1")]


def test_filing_an_unfiled_email_capture_marks_it_with_its_task(ctx, monkeypatch):
    cid = unfiled_email_capture(ctx)
    item = FakeItem()
    session = FakeSession({"E1": item})
    monkeypatch.setattr(outlook, "connect", lambda: (FakeApp(session), "fake"))
    monkeypatch.setattr(outlook, "list_separator", lambda: ",")
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    try:
        browse.file_to[cid] = RIGGING
        browse.file_capture(cid)
        assert item.Categories == "Rigging plan" and item.saved == 1 and session.asked == [("E1", "S1")]
        assert "Marked 1 email in Outlook with its task's name." in browse.status.text()
    finally:
        capture.deleteLater()
        browse.deleteLater()


def test_filing_with_marking_off_doesnt_touch_outlook(ctx, monkeypatch):
    ctx.settings.outlook_categories = False
    cid = unfiled_email_capture(ctx)
    monkeypatch.setattr(outlook, "connect", lambda: (_ for _ in ()).throw(AssertionError("Outlook was asked")))
    capture = CaptureWindow(ctx)
    browse = BrowseWindow(ctx, capture)
    try:
        browse.file_to[cid] = RIGGING
        browse.file_capture(cid)
        assert Model(ctx.conn).captures[cid].filed_to == RIGGING
    finally:
        capture.deleteLater()
        browse.deleteLater()


# ---- an email captured before ----
def test_a_second_drop_of_the_same_email_says_where_it_is(ctx, monkeypatch):
    monkeypatch.setattr(outlook, "selected_places", lambda: [])
    data = build(FakeEmail())
    w = CaptureWindow(ctx)
    try:
        w.show_capture()
        w.set_task(RIGGING)
        w.take_drop(DropRead([Dropped("Crane booking.msg", data, email=True)], outlook=True))
        assert w.item_cards.before_notes == []  # the first time: nothing to say
        w.save()
        w.show_capture()
        w.take_drop(DropRead([Dropped("Crane booking.msg", data, email=True)], outlook=True))
        notes = [n.text() for n in w.item_cards.before_notes]
        assert len(notes) == 1 and "is already captured on Rigging plan, " in notes[0] and "Open C0000" in notes[0]
        assert w.item_cards.isVisible() and len([e for e in w.files if e.row.email]) == 1  # it's taken all the same
        w.reset_draft()
        assert w.item_cards.before_notes == []
    finally:
        w.hide()
        w.deleteLater()


# ---- a size cap on what a drag hands over ----
class FakeDrag:
    """A drag whose list of files says one is 201 MB. Reading its contents fails the test."""

    def __init__(self, size: int) -> None:
        self.size = size

    def EnumFormatEtc(self, direction):  # noqa: N802 - OLE's name
        return []

    def GetData(self, formatetc):  # noqa: N802 - OLE's name
        if formatetc[3] != -1:
            raise AssertionError("the file's contents were read")
        entry = bytearray(drop_target.ENTRY)
        struct.pack_into("<I", entry, 0, drop_target.FD_FILESIZE)
        struct.pack_into("<II", entry, 64, self.size >> 32, self.size & 0xFFFFFFFF)
        name = "Turnaround video.mp4".encode("utf-16-le")
        entry[drop_target.NAME_AT:drop_target.NAME_AT + len(name)] = name

        class Medium:
            data = struct.pack("<I", 1) + bytes(entry)

        return Medium()


def test_a_drop_over_200_mb_is_refused_unread():
    found = drop_target.read(FakeDrag(201_000_000))
    assert found.items == [] and found.problems == ["Turnaround video.mp4 is 201 MB, over DocRepo's 200 MB for a dropped file, so it wasn't taken"]


def test_a_msg_file_over_the_cap_is_refused_unread(ctx, tmp_path, monkeypatch):
    big = tmp_path / "Huge.msg"
    big.write_bytes(b"x")
    monkeypatch.setattr(drop_target, "MAX_DROP", 0)
    from docrepo.ui import capture_window

    monkeypatch.setattr(capture_window, "MAX_DROP", 0)
    monkeypatch.setattr(capture_window, "read_msg_file", lambda path: (_ for _ in ()).throw(AssertionError("it was read")))
    w = CaptureWindow(ctx)
    try:
        w.show_capture()
        w.add_paths([str(big)])
        assert "over DocRepo's 200 MB" in w.error.text() and not w.files
    finally:
        w.hide()
        w.deleteLater()


def test_file_rows_still_take_a_path(ctx):
    assert FileRow("a.pdf", "C:\\Docs\\a.pdf").path  # a file from File Explorer is a path, copied later, never read whole here
